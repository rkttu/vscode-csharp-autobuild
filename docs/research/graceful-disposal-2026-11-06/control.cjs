'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const vscode = require('vscode');

const COMMAND = 'netcoredbg.debugActiveFile';
const MODULES = ['entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs'];
const DAP_COMMANDS = new Set(['initialize', 'launch', 'configurationDone', 'disconnect', 'terminate', 'continue', 'pause']);
const SAFETY_MS = 90000; // Local control safety limit, not a product budget.
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const samePath = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
function within(base, file) {
    const relative = path.relative(path.resolve(base), path.resolve(file));
    return relative && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}
function exists(file) {
    try { fs.lstatSync(file); return true; }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}
function pidAlive(pid) {
    assert(Number.isSafeInteger(pid) && pid > 0);
    try { process.kill(pid, 0); return true; }
    catch (error) { if (error.code === 'ESRCH') return false; throw error; }
}
function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}
async function bounded(promise, label, ms = SAFETY_MS) {
    let timer;
    try {
        return await Promise.race([promise, new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error(`Safety timeout: ${label}`)), ms);
        })]);
    } finally { clearTimeout(timer); }
}
async function availablePort() {
    const server = net.createServer();
    await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen({ host: '127.0.0.1', port: 0, exclusive: true }, resolve);
    });
    const port = server.address().port;
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    return port;
}
async function canBind(port) {
    const server = net.createServer();
    return new Promise((resolve, reject) => {
        server.once('error', error => error.code === 'EADDRINUSE' ? resolve(false) : reject(error));
        server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
            server.close(error => error ? reject(error) : resolve(true));
        });
    });
}
async function request(origin, endpoint = '/probe', options = {}) {
    const response = await fetch(origin + endpoint, { ...options, signal: AbortSignal.timeout(2000) });
    assert.equal(response.status, 200);
    return response.json();
}
function queuesEmpty(base) {
    return ['terminal-cleanup-v1', 'terminal-cleanup-staging-v1'].every(name => {
        const directory = path.join(base, name);
        return !exists(directory) || fs.readdirSync(directory).length === 0;
    });
}

