"""Non-recursive cleanup of empty, completed, catalog-backed chapter folders."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

import toki_core as core
import toki_library as lib
from toki_archive_catalog import archived_episodes


def _token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _stamp(path):
    stat = path.lstat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def _check_guards(root, guards):
    if lib._is_link(root) or root.resolve() != root:
        raise ValueError("작품 경로가 변경됐습니다. 폴더를 보존합니다.")
    for raw, expected in guards.items():
        if _stamp(lib._contained(Path(raw), root)) != expected:
            raise ValueError("상태/ZIP/정리 대상이 변경됐습니다. 다시 미리보기 해주세요.")


def _plan_root(root):
    state_path = lib._contained(root / ".toki-state.json", root)
    index_path = lib._contained(root / "_archives/.toki-archive-index.json", root)
    plan = {"targets": [], "guards": {}, "preservedFolderCount": 0, "warnings": []}
    if not state_path.is_file() or not index_path.is_file():
        return plan
    guards = {str(p): _stamp(p) for p in (state_path, index_path)}
    state = core.load_episode_state_manifest(root)
    # Stable identity + explicit completion are required; never guess by title.
    if not state.valid or state.version < 2 or not state.completed_ids_present:
        return plan
    pending = json.loads(state_path.read_text(encoding="utf-8")).get("pendingEpisodes", [])
    if not isinstance(pending, list) or any(not isinstance(p, dict) for p in pending):
        return plan
    pending_ids = {p.get("sourceId") for p in pending}
    pending_names = {str(p.get("folderName", "")).casefold() for p in pending}
    archived = {e.get("sourceId"): e for e in archived_episodes(root)}
    catalog = json.loads(index_path.read_text(encoding="utf-8"))
    ids = Counter(e.source_id for e in state.episodes)
    names = Counter(e.folder_name.casefold() for e in state.episodes)
    for episode in state.episodes:
        name = episode.folder_name
        if not name or name.startswith((".", "_")) or Path(name).name != name:
            continue
        folder = root / name
        archive = archived.get(episode.source_id)
        if (not episode.record_valid or ids[episode.source_id] != 1 or names[name.casefold()] != 1
                or episode.source_id not in state.completed_ids or episode.source_id in pending_ids
                or name.casefold() in pending_names or not archive
                or archive["folderName"] != name or archive.get("imageCount", 0) <= 0):
            if folder.is_dir():
                plan["preservedFolderCount"] += 1
            continue
        try:
            lib._contained(folder, root)
            if not folder.is_dir():
                continue
            with os.scandir(folder) as entries:
                if next(entries, None) is not None:
                    plan["preservedFolderCount"] += 1
                    continue
            archive_path = lib._contained(Path(archive["archivePath"]), root)
            archive_stamp = _stamp(archive_path)
            record = catalog[archive_path.name]
            if archive_stamp[2:] != [record["size"], int(record["mtimeNs"])]:
                raise ValueError("계획 수집 도중 ZIP이 변경됐습니다. 폴더를 보존합니다.")
            guards[str(archive_path)] = archive_stamp
            guards[str(folder)] = _stamp(folder)
            plan["targets"].append(str(folder))
        except (OSError, ValueError) as error:
            plan["warnings"].append({"path": str(folder), "message": str(error)})
    _check_guards(root, guards)
    plan["targets"].sort()
    plan["guards"] = guards
    return plan


def _set_readonly(path, enabled):
    """Change only FILE_ATTRIBUTE_READONLY, preserving OneDrive attributes."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.SetFileAttributesW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    api.SetFileAttributesW.restype = wintypes.BOOL
    flags = path.lstat().st_file_attributes
    changed = flags | 1 if enabled else flags & ~1
    if flags == changed:
        return False
    if not api.SetFileAttributesW(str(path), changed):
        raise ctypes.WinError(ctypes.get_last_error())
    return True


