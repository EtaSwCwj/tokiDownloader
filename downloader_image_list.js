import { setTimeout as delay } from 'node:timers/promises';
import { createDownloaderError, ERROR_CATEGORIES } from './downloader_errors.js';
import { EPISODE_IMAGE_SELECTOR } from './downloader_episodes.js';

export function incompleteImageList(reason, diagnostics = {}) {
    return createDownloaderError(`회차 이미지 목록을 확정하지 못했습니다: ${reason}`, {
        errorCode: 'incomplete_episode_image_list', category: ERROR_CATEGORIES.SITE_STRUCTURE,
        retryable: true, diagnostics: { reason, ...diagnostics },
        suggestion: '기존 이미지는 보존됩니다. 사이트 로딩이 정상일 때 작품 재검사를 실행하세요.',
    });
}

// Serialized into the browser. Hidden/lazy reader images are not discarded.
// Only explicit reader count attributes are trusted, never arbitrary page text.
export function inspectImageList(selector) {
    const nodes = Array.from(document.querySelectorAll(selector));
    const images = [], unresolved = [], counts = [];
    const roots = Array.from(document.querySelectorAll('.theme-viewer-images, .view-padding'));
    for (const root of roots) {
        for (const name of ['data-image-count', 'data-total-images']) {
            const raw = root.getAttribute(name);
            if (raw !== null) {
                if (!/^\d+$/.test(raw.trim()) || Number(raw) <= 0) unresolved.push(`invalid_${name}`);
                else counts.push(Number(raw));
            }
        }
    }
    for (const [index, node] of nodes.entries()) {
        try {
            const deferred = ['data-src', 'data-original', 'data-lazy-src', 'data-url']
                .map(name => node.getAttribute(name)).find(value => value?.trim());
            // Some old readers keep the /data path in a custom lazy attribute.
            const legacy = Array.from(node.attributes || [])
                .filter(attribute => attribute.name.startsWith('data-'))
                .map(attribute => attribute.value).find(value => /^\/?data\//.test(value));
            const sourceSet = node.getAttribute('data-srcset') || node.getAttribute('srcset');
            const fromSet = sourceSet?.split(',').map(value => value.trim().split(/\s+/))
                .sort((left, right) => (Number.parseFloat(right[1]) || 1) - (Number.parseFloat(left[1]) || 1))[0]?.[0];
            const raw = deferred || legacy || fromSet || node.currentSrc || node.getAttribute('src');
            if (!raw?.trim()) throw new Error('missing_source');
            const url = new URL(raw, location.href);
            if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
                throw new Error('unresolved_source');
            url.hash = '';
            const extension = url.pathname.match(/\.(?:jpe?g|png|gif|webp|bmp|avif)$/i)?.[0]?.toLowerCase() || '.jpg';
            images.push({ src: url.href, extension });
            // Native lazy loading and scroll-driven readers must get a chance to settle.
            if (node.loading === 'lazy') node.loading = 'eager';
        } catch (error) {
            unresolved.push({ index, reason: String(error.message || error) });
        }
    }
    const last = nodes.at(-1);
    if (last) last.scrollIntoView({ block: 'end', behavior: 'instant' });
    return { images, unresolved, expectedCounts: [...new Set(counts)], nodeCount: nodes.length,
        ready: document.readyState === 'complete',
        readerHeight: roots.reduce((sum, node) => sum + node.scrollHeight, 0) };
}

export function imageListKey(images) {
    return JSON.stringify(images.map(image => [image.src, image.extension]));
}

export async function collectEpisodeImages(page, {
    timeoutMs = 15000, stableMs = 1250, pollMs = 250, now = Date.now, wait = delay,
} = {}) {
    const started = now();
    let previous = '', stableSince = started, snapshot, reason = 'empty_list';
    while (now() - started <= timeoutMs) {
        let timer;
        try {
            snapshot = await Promise.race([
                page.evaluate(inspectImageList, EPISODE_IMAGE_SELECTOR),
                new Promise((_, reject) => {
                    timer = setTimeout(() => reject(incompleteImageList('browser_snapshot_timeout')),
                        Math.max(1, timeoutMs - (now() - started)));
                }),
            ]);
        } finally { clearTimeout(timer); }
        const counts = snapshot.expectedCounts || [];
        const complete = snapshot.ready && snapshot.images.length > 0 && !snapshot.unresolved.length
            && counts.every(count => count === snapshot.images.length);
        reason = !snapshot.ready ? 'document_loading' : snapshot.unresolved.length ? 'unresolved_sources'
            : !snapshot.images.length ? 'empty_list' : !counts.every(count => count === snapshot.images.length)
                ? 'declared_count_mismatch' : 'list_not_stable';
        const key = JSON.stringify([imageListKey(snapshot.images), snapshot.readerHeight, snapshot.nodeCount]);
        if (!complete || key !== previous) stableSince = now();
        if (complete && key === previous && now() - stableSince >= stableMs) return snapshot.images;
        previous = key;
        await wait(pollMs);
    }
    throw incompleteImageList(reason, { count: snapshot?.images.length || 0,
        expectedCounts: snapshot?.expectedCounts, unresolved: snapshot?.unresolved });
}
