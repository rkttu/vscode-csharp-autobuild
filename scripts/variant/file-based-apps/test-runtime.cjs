'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { getEventListeners } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { activate, COMMAND, requireFileAppSdk, sdkArchitecture, runProcess, createOutputDirectory } = require('./runtime.cjs');
const { classifyFile: classifyWithMsbuild } = require('./classify.cjs');
const vm = require('node:vm');

function fixture(t, options = {}) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'netcoredbg-fba-runtime-'));
    t.after(() => {
        assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
        assert(path.basename(root).startsWith('netcoredbg-fba-runtime-'));
        fs.rmSync(root, { recursive: true, force: true });
    });
    const sourceDirectory = path.join(root, 'source with spaces');
    fs.mkdirSync(sourceDirectory);
    const source = path.join(sourceDirectory, 'tool.cs');
    fs.writeFileSync(source, 'int answer = 40;\nanswer += 2;\nConsole.WriteLine(answer);\n');
    const calls = { commands: [], launches: [], stops: [], processes: [], classifications: [], errors: [], saves: 0, logs: [],
        disposals: { command: 0, started: 0, terminated: 0, tracker: 0, output: 0 } };
    function disposable(kind, action) {
        let disposed = false;
        return { dispose() {
            if (disposed) return;
            disposed = true;
            calls.disposals[kind]++;
            action?.();
        } };
    }
    const output = {
        append(value) { assert.equal(calls.disposals.output, 0, 'Disposed output must not receive stream data'); calls.logs.push(value); },
        appendLine(value) {
            assert.equal(calls.disposals.output, 0, 'Disposed output must not receive diagnostics');
            calls.logs.push(value);
            options.appendLine?.(value);
        },
        ...disposable('output', () => options.disposeOutput?.()),
    };
    let termination;
    let started;
    let cancellation;
    let trackerFactory;
    let nextConfiguration = 0;
    const trackers = new Map();
    const sessions = new Map();
    let nextSession = 0;
    const sessionFor = (config, overrides = {}) => ({
        id: `session-${++nextSession}`, type: config.type, name: config.name, configuration: config, ...overrides,
    });
    const startSession = (config, overrides) => {
        const session = sessionFor(config, overrides);
        sessions.set(config, session);
        if (session.type === 'coreclr' && trackerFactory) trackers.set(session.id, trackerFactory.createDebugAdapterTracker(session));
        started?.(session);
        return session;
    };
    const document = {
        uri: { scheme: 'file', fsPath: source },
        isDirty: Boolean(options.dirty),
        getText: () => fs.readFileSync(source, 'utf8'),
        save: async () => { calls.saves++; return options.save ? options.save() : options.saveResult !== false; },
    };
    const vscode = {
        ProgressLocation: { Notification: 15 },
        window: {
            activeTextEditor: { document },
            createOutputChannel: () => output,
            showErrorMessage: message => {
                calls.errors.push(message);
                return options.showErrorMessage ? options.showErrorMessage(message) : Promise.resolve(undefined);
            },
            withProgress: async (_settings, callback) => callback({ report: value => options.reportProgress?.(value) }, {
                isCancellationRequested: Boolean(options.cancellationRequested),
                onCancellationRequested: callback => { cancellation = callback; return { dispose() { cancellation = undefined; } }; },
            }),
        },
        workspace: { isTrusted: options.trusted !== false, getWorkspaceFolder: () => options.noWorkspace ? undefined : { name: 'workspace' } },
        commands: {
            registerCommand: (command, callback) => { assert.equal(command, COMMAND); calls.handler = callback;
                return disposable('command', () => { calls.handler = undefined; }); },
            executeCommand: async command => { calls.commands.push(command); return true; },
        },
        debug: {
            registerDebugAdapterTrackerFactory: (type, factory) => {
                assert.equal(type, 'coreclr'); trackerFactory = factory;
                return disposable('tracker', () => { trackerFactory = undefined; });
            },
            onDidStartDebugSession: callback => { started = callback; return disposable('started', () => { started = undefined; }); },
            onDidTerminateDebugSession: callback => { termination = callback; return disposable('terminated', () => { termination = undefined; }); },
            startDebugging: async (folder, config) => {
                calls.launches.push({ folder, config });
                if (options.startDebugging) return options.startDebugging(folder, config);
                if (options.startResult === false) return false;
                startSession(config);
                return true;
            },
            stopDebugging: async session => {
                assert(session, 'Stopping all editor sessions is forbidden');
                calls.stops.push(session);
                if (options.stopDebugging) return options.stopDebugging(session);
                termination?.(session);
            },
        },
    };
    if (options.noTrackerAPI) delete vscode.debug.registerDebugAdapterTrackerFactory;
    const context = { globalStorageUri: { fsPath: options.storage || path.join(root, 'storage') }, subscriptions: [], extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } };
    const dependencies = {
        vscode,
        env: {},
        ...(options.webSupport ? { webSupport: options.webSupport } : {}),
        ...(options.removeOutput ? { removeOutput: options.removeOutput } : {}),
        ...(options.now ? { now: options.now } : {}),
        ...(options.preparationTimeoutMs !== undefined ? { preparationTimeoutMs: options.preparationTimeoutMs } : {}),
        ...(options.scheduleTimeout ? { scheduleTimeout: options.scheduleTimeout, clearTimeout: options.clearTimeout } : {}),
        findDotnet: options.findDotnet || (async () => ({ executable: path.join(root, 'dotnet', 'dotnet.exe'), root: path.join(root, 'dotnet') })),
        classifyFile: async input => {
            calls.classifications.push(input);
            if (options.classify) return options.classify(input, calls, vscode);
            return { kind: options.kind || 'file', reason: 'fixture' };
        },
        runDotnet: async (args, settings) => {
            calls.processes.push({ args, settings });
            if (options.runDotnet) return options.runDotnet(args, settings, calls);
            if (args[0] === '--version') return { stdout: options.sdk || '10.0.402\n' };
            if (args[0] === '--info') return { stdout: `Host:\n  Version: 10.0.13\n  Architecture: ${options.arch || 'arm64'}\n` };
            if (args[0] === 'build') {
                if (options.buildError) throw options.buildError;
                const outputDirectory = args[args.indexOf('--output') + 1];
                fs.writeFileSync(path.join(outputDirectory, 'FileApp.dll'), 'fixture DLL');
                fs.writeFileSync(path.join(outputDirectory, 'FileApp.pdb'), 'fixture PDB');
                return { stdout: JSON.stringify({
                    Properties: {
                        UsingMicrosoftNETSdkWeb: options.web ? 'true' : '',
                        OutputType: 'Exe', TargetFrameworkIdentifier: '.NETCoreApp',
                    },
                    Items: { FrameworkReference: options.web ? [{ Identity: 'Microsoft.AspNetCore.App' }] : [] },
                }) };
            }
            throw new Error(`Unexpected command: ${args.join(' ')}`);
        },
    };
    const api = (options.activate || activate)(context, dependencies);
    return { root, source, document, vscode, context, dependencies, calls, api, output,
        startSession, emitStart: session => started?.(session),
        terminate: config => termination?.(sessions.get(config) || sessionFor(config)), cancel: () => cancellation?.(),
        tracker: session => trackers.get(session.id),
        createTracker: session => trackerFactory?.createDebugAdapterTracker(session),
        session: config => sessions.get(config),
        configuration: (session, success = true) => {
            const tracker = trackers.get(session.id);
            const seq = ++nextConfiguration;
            tracker?.onWillReceiveMessage?.({ type: 'request', command: 'configurationDone', seq });
            tracker?.onDidSendMessage?.({ type: 'response', command: 'configurationDone', request_seq: seq, success });
        },
        dispose: () => { for (const subscription of context.subscriptions) subscription.dispose(); } };
}

async function waitFor(predicate, message) {
    const deadline = Date.now() + 1000;
    while (!predicate() && Date.now() < deadline) await new Promise(resolve => setImmediate(resolve));
    assert(predicate(), message);
}

async function waitForFailedCleanup(f, count = 1) {
    await waitFor(() => f.calls.logs.filter(line => line.includes('Could not clean file-app output')).length >= count,
        'The terminal cleanup failure must be diagnosed before retrying it');
    // No I/O follows this diagnostic. Drain cleanup's final Promise bookkeeping
    // before a test asks the next command to select a retained failure.
    await new Promise(resolve => setImmediate(resolve));
}

async function waitForRemovedOutput(f, directory) {
    const base = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps');
    // Follow publication order after observing source absence so a staging-to-ready
    // move cannot fall between the two queue observations and appear complete.
    await waitFor(() => !fs.existsSync(directory) && ['terminal-cleanup-staging-v1', 'terminal-cleanup-v1'].every(name => {
        const queue = path.join(base, name);
        return !fs.existsSync(queue) || fs.readdirSync(queue).length === 0;
    }),
        'The terminal output and its completed receipt must be removed');
}

function terminalOutputs(f) {
    const queue = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps', 'terminal-cleanup-v1');
    if (!fs.existsSync(queue)) return [];
    return fs.readdirSync(queue, { withFileTypes: true }).filter(entry => entry.isDirectory()).map(entry => path.join(queue, entry.name, 'output'));
}

function activationWithOutputIO(overrides) {
    const runtimeModule = { exports: {} };
    vm.runInNewContext(fs.readFileSync(require.resolve('./runtime.cjs'), 'utf8'), {
        module: runtimeModule, process: { platform: 'win32', env: process.env }, AbortController, setTimeout, clearTimeout,
        require: name => name === 'node:fs' ? { ...fs, promises: { ...fs.promises, ...overrides } } : require(name),
    });
    return runtimeModule.exports.activate;
}

// Run the real activation/native executor branch in an isolated strict host.
// The SDK, debug sessions and DLL/PDB are stand-ins; the OS children and their
// stdout/stderr/exit/close events are real. Every CLI exits independently of its
// host, including when the baseline host dies from the unguarded data callback.
async function streamOutputProbe() {
    const assert = require('node:assert/strict');
    const cp = require('node:child_process');
    const fs = require('node:fs');
    const path = require('node:path');
    const vm = require('node:vm');
    const [runtimeFile, root, mode] = process.argv.slice(1);
    const diagnostic = 'Could not write .NET process output; process completion is still being observed.';
    const source = path.join(root, 'a.cs'), otherSource = path.join(root, 'b.cs');
    fs.writeFileSync(source, 'Console.WriteLine("original");\n');
    fs.writeFileSync(otherSource, 'Console.WriteLine("other");\n');
    const external = path.join(root, 'external-preserved.dll');
    fs.writeFileSync(external, 'unrelated marker');
    const rows = [], appends = [], logs = [], errors = [], stops = [], cleanup = [], metadata = [];
    let current, retry = false, cancelled = false, outputDisposed = false, postDisposeWrites = 0;
    let started, terminated, cancel, api, disposal, disposalSettled = false, commandSettled = false, snapshot;
    function ownedCli() {
        const fs = require('node:fs'), path = require('node:path');
        const args = process.argv.slice(1), command = args[0];
        const failing = process.env.STREAM_PROBE_BUILD_FAILURE === '1';
        process.stdout.on('error', () => {});
        process.stderr.on('error', () => {});
        // This bounded stand-in cannot remain orphaned after its host crashes.
        setTimeout(() => process.exit(failing ? 23 : 0), 1000);
        if (command === '--version') return process.stdout.write('10.0.403\n', () => process.exit(0));
        if (command === '--info') return process.stdout.write('Host:\n  Architecture: arm64\n', () => process.exit(0));
        if (command !== 'build') return process.exit(24);
        const directory = args[args.indexOf('--output') + 1];
        fs.writeFileSync(path.join(directory, 'FileApp.dll'), JSON.stringify({ source: args[1], originalOutput: directory }));
        fs.writeFileSync(path.join(directory, 'FileApp.pdb'), 'stand-in PDB');
        process.stdout.write('STREAM_STDOUT_1\n');
        setTimeout(() => process.stderr.write('STREAM_STDERR_1\n'), 15);
        setTimeout(() => process.stdout.write('STREAM_STDOUT_2\n'), 30);
        setTimeout(() => process.stderr.write('STREAM_STDERR_2\n'), 45);
        setTimeout(() => {
            const evaluated = JSON.stringify({ Properties: { UsingMicrosoftNETSdkWeb: '', OutputType: 'Exe',
                TargetFrameworkIdentifier: '.NETCoreApp' }, Items: { FrameworkReference: [] } });
            Promise.all([
                new Promise(resolve => process.stdout.write(evaluated + '\n', resolve)),
                new Promise(resolve => process.stderr.write(failing ? 'CLI_BUILD_FAILURE_23\n' : '', resolve)),
            ]).then(() => process.exit(failing ? 23 : 0));
        }, 60);
    }
    const cliCode = '(' + ownedCli.toString() + ')()';
    const executor = { ...cp, execFile(_executable, args, settings, callback) {
        const row = { kind: args[0], source: args[0] === 'build' ? args[1] : undefined,
            output: args[0] === 'build' ? args[args.indexOf('--output') + 1] : undefined,
            closed: false, retry };
        const child = cp.execFile(process.execPath, ['-e', cliCode, '--', ...args], {
            ...settings, env: { ...settings.env, STREAM_PROBE_BUILD_FAILURE:
                row.source === source && mode === 'failure' && !retry ? '1' : '0' },
        }, (error, stdout, stderr) => {
            row.callback = true; row.stdout = stdout; row.stderr = stderr; row.error = error;
            callback(error, stdout, stderr);
        });
        row.pid = child.pid; rows.push(row); current = row;
        // The baseline may terminate on its first stream callback. Publish the
        // exact PID synchronously before that callback can prevent pipe flushing.
        fs.writeSync(1, JSON.stringify({ event: 'owned-child', pid: row.pid, kind: row.kind }) + '\n');
        child.once('close', () => { row.closed = true; });
        return child;
    } };
    const runtimeModule = { exports: {} };
    const localRequire = name => name === 'node:child_process' ? executor :
        name.startsWith('.') ? require(path.resolve(path.dirname(runtimeFile), name)) : require(name);
    vm.runInNewContext(fs.readFileSync(runtimeFile, 'utf8'), {
        module: runtimeModule, require: localRequire, process, AbortController, setTimeout, clearTimeout,
    }, { filename: runtimeFile });
    const sessions = new Map();
    const document = filename => ({ uri: { scheme: 'file', fsPath: filename }, isDirty: false,
        getText: () => fs.readFileSync(filename, 'utf8'), save: async () => true });
    const active = document(source);
    const output = {
        append(value) {
            if (outputDisposed) postDisposeWrites++;
            appends.push({ source: current?.source, kind: current?.kind, value });
            if (current?.source !== source || current.kind !== 'build') return;
            if (!retry && !cancelled && ['cancel', 'dispose'].includes(mode)) {
                cancelled = true;
                queueMicrotask(() => {
                    if (mode === 'cancel') cancel();
                    else { disposal = api.dispose(); disposal.then(() => { disposalSettled = true; }); }
                    snapshot = { closed: current.closed, commandSettled, disposalSettled,
                        outputExists: fs.existsSync(current.output), outputDisposed };
                });
            }
            if (mode === 'failure') throw { get message() { throw new Error('Hostile message getter'); },
                toString() { throw new Error('Hostile error conversion'); } };
            throw new Error('STREAM_DIAGNOSTIC_SINK_THROW');
        },
        appendLine(value) {
            if (outputDisposed) postDisposeWrites++;
            logs.push(value);
            if (value === diagnostic && mode === 'dispose') throw new Error('Secondary diagnostic sink failed');
        },
        dispose() { outputDisposed = true; },
    };
    const vscode = { ProgressLocation: { Notification: 15 },
        window: { activeTextEditor: { document: document(otherSource) }, createOutputChannel: () => output,
            showErrorMessage(message) { errors.push(message); return Promise.resolve(undefined); },
            withProgress: (_settings, task) => task({ report() {} }, { isCancellationRequested: false,
                onCancellationRequested(callback) { cancel = callback; return { dispose() { cancel = undefined; } }; } }),
        },
        workspace: { isTrusted: true, getWorkspaceFolder: () => undefined },
        commands: { registerCommand: () => ({ dispose() {} }) },
        debug: {
            onDidStartDebugSession(callback) { started = callback; return { dispose() { started = undefined; } }; },
            onDidTerminateDebugSession(callback) { terminated = callback; return { dispose() { terminated = undefined; } }; },
            async startDebugging(_folder, config) {
                const session = { id: 'owned-' + sessions.size, type: config.type, name: config.name, configuration: config };
                sessions.set(config.__netcoredbgFileAppOutput, session); started(session); return true;
            },
            async stopDebugging(session) { stops.push(session.id); terminated(session); },
        },
    };
    const realWeb = require(path.join(path.dirname(runtimeFile), 'web.cjs'));
    api = runtimeModule.exports.activate({ globalStorageUri: { fsPath: path.join(root, 'storage') }, subscriptions: [],
        extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } }, {
        vscode, env: {}, findDotnet: async () => ({ executable: process.execPath, root: path.dirname(process.execPath) }),
        classifyFile: async () => ({ kind: 'file', reason: 'stand-in classification' }),
        webSupport: { ...realWeb, parseBuildMetadata(value) { metadata.push(value); return realWeb.parseBuildMetadata(value); } },
        removeOutput: async (directory, options) => {
            const marker = path.join(directory, 'FileApp.dll');
            const identity = fs.existsSync(marker) ? JSON.parse(fs.readFileSync(marker, 'utf8')) : undefined;
            const build = rows.find(row => row.kind === 'build' && row.source === identity?.source && row.output === identity?.originalOutput);
            cleanup.push({ owner: identity?.source, originalOutput: identity?.originalOutput,
                closed: build?.closed, callback: build?.callback });
            await fs.promises.rm(directory, options);
        },
    });
    await api.recoveryReady;
    assert.equal(await api.debugActiveFile(), true);
    const other = [...sessions.values()][0];
    started({ id: 'external-session', type: 'coreclr', name: 'external',
        configuration: { type: 'coreclr', program: external, __netcoredbgFileAppOutput: root } });
    vscode.window.activeTextEditor = { document: active };
    const requests = Array.from({ length: 3 }, () => api.debugActiveFile());
    const values = await Promise.all(requests).then(value => { commandSettled = true; return value; });
    const expected = mode === 'success';
    assert.deepEqual(values, [expected, expected, expected]);
    const first = rows.find(row => row.kind === 'build' && row.source === source);
    assert.equal(first.closed, true, 'The original command must observe actual child close');
    assert.equal(first.callback, true);
    const firstAppends = appends.filter(row => row.source === source && row.kind === 'build').map(row => row.value).join('');
    assert(firstAppends.includes('STREAM_STDOUT_1'));
    assert.equal(logs.filter(line => line === diagnostic).length, 1, 'One failed sink diagnostic per process');
    if (mode === 'success' || mode === 'failure') {
        for (const text of ['STREAM_STDOUT_1', 'STREAM_STDOUT_2', 'STREAM_STDERR_1', 'STREAM_STDERR_2']) {
            assert(firstAppends.includes(text), 'Later chunks still attempt the diagnostic sink: ' + text);
        }
        assert(first.stdout.includes('STREAM_STDOUT_1') && first.stdout.includes('STREAM_STDOUT_2'));
        assert(first.stderr.includes('STREAM_STDERR_1') && first.stderr.includes('STREAM_STDERR_2'));
    }
    if (mode === 'failure') {
        assert.equal(first.error.code, 23);
        assert.equal(first.error.stdout, first.stdout);
        assert.equal(first.error.stderr, first.stderr);
        assert.equal(errors.length, 1);
        assert(errors[0].includes('CLI_BUILD_FAILURE_23'));
    } else assert.equal(errors.length, 0, 'Sink failure must not become a launch error or cancellation notification');
    if (mode === 'cancel' || mode === 'dispose') {
        assert.deepEqual(snapshot, { closed: false, commandSettled: false, disposalSettled: false,
            outputExists: true, outputDisposed: false }, 'A real pending child retains command/output/disposal ownership');
    }
    const waitFor = async predicate => {
        const limit = Date.now() + 3000;
        while (!predicate() && Date.now() < limit) await new Promise(resolve => setTimeout(resolve, 10));
        assert(predicate(), 'Probe resources must finish their actual cleanup');
    };
    if (mode !== 'dispose') {
        assert(fs.existsSync(other.configuration.program));
        assert.deepEqual(stops, [], 'An unrelated live file must not be stopped for a sink failure');
    }
    if (!expected) await waitFor(() => !fs.existsSync(first.output));
    if (mode === 'failure' || mode === 'cancel') {
        retry = true; active.isDirty = true;
        active.save = async () => { fs.writeFileSync(source, 'Console.WriteLine("corrected");\n'); active.isDirty = false; return true; };
        assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => api.debugActiveFile())), [true, true, true]);
        const next = rows.filter(row => row.kind === 'build' && row.source === source).at(-1);
        assert.notEqual(next.output, first.output);
        assert.equal(next.closed, true);
        assert.equal(logs.filter(line => line === diagnostic).length, 2, 'The next process may report its own sink failure once');
        assert(fs.existsSync(other.configuration.program));
        assert.deepEqual(stops, []);
    }
    if (mode === 'success') assert(metadata.some(value => value.includes('STREAM_STDOUT_2')));
    await (disposal || api.dispose());
    assert.equal(outputDisposed, true);
    assert.equal(postDisposeWrites, 0, 'Actual child observation must finish before diagnostics are disposed');
    assert(cleanup.filter(row => row.owner === source).every(row => row.closed && row.callback),
        'Cleanup observations outside the guarded sink must follow actual child close');
    for (const build of rows.filter(row => row.kind === 'build')) {
        assert(cleanup.some(row => row.owner === build.source && row.originalOutput === build.output && row.closed && row.callback),
            'Each exact original output must retain its own close/cleanup witness across publication and retry');
    }
    assert(!stops.includes('external-session'));
    assert.equal(fs.readFileSync(external, 'utf8'), 'unrelated marker');
    assert(rows.every(row => row.closed));
    process.stdout.write(JSON.stringify({ event: 'probe-done', mode, values, childCount: rows.length,
        diagnosticCount: logs.filter(line => line === diagnostic).length, cleanupCount: cleanup.length }) + '\n');
}

