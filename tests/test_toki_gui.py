from __future__ import annotations

import json
import base64
import os
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMainWindow

import toki_gui
from toki_core import (
    DownloadJob,
    DownloadRun,
    SleepPreventionController,
    default_config,
)
from toki_gui import (
    HitomiMetadataDialog,
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


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[tuple] = []

    def showMessage(self, *values) -> None:
        self.messages.append(values)


class _ThreadPoolStub:
    def __init__(self) -> None:
        self.tasks = []

    def activeThreadCount(self) -> int:
        return 0

    def start(self, task) -> None:
        self.tasks.append(task)


class _ControlSocketStub:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.flushed = False
        self.disconnected = False

    def write(self, payload: bytes) -> None:
        self.writes.append(payload)

    def flush(self) -> None:
        self.flushed = True

    def disconnectFromServer(self) -> None:
        self.disconnected = True


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


class _JobContextMenuHarness(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.active_contexts = {}
        self.pending_jobs = deque()
        self.file_verify_processes = {}
        self.image_preview_processes = {}
        self.duplicate_image_tasks = {}
        self.episode_rename_tasks = {}
        self.image_conversion_processes = {}
        self.pdf_generation_processes = {}
        self.start_spin = _ValueStub(0)
        self.last_spin = _ValueStub(0)

    def show_group_manager(self) -> None:
        pass

    def show_recovery_dialog(self) -> None:
        pass


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
        self.program = _program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = arguments

    def setProcessEnvironment(self, environment) -> None:
        self.environment = environment

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
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.qt_app = QApplication.instance() or QApplication(["toki-gui-tests"])

    def test_image_preview_worker_decodes_valid_webp_when_qt_rejects_it(self) -> None:
        samples = json.loads((Path(__file__).parent / "fixtures/webp_validation_samples.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lossless.webp"
            payload = base64.b64decode(samples["lossless"])
            path.write_bytes(payload)
            failed_reader = Mock()
            failed_reader.read.return_value = toki_gui.QImage()
            failed_reader.errorString.return_value = "Qt decode failed"
            for data, expected_valid in ((payload, True), (payload[:20], False)):
                path.write_bytes(data)
                task = toki_gui.ImageLoadTask(str(path))
                received = []
                task.signals.loaded.connect(lambda *args: received.append(args))
                with patch.object(toki_gui, "QImageReader", return_value=failed_reader):
                    task.run()
                self.assertEqual(len(received), 1)
                self.assertEqual(not received[0][1].isNull(), expected_valid)
                self.assertEqual(not received[0][2], expected_valid)
                self.assertEqual(path.read_bytes(), data)

    def test_image_preview_combo_uses_folder_identity_for_same_ordinal(self) -> None:
        owner = QMainWindow()
        owner.start_image_preview = Mock(return_value={"started": True})
        result = {
            "jobId": "preview-work", "title": "작품", "episode": 1,
            "episodeFolder": "작품 140화", "availableEpisodes": [1],
            "episodeEntries": [
                {"number": 1, "sourceId": "source-a", "folderName": "작품 140화"},
                {"number": 1, "sourceId": "source-b", "folderName": "작품 140-2화"},
            ],
            "total": 0, "images": [],
        }
        dialog = toki_gui.ImagePreviewDialog(owner, result)
        try:
            self.assertEqual(dialog.episode_combo.count(), 2)
            self.assertEqual(dialog.episode_combo.itemText(1), "작품 140-2화")
            dialog.episode_combo.setCurrentIndex(1)
            owner.start_image_preview.assert_called_once_with(
                "preview-work", episode_folder="작품 140-2화"
            )
            self.assertEqual(dialog.episode_combo.currentData(), result["episodeFolder"])
            owner.start_image_preview.reset_mock()
            owner.start_image_preview.return_value = {"started": False, "alreadyRunning": True}
            dialog.episode_combo.setCurrentIndex(1)
            owner.start_image_preview.assert_called_once()
            self.assertEqual(dialog.episode_combo.currentData(), result["episodeFolder"])
        finally:
            dialog.close()
            owner.close()

    def test_image_preview_control_forwards_identity_selectors(self) -> None:
        harness = SimpleNamespace(start_image_preview=Mock(return_value={"started": True}))
        for field, keyword, value in (
            ("episodeId", "episode_id", "source-b"),
            ("episodeFolder", "episode_folder", "작품 140-2화"),
        ):
            harness.start_image_preview.reset_mock()
            MainWindow._handle_control_action(harness, {
                "action": "preview_images", "jobId": "preview-work", field: value,
            })
            harness.start_image_preview.assert_called_once_with("preview-work", None, **{keyword: value})

    def _job_context_menu_snapshot(
        self,
        job: DownloadJob,
        *,
        active_context=None,
        current_collection=None,
        groups=None,
    ) -> dict:
        harness = _JobContextMenuHarness()
        if active_context is not None:
            harness.active_contexts[job.job_id] = active_context
        with (
            patch(
                "toki_gui.work_collection_for_job",
                return_value=current_collection,
            ),
            patch("toki_gui.list_work_collections", return_value=list(groups or [])),
        ):
            menu = MainWindow._build_job_context_menu(harness, job)
            snapshot = MainWindow._menu_snapshot(menu)
        menu.deleteLater()
        harness.deleteLater()
        self.qt_app.processEvents()
        return snapshot

    def test_application_identity_ipc_reports_live_taskbar_configuration(self) -> None:
        expected = {
            "ok": True,
            "displayName": "tokiDownloader",
            "windowsAppUserModelId": "EtaSwCwj.tokiDownloader.GUI.1",
            "iconExists": True,
            "applied": True,
        }
        calls = []
        harness = type("ApplicationIdentityHarness", (), {})()
        harness.show_application_identity = (
            lambda: calls.append("show") or {"shown": True, **expected}
        )
        harness.close_application_identity = (
            lambda: calls.append("close") or True
        )
        with patch("toki_gui.application_identity_snapshot", return_value=expected):
            result = MainWindow._handle_control_action(
                harness, {"action": "application_identity"}
            )
        shown = MainWindow._handle_control_action(
            harness, {"action": "show_application_identity"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_application_identity"}
        )
        self.assertEqual(result, expected)
        self.assertTrue(shown["shown"])
        self.assertEqual(closed, {"closed": True})
        self.assertEqual(calls, ["show", "close"])

    def test_public_ip_button_requires_yes_before_starting_service(self) -> None:
        harness = type("PublicIpHarness", (), {})()
        starts = []
        harness.start_public_ip_check = lambda: starts.append(True)
        with patch(
            "toki_gui.QMessageBox.question",
            return_value=toki_gui.QMessageBox.StandardButton.No,
        ):
            self.assertFalse(MainWindow.confirm_public_ip_check(harness))
        self.assertEqual(starts, [])
        with patch(
            "toki_gui.QMessageBox.question",
            return_value=toki_gui.QMessageBox.StandardButton.Yes,
        ):
            self.assertTrue(MainWindow.confirm_public_ip_check(harness))
        self.assertEqual(starts, [True])

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

    def test_job_context_menu_ipc_routes_show_and_inspect_requests(self) -> None:
        calls = []
        harness = type("JobMenuHarness", (), {})()
        harness.show_job_context_menu_for_job = (
            lambda job_id: calls.append(("show", job_id)) or True
        )
        harness.job_context_menu_snapshot = (
            lambda job_id: calls.append(("inspect", job_id))
            or {
                "jobId": job_id,
                "rootItems": ["작품 정보 및 실행 이력", "작품 재검사", "복사"],
            }
        )

        shown = MainWindow._handle_control_action(
            harness, {"action": "show_job_menu", "jobId": "j1"}
        )
        inspected = MainWindow._handle_control_action(
            harness, {"action": "inspect_job_menu", "jobId": "j1"}
        )

        self.assertEqual(shown, {"shown": True})
        self.assertEqual(inspected["jobId"], "j1")
        self.assertEqual(inspected["rootItems"][1], "작품 재검사")
        self.assertEqual(calls, [("show", "j1"), ("inspect", "j1")])

    def test_episode_folder_rename_has_no_synchronous_control_branch(self) -> None:
        harness = type("EpisodeRenameHarness", (), {})()

        with self.assertRaisesRegex(ValueError, "지원하지 않는 CLI 동작"):
            MainWindow._handle_control_action(
                harness,
                {"action": "rename_episode_folders", "jobId": "j1"},
            )

    def test_episode_folder_rename_is_queued_and_duplicate_job_is_rejected(
        self,
    ) -> None:
        job = DownloadJob(
            job_id="rename-async",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\rename-async",
            title="작품",
            state="완료",
        )
        pool = _ThreadPoolStub()
        status = _StatusBarStub()
        service_calls = []
        flush_calls = []
        harness = type("EpisodeRenameAsyncHarness", (), {})()
        harness.selected_job = lambda _job_id: job
        harness.exit_requested = False
        harness.exit_after_episode_rename = False
        harness.episode_rename_tasks = {}
        harness.active_contexts = {}
        harness.pending_jobs = deque()
        harness.file_verify_processes = {}
        harness.image_preview_processes = {}
        harness.duplicate_image_tasks = {}
        harness.image_conversion_processes = {}
        harness.pdf_generation_processes = {}
        harness.io_thread_pool = pool
        harness.resource_limits = toki_gui.resource_budget()
        harness.rename_episode_folders = (
            lambda job_id, execute=False, job_snapshot=None: service_calls.append(
                (job_id, execute, job_snapshot)
            )
            or {"jobId": job_id, "executed": execute}
        )
        harness._flush_job_history = lambda: flush_calls.append("flush")
        harness._episode_folder_rename_finished = lambda *_args: None
        harness.log = lambda *_args, **_kwargs: None
        harness.statusBar = lambda: status

        first = MainWindow.start_episode_folder_rename(harness, job.job_id)
        second = MainWindow.start_episode_folder_rename(harness, job.job_id)

        self.assertTrue(first["started"])
        self.assertFalse(second["started"])
        self.assertTrue(second["alreadyRunning"])
        self.assertEqual(len(pool.tasks), 1)
        self.assertEqual(service_calls, [])
        self.assertEqual(
            pool.tasks[0].operation(),
            {"jobId": job.job_id, "executed": False},
        )
        self.assertEqual(len(service_calls), 1)
        self.assertEqual(service_calls[0][:2], (job.job_id, False))
        snapshot = service_calls[0][2]
        self.assertIsInstance(snapshot, toki_gui.EpisodeRenameJobSnapshot)
        with self.assertRaises(FrozenInstanceError):
            snapshot.title = "변경 금지"
        self.assertEqual(flush_calls, [])

        harness.episode_rename_tasks = {}
        executed = MainWindow.start_episode_folder_rename(
            harness, job.job_id, execute=True
        )
        self.assertTrue(executed["started"])
        self.assertEqual(flush_calls, ["flush"])
        execute_context = harness.episode_rename_tasks[job.job_id]
        self.assertEqual(execute_context.job_id, job.job_id)
        self.assertEqual(execute_context.work_key, job.work_key)
        self.assertEqual(execute_context.output_path, job.output_path)
        self.assertEqual(
            pool.tasks[1].operation(),
            {"jobId": job.job_id, "executed": True},
        )
        self.assertEqual(service_calls[1], (job.job_id, True, None))

    def test_episode_rename_execute_identity_matches_work_and_normalized_path(
        self,
    ) -> None:
        base_job = DownloadJob(
            job_id="rename-original",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\Same Work",
            state="완료",
        )
        context = toki_gui.EpisodeRenameTaskContext(
            task=SimpleNamespace(),
            execute=True,
            origin="cli",
            job_id=base_job.job_id,
            work_key=base_job.work_key,
            output_path=r"C:\Manga\Same Work\.",
        )
        harness = type("EpisodeRenameIdentityHarness", (), {})()
        harness.episode_rename_tasks = {base_job.job_id: context}

        work_alias = DownloadJob(
            job_id="rename-work-alias",
            url=base_job.url,
            output_dir=r"D:\Elsewhere",
            output_path=r"D:\Elsewhere\Different",
            state="완료",
        )
        work_conflict = MainWindow._episode_rename_execute_conflict(
            harness, work_alias
        )
        self.assertIsNotNone(work_conflict)
        self.assertIn("workKey", work_conflict["matchedBy"])

        path_alias = DownloadJob(
            job_id="rename-path-alias",
            url="https://newtoki1.org/manhwa/99999",
            output_dir=r"C:\Manga",
            output_path=r"c:\manga\same work",
            state="완료",
        )
        path_conflict = MainWindow._episode_rename_execute_conflict(
            harness, path_alias
        )
        self.assertIsNotNone(path_conflict)
        self.assertIn("outputPath", path_conflict["matchedBy"])

        context.execute = False
        self.assertIsNone(
            MainWindow._episode_rename_execute_conflict(harness, work_alias)
        )

    def test_episode_rename_execute_blocks_same_work_mutation_entry_points(
        self,
    ) -> None:
        locked_job = DownloadJob(
            job_id="rename-lock",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\Locked Work",
            state="완료",
        )
        alias_job = DownloadJob(
            job_id="alias-job",
            url=locked_job.url,
            output_dir=locked_job.output_dir,
            output_path=r"c:\manga\locked work\.",
            state="완료",
        )
        rename_context = toki_gui.EpisodeRenameTaskContext(
            task=SimpleNamespace(),
            execute=True,
            origin="cli",
            job_id=locked_job.job_id,
            work_key=locked_job.work_key,
            output_path=locked_job.output_path,
        )
        harness = type("EpisodeMutationGuardHarness", (), {})()
        harness.episode_rename_tasks = {locked_job.job_id: rename_context}
        harness.selected_job = lambda _job_id=None: alias_job
        harness.enqueue_download = lambda **_kwargs: self.fail(
            "blocked retry/rescan/refresh must not enqueue"
        )
        harness._flush_job_history = lambda: self.fail(
            "blocked move/rebuild must not flush"
        )

        for operation in (
            lambda: MainWindow.retry_job(harness, alias_job.job_id),
            lambda: MainWindow.rescan_job(harness, alias_job.job_id, "new"),
            lambda: MainWindow.refresh_job_metadata(harness, alias_job.job_id),
            lambda: MainWindow.move_job_folder(
                harness, alias_job.job_id, r"D:\Manga", execute=True
            ),
            lambda: MainWindow.rebuild_job_metadata(
                harness, alias_job.job_id, execute=True
            ),
        ):
            with self.assertRaisesRegex(ValueError, "episode_rename_in_progress"):
                operation()

        for operation_name, operation in (
            (
                "fileVerification",
                lambda: MainWindow.start_file_verification(
                    harness, alias_job.job_id
                ),
            ),
            (
                "imagePreview",
                lambda: MainWindow.start_image_preview(harness, alias_job.job_id),
            ),
            (
                "duplicateImages",
                lambda: MainWindow.start_duplicate_images(
                    harness, alias_job.job_id, "sha256"
                ),
            ),
            (
                "imageConversion",
                lambda: MainWindow.start_image_conversion(
                    harness, alias_job.job_id, execute=True
                ),
            ),
            (
                "pdfGeneration",
                lambda: MainWindow.start_pdf_generation(
                    harness, alias_job.job_id, execute=True
                ),
            ),
        ):
            result = operation()
            self.assertFalse(result["started"])
            self.assertTrue(result["mutationBlocked"])
            self.assertEqual(result["errorCode"], "episode_rename_in_progress")
            self.assertEqual(result["operation"], operation_name)

        with tempfile.TemporaryDirectory() as temporary:
            enqueue_harness = type("EpisodeEnqueueGuardHarness", (), {})()
            enqueue_harness.pending_jobs = deque()
            enqueue_harness.resource_limits = toki_gui.resource_budget()
            enqueue_harness.jobs_by_work = {}
            enqueue_harness.episode_rename_tasks = {
                locked_job.job_id: rename_context
            }
            with (
                patch("toki_gui.find_node", return_value="node"),
                patch("toki_gui.save_runs") as save_runs,
                self.assertRaisesRegex(ValueError, "episode_rename_in_progress"),
            ):
                MainWindow.enqueue_download(
                    enqueue_harness,
                    locked_job.url,
                    None,
                    None,
                    temporary,
                )
            save_runs.assert_not_called()

    def test_episode_rename_execute_is_blocked_by_alias_mutations(self) -> None:
        target = DownloadJob(
            job_id="rename-target",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\Target",
            state="완료",
        )
        active_alias = DownloadJob(
            job_id="download-alias",
            url=target.url,
            output_dir=target.output_dir,
            output_path=r"D:\Temporary\Alias",
            state="실행 중",
        )
        harness = type("RenameReverseMutationHarness", (), {})()
        harness.selected_job = lambda _job_id=None: target
        harness.exit_requested = False
        harness.exit_after_episode_rename = False
        harness.episode_rename_tasks = {}
        harness.active_contexts = {
            active_alias.job_id: ProcessContext(
                job=active_alias, run=DownloadRun.from_job(active_alias)
            )
        }
        harness.pending_jobs = deque()
        harness.pending_pdf_jobs = set()
        harness.file_verify_processes = {}
        harness.image_preview_processes = {}
        harness.duplicate_image_tasks = {}
        harness.image_conversion_processes = {}
        harness.pdf_generation_processes = {}

        download_block = MainWindow.start_episode_folder_rename(
            harness, target.job_id, execute=True
        )
        self.assertFalse(download_block["started"])
        self.assertTrue(download_block["mutationBlocked"])
        self.assertIn("downloadActive", download_block["conflictingServices"])

        harness.active_contexts = {}
        harness.image_conversion_processes = {
            "conversion-alias": ImageConversionProcessContext(
                process=_ProcessStub(),
                execute=True,
                job_id="conversion-alias",
                work_key="different-work",
                output_path=r"c:\manga\target\.",
            )
        }
        conversion_block = MainWindow.start_episode_folder_rename(
            harness, target.job_id, execute=True
        )
        self.assertFalse(conversion_block["started"])
        self.assertEqual(
            conversion_block["errorCode"], "job_mutation_in_progress"
        )
        self.assertIn(
            "imageConversion", conversion_block["conflictingServices"]
        )

    def test_download_scheduler_skips_work_under_episode_rename_execute(self) -> None:
        blocked = DownloadJob(
            job_id="queued-alias",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\Queued Alias",
        )
        unrelated = DownloadJob(
            job_id="queued-other",
            url="https://newtoki1.org/manhwa/99999",
            output_dir=r"C:\Manga",
        )
        rename_context = toki_gui.EpisodeRenameTaskContext(
            task=SimpleNamespace(),
            execute=True,
            origin="cli",
            job_id="rename-original",
            work_key=blocked.work_key,
            output_path=r"D:\Original Path",
        )
        harness = type("SchedulerMutationGuardHarness", (), {})()
        harness.config = {"workConcurrency": 1}
        harness.pending_jobs = deque([blocked, unrelated])
        harness.active_contexts = {}
        harness.episode_rename_tasks = {"rename-original": rename_context}
        harness.pdf_generation_processes = {}
        harness.pending_pdf_jobs = set()
        launched = []
        harness._launch_context = lambda context: launched.append(context.job.job_id)
        harness._refresh_pending_positions = lambda: None
        harness._update_active_summary = lambda: None

        with patch("toki_gui.load_run", return_value=None):
            MainWindow._start_next_job(harness)

        self.assertEqual(launched, [unrelated.job_id])
        self.assertEqual(list(harness.active_contexts), [unrelated.job_id])
        self.assertEqual([job.job_id for job in harness.pending_jobs], [blocked.job_id])

    def test_episode_folder_rename_control_response_waits_for_worker_completion(
        self,
    ) -> None:
        socket = _ControlSocketStub()
        callbacks = []
        harness = type("EpisodeRenameControlHarness", (), {})()
        harness.control_sockets = {socket}
        harness.log = lambda *_args, **_kwargs: None
        harness.start_episode_folder_rename = (
            lambda job_id, execute=False, origin="gui", completion=None: (
                callbacks.append((job_id, execute, origin, completion)),
                {"started": True, "jobId": job_id},
            )[-1]
        )
        harness._episode_rename_start_error = MainWindow._episode_rename_start_error
        harness._write_control_response = (
            lambda selected, response: MainWindow._write_control_response(
                harness, selected, response
            )
        )

        MainWindow._start_control_episode_folder_rename(
            harness,
            socket,
            {
                "action": "rename_episode_folders",
                "jobId": "j1",
                "execute": False,
            },
        )

        self.assertEqual(socket.writes, [])
        self.assertEqual(callbacks[0][:3], ("j1", False, "cli"))
        callbacks[0][3]("j1", {"jobId": "j1", "renameCount": 3}, "")
        response = json.loads(socket.writes[0].decode("utf-8"))
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["renameCount"], 3)
        self.assertTrue(socket.flushed)
        self.assertTrue(socket.disconnected)

    def test_episode_folder_rename_control_execute_requires_confirmation(self) -> None:
        socket = _ControlSocketStub()
        harness = type("EpisodeRenameControlConfirmationHarness", (), {})()
        harness.control_sockets = {socket}
        harness.log = lambda *_args, **_kwargs: None
        harness.start_episode_folder_rename = lambda *_args, **_kwargs: self.fail(
            "unconfirmed execute must not start"
        )
        harness._episode_rename_start_error = MainWindow._episode_rename_start_error
        harness._write_control_response = (
            lambda selected, response: MainWindow._write_control_response(
                harness, selected, response
            )
        )

        MainWindow._start_control_episode_folder_rename(
            harness,
            socket,
            {
                "action": "rename_episode_folders",
                "jobId": "j1",
                "execute": True,
            },
        )

        response = json.loads(socket.writes[0].decode("utf-8"))
        self.assertFalse(response["ok"])
        self.assertIn("--execute --yes", response["error"])

    def test_episode_folder_rename_control_reports_mutation_block_code(self) -> None:
        socket = _ControlSocketStub()
        harness = type("EpisodeRenameControlBlockedHarness", (), {})()
        harness.control_sockets = {socket}
        harness.log = lambda *_args, **_kwargs: None
        harness.start_episode_folder_rename = lambda *_args, **_kwargs: {
            "started": False,
            "mutationBlocked": True,
            "errorCode": "job_mutation_in_progress",
            "error": "같은 작품의 다운로드가 진행 중입니다.",
        }
        harness._episode_rename_start_error = MainWindow._episode_rename_start_error
        harness._write_control_response = (
            lambda selected, response: MainWindow._write_control_response(
                harness, selected, response
            )
        )

        MainWindow._start_control_episode_folder_rename(
            harness,
            socket,
            {
                "action": "rename_episode_folders",
                "jobId": "j1",
                "execute": True,
                "confirmed": True,
            },
        )

        response = json.loads(socket.writes[0].decode("utf-8"))
        self.assertFalse(response["ok"])
        self.assertIn("[job_mutation_in_progress]", response["error"])

    def test_episode_folder_rename_confirmation_no_never_executes(self) -> None:
        calls = []
        completions = []
        plan = {
            "canExecute": True,
            "renameCount": 1,
            "fallbackSuffixCount": 0,
            "mappings": [
                {
                    "sourceFolderName": "0001 축약 1화",
                    "destinationFolderName": "전체 작품 1화",
                    "samePath": False,
                }
            ],
        }
        harness = type("EpisodeRenameConfirmationHarness", (), {})()
        harness.start_episode_folder_rename = (
            lambda job_id, execute=False, origin="gui", completion=None: (
                calls.append((job_id, execute, origin)),
                completions.append(completion),
                {"started": True, "jobId": job_id},
            )[-1]
        )
        harness._episode_folder_rename_plan_ready = (
            lambda job_id, result, error: MainWindow._episode_folder_rename_plan_ready(
                harness, job_id, result, error
            )
        )
        harness._present_episode_folder_rename_plan = (
            lambda job_id, result: MainWindow._present_episode_folder_rename_plan(
                harness, job_id, result
            )
        )
        harness.exit_after_episode_rename = False

        with (
            patch.object(
                toki_gui.QMessageBox,
                "question",
                return_value=toki_gui.QMessageBox.StandardButton.No,
            ) as question,
            patch.object(toki_gui.QMessageBox, "information") as information,
        ):
            MainWindow.confirm_rename_episode_folders(harness, "j1")
            question.assert_not_called()
            completions[0]("j1", plan, "")

        question.assert_called_once()
        information.assert_not_called()
        self.assertEqual(calls, [("j1", False, "gui")])

    def test_episode_folder_rename_confirmation_yes_queues_execute_worker(self) -> None:
        plan = {
            "canExecute": True,
            "renameCount": 1,
            "fallbackSuffixCount": 0,
            "mappings": [
                {
                    "sourceFolderName": "0001 축약 1화",
                    "destinationFolderName": "전체 작품 1화",
                    "samePath": False,
                }
            ],
        }
        starts = []
        harness = type("EpisodeRenameExecuteHarness", (), {})()
        harness.start_episode_folder_rename = (
            lambda job_id, execute=False, origin="gui", completion=None: (
                starts.append((job_id, execute, origin, completion)),
                {"started": True, "jobId": job_id},
            )[-1]
        )
        harness._episode_folder_rename_execute_ready = lambda *_args: None

        with (
            patch.object(
                toki_gui.QMessageBox,
                "question",
                return_value=toki_gui.QMessageBox.StandardButton.Yes,
            ),
            patch.object(toki_gui.QMessageBox, "information") as information,
        ):
            MainWindow._present_episode_folder_rename_plan(harness, "j1", plan)

        self.assertEqual(starts[0][:3], ("j1", True, "gui"))
        self.assertIs(starts[0][3], harness._episode_folder_rename_execute_ready)
        information.assert_not_called()

    def test_episode_folder_rename_completion_defers_exit_until_last_task(self) -> None:
        status = _StatusBarStub()
        completions = []
        task = SimpleNamespace()
        context = toki_gui.EpisodeRenameTaskContext(
            task=task,
            execute=True,
            origin="cli",
            completion=lambda job_id, result, error: completions.append(
                (job_id, result, error)
            ),
        )
        harness = type("EpisodeRenameExitHarness", (), {})()
        harness.episode_rename_tasks = {"j1": context}
        harness.exit_after_episode_rename = True
        harness.log = lambda *_args, **_kwargs: None
        harness.statusBar = lambda: status
        harness.close = lambda: None

        with patch.object(toki_gui.QTimer, "singleShot") as single_shot:
            MainWindow._episode_folder_rename_finished(
                harness,
                "j1",
                {"renamedCount": 1},
                "",
            )

        self.assertEqual(completions, [("j1", {"renamedCount": 1}, "")])
        self.assertEqual(harness.episode_rename_tasks, {})
        single_shot.assert_called_once_with(100, harness.close)

    def test_episode_folder_rename_block_dialog_explains_each_cause(self) -> None:
        cases = [
            (
                "recovery",
                {
                    "canExecute": False,
                    "recoveryRequired": True,
                    "recovery": {
                        "message": "이전 이름 변경의 복구 자료가 남아 있습니다.",
                        "transactionFiles": [
                            {"path": r"C:\Manga\.toki-episode-rename-a.json"}
                        ],
                    },
                    "conflicts": [{"type": "recovery_required"}],
                },
                "복구 자료 위치",
            ),
            (
                "unsafe",
                {
                    "canExecute": False,
                    "unsafeSuffixCount": 1,
                    "conflicts": [
                        {
                            "type": "unsafe_suffix",
                            "unsafeSuffix": True,
                            "source": r"C:\Manga\0001 제목 없음",
                        }
                    ],
                },
                "회차명 판별 실패",
            ),
            (
                "duplicate",
                {
                    "canExecute": False,
                    "duplicateNumbers": [1, 2],
                    "conflicts": [],
                },
                "중복 회차",
            ),
            (
                "path_conflict",
                {
                    "canExecute": False,
                    "conflicts": [
                        {
                            "type": "path_conflict",
                            "existingDestination": True,
                            "destination": r"C:\Manga\전체 작품 1화",
                        }
                    ],
                },
                "이미 존재",
            ),
            (
                "path_too_long",
                {
                    "canExecute": False,
                    "conflicts": [
                        {
                            "type": "path_too_long",
                            "pathTooLong": True,
                            "destination": r"C:\Manga\매우 긴 회차 폴더",
                        }
                    ],
                },
                "Windows 안전 경로 길이 초과",
            ),
        ]

        for label, plan, expected in cases:
            with self.subTest(label=label):
                harness = type("EpisodeRenameBlockedHarness", (), {})()
                with (
                    patch.object(toki_gui.QMessageBox, "warning") as warning,
                    patch.object(toki_gui.QMessageBox, "question") as question,
                ):
                    MainWindow._present_episode_folder_rename_plan(
                        harness, "j1", plan
                    )

                question.assert_not_called()
                warning.assert_called_once()
                self.assertIn(expected, str(warning.call_args.args[2]))

    def test_job_context_menu_snapshot_recurses_into_checked_organize_leaves(
        self,
    ) -> None:
        job = DownloadJob(
            job_id="organized-work",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\organized-work",
            state="완료",
            tag_color="blue",
        )
        snapshot = self._job_context_menu_snapshot(
            job,
            current_collection={"groupId": "favorites", "name": "즐겨찾기"},
            groups=[{"groupId": "favorites", "name": "즐겨찾기"}],
        )

        self.assertIn("organize.collection.none", snapshot["actionIds"])
        self.assertIn("organize.collection.favorites", snapshot["actionIds"])
        self.assertIn("organize.tag.blue", snapshot["actionIds"])
        self.assertEqual(
            snapshot["submenus"]["작품 정리 > 정리 그룹"],
            ["미분류", "즐겨찾기", "그룹 관리..."],
        )
        self.assertIn("파랑", snapshot["submenus"]["작품 정리 > 색상 태그"])
        self.assertFalse(snapshot["checked"]["organize.collection.none"])
        self.assertTrue(snapshot["checked"]["organize.collection.favorites"])
        self.assertTrue(snapshot["checked"]["organize.tag.blue"])
        self.assertFalse(snapshot["checked"]["organize.tag.none"])

    def test_job_context_menu_retry_wait_has_stop_without_pause(self) -> None:
        job = DownloadJob(
            job_id="retry-wait",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            state="재시도 대기",
        )
        snapshot = self._job_context_menu_snapshot(
            job,
            active_context=SimpleNamespace(paused=False, process=None),
        )

        self.assertEqual(snapshot["submenus"]["작업 제어"], ["현재 작업 중지"])
        self.assertIn("job.stop", snapshot["actionIds"])
        self.assertNotIn("job.pause", snapshot["actionIds"])
        self.assertNotIn("job.resume", snapshot["actionIds"])

    def test_job_context_menu_stale_active_record_offers_only_recovery(self) -> None:
        job = DownloadJob(
            job_id="stale-running",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            state="실행 중",
        )
        snapshot = self._job_context_menu_snapshot(job)

        self.assertIn("recovery.inspect", snapshot["actionIds"])
        self.assertNotIn("section.rescan", snapshot["actionIds"])
        self.assertNotIn("job.rescan_new", snapshot["actionIds"])
        self.assertNotIn("job.rescan_full", snapshot["actionIds"])
        self.assertFalse(snapshot["enabled"]["record.remove"])

    def test_job_context_menu_branches_for_idle_manga_and_youtube(self) -> None:
        manga = DownloadJob(
            job_id="idle-manga",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\idle-manga",
            state="완료",
        )
        youtube = DownloadJob(
            job_id="idle-youtube",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir=r"C:\Videos",
            output_path=r"C:\Videos",
            provider="youtube",
            state="완료",
        )

        manga_snapshot = self._job_context_menu_snapshot(manga)
        youtube_snapshot = self._job_context_menu_snapshot(youtube)

        self.assertIn("section.rescan", manga_snapshot["actionIds"])
        self.assertIn("section.files", manga_snapshot["actionIds"])
        self.assertIn("episodes.rename", manga_snapshot["actionIds"])
        self.assertIn("section.data", manga_snapshot["actionIds"])
        self.assertNotIn("job.retry", manga_snapshot["actionIds"])
        self.assertIn("job.retry", youtube_snapshot["actionIds"])
        self.assertNotIn("section.rescan", youtube_snapshot["actionIds"])
        self.assertNotIn("section.files", youtube_snapshot["actionIds"])
        self.assertNotIn("section.data", youtube_snapshot["actionIds"])

    def test_job_context_menu_disables_file_mutations_while_episode_rename_is_busy(
        self,
    ) -> None:
        job = DownloadJob(
            job_id="rename-busy",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\Manga",
            output_path=r"C:\Manga\rename-busy",
            state="완료",
        )
        harness = _JobContextMenuHarness()
        harness.episode_rename_tasks[job.job_id] = SimpleNamespace(
            execute=True,
            origin="gui",
        )
        with (
            patch("toki_gui.work_collection_for_job", return_value=None),
            patch("toki_gui.list_work_collections", return_value=[]),
        ):
            menu = MainWindow._build_job_context_menu(harness, job)
            snapshot = MainWindow._menu_snapshot(menu)
        menu.deleteLater()
        harness.deleteLater()
        self.qt_app.processEvents()

        self.assertIn("episodes.rename", snapshot["actionIds"])
        self.assertFalse(snapshot["enabled"]["episodes.rename"])
        self.assertFalse(snapshot["enabled"]["folder.move"])
        self.assertFalse(snapshot["enabled"]["files.verify"])
        self.assertFalse(snapshot["enabled"]["record.remove"])
        self.assertNotIn("section.rescan", snapshot["actionIds"])
        self.assertIn(
            "회차 폴더명 정리 중…",
            snapshot["submenus"]["파일 및 회차 도구"],
        )

    def test_open_output_folder_uses_job_output_dir_before_global_default(self) -> None:
        job = DownloadJob(
            job_id="old-work",
            url="https://newtoki1.org/manhwa/34360",
            output_dir=r"C:\OldLibrary",
            output_path="",
            state="오류",
        )
        harness = SimpleNamespace(
            selected_job=lambda _job_id: job,
            output_edit=SimpleNamespace(text=lambda: r"C:\CurrentLibrary"),
            log=lambda *_args, **_kwargs: None,
        )

        with patch("toki_gui.open_in_explorer") as open_folder:
            target = MainWindow.open_output_folder(harness, job.job_id)

        self.assertEqual(target, r"C:\OldLibrary")
        open_folder.assert_called_once_with(r"C:\OldLibrary")

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
        self.assertEqual(SettingsDialog.matching_tab_indexes("비디오 코덱"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("썸네일 정보 json"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("채널 재생목록 역순"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("챕터 마커"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("업로드 날짜 mtime"), [4])
        self.assertEqual(
            SettingsDialog.matching_tab_indexes("서버 자동 수동 우선순위"), [4]
        )
        self.assertEqual(
            SettingsDialog.matching_tab_indexes("갤러리 메타데이터"), [4]
        )
        self.assertEqual(SettingsDialog.matching_tab_indexes("갤러리 정보"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("이미지 파일명 원본 숫자"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("제외 태그 규칙"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("일본어 제목 우선"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("metadata.json info.txt 파일 저장"), [4])
        self.assertEqual(SettingsDialog.matching_tab_indexes("이미지 품질 최적화"), [4])
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
            harness, {"action": "show_cookie_manager", "provider": "exhentai"}
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_cookie_manager"}
        )
        self.assertEqual(shown, {"shown": True})
        self.assertEqual(closed, {"closed": True})
        self.assertEqual(calls, [("show", "exhentai"), ("close",)])

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

    def test_hitomi_metadata_ipc_plans_offline_and_controls_dialog(self) -> None:
        calls = []
        harness = type("HitomiMetadataIpcHarness", (), {})()
        harness.config = default_config()
        harness.show_hitomi_metadata = (
            lambda reference, provider, fixture: calls.append(
                ("show", reference, provider, fixture)
            )
            or {"shown": True, "fetchRunning": False}
        )
        harness.close_hitomi_metadata = (
            lambda: calls.append(("close",)) or True
        )
        planned = MainWindow._handle_control_action(
            harness,
            {
                "action": "hitomi_metadata_plan",
                "reference": "https://exhentai.org/g/987654/abcdef1234/",
                "provider": "auto",
            },
        )
        shown = MainWindow._handle_control_action(
            harness,
            {
                "action": "show_hitomi_metadata",
                "reference": "42",
                "provider": "hitomi",
                "fixture": "fixture.js",
            },
        )
        closed = MainWindow._handle_control_action(
            harness, {"action": "close_hitomi_metadata"}
        )
        self.assertEqual(planned["request"]["method"], "POST")
        self.assertNotIn("abcdef1234", repr(planned))
        self.assertTrue(shown["shown"])
        self.assertTrue(closed["closed"])
        self.assertEqual(
            calls,
            [("show", "42", "hitomi", "fixture.js"), ("close",)],
        )

    def test_hitomi_metadata_state_reports_selected_japanese_title(self) -> None:
        text_stub = type("TextStub", (), {"text": lambda self: "1234567"})()
        checkbox_stub = type("CheckStub", (), {"isChecked": lambda self: False})()
        owner = type(
            "OwnerStub",
            (),
            {"config": {**default_config(), "hitomiPreferJapaneseTitle": True}},
        )()
        harness = type(
            "MetadataStateHarness",
            (),
            {
                "owner": owner,
                "last_result": {
                    "ok": True,
                    "galleryId": "1234567",
                    "workKey": "hitomi:1234567",
                    "title": "Romanized Title",
                    "japaneseTitle": "日本語タイトル",
                },
                "reference_edit": text_stub,
                "use_cookies_checkbox": checkbox_stub,
                "fixture_path": "fixture.js",
                "fetch_task": None,
                "isVisible": lambda self: True,
                "_provider": lambda self: "hitomi",
            },
        )()
        snapshot = HitomiMetadataDialog.state_snapshot(harness)
        self.assertEqual(snapshot["titleSelection"]["selectedTitle"], "日本語タイトル")
        self.assertEqual(snapshot["titleSelection"]["selectedField"], "japaneseTitle")
        self.assertFalse(snapshot["titleSelection"]["usedFallback"])
        self.assertTrue(snapshot["imageSourcePlan"]["useOriginal"])
        self.assertFalse(snapshot["imageSourcePlan"]["networkRequested"])
        self.assertFalse(snapshot["useStoredCookies"])
        self.assertFalse(snapshot["cookieValuesExposed"])

    def test_hitomi_metadata_cookie_fetch_reads_vault_only_when_opted_in(self) -> None:
        config = default_config()
        reference = "https://exhentai.org/g/987654/abcdef1234/"
        with (
            patch(
                "toki_gui.provider_cookie_request_header",
                return_value="ipb_member_id=member; ipb_pass_hash=secret",
            ) as header,
            patch(
                "toki_gui.fetch_hitomi_metadata",
                return_value={"ok": True},
            ) as fetch,
        ):
            result = HitomiMetadataDialog._fetch_metadata_service(
                reference, "auto", config, False
            )
        self.assertTrue(result["ok"])
        header.assert_not_called()
        fetch.assert_called_once_with(
            reference, provider_hint="auto", config=config, confirmed=True
        )

        with (
            patch(
                "toki_gui.provider_cookie_request_header",
                return_value="ipb_member_id=member; ipb_pass_hash=secret",
            ) as header,
            patch(
                "toki_gui.fetch_hitomi_metadata",
                return_value={"ok": True},
            ) as fetch,
        ):
            result = HitomiMetadataDialog._fetch_metadata_service(
                reference, "auto", config, True
            )
        self.assertTrue(result["ok"])
        header.assert_called_once_with(
            "exhentai", "https://api.e-hentai.org/api.php"
        )
        fetch.assert_called_once_with(
            reference,
            provider_hint="auto",
            config=config,
            confirmed=True,
            cookie_header="ipb_member_id=member; ipb_pass_hash=secret",
        )

        with (
            patch("toki_gui.provider_cookie_request_header") as header,
            patch("toki_gui.fetch_hitomi_metadata") as fetch,
        ):
            result = HitomiMetadataDialog._fetch_metadata_service(
                "42", "auto", config, True
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["errorCode"], "hitomi.cookie_host_mismatch")
        header.assert_not_called()
        fetch.assert_not_called()

        required = {**config, "hitomiMetadataMode": "required"}
        with patch(
            "toki_gui.fetch_hitomi_metadata",
            side_effect=toki_gui.HitomiReferenceError(
                "hitomi.metadata_dns", "DNS 주소를 확인하지 못했습니다."
            ),
        ):
            result = HitomiMetadataDialog._fetch_metadata_service(
                reference, "auto", required, False
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["errorCode"], "hitomi.metadata_dns")
        self.assertEqual(result["metadataPolicy"]["decision"], "stop")
        self.assertFalse(result["metadataPolicy"]["shouldContinue"])

    def test_hitomi_metadata_failure_text_exposes_mode_decision(self) -> None:
        class TextStub:
            value = ""

            def setPlainText(self, value: str) -> None:
                self.value = value

        harness = type("MetadataResultHarness", (), {})()
        harness.last_result = {}
        harness.result_text = TextStub()
        result = {
            "ok": False,
            "errorCode": "hitomi.metadata_network",
            "error": "연결 실패",
            "metadataPolicy": {
                "mode": "required",
                "decision": "stop",
                "shouldContinue": False,
            },
        }
        HitomiMetadataDialog._set_result(harness, result)
        self.assertIn("현재 모드: required", harness.result_text.value)
        self.assertIn("정책 결정: 작업 중단", harness.result_text.value)

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

    def test_apply_settings_updates_config_backed_download_controls(self) -> None:
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
        harness.download_settings_summary = _SettingWidgetStub()
        harness._update_download_settings_summary = (
            lambda: MainWindow._update_download_settings_summary(harness)
        )
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
        self.assertEqual(harness.config["workConcurrency"], 3)
        self.assertEqual(harness.config["imageConcurrency"], 11)
        self.assertEqual(
            harness.download_settings_summary.value,
            "작품 3 · 이미지 11 · 재시도 4회 · 브라우저 표시",
        )
        self.assertFalse(harness.log_box.value)
        self.assertEqual(display_updates, [result])
        self.assertEqual(harness.persist_timer.interval, 7000)
        self.assertEqual(harness.persist_timer.started, 1)
        self.assertEqual(harness.persist_timer.stopped, 1)

    def test_download_settings_setters_use_config_as_single_runtime_source(self) -> None:
        harness = type("DownloadSettingsHarness", (), {})()
        harness.config = default_config()
        harness.download_settings_summary = _SettingWidgetStub()
        harness.logs = []
        harness.log = lambda message, *_args, **_kwargs: harness.logs.append(message)
        harness._start_next_job = lambda: None
        harness._update_download_settings_summary = (
            lambda: MainWindow._update_download_settings_summary(harness)
        )

        with (
            patch("toki_gui.save_config") as save,
            patch("toki_gui.QTimer.singleShot") as single_shot,
        ):
            work = MainWindow.set_work_concurrency(harness, 3)
            image = MainWindow.set_image_concurrency(harness, 9)
            retry = MainWindow.set_retry_policy(
                harness, retry_count=4, backoff_seconds=7
            )

        self.assertEqual(work, {"workConcurrency": 3})
        self.assertEqual(image, {"imageConcurrency": 9})
        self.assertEqual(
            retry,
            {"retryCount": 4, "retryBackoffSeconds": 7},
        )
        self.assertEqual(harness.config["workConcurrency"], 3)
        self.assertEqual(harness.config["imageConcurrency"], 9)
        self.assertEqual(harness.config["retryCount"], 4)
        self.assertEqual(harness.config["retryBackoffSeconds"], 7)
        self.assertEqual(
            harness.download_settings_summary.value,
            "작품 3 · 이미지 9 · 재시도 4회 · 브라우저 숨김",
        )
        self.assertEqual(save.call_count, 3)
        single_shot.assert_called_once()

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
        harness.config = {"workConcurrency": 2}
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

    def test_youtube_context_uses_hidden_python_worker_and_normalized_progress(self) -> None:
        job = DownloadJob(
            job_id="youtube-sim",
            url="https://www.youtube.com/playlist?list=playlist-one",
            output_dir=r"C:\Video",
            simulation=True,
        )
        context = ProcessContext(job=job, run=DownloadRun.from_job(job))
        harness = type("YouTubeHarness", (), {})()
        harness.config = default_config()
        harness.active_contexts = {job.job_id: context}
        harness._update_job_card = lambda _job: None
        harness._read_stdout = lambda _job_id: None
        harness._read_stderr = lambda _job_id: None
        harness._process_started = lambda _job_id: None
        harness._process_error = lambda _job_id, _error: None
        harness._process_finished = lambda _job_id, _code, _status: None
        harness._schedule_job_card_update = lambda _job, _event: None
        harness.log = lambda *_args, **_kwargs: None
        _ProcessStub.instances = []

        with patch("toki_gui.create_background_process", _ProcessStub):
            MainWindow._launch_context(harness, context)

        process = _ProcessStub.instances[0]
        self.assertEqual(process.program, sys.executable)
        self.assertTrue(process.arguments[0].endswith("youtube_worker.py"))
        self.assertIn("--simulate", process.arguments)
        self.assertEqual(context.run.operation, "youtube_simulation")

        with patch("toki_gui.save_runs"):
            MainWindow._handle_downloader_event(
                harness,
                job.job_id,
                {
                    "event": "youtube_item",
                    "title": "목록의 두 번째 영상",
                    "itemIndex": 2,
                    "itemTotal": 4,
                },
            )
            MainWindow._handle_downloader_event(
                harness,
                job.job_id,
                {
                    "event": "youtube_progress",
                    "itemIndex": 2,
                    "itemTotal": 4,
                    "itemProgress": 50,
                    "progress": 37,
                },
            )
        self.assertEqual(job.title, "목록의 두 번째 영상")
        self.assertEqual(job.progress, 37)
        self.assertEqual(job.episode_index, 2)
        self.assertEqual(context.run.selected_episodes, 4)
        self.assertEqual(context.run.processed_episodes, 1)
        self.assertEqual(context.run.progress, 37)

    def test_youtube_manual_retry_requeues_same_provider_instead_of_manga_rescan(self) -> None:
        source = DownloadJob(
            job_id="youtube-old",
            url="https://www.youtube.com/watch?v=video-one",
            output_dir=r"C:\Video",
            state="오류",
            simulation=True,
        )
        captured = {}
        harness = type("YouTubeRetryHarness", (), {})()
        harness.selected_job = lambda _job_id=None: source
        harness.enqueue_download = lambda **kwargs: captured.update(kwargs) or source
        harness.log = lambda *_args, **_kwargs: None

        result = MainWindow.retry_job(harness, source.job_id)

        self.assertIs(result, source)
        self.assertTrue(captured["simulation"])
        self.assertEqual(captured["url"], source.url)
        self.assertEqual(captured["scan_mode"], "new")

    def test_retry_and_rescan_reject_unknown_explicit_job_ids(self) -> None:
        harness = type("MissingJobHarness", (), {})()
        harness.selected_job = lambda _job_id=None: None
        harness.enqueue_download = lambda **_kwargs: self.fail(
            "missing work must not be enqueued"
        )

        with self.assertRaisesRegex(ValueError, "missing-retry"):
            MainWindow.retry_job(harness, "missing-retry")
        with self.assertRaisesRegex(ValueError, "missing-rescan"):
            MainWindow.rescan_job(harness, "missing-rescan", "new")

    def test_file_tool_result_dialogs_can_be_closed_through_ipc(self) -> None:
        class DialogStub:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        harness = type("FileDialogHarness", (), {})()
        verify_dialog = DialogStub()
        preview_dialog = DialogStub()
        harness.active_file_verify_dialog = verify_dialog
        harness.active_image_preview_dialog = preview_dialog
        harness.close_file_verification = lambda: MainWindow.close_file_verification(
            harness
        )
        harness.close_image_preview = lambda: MainWindow.close_image_preview(harness)

        verify_result = MainWindow._handle_control_action(
            harness, {"action": "close_file_verification"}
        )
        preview_result = MainWindow._handle_control_action(
            harness, {"action": "close_image_preview"}
        )

        self.assertEqual(verify_result, {"closed": True})
        self.assertEqual(preview_result, {"closed": True})
        self.assertTrue(verify_dialog.closed)
        self.assertTrue(preview_dialog.closed)
        self.assertIsNone(harness.active_file_verify_dialog)
        self.assertIsNone(harness.active_image_preview_dialog)

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
