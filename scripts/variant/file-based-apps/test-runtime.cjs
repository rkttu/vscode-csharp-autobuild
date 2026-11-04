'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { activate, COMMAND, requireFileAppSdk, sdkArchitecture } = require('./runtime.cjs');

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
    const calls = { commands: [], launches: [], stops: [], processes: [], classifications: [], errors: [], saves: 0, logs: [] };
    let termination;
    let started;
    let cancellation;
    const sessions = new Map();
    let nextSession = 0;
    const sessionFor = (config, overrides = {}) => ({
        id: `session-${++nextSession}`, type: config.type, name: config.name, configuration: config, ...overrides,
    });
    const startSession = (config, overrides) => {
        const session = sessionFor(config, overrides);
        sessions.set(config, session);
        started?.(session);
        return session;
    };
    const document = {
        uri: { scheme: 'file', fsPath: source },
        isDirty: Boolean(options.dirty),
        getText: () => fs.readFileSync(source, 'utf8'),
        save: async () => { calls.saves++; return options.saveResult !== false; },
    };
    const vscode = {
        ProgressLocation: { Notification: 15 },
        window: {
            activeTextEditor: { document },
            createOutputChannel: () => ({ append: value => calls.logs.push(value), appendLine: value => {
                calls.logs.push(value);
                options.appendLine?.(value);
            }, dispose() {} }),
            showErrorMessage: message => {
                calls.errors.push(message);
                return options.showErrorMessage ? options.showErrorMessage(message) : Promise.resolve(undefined);
            },
            withProgress: async (_settings, callback) => callback({ report: value => options.reportProgress?.(value) }, {
                isCancellationRequested: false,
                onCancellationRequested: callback => { cancellation = callback; return { dispose() { cancellation = undefined; } }; },
            }),
        },
        workspace: { isTrusted: options.trusted !== false, getWorkspaceFolder: () => options.noWorkspace ? undefined : { name: 'workspace' } },
        commands: {
            registerCommand: (command, callback) => { assert.equal(command, COMMAND); calls.handler = callback; return { dispose() {} }; },
            executeCommand: async command => { calls.commands.push(command); return true; },
        },
        debug: {
            onDidStartDebugSession: callback => { started = callback; return { dispose() { started = undefined; } }; },
            onDidTerminateDebugSession: callback => { termination = callback; return { dispose() {} }; },
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
                termination(session);
            },
        },
    };
    const context = { globalStorageUri: { fsPath: path.join(root, 'storage') }, subscriptions: [], extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } };
    const dependencies = {
        vscode,
        env: {},
        ...(options.webSupport ? { webSupport: options.webSupport } : {}),
        ...(options.removeOutput ? { removeOutput: options.removeOutput } : {}),
        findDotnet: async () => ({ executable: path.join(root, 'dotnet', 'dotnet.exe'), root: path.join(root, 'dotnet') }),
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
    const api = activate(context, dependencies);
    return { root, source, document, vscode, context, dependencies, calls, api,
        startSession, emitStart: session => started?.(session),
        terminate: config => termination(sessions.get(config) || sessionFor(config)), cancel: () => cancellation?.() };
}

async function waitFor(predicate, message) {
    const deadline = Date.now() + 1000;
    while (!predicate() && Date.now() < deadline) await new Promise(resolve => setImmediate(resolve));
    assert(predicate(), message);
}

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
    assert(!fs.existsSync(f.calls.launches[0].config.program));
    assert.equal(f.calls.errors.length, 1);
    assert.match(f.calls.errors[0], /editor did not start the netcoredbg debug session/);
    assert.match(f.calls.errors[0], /Debug Console/);
    assert(f.calls.logs.some(message => message.includes('editor did not start the netcoredbg debug session')));
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
    const failed = f.calls.launches[1].config;
    assert(fs.existsSync(failed.program), 'An exhausted deletion attempt leaves output for later recovery');
    assert(f.calls.logs.some(line => line.includes('Could not clean file-app output')));
    locked = false;
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    const retried = f.calls.launches[2].config;
    assert(!fs.existsSync(failed.program), 'The next command must retry the failed cleanup');
    assert(fs.existsSync(active.program), 'Recovery must preserve an earlier live session');
    assert(fs.existsSync(retried.program), 'The new session must retain its distinct output');
    assert.notEqual(retried.program, failed.program);
    assert.deepEqual(removals, [path.dirname(failed.program), path.dirname(failed.program)]);
    assert.equal(f.calls.errors.length, 1, 'Cleanup must preserve the original launch failure');
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
    assert.equal(removals.length, 1);
    assert(fs.existsSync(config.program));
    release();
    await waitFor(() => !fs.existsSync(config.__netcoredbgFileAppOutput), 'The shared cleanup must complete');
    await new Promise(resolve => setImmediate(resolve));
    f.terminate(config);
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
    const failed = f.calls.launches[0].config;
    assert.equal(f.calls.errors.length, 1, 'A failed cleanup log must not replace the launch error');
    locked = false;
    options.startResult = true;
    assert.equal(await f.api.debugActiveFile(), true);
    assert(!fs.existsSync(failed.program));
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
    assert.equal(await f.api.debugActiveFile(), false);
    const first = f.calls.launches[0].config;
    const second = f.calls.launches[1].config;
    options.startResult = true;
    const before = removals.length;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(removals.length, before + 1, 'A command must not sweep the entire failed-output backlog');
    assert.equal(removals.at(-1), path.dirname(first.program));
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(removals.length, before + 2);
    assert.equal(removals.at(-1), path.dirname(second.program), 'A locked output must not starve another failed output');
    assert.equal(f.calls.errors.length, 2, 'Recovery failure must not become an additional launch error');
    for (const launch of f.calls.launches) assert(fs.existsSync(launch.config.program));
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
    const build = f.calls.processes.find(call => call.args[0] === 'build');
    const failedOutput = build.args[build.args.indexOf('--output') + 1];
    assert(fs.existsSync(failedOutput));
    assert.deepEqual(f.calls.errors, []);
    locked = false;
    assert.equal(await f.api.debugActiveFile(), true);
    assert(!fs.existsSync(failedOutput));
    assert.deepEqual(f.calls.errors, []);
    assert.equal(f.calls.launches.length, 1);
});

test('a declined debug start permits retry while its notification remains open', { timeout: 2000 }, async t => {
    let dismiss;
    const notification = new Promise(resolve => { dismiss = resolve; });
    t.after(() => dismiss());
    const options = { startResult: false, showErrorMessage: () => notification };
    const f = fixture(t, options);
    assert.equal(await f.api.debugActiveFile(), false);
    const rejected = f.calls.launches[0].config;
    assert.equal(f.calls.errors.length, 1);
    assert(!fs.existsSync(rejected.program));
    options.startResult = true;
    f.document.isDirty = true;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.saves, 1);
    assert.equal(f.calls.launches.length, 2);
    const retried = f.calls.launches[1].config;
    assert.notEqual(retried.program, rejected.program);
    assert(fs.existsSync(retried.program));
    assert.equal(f.calls.errors.length, 1, 'Retry must not duplicate the earlier failure');
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
        settle();
        assert.equal(await operation, false);
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
