"""Batch library operations. No GUI dependency; destructive choices are explicit."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import zipfile
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import toki_core as core
from toki_archive_catalog import archived_episodes

ARCHIVE_EXTENSIONS = {".zip", ".cbz", ".7z", ".cb7", ".rar", ".cbr"}
MEDIA_EXTENSIONS = core.IMAGE_EXTENSIONS | {".txt", ".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".flac", ".wav", ".srt", ".vtt"}
DELETE_KINDS = {"records", "files", "archives"}


def _jobs(job_ids: list[str]) -> list[core.DownloadJob]:
    ids = list(dict.fromkeys(str(value).strip() for value in job_ids if str(value).strip()))
    if not ids:
        raise ValueError("작품을 하나 이상 선택해주세요.")
    jobs = []
    for job_id in ids:
        job = core.load_job_by_id(job_id)
        if job is None:
            raise ValueError(f"작품 기록이 없습니다: {job_id}")
        if job.state in core.ACTIVE_JOB_STATES:
            raise ValueError(f"먼저 다운로드를 취소해주세요: {job.title}")
        jobs.append(job)
    return jobs


def _safe_root(job: core.DownloadJob) -> Path:
    if not job.output_path:
        raise ValueError(f"다운로드 폴더가 없습니다: {job.title}")
    raw = Path(job.output_path).absolute()
    root = raw.resolve()
    forbidden = {Path(root.anchor), Path.home().resolve(), core.ROOT_DIR.resolve(), Path(job.output_dir).resolve()}
    if root in forbidden or any(root == p or root in p.parents for p in (Path.home().resolve(), core.ROOT_DIR.resolve())):
        raise ValueError(f"작품 전용 폴더가 아닌 경로는 처리할 수 없습니다: {root}")
    if raw != root or _is_link(raw) or not root.is_dir():
        raise ValueError(f"실제 작품 폴더만 처리할 수 있습니다(링크/없는 경로 제외): {raw}")
    return root


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _contained(path: Path, root: Path) -> Path:
    if path == root or not path.is_relative_to(root):
        raise ValueError(f"작품 폴더 밖의 대상입니다: {path}")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if _is_link(parent):
            raise ValueError(f"링크 경로는 처리하지 않습니다: {parent}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"작품 폴더 밖으로 연결된 대상입니다: {path}")
    return path


def _files(root: Path) -> list[Path]:
    result = []
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d != ".toki-trash" and not _is_link(Path(current) / d))
        for name in sorted(files):
            path = Path(current) / name
            if not _is_link(path):
                result.append(_contained(path, root))
    return result


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(root: Path):
    lock = _contained(root / ".toki-library.lock", root)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        try:
            owner = json.loads(lock.read_text(encoding="utf-8"))
            stale = not core.psutil.pid_exists(int(owner["pid"]))
        except (OSError, ValueError, KeyError):
            stale = False
        if not stale:
            raise ValueError(f"다른 압축/삭제 작업의 잠금이 있습니다: {lock}") from error
        lock.unlink()
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid()}, handle)
        yield
    finally:
        lock.unlink(missing_ok=True)


def plan_library_delete(job_ids: list[str], kind: str, *, include_targets: bool = False) -> dict:
    if kind not in DELETE_KINDS:
        raise ValueError("삭제 종류는 records, files, archives 중 하나여야 합니다.")
    jobs = _jobs(job_ids)
    plans = []
    seen_roots = set()
    for job in jobs:
        targets = []
        root = None
        if kind != "records":
            root = _safe_root(job)
            if any(root == seen or root in seen.parents or seen in root.parents for seen in seen_roots):
                raise ValueError("저장 폴더가 같거나 상하위로 겹치는 작품은 함께 처리할 수 없습니다.")
            seen_roots.add(root)
            for path in _files(root):
                relative = path.relative_to(root)
                if kind == "archives" and path.suffix.lower() in ARCHIVE_EXTENSIONS:
                    targets.append(path)
                elif kind == "files" and "_archives" not in relative.parts and path.suffix.lower() in MEDIA_EXTENSIONS:
                    targets.append(path)
        item = {
            "jobId": job.job_id, "title": job.title, "outputPath": str(root or job.output_path),
            "fileCount": len(targets), "bytes": sum(p.stat().st_size for p in targets),
            "targets": [str(p) for p in targets],
            "stamps": {str(p): [p.stat().st_size, p.stat().st_mtime_ns] for p in targets},
        }
        item["targetToken"] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        if not include_targets:
            item.pop("stamps")
            item["targets"] = item["targets"][:100]
        plans.append(item)
    token = hashlib.sha256(json.dumps([item["targetToken"] for item in plans]).encode()).hexdigest()
    return {"kind": kind, "executed": False, "jobCount": len(jobs), "jobs": plans, "planToken": token,
            "fileCount": sum(p["fileCount"] for p in plans), "bytes": sum(p["bytes"] for p in plans),
            "destination": "app-trash" if kind != "records" else "records-only"}


def delete_library_items(job_ids: list[str], kind: str, *, execute: bool = False, plan_token: str | None = None) -> dict:
    plan = plan_library_delete(job_ids, kind)
    if execute and plan_token and plan_token != plan["planToken"]:
        raise ValueError("미리보기 이후 대상이 변경됐습니다. 다시 미리보기를 확인해주세요.")
    if not execute:
        return plan
    results = []
    for item in plan["jobs"]:
        try:
            if kind == "records":
                core.delete_job_record(item["jobId"])
                results.append({"jobId": item["jobId"], "success": True, "removedRecord": True})
                continue
            current = plan_library_delete([item["jobId"]], kind, include_targets=True)["jobs"][0]
            if current["targetToken"] != item["targetToken"]:
                raise ValueError("삭제 미리보기 이후 작품 파일이 변경됐습니다.")
            item = current
            job = _jobs([item["jobId"]])[0]
            root = _safe_root(job)
            with _lock(root):
                trash_root = _contained(root / ".toki-trash", root)
                trash_root.mkdir(exist_ok=True)
                trash = trash_root / uuid.uuid4().hex
                trash.mkdir()
                manifest = {"version": 1, "jobId": job.job_id, "root": str(root), "kind": kind,
                            "entries": [], "restored": False}
                manifest_path = trash / "manifest.json"
                # Publish the complete recovery map before the first move.
                for index, raw in enumerate(item["targets"]):
                    source = _contained(Path(raw), root)
                    manifest["entries"].append({"source": str(source.relative_to(root)), "stored": str(index)})
                _write_json(manifest_path, manifest)
                try:
                    for entry in manifest["entries"]:
                        source = _contained(root / entry["source"], root)
                        if [source.stat().st_size, source.stat().st_mtime_ns] != item["stamps"][str(source)]:
                            raise ValueError(f"삭제 계획 이후 파일이 변경됐습니다: {source}")
                        os.rename(source, trash / entry["stored"])
                    if kind == "files" and manifest["entries"]:
                        state = root / ".toki-state.json"
                        if state.is_file():
                            _contained(state, root)
                            payload = json.loads(state.read_text(encoding="utf-8"))
                            shutil.copy2(state, trash / "state-before.json")
                            kept = archived_episodes(root)
                            kept_numbers = {int(item["number"]) for item in kept}
                            kept_ids = {item.get("sourceId") for item in kept}
                            payload["completedEpisodes"] = [n for n in payload.get("completedEpisodes", []) if n in kept_numbers]
                            payload["completedEpisodeIds"] = [s for s in payload.get("completedEpisodeIds", []) if s in kept_ids]
                            _write_json(state, payload)
                        job.state = "중지됨"
                        job.progress = 0
                        core.save_jobs([job])
                except Exception:
                    # Best-effort rollback; the journal remains if recovery is interrupted.
                    for entry in reversed(manifest["entries"]):
                        saved = trash / entry["stored"]
                        source = _contained(root / entry["source"], root)
                        if saved.exists() and not source.exists():
                            os.rename(saved, source)
                    backup = trash / "state-before.json"
                    if backup.exists():
                        shutil.copy2(backup, root / ".toki-state.json")
                    raise
                results.append({"jobId": job.job_id, "success": True, "movedCount": len(manifest["entries"]),
                                "trashManifest": str(manifest_path)})
        except Exception as error:
            results.append({"jobId": item["jobId"], "success": False, "error": str(error)})
    return {**plan, "executed": True, "results": results, "success": all(p["success"] for p in results)}


def restore_library_trash(manifest_path: str, *, execute: bool = False) -> dict:
    path = Path(manifest_path).absolute()
    if path.name != "manifest.json" or path.parent.parent.name != ".toki-trash":
        raise ValueError("앱 휴지통 manifest.json을 선택해주세요.")
    root = path.parent.parent.parent
    payload = json.loads(_contained(path, root).read_text(encoding="utf-8"))
    job = _jobs([payload["jobId"]])[0]
    if _safe_root(job) != root or payload.get("root") != str(root):
        raise ValueError("휴지통과 현재 작품 폴더가 다릅니다.")
    entries = []
    for item in payload.get("entries", []):
        if not str(item["stored"]).isdigit():
            raise ValueError("잘못된 휴지통 저장 경로입니다.")
        source = _contained(root / item["source"], root)
        saved = _contained(path.parent / item["stored"], root)
        if saved.exists():
            if source.exists():
                raise ValueError(f"복구 대상에 파일이 있습니다. 덮어쓰지 않습니다: {source}")
            entries.append((saved, source))
    if execute:
        with _lock(root):
            for saved, source in entries:
                _contained(source, root)
                if source.exists():
                    raise ValueError(f"복구 대상 충돌: {source}")
                source.parent.mkdir(parents=True, exist_ok=True)
                os.rename(saved, source)
            payload["restored"] = True
            _write_json(path, payload)
            # Completion state is intentionally not restored over newer downloads.
    return {"executed": execute, "fileCount": len(entries), "manifest": str(path), "preservesNewerState": True}


def plan_library_archive(job_ids: list[str], mode: str = "episodes", *, include_members: bool = False) -> dict:
    if mode not in {"episodes", "work"}:
        raise ValueError("압축 단위는 episodes 또는 work여야 합니다.")
    plans = []
    seen_roots = set()
    for job in _jobs(job_ids):
        root = _safe_root(job)
        if any(root == seen or root in seen.parents or seen in root.parents for seen in seen_roots):
            raise ValueError("저장 폴더가 같거나 상하위로 겹치는 작품은 함께 처리할 수 없습니다.")
        seen_roots.add(root)
        output = _contained(root / "_archives", root)
        candidates = []
        incomplete = []
        if mode == "episodes":
            state = core.load_episode_state_manifest(root)
            for folder in core.discover_episode_folders(root, state):
                _contained(folder.path, root)
                files = [p for p in _files(folder.path) if p.suffix.lower() in MEDIA_EXTENSIONS]
                complete = state.valid and (
                    folder.source_id in state.completed_ids
                    if state.version >= 2 and state.completed_ids_present and folder.source_id
                    else folder.number in state.completed_numbers
                )
                if files and not complete:
                    incomplete.append(folder.folder_name)
                    continue
                if files:
                    candidates.append((folder.folder_name, folder.path, files, {
                        "number": folder.number, "sourceId": folder.source_id,
                        "sourceTitle": folder.source_title or folder.folder_name,
                        "folderName": folder.folder_name,
                    }))
        else:
            files = [p for p in _files(root) if not any(part in {"_archives", "_converted", "_pdf"} for part in p.relative_to(root).parts)
                     and (p.suffix.lower() in MEDIA_EXTENSIONS or p.name == "metadata.json")]
            if any(p.suffix.lower() in MEDIA_EXTENSIONS for p in files):
                candidates.append((root.name, root, files, None))
        archives = []
        for name, base, files, episode in candidates:
            destination = _contained(output / (name + ".zip"), root)
            files.sort(key=lambda p: [(0, int(s)) if s.isdigit() else (1, s.casefold()) for s in re.split(r"(\d+)", p.relative_to(base).as_posix())])
            members = [{"path": str(p), "name": f"{index:06d}{p.suffix.lower()}" if episode else p.relative_to(base).as_posix(),
                        "size": p.stat().st_size, "mtimeNs": p.stat().st_mtime_ns} for index, p in enumerate(files, 1)]
            fingerprint = hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()
            archives.append({"path": str(destination), "fileCount": len(members),
                             **({"members": members} if include_members else {}),
                             "fingerprint": fingerprint, "episode": episode})
        archived_count = len(archived_episodes(root))
        if not archives and not archived_count:
            raise ValueError(f"완료 기록이 확인되는 압축 대상이 없습니다: {job.title} (미완료/확인 불가 {len(incomplete)}회차)")
        plans.append({"jobId": job.job_id, "title": job.title, "outputPath": str(root), "archives": archives,
                      "alreadyArchived": archived_count, "incompleteCount": len(incomplete), "incompleteFolders": incomplete[:100]})
    return {"mode": mode, "executed": False, "jobs": plans, "jobCount": len(plans),
            "archiveCount": sum(len(p["archives"]) for p in plans),
            "fileCount": sum(a["fileCount"] for p in plans for a in p["archives"]), "preservesOriginals": True}


def archive_library_items(job_ids: list[str], mode: str = "episodes", *, execute: bool = False,
                          remove_originals: bool = False,
                          cancelled: Callable[[], bool] = lambda: False,
                          progress: Callable[[dict], None] = lambda _event: None) -> dict:
    if remove_originals and mode != "episodes":
        raise ValueError("원본 정리는 회차별 ZIP에서만 지원합니다.")
    plan = {**plan_library_archive(job_ids, mode), "removeOriginals": remove_originals,
            "preservesOriginals": not remove_originals}
    if not execute:
        return plan
    created = skipped = removed = 0
    results = []
    for item in plan["jobs"]:
        try:
            root = _safe_root(_jobs([item["jobId"]])[0])
            with _lock(root):
                item = plan_library_archive([item["jobId"]], mode, include_members=True)["jobs"][0]
                output = _contained(root / "_archives", root)
                output.mkdir(exist_ok=True)
                index_path = _contained(output / ".toki-archive-index.json", root)
                index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
                for archive in item["archives"]:
                    if cancelled():
                        return {**plan, "executed": True, "success": False, "cancelled": True,
                                "createdCount": created, "skippedCount": skipped, "removedOriginalCount": removed, "results": results}
                    target = _contained(Path(archive["path"]), root)
                    old = index.get(target.name, {})
                    if target.exists() and not old:
                        raise ValueError(f"앱이 만든 기록이 없는 압축 파일은 덮어쓰지 않습니다: {target}")
                    if target.exists() and (old.get("size") != target.stat().st_size or int(old.get("mtimeNs", 0)) != target.stat().st_mtime_ns):
                        raise ValueError(f"기존 ZIP이 외부에서 변경됐습니다. 보존합니다: {target}")
                    old_sources = old.get("sources", [])
                    if target.exists() and old_sources and any(not (root / m["source"]).exists() for m in old_sources):
                        # Never replace a complete ZIP with a partial set of raw pages
                        # after cleanup was interrupted or a page was re-downloaded.
                        known = {m["source"]: (m["size"], m["mtimeNs"]) for m in old_sources}
                        for member in archive["members"]:
                            relative = str(Path(member["path"]).relative_to(root))
                            if known.get(relative) != (member["size"], member["mtimeNs"]):
                                raise ValueError(f"원본 일부만 남은 회차에 변경 파일이 있습니다. 기존 ZIP을 보존합니다: {target}")
                        with zipfile.ZipFile(target) as bundle:
                            if bundle.testzip() is not None:
                                raise ValueError(f"기존 ZIP 검증 실패: {target}")
                        if remove_originals:
                            for member in archive["members"]:
                                source = _contained(Path(member["path"]), root)
                                if (source.stat().st_size, source.stat().st_mtime_ns) != (member["size"], member["mtimeNs"]):
                                    raise ValueError(f"정리 도중 원본 변경: {source}")
                                source.unlink()
                                removed += 1
                        skipped += 1
                        continue
                    if target.exists() and old.get("fingerprint") == archive["fingerprint"] and old.get("size") == target.stat().st_size and int(old.get("mtimeNs", 0)) == target.stat().st_mtime_ns and not remove_originals:
                        skipped += 1
                        continue
                    temporary = _contained(output / f".toki-{uuid.uuid4().hex}.tmp", root)
                    try:
                        with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
                            if archive["episode"]:
                                bundle.writestr(".toki-episode.json", json.dumps(archive["episode"], ensure_ascii=False))
                            for member in archive["members"]:
                                source = _contained(Path(member["path"]), root)
                                before = source.stat()
                                if before.st_size != member["size"] or before.st_mtime_ns != member["mtimeNs"]:
                                    raise ValueError(f"압축 계획 이후 원본이 변경됐습니다: {source}")
                                with source.open("rb") as reader, bundle.open(member["name"], "w", force_zip64=True) as writer:
                                    while chunk := reader.read(1024 * 1024):
                                        if cancelled():
                                            raise InterruptedError("압축이 취소되었습니다.")
                                        writer.write(chunk)
                                after = source.stat()
                                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                                    raise ValueError(f"압축 도중 원본이 변경됐습니다: {source}")
                        with zipfile.ZipFile(temporary) as bundle:
                            if bundle.testzip() is not None:
                                raise ValueError("생성한 ZIP의 CRC 검증에 실패했습니다.")
                        os.replace(temporary, target)
                        index[target.name] = {"fingerprint": archive["fingerprint"], "size": target.stat().st_size,
                                              "mtimeNs": str(target.stat().st_mtime_ns), "episode": archive["episode"],
                                              "sources": [{"source": str(Path(m["path"]).relative_to(root)), "size": m["size"], "mtimeNs": m["mtimeNs"]} for m in archive["members"]],
                                              "imageCount": sum(Path(m["path"]).suffix.lower() in core.IMAGE_EXTENSIONS for m in archive["members"])}
                        _write_json(index_path, index)
                        if remove_originals:
                            # The verified archive and durable catalog must exist first.
                            # Each source is checked again; never delete a changed file.
                            for member in archive["members"]:
                                source = _contained(Path(member["path"]), root)
                                stat = source.stat()
                                if (stat.st_size, stat.st_mtime_ns) != (member["size"], member["mtimeNs"]):
                                    raise ValueError(f"원본이 변경되어 정리를 중단했습니다: {source}")
                            for member in archive["members"]:
                                source = _contained(Path(member["path"]), root)
                                stat = source.stat()
                                if (stat.st_size, stat.st_mtime_ns) != (member["size"], member["mtimeNs"]):
                                    raise ValueError(f"원본이 변경되어 정리를 중단했습니다: {source}")
                                source.unlink()
                                removed += 1
                            folder = _contained(root / archive["episode"]["folderName"], root)
                            if folder.is_dir() and not any(folder.iterdir()):
                                folder.rmdir()
                        created += 1
                        progress({"jobId": item["jobId"], "archive": target.name, "createdCount": created})
                    finally:
                        temporary.unlink(missing_ok=True)
                results.append({"jobId": item["jobId"], "success": True})
        except Exception as error:
            results.append({"jobId": item["jobId"], "success": False, "error": str(error)})
    return {**plan, "executed": True, "success": all(p["success"] for p in results),
            "cancelled": cancelled(), "createdCount": created, "skippedCount": skipped,
            "removedOriginalCount": removed, "results": results}
