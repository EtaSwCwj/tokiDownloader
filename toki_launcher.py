"""Console-free launcher and crash evidence, independent of Qt/third-party imports."""
from __future__ import annotations

import argparse
import faulthandler
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
KEEP_FINISHED_RUNS = 20
MAX_LOG_BYTES = 2 * 1024 * 1024
_session = None


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def runtime_roots():
    roots = [ROOT / "logs" / "runtime"]
    if os.environ.get("LOCALAPPDATA"):
        roots.append(Path(os.environ["LOCALAPPDATA"]) / "tokiDownloader" / "logs" / "runtime")
    return roots


def new_run_directory(roots=None):
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:12]
    errors = []
    for root in roots if roots is not None else runtime_roots():
        try:
            directory = Path(root) / run_id
            directory.mkdir(parents=True)
            write_json(directory / "process.json", {
                "runId": run_id, "startedAt": timestamp(),
                "supervisorPid": os.getpid(), "state": "starting",
            })
            prune_finished_runs(Path(root))
            return directory
        except OSError as error:
            errors.append(str(error))
    raise OSError("Cannot create startup log: " + "; ".join(errors))


def prune_finished_runs(root, keep=KEEP_FINISHED_RUNS):
    # Only our completed run records; never recurse or remove downloads/active logs.
    finished = []
    for path in root.iterdir():
        if path.is_dir() and not path.is_symlink():
            state = read_json(path / "process.json")
            if state.get("runId") == path.name and state.get("finishedAt"):
                finished.append(path)
    for path in sorted(finished, reverse=True)[keep:]:
        try:
            for name in ("process.json", "child.json", "events.log", "events.log.1", "fault.log"):
                (path / name).unlink(missing_ok=True)
            path.rmdir()  # Leave a directory containing anything we do not own.
        except OSError:
            pass


class RuntimeSession:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.state = {"pid": os.getpid(), "phase": "python_start", "updatedAt": timestamp()}
        self.logger = logging.Logger("toki-runtime")
        self.handler = RotatingFileHandler(
            self.directory / "events.log", maxBytes=MAX_LOG_BYTES, backupCount=1,
            encoding="utf-8",
        )
        self.logger.addHandler(self.handler)
        self.event("python_start", executable=sys.executable, python=sys.version.split()[0])

    def event(self, event, **details):
        with self.lock:
            entry = {"time": timestamp(), "event": event, **details}
            self.logger.warning(json.dumps(entry, ensure_ascii=False, default=str))
            self.state.update(phase=event, updatedAt=entry["time"])
            if event in {"main_return", "python_error", "system_exit"}:
                self.state["terminal"] = event
                self.state["exitCode"] = details.get("exitCode", 1)
            if event == "close_accepted":
                self.state["close"] = details
            write_json(self.directory / "child.json", self.state)

    def close(self):
        self.handler.close()


def record_event(event, **details):
    if _session is not None:
        try:
            _session.event(event, **details)
        except Exception:
            # A full/read-only disk must not crash a running download recursively.
            pass


class LogStream:
    encoding = "utf-8"
    errors = "replace"

    def __init__(self, stream):
        self.stream = stream

    def write(self, text):
        text = str(text)
        for offset in range(0, len(text), 4096):
            record_event(self.stream, text=text[offset:offset + 4096])
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def report_exception(exc_type, exc, tb, *, source="main"):
    record_event("unhandled_exception", source=source,
                 traceback="".join(traceback.format_exception(exc_type, exc, tb))[-65536:])


def run_child(directory, callback):
    global _session
    session = RuntimeSession(directory)
    _session = session
    streams = sys.stdout, sys.stderr
    hooks = sys.excepthook, threading.excepthook, sys.unraisablehook
    fault_file = None
    try:
        sys.stdout, sys.stderr = LogStream("stdout"), LogStream("stderr")
        sys.excepthook = report_exception
        threading.excepthook = lambda args: report_exception(
            args.exc_type, args.exc_value, args.exc_traceback, source="thread")
        sys.unraisablehook = lambda args: report_exception(
            args.exc_type, args.exc_value, args.exc_traceback, source="unraisable")
        fault_file = (Path(directory) / "fault.log").open("ab", buffering=0)
        faulthandler.enable(file=fault_file, all_threads=True)
        code = int(callback() or 0)
        record_event("main_return", exitCode=code)
        return code
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (1 if error.code else 0)
        record_event("system_exit", exitCode=code)
        return code
    except BaseException:
        report_exception(*sys.exc_info())
        record_event("python_error", exitCode=1)
        return 1
    finally:
        if fault_file is not None:
            faulthandler.disable()
            fault_file.close()
        sys.stdout, sys.stderr = streams
        sys.excepthook, threading.excepthook, sys.unraisablehook = hooks
        _session = None
        session.close()


