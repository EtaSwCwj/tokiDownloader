import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
    DEFAULT_FOLDER_TEMPLATE,
    buildEpisodeDisplayTitle,
    buildEpisodeFolderName,
    buildEpisodeManifestRecord,
    buildInferredEpisodeTitleIndex,
    canReuseLegacyEpisodeFolder,
    episodeSourceId,
    episodeRecordFolderCandidates,
    episodeSourceTitlesMatch,
    extractEpisodeSuffix,
    findUniqueInferredEpisodeMatch,
    isLegacyEpisodeFolderCandidate,
    mergeEpisodeManifestRecords,
    orderedEpisodeFolderName,
    renderFolderTemplate,
    resolveEpisodeCollectionNames,
    sanitizePathSegment,
    uniqueEpisodeFolderName,
    validateEpisodeDestinationPath,
    validateFolderTemplate,
    windowsUtf16Units,
} from '../downloader_naming.js';
import { classifyDownloaderError } from '../downloader_errors.js';

const episodeSuffixCases = JSON.parse(fs.readFileSync(
    new URL('./fixtures/episode_suffix_cases.json', import.meta.url),
    'utf8',
));

const sample = {
    author: '이요미네 츠쿠',
    group: 'N／A',
    title: '이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건',
    source: { siteTitle: '마나토끼', workId: '34360' },
};

test('saved folder order precedes title variation and keeps decimal/split labels', () => {
    const titles = ['축약…제목 1화', '전체 제목 2화', '다른 표기 2.2화', '작품 2.5화', '작품 3-1화', '작품 3-2화', '외전'];
    const folders = titles.map((title, index) => orderedEpisodeFolderName(index + 1, title));
    assert.deepEqual([...folders].sort(), folders);
    assert.equal(folders[3], '000004 작품 2.5화');
    assert.equal(folders[5], '000006 작품 3-2화');
    assert.equal(orderedEpisodeFolderName(10000, '작품 9999화'), '010000 작품 9999화');
    for (const value of [0, -1, 0.2, 1000000]) assert.throws(() => orderedEpisodeFolderName(value, '작품'), /순번/);
});

test('default folder template preserves the requested author group title rule', () => {
    assert.equal(
        renderFolderTemplate(DEFAULT_FOLDER_TEMPLATE, sample),
        '[이요미네 츠쿠][N／A] 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건',
    );
});

test('custom template supports stable site and work id fields', () => {
    assert.equal(
        renderFolderTemplate('[{site}][{id}] {title}', sample),
        '[마나토끼][34360] 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건',
    );
});

test('metadata values are sanitized and reserved Windows names are protected', () => {
    assert.equal(sanitizePathSegment('작가:*?'), '작가');
    assert.equal(sanitizePathSegment('CON'), '_CON');
});

test('unknown fields, invalid literals, and missing title are rejected', () => {
    assert.throws(() => validateFolderTemplate('{publisher} {title}'), /지원하지 않는/);
    assert.throws(() => validateFolderTemplate('{author}/{title}'), /금지 문자/);
    assert.throws(() => validateFolderTemplate('[{author}]'), /title/);
});

test('episode folder names restore the full work title and keep the episode suffix', () => {
    const workTitle = '남녀비 1:39의 평행세계는 의외로 평범';
    assert.equal(
        extractEpisodeSuffix(workTitle, '남녀비 1:39의 …로 평범 287화', 272),
        '287화',
    );
    assert.equal(
        buildEpisodeDisplayTitle(workTitle, '남녀비 139의 …로 평범 287화', 272),
        '남녀비 1:39의 평행세계는 의외로 평범 287화',
    );
    assert.equal(
        buildEpisodeDisplayTitle(workTitle, '남녀비 1:39의 …로 평범 1~5화', 1),
        '남녀비 1:39의 평행세계는 의외로 평범 1~5화',
    );
    assert.equal(
        buildEpisodeFolderName(workTitle, '남녀비 1:39의 …평범 141.5화', 126),
        '남녀비 139의 평행세계는 의외로 평범 141.5화',
    );
    assert.equal(buildEpisodeDisplayTitle(workTitle, workTitle, 7), workTitle);
});