for (const mode of ['success', 'failure', 'cancel', 'dispose']) {
    test(`stream output diagnostics preserve ${mode} through a throwing native stream sink`, { timeout: 15000 }, async t => {
        const root = fs.mkdtempSync(path.join(os.tmpdir(), 'netcoredbg-stream-probe-'));
        const pids = [];
        t.after(async () => {
            const alive = pid => { try { process.kill(pid, 0); return true; } catch (error) { if (error.code === 'ESRCH') return false; throw error; } };
            const limit = Date.now() + 3000;
            while (pids.some(alive) && Date.now() < limit) await new Promise(resolve => setTimeout(resolve, 20));
            assert(pids.every(pid => !alive(pid)), 'Every exact owned CLI child must exit before fixture deletion, even after a baseline host crash');
            assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
            assert(path.basename(root).startsWith('netcoredbg-stream-probe-'));
            fs.rmSync(root, { recursive: true, force: true });
        });
        const child = spawnSync(process.execPath, ['--unhandled-rejections=strict', '-e',
            '(' + streamOutputProbe.toString() + ')().catch(error => { console.error(error); process.exitCode = 2; })',
            require.resolve('./runtime.cjs'), root, mode], { encoding: 'utf8', timeout: 10000, windowsHide: true });
        const records = child.stdout.split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
        pids.push(...records.filter(row => row.event === 'owned-child').map(row => row.pid));
        assert.equal(child.error, undefined, 'The strict activation probe must complete within its safety limit');
        assert(pids.length >= 6, 'The probe must reach the real CLI build after its independent file control');
        assert.equal(child.status, 0, `A stream diagnostic exception must not escape the ${mode} activation host.\n${child.stderr}`);
        const completed = records.find(row => row.event === 'probe-done');
        assert.equal(completed?.mode, mode);
        assert.equal(completed.childCount, pids.length);
        assert(completed.cleanupCount >= 2);
    });
}

test('output allocation retains ordinary mkdtemp behavior without entering the Windows fallback', async () => {
    const directory = path.join('output', 'run-Ab12Cd');
    const calls = [];
    const result = await createOutputDirectory('output', { platform: 'win32', io: {
        async mkdtemp(prefix) { calls.push(prefix); return directory; },
        async mkdir() { assert.fail('Ordinary allocation must not invoke mkdir'); },
    }, randomInt() { assert.fail('Ordinary allocation must not draw another name'); },
    log() { assert.fail('Ordinary allocation must not report fallback'); } });
    assert.equal(result, directory);
    assert.deepEqual(calls, [path.join('output', 'run-')]);
});

for (const [platform, code] of [['win32', 'EACCES'], ['linux', 'ENAMETOOLONG'], ['darwin', 'ENAMETOOLONG']]) {
    test(`output allocation preserves ${platform} ${code} instead of masking the original error`, async () => {
        const error = Object.assign(new Error('Original allocation failed'), { code });
        await assert.rejects(createOutputDirectory('output', { platform, io: {
            async mkdtemp() { throw error; },
            async mkdir() { assert.fail('This failure must not enter the Windows fallback'); },
        } }), actual => actual === error);
    });
}

test('Windows output fallback exclusively creates a six-alphanumeric sibling without touching a collision', async t => {
    const f = fixture(t);
    const parent = path.join(f.root, 'output-parent');
    fs.mkdirSync(parent);
    const collision = path.join(parent, 'run-AAAAAA');
    fs.mkdirSync(collision);
    const sentinel = path.join(collision, 'unrelated.txt');
    fs.writeFileSync(sentinel, 'preserve');
    const created = [], logs = [];
    let randomCalls = 0;
    const directory = await createOutputDirectory(parent, { platform: 'win32', io: {
        async mkdtemp() { throw Object.assign(new Error('Windows temporary path rejected'), { code: 'ENAMETOOLONG' }); },
        async mkdir(candidate, settings) {
            assert.deepEqual(settings, { mode: 0o700 });
            created.push(candidate);
            return fs.promises.mkdir(candidate, settings);
        },
    }, randomInt(maximum) { assert.equal(maximum, 62); return randomCalls++ < 6 ? 0 : 1; }, log: line => logs.push(line) });
    assert.equal(directory, path.join(parent, 'run-BBBBBB'));
    assert.match(path.basename(directory), /^run-[A-Za-z0-9]{6}$/);
    assert.equal(path.dirname(directory), parent);
    assert.deepEqual(created, [collision, directory]);
    assert.equal(fs.readFileSync(sentinel, 'utf8'), 'preserve');
    assert(fs.statSync(directory).isDirectory());
    if (process.platform !== 'win32') assert.equal(fs.statSync(directory).mode & 0o777, 0o700);
    assert.deepEqual(logs, [`Created Windows file-app output after mkdtemp ENAMETOOLONG: ${directory}`]);
});

test('Windows output fallback bounds collisions and never accepts an existing path', async () => {
    const collision = Object.assign(new Error('Every candidate already exists'), { code: 'EEXIST' });
    let attempts = 0, randomCalls = 0;
    await assert.rejects(createOutputDirectory('output', { platform: 'win32', io: {
        async mkdtemp() { throw Object.assign(new Error('Temporary path rejected'), { code: 'ENAMETOOLONG' }); },
        async mkdir(candidate, settings) {
            assert.equal(candidate, path.join('output', 'run-AAAAAA'));
            assert.deepEqual(settings, { mode: 0o700 });
            attempts++;
            throw collision;
        },
    }, randomInt() { randomCalls++; return 0; }, log() { assert.fail('An existing path must never be reported as created'); } }),
    actual => actual === collision);
    assert.equal(attempts, 8);
    assert.equal(randomCalls, 48);
});

test('Windows output fallback propagates a noncollision mkdir error without retrying', async () => {
    const denied = Object.assign(new Error('Creation denied'), { code: 'EACCES' });
    let attempts = 0;
    await assert.rejects(createOutputDirectory('output', { platform: 'win32', io: {
        async mkdtemp() { throw Object.assign(new Error('Temporary path rejected'), { code: 'ENAMETOOLONG' }); },
        async mkdir() { attempts++; throw denied; },
    }, randomInt: () => 0 }), actual => actual === denied);
    assert.equal(attempts, 1);
});

test('a fallback diagnostic failure cannot abandon a newly created output', async () => {
    const directory = await createOutputDirectory('output', { platform: 'win32', io: {
        async mkdtemp() { throw Object.assign(new Error('Temporary path rejected'), { code: 'ENAMETOOLONG' }); },
        async mkdir() {},
    }, randomInt: () => 0, log() { throw new Error('Logger unavailable'); } });
    assert.equal(directory, path.join('output', 'run-AAAAAA'));
});

test('disposal reentered after fallback creation retains ownership until aborted output cleanup', { timeout: 5000 }, async t => {
    let f, created;
    const activateWithFallback = activationWithOutputIO({
        async mkdtemp() { throw Object.assign(new Error('Temporary path rejected'), { code: 'ENAMETOOLONG' }); },
        async mkdir(directory, settings) {
            const result = await fs.promises.mkdir(directory, settings);
            if (!settings?.recursive) created = directory;
            return result;
        },
    });
    f = fixture(t, { activate: activateWithFallback, appendLine(line) {
        if (line.startsWith('Created Windows file-app output after mkdtemp ENAMETOOLONG:')) f.dispose();
    } });
    assert.equal(await f.api.debugActiveFile(), false);
    await f.api.disposalReady;
    assert(created && !fs.existsSync(created), 'The successfully created fallback output must be owned and cleaned');
    assert(!f.calls.processes.some(call => call.args[0] === 'build'));
    assert.deepEqual(f.calls.launches, []);
    assert.deepEqual(f.calls.errors, []);
    assert.deepEqual(terminalOutputs(f), []);
    assertDisposed(f);
});

test('Windows long storage allocates, launches and journals terminal output without namespace paths', {
    skip: process.platform !== 'win32', timeout: 10000,
}, async t => {
    const storageRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'netcoredbg-long-output-'));
    t.after(() => {
        assert.equal(path.dirname(path.resolve(storageRoot)), path.resolve(os.tmpdir()));
        assert(path.basename(storageRoot).startsWith('netcoredbg-long-output-'));
        fs.rmSync(storageRoot, { recursive: true, force: true });
    });
    const parentLength = 237;
    const storageLength = parentLength - path.join('file-based-apps', '0'.repeat(24)).length - 1;
    const padding = storageLength - storageRoot.length - 1;
    assert(padding > 0 && padding <= 255, 'The native probe needs one bounded long storage component');
    const storage = path.join(storageRoot, 's'.repeat(padding));
    const f = fixture(t, { storage });
    assert.equal(await f.api.debugActiveFile(), true,
        `The real Windows filesystem must permit the long output through allocation and handoff.\n${f.calls.logs.join('\n')}`);
    const config = f.calls.launches[0].config;
    assert.equal(path.dirname(config.__netcoredbgFileAppOutput).length, parentLength);
    assert.match(path.basename(config.__netcoredbgFileAppOutput), /^run-[A-Za-z0-9]{6}$/);
    assert(!config.program.startsWith('\\\\?\\'), 'Stored output and debugger paths must retain ordinary spellings');
    assert(fs.existsSync(config.program));
    f.terminate(config);
    await f.api.dispose();
    assert(!fs.existsSync(config.__netcoredbgFileAppOutput), 'The existing v1 journal must accept and clean the long owned output');
    const base = path.join(storage, 'file-based-apps');
    for (const name of ['terminal-cleanup-v1', 'terminal-cleanup-staging-v1']) {
        const queue = path.join(base, name);
        assert(!fs.existsSync(queue) || fs.readdirSync(queue).length === 0);
    }
});

function activationWithRecoveryIO(overrides) {
    const runtimeModule = { exports: {} };
    const nativeRecovery = require('./recovery.cjs');
    vm.runInNewContext(fs.readFileSync(require.resolve('./runtime.cjs'), 'utf8'), {
        module: runtimeModule, process, AbortController, setTimeout, clearTimeout,
        require: name => name === './recovery.cjs' ? { createRecovery: settings => nativeRecovery.createRecovery({
            ...settings, fs: { promises: { ...fs.promises, ...overrides } },
        }) } : require(name),
    });
    return runtimeModule.exports.activate;
}

async function retainedTerminalOutput(t, { staging = false } = {}) {
    const activate = staging ? activationWithRecoveryIO({
        rename: async (source, destination) => {
            if (path.basename(path.dirname(destination)) === 'terminal-cleanup-v1') {
                throw Object.assign(new Error('Final publication is temporarily blocked'), { code: 'EBUSY' });
            }
            return fs.promises.rename(source, destination);
        },
    }) : undefined;
    const owner = fixture(t, { ...(activate ? { activate } : {}), startResult: false,
        removeOutput: async () => { throw Object.assign(new Error('Terminal output is temporarily locked'), { code: 'EBUSY' }); },
    });
    await owner.api.recoveryReady;
    assert.equal(await owner.api.debugActiveFile(), false);
    await owner.api.dispose();
    const base = path.join(owner.context.globalStorageUri.fsPath, 'file-based-apps');
    const queue = path.join(base, staging ? 'terminal-cleanup-staging-v1' : 'terminal-cleanup-v1');
    const [name] = fs.readdirSync(queue);
    const entry = path.join(queue, name);
    const output = path.join(entry, 'output');
    assert(fs.existsSync(path.join(output, 'FileApp.dll')));
    assert(fs.existsSync(path.join(entry, 'record.json')));
    assert.equal(owner.calls.disposals.output, 1, 'The terminal writer must drain before the next owner starts');
    return { owner, base, entry, output };
}

function preparationFixture(t, options = {}) {
    let elapsed = 0;
    let latest;
    const timers = new Set();
    const f = fixture(t, { ...options, preparationTimeoutMs: 100, now: () => elapsed,
        scheduleTimeout: callback => { latest = { callback }; timers.add(latest); return latest; },
        clearTimeout: timer => timers.delete(timer),
    });
    return { ...f, advance: ms => { elapsed += ms; }, timers,
        expire: () => { assert(latest, 'A preparation deadline must be armed'); elapsed += 100; latest.callback(); } };
}

function certificatePhaseFixture(t, options = {}) {
    const f = preparationFixture(t, { ...options, web: true });
    const certificate = { processes: [], prompts: 0 };
    const run = f.dependencies.runDotnet;
    f.dependencies.runDotnet = async (args, settings) => {
        if (args[0] !== 'dev-certs') return run(args, settings);
        f.calls.processes.push({ args, settings });
        certificate.processes.push({ args, settings });
        return options.certificateProcess ? options.certificateProcess(args, settings, certificate.processes.length) :
            { exitCode: certificate.processes.length === 1 ? 7 : 0 };
    };
    f.vscode.window.showWarningMessage = (...args) => {
        certificate.prompts++;
        return options.certificatePrompt ? options.certificatePrompt(...args) : Promise.resolve('Trust development certificate');
    };
    const writeProfile = environmentVariables => fs.writeFileSync(f.source.replace(/\.cs$/, '.run.json'), JSON.stringify({
        profiles: { Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011', environmentVariables } },
    }));
    writeProfile();
    return { ...f, certificate, writeProfile };
}

function assertDisposed(f, tracker = 1) {
    assert.deepEqual(f.calls.disposals, { command: 1, started: 1, terminated: 1, tracker, output: 1 });
}

function observeDisposal(f) {
    const state = { settled: false };
    assert.equal(typeof f.api.dispose, 'function', 'Runtime must expose the shutdown bridge');
    state.promise = f.api.dispose();
    assert.equal(state.promise, f.api.disposalReady, 'All shutdown callers must share the drain boundary');
    assert.equal(f.api.dispose(), state.promise, 'Repeated disposal must retain Promise identity');
    state.promise.then(() => { state.settled = true; });
    return state;
}

test('runtime drain resolves only after final resources release and survives reentrant throwing disposal', async t => {
    let f, reentrant, outputCallbackCompleted = false;
    f = fixture(t, { disposeOutput() {
        reentrant = f.api.dispose();
        outputCallbackCompleted = true;
        throw new Error('Output dispose failed after release');
    } });
    await f.api.recoveryReady;
    let resolved = false;
    f.api.disposalReady?.then(() => { resolved = true; });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(resolved, false, 'Readiness must not resolve merely because activation is idle');
    const disposal = observeDisposal(f);
    assert.equal(reentrant, disposal.promise);
    await disposal.promise;
    assert.equal(outputCallbackCompleted, true);
    assertDisposed(f);
});

test('graceful disposal prevents a pending save from starting SDK work and rejects future commands', async t => {
    let resolveSave;
    const f = fixture(t, { dirty: true, save: () => new Promise(resolve => { resolveSave = resolve; }) });
    const operation = f.api.debugActiveFile();
    await waitFor(() => resolveSave, 'The source save must be pending');
    f.dispose();
    f.dispose();
    const disposal = observeDisposal(f);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(disposal.settled, false, 'The editor shutdown bridge must wait for the save provider');
    resolveSave(true);
    assert.equal(await operation, false);
    assert.equal(await f.api.debugActiveFile(), false);
    assert.equal(f.calls.handler, undefined, 'The command registration must be removed immediately');
    assert.deepEqual(f.calls.classifications, []);
    assert.deepEqual(f.calls.processes, []);
    assert.deepEqual(f.calls.launches, []);
    assert.deepEqual(f.calls.errors, []);
    await waitFor(() => f.calls.disposals.output, 'An idle disposed owner must release its resources');
    await disposal.promise;
    assertDisposed(f);
});

test('graceful disposal suppresses a pending save rejection instead of notifying after teardown', async t => {
    let rejectSave;
    const f = fixture(t, { dirty: true, save: () => new Promise((_resolve, reject) => { rejectSave = reject; }) });
    const operation = f.api.debugActiveFile();
    await waitFor(() => rejectSave, 'The source save must be pending');
    f.dispose();
    rejectSave(new Error('Save provider failed after disposal'));
    assert.equal(await operation, false);
    assert.deepEqual(f.calls.errors, []);
    assert.deepEqual(f.calls.processes, []);
    await waitFor(() => f.calls.disposals.output, 'Background recovery must also drain before final release');
    assertDisposed(f);
});

test('graceful disposal waits for an in-flight classification and keeps its original failure quiet', async t => {
    let rejectClassification;
    const f = fixture(t, { classify: () => new Promise((_resolve, reject) => { rejectClassification = reject; }) });
    const operation = f.api.debugActiveFile();
    await waitFor(() => rejectClassification, 'Classification must be pending');
    f.dispose();
    assert.equal(f.calls.disposals.output, 0, 'Diagnostics must remain available while preparation settles');
    rejectClassification(new Error('Project evaluation failed during disposal'));
    assert.equal(await operation, false);
    assert(f.calls.logs.some(line => line.includes('Project evaluation failed during disposal')));
    assert.deepEqual(f.calls.errors, []);
    assert.deepEqual(f.calls.launches, []);
    await waitFor(() => f.calls.disposals.output, 'The settled owner must also wait for recovery');
    assertDisposed(f);
});

test('graceful disposal cancels fresh SDK work while an older cleanup retry retains drain ownership', async t => {
    let releaseCleanup;
    const cleanupGate = new Promise(resolve => { releaseCleanup = resolve; });
    let releaseSdk;
    let gateSdk = false;
    let retrying = false;
    let first = true;
    const f = fixture(t, { dirty: true, buildError: new Error('Compiler failure'),
        findDotnet: () => gateSdk ? new Promise(resolve => { releaseSdk = resolve; })
            : { executable: 'dotnet', root: f.root },
        removeOutput: async (directory, settings) => {
            if (first) { first = false; throw Object.assign(new Error('Output is busy'), { code: 'EBUSY' }); }
            retrying = true;
            await cleanupGate;
            await fs.promises.rm(directory, settings);
        } });
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const processCount = f.calls.processes.length;
    const saveCount = f.calls.saves;
    const errorCount = f.calls.errors.length;
    gateSdk = true;
    const operation = f.api.debugActiveFile();
    try {
        await waitFor(() => retrying, 'The retained terminal output must be retrying cleanup');
        await waitFor(() => releaseSdk, 'Fresh SDK discovery must not wait for an older terminal deletion');
        assert.equal(f.calls.saves, saveCount + 1, 'The fresh command may save before disposal');
        const disposal = observeDisposal(f);
        releaseSdk({ executable: 'dotnet', root: f.root });
        assert.equal(await operation, false);
        assert.equal(f.calls.disposals.output, 0, 'The unsettled deletion must retain cleanup diagnostics');
        assert.equal(disposal.settled, false);
        assert.equal(f.calls.processes.length, processCount, 'Disposal must prevent downstream SDK processes');
        assert.equal(f.calls.errors.length, errorCount);
        assert.deepEqual(f.calls.launches, []);
        assert.equal(await f.api.debugActiveFile(), false);
        releaseCleanup();
        await disposal.promise;
        assert.deepEqual(terminalOutputs(f), []);
        assertDisposed(f);
    } finally {
        f.dispose();
        releaseSdk?.({ executable: 'dotnet', root: f.root });
        releaseCleanup();
        await operation;
        await f.api.disposalReady;
    }
});

for (const outcomeBeforeEvent of [false, true]) {
    test(`graceful disposal captures a late exact session and waits for start outcome and termination (${outcomeBeforeEvent ? 'outcome first' : 'event first'})`, async t => {
        let resolveStart;
        let resolveStop;
        const f = fixture(t, { startDebugging: () => new Promise(resolve => { resolveStart = resolve; }),
            stopDebugging: () => new Promise(resolve => { resolveStop = resolve; }) });
        const operation = f.api.debugActiveFile();
        await waitFor(() => resolveStart, 'The editor start request must be pending');
        const config = f.calls.launches[0].config;
        f.dispose();
        const disposal = observeDisposal(f);
        assert.equal(await operation, false);
        if (outcomeBeforeEvent) { resolveStart(true); await new Promise(resolve => setImmediate(resolve)); }
        const unrelated = { ...config, program: path.join(path.dirname(config.program), 'Other.dll') };
        f.startSession(unrelated);
        assert.deepEqual(f.calls.stops, [], 'A nonmatching session must not be stopped during disposal');
        const session = f.startSession(config);
        await waitFor(() => resolveStop, 'The late owned session must receive targeted Stop');
        assert.deepEqual(f.calls.stops, [session]);
        assert.equal(f.calls.disposals.started, 0, 'A pending owned launch still needs lifecycle listeners');
        resolveStop();
        await new Promise(resolve => setImmediate(resolve));
        assert(fs.existsSync(config.program), 'Resolved Stop alone must preserve output until termination');
        assert.equal(f.calls.disposals.output, 0);
        assert.equal(disposal.settled, false, 'Stop acknowledgement is not the runtime drain boundary');
        f.terminate(config);
        await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'Matching termination must release owned output');
        if (!outcomeBeforeEvent) {
            assert.equal(f.calls.disposals.output, 0, 'The original editor start outcome must remain observed');
            assert.equal(disposal.settled, false);
            resolveStart(true);
        }
        await waitFor(() => f.calls.disposals.output, 'Terminal owned work must release retained listeners and output');
        await disposal.promise;
        assertDisposed(f);
        f.dispose();
        assert.deepEqual(f.calls.stops, [session], 'Repeated disposal must not request Stop twice');
        assert.deepEqual(f.calls.errors, []);
    });
}

test('graceful disposal stops active owned sessions once and preserves unrelated output', async t => {
    const f = fixture(t);
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    const unrelatedDirectory = path.join(f.root, 'unrelated-output');
    fs.mkdirSync(unrelatedDirectory);
    const sentinel = path.join(unrelatedDirectory, 'keep.txt');
    fs.writeFileSync(sentinel, 'unrelated');
    const unrelated = f.startSession({ type: 'coreclr', name: 'Other', program: sentinel,
        __netcoredbgFileAppOutput: unrelatedDirectory });
    f.dispose();
    f.dispose();
    const disposal = observeDisposal(f);
    await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'Active owned output must be cleaned after Stop termination');
    await waitFor(() => f.calls.disposals.output, 'All terminal owned work must release the owner');
    await disposal.promise;
    assert.equal(f.calls.stops.length, 1);
    assert.equal(f.calls.stops[0].configuration, config);
    assert.notEqual(f.calls.stops[0].id, unrelated.id);
    assert.equal(fs.readFileSync(sentinel, 'utf8'), 'unrelated');
    assertDisposed(f);
});

test('graceful disposal retains uncertain output after Stop rejection without error UI or repeated Stop', async t => {
    const f = fixture(t, { stopDebugging: async () => { throw new Error('Adapter refused disposal disconnect'); } });
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    f.dispose();
    await waitFor(() => f.calls.logs.some(line => line.includes('Adapter refused disposal disconnect')), 'Stop failure must remain in diagnostics');
    const disposal = observeDisposal(f);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(disposal.settled, false, 'Uncertain session ownership must not be reported as drained');
    f.dispose();
    assert.equal(f.calls.stops.length, 1);
    assert.deepEqual(f.calls.errors, []);
    assert(fs.existsSync(config.program));
    assert.deepEqual(terminalOutputs(f), [], 'An uncertain live session must not become an eligible terminal receipt');
    assert.equal(f.calls.disposals.output, 0, 'Unknown live work must retain its lifecycle observers');
    f.terminate(config);
    await waitFor(() => f.calls.disposals.output, 'A later confirmed termination permits final release');
    await disposal.promise;
    assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
    assertDisposed(f);
});

