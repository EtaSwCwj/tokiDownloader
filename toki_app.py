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
    load_config,
    open_in_explorer,
    read_log_tail,
    save_config,
)


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
    window.show()
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
    )
    command = [find_node(), *build_downloader_args(job, json_events=False)]
    append_log(f"직접 CLI 실행: {command}", job_id="direct")
    completed = subprocess.run(command, cwd=str(ROOT_DIR), check=False)
    append_log(f"직접 CLI 종료 코드: {completed.returncode}", job_id="direct")
    return completed.returncode


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
    download.add_argument("--direct", action="store_true", help="GUI 없이 직접 실행")

    subparsers.add_parser("stop", help="현재 실행 작업 중지")
    retry = subparsers.add_parser("retry", help="작업 재시도")
    retry.add_argument("--job", help="작업 ID")

    status = subparsers.add_parser("status", help="GUI와 작업 상태 조회")
    status.add_argument("--json", action="store_true", help="JSON으로 출력")

    set_output = subparsers.add_parser("set-output", help="기본 저장 폴더 설정")
    set_output.add_argument("path", help="저장 폴더 경로")

    open_folder = subparsers.add_parser("open-folder", help="저장 폴더 열기")
    open_folder.add_argument("--job", help="작업 ID")

    screenshot = subparsers.add_parser("screenshot", help="실행 중인 GUI 화면을 PNG로 저장")
    screenshot.add_argument("--output", help="PNG 저장 경로")

    logs = subparsers.add_parser("logs", help="파일 로그 출력")
    logs.add_argument("--tail", type=int, default=200, help="마지막 N줄")

    copy_log = subparsers.add_parser("copy-log", help="파일 로그를 클립보드에 복사")
    copy_log.add_argument("--tail", type=int, default=3000, help="마지막 N줄")

    subparsers.add_parser("clear-log", help="GUI 및 파일 로그 지우기")
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
    if command == "screenshot":
        ensure_gui_running()
        requested = str(Path(args.output).expanduser().resolve()) if args.output else ""
        result = control_request({"action": "screenshot", "path": requested})
        print(result["path"])
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