test('collection naming adds a decimal base only beside a same-context decimal sibling', () => {
    const workTitle = '작품 제목';
    const records = [
        buildEpisodeManifestRecord({ number: 1, sourceTitle: '작품 제목 141화' }, workTitle),
        buildEpisodeManifestRecord({ number: 2, sourceTitle: '작품 제목 141.5화' }, workTitle),
        buildEpisodeManifestRecord({ number: 3, sourceTitle: '작품 제목 142화' }, workTitle),
    ];
    assert.equal(records[0].folderName, '작품 제목 141화');

    const result = resolveEpisodeCollectionNames(records, workTitle);
    assert.deepEqual(result.conflicts, []);
    assert.equal(result.records[0].displayTitle, '작품 제목 141.0화');
    assert.equal(result.records[0].folderName, '작품 제목 141.0화');
    assert.equal(result.records[1].folderName, '작품 제목 141.5화');
    assert.equal(result.records[2].folderName, '작품 제목 142화');
});

test('collection naming isolates special contexts and ignores range labels', () => {
    const workTitle = '작품 제목';
    const records = [
        buildEpisodeManifestRecord({ number: 1, sourceTitle: '작품 제목 1화' }, workTitle),
        buildEpisodeManifestRecord({ number: 2, sourceTitle: '작품 제목 R-18 미쿠 1.5화' }, workTitle),
        buildEpisodeManifestRecord({ number: 3, sourceTitle: '작품 제목 1~5화' }, workTitle),
        buildEpisodeManifestRecord({ number: 4, sourceTitle: '작품 제목 2화 본편' }, workTitle),
        buildEpisodeManifestRecord({ number: 5, sourceTitle: '작품 제목 2.5화 부록' }, workTitle),
    ];
    const result = resolveEpisodeCollectionNames(records, workTitle);
    assert.deepEqual(result.conflicts, []);
    assert.deepEqual(
        result.records.map(record => record.folderName),
        [
            '작품 제목 1화',
            '작품 제목 R-18 미쿠 1.5화',
            '작품 제목 1~5화',
            '작품 제목 2화 본편',
            '작품 제목 2.5화 부록',
        ],
    );
});

test('collection naming infers hyphen part one only from an exact part-two sibling', () => {
    const workTitle = '작품 제목';
    const make = (number, suffix) => buildEpisodeManifestRecord(
        { number, sourceTitle: `${workTitle} ${suffix}` },
        workTitle,
    );
    const result = resolveEpisodeCollectionNames([
        make(1, '12화'),
        make(2, '12 - 2화'),
        make(3, '13화'),
        make(4, '13-5화'),
    ], workTitle);
    assert.deepEqual(result.conflicts, []);
    assert.equal(result.records[0].folderName, '작품 제목 12 - 1화');
    assert.equal(result.records[1].folderName, '작품 제목 12 - 2화');
    assert.equal(result.records[2].folderName, '작품 제목 13화');
    assert.equal(result.records[3].folderName, '작품 제목 13-5화');
});

test('ambiguous sibling conventions are surfaced without guessing a base name', () => {
    const workTitle = '작품 제목';
    const make = (number, suffix) => buildEpisodeManifestRecord(
        { number, sourceTitle: `${workTitle} ${suffix}` },
        workTitle,
    );
    const mixed = resolveEpisodeCollectionNames([
        make(1, '141화'),
        make(2, '141.5화'),
        make(3, '141-2화'),
    ], workTitle);
    assert.equal(mixed.records[0].folderName, '작품 제목 141화');
    assert.equal(mixed.conflicts[0].reason, 'mixed_decimal_hyphen_siblings');

    const occupied = resolveEpisodeCollectionNames([
        make(1, '142화'),
        make(2, '142-1화'),
        make(3, '142-2화'),
    ], workTitle);
    assert.equal(occupied.records[0].folderName, '작품 제목 142화');
    assert.equal(occupied.conflicts[0].reason, 'hyphen_part_one_already_exists');
});

test('duplicate base labels without rewrite siblings remain collision-resolvable', () => {
    const workTitle = '작품 제목';
    const records = [1, 2].map(number => buildEpisodeManifestRecord(
        {
            number,
            sourceTitle: `${workTitle} 특별편 7화`,
            sourceUrl: `https://example.test/episode-${number}`,
        },
        workTitle,
    ));
    const result = resolveEpisodeCollectionNames(records, workTitle);
    assert.deepEqual(result.conflicts, []);
    assert.deepEqual(
        result.records.map(record => record.folderName),
        ['작품 제목 특별편 7화', '작품 제목 특별편 7화'],
    );
    const used = new Set();
    assert.equal(uniqueEpisodeFolderName(result.records[0].folderName, 1, used), '작품 제목 특별편 7화');
    assert.equal(uniqueEpisodeFolderName(result.records[1].folderName, 2, used), '작품 제목 특별편 7화 [0002]');
});

