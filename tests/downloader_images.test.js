import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

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


function withTempDirectory(callback) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'toki-image-test-'));
    try {
        callback(directory);
    }
    finally {
        fs.rmSync(directory, { recursive: true, force: true });
    }
}


test('existing images skip only for supported non-empty matching signatures', () => {
    withTempDirectory(directory => {
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

        writeImageBufferAtomically(directory, '0002.jpg', jpegB);
        assert.deepEqual(fs.readFileSync(htmlPath), jpegB);
        assert.equal(existingImageFileIsValid(htmlPath), true);
    });
});


test('atomic image replacement validates first and preserves the old file on failure', () => {
    withTempDirectory(directory => {
        const destination = path.join(directory, '0000.jpg');
        fs.writeFileSync(destination, jpegA);

        assert.throws(
            () => writeImageBufferAtomically(
                directory,
                '0000.jpg',
                Buffer.from('<html>blocked</html>'),
            ),
            error => error?.code === 'invalid_image_payload',
        );
        assert.deepEqual(fs.readFileSync(destination), jpegA);

        assert.throws(
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

        writeImageBufferAtomically(directory, '0000.jpg', jpegB);
        assert.deepEqual(fs.readFileSync(destination), jpegB);
        assert.equal(existingImageFileIsValid(destination), true);
    });
});