test('graceful disposal leaves terminal cleanup failures recoverable and releases resources once', async t => {
    const f = fixture(t, { removeOutput: async () => { throw Object.assign(new Error('Still busy'), { code: 'EBUSY' }); },
        disposeOutput: () => { throw new Error('Output disposal failed'); } });
    assert.equal(await f.api.debugActiveFile(), true);
    f.dispose();
    await waitFor(() => f.calls.disposals.output, 'Terminal failed cleanup must not keep the owner alive forever');
    assert.equal(terminalOutputs(f).length, 1);
    assert(fs.existsSync(path.join(terminalOutputs(f)[0], 'FileApp.dll')));
    assert.equal(await f.api.debugActiveFile(), false);
    assert.deepEqual(f.calls.errors, []);
    f.dispose();
    assertDisposed(f);
});

test('graceful disposal reentered from a cleanup provider waits for that deletion to settle', async t => {
    let releaseCleanup;
    let outputDisposedInsideProvider;
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        f.dispose();
        outputDisposedInsideProvider = f.calls.disposals.output;
        await new Promise(resolve => { releaseCleanup = resolve; });
        await fs.promises.rm(directory, settings);
    } });
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    f.terminate(config);
    await waitFor(() => releaseCleanup, 'The termination deletion must reach its provider');
    const disposal = observeDisposal(f);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(disposal.settled, false, 'Reentrant disposal must wait for the registered deletion');
    try {
        assert.equal(outputDisposedInsideProvider, 0, 'Register cleanup ownership before calling a reentrant provider');
        assert.equal(f.calls.disposals.started, 0);
        assert.equal(f.calls.disposals.terminated, 0);
        const [queued] = terminalOutputs(f);
        assert(queued, 'Reentrant disposal must retain the published terminal receipt');
        assert(fs.existsSync(path.join(queued, 'FileApp.dll')));
        assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
    } finally { releaseCleanup(); }
    await waitFor(() => f.calls.disposals.output, 'Settled terminal cleanup must complete disposal');
    await disposal.promise;
    assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
    assert.deepEqual(f.calls.stops, [], 'A session already confirmed terminal needs no Stop');
    assertDisposed(f);
});

for (const firstStopSettled of [false, true]) {
    test(`adapter configuration success retries one early exact Stop and serializes attempts (${firstStopSettled ? 'early acknowledgement' : 'first Stop pending'})`, async t => {
        let releaseFirst;
        let releaseSecond;
        let first;
        const f = fixture(t, { stopDebugging: () => {
            if (f.calls.stops.length === 1) {
                first = new Promise(resolve => { releaseFirst = resolve; });
                return first;
            }
            return new Promise(resolve => { releaseSecond = resolve; });
        } });
        assert.equal(await f.api.debugActiveFile(), true);
        const config = f.calls.launches[0].config;
        const session = f.session(config);
        f.dispose();
        await waitFor(() => releaseFirst, 'An early exact Stop must be requested');
        if (firstStopSettled) { releaseFirst(); await first; await new Promise(resolve => setImmediate(resolve)); }
        f.configuration(session);
        f.configuration(session); // Duplicate successful ready events must not multiply Stops.
        if (!firstStopSettled) {
            await new Promise(resolve => setImmediate(resolve));
            assert.equal(f.calls.stops.length, 1, 'The second Stop must wait for the first to settle');
            releaseFirst();
        }
        await waitFor(() => releaseSecond, 'Configuration completion must trigger one follow-up Stop');
        assert.deepEqual(f.calls.stops, [session, session]);
        f.configuration(session);
        releaseSecond();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(f.calls.stops.length, 2);
        assert(fs.existsSync(config.program), 'Both Stop acknowledgements still require matching termination');
        assert.equal(f.calls.disposals.tracker, 0, 'The configuration tracker must live with uncertain work');
        f.terminate(config);
        await waitFor(() => f.calls.disposals.output, 'Matching termination must complete disposal');
        assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
        assert.deepEqual(f.calls.errors, []);
        assertDisposed(f);
    });
}

for (const beforeDispose of [false, true]) {
    test(`adapter configuration ready before actual Stop dispatch needs no retry (${beforeDispose ? 'ready before disposal' : 'ready before Stop microtask'})`, async t => {
        const f = fixture(t, { stopDebugging: async () => {} });
        assert.equal(await f.api.debugActiveFile(), true);
        const config = f.calls.launches[0].config;
        const session = f.session(config);
        if (beforeDispose) f.configuration(session);
        f.dispose();
        if (!beforeDispose) f.configuration(session);
        await waitFor(() => f.calls.stops.length, 'Disposal must request exact Stop');
        f.configuration(session);
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(f.calls.stops, [session], 'A ready-first Stop requires only one request');
        assert(fs.existsSync(config.program));
        f.terminate(config);
        await waitFor(() => f.calls.disposals.output, 'Confirmed termination must release the tracker');
        assertDisposed(f);
    });
}

test('adapter configuration ignores unrelated, failed and uncorrelated responses', async t => {
    const f = fixture(t, { stopDebugging: async () => {} });
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    const session = f.session(config);
    f.dispose();
    await waitFor(() => f.calls.stops.length, 'The first early Stop must be acknowledged');
    const unrelated = f.startSession({ ...config, program: path.join(path.dirname(config.program), 'Other.dll') });
    f.configuration(unrelated);
    const tracker = f.tracker(session);
    tracker?.onDidSendMessage?.({ type: 'response', command: 'configurationDone', request_seq: 9999, success: true });
    f.configuration(session, false);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(f.calls.stops, [session], 'Only the successful matching readiness response can request a retry');
    f.configuration(session);
    await waitFor(() => f.calls.stops.length === 2, 'A later valid ready response must request the exact follow-up Stop');
    assert.deepEqual(f.calls.stops, [session, session]);
    // Restore the primary fixture lookup after creating an unrelated config.
    f.emitStart(session);
    f.terminate(config);
    await waitFor(() => f.calls.disposals.output, 'The owned session must release after actual termination');
    assertDisposed(f);
});

test('adapter configuration retry failures preserve uncertain output and remain quiet after disposal', async t => {
    const f = fixture(t, { stopDebugging: async () => { throw new Error('Native Stop failed'); } });
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    const session = f.session(config);
    f.dispose();
    await waitFor(() => f.calls.stops.length === 1, 'The early Stop must run');
    f.configuration(session);
    await waitFor(() => f.calls.stops.length === 2, 'Successful configuration permits the single follow-up attempt');
    f.configuration(session);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(f.calls.stops, [session, session]);
    assert.deepEqual(f.calls.errors, []);
    assert(fs.existsSync(config.program));
    assert.deepEqual(terminalOutputs(f), []);
    assert.equal(f.calls.disposals.output, 0);
    assert.equal(f.calls.disposals.tracker, 0);
    assert(f.calls.logs.some(line => line.includes('Native Stop failed')));
    f.terminate(config);
    await waitFor(() => f.calls.disposals.output, 'A later terminal event permits cleanup after failed Stops');
    assertDisposed(f);
});

test('adapter configuration arriving after termination cannot restart Stop or cleanup', async t => {
    const f = fixture(t, { stopDebugging: async () => {} });
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    const session = f.session(config);
    f.dispose();
    await waitFor(() => f.calls.stops.length === 1, 'The early Stop must be requested');
    f.terminate(config);
    await waitFor(() => f.calls.disposals.output, 'Termination must release the owner');
    f.configuration(session);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(f.calls.stops, [session]);
    assertDisposed(f);
});

test('adapter configuration API absence preserves conservative Stop and termination behavior', async t => {
    const f = fixture(t, { noTrackerAPI: true, stopDebugging: async () => {} });
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    const session = f.session(config);
    f.dispose();
    await waitFor(() => f.calls.stops.length === 1, 'An exact Stop remains available without tracker support');
    assert(fs.existsSync(config.program));
    assert.equal(f.calls.disposals.output, 0);
    f.terminate(config);
    await waitFor(() => f.calls.disposals.output, 'Matching termination still releases owned resources');
    assert.deepEqual(f.calls.stops, [session]);
    assertDisposed(f, 0);
});

function dapExit(tracker, code = 0) {
    tracker.onDidSendMessage({ type: 'event', event: 'exited', body: { exitCode: code } });
}

function dapTermination(tracker, body = {}) {
    tracker.onDidSendMessage({ type: 'event', event: 'terminated', body });
}

async function assertUncertainDAP(f, config, disposal) {
    await new Promise(resolve => setImmediate(resolve));
    assert(fs.existsSync(config.program), 'Unconfirmed debuggee output must remain untouched');
    assert.deepEqual(terminalOutputs(f), [], 'Unconfirmed output must not become a terminal receipt');
    assert.equal(f.calls.disposals.tracker, 0);
    assert.equal(f.calls.disposals.output, 0);
    if (disposal) assert.equal(disposal.settled, false);
    assert(!f.calls.logs.some(line => line.includes('Confirmed disposed C# session termination from paired DAP')));
}

for (const code of [0, -1, -2147483648, 2147483647]) {
    test(`disposed exact session drains from DAP debuggee exit then non-restarting termination (${code})`, async t => {
        const f = fixture(t, { stopDebugging: async () => {} });
        assert.equal(await f.api.debugActiveFile(), true);
        const config = f.calls.launches[0].config;
        const session = f.session(config), tracker = f.tracker(session);
        const disposal = observeDisposal(f);
        dapExit(tracker, code);
        await assertUncertainDAP(f, config, disposal);
        if (code === -1) tracker.onDidSendMessage({ type: 'event', event: 'terminated' });
        else dapTermination(tracker);
        await waitFor(() => f.calls.disposals.output, 'The trusted DAP pair must complete owned cleanup without an API event');
        await disposal.promise;
        assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
        assert.equal(f.calls.logs.filter(line => line.includes('Confirmed disposed C# session termination from paired DAP')).length, 1);
        assert(f.calls.logs.some(line => line.includes(`${session.id} (exitCode=${code})`)));
        assert.deepEqual(f.calls.errors, []);
        assertDisposed(f);
    });
}

for (const [name, messages] of [
    ['termination alone', tracker => dapTermination(tracker)],
    ['reverse order', tracker => { dapTermination(tracker); dapExit(tracker); }],
    ['adapter exit and disconnect acknowledgement', tracker => {
        tracker.onExit?.(0);
        tracker.onDidSendMessage({ type: 'response', command: 'disconnect', success: true });
    }],
    ['a response carrying an exited event field', tracker => {
        tracker.onDidSendMessage({ type: 'response', event: 'exited', body: { exitCode: 0 } });
        dapTermination(tracker);
    }],
]) {
    test(`disposed session preserves output for ${name}`, async t => {
        const f = fixture(t, { stopDebugging: async () => {} });
        await f.api.debugActiveFile();
        const config = f.calls.launches[0].config, tracker = f.tracker(f.session(config));
        const disposal = observeDisposal(f);
        messages(tracker);
        await assertUncertainDAP(f, config, disposal);
        f.terminate(config);
        await disposal.promise;
        assertDisposed(f);
    });
}

test('malformed or missing DAP debuggee exit codes cannot combine with termination', async t => {
    const f = fixture(t, { stopDebugging: async () => {} });
    await f.api.debugActiveFile();
    const config = f.calls.launches[0].config, tracker = f.tracker(f.session(config));
    const disposal = observeDisposal(f);
    for (const body of [undefined, null, {}, [], { exitCode: '0' }, { exitCode: 0.5 }, { exitCode: NaN },
        { exitCode: Infinity }, { exitCode: -2147483649 }, { exitCode: 2147483648 }]) {
        dapExit(tracker); // A malformed later exit must invalidate an earlier candidate too.
        tracker.onDidSendMessage({ type: 'event', event: 'exited', body });
        dapTermination(tracker);
        await assertUncertainDAP(f, config, disposal);
    }
    f.terminate(config);
    await disposal.promise;
});

test('malformed DAP termination clears a pending exit and a later termination cannot reuse it', async t => {
    const f = fixture(t, { stopDebugging: async () => {} });
    await f.api.debugActiveFile();
    const config = f.calls.launches[0].config, tracker = f.tracker(f.session(config));
    const disposal = observeDisposal(f);
    for (const body of [null, 'terminated', [], 0, false]) {
        dapExit(tracker);
        dapTermination(tracker, body);
        dapTermination(tracker);
        await assertUncertainDAP(f, config, disposal);
    }
    f.terminate(config);
    await disposal.promise;
});

for (const restart of [true, false, null, {}]) {
    test(`an explicit DAP restart permanently blocks the shutdown fallback (${JSON.stringify(restart)})`, async t => {
        const f = fixture(t, { stopDebugging: async () => {} });
        await f.api.debugActiveFile();
        const config = f.calls.launches[0].config, tracker = f.tracker(f.session(config));
        const disposal = observeDisposal(f);
        dapExit(tracker);
        dapTermination(tracker, { restart });
        dapExit(tracker);
        dapTermination(tracker);
        await assertUncertainDAP(f, config, disposal);
        f.terminate(config);
        await disposal.promise;
    });
}

test('normal sessions ignore a DAP pair and disposal cannot reuse a pre-disposal exit', async t => {
    const f = fixture(t, { stopDebugging: async () => {} });
    await f.api.debugActiveFile();
    const config = f.calls.launches[0].config, tracker = f.tracker(f.session(config));
    dapExit(tracker);
    dapTermination(tracker);
    await assertUncertainDAP(f, config);
    dapExit(tracker);
    const disposal = observeDisposal(f);
    dapTermination(tracker);
    await assertUncertainDAP(f, config, disposal);
    f.terminate(config);
    await disposal.promise;
});

test('a cancelled start still requires the API event unless its owner is disposing', async t => {
    let resolveStart;
    const f = fixture(t, { startDebugging: () => new Promise(resolve => { resolveStart = resolve; }),
        stopDebugging: async () => {} });
    t.after(() => { resolveStart?.(true); f.dispose(); });
    const operation = f.api.debugActiveFile();
    await waitFor(() => resolveStart, 'The editor start must still be pending');
    const config = f.calls.launches[0].config;
    const session = f.startSession(config), tracker = f.tracker(session);
    f.cancel();
    assert.equal(await operation, false);
    dapExit(tracker);
    dapTermination(tracker);
    await assertUncertainDAP(f, config);
    const disposal = observeDisposal(f);
    dapTermination(tracker);
    await assertUncertainDAP(f, config, disposal);
    f.terminate(config);
    resolveStart(true);
    await disposal.promise;
});

test('exit and termination from separate trackers cannot form a shutdown confirmation', async t => {
    const f = fixture(t, { stopDebugging: async () => {} });
    await f.api.debugActiveFile();
    const config = f.calls.launches[0].config, session = f.session(config);
    const first = f.tracker(session), second = f.createTracker(session);
    const disposal = observeDisposal(f);
    dapExit(first);
    dapTermination(second);
    await assertUncertainDAP(f, config, disposal);
    f.terminate(config);
    await disposal.promise;
});

test('a tracker without the exact captured session cannot release output before or after capture', async t => {
    let tracker;
    const f = fixture(t, { startDebugging: async (_folder, config) => {
        tracker = f.createTracker({ id: 'uncaptured-session', type: 'coreclr', configuration: config });
        return true;
    }, stopDebugging: async () => {} });
    await f.api.debugActiveFile();
    const config = f.calls.launches[0].config;
    const disposal = observeDisposal(f);
    dapExit(tracker);
    dapTermination(tracker);
    await assertUncertainDAP(f, config, disposal);
    const captured = f.startSession(config);
    assert.equal(f.createTracker({ ...captured, id: 'other-session' }), undefined);
    assert.equal(f.createTracker({ ...captured, type: 'other' }), undefined);
    dapExit(tracker);
    dapTermination(tracker);
    await assertUncertainDAP(f, config, disposal);
    f.terminate(config);
    await disposal.promise;
});

for (const property of ['program', '__netcoredbgFileAppOutput', 'type']) {
    test(`a captured session whose ${property} no longer matches cannot use the DAP fallback`, async t => {
        const f = fixture(t, { stopDebugging: async () => {} });
        await f.api.debugActiveFile();
        const config = f.calls.launches[0].config, session = f.session(config), tracker = f.tracker(session);
        const disposal = observeDisposal(f);
        const original = config[property];
        config[property] = `${original}-unrelated`;
        dapExit(tracker);
        dapTermination(tracker);
        config[property] = original;
        await assertUncertainDAP(f, config, disposal);
        dapTermination(tracker);
        await assertUncertainDAP(f, config, disposal);
        f.terminate(config);
        await disposal.promise;
    });
}

for (const apiFirst of [false, true]) {
    test(`DAP duplicates and API termination share one cleanup (${apiFirst ? 'API first' : 'DAP first'})`, async t => {
        let releaseCleanup, rejectStop;
        let removals = 0;
        const f = fixture(t, { stopDebugging: () => new Promise((_resolve, reject) => { rejectStop = reject; }),
            removeOutput: async (directory, settings) => {
                removals++;
                await new Promise(resolve => { releaseCleanup = resolve; });
                await fs.promises.rm(directory, settings);
            } });
        t.after(() => { releaseCleanup?.(); rejectStop?.(new Error('Stop failed after terminal confirmation')); });
        await f.api.debugActiveFile();
        const config = f.calls.launches[0].config, tracker = f.tracker(f.session(config));
        const disposal = observeDisposal(f);
        await waitFor(() => rejectStop, 'The exact session Stop must be pending');
        if (apiFirst) f.terminate(config);
        dapExit(tracker);
        dapTermination(tracker);
        await waitFor(() => releaseCleanup, 'One confirmed terminal deletion must reach the provider');
        dapExit(tracker);
        dapTermination(tracker);
        f.terminate(config);
        rejectStop(new Error('Stop failed after terminal confirmation'));
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(disposal.settled, false, 'The receipt deletion must finish before shutdown is drained');
        assert.equal(removals, 1);
        assert.equal(f.calls.logs.filter(line => line.includes('Confirmed disposed C# session termination from paired DAP')).length, apiFirst ? 0 : 1);
        releaseCleanup();
        await disposal.promise;
        assert.deepEqual(f.calls.errors, []);
        assert(!f.calls.logs.some(line => line.includes('Stop failed after terminal confirmation')));
        assertDisposed(f);
    });
}

test('one preparation deadline bounds cumulative ancestor and multi-target evaluations', async t => {
    const f = preparationFixture(t, { classify: input => classifyWithMsbuild({ ...input, fs: {
        readdir: async directory => directory === path.dirname(f.source) ? ['A.csproj', 'B.csproj'].map(name => ({
            name, isFile: () => true, isSymbolicLink: () => false,
        })) : [],
        realpath: fs.promises.realpath,
    } }) });
    const run = f.dependencies.runDotnet;
    f.dependencies.runDotnet = async (args, settings) => {
        if (args[0] !== 'msbuild') return run(args, settings);
        f.calls.processes.push({ args, settings });
        f.advance(40);
        return { stdout: JSON.stringify({ Properties: { TargetFrameworks: 'net8.0;net10.0' }, Items: { Compile: [] } }) };
    };
    assert.equal(await f.api.debugActiveFile(), false);
    assert.equal(f.calls.processes.length, 3, 'The next evaluation must not receive a fresh time budget');
    assert.equal(f.calls.launches.length, 0);
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /timed out.*Checking project membership.*120 ms/i);
    assert.equal(f.calls.classifications[0].signal.reason.name, 'TimeoutError');
    assert.equal(f.timers.size, 0);
});

test('a preparation deadline waits for the build to settle before cleanup and retry gets a fresh deadline', async t => {
    let settleChild;
    let buildSignal;
    const f = preparationFixture(t, { showErrorMessage: () => new Promise(() => {}) });
    const run = f.dependencies.runDotnet;
    f.dependencies.runDotnet = async (args, settings) => {
        const result = await run(args, settings);
        if (args[0] !== 'build') return result;
        buildSignal = settings.signal;
        return new Promise((_resolve, reject) => {
            settleChild = () => reject(Object.assign(new Error('Child aborted'), { name: 'AbortError' }));
        });
    };
    const operation = f.api.debugActiveFile();
    await waitFor(() => settleChild, 'The build must be pending');
    const build = f.calls.processes.find(call => call.args[0] === 'build');
    const directory = build.args[build.args.indexOf('--output') + 1];
    f.expire();
    assert.equal(buildSignal.reason.name, 'TimeoutError');
    let returned = false;
    void operation.then(() => { returned = true; });
    await new Promise(resolve => setImmediate(resolve));
    assert(!returned, 'Do not abandon a process that can still write output');
    assert(fs.existsSync(path.join(directory, 'FileApp.dll')));
    settleChild();
    assert.equal(await operation, false);
    await waitForRemovedOutput(f, directory);
    assert(!fs.existsSync(directory));
    assert.match(f.calls.errors[0], /timed out.*Building file-based app.*100 ms/i);
    assert(f.calls.logs.some(line => /Phase timed out: Building file-based app/.test(line)));
    f.dependencies.runDotnet = run;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.notEqual(path.dirname(f.calls.launches[0].config.program), directory);
    assert(fs.existsSync(f.calls.launches[0].config.program));
    assert.equal(f.calls.errors.length, 1);
    assert.equal(f.timers.size, 0);
});

test('user cancellation remains quiet when a queued preparation deadline fires afterward', async t => {
    const f = preparationFixture(t, { classify: ({ signal }) => new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(Object.assign(new Error('Process aborted'), { name: 'AbortError' })), { once: true });
    }) });
    const operation = f.api.debugActiveFile();
    await waitFor(() => f.calls.classifications.length, 'Classification must be pending');
    f.cancel();
    f.expire();
    assert.equal(await operation, false);
    assert.equal(f.calls.classifications[0].signal.reason.name, 'AbortError');
    assert.deepEqual(f.calls.errors, []);
    assert(f.calls.logs.some(line => /Phase cancelled: Checking project membership/.test(line)));
    assert.equal(f.timers.size, 0);
});

test('a real failure overtaken by cancellation remains in diagnostics without an error notification', async t => {
    const f = preparationFixture(t, { classify: async () => {
        f.cancel();
        throw new Error('Project import failed during cancellation');
    } });
    assert.equal(await f.api.debugActiveFile(), false);
    assert.deepEqual(f.calls.errors, []);
    assert(f.calls.logs.some(line => line.includes('Project import failed during cancellation')));
    assert(f.calls.logs.some(line => /Phase cancelled: Checking project membership/.test(line)));
    assert.equal(f.timers.size, 0);
});

