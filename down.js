import { connect } from "puppeteer-real-browser";
import fs from 'node:fs';
import path from 'node:path';
import { selectEpisodeLinks } from './downloader_policy.js';
import { classifyDownloaderError } from './downloader_errors.js';
import {
    DEFAULT_FOLDER_TEMPLATE,
    renderFolderTemplate,
    sanitizePathSegment,
} from './downloader_naming.js';

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
    scanMode: ''
}

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
    console.log(`사용법: node down -url "URL" [-scan-mode new|full|range] [-start STARTINDEX] [-last LASTINDEX] [-output "폴더 경로"] [-folder-template "[{author}][{group}] {title}"] [-show-browser] [-image-concurrency 1~16] [-metadata-only] [-content-path "기존 작품 폴더"] [-json-events]`);
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
function buildContentFolderName(metadata) {
    return renderFolderTemplate(info.folderTemplate, metadata);
}
function getContentPath() {
    return info.contentPathOverride || path.join(info.outputDir, info.siteTitle, info.contentFolderName);
}
function completionStatePath() {
    return path.join(getContentPath(), '.toki-state.json');
}
function physicalEpisodeNumbers() {
    const contentPath = getContentPath();
    if (!fs.existsSync(contentPath))
        return new Set();
    const episodes = new Set();
    for (const entry of fs.readdirSync(contentPath, { withFileTypes: true })) {
        const matched = entry.name.match(/^0*(\d+)(?:\s|$)/);
        if (matched)
            episodes.add(parseInt(matched[1]));
    }
    return episodes;
}
function loadCompletedEpisodeNumbers() {
    const physical = physicalEpisodeNumbers();
    const statePath = completionStatePath();
    if (!fs.existsSync(statePath))
        return physical;
    try {
        const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
        return new Set((state.completedEpisodes || [])
            .map(Number)
            .filter(number => Number.isInteger(number) && physical.has(number)));
    }
    catch (error) {
        console.log(`회차 완료 상태 읽기 실패, 기존 파일로 복구: ${error.message || error}`);
        return physical;
    }
}
function saveCompletedEpisodeNumbers(completedEpisodes) {
    const contentPath = getContentPath();
    fs.mkdirSync(contentPath, { recursive: true });
    fs.writeFileSync(completionStatePath(), `${JSON.stringify({
        version: 1,
        completedEpisodes: [...completedEpisodes].sort((a, b) => a - b),
        updatedAt: new Date().toISOString()
    }, null, 2)}\n`, 'utf8');
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
async function saveImage(path, fileName, src) {
    let imageBuffer;
    let lastError;
    for (let attempt = 1; attempt <= 3; attempt++) {
        try {
            const response = await fetch(src, {
                headers: {
                    'User-Agent': 'Mozilla/5.0',
                    'Referer': `${info.protocolDomain}/`
                }
            });
            if (!response.ok)
                throw new Error(`HTTP ${response.status}`);
            imageBuffer = Buffer.from(await response.arrayBuffer());
            break;
        }
        catch (error) {
            lastError = error;
            if (attempt < 3)
                await sleep(attempt * 1000);
        }
    }
    if (!imageBuffer)
        throw new Error(`이미지 다운로드 실패: ${src}\n${lastError}`);
    // 경로가 없다면 만들기
    if (!fs.existsSync(path))
        fs.mkdirSync(path, { recursive: true });
    fs.writeFileSync(`${path}/${fileName}`, imageBuffer);
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
        args: [],
        customConfig: {},
        turnstile: true, //captcha를 자동으로 풀것인지
        connectOption: { defaultViewport: null },
        disableXvfb: false, //화면을 볼것인지
    })
    try {
        // await page.goto('https://booktoki350.com/');
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
                    list[i] = {
                        num: list[i].querySelector('.wr-num').innerText.padStart(4, '0'),
                        fileName: list[i].querySelector('a').innerHTML.replace(/<span[\s\S]*?\/span>/g, '').trim(),
                        src: list[i].querySelector('a').href
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
        // 1화부터 받을것이기 때문에 리버스 해준다.
        link.reverse();
        const totalEpisodeCount = link.length;
        let completedEpisodes = new Set();
        let skippedExistingEpisodes = 0;
        if (!info.metadataOnly) {
            completedEpisodes = loadCompletedEpisodeNumbers();
        }
        const selection = selectEpisodeLinks(link, {
            metadataOnly: info.metadataOnly,
            scanMode: info.scanMode,
            startIndex: info.startIndex,
            lastIndex: info.lastIndex,
            completedEpisodes
        });
        link = selection.links;
        skippedExistingEpisodes = selection.skippedExistingEpisodes;
        if (!info.metadataOnly && info.scanMode === 'new') {
            saveCompletedEpisodeNumbers(completedEpisodes);
        }
        if (!info.metadataOnly && info.scanMode !== 'new' && link.length === 0)
            throw new Error('지정한 범위에 해당하는 회차가 없습니다.');
        info.metadata.folderName = info.contentFolderName;
        info.metadata.episodeCount = totalEpisodeCount;
        info.metadata.selectedEpisodeCount = link.length;
        info.metadata.requestedRange = {
            start: info.startIndex === 0 ? null : info.startIndex,
            last: info.lastIndex === 99999 ? null : info.lastIndex
        };
        info.metadata.scanMode = info.metadataOnly ? 'metadata' : info.scanMode;
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
            await Promise.all([page.goto(link[i].src), page.waitForNavigation()]);
            await sleep(2000);
            const safeEpisodeName = sanitizePathSegment(link[i].fileName, '회차');
            console.log(`${link[i].num} ${link[i].fileName} 진행중`);
            emitEvent('episode_started', {
                index: i + 1,
                total: link.length,
                number: parseInt(link[i].num),
                title: link[i].fileName
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
                    title: link[i].fileName
                });
                completedEpisodes.add(parseInt(link[i].num));
                saveCompletedEpisodeNumbers(completedEpisodes);
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
                }, imageSelector)
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
                for (let j = 0; j < imgLists.length; j++) {
                    const episodePath = path.join(getContentPath(), `${link[i].num} ${safeEpisodeName}`);
                    const fileName = `${link[i].num} ${safeEpisodeName} image${j.toString().padStart(4, '0')}${imgLists[j].extension}`;
                    // 이미지 다운. 있다면 다운하지 않는다.
                    if (fs.existsSync(path.join(episodePath, fileName))) {
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
                    title: link[i].fileName
                });
                completedEpisodes.add(parseInt(link[i].num));
                saveCompletedEpisodeNumbers(completedEpisodes);
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
        await browser.close().catch(() => {});
    }

}

analyseArguments();
main();
