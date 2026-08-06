from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication

from toki_core import (
    CONTROL_SERVER_NAME,
    ROOT_DIR,
    DownloadJob,
    append_log,
    build_job_list_view_state,
    build_downloader_args,
    clear_log_file,
    find_node,
    hydrate_job_metadata,
    job_database_diagnostics,
    keyboard_shortcut_catalog,
    count_jobs,
    count_runs,
    convert_job_images,
    delete_job_record,
    delete_job_records,
    error_category_label,
    load_config,
    load_job_by_id,
    load_jobs_page,
    list_job_episode_images,
    load_run,
    load_runs_page,
    move_job_folder,
    normalize_image_concurrency,
    normalize_retry_backoff,
    normalize_retry_count,
    normalize_scan_request,
    normalize_work_concurrency,
    plan_job_folder_move,
    plan_metadata_rebuild,
    plan_image_conversion,
    update_job_markers,
    open_in_explorer,
    read_log_tail,
    read_run_log,
    rebuild_job_metadata,
    resolve_cover_path,
    retry_backoff_seconds,
    save_config,
    save_jobs,
    settings_snapshot,
    should_auto_retry,
    update_app_settings,
    update_job_note,
    verify_job_files,
)
from toki_selftest import run_self_test


class ControlError(RuntimeError):
    pass


def control_request(request: dict[str, Any], timeout_ms: int = 2500) -> Any:
    socket = QLocalSocket()
    socket.connectToServer(CONTROL_SERVER_NAME)
    if not socket.waitForConnected(timeout_ms):
        raise ControlError("실행 중인 GUI에 연결할 수 없습니다.")
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    socket.write(payload)
    if not socket.waitForBytesWritten(timeout_ms):
        raise ControlError("GUI에 명령을 보내지 못했습니다.")

    received = bytearray()
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if socket.bytesAvailable() or socket.waitForReadyRead(150):
            received.extend(bytes(socket.readAll()))
            if b"\n" in received:
                break
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            break
    if not received:
        raise ControlError("GUI가 응답하지 않았습니다.")
    try:
        response = json.loads(received.decode("utf-8", errors="replace").splitlines()[0])
    except json.JSONDecodeError as error:
        raise ControlError("GUI 응답을 해석할 수 없습니다.") from error
    if not response.get("ok"):
        raise ControlError(str(response.get("error") or "GUI 명령 실패"))
    return response.get("result")


def gui_is_running() -> bool:
    try:
        result = control_request({"action": "ping"}, timeout_ms=350)
        return bool(result and result.get("pong"))
    except ControlError:
        return False


def start_gui_background() -> None:
    python_executable = Path(sys.executable)
    pythonw = python_executable.with_name("pythonw.exe")
    executable = str(pythonw if pythonw.exists() else python_executable)
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [executable, str(Path(__file__).resolve()), "gui"],
        cwd=str(ROOT_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )


def ensure_gui_running(timeout_seconds: float = 12.0) -> None:
    if gui_is_running():
        return
    start_gui_background()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if gui_is_running():
            return
        time.sleep(0.2)
    raise ControlError("GUI를 시작했지만 제어 서버에 연결할 수 없습니다. logs/gui.log를 확인하세요.")