test('the preparation deadline is disarmed before Web certificate interaction', async t => {
    const f = preparationFixture(t, { webSupport: {
        BUILD_METADATA_ARGS: [], parseBuildMetadata: () => ({ isWebServer: true }),
        prepareWebLaunch: async ({ signal }) => {
            assert.equal(f.timers.size, 0);
            f.expire(); // A previously queued timer must not time out user interaction.
            assert(!signal.aborted);
        },
    } });
    assert.equal(await f.api.debugActiveFile(), true);
    assert.deepEqual(f.calls.errors, []);
    assert.equal(f.timers.size, 0);
});

test('certificate phases attribute a held consent cancellation without spending the SDK deadline', { timeout: 5000 }, async t => {
    const progress = [];
    let dismiss;
    const f = certificatePhaseFixture(t, {
        reportProgress: value => progress.push(value.message),
        certificateProcess: async () => { f.advance(7); return { exitCode: 7 }; },
        certificatePrompt: () => new Promise(resolve => { dismiss = resolve; }),
    });
    const first = f.api.debugActiveFile();
    let repeated;
    try {
        await waitFor(() => dismiss, 'The certificate consent must be pending');
        repeated = f.api.debugActiveFile();
        assert.equal(progress.at(-1), 'Waiting for HTTPS certificate consent');
        assert.equal(f.timers.size, 0, 'User consent must not consume the SDK preparation deadline');
        f.advance(500);
        f.expire(); // Even a queued, disarmed deadline cannot cancel user interaction.
        assert(!f.certificate.processes[0].settings.signal.aborted);
        f.cancel();
        assert.deepEqual(await Promise.all([first, repeated]), [false, false]);
        assert(f.calls.logs.includes('Phase completed: Checking HTTPS development certificate (7 ms; total 7 ms)'));
        assert(f.calls.logs.includes('Phase cancelled: Waiting for HTTPS certificate consent (600 ms; total 607 ms)'));
        assert.deepEqual(f.calls.errors, []);
        dismiss('Trust development certificate');
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(f.certificate.processes.length, 1, 'A late consent answer must not authorize trust');
        assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
        assert.equal(f.calls.launches.length, 0);
        const build = f.calls.processes.find(call => call.args[0] === 'build');
        await waitForRemovedOutput(f, build.args[build.args.indexOf('--output') + 1]);
    } finally {
        f.cancel(); dismiss?.('Cancel');
        await Promise.all([first, repeated]);
        await f.api.dispose();
    }
});

test('certificate phases retain a cancelled trust provider and its output until actual settlement', { timeout: 5000 }, async t => {
    let rejectTrust;
    const failure = new Error('Original trust provider failed after cancellation');
    const f = certificatePhaseFixture(t, { certificateProcess: async (_args, _settings, count) => {
        if (count === 1) return { exitCode: 7 };
        return new Promise((_resolve, reject) => { rejectTrust = () => reject(failure); });
    } });
    let returned = false, disposed = false;
    const operation = f.api.debugActiveFile().then(result => { returned = true; return result; });
    let disposal;
    try {
        await waitFor(() => rejectTrust, 'The noncooperative trust provider must be pending');
        const build = f.calls.processes.find(call => call.args[0] === 'build');
        const directory = build.args[build.args.indexOf('--output') + 1];
        f.advance(31);
        f.expire();
        assert.equal(f.timers.size, 0);
        f.cancel();
        disposal = f.api.dispose().then(() => { disposed = true; });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(returned, false, 'Cancel must not pretend the trust provider settled');
        assert.equal(disposed, false, 'Disposal must retain the active trust provider');
        assert(fs.existsSync(path.join(directory, 'FileApp.dll')));
        assert.equal(f.calls.disposals.output, 0);
        rejectTrust();
        assert.equal(await operation, false);
        await disposal;
        assert(f.calls.logs.includes('Phase cancelled: Preparing HTTPS development certificate (131 ms; total 131 ms)'));
        assert(f.calls.logs.some(line => line.includes('Error observed during Preparing HTTPS development certificate after cancellation:') &&
            line.includes(failure.message)));
        assert(!f.calls.logs.some(line => line.includes('Phase started: Verifying HTTPS development certificate')));
        assert.deepEqual(f.calls.errors, []);
        assert.equal(f.calls.launches.length, 0);
        assert.equal(f.certificate.processes.length, 2);
        assert(!fs.existsSync(directory));
        assertDisposed(f);
    } finally {
        rejectTrust?.();
        await operation;
        await (disposal || f.api.dispose());
    }
});

test('certificate phases attribute failed verification with separate monotonic stage durations', async t => {
    const f = certificatePhaseFixture(t, {
        certificatePrompt: async () => { f.advance(13); return 'Trust development certificate'; },
        certificateProcess: async (_args, _settings, count) => {
            f.advance([7, 29, 11][count - 1]);
            if (count === 3) throw new Error('Original certificate verification failure');
            return { exitCode: count === 1 ? 7 : 0 };
        },
    });
    try {
        assert.equal(await f.api.debugActiveFile(), false);
        assert(f.calls.logs.includes('Phase completed: Checking HTTPS development certificate (7 ms; total 7 ms)'));
        assert(f.calls.logs.includes('Phase completed: Waiting for HTTPS certificate consent (13 ms; total 20 ms)'));
        assert(f.calls.logs.includes('Phase completed: Preparing HTTPS development certificate (29 ms; total 49 ms)'));
        assert(f.calls.logs.includes('Phase failed: Verifying HTTPS development certificate (11 ms; total 60 ms)'));
        assert(f.calls.logs.some(line => line.includes('Original certificate verification failure')));
        assert.match(f.calls.errors[0], /still missing or untrusted after setup/);
        assert.equal(f.calls.launches.length, 0);
        assert.equal(f.timers.size, 0);
    } finally { await f.api.dispose(); }
});

test('certificate phases restore Web validation attribution and tolerate diagnostic failures', async t => {
    for (const invalidRoot of [false, true]) {
        for (const brokenDiagnostics of [false, true]) {
            const f = certificatePhaseFixture(t, { appendLine: line => {
                if (brokenDiagnostics && line.startsWith('Phase ')) throw new Error('Phase output unavailable');
            } });
            if (invalidRoot) f.writeProfile({ DOTNET_ROOT: path.join(f.root, 'wrong-dotnet') });
            try {
                assert.equal(await f.api.debugActiveFile(), !invalidRoot);
                assert(f.calls.logs.some(line => line.startsWith('Phase completed: Verifying HTTPS development certificate')));
                assert.equal(f.timers.size, 0);
                if (invalidRoot) {
                    assert.match(f.calls.errors[0], /web launch profile DOTNET_ROOT does not identify the selected dotnet installation/);
                    assert(f.calls.logs.some(line => line.startsWith('Phase failed: Preparing web launch settings')));
                    assert.equal(f.calls.launches.length, 0);
                } else {
                    assert.deepEqual(f.calls.errors, []);
                    assert.equal(f.calls.launches.length, 1);
                }
            } finally { await f.api.dispose(); }
        }
    }
});

test('the preparation deadline is disarmed before delegating existing project debugging', async t => {
    const f = preparationFixture(t, { kind: 'project' });
    const execute = f.vscode.commands.executeCommand;
    f.vscode.commands.executeCommand = async command => {
        assert.equal(f.timers.size, 0);
        f.expire();
        return execute(command);
    };
    assert.equal(await f.api.debugActiveFile(), true);
    assert.deepEqual(f.calls.commands, ['workbench.action.debug.start']);
    assert.equal(f.calls.processes.length, 0);
    assert.deepEqual(f.calls.errors, []);
});

test('phase diagnostics include monotonic phase and cumulative durations and preserve original failures', async t => {
    const f = preparationFixture(t, { classify: async () => { f.advance(7); throw new Error('Broken project import'); } });
    assert.equal(await f.api.debugActiveFile(), false);
    assert.match(f.calls.errors[0], /Broken project import/);
    assert(f.calls.logs.some(line => /Phase started: Checking project membership/.test(line)));
    assert(f.calls.logs.some(line => /Phase failed: Checking project membership \(7 ms; total 7 ms\)/.test(line)));
    assert.equal(f.timers.size, 0);
});

test('phase logging failures do not change a launch result or its original error', async t => {
    for (const broken of [false, true]) {
        const f = preparationFixture(t, {
            appendLine: line => { if (line.startsWith('Phase ')) throw new Error('Phase output unavailable'); },
            classify: async () => {
                if (broken) throw new Error('Original project failure');
                return { kind: 'file', reason: 'standalone' };
            },
        });
        assert.equal(await f.api.debugActiveFile(), !broken);
        assert.equal(f.timers.size, 0);
        if (broken) assert.match(f.calls.errors[0], /Original project failure/);
        else assert.deepEqual(f.calls.errors, []);
    }
});

test('a preparation deadline aborts a real child and cleanup follows direct-child termination', { timeout: 10000 }, async t => {
    let childPid;
    const exited = () => assert.throws(() => process.kill(childPid, 0), error => error.code === 'ESRCH');
    const f = preparationFixture(t, { removeOutput: async (directory, settings) => {
        assert(childPid, 'A real child must have started');
        exited();
        await fs.promises.rm(directory, settings);
    } });
    const run = f.dependencies.runDotnet;
    f.dependencies.runDotnet = async (args, settings) => {
        if (args[0] !== 'build') return run(args, settings);
        f.calls.processes.push({ args, settings });
        let text = '';
        return runProcess(process.execPath, ['-e', 'process.stdout.write("READY_PID=" + process.pid + "\\n"); setInterval(() => {}, 1000);'], {
            ...settings, onOutput: chunk => {
                text += chunk.toString();
                const ready = /^READY_PID=(\d+)\r?$/m.exec(text);
                if (!childPid && ready) { childPid = Number(ready[1]); f.expire(); }
            },
        });
    };
    const operation = f.api.debugActiveFile();
    t.after(async () => { f.context.subscriptions.at(-1).dispose(); await operation; });
    assert.equal(await operation, false);
    exited();
    const build = f.calls.processes.find(call => call.args[0] === 'build');
    await waitForRemovedOutput(f, build.args[build.args.indexOf('--output') + 1]);
    assert(!fs.existsSync(build.args[build.args.indexOf('--output') + 1]));
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /timed out.*Building file-based app/i);
    assert.equal(f.calls.launches.length, 0);
    assert.equal(f.timers.size, 0);
});

test('waiting for child close preserves stdout, stderr, exit errors and spawn failures', async t => {
    const missing = path.join(fixture(t).root, 'missing-executable');
    const result = await runProcess(process.execPath, ['-e', 'process.stdout.write("out"); process.stderr.write("err");']);
    assert.equal(result.stdout, 'out');
    assert.equal(result.stderr, 'err');
    await assert.rejects(runProcess(process.execPath, ['-e', 'process.stdout.write("failed"); process.stderr.write("reason"); process.exitCode=7;']), error => {
        assert.equal(error.code, 7);
        assert.equal(error.stdout, 'failed');
        assert.equal(error.stderr, 'reason');
        return true;
    });
    await assert.rejects(runProcess(missing, []), { code: 'ENOENT' });
});

test('F5 builds the saved captured file with SDK cwd, then launches existing coreclr adapter', async t => {
    const f = fixture(t, { dirty: true, noWorkspace: true, classify: async (input, calls, vscode) => {
        vscode.window.activeTextEditor = { document: { uri: { scheme: 'file', fsPath: '/another/file.cs' } } };
        return { kind: 'file', reason: 'directive' };
    } });
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.launches.length, 1);
    const { folder, config } = f.calls.launches[0];
    assert.equal(folder, undefined);
    assert.equal(config.type, 'coreclr');
    assert.equal(config.cwd, path.dirname(f.source));
    assert.equal(config.targetArchitecture, 'arm64');
    assert.equal(config.env.DOTNET_ROOT, path.join(f.root, 'dotnet'));
    const build = f.calls.processes.find(call => call.args[0] === 'build');
    assert.equal(build.args[1], f.source);
    assert.equal(build.settings.cwd, path.dirname(f.source));
    assert(build.args.includes('-p:AssemblyName=FileApp'));
    assert(build.args.includes('-p:PublishAot=false'));
    assert(build.args.includes('-p:DebugType=portable'));
    assert.equal(config.program, path.join(build.args[build.args.indexOf('--output') + 1], 'FileApp.dll'));
    assert(fs.existsSync(config.program), 'Output must survive through the debug session');
    assert.deepEqual(f.calls.errors, []);
});

test('a project-owned file delegates to normal F5 without imposing the file-app SDK minimum', async t => {
    const f = fixture(t, { kind: 'project', sdk: '8.0.418' });
    assert.equal(await f.api.debugActiveFile(), true);
    assert.deepEqual(f.calls.commands, ['workbench.action.debug.start']);
    assert.equal(f.calls.launches.length, 0);
    assert.equal(f.calls.processes.length, 0);
});

test('Web SDK build metadata applies HTTP run.json without certificate commands or a second evaluation', async t => {
    const f = fixture(t, { web: true });
    fs.writeFileSync(path.join(path.dirname(f.source), 'tool.run.json'), JSON.stringify({ profiles: {
        local: { commandName: 'Project', launchBrowser: true, applicationUrl: 'http://localhost:5123',
            launchUrl: 'health', commandLineArgs: '--message "hello world"', environmentVariables: { WEB_TEST: 'ready' } },
    } }));
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    assert.equal(config.env.ASPNETCORE_URLS, 'http://localhost:5123');
    assert.equal(config.env.WEB_TEST, 'ready');
    assert.equal(config.env.DOTNET_LAUNCH_PROFILE, 'local');
    assert.deepEqual(config.args, ['--message', 'hello world']);
    assert.equal(config.checkForDevCert, false);
    assert.equal(config.serverReadyAction.action, 'openExternally');
    assert.equal(config.serverReadyAction.uriFormat, '%s/health');
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
    assert(!f.calls.processes.some(call => call.args[0] === 'dev-certs'));
    const build = f.calls.processes.find(call => call.args[0] === 'build');
    assert(build.args.includes('-target:Build'));
    assert(build.args.includes('-getItem:FrameworkReference'));
});

test('an invalid HTTP profile root fails after build and permits corrected coalesced retry with its notification open', { timeout: 5000 }, async t => {
    let dismiss;
    const notification = new Promise(resolve => { dismiss = resolve; });
    const f = fixture(t, { web: true, showErrorMessage: () => notification });
    t.after(() => dismiss());
    const original = fs.readFileSync(f.source);
    const profilePath = f.source.replace(/\.cs$/i, '.run.json');
    const profile = { profiles: { Http: { commandName: 'Project', applicationUrl: 'http://127.0.0.1:5123',
        launchBrowser: false, environmentVariables: { DOTNET_ROOT: path.join(f.root, 'incorrect-sdk-root') } } } };
    fs.writeFileSync(profilePath, JSON.stringify(profile));
    assert.equal(await f.api.debugActiveFile(), false);
    assert.deepEqual(fs.readFileSync(f.source), original, 'The failure must originate only in the launch profile');
    assert.equal(f.calls.launches.length, 0, 'A profile rejection must never call the debug start API');
    const builds = f.calls.processes.filter(call => call.args[0] === 'build');
    assert.equal(builds.length, 1);
    const failedOutput = builds[0].args[builds[0].args.indexOf('--output') + 1];
    await waitForRemovedOutput(f, failedOutput);
    assert(!fs.existsSync(failedOutput));
    assert.deepEqual(terminalOutputs(f), []);
    assert(f.calls.logs.some(line => line.startsWith('Phase completed: Building file-based app')));
    assert(f.calls.logs.some(line => line.startsWith('Phase failed: Preparing web launch settings')));
    assert(!f.calls.logs.some(line => line.startsWith('Phase started: Starting netcoredbg')));
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /The web launch profile DOTNET_ROOT does not identify the selected dotnet installation/);
    assert(!f.calls.processes.some(call => call.args[0] === 'dev-certs'), 'Explicit HTTP profiles cannot enter certificate setup');

    delete profile.profiles.Http.environmentVariables.DOTNET_ROOT;
    fs.writeFileSync(profilePath, JSON.stringify(profile));
    fs.writeFileSync(f.source, 'Console.WriteLine("corrected profile retry");\n');
    f.document.isDirty = true;
    assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 2);
    assert.equal(f.calls.launches.length, 1);
    assert.notEqual(f.calls.launches[0].config.__netcoredbgFileAppOutput, failedOutput);
    assert.equal(f.calls.launches[0].config.env.DOTNET_ROOT, path.join(f.root, 'dotnet'));
    assert.equal(f.calls.launches[0].config.env.ASPNETCORE_URLS, 'http://127.0.0.1:5123');
    assert.equal(f.calls.errors.length, 1, 'The earlier undismissed notification must not obstruct or duplicate retry');
    f.terminate(f.calls.launches[0].config);
    await waitFor(() => !fs.existsSync(f.calls.launches[0].config.__netcoredbgFileAppOutput), 'Retry output must clean after matching termination');
});

test('failed Web builds never enter certificate or browser preparation', async t => {
    let prepared = 0;
    const f = fixture(t, { web: true, buildError: new Error('CS1002'), webSupport: {
        BUILD_METADATA_ARGS: [], parseBuildMetadata: () => ({ isWebServer: true }),
        prepareWebLaunch: async () => { prepared++; },
    } });
    assert.equal(await f.api.debugActiveFile(), false);
    assert.equal(prepared, 0);
    assert.equal(f.calls.launches.length, 0);
});

test('cancelling Web preparation releases F5 and cleans its output before a retry', async t => {
    let cancelFirst = true;
    const f = fixture(t, { web: true, webSupport: {
        BUILD_METADATA_ARGS: [], parseBuildMetadata: () => ({ isWebServer: true }),
        prepareWebLaunch: async ({ signal }) => {
            if (cancelFirst) { cancelFirst = false; f.cancel(); signal.throwIfAborted(); }
            return { env: { ASPNETCORE_URLS: 'http://localhost:5123' }, args: [] };
        },
    } });
    assert.equal(await f.api.debugActiveFile(), false);
    const failedBuild = f.calls.processes.find(call => call.args[0] === 'build');
    await waitForRemovedOutput(f, failedBuild.args[failedBuild.args.indexOf('--output') + 1]);
    assert(!fs.existsSync(failedBuild.args[failedBuild.args.indexOf('--output') + 1]));
    assert.deepEqual(f.calls.errors, []);
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.launches.length, 1);
});

test('evaluation failures do not silently turn a project file into an FBA', async t => {
    const f = fixture(t, { classify: async () => { throw new Error('MSBuild project evaluation failed'); } });
    assert.equal(await f.api.debugActiveFile(), false);
    assert.equal(f.calls.launches.length, 0);
    assert.equal(f.calls.commands.length, 0);
    assert.match(f.calls.errors[0], /MSBuild project evaluation failed/);
});

test('untrusted workspaces and cancelled saves execute no build or project evaluation', async t => {
    for (const options of [{ trusted: false }, { dirty: true, saveResult: false }]) {
        const f = fixture(t, options);
        assert.equal(await f.api.debugActiveFile(), false);
        assert.equal(f.calls.processes.length, 0);
        assert.equal(f.calls.classifications.length, 0);
    }
});

test('old SDK and incompatible SDK architecture stop before compilation', async t => {
    for (const options of [{ sdk: '9.0.400' }, { arch: 'x64' }]) {
        const f = fixture(t, options);
        assert.equal(await f.api.debugActiveFile(), false);
        assert.equal(f.calls.launches.length, 0);
        assert(!f.calls.processes.some(call => call.args[0] === 'build'));
        assert.equal(f.calls.errors.length, 1);
    }
});

test('failed SDK selection allocates no output and permits one corrected concurrent retry with its notification open', { timeout: 5000 }, async t => {
    let unavailable = true;
    let dismiss;
    const notification = new Promise(resolve => { dismiss = resolve; });
    t.after(() => dismiss());
    const f = fixture(t, { showErrorMessage: () => notification,
        classify: input => classifyWithMsbuild(input),
        runDotnet: async args => {
            if (args[0] === '--version') return unavailable
                ? { exitCode: 145, stderr: 'A compatible .NET SDK was not found. Requested SDK version: 99.0.100' }
                : { stdout: '10.0.402\n' };
            if (args[0] === '--info') return { stdout: 'Host:\n  Architecture: arm64\n' };
            assert.equal(args[0], 'build');
            const output = args[args.indexOf('--output') + 1];
            fs.writeFileSync(path.join(output, 'FileApp.dll'), 'corrected SDK DLL');
            fs.writeFileSync(path.join(output, 'FileApp.pdb'), 'corrected SDK PDB');
            return { stdout: JSON.stringify({ Properties: { OutputType: 'Exe', TargetFrameworkIdentifier: '.NETCoreApp' },
                Items: { FrameworkReference: [] } }) };
        } });
    fs.writeFileSync(f.source, '#:sdk Microsoft.NET.Sdk\nConsole.WriteLine("SDK selection");\n');
    const original = fs.readFileSync(f.source);
    assert.equal(await f.api.debugActiveFile(), false);
    assert.deepEqual(f.calls.processes.map(call => call.args), [['--version']]);
    assert.equal(f.calls.launches.length, 0);
    assert.deepEqual(fs.readFileSync(f.source), original);
    const outputBase = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps');
    assert.deepEqual(fs.existsSync(outputBase) ? fs.readdirSync(outputBase) : [], [], 'SDK rejection must allocate no output or receipt');
    assert(f.calls.logs.some(line => line.startsWith('Phase failed: Checking .NET SDK')));
    assert(!f.calls.logs.some(line => line.startsWith('Phase started: Preparing build output')));
    assert(!f.calls.logs.some(line => line.startsWith('Phase started: Starting netcoredbg')));
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /99\.0\.100/);

    unavailable = false;
    fs.writeFileSync(f.source, '#:sdk Microsoft.NET.Sdk\nConsole.WriteLine("corrected SDK retry");\n');
    f.document.isDirty = true;
    assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.processes.filter(call => call.args[0] === '--version').length, 2);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
    assert.equal(f.calls.launches.length, 1);
    assert.equal(f.calls.errors.length, 1, 'The undismissed SDK failure notification must not obstruct or duplicate retry');
    const output = f.calls.launches[0].config.__netcoredbgFileAppOutput;
    f.terminate(f.calls.launches[0].config);
    await f.api.dispose();
    assert(!fs.existsSync(output), 'Corrected SDK retry output must clean after matching termination and drain');
    assert.deepEqual(terminalOutputs(f), []);
});

test('a valid symlink or junction DOTNET_ROOT is compared by its physical directory', async t => {
    const f = fixture(t);
    const actualRoot = path.join(f.root, 'dotnet');
    const aliasRoot = path.join(f.root, 'linked-dotnet');
    fs.mkdirSync(actualRoot);
    try {
        fs.symlinkSync(actualRoot, aliasRoot, process.platform === 'win32' ? 'junction' : 'dir');
    } catch (error) {
        if (['EPERM', 'ENOTSUP'].includes(error.code)) return t.skip('Directory links are unavailable on this host');
        throw error;
    }
    f.dependencies.env.DOTNET_ROOT = aliasRoot;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.deepEqual(f.calls.errors, []);
});

