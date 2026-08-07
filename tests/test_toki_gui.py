from __future__ import annotations

import os
import subprocess
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

import toki_gui
from toki_core import (
    DownloadJob,
    DownloadRun,
    SleepPreventionController,
    default_config,
)
from toki_gui import (
    ImageConversionProcessContext,
    JobListModel,
    MainWindow,
    PdfGenerationProcessContext,
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


class _TimerStub:
    def __init__(self) -> None:
        self.interval = 0
        self.started = 0
        self.stopped = 0
        self.active = False

    def setInterval(self, interval: int) -> None:
        self.interval = interval

    def start(self) -> None:
        self.started += 1
        self.active = True

    def stop(self) -> None:
        self.stopped += 1
        self.active = False

    def isActive(self) -> bool:
        return self.active


class _ProgressStub:
    def __init__(self) -> None:
        self.value = 0
        self.format = ""
        self.tooltip = ""
        self.visible = True

    def setValue(self, value: int) -> None:
        self.value = value

    def setFormat(self, value: str) -> None:
        self.format = value

    def setToolTip(self, value: str) -> None:
        self.tooltip = value

    def setVisible(self, value: bool) -> None:
        self.visible = value


class _LocalApiServerStub:
    def __init__(self) -> None:
        self.running = False
        self.selected_port = 0
        self.secret = ""
        self.last_error = ""
        self.request_count = 0
        self.last_request = {}
        self.start_calls: list[int] = []
        self.stop_calls = 0

    def start(self, port: int) -> bool:
        self.start_calls.append(port)
        self.running = True
        self.selected_port = port
        self.secret = "temporary-secret"
        return True

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False
        self.selected_port = 0
        self.secret = ""
        self.last_error = ""

    def is_running(self) -> bool:
        return self.running

    def port(self) -> int:
        return self.selected_port

    def token(self) -> str:
        return self.secret

    def error(self) -> str:
        return self.last_error

    def rotate_token(self) -> str:
        self.secret = "rotated-secret"
        return self.secret


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
    def test_local_api_runtime_is_loopback_temporary_and_ipc_controlled(self) -> None:
        harness = type("LocalApiHarness", (), {})()
        harness.config = {"localApiEnabled": True, "localApiPort": 9123}
        harness.local_api_server = _LocalApiServerStub()
        harness.active_settings_dialog = None
        harness.logs = []
        harness.log = lambda *args, **kwargs: harness.logs.append((args, kwargs))
        harness.local_api_status_snapshot = lambda: MainWindow.local_api_status_snapshot(
            harness
        )

        MainWindow._configure_local_api(harness)
        status = MainWindow.local_api_status_snapshot(harness)
        self.assertEqual(harness.local_api_server.start_calls, [9123])
        self.assertTrue(status["running"])
        self.assertEqual(status["host"], "127.0.0.1")
        self.assertFalse(status["publicBindingAllowed"])
        self.assertNotIn("temporary-secret", str(status))

        token_harness = type("LocalApiTokenHarness", (), {})()
        token_harness.local_api_status_snapshot = lambda: status
        token_harness.local_api_token_snapshot = lambda reveal=False: {
            **status,
            **({"token": "temporary-secret"} if reveal else {}),
        }
        token_harness.copy_local_api_token = lambda: True
        token_harness.rotate_local_api_token = lambda: {**status, "tokenHint": "…rotated"}
        revealed = MainWindow._handle_control_action(
            token_harness,
            {
                "action": "local_api_token",
                "reveal": True,
                "confirmed": True,
            },
        )
        self.assertEqual(revealed["token"], "temporary-secret")
        with self.assertRaises(ValueError):
            MainWindow._handle_control_action(
                token_harness,
                {"action": "local_api_token", "reveal": True},
            )

        harness.config["localApiEnabled"] = False
        MainWindow._configure_local_api(harness)
        self.assertFalse(harness.local_api_server.running)
        self.assertEqual(harness.local_api_server.stop_calls, 1)

    def test_memory_display_uses_shared_snapshot_timer_and_ipc(self) -> None:
        harness = type("MemoryHarness", (), {})()
        harness.config = {"memoryDisplayEnabled": True}
        harness.memory_progress = _ProgressStub()
        harness.memory_timer = _TimerStub()
        harness.active_contexts = {}
        harness.image_conversion_processes = {}
        harness.pdf_generation_processes = {}
        harness.last_memory_usage = {}
        harness._memory_mib = MainWindow._memory_mib
        snapshot = {
            "ok": True,
            "displayEnabled": True,
            "application": {
                "ownRssBytes": 100 * 1024**2,
                "childRssBytes": 50 * 1024**2,
                "combinedRssBytes": 150 * 1024**2,
                "childProcessCount": 2,
                "children": [],
            },
            "system": {
                "usedBytes": 8 * 1024**3,
                "totalBytes": 16 * 1024**3,
                "percent": 50.0,
            },
            "display": {"percent": 50, "severity": "normal"},
        }
        harness.memory_status_snapshot = lambda child_limit=200: snapshot
        harness._update_memory_usage = lambda: MainWindow._update_memory_usage(harness)

        MainWindow._configure_memory_display(harness)

        self.assertTrue(harness.memory_timer.active)
        self.assertTrue(harness.memory_progress.visible)
        self.assertEqual(harness.memory_progress.value, 50)
        self.assertIn("RAM 50%", harness.memory_progress.format)
        self.assertIn("150 MiB", harness.memory_progress.format)
        self.assertIn("자식 작업 50 MiB", harness.memory_progress.tooltip)

        harness.config["memoryDisplayEnabled"] = False
        MainWindow._configure_memory_display(harness)
        self.assertFalse(harness.memory_timer.active)
        self.assertFalse(harness.memory_progress.visible)

        ipc_harness = type("MemoryIpcHarness", (), {})()
        ipc_harness.memory_status_snapshot = lambda limit=200: {
            "ok": True,
            "childLimit": limit,
        }
        ipc = MainWindow._handle_control_action(
            ipc_harness,
            {"action": "memory_status", "childLimit": 25},
        )
        self.assertEqual(ipc, {"ok": True, "childLimit": 25})

        process = type("TrackedProcess", (), {"processId": lambda self: 300})()
        context = type("TrackedContext", (), {"process": process})()
        tree_harness = type("MemoryTreeHarness", (), {})()
        tree_harness.config = {"memoryDisplayEnabled": True}
        tree_harness.active_contexts = {"job-1": context}
        tree_harness.image_conversion_processes = {}
        tree_harness.pdf_generation_processes = {}
        tree_harness.last_memory_usage = {}
        process_tree = {
            **snapshot,
            "application": {
                **snapshot["application"],
                "children": [
                    {"pid": 300, "parentPid": 10, "rssBytes": 40},
                    {"pid": 301, "parentPid": 300, "rssBytes": 60},
                ],
            },
        }
        with patch("toki_gui.memory_usage_snapshot", return_value=process_tree):
            tracked = MainWindow.memory_status_snapshot(tree_harness, 25)
        self.assertEqual(
            tracked["trackedJobProcesses"],
            [
                {
                    "kind": "download",
                    "jobId": "job-1",
                    "pid": 300,
                    "rssBytes": 100,
                }
            ],
        )

    def test_clipboard_inspection_ipc_never_prompts_without_explicit_request(self) -> None:
        calls = []
        harness = type("ClipboardHarness", (), {})()
        harness.inspect_clipboard_text = (
            lambda text, prompt=False: calls.append((text, prompt))
            or {"candidate": True, "duplicate": False}
        )

        result = MainWindow._handle_control_action(
            harness,
            {
                "action": "inspect_clipboard",
                "text": "https://newtoki1.org/manhwa/34360",
                "prompt": False,
            },
        )

        self.assertTrue(result["candidate"])
        self.assertEqual(calls, [("https://newtoki1.org/manhwa/34360", False)])

    def test_completion_action_ipc_only_previews_or_cancels(self) -> None:
        calls = []
        harness = type("CompletionHarness", (), {})()
        harness.preview_completion_action = (
            lambda action, countdown: calls.append(("preview", action, countdown))
            or {"shown": True, "executed": False}
        )
        harness.cancel_completion_action = lambda: calls.append(("cancel",)) or True

        previewed = MainWindow._handle_control_action(
            harness,
            {
                "action": "preview_completion_action",
                "completionAction": "shutdown",
                "countdownSeconds": 20,
            },
        )
        cancelled = MainWindow._handle_control_action(
            harness, {"action": "cancel_completion_action"}
        )

        self.assertFalse(previewed["executed"])
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(calls, [("preview", "shutdown", 20), ("cancel",)])

    def test_work_copy_ipc_routes_id_source_path_and_title(self) -> None:
        calls = []
        harness = type("WorkCopyHarness", (), {})()
        harness.copy_job_id = lambda job_id: calls.append(("id", job_id)) or "j1"
        harness.copy_job_link = lambda job_id: calls.append(("link", job_id)) or "url"
        harness.copy_job_path = lambda job_id: calls.append(("path", job_id)) or "folder"
        harness.copy_job_title = lambda job_id: calls.append(("title", job_id)) or "title"

        results = [
            MainWindow._handle_control_action(
                harness, {"action": action, "jobId": "j1"}
            )["copied"]
            for action in ("copy_id", "copy_link", "copy_path", "copy_title")
        ]

        self.assertEqual(results, ["j1", "url", "folder", "title"])
        self.assertEqual(
            calls,
            [("id", "j1"), ("link", "j1"), ("path", "j1"), ("title", "j1")],
        )

    def test_duplicate_images_ipc_starts_algorithm_and_closes_report(self) -> None:
        calls = []
        harness = type("DuplicateImagesHarness", (), {})()
        harness.start_duplicate_images = (
            lambda job_id, algorithm: calls.append(("start", job_id, algorithm))
            or {"started": True}
        )
        harness.close_duplicate_images = lambda: calls.append(("close",)) or True

        started = MainWindow._handle_control_action(
            harness,
            {
                "action": "show_duplicate_images",
                "jobId": "j1",
                "algorithm": "phash",
            },
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_duplicate_images"}
        )

        self.assertTrue(started["started"])
        self.assertTrue(closed["closed"])
        self.assertEqual(calls, [("start", "j1", "phash"), ("close",)])

    def test_duplicate_works_ipc_can_show_and_close_report(self) -> None:
        calls = []
        harness = type("DuplicateWorksHarness", (), {})()
        harness.show_duplicate_works = lambda: calls.append(("show",)) or True
        harness.close_duplicate_works = lambda: calls.append(("close",)) or True

        shown = MainWindow._handle_control_action(
            harness, {"action": "show_duplicate_works"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_duplicate_works"}
        )

        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(calls, [("show",), ("close",)])

    def test_archive_inspection_ipc_can_show_and_close_result_window(self) -> None:
        calls = []
        harness = type("ArchiveInspectionHarness", (), {})()
        harness.show_archive_inspection = (
            lambda path: calls.append(("show", path)) or True
        )
        harness.close_archive_inspection = lambda: calls.append(("close",)) or True
        harness.config = default_config()

        shown = MainWindow._handle_control_action(
            harness, {"action": "show_archive_inspection", "path": "work.cbz"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_archive_inspection"}
        )
        with patch(
            "toki_gui.archive_viewer_policy_snapshot",
            return_value={"mode": "system", "available": True},
        ) as policy:
            viewer = MainWindow._handle_control_action(
                harness, {"action": "archive_viewer_policy"}
            )

        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(viewer["mode"], "system")
        policy.assert_called_once_with(harness.config)
        self.assertEqual(calls, [("show", "work.cbz"), ("close",)])

    def test_archive_viewer_gui_requires_confirmation_and_uses_shared_service(self) -> None:
        harness = type("ArchiveViewerHarness", (), {})()
        harness.config = default_config()
        logs = []
        messages = []
        harness.log = lambda message, *_args, **_kwargs: logs.append(message)
        harness.statusBar = lambda: type(
            "StatusBarHarness",
            (),
            {"showMessage": lambda _self, message, _timeout: messages.append(message)},
        )()
        plan = {
            "ok": True,
            "executed": False,
            "path": str(Path("work.cbz").resolve()),
            "viewerLabel": "Windows 기본 연결 프로그램",
            "error": "",
        }
        executed = {**plan, "executed": True}
        with (
            patch("toki_gui.plan_archive_viewer_open", return_value=plan) as planner,
            patch(
                "toki_gui.QMessageBox.question",
                return_value=toki_gui.QMessageBox.StandardButton.Yes,
            ),
            patch(
                "toki_gui.open_archive_with_viewer", return_value=executed
            ) as opener,
        ):
            result = MainWindow.confirm_open_archive_viewer(harness, "work.cbz")

        planner.assert_called_once_with(Path("work.cbz"), config=harness.config)
        opener.assert_called_once_with(
            Path("work.cbz"), config=harness.config, execute=True
        )
        self.assertTrue(result["executed"])
        self.assertEqual(len(logs), 1)
        self.assertEqual(len(messages), 1)

    def test_persistence_ipc_and_manual_recovery_block_current_work(self) -> None:
        calls = []
        harness = type("PersistenceHarness", (), {})()
        harness.persistence_status_snapshot = lambda: {"ok": True, "dirtyJobCount": 0}
        harness.recover_interrupted_records = (
            lambda execute=False: calls.append(("recover", execute))
            or {"ok": True, "executed": execute}
        )
        harness.show_recovery_dialog = lambda: calls.append(("show",)) or True
        harness.close_recovery_dialog = lambda: calls.append(("close",)) or True

        status = MainWindow._handle_control_action(
            harness, {"action": "persistence_status"}
        )
        preview = MainWindow._handle_control_action(
            harness, {"action": "recover_interrupted", "execute": False}
        )
        executed = MainWindow._handle_control_action(
            harness, {"action": "recover_interrupted", "execute": True}
        )
        shown = MainWindow._handle_control_action(
            harness, {"action": "show_recovery_dialog"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_recovery_dialog"}
        )

        self.assertTrue(status["ok"])
        self.assertFalse(preview["executed"])
        self.assertTrue(executed["executed"])
        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(
            calls, [("recover", False), ("recover", True), ("show",), ("close",)]
        )

        blocked_harness = type("BlockedRecoveryHarness", (), {})()
        blocked_harness.active_contexts = {"active": object()}
        blocked_harness.pending_jobs = deque()
        blocked = MainWindow.recover_interrupted_records(
            blocked_harness, execute=True
        )
        self.assertFalse(blocked["ok"])
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["activeJobIds"], ["active"])

    def test_autosave_failure_keeps_dirty_jobs_and_schedules_retry(self) -> None:
        job = DownloadJob(
            job_id="dirty",
            url="https://newtoki1.org/manhwa/7000",
            output_dir=r"C:\Manga",
        )
        harness = type("AutosaveHarness", (), {})()
        harness.dirty_job_ids = {job.job_id}
        harness.jobs = {job.job_id: job}
        harness.persist_timer = _TimerStub()
        harness.last_autosave = {}
        logs = []
        harness.log = lambda *args: logs.append(args)

        with patch("toki_gui.save_jobs", side_effect=OSError("disk busy")):
            MainWindow._flush_job_history(harness)

        self.assertEqual(harness.dirty_job_ids, {job.job_id})
        self.assertTrue(harness.persist_timer.active)
        self.assertFalse(harness.last_autosave["ok"])
        self.assertIn("disk busy", harness.last_autosave["error"])
        self.assertEqual(len(logs), 1)

    def test_list_performance_ipc_and_lazy_load_policy_are_cli_visible(self) -> None:
        harness = type("ListPerformanceHarness", (), {})()
        harness.list_performance_status_snapshot = lambda: {
            "ok": True,
            "effective": {"pageSize": 100, "loadedLimit": 500},
        }
        result = MainWindow._handle_control_action(
            harness, {"action": "list_performance_status"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["effective"]["loadedLimit"], 500)

        policy_harness = type("ListPolicyHarness", (), {})()
        policy_harness.list_performance_policy = {
            "effective": {
                "pageSize": 80,
                "loadedLimit": 400,
                "lazyLoading": True,
            }
        }
        self.assertEqual(MainWindow._initial_history_load_limit(policy_harness), 80)
        policy_harness.list_performance_policy["effective"]["lazyLoading"] = False
        self.assertEqual(MainWindow._initial_history_load_limit(policy_harness), 400)
        MainWindow._maybe_load_more_history(policy_harness, 999)

    def test_sleep_prevention_follows_running_not_paused_downloads_and_ipc(self) -> None:
        calls: list[int] = []
        job = DownloadJob(
            job_id="power",
            url="https://newtoki1.org/manhwa/8000",
            output_dir=r"C:\Manga",
        )
        job.state = "실행 중"
        context = type("PowerContext", (), {"job": job, "paused": False})()
        harness = type("PowerHarness", (), {})()
        harness.config = default_config()
        harness.config["preventSleepDuringDownloads"] = True
        harness.active_contexts = {job.job_id: context}
        harness._running_download_count = lambda: MainWindow._running_download_count(
            harness
        )
        harness.sleep_prevention_controller = SleepPreventionController(
            platform_name="nt",
            execution_state_setter=lambda flags: calls.append(flags) or 1,
        )
        harness.last_sleep_prevention = {}
        harness.log = lambda *_args, **_kwargs: None

        active = MainWindow._sync_sleep_prevention(harness)
        self.assertTrue(active["active"])
        self.assertEqual(active["activeDownloads"], 1)
        harness.sleep_prevention_status_snapshot = lambda: active
        self.assertEqual(
            MainWindow._handle_control_action(
                harness, {"action": "sleep_prevention_status"}
            ),
            active,
        )

        context.paused = True
        job.state = "일시정지"
        released = MainWindow._sync_sleep_prevention(harness)
        self.assertFalse(released["active"])
        self.assertEqual(released["activeDownloads"], 0)
        self.assertEqual(calls[-1], SleepPreventionController.ES_CONTINUOUS)

    def test_group_ipc_routes_all_manager_and_assignment_actions(self) -> None:
        calls = []
        harness = type("GroupHarness", (), {})()
        harness.list_groups_snapshot = lambda: {"ok": True, "groups": []}
        harness.create_work_group = (
            lambda name: calls.append(("create", name)) or {"groupId": "g1", "name": name}
        )
        harness.rename_work_group = (
            lambda group_id, name: calls.append(("rename", group_id, name))
            or {"groupId": group_id, "name": name}
        )
        harness.assign_work_group = (
            lambda job_id, group_id: calls.append(("assign", job_id, group_id))
            or {"ok": True}
        )
        harness.show_group_manager = lambda: calls.append(("show",)) or True
        harness.close_group_manager = lambda: calls.append(("close",)) or True

        self.assertEqual(
            MainWindow._handle_control_action(harness, {"action": "groups"})["groups"],
            [],
        )
        MainWindow._handle_control_action(
            harness, {"action": "create_group", "name": "읽을 것"}
        )
        MainWindow._handle_control_action(
            harness, {"action": "rename_group", "groupId": "g1", "name": "완독"}
        )
        MainWindow._handle_control_action(
            harness, {"action": "assign_group", "jobId": "j1", "groupId": "g1"}
        )
        shown = MainWindow._handle_control_action(harness, {"action": "show_group_manager"})
        closed = MainWindow._handle_control_action(harness, {"action": "close_group_manager"})

        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(
            calls,
            [
                ("create", "읽을 것"),
                ("rename", "g1", "완독"),
                ("assign", "j1", "g1"),
                ("show",),
                ("close",),
            ],
        )

    def test_jobs_snapshot_ipc_routes_export_preview_execute_show_and_close(self) -> None:
        calls = []
        harness = type("JobsSnapshotHarness", (), {})()
        harness.export_jobs_snapshot_now = (
            lambda output: calls.append(("export", output)) or {"ok": True}
        )
        harness.execute_jobs_snapshot_import = (
            lambda input_path: calls.append(("execute", input_path)) or {"ok": True}
        )
        harness.show_jobs_snapshot_import = (
            lambda input_path: calls.append(("show", input_path)) or True
        )
        harness.close_jobs_snapshot_dialog = lambda: calls.append(("close",)) or True

        with patch(
            "toki_gui.import_jobs_snapshot", return_value={"ok": True, "executed": False}
        ) as preview:
            exported = MainWindow._handle_control_action(
                harness, {"action": "export_jobs_snapshot", "output": "jobs.json"}
            )
            previewed = MainWindow._handle_control_action(
                harness,
                {"action": "import_jobs_snapshot", "input": "jobs.json", "execute": False},
            )
            executed = MainWindow._handle_control_action(
                harness,
                {"action": "import_jobs_snapshot", "input": "jobs.json", "execute": True},
            )
            shown = MainWindow._handle_control_action(
                harness, {"action": "show_jobs_snapshot_import", "input": "jobs.json"}
            )
            closed = MainWindow._handle_control_action(
                harness, {"action": "close_jobs_snapshot_import"}
            )

        preview.assert_called_once_with(Path("jobs.json"), execute=False)
        self.assertTrue(exported["ok"])
        self.assertFalse(previewed["executed"])
        self.assertTrue(executed["ok"])
        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(
            calls,
            [
                ("export", "jobs.json"),
                ("execute", "jobs.json"),
                ("show", "jobs.json"),
                ("close",),
            ],
        )

    def test_settings_search_catalog_matches_pages_without_opening_gui(self) -> None:
        self.assertEqual(SettingsDialog.matching_tab_indexes("테마"), [2])
        self.assertEqual(SettingsDialog.matching_tab_indexes("폴더명 템플릿"), [0])
        self.assertEqual(SettingsDialog.matching_tab_indexes("언어 한국어"), [0])
        self.assertEqual(SettingsDialog.matching_tab_indexes("배율 배경 글꼴"), [2])
        self.assertEqual(SettingsDialog.matching_tab_indexes("프록시 속도 공급자"), [1])
        self.assertEqual(SettingsDialog.matching_tab_indexes("yt-dlp"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("압축 연결 프로그램"), [3])
        self.assertEqual(SettingsDialog.matching_tab_indexes("자동 저장 복구"), [3])
        self.assertEqual(
            SettingsDialog.matching_tab_indexes("페이지 스크롤 지연 저사양"), [3]
        )
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

    def test_cookie_manager_ipc_shows_provider_without_reading_secrets(self) -> None:
        calls = []
        harness = type("CookieIpcHarness", (), {})()
        harness.show_cookie_manager = (
            lambda provider: calls.append(("show", provider)) or True
        )
        harness.close_cookie_manager = lambda: calls.append(("close",)) or True
        shown = MainWindow._handle_control_action(
            harness, {"action": "show_cookie_manager", "provider": "manatoki"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_cookie_manager"}
        )
        self.assertEqual(shown, {"shown": True})
        self.assertEqual(closed, {"closed": True})
        self.assertEqual(calls, [("show", "manatoki"), ("close",)])

    def test_hitomi_inspector_ipc_uses_offline_service_and_gui_contract(self) -> None:
        calls = []
        harness = type("HitomiIpcHarness", (), {})()
        harness.show_hitomi_inspector = (
            lambda reference, provider: calls.append(
                ("show", reference, provider)
            )
            or {"shown": True, "networkRequested": False}
        )
        harness.close_hitomi_inspector = (
            lambda: calls.append(("close",)) or True
        )

        inspected = MainWindow._handle_control_action(
            harness,
            {
                "action": "hitomi_inspect",
                "reference": "https://hitomi.la/manga/sample-1234567.html",
                "provider": "auto",
            },
        )
        shown = MainWindow._handle_control_action(
            harness,
            {
                "action": "show_hitomi_inspector",
                "reference": "1234567",
                "provider": "hitomi",
            },
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_hitomi_inspector"}
        )
        invalid = MainWindow._handle_control_action(
            harness,
            {
                "action": "hitomi_inspect",
                "reference": "https://example.com/g/1",
                "provider": "auto",
            },
        )

        self.assertEqual(inspected["workKey"], "hitomi:1234567")
        self.assertFalse(inspected["networkRequested"])
        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(invalid["errorCode"], "hitomi.unsupported_host")
        self.assertEqual(
            calls,
            [("show", "1234567", "hitomi"), ("close",)],
        )

    def test_proxy_credential_manager_ipc_opens_without_reading_secrets(self) -> None:
        calls = []
        harness = type("ProxyCredentialIpcHarness", (), {})()
        harness.show_proxy_credential_manager = (
            lambda: calls.append(("show",)) or True
        )
        harness.close_proxy_credential_manager = (
            lambda: calls.append(("close",)) or True
        )
        shown = MainWindow._handle_control_action(
            harness, {"action": "show_proxy_credential_manager"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_proxy_credential_manager"}
        )
        self.assertEqual(shown, {"shown": True})
        self.assertEqual(closed, {"closed": True})
        self.assertEqual(calls, [("show",), ("close",)])

    def test_embedded_browser_ipc_preserves_offline_navigation_contract(self) -> None:
        calls = []
        harness = type("EmbeddedBrowserIpcHarness", (), {})()
        harness.show_embedded_browser = (
            lambda url, navigate, confirmed: calls.append(
                ("show", url, navigate, confirmed)
            )
            or True
        )
        harness.close_embedded_browser = lambda: calls.append(("close",)) or True
        shown = MainWindow._handle_control_action(
            harness,
            {
                "action": "show_embedded_browser",
                "url": "https://newtoki1.org/manhwa/34360",
                "navigate": False,
                "confirmed": False,
            },
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_embedded_browser"}
        )
        self.assertEqual(shown, {"shown": True})
        self.assertEqual(closed, {"closed": True})
        self.assertEqual(
            calls,
            [
                (
                    "show",
                    "https://newtoki1.org/manhwa/34360",
                    False,
                    False,
                ),
                ("close",),
            ],
        )

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
        in_app_messages = []
        tray_messages = []
        message_boxes = []
        sounds = []
        harness = type("NotificationHarness", (), {})()
        harness.config = {
            "notifyOnComplete": True,
            "notifyOnError": True,
            "notificationSound": "none",
            "notificationMessageBox": False,
        }
        harness.show_in_app_notification_message = (
            lambda message: in_app_messages.append(message) or True
        )
        harness.show_tray_notification = (
            lambda message: tray_messages.append(message) or True
        )
        harness.show_notification_message_box = (
            lambda plan: message_boxes.append(plan["message"]) or True
        )
        harness.play_notification_sound = lambda: sounds.append(True) or True
        harness.deliver_notification = lambda plan: MainWindow.deliver_notification(
            harness, plan
        )
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
            in_app_messages,
            ["다운로드 완료: 완료 작품", "실패 작품: 네트워크 오류"],
        )
        self.assertEqual(tray_messages, in_app_messages)
        self.assertEqual(message_boxes, [])
        self.assertEqual(sounds, [])
        harness.config["notifyOnError"] = False
        MainWindow._notify_job_result(harness, failed)
        self.assertEqual(len(in_app_messages), 2)

        harness.config["notificationSound"] = "system"
        harness.config["notificationMessageBox"] = True
        preview = MainWindow.preview_notification(
            harness, "error", "미리보기 작품", "테스트 오류"
        )
        self.assertTrue(preview["messageBoxShown"])
        self.assertTrue(preview["soundPlayed"])
        self.assertEqual(message_boxes, ["미리보기 작품: 테스트 오류"])
        self.assertEqual(sounds, [True])

    def test_notification_ipc_status_and_preview_use_shared_runtime(self) -> None:
        calls = []
        harness = type("NotificationIpcHarness", (), {})()
        harness.notification_status_snapshot = lambda: {"sound": "none"}
        harness.preview_notification = (
            lambda kind, title, detail: calls.append((kind, title, detail))
            or {"executed": True}
        )
        harness.close_notification_messages = lambda: 2
        status = MainWindow._handle_control_action(
            harness, {"action": "notification_status"}
        )
        preview = MainWindow._handle_control_action(
            harness,
            {
                "action": "preview_notification",
                "kind": "complete",
                "title": "완료 작품",
                "detail": "",
            },
        )
        self.assertEqual(status["sound"], "none")
        self.assertTrue(preview["executed"])
        self.assertEqual(calls, [("complete", "완료 작품", "")])
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_notifications"}
        )
        self.assertEqual(closed["closed"], 2)

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
            "listViewMode": "icon",
            "thumbnailsVisible": False,
            "thumbnailSize": "large",
            "alwaysOnTop": True,
            "windowOpacity": 85,
            "autosaveIntervalSeconds": 7,
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
        display_updates = []
        harness._apply_display_preferences = lambda values: display_updates.append(values)
        harness._apply_keyboard_shortcuts = lambda: None
        harness._configure_tray = lambda: None
        harness.resolved_theme = "light"
        harness.theme_mode = "system"
        harness.active_settings_dialog = None
        harness.persist_timer = _TimerStub()
        harness.dirty_job_ids = {"dirty"}

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
        self.assertEqual(display_updates, [result])
        self.assertEqual(harness.persist_timer.interval, 7000)
        self.assertEqual(harness.persist_timer.started, 1)
        self.assertEqual(harness.persist_timer.stopped, 1)
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

    def test_shortcut_override_ipc_applies_validated_live_settings(self) -> None:
        calls = []
        harness = type("ShortcutOverrideHarness", (), {})()
        harness.apply_shortcut_overrides = (
            lambda overrides: calls.append(overrides)
            or {"overrideCount": len(overrides), "disabledCount": 0}
        )
        result = MainWindow._handle_control_action(
            harness,
            {
                "action": "apply_shortcut_overrides",
                "shortcutOverrides": {"focus.search": ["Ctrl+Alt+F"]},
            },
        )
        self.assertEqual(result["overrideCount"], 1)
        self.assertEqual(calls, [{"focus.search": ["Ctrl+Alt+F"]}])

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
        harness.pdf_generation_processes = {}
        harness.config = default_config()
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
                max_width=1600,
                max_height=2400,
                excluded_extensions=["gif"],
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
        self.assertEqual(
            process.arguments[process.arguments.index("--max-width") + 1], "1600"
        )
        self.assertEqual(
            process.arguments[process.arguments.index("--max-height") + 1], "2400"
        )
        self.assertIn("--exclude-ext", process.arguments)
        self.assertIn(".gif", process.arguments)

        policy_harness = type("ImagePolicyHarness", (), {})()
        policy_harness.config = default_config()
        policy = MainWindow._handle_control_action(
            policy_harness, {"action": "image_processing_policy"}
        )
        self.assertEqual(policy["maxWidth"], 0)
        self.assertTrue(policy["preservesOriginals"])

        ipc_calls = []
        ipc_harness = type("ImageConversionIpcHarness", (), {})()
        ipc_harness.start_image_conversion = lambda *args, **kwargs: (
            ipc_calls.append((args, kwargs)) or {"started": True}
        )
        MainWindow._handle_control_action(
            ipc_harness,
            {
                "action": "convert_images",
                "jobId": "convert-job",
                "format": "webp",
                "quality": 82,
                "maxWidth": 1600,
                "maxHeight": 2400,
                "excludedExtensions": ["gif"],
            },
        )
        self.assertEqual(ipc_calls[0][0], ("convert-job", "webp", 82))
        self.assertEqual(
            ipc_calls[0][1],
            {
                "max_width": 1600,
                "max_height": 2400,
                "excluded_extensions": ["gif"],
                "execute": False,
            },
        )
        ipc_harness.close_image_conversion_dialog = lambda: True
        closed = MainWindow._handle_control_action(
            ipc_harness, {"action": "close_image_conversion"}
        )
        self.assertTrue(closed["closed"])

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

    def test_pdf_gui_uses_confirmed_child_cli_and_all_actions_are_ipc_callable(self) -> None:
        job = DownloadJob(
            job_id="pdf-job",
            url="https://newtoki1.org/manhwa/9200",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\작품",
            state="완료",
        )
        harness = type("PdfHarness", (), {})()
        harness.pdf_generation_processes = {}
        harness.image_conversion_processes = {}
        harness.resource_limits = {"cpuProcesses": 2}
        harness.active_pdf_generation_dialog = None
        harness.active_pdf_generation_progress_dialog = None
        harness.selected_job = lambda _job_id=None: job
        harness.log = lambda *_args, **_kwargs: None
        _ProcessStub.instances = []

        with (
            patch("toki_gui.create_background_process", _ProcessStub),
            patch("toki_gui.PdfGenerationProgressDialog", _DialogStub),
        ):
            result = MainWindow.start_pdf_generation(
                harness, job.job_id, execute=True, automatic=False
            )

        process = _ProcessStub.instances[0]
        self.assertTrue(result["started"])
        self.assertTrue(result["preservesOriginals"])
        self.assertIn("pdf", process.arguments)
        self.assertIn("generate", process.arguments)
        self.assertIn("--execute", process.arguments)
        self.assertIn("--yes", process.arguments)
        self.assertIn("--progress-json", process.arguments)

        ipc_calls = []
        ipc_harness = type("PdfIpcHarness", (), {})()
        ipc_harness.pdf_status_snapshot = lambda: {"ok": True, "automatic": False}
        ipc_harness.start_pdf_generation = lambda *args, **kwargs: (
            ipc_calls.append((args, kwargs)) or {"started": True}
        )
        ipc_harness.cancel_pdf_generation = lambda job_id: {
            "cancelled": True,
            "jobId": job_id,
        }
        ipc_harness.close_pdf_generation_dialogs = lambda: True
        self.assertFalse(
            MainWindow._handle_control_action(
                ipc_harness, {"action": "pdf_status"}
            )["automatic"]
        )
        MainWindow._handle_control_action(
            ipc_harness,
            {"action": "generate_pdf", "jobId": "pdf-job", "execute": False},
        )
        self.assertEqual(ipc_calls, [(('pdf-job',), {"execute": False, "automatic": False})])
        self.assertTrue(
            MainWindow._handle_control_action(
                ipc_harness,
                {"action": "cancel_pdf_generation", "jobId": "pdf-job"},
            )["cancelled"]
        )
        self.assertTrue(
            MainWindow._handle_control_action(
                ipc_harness, {"action": "close_pdf_generation"}
            )["closed"]
        )

        cancel_process = _ProcessStub()
        cancel_context = PdfGenerationProcessContext(
            process=cancel_process, execute=True
        )
        cancel_harness = type("PdfCancelHarness", (), {})()
        cancel_harness.pdf_generation_processes = {"pdf-job": cancel_context}
        cancel_harness.active_pdf_generation_progress_dialog = None
        cancel_harness.log = lambda *_args, **_kwargs: None
        first = MainWindow.cancel_pdf_generation(cancel_harness, "pdf-job")
        second = MainWindow.cancel_pdf_generation(cancel_harness, "pdf-job")
        self.assertTrue(first["cancelled"])
        self.assertTrue(second["cancelled"])
        self.assertTrue(cancel_process.killed)

    def test_automatic_pdf_waits_for_cpu_capacity_before_completion(self) -> None:
        harness = type("AutomaticPdfHarness", (), {})()
        harness.config = {"pdfGenerationEnabled": True}
        harness.pending_pdf_jobs = set()
        harness.pdf_generation_processes = {}
        harness.active_contexts = {}
        harness.pending_jobs = deque()
        harness.logs = []
        harness.log = lambda *args, **kwargs: harness.logs.append((args, kwargs))
        harness.completion_calls = 0
        harness._maybe_trigger_completion_action = lambda: setattr(
            harness, "completion_calls", harness.completion_calls + 1
        )
        outcomes = deque([{"started": False, "resourceLimit": True}])

        def start_pdf(job_id: str, **_kwargs: object) -> dict[str, object]:
            if outcomes:
                return outcomes.popleft()
            harness.pdf_generation_processes[job_id] = object()
            return {"started": True, "jobId": job_id}

        harness.start_pdf_generation = start_pdf
        harness._try_start_automatic_pdf_generation = lambda job_id: (
            MainWindow._try_start_automatic_pdf_generation(harness, job_id)
        )
        harness._schedule_completion_if_idle = lambda: (
            MainWindow._schedule_completion_if_idle(harness)
        )
        timers: list[tuple[int, object]] = []

        with patch(
            "toki_gui.QTimer.singleShot",
            side_effect=lambda delay, callback: timers.append((delay, callback)),
        ):
            MainWindow._queue_automatic_pdf_generation(harness, "pdf-job")
            self.assertEqual(harness.pending_pdf_jobs, {"pdf-job"})
            self.assertEqual([delay for delay, _callback in timers], [500])
            self.assertEqual(harness.completion_calls, 0)

            _delay, retry = timers.pop(0)
            retry()
            self.assertFalse(harness.pending_pdf_jobs)
            self.assertIn("pdf-job", harness.pdf_generation_processes)
            self.assertFalse(timers)

            harness.pdf_generation_processes.clear()
            MainWindow._schedule_completion_if_idle(harness)
            self.assertEqual([delay for delay, _callback in timers], [0])
            _delay, complete = timers.pop(0)
            complete()

        self.assertEqual(harness.completion_calls, 1)

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