def _remove_empty(root, folder, guard):
    cleared = False
    try:
        for attempt in range(3):
            guard()
            lib._contained(folder, root)
            # Never use recursive deletion: a new child makes rmdir fail safely.
            with os.scandir(folder) as entries:
                if next(entries, None) is not None:
                    raise ValueError("파일/하위 폴더가 남아 있어 보존합니다.")
            try:
                folder.rmdir()
                return
            except PermissionError:
                if attempt == 2:
                    raise
                guard()
                # Recheck emptiness before changing an exact target's attribute.
                with os.scandir(folder) as entries:
                    if next(entries, None) is not None:
                        raise ValueError("정리 도중 파일이 생겨 폴더를 보존합니다.")
                changed = _set_readonly(folder, False)
                cleared = changed or cleared
                # A cleared readonly bit can be retried immediately; avoid a
                # per-folder delay when thousands of OneDrive folders remain.
                if not changed:
                    time.sleep(0.05 * (attempt + 1))
    except Exception:
        if cleared:
            # Best-effort restore, but never touch a substituted folder/link.
            try:
                guard()
                _set_readonly(folder, True)
            except (OSError, ValueError):
                pass
        raise


def cleanup_root(root, plan=None):
    """Caller holds the work lock. No ZIP CRC rescan; no file deletion."""
    plan = plan if plan is not None else _plan_root(root)
    warnings = list(plan["warnings"])
    removed = 0
    guards = dict(plan["guards"])
    # Do not check already removed targets; retain state and archive guards.
    folder_guards = {raw: guards.pop(raw) for raw in plan["targets"]}
    for raw in plan["targets"]:
        try:
            check = lambda: _check_guards(root, {**guards, raw: folder_guards[raw]})
            _remove_empty(root, Path(raw), check)
            removed += 1
        except (OSError, ValueError) as error:
            warnings.append({"path": raw, "message": str(error)})
    return {"removedFolderCount": removed, "cleanupWarningCount": len(warnings), "cleanupWarnings": warnings}


def cleanup_empty_episode_folders(job_ids, *, execute=False, plan_token=None):
    jobs = lib._jobs(job_ids)
    roots = [lib._safe_root(job) for job in jobs]
    for index, root in enumerate(roots):
        if any(root == p or root in p.parents or p in root.parents for p in roots[:index]):
            raise ValueError("저장 폴더가 겹치는 작품은 함께 정리할 수 없습니다.")
    plans = [{"jobId": job.job_id, "title": job.title, "outputPath": str(root), **_plan_root(root)}
             for job, root in zip(jobs, roots)]
    token = _token(plans)
    count = sum(len(p["targets"]) for p in plans)
    public = [{k: v for k, v in p.items() if k != "guards"} for p in plans]
    result = {"kind": "empty-folders", "executed": False, "jobCount": len(plans), "jobs": public,
              "folderCount": count, "planToken": token, "canExecute": bool(count), "preservesFiles": True}
    if not execute:
        return result
    if plan_token and token != plan_token:
        raise ValueError("정리 대상이 변경됐습니다. 다시 미리보기 해주세요.")
    results = []
    for job, root, plan in zip(jobs, roots, plans):
        try:
            with lib._lock(root):
                if lib._safe_root(lib._jobs([job.job_id])[0]) != root:
                    raise ValueError("작품 경로가 변경됐습니다.")
                current = _plan_root(root)
                if any(current[k] != plan[k] for k in current):
                    raise ValueError("정리 대상이 변경됐습니다. 다시 미리보기 해주세요.")
                report = cleanup_root(root, current)
                results.append({"jobId": job.job_id, "success": not report["cleanupWarningCount"], **report})
        except (OSError, ValueError) as error:
            results.append({"jobId": job.job_id, "success": False, "error": str(error)})
    return {**result, "executed": True, "success": all(r["success"] for r in results), "results": results,
            "removedFolderCount": sum(r.get("removedFolderCount", 0) for r in results),
            "cleanupWarningCount": sum(r.get("cleanupWarningCount", 0) for r in results)}