test('repeated F5 during classification coalesces the same file build', async t => {
    let resume;
    const f = fixture(t, { classify: async () => {
        await new Promise(resolve => { resume = resolve; });
        return { kind: 'file', reason: 'standalone' };
    } });
    const first = f.api.debugActiveFile();
    while (!resume) await new Promise(resolve => setImmediate(resolve));
    const second = f.api.debugActiveFile();
    resume();
    assert.deepEqual(await Promise.all([first, second]), [true, true]);
    assert.equal(f.calls.classifications.length, 1);
    assert.equal(f.calls.launches.length, 1);
});

test('concurrent dirty-file commands share a cancelled save and permit a corrected retry', async t => {
    let completeSave;
    let saveProvider = () => new Promise(resolve => { completeSave = resolve; });
    const progress = [];
    const options = { dirty: true, reportProgress: value => progress.push(value),
        save: () => saveProvider() };
    const f = preparationFixture(t, options);
    t.after(() => completeSave?.(false));
    const requests = Array.from({ length: 3 }, () => f.api.debugActiveFile());
    await waitFor(() => completeSave, 'The shared dirty source save must be pending');
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.classifications.length, 0);
    assert.equal(f.calls.processes.length, 0);
    assert.deepEqual(progress, [{ message: 'Saving C# file' }], 'The shared save must report the cancellable save phase');
    assert.equal(f.timers.size, 0, 'The preparation timer must remain unarmed during save');
    completeSave(false);
    assert.deepEqual(await Promise.all(requests), [false, false, false]);
    assert.deepEqual(f.calls.errors, []);
    assert.equal(f.calls.launches.length, 0);
    assert.equal(f.calls.classifications.length, 0);
    assert.equal(f.calls.processes.length, 0);
    assert.equal(f.timers.size, 0, 'A false save must not arm an SDK preparation timer');
    assert(f.calls.logs.some(line => /^Phase not saved: Saving C# file /.test(line)));
    assert(!f.calls.logs.some(line => /^Phase completed: Saving C# file /.test(line)), 'A false save must not claim success');

    fs.writeFileSync(f.source, 'Console.WriteLine("corrected after save cancellation");\n');
    saveProvider = async () => { f.document.isDirty = false; return true; };
    assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
    assert.equal(f.calls.saves, 2, 'The retry must perform exactly one new save');
    assert.equal(f.calls.classifications.length, 1);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
    assert.equal(f.calls.launches.length, 1);
    assert.equal(f.document.isDirty, false);
    assert.deepEqual(f.calls.errors, []);
});

test('save progress retains a cancelled save for coalesced callers and a corrected retry', { timeout: 5000 }, async t => {
    let completeSave;
    const progress = [];
    const options = { dirty: true, reportProgress: value => progress.push(value.message),
        save: () => new Promise(resolve => { completeSave = resolve; }) };
    const f = fixture(t, options);
    let settled = 0;
    const requests = Array.from({ length: 3 }, () => f.api.debugActiveFile().then(result => { settled++; return result; }));
    try {
        await waitFor(() => completeSave, 'The original save provider must be pending');
        assert.deepEqual(progress, ['Saving C# file'], 'The save must be visible inside the cancellable command progress');
        assert.equal(f.calls.saves, 1);
        f.cancel();
        const repeated = f.api.debugActiveFile().then(result => { settled++; return result; });
        requests.push(repeated);
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(settled, 0, 'Cancel intent must not pretend the original save has settled');
        assert.equal(f.calls.saves, 1, 'Repeated calls must not compete with the outstanding editor save');
        assert.deepEqual(f.calls.classifications, []);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.launches, []);
        completeSave(true);
        assert.deepEqual(await Promise.all(requests), [false, false, false, false]);
        assert.deepEqual(f.calls.classifications, [], 'A late successful save must not continue the cancelled command');
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.errors, []);
        assert(f.calls.logs.some(line => /^Phase cancelled: Saving C# file /.test(line)));

        const savedText = 'Console.WriteLine("saved corrected revision");\n';
        options.save = async () => { fs.writeFileSync(f.source, savedText); f.document.isDirty = false; return true; };
        assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
        assert.equal(f.calls.saves, 2, 'The corrected retry must share exactly one new save');
        assert.equal(f.calls.classifications.length, 1);
        assert.equal(f.calls.classifications[0].text, savedText, 'Classification must capture text after the successful save');
        assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
        assert.equal(f.calls.launches.length, 1);
        assert.deepEqual(f.calls.errors, []);
    } finally {
        completeSave?.(false);
        await Promise.all(requests);
        await f.api.dispose();
    }
});

test('save progress observes a late rejection after Cancel without starting preparation or notifying', { timeout: 5000 }, async t => {
    let rejectSave;
    const progress = [];
    const f = fixture(t, { dirty: true, reportProgress: value => progress.push(value.message),
        save: () => new Promise((_resolve, reject) => { rejectSave = reject; }) });
    const operation = f.api.debugActiveFile();
    try {
        await waitFor(() => rejectSave, 'The save rejection must remain controllable');
        assert.deepEqual(progress, ['Saving C# file']);
        f.cancel();
        rejectSave(new Error('Original save provider rejected after Cancel'));
        assert.equal(await operation, false);
        assert.deepEqual(f.calls.classifications, []);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.launches, []);
        assert.deepEqual(f.calls.errors, [], 'Expected cancellation must remain quiet after a late save fault');
        assert(f.calls.logs.some(line => line.includes('Error observed during Saving C# file after cancellation:') &&
            line.includes('Original save provider rejected after Cancel')), 'The actual late save failure must remain diagnosed');
        assert(f.calls.logs.some(line => /^Phase cancelled: Saving C# file /.test(line)));
    } finally {
        rejectSave?.(new Error('Test released the original save provider'));
        await operation;
        await f.api.dispose();
    }
});

test('save progress cancellation before dispatch prevents the editor save and SDK work', async t => {
    let f;
    f = fixture(t, { dirty: true, reportProgress: value => { if (value.message === 'Saving C# file') f.cancel(); } });
    try {
        assert.equal(await f.api.debugActiveFile(), false);
        assert.equal(f.calls.saves, 0, 'Cancel reported before dispatch must prevent the editor save call');
        assert.deepEqual(f.calls.classifications, []);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.launches, []);
        assert.deepEqual(f.calls.errors, []);
    } finally { await f.api.dispose(); }
});

test('save progress honors an already cancelled notification before saving a dirty document', async t => {
    const f = fixture(t, { dirty: true, cancellationRequested: true });
    try {
        assert.equal(await f.api.debugActiveFile(), false);
        assert.equal(f.calls.saves, 0, 'An already cancelled progress token must precede the save provider');
        assert.deepEqual(f.calls.classifications, []);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.launches, []);
        assert.deepEqual(f.calls.errors, []);
    } finally { await f.api.dispose(); }
});

test('save progress excludes save time from preparation while retaining total phase duration', { timeout: 5000 }, async t => {
    let completeSave, completeClassification;
    const progress = [];
    const f = preparationFixture(t, { dirty: true, reportProgress: value => progress.push(value.message),
        save: () => new Promise(resolve => { completeSave = resolve; }),
        classify: () => new Promise(resolve => { completeClassification = resolve; }) });
    const operation = f.api.debugActiveFile();
    try {
        await waitFor(() => completeSave, 'The save must precede SDK preparation');
        assert.deepEqual(progress, ['Saving C# file']);
        assert.equal(f.timers.size, 0, 'The SDK preparation budget must not be armed during an editor-owned save');
        f.advance(1000);
        completeSave(true);
        await waitFor(() => completeClassification, 'The successful save must receive a fresh preparation budget');
        assert.equal(f.timers.size, 1);
        assert(f.calls.logs.some(line => line === 'Phase completed: Saving C# file (1000 ms; total 1000 ms)'));
        f.expire();
        completeClassification({ kind: 'file', reason: 'late classification after preparation expiry' });
        assert.equal(await operation, false);
        assert.equal(f.calls.processes.length, 0);
        assert.equal(f.calls.launches.length, 0);
        assert.equal(f.calls.errors.length, 1);
        assert.match(f.calls.errors[0], /Preparation timed out during Checking project membership after 100 ms \(limit 100 ms\)/);
        assert(f.calls.logs.some(line => line === 'Phase timed out: Checking project membership (100 ms; total 1100 ms)'));
        assert.equal(f.timers.size, 0);
    } finally {
        completeSave?.(false);
        completeClassification?.({ kind: 'file', reason: 'test release' });
        await operation;
        await f.api.dispose();
    }
});

test('save progress permits another file while a cancelled save retains its captured document', { timeout: 5000 }, async t => {
    let completeSave;
    const progress = [];
    const f = fixture(t, { dirty: true, reportProgress: value => progress.push(value.message),
        save: () => new Promise(resolve => { completeSave = resolve; }) });
    const operation = f.api.debugActiveFile();
    try {
        await waitFor(() => completeSave, 'The first file save must be outstanding');
        assert.deepEqual(progress, ['Saving C# file']);
        f.cancel();
        const otherSource = path.join(path.dirname(f.source), 'other.cs');
        const otherText = 'Console.WriteLine("independent other source");\n';
        fs.writeFileSync(otherSource, otherText);
        f.vscode.window.activeTextEditor = { document: {
            uri: { scheme: 'file', fsPath: otherSource }, isDirty: false,
            getText: () => otherText, save: async () => { assert.fail('The clean other document must not save'); },
        } };
        assert.equal(await f.api.debugActiveFile(), true, 'A different source must progress independently');
        assert.equal(f.calls.classifications.length, 1);
        assert.equal(f.calls.classifications[0].filePath, otherSource);
        assert.equal(f.calls.classifications[0].text, otherText);
        assert.equal(f.calls.launches.length, 1);
        const live = f.calls.launches[0].config;
        assert(fs.existsSync(live.program));
        completeSave(true);
        assert.equal(await operation, false);
        assert.equal(f.calls.classifications.length, 1, 'The first source must not resume using the new active document');
        assert.equal(f.calls.launches.length, 1);
        assert.equal(f.calls.stops.length, 0, 'Cancel intent for the first save must not stop the other session');
        assert(fs.existsSync(live.program));
        assert.deepEqual(f.calls.errors, []);
    } finally {
        completeSave?.(false);
        await operation;
        await f.api.dispose();
    }
});

test('web preparation cancellation cleans the failed output and permits one corrected retry while another file survives', { timeout: 10000 }, async t => {
    const options = { web: true };
    const f = fixture(t, options);
    const profile = JSON.stringify({ profiles: { Http: { commandName: 'Project', applicationUrl: 'http://localhost:5010' } } });
    const otherSource = path.join(path.dirname(f.source), 'other.cs');
    fs.writeFileSync(otherSource, 'Console.WriteLine("independent file");\n');
    fs.writeFileSync(path.join(path.dirname(otherSource), 'other.run.json'), profile);
    fs.writeFileSync(path.join(path.dirname(f.source), 'tool.run.json'), profile);
    f.vscode.window.activeTextEditor = { document: {
        uri: { scheme: 'file', fsPath: otherSource }, isDirty: false,
        getText: () => fs.readFileSync(otherSource, 'utf8'),
    } };
    assert.equal(await f.api.debugActiveFile(), true);
    const unrelated = f.calls.launches[0].config;
    f.vscode.window.activeTextEditor = { document: f.document };

    const reads = [];
    let gate = true;
    const paths = new Set([path.join(path.dirname(f.source), 'Properties', 'launchSettings.json'),
        path.join(path.dirname(f.source), 'tool.run.json')]);
    const originalRead = fs.promises.readFile;
    t.mock.method(fs.promises, 'readFile', (filename, settings) => {
        if (!gate || !paths.has(filename)) return originalRead(filename, settings);
        return new Promise((resolve, reject) => {
            let settled = false;
            const signal = settings?.signal;
            const finish = (complete, value) => {
                if (settled) return;
                settled = true;
                signal?.removeEventListener('abort', cancelled);
                complete(value);
            };
            const cancelled = () => finish(reject, Object.assign(new Error('Cooperative profile read cancelled'), { name: 'AbortError' }));
            reads.push({ settings, release: () => finish(resolve, profile) });
            signal?.addEventListener('abort', cancelled, { once: true });
            if (signal?.aborted) cancelled();
        });
    });
    const requests = Array.from({ length: 3 }, () => f.api.debugActiveFile());
    try {
        await waitFor(() => reads.length === 2, 'The real Web helper must be awaiting both profile reads');
        const failedBuild = f.calls.processes.find(call => call.args[0] === 'build' && call.args[1] === f.source);
        const failedOutput = failedBuild.args[failedBuild.args.indexOf('--output') + 1];
        f.cancel();
        let returned = false;
        const results = Promise.all(requests).then(value => { returned = true; return value; });
        await waitFor(() => returned, 'Cooperative profile read cancellation must release the coalesced file command');
        assert.deepEqual(await results, [false, false, false]);
        assert(reads.every(read => read.settings.encoding === 'utf8' && read.settings.signal === reads[0].settings.signal));
        assert.equal(reads[0].settings.signal.aborted, true);
        assert.deepEqual(f.calls.errors, []);
        assert.equal(f.calls.launches.length, 1, 'The cancelled Web preparation must start no new session');
        assert(f.calls.logs.some(line => /^Phase cancelled: Preparing web launch settings /.test(line)));
        await waitForRemovedOutput(f, failedOutput);
        assert(fs.existsSync(unrelated.program));
        assert.deepEqual(f.calls.stops, [], 'The unrelated file session must remain untouched');

        gate = false;
        f.document.isDirty = true;
        options.save = async () => { fs.writeFileSync(f.source, 'Console.WriteLine("corrected file");\n'); f.document.isDirty = false; return true; };
        assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
        assert.equal(f.calls.saves, 1);
        assert.equal(f.calls.processes.filter(call => call.args[0] === 'build' && call.args[1] === f.source).length, 2);
        assert.equal(f.calls.launches.length, 2, 'The corrected callers must share exactly one new session');
        assert.notEqual(f.calls.launches[1].config.__netcoredbgFileAppOutput, failedOutput);
        assert(fs.existsSync(unrelated.program));
        assert.deepEqual(f.calls.stops, []);
        assert.deepEqual(f.calls.errors, []);
    } finally {
        gate = false;
        f.cancel();
        for (const read of reads) read.release();
        await Promise.all(requests);
        await f.api.dispose();
    }
});

test('user build cancellation stays coalesced until child close and permits one dirty concurrent retry', async t => {
    let completeChild;
    let childPending = false;
    let firstBuild = true;
    const removals = [];
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        assert.equal(childPending, false, 'Cancellation must wait for the writing child to settle before cleanup');
        assert.deepEqual(terminalOutputs(f), [directory], 'Child closure must precede publication and queued deletion');
        removals.push(directory);
        await fs.promises.rm(directory, settings);
    }, save: async () => { f.document.isDirty = false; return true; } });
    const run = f.dependencies.runDotnet;
    f.dependencies.runDotnet = async (args, settings) => {
        const result = await run(args, settings);
        if (args[0] !== 'build' || !firstBuild) return result;
        firstBuild = false;
        childPending = true;
        return new Promise((_resolve, reject) => {
            completeChild = () => {
                childPending = false;
                reject(Object.assign(new Error('Direct child closed after cancellation'), { name: 'AbortError' }));
            };
        });
    };
    t.after(() => { completeChild?.(); f.dispose(); });
    const first = f.api.debugActiveFile();
    await waitFor(() => completeChild, 'The first build child must be pending');
    const cancelledBuild = f.calls.processes.find(call => call.args[0] === 'build');
    const directory = cancelledBuild.args[cancelledBuild.args.indexOf('--output') + 1];
    f.cancel();
    assert.equal(cancelledBuild.settings.signal.reason.name, 'AbortError');
    const requests = [first, f.api.debugActiveFile(), f.api.debugActiveFile()];
    let settled = 0;
    for (const request of requests) void request.then(() => { settled++; });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(settled, 0, 'Repeated commands must keep sharing the cancelled child until close');
    assert.equal(f.calls.classifications.length, 1);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
    assert(fs.existsSync(path.join(directory, 'FileApp.dll')));
    assert.deepEqual(removals, []);
    completeChild();
    assert.deepEqual(await Promise.all(requests), [false, false, false]);
    await waitFor(() => removals.length === 1 && !fs.existsSync(removals[0]) && terminalOutputs(f).length === 0,
        'The closed cancelled child must eventually release its queued output');
    assert.equal(removals.length, 1);
    assert.notEqual(removals[0], directory, 'The writing child output is retired before its first deletion');
    assert(!fs.existsSync(removals[0]));
    assert.deepEqual(terminalOutputs(f), []);
    assert(!fs.existsSync(directory));
    assert.equal(f.calls.launches.length, 0);
    assert.deepEqual(f.calls.errors, []);
    assert(f.calls.logs.some(line => /Phase cancelled: Building file-based app/.test(line)));

    fs.writeFileSync(f.source, 'Console.WriteLine("dirty retry after build cancellation");\n');
    f.document.isDirty = true;
    assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.document.isDirty, false);
    assert.equal(f.calls.classifications.length, 2);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 2);
    assert.equal(f.calls.launches.length, 1);
    assert.notEqual(f.calls.launches[0].config.__netcoredbgFileAppOutput, directory);
    assert(fs.existsSync(f.calls.launches[0].config.program));
    assert.deepEqual(f.calls.errors, []);
});

test('separate sessions have distinct output directories; only owned output is removed on termination', async t => {
    const f = fixture(t);
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(await f.api.debugActiveFile(), true);
    const first = f.calls.launches[0].config;
    const second = f.calls.launches[1].config;
    assert.notEqual(first.program, second.program);
    f.terminate({ __netcoredbgFileAppOutput: path.dirname(f.source) });
    assert(fs.existsSync(f.source), 'Arbitrary session paths must never be removed');
    f.terminate(first);
    for (let attempt = 0; attempt < 50 && fs.existsSync(first.program); attempt++) {
        await new Promise(resolve => setTimeout(resolve, 10));
    }
    assert(!fs.existsSync(first.program));
    assert(fs.existsSync(second.program));
});

test('failed debug launch removes its own output and does not reuse stale bytes', async t => {
    const f = fixture(t, { startResult: false });
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForRemovedOutput(f, f.calls.launches[0].config.__netcoredbgFileAppOutput);
    assert(!fs.existsSync(f.calls.launches[0].config.program));
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /editor did not start the netcoredbg debug session/);
    assert.match(f.calls.errors[0], /Debug Console/);
    assert(f.calls.logs.some(message => message.includes('editor did not start the netcoredbg debug session')));
});

test('first terminal deletion waits behind a published receipt while unrelated live output survives', async t => {
    let release;
    let removed;
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        removed = directory;
        await new Promise(resolve => { release = resolve; });
        await fs.promises.rm(directory, settings);
    } });
    t.after(() => release?.());
    assert.equal(await f.api.debugActiveFile(), true);
    const live = f.calls.launches[0].config;
    assert.equal(await f.api.debugActiveFile(), true);
    const terminal = f.calls.launches[1].config;
    f.terminate(terminal);
    await waitFor(() => release, 'The first terminal deletion must reach its provider');
    const [queued] = terminalOutputs(f);
    assert(queued, 'A complete terminal receipt must exist before the first deletion begins');
    assert.equal(removed, queued, 'The first deletion must target only the fixed queued output');
    const entry = path.dirname(queued);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(entry, 'record.json'), 'utf8')), {
        version: 1, kind: 'netcoredbg-terminal-output', entryId: path.basename(entry),
    });
    assert(fs.existsSync(path.join(queued, 'FileApp.dll')));
    assert(!fs.existsSync(terminal.__netcoredbgFileAppOutput));
    assert(fs.existsSync(live.program));
    release();
    await waitFor(() => !fs.existsSync(queued), 'The first deletion must complete from its published receipt');
    await waitFor(() => terminalOutputs(f).length === 0, 'The completed terminal receipt must be removed');
    assert(fs.existsSync(live.program));
});

test('a partial first deletion is recoverable by a fresh activation and late owner cleanup preserves replacements', async t => {
    let release;
    let firstDeletion;
    let removals = 0;
    const options = { removeOutput: async (directory, settings) => {
        removals++;
        firstDeletion = directory;
        await fs.promises.unlink(path.join(directory, 'FileApp.dll'));
        await new Promise(resolve => { release = resolve; });
        await fs.promises.rm(directory, settings);
    } };
    const first = fixture(t, options);
    t.after(() => release?.());
    await first.api.recoveryReady;
    assert.equal(await first.api.debugActiveFile(), true);
    const live = first.calls.launches[0].config;
    options.startResult = false;
    const declined = first.api.debugActiveFile();
    await waitFor(() => release, 'The first recursive deletion must be paused after a partial removal');
    const original = first.calls.launches[1].config.__netcoredbgFileAppOutput;
    const [queued] = terminalOutputs(first);
    assert(queued, 'Interruption during the first deletion must already have a terminal receipt');
    assert.equal(firstDeletion, queued);
    assert(!fs.existsSync(path.join(queued, 'FileApp.dll')));
    assert(fs.existsSync(path.join(queued, 'FileApp.pdb')));
    assert(!fs.existsSync(original));
    fs.mkdirSync(original);
    const replacement = path.join(original, 'unrelated.txt');
    fs.writeFileSync(replacement, 'preserve replacement');

    const second = fixture(t, { storage: first.context.globalStorageUri.fsPath });
    assert.equal((await second.api.recoveryReady).removed, 1);
    assert(!fs.existsSync(queued));
    assert(fs.existsSync(live.program));
    assert.equal(fs.readFileSync(replacement, 'utf8'), 'preserve replacement');
    assert.equal(await second.api.debugActiveFile(), true);
    const newLive = second.calls.launches[0].config;
    release();
    assert.equal(await declined, false);
    assert.equal(removals, 1, 'Late owner cleanup must not target the replacement original run');
    assert.deepEqual(terminalOutputs(first), []);
    assert.equal(first.calls.errors.length, 1, 'Only the original declined launch is a user-facing failure');
    assert(!first.calls.logs.some(line => line.includes('Could not clean file-app output')));
    assert.equal(fs.readFileSync(replacement, 'utf8'), 'preserve replacement');
    assert(fs.existsSync(live.program));
    assert(fs.existsSync(newLive.program));
});

