from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import toki_launcher as launcher
from toki_windows_launch import APP_ID, apply_window_relaunch, relaunch_properties, window_properties

FIXTURE = Path(__file__).parent / "fixtures" / "launcher_child.py"


class LauncherTests(unittest.TestCase):
    def run_fixture(self, root, mode):
        directory = launcher.new_run_directory([root])
        code = launcher.supervise(directory, [sys.executable, str(FIXTURE), str(directory), mode])
        return code, launcher.read_json(directory / "process.json"), directory

    def test_clean_error_and_abrupt_zero_or_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as root:
            for mode, code, expected in (("normal", 0, "normal_exit"),
                                         ("error", 1, "python_error"),
                                         ("exit-7", 7, "unexpected_exit"),
                                         ("exit-0", 0, "unexpected_exit")):
                with self.subTest(mode=mode):
                    result, state, directory = self.run_fixture(Path(root), mode)
                    self.assertEqual(result, code)
                    self.assertEqual(state["state"], expected)
                    self.assertEqual(state["exitCodeHex"], f"0x{code:08X}")
                    self.assertTrue(state["finishedAt"])
                    if mode == "error":
                        self.assertIn("fixture startup import failure", (directory / "events.log").read_text())

    def test_worker_exception_and_pythonw_streams_are_logged(self):
        with tempfile.TemporaryDirectory() as root:
            for mode, expected in (("thread", "fixture thread exception"), ("output", "fixture stderr")):
                _, state, directory = self.run_fixture(Path(root), mode)
                self.assertEqual(state["state"], "normal_exit")
                self.assertIn(expected, (directory / "events.log").read_text())

    def test_external_termination_is_observed_without_touching_gui(self):
        with tempfile.TemporaryDirectory() as root:
            directory = launcher.new_run_directory([Path(root)])
            monitor = threading.Thread(target=launcher.supervise, args=(directory,
                [sys.executable, str(FIXTURE), str(directory), "wait"]))
            monitor.start()
            child_pid = None
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    # Windows venv python.exe can be a redirector. Terminate the
                    # real fixture interpreter after its session has started.
                    child_pid = launcher.read_json(directory / "child.json").get("pid")
                    if child_pid:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(child_pid)
                # This PID belongs to the fixture Popen above, not a discovered user process.
                import psutil
                psutil.Process(child_pid).terminate()
            finally:
                monitor.join(timeout=10)
            self.assertFalse(monitor.is_alive())
            state = launcher.read_json(directory / "process.json")
            self.assertEqual(state["state"], "unexpected_exit")
            self.assertNotEqual(state["exitCode"], 0)

    def test_launch_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as root:
            directory = launcher.new_run_directory([Path(root)])
            self.assertEqual(launcher.supervise(directory, [str(Path(root) / "missing.exe")]), 1)
            self.assertEqual(launcher.read_json(directory / "process.json")["state"], "launch_error")

    def test_supervised_private_gui_cli_capture_and_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".library-cli-test").touch()
            (root / "config.json").write_text(json.dumps({
                "outputDir": str(root / "downloads"), "clipboardMonitor": False,
                "clipboardAutoDownload": False, "recoverInterruptedOnStartup": False,
                "trayEnabled": False, "closeToTray": False,
            }), encoding="utf-8")
            directory = launcher.new_run_directory([root / "runtime"])
            monitor = threading.Thread(target=launcher.supervise, args=(directory,
                [sys.executable, str(FIXTURE), str(directory), "gui", str(root)]))
            command = [sys.executable, "-X", "utf8", str(FIXTURE.with_name("library_cli_host.py")), str(root)]
            def cli(*args):
                return subprocess.run([*command, *args], capture_output=True, encoding="utf-8", timeout=10,
                                      env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            monitor.start()
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    status = cli("status", "--json")
                    if status.returncode == 0:
                        break
                    self.assertTrue(monitor.is_alive(), launcher.read_json(directory / "process.json"))
                    time.sleep(0.1)
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertEqual(json.loads(status.stdout)["totalJobCount"], 0)
                capture = root / "private-gui.png"
                shot = cli("screenshot", "--output", str(capture))
                self.assertEqual(shot.returncode, 0, shot.stderr)
                self.assertGreater(capture.stat().st_size, 1000)
                result = cli("quit")
                self.assertEqual(result.returncode, 0, result.stderr)
                monitor.join(timeout=10)
                self.assertFalse(monitor.is_alive())
                state = launcher.read_json(directory / "process.json")
                self.assertEqual(state["state"], "normal_exit")
                child = launcher.read_json(directory / "child.json")
                self.assertEqual(child["close"]["source"], "cli_quit")
                self.assertTrue(child["close"]["historyFlushed"])
                events = (directory / "events.log").read_text(encoding="utf-8")
                for event in ("gui_ready", "close_accepted", "qt_about_to_quit"):
                    self.assertIn(event, events)
            finally:
                if monitor.is_alive():
                    try:
                        cli("quit", "--force")
                    finally:
                        monitor.join(timeout=10)
                        if monitor.is_alive():
                            import psutil
                            psutil.Process(launcher.read_json(directory / "process.json")["childPid"]).kill()
                            monitor.join(timeout=5)

    def test_retention_preserves_active_unknown_files_and_other_directories(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for name in ("01", "02", "03", "active", "unrelated"):
                (root / name).mkdir()
                launcher.write_json(root / name / "process.json", {
                    "runId": name if name != "unrelated" else "not-owned",
                    "finishedAt": "done" if name != "active" else "",
                })
            (root / "01" / "user.txt").write_text("preserve")
            launcher.prune_finished_runs(root, keep=1)
            self.assertTrue((root / "01" / "user.txt").is_file())
            self.assertFalse((root / "02").exists())
            self.assertTrue((root / "03").exists())
            self.assertTrue((root / "active" / "process.json").exists())
            self.assertTrue((root / "unrelated" / "process.json").exists())

    def test_log_rotation_and_status_are_bounded_and_readonly(self):
        with tempfile.TemporaryDirectory() as root:
            directory = launcher.new_run_directory([Path(root)])
            session = launcher.RuntimeSession(directory)
            try:
                for _ in range(550):
                    session.event("stdout", text="x" * 4096)
            finally:
                session.close()
            self.assertTrue((directory / "events.log.1").exists())
            self.assertLess((directory / "events.log").stat().st_size, launcher.MAX_LOG_BYTES + 8192)
            before = (directory / "process.json").read_bytes()
            report = launcher.runtime_status([Path(root)], limit=1)
            self.assertFalse(report["runs"][0]["exitObserved"])
            self.assertEqual(before, (directory / "process.json").read_bytes())

    def test_unwritable_root_uses_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            bad, good = Path(root) / "file", Path(root) / "fallback"
            bad.write_text("not a directory")
            self.assertEqual(launcher.new_run_directory([bad, good]).parent, good)

    def test_taskbar_inspection_is_passive_and_repair_is_explicit_hidden(self):
        if os.name != "nt":
            self.skipTest("Windows flags")
        with patch("toki_launcher.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"ok":true}'
            launcher.taskbar_shortcuts()
            self.assertNotIn("-Repair", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
            launcher.taskbar_shortcuts(True)
            self.assertIn("-Repair", run.call_args.args[0])
            run.return_value.stdout = '{"ok":true,"shortcuts":[{"needsRepair":false,"path":"private-test.lnk"}]}'
            with patch("toki_windows_launch.notify_shortcut_changed") as notify:
                launcher.taskbar_shortcuts()
                notify.assert_not_called()
                launcher.taskbar_shortcuts(True)
                notify.assert_called_once_with("private-test.lnk")

    def test_relaunch_command_contains_script_and_quotes_spaces(self):
        root = Path(tempfile.gettempdir()) / "toki path"
        properties = relaunch_properties(root)
        self.assertIn('toki_launcher.py" launch', properties["command"])
        self.assertIn('pythonw.exe"', properties["command"])
        self.assertEqual(properties["appId"], APP_ID)
        self.assertTrue(properties["icon"].endswith(".ico,0"))
        report = apply_window_relaunch(123, root, native=lambda hwnd, values: values)
        self.assertTrue(report["applied"])
        failed = apply_window_relaunch(123, root, native=lambda hwnd, values: {})
        self.assertFalse(failed["applied"])

    @unittest.skipUnless(os.name == "nt", "Windows property store integration")
    def test_native_window_relaunch_properties_roundtrip_and_clear(self):
        # A private, never-visible Win32 window. The full suite runs Qt offscreen,
        # whose synthetic winId is not an HWND and cannot test Shell properties.
        import ctypes as c
        user = c.WinDLL("user32", use_last_error=True)
        create = user.CreateWindowExW
        create.argtypes = [c.c_ulong, c.c_wchar_p, c.c_wchar_p, c.c_ulong,
                           c.c_int, c.c_int, c.c_int, c.c_int,
                           c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
        create.restype = c.c_void_p
        user.DestroyWindow.argtypes = [c.c_void_p]
        hwnd = create(0, "STATIC", "toki-private-property-test", 0x80000000,
                      0, 0, 1, 1, None, None, None, None)
        self.assertTrue(hwnd, c.get_last_error())
        try:
            desired = relaunch_properties(launcher.ROOT)
            self.assertEqual(window_properties(hwnd, desired), desired)
            self.assertEqual(window_properties(hwnd), desired)
            self.assertEqual(window_properties(hwnd, {k: None for k in desired}), {k: "" for k in desired})
        finally:
            user.DestroyWindow(hwnd)


if __name__ == "__main__":
    unittest.main()
