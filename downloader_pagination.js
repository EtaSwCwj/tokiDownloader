import { normalizeAndSortEpisodeLinks } from './downloader_policy.js';

// Executed in the page as well as against local HTML fixtures. Never follow
// comment pagination, episode-reader links, or another work/domain.
export function readEpisodeListPage() {
    const modern = document.querySelector('.theme-episode-pager');
    const pagers = modern ? [modern] : [...document.querySelectorAll('ul.pagination')]
        .filter(node => !node.closest('#comment, #comment_list, .comments, .theme-comment-pager'));
    const rows = [...(document.querySelector('.list-body')?.querySelectorAll('li') || [])].map(row => {
        const anchor = row.querySelector('a');
        const subject = anchor?.cloneNode(true);
        subject?.querySelectorAll('span').forEach(node => node.remove());
        return { num: row.querySelector('.wr-num')?.textContent?.trim() || '',
            fileName: subject?.textContent?.trim() || '', src: anchor?.href || '' };
    });
    return { url: location.href, rows,
        pageLinks: pagers.flatMap(node => [...node.querySelectorAll('a[href]')].map(a => a.href)),
        expectedCount: Number(modern?.getAttribute('aria-label')?.match(/총\s*([\d,]+)회/)?.[1]?.replaceAll(',', '')) || 0 };
}

export function episodeListPageUrl(raw, base, parameter = null) {
    try {
        const url = new URL(raw, base), work = new URL(base);
        if (url.origin !== work.origin || url.pathname.replace(/\/$/, '') !== work.pathname.replace(/\/$/, '')
            || url.username || url.password || url.hash) return null;
        const key = parameter || (url.searchParams.has('epage') ? 'epage' : 'page');
        const number = url.searchParams.get(key) || '1';
        if (!/^[1-9]\d*$/.test(number) || !Number.isSafeInteger(Number(number))) return null;
        if (parameter && !url.searchParams.has(key) && url.searchParams.has(key === 'epage' ? 'page' : 'epage')) return null;
        url.search = '';
        if (Number(number) > 1) url.searchParams.set(key, number);
        return url.href;
    } catch { return null; }
}

export async function collectEpisodeListPages(page, { beforeNavigate = async () => {}, onPage = () => {}, maxPages = 10000 } = {}) {
    const base = page.url();
    const visited = new Set(), queued = new Set(), fingerprints = new Set();
    const pending = [], rows = [];
    let expectedCount = 0, parameter;
    while (true) {
        await page.waitForSelector('.list-body', { timeout: 40000 });
        const snapshot = await page.evaluate(readEpisodeListPage);
        parameter ||= snapshot.pageLinks.some(raw => new URL(raw, base).searchParams.has('epage')) ? 'epage' : 'page';
        const current = episodeListPageUrl(snapshot.url, base, parameter);
        if (!current) throw new Error('회차 목록 탐색 중 다른 작품/주소로 이동했습니다.');
        if (visited.has(current)) throw new Error('회차 목록 페이지가 반복되었습니다. 전체 수집을 중단합니다.');
        visited.add(current);
        const valid = normalizeAndSortEpisodeLinks(snapshot.rows).links;
        if (!valid.length) throw new Error('회차 목록 페이지에 유효한 회차가 없습니다. 전체 수집을 중단합니다.');
        const signature = JSON.stringify(valid.map(row => row.src).sort());
        if (fingerprints.has(signature)) throw new Error('서로 다른 목록 페이지에 같은 회차만 반환되었습니다. 전체 수집을 중단합니다.');
        fingerprints.add(signature);
        rows.push(...snapshot.rows);
        expectedCount = Math.max(expectedCount, snapshot.expectedCount || 0);
        onPage({ pageCount: visited.size, rowCount: rows.length, expectedCount, url: current });
        for (const raw of snapshot.pageLinks) {
            const next = episodeListPageUrl(raw, base, parameter);
            if (next && !visited.has(next) && !queued.has(next)) { pending.push(next); queued.add(next); }
        }
        if (!pending.length) break;
        if (visited.size >= maxPages) throw new Error('회차 목록 페이지 안전 한도를 초과했습니다. 일부 목록으로 다운로드하지 않습니다.');
        await beforeNavigate();
        await page.goto(pending.shift(), { waitUntil: 'domcontentloaded' });
    }
    const count = normalizeAndSortEpisodeLinks(rows).links.length;
    if (expectedCount && count < expectedCount)
        throw new Error(`회차 목록이 불완전합니다: 사이트 ${expectedCount}개 중 ${count}개 수집. 다운로드를 중단합니다.`);
    return { rows, pageCount: visited.size, expectedCount, count };
}
