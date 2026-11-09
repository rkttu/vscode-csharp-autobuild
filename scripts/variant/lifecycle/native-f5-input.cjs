'use strict';

// This helper records a human's declaration. It never sends input, starts an
// editor, invokes a debug command, or decides whether a scenario passed.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const PRODUCER_VERSION = 'manual-native-receipt-v1';
const SHA256 = /^[a-f0-9]{64}$/;
const SHARED_KEYS = ['nonce', 'sequence', 'launchToken', 'windowTitle', 'action', 'key', 'mechanism'];
const MANUAL_KEYS = ['actor', 'attestedAtUtc', 'evidenceKind', 'oneF5KeyPressed',
    'inputOccurredDuringRequest', 'automationUsed', 'targetCommandApiUsed', 'observationNote'];

function inputPolicy(mode = 'native-injected') {
    assert(['native-injected', 'manual-native'].includes(mode), 'Unknown native F5 input mode');
    return Object.freeze({ mode, mechanism: mode,
        label: mode === 'manual-native' ? 'human-attested manual native F5' : 'native injected F5' });
}

function object(value, label) {
    assert(value && typeof value === 'object' && !Array.isArray(value), `${label} must be an object`);
}

function nonblank(value, label) {
    assert(typeof value === 'string' && value.trim().length > 0, `${label} must be nonblank`);
}

function timestamp(value, label) {
    // An offset is mandatory. Date.parse alone accepts local/ambiguous strings.
    assert(typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?(?:Z|[+-]\d\d:\d\d)$/.test(value),
        `${label} must be an offset-aware ISO timestamp`);
    const parsed = Date.parse(value);
    assert(Number.isFinite(parsed), `${label} must be a valid timestamp`);
    return parsed;
}

function requestTimes(request, mode, now) {
    const policy = inputPolicy(mode);
    object(request, 'Native F5 request');
    assert.equal(request.schema, 1);
    nonblank(request.nonce, 'Request nonce');
    nonblank(request.launchToken, 'Request launch token');
    nonblank(request.windowTitle, 'Request window title');
    assert(request.windowTitle.includes(request.nonce), 'Request title must contain its unique nonce');
    assert(Number.isInteger(request.sequence) && request.sequence >= 1 && request.sequence <= 10, 'Invalid input sequence');
    assert.equal(request.action, 'press-key');
    assert.equal(request.key, 'F5');
    assert.equal(request.mechanism, policy.mechanism, 'Request input mechanism differs from the frozen mode');
    if (mode === 'manual-native' || Object.hasOwn(request, 'inputMode')) assert.equal(request.inputMode, mode);
    assert(Number.isFinite(now), 'Receipt clock must be finite');
    const requested = timestamp(request.requestedAtUtc, 'Request start');
    const expires = timestamp(request.expiresAtUtc, 'Request expiry');
    assert(expires > requested, 'Request expiry must follow its start');
    assert(requested <= now + 1000, 'Request starts in the future');
    assert(now <= expires, 'Native F5 request expired');
    return { requested, expires };
}