test('episode suffix extraction matches the shared Python migration cases', () => {
    for (const item of episodeSuffixCases) {
        if (item.downloaderErrorCode) {
            assert.throws(
                () => extractEpisodeSuffix(item.workTitle, item.sourceTitle, item.number),
                error => error?.errorCode === item.downloaderErrorCode,
                item.name,
            );
        }
        else {
            assert.equal(
                extractEpisodeSuffix(item.workTitle, item.sourceTitle, item.number),
                item.expectedSuffix,
                item.name,
            );
        }
    }
});

test('episode destination validation uses Windows UTF-16 safety limits', () => {
    assert.equal(windowsUtf16Units('😀'), 2);
    assert.deepEqual(
        validateEpisodeDestinationPath('가'.repeat(240), 'C:\\' + 'a'.repeat(245)),
        {
            encoding: 'utf-16',
            componentMaxUnits: 240,
            destinationMaxUnits: 248,
            componentUtf16Units: 240,
            destinationUtf16Units: 248,
            componentTooLong: false,
            absolutePathTooLong: false,
            pathTooLong: false,
        },
    );
    assert.throws(
        () => validateEpisodeDestinationPath('😀'.repeat(121), 'C:\\safe'),
        /회차 폴더명이 Windows 안전 길이를 초과합니다: 242 UTF-16 units/,
    );
    let pathError;
    try {
        validateEpisodeDestinationPath('safe', 'C:\\' + 'a'.repeat(246));
    }
    catch (error) {
        pathError = error;
    }
    assert.match(
        pathError?.message || '',
        /전체 목적지 경로가 Windows 안전 길이를 초과합니다: 249 UTF-16 units/,
    );
    assert.match(pathError?.message || '', /-output/);
    const diagnosis = classifyDownloaderError(pathError);
    assert.equal(diagnosis.errorCode, 'path_too_long');
    assert.equal(diagnosis.category, 'filesystem');
    assert.equal(diagnosis.retryable, false);
    assert.equal(diagnosis.diagnostics.destinationUtf16Units, 249);
    assert.equal(diagnosis.diagnostics.pathTooLong, true);
    assert.match(diagnosis.suggestion, /-output/);
});

test('known R-18 truncation artifacts are restored without an ellipsis', () => {
    const workTitle = '남녀비 1:39의 평행세계는 의외로 평범';
    const cases = [
        ['남녀비 1:39의 …-18 미쿠 1화', 'R-18 미쿠 1화'],
        ['남녀비 1:39의 …8 카나리아 2화', 'R-18 카나리아 2화'],
        ['남녀비 1:39의 …18 히나타 1화', 'R-18 히나타 1화'],
        ['남녀비 1:39의 … R-18 10화', 'R-18 10화'],
        ['남녀비 1:39의 …평범 히나타 3화', '히나타 3화'],
    ];
    for (const [sourceTitle, suffix] of cases) {
        const display = buildEpisodeDisplayTitle(workTitle, sourceTitle, 1);
        assert.equal(display, `${workTitle} ${suffix}`);
        assert.equal(display.includes('…'), false);
    }
    assert.equal(
        buildEpisodeDisplayTitle('다른 작품 제목', '다른 작품 …8 용사 1화', 1),
        '다른 작품 제목 8 용사 1화',
    );
});

test('episode manifest records use host-independent source ids and exact mapped folders', () => {
    const record = buildEpisodeManifestRecord(
        {
            number: 272,
            sourceUrl: 'https://newtoki1.org/manhwa/34360/u-msgh19fy-ecyu?from=list',
            sourceTitle: '남녀비 1:39의 …로 평범 287화',
            folderName: '이미 이관된 회차 폴더',
        },
        '남녀비 1:39의 평행세계는 의외로 평범',
    );
    assert.deepEqual(record, {
        number: 272,
        sourceId: '/manhwa/34360/u-msgh19fy-ecyu',
        sourceUrl: 'https://newtoki1.org/manhwa/34360/u-msgh19fy-ecyu?from=list',
        sourceTitle: '남녀비 1:39의 …로 평범 287화',
        displayTitle: '남녀비 1:39의 평행세계는 의외로 평범 287화',
        folderName: '이미 이관된 회차 폴더',
    });
    assert.equal(
        episodeSourceId('https://manatoki999.net/comic/12/episode-3#images'),
        '/comic/12/episode-3',
    );
});

