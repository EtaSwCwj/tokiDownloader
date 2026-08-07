import { episodeSourceId } from './downloader_naming.js';
import {
    ERROR_CATEGORIES,
    createDownloaderError,
} from './downloader_errors.js';

const IMAGE_EXTENSION_FORMATS = Object.freeze({
    '.avif': 'avif',
    '.bmp': 'bmp',
    '.gif': 'gif',
    '.jpeg': 'jpeg',
    '.jpg': 'jpeg',
    '.png': 'png',
    '.webp': 'webp',
});

function ascii(bytes, start, end) {
    return String.fromCharCode(...bytes.subarray(start, end));
}

function asBuffer(value) {
    if (Buffer.isBuffer(value))
        return value;
    if (value instanceof Uint8Array)
        return Buffer.from(value.buffer, value.byteOffset, value.byteLength);
    return Buffer.alloc(0);
}

export function detectImageFormat(value) {
    const bytes = asBuffer(value);
    if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff)
        return 'jpeg';
    if (
        bytes.length >= 8
        && bytes[0] === 0x89
        && ascii(bytes, 1, 4) === 'PNG'
        && bytes[4] === 0x0d
        && bytes[5] === 0x0a
        && bytes[6] === 0x1a
        && bytes[7] === 0x0a
    )
        return 'png';
    if (bytes.length >= 6 && ['GIF87a', 'GIF89a'].includes(ascii(bytes, 0, 6)))
        return 'gif';
    if (
        bytes.length >= 12
        && ascii(bytes, 0, 4) === 'RIFF'
        && ascii(bytes, 8, 12) === 'WEBP'
    )
        return 'webp';
    if (bytes.length >= 2 && ascii(bytes, 0, 2) === 'BM')
        return 'bmp';
    if (bytes.length >= 12 && ascii(bytes, 4, 8) === 'ftyp') {
        const declaredBoxSize = bytes.readUInt32BE(0);
        const availableBoxSize = Math.min(
            bytes.length,
            declaredBoxSize >= 16 ? declaredBoxSize : bytes.length,
            256,
        );
        const brands = [ascii(bytes, 8, 12)];
        for (let offset = 16; offset + 4 <= availableBoxSize; offset += 4)
            brands.push(ascii(bytes, offset, offset + 4));
        if (brands.some(brand => brand === 'avif' || brand === 'avis'))
            return 'avif';
    }
    return '';
}

export function validateImageBuffer(
    value,
    extension = '',
    { tail = null, totalSize = null } = {},
) {
    const bytes = asBuffer(value);
    const ending = tail === null
        ? bytes.subarray(Math.max(0, bytes.length - 16))
        : asBuffer(tail);
    const declaredSize = Number(totalSize);
    const size = totalSize !== null
        && totalSize !== undefined
        && Number.isSafeInteger(declaredSize)
        && declaredSize >= 0
        ? declaredSize
        : bytes.byteLength;
    const normalizedExtension = String(extension || '').trim().toLowerCase();
    const expectedFormat = IMAGE_EXTENSION_FORMATS[normalizedExtension] || '';
    const detectedFormat = size > 0 ? detectImageFormat(value) : '';
    let reason = '';
    if (size <= 0)
        reason = 'empty_image';
    else if (!expectedFormat)
        reason = 'unsupported_extension';
    else if (!detectedFormat)
        reason = 'invalid_signature';
    else if (detectedFormat !== expectedFormat)
        reason = 'extension_signature_mismatch';
    else if (
        detectedFormat === 'jpeg'
        && !(ending.length >= 2 && ending.at(-2) === 0xff && ending.at(-1) === 0xd9)
    )
        reason = 'missing_end_marker';
    else if (
        detectedFormat === 'png'
        && !ending.includes(Buffer.from('IEND', 'ascii'))
    )
        reason = 'missing_end_marker';
    return {
        valid: !reason,
        reason,
        size,
        extension: normalizedExtension,
        expectedFormat,
        detectedFormat,
    };
}

export function requireEpisodeImages(images, context = {}) {
    if (Array.isArray(images) && images.length > 0)
        return images;
    throw createDownloaderError(
        '회차 페이지에서 저장할 이미지를 하나도 확인하지 못했습니다. '
        + '완료 처리하지 않고 중단합니다.',
        {
            errorCode: 'empty_episode_images',
            category: ERROR_CATEGORIES.SITE_STRUCTURE,
            retryable: false,
            diagnostics: {
                episodeNumber: Number(context.episodeNumber) || null,
                sourceId: String(context.sourceId || ''),
                sourceUrl: String(context.sourceUrl || ''),
            },
            suggestion: '사이트 뷰어 DOM과 이미지 선택자를 확인하세요.',
        },
    );
}

