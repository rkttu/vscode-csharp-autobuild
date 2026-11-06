'use strict';

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { promisify } = require('node:util');
const { createRecovery } = require('./recovery.cjs');

const READY = 'terminal-cleanup-v1';
const STAGING = 'terminal-cleanup-staging-v1';
const KIND = 'netcoredbg-terminal-output';
const execFile = promisify(childProcess.execFile);

function fixture(t) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'netcoredbg-fba-recovery-'));
    t.after(() => {
        assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
        assert(path.basename(root).startsWith('netcoredbg-fba-recovery-'));
        fs.rmSync(root, { recursive: true, force: true });
    });
    const base = path.join(root, 'outputs');
    fs.mkdirSync(base);
    const owned = new Set();
    const removals = [];
    const logs = [];
    function run(ownedByHost = true) {
        const parent = path.join(base, 'a'.repeat(24));
        fs.mkdirSync(parent, { recursive: true });
        const directory = fs.mkdtempSync(path.join(parent, 'run-'));
        fs.writeFileSync(path.join(directory, 'FileApp.dll'), 'dll');
        fs.writeFileSync(path.join(directory, 'FileApp.pdb'), 'pdb');
        if (ownedByHost) owned.add(directory);
        return directory;
    }
    function manager(options = {}) {
        return createRecovery({
            baseDirectory: base,
            isOwned: directory => owned.has(directory),
            removeOutput: async (directory, settings) => {
                removals.push({ directory, settings });
                await fs.promises.rm(directory, settings);
            },
            log: message => logs.push(message),
            ...options,
        });
    }
    function ready(options = {}) {
        const entryId = options.entryId || crypto.randomUUID();
        const directory = path.join(base, READY, entryId);
        fs.mkdirSync(path.join(directory, 'output'), { recursive: true });
        fs.writeFileSync(path.join(directory, 'output', 'sentinel'), 'terminal');
        const record = options.record === undefined ? { version: 1, kind: KIND, entryId } : options.record;
        fs.writeFileSync(path.join(directory, 'record.json'), typeof record === 'string' ? record : JSON.stringify(record));
        return { directory, entryId, output: path.join(directory, 'output'), marker: path.join(directory, 'record.json') };
    }
    function readyNames() {
        const directory = path.join(base, READY);
        return fs.existsSync(directory) ? fs.readdirSync(directory) : [];
    }
    function staged(options = {}) {
        const entry = ready(options);
        const directory = path.join(base, STAGING, entry.entryId);
        fs.mkdirSync(path.dirname(directory), { recursive: true });
        fs.renameSync(entry.directory, directory);
        return { ...entry, directory, output: path.join(directory, 'output'), marker: path.join(directory, 'record.json') };
    }
    return { root, base, owned, removals, logs, run, manager, ready, staged, readyNames };
}

function linkDirectory(target, link) {
    fs.symlinkSync(target, link, process.platform === 'win32' ? 'junction' : 'dir');
}

test('only owned exact run directories can enter the terminal queue', async t => {
    const f = fixture(t);
    const unknown = f.run(false);
    const manager = f.manager();
    assert.equal(await manager.preserve(unknown), false);
    assert.equal(await manager.remove(unknown), false);
    assert.equal(manager.has(unknown), false);
    assert(fs.existsSync(path.join(unknown, 'FileApp.dll')));
    const malformed = path.join(f.base, 'unexpected', 'run-ABCDEF');
    fs.mkdirSync(malformed, { recursive: true });
    f.owned.add(malformed);
    assert.equal(await manager.preserve(malformed), false);
    const missing = path.join(f.base, 'b'.repeat(24), 'run-ABCDEF');
    f.owned.add(missing);
    assert.equal(await manager.preserve(missing), false);
    const outside = path.join(f.root, 'outside', 'run-ABCDEF');
    fs.mkdirSync(outside, { recursive: true });
    fs.writeFileSync(path.join(outside, 'sentinel'), 'keep');
    f.owned.add(outside);
    assert.equal(await manager.preserve(outside), false);
    assert(fs.existsSync(path.join(outside, 'sentinel')));
    assert.deepEqual(f.readyNames(), []);
    assert.equal(f.removals.length, 0);
});

test('preserve publishes exact terminal metadata and same-host removal uses the fixed queued output', async t => {
    const f = fixture(t);
    const original = f.run();
    const manager = f.manager();
    assert.equal(await manager.preserve(original), true);
    assert.equal(manager.has(original), true);
    assert.equal(fs.existsSync(original), false);
    const [entryId] = f.readyNames();
    const entry = path.join(f.base, READY, entryId);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(entry, 'record.json'), 'utf8')), { version: 1, kind: KIND, entryId });
    assert.deepEqual(fs.readdirSync(entry).sort(), ['output', 'record.json']);
    assert.equal(await manager.preserve(original), true);
    assert.equal(await manager.remove(original), true);
    assert.equal(manager.has(original), false);
    assert.equal(await manager.remove(original), false);
    assert.deepEqual(f.readyNames(), []);
    assert.equal(f.removals.length, 1);
    assert.equal(f.removals[0].directory, path.join(entry, 'output'));
    assert.deepEqual(f.removals[0].settings, { recursive: true, force: true, maxRetries: 3, retryDelay: 50 });
});

