from __future__ import annotations

import json
import hashlib
import hmac
import importlib.metadata
import ipaddress
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import psutil
from toki_archive_catalog import archived_episodes

from hitomi_provider import (
    HITOMI_SERVER_IDS,
    normalize_hitomi_excluded_tags,
    normalize_hitomi_filename_mode,
    normalize_hitomi_manual_server,
    normalize_hitomi_metadata_mode,
    normalize_hitomi_metadata_file_mode,
    normalize_hitomi_server_mode,
    normalize_hitomi_server_priority,
)
from youtube_provider import (
    YOUTUBE_HOSTS,
    inspect_youtube_url,
    normalize_youtube_audio_codec,
    normalize_youtube_collection_order,
    normalize_youtube_container,
    normalize_youtube_format_mode,
    normalize_youtube_filename_template,
    normalize_youtube_languages,
    normalize_youtube_max_height,
    normalize_youtube_subtitle_mode,
    normalize_youtube_subtitle_format,
    normalize_youtube_audio_track_mode,
    normalize_youtube_video_codec,
    youtube_execution_config_snapshot,
)


ROOT_DIR = Path(__file__).resolve().parent
VERSION_PATH = ROOT_DIR / "VERSION"
APP_DISPLAY_NAME = "tokiDownloader"
APP_ORGANIZATION_NAME = "EtaSwCwj"
APP_ORGANIZATION_DOMAIN = "github.com/EtaSwCwj"
WINDOWS_APP_USER_MODEL_ID = "EtaSwCwj.tokiDownloader.GUI.1"
APP_ICON_PATH = ROOT_DIR / "assets" / "toki-downloader.png"
APP_EXECUTABLE_ICON_PATH = ROOT_DIR / "assets" / "toki-downloader.ico"
APP_VERSION = (
    VERSION_PATH.read_text(encoding="utf-8").strip()
    if VERSION_PATH.is_file()
    else "0.0.0-dev"
)
DOWNLOADER_PATH = ROOT_DIR / "down.js"
YOUTUBE_WORKER_PATH = ROOT_DIR / "youtube_worker.py"
CONFIG_PATH = ROOT_DIR / "config.json"
LOG_DIR = ROOT_DIR / "logs"
LOG_PATH = LOG_DIR / "gui.log"
JOB_DB_PATH = ROOT_DIR / "jobs.db"
THUMBNAIL_CACHE_DIR = ROOT_DIR / ".cache" / "thumbnails"
CONTROL_SERVER_NAME = "tokiDownloaderGUI"
EVENT_PREFIX = "@@TOKI@@"
_APPLICATION_IDENTITY_RUNTIME: dict[str, Any] = {
    "attempted": False,
    "applied": False,
    "error": "",
}
_INITIALIZED_JOB_DBS: set[str] = set()
CONFIG_SCHEMA_VERSION = 30
JOB_DB_SCHEMA_VERSION = 4
LOCALES_DIR = ROOT_DIR / "locales"
DEFAULT_FOLDER_TEMPLATE = "[{author}][{group}] {title}"
FOLDER_TEMPLATE_FIELDS = frozenset({"author", "group", "title", "site", "id"})
_WINDOWS_RESERVED_SEGMENT = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_WINDOWS_INVALID_SEGMENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
NETWORK_PROVIDERS = ("manatoki", "newtoki", "booktoki")
COOKIE_PROVIDERS = NETWORK_PROVIDERS + ("hitomi", "exhentai", "ehentai")
COOKIE_PROVIDER_POLICIES: dict[str, dict[str, Any]] = {
    "manatoki": {
        "label": "마나토끼",
        "authenticationRequired": False,
        "allowedDomainSuffixes": (),
        "requiredCookieNames": (),
        "recommendedCookieNames": (),
    },
    "newtoki": {
        "label": "뉴토끼",
        "authenticationRequired": False,
        "allowedDomainSuffixes": (),
        "requiredCookieNames": (),
        "recommendedCookieNames": (),
    },
    "booktoki": {
        "label": "북토끼",
        "authenticationRequired": False,
        "allowedDomainSuffixes": (),
        "requiredCookieNames": (),
        "recommendedCookieNames": (),
    },
    "hitomi": {
        "label": "Hitomi.la",
        "authenticationRequired": False,
        "allowedDomainSuffixes": ("hitomi.la",),
        "requiredCookieNames": (),
        "recommendedCookieNames": (),
    },
    "exhentai": {
        "label": "ExHentai",
        "authenticationRequired": True,
        "allowedDomainSuffixes": ("exhentai.org", "e-hentai.org"),
        "requiredCookieNames": (),
        "recommendedCookieNames": ("ipb_member_id", "ipb_pass_hash", "igneous"),
    },
    "ehentai": {
        "label": "E-Hentai",
        "authenticationRequired": False,
        "allowedDomainSuffixes": ("e-hentai.org",),
        "requiredCookieNames": (),
        "recommendedCookieNames": ("ipb_member_id", "ipb_pass_hash"),
    },
}
PUBLIC_IP_ENDPOINT = "https://api.ipify.org?format=json"
CREDENTIAL_SERVICE = "tokiDownloader"
PROXY_CREDENTIAL_KEY = "proxy:credentials"
MAX_COOKIE_IMPORT_BYTES = 5 * 1024 * 1024
MAX_COOKIE_COUNT = 10_000
_COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
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


def application_identity_snapshot() -> dict[str, Any]:
    from toki_windows_launch import relaunch_snapshot
    icon_exists = APP_ICON_PATH.is_file() and APP_ICON_PATH.stat().st_size > 0
    executable_icon_exists = (
        APP_EXECUTABLE_ICON_PATH.is_file()
        and APP_EXECUTABLE_ICON_PATH.stat().st_size > 0
    )
    return {
        "ok": icon_exists and executable_icon_exists,
        "displayName": APP_DISPLAY_NAME,
        "organizationName": APP_ORGANIZATION_NAME,
        "organizationDomain": APP_ORGANIZATION_DOMAIN,
        "windowsAppUserModelId": WINDOWS_APP_USER_MODEL_ID,
        "iconPath": str(APP_ICON_PATH),
        "iconExists": icon_exists,
        "executableIconPath": str(APP_EXECUTABLE_ICON_PATH),
        "executableIconExists": executable_icon_exists,
        "plannedExecutableName": "tokiDownloader.exe",
        "runningExecutable": str(Path(sys.executable).resolve()),
        "taskbarRelaunch": relaunch_snapshot(),
        "windowsTaskbarIsolationConfigured": bool(
            WINDOWS_APP_USER_MODEL_ID and icon_exists
        ),
        "attempted": bool(_APPLICATION_IDENTITY_RUNTIME["attempted"]),
        "applied": bool(_APPLICATION_IDENTITY_RUNTIME["applied"]),
        "error": str(_APPLICATION_IDENTITY_RUNTIME["error"]),
        "networkRequested": False,
    }


