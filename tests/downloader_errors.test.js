import test from 'node:test';
import assert from 'node:assert/strict';

import { classifyDownloaderError } from '../downloader_errors.js';


test('Cloudflare and challenge pages require authentication without blind retry', () => {
    const result = classifyDownloaderError(new Error('인증 확인 시간 초과'), {
        pageTitle: 'Just a moment... | Cloudflare',
        pageUrl: 'https://example.test/cdn-cgi/challenge-platform/'
    });
    assert.equal(result.category, 'authentication_required');
    assert.equal(result.retryable, false);
});


test('ordinary navigation timeout is classified as retryable network failure', () => {
    const result = classifyDownloaderError(new Error('Navigation timeout of 30000 ms exceeded'));
    assert.equal(result.category, 'network');
    assert.equal(result.retryable, true);
});


test('rate limits and filesystem errors remain distinct', () => {
    assert.equal(classifyDownloaderError(new Error('HTTP 429')).category, 'rate_limited');
    const filesystem = classifyDownloaderError(new Error('EACCES: permission denied'));
    assert.equal(filesystem.category, 'filesystem');
    assert.equal(filesystem.retryable, false);
});
