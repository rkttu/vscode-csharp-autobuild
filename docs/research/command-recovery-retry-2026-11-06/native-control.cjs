'use strict';
// Real product runtime/recovery and native filesystem; controlled SDK/editor APIs.
const assert = require('node:assert/strict'), crypto = require('node:crypto'), fs = require('node:fs'), path = require('node:path');
const [phase, suppliedRoot] = process.argv.slice(2);
assert(['write', 'read'].includes(phase) && suppliedRoot && path.isAbsolute(suppliedRoot));
const root = fs.realpathSync(suppliedRoot), input = JSON.parse(fs.readFileSync(path.join(root, 'input.json'), 'utf8'));
assert.equal(input.schema, 1); assert.equal(path.resolve(input.workDirectory), root);
const READY = 'terminal-cleanup-v1', STAGING = 'terminal-cleanup-staging-v1', KIND = 'netcoredbg-terminal-output';
const base = path.join(root, 'storage', 'file-based-apps');
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function inside(file) { const r = path.relative(root, path.resolve(file)); return r && r !== '..' && !r.startsWith('..' + path.sep) && !path.isAbsolute(r); }
function save(name, value) {
    const file = path.join(root, name); assert(inside(file)); const fd = fs.openSync(file, 'wx');
    try { fs.writeFileSync(fd, JSON.stringify(value, null, 2) + '\n'); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}
async function until(check, label) {
    const begin = performance.now();
    while (!await check()) { if (performance.now() - begin > 5000) throw new Error('Safety deadline: ' + label); await delay(10); }
}
const traceFd = fs.openSync(path.join(root, `${phase}.trace.jsonl`), 'wx');
function trace(event, detail = {}) {
    fs.writeSync(traceFd, JSON.stringify({ event, pid: process.pid, atUtc: new Date().toISOString(), ...detail }) + '\n'); fs.fsyncSync(traceFd);
}
const role = phase === 'write' ? 'writer' : 'reader', modules = path.join(root, role + '-modules');
const sourceIdentity = {};
for (const [name, expected] of Object.entries(input[role + 'Modules'])) { sourceIdentity[name] = hash(path.join(modules, name)); assert.equal(sourceIdentity[name], expected); }
const { activate, COMMAND } = require(path.join(modules, 'runtime.cjs'));
const calls = { errors: [], logs: [], builds: [], launches: [], stops: [], deletions: [], sdkSelections: 0 };
let started, terminated, active, original, session, locked = true, commandStarted = false, commandLaunched = false, releaseCommandLaunch;
let guards = [];
const commandLaunch = new Promise(resolve => { releaseCommandLaunch = resolve; });
let signalOldDeleteEntered;
const oldDeleteEntered = new Promise(resolve => { signalOldDeleteEntered = resolve; });
const before = phase === 'read' ? JSON.parse(fs.readFileSync(path.join(root, 'publication-proof.json'), 'utf8')) : undefined;
const disposable = () => ({ dispose() {} });
const channel = { append: v => calls.logs.push(String(v)), appendLine: v => calls.logs.push(String(v)), dispose() { calls.outputDisposed = true; trace('output-channel-disposed'); } };
const vscode = {
    ProgressLocation: { Notification: 15 },
    window: { get activeTextEditor() { return active ? { document: active } : undefined; }, createOutputChannel: () => channel,
        showErrorMessage: m => { calls.errors.push(m); return Promise.resolve(undefined); },
        withProgress: async (_s, run) => run({ report() {} }, { isCancellationRequested: false, onCancellationRequested: disposable }) },
    workspace: { isTrusted: true, getWorkspaceFolder: () => undefined },
    commands: { registerCommand: (name, handler) => { assert.equal(name, COMMAND); calls.command = handler; return disposable(); },
        executeCommand: async () => { throw new Error('Project delegation is outside this control'); } },
    debug: {
        onDidStartDebugSession: f => { started = f; return disposable(); }, onDidTerminateDebugSession: f => { terminated = f; return disposable(); },
        registerDebugAdapterTrackerFactory: () => disposable(),
        startDebugging: async (_folder, config) => {
            assert.equal(phase, 'read'); session = { id: 'same-reader-stub-session', type: 'coreclr', name: config.name, configuration: config };
            commandLaunched = true; calls.launches.push({ id: session.id, configuration: config });
            trace('valid-command-stub-session-start', { sessionId: session.id, oldPayloadPresent: fs.existsSync(before.residualLeaf) });
            started?.(session); releaseCommandLaunch(); return true;
        },
        stopDebugging: async s => { assert(s); calls.stops.push(s.id); terminated?.(s); },
    },
};
const context = { globalStorageUri: { fsPath: path.join(root, 'storage') }, subscriptions: [], extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } };
function document(name) {
    const file = path.join(root, 'source', name);
    return { uri: { scheme: 'file', fsPath: file }, isDirty: false, getText: () => fs.readFileSync(file, 'utf8'), save: async () => true };
}
function sentinel(file, kind) {
    assert(inside(file)); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, `${input.nonce}:${kind}\n`, { flag: 'wx' });
    return { file, sha256: hash(file), kind };
}
trace('native-process-start', { phase, executable: process.execPath, architecture: process.arch, nodeVersion: process.version, sourceIdentity });
const dependencies = {
    vscode, env: {}, webSupport: { BUILD_METADATA_ARGS: [], parseBuildMetadata: JSON.parse, prepareWebLaunch: async () => undefined },
    findDotnet: async () => { calls.sdkSelections++; return { executable: path.join(root, 'controlled-sdk/dotnet.exe'), root: path.join(root, 'controlled-sdk') }; },
    classifyFile: async () => ({ kind: 'file', reason: 'controlled standalone source' }),
    runDotnet: async args => {
        if (args[0] === '--version') return { stdout: '10.0.403\n' };
        if (args[0] === '--info') return { stdout: 'Host:\n  Version: 10.0.14\n  Architecture: arm64\n' };
        assert.equal(args[0], 'build'); const directory = args[args.indexOf('--output') + 1]; assert(inside(directory));
        calls.builds.push({ source: args[1], output: directory }); trace('controlled-build', { source: args[1], output: directory });
        for (const name of ['FileApp.dll', 'FileApp.pdb', 'retained.txt']) fs.writeFileSync(path.join(directory, name), `Controlled payload: ${name}\n`, { flag: 'wx' });
        if (phase === 'write') { original = directory; throw new Error('CONTROL terminal build failure'); }
        assert.equal(path.basename(args[1]), 'reader.cs');
        if (input.expectedRecovery) await oldDeleteEntered;
        return { stdout: JSON.stringify({ Properties: { OutputType: 'Exe', TargetFrameworkIdentifier: '.NETCoreApp' }, Items: { FrameworkReference: [] } }) };
    },
    removeOutput: async (directory, settings) => {
        assert(inside(directory)); assert.equal(settings.recursive, true); assert.equal(settings.force, true);
        assert.equal(path.basename(directory), 'output'); assert.equal(path.basename(path.dirname(path.dirname(directory))), READY);
        const entry = path.dirname(directory), receiptFile = path.join(entry, 'record.json'), receipt = JSON.parse(fs.readFileSync(receiptFile, 'utf8'));
        assert.deepEqual(receipt, { version: 1, kind: KIND, entryId: path.basename(entry) });
        const item = { directory, settings, commandStarted, commandLaunched, locked }; calls.deletions.push(item);
        if (phase === 'write') {
            assert.equal(calls.launches.length, 0); assert(!fs.existsSync(original));
            const stagingEntry = path.join(base, STAGING, path.basename(entry)); assert(!fs.existsSync(stagingEntry));
            guards.push(sentinel(path.join(original, 'replacement.txt'), 'replacement-at-original-output'));
            const payload = ['FileApp.dll', 'FileApp.pdb', 'retained.txt'].map(name => ({ file: path.join(directory, name), sha256: hash(path.join(directory, name)) }));
            const proof = { schema: 1, boundary: 'published-ready-before-first-delete', pid: process.pid, expectedExitCode: 73, original,
                readyEntry: entry, stagingEntry, output: directory, receipt, receiptSha256: hash(receiptFile), payload,
                residualLeaf: path.join(directory, 'retained.txt'), guards, sourceIdentity, calls, published: true, recursiveDeleteExecuted: false };
            save('publication-proof.json', proof); trace('published-ready-before-first-delete', proof); trace('intentional-writer-exit', { exitCode: 73 }); process.exit(73);
        }
        if (directory === before.output) {
            item.oldTerminalEntry = true;
            if (locked) { item.failed = 'EBUSY'; trace('reader-startup-delete-busy', item); throw Object.assign(new Error('CONTROL old terminal output temporarily busy'), { code: 'EBUSY' }); }
            assert(commandStarted); assert(!commandLaunched); signalOldDeleteEntered();
            trace('command-recovery-delete-waiting-for-launch', item); await commandLaunch;
            assert(commandLaunched); item.releasedAfterCommandLaunch = true;
        }
        await fs.promises.rm(directory, settings); item.removed = !fs.existsSync(directory); trace('recursive-delete-complete', item);
    },
};
async function main() {
    if (phase === 'write') {
        fs.mkdirSync(path.join(root, 'source'), { recursive: true });
        for (const name of ['terminal.cs', 'reader.cs']) fs.writeFileSync(path.join(root, 'source', name), 'Console.WriteLine("control");\n', { flag: 'wx' });
        guards.push(sentinel(path.join(base, 'aaaaaaaaaaaaaaaaaaaaaaaa/run-UNMARK/unmarked.txt'), 'unmarked-output'));
        guards.push(sentinel(path.join(root, 'external/sentinel.txt'), 'outside-extension-storage'));
        const incomplete = path.join(base, STAGING, crypto.randomUUID()); fs.mkdirSync(incomplete, { recursive: true });
        const record = path.join(incomplete, 'record.json'); fs.writeFileSync(record, JSON.stringify({ version: 1, kind: KIND, entryId: path.basename(incomplete) }) + '\n', { flag: 'wx' });
        guards.push({ file: record, sha256: hash(record), kind: 'incomplete-record-without-output' });
        const api = activate(context, dependencies); await api.recoveryReady; active = document('terminal.cs'); await api.debugActiveFile();
        throw new Error('First terminal deletion did not interrupt this process');
    }
    assert.notEqual(before.pid, process.pid); guards = before.guards;
    const api = activate(context, dependencies), recovery = await api.recoveryReady;
    assert.deepEqual(recovery, { scanned: 1, attempted: 1, removed: 0 });
    assert.equal(calls.sdkSelections, 0); assert.equal(calls.builds.length, 0); assert.equal(calls.launches.length, 0); assert.equal(calls.stops.length, 0);
    const startup = { pid: process.pid, recovery, oldReceiptPresent: fs.existsSync(path.join(before.readyEntry, 'record.json')),
        oldPayloadPresent: fs.existsSync(before.residualLeaf), oldDeletionAttempts: calls.deletions.filter(x => x.oldTerminalEntry).length,
        sdkSelections: calls.sdkSelections, builds: calls.builds.length, launches: calls.launches.length, stops: calls.stops.length };
    assert(startup.oldReceiptPresent && startup.oldPayloadPresent && startup.oldDeletionAttempts === 1);
    save('startup-proof.json', startup); trace('startup-recovery-settled-busy', startup);
    locked = false; commandStarted = true; active = document('reader.cs'); trace('same-reader-valid-command', { writerPid: before.pid });
    const commandResult = await calls.command();
    assert.equal(commandResult, true); assert.equal(calls.launches.length, 1); assert.equal(calls.builds.length, 1); assert(commandLaunched);
    if (input.expectedRecovery) await until(() => !fs.existsSync(before.readyEntry), 'subsequent-command old terminal recovery');
    else await delay(100); // Observation window after the resolved baseline command; no pass was scheduled.
    const oldAttempts = calls.deletions.filter(x => x.oldTerminalEntry);
    const commandObservation = { pid: process.pid, commandResult, oldDeletionAttempts: oldAttempts,
        oldReceiptPresent: fs.existsSync(path.join(before.readyEntry, 'record.json')), oldPayloadPresent: fs.existsSync(before.residualLeaf),
        oldEntryAbsent: !fs.existsSync(before.readyEntry), commandLaunched, freshOutput: session.configuration.__netcoredbgFileAppOutput,
        sdkSelections: calls.sdkSelections, builds: calls.builds, launches: calls.launches };
    assert.notEqual(commandObservation.freshOutput, before.original); assert.notEqual(commandObservation.freshOutput, before.output);
    assert(fs.existsSync(path.join(commandObservation.freshOutput, 'FileApp.dll')));
    if (input.expectedRecovery) { assert.equal(oldAttempts.length, 2); assert(oldAttempts[1].removed && oldAttempts[1].releasedAfterCommandLaunch); assert(!oldAttempts[1].locked && commandObservation.oldEntryAbsent); }
    else { assert.equal(oldAttempts.length, 1); assert(commandObservation.oldReceiptPresent && commandObservation.oldPayloadPresent); }
    save('command-proof.json', commandObservation); trace('same-reader-command-observed', commandObservation);
    await vscode.debug.stopDebugging(session); await until(() => !fs.existsSync(commandObservation.freshOutput), 'stub terminal output cleanup');
    for (const subscription of context.subscriptions) subscription.dispose(); await until(() => calls.outputDisposed, 'disposed output after recovery and own cleanup drain');
    const observations = guards.map(g => ({ ...g, exists: fs.existsSync(g.file), unchanged: fs.existsSync(g.file) && hash(g.file) === g.sha256 }));
    assert(observations.every(g => g.unchanged));
    const proof = { schema: 1, pid: process.pid, writerPid: before.pid, startup, commandObservation, observations,
        oldEntryAbsent: !fs.existsSync(before.readyEntry), oldPayloadPresent: fs.existsSync(before.residualLeaf),
        ownOutputAbsent: !fs.existsSync(commandObservation.freshOutput), outputDisposed: calls.outputDisposed,
        desiredBehaviorObserved: !fs.existsSync(before.readyEntry),
        readyNames: fs.existsSync(path.join(base, READY)) ? fs.readdirSync(path.join(base, READY)).sort() : [],
        stagingNames: fs.readdirSync(path.join(base, STAGING)).sort(), sourceIdentity, calls };
    save('recovery-proof.json', proof); trace('same-reader-control-complete', { oldEntryAbsent: proof.oldEntryAbsent, desiredBehaviorObserved: proof.desiredBehaviorObserved });
    console.log(JSON.stringify({ pid: process.pid, startup: recovery, desiredBehaviorObserved: proof.desiredBehaviorObserved, guardsUnchanged: true }));
}
const safety = setTimeout(() => { console.error('Native control safety deadline'); process.exit(2); }, 15000);
main().then(() => { clearTimeout(safety); fs.closeSync(traceFd); }, error => {
    clearTimeout(safety); console.error(error.stack || String(error)); process.exitCode = 1;
    try { trace('control-failure', { error: error.stack || String(error) }); } finally { fs.closeSync(traceFd); }
});