def apply_windows_app_user_model_id(
    *,
    platform_name: str | None = None,
    setter: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    selected_platform = str(platform_name or os.name)
    persist_runtime = platform_name is None and setter is None
    attempted = selected_platform == "nt"
    applied = False
    error_text = ""
    if selected_platform != "nt":
        return {
            **application_identity_snapshot(),
            "attempted": attempted,
            "applied": applied,
            "error": error_text,
        }
    try:
        if setter is None:
            import ctypes

            native = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            native.argtypes = [ctypes.c_wchar_p]
            native.restype = ctypes.c_long
            setter = native
        result = int(setter(WINDOWS_APP_USER_MODEL_ID))
        if result != 0:
            raise OSError(f"HRESULT 0x{result & 0xFFFFFFFF:08X}")
        applied = True
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
    if persist_runtime:
        _APPLICATION_IDENTITY_RUNTIME.update(
            {"attempted": attempted, "applied": applied, "error": error_text}
        )
    return {
        **application_identity_snapshot(),
        "attempted": attempted,
        "applied": applied,
        "error": error_text,
    }
SETTING_KEYS = frozenset(
    {
        "outputDir",
        "folderNameTemplate",
        "uiLanguage",
        "logVisible",
        "showBrowser",
        "workConcurrency",
        "imageConcurrency",
        "retryCount",
        "retryBackoffSeconds",
        "logMaxMiB",
        "logBackupCount",
        "rowDensity",
        "listViewMode",
        "thumbnailsVisible",
        "thumbnailSize",
        "alwaysOnTop",
        "windowOpacity",
        "uiScale",
        "fontFamily",
        "backgroundImage",
        "proxyUrl",
        "speedLimitKib",
        "providerPolicies",
        "quickActions",
        "shortcutOverrides",
        "completionAction",
        "completionCountdownSeconds",
        "clipboardMonitor",
        "clipboardAutoDownload",
        "theme",
        "trayEnabled",
        "closeToTray",
        "minimizeToTray",
        "notifyOnComplete",
        "notifyOnError",
        "notificationSound",
        "notificationMessageBox",
        "imageResizeMaxWidth",
        "imageResizeMaxHeight",
        "imageExcludedExtensions",
        "archiveViewerMode",
        "archiveViewerPath",
        "autosaveIntervalSeconds",
        "recoverInterruptedOnStartup",
        "listPageSize",
        "listLoadedLimit",
        "listScrollLines",
        "listLazyLoading",
        "lowSpecMode",
        "preventSleepDuringDownloads",
        "pdfGenerationEnabled",
        "archiveAfterDownload",
        "archiveRemoveOriginals",
        "memoryDisplayEnabled",
        "localApiEnabled",
        "localApiPort",
        "hitomiServerMode",
        "hitomiManualServer",
        "hitomiServerPriority",
        "hitomiMetadataMode",
        "hitomiFilenameMode",
        "hitomiExcludedTags",
        "hitomiPreferJapaneseTitle",
        "hitomiMetadataFileMode",
        "hitomiUseOriginalImages",
        "youtubeFormatMode",
        "youtubeMaxHeight",
        "youtubeContainer",
        "youtubeVideoCodec",
        "youtubeAudioCodec",
        "youtubeFilenameTemplate",
        "youtubePreferredLanguages",
        "youtubeSubtitleMode",
        "youtubeSubtitleFormat",
        "youtubeEmbedSubtitles",
        "youtubeAudioTrackMode",
        "youtubeWriteThumbnail",
        "youtubeEmbedThumbnail",
        "youtubeWriteInfoJson",
        "youtubeWriteDescription",
        "youtubeEmbedMetadata",
        "youtubeCollectionOrder",
        "youtubeEmbedChapters",
        "youtubeApplyUploadDateMtime",
    }
)
_LOG_MAX_BYTES = 2 * 1024 * 1024
_LOG_BACKUP_COUNT = 1
ACTIVE_JOB_STATES = frozenset({"대기", "실행 중", "일시정지", "재시도 대기"})
QUICK_ACTIONS = (
    {"id": "download.start", "label": "다운로드"},
    {"id": "job.stop", "label": "중지"},
    {"id": "job.rescan_full", "label": "전체 재검사"},
    {"id": "folder.open", "label": "폴더 열기"},
    {"id": "details.open", "label": "작품 정보"},
    {"id": "duplicates.works", "label": "중복 검사"},
    {"id": "settings.open", "label": "설정"},
    {"id": "screenshot.capture", "label": "화면 캡처"},
)
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
COALESCED_DOWNLOADER_EVENTS = frozenset({"image_saved", "youtube_progress"})
PERSISTED_DOWNLOADER_EVENTS = frozenset(
    {
        "work_metadata",
        "queue_ready",
        "episode_started",
        "episode_completed",
        "episode_deferred",
        "youtube_started",
        "youtube_item",
        "youtube_item_completed",
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
        "dependency",
        "source",
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
    "dependency": "의존성",
    "source": "원본 상태",
    "process": "프로세스",
    "unknown": "기타",
}
NON_RETRYABLE_ERROR_CATEGORIES = frozenset(
    {"authentication_required", "site_structure", "filesystem", "dependency", "source"}
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
        "folderNameTemplate": DEFAULT_FOLDER_TEMPLATE,
        "uiLanguage": "ko",
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
        "listViewMode": "list",
        "thumbnailsVisible": True,
        "thumbnailSize": "medium",
        "alwaysOnTop": False,
        "windowOpacity": 100,
        "uiScale": 100,
        "fontFamily": "Malgun Gothic",
        "backgroundImage": "",
        "proxyUrl": "",
        "speedLimitKib": 0,
        "providerPolicies": {
            provider: {"requestDelayMs": 0, "backoffSeconds": 2}
            for provider in NETWORK_PROVIDERS
        },
        "quickActions": [
            "download.start",
            "job.stop",
            "job.rescan_full",
            "folder.open",
            "settings.open",
        ],
        "shortcutOverrides": {},
        "completionAction": "none",
        "completionCountdownSeconds": 15,
        "clipboardMonitor": False,
        "clipboardAutoDownload": False,
        "theme": "system",
        "trayEnabled": False,
        "closeToTray": False,
        "minimizeToTray": False,
        "notifyOnComplete": True,
        "notifyOnError": True,
        "notificationSound": "none",
        "notificationMessageBox": False,
        "imageResizeMaxWidth": 0,
        "imageResizeMaxHeight": 0,
        "imageExcludedExtensions": [],
        "archiveViewerMode": "system",
        "archiveViewerPath": "",
        "autosaveIntervalSeconds": 1,
        "recoverInterruptedOnStartup": True,
        "listPageSize": 200,
        "listLoadedLimit": 2_000,
        "listScrollLines": 3,
        "listLazyLoading": True,
        "lowSpecMode": False,
        "preventSleepDuringDownloads": False,
        "pdfGenerationEnabled": False,
        "archiveAfterDownload": False,
        "archiveRemoveOriginals": True,
        "memoryDisplayEnabled": True,
        "localApiEnabled": False,
        "localApiPort": 8765,
        "hitomiServerMode": "auto",
        "hitomiManualServer": "hitomi",
        "hitomiServerPriority": list(HITOMI_SERVER_IDS),
        "hitomiMetadataMode": "auto",
        "hitomiFilenameMode": "number_original",
        "hitomiExcludedTags": [],
        "hitomiPreferJapaneseTitle": False,
        "hitomiMetadataFileMode": "metadata_json",
        "hitomiUseOriginalImages": True,
        "youtubeFormatMode": "video_audio",
        "youtubeMaxHeight": 0,
        "youtubeContainer": "auto",
        "youtubeVideoCodec": "auto",
        "youtubeAudioCodec": "auto",
        "youtubeFilenameTemplate": "%(title)s [%(id)s].%(ext)s",
        "youtubePreferredLanguages": ["ko", "en", "ja"],
        "youtubeSubtitleMode": "none",
        "youtubeSubtitleFormat": "best",
        "youtubeEmbedSubtitles": False,
        "youtubeAudioTrackMode": "preferred_single",
        "youtubeWriteThumbnail": False,
        "youtubeEmbedThumbnail": False,
        "youtubeWriteInfoJson": False,
        "youtubeWriteDescription": False,
        "youtubeEmbedMetadata": False,
        "youtubeCollectionOrder": "site",
        "youtubeEmbedChapters": False,
        "youtubeApplyUploadDateMtime": False,
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


def normalize_list_view_mode(value: str | None) -> str:
    normalized = str(value or "list").strip().lower()
    if normalized not in {"list", "icon"}:
        raise ValueError("목록 보기 방식은 list 또는 icon이어야 합니다.")
    return normalized


def normalize_thumbnail_size(value: str | None) -> str:
    normalized = str(value or "medium").strip().lower()
    if normalized not in {"small", "medium", "large"}:
        raise ValueError("썸네일 크기는 small, medium 또는 large여야 합니다.")
    return normalized


def normalize_window_opacity(value: int | None) -> int:
    normalized = 100 if value is None else int(value)
    if not 50 <= normalized <= 100:
        raise ValueError("창 불투명도는 50~100이어야 합니다.")
    return normalized


def available_ui_languages() -> list[dict[str, str]]:
    languages: list[dict[str, str]] = []
    if not LOCALES_DIR.is_dir():
        return [{"code": "ko", "name": "한국어"}]
    for path in sorted(LOCALES_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        code = str(payload.get("meta.code") or path.stem).strip().lower()
        name = str(payload.get("meta.name") or code).strip()
        if code:
            languages.append({"code": code, "name": name})
    return languages or [{"code": "ko", "name": "한국어"}]


def normalize_ui_language(value: str | None) -> str:
    language = str(value or "ko").strip().lower()
    supported = {item["code"] for item in available_ui_languages()}
    if language not in supported:
        raise ValueError(
            f"지원하지 않는 UI 언어입니다: {language} (지원: {', '.join(sorted(supported))})"
        )
    return language


def load_ui_strings(language: str | None = None) -> dict[str, str]:
    code = normalize_ui_language(language)
    path = LOCALES_DIR / f"{code}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"UI 언어 리소스를 읽을 수 없습니다: {path.name}") from error
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise ValueError(f"UI 언어 리소스 형식이 잘못되었습니다: {path.name}")
    return dict(payload)


def ui_text(language: str | None, key: str, **values: Any) -> str:
    text = load_ui_strings(language).get(key, key)
    try:
        return text.format(**values)
    except (KeyError, ValueError):
        return text


def normalize_ui_scale(value: int | None) -> int:
    scale = 100 if value is None else int(value)
    if not 75 <= scale <= 200:
        raise ValueError("UI 배율은 75~200%여야 합니다.")
    return scale


def normalize_font_family(value: str | None) -> str:
    family = str(value or "Malgun Gothic").strip()
    if not family or len(family) > 100 or any(ord(char) < 32 for char in family):
        raise ValueError("글꼴 이름은 1~100자의 표시 가능한 문자여야 합니다.")
    return family


def normalize_background_image(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > 1024:
        raise ValueError("배경 이미지 경로가 너무 깁니다.")
    if Path(raw).suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        raise ValueError("배경 이미지는 PNG, JPEG, BMP 또는 WebP 파일이어야 합니다.")
    return str(Path(raw).expanduser())


def browser_launch_policy(show_browser: bool | None = None) -> dict[str, Any]:
    visible = bool(show_browser)
    return {
        "mode": "visible-diagnostic" if visible else "headless",
        "showBrowser": visible,
        "windowVisible": visible,
        "personalChromeProfile": False,
        "profileIsolation": "temporary-automation-profile",
        "recommended": not visible,
        "purpose": (
            "사이트 인증·선택자 문제를 사용자가 직접 확인"
            if visible
            else "백그라운드 다운로드"
        ),
    }


def embedded_browser_capabilities() -> dict[str, Any]:
    try:
        version = importlib.metadata.version("PyQt6-WebEngine")
    except importlib.metadata.PackageNotFoundError:
        version = ""
    return {
        "available": bool(version),
        "package": "PyQt6-WebEngine",
        "version": version,
        "offTheRecordProfile": True,
        "persistentCookies": False,
        "sharesAutomationCookies": False,
        "personalChromeProfile": False,
        "defaultPage": "offline",
    }


def normalize_embedded_browser_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > 4096:
        raise ValueError("내장 브라우저 URL은 4096자 이하여야 합니다.")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("내장 브라우저는 HTTPS 주소만 열 수 있습니다.")
    if parsed.username or parsed.password:
        raise ValueError("내장 브라우저 URL에는 인증 정보를 넣을 수 없습니다.")
    if any(ord(char) < 32 for char in raw):
        raise ValueError("내장 브라우저 URL에 제어 문자를 사용할 수 없습니다.")
    return raw


def embedded_browser_navigation_plan(url: str) -> dict[str, Any]:
    normalized = normalize_embedded_browser_url(url)
    if not normalized:
        raise ValueError("열 URL을 입력해주세요.")
    parsed = urlsplit(normalized)
    return {
        "url": normalized,
        "host": str(parsed.hostname or ""),
        "requiresNetwork": True,
        "requiresConfirmation": True,
        "sendsProviderCookies": False,
        "offTheRecordProfile": True,
        "persistentCookies": False,
        "personalChromeProfile": False,
        "executed": False,
    }


def normalize_proxy_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https", "socks", "socks4", "socks5"}:
        raise ValueError("프록시는 HTTP, HTTPS, SOCKS4 또는 SOCKS5만 지원합니다.")
    if not parsed.hostname or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("프록시 URL에는 호스트와 선택적 포트만 입력해주세요.")
    if parsed.username or parsed.password:
        raise ValueError("프록시 인증 정보는 URL에 저장할 수 없습니다.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("프록시 포트가 잘못되었습니다.") from error
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    normalized = f"{parsed.scheme.lower()}://{host}"
    if port:
        normalized += f":{port}"
    return normalized


def normalize_speed_limit_kib(value: int | None) -> int:
    limit = 0 if value is None else int(value)
    if limit != 0 and not 32 <= limit <= 1_048_576:
        raise ValueError("속도 제한은 0(무제한) 또는 32~1048576 KiB/s여야 합니다.")
    return limit


def normalize_provider_policies(value: Any) -> dict[str, dict[str, int]]:
    defaults = {
        provider: {"requestDelayMs": 0, "backoffSeconds": 2}
        for provider in NETWORK_PROVIDERS
    }
    source = value if isinstance(value, dict) else {}
    result: dict[str, dict[str, int]] = {}
    for provider in NETWORK_PROVIDERS:
        raw = source.get(provider)
        raw = raw if isinstance(raw, dict) else defaults[provider]
        delay = int(raw.get("requestDelayMs", 0))
        backoff = int(raw.get("backoffSeconds", 2))
        if not 0 <= delay <= 5000:
            raise ValueError(f"{provider} 요청 간격은 0~5000ms여야 합니다.")
        if not 1 <= backoff <= 60:
            raise ValueError(f"{provider} 백오프는 1~60초여야 합니다.")
        result[provider] = {
            "requestDelayMs": delay,
            "backoffSeconds": backoff,
        }
    unknown = sorted(set(source) - set(NETWORK_PROVIDERS))
    if unknown:
        raise ValueError(f"지원하지 않는 공급자 정책입니다: {', '.join(unknown)}")
    return result


def provider_from_url(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host.startswith("booktoki") or "/novel/" in path:
        return "booktoki"
    if "/webtoon/" in path:
        return "newtoki"
    return "manatoki"


def network_policy_snapshot(
    config: dict[str, Any] | None = None,
    *,
    url: str = "",
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    policies = normalize_provider_policies(source.get("providerPolicies"))
    provider = provider_from_url(url) if url else ""
    return {
        "proxyUrl": normalize_proxy_url(source.get("proxyUrl")),
        "proxyEnabled": bool(source.get("proxyUrl")),
        "proxyAuthenticationStored": False,
        "speedLimitKib": normalize_speed_limit_kib(source.get("speedLimitKib")),
        "unlimited": normalize_speed_limit_kib(source.get("speedLimitKib")) == 0,
        "provider": provider,
        "providerPolicy": policies.get(provider) if provider else None,
        "providerPolicies": policies,
    }


def public_ip_check_plan(endpoint: str = PUBLIC_IP_ENDPOINT) -> dict[str, Any]:
    normalized_endpoint = str(endpoint or "").strip()
    parsed = urlsplit(normalized_endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("공인 IP 확인 주소는 HTTPS여야 합니다.")
    return {
        "ok": True,
        "operation": "public_ip_check",
        "requiresNetwork": True,
        "requiresConfirmation": True,
        "endpoint": normalized_endpoint,
        "method": "GET",
        "sendsCookies": False,
        "sendsDownloadedFiles": False,
        "timeoutSeconds": 10,
        "maxResponseBytes": 4096,
        "networkRequested": False,
        "executed": False,
    }


def lookup_public_ip(
    *,
    endpoint: str = PUBLIC_IP_ENDPOINT,
    fetcher: Callable[[str, int], bytes] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    plan = public_ip_check_plan(endpoint)
    default_fetcher = fetcher is None
    if default_fetcher and not confirmed:
        raise ValueError("공인 IP 외부 요청에는 명시적 확인이 필요합니다.")
    if default_fetcher:
        def fetcher(url: str, timeout: int) -> bytes:
            request = Request(url, headers={"User-Agent": f"tokiDownloader/{APP_VERSION}"})
            with urlopen(request, timeout=timeout) as response:
                return response.read(int(plan["maxResponseBytes"]) + 1)
    payload = fetcher(str(plan["endpoint"]), int(plan["timeoutSeconds"]))
    payload_bytes = bytes(payload)
    if len(payload_bytes) > int(plan["maxResponseBytes"]):
        raise ValueError("공인 IP 확인 응답이 허용 크기를 초과했습니다.")
    try:
        decoded = json.loads(payload_bytes.decode("utf-8"))
        address = str(decoded.get("ip") or "").strip()
        parsed_address = ipaddress.ip_address(address)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("공인 IP 확인 응답 형식이 잘못되었습니다.") from error
    return {
        **plan,
        "ok": True,
        "ip": str(parsed_address),
        "version": parsed_address.version,
        "responseBytes": len(payload_bytes),
        "confirmationSatisfied": bool(confirmed or not default_fetcher),
        "injectedFetcher": not default_fetcher,
        "networkRequested": default_fetcher,
        "executed": True,
        "checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def normalize_cookie_provider(value: str) -> str:
    provider = str(value or "").strip().lower()
    if provider not in COOKIE_PROVIDERS:
        raise ValueError(
            f"쿠키 공급자는 {', '.join(COOKIE_PROVIDERS)} 중 하나여야 합니다."
        )
    return provider


def provider_cookie_policy(provider: str) -> dict[str, Any]:
    normalized_provider = normalize_cookie_provider(provider)
    policy = COOKIE_PROVIDER_POLICIES[normalized_provider]
    return {
        "provider": normalized_provider,
        "label": str(policy["label"]),
        "authenticationRequired": bool(policy["authenticationRequired"]),
        "allowedDomainSuffixes": list(policy["allowedDomainSuffixes"]),
        "requiredCookieNames": list(policy["requiredCookieNames"]),
        "recommendedCookieNames": list(policy["recommendedCookieNames"]),
        "accessRestrictionBypassSupported": False,
        "storage": "os-credential-vault",
        "valuesExposed": False,
    }


def _cookie_matches_domain(cookie_domain: str, allowed_suffixes: tuple[str, ...]) -> bool:
    normalized_domain = str(cookie_domain or "").strip().lower().lstrip(".")
    return any(
        normalized_domain == suffix or normalized_domain.endswith(f".{suffix}")
        for suffix in allowed_suffixes
    )


def assess_provider_cookies(
    provider: str,
    cookies: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = provider_cookie_policy(provider)
    allowed_suffixes = tuple(policy["allowedDomainSuffixes"])
    relevant = (
        [
            cookie
            for cookie in cookies
            if _cookie_matches_domain(str(cookie.get("domain") or ""), allowed_suffixes)
        ]
        if allowed_suffixes
        else list(cookies)
    )
    present_names = {
        str(cookie.get("name") or "").strip().lower()
        for cookie in relevant
        if cookie.get("name")
    }
    required_names = [name.lower() for name in policy["requiredCookieNames"]]
    recommended_names = [name.lower() for name in policy["recommendedCookieNames"]]
    missing_required = [name for name in required_names if name not in present_names]
    missing_recommended = [name for name in recommended_names if name not in present_names]
    authentication_ready: bool | None
    if policy["authenticationRequired"]:
        if not relevant:
            authentication_ready = False
        elif required_names:
            authentication_ready = not missing_required
        else:
            authentication_ready = None
    else:
        authentication_ready = bool(relevant)
    return {
        "provider": policy["provider"],
        "inputCookieCount": len(cookies),
        "relevantCookieCount": len(relevant),
        "ignoredCookieCount": len(cookies) - len(relevant),
        "domains": sorted(
            {str(cookie.get("domain") or "") for cookie in relevant if cookie.get("domain")}
        ),
        "authenticationRequired": policy["authenticationRequired"],
        "authenticationReady": authentication_ready,
        "authenticationReadinessVerifiable": bool(required_names),
        "missingRequiredCookieNames": missing_required,
        "missingRecommendedCookieNames": missing_recommended,
        "valuesExposed": False,
    }


def credential_store_status() -> dict[str, Any]:
    try:
        import keyring

        backend = keyring.get_keyring()
        priority = float(getattr(backend, "priority", 0) or 0)
        return {
            "available": priority > 0,
            "backend": f"{type(backend).__module__}.{type(backend).__name__}",
            "priority": priority,
            "plaintext": False,
            "packageVersion": importlib.metadata.version("keyring"),
        }
    except (ImportError, importlib.metadata.PackageNotFoundError, RuntimeError) as error:
        return {
            "available": False,
            "backend": "",
            "priority": 0,
            "plaintext": False,
            "error": str(error),
        }


def _credential_backend(backend: Any | None = None) -> Any:
    if backend is not None:
        return backend
    try:
        import keyring
    except ImportError as error:
        raise RuntimeError(
            "보안 저장소가 설치되지 않았습니다. requirements-security.txt를 설치해주세요."
        ) from error
    status = credential_store_status()
    if not status["available"]:
        raise RuntimeError("사용 가능한 OS 자격 증명 저장소가 없습니다.")
    return keyring


def _normalize_proxy_credentials(
    proxy_url: str,
    username: str,
    password: str,
) -> dict[str, str]:
    normalized_proxy = normalize_proxy_url(proxy_url)
    normalized_username = str(username or "").strip()
    normalized_password = str(password or "")
    if not normalized_proxy:
        raise ValueError("프록시 주소를 먼저 설정해주세요.")
    if not normalized_username or not normalized_password:
        raise ValueError("프록시 사용자명과 비밀번호를 모두 입력해주세요.")
    if any(ord(char) < 32 for char in normalized_username):
        raise ValueError("프록시 사용자명에는 제어 문자를 사용할 수 없습니다.")
    if len(normalized_username) > 512 or len(normalized_password) > 4096:
        raise ValueError("프록시 인증 정보가 안전 길이 한도를 초과합니다.")
    return {
        "proxyUrl": normalized_proxy,
        "username": normalized_username,
        "password": normalized_password,
    }


def store_proxy_credentials(
    proxy_url: str,
    username: str,
    password: str,
    *,
    backend: Any | None = None,
) -> dict[str, Any]:
    credentials = _normalize_proxy_credentials(proxy_url, username, password)
    payload = {
        "format": "tokiDownloader-proxy-credentials",
        "formatVersion": 1,
        **credentials,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    store = _credential_backend(backend)
    store.set_password(
        CREDENTIAL_SERVICE,
        PROXY_CREDENTIAL_KEY,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return {
        "stored": True,
        "proxyUrl": credentials["proxyUrl"],
        "username": credentials["username"],
        "updatedAt": payload["updatedAt"],
        "valuesExposed": False,
        "executed": True,
    }


def _load_proxy_credential_payload(backend: Any | None = None) -> dict[str, str] | None:
    store = _credential_backend(backend)
    secret = store.get_password(CREDENTIAL_SERVICE, PROXY_CREDENTIAL_KEY)
    if not secret:
        return None
    try:
        payload = json.loads(secret)
        normalized = _normalize_proxy_credentials(
            str(payload.get("proxyUrl") or ""),
            str(payload.get("username") or ""),
            str(payload.get("password") or ""),
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("OS 보안 저장소의 프록시 인증 정보가 손상되었습니다.") from error
    return {
        **normalized,
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def proxy_credential_status(
    proxy_url: str = "",
    *,
    backend: Any | None = None,
) -> dict[str, Any]:
    configured_proxy = normalize_proxy_url(proxy_url)
    payload = _load_proxy_credential_payload(backend)
    stored_proxy = str(payload.get("proxyUrl") or "") if payload else ""
    return {
        "stored": payload is not None,
        "proxyUrl": stored_proxy,
        "username": str(payload.get("username") or "") if payload else "",
        "updatedAt": str(payload.get("updatedAt") or "") if payload else "",
        "matchesConfiguredProxy": bool(
            payload and configured_proxy and stored_proxy == configured_proxy
        ),
        "configuredProxyUrl": configured_proxy,
        "valuesExposed": False,
    }


def clear_proxy_credentials(*, backend: Any | None = None) -> dict[str, Any]:
    store = _credential_backend(backend)
    existing = store.get_password(CREDENTIAL_SERVICE, PROXY_CREDENTIAL_KEY)
    if existing:
        try:
            store.delete_password(CREDENTIAL_SERVICE, PROXY_CREDENTIAL_KEY)
        except Exception as error:
            if type(error).__name__ != "PasswordDeleteError":
                raise
    return {
        "cleared": bool(existing),
        "executed": True,
    }


def downloader_environment_overrides(
    config: dict[str, Any] | None = None,
    *,
    backend: Any | None = None,
) -> dict[str, str]:
    source = normalize_config(config) if config is not None else load_config()
    configured_proxy = normalize_proxy_url(source.get("proxyUrl"))
    if not configured_proxy:
        return {}
    try:
        payload = _load_proxy_credential_payload(backend)
    except RuntimeError:
        return {}
    if not payload or payload["proxyUrl"] != configured_proxy:
        return {}
    return {
        "TOKI_PROXY_USERNAME": payload["username"],
        "TOKI_PROXY_PASSWORD": payload["password"],
    }


def _normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    name = str(cookie.get("name") or "").strip()
    value = str(cookie.get("value") or "")
    domain = str(cookie.get("domain") or "").strip().lower()
    path_value = str(cookie.get("path") or "/").strip() or "/"
    if not name or not domain or any(ord(char) < 32 for char in name + domain):
        raise ValueError("쿠키 이름과 도메인이 필요합니다.")
    if not _COOKIE_NAME.fullmatch(name):
        raise ValueError("쿠키 이름에 HTTP 헤더에서 사용할 수 없는 문자가 있습니다.")
    if any(ord(char) < 32 for char in value + path_value) or ";" in value:
        raise ValueError("쿠키 값 또는 경로에 안전하지 않은 문자가 있습니다.")
    if len(name) > 512 or len(value) > 16_384 or len(domain) > 253:
        raise ValueError("쿠키 필드 길이가 안전 한도를 초과합니다.")
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path_value,
        "expires": int(cookie.get("expires") or cookie.get("expirationDate") or 0),
        "secure": bool(cookie.get("secure", False)),
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "sameSite": str(cookie.get("sameSite") or ""),
    }


def parse_cookie_file(input_path: Path) -> list[dict[str, Any]]:
    path = Path(input_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"쿠키 파일을 찾을 수 없습니다: {path}")
    if path.stat().st_size > MAX_COOKIE_IMPORT_BYTES:
        raise ValueError("쿠키 파일은 5 MiB 이하여야 합니다.")
    text = path.read_text(encoding="utf-8-sig")
    cookies: list[dict[str, Any]] = []
    stripped = text.lstrip()
    if stripped.startswith(("[", "{")):
        payload = json.loads(text)
        source = payload.get("cookies") if isinstance(payload, dict) else payload
        if not isinstance(source, list):
            raise ValueError("JSON 쿠키 파일은 배열 또는 cookies 배열이어야 합니다.")
        for item in source:
            if not isinstance(item, dict):
                raise ValueError("JSON 쿠키 항목은 객체여야 합니다.")
            cookies.append(_normalize_cookie(item))
    else:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            http_only = line.startswith("#HttpOnly_")
            if http_only:
                line = line.removeprefix("#HttpOnly_")
            fields = line.split("\t")
            if len(fields) != 7:
                raise ValueError("Netscape 쿠키 행은 탭으로 구분된 7개 필드여야 합니다.")
            domain, _include_subdomains, path_value, secure, expires, name, value = fields
            cookies.append(
                _normalize_cookie(
                    {
                        "domain": domain,
                        "path": path_value,
                        "secure": secure.upper() == "TRUE",
                        "expires": expires,
                        "name": name,
                        "value": value,
                        "httpOnly": http_only,
                    }
                )
            )
    if not cookies:
        raise ValueError("가져올 쿠키가 없습니다.")
    if len(cookies) > MAX_COOKIE_COUNT:
        raise ValueError(f"쿠키는 최대 {MAX_COOKIE_COUNT:,}개까지 가져올 수 있습니다.")
    return cookies


def cookie_import_plan(provider: str, input_path: Path) -> dict[str, Any]:
    normalized_provider = normalize_cookie_provider(provider)
    cookies = parse_cookie_file(input_path)
    assessment = assess_provider_cookies(normalized_provider, cookies)
    if assessment["relevantCookieCount"] <= 0:
        allowed = provider_cookie_policy(normalized_provider)["allowedDomainSuffixes"]
        raise ValueError(
            "선택한 공급자에 해당하는 쿠키가 없습니다. "
            f"허용 도메인: {', '.join(allowed)}"
        )
    return {
        "provider": normalized_provider,
        "inputPath": str(Path(input_path).expanduser().resolve()),
        "cookieCount": assessment["relevantCookieCount"],
        "ignoredCookieCount": assessment["ignoredCookieCount"],
        "domains": assessment["domains"],
        "authenticationRequired": assessment["authenticationRequired"],
        "authenticationReady": assessment["authenticationReady"],
        "authenticationReadinessVerifiable": assessment[
            "authenticationReadinessVerifiable"
        ],
        "missingRequiredCookieNames": assessment["missingRequiredCookieNames"],
        "missingRecommendedCookieNames": assessment["missingRecommendedCookieNames"],
        "containsValues": True,
        "willStoreInOsCredentialVault": True,
        "valuesExposed": False,
        "executed": False,
    }


def import_provider_cookies(
    provider: str,
    input_path: Path,
    *,
    backend: Any | None = None,
) -> dict[str, Any]:
    plan = cookie_import_plan(provider, input_path)
    cookies = parse_cookie_file(input_path)
    allowed_suffixes = tuple(
        COOKIE_PROVIDER_POLICIES[plan["provider"]]["allowedDomainSuffixes"]
    )
    if allowed_suffixes:
        cookies = [
            cookie
            for cookie in cookies
            if _cookie_matches_domain(cookie["domain"], allowed_suffixes)
        ]
    payload = {
        "format": "tokiDownloader-cookies",
        "formatVersion": 1,
        "provider": plan["provider"],
        "cookies": cookies,
        "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    store = _credential_backend(backend)
    store.set_password(
        CREDENTIAL_SERVICE,
        f"cookies:{plan['provider']}",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    return {**plan, "executed": True}


def _load_provider_cookie_payload(provider: str, backend: Any | None = None) -> dict[str, Any] | None:
    normalized_provider = normalize_cookie_provider(provider)
    store = _credential_backend(backend)
    secret = store.get_password(CREDENTIAL_SERVICE, f"cookies:{normalized_provider}")
    if not secret:
        return None
    try:
        payload = json.loads(secret)
    except json.JSONDecodeError as error:
        raise ValueError("OS 보안 저장소의 쿠키 데이터가 손상되었습니다.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("cookies"), list):
        raise ValueError("OS 보안 저장소의 쿠키 형식이 잘못되었습니다.")
    return payload


def provider_cookie_status(provider: str, *, backend: Any | None = None) -> dict[str, Any]:
    normalized_provider = normalize_cookie_provider(provider)
    payload = _load_provider_cookie_payload(normalized_provider, backend)
    cookies = payload.get("cookies", []) if payload else []
    assessment = assess_provider_cookies(normalized_provider, cookies)
    return {
        "provider": normalized_provider,
        "stored": payload is not None,
        "cookieCount": len(cookies),
        "domains": assessment["domains"],
        "authenticationRequired": assessment["authenticationRequired"],
        "authenticationReady": assessment["authenticationReady"],
        "authenticationReadinessVerifiable": assessment[
            "authenticationReadinessVerifiable"
        ],
        "missingRequiredCookieNames": assessment["missingRequiredCookieNames"],
        "missingRecommendedCookieNames": assessment["missingRecommendedCookieNames"],
        "updatedAt": str(payload.get("updatedAt") or "") if payload else "",
        "valuesExposed": False,
    }


def provider_cookie_request_header(
    provider: str,
    request_url: str,
    *,
    backend: Any | None = None,
    now_epoch: int | None = None,
) -> str:
    normalized_provider = normalize_cookie_provider(provider)
    policy = provider_cookie_policy(normalized_provider)
    parsed_url = urlsplit(str(request_url or "").strip())
    host = str(parsed_url.hostname or "").lower()
    if parsed_url.scheme not in {"http", "https"} or not host:
        raise ValueError("쿠키를 적용할 HTTP(S) 주소가 필요합니다.")
    allowed_suffixes = tuple(policy["allowedDomainSuffixes"])
    if allowed_suffixes and not _cookie_matches_domain(host, allowed_suffixes):
        raise ValueError("선택한 공급자와 요청 주소의 도메인이 일치하지 않습니다.")
    payload = _load_provider_cookie_payload(normalized_provider, backend)
    if payload is None:
        raise ValueError("선택한 공급자의 저장된 쿠키가 없습니다.")
    current_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
    request_path = parsed_url.path or "/"
    selected: list[dict[str, Any]] = []
    for raw_cookie in payload["cookies"]:
        if not isinstance(raw_cookie, dict):
            continue
        cookie = _normalize_cookie(raw_cookie)
        cookie_domain = cookie["domain"].lstrip(".")
        if host != cookie_domain and not host.endswith(f".{cookie_domain}"):
            continue
        if cookie["secure"] and parsed_url.scheme != "https":
            continue
        cookie_path = cookie["path"] or "/"
        if not request_path.startswith(cookie_path):
            continue
        if cookie["expires"] > 0 and cookie["expires"] <= current_epoch:
            continue
        selected.append(cookie)
    if not selected:
        raise ValueError("요청 주소에 적용할 수 있는 유효한 저장 쿠키가 없습니다.")
    selected.sort(key=lambda cookie: (-len(cookie["path"]), cookie["name"].casefold()))
    return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in selected)


def export_provider_cookies(
    provider: str,
    output_path: Path,
    *,
    backend: Any | None = None,
) -> dict[str, Any]:
    normalized_provider = normalize_cookie_provider(provider)
    payload = _load_provider_cookie_payload(normalized_provider, backend)
    if payload is None:
        raise ValueError("저장된 쿠키가 없습니다.")
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return {
        "provider": normalized_provider,
        "outputPath": str(target),
        "cookieCount": len(payload["cookies"]),
        "containsSensitiveValues": True,
        "executed": True,
    }


def clear_provider_cookies(provider: str, *, backend: Any | None = None) -> dict[str, Any]:
    normalized_provider = normalize_cookie_provider(provider)
    store = _credential_backend(backend)
    existing = store.get_password(CREDENTIAL_SERVICE, f"cookies:{normalized_provider}")
    if existing:
        try:
            store.delete_password(CREDENTIAL_SERVICE, f"cookies:{normalized_provider}")
        except Exception as error:
            if type(error).__name__ != "PasswordDeleteError":
                raise
    return {
        "provider": normalized_provider,
        "cleared": bool(existing),
        "executed": True,
    }


def normalize_folder_name_template(value: str | None) -> str:
    template = str(value or "").strip()
    if not template:
        raise ValueError("작품 폴더명 템플릿을 입력해주세요.")
    if len(template) > 180:
        raise ValueError("작품 폴더명 템플릿은 180자 이하여야 합니다.")

    fields: list[str] = []

    def collect_field(match: re.Match[str]) -> str:
        field = match.group(1)
        if field not in FOLDER_TEMPLATE_FIELDS:
            raise ValueError(f"지원하지 않는 폴더명 변수입니다: {{{field}}}")
        fields.append(field)
        return ""

    literal = re.sub(r"\{([A-Za-z][A-Za-z0-9_]*)\}", collect_field, template)
    if "{" in literal or "}" in literal:
        raise ValueError(
            "폴더명 변수는 {author}, {group}, {title}, {site}, {id} 형식으로 입력해주세요."
        )
    if _WINDOWS_INVALID_SEGMENT.search(literal):
        raise ValueError(
            "폴더명 템플릿의 고정 문자에 Windows 금지 문자를 사용할 수 없습니다."
        )
    if "title" not in fields:
        raise ValueError("작품을 구분할 수 있도록 {title} 변수가 필요합니다.")
    return template


def sanitize_windows_path_segment(value: Any, fallback: str = "N／A") -> str:
    sanitized = _WINDOWS_INVALID_SEGMENT.sub("", str(value or ""))
    sanitized = sanitized.rstrip(". ").strip() or fallback
    return f"_{sanitized}" if _WINDOWS_RESERVED_SEGMENT.fullmatch(sanitized) else sanitized


def render_folder_name_template(
    template: str | None,
    metadata: dict[str, Any] | None = None,
) -> str:
    normalized = normalize_folder_name_template(template or DEFAULT_FOLDER_TEMPLATE)
    source = metadata if isinstance(metadata, dict) else {}
    source_metadata = source.get("source")
    source_metadata = source_metadata if isinstance(source_metadata, dict) else {}
    values = {
        "author": sanitize_windows_path_segment(source.get("author")),
        "group": sanitize_windows_path_segment(source.get("group")),
        "title": sanitize_windows_path_segment(source.get("title"), "제목 없음"),
        "site": sanitize_windows_path_segment(
            source_metadata.get("siteTitle")
            or source.get("site")
            or source_metadata.get("site")
        ),
        "id": sanitize_windows_path_segment(
            source_metadata.get("workId") or source.get("id")
        ),
    }
    rendered = re.sub(
        r"\{([A-Za-z][A-Za-z0-9_]*)\}",
        lambda match: values[match.group(1)],
        normalized,
    )
    if not rendered or len(rendered) > 240:
        raise ValueError(
            "미리보기 폴더명이 비어 있거나 Windows 안전 길이 240자를 초과합니다."
        )
    if _WINDOWS_INVALID_SEGMENT.search(rendered) or rendered.endswith((".", " ")):
        raise ValueError("미리보기 폴더명이 Windows 경로 규칙에 맞지 않습니다.")
    if _WINDOWS_RESERVED_SEGMENT.fullmatch(rendered):
        raise ValueError("Windows 예약 장치 이름은 폴더명으로 사용할 수 없습니다.")
    return rendered


def folder_name_template_preview(
    template: str | None,
    *,
    metadata: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    site_title: str = "마나토끼",
) -> dict[str, Any]:
    sample = metadata or {
        "author": "이요미네 츠쿠",
        "group": "N／A",
        "title": "이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건",
        "source": {"siteTitle": "마나토끼", "workId": "34360"},
    }
    normalized = normalize_folder_name_template(template or DEFAULT_FOLDER_TEMPLATE)
    preview = render_folder_name_template(normalized, sample)
    candidate = ""
    exists = False
    if output_dir:
        candidate_path = (
            Path(output_dir).expanduser().resolve()
            / sanitize_windows_path_segment(site_title, "사이트")
            / preview
        )
        candidate = str(candidate_path)
        exists = candidate_path.exists()
    return {
        "ok": True,
        "dryRun": True,
        "template": normalized,
        "preview": preview,
        "candidatePath": candidate,
        "collision": exists,
        "existingFoldersChanged": False,
        "allowedFields": sorted(FOLDER_TEMPLATE_FIELDS),
    }


def quick_action_catalog() -> list[dict[str, str]]:
    return [dict(item) for item in QUICK_ACTIONS]


def normalize_quick_actions(value: Any) -> list[str]:
    if value is None:
        return list(default_config()["quickActions"])
    if not isinstance(value, (list, tuple)):
        raise ValueError("빠른 실행 도구는 동작 ID 목록이어야 합니다.")
    supported = {item["id"] for item in QUICK_ACTIONS}
    normalized: list[str] = []
    for item in value:
        action_id = str(item or "").strip()
        if action_id not in supported:
            raise ValueError(f"지원하지 않는 빠른 실행 동작입니다: {action_id}")
        if action_id not in normalized:
            normalized.append(action_id)
    if not normalized:
        raise ValueError("빠른 실행 도구를 하나 이상 선택해주세요.")
    return normalized


def normalize_completion_action(value: str | None) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized not in {"none", "exit", "shutdown"}:
        raise ValueError("완료 후 동작은 none, exit 또는 shutdown이어야 합니다.")
    return normalized


def normalize_completion_countdown(value: int | None) -> int:
    normalized = 15 if value is None else int(value)
    if not 5 <= normalized <= 300:
        raise ValueError("완료 후 동작 카운트다운은 5~300초여야 합니다.")
    return normalized


def normalize_notification_sound(value: str | None) -> str:
    normalized = str(value or "none").strip().lower()
    if normalized not in {"none", "system"}:
        raise ValueError("알림음은 none 또는 system이어야 합니다.")
    return normalized


def normalize_archive_viewer_mode(value: str | None) -> str:
    normalized = str(value or "system").strip().lower()
    if normalized not in {"system", "custom"}:
        raise ValueError("압축 파일 연결 프로그램 방식은 system 또는 custom이어야 합니다.")
    return normalized


def normalize_archive_viewer_path(value: str | os.PathLike[str] | None) -> str:
    normalized = str(value or "").strip()
    if "\x00" in normalized:
        raise ValueError("압축 파일 연결 프로그램 경로에 NUL 문자를 사용할 수 없습니다.")
    if len(normalized) > 32_767:
        raise ValueError("압축 파일 연결 프로그램 경로가 너무 깁니다.")
    return normalized


def normalize_autosave_interval_seconds(value: int | None) -> int:
    normalized = 1 if value is None else int(value)
    if not 1 <= normalized <= 300:
        raise ValueError("자동 저장 주기는 1~300초여야 합니다.")
    return normalized


def normalize_list_page_size(value: int | None) -> int:
    normalized = 200 if value is None else int(value)
    if not 25 <= normalized <= 1_000:
        raise ValueError("목록 페이지 크기는 25~1000개여야 합니다.")
    return normalized


def normalize_list_loaded_limit(value: int | None) -> int:
    normalized = 2_000 if value is None else int(value)
    if not 100 <= normalized <= 5_000:
        raise ValueError("메모리 내 작품 상한은 100~5000개여야 합니다.")
    return normalized


def normalize_list_scroll_lines(value: int | None) -> int:
    normalized = 3 if value is None else int(value)
    if not 1 <= normalized <= 20:
        raise ValueError("목록 스크롤 속도는 1~20단계여야 합니다.")
    return normalized


def normalize_local_api_port(value: int | None) -> int:
    normalized = 8765 if value is None else int(value)
    if not 1024 <= normalized <= 65_535:
        raise ValueError("로컬 HTTP API 포트는 1024~65535여야 합니다.")
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
    normalized["folderNameTemplate"] = _safe_normalize(
        normalize_folder_name_template,
        source.get("folderNameTemplate"),
        defaults["folderNameTemplate"],
    )
    normalized["uiLanguage"] = _safe_normalize(
        normalize_ui_language,
        source.get("uiLanguage"),
        defaults["uiLanguage"],
    )
    normalized["uiScale"] = _safe_normalize(
        normalize_ui_scale,
        source.get("uiScale"),
        defaults["uiScale"],
    )
    normalized["fontFamily"] = _safe_normalize(
        normalize_font_family,
        source.get("fontFamily"),
        defaults["fontFamily"],
    )
    normalized["backgroundImage"] = _safe_normalize(
        normalize_background_image,
        source.get("backgroundImage"),
        defaults["backgroundImage"],
    )
    normalized["proxyUrl"] = _safe_normalize(
        normalize_proxy_url,
        source.get("proxyUrl"),
        defaults["proxyUrl"],
    )
    normalized["speedLimitKib"] = _safe_normalize(
        normalize_speed_limit_kib,
        source.get("speedLimitKib"),
        defaults["speedLimitKib"],
    )
    normalized["providerPolicies"] = _safe_normalize(
        normalize_provider_policies,
        source.get("providerPolicies"),
        defaults["providerPolicies"],
    )
    for key in (
        "logVisible",
        "showBrowser",
        "trayEnabled",
        "closeToTray",
        "minimizeToTray",
        "notifyOnComplete",
        "notifyOnError",
        "notificationMessageBox",
        "thumbnailsVisible",
        "alwaysOnTop",
        "clipboardMonitor",
        "clipboardAutoDownload",
        "recoverInterruptedOnStartup",
        "listLazyLoading",
        "lowSpecMode",
        "preventSleepDuringDownloads",
        "pdfGenerationEnabled",
        "archiveAfterDownload",
        "archiveRemoveOriginals",
        "memoryDisplayEnabled",
        "localApiEnabled",
        "hitomiPreferJapaneseTitle",
        "hitomiUseOriginalImages",
        "youtubeEmbedSubtitles",
        "youtubeWriteThumbnail",
        "youtubeEmbedThumbnail",
        "youtubeWriteInfoJson",
        "youtubeWriteDescription",
        "youtubeEmbedMetadata",
        "youtubeEmbedChapters",
        "youtubeApplyUploadDateMtime",
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
    normalized["listViewMode"] = _safe_normalize(
        normalize_list_view_mode,
        source.get("listViewMode"),
        defaults["listViewMode"],
    )
    normalized["thumbnailSize"] = _safe_normalize(
        normalize_thumbnail_size,
        source.get("thumbnailSize"),
        defaults["thumbnailSize"],
    )
    normalized["windowOpacity"] = _safe_normalize(
        normalize_window_opacity,
        source.get("windowOpacity"),
        defaults["windowOpacity"],
    )
    normalized["quickActions"] = _safe_normalize(
        normalize_quick_actions,
        source.get("quickActions"),
        defaults["quickActions"],
    )
    normalized["shortcutOverrides"] = _safe_normalize(
        normalize_shortcut_overrides,
        source.get("shortcutOverrides"),
        defaults["shortcutOverrides"],
    )
    normalized["completionAction"] = _safe_normalize(
        normalize_completion_action,
        source.get("completionAction"),
        defaults["completionAction"],
    )
    normalized["completionCountdownSeconds"] = _safe_normalize(
        normalize_completion_countdown,
        source.get("completionCountdownSeconds"),
        defaults["completionCountdownSeconds"],
    )
    normalized["notificationSound"] = _safe_normalize(
        normalize_notification_sound,
        source.get("notificationSound"),
        defaults["notificationSound"],
    )
    normalized["imageResizeMaxWidth"] = _safe_normalize(
        normalize_image_resize_dimension,
        source.get("imageResizeMaxWidth"),
        defaults["imageResizeMaxWidth"],
    )
    normalized["imageResizeMaxHeight"] = _safe_normalize(
        normalize_image_resize_dimension,
        source.get("imageResizeMaxHeight"),
        defaults["imageResizeMaxHeight"],
    )
    normalized["imageExcludedExtensions"] = _safe_normalize(
        normalize_image_excluded_extensions,
        source.get("imageExcludedExtensions"),
        defaults["imageExcludedExtensions"],
    )
    normalized["archiveViewerMode"] = _safe_normalize(
        normalize_archive_viewer_mode,
        source.get("archiveViewerMode"),
        defaults["archiveViewerMode"],
    )
    normalized["archiveViewerPath"] = _safe_normalize(
        normalize_archive_viewer_path,
        source.get("archiveViewerPath"),
        defaults["archiveViewerPath"],
    )
    normalized["autosaveIntervalSeconds"] = _safe_normalize(
        normalize_autosave_interval_seconds,
        source.get("autosaveIntervalSeconds"),
        defaults["autosaveIntervalSeconds"],
    )
    normalized["listPageSize"] = _safe_normalize(
        normalize_list_page_size,
        source.get("listPageSize"),
        defaults["listPageSize"],
    )
    normalized["listLoadedLimit"] = _safe_normalize(
        normalize_list_loaded_limit,
        source.get("listLoadedLimit"),
        defaults["listLoadedLimit"],
    )
    normalized["listScrollLines"] = _safe_normalize(
        normalize_list_scroll_lines,
        source.get("listScrollLines"),
        defaults["listScrollLines"],
    )
    normalized["localApiPort"] = _safe_normalize(
        normalize_local_api_port,
        source.get("localApiPort"),
        defaults["localApiPort"],
    )
    normalized["hitomiServerMode"] = _safe_normalize(
        normalize_hitomi_server_mode,
        source.get("hitomiServerMode"),
        defaults["hitomiServerMode"],
    )
    normalized["hitomiManualServer"] = _safe_normalize(
        normalize_hitomi_manual_server,
        source.get("hitomiManualServer"),
        defaults["hitomiManualServer"],
    )
    normalized["hitomiServerPriority"] = _safe_normalize(
        normalize_hitomi_server_priority,
        source.get("hitomiServerPriority", defaults["hitomiServerPriority"]),
        defaults["hitomiServerPriority"],
    )
    normalized["hitomiMetadataMode"] = _safe_normalize(
        normalize_hitomi_metadata_mode,
        source.get("hitomiMetadataMode"),
        defaults["hitomiMetadataMode"],
    )
    normalized["hitomiFilenameMode"] = _safe_normalize(
        normalize_hitomi_filename_mode,
        source.get("hitomiFilenameMode"),
        defaults["hitomiFilenameMode"],
    )
    normalized["hitomiExcludedTags"] = _safe_normalize(
        normalize_hitomi_excluded_tags,
        source.get("hitomiExcludedTags"),
        defaults["hitomiExcludedTags"],
    )
    normalized["hitomiMetadataFileMode"] = _safe_normalize(
        normalize_hitomi_metadata_file_mode,
        source.get("hitomiMetadataFileMode"),
        defaults["hitomiMetadataFileMode"],
    )
    normalized["youtubeFormatMode"] = _safe_normalize(
        normalize_youtube_format_mode,
        source.get("youtubeFormatMode"),
        defaults["youtubeFormatMode"],
    )
    normalized["youtubeMaxHeight"] = _safe_normalize(
        normalize_youtube_max_height,
        source.get("youtubeMaxHeight"),
        defaults["youtubeMaxHeight"],
    )
    normalized["youtubeContainer"] = _safe_normalize(
        normalize_youtube_container,
        source.get("youtubeContainer"),
        defaults["youtubeContainer"],
    )
    normalized["youtubeVideoCodec"] = _safe_normalize(
        normalize_youtube_video_codec,
        source.get("youtubeVideoCodec"),
        defaults["youtubeVideoCodec"],
    )
    normalized["youtubeAudioCodec"] = _safe_normalize(
        normalize_youtube_audio_codec,
        source.get("youtubeAudioCodec"),
        defaults["youtubeAudioCodec"],
    )
    normalized["youtubeFilenameTemplate"] = _safe_normalize(
        normalize_youtube_filename_template,
        source.get("youtubeFilenameTemplate"),
        defaults["youtubeFilenameTemplate"],
    )
    normalized["youtubePreferredLanguages"] = _safe_normalize(
        normalize_youtube_languages, source.get("youtubePreferredLanguages"), defaults["youtubePreferredLanguages"]
    )
    normalized["youtubeSubtitleMode"] = _safe_normalize(
        normalize_youtube_subtitle_mode, source.get("youtubeSubtitleMode"), defaults["youtubeSubtitleMode"]
    )
    normalized["youtubeSubtitleFormat"] = _safe_normalize(
        normalize_youtube_subtitle_format, source.get("youtubeSubtitleFormat"), defaults["youtubeSubtitleFormat"]
    )
    normalized["youtubeAudioTrackMode"] = _safe_normalize(
        normalize_youtube_audio_track_mode, source.get("youtubeAudioTrackMode"), defaults["youtubeAudioTrackMode"]
    )
    normalized["youtubeCollectionOrder"] = _safe_normalize(
        normalize_youtube_collection_order,
        source.get("youtubeCollectionOrder"),
        defaults["youtubeCollectionOrder"],
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
    source_version = CONFIG_SCHEMA_VERSION
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                source_version = int(loaded.get("configVersion") or 0)
                config.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    normalized = normalize_config(config)
    if CONFIG_PATH.is_file() and source_version < CONFIG_SCHEMA_VERSION:
        backup = CONFIG_PATH.with_suffix(
            CONFIG_PATH.suffix + f".pre-v{CONFIG_SCHEMA_VERSION}.bak"
        )
        if not backup.exists():
            shutil.copy2(CONFIG_PATH, backup)
        temporary = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
        temporary.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, CONFIG_PATH)
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
        "notificationMessageBox",
        "thumbnailsVisible",
        "alwaysOnTop",
        "clipboardMonitor",
        "clipboardAutoDownload",
        "recoverInterruptedOnStartup",
        "listLazyLoading",
        "lowSpecMode",
        "preventSleepDuringDownloads",
        "pdfGenerationEnabled",
        "archiveAfterDownload",
        "archiveRemoveOriginals",
        "memoryDisplayEnabled",
        "localApiEnabled",
        "hitomiPreferJapaneseTitle",
        "hitomiUseOriginalImages",
        "youtubeEmbedSubtitles",
        "youtubeWriteThumbnail",
        "youtubeEmbedThumbnail",
        "youtubeWriteInfoJson",
        "youtubeWriteDescription",
        "youtubeEmbedMetadata",
        "youtubeEmbedChapters",
        "youtubeApplyUploadDateMtime",
    ):
        if key in updates:
            if not isinstance(updates[key], bool):
                raise ValueError(f"{key} 설정은 true 또는 false여야 합니다.")
            validated[key] = updates[key]
    normalizers: dict[str, Callable[[Any], Any]] = {
        "folderNameTemplate": normalize_folder_name_template,
        "uiLanguage": normalize_ui_language,
        "uiScale": normalize_ui_scale,
        "fontFamily": normalize_font_family,
        "backgroundImage": normalize_background_image,
        "proxyUrl": normalize_proxy_url,
        "speedLimitKib": normalize_speed_limit_kib,
        "providerPolicies": normalize_provider_policies,
        "workConcurrency": normalize_work_concurrency,
        "imageConcurrency": normalize_image_concurrency,
        "retryCount": normalize_retry_count,
        "retryBackoffSeconds": normalize_retry_backoff,
        "logMaxMiB": normalize_log_max_mib,
        "logBackupCount": normalize_log_backup_count,
        "rowDensity": normalize_row_density,
        "theme": normalize_theme,
        "listViewMode": normalize_list_view_mode,
        "thumbnailSize": normalize_thumbnail_size,
        "windowOpacity": normalize_window_opacity,
        "quickActions": normalize_quick_actions,
        "shortcutOverrides": normalize_shortcut_overrides,
        "completionAction": normalize_completion_action,
        "completionCountdownSeconds": normalize_completion_countdown,
        "notificationSound": normalize_notification_sound,
        "imageResizeMaxWidth": normalize_image_resize_dimension,
        "imageResizeMaxHeight": normalize_image_resize_dimension,
        "imageExcludedExtensions": normalize_image_excluded_extensions,
        "archiveViewerMode": normalize_archive_viewer_mode,
        "archiveViewerPath": normalize_archive_viewer_path,
        "autosaveIntervalSeconds": normalize_autosave_interval_seconds,
        "listPageSize": normalize_list_page_size,
        "listLoadedLimit": normalize_list_loaded_limit,
        "listScrollLines": normalize_list_scroll_lines,
        "localApiPort": normalize_local_api_port,
        "hitomiServerMode": normalize_hitomi_server_mode,
        "hitomiManualServer": normalize_hitomi_manual_server,
        "hitomiServerPriority": normalize_hitomi_server_priority,
        "hitomiMetadataMode": normalize_hitomi_metadata_mode,
        "hitomiFilenameMode": normalize_hitomi_filename_mode,
        "hitomiExcludedTags": normalize_hitomi_excluded_tags,
        "hitomiMetadataFileMode": normalize_hitomi_metadata_file_mode,
        "youtubeFormatMode": normalize_youtube_format_mode,
        "youtubeMaxHeight": normalize_youtube_max_height,
        "youtubeContainer": normalize_youtube_container,
        "youtubeVideoCodec": normalize_youtube_video_codec,
        "youtubeAudioCodec": normalize_youtube_audio_codec,
        "youtubeFilenameTemplate": normalize_youtube_filename_template,
        "youtubePreferredLanguages": normalize_youtube_languages,
        "youtubeSubtitleMode": normalize_youtube_subtitle_mode,
        "youtubeSubtitleFormat": normalize_youtube_subtitle_format,
        "youtubeAudioTrackMode": normalize_youtube_audio_track_mode,
        "youtubeCollectionOrder": normalize_youtube_collection_order,
    }
    for key, normalizer in normalizers.items():
        if key in updates:
            validated[key] = normalizer(updates[key])
    if validated.get("backgroundImage"):
        background_path = Path(validated["backgroundImage"]).expanduser().resolve()
        if not background_path.is_file():
            raise ValueError(f"배경 이미지 파일을 찾을 수 없습니다: {background_path}")
        validated["backgroundImage"] = str(background_path)
    if validated.get("archiveViewerPath"):
        viewer_path = Path(validated["archiveViewerPath"]).expanduser().resolve()
        if not viewer_path.is_file():
            raise ValueError(
                f"압축 파일 연결 프로그램을 찾을 수 없습니다: {viewer_path}"
            )
        validated["archiveViewerPath"] = str(viewer_path)
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
    if (
        {"archiveViewerMode", "archiveViewerPath"} & set(updates)
        and current["archiveViewerMode"] == "custom"
        and not current["archiveViewerPath"]
    ):
        raise ValueError("지정한 프로그램 방식을 사용하려면 실행 파일 경로가 필요합니다.")
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
    checks.append(package("keyring", "keyring", False))
    checks.append(package("PyQt6-WebEngine", "PyQt6-WebEngine", False))
    for name, executable, version_argument in (
        ("FFmpeg", "ffmpeg", "-version"),
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
    ytdlp_path = shutil.which("yt-dlp") or ""
    adjacent_ytdlp = Path(sys.executable).with_name(
        "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    )
    if not ytdlp_path and adjacent_ytdlp.is_file():
        ytdlp_path = str(adjacent_ytdlp)
    try:
        ytdlp_version = importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        ytdlp_version = ""
    checks.append(
        {
            "name": "yt-dlp",
            "kind": "optional",
            "available": bool(ytdlp_path or ytdlp_version),
            "version": (
                _command_version(ytdlp_path, "--version")
                if ytdlp_path
                else ytdlp_version
            ),
            "path": ytdlp_path or (str(Path(sys.executable).resolve()) if ytdlp_version else ""),
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
    parsed = urlsplit(value)
    if str(parsed.hostname or "").lower() in YOUTUBE_HOSTS:
        inspect_youtube_url(value)
    return value


def detect_download_provider(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlsplit(value)
    if str(parsed.hostname or "").lower() in YOUTUBE_HOSTS:
        inspect_youtube_url(value)
        return "youtube"
    match = re.search(r"/(novel|webtoon|comic|manhwa)/(\d+)", value, re.IGNORECASE)
    if match:
        return {
            "novel": "booktoki",
            "webtoon": "newtoki",
            "comic": "manatoki",
            "manhwa": "manatoki",
        }[match.group(1).lower()]
    return "toki"


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
        "maxLoadedJobs": 5_000,
        "maxProcessOutputBytes": 2 * 1024 * 1024,
    }


def memory_usage_snapshot(
    config: dict[str, Any] | None = None,
    *,
    process_id: int | None = None,
    child_limit: int = 200,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    selected_pid = max(1, int(process_id or os.getpid()))
    clean_child_limit = max(0, min(1000, int(child_limit)))
    sampled_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        virtual = psutil.virtual_memory()
        total_system = max(0, int(virtual.total))
        available_system = max(0, min(total_system, int(virtual.available)))
        used_system = max(0, total_system - available_system)
        process = psutil.Process(selected_pid)
        application_bytes = max(0, int(process.memory_info().rss))
        children: list[dict[str, Any]] = []
        inaccessible_children = 0
        for child in process.children(recursive=True):
            try:
                children.append(
                    {
                        "pid": int(child.pid),
                        "parentPid": int(child.ppid()),
                        "name": str(child.name()),
                        "status": str(child.status()),
                        "rssBytes": max(0, int(child.memory_info().rss)),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                inaccessible_children += 1
        children.sort(key=lambda item: (-int(item["rssBytes"]), int(item["pid"])))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError) as error:
        return {
            "ok": False,
            "displayEnabled": bool(source["memoryDisplayEnabled"]),
            "processId": selected_pid,
            "sampledAt": sampled_at,
            "error": str(error),
        }
    child_bytes = sum(int(item["rssBytes"]) for item in children)
    combined_bytes = application_bytes + child_bytes
    system_percent = (
        round((used_system / total_system) * 100, 1) if total_system else 0.0
    )
    application_percent = (
        round((combined_bytes / total_system) * 100, 2) if total_system else 0.0
    )
    severity = (
        "critical"
        if system_percent >= 90
        else "warning"
        if system_percent >= 80
        else "normal"
    )
    visible_children = children[:clean_child_limit]
    return {
        "ok": True,
        "displayEnabled": bool(source["memoryDisplayEnabled"]),
        "processId": selected_pid,
        "sampledAt": sampled_at,
        "application": {
            "ownRssBytes": application_bytes,
            "childRssBytes": child_bytes,
            "combinedRssBytes": combined_bytes,
            "percentOfSystem": application_percent,
            "childProcessCount": len(children),
            "inaccessibleChildCount": inaccessible_children,
            "children": visible_children,
            "childrenTruncated": len(children) > len(visible_children),
        },
        "system": {
            "totalBytes": total_system,
            "availableBytes": available_system,
            "usedBytes": used_system,
            "percent": system_percent,
        },
        "display": {
            "percent": max(0, min(100, int(round(system_percent)))),
            "severity": severity,
        },
    }


LOCAL_API_READ_ACTIONS = frozenset(
    {
        "ping",
        "status",
        "list_jobs",
        "job_info",
        "list_runs",
        "queue_list",
        "memory_status",
        "resource_status",
        "pdf_status",
        "notification_status",
        "list_performance_status",
        "sleep_prevention_status",
        "persistence_status",
        "image_processing_policy",
        "archive_viewer_policy",
    }
)
LOCAL_API_CONTROL_ACTIONS = frozenset(
    {
        "enqueue",
        "stop",
        "pause",
        "resume",
        "cancel",
        "queue_move",
        "retry",
        "rescan",
        "refresh_metadata",
        "set_image_concurrency",
        "set_concurrency",
        "set_retry_policy",
        "set_list_filter",
        "pin_job",
        "tag_job",
        "refresh_list",
    }
)
LOCAL_API_ALLOWED_ACTIONS = LOCAL_API_READ_ACTIONS | LOCAL_API_CONTROL_ACTIONS
LOCAL_API_MAX_REQUEST_BYTES = 64 * 1024


def generate_local_api_token(byte_count: int = 32) -> str:
    clean_count = max(24, min(64, int(byte_count)))
    return secrets.token_urlsafe(clean_count)


def local_api_policy_snapshot(
    config: dict[str, Any] | None = None,
    *,
    running: bool = False,
    current_port: int = 0,
    token: str = "",
    error: str = "",
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    clean_token = str(token or "")
    port = int(current_port or source["localApiPort"])
    return {
        "enabled": bool(source["localApiEnabled"]),
        "running": bool(running),
        "host": "127.0.0.1",
        "configuredPort": int(source["localApiPort"]),
        "port": port,
        "baseUrl": f"http://127.0.0.1:{port}" if running else "",
        "authentication": "Bearer",
        "tokenPresent": bool(clean_token),
        "tokenHint": f"…{clean_token[-6:]}" if clean_token else "",
        "tokenPersistent": False,
        "publicBindingAllowed": False,
        "corsEnabled": False,
        "maxRequestBytes": LOCAL_API_MAX_REQUEST_BYTES,
        "allowedActions": sorted(LOCAL_API_ALLOWED_ACTIONS),
        "error": str(error or ""),
    }


def _local_api_rejection(status_code: int, code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "statusCode": int(status_code),
        "errorCode": code,
        "error": message,
    }


def local_api_request_plan(
    method: str,
    target: str,
    headers: dict[str, Any] | None,
    body: bytes,
    expected_token: str,
) -> dict[str, Any]:
    clean_method = str(method or "").upper()
    if clean_method not in {"GET", "POST"}:
        return _local_api_rejection(405, "method_not_allowed", "GET과 POST만 지원합니다.")
    if len(body) > LOCAL_API_MAX_REQUEST_BYTES:
        return _local_api_rejection(413, "request_too_large", "요청 본문이 64 KiB를 넘습니다.")
    normalized_headers = {
        str(key).strip().casefold(): str(value).strip()
        for key, value in (headers or {}).items()
    }
    authorization = normalized_headers.get("authorization", "")
    supplied_token = normalized_headers.get("x-toki-token", "")
    if authorization.casefold().startswith("bearer "):
        supplied_token = authorization[7:].strip()
    expected = str(expected_token or "")
    authorized = bool(expected) and hmac.compare_digest(
        supplied_token.encode("utf-8", errors="replace"),
        expected.encode("utf-8", errors="replace"),
    )
    if not authorized:
        return _local_api_rejection(401, "unauthorized", "유효한 Bearer 토큰이 필요합니다.")
    parsed = urlsplit(str(target or ""))
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query, keep_blank_values=False)
    if clean_method == "GET" and path == "/v1/health":
        return {"ok": True, "statusCode": 200, "route": "health", "request": None}
    if clean_method == "GET" and path == "/v1/status":
        return {
            "ok": True,
            "statusCode": 200,
            "route": "control",
            "request": {"action": "status"},
        }
    if clean_method == "GET" and path == "/v1/jobs":
        try:
            limit = max(1, min(1000, int((query.get("limit") or [200])[0])))
            offset = max(0, int((query.get("offset") or [0])[0]))
        except (TypeError, ValueError):
            return _local_api_rejection(400, "invalid_query", "limit 또는 offset이 올바르지 않습니다.")
        return {
            "ok": True,
            "statusCode": 200,
            "route": "control",
            "request": {
                "action": "list_jobs",
                "query": str((query.get("query") or [""])[0]),
                "status": str((query.get("status") or [""])[0]),
                "sort": str((query.get("sort") or ["updated"])[0]),
                "limit": limit,
                "offset": offset,
            },
        }
    if clean_method == "POST" and path == "/v1/control":
        content_type = normalized_headers.get("content-type", "")
        if "application/json" not in content_type.casefold():
            return _local_api_rejection(415, "unsupported_media_type", "application/json 본문이 필요합니다.")
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _local_api_rejection(400, "invalid_json", "요청 JSON을 읽을 수 없습니다.")
        if not isinstance(request, dict):
            return _local_api_rejection(400, "invalid_request", "JSON 객체가 필요합니다.")
        action = str(request.get("action") or "")
        if action not in LOCAL_API_ALLOWED_ACTIONS:
            return _local_api_rejection(403, "action_not_allowed", "로컬 API에서 허용하지 않는 동작입니다.")
        return {
            "ok": True,
            "statusCode": 200,
            "route": "control",
            "request": request,
        }
    return _local_api_rejection(404, "not_found", "지원하지 않는 로컬 API 경로입니다.")


def list_performance_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    low_spec = bool(source["lowSpecMode"])
    configured_page_size = int(source["listPageSize"])
    configured_loaded_limit = int(source["listLoadedLimit"])
    configured_scroll_lines = int(source["listScrollLines"])
    configured_lazy = bool(source["listLazyLoading"])
    return {
        "configured": {
            "pageSize": configured_page_size,
            "loadedLimit": configured_loaded_limit,
            "scrollLines": configured_scroll_lines,
            "lazyLoading": configured_lazy,
            "lowSpecMode": low_spec,
        },
        "effective": {
            "pageSize": (
                min(configured_page_size, 100)
                if low_spec
                else configured_page_size
            ),
            "loadedLimit": (
                min(configured_loaded_limit, 500)
                if low_spec
                else configured_loaded_limit
            ),
            "scrollLines": (
                min(configured_scroll_lines, 3)
                if low_spec
                else configured_scroll_lines
            ),
            "lazyLoading": True if low_spec else configured_lazy,
            "thumbnailsVisible": (
                False if low_spec else bool(source["thumbnailsVisible"])
            ),
            "thumbnailCacheEntries": 32 if low_spec else 128,
        },
        "databasePagination": True,
        "visibleOnlyThumbnailDecode": True,
        "eagerLoadingOptIn": not configured_lazy and not low_spec,
    }


class SleepPreventionController:
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_CONTINUOUS = 0x80000000

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        execution_state_setter: Callable[[int], int] | None = None,
    ) -> None:
        self.platform_name = str(platform_name or os.name)
        self.available = self.platform_name == "nt"
        self._execution_state_setter = execution_state_setter
        self.requested = False
        self.active = False
        self.last_flags = 0
        self.last_error = ""
        self.transition_count = 0

    @staticmethod
    def _windows_set_execution_state(flags: int) -> int:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        setter = kernel32.SetThreadExecutionState
        setter.argtypes = [ctypes.c_uint]
        setter.restype = ctypes.c_uint
        result = int(setter(int(flags)))
        if result == 0:
            error_code = int(ctypes.get_last_error())
            raise OSError(error_code, "Windows 절전 방지 요청에 실패했습니다.")
        return result

    def set_required(self, required: bool) -> dict[str, Any]:
        target = bool(required)
        self.requested = target
        if not self.available:
            self.active = False
            self.last_flags = 0
            self.last_error = ""
            return self.snapshot()
        if target == self.active:
            return self.snapshot()
        flags = self.ES_CONTINUOUS | (self.ES_SYSTEM_REQUIRED if target else 0)
        setter = self._execution_state_setter or self._windows_set_execution_state
        try:
            result = int(setter(flags))
            if result == 0:
                raise OSError("Windows 절전 방지 요청이 거부되었습니다.")
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.last_flags = flags
            self.last_error = str(error)
            return self.snapshot()
        self.active = target
        self.last_flags = flags
        self.last_error = ""
        self.transition_count += 1
        return self.snapshot()

    def close(self) -> dict[str, Any]:
        return self.set_required(False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "ok": not bool(self.last_error),
            "available": self.available,
            "platform": self.platform_name,
            "requested": self.requested,
            "active": self.active,
            "lastFlags": self.last_flags,
            "lastError": self.last_error,
            "transitionCount": self.transition_count,
            "mechanism": "SetThreadExecutionState" if self.available else "unsupported",
            "preventsSystemSleepOnly": True,
            "preventsDisplaySleep": False,
        }


def sleep_prevention_policy_snapshot(
    config: dict[str, Any] | None = None,
    *,
    active_downloads: int = 0,
    controller: SleepPreventionController | dict[str, Any] | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    active_count = max(0, int(active_downloads))
    configured = bool(source["preventSleepDuringDownloads"])
    if isinstance(controller, SleepPreventionController):
        runtime = controller.snapshot()
    elif isinstance(controller, dict):
        runtime = dict(controller)
    else:
        selected_platform = str(platform_name or os.name)
        runtime = SleepPreventionController(
            platform_name=selected_platform
        ).snapshot()
    requested = configured and active_count > 0
    return {
        "ok": bool(runtime.get("ok", True)),
        "configured": configured,
        "activeDownloads": active_count,
        "requested": requested,
        "active": bool(runtime.get("active", False)),
        "available": bool(runtime.get("available", False)),
        "platform": str(runtime.get("platform") or platform_name or os.name),
        "mechanism": str(runtime.get("mechanism") or "unsupported"),
        "preventsSystemSleepOnly": True,
        "preventsDisplaySleep": False,
        "lastFlags": int(runtime.get("lastFlags") or 0),
        "lastError": str(runtime.get("lastError") or ""),
        "transitionCount": int(runtime.get("transitionCount") or 0),
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


def normalize_shortcut_sequence(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 80:
        raise ValueError("단축키는 1~80자로 입력해주세요.")
    try:
        from PyQt6.QtGui import QKeySequence
    except ImportError as error:
        raise RuntimeError("단축키 검증에는 PyQt6가 필요합니다.") from error
    sequence = QKeySequence.fromString(
        raw, QKeySequence.SequenceFormat.PortableText
    )
    portable = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    if not portable:
        raise ValueError(f"인식할 수 없는 단축키입니다: {raw}")
    if sequence.count() != 1:
        raise ValueError("한 항목에는 단일 키 조합만 사용할 수 있습니다.")
    if portable.casefold() == "alt+f4":
        raise ValueError("Alt+F4는 프로그램 종료 키라 지정할 수 없습니다.")
    safe_unmodified = {
        "return", "enter", "escape", "tab", "backspace", "delete", "insert",
        "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
    }
    if "+" not in portable and not re.fullmatch(r"F(?:[1-9]|[12][0-9]|3[0-5])", portable):
        if portable.casefold() not in safe_unmodified:
            raise ValueError("입력 중 오작동을 막기 위해 단일 문자에는 Ctrl·Alt·Shift·Meta가 필요합니다.")
    return portable


def normalize_shortcut_overrides(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("단축키 설정은 동작별 배열을 담은 객체여야 합니다.")
    source = value
    known_ids = {str(item["id"]) for item in KEYBOARD_SHORTCUTS}
    unknown = sorted(set(map(str, source)) - known_ids)
    if unknown:
        raise ValueError(f"지원하지 않는 단축키 동작입니다: {', '.join(unknown)}")
    normalized: dict[str, list[str]] = {}
    for action_id, raw_keys in source.items():
        if not isinstance(raw_keys, (list, tuple)):
            raise ValueError(f"{action_id} 단축키는 배열이어야 합니다.")
        if len(raw_keys) > 4:
            raise ValueError("동작 하나에는 단축키를 최대 4개 지정할 수 있습니다.")
        keys: list[str] = []
        for raw_key in raw_keys:
            key = normalize_shortcut_sequence(str(raw_key))
            if key.casefold() not in {existing.casefold() for existing in keys}:
                keys.append(key)
        normalized[str(action_id)] = keys
    effective: dict[str, list[str]] = {}
    for item in KEYBOARD_SHORTCUTS:
        action_id = str(item["id"])
        effective[action_id] = list(
            normalized.get(action_id, list(item["keys"]))
        )
    owners: dict[str, str] = {}
    for action_id, keys in effective.items():
        for key in keys:
            folded = key.casefold()
            previous = owners.get(folded)
            if previous and previous != action_id:
                raise ValueError(
                    f"단축키 {key}가 {previous}와 {action_id}에 중복 지정되었습니다."
                )
            owners[folded] = action_id
    return normalized


def parse_shortcut_keys_text(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(";") if part.strip()]


def keyboard_shortcut_catalog(
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source = normalize_config(config) if config is not None else load_config()
    overrides = normalize_shortcut_overrides(source.get("shortcutOverrides"))
    return [
        {
            **item,
            "defaultKeys": list(item["keys"]),
            "keys": list(overrides.get(str(item["id"]), list(item["keys"]))),
            "overridden": str(item["id"]) in overrides,
            "enabled": bool(overrides.get(str(item["id"]), list(item["keys"]))),
        }
        for item in KEYBOARD_SHORTCUTS
    ]


def keyboard_shortcut_keys(
    action_id: str,
    config: dict[str, Any] | None = None,
) -> list[str]:
    normalized = str(action_id or "").strip()
    for item in keyboard_shortcut_catalog(config):
        if item["id"] == normalized:
            return list(item["keys"])
    raise ValueError(f"지원하지 않는 단축키 동작입니다: {action_id}")


def shortcut_settings_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    overrides = normalize_shortcut_overrides(source.get("shortcutOverrides"))
    catalog = keyboard_shortcut_catalog(source)
    return {
        "count": len(catalog),
        "overrideCount": len(overrides),
        "disabledCount": sum(1 for keys in overrides.values() if not keys),
        "shortcutOverrides": overrides,
        "shortcuts": catalog,
    }


def export_shortcut_settings(output_path: Path) -> dict[str, Any]:
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = shortcut_settings_snapshot()
    payload = {
        "format": "tokiDownloader-shortcuts",
        "formatVersion": 1,
        "appVersion": APP_VERSION,
        "shortcutOverrides": snapshot["shortcutOverrides"],
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return {
        "ok": True,
        "path": str(target),
        "overrideCount": snapshot["overrideCount"],
        "containsSecrets": False,
    }


def shortcut_import_plan(input_path: Path) -> dict[str, Any]:
    source_path = Path(input_path).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"단축키 파일을 찾을 수 없습니다: {source_path}")
    if source_path.stat().st_size > 1024 * 1024:
        raise ValueError("단축키 파일은 1 MiB 이하여야 합니다.")
    payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("format") != "tokiDownloader-shortcuts":
        raise ValueError("tokiDownloader 단축키 파일 형식이 아닙니다.")
    if int(payload.get("formatVersion") or 0) != 1:
        raise ValueError("지원하지 않는 단축키 파일 버전입니다.")
    overrides = normalize_shortcut_overrides(payload.get("shortcutOverrides"))
    current_config = load_config()
    before = shortcut_settings_snapshot(current_config)
    after_config = dict(current_config)
    after_config["shortcutOverrides"] = overrides
    after = shortcut_settings_snapshot(after_config)
    changed = [
        item["id"]
        for item in after["shortcuts"]
        if item["keys"]
        != next(
            before_item["keys"]
            for before_item in before["shortcuts"]
            if before_item["id"] == item["id"]
        )
    ]
    return {
        "ok": True,
        "inputPath": str(source_path),
        "shortcutOverrides": overrides,
        "changedActions": changed,
        "changedCount": len(changed),
        "executed": False,
    }


def import_shortcut_settings(input_path: Path, *, execute: bool = False) -> dict[str, Any]:
    plan = shortcut_import_plan(input_path)
    if not execute:
        return plan
    saved = update_app_settings(
        {"shortcutOverrides": plan["shortcutOverrides"]}
    )
    return {
        **plan,
        "shortcutOverrides": saved["shortcutOverrides"],
        "executed": True,
    }


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


def completion_action_plan(
    action: str,
    countdown_seconds: int,
    *,
    active_count: int = 0,
    pending_count: int = 0,
    armed: bool = True,
) -> dict[str, Any]:
    normalized_action = normalize_completion_action(action)
    countdown = normalize_completion_countdown(countdown_seconds)
    idle = max(0, int(active_count)) == 0 and max(0, int(pending_count)) == 0
    return {
        "action": normalized_action,
        "countdownSeconds": countdown,
        "activeCount": max(0, int(active_count)),
        "pendingCount": max(0, int(pending_count)),
        "idle": idle,
        "armed": bool(armed),
        "shouldTrigger": bool(armed and idle and normalized_action != "none"),
        "requiresCountdown": normalized_action in {"exit", "shutdown"},
        "destructive": normalized_action == "shutdown",
    }


def notification_settings_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    return {
        "notifyOnComplete": bool(source["notifyOnComplete"]),
        "notifyOnError": bool(source["notifyOnError"]),
        "sound": str(source["notificationSound"]),
        "messageBox": bool(source["notificationMessageBox"]),
        "supportedSounds": ["none", "system"],
    }


def notification_event_plan(
    kind: str,
    *,
    title: str = "",
    detail: str = "",
    config: dict[str, Any] | None = None,
    preview: bool = False,
) -> dict[str, Any]:
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in {"complete", "error"}:
        raise ValueError("알림 종류는 complete 또는 error여야 합니다.")
    settings = notification_settings_snapshot(config)
    clean_title = str(title or "작품").strip()[:500] or "작품"
    clean_detail = str(detail or "").strip()[:1000]
    configured = bool(
        settings[
            "notifyOnComplete" if normalized_kind == "complete" else "notifyOnError"
        ]
    )
    enabled = bool(preview or configured)
    if normalized_kind == "complete":
        message = f"다운로드 완료: {clean_title}"
    else:
        message = f"{clean_title}: {clean_detail or '오류'}"
    sound = str(settings["sound"]) if enabled else "none"
    return {
        "kind": normalized_kind,
        "title": clean_title,
        "detail": clean_detail,
        "message": message,
        "configured": configured,
        "enabled": enabled,
        "preview": bool(preview),
        "trayRequested": enabled,
        "messageBoxRequested": bool(enabled and settings["messageBox"]),
        "sound": sound,
        "soundRequested": sound == "system",
        "executed": False,
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
    provider: str = ""
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
    simulation: bool = False
    external_request_confirmed: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if not self.provider:
            self.provider = detect_download_provider(self.url)
        if not self.site and self.provider == "youtube":
            self.site = "youtube"
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
                "youtube_simulation"
                if job.provider == "youtube" and job.simulation
                else (
                    "youtube_download"
                    if job.provider == "youtube"
                    else (
                        "metadata_refresh"
                        if job.metadata_only
                        else f"download_{normalize_scan_mode(job.scan_mode)}"
                    )
                )
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
    parsed = urlsplit(value)
    if str(parsed.hostname or "").lower() in YOUTUBE_HOSTS:
        reference = inspect_youtube_url(value)
        if reference["referenceType"] == "video":
            return f"youtube:video:{reference['videoId']}"
        if reference["referenceType"] == "playlist":
            return f"youtube:playlist:{reference['playlistId']}"
        return f"youtube:channel:{str(reference['channelPath']).casefold()}"
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
    normalized_path = parsed.path.rstrip("/").lower()
    return f"url:{parsed.hostname or ''}{normalized_path}"


def inspect_clipboard_url(
    text: str, *, existing_work_keys: tuple[str, ...] | list[str] | set[str] = ()
) -> dict[str, Any]:
    """Inspect at most 32 URLs in 65,536 characters; never fetch or enqueue.

    Only the modern work-list route is unambiguous without a network request.
    Legacy chapter URLs and arbitrary hosts must not pass via build_work_key's
    intentionally permissive identity extraction. One copy adds at most one work.
    """
    value = str(text or "")
    result: dict[str, Any] = {
        "ok": True,
        "candidate": False,
        "duplicate": False,
        "reason": "no_https_url",
        "url": "",
        "workKey": "",
        "validation": "url_shape_only",
    }
    if len(value) > 65_536:
        return {**result, "reason": "text_too_long"}
    for index, match in enumerate(re.finditer(r"https://[^\s<>\"']+", value, re.IGNORECASE)):
        if index >= 32:
            break
        result["reason"] = "unsupported_url"
        url = match.group(0).rstrip(".,;:!?)]}>\"'")
        if "\\" in url or re.search(r"[\x00-\x1f\x7f]", url):
            continue
        try:
            parsed = urlsplit(url)
            host = str(parsed.hostname or "").lower()
            if (
                parsed.scheme.lower() != "https"
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)
                or not re.fullmatch(r"newtoki[0-9]+\.org", host)
            ):
                continue
            route = re.fullmatch(r"/manhwa/([1-9][0-9]{0,19})/?", parsed.path)
            if not route:
                continue
        except ValueError:
            continue
        # Remove pagination/tracking/fragment parameters: always scan the work
        # from its canonical first page, with the downloader validating content.
        normalized = f"https://{host}/manhwa/{route.group(1)}"
        work_key = build_work_key(normalized)
        duplicate = work_key in existing_work_keys
        return {
            **result,
            "candidate": True,
            "duplicate": duplicate,
            "reason": "duplicate" if duplicate else "new",
            "url": normalized,
            "workKey": work_key,
        }
    return result


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


def archive_viewer_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the app-local archive opener without changing OS associations."""
    source = normalize_config(config) if config is not None else load_config()
    mode = normalize_archive_viewer_mode(source.get("archiveViewerMode"))
    viewer_path = normalize_archive_viewer_path(source.get("archiveViewerPath"))
    custom_available = bool(viewer_path and Path(viewer_path).is_file())
    if os.name == "nt":
        system_available = hasattr(os, "startfile")
        system_label = "Windows 기본 연결 프로그램"
    elif sys.platform == "darwin":
        system_available = bool(shutil.which("open"))
        system_label = "macOS 기본 연결 프로그램"
    else:
        system_available = bool(shutil.which("xdg-open"))
        system_label = "시스템 기본 연결 프로그램"
    available = system_available if mode == "system" else custom_available
    return {
        "mode": mode,
        "viewerPath": viewer_path,
        "configured": mode == "system" or bool(viewer_path),
        "available": available,
        "label": system_label if mode == "system" else (Path(viewer_path).name or "지정한 프로그램"),
        "supportedExtensions": sorted(SUPPORTED_ARCHIVE_EXTENSIONS),
        "changesSystemAssociation": False,
        "requiresConfirmation": True,
    }


def plan_archive_viewer_open(
    archive_path: Path,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(archive_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"압축 파일이 없습니다: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_ARCHIVE_EXTENSIONS:
        raise ValueError(f"지원하지 않는 압축 형식입니다: {suffix or '(확장자 없음)'}")
    policy = archive_viewer_policy_snapshot(config)
    command = (
        [policy["viewerPath"], str(source)]
        if policy["mode"] == "custom"
        else ["<system-association>", str(source)]
    )
    error = ""
    if not policy["available"]:
        error = (
            "지정한 압축 파일 연결 프로그램을 찾을 수 없습니다."
            if policy["mode"] == "custom"
            else "시스템 기본 연결 프로그램을 사용할 수 없습니다."
        )
    return {
        "ok": not error,
        "executed": False,
        "path": str(source),
        "extension": suffix,
        "mode": policy["mode"],
        "viewerPath": policy["viewerPath"],
        "viewerLabel": policy["label"],
        "command": command,
        "requiresConfirmation": True,
        "changesSystemAssociation": False,
        "filesChanged": False,
        "error": error,
    }


def _launch_archive_viewer(plan: dict[str, Any]) -> int | None:
    if plan["mode"] == "system" and os.name == "nt":
        os.startfile(plan["path"])  # type: ignore[attr-defined]
        return None
    command = (
        ["open", plan["path"]]
        if plan["mode"] == "system" and sys.platform == "darwin"
        else ["xdg-open", plan["path"]]
        if plan["mode"] == "system"
        else list(plan["command"])
    )
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    return int(process.pid)


def open_archive_with_viewer(
    archive_path: Path,
    *,
    config: dict[str, Any] | None = None,
    execute: bool = False,
    launcher: Callable[[dict[str, Any]], int | None] | None = None,
) -> dict[str, Any]:
    plan = plan_archive_viewer_open(archive_path, config=config)
    if not execute:
        return plan
    if not plan["ok"]:
        raise RuntimeError(str(plan["error"]))
    process_id = (launcher or _launch_archive_viewer)(plan)
    return {
        **plan,
        "executed": True,
        "processId": process_id,
    }


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
    execute: bool = True,
) -> dict[str, Any]:
    interrupted_states = tuple(sorted(ACTIVE_JOB_STATES))
    placeholders = ", ".join("?" for _ in interrupted_states)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    candidate_jobs: list[tuple[str, DownloadJob]] = []
    candidate_runs: list[tuple[str, DownloadRun]] = []
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
            candidate_jobs.append((str(job_id), job))
        for run_id, payload in run_rows:
            run = _decode_run(payload)
            if run is not None:
                candidate_runs.append((str(run_id), run))

        if execute:
            with connection:
                for job_id, job in candidate_jobs:
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

                for run_id, run in candidate_runs:
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
    finally:
        connection.close()
    return {
        "ok": True,
        "executed": bool(execute),
        "jobCount": len(candidate_jobs),
        "runCount": len(candidate_runs),
        "jobIds": [job_id for job_id, _job in candidate_jobs],
        "runIds": [run_id for run_id, _run in candidate_runs],
        "activeStates": list(interrupted_states),
        "reason": reason,
        "filesChanged": False,
    }


def persistence_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    return {
        "autosaveIntervalSeconds": int(source["autosaveIntervalSeconds"]),
        "autosaveEnabled": True,
        "startupRecoveryEnabled": bool(source["recoverInterruptedOnStartup"]),
        "recoveryAction": "mark_stopped",
        "preservesProgress": True,
        "preservesDownloadedFiles": True,
        "requiresConfirmationForManualRecovery": True,
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


def build_downloader_args(
    job: DownloadJob,
    json_events: bool = True,
    folder_template: str | None = None,
    network_config: dict[str, Any] | None = None,
) -> list[str]:
    args = [str(DOWNLOADER_PATH), "-url", job.url, "-output", job.output_dir]
    args.extend(
        [
            "-folder-template",
            normalize_folder_name_template(folder_template or DEFAULT_FOLDER_TEMPLATE),
        ]
    )
    network = network_policy_snapshot(network_config or default_config(), url=job.url)
    if network["proxyUrl"]:
        args.extend(["-proxy", str(network["proxyUrl"])])
    args.extend(["-speed-limit-kib", str(network["speedLimitKib"])])
    provider_policy = network["providerPolicy"] or {
        "requestDelayMs": 0,
        "backoffSeconds": 2,
    }
    args.extend(["-request-delay-ms", str(provider_policy["requestDelayMs"])])
    args.extend(["-provider-backoff", str(provider_policy["backoffSeconds"])])
    if job.start is not None:
        args.extend(["-start", str(job.start)])
    if job.last is not None:
        args.extend(["-last", str(job.last)])
    if job.show_browser:
        args.append("-show-browser")
    if job.output_path:
        args.extend(["-content-path", job.output_path])
    if job.metadata_only:
        args.append("-metadata-only")
    else:
        args.extend(["-scan-mode", normalize_scan_mode(job.scan_mode)])
    args.extend(["-image-concurrency", str(normalize_image_concurrency(job.image_concurrency))])
    if json_events:
        args.append("-json-events")
    return args


def build_youtube_worker_args(
    job: DownloadJob,
    config: dict[str, Any] | None = None,
    *,
    simulation_delay_ms: int = 0,
) -> list[str]:
    if job.provider != "youtube":
        raise ValueError("YouTube 작업만 YouTube 실행기로 시작할 수 있습니다.")
    if not job.simulation and not job.external_request_confirmed:
        raise ValueError("YouTube 외부 요청 실행에는 명시적 확인이 필요합니다.")
    arguments = [
        str(YOUTUBE_WORKER_PATH),
        "--url",
        job.url,
        "--output",
        job.output_dir,
        "--config-json",
        json.dumps(youtube_execution_config_snapshot(config), ensure_ascii=False),
    ]
    if job.simulation:
        arguments.append("--simulate")
        if simulation_delay_ms:
            arguments.extend(("--simulate-delay-ms", str(max(0, int(simulation_delay_ms)))))
    return arguments


def retry_job_parameters(source: DownloadJob) -> dict[str, Any]:
    """Return the shared full-rescan contract used by GUI and CLI retries."""
    if source.provider == "youtube":
        return {
            "url": source.url,
            "start": None,
            "last": None,
            "output_dir": source.output_dir,
            "show_browser": False,
            "scan_mode": "new",
            "simulation": source.simulation,
            "external_request_confirmed": source.external_request_confirmed,
        }
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


_LEGACY_EPISODE_FOLDER = re.compile(r"^(\d{4,})\s+(.+\S|\S)$")
_EPISODE_RENAME_ARTIFACT_PREFIX = ".toki-episode-rename-"
_EPISODE_RENAME_TRANSACTION = re.compile(
    r"^\.toki-episode-rename-([0-9a-f]{32})\.json$",
    re.IGNORECASE,
)
_KNOWN_R18_ARTIFACT_WORK_TITLE = "남녀비 139의 평행세계는 의외로 평범"
_EPISODE_CONTEXT_RANGE = re.compile(
    r"\d+(?:\.\d+)?\s*[~～–—]\s*\d+(?:\.\d+)?\s*화"
)
_EPISODE_CONTEXT_TOKEN = re.compile(
    r"(?<![\d.])(?P<number>\d+)"
    r"(?:(?P<decimal>\.(?P<decimal_digits>\d+))|"
    r"(?P<hyphen_separator>\s*-\s*)(?P<hyphen_digits>\d+))?"
    r"(?P<unit_spacing>\s*)화"
)
_WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS = 240
_WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS = 248
_LEGACY_EPISODE_INLINE_HTML_TAG = re.compile(
    r"</?(?:abbr|b|bdi|bdo|br|cite|code|data|del|dfn|em|i|img|ins|kbd|mark|q|"
    r"rp|rt|ruby|s|samp|small|span|strong|sub|sup|time|u|var|wbr)\b[^<>]*>",
    re.IGNORECASE,
)
_LEGACY_EPISODE_HTML_ENTITY = re.compile(
    r"&(#(?:x[0-9a-f]+|[0-9]+)|[a-z][a-z0-9]+);",
    re.IGNORECASE,
)
_LEGACY_EPISODE_HTML_ENTITIES = {
    "amp": "&",
    "apos": "'",
    "gt": ">",
    "hellip": "…",
    "lt": "<",
    "mdash": "—",
    "middot": "·",
    "nbsp": "\u00a0",
    "ndash": "–",
    "quot": '"',
}
_LEGACY_EPISODE_IMAGE_FILE = re.compile(
    r"(?:^|\s)image\d{4}\.(?:jpe?g|png|webp|gif|bmp|avif)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EpisodeRenameJobSnapshot:
    job_id: str
    work_key: str
    title: str
    state: str
    output_path: str


def episode_rename_job_snapshot(job: DownloadJob) -> EpisodeRenameJobSnapshot:
    """Capture the GUI-visible fields needed by a read-only rename plan."""

    return EpisodeRenameJobSnapshot(
        job_id=str(job.job_id),
        work_key=str(job.work_key),
        title=str(job.title),
        state=str(job.state),
        output_path=str(job.output_path),
    )


def _episode_rename_resolve_job(
    job_id: str,
    job_snapshot: EpisodeRenameJobSnapshot | DownloadJob | None,
) -> EpisodeRenameJobSnapshot | DownloadJob:
    if job_snapshot is None:
        job = load_job_by_id(job_id)
        if job is None:
            raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
        return job
    snapshot = (
        episode_rename_job_snapshot(job_snapshot)
        if isinstance(job_snapshot, DownloadJob)
        else job_snapshot
    )
    if not isinstance(snapshot, EpisodeRenameJobSnapshot):
        raise TypeError("회차 폴더명 계획의 작업 snapshot 형식이 올바르지 않습니다.")
    if snapshot.job_id != str(job_id):
        raise ValueError("회차 폴더명 계획의 작업 ID와 snapshot이 일치하지 않습니다.")
    return snapshot


def _episode_rename_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}을 읽을 수 없습니다: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label}은 JSON 객체여야 합니다: {path}")
    return payload


def _episode_rename_record_folders(record: dict[str, Any]) -> list[str]:
    values = [
        record.get("folderName"),
        *(record.get("folderHints") if isinstance(record.get("folderHints"), list) else []),
        record.get("displayTitle"),
        record.get("sourceTitle"),
    ]
    folders: list[str] = []
    seen: set[str] = set()
    for value in values:
        folder = sanitize_windows_path_segment(str(value or ""), "").strip()
        key = folder.casefold()
        if folder and key not in seen:
            folders.append(folder)
            seen.add(key)
    return folders


def _episode_rename_stable_id(record: dict[str, Any]) -> str:
    source_id = str(record.get("sourceId") or "").strip()
    if source_id:
        return source_id
    source_url = str(record.get("sourceUrl") or "").strip()
    if not source_url:
        return ""
    parsed = urlsplit(source_url)
    return parsed.path.rstrip("/") or (source_url.split("?", 1)[0].rstrip("/"))


def _episode_rename_merge_records(
    state_records: list[Any], metadata_records: list[Any]
) -> list[dict[str, Any]]:
    def normalize(raw: Any, fallback_number: int) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        try:
            declared_number = int(raw.get("number") or 0)
        except (TypeError, ValueError):
            declared_number = 0
        number_inferred = bool(raw.get("numberInferred")) or declared_number <= 0
        number = fallback_number if number_inferred else declared_number
        record = dict(raw)
        record["number"] = number
        if number_inferred:
            record["numberInferred"] = True
        else:
            record.pop("numberInferred", None)
        source_id = _episode_rename_stable_id(record)
        if source_id:
            record["sourceId"] = source_id
        folders = _episode_rename_record_folders(record)
        if folders:
            record["folderName"] = folders[0]
            if len(folders) > 1:
                record["folderHints"] = folders[1:]
        if not folders and not source_id:
            return None
        return record

    primary = [
        record
        for index, item in enumerate(state_records, start=1)
        if (record := normalize(item, index)) is not None
    ]

    def records_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_id = _episode_rename_stable_id(left)
        right_id = _episode_rename_stable_id(right)
        if left_id and right_id:
            return left_id == right_id
        if int(left.get("number") or 0) != int(right.get("number") or 0):
            return False
        left_folders = {
            folder.casefold() for folder in _episode_rename_record_folders(left)
        }
        return any(
            folder.casefold() in left_folders
            for folder in _episode_rename_record_folders(right)
        )

    def combine(
        preferred: dict[str, Any], supplemental: dict[str, Any]
    ) -> dict[str, Any]:
        combined = dict(supplemental)
        combined.update(preferred)
        if preferred.get("numberInferred") and not supplemental.get(
            "numberInferred"
        ):
            combined["number"] = supplemental["number"]
            combined.pop("numberInferred", None)
        for key in ("sourceId", "sourceUrl", "sourceTitle", "displayTitle"):
            if not str(preferred.get(key) or "").strip() and str(
                supplemental.get(key) or ""
            ).strip():
                combined[key] = supplemental[key]
        folders = _episode_rename_record_folders(
            {
                "folderName": preferred.get("folderName")
                or supplemental.get("folderName"),
                "folderHints": [
                    *(
                        preferred.get("folderHints")
                        if isinstance(preferred.get("folderHints"), list)
                        else []
                    ),
                    *_episode_rename_record_folders(supplemental),
                ],
                "displayTitle": preferred.get("displayTitle"),
                "sourceTitle": preferred.get("sourceTitle"),
            }
        )
        if folders:
            combined["folderName"] = folders[0]
            if len(folders) > 1:
                combined["folderHints"] = folders[1:]
            else:
                combined.pop("folderHints", None)
        source_id = _episode_rename_stable_id(combined)
        if source_id:
            combined["sourceId"] = source_id
        return combined

    merged = list(primary)
    for index, raw in enumerate(metadata_records, start=1):
        item = normalize(raw, index)
        if item is None:
            continue
        matching_index = next(
            (
                candidate_index
                for candidate_index, candidate in enumerate(merged)
                if records_match(candidate, item)
            ),
            None,
        )
        if matching_index is None:
            merged.append(item)
        else:
            merged[matching_index] = combine(merged[matching_index], item)
    merged.sort(
        key=lambda item: (
            int(item.get("number") or 0),
            str(item.get("sourceId") or ""),
            str(item.get("folderName") or "").casefold(),
        )
    )
    return merged


def _episode_rename_normalized_text(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFC", str(value or "")),
    ).strip()


def _episode_rename_decode_legacy_entity(match: re.Match[str]) -> str:
    entity = match.group(1)
    if entity.startswith("#"):
        hexadecimal = len(entity) > 1 and entity[1].casefold() == "x"
        digits = entity[2:] if hexadecimal else entity[1:]
        try:
            code_point = int(digits, 16 if hexadecimal else 10)
        except ValueError:
            return match.group(0)
        if (
            code_point <= 0
            or code_point > 0x10FFFF
            or 0xD800 <= code_point <= 0xDFFF
        ):
            return match.group(0)
        return chr(code_point)
    return _LEGACY_EPISODE_HTML_ENTITIES.get(entity.casefold(), match.group(0))


def _episode_rename_legacy_title_text(value: Any) -> str:
    """Match the downloader's conservative v1 ``innerHTML`` normalization."""

    without_tags = _LEGACY_EPISODE_INLINE_HTML_TAG.sub("", str(value or ""))
    return _LEGACY_EPISODE_HTML_ENTITY.sub(
        _episode_rename_decode_legacy_entity,
        without_tags,
    )


def _episode_rename_title_identity(value: Any, number: int = 0) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        _episode_rename_normalized_text(_episode_rename_legacy_title_text(value)),
    )
    if number > 0:
        normalized = re.sub(rf"^0*{number}(?:\s+|$)", "", normalized)
    return unicodedata.normalize(
        "NFKC",
        sanitize_windows_path_segment(normalized, ""),
    ).casefold()


def _episode_rename_titles_match(left: Any, right: Any, number: int = 0) -> bool:
    left_key = _episode_rename_title_identity(left, number)
    right_key = _episode_rename_title_identity(right, number)
    return bool(left_key and right_key and left_key == right_key)


def _episode_rename_safe_text(value: Any) -> str:
    return _episode_rename_normalized_text(
        sanitize_windows_path_segment(_episode_rename_normalized_text(value), "")
    )


def _windows_utf16_units(value: Any) -> int:
    """Return the number of UTF-16 code units Windows uses for a path string."""

    return len(str(value or "").encode("utf-16-le", errors="surrogatepass")) // 2


def _episode_rename_path_policy() -> dict[str, Any]:
    return {
        "encoding": "utf-16",
        "componentMaxUnits": _WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS,
        "destinationMaxUnits": _WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS,
    }


def _episode_rename_overlap(work_title: str, abbreviated_suffix: str) -> int:
    folded_work = work_title.casefold()
    folded_suffix = abbreviated_suffix.casefold()
    for length in range(min(len(folded_work), len(folded_suffix)), 0, -1):
        if folded_work[-length:] == folded_suffix[:length]:
            return length
    return 0


def _episode_rename_repair_known_artifact(value: str, work_title: str) -> str:
    suffix = _episode_rename_normalized_text(value)
    if _episode_rename_safe_text(work_title) != _KNOWN_R18_ARTIFACT_WORK_TITLE:
        return suffix
    matched = re.match(
        r"^(?:-18|18|8)\s+(.+\s\d+(?:\.\d+)?(?:~\d+(?:\.\d+)?)?화)$",
        suffix,
        re.IGNORECASE,
    )
    return f"R-18 {matched.group(1)}" if matched else suffix


def _episode_rename_suffix(
    *titles: str,
    number: int,
    work_title: str,
) -> tuple[str, str]:
    del number  # A storage ordinal is never evidence for the displayed episode suffix.
    safe_work = _episode_rename_safe_text(work_title)
    for title in titles:
        original = _episode_rename_normalized_text(
            _episode_rename_legacy_title_text(title)
        )
        if not original:
            continue
        safe_original = _episode_rename_safe_text(original)
        if not safe_original:
            continue
        if safe_original.casefold() == safe_work.casefold():
            return "", "unnumbered"
        if safe_work and safe_original.casefold().startswith(
            f"{safe_work.casefold()} "
        ):
            suffix = safe_original[len(safe_work) :].strip(" -–—")
            if suffix:
                return suffix, "source_title"
            return "", "unnumbered"

        ellipsis_match = re.search(r"…|\.{3}", original)
        if ellipsis_match:
            left = original[: ellipsis_match.start()].rstrip()
            right = original[ellipsis_match.end() :].lstrip()
            safe_left = _episode_rename_safe_text(left)
            if not right or not (
                not left
                or work_title.casefold().startswith(left.casefold())
                or (safe_left and safe_work.casefold().startswith(safe_left.casefold()))
            ):
                continue
            overlap = _episode_rename_overlap(work_title, right)
            if overlap:
                suffix = right[overlap:].strip(" -–—")
            else:
                safe_right = _episode_rename_safe_text(right)
                safe_overlap = _episode_rename_overlap(safe_work, safe_right)
                suffix = (
                    safe_right[safe_overlap:].strip(" -–—")
                    if safe_overlap
                    else _episode_rename_repair_known_artifact(right, work_title)
                )
            if suffix:
                return suffix, "source_title"
            return "", "unnumbered"

        # This is the same conservative final case used by the downloader:
        # a non-empty source label such as "프롤로그" or "공지" is itself the
        # full suffix.  Never manufacture an N화 label from the storage ordinal.
        return original, "source_title"
    return "", "unsafe"


def _episode_suffix_context_text(value: str) -> str:
    return unicodedata.normalize(
        "NFKC",
        _episode_rename_normalized_text(value),
    ).casefold()


def _episode_suffix_context_token(value: str) -> dict[str, Any] | None:
    """Parse one sortable episode token without treating ranges as parts."""

    suffix = str(value or "")
    if _EPISODE_CONTEXT_RANGE.search(suffix):
        return None
    matches = list(_EPISODE_CONTEXT_TOKEN.finditer(suffix))
    if len(matches) != 1:
        return None
    match = matches[0]
    decimal = str(match.group("decimal") or "")
    hyphen_separator = str(match.group("hyphen_separator") or "")
    variant_digits = str(
        match.group("decimal_digits") or match.group("hyphen_digits") or ""
    )
    kind = "decimal" if decimal else "hyphen" if hyphen_separator else "base"
    return {
        "kind": kind,
        "number": int(match.group("number")),
        "numberText": match.group("number"),
        "part": int(variant_digits) if variant_digits else None,
        "variantDigits": variant_digits,
        "hyphenSeparator": hyphen_separator,
        "unitSpacing": str(match.group("unit_spacing") or ""),
        "start": match.start(),
        "end": match.end(),
        "prefix": suffix[: match.start()],
        "tail": suffix[match.end() :],
        "context": (
            int(match.group("number")),
            _episode_suffix_context_text(suffix[: match.start()]),
            _episode_suffix_context_text(suffix[match.end() :]),
        ),
    }


def _plan_contextual_episode_suffixes(suffixes: list[str]) -> list[dict[str, Any]]:
    """Plan only the disambiguating rename needed by sibling episode labels."""

    parsed = [_episode_suffix_context_token(value) for value in suffixes]
    siblings: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
    for item in parsed:
        if item is not None:
            siblings.setdefault(item["context"], []).append(item)

    decisions: list[dict[str, Any]] = []
    for suffix, item in zip(suffixes, parsed, strict=True):
        decision = {
            "suffix": suffix,
            "applied": False,
            "reason": "",
            "conflict": False,
            "conflictCode": "",
            "conflictReason": "",
        }
        if item is None or item["kind"] != "base":
            decisions.append(decision)
            continue

        related = siblings.get(item["context"], [])
        bases = [candidate for candidate in related if candidate["kind"] == "base"]
        decimals = [
            candidate for candidate in related if candidate["kind"] == "decimal"
        ]
        hyphen_ones = [
            candidate
            for candidate in related
            if candidate["kind"] == "hyphen" and candidate["variantDigits"] == "1"
        ]
        hyphen_twos = [
            candidate
            for candidate in related
            if candidate["kind"] == "hyphen" and candidate["variantDigits"] == "2"
        ]
        if not decimals and not hyphen_twos:
            decisions.append(decision)
            continue
        if len(bases) != 1:
            decision.update(
                {
                    "conflict": True,
                    "conflictCode": "duplicate_base_episode",
                    "conflictReason": (
                        "같은 문맥의 기본 회차가 둘 이상 있어 안전하게 변경할 수 없습니다."
                    ),
                }
            )
            decisions.append(decision)
            continue
        if any(
            re.fullmatch(r"0+", candidate["variantDigits"]) is not None
            for candidate in decimals
        ):
            decision.update(
                {
                    "conflict": True,
                    "conflictCode": "decimal_zero_already_exists",
                    "conflictReason": (
                        "같은 문맥의 소수점 0 회차가 이미 있어 기본 회차를 "
                        "안전하게 변경할 수 없습니다."
                    ),
                }
            )
            decisions.append(decision)
            continue
        replacements: list[tuple[str, str]] = []
        if decimals:
            replacements.append(
                (
                    f"{item['numberText']}.0{item['unitSpacing']}화",
                    "decimal_sibling",
                )
            )
        if hyphen_twos and hyphen_ones:
            decision.update(
                {
                    "conflict": True,
                    "conflictCode": "hyphen_part_one_already_exists",
                    "conflictReason": (
                        "같은 문맥의 -1 회차가 이미 있어 기본 회차를 "
                        "-1 회차로 안전하게 변경할 수 없습니다."
                    ),
                }
            )
            decisions.append(decision)
            continue
        if decimals and hyphen_twos:
            decision.update(
                {
                    "conflict": True,
                    "conflictCode": "mixed_decimal_hyphen_siblings",
                    "conflictReason": (
                        "같은 문맥에 소수 회차와 -2 회차가 함께 있어 "
                        "기본 회차명을 안전하게 결정할 수 없습니다."
                    ),
                }
            )
            decisions.append(decision)
            continue
        if hyphen_twos:
            separators = {
                candidate["hyphenSeparator"] for candidate in hyphen_twos
            }
            if len(separators) != 1:
                decision.update(
                    {
                        "conflict": True,
                        "conflictCode": "ambiguous_hyphen_style",
                        "conflictReason": (
                            "같은 문맥의 -2 회차 구분자 형식이 서로 달라 "
                            "기본 회차명을 안전하게 결정할 수 없습니다."
                        ),
                    }
                )
                decisions.append(decision)
                continue
            separator = next(iter(separators))
            replacements.append(
                (
                    f"{item['numberText']}{separator}1{item['unitSpacing']}화",
                    "hyphen_part_sibling",
                )
            )
        distinct_replacements = {replacement for replacement, _reason in replacements}
        if len(distinct_replacements) > 1:
            decision.update(
                {
                    "conflict": True,
                    "conflictCode": "mixed_decimal_hyphen_siblings",
                    "conflictReason": (
                        "같은 문맥에 소수 회차와 -2 회차가 함께 있어 "
                        "기본 회차명을 안전하게 결정할 수 없습니다."
                    ),
                }
            )
        elif replacements:
            replacement, reason = replacements[0]
            decision.update(
                {
                    "suffix": (
                        f"{suffix[:item['start']]}{replacement}{suffix[item['end'] :]}"
                    ),
                    "applied": True,
                    "reason": reason,
                }
            )
        decisions.append(decision)
    return decisions


def _episode_rename_work_title(
    job: DownloadJob | EpisodeRenameJobSnapshot,
    metadata: dict[str, Any],
    output_path: Path,
) -> str:
    folder_match = re.match(r"^\[[^]]*\]\[[^]]*\]\s*(.+)$", output_path.name)
    candidates = (
        metadata.get("title"),
        job.title,
        folder_match.group(1) if folder_match else output_path.name,
    )
    placeholders = {"", "메타데이터 확인 중", "제목 없음"}
    truncated_candidates: list[str] = []
    for candidate in candidates:
        clean = sanitize_windows_path_segment(candidate, "").strip()
        if clean in placeholders:
            continue
        if "…" in clean or "..." in clean:
            truncated_candidates.append(clean)
            continue
        return clean
    if truncated_candidates:
        raise ValueError(
            "줄임표가 없는 전체 작품 제목을 metadata.json 또는 작업 기록에서 찾을 수 없습니다."
        )
    raise ValueError("회차 폴더에 사용할 전체 작품 제목을 찾을 수 없습니다.")


def _episode_rename_backup_candidate(path: Path) -> Path:
    base = path.with_name(path.name + ".pre-episode-rename.bak")
    if not base.exists():
        return base
    for index in range(2, 1000):
        candidate = path.with_name(
            path.name + f".pre-episode-rename.{index}.bak"
        )
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"백업 파일 이름을 만들 수 없습니다: {path}")


def _episode_rename_recovery_info(output_path: Path) -> dict[str, Any]:
    temporary_folders: list[str] = []
    transaction_files: list[dict[str, Any]] = []
    unknown_artifacts: list[str] = []
    with os.scandir(output_path) as output_entries_scan:
        output_entries = list(output_entries_scan)
    for entry in output_entries:
        if not entry.name.startswith(_EPISODE_RENAME_ARTIFACT_PREFIX):
            continue
        path = Path(entry.path).resolve()
        if entry.is_dir(follow_symlinks=False):
            temporary_folders.append(str(path))
            continue
        if not entry.is_file(follow_symlinks=False):
            continue
        matched = _EPISODE_RENAME_TRANSACTION.fullmatch(entry.name)
        if not matched:
            unknown_artifacts.append(str(path))
            continue
        detail: dict[str, Any] = {
            "path": str(path),
            "token": matched.group(1),
            "valid": False,
            "status": "unknown",
            "entries": [],
        }
        try:
            payload = _episode_rename_json(path, label="회차 폴더 복구 기록")
            raw_entries = payload.get("entries", [])
            if not isinstance(raw_entries, list):
                raise ValueError("entries가 배열이 아닙니다.")
            locations: list[dict[str, Any]] = []
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                source_text = str(item.get("source") or "").strip()
                temporary_text = str(item.get("temporary") or "").strip()
                target_text = str(item.get("target") or "").strip()
                locations.append(
                    {
                        "source": source_text,
                        "temporary": temporary_text,
                        "target": target_text,
                        "sourceExists": bool(
                            source_text and Path(source_text).is_dir()
                        ),
                        "temporaryExists": bool(
                            temporary_text and Path(temporary_text).is_dir()
                        ),
                        "targetExists": bool(
                            target_text and Path(target_text).is_dir()
                        ),
                    }
                )
            rollback_errors = payload.get("rollbackErrors", [])
            if not isinstance(rollback_errors, list):
                rollback_errors = [str(rollback_errors)]
            detail.update(
                {
                    "valid": True,
                    "status": str(payload.get("status") or "unknown"),
                    "createdAt": str(payload.get("createdAt") or ""),
                    "updatedAt": str(payload.get("updatedAt") or ""),
                    "rollbackErrors": [str(item) for item in rollback_errors],
                    "entries": locations,
                }
            )
        except (OSError, ValueError) as error:
            detail["error"] = str(error)
        transaction_files.append(detail)

    temporary_folders.sort(key=str.casefold)
    transaction_files.sort(key=lambda item: str(item["path"]).casefold())
    unknown_artifacts.sort(key=str.casefold)
    required = bool(temporary_folders or transaction_files or unknown_artifacts)
    return {
        "required": required,
        "message": (
            "이전 회차 폴더명 변경의 복구 자료가 남아 있습니다. "
            "표시된 원본·임시·대상 경로를 확인하고 복구하기 전에는 다시 실행할 수 없습니다."
            if required
            else ""
        ),
        "temporaryFolders": temporary_folders,
        "transactionFiles": transaction_files,
        "unknownArtifacts": unknown_artifacts,
        "artifactCount": (
            len(temporary_folders)
            + len(transaction_files)
            + len(unknown_artifacts)
        ),
    }


def _episode_rename_has_legacy_image(folder: Path) -> bool:
    """Return whether a heuristic folder contains an old downloader image name."""

    try:
        with os.scandir(folder) as children:
            return any(
                child.is_file(follow_symlinks=False)
                and _LEGACY_EPISODE_IMAGE_FILE.search(child.name) is not None
                for child in children
            )
    except OSError:
        return False


def plan_episode_folder_rename(
    job_id: str,
    *,
    job_snapshot: EpisodeRenameJobSnapshot | DownloadJob | None = None,
    ordered: bool = True,
) -> dict[str, Any]:
    """Plan a non-destructive legacy episode-folder naming migration.

    The legacy leading ordinal remains the stable episode number in state.  Only
    the directory name changes; ordered mode prefixes a six-digit reading ordinal.
    """

    job = _episode_rename_resolve_job(job_id, job_snapshot)
    if job.state in ACTIVE_JOB_STATES:
        raise ValueError("대기 또는 실행 중인 작품의 회차 폴더명은 변경할 수 없습니다.")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")

    state_path = output_path / ".toki-state.json"
    metadata_path = output_path / "metadata.json"
    state = _episode_rename_json(state_path, label="완료 회차 상태 파일")
    metadata = _episode_rename_json(metadata_path, label="metadata.json")
    work_title = _episode_rename_work_title(job, metadata, output_path)

    state_records = state.get("episodes", [])
    if not isinstance(state_records, list):
        raise ValueError("완료 회차 상태의 episodes는 배열이어야 합니다.")
    metadata_records = metadata.get("episodes", [])
    if not isinstance(metadata_records, list):
        raise ValueError("metadata.json의 episodes는 배열이어야 합니다.")
    existing_records = _episode_rename_merge_records(
        state_records,
        metadata_records,
    )
    records_by_number: dict[int, list[dict[str, Any]]] = {}
    for item in existing_records:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if number > 0:
            records_by_number.setdefault(number, []).append(item)

    recovery = _episode_rename_recovery_info(output_path)
    if recovery["required"]:
        return {
            "jobId": job.job_id,
            "workKey": job.work_key,
            "title": work_title,
            "outputPath": str(output_path),
            "mode": "title_suffix",
            "dryRun": True,
            "executed": False,
            "folderCount": 0,
            "renameCount": 0,
            "unchangedCount": 0,
            "fallbackSuffixCount": 0,
            "unsafeSuffixCount": 0,
            "duplicateNumbers": [],
            "conflictCount": 1,
            "conflicts": [
                {
                    "type": "recovery_required",
                    "message": recovery["message"],
                    "artifactCount": recovery["artifactCount"],
                }
            ],
            "canExecute": False,
            "recoveryRequired": True,
            "recovery": recovery,
            "mappings": [],
            "episodes": [
                dict(item) for item in existing_records if isinstance(item, dict)
            ],
            "stateVersion": 2,
            "statePath": str(state_path),
            "stateExists": state_path.is_file(),
            "stateBackupPath": str(_episode_rename_backup_candidate(state_path)),
            "metadataPath": str(metadata_path),
            "metadataExists": metadata_path.is_file(),
            "metadataBackupPath": str(
                _episode_rename_backup_candidate(metadata_path)
            ),
            "pathPolicy": _episode_rename_path_policy(),
            "manifestValid": False,
        }

    sources: list[tuple[int, Path, str, bool]] = []
    known_sources: set[str] = set()
    # State v2 is authoritative and must be consulted before the legacy-name
    # heuristic.  An already migrated title is allowed to begin with digits.
    for number, records in records_by_number.items():
        for record in records:
            for folder_name in _episode_rename_record_folders(record):
                source = (output_path / folder_name).resolve()
                source_key = os.path.normcase(str(source))
                if source_key in known_sources or not source.is_dir():
                    continue
                try:
                    source.relative_to(output_path)
                except ValueError:
                    continue
                matched = _LEGACY_EPISODE_FOLDER.match(source.name)
                legacy_title = (
                    matched.group(2).strip()
                    if matched
                    else str(record.get("sourceTitle") or source.name).strip()
                )
                sources.append((number, source, legacy_title, False))
                known_sources.add(source_key)
                break

    with os.scandir(output_path) as output_entries_scan:
        output_entries = list(output_entries_scan)
    for entry in output_entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        source = Path(entry.path).resolve()
        source_key = os.path.normcase(str(source))
        if source_key in known_sources:
            continue
        matched = _LEGACY_EPISODE_FOLDER.match(entry.name)
        if not matched:
            continue
        number = int(matched.group(1))
        if number <= 0 or not _episode_rename_has_legacy_image(source):
            continue
        sources.append((number, source, matched.group(2).strip(), True))
        known_sources.add(source_key)

    if not sources:
        raise FileNotFoundError("이름을 변경할 회차 폴더를 찾을 수 없습니다.")
    sources.sort(key=lambda item: (item[0], item[1].name.casefold()))

    mappings: list[dict[str, Any]] = []
    represented_records: set[int] = set()
    target_counts: dict[str, int] = {}
    number_counts: dict[int, int] = {}
    unsafe_count = 0
    for number, source, legacy_title, heuristic_legacy in sources:
        matching_records = records_by_number.get(number, [])
        exact_record = next(
            (
                item
                for item in matching_records
                if source.name.casefold()
                in {
                    folder.casefold()
                    for folder in _episode_rename_record_folders(item)
                }
            ),
            None,
        )
        identity_matches = [
            item
            for item in matching_records
            if any(
                _episode_rename_titles_match(legacy_title, candidate, number)
                for candidate in (
                    item.get("sourceTitle"),
                    item.get("displayTitle"),
                    *_episode_rename_record_folders(item),
                )
            )
        ]
        record = exact_record or (
            identity_matches[0] if len(identity_matches) == 1 else {}
        )
        identity_trusted = bool(record)
        source_title = str(record.get("sourceTitle") or legacy_title).strip()
        suffix, suffix_source = _episode_rename_suffix(
            source_title,
            legacy_title,
            number=number,
            work_title=work_title,
        )
        # Only ordered naming can safely represent an empty suffix. The legacy
        # title-only migration must still refuse to collapse separate chapters.
        unsafe_suffix = suffix_source == "unsafe" or (
            not suffix and not (ordered and suffix_source == "unnumbered")
        )
        if unsafe_suffix:
            unsafe_count += 1
        display_title = (
            sanitize_windows_path_segment(f"{work_title} {suffix}", "회차")
            if not unsafe_suffix
            else ""
        )
        if "…" in display_title or "..." in display_title:
            unsafe_suffix = True
            unsafe_count += int(suffix_source != "unsafe")
            suffix_source = "unsafe"
            display_title = ""
        if not record and display_title and matching_records:
            identity_matches = [
                item
                for item in matching_records
                if display_title.casefold()
                in {
                    folder.casefold()
                    for folder in _episode_rename_record_folders(item)
                }
            ]
            if len(identity_matches) == 1:
                record = identity_matches[0]
                identity_trusted = True
                source_title = str(
                    record.get("sourceTitle") or source_title
                ).strip()
        if record:
            represented_records.add(id(record))
        folder_name = ordered_episode_folder_name(number, display_title) if ordered and display_title else display_title
        target = (output_path / folder_name).resolve() if folder_name else None
        if target is not None:
            try:
                target.relative_to(output_path)
            except ValueError as error:
                raise ValueError("회차 폴더명이 작품 폴더 밖을 가리킵니다.") from error
        same_path = bool(
            target is not None
            and os.path.normcase(str(source)) == os.path.normcase(str(target))
        )
        component_utf16_units = _windows_utf16_units(folder_name)
        destination_utf16_units = _windows_utf16_units(target) if target else 0
        component_too_long = (
            component_utf16_units
            > _WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS
        )
        absolute_path_too_long = (
            destination_utf16_units > _WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS
        )
        if target is not None:
            target_key = os.path.normcase(str(target))
            target_counts[target_key] = target_counts.get(target_key, 0) + 1
        if heuristic_legacy:
            number_counts[number] = number_counts.get(number, 0) + 1
        mappings.append(
            {
                "number": number,
                "sourceId": str(record.get("sourceId") or ""),
                "sourceUrl": str(record.get("sourceUrl") or ""),
                "sourceTitle": source_title,
                "displayTitle": display_title,
                "folderName": folder_name,
                "source": str(source),
                "destination": str(target) if target is not None else "",
                "sourceFolderName": source.name,
                "destinationFolderName": folder_name,
                "suffix": suffix,
                "suffixSource": suffix_source,
                "sourceDiscovery": "legacy_prefix" if heuristic_legacy else "state",
                "identityTrusted": identity_trusted,
                "numberInferred": bool(record.get("numberInferred"))
                and not heuristic_legacy,
                "unsafeSuffix": unsafe_suffix,
                "unsafeReason": (
                    "원본 회차 제목에서 신뢰할 수 있는 회차 접미사를 찾지 못했습니다."
                    if unsafe_suffix
                    else ""
                ),
                "samePath": same_path,
                "componentUtf16Units": component_utf16_units,
                "destinationUtf16Units": destination_utf16_units,
                "componentTooLong": component_too_long,
                "absolutePathTooLong": absolute_path_too_long,
                "pathTooLong": (
                    not same_path and (component_too_long or absolute_path_too_long)
                ),
                "conflict": bool(target is not None and target.exists() and not same_path),
            }
        )

    # A range-only download still belongs to the full episode catalog. Include
    # absent siblings, but never count a mapped catalog record twice.
    contextual_suffixes = [
        "" if mapping["unsafeSuffix"] else str(mapping["suffix"])
        for mapping in mappings
    ]
    for records in records_by_number.values():
        for record in records:
            if id(record) in represented_records:
                continue
            suffix, source = _episode_rename_suffix(
                str(record.get("sourceTitle") or record.get("displayTitle") or ""),
                number=record["number"],
                work_title=work_title,
            )
            if source != "unsafe":
                contextual_suffixes.append(suffix)
    contextual_decisions = _plan_contextual_episode_suffixes(
        contextual_suffixes
    )[:len(mappings)]
    target_counts = {}
    unsafe_count = 0
    for mapping, decision in zip(mappings, contextual_decisions, strict=True):
        unsafe_suffix = bool(mapping["unsafeSuffix"] or decision["conflict"])
        suffix = str(decision["suffix"])
        unsafe_reason = str(mapping["unsafeReason"])
        if decision["conflict"]:
            unsafe_reason = str(decision["conflictReason"])
        display_title = (
            sanitize_windows_path_segment(f"{work_title} {suffix}", "회차")
            if not unsafe_suffix
            else ""
        )
        folder_name = ordered_episode_folder_name(mapping["number"], display_title) if ordered and display_title else display_title
        target = (output_path / folder_name).resolve() if folder_name else None
        if target is not None:
            try:
                target.relative_to(output_path)
            except ValueError as error:
                raise ValueError("회차 폴더명이 작품 폴더 밖을 가리킵니다.") from error
        source = Path(mapping["source"])
        same_path = bool(
            target is not None
            and os.path.normcase(str(source)) == os.path.normcase(str(target))
        )
        component_utf16_units = _windows_utf16_units(folder_name)
        destination_utf16_units = _windows_utf16_units(target) if target else 0
        component_too_long = (
            component_utf16_units
            > _WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS
        )
        absolute_path_too_long = (
            destination_utf16_units > _WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS
        )
        if target is not None:
            target_key = os.path.normcase(str(target))
            target_counts[target_key] = target_counts.get(target_key, 0) + 1
        if unsafe_suffix:
            unsafe_count += 1
        mapping.update(
            {
                "displayTitle": display_title,
                "folderName": folder_name,
                "destination": str(target) if target is not None else "",
                "destinationFolderName": folder_name,
                "suffix": suffix,
                "contextualSuffixApplied": bool(decision["applied"]),
                "contextualSuffixReason": str(decision["reason"]),
                "contextualSuffixConflict": bool(decision["conflict"]),
                "contextualSuffixConflictCode": str(decision["conflictCode"]),
                "unsafeSuffix": unsafe_suffix,
                "unsafeReason": unsafe_reason,
                "samePath": same_path,
                "componentUtf16Units": component_utf16_units,
                "destinationUtf16Units": destination_utf16_units,
                "componentTooLong": component_too_long,
                "absolutePathTooLong": absolute_path_too_long,
                "pathTooLong": (
                    not same_path and (component_too_long or absolute_path_too_long)
                ),
                "conflict": bool(
                    target is not None and target.exists() and not same_path
                ),
            }
        )

    duplicate_targets = {
        target for target, count in target_counts.items() if count > 1
    }
    duplicate_numbers = sorted(
        number for number, count in number_counts.items() if count > 1
    )
    for mapping in mappings:
        mapping["duplicateTarget"] = (
            bool(mapping["destination"])
            and os.path.normcase(mapping["destination"]) in duplicate_targets
        )

    def conflict_type(mapping: dict[str, Any]) -> str:
        if mapping.get("contextualSuffixConflict"):
            return "contextual_suffix_conflict"
        if mapping["unsafeSuffix"]:
            return "unsafe_suffix"
        if mapping["duplicateTarget"]:
            return "duplicate_target"
        if mapping["pathTooLong"]:
            return "path_too_long"
        return "path_conflict"

    def conflict_message(mapping: dict[str, Any]) -> str:
        if mapping["unsafeSuffix"]:
            return str(mapping["unsafeReason"])
        if mapping["duplicateTarget"]:
            return "둘 이상의 회차가 같은 목적지 폴더명을 사용합니다."
        if mapping["componentTooLong"]:
            return (
                "회차 폴더명이 Windows 안전 길이를 초과합니다: "
                f"{mapping['componentUtf16Units']} UTF-16 units"
            )
        if mapping["absolutePathTooLong"]:
            return (
                "전체 목적지 경로가 Windows 안전 길이를 초과합니다: "
                f"{mapping['destinationUtf16Units']} UTF-16 units"
            )
        return "목적지 폴더가 이미 존재합니다."

    conflicts = [
        {
            "type": conflict_type(mapping),
            "number": mapping["number"],
            "source": mapping["source"],
            "destination": mapping["destination"],
            "existingDestination": mapping["conflict"],
            "duplicateTarget": mapping["duplicateTarget"],
            "pathTooLong": mapping["pathTooLong"],
            "componentTooLong": mapping["componentTooLong"],
            "absolutePathTooLong": mapping["absolutePathTooLong"],
            "componentUtf16Units": mapping["componentUtf16Units"],
            "destinationUtf16Units": mapping["destinationUtf16Units"],
            "unsafeSuffix": mapping["unsafeSuffix"],
            "contextualSuffixConflict": mapping.get(
                "contextualSuffixConflict", False
            ),
            "contextualSuffixConflictCode": mapping.get(
                "contextualSuffixConflictCode", ""
            ),
            "message": conflict_message(mapping),
        }
        for mapping in mappings
        if mapping["conflict"]
        or mapping["duplicateTarget"]
        or mapping["pathTooLong"]
        or mapping["unsafeSuffix"]
    ]

    mapped_folder_names = {
        str(mapping["sourceFolderName"]).casefold()
        for mapping in mappings
        if not mapping["unsafeSuffix"]
    }
    mapped_source_ids = {
        str(mapping["sourceId"])
        for mapping in mappings
        if not mapping["unsafeSuffix"] and mapping["sourceId"]
    }
    episodes: list[dict[str, Any]] = []
    for item in existing_records:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("number") or 0)
        except (TypeError, ValueError):
            continue
        folder_names = {
            folder.casefold() for folder in _episode_rename_record_folders(item)
        }
        source_id = str(item.get("sourceId") or "")
        if number <= 0 or folder_names.intersection(mapped_folder_names) or (
            source_id and source_id in mapped_source_ids
        ):
            continue
        episodes.append(dict(item))
    episodes.extend(
        {
            "number": mapping["number"],
            **(
                {"numberInferred": True}
                if mapping.get("numberInferred")
                else {}
            ),
            "sourceId": mapping["sourceId"],
            "sourceUrl": mapping["sourceUrl"],
            "sourceTitle": mapping["sourceTitle"],
            "displayTitle": mapping["displayTitle"],
            "folderName": mapping["folderName"],
        }
        for mapping in mappings
        if not mapping["unsafeSuffix"]
    )
    episodes = [
        {
            "number": int(item.get("number") or 0),
            **({"numberInferred": True} if item.get("numberInferred") else {}),
            "sourceId": _episode_rename_stable_id(item),
            "sourceUrl": str(item.get("sourceUrl") or ""),
            "sourceTitle": str(item.get("sourceTitle") or ""),
            "displayTitle": str(
                item.get("displayTitle")
                or item.get("folderName")
                or item.get("sourceTitle")
                or ""
            ),
            "folderName": str(
                next(iter(_episode_rename_record_folders(item)), "")
            ),
        }
        for item in episodes
        if int(item.get("number") or 0) > 0
    ]
    episodes.sort(
        key=lambda item: (
            int(item.get("number") or 0),
            str(item.get("sourceId") or ""),
            str(item.get("folderName") or "").casefold(),
        )
    )
    _parsed_episodes, manifest_valid = _parse_episode_manifest_entries(episodes)
    if not manifest_valid:
        conflicts.append(
            {
                "type": "manifest_invalid",
                "number": 0,
                "source": "",
                "destination": "",
                "existingDestination": False,
                "duplicateTarget": False,
                "pathTooLong": False,
                "componentTooLong": False,
                "absolutePathTooLong": False,
                "componentUtf16Units": 0,
                "destinationUtf16Units": 0,
                "unsafeSuffix": False,
                "message": (
                    "이름 변경 뒤 회차 manifest의 ID 또는 폴더명이 중복되거나 "
                    "필수 필드가 비어 있어 실행할 수 없습니다."
                ),
            }
        )

    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": work_title,
        "outputPath": str(output_path),
        "mode": "ordered_title" if ordered else "title_suffix",
        "dryRun": True,
        "executed": False,
        "folderCount": len(mappings),
        "renameCount": sum(
            not item["samePath"] and not item["unsafeSuffix"] for item in mappings
        ),
        "unchangedCount": sum(bool(item["samePath"]) for item in mappings),
        "fallbackSuffixCount": 0,
        "unsafeSuffixCount": unsafe_count,
        "duplicateNumbers": duplicate_numbers,
        "conflictCount": len(conflicts),
        "conflicts": conflicts,
        "canExecute": not conflicts and not duplicate_numbers,
        "recoveryRequired": False,
        "recovery": recovery,
        "mappings": mappings,
        "episodes": episodes,
        "stateVersion": 2,
        "statePath": str(state_path),
        "stateExists": state_path.is_file(),
        "stateBackupPath": str(_episode_rename_backup_candidate(state_path)),
        "metadataPath": str(metadata_path),
        "metadataExists": metadata_path.is_file(),
        "metadataBackupPath": str(_episode_rename_backup_candidate(metadata_path)),
        "pathPolicy": _episode_rename_path_policy(),
        "manifestValid": manifest_valid,
    }


def _write_episode_rename_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".episode-rename.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def ordered_episode_folder_name(number: int, display_title: str) -> str:
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 999999:
        raise ValueError("정렬용 회차 순번은 1~999999 정수여야 합니다.")
    return f"{number:06d} {sanitize_windows_path_segment(display_title, '회차')}"


def rename_episode_folders(job_id: str, *, ordered: bool = True) -> dict[str, Any]:
    plan = plan_episode_folder_rename(job_id, ordered=ordered)
    if not plan["canExecute"]:
        if plan.get("recoveryRequired"):
            raise RuntimeError(str(plan["recovery"]["message"]))
        if plan.get("unsafeSuffixCount"):
            raise ValueError(
                "원본 제목에서 신뢰할 수 있는 회차 접미사를 찾지 못한 폴더가 있습니다."
            )
        if plan["duplicateNumbers"]:
            joined = ", ".join(str(value) for value in plan["duplicateNumbers"])
            raise FileExistsError(f"중복 회차 번호 폴더가 있습니다: {joined}")
        first = plan["conflicts"][0]
        if first.get("type") == "manifest_invalid":
            raise ValueError(str(first.get("message") or "회차 manifest가 올바르지 않습니다."))
        raise FileExistsError(f"회차 폴더 이름 충돌이 있습니다: {first['destination']}")

    state_path = Path(plan["statePath"])
    metadata_path = Path(plan["metadataPath"])
    state_existed = state_path.is_file()
    metadata_existed = metadata_path.is_file()
    state = _episode_rename_json(state_path, label="완료 회차 상태 파일")
    metadata = _episode_rename_json(metadata_path, label="metadata.json")
    state_backup = _episode_rename_backup_candidate(state_path)
    metadata_backup = _episode_rename_backup_candidate(metadata_path)
    if state_existed:
        shutil.copy2(state_path, state_backup)
    if metadata_existed:
        shutil.copy2(metadata_path, metadata_backup)

    # ZIP bytes stay untouched, but their external-folder/source references must
    # follow the migration so verification and later archive cleanup still agree.
    from toki_archive_catalog import remap_archive_catalog
    archive_index_path = Path(plan["outputPath"]) / "_archives/.toki-archive-index.json"
    archive_index = remap_archive_catalog(Path(plan["outputPath"]), plan["mappings"])
    archive_index_backup = _episode_rename_backup_candidate(archive_index_path) if archive_index is not None else None
    if archive_index_backup:
        shutil.copy2(archive_index_path, archive_index_backup)

    token = uuid.uuid4().hex
    entries: list[dict[str, Path]] = []
    for index, mapping in enumerate(plan["mappings"], start=1):
        if mapping["samePath"]:
            continue
        source = Path(mapping["source"])
        target = Path(mapping["destination"])
        temporary = Path(plan["outputPath"]) / (
            f".toki-episode-rename-{token}-{index:04d}"
        )
        if temporary.exists():
            raise FileExistsError(f"임시 회차 폴더가 이미 존재합니다: {temporary}")
        entries.append({"source": source, "temporary": temporary, "target": target})

    transaction_path = Path(plan["outputPath"]) / (
        f".toki-episode-rename-{token}.json"
    )
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    transaction: dict[str, Any] = {
        "version": 1,
        "jobId": job_id,
        "token": token,
        "status": "prepared",
        "createdAt": now,
        "updatedAt": now,
        "entries": [
            {key: str(value) for key, value in entry.items()} for entry in entries
        ],
        "rollbackErrors": [],
        "archiveIndexBackupPath": str(archive_index_backup or ""),
    }
    _write_episode_rename_json(transaction_path, transaction)

    def update_transaction(status: str, rollback_errors: list[str] | None = None) -> None:
        transaction["status"] = status
        transaction["updatedAt"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        if rollback_errors is not None:
            transaction["rollbackErrors"] = list(rollback_errors)
        _write_episode_rename_json(transaction_path, transaction)

    current_locations: dict[str, Path] = {
        os.path.normcase(str(entry["source"])): entry["source"] for entry in entries
    }
    try:
        for entry in entries:
            os.replace(entry["source"], entry["temporary"])
            current_locations[os.path.normcase(str(entry["source"]))] = entry[
                "temporary"
            ]
        update_transaction("temporary")
        for entry in entries:
            if entry["target"].exists():
                raise FileExistsError(
                    f"회차 폴더 이름 변경 중 목적지가 생성되었습니다: {entry['target']}"
                )
            os.replace(entry["temporary"], entry["target"])
            current_locations[os.path.normcase(str(entry["source"]))] = entry["target"]
        update_transaction("renamed")

        completed = state.get("completedEpisodes")
        if isinstance(completed, list):
            completed_episodes = sorted(
                {
                    int(value)
                    for value in completed
                    if str(value).isdigit() and int(value) > 0
                }
            )
        else:
            # A folder can be left behind by an interrupted/partial download.
            # Without an explicit completion list, migration must not invent one.
            completed_episodes = []
        existing_completed_ids = state.get("completedEpisodeIds")
        completed_episode_ids = {
            str(value).strip()
            for value in (
                existing_completed_ids
                if isinstance(existing_completed_ids, list)
                else []
            )
            if str(value).strip()
        }
        try:
            source_state_version = int(
                state.get("version", 1 if state_existed else 0)
            )
        except (TypeError, ValueError):
            source_state_version = 0
        if (
            state_existed
            and source_state_version <= 1
            and isinstance(completed, list)
        ):
            mappings_by_number: dict[int, list[dict[str, Any]]] = {}
            for mapping in plan["mappings"]:
                mappings_by_number.setdefault(int(mapping["number"]), []).append(mapping)
            for number in completed_episodes:
                candidates = mappings_by_number.get(number, [])
                if len(candidates) != 1:
                    continue
                candidate = candidates[0]
                source_id = str(candidate.get("sourceId") or "").strip()
                if source_id and bool(candidate.get("identityTrusted")):
                    completed_episode_ids.add(source_id)
        state.update(
            {
                "version": 2,
                "completedEpisodes": completed_episodes,
                "completedEpisodeIds": sorted(completed_episode_ids),
                "episodes": plan["episodes"],
                "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
        )
        metadata["episodes"] = plan["episodes"]
        metadata["episodeFolderNaming"] = {
            "version": 2 if ordered else 1,
            "mode": plan["mode"],
            "prefixDigits": 6 if ordered else 0,
            "title": plan["title"],
            "updatedAt": state["updatedAt"],
        }
        _write_episode_rename_json(state_path, state)
        _write_episode_rename_json(metadata_path, metadata)
        if archive_index is not None:
            _write_episode_rename_json(archive_index_path, archive_index)
        transaction_path.unlink(missing_ok=True)
    except Exception as error:
        rollback_errors: list[str] = []
        for entry in reversed(entries):
            source_key = os.path.normcase(str(entry["source"]))
            current = current_locations[source_key]
            try:
                if current.exists() and not entry["source"].exists():
                    os.replace(current, entry["source"])
            except OSError as rollback_error:
                rollback_errors.append(f"{current} -> {entry['source']}: {rollback_error}")
        for entry in entries:
            source_key = os.path.normcase(str(entry["source"]))
            current = current_locations[source_key]
            if not entry["source"].is_dir():
                rollback_errors.append(f"원본 폴더가 복구되지 않음: {entry['source']}")
            if current != entry["source"] and current.exists():
                rollback_errors.append(f"변경 중 폴더가 남아 있음: {current}")
        try:
            if state_existed and state_backup.is_file():
                shutil.copy2(state_backup, state_path)
            elif not state_existed and state_path.exists():
                state_path.unlink()
        except OSError as rollback_error:
            rollback_errors.append(f"완료 회차 상태 파일 복구: {rollback_error}")
        try:
            if metadata_existed and metadata_backup.is_file():
                shutil.copy2(metadata_backup, metadata_path)
            elif not metadata_existed and metadata_path.exists():
                metadata_path.unlink()
        except OSError as rollback_error:
            rollback_errors.append(f"metadata.json 복구: {rollback_error}")
        try:
            if archive_index_backup and archive_index_backup.is_file():
                shutil.copy2(archive_index_backup, archive_index_path)
        except OSError as rollback_error:
            rollback_errors.append(f"ZIP 카탈로그 복구: {rollback_error}")
        if not rollback_errors:
            try:
                transaction_path.unlink(missing_ok=True)
            except OSError as rollback_error:
                rollback_errors.append(f"복구 기록 정리: {rollback_error}")
        if rollback_errors:
            try:
                update_transaction("rollback_failed", rollback_errors)
            except OSError as marker_error:
                rollback_errors.append(f"복구 기록 갱신: {marker_error}")
            raise RuntimeError(
                "회차 폴더명 변경과 원위치 복구가 모두 실패했습니다: "
                + "; ".join(rollback_errors)
            ) from error
        raise

    return {
        **plan,
        "dryRun": False,
        "executed": True,
        "renamedCount": len(entries),
        "stateBackupPath": str(state_backup) if state_existed else "",
        "stateBackupCreated": state_existed and state_backup.is_file(),
        "metadataBackupPath": str(metadata_backup) if metadata_existed else "",
        "metadataBackupCreated": metadata_existed and metadata_backup.is_file(),
        "archiveIndexBackupPath": str(archive_index_backup or ""),
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

    discovered_episodes = discover_episode_folders(output_path)
    discovered_names = {episode.folder_name for episode in discovered_episodes}
    for item in archived_episodes(output_path):
        if item["folderName"] not in discovered_names:
            discovered_episodes.append(EpisodeFolderEntry(
                number=int(item["number"]), path=Path(item["archivePath"]), folder_name=item["folderName"],
                source_id=item.get("sourceId", ""), source_title=item.get("sourceTitle", ""),
                display_title=item["folderName"], discovery="archive",
            ))
    rebuilt_episodes = [
        {
            "number": episode.number,
            **({"numberInferred": True} if episode.number_inferred else {}),
            "sourceId": episode.source_id,
            "sourceUrl": episode.source_url,
            "sourceTitle": episode.source_title or episode.folder_name,
            "displayTitle": episode.display_title or episode.folder_name,
            "folderName": episode.folder_name,
        }
        for episode in discovered_episodes
    ]
    try:
        recorded_episode_count = int(existing.get("episodeCount") or 0)
    except (TypeError, ValueError):
        recorded_episode_count = 0
    episode_count = max(
        recorded_episode_count,
        job.episode_total,
        job.episode_number,
        len(rebuilt_episodes),
        0,
    )

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
            "episodeCount": episode_count,
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "generatedBy": "tokiDownloader-local-rebuild",
        }
    )
    if rebuilt_episodes:
        rebuilt["episodes"] = rebuilt_episodes
    if cover_file:
        rebuilt["coverFile"] = cover_file
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "metadataPath": str(metadata_path),
        "backupPath": str(metadata_path.with_suffix(".json.bak")),
        "willOverwrite": metadata_path.exists(),
        "existingValid": existing_valid,
        "episodeFolderCount": len(rebuilt_episodes),
        "recoveredEpisodeCount": sum(
            episode.discovery.endswith("recovery")
            for episode in discovered_episodes
        ),
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


@dataclass(frozen=True)
class EpisodeManifestEntry:
    number: int
    source_id: str
    source_url: str
    source_title: str
    display_title: str
    folder_name: str
    folder_hints: tuple[str, ...] = ()
    number_inferred: bool = False
    record_valid: bool = True


@dataclass(frozen=True)
class EpisodeStateManifest:
    path: Path
    exists: bool
    valid: bool
    version: int
    completed_numbers: frozenset[int]
    completed_ids: frozenset[str]
    completed_ids_present: bool
    episodes: tuple[EpisodeManifestEntry, ...]
    error: str = ""


@dataclass(frozen=True)
class EpisodeFolderEntry:
    number: int
    path: Path
    folder_name: str
    source_id: str = ""
    source_url: str = ""
    source_title: str = ""
    display_title: str = ""
    number_inferred: bool = False
    discovery: str = "legacy"


def _positive_episode_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _safe_manifest_folder_name(value: Any) -> str:
    folder_name = str(value or "").strip()
    if (
        not folder_name
        or folder_name in {".", ".."}
        or "/" in folder_name
        or "\\" in folder_name
        or "\x00" in folder_name
    ):
        return ""
    return folder_name


def _parse_episode_manifest_entries(
    raw_episodes: Any,
) -> tuple[tuple[EpisodeManifestEntry, ...], bool]:
    if not isinstance(raw_episodes, list):
        return (), False
    episodes: list[EpisodeManifestEntry] = []
    valid = True
    seen_ids: set[str] = set()
    seen_folders: set[str] = set()
    required_fields = {
        "number",
        "sourceId",
        "sourceUrl",
        "sourceTitle",
        "displayTitle",
        "folderName",
    }
    for position, raw_episode in enumerate(raw_episodes, start=1):
        if not isinstance(raw_episode, dict):
            valid = False
            continue
        declared_number = _positive_episode_number(raw_episode.get("number"))
        number = declared_number or position
        number_inferred = (
            raw_episode.get("numberInferred") is True or declared_number is None
        )
        source_id = str(raw_episode.get("sourceId") or "").strip()
        source_url = str(raw_episode.get("sourceUrl") or "").strip()
        source_title = str(raw_episode.get("sourceTitle") or "").strip()
        display_title = str(raw_episode.get("displayTitle") or "").strip()
        folder_candidates: list[str] = []
        declared_folder = _safe_manifest_folder_name(raw_episode.get("folderName"))
        if declared_folder:
            folder_candidates.append(declared_folder)
        for title in (display_title, source_title):
            candidate = _safe_manifest_folder_name(
                sanitize_windows_path_segment(title, "")
            )
            if candidate and candidate.casefold() not in {
                item.casefold() for item in folder_candidates
            }:
                folder_candidates.append(candidate)
        if not folder_candidates:
            valid = False
            continue
        folder_name = folder_candidates[0]
        folder_key = folder_name.casefold()
        source_fields_are_strings = all(
            isinstance(raw_episode.get(field), str)
            for field in (
                "sourceId",
                "sourceUrl",
                "sourceTitle",
                "displayTitle",
                "folderName",
            )
        )
        record_valid = (
            required_fields.issubset(raw_episode)
            and source_fields_are_strings
            and declared_number is not None
            and bool(declared_folder)
            and (not source_id or source_id not in seen_ids)
            and folder_key not in seen_folders
        )
        if not record_valid:
            valid = False
        if source_id:
            seen_ids.add(source_id)
        seen_folders.add(folder_key)
        episodes.append(
            EpisodeManifestEntry(
                number=number,
                source_id=source_id,
                source_url=source_url,
                source_title=source_title,
                display_title=display_title,
                folder_name=folder_name,
                folder_hints=tuple(folder_candidates[1:]),
                number_inferred=number_inferred,
                record_valid=record_valid,
            )
        )
    episodes.sort(key=lambda item: item.number)
    return tuple(episodes), valid


def load_episode_metadata_manifest(
    output_path: str | Path,
) -> tuple[EpisodeManifestEntry, ...]:
    metadata_path = Path(output_path).expanduser().resolve() / "metadata.json"
    if not metadata_path.is_file():
        return ()
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(metadata, dict) or "episodes" not in metadata:
        return ()
    episodes, _valid = _parse_episode_manifest_entries(metadata.get("episodes"))
    return episodes


def load_episode_state_manifest(output_path: str | Path) -> EpisodeStateManifest:
    root = Path(output_path).expanduser().resolve()
    state_path = root / ".toki-state.json"
    if not state_path.is_file():
        return EpisodeStateManifest(
            path=state_path,
            exists=state_path.exists(),
            valid=False,
            version=0,
            completed_numbers=frozenset(),
            completed_ids=frozenset(),
            completed_ids_present=False,
            episodes=(),
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return EpisodeStateManifest(
            path=state_path,
            exists=True,
            valid=False,
            version=0,
            completed_numbers=frozenset(),
            completed_ids=frozenset(),
            completed_ids_present=False,
            episodes=(),
            error=str(error),
        )
    if not isinstance(state, dict):
        return EpisodeStateManifest(
            path=state_path,
            exists=True,
            valid=False,
            version=0,
            completed_numbers=frozenset(),
            completed_ids=frozenset(),
            completed_ids_present=False,
            episodes=(),
            error="완료 회차 상태가 JSON 객체가 아닙니다.",
        )

    valid = True
    try:
        version = int(state.get("version", 1))
    except (TypeError, ValueError):
        version = 0
        valid = False
    if version < 1:
        valid = False

    raw_completed = state.get("completedEpisodes", [])
    if not isinstance(raw_completed, list):
        raw_completed = []
        valid = False
    completed_numbers = frozenset(
        number
        for value in raw_completed
        if (number := _positive_episode_number(value)) is not None
    )

    completed_ids_present = "completedEpisodeIds" in state
    raw_completed_ids = state.get("completedEpisodeIds", [])
    if raw_completed_ids is None and not completed_ids_present:
        raw_completed_ids = []
    if not isinstance(raw_completed_ids, list):
        raw_completed_ids = []
        valid = False
    completed_ids = frozenset(
        str(value).strip() for value in raw_completed_ids if str(value).strip()
    )

    episodes: tuple[EpisodeManifestEntry, ...] = ()
    if version >= 2:
        episodes, episodes_valid = _parse_episode_manifest_entries(
            state.get("episodes")
        )
        valid = valid and episodes_valid
        seen_ids = {episode.source_id for episode in episodes if episode.source_id}
        if completed_ids_present and not completed_ids.issubset(seen_ids):
            valid = False

    return EpisodeStateManifest(
        path=state_path,
        exists=True,
        valid=valid,
        version=version,
        completed_numbers=completed_numbers,
        completed_ids=completed_ids,
        completed_ids_present=completed_ids_present,
        episodes=episodes,
    )


def _episode_path_sort_key(path: Path) -> list[tuple[int, Any]]:
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
    ]


def _modern_episode_recovery_titles(root: Path) -> tuple[str, ...]:
    """Return conservative, filesystem-safe work-title prefixes for recovery."""

    candidates: list[Any] = []
    metadata_path = root / "metadata.json"
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = None
        if isinstance(metadata, dict):
            candidates.append(metadata.get("title"))

    folder_match = re.match(r"^\[[^]]*\]\[[^]]*\]\s*(.+)$", root.name)
    if folder_match:
        candidates.append(folder_match.group(1))

    titles: list[str] = []
    seen: set[str] = set()
    placeholders = {"", "메타데이터 확인 중", "제목 없음"}
    for candidate in candidates:
        title = _episode_rename_safe_text(candidate)
        key = title.casefold()
        if title in placeholders or key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return tuple(titles)


def _folder_has_supported_episode_image(folder: Path) -> bool:
    try:
        with os.scandir(folder) as children:
            return any(
                child.is_file(follow_symlinks=False)
                and Path(child.name).suffix.lower() in IMAGE_EXTENSIONS
                for child in children
            )
    except OSError:
        return False


def _is_modern_episode_recovery_folder(
    folder: Path,
    work_titles: tuple[str, ...],
) -> bool:
    folder_name = _episode_rename_safe_text(folder.name)
    folded_name = folder_name.casefold()
    if not any(
        folded_name.startswith(f"{title.casefold()} ")
        and len(folder_name) > len(title) + 1
        for title in work_titles
    ):
        return False
    return _folder_has_supported_episode_image(folder)


def discover_episode_folders(
    output_path: str | Path,
    state_manifest: EpisodeStateManifest | None = None,
) -> list[EpisodeFolderEntry]:
    root = Path(output_path).expanduser().resolve()
    if not root.is_dir():
        return []
    manifest = state_manifest or load_episode_state_manifest(root)
    physical_folders = [
        Path(entry.path).resolve()
        for entry in os.scandir(root)
        if entry.is_dir(follow_symlinks=False)
        and entry.name not in {"_converted", "_pdf", "_archives", ".toki-trash"}
    ]
    physical_folders.sort(key=_episode_path_sort_key)
    by_name: dict[str, list[Path]] = {}
    legacy_by_number: dict[int, list[Path]] = {}
    for folder in physical_folders:
        by_name.setdefault(folder.name.casefold(), []).append(folder)
        matched = re.match(r"^0*(\d+)(?:\s|$)", folder.name)
        if matched:
            legacy_by_number.setdefault(int(matched.group(1)), []).append(folder)

    discovered: list[EpisodeFolderEntry] = []
    consumed_paths: set[Path] = set()
    manifest_sources: list[tuple[int, EpisodeManifestEntry, str]] = []
    if manifest.version >= 2:
        manifest_sources.extend(
            (
                0 if episode.record_valid else 2,
                episode,
                "manifest" if episode.record_valid else "manifest-recovery",
            )
            for episode in manifest.episodes
        )
    manifest_sources.extend(
        (
            1 if episode.record_valid else 3,
            episode,
            "metadata" if episode.record_valid else "metadata-recovery",
        )
        for episode in load_episode_metadata_manifest(root)
    )
    manifest_sources.sort(key=lambda item: (item[0], item[1].number))

    def add_manifest_folder(
        episode: EpisodeManifestEntry,
        folder: Path,
        discovery: str,
    ) -> None:
        if folder in consumed_paths:
            return
        consumed_paths.add(folder)
        discovered.append(
            EpisodeFolderEntry(
                number=episode.number,
                path=folder,
                folder_name=folder.name,
                source_id=episode.source_id,
                source_url=episode.source_url,
                source_title=episode.source_title,
                display_title=episode.display_title,
                number_inferred=episode.number_inferred,
                discovery=discovery,
            )
        )

    legacy_fallbacks: list[EpisodeManifestEntry] = []
    for _priority, episode, discovery in manifest_sources:
        exact_matches: list[Path] = []
        matched_paths: set[Path] = set()
        for folder_name in (episode.folder_name, *episode.folder_hints):
            for folder in by_name.get(folder_name.casefold(), []):
                if folder not in matched_paths:
                    matched_paths.add(folder)
                    exact_matches.append(folder)
        if exact_matches:
            for folder in exact_matches:
                add_manifest_folder(episode, folder, discovery)
        else:
            legacy_fallbacks.append(episode)

    fallbacks_by_number: dict[int, list[EpisodeManifestEntry]] = {}
    for episode in legacy_fallbacks:
        if episode.record_valid:
            fallbacks_by_number.setdefault(episode.number, []).append(episode)
    for number, candidates in fallbacks_by_number.items():
        for folder in legacy_by_number.get(number, []):
            if folder in consumed_paths:
                continue
            matches = [
                episode for episode in candidates
                if any(
                    _episode_rename_titles_match(folder.name, title, number)
                    for title in (
                        episode.source_title, episode.display_title,
                        episode.folder_name, *episode.folder_hints,
                    )
                )
            ]
            identities = {
                ("id", episode.source_id) if episode.source_id else
                ("title", _episode_rename_title_identity(
                    episode.source_title or episode.display_title or episode.folder_name,
                    number,
                ))
                for episode in matches
            }
            # An ordinal alone is not evidence of chapter identity. Ambiguous
            # title matches remain idless instead of claiming either source ID.
            if len(identities) == 1:
                add_manifest_folder(matches[0], folder, "legacy-fallback")

    work_titles = _modern_episode_recovery_titles(root)
    used_recovery_numbers = {
        episode.number for episode in discovered
    } | set(legacy_by_number)
    next_recovery_number = 1
    for folder in physical_folders:
        if folder in consumed_paths or not _is_modern_episode_recovery_folder(
            folder, work_titles
        ):
            continue
        while next_recovery_number in used_recovery_numbers:
            next_recovery_number += 1
        consumed_paths.add(folder)
        used_recovery_numbers.add(next_recovery_number)
        discovered.append(
            EpisodeFolderEntry(
                number=next_recovery_number,
                path=folder,
                folder_name=folder.name,
                source_title=folder.name,
                display_title=folder.name,
                number_inferred=True,
                discovery="modern-recovery",
            )
        )
        next_recovery_number += 1

    for number in sorted(legacy_by_number):
        for folder in legacy_by_number[number]:
            if folder in consumed_paths:
                continue
            consumed_paths.add(folder)
            discovered.append(
                EpisodeFolderEntry(
                    number=number,
                    path=folder,
                    folder_name=folder.name,
                )
            )
    discovery_order = {
        "manifest": 0,
        "metadata": 1,
        "manifest-recovery": 2,
        "metadata-recovery": 3,
        "modern-recovery": 4,
        "legacy-fallback": 5,
        "legacy": 6,
    }
    discovered.sort(
        key=lambda item: (
            item.number,
            discovery_order.get(item.discovery, 9),
            _episode_path_sort_key(item.path),
        )
    )
    return discovered


def _webp_container_valid(handle: Any, header: bytes, size: int) -> bool:
    """Bounded-memory container check, matching downloader_policy.js (not decoding)."""
    if (
        size < 20 or header[:4] != b"RIFF" or header[8:12] != b"WEBP"
        or int.from_bytes(header[4:8], "little") + 8 != size
    ):
        return False

    def chunks_complete(start: int, end: int, frame: bool = False) -> bool:
        offset = start
        has_image = False
        while offset < end:
            if offset + 8 > end:
                return False
            handle.seek(offset)
            chunk = handle.read(8)
            if len(chunk) != 8:
                return False
            kind = chunk[:4]
            length = int.from_bytes(chunk[4:8], "little")
            next_offset = offset + 8 + length + length % 2
            if next_offset > end:
                return False
            if kind in {b"VP8 ", b"VP8L"}:
                if length < (10 if kind == b"VP8 " else 5):
                    return False
                has_image = True
            if kind == b"ANMF":
                if frame or length < 24 or not chunks_complete(
                    offset + 24, offset + 8 + length, True
                ):
                    return False
                has_image = True
            offset = next_offset
        return offset == end and has_image

    return chunks_complete(12, size)


def _image_signature_valid(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size <= 0:
            return False
        with path.open("rb") as handle:
            header = handle.read(16)
            if path.suffix.lower() == ".webp":
                return _webp_container_valid(handle, header, size)
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

    state_manifest = load_episode_state_manifest(output_path)
    state_path = state_manifest.path
    state_valid = state_manifest.valid
    uses_episode_ids = (
        state_manifest.version >= 2 and state_manifest.completed_ids_present
    )
    if uses_episode_ids:
        expected_episode_ids = set(state_manifest.completed_ids)
        expected_id_episodes = {
            episode.number
            for episode in state_manifest.episodes
            if episode.source_id in expected_episode_ids
        }
        expected_number_fallbacks = {
            episode.number
            for episode in state_manifest.episodes
            if not episode.source_id
            and episode.number in state_manifest.completed_numbers
        }
        expected_episodes = expected_id_episodes | expected_number_fallbacks
    else:
        expected_episode_ids = set()
        expected_episodes = set(state_manifest.completed_numbers)
        expected_number_fallbacks = set(expected_episodes)
    if state_manifest.exists and not state_valid:
        add_issue("state_invalid", state_path, "완료 회차 상태 파일을 읽을 수 없습니다.")

    episode_folders: dict[int, list[EpisodeFolderEntry]] = {}
    archived = {item["folderName"]: item for item in archived_episodes(output_path, verify_crc=True)}
    image_count = 0
    other_file_count = 0
    zero_byte_count = 0
    invalid_image_count = 0
    empty_episode_count = 0
    for episode_folder in discover_episode_folders(output_path, state_manifest):
        episode_number = episode_folder.number
        episode_path = episode_folder.path
        episode_folders.setdefault(episode_number, []).append(episode_folder)
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
                    add_issue("image_invalid", child_path, "이미지 서명 또는 파일 구조가 올바르지 않습니다.")
        if episode_image_count == 0 and episode_folder.folder_name not in archived:
            empty_episode_count += 1
            add_issue("episode_empty", episode_path, "회차 폴더에 지원 이미지가 없습니다.")

    physical_folder_names = {folder.folder_name for folders in episode_folders.values() for folder in folders}
    archived_image_count = 0
    for name, item in archived.items():
        if name not in physical_folder_names:
            episode_folders.setdefault(int(item["number"]), []).append(EpisodeFolderEntry(
                number=int(item["number"]), path=Path(item["archivePath"]), folder_name=name,
                source_id=item.get("sourceId", ""), source_title=item.get("sourceTitle", name),
                display_title=name, discovery="archive",
            ))
        archived_image_count += int(item.get("imageCount", 0))
    physical_episodes = set(episode_folders)

    def episode_identity(folder: EpisodeFolderEntry) -> tuple[str, str] | None:
        if folder.source_id:
            return "source", folder.source_id
        if folder.discovery != "legacy":
            return "folder", os.path.normcase(folder.folder_name)
        return None

    duplicate_episodes: list[int] = []
    for number, folders in episode_folders.items():
        if len(folders) <= 1:
            continue
        identities = [episode_identity(folder) for folder in folders]
        known_identities = [identity for identity in identities if identity is not None]
        if len(known_identities) != len(folders) or len(set(known_identities)) != len(
            known_identities
        ):
            duplicate_episodes.append(number)
    duplicate_episodes.sort()
    for number in duplicate_episodes:
        add_issue(
            "episode_duplicate",
            episode_folders[number][0].path,
            f"{number}번 회차 폴더가 {len(episode_folders[number])}개입니다.",
        )

    all_episode_folders = [
        folder for folders in episode_folders.values() for folder in folders
    ]
    if all_episode_folders and not state_manifest.exists:
        add_issue(
            "state_missing",
            state_path,
            "회차 폴더가 있지만 완료 회차 상태 파일이 없습니다.",
        )
    physical_episode_ids = {
        folder.source_id for folder in all_episode_folders if folder.source_id
    }
    if uses_episode_ids:
        physical_number_fallbacks = {
            folder.number for folder in all_episode_folders if not folder.source_id
        }
        missing_episode_ids = sorted(expected_episode_ids - physical_episode_ids)
        numbers_by_id = {
            episode.source_id: episode.number
            for episode in state_manifest.episodes
            if episode.source_id
        }
        missing_number_fallbacks = sorted(
            expected_number_fallbacks - physical_number_fallbacks
        )
        missing_episodes = sorted(
            {
                numbers_by_id[source_id]
                for source_id in missing_episode_ids
                if source_id in numbers_by_id
            }
            | set(missing_number_fallbacks)
        )
        for source_id in missing_episode_ids:
            number = numbers_by_id.get(source_id)
            label = f"{number}번 회차" if number is not None else source_id
            add_issue("episode_missing", None, f"완료 상태의 {label} 폴더가 없습니다.")
        for number in missing_number_fallbacks:
            add_issue(
                "episode_missing",
                None,
                f"완료 상태의 ID 없는 {number}번 회차 폴더가 없습니다.",
            )
        untracked_episode_ids = (
            sorted(physical_episode_ids - expected_episode_ids) if state_valid else []
        )
        untracked_number_fallbacks = (
            physical_number_fallbacks - expected_number_fallbacks
            if state_valid
            else set()
        )
        untracked_episodes = sorted(
            {
                folder.number
                for folder in all_episode_folders
                if folder.source_id in untracked_episode_ids
            }
            | untracked_number_fallbacks
        )
        expected_episode_count = len(expected_episode_ids) + len(
            expected_number_fallbacks
        )
        missing_episode_count = len(missing_episode_ids) + len(
            missing_number_fallbacks
        )
    else:
        missing_episode_ids = []
        untracked_episode_ids = []
        missing_episodes = sorted(expected_episodes - physical_episodes)
        for number in missing_episodes:
            add_issue(
                "episode_missing",
                None,
                f"완료 상태의 {number}번 회차 폴더가 없습니다.",
            )
        untracked_episodes = (
            sorted(physical_episodes - expected_episodes) if state_valid else []
        )
        expected_episode_count = len(expected_episodes)
        missing_episode_count = len(missing_episodes)

    physical_episode_identities = {
        episode_identity(folder) or ("legacy-number", str(folder.number))
        for folder in all_episode_folders
    }

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
            "episodeFolders": len(all_episode_folders),
            "uniqueEpisodes": len(physical_episode_identities),
            "expectedEpisodes": expected_episode_count,
            "images": image_count,
            "archivedEpisodes": len(archived),
            "archivedImages": archived_image_count,
            "otherFiles": other_file_count,
            "emptyEpisodes": empty_episode_count,
            "zeroByteImages": zero_byte_count,
            "invalidImages": invalid_image_count,
            "duplicateEpisodes": len(duplicate_episodes),
            "missingEpisodes": missing_episode_count,
            "untrackedEpisodes": len(untracked_episodes),
            "issueCount": issue_count,
            "returnedIssues": len(issues),
            "issuesTruncated": issue_count > len(issues),
        },
        "metadata": {"path": str(metadata_path), "valid": metadata_valid},
        "state": {
            "path": str(state_path),
            "exists": state_manifest.exists,
            "valid": state_valid,
            "version": state_manifest.version,
            "manifestEpisodes": len(state_manifest.episodes),
            "completedEpisodeIds": len(state_manifest.completed_ids),
        },
        "missingEpisodes": missing_episodes,
        "missingEpisodeIds": missing_episode_ids,
        "untrackedEpisodes": untracked_episodes,
        "untrackedEpisodeIds": untracked_episode_ids,
        "issues": issues,
    }


def list_job_episode_images(
    job_id: str,
    episode: int | None = None,
    *,
    episode_id: str | None = None,
    episode_folder: str | None = None,
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

    folders = discover_episode_folders(output_path)
    archive_by_folder = {item["folderName"]: item for item in archived_episodes(output_path)}
    existing_names = {folder.folder_name for folder in folders}
    for name, item in archive_by_folder.items():
        if name not in existing_names:
            folders.append(EpisodeFolderEntry(
                number=int(item["number"]), path=Path(item["archivePath"]), folder_name=name,
                source_id=item.get("sourceId", ""), source_title=item.get("sourceTitle", name),
                display_title=name, discovery="archive",
            ))
    folders.sort(key=lambda folder: (folder.number, _episode_path_sort_key(Path(folder.folder_name))))
    available_episodes = sorted({folder.number for folder in folders})
    if not folders:
        raise FileNotFoundError("미리 볼 회차 폴더가 없습니다.")
    if episode_id is not None and episode_folder is not None:
        raise ValueError("--episode-id와 --episode-folder는 함께 지정할 수 없습니다.")
    requested_episode = int(episode or 0)
    candidates = [
        folder for folder in folders
        if (not requested_episode or folder.number == requested_episode)
        and (episode_id is None or folder.source_id == episode_id)
        and (episode_folder is None or folder.folder_name == episode_folder)
    ]
    if not candidates:
        raise ValueError("지정한 회차 폴더를 찾을 수 없습니다.")
    explicit_selection = bool(requested_episode) or episode_id is not None or episode_folder is not None
    if len(candidates) > 1 and explicit_selection:
        choices = "; ".join(
            f"{folder.folder_name} (ID: {folder.source_id or '없음'})"
            for folder in candidates
        )
        raise ValueError(
            "회차 선택이 중복됩니다. --episode-id 또는 --episode-folder로 "
            f"구분해주세요: {choices}"
        )
    selected = candidates[0]
    selected_episode = selected.number

    def natural_key(path: Path) -> list[tuple[int, Any]]:
        return [
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", path.name)
        ]

    images: list[Path] = []
    if selected.path.is_dir():
        with os.scandir(selected.path) as children:
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
        "episodeId": selected.source_id,
        "archivePath": archive_by_folder.get(selected.folder_name, {}).get("archivePath", ""),
        "archivedImageCount": archive_by_folder.get(selected.folder_name, {}).get("imageCount", 0),
        "episodeFolder": selected.folder_name,
        "availableEpisodes": available_episodes,
        "episodeEntries": [
            {
                "number": folder.number,
                "sourceId": folder.source_id,
                "folderName": folder.folder_name,
                "displayTitle": folder.display_title or folder.folder_name,
            }
            for folder in folders
        ],
        "episodeFolders": [str(selected.path)],
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


def normalize_image_resize_dimension(value: int | None) -> int:
    dimension = 0 if value is None else int(value)
    if dimension != 0 and not 64 <= dimension <= 16384:
        raise ValueError("이미지 리사이즈 크기는 0(제한 없음) 또는 64~16384px여야 합니다.")
    return dimension


def normalize_image_excluded_extensions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("제외할 이미지 유형은 확장자 목록이어야 합니다.")
    normalized: list[str] = []
    for item in value:
        extension = str(item or "").strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        if extension not in IMAGE_EXTENSIONS:
            raise ValueError(
                f"지원하지 않는 이미지 제외 확장자입니다: {extension}"
            )
        if extension not in normalized:
            normalized.append(extension)
    if len(normalized) > 16:
        raise ValueError("제외할 이미지 유형은 최대 16개까지 지정할 수 있습니다.")
    return normalized


def image_processing_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    width = normalize_image_resize_dimension(source.get("imageResizeMaxWidth"))
    height = normalize_image_resize_dimension(source.get("imageResizeMaxHeight"))
    excluded = normalize_image_excluded_extensions(
        source.get("imageExcludedExtensions")
    )
    return {
        "maxWidth": width,
        "maxHeight": height,
        "resizeEnabled": bool(width or height),
        "excludedExtensions": excluded,
        "supportedExtensions": sorted(IMAGE_EXTENSIONS),
        "preservesAspectRatio": True,
        "preservesOriginals": True,
    }


def _collect_conversion_sources(output_path: Path) -> list[Path]:
    sources: list[Path] = []
    for episode_folder in discover_episode_folders(output_path):
        with os.scandir(episode_folder.path) as children:
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


def _conversion_source_mappings(
    output_path: Path,
    normalized_format: str,
    max_width: int,
    max_height: int,
    excluded_extensions: list[str],
) -> tuple[Path, list[tuple[Path, Path]], list[Path]]:
    target_name = normalized_format
    if max_width or max_height:
        target_name = f"{normalized_format}-{max_width}x{max_height}"
    target_root = output_path / "_converted" / target_name
    extension = IMAGE_CONVERSION_FORMATS[normalized_format]["extension"]
    all_sources = _collect_conversion_sources(output_path)
    excluded_set = set(excluded_extensions)
    excluded_sources = [
        source for source in all_sources if source.suffix.lower() in excluded_set
    ]
    sources = [
        source for source in all_sources if source.suffix.lower() not in excluded_set
    ]
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
    return target_root, mappings, excluded_sources


def plan_image_conversion(
    job_id: str,
    image_format: str,
    *,
    quality: int | None = None,
    max_width: int | None = None,
    max_height: int | None = None,
    excluded_extensions: list[str] | tuple[str, ...] | None = None,
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
    normalized_width = normalize_image_resize_dimension(max_width)
    normalized_height = normalize_image_resize_dimension(max_height)
    normalized_excluded = normalize_image_excluded_extensions(excluded_extensions)
    clean_sample_limit = max(1, min(1000, int(sample_limit)))
    target_root, mappings, excluded_sources = _conversion_source_mappings(
        output_path,
        normalized_format,
        normalized_width,
        normalized_height,
        normalized_excluded,
    )
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
        "maxWidth": normalized_width,
        "maxHeight": normalized_height,
        "resizeEnabled": bool(normalized_width or normalized_height),
        "preservesAspectRatio": True,
        "excludedExtensions": normalized_excluded,
        "candidateSourceCount": len(mappings) + len(excluded_sources),
        "excludedSourceCount": len(excluded_sources),
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
    max_width: int | None = None,
    max_height: int | None = None,
    excluded_extensions: list[str] | tuple[str, ...] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    plan = plan_image_conversion(
        job_id,
        image_format,
        quality=quality,
        max_width=max_width,
        max_height=max_height,
        excluded_extensions=excluded_extensions,
        sample_limit=1,
    )
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
    _target_root, mappings, _excluded_sources = _conversion_source_mappings(
        output_path,
        normalized_format,
        int(plan["maxWidth"]),
        int(plan["maxHeight"]),
        list(plan["excludedExtensions"]),
    )
    converted = 0
    resized = 0
    skipped_existing = 0
    failures: list[dict[str, str]] = []
    failure_count = 0
    cancelled = False
    recovered_temporary_files = 0
    total = len(mappings)
    for index, (source, target) in enumerate(mappings, start=1):
        if cancel_check and cancel_check():
            cancelled = True
            break
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
                        "resized": resized,
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
                original_size = image.size
                if plan["resizeEnabled"]:
                    width_limit = int(plan["maxWidth"]) or image.width
                    height_limit = int(plan["maxHeight"]) or image.height
                    image.thumbnail(
                        (width_limit, height_limit), Image.Resampling.LANCZOS
                    )
                was_resized = image.size != original_size
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
            if was_resized:
                resized += 1
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
                    "resized": resized,
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
        "resizedCount": resized,
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


def pdf_generation_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = normalize_config(config) if config is not None else load_config()
    try:
        pillow_version = importlib.metadata.version("Pillow")
        dependency_available = True
    except importlib.metadata.PackageNotFoundError:
        pillow_version = ""
        dependency_available = False
    return {
        "automatic": bool(source["pdfGenerationEnabled"]),
        "scope": "per_episode",
        "targetFolder": "_pdf",
        "preservesOriginals": True,
        "atomicOutput": True,
        "replacesGeneratedPdfWhenSourcesChange": True,
        "dependency": {
            "name": "Pillow",
            "available": dependency_available,
            "version": pillow_version,
            "requirementsFile": str(ROOT_DIR / "requirements-image-tools.txt"),
        },
    }


def _natural_path_key(path: Path) -> list[tuple[int, Any]]:
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
    ]


def _pdf_episode_mappings(
    output_path: Path,
) -> tuple[Path, list[tuple[Path, list[Path], Path]], int]:
    target_root = output_path / "_pdf"
    episode_folders = [
        episode_folder.path
        for episode_folder in discover_episode_folders(output_path)
    ]
    mappings: list[tuple[Path, list[Path], Path]] = []
    used_targets: set[str] = set()
    empty_count = 0
    for folder in episode_folders:
        with os.scandir(folder) as children:
            images = [
                Path(child.path).resolve()
                for child in children
                if child.is_file(follow_symlinks=False)
                and Path(child.name).suffix.lower() in IMAGE_EXTENSIONS
            ]
        images.sort(key=_natural_path_key)
        if not images:
            empty_count += 1
            continue
        target = target_root / f"{folder.name}.pdf"
        suffix = 2
        while os.path.normcase(str(target)) in used_targets:
            target = target_root / f"{folder.name}_{suffix}.pdf"
            suffix += 1
        used_targets.add(os.path.normcase(str(target)))
        mappings.append((folder, images, target))
    return target_root, mappings, empty_count


def _pdf_target_is_current(target: Path, images: list[Path]) -> bool:
    if not target.is_file() or target.stat().st_size <= 4:
        return False
    latest_source = max(image.stat().st_mtime_ns for image in images)
    return target.stat().st_mtime_ns >= latest_source


def plan_job_pdf_generation(
    job_id: str,
    *,
    sample_limit: int = 100,
) -> dict[str, Any]:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if job.state in ACTIVE_JOB_STATES:
        raise ValueError("대기 또는 실행 중인 작품은 PDF를 생성할 수 없습니다.")
    if not job.output_path:
        raise ValueError("저장된 작품 폴더 경로가 없습니다.")
    output_path = Path(job.output_path).expanduser().resolve()
    if not output_path.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output_path}")
    clean_sample_limit = max(1, min(1000, int(sample_limit)))
    target_root, mappings, empty_count = _pdf_episode_mappings(output_path)
    current_count = 0
    replacement_count = 0
    samples: list[dict[str, Any]] = []
    total_images = 0
    source_bytes = 0
    for folder, images, target in mappings:
        current = _pdf_target_is_current(target, images)
        current_count += int(current)
        replacement_count += int(target.exists() and not current)
        total_images += len(images)
        source_bytes += sum(image.stat().st_size for image in images)
        if len(samples) < clean_sample_limit:
            samples.append(
                {
                    "episodeFolder": str(folder),
                    "target": str(target),
                    "pageCount": len(images),
                    "exists": target.exists(),
                    "current": current,
                }
            )
    policy = pdf_generation_policy_snapshot()
    return {
        "jobId": job.job_id,
        "workKey": job.work_key,
        "title": job.title,
        "outputPath": str(output_path),
        "targetRoot": str(target_root),
        "scope": "per_episode",
        "episodeFolderCount": len(mappings) + empty_count,
        "episodeCount": len(mappings),
        "emptyEpisodeCount": empty_count,
        "sourceCount": total_images,
        "sourceBytes": source_bytes,
        "existingCurrentCount": current_count,
        "replacementCount": replacement_count,
        "pendingCount": len(mappings) - current_count,
        "preservesOriginals": True,
        "atomicOutput": True,
        "dependency": policy["dependency"],
        "sample": samples,
        "sampleTruncated": len(mappings) > clean_sample_limit,
        "executed": False,
    }


def generate_job_pdfs(
    job_id: str,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    plan = plan_job_pdf_generation(job_id, sample_limit=1)
    if not plan["dependency"]["available"]:
        raise RuntimeError(
            "PDF 생성에는 Pillow가 필요합니다. "
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements-image-tools.txt"
        )
    from PIL import Image, ImageOps

    output_path = Path(plan["outputPath"])
    target_root, mappings, _empty_count = _pdf_episode_mappings(output_path)
    generated = 0
    replaced = 0
    skipped = 0
    failed = 0
    failures: list[dict[str, str]] = []
    recovered_temporary_files = 0
    cancelled = False
    total = len(mappings)
    for index, (folder, images, target) in enumerate(mappings, start=1):
        if cancel_check and cancel_check():
            cancelled = True
            break
        temporary = target.with_suffix(target.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
            recovered_temporary_files += 1
        if _pdf_target_is_current(target, images):
            skipped += 1
            status = "skipped"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            pages: list[Any] = []
            try:
                for source in images:
                    if cancel_check and cancel_check():
                        cancelled = True
                        break
                    with Image.open(source) as opened:
                        page = ImageOps.exif_transpose(opened)
                        if page.mode in {"RGBA", "LA"} or (
                            page.mode == "P" and "transparency" in page.info
                        ):
                            rgba = page.convert("RGBA")
                            rgb = Image.new("RGB", rgba.size, "white")
                            rgb.paste(rgba, mask=rgba.getchannel("A"))
                            page = rgb
                        else:
                            page = page.convert("RGB")
                        pages.append(page.copy())
                if cancelled:
                    status = "cancelled"
                elif not pages:
                    raise ValueError("PDF에 넣을 이미지가 없습니다.")
                else:
                    pages[0].save(
                        temporary,
                        format="PDF",
                        save_all=True,
                        append_images=pages[1:],
                        resolution=100.0,
                    )
                    existed = target.exists()
                    os.replace(temporary, target)
                    generated += 1
                    replaced += int(existed)
                    status = "generated"
            except Exception as error:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                failed += 1
                if len(failures) < 100:
                    failures.append(
                        {"episodeFolder": str(folder), "error": str(error)}
                    )
                status = "failed"
            finally:
                for page in pages:
                    page.close()
        if progress_callback:
            progress_callback(
                {
                    "current": index,
                    "total": total,
                    "generated": generated,
                    "replaced": replaced,
                    "skipped": skipped,
                    "failed": failed,
                    "pageCount": len(images),
                    "episodeFolder": str(folder),
                    "target": str(target),
                    "status": status,
                }
            )
        if cancelled:
            break
    processed = generated + skipped + failed
    return {
        **plan,
        "targetRoot": str(target_root),
        "executed": True,
        "generatedCount": generated,
        "replacedCount": replaced,
        "skippedCurrentCount": skipped,
        "failedCount": failed,
        "failures": failures,
        "failuresTruncated": failed > len(failures),
        "processedCount": processed,
        "cancelled": cancelled,
        "remainingCount": total - processed,
        "recoveredTemporaryFiles": recovered_temporary_files,
        "success": not cancelled and processed == total and failed == 0,
        "preservesOriginals": True,
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
