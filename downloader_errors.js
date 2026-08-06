export const ERROR_CATEGORIES = Object.freeze({
    AUTHENTICATION_REQUIRED: 'authentication_required',
    RATE_LIMITED: 'rate_limited',
    NETWORK: 'network',
    SITE_STRUCTURE: 'site_structure',
    FILESYSTEM: 'filesystem',
    UNKNOWN: 'unknown'
});


export function classifyDownloaderError(error, context = {}) {
    const message = String(error?.stack || error || '');
    const evidence = `${message}\n${context.pageTitle || ''}\n${context.pageUrl || ''}`.toLowerCase();
    let category = ERROR_CATEGORIES.UNKNOWN;
    let retryable = true;

    if (/cloudflare|captcha|turnstile|checking your browser|just a moment|cf-chl|challenge-platform|access denied|http 403/.test(evidence)) {
        category = ERROR_CATEGORIES.AUTHENTICATION_REQUIRED;
        retryable = false;
    }
    else if (/http 429|too many requests|rate.?limit/.test(evidence)) {
        category = ERROR_CATEGORIES.RATE_LIMITED;
    }
    else if (/timeout|timed out|net::|err_|econn|enotfound|fetch failed|socket|network/.test(evidence)) {
        category = ERROR_CATEGORIES.NETWORK;
    }
    else if (/waiting for selector|failed to find element|list-body|queryselector|null/.test(evidence)) {
        category = ERROR_CATEGORIES.SITE_STRUCTURE;
        retryable = false;
    }
    else if (/enoent|eacces|eperm|enospc|read-only file system/.test(evidence)) {
        category = ERROR_CATEGORIES.FILESYSTEM;
        retryable = false;
    }

    return {
        category,
        retryable,
        message,
        pageTitle: String(context.pageTitle || ''),
        pageUrl: String(context.pageUrl || '')
    };
}
