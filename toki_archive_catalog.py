"""Read-only catalog for ZIP-only episodes (also consumed by the Node worker)."""
import json
import zipfile
from pathlib import Path


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
