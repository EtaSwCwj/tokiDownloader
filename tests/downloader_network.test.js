import test from 'node:test';
import assert from 'node:assert/strict';

import {
    bandwidthDelayMs,
    normalizeProxyUrl,
    normalizeRequestDelayMs,
    normalizeSpeedLimitKib,
} from '../downloader_network.js';

test('proxy URLs accept HTTP and SOCKS without persisted credentials', () => {
    assert.equal(normalizeProxyUrl('http://127.0.0.1:8080'), 'http://127.0.0.1:8080');
    assert.equal(normalizeProxyUrl('socks5://localhost:1080'), 'socks5://localhost:1080');
    assert.throws(() => normalizeProxyUrl('ftp://localhost:21'), /HTTP/);
    assert.throws(() => normalizeProxyUrl('http://user:secret@localhost:8080'), /인증/);
});

test('speed and request pacing have bounded deterministic plans', () => {
    assert.equal(normalizeSpeedLimitKib(0), 0);
    assert.equal(normalizeSpeedLimitKib(1024), 1024);
    assert.equal(bandwidthDelayMs(1024 * 1024, 1024), 1000);
    assert.equal(normalizeRequestDelayMs(250), 250);
    assert.throws(() => normalizeSpeedLimitKib(1), /32/);
    assert.throws(() => normalizeRequestDelayMs(6000), /5000/);
});
