import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { renameWithRetry, writeJsonAtomically } from './downloader_files.js';
import { imageListKey, incompleteImageList } from './downloader_image_list.js';

const IMAGE = /\.(?:jpe?g|png|gif|webp|bmp|avif)$/i;
const digest = value => createHash('sha256').update(value).digest('hex');
const stamp = file => { const value = fs.statSync(file); return { size: value.size, mtimeMs: value.mtimeMs }; };

function contained(root, ...segments) {
    const target = path.resolve(root, ...segments);
    const relative = path.relative(root, target);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Unsafe image resume path');
    for (let current = target; current !== root; current = path.dirname(current)) {
        if (fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) throw new Error('Linked image resume path');
    }
    return target;
}

function basename(value) {
    return typeof value === 'string' && value.length > 0 && path.basename(value) === value
        && !/[\\/:]/.test(value) && value !== '.' && value !== '..';
}

function normalizeImages(images) {
    if (!images.length) throw incompleteImageList('empty_list');
    return images.map((image, index) => {
        const url = new URL(image.src);
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw incompleteImageList('invalid_source');
        url.hash = '';
        if (!/^\.(?:jpe?g|png|gif|webp|bmp|avif)$/i.test(image.extension)) throw incompleteImageList('invalid_extension');
        const extension = image.extension.toLowerCase();
        return { src: url.href, extension, fileName: `${String(index).padStart(4, '0')}${extension}`,
            objectName: `${digest(url.href)}${extension}` };
    });
}

export function imageResumePaths(workRoot, episode) {
    const root = path.resolve(workRoot);
    if (fs.existsSync(root) && fs.lstatSync(root).isSymbolicLink()) throw new Error('Linked work root');
    const sourceId = String(episode.sourceId || episode.sourceUrl || '');
    if (!sourceId || !basename(episode.folderName)) throw new Error('Missing image resume episode identity');
    const directory = contained(root, '.toki-image-resume', digest(sourceId));
    return { root, sourceId, directory, objects: contained(root, directory, 'objects'),
        manifest: contained(root, directory, 'manifest.json'), episodePath: contained(root, episode.folderName) };
}

function loadManifest(paths) {
    if (!fs.existsSync(paths.manifest)) return null;
    let value;
    try { value = JSON.parse(fs.readFileSync(paths.manifest, 'utf8')); }
    catch { throw incompleteImageList('invalid_resume_manifest'); }
    if (value.version !== 1 || value.sourceId !== paths.sourceId || !Array.isArray(value.images)
        || !Array.isArray(value.published) || !['downloading', 'projecting', 'complete'].includes(value.phase))
        throw incompleteImageList('invalid_resume_manifest');
    const normalized = normalizeImages(value.images);
    if (normalized.some((item, index) => item.objectName !== value.images[index].objectName
        || item.fileName !== value.images[index].fileName)) throw incompleteImageList('invalid_resume_paths');
    if (value.published.some(item => !basename(item.fileName) || !IMAGE.test(item.fileName)
        || typeof item.src !== 'string' || !Number.isFinite(item.size) || !Number.isFinite(item.mtimeMs)))
        throw incompleteImageList('invalid_published_paths');
    return value;
}