function validateReceipt({ mode = 'native-injected', request, receipt, requestSha256, now = Date.now() }) {
    const { requested, expires } = requestTimes(request, mode, now);
    object(receipt, 'Native F5 receipt');
    assert.equal(receipt.schema, 1);
    for (const key of SHARED_KEYS) assert.equal(receipt[key], request[key], `Native F5 receipt ${key}`);
    if (mode === 'manual-native' || Object.hasOwn(receipt, 'inputMode')) assert.equal(receipt.inputMode, mode);
    assert(typeof requestSha256 === 'string' && SHA256.test(requestSha256), 'Invalid request SHA-256');
    assert.equal(receipt.requestSha256, requestSha256, 'Native F5 request SHA-256 differs');
    assert.equal(receipt.editorFocusedBeforeInput, true, 'Native input needs separately observed editor focus');
    nonblank(receipt.observedWindowTitle, 'Observed window title');
    assert(receipt.observedWindowTitle.includes(request.windowTitle), 'Observed title lacks the unique expected window title');
    for (const key of ['observationPath', 'inputRecordPath']) {
        assert(typeof receipt[key] === 'string' && path.isAbsolute(receipt[key]), `${key} must be absolute`);
    }

    let reportedAt;
    if (mode === 'native-injected') {
        assert.equal(receipt.tool, 'sky.press_key');
        for (const key of MANUAL_KEYS) assert(!Object.hasOwn(receipt, key), `Injected receipt cannot contain manual field ${key}`);
        assert(['string', 'number'].includes(typeof receipt.windowId) && String(receipt.windowId).length > 0,
            'Injected receipt requires the original window ID');
        if (typeof receipt.windowId === 'number') assert(Number.isFinite(receipt.windowId));
        reportedAt = timestamp(receipt.inputAtUtc, 'Injected input time');
    } else {
        assert.equal(receipt.tool, 'human-observer');
        for (const key of ['inputAtUtc', 'windowId', 'keyCallReturned', 'arguments', 'keyCallResult']) {
            assert(!Object.hasOwn(receipt, key), `Manual attestation cannot contain injected measurement ${key}`);
        }
        object(receipt.actor, 'Human observer');
        assert.equal(receipt.actor.type, 'human', 'Manual input requires a human actor');
        assert.deepEqual(Object.keys(receipt.actor).sort(), ['id', 'type']);
        nonblank(receipt.actor.id, 'Human observer ID');
        nonblank(receipt.observationNote, 'Human focus observation note');
        assert.equal(receipt.evidenceKind, 'human-attestation');
        assert.equal(receipt.nativeExecutionVerified, false);
        assert.equal(receipt.hardwareKeypressIndependentlyVerified, false);
        assert.equal(receipt.oneF5KeyPressed, true);
        assert.equal(receipt.inputOccurredDuringRequest, true);
        assert.equal(receipt.automationUsed, false);
        assert.equal(receipt.targetCommandApiUsed, false);
        reportedAt = timestamp(receipt.attestedAtUtc, 'Human attestation time');
    }
    assert(reportedAt >= requested, 'Receipt timestamp precedes the request');
    assert(reportedAt <= expires, 'Receipt timestamp is outside the request lease');
    assert(reportedAt <= now + 1000, 'Receipt timestamp is in the future');
    return receipt;
}

function digest(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }
function samePath(left, right) {
    if (typeof left !== 'string' || typeof right !== 'string') return false;
    const a = path.resolve(left), b = path.resolve(right);
    return process.platform === 'win32' ? a.toLowerCase() === b.toLowerCase() : a === b;
}

function safePath(root, filename, { direct = false, exists = true, directory = false } = {}) {
    assert(typeof filename === 'string' && path.isAbsolute(filename), 'Evidence path must be absolute');
    const resolved = path.resolve(filename);
    const relative = path.relative(root, resolved);
    assert(relative && !relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative),
        'Evidence path must stay within the isolated profile');
    if (direct) assert(samePath(path.dirname(resolved), root), 'Evidence file must be a direct child of the profile');
    let current = root;
    const parts = relative.split(path.sep);
    for (let index = 0; index < parts.length; index++) {
        current = path.join(current, parts[index]);
        let stat;
        try { stat = fs.lstatSync(current); }
        catch (error) {
            if (error.code === 'ENOENT' && !exists && index === parts.length - 1) return resolved;
            throw error;
        }
        assert(!stat.isSymbolicLink(), 'Evidence paths cannot contain symbolic links or junctions');
        assert(samePath(fs.realpathSync(current), current), 'Evidence path must retain its real parent');
        if (index < parts.length - 1 || directory) assert(stat.isDirectory(), 'Evidence parent must be a directory');
        else assert(stat.isFile(), 'Evidence input must be a regular file');
    }
    return resolved;
}

function readJson(root, filename, direct = false) {
    const file = safePath(root, filename, { direct });
    const bytes = fs.readFileSync(file);
    const value = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''));
    object(value, file);
    return { file, bytes, sha256: digest(bytes), value };
}

function absent(root, filename) {
    safePath(root, filename, { direct: true, exists: false });
    assert(!fs.existsSync(filename), 'Never overwrite existing manual input evidence');
}

