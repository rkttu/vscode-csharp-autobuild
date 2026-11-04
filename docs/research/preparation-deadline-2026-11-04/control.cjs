'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { performance } = require('node:perf_hooks');
const root = __dirname;
const runtimePath = path.resolve(root, '../worktree/scripts/variant/file-based-apps/runtime.cjs');
const { activate } = require(runtimePath);
const sdkRoot = 'C:\\Program Files\\dotnet';
const workspace = path.join(root, 'workspace');
const source = path.join(workspace, 'sample.cs');
const storage = path.join(root, 'storage');
const env = { ...process.env, APPDATA: path.join(root, 'appdata'), DOTNET_CLI_HOME: path.join(root, 'dotnet-home'),
    DOTNET_ROOT: sdkRoot, DOTNET_CLI_TELEMETRY_OPTOUT: '1', DOTNET_GENERATE_ASPNET_CERTIFICATE: 'false',
    DOTNET_CLI_UI_LANGUAGE: 'en-US', PATH: sdkRoot + path.delimiter + process.env.PATH };
const result = { success: false, checks: [], errors: [], logs: [], progress: [],
    scope: { realDotnetCli: true, runtimeLoadedDirectly: true, mockedEditorApi: true,
        syntheticDeadlineAndClockOnFirstBuild: true, actualFiveMinuteWait: false, sameRuntimeRetry: true,
        realDebugger: false, installedCommand: false, physicalF5: false, VSCodium: false, macOS: false, published: false },
    sdkVersion: '10.0.403', runtimeVersion: '10.0.14', platform: 'Windows ARM64',
    runtimeSha256: crypto.createHash('sha256').update(fs.readFileSync(runtimePath)).digest('hex') };
let offset = 0;
let deadline;
let injectBuildTimeout = true;
let startedListener;
let terminatedListener;
let faultTimer;
const launches = [];
const document = { uri: { scheme: 'file', fsPath: source }, isDirty: false,
    getText: () => fs.readFileSync(source, 'utf8'), save: async () => true };
const context = { globalStorageUri: { fsPath: storage }, subscriptions: [],
    extension: { packageJSON: { netcoredbgBuild: { target: 'win32-arm64' } } } };
const vscode = {
    ProgressLocation: { Notification: 15 },
    window: { activeTextEditor: { document },
        createOutputChannel: () => ({ append: text => result.logs.push(String(text)), appendLine: text => result.logs.push(String(text)), dispose() {} }),
        showErrorMessage: message => { result.errors.push(message); return new Promise(() => {}); },
        withProgress: async (_options, callback) => callback({ report: progress => {
            result.progress.push(progress.message);
            if (injectBuildTimeout && progress.message === 'Building file-based app') {
                injectBuildTimeout = false;
                faultTimer = setTimeout(() => { offset += 300001; deadline(); }, 50);
            }
        } }, { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) }),
    },
    workspace: { isTrusted: true, getWorkspaceFolder: () => undefined },
    commands: { registerCommand: () => ({ dispose() {} }), executeCommand: async () => { throw new Error('Unexpected project fallback'); } },
    debug: {
        onDidStartDebugSession: callback => { startedListener = callback; return { dispose() {} }; },
        onDidTerminateDebugSession: callback => { terminatedListener = callback; return { dispose() {} }; },
        startDebugging: async (_folder, config) => {
            const session = { id: `control-${launches.length + 1}`, type: config.type, name: config.name, configuration: config };
            launches.push(session); startedListener(session); return true;
        },
        stopDebugging: async session => terminatedListener(session),
    },
};
async function waitFor(predicate, label) {
    const end = Date.now() + 5000;
    while (!predicate() && Date.now() < end) await new Promise(resolve => setTimeout(resolve, 10));
    assert(predicate(), label);
}
function runDirectories() {
    const base = path.join(storage, 'file-based-apps');
    if (!fs.existsSync(base)) return [];
    return fs.readdirSync(base).flatMap(parent => fs.readdirSync(path.join(base, parent)).filter(name => name.startsWith('run-')));
}
async function main() {
    fs.mkdirSync(workspace, { recursive: true });
    fs.mkdirSync(path.join(env.APPDATA, 'NuGet'), { recursive: true });
    const nuget = '<configuration><packageSources><clear /></packageSources></configuration>\n';
    fs.writeFileSync(path.join(workspace, 'NuGet.Config'), nuget);
    fs.writeFileSync(path.join(env.APPDATA, 'NuGet/NuGet.Config'), nuget);
    fs.writeFileSync(path.join(workspace, 'global.json'), JSON.stringify({ sdk: { version: '10.0.403', rollForward: 'disable' } }));
    fs.writeFileSync(source, '#:property TargetFramework=net10.0\nint answer = 40;\nanswer += 2;\nConsole.WriteLine($"ANSWER={answer}");\n');
    const api = activate(context, { vscode, env,
        findDotnet: async () => ({ executable: path.join(sdkRoot, 'dotnet.exe'), root: sdkRoot }),
        now: () => performance.now() + offset,
        scheduleTimeout: (callback, ms) => { deadline = callback; return setTimeout(callback, ms); },
    });
    assert.equal(await api.debugActiveFile(), false);
    clearTimeout(faultTimer);
    assert.equal(launches.length, 0);
    assert.equal(result.errors.length, 1);
    assert.match(result.errors[0], /timed out.*Building file-based app/);
    assert.deepEqual(runDirectories(), []);
    result.checks.push('Injected deadline during a real dotnet build reports phase timeout, launches no debug session and removes owned run output');
    assert.equal(await api.debugActiveFile(), true);
    assert.equal(launches.length, 1);
    const session = launches[0];
    assert(fs.existsSync(session.configuration.program));
    assert(fs.existsSync(path.join(path.dirname(session.configuration.program), 'FileApp.pdb')));
    assert.equal(result.errors.length, 1);
    result.checks.push('Same runtime and source retry completes real SDK checks/build with a fresh preparation budget while prior notification stays open');
    assert(result.logs.some(line => /Phase timed out: Building file-based app/.test(line)));
    assert(result.logs.some(line => /Phase completed: Building file-based app/.test(line)));
    result.checks.push('Real SDK work emits failed and successful phase/cumulative duration diagnostics');
    terminatedListener(session);
    await waitFor(() => !fs.existsSync(session.configuration.__netcoredbgFileAppOutput), 'Normal control termination must clean output');
    result.checks.push('Mocked matching session termination cleans the successful real build output');
    result.success = true;
}
main().catch(error => { result.error = error.stack || String(error); process.exitCode = 1; }).finally(() => {
    clearTimeout(faultTimer);
    for (const subscription of context.subscriptions.reverse()) subscription.dispose();
    fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    process.stdout.write(JSON.stringify({ success: result.success, checks: result.checks, error: result.error }) + '\n');
});
