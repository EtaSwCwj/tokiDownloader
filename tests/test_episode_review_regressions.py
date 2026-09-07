from __future__ import annotations

import base64
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import toki_app
import toki_core as core


class EpisodeReviewRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = core.DownloadJob(
            job_id="review-regression", url="https://newtoki1.org/manhwa/1",
            output_dir=str(self.root), output_path=str(self.root),
            title="작품", state="완료", site="manatoki",
        )
        self.job_patch = patch.object(core, "load_job_by_id", return_value=self.job)
        self.job_patch.start()
        self.addCleanup(self.job_patch.stop)

    def record(self, number: int, title: str, *, source_id: str = "", folder: str = "") -> dict:
        return {
            "number": number, "sourceId": source_id,
            "sourceUrl": f"https://newtoki1.org{source_id}" if source_id else "",
            "sourceTitle": title, "displayTitle": folder or title,
            "folderName": folder or title,
        }

    def manifest(self, records: list[dict], completed: list[int] | None = None,
                 metadata_records: list[dict] | None = None) -> None:
        completed = completed if completed is not None else [r["number"] for r in records]
        state = {
            "version": 2, "episodes": records, "completedEpisodes": completed,
            "completedEpisodeIds": [
                r["sourceId"] for r in records if r["number"] in completed and r["sourceId"]
            ],
        }
        (self.root / ".toki-state.json").write_text(json.dumps(state), encoding="utf-8")
        (self.root / "metadata.json").write_text(json.dumps({
            "title": "작품", "episodes": records if metadata_records is None else metadata_records,
        }), encoding="utf-8")

    def folder(self, name: str, count: int = 1) -> Path:
        folder = self.root / name
        folder.mkdir(exist_ok=True)
        for index in range(count):
            (folder / f"{index:04d}.jpg").write_bytes(b"\xff\xd8\xffimage\xff\xd9")
        return folder

    def test_wrong_same_ordinal_folder_never_inherits_completed_source_identity(self) -> None:
        record = self.record(1, "작품 원래 1화", source_id="/manhwa/1/original")
        self.manifest([record])
        wrong = self.folder("0001 전혀 다른 9화")
        discovered = core.discover_episode_folders(self.root)
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].source_id, "")
        verified = core.verify_job_files(self.job.job_id)
        self.assertFalse(verified["healthy"])
        self.assertEqual(verified["missingEpisodeIds"], [record["sourceId"]])
        rebuilt = core.plan_metadata_rebuild(self.job.job_id)["metadata"]
        self.assertEqual(rebuilt["episodes"][0]["folderName"], wrong.name)
        self.assertEqual(rebuilt["episodes"][0]["sourceId"], "")
        # Even after saving the rebuilt metadata, the wrong folder remains idless.
        (self.root / "metadata.json").write_text(json.dumps(rebuilt), encoding="utf-8")
        self.assertEqual(core.discover_episode_folders(self.root)[0].source_id, "")
        self.assertEqual(core.verify_job_files(self.job.job_id)["missingEpisodeIds"], [record["sourceId"]])

    def test_title_verified_legacy_fallback_preserves_source_identity(self) -> None:
        record = self.record(1, "작품 <b>1화</b>", source_id="/manhwa/1/original", folder="작품 표시 1화")
        self.manifest([record])
        self.folder("0001 작품 1화")
        found = core.discover_episode_folders(self.root)[0]
        self.assertEqual(found.discovery, "legacy-fallback")
        self.assertEqual(found.source_id, record["sourceId"])
        self.assertTrue(core.verify_job_files(self.job.job_id)["healthy"])

    def test_ambiguous_legacy_title_does_not_claim_one_of_two_source_ids(self) -> None:
        records = [
            self.record(1, "작품 1화", source_id=f"/manhwa/1/{key}", folder=f"작품 1화 ({key})")
            for key in ("a", "b")
        ]
        self.manifest(records)
        self.folder("0001 작품 1화")
        self.assertEqual(core.discover_episode_folders(self.root)[0].source_id, "")
        self.assertEqual(len(core.verify_job_files(self.job.job_id)["missingEpisodeIds"]), 2)

    def test_webp_validation_rejects_truncation_and_accepts_real_static_and_animated_files(self) -> None:
        samples = json.loads((Path(__file__).parent / "fixtures/webp_validation_samples.json").read_text())
        folder = self.root / "작품 1화"
        folder.mkdir()
        self.manifest([self.record(1, folder.name, source_id="/manhwa/1/a")])
        image = folder / "0000.webp"
        for name, encoded in samples.items():
            payload = base64.b64decode(encoded)
            oversized_chunk = bytearray(payload)
            oversized_chunk[16:20] = len(payload).to_bytes(4, "little")
            header_only = bytearray(payload[:20])
            header_only[4:8] = (12).to_bytes(4, "little")
            for label, data, valid in (
                ("valid", payload, True), ("truncated", payload[:20], False),
                ("missing-last-byte", payload[:-1], False),
                ("oversized-chunk", oversized_chunk, False),
                ("header-only", header_only, False),
            ):
                with self.subTest(name=name, variant=label):
                    image.write_bytes(data)
                    self.assertEqual(core._image_signature_valid(image), valid)
                    self.assertEqual(core.verify_job_files(self.job.job_id)["healthy"], valid)

    def test_webp_validation_checks_chunks_beyond_initial_header(self) -> None:
        samples = json.loads((Path(__file__).parent / "fixtures/webp_validation_samples.json").read_text())
        base = base64.b64decode(samples["lossy"])
        metadata = b"JUNK" + (1024).to_bytes(4, "little") + bytes(1024)
        extended = bytearray(base[:12] + metadata + base[12:])
        extended[4:8] = (len(extended) - 8).to_bytes(4, "little")
        image = self.root / "large.webp"
        image.write_bytes(extended)
        self.assertTrue(core._image_signature_valid(image))
        extended[16 + len(metadata):20 + len(metadata)] = len(extended).to_bytes(4, "little")
        image.write_bytes(extended)
        self.assertFalse(core._image_signature_valid(image))

    def test_partial_download_preserves_contextual_name_using_full_catalog(self) -> None:
        for base, sibling, canonical in (
            ("141화", "141.5화", "141.0화"),
            ("140화", "140-2화", "140-1화"),
        ):
            for catalog in ("state", "metadata"):
                with self.subTest(base=base, catalog=catalog):
                    folder = self.folder(f"작품 {canonical}")
                    record = self.record(1, f"작품 {base}", source_id="/manhwa/1/a", folder=folder.name)
                    records = [record, self.record(2, f"작품 {sibling}", source_id="/manhwa/1/b")]
                    self.manifest(records if catalog == "state" else [record], [1], records)
                    result = core.plan_episode_folder_rename(self.job.job_id)
                    self.assertTrue(result["canExecute"], result["conflicts"])
                    self.assertEqual(result["renameCount"], 0)
                    self.assertEqual(result["mappings"][0]["destinationFolderName"], folder.name)
                    self.assertEqual(len(result["episodes"]), 2)
                    # Only this test-owned fixture is removed between cases.
                    (folder / "0000.jpg").unlink()
                    folder.rmdir()

    def test_missing_sibling_can_trigger_rename_and_catalog_conflict(self) -> None:
        folder = self.folder("작품 140화")
        records = [
            self.record(1, folder.name, source_id="/manhwa/1/a"),
            self.record(2, "작품 140-2화", source_id="/manhwa/1/b"),
        ]
        self.manifest(records, [1])
        plan = core.plan_episode_folder_rename(self.job.job_id)
        self.assertEqual(plan["renameCount"], 1)
        self.assertEqual(plan["mappings"][0]["destinationFolderName"], "작품 140-1화")
        self.manifest([*records, self.record(3, "작품 140.5화", source_id="/manhwa/1/c")], [1])
        conflict = core.plan_episode_folder_rename(self.job.job_id)
        self.assertFalse(conflict["canExecute"])
        self.assertEqual(conflict["mappings"][0]["contextualSuffixConflictCode"], "mixed_decimal_hyphen_siblings")

    def test_preview_separates_same_ordinal_and_supports_precise_selection(self) -> None:
        records = [self.record(1, f"작품 {n}화", source_id=f"/manhwa/1/{n}") for n in (1, 2)]
        self.manifest(records)
        for record in records:
            self.folder(record["folderName"], count=2)
        initial = core.list_job_episode_images(self.job.job_id)
        self.assertEqual(initial["total"], 2)
        self.assertEqual(len(initial["episodeEntries"]), 2)
        self.assertEqual(initial["availableEpisodes"], [1])
        with self.assertRaisesRegex(ValueError, "--episode-id"):
            core.list_job_episode_images(self.job.job_id, 1)
        for selector in ({"episode_id": records[1]["sourceId"]}, {"episode_folder": records[1]["folderName"]}):
            result = core.list_job_episode_images(self.job.job_id, limit=1, offset=1, **selector)
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["episodeId"], records[1]["sourceId"])
            self.assertEqual(result["images"][0]["name"], "0001.jpg")
            self.assertEqual(Path(result["images"][0]["path"]).parent.name, records[1]["folderName"])
        for selector in ({"episode_folder": "../outside"}, {"episode_id": "missing"}):
            with self.assertRaises(ValueError):
                core.list_job_episode_images(self.job.job_id, **selector)

    def test_preview_cli_selects_exact_folder_and_emits_ambiguity_error(self) -> None:
        records = [self.record(1, f"작품 {n}화", source_id=f"/manhwa/1/{n}") for n in (1, 2)]
        self.manifest(records)
        for record in records:
            self.folder(record["folderName"])
        for option, field in (("--episode-id", "sourceId"), ("--episode-folder", "folderName")):
            args = toki_app.build_parser().parse_args([
                "preview", "--job", self.job.job_id, option, records[1][field], "--json",
            ])
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(toki_app.run_cli(args), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["episodeFolder"], records[1]["folderName"])
            self.assertEqual(len(result["images"]), 1)
        args = toki_app.build_parser().parse_args(["preview", "--job", self.job.job_id, "--episode", "1"])
        with self.assertRaisesRegex(ValueError, "--episode-folder"):
            toki_app.run_cli(args)


if __name__ == "__main__":
    unittest.main()
