"""Read-only catalog for ZIP-only episodes (also consumed by the Node worker)."""
import json
import copy
import zipfile
from pathlib import Path


def remap_archive_catalog(root: Path, mappings: list[dict]) -> dict | None:
    """Prepare a read-only catalog remap for the folder rename transaction."""
    directory = root / "_archives"
    path = directory / ".toki-archive-index.json"
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or path.is_symlink():
        raise ValueError("링크로 연결된 ZIP 카탈로그는 변경하지 않습니다.")
    if not path.exists():
        return None
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, dict):
        raise ValueError("ZIP 카탈로그 형식이 올바르지 않습니다.")
    folders = {m["sourceFolderName"]: m["destinationFolderName"] for m in mappings}
    by_id = {m["sourceId"]: m for m in mappings if m["sourceId"]}
    result = copy.deepcopy(records)
    for record in result.values():
        if not isinstance(record, dict):
            continue
        for episode in record.get("episodes") or ([record["episode"]] if record.get("episode") else []):
            matching = by_id.get(episode.get("sourceId"))
            if matching:
                episode.update(folderName=matching["folderName"], displayTitle=matching["displayTitle"], number=matching["number"])
            elif episode.get("folderName") in folders:
                episode["folderName"] = folders[episode["folderName"]]
        for source in record.get("sources", []):
            parts = str(source.get("source", "")).replace("\\", "/").split("/")
            if len(parts) > 1 and parts[0] in folders:
                source["source"] = "/".join([folders[parts[0]], *parts[1:]])
    return result


def archived_episodes(root: Path, *, verify_crc: bool = False) -> list[dict]:
    directory = root / "_archives"
    index = directory / ".toki-archive-index.json"
    result = []
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or index.is_symlink():
        return result
    try:
        records = json.loads(index.read_text(encoding="utf-8"))
        if not isinstance(records, dict):
            return result
    except (OSError, ValueError):
        return result
    for name, record in records.items():
        try:
            if Path(name).name != name or not name.endswith(".zip") or not isinstance(record, dict):
                continue
            path = directory / name
            stat = path.stat()
            episodes = record.get("episodes") or ([record["episode"]] if record.get("episode") else [])
            if (not episodes or path.is_symlink() or stat.st_size != record["size"]
                    or stat.st_mtime_ns != int(record["mtimeNs"])):
                continue
            with zipfile.ZipFile(path) as bundle:
                if not bundle.infolist() or (verify_crc and bundle.testzip() is not None):
                    continue
                prefixes = set(entry.filename.split("/", 1)[0] + "/" for entry in bundle.infolist() if not entry.is_dir())
            for episode in episodes:
                if not isinstance(episode, dict) or Path(episode["folderName"]).name != episode["folderName"] or int(episode["number"]) <= 0:
                    continue
                if record.get("episodes") and (not episode.get("prefix") or episode["prefix"] not in prefixes):
                    continue
                result.append({**episode, "archivePath": str(path), "imageCount": episode.get("imageCount", record.get("imageCount", 0))})
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
            continue
    # A migrated work may retain legacy ZIPs. Prefer the work ZIP and expose
    # each stable episode once, so counts and completion do not double.
    unique = {}
    for episode in sorted(result, key=lambda item: bool(item.get("prefix"))):
        unique[episode.get("sourceId") or episode["folderName"]] = episode
    return list(unique.values())
