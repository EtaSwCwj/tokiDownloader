import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

const TRANSIENT_RENAME_ERRORS = new Set(['EPERM', 'EACCES', 'EBUSY']);

// Windows cloud-sync/AV filters can briefly deny replace even with correct ACLs.
// Never unlink the destination to "fix" this: the old checkpoint remains valid.
export async function renameWithRetry(source, destination, {
    rename = fs.promises.rename, wait = delay, onRetry = () => {}, attempts = 9,
} = {}) {
    const limit = Math.max(1, Math.min(12, Number(attempts) || 9));
    for (let attempt = 1; ; attempt++) {
        try {
            await rename(source, destination);
            return { attempts: attempt };
        } catch (error) {
            if (!TRANSIENT_RENAME_ERRORS.has(error.code) || attempt >= limit)
                throw error;
            const delayMs = Math.min(1000, 100 * (2 ** (attempt - 1)));
            onRetry({ code: error.code, attempt, delayMs });
            await wait(delayMs);
        }
    }
}

export async function writeJsonAtomically(destination, value, options = {}) {
    const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`;
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    let descriptor;
    try {
        descriptor = fs.openSync(temporary, 'wx');
        fs.writeFileSync(descriptor, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
        fs.fsyncSync(descriptor);
        fs.closeSync(descriptor);
        descriptor = undefined;
        return await renameWithRetry(temporary, destination, options);
    } catch (error) {
        // Keep the durable new checkpoint as well as the old destination on
        // persistent failure; the error tells the user where recovery data is.
        error.diagnostics = { ...error.diagnostics, destination, temporary };
        throw error;
    } finally {
        if (descriptor !== undefined) fs.closeSync(descriptor);
    }
}