exports.run = async function run() {
    const root = process.env.NETCOREDBG_LIFECYCLE_ROOT;
    assert(root && path.isAbsolute(root), 'Expected an isolated lifecycle artifact directory');
    const expected = JSON.parse(fs.readFileSync(path.join(root, 'expected.json'), 'utf8'));
    const start = process.hrtime.bigint();
    const elapsed = () => Number(process.hrtime.bigint() - start) / 1e6;
    const result = { schema: 1, success: false, expected, editorApiVersion: vscode.version,
        controlSha256: hash(__filename), safetyTimeoutMilliseconds: SAFETY_MS,
        scope: { directRuntimeApi: true, runtimeLoadedFromInstalledCandidate: true,
            installedPublicCommandForUnrelatedB: true, injectedStartAndSaveTiming: true,
            actualSdkAndDebugger: true, physicalF5: false, actualHostShutdown: false,
            hostCrash: false, macOS: false, qualification: false, localOnly: true, published: false,
            caseOrder: ['installed-B', 'pending-save', 'active-helper', 'pending-handoff', 'stop-B'] },
        checks: [], phases: [], launches: [], helperContexts: [], cleanup: [] };
    const launches = [];
    const byToken = new Map();
    const helpers = [];
    const subscriptions = [];
    const gates = [];
    const traceFile = path.join(root, 'trace.jsonl');
    fs.writeFileSync(traceFile, '');
    fs.mkdirSync(path.join(root, 'progress'), { recursive: true });
    let observerError;

    function record(event, detail) {
        fs.appendFileSync(traceFile, JSON.stringify({ atMilliseconds: elapsed(), event, detail }) + '\n');
    }
    function launchState(launch) {
        return { label: launch.label, source: launch.source, nonce: launch.nonce, origin: launch.origin,
            port: launch.port, pid: launch.pid, program: launch.program, output: launch.output,
            sessionId: launch.session?.id, terminated: launch.terminated,
            capturedSessions: [...launch.sessions.values()].map(owned => ({ sessionId: owned.session.id,
                pid: owned.pid, terminated: owned.terminated, program: owned.session.configuration.program,
                output: owned.session.configuration.__netcoredbgFileAppOutput })),
            commandResult: launch.commandResult, startedAtMilliseconds: launch.startedAtMilliseconds,
            terminatedAtMilliseconds: launch.terminatedAtMilliseconds,
            pidGoneAtMilliseconds: launch.pidGoneAtMilliseconds,
            portReusableAtMilliseconds: launch.portReusableAtMilliseconds,
            outputRemovedAtMilliseconds: launch.outputRemovedAtMilliseconds,
            response: launch.response, coreRuntimeModules: launch.coreRuntimeModules };
    }
    function helperState(helper) {
        return { label: helper.label, storage: helper.storage, disposedAtMilliseconds: helper.disposedAtMilliseconds,
            sdkFinderCalls: helper.sdkFinderCalls, startRequests: helper.startRequests,
            stopRequests: helper.stopOutcomes.length,
            saveRequests: helper.saveRequests, registeredDisposeCalls: helper.registeredDisposeCalls,
            outputDisposeCalls: helper.outputDisposeCalls,
            postDisposalWrites: helper.postDisposalWrites,
            trackerDisposeCalls: helper.trackerDisposeCalls,
            listenerDisposeCalls: helper.listenerDisposeCalls, listenersActive: helper.listenersActive,
            errors: helper.errors, postDisposalResult: helper.postDisposalResult,
            startOutcomes: helper.startOutcomes, stopOutcomes: helper.stopOutcomes };
    }
    function state() {
        fs.writeFileSync(path.join(root, 'progress/state.json'), JSON.stringify({ schema: 1, root,
            elapsedMilliseconds: elapsed(), firstFailure: result.firstFailure,
            launches: launches.map(launchState), helperContexts: helpers.map(helperState) }, null, 2) + '\n');
    }
    function observe(event, action) {
        try { action(); }
        catch (error) {
            observerError ||= error;
            const failure = { event, atMilliseconds: elapsed(), error: error.stack || String(error) };
            result.firstFailure ||= failure;
            result.firstCallbackError ||= failure;
            record('observer-failure', failure);
            state();
        }
    }
    async function until(predicate, label, ms = SAFETY_MS) {
        const began = elapsed();
        while (true) {
            if (observerError) throw observerError;
            if (await predicate()) return;
            if (elapsed() - began >= ms) throw new Error(`Safety timeout: ${label}`);
            await delay(25);
        }
    }
    async function phase(label, action) {
        const item = { label, startedAtMilliseconds: elapsed() };
        result.phases.push(item);
        record('phase-start', item);
        try {
            const value = await bounded(action(), label);
            if (observerError) throw observerError;
            item.outcome = 'passed';
            return value;
        } catch (error) { item.outcome = 'failed'; item.error = error.stack || String(error); throw error; }
        finally { item.elapsedMilliseconds = elapsed() - item.startedAtMilliseconds; record('phase-end', item); state(); }
    }
    function entryBeforeCommand(entered, command, helper, label) {
        return bounded(Promise.race([entered.promise, Promise.resolve(command).then(value => {
            throw new Error(`${label}: command settled as ${JSON.stringify(value)} before gate entry; helper errors: ${JSON.stringify(helper.errors)}`);
        })]), label);
    }
    function capture(session) {
        const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN);
        if (!launch) return undefined;
        if (!launch.sessions.has(session.id)) launch.sessions.set(session.id, { session });
        launch.session ||= session;
        assert.equal(launch.sessions.size, 1, 'Each control token must create exactly one session');
        assert.equal(session.type, 'coreclr');
        const output = session.configuration.__netcoredbgFileAppOutput;
        const program = session.configuration.program;
        assert(within(root, output) && within(root, program));
        assert(samePath(path.dirname(program), output));
        if (launch.helperStorage) assert(within(launch.helperStorage, output));
        launch.output = output;
        launch.program = program;
        launch.base = path.dirname(path.dirname(output));
        return launch;
    }
    async function newLaunch(label, source) {
        let port;
        do { port = await availablePort(); } while (launches.some(launch => launch.port === port));
        const launch = { label, source, port, origin: `http://127.0.0.1:${port}`,
            nonce: crypto.randomUUID(), sessions: new Map(), coreRuntimeModules: [] };
        launches.push(launch);
        byToken.set(launch.nonce, launch);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { DisposalHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: launch.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2));
        await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(source));
        state();
        return launch;
    }
    async function ready(launch) {
        await until(async () => {
            let body;
            try { body = await request(launch.origin); }
            catch (error) { if (error instanceof assert.AssertionError) throw error; return false; }
            assert.equal(body.nonce, launch.nonce);
            assert.equal(body.revision, 'initial');
            assert.equal(body.value, 42);
            assert(Number.isSafeInteger(body.pid) && body.pid > 0);
            if (launch.pid) assert.equal(body.pid, launch.pid);
            launch.pid = body.pid;
            assert(pidAlive(body.pid));
            launch.response = body;
            return true;
        }, `${launch.label} HTTP readiness`);
        assert(launch.session && exists(launch.output));
        record('http-ready', launchState(launch));
        state();
    }
    async function preserved(b) {
        assert(!b.terminated && pidAlive(b.pid) && exists(b.output) && exists(b.program));
        assert.deepEqual(await request(b.origin), b.response);
        record('unrelated-preserved', { label: b.label, pid: b.pid, sessionId: b.session.id });
    }
    async function released(launch) {
        await until(() => launch.terminated, `${launch.label} matching termination`);
        if (launch.pid) {
            await until(() => !pidAlive(launch.pid), `${launch.label} captured PID exit`);
            launch.pidGoneAtMilliseconds = elapsed();
        }
        await until(() => canBind(launch.port), `${launch.label} port rebind`);
        launch.portReusableAtMilliseconds = elapsed();
        assert(launch.output, 'A launched session must identify its owned output');
        await until(() => !exists(launch.output) && queuesEmpty(launch.base), `${launch.label} output cleanup`);
        launch.outputRemovedAtMilliseconds = elapsed();
        record('owned-resources-released', launchState(launch));
        state();
    }
    function helperContext(label, runtime, extension, options = {}) {
        const helper = { label, storage: path.join(root, 'control-storage', label), subscriptions: [],
            sdkFinderCalls: 0, startRequests: 0, saveRequests: 0, registeredDisposeCalls: 0,
            outputDisposeCalls: 0, postDisposalWrites: 0, trackerDisposeCalls: 0,
            listenerDisposeCalls: { start: 0, terminate: 0 }, listenersActive: 0,
            errors: [], logs: [], startOperations: [], startOutcomes: [], stopOutcomes: [] };
        helpers.push(helper);
        // Enumerating editor namespaces can invoke gated proposed-API getters.
        // Forward only the stable surface exercised by runtime/web helpers.
        const window = {
            withProgress: (...args) => vscode.window.withProgress(...args),
            showWarningMessage: (...args) => vscode.window.showWarningMessage(...args),
        };
        Object.defineProperty(window, 'activeTextEditor', { get() {
            const editor = vscode.window.activeTextEditor;
            if (!editor || !options.saveGate) return editor;
            const target = editor.document;
            // TextDocument can expose frozen own methods, so a Proxy override
            // violates its invariants. Forward only the runtime's document API.
            const document = {
                get uri() { return target.uri; },
                get isDirty() { return target.isDirty; },
                getText: () => target.getText(),
                save: async () => {
                    helper.saveRequests++;
                    options.saveEntered.resolve();
                    await options.saveGate.promise;
                    return target.save();
                },
            };
            return { document };
        } });
        window.createOutputChannel = () => {
            const channel = vscode.window.createOutputChannel(`Disposal control ${label}`);
            let disposed = false;
            const append = (method, value) => {
                if (disposed) helper.postDisposalWrites++;
                assert(!disposed, 'Runtime wrote to an already-disposed control output channel');
                helper.logs.push(String(value));
                channel[method](value);
            };
            return { append: value => append('append', value), appendLine: value => append('appendLine', value),
                dispose() { helper.outputDisposeCalls++; disposed = true; channel.dispose(); record('helper-output-disposed', helperState(helper)); } };
        };
        window.showErrorMessage = (...args) => { helper.errors.push(args[0]); return vscode.window.showErrorMessage(...args); };
        const debug = { stopDebugging: (...args) => {
            const item = { sessionId: args[0]?.id, requestedAtMilliseconds: elapsed() };
            helper.stopOutcomes.push(item);
            record('helper-stop-request', { label, ...item });
            let operation;
            try { operation = vscode.debug.stopDebugging(...args); }
            catch (error) {
                item.rejectedAtMilliseconds = elapsed(); item.error = String(error);
                record('helper-stop-rejected', { label, ...item }); throw error;
            }
            void Promise.resolve(operation).then(() => observe('helper-stop-resolved', () => {
                item.resolvedAtMilliseconds = elapsed(); record('helper-stop-resolved', { label, ...item }); state();
            }), error => observe('helper-stop-rejected', () => {
                item.rejectedAtMilliseconds = elapsed(); item.error = String(error);
                record('helper-stop-rejected', { label, ...item }); state();
            }));
            return operation;
        } };
        debug.registerDebugAdapterTrackerFactory = (...args) => {
            const tracker = vscode.debug.registerDebugAdapterTrackerFactory(...args);
            return { dispose() { helper.trackerDisposeCalls++; tracker.dispose(); } };
        };
        for (const [kind, method] of [['start', 'onDidStartDebugSession'], ['terminate', 'onDidTerminateDebugSession']]) {
            debug[method] = callback => {
                helper.listenersActive++;
                const subscription = vscode.debug[method](callback);
                return { dispose() { helper.listenerDisposeCalls[kind]++; helper.listenersActive--; subscription.dispose(); } };
            };
        }
        debug.startDebugging = (...args) => {
            helper.startRequests++;
            const item = { requestedAtMilliseconds: elapsed(), program: args[1]?.program };
            helper.startOutcomes.push(item);
            record('helper-start-request', { label, ...item });
            const operation = (async () => {
                if (options.startGate) {
                    options.startEntered.resolve(args[1]);
                    await options.startGate.promise;
                }
                item.actualInvokedAtMilliseconds = elapsed();
                record('helper-actual-start-invoked', { label, ...item });
                return vscode.debug.startDebugging(...args);
            })();
            helper.startOperations.push(operation);
            void operation.then(value => observe('helper-start-resolved', () => {
                item.resolvedAtMilliseconds = elapsed(); item.result = value;
                record('helper-start-resolved', { label, ...item }); state();
            }), error => observe('helper-start-rejected', () => {
                item.rejectedAtMilliseconds = elapsed(); item.error = String(error);
                record('helper-start-rejected', { label, ...item }); state();
            }));
            return operation;
        };
        const commands = { executeCommand: (...args) => vscode.commands.executeCommand(...args) };
        commands.registerCommand = (_name, callback) => {
            const registration = vscode.commands.registerCommand(`local.disposal-control.${label}`, callback);
            return { dispose() { helper.registeredDisposeCalls++; registration.dispose(); } };
        };
        const context = { globalStorageUri: vscode.Uri.file(helper.storage), subscriptions: helper.subscriptions,
            extension: { packageJSON: extension.packageJSON } };
        const workspace = {
            get isTrusted() { return vscode.workspace.isTrusted; },
            getWorkspaceFolder: (...args) => vscode.workspace.getWorkspaceFolder(...args),
        };
        helper.api = runtime.activate(context, { vscode: {
            ProgressLocation: vscode.ProgressLocation, workspace, window, debug, commands,
        },
            findDotnet: () => { helper.sdkFinderCalls++; return runtime.findDotnet(process.env); } });
        helper.dispose = () => {
            helper.disposedAtMilliseconds ??= elapsed();
            for (const disposable of [...helper.subscriptions]) disposable.dispose();
            record('helper-full-subscriptions-disposed', helperState(helper));
            state();
        };
        return helper;
    }
    async function drained(helper) {
        await until(() => helper.outputDisposeCalls === 1 && helper.listenersActive === 0, `${helper.label} resource drain`);
        assert.equal(helper.registeredDisposeCalls, 1);
        assert.deepEqual(helper.listenerDisposeCalls, { start: 1, terminate: 1 });
        assert.equal(helper.trackerDisposeCalls, 1);
        assert.equal(helper.postDisposalWrites, 0);
        assert.deepEqual(helper.errors, []);
        const expectedStops = helper.label === 'save-A' ? [0] : helper.label === 'active-A' ? [1] : [1, 2];
        assert(expectedStops.includes(helper.stopOutcomes.length), 'Only the bounded exact-session Stop attempts are permitted');
        helper.postDisposalResult = await helper.api.debugActiveFile();
        assert.equal(helper.postDisposalResult, false);
        state();
    }
    async function failureCleanup() {
        for (const gate of gates) gate.resolve();
        for (const helper of helpers) {
            try { helper.dispose(); } catch (error) { result.cleanup.push({ label: helper.label, disposeError: String(error) }); }
        }
        try {
            await bounded(Promise.allSettled(helpers.flatMap(helper => helper.startOperations)),
                'failure cleanup original start outcomes', 15000);
        } catch (error) { result.cleanup.push({ originalStartDrainError: String(error) }); }
        for (const launch of launches.slice().reverse()) {
            for (const owned of launch.sessions.values()) {
                const cleanup = { label: launch.label, sessionId: owned.session.id };
                result.cleanup.push(cleanup);
                try { if (!owned.terminated) await bounded(vscode.debug.stopDebugging(owned.session), 'failure exact Stop', 5000); }
                catch (error) { cleanup.stopError = String(error); }
                const pid = owned.pid || (owned.session.id === launch.session?.id ? launch.pid : undefined);
                try {
                    if (pid && pidAlive(pid)) {
                        const body = await request(launch.origin);
                        assert.equal(body.pid, pid); assert.equal(body.nonce, launch.nonce);
                        await request(launch.origin, `/shutdown?token=${encodeURIComponent(launch.nonce)}`, { method: 'POST' });
                        cleanup.verifiedFixtureShutdownRequested = true;
                    }
                } catch (error) { cleanup.fixtureShutdownError = String(error); }
            }
        }
    }

    try {
        subscriptions.push(vscode.debug.onDidStartDebugSession(session => observe('editor-start', () => {
            const launch = capture(session); if (!launch) return;
            launch.startedAtMilliseconds = elapsed(); record('editor-start', launchState(launch)); state();
        })));
        subscriptions.push(vscode.debug.onDidTerminateDebugSession(session => observe('editor-terminate', () => {
            const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN);
            const owned = launch?.sessions.get(session.id); if (!owned) return;
            owned.terminated = true;
            if (launch.session?.id === session.id) { launch.terminated = true; launch.terminatedAtMilliseconds = elapsed(); }
            record('editor-terminate', launchState(launch)); state();
        })));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr', { createDebugAdapterTracker(session) {
            const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN); if (!launch) return undefined;
            observe('adapter-capture', () => capture(session));
            return { onWillReceiveMessage(message) { observe('adapter-request', () => {
                if (message.type === 'request' && DAP_COMMANDS.has(message.command)) {
                    record('dap-request', { label: launch.label, sessionId: session.id, message });
                }
            }); }, onDidSendMessage(message) { observe('adapter-message', () => {
                if (message.type === 'response' && DAP_COMMANDS.has(message.command)) {
                    record('dap-response', { label: launch.label, sessionId: session.id, message });
                }
                if (message.event === 'process' && message.body?.isLocalProcess) {
                    const pid = message.body.systemProcessId; assert(Number.isSafeInteger(pid) && pid > 0);
                    const owned = launch.sessions.get(session.id); owned.pid = pid;
                    if (launch.pid) assert.equal(launch.pid, pid); launch.pid = pid;
                    record('debuggee-process', { label: launch.label, sessionId: session.id, pid }); state();
                }
                if (message.event === 'module' && /System\.Private\.CoreLib|Microsoft\.AspNetCore/.test(message.body?.module?.name || '')) {
                    launch.coreRuntimeModules.push(message.body.module.path);
                }
                if (['initialized', 'stopped', 'continued', 'exited', 'terminated'].includes(message.event)) {
                    record('adapter-event', { label: launch.label, sessionId: session.id, message });
                }
            }); }, onError(error) { record('adapter-error', { label: launch.label, error: String(error) }); } };
        } }));

        const extension = await phase('verify installed candidate and activate native adapter', async () => {
            const target = vscode.extensions.getExtension(expected.extensionId);
            assert(target && within(path.join(root, 'extensions'), target.extensionPath));
            // Extension.packageJSON omits installer-private __metadata. Inspect
            // the installed file and separately match its public API identity.
            const metadata = JSON.parse(fs.readFileSync(path.join(target.extensionPath, 'package.json'), 'utf8'));
            assert(metadata.__metadata, 'Normally installed candidate metadata must exist');
            assert.equal(`${metadata.publisher}.${metadata.name}`, expected.extensionId);
            assert.equal(target.id.toLowerCase(), expected.extensionId.toLowerCase());
            assert.equal(target.packageJSON.version, metadata.version);
            assert.equal(target.packageJSON.main, metadata.main);
            assert.deepEqual(target.packageJSON.netcoredbgBuild, metadata.netcoredbgBuild);
            assert.equal(metadata.main, './.netcoredbg/entry.cjs');
            assert.equal(metadata.netcoredbgBuild.localCandidate, true);
            assert.equal(metadata.netcoredbgBuild.lifecycleBuildId, expected.candidate.buildId);
            assert.equal(metadata.netcoredbgBuild.target, `${process.platform}-${process.arch}`);
            result.installedModules = {};
            for (const name of MODULES) {
                const actual = hash(path.join(target.extensionPath, '.netcoredbg', name));
                assert.equal(actual, expected.candidate.ownedModules[name]); result.installedModules[name] = actual;
            }
            result.installedExtension = { path: target.extensionPath, version: metadata.version,
                build: metadata.netcoredbgBuild, metadata: metadata.__metadata };
            const dependency = vscode.extensions.getExtension('ms-dotnettools.vscode-dotnet-runtime');
            assert(dependency && within(path.join(root, 'extensions'), dependency.extensionPath));
            assert.equal(dependency.packageJSON.version, expected.dependency.version);
            result.installedDependency = { path: dependency.extensionPath, version: dependency.packageJSON.version };
            await target.activate();
            return target;
        });
        const runtime = require(path.join(extension.extensionPath, '.netcoredbg/runtime.cjs'));
        const aSource = path.join(root, 'workspace/a.cs');
        const bSource = path.join(root, 'workspace/b.cs');
        const b = await phase('B installed-public-command real Web readiness', async () => {
            const launch = await newLaunch('B', bSource);
            launch.commandResult = await vscode.commands.executeCommand(COMMAND);
            assert.equal(launch.commandResult, true); await ready(launch); return launch;
        });
        await phase('pending real source save cannot begin SDK/debug work after disposal', async () => {
            const a = await newLaunch('save-A', aSource);
            const document = await vscode.workspace.openTextDocument(aSource);
            const edit = new vscode.WorkspaceEdit(); edit.insert(document.uri, document.positionAt(document.getText().length), '\n// disposal save control\n');
            assert.equal(await vscode.workspace.applyEdit(edit), true); assert(document.isDirty);
            const saveGate = deferred(); const saveEntered = deferred(); gates.push(saveGate);
            const helper = helperContext(a.label, runtime, extension, { saveGate, saveEntered }); a.helperStorage = helper.storage;
            const command = helper.api.debugActiveFile();
            await entryBeforeCommand(saveEntered, command, helper, 'pending real document save');
            assert.equal(helper.sdkFinderCalls, 0); helper.dispose(); helper.dispose();
            saveGate.resolve();
            a.commandResult = await bounded(command, 'save completion after disposal');
            assert.equal(a.commandResult, false); assert.equal(document.isDirty, false);
            assert.equal(helper.saveRequests, 1); assert.equal(helper.sdkFinderCalls, 0);
            assert.equal(helper.startRequests, 0); assert.equal(a.sessions.size, 0);
            await drained(helper); await preserved(b);
            result.checks.push('Real dirty save completes after disposal, but no SDK discovery/build/debug handoff begins and subsequent command returns false');
        });
        await phase('active helper disposal releases exact A resources and preserves B', async () => {
            const a = await newLaunch('active-A', aSource);
            const helper = helperContext(a.label, runtime, extension); a.helperStorage = helper.storage;
            a.commandResult = await helper.api.debugActiveFile(); assert.equal(a.commandResult, true);
            await ready(a); await preserved(b);
            helper.dispose(); helper.dispose();
            await released(a); await drained(helper); await preserved(b);
            result.checks.push('Active direct-runtime A disposal terminates its exact session/PID, releases port/output and preserves installed-command B');
        });
        await phase('pending handoff disposal observes and stops actual late session', async () => {
            const a = await newLaunch('late-A', aSource);
            const startGate = deferred(); const startEntered = deferred(); gates.push(startGate);
            const helper = helperContext(a.label, runtime, extension, { startGate, startEntered }); a.helperStorage = helper.storage;
            const command = helper.api.debugActiveFile();
            const config = await entryBeforeCommand(startEntered, command, helper, 'pending actual start request');
            assert(within(helper.storage, config.program));
            helper.dispose(); helper.dispose();
            a.commandResult = await bounded(command, 'disposed foreground returns'); assert.equal(a.commandResult, false);
            assert.equal(helper.outputDisposeCalls, 0, 'Output must survive unresolved original start');
            assert.equal(helper.listenersActive, 2, 'Lifecycle observers must survive unresolved original start');
            assert(exists(config.program)); assert.equal(a.sessions.size, 0);
            await preserved(b);
            record('releasing-late-actual-start', { label: a.label, program: config.program });
            startGate.resolve();
            await until(() => a.sessions.size === 1, 'late real session capture');
            await released(a); await drained(helper); await preserved(b);
            result.checks.push('Disposed foreground returns false; actual delayed start is captured, terminated and cleaned without losing B');
        });
        await phase('B final exact Stop and owned resource release', async () => {
            await vscode.debug.stopDebugging(b.session); await released(b);
        });
        if (observerError) throw observerError;
        for (const helper of helpers) {
            assert.equal(helper.postDisposalWrites, 0);
            assert.equal(helper.trackerDisposeCalls, 1);
        }
        result.success = true;
    } catch (error) {
        result.firstFailure ||= { atMilliseconds: elapsed(), error: error.stack || String(error) };
        record('first-failure', result.firstFailure); state();
        await failureCleanup(); throw error;
    } finally {
        for (const subscription of subscriptions.reverse()) subscription.dispose();
        result.elapsedMilliseconds = elapsed(); result.launches = launches.map(launchState);
        result.helperContexts = helpers.map(helperState);
        result.helperLogs = helpers.map(helper => ({ label: helper.label, lines: helper.logs }));
        state(); fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
