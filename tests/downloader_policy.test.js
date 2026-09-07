import test from 'node:test';
import assert from 'node:assert/strict';
import webpSamples from './fixtures/webp_validation_samples.json' with { type: 'json' };

import {
    detectImageFormat,
    episodeStateUsesStableIds,
    normalizeAndSortEpisodeLinks,
    requireEpisodeImages,
    resolveEpisodeCompletion,
    selectEpisodeLinks,
    validateImageBuffer,
} from '../downloader_policy.js';


const links = [1, 2, 3, 4, 5].map(number => ({
    num: String(number).padStart(4, '0'),
    src: `https://example.test/${number}`
}));

const imageSignatures = new Map([
    ['.jpg', Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0xff, 0xd9])],
    ['.png', Buffer.from([
        0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
        0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44,
        0xae, 0x42, 0x60, 0x82,
    ])],
    ['.gif', Buffer.from('GIF89a', 'ascii')],
    ['.webp', Buffer.from(webpSamples.lossy, 'base64')],
    ['.bmp', Buffer.from('BM', 'ascii')],
    ['.avif', Buffer.concat([
        Buffer.from([0x00, 0x00, 0x00, 0x18]),
        Buffer.from('ftypavif', 'ascii'),
        Buffer.from([0x00, 0x00, 0x00, 0x00]),
        Buffer.from('avif', 'ascii'),
    ])],
]);


test('supported image signatures must be non-empty and match their extension', () => {
    for (const [extension, signature] of imageSignatures) {
        const result = validateImageBuffer(signature, extension);
        assert.equal(result.valid, true, extension);
        assert.equal(detectImageFormat(signature), result.expectedFormat, extension);
    }
    assert.deepEqual(
        validateImageBuffer(Buffer.alloc(0), '.jpg').reason,
        'empty_image',
    );
    assert.equal(
        validateImageBuffer(Buffer.from('<html>blocked</html>'), '.jpg').reason,
        'invalid_signature',
    );
    assert.equal(
        validateImageBuffer(imageSignatures.get('.png'), '.jpg').reason,
        'extension_signature_mismatch',
    );
    assert.equal(
        validateImageBuffer(imageSignatures.get('.jpg'), '.txt').reason,
        'unsupported_extension',
    );
    assert.equal(
        validateImageBuffer(Buffer.from([0xff, 0xd8, 0xff, 0xe0]), '.jpg').reason,
        'missing_end_marker',
    );
    assert.equal(
        validateImageBuffer(
            Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
            '.png',
        ).reason,
        'missing_end_marker',
    );
});


test('an episode with zero usable DOM images fails terminally before completion', () => {
    assert.throws(
        () => requireEpisodeImages([], {
            episodeNumber: 27,
            sourceId: '/manhwa/1/episode-27',
            sourceUrl: 'https://example.test/episode-27',
        }),
        error => (
            error?.errorCode === 'empty_episode_images'
            && error?.category === 'site_structure'
            && error?.retryable === false
            && error?.diagnostics?.episodeNumber === 27
        ),
    );
    const images = [{ src: 'https://example.test/1.jpg', extension: '.jpg' }];
    assert.equal(requireEpisodeImages(images), images);
});


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

test('new mode prefers stable source ids when v2 state is available', () => {
    const shifted = [
        { num: '0001', sourceId: '/manhwa/1/new-first' },
        { num: '0002', sourceId: '/manhwa/1/kept' },
    ];
    const result = selectEpisodeLinks(shifted, {
        scanMode: 'new',
        completedEpisodes: new Set([1]),
        completedEpisodeIds: new Set(['/manhwa/1/kept']),
        preferEpisodeIds: true,
    });
    assert.deepEqual(result.links.map(item => item.sourceId), ['/manhwa/1/new-first']);
    assert.equal(result.skippedExistingEpisodes, 1);
});

test('partial v2 ids never apply a numeric fallback to an identified current episode', () => {
    const partial = [
        { num: '0001', sourceId: '/manhwa/1/known' },
        { num: '0002', sourceId: '/manhwa/1/legacy-without-id' },
        { num: '0003', sourceId: '/manhwa/1/new' },
    ];
    const result = selectEpisodeLinks(partial, {
        scanMode: 'new',
        completedEpisodes: new Set([1, 2]),
        completedEpisodeIds: new Set(['/manhwa/1/known']),
        completedEpisodeFallbacks: new Set([2]),
        preferEpisodeIds: true,
    });
    assert.deepEqual(result.links.map(item => item.sourceId), [
        '/manhwa/1/legacy-without-id',
        '/manhwa/1/new',
    ]);
    assert.equal(result.skippedExistingEpisodes, 1);
});

test('partial v2 completion keeps a reused ordinal with a new id incomplete', () => {
    const state = {
        exists: true,
        version: 2,
        completedEpisodes: [1, 2],
        completedEpisodeIds: ['/manhwa/1/old'],
        episodes: [
            { number: 1, sourceId: '/manhwa/1/old' },
            { number: 2, sourceId: '' },
        ],
    };
    const current = [
        { num: '0001', sourceId: '/manhwa/1/new', storageExists: true },
        { num: '0002', sourceId: '', storageExists: true },
    ];
    const completion = resolveEpisodeCompletion(state, current, {
        physicalNumbers: new Set([1, 2]),
        physicalEpisodeIds: new Set(['/manhwa/1/old', '/manhwa/1/new']),
    });

    assert.deepEqual([...completion.completedEpisodeIds], ['/manhwa/1/old']);
    assert.deepEqual([...completion.completedEpisodeFallbacks], [2]);
    const selection = selectEpisodeLinks(current, {
        scanMode: 'new',
        ...completion,
        preferEpisodeIds: true,
    });
    assert.deepEqual(selection.links.map(item => item.sourceId), ['/manhwa/1/new']);
    assert.equal(selection.skippedExistingEpisodes, 1);
});

