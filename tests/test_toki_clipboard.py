"""Bounded URL inspection and the exact GUI/CLI clipboard enqueue path."""
import json
import os
import sqlite3
import unittest
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import toki_core as core
from toki_app import ControlError, build_parser, run_cli
from toki_gui import MainWindow, QMessageBox


URL = "https://newtoki1.org/manhwa/34360"


class ClipboardCoreTests(unittest.TestCase):
    def test_canonical_work_urls_and_punctuation(self):
        for text in (URL, URL + "/", URL + "?epage=3#comments", "복사: (" + URL + ").",
                     "HTTPS://NEWTOKI1.ORG:443/manhwa/34360"):
            with self.subTest(text=text):
                result = core.inspect_clipboard_url(text)
                self.assertTrue(result["candidate"])
                self.assertEqual(result["url"], URL)
                self.assertEqual(result["workKey"], "manatoki:34360")
                self.assertEqual(result["validation"], "url_shape_only")

    def test_other_sites_chapters_and_deceptive_urls_are_rejected(self):
        for url in (
            "https://newtoki1.org/", URL + "/1", URL + "extra", URL + "%2f1",
            "https://example.com/manhwa/34360", "https://newtoki1.org.evil.com/manhwa/34360",
            "https://newtoki1.org@evil.com/manhwa/34360", "https://evil@newtoki1.org/manhwa/34360",
            "https://newtoki1.org:444/manhwa/34360", "https://newtoki1.org:abc/manhwa/34360",
            "https://newtoki1.org/manhwa/0", "https://newtoki1.org/manhwa/034360",
            "https://newtoki1.org/manhwa/34360/../1", "https://newtoki1.org\\evil/manhwa/34360",
            "https://newtoki1.org./manhwa/34360", "https://[bad/manhwa/34360",
            "https://manatoki999.net/comic/34360", "https://newtoki999.com/webtoon/34360",
            "https://booktoki999.com/novel/34360", "https://www.youtube.com/watch?v=abcdefghijk",
            "http://newtoki1.org/manhwa/34360", "https://newtoki1.org/manhwa/34360\x00",
        ):
            with self.subTest(url=url):
                self.assertFalse(core.inspect_clipboard_url(url)["candidate"])

    def test_first_supported_url_only_and_duplicate_domain_variants(self):
        result = core.inspect_clipboard_url("https://example.com/page " + URL + " " + URL[:-1])
        self.assertEqual(result["url"], URL)
        duplicate = core.inspect_clipboard_url(
            URL.replace("newtoki1", "newtoki2") + "?epage=2", existing_work_keys={"manatoki:34360": object()}
        )
        self.assertTrue(duplicate["duplicate"])

    def test_text_and_url_count_limits(self):
        self.assertEqual(core.inspect_clipboard_url("x" * 65_537 + URL)["reason"], "text_too_long")
        self.assertFalse(core.inspect_clipboard_url("https://example.com/ " * 32 + URL)["candidate"])
        self.assertTrue(core.inspect_clipboard_url("https://example.com/ " * 31 + URL)["candidate"])
        self.assertEqual(core.inspect_clipboard_url("")["reason"], "no_https_url")

    def test_config_migration_preserves_confirmation_and_requires_real_boolean(self):
        values = core.normalize_config({"configVersion": 29, "clipboardMonitor": True})
        self.assertTrue(values["clipboardMonitor"])
        self.assertFalse(values["clipboardAutoDownload"])
        self.assertEqual(values["configVersion"], core.CONFIG_SCHEMA_VERSION)
        self.assertEqual(core.validate_app_setting_updates({"clipboardAutoDownload": True}),
                         {"clipboardAutoDownload": True})
        with self.assertRaises(ValueError):
            core.validate_app_setting_updates({"clipboardAutoDownload": "false"})