async function copyAtomically(source, target) {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    const temporary = `${target}.${randomUUID()}.tmp`;
    try {
        fs.copyFileSync(source, temporary, fs.constants.COPYFILE_EXCL);
        const descriptor = fs.openSync(temporary, 'r+');
        try { fs.fsyncSync(descriptor); } finally { fs.closeSync(descriptor); }
        await renameWithRetry(temporary, target);
    } finally {
        try { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
        catch { /* Keep an owned temporary rather than hide the original I/O failure. */ }
    }
}

// The ledger is committed BEFORE network tasks. Each object is an atomically
// written image addressed by its full source URL, never by its position.
// Old raw files stay untouched until every expected object is available.
export async function downloadEpisodeImages(workRoot, episode, images, {
    validateFile, saveImage, runTasks, concurrency = 5, report = () => {}, log = () => {},
    verifyList = null, copyFile = copyAtomically, writeManifest = writeJsonAtomically,
} = {}) {
    const paths = imageResumePaths(workRoot, episode);
    const old = loadManifest(paths);
    const items = normalizeImages(images);
    const existing = fs.existsSync(paths.episodePath)
        ? fs.readdirSync(paths.episodePath, { withFileTypes: true }).filter(item => item.isFile() && IMAGE.test(item.name)) : [];
    const oldMinimum = Math.max(old?.images.length || 0, old?.published.length || 0,
        ...existing.map(item => {
            const index = item.name.match(/^(\d{4,})\.[^.]+$/) || item.name.match(/image(\d{4,})\.[^.]+$/i);
            return index ? Number(index[1]) + 1 : 0;
        }));
    if (items.length < oldMinimum) throw incompleteImageList('list_shrank', { previousCount: oldMinimum, count: items.length });
    const oldObjects = new Set((old?.images || []).map(item => item.objectName));
    const published = new Map((old?.published || []).map(item => [item.src, item]));
    const groups = new Map();
    for (const [index, item] of items.entries()) {
        if (!groups.has(item.objectName)) groups.set(item.objectName, { item, indexes: [] });
        groups.get(item.objectName).indexes.push(index);
    }
    fs.mkdirSync(paths.objects, { recursive: true });
    let reused = 0;
    const ready = new Set();
    const matchesPublished = item => {
        const file = contained(paths.root, paths.episodePath, item.fileName);
        if (!fs.existsSync(file) || !validateFile(file)) return false;
        const current = stamp(file);
        return current.size === item.size && current.mtimeMs === item.mtimeMs;
    };
    if (old?.phase === 'complete' && imageListKey(old.images) === imageListKey(items)
        && old.published.length === items.length
        && items.every((item, index) => old.published[index].src === item.src
            && old.published[index].fileName === item.fileName && matchesPublished(old.published[index]))
        && existing.length === items.length) {
        if (verifyList && imageListKey(normalizeImages(await verifyList())) !== imageListKey(items))
            throw incompleteImageList('list_changed_during_download');
        for (let index = 0; index < items.length; index++) report(index, true);
        log(`이미지 대응표: ${items.length}장 모두 원본·파일 일치(추가 복사 없음)`);
        return { imageCount: items.length, reused: items.length, downloaded: 0, backupPath: '' };
    }
    for (const { item, indexes } of groups.values()) {
        const object = contained(paths.root, paths.objects, item.objectName);
        if (oldObjects.has(item.objectName) && validateFile(object)) {
            ready.add(item.objectName);
        } else {
            const previous = published.get(item.src);
            if (previous && matchesPublished(previous)) {
                await copyFile(contained(paths.root, paths.episodePath, previous.fileName), object);
                ready.add(item.objectName);
            }
        }
        if (ready.has(item.objectName)) reused += indexes.length;
    }
    const ledger = { version: 1, sourceId: paths.sourceId, phase: 'downloading',
        images: items, published: old?.published || [], updatedAt: new Date().toISOString() };
    await writeManifest(paths.manifest, ledger);
    log(`이미지 대응표: ${items.length}장 · 원본 일치 재사용 ${reused}장 · ${old ? '이전 대응표 비교' : '최초 대응표 생성(번호만으로 재사용 안 함)'}`);
    const tasks = [];
    for (const { item, indexes } of groups.values()) {
        if (ready.has(item.objectName)) {
            for (const index of indexes) report(index, true);
        } else tasks.push(async () => {
            await saveImage(paths.objects, item.objectName, item.src);
            for (const index of indexes) report(index, false);
        });
    }
    await runTasks(tasks, concurrency);
    for (const { item } of groups.values()) {
        if (!validateFile(contained(paths.root, paths.objects, item.objectName)))
            throw incompleteImageList('saved_image_missing', { fileName: item.fileName });
    }
    if (verifyList && imageListKey(normalizeImages(await verifyList())) !== imageListKey(items))
        throw incompleteImageList('list_changed_during_download');
    ledger.phase = 'projecting';
    await writeManifest(paths.manifest, ledger);
    fs.mkdirSync(paths.episodePath, { recursive: true });
    const unchanged = new Set();
    for (const item of items) {
        const previous = published.get(item.src);
        if (previous?.fileName === item.fileName && matchesPublished(previous)) unchanged.add(item.fileName);
    }
    // Reversible quarantine, outside chapter discovery and ZIP input. Never
    // overwrite or delete an old user image to make room for a changed order.
    let backupPath = '';
    for (const entry of fs.readdirSync(paths.episodePath, { withFileTypes: true })) {
        if (!IMAGE.test(entry.name) || unchanged.has(entry.name)) continue;
        const source = contained(paths.root, paths.episodePath, entry.name);
        if (!entry.isFile()) throw new Error('Non-file image destination');
        if (!backupPath) {
            backupPath = contained(paths.root, '.toki-trash', 'image-resume', `${digest(paths.sourceId).slice(0, 16)}-${randomUUID()}`);
            fs.mkdirSync(backupPath, { recursive: true });
        }
        await renameWithRetry(source, contained(paths.root, backupPath, entry.name));
    }
    if (backupPath) log(`이전 회차 이미지 보존: ${backupPath}`);
    for (const item of items) {
        const target = contained(paths.root, paths.episodePath, item.fileName);
        if (!unchanged.has(item.fileName)) {
            if (fs.existsSync(target)) throw incompleteImageList('destination_changed_during_resume', { fileName: item.fileName });
            await copyFile(contained(paths.root, paths.objects, item.objectName), target);
        } else if (!matchesPublished(published.get(item.src))) {
            throw incompleteImageList('file_changed_during_resume', { fileName: item.fileName });
        }
        if (!validateFile(target)) throw incompleteImageList('published_image_invalid', { fileName: item.fileName });
    }
    ledger.phase = 'complete';
    ledger.published = items.map(item => ({ src: item.src, fileName: item.fileName,
        ...stamp(contained(paths.root, paths.episodePath, item.fileName)) }));
    await writeManifest(paths.manifest, ledger);
    // Only our named staging objects; originals now exist at their final paths.
    for (const objectName of new Set([...oldObjects, ...items.map(item => item.objectName)])) {
        try { fs.unlinkSync(contained(paths.root, paths.objects, objectName)); }
        catch (error) { if (error.code !== 'ENOENT') log(`이미지 임시 파일 정리 보류: ${error.message}`); }
    }
    return { imageCount: items.length, reused, downloaded: items.length - reused, backupPath };
}