def run_gui() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("tokiDownloader")
    app.setOrganizationName("tokiDownloader")
    app.setFont(QFont("Malgun Gothic", 9))

    def log_unhandled_exception(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
        append_log(f"처리되지 않은 GUI 오류:\n{details}", level="ERROR", job_id="gui")
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = log_unhandled_exception
    if gui_is_running():
        control_request({"action": "show"})
        return 0
    from toki_gui import MainWindow

    window = MainWindow()
    if window.geometry_restored:
        window.show()
    elif window.restore_maximized:
        window.show()
        if window.restore_position is not None:
            window.move(window.restore_position)
        window.showMaximized()
    else:
        window.show()
        if window.restore_position is not None:
            window.move(window.restore_position)
    return app.exec()


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_direct_download(args: argparse.Namespace) -> int:
    config = load_config()
    output = str(Path(args.output or config.get("outputDir") or ROOT_DIR).resolve())
    scan_mode, start, last = normalize_scan_request(args.mode, args.start, args.last)
    job = DownloadJob(
        job_id="direct",
        url=args.url,
        output_dir=output,
        start=start,
        last=last,
        show_browser=args.show_browser,
        scan_mode=scan_mode,
        image_concurrency=normalize_image_concurrency(config.get("imageConcurrency")),
        retry_limit=normalize_retry_count(config.get("retryCount")),
        retry_backoff_seconds=normalize_retry_backoff(
            config.get("retryBackoffSeconds")
        ),
    )
    command = [find_node(), *build_downloader_args(job, json_events=False)]
    for attempt in range(1, job.retry_limit + 2):
        job.attempt_count = attempt
        append_log(
            f"직접 CLI 실행 {attempt}/{job.retry_limit + 1}: {command}",
            job_id="direct",
        )
        completed = subprocess.run(command, cwd=str(ROOT_DIR), check=False)
        append_log(
            f"직접 CLI 종료 코드: {completed.returncode}", job_id="direct"
        )
        if not should_auto_retry(
            exit_code=completed.returncode,
            cancel_requested=False,
            attempt_count=attempt,
            retry_limit=job.retry_limit,
        ):
            return completed.returncode
        delay = retry_backoff_seconds(attempt, job.retry_backoff_seconds)
        append_log(f"직접 CLI 자동 재시도: {delay}초 후", job_id="direct")
        time.sleep(delay)
    return completed.returncode


def run_gui_self_test_probe() -> dict[str, Any]:
    was_running = gui_is_running()
    if not was_running:
        ensure_gui_running()
    screenshot_path = ROOT_DIR / "logs" / "self-test-gui.png"
    try:
        ping = control_request({"action": "ping"})
        status = control_request({"action": "status"})
        list_view_state = status.get("listViewState")
        if not isinstance(list_view_state, dict) or list_view_state.get("state") not in {
            "loading",
            "error",
            "empty",
            "no_results",
            "content",
        }:
            raise ControlError("GUI 상태에 작품 목록 화면 상태가 없습니다.")
        active_jobs = status.get("activeJobs")
        if not isinstance(active_jobs, list):
            raise ControlError("GUI 상태에 다중 실행 작품 목록이 없습니다.")
        if int(status.get("activeCount") or 0) != len(active_jobs):
            raise ControlError("GUI 실행 작품 개수와 목록이 일치하지 않습니다.")
        normalize_work_concurrency(status.get("workConcurrency"))
        normalize_retry_count(status.get("retryCount"))
        normalize_retry_backoff(status.get("retryBackoffSeconds"))
        startup_recovery = status.get("startupRecovery")
        if not isinstance(startup_recovery, dict):
            raise ControlError("GUI 상태에 재시작 복구 결과가 없습니다.")
        window_status = status.get("window")
        if not isinstance(window_status, dict) or not window_status.get("onScreen"):
            raise ControlError("GUI 창이 현재 모니터의 보이는 영역에 없습니다.")
        screen_status = window_status.get("screens")
        if not isinstance(screen_status, list) or not screen_status:
            raise ControlError("GUI 상태에 모니터/DPI 정보가 없습니다.")
        queue_status = control_request({"action": "queue_list"})
        shortcut_status = control_request({"action": "keyboard_shortcuts"})
        if int(shortcut_status.get("count") or 0) < 1:
            raise ControlError("GUI 단축키 카탈로그가 비어 있습니다.")
        screenshot = control_request({"action": "screenshot", "path": str(screenshot_path)})
        if not screenshot_path.is_file() or screenshot_path.stat().st_size <= 0:
            raise ControlError("GUI 자체 점검 화면 캡처 파일이 생성되지 않았습니다.")
        detail_probe: dict[str, Any] = {"skipped": True, "reason": "저장된 작품 없음"}
        jobs = status.get("jobs") or []
        if jobs:
            job_id = str(jobs[0]["job_id"])
            job_info = control_request({"action": "job_info", "jobId": job_id})
            runs = control_request(
                {"action": "list_runs", "jobId": job_id, "limit": 5, "offset": 0}
            )
            shown = control_request({"action": "show_details", "jobId": job_id})
            detail_path = ROOT_DIR / "logs" / "self-test-work-details.png"
            detail_shot = control_request(
                {"action": "screenshot", "path": str(detail_path)}
            )
            run_log_probe: dict[str, Any] = {"skipped": True, "reason": "실행 이력 없음"}
            returned_runs = runs.get("runs") or []
            if returned_runs:
                run_id = str(returned_runs[0]["run_id"])
                run_lines = read_run_log(run_id, 20)
                run_log_shown = control_request(
                    {"action": "show_run_log", "runId": run_id}
                )
                run_log_path = ROOT_DIR / "logs" / "self-test-run-log.png"
                run_log_shot = control_request(
                    {"action": "screenshot", "path": str(run_log_path)}
                )
                run_log_closed = control_request({"action": "close_run_log"})
                if not run_log_path.is_file() or run_log_path.stat().st_size <= 0:
                    raise ControlError("실행 상세 로그 자체 점검 캡처 파일이 생성되지 않았습니다.")
                run_log_probe = {
                    "skipped": False,
                    "runId": run_id,
                    "returnedLines": len(run_lines),
                    "shown": run_log_shown.get("shown"),
                    "screenshotPath": run_log_shot.get("path"),
                    "closed": run_log_closed.get("closed"),
                }
            closed = control_request({"action": "close_details"})
            if not detail_path.is_file() or detail_path.stat().st_size <= 0:
                raise ControlError("작품 상세창 자체 점검 캡처 파일이 생성되지 않았습니다.")
            detail_probe = {
                "skipped": False,
                "jobId": job_id,
                "runCount": job_info.get("runCount", 0),
                "returnedRuns": len(runs.get("runs") or []),
                "shown": shown.get("shown"),
                "screenshotPath": detail_shot.get("path"),
                "closed": closed.get("closed"),
                "runLog": run_log_probe,
            }
        return {
            "detail": "GUI IPC, 작품 상세 이력, 화면 캡처 통과",
            "wasRunning": was_running,
            "ping": ping,
            "loadedJobCount": status.get("loadedJobCount", 0),
            "activeJobCount": len(active_jobs),
            "workConcurrency": status.get("workConcurrency"),
            "startupRecovery": startup_recovery,
            "listViewState": list_view_state,
            "pendingQueueCount": queue_status.get("total", 0),
            "keyboardShortcutCount": shortcut_status.get("count", 0),
            "windowScreenCount": len(screen_status),
            "screenshotPath": screenshot.get("path"),
            "workDetails": detail_probe,
        }
    finally:
        if not was_running and gui_is_running():
            control_request({"action": "quit", "force": False})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and gui_is_running():
                time.sleep(0.1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toki-cli",
        description="tokiDownloader GUI 및 CLI 제어",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("gui", help="GUI 실행 또는 기존 GUI 앞으로 가져오기")
    subparsers.add_parser("show", help="실행 중인 GUI 앞으로 가져오기")

    download = subparsers.add_parser("download", help="다운로드 작업 추가")
    download.add_argument("--url", required=True, help="작품 회차 목록 URL")
    download.add_argument("--start", type=int, help="시작 회차")
    download.add_argument("--last", type=int, help="마지막 회차")
    download.add_argument(
        "--mode",
        choices=("new", "full", "range"),
        default="new",
        help="검사 방식(기본값: 신규 회차만)",
    )
    download.add_argument("--output", help="저장 기준 폴더")
    download.add_argument(
        "--show-browser",
        action="store_true",
        help="자동화 Chrome 창을 표시(기본값은 백그라운드 실행)",
    )
    download.add_argument("--direct", action="store_true", help="GUI 없이 직접 실행")

    stop = subparsers.add_parser("stop", help="현재 실행 작업 중지")
    stop.add_argument("--job", help="현재 실행 중인지 확인할 작업 ID")
    cancel = subparsers.add_parser("cancel", help="작업 ID로 대기 작업 실행 전 취소")
    cancel.add_argument("--job", required=True, help="대기 작업 ID")
    pause = subparsers.add_parser("pause", help="현재 작업의 Node/Chrome 프로세스 트리 일시정지")
    pause.add_argument("--job", required=True, help="현재 실행 작업 ID")
    resume = subparsers.add_parser("resume", help="일시정지한 작업 프로세스 트리 계속")
    resume.add_argument("--job", required=True, help="일시정지 작업 ID")
    queue = subparsers.add_parser("queue", help="대기열 조회와 순서 변경")
    queue_commands = queue.add_subparsers(dest="queue_command", required=True)
    queue_list = queue_commands.add_parser("list", help="현재 대기열 순서 조회")
    queue_list.add_argument("--json", action="store_true", help="JSON으로 출력")
    queue_move = queue_commands.add_parser("move", help="대기 작업 순서 변경")
    queue_move.add_argument("--job", required=True, help="이동할 대기 작업 ID")
    queue_target = queue_move.add_mutually_exclusive_group(required=True)
    queue_target.add_argument("--before", help="이 작업 ID 바로 앞으로 이동")
    queue_target.add_argument("--first", action="store_true", help="대기열 맨 앞으로 이동")
    queue_target.add_argument("--last", action="store_true", help="대기열 맨 뒤로 이동")
    concurrency = subparsers.add_parser("concurrency", help="현재 동시성 설정 조회")
    concurrency.add_argument("--json", action="store_true", help="JSON으로 출력")
    set_concurrency = subparsers.add_parser("set-concurrency", help="동시성 설정 변경")
    set_concurrency.add_argument("--works", type=int, help="동시 실행 작품 수 1~4")
    set_concurrency.add_argument("--images", type=int, help="이미지 동시 다운로드 수 1~16")
    retry_policy = subparsers.add_parser("retry-policy", help="자동 재시도 정책 조회")
    retry_policy.add_argument("--json", action="store_true", help="JSON으로 출력")
    set_retry_policy = subparsers.add_parser(
        "set-retry-policy", help="자동 재시도 횟수와 기본 대기 시간 변경"
    )
    set_retry_policy.add_argument("--count", type=int, help="재시도 횟수 0~5")
    set_retry_policy.add_argument("--backoff", type=int, help="기본 대기 초 1~60")
    retry = subparsers.add_parser(
        "retry",
        help="선택 작품의 전체 회차를 재검사하고 기존 파일은 건너뛰기",
    )
    retry.add_argument("--job", help="작업 ID")
    rescan = subparsers.add_parser("rescan", help="작품을 지정한 방식으로 다시 검사")
    rescan.add_argument("--job", required=True, help="작품 작업 ID")
    rescan.add_argument(
        "--mode", choices=("new", "full", "range"), required=True, help="검사 방식"
    )
    rescan.add_argument("--start", type=int, help="range 시작 회차")
    rescan.add_argument("--last", type=int, help="range 마지막 회차")

    status = subparsers.add_parser("status", help="GUI와 작업 상태 조회")
    status.add_argument("--json", action="store_true", help="JSON으로 출력")

    list_jobs = subparsers.add_parser("list", help="저장된 작품 목록 검색·필터·정렬")
    list_jobs.add_argument("--query", default="", help="제목, 작가, 그룹, 작품 ID 검색")
    list_jobs.add_argument("--status", default="", help="작업 상태 필터")
    list_jobs.add_argument(
        "--sort",
        choices=("updated", "title", "progress"),
        default="updated",
        help="정렬 기준",
    )
    list_jobs.add_argument("--limit", type=int, default=200, help="가져올 작품 수(최대 1000)")
    list_jobs.add_argument("--offset", type=int, default=0, help="건너뛸 작품 수")
    list_jobs.add_argument(
        "--apply-gui",
        action="store_true",
        help="같은 검색·필터·정렬을 실행 중인 GUI 목록에도 적용",
    )
    list_jobs.add_argument("--json", action="store_true", help="JSON으로 출력")

    performance = subparsers.add_parser("performance", help="대규모 목록 성능 진단")
    performance_commands = performance.add_subparsers(
        dest="performance_command", required=True
    )
    performance_audit = performance_commands.add_parser(
        "audit", help="SQLite 목록 인덱스와 쿼리 계획 검사"
    )
    performance_audit.add_argument("--json", action="store_true", help="JSON으로 출력")
    performance_window = performance_audit.add_mutually_exclusive_group()
    performance_window.add_argument(
        "--show-gui", action="store_true", help="GUI 성능 진단창 열기"
    )
    performance_window.add_argument(
        "--close", action="store_true", help="GUI 성능 진단창 닫기"
    )

    list_state = subparsers.add_parser(
        "list-state", help="작품 목록의 빈 화면·로딩·오류 상태 조회 및 GUI 점검"
    )
    list_state.add_argument("--query", default="", help="상태 판정에 사용할 검색어")
    list_state.add_argument("--status", default="", help="상태 판정에 사용할 작업 상태 필터")
    list_state.add_argument(
        "--apply-gui", action="store_true", help="검색 조건 또는 미리보기를 실행 중인 GUI에 적용"
    )
    list_state.add_argument(
        "--preview",
        choices=("auto", "loading", "error", "empty", "no-results"),
        default="auto",
        help="GUI 상태 패널 진단용 미리보기",
    )
    list_state.add_argument("--message", default="", help="오류 미리보기의 진단 문구")
    list_state.add_argument("--json", action="store_true", help="JSON으로 출력")

    shortcuts = subparsers.add_parser("shortcuts", help="키보드 단축키와 대응 CLI 조회")
    shortcuts.add_argument("--json", action="store_true", help="JSON으로 출력")
    shortcut_window = shortcuts.add_mutually_exclusive_group()
    shortcut_window.add_argument(
        "--show-gui", action="store_true", help="GUI 단축키 안내창 열기"
    )
    shortcut_window.add_argument(
        "--close", action="store_true", help="GUI 단축키 안내창 닫기"
    )

    focus = subparsers.add_parser("focus", help="GUI 키보드 포커스와 작품 선택 이동")
    focus.add_argument(
        "--target",
        choices=("url", "search", "list", "log", "next", "previous", "next-section"),
        required=True,
        help="이동할 화면 영역 또는 작품 선택 방향",
    )
    focus.add_argument("--clear", action="store_true", help="URL 또는 검색 입력을 지운 뒤 포커스")
    focus.add_argument("--json", action="store_true", help="JSON으로 출력")

    info = subparsers.add_parser("info", help="작품 메타데이터와 실행 이력 요약 조회")
    info.add_argument("--job", required=True, help="작업 ID")
    info.add_argument("--json", action="store_true", help="JSON으로 출력")

    runs = subparsers.add_parser("runs", help="작품의 실행 이력 페이지 조회")
    runs.add_argument("--job", required=True, help="작업 ID")
    runs.add_argument("--limit", type=int, default=100, help="가져올 실행 수(최대 1000)")
    runs.add_argument("--offset", type=int, default=0, help="건너뛸 실행 수")
    runs.add_argument("--json", action="store_true", help="JSON으로 출력")

    run_info = subparsers.add_parser("run-info", help="실행 1건의 상세 정보 조회")
    run_info.add_argument("--run", required=True, help="실행 ID")
    run_info.add_argument("--json", action="store_true", help="JSON으로 출력")

    run_logs = subparsers.add_parser("run-logs", help="실행 ID로 상세 로그 조회")
    run_logs.add_argument("--run", required=True, help="실행 ID")
    run_logs.add_argument("--tail", type=int, default=500, help="마지막 N줄(최대 10000)")
    run_logs.add_argument("--json", action="store_true", help="JSON으로 출력")

    run_log = subparsers.add_parser("run-log", help="GUI 실행 상세 로그 창 표시")
    run_log_target = run_log.add_mutually_exclusive_group(required=True)
    run_log_target.add_argument("--run", help="실행 ID")
    run_log_target.add_argument("--close", action="store_true", help="열린 실행 로그 창 닫기")

    set_note = subparsers.add_parser("set-note", help="작품 사용자 메모 저장")
    set_note.add_argument("--job", required=True, help="작업 ID")
    set_note.add_argument("--text", required=True, help="저장할 메모(빈 문자열이면 삭제)")

    open_source = subparsers.add_parser("open-source", help="작품 원본 페이지 열기")
    open_source.add_argument("--job", required=True, help="작업 ID")

    open_cover = subparsers.add_parser("open-cover", help="저장된 대표 이미지 원본 열기")
    open_cover.add_argument("--job", required=True, help="작업 ID")

    refresh_metadata = subparsers.add_parser(
        "refresh-metadata",
        help="회차 파일은 건드리지 않고 메타데이터와 대표 이미지 다시 받기",
    )
    refresh_metadata.add_argument("--job", required=True, help="작업 ID")

    details = subparsers.add_parser("details", help="GUI 작품 정보 및 실행 이력 창 표시")
    details_target = details.add_mutually_exclusive_group(required=True)
    details_target.add_argument("--job", help="작업 ID")
    details_target.add_argument("--close", action="store_true", help="열린 상세창 닫기")

    pin = subparsers.add_parser("pin", help="작품 고정 상태 변경")
    pin.add_argument("--job", required=True, help="작업 ID")
    pin_state = pin.add_mutually_exclusive_group(required=True)
    pin_state.add_argument("--on", action="store_true", help="목록 상단에 고정")
    pin_state.add_argument("--off", action="store_true", help="고정 해제")

    tag = subparsers.add_parser("tag", help="작품 색상 태그 변경")
    tag.add_argument("--job", required=True, help="작업 ID")
    tag.add_argument(
        "--color",
        required=True,
        choices=("none", "red", "orange", "yellow", "green", "blue", "purple", "gray"),
        help="태그 색상",
    )

    remove_record = subparsers.add_parser(
        "remove-record",
        help="다운로드 파일은 보존하고 작품 기록만 제거",
    )
    remove_record.add_argument("--job", required=True, help="작업 ID")
    remove_record.add_argument(
        "--yes",
        action="store_true",
        help="기록 제거 확인(다운로드 파일은 삭제하지 않음)",
    )

    cleanup_records = subparsers.add_parser(
        "cleanup-records",
        help="다운로드 파일은 보존하고 선택 상태의 기록만 일괄 정리",
    )
    cleanup_records.add_argument(
        "--status",
        action="append",
        required=True,
        choices=("completed", "error", "authentication", "stopped"),
        help="정리할 상태(여러 번 지정 가능)",
    )
    cleanup_records.add_argument("--yes", action="store_true", help="일괄 기록 정리 확인")
    subparsers.add_parser("refresh-list", help="GUI 작품 목록과 썸네일 캐시 새로고침")

    set_output = subparsers.add_parser("set-output", help="기본 저장 폴더 설정")
    set_output.add_argument("path", help="저장 폴더 경로")

    settings = subparsers.add_parser("settings", help="전체 일반 설정 조회")
    settings.add_argument("--json", action="store_true", help="JSON으로 출력")
    settings.add_argument("--show-gui", action="store_true", help="GUI 설정 창 표시")
    settings.add_argument(
        "--tab",
        choices=("general", "network", "display", "advanced"),
        default="general",
        help="GUI에서 처음 표시할 설정 탭",
    )

    set_settings = subparsers.add_parser("set-settings", help="일반 설정 일괄 변경")
    set_settings.add_argument("--output", help="기본 저장 폴더")
    set_settings.add_argument("--works", type=int, help="동시 실행 작품 수 1~4")
    set_settings.add_argument("--images", type=int, help="이미지 연결 수 1~16")
    set_settings.add_argument("--retry-count", type=int, help="재시도 횟수 0~5")
    set_settings.add_argument("--retry-backoff", type=int, help="기본 대기 초 1~60")
    set_settings.add_argument(
        "--show-browser", choices=("on", "off"), help="브라우저 표시 기본값"
    )
    set_settings.add_argument(
        "--log-visible", choices=("on", "off"), help="GUI 로그 패널 표시"
    )
    set_settings.add_argument("--log-max-mib", type=int, help="로그 파일당 최대 MiB 1~100")
    set_settings.add_argument("--log-backups", type=int, help="보존할 이전 로그 수 1~10")
    set_settings.add_argument(
        "--row-density",
        choices=("compact", "comfortable"),
        help="작품 목록 행 높이와 정보 밀도",
    )
    set_settings.add_argument(
        "--theme", choices=("system", "light", "dark"), help="GUI 색상 테마"
    )
    set_settings.add_argument("--tray", choices=("on", "off"), help="시스템 트레이 사용")
    set_settings.add_argument(
        "--close-to-tray", choices=("on", "off"), help="창 닫기 시 트레이로 숨김"
    )
    set_settings.add_argument(
        "--minimize-to-tray", choices=("on", "off"), help="최소화 시 트레이로 숨김"
    )
    set_settings.add_argument(
        "--notify-complete", choices=("on", "off"), help="작업 완료 알림"
    )
    set_settings.add_argument(
        "--notify-error", choices=("on", "off"), help="작업 오류 알림"
    )
    set_settings.add_argument("--defaults", action="store_true", help="일반 설정 기본값 복원")
    set_settings.add_argument("--json", action="store_true", help="JSON으로 출력")

    tray = subparsers.add_parser("tray", help="GUI 시스템 트레이 제어")
    tray.add_argument(
        "action",
        choices=("status", "show", "hide", "notify"),
        help="트레이 상태 조회, 창 표시/숨김 또는 테스트 알림",
    )
    tray.add_argument("--message", default="tokiDownloader 테스트 알림", help="테스트 알림 내용")

    open_folder = subparsers.add_parser("open-folder", help="저장 폴더 열기")
    open_folder.add_argument("--job", help="작업 ID")

    move_folder = subparsers.add_parser(
        "move-folder",
        help="작품 폴더 이동 계획을 확인하거나 명시적으로 실행",
    )
    move_folder.add_argument("--job", required=True, help="작업 ID")
    move_folder.add_argument("--output", required=True, help="새 저장 루트 폴더")
    move_mode = move_folder.add_mutually_exclusive_group()
    move_mode.add_argument(
        "--dry-run", action="store_true", help="파일을 옮기지 않고 목적지와 충돌만 확인"
    )
    move_mode.add_argument("--execute", action="store_true", help="실제 폴더 이동 실행")
    move_folder.add_argument("--yes", action="store_true", help="실제 이동 확인")
    move_folder.add_argument("--json", action="store_true", help="JSON으로 출력")

    rebuild_metadata = subparsers.add_parser(
        "rebuild-metadata",
        help="사이트 접속 없이 작품 폴더의 metadata.json 재생성 계획 또는 실행",
    )
    rebuild_metadata.add_argument("--job", required=True, help="작업 ID")
    rebuild_mode = rebuild_metadata.add_mutually_exclusive_group()
    rebuild_mode.add_argument(
        "--dry-run", action="store_true", help="파일을 바꾸지 않고 생성 내용을 확인"
    )
    rebuild_mode.add_argument("--execute", action="store_true", help="메타데이터 재생성 실행")
    rebuild_metadata.add_argument("--yes", action="store_true", help="기존 파일 변경 확인")
    rebuild_metadata.add_argument("--json", action="store_true", help="JSON으로 출력")

    verify_files = subparsers.add_parser(
        "verify-files",
        help="작품 폴더의 회차, 누락 파일과 이미지 서명을 읽기 전용 검사",
    )
    verify_files.add_argument("--job", required=True, help="작업 ID")
    verify_files.add_argument(
        "--issue-limit", type=int, default=500, help="JSON에 포함할 문제 항목 수(최대 10000)"
    )
    verify_files.add_argument(
        "--show-gui", action="store_true", help="GUI 별도 프로세스 검사와 결과 창 표시"
    )
    verify_files.add_argument(
        "--ascii-json", action="store_true", help=argparse.SUPPRESS
    )
    verify_files.add_argument("--json", action="store_true", help="JSON으로 출력")

    preview = subparsers.add_parser(
        "preview",
        help="작품 회차의 이미지 목록 조회 또는 GUI 미리보기",
    )
    preview.add_argument("--job", required=True, help="작업 ID")
    preview.add_argument("--episode", type=int, help="회차 번호(생략 시 첫 보유 회차)")
    preview.add_argument("--limit", type=int, default=200, help="가져올 이미지 수(최대 1000)")
    preview.add_argument("--offset", type=int, default=0, help="건너뛸 이미지 수")
    preview.add_argument("--show-gui", action="store_true", help="GUI 이미지 미리보기 창 표시")
    preview.add_argument("--json", action="store_true", help="JSON으로 출력")
    preview.add_argument("--ascii-json", action="store_true", help=argparse.SUPPRESS)

    convert_images = subparsers.add_parser(
        "convert-images",
        help="원본을 보존하고 _converted 폴더에 이미지 형식 변환",
    )
    convert_images.add_argument("--job", required=True, help="작업 ID")
    convert_images.add_argument(
        "--format", required=True, choices=("jpg", "jpeg", "png", "webp"), help="대상 형식"
    )
    convert_images.add_argument("--quality", type=int, default=90, help="JPG/WebP 품질(1~100)")
    convert_mode = convert_images.add_mutually_exclusive_group()
    convert_mode.add_argument("--dry-run", action="store_true", help="변환 대상과 충돌만 확인")
    convert_mode.add_argument("--execute", action="store_true", help="별도 폴더에 실제 변환")
    convert_images.add_argument("--yes", action="store_true", help="대량 새 파일 생성 확인")
    convert_images.add_argument("--show-gui", action="store_true", help="GUI 확인/변환 창 표시")
    convert_images.add_argument("--json", action="store_true", help="JSON으로 출력")
    convert_images.add_argument(
        "--progress-json",
        action="store_true",
        help="진행 이벤트와 최종 결과를 줄 단위 JSON으로 출력",
    )
    convert_images.add_argument("--ascii-json", action="store_true", help=argparse.SUPPRESS)

    cancel_conversion = subparsers.add_parser(
        "cancel-conversion",
        help="GUI에서 실행 중인 이미지 변환 중지",
    )
    cancel_conversion.add_argument("--job", required=True, help="작업 ID")

    copy_link = subparsers.add_parser("copy-link", help="작품 원본 링크 복사")
    copy_link.add_argument("--job", help="작업 ID")
    copy_title = subparsers.add_parser("copy-title", help="작품명 복사")
    copy_title.add_argument("--job", help="작업 ID")
    job_menu = subparsers.add_parser("job-menu", help="선택 작품의 우클릭 메뉴 표시")
    job_menu.add_argument("--job", help="작업 ID")

    screenshot = subparsers.add_parser("screenshot", help="실행 중인 GUI 화면을 PNG로 저장")
    screenshot.add_argument("--output", help="PNG 저장 경로")

    window = subparsers.add_parser("window", help="GUI 창 위치와 크기 조회 또는 설정")
    window.add_argument("--x", type=int, help="창의 화면 X 좌표")
    window.add_argument("--y", type=int, help="창의 화면 Y 좌표")
    window.add_argument("--width", type=int, help="창 너비")
    window.add_argument("--height", type=int, help="창 높이")
    window_state = window.add_mutually_exclusive_group()
    window_state.add_argument("--maximize", action="store_true", help="창 최대화")
    window_state.add_argument("--normal", action="store_true", help="창을 보통 상태로 복원")
    window.add_argument("--screen", help="이름으로 지정한 모니터로 이동")
    window.add_argument("--center", action="store_true", help="대상 모니터 중앙에 배치")
    window.add_argument("--safe", action="store_true", help="현재 창을 보이는 화면 영역 안으로 보정")

    logs = subparsers.add_parser("logs", help="파일 로그 출력")
    logs.add_argument("--tail", type=int, default=200, help="마지막 N줄")

    copy_log = subparsers.add_parser("copy-log", help="파일 로그를 클립보드에 복사")
    copy_log.add_argument("--tail", type=int, default=3000, help="마지막 N줄")

    subparsers.add_parser("clear-log", help="GUI 및 파일 로그 지우기")
    self_test = subparsers.add_parser("self-test", help="로컬 핵심 기능과 GUI 제어 자체 점검")
    self_test.add_argument("--json", action="store_true", help="JSON으로 결과 출력")
    self_test_mode = self_test.add_mutually_exclusive_group()
    self_test_mode.add_argument(
        "--core-only",
        action="store_true",
        help="GUI 시작과 IPC 점검을 제외하고 핵심 검사만 실행",
    )
    self_test_mode.add_argument(
        "--via-gui",
        action="store_true",
        help="실행 중인 GUI의 자체 점검 버튼 경로를 원격 실행",
    )
    self_test.add_argument("--timeout", type=int, default=120, help="GUI 점검 대기 초")
    quit_parser = subparsers.add_parser("quit", help="GUI 종료")
    quit_parser.add_argument("--force", action="store_true", help="실행 작업도 중지하고 종료")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    command = args.command
    if command == "download":
        scan_mode, start, last = normalize_scan_request(args.mode, args.start, args.last)
        if args.direct:
            return run_direct_download(args)
        ensure_gui_running()
        config = load_config()
        result = control_request(
            {
                "action": "enqueue",
                "url": args.url,
                "start": start,
                "last": last,
                "output": args.output or config.get("outputDir") or str(ROOT_DIR),
                "showBrowser": args.show_browser,
                "scanMode": scan_mode,
            }
        )
        print(f"작업 추가: {result['job_id']}")
        return 0
    if command == "show":
        ensure_gui_running()
        control_request({"action": "show"})
        return 0
    if command == "shortcuts":
        if args.show_gui or args.close:
            ensure_gui_running()
            action = "close_shortcut_help" if args.close else "show_shortcut_help"
            result = control_request({"action": action})
            print_json(result)
            return 0
        catalog = keyboard_shortcut_catalog()
        result = {"count": len(catalog), "shortcuts": catalog}
        if args.json:
            print_json(result)
        else:
            for item in catalog:
                print(f"{', '.join(item['keys'])} | {item['label']} | {item['cli']}")
        return 0
    if command == "focus":
        if args.clear and args.target not in {"url", "search"}:
            raise ValueError("--clear는 url 또는 search 대상에만 사용할 수 있습니다.")
        ensure_gui_running()
        result = control_request(
            {"action": "keyboard_focus", "target": args.target, "clear": args.clear}
        )
        if args.json:
            print_json(result)
        else:
            print(
                f"포커스 {result.get('focus')} | 선택 행 {result.get('selectedRow')} | "
                f"작업 {result.get('selectedJobId') or '-'}"
            )
        return 0
    if command == "stop":
        print_json(control_request({"action": "stop", "jobId": args.job}))
        return 0
    if command == "cancel":
        print_json(control_request({"action": "cancel", "jobId": args.job}))
        return 0
    if command == "pause":
        print_json(control_request({"action": "pause", "jobId": args.job}))
        return 0
    if command == "resume":
        print_json(control_request({"action": "resume", "jobId": args.job}))
        return 0
    if command == "queue":
        ensure_gui_running()
        if args.queue_command == "list":
            result = control_request({"action": "queue_list"})
            if args.json:
                print_json(result)
            else:
                for job in result["jobs"]:
                    print(f"{job['queue_position']} | {job['job_id']} | {job['title']}")
                print(f"대기 {result['total']}개")
            return 0
        position = "first" if args.first else "last" if args.last else ""
        result = control_request(
            {
                "action": "queue_move",
                "jobId": args.job,
                "beforeJobId": args.before or "",
                "position": position,
            }
        )
        print_json(result)
        return 0
    if command == "concurrency":
        if gui_is_running():
            status = control_request({"action": "status"})
            result = {
                "workConcurrency": status["workConcurrency"],
                "imageConcurrency": status["imageConcurrency"],
            }
        else:
            config = load_config()
            result = {
                "workConcurrency": normalize_work_concurrency(
                    config.get("workConcurrency")
                ),
                "imageConcurrency": normalize_image_concurrency(
                    config.get("imageConcurrency")
                ),
            }
        if args.json:
            print_json(result)
        else:
            print(f"작품 동시 다운로드: {result['workConcurrency']}")
            print(f"이미지 동시 다운로드: {result['imageConcurrency']}")
        return 0
    if command == "set-concurrency":
        if args.works is None and args.images is None:
            raise ValueError("--works 또는 --images 중 하나 이상을 지정해주세요.")
        work_concurrency = (
            normalize_work_concurrency(args.works) if args.works is not None else None
        )
        image_concurrency = (
            normalize_image_concurrency(args.images) if args.images is not None else None
        )
        if gui_is_running():
            result = control_request(
                {
                    "action": "set_concurrency",
                    "works": work_concurrency,
                    "images": image_concurrency,
                }
            )
        else:
            config = load_config()
            if work_concurrency is not None:
                config["workConcurrency"] = work_concurrency
            if image_concurrency is not None:
                config["imageConcurrency"] = image_concurrency
            save_config(config)
            result = {
                "workConcurrency": normalize_work_concurrency(
                    config.get("workConcurrency")
                ),
                "imageConcurrency": normalize_image_concurrency(
                    config.get("imageConcurrency")
                ),
            }
        print_json(result)
        return 0
    if command == "retry-policy":
        if gui_is_running():
            status = control_request({"action": "status"})
            result = {
                "retryCount": status["retryCount"],
                "retryBackoffSeconds": status["retryBackoffSeconds"],
            }
        else:
            config = load_config()
            result = {
                "retryCount": normalize_retry_count(config.get("retryCount")),
                "retryBackoffSeconds": normalize_retry_backoff(
                    config.get("retryBackoffSeconds")
                ),
            }
        if args.json:
            print_json(result)
        else:
            print(f"자동 재시도: {result['retryCount']}회")
            print(f"기본 대기: {result['retryBackoffSeconds']}초 (이후 2배씩 증가)")
        return 0
    if command == "set-retry-policy":
        if args.count is None and args.backoff is None:
            raise ValueError("--count 또는 --backoff 중 하나 이상을 지정해주세요.")
        retry_count = (
            normalize_retry_count(args.count) if args.count is not None else None
        )
        backoff = (
            normalize_retry_backoff(args.backoff) if args.backoff is not None else None
        )
        if gui_is_running():
            result = control_request(
                {
                    "action": "set_retry_policy",
                    "retryCount": retry_count,
                    "backoffSeconds": backoff,
                }
            )
        else:
            config = load_config()
            if retry_count is not None:
                config["retryCount"] = retry_count
            if backoff is not None:
                config["retryBackoffSeconds"] = backoff
            save_config(config)
            result = {
                "retryCount": normalize_retry_count(config.get("retryCount")),
                "retryBackoffSeconds": normalize_retry_backoff(
                    config.get("retryBackoffSeconds")
                ),
            }
        print_json(result)
        return 0
    if command == "retry":
        print_json(control_request({"action": "retry", "jobId": args.job}))
        return 0
    if command == "rescan":
        print_json(
            control_request(
                {
                    "action": "rescan",
                    "jobId": args.job,
                    "mode": args.mode,
                    "start": args.start,
                    "last": args.last,
                }
            )
        )
        return 0
    if command == "performance":
        if args.close:
            ensure_gui_running()
            result = control_request({"action": "close_performance_diagnostics"})
        elif args.show_gui:
            ensure_gui_running()
            result = control_request({"action": "show_performance_diagnostics"})
        else:
            result = job_database_diagnostics()
        if args.json or args.show_gui or args.close:
            print_json(result)
        else:
            queries = list(result.get("queries") or [])
            passed = sum(1 for query in queries if query.get("ok"))
            print(
                f"작품 {int(result.get('jobCount') or 0):,}개 | "
                f"실행 이력 {int(result.get('runCount') or 0):,}개 | "
                f"쿼리 계획 {passed}/{len(queries)} 통과 | "
                f"{float(result.get('elapsedMs') or 0):.1f}ms"
            )
        report = result.get("report") if isinstance(result, dict) else None
        effective = report if isinstance(report, dict) else result
        return 0 if bool(effective.get("ok", args.close)) else 2
    if command == "status":
        result = control_request({"action": "status"})
        if args.json:
            print_json(result)
        else:
            active_jobs = result.get("activeJobs") or []
            print(
                f"GUI: 실행 중 | 실행: {len(active_jobs)} | "
                f"대기: {result.get('pendingCount', 0)}"
            )
            if active_jobs:
                for active in active_jobs:
                    print(
                        f"현재 작업: {active['job_id']} | {active['state']} | "
                        f"{active['progress']}% | {active['title']}"
                    )
            else:
                print("현재 작업: 없음")
            recovery = result.get("startupRecovery") or {}
            print(
                f"시작 복구: 작품 {recovery.get('jobCount', 0)} | "
                f"실행 이력 {recovery.get('runCount', 0)}"
            )
            print(f"저장 폴더: {result.get('outputDir')}")
            print(f"로그: {result.get('logPath')}")
        return 0
    if command == "list":
        request = {
            "action": "list_jobs",
            "query": args.query,
            "status": args.status,
            "sort": args.sort,
            "limit": args.limit,
            "offset": args.offset,
        }
        if args.apply_gui:
            ensure_gui_running()
            request["action"] = "set_list_filter"
            result = control_request(request)
        elif gui_is_running():
            result = control_request(request)
        else:
            jobs = load_jobs_page(
                limit=args.limit,
                offset=args.offset,
                query=args.query,
                state=args.status,
                sort=args.sort,
            )
            result = {
                "ok": True,
                "total": count_jobs(args.query, args.status),
                "limit": max(1, min(1000, args.limit)),
                "offset": max(0, args.offset),
                "query": args.query,
                "status": args.status,
                "sort": args.sort,
                "jobs": [job.to_dict() for job in jobs],
            }
        if args.json:
            print_json(result)
        else:
            for job in result["jobs"]:
                print(f"{job['job_id']} | {job['state']} | {job['title']}")
            print(f"표시 {len(result['jobs'])} / 전체 {result['total']}")
        return 0
    if command == "info":
        if gui_is_running():
            result = control_request({"action": "job_info", "jobId": args.job})
        else:
            job = load_job_by_id(args.job)
            if job is None:
                raise ControlError(f"작업 기록을 찾을 수 없습니다: {args.job}")
            if hydrate_job_metadata(job):
                save_jobs([job])
            result = {"job": job.to_dict(), "runCount": count_runs(job.work_key)}
        if args.json:
            print_json(result)
        else:
            job_data = result["job"]
            print(f"작품: {job_data['title']}")
            print(f"작업 ID: {job_data['job_id']} | 작품 키: {job_data['work_key']}")
            print(f"상태: {job_data['state']} | 실행 이력: {result['runCount']}건")
            print(f"작가: {job_data.get('author') or '-'} | 그룹: {job_data.get('group') or '-'}")
            print(f"저장 폴더: {job_data.get('output_path') or job_data['output_dir']}")
            print(f"메모: {job_data.get('user_note') or '-'}")
        return 0
    if command == "list-state":
        if not args.apply_gui and (args.preview != "auto" or args.message):
            raise ValueError("--preview와 --message는 --apply-gui와 함께 사용해야 합니다.")
        if args.apply_gui:
            ensure_gui_running()
            if args.preview == "auto":
                control_request(
                    {
                        "action": "set_list_filter",
                        "query": args.query,
                        "status": args.status,
                        "sort": "updated",
                    }
                )
                result = control_request({"action": "list_view_state"})
            else:
                result = control_request(
                    {
                        "action": "preview_list_view_state",
                        "state": args.preview,
                        "message": args.message,
                    }
                )
        else:
            total = count_jobs()
            filtered = count_jobs(args.query, args.status)
            result = build_job_list_view_state(
                total_count=total,
                filtered_count=filtered,
                query=args.query,
                state=args.status,
            )
        if args.json:
            print_json(result)
        else:
            print(f"{result['state']} | {result['title'] or '작업 목록'}")
            if result.get("message"):
                print(result["message"])
        return 0
    if command == "runs":
        if gui_is_running():
            result = control_request(
                {
                    "action": "list_runs",
                    "jobId": args.job,
                    "limit": args.limit,
                    "offset": args.offset,
                }
            )
        else:
            job = load_job_by_id(args.job)
            if job is None:
                raise ControlError(f"작업 기록을 찾을 수 없습니다: {args.job}")
            limit = max(1, min(1000, args.limit))
            offset = max(0, args.offset)
            result = {
                "jobId": job.job_id,
                "workKey": job.work_key,
                "total": count_runs(job.work_key),
                "limit": limit,
                "offset": offset,
                "runs": [run.to_dict() for run in load_runs_page(job.work_key, limit, offset)],
            }
        if args.json:
            print_json(result)
        else:
            for run in result["runs"]:
                requested = f"{run.get('requested_start') or '처음'}~{run.get('requested_last') or '끝'}"
                print(
                    f"{run['run_id']} | {run['state']} | {run['progress']}% | "
                    f"시도 {run.get('attempt_count', 0)}/{run.get('retry_limit', 0) + 1} | "
                    f"범위 {requested} | {run['created_at']}"
                )
            print(f"표시 {len(result['runs'])} / 전체 {result['total']}")
        return 0
    if command == "run-info":
        run = load_run(args.run)
        if run is None:
            raise ControlError(f"실행 기록을 찾을 수 없습니다: {args.run}")
        result = run.to_dict()
        if args.json:
            print_json(result)
        else:
            print(f"실행 ID: {run.run_id} | 상태: {run.state} | 진행률: {run.progress}%")
            print(f"작품 키: {run.work_key} | PID: {run.process_pid or '-'}")
            print(
                f"시도: {run.attempt_count}/{run.retry_limit + 1} | "
                f"기본 백오프: {run.retry_backoff_seconds}초"
            )
            print(
                f"발견/선택/처리: {run.discovered_episodes}/"
                f"{run.selected_episodes}/{run.processed_episodes}"
            )
            print(f"시작: {run.started_at or '-'} | 종료: {run.finished_at or '-'}")
            if run.error:
                print(
                    f"오류 분류: {error_category_label(run.error_category)} | "
                    f"자동 재시도 가능: "
                    f"{'예' if run.retryable_error is not False else '아니요'}"
                )
                print(f"오류: {run.error}")
        return 0
    if command == "run-logs":
        run = load_run(args.run)
        if run is None:
            raise ControlError(f"실행 기록을 찾을 수 없습니다: {args.run}")
        clean_tail = max(1, min(10000, args.tail))
        lines = read_run_log(run.run_id, clean_tail)
        result = {
            "runId": run.run_id,
            "tail": clean_tail,
            "returnedLines": len(lines),
            "lines": lines,
        }
        if args.json:
            print_json(result)
        else:
            for line in lines:
                print(line)
            if not lines:
                print(f"실행 {run.run_id}의 보존된 로그가 없습니다.")
        return 0
    if command == "run-log":
        ensure_gui_running()
        action = "close_run_log" if args.close else "show_run_log"
        print_json(control_request({"action": action, "runId": args.run}))
        return 0
    if command == "set-note":
        if gui_is_running():
            result = control_request(
                {"action": "set_note", "jobId": args.job, "text": args.text}
            )
        else:
            result = update_job_note(args.job, args.text).to_dict()
        print_json({"ok": True, "job": result})
        return 0
    if command == "open-source":
        if gui_is_running():
            result = control_request({"action": "open_source", "jobId": args.job})
            print(result["opened"])
        else:
            job = load_job_by_id(args.job)
            if job is None:
                raise ControlError(f"작업 기록을 찾을 수 없습니다: {args.job}")
            if not webbrowser.open(job.url):
                raise ControlError("기본 브라우저에서 작품 페이지를 열지 못했습니다.")
            print(job.url)
        return 0
    if command == "open-cover":
        if gui_is_running():
            result = control_request({"action": "open_cover", "jobId": args.job})
            print(result["opened"])
        else:
            job = load_job_by_id(args.job)
            if job is None:
                raise ControlError(f"작업 기록을 찾을 수 없습니다: {args.job}")
            cover_path = resolve_cover_path(job)
            open_in_explorer(cover_path)
            print(cover_path)
        return 0
    if command == "refresh-metadata":
        ensure_gui_running()
        result = control_request({"action": "refresh_metadata", "jobId": args.job})
        print_json({"ok": True, "job": result})
        return 0
    if command == "details":
        ensure_gui_running()
        action = "close_details" if args.close else "show_details"
        print_json(control_request({"action": action, "jobId": args.job}))
        return 0
    if command == "pin":
        if gui_is_running():
            result = control_request(
                {"action": "pin_job", "jobId": args.job, "pinned": bool(args.on)}
            )
        else:
            result = update_job_markers(args.job, pinned=bool(args.on)).to_dict()
        print_json({"ok": True, "job": result})
        return 0
    if command == "tag":
        if gui_is_running():
            result = control_request(
                {"action": "tag_job", "jobId": args.job, "color": args.color}
            )
        else:
            result = update_job_markers(args.job, tag_color=args.color).to_dict()
        print_json({"ok": True, "job": result})
        return 0
    if command == "remove-record":
        if not args.yes:
            raise ControlError(
                "기록 제거에는 --yes가 필요합니다. 다운로드 파일은 삭제되지 않습니다."
            )
        if gui_is_running():
            result = control_request({"action": "remove_record", "jobId": args.job})
        else:
            removed = delete_job_record(args.job)
            result = {
                "removed": True,
                "jobId": removed.job_id,
                "workKey": removed.work_key,
                "outputPath": removed.output_path,
                "filesDeleted": False,
            }
        print_json({"ok": True, **result})
        return 0
    if command == "cleanup-records":
        if not args.yes:
            raise ControlError("일괄 기록 정리에는 --yes가 필요합니다. 파일은 삭제되지 않습니다.")
        state_map = {
            "completed": "완료",
            "error": "오류",
            "authentication": "인증 필요",
            "stopped": "중지됨",
        }
        states = [state_map[state] for state in args.status]
        if gui_is_running():
            result = control_request({"action": "cleanup_records", "states": states})
        else:
            removed = delete_job_records(states)
            result = {
                "removedCount": len(removed),
                "jobIds": [job.job_id for job in removed],
                "filesDeleted": False,
            }
        print_json({"ok": True, **result})
        return 0
    if command == "refresh-list":
        ensure_gui_running()
        result = control_request({"action": "refresh_list"})
        refreshed = bool(result.get("refreshed", False))
        print_json({"ok": refreshed, **result})
        return 0 if refreshed else 2
    if command == "move-folder":
        execute = bool(args.execute)
        if execute and not args.yes:
            raise ControlError("실제 작품 폴더 이동에는 --execute --yes가 모두 필요합니다.")
        if gui_is_running():
            result = control_request(
                {
                    "action": "move_folder",
                    "jobId": args.job,
                    "output": args.output,
                    "execute": execute,
                },
                timeout_ms=30000 if execute else 2500,
            )
        else:
            result = (
                move_job_folder(args.job, args.output)
                if execute
                else plan_job_folder_move(args.job, args.output)
            )
        if args.json:
            print_json({"ok": True, **result})
        else:
            print(f"원본: {result['source']}")
            print(f"목적지: {result['destination']}")
            print(
                "결과: "
                + (
                    "이동 완료"
                    if result.get("moved")
                    else "같은 경로"
                    if result.get("samePath")
                    else "목적지 충돌"
                    if result.get("conflict")
                    else "이동 가능(dry-run)"
                )
            )
        return 0
    if command == "rebuild-metadata":
        execute = bool(args.execute)
        if execute and not args.yes:
            raise ControlError("실제 메타데이터 재생성에는 --execute --yes가 모두 필요합니다.")
        if gui_is_running():
            result = control_request(
                {
                    "action": "rebuild_metadata",
                    "jobId": args.job,
                    "execute": execute,
                }
            )
        else:
            result = (
                rebuild_job_metadata(args.job)
                if execute
                else plan_metadata_rebuild(args.job)
            )
        if args.json:
            print_json({"ok": True, **result})
        else:
            print(f"메타데이터: {result['metadataPath']}")
            print(f"백업: {result['backupPath']}")
            print(
                "결과: 재생성 완료"
                if result.get("executed")
                else "결과: 생성 가능(dry-run)"
            )
        return 0
    if command == "verify-files":
        if args.show_gui:
            ensure_gui_running()
            print_json(
                control_request({"action": "verify_files", "jobId": args.job})
            )
            return 0
        result = verify_job_files(args.job, args.issue_limit)
        if args.json:
            payload = {"ok": True, **result}
            if args.ascii_json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print_json(payload)
        else:
            summary = result["summary"]
            print(f"작품: {result['title']}")
            print(f"폴더: {result['outputPath']}")
            print(
                f"회차 {summary['episodeFolders']} · 이미지 {summary['images']} · "
                f"문제 {summary['issueCount']} · {result['durationMs']}ms"
            )
            for issue in result["issues"]:
                target = f" ({issue['path']})" if issue["path"] else ""
                print(f"- {issue['kind']}: {issue['detail']}{target}")
            if summary["issuesTruncated"]:
                print("- 나머지 문제는 --issue-limit 값을 늘려 확인하세요.")
        return 0 if result["healthy"] else 2
    if command == "preview":
        if args.show_gui:
            ensure_gui_running()
            print_json(
                control_request(
                    {
                        "action": "preview_images",
                        "jobId": args.job,
                        "episode": args.episode,
                    }
                )
            )
            return 0
        result = list_job_episode_images(
            args.job,
            args.episode,
            limit=args.limit,
            offset=args.offset,
        )
        if args.json:
            payload = {"ok": True, **result}
            if args.ascii_json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print_json(payload)
        else:
            print(f"작품: {result['title']} | 회차: {result['episode']}")
            print(f"이미지 {len(result['images'])} / 전체 {result['total']}")
            for image in result["images"]:
                print(f"{image['index']}: {image['name']} ({image['size']} bytes)")
        return 0
    if command == "convert-images":
        if args.show_gui:
            ensure_gui_running()
            print_json(
                control_request(
                    {
                        "action": "convert_images",
                        "jobId": args.job,
                        "format": args.format,
                        "quality": args.quality,
                    }
                )
            )
            return 0
        execute = bool(args.execute)
        if execute and not args.yes:
            raise ControlError("실제 이미지 변환에는 --execute --yes가 모두 필요합니다.")
        progress_callback = None
        if args.progress_json:
            def emit_progress(event: dict[str, Any]) -> None:
                print(
                    json.dumps(
                        {"event": "progress", **event}, ensure_ascii=True
                    ),
                    flush=True,
                )

            progress_callback = emit_progress
        result = (
            convert_job_images(
                args.job,
                args.format,
                quality=args.quality,
                progress_callback=progress_callback,
            )
            if execute
            else plan_image_conversion(args.job, args.format, quality=args.quality)
        )
        if args.progress_json:
            print(
                json.dumps(
                    {"event": "result", "result": {"ok": bool(result.get("success", True)), **result}},
                    ensure_ascii=True,
                ),
                flush=True,
            )
        elif args.json:
            payload = {"ok": bool(result.get("success", True)), **result}
            if args.ascii_json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print_json(payload)
        else:
            print(f"대상: {result['targetRoot']}")
            print(
                f"원본 {result['sourceCount']} · 기존 결과 {result['existingTargetCount']} · "
                f"변환 예정 {result['pendingCount']}"
            )
            if result.get("executed"):
                print(
                    f"완료 {result['convertedCount']} · 건너뜀 "
                    f"{result['skippedExistingCount']} · 실패 {result['failedCount']}"
                )
        if result.get("cancelled"):
            return 3
        return 0 if result.get("success", True) else 2
    if command == "cancel-conversion":
        ensure_gui_running()
        result = control_request(
            {"action": "cancel_image_conversion", "jobId": args.job}
        )
        print_json(result)
        return 0 if result.get("cancelled") else 2
    if command == "settings":
        if args.show_gui:
            ensure_gui_running()
            result = control_request({"action": "show_settings", "tab": args.tab})
            print_json(result)
            return 0
        result = (
            control_request({"action": "settings"})
            if gui_is_running()
            else settings_snapshot()
        )
        if args.json:
            print_json(result)
        else:
            print(f"저장 폴더: {result['outputDir']}")
            print(
                f"동시 작업: 작품 {result['workConcurrency']} · "
                f"이미지 {result['imageConcurrency']}"
            )
            print(
                f"자동 재시도: {result['retryCount']}회 · "
                f"기본 대기 {result['retryBackoffSeconds']}초"
            )
            print(
                f"브라우저 표시: {'켜짐' if result['showBrowser'] else '꺼짐'} · "
                f"로그 패널: {'표시' if result['logVisible'] else '숨김'}"
            )
            print(
                f"로그 보존: 파일당 {result['logMaxMiB']} MiB · "
                f"백업 {result['logBackupCount']}개"
            )
        return 0
    if command == "set-settings":
        mapping = {
            "outputDir": args.output,
            "workConcurrency": args.works,
            "imageConcurrency": args.images,
            "retryCount": args.retry_count,
            "retryBackoffSeconds": args.retry_backoff,
            "logMaxMiB": args.log_max_mib,
            "logBackupCount": args.log_backups,
            "rowDensity": args.row_density,
            "theme": args.theme,
        }
        updates = {key: value for key, value in mapping.items() if value is not None}
        if args.show_browser is not None:
            updates["showBrowser"] = args.show_browser == "on"
        if args.log_visible is not None:
            updates["logVisible"] = args.log_visible == "on"
        for argument, key in (
            (args.tray, "trayEnabled"),
            (args.close_to_tray, "closeToTray"),
            (args.minimize_to_tray, "minimizeToTray"),
            (args.notify_complete, "notifyOnComplete"),
            (args.notify_error, "notifyOnError"),
        ):
            if argument is not None:
                updates[key] = argument == "on"
        if not updates and not args.defaults:
            raise ControlError("변경할 설정 또는 --defaults를 지정해주세요.")
        if gui_is_running():
            result = control_request(
                {"action": "set_settings", "updates": updates, "reset": args.defaults}
            )
        else:
            result = update_app_settings(updates, reset=args.defaults)
        if args.json:
            print_json(result)
        else:
            print(f"설정 저장 완료: {result['outputDir']}")
        return 0
    if command == "tray":
        ensure_gui_running()
        result = control_request(
            {"action": "tray", "command": args.action, "message": args.message}
        )
        print_json(result)
        return 0
    if command == "set-output":
        resolved = str(Path(args.path).expanduser().resolve())
        Path(resolved).mkdir(parents=True, exist_ok=True)
        if gui_is_running():
            result = control_request({"action": "set_output", "path": resolved})
        else:
            config = load_config()
            config["outputDir"] = resolved
            save_config(config)
            result = {"outputDir": resolved}
        print_json(result)
        return 0
    if command == "open-folder":
        if gui_is_running():
            print_json(control_request({"action": "open_folder", "jobId": args.job}))
        else:
            target = load_config().get("outputDir") or str(ROOT_DIR)
            open_in_explorer(target)
            print(target)
        return 0
    if command == "copy-link":
        print_json(control_request({"action": "copy_link", "jobId": args.job}))
        return 0
    if command == "copy-title":
        print_json(control_request({"action": "copy_title", "jobId": args.job}))
        return 0
    if command == "job-menu":
        print_json(control_request({"action": "show_job_menu", "jobId": args.job}))
        return 0
    if command == "screenshot":
        ensure_gui_running()
        requested = str(Path(args.output).expanduser().resolve()) if args.output else ""
        result = control_request({"action": "screenshot", "path": requested})
        print(result["path"])
        return 0
    if command == "window":
        ensure_gui_running()
        maximized = True if args.maximize else False if args.normal else None
        result = control_request(
            {
                "action": "window",
                "x": args.x,
                "y": args.y,
                "width": args.width,
                "height": args.height,
                "maximized": maximized,
                "screenName": args.screen or "",
                "center": args.center,
                "safe": args.safe,
            }
        )
        print_json(result)
        return 0
    if command == "logs":
        for line in read_log_tail(args.tail):
            print(line)
        return 0
    if command == "copy-log":
        content = "\n".join(read_log_tail(args.tail))
        if os.name != "nt":
            raise ControlError("로그 클립보드 복사는 현재 Windows에서만 지원합니다.")
        completed = subprocess.run(
            ["clip.exe"],
            input=content,
            text=True,
            encoding="utf-16le",
            check=False,
        )
        if completed.returncode != 0:
            raise ControlError("로그를 클립보드에 복사하지 못했습니다.")
        print(f"로그 {len(content.splitlines())}줄을 복사했습니다.")
        return 0
    if command == "clear-log":
        if gui_is_running():
            print_json(control_request({"action": "clear_log"}))
        else:
            clear_log_file()
            print("로그를 지웠습니다.")
        return 0
    if command == "self-test":
        if args.via_gui:
            ensure_gui_running()
            control_request({"action": "self_test"})
            deadline = time.monotonic() + max(10, args.timeout)
            result = None
            while time.monotonic() < deadline:
                status = control_request({"action": "status"})
                if not status.get("selfTestRunning") and status.get("lastSelfTest"):
                    result = status["lastSelfTest"]
                    break
                time.sleep(0.2)
            if result is None:
                raise ControlError("GUI 자체 점검이 제한 시간 안에 끝나지 않았습니다.")
        else:
            result = run_self_test(None if args.core_only else run_gui_self_test_probe)
        append_log(
            f"자체 점검: {result['summary']['passed']}/{result['summary']['total']} 통과",
            level="INFO" if result["ok"] else "ERROR",
            job_id="self-test",
        )
        if args.json:
            print_json(result)
        else:
            for check in result.get("checks", []):
                marker = "PASS" if check["ok"] else "FAIL"
                print(f"[{marker}] {check['name']}: {check['detail']}")
            summary = result.get("summary") or {}
            print(
                f"결과: {summary.get('passed', 0)}/{summary.get('total', 0)} 통과"
            )
            print(f"보고서: {result['reportPath']}")
        return 0 if result["ok"] else 1
    if command == "quit":
        print_json(control_request({"action": "quit", "force": args.force}))
        return 0
    raise ControlError("명령을 지정해주세요. --help에서 사용법을 확인할 수 있습니다.")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in (None, "gui"):
        return run_gui()
    QCoreApplication.instance() or QCoreApplication([sys.argv[0]])
    try:
        return run_cli(args)
    except (ControlError, ValueError, RuntimeError, OSError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