test('an unavailable directory identity refuses preservation without moving the original', async t => {
    const f = fixture(t);
    const original = f.run();
    const manager = f.manager({ fs: { promises: { ...fs.promises, lstat: async (target, options) => {
        const stat = await fs.promises.lstat(target, options);
        if (target === original && options?.bigint) {
            Object.assign(stat, { dev: 0n, ino: 0n, birthtimeNs: 0n, birthtimeMs: 0n });
        }
        return stat;
    } } } });
    assert.equal(await manager.preserve(original), false);
    assert.equal(manager.has(original), false);
    assert(fs.existsSync(path.join(original, 'FileApp.dll')));
    assert.deepEqual(f.readyNames(), []);
    assert.equal(fs.existsSync(path.join(f.base, STAGING)), false);
    assert.equal(f.removals.length, 0);
});

test('a fresh manager recovers terminal output while unmarked and live original runs survive', async t => {
    const f = fixture(t);
    const terminal = f.run();
    const live = f.run();
    const unknown = f.run(false);
    await f.manager().preserve(terminal);
    const fresh = f.manager({ isOwned: () => false });
    assert.deepEqual(await fresh.recover(), { scanned: 1, attempted: 1, removed: 1 });
    assert(fs.existsSync(path.join(live, 'FileApp.dll')));
    assert(fs.existsSync(path.join(unknown, 'FileApp.dll')));
    assert.deepEqual(f.readyNames(), []);
});

test('partial recursive removal leaves the sibling journal for the next fresh manager', async t => {
    const f = fixture(t);
    const original = f.run();
    await f.manager().preserve(original);
    const entry = path.join(f.base, READY, f.readyNames()[0]);
    const failed = f.manager({ removeOutput: async directory => {
        await fs.promises.unlink(path.join(directory, 'FileApp.dll'));
        throw Object.assign(new Error('busy PDB'), { code: 'EPERM' });
    } });
    assert.deepEqual(await failed.recover(), { scanned: 1, attempted: 1, removed: 0 });
    assert(fs.existsSync(path.join(entry, 'record.json')));
    assert(fs.existsSync(path.join(entry, 'output', 'FileApp.pdb')));
    assert.deepEqual(await f.manager().recover(), { scanned: 1, attempted: 1, removed: 1 });
    assert.deepEqual(f.readyNames(), []);
});

test('same-host receipts never target a replacement original after another host has recovered', async t => {
    const f = fixture(t);
    const original = f.run();
    const first = f.manager();
    await first.preserve(original);
    await f.manager().recover();
    fs.mkdirSync(original);
    fs.writeFileSync(path.join(original, 'unrelated'), 'keep');
    assert.equal(await first.remove(original), true);
    assert.equal(first.has(original), false);
    assert.equal(fs.readFileSync(path.join(original, 'unrelated'), 'utf8'), 'keep');
});

test('a missing queued output leaves only journal housekeeping to recovery', async t => {
    const f = fixture(t);
    const entry = f.ready();
    fs.rmSync(entry.output, { recursive: true });
    assert.deepEqual(await f.manager().recover(), { scanned: 1, attempted: 1, removed: 1 });
    assert.equal(f.removals.length, 0);
    assert.equal(fs.existsSync(entry.directory), false);
});

test('a source run symlink or junction cannot be preserved', async t => {
    const f = fixture(t);
    const outside = path.join(f.root, 'outside');
    fs.mkdirSync(outside);
    fs.writeFileSync(path.join(outside, 'sentinel'), 'keep');
    const source = path.join(f.base, 'a'.repeat(24), 'run-ABCDEF');
    fs.mkdirSync(path.dirname(source));
    linkDirectory(outside, source);
    f.owned.add(source);
    assert.equal(await f.manager().preserve(source), false);
    assert.equal(fs.readFileSync(path.join(outside, 'sentinel'), 'utf8'), 'keep');
    assert.equal(f.removals.length, 0);
});

test('a redirected source hash parent cannot be preserved', async t => {
    const f = fixture(t);
    const outside = path.join(f.root, 'outside');
    fs.mkdirSync(path.join(outside, 'run-ABCDEF'), { recursive: true });
    fs.writeFileSync(path.join(outside, 'run-ABCDEF', 'sentinel'), 'keep');
    linkDirectory(outside, path.join(f.base, 'a'.repeat(24)));
    const original = path.join(f.base, 'a'.repeat(24), 'run-ABCDEF');
    f.owned.add(original);
    assert.equal(await f.manager().preserve(original), false);
    assert.equal(f.removals.length, 0);
    assert(fs.existsSync(path.join(outside, 'run-ABCDEF', 'sentinel')));
});