test('an existing output with unavailable journal identity is retained and retried without direct deletion', async t => {
    let unavailable = true;
    const controlledActivate = activationWithRecoveryIO({ lstat: async (target, options) => {
        const stat = await fs.promises.lstat(target, options);
        if (unavailable && options?.bigint) Object.assign(stat, { ino: 0n, birthtimeNs: 0n, birthtimeMs: 0n });
        return stat;
    } });
    const removals = [];
    const options = { activate: controlledActivate, startResult: false,
        removeOutput: async (directory, settings) => { removals.push(directory); await fs.promises.rm(directory, settings); } };
    const f = fixture(t, options);
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const retained = f.calls.launches[0].config;
    assert(fs.existsSync(retained.program), 'Unpublishable existing output must remain available for a safe retry');
    assert.deepEqual(removals, [], 'A failed ownership journal must never fall back to deleting the original path');
    assert.deepEqual(terminalOutputs(f), []);
    assert(f.calls.logs.some(line => /Could not clean file-app output/.test(line)));
    assert(f.calls.logs.some(line => /publish.*terminal|terminal.*publish/i.test(line)));
    unavailable = false;
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => removals.length === 1 && !fs.existsSync(retained.__netcoredbgFileAppOutput) && terminalOutputs(f).length === 0,
        'The independent retry must publish and drain the retained output');
    assert.equal(removals.length, 1, 'The next command retries one retained terminal output');
    assert(!fs.existsSync(retained.__netcoredbgFileAppOutput));
    assert.deepEqual(terminalOutputs(f), []);
    assert(fs.existsSync(f.calls.launches[1].config.program));
    assert.equal(f.calls.errors.length, 1, 'Cleanup diagnostics must preserve the original declined launch error');
});

test('an incomplete tracked publication is retained when its original disappears before the move', async t => {
    let checks = 0;
    let removedOriginal;
    const controlledActivate = activationWithRecoveryIO({ lstat: async (target, options) => {
        if (!options?.bigint && /^run-[A-Za-z0-9]{6}$/.test(path.basename(target)) && ++checks === 2) {
            removedOriginal = target;
            await fs.promises.rm(target, { recursive: true });
        }
        return fs.promises.lstat(target, options);
    } });
    const removals = [];
    const options = { activate: controlledActivate, startResult: false,
        removeOutput: async directory => { removals.push(directory); } };
    const f = fixture(t, options);
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    assert.equal(removedOriginal, f.calls.launches[0].config.__netcoredbgFileAppOutput);
    assert(!fs.existsSync(removedOriginal));
    const staging = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps', 'terminal-cleanup-staging-v1');
    const [entryId] = fs.readdirSync(staging);
    assert(entryId, 'The interrupted publication must retain its tracked staging receipt');
    const marker = path.join(staging, entryId, 'record.json');
    assert.equal(JSON.parse(fs.readFileSync(marker, 'utf8')).entryId, entryId);
    assert(f.calls.logs.some(line => /publication is incomplete/.test(line)), 'An absent original must not silently complete a tracked publication');
    assert.deepEqual(removals, []);
    const failures = () => f.calls.logs.filter(line => line.includes('Could not clean file-app output')).length;
    assert.equal(failures(), 1);
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => failures() === 2, 'The independent retry must report its retained incomplete publication');
    assert.equal(failures(), 2, 'The next command must retain and retry this incomplete owned publication');
    assert(fs.existsSync(marker));
    assert.deepEqual(removals, []);
    assert(fs.existsSync(f.calls.launches[1].config.program));
    assert.equal(f.calls.errors.length, 1);
});

test('an already absent terminal output needs no deletion or journal and releases ownership', async t => {
    const removals = [];
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        removals.push(directory);
        await fs.promises.rm(directory, settings);
    } });
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    fs.rmSync(config.__netcoredbgFileAppOutput, { recursive: true });
    f.terminate(config);
    // Graceful disposal gives an observable drain boundary for the asynchronous termination callback.
    f.dispose();
    await waitFor(() => f.calls.disposals.output, 'Absent output cleanup must finish rather than retain disposal forever');
    assert.deepEqual(removals, [], 'An exact ENOENT must not invoke a deletion provider');
    assert.deepEqual(terminalOutputs(f), []);
    assert(!f.calls.logs.some(line => line.includes('Could not clean file-app output')));
    assertDisposed(f);
});

test('failed cleanup is retried by the next command without removing live session output', async t => {
    let locked = true;
    const removals = [];
    const options = { removeOutput: async (directory, settings) => {
        removals.push(directory);
        if (locked) throw Object.assign(new Error('Output remains locked after filesystem retries'), { code: 'EPERM' });
        await fs.promises.rm(directory, settings);
    } };
    const f = fixture(t, options);
    assert.equal(await f.api.debugActiveFile(), true);
    const active = f.calls.launches[0].config;
    options.startResult = false;
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const failed = f.calls.launches[1].config;
    const [retired] = terminalOutputs(f);
    assert(fs.existsSync(path.join(retired, 'FileApp.dll')), 'A terminal receipt retains failed output for later recovery');
    assert(f.calls.logs.some(line => line.includes('Could not clean file-app output')));
    locked = false;
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    const retried = f.calls.launches[2].config;
    await waitFor(() => !fs.existsSync(retired), 'The older terminal output must drain independently of the new launch');
    assert(!fs.existsSync(retired), 'The next command must retry the failed cleanup');
    assert(fs.existsSync(active.program), 'Recovery must preserve an earlier live session');
    assert(fs.existsSync(retried.program), 'The new session must retain its distinct output');
    assert.notEqual(retried.program, failed.program);
    assert.deepEqual(removals, [retired, retired], 'The initial deletion and retry must share the same published output');
    assert.equal(f.calls.errors.length, 1, 'Cleanup must preserve the original launch failure');
});

test('current terminal cleanup releases a failed build for coalesced dirty retry while disposal waits', { timeout: 5000 }, async t => {
    let releaseCleanup;
    const gate = new Promise(resolve => { releaseCleanup = resolve; });
    let retired;
    const removals = [];
    const options = { buildError: new Error('Current compiler failure'), showErrorMessage: () => new Promise(() => {}),
        removeOutput: async (directory, settings) => {
            removals.push(directory);
            if (!retired) { retired = directory; await gate; }
            await fs.promises.rm(directory, settings);
        } };
    const f = fixture(t, options);
    await f.api.recoveryReady;
    let returned = false;
    const failed = Promise.all([f.api.debugActiveFile(), f.api.debugActiveFile(), f.api.debugActiveFile()])
        .then(result => { returned = true; return result; });
    try {
        await waitFor(() => retired, 'The current failed output must enter deletion');
        const recoveryPasses = f.calls.logs.filter(line => line.startsWith('Terminal output recovery:')).length;
        await waitFor(() => returned, 'Current terminal deletion must not hold the failed command pending');
        assert.deepEqual(await failed, [false, false, false]);
        assert.equal(f.calls.errors.length, 1);
        assert.match(f.calls.errors[0], /Current compiler failure/);
        assert.deepEqual(terminalOutputs(f), [retired]);
        options.buildError = undefined;
        fs.writeFileSync(f.source, 'Console.WriteLine("corrected current failure");\n');
        f.document.isDirty = true;
        assert.deepEqual(await Promise.all([f.api.debugActiveFile(), f.api.debugActiveFile(), f.api.debugActiveFile()]),
            [true, true, true]);
        assert.equal(f.calls.saves, 1);
        assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 2);
        assert.equal(f.calls.launches.length, 1);
        const fresh = f.calls.launches[0].config;
        const firstBuild = f.calls.processes.find(call => call.args[0] === 'build');
        assert.notEqual(fresh.__netcoredbgFileAppOutput, firstBuild.args[firstBuild.args.indexOf('--output') + 1]);
        assert(fs.existsSync(fresh.program));
        assert.deepEqual(removals, [retired], 'A retry cannot duplicate an unsettled current deletion');
        assert.equal(f.calls.logs.filter(line => line.startsWith('Terminal output recovery:')).length, recoveryPasses);
        f.terminate(fresh);
        const disposal = observeDisposal(f);
        await waitFor(() => !fs.existsSync(fresh.__netcoredbgFileAppOutput) && terminalOutputs(f).length === 1,
            'Fresh session cleanup must proceed while the failed output stays held');
        assert.equal(disposal.settled, false);
        assert.equal(f.calls.disposals.started, 0);
        assert.equal(f.calls.disposals.terminated, 0);
        assert.equal(f.calls.disposals.output, 0, 'Actual cleanup keeps its diagnostics and drain ownership');
        releaseCleanup();
        await disposal.promise;
        assert.deepEqual(terminalOutputs(f), []);
        assert.equal(f.calls.errors.length, 1);
        assertDisposed(f);
    } finally {
        releaseCleanup();
        await failed;
        await f.api.dispose();
    }
});

test('current terminal cleanup releases cancellation only after child close and retains its deletion drain', { timeout: 5000 }, async t => {
    let closeChild;
    let writing = false;
    let releaseCleanup;
    const gate = new Promise(resolve => { releaseCleanup = resolve; });
    let deleting;
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        assert.equal(writing, false, 'A writing child must settle before terminal publication or deletion');
        deleting = directory;
        await gate;
        await fs.promises.rm(directory, settings);
    } });
    const run = f.dependencies.runDotnet;
    f.dependencies.runDotnet = async (args, settings) => {
        const result = await run(args, settings);
        if (args[0] !== 'build') return result;
        writing = true;
        return new Promise((_resolve, reject) => { closeChild = () => {
            writing = false;
            reject(Object.assign(new Error('Cancelled child closed'), { name: 'AbortError' }));
        }; });
    };
    const first = f.api.debugActiveFile();
    let requests;
    try {
        await waitFor(() => closeChild, 'The build child must be pending');
        f.cancel();
        let returned = false;
        requests = Promise.all([first, f.api.debugActiveFile(), f.api.debugActiveFile()])
            .then(result => { returned = true; return result; });
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(returned, false, 'Cancellation still coalesces the writing child until close');
        assert.equal(deleting, undefined);
        assert.deepEqual(terminalOutputs(f), []);
        closeChild();
        await waitFor(() => deleting, 'Child close must authorize terminal cleanup');
        await waitFor(() => returned, 'A closed cancelled child must release foreground callers before deletion settles');
        assert.deepEqual(await requests, [false, false, false]);
        assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
        assert.deepEqual(f.calls.launches, []);
        assert.deepEqual(f.calls.errors, []);
        const disposal = observeDisposal(f);
        assert.equal(disposal.settled, false);
        assert.equal(f.calls.disposals.output, 0);
        releaseCleanup();
        await disposal.promise;
        assert.deepEqual(terminalOutputs(f), []);
        assertDisposed(f);
    } finally {
        closeChild?.();
        releaseCleanup();
        await (requests || first);
        await f.api.dispose();
    }
});

for (const rejectStart of [false, true]) {
    test(`current terminal cleanup releases an editor ${rejectStart ? 'rejection' : 'decline'} without a session`, { timeout: 5000 }, async t => {
        let releaseCleanup;
        const gate = new Promise(resolve => { releaseCleanup = resolve; });
        let retired;
        let removals = 0;
        const options = { startResult: false,
            ...(rejectStart ? { startDebugging: async () => { throw new Error('Current adapter rejection'); } } : {}),
            removeOutput: async (directory, settings) => {
                removals++;
                if (!retired) { retired = directory; await gate; }
                await fs.promises.rm(directory, settings);
            } };
        const f = fixture(t, options);
        let returned = false;
        const failed = f.api.debugActiveFile().then(result => { returned = true; return result; });
        try {
            await waitFor(() => retired, 'The definitive editor failure must authorize deletion');
            await waitFor(() => returned, 'Editor failure reporting must not wait for terminal deletion');
            assert.equal(await failed, false);
            assert.equal(f.calls.errors.length, 1);
            assert.match(f.calls.errors[0], rejectStart ? /Current adapter rejection/ : /editor did not start/);
            options.startDebugging = undefined;
            options.startResult = true;
            assert.equal(await f.api.debugActiveFile(), true);
            assert.equal(f.calls.launches.length, 2);
            assert.notEqual(f.calls.launches[0].config.program, f.calls.launches[1].config.program);
            assert(fs.existsSync(f.calls.launches[1].config.program));
            assert.equal(removals, 1);
            assert.deepEqual(f.calls.stops, []);
            const disposal = observeDisposal(f);
            await waitFor(() => f.calls.stops.length === 1, 'Disposal must Stop only the corrected live session');
            assert.equal(disposal.settled, false);
            assert.equal(f.calls.disposals.output, 0);
            releaseCleanup();
            await disposal.promise;
            assert.equal(f.calls.errors.length, 1);
            assertDisposed(f);
        } finally {
            releaseCleanup();
            await failed;
            await f.api.dispose();
        }
    });
}

test('current terminal cleanup observes a late quiet rejection and permits recovery without changing live output', { timeout: 5000 }, async t => {
    let rejectCleanup;
    const gate = new Promise((_resolve, reject) => { rejectCleanup = reject; });
    let retired;
    let cancelFirst = true;
    let rejected = false;
    const removals = [];
    const f = fixture(t, {
        appendLine: line => { if (line.includes('Current late deletion rejection')) throw new Error('Diagnostic delivery failed'); },
        webSupport: { BUILD_METADATA_ARGS: [], parseBuildMetadata: () => ({}), prepareWebLaunch: async ({ signal }) => {
            if (cancelFirst) { cancelFirst = false; f.cancel(); signal.throwIfAborted(); }
        } },
        removeOutput: async (directory, settings) => {
            removals.push(directory);
            if (!retired) { retired = directory; await gate; }
            await fs.promises.rm(directory, settings);
        },
    });
    let returned = false;
    const cancelled = f.api.debugActiveFile().then(result => { returned = true; return result; });
    try {
        await waitFor(() => retired, 'The cancelled Web preparation must enter cleanup');
        await waitFor(() => returned, 'Quiet cancellation must return before its terminal deletion rejects');
        assert.equal(await cancelled, false);
        assert.deepEqual(f.calls.errors, []);
        assert.equal(await f.api.debugActiveFile(), true);
        const live = f.calls.launches[0].config;
        assert(fs.existsSync(live.program));
        rejected = true;
        rejectCleanup(new Error('Current late deletion rejection'));
        await waitFor(() => f.calls.logs.some(line => line.includes('Current late deletion rejection')),
            'The late rejection must remain observed when diagnostic delivery throws');
        // Cleanup has no more I/O after this diagnostic; let its final bookkeeping settle.
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(f.calls.errors, []);
        assert.deepEqual(terminalOutputs(f), [retired]);
        assert.equal(await f.api.debugActiveFile(), true);
        await waitFor(() => !fs.existsSync(path.dirname(retired)), 'A later command must recover the settled failed cleanup');
        assert.equal(removals.filter(directory => directory === retired).length, 2);
        assert(fs.existsSync(live.program));
        assert(fs.existsSync(f.calls.launches[1].config.program));
        assert.deepEqual(f.calls.errors, []);
    } finally {
        if (!rejected) rejectCleanup(new Error('Release current cleanup during test teardown'));
        await cancelled;
        await f.api.dispose();
    }
});

test('current terminal cleanup retains ownership while receipt publication is blocked', { timeout: 5000 }, async t => {
    let releasePublication;
    const gate = new Promise(resolve => { releasePublication = resolve; });
    let publishing;
    const activate = activationWithRecoveryIO({ lstat: async (target, settings) => {
        if (!publishing && settings?.bigint) { publishing = target; await gate; }
        return fs.promises.lstat(target, settings);
    } });
    const options = { activate, buildError: new Error('Failure before publication') };
    const f = fixture(t, options);
    await f.api.recoveryReady;
    let returned = false;
    const failed = f.api.debugActiveFile().then(result => { returned = true; return result; });
    try {
        await waitFor(() => publishing, 'Terminal ownership publication must reach its identity check');
        await waitFor(() => returned, 'Receipt publication must not hold the original failure pending');
        assert.equal(await failed, false);
        assert(fs.existsSync(publishing));
        assert.deepEqual(terminalOutputs(f), []);
        options.buildError = undefined;
        assert.equal(await f.api.debugActiveFile(), true);
        assert.notEqual(f.calls.launches[0].config.__netcoredbgFileAppOutput, publishing);
        const disposal = observeDisposal(f);
        await waitFor(() => f.calls.stops.length === 1, 'The corrected session must receive Stop during disposal');
        assert.equal(disposal.settled, false);
        assert.equal(f.calls.disposals.output, 0, 'An unpublished terminal output still owns the cleanup drain');
        releasePublication();
        await disposal.promise;
        assert(!fs.existsSync(publishing));
        assert.deepEqual(terminalOutputs(f), []);
        assert.equal(f.calls.errors.length, 1);
        assertDisposed(f);
    } finally {
        releasePublication();
        await failed;
        await f.api.dispose();
    }
});

test('current terminal cleanup preserves a captured session after an editor decline or rejection', async t => {
    for (const rejectStart of [false, true]) {
        let f;
        const removals = [];
        const options = { startDebugging: async (_folder, config) => {
            f.startSession(config);
            if (rejectStart) throw new Error('API rejected after session start');
            return false;
        }, removeOutput: async (directory, settings) => { removals.push(directory); await fs.promises.rm(directory, settings); } };
        f = fixture(t, options);
        assert.equal(await f.api.debugActiveFile(), false);
        const captured = f.calls.launches[0].config;
        assert(fs.existsSync(captured.program), 'A captured session requires actual termination before cleanup');
        assert.deepEqual(terminalOutputs(f), []);
        assert.deepEqual(removals, []);
        options.startDebugging = undefined;
        assert.equal(await f.api.debugActiveFile(), true);
        assert(fs.existsSync(captured.program));
        f.terminate(captured);
        await f.api.dispose();
        assert(!fs.existsSync(captured.__netcoredbgFileAppOutput));
        assert.equal(f.calls.errors.length, 1);
        assertDisposed(f);
    }
});

test('a blocked older terminal cleanup retry permits coalesced dirty launches and retains drain ownership', { timeout: 5000 }, async t => {
    let retired;
    let releaseCleanup;
    const cleanupGate = new Promise(resolve => { releaseCleanup = resolve; });
    const removals = [];
    const options = { dirty: true, startResult: false, removeOutput: async (directory, settings) => {
        removals.push(directory);
        if (!retired) {
            retired = directory;
            throw Object.assign(new Error('Initial terminal deletion is busy'), { code: 'EBUSY' });
        }
        if (directory === retired) await cleanupGate;
        await fs.promises.rm(directory, settings);
    } };
    const f = fixture(t, options);
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    assert.deepEqual(terminalOutputs(f), [retired]);
    const originalDll = fs.readFileSync(path.join(retired, 'FileApp.dll'));
    const initialBuilds = f.calls.processes.filter(call => call.args[0] === 'build').length;
    const completedPasses = f.calls.logs.filter(line => line.startsWith('Terminal output recovery:')).length;
    options.startResult = true;
    fs.writeFileSync(f.source, 'Console.WriteLine("fresh dirty retry");\n');
    let settled = false;
    const commands = Promise.all([f.api.debugActiveFile(), f.api.debugActiveFile(), f.api.debugActiveFile()])
        .then(value => { settled = true; return value; });
    try {
        await waitFor(() => removals.filter(directory => directory === retired).length === 2,
            'One local retry must enter the held deletion provider');
        await waitFor(() => settled, 'Older terminal deletion must not hold three fresh same-file callers pending');
        assert.deepEqual(await commands, [true, true, true]);
        assert.equal(f.calls.saves, 2, 'Three dirty callers share one new save');
        assert.equal(f.calls.launches.length, 2, 'Three dirty callers share one new session');
        assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, initialBuilds + 1);
        const fresh = f.calls.launches[1].config;
        assert.notEqual(fresh.program, f.calls.launches[0].config.program);
        assert(fs.existsSync(fresh.program));
        assert.deepEqual(fs.readFileSync(path.join(retired, 'FileApp.dll')), originalDll);
        assert.equal(await f.api.debugActiveFile(), true, 'The settled command releases its same-file pending entry');
        const later = f.calls.launches[2].config;
        assert.notEqual(later.program, fresh.program);
        assert(fs.existsSync(fresh.program) && fs.existsSync(later.program));
        assert.deepEqual(removals, [retired, retired], 'Further commands cannot duplicate the held deletion');
        assert.equal(f.calls.logs.filter(line => line.startsWith('Terminal output recovery:')).length, completedPasses,
            'The local retry must not introduce a competing global recovery pass');
        f.terminate(fresh);
        f.terminate(later);
        await waitFor(() => !fs.existsSync(fresh.__netcoredbgFileAppOutput) && !fs.existsSync(later.__netcoredbgFileAppOutput)
            && terminalOutputs(f).length === 1 && terminalOutputs(f)[0] === retired,
            'The fresh sessions clean independently while the older deletion stays held');
        const disposal = observeDisposal(f);
        assert.equal(disposal.settled, false);
        assert.equal(f.calls.disposals.output, 0, 'An unsettled older deletion still owns diagnostics and listeners');
        assert.equal(f.calls.disposals.started, 0);
        assert.equal(f.calls.disposals.terminated, 0);
        releaseCleanup();
        await disposal.promise;
        assert(!fs.existsSync(retired));
        assert.deepEqual(terminalOutputs(f), []);
        assert.equal(removals.filter(directory => directory === retired).length, 2);
        assert.equal(f.calls.errors.length, 1, 'Background cleanup must preserve the original launch failure');
        assertDisposed(f);
    } finally {
        releaseCleanup();
        await commands;
        f.dispose();
        await f.api.disposalReady;
    }
});

