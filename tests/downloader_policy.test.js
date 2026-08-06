import test from 'node:test';
import assert from 'node:assert/strict';

import { selectEpisodeLinks } from '../downloader_policy.js';


const links = [1, 2, 3, 4, 5].map(number => ({
    num: String(number).padStart(4, '0'),
    src: `https://example.test/${number}`
}));


test('new mode selects only episodes absent from completion state', () => {
    const result = selectEpisodeLinks(links, {
        scanMode: 'new',
        completedEpisodes: new Set([1, 2, 4])
    });
    assert.deepEqual(result.links.map(item => parseInt(item.num)), [3, 5]);
    assert.equal(result.skippedExistingEpisodes, 3);
});


test('new mode may complete successfully with an empty selection', () => {
    const result = selectEpisodeLinks(links, {
        scanMode: 'new',
        completedEpisodes: new Set([1, 2, 3, 4, 5])
    });
    assert.equal(result.links.length, 0);
    assert.equal(result.skippedExistingEpisodes, 5);
});


test('full and range modes have distinct selection rules', () => {
    const full = selectEpisodeLinks(links, { scanMode: 'full' });
    const ranged = selectEpisodeLinks(links, {
        scanMode: 'range', startIndex: 2, lastIndex: 4
    });
    assert.deepEqual(full.links.map(item => parseInt(item.num)), [1, 2, 3, 4, 5]);
    assert.deepEqual(ranged.links.map(item => parseInt(item.num)), [2, 3, 4]);
});


test('metadata mode never selects episode pages', () => {
    const result = selectEpisodeLinks(links, { metadataOnly: true, scanMode: 'full' });
    assert.equal(result.links.length, 0);
});
