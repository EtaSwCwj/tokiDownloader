"""Real CLI -> private Qt clipboard signal -> queue -> SQLite, no downloads."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import toki_core as core


class ClipboardCliIntegrationTests(unittest.TestCase):
    def cli(self, *arguments, expected=0):
        result = subprocess.run([*self.command, *arguments], cwd=core.ROOT_DIR, env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=20,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if expected == 0 else result

    def test_copied_url_enqueues_once_while_minimized_and_keeps_saved_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".library-cli-test").touch()
            (root / ".clipboard-auto-test").touch()
            output = root / "saved-output"
            output.mkdir()
            with patch.object(core, "CONFIG_PATH", root / "config.json"):
                core.save_config({**core.default_config(), "outputDir": str(output),
                                  "thumbnailsVisible": False, "archiveAfterDownload": True,
                                  "archiveRemoveOriginals": True, "notificationMessageBox": False,
                                  "recoverInterruptedOnStartup": False})
            self.command = [sys.executable, "-X", "utf8", str(core.ROOT_DIR / "tests/fixtures/library_cli_host.py"), str(root)]
            self.env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
            with (root / "host.log").open("w", encoding="utf-8") as log:
                host = subprocess.Popen([*self.command, "gui"], cwd=core.ROOT_DIR, env=self.env,
                                        stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    for _ in range(30):
                        status = subprocess.run([*self.command, "status", "--json"], cwd=core.ROOT_DIR, env=self.env,
                                                capture_output=True, text=True, encoding="utf-8", timeout=5,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        if status.returncode == 0:
                            break
                        self.assertIsNone(host.poll(), (root / "host.log").read_text(encoding="utf-8"))
                        time.sleep(0.1)
                    else:
                        self.fail("Private clipboard GUI did not start")
                    url = "https://newtoki1.org/manhwa/99001"
                    self.cli("test-clipboard-copy", url)
                    self.assertEqual(self.cli("status", "--json")["totalJobCount"], 0)
                    mode = self.cli("clipboard", "monitor", "--state", "on", "--mode", "auto", "--json")
                    self.assertTrue(mode["autoDownload"])
                    self.assertEqual(self.cli("test-clipboard-settings"), {
                        "monitorChecked": True, "autoSelected": True, "modeEnabled": True})
                    # Enabling must not process pre-existing clipboard content.
                    self.assertEqual(self.cli("status", "--json")["totalJobCount"], 0)
                    self.assertFalse(self.cli("clipboard", "inspect", "--text", url, "--via-gui", "--json")["enqueued"])
                    self.cli("test-clipboard-copy", "")
                    copied = self.cli("test-clipboard-copy", url + "?epage=3")
                    self.assertTrue(copied["inspection"]["enqueued"])
                    self.assertFalse(copied["inspection"]["prompted"])
                    self.assertEqual((copied["formUrl"], copied["start"], copied["last"]),
                                     ("typed URL must stay untouched", 13, 15))
                    self.assertTrue(copied["minimized"])
                    self.assertFalse(copied["processing"])
                    registered = self.cli("status", "--json")
                    self.assertEqual(registered["totalJobCount"], 1)
                    self.assertEqual(registered["pendingCount"], 1)
                    self.assertEqual(registered["activeCount"], 0)
                    job = registered["jobs"][0]
                    self.assertEqual(job["output_dir"], str(output))
                    self.assertEqual(job["url"], url)
                    self.assertIsNone(job["start"])
                    self.assertIsNone(job["last"])
                    self.assertEqual(job["scan_mode"], "new")
                    settings = self.cli("settings", "--json")
                    self.assertTrue(settings["archiveAfterDownload"])
                    self.assertTrue(settings["archiveRemoveOriginals"])
                    dupe = self.cli("test-clipboard-copy", url.replace("newtoki1", "newtoki2"))
                    self.assertTrue(dupe["inspection"]["duplicate"])
                    for text in ("ordinary copied text", "https://newtoki1.org/", url + "/1",
                                 "https://example.com/manhwa/99002"):
                        self.assertFalse(self.cli("test-clipboard-copy", text)["inspection"]["candidate"])
                    self.assertEqual(self.cli("status", "--json")["totalJobCount"], 1)
                    self.cli("clipboard", "monitor", "--state", "off")
                    self.cli("test-clipboard-copy", url[:-1] + "2")
                    self.assertEqual(self.cli("status", "--json")["totalJobCount"], 1)
                    self.assertEqual(self.cli("test-clipboard-settings"), {
                        "monitorChecked": False, "autoSelected": True, "modeEnabled": False})
                    # Explicit CLI dispatch has the same validator/queue path,
                    # but is independent of automatic monitoring and needs --yes.
                    self.cli("clipboard", "enqueue", "--text", url[:-1] + "2", expected=1)
                    self.assertEqual(self.cli("status", "--json")["totalJobCount"], 1)
                    direct = self.cli("clipboard", "enqueue", "--text", url[:-1] + "2", "--yes")
                    self.assertTrue(direct["enqueued"])
                    self.assertEqual(self.cli("status", "--json")["totalJobCount"], 2)
                    with patch.object(core, "JOB_DB_PATH", root / "jobs.db"):
                        stored = core.load_job_by_work_key("manatoki:99001")
                    self.assertIsNotNone(stored)
                    self.assertEqual(stored.output_dir, str(output))
                    self.assertEqual(list(output.iterdir()), [])
                    print("[Clipboard CLI] copied URL -> real Qt signal -> 1 queued work; duplicate/invalid ignored; minimized/form/settings/SQLite verified; no download processes")
                finally:
                    if host.poll() is None:
                        try:
                            self.cli("quit", "--force")
                            host.wait(timeout=8)
                        finally:
                            if host.poll() is None:
                                host.kill()
                                host.wait(timeout=5)
