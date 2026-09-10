import { createDownloaderError, ERROR_CATEGORIES } from './downloader_errors.js';

export const EPISODE_IMAGE_SELECTOR = '.view-padding div img, .theme-viewer-images img';
export const EPISODE_PROCESSING_MESSAGE = '이미지 처리 중인 회차입니다. 잠시 후 다시 확인해주세요.';

// Serialized into the browser: keep this function independent of module scope.
export function inspectEpisodeViewer(selector, processingMessage) {
    if (document.querySelector(selector)) return { status: 'ready' };
    const notice = document.querySelector('.theme-viewer-images .wr-none');
    const message = String(notice?.textContent || '').replace(/\s+/g, ' ').trim();
    if (message === processingMessage) return { status: 'processing', message };
    return false; // Unknown empty pages/auth failures retain the existing failure path.
}

export async function waitForEpisodeAvailability(page, { timeoutMs = 60000 } = {}) {
    const handle = await page.waitForFunction(inspectEpisodeViewer,
        { timeout: timeoutMs, polling: 250 }, EPISODE_IMAGE_SELECTOR, EPISODE_PROCESSING_MESSAGE);
    try { return await handle.jsonValue(); }
    finally { await handle.dispose(); }
}

export class PendingEpisodes {
    constructor(records = []) {
        this.byId = new Map();
        for (const record of Array.isArray(records) ? records : []) {
            if (record && typeof record.sourceId === 'string' && record.sourceId)
                this.byId.set(record.sourceId, { ...record });
        }
    }
    defer(record, message) {
        const value = { number: record.number, sourceId: record.sourceId,
            sourceUrl: record.sourceUrl, sourceTitle: record.sourceTitle,
            displayTitle: record.displayTitle, folderName: record.folderName,
            reason: 'site_episode_processing', message, checkedAt: new Date().toISOString() };
        this.byId.set(record.sourceId, value);
        return value;
    }
    resolve(sourceId) { this.byId.delete(sourceId); }
    get records() {
        return [...this.byId.values()].sort((a, b) => Number(a.number) - Number(b.number));
    }
    throwIfPending(completedThisRun, selectedEpisodes) {
        const pendingEpisodes = this.records;
        if (!pendingEpisodes.length) return;
        const titles = pendingEpisodes.slice(0, 5).map(item => item.displayTitle || item.sourceTitle).join(', ');
        throw createDownloaderError(
            `일부 미완료: 사이트 이미지 준비 중 ${pendingEpisodes.length}개 (${titles}${pendingEpisodes.length > 5 ? ' 외' : ''}). `
            + `이번 실행에서 다른 회차 ${completedThisRun}개 처리를 마쳤습니다. 나중에 신규 회차 검사로 다시 시도하세요.`,
            { errorCode: 'episodes_pending', category: ERROR_CATEGORIES.SOURCE, retryable: false,
                diagnostics: { pendingEpisodes, completedThisRun, selectedEpisodes },
                suggestion: '사이트 이미지 처리가 끝난 뒤 신규 회차 검사를 실행하면 미완료 회차만 다시 받습니다.' },
        );
    }
}
