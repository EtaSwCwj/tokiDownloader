from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from toki_core import DOWNLOADER_PATH, LOG_DIR, ROOT_DIR, find_node


SELF_TEST_REPORT_PATH = LOG_DIR / "self-test.json"


@dataclass
class SelfTestCheck:
    name: str
    ok: bool
    duration_ms: int
    detail: str
    data: dict[str, Any] | None = None


def _run_check(name: str, callback: Callable[[], Any]) -> SelfTestCheck:
    started = time.perf_counter()
    try:
        value = callback()
        detail = "통과"
        data: dict[str, Any] | None = None
        if isinstance(value, dict):
            data = value
            detail = str(value.get("detail") or detail)
        elif value not in (None, True):
            detail = str(value)
        ok = not isinstance(value, dict) or bool(value.get("ok", True))
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {error}"
        data = None
    duration_ms = round((time.perf_counter() - started) * 1000)
    return SelfTestCheck(name, ok, duration_ms, detail, data)


def _check_required_files() -> dict[str, Any]:
    required = [
        ROOT_DIR / "toki_app.py",
        ROOT_DIR / "toki_core.py",
        ROOT_DIR / "toki_gui.py",
        ROOT_DIR / "down.js",
        ROOT_DIR / "downloader_policy.js",
        ROOT_DIR / "downloader_errors.js",
        ROOT_DIR / "tokiDownloader.js",
        ROOT_DIR / "package.json",
        ROOT_DIR / "requirements-image-tools.txt",
        ROOT_DIR / "start-gui.cmd",
        ROOT_DIR / "toki-cli.cmd",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("필수 파일 누락: " + ", ".join(missing))
    return {"detail": f"필수 파일 {len(required)}개 확인", "files": len(required)}


def _check_python_syntax() -> dict[str, Any]:
    files = [
        ROOT_DIR / "toki_app.py",
        ROOT_DIR / "toki_core.py",
        ROOT_DIR / "toki_gui.py",
        ROOT_DIR / "toki_selftest.py",
    ]
    for path in files:
        py_compile.compile(str(path), doraise=True)
    return {"detail": f"Python 파일 {len(files)}개 컴파일", "files": len(files)}


def _check_node_syntax() -> dict[str, Any]:
    node = find_node()
    version = subprocess.run(
        [node, "--version"],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=15,
    ).stdout.strip()
    files = [
        DOWNLOADER_PATH,
        ROOT_DIR / "downloader_policy.js",
        ROOT_DIR / "downloader_errors.js",
        ROOT_DIR / "tokiDownloader.js",
    ]
    for path in files:
        completed = subprocess.run(
            [node, "--check", str(path)],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        if completed.returncode:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"{path.name} 구문 오류: {message}")
    return {"detail": f"Node {version}, JavaScript 파일 {len(files)}개 구문 확인"}


def _check_node_tests() -> dict[str, Any]:
    completed = subprocess.run(
        [
            find_node(),
            "--test",
            str(ROOT_DIR / "tests" / "downloader_policy.test.js"),
            str(ROOT_DIR / "tests" / "downloader_errors.test.js"),
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode:
        raise RuntimeError(output or f"종료 코드 {completed.returncode}")
    return {"detail": "다운로더 JavaScript 테스트 7건 통과", "tests": 7}


def _check_unit_tests() -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(ROOT_DIR / "tests"),
            "-v",
        ],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=90,
    )
    combined = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    if completed.returncode:
        raise RuntimeError(combined or f"종료 코드 {completed.returncode}")
    summary = next(
        (line.strip() for line in reversed(combined.splitlines()) if line.strip().startswith("Ran ")),
        "단위 테스트 통과",
    )
    return {"detail": summary, "output": combined[-4000:]}


def run_self_test(
    gui_probe: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started_wall = datetime.now().astimezone().isoformat(timespec="seconds")
    started = time.perf_counter()
    checks = [
        _run_check("required_files", _check_required_files),
        _run_check("python_syntax", _check_python_syntax),
        _run_check("node_syntax", _check_node_syntax),
        _run_check("node_tests", _check_node_tests),
        _run_check("unit_tests", _check_unit_tests),
    ]
    if gui_probe is not None:
        checks.append(_run_check("gui_ipc", gui_probe))

    passed = sum(check.ok for check in checks)
    result = {
        "ok": passed == len(checks),
        "startedAt": started_wall,
        "durationMs": round((time.perf_counter() - started) * 1000),
        "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks)},
        "checks": [asdict(check) for check in checks],
        "reportPath": str(SELF_TEST_REPORT_PATH),
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SELF_TEST_REPORT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result