export function normalizeAndSortEpisodeLinks(links) {
    const valid = [];
    const skipped = [];
    for (const item of links || []) {
        const rawNumber = String(item?.num ?? '').trim();
        const number = Number(rawNumber);
        if (!/^\d+$/.test(rawNumber) || !Number.isSafeInteger(number) || number <= 0) {
            skipped.push({ ...item, reason: 'invalid_episode_number', rawNumber });
            continue;
        }
        const sourceUrl = String(item?.src || item?.sourceUrl || '').trim();
        let parsedUrl;
        try {
            parsedUrl = new URL(sourceUrl);
        }
        catch (_error) {
            parsedUrl = null;
        }
        if (!parsedUrl || !['http:', 'https:'].includes(parsedUrl.protocol)) {
            skipped.push({
                ...item,
                reason: 'invalid_episode_url',
                rawNumber,
                sourceUrl,
            });
            continue;
        }
        valid.push({
            ...item,
            num: String(number).padStart(4, '0'),
            src: sourceUrl,
            sourceId: episodeSourceId(sourceUrl),
        });
    }
    valid.sort((left, right) => (
        Number(left.num) - Number(right.num)
        || String(left.src || '').localeCompare(String(right.src || ''))
    ));
    const unique = [];
    const seenSourceIds = new Set();
    for (const item of valid) {
        if (seenSourceIds.has(item.sourceId)) {
            skipped.push({ ...item, reason: 'duplicate_episode_source' });
            continue;
        }
        seenSourceIds.add(item.sourceId);
        unique.push(item);
    }
    return { links: unique, skipped };
}

export function episodeStateUsesStableIds(state) {
    const completedNumbers = new Set(
        (Array.isArray(state?.completedEpisodes) ? state.completedEpisodes : [])
            .map(Number)
            .filter(number => Number.isSafeInteger(number) && number > 0),
    );
    if (Number(state?.version) === 1 && state?.completedEpisodeIdsPresent === false)
        return false;
    if ((Array.isArray(state?.completedEpisodeIds) ? state.completedEpisodeIds : [])
        .some(value => String(value || '').trim()))
        return true;
    return (Array.isArray(state?.episodes) ? state.episodes : []).some(item => (
        item
        && String(item.sourceId || '').trim()
        && completedNumbers.has(Number(item.number))
    ));
}

export function resolveEpisodeCompletion(
    state,
    links,
    { physicalNumbers = new Set(), physicalEpisodeIds = new Set() } = {},
) {
    const requestedNumbers = state?.exists
        ? new Set(state.completedEpisodes || [])
        : physicalNumbers;
    const completedEpisodes = new Set(
        [...requestedNumbers].filter(number => physicalNumbers.has(number)),
    );
    const requestedIds = new Set(state?.completedEpisodeIds || []);
    const completedEpisodeIds = new Set(
        [...(state?.exists ? requestedIds : physicalEpisodeIds)]
            .filter(sourceId => physicalEpisodeIds.has(sourceId)),
    );
    const preferEpisodeIds = episodeStateUsesStableIds(state);
    const completedEpisodeFallbacks = new Set();
    for (const item of links || []) {
        const number = Number.parseInt(item?.num);
        const sourceId = String(item?.sourceId || item?.episode?.sourceId || '').trim();
        if (!item?.storageExists || !Number.isSafeInteger(number) || number <= 0)
            continue;
        if (sourceId && (completedEpisodeIds.has(sourceId) || requestedIds.has(sourceId))) {
            completedEpisodes.add(number);
            completedEpisodeIds.add(sourceId);
        }
        else if (
            completedEpisodes.has(number)
            && (
                (preferEpisodeIds && !sourceId)
                || (!preferEpisodeIds && (!sourceId || item.numericFallbackVerified === true))
            )
        ) {
            if (sourceId)
                completedEpisodeIds.add(sourceId);
            else
                completedEpisodeFallbacks.add(number);
        }
    }
    return { completedEpisodes, completedEpisodeIds, completedEpisodeFallbacks };
}

export function selectEpisodeLinks(
    links,
    { metadataOnly = false, scanMode = 'full', startIndex = 0, lastIndex = 99999,
        completedEpisodes = new Set(), completedEpisodeIds = new Set(),
        completedEpisodeFallbacks = null, preferEpisodeIds = false } = {}
) {
    if (metadataOnly)
        return { links: [], skippedExistingEpisodes: 0 };
    if (scanMode === 'new') {
        const selected = links.filter(item => {
            const sourceId = String(item.sourceId || item.episode?.sourceId || '');
            const completedById = sourceId && completedEpisodeIds.has(sourceId);
            const completedByNumber = completedEpisodes.has(parseInt(item.num));
            const hasVerifiedFallbacks = completedEpisodeFallbacks instanceof Set;
            const safeNumberFallback = hasVerifiedFallbacks
                && completedEpisodeFallbacks.has(parseInt(item.num))
                && (!preferEpisodeIds || !sourceId);
            return !(
                completedById
                || safeNumberFallback
                || (!preferEpisodeIds && !hasVerifiedFallbacks && completedByNumber)
            );
        });
        return {
            links: selected,
            skippedExistingEpisodes: links.length - selected.length
        };
    }
    if (scanMode === 'range') {
        return {
            links: links.filter(item => {
                const episodeNumber = parseInt(item.num);
                return startIndex <= episodeNumber && episodeNumber <= lastIndex;
            }),
            skippedExistingEpisodes: 0
        };
    }
    return { links: [...links], skippedExistingEpisodes: 0 };
}
