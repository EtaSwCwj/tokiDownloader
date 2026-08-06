from __future__ import annotations

import os
import subprocess
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from toki_core import DownloadJob, DownloadRun
from toki_gui import (
    ImageConversionProcessContext,
    JobListModel,
    MainWindow,
    ProcessContext,
    SettingsDialog,
    hidden_process_options,
)


class _ValueStub:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _SettingWidgetStub:
    def __init__(self) -> None:
        self.value = None
        self.blocked = False

    def blockSignals(self, blocked: bool) -> None:
        self.blocked = blocked

    def setValue(self, value: int) -> None:
        self.value = value

    def setText(self, value: str) -> None:
        self.value = value

    def setChecked(self, value: bool) -> None:
        self.value = value

    def setVisible(self, value: bool) -> None:
        self.value = value


class _SignalStub:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _ProcessStub:
    instances = []

    def __init__(self, _parent=None) -> None:
        self.readyReadStandardOutput = _SignalStub()
        self.readyReadStandardError = _SignalStub()
        self.started = _SignalStub()
        self.errorOccurred = _SignalStub()
        self.finished = _SignalStub()
        self.arguments = []
        self.started_called = False
        self.deleted = False
        self.killed = False
        self.__class__.instances.append(self)

    def setWorkingDirectory(self, _path: str) -> None:
        pass

    def setProgram(self, _program: str) -> None:
        pass

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = arguments

    def start(self) -> None:
        self.started_called = True

    def deleteLater(self) -> None:
        self.deleted = True

    def kill(self) -> None:
        self.killed = True


class _DialogStub:
    def __init__(self, *_args) -> None:
        self.destroyed = _SignalStub()

    def setAttribute(self, *_args) -> None:
        pass

    def show(self) -> None:
        pass

    def raise_(self) -> None:
        pass

    def activateWindow(self) -> None:
        pass