test('a late rejected terminal retry stays observed and recoverable without changing fresh launches', { timeout: 5000 }, async t => {
    let retired;
    let rejectCleanup;
    const cleanupGate = new Promise((_resolve, reject) => { rejectCleanup = reject; });
    let rejected = false;
    let hold = true;
    const removals = [];
    const options = { startResult: false,
        appendLine: line => { if (line.includes('Late terminal deletion failure')) throw new Error('Diagnostic delivery failed'); },
        removeOutput: async (directory, settings) => {
            removals.push(directory);
            if (!retired) {
                retired = directory;
                throw Object.assign(new Error('Initial terminal deletion is busy'), { code: 'EBUSY' });
            }
            if (directory === retired && hold) await cleanupGate;
            await fs.promises.rm(directory, settings);
        },
    };
    const f = fixture(t, options);
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const originalErrors = [...f.calls.errors];
    options.startResult = true;
    let settled = false;
    const command = f.api.debugActiveFile().then(value => { settled = true; return value; });
    try {
        await waitFor(() => removals.filter(directory => directory === retired).length === 2,
            'The local retry must wait inside its deletion provider');
        await waitFor(() => settled, 'A fresh launch must complete before an older retry rejects');
        assert.equal(await command, true);
        const fresh = f.calls.launches[1].config;
        assert(fs.existsSync(fresh.program) && fs.existsSync(path.join(retired, 'FileApp.dll')));
        rejected = true;
        rejectCleanup(new Error('Late terminal deletion failure'));
        await waitFor(() => f.calls.logs.some(line => line.includes('Late terminal deletion failure')),
            'A late deletion rejection must remain observed even when diagnostic delivery throws');
        assert.deepEqual(f.calls.errors, originalErrors, 'The late rejection must not replace or add a launch notification');
        assert.deepEqual(terminalOutputs(f), [retired]);
        assert(fs.existsSync(fresh.program));
        hold = false;
        assert.equal(await f.api.debugActiveFile(), true);
        await waitFor(() => !fs.existsSync(retired), 'A later command must retry and drain the retained terminal receipt');
        assert.equal(removals.filter(directory => directory === retired).length, 3);
        assert.deepEqual(f.calls.errors, originalErrors);
        assert(fs.existsSync(fresh.program), 'Recovering the older output must preserve the earlier fresh live session');
        assert(fs.existsSync(f.calls.launches[2].config.program));
    } finally {
        if (!rejected) rejectCleanup(new Error('Release held deletion during test cleanup'));
        await command;
        f.dispose();
        await f.api.disposalReady;
    }
});

test('overlapping cleanup requests share one deletion and release ownership only after success', async t => {
    let release;
    const removals = [];
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        removals.push(directory);
        await new Promise(resolve => { release = resolve; });
        await fs.promises.rm(directory, settings);
    } });
    assert.equal(await f.api.debugActiveFile(), true);
    const config = f.calls.launches[0].config;
    f.terminate(config);
    f.terminate(config);
    await waitFor(() => release, 'The shared deletion must enter its provider');
    assert.equal(removals.length, 1);
    assert.deepEqual(terminalOutputs(f), [removals[0]]);
    assert(fs.existsSync(path.join(removals[0], 'FileApp.dll')));
    assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
    release();
    await waitFor(() => !fs.existsSync(removals[0]), 'The shared queued cleanup must complete');
    await waitFor(() => terminalOutputs(f).length === 0, 'Successful shared cleanup must remove its journal');
    await new Promise(resolve => setImmediate(resolve));
    f.terminate(config);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(removals.length, 1, 'Successful cleanup releases ownership');
});

test('cleanup never submits arbitrary paths to filesystem deletion', async t => {
    const removals = [];
    const f = fixture(t, { removeOutput: async directory => { removals.push(directory); } });
    assert.equal(await f.api.debugActiveFile(), true);
    const active = f.calls.launches[0].config;
    const unowned = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps', 'unowned');
    fs.mkdirSync(unowned, { recursive: true });
    const sentinel = path.join(unowned, 'keep.txt');
    fs.writeFileSync(sentinel, 'unowned output');
    f.terminate({ __netcoredbgFileAppOutput: path.dirname(f.source) });
    f.terminate({ __netcoredbgFileAppOutput: unowned });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(removals, []);
    assert(fs.existsSync(f.source));
    assert(fs.existsSync(sentinel));
    assert(fs.existsSync(active.program));
});

test('cleanup logging failure preserves the original result and failed output can still recover', async t => {
    let locked = true;
    const options = { startResult: false,
        appendLine: line => { if (line.includes('Could not clean file-app output')) throw new Error('Output channel disposed'); },
        removeOutput: async (directory, settings) => {
            if (locked) throw Object.assign(new Error('Output locked'), { code: 'EPERM' });
            await fs.promises.rm(directory, settings);
        },
    };
    const f = fixture(t, options);
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const [retired] = terminalOutputs(f);
    assert(fs.existsSync(path.join(retired, 'FileApp.dll')));
    assert.equal(f.calls.errors.length, 1, 'A failed cleanup log must not replace the launch error');
    locked = false;
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(retired), 'The observed retry must recover despite earlier diagnostic failure');
    assert(!fs.existsSync(retired));
    assert(fs.existsSync(f.calls.launches[1].config.program));
});

test('persistent cleanup failures permit fresh launches and retry only one older output per command', async t => {
    const removals = [];
    const options = { startResult: false, removeOutput: async directory => {
        removals.push(directory);
        throw Object.assign(new Error('Output locked after filesystem retries'), { code: 'EPERM' });
    } };
    const f = fixture(t, options);
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    assert.equal(await f.api.debugActiveFile(), false);
    const failures = () => f.calls.logs.filter(line => line.includes('Could not clean file-app output')).length;
    await waitFor(() => failures() === 3, 'Both current-output failures and the independent older retry must settle');
    await new Promise(resolve => setImmediate(resolve));
    const retained = terminalOutputs(f);
    assert.equal(retained.length, 2);
    options.startResult = true;
    const before = removals.length;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => failures() === 4, 'The command must finish exactly one independent older retry');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(removals.length, before + 1, 'A command must not sweep the entire failed-output backlog');
    const first = removals.at(-1);
    assert(retained.includes(first));
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => failures() === 5, 'The next command must finish one further independent retry');
    assert.equal(removals.length, before + 2);
    const second = retained.find(directory => directory !== first);
    assert.equal(removals.at(-1), second, 'A locked output must not starve another failed output');
    assert.equal(f.calls.errors.length, 2, 'Recovery failure must not become an additional launch error');
    assert(fs.existsSync(path.join(first, 'FileApp.dll')));
    assert(fs.existsSync(path.join(second, 'FileApp.dll')));
    for (const launch of f.calls.launches.slice(2)) assert(fs.existsSync(launch.config.program));
});

test('cleanup failure preserves quiet cancellation and the next command recovers its output', async t => {
    let locked = true;
    let cancelFirst = true;
    const f = fixture(t, {
        removeOutput: async (directory, settings) => {
            if (locked) throw Object.assign(new Error('Output locked'), { code: 'EPERM' });
            await fs.promises.rm(directory, settings);
        },
        webSupport: {
            BUILD_METADATA_ARGS: [], parseBuildMetadata: () => ({ isWebServer: true }),
            prepareWebLaunch: async ({ signal }) => {
                if (cancelFirst) { cancelFirst = false; f.cancel(); signal.throwIfAborted(); }
            },
        },
    });
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const [failedOutput] = terminalOutputs(f);
    assert(fs.existsSync(path.join(failedOutput, 'FileApp.dll')));
    assert.deepEqual(f.calls.errors, []);
    locked = false;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(failedOutput), 'The quiet cancelled output must recover in the independent retry');
    assert(!fs.existsSync(failedOutput));
    assert.deepEqual(f.calls.errors, []);
    assert.equal(f.calls.launches.length, 1);
});

test('a fresh activation recovers a terminal receipt while preserving another host live output', async t => {
    let locked = true;
    const options = { removeOutput: async (directory, settings) => {
        if (locked) throw Object.assign(new Error('Deletion locked'), { code: 'EPERM' });
        await fs.promises.rm(directory, settings);
    } };
    const first = fixture(t, options);
    await first.api.recoveryReady;
    assert.equal(await first.api.debugActiveFile(), true);
    const live = first.calls.launches[0].config;
    options.startResult = false;
    assert.equal(await first.api.debugActiveFile(), false);
    await waitForFailedCleanup(first);
    const failed = first.calls.launches[1].config;
    const [retired] = terminalOutputs(first);
    assert(fs.existsSync(path.join(retired, 'FileApp.dll')));
    const second = fixture(t, { storage: first.context.globalStorageUri.fsPath });
    const stats = await second.api.recoveryReady;
    assert.equal(stats.removed, 1);
    assert(!fs.existsSync(retired));
    assert(fs.existsSync(live.program));
    assert.deepEqual(second.calls.errors, []);
    // A stale in-memory receipt must not delete a replacement at its original run path.
    fs.mkdirSync(path.dirname(failed.program), { recursive: true });
    const replacement = path.join(path.dirname(failed.program), 'unrelated.txt');
    fs.writeFileSync(replacement, 'preserve replacement');
    locked = false;
    options.startResult = true;
    assert.equal(await first.api.debugActiveFile(), true);
    assert(fs.existsSync(replacement));
    assert(fs.existsSync(live.program));
});

test('background recovery does not hold a fresh file command pending', async t => {
    const first = fixture(t, { startResult: false, removeOutput: async () => { throw new Error('Locked output'); } });
    await first.api.recoveryReady;
    assert.equal(await first.api.debugActiveFile(), false);
    await first.api.dispose();
    const [retired] = terminalOutputs(first);
    let release;
    const second = fixture(t, { storage: first.context.globalStorageUri.fsPath, removeOutput: async (directory, settings) => {
        await new Promise(resolve => { release = resolve; });
        await fs.promises.rm(directory, settings);
    } });
    await waitFor(() => release, 'A recovery deletion must be pending');
    assert.equal(await second.api.debugActiveFile(), true);
    assert(fs.existsSync(second.calls.launches[0].config.program));
    assert(fs.existsSync(retired));
    release();
    await second.api.recoveryReady;
    assert(!fs.existsSync(retired));
    assert(fs.existsSync(second.calls.launches[0].config.program));
});

test('command recovery retries a previous owner receipt after a busy activation without restarting', async t => {
    const previous = await retainedTerminalOutput(t);
    let locked = true;
    const removals = [];
    const f = fixture(t, { storage: previous.owner.context.globalStorageUri.fsPath,
        removeOutput: async (directory, settings) => {
            removals.push(directory);
            if (locked) throw Object.assign(new Error('Startup output is busy'), { code: 'EBUSY' });
            await fs.promises.rm(directory, settings);
        },
    });
    assert.equal((await f.api.recoveryReady).removed, 0);
    assert.deepEqual(removals, [previous.output]);
    locked = false;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(previous.entry), 'The next command must recover the unlocked previous owner output');
    assert.deepEqual(removals, [previous.output, previous.output]);
    assert(fs.existsSync(f.calls.launches[0].config.program));
    assert.deepEqual(f.calls.errors, []);
});

for (const staging of [false, true]) {
    test(`command recovery notices a later ${staging ? 'complete staging' : 'ready'} receipt and preserves unrelated paths`, async t => {
        const f = fixture(t);
        await f.api.recoveryReady;
        const later = await retainedTerminalOutput(t, { staging });
        const name = path.basename(later.entry);
        const queue = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps',
            staging ? 'terminal-cleanup-staging-v1' : 'terminal-cleanup-v1');
        fs.mkdirSync(queue, { recursive: true });
        const entry = path.join(queue, name);
        fs.renameSync(later.entry, entry);
        const base = path.dirname(queue);
        const guards = [path.join(base, 'unmarked', 'sentinel.txt'),
            path.join(base, 'a'.repeat(24), 'run-Abc123', 'replacement.txt'), path.join(f.root, 'external-sentinel.txt')];
        for (const guard of guards) { fs.mkdirSync(path.dirname(guard), { recursive: true }); fs.writeFileSync(guard, 'preserve'); }
        const incomplete = path.join(base, 'terminal-cleanup-staging-v1', '11111111-1111-4111-8111-111111111111');
        fs.mkdirSync(incomplete, { recursive: true });
        const marker = path.join(incomplete, 'record.json');
        fs.writeFileSync(marker, JSON.stringify({ version: 1, kind: 'netcoredbg-terminal-output', entryId: path.basename(incomplete) }));
        guards.push(marker);
        const snapshots = guards.map(guard => fs.readFileSync(guard));
        assert.equal(await f.api.debugActiveFile(), true);
        await waitFor(() => !fs.existsSync(entry), 'A receipt arriving after activation must recover on the next command');
        for (let index = 0; index < guards.length; index++) assert.deepEqual(fs.readFileSync(guards[index]), snapshots[index]);
        assert(fs.existsSync(f.calls.launches[0].config.program));
        assert.deepEqual(f.calls.errors, []);
    });
}

test('command recovery is background work and concurrent new files share its blocked pass without queuing another', async t => {
    const previous = await retainedTerminalOutput(t);
    let unlocked = false;
    let release;
    const removals = [];
    const f = fixture(t, { storage: previous.owner.context.globalStorageUri.fsPath,
        removeOutput: async (directory, settings) => {
            removals.push(directory);
            if (!unlocked) throw Object.assign(new Error('Startup output is busy'), { code: 'EBUSY' });
            if (directory === previous.output) await new Promise(resolve => { release = resolve; });
            await fs.promises.rm(directory, settings);
        },
    });
    t.after(() => { f.dispose(); release?.(); });
    await f.api.recoveryReady;
    unlocked = true;
    const first = f.api.debugActiveFile();
    const duplicate = f.api.debugActiveFile();
    f.vscode.window.activeTextEditor = { document: { ...f.document, uri: { scheme: 'file', fsPath: path.join(f.root, 'other.cs') } } };
    assert.equal(await f.api.debugActiveFile(), true);
    assert.deepEqual(await Promise.all([first, duplicate]), [true, true]);
    await waitFor(() => release, 'The command must have started another bounded recovery pass');
    assert.equal(f.calls.launches.length, 2, 'Same-file callers coalesce while the separate file still launches');
    assert.deepEqual(removals, [previous.output, previous.output]);
    assert(fs.existsSync(previous.output));
    release();
    await waitFor(() => !fs.existsSync(previous.entry), 'The shared background pass must finish');
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(removals.length, 2, 'Callers arriving during a pass must not queue a later pass');
    assert(f.calls.launches.every(launch => fs.existsSync(launch.config.program)));
});

test('command recovery drains before disposal releases observers and a reentrant provider cannot restart work', async t => {
    const previous = await retainedTerminalOutput(t);
    let unlocked = false;
    let release;
    let releaseSdk;
    let f;
    f = fixture(t, { storage: previous.owner.context.globalStorageUri.fsPath,
        findDotnet: () => new Promise(resolve => { releaseSdk = resolve; }),
        removeOutput: async (directory, settings) => {
            if (!unlocked) throw Object.assign(new Error('Startup output is busy'), { code: 'EBUSY' });
            f.dispose();
            releaseSdk({ executable: 'dotnet', root: f.root });
            await new Promise(resolve => { release = resolve; });
            await fs.promises.rm(directory, settings);
        },
    });
    t.after(() => { f.dispose(); releaseSdk?.({ executable: 'dotnet', root: f.root }); release?.(); });
    await f.api.recoveryReady;
    unlocked = true;
    const command = f.api.debugActiveFile();
    await waitFor(() => release, 'The recovery provider must reenter disposal with a registered owner');
    const disposal = observeDisposal(f);
    assert.equal(await command, false);
    assert.equal(disposal.settled, false, 'Draining the foreground command must not finish background recovery');
    assert.equal(f.calls.disposals.output, 0, 'The background pass must retain diagnostics after foreground work drains');
    assert.equal(f.calls.disposals.started, 0);
    assert.equal(f.calls.disposals.terminated, 0);
    assert.equal(await f.api.debugActiveFile(), false);
    assert.deepEqual(f.calls.processes, []);
    assert.deepEqual(f.calls.launches, []);
    assert.deepEqual(f.calls.errors, []);
    release();
    await waitFor(() => f.calls.disposals.output, 'The settled pass must release all disposed resources');
    await disposal.promise;
    assertDisposed(f);
    assert(!fs.existsSync(previous.entry));
});

test('command recovery leaves receipts untouched for invalid, untrusted and disposed requests', async t => {
    const f = fixture(t);
    await f.api.recoveryReady;
    const later = await retainedTerminalOutput(t);
    const queue = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps', 'terminal-cleanup-v1');
    fs.mkdirSync(queue, { recursive: true });
    const entry = path.join(queue, path.basename(later.entry));
    fs.renameSync(later.entry, entry);
    f.vscode.workspace.isTrusted = false;
    assert.equal(await f.api.debugActiveFile(), false);
    f.vscode.workspace.isTrusted = true;
    for (const document of [undefined, { uri: { scheme: 'untitled', fsPath: 'tool.cs' } },
        { uri: { scheme: 'file', fsPath: path.join(f.root, 'notes.txt') } }]) {
        f.vscode.window.activeTextEditor = document ? { document } : undefined;
        assert.equal(await f.api.debugActiveFile(), false);
    }
    f.dispose();
    assert.equal(await f.api.debugActiveFile(), false);
    await new Promise(resolve => setImmediate(resolve));
    assert(fs.existsSync(path.join(entry, 'output', 'FileApp.dll')));
    assert(fs.existsSync(path.join(entry, 'record.json')));
    assert.deepEqual(f.calls.processes, []);
});

test('command recovery does not start accepted activation work after immediate disposal', async t => {
    const previous = await retainedTerminalOutput(t);
    const removals = [];
    const f = fixture(t, { storage: previous.owner.context.globalStorageUri.fsPath,
        removeOutput: async (directory, settings) => { removals.push(directory); await fs.promises.rm(directory, settings); },
    });
    f.dispose();
    assert.deepEqual(await f.api.recoveryReady, { scanned: 0, attempted: 0, removed: 0 });
    assert.deepEqual(removals, []);
    assert(fs.existsSync(path.join(previous.output, 'FileApp.dll')));
    assert(fs.existsSync(path.join(previous.entry, 'record.json')));
    assert.equal(await f.api.debugActiveFile(), false);
    assert.deepEqual(f.calls.processes, []);
    assertDisposed(f);
});

test('command recovery chooses a local failed cleanup instead of introducing another global attempt', async t => {
    let locked = true;
    const removals = [];
    const options = { startResult: false, removeOutput: async (directory, settings) => {
        removals.push(directory);
        if (locked) throw Object.assign(new Error('Terminal output is busy'), { code: 'EBUSY' });
        await fs.promises.rm(directory, settings);
    } };
    const f = fixture(t, options);
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const [retained] = terminalOutputs(f);
    const completedPasses = f.calls.logs.filter(line => line.startsWith('Terminal output recovery:')).length;
    options.startResult = true;
    locked = false;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(retained), 'The selected local retry must finish without a global pass');
    assert.deepEqual(removals, [retained, retained]);
    assert(!fs.existsSync(retained));
    assert.equal(f.calls.logs.filter(line => line.startsWith('Terminal output recovery:')).length, completedPasses,
        'Selecting one local retry must not also start a global pass');
    assert(fs.existsSync(f.calls.launches[1].config.program));
});

test('command recovery does not wait for or duplicate a local retry while a global pass is already active', async t => {
    const previous = await retainedTerminalOutput(t);
    let release;
    let localLocked = true;
    const removals = [];
    const options = { storage: previous.owner.context.globalStorageUri.fsPath, startResult: false,
        removeOutput: async (directory, settings) => {
            removals.push(directory);
            if (directory === previous.output) await new Promise(resolve => { release = resolve; });
            else if (localLocked) throw Object.assign(new Error('Local terminal output is busy'), { code: 'EBUSY' });
            await fs.promises.rm(directory, settings);
        },
    };
    const f = fixture(t, options);
    t.after(() => { f.dispose(); release?.(); });
    await waitFor(() => release, 'The initial foreign receipt recovery must be pending');
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForFailedCleanup(f);
    const local = terminalOutputs(f).find(directory => directory !== previous.output);
    assert(local && fs.existsSync(local));
    localLocked = false;
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.deepEqual(removals, [previous.output, local], 'A foreground command must not compete with an active global pass');
    assert(fs.existsSync(local));
    release();
    await f.api.recoveryReady;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(local), 'After the global pass, one local background retry must drain');
    assert.deepEqual(removals, [previous.output, local, local]);
    assert(!fs.existsSync(local));
});

test('command recovery does not introduce a pass while terminal session cleanup is in flight', async t => {
    let release;
    let gated;
    const removals = [];
    const f = fixture(t, { removeOutput: async (directory, settings) => {
        removals.push(directory);
        if (!gated) {
            gated = directory;
            await new Promise(resolve => { release = resolve; });
        }
        await fs.promises.rm(directory, settings);
    } });
    t.after(() => { f.dispose(); release?.(); });
    assert.equal(await f.api.debugActiveFile(), true);
    await f.api.recoveryReady;
    f.terminate(f.calls.launches[0].config);
    await waitFor(() => release, 'The owned terminal cleanup must be blocked');
    const later = await retainedTerminalOutput(t);
    const queue = path.join(f.context.globalStorageUri.fsPath, 'file-based-apps', 'terminal-cleanup-v1');
    const foreign = path.join(queue, path.basename(later.entry));
    fs.renameSync(later.entry, foreign);
    assert.equal(await f.api.debugActiveFile(), true);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(removals, [gated], 'A new command must not duplicate an active terminal deletion or begin a foreign one');
    assert(fs.existsSync(path.join(foreign, 'output', 'FileApp.dll')));
    release();
    await waitFor(() => !fs.existsSync(path.dirname(gated)), 'The terminal cleanup must finish');
    // The kernel can remove the entry before its rmdir completion drains the
    // owning cleanup Promise. Let that I/O completion settle before the retry.
    await fs.promises.readdir(queue);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(foreign), 'A subsequent command can now recover the foreign receipt');
    assert.deepEqual(f.calls.errors, []);
});

test('command recovery survives a later rejection and throwing completion diagnostics without changing fresh launches', async t => {
    const previous = await retainedTerminalOutput(t);
    const nativeRecovery = require('./recovery.cjs');
    const runtimeModule = { exports: {} };
    let passes = 0;
    vm.runInNewContext(fs.readFileSync(require.resolve('./runtime.cjs'), 'utf8'), {
        module: runtimeModule, process, AbortController, setTimeout, clearTimeout,
        require: name => name === './recovery.cjs' ? { createRecovery: settings => {
            const manager = nativeRecovery.createRecovery(settings);
            return { ...manager, recover: () => ++passes === 2
                ? Promise.reject(new Error('Unexpected later recovery rejection')) : manager.recover() };
        } } : require(name),
    });
    let locked = true;
    const f = fixture(t, { activate: runtimeModule.exports.activate, storage: previous.owner.context.globalStorageUri.fsPath,
        appendLine: line => { if (line.startsWith('Terminal output recovery:')) throw new Error('Completion diagnostic failed'); },
        removeOutput: async (directory, settings) => {
            if (locked) throw Object.assign(new Error('Startup output is busy'), { code: 'EBUSY' });
            await fs.promises.rm(directory, settings);
        },
    });
    const initial = f.api.recoveryReady;
    assert.deepEqual(JSON.parse(JSON.stringify(await initial)), { scanned: 1, attempted: 1, removed: 0 });
    locked = false;
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => f.calls.logs.some(line => line.includes('Unexpected later recovery rejection')),
        'A rejected background pass must log quietly');
    assert(fs.existsSync(previous.output));
    assert.equal(f.api.recoveryReady, initial, 'The initial completion API must keep its original identity');
    assert.equal(await f.api.debugActiveFile(), true);
    await waitFor(() => !fs.existsSync(previous.entry), 'A later command must still be able to start a fresh pass');
    assert.deepEqual(f.calls.errors, []);
    assert(f.calls.launches.every(launch => fs.existsSync(launch.config.program)));
});

