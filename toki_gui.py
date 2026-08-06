from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QByteArray, QAbstractListModel, QModelIndex, QPoint, QProcess, QRect, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QColor, QCloseEvent, QDesktopServices, QFont, QPainter, QPen, QPixmap
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from toki_core import (
    ACTIVE_JOB_STATES,
    CONTROL_SERVER_NAME,
    EVENT_PREFIX,
    JOB_DB_PATH,
    LOG_PATH,
    ROOT_DIR,
    TAG_COLORS,
    DownloadJob,
    DownloadRun,
    available_work_slots,
    append_log,
    build_work_key,
    build_downloader_args,
    clear_log_file,
    count_jobs,
    count_runs,
    delete_job_record,
    delete_job_records,
    error_category_label,
    find_node,
    hydrate_job_metadata,
    load_config,
    load_job_by_id,
    load_job_by_work_key,
    load_jobs_page,
    load_run,
    load_runs_page,
    mark_job_cancelled,
    mark_run_cancelled,
    move_job_folder as execute_job_folder_move,
    normalize_image_concurrency,
    normalize_retry_backoff,
    normalize_retry_count,
    normalize_scan_request,
    normalize_work_concurrency,
    open_in_explorer,
    plan_job_folder_move,
    plan_metadata_rebuild,
    read_log_tail,
    read_run_log,
    rebuild_job_metadata as execute_metadata_rebuild,
    recover_interrupted_jobs,
    rescan_job_parameters,
    resolve_cover_path,
    reorder_pending_jobs,
    save_config,
    save_jobs,
    save_runs,
    set_job_pause_state,
    set_process_tree_paused,
    retry_backoff_seconds,
    should_auto_retry,
    update_job_note,
    update_job_markers,
    validate_url,
)


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cover_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.cache_limit = 128

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), 92)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        job = index.data(JobListModel.JobRole)
        if not isinstance(job, DownloadJob):
            return

        painter.save()
        card = option.rect.adjusted(4, 3, -4, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(QColor("#9ebfe7" if selected else "#d8dde5"), 1))
        painter.setBrush(QColor("#dcecff" if selected else "#ffffff"))
        painter.drawRoundedRect(card, 5, 5)
        if job.tag_color and job.tag_color in TAG_COLORS:
            tag_rect = QRect(card.left(), card.top() + 5, 5, card.height() - 10)
            painter.fillRect(tag_rect, QColor(TAG_COLORS[job.tag_color]))

        cover_rect = card.adjusted(9, 8, 0, -8)
        cover_rect.setWidth(52)
        painter.setPen(QPen(QColor("#d8dde5"), 1))
        painter.setBrush(QColor("#eef1f4"))
        painter.drawRoundedRect(cover_rect, 4, 4)
        cover = self._cover(job.cover_path)
        if cover:
            x = cover_rect.x() + (cover_rect.width() - cover.width()) // 2
            y = cover_rect.y() + (cover_rect.height() - cover.height()) // 2
            painter.drawPixmap(x, y, cover)
        else:
            painter.setPen(QColor("#7b8794"))
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
        painter.setPen(QColor("#20262e"))
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
        if not details:
            details.append(job.url)
        detail_text = " · ".join(details)
        detail_rect = card.adjusted(body_x - card.left(), 35, -10, 0)
        detail_rect.setHeight(20)
        painter.setFont(option.font)
        painter.setPen(QColor("#667282"))
        detail_text = painter.fontMetrics().elidedText(
            detail_text, Qt.TextElideMode.ElideRight, max(20, detail_rect.width())
        )
        painter.drawText(detail_rect, Qt.AlignmentFlag.AlignVCenter, detail_text)

        progress_rect = card.adjusted(body_x - card.left(), 60, -10, -9)
        painter.setPen(QPen(QColor("#cfd6df"), 1))
        painter.setBrush(QColor("#eef1f4"))
        painter.drawRect(progress_rect)
        progress = max(0, min(100, job.progress))
        chunk = progress_rect.adjusted(1, 1, -1, -1)
        chunk.setWidth(int(chunk.width() * progress / 100))
        painter.fillRect(chunk, QColor("#2f7de1"))
        painter.setPen(QColor("#20262e"))
        painter.drawText(progress_rect, Qt.AlignmentFlag.AlignCenter, f"{progress}%")
        painter.restore()

    def _cover(self, cover_path: str) -> QPixmap | None:
        if not cover_path:
            return None
        cached = self.cover_cache.get(cover_path)
        if cached is not None:
            self.cover_cache.move_to_end(cover_path)
            return cached
        source = QPixmap(cover_path)
        if source.isNull():
            return None
        scaled = source.scaled(
            QSize(50, 66),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.cover_cache[cover_path] = scaled
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
        self.cover_label.setStyleSheet("border: 1px solid #cfd6df; background: #eef1f4;")
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


@dataclass
class ProcessContext:
    job: DownloadJob
    run: DownloadRun
    process: QProcess | None = None
    stdout_buffer: str = ""
    stderr_buffer: str = ""
    cancel_requested: bool = False
    paused: bool = False
    attempt_count: int = 0
    retry_generation: int = 0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.jobs: dict[str, DownloadJob] = {}
        self.jobs_by_work: dict[str, DownloadJob] = {}
        self.history_page_size = 200
        self.history_loaded = 0
        self.history_total = 0
        self.history_all_total = 0
        self.history_loading = False
        self.history_query = ""
        self.history_state = ""
        self.history_sort = "updated"
        self.history_filter_timer = QTimer(self)
        self.history_filter_timer.setSingleShot(True)
        self.history_filter_timer.setInterval(250)
        self.history_filter_timer.timeout.connect(self.apply_history_filters)
        self.pending_jobs: deque[DownloadJob] = deque()
        self.active_contexts: dict[str, ProcessContext] = {}
        self.self_test_process: QProcess | None = None
        self.file_verify_processes: dict[str, QProcess] = {}
        self.self_test_stdout = ""
        self.self_test_stderr = ""
        self.last_self_test: dict[str, Any] | None = None
        self.startup_recovery: dict[str, Any] = {
            "jobCount": 0,
            "runCount": 0,
            "jobIds": [],
            "runIds": [],
        }
        self.force_close = False
        self.control_sockets: set[Any] = set()
        self.active_context_menu: QMenu | None = None
        self.active_detail_dialog: WorkDetailDialog | None = None
        self.active_run_log_dialog: RunLogDialog | None = None
        self.active_file_verify_dialog: FileVerificationDialog | None = None
        self.dirty_job_ids: set[str] = set()
        self.persist_timer = QTimer(self)
        self.persist_timer.setSingleShot(True)
        self.persist_timer.setInterval(600)
        self.persist_timer.timeout.connect(self._flush_job_history)

        self.setWindowTitle("tokiDownloader")
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
        self._start_control_server()
        self._restore_job_history()

        for line in read_log_tail(120):
            self.log_edit.appendPlainText(line)
        self.log("GUI 시작")

    def _restore_window_geometry(self, window_config: dict[str, Any]) -> None:
        encoded_geometry = window_config.get("qtGeometry")
        if isinstance(encoded_geometry, str) and encoded_geometry:
            saved_geometry = QByteArray.fromBase64(encoded_geometry.encode("ascii"))
            if not saved_geometry.isEmpty() and self.restoreGeometry(saved_geometry):
                self.geometry_restored = True
                return

        width = max(self.minimumWidth(), int(window_config.get("width") or 860))
        height = max(self.minimumHeight(), int(window_config.get("height") or 720))
        self.resize(width, height)

        saved_x = window_config.get("x")
        saved_y = window_config.get("y")
        if isinstance(saved_x, (int, float)) and isinstance(saved_y, (int, float)):
            desired = QRect(int(saved_x), int(saved_y), width, height)
            if any(screen.availableGeometry().intersects(desired) for screen in QApplication.screens()):
                self.restore_position = desired.topLeft()
                return

        primary = QApplication.primaryScreen()
        if primary:
            available = primary.availableGeometry()
            centered = available.center() - QPoint(width // 2, height // 2)
            self.restore_position = centered

    def _build_actions(self) -> None:
        self.start_action = QAction("다운로드 시작", self)
        self.start_action.setShortcut("Ctrl+Enter")
        self.start_action.triggered.connect(self.start_from_form)

        self.stop_action = QAction("현재 작업 중지", self)
        self.stop_action.setShortcut("Ctrl+K")
        self.stop_action.triggered.connect(self.stop_active_job)

        self.pause_action = QAction("현재 작업 일시정지", self)
        self.pause_action.setShortcut("Ctrl+P")
        self.pause_action.triggered.connect(self.pause_selected_active_job)

        self.resume_action = QAction("일시정지 작업 계속", self)
        self.resume_action.setShortcut("Ctrl+Shift+P")
        self.resume_action.triggered.connect(self.resume_selected_active_job)

        self.retry_action = QAction("선택 작품 전체 재검사", self)
        self.retry_action.setShortcut("Ctrl+R")
        self.retry_action.triggered.connect(self.retry_selected_job)

        self.new_scan_action = QAction("선택 작품 신규 회차만 검사", self)
        self.new_scan_action.triggered.connect(
            lambda: self.rescan_selected_job("new")
        )

        self.range_scan_action = QAction("선택 작품 입력 범위 검사", self)
        self.range_scan_action.triggered.connect(
            lambda: self.rescan_selected_job("range")
        )

        self.open_folder_action = QAction("저장 폴더 열기", self)
        self.open_folder_action.setShortcut("Ctrl+O")
        self.open_folder_action.triggered.connect(self.open_output_folder)

        self.details_action = QAction("작품 정보 및 실행 이력", self)
        self.details_action.setShortcut("Ctrl+I")
        self.details_action.triggered.connect(self.show_job_details)

        self.clear_log_action = QAction("로그 지우기", self)
        self.clear_log_action.triggered.connect(self.clear_logs)

        self.screenshot_action = QAction("GUI 화면 캡처", self)
        self.screenshot_action.setShortcut("Ctrl+Shift+S")
        self.screenshot_action.triggered.connect(self.capture_window)

        self.self_test_action = QAction("자체 점검 실행", self)
        self.self_test_action.triggered.connect(self.start_self_test)

        self.refresh_list_action = QAction("작품 목록 새로고침", self)
        self.refresh_list_action.setShortcut("F5")
        self.refresh_list_action.triggered.connect(self.refresh_job_list)

        self.cleanup_records_action = QAction("완료·오류 기록 정리...", self)
        self.cleanup_records_action.triggered.connect(self.confirm_cleanup_records)

        self.exit_action = QAction("종료", self)
        self.exit_action.triggered.connect(self.close)

    def _build_ui(self) -> None:
        work_menu = self.menuBar().addMenu("작업")
        work_menu.addAction(self.start_action)
        work_menu.addAction(self.stop_action)
        work_menu.addAction(self.pause_action)
        work_menu.addAction(self.resume_action)
        work_menu.addAction(self.retry_action)
        work_menu.addAction(self.new_scan_action)
        work_menu.addAction(self.range_scan_action)
        work_menu.addSeparator()
        work_menu.addAction(self.exit_action)

        tools_menu = self.menuBar().addMenu("도구")
        tools_menu.addAction(self.open_folder_action)
        tools_menu.addAction(self.details_action)
        tools_menu.addAction(self.refresh_list_action)
        tools_menu.addAction(self.cleanup_records_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.screenshot_action)
        tools_menu.addAction(self.self_test_action)
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
        queue_font = QFont()
        queue_font.setBold(True)
        queue_title.setFont(queue_font)
        self.queue_summary = QLabel("대기 0 · 실행 0 · 완료 0 · 문제 0")
        self.queue_summary.setObjectName("mutedLabel")
        queue_header.addWidget(queue_title)
        queue_header.addStretch(1)
        queue_header.addWidget(self.queue_summary)

        filter_bar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("제목, 작가, 그룹, 작품 ID 검색")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda: self.history_filter_timer.start())
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
        self.task_list.setItemDelegate(JobItemDelegate(self.task_list))
        self.task_list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.task_list.setUniformItemSizes(True)
        self.task_list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.task_list.setSpacing(2)
        self.task_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.task_list.setToolTip(
            "한 번 클릭하면 작업을 선택하고, 더블클릭하면 다운로드 폴더를 엽니다."
        )
        self.task_list.doubleClicked.connect(self.open_job_index_folder)
        self.task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.task_list.customContextMenuRequested.connect(self.show_job_context_menu)
        self.task_list.verticalScrollBar().valueChanged.connect(self._maybe_load_more_history)

        log_box = QGroupBox("실행 로그")
        log_layout = QVBoxLayout(log_box)
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

        root.addWidget(input_box)
        root.addLayout(queue_header)
        root.addLayout(filter_bar)
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
            QDialog { background: #f3f5f7; color: #20262e; }
            QMenuBar { background: #ffffff; color: #20262e; border-bottom: 1px solid #d9dee5; }
            QMenuBar::item:selected { background: #e9f1ff; }
            QMenu { background: #ffffff; color: #20262e; border: 1px solid #cfd6df; }
            QMenu::item:selected { background: #e9f1ff; }
            #inputBox { background: #ffffff; border: 1px solid #d8dde5; border-radius: 5px; }
            QLineEdit, QSpinBox, QPlainTextEdit, QListView, QTableWidget {
                background: #ffffff; color: #20262e; border: 1px solid #cfd6df; border-radius: 4px;
                padding: 5px; selection-background-color: #2f7de1;
                selection-color: #ffffff;
            }
            QTableWidget { gridline-color: #d8dde5; padding: 0; }
            QHeaderView::section {
                background: #e9edf2; color: #20262e; border: 0;
                border-right: 1px solid #cfd6df; border-bottom: 1px solid #cfd6df;
                padding: 5px; font-weight: 700;
            }
            QPushButton { min-height: 28px; padding: 0 12px; border: 1px solid #c9d0d9;
                border-radius: 4px; background: #ffffff; color: #20262e; }
            QPushButton:hover { background: #edf4ff; border-color: #8eb8ee; }
            QPushButton:pressed { background: #dfeeff; }
            #primaryButton { background: #2f7de1; color: white; border-color: #2469bd; font-weight: 700; }
            #primaryButton:hover { background: #3b89ee; }
            QListView { padding: 2px; }
            QListView::item { border: 0; }
            #detailLabel, #mutedLabel { color: #667282; }
            #stateLabel { border-radius: 3px; padding: 3px; font-weight: 700; color: white; background: #7b8794; }
            #stateLabel[state="실행 중"] { background: #1a73e8; }
            #stateLabel[state="재시도 대기"] { background: #cf7a18; }
            #stateLabel[state="인증 필요"] { background: #b33a7a; }
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
        index = self.task_model.index(0, 0)
        self.task_list.setCurrentIndex(index)
        self.task_list.scrollTo(index)

    def _restore_job_history(self) -> None:
        self.startup_recovery = recover_interrupted_jobs()
        metadata_updates: list[DownloadJob] = []
        self.history_all_total = count_jobs()
        self.history_total = count_jobs(self.history_query, self.history_state)
        page = load_jobs_page(
            self.history_page_size,
            0,
            self.history_query,
            self.history_state,
            self.history_sort,
        )
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
        if self.startup_recovery["jobCount"] or self.startup_recovery["runCount"]:
            self.log(
                "이전 종료 작업 복구: "
                f"작품 {self.startup_recovery['jobCount']}개, "
                f"실행 이력 {self.startup_recovery['runCount']}개를 중지됨으로 변경"
            )
        if self.task_model.rowCount():
            self.task_list.setCurrentIndex(self.task_model.index(0, 0))
            self.task_list.scrollToTop()
        self._update_summary()

    def _job_matches_history_filters(self, job: DownloadJob) -> bool:
        if self.history_state and job.state != self.history_state:
            return False
        query = self.history_query.casefold().strip()
        if not query:
            return True
        haystack = " ".join((job.title, job.work_key, job.url)).casefold()
        return query in haystack

    def apply_history_filters(self, *_args: Any) -> None:
        self.history_filter_timer.stop()
        self._flush_job_history()
        selected = self.selected_job()
        selected_key = selected.work_key if selected else ""
        self.history_query = self.search_edit.text().strip()
        self.history_state = str(self.state_filter_combo.currentData() or "")
        self.history_sort = str(self.sort_combo.currentData() or "updated")
        page = load_jobs_page(
            self.history_page_size,
            0,
            self.history_query,
            self.history_state,
            self.history_sort,
        )
        display_jobs: list[DownloadJob] = []
        for stored_job in page:
            job = self.jobs_by_work.get(stored_job.work_key) or stored_job
            if stored_job.work_key not in self.jobs_by_work:
                self.jobs[job.job_id] = job
                self.jobs_by_work[job.work_key] = job
            display_jobs.append(job)
        self.task_model.replace_jobs(display_jobs)
        self.history_all_total = count_jobs()
        self.history_total = count_jobs(self.history_query, self.history_state)
        self.history_loaded = len(display_jobs)
        if selected_key and selected_key in self.task_model.row_by_key:
            row = self.task_model.row_by_key[selected_key]
            self.task_list.setCurrentIndex(self.task_model.index(row, 0))
        elif display_jobs:
            self.task_list.setCurrentIndex(self.task_model.index(0, 0))
        self._update_summary()

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
        self.apply_history_filters()
        self.task_list.viewport().update()
        result = {
            "refreshed": True,
            "loaded": self.task_model.rowCount(),
            "total": self.history_total,
            "thumbnailCacheCleared": True,
        }
        self.log("작품 목록과 썸네일 캐시 새로고침")
        return result

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
        scrollbar = self.task_list.verticalScrollBar()
        if scrollbar.maximum() <= 0 or value < scrollbar.maximum() - 24:
            return
        self._load_more_history()

    def _load_more_history(self) -> None:
        if self.history_loading or self.history_loaded >= self.history_total:
            return
        self.history_loading = True
        try:
            page = load_jobs_page(
                self.history_page_size,
                self.history_loaded,
                self.history_query,
                self.history_state,
                self.history_sort,
            )
            self.history_loaded += len(page)
            unseen = [job for job in page if job.work_key not in self.jobs_by_work]
            for job in unseen:
                self.jobs[job.job_id] = job
                self.jobs_by_work[job.work_key] = job
            self.task_model.append_jobs(unseen)
        finally:
            self.history_loading = False
        self._update_summary()

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
            self.log(f"작업 기록 저장 실패: {error}", "ERROR")

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
        process = QProcess(self)
        context.process = process
        self._update_job_card(context.job)

        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(find_node())
        process.setArguments(build_downloader_args(context.job, json_events=True))
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
        setattr(context, buffer_name, buffer_value)

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
        if event_name in {
            "work_metadata", "queue_ready", "episode_started",
            "episode_completed", "completed", "error",
        }:
            save_runs([run])
        self._update_job_card(job)

    def _process_finished(
        self,
        job_id: str,
        exit_code: int,
        _exit_status: QProcess.ExitStatus,
    ) -> None:
        context = self.active_contexts.get(job_id)
        if not context:
            return
        if context.stdout_buffer.strip():
            self._handle_process_line(job_id, context.stdout_buffer, False)
        if context.stderr_buffer.strip():
            self._handle_process_line(job_id, context.stderr_buffer, True)
        context.stdout_buffer = ""
        context.stderr_buffer = ""
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
        contexts = list(self.active_contexts.values())
        if not contexts:
            self.status_label.setText("준비")
            self.overall_progress.setValue(0)
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
        python = Path(sys.executable).with_name("python.exe")
        process = QProcess(self)
        process.setWorkingDirectory(str(ROOT_DIR))
        process.setProgram(str(python if python.is_file() else Path(sys.executable)))
        process.setArguments(
            [
                str(ROOT_DIR / "toki_app.py"),
                "verify-files",
                "--job",
                job.job_id,
                "--json",
                "--ascii-json",
            ]
        )
        process.finished.connect(
            lambda exit_code, _status, selected=job.job_id: self._file_verification_finished(
                selected, exit_code
            )
        )
        self.file_verify_processes[job.job_id] = process
        process.start()
        self.log("작품 파일 검사 시작(별도 프로세스)", job_id=job.job_id)
        self.statusBar().showMessage(f"{job.title} 파일 검사 중…")
        return {"started": True, "jobId": job.job_id, "processId": 0}

    def _file_verification_finished(self, job_id: str, exit_code: int) -> None:
        process = self.file_verify_processes.pop(job_id, None)
        if process is None:
            return
        stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        process.deleteLater()
        try:
            result = json.loads(stdout.strip())
        except json.JSONDecodeError:
            message = stderr.strip() or stdout.strip() or f"종료 코드 {exit_code}"
            self.log(f"작품 파일 검사 실패: {message}", "ERROR", job_id)
            QMessageBox.critical(self, "작품 파일 검사 실패", message)
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
        menu.addSeparator()
        menu.addAction("원본 링크 복사", lambda: self.copy_job_link(job.job_id))
        menu.addAction("작품명 복사", lambda: self.copy_job_title(job.job_id))
        menu.addSeparator()
        menu.addAction(
            "고정 해제" if job.pinned else "목록 상단에 고정",
            lambda: self.set_job_pin(job.job_id, not job.pinned),
        )
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
        if (
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

        process = QProcess(self)
        self.self_test_process = process
        self.self_test_stdout = ""
        self.self_test_stderr = ""
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
            self.self_test_stdout += bytes(
                self.self_test_process.readAllStandardOutput()
            ).decode("utf-8", errors="replace")

    def _read_self_test_stderr(self) -> None:
        if self.self_test_process:
            self.self_test_stderr += bytes(
                self.self_test_process.readAllStandardError()
            ).decode("utf-8", errors="replace")

    def _self_test_process_error(self, _error: QProcess.ProcessError) -> None:
        if not self.self_test_process:
            return
        message = f"자체 점검 프로세스 오류: {self.self_test_process.errorString()}"
        self.log(message, "ERROR", job_id="self-test")
        self.status_label.setText("자체 점검 실행 오류")

    def _self_test_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_self_test_stdout()
        self._read_self_test_stderr()
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

    def show_cli_help(self) -> None:
        QMessageBox.information(
            self,
            "CLI 명령",
            "toki-cli.cmd download --url URL [--start N --last N --output PATH --show-browser]\n"
            "toki-cli.cmd status [--json]\n"
            "toki-cli.cmd list [--query TEXT --status STATE --sort updated|title|progress --apply-gui --json]\n"
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
            "toki-cli.cmd retry [--job ID]\n"
            "toki-cli.cmd rescan --job ID --mode new|full|range [--start N --last N]\n"
            "toki-cli.cmd set-output PATH\n"
            "toki-cli.cmd open-folder [--job ID]\n"
            "toki-cli.cmd copy-link [--job ID]\n"
            "toki-cli.cmd copy-title [--job ID]\n"
            "toki-cli.cmd job-menu [--job ID]\n"
            "toki-cli.cmd logs --tail 200\n"
            "toki-cli.cmd copy-log [--tail 3000]\n"
            "toki-cli.cmd screenshot [--output PATH]\n"
            "toki-cli.cmd window [--x N --y N --width N --height N --maximize|--normal]\n"
            "toki-cli.cmd self-test [--json] [--core-only]\n"
            "toki-cli.cmd clear-log\n"
            "toki-cli.cmd show\n"
            "toki-cli.cmd quit",
        )

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
            "jobs": [job.to_dict() for job in self.jobs.values()],
            "loadedJobCount": len(self.jobs),
            "totalJobCount": self.history_all_total,
            "filteredJobCount": self.history_total,
            "outputDir": self.output_edit.text(),
            "imageConcurrency": self.image_concurrency_spin.value(),
            "workConcurrency": self.work_concurrency_spin.value(),
            "retryCount": self.retry_count_spin.value(),
            "retryBackoffSeconds": self.retry_backoff_spin.value(),
            "startupRecovery": self.startup_recovery,
            "logPath": str(LOG_PATH),
            "jobDbPath": str(JOB_DB_PATH),
            "screenshotPath": str(LOG_PATH.parent / "gui-screenshot.png"),
            "selfTestRunning": bool(
                self.self_test_process
                and self.self_test_process.state() != QProcess.ProcessState.NotRunning
            ),
            "fileVerificationJobs": sorted(self.file_verify_processes),
            "lastSelfTest": self.last_self_test,
            "listFilter": {
                "query": self.history_query,
                "status": self.history_state,
                "sort": self.history_sort,
                "loaded": self.task_model.rowCount(),
                "total": self.history_total,
            },
            "window": self.window_snapshot(),
        }

    def window_snapshot(self) -> dict[str, Any]:
        maximized = self.isMaximized()
        geometry = self.normalGeometry() if maximized else None
        position = geometry.topLeft() if geometry is not None else self.pos()
        return {
            "x": position.x(),
            "y": position.y(),
            "width": geometry.width() if geometry is not None else self.width(),
            "height": geometry.height() if geometry is not None else self.height(),
            "maximized": maximized,
        }

    def set_window_geometry(self, request: dict[str, Any]) -> dict[str, Any]:
        width = request.get("width")
        height = request.get("height")
        x = request.get("x")
        y = request.get("y")
        maximized = request.get("maximized")

        if any(value is not None for value in (width, height, x, y)):
            self.showNormal()
            target_width = max(self.minimumWidth(), int(width or self.width()))
            target_height = max(self.minimumHeight(), int(height or self.height()))
            self.resize(target_width, target_height)
            self.move(int(x if x is not None else self.x()), int(y if y is not None else self.y()))
        if maximized is True:
            self.showMaximized()
        elif maximized is False:
            self.showNormal()
        QApplication.processEvents()
        return self.window_snapshot()

    def _update_summary(self) -> None:
        states = [job.state for job in self.task_model.rows]
        self.queue_summary.setText(
            f"전체 {self.history_all_total} · 검색 {self.history_total} · 로딩 {len(states)} · "
            f"대기 {states.count('대기')} · 실행 {states.count('실행 중')} · "
            f"재시도 {states.count('재시도 대기')} · "
            f"일시정지 {states.count('일시정지')} · 완료 {states.count('완료')} · "
            f"문제 {states.count('오류') + states.count('중지됨') + states.count('인증 필요')}"
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
            if self.force_close:
                for job_id in list(self.active_contexts):
                    self.stop_active_job(job_id)
            QTimer.singleShot(100, self.close)
            return {"quitting": True}
        raise ValueError(f"지원하지 않는 CLI 동작입니다: {action}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            not self.force_close
            and self.active_contexts
        ):
            answer = QMessageBox.question(
                self,
                "실행 중인 작업",
                "다운로드가 진행 중입니다. 작업을 중지하고 종료할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for job_id in list(self.active_contexts):
                self.stop_active_job(job_id)
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
        self.persist_timer.stop()
        self._flush_job_history()
        self.control_server.close()
        QLocalServer.removeServer(CONTROL_SERVER_NAME)
        event.accept()
