import fs from 'node:fs';
import path from 'node:path';
import { episodeSourceTitlesMatch } from './downloader_naming.js';

// Loaded catalog arrays are read-only. Index once per scan, not once per episode.
const lookupCache = new WeakMap();

export function loadArchivedEpisodes(root) {
    const directory = path.join(root, '_archives');
    const result = [];
    try {
        if (fs.lstatSync(directory).isSymbolicLink()) return result;
        const records = JSON.parse(fs.readFileSync(path.join(directory, '.toki-archive-index.json'), 'utf8'));
        for (const [name, value] of Object.entries(records)) {
            try {
                const episodes = value?.episodes || (value?.episode ? [value.episode] : []);
                if (path.basename(name) !== name || !name.endsWith('.zip') || !episodes.length) continue;
                const archive = path.join(directory, name);
                const stat = fs.lstatSync(archive, { bigint: true });
                if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== BigInt(value.size)
                    || stat.mtimeNs !== BigInt(value.mtimeNs)) continue;
                // EOCD presence rejects incomplete writes without loading a whole ZIP.
                const fd = fs.openSync(archive, 'r');
                let tail;
                try {
                    const length = Math.min(Number(stat.size), 65557);
                    tail = Buffer.alloc(length);
                    fs.readSync(fd, tail, 0, length, Number(stat.size) - length);
                    const end = tail.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
                    if (end < 0 || end + 22 > tail.length || end + 22 + tail.readUInt16LE(end + 20) !== tail.length) continue;
                    let count = tail.readUInt16LE(end + 10);
                    let centralSize = tail.readUInt32LE(end + 12);
                    let centralOffset = tail.readUInt32LE(end + 16);
                    if (count === 0xffff || centralSize === 0xffffffff || centralOffset === 0xffffffff) {
                        // Whole-work ZIPs can exceed 4 GiB or 65,535 images.
                        if (end < 20 || tail.readUInt32LE(end - 20) !== 0x07064b50) continue;
                        const offset = Number(tail.readBigUInt64LE(end - 12));
                        if (!Number.isSafeInteger(offset) || offset < 0 || offset + 56 > Number(stat.size)) continue;
                        const zip64 = Buffer.alloc(56);
                        if (fs.readSync(fd, zip64, 0, 56, offset) !== 56 || zip64.readUInt32LE(0) !== 0x06064b50) continue;
                        count = Number(zip64.readBigUInt64LE(32));
                        centralSize = Number(zip64.readBigUInt64LE(40));
                        centralOffset = Number(zip64.readBigUInt64LE(48));
                        if (![count, centralSize, centralOffset].every(Number.isSafeInteger)) continue;
                    }
                    if (!count || centralOffset + centralSize > Number(stat.size) - 22 || centralSize < 46) continue;
                    const signature = Buffer.alloc(4);
                    fs.readSync(fd, signature, 0, 4, centralOffset);
                    if (!signature.equals(Buffer.from([0x50, 0x4b, 0x01, 0x02]))) continue;
                } finally { fs.closeSync(fd); }
                result.push(...episodes.filter(episode => episode && Number(episode.number) > 0
                    && typeof episode.folderName === 'string' && path.basename(episode.folderName) === episode.folderName));
            } catch { /* A missing or changed ZIP is never treated as completed. */ }
        }
    } catch { /* No catalog means normal folder-based completion. */ }
    return result;
}

export function hasArchivedEpisode(archives, record) {
    let lookup = lookupCache.get(archives);
    if (!lookup) {
        lookup = { ids: new Set(), folders: new Map() };
        for (const item of archives) {
            if (item.sourceId) lookup.ids.add(item.sourceId);
            const entries = lookup.folders.get(item.folderName) || [];
            entries.push(item);
            lookup.folders.set(item.folderName, entries);
        }
        lookupCache.set(archives, lookup);
    }
    if (record.sourceId && lookup.ids.has(record.sourceId)) return true;
    return (lookup.folders.get(record.folderName) || []).some(item => (
        !(item.sourceId && record.sourceId) && episodeSourceTitlesMatch(
            item.sourceTitle, record.sourceTitle, Number(record.number),
        )
    ));
}