test('episode folder collisions get a deterministic ordinal discriminator', () => {
    const used = new Set();
    assert.equal(uniqueEpisodeFolderName('같은 작품 1화', 1, used), '같은 작품 1화');
    assert.equal(uniqueEpisodeFolderName('같은 작품 1화', 2, used), '같은 작품 1화 [0002]');
    assert.equal(uniqueEpisodeFolderName('같은 작품 1화', 2, used), '같은 작품 1화 [0002-2]');
});

test('disk directory names are reserved unless the exact mapped folder is claimed', () => {
    const unrelated = new Set(['작품 제목 1화']);
    assert.equal(
        uniqueEpisodeFolderName('작품 제목 1화', 1, unrelated),
        '작품 제목 1화 [0001]',
    );
    const exact = new Set(['작품 제목 1화']);
    assert.equal(
        uniqueEpisodeFolderName('작품 제목 1화', 1, exact, { allowExisting: true }),
        '작품 제목 1화',
    );
});

test('stale manifest records survive when an episode disappears from the site list', () => {
    const previous = [
        {
            number: 1,
            sourceId: '/manhwa/1/old-one',
            sourceUrl: 'https://example.test/manhwa/1/old-one',
            sourceTitle: '작품 1화',
            displayTitle: '전체 작품 1화',
            folderName: '전체 작품 1화',
        },
        {
            number: 2,
            sourceId: '/manhwa/1/two',
            sourceUrl: 'https://example.test/manhwa/1/two',
            sourceTitle: '작품 2화',
            displayTitle: '전체 작품 2화',
            folderName: '전체 작품 2화',
        },
    ];
    const current = [{ ...previous[1], sourceTitle: '새 목록 제목 2화' }];
    const merged = mergeEpisodeManifestRecords(current, previous);
    assert.equal(merged.length, 2);
    assert.equal(merged[0].sourceId, '/manhwa/1/old-one');
    assert.equal(merged[0].folderName, '전체 작품 1화');
    assert.equal(merged[1].sourceTitle, '새 목록 제목 2화');
});

test('partial state records recover folder hints and stable URL fields from metadata', () => {
    const stateEpisodes = [{
        sourceId: '/manhwa/1/episode-1',
        sourceTitle: '축약 작품 1화',
        displayTitle: '전체 작품 1화',
    }];
    const metadataEpisodes = [{
        number: 1,
        sourceId: '/manhwa/1/episode-1',
        sourceUrl: 'https://example.test/manhwa/1/episode-1',
        sourceTitle: '축약 작품 1화',
        displayTitle: '전체 작품 1화',
        folderName: '전체 작품 1화',
    }];

    const recovered = mergeEpisodeManifestRecords(stateEpisodes, metadataEpisodes);
    assert.equal(recovered.length, 1);
    assert.equal(recovered[0].number, 1);
    assert.equal(recovered[0].sourceId, '/manhwa/1/episode-1');
    assert.equal(
        recovered[0].sourceUrl,
        'https://example.test/manhwa/1/episode-1',
    );
    assert.deepEqual(episodeRecordFolderCandidates(recovered[0]), [
        '전체 작품 1화',
        '축약 작품 1화',
    ]);
    const directories = new Set(['전체 작품 1화']);
    assert.equal(
        episodeRecordFolderCandidates(recovered[0]).find(name => directories.has(name)),
        '전체 작품 1화',
    );
    const persisted = mergeEpisodeManifestRecords(
        [{ ...metadataEpisodes[0], folderName: '전체 작품 1화' }],
        recovered,
    );
    assert.equal(persisted.length, 1);
    assert.equal(persisted[0].folderName, '전체 작품 1화');
    assert.equal(persisted[0].sourceId, '/manhwa/1/episode-1');

    const metadataOnlyRecovery = mergeEpisodeManifestRecords([], metadataEpisodes);
    assert.equal(metadataOnlyRecovery.length, 1);
    assert.equal(metadataOnlyRecovery[0].folderName, '전체 작품 1화');
});

test('explicit metadata ordinal replaces an inferred partial-state array position', () => {
    const recovered = mergeEpisodeManifestRecords(
        [{ sourceId: '/manhwa/1/episode-7', displayTitle: '전체 작품 7화' }],
        [{
            number: 7,
            sourceId: '/manhwa/1/episode-7',
            sourceUrl: 'https://example.test/manhwa/1/episode-7',
            sourceTitle: '작품 7화',
            displayTitle: '전체 작품 7화',
            folderName: '전체 작품 7화',
        }],
    );
    assert.equal(recovered.length, 1);
    assert.equal(recovered[0].number, 7);
    assert.equal(recovered[0].numberInferred, undefined);
});

