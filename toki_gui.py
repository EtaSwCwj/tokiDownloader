from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QProcess, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QCloseEvent, QFont, QPixmap
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from toki_core import (
    CONTROL_SERVER_NAME,
    EVENT_PREFIX,
    LOG_PATH,
    ROOT_DIR,
    DownloadJob,
    append_log,
    build_downloader_args,
    clear_log_file,
    find_node,
    load_config,
    normalize_range,
    open_in_explorer,
    read_log_tail,
    save_config,
    validate_url,
)


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class TaskCard(QWidget):
    def __init__(self, job: DownloadJob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.job_id = job.job_id
        self.setObjectName("taskCard")
        self.loaded_cover_path = ""

        self.cover_label = QLabel("표지")
        self.cover_label.setObjectName("coverLabel")
        self.cover_label.setFixedSize(72, 94)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.state_label = QLabel(job.state)
        self.state_label.setObjectName("stateLabel")
        self.state_label.setFixedWidth(72)
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        self.title_label = QLabel(job.title)
        self.title_label.setFont(title_font)
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.detail_label = QLabel(job.url)
        self.detail_label.setObjectName("detailLabel")
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(job.progress)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.state_label)
        header.addWidget(self.title_label, 1)

        details_layout = QVBoxLayout()
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(5)
        details_layout.addLayout(header)
        details_layout.addWidget(self.detail_label)
        details_layout.addWidget(self.progress)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 8, 10, 8)
        layout.setSpacing(10)
        layout.addWidget(self.cover_label)
        layout.addLayout(details_layout, 1)
        self.update_job(job)

    def update_job(self, job: DownloadJob) -> None:
        self._update_cover(job.cover_path)
        self.title_label.setText(job.title)
        self.state_label.setText(job.state)
        self.state_label.setProperty("state", job.state)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

        details: list[str] = []
        if job.episode_total:
            details.append(f"회차 {job.episode_index}/{job.episode_total}")
        if job.episode_number:
            details.append(f"현재 {job.episode_number}화")
        if job.image_total:
            details.append(f"이미지 {job.image_current}/{job.image_total}")
        if not details:
            details.append(job.url)
        if job.error:
            details.append(job.error.splitlines()[0])
        self.detail_label.setText(" · ".join(details))
        self.progress.setValue(max(0, min(100, job.progress)))

    def _update_cover(self, cover_path: str) -> None:
        if not cover_path or cover_path == self.loaded_cover_path:
            return
        pixmap = QPixmap(cover_path)
        if pixmap.isNull():
            return
        self.loaded_cover_path = cover_path
        self.cover_label.setText("")
        self.cover_label.setPixmap(
            pixmap.scaled(
                self.cover_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.jobs: dict[str, DownloadJob] = {}
        self.cards: dict[str, TaskCard] = {}
        self.items: dict[str, QListWidgetItem] = {}
        self.pending_jobs: deque[DownloadJob] = deque()
        self.active_job: DownloadJob | None = None
        self.process: QProcess | None = None
        self.cancel_requested = False
        self.force_close = False
        self.stdout_buffer = ""
        self.stderr_buffer = ""
        self.control_sockets: set[Any] = set()

        self.setWindowTitle("tokiDownloader")
        window_config = self.config.get("window", {})
        self.resize(int(window_config.get("width", 860)), int(window_config.get("height", 720)))
        self.setMinimumSize(QSize(720, 580))
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))

        self._build_actions()
        self._build_ui()
        self._apply_style()
        self._start_control_server()

        for line in read_log_tail(120):
            self.log_edit.appendPlainText(line)
        self.log("GUI 시작")

    def _build_actions(self) -> None:
        self.start_action = QAction("다운로드 시작", self)
        self.start_action.setShortcut("Ctrl+Enter")
        self.start_action.triggered.connect(self.start_from_form)

        self.stop_action = QAction("현재 작업 중지", self)
        self.stop_action.setShortcut("Ctrl+K")
        self.stop_action.triggered.connect(self.stop_active_job)

        self.retry_action = QAction("선택 작업 재시도", self)
        self.retry_action.setShortcut("Ctrl+R")
        self.retry_action.triggered.connect(self.retry_selected_job)

        self.open_folder_action = QAction("저장 폴더 열기", self)
        self.open_folder_action.setShortcut("Ctrl+O")
        self.open_folder_action.triggered.connect(self.open_output_folder)

        self.clear_log_action = QAction("로그 지우기", self)
        self.clear_log_action.triggered.connect(self.clear_logs)

        self.screenshot_action = QAction("GUI 화면 캡처", self)
        self.screenshot_action.setShortcut("Ctrl+Shift+S")
        self.screenshot_action.triggered.connect(self.capture_window)

        self.exit_action = QAction("종료", self)
        self.exit_action.triggered.connect(self.close)

    def _build_ui(self) -> None:
        work_menu = self.menuBar().addMenu("작업")
        work_menu.addAction(self.start_action)
        work_menu.addAction(self.stop_action)
        work_menu.addAction(self.retry_action)
        work_menu.addSeparator()
        work_menu.addAction(self.exit_action)

        tools_menu = self.menuBar().addMenu("도구")
        tools_menu.addAction(self.open_folder_action)
        tools_menu.addAction(self.screenshot_action)
        tools_menu.addAction(self.clear_log_action)

        help_menu = self.menuBar().addMenu("도움말")
        cli_action = help_menu.addAction("CLI 명령 보기")
        cli_action.triggered.connect(self.show_cli_help)

        central = QWidget()
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

        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 999999)
        self.start_spin.setSpecialValueText("처음")
        self.start_spin.setToolTip("0이면 처음 회차부터")

        self.last_spin = QSpinBox()
        self.last_spin.setRange(0, 999999)
        self.last_spin.setSpecialValueText("마지막")
        self.last_spin.setToolTip("0이면 마지막 회차까지")

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
        self.retry_button = QPushButton("재시도")
        self.retry_button.clicked.connect(self.retry_selected_job)

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
        input_layout.setColumnStretch(1, 1)

        queue_header = QHBoxLayout()
        queue_title = QLabel("다운로드 작업")
        queue_font = QFont()
        queue_font.setBold(True)
        queue_title.setFont(queue_font)
        self.queue_summary = QLabel("대기 0 · 실행 0 · 완료 0 · 문제 0")
        self.queue_summary.setObjectName("mutedLabel")
        queue_header.addWidget(queue_title)
        queue_header.addStretch(1)
        queue_header.addWidget(self.queue_summary)

        self.task_list = QListWidget()
        self.task_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.task_list.setSpacing(4)

        log_box = QGroupBox("실행 로그")
        log_layout = QVBoxLayout(log_box)
        log_actions = QHBoxLayout()
        log_actions.addStretch(1)
        copy_log_button = QPushButton("복사")
        copy_log_button.clicked.connect(self.copy_logs)
        screenshot_button = QPushButton("화면 캡처")
        screenshot_button.clicked.connect(self.capture_window)
        clear_log_button = QPushButton("지우기")
        clear_log_button.clicked.connect(self.clear_logs)
        log_actions.addWidget(screenshot_button)
        log_actions.addWidget(copy_log_button)
        log_actions.addWidget(clear_log_button)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(3000)
        self.log_edit.setMinimumHeight(150)
        log_layout.addLayout(log_actions)
        log_layout.addWidget(self.log_edit)

        root.addWidget(input_box)
        root.addLayout(queue_header)
        root.addWidget(self.task_list, 1)
        root.addWidget(log_box)
        self.setCentralWidget(central)

        status = QStatusBar()
        self.status_label = QLabel("준비")
        self.overall_progress = QProgressBar()
        self.overall_progress.setFixedWidth(220)
        self.overall_progress.setRange(0, 100)
        status.addWidget(self.status_label, 1)
        status.addPermanentWidget(self.overall_progress)
        self.setStatusBar(status)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { color: #20262e; }
            QMainWindow { background: #f3f5f7; color: #20262e; }
            QMenuBar { background: #ffffff; color: #20262e; border-bottom: 1px solid #d9dee5; }
            QMenuBar::item:selected { background: #e9f1ff; }
            QMenu { background: #ffffff; color: #20262e; border: 1px solid #cfd6df; }
            QMenu::item:selected { background: #e9f1ff; }
            #inputBox { background: #ffffff; border: 1px solid #d8dde5; border-radius: 5px; }
            QLineEdit, QSpinBox, QPlainTextEdit, QListWidget {
                background: #ffffff; color: #20262e; border: 1px solid #cfd6df; border-radius: 4px;
                padding: 5px; selection-background-color: #2f7de1;
                selection-color: #ffffff;
            }
            QPushButton { min-height: 28px; padding: 0 12px; border: 1px solid #c9d0d9;
                border-radius: 4px; background: #ffffff; color: #20262e; }
            QPushButton:hover { background: #edf4ff; border-color: #8eb8ee; }
            QPushButton:pressed { background: #dfeeff; }
            #primaryButton { background: #2f7de1; color: white; border-color: #2469bd; font-weight: 700; }
            #primaryButton:hover { background: #3b89ee; }
            QListWidget { padding: 4px; }
            QListWidget::item { border: 0; }
            QListWidget::item:selected { background: #dcecff; border-radius: 5px; }
            #taskCard { background: #ffffff; border: 1px solid #d8dde5; border-radius: 5px; }
            #coverLabel { color: #7b8794; background: #eef1f4; border: 1px solid #d8dde5;
                border-radius: 4px; }
            #detailLabel, #mutedLabel { color: #667282; }
            #stateLabel { border-radius: 3px; padding: 3px; font-weight: 700; color: white; background: #7b8794; }
            #stateLabel[state="실행 중"] { background: #1a73e8; }
            #stateLabel[state="완료"] { background: #3b7d44; }
            #stateLabel[state="오류"] { background: #d13b32; }
            #stateLabel[state="중지됨"] { background: #cf7a18; }
            QProgressBar { border: 1px solid #cfd6df; border-radius: 3px; text-align: center; background: #eef1f4; }
            QProgressBar::chunk { background: #2f7de1; }
            QGroupBox { color: #20262e; font-weight: 700; }
            QStatusBar { color: #20262e; background: #f3f5f7; }
            QGroupBox QPlainTextEdit { font-family: Consolas, "Malgun Gothic"; font-size: 9pt; font-weight: 400; }
            """
        )

    def log(self, message: str, level: str = "INFO", job_id: str | None = None) -> None:
        clean = ANSI_RE.sub("", str(message)).strip()
        if not clean:
            return
        resolved_job_id = job_id or (self.active_job.job_id if self.active_job else "-")
        line = append_log(clean, level, resolved_job_id)
        self.log_edit.appendPlainText(line)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_from_form(self) -> None:
        try:
            self.enqueue_download(
                self.url_edit.text(),
                self.start_spin.value() or None,
                self.last_spin.value() or None,
                self.output_edit.text(),
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
    ) -> DownloadJob:
        valid_url = validate_url(url)
        start_value, last_value = normalize_range(start, last)
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        find_node()

        job = DownloadJob(
            job_id=uuid.uuid4().hex[:10],
            url=valid_url,
            output_dir=str(output_path),
            start=start_value,
            last=last_value,
        )
        self.jobs[job.job_id] = job
        self.pending_jobs.append(job)
        self._add_job_card(job)
        self.log(f"작업 추가: {job.url}", job_id=job.job_id)
        self._update_summary()
        self._start_next_job()
        return job

    def _add_job_card(self, job: DownloadJob) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, job.job_id)
        card = TaskCard(job)
        item.setSizeHint(QSize(100, 116))
        self.task_list.addItem(item)
        self.task_list.setItemWidget(item, card)
        self.cards[job.job_id] = card
        self.items[job.job_id] = item
        self.task_list.setCurrentItem(item)

    def _update_job_card(self, job: DownloadJob) -> None:
        card = self.cards.get(job.job_id)
        if card:
            card.update_job(job)
        if self.active_job and self.active_job.job_id == job.job_id:
            self.overall_progress.setValue(job.progress)
            self.status_label.setText(f"{job.state}: {job.title}")
        self._update_summary()

    def _start_next_job(self) -> None:
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if not self.pending_jobs:
            self.active_job = None
            self.status_label.setText("준비")
            self.overall_progress.setValue(0)
            self._update_summary()
            return

        job = self.pending_jobs.popleft()
        self.active_job = job
        self.cancel_requested = False
        job.state = "실행 중"
        job.error = ""
        self._update_job_card(job)

        process = QProcess(self)
        self.process = process
        self.stdout_buffer = ""
        self.stderr_buffer = ""
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(find_node())
        process.setArguments(build_downloader_args(job, json_events=True))
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.started.connect(
            lambda: self.log(
                f"작업 시작 PID={int(process.processId())}: {job.url}", job_id=job.job_id
            )
        )
        process.errorOccurred.connect(
            lambda error: self.log(f"프로세스 오류: {error}", "ERROR", job.job_id)
        )
        process.finished.connect(self._process_finished)
        process.start()

    def _consume_lines(self, text: str, is_stderr: bool) -> None:
        buffer_name = "stderr_buffer" if is_stderr else "stdout_buffer"
        buffer_value = getattr(self, buffer_name) + text
        while "\n" in buffer_value:
            line, buffer_value = buffer_value.split("\n", 1)
            self._handle_process_line(line.rstrip("\r"), is_stderr)
        setattr(self, buffer_name, buffer_value)

    def _read_stdout(self) -> None:
        if self.process:
            data = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._consume_lines(data, False)

    def _read_stderr(self) -> None:
        if self.process:
            data = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            self._consume_lines(data, True)

    def _handle_process_line(self, line: str, is_stderr: bool) -> None:
        clean = ANSI_RE.sub("", line).strip()
        if not clean:
            return
        if clean.startswith(EVENT_PREFIX):
            try:
                self._handle_downloader_event(json.loads(clean[len(EVENT_PREFIX):]))
            except json.JSONDecodeError:
                self.log(f"이벤트 해석 실패: {clean}", "ERROR")
            return
        self.log(clean, "ERROR" if is_stderr else "INFO")

    def _handle_downloader_event(self, event: dict[str, Any]) -> None:
        job = self.active_job
        if not job:
            return
        event_name = event.get("event")
        if event_name == "work_metadata":
            metadata = event.get("metadata") or {}
            job.title = metadata.get("folderName") or metadata.get("title") or job.title
            job.output_path = str(event.get("outputPath") or "")
            job.cover_url = str(metadata.get("coverUrl") or "")
            job.cover_path = str(event.get("coverPath") or "")
        elif event_name == "queue_ready":
            job.episode_total = int(event.get("selectedEpisodes") or 0)
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

        if job.episode_total:
            fraction = job.image_current / job.image_total if job.image_total else 0.0
            completed_before = max(0, job.episode_index - 1)
            job.progress = min(99, int(((completed_before + fraction) / job.episode_total) * 100))
            if event_name == "episode_completed":
                job.progress = min(99, int((job.episode_index / job.episode_total) * 100))
        if event_name == "completed":
            job.progress = 100
        self._update_job_card(job)

    def _process_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if self.stdout_buffer.strip():
            self._handle_process_line(self.stdout_buffer, False)
        if self.stderr_buffer.strip():
            self._handle_process_line(self.stderr_buffer, True)
        self.stdout_buffer = ""
        self.stderr_buffer = ""

        job = self.active_job
        if job:
            if self.cancel_requested:
                job.state = "중지됨"
            elif exit_code == 0:
                job.state = "완료"
                job.progress = 100
            else:
                job.state = "오류"
                if not job.error:
                    job.error = f"프로세스 종료 코드 {exit_code}"
            self.log(f"작업 종료: {job.state} (code={exit_code})", job_id=job.job_id)
            self._update_job_card(job)

        self.process = None
        self.active_job = None
        self.cancel_requested = False
        QTimer.singleShot(250, self._start_next_job)

    def stop_active_job(self) -> bool:
        if not self.process or self.process.state() == QProcess.ProcessState.NotRunning:
            self.log("중지할 실행 작업이 없습니다.")
            return False
        self.cancel_requested = True
        pid = int(self.process.processId())
        self.log(f"작업 중지 요청: PID {pid}")
        if pid and os.name == "nt":
            subprocess.Popen(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            self.process.kill()
        return True

    def selected_job(self, job_id: str | None = None) -> DownloadJob | None:
        if job_id:
            return self.jobs.get(job_id)
        item = self.task_list.currentItem()
        if item:
            return self.jobs.get(str(item.data(Qt.ItemDataRole.UserRole)))
        if self.active_job:
            return self.active_job
        return next(reversed(self.jobs.values()), None) if self.jobs else None

    def retry_job(self, job_id: str | None = None) -> DownloadJob | None:
        source = self.selected_job(job_id)
        if not source:
            self.log("재시도할 작업을 선택해주세요.")
            return None
        return self.enqueue_download(source.url, source.start, source.last, source.output_dir)

    def retry_selected_job(self) -> None:
        self.retry_job()

    def choose_output_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.output_edit.text())
        if selected:
            self.set_output_folder(selected)

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

    def open_output_folder(self, job_id: str | None = None) -> str:
        job = self.selected_job(job_id)
        target = job.output_path if job and job.output_path else self.output_edit.text()
        open_in_explorer(target)
        self.log(f"폴더 열기: {target}")
        return target

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
        if not self.grab().save(str(target), "PNG"):
            raise OSError(f"GUI 화면을 저장하지 못했습니다: {target}")
        self.log(f"GUI 화면 캡처: {target}")
        self.statusBar().showMessage(f"화면 저장: {target}", 3000)
        return str(target)

    def show_cli_help(self) -> None:
        QMessageBox.information(
            self,
            "CLI 명령",
            "toki-cli.cmd download --url URL [--start N --last N --output PATH]\n"
            "toki-cli.cmd status [--json]\n"
            "toki-cli.cmd stop\n"
            "toki-cli.cmd retry [--job ID]\n"
            "toki-cli.cmd set-output PATH\n"
            "toki-cli.cmd open-folder [--job ID]\n"
            "toki-cli.cmd logs --tail 200\n"
            "toki-cli.cmd copy-log [--tail 3000]\n"
            "toki-cli.cmd screenshot [--output PATH]\n"
            "toki-cli.cmd clear-log\n"
            "toki-cli.cmd show\n"
            "toki-cli.cmd quit",
        )

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "running": self.active_job is not None,
            "activeJob": self.active_job.to_dict() if self.active_job else None,
            "pendingCount": len(self.pending_jobs),
            "jobs": [job.to_dict() for job in self.jobs.values()],
            "outputDir": self.output_edit.text(),
            "logPath": str(LOG_PATH),
            "screenshotPath": str(LOG_PATH.parent / "gui-screenshot.png"),
        }

    def _update_summary(self) -> None:
        states = [job.state for job in self.jobs.values()]
        self.queue_summary.setText(
            f"대기 {states.count('대기')} · 실행 {states.count('실행 중')} · "
            f"완료 {states.count('완료')} · 문제 {states.count('오류') + states.count('중지됨')}"
        )

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
                str(request.get("url") or ""),
                request.get("start"),
                request.get("last"),
                str(request.get("output") or self.output_edit.text()),
            )
            return job.to_dict()
        if action == "stop":
            return {"stopped": self.stop_active_job()}
        if action == "retry":
            job = self.retry_job(request.get("jobId"))
            return job.to_dict() if job else None
        if action == "set_output":
            return {"outputDir": self.set_output_folder(str(request.get("path") or ""))}
        if action == "open_folder":
            return {"opened": self.open_output_folder(request.get("jobId"))}
        if action == "clear_log":
            self.clear_logs()
            return {"cleared": True}
        if action == "status":
            return self.status_snapshot()
        if action == "screenshot":
            return {"path": self.capture_window(str(request.get("path") or ""))}
        if action == "show":
            self.showNormal()
            self.raise_()
            self.activateWindow()
            return {"shown": True}
        if action == "quit":
            self.force_close = bool(request.get("force"))
            if self.force_close and self.process:
                self.stop_active_job()
            QTimer.singleShot(100, self.close)
            return {"quitting": True}
        raise ValueError(f"지원하지 않는 CLI 동작입니다: {action}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self.force_close
            and self.process
            and self.process.state() != QProcess.ProcessState.NotRunning
        ):
            answer = QMessageBox.question(
                self,
                "실행 중인 작업",
                "다운로드가 진행 중입니다. 작업을 중지하고 종료할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.stop_active_job()
        self.config["window"] = {"width": self.width(), "height": self.height()}
        self.config["outputDir"] = self.output_edit.text()
        save_config(self.config)
        self.control_server.close()
        QLocalServer.removeServer(CONTROL_SERVER_NAME)
        event.accept()
