"""Run the real application with isolated test data and a private IPC endpoint."""
import hashlib
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))
runtime = Path(sys.argv.pop(1)).resolve(strict=True)
if not (runtime / ".library-cli-test").is_file():
    raise SystemExit("Missing isolated test marker")

import toki_core as core

core.CONFIG_PATH = runtime / "config.json"
core.JOB_DB_PATH = runtime / "jobs.db"
core.LOG_DIR = runtime / "logs"
core.LOG_PATH = core.LOG_DIR / "gui.log"
core.THUMBNAIL_CACHE_DIR = runtime / "thumbnails"
core.CONTROL_SERVER_NAME = "tokiLibraryTest_" + hashlib.sha256(str(runtime).encode()).hexdigest()[:16]

import toki_app

raise SystemExit(toki_app.main())
