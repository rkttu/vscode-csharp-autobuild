'use strict';

const crypto = require('node:crypto');
const nativeFs = require('node:fs');
const path = require('node:path');

const READY = 'terminal-cleanup-v1';
const STAGING = 'terminal-cleanup-staging-v1';
const KIND = 'netcoredbg-terminal-output';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MAX_RECORD_BYTES = 4096;

function createRecovery({ baseDirectory, removeOutput, isOwned, log = () => {}, fs = nativeFs }) {
    // The caller establishes terminal state. Ownership, host exit, PID or age alone cannot establish it.
    // Only fully published terminal entries are recoverable after this host loses its in-memory map.
    const io = fs.promises || fs;
    const base = path.resolve(baseDirectory);
    const tracked = new Map();
    let recovering;

    const keyFor = directory => path.resolve(directory);
    const samePath = (left, right) => process.platform === 'win32'
        ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
        : path.resolve(left) === path.resolve(right);
    const unsafe = message => Object.assign(new Error(`Unsafe terminal output recovery: ${message}`), { code: 'ERR_UNSAFE_TERMINAL_OUTPUT' });
    const report = error => {
        try { log(`Could not recover terminal file-app output: ${error?.message || String(error)}`); } catch { /* Best effort. */ }
    };
    async function statOrMissing(target) {
        try { return await io.lstat(target); } catch (error) {
            if (error.code === 'ENOENT') return undefined;
            throw error;
        }
    }
    async function realDirectory(target, physicalTarget) {
        const stat = await statOrMissing(target);
        if (!stat) return false;
        if (!stat.isDirectory() || stat.isSymbolicLink()) throw unsafe(`not a real directory: ${target}`);
        if (physicalTarget && !samePath(await io.realpath(target), physicalTarget)) {
            throw unsafe(`redirected directory: ${target}`);
        }
        return true;
    }
    async function physicalBase() {
        if (!await realDirectory(base)) return undefined;
        return io.realpath(base);
    }
    async function queueDirectory(name, create = false) {
        const physical = await physicalBase();
        if (!physical) return undefined;
        const directory = path.join(base, name);
        if (create) {
            try { await io.mkdir(directory); } catch (error) { if (error.code !== 'EEXIST') throw error; }
        }
        return await realDirectory(directory, path.join(physical, name)) ? directory : undefined;
    }
    async function ownedSource(original) {
        if (!isOwned(original)) return false;
        const relative = path.relative(base, keyFor(original));
        const parts = relative.split(path.sep);
        if (parts.length !== 2 || !/^[0-9a-f]{24}$/.test(parts[0]) || !/^run-[A-Za-z0-9]{6}$/.test(parts[1])) return false;
        const physical = await physicalBase();
        if (!physical) return false;
        if (!await realDirectory(path.join(base, parts[0]), path.join(physical, parts[0]))) return false;
        return realDirectory(keyFor(original), path.join(physical, ...parts));
    }
    async function sourceIdentity(original) {
        const stat = await io.lstat(original, { bigint: true });
        if (!stat.isDirectory() || stat.isSymbolicLink()) throw unsafe('original output is not a real directory');
        const birthtime = stat.birthtimeNs ?? stat.birthtimeMs;
        if ([stat.dev, stat.ino, birthtime].some(value => typeof value !== 'bigint') ||
            stat.dev < 0n || stat.ino <= 0n || birthtime <= 0n) {
            throw unsafe('original directory identity is unavailable');
        }
        return [stat.dev, stat.ino, birthtime].join(':');
    }
    async function recordFor(entry, entryId) {
        const marker = path.join(entry, 'record.json');
        const stat = await statOrMissing(marker);
        if (!stat || !stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_RECORD_BYTES) throw unsafe(`invalid record: ${entry}`);
        const handle = await io.open(marker, 'r');
        let record;
        try {
            const opened = await handle.stat();
            if (!opened.isFile() || opened.size > MAX_RECORD_BYTES) throw unsafe(`oversized or invalid record: ${entry}`);
            const buffer = Buffer.alloc(MAX_RECORD_BYTES + 1);
            const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
            if (bytesRead !== opened.size || bytesRead > MAX_RECORD_BYTES) throw unsafe(`incomplete or oversized record: ${entry}`);
            try { record = JSON.parse(buffer.subarray(0, bytesRead).toString('utf8')); } catch { throw unsafe(`malformed record: ${entry}`); }
        } finally {
            await handle.close();
        }
        if (!record || Array.isArray(record) || Object.keys(record).sort().join(',') !== 'entryId,kind,version' ||
            record.version !== 1 || record.kind !== KIND || record.entryId !== entryId || !UUID.test(record.entryId)) {
            throw unsafe(`unsupported record: ${entry}`);
        }
    }
    async function entryContents(entry, allowed) {
        const directory = await io.opendir(entry);
        // Node's async directory iterator closes its handle on exhaustion, break and loop-body throws.
        for await (const child of directory) {
            if (!allowed.has(child.name)) throw unsafe(`unexpected entry content: ${entry}`);
        }
    }
    async function inspectEntry(parentName, entryId) {
        if (!UUID.test(entryId)) throw unsafe('invalid entry name');
        const parent = await queueDirectory(parentName);
        if (!parent) return undefined;
        const entry = path.join(parent, entryId);
        const physical = await io.realpath(parent);
        if (!await realDirectory(entry, path.join(physical, entryId))) return undefined;
        await entryContents(entry, new Set(['record.json', 'output']));
        await recordFor(entry, entryId);
        const output = path.join(entry, 'output');
        const outputExists = await realDirectory(output, path.join(physical, entryId, 'output'));
        return { entry, output, outputExists };
    }
    async function writeRecord(state) {
        const marker = path.join(state.staging, 'record.json');
        if (await statOrMissing(marker)) {
            await recordFor(state.staging, state.entryId);
            return;
        }
        // Staging is not scanned. Publish a complete marker before moving any output into it.
        const temporary = path.join(state.staging, `.record-${crypto.randomUUID()}.tmp`);
        state.temporary = temporary;
        const handle = await io.open(temporary, 'wx', 0o600);
        try {
            await handle.writeFile(`${JSON.stringify({ version: 1, kind: KIND, entryId: state.entryId })}\n`, 'utf8');
            await handle.sync();
        } finally {
            await handle.close();
        }
        await io.rename(temporary, marker);
        state.temporary = undefined;
    }
    async function resume(state) {
        if (state.ready) return true;
        const stagingParent = await queueDirectory(STAGING);
        const readyParent = await queueDirectory(READY, true);
        if (!stagingParent || !readyParent) throw unsafe('missing queue directory');
        if (!await realDirectory(state.staging, path.join(await io.realpath(stagingParent), state.entryId))) {
            // A rename can have completed even if an injected/late I/O failure obscured its result.
            if (await inspectEntry(READY, state.entryId)) { state.ready = true; return true; }
            throw unsafe('missing staged output');
        }
        if (state.temporary) {
            const stat = await statOrMissing(state.temporary);
            if (stat && (!stat.isFile() || stat.isSymbolicLink())) throw unsafe('redirected temporary record');
            try { await io.unlink(state.temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
            state.temporary = undefined;
        }
        await entryContents(state.staging, new Set(['record.json', 'output']));
        await writeRecord(state);
        const output = path.join(state.staging, 'output');
        const outputExists = await realDirectory(output, path.join(await io.realpath(stagingParent), state.entryId, 'output'));
        if (!outputExists) {
            if (!await ownedSource(state.original)) return false;
            if (await sourceIdentity(state.original) !== state.sourceIdentity) throw unsafe('original output was replaced');
            await io.rename(state.original, output);
        } else if (await statOrMissing(state.original)) {
            throw unsafe('both original and staged output exist');
        }
        await inspectEntry(STAGING, state.entryId);
        const ready = path.join(readyParent, state.entryId);
        if (await statOrMissing(ready)) throw unsafe('ready entry already exists');
        await io.rename(state.staging, ready);
        state.ready = true;
        return true;
    }
    async function preserve(original) {
        const key = keyFor(original);
        if (!isOwned(original)) return false;
        const existing = tracked.get(key);
        if (existing) return resume(existing);
        let identity;
        try {
            if (!await ownedSource(original)) return false;
            identity = await sourceIdentity(original);
        } catch (error) {
            if (['ENOENT', 'ERR_UNSAFE_TERMINAL_OUTPUT'].includes(error.code)) return false;
            throw error;
        }
        const stagingParent = await queueDirectory(STAGING, true);
        if (!stagingParent) return false;
        const entryId = crypto.randomUUID();
        const staging = path.join(stagingParent, entryId);
        await io.mkdir(staging);
        const state = { original: key, sourceIdentity: identity, entryId, staging, ready: false, temporary: undefined };
        tracked.set(key, state);
        return resume(state);
    }
    async function removeEntry(entryId, inspection) {
        const info = inspection || await inspectEntry(READY, entryId);
        if (!info) return true; // Another host may already have finished this immutable terminal entry.
        if (info.outputExists) {
            await removeOutput(info.output, { recursive: true, force: true, maxRetries: 3, retryDelay: 50 });
            if (await statOrMissing(info.output)) throw new Error(`Terminal output still exists: ${info.output}`);
        }
        // Never recursively remove the entry: its journal must survive any partial output deletion.
        try { await entryContents(info.entry, new Set(['record.json'])); } catch (error) {
            if (error.code === 'ENOENT') return true;
            throw error;
        }
        const marker = path.join(info.entry, 'record.json');
        try { await io.unlink(marker); } catch (error) {
            if (error.code !== 'ENOENT' && await statOrMissing(marker)) throw error;
        }
        try { await io.rmdir(info.entry); } catch (error) {
            // Concurrent Windows removals can report EPERM rather than ENOENT for a deleted entry.
            if (error.code !== 'ENOENT' && await statOrMissing(info.entry)) throw error;
        }
        return true;
    }
    async function remove(original) {
        const key = keyFor(original);
        const state = tracked.get(key);
        if (!state || !isOwned(original)) return false;
        if (!await resume(state)) return false;
        await removeEntry(state.entryId);
        tracked.delete(key);
        return true;
    }
    function recover() {
        if (recovering) return recovering;
        const operation = (async () => {
            const result = { scanned: 0, attempted: 0, removed: 0 };
            try {
                const parent = await queueDirectory(READY);
                if (!parent) return result;
                const directory = await io.opendir(parent);
                // for-await closes the directory when the bounded pass breaks early.
                for await (const entry of directory) {
                    result.scanned++;
                    if (UUID.test(entry.name)) {
                        try {
                            const inspection = await inspectEntry(READY, entry.name);
                            if (inspection) {
                                result.attempted++;
                                await removeEntry(entry.name, inspection);
                                result.removed++;
                            }
                        } catch (error) { report(error); }
                    }
                    if (result.scanned >= 32 || result.attempted >= 1) break;
                }
            } catch (error) { report(error); }
            return result;
        })();
        recovering = operation;
        void operation.then(() => { recovering = undefined; }, () => { recovering = undefined; });
        return operation;
    }
    return { has: original => tracked.has(keyFor(original)), preserve, remove, recover };
}

module.exports = { createRecovery };
