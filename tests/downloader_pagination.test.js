import test from 'node:test';
import assert from 'node:assert/strict';
import { collectEpisodeListPages, episodeListPageUrl } from '../downloader_pagination.js';

const base = 'https://newtoki1.org/manhwa/34732';
const rows = (...numbers) => numbers.map(num => ({num: String(num), fileName: `${num}화`, src: `${base}/${num}`}));
function pageFor(snapshots, start = base) {
    let url = start;
    const visits = [];
    return { visits, url: () => url, waitForSelector: async () => {},
        evaluate: async () => ({ url, ...snapshots[url] }),
        goto: async next => { visits.push(next); url = next; } };
}

test('new episode pager collects all pages and ignores another work and comment-only links', async () => {
    const next = `${base}?epage=2`;
    const page = pageFor({
        [base]: {rows: rows(4, 3), expectedCount: 4, pageLinks: [next, next, `${base}?page=2`, `${base}/3?epage=2`, 'https://other.test/manhwa/34732?epage=2']},
        [next]: {rows: rows(2, 1), expectedCount: 4, pageLinks: [base, next]},
    });
    const result = await collectEpisodeListPages(page);
    assert.equal(result.count, 4);
    assert.equal(result.pageCount, 2);
    assert.deepEqual(page.visits, [next]);
});

test('legacy page pager, starting on page two, and duplicate rows are supported', async () => {
    const next = `${base}?page=2`;
    const page = pageFor({
        [base]: {rows: rows(4, 3), pageLinks: [next]},
        [next]: {rows: rows(3, 2, 1), pageLinks: [base]},
    }, next);
    assert.equal((await collectEpisodeListPages(page)).count, 4);
});

test('missed page, repeated content, redirect loop and page cap fail instead of partial success', async () => {
    const next = `${base}?epage=2`;
    await assert.rejects(collectEpisodeListPages(pageFor({[base]: {rows: rows(2), expectedCount: 2, pageLinks: []}})), /불완전/);
    const repeated = {[base]: {rows: rows(2), pageLinks: [next]}, [next]: {rows: rows(2), pageLinks: []}};
    await assert.rejects(collectEpisodeListPages(pageFor(repeated)), /같은 회차/);
    await assert.rejects(collectEpisodeListPages(pageFor(repeated), {maxPages: 1}), /안전 한도/);
    const page = pageFor(repeated); page.goto = async () => {};
    await assert.rejects(collectEpisodeListPages(page), /반복/);
});

test('only valid same-work page URLs are canonicalized', () => {
    assert.equal(episodeListPageUrl(`${base}?page=2&epage=3`, base, 'epage'), `${base}?epage=3`);
    assert.equal(episodeListPageUrl(`${base}?epage=1`, base), base);
    for (const raw of [`${base}?epage=-1`, `${base}?epage=NaN`, `${base}?epage=2#comment`, `${base}/1?epage=2`])
        assert.equal(episodeListPageUrl(raw, base), null);
});