test('legacy numeric completion requires a verified original-title match', () => {
    const state = {
        exists: true,
        version: 1,
        completedEpisodeIdsPresent: false,
        completedEpisodes: [1],
        completedEpisodeIds: [],
        episodes: [],
    };
    const current = [
        {
            num: '0001',
            sourceId: '/manhwa/1/shifted',
            storageExists: true,
            numericFallbackVerified: false,
        },
    ];
    const unsafe = resolveEpisodeCompletion(state, current, {
        physicalNumbers: new Set([1]),
        physicalEpisodeIds: new Set(['/manhwa/1/shifted']),
    });
    assert.deepEqual([...unsafe.completedEpisodeIds], []);
    assert.deepEqual([...unsafe.completedEpisodeFallbacks], []);

    const safe = resolveEpisodeCompletion(
        state,
        [{ ...current[0], numericFallbackVerified: true }],
        {
            physicalNumbers: new Set([1]),
            physicalEpisodeIds: new Set(['/manhwa/1/shifted']),
        },
    );
    assert.deepEqual([...safe.completedEpisodeIds], ['/manhwa/1/shifted']);
    assert.deepEqual([...safe.completedEpisodeFallbacks], []);
    const selection = selectEpisodeLinks(
        [
            { ...current[0], numericFallbackVerified: true },
            {
                num: '0001',
                sourceId: '/manhwa/1/new-at-same-ordinal',
                storageExists: false,
                numericFallbackVerified: false,
            },
        ],
        { scanMode: 'new', ...safe, preferEpisodeIds: false },
    );
    assert.deepEqual(
        selection.links.map(item => item.sourceId),
        ['/manhwa/1/new-at-same-ordinal'],
    );
});

test('an unverified physical number never skips a newly named episode', () => {
    const result = selectEpisodeLinks(
        [{ num: '2024', sourceId: '/manhwa/1/new-2024' }],
        {
            scanMode: 'new',
            completedEpisodes: new Set([2024]),
            completedEpisodeIds: new Set(),
            completedEpisodeFallbacks: new Set(),
            preferEpisodeIds: false,
        },
    );
    assert.equal(result.links.length, 1);
});

test('episode links are numerically sorted and invalid notice rows are skipped', () => {
    const result = normalizeAndSortEpisodeLinks([
        { num: '10', src: 'https://example.test/episode-10' },
        { num: '공지', src: 'https://example.test/notice' },
        { num: '2', src: 'https://example.test/episode-2' },
        { num: '0', src: 'https://example.test/invalid-zero' },
        { num: '1', src: 'https://example.test/episode-1' },
    ]);
    assert.deepEqual(result.links.map(item => item.num), ['0001', '0002', '0010']);
    assert.deepEqual(result.links.map(item => item.src), [
        'https://example.test/episode-1',
        'https://example.test/episode-2',
        'https://example.test/episode-10',
    ]);
    assert.deepEqual(result.skipped.map(item => item.rawNumber), ['공지', '0']);
});

test('episode links reject invalid URLs and deterministically deduplicate source ids', () => {
    const result = normalizeAndSortEpisodeLinks([
        { num: '2', src: 'https://mirror.test/manhwa/10/same?from=page-2' },
        { num: '1', src: 'https://mirror.test/manhwa/10/same?from=page-1' },
        { num: '3', src: '' },
        { num: '4', src: 'javascript:void(0)' },
        { num: '5', src: 'https://mirror.test/manhwa/10/unique' },
    ]);

    assert.deepEqual(result.links.map(item => item.num), ['0001', '0005']);
    assert.deepEqual(result.links.map(item => item.sourceId), [
        '/manhwa/10/same',
        '/manhwa/10/unique',
    ]);
    assert.deepEqual(result.skipped.map(item => item.reason), [
        'invalid_episode_url',
        'invalid_episode_url',
        'duplicate_episode_source',
    ]);
    assert.equal(result.skipped.at(-1).num, '0002');
});

test('stable-id preference comes from persisted state even when no id is physically matched', () => {
    const state = {
        completedEpisodes: [1],
        completedEpisodeIds: ['/manhwa/1/old'],
        episodes: [{ number: 1, sourceId: '/manhwa/1/old' }],
    };
    assert.equal(episodeStateUsesStableIds(state), true);
    const result = selectEpisodeLinks(
        [{ num: '0001', sourceId: '/manhwa/1/new' }],
        {
            scanMode: 'new',
            completedEpisodes: new Set([1]),
            completedEpisodeIds: new Set(),
            completedEpisodeFallbacks: new Set(),
            preferEpisodeIds: episodeStateUsesStableIds(state),
        },
    );
    assert.equal(result.links.length, 1);
    assert.equal(result.skippedExistingEpisodes, 0);
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
