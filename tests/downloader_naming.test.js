import test from 'node:test';
import assert from 'node:assert/strict';

import {
    DEFAULT_FOLDER_TEMPLATE,
    renderFolderTemplate,
    sanitizePathSegment,
    validateFolderTemplate,
} from '../downloader_naming.js';

const sample = {
    author: '이요미네 츠쿠',
    group: 'N／A',
    title: '이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건',
    source: { siteTitle: '마나토끼', workId: '34360' },
};

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
