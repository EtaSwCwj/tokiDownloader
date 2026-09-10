export const ERROR_CATEGORIES = Object.freeze({
    AUTHENTICATION_REQUIRED: 'authentication_required',
    RATE_LIMITED: 'rate_limited',
    NETWORK: 'network',
    SITE_STRUCTURE: 'site_structure',
    FILESYSTEM: 'filesystem',
    SOURCE: 'source',
    UNKNOWN: 'unknown'
});

const ERROR_CATEGORY_VALUES = new Set(Object.values(ERROR_CATEGORIES));


export function createDownloaderError(
    message,
    {
        errorCode = '',
        category = ERROR_CATEGORIES.UNKNOWN,
        retryable = true,
        diagnostics = {},
        suggestion = '',
    } = {},
) {
    const error = new Error(String(message || '다운로더 오류'));
    error.name = 'DownloaderError';
    error.errorCode = String(errorCode || '');
    error.category = ERROR_CATEGORY_VALUES.has(category)
        ? category
        : ERROR_CATEGORIES.UNKNOWN;
    error.retryable = Boolean(retryable);
    error.diagnostics = diagnostics && typeof diagnostics === 'object'
        ? { ...diagnostics }
        : {};
    error.suggestion = String(suggestion || '');
    return error;
}


export function classifyDownloaderError(error, context = {}) {
    const message = String(error?.stack || error || '');
    const evidence = `${message}\n${context.pageTitle || ''}\n${context.pageUrl || ''}`.toLowerCase();
    const declaredCategory = ERROR_CATEGORY_VALUES.has(error?.category)
        ? error.category
        : '';
    let category = declaredCategory || ERROR_CATEGORIES.UNKNOWN;
    let retryable = typeof error?.retryable === 'boolean'
        ? error.retryable
        : true;

    if (declaredCategory) {
        // Structured errors from naming/path validation are authoritative.  In
        // particular, they must not enter the process-level retry loop.
    }
    else if (/cloudflare|captcha|turnstile|checking your browser|just a moment|cf-chl|challenge-platform|access denied|http 403/.test(evidence)) {
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
    else if (/enoent|eacces|eperm|enospc|enametoolong|path too long|filename or extension is too long|windows 안전 길이|read-only file system/.test(evidence)) {
        category = ERROR_CATEGORIES.FILESYSTEM;
        retryable = false;
    }

    return {
        category,
        retryable,
        errorCode: String(error?.errorCode || error?.code || ''),
        message,
        pageTitle: String(context.pageTitle || ''),
        pageUrl: String(context.pageUrl || ''),
        diagnostics: error?.diagnostics && typeof error.diagnostics === 'object'
            ? { ...error.diagnostics }
            : {},
        suggestion: String(error?.suggestion || ''),
    };
}
