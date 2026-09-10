import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { inspectEpisodeViewer, EPISODE_IMAGE_SELECTOR, EPISODE_PROCESSING_MESSAGE,
    waitForEpisodeAvailability, PendingEpisodes } from '../downloader_episodes.js';
import { classifyDownloaderError } from '../downloader_errors.js';
import { selectEpisodeLinks } from '../downloader_policy.js';

function inspect({ image = false, notice = null } = {}) {
    return vm.runInNewContext(`(${inspectEpisodeViewer.toString()})(selector, message)`, {
        selector: EPISODE_IMAGE_SELECTOR, message: EPISODE_PROCESSING_MESSAGE,
        document: { querySelector: selector => selector === EPISODE_IMAGE_SELECTOR
            ? image ? {} : null : notice === null ? null : {textContent: notice} },
    });
}

test('only an explicit processing notice inside the reader defers a chapter', () => {
    assert.equal(inspect({notice: EPISODE_PROCESSING_MESSAGE}).status, 'processing');
    assert.equal(inspect({notice: ` \n${EPISODE_PROCESSING_MESSAGE} \n`}).status, 'processing');
    for (const notice of [null, '', '이미지 불러오는 중...', '로그인이 필요합니다', 'Just a moment', '삭제된 회차입니다'])
        assert.equal(inspect({notice}), false);
    assert.equal(inspect({image:true, notice:EPISODE_PROCESSING_MESSAGE}).status, 'ready');
});

test('browser wait uses the same predicate and releases its result handle', async () => {
    let disposed = false;
    const page = {waitForFunction: async (predicate, options, selector, message) => {
        assert.equal(predicate, inspectEpisodeViewer);
        assert.equal(options.timeout, 60000);
        assert.equal(selector, EPISODE_IMAGE_SELECTOR);
        assert.equal(message, EPISODE_PROCESSING_MESSAGE);
        return {jsonValue: async () => ({status:'processing',message}), dispose:async () => {disposed=true;}};
    }};
    assert.equal((await waitForEpisodeAvailability(page)).status, 'processing');
    assert.equal(disposed, true);
});

test('unknown empty or authenticated error pages do not silently become deferred', async () => {
    const failure = new Error('selector timeout');
    await assert.rejects(waitForEpisodeAvailability({waitForFunction: async () => {throw failure;}}), error => error === failure);
});

const chapter = number => ({number,sourceId:`/manhwa/40/${number}`,
    sourceUrl:`https://newtoki1.org/manhwa/40/${number}`,sourceTitle:`은혼 ${number}화`,
    displayTitle:`은혼 ${number}화`,folderName:`${String(number).padStart(6,'0')} 은혼 ${number}화`});

test('pending source IDs persist independently of successful later chapters and retry as new', () => {
    const first = chapter(563), next = chapter(564);
    const ledger = new PendingEpisodes();
    ledger.defer(first, EPISODE_PROCESSING_MESSAGE);
    ledger.defer(first, EPISODE_PROCESSING_MESSAGE);
    ledger.resolve(next.sourceId);
    const state = JSON.parse(JSON.stringify({pendingEpisodes:ledger.records, completedEpisodeIds:[next.sourceId]}));
    const restored = new PendingEpisodes(state.pendingEpisodes);
    assert.equal(restored.records.length, 1);
    assert.equal(restored.records[0].sourceId, first.sourceId);
    const selected = selectEpisodeLinks([first,next].map(c=>({num:String(c.number),sourceId:c.sourceId})), {
        scanMode:'new',preferEpisodeIds:true,completedEpisodeIds:new Set(state.completedEpisodeIds)});
    assert.deepEqual(selected.links.map(row=>row.sourceId), [first.sourceId]);
    assert.throws(()=>restored.throwIfPending(1,2), error=> {
        const result=classifyDownloaderError(error);
        assert.equal(result.category,'source');
        assert.equal(result.retryable,false);
        assert.equal(result.errorCode,'episodes_pending');
        assert.equal(result.diagnostics.completedThisRun,1);
        return true;
    });
    restored.resolve(first.sourceId);
    assert.doesNotThrow(()=>restored.throwIfPending(1,1));
});

test('a range scan cannot discard unresolved pending records outside that range', () => {
    const ledger = new PendingEpisodes([chapter(563)]);
    ledger.resolve(chapter(700).sourceId);
    assert.throws(()=>ledger.throwIfPending(1,1), error=>error.errorCode==='episodes_pending');
    assert.deepEqual(new PendingEpisodes(null).records, []);
});