test('a base directory symlink or junction is refused by preserve and background recovery', async t => {
    const f = fixture(t);
    const alias = path.join(f.root, 'alias');
    linkDirectory(f.base, alias);
    const original = f.run();
    const aliased = path.join(alias, path.relative(f.base, original));
    const manager = f.manager({ baseDirectory: alias, isOwned: () => true });
    assert.equal(await manager.preserve(aliased), false);
    assert.deepEqual(await manager.recover(), { scanned: 0, attempted: 0, removed: 0 });
    assert(fs.existsSync(path.join(original, 'FileApp.dll')));
    assert.equal(f.removals.length, 0);
});

test('a redirected ready queue cannot escape to another directory', async t => {
    const f = fixture(t);
    const entry = f.ready();
    const outside = path.join(f.root, 'outside-ready');
    fs.renameSync(path.join(f.base, READY), outside);
    linkDirectory(outside, path.join(f.base, READY));
    assert.deepEqual(await f.manager().recover(), { scanned: 0, attempted: 0, removed: 0 });
    assert(fs.existsSync(path.join(outside, entry.entryId, 'output', 'sentinel')));
    assert.equal(f.removals.length, 0);
});

test('a redirected staging queue is refused without moving the owned original', async t => {
    const f = fixture(t);
    const original = f.run();
    const outside = path.join(f.root, 'outside-staging');
    fs.mkdirSync(outside);
    linkDirectory(outside, path.join(f.base, STAGING));
    await assert.rejects(f.manager().preserve(original), /real directory|redirected/);
    assert(fs.existsSync(path.join(original, 'FileApp.dll')));
    assert.deepEqual(fs.readdirSync(outside), []);
});

test('a terminal entry symlink or junction is preserved with its outside target', async t => {
    const f = fixture(t);
    const entry = f.ready();
    const outside = path.join(f.root, 'outside-entry');
    fs.renameSync(entry.directory, outside);
    linkDirectory(outside, entry.directory);
    assert.equal((await f.manager().recover()).removed, 0);
    assert(fs.existsSync(path.join(outside, 'output', 'sentinel')));
    assert.equal(f.removals.length, 0);
});

test('a queued output symlink or junction is preserved with its outside target', async t => {
    const f = fixture(t);
    const entry = f.ready();
    const outside = path.join(f.root, 'outside-output');
    fs.renameSync(entry.output, outside);
    linkDirectory(outside, entry.output);
    assert.equal((await f.manager().recover()).removed, 0);
    assert(fs.existsSync(path.join(outside, 'sentinel')));
    assert(fs.existsSync(entry.marker));
    assert.equal(f.removals.length, 0);
});

test('an internal output link is removed without traversing its outside target', async t => {
    const f = fixture(t);
    const entry = f.ready();
    const outside = path.join(f.root, 'outside-nested');
    fs.mkdirSync(outside);
    fs.writeFileSync(path.join(outside, 'sentinel'), 'keep');
    linkDirectory(outside, path.join(entry.output, 'nested-link'));
    assert.equal((await f.manager().recover()).removed, 1);
    assert.equal(fs.readFileSync(path.join(outside, 'sentinel'), 'utf8'), 'keep');
});

test('a symbolic-link record cannot authorize deletion', async t => {
    const f = fixture(t);
    const entry = f.ready();
    const outside = path.join(f.root, 'outside-record.json');
    fs.renameSync(entry.marker, outside);
    try { fs.symlinkSync(outside, entry.marker, 'file'); } catch (error) {
        if (process.platform === 'win32' && error.code === 'EPERM') { t.skip('Windows file symlink privilege is unavailable; junction guards run separately.'); return; }
        throw error;
    }
    assert.equal((await f.manager().recover()).removed, 0);
    assert(fs.existsSync(path.join(entry.output, 'sentinel')));
    assert.equal(f.removals.length, 0);
});

const invalidRecords = [
    ['malformed JSON', '{'],
    ['future version', id => ({ version: 2, kind: KIND, entryId: id })],
    ['wrong kind', id => ({ version: 1, kind: 'other-extension', entryId: id })],
    ['mismatched id', () => ({ version: 1, kind: KIND, entryId: crypto.randomUUID() })],
    ['arbitrary JSON deletion path', id => ({ version: 1, kind: KIND, entryId: id, output: '../../outside' })],
    ['missing version', id => ({ kind: KIND, entryId: id })],
    ['array', []],
    ['oversized file', ' '.repeat(4097)],
];
for (const [name, value] of invalidRecords) {
    test(`${name} cannot authorize terminal deletion`, async t => {
        const f = fixture(t);
        const id = crypto.randomUUID();
        const entry = f.ready({ entryId: id, record: typeof value === 'function' ? value(id) : value });
        assert.equal((await f.manager().recover()).removed, 0);
        assert(fs.existsSync(path.join(entry.output, 'sentinel')));
        assert(fs.existsSync(entry.marker));
        assert.equal(f.removals.length, 0);
    });
}

