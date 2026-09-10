import json
import os
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import toki_archive_cleanup as cleanup
import toki_library as lib
import toki_core as core
import test_toki_library as legacy
from test_toki_work_archive import add_chapter


class EmptyFolderCleanupTests(unittest.TestCase):
    setUp = legacy.LibraryTests.setUp
    work = legacy.LibraryTests.work

    def archived_empty(self):
        job, root, episode = self.work()
        result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result["success"], result)
        episode.mkdir(exist_ok=True)  # Historical leftover after ZIP publication.
        return job, root, episode, Path(result["jobs"][0]["archives"][0]["path"])

    def test_readonly_dry_run_then_cleanup_without_crc_or_state_changes(self):
        job, root, episode, archive = self.archived_empty()
        if os.name == "nt":
            cleanup._set_readonly(episode, True)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (
            archive, root / "metadata.json", root / ".toki-state.json", archive.parent / ".toki-archive-index.json")}
        unknown = root / "개인 메모 폴더"
        unknown.mkdir()
        hidden = root / ".toki-image-resume" / "objects"
        hidden.mkdir(parents=True)
        with patch.object(zipfile.ZipFile, "testzip", side_effect=AssertionError("No CRC reread")):
            plan = cleanup.cleanup_empty_episode_folders([job.job_id])
            self.assertEqual(plan["jobs"][0]["targets"], [str(episode)])
            self.assertTrue(episode.exists())
            result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True, plan_token=plan["planToken"])
            self.assertTrue(result["success"], result)
            self.assertEqual(result["removedFolderCount"], 1)
            self.assertFalse(episode.exists())
            self.assertEqual(cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)["removedFolderCount"], 0)
        self.assertTrue(unknown.is_dir() and hidden.is_dir())
        for path, (data, mtime) in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (data, mtime))

    def test_changed_preview_or_new_child_never_deleted(self):
        job, root, episode, _ = self.archived_empty()
        plan = cleanup.cleanup_empty_episode_folders([job.job_id])
        (episode / "note.txt").write_text("user note")
        with self.assertRaisesRegex(ValueError, "변경"):
            cleanup.cleanup_empty_episode_folders([job.job_id], execute=True, plan_token=plan["planToken"])
        self.assertFalse(cleanup.cleanup_empty_episode_folders([job.job_id])["canExecute"])
        self.assertEqual((episode / "note.txt").read_text(), "user note")

    def test_incomplete_pending_and_changed_zip_preserved(self):
        job, root, episode, archive = self.archived_empty()
        state_path = root / ".toki-state.json"
        state = json.loads(state_path.read_text())
        state["pendingEpisodes"] = [state["episodes"][0]]
        state_path.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(cleanup.cleanup_empty_episode_folders([job.job_id])["folderCount"], 0)
        state.pop("pendingEpisodes")
        state["completedEpisodeIds"] = []
        state_path.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(cleanup.cleanup_empty_episode_folders([job.job_id])["folderCount"], 0)
        state["completedEpisodeIds"] = [state["episodes"][0]["sourceId"]]
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with archive.open("ab") as stream:
            stream.write(b"external mutation")
        result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
        self.assertEqual(result["removedFolderCount"], 0)
        self.assertTrue(episode.exists())

    def test_invalid_state_and_missing_catalog_preserved(self):
        job, root, episode, _ = self.archived_empty()
        (root / ".toki-state.json").write_text("{broken")
        self.assertFalse(cleanup.cleanup_empty_episode_folders([job.job_id])["canExecute"])
        self.assertTrue(episode.exists())

    def test_symlink_target_never_touched(self):
        job, root, episode, _ = self.archived_empty()
        with patch.object(lib, "_is_link", side_effect=lambda p: p == episode):
            result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
        self.assertEqual(result["removedFolderCount"], 0)
        self.assertTrue(episode.exists())

    def test_nonempty_subfolder_is_not_recursively_removed(self):
        job, root, episode, _ = self.archived_empty()
        (episode / "empty child").mkdir()
        self.assertEqual(cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)["removedFolderCount"], 0)
        self.assertTrue((episode / "empty child").is_dir())

    def test_archive_cleanup_denial_is_warning_and_other_chapters_continue(self):
        job, root, episode = self.work()
        other = add_chapter(root, 2, "작품 a 142화")
        original = Path.rmdir
        def deny(path):
            if path == episode:
                raise PermissionError("OneDrive busy")
            return original(path)
        with patch.object(Path, "rmdir", deny), patch.object(cleanup.time, "sleep"):
            result = lib.archive_library_items([job.job_id], execute=True, remove_originals=True)
        self.assertTrue(result["success"], result)
        self.assertEqual((result["removedOriginalCount"], result["removedFolderCount"], result["cleanupWarningCount"]), (6, 1, 1))
        self.assertTrue(episode.exists())
        self.assertFalse(other.exists())
        with zipfile.ZipFile(result["jobs"][0]["archives"][0]["path"]) as bundle:
            self.assertIsNone(bundle.testzip())
        self.assertEqual(cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)["removedFolderCount"], 1)

    @unittest.skipUnless(os.name == "nt", "Windows readonly attributes")
    def test_readonly_restored_on_permanent_permission_failure(self):
        job, root, episode, _ = self.archived_empty()
        cleanup._set_readonly(episode, True)
        flags = episode.lstat().st_file_attributes
        try:
            with patch.object(Path, "rmdir", side_effect=PermissionError("locked")), patch.object(cleanup.time, "sleep"):
                result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
            self.assertFalse(result["success"])
            self.assertEqual(result["cleanupWarningCount"], 1)
            self.assertEqual(episode.lstat().st_file_attributes, flags)
        finally:
            cleanup._set_readonly(episode, False)

    def test_child_appearing_at_rmdir_preserved(self):
        job, root, episode, _ = self.archived_empty()
        original = Path.rmdir
        def inject(path):
            if path == episode:
                (path / "new.txt").write_text("keep")
            return original(path)
        with patch.object(Path, "rmdir", inject):
            result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
        self.assertEqual(result["removedFolderCount"], 0)
        self.assertEqual((episode / "new.txt").read_text(), "keep")

    def test_activity_or_existing_lock_blocks_cleanup(self):
        job, root, episode, _ = self.archived_empty()
        with lib._lock(root):
            result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
            self.assertFalse(result["success"])
        job.state = next(iter(core.ACTIVE_JOB_STATES))
        core.save_jobs([job])
        with self.assertRaises(ValueError):
            cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
        self.assertTrue(episode.exists())

    def test_zip_changed_after_planning_blocks_removal(self):
        job, root, episode, archive = self.archived_empty()
        original = cleanup._remove_empty
        def change_before_delete(root, folder, guard):
            with archive.open("ab") as stream:
                stream.write(b"changed")
            return original(root, folder, guard)
        with patch.object(cleanup, "_remove_empty", change_before_delete):
            result = cleanup.cleanup_empty_episode_folders([job.job_id], execute=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["removedFolderCount"], 0)
        self.assertTrue(episode.exists())

    def test_thousand_folders_read_catalog_once_without_crc(self):
        job, root, episode, archive = self.archived_empty()
        episodes = []
        for index in range(1, 1001):
            folder = root / f"{index:06d} 작품 a {index}화"
            folder.mkdir()
            episodes.append({"number": index, "sourceId": f"/manhwa/a/{index}",
                             "sourceUrl": f"https://newtoki1.org/manhwa/a/{index}",
                             "sourceTitle": folder.name, "displayTitle": folder.name,
                             "folderName": folder.name, "prefix": folder.name + "/", "imageCount": 1})
        with zipfile.ZipFile(archive, "w") as bundle:
            for e in episodes:
                bundle.writestr(e["prefix"] + "000001.jpg", b"fixture")
        state = {"version": 2, "episodes": episodes, "completedEpisodeIds": [e["sourceId"] for e in episodes],
                 "completedEpisodes": [e["number"] for e in episodes]}
        (root / ".toki-state.json").write_text(json.dumps(state), encoding="utf-8")
        index = {archive.name: {"size": archive.stat().st_size, "mtimeNs": str(archive.stat().st_mtime_ns), "episodes": episodes}}
        (archive.parent / ".toki-archive-index.json").write_text(json.dumps(index), encoding="utf-8")
        with patch.object(cleanup, "archived_episodes", wraps=cleanup.archived_episodes) as catalog:
            with patch.object(zipfile.ZipFile, "testzip", side_effect=AssertionError("No CRC scan")):
                plan = cleanup.cleanup_empty_episode_folders([job.job_id])
        self.assertEqual(plan["folderCount"], 1000)
        self.assertEqual(catalog.call_count, 1)
        self.assertTrue(episode.is_dir())  # Old name is no longer owned by the state.