class WorkSchedulerTests(unittest.TestCase):
    def test_settings_search_catalog_matches_pages_without_opening_gui(self) -> None:
        self.assertEqual(SettingsDialog.matching_tab_indexes("테마"), [2])
        self.assertEqual(SettingsDialog.matching_tab_indexes("yt-dlp"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("존재하지않음"), [])
        self.assertEqual(SettingsDialog.matching_tab_indexes(""), [0, 1, 2, 3, 4])

    def test_settings_ipc_passes_tab_and_search_and_can_close(self) -> None:
        calls = []
        harness = type("SettingsIpcHarness", (), {})()
        harness.show_settings_dialog = (
            lambda tab, search: calls.append(("show", tab, search)) or True
        )
        harness.close_settings_dialog = lambda: calls.append(("close",)) or True

        shown = MainWindow._handle_control_action(
            harness,
            {"action": "show_settings", "tab": "provider", "search": "yt-dlp"},
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_settings"}
        )

        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(calls, [("show", "provider", "yt-dlp"), ("close",)])

    def test_settings_import_ipc_applies_executed_values_to_live_gui(self) -> None:
        applied = []
        harness = type("SettingsImportHarness", (), {})()
        harness.apply_settings = lambda values: applied.append(values) or values
        result = {
            "ok": True,
            "executed": True,
            "after": {"theme": "dark", "workConcurrency": 2},
        }

        with patch("toki_gui.import_app_settings", return_value=result) as importer:
            response = MainWindow._handle_control_action(
                harness,
                {
                    "action": "import_settings",
                    "input": "settings.json",
                    "execute": True,
                },
            )

        importer.assert_called_once_with(Path("settings.json"), execute=True)
        self.assertEqual(response, result)
        self.assertEqual(applied, [result["after"]])

    def test_diagnostics_ipc_action_passes_output_path(self) -> None:
        harness = type("DiagnosticsIpcHarness", (), {})()
        harness.export_diagnostic_bundle = lambda output: {
            "ok": True,
            "path": output,
        }

        result = MainWindow._handle_control_action(
            harness,
            {"action": "export_diagnostics", "output": "bundle.zip"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "bundle.zip")

    def test_doctor_ipc_actions_share_gui_dialog_contract(self) -> None:
        harness = type("DoctorIpcHarness", (), {})()
        harness.show_dependency_diagnostics = lambda: {"ok": True, "checks": []}
        harness.close_dependency_diagnostics = lambda: True

        shown = MainWindow._handle_control_action(harness, {"action": "show_doctor"})
        closed = MainWindow._handle_control_action(harness, {"action": "close_doctor"})

        self.assertTrue(shown["shown"])
        self.assertTrue(shown["report"]["ok"])
        self.assertTrue(closed["closed"])

    def test_stability_ipc_action_passes_request_values(self) -> None:
        calls = []
        harness = type("StabilityIpcHarness", (), {})()
        harness.active_performance_dialog = None
        harness.show_performance_diagnostics = lambda: calls.append(("show",))
        harness.start_stability_test = (
            lambda records, cycles, output: calls.append(
                ("start", records, cycles, output)
            )
            or True
        )
        harness.stability_test_snapshot = lambda: {"running": True, "last": None}

        result = MainWindow._handle_control_action(
            harness,
            {
                "action": "start_stability_test",
                "records": 2_000,
                "cycles": 25,
                "output": "report.json",
            },
        )

        self.assertTrue(result["started"])
        self.assertEqual(calls, [("show",), ("start", 2_000, 25, "report.json")])

    def test_stability_button_uses_background_cli_contract(self) -> None:
        status = type("StatusHarness", (), {"showMessage": lambda _self, *_args: None})()
        label = type("LabelHarness", (), {"setText": lambda _self, *_args: None})()
        harness = type("StabilityHarness", (), {})()
        harness.stability_test_process = None
        harness.stability_test_stdout = ""
        harness.stability_test_stderr = ""
        harness.last_stability_test = None
        harness.stability_test_snapshot = lambda: {"running": False, "last": None}
        harness._read_stability_test_stdout = lambda: None
        harness._read_stability_test_stderr = lambda: None
        harness._stability_test_process_error = lambda _error: None
        harness._stability_test_finished = lambda _code, _status: None
        harness._update_stability_test_dialog = lambda: None
        harness.statusBar = lambda: status
        harness.status_label = label
        harness.log = lambda *_args, **_kwargs: None
        _ProcessStub.instances = []

        with patch("toki_gui.create_background_process", _ProcessStub):
            started = MainWindow.start_stability_test(harness, 2_000, 25)

        process = _ProcessStub.instances[0]
        self.assertTrue(started)
        self.assertTrue(process.started_called)
        self.assertIn("stability", process.arguments)
        self.assertIn("2000", process.arguments)
        self.assertIn("25", process.arguments)
        self.assertIn("--json", process.arguments)

    def test_job_model_trims_tail_to_loaded_memory_limit(self) -> None:
        model = JobListModel()
        jobs = [
            DownloadJob(
                job_id=f"job-{index}",
                url=f"https://newtoki1.org/manhwa/{9400 + index}",
                output_dir=r"C:\Manga",
            )
            for index in range(5)
        ]
        model.append_jobs(jobs)

        removed = model.trim_to_limit(3)

        self.assertEqual(model.rowCount(), 3)
        self.assertEqual([job.job_id for job in removed], ["job-3", "job-4"])
        self.assertEqual(set(model.row_by_key), {job.work_key for job in jobs[:3]})

    def test_downloader_partial_line_buffer_is_bounded(self) -> None:
        job = DownloadJob(
            job_id="buffer-job",
            url="https://newtoki1.org/manhwa/9500",
            output_dir=r"C:\Manga",
        )
        context = ProcessContext(job=job, run=DownloadRun.from_job(job))
        harness = type("BufferHarness", (), {})()
        harness.active_contexts = {job.job_id: context}
        harness.resource_limits = {"maxProcessOutputBytes": 32}
        harness.total_output_dropped_bytes = 0
        harness._handle_process_line = lambda *_args: None

        MainWindow._consume_lines(harness, job.job_id, "가" * 100, False)

        self.assertLessEqual(len(context.stdout_buffer.encode("utf-8")), 32)
        self.assertGreater(context.stdout_dropped_bytes, 0)
        self.assertEqual(
            harness.total_output_dropped_bytes, context.stdout_dropped_bytes
        )

    def test_image_progress_events_merge_into_one_card_render(self) -> None:
        class TimerStub:
            def __init__(self) -> None:
                self.active = False
                self.starts = 0

            def isActive(self) -> bool:
                return self.active

            def start(self) -> None:
                self.active = True
                self.starts += 1

            def interval(self) -> int:
                return 100

        job = DownloadJob(
            job_id="progress-job",
            url="https://newtoki1.org/manhwa/9200",
            output_dir=r"C:\Manga",
        )
        rendered = []
        harness = type("EventUpdateHarness", (), {})()
        harness.pending_job_ui_updates = set()
        harness.job_ui_update_timer = TimerStub()
        harness.event_update_metrics = {
            "receivedEvents": 0,
            "immediateUpdates": 0,
            "queuedEvents": 0,
            "mergedEvents": 0,
            "flushes": 0,
            "renderedUpdates": 0,
        }
        harness.jobs = {job.job_id: job}
        harness._update_job_card = rendered.append

        for _index in range(100):
            MainWindow._schedule_job_card_update(harness, job, "image_saved")
        self.assertEqual(rendered, [])
        self.assertEqual(harness.job_ui_update_timer.starts, 1)
        self.assertEqual(harness.event_update_metrics["mergedEvents"], 99)

        MainWindow._flush_job_card_updates(harness)
        self.assertEqual(rendered, [job])
        MainWindow._schedule_job_card_update(harness, job, "completed")
        self.assertEqual(rendered, [job, job])

    def test_performance_benchmark_button_uses_background_cli_contract(self) -> None:
        status = type("StatusHarness", (), {"showMessage": lambda _self, *_args: None})()
        label = type("LabelHarness", (), {"setText": lambda _self, *_args: None})()
        harness = type("PerformanceHarness", (), {})()
        harness.performance_benchmark_process = None
        harness.performance_benchmark_stdout = ""
        harness.performance_benchmark_stderr = ""
        harness.last_performance_benchmark = None
        harness.active_performance_dialog = None
        harness.performance_benchmark_snapshot = lambda: {"running": False, "last": None}
        harness._read_performance_benchmark_stdout = lambda: None
        harness._read_performance_benchmark_stderr = lambda: None
        harness._performance_benchmark_process_error = lambda _error: None
        harness._performance_benchmark_finished = lambda _code, _status: None
        harness._update_performance_benchmark_dialog = lambda: None
        harness.statusBar = lambda: status
        harness.status_label = label
        harness.log = lambda *_args, **_kwargs: None
        _ProcessStub.instances = []

        with patch("toki_gui.create_background_process", _ProcessStub):
            started = MainWindow.start_performance_benchmark(harness)

        process = _ProcessStub.instances[0]
        self.assertTrue(started)
        self.assertTrue(process.started_called)
        self.assertIn("performance", process.arguments)
        self.assertIn("benchmark", process.arguments)
        self.assertIn("--json", process.arguments)

    def test_keyboard_selection_moves_and_wraps_visible_jobs(self) -> None:
        jobs = [
            DownloadJob(
                job_id=f"job-{index}",
                url=f"https://newtoki1.org/manhwa/{9300 + index}",
                output_dir=r"C:\Manga",
                title=f"작품 {index}",
            )
            for index in range(2)
        ]

        class IndexStub:
            def __init__(self, row: int) -> None:
                self._row = row

            def row(self) -> int:
                return self._row

            def isValid(self) -> bool:
                return self._row >= 0

        class ModelStub:
            def rowCount(self) -> int:
                return len(jobs)

            def index(self, row: int, _column: int) -> IndexStub:
                return IndexStub(row)

            def job_at(self, row: int) -> DownloadJob | None:
                return jobs[row] if 0 <= row < len(jobs) else None

        class ListStub:
            def __init__(self) -> None:
                self.index = IndexStub(0)

            def currentIndex(self) -> IndexStub:
                return self.index

            def setCurrentIndex(self, index: IndexStub) -> None:
                self.index = index

            def scrollTo(self, _index: IndexStub) -> None:
                pass

            def setFocus(self) -> None:
                pass

        harness = type("KeyboardHarness", (), {})()
        harness.task_model = ModelStub()
        harness.task_list = ListStub()
        harness.statusBar = lambda: type(
            "StatusHarness", (), {"showMessage": lambda _self, *_args: None}
        )()
        harness.keyboard_focus_snapshot = lambda: {
            "selectedRow": harness.task_list.currentIndex().row()
        }

        first = MainWindow.move_job_selection(harness, 1)
        wrapped = MainWindow.move_job_selection(harness, 1)

        self.assertTrue(first["moved"])
        self.assertEqual(first["selectedRow"], 1)
        self.assertEqual(wrapped["selectedRow"], 0)

    def test_list_state_recovery_actions_are_connected(self) -> None:
        calls = []
        url = type(
            "UrlHarness",
            (),
            {
                "setFocus": lambda _self: calls.append("focus"),
                "selectAll": lambda _self: calls.append("select"),
            },
        )()
        harness = type("ListStateHarness", (), {})()
        harness.url_edit = url
        harness.reset_history_filters = lambda: calls.append("reset")
        harness.refresh_job_list = lambda: calls.append("retry")

        for action in ("focus_url", "reset_filters", "retry"):
            harness.list_view_state = {"action": action}
            MainWindow._handle_list_state_action(harness)

        self.assertEqual(calls, ["focus", "select", "reset", "retry"])

    def test_job_result_notifications_follow_settings(self) -> None:
        messages = []
        harness = type("NotificationHarness", (), {})()
        harness.config = {"notifyOnComplete": True, "notifyOnError": True}
        harness.show_tray_notification = lambda message: messages.append(message) or True
        completed = DownloadJob(
            job_id="done",
            url="https://newtoki1.org/manhwa/9901",
            output_dir=r"C:\Manga",
            title="완료 작품",
            state="완료",
        )
        failed = DownloadJob(
            job_id="failed",
            url="https://newtoki1.org/manhwa/9902",
            output_dir=r"C:\Manga",
            title="실패 작품",
            state="오류",
            error="네트워크 오류",
        )

        MainWindow._notify_job_result(harness, completed)
        MainWindow._notify_job_result(harness, failed)

        self.assertEqual(
            messages,
            ["다운로드 완료: 완료 작품", "실패 작품: 네트워크 오류"],
        )
        harness.config["notifyOnError"] = False
        MainWindow._notify_job_result(harness, failed)
        self.assertEqual(len(messages), 2)

    def test_windows_background_process_disables_console_window(self) -> None:
        options = hidden_process_options()
        if os.name == "nt":
            self.assertEqual(
                options["creationflags"] & subprocess.CREATE_NO_WINDOW,
                subprocess.CREATE_NO_WINDOW,
            )
            self.assertEqual(options["startupinfo"].wShowWindow, subprocess.SW_HIDE)
        else:
            self.assertEqual(options, {})

    def test_apply_settings_updates_all_live_controls_without_signal_writes(self) -> None:
        result = {
            "outputDir": r"C:\Manga",
            "showBrowser": True,
            "logVisible": False,
            "workConcurrency": 3,
            "imageConcurrency": 11,
            "retryCount": 4,
            "retryBackoffSeconds": 6,
            "logMaxMiB": 8,
            "logBackupCount": 3,
            "rowDensity": "compact",
            "theme": "dark",
        }
        harness = type("SettingsHarness", (), {})()
        harness.config = {}
        harness.output_edit = _SettingWidgetStub()
        harness.show_browser_check = _SettingWidgetStub()
        harness.work_concurrency_spin = _SettingWidgetStub()
        harness.image_concurrency_spin = _SettingWidgetStub()
        harness.retry_count_spin = _SettingWidgetStub()
        harness.retry_backoff_spin = _SettingWidgetStub()
        harness.log_box = _SettingWidgetStub()
        harness.task_list = type(
            "TaskListHarness",
            (),
            {
                "itemDelegate": lambda _self: None,
            },
        )()
        harness.log = lambda *_args, **_kwargs: None
        harness._start_next_job = lambda: None
        harness._resolve_theme = lambda mode: mode
        harness._apply_style = lambda: None
        harness._configure_tray = lambda: None
        harness.resolved_theme = "light"
        harness.theme_mode = "system"
        harness.active_settings_dialog = None

        with (
            patch("toki_gui.update_app_settings", return_value=result) as update,
            patch("toki_gui.QTimer.singleShot"),
        ):
            applied = MainWindow.apply_settings(
                harness, {"workConcurrency": 3, "logVisible": False}
            )

        update.assert_called_once_with(
            {"workConcurrency": 3, "logVisible": False}, reset=False
        )
        self.assertEqual(applied, result)
        self.assertEqual(harness.output_edit.value, r"C:\Manga")
        self.assertEqual(harness.work_concurrency_spin.value, 3)
        self.assertFalse(harness.log_box.value)
        self.assertTrue(
            all(
                not widget.blocked
                for widget in (
                    harness.work_concurrency_spin,
                    harness.image_concurrency_spin,
                    harness.retry_count_spin,
                    harness.retry_backoff_spin,
                )
            )
        )

    def test_image_conversion_gui_execution_uses_confirmed_cli_contract(self) -> None:
        job = DownloadJob(
            job_id="convert-job",
            url="https://newtoki1.org/manhwa/9100",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\작품",
            state="완료",
        )
        harness = type("ConversionHarness", (), {})()
        harness.image_conversion_processes = {}
        harness.resource_limits = {"cpuProcesses": 2}
        harness.active_image_conversion_dialog = None
        harness.active_image_conversion_progress_dialog = None
        harness.selected_job = lambda _job_id=None: job
        harness.log = lambda *_args, **_kwargs: None
        _ProcessStub.instances = []

        with (
            patch("toki_gui.create_background_process", _ProcessStub),
            patch("toki_gui.ImageConversionProgressDialog", _DialogStub),
        ):
            result = MainWindow.start_image_conversion(
                harness,
                job.job_id,
                "webp",
                82,
                execute=True,
            )

        process = _ProcessStub.instances[0]
        self.assertTrue(result["started"])
        self.assertTrue(process.started_called)
        self.assertIn("--execute", process.arguments)
        self.assertIn("--yes", process.arguments)
        self.assertIn("--progress-json", process.arguments)
        self.assertNotIn("--json", process.arguments)
        self.assertEqual(
            process.arguments[process.arguments.index("--quality") + 1], "82"
        )

    def test_image_conversion_cancel_is_cli_callable_and_idempotent(self) -> None:
        process = _ProcessStub()
        context = ImageConversionProcessContext(process=process, execute=True)
        harness = type("ConversionCancelHarness", (), {})()
        harness.image_conversion_processes = {"convert-job": context}
        harness.active_image_conversion_progress_dialog = None
        harness.log = lambda *_args, **_kwargs: None

        first = MainWindow.cancel_image_conversion(harness, "convert-job")
        second = MainWindow.cancel_image_conversion(harness, "convert-job")

        self.assertTrue(first["cancelled"])
        self.assertTrue(second["cancelled"])
        self.assertTrue(process.killed)
        self.assertTrue(context.cancel_requested)

    def test_image_conversion_progress_event_updates_dialog_and_final_result(self) -> None:
        process = _ProcessStub()
        context = ImageConversionProcessContext(process=process, execute=True)
        received = []
        dialog = type(
            "ProgressDialogHarness",
            (),
            {
                "job_id": "convert-job",
                "update_progress": lambda _self, event: received.append(event),
            },
        )()
        status = type(
            "StatusHarness", (), {"showMessage": lambda _self, *_args: None}
        )()
        harness = type("ConversionProgressHarness", (), {})()
        harness.image_conversion_processes = {"convert-job": context}
        harness.active_image_conversion_progress_dialog = dialog
        harness.statusBar = lambda: status

        MainWindow._handle_image_conversion_output_line(
            harness,
            "convert-job",
            '{"event":"progress","current":1,"total":2,"converted":1,"failed":0}',
        )
        MainWindow._handle_image_conversion_output_line(
            harness,
            "convert-job",
            '{"event":"result","result":{"success":true,"convertedCount":2}}',
        )

        self.assertEqual(received[0]["current"], 1)
        self.assertTrue(context.result["success"])

    def test_scheduler_starts_distinct_process_contexts_up_to_work_limit(self) -> None:
        jobs = [
            DownloadJob(
                job_id=f"job-{index}",
                url=f"https://newtoki1.org/manhwa/{8000 + index}",
                output_dir=r"C:\Manga",
            )
            for index in range(3)
        ]
        harness = type("SchedulerHarness", (), {})()
        harness.work_concurrency_spin = _ValueStub(2)
        harness.pending_jobs = deque(jobs)
        harness.active_contexts = {}
        harness._update_job_card = lambda _job: None
        harness._launch_context = lambda context: MainWindow._launch_context(
            harness, context
        )
        harness._read_stdout = lambda _job_id: None
        harness._read_stderr = lambda _job_id: None
        harness._process_started = lambda _job_id: None
        harness._process_error = lambda _job_id, _error: None
        harness._process_finished = lambda _job_id, _code, _status: None
        harness._refresh_pending_positions = lambda: None
        harness._update_active_summary = lambda: None
        harness._notify_job_result = lambda _job: None
        _ProcessStub.instances = []

        with (
            patch("toki_gui.create_background_process", _ProcessStub),
            patch("toki_gui.find_node", return_value="node"),
            patch("toki_gui.build_downloader_args", return_value=["down.js"]),
            patch("toki_gui.load_run", return_value=None),
        ):
            MainWindow._start_next_job(harness)

        self.assertEqual(set(harness.active_contexts), {"job-0", "job-1"})
        self.assertEqual([job.job_id for job in harness.pending_jobs], ["job-2"])
        self.assertEqual(len(_ProcessStub.instances), 2)
        self.assertTrue(all(process.started_called for process in _ProcessStub.instances))
        self.assertIsNot(
            harness.active_contexts["job-0"].process,
            harness.active_contexts["job-1"].process,
        )

    def test_failed_process_enters_retry_wait_without_leaving_active_context(self) -> None:
        job = DownloadJob(
            job_id="retry-job",
            url="https://newtoki1.org/manhwa/9001",
            output_dir=r"C:\Manga",
            state="실행 중",
            retry_limit=2,
            retry_backoff_seconds=1,
        )
        process = _ProcessStub()
        context = ProcessContext(
            job=job,
            run=DownloadRun.from_job(job),
            process=process,
            attempt_count=1,
        )
        harness = type("RetryHarness", (), {})()
        harness.active_contexts = {job.job_id: context}
        harness.pending_job_ui_updates = {job.job_id}
        harness.active_detail_dialog = None
        harness._handle_process_line = lambda *_args: None
        harness._update_job_card = lambda _job: None
        harness._update_active_summary = lambda: None
        harness._start_next_job = lambda: None
        harness.log = lambda *_args, **_kwargs: None
        restarted = []
        harness._restart_context = lambda job_id, generation: restarted.append(
            (job_id, generation)
        )
        timers = []

        with (
            patch("toki_gui.save_runs"),
            patch(
                "toki_gui.QTimer.singleShot",
                side_effect=lambda delay, callback: timers.append((delay, callback)),
            ),
        ):
            MainWindow._process_finished(
                harness,
                job.job_id,
                1,
                None,
            )

        self.assertEqual(job.state, "재시도 대기")
        self.assertIn(job.job_id, harness.active_contexts)
        self.assertIsNone(context.process)
        self.assertTrue(process.deleted)
        self.assertEqual(timers[0][0], 1000)
        timers[0][1]()
        self.assertEqual(restarted, [(job.job_id, 1)])

    def test_authentication_failure_is_terminal_without_automatic_retry(self) -> None:
        job = DownloadJob(
            job_id="auth-job",
            url="https://newtoki1.org/manhwa/9002",
            output_dir=r"C:\Manga",
            state="실행 중",
            retry_limit=5,
            error="Cloudflare 인증 확인 시간 초과",
            error_category="authentication_required",
            retryable_error=False,
        )
        context = ProcessContext(
            job=job,
            run=DownloadRun.from_job(job),
            process=_ProcessStub(),
            attempt_count=1,
        )
        harness = type("AuthenticationHarness", (), {})()
        harness.active_contexts = {job.job_id: context}
        harness.pending_job_ui_updates = {job.job_id}
        harness.active_detail_dialog = None
        harness._handle_process_line = lambda *_args: None
        harness._update_job_card = lambda _job: None
        harness._update_active_summary = lambda: None
        harness._notify_job_result = lambda _job: None
        harness._start_next_job = lambda: None
        harness.log = lambda *_args, **_kwargs: None
        timers = []

        with (
            patch("toki_gui.save_runs"),
            patch(
                "toki_gui.QTimer.singleShot",
                side_effect=lambda delay, callback: timers.append((delay, callback)),
            ),
        ):
            MainWindow._process_finished(harness, job.job_id, 1, None)

        self.assertEqual(job.state, "인증 필요")
        self.assertNotIn(job.job_id, harness.active_contexts)
        self.assertEqual(context.run.state, "인증 필요")
        self.assertTrue(context.run.finished_at)
        self.assertEqual([delay for delay, _callback in timers], [250])


if __name__ == "__main__":
    unittest.main()
