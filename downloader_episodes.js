export const EPISODE_IMAGE_SELECTOR = '.view-padding div img, .theme-viewer-images img';
export const EPISODE_PROCESSING_MESSAGE = '이미지 처리 중인 회차입니다. 잠시 후 다시 확인해주세요.';

// Do not mistake an HTML login/error response, timeout, or local disk failure for
// a damaged source image. Only known image payloads rejected on every retry qualify.
const DAMAGED_IMAGE_REASONS = new Set([
    'extension_signature_mismatch', 'missing_end_marker', 'jpeg_decode_failed',
    'invalid_webp_size', 'invalid_webp_chunks',
]);

export function isDamagedImageError(error) {
    return error?.code === 'invalid_image_payload'
        && ['jpeg', 'png', 'gif', 'webp', 'bmp', 'avif'].includes(error.diagnostics?.detectedFormat)
        && DAMAGED_IMAGE_REASONS.has(error.diagnostics?.reason);
}

export function imageFailureDeferral(error) {
    if (error?.code !== 'image_downloads_failed' || !Array.isArray(error.errors)
        || !error.errors.length || !error.errors.every(item => item.code === 'source_image_unavailable'))
        return null;
    return {
        reason: 'source_image_validation_failed',
        message: `이미지 검증 실패 ${error.errors.length}장. 정상 수신 이미지는 보존하고 다음 회차를 진행합니다.`,
        failedImages: error.errors.map(item => ({ ...item.diagnostics })),
    };
}

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
    defer(record, message, { reason = 'site_episode_processing', failedImages = [] } = {}) {
        const value = { number: record.number, sourceId: record.sourceId,
            sourceUrl: record.sourceUrl, sourceTitle: record.sourceTitle,
            displayTitle: record.displayTitle, folderName: record.folderName,
            reason, message, checkedAt: new Date().toISOString() };
        if (failedImages.length) value.failedImages = failedImages;
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
                ? `미수신 ${pendingEpisodes.length}개: ${titles}${pendingEpisodes.length > 5 ? ' 외' : ''}. 사이트 원본이 준비되거나 수정된 후 신규 회차 검사로 다시 받을 수 있습니다.`
                : '' };
    }
}
