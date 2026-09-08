import { connect } from "puppeteer-real-browser";
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { ProxyAgent } from 'proxy-agent';
import { ImageTransport } from './downloader_transport.js';
import { loadArchivedEpisodes, hasArchivedEpisode } from './downloader_archives.js';
import {
    episodeStateUsesStableIds,
    normalizeAndSortEpisodeLinks,
    requireEpisodeImages,
    resolveEpisodeCompletion,
    selectEpisodeLinks,
    validateImageBuffer,
} from './downloader_policy.js';
import {
    ERROR_CATEGORIES,
    classifyDownloaderError,
    createDownloaderError,
} from './downloader_errors.js';
import {
    DEFAULT_FOLDER_TEMPLATE,
    buildInferredEpisodeTitleIndex,
    buildEpisodeManifestRecord,
    canReuseLegacyEpisodeFolder,
    episodeRecordFolderCandidates,
    episodeSourceTitlesMatch,
    findUniqueInferredEpisodeMatch,
    isLegacyEpisodeFolderCandidate,
    mergeEpisodeManifestRecords,
    renderFolderTemplate,
    resolveEpisodeCollectionNames,
    sanitizePathSegment,
    uniqueEpisodeFolderName,
    validateEpisodeDestinationPath,
} from './downloader_naming.js';
import {
    GlobalBandwidthLimiter,
    RequestPacer,
    authenticatedProxyUrl,
    normalizeProxyUrl,
    normalizeRequestDelayMs,
    normalizeSpeedLimitKib,
    proxyAuthenticationResponse,
    proxyCredentialsFromEnvironment,
} from './downloader_network.js';

let info = {
    url: '',
    protocolDomain: 'https://booktoki350.com',
    siteTitle: '북토끼',
    site: 'booktoki',
    startIndex: 0,
    lastIndex: 99999,
    outputDir: process.cwd(),
    contentTitle: '',
    contentFolderName: '',
    metadata: null,
    jsonEvents: false,
    showBrowser: false,
    metadataOnly: false,
    contentPathOverride: '',
    folderTemplate: DEFAULT_FOLDER_TEMPLATE,
    imageConcurrency: 5,
    scanMode: '',
    proxyUrl: '',
    proxyCredentials: { username: '', password: '', configured: false },
    authenticatedProxyUrl: '',
    speedLimitKib: 0,
    requestDelayMs: 0,
    providerBackoffSeconds: 2,
}

let bandwidthLimiter = new GlobalBandwidthLimiter(0);
let requestPacer = new RequestPacer(0);
let outboundProxyAgent = null;
let imageTransport = new ImageTransport();

function sleep(ms) {
    return new Promise(function (resolve) {
        setTimeout(() => { resolve(); }, ms);
    })
}
function consoleRed(val) {
    console.log(`\x1b[41m${val}\x1b[0m`);
}
function consoleGrey(val) {
    console.log(`\x1b[100m${val}\x1b[0m`);
}
function help() {
    console.log(`사용법: node down -url "URL" [-scan-mode new|full|range] [-start STARTINDEX] [-last LASTINDEX] [-output "폴더 경로"] [-folder-template "[{author}][{group}] {title}"] [-proxy URL] [-speed-limit-kib 0|32~1048576] [-request-delay-ms 0~5000] [-provider-backoff 1~60] [-show-browser] [-image-concurrency 1~16] [-metadata-only] [-content-path "기존 작품 폴더"] [-json-events]`);
    process.exit();
}
function emitEvent(event, data = {}) {
    if (info.jsonEvents)
        console.log(`@@TOKI@@${JSON.stringify({ event, ...data })}`);
}

