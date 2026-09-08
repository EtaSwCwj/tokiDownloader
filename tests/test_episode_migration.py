from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError
from functools import partial
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import toki_app
import toki_core
from toki_app import ControlError, ControlTimeoutError, build_parser, run_cli
from toki_core import (
    DownloadJob,
    episode_rename_job_snapshot,
    plan_episode_folder_rename,
    rename_episode_folders,
    save_jobs,
)


WORK_TITLE = "남녀비 139의 평행세계는 의외로 평범"

# Historical title-only migration remains covered explicitly; new default
# ordered migrations have their own end-to-end and archive integration tests.
plan_episode_folder_rename = partial(plan_episode_folder_rename, ordered=False)
rename_episode_folders = partial(rename_episode_folders, ordered=False)


class EpisodeFolderMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "jobs.db"
        self.path_patch = patch.object(toki_core, "JOB_DB_PATH", self.database_path)
        self.path_patch.start()
        toki_core._INITIALIZED_JOB_DBS.clear()
        toki_core._DATABASE_MIGRATION_REPORTS.clear()

    def tearDown(self) -> None:
        toki_core._INITIALIZED_JOB_DBS.clear()
        toki_core._DATABASE_MIGRATION_REPORTS.clear()
        self.path_patch.stop()
        self.temporary.cleanup()

    def make_work(
        self,
        folders: list[str],
        *,
        state: str = "완료",
        state_payload: dict | None = None,
        metadata_payload: dict | None = None,
        work_title: str = WORK_TITLE,
        output_folder_name: str | None = None,
    ) -> tuple[DownloadJob, Path]:
        output = self.root / "마나토끼" / (
            output_folder_name or f"[킷사][N／A] {work_title}"
        )
        output.mkdir(parents=True)
        for index, folder_name in enumerate(folders, start=1):
            episode = output / folder_name
            episode.mkdir()
            (episode / "image0000.jpg").write_bytes(f"image-{index}".encode())
        metadata = {"schemaVersion": 1, "title": work_title}
        metadata.update(metadata_payload or {})
        (output / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if state_payload is not None:
            (output / ".toki-state.json").write_text(
                json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        job = DownloadJob(
            job_id="episode-rename",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=str(self.root),
            output_path=str(output),
            title=work_title,
            state=state,
            site="manatoki",
        )
        save_jobs([job])
        return job, output

    def test_raw_source_title_and_work_title_are_compared_after_windows_sanitize(
        self,
    ) -> None:
        source_name = f"0001 {WORK_TITLE} 1화"
        raw_title = "남녀비 1:39의 평행세계는 의외로 평범 1화"
        state = {
            "version": 2,
            "completedEpisodes": [1],
            "episodes": [
                {
                    "number": 1,
                    "sourceId": "post-1",
                    "sourceTitle": raw_title,
                    "folderName": source_name,
                }
            ],
        }
        job, _output = self.make_work([source_name], state_payload=state)

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        mapping = plan["mappings"][0]
        self.assertEqual(mapping["suffix"], "1화")
        self.assertEqual(mapping["destinationFolderName"], f"{WORK_TITLE} 1화")
        self.assertEqual(mapping["destinationFolderName"].count(WORK_TITLE), 1)

    def test_suffix_extraction_matches_shared_node_cases(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "episode_suffix_cases.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))

        for item in cases:
            with self.subTest(item["name"]):
                suffix, source = toki_core._episode_rename_suffix(
                    item["sourceTitle"],
                    number=item["number"],
                    work_title=item["workTitle"],
                )
                self.assertEqual(source, item.get("expectedSource", "source_title"))
                self.assertEqual(suffix, item["expectedSuffix"])

    def test_contextual_suffix_plan_only_changes_matching_sibling_groups(
        self,
    ) -> None:
        suffixes = [
            "141화",
            "141.5화",
            "200화",
            "1~5화",
            "R-18 1화",
            "1.5화",
        ]

        decisions = toki_core._plan_contextual_episode_suffixes(suffixes)

        self.assertEqual(
            [item["suffix"] for item in decisions],
            [
                "141.0화",
                "141.5화",
                "200화",
                "1~5화",
                "R-18 1화",
                "1.5화",
            ],
        )
        self.assertTrue(decisions[0]["applied"])
        self.assertEqual(decisions[0]["reason"], "decimal_sibling")
        self.assertFalse(any(item["conflict"] for item in decisions))

    def test_contextual_suffix_plan_handles_hyphen_parts_without_guessing(
        self,
    ) -> None:
        suffixes = [
            "50화",
            "50 - 2화",
            "60화",
            "60-1화",
            "60-2화",
            "70화",
            "70.5화",
            "70-2화",
        ]

        decisions = toki_core._plan_contextual_episode_suffixes(suffixes)

        self.assertEqual(decisions[0]["suffix"], "50 - 1화")
        self.assertEqual(decisions[0]["reason"], "hyphen_part_sibling")
        self.assertTrue(decisions[2]["conflict"])
        self.assertEqual(
            decisions[2]["conflictCode"], "hyphen_part_one_already_exists"
        )
        self.assertIn("-1 회차가 이미", decisions[2]["conflictReason"])
        self.assertTrue(decisions[5]["conflict"])
        self.assertEqual(
            decisions[5]["conflictCode"], "mixed_decimal_hyphen_siblings"
        )
        self.assertEqual(decisions[5]["suffix"], "70화")
        self.assertEqual(
            [decisions[index]["suffix"] for index in (1, 3, 4, 6, 7)],
            ["50 - 2화", "60-1화", "60-2화", "70.5화", "70-2화"],
        )

    def test_contextual_suffix_plan_rejects_zero_decimal_and_mixed_hyphen_styles(
        self,
    ) -> None:
        suffixes = [
            "80화",
            "80-2화",
            "80 - 2화",
            "90화",
            "90.0화",
            "91화",
            "91.00화",
        ]

        decisions = toki_core._plan_contextual_episode_suffixes(suffixes)

        self.assertTrue(decisions[0]["conflict"])
        self.assertEqual(decisions[0]["conflictCode"], "ambiguous_hyphen_style")
        self.assertTrue(decisions[3]["conflict"])
        self.assertEqual(
            decisions[3]["conflictCode"], "decimal_zero_already_exists"
        )
        self.assertTrue(decisions[5]["conflict"])
        self.assertEqual(
            decisions[5]["conflictCode"], "decimal_zero_already_exists"
        )

    def test_duplicate_base_suffixes_are_safe_until_a_variant_requires_rewrite(
        self,
    ) -> None:
        unchanged = toki_core._plan_contextual_episode_suffixes(
            ["100화", "100화"]
        )
        demanded = toki_core._plan_contextual_episode_suffixes(
            ["101화", "101화", "101.5화"]
        )

        self.assertEqual([item["suffix"] for item in unchanged], ["100화", "100화"])
        self.assertFalse(any(item["conflict"] for item in unchanged))
        self.assertTrue(demanded[0]["conflict"])
        self.assertTrue(demanded[1]["conflict"])
        self.assertEqual(
            demanded[0]["conflictCode"],
            "duplicate_base_episode",
        )

    def test_r18_artifact_repair_is_gated_to_the_known_work(self) -> None:
        work_title = "전생한 용사의 기록"
        source_name = "0001 전생한 용사의 …8 용사 1화"
        job, _output = self.make_work(
            [source_name],
            state_payload=None,
            work_title=work_title,
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["mappings"][0]["suffix"], "8 용사 1화")
        self.assertNotIn("R-18", plan["mappings"][0]["destinationFolderName"])

    def test_non_numeric_full_suffixes_are_preserved_without_ordinal_fallback(
        self,
    ) -> None:
        folders = [
            f"0001 {WORK_TITLE} 프롤로그",
            f"0002 {WORK_TITLE} 공지 - 휴재 안내",
            "0003 남녀비 139의 …로 평범 여름 특별편",
        ]
        job, _output = self.make_work(folders, state_payload=None)

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["fallbackSuffixCount"], 0)
        self.assertEqual(plan["unsafeSuffixCount"], 0)
        self.assertEqual(
            [item["suffix"] for item in plan["mappings"]],
            ["프롤로그", "공지 - 휴재 안내", "여름 특별편"],
        )
        self.assertNotIn("1화", plan["mappings"][0]["destinationFolderName"])
        self.assertNotIn("2화", plan["mappings"][1]["destinationFolderName"])
        self.assertNotIn("3화", plan["mappings"][2]["destinationFolderName"])

    def test_missing_real_suffix_is_reported_unsafe_and_blocks_execution(self) -> None:
        source_name = f"0001 {WORK_TITLE}"
        job, output = self.make_work([source_name], state_payload=None)

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        self.assertEqual(plan["unsafeSuffixCount"], 1)
        self.assertEqual(plan["renameCount"], 0)
        mapping = plan["mappings"][0]
        self.assertEqual(mapping["suffix"], "")
        self.assertEqual(mapping["suffixSource"], "unsafe")
        self.assertEqual(mapping["destinationFolderName"], "")
        self.assertNotIn("1화", json.dumps(plan, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "신뢰할 수 있는 회차 접미사"):
            rename_episode_folders(job.job_id)
        self.assertTrue((output / source_name).is_dir())

    def test_utf16_component_length_blocks_emoji_heavy_folder_name(self) -> None:
        work_title = "😀" * 121
        source_name = "0001 짧은 목록 제목 1화"
        job, output = self.make_work(
            [source_name],
            state_payload=None,
            work_title=work_title,
            output_folder_name="[킷사][N／A] 짧은 작품 폴더",
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        self.assertEqual(plan["pathPolicy"]["encoding"], "utf-16")
        self.assertEqual(plan["conflicts"][0]["type"], "path_too_long")
        mapping = plan["mappings"][0]
        self.assertGreater(
            mapping["componentUtf16Units"],
            plan["pathPolicy"]["componentMaxUnits"],
        )
        self.assertTrue(mapping["componentTooLong"])
        self.assertTrue(mapping["pathTooLong"])
        self.assertTrue((output / source_name).is_dir())

    def test_full_destination_length_blocks_before_component_limit(self) -> None:
        work_title = "가" * 200
        source_name = "0001 짧은 목록 제목 1화"
        job, output = self.make_work(
            [source_name],
            state_payload=None,
            work_title=work_title,
            output_folder_name="[킷사][N／A] 짧은 작품 폴더",
        )

        plan = plan_episode_folder_rename(job.job_id)

        mapping = plan["mappings"][0]
        self.assertFalse(mapping["componentTooLong"])
        self.assertTrue(mapping["absolutePathTooLong"])
        self.assertGreater(
            mapping["destinationUtf16Units"],
            plan["pathPolicy"]["destinationMaxUnits"],
        )
        self.assertFalse(plan["canExecute"])
        self.assertTrue((output / source_name).is_dir())

    def test_state_mapping_precedes_strict_legacy_prefix_detection(self) -> None:
        mapped_folder = "2024 특별편"
        ignored_folder = "12 참고자료"
        state = {
            "version": 2,
            "completedEpisodes": [7],
            "episodes": [
                {
                    "number": 7,
                    "sourceId": "special-2024",
                    "sourceTitle": "특별편",
                    "folderName": mapped_folder,
                }
            ],
        }
        job, _output = self.make_work(
            [mapped_folder, ignored_folder],
            state_payload=state,
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["folderCount"], 1)
        self.assertEqual(plan["mappings"][0]["number"], 7)
        self.assertEqual(plan["mappings"][0]["sourceDiscovery"], "state")
        self.assertEqual(plan["mappings"][0]["sourceFolderName"], mapped_folder)

    def test_heuristic_legacy_scan_requires_old_downloader_image_evidence(self) -> None:
        legacy_folder = f"0001 {WORK_TITLE} 1화"
        job, output = self.make_work(
            [legacy_folder],
            state_payload={"version": 1, "completedEpisodes": [1]},
        )
        personal_notes = output / "2024 개인 메모"
        personal_notes.mkdir()
        (personal_notes / "note.txt").write_text("keep", encoding="utf-8")

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["folderCount"], 1)
        self.assertEqual(plan["mappings"][0]["sourceFolderName"], legacy_folder)
        self.assertNotIn(
            personal_notes.name,
            {item["sourceFolderName"] for item in plan["mappings"]},
        )

    def test_single_stale_ordinal_record_does_not_claim_a_different_legacy_title(
        self,
    ) -> None:
        legacy_folder = f"0001 {WORK_TITLE} 새 1화"
        stale_id = "/manhwa/34360/old-special"
        job, _output = self.make_work(
            [legacy_folder],
            state_payload={
                "version": 2,
                "completedEpisodes": [1],
                "completedEpisodeIds": [stale_id],
                "episodes": [
                    {
                        "number": 1,
                        "sourceId": stale_id,
                        "sourceUrl": f"https://newtoki1.org{stale_id}",
                        "sourceTitle": f"{WORK_TITLE} 과거 특별편",
                        "displayTitle": f"{WORK_TITLE} 과거 특별편",
                        "folderName": f"{WORK_TITLE} 과거 특별편",
                    }
                ],
            },
        )

        plan = plan_episode_folder_rename(job.job_id)

        mapping = plan["mappings"][0]
        self.assertTrue(plan["canExecute"])
        self.assertFalse(mapping["identityTrusted"])
        self.assertEqual(mapping["sourceId"], "")
        self.assertEqual(mapping["sourceTitle"], f"{WORK_TITLE} 새 1화")
        self.assertEqual(mapping["destinationFolderName"], f"{WORK_TITLE} 새 1화")
        self.assertIn(stale_id, {item["sourceId"] for item in plan["episodes"]})

    def test_html_entities_match_a_single_manifest_identity_during_migration(
        self,
    ) -> None:
        self.assertEqual(toki_core._episode_rename_legacy_title_text("&#65;"), "A")
        self.assertEqual(
            toki_core._episode_rename_legacy_title_text("&#٦٥;"),
            "&#٦٥;",
        )
        self.assertTrue(
            toki_core._episode_rename_titles_match(
                "작품 & 이름 특별편",
                "<em>작품 &amp; 이름</em> &#xD2B9;&#48324;&#54200;",
                1,
            )
        )
        self.assertFalse(
            toki_core._episode_rename_titles_match(
                "작품 A 특별편",
                "<custom>작품 A</custom> 특별편",
                1,
            )
        )
        work_title = "작품 & 이름"
        legacy_folder = "0001 작품 &amp; 이름 1화"
        source_id = "/manhwa/9000/episode-1"
        job, _output = self.make_work(
            [legacy_folder],
            work_title=work_title,
            state_payload={
                "version": 2,
                "completedEpisodes": [1],
                "completedEpisodeIds": [source_id],
                "episodes": [
                    {
                        "number": 1,
                        "sourceId": source_id,
                        "sourceUrl": f"https://newtoki1.org{source_id}",
                        "sourceTitle": f"{work_title} 1화",
                        "displayTitle": f"{work_title} 1화",
                        "folderName": "현재 없는 이전 폴더",
                    }
                ],
            },
        )

        plan = plan_episode_folder_rename(job.job_id)

        mapping = plan["mappings"][0]
        self.assertTrue(plan["canExecute"])
        self.assertTrue(mapping["identityTrusted"])
        self.assertEqual(mapping["sourceId"], source_id)
        self.assertEqual(mapping["sourceTitle"], f"{work_title} 1화")
        self.assertEqual(mapping["destinationFolderName"], f"{work_title} 1화")

    def test_html_entity_legacy_title_is_decoded_without_a_manifest_record(
        self,
    ) -> None:
        work_title = "작품 & 이름"
        legacy_folder = "0001 작품 &amp; 이름 1화"
        job, _output = self.make_work(
            [legacy_folder],
            work_title=work_title,
            state_payload={"version": 1, "completedEpisodes": [1]},
        )

        plan = plan_episode_folder_rename(job.job_id)

        mapping = plan["mappings"][0]
        self.assertTrue(plan["canExecute"])
        self.assertFalse(mapping["identityTrusted"])
        self.assertEqual(mapping["sourceId"], "")
        self.assertEqual(mapping["suffix"], "1화")
        self.assertEqual(mapping["destinationFolderName"], f"{work_title} 1화")

    def test_distinct_state_mappings_may_share_an_ordinal(self) -> None:
        folders = ["프롤로그", "제1화"]
        state = {
            "version": 2,
            "completedEpisodes": [1],
            "episodes": [
                {
                    "number": 1,
                    "sourceId": "prologue",
                    "sourceTitle": "프롤로그",
                    "folderName": "프롤로그",
                },
                {
                    "number": 1,
                    "sourceId": "episode-1",
                    "sourceTitle": "제1화",
                    "folderName": "제1화",
                },
                {
                    "number": 1,
                    "sourceId": "stale-shifted",
                    "sourceTitle": "이전 순번 기록",
                    "folderName": "현재 없는 이전 폴더",
                },
            ],
        }
        job, _output = self.make_work(folders, state_payload=state)

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["duplicateNumbers"], [])
        self.assertEqual(plan["folderCount"], 2)
        self.assertEqual({item["number"] for item in plan["mappings"]}, {1})
        self.assertEqual(len(plan["episodes"]), 3)
        self.assertIn(
            "stale-shifted",
            {item.get("sourceId") for item in plan["episodes"]},
        )

    def test_v2_explicit_completion_ids_are_not_inflated_by_shared_ordinal(
        self,
    ) -> None:
        records = [
            {
                "number": 1,
                "sourceId": "prologue",
                "sourceUrl": "https://newtoki1.org/manhwa/34360/prologue",
                "sourceTitle": "프롤로그",
                "displayTitle": "프롤로그",
                "folderName": "프롤로그",
            },
            {
                "number": 1,
                "sourceId": "episode-1",
                "sourceUrl": "https://newtoki1.org/manhwa/34360/episode-1",
                "sourceTitle": "제1화",
                "displayTitle": "제1화",
                "folderName": "제1화",
            },
        ]
        job, output = self.make_work(
            [item["folderName"] for item in records],
            state_payload={
                "version": 2,
                "completedEpisodes": [1],
                "completedEpisodeIds": ["prologue"],
                "episodes": records,
            },
        )

        rename_episode_folders(job.job_id)

        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["completedEpisodes"], [1])
        self.assertEqual(state["completedEpisodeIds"], ["prologue"])

    def test_v1_numeric_completion_promotes_one_trusted_manifest_identity(self) -> None:
        source_name = f"0007 {WORK_TITLE} 보너스편"
        source_id = "/manhwa/34360/bonus-7"
        record = {
            "number": 7,
            "sourceId": source_id,
            "sourceUrl": f"https://newtoki1.org{source_id}",
            "sourceTitle": f"{WORK_TITLE} 보너스편",
            "displayTitle": f"{WORK_TITLE} 보너스편",
            "folderName": source_name,
        }
        job, output = self.make_work(
            [source_name],
            state_payload={"version": 1, "completedEpisodes": [7]},
            metadata_payload={"episodes": [record]},
        )

        rename_episode_folders(job.job_id)

        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["completedEpisodes"], [7])
        self.assertEqual(state["completedEpisodeIds"], [source_id])

    def test_v1_numeric_completion_does_not_promote_ambiguous_shared_ordinal(
        self,
    ) -> None:
        records = [
            {
                "number": 1,
                "sourceId": "prologue",
                "sourceUrl": "https://newtoki1.org/manhwa/34360/prologue",
                "sourceTitle": "프롤로그",
                "displayTitle": "프롤로그",
                "folderName": "프롤로그",
            },
            {
                "number": 1,
                "sourceId": "episode-1",
                "sourceUrl": "https://newtoki1.org/manhwa/34360/episode-1",
                "sourceTitle": "제1화",
                "displayTitle": "제1화",
                "folderName": "제1화",
            },
        ]
        job, output = self.make_work(
            [item["folderName"] for item in records],
            state_payload={"version": 1, "completedEpisodes": [1]},
            metadata_payload={"episodes": records},
        )

        rename_episode_folders(job.job_id)

        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["completedEpisodes"], [1])
        self.assertEqual(state["completedEpisodeIds"], [])

    def test_legacy_folder_claims_unique_same_ordinal_manifest_identity(self) -> None:
        legacy_folder = "0001 남녀비 139의 …로 평범 1화"
        target_folder = f"{WORK_TITLE} 1화"
        records = [
            {
                "number": 1,
                "sourceId": "episode-current",
                "sourceUrl": "https://newtoki1.org/manhwa/34360/current",
                "sourceTitle": target_folder,
                "displayTitle": target_folder,
                "folderName": target_folder,
            },
            {
                "number": 1,
                "sourceId": "episode-stale",
                "sourceUrl": "https://newtoki1.org/manhwa/34360/stale",
                "sourceTitle": "과거 특별편",
                "displayTitle": "과거 특별편",
                "folderName": "현재 없는 과거 특별편",
            },
        ]
        job, _output = self.make_work(
            [legacy_folder],
            state_payload={
                "version": 2,
                "completedEpisodes": [1],
                "completedEpisodeIds": [item["sourceId"] for item in records],
                "episodes": records,
            },
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertTrue(plan["manifestValid"])
        self.assertEqual(plan["mappings"][0]["sourceId"], "episode-current")
        self.assertEqual(len(plan["episodes"]), 2)
        self.assertEqual(
            len({item["folderName"].casefold() for item in plan["episodes"]}),
            2,
        )

    def test_ambiguous_same_ordinal_manifest_folder_conflict_blocks_execution(
        self,
    ) -> None:
        legacy_folder = "0001 남녀비 139의 …로 평범 1화"
        target_folder = f"{WORK_TITLE} 1화"
        records = [
            {
                "number": 1,
                "sourceId": f"episode-{index}",
                "sourceUrl": f"https://newtoki1.org/manhwa/34360/{index}",
                "sourceTitle": target_folder,
                "displayTitle": target_folder,
                "folderName": target_folder,
            }
            for index in (1, 2)
        ]
        job, output = self.make_work(
            [legacy_folder],
            state_payload={
                "version": 2,
                "completedEpisodes": [1],
                "completedEpisodeIds": [item["sourceId"] for item in records],
                "episodes": records,
            },
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        self.assertFalse(plan["manifestValid"])
        self.assertIn("manifest_invalid", {item["type"] for item in plan["conflicts"]})
        with self.assertRaisesRegex(ValueError, "manifest"):
            rename_episode_folders(job.job_id)
        self.assertTrue((output / legacy_folder).is_dir())
        self.assertFalse((output / target_folder).exists())

    def test_plan_is_read_only_and_preserves_full_episode_suffix(self) -> None:
        source_name = "0001 남녀비 139의 …로 평범 1~5화"
        job, output = self.make_work([source_name], state_payload=None)

        result = plan_episode_folder_rename(job.job_id)

        target_name = f"{WORK_TITLE} 1~5화"
        self.assertTrue(result["dryRun"])
        self.assertFalse(result["executed"])
        self.assertTrue(result["canExecute"])
        self.assertEqual(result["renameCount"], 1)
        self.assertEqual(result["conflictCount"], 0)
        self.assertEqual(result["mappings"][0]["destinationFolderName"], target_name)
        self.assertNotIn("…", target_name)
        self.assertTrue((output / source_name).is_dir())
        self.assertFalse((output / target_name).exists())
        self.assertFalse(Path(result["stateBackupPath"]).exists())
        self.assertFalse(Path(result["metadataBackupPath"]).exists())

    def test_modern_integer_folder_with_decimal_sibling_migrates_idempotently(
        self,
    ) -> None:
        source_name = f"{WORK_TITLE} 141화"
        decimal_name = f"{WORK_TITLE} 141.5화"
        target_name = f"{WORK_TITLE} 141.0화"
        records = [
            {
                "number": number,
                "sourceId": source_id,
                "sourceUrl": f"https://newtoki1.org{source_id}",
                "sourceTitle": folder_name,
                "displayTitle": folder_name,
                "folderName": folder_name,
            }
            for number, source_id, folder_name in (
                (141, "/manhwa/34360/episode-141", source_name),
                (142, "/manhwa/34360/episode-141-5", decimal_name),
            )
        ]
        job, output = self.make_work(
            [source_name, decimal_name],
            state_payload={
                "version": 2,
                "completedEpisodes": [141, 142],
                "completedEpisodeIds": [item["sourceId"] for item in records],
                "episodes": records,
            },
            metadata_payload={"episodes": records},
        )
        original_image = (output / source_name / "image0000.jpg").read_bytes()

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["folderCount"], 2)
        self.assertEqual(plan["renameCount"], 1)
        self.assertEqual(plan["unchangedCount"], 1)
        mappings = {item["sourceFolderName"]: item for item in plan["mappings"]}
        self.assertEqual(mappings[source_name]["sourceDiscovery"], "state")
        self.assertEqual(mappings[source_name]["suffix"], "141.0화")
        self.assertTrue(mappings[source_name]["contextualSuffixApplied"])
        self.assertEqual(
            mappings[source_name]["contextualSuffixReason"], "decimal_sibling"
        )
        self.assertEqual(mappings[source_name]["destinationFolderName"], target_name)
        self.assertEqual(mappings[decimal_name]["destinationFolderName"], decimal_name)
        self.assertFalse(mappings[decimal_name]["contextualSuffixApplied"])

        result = rename_episode_folders(job.job_id)

        self.assertEqual(result["renamedCount"], 1)
        self.assertFalse((output / source_name).exists())
        self.assertTrue((output / decimal_name).is_dir())
        self.assertEqual(
            (output / target_name / "image0000.jpg").read_bytes(),
            original_image,
        )
        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(state["completedEpisodes"], [141, 142])
        self.assertEqual(
            state["completedEpisodeIds"],
            sorted(item["sourceId"] for item in records),
        )
        episodes = {item["sourceId"]: item for item in state["episodes"]}
        base_episode = episodes[records[0]["sourceId"]]
        decimal_episode = episodes[records[1]["sourceId"]]
        self.assertEqual(base_episode["sourceTitle"], source_name)
        self.assertEqual(base_episode["displayTitle"], target_name)
        self.assertEqual(base_episode["folderName"], target_name)
        self.assertEqual(decimal_episode["folderName"], decimal_name)
        self.assertEqual(metadata["episodes"], state["episodes"])

        repeated = rename_episode_folders(job.job_id)
        self.assertEqual(repeated["renamedCount"], 0)
        self.assertTrue((output / target_name).is_dir())

    def test_modern_base_with_second_part_migrates_to_first_part_idempotently(
        self,
    ) -> None:
        source_name = f"{WORK_TITLE} 88화"
        second_name = f"{WORK_TITLE} 88 - 2화"
        target_name = f"{WORK_TITLE} 88 - 1화"
        records = [
            {
                "number": number,
                "sourceId": source_id,
                "sourceTitle": folder_name,
                "displayTitle": folder_name,
                "folderName": folder_name,
            }
            for number, source_id, folder_name in (
                (88, "episode-88", source_name),
                (89, "episode-88-part-2", second_name),
            )
        ]
        job, output = self.make_work(
            [source_name, second_name],
            state_payload={
                "version": 2,
                "completedEpisodes": [88, 89],
                "completedEpisodeIds": [item["sourceId"] for item in records],
                "episodes": records,
            },
            metadata_payload={"episodes": records},
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["renameCount"], 1)
        mappings = {item["sourceFolderName"]: item for item in plan["mappings"]}
        self.assertEqual(mappings[source_name]["destinationFolderName"], target_name)
        self.assertEqual(
            mappings[source_name]["contextualSuffixReason"],
            "hyphen_part_sibling",
        )
        self.assertEqual(mappings[second_name]["destinationFolderName"], second_name)

        rename_episode_folders(job.job_id)

        self.assertFalse((output / source_name).exists())
        self.assertTrue((output / target_name).is_dir())
        self.assertTrue((output / second_name).is_dir())
        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {item["sourceId"]: item["folderName"] for item in state["episodes"]},
            {"episode-88": target_name, "episode-88-part-2": second_name},
        )
        repeated = plan_episode_folder_rename(job.job_id)
        self.assertTrue(repeated["canExecute"])
        self.assertEqual(repeated["renameCount"], 0)

    def test_contextual_suffix_conflict_blocks_mixed_decimal_and_hyphen_rules(
        self,
    ) -> None:
        folders = [
            f"{WORK_TITLE} 70화",
            f"{WORK_TITLE} 70.5화",
            f"{WORK_TITLE} 70-2화",
        ]
        records = [
            {
                "number": index,
                "sourceId": f"episode-70-{index}",
                "sourceTitle": folder_name,
                "folderName": folder_name,
            }
            for index, folder_name in enumerate(folders, start=1)
        ]
        job, output = self.make_work(
            folders,
            state_payload={"version": 2, "episodes": records},
            metadata_payload={"episodes": records},
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        self.assertEqual(plan["unsafeSuffixCount"], 1)
        self.assertIn(
            "contextual_suffix_conflict",
            {item["type"] for item in plan["conflicts"]},
        )
        base = next(
            item for item in plan["mappings"] if item["sourceFolderName"] == folders[0]
        )
        self.assertTrue(base["contextualSuffixConflict"])
        self.assertEqual(
            base["contextualSuffixConflictCode"],
            "mixed_decimal_hyphen_siblings",
        )
        self.assertEqual(base["destinationFolderName"], "")
        with self.assertRaisesRegex(ValueError, "신뢰할 수 있는 회차 접미사"):
            rename_episode_folders(job.job_id)
        self.assertTrue(all((output / folder_name).is_dir() for folder_name in folders))

    def test_contextual_suffix_target_that_already_exists_is_a_conflict(self) -> None:
        folders = [f"{WORK_TITLE} 71화", f"{WORK_TITLE} 71.5화"]
        target_name = f"{WORK_TITLE} 71.0화"
        records = [
            {
                "number": index,
                "sourceId": f"episode-71-{index}",
                "sourceTitle": folder_name,
                "folderName": folder_name,
            }
            for index, folder_name in enumerate(folders, start=1)
        ]
        job, output = self.make_work(
            folders,
            state_payload={"version": 2, "episodes": records},
            metadata_payload={"episodes": records},
        )
        existing_target = output / target_name
        existing_target.mkdir()
        (existing_target / "keep.txt").write_text("keep", encoding="utf-8")

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        base = next(
            item for item in plan["mappings"] if item["sourceFolderName"] == folders[0]
        )
        self.assertEqual(base["destinationFolderName"], target_name)
        self.assertTrue(base["conflict"])
        self.assertFalse(base["duplicateTarget"])
        self.assertIn(
            "path_conflict",
            {item["type"] for item in plan["conflicts"]},
        )
        with self.assertRaises(FileExistsError):
            rename_episode_folders(job.job_id)
        self.assertTrue(all((output / folder_name).is_dir() for folder_name in folders))
        self.assertEqual((existing_target / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_explicit_decimal_zero_sibling_is_a_contextual_conflict(self) -> None:
        folders = [f"{WORK_TITLE} 72화", f"{WORK_TITLE} 72.00화"]
        records = [
            {
                "number": index,
                "sourceId": f"episode-72-{index}",
                "sourceTitle": folder_name,
                "folderName": folder_name,
            }
            for index, folder_name in enumerate(folders, start=1)
        ]
        job, output = self.make_work(
            folders,
            state_payload={"version": 2, "episodes": records},
            metadata_payload={"episodes": records},
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        base = next(
            item for item in plan["mappings"] if item["sourceFolderName"] == folders[0]
        )
        self.assertTrue(base["contextualSuffixConflict"])
        self.assertEqual(
            base["contextualSuffixConflictCode"],
            "decimal_zero_already_exists",
        )
        self.assertEqual(base["destinationFolderName"], "")
        self.assertIn(
            "contextual_suffix_conflict",
            {item["type"] for item in plan["conflicts"]},
        )
        with self.assertRaisesRegex(ValueError, "신뢰할 수 있는 회차 접미사"):
            rename_episode_folders(job.job_id)
        self.assertTrue(all((output / folder_name).is_dir() for folder_name in folders))

    def test_snapshot_plan_never_reads_or_changes_jobs_database(self) -> None:
        source_name = "0001 남녀비 139의 …로 평범 1~5화"
        job, _output = self.make_work([source_name], state_payload=None)
        snapshot = episode_rename_job_snapshot(job)
        before_bytes = self.database_path.read_bytes()
        before_mtime = self.database_path.stat().st_mtime_ns

        with patch(
            "toki_core.load_job_by_id",
            side_effect=AssertionError("snapshot plan must not read jobs.db"),
        ):
            plan = plan_episode_folder_rename(
                job.job_id,
                job_snapshot=snapshot,
            )

        self.assertTrue(plan["canExecute"])
        self.assertEqual(self.database_path.read_bytes(), before_bytes)
        self.assertEqual(self.database_path.stat().st_mtime_ns, before_mtime)
        with self.assertRaises(FrozenInstanceError):
            snapshot.title = "변경 금지"

    def test_plan_preserves_distinguishing_suffixes_from_truncated_titles(self) -> None:
        folders = [
            "0001 남녀비 139의 …범 R-18 1화",
            "0002 남녀비 139의 …-18 미쿠 1화",
            "0003 남녀비 139의 …8 카나리아 1화",
            "0004 남녀비 139의 …18 히나타 1화",
            "0005 남녀비 139의 …평범 히나타 3화",
        ]
        job, _output = self.make_work(folders, state_payload=None)

        result = plan_episode_folder_rename(job.job_id)

        self.assertTrue(result["canExecute"])
        self.assertEqual(result["conflictCount"], 0)
        self.assertEqual(
            [item["suffix"] for item in result["mappings"]],
            [
                "R-18 1화",
                "R-18 미쿠 1화",
                "R-18 카나리아 1화",
                "R-18 히나타 1화",
                "히나타 3화",
            ],
        )
        self.assertEqual(
            len({item["destinationFolderName"] for item in result["mappings"]}),
            5,
        )

    def test_existing_destination_blocks_execution_without_changes(self) -> None:
        source_name = f"0001 {WORK_TITLE} 1화"
        job, output = self.make_work([source_name], state_payload=None)
        target = output / f"{WORK_TITLE} 1화"
        target.mkdir()

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        self.assertEqual(plan["conflictCount"], 1)
        with self.assertRaises(FileExistsError):
            rename_episode_folders(job.job_id)
        self.assertTrue((output / source_name).is_dir())
        self.assertTrue(target.is_dir())

    def test_execute_renames_only_folders_and_updates_state_v2_and_metadata(self) -> None:
        source_name = "0001 남녀비 139의 …-18 미쿠 1화"
        original_state = {
            "version": 2,
            "completedEpisodes": [1],
            "completedEpisodeIds": ["post-1001"],
            "episodes": [
                {
                    "number": 1,
                    "sourceId": "post-1001",
                    "sourceUrl": "https://newtoki1.org/manhwa/34360/1001",
                    "sourceTitle": "남녀비 139의 …-18 미쿠 1화",
                    "displayTitle": "",
                    "folderName": source_name,
                }
            ],
        }
        job, output = self.make_work([source_name], state_payload=original_state)
        source_image = output / source_name / "image0000.jpg"
        image_bytes = source_image.read_bytes()

        result = rename_episode_folders(job.job_id)

        target_name = f"{WORK_TITLE} R-18 미쿠 1화"
        target_image = output / target_name / "image0000.jpg"
        self.assertTrue(result["executed"])
        self.assertEqual(result["renamedCount"], 1)
        self.assertFalse((output / source_name).exists())
        self.assertEqual(target_image.read_bytes(), image_bytes)
        self.assertTrue(result["stateBackupCreated"])
        self.assertTrue(result["metadataBackupCreated"])
        self.assertEqual(
            json.loads(Path(result["stateBackupPath"]).read_text(encoding="utf-8")),
            original_state,
        )

        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(state["version"], 2)
        self.assertEqual(state["completedEpisodes"], [1])
        self.assertEqual(state["completedEpisodeIds"], ["post-1001"])
        episode = state["episodes"][0]
        self.assertEqual(episode["sourceId"], "post-1001")
        self.assertEqual(
            episode["sourceUrl"], "https://newtoki1.org/manhwa/34360/1001"
        )
        self.assertEqual(episode["sourceTitle"], original_state["episodes"][0]["sourceTitle"])
        self.assertEqual(episode["displayTitle"], target_name)
        self.assertEqual(episode["folderName"], target_name)
        self.assertEqual(metadata["episodes"], state["episodes"])
        self.assertEqual(metadata["episodeFolderNaming"]["mode"], "title_suffix")

        repeated = plan_episode_folder_rename(job.job_id)
        self.assertTrue(repeated["canExecute"])
        self.assertEqual(repeated["renameCount"], 0)
        self.assertEqual(repeated["unchangedCount"], 1)

    def test_zero_rename_execute_preserves_inferred_numbers_in_state_and_metadata(
        self,
    ) -> None:
        current_title = f"{WORK_TITLE} 특별편"
        stale_title = f"{WORK_TITLE} 과거 특별편"
        state_payload = {
            "version": 2,
            "completedEpisodes": [1],
            "completedEpisodeIds": ["current"],
            "episodes": [
                {
                    "number": 1,
                    "numberInferred": True,
                    "sourceId": "current",
                    "sourceUrl": "https://newtoki1.org/manhwa/34360/current",
                    "sourceTitle": current_title,
                    "displayTitle": current_title,
                    "folderName": current_title,
                },
                {
                    "number": 2,
                    "numberInferred": True,
                    "sourceId": "stale",
                    "sourceUrl": "https://newtoki1.org/manhwa/34360/stale",
                    "sourceTitle": stale_title,
                    "displayTitle": stale_title,
                    "folderName": stale_title,
                },
            ],
        }
        job, output = self.make_work(
            [current_title],
            state_payload=state_payload,
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        self.assertEqual(plan["renameCount"], 0)
        self.assertEqual(plan["unchangedCount"], 1)
        self.assertTrue(plan["mappings"][0]["numberInferred"])
        self.assertEqual(
            {item["sourceId"]: item.get("numberInferred") for item in plan["episodes"]},
            {"current": True, "stale": True},
        )

        result = rename_episode_folders(job.job_id)

        self.assertTrue(result["executed"])
        self.assertEqual(result["renamedCount"], 0)
        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {
                item["sourceId"]: item.get("numberInferred")
                for item in state["episodes"]
            },
            {"current": True, "stale": True},
        )
        self.assertEqual(metadata["episodes"], state["episodes"])

    def test_legacy_prefix_discovery_clears_an_inferred_number_flag(self) -> None:
        modern_title = f"{WORK_TITLE} 특별편"
        legacy_folder = f"0001 {modern_title}"
        source_id = "/manhwa/34360/special"
        job, _output = self.make_work(
            [legacy_folder],
            state_payload={
                "version": 2,
                "completedEpisodes": [1],
                "completedEpisodeIds": [source_id],
                "episodes": [
                    {
                        "number": 1,
                        "numberInferred": True,
                        "sourceId": source_id,
                        "sourceUrl": f"https://newtoki1.org{source_id}",
                        "sourceTitle": modern_title,
                        "displayTitle": modern_title,
                        "folderName": "현재 없는 이전 폴더",
                    }
                ],
            },
        )

        plan = plan_episode_folder_rename(job.job_id)

        self.assertTrue(plan["canExecute"])
        mapping = plan["mappings"][0]
        self.assertEqual(mapping["sourceDiscovery"], "legacy_prefix")
        self.assertTrue(mapping["identityTrusted"])
        self.assertEqual(mapping["sourceId"], source_id)
        self.assertFalse(mapping["numberInferred"])
        episode = next(
            item for item in plan["episodes"] if item["sourceId"] == source_id
        )
        self.assertNotIn("numberInferred", episode)

    def test_metadata_manifest_preserves_identity_when_state_is_missing(self) -> None:
        source_name = "0001 남녀비 139의 …로 평범 특별편"
        metadata_episode = {
            "number": 1,
            "sourceId": "/manhwa/34360/metadata-special",
            "sourceUrl": "https://newtoki1.org/manhwa/34360/metadata-special",
            "sourceTitle": "남녀비 139의 …로 평범 특별편",
            "displayTitle": "",
            "folderName": source_name,
        }
        job, output = self.make_work(
            [source_name],
            state_payload=None,
            metadata_payload={"episodes": [metadata_episode]},
        )

        plan = plan_episode_folder_rename(job.job_id)
        self.assertEqual(plan["mappings"][0]["sourceId"], metadata_episode["sourceId"])
        self.assertEqual(plan["mappings"][0]["sourceUrl"], metadata_episode["sourceUrl"])
        rename_episode_folders(job.job_id)

        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["completedEpisodes"], [])
        self.assertEqual(state["completedEpisodeIds"], [])
        self.assertEqual(state["episodes"][0]["sourceId"], metadata_episode["sourceId"])
        self.assertEqual(state["episodes"][0]["sourceUrl"], metadata_episode["sourceUrl"])

    def test_metadata_manifest_supplements_a_partial_state_record(self) -> None:
        source_name = "0007 남녀비 139의 …로 평범 보너스편"
        source_id = "/manhwa/34360/metadata-bonus"
        source_url = "https://newtoki1.org/manhwa/34360/metadata-bonus"
        job, output = self.make_work(
            [source_name],
            state_payload={
                "version": 2,
                "completedEpisodes": [7],
                "completedEpisodeIds": [source_id],
                "episodes": [{"sourceId": source_id}],
            },
            metadata_payload={
                "episodes": [
                    {
                        "number": 7,
                        "sourceId": source_id,
                        "sourceUrl": source_url,
                        "sourceTitle": "남녀비 139의 …로 평범 보너스편",
                        "displayTitle": "",
                        "folderName": source_name,
                    }
                ]
            },
        )

        result = rename_episode_folders(job.job_id)

        self.assertTrue(result["executed"])
        state = json.loads((output / ".toki-state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["episodes"]), 1)
        self.assertEqual(state["episodes"][0]["number"], 7)
        self.assertEqual(state["episodes"][0]["sourceId"], source_id)
        self.assertEqual(state["episodes"][0]["sourceUrl"], source_url)

    def test_active_job_is_rejected_before_touching_folders(self) -> None:
        source_name = "0001 짧은 제목 1화"
        job, output = self.make_work(
            [source_name], state="실행 중", state_payload=None
        )

        with self.assertRaisesRegex(ValueError, "대기 또는 실행 중"):
            plan_episode_folder_rename(job.job_id)

        self.assertTrue((output / source_name).is_dir())
        self.assertEqual(list(output.glob("*.bak")), [])

    def test_second_phase_failure_rolls_all_folder_names_back(self) -> None:
        folders = ["0001 짧은 제목 1화", "0002 짧은 제목 2화"]
        original_state = {"version": 1, "completedEpisodes": [1, 2]}
        job, output = self.make_work(folders, state_payload=original_state)
        original_replace = os.replace
        failure_injected = False

        def fail_once(source: str | Path, destination: str | Path) -> None:
            nonlocal failure_injected
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                not failure_injected
                and source_path.is_dir()
                and source_path.name.startswith(".toki-episode-rename-")
                and destination_path.name == f"{WORK_TITLE} 짧은 제목 2화"
            ):
                failure_injected = True
                raise OSError("injected second-phase failure")
            original_replace(source, destination)

        with patch.object(toki_core.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "injected"):
                rename_episode_folders(job.job_id)

        self.assertTrue(all((output / name).is_dir() for name in folders))
        self.assertFalse((output / f"{WORK_TITLE} 1화").exists())
        self.assertFalse((output / f"{WORK_TITLE} 2화").exists())
        self.assertEqual(
            json.loads((output / ".toki-state.json").read_text(encoding="utf-8")),
            original_state,
        )
        self.assertEqual(list(output.glob(".toki-episode-rename-*")), [])

    def test_rollback_failure_is_persisted_and_blocks_the_next_plan(self) -> None:
        folders = ["0001 짧은 제목 1화", "0002 짧은 제목 2화"]
        job, output = self.make_work(
            folders,
            state_payload={"version": 1, "completedEpisodes": [1, 2]},
        )
        original_replace = os.replace
        phase_failure_injected = False

        def fail_phase_and_rollback(
            source: str | Path,
            destination: str | Path,
        ) -> None:
            nonlocal phase_failure_injected
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                not phase_failure_injected
                and source_path.is_dir()
                and source_path.name.startswith(".toki-episode-rename-")
                and destination_path.name == f"{WORK_TITLE} 짧은 제목 2화"
            ):
                phase_failure_injected = True
                raise OSError("injected phase failure")
            if (
                phase_failure_injected
                and source_path.name == f"{WORK_TITLE} 짧은 제목 1화"
                and destination_path.name == folders[0]
            ):
                raise OSError("injected rollback failure")
            original_replace(source, destination)

        with patch.object(toki_core.os, "replace", side_effect=fail_phase_and_rollback):
            with self.assertRaisesRegex(RuntimeError, "원위치 복구가 모두 실패"):
                rename_episode_folders(job.job_id)

        transaction_files = list(output.glob(".toki-episode-rename-*.json"))
        self.assertEqual(len(transaction_files), 1)
        transaction = json.loads(transaction_files[0].read_text(encoding="utf-8"))
        self.assertEqual(transaction["status"], "rollback_failed")
        self.assertTrue(transaction["rollbackErrors"])

        plan = plan_episode_folder_rename(job.job_id)
        self.assertFalse(plan["canExecute"])
        self.assertTrue(plan["recoveryRequired"])
        self.assertEqual(plan["conflicts"][0]["type"], "recovery_required")
        recovery = plan["recovery"]
        self.assertGreaterEqual(recovery["artifactCount"], 1)
        self.assertEqual(recovery["transactionFiles"][0]["status"], "rollback_failed")
        locations = recovery["transactionFiles"][0]["entries"]
        self.assertTrue(any(item["targetExists"] for item in locations))
        with self.assertRaisesRegex(RuntimeError, "복구 자료가 남아"):
            rename_episode_folders(job.job_id)

    def test_orphan_temporary_folder_is_never_hidden(self) -> None:
        source_name = f"0001 {WORK_TITLE} 1화"
        job, output = self.make_work([source_name], state_payload=None)
        orphan = output / (".toki-episode-rename-" + "a" * 32 + "-0001")
        orphan.mkdir()

        plan = plan_episode_folder_rename(job.job_id)

        self.assertFalse(plan["canExecute"])
        self.assertTrue(plan["recoveryRequired"])
        self.assertEqual(plan["recovery"]["temporaryFolders"], [str(orphan.resolve())])
        self.assertEqual(plan["renameCount"], 0)

    def test_cli_defaults_to_plan_and_execute_requires_yes(self) -> None:
        args = build_parser().parse_args(
            ["rename-episodes", "--job", "work-1", "--json"]
        )
        self.assertFalse(args.dry_run)
        self.assertFalse(args.execute)
        planned = {
            "jobId": "work-1",
            "outputPath": r"C:\Manga\work",
            "title": "작품",
            "folderCount": 2,
            "renameCount": 2,
            "conflictCount": 0,
            "canExecute": True,
        }
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch("toki_app.plan_episode_folder_rename", return_value=planned) as plan,
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(args), 0)
        plan.assert_called_once_with("work-1")
        self.assertEqual(json.loads(stdout.getvalue())["jobId"], "work-1")

        unconfirmed = build_parser().parse_args(
            ["rename-episodes", "--job", "work-1", "--execute", "--json"]
        )
        with patch("toki_app.rename_episode_folders") as execute:
            with self.assertRaisesRegex(ControlError, "--execute --yes"):
                run_cli(unconfirmed)
        execute.assert_not_called()

        confirmed = build_parser().parse_args(
            [
                "rename-episodes",
                "--job",
                "work-1",
                "--execute",
                "--yes",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=False),
            patch(
                "toki_app.rename_episode_folders",
                return_value={**planned, "executed": True},
            ) as execute,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(confirmed), 0)
        execute.assert_called_once_with("work-1")

    def test_cli_default_plan_json_exposes_the_migration_contract(self) -> None:
        source_name = "0001 남녀비 139의 …로 평범 1~5화"
        job, _output = self.make_work([source_name], state_payload=None)
        args = build_parser().parse_args(
            ["rename-episodes", "--job", job.job_id, "--json"]
        )

        with (
            patch("toki_app.gui_is_running", return_value=False),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(run_cli(args), 0)

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dryRun"])
        self.assertFalse(payload["executed"])
        self.assertTrue(payload["canExecute"])
        self.assertEqual(payload["folderCount"], 1)
        self.assertEqual(payload["renameCount"], 1)
        self.assertEqual(payload["conflictCount"], 0)
        self.assertEqual(payload["unsafeSuffixCount"], 0)
        self.assertFalse(payload["recoveryRequired"])
        self.assertEqual(payload["stateVersion"], 2)
        self.assertEqual(payload["pathPolicy"]["encoding"], "utf-16")
        self.assertEqual(len(payload["mappings"]), 1)
        self.assertEqual(len(payload["episodes"]), 1)
        self.assertTrue(
            {
                "number",
                "sourceId",
                "sourceTitle",
                "destinationFolderName",
                "componentUtf16Units",
                "destinationUtf16Units",
                "pathTooLong",
            }.issubset(payload["mappings"][0])
        )

    def test_cli_json_error_is_machine_readable(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch.object(
                toki_app.sys,
                "argv",
                [
                    "toki_app.py",
                    "rename-episodes",
                    "--job",
                    "work-1",
                    "--execute",
                    "--json",
                ],
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = toki_app.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("--execute --yes", payload["error"])
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_execute_timeout_reports_possible_background_continuation(
        self,
    ) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch.object(
                toki_app.sys,
                "argv",
                [
                    "toki_app.py",
                    "rename-episodes",
                    "--job",
                    "work-1",
                    "--execute",
                    "--yes",
                    "--json",
                ],
            ),
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request",
                side_effect=ControlTimeoutError("GUI response timeout"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = toki_app.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["timeout"])
        self.assertTrue(payload["operationMayContinue"])
        self.assertEqual(
            payload["statusCommand"],
            r".\toki-cli.cmd status --json",
        )
        self.assertIn("백그라운드에서 계속될 수 있으니", payload["error"])
        self.assertIn("status", payload["error"])
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_routes_plan_and_execute_through_running_gui(self) -> None:
        planned = {
            "jobId": "work-1",
            "outputPath": r"C:\Manga\work",
            "title": "작품",
            "folderCount": 2,
            "renameCount": 2,
            "conflictCount": 0,
            "canExecute": True,
        }
        dry_run = build_parser().parse_args(
            ["rename-episodes", "--job", "work-1", "--dry-run", "--json"]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch("toki_app.control_request", return_value=planned) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(dry_run), 0)
        request.assert_called_once_with(
            {
                "action": "rename_episode_folders",
                "jobId": "work-1",
                "execute": False,
                "confirmed": False,
            },
            timeout_ms=30000,
        )

        execute = build_parser().parse_args(
            [
                "rename-episodes",
                "--job",
                "work-1",
                "--execute",
                "--yes",
                "--json",
            ]
        )
        with (
            patch("toki_app.gui_is_running", return_value=True),
            patch(
                "toki_app.control_request", return_value={**planned, "executed": True}
            ) as request,
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(run_cli(execute), 0)
        request.assert_called_once_with(
            {
                "action": "rename_episode_folders",
                "jobId": "work-1",
                "execute": True,
                "confirmed": True,
            },
            timeout_ms=120000,
        )


if __name__ == "__main__":
    unittest.main()