test('a unique idless inferred title is claimed across ordinal changes and promoted', () => {
    const previous = [{
        number: 1,
        numberInferred: true,
        sourceId: '',
        sourceTitle: '',
        displayTitle: '전체 작품 특별편',
        folderName: '전체 작품 특별편',
    }];
    const current = [{
        number: 87,
        sourceId: '/manhwa/1/special',
        sourceUrl: 'https://example.test/manhwa/1/special',
        sourceTitle: '전체 작품 특별편',
        displayTitle: '전체 작품 특별편',
        folderName: '새로 계산된 폴더',
    }];

    const merged = mergeEpisodeManifestRecords(current, previous);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].number, 87);
    assert.equal(merged[0].numberInferred, undefined);
    assert.equal(merged[0].sourceId, '/manhwa/1/special');
    assert.equal(merged[0].folderName, '전체 작품 특별편');
});

test('duplicate inferred titles are never claimed by ordinal or a unique folder hint', () => {
    const previous = [1, 2].map(number => ({
        number,
        numberInferred: true,
        sourceId: '',
        sourceTitle: '중복 작품 특별편',
        displayTitle: '중복 작품 특별편',
        folderName: `중복 작품 특별편 ${number}`,
    }));
    const current = {
        number: 1,
        sourceId: '/manhwa/1/current',
        sourceTitle: '중복 작품 특별편',
        displayTitle: '중복 작품 특별편',
        folderName: '중복 작품 특별편 1',
    };
    const index = buildInferredEpisodeTitleIndex(previous);
    assert.equal(findUniqueInferredEpisodeMatch(index, current), null);
    const merged = mergeEpisodeManifestRecords([current], previous);
    assert.equal(merged.length, 3);
    assert.equal(merged.find(item => item.sourceId)?.folderName, current.folderName);
});

test('inferred title indexing remains linear-sized for thousands of records', () => {
    const records = Array.from({ length: 3000 }, (_value, index) => ({
        number: index + 1,
        numberInferred: true,
        sourceId: '',
        sourceTitle: `작품 ${index + 1}화`,
        folderName: `전체 작품 ${index + 1}화`,
    }));
    const index = buildInferredEpisodeTitleIndex(records);
    assert.ok(index.size <= records.length * 2);
    assert.equal(mergeEpisodeManifestRecords([], records).length, records.length);
    assert.equal(
        findUniqueInferredEpisodeMatch(index, {
            sourceTitle: '작품 2999화',
            displayTitle: '전체 작품 2999화',
        }),
        records[2998],
    );
});

test('ordinal shifts preserve the old stable record and forbid legacy folder reuse', () => {
    const previous = [{
        number: 1,
        sourceId: '/manhwa/1/old',
        sourceUrl: 'https://example.test/manhwa/1/old',
        sourceTitle: '이전 1화',
        displayTitle: '작품 이전 1화',
        folderName: '0001 이전 1화',
    }];
    const current = [{
        number: 1,
        sourceId: '/manhwa/1/new',
        sourceUrl: 'https://example.test/manhwa/1/new',
        sourceTitle: '새 1화',
        displayTitle: '작품 새 1화',
        folderName: '작품 새 1화',
    }];
    assert.equal(canReuseLegacyEpisodeFolder(previous, 1, '/manhwa/1/new'), false);
    assert.equal(canReuseLegacyEpisodeFolder(previous, 1, '/manhwa/1/old'), true);
    assert.equal(mergeEpisodeManifestRecords(current, previous).length, 2);
});

