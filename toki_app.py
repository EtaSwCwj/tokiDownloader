from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication

from toki_core import (
    CONTROL_SERVER_NAME,
    ROOT_DIR,
    DownloadJob,
    append_log,
    build_downloader_args,
    clear_log_file,
    find_node,
    count_jobs,
    delete_job_record,
    delete_job_records,
    load_config,
    load_jobs_page,
    update_job_markers,
    open_in_explorer,
    read_log_tail,
    save_config,
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
    job = DownloadJob(
        job_id="direct",
        url=args.url,
        output_dir=output,
        start=args.start,
        last=args.last,
        show_browser=args.show_browser,
    )
    command = [find_node(), *build_downloader_args(job, json_events=False)]
    append_log(f"직접 CLI 실행: {command}", job_id="direct")
    completed = subprocess.run(command, cwd=str(ROOT_DIR), check=False)
    append_log(f"직접 CLI 종료 코드: {completed.returncode}", job_id="direct")
    return completed.returncode


def run_gui_self_test_probe() -> dict[str, Any]:
    was_running = gui_is_running()
    if not was_running:
        ensure_gui_running()
    screenshot_path = ROOT_DIR / "logs" / "self-test-gui.png"
    try:
        ping = control_request({"action": "ping"})
        status = control_request({"action": "status"})
        screenshot = control_request({"action": "screenshot", "path": str(screenshot_path)})
        if not screenshot_path.is_file() or screenshot_path.stat().st_size <= 0:
            raise ControlError("GUI 자체 점검 화면 캡처 파일이 생성되지 않았습니다.")
        return {
            "detail": "GUI IPC 상태 조회와 화면 캡처 통과",
            "wasRunning": was_running,
            "ping": ping,
            "loadedJobCount": status.get("loadedJobCount", 0),
            "screenshotPath": screenshot.get("path"),
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
    download.add_argument("--output", help="저장 기준 폴더")
    download.add_argument(
        "--show-browser",
        action="store_true",
        help="자동화 Chrome 창을 표시(기본값은 백그라운드 실행)",
    )
    download.add_argument("--direct", action="store_true", help="GUI 없이 직접 실행")

    subparsers.add_parser("stop", help="현재 실행 작업 중지")
    retry = subparsers.add_parser(
        "retry",
        help="선택 작품의 전체 회차를 재검사하고 기존 파일은 건너뛰기",
    )
    retry.add_argument("--job", help="작업 ID")

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
        choices=("completed", "error", "stopped"),
        help="정리할 상태(여러 번 지정 가능)",
    )
    cleanup_records.add_argument("--yes", action="store_true", help="일괄 기록 정리 확인")
    subparsers.add_parser("refresh-list", help="GUI 작품 목록과 썸네일 캐시 새로고침")

    set_output = subparsers.add_parser("set-output", help="기본 저장 폴더 설정")
    set_output.add_argument("path", help="저장 폴더 경로")

    open_folder = subparsers.add_parser("open-folder", help="저장 폴더 열기")
    open_folder.add_argument("--job", help="작업 ID")

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
        if args.direct:
            return run_direct_download(args)
        ensure_gui_running()
        config = load_config()
        result = control_request(
            {
                "action": "enqueue",
                "url": args.url,
                "start": args.start,
                "last": args.last,
                "output": args.output or config.get("outputDir") or str(ROOT_DIR),
                "showBrowser": args.show_browser,
            }
        )
        print(f"작업 추가: {result['job_id']}")
        return 0
    if command == "show":
        ensure_gui_running()
        control_request({"action": "show"})
        return 0
    if command == "stop":
        print_json(control_request({"action": "stop"}))
        return 0
    if command == "retry":
        print_json(control_request({"action": "retry", "jobId": args.job}))
        return 0
    if command == "status":
        result = control_request({"action": "status"})
        if args.json:
            print_json(result)
        else:
            active = result.get("activeJob")
            print(f"GUI: 실행 중 | 대기: {result.get('pendingCount', 0)}")
            if active:
                print(
                    f"현재 작업: {active['job_id']} | {active['state']} | "
                    f"{active['progress']}% | {active['title']}"
                )
            else:
                print("현재 작업: 없음")
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
        state_map = {"completed": "완료", "error": "오류", "stopped": "중지됨"}
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
        print_json({"ok": True, **control_request({"action": "refresh_list"})})
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