function analyseArguments() {
    let argL = process.argv.length;
    if (argL == 2) {
        help();
    }
    for (let i = 2; i < argL; i++) {
        if (process.argv[i] == '-url') {
            if ((i + 1) < argL) {
                info.url = process.argv[i + 1];
                i++;
            }
        }
        else if (process.argv[i] == '-start') {
            if ((i + 1) < argL) {
                info.startIndex = parseInt(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-last') {
            if ((i + 1) < argL) {
                info.lastIndex = parseInt(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-output') {
            if ((i + 1) < argL) {
                info.outputDir = path.resolve(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-json-events') {
            info.jsonEvents = true;
        }
        else if (process.argv[i] == '-show-browser') {
            info.showBrowser = true;
        }
        else if (process.argv[i] == '-metadata-only') {
            info.metadataOnly = true;
        }
        else if (process.argv[i] == '-content-path') {
            if ((i + 1) < argL) {
                info.contentPathOverride = path.resolve(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-folder-template') {
            if ((i + 1) < argL) {
                info.folderTemplate = process.argv[i + 1];
                i++;
            }
        }
        else if (process.argv[i] == '-proxy') {
            if ((i + 1) < argL) {
                info.proxyUrl = process.argv[i + 1];
                i++;
            }
        }
        else if (process.argv[i] == '-speed-limit-kib') {
            if ((i + 1) < argL) {
                info.speedLimitKib = parseInt(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-request-delay-ms') {
            if ((i + 1) < argL) {
                info.requestDelayMs = parseInt(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-provider-backoff') {
            if ((i + 1) < argL) {
                info.providerBackoffSeconds = parseInt(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-image-concurrency') {
            if ((i + 1) < argL) {
                info.imageConcurrency = parseInt(process.argv[i + 1]);
                i++;
            }
        }
        else if (process.argv[i] == '-scan-mode') {
            if ((i + 1) < argL) {
                info.scanMode = String(process.argv[i + 1]).toLowerCase();
                i++;
            }
        }
        else if (process.argv[i] == '-h' || process.argv[i] == '-help') {
            help();
        }
    }
    if (!info.url) {
        consoleGrey('url을 입력하세요');
        process.exit(1);
    }
    // check url
    // 북토끼
    if (info.url.match(/^https:\/\/booktoki[0-9]+\.com\/novel\/[0-9]+/)) {
        info.site = 'booktoki'; info.siteTitle = '북토끼';
        info.protocolDomain = info.url.match(/^https:\/\/booktoki[0-9]+\.com/)[0];
    }
    // 뉴토끼
    else if (info.url.match(/^https:\/\/newtoki[0-9]+\.com\/webtoon\/[0-9]+/)) {
        info.site = 'newtoki'; info.siteTitle = '뉴토끼';
        info.protocolDomain = info.url.match(/^https:\/\/newtoki[0-9]+\.com/)[0];
    }
    // 마나토끼(newtoki*.org 주소)
    else if (info.url.match(/^https:\/\/newtoki[0-9]+\.org\/manhwa\/[0-9]+/)) {
        info.site = 'manatoki'; info.siteTitle = '마나토끼';
        info.protocolDomain = info.url.match(/^https:\/\/newtoki[0-9]+\.org/)[0];
    }
    // 마나토끼
    else if (info.url.match(/^https:\/\/manatoki[0-9]+\.net\/comic\/[0-9]+/)) {
        info.site = 'manatoki'; info.siteTitle = '마나토끼';
        info.protocolDomain = info.url.match(/^https:\/\/manatoki[0-9]+\.net/)[0];
    }
    else {
        consoleGrey('회차 목록 페이지 url을 입력해야합니다. url을 확인해주세요.');
        process.exit(1);
    }
    if (!Number.isInteger(info.imageConcurrency) || info.imageConcurrency < 1 || info.imageConcurrency > 16) {
        consoleGrey('이미지 동시 다운로드 수는 1~16 사이여야 합니다.');
        process.exit(1);
    }
    info.proxyUrl = normalizeProxyUrl(info.proxyUrl);
    info.speedLimitKib = normalizeSpeedLimitKib(info.speedLimitKib);
    info.requestDelayMs = normalizeRequestDelayMs(info.requestDelayMs);
    if (!Number.isInteger(info.providerBackoffSeconds)
        || info.providerBackoffSeconds < 1 || info.providerBackoffSeconds > 60) {
        consoleGrey('공급자 백오프는 1~60초여야 합니다.');
        process.exit(1);
    }
    if (!info.scanMode)
        info.scanMode = (info.startIndex !== 0 || info.lastIndex !== 99999) ? 'range' : 'full';
    if (!['new', 'full', 'range'].includes(info.scanMode)) {
        consoleGrey('검사 방식은 new, full, range 중 하나여야 합니다.');
        process.exit(1);
    }
    if (!Number.isInteger(info.startIndex) || !Number.isInteger(info.lastIndex)
        || info.startIndex < 0 || info.lastIndex < 1 || info.startIndex > info.lastIndex) {
        consoleGrey('회차 범위를 확인해주세요.');
        process.exit(1);
    }
    if (info.scanMode === 'range' && info.startIndex === 0 && info.lastIndex === 99999) {
        consoleGrey('지정 범위 검사는 -start 또는 -last가 필요합니다.');
        process.exit(1);
    }
    if (info.scanMode !== 'range') {
        info.startIndex = 0;
        info.lastIndex = 99999;
    }
}
function configureNetworkRuntime() {
    bandwidthLimiter = new GlobalBandwidthLimiter(info.speedLimitKib);
    requestPacer = new RequestPacer(info.requestDelayMs);
    info.proxyCredentials = proxyCredentialsFromEnvironment();
    info.authenticatedProxyUrl = authenticatedProxyUrl(
        info.proxyUrl,
        info.proxyCredentials,
    );
    outboundProxyAgent = info.proxyUrl
        ? new ProxyAgent({ getProxyForUrl: () => info.authenticatedProxyUrl })
        : null;
    imageTransport.close();
    imageTransport = new ImageTransport({proxyAgent: outboundProxyAgent,
        wait: () => requestPacer.wait(), consume: bytes => bandwidthLimiter.consume(bytes),
        log: message => console.log(message)});
}
async function installProxyAuthentication(page) {
    if (!info.proxyCredentials.configured)
        return null;
    const client = typeof page.createCDPSession === 'function'
        ? await page.createCDPSession()
        : await page.target().createCDPSession();
    const attemptedRequests = new Set();
    client.on('Fetch.requestPaused', event => {
        client.send('Fetch.continueRequest', { requestId: event.requestId }).catch(() => {});
    });
    client.on('Fetch.authRequired', event => {
        const attempted = attemptedRequests.has(event.requestId);
        if (String(event.authChallenge?.source ?? '').toLowerCase() === 'proxy')
            attemptedRequests.add(event.requestId);
        const authChallengeResponse = proxyAuthenticationResponse(
            event.authChallenge,
            info.proxyCredentials,
            attempted,
        );
        client.send('Fetch.continueWithAuth', {
            requestId: event.requestId,
            authChallengeResponse,
        }).catch(() => {});
    });
    await client.send('Fetch.enable', { handleAuthRequests: true });
    return client;
}
function buildContentFolderName(metadata) {
    return renderFolderTemplate(info.folderTemplate, metadata);
}
function getContentPath() {
    return info.contentPathOverride || path.join(info.outputDir, info.siteTitle, info.contentFolderName);
}
function completionStatePath() {
    return path.join(getContentPath(), '.toki-state.json');
}
function contentEntries() {
    const contentPath = getContentPath();
    if (!fs.existsSync(contentPath))
        return [];
    return fs.readdirSync(contentPath, { withFileTypes: true });
}
function loadEpisodeState() {
    const statePath = completionStatePath();
    if (!fs.existsSync(statePath)) {
        return {
            exists: false,
            version: 2,
            completedEpisodes: [],
            completedEpisodeIds: [],
            completedEpisodeIdsPresent: false,
            episodes: [],
        };
    }
    try {
        const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
        return {
            exists: true,
            version: Number.parseInt(state.version) || 1,
            completedEpisodes: Array.isArray(state.completedEpisodes)
                ? state.completedEpisodes.map(Number).filter(Number.isInteger)
                : [],
            completedEpisodeIds: Array.isArray(state.completedEpisodeIds)
                ? state.completedEpisodeIds.map(String).filter(Boolean)
                : [],
            completedEpisodeIdsPresent: Object.prototype.hasOwnProperty.call(
                state,
                'completedEpisodeIds',
            ),
            episodes: Array.isArray(state.episodes)
                ? mergeEpisodeManifestRecords([], state.episodes)
                : [],
        };
    }
    catch (error) {
        console.log(`회차 완료 상태 읽기 실패, 기존 파일로 복구: ${error.message || error}`);
        return {
            exists: false,
            version: 2,
            completedEpisodes: [],
            completedEpisodeIds: [],
            completedEpisodeIdsPresent: false,
            episodes: [],
        };
    }
}
function loadEpisodeMetadataManifest() {
    const metadataPath = path.join(getContentPath(), 'metadata.json');
    if (!fs.existsSync(metadataPath))
        return [];
    try {
        const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
        return Array.isArray(metadata?.episodes)
            ? mergeEpisodeManifestRecords([], metadata.episodes)
            : [];
    }
    catch (error) {
        console.log(`기존 메타데이터 회차 목록 읽기 실패: ${error.message || error}`);
        return [];
    }
}
function legacyEpisodeFolderName(
    number,
    entries = contentEntries(),
    currentSourceTitle = '',
    previousEpisodes = [],
    sourceId = '',
) {
    const normalizedNumber = Number(number);
    if (!Number.isSafeInteger(normalizedNumber) || normalizedNumber <= 0)
        return '';
    const prefixPattern = new RegExp(`^0*${normalizedNumber}(?:\\s|$)`);
    return entries
        .filter(entry => {
            if (!entry.isDirectory() || !prefixPattern.test(entry.name))
                return false;
            if (!episodeSourceTitlesMatch(currentSourceTitle, entry.name, normalizedNumber))
                return false;
            if (!canReuseLegacyEpisodeFolder(
                previousEpisodes,
                normalizedNumber,
                sourceId,
                currentSourceTitle,
                entry.name,
            ))
                return false;
            try {
                const childNames = fs.readdirSync(path.join(getContentPath(), entry.name));
                return isLegacyEpisodeFolderCandidate(
                    entry.name,
                    number,
                    childNames,
                );
            }
            catch (_error) {
                return false;
            }
        })
        .map(entry => entry.name)
        .sort((left, right) => left.localeCompare(right, 'ko', { numeric: true }))[0] || '';
}
function isLegacyEpisodeFolder(folderName, number) {
    return new RegExp(`^0*${Number.parseInt(number)}(?:\\s|$)`).test(String(folderName || ''));
}
function prepareEpisodeManifest(links, state) {
    const archived = loadArchivedEpisodes(getContentPath());
    const entries = contentEntries();
    const directories = new Set(
        entries.filter(entry => entry.isDirectory()).map(entry => entry.name.toLowerCase()),
    );
    const previousById = new Map();
    const previousByNumber = new Map();
    for (const item of state.episodes || []) {
        const number = Number.parseInt(item.number);
        if (!Number.isSafeInteger(number) || number <= 0)
            continue;
        if (item.sourceId)
            previousById.set(String(item.sourceId), item);
        if (!item.sourceId && !item.numberInferred) {
            if (!previousByNumber.has(number))
                previousByNumber.set(number, []);
            previousByNumber.get(number).push(item);
        }
    }
    const inferredTitleIndex = buildInferredEpisodeTitleIndex(state.episodes);
    const freshRecords = links.map(item => buildEpisodeManifestRecord(
        {
            number: Number.parseInt(item.num),
            sourceUrl: item.src,
            sourceTitle: item.fileName,
        },
        info.contentTitle,
    ));
    const collectionNaming = resolveEpisodeCollectionNames(
        freshRecords,
        info.contentTitle,
    );
    if (collectionNaming.conflicts.length > 0) {
        throw createDownloaderError(
            '회차 목록에 서로 충돌하는 소수점/분할 회차 표기가 있어 폴더명을 안전하게 결정할 수 없습니다.',
            {
                errorCode: 'ambiguous_episode_sibling_naming',
                category: ERROR_CATEGORIES.SITE_STRUCTURE,
                retryable: false,
                diagnostics: { conflicts: collectionNaming.conflicts },
                suggestion: '충돌한 회차 제목을 확인한 뒤 명명 규칙을 명시적으로 정리하세요.',
            },
        );
    }
    const preparedLinks = links.map((item, index) => {
        const base = collectionNaming.records[index];
        return {
            item,
            base,
            inferredPrevious: findUniqueInferredEpisodeMatch(inferredTitleIndex, base),
        };
    });
    const inferredClaimCounts = new Map();
    for (const prepared of preparedLinks) {
        if (prepared.inferredPrevious) {
            inferredClaimCounts.set(
                prepared.inferredPrevious,
                (inferredClaimCounts.get(prepared.inferredPrevious) || 0) + 1,
            );
        }
    }
    const usedNames = new Set(directories);
    const claimedNames = new Set();
    const manifest = [];
    for (const { item, base, inferredPrevious } of preparedLinks) {
        const previous = previousById.get(base.sourceId) || (
            previousByNumber.get(base.number) || []
        ).find(candidate => (
            episodeSourceTitlesMatch(
                base.sourceTitle,
                candidate.sourceTitle || candidate.folderName,
                base.number,
            )
        )) || (
            inferredPrevious && inferredClaimCounts.get(inferredPrevious) === 1
                ? inferredPrevious
                : null
        );
        const legacyName = legacyEpisodeFolderName(
            base.number,
            entries,
            base.sourceTitle,
            state.episodes,
            base.sourceId,
        );
        const mappedNames = previous ? episodeRecordFolderCandidates(previous) : [];
        const existingMappedName = mappedNames.find(candidate => (
            directories.has(candidate.toLowerCase())
        )) || '';
        const mappedName = String(existingMappedName || mappedNames[0] || '');
        const preferredName = String(
            (mappedName && directories.has(mappedName.toLowerCase()) ? mappedName : '')
            || legacyName
            || mappedName
            || base.folderName,
        );
        const preferredKey = preferredName.toLowerCase();
        const referencesExistingFolder = (
            directories.has(preferredKey)
            && (
                Boolean(mappedName && mappedName.toLowerCase() === preferredKey)
                || Boolean(legacyName && legacyName.toLowerCase() === preferredKey)
            )
        );
        const folderName = uniqueEpisodeFolderName(
            preferredName,
            base.number,
            usedNames,
            { allowExisting: referencesExistingFolder && !claimedNames.has(preferredKey) },
        );
        claimedNames.add(folderName.toLowerCase());
        const record = buildEpisodeManifestRecord(
            {
                number: base.number,
                sourceUrl: base.sourceUrl,
                sourceTitle: base.sourceTitle,
                folderName,
            },
            info.contentTitle,
        );
        record.displayTitle = base.displayTitle;
        const destinationPath = path.join(getContentPath(), record.folderName);
        if (
            info.site !== 'booktoki'
            && !fs.existsSync(destinationPath)
        )
            validateEpisodeDestinationPath(record.folderName, destinationPath);
        item.sourceId = record.sourceId;
        item.archiveExists = hasArchivedEpisode(archived, record);
        item.episode = record;
        item.legacyFolder = isLegacyEpisodeFolder(record.folderName, record.number);
        item.numericFallbackVerified = Boolean(
            legacyName
            || (
                previous
                && episodeSourceTitlesMatch(
                    base.sourceTitle,
                    previous.sourceTitle || previous.folderName,
                    base.number,
                )
            )
        );
        item.storageExists = (
            info.site === 'booktoki'
                ? entries.some(entry => (
                    entry.isFile()
                    && new RegExp(`^0*${record.number}(?:\\s|$)`).test(entry.name)
                    && entry.name.toLowerCase().endsWith('.txt')
                ))
                : directories.has(record.folderName.toLowerCase()) || item.archiveExists
        );
        manifest.push(record);
    }
    return mergeEpisodeManifestRecords(manifest, state.episodes);
}
function loadEpisodeCompletion(state, links, manifest) {
    const archived = loadArchivedEpisodes(getContentPath());
    const entries = contentEntries();
    const directoryNames = new Set(
        entries.filter(entry => entry.isDirectory()).map(entry => entry.name.toLowerCase()),
    );
    const storageExists = record => (
        info.site === 'booktoki'
            ? entries.some(entry => (
                entry.isFile()
                && new RegExp(`^0*${Number(record.number)}(?:\\s|$)`).test(entry.name)
                && entry.name.toLowerCase().endsWith('.txt')
            ))
            : directoryNames.has(String(record.folderName || '').toLowerCase()) || hasArchivedEpisode(archived, record)
    );
    const physicalNumbers = new Set();
    const physicalEpisodeIds = new Set();
    for (const entry of entries) {
        const matched = entry.name.match(/^0*(\d+)(?:\s|$)/);
        const number = matched ? Number.parseInt(matched[1]) : 0;
        if (number > 0 && (entry.isDirectory() || entry.name.toLowerCase().endsWith('.txt')))
            physicalNumbers.add(number);
    }
    for (const record of manifest || []) {
        if (!storageExists(record))
            continue;
        physicalNumbers.add(Number(record.number));
        if (record.sourceId)
            physicalEpisodeIds.add(String(record.sourceId));
    }
    return resolveEpisodeCompletion(state, links, {
        physicalNumbers,
        physicalEpisodeIds,
    });
}
function saveEpisodeState(completedEpisodes, completedEpisodeIds, episodes) {
    const contentPath = getContentPath();
    fs.mkdirSync(contentPath, { recursive: true });
    const statePath = completionStatePath();
    const temporaryPath = `${statePath}.tmp`;
    fs.writeFileSync(temporaryPath, `${JSON.stringify({
        version: 2,
        completedEpisodes: [...completedEpisodes].sort((a, b) => a - b),
        completedEpisodeIds: [...completedEpisodeIds].filter(Boolean).sort(),
        episodes: [...episodes].sort((left, right) => (
            Number(left.number) - Number(right.number)
            || String(left.sourceId).localeCompare(String(right.sourceId))
        )),
        updatedAt: new Date().toISOString()
    }, null, 2)}\n`, 'utf8');
    fs.renameSync(temporaryPath, statePath);
}
function saveMetadata(metadata) {
    const contentPath = getContentPath();
    fs.mkdirSync(contentPath, { recursive: true });
    fs.writeFileSync(
        path.join(contentPath, 'metadata.json'),
        `${JSON.stringify(metadata, null, 2)}\n`,
        'utf8'
    );
}
async function cacheCoverImage(metadata, force = false) {
    if (!metadata.coverUrl)
        return '';
    try {
        const extensionMatch = new URL(metadata.coverUrl).pathname.match(/\.(?:jpe?g|png|webp|gif)$/i);
        const fileName = `cover${extensionMatch?.[0]?.toLowerCase() || '.jpg'}`;
        const coverPath = path.join(getContentPath(), fileName);
        if (force || !fs.existsSync(coverPath))
            await saveImage(getContentPath(), fileName, metadata.coverUrl);
        metadata.coverFile = fileName;
        return coverPath;
    }
    catch (error) {
        console.log(`대표 이미지 저장 실패: ${error.message || error}`);
        return '';
    }
}
function saveBook(path, fileName, content) {
    if (!fs.existsSync(path))
        fs.mkdirSync(path, { recursive: true });
    fs.writeFileSync(`${path}/${fileName}`, content);
}

function existingImageFileValidation(filePath) {
    try {
        const stat = fs.statSync(filePath);
        if (!stat.isFile() || stat.size <= 0) {
            return {
                valid: false,
                reason: stat.size <= 0 ? 'empty_image' : 'not_a_file',
                size: stat.size,
            };
        }
        const headerLength = Math.min(256, stat.size);
        const tailLength = Math.min(16, stat.size);
        const header = Buffer.allocUnsafe(headerLength);
        const tail = Buffer.allocUnsafe(tailLength);
        const descriptor = fs.openSync(filePath, 'r');
        let bytesRead = 0;
        let tailBytesRead = 0;
        try {
            bytesRead = fs.readSync(descriptor, header, 0, headerLength, 0);
            tailBytesRead = fs.readSync(
                descriptor,
                tail,
                0,
                tailLength,
                Math.max(0, stat.size - tailLength),
            );
            return {
                ...validateImageBuffer(
                    header.subarray(0, bytesRead),
                    path.extname(filePath),
                    {
                        tail: tail.subarray(0, tailBytesRead),
                        totalSize: stat.size,
                        readAt: (offset, length) => {
                            const chunk = Buffer.allocUnsafe(length);
                            const count = fs.readSync(descriptor, chunk, 0, length, offset);
                            return chunk.subarray(0, count);
                        },
                    },
                ),
                size: stat.size,
            };
        }
        finally {
            fs.closeSync(descriptor);
        }
    }
    catch (error) {
        return { valid: false, reason: 'image_read_failed', size: 0, error };
    }
}

function existingImageFileIsValid(filePath) {
    return existingImageFileValidation(filePath).valid === true;
}

function imageValidationError(fileName, validation) {
    const error = new Error(
        `이미지 응답 검증 실패: ${fileName} (${validation.reason || 'unknown'})`,
    );
    error.code = 'invalid_image_payload';
    error.diagnostics = { ...validation, fileName };
    return error;
}

function writeImageBufferAtomically(
    directoryPath,
    fileName,
    imageBuffer,
    { renameFile = fs.renameSync } = {},
) {
    const validation = validateImageBuffer(imageBuffer, path.extname(fileName));
    if (!validation.valid)
        throw imageValidationError(fileName, validation);
    fs.mkdirSync(directoryPath, { recursive: true });
    const destinationPath = path.join(directoryPath, fileName);
    const temporaryPath = path.join(
        directoryPath,
        `.${path.basename(fileName)}.${process.pid}.${randomUUID()}.tmp`,
    );
    let descriptor;
    try {
        descriptor = fs.openSync(temporaryPath, 'wx');
        fs.writeFileSync(descriptor, imageBuffer);
        fs.fsyncSync(descriptor);
        fs.closeSync(descriptor);
        descriptor = undefined;
        renameFile(temporaryPath, destinationPath);
    }
    catch (error) {
        if (descriptor !== undefined) {
            try {
                fs.closeSync(descriptor);
            }
            catch (_closeError) {}
        }
        try {
            fs.rmSync(temporaryPath, { force: true });
        }
        catch (_cleanupError) {}
        throw error;
    }
    return { destinationPath, validation };
}

async function saveImage(directoryPath, fileName, src) {
    let imageBuffer;
    let lastError;
    for (let attempt = 1; attempt <= 3; attempt++) {
        try {
            const candidate = await downloadBuffer(src, {
                'User-Agent': 'Mozilla/5.0',
                'Referer': `${info.protocolDomain}/`
            });
            const validation = validateImageBuffer(candidate, path.extname(fileName));
            if (!validation.valid)
                throw imageValidationError(fileName, validation);
            imageBuffer = candidate;
            break;
        }
        catch (error) {
            lastError = error;
            if (attempt < 3)
                await sleep(Math.min(60, info.providerBackoffSeconds * (2 ** (attempt - 1))) * 1000);
        }
    }
    if (!imageBuffer)
        throw new Error(`이미지 다운로드 실패: ${src}\n${lastError}`);
    // 새 버퍼 검증이 끝나기 전에는 기존 파일을 건드리지 않는다.
    writeImageBufferAtomically(directoryPath, fileName, imageBuffer);
}

async function downloadBuffer(src, headers, redirectCount = 0) {
    return imageTransport.download(src, headers, redirectCount);
}

async function runDownloadTasks(tasks, concurrency = 5) {
    let nextIndex = 0;
    const errors = [];
    async function worker() {
        while (true) {
            const index = nextIndex++;
            if (index >= tasks.length)
                return;
            try {
                await tasks[index]();
            }
            catch (error) {
                errors.push(error);
            }
        }
    }
    const workerCount = Math.min(concurrency, tasks.length);
    await Promise.all(Array.from({ length: workerCount }, () => worker()));
    if (errors.length > 0)
        throw new Error(`${errors.length}개 이미지 다운로드 실패\n${errors[0]}`);
}

async function main() {
    const { browser, page } = await connect({
        headless: info.showBrowser ? false : 'new',
        args: info.proxyUrl ? [`--proxy-server=${info.proxyUrl}`] : [],
        customConfig: {},
        turnstile: true, //captcha를 자동으로 풀것인지
        connectOption: { defaultViewport: null },
        disableXvfb: false, //화면을 볼것인지
    })
    try {
        await installProxyAuthentication(page);
        // await page.goto('https://booktoki350.com/');
        await requestPacer.wait();
        await Promise.all([page.waitForNavigation(), page.goto(info.url)]);
        // cloudflare에 막히기때문에 title이 바뀌기전까지 기다린다.
        const challengeDeadline = Date.now() + 60000;
        while (!(await page.title()).includes(info.siteTitle)) {
            if (Date.now() >= challengeDeadline)
                throw new Error(`Cloudflare 또는 사이트 인증 확인 시간 초과: ${await page.title()}`);
            await sleep(100);
        }
        info.metadata = await page.evaluate(({ site, siteTitle, sourceUrl }) => {
            const getText = (selector) => document.querySelector(selector)?.textContent?.trim() || '';
            const getInfoValue = (...labels) => {
                const rows = Array.from(document.querySelectorAll('.theme-detail-info-row'));
                for (const row of rows) {
                    const label = row.querySelector('.theme-detail-info-label')?.textContent?.trim();
                    if (labels.includes(label))
                        return row.querySelector('.theme-detail-info-value')?.textContent?.trim() || '';
                }
                return '';
            };
            const ogTitle = document.querySelector('meta[property="og:title"]')?.content?.trim() || '';
            const title = getText('.theme-detail-title-line')
                || getText('.page-title h2 span')
                || ogTitle.replace(/\s+-\s+(?:뉴토끼|마나토끼|북토끼).*$/, '')
                || getText('.page-title .page-desc');
            const rawGenres = getInfoValue('장르');
            const genres = rawGenres
                .split(',')
                .map(value => value.trim())
                .filter(value => value && !/^\d+$/.test(value));
            const workId = sourceUrl.match(/\/(?:novel|webtoon|comic|manhwa)\/([0-9]+)/)?.[1] || '';
            return {
                schemaVersion: 1,
                title,
                author: getInfoValue('작가', '글작가') || 'N／A',
                group: getInfoValue('그룹', '역자', '번역', '번역자') || 'N／A',
                category: getText('.page-title .page-desc'),
                genres,
                status: getInfoValue('발행구분', '연재상태'),
                description: getText('.theme-detail-description'),
                coverUrl: document.querySelector('meta[property="og:image"]')?.content || '',
                source: {
                    site,
                    siteTitle,
                    workId,
                    url: sourceUrl
                }
            };
        }, { site: info.site, siteTitle: info.siteTitle, sourceUrl: info.url });
        info.contentTitle = info.metadata.title;
        info.contentFolderName = buildContentFolderName(info.metadata);
        let link = [];
        // 연재 목록들의 링크를 알아낸다. {num:회차, fileName:연재제목, src:링크}로 구성되어있다.
        while (true) {
            await page.locator('.list-body').setTimeout(40000).wait();
            sleep(1000);
            link = link.concat(await page.evaluate(() => {
                let list = Array.from(document.querySelector('.list-body').querySelectorAll('li'));
                for (let i = 0; i < list.length; i++) {
                    const anchor = list[i].querySelector('a');
                    const subject = anchor?.cloneNode(true);
                    subject?.querySelectorAll('span').forEach(element => element.remove());
                    list[i] = {
                        num: list[i].querySelector('.wr-num')?.innerText?.trim() || '',
                        fileName: subject?.textContent?.trim() || '',
                        src: anchor?.href || ''
                    }
                }
                return list;
            }));
            // 다음 페이지가 없다면 break
            if (await page.$('ul.pagination li[class="active"] ~ li:not([class="disabled"]) a')) {
                await Promise.all([
                    page.waitForNavigation(),
                    page.locator('ul.pagination li[class="active"] ~ li:not([class="disabled"]) a').click()
                ]);
            }
            else
                break;
        }
        // 페이지 구성이나 DOM 방향에 의존하지 않고 유효한 행 순번만 안정적으로 처리한다.
        const normalizedLinks = normalizeAndSortEpisodeLinks(link);
        for (const skipped of normalizedLinks.skipped) {
            const reason = skipped.reason === 'duplicate_episode_source'
                ? '중복 회차 URL'
                : skipped.reason === 'invalid_episode_url'
                    ? '유효하지 않은 회차 URL'
                    : `유효하지 않은 순번 "${skipped.rawNumber}"`;
            console.log(
                `회차 목록 항목 건너뜀: ${reason}`
                + `${skipped.fileName ? ` (${skipped.fileName})` : ''}`,
            );
        }
        link = normalizedLinks.links;
        if (link.length === 0 && !info.metadataOnly)
            throw new Error('회차 목록에서 유효한 양의 정수 순번을 찾지 못했습니다.');
        const totalEpisodeCount = link.length;
        const episodeState = loadEpisodeState();
        episodeState.episodes = mergeEpisodeManifestRecords(
            episodeState.episodes,
            loadEpisodeMetadataManifest(),
        );
        const preferEpisodeIds = episodeStateUsesStableIds(episodeState);
        const episodeManifest = prepareEpisodeManifest(link, episodeState);
        let completedEpisodes = new Set();
        let completedEpisodeIds = new Set();
        let completedEpisodeFallbacks = new Set();
        let skippedExistingEpisodes = 0;
        if (!info.metadataOnly) {
            const completion = loadEpisodeCompletion(episodeState, link, episodeManifest);
            completedEpisodes = completion.completedEpisodes;
            completedEpisodeIds = completion.completedEpisodeIds;
            completedEpisodeFallbacks = completion.completedEpisodeFallbacks;
            saveEpisodeState(completedEpisodes, completedEpisodeIds, episodeManifest);
        }
        const selection = selectEpisodeLinks(link, {
            metadataOnly: info.metadataOnly,
            scanMode: info.scanMode,
            startIndex: info.startIndex,
            lastIndex: info.lastIndex,
            completedEpisodes,
            completedEpisodeIds,
            completedEpisodeFallbacks,
            preferEpisodeIds,
        });
        link = selection.links.filter(item => !item.archiveExists);
        skippedExistingEpisodes = selection.skippedExistingEpisodes + selection.links.length - link.length;
        if (!info.metadataOnly && info.scanMode !== 'new' && selection.links.length === 0)
            throw new Error('지정한 범위에 해당하는 회차가 없습니다.');
        info.metadata.folderName = info.contentFolderName;
        info.metadata.episodeCount = totalEpisodeCount;
        info.metadata.selectedEpisodeCount = link.length;
        info.metadata.requestedRange = {
            start: info.startIndex === 0 ? null : info.startIndex,
            last: info.lastIndex === 99999 ? null : info.lastIndex
        };
        info.metadata.scanMode = info.metadataOnly ? 'metadata' : info.scanMode;
        info.metadata.episodes = episodeManifest;
        info.metadata.generatedAt = new Date().toISOString();
        const coverPath = await cacheCoverImage(info.metadata, info.metadataOnly);
        saveMetadata(info.metadata);
        console.log(`저장 폴더: ${getContentPath()}`);
        emitEvent('work_metadata', {
            metadata: info.metadata,
            outputPath: getContentPath(),
            coverPath
        });
        emitEvent('queue_ready', {
            totalEpisodes: totalEpisodeCount,
            selectedEpisodes: link.length,
            skippedExistingEpisodes,
            scanMode: info.metadataOnly ? 'metadata' : info.scanMode
        });
        if (info.metadataOnly) {
            console.log('메타데이터와 대표 이미지 새로고침 완료');
            emitEvent('metadata_refreshed', {
                outputPath: getContentPath(),
                coverPath
            });
            emitEvent('completed', {
                outputPath: getContentPath(),
                selectedEpisodes: 0,
                metadataOnly: true
            });
            return;
        }
        // 페이지 방문하기
        for (let i = 0; i < link.length; i++) {
            await requestPacer.wait();
            await Promise.all([page.goto(link[i].src), page.waitForNavigation()]);
            await sleep(2000);
            const safeEpisodeName = sanitizePathSegment(link[i].fileName, '회차');
            const episodeRecord = link[i].episode || buildEpisodeManifestRecord(
                {
                    number: Number.parseInt(link[i].num),
                    sourceUrl: link[i].src,
                    sourceTitle: link[i].fileName,
                },
                info.contentTitle,
            );
            console.log(`${link[i].num} ${link[i].fileName} 진행중`);
            emitEvent('episode_started', {
                index: i + 1,
                total: link.length,
                number: parseInt(link[i].num),
                title: episodeRecord.displayTitle,
                sourceTitle: link[i].fileName,
                folderName: episodeRecord.folderName,
                sourceId: episodeRecord.sourceId,
            });
            // 북토끼
            if (info.site === "booktoki") {
                await page.locator('#novel_content').wait();
                // 텍스트 가져오기
                let fileContent = await page.evaluate(() => {
                    const fileContent = document.querySelector('#novel_content').innerText;
                    return fileContent;
                });
                // 텍스트 저장. 이미 있다면 저장하지 않음.
                const bookPath = getContentPath();
                const bookFileName = `${link[i].num} ${safeEpisodeName}.txt`;
                if (!fs.existsSync(path.join(bookPath, bookFileName)))
                    saveBook(bookPath, bookFileName, fileContent);
                emitEvent('episode_completed', {
                    index: i + 1,
                    total: link.length,
                    number: parseInt(link[i].num),
                    title: episodeRecord.displayTitle,
                    sourceTitle: link[i].fileName,
                    folderName: episodeRecord.folderName,
                    sourceId: episodeRecord.sourceId,
                });
                completedEpisodes.add(parseInt(link[i].num));
                if (episodeRecord.sourceId)
                    completedEpisodeIds.add(episodeRecord.sourceId);
                saveEpisodeState(completedEpisodes, completedEpisodeIds, episodeManifest);
            }
            // 뉴토끼, 마나토끼
            else {
                const imageSelector = '.view-padding div img, .theme-viewer-images img';
                await page.waitForSelector(imageSelector, { timeout: 60000 });
                // 이미지 가져오기
                let imgLists = await page.evaluate((selector) => {
                    let imgLists = Array.from(document.querySelectorAll(selector));
                    let returnList = [];
                    // 화면에 보이지 않는 이미지라면 리스트에서 제거
                    for (let j = 0; j < imgLists.length;) {
                        if (imgLists[j].checkVisibility() === false)
                            imgLists.splice(j, 1);
                        else {
                            try {
                                // 구형 뷰어의 지연 로딩 경로와 신형 뷰어의 CDN 주소를 모두 지원한다.
                                const legacyPath = imgLists[j].outerHTML.match(/\/data[^"]+/)?.[0];
                                const rawSrc = legacyPath || imgLists[j].currentSrc || imgLists[j].getAttribute('src');
                                const src = new URL(rawSrc, location.origin).href;
                                const extension = new URL(src).pathname.match(/\.[a-zA-Z0-9]+$/)?.[0] || '.jpg';
                                returnList.push({ src, extension });
                            }
                            catch (error) {}
                            j++;
                        }
                    }
                    return returnList;
                }, imageSelector);
                imgLists = requireEpisodeImages(imgLists, {
                    episodeNumber: Number.parseInt(link[i].num),
                    sourceId: episodeRecord.sourceId,
                    sourceUrl: link[i].src,
                });
                console.log(`이미지 ${imgLists.length}개 감지`);
                emitEvent('images_found', {
                    episodeNumber: parseInt(link[i].num),
                    count: imgLists.length
                });
                let downloadTasks = [];
                let completedImages = 0;
                const reportImage = (imageIndex, skipped) => {
                    completedImages++;
                    emitEvent('image_saved', {
                        episodeNumber: parseInt(link[i].num),
                        imageIndex: imageIndex + 1,
                        current: completedImages,
                        total: imgLists.length,
                        skipped
                    });
                };
                // 이미지들을 다운로드한다.
                const episodePath = path.join(getContentPath(), episodeRecord.folderName);
                const existingImageIndexes = new Set();
                let hasLegacyImageFiles = false;
                if (fs.existsSync(episodePath)) {
                    for (const entry of fs.readdirSync(episodePath, { withFileTypes: true })) {
                        if (!entry.isFile())
                            continue;
                        const numbered = entry.name.match(/^(\d{4})\.[a-zA-Z0-9]+$/);
                        const legacy = entry.name.match(/image(\d{4})\.[a-zA-Z0-9]+$/i);
                        if (!numbered && !legacy)
                            continue;
                        const existingPath = path.join(episodePath, entry.name);
                        const validImage = existingImageFileIsValid(existingPath);
                        if (numbered && validImage)
                            existingImageIndexes.add(Number.parseInt(numbered[1]));
                        if (legacy) {
                            if (validImage)
                                existingImageIndexes.add(Number.parseInt(legacy[1]));
                            hasLegacyImageFiles = true;
                        }
                    }
                }
                const useLegacyImageNames = Boolean(link[i].legacyFolder || hasLegacyImageFiles);
                for (let j = 0; j < imgLists.length; j++) {
                    const imageNumber = j.toString().padStart(4, '0');
                    const fileName = useLegacyImageNames
                        ? `${link[i].num} ${safeEpisodeName} image${imageNumber}${imgLists[j].extension}`
                        : `${imageNumber}${imgLists[j].extension}`;
                    // 파일명만 같은 0 byte/손상 파일은 skip하지 않는다.
                    if (existingImageIndexes.has(j)) {
                        reportImage(j, true);
                    }
                    else {
                        downloadTasks.push(async () => {
                            await saveImage(episodePath, fileName, imgLists[j].src);
                            reportImage(j, false);
                        });
                    }
                }
                await runDownloadTasks(downloadTasks, info.imageConcurrency);
                emitEvent('episode_completed', {
                    index: i + 1,
                    total: link.length,
                    number: parseInt(link[i].num),
                    title: episodeRecord.displayTitle,
                    sourceTitle: link[i].fileName,
                    folderName: episodeRecord.folderName,
                    sourceId: episodeRecord.sourceId,
                });
                completedEpisodes.add(parseInt(link[i].num));
                if (episodeRecord.sourceId)
                    completedEpisodeIds.add(episodeRecord.sourceId);
                saveEpisodeState(completedEpisodes, completedEpisodeIds, episodeManifest);
            }
        }
        console.log('다운로드 완료');
        emitEvent('completed', {
            outputPath: getContentPath(),
            selectedEpisodes: link.length,
            skippedExistingEpisodes,
            scanMode: info.scanMode
        });
    } catch (error) {
        console.error(error);
        const diagnosis = classifyDownloaderError(error, {
            pageTitle: await page.title().catch(() => ''),
            pageUrl: page.url()
        });
        emitEvent('error', diagnosis);
        process.exitCode = 1;
    } finally {
        imageTransport.close();
        await browser.close().catch(() => {});
    }

}

const directEntryPath = process.argv[1] ? path.resolve(process.argv[1]) : '';
const directEntryCandidates = directEntryPath
    ? [directEntryPath, ...(path.extname(directEntryPath) ? [] : [`${directEntryPath}.js`])]
    : [];
const isDirectExecution = directEntryCandidates.some(candidate => (
    import.meta.url === pathToFileURL(candidate).href
));

if (isDirectExecution) {
    analyseArguments();
    configureNetworkRuntime();
    main();
}

export {
    existingImageFileIsValid,
    existingImageFileValidation,
    writeImageBufferAtomically,
};
