import {
    ERROR_CATEGORIES,
    createDownloaderError,
} from './downloader_errors.js';

const DEFAULT_FOLDER_TEMPLATE = '[{author}][{group}] {title}';
const ALLOWED_FOLDER_FIELDS = new Set(['author', 'group', 'title', 'site', 'id']);
const WINDOWS_INVALID_PATH_CHARS = /[<>:"/\\|?*\u0000-\u001F]/;
const WINDOWS_RESERVED_NAMES = /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$/i;
const WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS = 240;
const WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS = 248;

function normalizeDisplayText(value) {
    return String(value ?? '').normalize('NFC').replace(/\s+/g, ' ').trim();
}

const LEGACY_INLINE_HTML_TAG = /<\/?(?:abbr|b|bdi|bdo|br|cite|code|data|del|dfn|em|i|img|ins|kbd|mark|q|rp|rt|ruby|s|samp|small|span|strong|sub|sup|time|u|var|wbr)\b[^<>]*>/gi;
const LEGACY_HTML_ENTITIES = Object.freeze({
    amp: '&',
    apos: "'",
    gt: '>',
    hellip: '…',
    lt: '<',
    mdash: '—',
    middot: '·',
    nbsp: '\u00a0',
    ndash: '–',
    quot: '"',
});

function decodeLegacyHtmlEntity(match, entity) {
    if (entity.startsWith('#')) {
        const hexadecimal = entity[1]?.toLowerCase() === 'x';
        const digits = entity.slice(hexadecimal ? 2 : 1);
        if (!(hexadecimal ? /^[0-9a-f]+$/i : /^\d+$/).test(digits))
            return match;
        const codePoint = Number.parseInt(digits, hexadecimal ? 16 : 10);
        if (
            !Number.isSafeInteger(codePoint)
            || codePoint <= 0
            || codePoint > 0x10ffff
            || (codePoint >= 0xd800 && codePoint <= 0xdfff)
        )
            return match;
        return String.fromCodePoint(codePoint);
    }
    return LEGACY_HTML_ENTITIES[entity.toLowerCase()] ?? match;
}

function legacyEpisodeTitleText(value) {
    // v1 persisted anchor.innerHTML.  Strip only known inline tags and decode
    // character references; unknown markup/entities remain unequal so an
    // ambiguous folder can never be reused by accident.
    return String(value ?? '')
        .replace(LEGACY_INLINE_HTML_TAG, '')
        .replace(/&(#(?:x[0-9a-f]+|\d+)|[a-z][a-z0-9]+);/gi, decodeLegacyHtmlEntity);
}

function unsafeEpisodeTitleError(workTitle, sourceTitle, episodeNumber, reason) {
    const siteOrdinal = Number.parseInt(episodeNumber);
    return createDownloaderError(
        `사이트 회차 제목에서 실제 회차명을 확인할 수 없습니다`
        + `${Number.isSafeInteger(siteOrdinal) && siteOrdinal > 0 ? ` (사이트 순번 ${siteOrdinal})` : ''}. `
        + '사이트 순번을 N화로 저장하지 않고 중단합니다.',
        {
            errorCode: 'unsafe_episode_title',
            category: ERROR_CATEGORIES.SITE_STRUCTURE,
            retryable: false,
            diagnostics: {
                reason,
                siteOrdinal: Number.isSafeInteger(siteOrdinal) && siteOrdinal > 0
                    ? siteOrdinal
                    : null,
                workTitle: normalizeDisplayText(workTitle),
                sourceTitle: normalizeDisplayText(sourceTitle),
            },
            suggestion: '사이트 목록의 회차 제목 DOM을 확인한 뒤 다시 시도하세요.',
        },
    );
}

function episodeSuffixOrThrow(value, workTitle, sourceTitle, episodeNumber, reason) {
    const suffix = trimEpisodeSeparator(value);
    if (!suffix)
        throw unsafeEpisodeTitleError(workTitle, sourceTitle, episodeNumber, reason);
    return suffix;
}

function sanitizePathSegment(value, fallback = 'N／A') {
    const sanitized = String(value ?? '')
        .replace(/[<>:"/\\|?*\u0000-\u001F]/g, '')
        .replace(/[. ]+$/g, '')
        .trim();
    const candidate = sanitized || fallback;
    return WINDOWS_RESERVED_NAMES.test(candidate) ? `_${candidate}` : candidate;
}

function validateFolderTemplate(value) {
    const template = String(value ?? '').trim();
    if (!template)
        throw new Error('작품 폴더명 템플릿을 입력해주세요.');
    if (template.length > 180)
        throw new Error('작품 폴더명 템플릿은 180자 이하여야 합니다.');

    const withoutFields = template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (_match, field) => {
        if (!ALLOWED_FOLDER_FIELDS.has(field))
            throw new Error(`지원하지 않는 폴더명 변수입니다: {${field}}`);
        return '';
    });
    if (/[{}]/.test(withoutFields))
        throw new Error('폴더명 변수는 {author}, {group}, {title}, {site}, {id} 형식으로 입력해주세요.');
    if (WINDOWS_INVALID_PATH_CHARS.test(withoutFields))
        throw new Error('폴더명 템플릿의 고정 문자에 Windows 금지 문자를 사용할 수 없습니다.');
    if (!template.includes('{title}'))
        throw new Error('작품을 구분할 수 있도록 {title} 변수가 필요합니다.');
    return template;
}

function renderFolderTemplate(value, metadata = {}) {
    const template = validateFolderTemplate(value || DEFAULT_FOLDER_TEMPLATE);
    const source = metadata.source || {};
    const values = {
        author: sanitizePathSegment(metadata.author),
        group: sanitizePathSegment(metadata.group),
        title: sanitizePathSegment(metadata.title, '제목 없음'),
        site: sanitizePathSegment(source.siteTitle || metadata.site || source.site),
        id: sanitizePathSegment(source.workId || metadata.id),
    };
    const rendered = template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (_match, field) => values[field]);
    if (!rendered || rendered.length > 240)
        throw new Error('미리보기 폴더명이 비어 있거나 Windows 안전 길이 240자를 초과합니다.');
    if (WINDOWS_INVALID_PATH_CHARS.test(rendered) || /[. ]$/.test(rendered))
        throw new Error('미리보기 폴더명이 Windows 경로 규칙에 맞지 않습니다.');
    if (WINDOWS_RESERVED_NAMES.test(rendered))
        throw new Error('Windows 예약 장치 이름은 폴더명으로 사용할 수 없습니다.');
    return rendered;
}

function episodeSourceId(sourceUrl) {
    const value = String(sourceUrl ?? '').trim();
    if (!value)
        return '';
    try {
        const pathname = new URL(value).pathname.replace(/\/+$/g, '');
        return pathname || '/';
    }
    catch (_error) {
        return value.split(/[?#]/, 1)[0].replace(/\/+$/g, '');
    }
}

function longestWorkTitleOverlap(workTitle, abbreviatedSuffix) {
    const foldedWorkTitle = workTitle.toLowerCase();
    const foldedSuffix = abbreviatedSuffix.toLowerCase();
    const maximum = Math.min(foldedWorkTitle.length, foldedSuffix.length);
    for (let length = maximum; length > 0; length--) {
        if (foldedWorkTitle.endsWith(foldedSuffix.slice(0, length)))
            return length;
    }
    return 0;
}

function trimEpisodeSeparator(value) {
    return String(value ?? '').replace(/^[\s\-–—]+|[\s\-–—]+$/g, '');
}

function repairKnownEpisodeSuffixArtifact(value, workTitle) {
    const suffix = normalizeDisplayText(value);
    const normalizedWorkTitle = sanitizePathSegment(workTitle, '');
    if (normalizedWorkTitle !== '남녀비 139의 평행세계는 의외로 평범')
        return suffix;
    const matched = suffix.match(/^(?:-18|18|8)\s+(.+\s\d+(?:\.\d+)?(?:~\d+(?:\.\d+)?)?화)$/i);
    return matched ? `R-18 ${matched[1]}` : suffix;
}

function extractEpisodeSuffix(workTitle, sourceTitle, episodeNumber = 0) {
    const work = normalizeDisplayText(workTitle);
    const source = normalizeDisplayText(sourceTitle);
    const safeWork = sanitizePathSegment(work, '');
    const safeSource = sanitizePathSegment(source, '');
    if (!source)
        throw unsafeEpisodeTitleError(work, source, episodeNumber, 'empty_source_title');
    if (!work)
        return source;
    const foldedWork = work.toLowerCase();
    const foldedSource = source.toLowerCase();
    const foldedSafeWork = safeWork.toLowerCase();
    const foldedSafeSource = safeSource.toLowerCase();
    if (foldedSource === foldedWork)
        throw unsafeEpisodeTitleError(work, source, episodeNumber, 'source_equals_work_title');
    if (safeWork && foldedSafeSource === foldedSafeWork)
        throw unsafeEpisodeTitleError(work, source, episodeNumber, 'source_equals_sanitized_work_title');
    if (foldedSource.startsWith(`${foldedWork} `))
        return episodeSuffixOrThrow(
            source.slice(work.length), work, source, episodeNumber, 'empty_title_suffix',
        );
    if (safeWork && foldedSafeSource.startsWith(`${foldedSafeWork} `))
        return episodeSuffixOrThrow(
            safeSource.slice(safeWork.length),
            work,
            source,
            episodeNumber,
            'empty_sanitized_title_suffix',
        );

    const ellipsisMatch = /…|\.{3}/.exec(source);
    if (ellipsisMatch) {
        const left = source.slice(0, ellipsisMatch.index).trimEnd();
        const right = source.slice(ellipsisMatch.index + ellipsisMatch[0].length).trimStart();
        const safeLeft = sanitizePathSegment(left, '');
        const foldedLeft = left.toLowerCase();
        const foldedSafeLeft = safeLeft.toLowerCase();
        if (right && (
            !left
            || foldedWork.startsWith(foldedLeft)
            || (safeLeft && foldedSafeWork.startsWith(foldedSafeLeft))
        )) {
            const rawOverlap = longestWorkTitleOverlap(work, right);
            if (rawOverlap)
                return episodeSuffixOrThrow(
                    right.slice(rawOverlap), work, source, episodeNumber, 'empty_ellipsis_suffix',
                );
            const safeRight = sanitizePathSegment(right, '');
            const safeOverlap = longestWorkTitleOverlap(safeWork, safeRight);
            if (safeOverlap)
                return episodeSuffixOrThrow(
                    safeRight.slice(safeOverlap),
                    work,
                    source,
                    episodeNumber,
                    'empty_sanitized_ellipsis_suffix',
                );
            return repairKnownEpisodeSuffixArtifact(right, work);
        }
    }

    return source;
}

function windowsUtf16Units(value) {
    // JavaScript string length is defined in UTF-16 code units, matching Windows.
    return String(value ?? '').length;
}

function validateEpisodeDestinationPath(folderName, destinationPath) {
    const component = String(folderName ?? '');
    const destination = String(destinationPath ?? '');
    if (!component)
        throw new Error('회차 폴더명이 비어 있습니다.');
    if (!destination)
        throw new Error('회차 폴더의 전체 목적지 경로가 비어 있습니다.');
    const componentUtf16Units = windowsUtf16Units(component);
    const destinationUtf16Units = windowsUtf16Units(destination);
    const result = {
        encoding: 'utf-16',
        componentMaxUnits: WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS,
        destinationMaxUnits: WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS,
        componentUtf16Units,
        destinationUtf16Units,
        componentTooLong: componentUtf16Units > WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS,
        absolutePathTooLong: destinationUtf16Units > WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS,
    };
    result.pathTooLong = result.componentTooLong || result.absolutePathTooLong;
    if (result.componentTooLong) {
        throw createDownloaderError(
            `회차 폴더명이 Windows 안전 길이를 초과합니다: ${componentUtf16Units} UTF-16 units`,
            {
                errorCode: 'path_too_long',
                category: ERROR_CATEGORIES.FILESYSTEM,
                retryable: false,
                diagnostics: { ...result, folderName: component, destinationPath: destination },
                suggestion: '회차 제목을 자동으로 자르지 않습니다. 원문을 확인하거나 폴더명 정책을 명시적으로 조정하세요.',
            },
        );
    }
    if (result.absolutePathTooLong) {
        throw createDownloaderError(
            `전체 목적지 경로가 Windows 안전 길이를 초과합니다: ${destinationUtf16Units} UTF-16 units. `
            + '더 짧은 출력 폴더를 -output으로 지정하세요.',
            {
                errorCode: 'path_too_long',
                category: ERROR_CATEGORIES.FILESYSTEM,
                retryable: false,
                diagnostics: { ...result, folderName: component, destinationPath: destination },
                suggestion: '더 짧은 출력 폴더를 -output으로 지정한 뒤 다시 시도하세요.',
            },
        );
    }
    return result;
}

function buildEpisodeDisplayTitle(workTitle, sourceTitle, episodeNumber = 0) {
    const work = normalizeDisplayText(workTitle) || '제목 없음';
    const suffix = extractEpisodeSuffix(work, sourceTitle, episodeNumber);
    return normalizeDisplayText(`${work} ${suffix}`);
}

function buildEpisodeFolderName(workTitle, sourceTitle, episodeNumber = 0) {
    return sanitizePathSegment(
        buildEpisodeDisplayTitle(workTitle, sourceTitle, episodeNumber),
        `회차 ${String(Math.max(0, Number.parseInt(episodeNumber) || 0)).padStart(4, '0')}`,
    );
}

function uniqueEpisodeFolderName(
    folderName,
    episodeNumber,
    usedNames = new Set(),
    { allowExisting = false } = {},
) {
    const normalizedNumber = Number.parseInt(episodeNumber);
    if (!Number.isSafeInteger(normalizedNumber) || normalizedNumber <= 0)
        throw new Error('회차 순번은 1 이상의 정수여야 합니다.');
    const base = sanitizePathSegment(folderName, `회차 ${episodeNumber}`);
    const used = usedNames instanceof Set ? usedNames : new Set(usedNames);
    if (allowExisting)
        used.delete(base.toLowerCase());
    let candidate = base;
    let counter = 1;
    while (used.has(candidate.toLowerCase())) {
        const discriminator = String(normalizedNumber).padStart(4, '0');
        candidate = `${base} [${discriminator}${counter === 1 ? '' : `-${counter}`}]`;
        counter++;
    }
    used.add(candidate.toLowerCase());
    return candidate;
}

function buildEpisodeManifestRecord(
    { number, src = '', sourceUrl = '', fileName = '', sourceTitle = '', folderName = '' } = {},
    workTitle = '',
) {
    const normalizedNumber = Number.parseInt(number);
    if (!Number.isSafeInteger(normalizedNumber) || normalizedNumber <= 0)
        throw new Error('회차 순번은 1 이상의 정수여야 합니다.');
    const normalizedSourceUrl = String(sourceUrl || src || '').trim();
    const normalizedSourceTitle = normalizeDisplayText(sourceTitle || fileName);
    const displayTitle = buildEpisodeDisplayTitle(
        workTitle,
        normalizedSourceTitle,
        normalizedNumber,
    );
    return {
        number: normalizedNumber,
        sourceId: episodeSourceId(normalizedSourceUrl),
        sourceUrl: normalizedSourceUrl,
        sourceTitle: normalizedSourceTitle,
        displayTitle,
        folderName: sanitizePathSegment(
            folderName || displayTitle,
            `회차 ${String(normalizedNumber).padStart(4, '0')}`,
        ),
    };
}

function episodeRecordFolderCandidates(item) {
    const candidates = [];
    const seen = new Set();
    for (const value of [
        item?.folderName,
        ...(Array.isArray(item?.folderHints) ? item.folderHints : []),
        item?.displayTitle,
        item?.sourceTitle,
    ]) {
        const candidate = sanitizePathSegment(value, '');
        const key = candidate.toLowerCase();
        if (candidate && !seen.has(key)) {
            candidates.push(candidate);
            seen.add(key);
        }
    }
    return candidates;
}

function normalizeEpisodeManifestRecord(item, fallbackNumber = 0) {
    if (!item || typeof item !== 'object')
        return null;
    const declaredNumber = Number(item.number);
    const numberWasInferred = Boolean(item.numberInferred)
        || !Number.isSafeInteger(declaredNumber)
        || declaredNumber <= 0;
    const number = !numberWasInferred
        ? declaredNumber
        : Number(fallbackNumber);
    if (!Number.isSafeInteger(number) || number <= 0)
        return null;
    const folderCandidates = episodeRecordFolderCandidates(item);
    if (folderCandidates.length === 0)
        return null;
    const sourceUrl = String(item.sourceUrl || '').trim();
    const sourceId = String(item.sourceId || episodeSourceId(sourceUrl)).trim();
    const folderName = folderCandidates[0];
    const folderHints = folderCandidates.slice(1);
    return {
        number,
        ...(numberWasInferred ? { numberInferred: true } : {}),
        sourceId,
        sourceUrl,
        sourceTitle: normalizeDisplayText(item.sourceTitle),
        displayTitle: normalizeDisplayText(item.displayTitle) || folderName,
        folderName,
        ...(folderHints.length > 0 ? { folderHints } : {}),
    };
}

function mergeEpisodeManifestRecords(currentEpisodes, previousEpisodes) {
    const current = (currentEpisodes || [])
        .map((item, index) => normalizeEpisodeManifestRecord(item, index + 1))
        .filter(Boolean);
    const previous = (previousEpisodes || [])
        .map((item, index) => normalizeEpisodeManifestRecord(item, index + 1))
        .filter(Boolean);
    const merged = [...current];
    const recordsMatch = (left, right) => {
        if (left.sourceId && right.sourceId)
            return left.sourceId === right.sourceId;
        if (left.numberInferred || right.numberInferred)
            return false;
        if (left.number !== right.number)
            return false;
        const leftFolders = new Set(
            episodeRecordFolderCandidates(left).map(value => value.toLowerCase()),
        );
        return episodeRecordFolderCandidates(right).some(
            value => leftFolders.has(value.toLowerCase()),
        );
    };
    const combineRecords = (
        primary,
        supplemental,
        { preferSupplementalFolder = false } = {},
    ) => {
        const folders = episodeRecordFolderCandidates({
            folderName: preferSupplementalFolder
                ? supplemental.folderName || primary.folderName
                : primary.folderName || supplemental.folderName,
            folderHints: [
                ...(preferSupplementalFolder
                    ? episodeRecordFolderCandidates(primary)
                    : []),
                ...(primary.folderHints || []),
                ...episodeRecordFolderCandidates(supplemental),
            ],
            displayTitle: primary.displayTitle,
            sourceTitle: primary.sourceTitle,
        });
        const useSupplementalNumber = Boolean(primary.numberInferred)
            && !supplemental.numberInferred;
        const number = useSupplementalNumber ? supplemental.number : primary.number;
        const numberInferred = useSupplementalNumber
            ? false
            : Boolean(primary.numberInferred);
        return {
            number,
            ...(numberInferred ? { numberInferred: true } : {}),
            sourceId: primary.sourceId || supplemental.sourceId,
            sourceUrl: primary.sourceUrl || supplemental.sourceUrl,
            sourceTitle: primary.sourceTitle || supplemental.sourceTitle,
            displayTitle: primary.displayTitle || supplemental.displayTitle || folders[0],
            folderName: folders[0],
            ...(folders.length > 1 ? { folderHints: folders.slice(1) } : {}),
        };
    };

    const inferredIndex = buildInferredEpisodeTitleIndex(previous);
    const inferredClaimIndexes = new Map();
    const inferredClaimCounts = new Map();
    for (const [index, item] of current.entries()) {
        if (item.numberInferred)
            continue;
        const candidate = findUniqueInferredEpisodeMatch(inferredIndex, item);
        if (!candidate)
            continue;
        inferredClaimIndexes.set(candidate, index);
        inferredClaimCounts.set(candidate, (inferredClaimCounts.get(candidate) || 0) + 1);
    }

    for (const item of previous) {
        const matchingIndex = item.numberInferred
            ? -1
            : merged.findIndex(existing => recordsMatch(existing, item));
        const inferredMatchingIndex = (
            matchingIndex < 0
            && item.numberInferred
            && inferredClaimCounts.get(item) === 1
        )
            ? inferredClaimIndexes.get(item)
            : undefined;
        if (matchingIndex >= 0) {
            merged[matchingIndex] = combineRecords(merged[matchingIndex], item);
        }
        else if (Number.isInteger(inferredMatchingIndex)) {
            merged[inferredMatchingIndex] = combineRecords(
                merged[inferredMatchingIndex],
                item,
                { preferSupplementalFolder: true },
            );
        }
        else {
            merged.push(item);
        }
    }
    return merged.sort((left, right) => (
        left.number - right.number
        || left.sourceId.localeCompare(right.sourceId)
        || left.folderName.localeCompare(right.folderName, 'ko', { numeric: true })
    ));
}

function normalizedEpisodeSourceTitle(value, episodeNumber = 0) {
    const number = Number(episodeNumber);
    let normalized = normalizeDisplayText(legacyEpisodeTitleText(value)).normalize('NFKC');
    if (Number.isSafeInteger(number) && number > 0)
        normalized = normalized.replace(new RegExp(`^0*${number}(?:\\s+|$)`), '');
    return sanitizePathSegment(normalized, '').normalize('NFKC').toLowerCase();
}

function episodeSourceTitlesMatch(left, right, episodeNumber = 0) {
    const leftKey = normalizedEpisodeSourceTitle(left, episodeNumber);
    const rightKey = normalizedEpisodeSourceTitle(right, episodeNumber);
    return Boolean(leftKey && rightKey && leftKey === rightKey);
}

function episodeRecordTitleKeys(item) {
    const keys = new Set();
    for (const value of [
        item?.sourceTitle,
        item?.displayTitle,
        item?.folderName,
        ...(Array.isArray(item?.folderHints) ? item.folderHints : []),
    ]) {
        const key = normalizedEpisodeSourceTitle(value, 0);
        if (key)
            keys.add(key);
    }
    return keys;
}

function buildInferredEpisodeTitleIndex(episodes) {
    const index = new Map();
    for (const item of episodes || []) {
        if (!item?.numberInferred || String(item.sourceId || '').trim())
            continue;
        for (const key of episodeRecordTitleKeys(item)) {
            if (!index.has(key))
                index.set(key, new Set());
            index.get(key).add(item);
        }
    }
    return index;
}

function findUniqueInferredEpisodeMatch(index, currentEpisode) {
    if (!(index instanceof Map))
        return null;
    const matches = new Set();
    for (const key of episodeRecordTitleKeys(currentEpisode)) {
        const candidates = index.get(key);
        if (!candidates)
            continue;
        // An ambiguous key makes the entire claim unsafe even when another
        // folder hint happens to identify only one of the records.
        if (candidates.size !== 1)
            return null;
        matches.add(candidates.values().next().value);
        if (matches.size > 1)
            return null;
    }
    return matches.size === 1 ? matches.values().next().value : null;
}

function canReuseLegacyEpisodeFolder(
    previousEpisodes,
    episodeNumber,
    sourceId,
    currentSourceTitle = '',
    legacyFolderName = '',
) {
    const number = Number(episodeNumber);
    if (!Number.isSafeInteger(number) || number <= 0)
        return false;
    const stableIds = new Set(
        (previousEpisodes || [])
            .filter(item => Number(item?.number) === number && item?.sourceId)
            .map(item => String(item.sourceId)),
    );
    if (stableIds.size > 0)
        return stableIds.has(String(sourceId || ''));
    const titleCandidates = (previousEpisodes || [])
        .filter(item => Number(item?.number) === number && !item?.sourceId)
        .flatMap(item => [item.sourceTitle, item.folderName]);
    if (legacyFolderName)
        titleCandidates.push(legacyFolderName);
    return titleCandidates.some(candidate => (
        episodeSourceTitlesMatch(currentSourceTitle, candidate, number)
    ));
}

function isLegacyEpisodeFolderCandidate(
    folderName,
    episodeNumber,
    childFileNames = [],
    explicitlyMapped = false,
) {
    const number = Number(episodeNumber);
    if (!Number.isSafeInteger(number) || number <= 0)
        return false;
    const prefixMatches = new RegExp(`^0*${number}(?:\\s|$)`).test(String(folderName || ''));
    if (!prefixMatches)
        return false;
    if (explicitlyMapped)
        return true;
    return (childFileNames || []).some(fileName => (
        /(?:^|\s)image\d{4}\.[a-zA-Z0-9]+$/i.test(String(fileName || ''))
    ));
}

export {
    ALLOWED_FOLDER_FIELDS,
    DEFAULT_FOLDER_TEMPLATE,
    WINDOWS_SAFE_EPISODE_COMPONENT_UTF16_UNITS,
    WINDOWS_SAFE_EPISODE_PATH_UTF16_UNITS,
    buildEpisodeDisplayTitle,
    buildEpisodeFolderName,
    buildEpisodeManifestRecord,
    buildInferredEpisodeTitleIndex,
    canReuseLegacyEpisodeFolder,
    episodeSourceId,
    episodeRecordFolderCandidates,
    episodeSourceTitlesMatch,
    extractEpisodeSuffix,
    findUniqueInferredEpisodeMatch,
    isLegacyEpisodeFolderCandidate,
    mergeEpisodeManifestRecords,
    renderFolderTemplate,
    sanitizePathSegment,
    uniqueEpisodeFolderName,
    validateEpisodeDestinationPath,
    validateFolderTemplate,
    windowsUtf16Units,
};