function recordManualInput({ workDir, sequence, observer, observedWindowTitle, note, confirmHumanF5 }, optionalNow) {
    assert.equal(confirmHumanF5, true, 'A human must personally press one F5 before explicitly confirming it');
    nonblank(workDir, 'Work directory');
    nonblank(observer, 'Human observer ID');
    nonblank(observedWindowTitle, 'Actual observed window title');
    nonblank(note, 'Human focus observation note');
    assert(Number.isInteger(sequence) && sequence >= 1 && sequence <= 10, 'Invalid input sequence');
    const clock = optionalNow === undefined ? Date.now : typeof optionalNow === 'function' ? optionalNow : () => optionalNow;
    const root = path.resolve(workDir);
    const rootStat = fs.lstatSync(root);
    assert(rootStat.isDirectory() && !rootStat.isSymbolicLink() && samePath(fs.realpathSync(root), root),
        'Work directory must have a real, non-symlink parent');
    const expectedSnapshot = readJson(root, path.join(root, 'expected.json'), true);
    const expected = expectedSnapshot.value;
    assert.equal(expected.schema, 1);
    assert.equal(expected.scenario, 'native-f5');
    assert.equal(expected.extensionId, 'dotnetdev-kr-custom.csharp-with-netcoredbg');
    assert.equal(expected.nativeF5?.inputMode, 'manual-native', 'Profile was not prepared for manual native input');
    assert.equal(expected.candidate?.localOnly, true);
    assert.equal(expected.candidate.published, false);
    assert.equal(expected.scope?.localOnly, true);
    assert.equal(expected.scope.published, false);
    assert.equal(expected.scope.qualification, false);
    assert(SHA256.test(expected.candidate.sha256) && SHA256.test(expected.candidate.buildId), 'Candidate identity must be pinned');
    assert(typeof expected.candidate.sourceCommit === 'string' && /^[a-f0-9]{40}$/.test(expected.candidate.sourceCommit), 'Candidate source commit must be pinned');
    assert(Number.isInteger(expected.cycles) && expected.cycles >= 2 && expected.cycles <= 10);
    assert.equal(expected.nativeF5.inputs.length, expected.cycles);
    const producerSha256 = expected.harness?.['native-f5-input.cjs'];
    assert(typeof producerSha256 === 'string' && SHA256.test(producerSha256), 'Manual helper SHA-256 must be frozen');
    assert.equal(digest(fs.readFileSync(__filename)), producerSha256, 'Manual helper differs from the frozen input');
    safePath(root, expected.candidate.path, { direct: true });
    const native = expected.nativeF5;
    nonblank(native.nonce, 'Prepared native input nonce');
    nonblank(native.windowTitle, 'Prepared native window title');
    assert(native.windowTitle.includes(native.nonce));
    assert(samePath(native.closed, path.join(root, 'f5-input-closed.json')), 'Unexpected native input closure path');
    native.inputs.forEach((input, index) => {
        assert.equal(input.sequence, index + 1);
        const suffix = String(input.sequence).padStart(2, '0');
        assert(samePath(input.request, path.join(root, `needs-f5-input-${suffix}.json`)), 'Unexpected input request path');
        assert(samePath(input.receipt, path.join(root, `f5-input-action-${suffix}.json`)), 'Unexpected input receipt path');
    });
    const input = native.inputs[sequence - 1];
    assert(input, 'Input sequence is outside this prepared profile');
    const requestSnapshot = readJson(root, input.request, true);
    const request = requestSnapshot.value;
    assert.equal(request.nonce, native.nonce);
    assert.equal(request.sequence, sequence);
    assert.equal(request.windowTitle, native.windowTitle);
    assert(samePath(request.receipt, input.receipt) && samePath(request.closed, native.closed), 'Request evidence paths differ from preparation');
    const source = safePath(root, path.join(root, 'workspace/a.cs'));
    assert(samePath(request.source, source) && samePath(request.activeSource, source), 'Manual request must name the captured isolated C# source');
    assert.equal(request.languageId, 'csharp');
    assert.equal(request.noFolderWindow, true);
    assert.deepEqual(request.workspaceFolders, []);
    assert.equal(request.activeDebugSessionId, null);
    assert.equal(request.isDirty, sequence > 1);
    const suffix = String(sequence).padStart(2, '0');
    const observationPath = path.join(root, `manual-observation-${suffix}.json`);
    const inputRecordPath = path.join(root, `manual-action-${suffix}.json`);
    const stagedPath = input.receipt + '.tmp';

    function openRequest(now) {
        absent(root, native.closed);
        const state = readJson(root, path.join(root, 'progress/state.json')).value;
        assert(samePath(state.root, root), 'Progress belongs to a different profile');
        assert(state.firstFailure == null, 'First failure closes manual input');
        assert(Array.isArray(state.launches) && state.launches.length > 0, 'No observer is armed for this input');
        const launch = state.launches.at(-1);
        assert.equal(launch.label, `F5-${sequence}`);
        assert.equal(launch.nonce, request.launchToken, 'Progress launch token differs from the request');
        assert(samePath(launch.source, source), 'Progress source differs from the request');
        requestTimes(request, 'manual-native', now);
    }

    const attestedAt = clock();
    openRequest(attestedAt);
    for (const file of [input.receipt, stagedPath, observationPath, inputRecordPath]) absent(root, file);
    const producer = { path: __filename, sha256: producerSha256, version: PRODUCER_VERSION };
    const common = Object.fromEntries(SHARED_KEYS.map(key => [key, request[key]]));
    const declaration = { schema: 1, ...common, inputMode: 'manual-native', requestSha256: requestSnapshot.sha256,
        tool: 'human-observer', actor: { type: 'human', id: observer.trim() },
        attestedAtUtc: new Date(attestedAt).toISOString(), evidenceKind: 'human-attestation',
        nativeExecutionVerified: false, hardwareKeypressIndependentlyVerified: false,
        observedWindowTitle, editorFocusedBeforeInput: true, observationNote: note.trim(),
        oneF5KeyPressed: true, inputOccurredDuringRequest: true, automationUsed: false, targetCommandApiUsed: false,
        producer, attestationMeaning: 'The human declares one native F5 with C# editor focus during this request. This is not independent hardware or native execution proof.' };
    const receipt = { ...declaration, observationPath, inputRecordPath };
    validateReceipt({ mode: 'manual-native', request, receipt, requestSha256: requestSnapshot.sha256, now: attestedAt });
    const observation = { ...declaration, source, activeSource: request.activeSource, languageId: request.languageId,
        candidate: { sha256: expected.candidate.sha256, buildId: expected.candidate.buildId, sourceCommit: expected.candidate.sourceCommit },
        editor: expected.editor, sdk: expected.sdk };
    const action = { ...declaration, observationPath };
    const records = [[observationPath, observation], [inputRecordPath, action], [stagedPath, receipt]]
        .map(([file, value]) => [file, Buffer.from(JSON.stringify(value, null, 2) + '\n')]);
    // Keep every original, including the staged receipt, if publication fails.
    // linkSync publishes complete JSON atomically and refuses an existing name.
    for (const [file, bytes] of records) fs.writeFileSync(file, bytes, { flag: 'wx' });
    const publicationTime = clock();
    assert(readJson(root, expectedSnapshot.file, true).bytes.equals(expectedSnapshot.bytes), 'Preparation changed before receipt publication');
    assert.equal(digest(fs.readFileSync(__filename)), producerSha256, 'Manual helper changed before publication');
    assert(readJson(root, requestSnapshot.file, true).bytes.equals(requestSnapshot.bytes), 'Request changed before receipt publication');
    for (const [file, bytes] of records) assert(readJson(root, file, true).bytes.equals(bytes), 'Original manual evidence changed before publication');
    openRequest(publicationTime);
    validateReceipt({ mode: 'manual-native', request, receipt, requestSha256: requestSnapshot.sha256, now: publicationTime });
    absent(root, input.receipt);
    fs.linkSync(stagedPath, input.receipt);
    return { receiptPublished: true, receipt: input.receipt, nativeExecutionVerified: false };
}

