from __future__ import annotations

import json
import threading
import uuid
from types import SimpleNamespace
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QTimer, pyqtSignal, QItemSelection, QItemSelectionModel
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QButtonGroup, QGridLayout, QCheckBox, QPlainTextEdit, QPushButton, QHBoxLayout, QMessageBox, QMenu

import toki_core as core
from toki_library import archive_library_items, delete_library_items, restore_library_trash
from toki_archive_cleanup import cleanup_empty_episode_folders


class _Signals(QObject):
    finished = pyqtSignal(str, object, str)
    progress = pyqtSignal(object)


class _Task(QRunnable):
    def __init__(self, key, operation):
        super().__init__()
        self.key, self.operation = key, operation
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.finished.emit(self.key, self.operation(self.signals.progress.emit), "")
        except Exception as error:
            self.signals.finished.emit(self.key, {}, str(error))


class LibraryDialog(QDialog):
    def __init__(self, owner, ids, archive=False):
        super().__init__(owner)
        self.owner, self.ids = owner, list(ids)
        self.operation_id = ""
        self.plan = None
        self.confirm_after_preview = False
        self.setWindowTitle("선택 작품 ZIP 압축 / 빈 폴더 정리" if archive else "선택 작품 처리 · Delete")
        self.resize(740, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"선택한 작품 {len(ids)}개 · " + (
            "작품 전체 ZIP · 작품당 1개 · 회차 폴더 순서 유지" if archive else "작업 버튼 → 확인창 → 실행"
        )))
        self.selected_action = "archive" if archive else ""
        self.action_buttons = {}
        self.action_group = QButtonGroup(self)
        self.action_group.setExclusive(True)
        choices = [
                ("작품 전체 ZIP 압축", "archive"),
                ("남은 빈 회차 폴더 정리\nZIP·메타데이터·미완료 회차 보존", "cleanup-folders"),
            ] if archive else [
                ("목록만 삭제\n다운로드 파일 보존", "delete:records"),
                ("다운로드 파일 삭제\n압축·목록 보존 · 앱 휴지통으로 이동", "delete:files"),
                ("압축 파일만 삭제\n원본·목록 보존 · 앱 휴지통으로 이동", "delete:archives"),
                ("다운로드 취소\n선택한 대기·진행 작업 중지", "cancel-downloads"),
            ]
        grid = QGridLayout()
        for index, (text, action) in enumerate(choices):
            button = QPushButton(text)
            button.setObjectName("library_" + action.replace(":", "_"))
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setStyleSheet(
                "QPushButton { min-height: 60px; padding: 6px 10px; }"
                "QPushButton:checked { background: #2f7de1; color: white; border: 2px solid #6ab2ff; }"
            )
            button.clicked.connect(lambda _checked, action=action: self.request_action(action))
            self.action_group.addButton(button)
            self.action_buttons[action] = button
            grid.addWidget(button, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        if archive:
            self.action_buttons["archive"].setChecked(True)
        self.remove_originals = QCheckBox("ZIP 무결성 검사 성공 후 원본 정리 (ZIP에서 복원 가능)")
        self.remove_originals.setChecked(bool(owner.config.get("archiveRemoveOriginals", True)))
        self.remove_originals.setVisible(archive)
        layout.addWidget(self.remove_originals)
        self.info = QLabel("작품 전체를 ZIP 하나로 저장합니다. 내부는 회차 폴더 → 페이지 순서입니다.\n원본 정리는 검증된 회차 파일만 대상으로 하며 메타데이터와 표지는 보존합니다." if archive else "파일 삭제는 영구 삭제가 아닙니다. 작품 폴더의 .toki-trash에 이동합니다.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("위에서 원하는 작업 버튼을 눌러주세요. 아직 어떤 파일도 변경하지 않았습니다.")
        layout.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        self.preview_button = QPushButton("대상 미리보기")
        self.preview_button.setStyleSheet("QPushButton:disabled { color: #7a8492; }")
        self.preview_button.setEnabled(archive)
        self.execute_button = QPushButton("확인 후 실행")
        self.execute_button.setStyleSheet("QPushButton:disabled { color: #7a8492; }")
        self.execute_button.setEnabled(False)
        self.stop_button = QPushButton("압축 중지")
        self.stop_button.setVisible(archive)
        self.stop_button.setEnabled(False)
        close = QPushButton("취소 / 닫기")
        for button in (self.preview_button, self.execute_button, self.stop_button, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.preview_button.clicked.connect(lambda: self.start(False))
        self.execute_button.clicked.connect(lambda: self.start(True))
        self.stop_button.clicked.connect(lambda: owner.cancel_library_operation(self.operation_id))
        close.clicked.connect(self.close)
        self.remove_originals.toggled.connect(self.invalidate)

    def select_action(self, action, *, preview=False):
        if action not in self.action_buttons and not (self.selected_action == "archive" and action == "archive"):
            raise ValueError(f"이 창에서 선택할 수 없는 작업입니다: {action}")
        self.selected_action = action
        self.remove_originals.setVisible(action == "archive")
        self.stop_button.setVisible(action == "archive")
        if action == "cleanup-folders":
            self.info.setText("ZIP과 완료 기록이 일치하는 빈 회차 폴더만 정리합니다.\n파일·하위 폴더가 남은 회차, 미완료 회차, 링크는 보존합니다. ZIP 전체를 다시 검사하지 않습니다.")
        elif action == "archive":
            self.info.setText("작품 전체를 ZIP 하나로 저장합니다. 검증 후 원본 정리 시 빈 회차 폴더도 정리합니다.\n메타데이터·표지·미완료 회차는 보존합니다.")
        if action in self.action_buttons:
            self.action_buttons[action].setChecked(True)
        self.invalidate()
        self.preview_button.setEnabled(True)
        if preview:
            self.start(False)

    def request_action(self, action):
        self.select_action(action)
        self.start(False, confirm_after_preview=True)

    def set_action_buttons_enabled(self, enabled):
        for button in self.action_buttons.values():
            button.setEnabled(enabled)

    def invalidate(self, *_args):
        self.plan = None
        self.confirm_after_preview = False
        self.execute_button.setEnabled(False)
        self.details.clear()

    def start(self, execute, *, confirm_after_preview=False):
        action = self.selected_action
        if not action or (execute and (not self.plan or self.plan.get("executed") or not self.plan.get("canExecute", True))):
            return
        explanation = {
            "delete:records": f"선택한 작품 {len(self.ids)}개의 목록 및 실행 기록을 삭제할까요?\n\n다운로드 파일과 압축 파일은 그대로 보존합니다.",
            "delete:files": f"선택한 작품의 다운로드 파일 {(self.plan or {}).get('fileCount', 0):,}개를 앱 휴지통으로 이동할까요?\n\n압축 파일과 목록 기록은 보존합니다.",
            "delete:archives": f"선택한 작품의 압축 파일 {(self.plan or {}).get('fileCount', 0):,}개를 앱 휴지통으로 이동할까요?\n\n원본 파일과 목록 기록은 보존합니다.",
            "cancel-downloads": f"선택한 작품 {len(self.ids)}개의 대기·진행 중 다운로드를 취소할까요?\n\n이미 받은 파일은 보존합니다.",
            "cleanup-folders": f"완료·압축이 확인된 빈 회차 폴더 {(self.plan or {}).get('folderCount', 0):,}개를 정리할까요?\n\n파일은 삭제하지 않습니다. ZIP·메타데이터·미완료 회차는 보존합니다.",
        }.get(action, self.details.toPlainText()[:1800] + "\n\n위 대상을 처리할까요?")
        if execute and self.plan.get("skippedJobCount"):
            explanation += f"\n\n모의 작업 {self.plan['skippedJobCount']}개는 제외하고 처리 가능한 {self.plan['eligibleJobCount']}개 작품만 처리합니다."
        if execute and QMessageBox.question(self, "선택한 대상 처리 확인", explanation,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.confirm_after_preview = bool(confirm_after_preview and not execute)
            response = self.owner.start_library_operation(
                self.ids, action, execute=execute, remove_originals=self.remove_originals.isChecked(),
                plan_token=self.plan.get("planToken") if self.plan and execute else None,
            )
            self.operation_id = response["operationId"]
            self.preview_button.setEnabled(False)
            self.execute_button.setEnabled(False)
            self.set_action_buttons_enabled(False)
            self.remove_originals.setEnabled(False)
            self.stop_button.setEnabled(execute and action == "archive")
            self.details.setPlainText("처리 중… 진행 상황은 실행 로그에도 기록됩니다.")
        except Exception as error:
            self.confirm_after_preview = False
            QMessageBox.warning(self, "작업을 시작할 수 없음", str(error))

    def confirm_preview(self, key, plan):
        # Closing/replacing the dialog or changing actions cancels the queued confirmation.
        if self.isVisible() and self.owner.active_library_dialog is self and self.operation_id == key and self.plan is plan:
            self.start(True)

    def completed(self, result, error):
        confirm = self.confirm_after_preview
        self.confirm_after_preview = False
        self.preview_button.setEnabled(True)
        self.set_action_buttons_enabled(True)
        self.remove_originals.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.plan = result if not error else None
        can_execute = result.get("canExecute", True)
        self.execute_button.setEnabled(bool(result) and not result.get("executed") and not error and can_execute)
        if error:
            self.details.setPlainText(error)
            return
        heading = "취소됨" if result.get("cancelled") else "일부 실패" if result.get("success") is False else "처리 완료 (폴더 정리 경고)" if result.get("cleanupWarningCount") else "처리 완료"
        lines = [f"{heading if result.get('executed') else '미리보기 — 아직 변경하지 않았습니다.'}",
                 f"작품 {result.get('jobCount', len(self.ids))}개 · 파일 {result.get('fileCount', 0):,}개 · ZIP {result.get('archiveCount', 0):,}개"]
        if "eligibleJobCount" in result:
            lines.append(f"처리 가능 {result['eligibleJobCount']}개 작품 · 모의 작업 제외 {result['skippedJobCount']}개 · 대상 파일 없음 {result['emptyJobCount']}개 작품")
        if not can_execute:
            kind_label = "압축 파일" if result.get("kind") == "archives" else "다운로드 파일"
            lines.insert(0, "정리 가능한 빈 회차 폴더가 없습니다." if result.get("kind") == "empty-folders" else f"삭제할 {kind_label}이 없습니다. 파일과 목록을 변경하지 않았습니다.")
        if "folderCount" in result:
            lines.append(f"빈 회차 폴더 {result['folderCount']:,}개 · 파일은 삭제하지 않음")
        if result.get("executed") and "removedFolderCount" in result:
            lines.append(f"빈 폴더 정리 {result['removedFolderCount']:,}개 · 정리 경고 {result.get('cleanupWarningCount', 0)}개")
        for skipped in result.get("skippedJobs", [])[:30]:
            lines.append(f"제외: {skipped['title']} — {skipped['reason']}")
        if result.get("skippedJobCount", 0) > 30:
            lines.append(f"… 모의 작업 {result['skippedJobCount'] - 30}개 추가 제외")
        if result.get("removeOriginals"):
            lines.append("원본 정리: ZIP 생성·무결성 검사 성공 후에만 실행")
        if result.get("executed"):
            if result.get("kind") == "records":
                lines.append(f"목록 삭제 {result.get('removedRecordCount', 0)}개 · 다운로드/압축 파일 보존")
            elif result.get("kind") in {"files", "archives"}:
                lines.append(f"파일 {result.get('movedFileCount', 0)}개 앱 휴지통으로 이동 · 목록 보존")
            elif self.selected_action == "archive":
                lines.append(f"ZIP 생성 {result.get('createdCount', 0)}개 · 기존 유지 {result.get('skippedCount', 0)}개 · 정리된 원본 {result.get('removedOriginalCount', 0)}개")
        for entry in result.get("results", [])[:50]:
            for warning in entry.get("cleanupWarnings", [])[:20]:
                lines.append(f"정리 경고: {warning['path']} — {warning['message']}")
            if "cancellable" in entry:
                lines.append(f"{entry['title']}: {'취소 요청됨' if entry['cancelRequested'] else '취소 가능' if entry['cancellable'] else '진행 중인 다운로드 없음'}")
            if entry.get("error"):
                lines.append(f"오류 [{entry.get('jobId')}]: {entry['error']}")
            if entry.get("trashManifest"):
                lines.append(f"복구 기록: {entry['trashManifest']}")
        remaining = 100
        for job in result.get("jobs", [])[:100]:
            lines.append(f"\n{job['title']}\n{job.get('outputPath', '')}")
            if job.get("incompleteCount"):
                lines.append(f"미완료/확인 불가 {job['incompleteCount']}회차는 압축하지 않고 보존합니다.")
            for warning in job.get("warnings", [])[:20]:
                lines.append(f"정리 제외: {warning['path']} — {warning['message']}")
            targets = job.get("targets") or [a["path"] for a in job.get("archives", [])]
            shown = min(30, remaining, len(targets))
            root = Path(job.get("outputPath") or ".")
            for raw in targets[:shown]:
                path = Path(raw)
                lines.append(str(path.relative_to(root)) if path.is_relative_to(root) else raw)
            remaining -= shown
            total = job.get("fileCount", len(targets))
            if total > shown:
                lines.append(f"… 외 {total - shown}개")
        self.details.setPlainText("\n".join(lines))
        if result.get("executed") and result.get("kind") == "records" and result.get("success"):
            self.owner.statusBar().showMessage(f"목록 {result['removedRecordCount']}개 삭제 완료 · 다운로드 파일 보존", 6000)
            self.accept()
        elif confirm and not result.get("executed") and can_execute:
            key, plan = self.operation_id, self.plan
            QTimer.singleShot(0, lambda: self.confirm_preview(key, plan))


class LibraryWindowMixin:
    def initialize_library(self):
        self.library_tasks = {}
        self.library_jobs = {}
        self.library_results = {}
        self.pending_auto_archives = set()
        self.active_library_dialog = None

    def setup_library_selection(self):
        self.task_list.setSelectionMode(self.task_list.SelectionMode.ExtendedSelection)
        self.task_list.setToolTip("Ctrl+클릭: 여러 작품 · Shift+클릭: 범위 · Ctrl+A: 로딩된 목록 전체 · Delete: 처리 선택 · 더블클릭: 폴더 열기")
        self.delete_selection_action = QAction("선택 작품 처리...", self.task_list)
        self.delete_selection_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self.delete_selection_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.delete_selection_action.triggered.connect(self.open_selected_library_dialog)
        self.task_list.addAction(self.delete_selection_action)

    def open_selected_library_dialog(self):
        if not self.selected_job_ids():
            self.statusBar().showMessage("먼저 목록에서 작품을 선택해주세요.", 3000)
            return
        self.show_library_dialog()

    def selected_job_ids(self):
        return list(dict.fromkeys(job.job_id for index in self.task_list.selectionModel().selectedRows()
                                 if (job := self.task_model.job_at(index.row())) is not None))

    def select_library_jobs(self, ids=None, clear=False):
        if ids is not None or clear:
            selection = QItemSelection()
            by_id = {self.task_model.job_at(row).job_id: row for row in range(self.task_model.rowCount())}
            for job_id in ids or []:
                if job_id not in by_id:
                    raise ValueError(f"현재 로딩된 목록에 없는 작품입니다: {job_id}")
                index = self.task_model.index(by_id[job_id], 0)
                selection.select(index, index)
            self.task_list.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        return {"jobIds": self.selected_job_ids(), "selectedCount": len(self.selected_job_ids())}

    def show_library_dialog(self, ids=None, archive=False, operation=None, preview=False):
        ids = ids or self.selected_job_ids()
        if not ids:
            raise ValueError("목록에서 작품을 선택해주세요.")
        if self.active_library_dialog:
            self.active_library_dialog.close()
        dialog = LibraryDialog(self, ids, archive)
        if operation:
            dialog.select_action(operation)
        self.active_library_dialog = dialog
        dialog.show()
        if preview:
            QTimer.singleShot(0, lambda: dialog.start(False))
        return {"open": True, "jobIds": ids, "archive": archive}

    def library_context_menu(self, position):
        menu = QMenu(self)
        menu.addAction(f"선택한 {len(self.selected_job_ids())}개 작품 ZIP 압축...", lambda: self.show_library_dialog(archive=True))
        menu.addAction("선택 작품 처리... (Delete)", lambda: self.show_library_dialog())
        self.active_context_menu = menu
        menu.popup(position)

    def library_snapshot(self):
        return {"running": [{"operationId": key, "action": context.action, "jobIds": context.ids}
                            for key, context in self.library_tasks.items()],
                "pendingAutomatic": sorted(self.pending_auto_archives), "results": self.library_results,
                "selection": self.select_library_jobs()}

    def cancel_library_operation(self, key):
        context = self.library_tasks.get(key)
        if not context or context.action != "archive":
            return {"cancelled": False}
        context.cancel.set()
        return {"cancelled": True, "operationId": key}

    def start_library_operation(self, ids, action, *, execute=False, remove_originals=False, plan_token=None, manifest=None):
        ids = list(dict.fromkeys(ids))
        if action == "restore":
            ids = [json.loads(Path(manifest).read_text(encoding="utf-8"))["jobId"]]
        if not ids and action != "restore":
            raise ValueError("작품을 선택해주세요.")
        key = uuid.uuid4().hex[:12]
        if action == "cancel-downloads":
            results = []
            for job_id in ids:
                job = self.selected_job(job_id)
                if not job:
                    raise ValueError(f"작품 기록이 없습니다: {job_id}")
                cancellable = job_id in self.active_contexts or any(j.job_id == job_id for j in self.pending_jobs)
                if execute:
                    if job_id in self.active_contexts:
                        self.stop_active_job(job_id)
                    elif any(j.job_id == job_id for j in self.pending_jobs):
                        self.cancel_queued_job(job_id)
                results.append({"jobId": job_id, "title": job.title, "cancellable": cancellable, "cancelRequested": execute and cancellable})
            result = {"executed": execute, "jobCount": len(ids), "results": results}
            self.library_results[key] = {"done": True, "result": result, "error": ""}
            QTimer.singleShot(0, lambda: self._show_library_result(key, result, ""))
            return {"operationId": key, "started": True}
        if self.library_tasks:
            raise ValueError("현재 압축/파일 처리가 끝난 뒤 다시 시도해주세요.")
        for job_id in ids:
            job = self.selected_job(job_id)
            if not job:
                raise ValueError(f"작품이 없습니다: {job_id}")
            conflict = type(self)._episode_rename_execute_conflict(self, job)
            operations = type(self)._conflicting_operations_for_episode_rename(self, job)
            if job.state in core.ACTIVE_JOB_STATES or conflict or operations:
                raise ValueError(f"다운로드 또는 파일 작업이 진행 중입니다: {job.title}")
        self._flush_job_history()
        stop = threading.Event()
        def operation(progress):
            if action == "archive":
                return archive_library_items(ids, execute=execute, remove_originals=remove_originals,
                                             cancelled=stop.is_set, progress=progress)
            if action.startswith("delete:"):
                return delete_library_items(ids, action.split(":", 1)[1], execute=execute, plan_token=plan_token)
            if action == "restore":
                return restore_library_trash(manifest, execute=execute)
            if action == "cleanup-folders":
                return cleanup_empty_episode_folders(ids, execute=execute, plan_token=plan_token)
            raise ValueError(f"지원하지 않는 처리: {action}")
        task = _Task(key, operation)
        task.signals.finished.connect(self._library_finished)
        task.signals.progress.connect(lambda event: self.log(f"ZIP 생성: {event.get('archive')}", job_id=event.get("jobId")))
        self.library_tasks[key] = SimpleNamespace(task=task, cancel=stop, ids=ids, action=action, execute=execute)
        for job_id in ids:
            self.library_jobs[job_id] = SimpleNamespace(job=self.selected_job(job_id), execute=True, library=True)
        self.io_thread_pool.start(task)
        self.log(f"선택 작품 처리 시작: {action} · {len(ids)}개 · {'실행' if execute else '미리보기'}")
        return {"operationId": key, "started": True}

    def _show_library_result(self, key, result, error):
        dialog = self.active_library_dialog
        if dialog and dialog.operation_id == key:
            dialog.completed(result, error)

    def _library_finished(self, key, result, error):
        context = self.library_tasks.pop(key, None)
        if context is None:
            return
        for job_id in context.ids:
            self.library_jobs.pop(job_id, None)
            if context.execute and context.action.startswith("delete:"):
                previous = self.jobs.pop(job_id, None)
                if previous:
                    self.jobs_by_work.pop(previous.work_key, None)
                self.dirty_job_ids.discard(job_id)
        compact = {k: v for k, v in result.items() if k != "jobs"}
        compact["jobs"] = [{k: v for k, v in item.items() if k not in {"stamps", "archives"}}
                           | {"archivePaths": [a["path"] for a in item.get("archives", [])[:100]]}
                           for item in result.get("jobs", [])[:100]]
        self.library_results[key] = {"done": True, "result": compact, "error": error}
        while len(self.library_results) > 20:
            self.library_results.pop(next(iter(self.library_results)))
        self._show_library_result(key, result, error)
        summary = {k: v for k, v in compact.items() if k not in {"jobs", "results", "skippedJobs"}}
        self.log(f"선택 작품 처리 완료: {context.action} · {error or json.dumps(summary, ensure_ascii=False)}",
                 "ERROR" if error or result.get("success") is False else "INFO")
        for entry in result.get("results", []):
            for warning in entry.get("cleanupWarnings", []):
                self.log(f"빈 폴더 정리 경고 (파일/ZIP 보존): {warning['path']} — {warning['message']}",
                         "WARNING", entry.get("jobId"))
            if entry.get("error") or entry.get("trashManifest"):
                self.log(entry.get("error") or f"복구 기록: {entry['trashManifest']}",
                         "ERROR" if entry.get("error") else "INFO", entry.get("jobId"))
        if context.execute and context.action.startswith("delete:"):
            self.apply_history_filters()
        QTimer.singleShot(0, self.drain_auto_archives)
        QTimer.singleShot(0, self._maybe_trigger_completion_action)

    def queue_auto_archive(self, job):
        if self.config.get("archiveAfterDownload", False) and not job.metadata_only and not job.simulation and job.provider != "youtube":
            self.pending_auto_archives.add(job.job_id)
            QTimer.singleShot(0, self.drain_auto_archives)

    def drain_auto_archives(self):
        if getattr(self, "exit_requested", False):
            self.pending_auto_archives.clear()
            return
        if not self.pending_auto_archives or self.library_tasks:
            return
        job_id = next(iter(self.pending_auto_archives))
        job = self.selected_job(job_id)
        if job and (type(self)._conflicting_operations_for_episode_rename(self, job) or type(self)._episode_rename_execute_conflict(self, job)):
            QTimer.singleShot(1000, self.drain_auto_archives)
            return
        self.pending_auto_archives.discard(job_id)
        try:
            self.start_library_operation([job_id], "archive", execute=True,
                                         remove_originals=bool(self.config.get("archiveRemoveOriginals", True)))
        except Exception as error:
            self.log(f"자동 ZIP 압축 실패: {error}", "ERROR", job_id)
            QTimer.singleShot(0, self.drain_auto_archives)