test('an unknown entry name and extra entry siblings are preserved', async t => {
    const f = fixture(t);
    const invalidName = f.ready({ entryId: 'unrecognized' });
    const extra = f.ready();
    fs.writeFileSync(path.join(extra.directory, 'unrelated'), 'keep');
    assert.equal((await f.manager().recover()).removed, 0);
    assert(fs.existsSync(path.join(invalidName.output, 'sentinel')));
    assert.equal(fs.readFileSync(path.join(extra.directory, 'unrelated'), 'utf8'), 'keep');
    assert(fs.existsSync(path.join(extra.output, 'sentinel')));
    assert.equal(f.removals.length, 0);
});

test('a record directory cannot authorize deletion', async t => {
    const f = fixture(t);
    const entry = f.ready();
    fs.unlinkSync(entry.marker);
    fs.mkdirSync(entry.marker);
    assert.equal((await f.manager().recover()).removed, 0);
    assert(fs.existsSync(path.join(entry.output, 'sentinel')));
});

test('publication failure leaves complete staging recoverable by a new host and idempotent for its owner', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        if (path.dirname(to) === path.join(f.base, READY) && fail) {
            fail = false;
            throw Object.assign(new Error('ready rename busy'), { code: 'EPERM' });
        }
        return fs.promises.rename(from, to);
    } } } });
    await assert.rejects(manager.preserve(original), /ready rename busy/);
    assert.equal(manager.has(original), true);
    assert.equal(fs.existsSync(original), false);
    const [id] = fs.readdirSync(path.join(f.base, STAGING));
    const stagedOutput = path.join(f.base, STAGING, id, 'output');
    assert(fs.existsSync(path.join(stagedOutput, 'FileApp.dll')));
    assert.equal((await f.manager().recover()).removed, 1);
    assert(!fs.existsSync(stagedOutput));
    assert.equal(await manager.remove(original), true);
    assert.equal(manager.has(original), false);
    assert.equal(fs.existsSync(stagedOutput), false);
    assert.deepEqual(f.readyNames(), []);
});

test('complete staging recovery removes a valid terminal payload while unmarked output survives', async t => {
    const f = fixture(t);
    const entry = f.staged();
    const unmarked = f.run(false);
    assert.deepEqual(await f.manager({ isOwned: () => false }).recover(), { scanned: 1, attempted: 1, removed: 1 });
    assert(!fs.existsSync(entry.directory));
    assert.deepEqual(f.readyNames(), []);
    assert(fs.existsSync(path.join(unmarked, 'FileApp.dll')));
});

test('complete staging recovery lets a paused original owner finish without touching its replacement', async t => {
    const f = fixture(t);
    const original = f.run();
    let reached;
    const waiting = new Promise(resolve => { reached = resolve; });
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const owner = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        if (path.dirname(to) === path.join(f.base, READY)) { reached(); await gate; }
        return fs.promises.rename(from, to);
    } } } });
    const pending = owner.preserve(original);
    void pending.catch(() => {});
    try {
        await waiting;
        const [id] = fs.readdirSync(path.join(f.base, STAGING));
        assert(fs.existsSync(path.join(f.base, STAGING, id, 'output', 'FileApp.dll')));
        fs.mkdirSync(original);
        fs.writeFileSync(path.join(original, 'replacement'), 'keep replacement');
        assert.equal((await f.manager().recover()).removed, 1);
        release();
        assert.equal(await pending, true);
        assert.equal(await owner.remove(original), true);
        assert.equal(owner.has(original), false);
        assert.equal(fs.readFileSync(path.join(original, 'replacement'), 'utf8'), 'keep replacement');
        assert.deepEqual(f.readyNames(), []);
    } finally { release(); await pending.catch(() => {}); }
});

test('complete staging recovery reconciles a late ready rename error after another host consumes the entry', async t => {
    const f = fixture(t);
    const original = f.run();
    let owner;
    owner = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        await fs.promises.rename(from, to);
        if (path.dirname(to) === path.join(f.base, READY)) {
            assert.equal((await f.manager().recover()).removed, 1);
            fs.mkdirSync(original);
            fs.writeFileSync(path.join(original, 'replacement'), 'keep after late error');
            throw Object.assign(new Error('late publication completion error'), { code: 'EPERM' });
        }
    } } } });
    assert.equal(await owner.preserve(original), true);
    assert.equal(await owner.remove(original), true);
    assert.equal(fs.readFileSync(path.join(original, 'replacement'), 'utf8'), 'keep after late error');
    assert.equal(owner.has(original), false);
});

