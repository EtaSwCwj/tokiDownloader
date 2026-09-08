import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QThreadPool, Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QListView, QVBoxLayout, QWidget, QMessageBox, QComboBox
from PyQt6.QtTest import QTest

import toki_core as core
import toki_app
from toki_gui import JobListModel, MainWindow, SettingsDialog
from toki_library_gui import LibraryWindowMixin
import test_toki_library as library_tests


class Harness(LibraryWindowMixin, QMainWindow):
    _episode_rename_execute_conflict = MainWindow._episode_rename_execute_conflict
    _conflicting_operations_for_episode_rename = MainWindow._conflicting_operations_for_episode_rename

    def __init__(self, jobs):
        super().__init__()
        self.config = core.default_config()
        self.initialize_library()
        self.jobs = {j.job_id: j for j in jobs}
        self.jobs_by_work = {j.work_key: j for j in jobs}
        self.dirty_job_ids = set()
        self.pending_jobs = []
        self.active_contexts = {}
        self.io_thread_pool = QThreadPool(self)
        self.task_model = JobListModel(self)
        self.task_model.replace_jobs(jobs)
        self.task_list = QListView()
        self.task_list.setModel(self.task_model)
        self.setup_library_selection()
        self.setCentralWidget(self.task_list)
        self.resize(700, 300)
        self.messages = []

    def selected_job(self, job_id):
        return self.jobs.get(job_id)

    def log(self, message, *_args, **_kwargs):
        self.messages.append(message)

    def _flush_job_history(self):
        pass

    def _maybe_trigger_completion_action(self):
        pass

    def apply_history_filters(self):
        self.task_model.replace_jobs(core.load_jobs_page(100))


