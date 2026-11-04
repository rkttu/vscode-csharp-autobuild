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
    const calls = { commands: [], launches: [], processes: [], classifications: [], errors: [], saves: 0, logs: [] };
    let termination;
    let cancellation;
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
            createOutputChannel: () => ({ append: value => calls.logs.push(value), appendLine: value => calls.logs.push(value), dispose() {} }),
            showErrorMessage: message => {
                calls.errors.push(message);
                return options.showErrorMessage ? options.showErrorMessage(message) : Promise.resolve(undefined);
            },
            withProgress: async (_settings, callback) => callback({ report() {} }, {
                isCancellationRequested: false,
                onCancellationRequested: callback => { cancellation = callback; return { dispose() {} }; },
            }),
        },
        workspace: { isTrusted: options.trusted !== false, getWorkspaceFolder: () => options.noWorkspace ? undefined : { name: 'workspace' } },
        commands: {
            registerCommand: (command, callback) => { assert.equal(command, COMMAND); calls.handler = callback; return { dispose() {} }; },
            executeCommand: async command => { calls.commands.push(command); return true; },
        },
        debug: {
            onDidTerminateDebugSession: callback => { termination = callback; return { dispose() {} }; },
            startDebugging: async (folder, config) => {
                calls.launches.push({ folder, config });
                return options.startDebugging ? options.startDebugging(folder, config) : options.startResult !== false;
            },
        },
    };
    const context = { globalStorageUri: { fsPath: path.join(root, 'storage') }, subscriptions: [], extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } };
    const dependencies = {
        vscode,
        env: {},
        ...(options.webSupport ? { webSupport: options.webSupport } : {}),
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
        terminate: config => termination({ configuration: config }), cancel: () => cancellation() };
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
    assert(!fs.existsSync(f.calls.launches[0].config.program));
    options.startDebugging = async () => true;
    assert.equal(await f.api.debugActiveFile(), true);
    assert.equal(f.calls.launches.length, 2);
    assert(fs.existsSync(f.calls.launches[1].config.program));
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