test('complete staging recovery confirms a late source move without reopening a replacement', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const owner = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        await fs.promises.rename(from, to);
        if (from === original && fail) { fail = false; throw new Error('late source completion'); }
    } } } });
    await assert.rejects(owner.preserve(original), /late source completion/);
    fs.mkdirSync(original);
    fs.writeFileSync(path.join(original, 'replacement'), 'preserve late source replacement');
    assert.equal(await owner.remove(original), true);
    assert.equal(owner.has(original), false);
    assert.equal(fs.readFileSync(path.join(original, 'replacement'), 'utf8'), 'preserve late source replacement');
    assert.deepEqual(f.readyNames(), []);
});

test('complete staging recovery retains ambiguous source-move ownership after another host consumes it', async t => {
    const f = fixture(t);
    const original = f.run();
    const failure = new Error('unconfirmed source completion');
    const owner = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        await fs.promises.rename(from, to);
        if (from === original) {
            assert.equal((await f.manager().recover()).removed, 1);
            fs.mkdirSync(original);
            fs.writeFileSync(path.join(original, 'replacement'), 'preserve ambiguous replacement');
            throw failure;
        }
    } } } });
    await assert.rejects(owner.preserve(original), error => error === failure);
    await assert.rejects(owner.remove(original), /missing staged output/);
    assert.equal(owner.has(original), true, 'An unconfirmed source move may retain bookkeeping but cannot reclaim its old path');
    assert.equal(fs.readFileSync(path.join(original, 'replacement'), 'utf8'), 'preserve ambiguous replacement');
    assert.equal(f.removals.length, 1, 'Only the other host may delete the already-complete terminal payload');
});

test('complete staging recovery shares the 32 entry scan budget with the ready queue', async t => {
    const f = fixture(t);
    for (let index = 0; index < 31; index++) fs.mkdirSync(path.join(f.base, READY, `unknown-${index}`), { recursive: true });
    const entry = f.staged();
    assert.deepEqual(await f.manager().recover(), { scanned: 32, attempted: 1, removed: 1 });
    assert(!fs.existsSync(entry.directory));
    assert.equal(f.readyNames().length, 31);
});

test('complete staging recovery charges a failed promotion as its one attempt and preserves every payload', async t => {
    const f = fixture(t);
    const first = f.staged();
    const second = f.staged();
    let moves = 0;
    const manager = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        moves++;
        throw Object.assign(new Error('publication busy'), { code: 'EPERM' });
    } } } });
    assert.deepEqual(await manager.recover(), { scanned: 1, attempted: 1, removed: 0 });
    assert.equal(moves, 1);
    assert(fs.existsSync(path.join(first.output, 'sentinel')));
    assert(fs.existsSync(path.join(second.output, 'sentinel')));
    assert.equal(f.removals.length, 0);
});

test('complete staging recovery permits concurrent promoters and removers without losing terminal data', async t => {
    const f = fixture(t);
    const entry = f.staged();
    let arrivals = 0;
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const io = { promises: { ...fs.promises, rename: async (from, to) => {
        if (from === entry.directory) { if (++arrivals === 2) release(); await gate; }
        return fs.promises.rename(from, to);
    } } };
    const results = await Promise.all([f.manager({ fs: io }).recover(), f.manager({ fs: io }).recover()]);
    assert(results.every(result => result.attempted === 1), JSON.stringify(results));
    assert(results.some(result => result.removed === 1));
    assert(!fs.existsSync(entry.directory));
    assert.deepEqual(f.readyNames(), []);
});

test('staging eligibility preserves record-only, output-only, malformed and extra-content entries', async t => {
    const f = fixture(t);
    const recordOnly = f.staged();
    fs.rmSync(recordOnly.output, { recursive: true });
    const outputOnly = f.staged();
    fs.unlinkSync(outputOnly.marker);
    const malformed = f.staged({ record: '{broken' });
    const extra = f.staged();
    fs.writeFileSync(path.join(extra.directory, '.record-incomplete.tmp'), 'partial');
    assert.deepEqual(await f.manager().recover(), { scanned: 4, attempted: 0, removed: 0 });
    assert(fs.existsSync(recordOnly.marker));
    for (const entry of [outputOnly, malformed, extra]) assert(fs.existsSync(path.join(entry.output, 'sentinel')));
    assert.equal(f.removals.length, 0);
});

