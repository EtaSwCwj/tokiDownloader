from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from youtube_provider import (
    YOUTUBE_COMPLETE_PREFIX,
    YOUTUBE_ITEM_PREFIX,
    YOUTUBE_PROGRESS_PREFIX,
    apply_youtube_upload_date_mtime,
    inspect_youtube_url,
    plan_youtube_execution,
    youtube_mtime_policy_snapshot,
)


EVENT_PREFIX = "@@TOKI@@"
_PERCENT_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_AUTHENTICATION_MARKERS = (
    "sign in",
    "login required",
    "cookies",
    "confirm you're not a bot",
    "confirm you’re not a bot",
)
_SOURCE_MARKERS = (
    "private video",
    "video unavailable",
    "unsupported url",
    "has been removed",
    "copyright claim",
)
_NETWORK_MARKERS = (
    "timed out",
    "temporary failure",
    "connection reset",
    "network is unreachable",
    "http error 403",
    "http error 429",
    "too many requests",
)


def emit_event(event: dict[str, Any], stream: TextIO | None = None) -> None:
    target = stream or sys.stdout
    target.write(EVENT_PREFIX + json.dumps(event, ensure_ascii=False) + "\n")
    target.flush()


def _optional_int(value: Any) -> int:
    text = str(value or "").strip()
    if not text or text.casefold() in {"na", "n/a", "none", "null"}:
        return 0
    try:
        return max(0, int(float(text)))
    except ValueError:
        return 0


def _display_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"na", "n/a", "none", "null"} else text


def _json_event_payload(clean: str, prefix: str) -> dict[str, Any] | None:
    payload = clean[len(prefix) :].strip()
    if not payload.startswith("{"):
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def parse_youtube_output_line(line: str) -> dict[str, Any] | None:
    clean = str(line or "").strip()
    if clean.startswith(YOUTUBE_PROGRESS_PREFIX):
        payload = _json_event_payload(clean, YOUTUBE_PROGRESS_PREFIX)
        if payload is None:
            fields = clean[len(YOUTUBE_PROGRESS_PREFIX) :].split("\t", 6)
            fields.extend([""] * (7 - len(fields)))
            video_id, index_raw, total_raw, status, percent_raw, speed, eta = fields
        else:
            video_id = payload.get("videoId")
            index_raw = payload.get("itemIndex")
            total_raw = payload.get("itemTotal")
            status = payload.get("status")
            percent_raw = payload.get("percent")
            speed = payload.get("speed")
            eta = payload.get("eta")
        match = _PERCENT_PATTERN.search(percent_raw)
        item_progress = min(100, max(0, round(float(match.group(1))))) if match else 0
        item_index = _optional_int(index_raw)
        item_total = _optional_int(total_raw)
        progress = item_progress
        if item_index and item_total:
            progress = min(
                99,
                max(0, int((((item_index - 1) + (item_progress / 100)) / item_total) * 100)),
            )
        return {
            "event": "youtube_progress",
            "videoId": _display_value(video_id),
            "itemIndex": item_index,
            "itemTotal": item_total,
            "status": _display_value(status),
            "itemProgress": item_progress,
            "progress": progress,
            "speed": _display_value(speed),
            "eta": _display_value(eta),
        }
    if clean.startswith(YOUTUBE_ITEM_PREFIX):
        payload = _json_event_payload(clean, YOUTUBE_ITEM_PREFIX)
        if payload is None:
            fields = clean[len(YOUTUBE_ITEM_PREFIX) :].split("\t", 3)
            fields.extend([""] * (4 - len(fields)))
            video_id, index_raw, total_raw, video_title = fields
            collection_title = ""
            channel = ""
        else:
            video_id = payload.get("videoId")
            index_raw = payload.get("itemIndex")
            total_raw = payload.get("itemTotal")
            video_title = payload.get("videoTitle")
            collection_title = payload.get("collectionTitle")
            channel = payload.get("channel")
        display_title = _display_value(collection_title) or _display_value(video_title)
        return {
            "event": "youtube_item",
            "videoId": _display_value(video_id),
            "itemIndex": _optional_int(index_raw),
            "itemTotal": _optional_int(total_raw),
            "title": display_title,
            "videoTitle": _display_value(video_title),
            "collectionTitle": _display_value(collection_title),
            "channel": _display_value(channel),
        }
    if clean.startswith(YOUTUBE_COMPLETE_PREFIX):
        payload = _json_event_payload(clean, YOUTUBE_COMPLETE_PREFIX)
        if payload is None:
            fields = clean[len(YOUTUBE_COMPLETE_PREFIX) :].split("\t", 4)
            fields.extend([""] * (5 - len(fields)))
            video_id, index_raw, total_raw, upload_date, file_path = fields
        else:
            video_id = payload.get("videoId")
            index_raw = payload.get("itemIndex")
            total_raw = payload.get("itemTotal")
            upload_date = payload.get("uploadDate")
            file_path = payload.get("outputPath")
        return {
            "event": "youtube_item_completed",
            "videoId": _display_value(video_id),
            "itemIndex": _optional_int(index_raw),
            "itemTotal": _optional_int(total_raw),
            "uploadDate": _display_value(upload_date),
            "outputPath": _display_value(file_path),
        }
    return None


