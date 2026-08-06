from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from collections import deque
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
    author: str = ""
    group: str = ""
    site: str = ""
    metadata_path: str = ""
    user_note: str = ""
    pinned: bool = False
    tag_color: str = ""
    show_browser: bool = False
    metadata_only: bool = False
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
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_job(cls, job: DownloadJob) -> "DownloadRun":
        finished_at = job.created_at if job.state in {"완료", "오류", "중지됨"} else ""
        return cls(
            run_id=job.job_id,
            work_key=job.work_key,
            requested_start=job.start,
            requested_last=job.last,
            operation="metadata_refresh" if job.metadata_only else "download",
            state=job.state,
            selected_episodes=job.episode_total,
            processed_episodes=job.episode_index,
            last_episode_number=job.episode_number,
            progress=job.progress,
            error=job.error,
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


def _connect_job_db() -> sqlite3.Connection:
    connection = sqlite3.connect(JOB_DB_PATH, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            work_key TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            progress INTEGER NOT NULL DEFAULT 0,
            url TEXT NOT NULL DEFAULT '',
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
    database_key = str(JOB_DB_PATH.resolve())
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
                    pinned = ?, tag_color = ?, payload = ?
                WHERE job_id = ?
                """,
                (
                    work_key,
                    str(data.get("title") or ""),
                    str(data.get("state") or ""),
                    int(data.get("progress") or 0),
                    str(data.get("url") or ""),
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
        _INITIALIZED_JOB_DBS.add(database_key)
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
    return connection


def save_jobs(jobs: list[DownloadJob]) -> None:
    if not jobs:
        return
    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = [
        (
            job.job_id,
            job.work_key,
            job.title,
            job.state,
            job.progress,
            job.url,
            int(job.pinned),
            job.tag_color,
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
            INSERT INTO jobs(
                job_id, work_key, title, state, progress, url, pinned, tag_color,
                created_at, updated_at, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(work_key) DO UPDATE SET
                job_id=excluded.job_id,
                title=excluded.title,
                state=excluded.state,
                progress=excluded.progress,
                url=excluded.url,
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


def save_runs(runs: list[DownloadRun]) -> None:
    if not runs:
        return
    updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
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
    connection = _connect_job_db()
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
            "(title LIKE ? COLLATE NOCASE OR work_key LIKE ? COLLATE NOCASE "
            "OR url LIKE ? COLLATE NOCASE)"
        )
        parameters.extend([pattern, pattern, pattern])
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
) -> list[DownloadJob]:
    field_names = set(DownloadJob.__dataclass_fields__)
    order_by = {
        "updated": "pinned DESC, updated_at DESC, rowid DESC",
        "title": "pinned DESC, title COLLATE NOCASE ASC, updated_at DESC",
        "progress": "pinned DESC, progress DESC, updated_at DESC",
    }.get(sort)
    if order_by is None:
        raise ValueError(f"지원하지 않는 작업 정렬입니다: {sort}")
    where_sql, parameters = _job_filter_clause(query, state)
    connection = _connect_job_db()
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


def delete_job_record(job_id: str) -> DownloadJob:
    job = load_job_by_id(job_id)
    if job is None:
        raise ValueError(f"작업 기록을 찾을 수 없습니다: {job_id}")
    if job.state in {"대기", "실행 중"}:
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
    if any(state in {"대기", "실행 중"} for state in clean_states):
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
