import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import jpeg from 'jpeg-js';
import webpSamples from './fixtures/webp_validation_samples.json' with { type: 'json' };
import { validateImageBuffer } from '../downloader_policy.js';

import {
    existingImageFileIsValid,
    existingImageFileValidation,
    writeImageBufferAtomically,
} from '../down.js';

const jpegA = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x01, 0xff, 0xd9]);
const jpegB = Buffer.from([0xff, 0xd8, 0xff, 0xe1, 0x02, 0xff, 0xd9]);
const truncatedJpeg = Buffer.concat([
    Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x01]),
    Buffer.alloc(300),
]);
const truncatedPng = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    Buffer.alloc(300),
]);

test('WebP downloads and existing files reject truncated containers and chunks', async () => {
    await withTempDirectory(async directory => {
        for (const [name, encoded] of Object.entries(webpSamples)) {
            const valid = Buffer.from(encoded, 'base64');
            const damagedChunk = Buffer.from(valid);
            damagedChunk.writeUInt32LE(valid.length, 16);
            const headerOnly = Buffer.from(valid.subarray(0, 20));
            headerOnly.writeUInt32LE(12, 4);
            const variants = [
                [name, valid, true],
                ['truncated', valid.subarray(0, 20), false],
                ['last-byte-missing', valid.subarray(0, valid.length - 1), false],
                ['damaged-chunk', damagedChunk, false],
                ['header-only', headerOnly, false],
            ];
            for (const [variant, payload, expected] of variants) {
                const filePath = path.join(directory, `${name}-${variant}.webp`);
                fs.writeFileSync(filePath, payload);
                assert.equal(validateImageBuffer(payload, '.webp').valid, expected, filePath);
                assert.equal(existingImageFileIsValid(filePath), expected, filePath);
            }
            const destination = `${name}-replace.webp`;
            fs.writeFileSync(path.join(directory, destination), valid);
            await assert.rejects(
                () => writeImageBufferAtomically(directory, destination, valid.subarray(0, 20)),
                error => error?.code === 'invalid_image_payload',
            );
            assert.deepEqual(fs.readFileSync(path.join(directory, destination)), valid);
        }
    });
});

test('existing WebP validation reads chunks beyond the header without buffering the payload', async () => {
    await withTempDirectory(async directory => {
        const base = Buffer.from(webpSamples.lossy, 'base64');
        const metadataChunk = Buffer.alloc(1032);
        metadataChunk.write('JUNK');
        metadataChunk.writeUInt32LE(1024, 4);
        const extended = Buffer.concat([base.subarray(0, 12), metadataChunk, base.subarray(12)]);
        extended.writeUInt32LE(extended.length - 8, 4);
        const target = path.join(directory, 'extended.webp');
        fs.writeFileSync(target, extended);
        assert.equal(existingImageFileIsValid(target), true);
        // A valid outer RIFF size does not hide a truncated final image chunk.
        extended.writeUInt32LE(extended.length, 12 + metadataChunk.length + 4);
        fs.writeFileSync(target, extended);
        assert.equal(existingImageFileValidation(target).reason, 'invalid_webp_chunks');
    });
});


async function withTempDirectory(callback) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'toki-image-test-'));
    try {
        await callback(directory);
    }
    finally {
        fs.rmSync(directory, { recursive: true, force: true });
    }
}