def classify_youtube_failure(message: str) -> dict[str, Any]:
    normalized = str(message or "").casefold()
    if any(marker in normalized for marker in _AUTHENTICATION_MARKERS):
        return {"category": "authentication_required", "retryable": False}
    if any(marker in normalized for marker in _SOURCE_MARKERS):
        return {"category": "source", "retryable": False}
    if any(marker in normalized for marker in _NETWORK_MARKERS):
        return {"category": "network", "retryable": True}
    return {"category": "process", "retryable": True}


def resolve_ytdlp_command(executable: str = "") -> list[str]:
    requested = str(executable or "").strip()
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            return [str(candidate.resolve())]
        located = shutil.which(requested)
        if located:
            return [located]
        raise RuntimeError(f"yt-dlp 실행 파일을 찾을 수 없습니다: {requested}")
    located = shutil.which("yt-dlp")
    if located:
        return [located]
    adjacent = Path(sys.executable).with_name("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if adjacent.is_file():
        return [str(adjacent)]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    raise RuntimeError("yt-dlp가 설치되어 있지 않습니다. 진단 화면에서 선택 의존성을 확인하세요.")


def _safe_apply_upload_date(
    event: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> dict[str, Any] | None:
    policy = youtube_mtime_policy_snapshot(config)
    if not policy["applyUploadDateMtime"]:
        return None
    file_path = _display_value(event.get("outputPath"))
    upload_date = _display_value(event.get("uploadDate"))
    if not file_path or not upload_date:
        return None
    target = Path(file_path).expanduser().resolve()
    output_root = output_dir.resolve()
    if not target.is_relative_to(output_root):
        raise ValueError("yt-dlp 결과 파일이 지정한 저장 폴더 밖에 있어 날짜를 변경하지 않았습니다.")
    return apply_youtube_upload_date_mtime(
        target,
        upload_date,
        config=config,
        confirmed=True,
    )


def simulate_youtube_execution(
    url: str,
    output_dir: str | Path,
    *,
    delay_ms: int = 0,
    stream: TextIO = sys.stdout,
) -> int:
    reference = inspect_youtube_url(url)
    total = 3 if reference["collection"] else 1
    work_title = (
        "YouTube 모의 재생목록"
        if reference["referenceType"] == "playlist"
        else "YouTube 모의 채널"
        if reference["referenceType"] == "channel"
        else "YouTube 모의 동영상"
    )
    emit_event(
        {
            "event": "youtube_started",
            "reference": reference,
            "outputDir": str(Path(output_dir).expanduser().resolve()),
            "simulated": True,
            "progress": 0,
        },
        stream,
    )
    pause = max(0, int(delay_ms)) / 1000
    for index in range(1, total + 1):
        emit_event(
            {
                "event": "youtube_item",
                "videoId": f"simulation-{index}",
                "itemIndex": index,
                "itemTotal": total,
                "title": work_title,
                "videoTitle": f"YouTube 모의 동영상 {index}",
                "collectionTitle": work_title if reference["collection"] else "",
                "simulated": True,
            },
            stream,
        )
        for item_progress in (12, 48, 83, 100):
            overall = min(99, int((((index - 1) + item_progress / 100) / total) * 100))
            emit_event(
                {
                    "event": "youtube_progress",
                    "videoId": f"simulation-{index}",
                    "itemIndex": index,
                    "itemTotal": total,
                    "itemProgress": item_progress,
                    "progress": overall,
                    "speed": "모의 8.0 MiB/s",
                    "eta": "00:01" if item_progress < 100 else "00:00",
                    "simulated": True,
                },
                stream,
            )
            if pause:
                time.sleep(pause)
        emit_event(
            {
                "event": "youtube_item_completed",
                "videoId": f"simulation-{index}",
                "itemIndex": index,
                "itemTotal": total,
                "outputPath": str(Path(output_dir) / f"YouTube 모의 동영상 {index}.mp4"),
                "simulated": True,
            },
            stream,
        )
    emit_event(
        {
            "event": "completed",
            "provider": "youtube",
            "processedItems": total,
            "progress": 100,
            "simulated": True,
        },
        stream,
    )
    return 0


def run_youtube_execution(
    url: str,
    output_dir: str | Path,
    config: dict[str, Any],
    *,
    executable: str = "",
    stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan = plan_youtube_execution(url, output, config)
    command = [*resolve_ytdlp_command(executable), *plan["arguments"]]
    emit_event(
        {
            "event": "youtube_started",
            "reference": plan["reference"],
            "outputDir": str(output),
            "simulated": False,
            "progress": 0,
        },
        stream,
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process_environment = dict(os.environ)
    process_environment.update(
        {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    )
    process = subprocess.Popen(
        command,
        cwd=str(output),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
        env=process_environment,
    )
    output_tail: list[str] = []
    processed_items = 0
    assert process.stdout is not None
    for raw_line in process.stdout:
        clean = raw_line.rstrip("\r\n")
        event = parse_youtube_output_line(clean)
        if event:
            if event["event"] == "youtube_item_completed":
                processed_items += 1
                timestamp_result = _safe_apply_upload_date(event, output, config)
                if timestamp_result:
                    event["mtimeApplied"] = True
                    event["mtimeUtc"] = timestamp_result["targetUtc"]
            emit_event(event, stream)
            continue
        if clean:
            output_tail.append(clean)
            del output_tail[:-20]
            error_stream.write(clean + "\n")
            error_stream.flush()
    process.stdout.close()
    exit_code = int(process.wait())
    if exit_code:
        message = output_tail[-1] if output_tail else f"yt-dlp 종료 코드 {exit_code}"
        classification = classify_youtube_failure("\n".join(output_tail))
        emit_event(
            {
                "event": "error",
                "provider": "youtube",
                "message": message,
                "exitCode": exit_code,
                **classification,
            },
            stream,
        )
        return exit_code
    emit_event(
        {
            "event": "completed",
            "provider": "youtube",
            "processedItems": processed_items,
            "progress": 100,
            "simulated": False,
        },
        stream,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="tokiDownloader YouTube 실행 작업자")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config-json", default="{}")
    parser.add_argument("--yt-dlp", default="")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--simulate-delay-ms", type=int, default=0)
    return parser


def configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    configure_utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        config = json.loads(args.config_json)
        if not isinstance(config, dict):
            raise ValueError("YouTube 실행 설정 JSON은 객체여야 합니다.")
        if args.simulate:
            return simulate_youtube_execution(
                args.url,
                args.output,
                delay_ms=args.simulate_delay_ms,
            )
        return run_youtube_execution(
            args.url,
            args.output,
            config,
            executable=args.yt_dlp,
        )
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        classification = classify_youtube_failure(str(error))
        if "설치되어 있지" in str(error) or "실행 파일을 찾을 수" in str(error):
            classification = {"category": "dependency", "retryable": False}
        emit_event(
            {
                "event": "error",
                "provider": "youtube",
                "message": str(error),
                **classification,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
