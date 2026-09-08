"""Run the real application with isolated test data and a private IPC endpoint."""
import hashlib
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))
runtime = Path(sys.argv.pop(1)).resolve(strict=True)
if not (runtime / ".library-cli-test").is_file():
    raise SystemExit("Missing isolated test marker")

import toki_core as core

core.CONFIG_PATH = runtime / "config.json"
core.JOB_DB_PATH = runtime / "jobs.db"
core.LOG_DIR = runtime / "logs"
core.LOG_PATH = core.LOG_DIR / "gui.log"
core.THUMBNAIL_CACHE_DIR = runtime / "thumbnails"
core.CONTROL_SERVER_NAME = "tokiLibraryTest_" + hashlib.sha256(str(runtime).encode()).hexdigest()[:16]

import toki_app

# Keep a failed private-IPC probe visible when a CLI unexpectedly takes its
# offline route. Normal JSON output and production behavior are unchanged.
_control_request = toki_app.control_request

def traced_control_request(*args, **kwargs):
    try:
        return _control_request(*args, **kwargs)
    except toki_app.ControlError as error:
        print(f"[private IPC] {args[0].get('action')}: {error}", file=sys.stderr)
        raise

toki_app.control_request = traced_control_request

def refuse_unisolated_gui_start():
    raise toki_app.ControlError("The isolated test GUI must already be running")

# The production launcher cannot inherit this fixture's private paths. A failed
# ping must never launch it against the user's real database from a test.
toki_app.start_gui_background = refuse_unisolated_gui_start

# Optional clipboard integration harness. The offscreen platform provides a
# process-private QClipboard, never the user's Windows clipboard. Only process
# launch is replaced; real clipboard signals, enqueue, settings, IPC and DB run.
if (runtime / ".clipboard-auto-test").is_file():
    import os
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        raise SystemExit("Clipboard tests require the offscreen platform")
    from PyQt6.QtWidgets import QApplication
    import toki_gui

    toki_gui.MainWindow._start_next_job = lambda self: self._flush_job_history()
    production_action = toki_gui.MainWindow._handle_control_action

    def clipboard_test_action(self, request):
        if request.get("action") == "test_clipboard_copy":
            self.url_edit.setText("typed URL must stay untouched")
            self.start_spin.setValue(13)
            self.last_spin.setValue(15)
            self.showMinimized()
            QApplication.clipboard().setText(str(request["text"]))
            self._flush_job_history()
            return {
                "inspection": self.last_clipboard_inspection,
                "formUrl": self.url_edit.text(),
                "start": self.start_spin.value(),
                "last": self.last_spin.value(),
                "minimized": self.isMinimized(),
                "processing": self._clipboard_processing,
            }
        if request.get("action") == "test_clipboard_settings":
            self.show_settings_dialog()
            dialog = self.active_settings_dialog
            result = {
                "monitorChecked": dialog.clipboard_monitor_check.isChecked(),
                "autoSelected": dialog.clipboard_mode_combo.currentData(),
                "modeEnabled": dialog.clipboard_mode_combo.isEnabled(),
            }
            self.close_settings_dialog()
            return result
        return production_action(self, request)

    toki_gui.MainWindow._handle_control_action = clipboard_test_action
    if sys.argv[1] == "test-clipboard-copy":
        toki_app.print_json(toki_app.control_request({"action": "test_clipboard_copy", "text": sys.argv[2]}))
        raise SystemExit(0)
    if sys.argv[1] == "test-clipboard-settings":
        toki_app.print_json(toki_app.control_request({"action": "test_clipboard_settings"}))
        raise SystemExit(0)

raise SystemExit(toki_app.main())
