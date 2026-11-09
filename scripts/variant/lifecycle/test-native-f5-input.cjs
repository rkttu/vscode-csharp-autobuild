'use strict';

// Synthetic receipt/handshake tests only. No native input or editor is used.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { inputPolicy, validateReceipt, recordManualInput } = require('./native-f5-input.cjs');

const NOW = Date.parse('2026-11-09T12:00:01.000Z');
const HASH = 'a'.repeat(64);
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const clone = value => JSON.parse(JSON.stringify(value));
const iso = value => new Date(value).toISOString();
const write = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');

function sample(mode = 'native-injected') {
    const request = { schema: 1, nonce: 'profile-unique-nonce', sequence: 1, launchToken: 'exact-launch-token',
        windowTitle: 'FBA native F5 profile-unique-nonce', action: 'press-key', key: 'F5', mechanism: mode,
        requestedAtUtc: iso(NOW - 1000), expiresAtUtc: iso(NOW + 89000) };
    const receipt = { schema: 1, ...Object.fromEntries(['nonce', 'sequence', 'launchToken', 'windowTitle', 'action', 'key', 'mechanism']
        .map(key => [key, request[key]])), requestSha256: HASH,
        observedWindowTitle: '[Extension Development Host] ' + request.windowTitle, editorFocusedBeforeInput: true,
        observationPath: path.join(os.tmpdir(), 'synthetic-observation.json'), inputRecordPath: path.join(os.tmpdir(), 'synthetic-action.json') };
    if (mode === 'native-injected') Object.assign(receipt, { tool: 'sky.press_key', windowId: 12345, inputAtUtc: iso(NOW) });
    else {
        request.inputMode = mode;
        Object.assign(receipt, { inputMode: mode, tool: 'human-observer', actor: { type: 'human', id: 'synthetic-test-observer' },
            attestedAtUtc: iso(NOW), evidenceKind: 'human-attestation', nativeExecutionVerified: false,
            hardwareKeypressIndependentlyVerified: false, observationNote: 'Synthetic declaration: caret observed in the token-bearing C# editor.',
            oneF5KeyPressed: true, inputOccurredDuringRequest: true, automationUsed: false, targetCommandApiUsed: false });
    }
    return { mode, request, receipt, requestSha256: HASH, now: NOW };
}