test('an unexpected recovery rejection preserves a stable zero-count result without notifying', async t => {
    const f = fixture(t);
    await f.api.recoveryReady;
    const module = { exports: {} };
    vm.runInNewContext(fs.readFileSync(require.resolve('./runtime.cjs'), 'utf8'), {
        module, process, AbortController, setTimeout, clearTimeout,
        require: name => name === './recovery.cjs' ? { createRecovery: () => ({
            recover: () => Promise.reject(new Error('Unexpected recovery failure')),
        }) } : require(name),
    });
    const api = module.exports.activate(f.context, f.dependencies);
    assert.deepEqual(JSON.parse(JSON.stringify(await api.recoveryReady)), { scanned: 0, attempted: 0, removed: 0 });
    assert(f.calls.logs.some(line => line.includes('Unexpected recovery failure')));
    assert.deepEqual(f.calls.errors, []);
});

test('a new activation preserves output whose cancelled editor start is still unresolved', async t => {
    let settle;
    const first = fixture(t, { startDebugging: () => new Promise(resolve => { settle = resolve; }) });
    await first.api.recoveryReady;
    const operation = first.api.debugActiveFile();
    await waitFor(() => settle, 'The editor start must be pending');
    const config = first.calls.launches[0].config;
    first.cancel();
    assert.equal(await operation, false);
    const second = fixture(t, { storage: first.context.globalStorageUri.fsPath });
    assert.equal((await second.api.recoveryReady).removed, 0);
    assert(fs.existsSync(config.program));
    assert.deepEqual(terminalOutputs(first), []);
    settle(false);
    await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'The declined request may now clean output');
});

test('coalesced declined debug starts permit coalesced retry while their notification remains open', { timeout: 3000 }, async t => {
    let dismiss;
    const notification = new Promise(resolve => { dismiss = resolve; });
    t.after(() => dismiss());
    const options = { startResult: false, showErrorMessage: () => notification };
    const f = fixture(t, options);
    assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [false, false, false]);
    assert.equal(f.calls.launches.length, 1, 'Three failed callers must share one editor start');
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 1);
    const rejected = f.calls.launches[0].config;
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /The editor did not start the netcoredbg debug session/);
    await waitForRemovedOutput(f, rejected.__netcoredbgFileAppOutput);
    assert(!fs.existsSync(rejected.program));
    assert.deepEqual(terminalOutputs(f), []);
    options.startResult = true;
    f.document.isDirty = true;
    assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.launches.length, 2);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 2, 'Three corrected callers must share one fresh build');
    const retried = f.calls.launches[1].config;
    assert.notEqual(retried.program, rejected.program);
    assert(fs.existsSync(retried.program));
    assert.equal(f.calls.errors.length, 1, 'Retry must not duplicate the earlier failure');
    f.terminate(retried);
    await f.api.dispose();
    assert(!fs.existsSync(retried.__netcoredbgFileAppOutput));
    assert.deepEqual(terminalOutputs(f), []);
});

test('cancellation during a declined debug start is quiet and releases the file for retry', { timeout: 2000 }, async t => {
    let resolveStart;
    const options = { startDebugging: () => new Promise(resolve => { resolveStart = resolve; }) };
    const f = fixture(t, options);
    const operation = f.api.debugActiveFile();
    const startDeadline = Date.now() + 1000;
    while (!resolveStart && Date.now() < startDeadline) await new Promise(resolve => setImmediate(resolve));
    assert.equal(typeof resolveStart, 'function', 'The command must reach debug start before cancellation');
    f.cancel();
    resolveStart(false);
    assert.equal(await operation, false);
    assert.deepEqual(f.calls.errors, []);
    await waitFor(() => !fs.existsSync(f.calls.launches[0].config.program), 'The declined start must clean cancelled output');
    options.startDebugging = async () => true;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.launches.length, 2);
    assert(fs.existsSync(f.calls.launches[1].config.program));
});

for (const eventBeforeCancel of [false, true]) {
    test(`cancelling a pending start stops only its session and preserves output until stop (${eventBeforeCancel ? 'event first' : 'cancel first'})`, async t => {
        let resolveStart;
        let resolveStop;
        const removals = [];
        const options = {
            startDebugging: () => new Promise(resolve => { resolveStart = resolve; }),
            stopDebugging: () => new Promise(resolve => { resolveStop = resolve; }),
            removeOutput: async (directory, settings) => { removals.push(directory); await fs.promises.rm(directory, settings); },
        };
        const f = fixture(t, options);
        const operation = f.api.debugActiveFile();
        await waitFor(() => resolveStart, 'The start request must be pending');
        const config = f.calls.launches[0].config;
        let session;
        if (eventBeforeCancel) session = f.startSession(config);
        f.cancel();
        if (!eventBeforeCancel) session = f.startSession(config);
        resolveStart(true);
        assert.equal(await operation, false, 'Cancellation must not be reported as a successful launch');
        await waitFor(() => resolveStop, 'The cancelled session must be stopped');
        assert.deepEqual(f.calls.stops, [session]);
        assert(fs.existsSync(config.program), 'A session being stopped still owns its DLL');
        resolveStop();
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(removals, [], 'Stop completion must not even request deletion before termination');
        assert(fs.existsSync(config.program), 'Stop completion alone must not delete output before termination');
        f.terminate(config);
        await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'Stopped session output must be cleaned');
        assert.deepEqual(f.calls.errors, []);
        options.startDebugging = undefined;
        assert.equal(await f.api.debugActiveFile(), true);
        assert(fs.existsSync(f.calls.launches[1].config.program));
    });
}

test('cancellation releases the pending command and a later start event stops only the old session', async t => {
    let resolveStart;
    const options = { startDebugging: () => new Promise(resolve => { resolveStart = resolve; }) };
    const f = fixture(t, options);
    const operation = f.api.debugActiveFile();
    await waitFor(() => resolveStart, 'The first start request must be pending');
    const old = f.calls.launches[0].config;
    f.cancel();
    let timer;
    const result = await Promise.race([operation, new Promise(resolve => {
        timer = setTimeout(() => resolve('still pending'), 1000);
    })]).finally(() => clearTimeout(timer));
    assert.equal(result, false, 'A pending editor start must not keep the cancelled file command pending');
    options.startDebugging = undefined;
    assert.equal(await f.api.debugActiveFile(), true);
    const retried = f.calls.launches[1].config;
    assert(fs.existsSync(old.program), 'The editor may still start the old session');
    resolveStart(true);
    await new Promise(resolve => setImmediate(resolve));
    assert(fs.existsSync(old.program), 'A true result without a session handle must retain output');
    const oldSession = f.startSession(old);
    await waitFor(() => !fs.existsSync(old.__netcoredbgFileAppOutput), 'The late cancelled session must stop and clean');
    assert.deepEqual(f.calls.stops, [oldSession]);
    assert(fs.existsSync(retried.program), 'Old-session termination must preserve the retry');
    assert.deepEqual(f.calls.errors, []);
});

test('cancelled pending starts that later decline or reject clean their output quietly', async t => {
    for (const reject of [false, true]) {
        let settle;
        const f = fixture(t, { startDebugging: () => new Promise((resolve, fail) => {
            settle = () => reject ? fail(new Error('Adapter start failed after cancellation')) : resolve(false);
        }) });
        const operation = f.api.debugActiveFile();
        await waitFor(() => settle, 'The start request must be pending');
        const config = f.calls.launches[0].config;
        f.cancel();
        let timer;
        assert.equal(await Promise.race([operation, new Promise(resolve => {
            timer = setTimeout(() => resolve('still pending'), 1000);
        })]).finally(() => clearTimeout(timer)), false);
        await new Promise(resolve => setImmediate(resolve));
        settle(); // Reject or decline in a later turn, after the cancellation race has settled.
        await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'The failed background start must clean output');
        assert.deepEqual(f.calls.errors, []);
        assert.deepEqual(f.calls.stops, []);
    }
});

test('a stop failure reports once and preserves live output until actual termination', async t => {
    let resolveStart;
    const options = {
        startDebugging: () => new Promise(resolve => { resolveStart = resolve; }),
        stopDebugging: async () => { throw new Error('Adapter refused disconnect'); },
        showErrorMessage: () => new Promise(() => {}),
    };
    const f = fixture(t, options);
    const operation = f.api.debugActiveFile();
    await waitFor(() => resolveStart, 'The start request must be pending');
    const old = f.calls.launches[0].config;
    const session = f.startSession(old);
    f.cancel();
    resolveStart(true);
    assert.equal(await operation, false);
    await waitFor(() => f.calls.errors.length, 'Stop failure must be reported');
    assert.match(f.calls.errors[0], /stop.*cancelled.*debug session/i);
    assert(f.calls.errors[0].includes(session.name), 'The notification must identify the session to stop manually');
    assert(f.calls.logs.some(line => line.includes('Adapter refused disconnect')));
    f.emitStart(session);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.calls.stops.length, 1);
    assert.equal(f.calls.errors.length, 1);
    options.startDebugging = undefined;
    assert.equal(await f.api.debugActiveFile(), true);
    assert(fs.existsSync(old.program), 'Unconfirmed stop must never enter the cleanup-retry queue');
    assert(fs.existsSync(f.calls.launches[1].config.program));
    f.terminate(old);
    await waitFor(() => !fs.existsSync(old.__netcoredbgFileAppOutput), 'Actual termination permits cleanup');
    assert(fs.existsSync(f.calls.launches[1].config.program));
});

test('termination before a stop rejection stays terminal and quiet', async t => {
    let resolveStart;
    let rejectStop;
    const f = fixture(t, {
        startDebugging: () => new Promise(resolve => { resolveStart = resolve; }),
        stopDebugging: () => new Promise((_resolve, reject) => { rejectStop = reject; }),
    });
    const operation = f.api.debugActiveFile();
    await waitFor(() => resolveStart, 'The start request must be pending');
    const config = f.calls.launches[0].config;
    f.startSession(config);
    f.cancel();
    resolveStart(true);
    assert.equal(await operation, false);
    await waitFor(() => rejectStop, 'The cancelled session must be stopping');
    f.terminate(config);
    await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'Termination must permit cleanup');
    rejectStop(new Error('Already terminated'));
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(f.calls.errors, []);
});

test('cancelled launch ignores unrelated session events even when they carry its output field', async t => {
    let resolveStart;
    let resolveStop;
    const f = fixture(t, {
        startDebugging: () => new Promise(resolve => { resolveStart = resolve; }),
        stopDebugging: () => new Promise(resolve => { resolveStop = resolve; }),
    });
    const operation = f.api.debugActiveFile();
    await waitFor(() => resolveStart, 'The start request must be pending');
    const config = f.calls.launches[0].config;
    f.cancel();
    f.startSession({ ...config, program: path.join(path.dirname(config.program), 'Other.dll') });
    f.startSession(config, { type: 'node' });
    assert.deepEqual(f.calls.stops, []);
    assert(fs.existsSync(config.program));
    const session = f.startSession(config);
    const impostor = { ...session, id: 'unrelated-session' };
    f.emitStart(impostor);
    f.terminate({ ...config });
    await new Promise(resolve => setImmediate(resolve));
    assert(fs.existsSync(config.program), 'An unrelated termination must not release a captured session output');
    await waitFor(() => resolveStop, 'The matching session must be stopped');
    assert.deepEqual(f.calls.stops, [session]);
    resolveStart(true);
    assert.equal(await operation, false);
    resolveStop();
    await new Promise(resolve => setImmediate(resolve));
    assert(fs.existsSync(config.program));
    f.terminate(config);
    await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'Only the matching session may release output');
});

test('an uncancelled start rejection reports the failure and cleans output', async t => {
    const f = fixture(t, { startDebugging: async () => { throw new Error('Adapter start rejected'); } });
    assert.equal(await f.api.debugActiveFile(), false);
    await waitForRemovedOutput(f, f.calls.launches[0].config.__netcoredbgFileAppOutput);
    assert(!fs.existsSync(f.calls.launches[0].config.program));
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /Adapter start rejected/);
    assert.deepEqual(f.calls.stops, []);
});

test('cancellation just before handoff skips the start API and cleans output before retry', async t => {
    let cancelFirst = true;
    const f = fixture(t, { reportProgress: progress => {
        if (cancelFirst && progress.message === 'Starting netcoredbg') { cancelFirst = false; f.cancel(); }
    } });
    assert.equal(await f.api.debugActiveFile(), false);
    const build = f.calls.processes.find(call => call.args[0] === 'build');
    const directory = build.args[build.args.indexOf('--output') + 1];
    await waitFor(() => !fs.existsSync(directory), 'A pre-cancelled launch must release its output');
    assert.deepEqual(f.calls.launches, []);
    assert.deepEqual(f.calls.errors, []);
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.launches.length, 1);
    assert.deepEqual(f.calls.stops, []);
});

test('a build failure releases the file for retry while its error notification remains open', async t => {
    let dismiss;
    const notification = new Promise(resolve => { dismiss = resolve; });
    const options = { buildError: new Error('CS0246: DllImport could not be found'), showErrorMessage: () => notification };
    const f = fixture(t, options);
    const failed = f.api.debugActiveFile();
    t.after(async () => { dismiss(); await failed; });

    assert.equal(await Promise.race([failed, new Promise(resolve => setTimeout(() => resolve('still waiting for notification'), 250))]), false);
    const failedBuild = f.calls.processes.find(call => call.args[0] === 'build');
    await waitForRemovedOutput(f, failedBuild.args[failedBuild.args.indexOf('--output') + 1]);
    assert(!fs.existsSync(failedBuild.args[failedBuild.args.indexOf('--output') + 1]), 'Failed output must be cleaned before the notification closes');

    options.buildError = undefined;
    fs.writeFileSync(f.source, 'using System.Runtime.InteropServices;\nConsole.WriteLine("fixed");\n');
    f.document.isDirty = true;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 2);
    assert.equal(f.calls.launches.length, 1);
});

test('a save failure releases the file for retry while its error notification remains open', async t => {
    let dismiss;
    const notification = new Promise(resolve => { dismiss = resolve; });
    const f = fixture(t, { dirty: true, showErrorMessage: () => notification });
    const save = f.document.save;
    f.document.save = async () => { throw new Error('Could not save source'); };
    const failed = f.api.debugActiveFile();
    t.after(async () => { dismiss(); await failed; });

    assert.equal(await Promise.race([failed, new Promise(resolve => setTimeout(() => resolve('still waiting for notification'), 250))]), false);
    assert.equal(f.calls.processes.length, 0);
    f.document.save = save;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.launches.length, 1);
});

test('notification delivery failures are logged without preventing a retry', async t => {
    for (const [showErrorMessage, diagnostic] of [
        [() => Promise.reject(new Error('Notification service unavailable')), 'Notification service unavailable'],
        [() => { throw new Error('Notification service unavailable'); }, 'Notification service unavailable'],
        [() => Promise.reject(undefined), 'undefined'],
    ]) {
        const options = { buildError: new Error('Build failed'), showErrorMessage };
        const f = fixture(t, options);
        assert.equal(await f.api.debugActiveFile(), false);
        assert(f.calls.logs.some(line => line.includes(`Could not show error notification: ${diagnostic}`)));
        options.buildError = undefined;
        assert.equal(await f.api.debugActiveFile(), true);
        assert.equal(f.calls.launches.length, 1);
    }
});

test('cancelling classification prevents a fallback project launch', async t => {
    const f = fixture(t, { classify: async () => {
        f.cancel();
        return { kind: 'project', reason: 'included' };
    } });
    assert.equal(await f.api.debugActiveFile(), false);
    assert.equal(f.calls.launches.length, 0);
    assert.equal(f.calls.commands.length, 0);
    assert.deepEqual(f.calls.errors, []);
});

test('SDK checks accept supported versions and parse English host architecture', () => {
    for (const version of ['10.0.100', '10.0.402', '11.0.100-rc.2']) requireFileAppSdk(version);
    for (const version of ['8.0.418', '10.0.99', '10.0.100-preview.7', 'garbage']) {
        assert.throws(() => requireFileAppSdk(version), /10.0.100/);
    }
    assert.equal(sdkArchitecture('Host:\r\n  Version: 10.0.13\r\n  Architecture: arm64\r\n'), 'arm64');
    assert.throws(() => sdkArchitecture('unknown'), /architecture/);
});

for (const sink of ['command', 'classification']) {
    test(`foreground diagnostics preserve build failure and a coalesced dirty retry when ${sink} logging throws`, { timeout: 5000 }, async t => {
        const failure = new Error(`Original build failure under ${sink} logging`);
        let broken = true, diagnosticAttempts = 0;
        const f = fixture(t, { appendLine: line => {
            if (sink === 'command' ? line.startsWith('dotnet ') : line.includes(': file (fixture)')) {
                diagnosticAttempts++;
                throw new Error(`${sink} diagnostic unavailable`);
            }
        } });
        const run = f.dependencies.runDotnet;
        f.dependencies.runDotnet = async (args, settings) => {
            if (args[0] === 'build' && broken) {
                f.calls.processes.push({ args, settings });
                throw failure;
            }
            return run(args, settings);
        };
        try {
            assert.equal(await f.api.debugActiveFile(), false);
            assert.equal(f.calls.errors.length, 1);
            assert.match(f.calls.errors[0], new RegExp(failure.message));
            assert.equal(f.calls.launches.length, 0);
            const failedBuild = f.calls.processes.find(call => call.args[0] === 'build');
            assert(failedBuild, 'A diagnostic failure must not prevent the real build');
            const failedDirectory = failedBuild.args[failedBuild.args.indexOf('--output') + 1];
            await waitForRemovedOutput(f, failedDirectory);
            assert.deepEqual(terminalOutputs(f), []);

            broken = false;
            f.document.isDirty = true;
            assert.deepEqual(await Promise.all(Array.from({ length: 3 }, () => f.api.debugActiveFile())), [true, true, true]);
            assert.equal(f.calls.saves, 1);
            assert.equal(f.calls.classifications.length, 2);
            assert.equal(f.calls.processes.filter(call => call.args[0] === 'build').length, 2);
            assert.equal(f.calls.launches.length, 1);
            assert.equal(f.calls.errors.length, 1, 'A corrected retry must not report the failed diagnostic');
            assert.equal(diagnosticAttempts, sink === 'command' ? 6 : 2);
            const config = f.calls.launches[0].config;
            assert.notEqual(config.__netcoredbgFileAppOutput, failedDirectory);
            assert(fs.existsSync(config.program));
            f.terminate(config);
            await f.api.dispose();
            assert(!fs.existsSync(config.__netcoredbgFileAppOutput));
            assert.deepEqual(terminalOutputs(f), []);
            assertDisposed(f);
        } finally { await f.api.dispose(); }
    });
}

test('foreground diagnostics checkpoint reentrant command-log cancellation and disposal without swallowing progress errors', async t => {
    for (const action of ['cancel', 'dispose']) {
        let f, disposal, diagnosticAttempts = 0, heldOutput;
        f = fixture(t, { appendLine: line => {
            if (!line.startsWith('dotnet ')) return;
            diagnosticAttempts++;
            if (action === 'cancel') f.cancel();
            else disposal = f.api.dispose();
            heldOutput = f.calls.disposals.output === 0;
            throw new Error('Command diagnostic failed after reentrant cancellation');
        } });
        try {
            // The fixture SDK provider deliberately ignores its AbortSignal.
            assert.equal(await f.api.debugActiveFile(), false);
            assert.equal(diagnosticAttempts, 1);
            assert.equal(heldOutput, true, 'The command must retain diagnostics until its continuation settles');
            assert.equal(f.calls.classifications.length, 1);
            assert.deepEqual(f.calls.processes, [], 'No provider may dispatch after command logging cancels');
            assert.deepEqual(f.calls.launches, []);
            assert.deepEqual(f.calls.errors, []);
        } finally { await (disposal || f.api.dispose()); }
        assertDisposed(f);
    }

    const failure = new Error('Original progress delivery failure');
    const f = fixture(t, { reportProgress: () => { throw failure; } });
    try {
        assert.equal(await f.api.debugActiveFile(), false);
        assert.equal(f.calls.errors.length, 1);
        assert.match(f.calls.errors[0], /Original progress delivery failure/);
        assert.deepEqual(f.calls.classifications, []);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.launches, []);
    } finally { await f.api.dispose(); }
    assertDisposed(f);
});

test('foreground diagnostics keep certificate cancellation quiet and reject late consent after output drains', { timeout: 5000 }, async t => {
    for (const timing of ['log', 'consent']) for (const action of ['cancel', 'dispose']) {
        let f, disposal, dismiss, diagnosticAttempts = 0;
        const cancel = () => {
            if (action === 'cancel') f.cancel();
            else disposal = f.api.dispose();
        };
        f = certificatePhaseFixture(t, {
            certificateProcess: async () => { throw new Error('Original missing certificate'); },
            certificatePrompt: () => new Promise(resolve => { dismiss = resolve; }),
            appendLine: line => {
                if (!line.startsWith('HTTPS development certificate needs attention:')) return;
                diagnosticAttempts++;
                if (timing === 'log') cancel();
                throw new Error('Certificate diagnostic unavailable');
            },
        });
        const operation = f.api.debugActiveFile();
        try {
            if (timing === 'consent') {
                await waitFor(() => dismiss, 'A broken diagnostic must not prevent the consent modal');
                assert.equal(getEventListeners(f.certificate.processes[0].settings.signal, 'abort').length, 1);
                cancel();
            }
            assert.equal(await operation, false);
            await (disposal || f.api.dispose());
            assert.equal(diagnosticAttempts, 1);
            assert.equal(f.certificate.processes.length, 1);
            assert.equal(f.certificate.prompts, timing === 'consent' ? 1 : 0);
            assert.equal(getEventListeners(f.certificate.processes[0].settings.signal, 'abort').length, 0);
            assert.deepEqual(f.calls.errors, []);
            assert.deepEqual(f.calls.launches, []);
            const build = f.calls.processes.find(call => call.args[0] === 'build');
            assert(!fs.existsSync(build.args[build.args.indexOf('--output') + 1]));
            assert.deepEqual(terminalOutputs(f), []);
            assertDisposed(f);
            const logCount = f.calls.logs.length;
            dismiss?.('Trust development certificate');
            await new Promise(resolve => setImmediate(resolve));
            assert.equal(f.certificate.processes.length, 1, 'A late Trust answer cannot authorize work');
            assert.equal(f.calls.logs.length, logCount, 'Late consent must not write to disposed output');
        } finally {
            f.cancel();
            dismiss?.('Cancel');
            await operation;
            await (disposal || f.api.dispose());
        }
    }
});
