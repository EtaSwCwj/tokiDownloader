import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import toki_core as core
from toki_library import archive_library_items, delete_library_items, plan_library_delete, restore_library_trash
from toki_archive_catalog import archived_episodes


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(core, "JOB_DB_PATH", self.root / "jobs.db")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        core._INITIALIZED_JOB_DBS.clear()

    def work(self, key="a"):
        root = self.root / f"[작가][N／A] 작품 {key}"
        episode = root / f"작품 {key} 141.0화"
        episode.mkdir(parents=True)
        for page in (10, 2, 1):
            (episode / f"image{page}.jpg").write_bytes(b"\xff\xd8\xff" + str(page).encode() + b"\xff\xd9")
        record = {"number": 1, "sourceId": f"/manhwa/{key}/1", "sourceTitle": episode.name,
                  "sourceUrl": f"https://newtoki1.org/manhwa/{key}/1",
                  "displayTitle": episode.name, "folderName": episode.name}
        (root / "metadata.json").write_text(json.dumps({"title": f"작품 {key}", "episodes": [record]}), encoding="utf-8")
        (root / ".toki-state.json").write_text(json.dumps({"version": 2, "episodes": [record],
            "completedEpisodes": [1], "completedEpisodeIds": [record["sourceId"]]}), encoding="utf-8")
        job = core.DownloadJob(job_id=key, url=f"https://newtoki1.org/manhwa/{key}", output_dir=str(self.root),
                               output_path=str(root), title=f"작품 {key}", state="완료")
        core.save_jobs([job])
        return job, root, episode

    def simulation_work(self, key):
        root = self.root / "simulation-shared"
        root.mkdir(exist_ok=True)
        guard = root / "shared-user-file.zip"
        if not guard.exists():
            guard.write_bytes(b"shared files must never be touched")
        job = core.DownloadJob(job_id=key, url=f"https://www.youtube.com/watch?v={key:0>11}",
                               title=f"YouTube 모의 작업 {key}", state="완료", provider="youtube",
                               simulation=True, output_dir=str(root), output_path=str(root))
        core.save_jobs([job])
        return job, guard

    def test_delete_plan_is_read_only_and_changes_require_same_plan(self):
        job, root, episode = self.work()
        plan = plan_library_delete([job.job_id], "files")
        self.assertEqual(plan["fileCount"], 3)
        self.assertFalse((root / ".toki-trash").exists())
        (episode / "image3.jpg").write_bytes(b"new")
        with self.assertRaisesRegex(ValueError, "변경"):
            delete_library_items([job.job_id], "files", execute=True, plan_token=plan["planToken"])
        self.assertEqual(len(list(episode.iterdir())), 4)

    def test_batch_record_deletion_leaves_files(self):
        first, root, _ = self.work("a")
        second, second_root, _ = self.work("b")
        result = delete_library_items([first.job_id, second.job_id], "records", execute=True)
        self.assertTrue(result["success"])
        self.assertIsNone(core.load_job_by_id(first.job_id))
        self.assertIsNone(core.load_job_by_id(second.job_id))
        self.assertTrue(root.is_dir() and second_root.is_dir())

    def test_file_deletion_keeps_archives_and_can_restore_without_overwriting(self):
        job, root, episode = self.work()
        archive_library_items([job.job_id], execute=True)
        result = delete_library_items([job.job_id], "files", execute=True)
        self.assertTrue(result["success"])
        self.assertFalse(list(episode.glob("*.jpg")))
        self.assertEqual(len(list((root / "_archives").glob("*.zip"))), 1)
        manifest = result["results"][0]["trashManifest"]
        self.assertEqual(restore_library_trash(manifest)["fileCount"], 3)
        (episode / "image1.jpg").write_bytes(b"new")
        with self.assertRaisesRegex(ValueError, "덮어쓰지"):
            restore_library_trash(manifest, execute=True)
        (episode / "image1.jpg").unlink()
        restore_library_trash(manifest, execute=True)
        self.assertEqual(len(list(episode.glob("*.jpg"))), 3)
        self.assertEqual(json.loads((root / ".toki-state.json").read_text())["completedEpisodeIds"], ["/manhwa/a/1"])

    def test_archive_only_deletion_preserves_raw_pages(self):
        job, root, episode = self.work()
        archive_library_items([job.job_id], execute=True)
        result = delete_library_items([job.job_id], "archives", execute=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["fileCount"], 1)
        self.assertEqual(len(list(episode.glob("*.jpg"))), 3)
        self.assertFalse(archived_episodes(root))

    def test_zip_page_order_and_cleanup_completion_preview_and_node_agree(self):
        job, root, episode = self.work()
        result = archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["removedOriginalCount"], 3)
        self.assertFalse(episode.exists())
        archive = Path(result["jobs"][0]["archives"][0]["path"])
        with zipfile.ZipFile(archive) as bundle:
            names = [n for n in bundle.namelist() if n.endswith(".jpg")]
            self.assertEqual(names, [f"000001 {episode.name}/{n:06d}.jpg" for n in range(1, 4)])
            self.assertEqual([bundle.read(name)[3:-2] for name in names], [b"1", b"2", b"10"])
            self.assertIsNone(bundle.testzip())
        checked = core.verify_job_files(job.job_id)
        self.assertTrue(checked["healthy"], checked)
        self.assertEqual(checked["summary"]["archivedImages"], 3)
        preview = core.list_job_episode_images(job.job_id)
        self.assertEqual(preview["archivePath"], str(archive))
        self.assertEqual(preview["archivedImageCount"], 3)
        self.assertEqual(len(core.plan_metadata_rebuild(job.job_id)["metadata"]["episodes"]), 1)
        repeated = archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertEqual(repeated["createdCount"], 0)
        script = "import {loadArchivedEpisodes,hasArchivedEpisode} from './downloader_archives.js'; const a=loadArchivedEpisodes(process.argv[1]); console.log(JSON.stringify({count:a.length,match:hasArchivedEpisode(a,{sourceId:'/manhwa/a/1'})}));"
        process = subprocess.run(["node", "--input-type=module", "-e", script, str(root)], cwd=core.ROOT_DIR,
                                 capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), {"count": 1, "match": True})

    def test_crc_failure_and_cancel_never_remove_originals(self):
        job, root, episode = self.work()
        with patch.object(zipfile.ZipFile, "testzip", return_value="bad.jpg"):
            failed = archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertFalse(failed["success"])
        self.assertEqual(len(list(episode.iterdir())), 3)
        self.assertFalse(list((root / "_archives").glob("*.zip")))
        self.assertFalse(list((root / "_archives").glob("*.tmp")))
        cancelled = archive_library_items([job.job_id], execute=True, remove_originals=True, cancelled=lambda: True)
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(len(list(episode.iterdir())), 3)

    def test_partial_source_cleanup_never_replaces_complete_archive_with_subset(self):
        job, root, episode = self.work()
        first = archive_library_items([job.job_id], execute=True)
        archive = Path(first["jobs"][0]["archives"][0]["path"])
        original = archive.read_bytes()
        (episode / "image1.jpg").unlink()
        result = archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result["success"])
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse(list(episode.glob("*.jpg")))

    def test_unmanaged_or_changed_archive_is_never_overwritten(self):
        job, root, _ = self.work()
        plan = archive_library_items([job.job_id])
        path = Path(plan["jobs"][0]["archives"][0]["path"])
        path.parent.mkdir()
        path.write_bytes(b"user archive")
        result = archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertFalse(result["success"])
        self.assertEqual(path.read_bytes(), b"user archive")

    def test_unsafe_roots_and_active_jobs_are_rejected(self):
        job, _, _ = self.work()
        job.output_path = str(self.root)
        core.save_jobs([job])
        with self.assertRaises(ValueError):
            delete_library_items([job.job_id], "files", execute=True)
        job.state = "실행 중"
        core.save_jobs([job])
        with self.assertRaises(ValueError):
            delete_library_items([job.job_id], "records", execute=True)

    def test_restore_rejects_path_escape(self):
        job, root, _ = self.work()
        result = delete_library_items([job.job_id], "files", execute=True)
        path = Path(result["results"][0]["trashManifest"])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["entries"][0]["source"] = "../outside.jpg"
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ValueError):
            restore_library_trash(str(path), execute=True)

    def test_incomplete_episode_is_not_promoted_to_archive_completion(self):
        job, root, episode = self.work()
        state_path = root / ".toki-state.json"
        state = json.loads(state_path.read_text())
        # Numbers are stale: explicit empty stable IDs must remain authoritative.
        state["completedEpisodeIds"] = []
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "완료 기록"):
            archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertEqual(len(list(episode.glob("*.jpg"))), 3)
        self.assertFalse((root / "_archives").exists())

    def test_overlapping_work_roots_are_rejected_before_mutation(self):
        parent, root, _ = self.work("a")
        child, _, _ = self.work("b")
        child.output_path = str(root / "nested work")
        Path(child.output_path).mkdir()
        core.save_jobs([child])
        for operation in (lambda: delete_library_items([parent.job_id, child.job_id], "files", execute=True),
                          lambda: archive_library_items([parent.job_id, child.job_id], execute=True)):
            with self.assertRaisesRegex(ValueError, "겹치는"):
                operation()
        self.assertFalse((root / ".toki-trash").exists())
        self.assertFalse((root / "_archives").exists())

    def test_changed_or_truncated_zip_is_not_counted_as_downloaded(self):
        job, root, _ = self.work()
        result = archive_library_items([job.job_id], execute=True)
        archive = Path(result["jobs"][0]["archives"][0]["path"])
        archive.write_bytes(archive.read_bytes()[:-22])
        self.assertEqual(archived_episodes(root, verify_crc=True), [])
        script = "import {loadArchivedEpisodes} from './downloader_archives.js'; console.log(JSON.stringify(loadArchivedEpisodes(process.argv[1])));"
        process = subprocess.run(["node", "--input-type=module", "-e", script, str(root)], cwd=core.ROOT_DIR,
                                 capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), [])

    def test_mixed_simulations_do_not_block_real_file_deletion(self):
        job, root, episode = self.work()
        simulations = [self.simulation_work(f"sim{i}") for i in range(3)]
        ids = [job.job_id, *(j.job_id for j, _ in simulations)]
        plan = plan_library_delete(ids, "files")
        self.assertEqual((plan["eligibleJobCount"], plan["skippedJobCount"], plan["fileCount"]), (1, 3, 3))
        result = delete_library_items(ids, "files", execute=True, plan_token=plan["planToken"])
        self.assertEqual(result["movedFileCount"], 3)
        self.assertFalse(list(episode.glob("*.jpg")))
        for simulation, guard in simulations:
            self.assertEqual(guard.read_bytes(), b"shared files must never be touched")
            self.assertIsNotNone(core.load_job_by_id(simulation.job_id))
        self.assertTrue((root / "metadata.json").is_file())

    def test_empty_archive_deletion_is_noop_with_simulations(self):
        job, root, episode = self.work()
        simulations = [self.simulation_work(f"sim{i}") for i in range(3)]
        ids = [job.job_id, *(j.job_id for j, _ in simulations)]
        result = delete_library_items(ids, "archives", execute=True)
        self.assertFalse(result["canExecute"])
        self.assertFalse(result["executed"])
        self.assertTrue(result["noOp"])
        self.assertEqual((result["skippedJobCount"], result["emptyJobCount"]), (3, 1))
        self.assertFalse((root / ".toki-trash").exists())
        self.assertEqual(len(list(episode.glob("*.jpg"))), 3)
        # List-only deletion remains available even for simulation records.
        removed = delete_library_items(ids, "records", execute=True)
        self.assertEqual(removed["removedRecordCount"], 4)
        self.assertTrue(simulations[0][1].is_file())


if __name__ == "__main__":
    unittest.main()
