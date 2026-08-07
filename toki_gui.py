from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import psutil
from PyQt6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QProcess,
    QProcessEnvironment,
    QRect,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QDesktopServices,
    QFont,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt6.QtNetwork import QHostAddress, QLocalServer, QTcpServer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QStyleOptionViewItem,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

WEBENGINE_IMPORT_ERROR = ""
try:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError as error:
    WEBENGINE_IMPORT_ERROR = str(error)
    QWebEnginePage = None
    QWebEngineProfile = None
    QWebEngineView = None

from hitomi_provider import (
    HITOMI_SERVER_CATALOG,
    HitomiReferenceError,
    fetch_hitomi_metadata,
    hitomi_excluded_tag_policy_snapshot,
    hitomi_filename_policy_snapshot,
    hitomi_metadata_policy_snapshot,
    hitomi_metadata_file_policy_snapshot,
    hitomi_metadata_request_plan,
    hitomi_original_image_policy_snapshot,
    hitomi_provider_capabilities,
    hitomi_server_policy_snapshot,
    hitomi_title_policy_snapshot,
    inspect_hitomi_reference,
    load_hitomi_metadata_fixture,
    plan_hitomi_metadata_files,
    plan_hitomi_image_sources,
    select_hitomi_display_title,
    write_hitomi_metadata_files,
)
from youtube_provider import (
    YOUTUBE_AUDIO_CODECS,
    YOUTUBE_CONTAINERS,
    YOUTUBE_FORMAT_MODES,
    YOUTUBE_MAX_HEIGHTS,
    YOUTUBE_VIDEO_CODECS,
    YOUTUBE_SUBTITLE_MODES,
    YOUTUBE_SUBTITLE_FORMATS,
    YOUTUBE_AUDIO_TRACK_MODES,
    YOUTUBE_COLLECTION_ORDERS,
    youtube_format_policy_snapshot,
    preview_youtube_filename,
)


def webengine_runtime_status() -> dict[str, Any]:
    available = all((QWebEnginePage, QWebEngineProfile, QWebEngineView))
    return {
        "available": bool(available),
        "importError": WEBENGINE_IMPORT_ERROR,
    }

from toki_core import (
    APP_VERSION,
    ACTIVE_JOB_STATES,
    archive_viewer_policy_snapshot,
    CONTROL_SERVER_NAME,
    EVENT_PREFIX,
    JOB_DB_PATH,
    LOG_PATH,
    ROOT_DIR,
    TAG_COLORS,
    DownloadJob,
    DownloadRun,
    SleepPreventionController,
    append_bounded_text,
    available_ui_languages,
    assign_job_to_collection,
    available_work_slots,
    append_log,
    build_job_list_view_state,
    build_work_key,
    build_downloader_args,
    clear_proxy_credentials,
    completion_action_plan,
    cookie_import_plan,
    credential_store_status,
    clear_provider_cookies,
    clear_log_file,
    cleanup_run_history,
    cleanup_thumbnail_cache,
    count_jobs,
    count_runs,
    create_work_collection,
    delete_job_record,
    delete_job_records,
    dependency_diagnostics,
    downloader_event_update_policy,
    downloader_environment_overrides,
    embedded_browser_capabilities,
    embedded_browser_navigation_plan,
    error_category_label,
    export_diagnostics,
    export_jobs_snapshot,
    export_provider_cookies,
    export_shortcut_settings,
    find_duplicate_works,
    find_duplicate_images,
    folder_name_template_preview,
    find_node,
    hydrate_job_metadata,
    image_processing_policy_snapshot,
    import_app_settings,
    import_jobs_snapshot,
    import_provider_cookies,
    shortcut_import_plan,
    inspect_local_archive,
    inspect_clipboard_url,
    job_database_diagnostics,
    keyboard_shortcut_catalog,
    keyboard_shortcut_keys,
    menu_action_availability,
    quick_action_catalog,
    provider_cookie_status,
    provider_cookie_policy,
    provider_cookie_request_header,
    pdf_generation_policy_snapshot,
    generate_local_api_token,
    local_api_policy_snapshot,
    local_api_request_plan,
    LOCAL_API_MAX_REQUEST_BYTES,
    proxy_credential_status,
    load_ui_strings,
    lookup_public_ip,
    load_config,
    load_job_by_id,
    load_job_by_work_key,
    load_jobs_page,
    list_job_episode_images,
    list_performance_policy_snapshot,
    memory_usage_snapshot,
    list_work_collections,
    log_retention_status,
    load_run,
    load_runs_page,
    mark_job_cancelled,
    mark_run_cancelled,
    move_job_folder as execute_job_folder_move,
    normalize_image_concurrency,
    normalize_image_excluded_extensions,
    normalize_image_resize_dimension,
    normalize_shortcut_overrides,
    normalize_embedded_browser_url,
    normalize_retry_backoff,
    normalize_retry_count,
    normalize_scan_request,
    normalize_work_concurrency,
    notification_event_plan,
    notification_settings_snapshot,
    open_in_explorer,
    open_archive_with_viewer,
    plan_archive_viewer_open,
    persistence_policy_snapshot,
    plan_job_folder_move,
    plan_metadata_rebuild,
    plan_window_geometry,
    read_log_tail,
    read_run_log,
    rebuild_job_metadata as execute_metadata_rebuild,
    rename_work_collection,
    recover_interrupted_jobs,
    rescan_job_parameters,
    resource_admission,
    resource_budget,
    reset_app_settings,
    resolve_cover_path,
    reorder_pending_jobs,
    save_config,
    save_jobs,
    save_runs,
    settings_snapshot,
    shortcut_settings_snapshot,
    sleep_prevention_policy_snapshot,
    store_proxy_credentials,
    set_job_pause_state,
    set_process_tree_paused,
    retry_backoff_seconds,
    should_auto_retry,
    thumbnail_cache_path,
    update_job_note,
    update_job_markers,
    update_app_settings,
    validate_url,
    verify_job_files,
    work_collection_for_job,
)


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def hidden_process_options() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startup,
    }


class HiddenProcess(QObject):
    readyReadStandardOutput = pyqtSignal()
    readyReadStandardError = pyqtSignal()
    started = pyqtSignal()
    errorOccurred = pyqtSignal(object)
    finished = pyqtSignal(int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._working_directory = str(ROOT_DIR)
        self._program = ""
        self._arguments: list[str] = []
        self._environment_overrides: dict[str, str] = {}
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout = bytearray()
        self._stderr = bytearray()
        self._max_output_bytes = int(resource_budget()["maxProcessOutputBytes"])
        self._dropped_output_bytes = {"stdout": 0, "stderr": 0}
        self._lock = threading.Lock()
        self._error = ""
        self._reader_threads: list[threading.Thread] = []

    def setWorkingDirectory(self, path: str) -> None:
        self._working_directory = path

    def setProgram(self, program: str) -> None:
        self._program = program

    def setArguments(self, arguments: list[str]) -> None:
        self._arguments = list(arguments)

    def setEnvironmentOverrides(self, values: dict[str, str]) -> None:
        self._environment_overrides = dict(values)

    def start(self) -> None:
        try:
            self._process = subprocess.Popen(
                [self._program, *self._arguments],
                cwd=self._working_directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, **self._environment_overrides},
                **hidden_process_options(),
            )
        except OSError as error:
            self._error = str(error)
            self.errorOccurred.emit(QProcess.ProcessError.FailedToStart)
            self.finished.emit(-1, QProcess.ExitStatus.CrashExit)
            return
        self.started.emit()
        stdout_thread = threading.Thread(
            target=self._read_stream,
            args=(
                self._process.stdout,
                self._stdout,
                "stdout",
                self.readyReadStandardOutput,
            ),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(
                self._process.stderr,
                self._stderr,
                "stderr",
                self.readyReadStandardError,
            ),
            daemon=True,
        )
        self._reader_threads = [stdout_thread, stderr_thread]
        stdout_thread.start()
        stderr_thread.start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _read_stream(
        self, stream: Any, target: bytearray, stream_name: str, signal: Any
    ) -> None:
        if stream is None:
            return
        for chunk in iter(stream.readline, b""):
            with self._lock:
                target.extend(chunk)
                overflow = max(0, len(target) - self._max_output_bytes)
                if overflow:
                    del target[:overflow]
                    self._dropped_output_bytes[stream_name] += overflow
            signal.emit()
        stream.close()

    def _wait(self) -> None:
        process = self._process
        if process is None:
            return
        code = process.wait()
        for thread in self._reader_threads:
            thread.join(timeout=2)
        exit_status = (
            QProcess.ExitStatus.NormalExit
            if code >= 0
            else QProcess.ExitStatus.CrashExit
        )
        self.finished.emit(code, exit_status)

    def readAllStandardOutput(self) -> bytes:
        with self._lock:
            data = bytes(self._stdout)
            self._stdout.clear()
        return data

    def readAllStandardError(self) -> bytes:
        with self._lock:
            data = bytes(self._stderr)
            self._stderr.clear()
        return data

    def processId(self) -> int:
        return int(self._process.pid) if self._process else 0

    def state(self) -> QProcess.ProcessState:
        if self._process is None or self._process.poll() is not None:
            return QProcess.ProcessState.NotRunning
        return QProcess.ProcessState.Running

    def errorString(self) -> str:
        return self._error

    def droppedOutputBytes(self) -> dict[str, int]:
        with self._lock:
            return dict(self._dropped_output_bytes)

    def kill(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            root = psutil.Process(process.pid)
            descendants = root.children(recursive=True)
            for child in reversed(descendants):
                child.kill()
            root.kill()
        except (psutil.Error, OSError):
            process.kill()


def create_background_process(parent: QObject) -> QProcess | HiddenProcess:
    return HiddenProcess(parent) if os.name == "nt" else QProcess(parent)


class LocalApiServer(QObject):
    def __init__(
        self,
        control_handler: Callable[[dict[str, Any]], Any],
        status_handler: Callable[[], dict[str, Any]],
        log_handler: Callable[[str, str], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.control_handler = control_handler
        self.status_handler = status_handler
        self.log_handler = log_handler
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept_connections)
        self.buffers: dict[Any, bytearray] = {}
        self._token = ""
        self._port = 0
        self._error = ""
        self.request_count = 0
        self.last_request: dict[str, Any] = {}

    def start(self, port: int) -> bool:
        self.stop()
        selected_port = max(0, min(65_535, int(port)))
        if not self.server.listen(QHostAddress("127.0.0.1"), selected_port):
            self._error = self.server.errorString()
            return False
        self._port = int(self.server.serverPort())
        self._token = generate_local_api_token()
        self._error = ""
        return True

    def stop(self) -> None:
        for socket in list(self.buffers):
            socket.disconnectFromHost()
        self.buffers.clear()
        if self.server.isListening():
            self.server.close()
        self._token = ""
        self._port = 0
        self._error = ""

    def rotate_token(self) -> str:
        if not self.server.isListening():
            raise RuntimeError("로컬 HTTP API가 실행 중이 아닙니다.")
        self._token = generate_local_api_token()
        return self._token

    def is_running(self) -> bool:
        return bool(self.server.isListening())

    def port(self) -> int:
        return self._port

    def token(self) -> str:
        return self._token

    def error(self) -> str:
        return self._error

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.buffers[socket] = bytearray()
            socket.readyRead.connect(lambda selected=socket: self._read_request(selected))
            socket.disconnected.connect(
                lambda selected=socket: self._discard_socket(selected)
            )

    def _discard_socket(self, socket: Any) -> None:
        self.buffers.pop(socket, None)
        socket.deleteLater()

    def _read_request(self, socket: Any) -> None:
        buffer = self.buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > LOCAL_API_MAX_REQUEST_BYTES + 16 * 1024:
            self._send_json(
                socket,
                413,
                {"ok": False, "errorCode": "request_too_large", "error": "요청이 너무 큽니다."},
            )
            return
        header_end = buffer.find(b"\r\n\r\n")
        if header_end < 0:
            return
        if header_end > 16 * 1024:
            self._send_json(
                socket,
                431,
                {"ok": False, "errorCode": "headers_too_large", "error": "요청 헤더가 너무 큽니다."},
            )
            return
        try:
            header_lines = bytes(buffer[:header_end]).decode("iso-8859-1").split("\r\n")
            method, target, _version = header_lines[0].split(" ", 2)
            headers: dict[str, str] = {}
            for line in header_lines[1:]:
                key, separator, value = line.partition(":")
                if not separator:
                    raise ValueError("잘못된 HTTP 헤더입니다.")
                headers[key.strip()] = value.strip()
            normalized_headers = {
                key.casefold(): value for key, value in headers.items()
            }
            if normalized_headers.get("transfer-encoding", "").casefold() not in {
                "",
                "identity",
            }:
                raise ValueError("chunked 요청 본문은 지원하지 않습니다.")
            content_length = int(normalized_headers.get("content-length", "0") or 0)
            if content_length < 0 or content_length > LOCAL_API_MAX_REQUEST_BYTES:
                raise OverflowError("요청 본문이 너무 큽니다.")
        except OverflowError as error:
            self._send_json(
                socket,
                413,
                {"ok": False, "errorCode": "request_too_large", "error": str(error)},
            )
            return
        except (ValueError, IndexError) as error:
            self._send_json(
                socket,
                400,
                {"ok": False, "errorCode": "invalid_http", "error": str(error)},
            )
            return
        body_start = header_end + 4
        if len(buffer) < body_start + content_length:
            return
        body = bytes(buffer[body_start : body_start + content_length])
        plan = local_api_request_plan(method, target, headers, body, self._token)
        if not plan.get("ok"):
            self._record_request(method, target, int(plan["statusCode"]))
            self._send_json(socket, int(plan["statusCode"]), plan)
            return
        try:
            if plan.get("route") == "health":
                result: Any = {
                    "service": "tokiDownloader",
                    "api": self.status_handler(),
                }
            else:
                request = dict(plan.get("request") or {})
                result = self.control_handler(request)
                if request.get("action") == "status" and isinstance(result, dict):
                    result = dict(result)
                    result.pop("jobs", None)
                    result["jobsOmitted"] = True
                    result["jobsEndpoint"] = "/v1/jobs"
            response = {"ok": True, "result": result}
            status_code = 200
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            response = {
                "ok": False,
                "errorCode": "control_error",
                "error": str(error),
            }
            status_code = 400
        self._record_request(method, target, status_code)
        self._send_json(socket, status_code, response)

    def _record_request(self, method: str, target: str, status_code: int) -> None:
        self.request_count += 1
        self.last_request = {
            "method": str(method).upper(),
            "path": urlsplit(str(target)).path,
            "statusCode": int(status_code),
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if self.log_handler:
            self.log_handler(
                f"로컬 API {self.last_request['method']} {self.last_request['path']} -> {status_code}",
                "INFO" if status_code < 400 else "WARNING",
            )

    def _send_json(self, socket: Any, status_code: int, payload: dict[str, Any]) -> None:
        reasons = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            431: "Request Header Fields Too Large",
            500: "Internal Server Error",
        }
        try:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        except (TypeError, ValueError) as error:
            status_code = 500
            body = json.dumps(
                {"ok": False, "errorCode": "serialization_error", "error": str(error)},
                ensure_ascii=False,
            ).encode("utf-8")
        header = (
            f"HTTP/1.1 {status_code} {reasons.get(status_code, 'Error')}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        socket.write(header + body)
        socket.flush()
        socket.disconnectFromHost()


class JobListModel(QAbstractListModel):
    JobRole = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[DownloadJob] = []
        self.row_by_key: dict[str, int] = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        job = self.rows[index.row()]
        if role == self.JobRole:
            return job
        if role == int(Qt.ItemDataRole.DisplayRole):
            return job.title
        if role == int(Qt.ItemDataRole.SizeHintRole):
            return QSize(100, 92)
        return None

    def job_at(self, row: int) -> DownloadJob | None:
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def replace_jobs(self, jobs: list[DownloadJob]) -> None:
        self.beginResetModel()
        self.rows = list(jobs)
        self.row_by_key = {job.work_key: row for row, job in enumerate(self.rows)}
        self.endResetModel()

    def upsert_job(self, job: DownloadJob) -> bool:
        existing_row = self.row_by_key.get(job.work_key)
        replaced = existing_row is not None
        if existing_row is not None:
            self.beginRemoveRows(QModelIndex(), existing_row, existing_row)
            self.rows.pop(existing_row)
            self.endRemoveRows()
        self.beginInsertRows(QModelIndex(), 0, 0)
        self.rows.insert(0, job)
        self.endInsertRows()
        self._rebuild_positions()
        return replaced

    def append_jobs(self, jobs: list[DownloadJob]) -> None:
        if not jobs:
            return
        start = len(self.rows)
        self.beginInsertRows(QModelIndex(), start, start + len(jobs) - 1)
        self.rows.extend(jobs)
        self.endInsertRows()
        for row in range(start, len(self.rows)):
            self.row_by_key[self.rows[row].work_key] = row

    def trim_to_limit(self, limit: int) -> list[DownloadJob]:
        safe_limit = max(1, int(limit))
        if len(self.rows) <= safe_limit:
            return []
        first = safe_limit
        last = len(self.rows) - 1
        self.beginRemoveRows(QModelIndex(), first, last)
        removed = self.rows[first:]
        del self.rows[first:]
        self.endRemoveRows()
        self._rebuild_positions()
        return removed

    def remove_work_key(self, work_key: str) -> bool:
        row = self.row_by_key.get(work_key)
        if row is None:
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        self.rows.pop(row)
        self.endRemoveRows()
        self._rebuild_positions()
        return True

    def contains_work_key(self, work_key: str) -> bool:
        return work_key in self.row_by_key

    def update_job(self, job: DownloadJob) -> None:
        row = self.row_by_key.get(job.work_key)
        if row is None:
            return
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [self.JobRole, int(Qt.ItemDataRole.DisplayRole)])

    def _rebuild_positions(self) -> None:
        self.row_by_key = {job.work_key: row for row, job in enumerate(self.rows)}


class JobItemDelegate(QStyledItemDelegate):
    def __init__(
        self,
        parent: QWidget | None = None,
        density: str = "comfortable",
        theme: str = "light",
    ) -> None:
        super().__init__(parent)
        self.cover_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.cache_limit = 128
        self.density = density
        self.theme = theme
        self.view_mode = "list"
        self.thumbnails_visible = True
        self.thumbnail_size = "medium"

    def set_density(self, density: str) -> None:
        self.density = density

    def set_theme(self, theme: str) -> None:
        self.theme = theme

    def set_view_preferences(
        self, view_mode: str, thumbnails_visible: bool, thumbnail_size: str
    ) -> None:
        self.view_mode = view_mode
        self.thumbnails_visible = thumbnails_visible
        self.thumbnail_size = thumbnail_size

    def _thumbnail_dimensions(self) -> tuple[int, int]:
        return {
            "small": (76, 100),
            "large": (130, 170),
        }.get(self.thumbnail_size, (100, 130))

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if self.view_mode == "icon":
            width, height = self._thumbnail_dimensions()
            return QSize(width + 36, height + 20)
        view = self.parent()
        width = option.rect.width()
        if isinstance(view, QListView):
            width = max(100, view.viewport().width() - (view.spacing() * 2) - 2)
        return QSize(width, 66 if self.density == "compact" else 92)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        job = index.data(JobListModel.JobRole)
        if not isinstance(job, DownloadJob):
            return

        if self.view_mode == "icon":
            self._paint_icon(painter, option, job)
            return

        painter.save()
        dark = self.theme == "dark"
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        border_color = "#46505d" if dark else "#d8dde5"
        selected_border = "#5f9ee8" if dark else "#9ebfe7"
        card_color = "#26374b" if selected and dark else (
            "#dcecff" if selected else ("#252a31" if dark else "#ffffff")
        )
        surface_color = "#303741" if dark else "#eef1f4"
        text_color = "#edf2f7" if dark else "#20262e"
        detail_color = "#aeb9c7" if dark else "#667282"
        card = option.rect.adjusted(4, 3, -4, -3)
        painter.setPen(QPen(QColor(selected_border if selected else border_color), 1))
        painter.setBrush(QColor(card_color))
        painter.drawRoundedRect(card, 5, 5)
        if job.tag_color and job.tag_color in TAG_COLORS:
            tag_rect = QRect(card.left(), card.top() + 5, 5, card.height() - 10)
            painter.fillRect(tag_rect, QColor(TAG_COLORS[job.tag_color]))

        compact = self.density == "compact"
        show_cover = not compact and self.thumbnails_visible
        if not show_cover:
            body_x = card.left() + 10
        else:
            cover_rect = card.adjusted(9, 8, 0, -8)
            cover_rect.setWidth(52)
            painter.setPen(QPen(QColor(border_color), 1))
            painter.setBrush(QColor(surface_color))
            painter.drawRoundedRect(cover_rect, 4, 4)
            cover = self._cover(job.cover_path, 50, 66)
            if cover:
                x = cover_rect.x() + (cover_rect.width() - cover.width()) // 2
                y = cover_rect.y() + (cover_rect.height() - cover.height()) // 2
                painter.drawPixmap(x, y, cover)
            else:
                painter.setPen(QColor(detail_color))
                painter.drawText(cover_rect, Qt.AlignmentFlag.AlignCenter, "표지")
            body_x = cover_rect.right() + 11
        state_rect = card.adjusted(body_x - card.left(), 9, 0, 0)
        state_rect.setWidth(82)
        state_rect.setHeight(23)
        state_colors = {
            "실행 중": "#1a73e8",
            "일시정지": "#8856c6",
            "재시도 대기": "#cf7a18",
            "완료": "#3b7d44",
            "오류": "#d13b32",
            "중지됨": "#cf7a18",
            "인증 필요": "#b33a7a",
        }
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(state_colors.get(job.state, "#7b8794")))
        painter.drawRoundedRect(state_rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        state_font = QFont(option.font)
        state_font.setBold(True)
        painter.setFont(state_font)
        painter.drawText(state_rect, Qt.AlignmentFlag.AlignCenter, job.state)

        title_rect = card.adjusted(state_rect.right() - card.left() + 8, 7, -10, 0)
        title_rect.setHeight(27)
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(text_color))
        display_title = f"★ {job.title}" if job.pinned else job.title
        title = painter.fontMetrics().elidedText(
            display_title, Qt.TextElideMode.ElideRight, max(20, title_rect.width())
        )
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter, title)

        details: list[str] = []
        if job.state == "대기" and job.queue_position:
            details.append(f"대기열 {job.queue_position}번")
        if job.episode_total:
            details.append(f"회차 {job.episode_index}/{job.episode_total}")
        if job.episode_number:
            details.append(f"현재 {job.episode_number}화")
        if job.image_total:
            details.append(f"이미지 {job.image_current}/{job.image_total}")
        if job.error_category:
            details.append(f"분류 {error_category_label(job.error_category)}")
        if job.attempt_count:
            details.append(f"시도 {job.attempt_count}/{job.retry_limit + 1}")
        if compact:
            details.append(f"진행 {max(0, min(100, job.progress))}%")
        if not details:
            details.append(job.url)
        detail_text = " · ".join(details)
        detail_rect = card.adjusted(body_x - card.left(), 35, -10, 0)
        detail_rect.setHeight(20)
        painter.setFont(option.font)
        painter.setPen(QColor(detail_color))
        detail_text = painter.fontMetrics().elidedText(
            detail_text, Qt.TextElideMode.ElideRight, max(20, detail_rect.width())
        )
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter, detail_text)

        if compact:
            painter.restore()
            return
        progress_rect = card.adjusted(body_x - card.left(), 60, -10, -9)
        painter.setPen(QPen(QColor(border_color), 1))
        painter.setBrush(QColor(surface_color))
        painter.drawRect(progress_rect)
        progress = max(0, min(100, job.progress))
        chunk = progress_rect.adjusted(1, 1, -1, -1)
        chunk.setWidth(int(chunk.width() * progress / 100))
        painter.fillRect(chunk, QColor("#2f7de1"))
        painter.setPen(QColor(text_color))
        painter.drawText(progress_rect, Qt.AlignmentFlag.AlignCenter, f"{progress}%")
        painter.restore()

    def _paint_icon(
        self, painter: QPainter, option: QStyleOptionViewItem, job: DownloadJob
    ) -> None:
        painter.save()
        dark = self.theme == "dark"
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        border = QColor("#5f9ee8" if selected else ("#46505d" if dark else "#d8dde5"))
        surface = QColor("#26374b" if selected and dark else ("#252a31" if dark else "#ffffff"))
        text = QColor("#edf2f7" if dark else "#20262e")
        muted = QColor("#aeb9c7" if dark else "#667282")
        card = option.rect.adjusted(4, 4, -4, -4)
        painter.setPen(QPen(border, 1))
        painter.setBrush(surface)
        painter.drawRoundedRect(card, 6, 6)

        thumb_width, thumb_height = self._thumbnail_dimensions()
        cover_rect = QRect(
            card.center().x() - thumb_width // 2,
            card.top() + 10,
            thumb_width,
            thumb_height,
        )
        if self.thumbnails_visible:
            cover = self._cover(job.cover_path, thumb_width, thumb_height)
            if cover:
                painter.drawPixmap(
                    cover_rect.x() + (cover_rect.width() - cover.width()) // 2,
                    cover_rect.y() + (cover_rect.height() - cover.height()) // 2,
                    cover,
                )
            else:
                painter.setPen(muted)
                painter.drawText(cover_rect, Qt.AlignmentFlag.AlignCenter, "표지 없음")
        else:
            painter.setPen(muted)
            painter.drawText(cover_rect, Qt.AlignmentFlag.AlignCenter, "썸네일 숨김")

        state_rect = QRect(cover_rect.left() + 5, cover_rect.top() + 5, 70, 22)
        state_colors = {
            "실행 중": "#1a73e8",
            "일시정지": "#8856c6",
            "재시도 대기": "#cf7a18",
            "완료": "#3b7d44",
            "오류": "#d13b32",
            "중지됨": "#cf7a18",
            "인증 필요": "#b33a7a",
        }
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(state_colors.get(job.state, "#7b8794")))
        painter.drawRoundedRect(state_rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(state_rect, Qt.AlignmentFlag.AlignCenter, job.state)

        title_rect = QRect(cover_rect.left(), cover_rect.bottom() - 43, cover_rect.width(), 43)
        painter.fillRect(title_rect, QColor(0, 0, 0, 170))
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff") if self.thumbnails_visible else text)
        title = f"★ {job.title}" if job.pinned else job.title
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            painter.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideRight, max(20, title_rect.width() * 2)
            ),
        )
        painter.restore()

    def _cover(self, cover_path: str, width: int, height: int) -> QPixmap | None:
        if not cover_path:
            return None
        try:
            disk_cache_path = thumbnail_cache_path(
                cover_path, width=width, height=height
            )
        except OSError:
            return None
        cache_key = str(disk_cache_path)
        cached = self.cover_cache.get(cache_key)
        if cached is not None:
            self.cover_cache.move_to_end(cache_key)
            return cached
        source = QPixmap(str(disk_cache_path)) if disk_cache_path.is_file() else QPixmap()
        if not source.isNull():
            try:
                os.utime(disk_cache_path, None)
            except OSError:
                pass
        else:
            if disk_cache_path.is_file():
                try:
                    disk_cache_path.unlink()
                except OSError:
                    pass
            source = QPixmap(cover_path)
        if source.isNull():
            return None
        scaled = source.scaled(
            QSize(width, height),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not disk_cache_path.is_file():
            try:
                disk_cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = disk_cache_path.with_suffix(".png.tmp")
                if scaled.save(str(temporary), "PNG"):
                    os.replace(temporary, disk_cache_path)
            except OSError:
                pass
        self.cover_cache[cache_key] = scaled
        if len(self.cover_cache) > self.cache_limit:
            self.cover_cache.popitem(last=False)
        return scaled


class RunLogDialog(QDialog):
    def __init__(self, owner: "MainWindow", run: DownloadRun) -> None:
        super().__init__(owner)
        self.owner = owner
        self.run = run
        self.setWindowTitle(f"실행 상세 로그 - {run.run_id}")
        self.setMinimumSize(760, 480)
        self.resize(900, 620)
        root = QVBoxLayout(self)
        summary = QLabel(
            f"실행 ID: {run.run_id}  |  상태: {run.state}  |  "
            f"시작: {run.started_at or '-'}  |  종료: {run.finished_at or '-'}"
        )
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(summary)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(10000)
        root.addWidget(self.log_edit, 1)
        actions = QHBoxLayout()
        refresh_button = QPushButton("로그 새로고침")
        refresh_button.clicked.connect(self.refresh)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        actions.addWidget(refresh_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        root.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        lines = read_run_log(self.run.run_id, 10000)
        self.log_edit.setPlainText(
            "\n".join(lines) if lines else "이 실행에 대해 보존된 로그가 없습니다."
        )
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class ShortcutHelpDialog(QDialog):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("키보드 단축키 편집")
        self.resize(880, 620)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "동작별 단축키를 편집하거나 비활성화할 수 있습니다. 세미콜론으로 최대 4개를 구분하며 "
            "충돌·단일 문자·종료 키는 저장 전에 차단합니다."
        )
        intro.setWordWrap(True)
        intro.setObjectName("mutedLabel")
        layout.addWidget(intro)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("키", "동작", "대응 CLI"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        editor = QHBoxLayout()
        editor.addWidget(QLabel("선택 동작 키"))
        self.keys_edit = QLineEdit()
        self.keys_edit.setPlaceholderText("예: Ctrl+Alt+F; F9")
        self.keys_edit.returnPressed.connect(self._apply_selected)
        editor.addWidget(self.keys_edit, 1)
        apply_button = QPushButton("적용")
        apply_button.setToolTip("CLI: shortcuts --set ACTION --keys KEYS --json")
        apply_button.clicked.connect(self._apply_selected)
        disable_button = QPushButton("비활성화")
        disable_button.setToolTip("CLI: shortcuts --disable ACTION --json")
        disable_button.clicked.connect(self._disable_selected)
        default_button = QPushButton("기본값")
        default_button.setToolTip("CLI: shortcuts --reset ACTION --json")
        default_button.clicked.connect(self._reset_selected)
        editor.addWidget(apply_button)
        editor.addWidget(disable_button)
        editor.addWidget(default_button)
        layout.addLayout(editor)

        file_actions = QHBoxLayout()
        import_button = QPushButton("가져오기...")
        import_button.setToolTip("CLI: shortcuts --import PATH --execute --yes --json")
        import_button.clicked.connect(self._import_file)
        export_button = QPushButton("내보내기...")
        export_button.setToolTip("CLI: shortcuts --export PATH --json")
        export_button.clicked.connect(self._export_file)
        reset_all_button = QPushButton("전체 기본값...")
        reset_all_button.setToolTip("CLI: shortcuts --reset-all --json")
        reset_all_button.clicked.connect(self._reset_all)
        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedLabel")
        file_actions.addWidget(import_button)
        file_actions.addWidget(export_button)
        file_actions.addWidget(reset_all_button)
        file_actions.addWidget(self.status_label, 1)
        layout.addLayout(file_actions)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.refresh()

    def selected_action_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 1)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def refresh(self, selected_action: str = "") -> None:
        catalog = keyboard_shortcut_catalog(self.owner.config)
        selected_action = selected_action or self.selected_action_id()
        self.table.setRowCount(len(catalog))
        selected_row = 0
        for row, item in enumerate(catalog):
            keys = "; ".join(item["keys"]) if item["keys"] else "사용 안 함"
            key_item = QTableWidgetItem(keys)
            if item["overridden"]:
                key_item.setToolTip(
                    "사용자 지정" if item["enabled"] else "사용자가 비활성화함"
                )
            label_item = QTableWidgetItem(str(item["label"]))
            label_item.setData(Qt.ItemDataRole.UserRole, str(item["id"]))
            cli_item = QTableWidgetItem(str(item["cli"]))
            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, label_item)
            self.table.setItem(row, 2, cli_item)
            if item["id"] == selected_action:
                selected_row = row
        if self.table.rowCount():
            self.table.selectRow(selected_row)
        snapshot = shortcut_settings_snapshot(self.owner.config)
        self.status_label.setText(
            f"사용자 지정 {snapshot['overrideCount']}개 · 비활성 {snapshot['disabledCount']}개"
        )

    def _selection_changed(self) -> None:
        action_id = self.selected_action_id()
        if not action_id:
            return
        item = next(
            item
            for item in keyboard_shortcut_catalog(self.owner.config)
            if item["id"] == action_id
        )
        self.keys_edit.setText("; ".join(item["keys"]))

    def _overrides(self) -> dict[str, list[str]]:
        return {
            key: list(value)
            for key, value in self.owner.config.get("shortcutOverrides", {}).items()
        }

    def _apply_overrides(self, overrides: dict[str, list[str]], action_id: str = "") -> None:
        try:
            self.owner.apply_shortcut_overrides(overrides)
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "단축키를 저장할 수 없음", str(error))
            return
        self.refresh(action_id)

    def _apply_selected(self) -> None:
        action_id = self.selected_action_id()
        if not action_id:
            return
        overrides = self._overrides()
        overrides[action_id] = [
            part.strip() for part in self.keys_edit.text().split(";") if part.strip()
        ]
        self._apply_overrides(overrides, action_id)

    def _disable_selected(self) -> None:
        action_id = self.selected_action_id()
        if not action_id:
            return
        overrides = self._overrides()
        overrides[action_id] = []
        self._apply_overrides(overrides, action_id)

    def _reset_selected(self) -> None:
        action_id = self.selected_action_id()
        if not action_id:
            return
        overrides = self._overrides()
        overrides.pop(action_id, None)
        self._apply_overrides(overrides, action_id)

    def _reset_all(self) -> None:
        if QMessageBox.question(
            self,
            "전체 기본 단축키 복원",
            "모든 사용자 지정 단축키와 비활성화를 지우고 기본값으로 복원할까요?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._apply_overrides({})

    def _export_file(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self, "단축키 내보내기", "toki-shortcuts.json", "JSON (*.json)"
        )
        if not selected:
            return
        try:
            result = export_shortcut_settings(Path(selected))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "단축키를 내보낼 수 없음", str(error))
            return
        self.status_label.setText(f"내보냄: {result['path']}")

    def _import_file(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "단축키 가져오기", "", "JSON (*.json)"
        )
        if not selected:
            return
        try:
            plan = shortcut_import_plan(Path(selected))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "단축키 파일을 읽을 수 없음", str(error))
            return
        if QMessageBox.question(
            self,
            "단축키 가져오기",
            f"현재 설정 중 {plan['changedCount']}개 동작이 바뀝니다. 적용할까요?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._apply_overrides(plan["shortcutOverrides"])

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "selectedAction": self.selected_action_id(),
            **{
                key: value
                for key, value in shortcut_settings_snapshot(self.owner.config).items()
                if key in {"count", "overrideCount", "disabledCount"}
            },
        }


class DependencyDiagnosticsDialog(QDialog):
    def __init__(self, report: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("설치 및 선택 기능 진단")
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        required = report.get("required") or {}
        optional = report.get("optional") or {}
        schemas = report.get("schemas") or {}
        config_schema = schemas.get("config") or {}
        database_schema = schemas.get("database") or {}
        summary = QLabel(
            f"필수 {int(required.get('passed') or 0)}/{int(required.get('total') or 0)} · "
            f"선택 {int(optional.get('available') or 0)}/{int(optional.get('total') or 0)} · "
            f"설정 v{int(config_schema.get('version') or 0)}/"
            f"{int(config_schema.get('currentVersion') or 0)} · DB v"
            f"{int(database_schema.get('version') or 0)}/"
            f"{int(database_schema.get('currentVersion') or 0)} · "
            f"{'실행 준비 완료' if report.get('ok') else '필수 점검 필요'}"
        )
        summary.setObjectName("mutedLabel")
        layout.addWidget(summary)
        checks = list(report.get("checks") or [])
        table = QTableWidget(len(checks), 4)
        table.setHorizontalHeaderLabels(("구분", "항목", "상태·버전", "경로"))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        labels = {"required": "필수", "optional": "선택", "setup": "설치 도구"}
        for row, item in enumerate(checks):
            values = (
                labels.get(str(item.get("kind")), str(item.get("kind") or "")),
                str(item.get("name") or ""),
                (
                    f"정상 {item.get('version')}".strip()
                    if item.get("available")
                    else "설치되지 않음"
                ),
                str(item.get("path") or ""),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)
        note = QLabel(
            "Pillow는 이미지 변환, FFmpeg·yt-dlp는 향후 동영상 공급자, "
            "PyInstaller는 배포 빌드에만 필요합니다."
        )
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)


class PerformanceDiagnosticsDialog(QDialog):
    def __init__(self, report: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("목록 데이터베이스 성능 진단")
        self.resize(820, 540)
        layout = QVBoxLayout(self)

        query_plans = list(report.get("queries") or [])
        passed = sum(1 for plan in query_plans if plan.get("ok"))
        summary = QLabel(
            f"작품 {int(report.get('jobCount') or 0):,}개 · 실행 이력 "
            f"{int(report.get('runCount') or 0):,}개 · 쿼리 계획 {passed}/{len(query_plans)} 통과 · "
            f"진단 {float(report.get('elapsedMs') or 0):.1f}ms"
        )
        summary.setObjectName("mutedLabel")
        layout.addWidget(summary)

        table = QTableWidget(len(query_plans), 5)
        table.setHorizontalHeaderLabels(("조회", "상태 필터", "인덱스", "임시 정렬", "결과"))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row, plan in enumerate(query_plans):
            values = (
                str(plan.get("sort") or ""),
                "사용" if plan.get("stateFiltered") else "없음",
                "사용" if plan.get("usesIndex") else "미사용",
                "발생" if plan.get("temporarySort") else "없음",
                "통과" if plan.get("ok") else "점검 필요",
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)

        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setMaximumHeight(125)
        details.setPlainText(
            "\n".join(
                f"{plan.get('name')}: {' | '.join(plan.get('details') or [])}"
                for plan in query_plans
            )
        )
        layout.addWidget(details)

        benchmark_row = QHBoxLayout()
        self.benchmark_status_label = QLabel("합성 벤치마크: 실행 전")
        self.benchmark_status_label.setObjectName("mutedLabel")
        benchmark_row.addWidget(self.benchmark_status_label, 1)
        self.benchmark_button = QPushButton("100~100,000개 벤치마크 실행")
        benchmark_row.addWidget(self.benchmark_button)
        layout.addLayout(benchmark_row)
        stability_row = QHBoxLayout()
        self.stability_status_label = QLabel("안정성·복구: 실행 전")
        self.stability_status_label.setObjectName("mutedLabel")
        stability_row.addWidget(self.stability_status_label, 1)
        self.stability_button = QPushButton("10,000개 장시간·강제 종료 복구 검증")
        stability_row.addWidget(self.stability_button)
        layout.addLayout(stability_row)
        if parent is not None and hasattr(parent, "start_performance_benchmark"):
            self.benchmark_button.clicked.connect(
                lambda: parent.start_performance_benchmark()
            )
            self.update_benchmark_status(parent.performance_benchmark_snapshot())
            self.stability_button.clicked.connect(lambda: parent.start_stability_test())
            self.update_stability_status(parent.stability_test_snapshot())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def update_benchmark_status(self, snapshot: dict[str, Any]) -> None:
        running = bool(snapshot.get("running"))
        last = snapshot.get("last") if isinstance(snapshot.get("last"), dict) else None
        self.benchmark_button.setEnabled(not running)
        if running:
            self.benchmark_status_label.setText("합성 벤치마크: 실행 중...")
        elif last:
            results = list(last.get("results") or [])
            largest = results[-1] if results else {}
            self.benchmark_status_label.setText(
                f"최근 결과: {'통과' if last.get('ok') else '실패'} · "
                f"{int(largest.get('size') or 0):,}개 첫 화면 "
                f"{float(largest.get('firstPageMs') or 0):.1f}ms"
            )
        else:
            self.benchmark_status_label.setText("합성 벤치마크: 실행 전")

    def update_stability_status(self, snapshot: dict[str, Any]) -> None:
        running = bool(snapshot.get("running"))
        last = snapshot.get("last") if isinstance(snapshot.get("last"), dict) else None
        self.stability_button.setEnabled(not running)
        if running:
            self.stability_status_label.setText("안정성·복구: 격리 환경에서 실행 중...")
        elif last:
            forced = last.get("forcedTermination") or {}
            self.stability_status_label.setText(
                f"최근 결과: {'통과' if last.get('ok') else '실패'} · "
                f"{int(last.get('records') or 0):,}개/{int(last.get('cycles') or 0):,}회 · "
                f"복구 {'통과' if forced.get('recoveryPassed') else '실패'}"
            )
        else:
            self.stability_status_label.setText("안정성·복구: 실행 전")


class WorkDetailDialog(QDialog):
    page_size = 100

    def __init__(self, owner: "MainWindow", job: DownloadJob) -> None:
        super().__init__(owner)
        self.owner = owner
        self.job = job
        self.offset = 0
        self.setWindowTitle("작품 정보 및 실행 이력")
        self.setMinimumSize(820, 620)
        self.resize(920, 700)

        root = QVBoxLayout(self)
        overview = QHBoxLayout()
        self.cover_label = QLabel("대표 이미지 없음")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(150, 205)
        self.cover_label.setObjectName("previewSurface")
        overview.addWidget(self.cover_label)

        metadata = QGridLayout()
        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 2)
        self.title_label.setFont(title_font)
        metadata.addWidget(self.title_label, 0, 0, 1, 2)
        self.metadata_labels: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(
            (
                ("author", "작가"),
                ("group", "그룹"),
                ("site", "사이트"),
                ("state", "현재 상태"),
                ("work_key", "작품 키"),
                ("output", "저장 폴더"),
                ("metadata", "메타데이터"),
            ),
            start=1,
        ):
            metadata.addWidget(QLabel(f"{label}:"), row, 0)
            value = QLabel()
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            self.metadata_labels[key] = value
            metadata.addWidget(value, row, 1)
        overview.addLayout(metadata, 1)
        root.addLayout(overview)

        action_row = QHBoxLayout()
        open_folder = QPushButton("다운로드 폴더 열기")
        open_folder.clicked.connect(lambda: owner.open_output_folder(self.job.job_id))
        open_source = QPushButton("원본 페이지 열기")
        open_source.clicked.connect(lambda: owner.open_job_source(self.job.job_id))
        open_cover = QPushButton("대표 이미지 원본 열기")
        open_cover.clicked.connect(lambda: owner.open_job_cover(self.job.job_id))
        refresh_metadata = QPushButton("메타데이터 새로고침")
        refresh_metadata.clicked.connect(
            lambda: owner.refresh_selected_metadata(self.job.job_id)
        )
        action_row.addWidget(open_folder)
        action_row.addWidget(open_source)
        action_row.addWidget(open_cover)
        action_row.addWidget(refresh_metadata)
        action_row.addStretch(1)
        root.addLayout(action_row)

        root.addWidget(QLabel("사용자 메모"))
        note_row = QHBoxLayout()
        self.note_edit = QPlainTextEdit()
        self.note_edit.setMaximumHeight(80)
        note_row.addWidget(self.note_edit, 1)
        save_note = QPushButton("메모 저장")
        save_note.clicked.connect(self._save_note)
        note_row.addWidget(save_note)
        root.addLayout(note_row)

        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("실행 이력"))
        history_header.addStretch(1)
        self.page_label = QLabel()
        history_header.addWidget(self.page_label)
        root.addLayout(history_header)

        columns = (
            "실행 시각", "종류", "상태", "요청 범위", "발견", "선택", "처리",
            "진행률", "시도", "PID",
        )
        self.run_table = QTableWidget(0, len(columns))
        self.run_table.setHorizontalHeaderLabels(columns)
        self.run_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.run_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.run_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.run_table.verticalHeader().setVisible(False)
        header = self.run_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.run_table, 1)

        self.run_detail_label = QLabel("실행을 선택하면 오류와 시작·종료 시각이 표시됩니다.")
        self.run_detail_label.setWordWrap(True)
        self.run_detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        run_detail_row = QHBoxLayout()
        run_detail_row.addWidget(self.run_detail_label, 1)
        self.open_run_log_button = QPushButton("선택 실행 로그 보기")
        self.open_run_log_button.setEnabled(False)
        self.open_run_log_button.clicked.connect(self._open_selected_run_log)
        run_detail_row.addWidget(self.open_run_log_button)
        root.addLayout(run_detail_row)
        self.run_table.itemSelectionChanged.connect(self._show_selected_run)
        self.run_table.itemDoubleClicked.connect(lambda _item: self._open_selected_run_log())

        paging = QHBoxLayout()
        self.previous_button = QPushButton("이전 100건")
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button = QPushButton("다음 100건")
        self.next_button.clicked.connect(self._next_page)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        paging.addWidget(self.previous_button)
        paging.addWidget(self.next_button)
        paging.addStretch(1)
        paging.addWidget(close_button)
        root.addLayout(paging)

        self.refresh()

    def refresh(self) -> None:
        current = self.owner.selected_job(self.job.job_id)
        if current:
            self.job = current
        job = self.job
        self.title_label.setText(job.title)
        self.metadata_labels["author"].setText(job.author or "-")
        self.metadata_labels["group"].setText(job.group or "-")
        self.metadata_labels["site"].setText(job.site or "-")
        self.metadata_labels["state"].setText(job.state)
        self.metadata_labels["work_key"].setText(job.work_key)
        self.metadata_labels["output"].setText(job.output_path or job.output_dir)
        self.metadata_labels["metadata"].setText(job.metadata_path or "-")
        self.note_edit.setPlainText(job.user_note)
        cover = QPixmap(job.cover_path) if job.cover_path else QPixmap()
        if not cover.isNull():
            self.cover_label.setPixmap(
                cover.scaled(
                    self.cover_label.size() - QSize(8, 8),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._load_runs()

    def _load_runs(self) -> None:
        result = self.owner.list_runs_snapshot(self.job.job_id, self.page_size, self.offset)
        runs = result["runs"]
        self.run_table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            requested = f"{run.get('requested_start') or '처음'} ~ {run.get('requested_last') or '끝'}"
            operation_label = {
                "metadata_refresh": "메타데이터",
                "download_new": "신규 검사",
                "download_full": "전체 재검사",
                "download_range": "범위 검사",
                "download": "다운로드",
            }.get(str(run.get("operation") or ""), "다운로드")
            values = (
                str(run.get("created_at") or "").replace("T", " "),
                operation_label,
                str(run.get("state") or ""),
                requested,
                str(run.get("discovered_episodes") or 0),
                str(run.get("selected_episodes") or 0),
                str(run.get("processed_episodes") or 0),
                f"{int(run.get('progress') or 0)}%",
                f"{int(run.get('attempt_count') or 0)}/{int(run.get('retry_limit') or 0) + 1}",
                str(run.get("process_pid") or "-"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, run)
                self.run_table.setItem(row, column, item)
        total = int(result["total"])
        first = self.offset + 1 if runs else 0
        last = self.offset + len(runs)
        self.page_label.setText(f"{first}-{last} / {total}건")
        self.previous_button.setEnabled(self.offset > 0)
        self.next_button.setEnabled(self.offset + len(runs) < total)

    def _previous_page(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self._load_runs()

    def _next_page(self) -> None:
        self.offset += self.page_size
        self._load_runs()

    def _show_selected_run(self) -> None:
        items = self.run_table.selectedItems()
        if not items:
            return
        run = items[0].data(Qt.ItemDataRole.UserRole) or {}
        detail = (
            f"실행 ID {run.get('run_id')} | 시작 {run.get('started_at') or '-'} | "
            f"종료 {run.get('finished_at') or '-'} | "
            f"시도 {int(run.get('attempt_count') or 0)}/"
            f"{int(run.get('retry_limit') or 0) + 1}"
        )
        if run.get("error"):
            category = error_category_label(run.get("error_category"))
            detail += f" | 오류 분류 {category}: {run['error']}"
        self.run_detail_label.setText(detail)
        self.open_run_log_button.setEnabled(True)

    def _open_selected_run_log(self) -> None:
        items = self.run_table.selectedItems()
        if not items:
            return
        run = items[0].data(Qt.ItemDataRole.UserRole) or {}
        self.owner.show_run_log(str(run.get("run_id") or ""))

    def _save_note(self) -> None:
        self.owner.set_job_note(self.job.job_id, self.note_edit.toPlainText())
        self.owner.statusBar().showMessage("작품 메모를 저장했습니다.", 2500)


class FileVerificationDialog(QDialog):
    def __init__(self, owner: "MainWindow", result: dict[str, Any]) -> None:
        super().__init__(owner)
        self.setWindowTitle("작품 파일 검사 결과")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        summary = result.get("summary") or {}
        state = "정상" if result.get("healthy") else "문제 발견"
        heading = QLabel(
            f"{state} · 회차 {summary.get('episodeFolders', 0)} · "
            f"이미지 {summary.get('images', 0)} · 문제 {summary.get('issueCount', 0)} · "
            f"{result.get('durationMs', 0)}ms"
        )
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        path_label = QLabel(str(result.get("outputPath") or ""))
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines = [
            f"메타데이터: {'정상' if (result.get('metadata') or {}).get('valid') else '없음/손상'}",
            f"완료 상태 파일: {'정상' if (result.get('state') or {}).get('valid') else '없음/손상'}",
            f"빈 회차: {summary.get('emptyEpisodes', 0)}",
            f"0바이트 이미지: {summary.get('zeroByteImages', 0)}",
            f"손상 이미지: {summary.get('invalidImages', 0)}",
            f"중복 회차: {summary.get('duplicateEpisodes', 0)}",
            f"누락 회차: {summary.get('missingEpisodes', 0)}",
            f"상태 미등록 회차: {summary.get('untrackedEpisodes', 0)}",
            "",
        ]
        for issue in result.get("issues") or []:
            target = f"\n  {issue.get('path')}" if issue.get("path") else ""
            lines.append(f"[{issue.get('kind')}] {issue.get('detail')}{target}")
        if summary.get("issuesTruncated"):
            lines.append("\n문제 목록이 제한되어 일부 항목은 표시하지 않았습니다.")
        if not result.get("issues"):
            lines.append("검사에서 발견된 문제가 없습니다.")
        details.setPlainText("\n".join(lines))
        layout.addWidget(details, 1)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)


class ImageLoadSignals(QObject):
    loaded = pyqtSignal(str, object, str)


class ImageLoadTask(QRunnable):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.signals = ImageLoadSignals()

    def run(self) -> None:
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        image = reader.read()
        error = reader.errorString() if image.isNull() else ""
        if not image.isNull() and (image.width() > 1400 or image.height() > 1000):
            image = image.scaled(
                QSize(1400, 1000),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.signals.loaded.emit(self.path, image, error)


class ServiceTaskSignals(QObject):
    finished = pyqtSignal(str, object, str)


class ServiceTask(QRunnable):
    def __init__(self, task_id: str, operation: Callable[[], dict[str, Any]]) -> None:
        super().__init__()
        self.task_id = task_id
        self.operation = operation
        self.signals = ServiceTaskSignals()

    def run(self) -> None:
        try:
            result = self.operation()
            self.signals.finished.emit(self.task_id, result, "")
        except Exception as error:  # Worker boundary: report service failures to the GUI.
            self.signals.finished.emit(self.task_id, {}, str(error))


class ImagePreviewDialog(QDialog):
    def __init__(self, owner: "MainWindow", result: dict[str, Any]) -> None:
        super().__init__(owner)
        self.owner = owner
        self.result = result
        self.current_path = ""
        self.setWindowTitle("회차 이미지 미리보기")
        self.resize(980, 720)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(str(result.get("title") or "작품")), 1)
        toolbar.addWidget(QLabel("회차"))
        self.episode_combo = QComboBox()
        for episode in result.get("availableEpisodes") or []:
            self.episode_combo.addItem(str(episode), int(episode))
        selected_index = self.episode_combo.findData(int(result.get("episode") or 0))
        if selected_index >= 0:
            self.episode_combo.setCurrentIndex(selected_index)
        toolbar.addWidget(self.episode_combo)
        layout.addLayout(toolbar)

        content = QHBoxLayout()
        self.image_list = QListWidget()
        self.image_list.setMinimumWidth(280)
        self.image_list.setObjectName("imageList")
        for image in result.get("images") or []:
            name = str(image["name"])
            short_match = re.search(r"(image\d+\.[a-zA-Z0-9]+)$", name)
            display_name = short_match.group(1) if short_match else name
            self.image_list.addItem(f"{int(image['index']) + 1}. {display_name}")
            item = self.image_list.item(self.image_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, image)
        content.addWidget(self.image_list)
        self.preview_label = QLabel("이미지를 선택해주세요.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(520, 480)
        self.preview_label.setObjectName("previewSurface")
        content.addWidget(self.preview_label, 1)
        layout.addLayout(content, 1)

        footer = QHBoxLayout()
        self.page_label = QLabel(
            f"이미지 {len(result.get('images') or [])} / 전체 {result.get('total', 0)}"
        )
        footer.addWidget(self.page_label, 1)
        open_button = QPushButton("원본 이미지 열기")
        open_button.clicked.connect(self._open_current)
        footer.addWidget(open_button)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.image_list.currentItemChanged.connect(self._selection_changed)
        self.episode_combo.currentIndexChanged.connect(self._episode_changed)
        if self.image_list.count():
            self.image_list.setCurrentRow(0)

    def _selection_changed(self, current: Any, _previous: Any) -> None:
        image = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not image:
            return
        self.current_path = str(image.get("path") or "")
        self.preview_label.setText("이미지 불러오는 중…")
        task = ImageLoadTask(self.current_path)
        task.signals.loaded.connect(self._image_loaded)
        self.owner.image_thread_pool.start(task)

    def _image_loaded(self, path: str, image: QImage, error: str) -> None:
        if path != self.current_path:
            return
        if image.isNull():
            self.preview_label.setText(f"이미지를 열 수 없습니다.\n{error}")
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(pixmap)

    def _episode_changed(self, _index: int) -> None:
        episode = self.episode_combo.currentData()
        if episode is None or int(episode) == int(self.result.get("episode") or 0):
            return
        self.owner.start_image_preview(self.result["jobId"], int(episode))

    def _open_current(self) -> None:
        if self.current_path:
            open_in_explorer(self.current_path)


class JobsSnapshotImportDialog(QDialog):
    def __init__(
        self, owner: "MainWindow", source_path: str, result: dict[str, Any]
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.source_path = source_path
        self.result = result
        self.setWindowTitle("작업 스냅샷 가져오기")
        self.resize(620, 390)
        layout = QVBoxLayout(self)
        self.heading = QLabel("작업 스냅샷 미리보기")
        self.heading.setObjectName("sectionTitle")
        layout.addWidget(self.heading)
        source_label = QLabel(f"파일: {source_path}")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        note = QLabel(
            "기존 작품과 실행 기록은 덮어쓰지 않습니다. 다운로드 폴더와 파일은 변경하지 않습니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.import_button.setText("가져오기")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(self._execute)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.update_result(result)

    def update_result(self, result: dict[str, Any]) -> None:
        self.result = result
        executed = bool(result.get("executed"))
        self.heading.setText("작업 스냅샷 가져오기 완료" if executed else "작업 스냅샷 미리보기")
        self.summary.setText(
            f"작품 {result.get('pendingJobs', 0)}개 · 실행 기록 {result.get('pendingRuns', 0)}개 "
            f"{'추가 완료' if executed else '추가 예정'}"
        )
        self.details.setPlainText(
            "\n".join(
                [
                    f"원본 작품: {result.get('sourceJobCount', 0)}",
                    f"원본 실행 기록: {result.get('sourceRunCount', 0)}",
                    f"기존 작품 건너뜀: {result.get('skippedExistingWorks', 0)}",
                    f"기존 실행 기록 건너뜀: {result.get('skippedExistingRuns', 0)}",
                    f"연결할 작품이 없는 실행 기록: {result.get('orphanRuns', 0)}",
                    f"충돌로 새 ID를 부여할 작품: {result.get('remappedJobIds', 0)}",
                    "다운로드 파일 변경: 없음",
                ]
            )
        )
        if executed:
            self.import_button.setEnabled(False)
            self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("닫기")

    def _execute(self) -> None:
        try:
            result = self.owner.execute_jobs_snapshot_import(self.source_path)
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "작업 스냅샷을 가져올 수 없음", str(error))
            return
        self.update_result(result)


class WorkGroupManagerDialog(QDialog):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("작품 그룹 관리")
        self.resize(580, 430)
        layout = QVBoxLayout(self)
        heading = QLabel("작품 정리 그룹")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        note = QLabel(
            "목록 정리용 그룹입니다. 작품의 작가·번역 그룹 메타데이터와 다운로드 폴더명은 바뀌지 않습니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["그룹 이름", "작품 수"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        editor = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("새 그룹 이름 또는 선택한 그룹의 새 이름")
        editor.addWidget(self.name_edit, 1)
        create_button = QPushButton("새 그룹")
        create_button.clicked.connect(self._create)
        editor.addWidget(create_button)
        self.rename_button = QPushButton("이름 변경")
        self.rename_button.clicked.connect(self._rename)
        editor.addWidget(self.rename_button)
        layout.addLayout(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def selected_group_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def refresh(self) -> None:
        groups = self.owner.list_groups_snapshot()["groups"]
        self.table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            name_item = QTableWidgetItem(str(group["name"]))
            name_item.setData(Qt.ItemDataRole.UserRole, str(group["groupId"]))
            count_item = QTableWidgetItem(str(group["memberCount"]))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, count_item)
        self.rename_button.setEnabled(bool(self.selected_group_id()))

    def _selection_changed(self) -> None:
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            self.name_edit.setText(self.table.item(row, 0).text())
        self.rename_button.setEnabled(bool(self.selected_group_id()))

    def _create(self) -> None:
        try:
            self.owner.create_work_group(self.name_edit.text())
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "그룹을 만들 수 없음", str(error))
            return
        self.name_edit.clear()
        self.refresh()

    def _rename(self) -> None:
        try:
            self.owner.rename_work_group(self.selected_group_id(), self.name_edit.text())
        except (ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "그룹 이름을 바꿀 수 없음", str(error))
            return
        self.refresh()


class ArchiveInspectionDialog(QDialog):
    def __init__(self, owner: "MainWindow", result: dict[str, Any]) -> None:
        super().__init__(owner)
        self.owner = owner
        self.result = result
        self.setWindowTitle("로컬 압축 작품 검사")
        self.resize(680, 500)
        layout = QVBoxLayout(self)
        heading = QLabel("압축 작품 검사 결과")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        path_label = QLabel(str(result.get("path") or ""))
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        state = "안전 경로" if result.get("healthy") else "확인 필요한 경로 발견"
        summary = QLabel(
            f"{str(result.get('format') or '').upper()} · {state} · "
            f"파일 {result.get('fileCount', 0)}개 · 이미지 {result.get('imageCount', 0)}개"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines = [
            f"압축 크기: {int(result.get('bytes') or 0):,} bytes",
            f"원본 합계: {int(result.get('totalUncompressedBytes') or 0):,} bytes",
            f"빈 파일: {result.get('emptyFileCount', 0)}",
            f"암호화 파일: {result.get('encryptedFileCount', 0)}",
            f"의심 경로: {result.get('suspiciousPathCount', 0)}",
            f"검사 모듈: {(result.get('dependency') or {}).get('name', '-')}",
            "압축 해제: 하지 않음",
            "파일 변경: 없음",
            f"연결 프로그램: {(result.get('viewer') or {}).get('viewerLabel', '-')}",
            "Windows 시스템 연결 변경: 없음",
        ]
        suspicious = result.get("suspiciousPaths") or []
        if suspicious:
            lines.extend(["", "[확인 필요한 경로]", *map(str, suspicious)])
        empty_files = result.get("emptyFiles") or []
        if empty_files:
            lines.extend(["", "[빈 파일]", *map(str, empty_files)])
        sample = result.get("sample") or []
        if sample:
            lines.extend(["", "[파일 예시]"])
            lines.extend(
                f"{item.get('name')} ({int(item.get('size') or 0):,} bytes)"
                for item in sample[:30]
            )
        details.setPlainText("\n".join(lines))
        layout.addWidget(details, 1)
        note = QLabel("읽기 전용 검사입니다. 압축 내용은 추출하지 않습니다.")
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        open_button = buttons.addButton(
            "연결 프로그램으로 열기...",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        open_button.setToolTip(
            "CLI: archive-viewer open --path PATH --execute --yes"
        )
        viewer = result.get("viewer") or {}
        open_button.setEnabled(bool(viewer.get("ok")))
        open_button.clicked.connect(
            lambda: owner.confirm_open_archive_viewer(str(result.get("path") or ""))
        )
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def state_snapshot(self) -> dict[str, Any]:
        viewer = self.result.get("viewer") or {}
        return {
            "open": self.isVisible(),
            "path": str(self.result.get("path") or ""),
            "fileCount": int(self.result.get("fileCount") or 0),
            "imageCount": int(self.result.get("imageCount") or 0),
            "viewer": {
                "mode": str(viewer.get("mode") or ""),
                "label": str(viewer.get("viewerLabel") or ""),
                "available": bool(viewer.get("ok")),
                "requiresConfirmation": bool(viewer.get("requiresConfirmation")),
                "changesSystemAssociation": bool(
                    viewer.get("changesSystemAssociation")
                ),
            },
        }


class RecoveryStatusDialog(QDialog):
    def __init__(self, owner: "MainWindow", result: dict[str, Any]) -> None:
        super().__init__(owner)
        self.owner = owner
        self.result = result
        self.setWindowTitle("불완전 작업 복구")
        self.resize(650, 430)
        layout = QVBoxLayout(self)
        self.heading = QLabel("불완전 작업 복구 미리보기")
        self.heading.setObjectName("sectionTitle")
        layout.addWidget(self.heading)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        note = QLabel(
            "복구는 DB의 상태만 중지됨으로 바꾸고 진행률과 다운로드 파일을 보존합니다. "
            "현재 실행·대기 작업이 있으면 수동 복구를 차단합니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        refresh_button = buttons.addButton(
            "다시 확인", QDialogButtonBox.ButtonRole.ActionRole
        )
        refresh_button.setToolTip("CLI: persistence recover --show-gui")
        refresh_button.clicked.connect(self.refresh)
        self.execute_button = buttons.addButton(
            "복구 실행...", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.execute_button.setToolTip(
            "CLI: persistence recover --execute --yes --json"
        )
        self.execute_button.clicked.connect(self._execute)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.set_result(result)

    def set_result(self, result: dict[str, Any]) -> None:
        self.result = result
        blocked = bool(result.get("blocked"))
        executed = bool(result.get("executed"))
        job_count = int(result.get("jobCount") or 0)
        run_count = int(result.get("runCount") or 0)
        self.heading.setText(
            "불완전 작업 복구 완료" if executed else "불완전 작업 복구 미리보기"
        )
        self.summary.setText(
            str(result.get("error") or "현재 작업이 있어 확인할 수 없습니다.")
            if blocked
            else f"작품 {job_count}개 · 실행 이력 {run_count}개 · "
            f"{'복구 완료' if executed else '변경 전 미리보기'}"
        )
        lines = [
            f"실행 여부: {'예' if executed else '아니요'}",
            "복구 상태: 중지됨",
            "진행률 보존: 예",
            "다운로드 파일 변경: 없음",
        ]
        if result.get("jobIds"):
            lines.extend(["", "[작품 ID]", *map(str, result["jobIds"][:100])])
        if result.get("runIds"):
            lines.extend(["", "[실행 ID]", *map(str, result["runIds"][:100])])
        self.details.setPlainText("\n".join(lines))
        self.execute_button.setEnabled(
            not blocked and not executed and bool(job_count or run_count)
        )

    def refresh(self) -> None:
        self.set_result(self.owner.recover_interrupted_records(execute=False))

    def _execute(self) -> None:
        self.set_result(self.owner.confirm_recover_interrupted_records())

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "executed": bool(self.result.get("executed")),
            "blocked": bool(self.result.get("blocked")),
            "jobCount": int(self.result.get("jobCount") or 0),
            "runCount": int(self.result.get("runCount") or 0),
        }


class DuplicateWorksDialog(QDialog):
    def __init__(self, result: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("중복 의심 작품 검사")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        heading = QLabel("중복 의심 작품")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        summary = QLabel(
            f"검사 {result.get('scannedWorks', 0)}개 · 중복 그룹 "
            f"{result.get('duplicateGroupCount', 0)}개 · 관련 작품 "
            f"{result.get('duplicateWorkCount', 0)}개"
        )
        layout.addWidget(summary)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        reason_labels = {
            "same_title_author": "제목과 작가가 같음",
            "same_output_path": "저장 폴더 경로가 같음",
        }
        lines: list[str] = []
        for index, group in enumerate(result.get("groups") or [], 1):
            lines.append(
                f"[{index}] {reason_labels.get(str(group.get('reason')), group.get('reason'))}"
            )
            for job in group.get("jobs") or []:
                lines.append(
                    f"  {job.get('jobId')} · {job.get('title')} · {job.get('author') or '-'}"
                )
                lines.append(f"    {job.get('workKey')} · {job.get('outputPath') or '-'}")
            lines.append("")
        if not lines:
            lines.append("중복으로 의심되는 작품 기록이 없습니다.")
        details.setPlainText("\n".join(lines))
        layout.addWidget(details, 1)
        note = QLabel(
            "읽기 전용 진단입니다. 작품 기록, 메타데이터와 다운로드 파일을 변경하지 않습니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DuplicateImagesDialog(QDialog):
    def __init__(self, result: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("중복 이미지 검사")
        self.resize(760, 540)
        layout = QVBoxLayout(self)
        heading = QLabel("중복 이미지 해시 검사")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        summary = QLabel(
            f"{result.get('title')} · {str(result.get('algorithm')).upper()} · "
            f"검사 {result.get('scannedImages', 0)}장 · 중복 그룹 "
            f"{result.get('duplicateGroupCount', 0)}개 · 관련 이미지 "
            f"{result.get('duplicateImageCount', 0)}장"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        pool = result.get("pool") or {}
        pool_label = QLabel(
            f"{pool.get('kind', '-')} 풀 {pool.get('workers', 0)}개 · "
            f"실패 {result.get('failedImages', 0)}장 · {result.get('durationMs', 0)} ms"
        )
        pool_label.setObjectName("mutedLabel")
        layout.addWidget(pool_label)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines: list[str] = []
        for index, group in enumerate(result.get("groups") or [], 1):
            lines.append(f"[{index}] {group.get('count')}장 · {group.get('hash')}")
            lines.extend(f"  {path}" for path in group.get("paths") or [])
            lines.append("")
        for failure in result.get("failures") or []:
            lines.append(f"[실패] {failure.get('path')}\n  {failure.get('error')}")
        if not lines:
            lines.append("같은 해시로 판정된 이미지가 없습니다.")
        details.setPlainText("\n".join(lines))
        layout.addWidget(details, 1)
        note = QLabel("읽기 전용 검사입니다. 이미지 파일을 변경하거나 삭제하지 않습니다.")
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CompletionCountdownDialog(QDialog):
    def __init__(
        self,
        action: str,
        countdown_seconds: int,
        *,
        preview: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.action = action
        self.remaining = max(1, int(countdown_seconds))
        self.preview = preview
        self.setWindowTitle("모든 작업 완료 후 동작")
        self.setModal(False)
        self.resize(500, 210)
        layout = QVBoxLayout(self)
        heading = QLabel("시스템 종료" if action == "shutdown" else "프로그램 종료")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        note = QLabel(
            "미리보기이므로 실제 종료는 실행하지 않습니다."
            if preview
            else "취소를 누르면 이번 완료 후 동작을 실행하지 않습니다."
        )
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._update_message()
        self.timer.start(1000)

    def _update_message(self) -> None:
        label = "Windows를 종료" if self.action == "shutdown" else "프로그램을 종료"
        self.message.setText(f"모든 작업이 끝났습니다. {self.remaining}초 후 {label}합니다.")

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            if self.preview:
                self.reject()
            else:
                self.accept()
            return
        self._update_message()

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "action": self.action,
            "remainingSeconds": self.remaining,
            "preview": self.preview,
        }


class HitomiReferenceDialog(QDialog):
    def __init__(
        self,
        owner: "MainWindow",
        reference: str = "",
        provider_hint: str = "auto",
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.last_result: dict[str, Any] = {}
        self.last_write_result: dict[str, Any] = {}
        self.setWindowTitle("Hitomi / ExHentai URL·ID 분석")
        self.resize(720, 430)
        layout = QVBoxLayout(self)

        heading = QLabel("Hitomi / ExHentai 작품 식별자 검사")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        note = QLabel(
            "URL 또는 숫자 갤러리 ID를 외부 네트워크 연결 없이 분석합니다. "
            "ExHentai 갤러리 토큰은 결과와 로그에 원문으로 표시하지 않습니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("자동 판정", "auto")
        self.provider_combo.addItem("Hitomi", "hitomi")
        self.provider_combo.addItem("ExHentai", "exhentai")
        provider_index = self.provider_combo.findData(str(provider_hint or "auto"))
        self.provider_combo.setCurrentIndex(max(0, provider_index))
        form.addRow("공급자", self.provider_combo)
        self.reference_edit = QLineEdit(str(reference or ""))
        self.reference_edit.setPlaceholderText(
            "https://hitomi.la/manga/title-1234567.html 또는 1234567"
        )
        form.addRow("URL / 갤러리 ID", self.reference_edit)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        inspect_button = QPushButton("분석")
        inspect_button.setToolTip(
            "CLI: hitomi inspect --input URL_OR_ID --provider auto --json"
        )
        inspect_button.clicked.connect(self.inspect_current_reference)
        action_row.addStretch(1)
        action_row.addWidget(inspect_button)
        layout.addLayout(action_row)

        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("분석 결과가 여기에 표시됩니다.")
        layout.addWidget(self.result_text, 1)

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        footer.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "CLI: hitomi close"
        )
        footer.rejected.connect(self.close)
        layout.addWidget(footer)
        self.reference_edit.returnPressed.connect(self.inspect_current_reference)
        if reference:
            self.inspect_current_reference()

    def inspect_current_reference(self) -> dict[str, Any]:
        try:
            result = inspect_hitomi_reference(
                self.reference_edit.text(),
                provider_hint=str(self.provider_combo.currentData() or "auto"),
            )
        except HitomiReferenceError as error:
            result = error.to_dict()
        self.last_result = result
        if result.get("ok"):
            authentication = (
                "필요 · 실제 인증 기능은 아직 사용하지 않음"
                if result["requiresAuthentication"]
                else "필요 없음"
            )
            token = (
                f"있음 ({result['galleryTokenHint']}) · 원문 미표시"
                if result["galleryTokenPresent"]
                else "없음"
            )
            display_url = result.get("displayUrl") or "갤러리 토큰을 포함한 URL 필요"
            lines = [
                "분석 완료 · 외부 요청 없음",
                "",
                f"공급자: {result['provider']}",
                f"갤러리 ID: {result['galleryId']}",
                f"작품 식별자: {result['workKey']}",
                f"입력 종류: {result['sourceKind']}",
                f"표시 URL: {display_url}",
                f"인증: {authentication}",
                f"갤러리 토큰: {token}",
            ]
        else:
            lines = [
                "분석 실패 · 외부 요청 없음",
                "",
                f"오류 코드: {result.get('errorCode', 'hitomi.unknown')}",
                f"원인: {result.get('error', '')}",
            ]
        self.result_text.setPlainText("\n".join(lines))
        return dict(result)

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "providerHint": str(self.provider_combo.currentData() or "auto"),
            "referenceLength": len(self.reference_edit.text()),
            "result": dict(self.last_result),
            "networkRequested": False,
        }


class HitomiMetadataDialog(QDialog):
    def __init__(
        self,
        owner: "MainWindow",
        reference: str = "",
        provider_hint: str = "auto",
        fixture_path: str = "",
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.last_result: dict[str, Any] = {}
        self.fixture_path = str(fixture_path or "")
        self.fetch_task: ServiceTask | None = None
        self.setWindowTitle("Hitomi / ExHentai 갤러리 메타데이터")
        self.resize(780, 610)
        layout = QVBoxLayout(self)

        heading = QLabel("갤러리 메타데이터 전용 모드")
        heading.setObjectName("dialogTitle")
        layout.addWidget(heading)
        policy = hitomi_metadata_policy_snapshot(owner.config)
        note = QLabel(
            f"현재 방식: {policy['mode']} · 응답 상한 8 MiB. 요청 계획과 로컬 픽스처는 "
            "오프라인이며 실제 조회는 매번 외부 연결 확인을 받습니다. 저장 쿠키 사용은 기본 꺼짐입니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("자동 판정", "auto")
        self.provider_combo.addItem("Hitomi", "hitomi")
        self.provider_combo.addItem("ExHentai", "exhentai")
        provider_index = self.provider_combo.findData(str(provider_hint or "auto"))
        self.provider_combo.setCurrentIndex(max(0, provider_index))
        form.addRow("공급자", self.provider_combo)
        self.reference_edit = QLineEdit(str(reference or ""))
        self.reference_edit.setPlaceholderText("Hitomi/ExHentai URL 또는 갤러리 ID")
        form.addRow("URL / 갤러리 ID", self.reference_edit)
        self.fixture_label = QLabel(self.fixture_path or "선택하지 않음")
        self.fixture_label.setWordWrap(True)
        form.addRow("로컬 픽스처", self.fixture_label)
        self.use_cookies_checkbox = QCheckBox("OS 보안 저장소의 선택 공급자 쿠키 사용")
        self.use_cookies_checkbox.setChecked(False)
        self.use_cookies_checkbox.setToolTip(
            "CLI: hitomi metadata fetch --input URL --use-cookies --yes --json"
        )
        form.addRow("로그인 쿠키", self.use_cookies_checkbox)
        layout.addLayout(form)

        actions = QHBoxLayout()
        plan_button = QPushButton("요청 계획")
        plan_button.setToolTip(
            "CLI: hitomi metadata plan --input URL_OR_ID --json"
        )
        plan_button.clicked.connect(self.show_request_plan)
        fixture_button = QPushButton("픽스처 열기...")
        fixture_button.setToolTip(
            "CLI: hitomi metadata parse --input URL_OR_ID --fixture PATH --json"
        )
        fixture_button.clicked.connect(self.load_fixture)
        self.fetch_button = QPushButton("실제 메타데이터 조회...")
        self.fetch_button.setToolTip(
            "CLI: hitomi metadata fetch --input URL --yes --json"
        )
        self.fetch_button.clicked.connect(self.confirm_fetch)
        self.save_files_button = QPushButton("폴더에 정보 저장...")
        self.save_files_button.setToolTip(
            "CLI: hitomi metadata-files write --input ID --fixture PATH --output DIR --yes --json"
        )
        self.save_files_button.clicked.connect(self.save_metadata_files)
        actions.addWidget(plan_button)
        actions.addWidget(fixture_button)
        actions.addWidget(self.fetch_button)
        actions.addWidget(self.save_files_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("요청 계획 또는 메타데이터 결과가 표시됩니다.")
        layout.addWidget(self.result_text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip(
            "CLI: hitomi metadata close"
        )
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        if self.fixture_path and reference:
            self.load_fixture(self.fixture_path)
        elif reference:
            self.show_request_plan()

    def _provider(self) -> str:
        return str(self.provider_combo.currentData() or "auto")

    def _set_result(self, result: dict[str, Any]) -> dict[str, Any]:
        self.last_result = dict(result)
        if not result.get("ok"):
            lines = [
                "처리 실패",
                "",
                f"오류 코드: {result.get('errorCode', 'hitomi.unknown')}",
                f"원인: {result.get('error', '')}",
            ]
        elif result.get("request") is not None or result.get("reason") == "disabled":
            request = result.get("request") or {}
            body = request.get("body")
            lines = [
                "요청 계획 · 아직 외부 요청 없음",
                "",
                f"공급자: {result.get('provider', '')}",
                f"갤러리 ID: {result.get('galleryId', '')}",
                f"메타데이터 방식: {result.get('mode', '')}",
                f"HTTP: {request.get('method', '사용 안 함')}",
                f"주소: {request.get('url', '-')}",
                f"요청 본문: {json.dumps(body, ensure_ascii=False) if body else '-'}",
                f"비밀값 포함: {'예 · 토큰 원문은 마스킹됨' if request.get('containsSecret') else '아니요'}",
            ]
        else:
            tags = list(result.get("tags") or [])
            title_selection = select_hitomi_display_title(
                result, config=self.owner.config
            )
            image_plan = plan_hitomi_image_sources(
                result, config=self.owner.config, sample_limit=0
            )
            image_summary = (
                f"원본 {image_plan['knownFileCount']}개"
                if image_plan["useOriginal"]
                else (
                    f"최적화 {image_plan['optimizedCount']}개 · "
                    f"원본 폴백 {image_plan['fallbackCount']}개 · "
                    f"미확정 {image_plan['unresolvedFileCount']}개"
                )
            )
            lines = [
                "메타데이터 분석 완료",
                "",
                f"공급자: {result.get('provider', '')}",
                f"갤러리 ID: {result.get('galleryId', '')}",
                f"제목: {result.get('title', '')}",
                f"일본어 제목: {result.get('japaneseTitle') or '-'}",
                f"선택 제목: {title_selection['selectedTitle']} · {title_selection['selectedField']}",
                f"작가: {', '.join(result.get('artists') or []) or '-'}",
                f"그룹: {', '.join(result.get('groups') or []) or '-'}",
                f"분류 / 언어: {result.get('category') or '-'} / {result.get('language') or '-'}",
                f"페이지: {int(result.get('pageCount') or 0):,}",
                f"이미지 선택: {image_summary}",
                f"태그: {', '.join(tags[:20]) or '-'}",
                f"외부 요청: {'실행함' if result.get('networkRequested') else '없음'}",
            ]
            if len(tags) > 20:
                lines.append(f"태그 나머지: {len(tags) - 20:,}개")
        self.result_text.setPlainText("\n".join(lines))
        return dict(result)

    def show_request_plan(self) -> dict[str, Any]:
        try:
            result = hitomi_metadata_request_plan(
                self.reference_edit.text(),
                provider_hint=self._provider(),
                config=self.owner.config,
            )
        except HitomiReferenceError as error:
            result = error.to_dict()
        return self._set_result(result)

    def load_fixture(self, selected_path: str | bool = "") -> dict[str, Any]:
        path = selected_path if isinstance(selected_path, str) else ""
        if not path:
            path, _filter = QFileDialog.getOpenFileName(
                self,
                "갤러리 메타데이터 픽스처 열기",
                self.fixture_path or str(ROOT_DIR),
                "메타데이터 (*.js *.json);;모든 파일 (*)",
            )
        if not path:
            return {}
        self.fixture_path = str(Path(path).expanduser().resolve())
        self.fixture_label.setText(self.fixture_path)
        try:
            result = load_hitomi_metadata_fixture(
                self.reference_edit.text(),
                Path(self.fixture_path),
                provider_hint=self._provider(),
            )
        except (HitomiReferenceError, OSError, ValueError) as error:
            result = (
                error.to_dict()
                if isinstance(error, HitomiReferenceError)
                else {"ok": False, "errorCode": "hitomi.fixture_error", "error": str(error)}
            )
        return self._set_result(result)

    def confirm_fetch(self) -> bool:
        try:
            plan = hitomi_metadata_request_plan(
                self.reference_edit.text(),
                provider_hint=self._provider(),
                config=self.owner.config,
            )
        except HitomiReferenceError as error:
            self._set_result(error.to_dict())
            return False
        if not plan.get("request"):
            self._set_result(plan)
            return False
        answer = QMessageBox.question(
            self,
            "외부 메타데이터 요청",
            f"다음 공급자 주소로 메타데이터만 요청할까요?\n\n"
            f"{plan['request']['url']}\n\n"
            + (
                "OS 보안 저장소에서 선택 공급자의 쿠키를 읽어 이 요청에만 사용합니다. "
                if self.use_cookies_checkbox.isChecked()
                else "저장된 쿠키는 읽거나 사용하지 않습니다. "
            )
            + "이미지 다운로드는 하지 않습니다. ExHentai URL의 갤러리 토큰과 쿠키 값은 "
            "요청 메모리에서만 사용하고 결과·로그에 남기지 않습니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.start_fetch()
        return True

    def save_metadata_files(self) -> dict[str, Any]:
        if not self.last_result.get("ok") or not (
            self.last_result.get("title") or self.last_result.get("japaneseTitle")
        ):
            QMessageBox.warning(
                self,
                "메타데이터 파일 저장",
                "먼저 로컬 픽스처를 열거나 메타데이터 조회를 완료해주세요.",
            )
            return {}
        policy = hitomi_metadata_file_policy_snapshot(self.owner.config)
        if not policy["enabled"]:
            QMessageBox.information(
                self,
                "메타데이터 파일 저장",
                "공급자 설정에서 메타데이터 파일 생성이 꺼져 있습니다.",
            )
            return {}
        output = QFileDialog.getExistingDirectory(
            self,
            "메타데이터를 저장할 기존 작품 폴더 선택",
            str(self.owner.config.get("outputDir") or ROOT_DIR),
        )
        if not output:
            return {}
        try:
            plan = plan_hitomi_metadata_files(
                self.last_result,
                Path(output),
                config=self.owner.config,
            )
        except (HitomiReferenceError, OSError, ValueError) as error:
            QMessageBox.warning(self, "메타데이터 파일 저장", str(error))
            return {}
        names = ", ".join(item["name"] for item in plan["files"]) or "생성 파일 없음"
        overwrite = int(plan["wouldOverwriteCount"]) > 0
        detail = (
            f"다음 폴더에 {names}을 저장할까요?\n\n{plan['outputPath']}"
            + (
                f"\n\n기존 파일 {plan['wouldOverwriteCount']}개를 교체합니다."
                if overwrite
                else "\n\n기존 파일은 교체하지 않습니다."
            )
        )
        if QMessageBox.question(
            self, "메타데이터 파일 저장 확인", detail
        ) != QMessageBox.StandardButton.Yes:
            return {}
        try:
            result = write_hitomi_metadata_files(
                self.last_result,
                Path(output),
                config=self.owner.config,
                overwrite=overwrite,
            )
        except (HitomiReferenceError, OSError, ValueError) as error:
            QMessageBox.warning(self, "메타데이터 파일 저장", str(error))
            return {}
        self.last_write_result = dict(result)
        self.owner.log(
            f"Hitomi 메타데이터 파일 저장: {result['writtenCount']}개 · {result['outputPath']}"
        )
        QMessageBox.information(
            self,
            "메타데이터 파일 저장 완료",
            f"{result['writtenCount']}개 파일을 저장했습니다.\n{result['outputPath']}",
        )
        return result

    def start_fetch(self) -> None:
        if self.fetch_task is not None:
            return
        reference = self.reference_edit.text()
        provider = self._provider()
        config = dict(self.owner.config)
        use_cookies = self.use_cookies_checkbox.isChecked()
        task = ServiceTask(
            "hitomi-metadata",
            lambda: self._fetch_metadata_service(
                reference, provider, config, use_cookies
            ),
        )
        self.fetch_task = task
        self.fetch_button.setEnabled(False)
        self.result_text.setPlainText("메타데이터 요청 중...")
        task.signals.finished.connect(self._fetch_finished)
        self.owner.io_thread_pool.start(task)
        self.owner.log("사용자 확인 후 Hitomi 메타데이터 요청 시작")

    @staticmethod
    def _fetch_metadata_service(
        reference: str,
        provider: str,
        config: dict[str, Any],
        use_cookies: bool,
    ) -> dict[str, Any]:
        fetch_options: dict[str, Any] = {}
        if use_cookies:
            plan = hitomi_metadata_request_plan(
                reference,
                provider_hint=provider,
                config=config,
            )
            request = plan.get("request") or {}
            fetch_options["cookie_header"] = provider_cookie_request_header(
                str(plan["provider"]),
                str(request.get("url") or ""),
            )
        return fetch_hitomi_metadata(
            reference,
            provider_hint=provider,
            config=config,
            **fetch_options,
        )

    def _fetch_finished(self, _task_id: str, result: object, error: str) -> None:
        self.fetch_task = None
        self.fetch_button.setEnabled(True)
        if error:
            payload = {
                "ok": False,
                "errorCode": "hitomi.metadata_network",
                "error": error,
            }
            self.owner.log("Hitomi 메타데이터 요청 실패", "ERROR")
        else:
            payload = result if isinstance(result, dict) else {}
            self.owner.log("Hitomi 메타데이터 요청 완료")
        self._set_result(payload)

    def state_snapshot(self) -> dict[str, Any]:
        try:
            title_selection = (
                select_hitomi_display_title(
                    self.last_result, config=self.owner.config
                )
                if self.last_result.get("ok")
                and (
                    self.last_result.get("title")
                    or self.last_result.get("japaneseTitle")
                )
                else {}
            )
        except (HitomiReferenceError, ValueError):
            title_selection = {}
        try:
            image_source_plan = (
                plan_hitomi_image_sources(
                    self.last_result, config=self.owner.config, sample_limit=20
                )
                if self.last_result.get("ok")
                and (self.last_result.get("title") or self.last_result.get("japaneseTitle"))
                else {}
            )
        except (HitomiReferenceError, ValueError):
            image_source_plan = {}
        return {
            "open": self.isVisible(),
            "providerHint": self._provider(),
            "referenceLength": len(self.reference_edit.text()),
            "fixtureSelected": bool(self.fixture_path),
            "fetchRunning": self.fetch_task is not None,
            "useStoredCookies": self.use_cookies_checkbox.isChecked(),
            "cookieValuesExposed": False,
            "result": dict(self.last_result),
            "titleSelection": title_selection,
            "metadataFiles": dict(getattr(self, "last_write_result", {})),
            "imageSourcePlan": image_source_plan,
        }


class EmbeddedBrowserDialog(QDialog):
    OFFLINE_HTML = """
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>
body{font-family:'Malgun Gothic',sans-serif;background:#20242b;color:#eef2f7;margin:0;padding:48px}
.card{max-width:760px;margin:auto;background:#292f38;border:1px solid #475262;border-radius:12px;padding:32px}
h1{font-size:26px;margin:0 0 16px}.muted{color:#b8c4d4;line-height:1.7}
.safe{display:inline-block;background:#234b37;color:#b8f3d0;padding:6px 10px;border-radius:6px;margin-top:14px}
</style></head><body><div class="card"><h1>tokiDownloader 내장 브라우저</h1>
<p class="muted">현재는 네트워크를 사용하지 않는 오프라인 시작 화면입니다. 주소를 입력하고 이동을 누르면 외부 연결 전에 확인합니다.</p>
<p class="muted">개인 Chrome 프로필 및 자동화 브라우저 쿠키와 분리된 메모리 전용 프로필을 사용합니다. 창을 닫으면 세션 데이터는 보존하지 않습니다.</p>
<span class="safe">오프라인 · 외부 요청 없음</span></div></body></html>
"""

    def __init__(
        self,
        owner: "MainWindow",
        initial_url: str = "",
        *,
        navigate: bool = False,
        confirmed: bool = False,
    ) -> None:
        super().__init__(owner)
        runtime = webengine_runtime_status()
        if not runtime["available"]:
            raise RuntimeError(
                "내장 브라우저가 설치되지 않았습니다. setup-gui.cmd -WithBrowserTools를 실행해주세요."
                + (f" ({runtime['importError']})" if runtime["importError"] else "")
            )
        self.owner = owner
        self._allowed_url = ""
        self._last_network_approved = False
        self._loading = False
        self.setWindowTitle("메모리 전용 내장 브라우저")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        notice = QLabel(
            "개인 Chrome·자동화 쿠키와 분리된 메모리 전용 프로필입니다. HTTPS 이동마다 외부 연결을 확인합니다."
        )
        notice.setObjectName("mutedLabel")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        toolbar = QHBoxLayout()
        back_button = QPushButton("뒤로")
        forward_button = QPushButton("앞으로")
        reload_button = QPushButton("새로고침")
        stop_button = QPushButton("중지")
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("HTTPS 주소")
        self.address_edit.setText(normalize_embedded_browser_url(initial_url))
        go_button = QPushButton("이동...")
        go_button.setToolTip(
            "CLI: embedded-browser manage --show-gui --url URL --navigate --yes"
        )
        toolbar.addWidget(back_button)
        toolbar.addWidget(forward_button)
        toolbar.addWidget(reload_button)
        toolbar.addWidget(stop_button)
        toolbar.addWidget(self.address_edit, 1)
        toolbar.addWidget(go_button)
        layout.addLayout(toolbar)

        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        self.profile.downloadRequested.connect(lambda download: download.cancel())

        owner_dialog = self

        class GuardedPage(QWebEnginePage):
            def acceptNavigationRequest(
                page_self,
                url: QUrl,
                navigation_type: Any,
                is_main_frame: bool,
            ) -> bool:
                target = url.toString()
                if not is_main_frame or url.scheme().lower() not in {"http", "https"}:
                    return super().acceptNavigationRequest(
                        url, navigation_type, is_main_frame
                    )
                if owner_dialog._allowed_url == target:
                    owner_dialog._allowed_url = ""
                    return True
                QTimer.singleShot(
                    0,
                    lambda requested=target: owner_dialog.request_navigation(requested),
                )
                return False

            def createWindow(page_self, _window_type: Any) -> Any:
                return None

        self.page = GuardedPage(self.profile, self)
        self.page.featurePermissionRequested.connect(
            lambda origin, feature: self.page.setFeaturePermission(
                origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser,
            )
        )
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.view.setHtml(self.OFFLINE_HTML, QUrl("about:blank"))
        layout.addWidget(self.view, 1)
        footer = QHBoxLayout()
        self.status_label = QLabel("오프라인 시작 화면 · 외부 요청 없음")
        footer.addWidget(self.status_label, 1)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        back_button.clicked.connect(self.view.back)
        forward_button.clicked.connect(self.view.forward)
        reload_button.clicked.connect(
            lambda: self.request_navigation(self.view.url().toString())
            if self.view.url().scheme().lower() in {"http", "https"}
            else self.view.setHtml(self.OFFLINE_HTML, QUrl("about:blank"))
        )
        stop_button.clicked.connect(self.view.stop)
        go_button.clicked.connect(lambda: self.request_navigation(self.address_edit.text()))
        self.address_edit.returnPressed.connect(
            lambda: self.request_navigation(self.address_edit.text())
        )
        self.view.urlChanged.connect(self._url_changed)
        self.view.loadStarted.connect(self._load_started)
        self.view.loadProgress.connect(
            lambda progress: self.status_label.setText(f"불러오는 중 · {progress}%")
        )
        self.view.loadFinished.connect(self._load_finished)
        if navigate:
            QTimer.singleShot(
                0,
                lambda: self.request_navigation(initial_url, confirmed=confirmed),
            )

    def request_navigation(self, url: str, *, confirmed: bool = False) -> bool:
        try:
            plan = embedded_browser_navigation_plan(url)
        except ValueError as error:
            QMessageBox.warning(self, "주소를 열 수 없음", str(error))
            return False
        if not confirmed:
            answer = QMessageBox.question(
                self,
                "외부 HTTPS 연결",
                f"메모리 전용 내장 브라우저로 다음 호스트에 연결할까요?\n\n{plan['host']}\n\n"
                "공급자 쿠키와 개인 Chrome 프로필은 사용하지 않습니다.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self._allowed_url = plan["url"]
        self._last_network_approved = True
        self.address_edit.setText(plan["url"])
        self.view.setUrl(QUrl(plan["url"]))
        return True

    def _url_changed(self, url: QUrl) -> None:
        if url.scheme().lower() in {"http", "https"}:
            self.address_edit.setText(url.toString())

    def _load_started(self) -> None:
        self._loading = True
        self.status_label.setText("불러오는 중...")

    def _load_finished(self, ok: bool) -> None:
        self._loading = False
        if self.view.url().scheme().lower() not in {"http", "https"}:
            self.status_label.setText("오프라인 시작 화면 · 외부 요청 없음")
        else:
            self.status_label.setText("불러오기 완료" if ok else "불러오기 실패 또는 차단")

    def state_snapshot(self) -> dict[str, Any]:
        current_url = self.view.url().toString()
        return {
            "open": self.isVisible(),
            "available": True,
            "url": current_url if current_url.startswith(("http://", "https://")) else "",
            "address": self.address_edit.text(),
            "loading": self._loading,
            "networkApproved": self._last_network_approved,
            "offTheRecordProfile": bool(self.profile.isOffTheRecord()),
            "persistentCookies": False,
            "sharesAutomationCookies": False,
        }

    def closeEvent(self, event: QCloseEvent) -> None:
        self.view.stop()
        self.page.deleteLater()
        self.profile.clearHttpCache()
        super().closeEvent(event)


class ProxyCredentialDialog(QDialog):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.proxy_url = str(owner.config.get("proxyUrl") or "")
        self.setWindowTitle("프록시 인증 관리")
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "프록시 사용자명과 비밀번호는 설정 파일에 저장하지 않고 Windows 자격 증명 저장소에만 보관합니다. 상태 읽기·저장·삭제마다 다시 확인합니다."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        proxy_label = QLabel(self.proxy_url or "설정된 프록시 없음")
        proxy_label.setWordWrap(True)
        form.addRow("현재 프록시", proxy_label)
        capability = credential_store_status()
        backend_text = (
            f"사용 가능 · {capability['backend']}"
            if capability["available"]
            else "사용 불가 · requirements-security.txt 설치 필요"
        )
        backend_label = QLabel(backend_text)
        backend_label.setWordWrap(True)
        form.addRow("OS 보안 저장소", backend_label)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("프록시 사용자명")
        form.addRow("사용자명", self.username_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("저장 후 화면과 로그에 표시하지 않음")
        form.addRow("비밀번호", self.password_edit)
        self.summary_label = QLabel("인증 상태를 아직 읽지 않았습니다.")
        self.summary_label.setWordWrap(True)
        form.addRow("현재 상태", self.summary_label)
        layout.addLayout(form)
        actions = QHBoxLayout()
        status_button = QPushButton("상태 읽기")
        status_button.setToolTip("CLI: proxy-auth status --yes")
        status_button.clicked.connect(self._read_status)
        save_button = QPushButton("안전하게 저장...")
        save_button.setToolTip(
            "CLI: proxy-auth set --username USER --password-stdin --yes"
        )
        save_button.clicked.connect(self._save)
        clear_button = QPushButton("저장 정보 삭제...")
        clear_button.setToolTip("CLI: proxy-auth clear --yes")
        clear_button.clicked.connect(self._clear)
        for button in (status_button, save_button, clear_button):
            button.setEnabled(bool(capability["available"]))
            actions.addWidget(button)
        save_button.setEnabled(bool(capability["available"] and self.proxy_url))
        actions.addStretch(1)
        layout.addLayout(actions)
        note = QLabel(
            "인증 정보는 저장 당시 프록시 주소와 정확히 일치할 때만 다운로드 자식 프로세스에 전달됩니다. 명령행 인자에는 포함하지 않습니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _confirm(self, title: str, message: str) -> bool:
        return QMessageBox.question(self, title, message) == QMessageBox.StandardButton.Yes

    def _read_status(self) -> None:
        if not self._confirm(
            "프록시 인증 상태 읽기",
            "Windows 자격 증명 저장소에서 프록시 인증 메타데이터를 읽을까요? 비밀번호는 표시하지 않습니다.",
        ):
            return
        try:
            status = proxy_credential_status(self.proxy_url)
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "프록시 인증 상태를 읽을 수 없음", str(error))
            return
        self.username_edit.setText(str(status.get("username") or ""))
        self.password_edit.clear()
        if not status["stored"]:
            summary = "저장된 프록시 인증 정보가 없습니다."
        elif status["matchesConfiguredProxy"]:
            summary = f"현재 프록시에 연결됨 · 사용자명 {status['username']} · 비밀번호 숨김"
        else:
            summary = "다른 프록시 주소에 묶인 인증 정보가 저장되어 있어 현재 다운로드에는 사용하지 않습니다."
        self.summary_label.setText(summary)

    def _save(self) -> None:
        if not self._confirm(
            "프록시 인증 저장",
            "입력한 사용자명과 비밀번호를 Windows 자격 증명 저장소에 저장할까요?",
        ):
            return
        try:
            result = store_proxy_credentials(
                self.proxy_url,
                self.username_edit.text(),
                self.password_edit.text(),
            )
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "프록시 인증을 저장할 수 없음", str(error))
            return
        self.password_edit.clear()
        self.summary_label.setText(
            f"현재 프록시에 안전하게 저장됨 · 사용자명 {result['username']} · 비밀번호 숨김"
        )

    def _clear(self) -> None:
        if not self._confirm(
            "프록시 인증 삭제",
            "Windows 자격 증명 저장소의 프록시 인증 정보를 삭제할까요? 되돌릴 수 없습니다.",
        ):
            return
        try:
            result = clear_proxy_credentials()
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "프록시 인증을 삭제할 수 없음", str(error))
            return
        self.username_edit.clear()
        self.password_edit.clear()
        self.summary_label.setText(
            "저장된 인증 정보를 삭제했습니다."
            if result["cleared"]
            else "저장된 인증 정보가 없습니다."
        )

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "proxyConfigured": bool(self.proxy_url),
            "statusRead": "아직" not in self.summary_label.text(),
            "passwordExposed": False,
        }


class CookieManagerDialog(QDialog):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("공급자 쿠키 관리")
        self.resize(620, 330)
        layout = QVBoxLayout(self)
        warning = QLabel(
            "쿠키는 계정 접근 권한을 포함할 수 있는 민감 정보입니다. 실제 읽기·저장·내보내기·삭제마다 다시 확인합니다."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self.provider_combo = QComboBox()
        for label, value in (
            ("마나토끼", "manatoki"),
            ("뉴토끼", "newtoki"),
            ("북토끼", "booktoki"),
            ("Hitomi.la", "hitomi"),
            ("ExHentai", "exhentai"),
            ("E-Hentai", "ehentai"),
        ):
            self.provider_combo.addItem(label, value)
        form.addRow("공급자", self.provider_combo)
        self.policy_label = QLabel("")
        self.policy_label.setWordWrap(True)
        form.addRow("인증 정책", self.policy_label)
        self.provider_combo.currentIndexChanged.connect(self._reset_summary)
        capability = credential_store_status()
        backend_text = (
            f"사용 가능 · {capability['backend']}"
            if capability["available"]
            else "사용 불가 · requirements-security.txt 설치 필요"
        )
        self.backend_label = QLabel(backend_text)
        self.backend_label.setWordWrap(True)
        form.addRow("OS 보안 저장소", self.backend_label)
        self.summary_label = QLabel("쿠키 상태를 아직 읽지 않았습니다.")
        self.summary_label.setWordWrap(True)
        form.addRow("현재 상태", self.summary_label)
        layout.addLayout(form)
        actions = QHBoxLayout()
        status_button = QPushButton("상태 읽기")
        status_button.setToolTip("CLI: cookies status --provider PROVIDER --yes")
        status_button.clicked.connect(self._read_status)
        import_button = QPushButton("가져오기...")
        import_button.setToolTip("CLI: cookies import --provider PROVIDER --input PATH --yes")
        import_button.clicked.connect(self._import_cookies)
        export_button = QPushButton("내보내기...")
        export_button.setToolTip("CLI: cookies export --provider PROVIDER --output PATH --yes")
        export_button.clicked.connect(self._export_cookies)
        clear_button = QPushButton("초기화...")
        clear_button.setToolTip("CLI: cookies clear --provider PROVIDER --yes")
        clear_button.clicked.connect(self._clear_cookies)
        for button in (status_button, import_button, export_button, clear_button):
            button.setEnabled(bool(capability["available"]))
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self._reset_summary()

    def provider(self) -> str:
        return str(self.provider_combo.currentData() or "manatoki")

    def _reset_summary(self, _index: int = 0) -> None:
        self.summary_label.setText("쿠키 상태를 아직 읽지 않았습니다.")
        policy = provider_cookie_policy(self.provider())
        allowed = ", ".join(policy["allowedDomainSuffixes"]) or "사이트 주소 변경에 따라 제한하지 않음"
        hints = ", ".join(policy["recommendedCookieNames"]) or "없음"
        self.policy_label.setText(
            f"로그인 필수: {'예' if policy['authenticationRequired'] else '아니요'} · "
            f"허용 도메인: {allowed} · 알려진 이름 힌트: {hints} · 접근 제한 우회 미지원"
        )

    def _confirm(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(self, title, message)
            == QMessageBox.StandardButton.Yes
        )

    def _read_status(self) -> None:
        if not self._confirm(
            "쿠키 상태 읽기",
            "OS 보안 저장소에서 쿠키 메타데이터를 읽을까요? 쿠키 값은 화면에 표시하지 않습니다.",
        ):
            return
        try:
            status = provider_cookie_status(self.provider())
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "쿠키 상태를 읽을 수 없음", str(error))
            return
        domains = ", ".join(status["domains"]) or "없음"
        readiness = ""
        if status["authenticationRequired"]:
            if status["authenticationReady"] is True:
                readiness = " · 인증 자료 확인됨"
            elif status["authenticationReady"] is False:
                readiness = " · 관련 쿠키 없음"
            else:
                readiness = " · 로그인 성공 여부는 실제 요청에서만 확인"
        self.summary_label.setText(
            f"저장: {'예' if status['stored'] else '아니요'} · "
            f"{status['cookieCount']}개 · 도메인: {domains}{readiness}"
        )

    def _import_cookies(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "쿠키 파일 선택", "", "쿠키 파일 (*.json *.txt);;모든 파일 (*)"
        )
        if not selected:
            return
        if not self._confirm(
            "민감한 쿠키 파일 검사",
            "선택한 파일을 읽어 쿠키 개수와 공급자 적합성을 검사할까요? 쿠키 값은 화면이나 로그에 표시하지 않습니다.",
        ):
            return
        try:
            plan = cookie_import_plan(self.provider(), Path(selected))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "쿠키 파일을 읽을 수 없음", str(error))
            return
        readiness = ""
        if plan["authenticationRequired"] and plan["authenticationReady"] is False:
            missing = ", ".join(plan["missingRequiredCookieNames"])
            readiness = f"\n주의: 로그인에 필요한 것으로 알려진 쿠키가 부족합니다: {missing}"
        elif plan["authenticationRequired"] and plan["authenticationReady"] is None:
            readiness = "\n로그인 성공 여부는 사용자가 승인한 실제 요청에서만 확인할 수 있습니다."
        ignored = (
            f"\n다른 도메인의 쿠키 {plan['ignoredCookieCount']}개는 저장하지 않습니다."
            if plan["ignoredCookieCount"]
            else ""
        )
        if not self._confirm(
            "쿠키 가져오기",
            f"관련 쿠키 {plan['cookieCount']}개를 Windows 보안 저장소에 저장할까요?"
            f"{ignored}{readiness}",
        ):
            return
        try:
            import_provider_cookies(self.provider(), Path(selected))
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "쿠키를 저장할 수 없음", str(error))
            return
        self.summary_label.setText(f"쿠키 {plan['cookieCount']}개를 안전하게 저장했습니다.")

    def _export_cookies(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self, "쿠키 내보내기", f"{self.provider()}-cookies.json", "JSON (*.json)"
        )
        if not selected:
            return
        if not self._confirm(
            "민감한 쿠키 내보내기",
            "쿠키 값이 포함된 평문 JSON 파일을 생성합니다. 안전한 개인 경로인지 확인했나요?",
        ):
            return
        try:
            result = export_provider_cookies(self.provider(), Path(selected))
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "쿠키를 내보낼 수 없음", str(error))
            return
        self.summary_label.setText(f"쿠키 {result['cookieCount']}개를 내보냈습니다.")

    def _clear_cookies(self) -> None:
        if not self._confirm(
            "저장된 쿠키 초기화",
            "선택 공급자의 쿠키를 Windows 보안 저장소에서 삭제할까요? 되돌릴 수 없습니다.",
        ):
            return
        try:
            result = clear_provider_cookies(self.provider())
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "쿠키를 초기화할 수 없음", str(error))
            return
        self.summary_label.setText(
            "저장된 쿠키를 삭제했습니다." if result["cleared"] else "저장된 쿠키가 없습니다."
        )

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "provider": self.provider(),
            "statusRead": "아직" not in self.summary_label.text(),
            "authenticationRequired": provider_cookie_policy(self.provider())[
                "authenticationRequired"
            ],
            "cookieValuesExposed": False,
        }


class SettingsDialog(QDialog):
    TAB_KEYS = ("general", "network", "display", "advanced", "provider")
    TAB_SEARCH_TERMS = (
        "일반 언어 한국어 저장 폴더 폴더명 템플릿 미리보기 경로 브라우저 로그 트레이 알림 닫기 최소화 완료 후 종료 시스템 종료 카운트다운 클립보드 URL 감지 중복 확인",
        "네트워크 동시 작품 이미지 연결 재시도 대기 백오프 프록시 HTTP HTTPS SOCKS 속도 제한 공급자 요청 간격 공인 IP 확인",
        "디스플레이 화면 테마 밝게 어둡게 목록 아이콘 밀도 표지 썸네일 크기 항상 위 투명도 배율 배경 이미지 글꼴 진행률 빠른 실행 도구",
        "고급 로그 파일 크기 보존 순환 기록 소리 알림음 메시지 상자 작업 완료 오류 미리보기 이미지 리사이즈 너비 높이 제외 확장자 파일 유형 압축 연결 프로그램 뷰어 자동 저장 주기 불완전 복구 시작 페이지 크기 메모리 작품 상한 스크롤 속도 지연 로딩 저사양 절전 방지 다운로드 전원 PDF 생성 회차 메모리 사용량 표시 RAM 시스템 자식 프로세스 HTTP API 로컬 포트 토큰",
        "공급자 toki newtoki manatoki booktoki hitomi exhentai 서버 자동 수동 우선순위 갤러리 정보 id 메타데이터 metadata.json info.txt 파일 저장 이미지 파일명 원본 숫자 이미지 품질 최적화 제외 태그 규칙 일본어 제목 우선 youtube yt-dlp ffmpeg 형식 해상도 컨테이너 비디오 오디오 코덱 선호 언어 자막 트랙 썸네일 설명 정보 json 포함 채널 재생목록 순서 역순 의존성 플러그인",
    )

    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner)
        self.owner = owner
        self.strings = load_ui_strings(owner.config.get("uiLanguage"))
        self.setWindowTitle(self.strings["settings.title"])
        self.resize(760, 700)
        layout = QVBoxLayout(self)
        heading = QLabel(self.strings["settings.heading"])
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            self.strings["settings.search.placeholder"]
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_tabs)
        layout.addWidget(self.search_edit)
        self.search_status = QLabel("")
        self.search_status.setObjectName("mutedLabel")
        layout.addWidget(self.search_status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        general_page = QWidget()
        general_page.setObjectName("settingsPage")
        general_form = QFormLayout(general_page)
        self.language_combo = QComboBox()
        for language in available_ui_languages():
            self.language_combo.addItem(language["name"], language["code"])
        general_form.addRow(self.strings["settings.language"], self.language_combo)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        output_row.addWidget(self.output_edit, 1)
        output_button = QPushButton("폴더 선택...")
        output_button.clicked.connect(self._choose_output)
        output_row.addWidget(output_button)
        general_form.addRow(self.strings["settings.output"], output_row)
        self.folder_template_edit = QLineEdit()
        self.folder_template_edit.setPlaceholderText("[{author}][{group}] {title}")
        self.folder_template_edit.textChanged.connect(self._update_folder_preview)
        general_form.addRow(
            self.strings["settings.folderTemplate"], self.folder_template_edit
        )
        self.folder_template_preview = QLabel("")
        self.folder_template_preview.setObjectName("mutedLabel")
        self.folder_template_preview.setWordWrap(True)
        general_form.addRow(self.strings["settings.preview"], self.folder_template_preview)
        self.show_browser_check = QCheckBox(
            "사이트 진단이 필요할 때 자동화 브라우저 창 표시"
        )
        general_form.addRow("브라우저", self.show_browser_check)
        self.log_visible_check = QCheckBox("메인 화면에 실행 로그 패널 표시")
        general_form.addRow("로그 패널", self.log_visible_check)
        self.tray_enabled_check = QCheckBox("시스템 트레이 아이콘 사용")
        general_form.addRow("트레이", self.tray_enabled_check)
        self.close_to_tray_check = QCheckBox("창 닫기 버튼을 누르면 트레이로 숨김")
        general_form.addRow("닫기 동작", self.close_to_tray_check)
        self.minimize_to_tray_check = QCheckBox("최소화하면 트레이로 숨김")
        general_form.addRow("최소화 동작", self.minimize_to_tray_check)
        self.notify_complete_check = QCheckBox("다운로드 완료 알림 표시")
        general_form.addRow("완료 알림", self.notify_complete_check)
        self.notify_error_check = QCheckBox("다운로드 오류·인증 필요 알림 표시")
        general_form.addRow("오류 알림", self.notify_error_check)
        self.completion_action_combo = QComboBox()
        self.completion_action_combo.addItem("아무 동작 안 함", "none")
        self.completion_action_combo.addItem("프로그램 종료", "exit")
        self.completion_action_combo.addItem("Windows 종료", "shutdown")
        general_form.addRow("모든 작업 완료 후", self.completion_action_combo)
        self.completion_countdown_spin = QSpinBox()
        self.completion_countdown_spin.setRange(5, 300)
        self.completion_countdown_spin.setSuffix("초")
        general_form.addRow("완료 후 카운트다운", self.completion_countdown_spin)
        self.clipboard_monitor_check = QCheckBox(
            "클립보드의 지원 작품 URL을 감지하고 추가 전 확인"
        )
        general_form.addRow("클립보드 감지", self.clipboard_monitor_check)
        general_note = QLabel(
            "브라우저 표시는 기본적으로 끄는 것을 권장합니다. 개인 Chrome 프로필은 사용하지 않습니다."
        )
        general_note.setObjectName("mutedLabel")
        general_note.setWordWrap(True)
        general_form.addRow("", general_note)
        self.tabs.addTab(general_page, self.strings["settings.tab.general"])

        network_page = QWidget()
        network_page.setObjectName("settingsPage")
        network_form = QFormLayout(network_page)
        self.work_spin = QSpinBox()
        self.work_spin.setRange(1, 4)
        network_form.addRow("최대 동시 작품", self.work_spin)
        self.image_spin = QSpinBox()
        self.image_spin.setRange(1, 16)
        network_form.addRow("작품당 이미지 연결", self.image_spin)
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(0, 5)
        network_form.addRow("자동 재시도 횟수", self.retry_count_spin)
        self.retry_backoff_spin = QSpinBox()
        self.retry_backoff_spin.setRange(1, 60)
        self.retry_backoff_spin.setSuffix("초")
        network_form.addRow("기본 재시도 대기", self.retry_backoff_spin)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("사용 안 함 · 예: http://127.0.0.1:8080")
        network_form.addRow("프록시", self.proxy_edit)
        proxy_auth_button = QPushButton("프록시 인증 관리...")
        proxy_auth_button.setToolTip("CLI: proxy-auth manage --show-gui")
        proxy_auth_button.clicked.connect(owner.show_proxy_credential_manager)
        proxy_auth_button.setEnabled(bool(credential_store_status()["available"]))
        network_form.addRow("선택적 인증", proxy_auth_button)
        self.speed_limit_spin = QSpinBox()
        self.speed_limit_spin.setRange(0, 1_048_576)
        self.speed_limit_spin.setSpecialValueText("무제한")
        self.speed_limit_spin.setSuffix(" KiB/s")
        network_form.addRow("전체 이미지 속도", self.speed_limit_spin)
        self.provider_policy_values: dict[str, dict[str, int]] = {}
        self._provider_current_key = ""
        self.provider_policy_combo = QComboBox()
        for label, value in (
            ("마나토끼", "manatoki"),
            ("뉴토끼", "newtoki"),
            ("북토끼", "booktoki"),
        ):
            self.provider_policy_combo.addItem(label, value)
        self.provider_policy_combo.currentIndexChanged.connect(
            self._provider_policy_selection_changed
        )
        network_form.addRow("공급자 정책", self.provider_policy_combo)
        self.provider_delay_spin = QSpinBox()
        self.provider_delay_spin.setRange(0, 5000)
        self.provider_delay_spin.setSuffix(" ms")
        network_form.addRow("최소 요청 간격", self.provider_delay_spin)
        self.provider_backoff_spin = QSpinBox()
        self.provider_backoff_spin.setRange(1, 60)
        self.provider_backoff_spin.setSuffix("초")
        network_form.addRow("공급자 백오프", self.provider_backoff_spin)
        public_ip_button = QPushButton("공인 IP 확인...")
        public_ip_button.clicked.connect(owner.confirm_public_ip_check)
        network_form.addRow("외부 연결 확인", public_ip_button)
        network_note = QLabel(
            "동시성 상한은 사이트와 PC 부하를 고려한 안전 범위입니다. 재시도 대기는 실패마다 지수 증가합니다."
        )
        network_note.setObjectName("mutedLabel")
        network_note.setWordWrap(True)
        network_form.addRow("", network_note)
        self.tabs.addTab(network_page, self.strings["settings.tab.network"])

        display_page = QWidget()
        display_page.setObjectName("settingsPage")
        display_form = QFormLayout(display_page)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("시스템 설정 사용", "system")
        self.theme_combo.addItem("밝게", "light")
        self.theme_combo.addItem("어둡게", "dark")
        display_form.addRow("테마", self.theme_combo)
        self.row_density_combo = QComboBox()
        self.row_density_combo.addItem("편안하게 - 표지와 진행률 표시", "comfortable")
        self.row_density_combo.addItem("간략하게 - 낮은 행으로 많이 표시", "compact")
        display_form.addRow("작품 목록 밀도", self.row_density_combo)
        self.list_view_mode_combo = QComboBox()
        self.list_view_mode_combo.addItem("목록 보기", "list")
        self.list_view_mode_combo.addItem("아이콘 보기", "icon")
        display_form.addRow("작품 보기 방식", self.list_view_mode_combo)
        self.thumbnails_visible_check = QCheckBox("작품 대표 이미지 표시")
        display_form.addRow("썸네일", self.thumbnails_visible_check)
        self.thumbnail_size_combo = QComboBox()
        self.thumbnail_size_combo.addItem("작게", "small")
        self.thumbnail_size_combo.addItem("보통", "medium")
        self.thumbnail_size_combo.addItem("크게", "large")
        display_form.addRow("썸네일 크기", self.thumbnail_size_combo)
        self.always_on_top_check = QCheckBox("다른 창 위에 항상 표시")
        display_form.addRow("항상 위", self.always_on_top_check)
        self.window_opacity_spin = QSpinBox()
        self.window_opacity_spin.setRange(50, 100)
        self.window_opacity_spin.setSuffix("%")
        display_form.addRow("창 불투명도", self.window_opacity_spin)
        self.ui_scale_spin = QSpinBox()
        self.ui_scale_spin.setRange(75, 200)
        self.ui_scale_spin.setSingleStep(5)
        self.ui_scale_spin.setSuffix("%")
        display_form.addRow("UI 배율", self.ui_scale_spin)
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(True)
        display_form.addRow("글꼴", self.font_combo)
        background_row = QHBoxLayout()
        self.background_edit = QLineEdit()
        self.background_edit.setReadOnly(True)
        self.background_edit.setPlaceholderText("사용 안 함")
        background_row.addWidget(self.background_edit, 1)
        background_button = QPushButton("선택...")
        background_button.clicked.connect(self._choose_background)
        background_row.addWidget(background_button)
        background_clear_button = QPushButton("해제")
        background_clear_button.clicked.connect(self.background_edit.clear)
        background_row.addWidget(background_clear_button)
        display_form.addRow("배경 이미지", background_row)
        self.quick_action_list = QListWidget()
        self.quick_action_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self.quick_action_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.quick_action_list.setMaximumHeight(180)
        display_form.addRow("빠른 실행 도구", self.quick_action_list)
        display_note = QLabel(
            "간략하게 모드는 표지를 생략하고 상태·제목·핵심 정보와 진행률을 한 줄 카드에 표시합니다."
        )
        display_note.setObjectName("mutedLabel")
        display_note.setWordWrap(True)
        display_form.addRow("", display_note)
        self.tabs.addTab(display_page, self.strings["settings.tab.display"])

        advanced_page = QWidget()
        advanced_page.setObjectName("settingsPage")
        advanced_form = QFormLayout(advanced_page)
        self.log_max_spin = QSpinBox()
        self.log_max_spin.setRange(1, 100)
        self.log_max_spin.setSuffix(" MiB")
        advanced_form.addRow("로그 파일 최대 크기", self.log_max_spin)
        self.log_backups_spin = QSpinBox()
        self.log_backups_spin.setRange(1, 10)
        self.log_backups_spin.setSuffix("개")
        advanced_form.addRow("이전 로그 보존", self.log_backups_spin)
        self.notification_sound_check = QCheckBox(
            "완료·오류 알림에 Windows 시스템 알림음 재생"
        )
        advanced_form.addRow("알림음", self.notification_sound_check)
        self.notification_message_box_check = QCheckBox(
            "트레이 사용 여부와 관계없이 비차단 메시지 상자 표시"
        )
        advanced_form.addRow("메시지 상자", self.notification_message_box_check)
        notification_preview_button = QPushButton("완료 알림 미리보기")
        notification_preview_button.setToolTip(
            "CLI: notifications preview --kind complete --json"
        )
        notification_preview_button.clicked.connect(
            lambda: owner.preview_notification(
                "complete", "알림 미리보기 작품", ""
            )
        )
        advanced_form.addRow("알림 확인", notification_preview_button)
        self.image_resize_width_spin = QSpinBox()
        self.image_resize_width_spin.setRange(0, 16384)
        self.image_resize_width_spin.setSingleStep(64)
        self.image_resize_width_spin.setSpecialValueText("제한 없음")
        self.image_resize_width_spin.setSuffix(" px")
        advanced_form.addRow("이미지 최대 너비", self.image_resize_width_spin)
        self.image_resize_height_spin = QSpinBox()
        self.image_resize_height_spin.setRange(0, 16384)
        self.image_resize_height_spin.setSingleStep(64)
        self.image_resize_height_spin.setSpecialValueText("제한 없음")
        self.image_resize_height_spin.setSuffix(" px")
        advanced_form.addRow("이미지 최대 높이", self.image_resize_height_spin)
        self.image_excluded_extensions_edit = QLineEdit()
        self.image_excluded_extensions_edit.setPlaceholderText(
            "사용 안 함 · 예: gif, bmp, avif"
        )
        advanced_form.addRow(
            "변환 제외 유형", self.image_excluded_extensions_edit
        )
        self.archive_viewer_mode_combo = QComboBox()
        self.archive_viewer_mode_combo.addItem(
            "Windows 기본 연결 프로그램", "system"
        )
        self.archive_viewer_mode_combo.addItem("지정한 프로그램", "custom")
        self.archive_viewer_mode_combo.setToolTip(
            "CLI: archive-viewer set --mode system|custom"
        )
        self.archive_viewer_mode_combo.currentIndexChanged.connect(
            self._update_archive_viewer_controls
        )
        advanced_form.addRow("압축 파일 열기", self.archive_viewer_mode_combo)
        archive_viewer_row = QHBoxLayout()
        self.archive_viewer_path_edit = QLineEdit()
        self.archive_viewer_path_edit.setReadOnly(True)
        self.archive_viewer_path_edit.setPlaceholderText("지정한 프로그램 사용 안 함")
        self.archive_viewer_path_edit.textChanged.connect(
            lambda _text: self._update_archive_viewer_controls()
        )
        archive_viewer_row.addWidget(self.archive_viewer_path_edit, 1)
        self.archive_viewer_choose_button = QPushButton("선택...")
        self.archive_viewer_choose_button.setToolTip(
            "CLI: archive-viewer set --mode custom --path EXE"
        )
        self.archive_viewer_choose_button.clicked.connect(
            self._choose_archive_viewer
        )
        archive_viewer_row.addWidget(self.archive_viewer_choose_button)
        self.archive_viewer_clear_button = QPushButton("해제")
        self.archive_viewer_clear_button.setToolTip(
            "CLI: archive-viewer set --mode system --clear-path"
        )
        self.archive_viewer_clear_button.clicked.connect(
            self._clear_archive_viewer
        )
        archive_viewer_row.addWidget(self.archive_viewer_clear_button)
        advanced_form.addRow("지정 프로그램", archive_viewer_row)
        self.autosave_interval_spin = QSpinBox()
        self.autosave_interval_spin.setRange(1, 300)
        self.autosave_interval_spin.setSuffix("초")
        self.autosave_interval_spin.setToolTip(
            "CLI: persistence set --autosave-seconds N"
        )
        advanced_form.addRow("자동 저장 주기", self.autosave_interval_spin)
        self.startup_recovery_check = QCheckBox(
            "시작할 때 대기·실행 중·일시정지 기록을 중지됨으로 복구"
        )
        self.startup_recovery_check.setToolTip(
            "CLI: persistence set --startup-recovery on|off"
        )
        advanced_form.addRow("불완전 작업 복구", self.startup_recovery_check)
        recovery_preview_button = QPushButton("불완전 기록 확인...")
        recovery_preview_button.setToolTip("CLI: persistence recover --show-gui")
        recovery_preview_button.clicked.connect(owner.show_recovery_dialog)
        advanced_form.addRow("복구 확인", recovery_preview_button)
        self.list_page_size_spin = QSpinBox()
        self.list_page_size_spin.setRange(25, 1000)
        self.list_page_size_spin.setSingleStep(25)
        self.list_page_size_spin.setSuffix("개")
        self.list_page_size_spin.setToolTip(
            "CLI: list-performance set --page-size N"
        )
        advanced_form.addRow("목록 페이지 크기", self.list_page_size_spin)
        self.list_loaded_limit_spin = QSpinBox()
        self.list_loaded_limit_spin.setRange(100, 5000)
        self.list_loaded_limit_spin.setSingleStep(100)
        self.list_loaded_limit_spin.setSuffix("개")
        self.list_loaded_limit_spin.setToolTip(
            "CLI: list-performance set --loaded-limit N"
        )
        advanced_form.addRow("메모리 내 작품 상한", self.list_loaded_limit_spin)
        self.list_scroll_lines_spin = QSpinBox()
        self.list_scroll_lines_spin.setRange(1, 20)
        self.list_scroll_lines_spin.setSuffix("단계")
        self.list_scroll_lines_spin.setToolTip(
            "CLI: list-performance set --scroll-lines N"
        )
        advanced_form.addRow("목록 스크롤 속도", self.list_scroll_lines_spin)
        self.list_lazy_loading_check = QCheckBox(
            "목록 하단에 도달할 때 다음 SQLite 페이지 로딩"
        )
        self.list_lazy_loading_check.setToolTip(
            "CLI: list-performance set --lazy-loading on|off"
        )
        advanced_form.addRow("지연 로딩", self.list_lazy_loading_check)
        self.low_spec_mode_check = QCheckBox(
            "페이지 100·로딩 500·썸네일 숨김·작은 캐시 적용"
        )
        self.low_spec_mode_check.setToolTip(
            "CLI: list-performance set --low-spec on|off"
        )
        advanced_form.addRow("저사양 모드", self.low_spec_mode_check)
        self.prevent_sleep_check = QCheckBox(
            "다운로드가 실행되는 동안 Windows 시스템 절전만 방지"
        )
        self.prevent_sleep_check.setToolTip(
            "CLI: sleep-prevention set --state on|off"
        )
        advanced_form.addRow("다운로드 중 절전 방지", self.prevent_sleep_check)
        self.sleep_prevention_status_label = QLabel("")
        self.sleep_prevention_status_label.setObjectName("mutedLabel")
        self.sleep_prevention_status_label.setWordWrap(True)
        advanced_form.addRow("현재 전원 요청", self.sleep_prevention_status_label)
        self.pdf_generation_check = QCheckBox(
            "다운로드 완료 후 새롭거나 변경된 회차를 _pdf 폴더에 자동 생성"
        )
        self.pdf_generation_check.setToolTip(
            "CLI: pdf set --automatic on|off"
        )
        advanced_form.addRow("PDF 자동 생성", self.pdf_generation_check)
        self.memory_display_check = QCheckBox(
            "상태 표시줄에 시스템 사용률과 앱·자식 작업 메모리 표시"
        )
        self.memory_display_check.setToolTip(
            "CLI: memory set --display on|off"
        )
        advanced_form.addRow("메모리 사용량 표시", self.memory_display_check)
        self.local_api_check = QCheckBox(
            "127.0.0.1에서만 임시 Bearer 토큰으로 제어 API 실행"
        )
        self.local_api_check.setToolTip(
            "CLI: local-api set --state on|off"
        )
        advanced_form.addRow("로컬 HTTP API", self.local_api_check)
        self.local_api_port_spin = QSpinBox()
        self.local_api_port_spin.setRange(1024, 65_535)
        self.local_api_port_spin.setToolTip(
            "CLI: local-api set --port N"
        )
        advanced_form.addRow("로컬 API 포트", self.local_api_port_spin)
        local_api_status_row = QHBoxLayout()
        self.local_api_status_label = QLabel("")
        self.local_api_status_label.setObjectName("mutedLabel")
        self.local_api_status_label.setWordWrap(True)
        local_api_status_row.addWidget(self.local_api_status_label, 1)
        self.local_api_copy_token_button = QPushButton("토큰 복사")
        self.local_api_copy_token_button.setToolTip(
            "CLI: local-api token --copy --yes"
        )
        self.local_api_copy_token_button.clicked.connect(self._copy_local_api_token)
        local_api_status_row.addWidget(self.local_api_copy_token_button)
        advanced_form.addRow("로컬 API 상태", local_api_status_row)
        self.local_api_check.toggled.connect(self.local_api_port_spin.setEnabled)
        advanced_note = QLabel(
            "로그는 최대 크기를 넘으면 순환 보존합니다. 알림 미리보기는 현재 저장된 설정을 "
            "사용하며 메시지 상자는 작업을 막지 않습니다. 압축 파일 설정은 이 앱에서 여는 "
            "방법만 정하며 Windows 시스템 연결은 변경하지 않습니다. 자동 저장은 변경된 작업만 "
            "묶어서 저장하고 복구는 다운로드 파일을 수정하지 않습니다. 저사양 모드는 원래 "
            "설정값을 지우지 않고 실행 중 유효 상한과 썸네일 비용만 낮춥니다. 절전 방지는 "
            "화면을 계속 켜지 않고 실제 다운로드가 실행되는 동안에만 시스템 절전을 막습니다. "
            "PDF는 회차별로 별도 생성하며 원본 이미지를 변경하거나 삭제하지 않습니다. "
            "메모리 표시는 읽기 전용이며 앱과 자식 작업을 시스템 전체 사용률과 구분합니다. "
            "로컬 API는 외부 주소에 바인딩하지 않고 시작할 때마다 새 토큰을 만듭니다."
        )
        advanced_note.setObjectName("mutedLabel")
        advanced_note.setWordWrap(True)
        advanced_form.addRow("", advanced_note)
        self.advanced_scroll = QScrollArea()
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.advanced_scroll.setWidget(advanced_page)
        self.tabs.addTab(
            self.advanced_scroll, self.strings["settings.tab.advanced"]
        )

        provider_page = QWidget()
        provider_page.setObjectName("settingsPage")
        provider_form = QFormLayout(provider_page)
        toki_status = QLabel("사용 가능 · Newtoki / Manatoki / Booktoki 내장")
        toki_status.setWordWrap(True)
        provider_form.addRow(self.strings["provider.toki"], toki_status)
        hitomi_capability = hitomi_provider_capabilities()
        hitomi_status = QLabel(
            "URL·ID 및 갤러리 메타데이터 사용 가능 · 이미지 다운로드 엔진 준비 중"
            if hitomi_capability["referenceInspection"]
            else "선택 기능 · 분석기 사용 불가"
        )
        hitomi_status.setWordWrap(True)
        provider_form.addRow(self.strings["provider.hitomi"], hitomi_status)
        self.hitomi_server_mode_combo = QComboBox()
        self.hitomi_server_mode_combo.addItem("자동 · 우선순위 사용", "auto")
        self.hitomi_server_mode_combo.addItem("수동 · 지정 서버만 사용", "manual")
        self.hitomi_server_mode_combo.setToolTip(
            "CLI: hitomi server set --mode auto|manual --json"
        )
        self.hitomi_server_mode_combo.currentIndexChanged.connect(
            self._update_hitomi_server_controls
        )
        provider_form.addRow("서버 방식", self.hitomi_server_mode_combo)
        self.hitomi_manual_server_combo = QComboBox()
        for server in HITOMI_SERVER_CATALOG:
            self.hitomi_manual_server_combo.addItem(
                str(server["label"]), str(server["id"])
            )
        self.hitomi_manual_server_combo.setToolTip(
            "CLI: hitomi server set --mode manual --manual-server SERVER --json"
        )
        provider_form.addRow("수동 서버", self.hitomi_manual_server_combo)
        self.hitomi_server_priority_list = QListWidget()
        self.hitomi_server_priority_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )
        self.hitomi_server_priority_list.setMaximumHeight(102)
        self.hitomi_server_priority_list.setToolTip(
            "드래그로 정렬 · CLI: hitomi server set --priority hitomi,exhentai,ehentai --json"
        )
        provider_form.addRow("자동 우선순위", self.hitomi_server_priority_list)
        priority_buttons = QHBoxLayout()
        priority_up = QPushButton("위로")
        priority_down = QPushButton("아래로")
        priority_up.setToolTip("선택 서버를 위로 이동 · CLI에서는 --priority로 전체 순서 지정")
        priority_down.setToolTip("선택 서버를 아래로 이동 · CLI에서는 --priority로 전체 순서 지정")
        priority_up.clicked.connect(lambda: self._move_hitomi_priority(-1))
        priority_down.clicked.connect(lambda: self._move_hitomi_priority(1))
        priority_buttons.addWidget(priority_up)
        priority_buttons.addWidget(priority_down)
        priority_buttons.addStretch(1)
        provider_form.addRow("", priority_buttons)
        self.hitomi_metadata_mode_combo = QComboBox()
        self.hitomi_metadata_mode_combo.addItem("자동 · 실패 시 계속", "auto")
        self.hitomi_metadata_mode_combo.addItem("필수 · 실패 시 중단", "required")
        self.hitomi_metadata_mode_combo.addItem("사용 안 함", "disabled")
        self.hitomi_metadata_mode_combo.setToolTip(
            "CLI: hitomi metadata set --mode auto|required|disabled --json"
        )
        provider_form.addRow("갤러리 정보", self.hitomi_metadata_mode_combo)
        self.hitomi_metadata_file_mode_combo = QComboBox()
        self.hitomi_metadata_file_mode_combo.addItem("공통 metadata.json", "metadata_json")
        self.hitomi_metadata_file_mode_combo.addItem("사람이 읽는 info.txt", "info_txt")
        self.hitomi_metadata_file_mode_combo.addItem("둘 다 생성", "both")
        self.hitomi_metadata_file_mode_combo.addItem("생성 안 함", "disabled")
        self.hitomi_metadata_file_mode_combo.setToolTip(
            "CLI: hitomi metadata-files set --mode metadata_json|info_txt|both|disabled --json"
        )
        provider_form.addRow("메타데이터 파일", self.hitomi_metadata_file_mode_combo)
        self.hitomi_filename_mode_combo = QComboBox()
        self.hitomi_filename_mode_combo.addItem("숫자 + 원본 · 0001_원본.jpg", "number_original")
        self.hitomi_filename_mode_combo.addItem("숫자만 · 0001.jpg", "number")
        self.hitomi_filename_mode_combo.addItem("원본 유지 · 원본.jpg", "original")
        self.hitomi_filename_mode_combo.setToolTip(
            "CLI: hitomi filenames set --mode original|number|number_original --json"
        )
        provider_form.addRow("이미지 파일명", self.hitomi_filename_mode_combo)
        self.hitomi_original_images_check = QCheckBox(
            "가능하면 최적화 변형 대신 공급자의 원본 이미지 사용"
        )
        self.hitomi_original_images_check.setToolTip(
            "CLI: hitomi images set --original on|off --json"
        )
        provider_form.addRow("이미지 품질", self.hitomi_original_images_check)
        self.hitomi_excluded_tags_edit = QPlainTextEdit()
        self.hitomi_excluded_tags_edit.setMaximumHeight(76)
        self.hitomi_excluded_tags_edit.setPlaceholderText(
            "예: guro, female:full color · 비워두면 제외 안 함"
        )
        self.hitomi_excluded_tags_edit.setToolTip(
            "쉼표 또는 세미콜론으로 구분 · CLI: hitomi tags set --tags TAGS --json"
        )
        provider_form.addRow("제외 태그", self.hitomi_excluded_tags_edit)
        self.hitomi_prefer_japanese_title_check = QCheckBox(
            "일본어 제목이 있으면 우선 사용하고, 없으면 기존 제목 사용"
        )
        self.hitomi_prefer_japanese_title_check.setToolTip(
            "CLI: hitomi title set --prefer-japanese on|off --json"
        )
        provider_form.addRow("제목 선택", self.hitomi_prefer_japanese_title_check)
        hitomi_inspector_button = QPushButton("Hitomi URL / ID 분석...")
        hitomi_inspector_button.setToolTip(
            "CLI: hitomi inspect --input URL_OR_ID --show-gui --json"
        )
        hitomi_inspector_button.clicked.connect(owner.show_hitomi_inspector)
        provider_form.addRow("작품 식별자", hitomi_inspector_button)
        hitomi_metadata_button = QPushButton("갤러리 메타데이터...")
        hitomi_metadata_button.setToolTip(
            "CLI: hitomi metadata show --input URL_OR_ID --json"
        )
        hitomi_metadata_button.clicked.connect(owner.show_hitomi_metadata)
        provider_form.addRow("메타데이터", hitomi_metadata_button)
        youtube_status = QLabel("선택 기능 · yt-dlp와 FFmpeg 상태는 진단에서 확인")
        youtube_status.setWordWrap(True)
        provider_form.addRow(self.strings["provider.youtube"], youtube_status)
        self.youtube_format_mode_combo = QComboBox()
        for label, value in (
            ("영상 + 오디오 · 가능한 경우 병합", "video_audio"),
            ("영상만 · 오디오 제외", "video_only"),
            ("오디오만", "audio_only"),
        ):
            self.youtube_format_mode_combo.addItem(label, value)
        self.youtube_format_mode_combo.setToolTip(
            "CLI: youtube format set --mode video_audio|video_only|audio_only --json"
        )
        provider_form.addRow("YouTube 형식", self.youtube_format_mode_combo)
        self.youtube_max_height_combo = QComboBox()
        for height in YOUTUBE_MAX_HEIGHTS:
            self.youtube_max_height_combo.addItem(
                "최고 화질" if height == 0 else f"최대 {height}p", height
            )
        self.youtube_max_height_combo.setToolTip(
            "CLI: youtube format set --max-height 0|2160|1440|1080|720|480|360|240|144 --json"
        )
        provider_form.addRow("최대 해상도", self.youtube_max_height_combo)
        self.youtube_container_combo = QComboBox()
        for value in YOUTUBE_CONTAINERS:
            self.youtube_container_combo.addItem(
                "자동 · 원본/병합 결과 유지" if value == "auto" else value.upper(), value
            )
        self.youtube_container_combo.setToolTip(
            "CLI: youtube format set --container auto|mp4|mkv|webm --json"
        )
        provider_form.addRow("출력 컨테이너", self.youtube_container_combo)
        self.youtube_video_codec_combo = QComboBox()
        for value in YOUTUBE_VIDEO_CODECS:
            self.youtube_video_codec_combo.addItem(
                "자동 · 품질 우선" if value == "auto" else value.upper(), value
            )
        self.youtube_video_codec_combo.setToolTip(
            "CLI: youtube format set --video-codec auto|h264|h265|vp9|av1 --json"
        )
        provider_form.addRow("비디오 코덱 선호", self.youtube_video_codec_combo)
        self.youtube_audio_codec_combo = QComboBox()
        for value in YOUTUBE_AUDIO_CODECS:
            self.youtube_audio_codec_combo.addItem(
                "자동 · 품질 우선" if value == "auto" else value.upper(), value
            )
        self.youtube_audio_codec_combo.setToolTip(
            "CLI: youtube format set --audio-codec auto|aac|opus --json"
        )
        provider_form.addRow("오디오 코덱 선호", self.youtube_audio_codec_combo)
        self.youtube_filename_template_edit = QLineEdit()
        self.youtube_filename_template_edit.setToolTip(
            "CLI: youtube filename set --template TEMPLATE --json"
        )
        self.youtube_filename_preview_label = QLabel("")
        self.youtube_filename_preview_label.setObjectName("mutedLabel")
        self.youtube_filename_preview_label.setWordWrap(True)
        self.youtube_filename_template_edit.textChanged.connect(
            self._update_youtube_filename_preview
        )
        provider_form.addRow("파일명 템플릿", self.youtube_filename_template_edit)
        provider_form.addRow("파일명 미리보기", self.youtube_filename_preview_label)
        self.youtube_languages_edit = QLineEdit()
        self.youtube_languages_edit.setPlaceholderText("ko, en, ja")
        self.youtube_languages_edit.setToolTip("CLI: youtube tracks set --languages ko,en,ja --json")
        provider_form.addRow("선호 언어", self.youtube_languages_edit)
        self.youtube_subtitle_mode_combo = QComboBox()
        subtitle_labels = {
            "none": "자막 받지 않음",
            "manual": "제작 자막",
            "manual_auto": "제작 + 자동 자막",
        }
        for value in YOUTUBE_SUBTITLE_MODES:
            self.youtube_subtitle_mode_combo.addItem(subtitle_labels[value], value)
        provider_form.addRow("자막", self.youtube_subtitle_mode_combo)
        self.youtube_subtitle_format_combo = QComboBox()
        for value in YOUTUBE_SUBTITLE_FORMATS:
            self.youtube_subtitle_format_combo.addItem(value.upper(), value)
        provider_form.addRow("자막 형식", self.youtube_subtitle_format_combo)
        self.youtube_embed_subtitles_check = QCheckBox("지원 컨테이너에 자막 포함")
        provider_form.addRow("자막 포함", self.youtube_embed_subtitles_check)
        self.youtube_audio_track_mode_combo = QComboBox()
        audio_track_labels = {
            "preferred_single": "선호 언어의 최상 트랙 하나",
            "all": "제공되는 모든 오디오 트랙",
        }
        for value in YOUTUBE_AUDIO_TRACK_MODES:
            self.youtube_audio_track_mode_combo.addItem(audio_track_labels[value], value)
        provider_form.addRow("오디오 트랙", self.youtube_audio_track_mode_combo)
        self.youtube_write_thumbnail_check = QCheckBox("대표 썸네일을 별도 파일로 저장")
        self.youtube_write_thumbnail_check.setToolTip(
            "CLI: youtube metadata set --write-thumbnail on|off --json"
        )
        provider_form.addRow("썸네일 파일", self.youtube_write_thumbnail_check)
        self.youtube_embed_thumbnail_check = QCheckBox("지원 미디어에 표지로 포함")
        self.youtube_embed_thumbnail_check.setToolTip(
            "CLI: youtube metadata set --embed-thumbnail on|off --json"
        )
        provider_form.addRow("썸네일 포함", self.youtube_embed_thumbnail_check)
        self.youtube_write_info_json_check = QCheckBox("정리된 .info.json 저장")
        self.youtube_write_info_json_check.setToolTip(
            "개인 정보가 포함될 수 있습니다. CLI: youtube metadata set --write-info-json on|off --json"
        )
        provider_form.addRow("정보 JSON", self.youtube_write_info_json_check)
        self.youtube_write_description_check = QCheckBox("영상 설명을 .description으로 저장")
        self.youtube_write_description_check.setToolTip(
            "CLI: youtube metadata set --write-description on|off --json"
        )
        provider_form.addRow("설명 파일", self.youtube_write_description_check)
        self.youtube_embed_metadata_check = QCheckBox("제목·업로더 등 미디어 태그 포함")
        self.youtube_embed_metadata_check.setToolTip(
            "CLI: youtube metadata set --embed-metadata on|off --json"
        )
        provider_form.addRow("메타데이터 포함", self.youtube_embed_metadata_check)
        self.youtube_metadata_privacy_note = QLabel(
            ".info.json에는 개인 정보와 추출기가 즉시 제공하는 댓글이 포함될 수 있습니다. "
            "댓글 수집은 별도로 요청하지 않고 재생목록 메타파일도 만들지 않습니다."
        )
        self.youtube_metadata_privacy_note.setObjectName("mutedLabel")
        self.youtube_metadata_privacy_note.setWordWrap(True)
        provider_form.addRow("", self.youtube_metadata_privacy_note)
        self.youtube_collection_order_combo = QComboBox()
        collection_labels = {
            "site": "사이트 기본 순서",
            "reverse": "역순 · 전체 목록 확인 필요",
        }
        for value in YOUTUBE_COLLECTION_ORDERS:
            self.youtube_collection_order_combo.addItem(collection_labels[value], value)
        self.youtube_collection_order_combo.setToolTip(
            "CLI: youtube collection set --order site|reverse --json"
        )
        provider_form.addRow("채널/재생목록 순서", self.youtube_collection_order_combo)
        self.youtube_collection_note = QLabel(
            "개별 영상+재생목록 주소는 영상 한 편만 처리합니다. 채널 탭 주소는 해당 탭 범위를 "
            "유지하며, 역순은 다운로드 전에 전체 목록을 확인해야 합니다."
        )
        self.youtube_collection_note.setObjectName("mutedLabel")
        self.youtube_collection_note.setWordWrap(True)
        provider_form.addRow("", self.youtube_collection_note)
        dependency_button = QPushButton("의존성 진단 열기")
        dependency_button.clicked.connect(owner.show_dependency_diagnostics)
        provider_form.addRow("설치 상태", dependency_button)
        embedded_capability = embedded_browser_capabilities()
        embedded_button = QPushButton("메모리 전용 내장 브라우저...")
        embedded_button.setToolTip("CLI: embedded-browser manage --show-gui")
        embedded_button.clicked.connect(lambda: owner.show_embedded_browser())
        embedded_button.setEnabled(bool(embedded_capability["available"]))
        provider_form.addRow("선택형 브라우저", embedded_button)
        credential = credential_store_status()
        credential_label = QLabel(
            "Windows 보안 저장소 사용 가능"
            if credential["available"]
            else "보안 저장소 선택 기능 미설치"
        )
        provider_form.addRow("쿠키 보안", credential_label)
        cookie_button = QPushButton("쿠키 관리...")
        cookie_button.clicked.connect(owner.show_cookie_manager)
        cookie_button.setEnabled(bool(credential["available"]))
        provider_form.addRow("공급자 쿠키", cookie_button)
        provider_note = QLabel(
            "선택 공급자는 기본 다운로드와 분리됩니다. Hitomi 분석은 로컬에서만 동작하고 "
            "ExHentai 토큰 원문을 결과·로그·설정에 저장하지 않습니다. 다운로드와 메타데이터 "
            "연결은 이후 단계에서 별도로 활성화합니다."
        )
        provider_note.setObjectName("mutedLabel")
        provider_note.setWordWrap(True)
        provider_form.addRow("", provider_note)
        self.provider_scroll = QScrollArea()
        self.provider_scroll.setWidgetResizable(True)
        self.provider_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.provider_scroll.setWidget(provider_page)
        self.tabs.addTab(self.provider_scroll, self.strings["settings.tab.provider"])

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장 후 닫기")
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(
            "기본값"
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._apply_without_closing
        )
        buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._load_defaults)
        layout.addWidget(buttons)
        self._load_values(settings_snapshot(owner.config))

    def set_search_query(self, query: str) -> None:
        self.search_edit.setText(str(query or ""))

    @classmethod
    def matching_tab_indexes(cls, query: str) -> list[int]:
        words = [word.casefold() for word in str(query).split() if word.strip()]
        if not words:
            return list(range(len(cls.TAB_KEYS)))
        return [
            index
            for index, terms in enumerate(cls.TAB_SEARCH_TERMS)
            if all(word in terms.casefold() for word in words)
        ]

    def _filter_tabs(self, query: str) -> None:
        words = [word for word in str(query).split() if word.strip()]
        matches = self.matching_tab_indexes(query)
        for index in range(self.tabs.count()):
            visible = index in matches
            self.tabs.setTabVisible(index, visible)
        if words and not matches:
            for index in range(self.tabs.count()):
                self.tabs.setTabVisible(index, True)
            self.search_status.setText("검색 결과가 없어 전체 설정을 표시합니다.")
            return
        self.search_status.setText(
            f"검색 결과: {len(matches)}개 페이지" if words else ""
        )
        if matches and self.tabs.currentIndex() not in matches:
            self.tabs.setCurrentIndex(matches[0])
        if 3 in matches and words:
            QTimer.singleShot(0, lambda: self._scroll_advanced_search(query))
        if 4 in matches and words:
            QTimer.singleShot(100, lambda: self._scroll_provider_search(query))

    def _scroll_provider_search(self, query: str) -> None:
        lowered = str(query or "").casefold()
        if "파일명" in lowered:
            self.provider_scroll.ensureWidgetVisible(
                self.youtube_filename_template_edit, 20, 40
            )
        elif any(word in lowered for word in ("자막", "언어", "오디오 트랙")):
            self.provider_scroll.ensureWidgetVisible(
                self.youtube_audio_track_mode_combo, 20, 40
            )
        elif any(word in lowered for word in ("썸네일", "정보 json", "설명", "메타데이터 포함")):
            self.provider_scroll.ensureWidgetVisible(
                self.youtube_metadata_privacy_note, 20, 40
            )
        elif any(word in lowered for word in ("채널", "재생목록", "역순")):
            self.provider_scroll.ensureWidgetVisible(
                self.youtube_collection_note, 20, 40
            )
        elif any(
            word in lowered
            for word in ("youtube", "yt-dlp", "ffmpeg", "형식", "해상도", "코덱", "컨테이너")
        ):
            self.provider_scroll.ensureWidgetVisible(
                self.youtube_audio_codec_combo, 20, 40
            )

    def _youtube_filename_preview_snapshot(self) -> dict[str, Any]:
        try:
            return preview_youtube_filename(self.youtube_filename_template_edit.text())
        except ValueError as error:
            return {"ok": False, "error": str(error), "networkRequested": False}

    def _update_youtube_filename_preview(self, _value: str = "") -> None:
        preview = self._youtube_filename_preview_snapshot()
        self.youtube_filename_preview_label.setText(
            preview.get("preview") if preview.get("ok") else f"사용할 수 없음: {preview['error']}"
        )

    def _scroll_advanced_search(self, query: str) -> None:
        lowered = str(query or "").casefold()
        targets = (
            (("토큰", "상태"), self.local_api_status_label),
            (("http", "HTTP", "api", "API", "로컬", "포트"), self.local_api_check),
            (("메모리 사용량", "ram", "RAM", "자식 프로세스"), self.memory_display_check),
            (("pdf", "PDF", "회차"), self.pdf_generation_check),
            (("절전", "전원"), self.prevent_sleep_check),
            (("저사양",), self.low_spec_mode_check),
            (("지연",), self.list_lazy_loading_check),
            (("스크롤",), self.list_scroll_lines_spin),
            (("상한",), self.list_loaded_limit_spin),
            (("페이지",), self.list_page_size_spin),
            (("자동", "복구"), self.autosave_interval_spin),
            (("압축", "연결", "뷰어"), self.archive_viewer_mode_combo),
            (("이미지", "리사이즈", "제외"), self.image_resize_width_spin),
            (("알림", "소리", "메시지"), self.notification_sound_check),
        )
        target = next(
            (
                widget
                for words, widget in targets
                if any(word.casefold() in lowered for word in words)
            ),
            None,
        )
        if target is not None:
            self.advanced_scroll.ensureWidgetVisible(target, 20, 40)

    def _update_sleep_prevention_status(self) -> None:
        snapshot_method = getattr(self.owner, "sleep_prevention_status_snapshot", None)
        snapshot = snapshot_method() if callable(snapshot_method) else {}
        if snapshot.get("active"):
            text = f"활성 · 실행 다운로드 {int(snapshot.get('activeDownloads') or 0)}개"
        elif not snapshot.get("available", os.name == "nt"):
            text = "현재 운영체제에서는 Windows 전원 요청을 사용할 수 없습니다."
        elif snapshot.get("lastError"):
            text = f"요청 오류 · {snapshot['lastError']}"
        else:
            text = "유휴 · 다운로드가 시작될 때만 활성화됩니다."
        self.sleep_prevention_status_label.setText(text)

    def _update_local_api_status(self) -> None:
        snapshot_method = getattr(self.owner, "local_api_status_snapshot", None)
        snapshot = snapshot_method() if callable(snapshot_method) else {}
        if snapshot.get("running"):
            text = f"실행 중 · {snapshot.get('baseUrl')} · 토큰 {snapshot.get('tokenHint')}"
        elif snapshot.get("error"):
            text = f"시작 오류 · {snapshot['error']}"
        else:
            text = "중지됨 · 외부 주소에는 바인딩하지 않습니다."
        self.local_api_status_label.setText(text)
        self.local_api_copy_token_button.setEnabled(bool(snapshot.get("tokenPresent")))

    def _copy_local_api_token(self) -> None:
        try:
            self.owner.copy_local_api_token()
        except RuntimeError as error:
            QMessageBox.warning(self, "로컬 API 토큰", str(error))

    def state_snapshot(self) -> dict[str, Any]:
        index = self.tabs.currentIndex()
        return {
            "open": self.isVisible(),
            "tab": self.TAB_KEYS[index] if 0 <= index < len(self.TAB_KEYS) else "",
            "search": self.search_edit.text(),
            "visibleTabs": [
                self.TAB_KEYS[index]
                for index in range(self.tabs.count())
                if self.tabs.isTabVisible(index)
            ],
            "hitomiServer": {
                "mode": str(self.hitomi_server_mode_combo.currentData() or "auto"),
                "manualServer": str(
                    self.hitomi_manual_server_combo.currentData() or "hitomi"
                ),
                "priority": self._hitomi_server_priority(),
            },
            "hitomiMetadataMode": str(
                self.hitomi_metadata_mode_combo.currentData() or "auto"
            ),
            "hitomiMetadataFileMode": str(
                self.hitomi_metadata_file_mode_combo.currentData() or "metadata_json"
            ),
            "hitomiFilenameMode": str(
                self.hitomi_filename_mode_combo.currentData() or "number_original"
            ),
            "hitomiUseOriginalImages": self.hitomi_original_images_check.isChecked(),
            "hitomiExcludedTags": [
                part.strip()
                for part in re.split(
                    r"[,;\n]", self.hitomi_excluded_tags_edit.toPlainText()
                )
                if part.strip()
            ],
            "hitomiPreferJapaneseTitle": self.hitomi_prefer_japanese_title_check.isChecked(),
            "youtubeFormat": {
                "mode": str(self.youtube_format_mode_combo.currentData() or "video_audio"),
                "maxHeight": int(self.youtube_max_height_combo.currentData() or 0),
                "container": str(self.youtube_container_combo.currentData() or "auto"),
                "videoCodec": str(self.youtube_video_codec_combo.currentData() or "auto"),
                "audioCodec": str(self.youtube_audio_codec_combo.currentData() or "auto"),
                "networkRequested": False,
            },
            "youtubeFilename": self._youtube_filename_preview_snapshot(),
            "youtubeTracks": {
                "languages": [part.strip() for part in self.youtube_languages_edit.text().split(",") if part.strip()],
                "subtitleMode": str(self.youtube_subtitle_mode_combo.currentData() or "none"),
                "subtitleFormat": str(self.youtube_subtitle_format_combo.currentData() or "best"),
                "embedSubtitles": self.youtube_embed_subtitles_check.isChecked(),
                "audioTrackMode": str(self.youtube_audio_track_mode_combo.currentData() or "preferred_single"),
                "networkRequested": False,
            },
            "youtubeMetadata": {
                "writeThumbnail": self.youtube_write_thumbnail_check.isChecked(),
                "embedThumbnail": self.youtube_embed_thumbnail_check.isChecked(),
                "writeInfoJson": self.youtube_write_info_json_check.isChecked(),
                "writeDescription": self.youtube_write_description_check.isChecked(),
                "embedMetadata": self.youtube_embed_metadata_check.isChecked(),
                "infoJsonMayContainPersonalInformation": self.youtube_write_info_json_check.isChecked(),
                "networkRequested": False,
            },
            "youtubeCollection": {
                "order": str(self.youtube_collection_order_combo.currentData() or "site"),
                "videoWithPlaylistPolicy": "single_video",
                "reverseRequiresFullCollectionScan": True,
                "networkRequested": False,
            },
        }

    def _load_values(self, values: dict[str, Any]) -> None:
        self.output_edit.setText(str(values["outputDir"]))
        language_index = self.language_combo.findData(str(values["uiLanguage"]))
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.folder_template_edit.setText(str(values["folderNameTemplate"]))
        self.show_browser_check.setChecked(bool(values["showBrowser"]))
        self.log_visible_check.setChecked(bool(values["logVisible"]))
        self.tray_enabled_check.setChecked(bool(values["trayEnabled"]))
        self.close_to_tray_check.setChecked(bool(values["closeToTray"]))
        self.minimize_to_tray_check.setChecked(bool(values["minimizeToTray"]))
        self.notify_complete_check.setChecked(bool(values["notifyOnComplete"]))
        self.notify_error_check.setChecked(bool(values["notifyOnError"]))
        completion_index = self.completion_action_combo.findData(
            str(values["completionAction"])
        )
        self.completion_action_combo.setCurrentIndex(max(0, completion_index))
        self.completion_countdown_spin.setValue(
            int(values["completionCountdownSeconds"])
        )
        self.clipboard_monitor_check.setChecked(bool(values["clipboardMonitor"]))
        self.work_spin.setValue(int(values["workConcurrency"]))
        self.image_spin.setValue(int(values["imageConcurrency"]))
        self.retry_count_spin.setValue(int(values["retryCount"]))
        self.retry_backoff_spin.setValue(int(values["retryBackoffSeconds"]))
        self.proxy_edit.setText(str(values["proxyUrl"]))
        self.speed_limit_spin.setValue(int(values["speedLimitKib"]))
        self.provider_policy_values = {
            key: dict(policy)
            for key, policy in values["providerPolicies"].items()
        }
        self._provider_current_key = str(
            self.provider_policy_combo.currentData() or "manatoki"
        )
        self._load_current_provider_policy()
        self.log_max_spin.setValue(int(values["logMaxMiB"]))
        self.log_backups_spin.setValue(int(values["logBackupCount"]))
        self.notification_sound_check.setChecked(
            str(values["notificationSound"]) == "system"
        )
        self.notification_message_box_check.setChecked(
            bool(values["notificationMessageBox"])
        )
        self.image_resize_width_spin.setValue(int(values["imageResizeMaxWidth"]))
        self.image_resize_height_spin.setValue(int(values["imageResizeMaxHeight"]))
        self.image_excluded_extensions_edit.setText(
            ", ".join(values["imageExcludedExtensions"])
        )
        archive_mode_index = self.archive_viewer_mode_combo.findData(
            str(values["archiveViewerMode"])
        )
        self.archive_viewer_mode_combo.setCurrentIndex(max(0, archive_mode_index))
        self.archive_viewer_path_edit.setText(str(values["archiveViewerPath"]))
        self._update_archive_viewer_controls()
        self.autosave_interval_spin.setValue(int(values["autosaveIntervalSeconds"]))
        self.startup_recovery_check.setChecked(
            bool(values["recoverInterruptedOnStartup"])
        )
        self.list_page_size_spin.setValue(int(values["listPageSize"]))
        self.list_loaded_limit_spin.setValue(int(values["listLoadedLimit"]))
        self.list_scroll_lines_spin.setValue(int(values["listScrollLines"]))
        self.list_lazy_loading_check.setChecked(bool(values["listLazyLoading"]))
        self.low_spec_mode_check.setChecked(bool(values["lowSpecMode"]))
        self.prevent_sleep_check.setChecked(
            bool(values["preventSleepDuringDownloads"])
        )
        self.pdf_generation_check.setChecked(bool(values["pdfGenerationEnabled"]))
        self.memory_display_check.setChecked(bool(values["memoryDisplayEnabled"]))
        self.local_api_check.setChecked(bool(values["localApiEnabled"]))
        self.local_api_port_spin.setValue(int(values["localApiPort"]))
        self.local_api_port_spin.setEnabled(self.local_api_check.isChecked())
        self._update_local_api_status()
        self._update_sleep_prevention_status()
        mode_index = self.hitomi_server_mode_combo.findData(
            str(values["hitomiServerMode"])
        )
        self.hitomi_server_mode_combo.setCurrentIndex(max(0, mode_index))
        manual_index = self.hitomi_manual_server_combo.findData(
            str(values["hitomiManualServer"])
        )
        self.hitomi_manual_server_combo.setCurrentIndex(max(0, manual_index))
        self._load_hitomi_server_priority(values["hitomiServerPriority"])
        self._update_hitomi_server_controls()
        metadata_index = self.hitomi_metadata_mode_combo.findData(
            str(values["hitomiMetadataMode"])
        )
        self.hitomi_metadata_mode_combo.setCurrentIndex(max(0, metadata_index))
        metadata_file_index = self.hitomi_metadata_file_mode_combo.findData(
            str(values["hitomiMetadataFileMode"])
        )
        self.hitomi_metadata_file_mode_combo.setCurrentIndex(
            max(0, metadata_file_index)
        )
        filename_index = self.hitomi_filename_mode_combo.findData(
            str(values["hitomiFilenameMode"])
        )
        self.hitomi_filename_mode_combo.setCurrentIndex(max(0, filename_index))
        self.hitomi_original_images_check.setChecked(
            bool(values["hitomiUseOriginalImages"])
        )
        self.hitomi_excluded_tags_edit.setPlainText(
            "\n".join(str(tag) for tag in values["hitomiExcludedTags"])
        )
        self.hitomi_prefer_japanese_title_check.setChecked(
            bool(values["hitomiPreferJapaneseTitle"])
        )
        for combo, value in (
            (self.youtube_format_mode_combo, values["youtubeFormatMode"]),
            (self.youtube_max_height_combo, values["youtubeMaxHeight"]),
            (self.youtube_container_combo, values["youtubeContainer"]),
            (self.youtube_video_codec_combo, values["youtubeVideoCodec"]),
            (self.youtube_audio_codec_combo, values["youtubeAudioCodec"]),
        ):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.youtube_filename_template_edit.setText(
            str(values["youtubeFilenameTemplate"])
        )
        self.youtube_languages_edit.setText(", ".join(values["youtubePreferredLanguages"]))
        for combo, value in (
            (self.youtube_subtitle_mode_combo, values["youtubeSubtitleMode"]),
            (self.youtube_subtitle_format_combo, values["youtubeSubtitleFormat"]),
            (self.youtube_audio_track_mode_combo, values["youtubeAudioTrackMode"]),
        ):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.youtube_embed_subtitles_check.setChecked(bool(values["youtubeEmbedSubtitles"]))
        self.youtube_write_thumbnail_check.setChecked(bool(values["youtubeWriteThumbnail"]))
        self.youtube_embed_thumbnail_check.setChecked(bool(values["youtubeEmbedThumbnail"]))
        self.youtube_write_info_json_check.setChecked(bool(values["youtubeWriteInfoJson"]))
        self.youtube_write_description_check.setChecked(bool(values["youtubeWriteDescription"]))
        self.youtube_embed_metadata_check.setChecked(bool(values["youtubeEmbedMetadata"]))
        self.youtube_collection_order_combo.setCurrentIndex(
            max(0, self.youtube_collection_order_combo.findData(values["youtubeCollectionOrder"]))
        )
        density_index = self.row_density_combo.findData(str(values["rowDensity"]))
        self.row_density_combo.setCurrentIndex(max(0, density_index))
        theme_index = self.theme_combo.findData(str(values["theme"]))
        self.theme_combo.setCurrentIndex(max(0, theme_index))
        view_index = self.list_view_mode_combo.findData(str(values["listViewMode"]))
        self.list_view_mode_combo.setCurrentIndex(max(0, view_index))
        self.thumbnails_visible_check.setChecked(bool(values["thumbnailsVisible"]))
        size_index = self.thumbnail_size_combo.findData(str(values["thumbnailSize"]))
        self.thumbnail_size_combo.setCurrentIndex(max(0, size_index))
        self.always_on_top_check.setChecked(bool(values["alwaysOnTop"]))
        self.window_opacity_spin.setValue(int(values["windowOpacity"]))
        self.ui_scale_spin.setValue(int(values["uiScale"]))
        self.font_combo.setCurrentFont(QFont(str(values["fontFamily"])))
        self.background_edit.setText(str(values["backgroundImage"]))
        self._load_quick_actions(values["quickActions"])
        self._update_folder_preview()

    def _update_folder_preview(self, _value: str = "") -> None:
        try:
            result = folder_name_template_preview(
                self.folder_template_edit.text(),
                output_dir=self.output_edit.text(),
            )
            collision = " · 기존 폴더 있음" if result["collision"] else ""
            self.folder_template_preview.setText(
                f"{result['preview']}{collision}\n기존 폴더는 자동 변경하지 않습니다."
            )
            self.folder_template_preview.setStyleSheet("")
        except ValueError as error:
            self.folder_template_preview.setText(f"사용할 수 없음: {error}")
            self.folder_template_preview.setStyleSheet("color: #d84a4a;")

    def _load_quick_actions(self, selected: list[str]) -> None:
        catalog = quick_action_catalog()
        by_id = {item["id"]: item for item in catalog}
        ordered_ids = [action_id for action_id in selected if action_id in by_id]
        ordered_ids.extend(
            item["id"] for item in catalog if item["id"] not in ordered_ids
        )
        self.quick_action_list.clear()
        for action_id in ordered_ids:
            item = QListWidgetItem(by_id[action_id]["label"])
            item.setData(Qt.ItemDataRole.UserRole, action_id)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if action_id in selected
                else Qt.CheckState.Unchecked
            )
            self.quick_action_list.addItem(item)

    def _load_hitomi_server_priority(self, priority: list[str]) -> None:
        catalog = {str(item["id"]): str(item["label"]) for item in HITOMI_SERVER_CATALOG}
        self.hitomi_server_priority_list.clear()
        for server_id in priority:
            if str(server_id) not in catalog:
                continue
            item = QListWidgetItem(catalog[str(server_id)])
            item.setData(Qt.ItemDataRole.UserRole, str(server_id))
            self.hitomi_server_priority_list.addItem(item)

    def _hitomi_server_priority(self) -> list[str]:
        return [
            str(
                self.hitomi_server_priority_list.item(row).data(
                    Qt.ItemDataRole.UserRole
                )
            )
            for row in range(self.hitomi_server_priority_list.count())
        ]

    def _move_hitomi_priority(self, offset: int) -> None:
        row = self.hitomi_server_priority_list.currentRow()
        target = row + int(offset)
        if row < 0 or not 0 <= target < self.hitomi_server_priority_list.count():
            return
        item = self.hitomi_server_priority_list.takeItem(row)
        self.hitomi_server_priority_list.insertItem(target, item)
        self.hitomi_server_priority_list.setCurrentRow(target)

    def _update_hitomi_server_controls(self, _index: int = -1) -> None:
        manual = str(self.hitomi_server_mode_combo.currentData()) == "manual"
        self.hitomi_manual_server_combo.setEnabled(manual)
        self.hitomi_server_priority_list.setEnabled(not manual)

    def _selected_quick_actions(self) -> list[str]:
        return [
            str(self.quick_action_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.quick_action_list.count())
            if self.quick_action_list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _store_current_provider_policy(self) -> None:
        if not self._provider_current_key or not self.provider_policy_values:
            return
        self.provider_policy_values[self._provider_current_key] = {
            "requestDelayMs": self.provider_delay_spin.value(),
            "backoffSeconds": self.provider_backoff_spin.value(),
        }

    def _load_current_provider_policy(self) -> None:
        policy = self.provider_policy_values.get(
            self._provider_current_key,
            {"requestDelayMs": 0, "backoffSeconds": 2},
        )
        self.provider_delay_spin.blockSignals(True)
        self.provider_backoff_spin.blockSignals(True)
        try:
            self.provider_delay_spin.setValue(int(policy["requestDelayMs"]))
            self.provider_backoff_spin.setValue(int(policy["backoffSeconds"]))
        finally:
            self.provider_delay_spin.blockSignals(False)
            self.provider_backoff_spin.blockSignals(False)

    def _provider_policy_selection_changed(self, _index: int) -> None:
        self._store_current_provider_policy()
        self._provider_current_key = str(
            self.provider_policy_combo.currentData() or "manatoki"
        )
        self._load_current_provider_policy()

    def _load_defaults(self) -> None:
        from toki_core import default_config

        defaults = settings_snapshot(default_config())
        self._load_values(defaults)

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "기본 저장 폴더 선택", self.output_edit.text()
        )
        if selected:
            self.output_edit.setText(selected)
            self._update_folder_preview()

    def _choose_background(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "배경 이미지 선택",
            self.background_edit.text() or self.output_edit.text(),
            "이미지 (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if selected:
            self.background_edit.setText(selected)

    def _choose_archive_viewer(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "압축 파일 연결 프로그램 선택",
            self.archive_viewer_path_edit.text(),
            "프로그램 (*.exe);;모든 파일 (*)",
        )
        if selected:
            self.archive_viewer_path_edit.setText(selected)
            index = self.archive_viewer_mode_combo.findData("custom")
            self.archive_viewer_mode_combo.setCurrentIndex(max(0, index))

    def _update_archive_viewer_controls(self, _index: int = -1) -> None:
        custom = str(self.archive_viewer_mode_combo.currentData()) == "custom"
        self.archive_viewer_choose_button.setEnabled(custom)
        self.archive_viewer_clear_button.setEnabled(
            custom and bool(self.archive_viewer_path_edit.text())
        )

    def _clear_archive_viewer(self) -> None:
        self.archive_viewer_path_edit.clear()
        index = self.archive_viewer_mode_combo.findData("system")
        self.archive_viewer_mode_combo.setCurrentIndex(max(0, index))

    def _collect_updates(self) -> dict[str, Any]:
        self._store_current_provider_policy()
        return {
            "outputDir": self.output_edit.text(),
            "uiLanguage": str(self.language_combo.currentData()),
            "folderNameTemplate": self.folder_template_edit.text(),
            "showBrowser": self.show_browser_check.isChecked(),
            "logVisible": self.log_visible_check.isChecked(),
            "trayEnabled": self.tray_enabled_check.isChecked(),
            "closeToTray": self.close_to_tray_check.isChecked(),
            "minimizeToTray": self.minimize_to_tray_check.isChecked(),
            "notifyOnComplete": self.notify_complete_check.isChecked(),
            "notifyOnError": self.notify_error_check.isChecked(),
            "completionAction": str(self.completion_action_combo.currentData()),
            "completionCountdownSeconds": self.completion_countdown_spin.value(),
            "clipboardMonitor": self.clipboard_monitor_check.isChecked(),
            "workConcurrency": self.work_spin.value(),
            "imageConcurrency": self.image_spin.value(),
            "retryCount": self.retry_count_spin.value(),
            "retryBackoffSeconds": self.retry_backoff_spin.value(),
            "proxyUrl": self.proxy_edit.text(),
            "speedLimitKib": self.speed_limit_spin.value(),
            "providerPolicies": {
                key: dict(policy)
                for key, policy in self.provider_policy_values.items()
            },
            "logMaxMiB": self.log_max_spin.value(),
            "logBackupCount": self.log_backups_spin.value(),
            "notificationSound": (
                "system" if self.notification_sound_check.isChecked() else "none"
            ),
            "notificationMessageBox": self.notification_message_box_check.isChecked(),
            "imageResizeMaxWidth": self.image_resize_width_spin.value(),
            "imageResizeMaxHeight": self.image_resize_height_spin.value(),
            "imageExcludedExtensions": [
                part.strip()
                for part in re.split(
                    r"[,;]", self.image_excluded_extensions_edit.text()
                )
                if part.strip()
            ],
            "archiveViewerMode": str(self.archive_viewer_mode_combo.currentData()),
            "archiveViewerPath": self.archive_viewer_path_edit.text(),
            "autosaveIntervalSeconds": self.autosave_interval_spin.value(),
            "recoverInterruptedOnStartup": self.startup_recovery_check.isChecked(),
            "listPageSize": self.list_page_size_spin.value(),
            "listLoadedLimit": self.list_loaded_limit_spin.value(),
            "listScrollLines": self.list_scroll_lines_spin.value(),
            "listLazyLoading": self.list_lazy_loading_check.isChecked(),
            "lowSpecMode": self.low_spec_mode_check.isChecked(),
            "preventSleepDuringDownloads": self.prevent_sleep_check.isChecked(),
            "pdfGenerationEnabled": self.pdf_generation_check.isChecked(),
            "memoryDisplayEnabled": self.memory_display_check.isChecked(),
            "localApiEnabled": self.local_api_check.isChecked(),
            "localApiPort": self.local_api_port_spin.value(),
            "hitomiServerMode": str(self.hitomi_server_mode_combo.currentData()),
            "hitomiManualServer": str(
                self.hitomi_manual_server_combo.currentData()
            ),
            "hitomiServerPriority": self._hitomi_server_priority(),
            "hitomiMetadataMode": str(
                self.hitomi_metadata_mode_combo.currentData()
            ),
            "hitomiMetadataFileMode": str(
                self.hitomi_metadata_file_mode_combo.currentData()
            ),
            "hitomiFilenameMode": str(
                self.hitomi_filename_mode_combo.currentData()
            ),
            "hitomiUseOriginalImages": self.hitomi_original_images_check.isChecked(),
            "hitomiExcludedTags": self.hitomi_excluded_tags_edit.toPlainText(),
            "hitomiPreferJapaneseTitle": self.hitomi_prefer_japanese_title_check.isChecked(),
            "youtubeFormatMode": str(self.youtube_format_mode_combo.currentData()),
            "youtubeMaxHeight": int(self.youtube_max_height_combo.currentData() or 0),
            "youtubeContainer": str(self.youtube_container_combo.currentData()),
            "youtubeVideoCodec": str(self.youtube_video_codec_combo.currentData()),
            "youtubeAudioCodec": str(self.youtube_audio_codec_combo.currentData()),
            "youtubeFilenameTemplate": self.youtube_filename_template_edit.text(),
            "youtubePreferredLanguages": self.youtube_languages_edit.text(),
            "youtubeSubtitleMode": str(self.youtube_subtitle_mode_combo.currentData()),
            "youtubeSubtitleFormat": str(self.youtube_subtitle_format_combo.currentData()),
            "youtubeEmbedSubtitles": self.youtube_embed_subtitles_check.isChecked(),
            "youtubeAudioTrackMode": str(self.youtube_audio_track_mode_combo.currentData()),
            "youtubeWriteThumbnail": self.youtube_write_thumbnail_check.isChecked(),
            "youtubeEmbedThumbnail": self.youtube_embed_thumbnail_check.isChecked(),
            "youtubeWriteInfoJson": self.youtube_write_info_json_check.isChecked(),
            "youtubeWriteDescription": self.youtube_write_description_check.isChecked(),
            "youtubeEmbedMetadata": self.youtube_embed_metadata_check.isChecked(),
            "youtubeCollectionOrder": str(self.youtube_collection_order_combo.currentData()),
            "rowDensity": str(self.row_density_combo.currentData()),
            "theme": str(self.theme_combo.currentData()),
            "listViewMode": str(self.list_view_mode_combo.currentData()),
            "thumbnailsVisible": self.thumbnails_visible_check.isChecked(),
            "thumbnailSize": str(self.thumbnail_size_combo.currentData()),
            "alwaysOnTop": self.always_on_top_check.isChecked(),
            "windowOpacity": self.window_opacity_spin.value(),
            "uiScale": self.ui_scale_spin.value(),
            "fontFamily": self.font_combo.currentFont().family(),
            "backgroundImage": self.background_edit.text(),
            "quickActions": self._selected_quick_actions(),
        }

    def _apply(self, *, close_after: bool) -> None:
        try:
            self.owner.apply_settings(self._collect_updates())
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "설정을 저장할 수 없음", str(error))
            return
        self.search_status.setText("설정을 적용했습니다.")
        if close_after:
            self.accept()

    def _save(self) -> None:
        self._apply(close_after=True)

    def _apply_without_closing(self) -> None:
        self._apply(close_after=False)


class ImageConversionDialog(QDialog):
    def __init__(self, owner: "MainWindow", result: dict[str, Any]) -> None:
        super().__init__(owner)
        self.owner = owner
        self.result = result
        self.setWindowTitle("이미지 형식 변환")
        self.resize(720, 500)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("형식"))
        self.format_combo = QComboBox()
        for label, value in (("WebP", "webp"), ("JPEG", "jpg"), ("PNG", "png")):
            self.format_combo.addItem(label, value)
        format_index = self.format_combo.findData(str(result.get("format") or "webp"))
        self.format_combo.setCurrentIndex(max(0, format_index))
        controls.addWidget(self.format_combo)
        controls.addWidget(QLabel("품질"))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(int(result.get("quality") or 90))
        controls.addWidget(self.quality_spin)
        refresh_button = QPushButton("미리보기 갱신")
        refresh_button.clicked.connect(self._refresh_plan)
        controls.addWidget(refresh_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        policy_controls = QHBoxLayout()
        policy_controls.addWidget(QLabel("최대 너비"))
        self.max_width_spin = QSpinBox()
        self.max_width_spin.setRange(0, 16384)
        self.max_width_spin.setSingleStep(64)
        self.max_width_spin.setSpecialValueText("제한 없음")
        self.max_width_spin.setSuffix(" px")
        self.max_width_spin.setValue(int(result.get("maxWidth") or 0))
        policy_controls.addWidget(self.max_width_spin)
        policy_controls.addWidget(QLabel("최대 높이"))
        self.max_height_spin = QSpinBox()
        self.max_height_spin.setRange(0, 16384)
        self.max_height_spin.setSingleStep(64)
        self.max_height_spin.setSpecialValueText("제한 없음")
        self.max_height_spin.setSuffix(" px")
        self.max_height_spin.setValue(int(result.get("maxHeight") or 0))
        policy_controls.addWidget(self.max_height_spin)
        policy_controls.addWidget(QLabel("제외"))
        self.excluded_extensions_edit = QLineEdit()
        self.excluded_extensions_edit.setPlaceholderText("예: gif, bmp")
        self.excluded_extensions_edit.setText(
            ", ".join(result.get("excludedExtensions") or [])
        )
        policy_controls.addWidget(self.excluded_extensions_edit, 1)
        layout.addLayout(policy_controls)

        dependency = result.get("dependency") or {}
        state = "실행 결과" if result.get("executed") else "변환 계획"
        heading = QLabel(
            f"{state} · 대상 {result.get('sourceCount', 0)}장 · "
            f"유형 제외 {result.get('excludedSourceCount', 0)}장 · "
            f"기존 결과 {result.get('existingTargetCount', 0)}장 · "
            f"변환 예정 {result.get('pendingCount', 0)}장"
        )
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        path_label = QLabel(f"출력: {result.get('targetRoot', '')}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        layout.addWidget(
            QLabel(
                f"Pillow: "
                f"{dependency.get('version') if dependency.get('available') else '설치 필요'} · "
                "원본 파일은 변경하거나 삭제하지 않습니다."
            )
        )
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines = []
        if result.get("executed"):
            lines.extend(
                [
                    f"변환 완료: {result.get('convertedCount', 0)}",
                    f"크기 조절: {result.get('resizedCount', 0)}",
                    f"기존 결과 건너뜀: {result.get('skippedExistingCount', 0)}",
                    f"실패: {result.get('failedCount', 0)}",
                    f"복구한 임시 파일: {result.get('recoveredTemporaryFiles', 0)}",
                    "",
                ]
            )
            for failure in result.get("failures") or []:
                lines.append(f"[실패] {failure.get('source')}\n  {failure.get('error')}")
        else:
            output_root = Path(str(result.get("outputPath") or ""))
            for item in result.get("sample") or []:
                marker = "기존" if item.get("exists") else "예정"
                source = Path(str(item.get("source") or ""))
                target = Path(str(item.get("target") or ""))
                source_short = re.search(
                    r"(image\d+\.[a-zA-Z0-9]+)$", source.name
                )
                target_short = re.search(
                    r"(image\d+(?:_[a-zA-Z0-9]+)?\.[a-zA-Z0-9]+)$", target.name
                )
                episode_match = re.match(r"^0*(\d+)", source.parent.name)
                episode_label = (
                    f"{int(episode_match.group(1))}회차"
                    if episode_match
                    else source.parent.name
                )
                source_text = (
                    f"{episode_label} / "
                    f"{source_short.group(1) if source_short else source.name}"
                )
                try:
                    relative_target = target.relative_to(output_root)
                    target_text = (
                        f"{relative_target.parts[0]}/{relative_target.parts[1]} / "
                        f"{episode_label} / "
                        f"{target_short.group(1) if target_short else target.name}"
                    )
                except ValueError:
                    target_text = str(target)
                lines.append(f"[{marker}] {source_text}\n  → {target_text}")
            if result.get("sampleTruncated"):
                lines.append("\n일부 대상만 표시했습니다.")
        details.setPlainText("\n".join(lines) or "변환할 이미지가 없습니다.")
        layout.addWidget(details, 1)

        buttons = QHBoxLayout()
        open_button = QPushButton("출력 위치 열기")
        open_button.clicked.connect(self._open_target)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        self.execute_button = QPushButton("변환 실행...")
        self.execute_button.setToolTip(
            "CLI: convert-images --job ID --format FORMAT --execute --yes"
        )
        self.execute_button.setEnabled(
            bool(dependency.get("available")) and int(result.get("pendingCount") or 0) > 0
        )
        self.execute_button.clicked.connect(self._execute)
        buttons.addWidget(self.execute_button)
        close_button = QPushButton("닫기")
        close_button.setToolTip("CLI: convert-images --close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _refresh_plan(self) -> None:
        self.owner.start_image_conversion(
            self.result["jobId"],
            str(self.format_combo.currentData()),
            self.quality_spin.value(),
            max_width=self.max_width_spin.value(),
            max_height=self.max_height_spin.value(),
            excluded_extensions=self._excluded_extensions(),
            execute=False,
        )

    def _execute(self) -> None:
        answer = QMessageBox.question(
            self,
            "이미지 변환 실행",
            f"{self.result.get('pendingCount', 0)}개 이미지를 별도 폴더에 변환할까요?\n\n"
            f"{self.result.get('targetRoot', '')}\n\n"
            "원본 이미지는 변경하거나 삭제하지 않습니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.owner.start_image_conversion(
            self.result["jobId"],
            str(self.format_combo.currentData()),
            self.quality_spin.value(),
            max_width=self.max_width_spin.value(),
            max_height=self.max_height_spin.value(),
            excluded_extensions=self._excluded_extensions(),
            execute=True,
        )

    def _excluded_extensions(self) -> list[str]:
        return [
            part.strip()
            for part in re.split(r"[,;]", self.excluded_extensions_edit.text())
            if part.strip()
        ]

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "jobId": str(self.result.get("jobId") or ""),
            "format": str(self.format_combo.currentData() or ""),
            "quality": self.quality_spin.value(),
            "maxWidth": self.max_width_spin.value(),
            "maxHeight": self.max_height_spin.value(),
            "excludedExtensions": self._excluded_extensions(),
            "sourceCount": int(self.result.get("sourceCount") or 0),
            "excludedSourceCount": int(
                self.result.get("excludedSourceCount") or 0
            ),
            "pendingCount": int(self.result.get("pendingCount") or 0),
            "preservesOriginals": bool(self.result.get("preservesOriginals")),
        }

    def _open_target(self) -> None:
        target = Path(str(self.result.get("targetRoot") or ""))
        open_in_explorer(target if target.exists() else Path(self.result["outputPath"]))


class ImageConversionProgressDialog(QDialog):
    def __init__(self, owner: "MainWindow", job_id: str) -> None:
        super().__init__(owner)
        self.owner = owner
        self.job_id = job_id
        self.setWindowTitle("이미지 변환 진행률")
        self.setMinimumWidth(580)
        layout = QVBoxLayout(self)
        self.heading_label = QLabel("이미지 변환을 준비하고 있습니다.")
        self.heading_label.setObjectName("sectionTitle")
        layout.addWidget(self.heading_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.summary_label = QLabel("완료 0 · 크기 조절 0 · 건너뜀 0 · 실패 0")
        layout.addWidget(self.summary_label)
        self.detail_label = QLabel("변환 대상 확인 중…")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("변환 중지")
        self.cancel_button.clicked.connect(
            lambda: self.owner.cancel_image_conversion(self.job_id)
        )
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def update_progress(self, event: dict[str, Any]) -> None:
        total = max(0, int(event.get("total") or 0))
        current = max(0, int(event.get("current") or 0))
        self.heading_label.setText("이미지 변환 중")
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(current, max(1, total)))
        self.progress.setFormat(f"{current} / {total} (%p%)")
        self.summary_label.setText(
            f"완료 {event.get('converted', 0)} · "
            f"크기 조절 {event.get('resized', 0)} · "
            f"건너뜀 {event.get('skipped', 0)} · 실패 {event.get('failed', 0)}"
        )
        source = Path(str(event.get("source") or ""))
        status_labels = {
            "converted": "변환 완료",
            "skipped": "기존 결과 건너뜀",
            "failed": "변환 실패",
        }
        self.detail_label.setText(
            f"{status_labels.get(str(event.get('status')), '처리 중')}: "
            f"{source.parent.name} / {source.name}"
        )

    def mark_cancelling(self) -> None:
        self.heading_label.setText("이미지 변환 중지 중")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("중지 중…")
        self.detail_label.setText(
            "현재 변환 프로세스를 중지하고 있습니다. 원본 파일은 변경되지 않습니다."
        )


class PdfGenerationDialog(QDialog):
    def __init__(self, owner: "MainWindow", result: dict[str, Any]) -> None:
        super().__init__(owner)
        self.owner = owner
        self.result = result
        self.setWindowTitle("회차별 PDF 생성")
        self.resize(720, 500)
        layout = QVBoxLayout(self)
        state = "실행 결과" if result.get("executed") else "생성 계획"
        heading = QLabel(
            f"{state} · 회차 {result.get('episodeCount', 0)}개 · "
            f"이미지 {result.get('sourceCount', 0)}장 · "
            f"최신 PDF {result.get('existingCurrentCount', 0)}개 · "
            f"생성 예정 {result.get('pendingCount', 0)}개"
        )
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        target_label = QLabel(f"출력: {result.get('targetRoot', '')}")
        target_label.setWordWrap(True)
        layout.addWidget(target_label)
        dependency = result.get("dependency") or {}
        note = QLabel(
            f"Pillow: {dependency.get('version') if dependency.get('available') else '설치 필요'} · "
            "회차별 PDF를 임시 파일에 완성한 뒤 교체하며 원본 이미지는 보존합니다."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        lines: list[str] = []
        if result.get("executed"):
            lines.extend(
                [
                    f"생성 완료: {result.get('generatedCount', 0)}",
                    f"변경 PDF 교체: {result.get('replacedCount', 0)}",
                    f"최신 결과 건너뜀: {result.get('skippedCurrentCount', 0)}",
                    f"실패: {result.get('failedCount', 0)}",
                    f"복구한 임시 파일: {result.get('recoveredTemporaryFiles', 0)}",
                    "",
                ]
            )
            for failure in result.get("failures") or []:
                lines.append(
                    f"[실패] {Path(str(failure.get('episodeFolder') or '')).name}\n"
                    f"  {failure.get('error')}"
                )
        else:
            for item in result.get("sample") or []:
                marker = "최신" if item.get("current") else "교체" if item.get("exists") else "예정"
                lines.append(
                    f"[{marker}] {Path(str(item.get('episodeFolder') or '')).name} · "
                    f"{int(item.get('pageCount') or 0)}쪽\n"
                    f"  → {item.get('target')}"
                )
            if result.get("sampleTruncated"):
                lines.append("\n일부 회차만 표시했습니다.")
        details.setPlainText("\n".join(lines) or "PDF로 만들 회차 이미지가 없습니다.")
        layout.addWidget(details, 1)
        buttons = QHBoxLayout()
        open_button = QPushButton("출력 위치 열기")
        open_button.clicked.connect(self._open_target)
        buttons.addWidget(open_button)
        buttons.addStretch(1)
        self.execute_button = QPushButton("PDF 생성...")
        self.execute_button.setToolTip(
            "CLI: pdf generate --job ID --execute --yes"
        )
        self.execute_button.setEnabled(
            bool(dependency.get("available"))
            and int(result.get("pendingCount") or 0) > 0
        )
        self.execute_button.clicked.connect(self._execute)
        buttons.addWidget(self.execute_button)
        close_button = QPushButton("닫기")
        close_button.setToolTip("CLI: pdf close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _execute(self) -> None:
        answer = QMessageBox.question(
            self,
            "PDF 생성",
            f"새롭거나 변경된 회차 PDF {self.result.get('pendingCount', 0)}개를 생성할까요?\n\n"
            f"{self.result.get('targetRoot', '')}\n\n"
            "원본 이미지와 기존 다운로드 폴더는 변경하거나 삭제하지 않습니다.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.owner.start_pdf_generation(
                str(self.result.get("jobId") or ""), execute=True
            )

    def _open_target(self) -> None:
        target = Path(str(self.result.get("targetRoot") or ""))
        open_in_explorer(
            target if target.exists() else Path(str(self.result.get("outputPath") or ""))
        )

    def state_snapshot(self) -> dict[str, Any]:
        return {
            "open": self.isVisible(),
            "jobId": str(self.result.get("jobId") or ""),
            "episodeCount": int(self.result.get("episodeCount") or 0),
            "sourceCount": int(self.result.get("sourceCount") or 0),
            "pendingCount": int(self.result.get("pendingCount") or 0),
            "preservesOriginals": bool(self.result.get("preservesOriginals")),
        }


class PdfGenerationProgressDialog(QDialog):
    def __init__(self, owner: "MainWindow", job_id: str) -> None:
        super().__init__(owner)
        self.owner = owner
        self.job_id = job_id
        self.setWindowTitle("PDF 생성 진행률")
        self.setMinimumWidth(580)
        layout = QVBoxLayout(self)
        self.heading_label = QLabel("PDF 생성을 준비하고 있습니다.")
        self.heading_label.setObjectName("sectionTitle")
        layout.addWidget(self.heading_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.summary_label = QLabel("생성 0 · 교체 0 · 건너뜀 0 · 실패 0")
        layout.addWidget(self.summary_label)
        self.detail_label = QLabel("회차 이미지 확인 중…")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("PDF 생성 중지")
        self.cancel_button.setToolTip("CLI: pdf cancel --job ID")
        self.cancel_button.clicked.connect(
            lambda: self.owner.cancel_pdf_generation(self.job_id)
        )
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def update_progress(self, event: dict[str, Any]) -> None:
        total = max(0, int(event.get("total") or 0))
        current = max(0, int(event.get("current") or 0))
        self.heading_label.setText("회차별 PDF 생성 중")
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(current, max(1, total)))
        self.progress.setFormat(f"{current} / {total} (%p%)")
        self.summary_label.setText(
            f"생성 {event.get('generated', 0)} · 교체 {event.get('replaced', 0)} · "
            f"건너뜀 {event.get('skipped', 0)} · 실패 {event.get('failed', 0)}"
        )
        folder = Path(str(event.get("episodeFolder") or ""))
        status_labels = {
            "generated": "PDF 생성 완료",
            "skipped": "최신 PDF 건너뜀",
            "failed": "PDF 생성 실패",
        }
        self.detail_label.setText(
            f"{status_labels.get(str(event.get('status')), '처리 중')}: "
            f"{folder.name} · {int(event.get('pageCount') or 0)}쪽"
        )

    def mark_cancelling(self) -> None:
        self.heading_label.setText("PDF 생성 중지 중")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("중지 중…")
        self.detail_label.setText(
            "현재 PDF 생성 프로세스를 중지하고 있습니다. 원본 이미지는 변경되지 않습니다."
        )


@dataclass
class ProcessContext:
    job: DownloadJob
    run: DownloadRun
    process: QProcess | None = None
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    stdout_dropped_bytes: int = 0
    stderr_dropped_bytes: int = 0
    cancel_requested: bool = False
    paused: bool = False
    attempt_count: int = 0
    retry_generation: int = 0


@dataclass
class ImageConversionProcessContext:
    process: QProcess
    execute: bool
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    stdout_dropped_bytes: int = 0
    stderr_dropped_bytes: int = 0
    result: dict[str, Any] | None = None
    cancel_requested: bool = False


@dataclass
class PdfGenerationProcessContext:
    process: QProcess
    execute: bool
    automatic: bool = False
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    stdout_dropped_bytes: int = 0
    stderr_dropped_bytes: int = 0
    result: dict[str, Any] | None = None
    cancel_requested: bool = False


class BackgroundWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._background = QPixmap()
        self._dark_theme = True

    def set_background(self, path: str, dark_theme: bool) -> None:
        resolved = str(path or "").strip()
        self._background = (
            QPixmap(resolved) if resolved and Path(resolved).is_file() else QPixmap()
        )
        self._dark_theme = bool(dark_theme)
        self.update()

    def paintEvent(self, event: Any) -> None:
        if self._background.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        scaled = self._background.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(
            (self.width() - scaled.width()) // 2,
            (self.height() - scaled.height()) // 2,
            scaled,
        )
        overlay = QColor(31, 35, 41, 205) if self._dark_theme else QColor(243, 245, 247, 218)
        painter.fillRect(self.rect(), overlay)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.strings = load_ui_strings(self.config.get("uiLanguage"))
        self.theme_mode = str(self.config.get("theme") or "system")
        self.resolved_theme = self._resolve_theme(self.theme_mode)
        self.jobs: dict[str, DownloadJob] = {}
        self.jobs_by_work: dict[str, DownloadJob] = {}
        self.list_performance_policy = list_performance_policy_snapshot(self.config)
        self.history_page_size = int(
            self.list_performance_policy["effective"]["pageSize"]
        )
        self.history_loaded = 0
        self.history_total = 0
        self.history_all_total = 0
        self.history_loading = False
        self.history_query = ""
        self.history_state = ""
        self.history_sort = "updated"
        self.list_view_state = build_job_list_view_state(loading=True)
        self.history_filter_timer = QTimer(self)
        self.history_filter_timer.setSingleShot(True)
        self.history_filter_timer.setInterval(250)
        self.history_filter_timer.timeout.connect(self.apply_history_filters)
        self.pending_jobs: deque[DownloadJob] = deque()
        self.active_contexts: dict[str, ProcessContext] = {}
        self.sleep_prevention_controller = SleepPreventionController()
        self.last_sleep_prevention: dict[str, Any] = {}
        self.self_test_process: QProcess | None = None
        self.performance_benchmark_process: QProcess | HiddenProcess | None = None
        self.stability_test_process: QProcess | HiddenProcess | None = None
        self.resource_limits = resource_budget()
        self.resource_limits["maxLoadedJobs"] = int(
            self.list_performance_policy["effective"]["loadedLimit"]
        )
        self.file_verify_processes: dict[str, ServiceTask] = {}
        self.image_preview_processes: dict[str, ServiceTask] = {}
        self.image_conversion_processes: dict[str, ImageConversionProcessContext] = {}
        self.pdf_generation_processes: dict[str, PdfGenerationProcessContext] = {}
        self.pending_pdf_jobs: set[str] = set()
        self.duplicate_image_tasks: dict[str, ServiceTask] = {}
        self.io_thread_pool = QThreadPool(self)
        self.io_thread_pool.setMaxThreadCount(int(self.resource_limits["ioThreads"]))
        self.image_thread_pool = self.io_thread_pool
        self.self_test_stdout = ""
        self.self_test_stderr = ""
        self.self_test_output_dropped_bytes = 0
        self.last_self_test: dict[str, Any] | None = None
        self.performance_benchmark_stdout = ""
        self.performance_benchmark_stderr = ""
        self.performance_output_dropped_bytes = 0
        self.stability_test_stdout = ""
        self.stability_test_stderr = ""
        self.stability_output_dropped_bytes = 0
        self.total_output_dropped_bytes = 0
        self.last_performance_benchmark: dict[str, Any] | None = None
        self.last_stability_test: dict[str, Any] | None = None
        self.public_ip_task: ServiceTask | None = None
        self.startup_recovery: dict[str, Any] = {
            "ok": True,
            "executed": False,
            "jobCount": 0,
            "runCount": 0,
            "jobIds": [],
            "runIds": [],
        }
        self.last_manual_recovery: dict[str, Any] = {}
        self.force_close = False
        self.exit_requested = False
        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None
        self.tray_status_action: QAction | None = None
        self.control_sockets: set[Any] = set()
        self.active_context_menu: QMenu | None = None
        self.active_detail_dialog: WorkDetailDialog | None = None
        self.active_run_log_dialog: RunLogDialog | None = None
        self.active_file_verify_dialog: FileVerificationDialog | None = None
        self.active_image_preview_dialog: ImagePreviewDialog | None = None
        self.active_image_conversion_dialog: ImageConversionDialog | None = None
        self.active_image_conversion_progress_dialog: (
            ImageConversionProgressDialog | None
        ) = None
        self.active_pdf_generation_dialog: PdfGenerationDialog | None = None
        self.active_pdf_generation_progress_dialog: (
            PdfGenerationProgressDialog | None
        ) = None
        self.active_settings_dialog: SettingsDialog | None = None
        self.active_hitomi_inspector_dialog: HitomiReferenceDialog | None = None
        self.active_hitomi_metadata_dialog: HitomiMetadataDialog | None = None
        self.active_embedded_browser_dialog: EmbeddedBrowserDialog | None = None
        self.active_proxy_credential_dialog: ProxyCredentialDialog | None = None
        self.active_cookie_manager_dialog: CookieManagerDialog | None = None
        self.active_jobs_snapshot_dialog: JobsSnapshotImportDialog | None = None
        self.active_group_manager_dialog: WorkGroupManagerDialog | None = None
        self.active_archive_inspection_dialog: ArchiveInspectionDialog | None = None
        self.active_recovery_dialog: RecoveryStatusDialog | None = None
        self.active_duplicate_works_dialog: DuplicateWorksDialog | None = None
        self.active_duplicate_images_dialog: DuplicateImagesDialog | None = None
        self.active_completion_dialog: CompletionCountdownDialog | None = None
        self.completion_action_armed = False
        self.last_completion_action: dict[str, Any] = {}
        self.notification_message_boxes: list[QMessageBox] = []
        self.last_notification: dict[str, Any] = {}
        self.last_clipboard_text = ""
        self.last_clipboard_inspection: dict[str, Any] = {}
        self.active_shortcut_help_dialog: ShortcutHelpDialog | None = None
        self.active_doctor_dialog: DependencyDiagnosticsDialog | None = None
        self.active_performance_dialog: PerformanceDiagnosticsDialog | None = None
        self.dirty_job_ids: set[str] = set()
        self.last_autosave: dict[str, Any] = {}
        self.persist_timer = QTimer(self)
        self.persist_timer.setSingleShot(True)
        self.persist_timer.setInterval(
            int(self.config.get("autosaveIntervalSeconds") or 1) * 1000
        )
        self.persist_timer.timeout.connect(self._flush_job_history)
        self.pending_job_ui_updates: set[str] = set()
        self.job_ui_update_timer = QTimer(self)
        self.job_ui_update_timer.setSingleShot(True)
        self.job_ui_update_timer.setInterval(
            int(downloader_event_update_policy("image_saved")["uiIntervalMs"])
        )
        self.job_ui_update_timer.timeout.connect(self._flush_job_card_updates)
        self.event_update_metrics = {
            "receivedEvents": 0,
            "immediateUpdates": 0,
            "queuedEvents": 0,
            "mergedEvents": 0,
            "flushes": 0,
            "renderedUpdates": 0,
        }
        self.local_api_server = LocalApiServer(
            self._handle_control_action,
            self.local_api_status_snapshot,
            lambda message, level: self.log(message, level),
            self,
        )

        self.setWindowTitle(f"tokiDownloader {APP_VERSION}")
        window_config = self.config.get("window", {})
        self.setMinimumSize(QSize(720, 580))
        self.restore_maximized = bool(window_config.get("maximized", False))
        self.restore_position: QPoint | None = None
        self.geometry_restored = False
        self._restore_window_geometry(window_config)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))

        self._build_actions()
        self._build_ui()
        self._apply_style()
        self._apply_display_preferences(self.config)
        self.last_memory_usage: dict[str, Any] = {}
        self.memory_timer = QTimer(self)
        self.memory_timer.setInterval(2000)
        self.memory_timer.timeout.connect(self._update_memory_usage)
        self._configure_memory_display()
        try:
            self.thumbnail_cache_report = cleanup_thumbnail_cache(execute=True)
        except OSError as error:
            self.thumbnail_cache_report = {"ok": False, "error": str(error)}
        try:
            self.run_retention_report = cleanup_run_history(execute=False)
        except (OSError, sqlite3.Error) as error:
            self.run_retention_report = {"ok": False, "error": str(error)}
        self._configure_tray()
        self._start_control_server()
        self._configure_local_api()
        self._restore_job_history()
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)

        for line in read_log_tail(120):
            self.log_edit.appendPlainText(line)
        self.log("GUI 시작")

    def _restore_window_geometry(self, window_config: dict[str, Any]) -> None:
        plan = plan_window_geometry(
            window_config,
            self.screen_layout_snapshot(),
            minimum_width=self.minimumWidth(),
            minimum_height=self.minimumHeight(),
        )
        self.window_restore_plan = plan
        self.restore_maximized = bool(plan["maximized"])
        self.resize(int(plan["width"]), int(plan["height"]))
        self.restore_position = QPoint(int(plan["x"]), int(plan["y"]))

    def _build_actions(self) -> None:
        self.start_action = QAction("다운로드 시작", self)
        self.start_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("download.start")]
        )
        self.start_action.triggered.connect(self.start_from_form)

        self.stop_action = QAction("현재 작업 중지", self)
        self.stop_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("job.stop")]
        )
        self.stop_action.triggered.connect(self.stop_active_job)

        self.pause_action = QAction("현재 작업 일시정지", self)
        self.pause_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("job.pause")]
        )
        self.pause_action.triggered.connect(self.pause_selected_active_job)

        self.resume_action = QAction("일시정지 작업 계속", self)
        self.resume_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("job.resume")]
        )
        self.resume_action.triggered.connect(self.resume_selected_active_job)

        self.retry_action = QAction("선택 작품 전체 재검사", self)
        self.retry_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("job.rescan_full")]
        )
        self.retry_action.triggered.connect(self.retry_selected_job)

        self.new_scan_action = QAction("선택 작품 신규 회차만 검사", self)
        self.new_scan_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("job.rescan_new")]
        )
        self.new_scan_action.triggered.connect(
            lambda: self.rescan_selected_job("new")
        )

        self.range_scan_action = QAction("선택 작품 입력 범위 검사", self)
        self.range_scan_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("job.rescan_range")]
        )
        self.range_scan_action.triggered.connect(
            lambda: self.rescan_selected_job("range")
        )

        self.export_jobs_action = QAction("작업 스냅샷 내보내기...", self)
        self.export_jobs_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("snapshot.export")]
        )
        self.export_jobs_action.triggered.connect(self.choose_jobs_snapshot_export)
        self.import_jobs_action = QAction("작업 스냅샷 가져오기...", self)
        self.import_jobs_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("snapshot.import")]
        )
        self.import_jobs_action.triggered.connect(self.choose_jobs_snapshot_import)
        self.group_manager_action = QAction("작품 그룹 관리...", self)
        self.group_manager_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("group.manage")]
        )
        self.group_manager_action.triggered.connect(self.show_group_manager)
        self.archive_inspection_action = QAction("로컬 압축 작품 검사...", self)
        self.archive_inspection_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("archive.inspect")]
        )
        self.archive_inspection_action.triggered.connect(self.choose_archive_inspection)
        self.duplicate_works_action = QAction("중복 의심 작품 검사...", self)
        self.duplicate_works_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("duplicates.works")]
        )
        self.duplicate_works_action.triggered.connect(self.show_duplicate_works)

        self.open_folder_action = QAction("저장 폴더 열기", self)
        self.open_folder_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("folder.open")]
        )
        self.open_folder_action.triggered.connect(self.open_output_folder)

        self.details_action = QAction("작품 정보 및 실행 이력", self)
        self.details_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("details.open")]
        )
        self.details_action.triggered.connect(self.show_job_details)

        self.activate_selected_action = QAction("선택 작품 상세 열기", self)
        self.activate_selected_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("list.activate")]
        )
        self.activate_selected_action.setShortcutContext(
            Qt.ShortcutContext.WidgetShortcut
        )
        self.activate_selected_action.triggered.connect(
            lambda: self.show_job_details()
        )

        self.clear_log_action = QAction("로그 지우기", self)
        self.clear_log_action.triggered.connect(self.clear_logs)

        self.screenshot_action = QAction("GUI 화면 캡처", self)
        self.screenshot_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("screenshot.capture")]
        )
        self.screenshot_action.triggered.connect(self.capture_window)

        self.self_test_action = QAction("자체 점검 실행", self)
        self.self_test_action.triggered.connect(self.start_self_test)

        self.doctor_action = QAction("설치 및 선택 기능 진단...", self)
        self.doctor_action.triggered.connect(self.show_dependency_diagnostics)

        self.embedded_browser_action = QAction("메모리 전용 내장 브라우저...", self)
        self.embedded_browser_action.setEnabled(
            bool(embedded_browser_capabilities()["available"])
        )
        self.embedded_browser_action.triggered.connect(
            lambda: self.show_embedded_browser()
        )

        self.export_diagnostics_action = QAction("오류 보고용 진단 묶음 내보내기", self)
        self.export_diagnostics_action.triggered.connect(
            lambda: self.export_diagnostic_bundle()
        )

        self.performance_action = QAction("목록 성능 진단...", self)
        self.performance_action.triggered.connect(self.show_performance_diagnostics)

        self.refresh_list_action = QAction("작품 목록 새로고침", self)
        self.refresh_list_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("list.refresh")]
        )
        self.refresh_list_action.triggered.connect(self.refresh_job_list)

        self.thumbnail_cache_action = QAction("썸네일 캐시 정리", self)
        self.thumbnail_cache_action.triggered.connect(self.cleanup_thumbnail_cache_now)

        self.cleanup_records_action = QAction("완료·오류 기록 정리...", self)
        self.cleanup_records_action.triggered.connect(self.confirm_cleanup_records)

        self.run_retention_action = QAction("오래된 실행 이력 정리...", self)
        self.run_retention_action.triggered.connect(self.confirm_run_history_cleanup)

        self.settings_action = QAction("설정...", self)
        self.settings_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("settings.open")]
        )
        self.settings_action.triggered.connect(self.show_settings_dialog)

        self.shortcut_help_action = QAction("키보드 단축키...", self)
        self.shortcut_help_action.triggered.connect(self.show_shortcut_help)

        self.focus_url_action = QAction("URL 입력으로 이동", self)
        self.focus_url_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("focus.url")]
        )
        self.focus_url_action.triggered.connect(
            lambda: self.focus_keyboard_target("url")
        )

        self.focus_search_action = QAction("작품 검색으로 이동", self)
        self.focus_search_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("focus.search")]
        )
        self.focus_search_action.triggered.connect(
            lambda: self.focus_keyboard_target("search")
        )

        self.focus_cycle_action = QAction("다음 화면 영역으로 이동", self)
        self.focus_cycle_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("focus.cycle")]
        )
        self.focus_cycle_action.triggered.connect(
            lambda: self.focus_keyboard_target("next-section")
        )

        self.select_previous_action = QAction("이전 작품 선택", self)
        self.select_previous_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("selection.previous")]
        )
        self.select_previous_action.triggered.connect(
            lambda: self.focus_keyboard_target("previous")
        )

        self.select_next_action = QAction("다음 작품 선택", self)
        self.select_next_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("selection.next")]
        )
        self.select_next_action.triggered.connect(
            lambda: self.focus_keyboard_target("next")
        )

        self.exit_action = QAction("종료", self)
        self.exit_action.triggered.connect(self.request_exit)

    def _build_ui(self) -> None:
        self.work_menu = self.menuBar().addMenu(self.strings["main.menu.work"])
        work_menu = self.work_menu
        work_menu.addAction(self.start_action)
        work_menu.addAction(self.stop_action)
        work_menu.addAction(self.pause_action)
        work_menu.addAction(self.resume_action)
        work_menu.addAction(self.retry_action)
        work_menu.addAction(self.new_scan_action)
        work_menu.addAction(self.range_scan_action)
        work_menu.addSeparator()
        work_menu.addAction(self.export_jobs_action)
        work_menu.addAction(self.import_jobs_action)
        work_menu.addAction(self.group_manager_action)
        work_menu.addSeparator()
        work_menu.addAction(self.exit_action)

        self.tools_menu = self.menuBar().addMenu(self.strings["main.menu.tools"])
        tools_menu = self.tools_menu
        tools_menu.addAction(self.open_folder_action)
        tools_menu.addAction(self.details_action)
        tools_menu.addAction(self.refresh_list_action)
        tools_menu.addAction(self.archive_inspection_action)
        tools_menu.addAction(self.duplicate_works_action)
        tools_menu.addAction(self.thumbnail_cache_action)
        tools_menu.addAction(self.cleanup_records_action)
        tools_menu.addAction(self.run_retention_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.settings_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.screenshot_action)
        tools_menu.addAction(self.embedded_browser_action)
        tools_menu.addAction(self.doctor_action)
        tools_menu.addAction(self.export_diagnostics_action)
        tools_menu.addAction(self.self_test_action)
        tools_menu.addAction(self.performance_action)
        tools_menu.addAction(self.clear_log_action)

        self.view_menu = self.menuBar().addMenu(self.strings["main.menu.view"])
        view_menu = self.view_menu
        view_menu.addAction(self.focus_url_action)
        view_menu.addAction(self.focus_search_action)
        view_menu.addAction(self.focus_cycle_action)
        view_menu.addSeparator()
        view_menu.addAction(self.select_previous_action)
        view_menu.addAction(self.select_next_action)

        self.help_menu = self.menuBar().addMenu(self.strings["main.menu.help"])
        help_menu = self.help_menu
        help_menu.addAction(self.shortcut_help_action)
        cli_action = help_menu.addAction("CLI 명령 보기")
        cli_action.triggered.connect(self.show_cli_help)

        central = BackgroundWidget()
        self.central_background = central
        central.setObjectName("mainCentral")
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)

        input_box = QFrame()
        input_box.setObjectName("inputBox")
        input_layout = QGridLayout(input_box)
        input_layout.setContentsMargins(10, 10, 10, 10)
        input_layout.setHorizontalSpacing(7)
        input_layout.setVerticalSpacing(7)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("작품 회차 목록 URL을 입력하세요")
        self.url_edit.returnPressed.connect(self.start_from_form)
        self.url_edit.textChanged.connect(lambda _text: self._update_action_states())

        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 999999)
        self.start_spin.setSpecialValueText("처음")
        self.start_spin.setToolTip("0이면 처음 회차부터")

        self.last_spin = QSpinBox()
        self.last_spin.setRange(0, 999999)
        self.last_spin.setSpecialValueText("마지막")
        self.last_spin.setToolTip("0이면 마지막 회차까지")

        self.show_browser_check = QCheckBox("브라우저 표시")
        self.show_browser_check.setChecked(bool(self.config.get("showBrowser", False)))
        self.show_browser_check.setToolTip(
            "기본은 백그라운드 실행입니다. 사이트 인증 문제를 확인할 때만 켜세요."
        )

        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItem("신규 회차만", "new")
        self.scan_mode_combo.addItem("전체 재검사", "full")
        self.scan_mode_combo.addItem("지정 범위", "range")
        self.scan_mode_combo.setToolTip(
            "신규는 로컬에 없는 회차만, 전체는 모든 회차 페이지를, "
            "범위는 입력한 구간만 검사합니다."
        )
        self.scan_mode_combo.currentIndexChanged.connect(self._scan_mode_changed)

        self.output_edit = QLineEdit(str(self.config.get("outputDir", ROOT_DIR)))
        self.output_edit.setReadOnly(True)

        self.choose_output_button = QPushButton("폴더 선택")
        self.choose_output_button.clicked.connect(self.choose_output_folder)
        self.open_output_button = QPushButton("폴더 열기")
        self.open_output_button.clicked.connect(self.open_output_folder)

        self.start_button = QPushButton("다운로드")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_from_form)
        self.stop_button = QPushButton("중지")
        self.stop_button.clicked.connect(self.stop_active_job)
        self.retry_button = QPushButton("전체 재검사")
        self.retry_button.setToolTip(
            "작품의 전체 회차를 다시 확인하고 기존 파일은 건너뜁니다."
        )
        self.retry_button.clicked.connect(self.retry_selected_job)

        self.image_concurrency_spin = QSpinBox()
        self.image_concurrency_spin.setRange(1, 16)
        self.image_concurrency_spin.setValue(
            normalize_image_concurrency(self.config.get("imageConcurrency"))
        )
        self.image_concurrency_spin.setToolTip(
            "한 회차 안에서 동시에 받을 이미지 수입니다. 권장값은 5입니다."
        )
        self.work_concurrency_spin = QSpinBox()
        self.work_concurrency_spin.setRange(1, 4)
        self.work_concurrency_spin.setValue(
            normalize_work_concurrency(self.config.get("workConcurrency"))
        )
        self.work_concurrency_spin.setToolTip(
            "동시에 실행할 작품 수입니다. 기본값은 1, 안전 상한은 4입니다."
        )
        self.work_concurrency_spin.valueChanged.connect(self._work_concurrency_changed)
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(0, 5)
        self.retry_count_spin.setValue(
            normalize_retry_count(self.config.get("retryCount"))
        )
        self.retry_count_spin.setToolTip("0이면 자동 재시도하지 않습니다.")
        self.retry_backoff_spin = QSpinBox()
        self.retry_backoff_spin.setRange(1, 60)
        self.retry_backoff_spin.setSuffix("초")
        self.retry_backoff_spin.setValue(
            normalize_retry_backoff(self.config.get("retryBackoffSeconds"))
        )
        self.retry_backoff_spin.setToolTip(
            "재시도 대기는 이 값에서 시작해 2배씩 늘어납니다."
        )
        self.retry_count_spin.valueChanged.connect(self._retry_policy_changed)
        self.retry_backoff_spin.valueChanged.connect(self._retry_policy_changed)

        input_layout.addWidget(QLabel("URL"), 0, 0)
        input_layout.addWidget(self.url_edit, 0, 1, 1, 5)
        input_layout.addWidget(self.start_button, 0, 6)
        input_layout.addWidget(QLabel("회차"), 1, 0)
        input_layout.addWidget(self.start_spin, 1, 1)
        input_layout.addWidget(QLabel("~"), 1, 2)
        input_layout.addWidget(self.last_spin, 1, 3)
        input_layout.addWidget(self.stop_button, 1, 5)
        input_layout.addWidget(self.retry_button, 1, 6)
        input_layout.addWidget(QLabel("저장"), 2, 0)
        input_layout.addWidget(self.output_edit, 2, 1, 1, 3)
        input_layout.addWidget(self.choose_output_button, 2, 4)
        input_layout.addWidget(self.open_output_button, 2, 5, 1, 2)
        input_layout.addWidget(QLabel("이미지 병렬"), 3, 0)
        input_layout.addWidget(self.image_concurrency_spin, 3, 1)
        input_layout.addWidget(QLabel("1~16 (권장 5)"), 3, 2, 1, 2)
        input_layout.addWidget(QLabel("작품 병렬"), 3, 4)
        input_layout.addWidget(self.work_concurrency_spin, 3, 5)
        input_layout.addWidget(QLabel("1~4"), 3, 6)
        input_layout.addWidget(QLabel("검사 방식"), 4, 0)
        input_layout.addWidget(self.scan_mode_combo, 4, 1, 1, 3)
        input_layout.addWidget(self.show_browser_check, 4, 4, 1, 3)
        input_layout.addWidget(QLabel("자동 재시도"), 5, 0)
        input_layout.addWidget(self.retry_count_spin, 5, 1)
        input_layout.addWidget(QLabel("회 (0~5)"), 5, 2)
        input_layout.addWidget(QLabel("기본 대기"), 5, 4)
        input_layout.addWidget(self.retry_backoff_spin, 5, 5)
        input_layout.addWidget(QLabel("지수 백오프"), 5, 6)
        input_layout.setColumnStretch(1, 1)
        self._scan_mode_changed()

        queue_header = QHBoxLayout()
        queue_title = QLabel("다운로드 작업")
        queue_title.setObjectName("headerLabel")
        queue_font = QFont()
        queue_font.setBold(True)
        queue_title.setFont(queue_font)
        self.queue_summary = QLabel("대기 0 · 실행 0 · 완료 0 · 문제 0")
        self.queue_summary.setObjectName("headerLabel")
        queue_header.addWidget(queue_title)
        queue_header.addStretch(1)
        queue_header.addWidget(self.queue_summary)

        filter_bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("제목, 작가, 그룹, 작품 ID 검색")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda: self.history_filter_timer.start())
        self.clear_search_action = QAction("검색어 지우기", self.search_edit)
        self.clear_search_action.setShortcuts(
            [QKeySequence(key) for key in keyboard_shortcut_keys("search.clear")]
        )
        self.clear_search_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.clear_search_action.triggered.connect(
            lambda: self.focus_keyboard_target("search", clear=True)
        )
        self.search_edit.addAction(self.clear_search_action)
        self.state_filter_combo = QComboBox()
        for label, value in (
            ("모든 상태", ""),
            ("대기", "대기"),
            ("실행 중", "실행 중"),
            ("일시정지", "일시정지"),
            ("재시도 대기", "재시도 대기"),
            ("인증 필요", "인증 필요"),
            ("완료", "완료"),
            ("오류", "오류"),
            ("중지됨", "중지됨"),
            ("취소됨", "취소됨"),
        ):
            self.state_filter_combo.addItem(label, value)
        self.state_filter_combo.currentIndexChanged.connect(self.apply_history_filters)
        self.sort_combo = QComboBox()
        for label, value in (
            ("최근 갱신순", "updated"),
            ("제목순", "title"),
            ("진행률순", "progress"),
        ):
            self.sort_combo.addItem(label, value)
        self.sort_combo.currentIndexChanged.connect(self.apply_history_filters)
        reset_filter_button = QPushButton("초기화")
        reset_filter_button.clicked.connect(self.reset_history_filters)
        refresh_list_button = QPushButton("새로고침")
        refresh_list_button.clicked.connect(self.refresh_job_list)
        filter_bar.addWidget(self.search_edit, 1)
        filter_bar.addWidget(self.state_filter_combo)
        filter_bar.addWidget(self.sort_combo)
        filter_bar.addWidget(refresh_list_button)
        filter_bar.addWidget(reset_filter_button)

        self.task_model = JobListModel(self)
        self.task_list = QListView()
        self.task_list.setModel(self.task_model)
        self.task_list.setItemDelegate(
            JobItemDelegate(
                self.task_list,
                str(self.config.get("rowDensity") or "comfortable"),
                self.resolved_theme,
            )
        )
        self.task_list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.task_list.setUniformItemSizes(True)
        self.task_list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.task_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.task_list.setSpacing(2)
        self.task_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.task_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_list.setToolTip(
            "한 번 클릭하면 선택, Enter는 상세 정보, 더블클릭은 다운로드 폴더 열기입니다."
        )
        self.task_list.setAccessibleName("다운로드 작업 목록")
        self.task_list.addAction(self.activate_selected_action)
        self.task_list.doubleClicked.connect(self.open_job_index_folder)
        self.task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_list.customContextMenuRequested.connect(self.show_job_context_menu)
        self.task_list.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._update_action_states()
        )
        self.task_list.verticalScrollBar().valueChanged.connect(self._maybe_load_more_history)

        self.list_state_panel = QFrame()
        self.list_state_panel.setObjectName("listStatePanel")
        self.list_state_panel.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        state_layout = QVBoxLayout(self.list_state_panel)
        state_layout.setContentsMargins(32, 32, 32, 32)
        state_layout.addStretch(1)
        self.list_state_title = QLabel()
        self.list_state_title.setObjectName("listStateTitle")
        self.list_state_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_state_title.setWordWrap(True)
        state_title_font = QFont()
        state_title_font.setPointSize(13)
        state_title_font.setBold(True)
        self.list_state_title.setFont(state_title_font)
        self.list_state_message = QLabel()
        self.list_state_message.setObjectName("mutedLabel")
        self.list_state_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_state_message.setWordWrap(True)
        self.list_state_action_button = QPushButton()
        self.list_state_action_button.clicked.connect(self._handle_list_state_action)
        self.list_state_action_button.setMaximumWidth(180)
        state_layout.addWidget(self.list_state_title)
        state_layout.addWidget(self.list_state_message)
        state_layout.addSpacing(8)
        state_layout.addWidget(
            self.list_state_action_button, 0, Qt.AlignmentFlag.AlignHCenter
        )
        state_layout.addStretch(1)

        self.list_stack = QStackedWidget()
        self.list_stack.setObjectName("listStack")
        self.list_stack.addWidget(self.task_list)
        self.list_stack.addWidget(self.list_state_panel)
        self._set_list_view_state(self.list_view_state)

        self.log_box = QGroupBox("실행 로그")
        log_layout = QVBoxLayout(self.log_box)
        log_actions = QHBoxLayout()
        log_actions.addStretch(1)
        copy_log_button = QPushButton("복사")
        copy_log_button.clicked.connect(self.copy_logs)
        screenshot_button = QPushButton("화면 캡처")
        screenshot_button.clicked.connect(self.capture_window)
        self.self_test_button = QPushButton("자체 점검")
        self.self_test_button.clicked.connect(self.start_self_test)
        clear_log_button = QPushButton("지우기")
        clear_log_button.clicked.connect(self.clear_logs)
        log_actions.addWidget(screenshot_button)
        log_actions.addWidget(self.self_test_button)
        log_actions.addWidget(copy_log_button)
        log_actions.addWidget(clear_log_button)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(3000)
        self.log_edit.setMinimumHeight(150)
        log_layout.addLayout(log_actions)
        log_layout.addWidget(self.log_edit)

        self.quick_action_frame = QFrame()
        self.quick_action_frame.setObjectName("inputBox")
        self.quick_action_layout = QHBoxLayout(self.quick_action_frame)
        self.quick_action_layout.setContentsMargins(8, 5, 8, 5)
        self.quick_action_buttons: dict[str, QPushButton] = {}
        self._rebuild_quick_action_bar(self.config.get("quickActions") or [])

        root.addWidget(input_box)
        root.addWidget(self.quick_action_frame)
        root.addLayout(queue_header)
        root.addLayout(filter_bar)
        root.addWidget(self.list_stack, 1)
        root.addWidget(self.log_box)
        self.log_box.setVisible(bool(self.config.get("logVisible", True)))
        self.setCentralWidget(central)

        status = QStatusBar()
        self.status_label = QLabel(self.strings["main.status.ready"])
        self.overall_progress = QProgressBar()
        self.overall_progress.setFixedWidth(220)
        self.overall_progress.setRange(0, 100)
        self.memory_progress = QProgressBar()
        self.memory_progress.setObjectName("memoryProgress")
        self.memory_progress.setFixedWidth(225)
        self.memory_progress.setRange(0, 100)
        self.memory_progress.setValue(0)
        self.memory_progress.setFormat("메모리 확인 중…")
        status.addWidget(self.status_label, 1)
        status.addPermanentWidget(self.memory_progress)
        status.addPermanentWidget(self.overall_progress)
        self.setStatusBar(status)

    def _resolve_theme(self, mode: str) -> str:
        if mode in {"light", "dark"}:
            return mode
        window_color = QApplication.palette().color(QPalette.ColorRole.Window)
        return "dark" if window_color.lightness() < 128 else "light"

    def _apply_style(self) -> None:
        dark = self.resolved_theme == "dark"
        scale = max(75, min(200, int(self.config.get("uiScale") or 100))) / 100
        has_background = bool(
            str(self.config.get("backgroundImage") or "").strip()
            and Path(str(self.config.get("backgroundImage"))).is_file()
        )
        colors = {
            "text": "#edf2f7" if dark else "#20262e",
            "muted": "#aeb9c7" if dark else "#667282",
            "window": "#1f2329" if dark else "#f3f5f7",
            "surface": (
                "rgba(37, 42, 49, 240)" if dark else "rgba(255, 255, 255, 240)"
            ) if has_background else ("#252a31" if dark else "#ffffff"),
            "surface2": (
                "rgba(48, 55, 65, 240)" if dark else "rgba(233, 237, 242, 240)"
            ) if has_background else ("#303741" if dark else "#e9edf2"),
            "border": "#46505d" if dark else "#cfd6df",
            "hover": "#33455d" if dark else "#edf4ff",
            "pressed": "#3a506b" if dark else "#dfeeff",
            "selection": "#2f7de1",
            "preview": (
                "rgba(48, 55, 65, 240)" if dark else "rgba(238, 241, 244, 240)"
            ) if has_background else ("#303741" if dark else "#eef1f4"),
            "fieldPadding": max(4, round(5 * scale)),
            "buttonHeight": max(24, round(28 * scale)),
            "buttonPadding": max(8, round(12 * scale)),
            "tabVPadding": max(5, round(8 * scale)),
            "tabHPadding": max(12, round(18 * scale)),
        }
        background_path = str(self.config.get("backgroundImage") or "").strip()
        if hasattr(self, "central_background"):
            self.central_background.set_background(background_path, dark)
        stylesheet = """
            QWidget { color: %(text)s; }
            QMainWindow, QDialog { background: %(window)s; color: %(text)s; }
            QMenuBar { background: %(surface)s; color: %(text)s; border-bottom: 1px solid %(border)s; }
            QMenuBar::item:selected, QMenu::item:selected { background: %(hover)s; }
            QMenu { background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; }
            QTabWidget::pane { background: %(surface)s; border: 1px solid %(border)s; }
            QTabBar::tab { background: %(surface2)s; color: %(text)s; border: 1px solid %(border)s;
                border-bottom: 0; padding: %(tabVPadding)spx %(tabHPadding)spx; }
            QTabBar::tab:selected { background: %(surface)s; color: %(text)s; font-weight: 700; }
            QTabWidget > QWidget, #settingsPage { background: %(surface)s; color: %(text)s; }
            #inputBox { background: %(surface)s; border: 1px solid %(border)s; border-radius: 5px; }
            #listStatePanel { background: %(surface)s; border: 1px solid %(border)s; border-radius: 4px; }
            #listStateTitle { color: %(text)s; }
            #headerLabel { background: %(surface)s; color: %(text)s; border-radius: 3px; padding: 3px 6px; }
            QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QListView, QListWidget, QTableWidget {
                background: %(surface)s; color: %(text)s; border: 1px solid %(border)s; border-radius: 4px;
                padding: %(fieldPadding)spx; selection-background-color: %(selection)s; selection-color: #ffffff; }
            QTableWidget { gridline-color: %(border)s; padding: 0; }
            QHeaderView::section { background: %(surface2)s; color: %(text)s; border: 0;
                border-right: 1px solid %(border)s; border-bottom: 1px solid %(border)s;
                padding: 5px; font-weight: 700; }
            QPushButton { min-height: %(buttonHeight)spx; padding: 0 %(buttonPadding)spx; border: 1px solid %(border)s;
                border-radius: 4px; background: %(surface)s; color: %(text)s; }
            QPushButton:hover { background: %(hover)s; border-color: #5f9ee8; }
            QPushButton:pressed { background: %(pressed)s; }
            #primaryButton { background: #2f7de1; color: white; border-color: #2469bd; font-weight: 700; }
            #primaryButton:hover { background: #3b89ee; }
            QListView { padding: 2px; }
            QListView::item { border: 0; }
            #imageList::item { padding: 7px; }
            #detailLabel, #mutedLabel { color: %(muted)s; }
            #previewSurface { background: %(preview)s; color: %(muted)s; border: 1px solid %(border)s; }
            #stateLabel { border-radius: 3px; padding: 3px; font-weight: 700; color: white; background: #7b8794; }
            #stateLabel[state="실행 중"] { background: #1a73e8; }
            #stateLabel[state="재시도 대기"], #stateLabel[state="중지됨"] { background: #cf7a18; }
            #stateLabel[state="인증 필요"] { background: #b33a7a; }
            #stateLabel[state="완료"] { background: #3b7d44; }
            #stateLabel[state="오류"] { background: #d13b32; }
            QProgressBar { color: %(text)s; border: 1px solid %(border)s; border-radius: 3px;
                text-align: center; background: %(preview)s; }
            QProgressBar::chunk { background: #2f7de1; }
            QGroupBox { color: %(text)s; background: %(surface)s; font-weight: 700; }
            QStatusBar { color: %(text)s; background: %(window)s; }
            QGroupBox QPlainTextEdit { font-family: Consolas, "Malgun Gothic"; font-size: 9pt; font-weight: 400; }
        """ % colors
        self.setStyleSheet(stylesheet)

    def log(self, message: str, level: str = "INFO", job_id: str | None = None) -> None:
        clean = ANSI_RE.sub("", str(message)).strip()
        if not clean:
            return
        first_active = next(iter(self.active_contexts.values()), None)
        resolved_job_id = job_id or (first_active.job.job_id if first_active else "-")
        line = append_log(clean, level, resolved_job_id)
        self.log_edit.appendPlainText(line)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _scan_mode_changed(self, _index: int | None = None) -> None:
        is_range = self.scan_mode_combo.currentData() == "range"
        self.start_spin.setEnabled(is_range)
        self.last_spin.setEnabled(is_range)

    def start_from_form(self) -> None:
        try:
            scan_mode = str(self.scan_mode_combo.currentData() or "new")
            self.enqueue_download(
                self.url_edit.text(),
                self.start_spin.value() or None if scan_mode == "range" else None,
                self.last_spin.value() or None if scan_mode == "range" else None,
                self.output_edit.text(),
                self.show_browser_check.isChecked(),
                scan_mode=scan_mode,
            )
        except (ValueError, OSError, RuntimeError) as error:
            QMessageBox.warning(self, "다운로드를 시작할 수 없음", str(error))
            self.log(str(error), "ERROR")

    def enqueue_download(
        self,
        url: str,
        start: int | None,
        last: int | None,
        output_dir: str,
        show_browser: bool = False,
        metadata_only: bool = False,
        image_concurrency: int | None = None,
        scan_mode: str = "new",
        retry_count: int | None = None,
        retry_backoff: int | None = None,
    ) -> DownloadJob:
        valid_url = validate_url(url)
        queue_admission = resource_admission(
            "download_queue",
            queued_count=len(self.pending_jobs),
            budget=self.resource_limits,
        )
        if not queue_admission["allowed"]:
            raise ValueError(
                f"다운로드 대기열 상한 {queue_admission['limit']:,}개에 도달했습니다."
            )
        scan_mode_value, start_value, last_value = normalize_scan_request(
            scan_mode, start, last
        )
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        find_node()

        work_key = build_work_key(valid_url)
        existing = self.jobs_by_work.get(work_key)
        if existing is None:
            existing = load_job_by_work_key(work_key)
        if existing and existing.state in ACTIVE_JOB_STATES:
            raise ValueError("같은 작품이 이미 대기 중이거나 다운로드 중입니다.")

        job = DownloadJob(
            job_id=uuid.uuid4().hex[:10],
            url=valid_url,
            output_dir=str(output_path),
            work_key=work_key,
            start=start_value,
            last=last_value,
            title=existing.title if existing else "메타데이터 확인 중",
            output_path=existing.output_path if existing else "",
            cover_url=existing.cover_url if existing else "",
            cover_path=existing.cover_path if existing else "",
            author=existing.author if existing else "",
            group=existing.group if existing else "",
            site=existing.site if existing else "",
            metadata_path=existing.metadata_path if existing else "",
            user_note=existing.user_note if existing else "",
            pinned=existing.pinned if existing else False,
            tag_color=existing.tag_color if existing else "",
            show_browser=show_browser,
            metadata_only=metadata_only,
            scan_mode=scan_mode_value,
            image_concurrency=normalize_image_concurrency(
                image_concurrency
                if image_concurrency is not None
                else self.image_concurrency_spin.value()
            ),
            retry_limit=normalize_retry_count(
                retry_count
                if retry_count is not None
                else self.retry_count_spin.value()
            ),
            retry_backoff_seconds=normalize_retry_backoff(
                retry_backoff
                if retry_backoff is not None
                else self.retry_backoff_spin.value()
            ),
        )
        run = DownloadRun.from_job(job)
        save_runs([run])
        if existing:
            self.jobs.pop(existing.job_id, None)
        self.jobs[job.job_id] = job
        self.jobs_by_work[work_key] = job
        self.pending_jobs.append(job)
        self.completion_action_armed = True
        self._refresh_pending_positions()
        self._add_job_card(job)
        if existing is None:
            self.history_all_total += 1
            if self._job_matches_history_filters(job):
                self.history_total += 1
        self.history_loaded = self.task_model.rowCount()
        self._schedule_job_persist(job)
        action = (
            "메타데이터 새로고침 예약"
            if metadata_only
            else "작품 작업 갱신" if existing else "작품 작업 추가"
        )
        self.log(f"{action}: {job.url} ({job.work_key})", job_id=job.job_id)
        self._update_summary()
        self._start_next_job()
        return job

    def _add_job_card(self, job: DownloadJob) -> None:
        if not self._job_matches_history_filters(job):
            self.task_model.remove_work_key(job.work_key)
            return
        self.task_model.upsert_job(job)
        self._enforce_loaded_job_limit()
        index = self.task_model.index(0, 0)
        self.task_list.setCurrentIndex(index)
        self.task_list.scrollTo(index)
        self._update_list_view_state()

    def _enforce_loaded_job_limit(self) -> list[str]:
        limit = int(self.resource_limits["maxLoadedJobs"])
        removed = self.task_model.trim_to_limit(limit)
        if not removed:
            return []
        protected_ids = {
            *(job.job_id for job in self.pending_jobs),
            *self.active_contexts,
            *self.dirty_job_ids,
        }
        for job in removed:
            if job.job_id in protected_ids:
                continue
            if self.jobs.get(job.job_id) is job:
                self.jobs.pop(job.job_id, None)
            if self.jobs_by_work.get(job.work_key) is job:
                self.jobs_by_work.pop(job.work_key, None)
        self.history_loaded = self.task_model.rowCount()
        return [job.job_id for job in removed]

    def _set_list_view_state(self, view_state: dict[str, Any]) -> dict[str, Any]:
        self.list_view_state = dict(view_state)
        state_name = str(self.list_view_state.get("state") or "error")
        if state_name == "content":
            self.list_stack.setCurrentWidget(self.task_list)
            self.task_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            return dict(self.list_view_state)

        self.list_state_panel.setProperty("state", state_name)
        self.list_state_title.setText(str(self.list_view_state.get("title") or ""))
        self.list_state_message.setText(str(self.list_view_state.get("message") or ""))
        action_label = str(self.list_view_state.get("actionLabel") or "")
        self.list_state_action_button.setText(action_label)
        self.list_state_action_button.setVisible(bool(action_label))
        self.list_stack.setCurrentWidget(self.list_state_panel)
        return dict(self.list_view_state)

    def _update_list_view_state(
        self, *, loading: bool = False, error: str = ""
    ) -> dict[str, Any]:
        return self._set_list_view_state(
            build_job_list_view_state(
                loading=loading,
                error=error,
                total_count=self.history_all_total,
                filtered_count=self.history_total,
                query=self.history_query,
                state=self.history_state,
            )
        )

    def _handle_list_state_action(self) -> None:
        action = str(self.list_view_state.get("action") or "")
        if action == "focus_url":
            self.url_edit.setFocus()
            self.url_edit.selectAll()
        elif action == "reset_filters":
            self.reset_history_filters()
        elif action == "retry":
            self.refresh_job_list()

    def preview_list_view_state(self, state_name: str, message: str = "") -> dict[str, Any]:
        normalized = str(state_name or "auto").strip().lower().replace("-", "_")
        if normalized == "auto":
            return self._update_list_view_state()
        if normalized == "loading":
            return self._update_list_view_state(loading=True)
        if normalized == "error":
            return self._update_list_view_state(
                error=str(message or "진단용 오류 상태 미리보기입니다.")
            )
        if normalized == "empty":
            return self._set_list_view_state(build_job_list_view_state())
        if normalized == "no_results":
            return self._set_list_view_state(
                build_job_list_view_state(
                    total_count=max(1, self.history_all_total),
                    filtered_count=0,
                    query=self.history_query or "진단용 검색",
                    state=self.history_state,
                )
            )
        raise ValueError(f"지원하지 않는 목록 상태입니다: {state_name}")

    def keyboard_focus_snapshot(self) -> dict[str, Any]:
        focused = QApplication.focusWidget()
        focus_target = "none"
        for name, widget in (
            ("url", self.url_edit),
            ("search", self.search_edit),
            ("list", self.task_list),
            ("list_state", self.list_state_panel),
            ("log", self.log_edit),
        ):
            if focused is widget or (focused is not None and widget.isAncestorOf(focused)):
                focus_target = name
                break
        index = self.task_list.currentIndex()
        selected = self.task_model.job_at(index.row()) if index.isValid() else None
        return {
            "focus": focus_target,
            "selectedRow": index.row() if index.isValid() else -1,
            "selectedJobId": selected.job_id if selected else None,
            "visibleJobCount": self.task_model.rowCount(),
            "listViewState": str(self.list_view_state.get("state") or ""),
        }

    def move_job_selection(self, offset: int) -> dict[str, Any]:
        count = self.task_model.rowCount()
        if count <= 0:
            result = self.focus_keyboard_target("list")
            return {"moved": False, **result}
        current = self.task_list.currentIndex()
        current_row = current.row() if current.isValid() else (-1 if offset >= 0 else 0)
        target_row = (current_row + (1 if offset >= 0 else -1)) % count
        target = self.task_model.index(target_row, 0)
        self.task_list.setCurrentIndex(target)
        self.task_list.scrollTo(target)
        self.task_list.setFocus()
        job = self.task_model.job_at(target_row)
        if job:
            self.statusBar().showMessage(f"선택: {job.title}", 2500)
        return {"moved": True, **self.keyboard_focus_snapshot()}

    def _cycle_keyboard_focus(self) -> dict[str, Any]:
        list_target: QWidget = self.task_list
        if self.list_stack.currentWidget() is self.list_state_panel:
            list_target = (
                self.list_state_action_button
                if self.list_state_action_button.isVisible()
                else self.list_state_panel
            )
        targets: list[tuple[str, QWidget]] = [
            ("url", self.url_edit),
            ("search", self.search_edit),
            ("list", list_target),
        ]
        if self.log_box.isVisible():
            targets.append(("log", self.log_edit))
        focused = QApplication.focusWidget()
        current_index = -1
        for index, (_name, widget) in enumerate(targets):
            if focused is widget or (focused is not None and widget.isAncestorOf(focused)):
                current_index = index
                break
        name, target = targets[(current_index + 1) % len(targets)]
        target.setFocus()
        self.statusBar().showMessage(f"키보드 포커스: {name}", 1800)
        return self.keyboard_focus_snapshot()

    def focus_keyboard_target(self, target: str, clear: bool = False) -> dict[str, Any]:
        normalized = str(target or "").strip().lower().replace("-", "_")
        if normalized == "next":
            return self.move_job_selection(1)
        if normalized == "previous":
            return self.move_job_selection(-1)
        if normalized == "next_section":
            return self._cycle_keyboard_focus()
        if normalized == "url":
            if clear:
                self.url_edit.clear()
            self.url_edit.setFocus()
            self.url_edit.selectAll()
        elif normalized == "search":
            if clear and self.search_edit.text():
                self.search_edit.clear()
                self.apply_history_filters()
            self.search_edit.setFocus()
            self.search_edit.selectAll()
        elif normalized == "list":
            if self.list_stack.currentWidget() is self.list_state_panel:
                if self.list_state_action_button.isVisible():
                    self.list_state_action_button.setFocus()
                else:
                    self.list_state_panel.setFocus()
            else:
                if not self.task_list.currentIndex().isValid() and self.task_model.rowCount():
                    self.task_list.setCurrentIndex(self.task_model.index(0, 0))
                self.task_list.setFocus()
        elif normalized == "log":
            if not self.log_box.isVisible():
                raise ValueError("로그 패널이 숨겨져 있어 포커스를 이동할 수 없습니다.")
            self.log_edit.setFocus()
        else:
            raise ValueError(f"지원하지 않는 키보드 포커스 대상입니다: {target}")
        return self.keyboard_focus_snapshot()

    def _restore_job_history(self) -> None:
        self._update_list_view_state(loading=True)
        try:
            recovery_enabled = bool(
                self.config.get("recoverInterruptedOnStartup", True)
            )
            self.startup_recovery = {
                **recover_interrupted_jobs(execute=recovery_enabled),
                "automatic": True,
                "enabled": recovery_enabled,
            }
            metadata_updates: list[DownloadJob] = []
            self.history_all_total = count_jobs()
            self.history_total = count_jobs(self.history_query, self.history_state)
            page = load_jobs_page(
                self._initial_history_load_limit(),
                0,
                self.history_query,
                self.history_state,
                self.history_sort,
            )
        except (OSError, sqlite3.Error, ValueError) as error:
            self._update_list_view_state(error=str(error))
            self.log(f"작업 목록 초기 로딩 실패: {error}", "ERROR")
            self._update_summary()
            return
        for job in page:
            if hydrate_job_metadata(job):
                metadata_updates.append(job)
            self.jobs[job.job_id] = job
            self.jobs_by_work[job.work_key] = job
        self.task_model.append_jobs(page)
        self.history_loaded = len(page)
        changed_jobs = {job.job_id: job for job in metadata_updates}
        if changed_jobs:
            save_jobs(list(changed_jobs.values()))
        if self.startup_recovery.get("executed") and (
            self.startup_recovery["jobCount"]
            or self.startup_recovery["runCount"]
        ):
            self.log(
                "이전 종료 작업 복구: "
                f"작품 {self.startup_recovery['jobCount']}개, "
                f"실행 이력 {self.startup_recovery['runCount']}개를 중지됨으로 변경"
            )
        if self.task_model.rowCount():
            self.task_list.setCurrentIndex(self.task_model.index(0, 0))
            self.task_list.scrollToTop()
        self._update_summary()
        self._update_list_view_state()

    def _job_matches_history_filters(self, job: DownloadJob) -> bool:
        if self.history_state and job.state != self.history_state:
            return False
        query = self.history_query.casefold().strip()
        if not query:
            return True
        haystack = " ".join((job.title, job.work_key, job.url)).casefold()
        return query in haystack

    def apply_history_filters(self, *_args: Any) -> dict[str, Any]:
        self.history_filter_timer.stop()
        self._flush_job_history()
        selected = self.selected_job()
        selected_key = selected.work_key if selected else ""
        self.history_query = self.search_edit.text().strip()
        self.history_state = str(self.state_filter_combo.currentData() or "")
        self.history_sort = str(self.sort_combo.currentData() or "updated")
        self._update_list_view_state(loading=True)
        QApplication.processEvents()
        try:
            page = load_jobs_page(
                self._initial_history_load_limit(),
                0,
                self.history_query,
                self.history_state,
                self.history_sort,
            )
            history_all_total = count_jobs()
            history_total = count_jobs(self.history_query, self.history_state)
        except (OSError, sqlite3.Error, ValueError) as error:
            self._update_list_view_state(error=str(error))
            self.log(f"작업 목록 로딩 실패: {error}", "ERROR")
            self._update_summary()
            return dict(self.list_view_state)
        display_jobs: list[DownloadJob] = []
        for stored_job in page:
            job = self.jobs_by_work.get(stored_job.work_key) or stored_job
            if stored_job.work_key not in self.jobs_by_work:
                self.jobs[job.job_id] = job
                self.jobs_by_work[job.work_key] = job
            display_jobs.append(job)
        self.task_model.replace_jobs(display_jobs)
        self.history_all_total = history_all_total
        self.history_total = history_total
        self.history_loaded = len(display_jobs)
        if selected_key and selected_key in self.task_model.row_by_key:
            row = self.task_model.row_by_key[selected_key]
            self.task_list.setCurrentIndex(self.task_model.index(row, 0))
        elif display_jobs:
            self.task_list.setCurrentIndex(self.task_model.index(0, 0))
        self._update_summary()
        return self._update_list_view_state()

    def reset_history_filters(self) -> None:
        self.history_filter_timer.stop()
        self.search_edit.clear()
        self.state_filter_combo.setCurrentIndex(0)
        self.sort_combo.setCurrentIndex(0)
        self.apply_history_filters()

    def refresh_job_list(self) -> dict[str, Any]:
        delegate = self.task_list.itemDelegate()
        if isinstance(delegate, JobItemDelegate):
            delegate.cover_cache.clear()
        view_state = self.apply_history_filters()
        self.task_list.viewport().update()
        refreshed = view_state.get("state") != "error"
        result = {
            "refreshed": refreshed,
            "loaded": self.task_model.rowCount(),
            "total": self.history_total,
            "thumbnailCacheCleared": True,
            "viewState": view_state,
        }
        if refreshed:
            self.log("작품 목록과 썸네일 캐시 새로고침")
        return result

    def cleanup_thumbnail_cache_now(self) -> dict[str, Any]:
        report = cleanup_thumbnail_cache(execute=True)
        self.thumbnail_cache_report = report
        delegate = self.task_list.itemDelegate()
        if isinstance(delegate, JobItemDelegate):
            delegate.cover_cache.clear()
        self.task_list.viewport().update()
        message = (
            f"썸네일 캐시 정리: {int(report['removedFiles'])}개, "
            f"{int(report['removedBytes']) / (1024 * 1024):.1f} MiB 제거"
        )
        self.log(message)
        self.statusBar().showMessage(message, 4000)
        return report

    def set_history_filters(self, query: str, state: str, sort: str) -> dict[str, Any]:
        state_index = self.state_filter_combo.findData(state)
        sort_index = self.sort_combo.findData(sort)
        if state_index < 0:
            raise ValueError(f"지원하지 않는 작업 상태 필터입니다: {state}")
        if sort_index < 0:
            raise ValueError(f"지원하지 않는 작업 정렬입니다: {sort}")
        self.search_edit.blockSignals(True)
        self.state_filter_combo.blockSignals(True)
        self.sort_combo.blockSignals(True)
        try:
            self.search_edit.setText(query)
            self.state_filter_combo.setCurrentIndex(state_index)
            self.sort_combo.setCurrentIndex(sort_index)
        finally:
            self.search_edit.blockSignals(False)
            self.state_filter_combo.blockSignals(False)
            self.sort_combo.blockSignals(False)
        self.apply_history_filters()
        return self.list_jobs_snapshot(query, state, sort, self.history_page_size, 0)

    def list_jobs_snapshot(
        self,
        query: str,
        state: str,
        sort: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        self._flush_job_history()
        safe_limit = max(1, min(1000, int(limit)))
        safe_offset = max(0, int(offset))
        jobs = load_jobs_page(safe_limit, safe_offset, query, state, sort)
        return {
            "ok": True,
            "total": count_jobs(query, state),
            "limit": safe_limit,
            "offset": safe_offset,
            "query": query,
            "status": state,
            "sort": sort,
            "jobs": [job.to_dict() for job in jobs],
        }

    def _maybe_load_more_history(self, value: int) -> None:
        if not self.list_performance_policy["effective"]["lazyLoading"]:
            return
        scrollbar = self.task_list.verticalScrollBar()
        if scrollbar.maximum() <= 0 or value < scrollbar.maximum() - 24:
            return
        self._load_more_history()

    def _load_more_history(self) -> None:
        loaded_limit = int(self.resource_limits["maxLoadedJobs"])
        remaining = loaded_limit - self.task_model.rowCount()
        if (
            self.history_loading
            or self.history_loaded >= self.history_total
            or remaining <= 0
        ):
            return
        self.history_loading = True
        try:
            page = load_jobs_page(
                min(self.history_page_size, remaining),
                self.history_loaded,
                self.history_query,
                self.history_state,
                self.history_sort,
            )
            self.history_loaded += len(page)
            display_jobs: list[DownloadJob] = []
            for stored_job in page:
                job = self.jobs_by_work.get(stored_job.work_key) or stored_job
                if stored_job.work_key not in self.jobs_by_work:
                    self.jobs[job.job_id] = job
                    self.jobs_by_work[job.work_key] = job
                if not self.task_model.contains_work_key(job.work_key):
                    display_jobs.append(job)
            self.task_model.append_jobs(display_jobs)
            self._enforce_loaded_job_limit()
        except (OSError, sqlite3.Error, ValueError) as error:
            self._update_list_view_state(error=str(error))
            self.log(f"추가 작업 목록 로딩 실패: {error}", "ERROR")
            return
        finally:
            self.history_loading = False
        self._update_summary()
        self._update_list_view_state()

    def _schedule_job_persist(self, job: DownloadJob) -> None:
        self.dirty_job_ids.add(job.job_id)
        if not self.persist_timer.isActive():
            self.persist_timer.start()

    def _flush_job_history(self) -> None:
        if not self.dirty_job_ids:
            return
        job_ids = tuple(self.dirty_job_ids)
        self.dirty_job_ids.clear()
        pending = [self.jobs[job_id] for job_id in job_ids if job_id in self.jobs]
        try:
            save_jobs(pending)
        except (OSError, sqlite3.Error) as error:
            self.dirty_job_ids.update(job_ids)
            self.last_autosave = {
                "ok": False,
                "savedCount": 0,
                "pendingCount": len(self.dirty_job_ids),
                "error": str(error),
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self.log(f"작업 기록 저장 실패: {error}", "ERROR")
            if not self.persist_timer.isActive():
                self.persist_timer.start()
            return
        self.last_autosave = {
            "ok": True,
            "savedCount": len(pending),
            "pendingCount": len(self.dirty_job_ids),
            "error": "",
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    def _update_job_card(self, job: DownloadJob) -> None:
        was_visible = self.task_model.contains_work_key(job.work_key)
        is_visible = self._job_matches_history_filters(job)
        if was_visible and not is_visible:
            self.task_model.remove_work_key(job.work_key)
            self.history_total = max(0, self.history_total - 1)
        elif not was_visible and is_visible:
            self.task_model.upsert_job(job)
            self.history_total += 1
        else:
            self.task_model.update_job(job)
        if job.job_id in self.active_contexts:
            self._update_active_summary()
        self._schedule_job_persist(job)
        self._update_summary()

    def _schedule_job_card_update(self, job: DownloadJob, event_name: str) -> None:
        policy = downloader_event_update_policy(event_name)
        self.event_update_metrics["receivedEvents"] += 1
        if policy["uiMode"] == "coalesced":
            self.event_update_metrics["queuedEvents"] += 1
            if job.job_id in self.pending_job_ui_updates:
                self.event_update_metrics["mergedEvents"] += 1
            self.pending_job_ui_updates.add(job.job_id)
            if not self.job_ui_update_timer.isActive():
                self.job_ui_update_timer.start()
            return
        self.pending_job_ui_updates.discard(job.job_id)
        self.event_update_metrics["immediateUpdates"] += 1
        self.event_update_metrics["renderedUpdates"] += 1
        self._update_job_card(job)

    def _flush_job_card_updates(self) -> None:
        if not self.pending_job_ui_updates:
            return
        job_ids = tuple(self.pending_job_ui_updates)
        self.pending_job_ui_updates.clear()
        self.event_update_metrics["flushes"] += 1
        for job_id in job_ids:
            job = self.jobs.get(job_id)
            if job is None:
                continue
            self.event_update_metrics["renderedUpdates"] += 1
            self._update_job_card(job)

    def event_update_snapshot(self) -> dict[str, Any]:
        return {
            **self.event_update_metrics,
            "pendingJobs": len(self.pending_job_ui_updates),
            "intervalMs": self.job_ui_update_timer.interval(),
            "imageSavedPolicy": downloader_event_update_policy("image_saved"),
        }

    def thumbnail_cache_snapshot(self) -> dict[str, Any]:
        try:
            current = cleanup_thumbnail_cache(execute=False)
            self.thumbnail_cache_report = current
        except OSError as error:
            current = {"ok": False, "error": str(error)}
        delegate = self.task_list.itemDelegate()
        memory_entries = (
            len(delegate.cover_cache) if isinstance(delegate, JobItemDelegate) else 0
        )
        return {**current, "memoryEntries": memory_entries}

    def retention_snapshot(self) -> dict[str, Any]:
        return {
            "logs": log_retention_status(),
            "runs": self.run_retention_report,
        }

    def resource_snapshot(self) -> dict[str, Any]:
        io_tracked = len(self.file_verify_processes) + len(self.image_preview_processes)
        io_active = self.io_thread_pool.activeThreadCount()
        return {
            "limits": dict(self.resource_limits),
            "io": {
                "activeThreads": io_active,
                "trackedTasks": io_tracked,
                "queuedTasks": max(0, io_tracked - io_active),
                "threadLimit": self.io_thread_pool.maxThreadCount(),
            },
            "cpu": {
                "activeProcesses": (
                    len(self.image_conversion_processes)
                    + len(self.pdf_generation_processes)
                ),
                "queuedPdfJobs": len(self.pending_pdf_jobs),
                "processLimit": int(self.resource_limits["cpuProcesses"]),
            },
            "downloads": {
                "active": len(self.active_contexts),
                "pending": len(self.pending_jobs),
                "pendingLimit": int(self.resource_limits["maxPendingDownloads"]),
            },
            "memory": {
                "loadedJobs": self.task_model.rowCount(),
                "loadedJobLimit": int(self.resource_limits["maxLoadedJobs"]),
                "catalogTotal": self.history_total,
                "catalogCapped": (
                    self.task_model.rowCount()
                    >= int(self.resource_limits["maxLoadedJobs"])
                    and self.history_total > self.task_model.rowCount()
                ),
                "processOutputLimitBytes": int(
                    self.resource_limits["maxProcessOutputBytes"]
                ),
                "droppedProcessOutputBytes": self.total_output_dropped_bytes,
            },
        }

    @staticmethod
    def _memory_mib(value: Any) -> str:
        return f"{max(0, int(value or 0)) / (1024 * 1024):,.0f} MiB"

    def memory_status_snapshot(self, child_limit: int = 200) -> dict[str, Any]:
        snapshot = memory_usage_snapshot(
            self.config,
            process_id=os.getpid(),
            child_limit=child_limit,
        )
        if snapshot.get("ok"):
            child_entries = {
                int(item["pid"]): item
                for item in snapshot["application"].get("children") or []
            }
            parent_by_pid = {
                pid: int(item.get("parentPid") or 0)
                for pid, item in child_entries.items()
            }

            def memory_for_root(root_pid: int) -> int:
                total = 0
                for pid, item in child_entries.items():
                    current = pid
                    visited: set[int] = set()
                    while current and current not in visited:
                        if current == root_pid:
                            total += int(item.get("rssBytes") or 0)
                            break
                        visited.add(current)
                        current = parent_by_pid.get(current, 0)
                return total

            tracked: list[dict[str, Any]] = []
            candidates: list[tuple[str, str, Any]] = [
                ("download", job_id, context)
                for job_id, context in self.active_contexts.items()
            ]
            candidates.extend(
                ("image_conversion", job_id, context)
                for job_id, context in self.image_conversion_processes.items()
            )
            candidates.extend(
                ("pdf", job_id, context)
                for job_id, context in self.pdf_generation_processes.items()
            )
            for kind, job_id, context in candidates:
                process = getattr(context, "process", None)
                pid = int(process.processId()) if process else 0
                if pid <= 0:
                    continue
                tracked.append(
                    {
                        "kind": kind,
                        "jobId": job_id,
                        "pid": pid,
                        "rssBytes": memory_for_root(pid),
                    }
                )
            snapshot["trackedJobProcesses"] = tracked
        self.last_memory_usage = snapshot
        return snapshot

    def _configure_memory_display(self) -> None:
        enabled = bool(self.config.get("memoryDisplayEnabled", True))
        self.memory_progress.setVisible(enabled)
        if enabled:
            if not self.memory_timer.isActive():
                self.memory_timer.start()
            self._update_memory_usage()
        else:
            self.memory_timer.stop()

    def _update_memory_usage(self) -> None:
        if not bool(self.config.get("memoryDisplayEnabled", True)):
            return
        snapshot = self.memory_status_snapshot()
        if not snapshot.get("ok"):
            self.memory_progress.setValue(0)
            self.memory_progress.setFormat("메모리 확인 실패")
            self.memory_progress.setToolTip(str(snapshot.get("error") or "알 수 없는 오류"))
            return
        application = snapshot["application"]
        system = snapshot["system"]
        display = snapshot["display"]
        self.memory_progress.setValue(int(display["percent"]))
        self.memory_progress.setFormat(
            f"RAM {float(system['percent']):.0f}% · 앱 "
            f"{self._memory_mib(application['combinedRssBytes'])}"
        )
        self.memory_progress.setToolTip(
            "시스템 사용 "
            f"{self._memory_mib(system['usedBytes'])} / "
            f"{self._memory_mib(system['totalBytes'])}\n"
            f"앱 자체 {self._memory_mib(application['ownRssBytes'])} · "
            f"자식 작업 {self._memory_mib(application['childRssBytes'])} "
            f"({application['childProcessCount']}개)\n"
            f"상태: {display['severity']} · CLI: memory status --json"
        )

    def local_api_status_snapshot(self) -> dict[str, Any]:
        server = self.local_api_server
        return {
            "ok": not bool(server.error()),
            **local_api_policy_snapshot(
                self.config,
                running=server.is_running(),
                current_port=server.port(),
                token=server.token(),
                error=server.error(),
            ),
            "requestCount": server.request_count,
            "lastRequest": server.last_request,
        }

    def _configure_local_api(self) -> None:
        enabled = bool(self.config.get("localApiEnabled", False))
        configured_port = int(self.config.get("localApiPort") or 8765)
        server = self.local_api_server
        if enabled:
            if not server.is_running() or server.port() != configured_port:
                started = server.start(configured_port)
                if started:
                    self.log(
                        f"로컬 HTTP API 시작: 127.0.0.1:{server.port()} · 임시 토큰 생성"
                    )
                else:
                    self.log(
                        f"로컬 HTTP API 시작 실패: {server.error()}",
                        "ERROR",
                    )
        elif server.is_running() or server.token() or server.error():
            server.stop()
            self.log("로컬 HTTP API 중지")
        dialog = getattr(self, "active_settings_dialog", None)
        if dialog:
            dialog._update_local_api_status()

    def local_api_token_snapshot(self, *, reveal: bool = False) -> dict[str, Any]:
        status = self.local_api_status_snapshot()
        if reveal:
            token = self.local_api_server.token()
            if not token:
                raise RuntimeError("로컬 HTTP API가 실행 중이 아닙니다.")
            status["token"] = token
        return status

    def copy_local_api_token(self) -> bool:
        token = self.local_api_server.token()
        if not token:
            raise RuntimeError("로컬 HTTP API가 실행 중이 아닙니다.")
        QApplication.clipboard().setText(token)
        self.statusBar().showMessage("로컬 API 임시 토큰을 클립보드에 복사했습니다.", 4000)
        return True

    def rotate_local_api_token(self) -> dict[str, Any]:
        self.local_api_server.rotate_token()
        self.log("로컬 HTTP API 임시 토큰 재발급")
        dialog = getattr(self, "active_settings_dialog", None)
        if dialog:
            dialog._update_local_api_status()
        return self.local_api_status_snapshot()

    def _start_next_job(self) -> None:
        concurrency = normalize_work_concurrency(self.work_concurrency_spin.value())
        while self.pending_jobs and available_work_slots(
            len(self.active_contexts), concurrency
        ):
            job = self.pending_jobs.popleft()
            job.queue_position = 0
            run = load_run(job.job_id) or DownloadRun.from_job(job)
            context = ProcessContext(job=job, run=run)
            self.active_contexts[job.job_id] = context
            self._launch_context(context)
        self._refresh_pending_positions()
        self._update_active_summary()
        if (
            not self.pending_jobs
            and not self.active_contexts
            and not self.pdf_generation_processes
            and not self.pending_pdf_jobs
        ):
            QTimer.singleShot(0, self._maybe_trigger_completion_action)

    def _launch_context(self, context: ProcessContext) -> None:
        if context.cancel_requested:
            return
        context.attempt_count += 1
        context.job.attempt_count = context.attempt_count
        context.run.attempt_count = context.attempt_count
        context.run.retry_limit = context.job.retry_limit
        context.run.retry_backoff_seconds = context.job.retry_backoff_seconds
        context.stdout_buffer = ""
        context.stderr_buffer = ""
        context.paused = False
        context.job.state = "실행 중"
        context.job.error = ""
        context.job.error_category = ""
        context.job.retryable_error = None
        context.run.state = "실행 중"
        context.run.error = ""
        context.run.error_category = ""
        context.run.retryable_error = None
        context.run.finished_at = ""
        process = create_background_process(self)
        context.process = process
        self._update_job_card(context.job)

        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(find_node())
        process.setArguments(
            build_downloader_args(
                context.job,
                json_events=True,
                folder_template=str(
                    getattr(self, "config", {}).get("folderNameTemplate") or ""
                ),
                network_config=getattr(self, "config", {}),
            )
        )
        environment_overrides = downloader_environment_overrides(
            getattr(self, "config", {})
        )
        if isinstance(process, HiddenProcess):
            process.setEnvironmentOverrides(environment_overrides)
        elif environment_overrides:
            environment = QProcessEnvironment.systemEnvironment()
            for key, value in environment_overrides.items():
                environment.insert(key, value)
            process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(
            lambda job_id=context.job.job_id: self._read_stdout(job_id)
        )
        process.readyReadStandardError.connect(
            lambda job_id=context.job.job_id: self._read_stderr(job_id)
        )
        process.started.connect(
            lambda job_id=context.job.job_id: self._process_started(job_id)
        )
        process.errorOccurred.connect(
            lambda error, job_id=context.job.job_id: self._process_error(job_id, error)
        )
        process.finished.connect(
            lambda exit_code, exit_status, job_id=context.job.job_id: self._process_finished(
                job_id, exit_code, exit_status
            )
        )
        process.start()

    def _process_started(self, job_id: str) -> None:
        context = self.active_contexts.get(job_id)
        if not context:
            return
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        context.run.state = "실행 중"
        context.run.process_pid = int(context.process.processId())
        context.run.started_at = context.run.started_at or now
        save_runs([context.run])
        self.log(
            f"작업 시작 {context.attempt_count}/{context.job.retry_limit + 1} "
            f"PID={context.run.process_pid}: {context.job.url}",
            job_id=context.job.job_id,
        )

    def _process_error(self, job_id: str, error: QProcess.ProcessError) -> None:
        context = self.active_contexts.get(job_id)
        if not context:
            return
        message = f"프로세스 오류: {context.process.errorString()} ({error.name})"
        context.job.error = message
        context.job.error_category = "process"
        context.job.retryable_error = True
        self.log(message, "ERROR", job_id)
        if error == QProcess.ProcessError.FailedToStart:
            self._process_finished(job_id, -1, QProcess.ExitStatus.CrashExit)

    def _consume_lines(self, job_id: str, text: str, is_stderr: bool) -> None:
        context = self.active_contexts.get(job_id)
        if not context:
            return
        buffer_name = "stderr_buffer" if is_stderr else "stdout_buffer"
        buffer_value = getattr(context, buffer_name) + text
        while "\n" in buffer_value:
            line, buffer_value = buffer_value.split("\n", 1)
            self._handle_process_line(job_id, line.rstrip("\r"), is_stderr)
        buffer_value, dropped = append_bounded_text(
            "", buffer_value, int(self.resource_limits["maxProcessOutputBytes"])
        )
        setattr(context, buffer_name, buffer_value)
        if dropped:
            dropped_name = (
                "stderr_dropped_bytes" if is_stderr else "stdout_dropped_bytes"
            )
            setattr(context, dropped_name, getattr(context, dropped_name) + dropped)
            self.total_output_dropped_bytes += dropped

    def _read_stdout(self, job_id: str) -> None:
        context = self.active_contexts.get(job_id)
        if context:
            data = bytes(context.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._consume_lines(job_id, data, False)

    def _read_stderr(self, job_id: str) -> None:
        context = self.active_contexts.get(job_id)
        if context:
            data = bytes(context.process.readAllStandardError()).decode("utf-8", errors="replace")
            self._consume_lines(job_id, data, True)

    def _handle_process_line(self, job_id: str, line: str, is_stderr: bool) -> None:
        clean = ANSI_RE.sub("", line).strip()
        if not clean:
            return
        if clean.startswith(EVENT_PREFIX):
            try:
                self._handle_downloader_event(job_id, json.loads(clean[len(EVENT_PREFIX):]))
            except json.JSONDecodeError:
                self.log(f"이벤트 해석 실패: {clean}", "ERROR", job_id)
            return
        self.log(clean, "ERROR" if is_stderr else "INFO", job_id)

    def _handle_downloader_event(self, job_id: str, event: dict[str, Any]) -> None:
        context = self.active_contexts.get(job_id)
        if not context:
            return
        job = context.job
        event_name = event.get("event")
        if event_name == "work_metadata":
            metadata = event.get("metadata") or {}
            job.title = metadata.get("folderName") or metadata.get("title") or job.title
            job.output_path = str(event.get("outputPath") or "")
            job.cover_url = str(metadata.get("coverUrl") or "")
            job.cover_path = str(event.get("coverPath") or "")
            job.author = str(metadata.get("author") or "")
            job.group = str(metadata.get("group") or "")
            source = metadata.get("source") or {}
            job.site = str(source.get("site") or "")
            job.metadata_path = str(Path(job.output_path) / "metadata.json") if job.output_path else ""
            if job.metadata_only:
                delegate = self.task_list.itemDelegate()
                if isinstance(delegate, JobItemDelegate):
                    delegate.cover_cache.clear()
        elif event_name == "queue_ready":
            job.episode_total = int(event.get("selectedEpisodes") or 0)
            skipped = int(event.get("skippedExistingEpisodes") or 0)
            if skipped:
                self.log(
                    f"기존 완료 회차 {skipped}개를 건너뛰었습니다.",
                    job_id=job.job_id,
                )
        elif event_name == "episode_started":
            job.episode_index = int(event.get("index") or 0)
            job.episode_total = int(event.get("total") or job.episode_total)
            job.episode_number = int(event.get("number") or 0)
            job.image_current = 0
            job.image_total = 0
        elif event_name == "images_found":
            job.image_total = int(event.get("count") or 0)
            job.image_current = 0
        elif event_name == "image_saved":
            job.image_current = int(event.get("current") or 0)
            job.image_total = int(event.get("total") or job.image_total)
        elif event_name == "episode_completed":
            job.episode_index = int(event.get("index") or job.episode_index)
        elif event_name == "completed":
            job.progress = 100
        elif event_name == "error":
            job.error = str(event.get("message") or "알 수 없는 오류")
            job.error_category = str(event.get("category") or "unknown")
            job.retryable_error = bool(event.get("retryable", True))

        if job.episode_total:
            fraction = job.image_current / job.image_total if job.image_total else 0.0
            completed_before = max(0, job.episode_index - 1)
            job.progress = min(99, int(((completed_before + fraction) / job.episode_total) * 100))
            if event_name == "episode_completed":
                job.progress = min(99, int((job.episode_index / job.episode_total) * 100))
        if event_name == "completed":
            job.progress = 100
        run = context.run
        run.state = job.state
        run.progress = job.progress
        run.error = job.error
        run.error_category = job.error_category
        run.retryable_error = job.retryable_error
        if event_name == "queue_ready":
            run.discovered_episodes = int(event.get("totalEpisodes") or 0)
            run.selected_episodes = int(event.get("selectedEpisodes") or 0)
        elif event_name in {"episode_started", "episode_completed"}:
            run.processed_episodes = int(event.get("index") or run.processed_episodes)
            run.last_episode_number = int(event.get("number") or job.episode_number)
        policy = downloader_event_update_policy(str(event_name or ""))
        if policy["persistRun"]:
            save_runs([run])
        self._schedule_job_card_update(job, str(event_name or ""))

    def _process_finished(
        self,
        job_id: str,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        context = self.active_contexts.get(job_id)
        if not context:
            return
        if isinstance(context.process, HiddenProcess):
            hidden_drops = context.process.droppedOutputBytes()
            context.stdout_dropped_bytes += int(hidden_drops.get("stdout") or 0)
            context.stderr_dropped_bytes += int(hidden_drops.get("stderr") or 0)
            self.total_output_dropped_bytes += sum(hidden_drops.values())
        dropped_output = context.stdout_dropped_bytes + context.stderr_dropped_bytes
        if dropped_output:
            self.log(
                f"프로세스 출력 메모리 상한으로 {dropped_output:,}바이트를 생략했습니다.",
                "WARNING",
                job_id,
            )
        if context.stdout_buffer.strip():
            self._handle_process_line(job_id, context.stdout_buffer, False)
        if context.stderr_buffer.strip():
            self._handle_process_line(job_id, context.stderr_buffer, True)
        context.stdout_buffer = ""
        context.stderr_buffer = ""
        self.pending_job_ui_updates.discard(job_id)
        job = context.job
        if should_auto_retry(
            exit_code=exit_code,
            cancel_requested=context.cancel_requested,
            attempt_count=context.attempt_count,
            retry_limit=job.retry_limit,
            error_category=job.error_category,
            retryable_hint=job.retryable_error,
        ):
            retry_number = context.attempt_count
            delay = retry_backoff_seconds(retry_number, job.retry_backoff_seconds)
            job.state = "재시도 대기"
            if not job.error:
                job.error = f"프로세스 종료 코드 {exit_code}"
            context.run.state = job.state
            context.run.error = job.error
            context.run.progress = job.progress
            context.retry_generation += 1
            generation = context.retry_generation
            if context.process:
                context.process.deleteLater()
            context.process = None
            save_runs([context.run])
            self._update_job_card(job)
            self.log(
                f"자동 재시도 {retry_number}/{job.retry_limit}: {delay}초 후 실행",
                "ERROR",
                job_id,
            )
            self._update_active_summary()
            QTimer.singleShot(
                delay * 1000,
                lambda job_id=job_id, generation=generation: self._restart_context(
                    job_id, generation
                ),
            )
            return
        if context.cancel_requested:
            job.state = "중지됨"
        elif exit_code == 0:
            job.state = "완료"
            job.progress = 100
        else:
            job.state = (
                "인증 필요"
                if job.error_category == "authentication_required"
                else "오류"
            )
            if not job.error:
                job.error = f"프로세스 종료 코드 {exit_code}"
        self.log(f"작업 종료: {job.state} (code={exit_code})", job_id=job.job_id)
        context.run.state = job.state
        context.run.progress = job.progress
        context.run.error = job.error
        context.run.error_category = job.error_category
        context.run.retryable_error = job.retryable_error
        context.run.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        save_runs([context.run])
        self.active_contexts.pop(job_id, None)
        self._update_job_card(job)
        if (
            self.active_detail_dialog
            and self.active_detail_dialog.job.work_key == job.work_key
        ):
            self.active_detail_dialog.job = job
            self.active_detail_dialog.refresh()
        self._update_active_summary()
        self._notify_job_result(job)
        if job.state == "완료" and self.config.get("pdfGenerationEnabled", False):
            self._queue_automatic_pdf_generation(job.job_id)
        QTimer.singleShot(250, self._start_next_job)

    def _restart_context(self, job_id: str, generation: int) -> None:
        context = self.active_contexts.get(job_id)
        if (
            not context
            or context.cancel_requested
            or context.retry_generation != generation
            or context.job.state != "재시도 대기"
        ):
            return
        self._launch_context(context)

    def stop_active_job(self, job_id: str | None = None) -> bool:
        context = self._resolve_active_context(job_id)
        if not context:
            self.log("중지할 실행 작업이 없습니다.")
            return False
        context.cancel_requested = True
        context.retry_generation += 1
        process = context.process
        pid = int(process.processId()) if process else 0
        self.log(f"작업 중지 요청: PID {pid}", job_id=context.job.job_id)
        if pid and os.name == "nt":
            subprocess.Popen(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            if process and process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
            else:
                self._process_finished(job_id or context.job.job_id, -1, QProcess.ExitStatus.CrashExit)
        return True

    def pause_active_job(self, job_id: str | None = None) -> dict[str, Any]:
        context = self._resolve_active_context(job_id, required=True)
        if context.paused:
            raise ValueError(f"이미 일시정지된 작업입니다: {context.job.job_id}")
        if not context.process or context.job.state != "실행 중":
            raise ValueError("재시도 대기 중인 작업은 일시정지할 수 없습니다.")
        pid = int(context.process.processId())
        affected = set_process_tree_paused(pid, True)
        set_job_pause_state(context.job, context.run, paused=True)
        context.paused = True
        save_runs([context.run])
        self._update_job_card(context.job)
        self._update_active_summary()
        self.log(
            f"작업 일시정지: PID {pid}, 프로세스 {len(affected)}개",
            job_id=context.job.job_id,
        )
        return {"paused": True, "jobId": context.job.job_id, "processIds": affected}

    def resume_active_job(self, job_id: str | None = None) -> dict[str, Any]:
        context = self._resolve_active_context(job_id, required=True)
        if not context.paused:
            raise ValueError("현재 작업은 일시정지 상태가 아닙니다.")
        if not context.process:
            raise ValueError("계속할 프로세스가 없습니다.")
        pid = int(context.process.processId())
        affected = set_process_tree_paused(pid, False)
        set_job_pause_state(context.job, context.run, paused=False)
        context.paused = False
        save_runs([context.run])
        self._update_job_card(context.job)
        self._update_active_summary()
        self.log(
            f"작업 계속: PID {pid}, 프로세스 {len(affected)}개",
            job_id=context.job.job_id,
        )
        return {"resumed": True, "jobId": context.job.job_id, "processIds": affected}

    def _resolve_active_context(
        self,
        job_id: str | None = None,
        *,
        required: bool = False,
    ) -> ProcessContext | None:
        requested = job_id if isinstance(job_id, str) and job_id else ""
        if requested:
            context = self.active_contexts.get(requested)
            if context:
                return context
            raise ValueError(f"지정한 작업은 현재 실행 중이 아닙니다: {requested}")
        selected = self.selected_job()
        if selected and selected.job_id in self.active_contexts:
            return self.active_contexts[selected.job_id]
        if len(self.active_contexts) == 1:
            return next(iter(self.active_contexts.values()))
        if required or self.active_contexts:
            raise ValueError("여러 작업이 실행 중입니다. 작업 ID를 지정해주세요.")
        return None

    def _update_active_summary(self) -> None:
        self._sync_sleep_prevention()
        contexts = list(self.active_contexts.values())
        if not contexts:
            self.status_label.setText("준비")
            self.overall_progress.setValue(0)
            self._update_tray_status()
            return
        paused_count = sum(context.paused for context in contexts)
        retry_wait_count = sum(
            context.job.state == "재시도 대기" for context in contexts
        )
        running_count = len(contexts) - paused_count - retry_wait_count
        average = round(sum(context.job.progress for context in contexts) / len(contexts))
        self.overall_progress.setValue(average)
        self.status_label.setText(
            f"실행 {running_count} · 재시도 대기 {retry_wait_count} · "
            f"일시정지 {paused_count} · 평균 {average}%"
        )
        self._update_tray_status()

    def pause_selected_active_job(self, job_id: str | None = None) -> None:
        try:
            self.pause_active_job(job_id if isinstance(job_id, str) else None)
        except (ValueError, RuntimeError, OSError) as error:
            QMessageBox.warning(self, "작업을 일시정지할 수 없음", str(error))
            self.log(str(error), "ERROR")

    def resume_selected_active_job(self, job_id: str | None = None) -> None:
        try:
            self.resume_active_job(job_id if isinstance(job_id, str) else None)
        except (ValueError, RuntimeError, OSError) as error:
            QMessageBox.warning(self, "작업을 계속할 수 없음", str(error))
            self.log(str(error), "ERROR")

    def cancel_queued_job(self, job_id: str) -> dict[str, Any]:
        clean_job_id = str(job_id or "").strip()
        pending = next(
            (job for job in self.pending_jobs if job.job_id == clean_job_id),
            None,
        )
        if not pending:
            raise ValueError(f"대기 중인 작업을 찾을 수 없습니다: {clean_job_id}")
        self.pending_jobs.remove(pending)
        self._refresh_pending_positions()
        mark_job_cancelled(pending)
        run = load_run(pending.job_id) or DownloadRun.from_job(pending)
        mark_run_cancelled(run)
        save_runs([run])
        self._update_job_card(pending)
        self.log("대기 작업 취소", job_id=pending.job_id)
        return {"cancelled": True, "job": pending.to_dict(), "run": run.to_dict()}

    def _refresh_pending_positions(self) -> None:
        for index, pending in enumerate(self.pending_jobs, start=1):
            if pending.queue_position != index:
                pending.queue_position = index
                self.task_model.update_job(pending)
                self._schedule_job_persist(pending)

    def pending_queue_snapshot(self) -> dict[str, Any]:
        return {
            "total": len(self.pending_jobs),
            "jobs": [job.to_dict() for job in self.pending_jobs],
        }

    def move_queued_job(
        self,
        job_id: str,
        *,
        before_job_id: str = "",
        position: str = "",
    ) -> dict[str, Any]:
        reordered = reorder_pending_jobs(
            list(self.pending_jobs),
            job_id,
            before_job_id=before_job_id,
            position=position,
        )
        self.pending_jobs = deque(reordered)
        self._refresh_pending_positions()
        order = [job.job_id for job in self.pending_jobs]
        self.log(f"대기열 순서 변경: {' > '.join(order)}", job_id=job_id)
        self._update_summary()
        return {"moved": True, "jobId": job_id, "order": order}

    def cancel_selected_queued_job(self, job_id: str) -> None:
        try:
            self.cancel_queued_job(job_id)
        except (ValueError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, "대기 작업을 취소할 수 없음", str(error))
            self.log(str(error), "ERROR", job_id)

    def selected_job(self, job_id: str | None = None) -> DownloadJob | None:
        if job_id:
            return self.jobs.get(job_id) or load_job_by_id(job_id)
        index = self.task_list.currentIndex()
        if index.isValid():
            return self.task_model.job_at(index.row())
        first_active = next(iter(self.active_contexts.values()), None)
        if first_active:
            return first_active.job
        return next(reversed(self.jobs.values()), None) if self.jobs else None

    def retry_job(self, job_id: str | None = None) -> DownloadJob | None:
        return self.rescan_job(job_id, "full")

    def rescan_job(
        self,
        job_id: str | None,
        mode: str,
        start: int | None = None,
        last: int | None = None,
    ) -> DownloadJob | None:
        source = self.selected_job(job_id)
        if not source:
            self.log("재검사할 작품을 선택해주세요.")
            return None
        parameters = rescan_job_parameters(source, mode, start, last)
        return self.enqueue_download(**parameters)

    def retry_selected_job(self) -> None:
        try:
            self.retry_job()
        except (ValueError, OSError, RuntimeError) as error:
            QMessageBox.warning(self, "작업을 재시도할 수 없음", str(error))
            self.log(str(error), "ERROR")

    def rescan_selected_job(self, mode: str, job_id: str | None = None) -> None:
        try:
            start = self.start_spin.value() or None if mode == "range" else None
            last = self.last_spin.value() or None if mode == "range" else None
            self.rescan_job(job_id, mode, start, last)
        except (ValueError, OSError, RuntimeError) as error:
            QMessageBox.warning(self, "작품을 재검사할 수 없음", str(error))
            self.log(str(error), "ERROR")

    def refresh_job_metadata(self, job_id: str | None = None) -> DownloadJob:
        source = self.selected_job(job_id)
        if not source:
            raise ValueError("메타데이터를 새로고칠 작품을 선택해주세요.")
        if source.state in ACTIVE_JOB_STATES:
            raise ValueError("대기 또는 실행 중인 작품은 메타데이터를 새로고칠 수 없습니다.")
        return self.enqueue_download(
            source.url,
            None,
            None,
            source.output_dir,
            False,
            metadata_only=True,
        )

    def refresh_selected_metadata(self, job_id: str | None = None) -> None:
        try:
            self.refresh_job_metadata(job_id)
        except (ValueError, OSError, RuntimeError) as error:
            QMessageBox.warning(self, "메타데이터를 새로고칠 수 없음", str(error))
            self.log(str(error), "ERROR")

    def choose_output_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.output_edit.text())
        if selected:
            self.set_output_folder(selected)

    def show_settings_dialog(self, tab: str = "general", search: str = "") -> bool:
        if self.active_settings_dialog:
            self.active_settings_dialog.close()
        dialog = SettingsDialog(self)
        tab_index = {
            "general": 0,
            "network": 1,
            "display": 2,
            "advanced": 3,
            "provider": 4,
        }.get(str(tab), 0)
        dialog.tabs.setCurrentIndex(tab_index)
        dialog.set_search_query(search)
        self.active_settings_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_settings_dialog", None)
                if self.active_settings_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log("설정 창 표시")
        return True

    def show_cookie_manager(self, provider: str = "manatoki") -> bool:
        if self.active_cookie_manager_dialog:
            self.active_cookie_manager_dialog.close()
        dialog = CookieManagerDialog(self)
        index = dialog.provider_combo.findData(str(provider or "manatoki"))
        if index >= 0:
            dialog.provider_combo.setCurrentIndex(index)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(
            lambda _object=None: setattr(self, "active_cookie_manager_dialog", None)
        )
        self.active_cookie_manager_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def show_hitomi_inspector(
        self,
        reference: str | bool = "",
        provider: str = "auto",
    ) -> dict[str, Any]:
        safe_reference = reference if isinstance(reference, str) else ""
        if self.active_hitomi_inspector_dialog:
            self.active_hitomi_inspector_dialog.close()
        dialog = HitomiReferenceDialog(self, safe_reference, provider)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(
            lambda _object=None: setattr(
                self, "active_hitomi_inspector_dialog", None
            )
        )
        self.active_hitomi_inspector_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log("Hitomi URL/ID 분석창 표시")
        return {"shown": True, **dialog.state_snapshot()}

    def close_hitomi_inspector(self) -> bool:
        if not self.active_hitomi_inspector_dialog:
            return False
        self.active_hitomi_inspector_dialog.close()
        return True

    def show_hitomi_metadata(
        self,
        reference: str | bool = "",
        provider: str = "auto",
        fixture: str = "",
    ) -> dict[str, Any]:
        safe_reference = reference if isinstance(reference, str) else ""
        if self.active_hitomi_metadata_dialog:
            self.active_hitomi_metadata_dialog.close()
        dialog = HitomiMetadataDialog(
            self,
            safe_reference,
            str(provider or "auto"),
            str(fixture or ""),
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(
            lambda _object=None: setattr(
                self, "active_hitomi_metadata_dialog", None
            )
        )
        self.active_hitomi_metadata_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log("Hitomi 메타데이터 창 표시")
        return {"shown": True, **dialog.state_snapshot()}

    def close_hitomi_metadata(self) -> bool:
        if not self.active_hitomi_metadata_dialog:
            return False
        self.active_hitomi_metadata_dialog.close()
        return True

    def show_embedded_browser(
        self,
        url: str = "",
        *,
        navigate: bool = False,
        confirmed: bool = False,
    ) -> bool:
        if self.active_embedded_browser_dialog:
            self.active_embedded_browser_dialog.close()
        dialog = EmbeddedBrowserDialog(
            self,
            url,
            navigate=navigate,
            confirmed=confirmed,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(
            lambda _object=None: setattr(self, "active_embedded_browser_dialog", None)
        )
        self.active_embedded_browser_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def close_embedded_browser(self) -> bool:
        if not self.active_embedded_browser_dialog:
            return False
        self.active_embedded_browser_dialog.close()
        return True

    def show_proxy_credential_manager(self) -> bool:
        if self.active_proxy_credential_dialog:
            self.active_proxy_credential_dialog.close()
        dialog = ProxyCredentialDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(
            lambda _object=None: setattr(self, "active_proxy_credential_dialog", None)
        )
        self.active_proxy_credential_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def close_proxy_credential_manager(self) -> bool:
        if not self.active_proxy_credential_dialog:
            return False
        self.active_proxy_credential_dialog.close()
        return True

    def close_cookie_manager(self) -> bool:
        if not self.active_cookie_manager_dialog:
            return False
        self.active_cookie_manager_dialog.close()
        return True

    def export_jobs_snapshot_now(self, output_path: str) -> dict[str, Any]:
        result = export_jobs_snapshot(Path(output_path))
        message = (
            f"작업 스냅샷 내보내기: 작품 {result['jobCount']}개, "
            f"실행 {result['runCount']}개"
        )
        self.log(message)
        self.statusBar().showMessage(message, 5000)
        return result

    def choose_jobs_snapshot_export(self) -> dict[str, Any] | None:
        default_path = str(
            LOG_PATH.parent
            / f"toki-jobs-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}.json"
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self, "작업 스냅샷 내보내기", default_path, "JSON 파일 (*.json)"
        )
        return self.export_jobs_snapshot_now(selected) if selected else None

    def choose_jobs_snapshot_import(self) -> bool:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "작업 스냅샷 가져오기", str(LOG_PATH.parent), "JSON 파일 (*.json)"
        )
        return self.show_jobs_snapshot_import(selected) if selected else False

    def show_jobs_snapshot_import(self, input_path: str) -> bool:
        result = import_jobs_snapshot(Path(input_path), execute=False)
        if self.active_jobs_snapshot_dialog:
            self.active_jobs_snapshot_dialog.close()
        dialog = JobsSnapshotImportDialog(self, str(Path(input_path).resolve()), result)
        self.active_jobs_snapshot_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_jobs_snapshot_dialog", None)
                if self.active_jobs_snapshot_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log("작업 스냅샷 가져오기 미리보기 표시")
        return True

    def execute_jobs_snapshot_import(self, input_path: str) -> dict[str, Any]:
        result = import_jobs_snapshot(Path(input_path), execute=True)
        self.refresh_job_list()
        message = (
            f"작업 스냅샷 가져오기: 작품 {result['importedJobs']}개, "
            f"실행 {result['importedRuns']}개"
        )
        self.log(message)
        self.statusBar().showMessage(message, 5000)
        return result

    def close_jobs_snapshot_dialog(self) -> bool:
        if not self.active_jobs_snapshot_dialog:
            return False
        self.active_jobs_snapshot_dialog.close()
        return True

    def list_groups_snapshot(self) -> dict[str, Any]:
        groups = list_work_collections()
        return {"ok": True, "count": len(groups), "groups": groups}

    def create_work_group(self, name: str) -> dict[str, Any]:
        result = create_work_collection(name)
        if self.active_group_manager_dialog:
            self.active_group_manager_dialog.refresh()
        self.log(f"작품 그룹 생성: {result['name']}")
        return result

    def rename_work_group(self, group_id: str, name: str) -> dict[str, Any]:
        result = rename_work_collection(group_id, name)
        if self.active_group_manager_dialog:
            self.active_group_manager_dialog.refresh()
        self.log(f"작품 그룹 이름 변경: {result['name']}")
        return result

    def assign_work_group(self, job_id: str, group_id: str) -> dict[str, Any]:
        result = assign_job_to_collection(job_id, group_id or None)
        if self.active_group_manager_dialog:
            self.active_group_manager_dialog.refresh()
        label = result["group"]["name"] if result.get("group") else "미분류"
        self.log(f"작품 정리 그룹: {label}", job_id=job_id)
        self.statusBar().showMessage(f"작품을 {label} 그룹으로 이동했습니다.", 3500)
        return result

    def show_group_manager(self) -> bool:
        if self.active_group_manager_dialog:
            self.active_group_manager_dialog.show()
            self.active_group_manager_dialog.raise_()
            self.active_group_manager_dialog.activateWindow()
            return True
        dialog = WorkGroupManagerDialog(self)
        self.active_group_manager_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_group_manager_dialog", None)
                if self.active_group_manager_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log("작품 그룹 관리 창 표시")
        return True

    def close_group_manager(self) -> bool:
        if not self.active_group_manager_dialog:
            return False
        self.active_group_manager_dialog.close()
        return True

    def choose_archive_inspection(self) -> bool:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "로컬 압축 작품 검사",
            str(Path(self.output_edit.text() or ROOT_DIR)),
            "압축 작품 (*.zip *.cbz *.7z *.cb7 *.rar *.cbr)",
        )
        return self.show_archive_inspection(selected) if selected else False

    def show_archive_inspection(self, archive_path: str) -> bool:
        result = inspect_local_archive(Path(archive_path))
        result["viewer"] = plan_archive_viewer_open(
            Path(archive_path), config=self.config
        )
        if self.active_archive_inspection_dialog:
            self.active_archive_inspection_dialog.close()
        dialog = ArchiveInspectionDialog(self, result)
        self.active_archive_inspection_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_archive_inspection_dialog", None)
                if self.active_archive_inspection_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log(
            f"로컬 압축 작품 검사: 파일 {result['fileCount']}개, "
            f"의심 경로 {result['suspiciousPathCount']}개"
        )
        return True

    def confirm_open_archive_viewer(self, archive_path: str) -> dict[str, Any]:
        plan = plan_archive_viewer_open(Path(archive_path), config=self.config)
        if not plan["ok"]:
            QMessageBox.warning(self, "연결 프로그램을 사용할 수 없음", plan["error"])
            return plan
        answer = QMessageBox.question(
            self,
            "압축 파일 열기",
            f"{plan['viewerLabel']}으로 다음 파일을 여시겠습니까?\n\n{plan['path']}\n\n"
            "Windows 시스템 파일 연결은 변경하지 않습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return plan
        try:
            result = open_archive_with_viewer(
                Path(archive_path), config=self.config, execute=True
            )
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "압축 파일을 열 수 없음", str(error))
            return {**plan, "ok": False, "error": str(error)}
        self.log(
            f"압축 파일 연결 프로그램 실행: {result['viewerLabel']} · {result['path']}"
        )
        self.statusBar().showMessage("압축 파일을 연결 프로그램으로 열었습니다.", 5000)
        return result

    def close_archive_inspection(self) -> bool:
        if not self.active_archive_inspection_dialog:
            return False
        self.active_archive_inspection_dialog.close()
        return True

    def recover_interrupted_records(self, *, execute: bool = False) -> dict[str, Any]:
        active_ids = sorted(getattr(self, "active_contexts", {}))
        pending_ids = [
            job.job_id for job in getattr(self, "pending_jobs", ())
        ]
        if active_ids or pending_ids:
            return {
                "ok": False,
                "executed": False,
                "blocked": True,
                "jobCount": 0,
                "runCount": 0,
                "jobIds": [],
                "runIds": [],
                "activeJobIds": active_ids,
                "pendingJobIds": pending_ids,
                "error": "현재 실행 또는 대기 작업이 있어 불완전 기록 복구를 차단했습니다.",
                "filesChanged": False,
            }
        if execute:
            self._flush_job_history()
        result = {
            **recover_interrupted_jobs(execute=execute),
            "blocked": False,
        }
        if execute:
            for job_id in result["jobIds"]:
                stored = load_job_by_id(job_id)
                if stored is None:
                    continue
                previous = self.jobs.get(job_id)
                if previous is not None:
                    self.jobs_by_work.pop(previous.work_key, None)
                self.jobs[job_id] = stored
                self.jobs_by_work[stored.work_key] = stored
                self.task_model.update_job(stored)
            self.last_manual_recovery = result
            self._update_summary()
            self.log(
                "수동 불완전 기록 복구: "
                f"작품 {result['jobCount']}개, 실행 {result['runCount']}개"
            )
        return result

    def persistence_status_snapshot(self) -> dict[str, Any]:
        recovery = self.recover_interrupted_records(execute=False)
        return {
            "ok": True,
            "policy": persistence_policy_snapshot(self.config),
            "recovery": recovery,
            "startupRecovery": self.startup_recovery,
            "lastManualRecovery": self.last_manual_recovery,
            "dirtyJobCount": len(self.dirty_job_ids),
            "autosaveTimerActive": self.persist_timer.isActive(),
            "autosaveRemainingMs": max(0, int(self.persist_timer.remainingTime())),
            "lastAutosave": self.last_autosave,
            "guiRunning": True,
        }

    def list_performance_status_snapshot(self) -> dict[str, Any]:
        policy = list_performance_policy_snapshot(self.config)
        return {
            "ok": True,
            **policy,
            "live": {
                "pageSize": self.history_page_size,
                "loadedLimit": int(self.resource_limits["maxLoadedJobs"]),
                "loadedJobs": self.task_model.rowCount(),
                "catalogTotal": self.history_total,
                "lazyLoading": bool(
                    self.list_performance_policy["effective"]["lazyLoading"]
                ),
                "scrollPixelStep": self.task_list.verticalScrollBar().singleStep(),
            },
        }

    def _running_download_count(self) -> int:
        return sum(
            1
            for context in self.active_contexts.values()
            if context.job.state == "실행 중" and not context.paused
        )

    def _sync_sleep_prevention(self) -> dict[str, Any]:
        running = self._running_download_count()
        required = bool(self.config.get("preventSleepDuringDownloads", False)) and running > 0
        before = self.sleep_prevention_controller.snapshot()
        runtime = self.sleep_prevention_controller.set_required(required)
        snapshot = sleep_prevention_policy_snapshot(
            self.config,
            active_downloads=running,
            controller=runtime,
        )
        previous_error = str(self.last_sleep_prevention.get("lastError") or "")
        if bool(before.get("active")) != bool(runtime.get("active")):
            self.log(
                "다운로드 중 시스템 절전 방지 활성화"
                if runtime.get("active")
                else "다운로드 중 시스템 절전 방지 해제"
            )
        if snapshot.get("lastError") and snapshot["lastError"] != previous_error:
            self.log(
                f"시스템 절전 방지 요청 실패: {snapshot['lastError']}",
                "ERROR",
            )
        self.last_sleep_prevention = snapshot
        return snapshot

    def sleep_prevention_status_snapshot(self) -> dict[str, Any]:
        return sleep_prevention_policy_snapshot(
            self.config,
            active_downloads=self._running_download_count(),
            controller=self.sleep_prevention_controller,
        )

    def show_recovery_dialog(self) -> bool:
        result = self.recover_interrupted_records(execute=False)
        if self.active_recovery_dialog:
            self.active_recovery_dialog.close()
        dialog = RecoveryStatusDialog(self, result)
        self.active_recovery_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_recovery_dialog", None)
                if self.active_recovery_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def close_recovery_dialog(self) -> bool:
        if not self.active_recovery_dialog:
            return False
        self.active_recovery_dialog.close()
        return True

    def confirm_recover_interrupted_records(self) -> dict[str, Any]:
        preview = self.recover_interrupted_records(execute=False)
        if not preview.get("ok") or not (
            preview.get("jobCount") or preview.get("runCount")
        ):
            return preview
        answer = QMessageBox.question(
            self,
            "불완전 기록 복구",
            f"작품 {preview['jobCount']}개와 실행 이력 {preview['runCount']}개를 "
            "중지됨으로 복구하시겠습니까?\n\n진행률과 다운로드 파일은 보존됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return preview
        return self.recover_interrupted_records(execute=True)

    def show_duplicate_works(self) -> bool:
        result = find_duplicate_works()
        if self.active_duplicate_works_dialog:
            self.active_duplicate_works_dialog.close()
        dialog = DuplicateWorksDialog(result, self)
        self.active_duplicate_works_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_duplicate_works_dialog", None)
                if self.active_duplicate_works_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log(
            f"중복 의심 작품 검사: 그룹 {result['duplicateGroupCount']}개, "
            f"관련 작품 {result['duplicateWorkCount']}개"
        )
        return True

    def close_duplicate_works(self) -> bool:
        if not self.active_duplicate_works_dialog:
            return False
        self.active_duplicate_works_dialog.close()
        return True

    def start_duplicate_images(
        self, job_id: str | None = None, algorithm: str = "sha256"
    ) -> dict[str, Any]:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("이미지 중복을 검사할 작품을 선택해주세요.")
        if job.job_id in self.duplicate_image_tasks:
            return {"started": False, "jobId": job.job_id, "alreadyRunning": True}
        tracked = (
            len(self.file_verify_processes)
            + len(self.image_preview_processes)
            + len(self.duplicate_image_tasks)
        )
        active = self.io_thread_pool.activeThreadCount()
        admission = resource_admission(
            "io",
            active_count=active,
            queued_count=max(0, tracked - active),
            budget=self.resource_limits,
        )
        if not admission["allowed"]:
            return {
                "started": False,
                "jobId": job.job_id,
                "resourceLimit": True,
                "resources": admission,
            }
        selected_algorithm = str(algorithm or "sha256").lower()
        task = ServiceTask(
            job.job_id,
            lambda: find_duplicate_images(job.job_id, algorithm=selected_algorithm),
        )
        task.signals.finished.connect(self._duplicate_images_finished)
        self.duplicate_image_tasks[job.job_id] = task
        self.io_thread_pool.start(task)
        self.log(
            f"중복 이미지 검사 시작({selected_algorithm}, 자원 풀)", job_id=job.job_id
        )
        self.statusBar().showMessage(f"{job.title} 중복 이미지 검사 중…")
        return {
            "started": True,
            "jobId": job.job_id,
            "algorithm": selected_algorithm,
            "resources": admission,
        }

    def _duplicate_images_finished(
        self, job_id: str, result: dict[str, Any], error: str
    ) -> None:
        task = self.duplicate_image_tasks.pop(job_id, None)
        if task is None:
            return
        if error:
            self.log(f"중복 이미지 검사 실패: {error}", "ERROR", job_id)
            QMessageBox.critical(self, "중복 이미지 검사 실패", error)
            return
        if self.active_duplicate_images_dialog:
            self.active_duplicate_images_dialog.close()
        dialog = DuplicateImagesDialog(result, self)
        self.active_duplicate_images_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_duplicate_images_dialog", None)
                if self.active_duplicate_images_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log(
            f"중복 이미지 검사 완료: 그룹 {result['duplicateGroupCount']}개, "
            f"관련 이미지 {result['duplicateImageCount']}장",
            job_id=job_id,
        )

    def close_duplicate_images(self) -> bool:
        if not self.active_duplicate_images_dialog:
            return False
        self.active_duplicate_images_dialog.close()
        return True

    def completion_action_snapshot(self) -> dict[str, Any]:
        plan = completion_action_plan(
            str(self.config.get("completionAction") or "none"),
            int(self.config.get("completionCountdownSeconds") or 15),
            active_count=(
                len(self.active_contexts) + len(self.pdf_generation_processes)
            ),
            pending_count=len(self.pending_jobs) + len(self.pending_pdf_jobs),
            armed=self.completion_action_armed,
        )
        dialog = self.active_completion_dialog
        return {
            **plan,
            "dialog": dialog.state_snapshot() if dialog else {"open": False},
            "last": self.last_completion_action,
        }

    def inspect_clipboard_text(
        self, text: str, *, prompt: bool = False
    ) -> dict[str, Any]:
        first = inspect_clipboard_url(text, existing_work_keys=set(self.jobs_by_work))
        if first.get("candidate") and not first.get("duplicate"):
            stored = load_job_by_work_key(str(first["workKey"]))
            if stored:
                first = inspect_clipboard_url(
                    text, existing_work_keys={stored.work_key}
                )
        result = {
            **first,
            "monitorEnabled": bool(self.config.get("clipboardMonitor", False)),
            "prompted": False,
            "accepted": False,
            "enqueued": False,
        }
        self.last_clipboard_inspection = result
        if not result.get("candidate"):
            return result
        if result.get("duplicate"):
            self.statusBar().showMessage("이미 등록된 작품 URL입니다.", 3000)
            return result
        if not prompt:
            return result
        result["prompted"] = True
        answer = QMessageBox.question(
            self,
            "클립보드 작품 URL 감지",
            f"새 작품 URL을 감지했습니다. 다운로드 작업에 추가할까요?\n\n{result['url']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        result["accepted"] = answer == QMessageBox.StandardButton.Yes
        if result["accepted"]:
            self.url_edit.setText(str(result["url"]))
            self.start_from_form()
            result["enqueued"] = True
        self.last_clipboard_inspection = result
        return result

    def _clipboard_changed(self) -> None:
        if not bool(self.config.get("clipboardMonitor", False)):
            return
        text = QApplication.clipboard().text().strip()
        if not text or text == self.last_clipboard_text:
            return
        self.last_clipboard_text = text
        self.inspect_clipboard_text(text, prompt=True)

    def preview_completion_action(
        self, action: str, countdown_seconds: int
    ) -> dict[str, Any]:
        plan = completion_action_plan(action, countdown_seconds, armed=True)
        self._show_completion_countdown(
            plan["action"], plan["countdownSeconds"], preview=True
        )
        return {**plan, "shown": True, "executed": False}

    def _show_completion_countdown(
        self, action: str, countdown_seconds: int, *, preview: bool
    ) -> None:
        self.cancel_completion_action()
        dialog = CompletionCountdownDialog(
            action, countdown_seconds, preview=preview, parent=self
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.finished.connect(
            lambda result, current=dialog, execute=not preview: self._completion_dialog_finished(
                current, result, execute
            )
        )
        dialog.destroyed.connect(
            lambda *_: setattr(self, "active_completion_dialog", None)
        )
        self.active_completion_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def cancel_completion_action(self) -> bool:
        dialog = self.active_completion_dialog
        if not dialog:
            return False
        dialog.reject()
        return True

    def _completion_dialog_finished(
        self, dialog: CompletionCountdownDialog, result: int, execute: bool
    ) -> None:
        accepted = result == int(QDialog.DialogCode.Accepted)
        self.last_completion_action = {
            "action": dialog.action,
            "accepted": accepted,
            "executed": bool(accepted and execute),
            "preview": dialog.preview,
            "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if accepted and execute:
            self._execute_completion_action(dialog.action)

    def _maybe_trigger_completion_action(self) -> None:
        plan = self.completion_action_snapshot()
        if not plan["shouldTrigger"]:
            return
        self.completion_action_armed = False
        self.last_completion_action = {**plan, "triggered": True}
        self._show_completion_countdown(
            str(plan["action"]), int(plan["countdownSeconds"]), preview=False
        )

    def _execute_completion_action(self, action: str) -> None:
        if action == "exit":
            QTimer.singleShot(0, self.request_exit)
            return
        if action != "shutdown":
            return
        if os.name != "nt":
            self.log("시스템 종료는 현재 Windows에서만 지원합니다.", "ERROR")
            return
        subprocess.Popen(
            ["shutdown.exe", "/s", "/t", "0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_process_options(),
        )

    def close_settings_dialog(self) -> bool:
        if not self.active_settings_dialog:
            return False
        self.active_settings_dialog.close()
        return True

    def apply_settings(
        self, updates: dict[str, Any], *, reset: bool = False
    ) -> dict[str, Any]:
        result = update_app_settings(updates, reset=reset)
        self.config.update(result)
        self.strings = load_ui_strings(result.get("uiLanguage"))
        MainWindow._apply_language_strings(self)
        self.output_edit.setText(str(result["outputDir"]))
        self.show_browser_check.setChecked(bool(result["showBrowser"]))
        widgets = (
            self.work_concurrency_spin,
            self.image_concurrency_spin,
            self.retry_count_spin,
            self.retry_backoff_spin,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.work_concurrency_spin.setValue(int(result["workConcurrency"]))
            self.image_concurrency_spin.setValue(int(result["imageConcurrency"]))
            self.retry_count_spin.setValue(int(result["retryCount"]))
            self.retry_backoff_spin.setValue(int(result["retryBackoffSeconds"]))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.log_box.setVisible(bool(result["logVisible"]))
        self.theme_mode = str(result["theme"])
        self.resolved_theme = self._resolve_theme(self.theme_mode)
        self._apply_style()
        self._apply_display_preferences(result)
        configure_memory = getattr(self, "_configure_memory_display", None)
        if callable(configure_memory):
            configure_memory()
        configure_local_api = getattr(self, "_configure_local_api", None)
        if callable(configure_local_api):
            configure_local_api()
        sync_sleep = getattr(self, "_sync_sleep_prevention", None)
        if callable(sync_sleep):
            sync_sleep()
        if {
            "listPageSize",
            "listLoadedLimit",
            "listScrollLines",
            "listLazyLoading",
            "lowSpecMode",
        } & set(updates):
            reload_list = getattr(self, "apply_history_filters", None)
            if callable(reload_list):
                QTimer.singleShot(0, reload_list)
        self._apply_keyboard_shortcuts()
        persist_timer = getattr(self, "persist_timer", None)
        if persist_timer is not None:
            persist_timer.setInterval(
                int(result.get("autosaveIntervalSeconds") or 1) * 1000
            )
            if getattr(self, "dirty_job_ids", set()):
                persist_timer.stop()
                persist_timer.start()
        delegate = self.task_list.itemDelegate()
        if isinstance(delegate, JobItemDelegate):
            delegate.set_density(str(result["rowDensity"]))
            delegate.set_theme(self.resolved_theme)
            delegate.set_view_preferences(
                str(result["listViewMode"]),
                bool(result["thumbnailsVisible"]),
                str(result["thumbnailSize"]),
            )
            self.task_list.setUniformItemSizes(False)
            self.task_list.doItemsLayout()
            self.task_list.setUniformItemSizes(True)
            self.task_list.viewport().update()
        if self.active_settings_dialog:
            self.active_settings_dialog._load_values(result)
        self._configure_tray()
        self.log(
            "설정 저장: 작품 동시성 "
            f"{result['workConcurrency']}, 이미지 {result['imageConcurrency']}, "
            f"재시도 {result['retryCount']}회"
        )
        QTimer.singleShot(0, self._start_next_job)
        return result

    def _keyboard_action_map(self) -> dict[str, QAction]:
        candidates = {
            "download.start": "start_action",
            "job.stop": "stop_action",
            "job.pause": "pause_action",
            "job.resume": "resume_action",
            "job.rescan_full": "retry_action",
            "job.rescan_new": "new_scan_action",
            "job.rescan_range": "range_scan_action",
            "snapshot.export": "export_jobs_action",
            "snapshot.import": "import_jobs_action",
            "group.manage": "group_manager_action",
            "archive.inspect": "archive_inspection_action",
            "duplicates.works": "duplicate_works_action",
            "folder.open": "open_folder_action",
            "details.open": "details_action",
            "list.activate": "activate_selected_action",
            "list.refresh": "refresh_list_action",
            "focus.url": "focus_url_action",
            "focus.search": "focus_search_action",
            "focus.cycle": "focus_cycle_action",
            "selection.previous": "select_previous_action",
            "selection.next": "select_next_action",
            "search.clear": "clear_search_action",
            "screenshot.capture": "screenshot_action",
            "settings.open": "settings_action",
        }
        return {
            action_id: action
            for action_id, attribute in candidates.items()
            if isinstance((action := getattr(self, attribute, None)), QAction)
        }

    def _apply_keyboard_shortcuts(self) -> None:
        for action_id, action in self._keyboard_action_map().items():
            action.setShortcuts(
                [
                    QKeySequence(key)
                    for key in keyboard_shortcut_keys(action_id, self.config)
                ]
            )

    def apply_shortcut_overrides(
        self, overrides: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = normalize_shortcut_overrides(overrides)
        self.apply_settings({"shortcutOverrides": normalized})
        snapshot = shortcut_settings_snapshot(self.config)
        self.log(
            f"단축키 적용: 사용자 지정 {snapshot['overrideCount']}개, "
            f"비활성 {snapshot['disabledCount']}개"
        )
        return snapshot

    def _apply_language_strings(self) -> None:
        menu_keys = (
            (getattr(self, "work_menu", None), "main.menu.work"),
            (getattr(self, "tools_menu", None), "main.menu.tools"),
            (getattr(self, "view_menu", None), "main.menu.view"),
            (getattr(self, "help_menu", None), "main.menu.help"),
        )
        for menu, key in menu_keys:
            if menu is not None:
                menu.setTitle(self.strings[key])

    def _apply_display_preferences(self, values: dict[str, Any]) -> None:
        application = QApplication.instance()
        if application is not None:
            font = QFont(str(values.get("fontFamily") or "Malgun Gothic"))
            font.setPointSizeF(9.0 * int(values.get("uiScale") or 100) / 100.0)
            application.setFont(font)
        mode = str(values.get("listViewMode") or "list")
        size = str(values.get("thumbnailSize") or "medium")
        policy = list_performance_policy_snapshot(values)
        self.list_performance_policy = policy
        effective = policy["effective"]
        self.history_page_size = int(effective["pageSize"])
        self.resource_limits["maxLoadedJobs"] = int(effective["loadedLimit"])
        visible = bool(effective["thumbnailsVisible"])
        delegate = self.task_list.itemDelegate()
        if isinstance(delegate, JobItemDelegate):
            delegate.set_view_preferences(mode, visible, size)
            delegate.cache_limit = int(effective["thumbnailCacheEntries"])
            while len(delegate.cover_cache) > delegate.cache_limit:
                delegate.cover_cache.popitem(last=False)
        self.task_list.setLayoutMode(QListView.LayoutMode.Batched)
        self.task_list.setBatchSize(min(100, self.history_page_size))
        self.task_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.task_list.verticalScrollBar().setSingleStep(
            int(effective["scrollLines"]) * 12
        )
        if mode == "icon":
            dimensions = {
                "small": QSize(112, 120),
                "large": QSize(166, 190),
            }.get(size, QSize(136, 150))
            scale = max(75, min(200, int(values.get("uiScale") or 100))) / 100
            dimensions = QSize(
                max(84, round(dimensions.width() * scale)),
                max(90, round(dimensions.height() * scale)),
            )
            self.task_list.setViewMode(QListView.ViewMode.IconMode)
            self.task_list.setFlow(QListView.Flow.LeftToRight)
            self.task_list.setWrapping(True)
            self.task_list.setGridSize(dimensions)
        else:
            self.task_list.setViewMode(QListView.ViewMode.ListMode)
            self.task_list.setFlow(QListView.Flow.TopToBottom)
            self.task_list.setWrapping(False)
            self.task_list.setGridSize(QSize())
        self.task_list.setUniformItemSizes(True)
        self.task_list.doItemsLayout()
        self.task_list.viewport().update()

        always_on_top = bool(values.get("alwaysOnTop", False))
        currently_on_top = bool(
            self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )
        if always_on_top != currently_on_top:
            was_visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, always_on_top)
            if was_visible:
                self.show()
        self.setWindowOpacity(max(0.5, min(1.0, int(values.get("windowOpacity", 100)) / 100)))
        self._rebuild_quick_action_bar(values.get("quickActions") or [])

    def _initial_history_load_limit(self) -> int:
        effective = self.list_performance_policy["effective"]
        return (
            int(effective["pageSize"])
            if effective["lazyLoading"]
            else int(effective["loadedLimit"])
        )

    def _rebuild_quick_action_bar(self, action_ids: list[str]) -> None:
        if not hasattr(self, "quick_action_layout"):
            return
        while self.quick_action_layout.count():
            item = self.quick_action_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.quick_action_buttons = {}
        label = QLabel("빠른 실행")
        label.setObjectName("mutedLabel")
        self.quick_action_layout.addWidget(label)
        action_map = {
            "download.start": self.start_action,
            "job.stop": self.stop_action,
            "job.rescan_full": self.retry_action,
            "folder.open": self.open_folder_action,
            "details.open": self.details_action,
            "duplicates.works": self.duplicate_works_action,
            "settings.open": self.settings_action,
            "screenshot.capture": self.screenshot_action,
        }
        labels = {item["id"]: item["label"] for item in quick_action_catalog()}
        for action_id in action_ids:
            action = action_map.get(action_id)
            if not action:
                continue
            button = QPushButton(labels.get(action_id, action.text()))
            button.setEnabled(action.isEnabled())
            button.clicked.connect(action.trigger)
            self.quick_action_layout.addWidget(button)
            self.quick_action_buttons[action_id] = button
        self.quick_action_layout.addStretch(1)

    def _configure_tray(self) -> None:
        enabled = bool(self.config.get("trayEnabled", False))
        if not enabled or not QSystemTrayIcon.isSystemTrayAvailable():
            if self.tray_icon:
                self.tray_icon.hide()
                self.tray_icon.deleteLater()
            self.tray_icon = None
            self.tray_menu = None
            self.tray_status_action = None
            return
        if self.tray_icon is None:
            tray = QSystemTrayIcon(self.windowIcon(), self)
            tray.setToolTip("tokiDownloader")
            menu = QMenu()
            show_action = menu.addAction("창 표시")
            show_action.triggered.connect(self.show_from_tray)
            hide_action = menu.addAction("창 숨기기")
            hide_action.triggered.connect(self.hide_to_tray)
            menu.addSeparator()
            self.tray_status_action = menu.addAction("준비")
            self.tray_status_action.setEnabled(False)
            menu.addSeparator()
            quit_action = menu.addAction("종료")
            quit_action.triggered.connect(self.request_exit)
            tray.setContextMenu(menu)
            tray.activated.connect(
                lambda reason: self.show_from_tray()
                if reason == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
            self.tray_icon = tray
            self.tray_menu = menu
        self._update_tray_status()
        self.tray_icon.show()

    def _update_tray_status(self) -> None:
        if not self.tray_status_action:
            return
        self.tray_status_action.setText(
            f"실행 {len(self.active_contexts)} · 대기 {len(self.pending_jobs)}"
        )

    def tray_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.get("trayEnabled", False)),
            "available": QSystemTrayIcon.isSystemTrayAvailable(),
            "visible": bool(self.tray_icon and self.tray_icon.isVisible()),
            "windowVisible": self.isVisible(),
            "activeCount": len(self.active_contexts),
            "pendingCount": len(self.pending_jobs),
        }

    def show_from_tray(self) -> bool:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        return True

    def hide_to_tray(self) -> bool:
        if not self.tray_icon or not self.tray_icon.isVisible():
            raise ValueError("시스템 트레이가 활성화되어 있지 않습니다.")
        self.hide()
        return True

    def show_tray_notification(self, message: str) -> bool:
        if not self.tray_icon or not self.tray_icon.isVisible():
            return False
        self.tray_icon.showMessage(
            "tokiDownloader",
            message,
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )
        return True

    def show_in_app_notification_message(self, message: str) -> bool:
        self.statusBar().showMessage(message, 5000)
        return True

    def play_notification_sound(self) -> bool:
        QApplication.beep()
        return True

    def show_notification_message_box(self, plan: dict[str, Any]) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(
            "tokiDownloader - 작업 완료"
            if plan.get("kind") == "complete"
            else "tokiDownloader - 작업 오류"
        )
        box.setText(str(plan.get("message") or ""))
        box.setIcon(
            QMessageBox.Icon.Information
            if plan.get("kind") == "complete"
            else QMessageBox.Icon.Warning
        )
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setModal(False)
        self.notification_message_boxes.append(box)
        box.finished.connect(
            lambda _result, selected=box: self._notification_box_finished(selected)
        )
        box.show()
        return True

    def _notification_box_finished(self, box: QMessageBox) -> None:
        if box in self.notification_message_boxes:
            self.notification_message_boxes.remove(box)
        box.deleteLater()

    def deliver_notification(self, plan: dict[str, Any]) -> dict[str, Any]:
        if not plan.get("enabled"):
            result = {
                **plan,
                "executed": False,
                "inAppMessageShown": False,
                "trayShown": False,
                "messageBoxShown": False,
                "soundPlayed": False,
            }
            self.last_notification = result
            return result
        message = str(plan.get("message") or "")
        in_app_shown = self.show_in_app_notification_message(message)
        tray_shown = bool(
            plan.get("trayRequested") and self.show_tray_notification(message)
        )
        message_box_shown = bool(
            plan.get("messageBoxRequested")
            and self.show_notification_message_box(plan)
        )
        sound_played = bool(
            plan.get("soundRequested") and self.play_notification_sound()
        )
        result = {
            **plan,
            "executed": True,
            "inAppMessageShown": in_app_shown,
            "trayShown": tray_shown,
            "messageBoxShown": message_box_shown,
            "soundPlayed": sound_played,
        }
        self.last_notification = result
        return result

    def notification_status_snapshot(self) -> dict[str, Any]:
        return {
            **notification_settings_snapshot(self.config),
            "openMessageBoxes": len(self.notification_message_boxes),
            "last": dict(self.last_notification),
        }

    def close_notification_messages(self) -> int:
        boxes = list(self.notification_message_boxes)
        for box in boxes:
            box.close()
        return len(boxes)

    def preview_notification(
        self, kind: str, title: str, detail: str = ""
    ) -> dict[str, Any]:
        plan = notification_event_plan(
            kind,
            title=title,
            detail=detail,
            config=self.config,
            preview=True,
        )
        return self.deliver_notification(plan)

    def handle_tray_command(self, command: str, message: str = "") -> dict[str, Any]:
        if command == "show":
            self.show_from_tray()
        elif command == "hide":
            self.hide_to_tray()
        elif command == "notify":
            if not self.show_tray_notification(message or "tokiDownloader 테스트 알림"):
                raise ValueError("시스템 트레이가 활성화되어 있지 않습니다.")
        elif command != "status":
            raise ValueError(f"지원하지 않는 트레이 명령입니다: {command}")
        return self.tray_snapshot()

    def _notify_job_result(self, job: DownloadJob) -> dict[str, Any] | None:
        if job.state == "완료":
            kind = "complete"
        elif job.state in {"오류", "인증 필요"}:
            kind = "error"
        else:
            return None
        plan = notification_event_plan(
            kind,
            title=job.title,
            detail=job.error or job.state,
            config=self.config,
        )
        return self.deliver_notification(plan)

    def request_exit(self) -> None:
        self.exit_requested = True
        self.close()

    def set_output_folder(self, output_dir: str) -> str:
        if not output_dir:
            raise ValueError("저장 폴더 경로를 입력해주세요.")
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        self.output_edit.setText(str(output_path))
        self.config["outputDir"] = str(output_path)
        save_config(self.config)
        self.log(f"기본 저장 폴더 변경: {output_path}")
        return str(output_path)

    def set_image_concurrency(self, value: int) -> dict[str, Any]:
        concurrency = normalize_image_concurrency(value)
        self.image_concurrency_spin.setValue(concurrency)
        self.config["imageConcurrency"] = concurrency
        save_config(self.config)
        self.log(f"이미지 동시 다운로드 수 변경: {concurrency}")
        return {"imageConcurrency": concurrency}

    def _work_concurrency_changed(self, value: int) -> None:
        concurrency = normalize_work_concurrency(value)
        self.config["workConcurrency"] = concurrency
        save_config(self.config)
        self.log(f"작품 동시 다운로드 수 변경: {concurrency}")
        QTimer.singleShot(0, self._start_next_job)

    def set_work_concurrency(self, value: int) -> dict[str, Any]:
        concurrency = normalize_work_concurrency(value)
        if self.work_concurrency_spin.value() != concurrency:
            self.work_concurrency_spin.setValue(concurrency)
        else:
            self._work_concurrency_changed(concurrency)
        return {"workConcurrency": concurrency}

    def set_concurrency(
        self,
        *,
        works: int | None = None,
        images: int | None = None,
    ) -> dict[str, Any]:
        if works is None and images is None:
            raise ValueError("변경할 작품 또는 이미지 동시성 값을 지정해주세요.")
        if works is not None:
            self.set_work_concurrency(works)
        if images is not None:
            self.set_image_concurrency(images)
        return {
            "workConcurrency": self.work_concurrency_spin.value(),
            "imageConcurrency": self.image_concurrency_spin.value(),
        }

    def _retry_policy_changed(self, _value: int | None = None) -> None:
        retry_count = normalize_retry_count(self.retry_count_spin.value())
        backoff = normalize_retry_backoff(self.retry_backoff_spin.value())
        self.config["retryCount"] = retry_count
        self.config["retryBackoffSeconds"] = backoff
        save_config(self.config)
        self.log(f"자동 재시도 정책 변경: {retry_count}회, 기본 {backoff}초")

    def set_retry_policy(
        self,
        *,
        retry_count: int | None = None,
        backoff_seconds: int | None = None,
    ) -> dict[str, Any]:
        if retry_count is None and backoff_seconds is None:
            raise ValueError("변경할 재시도 횟수 또는 대기 시간을 지정해주세요.")
        self.retry_count_spin.blockSignals(True)
        self.retry_backoff_spin.blockSignals(True)
        try:
            if retry_count is not None:
                self.retry_count_spin.setValue(normalize_retry_count(retry_count))
            if backoff_seconds is not None:
                self.retry_backoff_spin.setValue(
                    normalize_retry_backoff(backoff_seconds)
                )
        finally:
            self.retry_count_spin.blockSignals(False)
            self.retry_backoff_spin.blockSignals(False)
        self._retry_policy_changed()
        return {
            "retryCount": self.retry_count_spin.value(),
            "retryBackoffSeconds": self.retry_backoff_spin.value(),
        }

    def confirm_public_ip_check(self) -> bool:
        answer = QMessageBox.question(
            self,
            "공인 IP 확인",
            "공인 IP 확인을 위해 api.ipify.org에 HTTPS 요청을 보냅니다.\n"
            "쿠키와 다운로드 파일은 전송하지 않습니다. 계속할까요?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.start_public_ip_check()
        return True

    def start_public_ip_check(self) -> None:
        if self.public_ip_task is not None:
            raise ValueError("공인 IP 확인이 이미 진행 중입니다.")
        task = ServiceTask("public-ip", lookup_public_ip)
        self.public_ip_task = task
        task.signals.finished.connect(self._public_ip_check_finished)
        self.io_thread_pool.start(task)
        self.log("사용자 확인 후 공인 IP 조회 시작")

    def _public_ip_check_finished(
        self, _task_id: str, result: object, error: str
    ) -> None:
        self.public_ip_task = None
        if error:
            self.log(f"공인 IP 확인 실패: {error}", "ERROR")
            QMessageBox.warning(self, "공인 IP 확인 실패", error)
            return
        payload = result if isinstance(result, dict) else {}
        address = str(payload.get("ip") or "")
        self.log(f"공인 IP 확인 완료: {address}")
        QMessageBox.information(self, "공인 IP 확인", f"현재 공인 IP: {address}")

    def open_output_folder(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        target = job.output_path if job and job.output_path else self.output_edit.text()
        open_in_explorer(target)
        self.log(f"폴더 열기: {target}")
        return target

    def move_job_folder(
        self, job_id: str, output_dir: str, *, execute: bool = False
    ) -> dict[str, Any]:
        self._flush_job_history()
        result = (
            execute_job_folder_move(job_id, output_dir)
            if execute
            else plan_job_folder_move(job_id, output_dir)
        )
        if execute and result.get("job"):
            moved = DownloadJob(**result["job"])
            previous = self.jobs_by_work.get(moved.work_key)
            if previous and previous.job_id != moved.job_id:
                self.jobs.pop(previous.job_id, None)
            self.jobs[moved.job_id] = moved
            self.jobs_by_work[moved.work_key] = moved
            self.task_model.update_job(moved)
            if (
                self.active_detail_dialog
                and self.active_detail_dialog.job.work_key == moved.work_key
            ):
                self.active_detail_dialog.job = moved
                self.active_detail_dialog.refresh()
            self.log(
                f"작품 폴더 이동: {result['source']} -> {result['destination']}",
                job_id=moved.job_id,
            )
        return result

    def confirm_move_job_folder(self, job_id: str) -> None:
        job = self.selected_job(job_id)
        if not job:
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            "새 저장 루트 선택",
            job.output_dir or self.output_edit.text(),
        )
        if not selected:
            return
        try:
            plan = self.move_job_folder(job.job_id, selected, execute=False)
        except (ValueError, FileNotFoundError) as error:
            QMessageBox.warning(self, "작품 폴더 이동", str(error))
            return
        if plan["samePath"]:
            QMessageBox.information(self, "작품 폴더 이동", "현재 위치와 같은 경로입니다.")
            return
        if plan["conflict"]:
            QMessageBox.warning(
                self,
                "작품 폴더 이동",
                f"목적지 폴더가 이미 존재합니다.\n\n{plan['destination']}",
            )
            return
        answer = QMessageBox.question(
            self,
            "작품 폴더 이동",
            f"다음 작품 폴더를 이동할까요?\n\n"
            f"원본: {plan['source']}\n\n목적지: {plan['destination']}\n\n"
            "이동이 끝난 뒤 작품 기록의 경로도 함께 갱신됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.move_job_folder(job.job_id, selected, execute=True)
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.critical(self, "작품 폴더 이동 실패", str(error))

    def rebuild_job_metadata(
        self, job_id: str, *, execute: bool = False
    ) -> dict[str, Any]:
        self._flush_job_history()
        result = (
            execute_metadata_rebuild(job_id)
            if execute
            else plan_metadata_rebuild(job_id)
        )
        if execute and result.get("job"):
            rebuilt = DownloadJob(**result["job"])
            self.jobs[rebuilt.job_id] = rebuilt
            self.jobs_by_work[rebuilt.work_key] = rebuilt
            self.task_model.update_job(rebuilt)
            if (
                self.active_detail_dialog
                and self.active_detail_dialog.job.work_key == rebuilt.work_key
            ):
                self.active_detail_dialog.job = rebuilt
                self.active_detail_dialog.refresh()
            self.log(
                f"로컬 메타데이터 재생성: {result['metadataPath']}",
                job_id=rebuilt.job_id,
            )
        return result

    def confirm_rebuild_job_metadata(self, job_id: str) -> None:
        try:
            plan = self.rebuild_job_metadata(job_id, execute=False)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "메타데이터 재생성", str(error))
            return
        backup_text = (
            f"기존 파일은 다음 위치에 백업됩니다.\n{plan['backupPath']}\n\n"
            if plan["willOverwrite"]
            else "새 metadata.json 파일을 만듭니다.\n\n"
        )
        answer = QMessageBox.question(
            self,
            "로컬 메타데이터 재생성",
            f"사이트에 접속하지 않고 다음 파일을 재생성할까요?\n\n"
            f"{plan['metadataPath']}\n\n{backup_text}"
            "설명·장르 등 읽을 수 있는 기존 값은 보존됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.rebuild_job_metadata(job_id, execute=True)
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.critical(self, "메타데이터 재생성 실패", str(error))

    def start_file_verification(self, job_id: str | None = None) -> dict[str, Any]:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("파일을 검사할 작품을 선택해주세요.")
        if job.job_id in self.file_verify_processes:
            return {"started": False, "jobId": job.job_id, "alreadyRunning": True}
        tracked = len(self.file_verify_processes) + len(self.image_preview_processes)
        active = self.io_thread_pool.activeThreadCount()
        admission = resource_admission(
            "io",
            active_count=active,
            queued_count=max(0, tracked - active),
            budget=self.resource_limits,
        )
        if not admission["allowed"]:
            return {
                "started": False,
                "jobId": job.job_id,
                "resourceLimit": True,
                "resources": admission,
            }
        task = ServiceTask(job.job_id, lambda: verify_job_files(job.job_id))
        task.signals.finished.connect(self._file_verification_finished)
        self.file_verify_processes[job.job_id] = task
        self.io_thread_pool.start(task)
        self.log("작품 파일 검사 시작(I/O 스레드 풀)", job_id=job.job_id)
        self.statusBar().showMessage(f"{job.title} 파일 검사 중…")
        return {
            "started": True,
            "jobId": job.job_id,
            "resources": admission,
        }

    def _file_verification_finished(
        self, job_id: str, result: dict[str, Any], error: str
    ) -> None:
        task = self.file_verify_processes.pop(job_id, None)
        if task is None:
            return
        if error:
            self.log(f"작품 파일 검사 실패: {error}", "ERROR", job_id)
            QMessageBox.critical(self, "작품 파일 검사 실패", error)
            return
        if self.active_file_verify_dialog:
            self.active_file_verify_dialog.close()
        dialog = FileVerificationDialog(self, result)
        self.active_file_verify_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda: setattr(self, "active_file_verify_dialog", None)
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        summary = result.get("summary") or {}
        level = "INFO" if result.get("healthy") else "ERROR"
        self.log(
            f"작품 파일 검사 완료: 회차 {summary.get('episodeFolders', 0)}, "
            f"이미지 {summary.get('images', 0)}, 문제 {summary.get('issueCount', 0)}",
            level,
            job_id,
        )
        self.statusBar().showMessage("작품 파일 검사가 완료되었습니다.", 3500)

    def start_image_preview(
        self, job_id: str | None = None, episode: int | None = None
    ) -> dict[str, Any]:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("이미지를 미리 볼 작품을 선택해주세요.")
        if job.job_id in self.image_preview_processes:
            return {"started": False, "jobId": job.job_id, "alreadyRunning": True}
        tracked = len(self.file_verify_processes) + len(self.image_preview_processes)
        active = self.io_thread_pool.activeThreadCount()
        admission = resource_admission(
            "io",
            active_count=active,
            queued_count=max(0, tracked - active),
            budget=self.resource_limits,
        )
        if not admission["allowed"]:
            return {
                "started": False,
                "jobId": job.job_id,
                "resourceLimit": True,
                "resources": admission,
            }
        task = ServiceTask(
            job.job_id,
            lambda: list_job_episode_images(job.job_id, episode, limit=200),
        )
        task.signals.finished.connect(self._image_preview_finished)
        self.image_preview_processes[job.job_id] = task
        self.io_thread_pool.start(task)
        self.log("회차 이미지 목록 조회 시작(I/O 스레드 풀)", job_id=job.job_id)
        return {
            "started": True,
            "jobId": job.job_id,
            "episode": episode,
            "resources": admission,
        }

    def _image_preview_finished(
        self, job_id: str, result: dict[str, Any], error: str
    ) -> None:
        task = self.image_preview_processes.pop(job_id, None)
        if task is None:
            return
        if error:
            self.log(f"이미지 미리보기 준비 실패: {error}", "ERROR", job_id)
            QMessageBox.critical(self, "이미지 미리보기 실패", error)
            return
        if self.active_image_preview_dialog:
            self.active_image_preview_dialog.close()
        dialog = ImagePreviewDialog(self, result)
        self.active_image_preview_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_image_preview_dialog", None)
                if self.active_image_preview_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log(
            f"이미지 미리보기 표시: {result.get('episode')}회차, "
            f"{len(result.get('images') or [])}장",
            job_id=job_id,
        )

    def start_image_conversion(
        self,
        job_id: str,
        image_format: str = "webp",
        quality: int = 90,
        *,
        max_width: int | None = None,
        max_height: int | None = None,
        excluded_extensions: list[str] | None = None,
        execute: bool = False,
    ) -> dict[str, Any]:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("이미지를 변환할 작품을 선택해주세요.")
        if job.job_id in self.image_conversion_processes:
            return {"started": False, "jobId": job.job_id, "alreadyRunning": True}
        admission = resource_admission(
            "cpu",
            active_count=(
                len(self.image_conversion_processes)
                + len(self.pdf_generation_processes)
            ),
            budget=self.resource_limits,
        )
        if not admission["allowed"]:
            return {
                "started": False,
                "jobId": job.job_id,
                "resourceLimit": True,
                "resources": admission,
            }
        policy = image_processing_policy_snapshot(self.config)
        selected_width = normalize_image_resize_dimension(
            policy["maxWidth"] if max_width is None else max_width
        )
        selected_height = normalize_image_resize_dimension(
            policy["maxHeight"] if max_height is None else max_height
        )
        selected_exclusions = normalize_image_excluded_extensions(
            policy["excludedExtensions"]
            if excluded_extensions is None
            else excluded_extensions
        )
        python = Path(sys.executable).with_name("python.exe")
        arguments = [
            str(ROOT_DIR / "toki_app.py"),
            "convert-images",
            "--job",
            job.job_id,
            "--format",
            str(image_format),
            "--quality",
            str(int(quality)),
            "--max-width",
            str(selected_width),
            "--max-height",
            str(selected_height),
        ]
        for extension in selected_exclusions:
            arguments.extend(["--exclude-ext", str(extension)])
        arguments.extend(
            ["--execute", "--yes", "--progress-json"]
            if execute
            else ["--dry-run", "--json", "--ascii-json"]
        )
        process = create_background_process(self)
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(str(python if python.is_file() else Path(sys.executable)))
        process.setArguments(arguments)
        process.finished.connect(
            lambda exit_code, _status, selected=job.job_id: self._image_conversion_finished(
                selected, exit_code
            )
        )
        context = ImageConversionProcessContext(process=process, execute=execute)
        self.image_conversion_processes[job.job_id] = context
        if execute:
            process.readyReadStandardOutput.connect(
                lambda selected=job.job_id: self._read_image_conversion_stdout(selected)
            )
            process.readyReadStandardError.connect(
                lambda selected=job.job_id: self._read_image_conversion_stderr(selected)
            )
            if self.active_image_conversion_dialog:
                self.active_image_conversion_dialog.close()
            if self.active_image_conversion_progress_dialog:
                self.active_image_conversion_progress_dialog.close()
            progress_dialog = ImageConversionProgressDialog(self, job.job_id)
            self.active_image_conversion_progress_dialog = progress_dialog
            progress_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            progress_dialog.destroyed.connect(
                lambda _object=None, selected=progress_dialog: (
                    setattr(self, "active_image_conversion_progress_dialog", None)
                    if self.active_image_conversion_progress_dialog is selected
                    else None
                )
            )
            progress_dialog.show()
            progress_dialog.raise_()
            progress_dialog.activateWindow()
        process.start()
        self.log(
            "이미지 변환 시작(별도 프로세스)"
            if execute
            else "이미지 변환 계획 조회(별도 프로세스)",
            job_id=job.job_id,
        )
        return {
            "started": True,
            "jobId": job.job_id,
            "format": image_format,
            "quality": int(quality),
            "maxWidth": selected_width,
            "maxHeight": selected_height,
            "excludedExtensions": selected_exclusions,
            "execute": execute,
            "resources": admission,
        }

    def _read_image_conversion_stdout(self, job_id: str) -> None:
        context = self.image_conversion_processes.get(job_id)
        if context is None:
            return
        addition = bytes(context.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        context.stdout_buffer += addition
        while "\n" in context.stdout_buffer:
            line, context.stdout_buffer = context.stdout_buffer.split("\n", 1)
            self._handle_image_conversion_output_line(job_id, line)
        context.stdout_buffer, dropped = append_bounded_text(
            "",
            context.stdout_buffer,
            int(self.resource_limits["maxProcessOutputBytes"]),
        )
        context.stdout_dropped_bytes += dropped
        self.total_output_dropped_bytes += dropped

    def _read_image_conversion_stderr(self, job_id: str) -> None:
        context = self.image_conversion_processes.get(job_id)
        if context is None:
            return
        addition = bytes(context.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        context.stderr_buffer, dropped = append_bounded_text(
            context.stderr_buffer,
            addition,
            int(self.resource_limits["maxProcessOutputBytes"]),
        )
        context.stderr_dropped_bytes += dropped
        self.total_output_dropped_bytes += dropped

    def _handle_image_conversion_output_line(self, job_id: str, line: str) -> None:
        context = self.image_conversion_processes.get(job_id)
        if context is None or not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            context.stderr_buffer, dropped = append_bounded_text(
                context.stderr_buffer,
                f"\n잘못된 진행 출력: {line}",
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            context.stderr_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped
            return
        if event.get("event") == "result":
            result = event.get("result")
            if isinstance(result, dict):
                context.result = result
            return
        if event.get("event") != "progress":
            return
        dialog = self.active_image_conversion_progress_dialog
        if dialog and dialog.job_id == job_id:
            dialog.update_progress(event)
        current = int(event.get("current") or 0)
        total = int(event.get("total") or 0)
        if current == 1 or current == total or current % 100 == 0:
            self.statusBar().showMessage(
                f"이미지 변환 {current}/{total} · 실패 {event.get('failed', 0)}"
            )

    def cancel_image_conversion(self, job_id: str) -> dict[str, Any]:
        context = self.image_conversion_processes.get(job_id)
        if context is None or not context.execute:
            return {"cancelled": False, "jobId": job_id, "running": False}
        if not context.cancel_requested:
            context.cancel_requested = True
            dialog = self.active_image_conversion_progress_dialog
            if dialog and dialog.job_id == job_id:
                dialog.mark_cancelling()
            context.process.kill()
            self.log(
                "이미지 변환 중지 요청: 원본 보존, 다음 실행에서 임시 파일 복구",
                "WARNING",
                job_id,
            )
        return {"cancelled": True, "jobId": job_id, "running": True}

    def close_image_conversion_dialog(self) -> bool:
        if not self.active_image_conversion_dialog:
            return False
        self.active_image_conversion_dialog.close()
        return True

    def _image_conversion_finished(self, job_id: str, exit_code: int) -> None:
        context = self.image_conversion_processes.get(job_id)
        if context is None:
            return
        process = context.process
        execute = context.execute
        if execute:
            self._read_image_conversion_stdout(job_id)
            self._read_image_conversion_stderr(job_id)
            if context.stdout_buffer.strip():
                self._handle_image_conversion_output_line(
                    job_id, context.stdout_buffer.strip()
                )
        else:
            context.stdout_buffer, dropped_stdout = append_bounded_text(
                context.stdout_buffer,
                bytes(process.readAllStandardOutput()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            context.stderr_buffer, dropped_stderr = append_bounded_text(
                context.stderr_buffer,
                bytes(process.readAllStandardError()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            context.stdout_dropped_bytes += dropped_stdout
            context.stderr_dropped_bytes += dropped_stderr
            self.total_output_dropped_bytes += dropped_stdout + dropped_stderr
            try:
                context.result = json.loads(context.stdout_buffer.strip())
            except json.JSONDecodeError:
                pass
        if isinstance(process, HiddenProcess):
            hidden_drops = process.droppedOutputBytes()
            context.stdout_dropped_bytes += int(hidden_drops.get("stdout") or 0)
            context.stderr_dropped_bytes += int(hidden_drops.get("stderr") or 0)
            self.total_output_dropped_bytes += sum(hidden_drops.values())
        self.image_conversion_processes.pop(job_id, None)
        process.deleteLater()
        if self.active_image_conversion_progress_dialog:
            self.active_image_conversion_progress_dialog.close()
        if context.cancel_requested:
            self.log("이미지 변환이 사용자 요청으로 중지되었습니다.", "WARNING", job_id)
            self.statusBar().showMessage("이미지 변환을 중지했습니다.", 4000)
            return
        dropped_output = context.stdout_dropped_bytes + context.stderr_dropped_bytes
        if dropped_output:
            self.log(
                f"이미지 변환 출력 상한으로 {dropped_output:,}바이트를 생략했습니다.",
                "WARNING",
                job_id,
            )
        result = context.result
        if result is None:
            message = (
                context.stderr_buffer.strip()
                or context.stdout_buffer.strip()
                or f"종료 코드 {exit_code}"
            )
            self.log(f"이미지 변환 실패: {message}", "ERROR", job_id)
            QMessageBox.critical(self, "이미지 변환 실패", message)
            return
        if self.active_image_conversion_dialog:
            self.active_image_conversion_dialog.close()
        dialog = ImageConversionDialog(self, result)
        self.active_image_conversion_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(
            lambda _object=None, selected=dialog: (
                setattr(self, "active_image_conversion_dialog", None)
                if self.active_image_conversion_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if execute:
            self.log(
                f"이미지 변환 종료: 완료 {result.get('convertedCount', 0)}, "
                f"건너뜀 {result.get('skippedExistingCount', 0)}, "
                f"실패 {result.get('failedCount', 0)}",
                "INFO" if result.get("success") else "ERROR",
                job_id,
            )

    def pdf_status_snapshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            **pdf_generation_policy_snapshot(self.config),
            "runningJobIds": sorted(self.pdf_generation_processes),
            "pendingAutomaticJobIds": sorted(self.pending_pdf_jobs),
            "dialog": (
                self.active_pdf_generation_dialog.state_snapshot()
                if self.active_pdf_generation_dialog
                else {"open": False}
            ),
            "progressDialog": {
                "open": bool(
                    self.active_pdf_generation_progress_dialog
                    and self.active_pdf_generation_progress_dialog.isVisible()
                ),
                "jobId": (
                    self.active_pdf_generation_progress_dialog.job_id
                    if self.active_pdf_generation_progress_dialog
                    else ""
                ),
            },
        }

    def _queue_automatic_pdf_generation(self, job_id: str) -> None:
        if not self.config.get("pdfGenerationEnabled", False):
            return
        if job_id not in self.pending_pdf_jobs:
            self.pending_pdf_jobs.add(job_id)
            self.log("자동 PDF 생성 대기열에 추가했습니다.", job_id=job_id)
        self._try_start_automatic_pdf_generation(job_id)

    def _try_start_automatic_pdf_generation(self, job_id: str) -> None:
        if job_id not in self.pending_pdf_jobs:
            return
        if not self.config.get("pdfGenerationEnabled", False):
            self.pending_pdf_jobs.discard(job_id)
            self._schedule_completion_if_idle()
            return
        try:
            result = self.start_pdf_generation(
                job_id,
                execute=True,
                automatic=True,
            )
        except (OSError, RuntimeError, ValueError) as error:
            self.pending_pdf_jobs.discard(job_id)
            self.log(f"자동 PDF 생성 시작 실패: {error}", "ERROR", job_id)
            self._schedule_completion_if_idle()
            return
        if result.get("started") or result.get("alreadyRunning"):
            self.pending_pdf_jobs.discard(job_id)
            self._schedule_completion_if_idle()
            return
        if result.get("resourceLimit"):
            QTimer.singleShot(
                500,
                lambda selected=job_id: self._try_start_automatic_pdf_generation(
                    selected
                ),
            )
            return
        self.pending_pdf_jobs.discard(job_id)
        self.log("자동 PDF 생성을 시작하지 못했습니다.", "ERROR", job_id)
        self._schedule_completion_if_idle()

    def _schedule_completion_if_idle(self) -> None:
        if (
            not self.active_contexts
            and not self.pending_jobs
            and not self.pdf_generation_processes
            and not self.pending_pdf_jobs
        ):
            QTimer.singleShot(0, self._maybe_trigger_completion_action)

    def start_pdf_generation(
        self,
        job_id: str,
        *,
        execute: bool = False,
        automatic: bool = False,
    ) -> dict[str, Any]:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("PDF를 생성할 작품을 선택해주세요.")
        if job.job_id in self.pdf_generation_processes:
            return {"started": False, "jobId": job.job_id, "alreadyRunning": True}
        admission = resource_admission(
            "cpu",
            active_count=(
                len(self.image_conversion_processes)
                + len(self.pdf_generation_processes)
            ),
            budget=self.resource_limits,
        )
        if not admission["allowed"]:
            return {
                "started": False,
                "jobId": job.job_id,
                "resourceLimit": True,
                "resources": admission,
            }
        python = Path(sys.executable).with_name("python.exe")
        arguments = [
            str(ROOT_DIR / "toki_app.py"),
            "pdf",
            "generate" if execute else "plan",
            "--job",
            job.job_id,
        ]
        arguments.extend(
            ["--execute", "--yes", "--progress-json"]
            if execute
            else ["--json", "--ascii-json"]
        )
        process = create_background_process(self)
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(str(python if python.is_file() else Path(sys.executable)))
        process.setArguments(arguments)
        process.finished.connect(
            lambda exit_code, _status, selected=job.job_id: self._pdf_generation_finished(
                selected, exit_code
            )
        )
        context = PdfGenerationProcessContext(
            process=process,
            execute=execute,
            automatic=automatic,
        )
        self.pdf_generation_processes[job.job_id] = context
        if execute:
            process.readyReadStandardOutput.connect(
                lambda selected=job.job_id: self._read_pdf_generation_stdout(selected)
            )
            process.readyReadStandardError.connect(
                lambda selected=job.job_id: self._read_pdf_generation_stderr(selected)
            )
            if not automatic:
                if self.active_pdf_generation_dialog:
                    self.active_pdf_generation_dialog.close()
                if self.active_pdf_generation_progress_dialog:
                    self.active_pdf_generation_progress_dialog.close()
                progress_dialog = PdfGenerationProgressDialog(self, job.job_id)
                self.active_pdf_generation_progress_dialog = progress_dialog
                progress_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                progress_dialog.destroyed.connect(
                    lambda _object=None, selected=progress_dialog: (
                        setattr(self, "active_pdf_generation_progress_dialog", None)
                        if self.active_pdf_generation_progress_dialog is selected
                        else None
                    )
                )
                progress_dialog.show()
                progress_dialog.raise_()
                progress_dialog.activateWindow()
        process.start()
        self.log(
            "회차별 PDF 자동 생성 시작(별도 프로세스)"
            if automatic
            else "회차별 PDF 생성 시작(별도 프로세스)"
            if execute
            else "회차별 PDF 생성 계획 조회(별도 프로세스)",
            job_id=job.job_id,
        )
        return {
            "started": True,
            "jobId": job.job_id,
            "execute": execute,
            "automatic": automatic,
            "preservesOriginals": True,
            "resources": admission,
        }

    def _read_pdf_generation_stdout(self, job_id: str) -> None:
        context = self.pdf_generation_processes.get(job_id)
        if context is None:
            return
        addition = bytes(context.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        context.stdout_buffer += addition
        while "\n" in context.stdout_buffer:
            line, context.stdout_buffer = context.stdout_buffer.split("\n", 1)
            self._handle_pdf_generation_output_line(job_id, line)
        context.stdout_buffer, dropped = append_bounded_text(
            "",
            context.stdout_buffer,
            int(self.resource_limits["maxProcessOutputBytes"]),
        )
        context.stdout_dropped_bytes += dropped
        self.total_output_dropped_bytes += dropped

    def _read_pdf_generation_stderr(self, job_id: str) -> None:
        context = self.pdf_generation_processes.get(job_id)
        if context is None:
            return
        addition = bytes(context.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )
        context.stderr_buffer, dropped = append_bounded_text(
            context.stderr_buffer,
            addition,
            int(self.resource_limits["maxProcessOutputBytes"]),
        )
        context.stderr_dropped_bytes += dropped
        self.total_output_dropped_bytes += dropped

    def _handle_pdf_generation_output_line(self, job_id: str, line: str) -> None:
        context = self.pdf_generation_processes.get(job_id)
        if context is None or not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            context.stderr_buffer, dropped = append_bounded_text(
                context.stderr_buffer,
                f"\n잘못된 PDF 진행 출력: {line}",
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            context.stderr_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped
            return
        if event.get("event") == "result":
            result = event.get("result")
            if isinstance(result, dict):
                context.result = result
            return
        if event.get("event") != "progress":
            return
        dialog = self.active_pdf_generation_progress_dialog
        if dialog and dialog.job_id == job_id:
            dialog.update_progress(event)
        current = int(event.get("current") or 0)
        total = int(event.get("total") or 0)
        if current == 1 or current == total or current % 25 == 0:
            self.statusBar().showMessage(
                f"PDF 생성 {current}/{total} · 실패 {event.get('failed', 0)}"
            )

    def cancel_pdf_generation(self, job_id: str) -> dict[str, Any]:
        context = self.pdf_generation_processes.get(job_id)
        if context is None or not context.execute:
            return {"cancelled": False, "jobId": job_id, "running": False}
        if not context.cancel_requested:
            context.cancel_requested = True
            dialog = self.active_pdf_generation_progress_dialog
            if dialog and dialog.job_id == job_id:
                dialog.mark_cancelling()
            context.process.kill()
            self.log(
                "PDF 생성 중지 요청: 원본 보존, 다음 실행에서 임시 파일 복구",
                "WARNING",
                job_id,
            )
        return {"cancelled": True, "jobId": job_id, "running": True}

    def close_pdf_generation_dialogs(self) -> bool:
        closed = False
        for dialog in (
            self.active_pdf_generation_dialog,
            self.active_pdf_generation_progress_dialog,
        ):
            if dialog:
                dialog.close()
                closed = True
        return closed

    def _pdf_generation_finished(self, job_id: str, exit_code: int) -> None:
        context = self.pdf_generation_processes.get(job_id)
        if context is None:
            return
        process = context.process
        if context.execute:
            self._read_pdf_generation_stdout(job_id)
            self._read_pdf_generation_stderr(job_id)
            if context.stdout_buffer.strip():
                self._handle_pdf_generation_output_line(
                    job_id, context.stdout_buffer.strip()
                )
        else:
            context.stdout_buffer, dropped_stdout = append_bounded_text(
                context.stdout_buffer,
                bytes(process.readAllStandardOutput()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            context.stderr_buffer, dropped_stderr = append_bounded_text(
                context.stderr_buffer,
                bytes(process.readAllStandardError()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            context.stdout_dropped_bytes += dropped_stdout
            context.stderr_dropped_bytes += dropped_stderr
            self.total_output_dropped_bytes += dropped_stdout + dropped_stderr
            try:
                context.result = json.loads(context.stdout_buffer.strip())
            except json.JSONDecodeError:
                pass
        if isinstance(process, HiddenProcess):
            hidden_drops = process.droppedOutputBytes()
            context.stdout_dropped_bytes += int(hidden_drops.get("stdout") or 0)
            context.stderr_dropped_bytes += int(hidden_drops.get("stderr") or 0)
            self.total_output_dropped_bytes += sum(hidden_drops.values())
        self.pdf_generation_processes.pop(job_id, None)
        process.deleteLater()
        if self.active_pdf_generation_progress_dialog:
            self.active_pdf_generation_progress_dialog.close()
        if context.cancel_requested:
            self.log("PDF 생성이 사용자 요청으로 중지되었습니다.", "WARNING", job_id)
            self.statusBar().showMessage("PDF 생성을 중지했습니다.", 4000)
            self._schedule_completion_if_idle()
            return
        result = context.result
        if result is None:
            message = (
                context.stderr_buffer.strip()
                or context.stdout_buffer.strip()
                or f"종료 코드 {exit_code}"
            )
            self.log(f"PDF 생성 실패: {message}", "ERROR", job_id)
            if not context.automatic:
                QMessageBox.critical(self, "PDF 생성 실패", message)
            self._schedule_completion_if_idle()
            return
        if not context.automatic:
            if self.active_pdf_generation_dialog:
                self.active_pdf_generation_dialog.close()
            dialog = PdfGenerationDialog(self, result)
            self.active_pdf_generation_dialog = dialog
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.destroyed.connect(
                lambda _object=None, selected=dialog: (
                    setattr(self, "active_pdf_generation_dialog", None)
                    if self.active_pdf_generation_dialog is selected
                    else None
                )
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        if context.execute:
            self.log(
                f"PDF 생성 종료: 완료 {result.get('generatedCount', 0)}, "
                f"건너뜀 {result.get('skippedCurrentCount', 0)}, "
                f"실패 {result.get('failedCount', 0)}",
                "INFO" if result.get("success") else "ERROR",
                job_id,
            )
        self._schedule_completion_if_idle()

    def open_job_source(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("원본 페이지를 열 작품을 선택해주세요.")
        if not QDesktopServices.openUrl(QUrl(job.url)):
            raise RuntimeError("기본 브라우저에서 작품 페이지를 열지 못했습니다.")
        self.log(f"원본 페이지 열기: {job.url}", job_id=job.job_id)
        return job.url

    def open_job_cover(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("대표 이미지를 열 작품을 선택해주세요.")
        cover_path = resolve_cover_path(job)
        open_in_explorer(cover_path)
        self.log(f"대표 이미지 원본 열기: {cover_path}", job_id=job.job_id)
        return cover_path

    def show_job_details(self, job_id: str | None = None) -> bool:
        job = self.selected_job(job_id if isinstance(job_id, str) else None)
        if not job:
            self.statusBar().showMessage("상세 정보를 볼 작품을 선택해주세요.", 2500)
            return False
        if self.active_detail_dialog:
            self.active_detail_dialog.close()
        dialog = WorkDetailDialog(self, job)
        self.active_detail_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda: setattr(self, "active_detail_dialog", None))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def close_job_details(self) -> bool:
        if not self.active_detail_dialog:
            return False
        self.active_detail_dialog.close()
        return True

    def show_run_log(self, run_id: str) -> bool:
        run = load_run(str(run_id or ""))
        if not run:
            raise ValueError(f"실행 기록을 찾을 수 없습니다: {run_id}")
        if self.active_run_log_dialog:
            self.active_run_log_dialog.close()
        dialog = RunLogDialog(self, run)
        self.active_run_log_dialog = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(lambda: setattr(self, "active_run_log_dialog", None))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def close_run_log(self) -> bool:
        if not self.active_run_log_dialog:
            return False
        self.active_run_log_dialog.close()
        return True

    def open_job_index_folder(self, index: QModelIndex) -> None:
        job = self.task_model.job_at(index.row())
        if not job or not job.output_path:
            self.statusBar().showMessage("작품 다운로드 폴더를 아직 확인하는 중입니다.", 2500)
            return
        self.open_output_folder(job.job_id)

    def show_job_context_menu(self, position: QPoint) -> None:
        index = self.task_list.indexAt(position)
        if not index.isValid():
            return
        self.task_list.setCurrentIndex(index)
        job = self.task_model.job_at(index.row())
        if not job:
            return
        global_position = self.task_list.viewport().mapToGlobal(position)
        self._popup_job_context_menu(job, global_position)

    def show_job_context_menu_for_job(self, job_id: str | None = None) -> bool:
        job = self.selected_job(job_id)
        if not job:
            return False
        row = self.task_model.row_by_key.get(job.work_key)
        if row is None:
            return False
        index = self.task_model.index(row, 0)
        self.task_list.setCurrentIndex(index)
        self.task_list.scrollTo(index)
        rect = self.task_list.visualRect(index)
        global_position = self.task_list.viewport().mapToGlobal(rect.center())
        self._popup_job_context_menu(job, global_position)
        return True

    def _popup_job_context_menu(self, job: DownloadJob, global_position: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("작품 정보 및 실행 이력", lambda: self.show_job_details(job.job_id))
        menu.addAction("다운로드 폴더 열기", lambda: self.open_output_folder(job.job_id))
        move_action = menu.addAction(
            "작품 폴더 이동...",
            lambda: self.confirm_move_job_folder(job.job_id),
        )
        move_action.setEnabled(
            job.state not in ACTIVE_JOB_STATES and bool(job.output_path)
        )
        menu.addAction("원본 페이지 열기", lambda: self.open_job_source(job.job_id))
        menu.addAction("대표 이미지 원본 열기", lambda: self.open_job_cover(job.job_id))
        menu.addAction(
            "메타데이터 새로고침",
            lambda: self.refresh_selected_metadata(job.job_id),
        )
        rebuild_action = menu.addAction(
            "로컬 메타데이터 재생성...",
            lambda: self.confirm_rebuild_job_metadata(job.job_id),
        )
        rebuild_action.setEnabled(
            job.state not in ACTIVE_JOB_STATES and bool(job.output_path)
        )
        verify_action = menu.addAction(
            "보유 회차·파일 검사",
            lambda: self.start_file_verification(job.job_id),
        )
        verify_action.setEnabled(
            bool(job.output_path) and job.job_id not in self.file_verify_processes
        )
        preview_action = menu.addAction(
            "회차 이미지 미리보기",
            lambda: self.start_image_preview(job.job_id),
        )
        preview_action.setEnabled(
            bool(job.output_path) and job.job_id not in self.image_preview_processes
        )
        convert_action = menu.addAction(
            "이미지 형식 변환...",
            lambda: self.start_image_conversion(job.job_id),
        )
        convert_action.setEnabled(
            job.state not in ACTIVE_JOB_STATES
            and bool(job.output_path)
            and job.job_id not in self.image_conversion_processes
        )
        pdf_action = menu.addAction(
            "회차별 PDF 생성...",
            lambda: self.start_pdf_generation(job.job_id),
        )
        pdf_action.setEnabled(
            job.state not in ACTIVE_JOB_STATES
            and bool(job.output_path)
            and job.job_id not in self.pdf_generation_processes
        )
        duplicate_images_menu = menu.addMenu("중복 이미지 검사")
        duplicate_exact_action = duplicate_images_menu.addAction("정확히 같은 파일 (SHA-256)")
        duplicate_exact_action.triggered.connect(
            lambda: self.start_duplicate_images(job.job_id, "sha256")
        )
        duplicate_phash_action = duplicate_images_menu.addAction("시각적으로 유사 (pHash)")
        duplicate_phash_action.triggered.connect(
            lambda: self.start_duplicate_images(job.job_id, "phash")
        )
        duplicate_images_menu.setEnabled(
            bool(job.output_path) and job.job_id not in self.duplicate_image_tasks
        )
        menu.addSeparator()
        menu.addAction("작품 ID 복사", lambda: self.copy_job_id(job.job_id))
        source_copy_action = menu.addAction(
            "원본 URL 복사", lambda: self.copy_job_link(job.job_id)
        )
        source_copy_action.setEnabled(bool(job.url))
        path_copy_action = menu.addAction(
            "저장 폴더 경로 복사", lambda: self.copy_job_path(job.job_id)
        )
        path_copy_action.setEnabled(bool(job.output_path))
        menu.addAction("작품명 복사", lambda: self.copy_job_title(job.job_id))
        menu.addSeparator()
        menu.addAction(
            "고정 해제" if job.pinned else "목록 상단에 고정",
            lambda: self.set_job_pin(job.job_id, not job.pinned),
        )
        collection_menu = menu.addMenu("작품 정리 그룹")
        current_collection = work_collection_for_job(job.job_id)
        unassigned_action = collection_menu.addAction("미분류")
        unassigned_action.setCheckable(True)
        unassigned_action.setChecked(current_collection is None)
        unassigned_action.triggered.connect(
            lambda _checked=False: self.assign_work_group(job.job_id, "")
        )
        groups = list_work_collections()
        if groups:
            collection_menu.addSeparator()
        for group in groups:
            action = collection_menu.addAction(str(group["name"]))
            action.setCheckable(True)
            action.setChecked(
                bool(current_collection)
                and current_collection.get("groupId") == group["groupId"]
            )
            action.triggered.connect(
                lambda _checked=False, selected=str(group["groupId"]): self.assign_work_group(
                    job.job_id, selected
                )
            )
        collection_menu.addSeparator()
        collection_menu.addAction("그룹 관리...", self.show_group_manager)
        tag_menu = menu.addMenu("색상 태그")
        for label, color in (
            ("없음", "none"),
            ("빨강", "red"),
            ("주황", "orange"),
            ("노랑", "yellow"),
            ("초록", "green"),
            ("파랑", "blue"),
            ("보라", "purple"),
            ("회색", "gray"),
        ):
            action = tag_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked((job.tag_color or "none") == color)
            action.triggered.connect(
                lambda _checked=False, selected=color: self.set_job_tag(job.job_id, selected)
            )
        menu.addSeparator()
        remove_action = menu.addAction(
            "목록 기록 제거...",
            lambda: self.confirm_remove_job_record(job.job_id),
        )
        remove_action.setEnabled(job.state not in ACTIVE_JOB_STATES)
        menu.addSeparator()
        rescan_menu = menu.addMenu("작품 재검사")
        new_action = rescan_menu.addAction(
            "신규 회차만",
            lambda: self.rescan_selected_job("new", job.job_id),
        )
        full_action = rescan_menu.addAction(
            "전체 회차",
            lambda: self.rescan_selected_job("full", job.job_id),
        )
        range_action = rescan_menu.addAction(
            "현재 입력 범위",
            lambda: self.rescan_selected_job("range", job.job_id),
        )
        can_rescan = job.state not in ACTIVE_JOB_STATES
        new_action.setEnabled(can_rescan)
        full_action.setEnabled(can_rescan)
        range_action.setEnabled(
            can_rescan and bool(self.start_spin.value() or self.last_spin.value())
        )
        stop_action = menu.addAction("현재 작업 중지", self.stop_active_job)
        active_context = self.active_contexts.get(job.job_id)
        stop_action.setEnabled(active_context is not None)
        pause_action = menu.addAction(
            "현재 작업 일시정지",
            lambda: self.pause_selected_active_job(job.job_id),
        )
        pause_action.setEnabled(
            bool(
                active_context
                and not active_context.paused
            )
        )
        resume_action = menu.addAction(
            "일시정지 작업 계속",
            lambda: self.resume_selected_active_job(job.job_id),
        )
        resume_action.setEnabled(bool(active_context and active_context.paused))
        cancel_action = menu.addAction(
            "대기 작업 취소",
            lambda: self.cancel_selected_queued_job(job.job_id),
        )
        cancel_action.setEnabled(any(item.job_id == job.job_id for item in self.pending_jobs))
        queue_menu = menu.addMenu("대기열 우선순위")
        first_action = queue_menu.addAction(
            "맨 앞으로",
            lambda: self.move_queued_job(job.job_id, position="first"),
        )
        last_action = queue_menu.addAction(
            "맨 뒤로",
            lambda: self.move_queued_job(job.job_id, position="last"),
        )
        is_pending = any(item.job_id == job.job_id for item in self.pending_jobs)
        queue_menu.setEnabled(is_pending)
        first_action.setEnabled(is_pending and len(self.pending_jobs) > 1)
        last_action.setEnabled(is_pending and len(self.pending_jobs) > 1)
        menu.aboutToHide.connect(lambda: setattr(self, "active_context_menu", None))
        self.active_context_menu = menu
        menu.popup(global_position)

    def copy_job_link(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("링크를 복사할 작품을 선택해주세요.")
        QApplication.clipboard().setText(job.url)
        self.statusBar().showMessage("원본 링크를 복사했습니다.", 2500)
        return job.url

    def copy_job_id(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("ID를 복사할 작품을 선택해주세요.")
        QApplication.clipboard().setText(job.job_id)
        self.statusBar().showMessage("작품 ID를 복사했습니다.", 2500)
        return job.job_id

    def copy_job_path(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("저장 경로를 복사할 작품을 선택해주세요.")
        if not job.output_path:
            raise ValueError("이 작품에는 아직 저장 폴더가 없습니다.")
        QApplication.clipboard().setText(job.output_path)
        self.statusBar().showMessage("저장 폴더 경로를 복사했습니다.", 2500)
        return job.output_path

    def copy_job_title(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError("작품명을 복사할 작품을 선택해주세요.")
        QApplication.clipboard().setText(job.title)
        self.statusBar().showMessage("작품명을 복사했습니다.", 2500)
        return job.title

    def set_job_pin(self, job_id: str, pinned: bool) -> dict[str, Any]:
        updated = update_job_markers(job_id, pinned=pinned)
        current = self.jobs.get(job_id)
        if current:
            current.pinned = updated.pinned
            updated = current
        self.apply_history_filters()
        self.log(
            f"작품 고정 {'설정' if pinned else '해제'}: {updated.title}",
            job_id=job_id,
        )
        return updated.to_dict()

    def set_job_tag(self, job_id: str, color: str) -> dict[str, Any]:
        updated = update_job_markers(job_id, tag_color=color)
        current = self.jobs.get(job_id)
        if current:
            current.tag_color = updated.tag_color
            updated = current
        self.task_model.update_job(updated)
        self.log(f"작품 색상 태그 변경: {color}", job_id=job_id)
        return updated.to_dict()

    def job_info_snapshot(self, job_id: str) -> dict[str, Any]:
        self._flush_job_history()
        job = self.selected_job(job_id)
        if not job:
            raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
        return {"job": job.to_dict(), "runCount": count_runs(job.work_key)}

    def list_runs_snapshot(
        self, job_id: str, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        job = self.selected_job(job_id)
        if not job:
            raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
        clean_limit = max(1, min(1000, int(limit)))
        clean_offset = max(0, int(offset))
        runs = load_runs_page(job.work_key, clean_limit, clean_offset)
        return {
            "jobId": job.job_id,
            "workKey": job.work_key,
            "total": count_runs(job.work_key),
            "limit": clean_limit,
            "offset": clean_offset,
            "runs": [run.to_dict() for run in runs],
        }

    def set_job_note(self, job_id: str, text: str) -> dict[str, Any]:
        updated = update_job_note(job_id, text)
        current = self.jobs.get(job_id)
        if current:
            current.user_note = updated.user_note
            updated = current
        self.task_model.update_job(updated)
        self.log("작품 메모 변경", job_id=job_id)
        return updated.to_dict()

    def confirm_remove_job_record(self, job_id: str) -> None:
        job = self.selected_job(job_id)
        if not job:
            return
        answer = QMessageBox.question(
            self,
            "작품 기록 제거",
            f"목록에서 다음 작품 기록을 제거할까요?\n\n{job.title}\n\n"
            "다운로드한 폴더와 이미지 파일은 삭제하지 않습니다.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.remove_job_record(job_id)

    def remove_job_record(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id) or load_job_by_id(job_id)
        if not job:
            raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
        removed = delete_job_record(job_id)
        was_visible = self.task_model.remove_work_key(job.work_key)
        self.jobs.pop(job_id, None)
        self.jobs_by_work.pop(job.work_key, None)
        self.dirty_job_ids.discard(job_id)
        self.history_all_total = max(0, self.history_all_total - 1)
        if was_visible:
            self.history_total = max(0, self.history_total - 1)
        self.history_loaded = self.task_model.rowCount()
        if self.task_model.rowCount():
            self.task_list.setCurrentIndex(self.task_model.index(0, 0))
        self._update_summary()
        self.log(
            f"작품 기록 제거(파일 보존): {removed.title}",
            job_id=removed.job_id,
        )
        return {
            "removed": True,
            "jobId": removed.job_id,
            "workKey": removed.work_key,
            "outputPath": removed.output_path,
            "filesDeleted": False,
        }

    def confirm_cleanup_records(self) -> None:
        states = ["완료", "오류", "인증 필요", "중지됨"]
        count = sum(count_jobs(state=state) for state in states)
        if count <= 0:
            QMessageBox.information(
                self,
                "기록 정리",
                "정리할 완료·오류·인증 필요·중단 기록이 없습니다.",
            )
            return
        answer = QMessageBox.question(
            self,
            "종료 기록 정리",
            f"완료·오류·인증 필요·중단 기록 {count}개를 목록에서 제거할까요?\n\n"
            "다운로드한 폴더와 이미지 파일은 삭제하지 않습니다.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cleanup_job_records(states)

    def cleanup_job_records(self, states: list[str]) -> dict[str, Any]:
        removed = delete_job_records(states)
        for job in removed:
            self.jobs.pop(job.job_id, None)
            self.jobs_by_work.pop(job.work_key, None)
            self.dirty_job_ids.discard(job.job_id)
        self.apply_history_filters()
        self.log(f"작품 기록 일괄 정리(파일 보존): {len(removed)}개")
        return {
            "removedCount": len(removed),
            "jobIds": [job.job_id for job in removed],
            "filesDeleted": False,
        }

    def confirm_run_history_cleanup(self) -> None:
        preview = cleanup_run_history(execute=False)
        self.run_retention_report = preview
        candidate_count = int(preview.get("candidateRuns") or 0)
        if candidate_count <= 0:
            QMessageBox.information(
                self, "실행 이력 정리", "현재 보존 정책을 넘는 실행 이력이 없습니다."
            )
            return
        answer = QMessageBox.question(
            self,
            "오래된 실행 이력 정리",
            f"오래된 실행 이력 {candidate_count:,}건을 제거할까요?\n\n"
            "작품별 최신 기록과 진행 중 기록은 보존하며 다운로드 파일은 삭제하지 않습니다.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cleanup_run_history_now()

    def cleanup_run_history_now(
        self, max_per_work: int = 500, max_age_days: int = 365
    ) -> dict[str, Any]:
        report = cleanup_run_history(
            max_per_work=max_per_work,
            max_age_days=max_age_days,
            execute=True,
        )
        self.run_retention_report = report
        message = f"오래된 실행 이력 정리: {int(report['removedRuns']):,}건"
        self.log(message)
        self.statusBar().showMessage(message, 4000)
        if self.active_detail_dialog:
            self.active_detail_dialog.refresh()
        return report

    def clear_logs(self) -> None:
        clear_log_file()
        self.log_edit.clear()
        self.log("로그를 지웠습니다.")

    def copy_logs(self) -> None:
        QApplication.clipboard().setText(self.log_edit.toPlainText())
        self.statusBar().showMessage("로그를 클립보드에 복사했습니다.", 2500)

    def capture_window(self, output_path: str | bool | None = None) -> str:
        requested_path = output_path if isinstance(output_path, str) else ""
        target = (
            Path(requested_path).expanduser().resolve()
            if requested_path
            else LOG_PATH.parent / "gui-screenshot.png"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        notification_box = next(
            (
                box
                for box in reversed(self.notification_message_boxes)
                if box.isVisible()
            ),
            None,
        )
        if notification_box:
            screenshot = notification_box.grab()
        elif (
            self.active_shortcut_help_dialog
            and self.active_shortcut_help_dialog.isVisible()
        ):
            screenshot = self.active_shortcut_help_dialog.grab()
        elif self.active_doctor_dialog and self.active_doctor_dialog.isVisible():
            screenshot = self.active_doctor_dialog.grab()
        elif self.active_performance_dialog and self.active_performance_dialog.isVisible():
            screenshot = self.active_performance_dialog.grab()
        elif (
            self.active_hitomi_inspector_dialog
            and self.active_hitomi_inspector_dialog.isVisible()
        ):
            screenshot = self.active_hitomi_inspector_dialog.grab()
        elif (
            self.active_hitomi_metadata_dialog
            and self.active_hitomi_metadata_dialog.isVisible()
        ):
            screenshot = self.active_hitomi_metadata_dialog.grab()
        elif (
            self.active_embedded_browser_dialog
            and self.active_embedded_browser_dialog.isVisible()
        ):
            screenshot = self.active_embedded_browser_dialog.grab()
        elif (
            self.active_proxy_credential_dialog
            and self.active_proxy_credential_dialog.isVisible()
        ):
            screenshot = self.active_proxy_credential_dialog.grab()
        elif (
            self.active_cookie_manager_dialog
            and self.active_cookie_manager_dialog.isVisible()
        ):
            screenshot = self.active_cookie_manager_dialog.grab()
        elif self.active_settings_dialog and self.active_settings_dialog.isVisible():
            screenshot = self.active_settings_dialog.grab()
        elif (
            self.active_jobs_snapshot_dialog
            and self.active_jobs_snapshot_dialog.isVisible()
        ):
            screenshot = self.active_jobs_snapshot_dialog.grab()
        elif (
            self.active_group_manager_dialog
            and self.active_group_manager_dialog.isVisible()
        ):
            screenshot = self.active_group_manager_dialog.grab()
        elif (
            self.active_archive_inspection_dialog
            and self.active_archive_inspection_dialog.isVisible()
        ):
            screenshot = self.active_archive_inspection_dialog.grab()
        elif (
            self.active_recovery_dialog
            and self.active_recovery_dialog.isVisible()
        ):
            screenshot = self.active_recovery_dialog.grab()
        elif (
            self.active_duplicate_works_dialog
            and self.active_duplicate_works_dialog.isVisible()
        ):
            screenshot = self.active_duplicate_works_dialog.grab()
        elif (
            self.active_duplicate_images_dialog
            and self.active_duplicate_images_dialog.isVisible()
        ):
            screenshot = self.active_duplicate_images_dialog.grab()
        elif self.active_completion_dialog and self.active_completion_dialog.isVisible():
            screenshot = self.active_completion_dialog.grab()
        elif (
            self.active_pdf_generation_progress_dialog
            and self.active_pdf_generation_progress_dialog.isVisible()
        ):
            screenshot = self.active_pdf_generation_progress_dialog.grab()
        elif (
            self.active_pdf_generation_dialog
            and self.active_pdf_generation_dialog.isVisible()
        ):
            screenshot = self.active_pdf_generation_dialog.grab()
        elif (
            self.active_image_conversion_progress_dialog
            and self.active_image_conversion_progress_dialog.isVisible()
        ):
            screenshot = self.active_image_conversion_progress_dialog.grab()
        elif (
            self.active_image_conversion_dialog
            and self.active_image_conversion_dialog.isVisible()
        ):
            screenshot = self.active_image_conversion_dialog.grab()
        elif (
            self.active_image_preview_dialog
            and self.active_image_preview_dialog.isVisible()
        ):
            screenshot = self.active_image_preview_dialog.grab()
        elif (
            self.active_file_verify_dialog
            and self.active_file_verify_dialog.isVisible()
        ):
            screenshot = self.active_file_verify_dialog.grab()
        elif self.active_run_log_dialog and self.active_run_log_dialog.isVisible():
            screenshot = self.active_run_log_dialog.grab()
        elif self.active_detail_dialog and self.active_detail_dialog.isVisible():
            screenshot = self.active_detail_dialog.grab()
        else:
            screenshot = self.grab()
        if self.active_context_menu and self.active_context_menu.isVisible():
            QApplication.processEvents()
            menu_image = self.active_context_menu.grab()
            window_origin = self.mapToGlobal(QPoint(0, 0))
            menu_position = self.active_context_menu.pos() - window_origin
            composite = QPainter(screenshot)
            composite.drawPixmap(menu_position, menu_image)
            composite.end()
        if not screenshot.save(str(target), "PNG"):
            raise OSError(f"GUI 화면을 저장하지 못했습니다: {target}")
        self.log(f"GUI 화면 캡처: {target}")
        self.statusBar().showMessage(f"화면 저장: {target}", 3000)
        return str(target)

    def start_self_test(self) -> bool:
        if (
            self.self_test_process
            and self.self_test_process.state() != QProcess.ProcessState.NotRunning
        ):
            self.statusBar().showMessage("자체 점검이 이미 실행 중입니다.", 2500)
            return False

        process = create_background_process(self)
        self.self_test_process = process
        self.self_test_stdout = ""
        self.self_test_stderr = ""
        self.self_test_output_dropped_bytes = 0
        self.last_self_test = None
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(sys.executable)
        process.setArguments([str(ROOT_DIR / "toki_app.py"), "self-test", "--json"])
        process.readyReadStandardOutput.connect(self._read_self_test_stdout)
        process.readyReadStandardError.connect(self._read_self_test_stderr)
        process.errorOccurred.connect(self._self_test_process_error)
        process.finished.connect(self._self_test_finished)
        self.self_test_button.setEnabled(False)
        self.self_test_action.setEnabled(False)
        self.status_label.setText("자체 점검 실행 중")
        self.log("자체 점검 시작", job_id="self-test")
        process.start()
        return True

    def _read_self_test_stdout(self) -> None:
        if self.self_test_process:
            self.self_test_stdout, dropped = append_bounded_text(
                self.self_test_stdout,
                bytes(self.self_test_process.readAllStandardOutput()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            self.self_test_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped

    def _read_self_test_stderr(self) -> None:
        if self.self_test_process:
            self.self_test_stderr, dropped = append_bounded_text(
                self.self_test_stderr,
                bytes(self.self_test_process.readAllStandardError()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            self.self_test_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped

    def _self_test_process_error(self, _error: QProcess.ProcessError) -> None:
        if not self.self_test_process:
            return
        message = f"자체 점검 프로세스 오류: {self.self_test_process.errorString()}"
        self.log(message, "ERROR", job_id="self-test")
        self.status_label.setText("자체 점검 실행 오류")

    def _self_test_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_self_test_stdout()
        self._read_self_test_stderr()
        if isinstance(self.self_test_process, HiddenProcess):
            hidden_drops = self.self_test_process.droppedOutputBytes()
            dropped = sum(hidden_drops.values())
            self.self_test_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped
        try:
            result = json.loads(self.self_test_stdout.strip())
            if not isinstance(result, dict):
                raise ValueError("자체 점검 결과가 JSON 객체가 아닙니다.")
        except (json.JSONDecodeError, ValueError) as error:
            result = {
                "ok": False,
                "summary": {"passed": 0, "failed": 1, "total": 1},
                "error": str(error),
                "stderr": self.self_test_stderr.strip(),
            }
        summary = result.get("summary") or {}
        passed = int(summary.get("passed") or 0)
        total = int(summary.get("total") or 0)
        ok = bool(result.get("ok")) and exit_code == 0
        self.last_self_test = {
            "ok": ok,
            "durationMs": result.get("durationMs"),
            "summary": summary,
            "reportPath": result.get("reportPath"),
            "outputDroppedBytes": self.self_test_output_dropped_bytes,
        }
        message = f"자체 점검 {'통과' if ok else '실패'}: {passed}/{total}"
        self.log(message, "INFO" if ok else "ERROR", job_id="self-test")
        if self.self_test_stderr.strip() and not ok:
            self.log(self.self_test_stderr.strip(), "ERROR", job_id="self-test")
        self.status_label.setText(message)
        self.statusBar().showMessage(message, 5000)
        self.self_test_button.setEnabled(True)
        self.self_test_action.setEnabled(True)
        self.self_test_process = None

    def performance_benchmark_snapshot(self) -> dict[str, Any]:
        running = bool(
            self.performance_benchmark_process
            and self.performance_benchmark_process.state()
            != QProcess.ProcessState.NotRunning
        )
        return {"running": running, "last": self.last_performance_benchmark}

    def _update_performance_benchmark_dialog(self) -> None:
        if self.active_performance_dialog:
            self.active_performance_dialog.update_benchmark_status(
                self.performance_benchmark_snapshot()
            )

    def start_performance_benchmark(
        self,
        sizes: list[int] | None = None,
        page_size: int = 200,
        output: str = "",
    ) -> bool:
        if self.performance_benchmark_snapshot()["running"]:
            self.statusBar().showMessage("목록 벤치마크가 이미 실행 중입니다.", 2500)
            return False
        process = create_background_process(self)
        self.performance_benchmark_process = process
        self.performance_benchmark_stdout = ""
        self.performance_benchmark_stderr = ""
        self.performance_output_dropped_bytes = 0
        self.last_performance_benchmark = None
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(sys.executable)
        normalized_sizes = [int(size) for size in (sizes or [100, 1_000, 10_000, 100_000])]
        if not normalized_sizes or any(size < 1 or size > 100_000 for size in normalized_sizes):
            raise ValueError("벤치마크 크기는 각각 1~100,000개여야 합니다.")
        arguments = [
            str(ROOT_DIR / "toki_app.py"),
            "performance",
            "benchmark",
            "--sizes",
            *(str(size) for size in normalized_sizes),
            "--page-size",
            str(max(1, min(1_000, int(page_size)))),
            "--json",
        ]
        if output:
            arguments.extend(("--output", str(output)))
        process.setArguments(arguments)
        process.readyReadStandardOutput.connect(self._read_performance_benchmark_stdout)
        process.readyReadStandardError.connect(self._read_performance_benchmark_stderr)
        process.errorOccurred.connect(self._performance_benchmark_process_error)
        process.finished.connect(self._performance_benchmark_finished)
        self.status_label.setText("목록 벤치마크 실행 중")
        self.log("100~100,000개 합성 목록 벤치마크 시작", job_id="performance")
        process.start()
        self._update_performance_benchmark_dialog()
        return True

    def _read_performance_benchmark_stdout(self) -> None:
        if self.performance_benchmark_process:
            self.performance_benchmark_stdout, dropped = append_bounded_text(
                self.performance_benchmark_stdout,
                bytes(
                    self.performance_benchmark_process.readAllStandardOutput()
                ).decode("utf-8", errors="replace"),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            self.performance_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped

    def _read_performance_benchmark_stderr(self) -> None:
        if self.performance_benchmark_process:
            self.performance_benchmark_stderr, dropped = append_bounded_text(
                self.performance_benchmark_stderr,
                bytes(
                    self.performance_benchmark_process.readAllStandardError()
                ).decode("utf-8", errors="replace"),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            self.performance_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped

    def _performance_benchmark_process_error(
        self, _error: QProcess.ProcessError
    ) -> None:
        if not self.performance_benchmark_process:
            return
        message = (
            "목록 벤치마크 프로세스 오류: "
            f"{self.performance_benchmark_process.errorString()}"
        )
        self.log(message, "ERROR", job_id="performance")
        self.status_label.setText("목록 벤치마크 실행 오류")

    def _performance_benchmark_finished(
        self, exit_code: int, _exit_status: QProcess.ExitStatus
    ) -> None:
        self._read_performance_benchmark_stdout()
        self._read_performance_benchmark_stderr()
        if isinstance(self.performance_benchmark_process, HiddenProcess):
            hidden_drops = self.performance_benchmark_process.droppedOutputBytes()
            dropped = sum(hidden_drops.values())
            self.performance_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped
        try:
            result = json.loads(self.performance_benchmark_stdout.strip())
            if not isinstance(result, dict):
                raise ValueError("벤치마크 결과가 JSON 객체가 아닙니다.")
        except (json.JSONDecodeError, ValueError) as error:
            result = {
                "ok": False,
                "error": str(error),
                "stderr": self.performance_benchmark_stderr.strip(),
                "results": [],
            }
        result["ok"] = bool(result.get("ok")) and exit_code == 0
        result["outputDroppedBytes"] = self.performance_output_dropped_bytes
        self.last_performance_benchmark = result
        message = f"목록 벤치마크 {'통과' if result['ok'] else '실패'}"
        self.log(message, "INFO" if result["ok"] else "ERROR", job_id="performance")
        if self.performance_benchmark_stderr.strip() and not result["ok"]:
            self.log(
                self.performance_benchmark_stderr.strip(), "ERROR", job_id="performance"
            )
        self.status_label.setText(message)
        self.statusBar().showMessage(message, 5000)
        self.performance_benchmark_process = None
        self._update_performance_benchmark_dialog()

    def stability_test_snapshot(self) -> dict[str, Any]:
        running = bool(
            self.stability_test_process
            and self.stability_test_process.state()
            != QProcess.ProcessState.NotRunning
        )
        return {"running": running, "last": self.last_stability_test}

    def _update_stability_test_dialog(self) -> None:
        if self.active_performance_dialog:
            self.active_performance_dialog.update_stability_status(
                self.stability_test_snapshot()
            )

    def start_stability_test(
        self,
        records: int = 10_000,
        cycles: int = 100,
        output: str = "",
    ) -> bool:
        if self.stability_test_snapshot()["running"]:
            self.statusBar().showMessage("안정성·복구 검증이 이미 실행 중입니다.", 2500)
            return False
        safe_records = max(100, min(100_000, int(records)))
        safe_cycles = max(1, min(1_000, int(cycles)))
        process = create_background_process(self)
        self.stability_test_process = process
        self.stability_test_stdout = ""
        self.stability_test_stderr = ""
        self.stability_output_dropped_bytes = 0
        self.last_stability_test = None
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(sys.executable)
        arguments = [
            str(ROOT_DIR / "toki_app.py"),
            "performance",
            "stability",
            "--records",
            str(safe_records),
            "--cycles",
            str(safe_cycles),
            "--json",
        ]
        if output:
            arguments.extend(("--output", str(output)))
        process.setArguments(arguments)
        process.readyReadStandardOutput.connect(self._read_stability_test_stdout)
        process.readyReadStandardError.connect(self._read_stability_test_stderr)
        process.errorOccurred.connect(self._stability_test_process_error)
        process.finished.connect(self._stability_test_finished)
        self.status_label.setText("안정성·강제 종료 복구 검증 중")
        self.log(
            f"격리 안정성 검증 시작: {safe_records:,}개, {safe_cycles:,}회",
            job_id="stability",
        )
        process.start()
        self._update_stability_test_dialog()
        return True

    def _read_stability_test_stdout(self) -> None:
        if self.stability_test_process:
            self.stability_test_stdout, dropped = append_bounded_text(
                self.stability_test_stdout,
                bytes(self.stability_test_process.readAllStandardOutput()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            self.stability_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped

    def _read_stability_test_stderr(self) -> None:
        if self.stability_test_process:
            self.stability_test_stderr, dropped = append_bounded_text(
                self.stability_test_stderr,
                bytes(self.stability_test_process.readAllStandardError()).decode(
                    "utf-8", errors="replace"
                ),
                int(self.resource_limits["maxProcessOutputBytes"]),
            )
            self.stability_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped

    def _stability_test_process_error(self, _error: QProcess.ProcessError) -> None:
        if not self.stability_test_process:
            return
        message = (
            "안정성 검증 프로세스 오류: "
            f"{self.stability_test_process.errorString()}"
        )
        self.log(message, "ERROR", job_id="stability")
        self.status_label.setText("안정성·복구 검증 실행 오류")

    def _stability_test_finished(
        self, exit_code: int, _exit_status: QProcess.ExitStatus
    ) -> None:
        self._read_stability_test_stdout()
        self._read_stability_test_stderr()
        if isinstance(self.stability_test_process, HiddenProcess):
            hidden_drops = self.stability_test_process.droppedOutputBytes()
            dropped = sum(hidden_drops.values())
            self.stability_output_dropped_bytes += dropped
            self.total_output_dropped_bytes += dropped
        try:
            result = json.loads(self.stability_test_stdout.strip())
            if not isinstance(result, dict):
                raise ValueError("안정성 검증 결과가 JSON 객체가 아닙니다.")
        except (json.JSONDecodeError, ValueError) as error:
            result = {
                "ok": False,
                "error": str(error),
                "stderr": self.stability_test_stderr.strip(),
            }
        result["ok"] = bool(result.get("ok")) and exit_code == 0
        result["outputDroppedBytes"] = self.stability_output_dropped_bytes
        self.last_stability_test = result
        message = f"안정성·강제 종료 복구 검증 {'통과' if result['ok'] else '실패'}"
        self.log(message, "INFO" if result["ok"] else "ERROR", job_id="stability")
        if self.stability_test_stderr.strip() and not result["ok"]:
            self.log(self.stability_test_stderr.strip(), "ERROR", job_id="stability")
        self.status_label.setText(message)
        self.statusBar().showMessage(message, 5000)
        self.stability_test_process = None
        self._update_stability_test_dialog()

    def show_cli_help(self) -> None:
        QMessageBox.information(
            self,
            "CLI 명령",
            "toki-cli.cmd download --url URL [--start N --last N --output PATH --show-browser]\n"
            "toki-cli.cmd status [--json]\n"
            "toki-cli.cmd list [--query TEXT --status STATE --sort updated|title|progress --apply-gui --json]\n"
            "toki-cli.cmd list-state [--query TEXT --status STATE --apply-gui --preview STATE --json]\n"
            "toki-cli.cmd shortcuts [--json]\n"
            "toki-cli.cmd focus --target url|search|list|log|next|previous|next-section [--clear --json]\n"
            "toki-cli.cmd pin --job ID --on|--off\n"
            "toki-cli.cmd tag --job ID --color COLOR\n"
            "toki-cli.cmd remove-record --job ID --yes\n"
            "toki-cli.cmd cleanup-records --status completed|error|authentication|stopped --yes\n"
            "toki-cli.cmd refresh-list\n"
            "toki-cli.cmd move-folder --job ID --output PATH --dry-run --json\n"
            "toki-cli.cmd move-folder --job ID --output PATH --execute --yes --json\n"
            "toki-cli.cmd rebuild-metadata --job ID --dry-run --json\n"
            "toki-cli.cmd rebuild-metadata --job ID --execute --yes --json\n"
            "toki-cli.cmd verify-files --job ID [--json|--show-gui]\n"
            "toki-cli.cmd preview --job ID [--episode N] [--json|--show-gui]\n"
            "toki-cli.cmd convert-images --job ID --format jpg|png|webp [--max-width N --max-height N --exclude-ext EXT] [--dry-run|--execute --yes|--show-gui]\n"
            "toki-cli.cmd image-processing status|set [options]\n"
            "toki-cli.cmd hitomi status|inspect|close|server status|set|plan|metadata status|set|plan|parse|fetch|show|close|metadata-files status|set|plan|write|filenames status|set|plan|images status|set|plan|tags status|set|evaluate|title status|set|select [options]\n"
            "toki-cli.cmd pdf status|set|plan|generate|cancel|close [options]\n"
            "toki-cli.cmd stop --job ID\n"
            "toki-cli.cmd cancel --job ID\n"
            "toki-cli.cmd pause --job ID\n"
            "toki-cli.cmd resume --job ID\n"
            "toki-cli.cmd queue list [--json]\n"
            "toki-cli.cmd queue move --job ID --before OTHER_ID|--first|--last\n"
            "toki-cli.cmd concurrency [--json]\n"
            "toki-cli.cmd set-concurrency [--works 1~4] [--images 1~16]\n"
            "toki-cli.cmd retry-policy [--json]\n"
            "toki-cli.cmd set-retry-policy [--count 0~5] [--backoff 1~60]\n"
            "toki-cli.cmd settings [--json|--show-gui --tab general|network|display|advanced|provider --search TEXT|--close]\n"
            "toki-cli.cmd completion-action status|set|preview|cancel [options]\n"
            "toki-cli.cmd notifications status|set|preview|close [options]\n"
            "toki-cli.cmd clipboard inspect|monitor [options]\n"
            "toki-cli.cmd config get|set|export|import|reset [options] --json\n"
            "toki-cli.cmd jobs export --output PATH --json [--via-gui]\n"
            "toki-cli.cmd jobs import [--input PATH --dry-run|--input PATH --show-gui|--input PATH --execute --yes|--close] --json\n"
            "toki-cli.cmd group list|create|rename|assign|unassign|manage [options]\n"
            "toki-cli.cmd local inspect [--path ARCHIVE --json|--show-gui|--close]\n"
            "toki-cli.cmd archive-viewer status|set|open [options]\n"
            "toki-cli.cmd persistence status|set|recover [options]\n"
            "toki-cli.cmd list-performance status|set [options]\n"
            "toki-cli.cmd sleep-prevention status|set|plan [options]\n"
            "toki-cli.cmd duplicates works [--json|--show-gui|--close]\n"
            "toki-cli.cmd duplicates images --job ID [--algorithm sha256|phash --json|--show-gui|--close]\n"
            "toki-cli.cmd set-settings [--output PATH --works N --images N --show-browser on|off --row-density MODE --theme MODE]\n"
            "toki-cli.cmd tray status|show|hide|notify [--message TEXT]\n"
            "toki-cli.cmd retry [--job ID]\n"
            "toki-cli.cmd rescan --job ID --mode new|full|range [--start N --last N]\n"
            "toki-cli.cmd set-output PATH\n"
            "toki-cli.cmd open-folder [--job ID]\n"
            "toki-cli.cmd copy-id [--job ID]\n"
            "toki-cli.cmd copy-link [--job ID]\n"
            "toki-cli.cmd copy-path [--job ID]\n"
            "toki-cli.cmd copy-title [--job ID]\n"
            "toki-cli.cmd job-menu [--job ID]\n"
            "toki-cli.cmd logs --tail 200\n"
            "toki-cli.cmd copy-log [--tail 3000]\n"
            "toki-cli.cmd screenshot [--output PATH]\n"
            "toki-cli.cmd window [--x N --y N --width N --height N --screen NAME --center --safe --maximize|--normal]\n"
            "toki-cli.cmd performance audit [--json|--show-gui|--close]\n"
            "toki-cli.cmd performance benchmark [--sizes N...] [--page-size N --json|--via-gui]\n"
            "toki-cli.cmd performance stability [--records N --cycles N --json|--via-gui]\n"
            "toki-cli.cmd performance resources --json\n"
            "toki-cli.cmd performance event-policy --event EVENT --json\n"
            "toki-cli.cmd doctor [--json|--show-gui|--close]\n"
            "toki-cli.cmd diagnostics export [--output PATH --json|--via-gui]\n"
            "toki-cli.cmd thumbnail-cache status|cleanup [--execute --json]\n"
            "toki-cli.cmd retention status|cleanup-runs [--execute --json]\n"
            "toki-cli.cmd self-test [--json] [--core-only]\n"
            "toki-cli.cmd clear-log\n"
            "toki-cli.cmd show\n"
            "toki-cli.cmd quit",
        )

    def show_shortcut_help(self) -> bool:
        if self.active_shortcut_help_dialog:
            self.active_shortcut_help_dialog.refresh()
            self.active_shortcut_help_dialog.show()
            self.active_shortcut_help_dialog.raise_()
            self.active_shortcut_help_dialog.activateWindow()
            return True
        dialog = ShortcutHelpDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.active_shortcut_help_dialog = dialog
        selected = dialog
        dialog.destroyed.connect(
            lambda: (
                setattr(self, "active_shortcut_help_dialog", None)
                if self.active_shortcut_help_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def close_shortcut_help(self) -> bool:
        if not self.active_shortcut_help_dialog:
            return False
        self.active_shortcut_help_dialog.close()
        return True

    def show_dependency_diagnostics(self) -> dict[str, Any]:
        report = dependency_diagnostics()
        if self.active_doctor_dialog:
            self.active_doctor_dialog.close()
        dialog = DependencyDiagnosticsDialog(report, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.active_doctor_dialog = dialog
        selected = dialog
        dialog.destroyed.connect(
            lambda: (
                setattr(self, "active_doctor_dialog", None)
                if self.active_doctor_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.log(
            f"설치 환경 진단: 필수 {report['required']['passed']}/{report['required']['total']}"
        )
        return report

    def close_dependency_diagnostics(self) -> bool:
        if not self.active_doctor_dialog:
            return False
        self.active_doctor_dialog.close()
        return True

    def export_diagnostic_bundle(self, output: str = "") -> dict[str, Any]:
        result = export_diagnostics(Path(output) if output else None)
        message = f"진단 묶음 저장: {result['path']}"
        self.log(message)
        self.statusBar().showMessage(message, 8000)
        return result

    def show_performance_diagnostics(self) -> dict[str, Any]:
        report = job_database_diagnostics()
        if self.active_performance_dialog:
            self.active_performance_dialog.close()
        dialog = PerformanceDiagnosticsDialog(report, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.active_performance_dialog = dialog
        selected = dialog
        dialog.destroyed.connect(
            lambda: (
                setattr(self, "active_performance_dialog", None)
                if self.active_performance_dialog is selected
                else None
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return report

    def close_performance_diagnostics(self) -> bool:
        if not self.active_performance_dialog:
            return False
        self.active_performance_dialog.close()
        return True

    def status_snapshot(self) -> dict[str, Any]:
        active_contexts = list(self.active_contexts.values())
        active_jobs = [context.job.to_dict() for context in active_contexts]
        active_processes = [
            {
                "jobId": context.job.job_id,
                "pid": int(context.process.processId()),
                "paused": context.paused,
            }
            for context in active_contexts
            if context.process
            and context.process.state() != QProcess.ProcessState.NotRunning
        ]
        return {
            "running": bool(active_contexts),
            "processPid": active_processes[0]["pid"] if active_processes else None,
            "activeJob": active_jobs[0] if active_jobs else None,
            "activeJobs": active_jobs,
            "activeProcesses": active_processes,
            "activeCount": len(active_contexts),
            "pendingCount": len(self.pending_jobs),
            "pausedJobId": next(
                (context.job.job_id for context in active_contexts if context.paused),
                None,
            ),
            "pausedJobIds": [
                context.job.job_id for context in active_contexts if context.paused
            ],
            "actions": self._action_availability_snapshot(),
            "jobs": [job.to_dict() for job in self.jobs.values()],
            "loadedJobCount": len(self.jobs),
            "totalJobCount": self.history_all_total,
            "filteredJobCount": self.history_total,
            "outputDir": self.output_edit.text(),
            "imageConcurrency": self.image_concurrency_spin.value(),
            "workConcurrency": self.work_concurrency_spin.value(),
            "retryCount": self.retry_count_spin.value(),
            "retryBackoffSeconds": self.retry_backoff_spin.value(),
            "settings": settings_snapshot(self.config),
            "view": {
                "mode": str(self.config.get("listViewMode") or "list"),
                "thumbnailsVisible": bool(
                    self.list_performance_policy["effective"]["thumbnailsVisible"]
                ),
                "configuredThumbnailsVisible": bool(
                    self.config.get("thumbnailsVisible", True)
                ),
                "thumbnailSize": str(self.config.get("thumbnailSize") or "medium"),
                "alwaysOnTop": bool(self.config.get("alwaysOnTop", False)),
                "windowOpacity": int(self.config.get("windowOpacity", 100)),
                "loadedLimit": int(self.resource_limits["maxLoadedJobs"]),
                "batchSize": min(100, self.history_page_size),
                "lazyLoading": bool(
                    self.list_performance_policy["effective"]["lazyLoading"]
                ),
                "lowSpecMode": bool(self.config.get("lowSpecMode", False)),
            },
            "listPerformance": self.list_performance_status_snapshot(),
            "memoryUsage": self.memory_status_snapshot(),
            "localApi": self.local_api_status_snapshot(),
            "hitomiServer": hitomi_server_policy_snapshot(self.config),
            "hitomiMetadataPolicy": hitomi_metadata_policy_snapshot(self.config),
            "hitomiMetadataFilePolicy": hitomi_metadata_file_policy_snapshot(self.config),
            "hitomiOriginalImagePolicy": hitomi_original_image_policy_snapshot(self.config),
            "hitomiFilenamePolicy": hitomi_filename_policy_snapshot(self.config),
            "hitomiExcludedTagPolicy": hitomi_excluded_tag_policy_snapshot(self.config),
            "hitomiTitlePolicy": hitomi_title_policy_snapshot(self.config),
            "youtubeFormatPolicy": youtube_format_policy_snapshot(self.config),
            "sleepPrevention": self.sleep_prevention_status_snapshot(),
            "completionAction": self.completion_action_snapshot(),
            "notifications": self.notification_status_snapshot(),
            "clipboard": {
                "monitorEnabled": bool(self.config.get("clipboardMonitor", False)),
                "lastInspection": self.last_clipboard_inspection,
            },
            "startupRecovery": self.startup_recovery,
            "persistence": self.persistence_status_snapshot(),
            "logPath": str(LOG_PATH),
            "jobDbPath": str(JOB_DB_PATH),
            "screenshotPath": str(LOG_PATH.parent / "gui-screenshot.png"),
            "selfTestRunning": bool(
                self.self_test_process
                and self.self_test_process.state() != QProcess.ProcessState.NotRunning
            ),
            "performanceBenchmark": self.performance_benchmark_snapshot(),
            "stabilityTest": self.stability_test_snapshot(),
            "eventUpdates": self.event_update_snapshot(),
            "thumbnailCache": self.thumbnail_cache_snapshot(),
            "retention": self.retention_snapshot(),
            "resources": self.resource_snapshot(),
            "fileVerificationJobs": sorted(self.file_verify_processes),
            "imagePreviewJobs": sorted(self.image_preview_processes),
            "imageConversionJobs": sorted(self.image_conversion_processes),
            "imageProcessing": image_processing_policy_snapshot(self.config),
            "pdf": self.pdf_status_snapshot(),
            "imageConversionDialog": (
                self.active_image_conversion_dialog.state_snapshot()
                if self.active_image_conversion_dialog
                else {"open": False}
            ),
            "tray": self.tray_snapshot(),
            "lastSelfTest": self.last_self_test,
            "listFilter": {
                "query": self.history_query,
                "status": self.history_state,
                "sort": self.history_sort,
                "loaded": self.task_model.rowCount(),
                "total": self.history_total,
                "capped": (
                    self.task_model.rowCount()
                    >= int(self.resource_limits["maxLoadedJobs"])
                    and self.history_total > self.task_model.rowCount()
                ),
                "loadedLimit": int(self.resource_limits["maxLoadedJobs"]),
            },
            "listViewState": dict(self.list_view_state),
            "keyboard": self.keyboard_focus_snapshot(),
            "shortcutHelpOpen": bool(
                self.active_shortcut_help_dialog
                and self.active_shortcut_help_dialog.isVisible()
            ),
            "shortcutEditor": (
                self.active_shortcut_help_dialog.state_snapshot()
                if self.active_shortcut_help_dialog
                else {
                    "open": False,
                    "selectedAction": "",
                    "count": len(keyboard_shortcut_catalog(self.config)),
                    "overrideCount": len(self.config.get("shortcutOverrides", {})),
                    "disabledCount": sum(
                        1
                        for keys in self.config.get("shortcutOverrides", {}).values()
                        if not keys
                    ),
                }
            ),
            "performanceDiagnosticsOpen": bool(
                self.active_performance_dialog
                and self.active_performance_dialog.isVisible()
            ),
            "doctorOpen": bool(
                self.active_doctor_dialog and self.active_doctor_dialog.isVisible()
            ),
            "settingsDialog": (
                self.active_settings_dialog.state_snapshot()
                if self.active_settings_dialog
                else {"open": False, "tab": "", "search": "", "visibleTabs": []}
            ),
            "hitomiInspector": (
                self.active_hitomi_inspector_dialog.state_snapshot()
                if self.active_hitomi_inspector_dialog
                else {
                    "open": False,
                    "providerHint": "auto",
                    "referenceLength": 0,
                    "result": {},
                    "networkRequested": False,
                }
            ),
            "hitomiMetadata": (
                self.active_hitomi_metadata_dialog.state_snapshot()
                if self.active_hitomi_metadata_dialog
                else {
                    "open": False,
                    "providerHint": "auto",
                    "referenceLength": 0,
                    "fixtureSelected": False,
                    "fetchRunning": False,
                    "result": {},
                }
            ),
            "cookieManager": (
                self.active_cookie_manager_dialog.state_snapshot()
                if self.active_cookie_manager_dialog
                else {"open": False, "provider": "", "statusRead": False}
            ),
            "proxyCredentialManager": (
                self.active_proxy_credential_dialog.state_snapshot()
                if self.active_proxy_credential_dialog
                else {
                    "open": False,
                    "proxyConfigured": False,
                    "statusRead": False,
                    "passwordExposed": False,
                }
            ),
            "embeddedBrowser": (
                self.active_embedded_browser_dialog.state_snapshot()
                if self.active_embedded_browser_dialog
                else {
                    "open": False,
                    "available": bool(webengine_runtime_status()["available"]),
                    "importError": str(webengine_runtime_status()["importError"]),
                    "url": "",
                    "address": "",
                    "loading": False,
                    "networkApproved": False,
                    "offTheRecordProfile": True,
                    "persistentCookies": False,
                    "sharesAutomationCookies": False,
                }
            ),
            "jobsSnapshotDialogOpen": bool(
                self.active_jobs_snapshot_dialog
                and self.active_jobs_snapshot_dialog.isVisible()
            ),
            "groupManagerOpen": bool(
                self.active_group_manager_dialog
                and self.active_group_manager_dialog.isVisible()
            ),
            "groupCount": len(list_work_collections()),
            "archiveInspectionOpen": bool(
                self.active_archive_inspection_dialog
                and self.active_archive_inspection_dialog.isVisible()
            ),
            "archiveViewer": archive_viewer_policy_snapshot(self.config),
            "archiveInspection": (
                self.active_archive_inspection_dialog.state_snapshot()
                if self.active_archive_inspection_dialog
                else {"open": False}
            ),
            "recoveryDialog": (
                self.active_recovery_dialog.state_snapshot()
                if self.active_recovery_dialog
                else {"open": False}
            ),
            "duplicateWorksOpen": bool(
                self.active_duplicate_works_dialog
                and self.active_duplicate_works_dialog.isVisible()
            ),
            "duplicateImagesOpen": bool(
                self.active_duplicate_images_dialog
                and self.active_duplicate_images_dialog.isVisible()
            ),
            "duplicateImageJobs": sorted(self.duplicate_image_tasks),
            "window": {
                **self.window_snapshot(),
                "restorePlan": getattr(self, "window_restore_plan", None),
                "screens": self.screen_layout_snapshot(),
            },
        }

    def window_snapshot(self) -> dict[str, Any]:
        maximized = self.isMaximized()
        geometry = self.normalGeometry() if maximized else None
        position = geometry.topLeft() if geometry is not None else self.pos()
        width = geometry.width() if geometry is not None else self.width()
        height = geometry.height() if geometry is not None else self.height()
        center = QPoint(position.x() + width // 2, position.y() + height // 2)
        screen = QApplication.screenAt(center) or self.screen() or QApplication.primaryScreen()
        screen_name = screen.name() if screen else ""
        screen_dpr = float(screen.devicePixelRatio()) if screen else 1.0
        available = screen.availableGeometry() if screen else QRect()
        return {
            "x": position.x(),
            "y": position.y(),
            "width": width,
            "height": height,
            "maximized": maximized,
            "screenName": screen_name,
            "screenDpr": screen_dpr,
            "relativeX": position.x() - available.x() if screen else 0,
            "relativeY": position.y() - available.y() if screen else 0,
            "onScreen": bool(
                screen
                and available.intersects(
                    QRect(position.x(), position.y(), width, height)
                )
            ),
        }

    def screen_layout_snapshot(self) -> list[dict[str, Any]]:
        primary = QApplication.primaryScreen()
        screens: list[dict[str, Any]] = []
        for screen in QApplication.screens():
            available = screen.availableGeometry()
            geometry = screen.geometry()
            screens.append(
                {
                    "name": screen.name(),
                    "x": available.x(),
                    "y": available.y(),
                    "width": available.width(),
                    "height": available.height(),
                    "geometry": {
                        "x": geometry.x(),
                        "y": geometry.y(),
                        "width": geometry.width(),
                        "height": geometry.height(),
                    },
                    "devicePixelRatio": float(screen.devicePixelRatio()),
                    "logicalDpi": float(screen.logicalDotsPerInch()),
                    "physicalDpi": float(screen.physicalDotsPerInch()),
                    "primary": screen is primary,
                }
            )
        return screens

    def set_window_geometry(self, request: dict[str, Any]) -> dict[str, Any]:
        width = request.get("width")
        height = request.get("height")
        x = request.get("x")
        y = request.get("y")
        maximized = request.get("maximized")
        target_screen = str(request.get("screenName") or "").strip()
        center = bool(request.get("center"))
        safe = bool(request.get("safe"))

        screens = self.screen_layout_snapshot()
        if target_screen and not any(screen["name"] == target_screen for screen in screens):
            available = ", ".join(screen["name"] for screen in screens)
            raise ValueError(f"모니터를 찾을 수 없습니다: {target_screen} (사용 가능: {available})")
        plan: dict[str, Any] | None = None
        if any(value is not None for value in (width, height, x, y)) or target_screen or center or safe:
            desired = self.window_snapshot()
            if width is not None:
                desired["width"] = int(width)
            if height is not None:
                desired["height"] = int(height)
            if x is not None:
                desired["x"] = int(x)
            if y is not None:
                desired["y"] = int(y)
            plan = plan_window_geometry(
                desired,
                screens,
                target_screen=target_screen,
                center=center,
                minimum_width=self.minimumWidth(),
                minimum_height=self.minimumHeight(),
            )
            self.showNormal()
            self.resize(int(plan["width"]), int(plan["height"]))
            self.move(int(plan["x"]), int(plan["y"]))
            self.window_restore_plan = plan
        if maximized is True:
            self.showMaximized()
        elif maximized is False:
            self.showNormal()
        QApplication.processEvents()
        return {
            **self.window_snapshot(),
            "restorePlan": plan or getattr(self, "window_restore_plan", None),
            "screens": screens,
        }

    def _update_summary(self) -> None:
        states = [job.state for job in self.task_model.rows]
        cap_reached = (
            len(states) >= int(self.resource_limits["maxLoadedJobs"])
            and self.history_total > len(states)
        )
        self.queue_summary.setText(
            f"전체 {self.history_all_total} · 검색 {self.history_total} · "
            f"로딩 {len(states)}{'(상한)' if cap_reached else ''} · "
            f"대기 {states.count('대기')} · 실행 {states.count('실행 중')} · "
            f"재시도 {states.count('재시도 대기')} · "
            f"일시정지 {states.count('일시정지')} · 완료 {states.count('완료')} · "
            f"문제 {states.count('오류') + states.count('중지됨') + states.count('인증 필요')}"
        )
        self._update_action_states()

    def _action_availability_snapshot(self) -> dict[str, bool]:
        return menu_action_availability(
            self.selected_job(),
            form_url=self.url_edit.text(),
            active_job_ids=list(self.active_contexts),
            paused_job_ids=[
                job_id for job_id, context in self.active_contexts.items() if context.paused
            ],
            queued_job_ids=[job.job_id for job in self.pending_jobs],
        )

    def _update_action_states(self) -> dict[str, bool]:
        states = self._action_availability_snapshot()
        action_map = {
            "download.start": self.start_action,
            "job.stop": self.stop_action,
            "job.pause": self.pause_action,
            "job.resume": self.resume_action,
            "job.rescan_full": self.retry_action,
            "job.rescan_new": self.new_scan_action,
            "job.rescan_range": self.range_scan_action,
            "snapshot.export": self.export_jobs_action,
            "snapshot.import": self.import_jobs_action,
            "group.manage": self.group_manager_action,
            "archive.inspect": self.archive_inspection_action,
            "duplicates.works": self.duplicate_works_action,
            "folder.open": self.open_folder_action,
            "details.open": self.details_action,
            "list.activate": self.activate_selected_action,
            "list.refresh": self.refresh_list_action,
            "settings.open": self.settings_action,
            "screenshot.capture": self.screenshot_action,
        }
        for action_id, action in action_map.items():
            action.setEnabled(states[action_id])
        self.start_button.setEnabled(states["download.start"])
        self.stop_button.setEnabled(states["job.stop"])
        self.retry_button.setEnabled(states["job.rescan_full"])
        for action_id, button in getattr(self, "quick_action_buttons", {}).items():
            if action_id in states:
                button.setEnabled(states[action_id])
        return states

    def _start_control_server(self) -> None:
        QLocalServer.removeServer(CONTROL_SERVER_NAME)
        self.control_server = QLocalServer(self)
        self.control_server.newConnection.connect(self._accept_control_connection)
        if not self.control_server.listen(CONTROL_SERVER_NAME):
            self.log(f"CLI 제어 서버 시작 실패: {self.control_server.errorString()}", "ERROR")
        else:
            self.log(f"CLI 제어 준비: {CONTROL_SERVER_NAME}")

    def _accept_control_connection(self) -> None:
        while self.control_server.hasPendingConnections():
            socket = self.control_server.nextPendingConnection()
            self.control_sockets.add(socket)
            socket.readyRead.connect(lambda s=socket: self._read_control_request(s))
            socket.disconnected.connect(lambda s=socket: self.control_sockets.discard(s))

    def _read_control_request(self, socket: Any) -> None:
        raw = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        if not raw:
            return
        try:
            request = json.loads(raw.splitlines()[0])
            result = self._handle_control_action(request)
            response = {"ok": True, "result": result}
        except Exception as error:
            self.log(f"CLI 명령 실패: {error}", "ERROR")
            response = {"ok": False, "error": str(error)}
        socket.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        socket.flush()
        socket.disconnectFromServer()

    def _handle_control_action(self, request: dict[str, Any]) -> Any:
        action = request.get("action")
        if action == "ping":
            return {"pong": True}
        if action == "enqueue":
            job = self.enqueue_download(
                url=str(request.get("url") or ""),
                start=request.get("start"),
                last=request.get("last"),
                output_dir=str(request.get("output") or self.output_edit.text()),
                show_browser=bool(request.get("showBrowser", False)),
                metadata_only=bool(request.get("metadataOnly", False)),
                image_concurrency=request.get("imageConcurrency"),
                scan_mode=str(request.get("scanMode") or "new"),
            )
            return job.to_dict()
        if action == "stop":
            return {"stopped": self.stop_active_job(request.get("jobId"))}
        if action == "pause":
            return self.pause_active_job(request.get("jobId"))
        if action == "resume":
            return self.resume_active_job(request.get("jobId"))
        if action == "cancel":
            return self.cancel_queued_job(str(request.get("jobId") or ""))
        if action == "queue_list":
            return self.pending_queue_snapshot()
        if action == "queue_move":
            return self.move_queued_job(
                str(request.get("jobId") or ""),
                before_job_id=str(request.get("beforeJobId") or ""),
                position=str(request.get("position") or ""),
            )
        if action == "retry":
            job = self.retry_job(request.get("jobId"))
            return job.to_dict() if job else None
        if action == "rescan":
            job = self.rescan_job(
                str(request.get("jobId") or ""),
                str(request.get("mode") or "new"),
                request.get("start"),
                request.get("last"),
            )
            return job.to_dict() if job else None
        if action == "refresh_metadata":
            job = self.refresh_job_metadata(str(request.get("jobId") or ""))
            return job.to_dict()
        if action == "set_output":
            return {"outputDir": self.set_output_folder(str(request.get("path") or ""))}
        if action == "settings":
            return settings_snapshot(self.config)
        if action == "set_settings":
            updates = request.get("updates")
            if not isinstance(updates, dict):
                raise ValueError("설정 변경 내용이 올바르지 않습니다.")
            return self.apply_settings(updates, reset=bool(request.get("reset")))
        if action == "import_settings":
            result = import_app_settings(
                Path(str(request.get("input") or "")),
                execute=bool(request.get("execute")),
            )
            if result.get("executed"):
                self.apply_settings(dict(result["after"]))
            return result
        if action == "reset_settings":
            result = reset_app_settings(execute=bool(request.get("execute")))
            if result.get("executed"):
                self.apply_settings(dict(result["after"]))
            return result
        if action == "show_settings":
            return {
                "shown": self.show_settings_dialog(
                    str(request.get("tab") or "general"),
                    str(request.get("search") or ""),
                )
            }
        if action == "close_settings":
            return {"closed": self.close_settings_dialog()}
        if action == "show_cookie_manager":
            return {
                "shown": self.show_cookie_manager(
                    str(request.get("provider") or "manatoki")
                )
            }
        if action == "close_cookie_manager":
            return {"closed": self.close_cookie_manager()}
        if action == "show_proxy_credential_manager":
            return {"shown": self.show_proxy_credential_manager()}
        if action == "close_proxy_credential_manager":
            return {"closed": self.close_proxy_credential_manager()}
        if action == "show_embedded_browser":
            return {
                "shown": self.show_embedded_browser(
                    str(request.get("url") or ""),
                    navigate=bool(request.get("navigate")),
                    confirmed=bool(request.get("confirmed")),
                )
            }
        if action == "close_embedded_browser":
            return {"closed": self.close_embedded_browser()}
        if action == "preview_completion_action":
            return self.preview_completion_action(
                str(request.get("completionAction") or "exit"),
                int(request.get("countdownSeconds") or 15),
            )
        if action == "cancel_completion_action":
            return {"cancelled": self.cancel_completion_action()}
        if action == "notification_status":
            return self.notification_status_snapshot()
        if action == "preview_notification":
            return self.preview_notification(
                str(request.get("kind") or "complete"),
                str(request.get("title") or "알림 미리보기 작품"),
                str(request.get("detail") or ""),
            )
        if action == "close_notifications":
            return {"closed": self.close_notification_messages()}
        if action == "inspect_clipboard":
            return self.inspect_clipboard_text(
                str(request.get("text") or ""), prompt=bool(request.get("prompt"))
            )
        if action == "export_jobs_snapshot":
            return self.export_jobs_snapshot_now(str(request.get("output") or ""))
        if action == "import_jobs_snapshot":
            input_path = str(request.get("input") or "")
            if request.get("execute"):
                return self.execute_jobs_snapshot_import(input_path)
            return import_jobs_snapshot(Path(input_path), execute=False)
        if action == "show_jobs_snapshot_import":
            return {"shown": self.show_jobs_snapshot_import(str(request.get("input") or ""))}
        if action == "close_jobs_snapshot_import":
            return {"closed": self.close_jobs_snapshot_dialog()}
        if action == "groups":
            return self.list_groups_snapshot()
        if action == "create_group":
            return self.create_work_group(str(request.get("name") or ""))
        if action == "rename_group":
            return self.rename_work_group(
                str(request.get("groupId") or ""), str(request.get("name") or "")
            )
        if action == "assign_group":
            return self.assign_work_group(
                str(request.get("jobId") or ""), str(request.get("groupId") or "")
            )
        if action == "show_group_manager":
            return {"shown": self.show_group_manager()}
        if action == "close_group_manager":
            return {"closed": self.close_group_manager()}
        if action == "show_archive_inspection":
            return {
                "shown": self.show_archive_inspection(str(request.get("path") or ""))
            }
        if action == "close_archive_inspection":
            return {"closed": self.close_archive_inspection()}
        if action == "archive_viewer_policy":
            return archive_viewer_policy_snapshot(self.config)
        if action == "persistence_status":
            return self.persistence_status_snapshot()
        if action == "list_performance_status":
            return self.list_performance_status_snapshot()
        if action == "sleep_prevention_status":
            return self.sleep_prevention_status_snapshot()
        if action == "recover_interrupted":
            return self.recover_interrupted_records(
                execute=bool(request.get("execute"))
            )
        if action == "show_recovery_dialog":
            return {"shown": self.show_recovery_dialog()}
        if action == "close_recovery_dialog":
            return {"closed": self.close_recovery_dialog()}
        if action == "show_duplicate_works":
            return {"shown": self.show_duplicate_works()}
        if action == "close_duplicate_works":
            return {"closed": self.close_duplicate_works()}
        if action == "show_duplicate_images":
            return self.start_duplicate_images(
                str(request.get("jobId") or ""),
                str(request.get("algorithm") or "sha256"),
            )
        if action == "close_duplicate_images":
            return {"closed": self.close_duplicate_images()}
        if action == "tray":
            return self.handle_tray_command(
                str(request.get("command") or "status"),
                str(request.get("message") or ""),
            )
        if action == "set_image_concurrency":
            return self.set_image_concurrency(int(request.get("value") or 0))
        if action == "set_concurrency":
            works = request.get("works")
            images = request.get("images")
            return self.set_concurrency(
                works=int(works) if works is not None else None,
                images=int(images) if images is not None else None,
            )
        if action == "set_retry_policy":
            retry_count = request.get("retryCount")
            backoff = request.get("backoffSeconds")
            return self.set_retry_policy(
                retry_count=int(retry_count) if retry_count is not None else None,
                backoff_seconds=int(backoff) if backoff is not None else None,
            )
        if action == "open_folder":
            return {"opened": self.open_output_folder(request.get("jobId"))}
        if action == "move_folder":
            return self.move_job_folder(
                str(request.get("jobId") or ""),
                str(request.get("output") or ""),
                execute=bool(request.get("execute")),
            )
        if action == "rebuild_metadata":
            return self.rebuild_job_metadata(
                str(request.get("jobId") or ""),
                execute=bool(request.get("execute")),
            )
        if action == "verify_files":
            return self.start_file_verification(str(request.get("jobId") or ""))
        if action == "preview_images":
            episode = request.get("episode")
            return self.start_image_preview(
                str(request.get("jobId") or ""),
                int(episode) if episode is not None else None,
            )
        if action == "convert_images":
            return self.start_image_conversion(
                str(request.get("jobId") or ""),
                str(request.get("format") or "webp"),
                int(request.get("quality") or 90),
                max_width=(
                    int(request["maxWidth"])
                    if request.get("maxWidth") is not None
                    else None
                ),
                max_height=(
                    int(request["maxHeight"])
                    if request.get("maxHeight") is not None
                    else None
                ),
                excluded_extensions=(
                    [str(value) for value in request.get("excludedExtensions")]
                    if isinstance(request.get("excludedExtensions"), list)
                    else None
                ),
                execute=False,
            )
        if action == "image_processing_policy":
            return image_processing_policy_snapshot(self.config)
        if action == "pdf_status":
            return self.pdf_status_snapshot()
        if action == "generate_pdf":
            return self.start_pdf_generation(
                str(request.get("jobId") or ""),
                execute=bool(request.get("execute")),
                automatic=False,
            )
        if action == "cancel_pdf_generation":
            return self.cancel_pdf_generation(str(request.get("jobId") or ""))
        if action == "close_pdf_generation":
            return {"closed": self.close_pdf_generation_dialogs()}
        if action == "cancel_image_conversion":
            return self.cancel_image_conversion(str(request.get("jobId") or ""))
        if action == "close_image_conversion":
            return {"closed": self.close_image_conversion_dialog()}
        if action == "open_source":
            return {"opened": self.open_job_source(request.get("jobId"))}
        if action == "open_cover":
            return {"opened": self.open_job_cover(request.get("jobId"))}
        if action == "show_details":
            return {"shown": self.show_job_details(request.get("jobId"))}
        if action == "close_details":
            return {"closed": self.close_job_details()}
        if action == "show_run_log":
            return {"shown": self.show_run_log(str(request.get("runId") or ""))}
        if action == "close_run_log":
            return {"closed": self.close_run_log()}
        if action == "copy_link":
            return {"copied": self.copy_job_link(request.get("jobId"))}
        if action == "copy_id":
            return {"copied": self.copy_job_id(request.get("jobId"))}
        if action == "copy_path":
            return {"copied": self.copy_job_path(request.get("jobId"))}
        if action == "copy_title":
            return {"copied": self.copy_job_title(request.get("jobId"))}
        if action == "show_job_menu":
            return {"shown": self.show_job_context_menu_for_job(request.get("jobId"))}
        if action == "clear_log":
            self.clear_logs()
            return {"cleared": True}
        if action == "status":
            return self.status_snapshot()
        if action == "list_jobs":
            query = str(request.get("query") or "")
            state = str(request.get("status") or "")
            sort = str(request.get("sort") or "updated")
            limit = max(1, min(1000, int(request.get("limit") or 200)))
            offset = max(0, int(request.get("offset") or 0))
            return self.list_jobs_snapshot(query, state, sort, limit, offset)
        if action == "job_info":
            return self.job_info_snapshot(str(request.get("jobId") or ""))
        if action == "list_runs":
            return self.list_runs_snapshot(
                str(request.get("jobId") or ""),
                int(request.get("limit") or 100),
                int(request.get("offset") or 0),
            )
        if action == "set_note":
            return self.set_job_note(
                str(request.get("jobId") or ""), str(request.get("text") or "")
            )
        if action == "set_list_filter":
            return self.set_history_filters(
                str(request.get("query") or ""),
                str(request.get("status") or ""),
                str(request.get("sort") or "updated"),
            )
        if action == "pin_job":
            return self.set_job_pin(
                str(request.get("jobId") or ""), bool(request.get("pinned"))
            )
        if action == "tag_job":
            return self.set_job_tag(
                str(request.get("jobId") or ""), str(request.get("color") or "none")
            )
        if action == "remove_record":
            return self.remove_job_record(str(request.get("jobId") or ""))
        if action == "cleanup_records":
            states = [str(state) for state in request.get("states") or []]
            return self.cleanup_job_records(states)
        if action == "refresh_list":
            return self.refresh_job_list()
        if action == "thumbnail_cache_status":
            return self.thumbnail_cache_snapshot()
        if action == "cleanup_thumbnail_cache":
            return self.cleanup_thumbnail_cache_now()
        if action == "cleanup_run_history":
            return self.cleanup_run_history_now(
                int(request.get("maxPerWork") or 500),
                int(request.get("maxAgeDays") or 365),
            )
        if action == "list_view_state":
            return dict(self.list_view_state)
        if action == "preview_list_view_state":
            return self.preview_list_view_state(
                str(request.get("state") or "auto"),
                str(request.get("message") or ""),
            )
        if action == "keyboard_shortcuts":
            return shortcut_settings_snapshot(self.config)
        if action == "apply_shortcut_overrides":
            overrides = request.get("shortcutOverrides")
            if not isinstance(overrides, dict):
                raise ValueError("단축키 설정이 올바르지 않습니다.")
            return self.apply_shortcut_overrides(overrides)
        if action == "show_shortcut_help":
            return {"shown": self.show_shortcut_help()}
        if action == "close_shortcut_help":
            return {"closed": self.close_shortcut_help()}
        if action == "performance_diagnostics":
            return job_database_diagnostics()
        if action == "show_performance_diagnostics":
            return {"shown": True, "report": self.show_performance_diagnostics()}
        if action == "close_performance_diagnostics":
            return {"closed": self.close_performance_diagnostics()}
        if action == "start_performance_benchmark":
            self.show_performance_diagnostics()
            started = self.start_performance_benchmark(
                [int(size) for size in request.get("sizes") or []],
                int(request.get("pageSize") or 200),
                str(request.get("output") or ""),
            )
            return {"started": started, **self.performance_benchmark_snapshot()}
        if action == "show_doctor":
            return {"shown": True, "report": self.show_dependency_diagnostics()}
        if action == "close_doctor":
            return {"closed": self.close_dependency_diagnostics()}
        if action == "export_diagnostics":
            return self.export_diagnostic_bundle(str(request.get("output") or ""))
        if action == "start_stability_test":
            if self.active_performance_dialog is None:
                self.show_performance_diagnostics()
            started = self.start_stability_test(
                int(request.get("records") or 10_000),
                int(request.get("cycles") or 100),
                str(request.get("output") or ""),
            )
            return {"started": started, **self.stability_test_snapshot()}
        if action == "resource_status":
            return {"ok": True, **self.resource_snapshot()}
        if action == "memory_status":
            return self.memory_status_snapshot(
                max(0, min(1000, int(request.get("childLimit") or 200)))
            )
        if action == "local_api_status":
            return self.local_api_status_snapshot()
        if action == "local_api_token":
            if not request.get("confirmed"):
                raise ValueError("로컬 API 토큰 작업에는 명시적 확인이 필요합니다.")
            if request.get("rotate"):
                return self.rotate_local_api_token()
            if request.get("copy"):
                return {
                    **self.local_api_status_snapshot(),
                    "copied": self.copy_local_api_token(),
                }
            return self.local_api_token_snapshot(reveal=bool(request.get("reveal")))
        if action == "hitomi_inspect":
            try:
                return inspect_hitomi_reference(
                    str(request.get("reference") or ""),
                    provider_hint=str(request.get("provider") or "auto"),
                )
            except HitomiReferenceError as error:
                return error.to_dict()
        if action == "show_hitomi_inspector":
            return self.show_hitomi_inspector(
                str(request.get("reference") or ""),
                str(request.get("provider") or "auto"),
            )
        if action == "close_hitomi_inspector":
            return {"closed": self.close_hitomi_inspector()}
        if action == "hitomi_metadata_plan":
            try:
                return hitomi_metadata_request_plan(
                    str(request.get("reference") or ""),
                    provider_hint=str(request.get("provider") or "auto"),
                    config=self.config,
                )
            except HitomiReferenceError as error:
                return error.to_dict()
        if action == "show_hitomi_metadata":
            return self.show_hitomi_metadata(
                str(request.get("reference") or ""),
                str(request.get("provider") or "auto"),
                str(request.get("fixture") or ""),
            )
        if action == "close_hitomi_metadata":
            return {"closed": self.close_hitomi_metadata()}
        if action == "keyboard_focus":
            self.showNormal()
            self.raise_()
            self.activateWindow()
            return self.focus_keyboard_target(
                str(request.get("target") or ""), bool(request.get("clear"))
            )
        if action == "screenshot":
            return {"path": self.capture_window(str(request.get("path") or ""))}
        if action == "window":
            return self.set_window_geometry(request)
        if action == "self_test":
            return {"started": self.start_self_test()}
        if action == "show":
            self.showNormal()
            self.raise_()
            self.activateWindow()
            return {"shown": True}
        if action == "quit":
            self.force_close = bool(request.get("force"))
            self.exit_requested = True
            if self.force_close:
                for job_id in list(self.active_contexts):
                    self.stop_active_job(job_id)
                for context in list(self.image_conversion_processes.values()):
                    context.process.kill()
                for context in list(self.pdf_generation_processes.values()):
                    context.process.kill()
            QTimer.singleShot(100, self.close)
            return {"quitting": True}
        raise ValueError(f"지원하지 않는 CLI 동작입니다: {action}")

    def closeEvent(self, event: QCloseEvent) -> None:
        diagnostic_processes = tuple(
            process
            for process in (
                self.self_test_process,
                self.performance_benchmark_process,
                self.stability_test_process,
            )
            if process
            and process.state() != QProcess.ProcessState.NotRunning
        )
        if (
            not self.force_close
            and not self.exit_requested
            and self.config.get("closeToTray", False)
            and self.tray_icon
            and self.tray_icon.isVisible()
        ):
            self.hide()
            event.ignore()
            self.statusBar().showMessage("시스템 트레이로 숨겼습니다.", 3000)
            return
        if not self.force_close and (
            self.active_contexts
            or self.image_conversion_processes
            or self.pdf_generation_processes
            or self.pending_pdf_jobs
            or diagnostic_processes
        ):
            answer = QMessageBox.question(
                self,
                "실행 중인 작업",
                "다운로드·이미지 변환·PDF 생성 또는 진단 작업이 진행 중입니다. "
                "작업을 중지하고 종료할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.exit_requested = False
                event.ignore()
                return
            for job_id in list(self.active_contexts):
                self.stop_active_job(job_id)
            for context in list(self.image_conversion_processes.values()):
                context.process.kill()
            for context in list(self.pdf_generation_processes.values()):
                context.process.kill()
        self.pending_pdf_jobs.clear()
        for process in diagnostic_processes:
            process.kill()
        window_config = self.window_snapshot()
        window_config["qtGeometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.config["window"] = window_config
        self.config["outputDir"] = self.output_edit.text()
        self.config["showBrowser"] = self.show_browser_check.isChecked()
        self.config["imageConcurrency"] = self.image_concurrency_spin.value()
        self.config["workConcurrency"] = self.work_concurrency_spin.value()
        self.config["retryCount"] = self.retry_count_spin.value()
        self.config["retryBackoffSeconds"] = self.retry_backoff_spin.value()
        save_config(self.config)
        self.job_ui_update_timer.stop()
        self._flush_job_card_updates()
        self.persist_timer.stop()
        self._flush_job_history()
        self.sleep_prevention_controller.close()
        self.local_api_server.stop()
        self.control_server.close()
        if self.tray_icon:
            self.tray_icon.hide()
        QLocalServer.removeServer(CONTROL_SERVER_NAME)
        event.accept()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.ApplicationPaletteChange
            and getattr(self, "theme_mode", "") == "system"
        ):
            resolved = self._resolve_theme("system")
            if resolved != self.resolved_theme:
                self.resolved_theme = resolved
                self._apply_style()
                delegate = self.task_list.itemDelegate()
                if isinstance(delegate, JobItemDelegate):
                    delegate.set_theme(resolved)
                    self.task_list.viewport().update()
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.config.get("minimizeToTray", False)
            and self.tray_icon
            and self.tray_icon.isVisible()
        ):
            QTimer.singleShot(0, self.hide)
