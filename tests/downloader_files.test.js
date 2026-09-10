import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { renameWithRetry, writeJsonAtomically } from '../downloader_files.js';

async function fixture(callback) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'toki-checkpoint-test-'));
    try { await callback(directory); }
    finally { fs.rmSync(directory, { recursive: true, force: true }); }
}

test('transient Windows rename denial retries without removing the old checkpoint', async () => {
    await fixture(async directory => {
        const target = path.join(directory, '.toki-state.json');
        fs.writeFileSync(target, JSON.stringify({completedEpisodes: [1]}));
        const waits = [], retries = [];
        let calls = 0;
        const result = await writeJsonAtomically(target, {completedEpisodes: [1, 2]}, {
            wait: async ms => { waits.push(ms); }, onRetry: detail => retries.push(detail),
            rename: async (source, destination) => {
                calls++;
                assert.deepEqual(JSON.parse(fs.readFileSync(destination)), {completedEpisodes: [1]});
                assert.deepEqual(JSON.parse(fs.readFileSync(source)), {completedEpisodes: [1, 2]});
                if (calls < 3) throw Object.assign(new Error('OneDrive test lock'), {code: 'EPERM'});
                await fs.promises.rename(source, destination);
            },
        });
        assert.equal(result.attempts, 3);
        assert.deepEqual(waits, [100, 200]);
        assert.equal(retries.length, 2);
        assert.deepEqual(JSON.parse(fs.readFileSync(target)), {completedEpisodes: [1, 2]});
        assert.deepEqual(fs.readdirSync(directory), ['.toki-state.json']);
    });
});

test('persistent locks preserve both old and recoverable new checkpoint with bounded waits', async () => {
    await fixture(async directory => {
        const target = path.join(directory, '.toki-state.json');
        fs.writeFileSync(target, '{"old":true}');
        const waits = [];
        let failure;
        await assert.rejects(() => writeJsonAtomically(target, {new: true}, {
            wait: async ms => waits.push(ms),
            rename: async () => { throw Object.assign(new Error('locked'), {code: 'EBUSY'}); },
        }), error => { failure = error; return error.code === 'EBUSY'; });
        assert.equal(waits.length, 8);
        assert.equal(waits.reduce((a, b) => a + b, 0), 5500);
        assert.deepEqual(JSON.parse(fs.readFileSync(target)), {old: true});
        assert.deepEqual(JSON.parse(fs.readFileSync(failure.diagnostics.temporary)), {new: true});
    });
});

test('disk full and other permanent errors do not get rename retries', async () => {
    let waited = false, calls = 0;
    await assert.rejects(() => renameWithRetry('source', 'target', {
        rename: async () => { calls++; throw Object.assign(new Error('full'), {code: 'ENOSPC'}); },
        wait: async () => { waited = true; },
    }), error => error.code === 'ENOSPC');
    assert.equal(calls, 1);
    assert.equal(waited, false);
});

test('new checkpoint temps never overwrite an older pending .tmp', async () => {
    await fixture(async directory => {
        const target = path.join(directory, '.toki-state.json');
        fs.writeFileSync(target + '.tmp', 'previous recovery data');
        await writeJsonAtomically(target, {completedEpisodes: [1]});
        assert.equal(fs.readFileSync(target + '.tmp', 'utf8'), 'previous recovery data');
    });
});
