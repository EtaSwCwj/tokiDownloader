import test from 'node:test';
import assert from 'node:assert/strict';
import { hasArchivedEpisode, loadArchivedEpisodes } from '../downloader_archives.js';

test('archive completion requires the stable ID and does not reuse a title for a new ID', () => {
    const records = [{sourceId: '/manhwa/1', folderName: '작품 1화', sourceTitle: '작품 1화'}];
    assert.equal(hasArchivedEpisode(records, {sourceId: '/manhwa/1', folderName: 'renamed'}), true);
    assert.equal(hasArchivedEpisode(records, {sourceId: '/manhwa/2', folderName: '작품 1화', sourceTitle: '작품 1화', number: 1}), false);
    assert.equal(hasArchivedEpisode(records, {folderName: '작품 1화', sourceTitle: '작품 1화', number: 1}), true);
    assert.equal(hasArchivedEpisode(records, {folderName: '다른 작품 1화', sourceTitle: '작품 1화', number: 1}), false);
});

test('thousands of archive lookups index the catalog once', () => {
    let reads = 0;
    const records = Array.from({length: 10000}, (_, index) => ({
        get sourceId() { reads += 1; return `/manhwa/${index}`; },
        folderName: `작품 ${index}화`,
    }));
    for (let index = 0; index < 10000; index += 1) {
        assert.equal(hasArchivedEpisode(records, {sourceId: `/manhwa/${index}`}), true);
    }
    assert.ok(reads <= 20000, `unexpected repeated scans: ${reads}`);
});

test('absent archive catalog leaves normal completion unchanged', () => {
    assert.deepEqual(loadArchivedEpisodes('does-not-exist-archive-fixture'), []);
});