function fixture(t) {
    const tempParent = fs.realpathSync(os.tmpdir());
    const temporary = fs.mkdtempSync(path.join(tempParent, 'native-f5-input-test-'));
    t.after(() => {
        const target = fs.realpathSync(temporary);
        const relative = path.relative(tempParent, target);
        assert(relative && !relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
        assert(path.basename(target).startsWith('native-f5-input-test-') && path.dirname(target) === tempParent,
            'Recursive test cleanup must stay in its original mkdtemp directory');
        fs.rmSync(target, { recursive: true, force: true });
    });
    const root = path.join(temporary, 'profile');
    fs.mkdirSync(root);
    fs.mkdirSync(path.join(root, 'workspace'));
    fs.mkdirSync(path.join(root, 'progress'));
    const source = path.join(root, 'workspace/a.cs');
    fs.writeFileSync(source, '// synthetic source, never executed\n');
    const candidate = path.join(root, 'local-lifecycle.vsix');
    fs.writeFileSync(candidate, 'synthetic candidate, never installed');
    const preparedInputs = [1, 2].map(sequence => ({ sequence,
        request: path.join(root, `needs-f5-input-${String(sequence).padStart(2, '0')}.json`),
        receipt: path.join(root, `f5-input-action-${String(sequence).padStart(2, '0')}.json`) }));
    const expected = { schema: 1, extensionId: 'dotnetdev-kr-custom.csharp-with-netcoredbg', scenario: 'native-f5', cycles: 2,
        candidate: { localOnly: true, published: false, sha256: digest(fs.readFileSync(candidate)),
            buildId: 'b'.repeat(64), sourceCommit: 'c'.repeat(40), path: candidate },
        scope: { localOnly: true, published: false, qualification: false },
        harness: { 'native-f5-input.cjs': digest(fs.readFileSync(require.resolve('./native-f5-input.cjs'))) },
        editor: { version: 'synthetic-editor-version', commit: 'd'.repeat(40), sha256: 'e'.repeat(64) },
        sdk: { version: 'synthetic-sdk-version', sha256: 'f'.repeat(64) },
        nativeF5: { inputMode: 'manual-native', nonce: 'profile-unique-nonce', windowTitle: 'FBA native F5 profile-unique-nonce',
            inputs: preparedInputs, closed: path.join(root, 'f5-input-closed.json') } };
    const request = { ...sample('manual-native').request, source, activeSource: source, languageId: 'csharp',
        noFolderWindow: true, workspaceFolders: [], activeDebugSessionId: null, isDirty: false,
        receipt: preparedInputs[0].receipt, closed: expected.nativeF5.closed };
    const state = { root, launches: [{ label: 'F5-1', nonce: request.launchToken, source }] };
    const expectedPath = path.join(root, 'expected.json');
    const statePath = path.join(root, 'progress/state.json');
    write(expectedPath, expected);
    write(preparedInputs[0].request, request);
    write(statePath, state);
    const options = { workDir: root, sequence: 1, observer: 'synthetic-test-observer',
        observedWindowTitle: '[Extension Development Host] ' + request.windowTitle,
        note: 'Synthetic declaration: token title and C# editor caret observed before one F5.', confirmHumanF5: true };
    const outputs = [path.join(root, 'manual-observation-01.json'), path.join(root, 'manual-action-01.json'),
        preparedInputs[0].receipt + '.tmp', preparedInputs[0].receipt];
    return { temporary, root, source, expected, expectedPath, request, state, statePath, input: preparedInputs[0], options, outputs };
}

function noOutputs(f) { for (const file of f.outputs) assert.equal(fs.existsSync(file), false, file); }
function noResult(f) {
    for (const name of ['result.json', 'launcher-result.json', 'attempt.json', 'launch.json', 'trace.jsonl']) {
        assert.equal(fs.existsSync(path.join(f.root, name)), false, 'Receipt recording must not create scenario evidence: ' + name);
    }
}

test('default policy preserves the injected mechanism and original receipt semantics', () => {
    assert.deepEqual(inputPolicy(), { mode: 'native-injected', mechanism: 'native-injected', label: 'native injected F5' });
    assert.equal(inputPolicy('manual-native').mechanism, 'manual-native');
    assert.throws(() => inputPolicy('automatic-fallback'), /Unknown/);
    const original = sample();
    const before = clone(original);
    assert.equal(validateReceipt(original), original.receipt);
    assert.deepEqual(original, before, 'Pure validation must not rewrite historical receipts');
    assert.equal(Object.hasOwn(original.receipt, 'inputMode'), false, 'Existing injected receipt does not need a new field');
});

test('manual receipt has an explicit human actor and attestation, without native execution proof', () => {
    const input = sample('manual-native');
    assert.equal(validateReceipt(input), input.receipt);
    assert.equal(input.receipt.nativeExecutionVerified, false);
    assert.equal(input.receipt.hardwareKeypressIndependentlyVerified, false);
    for (const key of ['inputAtUtc', 'windowId', 'keyCallReturned']) assert.equal(Object.hasOwn(input.receipt, key), false);
});

test('modes, actors and tools cannot be substituted or mixed', () => {
    for (const change of [
        value => { value.mode = 'native-injected'; },
        value => { value.request.inputMode = 'native-injected'; },
        value => { value.receipt.inputMode = 'native-injected'; },
        value => { value.receipt.tool = 'sky.press_key'; },
        value => { value.receipt.actor.type = 'automation'; },
        value => { value.receipt.actor.id = ' '; },
        value => { value.receipt.actor.tool = 'sky.press_key'; },
        value => { value.receipt.nativeExecutionVerified = true; },
        value => { value.receipt.hardwareKeypressIndependentlyVerified = true; },
    ]) {
        const input = sample('manual-native');
        change(input);
        assert.throws(() => validateReceipt(input));
    }
    for (const field of ['inputAtUtc', 'windowId', 'keyCallReturned', 'arguments', 'keyCallResult']) {
        const input = sample('manual-native');
        input.receipt[field] = field === 'inputAtUtc' ? iso(NOW) : false;
        assert.throws(() => validateReceipt(input), /injected measurement/);
    }
    const forged = sample();
    forged.receipt.tool = 'human-observer';
    assert.throws(() => validateReceipt(forged));
    const mixed = sample();
    mixed.receipt.actor = { type: 'human', id: 'test' };
    assert.throws(() => validateReceipt(mixed), /manual field/);
});

test('request hash, sequence, exact launch token, action and unique title remain binding', () => {
    for (const key of ['nonce', 'sequence', 'launchToken', 'windowTitle', 'action', 'key', 'mechanism', 'requestSha256']) {
        const input = sample('manual-native');
        input.receipt[key] = key === 'sequence' ? 2 : 'different';
        assert.throws(() => validateReceipt(input), undefined, key);
    }
    for (const title of ['', 'Unrelated C# window', 'profile-unique-nonce']) {
        const input = sample('manual-native');
        input.receipt.observedWindowTitle = title;
        assert.throws(() => validateReceipt(input));
    }
});

test('freshness and offset-aware timestamps are checked for both mechanisms', () => {
    for (const mode of ['native-injected', 'manual-native']) {
        const field = mode === 'manual-native' ? 'attestedAtUtc' : 'inputAtUtc';
        for (const reported of [iso(NOW - 1001), iso(NOW + 1001), '2026-11-09T12:00:01', 'not-a-time']) {
            const input = sample(mode);
            input.receipt[field] = reported;
            assert.throws(() => validateReceipt(input));
        }
        const expired = sample(mode);
        expired.now = NOW + 89001;
        assert.throws(() => validateReceipt(expired), /expired/);
        const outsideLease = sample(mode);
        outsideLease.receipt[field] = iso(NOW + 89001);
        assert.throws(() => validateReceipt(outsideLease), /lease/);
        const futureRequest = sample(mode);
        futureRequest.request.requestedAtUtc = iso(NOW + 2000);
        assert.throws(() => validateReceipt(futureRequest), /future/);
        const backwards = sample(mode);
        backwards.request.expiresAtUtc = backwards.request.requestedAtUtc;
        assert.throws(() => validateReceipt(backwards), /expiry/);
    }
});

test('human focus, one-key and no-automation declarations are required, never inferred', () => {
    for (const field of ['editorFocusedBeforeInput', 'oneF5KeyPressed', 'inputOccurredDuringRequest',
        'automationUsed', 'targetCommandApiUsed', 'observationNote', 'evidenceKind']) {
        const input = sample('manual-native');
        delete input.receipt[field];
        assert.throws(() => validateReceipt(input), undefined, field);
    }
});

test('helper publishes complete JSON without replacement and preserves separate original records', t => {
    const f = fixture(t);
    const outcome = recordManualInput(f.options, NOW);
    assert.deepEqual(outcome, { receiptPublished: true, receipt: f.input.receipt, nativeExecutionVerified: false });
    const [observation, action, staged, receipt] = f.outputs.map(file => JSON.parse(fs.readFileSync(file, 'utf8')));
    assert.deepEqual(staged, receipt);
    assert.equal(receipt.actor.type, 'human');
    assert.equal(receipt.attestedAtUtc, iso(NOW));
    assert.equal(receipt.observedWindowTitle, f.options.observedWindowTitle);
    assert.equal(receipt.requestSha256, digest(fs.readFileSync(f.input.request)));
    assert.equal(receipt.observationPath, f.outputs[0]);
    assert.equal(receipt.inputRecordPath, f.outputs[1]);
    assert.equal(receipt.producer.sha256, f.expected.harness['native-f5-input.cjs']);
    assert.equal(receipt.producer.path, require.resolve('./native-f5-input.cjs'));
    assert.equal(receipt.producer.version, 'manual-native-receipt-v1');
    assert.equal(observation.candidate.sourceCommit, f.expected.candidate.sourceCommit);
    assert.deepEqual(observation.editor, f.expected.editor);
    assert.deepEqual(observation.sdk, f.expected.sdk);
    assert.equal(action.actor.id, f.options.observer);
    assert.equal(action.oneF5KeyPressed, true);
    validateReceipt({ mode: 'manual-native', request: f.request, receipt, requestSha256: receipt.requestSha256, now: NOW });
    assert.equal(fs.statSync(f.outputs[2]).nlink, 2, 'Final publication retains its staged original hardlink');
    for (const record of [observation, action, receipt]) {
        assert.equal(record.evidenceKind, 'human-attestation');
        assert.equal(record.nativeExecutionVerified, false);
        for (const key of ['success', 'inputAtUtc', 'windowId', 'keyCallReturned']) assert.equal(Object.hasOwn(record, key), false);
    }
    noResult(f);
});

test('no confirmation, actual title, focus note or observer means no writes', t => {
    const f = fixture(t);
    for (const [key, value] of [['confirmHumanF5', false], ['observedWindowTitle', undefined], ['note', ' '], ['observer', ' ']]) {
        assert.throws(() => recordManualInput({ ...f.options, [key]: value }, NOW));
        noOutputs(f);
    }
    assert.throws(() => recordManualInput({ ...f.options, observedWindowTitle: 'A different window' }, NOW));
    noOutputs(f);
    noResult(f);
});

test('closed, expired or failed profiles cannot acquire an input receipt', async t => {
    for (const kind of ['closed', 'expired', 'failed', 'wrong-progress-profile', 'wrong-progress-token']) {
        await t.test(kind, t => {
            const f = fixture(t);
            let now = NOW;
            if (kind === 'closed') write(f.expected.nativeF5.closed, { reason: 'synthetic first failure' });
            if (kind === 'expired') now = NOW + 90000;
            if (kind === 'failed') f.state.firstFailure = { error: 'synthetic first failure' };
            if (kind === 'wrong-progress-profile') f.state.root = f.temporary;
            if (kind === 'wrong-progress-token') f.state.launches[0].nonce = 'other-launch';
            write(f.statePath, f.state);
            assert.throws(() => recordManualInput(f.options, now));
            noOutputs(f);
            noResult(f);
        });
    }
});

test('unprepared mode, candidate/source identity and helper hash mismatches fail before writes', async t => {
    const mutations = [
        f => { f.expected.nativeF5.inputMode = 'native-injected'; },
        f => { f.expected.candidate.localOnly = false; },
        f => { f.expected.candidate.published = true; },
        f => { delete f.expected.candidate.sourceCommit; },
        f => { f.expected.harness['native-f5-input.cjs'] = '0'.repeat(64); },
        f => { f.request.source = path.join(f.root, 'workspace/b.cs'); },
        f => { f.request.nonce = 'other-profile'; },
        f => { f.request.launchToken = 'other-launch'; },
        f => { f.request.sequence = 2; },
    ];
    for (let index = 0; index < mutations.length; index++) await t.test(String(index + 1), t => {
        const f = fixture(t);
        mutations[index](f);
        write(f.expectedPath, f.expected);
        write(f.input.request, f.request);
        assert.throws(() => recordManualInput(f.options, NOW));
        noOutputs(f);
        noResult(f);
    });
});

test('prepared path escape cannot redirect the helper to result files or outside the profile', async t => {
    for (const destination of ['outside', 'result', 'nested', 'request-path']) await t.test(destination, t => {
        const f = fixture(t);
        if (destination === 'outside') f.expected.nativeF5.inputs[0].receipt = path.join(f.temporary, 'foreign.json');
        if (destination === 'result') f.expected.nativeF5.inputs[0].receipt = path.join(f.root, 'result.json');
        if (destination === 'nested') f.expected.nativeF5.inputs[0].receipt = path.join(f.root, 'progress/foreign.json');
        if (destination === 'request-path') f.expected.nativeF5.inputs[0].request = path.join(f.temporary, 'request.json');
        write(f.expectedPath, f.expected);
        assert.throws(() => recordManualInput(f.options, NOW));
        noOutputs(f);
        noResult(f);
        assert.equal(fs.existsSync(path.join(f.temporary, 'foreign.json')), false);
    });
});

test('real-parent checks reject a junction or symlink in source paths', t => {
    const f = fixture(t);
    const workspace = path.join(f.root, 'workspace');
    const moved = path.join(f.temporary, 'other-workspace');
    // Move a known synthetic directory only; no recursive move/delete is used.
    fs.renameSync(workspace, moved);
    fs.symlinkSync(moved, workspace, process.platform === 'win32' ? 'junction' : 'dir');
    assert.throws(() => recordManualInput(f.options, NOW), /symbolic links|real parent/);
    noOutputs(f);
    noResult(f);
});

test('existing receipt, staging or originals are never overwritten', async t => {
    for (let index = 0; index < 4; index++) await t.test(String(index), t => {
        const f = fixture(t);
        const original = Buffer.from('original failure evidence\n');
        fs.writeFileSync(f.outputs[index], original);
        assert.throws(() => recordManualInput(f.options, NOW));
        assert.deepEqual(fs.readFileSync(f.outputs[index]), original);
        for (let other = 0; other < 4; other++) if (other !== index) assert.equal(fs.existsSync(f.outputs[other]), false);
        noResult(f);
    });
});

test('a completed receipt cannot be replayed or reused for a different input sequence', t => {
    const f = fixture(t);
    recordManualInput(f.options, NOW);
    const originals = f.outputs.map(file => fs.readFileSync(file));
    assert.throws(() => recordManualInput(f.options, NOW));
    assert.throws(() => recordManualInput({ ...f.options, sequence: 2 }, NOW));
    f.outputs.forEach((file, index) => assert.deepEqual(fs.readFileSync(file), originals[index]));
    noResult(f);
});

test('a changed request, closed gate, first failure or expiry before publication retains originals without a receipt', async t => {
    for (const kind of ['request', 'closed', 'failed', 'expired', 'existing-final']) await t.test(kind, t => {
        const f = fixture(t);
        let calls = 0;
        const clock = () => {
            calls++;
            if (calls === 2) {
                if (kind === 'request') { f.request.launchToken = 'changed-after-staging'; write(f.input.request, f.request); }
                if (kind === 'closed') write(f.expected.nativeF5.closed, { reason: 'synthetic closure after staging' });
                if (kind === 'failed') { f.state.firstFailure = { error: 'synthetic failure after staging' }; write(f.statePath, f.state); }
                if (kind === 'existing-final') fs.writeFileSync(f.input.receipt, 'concurrent original', { flag: 'wx' });
            }
            return kind === 'expired' && calls >= 2 ? NOW + 90000 : NOW;
        };
        assert.throws(() => recordManualInput(f.options, clock));
        for (const file of f.outputs.slice(0, 3)) assert.equal(JSON.parse(fs.readFileSync(file)).evidenceKind, 'human-attestation');
        if (kind === 'existing-final') assert.equal(fs.readFileSync(f.input.receipt, 'utf8'), 'concurrent original');
        else assert.equal(fs.existsSync(f.input.receipt), false);
        const preserved = f.outputs.slice(0, 3).map(file => fs.readFileSync(file));
        assert.throws(() => recordManualInput(f.options, NOW), undefined, 'A partial failed recording cannot be retried as a pass');
        f.outputs.slice(0, 3).forEach((file, index) => assert.deepEqual(fs.readFileSync(file), preserved[index]));
        noResult(f);
    });
});
