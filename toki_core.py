from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT_DIR = Path(__file__).resolve().parent
DOWNLOADER_PATH = ROOT_DIR / "down.js"
CONFIG_PATH = ROOT_DIR / "config.json"
LOG_DIR = ROOT_DIR / "logs"
LOG_PATH = LOG_DIR / "gui.log"
JOB_DB_PATH = ROOT_DIR / "jobs.db"
CONTROL_SERVER_NAME = "tokiDownloaderGUI"
EVENT_PREFIX = "@@TOKI@@"
_INITIALIZED_JOB_DBS: set[str] = set()


def default_config() -> dict[str, Any]:
    return {
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
    }


def load_config() -> dict[str, Any]:
    config = default_config()
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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


def _rotate_log_if_needed(max_bytes: int = 2 * 1024 * 1024) -> None:
    try:
        if LOG_PATH.stat().st_size <= max_bytes:
            return
        backup = LOG_PATH.with_suffix(".log.1")
        if backup.exists():
            backup.unlink()
        LOG_PATH.replace(backup)
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


def find_node() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js를 찾지 못했습니다. Node.js 18 이상을 설치해주세요.")
    return node


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
    show_browser: bool = False
    episode_index: int = 0
    episode_total: int = 0
    episode_number: int = 0
    image_current: int = 0
    image_total: int = 0
    progress: int = 0
    error: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if not self.work_key:
            self.work_key = build_work_key(self.url)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def _connect_job_db() -> sqlite3.Connection:
    connection = sqlite3.connect(JOB_DB_PATH, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            work_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    database_key = str(JOB_DB_PATH.resolve())
    if database_key not in _INITIALIZED_JOB_DBS:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "work_key" not in columns:
            connection.execute(
                "ALTER TABLE jobs ADD COLUMN work_key TEXT NOT NULL DEFAULT ''"
            )
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
                "UPDATE jobs SET work_key = ?, payload = ? WHERE job_id = ?",
                (work_key, json.dumps(data, ensure_ascii=False), job_id),
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_work_key ON jobs(work_key)"
        )
        connection.commit()
        _INITIALIZED_JOB_DBS.add(database_key)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC)"
    )
    return connection


def save_jobs(jobs: list[DownloadJob]) -> None:
    if not jobs:
        return
    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = [
        (
            job.job_id,
            job.work_key,
            job.created_at,
            updated_at,
            json.dumps(job.to_dict(), ensure_ascii=False),
        )
        for job in jobs
    ]
    connection = _connect_job_db()
    try:
        with connection:
            connection.executemany(
                """
            INSERT INTO jobs(job_id, work_key, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(work_key) DO UPDATE SET
                job_id=excluded.job_id,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                payload=excluded.payload
                """,
                rows,
            )
    finally:
        connection.close()


def count_jobs() -> int:
    connection = _connect_job_db()
    try:
        return int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    finally:
        connection.close()


def load_job_by_work_key(work_key: str) -> DownloadJob | None:
    field_names = set(DownloadJob.__dataclass_fields__)
    connection = _connect_job_db()
    try:
        row = connection.execute(
            "SELECT payload FROM jobs WHERE work_key = ?",
            (work_key,),
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


def load_jobs_page(limit: int = 200, offset: int = 0) -> list[DownloadJob]:
    field_names = set(DownloadJob.__dataclass_fields__)
    connection = _connect_job_db()
    try:
        rows = connection.execute(
            "SELECT payload FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (max(1, int(limit)), max(0, int(offset))),
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


def load_recent_jobs(limit: int = 500) -> list[DownloadJob]:
    return load_jobs_page(limit=limit, offset=0)


def build_downloader_args(job: DownloadJob, json_events: bool = True) -> list[str]:
    args = [str(DOWNLOADER_PATH), "-url", job.url, "-output", job.output_dir]
    if job.start is not None:
        args.extend(["-start", str(job.start)])
    if job.last is not None:
        args.extend(["-last", str(job.last)])
    if job.show_browser:
        args.append("-show-browser")
    if json_events:
        args.append("-json-events")
    return args


def retry_job_parameters(source: DownloadJob) -> dict[str, Any]:
    """Return the shared full-rescan contract used by GUI and CLI retries."""
    return {
        "url": source.url,
        "start": None,
        "last": None,
        "output_dir": source.output_dir,
        "show_browser": source.show_browser,
    }


def open_in_explorer(target: str | os.PathLike[str]) -> None:
    resolved = str(Path(target).expanduser().resolve())
    if os.name != "nt":
        raise RuntimeError("현재는 Windows 탐색기 열기만 지원합니다.")
    os.startfile(resolved)  # type: ignore[attr-defined]
