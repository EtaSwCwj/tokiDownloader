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
    completionSummary(completedThisRun, selectedEpisodes) {
        const pendingEpisodes = this.records;
        const titles = pendingEpisodes.slice(0, 5).map(item => item.displayTitle || item.sourceTitle).join(', ');
        return { pendingEpisodeCount: pendingEpisodes.length, pendingEpisodes,
            completedThisRun, selectedEpisodes,
            completionNote: pendingEpisodes.length
                ? `미수신 ${pendingEpisodes.length}개: ${titles}${pendingEpisodes.length > 5 ? ' 외' : ''}. 사이트 이미지 준비 후 신규 회차 검사로 다시 받을 수 있습니다.`
                : '' };
    }
}
