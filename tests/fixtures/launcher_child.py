"""Isolated fault-injection child. Never points at production config/IPC/clipboard."""
import os
from pathlib import Path
import runpy
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from toki_launcher import run_child

directory = Path(sys.argv[1])
mode = sys.argv[2]


def callback():
    if mode == "error":
        raise RuntimeError("fixture startup import failure")
    if mode.startswith("exit-"):
        os._exit(int(mode[5:]))
    if mode == "thread":
        def fail():
            raise ValueError("fixture thread exception")
        thread = threading.Thread(target=fail)
        thread.start()
        thread.join()
    if mode == "output":
        print("fixture stdout")
        print("fixture stderr", file=sys.stderr)
    if mode == "wait":
        import time
        time.sleep(120)  # Parent test terminates this private child, not the real GUI.
    if mode == "gui":
        runtime = Path(sys.argv[3]).resolve(strict=True)
        if not (runtime / ".library-cli-test").is_file():
            raise RuntimeError("Missing private GUI marker")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        sys.argv = [str(Path(__file__).with_name("library_cli_host.py")), str(runtime), "gui"]
        runpy.run_path(sys.argv[0], run_name="__main__")
    return 0


raise SystemExit(run_child(directory, callback))