module.exports = { inputPolicy, validateReceipt, recordManualInput };

if (require.main === module) {
    try {
        const args = process.argv.slice(2);
        if (args.length === 1 && args[0] === '--help') {
            process.stdout.write('After personally observing the token-bearing C# editor and pressing exactly one native F5, record your declaration:\n' +
                'node native-f5-input.cjs --work-dir PATH --sequence N --observer ID --observed-window-title ACTUAL_TITLE --note FOCUS_OBSERVATION --confirm-human-f5\n' +
                'This helper sends no input and provides no independent native execution proof. It cannot retry or overwrite partial evidence.\n');
        } else {
            const names = { '--work-dir': 'workDir', '--sequence': 'sequence', '--observer': 'observer',
                '--observed-window-title': 'observedWindowTitle', '--note': 'note', '--confirm-human-f5': 'confirmHumanF5' };
            const options = {};
            for (let index = 0; index < args.length; index++) {
                const key = names[args[index]];
                assert(key, 'Unknown manual input argument');
                assert(!Object.hasOwn(options, key), 'Duplicate manual input argument');
                if (key === 'confirmHumanF5') options[key] = true;
                else {
                    assert(index + 1 < args.length && !args[index + 1].startsWith('--'), 'Manual input argument needs a value');
                    options[key] = args[++index];
                }
            }
            assert(typeof options.sequence === 'string' && /^(?:[1-9]|10)$/.test(options.sequence), 'Use an integer input sequence from 1 to 10');
            options.sequence = Number(options.sequence);
            process.stdout.write(JSON.stringify(recordManualInput(options)) + '\n');
        }
    } catch (error) {
        process.stderr.write('Manual F5 receipt refused: ' + error.message + '\n');
        process.exitCode = 1;
    }
}
