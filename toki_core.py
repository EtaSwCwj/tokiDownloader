from __future__ import annotations

import json
import hashlib
import importlib.metadata
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit

import psutil


ROOT_DIR = Path(__file__).resolve().parent
VERSION_PATH = ROOT_DIR / "VERSION"
APP_VERSION = (
    VERSION_PATH.read_text(encoding="utf-8").strip()
    if VERSION_PATH.is_file()
    else "0.0.0-dev"
)
DOWNLOADER_PATH = ROOT_DIR / "down.js"
CONFIG_PATH = ROOT_DIR / "config.json"
LOG_DIR = ROOT_DIR / "logs"
LOG_PATH = LOG_DIR / "gui.log"
JOB_DB_PATH = ROOT_DIR / "jobs.db"
THUMBNAIL_CACHE_DIR = ROOT_DIR / ".cache" / "thumbnails"
CONTROL_SERVER_NAME = "tokiDownloaderGUI"
EVENT_PREFIX = "@@TOKI@@"
_INITIALIZED_JOB_DBS: set[str] = set()
CONFIG_SCHEMA_VERSION = 1
JOB_DB_SCHEMA_VERSION = 4
JOB_DB_MIGRATIONS = {
    1: "작품 work_key 정규화와 실행 이력 분리",
    2: "고정·상태·정렬 복합 인덱스와 마이그레이션 이력",
    3: "작품 정리 그룹과 작품별 그룹 멤버십",
    4: "작가·메타데이터 그룹·작업 ID 통합 검색 열과 인덱스",
}
_DATABASE_MIGRATION_REPORTS: dict[str, dict[str, Any]] = {}
TAG_COLORS = {
    "none": "",
    "red": "#d84a4a",
    "orange": "#df862f",
    "yellow": "#d4ad2c",
    "green": "#3b9a59",
    "blue": "#3f7fd6",
    "purple": "#8856c6",
    "gray": "#7b8794",
}
SETTING_KEYS = frozenset(
    {
        "outputDir",
        "logVisible",
        "showBrowser",
        "workConcurrency",
        "imageConcurrency",
        "retryCount",
        "retryBackoffSeconds",
        "logMaxMiB",
        "logBackupCount",
        "rowDensity",
        "theme",
        "trayEnabled",
        "closeToTray",
        "minimizeToTray",
        "notifyOnComplete",
        "notifyOnError",
    }
)
_LOG_MAX_BYTES = 2 * 1024 * 1024
_LOG_BACKUP_COUNT = 1
ACTIVE_JOB_STATES = frozenset({"대기", "실행 중", "일시정지", "재시도 대기"})
JOB_SORT_ORDERS = {
    "updated": "pinned DESC, updated_at DESC, job_id DESC",
    "title": "pinned DESC, title COLLATE NOCASE ASC, updated_at DESC, job_id DESC",
    "progress": "pinned DESC, progress DESC, updated_at DESC, job_id DESC",
}
JOB_QUERY_INDEXES = {
    "idx_jobs_pinned_updated_job": (
        "pinned DESC, updated_at DESC, job_id DESC"
    ),
    "idx_jobs_state_pinned_updated_job": (
        "state, pinned DESC, updated_at DESC, job_id DESC"
    ),
    "idx_jobs_pinned_title_updated_job": (
        "pinned DESC, title COLLATE NOCASE ASC, updated_at DESC, job_id DESC"
    ),
    "idx_jobs_state_pinned_title_updated_job": (
        "state, pinned DESC, title COLLATE NOCASE ASC, updated_at DESC, job_id DESC"
    ),
    "idx_jobs_pinned_progress_updated_job": (
        "pinned DESC, progress DESC, updated_at DESC, job_id DESC"
    ),
    "idx_jobs_state_pinned_progress_updated_job": (
        "state, pinned DESC, progress DESC, updated_at DESC, job_id DESC"
    ),
}
COALESCED_DOWNLOADER_EVENTS = frozenset({"image_saved"})
PERSISTED_DOWNLOADER_EVENTS = frozenset(
    {
        "work_metadata",
        "queue_ready",
        "episode_started",
        "episode_completed",
        "completed",
        "error",
    }
)
KNOWN_DOWNLOADER_EVENTS = PERSISTED_DOWNLOADER_EVENTS | COALESCED_DOWNLOADER_EVENTS | {
    "images_found"
}
ERROR_CATEGORIES = frozenset(
    {
        "authentication_required",
        "rate_limited",
        "network",
        "site_structure",
        "filesystem",
        "process",
        "unknown",
    }
)
ERROR_CATEGORY_LABELS = {
    "authentication_required": "인증 필요",
    "rate_limited": "요청 제한",
    "network": "네트워크",
    "site_structure": "사이트 구조 변경",
    "filesystem": "파일 시스템",
    "process": "프로세스",
    "unknown": "기타",
}
NON_RETRYABLE_ERROR_CATEGORIES = frozenset(
    {"authentication_required", "site_structure", "filesystem"}
)
KEYBOARD_SHORTCUTS = (
    {
        "id": "download.start",
        "label": "다운로드 시작",
        "keys": ("Ctrl+Enter",),
        "cli": "download --url URL",
    },
    {
        "id": "job.stop",
        "label": "현재 작업 중지",
        "keys": ("Ctrl+K",),
        "cli": "stop --job ID",
    },
    {
        "id": "job.pause",
        "label": "현재 작업 일시정지",
        "keys": ("Ctrl+P",),
        "cli": "pause --job ID",
    },
    {
        "id": "job.resume",
        "label": "일시정지 작업 계속",
        "keys": ("Ctrl+Shift+P",),
        "cli": "resume --job ID",
    },
    {
        "id": "job.rescan_full",
        "label": "선택 작품 전체 재검사",
        "keys": ("Ctrl+R",),
        "cli": "rescan --job ID --mode full",
    },
    {
        "id": "job.rescan_new",
        "label": "선택 작품 신규 회차만 검사",
        "keys": ("Ctrl+Shift+N",),
        "cli": "rescan --job ID --mode new",
    },
    {
        "id": "job.rescan_range",
        "label": "선택 작품 입력 범위 검사",
        "keys": ("Ctrl+Shift+R",),
        "cli": "rescan --job ID --mode range --start N --last N",
    },
    {
        "id": "snapshot.export",
        "label": "작업 스냅샷 내보내기",
        "keys": ("Ctrl+Alt+E",),
        "cli": "jobs export --output PATH --json",
    },
    {
        "id": "snapshot.import",
        "label": "작업 스냅샷 가져오기",
        "keys": ("Ctrl+Alt+I",),
        "cli": "jobs import --input PATH --show-gui",
    },
    {
        "id": "group.manage",
        "label": "작품 그룹 관리",
        "keys": ("Ctrl+G",),
        "cli": "group manage --show-gui",
    },
    {
        "id": "archive.inspect",
        "label": "로컬 압축 작품 검사",
        "keys": ("Ctrl+Shift+A",),
        "cli": "local inspect --path PATH --show-gui",
    },
    {
        "id": "duplicates.works",
        "label": "중복 의심 작품 검사",
        "keys": ("Ctrl+D",),
        "cli": "duplicates works --show-gui",
    },
    {
        "id": "folder.open",
        "label": "저장 폴더 열기",
        "keys": ("Ctrl+O",),
        "cli": "open-folder --job ID",
    },
    {
        "id": "details.open",
        "label": "작품 정보 및 실행 이력",
        "keys": ("Ctrl+I",),
        "cli": "details --job ID",
    },
    {
        "id": "list.activate",
        "label": "선택 작품 상세 열기",
        "keys": ("Return", "Enter"),
        "cli": "details --job ID",
    },
    {
        "id": "list.refresh",
        "label": "작품 목록 새로고침",
        "keys": ("F5",),
        "cli": "refresh-list",
    },
    {
        "id": "focus.url",
        "label": "URL 입력으로 이동",
        "keys": ("Ctrl+L",),
        "cli": "focus --target url",
    },
    {
        "id": "focus.search",
        "label": "작품 검색으로 이동",
        "keys": ("Ctrl+F",),
        "cli": "focus --target search",
    },
    {
        "id": "focus.cycle",
        "label": "다음 화면 영역으로 이동",
        "keys": ("F6",),
        "cli": "focus --target next-section",
    },
    {
        "id": "selection.previous",
        "label": "이전 작품 선택",
        "keys": ("Ctrl+Shift+Up",),
        "cli": "focus --target previous",
    },
    {
        "id": "selection.next",
        "label": "다음 작품 선택",
        "keys": ("Ctrl+Shift+Down",),
        "cli": "focus --target next",
    },
    {
        "id": "search.clear",
        "label": "검색어 지우기",
        "keys": ("Escape",),
        "cli": "focus --target search --clear",
    },
    {
        "id": "screenshot.capture",
        "label": "GUI 화면 캡처",
        "keys": ("Ctrl+Shift+S",),
        "cli": "screenshot",
    },
    {
        "id": "settings.open",
        "label": "설정 열기",
        "keys": ("Ctrl+,",),
        "cli": "settings --show-gui",
    },
)


def default_config() -> dict[str, Any]:
    return {
        "configVersion": CONFIG_SCHEMA_VERSION,
        "outputDir": str(ROOT_DIR),
        "window": {
            "x": None,
            "y": None,
            "width": 860,
            "height": 720,
            "maximized": False,
        },
        "logVisible": True,
        "showBrowser": False,
        "workConcurrency": 1,
        "imageConcurrency": 5,
        "retryCount": 2,
        "retryBackoffSeconds": 2,
        "logMaxMiB": 2,
        "logBackupCount": 1,
        "rowDensity": "comfortable",
        "theme": "system",
        "trayEnabled": False,
        "closeToTray": False,
        "minimizeToTray": False,
        "notifyOnComplete": True,
        "notifyOnError": True,
    }


def _safe_normalize(
    normalizer: Callable[[Any], Any], value: Any, fallback: Any
) -> Any:
    try:
        return normalizer(value)
    except (TypeError, ValueError):
        return fallback


def normalize_log_max_mib(value: int | None) -> int:
    normalized = 2 if value is None else int(value)
    if not 1 <= normalized <= 100:
        raise ValueError("로그 파일 최대 크기는 1~100 MiB여야 합니다.")
    return normalized


def normalize_log_backup_count(value: int | None) -> int:
    normalized = 1 if value is None else int(value)
    if not 1 <= normalized <= 10:
        raise ValueError("로그 백업 개수는 1~10개여야 합니다.")
    return normalized


def normalize_row_density(value: str | None) -> str:
    normalized = str(value or "comfortable").strip().lower()
    if normalized not in {"compact", "comfortable"}:
        raise ValueError("작업 행 밀도는 compact 또는 comfortable이어야 합니다.")
    return normalized


def normalize_theme(value: str | None) -> str:
    normalized = str(value or "system").strip().lower()
    if normalized not in {"system", "light", "dark"}:
        raise ValueError("테마는 system, light 또는 dark여야 합니다.")
    return normalized


def normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_config()
    source = config if isinstance(config, dict) else {}
    normalized = {**source}
    try:
        source_version = int(source.get("configVersion") or 0)
    except (TypeError, ValueError):
        source_version = 0
    if source_version > CONFIG_SCHEMA_VERSION:
        raise ValueError(
            f"이 프로그램보다 새로운 설정 버전입니다: {source_version}"
        )
    normalized["configVersion"] = CONFIG_SCHEMA_VERSION
    output_dir = source.get("outputDir")
    normalized["outputDir"] = (
        str(output_dir).strip()
        if isinstance(output_dir, str) and str(output_dir).strip()
        else defaults["outputDir"]
    )
    for key in (
        "logVisible",
        "showBrowser",
        "trayEnabled",
        "closeToTray",
        "minimizeToTray",
        "notifyOnComplete",
        "notifyOnError",
    ):
        value = source.get(key)
        normalized[key] = value if isinstance(value, bool) else defaults[key]
    normalized["workConcurrency"] = _safe_normalize(
        normalize_work_concurrency,
        source.get("workConcurrency"),
        defaults["workConcurrency"],
    )
    normalized["imageConcurrency"] = _safe_normalize(
        normalize_image_concurrency,
        source.get("imageConcurrency"),
        defaults["imageConcurrency"],
    )
    normalized["retryCount"] = _safe_normalize(
        normalize_retry_count,
        source.get("retryCount"),
        defaults["retryCount"],
    )
    normalized["retryBackoffSeconds"] = _safe_normalize(
        normalize_retry_backoff,
        source.get("retryBackoffSeconds"),
        defaults["retryBackoffSeconds"],
    )
    normalized["logMaxMiB"] = _safe_normalize(
        normalize_log_max_mib,
        source.get("logMaxMiB"),
        defaults["logMaxMiB"],
    )
    normalized["logBackupCount"] = _safe_normalize(
        normalize_log_backup_count,
        source.get("logBackupCount"),
        defaults["logBackupCount"],
    )
    normalized["rowDensity"] = _safe_normalize(
        normalize_row_density,
        source.get("rowDensity"),
        defaults["rowDensity"],
    )
    normalized["theme"] = _safe_normalize(
        normalize_theme,
        source.get("theme"),
        defaults["theme"],
    )
    window = source.get("window")
    normalized["window"] = window if isinstance(window, dict) else defaults["window"]
    return normalized


def _apply_log_policy(config: dict[str, Any]) -> None:
    global _LOG_MAX_BYTES, _LOG_BACKUP_COUNT
    _LOG_MAX_BYTES = int(config["logMaxMiB"]) * 1024 * 1024
    _LOG_BACKUP_COUNT = int(config["logBackupCount"])


def load_config() -> dict[str, Any]:
    config = default_config()
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    normalized = normalize_config(config)
    _apply_log_policy(normalized)
    return normalized


def save_config(config: dict[str, Any]) -> None:
    normalized = normalize_config(config)
    temporary = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, CONFIG_PATH)
    config.clear()
    config.update(normalized)
    _apply_log_policy(normalized)


