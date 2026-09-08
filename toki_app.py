from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QApplication

from hitomi_provider import (
    HitomiReferenceError,
    evaluate_hitomi_metadata_outcome,
    fetch_hitomi_metadata,
    evaluate_hitomi_excluded_tags,
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
    plan_hitomi_image_filenames,
    plan_hitomi_image_sources,
    plan_hitomi_metadata_files,
    plan_hitomi_server,
    select_hitomi_display_title,
    validate_hitomi_metadata_cookie_destination,
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
    YouTubePolicyError,
    apply_youtube_upload_date_mtime,
    plan_youtube_format,
    plan_youtube_upload_date_mtime,
    preview_youtube_filename,
    youtube_format_policy_snapshot,
    youtube_metadata_policy_snapshot,
    youtube_collection_policy_snapshot,
    youtube_chapter_policy_snapshot,
    youtube_mtime_policy_snapshot,
)
from toki_core import (
    APP_DISPLAY_NAME,
    APP_ICON_PATH,
    APP_ORGANIZATION_DOMAIN,
    APP_ORGANIZATION_NAME,
    APP_VERSION,
    COOKIE_PROVIDERS,
    archive_viewer_policy_snapshot,
    application_identity_snapshot,
    apply_windows_app_user_model_id,
    available_ui_languages,
    apply_config_migrations,
    apply_database_migrations,
    CONTROL_SERVER_NAME,
    ROOT_DIR,
    SETTING_KEYS,
    DownloadJob,
    append_log,
    assign_job_to_collection,
    build_job_list_view_state,
    build_downloader_args,
    build_youtube_worker_args,
    clear_proxy_credentials,
    browser_launch_policy,
    clear_log_file,
    cleanup_thumbnail_cache,
    cleanup_run_history,
    config_schema_status,
    create_work_collection,
    detect_download_provider,
    find_node,
    hydrate_job_metadata,
    image_processing_policy_snapshot,
    job_database_diagnostics,
    keyboard_shortcut_catalog,
    count_jobs,
    count_runs,
    copy_text_to_clipboard,
    completion_action_plan,
    cookie_import_plan,
    credential_store_status,
    clear_provider_cookies,
    convert_job_images,
    delete_job_record,
    delete_job_records,
    dependency_diagnostics,
    database_schema_status,
    downloader_event_update_policy,
    downloader_environment_overrides,
    embedded_browser_capabilities,
    embedded_browser_navigation_plan,
    error_category_label,
    export_diagnostics,
    export_app_settings,
    export_jobs_snapshot,
    export_provider_cookies,
    export_shortcut_settings,
    find_duplicate_works,
    find_duplicate_images,
    folder_name_template_preview,
    generate_job_pdfs,
    load_config,
    import_app_settings,
    import_jobs_snapshot,
    import_provider_cookies,
    import_shortcut_settings,
    inspect_local_archive,
    inspect_clipboard_url,
    load_job_by_id,
    load_job_by_work_key,
    load_jobs_page,
    log_retention_status,
    list_job_episode_images,
    list_performance_policy_snapshot,
    local_api_policy_snapshot,
    memory_usage_snapshot,
    list_work_collections,
    load_run,
    load_runs_page,
    move_job_folder,
    network_policy_snapshot,
    notification_event_plan,
    notification_settings_snapshot,
    normalize_image_concurrency,
    normalize_embedded_browser_url,
    normalize_retry_backoff,
    normalize_retry_count,
    normalize_scan_request,
    normalize_work_concurrency,
    plan_episode_folder_rename,
    plan_job_folder_move,
    plan_metadata_rebuild,
    public_ip_check_plan,
    lookup_public_ip,
    provider_cookie_status,
    provider_cookie_policy,
    provider_cookie_request_header,
    pdf_generation_policy_snapshot,
    proxy_credential_status,
    plan_image_conversion,
    plan_job_pdf_generation,
    parse_shortcut_keys_text,
    update_job_markers,
    open_in_explorer,
    open_archive_with_viewer,
    persistence_policy_snapshot,
    read_log_tail,
    read_run_log,
    rebuild_job_metadata,
    rename_episode_folders,
    resolve_cover_path,
    resource_budget,
    reset_app_settings,
    recover_interrupted_jobs,
    rename_work_collection,
    retry_backoff_seconds,
    run_job_database_benchmark,
    run_stability_recovery_test,
    save_config,
    save_jobs,
    settings_snapshot,
    shortcut_import_plan,
    shortcut_settings_snapshot,
    sleep_prevention_policy_snapshot,
    store_proxy_credentials,
    should_auto_retry,
    update_app_settings,
    update_job_note,
    verify_job_files,
)
from toki_selftest import run_self_test


class ControlError(RuntimeError):
    pass


class ControlTimeoutError(ControlError):
    def __init__(
        self,
        message: str,
        *,
        operation_may_continue: bool = False,
        status_command: str = "",
    ) -> None:
        super().__init__(message)
        self.operation_may_continue = bool(operation_may_continue)
        self.status_command = str(status_command or "")


def control_request(request: dict[str, Any], timeout_ms: int = 2500) -> Any:
    socket = QLocalSocket()
    socket.connectToServer(CONTROL_SERVER_NAME)
    if not socket.waitForConnected(timeout_ms):
        raise ControlError("실행 중인 GUI에 연결할 수 없습니다.")
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
    if socket.write(payload) != len(payload):
        raise ControlError("GUI에 명령을 보내지 못했습니다.")
    # On Windows a fast peer can drain the queue before the blocking wait.
    # waitForBytesWritten(False) alone does not mean write() failed. Do not
    # discard an already-buffered reply and falsely switch to offline writes.
    if socket.bytesToWrite() > 0 and not socket.waitForBytesWritten(timeout_ms):
        if socket.bytesToWrite() > 0:
            raise ControlTimeoutError("GUI 명령 전송 확인 시간이 초과되었습니다.")

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
        if time.monotonic() >= deadline:
            raise ControlTimeoutError("GUI 응답 제한 시간이 초과되었습니다.")
        raise ControlError("GUI 연결이 응답 없이 종료되었습니다.")
    try:
        response = json.loads(received.decode("utf-8", errors="replace").splitlines()[0])
    except json.JSONDecodeError as error:
        raise ControlError("GUI 응답을 해석할 수 없습니다.") from error
    if not response.get("ok"):
        raise ControlError(str(response.get("error") or "GUI 명령 실패"))
    return response.get("result")