test('staging eligibility refuses an entry duplicated in ready instead of overwriting either payload', async t => {
    const f = fixture(t);
    const staged = f.staged();
    const ready = f.ready({ entryId: staged.entryId, record: '{invalid ready' });
    const result = await f.manager().recover();
    assert.equal(result.attempted, 0);
    assert.equal(result.removed, 0);
    assert(fs.existsSync(path.join(staged.output, 'sentinel')));
    assert(fs.existsSync(path.join(ready.output, 'sentinel')));
    assert.equal(fs.readFileSync(ready.marker, 'utf8'), '{invalid ready');
    assert.equal(f.removals.length, 0);
});

test('staging eligibility preserves both valid entries when their UUID occurs in both queues', async t => {
    const f = fixture(t);
    const staged = f.staged();
    const ready = f.ready({ entryId: staged.entryId });
    assert.deepEqual(await f.manager().recover(), { scanned: 2, attempted: 0, removed: 0 });
    assert(fs.existsSync(path.join(staged.output, 'sentinel')));
    assert(fs.existsSync(path.join(ready.output, 'sentinel')));
    assert.equal(f.removals.length, 0);
});

test('staging eligibility retains the original error when publication reconciliation also fails', async t => {
    const f = fixture(t);
    const original = f.run();
    const failure = new Error('first publication failure');
    let fail = true;
    let reconciling = false;
    const owner = f.manager({ fs: { promises: { ...fs.promises,
        rename: async (from, to) => {
            if (path.dirname(to) === path.join(f.base, READY) && fail) { reconciling = true; throw failure; }
            return fs.promises.rename(from, to);
        },
        lstat: async (...args) => {
            if (reconciling) throw new Error('later reconciliation I/O failure');
            return fs.promises.lstat(...args);
        },
    } } });
    await assert.rejects(owner.preserve(original), error => error === failure);
    assert.equal(owner.has(original), true);
    reconciling = false; fail = false;
    assert.equal(await owner.remove(original), true);
    assert.deepEqual(f.readyNames(), []);
});

for (const redirected of ['queue', 'entry', 'output']) {
    test(`staging eligibility refuses a redirected ${redirected} and preserves an external sentinel`, async t => {
        const f = fixture(t);
        const entry = f.staged();
        const target = redirected === 'queue' ? path.join(f.base, STAGING) : redirected === 'entry' ? entry.directory : entry.output;
        const outside = path.join(f.root, 'outside-staging');
        fs.renameSync(target, outside);
        linkDirectory(outside, target);
        assert.equal((await f.manager().recover()).attempted, 0);
        const payload = redirected === 'queue' ? path.join(outside, entry.entryId, 'output', 'sentinel') :
            redirected === 'entry' ? path.join(outside, 'output', 'sentinel') : path.join(outside, 'sentinel');
        assert.equal(fs.readFileSync(payload, 'utf8'), 'terminal');
        assert.equal(f.removals.length, 0);
    });
}

test('source move failure retains the original and same-host retry resumes staging', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        if (from === original && fail) { fail = false; throw new Error('source rename failed'); }
        return fs.promises.rename(from, to);
    } } } });
    await assert.rejects(manager.preserve(original), /source rename failed/);
    assert(fs.existsSync(path.join(original, 'FileApp.dll')));
    assert.equal(manager.has(original), true);
    assert.equal(await manager.remove(original), true);
    assert.equal(fs.existsSync(original), false);
});

test('a failed source-move retry refuses a replacement directory at the original path', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        if (from === original && fail) { fail = false; throw new Error('source rename failed'); }
        return fs.promises.rename(from, to);
    } } } });
    await assert.rejects(manager.preserve(original), /source rename failed/);
    // Move the old inode aside, making this a deterministic directory-identity replacement.
    const retained = path.join(f.root, 'retained-original');
    fs.renameSync(original, retained);
    fs.mkdirSync(original);
    fs.writeFileSync(path.join(original, 'unrelated'), 'keep');
    await assert.rejects(manager.remove(original), /original output was replaced/);
    assert.equal(manager.has(original), true);
    assert.equal(fs.readFileSync(path.join(original, 'unrelated'), 'utf8'), 'keep');
    assert(fs.existsSync(path.join(retained, 'FileApp.dll')));
    assert.equal(f.removals.length, 0);
});

test('a completed ready rename with a late failure can be recognized by the same host', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        await fs.promises.rename(from, to);
        if (path.dirname(to) === path.join(f.base, READY) && fail) { fail = false; throw new Error('late rename failure'); }
    } } } });
    assert.equal(await manager.preserve(original), true, 'A completed publication is recognized even if its rename reported a late failure');
    assert.equal(manager.has(original), true);
    assert.equal(await manager.remove(original), true);
    assert.deepEqual(f.readyNames(), []);
});

test('a completed source rename with a late failure can resume from its staged output', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, rename: async (from, to) => {
        await fs.promises.rename(from, to);
        if (from === original && fail) { fail = false; throw new Error('late source failure'); }
    } } } });
    await assert.rejects(manager.preserve(original), /late source failure/);
    assert.equal(fs.existsSync(original), false);
    assert.equal(await manager.remove(original), true);
    assert.deepEqual(f.readyNames(), []);
});

