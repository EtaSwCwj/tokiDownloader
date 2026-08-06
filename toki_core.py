from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DOWNLOADER_PATH = ROOT_DIR / "down.js"
CONFIG_PATH = ROOT_DIR / "config.json"
LOG_DIR = ROOT_DIR / "logs"
LOG_PATH = LOG_DIR / "gui.log"
CONTROL_SERVER_NAME = "tokiDownloaderGUI"
EVENT_PREFIX = "@@TOKI@@"


def default_config() -> dict[str, Any]:
    return {
        "outputDir": str(ROOT_DIR),
        "window": {"width": 860, "height": 720},
        "logVisible": True,
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
    start: int | None = None
    last: int | None = None
    title: str = "메타데이터 확인 중"
    state: str = "대기"
    output_path: str = ""
    cover_url: str = ""
    cover_path: str = ""
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_downloader_args(job: DownloadJob, json_events: bool = True) -> list[str]:
    args = [str(DOWNLOADER_PATH), "-url", job.url, "-output", job.output_dir]
    if job.start is not None:
        args.extend(["-start", str(job.start)])
    if job.last is not None:
        args.extend(["-last", str(job.last)])
    if json_events:
        args.append("-json-events")
    return args


def open_in_explorer(target: str | os.PathLike[str]) -> None:
    resolved = str(Path(target).expanduser().resolve())
    if os.name != "nt":
        raise RuntimeError("현재는 Windows 탐색기 열기만 지원합니다.")
    os.startfile(resolved)  # type: ignore[attr-defined]