def classify_exit(code, child):
    if child.get("terminal") == "python_error":
        return "python_error"
    if child.get("terminal") in {"main_return", "system_exit"}:
        if code == 0 and child.get("exitCode") == 0:
            return "normal_exit"
        return "error_exit"
    # Includes os._exit(0): exit code alone cannot prove a clean shutdown.
    return "unexpected_exit"


def supervise(directory, command):
    path = Path(directory) / "process.json"
    state = read_json(path)
    try:
        child = subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        state.update(childPid=child.pid, state="running")
        write_json(path, state)
        code = child.wait()  # OS wait, not a polling loop or GUI thread.
        child_state = read_json(Path(directory) / "child.json")
        state.update(state=classify_exit(code, child_state), exitCode=code,
                     pythonPid=child_state.get("pid"),
                     exitCodeHex=f"0x{code & 0xFFFFFFFF:08X}")
    except OSError as error:
        state.update(state="launch_error", error=str(error), exitCode=1)
        code = 1
    state["finishedAt"] = timestamp()
    write_json(path, state)
    return code


def runtime_status(roots=None, limit=20):
    reports = []
    for root in roots if roots is not None else runtime_roots():
        if not Path(root).is_dir():
            continue
        for path in Path(root).glob("*/process.json"):
            state = read_json(path)
            if state:
                state.update(logDirectory=str(path.parent), child=read_json(path.parent / "child.json"))
                # Without a finished record the monitor may still be running,
                # or both processes may have stopped (power loss, reboot, kill).
                state["exitObserved"] = bool(state.get("finishedAt"))
                reports.append(state)
    reports.sort(key=lambda item: item.get("runId", ""), reverse=True)
    return {"ok": True, "roots": [str(p) for p in (roots if roots is not None else runtime_roots())],
            "runs": reports[:limit], "retainedFinishedRuns": KEEP_FINISHED_RUNS,
            "unobservedNote": "No finishedAt means running or unobserved termination; not proof of a crash."}


def taskbar_shortcuts(repair=False):
    if os.name != "nt":
        return {"ok": False, "error": "Windows only"}
    completed = subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(ROOT / "scripts" / "repair-taskbar-shortcut.ps1"),
        *(["-Repair"] if repair else []),
    ], capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    result = json.loads(completed.stdout)
    if repair:
        from toki_windows_launch import notify_shortcut_changed
        for shortcut in result.get("shortcuts", []):
            if not shortcut.get("needsRepair"):
                notify_shortcut_changed(shortcut["path"])
    return result


def launch_command():
    python = Path(sys.executable)
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    return [str(pythonw if pythonw.is_file() else python), str(ROOT / "toki_launcher.py"), "launch"]


def _gui_main():
    record_event("import_gui")
    import toki_app
    sys.argv = [str(ROOT / "toki_app.py"), "gui"]
    return toki_app.main()


def main(argv=None):
    parser = argparse.ArgumentParser(description="tokiDownloader silent launcher / startup diagnostics")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("launch")
    commands.add_parser("status").add_argument("--json", action="store_true")
    shortcuts = commands.add_parser("taskbar")
    shortcuts.add_argument("--repair", action="store_true")
    shortcuts.add_argument("--json", action="store_true")
    child = commands.add_parser("_child")
    child.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    if args.command == "_child":
        return run_child(args.directory, _gui_main)
    if args.command == "launch":
        directory = new_run_directory()
        command = launch_command()[:2] + ["_child", str(directory)]
        return supervise(directory, command)
    result = taskbar_shortcuts(args.repair) if args.command == "taskbar" else runtime_status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    # Imported GUI modules must share the event sink initialized by this entry point.
    sys.modules["toki_launcher"] = sys.modules[__name__]
    raise SystemExit(main())