test('a failed marker write can retry without publishing a partial marker', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, open: async (...args) => {
        const handle = await fs.promises.open(...args);
        if (path.basename(args[0]).startsWith('.record-') && fail) {
            fail = false;
            return { writeFile: async () => { throw new Error('write failed'); }, close: () => handle.close() };
        }
        return handle;
    } } } });
    await assert.rejects(manager.preserve(original), /write failed/);
    assert(fs.existsSync(original));
    assert.deepEqual(f.readyNames(), []);
    assert.equal(await manager.remove(original), true);
});

test('a marker close-only failure leaves its temporary path tracked for retry', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ fs: { promises: { ...fs.promises, open: async (...args) => {
        const handle = await fs.promises.open(...args);
        if (path.basename(args[0]).startsWith('.record-') && fail) {
            fail = false;
            return {
                writeFile: (...values) => handle.writeFile(...values),
                sync: () => handle.sync(),
                close: async () => { await handle.close(); throw new Error('close failed'); },
            };
        }
        return handle;
    } } } });
    await assert.rejects(manager.preserve(original), /close failed/);
    assert.equal(manager.has(original), true);
    assert(fs.existsSync(original));
    assert.equal(await manager.remove(original), true);
    assert.deepEqual(f.readyNames(), []);
});

test('a same-host partial cleanup failure retains its receipt until a successful retry', async t => {
    const f = fixture(t);
    const original = f.run();
    let fail = true;
    const manager = f.manager({ removeOutput: async (directory, options) => {
        if (fail) {
            fail = false;
            await fs.promises.unlink(path.join(directory, 'FileApp.dll'));
            throw new Error('PDB busy');
        }
        await fs.promises.rm(directory, options);
    } });
    await manager.preserve(original);
    await assert.rejects(manager.remove(original), /PDB busy/);
    assert.equal(manager.has(original), true);
    const entry = path.join(f.base, READY, f.readyNames()[0]);
    assert(fs.existsSync(path.join(entry, 'record.json')));
    assert.equal(await manager.remove(original), true);
    assert.equal(manager.has(original), false);
});

test('recovery scans no more than 32 entries and never traverses unknown entries', async t => {
    const f = fixture(t);
    for (let index = 0; index < 40; index++) fs.mkdirSync(path.join(f.base, READY, `unknown-${index}`), { recursive: true });
    assert.deepEqual(await f.manager().recover(), { scanned: 32, attempted: 0, removed: 0 });
    assert.equal(f.readyNames().length, 40);
    assert.equal(f.removals.length, 0);
});

test('one recovery pass attempts only one terminal deletion', async t => {
    const f = fixture(t);
    f.ready(); f.ready(); f.ready();
    assert.deepEqual(await f.manager().recover(), { scanned: 1, attempted: 1, removed: 1 });
    assert.equal(f.readyNames().length, 2);
    assert.equal(f.removals.length, 1);
});

test('a failed deletion still consumes the single attempt per pass and logging cannot reject recovery', async t => {
    const f = fixture(t);
    f.ready(); f.ready();
    let calls = 0;
    const manager = f.manager({ removeOutput: async () => { calls++; throw new Error('busy'); }, log: () => { throw new Error('disposed'); } });
    assert.deepEqual(await manager.recover(), { scanned: 1, attempted: 1, removed: 0 });
    assert.equal(calls, 1);
    assert.equal(f.readyNames().length, 2);
});

test('overlapping recovery calls share one pass', async t => {
    const f = fixture(t);
    f.ready();
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let began;
    const started = new Promise(resolve => { began = resolve; });
    let calls = 0;
    const manager = f.manager({ removeOutput: async (directory, settings) => { calls++; began(); await gate; await fs.promises.rm(directory, settings); } });
    const first = manager.recover();
    const second = manager.recover();
    assert.strictEqual(first, second);
    await started;
    release();
    assert.equal((await first).removed, 1);
    assert.equal(calls, 1);
});

test('native directory iterators close handles when unexpected entry content throws', async t => {
    const f = fixture(t);
    const entry = f.ready();
    fs.writeFileSync(path.join(entry.directory, 'unrelated.txt'), 'keep');
    const handles = [];
    const io = { ...fs.promises, opendir: async (...args) => {
        const handle = await fs.promises.opendir(...args);
        handles.push(handle);
        return handle;
    } };
    assert.equal((await f.manager({ fs: io }).recover()).attempted, 0);
    assert(handles.length >= 2);
    for (const handle of handles) await assert.rejects(async () => handle.read(), { code: 'ERR_DIR_CLOSED' });
    assert(fs.existsSync(path.join(entry.directory, 'unrelated.txt')));
    assert(fs.existsSync(entry.output));
});