def config_schema_status(config_path: Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    if not path.is_file():
        return {
            "ok": True,
            "exists": False,
            "path": str(path.resolve()),
            "version": 0,
            "currentVersion": CONFIG_SCHEMA_VERSION,
            "needsMigration": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("설정 파일은 JSON 객체여야 합니다.")
        version = int(payload.get("configVersion") or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "ok": False,
            "exists": True,
            "path": str(path.resolve()),
            "error": str(error),
            "version": 0,
            "currentVersion": CONFIG_SCHEMA_VERSION,
            "needsMigration": False,
        }
    return {
        "ok": version <= CONFIG_SCHEMA_VERSION,
        "exists": True,
        "path": str(path.resolve()),
        "version": version,
        "currentVersion": CONFIG_SCHEMA_VERSION,
        "needsMigration": version < CONFIG_SCHEMA_VERSION,
        "futureVersion": version > CONFIG_SCHEMA_VERSION,
    }


def apply_config_migrations(config_path: Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else CONFIG_PATH
    before = config_schema_status(path)
    if not before["ok"]:
        raise ValueError(str(before.get("error") or "지원하지 않는 설정 버전입니다."))
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = default_config()
        path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = ""
    if before.get("needsMigration") and path.is_file():
        backup = path.with_suffix(path.suffix + f".pre-v{CONFIG_SCHEMA_VERSION}.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        backup_path = str(backup.resolve())
    normalized = normalize_config(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return {
        "ok": True,
        "before": before,
        "after": config_schema_status(path),
        "backupPath": backup_path,
    }


def settings_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    return {key: source[key] for key in sorted(SETTING_KEYS)}


def validate_app_setting_updates(
    updates: dict[str, Any], *, create_output_dir: bool = False
) -> dict[str, Any]:
    unknown = sorted(set(updates) - SETTING_KEYS)
    if unknown:
        raise ValueError(f"지원하지 않는 설정입니다: {', '.join(unknown)}")
    validated: dict[str, Any] = {}
    if "outputDir" in updates:
        raw_output = str(updates["outputDir"] or "").strip()
        if not raw_output:
            raise ValueError("저장 폴더 경로를 입력해주세요.")
        output_path = Path(raw_output).expanduser().resolve()
        if create_output_dir:
            output_path.mkdir(parents=True, exist_ok=True)
        validated["outputDir"] = str(output_path)
    for key in (
        "logVisible",
        "showBrowser",
        "trayEnabled",
        "closeToTray",
        "minimizeToTray",
        "notifyOnComplete",
        "notifyOnError",
    ):
        if key in updates:
            if not isinstance(updates[key], bool):
                raise ValueError(f"{key} 설정은 true 또는 false여야 합니다.")
            validated[key] = updates[key]
    normalizers: dict[str, Callable[[Any], Any]] = {
        "workConcurrency": normalize_work_concurrency,
        "imageConcurrency": normalize_image_concurrency,
        "retryCount": normalize_retry_count,
        "retryBackoffSeconds": normalize_retry_backoff,
        "logMaxMiB": normalize_log_max_mib,
        "logBackupCount": normalize_log_backup_count,
        "rowDensity": normalize_row_density,
        "theme": normalize_theme,
    }
    for key, normalizer in normalizers.items():
        if key in updates:
            validated[key] = normalizer(updates[key])
    return validated


def update_app_settings(
    updates: dict[str, Any], *, reset: bool = False
) -> dict[str, Any]:
    validated = validate_app_setting_updates(updates, create_output_dir=True)
    current = load_config()
    if reset:
        window = current.get("window")
        current.update(default_config())
        if isinstance(window, dict):
            current["window"] = window
    current.update(validated)
    save_config(current)
    return settings_snapshot(current)


def export_app_settings(output_path: Path) -> dict[str, Any]:
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "tokiDownloader-settings",
        "formatVersion": 1,
        "appVersion": APP_VERSION,
        "configVersion": CONFIG_SCHEMA_VERSION,
        "settings": settings_snapshot(),
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return {
        "ok": True,
        "path": str(target),
        "bytes": target.stat().st_size,
        "settings": payload["settings"],
    }


def import_app_settings(input_path: Path, *, execute: bool = False) -> dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"설정 가져오기 파일이 없습니다: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("설정 가져오기 파일은 JSON 객체여야 합니다.")
    raw_settings = payload.get("settings", payload)
    if not isinstance(raw_settings, dict):
        raise ValueError("settings 항목은 JSON 객체여야 합니다.")
    validated = validate_app_setting_updates(raw_settings)
    before = settings_snapshot()
    proposed_config = load_config()
    proposed_config.update(validated)
    proposed = settings_snapshot(normalize_config(proposed_config))
    changed = sorted(key for key in SETTING_KEYS if before[key] != proposed[key])
    backup_path = ""
    applied = before
    if execute:
        if CONFIG_PATH.is_file():
            timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
            backup = CONFIG_PATH.with_suffix(
                CONFIG_PATH.suffix + f".before-import-{timestamp}.bak"
            )
            shutil.copy2(CONFIG_PATH, backup)
            backup_path = str(backup.resolve())
        applied = update_app_settings(raw_settings)
    return {
        "ok": True,
        "executed": execute,
        "path": str(source),
        "changedKeys": changed,
        "before": before,
        "after": applied if execute else proposed,
        "backupPath": backup_path,
    }


def reset_app_settings(*, execute: bool = False) -> dict[str, Any]:
    before = settings_snapshot()
    defaults = settings_snapshot(default_config())
    changed = sorted(key for key in SETTING_KEYS if before[key] != defaults[key])
    after = update_app_settings({}, reset=True) if execute else defaults
    return {
        "ok": True,
        "executed": execute,
        "changedKeys": changed,
        "before": before,
        "after": after,
    }


def append_log(message: str, level: str = "INFO", job_id: str = "-") -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = (
        f"{datetime.now().astimezone().isoformat(timespec='seconds')} "
        f"[{level}] [{job_id}] {message}"
    )
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    _rotate_log_if_needed()
    return line


def _rotate_log_if_needed(
    max_bytes: int | None = None, backup_count: int | None = None
) -> None:
    try:
        size_limit = _LOG_MAX_BYTES if max_bytes is None else max_bytes
        keep_count = _LOG_BACKUP_COUNT if backup_count is None else backup_count
        if LOG_PATH.stat().st_size <= size_limit:
            return
        oldest = LOG_PATH.with_suffix(f".log.{keep_count}")
        oldest.unlink(missing_ok=True)
        for index in range(keep_count - 1, 0, -1):
            source = LOG_PATH.with_suffix(f".log.{index}")
            if source.exists():
                source.replace(LOG_PATH.with_suffix(f".log.{index + 1}"))
        LOG_PATH.replace(LOG_PATH.with_suffix(".log.1"))
        LOG_PATH.write_text("", encoding="utf-8")
    except OSError:
        pass


def clear_log_file() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("", encoding="utf-8")


def read_log_tail(count: int = 200) -> list[str]:
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max(1, count):]


def read_run_log(run_id: str, count: int = 500) -> list[str]:
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        raise ValueError("실행 ID를 지정해주세요.")
    marker = f"[{clean_run_id}]"
    matched: deque[str] = deque(maxlen=max(1, min(10000, int(count))))
    for path in (LOG_PATH.with_suffix(".log.1"), LOG_PATH):
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    clean = line.rstrip("\r\n")
                    if marker in clean:
                        matched.append(clean)
        except OSError:
            continue
    return list(matched)


def find_node() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js를 찾지 못했습니다. Node.js 18 이상을 설치해주세요.")
    return node


def _command_version(command: str, *arguments: str) -> str:
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run(
        [command, *arguments],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
        **options,
    )
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0].strip() if completed.returncode == 0 and output else ""


def dependency_diagnostics() -> dict[str, Any]:
    def package(name: str, distribution: str, required: bool) -> dict[str, Any]:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = ""
        return {
            "name": name,
            "kind": "required" if required else "optional",
            "available": bool(version),
            "version": version,
            "path": "",
        }

    python_version = ".".join(str(part) for part in sys.version_info[:3])
    checks = [
        {
            "name": "Python",
            "kind": "required",
            "available": sys.version_info >= (3, 10),
            "version": python_version,
            "path": str(Path(sys.executable).resolve()),
        },
        package("PyQt6", "PyQt6", True),
        package("psutil", "psutil", True),
    ]
    node = shutil.which("node") or ""
    checks.append(
        {
            "name": "Node.js",
            "kind": "required",
            "available": bool(node),
            "version": _command_version(node, "--version") if node else "",
            "path": node,
        }
    )
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm") or ""
    checks.append(
        {
            "name": "npm",
            "kind": "setup",
            "available": bool(npm),
            "version": _command_version(npm, "--version") if npm else "",
            "path": npm,
        }
    )
    puppeteer_manifest = ROOT_DIR / "node_modules" / "puppeteer-real-browser" / "package.json"
    puppeteer_version = ""
    if puppeteer_manifest.is_file():
        try:
            puppeteer_version = str(
                json.loads(puppeteer_manifest.read_text(encoding="utf-8")).get("version")
                or ""
            )
        except (OSError, json.JSONDecodeError):
            puppeteer_version = ""
    checks.append(
        {
            "name": "puppeteer-real-browser",
            "kind": "required",
            "available": bool(puppeteer_version),
            "version": puppeteer_version,
            "path": str(puppeteer_manifest.parent) if puppeteer_manifest.is_file() else "",
        }
    )
    checks.append(package("Pillow", "Pillow", False))
    checks.append(package("ImageHash", "ImageHash", False))
    checks.append(package("py7zr", "py7zr", False))
    checks.append(package("rarfile", "rarfile", False))
    for name, executable, version_argument in (
        ("FFmpeg", "ffmpeg", "-version"),
        ("yt-dlp", "yt-dlp", "--version"),
    ):
        path = shutil.which(executable) or ""
        checks.append(
            {
                "name": name,
                "kind": "optional",
                "available": bool(path),
                "version": _command_version(path, version_argument) if path else "",
                "path": path,
            }
        )
    checks.append(package("PyInstaller", "PyInstaller", False))
    required = [item for item in checks if item["kind"] == "required"]
    missing_required = [item["name"] for item in required if not item["available"]]
    optional = [item for item in checks if item["kind"] == "optional"]
    schemas = {
        "config": config_schema_status(),
        "database": database_schema_status(),
    }
    return {
        "ok": not missing_required and all(item["ok"] for item in schemas.values()),
        "platform": {
            "appVersion": APP_VERSION,
            "system": os.name,
            "pythonArchitecture": 64 if sys.maxsize > 2**32 else 32,
            "root": str(ROOT_DIR),
        },
        "required": {
            "passed": len(required) - len(missing_required),
            "total": len(required),
            "missing": missing_required,
        },
        "optional": {
            "available": sum(1 for item in optional if item["available"]),
            "total": len(optional),
        },
        "checks": checks,
        "schemas": schemas,
    }


def validate_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("URL을 입력해주세요.")
    if not re.match(r"^https://", value, re.IGNORECASE):
        raise ValueError("https://로 시작하는 작품 목록 URL을 입력해주세요.")
    return value


def normalize_range(start: int | None, last: int | None) -> tuple[int | None, int | None]:
    start_value = None if not start else int(start)
    last_value = None if not last else int(last)
    if start_value is not None and start_value < 1:
        raise ValueError("시작 회차는 1 이상이어야 합니다.")
    if last_value is not None and last_value < 1:
        raise ValueError("마지막 회차는 1 이상이어야 합니다.")
    if start_value is not None and last_value is not None and start_value > last_value:
        raise ValueError("시작 회차가 마지막 회차보다 클 수 없습니다.")
    return start_value, last_value


def normalize_image_concurrency(value: int | None) -> int:
    concurrency = int(value or 5)
    if not 1 <= concurrency <= 16:
        raise ValueError("이미지 동시 다운로드 수는 1~16 사이여야 합니다.")
    return concurrency


def normalize_work_concurrency(value: int | None) -> int:
    concurrency = int(value or 1)
    if not 1 <= concurrency <= 4:
        raise ValueError("작품 동시 다운로드 수는 1~4 사이여야 합니다.")
    return concurrency


def available_work_slots(active_count: int, work_concurrency: int | None) -> int:
    active = max(0, int(active_count))
    return max(0, normalize_work_concurrency(work_concurrency) - active)


def resource_budget(
    cpu_count: int | None = None,
    available_memory_bytes: int | None = None,
) -> dict[str, Any]:
    cpu = max(1, int(cpu_count or os.cpu_count() or 1))
    memory = int(
        available_memory_bytes
        if available_memory_bytes is not None
        else psutil.virtual_memory().available
    )
    io_threads = max(2, min(8, cpu))
    cpu_processes = max(1, min(4, cpu // 4 or 1))
    if memory < 4 * 1024 * 1024 * 1024:
        io_threads = min(io_threads, 4)
        cpu_processes = 1
    return {
        "cpuCount": cpu,
        "availableMemoryBytes": max(0, memory),
        "ioThreads": io_threads,
        "maxIoTasks": io_threads * 4,
        "cpuProcesses": cpu_processes,
        "maxPendingDownloads": 1_000,
        "maxLoadedJobs": 2_000,
        "maxProcessOutputBytes": 2 * 1024 * 1024,
    }


def resource_admission(
    kind: str,
    *,
    active_count: int = 0,
    queued_count: int = 0,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    limits = budget or resource_budget()
    normalized = str(kind or "").strip().lower()
    if normalized == "io":
        limit = int(limits["maxIoTasks"])
        used = max(0, int(active_count)) + max(0, int(queued_count))
    elif normalized == "cpu":
        limit = int(limits["cpuProcesses"])
        used = max(0, int(active_count))
    elif normalized == "download_queue":
        limit = int(limits["maxPendingDownloads"])
        used = max(0, int(queued_count))
    else:
        raise ValueError(f"지원하지 않는 자원 종류입니다: {kind}")
    available = max(0, limit - used)
    return {
        "kind": normalized,
        "allowed": used < limit,
        "limit": limit,
        "used": used,
        "available": available,
    }


def append_bounded_text(
    current: str,
    addition: str,
    max_bytes: int,
) -> tuple[str, int]:
    limit = max(1, int(max_bytes))
    combined = f"{current}{addition}".encode("utf-8", errors="replace")
    if len(combined) <= limit:
        return combined.decode("utf-8"), 0
    tail = combined[-limit:]
    while tail and (tail[0] & 0xC0) == 0x80:
        tail = tail[1:]
    kept = tail.decode("utf-8", errors="ignore")
    return kept, len(combined) - len(kept.encode("utf-8"))


def normalize_scan_mode(value: str | None) -> str:
    mode = str(value or "new").strip().lower()
    if mode not in {"new", "full", "range"}:
        raise ValueError("검사 방식은 new, full, range 중 하나여야 합니다.")
    return mode


def normalize_scan_request(
    mode: str | None,
    start: int | None,
    last: int | None,
) -> tuple[str, int | None, int | None]:
    scan_mode = normalize_scan_mode(mode)
    start_value, last_value = normalize_range(start, last)
    if scan_mode == "range" and start_value is None and last_value is None:
        raise ValueError("지정 범위 검사는 시작 또는 마지막 회차가 필요합니다.")
    if scan_mode != "range":
        start_value = None
        last_value = None
    return scan_mode, start_value, last_value


def normalize_retry_count(value: int | None) -> int:
    count = 2 if value is None else int(value)
    if not 0 <= count <= 5:
        raise ValueError("자동 재시도 횟수는 0~5 사이여야 합니다.")
    return count


def normalize_retry_backoff(value: int | None) -> int:
    seconds = 2 if value is None else int(value)
    if not 1 <= seconds <= 60:
        raise ValueError("재시도 기본 대기 시간은 1~60초 사이여야 합니다.")
    return seconds


def normalize_error_category(value: str | None) -> str:
    category = str(value or "unknown").strip().lower()
    return category if category in ERROR_CATEGORIES else "unknown"


def error_category_label(value: str | None) -> str:
    return ERROR_CATEGORY_LABELS[normalize_error_category(value)]


def build_job_list_view_state(
    *,
    loading: bool = False,
    error: str = "",
    total_count: int = 0,
    filtered_count: int | None = None,
    query: str = "",
    state: str = "",
) -> dict[str, Any]:
    """Return the shared, machine-readable state for the work list surface."""
    total = max(0, int(total_count or 0))
    filtered = total if filtered_count is None else max(0, int(filtered_count or 0))
    clean_query = str(query or "").strip()
    clean_state = str(state or "").strip()
    clean_error = str(error or "").strip()

    if loading:
        return {
            "state": "loading",
            "title": "작업 목록을 불러오는 중입니다",
            "message": "저장된 작품과 썸네일 정보를 확인하고 있습니다.",
            "action": "",
            "actionLabel": "",
            "total": total,
            "filtered": filtered,
            "query": clean_query,
            "status": clean_state,
        }
    if clean_error:
        return {
            "state": "error",
            "title": "작업 목록을 불러오지 못했습니다",
            "message": clean_error,
            "action": "retry",
            "actionLabel": "다시 시도",
            "total": total,
            "filtered": filtered,
            "query": clean_query,
            "status": clean_state,
        }
    if filtered > 0:
        return {
            "state": "content",
            "title": "",
            "message": "",
            "action": "",
            "actionLabel": "",
            "total": total,
            "filtered": filtered,
            "query": clean_query,
            "status": clean_state,
        }
    if total <= 0 and not clean_query and not clean_state:
        return {
            "state": "empty",
            "title": "아직 등록된 작품이 없습니다",
            "message": "위 URL 입력란에 작품 링크를 넣고 다운로드를 시작하세요.",
            "action": "focus_url",
            "actionLabel": "URL 입력으로 이동",
            "total": 0,
            "filtered": 0,
            "query": "",
            "status": "",
        }
    return {
        "state": "no_results",
        "title": "조건에 맞는 작품이 없습니다",
        "message": "검색어나 상태 필터를 바꾸거나 초기화해 보세요.",
        "action": "reset_filters",
        "actionLabel": "필터 초기화",
        "total": total,
        "filtered": 0,
        "query": clean_query,
        "status": clean_state,
    }


def downloader_event_update_policy(event_name: str) -> dict[str, Any]:
    """Return the shared UI/persistence policy for a downloader JSON event."""
    normalized = str(event_name or "").strip()
    coalesced = normalized in COALESCED_DOWNLOADER_EVENTS
    return {
        "event": normalized,
        "known": normalized in KNOWN_DOWNLOADER_EVENTS,
        "uiMode": "coalesced" if coalesced else "immediate",
        "uiIntervalMs": 100 if coalesced else 0,
        "persistRun": normalized in PERSISTED_DOWNLOADER_EVENTS,
        "terminal": normalized in {"completed", "error"},
    }


def keyboard_shortcut_catalog() -> list[dict[str, Any]]:
    return [
        {**item, "keys": list(item["keys"])}
        for item in KEYBOARD_SHORTCUTS
    ]


def keyboard_shortcut_keys(action_id: str) -> list[str]:
    normalized = str(action_id or "").strip()
    for item in KEYBOARD_SHORTCUTS:
        if item["id"] == normalized:
            return list(item["keys"])
    raise ValueError(f"지원하지 않는 단축키 동작입니다: {action_id}")


def menu_action_availability(
    selected_job: DownloadJob | None,
    *,
    form_url: str = "",
    active_job_ids: tuple[str, ...] | list[str] = (),
    paused_job_ids: tuple[str, ...] | list[str] = (),
    queued_job_ids: tuple[str, ...] | list[str] = (),
) -> dict[str, bool]:
    """Calculate menu/button states without depending on Qt widgets."""
    active = {str(value) for value in active_job_ids if value}
    paused = {str(value) for value in paused_job_ids if value} & active
    queued = {str(value) for value in queued_job_ids if value}
    selected_id = selected_job.job_id if selected_job else ""
    selected_busy = bool(selected_id and selected_id in active | queued)
    can_rescan = bool(selected_job and selected_job.url and not selected_busy)
    return {
        "download.start": bool(str(form_url or "").strip()),
        "job.stop": bool(active),
        "job.pause": bool(active - paused),
        "job.resume": bool(paused),
        "job.rescan_full": can_rescan,
        "job.rescan_new": can_rescan,
        "job.rescan_range": can_rescan,
        "snapshot.export": True,
        "snapshot.import": not active,
        "group.manage": True,
        "archive.inspect": True,
        "duplicates.works": True,
        "folder.open": bool(selected_job and selected_job.output_path),
        "details.open": bool(selected_job),
        "list.activate": bool(selected_job),
        "list.refresh": True,
        "settings.open": True,
        "screenshot.capture": True,
    }


def plan_window_geometry(
    saved: dict[str, Any] | None,
    screens: list[dict[str, Any]],
    *,
    target_screen: str = "",
    center: bool = False,
    minimum_width: int = 720,
    minimum_height: int = 580,
    default_width: int = 860,
    default_height: int = 720,
) -> dict[str, Any]:
    """Plan a logical-pixel window rect that remains visible across monitor/DPI changes."""
    source = saved if isinstance(saved, dict) else {}
    normalized_screens: list[dict[str, Any]] = []
    for index, screen in enumerate(screens or []):
        if not isinstance(screen, dict):
            continue
        try:
            width = max(1, int(screen.get("width") or 0))
            height = max(1, int(screen.get("height") or 0))
            normalized_screens.append(
                {
                    "name": str(screen.get("name") or f"screen-{index + 1}"),
                    "x": int(screen.get("x") or 0),
                    "y": int(screen.get("y") or 0),
                    "width": width,
                    "height": height,
                    "devicePixelRatio": float(screen.get("devicePixelRatio") or 1.0),
                    "primary": bool(screen.get("primary", index == 0)),
                }
            )
        except (TypeError, ValueError):
            continue
    if not normalized_screens:
        width = max(minimum_width, int(source.get("width") or default_width))
        height = max(minimum_height, int(source.get("height") or default_height))
        return {
            "x": int(source.get("x") or 0),
            "y": int(source.get("y") or 0),
            "width": width,
            "height": height,
            "maximized": bool(source.get("maximized", False)),
            "screenName": "",
            "screenDpr": 1.0,
            "relativeX": 0,
            "relativeY": 0,
            "clamped": False,
            "dpiChanged": False,
            "reason": "screen_information_unavailable",
        }

    primary = next(
        (screen for screen in normalized_screens if screen["primary"]),
        normalized_screens[0],
    )
    desired_name = str(target_screen or source.get("screenName") or "").strip()
    target = next(
        (screen for screen in normalized_screens if screen["name"] == desired_name),
        None,
    )

    saved_x = source.get("x")
    saved_y = source.get("y")
    has_position = isinstance(saved_x, (int, float)) and isinstance(saved_y, (int, float))
    requested_width = max(minimum_width, int(source.get("width") or default_width))
    requested_height = max(minimum_height, int(source.get("height") or default_height))

    def intersection_area(screen: dict[str, Any]) -> int:
        if not has_position:
            return 0
        left = max(int(saved_x), screen["x"])
        top = max(int(saved_y), screen["y"])
        right = min(int(saved_x) + requested_width, screen["x"] + screen["width"])
        bottom = min(int(saved_y) + requested_height, screen["y"] + screen["height"])
        return max(0, right - left) * max(0, bottom - top)

    reason = "saved_screen"
    if target is None:
        intersecting = max(normalized_screens, key=intersection_area)
        if intersection_area(intersecting) > 0:
            target = intersecting
            reason = "intersecting_screen"
        else:
            target = primary
            reason = "primary_fallback"
    elif target_screen:
        reason = "requested_screen"

    width = min(requested_width, target["width"])
    height = min(requested_height, target["height"])
    if center or not has_position:
        x = target["x"] + (target["width"] - width) // 2
        y = target["y"] + (target["height"] - height) // 2
        reason = "centered" if center else f"{reason}_centered"
    else:
        x = int(saved_x)
        y = int(saved_y)
        saved_screen_name = str(source.get("screenName") or "")
        if (
            not target_screen
            and saved_screen_name
            and saved_screen_name != target["name"]
        ):
            relative_x = source.get("relativeX")
            relative_y = source.get("relativeY")
            if isinstance(relative_x, (int, float)) and isinstance(relative_y, (int, float)):
                x = target["x"] + int(relative_x)
                y = target["y"] + int(relative_y)
                reason = f"{reason}_relative"
        maximum_x = target["x"] + target["width"] - width
        maximum_y = target["y"] + target["height"] - height
        x = min(max(x, target["x"]), maximum_x)
        y = min(max(y, target["y"]), maximum_y)

    saved_dpr = source.get("screenDpr")
    try:
        dpi_changed = saved_dpr is not None and abs(float(saved_dpr) - target["devicePixelRatio"]) > 0.01
    except (TypeError, ValueError):
        dpi_changed = False
    clamped = bool(
        width != requested_width
        or height != requested_height
        or (has_position and (x != int(saved_x) or y != int(saved_y)))
    )
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "maximized": bool(source.get("maximized", False)),
        "screenName": target["name"],
        "screenDpr": target["devicePixelRatio"],
        "relativeX": x - target["x"],
        "relativeY": y - target["y"],
        "available": {
            "x": target["x"],
            "y": target["y"],
            "width": target["width"],
            "height": target["height"],
        },
        "clamped": clamped,
        "dpiChanged": dpi_changed,
        "reason": reason,
    }


def retry_backoff_seconds(retry_number: int, base_seconds: int | None) -> int:
    retry = max(1, int(retry_number))
    base = normalize_retry_backoff(base_seconds)
    return min(300, base * (2 ** (retry - 1)))


def should_auto_retry(
    *,
    exit_code: int,
    cancel_requested: bool,
    attempt_count: int,
    retry_limit: int,
    error_category: str | None = None,
    retryable_hint: bool | None = None,
) -> bool:
    category = normalize_error_category(error_category)
    return (
        int(exit_code) != 0
        and not cancel_requested
        and int(attempt_count) <= normalize_retry_count(retry_limit)
        and retryable_hint is not False
        and category not in NON_RETRYABLE_ERROR_CATEGORIES
    )


@dataclass
class DownloadJob:
    job_id: str
    url: str
    output_dir: str
    work_key: str = ""
    start: int | None = None
    last: int | None = None
    title: str = "메타데이터 확인 중"
    state: str = "대기"
    output_path: str = ""
    cover_url: str = ""
    cover_path: str = ""
    author: str = ""
    group: str = ""
    site: str = ""
    metadata_path: str = ""
    user_note: str = ""
    pinned: bool = False
    tag_color: str = ""
    show_browser: bool = False
    metadata_only: bool = False
    scan_mode: str = "new"
    queue_position: int = 0
    image_concurrency: int = 5
    attempt_count: int = 0
    retry_limit: int = 2
    retry_backoff_seconds: int = 2
    episode_index: int = 0
    episode_total: int = 0
    episode_number: int = 0
    image_current: int = 0
    image_total: int = 0
    progress: int = 0
    error: str = ""
    error_category: str = ""
    retryable_error: bool | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if not self.work_key:
            self.work_key = build_work_key(self.url)
        self.scan_mode = normalize_scan_mode(self.scan_mode)
        self.retry_limit = normalize_retry_count(self.retry_limit)
        self.retry_backoff_seconds = normalize_retry_backoff(self.retry_backoff_seconds)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadRun:
    run_id: str
    work_key: str
    requested_start: int | None = None
    requested_last: int | None = None
    operation: str = "download"
    state: str = "대기"
    process_pid: int = 0
    discovered_episodes: int = 0
    selected_episodes: int = 0
    processed_episodes: int = 0
    last_episode_number: int = 0
    progress: int = 0
    attempt_count: int = 0
    retry_limit: int = 2
    retry_backoff_seconds: int = 2
    error: str = ""
    error_category: str = ""
    retryable_error: bool | None = None
    started_at: str = ""
    finished_at: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_job(cls, job: DownloadJob) -> "DownloadRun":
        finished_at = (
            job.created_at
            if job.state in {"완료", "오류", "인증 필요", "중지됨"}
            else ""
        )
        return cls(
            run_id=job.job_id,
            work_key=job.work_key,
            requested_start=job.start,
            requested_last=job.last,
            operation=(
                "metadata_refresh"
                if job.metadata_only
                else f"download_{normalize_scan_mode(job.scan_mode)}"
            ),
            state=job.state,
            selected_episodes=job.episode_total,
            processed_episodes=job.episode_index,
            last_episode_number=job.episode_number,
            progress=job.progress,
            attempt_count=job.attempt_count,
            retry_limit=job.retry_limit,
            retry_backoff_seconds=job.retry_backoff_seconds,
            error=job.error,
            error_category=job.error_category,
            retryable_error=job.retryable_error,
            finished_at=finished_at,
            created_at=job.created_at,
        )


def build_work_key(url: str) -> str:
    value = str(url or "").strip()
    match = re.search(r"/(novel|webtoon|comic|manhwa)/(\d+)", value, re.IGNORECASE)
    if match:
        content_type = match.group(1).lower()
        site = {
            "novel": "booktoki",
            "webtoon": "newtoki",
            "comic": "manatoki",
            "manhwa": "manatoki",
        }[content_type]
        return f"{site}:{match.group(2)}"
    parsed = urlsplit(value)
    normalized_path = parsed.path.rstrip("/").lower()
    return f"url:{parsed.hostname or ''}{normalized_path}"


def _connect_job_db(database_path: Path | None = None) -> sqlite3.Connection:
    path = Path(database_path) if database_path is not None else JOB_DB_PATH
    existed_before = path.is_file()
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    database_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if database_version > JOB_DB_SCHEMA_VERSION:
        connection.close()
        raise RuntimeError(
            f"이 프로그램보다 새로운 작업 DB 버전입니다: {database_version}"
        )
    database_key = str(path.resolve())
    backup_path = ""
    if existed_before and database_version < JOB_DB_SCHEMA_VERSION:
        backup = path.with_suffix(path.suffix + f".pre-v{JOB_DB_SCHEMA_VERSION}.bak")
        if not backup.exists():
            backup_connection = sqlite3.connect(backup)
            try:
                connection.backup(backup_connection)
            finally:
                backup_connection.close()
        backup_path = str(backup.resolve())
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            work_key TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            progress INTEGER NOT NULL DEFAULT 0,
            url TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            metadata_group TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            tag_color TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            work_key TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT '',
            process_pid INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    if database_key not in _INITIALIZED_JOB_DBS:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "work_key" not in columns:
            connection.execute(
                "ALTER TABLE jobs ADD COLUMN work_key TEXT NOT NULL DEFAULT ''"
            )
        for column, definition in (
            ("title", "TEXT NOT NULL DEFAULT ''"),
            ("state", "TEXT NOT NULL DEFAULT ''"),
            ("progress", "INTEGER NOT NULL DEFAULT 0"),
            ("url", "TEXT NOT NULL DEFAULT ''"),
            ("author", "TEXT NOT NULL DEFAULT ''"),
            ("metadata_group", "TEXT NOT NULL DEFAULT ''"),
            ("pinned", "INTEGER NOT NULL DEFAULT 0"),
            ("tag_color", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
        rows = connection.execute(
            "SELECT job_id, payload FROM jobs ORDER BY updated_at DESC, rowid DESC"
        ).fetchall()
        seen: set[str] = set()
        for job_id, payload in rows:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {}
            work_key = str(data.get("work_key") or build_work_key(data.get("url", "")))
            if work_key in seen:
                connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                continue
            seen.add(work_key)
            data["work_key"] = work_key
            connection.execute(
                """
                UPDATE jobs
                SET work_key = ?, title = ?, state = ?, progress = ?, url = ?,
                    author = ?, metadata_group = ?, pinned = ?, tag_color = ?, payload = ?
                WHERE job_id = ?
                """,
                (
                    work_key,
                    str(data.get("title") or ""),
                    str(data.get("state") or ""),
                    int(data.get("progress") or 0),
                    str(data.get("url") or ""),
                    str(data.get("author") or ""),
                    str(data.get("group") or ""),
                    int(bool(data.get("pinned", False))),
                    str(data.get("tag_color") or ""),
                    json.dumps(data, ensure_ascii=False),
                    job_id,
                ),
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_work_key ON jobs(work_key)"
        )
        run_field_names = set(DownloadRun.__dataclass_fields__)
        for job_id, payload in connection.execute(
            "SELECT job_id, payload FROM jobs ORDER BY updated_at ASC, rowid ASC"
        ).fetchall():
            try:
                data = json.loads(payload)
                filtered = {key: value for key, value in data.items() if key in set(DownloadJob.__dataclass_fields__)}
                legacy_run = DownloadRun.from_job(DownloadJob(**filtered))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            run_data = {key: value for key, value in legacy_run.to_dict().items() if key in run_field_names}
            connection.execute(
                """
                INSERT OR IGNORE INTO runs(
                    run_id, work_key, state, process_pid, created_at,
                    started_at, finished_at, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    legacy_run.work_key,
                    legacy_run.state,
                    legacy_run.process_pid,
                    legacy_run.created_at,
                    legacy_run.started_at,
                    legacy_run.finished_at,
                    legacy_run.created_at,
                    json.dumps(run_data, ensure_ascii=False),
                ),
            )
        connection.commit()
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title COLLATE NOCASE)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_author ON jobs(author COLLATE NOCASE)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_metadata_group "
        "ON jobs(metadata_group COLLATE NOCASE)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_state_updated ON jobs(state, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_progress ON jobs(progress DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_pinned_updated ON jobs(pinned DESC, updated_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_work_created ON runs(work_key, created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_state_updated ON runs(state, updated_at DESC)"
    )
    for index_name, columns in JOB_QUERY_INDEXES.items():
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON jobs({columns})"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS work_collections (
            collection_id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS work_collection_memberships (
            work_key TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(work_key) REFERENCES jobs(work_key) ON DELETE CASCADE,
            FOREIGN KEY(collection_id) REFERENCES work_collections(collection_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_memberships_group "
        "ON work_collection_memberships(collection_id, updated_at DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied_versions = list(range(database_version + 1, JOB_DB_SCHEMA_VERSION + 1))
    applied_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for version in applied_versions:
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (version, JOB_DB_MIGRATIONS[version], applied_at),
        )
    connection.execute(f"PRAGMA user_version = {JOB_DB_SCHEMA_VERSION}")
    connection.commit()
    _INITIALIZED_JOB_DBS.add(database_key)
    if applied_versions or database_key not in _DATABASE_MIGRATION_REPORTS:
        _DATABASE_MIGRATION_REPORTS[database_key] = {
            "path": database_key,
            "fromVersion": database_version,
            "toVersion": JOB_DB_SCHEMA_VERSION,
            "appliedVersions": applied_versions,
            "backupPath": backup_path,
        }
    return connection


def database_schema_status(database_path: Path | None = None) -> dict[str, Any]:
    path = Path(database_path) if database_path is not None else JOB_DB_PATH
    if not path.is_file():
        return {
            "ok": True,
            "exists": False,
            "path": str(path.resolve()),
            "version": 0,
            "currentVersion": JOB_DB_SCHEMA_VERSION,
            "needsMigration": False,
            "migrations": [],
            "lastMigration": None,
        }
    connection = sqlite3.connect(path, timeout=10)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        has_history = bool(
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
        )
        migrations = (
            [
                {"version": int(row[0]), "name": str(row[1]), "appliedAt": str(row[2])}
                for row in connection.execute(
                    "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]
            if has_history
            else []
        )
    finally:
        connection.close()
    return {
        "ok": version <= JOB_DB_SCHEMA_VERSION,
        "exists": True,
        "path": str(path.resolve()),
        "version": version,
        "currentVersion": JOB_DB_SCHEMA_VERSION,
        "needsMigration": version < JOB_DB_SCHEMA_VERSION,
        "futureVersion": version > JOB_DB_SCHEMA_VERSION,
        "migrations": migrations,
        "lastMigration": _DATABASE_MIGRATION_REPORTS.get(str(path.resolve())),
    }


def apply_database_migrations(database_path: Path | None = None) -> dict[str, Any]:
    path = Path(database_path) if database_path is not None else JOB_DB_PATH
    before = database_schema_status(path)
    _INITIALIZED_JOB_DBS.discard(str(path.resolve()))
    connection = _connect_job_db(path)
    connection.close()
    after = database_schema_status(path)
    return {
        "ok": bool(after["ok"] and not after["needsMigration"]),
        "before": before,
        "after": after,
        "migration": _DATABASE_MIGRATION_REPORTS.get(str(path.resolve())),
    }


def save_jobs(
    jobs: list[DownloadJob], *, database_path: Path | None = None
) -> None:
    if not jobs:
        return
    updated_at = datetime.now().astimezone().isoformat(timespec="microseconds")
    rows = [
        (
            job.job_id,
            job.work_key,
            job.title,
            job.state,
            job.progress,
            job.url,
            job.author,
            job.group,
            int(job.pinned),
            job.tag_color,
            job.created_at,
            updated_at,
            json.dumps(job.to_dict(), ensure_ascii=False),
        )
        for job in jobs
    ]
    connection = _connect_job_db(database_path)
    try:
        with connection:
            connection.executemany(
                """
            INSERT INTO jobs(
                job_id, work_key, title, state, progress, url, author, metadata_group,
                pinned, tag_color,
                created_at, updated_at, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_key) DO UPDATE SET
                job_id=excluded.job_id,
                title=excluded.title,
                state=excluded.state,
                progress=excluded.progress,
                url=excluded.url,
                author=excluded.author,
                metadata_group=excluded.metadata_group,
                pinned=excluded.pinned,
                tag_color=excluded.tag_color,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                payload=excluded.payload
                """,
                rows,
            )
    finally:
        connection.close()


def save_runs(
    runs: list[DownloadRun], *, database_path: Path | None = None
) -> None:
    if not runs:
        return
    updated_at = datetime.now().astimezone().isoformat(timespec="microseconds")
    rows = [
        (
            run.run_id,
            run.work_key,
            run.state,
            int(run.process_pid),
            run.created_at,
            run.started_at,
            run.finished_at,
            updated_at,
            json.dumps(run.to_dict(), ensure_ascii=False),
        )
        for run in runs
    ]
    connection = _connect_job_db(database_path)
    try:
        with connection:
            connection.executemany(
                """
                INSERT INTO runs(
                    run_id, work_key, state, process_pid, created_at,
                    started_at, finished_at, updated_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    work_key=excluded.work_key,
                    state=excluded.state,
                    process_pid=excluded.process_pid,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                rows,
            )
    finally:
        connection.close()


def count_runs(work_key: str = "") -> int:
    connection = _connect_job_db()
    try:
        if work_key:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM runs WHERE work_key = ?", (work_key,)
                ).fetchone()[0]
            )
        return int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
    finally:
        connection.close()


def load_run(run_id: str) -> DownloadRun | None:
    connection = _connect_job_db()
    try:
        row = connection.execute(
            "SELECT payload FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        connection.close()
    return _decode_run(row[0]) if row else None


def load_runs_page(
    work_key: str,
    limit: int = 100,
    offset: int = 0,
) -> list[DownloadRun]:
    connection = _connect_job_db()
    try:
        rows = connection.execute(
            """
            SELECT payload FROM runs
            WHERE work_key = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            (work_key, max(1, min(1000, int(limit))), max(0, int(offset))),
        ).fetchall()
    finally:
        connection.close()
    return [run for (payload,) in rows if (run := _decode_run(payload)) is not None]


def log_retention_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = normalize_config(config) if config is not None else load_config()
    max_bytes = int(policy["logMaxMiB"]) * 1024 * 1024
    backup_count = int(policy["logBackupCount"])
    paths = [LOG_PATH]
    if LOG_PATH.parent.exists():
        paths.extend(
            sorted(
                path
                for path in LOG_PATH.parent.glob(f"{LOG_PATH.name}.*")
                if path.is_file()
            )
        )
    files = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(
            {
                "path": str(path.resolve()),
                "bytes": int(stat.st_size),
                "modifiedAt": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
                    timespec="seconds"
                ),
            }
        )
    return {
        "ok": True,
        "path": str(LOG_PATH.resolve()),
        "maxBytes": max_bytes,
        "backupCount": backup_count,
        "fileCount": len(files),
        "totalBytes": sum(item["bytes"] for item in files),
        "files": files,
    }


def cleanup_run_history(
    *,
    max_per_work: int = 500,
    max_age_days: int = 365,
    execute: bool = False,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Preview or delete old terminal runs while preserving latest and active runs."""
    safe_max_per_work = max(1, min(10_000, int(max_per_work)))
    safe_max_age_days = max(1, min(10_000, int(max_age_days)))
    cutoff = (
        datetime.now().astimezone() - timedelta(days=safe_max_age_days)
    ).isoformat(timespec="seconds")
    active_states = tuple(sorted(ACTIVE_JOB_STATES))
    placeholders = ", ".join("?" for _state in active_states)
    ranked_sql = f"""
        WITH ranked AS (
            SELECT run_id, work_key, state, created_at, LENGTH(payload) AS payload_bytes,
                   ROW_NUMBER() OVER (
                       PARTITION BY work_key
                       ORDER BY created_at DESC, run_id DESC
                   ) AS work_position
            FROM runs
        )
    """
    candidate_where = f"""
        work_position > 1
        AND state NOT IN ({placeholders})
        AND (work_position > ? OR created_at < ?)
    """
    parameters: list[Any] = [*active_states, safe_max_per_work, cutoff]
    connection = _connect_job_db(database_path)
    try:
        total_before = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        candidate_row = connection.execute(
            ranked_sql
            + f"""
                SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0),
                       COUNT(DISTINCT work_key)
                FROM ranked WHERE {candidate_where}
            """,
            parameters,
        ).fetchone()
        sample_ids = [
            str(row[0])
            for row in connection.execute(
                ranked_sql
                + f"""
                    SELECT run_id FROM ranked WHERE {candidate_where}
                    ORDER BY created_at ASC, run_id ASC LIMIT 100
                """,
                parameters,
            ).fetchall()
        ]
        candidate_count = int(candidate_row[0] or 0)
        candidate_bytes = int(candidate_row[1] or 0)
        work_count = int(candidate_row[2] or 0)
        removed_count = 0
        if execute and candidate_count:
            with connection:
                connection.execute(
                    ranked_sql
                    + f"""
                        DELETE FROM runs WHERE run_id IN (
                            SELECT run_id FROM ranked WHERE {candidate_where}
                        )
                    """,
                    parameters,
                )
                removed_count = int(connection.execute("SELECT changes()").fetchone()[0])
        total_after = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
    finally:
        connection.close()
    return {
        "ok": not execute or removed_count == candidate_count,
        "executed": bool(execute),
        "totalBefore": total_before,
        "totalAfter": total_after,
        "candidateRuns": candidate_count,
        "candidateBytes": candidate_bytes,
        "affectedWorks": work_count,
        "removedRuns": removed_count,
        "sampleRunIds": sample_ids,
        "cutoff": cutoff,
        "policy": {
            "maxPerWork": safe_max_per_work,
            "maxAgeDays": safe_max_age_days,
            "preserveLatestPerWork": True,
            "preserveActive": True,
        },
    }


def _decode_run(payload: str) -> DownloadRun | None:
    try:
        data = json.loads(payload)
        field_names = set(DownloadRun.__dataclass_fields__)
        return DownloadRun(**{key: value for key, value in data.items() if key in field_names})
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _job_filter_clause(query: str = "", state: str = "") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    parameters: list[Any] = []
    clean_query = str(query or "").strip()
    clean_state = str(state or "").strip()
    if clean_query:
        pattern = f"%{clean_query}%"
        clauses.append(
            "(title LIKE ? COLLATE NOCASE OR author LIKE ? COLLATE NOCASE "
            "OR metadata_group LIKE ? COLLATE NOCASE OR job_id LIKE ? COLLATE NOCASE "
            "OR work_key LIKE ? COLLATE NOCASE OR url LIKE ? COLLATE NOCASE "
            "OR EXISTS ("
            "SELECT 1 FROM work_collection_memberships AS m "
            "JOIN work_collections AS c ON c.collection_id = m.collection_id "
            "WHERE m.work_key = jobs.work_key AND c.name LIKE ? COLLATE NOCASE))"
        )
        parameters.extend([pattern] * 7)
    if clean_state:
        clauses.append("state = ?")
        parameters.append(clean_state)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", parameters


def count_jobs(query: str = "", state: str = "") -> int:
    where_sql, parameters = _job_filter_clause(query, state)
    connection = _connect_job_db()
    try:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM jobs{where_sql}", parameters
            ).fetchone()[0]
        )
    finally:
        connection.close()


def load_job_by_work_key(work_key: str) -> DownloadJob | None:
    return _load_job("work_key", work_key)


def load_job_by_id(job_id: str) -> DownloadJob | None:
    return _load_job("job_id", job_id)


def _load_job(column: str, value: str) -> DownloadJob | None:
    if column not in {"job_id", "work_key"}:
        raise ValueError("지원하지 않는 작품 조회 열입니다.")
    field_names = set(DownloadJob.__dataclass_fields__)
    connection = _connect_job_db()
    try:
        row = connection.execute(
            f"SELECT payload FROM jobs WHERE {column} = ?",
            (value,),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    try:
        data = json.loads(row[0])
        filtered = {key: value for key, value in data.items() if key in field_names}
        return DownloadJob(**filtered)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def load_jobs_page(
    limit: int = 200,
    offset: int = 0,
    query: str = "",
    state: str = "",
    sort: str = "updated",
    *,
    database_path: Path | None = None,
) -> list[DownloadJob]:
    field_names = set(DownloadJob.__dataclass_fields__)
    order_by = JOB_SORT_ORDERS.get(sort)
    if order_by is None:
        raise ValueError(f"지원하지 않는 작업 정렬입니다: {sort}")
    where_sql, parameters = _job_filter_clause(query, state)
    connection = _connect_job_db(database_path)
    try:
        rows = connection.execute(
            f"SELECT payload FROM jobs{where_sql} ORDER BY {order_by} LIMIT ? OFFSET ?",
            [*parameters, max(1, min(1000, int(limit))), max(0, int(offset))],
        ).fetchall()
    finally:
        connection.close()
    jobs: list[DownloadJob] = []
    for (payload,) in rows:
        try:
            data = json.loads(payload)
            filtered = {key: value for key, value in data.items() if key in field_names}
            jobs.append(DownloadJob(**filtered))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return jobs


def export_jobs_snapshot(
    output_path: Path, *, database_path: Path | None = None
) -> dict[str, Any]:
    """Export work records and run history without reading download files."""
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect_job_db(database_path)
    try:
        job_payloads = connection.execute(
            "SELECT payload FROM jobs ORDER BY updated_at ASC, job_id ASC"
        ).fetchall()
        run_payloads = connection.execute(
            "SELECT payload FROM runs ORDER BY created_at ASC, run_id ASC"
        ).fetchall()
    finally:
        connection.close()
    jobs = [
        job.to_dict()
        for (payload,) in job_payloads
        if (job := _decode_job_payload(payload)) is not None
    ]
    runs = [
        run.to_dict()
        for (payload,) in run_payloads
        if (run := _decode_run(payload)) is not None
    ]
    payload = {
        "format": "tokiDownloader-jobs",
        "formatVersion": 1,
        "appVersion": APP_VERSION,
        "exportedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "jobs": jobs,
        "runs": runs,
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return {
        "ok": True,
        "path": str(target),
        "bytes": target.stat().st_size,
        "jobCount": len(jobs),
        "runCount": len(runs),
    }


def _decode_job_payload(payload: str | dict[str, Any]) -> DownloadJob | None:
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(data, dict):
            return None
        fields = set(DownloadJob.__dataclass_fields__)
        return DownloadJob(**{key: value for key, value in data.items() if key in fields})
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def import_jobs_snapshot(
    input_path: Path,
    *,
    execute: bool = False,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Preview or add missing work/run records; existing records are never overwritten."""
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"작업 스냅샷 파일이 없습니다: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != "tokiDownloader-jobs":
        raise ValueError("tokiDownloader 작업 스냅샷 JSON이 아닙니다.")
    if int(payload.get("formatVersion") or 0) != 1:
        raise ValueError("지원하지 않는 작업 스냅샷 버전입니다.")
    raw_jobs = payload.get("jobs")
    raw_runs = payload.get("runs")
    if not isinstance(raw_jobs, list) or not isinstance(raw_runs, list):
        raise ValueError("작업 스냅샷의 jobs와 runs는 배열이어야 합니다.")

    connection = _connect_job_db(database_path)
    try:
        existing_rows = connection.execute("SELECT job_id, work_key FROM jobs").fetchall()
        existing_job_ids = {str(row[0]) for row in existing_rows}
        existing_work_keys = {str(row[1]) for row in existing_rows}
        existing_run_ids = {
            str(row[0]) for row in connection.execute("SELECT run_id FROM runs").fetchall()
        }
    finally:
        connection.close()

    jobs: list[DownloadJob] = []
    incoming_work_keys: set[str] = set()
    skipped_existing_works = 0
    invalid_jobs = 0
    remapped_job_ids = 0
    for raw_job in raw_jobs:
        job = _decode_job_payload(raw_job)
        if not job or not job.job_id or not job.work_key:
            invalid_jobs += 1
            continue
        if job.work_key in existing_work_keys or job.work_key in incoming_work_keys:
            skipped_existing_works += 1
            continue
        if job.job_id in existing_job_ids:
            job.job_id = uuid.uuid4().hex[:10]
            remapped_job_ids += 1
        if job.state in ACTIVE_JOB_STATES:
            job.state = "중지됨"
            job.error = "스냅샷에서 복원된 미완료 작업"
            job.error_category = "cancelled"
            job.retryable_error = False
        job.queue_position = 0
        jobs.append(job)
        incoming_work_keys.add(job.work_key)
        existing_job_ids.add(job.job_id)

    available_work_keys = existing_work_keys | incoming_work_keys
    runs: list[DownloadRun] = []
    incoming_run_ids: set[str] = set()
    skipped_existing_runs = 0
    orphan_runs = 0
    invalid_runs = 0
    restored_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for raw_run in raw_runs:
        if not isinstance(raw_run, dict):
            invalid_runs += 1
            continue
        try:
            fields = set(DownloadRun.__dataclass_fields__)
            run = DownloadRun(
                **{key: value for key, value in raw_run.items() if key in fields}
            )
        except (TypeError, ValueError):
            invalid_runs += 1
            continue
        if not run.run_id or not run.work_key:
            invalid_runs += 1
            continue
        if run.work_key not in available_work_keys:
            orphan_runs += 1
            continue
        if run.run_id in existing_run_ids or run.run_id in incoming_run_ids:
            skipped_existing_runs += 1
            continue
        if run.state in ACTIVE_JOB_STATES:
            run.state = "중지됨"
            run.process_pid = 0
            run.finished_at = restored_at
            run.error = "스냅샷에서 복원된 미완료 실행"
            run.error_category = "cancelled"
            run.retryable_error = False
        runs.append(run)
        incoming_run_ids.add(run.run_id)

    if invalid_jobs or invalid_runs:
        raise ValueError(
            f"손상된 스냅샷 항목이 있습니다: jobs {invalid_jobs}, runs {invalid_runs}"
        )
    if execute:
        save_jobs(jobs, database_path=database_path)
        save_runs(runs, database_path=database_path)
    return {
        "ok": True,
        "executed": bool(execute),
        "path": str(source),
        "sourceJobCount": len(raw_jobs),
        "sourceRunCount": len(raw_runs),
        "pendingJobs": len(jobs),
        "pendingRuns": len(runs),
        "importedJobs": len(jobs) if execute else 0,
        "importedRuns": len(runs) if execute else 0,
        "skippedExistingWorks": skipped_existing_works,
        "skippedExistingRuns": skipped_existing_runs,
        "orphanRuns": orphan_runs,
        "remappedJobIds": remapped_job_ids,
        "downloadFilesChanged": False,
    }


def _normalize_collection_name(name: str) -> str:
    value = " ".join(str(name or "").split())
    if not value:
        raise ValueError("그룹 이름을 입력해주세요.")
    if len(value) > 100:
        raise ValueError("그룹 이름은 100자 이하여야 합니다.")
    return value


def list_work_collections(*, database_path: Path | None = None) -> list[dict[str, Any]]:
    connection = _connect_job_db(database_path)
    try:
        rows = connection.execute(
            """
            SELECT c.collection_id, c.name, c.created_at, c.updated_at,
                   COUNT(m.work_key) AS member_count
            FROM work_collections AS c
            LEFT JOIN work_collection_memberships AS m
              ON m.collection_id = c.collection_id
            GROUP BY c.collection_id
            ORDER BY c.name COLLATE NOCASE ASC, c.collection_id ASC
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "groupId": str(row[0]),
            "name": str(row[1]),
            "createdAt": str(row[2]),
            "updatedAt": str(row[3]),
            "memberCount": int(row[4]),
        }
        for row in rows
    ]


def create_work_collection(
    name: str, *, database_path: Path | None = None
) -> dict[str, Any]:
    clean_name = _normalize_collection_name(name)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    collection_id = uuid.uuid4().hex[:10]
    connection = _connect_job_db(database_path)
    try:
        with connection:
            connection.execute(
                "INSERT INTO work_collections(collection_id, name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (collection_id, clean_name, now, now),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError(f"같은 이름의 그룹이 이미 있습니다: {clean_name}") from error
    finally:
        connection.close()
    return {
        "groupId": collection_id,
        "name": clean_name,
        "createdAt": now,
        "updatedAt": now,
        "memberCount": 0,
    }


def rename_work_collection(
    collection_id: str,
    name: str,
    *,
    database_path: Path | None = None,
) -> dict[str, Any]:
    clean_id = str(collection_id or "").strip()
    clean_name = _normalize_collection_name(name)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    connection = _connect_job_db(database_path)
    try:
        try:
            with connection:
                cursor = connection.execute(
                    "UPDATE work_collections SET name = ?, updated_at = ? "
                    "WHERE collection_id = ?",
                    (clean_name, now, clean_id),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"같은 이름의 그룹이 이미 있습니다: {clean_name}") from error
        if cursor.rowcount != 1:
            raise ValueError(f"작품 그룹을 찾을 수 없습니다: {clean_id}")
        member_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM work_collection_memberships WHERE collection_id = ?",
                (clean_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return {
        "groupId": clean_id,
        "name": clean_name,
        "updatedAt": now,
        "memberCount": member_count,
    }


def assign_job_to_collection(
    job_id: str,
    collection_id: str | None,
    *,
    database_path: Path | None = None,
) -> dict[str, Any]:
    clean_job_id = str(job_id or "").strip()
    clean_collection_id = str(collection_id or "").strip()
    connection = _connect_job_db(database_path)
    try:
        row = connection.execute(
            "SELECT work_key FROM jobs WHERE job_id = ?", (clean_job_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"작업 기록을 찾을 수 없습니다: {clean_job_id}")
        work_key = str(row[0])
        if clean_collection_id:
            group_row = connection.execute(
                "SELECT name FROM work_collections WHERE collection_id = ?",
                (clean_collection_id,),
            ).fetchone()
            if not group_row:
                raise ValueError(f"작품 그룹을 찾을 수 없습니다: {clean_collection_id}")
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            with connection:
                connection.execute(
                    """
                    INSERT INTO work_collection_memberships(work_key, collection_id, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(work_key) DO UPDATE SET
                        collection_id=excluded.collection_id,
                        updated_at=excluded.updated_at
                    """,
                    (work_key, clean_collection_id, now),
                )
            group = {"groupId": clean_collection_id, "name": str(group_row[0])}
        else:
            with connection:
                connection.execute(
                    "DELETE FROM work_collection_memberships WHERE work_key = ?", (work_key,)
                )
            group = None
    finally:
        connection.close()
    return {
        "ok": True,
        "jobId": clean_job_id,
        "workKey": work_key,
        "group": group,
        "metadataChanged": False,
        "downloadFilesChanged": False,
    }


def work_collection_for_job(
    job_id: str, *, database_path: Path | None = None
) -> dict[str, Any] | None:
    connection = _connect_job_db(database_path)
    try:
        row = connection.execute(
            """
            SELECT c.collection_id, c.name
            FROM jobs AS j
            JOIN work_collection_memberships AS m ON m.work_key = j.work_key
            JOIN work_collections AS c ON c.collection_id = m.collection_id
            WHERE j.job_id = ?
            """,
            (str(job_id or "").strip(),),
        ).fetchone()
    finally:
        connection.close()
    return {"groupId": str(row[0]), "name": str(row[1])} if row else None


def find_duplicate_works(*, database_path: Path | None = None) -> dict[str, Any]:
    """Find suspicious duplicate work records without changing records or folders."""
    jobs: list[DownloadJob] = []
    offset = 0
    while True:
        page = load_jobs_page(
            limit=1000, offset=offset, sort="updated", database_path=database_path
        )
        jobs.extend(page)
        if len(page) < 1000:
            break
        offset += len(page)

    title_groups: dict[tuple[str, str], list[DownloadJob]] = {}
    path_groups: dict[str, list[DownloadJob]] = {}
    ignored_titles = {"", "메타데이터 확인 중".casefold()}
    for job in jobs:
        title = " ".join(str(job.title or "").split()).casefold()
        author = " ".join(str(job.author or "").split()).casefold()
        if title not in ignored_titles:
            title_groups.setdefault((title, author), []).append(job)
        if job.output_path:
            normalized_path = os.path.normcase(
                str(Path(job.output_path).expanduser().resolve())
            ).casefold()
            path_groups.setdefault(normalized_path, []).append(job)

    groups: list[dict[str, Any]] = []
    for (title, author), members in title_groups.items():
        distinct_keys = {member.work_key for member in members}
        if len(distinct_keys) < 2:
            continue
        groups.append(
            {
                "reason": "same_title_author",
                "key": f"{author}|{title}",
                "count": len(members),
                "jobs": [
                    {
                        "jobId": job.job_id,
                        "workKey": job.work_key,
                        "title": job.title,
                        "author": job.author,
                        "url": job.url,
                        "outputPath": job.output_path,
                    }
                    for job in members
                ],
            }
        )
    for path, members in path_groups.items():
        distinct_keys = {member.work_key for member in members}
        if len(distinct_keys) < 2:
            continue
        groups.append(
            {
                "reason": "same_output_path",
                "key": path,
                "count": len(members),
                "jobs": [
                    {
                        "jobId": job.job_id,
                        "workKey": job.work_key,
                        "title": job.title,
                        "author": job.author,
                        "url": job.url,
                        "outputPath": job.output_path,
                    }
                    for job in members
                ],
            }
        )
    groups.sort(key=lambda item: (str(item["reason"]), str(item["key"])))
    duplicate_job_ids = {
        str(job["jobId"]) for group in groups for job in group["jobs"]
    }
    return {
        "ok": True,
        "scannedWorks": len(jobs),
        "duplicateGroupCount": len(groups),
        "duplicateWorkCount": len(duplicate_job_ids),
        "groups": groups,
        "readOnly": True,
        "metadataChanged": False,
        "downloadFilesChanged": False,
    }


ARCHIVE_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
)
SUPPORTED_ARCHIVE_EXTENSIONS = frozenset({".zip", ".cbz", ".7z", ".cb7", ".rar", ".cbr"})


def _archive_path_is_suspicious(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        not normalized
        or normalized.startswith("/")
        or bool(re.match(r"^[A-Za-z]:/", normalized))
        or ".." in path.parts
    )


def inspect_local_archive(archive_path: Path) -> dict[str, Any]:
    """Read archive directory metadata only; never extracts or modifies contents."""
    source = Path(archive_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"압축 파일이 없습니다: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_ARCHIVE_EXTENSIONS:
        raise ValueError(f"지원하지 않는 압축 형식입니다: {suffix or '(확장자 없음)'}")

    entries: list[dict[str, Any]] = []
    dependency = {"name": "stdlib", "available": True, "version": sys.version.split()[0]}
    if suffix in {".zip", ".cbz"}:
        try:
            with zipfile.ZipFile(source) as archive:
                for item in archive.infolist():
                    entries.append(
                        {
                            "name": item.filename,
                            "isDir": item.is_dir(),
                            "size": int(item.file_size),
                            "compressedSize": int(item.compress_size),
                            "encrypted": bool(item.flag_bits & 0x1),
                        }
                    )
        except zipfile.BadZipFile as error:
            raise ValueError(f"손상되었거나 ZIP 형식이 아닌 파일입니다: {source.name}") from error
        archive_format = "zip"
    elif suffix in {".7z", ".cb7"}:
        try:
            import py7zr  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "7Z 검사는 py7zr가 필요합니다. setup-gui.cmd -WithArchiveTools를 실행하세요."
            ) from error
        dependency = {
            "name": "py7zr",
            "available": True,
            "version": importlib.metadata.version("py7zr"),
        }
        with py7zr.SevenZipFile(source, mode="r") as archive:
            for item in archive.list():
                entries.append(
                    {
                        "name": str(item.filename),
                        "isDir": bool(item.is_directory),
                        "size": int(item.uncompressed or 0),
                        "compressedSize": int(item.compressed or 0),
                        "encrypted": False,
                    }
                )
        archive_format = "7z"
    else:
        try:
            import rarfile  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "RAR 검사는 rarfile과 호환 백엔드가 필요합니다. "
                "setup-gui.cmd -WithArchiveTools를 실행하세요."
            ) from error
        dependency = {
            "name": "rarfile",
            "available": True,
            "version": importlib.metadata.version("rarfile"),
        }
        try:
            with rarfile.RarFile(source) as archive:
                for item in archive.infolist():
                    entries.append(
                        {
                            "name": str(item.filename),
                            "isDir": bool(item.is_dir()),
                            "size": int(item.file_size or 0),
                            "compressedSize": int(item.compress_size or 0),
                            "encrypted": bool(item.needs_password()),
                        }
                    )
        except rarfile.Error as error:
            raise ValueError(f"RAR 파일을 읽을 수 없습니다: {error}") from error
        archive_format = "rar"

    files = [entry for entry in entries if not entry["isDir"]]
    suspicious = [entry["name"] for entry in files if _archive_path_is_suspicious(entry["name"])]
    empty = [entry["name"] for entry in files if int(entry["size"]) == 0]
    encrypted = [entry["name"] for entry in files if entry["encrypted"]]
    images = [
        entry
        for entry in files
        if Path(str(entry["name"])).suffix.lower() in ARCHIVE_IMAGE_EXTENSIONS
    ]
    extensions: dict[str, int] = {}
    for entry in files:
        extension = Path(str(entry["name"])).suffix.lower() or "(none)"
        extensions[extension] = extensions.get(extension, 0) + 1
    top_folders = sorted(
        {
            PurePosixPath(str(entry["name"]).replace("\\", "/")).parts[0]
            for entry in files
            if len(PurePosixPath(str(entry["name"]).replace("\\", "/")).parts) > 1
        }
    )
    return {
        "ok": True,
        "healthy": not suspicious,
        "path": str(source),
        "format": archive_format,
        "bytes": source.stat().st_size,
        "dependency": dependency,
        "entryCount": len(entries),
        "fileCount": len(files),
        "folderCount": sum(1 for entry in entries if entry["isDir"]),
        "imageCount": len(images),
        "emptyFileCount": len(empty),
        "encryptedFileCount": len(encrypted),
        "suspiciousPathCount": len(suspicious),
        "totalUncompressedBytes": sum(int(entry["size"]) for entry in files),
        "totalCompressedBytes": sum(int(entry["compressedSize"]) for entry in files),
        "extensions": dict(sorted(extensions.items())),
        "topFolders": top_folders[:100],
        "suspiciousPaths": suspicious[:100],
        "emptyFiles": empty[:100],
        "sample": files[:100],
        "extracted": False,
        "filesChanged": False,
    }


def job_database_diagnostics(database_path: Path | None = None) -> dict[str, Any]:
    """Inspect list query plans without loading every stored work into memory."""
    started = time.perf_counter()
    path = Path(database_path) if database_path is not None else JOB_DB_PATH
    connection = _connect_job_db(path)
    try:
        indexes = sorted(
            str(row[1])
            for row in connection.execute("PRAGMA index_list('jobs')").fetchall()
        )
        query_plans: list[dict[str, Any]] = []
        for state_filtered in (False, True):
            for sort, order_by in JOB_SORT_ORDERS.items():
                where_sql = " WHERE state = ?" if state_filtered else ""
                parameters: list[Any] = ["완료"] if state_filtered else []
                rows = connection.execute(
                    "EXPLAIN QUERY PLAN "
                    f"SELECT payload FROM jobs{where_sql} "
                    f"ORDER BY {order_by} LIMIT ? OFFSET ?",
                    [*parameters, 200, 0],
                ).fetchall()
                details = [str(row[3]) for row in rows]
                uses_index = any("USING INDEX" in detail.upper() for detail in details)
                temporary_sort = any(
                    "USE TEMP B-TREE FOR ORDER BY" in detail.upper()
                    for detail in details
                )
                query_plans.append(
                    {
                        "name": f"{'state-' if state_filtered else ''}{sort}",
                        "sort": sort,
                        "stateFiltered": state_filtered,
                        "usesIndex": uses_index,
                        "temporarySort": temporary_sort,
                        "ok": uses_index and not temporary_sort,
                        "details": details,
                    }
                )
        missing_indexes = sorted(set(JOB_QUERY_INDEXES) - set(indexes))
        job_count = int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        run_count = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        connection.close()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "ok": not missing_indexes and all(plan["ok"] for plan in query_plans),
        "databasePath": str(path.resolve()),
        "databaseBytes": path.stat().st_size if path.exists() else 0,
        "jobCount": job_count,
        "runCount": run_count,
        "journalMode": journal_mode,
        "elapsedMs": elapsed_ms,
        "requiredIndexes": sorted(JOB_QUERY_INDEXES),
        "missingIndexes": missing_indexes,
        "indexes": indexes,
        "queries": query_plans,
    }


def _redact_diagnostic_value(
    value: Any, sensitive_paths: tuple[str, ...] | None = None
) -> Any:
    paths = sensitive_paths or (str(ROOT_DIR.resolve()), str(Path.home().resolve()))
    if isinstance(value, dict):
        return {
            str(key): _redact_diagnostic_value(item, paths) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_diagnostic_value(item, paths) for item in value]
    if not isinstance(value, str):
        return value
    redacted = value
    replacements = tuple(
        (source, "<APP_ROOT>" if index == 0 else "<PRIVATE_PATH>")
        for index, source in enumerate(paths)
    )
    for source, replacement in replacements:
        if source:
            redacted = re.sub(re.escape(source), replacement, redacted, flags=re.IGNORECASE)
            redacted = re.sub(
                re.escape(source.replace("\\", "/")),
                replacement,
                redacted,
                flags=re.IGNORECASE,
            )
    redacted = re.sub(r"https?://[^\s\"']+", "<URL>", redacted)
    redacted = re.sub(
        r"(\[[A-Z]+\]) \[[^\]]+\]", r"\1 [<JOB>]", redacted
    )
    redacted = re.sub(
        r"\b(?:manatoki|newtoki|booktoki):\d+\b",
        "<WORK_ID>",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def export_diagnostics(output_path: Path | None = None) -> dict[str, Any]:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    target = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else (LOG_DIR / f"toki-diagnostics-{timestamp}.zip").resolve()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = settings_snapshot()
    sensitive_paths = tuple(
        dict.fromkeys(
            (
                str(ROOT_DIR.resolve()),
                str(Path.home().resolve()),
                str(Path(str(settings.get("outputDir") or ROOT_DIR)).expanduser().resolve()),
            )
        )
    )
    settings["outputDir"] = "<REDACTED>"
    self_test_summary: dict[str, Any] | None = None
    self_test_path = LOG_DIR / "self-test.json"
    if self_test_path.is_file():
        try:
            self_test = json.loads(self_test_path.read_text(encoding="utf-8"))
            self_test_summary = {
                "ok": bool(self_test.get("ok")),
                "startedAt": self_test.get("startedAt"),
                "durationMs": self_test.get("durationMs"),
                "summary": self_test.get("summary"),
                "checks": [
                    {
                        "name": item.get("name"),
                        "ok": item.get("ok"),
                        "durationMs": item.get("duration_ms"),
                        "detail": item.get("detail"),
                    }
                    for item in self_test.get("checks") or []
                ],
            }
        except (OSError, json.JSONDecodeError):
            self_test_summary = None
    report = _redact_diagnostic_value(
        {
            "formatVersion": 1,
            "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "dependencies": dependency_diagnostics(),
            "schemas": {
                "config": config_schema_status(),
                "database": database_schema_status(),
            },
            "database": job_database_diagnostics(),
            "resources": resource_budget(),
            "retention": log_retention_status(),
            "settings": settings,
            "selfTest": self_test_summary,
        },
        sensitive_paths,
    )
    log_text = "\n".join(
        str(_redact_diagnostic_value(line, sensitive_paths))
        for line in read_log_tail(1_000)
    )
    temporary = target.with_suffix(target.suffix + ".tmp")
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr("recent-gui.log.txt", log_text + ("\n" if log_text else ""))
        archive.writestr(
            "README.txt",
            "This bundle excludes config files, databases, cookies, and downloaded files.\n"
            "Application paths, the user home path, outputDir, and HTTP(S) URLs are redacted.\n",
        )
    os.replace(temporary, target)
    return {
        "ok": True,
        "path": str(target),
        "bytes": target.stat().st_size,
        "files": ["diagnostics.json", "recent-gui.log.txt", "README.txt"],
        "redacted": ["appRoot", "userHome", "outputDir", "httpUrls"],
    }


def run_job_database_benchmark(
    sizes: list[int] | tuple[int, ...] | None = None,
    *,
    page_size: int = 200,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Benchmark bounded list queries against an isolated synthetic SQLite database."""
    requested_sizes = sizes or [100, 1_000, 10_000, 100_000]
    normalized_sizes = sorted({int(size) for size in requested_sizes})
    if not normalized_sizes or normalized_sizes[0] < 1:
        raise ValueError("벤치마크 크기는 1개 이상이어야 합니다.")
    if normalized_sizes[-1] > 100_000:
        raise ValueError("벤치마크 크기는 최대 100,000개입니다.")
    safe_page_size = max(1, min(1_000, int(page_size)))
    target = Path(report_path) if report_path is not None else LOG_DIR / "performance-benchmark.json"
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().astimezone()
    process = psutil.Process()
    memory_before = int(process.memory_info().rss)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="toki-performance-") as temporary_folder:
        database_path = Path(temporary_folder) / "synthetic-jobs.db"
        connection = _connect_job_db(database_path)
        inserted = 0

        def storage_bytes() -> int:
            return sum(
                candidate.stat().st_size
                for candidate in (
                    database_path,
                    Path(str(database_path) + "-wal"),
                    Path(str(database_path) + "-shm"),
                )
                if candidate.exists()
            )

        try:
            for size in normalized_sizes:
                insert_started = time.perf_counter()
                while inserted < size:
                    batch_end = min(size, inserted + 5_000)
                    rows: list[tuple[Any, ...]] = []
                    for index in range(inserted, batch_end):
                        job_id = f"benchmark-{index:06d}"
                        work_key = f"benchmark:{index:06d}"
                        state = ("완료", "오류", "대기", "중지됨")[index % 4]
                        title = f"합성 작품 {index:06d}"
                        progress = index % 101
                        pinned = int(index % 997 == 0)
                        timestamp = f"2026-01-01T{index:012d}+09:00"
                        payload = json.dumps(
                            {
                                "job_id": job_id,
                                "url": f"https://benchmark.invalid/manhwa/{index}",
                                "output_dir": r"C:\toki-benchmark",
                                "work_key": work_key,
                                "title": title,
                                "state": state,
                                "progress": progress,
                                "pinned": bool(pinned),
                                "created_at": timestamp,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        rows.append(
                            (
                                job_id,
                                work_key,
                                title,
                                state,
                                progress,
                                f"https://benchmark.invalid/manhwa/{index}",
                                pinned,
                                "",
                                timestamp,
                                timestamp,
                                payload,
                            )
                        )
                    connection.executemany(
                        """
                        INSERT INTO jobs(
                            job_id, work_key, title, state, progress, url, pinned,
                            tag_color, created_at, updated_at, payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    inserted = batch_end
                connection.commit()
                insert_ms = round((time.perf_counter() - insert_started) * 1000, 3)

                count_started = time.perf_counter()
                counted = int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
                count_ms = round((time.perf_counter() - count_started) * 1000, 3)
                query_times: dict[str, float] = {}
                returned: dict[str, int] = {}
                for sort in JOB_SORT_ORDERS:
                    query_started = time.perf_counter()
                    jobs = load_jobs_page(
                        safe_page_size,
                        0,
                        sort=sort,
                        database_path=database_path,
                    )
                    query_times[sort] = round(
                        (time.perf_counter() - query_started) * 1000, 3
                    )
                    returned[sort] = len(jobs)
                state_started = time.perf_counter()
                filtered_jobs = load_jobs_page(
                    safe_page_size,
                    0,
                    state="완료",
                    sort="updated",
                    database_path=database_path,
                )
                query_times["stateUpdated"] = round(
                    (time.perf_counter() - state_started) * 1000, 3
                )
                returned["stateUpdated"] = len(filtered_jobs)
                first_page_ms = query_times["updated"]
                results.append(
                    {
                        "size": size,
                        "insertMs": insert_ms,
                        "count": counted,
                        "countMs": count_ms,
                        "pageSize": safe_page_size,
                        "returned": returned,
                        "queryMs": query_times,
                        "firstPageMs": first_page_ms,
                        "maxQueryMs": max(query_times.values()),
                        "targetFirstPageMs": 2_000,
                        "passed": counted == size and first_page_ms <= 2_000,
                        "databaseBytes": storage_bytes(),
                    }
                )
        finally:
            connection.close()

    finished_at = datetime.now().astimezone()
    memory_after = int(process.memory_info().rss)
    result = {
        "ok": all(item["passed"] for item in results),
        "startedAt": started_at.isoformat(timespec="seconds"),
        "finishedAt": finished_at.isoformat(timespec="seconds"),
        "durationMs": round((finished_at - started_at).total_seconds() * 1000, 3),
        "pageSize": safe_page_size,
        "sizes": normalized_sizes,
        "temporaryDatabaseRemoved": True,
        "memory": {
            "beforeBytes": memory_before,
            "afterBytes": memory_after,
            "deltaBytes": memory_after - memory_before,
        },
        "environment": {
            "sqliteVersion": sqlite3.sqlite_version,
            "cpuCount": os.cpu_count() or 1,
        },
        "results": results,
        "reportPath": str(target),
    }
    temporary_report = target.with_suffix(target.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_report.replace(target)
    return result


def run_stability_recovery_test(
    *,
    records: int = 10_000,
    cycles: int = 100,
    report_path: Path | None = None,
) -> dict[str, Any]:
    safe_records = max(100, min(100_000, int(records)))
    safe_cycles = max(1, min(1_000, int(cycles)))
    target = Path(report_path) if report_path else LOG_DIR / "stability-recovery.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    process_memory = psutil.Process()
    memory_before = int(process_memory.memory_info().rss)
    started = time.perf_counter()
    child: subprocess.Popen[bytes] | None = None
    result: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="toki-stability-") as temporary_folder:
        temporary_root = Path(temporary_folder)
        database_path = temporary_root / "stability.db"
        ready_path = temporary_root / "child.ready"
        connection = _connect_job_db(database_path)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS stability_cycles (cycle INTEGER PRIMARY KEY, created_at TEXT NOT NULL)"
            )
            for batch_start in range(0, safe_records, 1_000):
                rows = []
                batch_end = min(safe_records, batch_start + 1_000)
                for index in range(batch_start, batch_end):
                    job = DownloadJob(
                        job_id=f"stable-{index:06d}",
                        url=f"https://newtoki1.org/manhwa/{500_000 + index}",
                        output_dir=str(temporary_root / "downloads"),
                        title=f"안정성 작품 {index:06d}",
                        state="완료",
                        progress=100,
                    )
                    payload = json.dumps(job.to_dict(), ensure_ascii=False)
                    rows.append(
                        (
                            job.job_id,
                            job.work_key,
                            job.title,
                            job.state,
                            job.progress,
                            job.url,
                            0,
                            "",
                            job.created_at,
                            job.created_at,
                            payload,
                        )
                    )
                with connection:
                    connection.executemany(
                        """
                        INSERT INTO jobs(
                            job_id, work_key, title, state, progress, url, pinned,
                            tag_color, created_at, updated_at, payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
        finally:
            connection.close()

        cycle_started = time.perf_counter()
        for cycle in range(safe_cycles):
            connection = _connect_job_db(database_path)
            try:
                with connection:
                    connection.execute(
                        "INSERT INTO stability_cycles(cycle, created_at) VALUES (?, ?)",
                        (
                            cycle,
                            datetime.now().astimezone().isoformat(timespec="microseconds"),
                        ),
                    )
                offset = (cycle * 200) % max(1, safe_records - 200)
                rows = connection.execute(
                    "SELECT job_id FROM jobs ORDER BY updated_at DESC, job_id DESC LIMIT 200 OFFSET ?",
                    (offset,),
                ).fetchall()
                if len(rows) != min(200, safe_records):
                    raise RuntimeError("장시간 목록 페이지 검증 결과가 부족합니다.")
            finally:
                connection.close()
        cycle_duration_ms = round((time.perf_counter() - cycle_started) * 1_000, 3)

        child_script = """
import os
import time
from pathlib import Path
import toki_core

toki_core.JOB_DB_PATH = Path(os.environ["TOKI_JOB_DB_PATH"])
toki_core._INITIALIZED_JOB_DBS.clear()
from toki_core import DownloadJob, DownloadRun, save_jobs, save_runs

job = DownloadJob(
    job_id="forced-crash",
    url="https://newtoki1.org/manhwa/999999",
    output_dir=str(Path(os.environ["TOKI_READY_PATH"]).parent / "downloads"),
    title="강제 종료 복구 검증",
    state="실행 중",
    progress=47,
)
run = DownloadRun.from_job(job)
run.process_pid = os.getpid()
save_jobs([job])
save_runs([run])
Path(os.environ["TOKI_READY_PATH"]).write_text("ready", encoding="utf-8")
while True:
    time.sleep(1)
"""
        environment = os.environ.copy()
        environment["TOKI_JOB_DB_PATH"] = str(database_path)
        environment["TOKI_READY_PATH"] = str(ready_path)
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT_DIR), environment.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        process_options: dict[str, Any] = {}
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NO_WINDOW
        child = subprocess.Popen(
            [sys.executable, "-c", child_script],
            cwd=ROOT_DIR,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **process_options,
        )
        try:
            deadline = time.monotonic() + 10
            while not ready_path.is_file() and time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError(
                        f"강제 종료 검증 자식 프로세스가 조기 종료했습니다: {child.returncode}"
                    )
                time.sleep(0.05)
            if not ready_path.is_file():
                raise TimeoutError("강제 종료 검증 자식 프로세스 준비 시간이 초과됐습니다.")
            child_pid = int(child.pid)
            child.kill()
            child_exit_code = int(child.wait(timeout=5))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

        recovery = recover_interrupted_jobs(
            "안정성 검증에서 강제 종료된 작업입니다.",
            database_path=database_path,
        )
        connection = _connect_job_db(database_path)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            cycle_count = int(
                connection.execute("SELECT COUNT(*) FROM stability_cycles").fetchone()[0]
            )
            job_row = connection.execute(
                "SELECT state, payload FROM jobs WHERE job_id = 'forced-crash'"
            ).fetchone()
            run_row = connection.execute(
                "SELECT state, finished_at, payload FROM runs WHERE run_id = 'forced-crash'"
            ).fetchone()
            total_jobs = int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        finally:
            connection.close()
        recovery_passed = bool(
            recovery.get("jobIds") == ["forced-crash"]
            and recovery.get("runIds") == ["forced-crash"]
            and job_row
            and job_row[0] == "중지됨"
            and run_row
            and run_row[0] == "중지됨"
            and run_row[1]
        )
        database_bytes = sum(
            path.stat().st_size
            for path in (
                database_path,
                Path(str(database_path) + "-wal"),
                Path(str(database_path) + "-shm"),
            )
            if path.is_file()
        )
        memory_after = int(process_memory.memory_info().rss)
        result = {
            "ok": integrity == "ok" and recovery_passed and cycle_count == safe_cycles,
            "records": safe_records,
            "cycles": safe_cycles,
            "cycleDurationMs": cycle_duration_ms,
            "averageCycleMs": round(cycle_duration_ms / safe_cycles, 3),
            "databaseBytes": database_bytes,
            "totalJobsBeforeCleanup": total_jobs,
            "integrity": integrity,
            "forcedTermination": {
                "pid": child_pid,
                "exitCode": child_exit_code,
                "recoveryPassed": recovery_passed,
                "recoveredJobIds": recovery.get("jobIds") or [],
                "recoveredRunIds": recovery.get("runIds") or [],
            },
            "memory": {
                "beforeBytes": memory_before,
                "afterBytes": memory_after,
                "deltaBytes": memory_after - memory_before,
            },
            "temporaryDatabaseRemoved": False,
            "durationMs": round((time.perf_counter() - started) * 1_000, 3),
            "reportPath": str(target.resolve()),
        }
    result["temporaryDatabaseRemoved"] = not Path(temporary_folder).exists()
    result["ok"] = bool(result["ok"] and result["temporaryDatabaseRemoved"])
    temporary_report = target.with_suffix(target.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_report.replace(target)
    return result


def recover_interrupted_jobs(
    reason: str = "이전 GUI가 종료되어 작업이 중단되었습니다.",
    *,
    database_path: Path | None = None,
) -> dict[str, Any]:
    interrupted_states = tuple(sorted(ACTIVE_JOB_STATES))
    placeholders = ", ".join("?" for _ in interrupted_states)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    recovered_jobs: list[DownloadJob] = []
    recovered_run_ids: list[str] = []
    job_field_names = set(DownloadJob.__dataclass_fields__)
    connection = _connect_job_db(database_path)
    try:
        job_rows = connection.execute(
            f"SELECT job_id, payload FROM jobs WHERE state IN ({placeholders})",
            interrupted_states,
        ).fetchall()
        run_rows = connection.execute(
            f"SELECT run_id, payload FROM runs WHERE state IN ({placeholders})",
            interrupted_states,
        ).fetchall()
        with connection:
            for job_id, payload in job_rows:
                try:
                    data = json.loads(payload)
                    job = DownloadJob(
                        **{
                            key: value
                            for key, value in data.items()
                            if key in job_field_names
                        }
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                job.state = "중지됨"
                job.error = job.error or reason
                connection.execute(
                    "UPDATE jobs SET state = ?, updated_at = ?, payload = ? WHERE job_id = ?",
                    (
                        job.state,
                        now,
                        json.dumps(job.to_dict(), ensure_ascii=False),
                        job_id,
                    ),
                )
                recovered_jobs.append(job)

            for run_id, payload in run_rows:
                run = _decode_run(payload)
                if run is None:
                    continue
                run.state = "중지됨"
                run.error = run.error or reason
                run.finished_at = run.finished_at or now
                connection.execute(
                    """
                    UPDATE runs
                    SET state = ?, finished_at = ?, updated_at = ?, payload = ?
                    WHERE run_id = ?
                    """,
                    (
                        run.state,
                        run.finished_at,
                        now,
                        json.dumps(run.to_dict(), ensure_ascii=False),
                        run_id,
                    ),
                )
                recovered_run_ids.append(run_id)
    finally:
        connection.close()
    return {
        "jobCount": len(recovered_jobs),
        "runCount": len(recovered_run_ids),
        "jobIds": [job.job_id for job in recovered_jobs],
        "runIds": recovered_run_ids,
    }


def load_recent_jobs(limit: int = 500) -> list[DownloadJob]:
    return load_jobs_page(limit=limit, offset=0)


def hydrate_job_metadata(job: DownloadJob) -> bool:
    metadata_path = (
        Path(job.metadata_path)
        if job.metadata_path
        else Path(job.output_path) / "metadata.json" if job.output_path else None
    )
    if metadata_path is None or not metadata_path.is_file():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    changed = False
    source = metadata.get("source") or {}
    values = {
        "author": str(metadata.get("author") or ""),
        "group": str(metadata.get("group") or ""),
        "site": str(source.get("site") or ""),
        "metadata_path": str(metadata_path.resolve()),
        "cover_url": str(metadata.get("coverUrl") or job.cover_url),
    }
    cover_file = str(metadata.get("coverFile") or "")
    if cover_file and not job.cover_path:
        values["cover_path"] = str((metadata_path.parent / cover_file).resolve())
    for attribute, value in values.items():
        if value and getattr(job, attribute) != value:
            setattr(job, attribute, value)
            changed = True
    return changed


def resolve_cover_path(job: DownloadJob) -> str:
    hydrate_job_metadata(job)
    if not job.cover_path:
        raise ValueError("이 작품에 저장된 대표 이미지 경로가 없습니다.")
    cover_path = Path(job.cover_path).expanduser().resolve()
    if not cover_path.is_file():
        raise FileNotFoundError(f"대표 이미지 파일을 찾을 수 없습니다: {cover_path}")
    return str(cover_path)


def thumbnail_cache_path(
    source_path: str | Path,
    *,
    width: int = 50,
    height: int = 66,
    cache_dir: Path | None = None,
) -> Path:
    source = Path(source_path).expanduser().resolve()
    stat = source.stat()
    fingerprint = "|".join(
        (
            str(source).casefold(),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            str(max(1, int(width))),
            str(max(1, int(height))),
        )
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    root = Path(cache_dir) if cache_dir is not None else THUMBNAIL_CACHE_DIR
    return root.resolve() / f"{digest}.png"


def cleanup_thumbnail_cache(
    *,
    cache_dir: Path | None = None,
    max_files: int = 2_000,
    max_bytes: int = 256 * 1024 * 1024,
    max_age_days: int = 90,
    execute: bool = False,
) -> dict[str, Any]:
    """Plan or execute cleanup only inside the application thumbnail cache."""
    root = (Path(cache_dir) if cache_dir is not None else THUMBNAIL_CACHE_DIR).resolve()
    safe_max_files = max(1, int(max_files))
    safe_max_bytes = max(1, int(max_bytes))
    safe_max_age_days = max(1, int(max_age_days))
    if not root.exists():
        return {
            "ok": True,
            "executed": bool(execute),
            "cacheDir": str(root),
            "existingFiles": 0,
            "existingBytes": 0,
            "removeFiles": 0,
            "removeBytes": 0,
            "removedFiles": 0,
            "removedBytes": 0,
            "keptFiles": 0,
            "keptBytes": 0,
            "limits": {
                "maxFiles": safe_max_files,
                "maxBytes": safe_max_bytes,
                "maxAgeDays": safe_max_age_days,
            },
        }
    if not root.is_dir():
        raise NotADirectoryError(f"썸네일 캐시 경로가 폴더가 아닙니다: {root}")

    entries: list[dict[str, Any]] = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {"path": path, "size": int(stat.st_size), "mtime": float(stat.st_mtime)}
        )
    existing_bytes = sum(entry["size"] for entry in entries)
    cutoff = time.time() - (safe_max_age_days * 24 * 60 * 60)
    removal_paths: set[Path] = {
        entry["path"]
        for entry in entries
        if entry["mtime"] < cutoff or entry["path"].suffix.lower() != ".png"
    }
    kept_count = 0
    kept_bytes = 0
    for entry in sorted(entries, key=lambda item: item["mtime"], reverse=True):
        if entry["path"] in removal_paths:
            continue
        if kept_count >= safe_max_files or kept_bytes + entry["size"] > safe_max_bytes:
            removal_paths.add(entry["path"])
            continue
        kept_count += 1
        kept_bytes += entry["size"]
    removal_entries = [entry for entry in entries if entry["path"] in removal_paths]
    removed_files = 0
    removed_bytes = 0
    if execute:
        for entry in removal_entries:
            try:
                entry["path"].unlink(missing_ok=True)
                removed_files += 1
                removed_bytes += entry["size"]
            except OSError:
                continue
    return {
        "ok": removed_files == len(removal_entries) if execute else True,
        "executed": bool(execute),
        "cacheDir": str(root),
        "existingFiles": len(entries),
        "existingBytes": existing_bytes,
        "removeFiles": len(removal_entries),
        "removeBytes": sum(entry["size"] for entry in removal_entries),
        "removedFiles": removed_files,
        "removedBytes": removed_bytes,
        "keptFiles": kept_count,
        "keptBytes": kept_bytes,
        "limits": {
            "maxFiles": safe_max_files,
            "maxBytes": safe_max_bytes,
            "maxAgeDays": safe_max_age_days,
        },
    }


def build_downloader_args(job: DownloadJob, json_events: bool = True) -> list[str]:
    args = [str(DOWNLOADER_PATH), "-url", job.url, "-output", job.output_dir]
    if job.start is not None:
        args.extend(["-start", str(job.start)])
    if job.last is not None:
        args.extend(["-last", str(job.last)])
    if job.show_browser:
        args.append("-show-browser")
    if job.metadata_only:
        args.append("-metadata-only")
        if job.output_path:
            args.extend(["-content-path", job.output_path])
    else:
        args.extend(["-scan-mode", normalize_scan_mode(job.scan_mode)])
    args.extend(["-image-concurrency", str(normalize_image_concurrency(job.image_concurrency))])
    if json_events:
        args.append("-json-events")
    return args


def retry_job_parameters(source: DownloadJob) -> dict[str, Any]:
    """Return the shared full-rescan contract used by GUI and CLI retries."""
    return rescan_job_parameters(source, "full")


def rescan_job_parameters(
    source: DownloadJob,
    mode: str,
    start: int | None = None,
    last: int | None = None,
) -> dict[str, Any]:
    scan_mode, start_value, last_value = normalize_scan_request(mode, start, last)
    return {
        "url": source.url,
        "start": start_value,
        "last": last_value,
        "output_dir": source.output_dir,
        "show_browser": source.show_browser,
        "scan_mode": scan_mode,
    }


def mark_job_cancelled(job: DownloadJob, reason: str = "") -> DownloadJob:
    if job.state != "대기":
        raise ValueError("대기 중인 작업만 실행 전에 취소할 수 있습니다.")
    job.state = "취소됨"
    job.error = str(reason or "사용자가 대기 작업을 취소했습니다.")
    return job


def mark_run_cancelled(run: DownloadRun, reason: str = "") -> DownloadRun:
    if run.state not in {"대기", "취소됨"}:
        raise ValueError("대기 중인 실행 기록만 취소할 수 있습니다.")
    run.state = "취소됨"
    run.error = str(reason or "사용자가 대기 작업을 취소했습니다.")
    run.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return run


def reorder_pending_jobs(
    jobs: list[DownloadJob],
    job_id: str,
    *,
    before_job_id: str = "",
    position: str = "",
) -> list[DownloadJob]:
    ordered = list(jobs)
    clean_job_id = str(job_id or "").strip()
    source = next((job for job in ordered if job.job_id == clean_job_id), None)
    if source is None:
        raise ValueError(f"대기 중인 작업을 찾을 수 없습니다: {clean_job_id}")
    if source.state != "대기":
        raise ValueError("대기 중인 작업만 순서를 변경할 수 있습니다.")
    clean_position = str(position or "").strip().lower()
    if clean_position not in {"", "first", "last"}:
        raise ValueError(f"지원하지 않는 대기열 위치입니다: {position}")
    if not before_job_id and not clean_position:
        raise ValueError("--before 또는 --first/--last 중 하나를 지정해주세요.")
    ordered.remove(source)
    if clean_position == "first":
        ordered.insert(0, source)
    elif clean_position == "last":
        ordered.append(source)
    else:
        clean_before = str(before_job_id or "").strip()
        if clean_before == clean_job_id:
            return list(jobs)
        target_index = next(
            (index for index, job in enumerate(ordered) if job.job_id == clean_before),
            None,
        )
        if target_index is None:
            raise ValueError(f"기준 대기 작업을 찾을 수 없습니다: {clean_before}")
        ordered.insert(target_index, source)
    return ordered


def set_process_tree_paused(process_pid: int, paused: bool) -> list[int]:
    pid = int(process_pid or 0)
    if pid <= 0:
        raise ValueError("일시정지할 프로세스 PID가 없습니다.")
    try:
        root = psutil.Process(pid)
        processes = list(root.children(recursive=True))
        processes.append(root)
        affected: list[int] = []
        for process in processes:
            try:
                process.suspend() if paused else process.resume()
                affected.append(process.pid)
            except psutil.NoSuchProcess:
                continue
        if not affected:
            raise RuntimeError(f"프로세스 트리를 찾을 수 없습니다: PID {pid}")
        return affected
    except psutil.NoSuchProcess as error:
        raise RuntimeError(f"프로세스를 찾을 수 없습니다: PID {pid}") from error
    except psutil.AccessDenied as error:
        raise RuntimeError(f"프로세스 제어 권한이 없습니다: PID {pid}") from error


def set_job_pause_state(
    job: DownloadJob,
    run: DownloadRun,
    *,
    paused: bool,
) -> tuple[DownloadJob, DownloadRun]:
    expected = "실행 중" if paused else "일시정지"
    target = "일시정지" if paused else "실행 중"
    if job.state != expected or run.state != expected:
        raise ValueError(f"{expected} 상태의 작업만 {target} 상태로 바꿀 수 있습니다.")
    job.state = target
    run.state = target
    return job, run


def update_job_markers(
    job_id: str,
    *,
    pinned: bool | None = None,
    tag_color: str | None = None,
) -> DownloadJob:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if pinned is not None:
        job.pinned = bool(pinned)
    if tag_color is not None:
        clean_color = str(tag_color).strip().lower() or "none"
        if clean_color not in TAG_COLORS:
            raise ValueError(f"지원하지 않는 태그 색상입니다: {tag_color}")
        job.tag_color = clean_color if clean_color != "none" else ""
    save_jobs([job])
    return job


def update_job_note(job_id: str, text: str) -> DownloadJob:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    job.user_note = str(text or "").strip()
    save_jobs([job])
    return job


def plan_job_folder_move(job_id: str, output_dir: str) -> dict[str, Any]:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if job.state in ACTIVE_JOB_STATES:
        raise ValueError("대기 또는 실행 중인 작품 폴더는 이동할 수 없습니다.")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")

    clean_output_dir = str(output_dir or "").strip()
    if not clean_output_dir:
        raise ValueError("새 저장 루트 폴더를 지정해주세요.")
    source = Path(job.output_path).expanduser().resolve()
    target_root = Path(clean_output_dir).expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {source}")
    destination = (target_root / source.parent.name / source.name).resolve()
    same_path = os.path.normcase(str(source)) == os.path.normcase(str(destination))
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        if not same_path:
            raise ValueError("작품 폴더 내부로는 이동할 수 없습니다.")
    conflict = destination.exists() and not same_path
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": job.title,
        "source": str(source),
        "destination": str(destination),
        "outputDir": str(target_root),
        "siteFolder": source.parent.name,
        "folderName": source.name,
        "samePath": same_path,
        "conflict": conflict,
        "canExecute": same_path or not conflict,
        "executed": False,
    }


def move_job_folder(job_id: str, output_dir: str) -> dict[str, Any]:
    plan = plan_job_folder_move(job_id, output_dir)
    if plan["conflict"]:
        raise FileExistsError(f"목적지 폴더가 이미 존재합니다: {plan['destination']}")
    if plan["samePath"]:
        return {**plan, "executed": True, "moved": False}

    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    source = Path(plan["source"])
    destination = Path(plan["destination"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))

    def relocated(value: str) -> str:
        if not value:
            return ""
        candidate = Path(value).expanduser().resolve()
        try:
            relative = candidate.relative_to(source)
        except ValueError:
            return value
        return str(destination / relative)

    job.output_dir = plan["outputDir"]
    job.output_path = str(destination)
    job.cover_path = relocated(job.cover_path)
    job.metadata_path = relocated(job.metadata_path)
    try:
        save_jobs([job])
    except Exception as error:
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
        except Exception as rollback_error:
            raise RuntimeError(
                "작품 폴더 이동 후 기록 저장과 원위치 복구가 모두 실패했습니다. "
                f"현재 폴더를 확인하세요: {destination}"
            ) from rollback_error
        raise error
    return {
        **plan,
        "executed": True,
        "moved": True,
        "job": job.to_dict(),
    }


def plan_metadata_rebuild(job_id: str) -> dict[str, Any]:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if job.state in ACTIVE_JOB_STATES:
        raise ValueError("대기 또는 실행 중인 작품의 메타데이터는 재생성할 수 없습니다.")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")
    metadata_path = output_path / "metadata.json"
    existing: dict[str, Any] = {}
    existing_valid = False
    if metadata_path.is_file():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
                existing_valid = True
        except (OSError, json.JSONDecodeError):
            pass

    folder_match = re.match(r"^\[([^]]*)\]\[([^]]*)\]\s*(.+)$", output_path.name)
    parsed_author = folder_match.group(1) if folder_match else ""
    parsed_group = folder_match.group(2) if folder_match else ""
    parsed_title = folder_match.group(3) if folder_match else output_path.name
    work_site = job.work_key.split(":", 1)[0] if ":" in job.work_key else ""
    site = (
        job.site
        or str((existing.get("source") or {}).get("site") or "")
        or (work_site if work_site in {"manatoki", "newtoki", "booktoki"} else "")
    )
    site_title = {
        "manatoki": "마나토끼",
        "newtoki": "뉴토끼",
        "booktoki": "북토끼",
    }.get(site, output_path.parent.name)
    work_id = job.work_key.rsplit(":", 1)[-1] if ":" in job.work_key else ""
    cover_path = Path(job.cover_path).expanduser() if job.cover_path else None
    cover_file = ""
    if cover_path and cover_path.is_file() and cover_path.parent.resolve() == output_path:
        cover_file = cover_path.name
    elif str(existing.get("coverFile") or ""):
        candidate = output_path / str(existing["coverFile"])
        if candidate.is_file():
            cover_file = candidate.name

    rebuilt = dict(existing)
    rebuilt.update(
        {
            "schemaVersion": 1,
            "title": str(existing.get("title") or parsed_title),
            "author": str(job.author or existing.get("author") or parsed_author or "N／A"),
            "group": str(job.group or existing.get("group") or parsed_group or "N／A"),
            "coverUrl": str(job.cover_url or existing.get("coverUrl") or ""),
            "source": {
                "site": site,
                "siteTitle": site_title,
                "workId": work_id,
                "url": job.url,
            },
            "folderName": output_path.name,
            "episodeCount": int(
                existing.get("episodeCount")
                or max(job.episode_total, job.episode_number, 0)
            ),
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "generatedBy": "tokiDownloader-local-rebuild",
        }
    )
    if cover_file:
        rebuilt["coverFile"] = cover_file
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "metadataPath": str(metadata_path),
        "backupPath": str(metadata_path.with_suffix(".json.bak")),
        "willOverwrite": metadata_path.exists(),
        "existingValid": existing_valid,
        "metadata": rebuilt,
        "executed": False,
    }


def rebuild_job_metadata(job_id: str) -> dict[str, Any]:
    plan = plan_metadata_rebuild(job_id)
    metadata_path = Path(plan["metadataPath"])
    backup_path = Path(plan["backupPath"])
    temporary_path = metadata_path.with_suffix(".json.tmp")
    if metadata_path.is_file():
        shutil.copy2(metadata_path, backup_path)
    temporary_path.write_text(
        json.dumps(plan["metadata"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, metadata_path)
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    job.metadata_path = str(metadata_path)
    hydrate_job_metadata(job)
    save_jobs([job])
    return {
        **plan,
        "executed": True,
        "backupCreated": backup_path.is_file(),
        "job": job.to_dict(),
    }


IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
)


def _image_signature_valid(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size <= 0:
            return False
        with path.open("rb") as handle:
            header = handle.read(16)
            tail = b""
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                handle.seek(max(0, size - 16))
                tail = handle.read(16)
    except OSError:
        return False
    extension = path.suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        return header.startswith(b"\xff\xd8\xff") and tail.endswith(b"\xff\xd9")
    if extension == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in tail
    if extension == ".gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if extension == ".webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if extension == ".bmp":
        return header.startswith(b"BM")
    if extension == ".avif":
        return len(header) >= 12 and header[4:8] == b"ftyp" and b"avif" in header[8:16]
    return False


def verify_job_files(job_id: str, issue_limit: int = 500) -> dict[str, Any]:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")
    clean_limit = max(1, min(10000, int(issue_limit)))
    started = datetime.now().astimezone()
    issues: list[dict[str, Any]] = []
    issue_count = 0

    def add_issue(kind: str, path: Path | None, detail: str) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) < clean_limit:
            issues.append(
                {
                    "kind": kind,
                    "path": str(path) if path is not None else "",
                    "detail": detail,
                }
            )

    metadata_path = output_path / "metadata.json"
    metadata_valid = False
    if metadata_path.is_file():
        try:
            metadata_valid = isinstance(
                json.loads(metadata_path.read_text(encoding="utf-8")), dict
            )
        except (OSError, json.JSONDecodeError):
            pass
    if not metadata_valid:
        add_issue(
            "metadata_missing" if not metadata_path.exists() else "metadata_invalid",
            metadata_path,
            "metadata.json이 없거나 올바른 JSON 객체가 아닙니다.",
        )

    state_path = output_path / ".toki-state.json"
    expected_episodes: set[int] = set()
    state_valid = False
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            raw_episodes = state.get("completedEpisodes", []) if isinstance(state, dict) else []
            expected_episodes = {
                int(value)
                for value in raw_episodes
                if str(value).isdigit() and int(value) > 0
            }
            state_valid = isinstance(state, dict)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    if state_path.exists() and not state_valid:
        add_issue("state_invalid", state_path, "완료 회차 상태 파일을 읽을 수 없습니다.")

    episode_folders: dict[int, list[Path]] = {}
    image_count = 0
    other_file_count = 0
    zero_byte_count = 0
    invalid_image_count = 0
    empty_episode_count = 0
    for entry in os.scandir(output_path):
        if not entry.is_dir(follow_symlinks=False):
            continue
        matched = re.match(r"^0*(\d+)(?:\s|$)", entry.name)
        if not matched:
            continue
        episode_number = int(matched.group(1))
        episode_path = Path(entry.path)
        episode_folders.setdefault(episode_number, []).append(episode_path)
        episode_image_count = 0
        try:
            children = os.scandir(episode_path)
        except OSError as error:
            add_issue("episode_unreadable", episode_path, str(error))
            continue
        with children:
            for child in children:
                if not child.is_file(follow_symlinks=False):
                    continue
                child_path = Path(child.path)
                if child_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    other_file_count += 1
                    continue
                episode_image_count += 1
                image_count += 1
                try:
                    file_size = child.stat(follow_symlinks=False).st_size
                except OSError as error:
                    add_issue("image_unreadable", child_path, str(error))
                    continue
                if file_size <= 0:
                    zero_byte_count += 1
                    add_issue("image_empty", child_path, "이미지 파일 크기가 0바이트입니다.")
                elif not _image_signature_valid(child_path):
                    invalid_image_count += 1
                    add_issue("image_invalid", child_path, "확장자와 이미지 서명이 맞지 않습니다.")
        if episode_image_count == 0:
            empty_episode_count += 1
            add_issue("episode_empty", episode_path, "회차 폴더에 지원 이미지가 없습니다.")

    physical_episodes = set(episode_folders)
    duplicate_episodes = sorted(
        number for number, paths in episode_folders.items() if len(paths) > 1
    )
    for number in duplicate_episodes:
        add_issue(
            "episode_duplicate",
            episode_folders[number][0],
            f"{number}번 회차 접두어 폴더가 {len(episode_folders[number])}개입니다.",
        )
    missing_episodes = sorted(expected_episodes - physical_episodes)
    for number in missing_episodes:
        add_issue("episode_missing", None, f"완료 상태의 {number}번 회차 폴더가 없습니다.")
    untracked_episodes = sorted(physical_episodes - expected_episodes) if state_valid else []

    finished = datetime.now().astimezone()
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": job.title,
        "outputPath": str(output_path),
        "healthy": issue_count == 0,
        "readOnly": True,
        "startedAt": started.isoformat(timespec="seconds"),
        "finishedAt": finished.isoformat(timespec="seconds"),
        "durationMs": max(0, int((finished - started).total_seconds() * 1000)),
        "summary": {
            "episodeFolders": sum(len(paths) for paths in episode_folders.values()),
            "uniqueEpisodes": len(physical_episodes),
            "expectedEpisodes": len(expected_episodes),
            "images": image_count,
            "otherFiles": other_file_count,
            "emptyEpisodes": empty_episode_count,
            "zeroByteImages": zero_byte_count,
            "invalidImages": invalid_image_count,
            "duplicateEpisodes": len(duplicate_episodes),
            "missingEpisodes": len(missing_episodes),
            "untrackedEpisodes": len(untracked_episodes),
            "issueCount": issue_count,
            "returnedIssues": len(issues),
            "issuesTruncated": issue_count > len(issues),
        },
        "metadata": {"path": str(metadata_path), "valid": metadata_valid},
        "state": {
            "path": str(state_path),
            "exists": state_path.exists(),
            "valid": state_valid,
        },
        "missingEpisodes": missing_episodes,
        "untrackedEpisodes": untracked_episodes,
        "issues": issues,
    }


def list_job_episode_images(
    job_id: str,
    episode: int | None = None,
    *,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")
    clean_limit = max(1, min(1000, int(limit)))
    clean_offset = max(0, int(offset))

    episode_folders: dict[int, list[Path]] = {}
    for entry in os.scandir(output_path):
        if not entry.is_dir(follow_symlinks=False):
            continue
        matched = re.match(r"^0*(\d+)(?:\s|$)", entry.name)
        if matched:
            episode_folders.setdefault(int(matched.group(1)), []).append(Path(entry.path))
    available_episodes = sorted(episode_folders)
    if not available_episodes:
        raise FileNotFoundError("미리 볼 회차 폴더가 없습니다.")
    requested_episode = int(episode or 0)
    selected_episode = requested_episode or available_episodes[0]
    if selected_episode not in episode_folders:
        raise ValueError(f"{selected_episode}번 회차 폴더를 찾을 수 없습니다.")

    def natural_key(path: Path) -> list[tuple[int, Any]]:
        return [
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", path.name)
        ]

    images: list[Path] = []
    for folder in sorted(episode_folders[selected_episode], key=natural_key):
        with os.scandir(folder) as children:
            images.extend(
                Path(child.path)
                for child in children
                if child.is_file(follow_symlinks=False)
                and Path(child.name).suffix.lower() in IMAGE_EXTENSIONS
            )
    images.sort(key=natural_key)
    page = images[clean_offset : clean_offset + clean_limit]
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": job.title,
        "outputPath": str(output_path),
        "episode": selected_episode,
        "availableEpisodes": available_episodes,
        "episodeFolders": [str(path) for path in episode_folders[selected_episode]],
        "total": len(images),
        "limit": clean_limit,
        "offset": clean_offset,
        "images": [
            {
                "index": clean_offset + index,
                "name": path.name,
                "path": str(path.resolve()),
                "extension": path.suffix.lower(),
                "size": path.stat().st_size,
            }
            for index, path in enumerate(page)
        ],
    }


IMAGE_CONVERSION_FORMATS = {
    "jpg": {"extension": ".jpg", "pillow": "JPEG"},
    "png": {"extension": ".png", "pillow": "PNG"},
    "webp": {"extension": ".webp", "pillow": "WEBP"},
}


def normalize_image_format(value: str) -> str:
    image_format = str(value or "").strip().lower()
    if image_format == "jpeg":
        image_format = "jpg"
    if image_format not in IMAGE_CONVERSION_FORMATS:
        raise ValueError("지원 이미지 형식은 jpg, png, webp입니다.")
    return image_format


def normalize_image_quality(value: int | None) -> int:
    quality = 90 if value is None else int(value)
    if not 1 <= quality <= 100:
        raise ValueError("이미지 품질은 1~100 사이여야 합니다.")
    return quality


def _collect_conversion_sources(output_path: Path) -> list[Path]:
    sources: list[Path] = []
    for entry in os.scandir(output_path):
        if not entry.is_dir(follow_symlinks=False) or entry.name == "_converted":
            continue
        if not re.match(r"^0*(\d+)(?:\s|$)", entry.name):
            continue
        with os.scandir(entry.path) as children:
            sources.extend(
                Path(child.path).resolve()
                for child in children
                if child.is_file(follow_symlinks=False)
                and Path(child.name).suffix.lower() in IMAGE_EXTENSIONS
            )
    return sorted(sources, key=lambda path: str(path).casefold())


def _sha256_image_file(path_text: str) -> tuple[str, str, str]:
    digest = hashlib.sha256()
    try:
        with Path(path_text).open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return path_text, digest.hexdigest(), ""
    except OSError as error:
        return path_text, "", str(error)


def _phash_image_file(path_text: str) -> tuple[str, str, str]:
    try:
        from PIL import Image  # type: ignore[import-not-found]
        import imagehash  # type: ignore[import-not-found]

        with Image.open(path_text) as image:
            return path_text, str(imagehash.phash(image)), ""
    except Exception as error:  # Pillow decoders expose several format exceptions.
        return path_text, "", str(error)


def find_duplicate_images(
    job_id: str,
    *,
    algorithm: str = "sha256",
    max_workers: int | None = None,
) -> dict[str, Any]:
    selected_algorithm = str(algorithm or "sha256").strip().lower()
    if selected_algorithm not in {"sha256", "phash"}:
        raise ValueError("이미지 중복 알고리즘은 sha256 또는 phash여야 합니다.")
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")
    images = _collect_conversion_sources(output_path)
    limits = resource_budget()
    if selected_algorithm == "phash":
        try:
            pillow_version = importlib.metadata.version("Pillow")
            imagehash_version = importlib.metadata.version("ImageHash")
        except importlib.metadata.PackageNotFoundError as error:
            raise RuntimeError(
                "pHash 검사는 Pillow와 ImageHash가 필요합니다. "
                "setup-gui.cmd -WithImageTools를 실행하세요."
            ) from error
        worker_count = max(
            1,
            min(
                int(max_workers or limits["cpuProcesses"]),
                int(limits["cpuProcesses"]),
            ),
        )
        executor_type = ProcessPoolExecutor
        hash_function = _phash_image_file
        dependency = {
            "name": "Pillow+ImageHash",
            "available": True,
            "version": f"{pillow_version}+{imagehash_version}",
        }
        pool_kind = "process"
    else:
        worker_count = max(
            1,
            min(int(max_workers or limits["ioThreads"]), int(limits["ioThreads"])),
        )
        executor_type = ThreadPoolExecutor
        hash_function = _sha256_image_file
        dependency = {"name": "hashlib", "available": True, "version": sys.version.split()[0]}
        pool_kind = "thread"

    started = time.perf_counter()
    with executor_type(max_workers=worker_count) as executor:
        hashed = list(executor.map(hash_function, map(str, images), chunksize=16))
    digest_groups: dict[str, list[str]] = {}
    failures: list[dict[str, str]] = []
    for path_text, digest, error in hashed:
        if error:
            failures.append({"path": path_text, "error": error})
        elif digest:
            digest_groups.setdefault(digest, []).append(path_text)
    duplicates = [
        {
            "hash": digest,
            "count": len(paths),
            "paths": sorted(paths, key=str.casefold),
        }
        for digest, paths in digest_groups.items()
        if len(paths) > 1
    ]
    duplicates.sort(key=lambda item: (-int(item["count"]), str(item["hash"])))
    duplicate_paths = {path for group in duplicates for path in group["paths"]}
    return {
        "ok": not failures,
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": job.title,
        "outputPath": str(output_path),
        "algorithm": selected_algorithm,
        "dependency": dependency,
        "pool": {"kind": pool_kind, "workers": worker_count},
        "scannedImages": len(images),
        "hashedImages": len(images) - len(failures),
        "failedImages": len(failures),
        "duplicateGroupCount": len(duplicates),
        "duplicateImageCount": len(duplicate_paths),
        "groups": duplicates,
        "failures": failures[:100],
        "durationMs": max(0, int((time.perf_counter() - started) * 1000)),
        "readOnly": True,
        "filesChanged": False,
    }


def plan_image_conversion(
    job_id: str,
    image_format: str,
    *,
    quality: int | None = None,
    sample_limit: int = 100,
) -> dict[str, Any]:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if job.state in ACTIVE_JOB_STATES:
        raise ValueError("대기 또는 실행 중인 작품 이미지는 변환할 수 없습니다.")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")
    normalized_format = normalize_image_format(image_format)
    normalized_quality = normalize_image_quality(quality)
    clean_sample_limit = max(1, min(1000, int(sample_limit)))
    target_root = output_path / "_converted" / normalized_format
    extension = IMAGE_CONVERSION_FORMATS[normalized_format]["extension"]
    sources = _collect_conversion_sources(output_path)
    used_targets: set[str] = set()
    mappings: list[tuple[Path, Path]] = []
    for source in sources:
        relative_parent = source.parent.relative_to(output_path)
        target = target_root / relative_parent / f"{source.stem}{extension}"
        target_key = os.path.normcase(str(target))
        if target_key in used_targets:
            target = target.with_name(
                f"{source.stem}_{source.suffix.lstrip('.').lower()}{extension}"
            )
            suffix = 2
            while os.path.normcase(str(target)) in used_targets:
                target = target.with_name(
                    f"{source.stem}_{source.suffix.lstrip('.').lower()}_{suffix}{extension}"
                )
                suffix += 1
        used_targets.add(os.path.normcase(str(target)))
        mappings.append((source, target))
    existing_targets = sum(1 for _source, target in mappings if target.exists())
    try:
        from PIL import __version__ as pillow_version

        dependency_available = True
    except ImportError:
        pillow_version = ""
        dependency_available = False
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": job.title,
        "outputPath": str(output_path),
        "targetRoot": str(target_root),
        "format": normalized_format,
        "quality": normalized_quality,
        "sourceCount": len(mappings),
        "sourceBytes": sum(source.stat().st_size for source, _target in mappings),
        "existingTargetCount": existing_targets,
        "pendingCount": len(mappings) - existing_targets,
        "preservesOriginals": True,
        "dependency": {
            "name": "Pillow",
            "available": dependency_available,
            "version": str(pillow_version),
            "requirementsFile": str(ROOT_DIR / "requirements-image-tools.txt"),
        },
        "sample": [
            {"source": str(source), "target": str(target), "exists": target.exists()}
            for source, target in mappings[:clean_sample_limit]
        ],
        "sampleTruncated": len(mappings) > clean_sample_limit,
        "executed": False,
    }


def convert_job_images(
    job_id: str,
    image_format: str,
    *,
    quality: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    plan = plan_image_conversion(job_id, image_format, quality=quality, sample_limit=1)
    if not plan["dependency"]["available"]:
        raise RuntimeError(
            "이미지 변환에는 Pillow가 필요합니다. "
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements-image-tools.txt"
        )
    from PIL import Image, ImageOps

    output_path = Path(plan["outputPath"])
    target_root = Path(plan["targetRoot"])
    normalized_format = str(plan["format"])
    pillow_format = IMAGE_CONVERSION_FORMATS[normalized_format]["pillow"]
    extension = IMAGE_CONVERSION_FORMATS[normalized_format]["extension"]
    sources = _collect_conversion_sources(output_path)
    used_targets: set[str] = set()
    converted = 0
    skipped_existing = 0
    failures: list[dict[str, str]] = []
    failure_count = 0
    cancelled = False
    recovered_temporary_files = 0
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        if cancel_check and cancel_check():
            cancelled = True
            break
        relative_parent = source.parent.relative_to(output_path)
        target = target_root / relative_parent / f"{source.stem}{extension}"
        target_key = os.path.normcase(str(target))
        if target_key in used_targets:
            target = target.with_name(
                f"{source.stem}_{source.suffix.lstrip('.').lower()}{extension}"
            )
            suffix = 2
            while os.path.normcase(str(target)) in used_targets:
                target = target.with_name(
                    f"{source.stem}_{source.suffix.lstrip('.').lower()}_{suffix}{extension}"
                )
                suffix += 1
        used_targets.add(os.path.normcase(str(target)))
        temporary = target.with_suffix(target.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
            recovered_temporary_files += 1
        if target.exists():
            skipped_existing += 1
            if progress_callback:
                progress_callback(
                    {
                        "current": index,
                        "total": total,
                        "converted": converted,
                        "skipped": skipped_existing,
                        "failed": failure_count,
                        "source": str(source),
                        "target": str(target),
                        "status": "skipped",
                    }
                )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened)
                if normalized_format == "jpg":
                    if image.mode in {"RGBA", "LA"} or (
                        image.mode == "P" and "transparency" in image.info
                    ):
                        rgba = image.convert("RGBA")
                        background = Image.new("RGB", rgba.size, "white")
                        background.paste(rgba, mask=rgba.getchannel("A"))
                        image = background
                    else:
                        image = image.convert("RGB")
                save_options: dict[str, Any] = {}
                if normalized_format in {"jpg", "webp"}:
                    save_options["quality"] = int(plan["quality"])
                if normalized_format == "jpg":
                    save_options.update({"optimize": True, "progressive": True})
                elif normalized_format == "png":
                    save_options["optimize"] = True
                image.save(temporary, format=pillow_format, **save_options)
            os.replace(temporary, target)
            converted += 1
            status = "converted"
        except Exception as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            failure_count += 1
            if len(failures) < 100:
                failures.append({"source": str(source), "error": str(error)})
            status = "failed"
        if progress_callback:
            progress_callback(
                {
                    "current": index,
                    "total": total,
                    "converted": converted,
                    "skipped": skipped_existing,
                    "failed": failure_count,
                    "source": str(source),
                    "target": str(target),
                    "status": status,
                }
            )
    processed = converted + skipped_existing + failure_count
    return {
        **plan,
        "executed": True,
        "convertedCount": converted,
        "skippedExistingCount": skipped_existing,
        "failedCount": failure_count,
        "failures": failures,
        "failuresTruncated": failure_count > len(failures),
        "processedCount": processed,
        "cancelled": cancelled,
        "remainingCount": total - processed,
        "recoveredTemporaryFiles": recovered_temporary_files,
        "success": not cancelled and processed == total and failure_count == 0,
    }


def delete_job_record(job_id: str) -> DownloadJob:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if job.state in ACTIVE_JOB_STATES:
        raise ValueError("대기 또는 실행 중인 작품 기록은 제거할 수 없습니다.")
    connection = _connect_job_db()
    try:
        with connection:
            connection.execute("DELETE FROM runs WHERE work_key = ?", (job.work_key,))
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    finally:
        connection.close()
    return job


def delete_job_records(states: list[str]) -> list[DownloadJob]:
    clean_states = sorted({str(state).strip() for state in states if str(state).strip()})
    if not clean_states:
        raise ValueError("정리할 작업 상태를 하나 이상 지정해주세요.")
    if any(state in ACTIVE_JOB_STATES for state in clean_states):
        raise ValueError("대기 또는 실행 중인 작품 기록은 일괄 제거할 수 없습니다.")
    placeholders = ",".join("?" for _ in clean_states)
    field_names = set(DownloadJob.__dataclass_fields__)
    connection = _connect_job_db()
    try:
        rows = connection.execute(
            f"SELECT payload FROM jobs WHERE state IN ({placeholders})",
            clean_states,
        ).fetchall()
        jobs: list[DownloadJob] = []
        for (payload,) in rows:
            data = json.loads(payload)
            filtered = {key: value for key, value in data.items() if key in field_names}
            jobs.append(DownloadJob(**filtered))
        with connection:
            work_keys = [job.work_key for job in jobs]
            if work_keys:
                work_placeholders = ",".join("?" for _ in work_keys)
                connection.execute(
                    f"DELETE FROM runs WHERE work_key IN ({work_placeholders})",
                    work_keys,
                )
            connection.execute(
                f"DELETE FROM jobs WHERE state IN ({placeholders})",
                clean_states,
            )
        return jobs
    finally:
        connection.close()


def open_in_explorer(target: str | os.PathLike[str]) -> None:
    resolved = str(Path(target).expanduser().resolve())
    if os.name != "nt":
        raise RuntimeError("현재는 Windows 탐색기 열기만 지원합니다.")
    os.startfile(resolved)  # type: ignore[attr-defined]


def copy_text_to_clipboard(text: str) -> None:
    """Copy Unicode text without starting a shell or visible helper process."""
    if os.name != "nt":
        raise RuntimeError("GUI 없는 클립보드 복사는 현재 Windows에서만 지원합니다.")

    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_int
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    payload = (str(text) + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0002, len(payload))  # GMEM_MOVEABLE
    if not handle:
        raise OSError("클립보드 메모리를 할당하지 못했습니다.")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError("클립보드 메모리를 잠그지 못했습니다.")
    ctypes.memmove(pointer, payload, len(payload))
    kernel32.GlobalUnlock(handle)

    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.02)
    if not opened:
        kernel32.GlobalFree(handle)
        raise OSError("다른 프로그램이 클립보드를 사용 중입니다.")

    transferred = False
    try:
        if not user32.EmptyClipboard():
            raise OSError("클립보드를 비우지 못했습니다.")
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            raise OSError("클립보드에 텍스트를 쓰지 못했습니다.")
        transferred = True
    finally:
        user32.CloseClipboard()
        if not transferred:
            kernel32.GlobalFree(handle)