class LibraryGuiTests(unittest.TestCase):
    setUp = library_tests.LibraryTests.setUp
    work = library_tests.LibraryTests.work
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["library-qa"])

    def wait_task(self, window):
        deadline = time.monotonic() + 5
        idle_ticks = 0
        while time.monotonic() < deadline:
            self.app.processEvents()
            idle_ticks = idle_ticks + 1 if not window.library_tasks else 0
            if idle_ticks >= 2:
                break
            time.sleep(0.01)
        self.assertFalse(window.library_tasks)

    def test_ctrl_selection_delete_key_and_preview_do_not_immediately_delete(self):
        a, root_a, _ = self.work("a")
        b, root_b, _ = self.work("b")
        window = Harness([a, b])
        try:
            window.show()
            window.activateWindow()
            window.task_list.setFocus()
            self.app.processEvents()
            first = window.task_list.visualRect(window.task_model.index(0, 0)).center()
            second = window.task_list.visualRect(window.task_model.index(1, 0)).center()
            QTest.mouseClick(window.task_list.viewport(), Qt.MouseButton.LeftButton, pos=first)
            QTest.mouseClick(window.task_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=second)
            self.assertEqual(set(window.selected_job_ids()), {"a", "b"})
            QTest.keyClick(window.task_list, Qt.Key.Key_Delete)
            self.app.processEvents()
            dialog = window.active_library_dialog
            self.assertIsNotNone(dialog)
            self.assertEqual(len(dialog.action_buttons), 4)
            self.assertEqual(dialog.findChildren(QComboBox), [])
            self.assertFalse(dialog.execute_button.isEnabled())
            self.assertFalse(dialog.preview_button.isEnabled())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as confirm:
                dialog.action_buttons["delete:records"].click()
                self.wait_task(window)
                self.assertEqual(confirm.call_count, 1)
            self.assertTrue(dialog.execute_button.isEnabled())
            self.assertIsNotNone(core.load_job_by_id("a"))
            self.assertTrue(root_a.exists() and root_b.exists())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                # A single action-button click must preview, confirm, execute and refresh.
                dialog.action_buttons["delete:records"].click()
                self.wait_task(window)
            self.assertIsNone(core.load_job_by_id("a"))
            self.assertIsNone(core.load_job_by_id("b"))
            self.assertTrue(root_a.exists() and root_b.exists())
            self.assertEqual(window.task_model.rowCount(), 0)
            self.assertFalse(dialog.isVisible())
        finally:
            if window.active_library_dialog:
                window.active_library_dialog.close()
            window.io_thread_pool.waitForDone()
            window.close()

    def test_action_buttons_preview_each_operation_without_deleting(self):
        job, root, episode = self.work()
        window = Harness([job])
        try:
            window.show_library_dialog([job.job_id])
            dialog = window.active_library_dialog
            for action in ("delete:records", "delete:files", "delete:archives", "cancel-downloads"):
                with self.subTest(action=action):
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                        dialog.action_buttons[action].click()
                        self.wait_task(window)
                    self.assertEqual(dialog.selected_action, action)
                    self.assertEqual(sum(b.isChecked() for b in dialog.action_buttons.values()), 1)
                    self.assertFalse(dialog.plan["executed"])
                    self.assertTrue(dialog.execute_button.isEnabled())
                    self.assertIsNotNone(core.load_job_by_id(job.job_id))
                    self.assertEqual(len(list(episode.glob("*.jpg"))), 3)
                    self.assertFalse((root / ".toki-trash").exists())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                dialog.execute_button.click()
            self.assertFalse(window.library_tasks)
            self.assertFalse(dialog.plan["executed"])
        finally:
            if window.active_library_dialog:
                window.active_library_dialog.close()
            window.io_thread_pool.waitForDone()
            window.close()

    def test_cli_dialog_choice_selects_button_and_can_preview(self):
        job, root, _ = self.work()
        window = Harness([job])
        try:
            with patch.object(QMessageBox, "question") as confirm:
                window.show_library_dialog([job.job_id], operation="delete:files", preview=True)
                self.app.processEvents()
                self.wait_task(window)
                confirm.assert_not_called()
            dialog = window.active_library_dialog
            self.assertTrue(dialog.action_buttons["delete:files"].isChecked())
            self.assertEqual(dialog.plan["kind"], "files")
            self.assertFalse(dialog.plan["executed"])
            self.assertFalse((root / ".toki-trash").exists())
        finally:
            if window.active_library_dialog:
                window.active_library_dialog.close()
            window.io_thread_pool.waitForDone()
            window.close()

    def test_closing_dialog_during_preview_never_confirms_or_deletes(self):
        job, root, _ = self.work()
        window = Harness([job])
        try:
            window.show_library_dialog([job.job_id])
            with patch.object(QMessageBox, "question") as confirm:
                window.active_library_dialog.action_buttons["delete:records"].click()
                window.active_library_dialog.close()
                self.wait_task(window)
                confirm.assert_not_called()
            self.assertIsNotNone(core.load_job_by_id(job.job_id))
            self.assertTrue(root.exists())
        finally:
            window.io_thread_pool.waitForDone()
            window.close()

    def test_gui_archive_worker_uses_shared_service_and_releases_mutation_lock(self):
        job, root, episode = self.work()
        window = Harness([job])
        try:
            response = window.start_library_operation([job.job_id], "archive", execute=True, remove_originals=True)
            conflict = MainWindow._episode_rename_execute_conflict(window, job)
            self.assertIsNotNone(conflict)
            self.wait_task(window)
            result = window.library_results[response["operationId"]]
            self.assertEqual(result["error"], "")
            self.assertTrue(result["result"]["success"])
            self.assertFalse(episode.exists())
            self.assertIsNone(MainWindow._episode_rename_execute_conflict(window, job))
        finally:
            window.io_thread_pool.waitForDone()
            window.close()

    def test_library_cli_requires_confirmation_and_routes_multiple_ids(self):
        job, root, _ = self.work()
        args = toki_app.build_parser().parse_args(["library", "delete", "--job", job.job_id, "--execute"])
        with self.assertRaises(toki_app.ControlError):
            toki_app.run_cli(args)
        args = toki_app.build_parser().parse_args([
            "library", "archive", "--job", "a", "--job", "b", "--remove-originals", "--execute", "--yes",
        ])
        with patch.object(toki_app, "gui_is_running", return_value=True), patch.object(toki_app, "ensure_gui_running"), patch.object(toki_app, "print_json"), patch.object(toki_app, "control_request", return_value={"operationId": "test"}) as request:
            self.assertEqual(toki_app.run_cli(args), 0)
        self.assertEqual(request.call_args.args[0]["jobIds"], ["a", "b"])
        self.assertTrue(request.call_args.args[0]["removeOriginals"])

    def test_delete_without_selection_is_harmless(self):
        window = Harness([])
        try:
            window.delete_selection_action.trigger()
            self.assertIsNone(window.active_library_dialog)
            self.assertIn("선택", window.statusBar().currentMessage())
        finally:
            window.close()

    def test_automatic_archive_waits_for_conflicts_and_stops_on_exit(self):
        job, _, episode = self.work()
        window = Harness([job])
        try:
            window.config["archiveAfterDownload"] = True
            window.queue_auto_archive(job)
            self.assertIn(job.job_id, window.pending_auto_archives)
            with patch.object(Harness, "_conflicting_operations_for_episode_rename", return_value=["PDF"]):
                window.drain_auto_archives()
            self.assertFalse(window.library_tasks)
            self.assertTrue(episode.exists())
            window.exit_requested = True
            window.drain_auto_archives()
            self.assertFalse(window.pending_auto_archives)
            self.assertFalse(window.library_tasks)
        finally:
            window.close()

    def test_automatic_archive_completes_after_download_and_settings_are_searchable(self):
        job, root, episode = self.work()
        window = Harness([job])
        try:
            window.config["archiveAfterDownload"] = True
            window.queue_auto_archive(job)
            window.drain_auto_archives()
            self.wait_task(window)
            self.assertFalse(episode.exists())
            self.assertEqual(len(list((root / "_archives").glob("*.zip"))), 1)
            self.assertFalse(window.pending_auto_archives)
            for query in ("ZIP", "원본 정리", "자동 압축"):
                self.assertIn(3, SettingsDialog.matching_tab_indexes(query))
        finally:
            window.io_thread_pool.waitForDone()
            window.close()
