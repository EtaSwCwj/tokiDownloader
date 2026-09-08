"""Real CLI subprocess -> private IPC -> real MainWindow -> SQLite -> list refresh."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import toki_core as core
from toki_library import archive_library_items
import test_toki_library as library_tests


class LibraryCliIntegrationTests(unittest.TestCase):
    setUp = library_tests.LibraryTests.setUp
    work = library_tests.LibraryTests.work
    simulation_work = library_tests.LibraryTests.simulation_work

    def cli(self, *arguments, expected=0):
        result = subprocess.run([*self.command, *arguments], cwd=core.ROOT_DIR, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_actual_cli_mixed_simulation_batch_and_record_deletion(self):
        first, first_root, first_episode = self.work("a")
        simulations = [self.simulation_work(f"sim{i}") for i in range(3)]
        ids = [first.job_id, *(j.job_id for j, _ in simulations)]
        job_args = tuple(part for job_id in ids for part in ("--job", job_id))
        archive_result = archive_library_items([first.job_id], execute=True)
        archive_path = archive_result["jobs"][0]["archives"][0]["path"]
        (self.root / ".library-cli-test").touch()
        with patch.object(core, "CONFIG_PATH", self.root / "config.json"):
            core.save_config({**core.default_config(), "outputDir": str(self.root),
                              "thumbnailsVisible": False, "notificationMessageBox": False,
                              "recoverInterruptedOnStartup": False})
        self.command = [sys.executable, "-X", "utf8", str(core.ROOT_DIR / "tests/fixtures/library_cli_host.py"), str(self.root)]
        self.env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        with (self.root / "host.log").open("w", encoding="utf-8") as log:
            host = subprocess.Popen([*self.command, "gui"], cwd=core.ROOT_DIR, env=self.env,
                                    stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                for _ in range(20):
                    status = subprocess.run([*self.command, "status", "--json"], cwd=core.ROOT_DIR, env=self.env,
                                            capture_output=True, text=True, encoding="utf-8", timeout=5,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if status.returncode == 0:
                        break
                    self.assertIsNone(host.poll(), (self.root / "host.log").read_text(encoding="utf-8"))
                    time.sleep(0.1)
                else:
                    self.fail("Isolated GUI IPC did not start")
                self.assertEqual(self.cli("status", "--json")["totalJobCount"], 4)
                self.cli("library", "select", *job_args, "--json")
                archive_args = ("library", "delete", *job_args, "--kind", "archives")
                archive_plan = self.cli(*archive_args, "--dry-run", "--wait", "--json")["result"]
                self.assertEqual((archive_plan["eligibleJobCount"], archive_plan["skippedJobCount"], archive_plan["fileCount"]), (1, 3, 1))
                deleted_archives = self.cli(*archive_args, "--execute", "--yes", "--wait", "--json")["result"]
                self.assertEqual(deleted_archives["movedFileCount"], 1)
                self.assertFalse(Path(archive_path).exists())
                self.assertEqual(len(list(first_episode.glob("*.jpg"))), 3)
                no_archives = self.cli(*archive_args, "--execute", "--yes", "--wait", "--json")["result"]
                self.assertTrue(no_archives["noOp"])
                self.assertFalse(no_archives["executed"])
                self.cli("library", "restore", "--manifest", deleted_archives["results"][0]["trashManifest"],
                         "--execute", "--yes", "--wait", "--json")
                self.assertTrue(Path(archive_path).is_file())
                deleted_files = self.cli("library", "delete", *job_args, "--kind", "files",
                                         "--execute", "--yes", "--wait", "--json")["result"]
                self.assertEqual(deleted_files["movedFileCount"], 3)
                self.assertFalse(list(first_episode.glob("*.jpg")))
                self.assertTrue(Path(archive_path).is_file())
                self.cli("library", "restore", "--manifest", deleted_files["results"][0]["trashManifest"],
                         "--execute", "--yes", "--wait", "--json")
                self.assertEqual(len(list(first_episode.glob("*.jpg"))), 3)
                for _, guard in simulations:
                    self.assertEqual(guard.read_bytes(), b"shared files must never be touched")
                self.assertEqual(self.cli("status", "--json")["totalJobCount"], 4)
                print("[CLI integration] mixed 1 real + 3 simulations: archive moved 1, empty retry no-op, files moved 3, restored, shared files protected")
                args = ("library", "delete", *job_args, "--kind", "records")
                preview = self.cli(*args, "--dry-run", "--wait", "--json")["result"]
                self.assertFalse(preview["executed"])
                self.assertEqual(self.cli("status", "--json")["totalJobCount"], 4)
                self.cli(*args, "--execute", "--json", expected=1)
                self.assertIsNotNone(core.load_job_by_id(first.job_id))
                result = self.cli(*args, "--execute", "--yes", "--plan-token", preview["planToken"], "--wait", "--json")
                self.assertEqual(result["error"], "")
                self.assertTrue(result["result"]["success"])
                self.assertEqual(result["result"]["removedRecordCount"], 4)
                for job_id in ids:
                    self.assertIsNone(core.load_job_by_id(job_id))
                self.cli("refresh-list")
                after = self.cli("status", "--json")
                self.assertEqual(after["totalJobCount"], 0)
                self.assertEqual(after["loadedJobCount"], 0)
                self.assertEqual(after["jobs"], [])
                self.assertEqual(len(list(first_episode.glob("*.jpg"))), 3)
                self.assertTrue((first_root / "metadata.json").is_file())
                self.assertTrue(Path(archive_path).is_file())
                print("[CLI integration] removed 4 records; database 0; GUI 0 after refresh; original images and archive preserved")
            finally:
                if host.poll() is None:
                    try:
                        self.cli("quit")
                        host.wait(timeout=8)
                    finally:
                        if host.poll() is None:
                            host.kill()
                            host.wait(timeout=5)
