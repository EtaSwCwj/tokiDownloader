import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { saveImage, runDownloadTasks } from '../down.js';
import { imageFailureDeferral, PendingEpisodes } from '../downloader_episodes.js';
import { selectEpisodeLinks } from '../downloader_policy.js';

const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 0xff, 0xd9]);
const bmp = Buffer.from('BM damaged source behind a jpg URL');
const noWait = async () => {};
async function fixture(callback) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'toki-image-deferral-'));
    try { await callback(directory); }
    finally { fs.rmSync(directory, { recursive: true, force: true }); }
}

test('known invalid images exhaust retries, preserve old files and retain every failed URL', async () => {
    await fixture(async directory => {
        fs.writeFileSync(path.join(directory, '0000.jpg'), jpeg);
        const calls = new Map();
        const download = async url => {
            calls.set(url, (calls.get(url) || 0) + 1);
            return url.endsWith('2.jpg') ? jpeg : bmp;
        };
        let failure;
        await assert.rejects(runDownloadTasks([0, 1, 2].map(i => () => saveImage(
            directory, `${String(i).padStart(4, '0')}.jpg`, `https://cdn.example/${i}.jpg`,
            { download, wait: noWait },
        )), 2), error => { failure = error; return true; });
        const result = imageFailureDeferral(failure);
        assert.equal(result.reason, 'source_image_validation_failed');
        assert.deepEqual(result.failedImages.map(item => item.sourceUrl), [
            'https://cdn.example/0.jpg', 'https://cdn.example/1.jpg',
        ]);
        for (const image of result.failedImages) {
            assert.equal(image.reason, 'extension_signature_mismatch');
            assert.equal(image.detectedFormat, 'bmp');
            assert.equal(image.expectedFormat, 'jpeg');
            assert.equal(image.attempts, 3);
            assert.equal(calls.get(image.sourceUrl), 3);
        }
        assert.deepEqual(fs.readFileSync(path.join(directory, '0000.jpg')), jpeg);
        assert.deepEqual(fs.readdirSync(directory).sort(), ['0000.jpg', '0002.jpg']);
    });
});

test('a valid retry succeeds normally without recording a missing image', async () => {
    await fixture(async directory => {
        let calls = 0;
        await runDownloadTasks([() => saveImage(directory, '0000.jpg', 'https://cdn.example/0.jpg', {
            download: async () => ++calls < 3 ? bmp : jpeg, wait: noWait,
        })]);
        assert.equal(calls, 3);
        assert.deepEqual(fs.readFileSync(path.join(directory, '0000.jpg')), jpeg);
    });
});

test('HTML, empty responses, network errors and mixed retry failures are never damage deferrals', async () => {
    await fixture(async directory => {
        for (const result of [Buffer.from('<html>login required</html>'), Buffer.alloc(0),
            new Error('HTTP 403'), new Error('HTTP 429'), new Error('ECONNRESET')]) {
            let failure;
            await assert.rejects(runDownloadTasks([() => saveImage(directory, '0000.jpg', 'https://cdn.example/0.jpg', {
                download: async () => { if (result instanceof Error) throw result; return result; },
                wait: noWait,
            })]), error => { failure = error; return true; });
            assert.equal(imageFailureDeferral(failure), null);
        }
        let calls = 0, failure;
        await assert.rejects(runDownloadTasks([() => saveImage(directory, '0000.jpg', 'https://cdn.example/0.jpg', {
            download: async () => { if (++calls === 1) throw new Error('HTTP 403'); return bmp; }, wait: noWait,
        })]), error => { failure = error; return true; });
        assert.equal(imageFailureDeferral(failure), null);
        assert.deepEqual(fs.readdirSync(directory), []);
    });
});

test('disk and authentication failures alongside damaged images still stop the work', async () => {
    await fixture(async directory => {
        for (const fatal of [Object.assign(new Error('disk full'), {code:'ENOSPC'}),
            Object.assign(new Error('file locked'), {code:'EPERM'}), new Error('HTTP 403')]) {
            let failure;
            await assert.rejects(runDownloadTasks([
                () => saveImage(directory, '0000.jpg', 'https://cdn.example/0.jpg', {
                    download: async () => bmp, wait: noWait,
                }),
                async () => { throw fatal; },
            ]), error => { failure = error; return true; });
            assert.equal(imageFailureDeferral(failure), null);
            assert.equal(failure.cause, fatal);
            assert.match(failure.message, new RegExp(fatal.message));
        }
    });
});

test('actual local write failures never enter the source damage path', async () => {
    await fixture(async directory => {
        const blockedDirectory = path.join(directory, 'not-a-directory');
        fs.writeFileSync(blockedDirectory, 'keep');
        let failure;
        await assert.rejects(runDownloadTasks([() => saveImage(blockedDirectory, '0000.jpg', 'https://cdn.example/0.jpg', {
            download: async () => jpeg, wait: noWait,
        })]), error => { failure = error; return true; });
        assert.equal(imageFailureDeferral(failure), null);
        assert.equal(fs.readFileSync(blockedDirectory, 'utf8'), 'keep');
    });
});

test('damaged chapter is durable and retryable while the next chapter completes', async () => {
    await fixture(async directory => {
        const ledger = new PendingEpisodes();
        const completedIds = new Set();
        const chapters = [32, 33].map(number => ({number, sourceId:`/manhwa/3184/${number}`,
            sourceUrl:`https://newtoki1.org/manhwa/3184/${number}`, displayTitle:`러브 다이어리 ${number}`}));
        for (const chapter of chapters) {
            try {
                await runDownloadTasks([() => saveImage(directory, `${chapter.number}.jpg`, `https://cdn.example/${chapter.number}.jpg`, {
                    download: async () => chapter.number === 32 ? bmp : jpeg, wait: noWait,
                })]);
                completedIds.add(chapter.sourceId);
            } catch (error) {
                const deferral = imageFailureDeferral(error);
                assert.ok(deferral);
                ledger.defer(chapter, deferral.message, deferral);
            }
        }
        const restored = new PendingEpisodes(JSON.parse(JSON.stringify(ledger.records)));
        const summary = restored.completionSummary(completedIds.size, chapters.length);
        assert.equal(summary.completedThisRun, 1);
        assert.equal(summary.pendingEpisodeCount, 1);
        assert.equal(summary.pendingEpisodes[0].failedImages.length, 1);
        assert.match(summary.completionNote, /수정된 후/);
        assert.deepEqual(fs.readdirSync(directory), ['33.jpg']);
        const selection = selectEpisodeLinks(chapters.map(c => ({num:String(c.number), sourceId:c.sourceId})), {
            scanMode:'new', preferEpisodeIds:true, completedEpisodeIds:completedIds,
        });
        assert.deepEqual(selection.links.map(item => item.sourceId), [chapters[0].sourceId]);
        // Once the source is repaired, the missing ID can be removed normally.
        await saveImage(directory, '32.jpg', 'https://cdn.example/32.jpg', {download:async () => jpeg, wait:noWait});
        restored.resolve(chapters[0].sourceId);
        assert.equal(restored.completionSummary(1, 1).pendingEpisodeCount, 0);
    });
});