test('existing images skip only for supported non-empty matching signatures', async () => {
    await withTempDirectory(async directory => {
        const validPath = path.join(directory, '0000.jpg');
        const emptyPath = path.join(directory, '0001.jpg');
        const htmlPath = path.join(directory, '0002.jpg');
        const mismatchPath = path.join(directory, '0003.jpg');
        const truncatedJpegPath = path.join(directory, '0004.jpg');
        const truncatedPngPath = path.join(directory, '0005.png');
        const longValidJpegPath = path.join(directory, '0006.jpg');
        fs.writeFileSync(validPath, jpegA);
        fs.writeFileSync(emptyPath, Buffer.alloc(0));
        fs.writeFileSync(htmlPath, '<html>challenge</html>');
        fs.writeFileSync(
            mismatchPath,
            Buffer.from([
                0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
                0x49, 0x45, 0x4e, 0x44,
            ]),
        );
        fs.writeFileSync(truncatedJpegPath, truncatedJpeg);
        fs.writeFileSync(truncatedPngPath, truncatedPng);
        fs.writeFileSync(longValidJpegPath, Buffer.concat([
            Buffer.from([0xff, 0xd8, 0xff]),
            Buffer.alloc(300),
            Buffer.from([0xff, 0xd9]),
        ]));

        assert.equal(existingImageFileIsValid(validPath), true);
        assert.equal(existingImageFileIsValid(emptyPath), false);
        assert.equal(existingImageFileValidation(emptyPath).reason, 'empty_image');
        assert.equal(existingImageFileValidation(htmlPath).reason, 'invalid_signature');
        assert.equal(
            existingImageFileValidation(mismatchPath).reason,
            'extension_signature_mismatch',
        );
        assert.equal(existingImageFileIsValid(truncatedJpegPath), false);
        assert.equal(
            existingImageFileValidation(truncatedJpegPath).reason,
            'missing_end_marker',
        );
        assert.equal(existingImageFileIsValid(truncatedPngPath), false);
        assert.equal(
            existingImageFileValidation(truncatedPngPath).reason,
            'missing_end_marker',
        );
        assert.equal(existingImageFileIsValid(longValidJpegPath), true);

        await writeImageBufferAtomically(directory, '0002.jpg', jpegB);
        assert.deepEqual(fs.readFileSync(htmlPath), jpegB);
        assert.equal(existingImageFileIsValid(htmlPath), true);
    });
});


test('atomic image replacement validates first and preserves the old file on failure', async () => {
    await withTempDirectory(async directory => {
        const destination = path.join(directory, '0000.jpg');
        fs.writeFileSync(destination, jpegA);

        await assert.rejects(
            () => writeImageBufferAtomically(
                directory,
                '0000.jpg',
                Buffer.from('<html>blocked</html>'),
            ),
            error => error?.code === 'invalid_image_payload',
        );
        assert.deepEqual(fs.readFileSync(destination), jpegA);

        await assert.rejects(
            () => writeImageBufferAtomically(directory, '0000.jpg', jpegB, {
                renameFile: () => { throw new Error('simulated rename failure'); },
            }),
            /simulated rename failure/,
        );
        assert.deepEqual(fs.readFileSync(destination), jpegA);
        assert.deepEqual(
            fs.readdirSync(directory).filter(name => name.endsWith('.tmp')),
            [],
        );

        await writeImageBufferAtomically(directory, '0000.jpg', jpegB);
        assert.deepEqual(fs.readFileSync(destination), jpegB);
        assert.equal(existingImageFileIsValid(destination), true);
    });
});

test('JPEG trailing metadata requires full decode and survives save/skip intact', async () => {
    const data = Buffer.alloc(8 * 8 * 4, 128);
    const encoded = jpeg.encode({width: 8, height: 8, data}).data;
    const payload = Buffer.concat([encoded, Buffer.alloc(46, 65)]);
    assert.equal(validateImageBuffer(payload, '.jpg').valid, true);
    // A plausible signature/EOI with garbage is not a decodable image.
    assert.equal(validateImageBuffer(Buffer.concat([jpegA, Buffer.alloc(46)]), '.jpg').reason,
        'jpeg_decode_failed');
    assert.equal(validateImageBuffer(encoded.subarray(0, encoded.length - 2), '.jpg').reason,
        'missing_end_marker');
    const truncated = Buffer.concat([encoded.subarray(0, 100), Buffer.from([255, 217]), Buffer.alloc(46)]);
    assert.equal(validateImageBuffer(truncated, '.jpg').valid, false);
    await withTempDirectory(async directory => {
        await writeImageBufferAtomically(directory, '0000.jpg', payload);
        const file = path.join(directory, '0000.jpg');
        assert.deepEqual(fs.readFileSync(file), payload);
        assert.equal(existingImageFileIsValid(file), true);
        await assert.rejects(() => writeImageBufferAtomically(directory, '0000.jpg', truncated));
        assert.deepEqual(fs.readFileSync(file), payload);
    });
});