def local_api_http_request(
    base_url: str,
    token: str,
    *,
    method: str = "GET",
    path: str = "/v1/health",
    body: str = "",
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    parsed_base = urlsplit(str(base_url or ""))
    if (
        parsed_base.scheme != "http"
        or parsed_base.hostname != "127.0.0.1"
        or parsed_base.username
        or parsed_base.password
        or not parsed_base.port
    ):
        raise ControlError("로컬 API 요청은 127.0.0.1 HTTP 주소에만 보낼 수 있습니다.")
    clean_path = str(path or "")
    parsed_path = urlsplit(clean_path)
    if not clean_path.startswith("/") or parsed_path.scheme or parsed_path.netloc:
        raise ControlError("로컬 API 경로는 /로 시작하는 상대 경로여야 합니다.")
    clean_method = str(method or "GET").upper()
    if clean_method not in {"GET", "POST"}:
        raise ControlError("로컬 API 요청은 GET 또는 POST만 지원합니다.")
    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if clean_method == "POST":
        try:
            parsed_body = json.loads(body or "{}")
        except json.JSONDecodeError as error:
            raise ControlError("--body에는 올바른 JSON을 입력해야 합니다.") from error
        data = json.dumps(parsed_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{parsed_base.scheme}://{parsed_base.hostname}:{parsed_base.port}{clean_path}",
        data=data,
        headers=headers,
        method=clean_method,
    )
    try:
        response = urlopen(request, timeout=max(0.2, min(30.0, timeout_seconds)))
    except HTTPError as error:
        response = error
    except URLError as error:
        raise ControlError(f"로컬 API에 연결하지 못했습니다: {error.reason}") from error
    with response:
        status_code = int(response.status)
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ControlError("로컬 API 응답이 4 MiB를 넘습니다.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ControlError("로컬 API JSON 응답을 읽을 수 없습니다.") from error
    return {
        "ok": status_code < 400 and bool(payload.get("ok", True)),
        "statusCode": status_code,
        "response": payload,
    }


def gui_is_running() -> bool:
    try:
        result = control_request({"action": "ping"}, timeout_ms=350)
        return bool(result and result.get("pong"))
    except ControlTimeoutError:
        # A connected but busy GUI is still running. Never fall back to direct
        # DB/file mutations or launch a second GUI after a short ping timeout.
        return True
    except ControlError:
        return False


def copy_job_field(job_id: str | None, field: str) -> dict[str, str]:
    if gui_is_running():
        return control_request({"action": f"copy_{field}", "jobId": job_id})
    if not job_id:
        raise ControlError("GUI가 꺼져 있을 때는 --job 작업ID가 필요합니다.")
    job = load_job_by_id(job_id)
    if not job:
        raise ControlError(f"작업을 찾을 수 없습니다: {job_id}")
    values = {
        "id": job.job_id,
        "link": job.url,
        "path": job.output_path,
        "title": job.title,
    }
    value = str(values[field] or "")
    if not value:
        raise ControlError("복사할 값이 아직 없습니다.")
    copy_text_to_clipboard(value)
    return {"copied": value, "field": field, "via": "cli"}


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
    identity = apply_windows_app_user_model_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(APP_ORGANIZATION_NAME)
    app.setOrganizationDomain(APP_ORGANIZATION_DOMAIN)
    app_icon = QIcon(str(APP_ICON_PATH))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    app.setFont(QFont("Malgun Gothic", 9))
    if identity.get("error"):
        append_log(
            f"Windows 앱 ID 적용 실패: {identity['error']}",
            level="WARNING",
            job_id="gui",
        )

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
    provider = detect_download_provider(args.url)
    simulation = bool(getattr(args, "simulate", False))
    external_request_confirmed = bool(getattr(args, "confirm_external", False))
    if simulation and provider != "youtube":
        raise ValueError("--simulate은 YouTube 작업에서만 사용할 수 있습니다.")
    if provider == "youtube" and not simulation and not external_request_confirmed:
        raise ValueError("YouTube 외부 요청 실행에는 --confirm-external이 필요합니다.")
    if provider == "youtube":
        scan_mode, start, last = "new", None, None
    else:
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
        provider=provider,
        simulation=simulation,
        external_request_confirmed=external_request_confirmed,
    )
    command = (
        [sys.executable, *build_youtube_worker_args(job, config)]
        if provider == "youtube"
        else [
            find_node(),
            *build_downloader_args(
                job,
                json_events=False,
                folder_template=str(config.get("folderNameTemplate") or ""),
                network_config=config,
            ),
        ]
    )
    runtime_environment = dict(os.environ)
    runtime_environment.update(downloader_environment_overrides(config))
    if provider == "youtube":
        runtime_environment.update(
            {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        )
    for attempt in range(1, job.retry_limit + 2):
        job.attempt_count = attempt
        append_log(
            f"직접 CLI 실행 {attempt}/{job.retry_limit + 1}: {command}",
            job_id="direct",
        )
        completed = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            check=False,
            env=runtime_environment,
        )
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
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("gui", help="GUI 실행 또는 기존 GUI 앞으로 가져오기")
    subparsers.add_parser("show", help="실행 중인 GUI 앞으로 가져오기")
    doctor = subparsers.add_parser("doctor", help="필수·선택 의존성과 실행 환경 진단")
    doctor.add_argument("--json", action="store_true", help="JSON으로 출력")
    doctor_window = doctor.add_mutually_exclusive_group()
    doctor_window.add_argument("--show-gui", action="store_true", help="GUI 진단창 열기")
    doctor_window.add_argument("--close", action="store_true", help="GUI 진단창 닫기")
    app_identity = subparsers.add_parser(
        "app-identity", help="앱 이름·아이콘·Windows 작업 표시줄 ID 조회"
    )
    app_identity_mode = app_identity.add_mutually_exclusive_group()
    app_identity_mode.add_argument(
        "--via-gui", action="store_true", help="실행 중인 GUI의 실제 적용 상태 조회"
    )
    app_identity_mode.add_argument(
        "--show-gui", action="store_true", help="아이콘과 앱 ID가 표시된 GUI 창 열기"
    )
    app_identity_mode.add_argument(
        "--close", action="store_true", help="열린 앱 정보 창 닫기"
    )
    app_identity.add_argument("--json", action="store_true", help="JSON으로 출력")
    migrate = subparsers.add_parser("migrate", help="설정과 작업 DB 스키마 점검·마이그레이션")
    migrate_commands = migrate.add_subparsers(dest="migrate_command", required=True)
    migrate_status = migrate_commands.add_parser("status", help="현재 스키마 버전 조회")
    migrate_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    migrate_apply = migrate_commands.add_parser("apply", help="백업 후 최신 스키마 적용")
    migrate_apply.add_argument("--json", action="store_true", help="JSON으로 출력")
    diagnostics = subparsers.add_parser("diagnostics", help="민감정보 제거 진단 묶음")
    diagnostics_commands = diagnostics.add_subparsers(
        dest="diagnostics_command", required=True
    )
    diagnostics_export = diagnostics_commands.add_parser(
        "export", help="진단 JSON과 최근 로그를 ZIP으로 내보내기"
    )
    diagnostics_export.add_argument("--output", help="저장할 ZIP 경로")
    diagnostics_export.add_argument("--json", action="store_true", help="JSON으로 출력")
    diagnostics_export.add_argument(
        "--via-gui", action="store_true", help="GUI 도구 메뉴와 같은 경로로 실행"
    )
    config_parser = subparsers.add_parser(
        "config", help="설정 조회·변경·내보내기·가져오기"
    )
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    config_get = config_commands.add_parser("get", help="전체 설정 또는 한 항목 조회")
    config_get.add_argument("--key", choices=tuple(sorted(SETTING_KEYS)))
    config_get.add_argument("--json", action="store_true", help="JSON으로 출력")
    config_set = config_commands.add_parser("set", help="한 설정 항목 변경")
    config_set.add_argument("--key", required=True, choices=tuple(sorted(SETTING_KEYS)))
    config_set.add_argument("--value", required=True, help="문자열 또는 JSON 값")
    config_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    config_export = config_commands.add_parser("export", help="설정을 JSON 파일로 내보내기")
    config_export.add_argument("--output", required=True, help="저장할 JSON 경로")
    config_export.add_argument("--json", action="store_true", help="JSON으로 출력")
    config_import = config_commands.add_parser("import", help="설정 JSON 미리보기 또는 적용")
    config_import.add_argument("--input", required=True, help="가져올 JSON 경로")
    config_import.add_argument("--execute", action="store_true", help="실제로 적용")
    config_import.add_argument("--yes", action="store_true", help="적용 확인")
    config_import.add_argument("--json", action="store_true", help="JSON으로 출력")
    config_reset = config_commands.add_parser("reset", help="기본 설정 미리보기 또는 적용")
    config_reset.add_argument("--execute", action="store_true", help="실제로 초기화")
    config_reset.add_argument("--yes", action="store_true", help="초기화 확인")
    config_reset.add_argument("--json", action="store_true", help="JSON으로 출력")
    jobs_parser = subparsers.add_parser(
        "jobs", help="작업 기록 스냅샷 내보내기·가져오기"
    )
    jobs_commands = jobs_parser.add_subparsers(dest="jobs_command", required=True)
    jobs_export = jobs_commands.add_parser("export", help="작품과 실행 기록을 JSON으로 내보내기")
    jobs_export.add_argument("--output", required=True, help="저장할 JSON 경로")
    jobs_export.add_argument("--json", action="store_true", help="JSON으로 출력")
    jobs_export.add_argument(
        "--via-gui", action="store_true", help="실행 중인 GUI의 공용 서비스로 내보내기"
    )
    jobs_import = jobs_commands.add_parser("import", help="작업 스냅샷 미리보기 또는 추가")
    jobs_import.add_argument("--input", help="가져올 JSON 경로")
    jobs_import_mode = jobs_import.add_mutually_exclusive_group()
    jobs_import_mode.add_argument("--dry-run", action="store_true", help="변경 예정만 확인")
    jobs_import_mode.add_argument("--execute", action="store_true", help="실제로 기록 추가")
    jobs_import_mode.add_argument(
        "--show-gui", action="store_true", help="GUI에서 가져오기 미리보기 표시"
    )
    jobs_import_mode.add_argument("--close", action="store_true", help="GUI 미리보기 창 닫기")
    jobs_import.add_argument("--yes", action="store_true", help="가져오기 확인")
    jobs_import.add_argument("--json", action="store_true", help="JSON으로 출력")
    jobs_import.add_argument(
        "--via-gui", action="store_true", help="실행 중인 GUI의 공용 서비스로 가져오기"
    )
    group_parser = subparsers.add_parser("group", help="작품 정리 그룹 관리")
    group_commands = group_parser.add_subparsers(dest="group_command", required=True)
    group_list = group_commands.add_parser("list", help="작품 그룹 목록")
    group_list.add_argument("--json", action="store_true", help="JSON으로 출력")
    group_create = group_commands.add_parser("create", help="작품 그룹 생성")
    group_create.add_argument("--name", required=True, help="새 그룹 이름")
    group_create.add_argument("--json", action="store_true", help="JSON으로 출력")
    group_rename = group_commands.add_parser("rename", help="작품 그룹 이름 변경")
    group_rename.add_argument("--group", required=True, help="그룹 ID")
    group_rename.add_argument("--name", required=True, help="새 이름")
    group_rename.add_argument("--json", action="store_true", help="JSON으로 출력")
    group_assign = group_commands.add_parser("assign", help="작품을 그룹에 배정")
    group_assign.add_argument("--job", required=True, help="작업 ID")
    group_assign.add_argument("--group", required=True, help="그룹 ID")
    group_assign.add_argument("--json", action="store_true", help="JSON으로 출력")
    group_unassign = group_commands.add_parser("unassign", help="작품을 미분류로 이동")
    group_unassign.add_argument("--job", required=True, help="작업 ID")
    group_unassign.add_argument("--json", action="store_true", help="JSON으로 출력")
    group_manage = group_commands.add_parser("manage", help="GUI 작품 그룹 관리 창")
    group_manage_window = group_manage.add_mutually_exclusive_group(required=True)
    group_manage_window.add_argument("--show-gui", action="store_true", help="관리 창 열기")
    group_manage_window.add_argument("--close", action="store_true", help="관리 창 닫기")
    local_parser = subparsers.add_parser("local", help="로컬 폴더·압축 작품 도구")
    local_commands = local_parser.add_subparsers(dest="local_command", required=True)
    local_inspect = local_commands.add_parser("inspect", help="압축 파일을 풀지 않고 구조 검사")
    local_inspect.add_argument("--path", help="검사할 ZIP/CBZ/7Z/CB7/RAR/CBR 경로")
    local_inspect_window = local_inspect.add_mutually_exclusive_group()
    local_inspect_window.add_argument("--show-gui", action="store_true", help="GUI 검사 결과 표시")
    local_inspect_window.add_argument("--close", action="store_true", help="GUI 검사 결과 닫기")
    local_inspect.add_argument("--json", action="store_true", help="JSON으로 출력")
    archive_viewer = subparsers.add_parser(
        "archive-viewer", help="압축 파일 연결 프로그램 조회·설정·안전한 열기"
    )
    archive_viewer_commands = archive_viewer.add_subparsers(
        dest="archive_viewer_command", required=True
    )
    archive_viewer_status = archive_viewer_commands.add_parser(
        "status", help="현재 앱 내부 연결 프로그램 정책 조회"
    )
    archive_viewer_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    archive_viewer_set = archive_viewer_commands.add_parser(
        "set", help="기본 연결 프로그램 또는 지정한 프로그램 선택"
    )
    archive_viewer_set.add_argument("--mode", choices=("system", "custom"))
    archive_viewer_path = archive_viewer_set.add_mutually_exclusive_group()
    archive_viewer_path.add_argument("--path", help="custom 방식에서 사용할 실행 파일")
    archive_viewer_path.add_argument(
        "--clear-path", action="store_true", help="저장된 지정 프로그램 경로 지우기"
    )
    archive_viewer_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    archive_viewer_open = archive_viewer_commands.add_parser(
        "open", help="압축 파일 열기 계획 조회 또는 확인 후 실행"
    )
    archive_viewer_open.add_argument("--path", required=True, help="열 압축 파일 경로")
    archive_viewer_open.add_argument(
        "--execute", action="store_true", help="외부 연결 프로그램 실제 실행"
    )
    archive_viewer_open.add_argument(
        "--yes", action="store_true", help="외부 프로그램 실행 확인"
    )
    archive_viewer_open.add_argument("--json", action="store_true", help="JSON으로 출력")
    persistence = subparsers.add_parser(
        "persistence", help="자동 저장 주기와 불완전 작업 복구"
    )
    persistence_commands = persistence.add_subparsers(
        dest="persistence_command", required=True
    )
    persistence_status = persistence_commands.add_parser(
        "status", help="저장·복구 정책과 복구 후보 조회"
    )
    persistence_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    persistence_set = persistence_commands.add_parser(
        "set", help="자동 저장과 시작 복구 설정"
    )
    persistence_set.add_argument(
        "--autosave-seconds", type=int, help="변경 작업 자동 저장 주기(1~300초)"
    )
    persistence_set.add_argument(
        "--startup-recovery", choices=("on", "off"), help="시작 시 불완전 기록 복구"
    )
    persistence_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    persistence_recover = persistence_commands.add_parser(
        "recover", help="불완전 기록 미리보기 또는 확인 후 중지됨으로 복구"
    )
    persistence_recover_mode = persistence_recover.add_mutually_exclusive_group()
    persistence_recover_mode.add_argument(
        "--execute", action="store_true", help="DB의 불완전 기록을 실제 복구"
    )
    persistence_recover_mode.add_argument(
        "--show-gui", action="store_true", help="GUI 복구 미리보기 표시"
    )
    persistence_recover_mode.add_argument(
        "--close", action="store_true", help="GUI 복구 미리보기 닫기"
    )
    persistence_recover.add_argument("--yes", action="store_true", help="실제 복구 확인")
    persistence_recover.add_argument("--json", action="store_true", help="JSON으로 출력")
    list_performance = subparsers.add_parser(
        "list-performance", help="대규모 작품 목록 페이지·스크롤·지연 로딩 정책"
    )
    list_performance_commands = list_performance.add_subparsers(
        dest="list_performance_command", required=True
    )
    list_performance_status = list_performance_commands.add_parser(
        "status", help="현재 목록 성능 정책 조회"
    )
    list_performance_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    list_performance_set = list_performance_commands.add_parser(
        "set", help="목록 성능 정책 변경"
    )
    list_performance_set.add_argument(
        "--page-size", type=int, help="SQLite 페이지당 작품 수(25~1000)"
    )
    list_performance_set.add_argument(
        "--loaded-limit", type=int, help="메모리 내 작품 상한(100~5000)"
    )
    list_performance_set.add_argument(
        "--scroll-lines", type=int, help="휠 스크롤 속도(1~20단계)"
    )
    list_performance_set.add_argument(
        "--lazy-loading", choices=("on", "off"), help="하단 도달 시 다음 페이지 로딩"
    )
    list_performance_set.add_argument(
        "--low-spec", choices=("on", "off"), help="저사양 목록 프로필"
    )
    list_performance_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    sleep_prevention = subparsers.add_parser(
        "sleep-prevention", help="다운로드 중 Windows 시스템 절전 방지 정책"
    )
    sleep_prevention_commands = sleep_prevention.add_subparsers(
        dest="sleep_prevention_command", required=True
    )
    sleep_prevention_status = sleep_prevention_commands.add_parser(
        "status", help="저장 설정과 실행 중 절전 방지 상태 조회"
    )
    sleep_prevention_status.add_argument(
        "--json", action="store_true", help="JSON으로 출력"
    )
    sleep_prevention_set = sleep_prevention_commands.add_parser(
        "set", help="다운로드 중 절전 방지 설정 변경"
    )
    sleep_prevention_set.add_argument(
        "--state", choices=("on", "off"), required=True, help="절전 방지 사용 여부"
    )
    sleep_prevention_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    sleep_prevention_plan = sleep_prevention_commands.add_parser(
        "plan", help="Windows API 호출 없이 활성 다운로드 수에 따른 정책 계산"
    )
    sleep_prevention_plan.add_argument(
        "--active-downloads", type=int, required=True, help="가정할 실행 다운로드 수(0 이상)"
    )
    sleep_prevention_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    memory_parser = subparsers.add_parser(
        "memory", help="앱·자식 작업·시스템 메모리 사용량과 표시 설정"
    )
    memory_commands = memory_parser.add_subparsers(
        dest="memory_command", required=True
    )
    memory_status = memory_commands.add_parser(
        "status", help="현재 메모리 사용량과 경고 상태 조회"
    )
    memory_status.add_argument(
        "--child-limit", type=int, default=200, help="반환할 자식 프로세스 최대 수(0~1000)"
    )
    memory_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    memory_set = memory_commands.add_parser(
        "set", help="GUI 상태 표시줄의 메모리 표시 여부 변경"
    )
    memory_set.add_argument(
        "--display", choices=("on", "off"), required=True, help="메모리 표시 사용 여부"
    )
    memory_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    local_api = subparsers.add_parser(
        "local-api", help="127.0.0.1 전용 인증 HTTP API 설정과 점검"
    )
    local_api_commands = local_api.add_subparsers(
        dest="local_api_command", required=True
    )
    local_api_status = local_api_commands.add_parser(
        "status", help="저장 설정과 현재 서버 상태 조회(토큰 원문 제외)"
    )
    local_api_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    local_api_set = local_api_commands.add_parser(
        "set", help="로컬 API 사용 여부와 포트 변경"
    )
    local_api_set.add_argument("--state", choices=("on", "off"), help="서버 사용 여부")
    local_api_set.add_argument("--port", type=int, help="127.0.0.1 수신 포트(1024~65535)")
    local_api_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    local_api_token = local_api_commands.add_parser(
        "token", help="실행 중 서버의 임시 토큰을 명시적으로 표시·복사·재발급"
    )
    local_api_token_mode = local_api_token.add_mutually_exclusive_group(required=True)
    local_api_token_mode.add_argument("--show", action="store_true", help="토큰 원문 표시")
    local_api_token_mode.add_argument("--copy", action="store_true", help="토큰을 클립보드에 복사")
    local_api_token_mode.add_argument("--rotate", action="store_true", help="기존 토큰 폐기 후 재발급")
    local_api_token.add_argument("--yes", action="store_true", help="민감한 토큰 작업 확인")
    local_api_token.add_argument("--json", action="store_true", help="JSON으로 출력")
    local_api_request = local_api_commands.add_parser(
        "request", help="토큰을 출력하지 않고 실행 중 로컬 API를 직접 점검"
    )
    local_api_request.add_argument(
        "--method", choices=("GET", "POST"), default="GET", help="HTTP 방식"
    )
    local_api_request.add_argument("--path", default="/v1/health", help="/로 시작하는 API 경로")
    local_api_request.add_argument("--body", default="", help="POST JSON 본문")
    local_api_request.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_parser = subparsers.add_parser(
        "hitomi", help="Hitomi/ExHentai 선택 공급자 URL과 갤러리 ID 도구"
    )
    hitomi_commands = hitomi_parser.add_subparsers(
        dest="hitomi_command", required=True
    )
    hitomi_status = hitomi_commands.add_parser(
        "status", help="공급자 계약과 현재 구현 범위 조회"
    )
    hitomi_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_inspect = hitomi_commands.add_parser(
        "inspect", help="외부 접속 없이 URL 또는 갤러리 ID 분석"
    )
    hitomi_inspect.add_argument(
        "--input", required=True, help="Hitomi/ExHentai URL 또는 숫자 갤러리 ID"
    )
    hitomi_inspect.add_argument(
        "--provider",
        choices=("auto", "hitomi", "exhentai"),
        default="auto",
        help="숫자 ID 해석 공급자 또는 URL 일치 확인",
    )
    hitomi_inspect.add_argument(
        "--show-gui", action="store_true", help="분석 결과를 GUI 대화상자에 표시"
    )
    hitomi_inspect.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_close = hitomi_commands.add_parser(
        "close", help="열린 Hitomi URL/ID 분석창 닫기"
    )
    hitomi_close.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_server = hitomi_commands.add_parser(
        "server", help="Hitomi/ExHentai 서버 자동·수동 선택과 우선순위"
    )
    hitomi_server_commands = hitomi_server.add_subparsers(
        dest="hitomi_server_command", required=True
    )
    hitomi_server_status = hitomi_server_commands.add_parser(
        "status", help="현재 서버 선택 정책 조회"
    )
    hitomi_server_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_server_set = hitomi_server_commands.add_parser(
        "set", help="서버 방식·수동 서버·자동 우선순위 저장"
    )
    hitomi_server_set.add_argument("--mode", choices=("auto", "manual"))
    hitomi_server_set.add_argument(
        "--manual-server", choices=("hitomi", "exhentai", "ehentai")
    )
    hitomi_server_set.add_argument(
        "--priority",
        help="hitomi,exhentai,ehentai를 중복 없이 쉼표 순서로 지정",
    )
    hitomi_server_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_server_plan = hitomi_server_commands.add_parser(
        "plan", help="외부 접속 없이 입력 작품의 실제 후보 서버 계산"
    )
    hitomi_server_plan.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
    hitomi_server_plan.add_argument(
        "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
    )
    hitomi_server_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_metadata = hitomi_commands.add_parser(
        "metadata", help="갤러리 메타데이터 전용 계획·픽스처·요청"
    )
    hitomi_metadata_commands = hitomi_metadata.add_subparsers(
        dest="hitomi_metadata_command", required=True
    )
    hitomi_metadata_status = hitomi_metadata_commands.add_parser(
        "status", help="메타데이터 모드와 안전 상한 조회"
    )
    hitomi_metadata_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_metadata_set = hitomi_metadata_commands.add_parser(
        "set", help="자동·필수·사용 안 함 방식 저장"
    )
    hitomi_metadata_set.add_argument(
        "--mode", choices=("auto", "required", "disabled"), required=True
    )
    hitomi_metadata_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name, help_text in (
        ("plan", "외부 요청 없이 엔드포인트와 마스킹 본문 계산"),
        ("parse", "로컬 픽스처를 공통 메타데이터로 변환"),
        ("fetch", "명시적 확인 뒤 실제 공급자 메타데이터 요청"),
        ("show", "GUI 메타데이터 대화상자 열기"),
    ):
        metadata_command = hitomi_metadata_commands.add_parser(name, help=help_text)
        metadata_command.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
        metadata_command.add_argument(
            "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
        )
        metadata_command.add_argument("--json", action="store_true", help="JSON으로 출력")
        if name in {"parse", "show"}:
            metadata_command.add_argument(
                "--fixture",
                required=name == "parse",
                help="로컬 JS/JSON 픽스처 경로",
            )
        if name == "fetch":
            metadata_command.add_argument("--yes", action="store_true", help="외부 요청 확인")
            metadata_command.add_argument("--timeout", type=int, default=30, help="요청 제한 초")
            metadata_command.add_argument(
                "--use-cookies",
                action="store_true",
                help="ExHentai/E-Hentai에서만 확인 후 OS 보안 저장소 쿠키 사용",
            )
    hitomi_metadata_decide = hitomi_metadata_commands.add_parser(
        "decide", help="외부 요청 없이 모드별 성공·실패 후속 동작 계산"
    )
    hitomi_metadata_decide.add_argument(
        "--outcome", choices=("pending", "success", "failure"), required=True
    )
    hitomi_metadata_decide.add_argument(
        "--error-code", default="", help="실패 결과에 함께 기록할 안정 오류 코드"
    )
    hitomi_metadata_decide.add_argument(
        "--json", action="store_true", help="JSON으로 출력"
    )
    hitomi_metadata_close = hitomi_metadata_commands.add_parser(
        "close", help="열린 메타데이터 대화상자 닫기"
    )
    hitomi_metadata_close.add_argument("--json", action="store_true", help="JSON으로 출력")

    youtube = subparsers.add_parser("youtube", help="YouTube 선택 공급자 정책과 오프라인 계획")
    youtube_commands = youtube.add_subparsers(dest="youtube_command", required=True)
    youtube_format = youtube_commands.add_parser("format", help="형식·해상도·코덱 정책")
    youtube_format_commands = youtube_format.add_subparsers(
        dest="youtube_format_command", required=True
    )
    youtube_format_status = youtube_format_commands.add_parser("status", help="현재 정책 조회")
    youtube_format_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name, help_text in (("set", "형식 정책 저장"), ("plan", "외부 요청 없이 yt-dlp 인자 계산")):
        youtube_format_command = youtube_format_commands.add_parser(name, help=help_text)
        if name == "plan":
            youtube_format_command.add_argument("--input", required=True, help="YouTube URL")
        youtube_format_command.add_argument("--mode", choices=YOUTUBE_FORMAT_MODES)
        youtube_format_command.add_argument(
            "--max-height", type=int, choices=YOUTUBE_MAX_HEIGHTS
        )
        youtube_format_command.add_argument("--container", choices=YOUTUBE_CONTAINERS)
        youtube_format_command.add_argument("--video-codec", choices=YOUTUBE_VIDEO_CODECS)
        youtube_format_command.add_argument("--audio-codec", choices=YOUTUBE_AUDIO_CODECS)
        youtube_format_command.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_filename = youtube_commands.add_parser("filename", help="안전한 출력 파일명 템플릿")
    youtube_filename_commands = youtube_filename.add_subparsers(
        dest="youtube_filename_command", required=True
    )
    youtube_filename_status = youtube_filename_commands.add_parser("status", help="현재 템플릿 조회")
    youtube_filename_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_filename_set = youtube_filename_commands.add_parser("set", help="템플릿 저장")
    youtube_filename_set.add_argument("--template", required=True)
    youtube_filename_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_filename_preview = youtube_filename_commands.add_parser("preview", help="오프라인 예시 파일명")
    youtube_filename_preview.add_argument("--template")
    youtube_filename_preview.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_tracks = youtube_commands.add_parser("tracks", help="선호 언어·자막·오디오 트랙")
    youtube_track_commands = youtube_tracks.add_subparsers(dest="youtube_track_command", required=True)
    youtube_track_status = youtube_track_commands.add_parser("status", help="현재 트랙 정책")
    youtube_track_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name in ("set", "plan"):
        track_command = youtube_track_commands.add_parser(name, help="트랙 정책 저장" if name == "set" else "오프라인 인자 계획")
        if name == "plan":
            track_command.add_argument("--input", required=True)
        track_command.add_argument("--languages")
        track_command.add_argument("--subtitles", choices=YOUTUBE_SUBTITLE_MODES)
        track_command.add_argument("--subtitle-format", choices=YOUTUBE_SUBTITLE_FORMATS)
        track_command.add_argument("--embed-subtitles", choices=("on", "off"))
        track_command.add_argument("--audio-tracks", choices=YOUTUBE_AUDIO_TRACK_MODES)
        track_command.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_metadata = youtube_commands.add_parser(
        "metadata", help="썸네일·설명·정보 JSON·미디어 메타데이터"
    )
    youtube_metadata_commands = youtube_metadata.add_subparsers(
        dest="youtube_metadata_command", required=True
    )
    youtube_metadata_status = youtube_metadata_commands.add_parser(
        "status", help="현재 썸네일·메타데이터 정책"
    )
    youtube_metadata_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name in ("set", "plan"):
        metadata_command = youtube_metadata_commands.add_parser(
            name,
            help="썸네일·메타데이터 정책 저장" if name == "set" else "오프라인 인자 계획",
        )
        if name == "plan":
            metadata_command.add_argument("--input", required=True)
        metadata_command.add_argument("--write-thumbnail", choices=("on", "off"))
        metadata_command.add_argument("--embed-thumbnail", choices=("on", "off"))
        metadata_command.add_argument("--write-info-json", choices=("on", "off"))
        metadata_command.add_argument("--write-description", choices=("on", "off"))
        metadata_command.add_argument("--embed-metadata", choices=("on", "off"))
        metadata_command.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_collection = youtube_commands.add_parser(
        "collection", help="채널·재생목록 처리 순서"
    )
    youtube_collection_commands = youtube_collection.add_subparsers(
        dest="youtube_collection_command", required=True
    )
    youtube_collection_status = youtube_collection_commands.add_parser(
        "status", help="현재 채널·재생목록 순서"
    )
    youtube_collection_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name in ("set", "plan"):
        collection_command = youtube_collection_commands.add_parser(
            name, help="순서 정책 저장" if name == "set" else "오프라인 범위·인자 계획"
        )
        if name == "plan":
            collection_command.add_argument("--input", required=True)
        collection_command.add_argument("--order", choices=YOUTUBE_COLLECTION_ORDERS)
        collection_command.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_chapters = youtube_commands.add_parser("chapters", help="미디어 챕터 마커")
    youtube_chapter_commands = youtube_chapters.add_subparsers(
        dest="youtube_chapter_command", required=True
    )
    youtube_chapter_status = youtube_chapter_commands.add_parser(
        "status", help="현재 챕터 마커 정책"
    )
    youtube_chapter_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name in ("set", "plan"):
        chapter_command = youtube_chapter_commands.add_parser(
            name, help="챕터 정책 저장" if name == "set" else "오프라인 인자 계획"
        )
        if name == "plan":
            chapter_command.add_argument("--input", required=True)
        chapter_command.add_argument("--embed", choices=("on", "off"))
        chapter_command.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_mtime = youtube_commands.add_parser(
        "mtime", help="업로드 날짜를 파일 수정 시각으로 적용"
    )
    youtube_mtime_commands = youtube_mtime.add_subparsers(
        dest="youtube_mtime_command", required=True
    )
    youtube_mtime_status = youtube_mtime_commands.add_parser(
        "status", help="현재 파일 시간 정책"
    )
    youtube_mtime_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    youtube_mtime_set = youtube_mtime_commands.add_parser("set", help="파일 시간 정책 저장")
    youtube_mtime_set.add_argument("--state", choices=("on", "off"), required=True)
    youtube_mtime_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name in ("plan", "apply"):
        mtime_command = youtube_mtime_commands.add_parser(
            name, help="파일 변경 없이 시간 계획" if name == "plan" else "확인 후 파일 시간 적용"
        )
        mtime_command.add_argument("--file", required=True)
        mtime_command.add_argument("--upload-date", required=True, help="YYYYMMDD")
        mtime_command.add_argument("--state", choices=("on", "off"))
        if name == "apply":
            mtime_command.add_argument("--yes", action="store_true", help="파일 수정 시각 변경 확인")
        mtime_command.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_filenames = hitomi_commands.add_parser(
        "filenames", help="Hitomi 이미지 파일명 방식과 로컬 계획"
    )
    hitomi_filename_commands = hitomi_filenames.add_subparsers(
        dest="hitomi_filename_command", required=True
    )
    hitomi_filename_status = hitomi_filename_commands.add_parser(
        "status", help="현재 원본·숫자 파일명 정책 조회"
    )
    hitomi_filename_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_filename_set = hitomi_filename_commands.add_parser(
        "set", help="이미지 파일명 방식 저장"
    )
    hitomi_filename_set.add_argument(
        "--mode", choices=("original", "number", "number_original"), required=True
    )
    hitomi_filename_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_filename_plan = hitomi_filename_commands.add_parser(
        "plan", help="로컬 메타데이터 픽스처에서 안전한 파일명 계획"
    )
    hitomi_filename_plan.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
    hitomi_filename_plan.add_argument(
        "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
    )
    hitomi_filename_plan.add_argument("--fixture", required=True, help="로컬 JS/JSON 픽스처 경로")
    hitomi_filename_plan.add_argument(
        "--mode", choices=("original", "number", "number_original"),
        help="저장 설정 대신 이 계획에만 적용할 방식",
    )
    hitomi_filename_plan.add_argument(
        "--sample-limit", type=int, default=100, help="출력할 샘플 수(최대 1000)"
    )
    hitomi_filename_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_tags = hitomi_commands.add_parser(
        "tags", help="Hitomi 제외 태그 규칙과 로컬 판정"
    )
    hitomi_tag_commands = hitomi_tags.add_subparsers(
        dest="hitomi_tag_command", required=True
    )
    hitomi_tag_status = hitomi_tag_commands.add_parser(
        "status", help="현재 제외 태그 규칙 조회"
    )
    hitomi_tag_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_tag_set = hitomi_tag_commands.add_parser(
        "set", help="쉼표·세미콜론 구분 제외 태그 저장"
    )
    hitomi_tag_set_mode = hitomi_tag_set.add_mutually_exclusive_group(required=True)
    hitomi_tag_set_mode.add_argument("--tags", help="예: guro,female:full color")
    hitomi_tag_set_mode.add_argument("--clear", action="store_true", help="모든 제외 태그 해제")
    hitomi_tag_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_tag_evaluate = hitomi_tag_commands.add_parser(
        "evaluate", help="로컬 메타데이터 픽스처의 제외 여부 판정"
    )
    hitomi_tag_evaluate.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
    hitomi_tag_evaluate.add_argument(
        "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
    )
    hitomi_tag_evaluate.add_argument("--fixture", required=True, help="로컬 JS/JSON 픽스처 경로")
    hitomi_tag_evaluate.add_argument(
        "--tags", help="저장 설정 대신 이 판정에만 적용할 규칙"
    )
    hitomi_tag_evaluate.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_title = hitomi_commands.add_parser(
        "title", help="Hitomi 기본·일본어 제목 선택 정책"
    )
    hitomi_title_commands = hitomi_title.add_subparsers(
        dest="hitomi_title_command", required=True
    )
    hitomi_title_status = hitomi_title_commands.add_parser(
        "status", help="현재 일본어 제목 우선 정책 조회"
    )
    hitomi_title_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_title_set = hitomi_title_commands.add_parser(
        "set", help="일본어 제목 우선 사용 설정"
    )
    hitomi_title_set.add_argument("--prefer-japanese", choices=("on", "off"), required=True)
    hitomi_title_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_title_select = hitomi_title_commands.add_parser(
        "select", help="로컬 메타데이터 픽스처에서 표시 제목 선택"
    )
    hitomi_title_select.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
    hitomi_title_select.add_argument(
        "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
    )
    hitomi_title_select.add_argument("--fixture", required=True, help="로컬 JS/JSON 픽스처 경로")
    hitomi_title_select.add_argument(
        "--prefer-japanese", choices=("on", "off"),
        help="저장 설정 대신 이 선택에만 적용",
    )
    hitomi_title_select.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_metadata_files = hitomi_commands.add_parser(
        "metadata-files", help="공통 metadata.json과 info.txt 계획·저장"
    )
    hitomi_metadata_file_commands = hitomi_metadata_files.add_subparsers(
        dest="hitomi_metadata_file_command", required=True
    )
    hitomi_metadata_file_status = hitomi_metadata_file_commands.add_parser(
        "status", help="현재 메타데이터 파일 생성 정책 조회"
    )
    hitomi_metadata_file_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_metadata_file_set = hitomi_metadata_file_commands.add_parser(
        "set", help="metadata.json·info.txt 생성 방식 저장"
    )
    hitomi_metadata_file_set.add_argument(
        "--mode", choices=("metadata_json", "info_txt", "both", "disabled"), required=True
    )
    hitomi_metadata_file_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    for name, help_text in (
        ("plan", "파일을 만들지 않고 대상·충돌 계산"),
        ("write", "명시적 확인 후 작품 폴더에 메타데이터 파일 저장"),
    ):
        metadata_file_command = hitomi_metadata_file_commands.add_parser(name, help=help_text)
        metadata_file_command.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
        metadata_file_command.add_argument(
            "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
        )
        metadata_file_command.add_argument("--fixture", required=True, help="로컬 JS/JSON 픽스처 경로")
        metadata_file_command.add_argument("--output", required=True, help="기존 작품 폴더 경로")
        metadata_file_command.add_argument(
            "--mode", choices=("metadata_json", "info_txt", "both", "disabled"),
            help="저장 설정 대신 이 작업에만 적용",
        )
        metadata_file_command.add_argument("--json", action="store_true", help="JSON으로 출력")
        if name == "write":
            metadata_file_command.add_argument("--yes", action="store_true", help="파일 생성 확인")
            metadata_file_command.add_argument(
                "--overwrite", action="store_true", help="기존 파일 교체 확인"
            )
    hitomi_images = hitomi_commands.add_parser(
        "images", help="Hitomi 원본 또는 최적화 이미지 선택 정책"
    )
    hitomi_image_commands = hitomi_images.add_subparsers(
        dest="hitomi_image_command", required=True
    )
    hitomi_image_status = hitomi_image_commands.add_parser(
        "status", help="현재 원본 이미지 사용 정책 조회"
    )
    hitomi_image_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_image_set = hitomi_image_commands.add_parser(
        "set", help="원본 이미지 사용 설정"
    )
    hitomi_image_set.add_argument("--original", choices=("on", "off"), required=True)
    hitomi_image_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    hitomi_image_plan = hitomi_image_commands.add_parser(
        "plan", help="로컬 메타데이터 픽스처에서 이미지 변형 선택"
    )
    hitomi_image_plan.add_argument("--input", required=True, help="URL 또는 갤러리 ID")
    hitomi_image_plan.add_argument(
        "--provider", choices=("auto", "hitomi", "exhentai"), default="auto"
    )
    hitomi_image_plan.add_argument("--fixture", required=True, help="로컬 JS/JSON 픽스처 경로")
    hitomi_image_plan.add_argument(
        "--original", choices=("on", "off"), help="저장 설정 대신 이 계획에만 적용"
    )
    hitomi_image_plan.add_argument("--sample-limit", type=int, default=100)
    hitomi_image_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    duplicates_parser = subparsers.add_parser("duplicates", help="작품·이미지 중복 검사")
    duplicates_commands = duplicates_parser.add_subparsers(
        dest="duplicates_command", required=True
    )
    duplicate_works = duplicates_commands.add_parser("works", help="중복 의심 작품 검사")
    duplicate_works_window = duplicate_works.add_mutually_exclusive_group()
    duplicate_works_window.add_argument("--show-gui", action="store_true", help="GUI 결과 표시")
    duplicate_works_window.add_argument("--close", action="store_true", help="GUI 결과 닫기")
    duplicate_works.add_argument("--json", action="store_true", help="JSON으로 출력")
    duplicate_images = duplicates_commands.add_parser("images", help="작품 이미지 해시 중복 검사")
    duplicate_images.add_argument("--job", help="작업 ID")
    duplicate_images.add_argument(
        "--algorithm", choices=("sha256", "phash"), default="sha256", help="해시 방식"
    )
    duplicate_images_window = duplicate_images.add_mutually_exclusive_group()
    duplicate_images_window.add_argument("--show-gui", action="store_true", help="GUI 결과 표시")
    duplicate_images_window.add_argument("--close", action="store_true", help="GUI 결과 닫기")
    duplicate_images.add_argument("--json", action="store_true", help="JSON으로 출력")

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
    download.add_argument(
        "--confirm-external",
        action="store_true",
        help="YouTube 외부 조회·다운로드 실행을 명시적으로 확인",
    )
    download.add_argument(
        "--simulate",
        action="store_true",
        help="YouTube 진행률·이력 통합을 외부 요청 없이 모의 실행",
    )

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
    performance_benchmark = performance_commands.add_parser(
        "benchmark", help="격리된 합성 DB에서 100~100,000개 목록 성능 측정"
    )
    performance_benchmark.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[100, 1_000, 10_000, 100_000],
        help="측정할 누적 작품 수(각 1~100000)",
    )
    performance_benchmark.add_argument(
        "--page-size", type=int, default=200, help="첫 화면 조회 수(최대 1000)"
    )
    performance_benchmark.add_argument("--output", help="JSON 보고서 저장 경로")
    performance_benchmark.add_argument("--json", action="store_true", help="JSON으로 출력")
    performance_benchmark.add_argument(
        "--via-gui", action="store_true", help="GUI 진단창을 열고 백그라운드에서 실행"
    )
    performance_stability = performance_commands.add_parser(
        "stability", help="격리 DB에서 반복 실행·강제 종료·재시작 복구 검증"
    )
    performance_stability.add_argument(
        "--records", type=int, default=10_000, help="격리 DB 작품 수(100~100000)"
    )
    performance_stability.add_argument(
        "--cycles", type=int, default=100, help="읽기·쓰기 재시작 반복 수(1~1000)"
    )
    performance_stability.add_argument("--output", help="JSON 보고서 저장 경로")
    performance_stability.add_argument("--json", action="store_true", help="JSON으로 출력")
    performance_stability.add_argument(
        "--via-gui", action="store_true", help="GUI 진단창을 열고 백그라운드에서 실행"
    )
    performance_event_policy = performance_commands.add_parser(
        "event-policy", help="다운로더 이벤트의 UI 병합·저장 정책 조회"
    )
    performance_event_policy.add_argument(
        "--event", default="image_saved", help="검사할 JSON 이벤트 이름"
    )
    performance_event_policy.add_argument(
        "--json", action="store_true", help="JSON으로 출력"
    )
    performance_resources = performance_commands.add_parser(
        "resources", help="I/O 스레드·CPU 프로세스·대기열 자원 상한 조회"
    )
    performance_resources.add_argument("--json", action="store_true", help="JSON으로 출력")

    thumbnail_cache = subparsers.add_parser(
        "thumbnail-cache", help="앱 전용 썸네일 디스크 캐시 조회·정리"
    )
    thumbnail_cache_commands = thumbnail_cache.add_subparsers(
        dest="thumbnail_cache_command", required=True
    )
    thumbnail_cache_status = thumbnail_cache_commands.add_parser(
        "status", help="캐시 크기와 정리 예정 항목 조회"
    )
    thumbnail_cache_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    thumbnail_cache_cleanup = thumbnail_cache_commands.add_parser(
        "cleanup", help="보존 기간·파일 수·용량 상한을 넘는 캐시 정리"
    )
    thumbnail_cache_cleanup.add_argument(
        "--execute", action="store_true", help="실제로 앱 캐시 파일 제거"
    )
    thumbnail_cache_cleanup.add_argument("--json", action="store_true", help="JSON으로 출력")

    retention = subparsers.add_parser("retention", help="로그와 오래된 실행 이력 보존 정책")
    retention_commands = retention.add_subparsers(dest="retention_command", required=True)
    retention_status = retention_commands.add_parser(
        "status", help="로그 순환과 실행 이력 정리 예정량 조회"
    )
    retention_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    retention_cleanup = retention_commands.add_parser(
        "cleanup-runs", help="최신·진행 중 기록을 제외한 오래된 실행 이력 정리"
    )
    retention_cleanup.add_argument(
        "--max-per-work", type=int, default=500, help="작품별 최대 보존 실행 수"
    )
    retention_cleanup.add_argument(
        "--max-age-days", type=int, default=365, help="최대 보존 일수"
    )
    retention_cleanup.add_argument(
        "--execute", action="store_true", help="실제로 오래된 실행 이력 제거"
    )
    retention_cleanup.add_argument("--json", action="store_true", help="JSON으로 출력")

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
    shortcut_action = shortcuts.add_mutually_exclusive_group()
    shortcut_action.add_argument(
        "--show-gui", action="store_true", help="GUI 단축키 안내창 열기"
    )
    shortcut_action.add_argument(
        "--close", action="store_true", help="GUI 단축키 안내창 닫기"
    )
    shortcut_action.add_argument("--set", metavar="ACTION", help="동작 단축키 덮어쓰기")
    shortcut_action.add_argument("--disable", metavar="ACTION", help="동작 단축키 비활성화")
    shortcut_action.add_argument("--reset", metavar="ACTION", help="동작 기본 단축키 복원")
    shortcut_action.add_argument("--reset-all", action="store_true", help="모든 기본 단축키 복원")
    shortcut_action.add_argument("--export", dest="export_path", metavar="PATH", help="단축키 JSON 내보내기")
    shortcut_action.add_argument("--import", dest="import_path", metavar="PATH", help="단축키 JSON 검사 또는 가져오기")
    shortcuts.add_argument("--keys", help="세미콜론으로 구분한 단축키; --set과 함께 사용")
    shortcuts.add_argument("--execute", action="store_true", help="--import 결과 실제 적용")
    shortcuts.add_argument("--yes", action="store_true", help="가져오기 적용 확인")

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
    settings_window = settings.add_mutually_exclusive_group()
    settings_window.add_argument("--show-gui", action="store_true", help="GUI 설정 창 표시")
    settings_window.add_argument("--close", action="store_true", help="GUI 설정 창 닫기")
    settings.add_argument(
        "--tab",
        choices=("general", "network", "display", "advanced", "provider"),
        default="general",
        help="GUI에서 처음 표시할 설정 탭",
    )
    settings.add_argument("--search", default="", help="설정 창에서 검색할 문구")

    set_settings = subparsers.add_parser("set-settings", help="일반 설정 일괄 변경")
    set_settings.add_argument("--output", help="기본 저장 폴더")
    set_settings.add_argument("--language", help="UI 언어 코드")
    set_settings.add_argument(
        "--folder-template",
        help="작품 폴더명 템플릿 ({author}, {group}, {title}, {site}, {id})",
    )
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
    set_settings.add_argument(
        "--view-mode", choices=("list", "icon"), help="작품 목록 또는 아이콘 보기"
    )
    set_settings.add_argument(
        "--thumbnails", choices=("on", "off"), help="작품 썸네일 표시"
    )
    set_settings.add_argument(
        "--thumbnail-size",
        choices=("small", "medium", "large"),
        help="작품 썸네일 크기",
    )
    set_settings.add_argument(
        "--always-on-top", choices=("on", "off"), help="창을 항상 위에 표시"
    )
    set_settings.add_argument("--opacity", type=int, help="창 불투명도 50~100")
    set_settings.add_argument("--ui-scale", type=int, help="UI 배율 75~200")
    set_settings.add_argument("--font", help="GUI 글꼴 이름")
    background_group = set_settings.add_mutually_exclusive_group()
    background_group.add_argument("--background", help="GUI 배경 이미지 경로")
    background_group.add_argument(
        "--clear-background", action="store_true", help="GUI 배경 이미지 해제"
    )
    proxy_group = set_settings.add_mutually_exclusive_group()
    proxy_group.add_argument("--proxy", help="HTTP/HTTPS/SOCKS 프록시 URL")
    proxy_group.add_argument("--clear-proxy", action="store_true", help="프록시 해제")
    set_settings.add_argument(
        "--speed-limit-kib", type=int, help="전체 이미지 속도 제한 KiB/s; 0은 무제한"
    )
    set_settings.add_argument(
        "--quick-actions",
        help="빠른 실행 동작 ID를 쉼표로 구분한 표시 순서",
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

    folder_template = subparsers.add_parser(
        "folder-template", help="작품 폴더명 템플릿 미리보기와 경로 검증"
    )
    folder_template.add_argument("--template", help="검사할 템플릿; 생략 시 현재 설정")
    folder_template.add_argument("--author", default="이요미네 츠쿠")
    folder_template.add_argument("--group", default="N／A")
    folder_template.add_argument(
        "--title",
        default="이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건",
    )
    folder_template.add_argument("--site", default="마나토끼")
    folder_template.add_argument("--id", default="34360")
    folder_template.add_argument("--output", help="충돌까지 확인할 저장 루트")
    folder_template.add_argument("--json", action="store_true", help="JSON으로 출력")

    language = subparsers.add_parser("language", help="UI 언어 리소스 조회·설정")
    language_commands = language.add_subparsers(dest="language_command", required=True)
    language_list = language_commands.add_parser("list", help="설치된 UI 언어 목록")
    language_list.add_argument("--json", action="store_true", help="JSON으로 출력")
    language_status = language_commands.add_parser("status", help="현재 UI 언어")
    language_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    language_set = language_commands.add_parser("set", help="UI 언어 설정")
    language_set.add_argument("code", help="언어 코드")
    language_set.add_argument("--json", action="store_true", help="JSON으로 출력")

    browser_mode = subparsers.add_parser(
        "browser-mode", help="자동화 브라우저의 headless·진단 표시 정책"
    )
    browser_mode_commands = browser_mode.add_subparsers(
        dest="browser_mode_command", required=True
    )
    browser_mode_status = browser_mode_commands.add_parser("status", help="현재 정책")
    browser_mode_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    browser_mode_set = browser_mode_commands.add_parser("set", help="기본 정책 변경")
    browser_mode_set.add_argument("mode", choices=("headless", "visible"))
    browser_mode_set.add_argument("--json", action="store_true", help="JSON으로 출력")

    embedded_browser = subparsers.add_parser(
        "embedded-browser", help="선택형 메모리 전용 내장 브라우저"
    )
    embedded_browser_commands = embedded_browser.add_subparsers(
        dest="embedded_browser_command", required=True
    )
    embedded_capabilities = embedded_browser_commands.add_parser(
        "capabilities", help="설치 및 격리 상태"
    )
    embedded_capabilities.add_argument("--json", action="store_true", help="JSON으로 출력")
    embedded_plan = embedded_browser_commands.add_parser(
        "plan", help="외부 연결 없이 URL 이동 계획만 검사"
    )
    embedded_plan.add_argument("--url", required=True)
    embedded_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    embedded_manage = embedded_browser_commands.add_parser(
        "manage", help="GUI 내장 브라우저 창 제어"
    )
    embedded_manage_window = embedded_manage.add_mutually_exclusive_group(required=True)
    embedded_manage_window.add_argument("--show-gui", action="store_true")
    embedded_manage_window.add_argument("--close", action="store_true")
    embedded_manage.add_argument("--url", default="", help="주소창에 넣을 HTTPS URL")
    embedded_manage.add_argument(
        "--navigate", action="store_true", help="창을 열면서 실제 URL로 이동"
    )
    embedded_manage.add_argument("--yes", action="store_true", help="외부 네트워크 요청 확인")
    embedded_manage.add_argument("--json", action="store_true", help="JSON으로 출력")

    network_policy = subparsers.add_parser(
        "network-policy", help="프록시·속도 제한·공급자별 요청 정책"
    )
    network_commands = network_policy.add_subparsers(
        dest="network_command", required=True
    )
    network_status = network_commands.add_parser("status", help="현재 네트워크 정책")
    network_status.add_argument("--url", default="", help="공급자 정책까지 볼 작품 URL")
    network_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    network_set = network_commands.add_parser("set", help="네트워크 정책 변경")
    network_proxy_group = network_set.add_mutually_exclusive_group()
    network_proxy_group.add_argument("--proxy", help="HTTP/HTTPS/SOCKS 프록시 URL")
    network_proxy_group.add_argument("--clear-proxy", action="store_true")
    network_set.add_argument("--speed-limit-kib", type=int)
    network_set.add_argument(
        "--provider", choices=("manatoki", "newtoki", "booktoki")
    )
    network_set.add_argument("--request-delay-ms", type=int)
    network_set.add_argument("--backoff", type=int)
    network_set.add_argument("--json", action="store_true", help="JSON으로 출력")

    proxy_auth = subparsers.add_parser(
        "proxy-auth", help="OS 보안 저장소의 프록시 인증 관리"
    )
    proxy_auth_commands = proxy_auth.add_subparsers(
        dest="proxy_auth_command", required=True
    )
    proxy_auth_capabilities = proxy_auth_commands.add_parser(
        "capabilities", help="보안 저장소 상태"
    )
    proxy_auth_capabilities.add_argument("--json", action="store_true", help="JSON으로 출력")
    proxy_auth_status = proxy_auth_commands.add_parser(
        "status", help="저장된 프록시 인증 메타데이터"
    )
    proxy_auth_status.add_argument("--proxy", help="일치 여부를 확인할 프록시 URL")
    proxy_auth_status.add_argument("--yes", action="store_true", help="보안 저장소 읽기 확인")
    proxy_auth_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    proxy_auth_set = proxy_auth_commands.add_parser(
        "set", help="프록시 인증을 OS 보안 저장소에 저장"
    )
    proxy_auth_set.add_argument("--proxy", help="인증을 묶을 프록시 URL; 생략 시 현재 설정")
    proxy_auth_set.add_argument("--username", required=True)
    proxy_auth_set.add_argument(
        "--password-stdin",
        action="store_true",
        help="대화형 입력 대신 표준 입력 첫 줄에서 비밀번호 읽기",
    )
    proxy_auth_set.add_argument("--yes", action="store_true", help="민감 정보 저장 확인")
    proxy_auth_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    proxy_auth_clear = proxy_auth_commands.add_parser(
        "clear", help="저장된 프록시 인증 삭제"
    )
    proxy_auth_clear.add_argument("--yes", action="store_true", help="삭제 확인")
    proxy_auth_clear.add_argument("--json", action="store_true", help="JSON으로 출력")
    proxy_auth_manage = proxy_auth_commands.add_parser(
        "manage", help="GUI 프록시 인증 창 제어"
    )
    proxy_auth_manage_window = proxy_auth_manage.add_mutually_exclusive_group(required=True)
    proxy_auth_manage_window.add_argument("--show-gui", action="store_true")
    proxy_auth_manage_window.add_argument("--close", action="store_true")
    proxy_auth_manage.add_argument("--json", action="store_true", help="JSON으로 출력")

    public_ip = subparsers.add_parser("public-ip", help="외부 서비스로 공인 IP 확인")
    public_ip_commands = public_ip.add_subparsers(dest="public_ip_command", required=True)
    public_ip_plan = public_ip_commands.add_parser("plan", help="네트워크 요청 계획만 조회")
    public_ip_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    public_ip_check = public_ip_commands.add_parser("check", help="사용자 확인 후 실제 조회")
    public_ip_check.add_argument("--yes", action="store_true", help="외부 요청 확인")
    public_ip_check.add_argument("--json", action="store_true", help="JSON으로 출력")

    cookies = subparsers.add_parser("cookies", help="OS 보안 저장소의 공급자 쿠키 관리")
    cookie_commands = cookies.add_subparsers(dest="cookie_command", required=True)
    cookie_capabilities = cookie_commands.add_parser("capabilities", help="보안 저장소 상태")
    cookie_capabilities.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_policy = cookie_commands.add_parser("policy", help="공급자 쿠키 정책 조회")
    cookie_policy.add_argument("--provider", required=True, choices=COOKIE_PROVIDERS)
    cookie_policy.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_plan = cookie_commands.add_parser("plan-import", help="파일을 저장하지 않고 검사")
    cookie_plan.add_argument("--provider", required=True, choices=COOKIE_PROVIDERS)
    cookie_plan.add_argument("--input", required=True)
    cookie_plan.add_argument("--yes", action="store_true", help="민감한 쿠키 파일 읽기 확인")
    cookie_plan.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_status = cookie_commands.add_parser("status", help="저장된 쿠키 메타데이터")
    cookie_status.add_argument("--provider", required=True, choices=COOKIE_PROVIDERS)
    cookie_status.add_argument("--yes", action="store_true", help="보안 저장소 읽기 확인")
    cookie_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_import = cookie_commands.add_parser("import", help="쿠키를 OS 보안 저장소에 저장")
    cookie_import.add_argument("--provider", required=True, choices=COOKIE_PROVIDERS)
    cookie_import.add_argument("--input", required=True)
    cookie_import.add_argument("--yes", action="store_true", help="민감 정보 저장 확인")
    cookie_import.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_export = cookie_commands.add_parser("export", help="쿠키 값을 JSON 파일로 내보내기")
    cookie_export.add_argument("--provider", required=True, choices=COOKIE_PROVIDERS)
    cookie_export.add_argument("--output", required=True)
    cookie_export.add_argument("--yes", action="store_true", help="평문 민감 파일 생성 확인")
    cookie_export.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_clear = cookie_commands.add_parser("clear", help="OS 보안 저장소 쿠키 삭제")
    cookie_clear.add_argument("--provider", required=True, choices=COOKIE_PROVIDERS)
    cookie_clear.add_argument("--yes", action="store_true", help="삭제 확인")
    cookie_clear.add_argument("--json", action="store_true", help="JSON으로 출력")
    cookie_manage = cookie_commands.add_parser("manage", help="GUI 쿠키 관리 창 제어")
    cookie_manage.add_argument(
        "--provider", default="manatoki", choices=COOKIE_PROVIDERS
    )
    cookie_manage_window = cookie_manage.add_mutually_exclusive_group(required=True)
    cookie_manage_window.add_argument("--show-gui", action="store_true")
    cookie_manage_window.add_argument("--close", action="store_true")
    cookie_manage.add_argument("--json", action="store_true", help="JSON으로 출력")

    completion_action = subparsers.add_parser(
        "completion-action", help="모든 작업 완료 후 동작 조회·설정·미리보기"
    )
    completion_commands = completion_action.add_subparsers(
        dest="completion_command", required=True
    )
    completion_status = completion_commands.add_parser("status", help="현재 정책 조회")
    completion_status.add_argument("--json", action="store_true", help="JSON으로 출력")
    completion_set = completion_commands.add_parser("set", help="완료 후 동작 저장")
    completion_set.add_argument(
        "--action", choices=("none", "exit", "shutdown"), required=True
    )
    completion_set.add_argument("--countdown", type=int, default=15)
    completion_set.add_argument("--json", action="store_true", help="JSON으로 출력")
    completion_preview = completion_commands.add_parser(
        "preview", help="실제 종료 없이 카운트다운 정책 점검"
    )
    completion_preview.add_argument(
        "--action", choices=("exit", "shutdown"), required=True
    )
    completion_preview.add_argument("--countdown", type=int, default=15)
    completion_preview.add_argument("--show-gui", action="store_true")
    completion_preview.add_argument("--json", action="store_true", help="JSON으로 출력")
    completion_commands.add_parser("cancel", help="열린 카운트다운 취소")

    clipboard = subparsers.add_parser(
        "clipboard", help="클립보드 작품 URL 판정과 감지 설정"
    )
    clipboard_commands = clipboard.add_subparsers(
        dest="clipboard_command", required=True
    )
    clipboard_inspect = clipboard_commands.add_parser(
        "inspect", help="텍스트의 지원 작품 URL과 중복 여부 검사"
    )
    clipboard_inspect.add_argument("--text", required=True)
    clipboard_inspect.add_argument("--via-gui", action="store_true")
    clipboard_inspect.add_argument("--json", action="store_true")
    clipboard_monitor = clipboard_commands.add_parser(
        "monitor", help="클립보드 URL 감지 켜기 또는 끄기"
    )
    clipboard_monitor.add_argument("--state", choices=("on", "off"), required=True)
    clipboard_monitor.add_argument(
        "--mode", choices=("auto", "confirm"), help="자동 추가 또는 확인 후 추가 (생략하면 기존 방식 유지)"
    )
    clipboard_monitor.add_argument("--json", action="store_true")
    clipboard_status = clipboard_commands.add_parser("status", help="감지·자동 추가 설정과 최근 처리 결과")
    clipboard_status.add_argument("--json", action="store_true")
    clipboard_enqueue = clipboard_commands.add_parser(
        "enqueue", help="클립보드와 동일한 URL 검사 후 새 작품 등록 또는 기존 작품 새 회차 확인"
    )
    clipboard_enqueue.add_argument("--text", required=True)
    clipboard_enqueue.add_argument("--yes", action="store_true", help="실제 다운로드 등록 승인")
    clipboard_enqueue.add_argument("--json", action="store_true")

    tray = subparsers.add_parser("tray", help="GUI 시스템 트레이 제어")
    tray.add_argument(
        "action",
        choices=("status", "show", "hide", "notify"),
        help="트레이 상태 조회, 창 표시/숨김 또는 테스트 알림",
    )
    tray.add_argument("--message", default="tokiDownloader 테스트 알림", help="테스트 알림 내용")

    notifications = subparsers.add_parser(
        "notifications", help="작업 결과 알림음과 메시지 설정·미리보기"
    )
    notification_commands = notifications.add_subparsers(
        dest="notification_command", required=True
    )
    notification_status = notification_commands.add_parser(
        "status", help="현재 작업 결과 알림 설정"
    )
    notification_status.add_argument("--json", action="store_true")
    notification_set = notification_commands.add_parser(
        "set", help="완료·오류 알림, 소리와 메시지 상자 설정"
    )
    notification_set.add_argument("--complete", choices=("on", "off"))
    notification_set.add_argument("--error", choices=("on", "off"))
    notification_set.add_argument("--sound", choices=("none", "system"))
    notification_set.add_argument("--message-box", choices=("on", "off"))
    notification_set.add_argument("--json", action="store_true")
    notification_preview = notification_commands.add_parser(
        "preview", help="실행 중 GUI로 결과 알림 미리보기"
    )
    notification_preview.add_argument(
        "--kind", choices=("complete", "error"), default="complete"
    )
    notification_preview.add_argument("--title", default="알림 미리보기 작품")
    notification_preview.add_argument("--detail", default="테스트 오류")
    notification_preview.add_argument("--json", action="store_true")
    notification_close = notification_commands.add_parser(
        "close", help="열린 알림 메시지 상자 닫기"
    )
    notification_close.add_argument("--json", action="store_true")

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

    rename_episodes = subparsers.add_parser(
        "rename-episodes",
        help="회차 폴더명을 6자리 정렬 순번 + 전체 작품명 + 회차 표기로 정리",
    )
    rename_episodes.add_argument("--job", required=True, help="작업 ID")
    rename_episode_mode = rename_episodes.add_mutually_exclusive_group()
    rename_episode_mode.add_argument(
        "--dry-run", action="store_true", help="이름을 바꾸지 않고 충돌과 매핑만 확인"
    )
    rename_episode_mode.add_argument(
        "--execute", action="store_true", help="회차 폴더명을 실제로 변경"
    )
    rename_episodes.add_argument(
        "--yes", action="store_true", help="기존 폴더와 상태 파일 변경 확인"
    )
    rename_episodes.add_argument("--json", action="store_true", help="JSON으로 출력")

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
    verify_files.add_argument("--job", help="작업 ID")
    verify_files.add_argument(
        "--issue-limit", type=int, default=500, help="JSON에 포함할 문제 항목 수(최대 10000)"
    )
    verify_window = verify_files.add_mutually_exclusive_group()
    verify_window.add_argument(
        "--show-gui", action="store_true", help="GUI 별도 프로세스 검사와 결과 창 표시"
    )
    verify_window.add_argument(
        "--close", action="store_true", help="열린 GUI 파일 검사 결과 창 닫기"
    )
    verify_files.add_argument(
        "--ascii-json", action="store_true", help=argparse.SUPPRESS
    )
    verify_files.add_argument("--json", action="store_true", help="JSON으로 출력")

    preview = subparsers.add_parser(
        "preview",
        help="작품 회차의 이미지 목록 조회 또는 GUI 미리보기",
    )
    preview.add_argument("--job", help="작업 ID")
    preview.add_argument("--episode", type=int, help="회차 번호(생략 시 첫 보유 회차)")
    preview_identity = preview.add_mutually_exclusive_group()
    preview_identity.add_argument("--episode-id", help="미리 볼 회차의 sourceId")
    preview_identity.add_argument("--episode-folder", help="미리 볼 회차의 정확한 폴더명")
    preview.add_argument("--limit", type=int, default=200, help="가져올 이미지 수(최대 1000)")
    preview.add_argument("--offset", type=int, default=0, help="건너뛸 이미지 수")
    preview_window = preview.add_mutually_exclusive_group()
    preview_window.add_argument(
        "--show-gui", action="store_true", help="GUI 이미지 미리보기 창 표시"
    )
    preview_window.add_argument(
        "--close", action="store_true", help="열린 GUI 이미지 미리보기 창 닫기"
    )
    preview.add_argument("--json", action="store_true", help="JSON으로 출력")
    preview.add_argument("--ascii-json", action="store_true", help=argparse.SUPPRESS)

    convert_images = subparsers.add_parser(
        "convert-images",
        help="원본을 보존하고 _converted 폴더에 이미지 형식 변환",
    )
    convert_images.add_argument("--job", help="작업 ID")
    convert_images.add_argument(
        "--format", choices=("jpg", "jpeg", "png", "webp"), help="대상 형식"
    )
    convert_images.add_argument("--quality", type=int, default=90, help="JPG/WebP 품질(1~100)")
    convert_images.add_argument(
        "--max-width", type=int, help="비율을 유지할 최대 너비; 0은 제한 없음"
    )
    convert_images.add_argument(
        "--max-height", type=int, help="비율을 유지할 최대 높이; 0은 제한 없음"
    )
    conversion_exclusions = convert_images.add_mutually_exclusive_group()
    conversion_exclusions.add_argument(
        "--exclude-ext",
        action="append",
        help="이번 변환에서 제외할 이미지 확장자; 반복 또는 쉼표 구분",
    )
    conversion_exclusions.add_argument(
        "--include-all-types",
        action="store_true",
        help="저장된 확장자 제외 설정을 이번 변환에서 무시",
    )
    convert_mode = convert_images.add_mutually_exclusive_group()
    convert_mode.add_argument("--dry-run", action="store_true", help="변환 대상과 충돌만 확인")
    convert_mode.add_argument("--execute", action="store_true", help="별도 폴더에 실제 변환")
    convert_images.add_argument("--yes", action="store_true", help="대량 새 파일 생성 확인")
    conversion_window = convert_images.add_mutually_exclusive_group()
    conversion_window.add_argument(
        "--show-gui", action="store_true", help="GUI 확인/변환 창 표시"
    )
    conversion_window.add_argument(
        "--close", action="store_true", help="열린 GUI 변환 계획 창 닫기"
    )
    convert_images.add_argument("--json", action="store_true", help="JSON으로 출력")
    convert_images.add_argument(
        "--progress-json",
        action="store_true",
        help="진행 이벤트와 최종 결과를 줄 단위 JSON으로 출력",
    )
    convert_images.add_argument("--ascii-json", action="store_true", help=argparse.SUPPRESS)

    image_processing = subparsers.add_parser(
        "image-processing", help="이미지 리사이즈와 변환 제외 유형 기본값"
    )
    image_processing_commands = image_processing.add_subparsers(
        dest="image_processing_command", required=True
    )
    image_processing_status = image_processing_commands.add_parser(
        "status", help="현재 이미지 후처리 기본값"
    )
    image_processing_status.add_argument("--json", action="store_true")
    image_processing_set = image_processing_commands.add_parser(
        "set", help="리사이즈 상한과 제외 확장자 저장"
    )
    image_processing_set.add_argument("--max-width", type=int)
    image_processing_set.add_argument("--max-height", type=int)
    exclusion_update = image_processing_set.add_mutually_exclusive_group()
    exclusion_update.add_argument(
        "--exclude", help="제외 확장자를 쉼표 또는 세미콜론으로 구분"
    )
    exclusion_update.add_argument(
        "--clear-exclusions", action="store_true", help="제외 확장자 모두 해제"
    )
    image_processing_set.add_argument("--json", action="store_true")

    pdf_parser = subparsers.add_parser(
        "pdf", help="회차별 PDF 생성 정책·계획·실행"
    )
    pdf_commands = pdf_parser.add_subparsers(dest="pdf_command", required=True)
    pdf_status = pdf_commands.add_parser("status", help="PDF 자동 생성 설정과 의존성 조회")
    pdf_status.add_argument("--json", action="store_true")
    pdf_set = pdf_commands.add_parser("set", help="다운로드 완료 후 PDF 자동 생성 설정")
    pdf_set.add_argument(
        "--automatic", choices=("on", "off"), required=True, help="자동 생성 사용 여부"
    )
    pdf_set.add_argument("--json", action="store_true")
    pdf_plan = pdf_commands.add_parser("plan", help="파일을 만들지 않고 회차별 PDF 계획 조회")
    pdf_plan.add_argument("--job", required=True, help="작업 ID")
    pdf_plan.add_argument("--json", action="store_true")
    pdf_plan.add_argument("--ascii-json", action="store_true", help=argparse.SUPPRESS)
    pdf_generate = pdf_commands.add_parser("generate", help="회차별 PDF 미리보기 또는 생성")
    pdf_generate.add_argument("--job", required=True, help="작업 ID")
    pdf_generate_mode = pdf_generate.add_mutually_exclusive_group()
    pdf_generate_mode.add_argument("--execute", action="store_true", help="_pdf 폴더에 실제 생성")
    pdf_generate_mode.add_argument("--show-gui", action="store_true", help="GUI 생성 확인 창 표시")
    pdf_generate.add_argument("--yes", action="store_true", help="PDF 새 파일 생성 확인")
    pdf_generate.add_argument("--json", action="store_true")
    pdf_generate.add_argument("--ascii-json", action="store_true", help=argparse.SUPPRESS)
    pdf_generate.add_argument(
        "--progress-json",
        action="store_true",
        help="진행 이벤트와 최종 결과를 줄 단위 JSON으로 출력",
    )
    pdf_cancel = pdf_commands.add_parser("cancel", help="GUI에서 실행 중인 PDF 생성 중지")
    pdf_cancel.add_argument("--job", required=True, help="작업 ID")
    pdf_cancel.add_argument("--json", action="store_true")
    pdf_close = pdf_commands.add_parser("close", help="GUI PDF 계획/진행 창 닫기")
    pdf_close.add_argument("--json", action="store_true")

    cancel_conversion = subparsers.add_parser(
        "cancel-conversion",
        help="GUI에서 실행 중인 이미지 변환 중지",
    )
    cancel_conversion.add_argument("--job", required=True, help="작업 ID")

    copy_link = subparsers.add_parser("copy-link", help="작품 원본 링크 복사")
    copy_link.add_argument("--job", help="작업 ID")
    copy_id = subparsers.add_parser("copy-id", help="작품 작업 ID 복사")
    copy_id.add_argument("--job", help="작업 ID")
    copy_path = subparsers.add_parser("copy-path", help="작품 저장 폴더 경로 복사")
    copy_path.add_argument("--job", help="작업 ID")
    copy_title = subparsers.add_parser("copy-title", help="작품명 복사")
    copy_title.add_argument("--job", help="작업 ID")
    job_menu = subparsers.add_parser("job-menu", help="선택 작품의 우클릭 메뉴 표시")
    job_menu.add_argument("--job", help="작업 ID")
    job_menu.add_argument(
        "--inspect",
        action="store_true",
        help="메뉴를 띄우지 않고 현재 항목·순서·활성 상태를 JSON으로 확인",
    )

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
    from toki_library_cli import configure_library_cli
    configure_library_cli(subparsers)
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if args.command == "library":
        from toki_library_cli import run_library_cli
        return run_library_cli(args, sys.modules[__name__])
    command = args.command
    if command == "download":
        provider = detect_download_provider(args.url)
        if args.simulate and provider != "youtube":
            raise ValueError("--simulate은 YouTube 작업에서만 사용할 수 있습니다.")
        if provider == "youtube" and not args.simulate and not args.confirm_external:
            raise ValueError("YouTube 외부 요청 실행에는 --confirm-external이 필요합니다.")
        if provider == "youtube":
            scan_mode, start, last = "new", None, None
        else:
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
                "simulation": args.simulate,
                "externalRequestConfirmed": args.confirm_external,
            }
        )
        print(f"작업 추가: {result['job_id']}")
        return 0
    if command == "show":
        ensure_gui_running()
        control_request({"action": "show"})
        return 0
    if command == "app-identity":
        if args.show_gui or args.close or args.via_gui:
            ensure_gui_running()
        if args.show_gui or args.close:
            result = control_request(
                {
                    "action": (
                        "show_application_identity"
                        if args.show_gui
                        else "close_application_identity"
                    )
                }
            )
        else:
            result = (
                control_request({"action": "application_identity"})
                if args.via_gui
                else application_identity_snapshot()
            )
        if args.json:
            print_json(result)
        elif args.show_gui:
            print("앱 정보 창을 열었습니다.")
        elif args.close:
            print(
                "앱 정보 창을 닫았습니다."
                if result.get("closed")
                else "앱 정보 창은 이미 닫혀 있습니다."
            )
        else:
            print(
                f"{result.get('displayName', 'tokiDownloader')} | AppUserModelID: "
                f"{result.get('windowsAppUserModelId', '')} | 아이콘: "
                f"{'정상' if result.get('iconExists') else '없음'} | 적용: "
                f"{'예' if result.get('applied') else '아니요'}"
            )
        return 0 if result.get("ok", bool(args.show_gui or args.close)) else 2
    if command == "doctor":
        if args.show_gui or args.close:
            ensure_gui_running()
            result = control_request(
                {"action": "show_doctor" if args.show_gui else "close_doctor"}
            )
        else:
            result = dependency_diagnostics()
        report = result.get("report") if isinstance(result.get("report"), dict) else result
        if args.json:
            print_json(result)
        else:
            for item in report.get("checks") or []:
                state = "정상" if item["available"] else "없음"
                version = f" {item['version']}" if item.get("version") else ""
                print(f"[{item['kind']}] {item['name']}: {state}{version}")
            required = report.get("required") or {}
            if required:
                print(f"필수 환경: {required['passed']}/{required['total']} 통과")
            elif result.get("closed"):
                print("환경 진단창을 닫았습니다.")
        default_success = bool(args.show_gui or args.close)
        return 0 if bool(report.get("ok", default_success)) else 2
    if command == "migrate":
        if args.migrate_command == "apply":
            result = {
                "config": apply_config_migrations(),
                "database": apply_database_migrations(),
            }
        else:
            result = {
                "config": config_schema_status(),
                "database": database_schema_status(),
            }
        result["ok"] = all(item.get("ok", False) for item in result.values())
        if args.json:
            print_json(result)
        else:
            print(
                f"설정 v{result['config'].get('after', result['config']).get('version', 0)}/"
                f"{result['config'].get('after', result['config']).get('currentVersion', 0)} | "
                f"DB v{result['database'].get('after', result['database']).get('version', 0)}/"
                f"{result['database'].get('after', result['database']).get('currentVersion', 0)}"
            )
        return 0 if result["ok"] else 2
    if command == "diagnostics":
        if args.via_gui:
            ensure_gui_running()
            result = control_request(
                {"action": "export_diagnostics", "output": args.output or ""}
            )
        else:
            result = export_diagnostics(Path(args.output) if args.output else None)
        if args.json or args.via_gui:
            print_json(result)
        else:
            print(f"진단 묶음: {result['path']} ({int(result['bytes']):,} bytes)")
        return 0 if result.get("ok") else 2
    if command == "config":
        if args.config_command == "get":
            settings = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            result = {
                "ok": True,
                "key": args.key or "",
                "value": settings[args.key] if args.key else settings,
            }
        elif args.config_command == "set":
            try:
                value = json.loads(args.value)
            except json.JSONDecodeError:
                value = args.value
            updated = (
                control_request(
                    {"action": "set_settings", "updates": {args.key: value}, "reset": False}
                )
                if gui_is_running()
                else update_app_settings({args.key: value})
            )
            result = {"ok": True, "key": args.key, "value": updated[args.key]}
        elif args.config_command == "export":
            result = export_app_settings(Path(args.output))
        elif args.config_command == "import":
            if args.execute and not args.yes:
                raise ValueError("설정을 적용하려면 --execute --yes를 함께 지정하세요.")
            result = (
                control_request(
                    {
                        "action": "import_settings",
                        "input": args.input,
                        "execute": True,
                    }
                )
                if args.execute and gui_is_running()
                else import_app_settings(Path(args.input), execute=bool(args.execute))
            )
        else:
            if args.execute and not args.yes:
                raise ValueError("설정을 초기화하려면 --execute --yes를 함께 지정하세요.")
            result = (
                control_request({"action": "reset_settings", "execute": True})
                if args.execute and gui_is_running()
                else reset_app_settings(execute=bool(args.execute))
            )
        if args.json:
            print_json(result)
        elif args.config_command == "get" and args.key:
            print(result["value"])
        else:
            print_json(result)
        return 0 if result.get("ok") else 2
    if command == "jobs":
        if args.jobs_command == "export":
            if args.via_gui:
                ensure_gui_running()
                result = control_request(
                    {"action": "export_jobs_snapshot", "output": args.output}
                )
            else:
                result = export_jobs_snapshot(Path(args.output))
        else:
            if args.close:
                ensure_gui_running()
                result = control_request({"action": "close_jobs_snapshot_import"})
                print_json(result)
                return 0
            if not args.input:
                raise ValueError("작업 스냅샷 JSON 경로를 --input으로 지정하세요.")
            if args.show_gui:
                ensure_gui_running()
                result = control_request(
                    {"action": "show_jobs_snapshot_import", "input": args.input}
                )
                print_json(result)
                return 0
            if args.execute and not args.yes:
                raise ValueError("작업 기록을 가져오려면 --execute --yes를 함께 지정하세요.")
            if args.via_gui:
                ensure_gui_running()
                result = control_request(
                    {
                        "action": "import_jobs_snapshot",
                        "input": args.input,
                        "execute": bool(args.execute),
                    }
                )
            else:
                result = import_jobs_snapshot(
                    Path(args.input), execute=bool(args.execute)
                )
        if args.json or args.via_gui:
            print_json(result)
        elif args.jobs_command == "export":
            print(
                f"작업 스냅샷: {result['path']} · 작품 {result['jobCount']} · "
                f"실행 {result['runCount']}"
            )
        else:
            print(
                f"작품 추가 {result['pendingJobs']} · 실행 기록 추가 {result['pendingRuns']} · "
                f"기존 작품 건너뜀 {result['skippedExistingWorks']}"
            )
        return 0 if result.get("ok") else 2
    if command == "group":
        if args.group_command == "manage":
            ensure_gui_running()
            action = "show_group_manager" if args.show_gui else "close_group_manager"
            result = control_request({"action": action})
            print_json(result)
            return 0
        use_gui = gui_is_running()
        if args.group_command == "list":
            groups = (
                control_request({"action": "groups"})["groups"]
                if use_gui
                else list_work_collections()
            )
            result = {"ok": True, "count": len(groups), "groups": groups}
        elif args.group_command == "create":
            result = (
                control_request({"action": "create_group", "name": args.name})
                if use_gui
                else create_work_collection(args.name)
            )
            result = {"ok": True, **result}
        elif args.group_command == "rename":
            result = (
                control_request(
                    {"action": "rename_group", "groupId": args.group, "name": args.name}
                )
                if use_gui
                else rename_work_collection(args.group, args.name)
            )
            result = {"ok": True, **result}
        else:
            group_id = args.group if args.group_command == "assign" else None
            result = (
                control_request(
                    {"action": "assign_group", "jobId": args.job, "groupId": group_id or ""}
                )
                if use_gui
                else assign_job_to_collection(args.job, group_id)
            )
        if getattr(args, "json", False):
            print_json(result)
        elif args.group_command == "list":
            for group in result["groups"]:
                print(f"{group['groupId']} | {group['name']} | {group['memberCount']}개")
        elif args.group_command in {"create", "rename"}:
            print(f"{result['groupId']} | {result['name']}")
        else:
            print(result["group"]["name"] if result.get("group") else "미분류")
        return 0 if result.get("ok", True) else 2
    if command == "local":
        if args.close:
            ensure_gui_running()
            result = control_request({"action": "close_archive_inspection"})
            print_json(result)
            return 0
        if not args.path:
            raise ValueError("검사할 압축 파일을 --path로 지정하세요.")
        if args.show_gui:
            ensure_gui_running()
            result = control_request(
                {"action": "show_archive_inspection", "path": args.path}
            )
            print_json(result)
            return 0
        result = inspect_local_archive(Path(args.path))
        if args.json:
            print_json(result)
        else:
            print(
                f"{result['format']} | 파일 {result['fileCount']} | "
                f"이미지 {result['imageCount']} | 의심 경로 {result['suspiciousPathCount']}"
            )
        return 0 if result.get("ok") else 2
    if command == "archive-viewer":
        if args.archive_viewer_command == "status":
            result = (
                control_request({"action": "archive_viewer_policy"})
                if gui_is_running()
                else archive_viewer_policy_snapshot()
            )
        elif args.archive_viewer_command == "set":
            updates: dict[str, Any] = {}
            if args.mode:
                updates["archiveViewerMode"] = args.mode
            if args.path is not None:
                updates["archiveViewerPath"] = args.path
            elif args.clear_path:
                updates["archiveViewerPath"] = ""
            if not updates:
                raise ValueError("--mode, --path 또는 --clear-path 중 하나를 지정하세요.")
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request({"action": "archive_viewer_policy"})
            else:
                saved = update_app_settings(updates)
                result = archive_viewer_policy_snapshot(saved)
        else:
            if args.execute and not args.yes:
                raise ValueError(
                    "압축 파일 연결 프로그램을 실행하려면 --execute --yes를 함께 지정하세요."
                )
            result = open_archive_with_viewer(
                Path(args.path), execute=bool(args.execute)
            )
        if args.json:
            print_json(result)
        elif args.archive_viewer_command == "open":
            state = "실행함" if result["executed"] else "실행 전 미리보기"
            print(f"{state} | {result['viewerLabel']} | {result['path']}")
        else:
            print_json(result)
        return 0 if result.get("ok", result.get("available", True)) else 2
    if command == "persistence":
        if args.persistence_command == "status":
            result = (
                control_request({"action": "persistence_status"})
                if gui_is_running()
                else {
                    "ok": True,
                    "policy": persistence_policy_snapshot(),
                    "recovery": recover_interrupted_jobs(execute=False),
                    "guiRunning": False,
                }
            )
        elif args.persistence_command == "set":
            updates: dict[str, Any] = {}
            if args.autosave_seconds is not None:
                updates["autosaveIntervalSeconds"] = args.autosave_seconds
            if args.startup_recovery is not None:
                updates["recoverInterruptedOnStartup"] = (
                    args.startup_recovery == "on"
                )
            if not updates:
                raise ValueError(
                    "--autosave-seconds 또는 --startup-recovery를 지정하세요."
                )
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request({"action": "persistence_status"})
            else:
                saved = update_app_settings(updates)
                result = {
                    "ok": True,
                    "policy": persistence_policy_snapshot(saved),
                    "recovery": recover_interrupted_jobs(execute=False),
                    "guiRunning": False,
                }
        else:
            if args.close or args.show_gui:
                ensure_gui_running()
                action = (
                    "close_recovery_dialog"
                    if args.close
                    else "show_recovery_dialog"
                )
                result = control_request({"action": action})
            else:
                if args.execute and not args.yes:
                    raise ValueError(
                        "불완전 기록을 복구하려면 --execute --yes를 함께 지정하세요."
                    )
                result = (
                    control_request(
                        {
                            "action": "recover_interrupted",
                            "execute": bool(args.execute),
                        }
                    )
                    if gui_is_running()
                    else recover_interrupted_jobs(execute=bool(args.execute))
                )
        if (
            args.json
            or args.persistence_command != "recover"
            or getattr(args, "show_gui", False)
            or getattr(args, "close", False)
        ):
            print_json(result)
        else:
            print(
                f"{'복구 완료' if result.get('executed') else '복구 미리보기'} | "
                f"작품 {result.get('jobCount', 0)} | 실행 {result.get('runCount', 0)}"
            )
        return 0 if result.get("ok", True) else 2
    if command == "list-performance":
        if args.list_performance_command == "status":
            result = (
                control_request({"action": "list_performance_status"})
                if gui_is_running()
                else {"ok": True, **list_performance_policy_snapshot()}
            )
        else:
            updates: dict[str, Any] = {}
            mappings = (
                ("listPageSize", args.page_size),
                ("listLoadedLimit", args.loaded_limit),
                ("listScrollLines", args.scroll_lines),
            )
            for key, value in mappings:
                if value is not None:
                    updates[key] = value
            if args.lazy_loading is not None:
                updates["listLazyLoading"] = args.lazy_loading == "on"
            if args.low_spec is not None:
                updates["lowSpecMode"] = args.low_spec == "on"
            if not updates:
                raise ValueError(
                    "--page-size, --loaded-limit, --scroll-lines, --lazy-loading 또는 "
                    "--low-spec 중 하나를 지정하세요."
                )
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request({"action": "list_performance_status"})
            else:
                saved = update_app_settings(updates)
                result = {"ok": True, **list_performance_policy_snapshot(saved)}
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "memory":
        if args.memory_command == "status":
            if not 0 <= args.child_limit <= 1000:
                raise ValueError("자식 프로세스 반환 수는 0~1000개여야 합니다.")
            result = (
                control_request(
                    {"action": "memory_status", "childLimit": args.child_limit}
                )
                if gui_is_running()
                else memory_usage_snapshot(child_limit=args.child_limit)
            )
        else:
            updates = {"memoryDisplayEnabled": args.display == "on"}
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request(
                    {"action": "memory_status", "childLimit": 200}
                )
            else:
                saved = update_app_settings(updates)
                result = memory_usage_snapshot(saved)
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "local-api":
        if args.local_api_command == "status":
            result = (
                control_request({"action": "local_api_status"})
                if gui_is_running()
                else {"ok": True, **local_api_policy_snapshot()}
            )
        elif args.local_api_command == "set":
            updates: dict[str, Any] = {}
            if args.state is not None:
                updates["localApiEnabled"] = args.state == "on"
            if args.port is not None:
                updates["localApiPort"] = args.port
            if not updates:
                raise ValueError("--state 또는 --port 중 하나 이상을 지정하세요.")
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request({"action": "local_api_status"})
            else:
                saved = update_app_settings(updates)
                result = {"ok": True, **local_api_policy_snapshot(saved)}
        elif args.local_api_command == "token":
            ensure_gui_running()
            if not args.yes:
                raise ControlError("토큰 표시·복사·재발급에는 --yes가 필요합니다.")
            result = control_request(
                {
                    "action": "local_api_token",
                    "reveal": bool(args.show),
                    "copy": bool(args.copy),
                    "rotate": bool(args.rotate),
                    "confirmed": True,
                }
            )
        else:
            ensure_gui_running()
            status = control_request({"action": "local_api_status"})
            if not status.get("running"):
                raise ControlError("로컬 HTTP API가 실행 중이 아닙니다.")
            secret = control_request(
                {
                    "action": "local_api_token",
                    "reveal": True,
                    "copy": False,
                    "rotate": False,
                    "confirmed": True,
                }
            )
            result = local_api_http_request(
                str(status.get("baseUrl") or ""),
                str(secret.get("token") or ""),
                method=args.method,
                path=args.path,
                body=args.body,
            )
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "hitomi":
        if args.hitomi_command == "status":
            result = hitomi_provider_capabilities()
        elif args.hitomi_command == "close":
            ensure_gui_running()
            result = control_request({"action": "close_hitomi_inspector"})
        elif args.hitomi_command == "server":
            current = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            if args.hitomi_server_command == "status":
                result = hitomi_server_policy_snapshot(current)
            elif args.hitomi_server_command == "plan":
                try:
                    result = plan_hitomi_server(
                        args.input,
                        provider_hint=args.provider,
                        config=current,
                    )
                except HitomiReferenceError as error:
                    result = error.to_dict()
            else:
                updates: dict[str, Any] = {}
                if args.mode is not None:
                    updates["hitomiServerMode"] = args.mode
                if args.manual_server is not None:
                    updates["hitomiManualServer"] = args.manual_server
                if args.priority is not None:
                    updates["hitomiServerPriority"] = args.priority
                if not updates:
                    raise ValueError(
                        "--mode, --manual-server 또는 --priority 중 하나 이상을 지정하세요."
                    )
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **hitomi_server_policy_snapshot(saved)}
        elif args.hitomi_command == "metadata":
            subcommand = args.hitomi_metadata_command
            if subcommand == "close":
                ensure_gui_running()
                result = control_request({"action": "close_hitomi_metadata"})
            elif subcommand == "show":
                ensure_gui_running()
                result = control_request(
                    {
                        "action": "show_hitomi_metadata",
                        "reference": args.input,
                        "provider": args.provider,
                        "fixture": str(args.fixture or ""),
                    }
                )
            else:
                current = (
                    control_request({"action": "settings"})
                    if gui_is_running()
                    else settings_snapshot()
                )
                if subcommand == "status":
                    result = hitomi_metadata_policy_snapshot(current)
                elif subcommand == "set":
                    updates = {"hitomiMetadataMode": args.mode}
                    saved = (
                        control_request(
                            {"action": "set_settings", "updates": updates, "reset": False}
                        )
                        if gui_is_running()
                        else update_app_settings(updates)
                    )
                    result = {"saved": True, **hitomi_metadata_policy_snapshot(saved)}
                elif subcommand == "decide":
                    result = evaluate_hitomi_metadata_outcome(
                        config=current,
                        outcome=args.outcome,
                        error_code=args.error_code,
                    )
                else:
                    try:
                        if subcommand == "plan":
                            result = hitomi_metadata_request_plan(
                                args.input,
                                provider_hint=args.provider,
                                config=current,
                            )
                        elif subcommand == "parse":
                            result = load_hitomi_metadata_fixture(
                                args.input,
                                Path(args.fixture),
                                provider_hint=args.provider,
                            )
                        else:
                            if not args.yes:
                                raise ControlError(
                                    "실제 공급자 메타데이터 요청에는 --yes가 필요합니다."
                                )
                            fetch_options: dict[str, Any] = {}
                            if args.use_cookies:
                                request_plan = hitomi_metadata_request_plan(
                                    args.input,
                                    provider_hint=args.provider,
                                    config=current,
                                )
                                request = request_plan.get("request") or {}
                                validate_hitomi_metadata_cookie_destination(
                                    str(request_plan["provider"]),
                                    str(request.get("url") or ""),
                                )
                                fetch_options["cookie_header"] = (
                                    provider_cookie_request_header(
                                        str(request_plan["provider"]),
                                        str(request.get("url") or ""),
                                    )
                                )
                            result = fetch_hitomi_metadata(
                                args.input,
                                provider_hint=args.provider,
                                config=current,
                                timeout=args.timeout,
                                confirmed=True,
                                **fetch_options,
                            )
                    except HitomiReferenceError as error:
                        result = error.to_dict()
                        if subcommand == "fetch":
                            result["metadataPolicy"] = evaluate_hitomi_metadata_outcome(
                                config=current,
                                outcome="failure",
                                error_code=error.code,
                            )
        elif args.hitomi_command == "filenames":
            current = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            subcommand = args.hitomi_filename_command
            if subcommand == "status":
                result = hitomi_filename_policy_snapshot(current)
            elif subcommand == "set":
                updates = {"hitomiFilenameMode": args.mode}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **hitomi_filename_policy_snapshot(saved)}
            else:
                try:
                    metadata = load_hitomi_metadata_fixture(
                        args.input,
                        Path(args.fixture),
                        provider_hint=args.provider,
                    )
                    result = plan_hitomi_image_filenames(
                        metadata,
                        config=current,
                        mode=args.mode,
                        sample_limit=args.sample_limit,
                    )
                except HitomiReferenceError as error:
                    result = error.to_dict()
        elif args.hitomi_command == "tags":
            current = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            subcommand = args.hitomi_tag_command
            if subcommand == "status":
                result = hitomi_excluded_tag_policy_snapshot(current)
            elif subcommand == "set":
                updates = {"hitomiExcludedTags": [] if args.clear else args.tags}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **hitomi_excluded_tag_policy_snapshot(saved)}
            else:
                try:
                    metadata = load_hitomi_metadata_fixture(
                        args.input,
                        Path(args.fixture),
                        provider_hint=args.provider,
                    )
                    result = evaluate_hitomi_excluded_tags(
                        metadata,
                        config=current,
                        rules=args.tags,
                    )
                except HitomiReferenceError as error:
                    result = error.to_dict()
        elif args.hitomi_command == "title":
            current = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            subcommand = args.hitomi_title_command
            if subcommand == "status":
                result = hitomi_title_policy_snapshot(current)
            elif subcommand == "set":
                updates = {
                    "hitomiPreferJapaneseTitle": args.prefer_japanese == "on"
                }
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **hitomi_title_policy_snapshot(saved)}
            else:
                try:
                    metadata = load_hitomi_metadata_fixture(
                        args.input,
                        Path(args.fixture),
                        provider_hint=args.provider,
                    )
                    result = select_hitomi_display_title(
                        metadata,
                        config=current,
                        prefer_japanese=(
                            None
                            if args.prefer_japanese is None
                            else args.prefer_japanese == "on"
                        ),
                    )
                except HitomiReferenceError as error:
                    result = error.to_dict()
        elif args.hitomi_command == "metadata-files":
            current = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            subcommand = args.hitomi_metadata_file_command
            if subcommand == "status":
                result = hitomi_metadata_file_policy_snapshot(current)
            elif subcommand == "set":
                updates = {"hitomiMetadataFileMode": args.mode}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **hitomi_metadata_file_policy_snapshot(saved)}
            else:
                try:
                    metadata = load_hitomi_metadata_fixture(
                        args.input,
                        Path(args.fixture),
                        provider_hint=args.provider,
                    )
                    if subcommand == "plan":
                        result = plan_hitomi_metadata_files(
                            metadata,
                            Path(args.output),
                            config=current,
                            mode=args.mode,
                        )
                    else:
                        if not args.yes:
                            raise ControlError(
                                "메타데이터 파일 저장에는 --yes가 필요합니다."
                            )
                        result = write_hitomi_metadata_files(
                            metadata,
                            Path(args.output),
                            config=current,
                            mode=args.mode,
                            overwrite=args.overwrite,
                        )
                except HitomiReferenceError as error:
                    result = error.to_dict()
        elif args.hitomi_command == "images":
            current = (
                control_request({"action": "settings"})
                if gui_is_running()
                else settings_snapshot()
            )
            subcommand = args.hitomi_image_command
            if subcommand == "status":
                result = hitomi_original_image_policy_snapshot(current)
            elif subcommand == "set":
                updates = {"hitomiUseOriginalImages": args.original == "on"}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **hitomi_original_image_policy_snapshot(saved)}
            else:
                try:
                    metadata = load_hitomi_metadata_fixture(
                        args.input,
                        Path(args.fixture),
                        provider_hint=args.provider,
                    )
                    result = plan_hitomi_image_sources(
                        metadata,
                        config=current,
                        use_original=(
                            None if args.original is None else args.original == "on"
                        ),
                        sample_limit=args.sample_limit,
                    )
                except HitomiReferenceError as error:
                    result = error.to_dict()
        elif args.show_gui:
            ensure_gui_running()
            result = control_request(
                {
                    "action": "show_hitomi_inspector",
                    "reference": args.input,
                    "provider": args.provider,
                }
            )
        else:
            try:
                result = inspect_hitomi_reference(
                    args.input,
                    provider_hint=args.provider,
                )
            except HitomiReferenceError as error:
                result = error.to_dict()
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "youtube":
        current = (
            control_request({"action": "settings"})
            if gui_is_running()
            else settings_snapshot()
        )
        if args.youtube_command == "mtime":
            if args.youtube_mtime_command == "status":
                result = youtube_mtime_policy_snapshot(current)
            elif args.youtube_mtime_command == "set":
                updates = {"youtubeApplyUploadDateMtime": args.state == "on"}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **youtube_mtime_policy_snapshot(saved)}
            else:
                enabled = None if args.state is None else args.state == "on"
                if args.youtube_mtime_command == "apply":
                    result = apply_youtube_upload_date_mtime(
                        args.file,
                        args.upload_date,
                        config=current,
                        enabled=enabled,
                        confirmed=args.yes,
                    )
                else:
                    result = plan_youtube_upload_date_mtime(
                        args.file, args.upload_date, config=current, enabled=enabled
                    )
            print_json(result)
            return 0
        if args.youtube_command == "chapters":
            embed = (
                None if args.youtube_chapter_command == "status" or args.embed is None
                else args.embed == "on"
            )
            if args.youtube_chapter_command == "status":
                result = youtube_chapter_policy_snapshot(current)
            elif args.youtube_chapter_command == "set":
                if embed is None:
                    raise ValueError("저장할 YouTube 챕터 마커 설정을 지정하세요.")
                updates = {"youtubeEmbedChapters": embed}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **youtube_chapter_policy_snapshot(saved)}
            else:
                plan_config = (
                    current if embed is None else {**current, "youtubeEmbedChapters": embed}
                )
                result = plan_youtube_format(args.input, plan_config)
            print_json(result)
            return 0
        if args.youtube_command == "collection":
            order = args.order if args.youtube_collection_command != "status" else None
            if args.youtube_collection_command == "status":
                result = youtube_collection_policy_snapshot(current)
            elif args.youtube_collection_command == "set":
                if order is None:
                    raise ValueError("저장할 YouTube 채널·재생목록 순서를 지정하세요.")
                updates = {"youtubeCollectionOrder": order}
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(updates)
                )
                result = {"saved": True, **youtube_collection_policy_snapshot(saved)}
            else:
                plan_config = (
                    current if order is None else {**current, "youtubeCollectionOrder": order}
                )
                result = plan_youtube_format(args.input, plan_config)
            print_json(result)
            return 0
        if args.youtube_command == "metadata":
            metadata_updates = {
                key: value == "on"
                for key, value in {
                    "youtubeWriteThumbnail": args.write_thumbnail,
                    "youtubeEmbedThumbnail": args.embed_thumbnail,
                    "youtubeWriteInfoJson": args.write_info_json,
                    "youtubeWriteDescription": args.write_description,
                    "youtubeEmbedMetadata": args.embed_metadata,
                }.items()
                if value is not None
            } if args.youtube_metadata_command != "status" else {}
            if args.youtube_metadata_command == "status":
                result = youtube_metadata_policy_snapshot(current)
            elif args.youtube_metadata_command == "set":
                if not metadata_updates:
                    raise ValueError("저장할 YouTube 썸네일·메타데이터 설정을 하나 이상 지정하세요.")
                saved = (
                    control_request(
                        {"action": "set_settings", "updates": metadata_updates, "reset": False}
                    )
                    if gui_is_running()
                    else update_app_settings(metadata_updates)
                )
                result = {"saved": True, **youtube_metadata_policy_snapshot(saved)}
            else:
                result = plan_youtube_format(args.input, {**current, **metadata_updates})
            print_json(result)
            return 0
        if args.youtube_command == "tracks":
            track_updates = {
                key: value
                for key, value in {
                    "youtubePreferredLanguages": args.languages,
                    "youtubeSubtitleMode": args.subtitles,
                    "youtubeSubtitleFormat": args.subtitle_format,
                    "youtubeEmbedSubtitles": (
                        None if args.embed_subtitles is None else args.embed_subtitles == "on"
                    ),
                    "youtubeAudioTrackMode": args.audio_tracks,
                }.items()
                if value is not None
            } if args.youtube_track_command != "status" else {}
            if args.youtube_track_command == "status":
                result = youtube_format_policy_snapshot(current)
            elif args.youtube_track_command == "set":
                if not track_updates:
                    raise ValueError("저장할 YouTube 트랙 설정을 하나 이상 지정하세요.")
                saved = (
                    control_request({"action": "set_settings", "updates": track_updates, "reset": False})
                    if gui_is_running()
                    else update_app_settings(track_updates)
                )
                result = {"saved": True, **youtube_format_policy_snapshot(saved)}
            else:
                result = plan_youtube_format(args.input, {**current, **track_updates})
            print_json(result)
            return 0
        if args.youtube_command == "filename":
            template = (
                args.template
                if getattr(args, "template", None) is not None
                else current["youtubeFilenameTemplate"]
            )
            if args.youtube_filename_command == "set":
                saved = (
                    control_request(
                        {
                            "action": "set_settings",
                            "updates": {"youtubeFilenameTemplate": template},
                            "reset": False,
                        }
                    )
                    if gui_is_running()
                    else update_app_settings({"youtubeFilenameTemplate": template})
                )
                result = {
                    "saved": True,
                    **preview_youtube_filename(saved["youtubeFilenameTemplate"]),
                }
            else:
                result = preview_youtube_filename(template)
            print_json(result)
            return 0
        updates = {
            key: value
            for key, value in {
                "youtubeFormatMode": args.mode,
                "youtubeMaxHeight": args.max_height,
                "youtubeContainer": args.container,
                "youtubeVideoCodec": args.video_codec,
                "youtubeAudioCodec": args.audio_codec,
            }.items()
            if value is not None
        } if args.youtube_format_command != "status" else {}
        if args.youtube_format_command == "status":
            result = youtube_format_policy_snapshot(current)
        elif args.youtube_format_command == "set":
            if not updates:
                raise ValueError("저장할 YouTube 형식 설정을 하나 이상 지정하세요.")
            saved = (
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                if gui_is_running()
                else update_app_settings(updates)
            )
            result = {"saved": True, **youtube_format_policy_snapshot(saved)}
        else:
            try:
                result = plan_youtube_format(args.input, {**current, **updates})
            except YouTubePolicyError as error:
                result = error.to_dict()
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "sleep-prevention":
        if args.sleep_prevention_command == "plan":
            if args.active_downloads < 0:
                raise ValueError("활성 다운로드 수는 0 이상이어야 합니다.")
            result = sleep_prevention_policy_snapshot(
                active_downloads=args.active_downloads
            )
        elif args.sleep_prevention_command == "status":
            result = (
                control_request({"action": "sleep_prevention_status"})
                if gui_is_running()
                else sleep_prevention_policy_snapshot()
            )
        else:
            updates = {
                "preventSleepDuringDownloads": args.state == "on"
            }
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request({"action": "sleep_prevention_status"})
            else:
                saved = update_app_settings(updates)
                result = sleep_prevention_policy_snapshot(saved)
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "duplicates":
        if args.close:
            ensure_gui_running()
            action = (
                "close_duplicate_works"
                if args.duplicates_command == "works"
                else "close_duplicate_images"
            )
            result = control_request({"action": action})
            print_json(result)
            return 0
        if args.duplicates_command == "images" and not args.job:
            raise ValueError("이미지 중복 검사 작업 ID를 --job으로 지정하세요.")
        if args.show_gui:
            ensure_gui_running()
            request = (
                {"action": "show_duplicate_works"}
                if args.duplicates_command == "works"
                else {
                    "action": "show_duplicate_images",
                    "jobId": args.job,
                    "algorithm": args.algorithm,
                }
            )
            result = control_request(request)
            print_json(result)
            return 0
        result = (
            find_duplicate_works()
            if args.duplicates_command == "works"
            else find_duplicate_images(args.job, algorithm=args.algorithm)
        )
        if args.json:
            print_json(result)
        else:
            if args.duplicates_command == "works":
                print(
                    f"검사 {result['scannedWorks']} · 중복 그룹 {result['duplicateGroupCount']} · "
                    f"관련 작품 {result['duplicateWorkCount']}"
                )
            else:
                print(
                    f"검사 {result['scannedImages']} · 중복 그룹 {result['duplicateGroupCount']} · "
                    f"관련 이미지 {result['duplicateImageCount']}"
                )
        return 0 if result.get("ok") else 2
    if command == "shortcuts":
        if args.keys is not None and not args.set:
            raise ControlError("--keys는 --set과 함께 사용해주세요.")
        if args.execute and not args.import_path:
            raise ControlError("--execute는 --import와 함께 사용해주세요.")
        if args.yes and not (args.import_path and args.execute):
            raise ControlError("--yes는 --import --execute와 함께 사용해주세요.")
        if args.show_gui or args.close:
            ensure_gui_running()
            action = "close_shortcut_help" if args.close else "show_shortcut_help"
            result = control_request({"action": action})
            print_json(result)
            return 0
        if args.export_path:
            result = export_shortcut_settings(Path(args.export_path))
        elif args.import_path:
            if args.execute and not args.yes:
                raise ControlError("단축키 가져오기를 적용하려면 --yes가 필요합니다.")
            plan = shortcut_import_plan(Path(args.import_path))
            if not args.execute:
                result = plan
            elif gui_is_running():
                saved = control_request(
                    {
                        "action": "apply_shortcut_overrides",
                        "shortcutOverrides": plan["shortcutOverrides"],
                    }
                )
                result = {**plan, "executed": True, "saved": saved}
            else:
                result = import_shortcut_settings(
                    Path(args.import_path), execute=True
                )
        elif args.set or args.disable or args.reset or args.reset_all:
            if args.set and args.keys is None:
                raise ControlError("--set에는 --keys가 필요합니다.")
            current = settings_snapshot()
            overrides = {
                key: list(value)
                for key, value in current["shortcutOverrides"].items()
            }
            if args.set:
                overrides[args.set] = parse_shortcut_keys_text(args.keys)
            elif args.disable:
                overrides[args.disable] = []
            elif args.reset:
                known_actions = {
                    item["id"] for item in shortcut_settings_snapshot(current)["shortcuts"]
                }
                if args.reset not in known_actions:
                    raise ControlError(
                        f"지원하지 않는 단축키 동작입니다: {args.reset}"
                    )
                overrides.pop(args.reset, None)
            else:
                overrides = {}
            if gui_is_running():
                saved = control_request(
                    {
                        "action": "apply_shortcut_overrides",
                        "shortcutOverrides": overrides,
                    }
                )
            else:
                saved = update_app_settings({"shortcutOverrides": overrides})
            result = {"saved": True, **shortcut_settings_snapshot(saved)}
        else:
            result = shortcut_settings_snapshot()
        if args.json:
            print_json(result)
        else:
            for item in result.get("shortcuts", []):
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
        if args.performance_command == "benchmark":
            if args.via_gui:
                ensure_gui_running()
                result = control_request(
                    {
                        "action": "start_performance_benchmark",
                        "sizes": args.sizes,
                        "pageSize": args.page_size,
                        "output": args.output or "",
                    }
                )
            else:
                result = run_job_database_benchmark(
                    args.sizes,
                    page_size=args.page_size,
                    report_path=Path(args.output) if args.output else None,
                )
        elif args.performance_command == "event-policy":
            result = {"ok": True, **downloader_event_update_policy(args.event)}
        elif args.performance_command == "stability":
            if args.via_gui:
                ensure_gui_running()
                result = control_request(
                    {
                        "action": "start_stability_test",
                        "records": args.records,
                        "cycles": args.cycles,
                        "output": args.output or "",
                    }
                )
            else:
                result = run_stability_recovery_test(
                    records=args.records,
                    cycles=args.cycles,
                    report_path=Path(args.output) if args.output else None,
                )
        elif args.performance_command == "resources":
            if gui_is_running():
                result = control_request({"action": "resource_status"})
            else:
                result = {"ok": True, "limits": resource_budget()}
        else:
            if args.close:
                ensure_gui_running()
                result = control_request({"action": "close_performance_diagnostics"})
            elif args.show_gui:
                ensure_gui_running()
                result = control_request({"action": "show_performance_diagnostics"})
            else:
                result = job_database_diagnostics()
        show_machine_result = bool(
            args.json
            or getattr(args, "via_gui", False)
            or getattr(args, "show_gui", False)
            or getattr(args, "close", False)
        )
        if show_machine_result:
            print_json(result)
        elif args.performance_command == "benchmark":
            for item in result.get("results") or []:
                print(
                    f"{int(item['size']):,}개 | 첫 화면 {float(item['firstPageMs']):.1f}ms | "
                    f"최대 조회 {float(item['maxQueryMs']):.1f}ms | "
                    f"{'통과' if item.get('passed') else '실패'}"
                )
            print(f"보고서: {result.get('reportPath')}")
        elif args.performance_command == "event-policy":
            print(
                f"{result['event']} | UI {result['uiMode']} "
                f"{int(result['uiIntervalMs'])}ms | 실행 이력 저장 "
                f"{'예' if result['persistRun'] else '아니오'}"
            )
        elif args.performance_command == "stability":
            if result.get("running") and not result.get("last"):
                print("GUI에서 안정성·강제 종료 복구 검증을 시작했습니다.")
            else:
                effective_stability = result.get("last") or result
                forced = effective_stability.get("forcedTermination") or {}
                print(
                    f"{int(effective_stability.get('records') or 0):,}개 · "
                    f"{int(effective_stability.get('cycles') or 0):,}회 | "
                    f"DB {effective_stability.get('integrity') or '실행 중'} | 강제 종료 복구 "
                    f"{'통과' if forced.get('recoveryPassed') else '실패'} | "
                    f"{float(effective_stability.get('durationMs') or 0):.1f}ms"
                )
                print(f"보고서: {effective_stability.get('reportPath') or '실행 중'}")
        elif args.performance_command == "resources":
            limits = result["limits"]
            print(
                f"I/O 스레드 {limits['ioThreads']} | CPU 프로세스 "
                f"{limits['cpuProcesses']} | 다운로드 대기 "
                f"{limits['maxPendingDownloads']:,}"
            )
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
        default_success = bool(
            getattr(args, "close", False) or getattr(args, "via_gui", False)
        )
        return 0 if bool(effective.get("ok", default_success)) else 2
    if command == "thumbnail-cache":
        execute = bool(
            args.thumbnail_cache_command == "cleanup" and args.execute
        )
        if execute and gui_is_running():
            result = control_request({"action": "cleanup_thumbnail_cache"})
        else:
            result = cleanup_thumbnail_cache(execute=execute)
        if args.json:
            print_json(result)
        else:
            action = "제거" if execute else "제거 예정"
            print(
                f"캐시 {int(result['existingFiles']):,}개, "
                f"{int(result['existingBytes']) / (1024 * 1024):.1f} MiB | "
                f"{action} {int(result['removeFiles']):,}개"
            )
        return 0 if result.get("ok") else 2
    if command == "retention":
        if args.retention_command == "status":
            result = {
                "ok": True,
                "logs": log_retention_status(),
                "runs": cleanup_run_history(execute=False),
            }
        else:
            if args.execute and gui_is_running():
                result = control_request(
                    {
                        "action": "cleanup_run_history",
                        "maxPerWork": args.max_per_work,
                        "maxAgeDays": args.max_age_days,
                    }
                )
            else:
                result = cleanup_run_history(
                    max_per_work=args.max_per_work,
                    max_age_days=args.max_age_days,
                    execute=args.execute,
                )
        if args.json:
            print_json(result)
        elif args.retention_command == "status":
            print(
                f"로그 {int(result['logs']['fileCount'])}개, "
                f"{int(result['logs']['totalBytes']) / (1024 * 1024):.1f} MiB | "
                f"실행 이력 정리 예정 {int(result['runs']['candidateRuns']):,}건"
            )
        else:
            label = "제거" if args.execute else "제거 예정"
            print(f"실행 이력 {label}: {int(result['candidateRuns']):,}건")
        return 0 if result.get("ok") else 2
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
    if command == "rename-episodes":
        execute = bool(args.execute)
        if execute and not args.yes:
            raise ControlError(
                "실제 회차 폴더명 변경에는 --execute --yes가 모두 필요합니다."
            )
        if gui_is_running():
            try:
                result = control_request(
                    {
                        "action": "rename_episode_folders",
                        "jobId": args.job,
                        "execute": execute,
                        "confirmed": bool(args.yes) if execute else False,
                    },
                    timeout_ms=120000 if execute else 30000,
                )
            except ControlTimeoutError as error:
                if not execute:
                    raise
                status_command = r".\toki-cli.cmd status --json"
                raise ControlTimeoutError(
                    "GUI 응답 제한 시간이 초과되었습니다. 회차 폴더명 변경은 "
                    "백그라운드에서 계속될 수 있으니 status를 확인하세요: "
                    + status_command,
                    operation_may_continue=True,
                    status_command=status_command,
                ) from error
        else:
            result = (
                rename_episode_folders(args.job)
                if execute
                else plan_episode_folder_rename(args.job)
            )
        if args.json:
            print_json({"ok": True, **result})
        else:
            print(f"작품 폴더: {result['outputPath']}")
            print(f"전체 작품명: {result['title']}")
            print(
                f"회차 폴더: {result['folderCount']}개 · "
                f"변경 {result['renameCount']}개 · 충돌 {result['conflictCount']}개"
            )
            print(
                "결과: 이름 변경 완료"
                if result.get("executed")
                else "결과: 변경 가능(dry-run)"
                if result.get("canExecute")
                else "결과: 충돌 해결 필요(dry-run)"
            )
            if not result.get("executed") and not result.get("canExecute"):
                if result.get("recoveryRequired"):
                    recovery = result.get("recovery") or {}
                    reason = str(
                        recovery.get("message")
                        or "이전 이름 변경의 복구 자료를 먼저 확인해야 합니다."
                    )
                elif int(result.get("unsafeSuffixCount") or 0) > 0:
                    reason = (
                        "원본 제목에서 실제 회차명을 판별하지 못한 폴더가 있습니다."
                    )
                elif result.get("duplicateNumbers"):
                    reason = "중복 회차 번호: " + ", ".join(
                        str(value) for value in result["duplicateNumbers"][:10]
                    )
                else:
                    first_conflict = next(iter(result.get("conflicts") or []), {})
                    reason = str(
                        first_conflict.get("message")
                        or first_conflict.get("destination")
                        or "안전 검사에서 실행이 차단되었습니다."
                    )
                print(f"원인: {reason}")
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
        if args.close:
            ensure_gui_running()
            print_json(control_request({"action": "close_file_verification"}))
            return 0
        if not args.job:
            raise ControlError("파일 검사에는 --job 작업ID가 필요합니다.")
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
        if args.close:
            ensure_gui_running()
            print_json(control_request({"action": "close_image_preview"}))
            return 0
        if not args.job:
            raise ControlError("이미지 미리보기에는 --job 작업ID가 필요합니다.")
        selection = {}
        if args.episode_id is not None:
            selection["episode_id"] = args.episode_id
        if args.episode_folder is not None:
            selection["episode_folder"] = args.episode_folder
        if args.show_gui:
            ensure_gui_running()
            print_json(
                control_request(
                    {
                        "action": "preview_images",
                        "jobId": args.job,
                        "episode": args.episode,
                        **({"episodeId": args.episode_id} if args.episode_id is not None else {}),
                        **({"episodeFolder": args.episode_folder} if args.episode_folder is not None else {}),
                    }
                )
            )
            return 0
        result = list_job_episode_images(
            args.job,
            args.episode,
            limit=args.limit,
            offset=args.offset,
            **selection,
        )
        if args.json:
            payload = {"ok": True, **result}
            if args.ascii_json:
                print(json.dumps(payload, ensure_ascii=True, indent=2))
            else:
                print_json(payload)
        else:
            print(f"작품: {result['title']} | 회차: {result['episode']}")
            if result.get("episodeFolder"):
                print(f"회차 폴더: {result['episodeFolder']}")
            print(f"이미지 {len(result['images'])} / 전체 {result['total']}")
            for image in result["images"]:
                print(f"{image['index']}: {image['name']} ({image['size']} bytes)")
        return 0
    if command == "convert-images":
        if args.close:
            ensure_gui_running()
            print_json(control_request({"action": "close_image_conversion"}))
            return 0
        if not args.job or not args.format:
            raise ControlError("이미지 변환에는 --job과 --format이 필요합니다.")
        policy = image_processing_policy_snapshot()
        max_width = (
            args.max_width if args.max_width is not None else policy["maxWidth"]
        )
        max_height = (
            args.max_height if args.max_height is not None else policy["maxHeight"]
        )
        if args.include_all_types:
            excluded_extensions: list[str] = []
        elif args.exclude_ext is not None:
            excluded_extensions = [
                part.strip()
                for value in args.exclude_ext
                for part in re.split(r"[,;]", value)
                if part.strip()
            ]
        else:
            excluded_extensions = list(policy["excludedExtensions"])
        if args.show_gui:
            ensure_gui_running()
            print_json(
                control_request(
                    {
                        "action": "convert_images",
                        "jobId": args.job,
                        "format": args.format,
                        "quality": args.quality,
                        "maxWidth": max_width,
                        "maxHeight": max_height,
                        "excludedExtensions": excluded_extensions,
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
                max_width=max_width,
                max_height=max_height,
                excluded_extensions=excluded_extensions,
                progress_callback=progress_callback,
            )
            if execute
            else plan_image_conversion(
                args.job,
                args.format,
                quality=args.quality,
                max_width=max_width,
                max_height=max_height,
                excluded_extensions=excluded_extensions,
            )
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
    if command == "image-processing":
        if args.image_processing_command == "status":
            result = (
                control_request({"action": "image_processing_policy"})
                if gui_is_running()
                else image_processing_policy_snapshot()
            )
        else:
            updates: dict[str, Any] = {}
            if args.max_width is not None:
                updates["imageResizeMaxWidth"] = args.max_width
            if args.max_height is not None:
                updates["imageResizeMaxHeight"] = args.max_height
            if args.exclude is not None:
                updates["imageExcludedExtensions"] = [
                    part.strip()
                    for part in re.split(r"[,;]", args.exclude)
                    if part.strip()
                ]
            elif args.clear_exclusions:
                updates["imageExcludedExtensions"] = []
            if not updates:
                raise ControlError("변경할 이미지 후처리 설정을 하나 이상 지정해주세요.")
            if gui_is_running():
                values = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                values = update_app_settings(updates)
            result = {"saved": True, **image_processing_policy_snapshot(values)}
        print_json(result)
        return 0
    if command == "pdf":
        if args.pdf_command == "status":
            result = (
                control_request({"action": "pdf_status"})
                if gui_is_running()
                else pdf_generation_policy_snapshot()
            )
        elif args.pdf_command == "set":
            updates = {"pdfGenerationEnabled": args.automatic == "on"}
            if gui_is_running():
                control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
                result = control_request({"action": "pdf_status"})
            else:
                saved = update_app_settings(updates)
                result = pdf_generation_policy_snapshot(saved)
        elif args.pdf_command == "plan":
            result = plan_job_pdf_generation(args.job)
        elif args.pdf_command == "cancel":
            ensure_gui_running()
            result = control_request(
                {"action": "cancel_pdf_generation", "jobId": args.job}
            )
        elif args.pdf_command == "close":
            ensure_gui_running()
            result = control_request({"action": "close_pdf_generation"})
        else:
            if args.show_gui:
                ensure_gui_running()
                result = control_request(
                    {"action": "generate_pdf", "jobId": args.job, "execute": False}
                )
                print_json(result)
                return 0
            if args.execute and not args.yes:
                raise ControlError("실제 PDF 생성에는 --execute --yes가 모두 필요합니다.")
            progress_callback = None
            if args.progress_json:
                def emit_pdf_progress(event: dict[str, Any]) -> None:
                    print(
                        json.dumps(
                            {"event": "progress", **event}, ensure_ascii=True
                        ),
                        flush=True,
                    )

                progress_callback = emit_pdf_progress
            result = (
                generate_job_pdfs(args.job, progress_callback=progress_callback)
                if args.execute
                else plan_job_pdf_generation(args.job)
            )
            if args.progress_json:
                print(
                    json.dumps(
                        {
                            "event": "result",
                            "result": {
                                "ok": bool(result.get("success", True)),
                                **result,
                            },
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                if result.get("cancelled"):
                    return 3
                return 0 if result.get("success", True) else 2
        payload = {"ok": bool(result.get("success", True)), **result}
        if getattr(args, "ascii_json", False):
            print(json.dumps(payload, ensure_ascii=True, indent=2))
        else:
            print_json(payload)
        if args.pdf_command == "generate" and result.get("cancelled"):
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
        if args.show_gui or args.close:
            ensure_gui_running()
            if args.close:
                result = control_request({"action": "close_settings"})
            else:
                result = control_request(
                    {
                        "action": "show_settings",
                        "tab": args.tab,
                        "search": args.search,
                    }
                )
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
            "uiLanguage": args.language,
            "folderNameTemplate": args.folder_template,
            "workConcurrency": args.works,
            "imageConcurrency": args.images,
            "retryCount": args.retry_count,
            "retryBackoffSeconds": args.retry_backoff,
            "logMaxMiB": args.log_max_mib,
            "logBackupCount": args.log_backups,
            "rowDensity": args.row_density,
            "theme": args.theme,
            "listViewMode": args.view_mode,
            "thumbnailSize": args.thumbnail_size,
            "windowOpacity": args.opacity,
            "uiScale": args.ui_scale,
            "fontFamily": args.font,
            "backgroundImage": args.background,
            "proxyUrl": args.proxy,
            "speedLimitKib": args.speed_limit_kib,
        }
        updates = {key: value for key, value in mapping.items() if value is not None}
        if args.clear_background:
            updates["backgroundImage"] = ""
        if args.clear_proxy:
            updates["proxyUrl"] = ""
        if args.quick_actions is not None:
            updates["quickActions"] = [
                value.strip() for value in args.quick_actions.split(",") if value.strip()
            ]
        if args.show_browser is not None:
            updates["showBrowser"] = args.show_browser == "on"
        if args.log_visible is not None:
            updates["logVisible"] = args.log_visible == "on"
        if args.thumbnails is not None:
            updates["thumbnailsVisible"] = args.thumbnails == "on"
        if args.always_on_top is not None:
            updates["alwaysOnTop"] = args.always_on_top == "on"
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
    if command == "folder-template":
        config = load_config()
        template = args.template or config.get("folderNameTemplate")
        result = folder_name_template_preview(
            template,
            metadata={
                "author": args.author,
                "group": args.group,
                "title": args.title,
                "source": {"siteTitle": args.site, "workId": args.id},
            },
            output_dir=args.output,
            site_title=args.site,
        )
        if args.json:
            print_json(result)
        else:
            print(f"템플릿: {result['template']}")
            print(f"미리보기: {result['preview']}")
            if result["candidatePath"]:
                print(f"예상 경로: {result['candidatePath']}")
                print(f"기존 폴더 충돌: {'있음' if result['collision'] else '없음'}")
            print("기존 폴더 변경: 없음 (dry-run)")
        return 0
    if command == "language":
        subcommand = args.language_command
        if subcommand == "list":
            result = {"languages": available_ui_languages()}
        elif subcommand == "status":
            settings = settings_snapshot()
            result = {
                "language": settings["uiLanguage"],
                "languages": available_ui_languages(),
            }
        else:
            updates = {"uiLanguage": args.code}
            if gui_is_running():
                settings = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                settings = update_app_settings(updates)
            result = {
                "saved": True,
                "language": settings["uiLanguage"],
                "languages": available_ui_languages(),
            }
        if args.json:
            print_json(result)
        else:
            if subcommand == "list":
                for item in result["languages"]:
                    print(f"{item['code']}: {item['name']}")
            else:
                print(f"UI 언어: {result['language']}")
        return 0
    if command == "browser-mode":
        if args.browser_mode_command == "set":
            updates = {"showBrowser": args.mode == "visible"}
            if gui_is_running():
                settings = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                settings = update_app_settings(updates)
            result = {"saved": True, **browser_launch_policy(settings["showBrowser"])}
        else:
            result = browser_launch_policy(settings_snapshot()["showBrowser"])
        if args.json:
            print_json(result)
        else:
            print(f"브라우저 모드: {result['mode']}")
            print("개인 Chrome 프로필 사용: 안 함")
        return 0
    if command == "embedded-browser":
        subcommand = args.embedded_browser_command
        if subcommand == "capabilities":
            result = embedded_browser_capabilities()
        elif subcommand == "plan":
            result = embedded_browser_navigation_plan(args.url)
        else:
            if args.close:
                ensure_gui_running()
                result = control_request({"action": "close_embedded_browser"})
            else:
                normalized_url = normalize_embedded_browser_url(args.url)
                if args.navigate:
                    if not normalized_url:
                        raise ControlError("--navigate에는 --url이 필요합니다.")
                    if not args.yes:
                        raise ControlError(
                            "내장 브라우저 URL 이동은 외부 네트워크 요청입니다. 실행하려면 --yes가 필요합니다."
                        )
                    embedded_browser_navigation_plan(normalized_url)
                ensure_gui_running()
                result = control_request(
                    {
                        "action": "show_embedded_browser",
                        "url": normalized_url,
                        "navigate": bool(args.navigate),
                        "confirmed": bool(args.yes),
                    }
                )
        if args.json:
            print_json(result)
        else:
            print_json(result)
        return 0
    if command == "network-policy":
        if gui_is_running():
            current = control_request({"action": "settings"})
        else:
            current = settings_snapshot()
        if args.network_command == "status":
            result = network_policy_snapshot(current, url=args.url)
        else:
            updates: dict[str, Any] = {}
            if args.proxy is not None:
                updates["proxyUrl"] = args.proxy
            if args.clear_proxy:
                updates["proxyUrl"] = ""
            if args.speed_limit_kib is not None:
                updates["speedLimitKib"] = args.speed_limit_kib
            provider_values = (
                args.request_delay_ms is not None or args.backoff is not None
            )
            if provider_values and not args.provider:
                raise ControlError(
                    "--request-delay-ms 또는 --backoff에는 --provider가 필요합니다."
                )
            if args.provider:
                policies = {
                    key: dict(value)
                    for key, value in current["providerPolicies"].items()
                }
                selected = policies[args.provider]
                if args.request_delay_ms is not None:
                    selected["requestDelayMs"] = args.request_delay_ms
                if args.backoff is not None:
                    selected["backoffSeconds"] = args.backoff
                if provider_values:
                    updates["providerPolicies"] = policies
            if not updates:
                raise ControlError("변경할 네트워크 정책을 지정해주세요.")
            if gui_is_running():
                saved = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                saved = update_app_settings(updates)
            result = {"saved": True, **network_policy_snapshot(saved)}
        if args.json:
            print_json(result)
        else:
            print(f"프록시: {result['proxyUrl'] or '사용 안 함'}")
            speed = result["speedLimitKib"]
            print(f"속도 제한: {speed if speed else '무제한'}")
            for provider, policy in result["providerPolicies"].items():
                print(
                    f"{provider}: 간격 {policy['requestDelayMs']}ms · "
                    f"백오프 {policy['backoffSeconds']}초"
                )
        return 0
    if command == "proxy-auth":
        subcommand = args.proxy_auth_command
        if subcommand == "manage":
            ensure_gui_running()
            result = control_request(
                {"action": "close_proxy_credential_manager"}
                if args.close
                else {"action": "show_proxy_credential_manager"}
            )
        elif subcommand == "capabilities":
            result = credential_store_status()
        else:
            if not args.yes:
                raise ControlError(
                    "프록시 인증은 민감 정보입니다. OS 보안 저장소 읽기·쓰기·삭제를 실행하려면 --yes가 필요합니다."
                )
            current_proxy = str(settings_snapshot().get("proxyUrl") or "")
            if subcommand == "status":
                result = proxy_credential_status(args.proxy or current_proxy)
            elif subcommand == "set":
                proxy_url = str(args.proxy or current_proxy)
                if not proxy_url:
                    raise ControlError("프록시 주소를 먼저 설정하거나 --proxy를 지정해주세요.")
                password = (
                    sys.stdin.readline().rstrip("\r\n")
                    if args.password_stdin
                    else getpass.getpass("프록시 비밀번호: ")
                )
                result = store_proxy_credentials(
                    proxy_url,
                    args.username,
                    password,
                )
            else:
                result = clear_proxy_credentials()
        if args.json:
            print_json(result)
        else:
            print_json(result)
        return 0
    if command == "public-ip":
        if args.public_ip_command == "plan":
            result = public_ip_check_plan()
        else:
            if not args.yes:
                raise ControlError(
                    "공인 IP 확인은 외부 서비스에 요청합니다. 실행하려면 --yes가 필요합니다."
                )
            result = lookup_public_ip(confirmed=True)
        if args.json:
            print_json(result)
        else:
            if args.public_ip_command == "plan":
                print(f"확인 주소: {result['endpoint']}")
                print("외부 네트워크 요청: 사용자 확인 필요")
            else:
                print(f"공인 IP: {result['ip']}")
        return 0
    if command == "cookies":
        subcommand = args.cookie_command
        if subcommand == "manage":
            ensure_gui_running()
            result = control_request(
                {"action": "close_cookie_manager"}
                if args.close
                else {
                    "action": "show_cookie_manager",
                    "provider": args.provider,
                }
            )
        elif subcommand == "capabilities":
            result = credential_store_status()
        elif subcommand == "policy":
            result = provider_cookie_policy(args.provider)
        elif subcommand == "plan-import":
            if not args.yes:
                raise ControlError(
                    "쿠키 파일에는 민감한 값이 포함됩니다. 읽어서 검사하려면 --yes가 필요합니다."
                )
            result = cookie_import_plan(args.provider, Path(args.input))
        else:
            if not args.yes:
                raise ControlError(
                    "쿠키는 민감 정보입니다. OS 보안 저장소 읽기·쓰기·삭제를 실행하려면 --yes가 필요합니다."
                )
            if subcommand == "status":
                result = provider_cookie_status(args.provider)
            elif subcommand == "import":
                result = import_provider_cookies(args.provider, Path(args.input))
            elif subcommand == "export":
                result = export_provider_cookies(
                    args.provider, Path(args.output)
                )
            else:
                result = clear_provider_cookies(args.provider)
        if args.json:
            print_json(result)
        else:
            print_json(result)
        return 0
    if command == "completion-action":
        subcommand = args.completion_command
        if subcommand == "status":
            values = settings_snapshot()
            result = completion_action_plan(
                str(values["completionAction"]),
                int(values["completionCountdownSeconds"]),
                armed=False,
            )
        elif subcommand == "set":
            updates = {
                "completionAction": args.action,
                "completionCountdownSeconds": args.countdown,
            }
            if gui_is_running():
                values = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                values = update_app_settings(updates)
            result = {
                "saved": True,
                **completion_action_plan(
                    str(values["completionAction"]),
                    int(values["completionCountdownSeconds"]),
                    armed=False,
                ),
            }
        elif subcommand == "preview":
            result = completion_action_plan(
                args.action, args.countdown, armed=True
            )
            if args.show_gui:
                ensure_gui_running()
                result = control_request(
                    {
                        "action": "preview_completion_action",
                        "completionAction": args.action,
                        "countdownSeconds": args.countdown,
                    }
                )
        else:
            ensure_gui_running()
            result = {"cancelled": bool(control_request({"action": "cancel_completion_action"})["cancelled"])}
        if getattr(args, "json", False):
            print_json(result)
        else:
            print_json(result)
        return 0
    if command == "clipboard":
        if args.clipboard_command == "monitor":
            updates = {"clipboardMonitor": args.state == "on"}
            if args.mode is not None:
                updates["clipboardAutoDownload"] = args.mode == "auto"
            if gui_is_running():
                values = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                values = update_app_settings(updates)
            result = {
                "monitorEnabled": bool(values["clipboardMonitor"]),
                "autoDownload": bool(values.get("clipboardAutoDownload", False)),
                "saved": True,
            }
        elif args.clipboard_command == "status":
            running = gui_is_running()
            if running:
                result = {**control_request({"action": "status"})["clipboard"], "guiRunning": True}
            else:
                values = load_config()
                result = {
                    "monitorEnabled": bool(values["clipboardMonitor"]),
                    "autoDownload": bool(values["clipboardAutoDownload"]),
                    "guiRunning": False,
                    "lastInspection": {},
                }
        elif args.clipboard_command == "enqueue":
            if not args.yes:
                raise ControlError("실제 다운로드 등록에는 --yes가 필요합니다. 판정만 하려면 clipboard inspect를 사용하세요.")
            ensure_gui_running()
            result = control_request({"action": "enqueue_clipboard", "text": args.text})
        elif args.via_gui:
            ensure_gui_running()
            result = control_request(
                {"action": "inspect_clipboard", "text": args.text, "prompt": False}
            )
        else:
            result = inspect_clipboard_url(args.text)
            if result.get("candidate"):
                existing = load_job_by_work_key(str(result["workKey"]))
                if existing:
                    result = inspect_clipboard_url(
                        args.text, existing_work_keys={existing.work_key}
                    )
        print_json(result)
        return 0 if result.get("ok", True) else 2
    if command == "tray":
        ensure_gui_running()
        result = control_request(
            {"action": "tray", "command": args.action, "message": args.message}
        )
        print_json(result)
        return 0
    if command == "notifications":
        subcommand = args.notification_command
        if subcommand == "status":
            result = (
                control_request({"action": "notification_status"})
                if gui_is_running()
                else notification_settings_snapshot()
            )
        elif subcommand == "set":
            updates: dict[str, Any] = {}
            for argument, key in (
                (args.complete, "notifyOnComplete"),
                (args.error, "notifyOnError"),
                (args.message_box, "notificationMessageBox"),
            ):
                if argument is not None:
                    updates[key] = argument == "on"
            if args.sound is not None:
                updates["notificationSound"] = args.sound
            if not updates:
                raise ControlError("변경할 알림 설정을 하나 이상 지정해주세요.")
            if gui_is_running():
                values = control_request(
                    {"action": "set_settings", "updates": updates, "reset": False}
                )
            else:
                values = update_app_settings(updates)
            result = {"saved": True, **notification_settings_snapshot(values)}
        elif subcommand == "preview":
            plan = notification_event_plan(
                args.kind,
                title=args.title,
                detail=args.detail,
                preview=True,
            )
            ensure_gui_running()
            result = control_request(
                {
                    "action": "preview_notification",
                    "kind": plan["kind"],
                    "title": plan["title"],
                    "detail": plan["detail"],
                }
            )
        else:
            ensure_gui_running()
            result = control_request({"action": "close_notifications"})
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
            if args.job:
                job = load_job_by_id(args.job)
                if job is None:
                    raise ControlError(f"작업 기록을 찾을 수 없습니다: {args.job}")
                target = job.output_path or job.output_dir
            else:
                target = load_config().get("outputDir") or str(ROOT_DIR)
            open_in_explorer(target)
            print(target)
        return 0
    if command == "copy-link":
        print_json(copy_job_field(args.job, "link"))
        return 0
    if command == "copy-id":
        print_json(copy_job_field(args.job, "id"))
        return 0
    if command == "copy-path":
        print_json(copy_job_field(args.job, "path"))
        return 0
    if command == "copy-title":
        print_json(copy_job_field(args.job, "title"))
        return 0
    if command == "job-menu":
        print_json(
            control_request(
                {
                    "action": (
                        "inspect_job_menu" if args.inspect else "show_job_menu"
                    ),
                    "jobId": args.job,
                }
            )
        )
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
        if bool(getattr(args, "json", False)):
            payload: dict[str, Any] = {"ok": False, "error": str(error)}
            if isinstance(error, ControlTimeoutError):
                payload["timeout"] = True
                payload["operationMayContinue"] = error.operation_may_continue
                if error.status_command:
                    payload["statusCommand"] = error.status_command
            print_json(payload)
        else:
            print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
