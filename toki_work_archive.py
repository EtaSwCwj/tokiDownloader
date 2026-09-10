"""One streamed, verified ZIP per work; archived-only chapters survive updates."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import toki_core as core
import toki_library as lib
from toki_archive_catalog import archived_episodes
from toki_reading_order import assign_reading_order


def _sort(value):
    return [(0, int(s)) if s.isdigit() else (1, s.casefold()) for s in re.split(r"(\d+)", str(value))]


def _key(episode):
    return episode.get("sourceId") or episode["folderName"]


def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _safe_member(name):
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or any(s in {"..", "."} or ":" in s for s in path.parts):
        raise ValueError(f"안전하지 않은 ZIP 내부 경로: {name}")
    return name


def _raw_member(path, root, cleanup=True):
    size, mtime = _stamp(path)
    return {"path": str(path), "source": path.relative_to(root).as_posix(),
            "size": size, "mtimeNs": mtime, "cleanup": cleanup}


def _existing_chapters(root):
    # The catalog reader opens each archive once, not once per chapter.
    episodes = archived_episodes(root)
    grouped = {}
    for episode in episodes:
        grouped.setdefault(episode["archivePath"], []).append(episode)
    result = {}
    index_path = root / "_archives/.toki-archive-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if grouped else {}
    # Whole-work archives take precedence over legacy chapter ZIPs.
    for archive_path, entries in sorted(grouped.items(), key=lambda item: bool(index[Path(item[0]).name].get("episodes"))):
        archive = lib._contained(Path(archive_path), root)
        record = index[archive.name]
        sources = record.get("sources", [])
        known = {s.get("member", f"{i:06d}{Path(s['source']).suffix.lower()}"): s for i, s in enumerate(sources, 1)}
        stamp = list(_stamp(archive))
        with zipfile.ZipFile(archive) as bundle:
            infos = {entry.filename: entry for entry in bundle.infolist() if not entry.is_dir()}
            by_prefix = {}
            for name, info in infos.items():
                by_prefix.setdefault(name.split("/", 1)[0] + "/", []).append(info)
            for episode in entries:
                prefix = episode.get("prefix", "")
                members = by_prefix.get(prefix, []) if prefix else list(infos.values())
                media = sorted((m for m in members if Path(m.filename).suffix.lower() in lib.MEDIA_EXTENSIONS), key=lambda m: _sort(m.filename))
                if not media:
                    continue
                saved = []
                for info in media:
                    _safe_member(info.filename)
                    source = known.get(info.filename, {})
                    saved.append({"archive": str(archive), "archiveStamp": stamp,
                        "archiveMember": info.filename, "source": source.get("source", ""),
                        "size": info.file_size, "mtimeNs": source.get("mtimeNs", 0),
                        "crc": info.CRC, "cleanup": False})
                result[_key(episode)] = {"episode": {k: v for k, v in episode.items() if k not in {"archivePath", "prefix", "imageCount"}},
                                         "members": saved, "raw": []}
    return result


def plan_work_archives(job_ids, *, include_members=False):
    jobs = lib._jobs(job_ids)
    roots = [lib._safe_root(job) for job in jobs]
    for i, root in enumerate(roots):
        if any(root == other or root in other.parents or other in root.parents for other in roots[:i]):
            raise ValueError("저장 폴더가 같거나 상하위로 겹치는 작품은 함께 처리할 수 없습니다.")
    plans = []
    for job, root in zip(jobs, roots):
        chapters = _existing_chapters(root)
        archived_count = len(chapters)
        state = core.load_episode_state_manifest(root)
        if state.valid:
            # A later full rescan can insert older chapters and renumber rows.
            # Match by source ID, never retain a stale ZIP-only ordinal.
            for record in state.episodes:
                previous = chapters.get(record.source_id) if record.source_id else None
                if previous and record.record_valid:
                    previous["episode"].update(number=record.number, folderName=record.folder_name,
                                               sourceTitle=record.source_title, displayTitle=record.display_title)
        incomplete = []
        for folder in core.discover_episode_folders(root, state):
            lib._contained(folder.path, root)
            files = sorted((p for p in lib._files(folder.path) if p.suffix.lower() in lib.MEDIA_EXTENSIONS), key=lambda p: _sort(p.relative_to(folder.path)))
            if not files:
                continue
            complete = state.valid and (folder.source_id in state.completed_ids
                if state.version >= 2 and state.completed_ids_present and folder.source_id else folder.number in state.completed_numbers)
            if not complete:
                incomplete.append(folder.folder_name)
                continue
            episode = {"number": folder.number, "sourceId": folder.source_id,
                       "sourceTitle": folder.source_title or folder.folder_name, "folderName": folder.folder_name,
                       "displayTitle": folder.display_title or folder.folder_name}
            raw = [_raw_member(p, root) for p in files]
            previous = chapters.get(_key(episode))
            if previous:
                known = {m["source"].replace("\\", "/"): (m["size"], int(m["mtimeNs"])) for m in previous["members"]}
                unchanged = all(known.get(m["source"]) == (m["size"], m["mtimeNs"]) for m in raw)
                if unchanged:
                    previous["raw"] = raw
                    previous["episode"] = episode
                    continue
                if len(raw) < len(previous["members"]):
                    raise ValueError(f"원본 일부만 남은 회차에 변경 파일이 있습니다. 기존 ZIP을 보존합니다: {folder.folder_name}")
            chapters[_key(episode)] = {"episode": episode, "members": raw, "raw": raw}
        if not chapters:
            raise ValueError(f"완료 기록이 확인되는 압축 대상이 없습니다: {job.title} (미완료/확인 불가 {len(incomplete)}회차)")
        metadata = core._episode_rename_json(root / 'metadata.json', label='metadata.json')
        work_title = core._episode_rename_work_title(job, metadata, root)
        catalog = [{"number": r.number, "sourceId": r.source_id, "sourceTitle": r.source_title,
                    "displayTitle": r.display_title, "folderName": r.folder_name,
                    "numberInferred": r.number_inferred} for r in state.episodes if r.record_valid]
        known = {_key(r) for r in catalog}
        catalog.extend(c['episode'] for k, c in chapters.items() if k not in known)
        reading = {_key(r): r for r in assign_reading_order(catalog, work_title)}
        for key, chapter in chapters.items():
            for field in ('readingOrder', 'readingOrderVersion', 'readingGroup', 'readingOrderWarning'):
                chapter['episode'][field] = reading[key][field]
        members, episodes, cleanup = [], [], []
        for chapter in sorted(chapters.values(), key=lambda c: c['episode']['readingOrder']):
            order = chapter['episode']['readingOrder']
            # A padded prefix guarantees order even in viewers using lexical sort.
            title = core.sanitize_windows_path_segment(chapter['episode'].get('displayTitle') or chapter['episode']['folderName'], '회차')
            prefix = f"{order:06d} {title}/"
            _safe_member(prefix)
            for number, source in enumerate(chapter["members"], 1):
                extension = Path(source.get("path") or source["archiveMember"]).suffix.lower()
                members.append({**source, "name": f"{prefix}{number:06d}{extension}"})
            episodes.append({**chapter["episode"], "prefix": prefix,
                             "imageCount": sum(Path(m["name"]).suffix.lower() in core.IMAGE_EXTENSIONS for m in members[-len(chapter["members"]):])})
            cleanup.extend(chapter["raw"])
        # Metadata/cover remain outside too: GUI and later rescans need them.
        for path in sorted(root.iterdir()):
            if path.is_file() and (path.name in {"metadata.json", ".toki-state.json"} or path.stem == "cover" and path.suffix.lower() in core.IMAGE_EXTENSIONS):
                lib._contained(path, root)
                members.append({**_raw_member(path, root, False), "name": path.name})
        signature = {"episodes": episodes, "members": [{k: m[k] for k in ("name", "source", "size", "mtimeNs")} for m in members]}
        fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        destination = lib._contained(root / "_archives" / (root.name + ".zip"), root)
        archive = {"path": str(destination), "fileCount": len(members), "episodeCount": len(episodes), "fingerprint": fingerprint,
                   **({"members": members, "episodes": episodes, "cleanup": cleanup} if include_members else {})}
        plans.append({"jobId": job.job_id, "title": job.title, "outputPath": str(root), "archives": [archive],
                      "alreadyArchived": archived_count, "incompleteCount": len(incomplete), "incompleteFolders": incomplete[:100]})
    return {"mode": "work", "executed": False, "jobs": plans, "jobCount": len(plans), "archiveCount": len(plans),
            "fileCount": sum(p["archives"][0]["fileCount"] for p in plans), "preservesOriginals": True}


def _check_raw(member, root):
    path = lib._contained(Path(member["path"]), root)
    if _stamp(path) != (member["size"], member["mtimeNs"]):
        raise ValueError(f"압축/정리 도중 원본이 변경됐습니다: {path}")
    return path


def _write_bundle(temporary, archive, root, cancelled):
    source_zip, source_path = None, None
    try:
        with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as bundle:
            bundle.writestr(".toki-work.json", json.dumps({"version": 2, "episodes": archive["episodes"]}, ensure_ascii=False))
            for member in archive["members"]:
                if cancelled():
                    raise InterruptedError("압축이 취소되었습니다.")
                if member.get("archive"):
                    path = lib._contained(Path(member["archive"]), root)
                    if list(_stamp(path)) != member["archiveStamp"]:
                        raise ValueError(f"기존 ZIP이 변경됐습니다: {path}")
                    if source_path != path:
                        if source_zip:
                            source_zip.close()
                        source_zip, source_path = zipfile.ZipFile(path), path
                    reader = source_zip.open(member["archiveMember"])
                else:
                    reader = _check_raw(member, root).open("rb")
                with reader, bundle.open(member["name"], "w", force_zip64=True) as writer:
                    while chunk := reader.read(1024 * 1024):
                        if cancelled():
                            raise InterruptedError("압축이 취소되었습니다.")
                        writer.write(chunk)
                if member.get("path"):
                    _check_raw(member, root)
        with zipfile.ZipFile(temporary) as bundle:
            if bundle.testzip() is not None:
                raise ValueError("생성한 ZIP의 CRC 검증에 실패했습니다.")
        for path, stamp in {m["archive"]: m["archiveStamp"] for m in archive["members"] if m.get("archive")}.items():
            if list(_stamp(lib._contained(Path(path), root))) != stamp:
                raise ValueError(f"압축 중 원본 ZIP이 변경됐습니다: {path}")
    finally:
        if source_zip:
            source_zip.close()


def archive_works(job_ids, *, execute, remove_originals, cancelled, progress):
    plan = {**plan_work_archives(job_ids), "removeOriginals": remove_originals, "preservesOriginals": not remove_originals}
    if not execute:
        return plan
    created = skipped = removed = 0
    results = []
    for item in plan["jobs"]:
        try:
            root = lib._safe_root(lib._jobs([item["jobId"]])[0])
            with lib._lock(root):
                if cancelled():
                    raise InterruptedError("압축이 취소되었습니다.")
                archive = plan_work_archives([item["jobId"]], include_members=True)["jobs"][0]["archives"][0]
                target = lib._contained(Path(archive["path"]), root)
                target.parent.mkdir(exist_ok=True)
                index_path = lib._contained(target.parent / ".toki-archive-index.json", root)
                index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
                old = index.get(target.name, {})
                if target.exists() and (not old or _stamp(target) != (old.get("size"), int(old.get("mtimeNs", 0)))):
                    raise ValueError(f"앱 기록이 없거나 외부에서 변경된 ZIP은 덮어쓰지 않습니다: {target}")
                unchanged = target.exists() and old.get("fingerprint") == archive["fingerprint"]
                if unchanged:
                    if remove_originals:
                        with zipfile.ZipFile(target) as bundle:
                            if bundle.testzip() is not None:
                                raise ValueError("기존 ZIP 검증 실패")
                    skipped += 1
                else:
                    temporary = target.with_name(f".toki-{uuid.uuid4().hex}.tmp")
                    backup = target.with_name(f".toki-{uuid.uuid4().hex}.previous")
                    published = False
                    try:
                        _write_bundle(temporary, archive, root, cancelled)
                        if cancelled():
                            raise InterruptedError("압축이 취소되었습니다.")
                        if target.exists():
                            if _stamp(target) != (old.get("size"), int(old.get("mtimeNs", 0))):
                                raise ValueError("압축 중 기존 ZIP이 변경됐습니다. 보존합니다.")
                            os.replace(target, backup)
                        os.replace(temporary, target)
                        published = True
                        index[target.name] = {"mode": "work", "fingerprint": archive["fingerprint"],
                            "size": target.stat().st_size, "mtimeNs": str(target.stat().st_mtime_ns), "episodes": archive["episodes"],
                            "sources": [{"source": m["source"], "member": m["name"], "size": m["size"], "mtimeNs": m["mtimeNs"]} for m in archive["members"]]}
                        lib._write_json(index_path, index)
                    except Exception:
                        if backup.exists():
                            os.replace(backup, target)
                        elif published:
                            target.unlink()
                        raise
                    finally:
                        temporary.unlink(missing_ok=True)
                    backup.unlink(missing_ok=True)
                    created += 1
                if remove_originals:
                    # All raw pages must still match; never delete metadata/cover.
                    expected_stamp = (index[target.name]["size"], int(index[target.name]["mtimeNs"]))
                    for member in archive["cleanup"]:
                        _check_raw(member, root)
                    for member in archive["cleanup"]:
                        if cancelled():
                            raise InterruptedError("원본 정리가 취소되었습니다. 검증된 ZIP과 남은 원본을 보존합니다.")
                        if _stamp(target) != expected_stamp:
                            raise ValueError("원본 정리 중 ZIP이 변경됐습니다. 남은 원본을 보존합니다.")
                        source = _check_raw(member, root)
                        source.unlink()
                        removed += 1
                    for folder in {Path(m["path"]).parent for m in archive["cleanup"]}:
                        lib._contained(folder, root)
                        if folder.is_dir() and not any(folder.iterdir()):
                            folder.rmdir()
                progress({"jobId": item["jobId"], "archive": target.name, "createdCount": created})
                results.append({"jobId": item["jobId"], "success": True, "archivePath": str(target)})
        except Exception as error:
            results.append({"jobId": item["jobId"], "success": False, "error": str(error)})
            if cancelled():
                break
    return {**plan, "executed": True, "success": len(results) == len(plan["jobs"]) and all(r["success"] for r in results),
            "cancelled": cancelled(), "createdCount": created, "skippedCount": skipped, "removedOriginalCount": removed, "results": results}
