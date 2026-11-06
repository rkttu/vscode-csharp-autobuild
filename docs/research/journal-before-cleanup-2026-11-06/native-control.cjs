'use strict';

// Actual product modules/filesystem; controlled SDK, VS Code API and first rm.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const [phase, suppliedRoot] = process.argv.slice(2);
assert(['interrupt', 'recover'].includes(phase));
assert(suppliedRoot && path.isAbsolute(suppliedRoot));
const root = fs.realpathSync(suppliedRoot);
const input = JSON.parse(fs.readFileSync(path.join(root, 'input.json'), 'utf8'));
assert.equal(input.schema, 1);
assert.equal(path.resolve(input.workDirectory), root);
const base = path.join(root, 'storage', 'file-based-apps');
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function inside(file) {
    const relative = path.relative(root, path.resolve(file));
    return relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}
function save(name, value) {
    const file = path.join(root, name);
    assert(inside(file));
    const fd = fs.openSync(file, 'wx');
    try { fs.writeFileSync(fd, JSON.stringify(value, null, 2) + '\n'); fs.fsyncSync(fd); }
    finally { fs.closeSync(fd); }
}
const traceFd = fs.openSync(path.join(root, `${phase}.trace.jsonl`), 'wx');
function trace(event, detail = {}) {
    fs.writeSync(traceFd, JSON.stringify({ event, pid: process.pid, atUtc: new Date().toISOString(), ...detail }) + '\n');
    fs.fsyncSync(traceFd);
}
const modules = path.join(root, 'modules');
for (const [name, expected] of Object.entries(input.moduleSha256)) assert.equal(hash(path.join(modules, name)), expected);
const sourceIdentity = Object.fromEntries(Object.keys(input.moduleSha256).map(name => [name, hash(path.join(modules, name))]));
const { activate, COMMAND } = require(path.join(modules, 'runtime.cjs'));
const calls = { errors: [], logs: [], builds: [], launches: [], stops: [], removals: [], sdkSelections: 0 };
let started, terminated, active, original;
let guards = [];
const disposable = () => ({ dispose() {} });
const channel = { append: value => calls.logs.push(String(value)), appendLine: value => calls.logs.push(String(value)), dispose() { calls.outputDisposed = true; } };
const vscode = {
    ProgressLocation: { Notification: 15 },
    window: {
        get activeTextEditor() { return active ? { document: active } : undefined; },
        createOutputChannel: () => channel,
        showErrorMessage: message => { calls.errors.push(message); return Promise.resolve(undefined); },
        withProgress: async (_settings, run) => run({ report() {} }, { isCancellationRequested: false, onCancellationRequested: disposable }),
    },
    workspace: { isTrusted: true, getWorkspaceFolder: () => undefined },
    commands: {
        registerCommand: (command, handler) => { assert.equal(command, COMMAND); calls.command = handler; return disposable(); },
        executeCommand: async () => { throw new Error('Project delegation is outside this control'); },
    },
    debug: {
        onDidStartDebugSession: listener => { started = listener; return disposable(); },
        onDidTerminateDebugSession: listener => { terminated = listener; return disposable(); },
        registerDebugAdapterTrackerFactory: () => disposable(),
        startDebugging: async (_folder, config) => {
            const session = { id: 'controlled-live-session', type: 'coreclr', name: config.name, configuration: config };
            calls.launches.push({ id: session.id, configuration: config }); started?.(session); return true;
        },
        stopDebugging: async session => { assert(session); calls.stops.push(session.id); terminated?.(session); },
    },
};
const context = { globalStorageUri: { fsPath: path.join(root, 'storage') }, subscriptions: [], extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } };
function document(name) {
    const file = path.join(root, 'source', name);
    return { uri: { scheme: 'file', fsPath: file }, isDirty: false, getText: () => fs.readFileSync(file, 'utf8'), save: async () => true };
}
function sentinel(file, kind) {
    assert(inside(file)); fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, `${input.nonce}:${kind}\n`, { flag: 'wx' }); return { file, sha256: hash(file), kind };
}
function entries() {
    const queue = path.join(base, 'terminal-cleanup-v1');
    return !fs.existsSync(queue) ? [] : fs.readdirSync(queue).map(name => {
        const entry = path.join(queue, name);
        return { entry, output: path.join(entry, 'output'), record: JSON.parse(fs.readFileSync(path.join(entry, 'record.json'), 'utf8')) };
    });
}
trace('cold-process-start', { phase, executable: process.execPath, architecture: process.arch, nodeVersion: process.version, sourceIdentity });
const dependencies = {
    vscode, env: {},
    webSupport: { BUILD_METADATA_ARGS: [], parseBuildMetadata: JSON.parse, prepareWebLaunch: async () => undefined },
    findDotnet: async () => { calls.sdkSelections++; return { executable: path.join(root, 'controlled-sdk', 'dotnet.exe'), root: path.join(root, 'controlled-sdk') }; },
    classifyFile: async () => ({ kind: 'file', reason: 'controlled standalone source' }),
    runDotnet: async args => {
        if (args[0] === '--version') return { stdout: '10.0.403\n' };
        if (args[0] === '--info') return { stdout: 'Host:\n  Version: 10.0.14\n  Architecture: arm64\n' };
        assert.equal(args[0], 'build');
        const directory = args[args.indexOf('--output') + 1]; assert(inside(directory));
        calls.builds.push({ source: args[1], output: directory });
        for (const name of ['FileApp.dll', 'FileApp.pdb', 'partial-delete.txt', 'retained.txt']) fs.writeFileSync(path.join(directory, name), `Controlled payload: ${name}\n`, { flag: 'wx' });
        if (path.basename(args[1]) === 'interrupted.cs') { original = directory; throw new Error('CONTROL terminal build failure'); }
        assert.equal(path.basename(args[1]), 'live.cs');
        return { stdout: JSON.stringify({ Properties: { OutputType: 'Exe', TargetFrameworkIdentifier: '.NETCoreApp' }, Items: { FrameworkReference: [] } }) };
    },
    removeOutput: async (directory, settings) => {
        assert(inside(directory)); assert.equal(settings.recursive, true); assert.equal(settings.force, true);
        calls.removals.push({ directory, settings });
        if (phase === 'recover') {
            assert.equal(path.basename(directory), 'output');
            assert.equal(path.basename(path.dirname(path.dirname(directory))), 'terminal-cleanup-v1');
            const receipt = path.join(path.dirname(directory), 'record.json'); assert(fs.existsSync(receipt));
            trace('cold-recovery-recursive-delete', { directory, receipt }); await fs.promises.rm(directory, settings); return;
        }
        assert.equal(calls.removals.length, 1); assert(calls.errors.some(message => message.includes('CONTROL terminal build failure')));
        assert.equal(calls.launches.length, 1, 'Only the controlled live source may launch');
        const ready = entries(); const selected = ready.find(entry => entry.output === directory);
        if (selected) {
            assert.equal(selected.record.version, 1); assert.equal(selected.record.kind, 'netcoredbg-terminal-output');
            assert.equal(path.basename(selected.entry), selected.record.entryId); assert(!fs.existsSync(original));
            guards.push(sentinel(path.join(original, 'replacement.txt'), 'replacement-at-original-output'));
        }
        trace('first-recursive-delete-boundary', { directory, original, ready });
        const partial = path.join(directory, 'partial-delete.txt'); assert(fs.existsSync(partial)); fs.unlinkSync(partial);
        assert(fs.existsSync(path.join(directory, 'retained.txt')));
        save('interruption-proof.json', { schema: 1, pid: process.pid, expectedExitCode: 73, original,
            firstRecursiveDeleteTarget: directory, publishedBeforeFirstDelete: Boolean(selected), ready,
            partialLeafRemoved: !fs.existsSync(partial), residualLeaf: path.join(directory, 'retained.txt'), guards, sourceIdentity, calls });
        trace('abrupt-exit-before-removal-promise-settles', { exitCode: 73, publishedBeforeFirstDelete: Boolean(selected) });
        process.exit(73);
    },
};
async function main() {
    if (phase === 'interrupt') {
        fs.mkdirSync(path.join(root, 'source'), { recursive: true });
        for (const name of ['live.cs', 'interrupted.cs']) fs.writeFileSync(path.join(root, 'source', name), 'Console.WriteLine("control");\n', { flag: 'wx' });
        guards.push(sentinel(path.join(base, 'aaaaaaaaaaaaaaaaaaaaaaaa', 'run-UNMARK', 'unmarked.txt'), 'unmarked-output'));
        guards.push(sentinel(path.join(root, 'external', 'sentinel.txt'), 'outside-extension-storage'));
        const staging = path.join(base, 'terminal-cleanup-staging-v1', crypto.randomUUID());
        guards.push(sentinel(path.join(staging, 'output', 'staged.txt'), 'unpublished-staging-output'));
        fs.writeFileSync(path.join(staging, 'record.json'), JSON.stringify({ version: 1, kind: 'netcoredbg-terminal-output', entryId: path.basename(staging) }), { flag: 'wx' });
        const api = activate(context, dependencies); await api.recoveryReady;
        active = document('live.cs'); assert.equal(await api.debugActiveFile(), true);
        const live = calls.launches[0].configuration.__netcoredbgFileAppOutput;
        guards.push({ file: path.join(live, 'FileApp.dll'), sha256: hash(path.join(live, 'FileApp.dll')), kind: 'active-stub-session-output' });
        active = document('interrupted.cs'); await api.debugActiveFile();
        throw new Error('First recursive cleanup did not interrupt this process');
    }
    const before = JSON.parse(fs.readFileSync(path.join(root, 'interruption-proof.json'), 'utf8')); assert.notEqual(before.pid, process.pid);
    guards = before.guards;
    const api = activate(context, dependencies); const recovery = await api.recoveryReady;
    assert.equal(calls.sdkSelections, 0); assert.equal(calls.launches.length, 0);
    const observations = guards.map(guard => ({ ...guard, exists: fs.existsSync(guard.file), unchanged: fs.existsSync(guard.file) && hash(guard.file) === guard.sha256 }));
    assert(observations.every(guard => guard.unchanged));
    const residualExists = fs.existsSync(before.residualLeaf); const ready = entries();
    for (const subscription of context.subscriptions) subscription.dispose();
    const proof = { schema: 1, pid: process.pid, interruptedPid: before.pid, recovery, observations, residualExists, ready,
        removals: calls.removals, sourceIdentity, calls, terminalJournalRecovered: before.publishedBeforeFirstDelete && !residualExists && ready.length === 0 };
    save('recovery-proof.json', proof); trace('cold-recovery-complete', { recovery, residualExists, terminalJournalRecovered: proof.terminalJournalRecovered });
    console.log(JSON.stringify({ pid: process.pid, recovery, residualExists, guardsUnchanged: true }));
}
const safety = setTimeout(() => { console.error('Native control safety deadline'); process.exit(2); }, 15000);
main().then(() => { clearTimeout(safety); fs.closeSync(traceFd); }, error => {
    clearTimeout(safety); console.error(error.stack || String(error)); process.exitCode = 1;
    try { trace('control-failure', { error: error.stack || String(error) }); } finally { fs.closeSync(traceFd); }
});