test('native directory iterators close handles when a bounded recovery pass breaks', async t => {
    const f = fixture(t);
    f.ready();
    const handles = [];
    const io = { ...fs.promises, opendir: async (...args) => {
        const handle = await fs.promises.opendir(...args);
        handles.push(handle);
        return handle;
    } };
    assert.equal((await f.manager({ fs: io }).recover()).removed, 1);
    assert(handles.length >= 3);
    for (const handle of handles) await assert.rejects(async () => handle.read(), { code: 'ERR_DIR_CLOSED' });
});

test('two hosts can concurrently recover the same immutable entry', async t => {
    const f = fixture(t);
    const entry = f.ready();
    let calls = 0;
    let release;
    const bothStarted = new Promise(resolve => { release = resolve; });
    const removeOutput = async (directory, settings) => {
        calls++;
        if (calls === 2) release();
        await bothStarted;
        await fs.promises.rm(directory, settings);
    };
    const results = await Promise.all([f.manager({ removeOutput }).recover(), f.manager({ removeOutput }).recover()]);
    assert(results.every(result => result.attempted === 1 && result.removed === 1), JSON.stringify({ results, logs: f.logs }));
    assert.equal(fs.existsSync(entry.directory), false);
    assert.equal(f.logs.length, 0);
});

for (const operation of ['unlink', 'rmdir']) {
    test(`concurrent ${operation} reporting EPERM after deletion is confirmed absent remains idempotent`, async t => {
        const f = fixture(t);
        const entry = f.ready();
        const target = operation === 'unlink' ? entry.marker : entry.directory;
        const manager = f.manager({ fs: { promises: { ...fs.promises, [operation]: async location => {
            await fs.promises[operation](location);
            if (location === target) throw Object.assign(new Error('concurrent deletion'), { code: 'EPERM' });
        } } } });
        assert.deepEqual(await manager.recover(), { scanned: 1, attempted: 1, removed: 1 });
        assert.equal(fs.existsSync(entry.directory), false);
        assert.equal(f.logs.length, 0);
    });
}

test('EPERM on a still-present journal is retained as a real cleanup failure', async t => {
    const f = fixture(t);
    const entry = f.ready();
    const manager = f.manager({ fs: { promises: { ...fs.promises, unlink: async target => {
        if (target === entry.marker) throw Object.assign(new Error('journal permission denied'), { code: 'EPERM' });
        return fs.promises.unlink(target);
    } } } });
    assert.deepEqual(await manager.recover(), { scanned: 1, attempted: 1, removed: 0 });
    assert(fs.existsSync(entry.marker));
    assert.equal(fs.existsSync(entry.output), false);
    assert.equal(f.logs.length, 1);
    assert.equal((await f.manager().recover()).removed, 1);
});

test('recovery does not create a missing base directory', async t => {
    const f = fixture(t);
    const missing = path.join(f.root, 'missing');
    assert.deepEqual(await f.manager({ baseDirectory: missing }).recover(), { scanned: 0, attempted: 0, removed: 0 });
    assert.equal(fs.existsSync(missing), false);
});

test('terminal recovery survives the owner Node process exiting and preserves unmarked live output', { timeout: 15000 }, async t => {
    const f = fixture(t);
    const terminal = f.run();
    const live = f.run(false);
    const modulePath = require.resolve('./recovery.cjs');
    const childSource = `
        const fs = require('node:fs');
        const { createRecovery } = require(process.argv[1]);
        const [baseDirectory, original, mode] = process.argv.slice(2);
        const manager = createRecovery({ baseDirectory, isOwned: value => value === original,
            removeOutput: (directory, options) => fs.promises.rm(directory, options) });
        (async () => {
            const result = mode === 'preserve' ? await manager.preserve(original) : await manager.recover();
            process.stdout.write(JSON.stringify(result));
        })().catch(error => { console.error(error); process.exitCode = 1; });
    `;
    const first = await execFile(process.execPath, ['--unhandled-rejections=strict', '-e', childSource, modulePath, f.base, terminal, 'preserve'], { windowsHide: true });
    assert.equal(JSON.parse(first.stdout), true);
    assert.equal(fs.existsSync(terminal), false);
    assert.equal(f.readyNames().length, 1);
    const second = await execFile(process.execPath, ['--unhandled-rejections=strict', '-e', childSource, modulePath, f.base, '', 'recover'], { windowsHide: true });
    assert.deepEqual(JSON.parse(second.stdout), { scanned: 1, attempted: 1, removed: 1 });
    assert.deepEqual(f.readyNames(), []);
    assert(fs.existsSync(path.join(live, 'FileApp.dll')));
    assert(fs.existsSync(path.join(live, 'FileApp.pdb')));
});
