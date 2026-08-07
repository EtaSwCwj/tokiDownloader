const SUPPORTED_PROXY_PROTOCOLS = new Set([
    'http:',
    'https:',
    'socks:',
    'socks4:',
    'socks5:',
]);

function normalizeProxyUrl(value) {
    const raw = String(value ?? '').trim();
    if (!raw)
        return '';
    let parsed;
    try {
        parsed = new URL(raw);
    }
    catch (_error) {
        throw new Error('프록시 URL 형식이 잘못되었습니다.');
    }
    if (!SUPPORTED_PROXY_PROTOCOLS.has(parsed.protocol))
        throw new Error('프록시는 HTTP, HTTPS, SOCKS4 또는 SOCKS5만 지원합니다.');
    if (!parsed.hostname || parsed.search || parsed.hash || !['', '/'].includes(parsed.pathname))
        throw new Error('프록시 URL에는 호스트와 선택적 포트만 입력해주세요.');
    if (parsed.username || parsed.password)
        throw new Error('프록시 인증 정보는 URL에 저장할 수 없습니다.');
    return parsed.toString().replace(/\/$/, '');
}

function normalizeSpeedLimitKib(value) {
    const limit = Number(value ?? 0);
    if (!Number.isInteger(limit) || (limit !== 0 && (limit < 32 || limit > 1048576)))
        throw new Error('속도 제한은 0(무제한) 또는 32~1048576 KiB/s여야 합니다.');
    return limit;
}

function normalizeRequestDelayMs(value) {
    const delay = Number(value ?? 0);
    if (!Number.isInteger(delay) || delay < 0 || delay > 5000)
        throw new Error('요청 간격은 0~5000ms여야 합니다.');
    return delay;
}

function bandwidthDelayMs(byteCount, speedLimitKib) {
    const limit = normalizeSpeedLimitKib(speedLimitKib);
    if (!limit)
        return 0;
    return Math.ceil(Math.max(0, Number(byteCount) || 0) * 1000 / (limit * 1024));
}

class GlobalBandwidthLimiter {
    constructor(speedLimitKib = 0) {
        this.speedLimitKib = normalizeSpeedLimitKib(speedLimitKib);
        this.nextAvailableAt = 0;
    }

    async consume(byteCount) {
        const duration = bandwidthDelayMs(byteCount, this.speedLimitKib);
        if (!duration)
            return;
        const now = Date.now();
        const start = Math.max(now, this.nextAvailableAt);
        this.nextAvailableAt = start + duration;
        const wait = this.nextAvailableAt - now;
        if (wait > 0)
            await new Promise(resolve => setTimeout(resolve, wait));
    }
}

class RequestPacer {
    constructor(delayMs = 0) {
        this.delayMs = normalizeRequestDelayMs(delayMs);
        this.nextAvailableAt = 0;
    }

    async wait() {
        if (!this.delayMs)
            return;
        const now = Date.now();
        const start = Math.max(now, this.nextAvailableAt);
        this.nextAvailableAt = start + this.delayMs;
        const wait = start - now;
        if (wait > 0)
            await new Promise(resolve => setTimeout(resolve, wait));
    }
}

export {
    GlobalBandwidthLimiter,
    RequestPacer,
    SUPPORTED_PROXY_PROTOCOLS,
    bandwidthDelayMs,
    normalizeProxyUrl,
    normalizeRequestDelayMs,
    normalizeSpeedLimitKib,
};