class ClipboardGuiTests(unittest.TestCase):
    def harness(self):
        h = SimpleNamespace(
            config={**core.default_config(), "clipboardMonitor": True, "clipboardAutoDownload": True,
                    "outputDir": "D:/saved-output", "archiveAfterDownload": True},
            jobs_by_work={}, statusBar=Mock(return_value=Mock()), log=Mock(),
            url_edit=Mock(), start_from_form=Mock(),
            last_clipboard_fingerprint="", _clipboard_processing=False, last_clipboard_inspection={},
        )
        def add(**kwargs):
            job = core.DownloadJob(job_id="clipboard-test", url=kwargs["url"], output_dir=kwargs["output_dir"])
            h.jobs_by_work[job.work_key] = job
            return job
        h.enqueue_download = Mock(side_effect=add)
        h.inspect_clipboard_text = lambda *a, **kw: MainWindow.inspect_clipboard_text(h, *a, **kw)
        h._clipboard_changed = lambda **kw: MainWindow._clipboard_changed(h, **kw)
        return h

    def test_inspection_is_passive_even_with_auto_mode_enabled(self):
        h = self.harness()
        with patch("toki_gui.load_job_by_work_key", return_value=None), patch("toki_gui.QMessageBox.question") as question:
            result = h.inspect_clipboard_text(URL)
        self.assertTrue(result["candidate"])
        self.assertFalse(result["enqueued"])
        h.enqueue_download.assert_not_called()
        question.assert_not_called()

    def test_auto_enqueue_keeps_form_and_uses_saved_output_full_work_scan(self):
        h = self.harness()
        with patch("toki_gui.load_job_by_work_key", return_value=None), patch("toki_gui.QMessageBox.question") as question:
            result = h.inspect_clipboard_text(URL + "?epage=2", enqueue=True)
        self.assertTrue(result["enqueued"])
        self.assertEqual(result["jobId"], "clipboard-test")
        self.assertFalse(result["prompted"])
        h.enqueue_download.assert_called_once_with(url=URL, start=None, last=None, output_dir="D:/saved-output",
                                                   show_browser=False, metadata_only=False, scan_mode="new")
        h.url_edit.setText.assert_not_called()
        h.start_from_form.assert_not_called()
        question.assert_not_called()
        self.assertTrue(h.config["archiveAfterDownload"])

    def test_active_duplicate_in_memory_or_unloaded_database_never_enqueues(self):
        for in_memory in (False, True):
            with self.subTest(in_memory=in_memory):
                h = self.harness()
                job = core.DownloadJob(job_id="existing", url=URL, output_dir="D:/old")
                if in_memory:
                    h.jobs_by_work[job.work_key] = job
                with patch("toki_gui.load_job_by_work_key", return_value=job):
                    result = h.inspect_clipboard_text(URL, enqueue=True)
                self.assertTrue(result["duplicate"])
                self.assertFalse(result["enqueued"])
                self.assertEqual(result["reason"], "already_active")
                h.enqueue_download.assert_not_called()

    def test_finished_duplicate_refreshes_new_episodes_using_its_saved_folder(self):
        for state in ("완료", "오류", "중지됨", "취소됨", "인증 필요"):
            for in_memory in (True, False):
                with self.subTest(state=state, in_memory=in_memory):
                    h = self.harness()
                    old = core.DownloadJob(job_id="existing", url=URL, state=state, output_dir="D:/old",
                                           start=13, last=15, scan_mode="range", show_browser=True)
                    if in_memory:
                        h.jobs_by_work[old.work_key] = old
                    with patch("toki_gui.load_job_by_work_key", return_value=old):
                        result = h.inspect_clipboard_text(URL.replace("newtoki1", "newtoki2"), enqueue=True)
                    self.assertTrue(result["duplicate"])
                    self.assertTrue(result["refreshed"])
                    self.assertTrue(result["enqueued"])
                    self.assertEqual(result["reason"], "refresh_queued")
                    h.enqueue_download.assert_called_once_with(
                        url=URL.replace("newtoki1", "newtoki2"), start=None, last=None,
                        output_dir="D:/old", show_browser=True, scan_mode="new", metadata_only=False)

    def test_all_active_states_keep_existing_job_without_confirmation(self):
        for state in core.ACTIVE_JOB_STATES:
            h = self.harness()
            old = core.DownloadJob(job_id="existing", url=URL, state=state, output_dir="D:/old")
            h.jobs_by_work[old.work_key] = old
            with patch("toki_gui.QMessageBox.question") as question:
                result = h.inspect_clipboard_text(URL, prompt=True)
            self.assertEqual(result["reason"], "already_active")
            self.assertFalse(result["refreshed"])
            h.enqueue_download.assert_not_called()
            question.assert_not_called()

    def test_finished_duplicate_inspection_stays_read_only(self):
        h = self.harness()
        old = core.DownloadJob(job_id="existing", url=URL, state="완료", output_dir="D:/old")
        with patch("toki_gui.load_job_by_work_key", return_value=old):
            result = h.inspect_clipboard_text(URL)
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["enqueued"])
        h.enqueue_download.assert_not_called()

    def test_confirmation_explains_existing_work_refresh(self):
        h = self.harness()
        old = core.DownloadJob(job_id="existing", url=URL, state="완료", output_dir="D:/old")
        with patch("toki_gui.load_job_by_work_key", return_value=old), patch(
            "toki_gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ) as question:
            result = h.inspect_clipboard_text(URL, prompt=True)
        self.assertIn("새 회차만", question.call_args.args[2])
        self.assertTrue(result["refreshed"])

    def test_confirmation_rechecks_a_newly_completed_work_and_refreshes_it(self):
        h = self.harness()
        old = core.DownloadJob(job_id="existing", url=URL, state="완료", output_dir="D:/old")
        with patch("toki_gui.load_job_by_work_key", side_effect=[None, old]), patch(
            "toki_gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            result = h.inspect_clipboard_text(URL, prompt=True)
        self.assertTrue(result["refreshed"])
        self.assertEqual(h.enqueue_download.call_args.kwargs["output_dir"], "D:/old")

    def test_same_text_can_be_copied_again_after_completion_but_not_by_deferred_recheck(self):
        h = self.harness()
        clipboard = Mock()
        clipboard.text.return_value = URL
        with patch("toki_gui.QApplication.clipboard", return_value=clipboard), patch("toki_gui.QTimer.singleShot"), patch(
            "toki_gui.load_job_by_work_key", return_value=None
        ):
            h._clipboard_changed()
            h.jobs_by_work["manatoki:34360"].state = "완료"
            h._clipboard_changed(recheck=True)
            self.assertEqual(h.enqueue_download.call_count, 1)
            h._clipboard_changed()
            self.assertTrue(h.last_clipboard_inspection["refreshed"])
            self.assertEqual(h.enqueue_download.call_count, 2)
            h._clipboard_changed()
            self.assertEqual(h.enqueue_download.call_count, 2)

    def test_confirmation_can_accept_or_cancel_without_form_mutation(self):
        for answer in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No):
            h = self.harness()
            with patch("toki_gui.load_job_by_work_key", return_value=None), patch("toki_gui.QMessageBox.question", return_value=answer):
                result = h.inspect_clipboard_text(URL, prompt=True)
            self.assertTrue(result["prompted"])
            self.assertEqual(result["enqueued"], answer == QMessageBox.StandardButton.Yes)
            h.url_edit.setText.assert_not_called()

    def test_confirmation_rechecks_duplicate_registered_while_dialog_open(self):
        h = self.harness()
        job = core.DownloadJob(job_id="existing", url=URL, output_dir="D:/old")
        with patch("toki_gui.load_job_by_work_key", side_effect=[None, job]), patch(
            "toki_gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            result = h.inspect_clipboard_text(URL, prompt=True)
        self.assertTrue(result["duplicate"])
        h.enqueue_download.assert_not_called()

    def test_enqueue_failures_are_reported_not_falsely_successful(self):
        for error in (ValueError("queue full"), OSError("output unavailable"), sqlite3.OperationalError("db locked")):
            h = self.harness()
            h.enqueue_download.side_effect = error
            with patch("toki_gui.load_job_by_work_key", return_value=None):
                result = h.inspect_clipboard_text(URL, enqueue=True)
            self.assertFalse(result["ok"])
            self.assertFalse(result["enqueued"])
            self.assertEqual(result["reason"], "enqueue_failed")

    def test_watcher_dispatch_repeated_signals_empty_copy_and_disable(self):
        h = self.harness()
        clipboard = Mock()
        clipboard.text.return_value = URL
        with patch("toki_gui.QApplication.clipboard", return_value=clipboard), patch("toki_gui.QTimer.singleShot"), patch(
            "toki_gui.load_job_by_work_key", return_value=None
        ), patch("toki_gui.QMessageBox.question") as question:
            h._clipboard_changed()
            h._clipboard_changed()
            clipboard.text.return_value = ""
            h._clipboard_changed()
            clipboard.text.return_value = URL
            h._clipboard_changed()
            self.assertTrue(h.last_clipboard_inspection["duplicate"])
            self.assertEqual(h.enqueue_download.call_count, 1)
            h.config["clipboardMonitor"] = False
            clipboard.text.return_value = URL[:-1]
            h._clipboard_changed()
            self.assertEqual(h.enqueue_download.call_count, 1)
            question.assert_not_called()

    def test_watcher_handles_database_errors_and_bounds_clipboard_text(self):
        h = self.harness()
        clipboard = Mock()
        clipboard.text.return_value = URL
        with patch("toki_gui.QApplication.clipboard", return_value=clipboard), patch("toki_gui.QTimer.singleShot"), patch(
            "toki_gui.load_job_by_work_key", side_effect=sqlite3.OperationalError("db busy")
        ):
            h._clipboard_changed()
        self.assertFalse(h._clipboard_processing)
        self.assertEqual(h.last_clipboard_inspection["reason"], "clipboard_failed")
        clipboard.text.return_value = "sensitive text" * 100_000
        with patch("toki_gui.QApplication.clipboard", return_value=clipboard), patch("toki_gui.QTimer.singleShot"):
            h._clipboard_changed()
        self.assertEqual(h.last_clipboard_inspection["reason"], "text_too_long")
        self.assertEqual(len(h.last_clipboard_fingerprint), 64)
        h.enqueue_download.assert_not_called()

    def test_watcher_reentrancy_is_ignored_until_current_processing_finishes(self):
        h = self.harness()
        h._clipboard_processing = True
        with patch("toki_gui.QApplication.clipboard") as clipboard:
            h._clipboard_changed()
        clipboard.assert_not_called()

    def test_enqueue_ipc_uses_same_handler(self):
        h = SimpleNamespace(inspect_clipboard_text=Mock(return_value={"enqueued": True}))
        result = MainWindow._handle_control_action(h, {"action": "enqueue_clipboard", "text": URL})
        self.assertTrue(result["enqueued"])
        h.inspect_clipboard_text.assert_called_once_with(URL, enqueue=True)


class ClipboardCliTests(unittest.TestCase):
    def test_auto_mode_configuration_uses_gui_settings_api(self):
        args = build_parser().parse_args(["clipboard", "monitor", "--state", "on", "--mode", "auto"])
        with patch("toki_app.gui_is_running", return_value=True), patch(
            "toki_app.control_request", return_value={"clipboardMonitor": True, "clipboardAutoDownload": True}
        ) as request, redirect_stdout(StringIO()):
            self.assertEqual(run_cli(args), 0)
        request.assert_called_once_with({"action": "set_settings", "updates": {
            "clipboardMonitor": True, "clipboardAutoDownload": True}, "reset": False})

    def test_enqueue_requires_yes_and_passive_inspect_does_not_start_gui(self):
        args = build_parser().parse_args(["clipboard", "enqueue", "--text", URL])
        with patch("toki_app.ensure_gui_running") as ensure, self.assertRaises(ControlError):
            run_cli(args)
        ensure.assert_not_called()
        args = build_parser().parse_args(["clipboard", "inspect", "--text", URL])
        with patch("toki_app.ensure_gui_running") as ensure, patch("toki_app.load_job_by_work_key", return_value=None), redirect_stdout(StringIO()):
            self.assertEqual(run_cli(args), 0)
        ensure.assert_not_called()

    def test_enqueue_reports_failed_dispatch_with_nonzero_exit(self):
        args = build_parser().parse_args(["clipboard", "enqueue", "--text", URL, "--yes"])
        with patch("toki_app.ensure_gui_running"), patch("toki_app.control_request", return_value={"ok": False, "enqueued": False}) as request, redirect_stdout(StringIO()):
            self.assertEqual(run_cli(args), 2)
        request.assert_called_once_with({"action": "enqueue_clipboard", "text": URL})

    def test_offline_status_does_not_launch_gui(self):
        args = build_parser().parse_args(["clipboard", "status"])
        output = StringIO()
        with patch("toki_app.gui_is_running", return_value=False), patch("toki_app.load_config", return_value=core.default_config()), redirect_stdout(output):
            self.assertEqual(run_cli(args), 0)
        self.assertFalse(json.loads(output.getvalue())["guiRunning"])


if __name__ == "__main__":
    unittest.main()