test('idless ordinal fallback requires the original source title to match', () => {
    const previous = [{
        number: 1,
        sourceId: '',
        sourceUrl: '',
        sourceTitle: '이전 작품 10화',
        displayTitle: '전체 이전 작품 10화',
        folderName: '0001 이전 작품 10화',
    }];
    assert.equal(
        episodeSourceTitlesMatch('이전 작품 10화', '0001 이전 작품 10화', 1),
        true,
    );
    assert.equal(
        canReuseLegacyEpisodeFolder(
            previous,
            1,
            '/manhwa/1/new-id',
            '이전 작품 10화',
            '0001 이전 작품 10화',
        ),
        true,
    );
    assert.equal(
        canReuseLegacyEpisodeFolder(
            previous,
            1,
            '/manhwa/1/new-id',
            '새 작품 1화',
            '0001 이전 작품 10화',
        ),
        false,
    );

    const shifted = [{
        number: 1,
        sourceId: '/manhwa/1/new-id',
        sourceUrl: 'https://example.test/manhwa/1/new-id',
        sourceTitle: '새 작품 1화',
        displayTitle: '전체 새 작품 1화',
        folderName: '전체 새 작품 1화',
    }];
    const merged = mergeEpisodeManifestRecords(shifted, previous);
    assert.equal(merged.length, 2);
    assert.deepEqual(new Set(merged.map(item => item.folderName)), new Set([
        '0001 이전 작품 10화',
        '전체 새 작품 1화',
    ]));
});

test('v1 HTML titles match current text without interpreting unknown markup', () => {
    assert.equal(
        episodeSourceTitlesMatch(
            '작품 & 이름 특별편',
            '0001 <em>작품 &amp; 이름</em> &#xD2B9;&#48324;&#54200;',
            1,
        ),
        true,
    );
    assert.equal(
        episodeSourceTitlesMatch(
            '작품 A 특별편',
            '0001 <custom>작품 A</custom> 특별편',
            1,
        ),
        false,
    );
    assert.equal(
        episodeSourceTitlesMatch(
            '작품 &notARealEntity; 1화',
            '0001 작품 &notARealEntity; 1화',
            1,
        ),
        true,
    );
});

test('empty DOM labels still stop instead of manufacturing the site ordinal', () => {
    for (const sourceTitle of ['', '   ']) {
        assert.throws(
            () => buildEpisodeManifestRecord(
                { number: 37, sourceTitle, sourceUrl: 'https://example.test/episode-37' },
                '작품 제목',
            ),
            error => (
                error?.errorCode === 'unsafe_episode_title'
                && error?.category === 'site_structure'
                && error?.retryable === false
                && error?.diagnostics?.siteOrdinal === 37
                && !String(error?.message || '').includes('37화')
            ),
        );
    }
});

test('unnumbered chapters stay in site order without blocking the complete manifest', () => {
    for (const [work, source] of [
        ['히토너', '히토너'],
        ['원펀맨 리메이크', '원펀맨 리메이크'],
        ['쿠로이와 메다카에게 내 귀여움이 통하지 않아', '쿠로이와 메다카에게…움이 통하지 않아'],
    ]) {
        const records = [work + ' 1화', source, work + ' 2화', source].map((sourceTitle, index) =>
            buildEpisodeManifestRecord({number: index + 1, sourceTitle,
                sourceUrl: `https://example.test/manhwa/1/${index + 1}`}, work));
        const result = resolveEpisodeCollectionNames(records, work);
        assert.deepEqual(result.conflicts, []);
        assert.equal(result.records.length, 4);
        assert.equal(result.records[1].displayTitle, work);
        assert.equal(result.records[3].sourceTitle, source);
        const folders = result.records.map(record => orderedEpisodeFolderName(record.number, record.displayTitle));
        assert.deepEqual([...folders].sort(), folders);
        assert.equal(new Set(folders).size, 4);
        assert.equal(folders[1], `000002 ${sanitizePathSegment(work)}`);
        assert.equal(folders[3], `000004 ${sanitizePathSegment(work)}`);
        assert.notEqual(result.records[1].sourceId, result.records[3].sourceId);
    }
});

test('numeric-looking modern folders are not mistaken for legacy episode folders', () => {
    assert.equal(
        isLegacyEpisodeFolderCandidate('0001 축약 제목', 1, ['0000.jpeg', '0001.jpeg']),
        false,
    );
    assert.equal(
        isLegacyEpisodeFolderCandidate('2024 작품 제목', 2024, ['0000.jpeg']),
        false,
    );
    assert.equal(
        isLegacyEpisodeFolderCandidate('0001 축약 제목', 1, ['0001 축약 제목 image0000.jpeg']),
        true,
    );
    assert.equal(
        isLegacyEpisodeFolderCandidate('0001 빈 매핑 폴더', 1, [], true),
        true,
    );
});

test('episode manifest and collision helpers reject zero or negative ordinals', () => {
    assert.throws(
        () => buildEpisodeManifestRecord({ number: 0, sourceTitle: '0화' }, '작품'),
        /1 이상의 정수/,
    );
    assert.throws(() => uniqueEpisodeFolderName('작품 0화', 0), /1 이상의 정수/);
});
