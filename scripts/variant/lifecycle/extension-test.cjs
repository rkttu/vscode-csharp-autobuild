'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const vscode = require('vscode');

const COMMAND = 'netcoredbg.debugActiveFile';
const MODULES = ['entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs'];
// Test safety limits are not calibrated product latency budgets.
const SAFETY_TIMEOUT_MS = 90000;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const elapsed = start => Number(process.hrtime.bigint() - start) / 1e6;
const sha256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const samePath = (left, right) => process.platform === 'win32'
    ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
    : path.resolve(left) === path.resolve(right);

function within(directory, file) {
    const relative = path.relative(path.resolve(directory), path.resolve(file));
    return relative !== '' && !path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`);
}

function exists(file) {
    try { fs.lstatSync(file); return true; }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

function pidAlive(pid) {
    assert(Number.isSafeInteger(pid) && pid > 0, 'Expected a captured positive debuggee PID');
    try { process.kill(pid, 0); return true; }
    catch (error) { if (error.code === 'ESRCH') return false; throw error; }
}

async function bounded(promise, label, milliseconds = SAFETY_TIMEOUT_MS) {
    let timer;
    try {
        return await Promise.race([promise, new Promise((_, reject) => {
            timer = setTimeout(() => reject(new Error(`Safety timeout: ${label}`)), milliseconds);
        })]);
    } finally { clearTimeout(timer); }
}

async function waitUntil(predicate, label, milliseconds = SAFETY_TIMEOUT_MS) {
    const start = process.hrtime.bigint();
    while (!await predicate()) {
        if (elapsed(start) >= milliseconds) throw new Error(`Safety timeout: ${label}`);
        await delay(25);
    }
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
    assert.equal(response.status, 200, `Unexpected fixture HTTP status at ${origin}${endpoint}`);
    return response.json();
}

function queueEmpty(base) {
    for (const name of ['terminal-cleanup-v1', 'terminal-cleanup-staging-v1']) {
        const directory = path.join(base, name);
        if (exists(directory) && fs.readdirSync(directory).length !== 0) return false;
    }
    return true;
}

exports.run = async function run() {
    const configuredRoot = process.env.NETCOREDBG_LIFECYCLE_ROOT;
    assert(configuredRoot && path.isAbsolute(configuredRoot), 'NETCOREDBG_LIFECYCLE_ROOT must be an absolute isolated artifact path');
    const root = path.resolve(configuredRoot);
    const expected = JSON.parse(fs.readFileSync(path.join(root, 'expected.json'), 'utf8'));
    assert.equal(expected.schema, 1);
    assert(Number.isInteger(expected.cycles) && expected.cycles >= 2 && expected.cycles <= 10);
    const start = process.hrtime.bigint();
    const result = {
        schema: 1, success: false, expected, editorApiVersion: vscode.version,
        safetyTimeoutMilliseconds: SAFETY_TIMEOUT_MS, checks: [], phases: [], launches: [], cleanup: [],
        scope: { installedCandidate: true, invocation: 'command-api', physicalF5: false,
            VSCodium: true, platform: `${process.platform}-${process.arch}`, macOS: process.platform === 'darwin',
            qualification: false, localOnly: true, published: false, directWebDebuggee: true,
            spawnedGrandchildren: false, hostReload: false, injectedTargetRuntime: false },
    };
    const launches = [];
    const byToken = new Map();
    const subscriptions = [];
    const breakpoints = [];
    let eventError;
    let rejectObserver;
    const observerFailure = new Promise((_, reject) => { rejectObserver = reject; });
    // Observe an error even between phases; each phase also races this Promise.
    observerFailure.catch(() => {});
    const traceFile = path.join(root, 'trace.jsonl');
    fs.mkdirSync(path.join(root, 'progress'), { recursive: true });
    fs.writeFileSync(traceFile, '');

    function record(event, detail) {
        fs.appendFileSync(traceFile, JSON.stringify({ atMilliseconds: elapsed(start), event, detail }) + '\n');
    }

    function state() {
        fs.writeFileSync(path.join(root, 'progress/state.json'), JSON.stringify({
            schema: 1, root, elapsedMilliseconds: elapsed(start), firstFailure: result.firstFailure,
            launches: launches.map(launch => ({
                label: launch.label, source: launch.source, revision: launch.revision, nonce: launch.nonce,
                origin: launch.origin, port: launch.port, pid: launch.pid, sessionId: launch.session?.id,
                program: launch.program, output: launch.output, terminated: launch.terminated,
                commandPending: launch.commandPending,
                stopRequestedAtMilliseconds: launch.stopRequestedAtMilliseconds,
                stopPromiseResolvedAtMilliseconds: launch.stopPromiseResolvedAtMilliseconds,
                terminatedAtMilliseconds: launch.terminatedAtMilliseconds,
            })),
        }, null, 2) + '\n');
    }

    function observe(event, action) {
        try { return action(); }
        catch (error) {
            // An event listener exception must fail the run, not be swallowed by
            // the editor's event dispatcher and become a later timeout.
            if (!eventError) {
                eventError = error;
                result.firstFailure = { atMilliseconds: elapsed(start), event, error: error.stack || String(error) };
                result.firstCallbackError = result.firstFailure;
                record('observer-failure', result.firstFailure);
                state();
                rejectObserver(error);
            }
            return undefined;
        }
    }

    async function until(predicate, label, milliseconds = SAFETY_TIMEOUT_MS) {
        return waitUntil(async () => {
            if (eventError) throw eventError;
            return predicate();
        }, label, milliseconds);
    }

    async function phase(label, action) {
        const phaseStart = process.hrtime.bigint();
        const item = { label, startedAtMilliseconds: elapsed(start) };
        result.phases.push(item);
        record('phase-start', { label });
        try {
            if (eventError) throw eventError;
            const value = await bounded(Promise.race([Promise.resolve().then(action), observerFailure]), label);
            if (eventError) throw eventError;
            item.outcome = 'passed';
            return value;
        } catch (error) {
            item.outcome = 'failed';
            item.error = error.stack || String(error);
            throw error;
        } finally {
            item.elapsedMilliseconds = elapsed(phaseStart);
            record('phase-end', item);
            state();
        }
    }

    function ownedLaunch(session) {
        return byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN);
    }

    function captureSession(session, launch) {
        if (launch.session) assert.equal(launch.session.id, session.id, 'One launch token must identify exactly one session');
        // Retain the exact token-matched session even if a later configuration
        // assertion fails, so failure cleanup can request its targeted stop.
        launch.session = session;
        assert.equal(session.type, 'coreclr');
        assert(within(root, session.configuration.program), 'Debuggee program must be inside this isolated artifact root');
        assert(within(root, session.configuration.__netcoredbgFileAppOutput), 'Owned output must be inside this isolated artifact root');
        assert(samePath(path.dirname(session.configuration.program), session.configuration.__netcoredbgFileAppOutput));
        launch.program = session.configuration.program;
        launch.output = session.configuration.__netcoredbgFileAppOutput;
        launch.base = path.dirname(path.dirname(launch.output));
    }

    async function ready(launch) {
        let body;
        await until(async () => {
            try { body = await request(launch.origin); }
            catch (error) {
                // A live wrong endpoint is an ownership failure, not a startup delay.
                if (error instanceof assert.AssertionError) throw error;
                launch.lastReadinessError = String(error);
                return false;
            }
            assert.equal(body.nonce, launch.nonce, 'HTTP endpoint must belong to this exact launch token');
            assert.equal(body.revision, launch.revision);
            assert.equal(body.value, 42);
            assert(Number.isSafeInteger(body.pid) && body.pid > 0);
            if (launch.pid) assert.equal(body.pid, launch.pid, 'HTTP PID must match the adapter process event');
            launch.pid = body.pid;
            assert(pidAlive(launch.pid));
            launch.response = body;
            state();
            record('http-ready', { label: launch.label, origin: launch.origin, body });
            return true;
        }, `${launch.label} owned HTTP readiness`);
    }

    async function stillAlive(launch) {
        assert(!launch.terminated, 'Unrelated session must remain active');
        assert(pidAlive(launch.pid), 'Unrelated debuggee PID must remain alive');
        assert(exists(launch.output), 'Unrelated output must remain available');
        assert(exists(launch.program), 'Unrelated DLL must remain available');
        assert.deepEqual(await request(launch.origin), launch.response, 'Unrelated endpoint must retain its nonce, PID, revision and value');
        record('unrelated-preserved', { label: launch.label, sessionId: launch.session.id, pid: launch.pid });
    }

    async function stop(launch) {
        assert(launch.session, 'Stop requires this launch\'s exact captured session');
        launch.stopRequestedAtMilliseconds = elapsed(start);
        record('stop-request', { label: launch.label, sessionId: launch.session.id, pid: launch.pid });
        await vscode.debug.stopDebugging(launch.session);
        launch.stopPromiseResolvedAtMilliseconds = elapsed(start);
        record('stop-promise-resolved', { label: launch.label, sessionId: launch.session.id,
            terminationObserved: !!launch.terminated, programExists: exists(launch.program) });
        state();
        await until(() => launch.terminated, `${launch.label} matching editor termination`);
        await until(() => !pidAlive(launch.pid), `${launch.label} debuggee PID exit`);
        launch.pidGoneAtMilliseconds = elapsed(start);
        await until(() => canBind(launch.port), `${launch.label} HTTP port rebind`);
        launch.portReusableAtMilliseconds = elapsed(start);
        await until(() => !exists(launch.output) && queueEmpty(launch.base), `${launch.label} owned output and terminal queues cleanup`);
        launch.outputRemovedAtMilliseconds = elapsed(start);
        record('owned-resources-released', { label: launch.label, pid: launch.pid, port: launch.port, output: launch.output });
        state();
    }

    async function launchFile(label, source, revision, port, inspectBreakpoint = false, document) {
        const nonce = crypto.randomUUID();
        const launch = { label, source, revision, nonce, port, origin: `http://127.0.0.1:${port}`, dap: [] };
        launches.push(launch);
        byToken.set(nonce, launch);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        const opened = document || await vscode.workspace.openTextDocument(source);
        await vscode.window.showTextDocument(opened);
        launch.commandPending = true;
        state();
        try {
            assert.equal(await vscode.commands.executeCommand(COMMAND), true, `${label} installed command must start debugging`);
        } finally {
            launch.commandPending = false;
            state();
        }
        assert.equal(opened.isDirty, false, 'Installed command must save the dirty source before building');
        await until(() => launch.started, `${label} exact owned session start`);
        assert(exists(launch.program));
        assert(exists(launch.output));
        assert.equal(launch.session.configuration.env.ASPNETCORE_URLS, launch.origin);
        assert.equal(launch.session.configuration.serverReadyAction, undefined);
        assert.equal(launch.session.configuration.checkForDevCert, false);
        assert(!launches.some(previous => previous !== launch && previous.output === launch.output), 'Every launch needs a fresh output directory');
        if (inspectBreakpoint) {
            await until(() => launch.dap.some(message => message.event === 'stopped' && message.body?.reason === 'breakpoint'), `${label} source breakpoint`);
            const stopped = launch.dap.find(message => message.event === 'stopped' && message.body?.reason === 'breakpoint');
            const frames = (await launch.session.customRequest('stackTrace', { threadId: stopped.body.threadId })).stackFrames;
            assert(samePath(frames[0].source.path, source));
            const expectedLine = opened.getText().split(/\r?\n/).findIndex(line => line.trim() === 'marker += 2;') + 1;
            assert.equal(frames[0].line, expectedLine);
            const evaluated = await launch.session.customRequest('evaluate', { frameId: frames[0].id, expression: 'marker', context: 'watch' });
            assert.equal(evaluated.result, '40');
            result.checks.push('A source breakpoint binds and evaluates marker=40 through the installed native adapter');
            vscode.debug.removeBreakpoints(breakpoints);
            breakpoints.length = 0;
            await launch.session.customRequest('continue', { threadId: stopped.body.threadId });
        }
        await ready(launch);
        return launch;
    }

    async function failureCleanup() {
        // Keep evidence when exact API stop or fixture ownership verification fails.
        // Do not issue global Stop, process-tree kill or filesystem cleanup.
        for (const launch of launches.slice().reverse()) {
            const cleanup = { label: launch.label, sessionId: launch.session?.id };
            result.cleanup.push(cleanup);
            try {
                if (launch.session && !launch.terminated) {
                    await bounded(vscode.debug.stopDebugging(launch.session), `failure cleanup exact session ${launch.label}`, 5000);
                    cleanup.exactSessionStopRequested = true;
                }
            } catch (error) { cleanup.sessionStopError = String(error); }
            try {
                if (launch.pid && pidAlive(launch.pid)) {
                    const body = await request(launch.origin);
                    assert.equal(body.pid, launch.pid);
                    assert.equal(body.nonce, launch.nonce);
                    await request(launch.origin, `/shutdown?token=${encodeURIComponent(launch.nonce)}`, { method: 'POST' });
                    cleanup.verifiedFixtureShutdownRequested = true;
                }
            } catch (error) { cleanup.fixtureShutdownError = String(error); }
            try {
                if (launch.pid) {
                    await waitUntil(() => !pidAlive(launch.pid), `failure cleanup PID ${launch.pid}`, 5000);
                    cleanup.pidGone = true;
                }
            } catch (error) { cleanup.pidExitError = String(error); }
            state();
        }
    }

    try {
        subscriptions.push(vscode.debug.onDidStartDebugSession(session => observe('editor-start', () => {
            const launch = ownedLaunch(session);
            if (!launch) return;
            captureSession(session, launch);
            launch.started = true;
            launch.startedAtMilliseconds = elapsed(start);
            record('editor-start', { label: launch.label, sessionId: session.id, configuration: session.configuration });
            state();
        })));
        subscriptions.push(vscode.debug.onDidTerminateDebugSession(session => observe('editor-terminate', () => {
            const launch = ownedLaunch(session);
            if (!launch || launch.session?.id !== session.id) return;
            launch.terminated = true;
            launch.terminatedAtMilliseconds = elapsed(start);
            record('editor-terminate', { label: launch.label, sessionId: session.id,
                programExists: exists(launch.program), outputExists: exists(launch.output) });
            state();
        })));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
            createDebugAdapterTracker(session) {
                const launch = ownedLaunch(session);
                if (!launch) return undefined;
                if (!observe('adapter-session', () => { captureSession(session, launch); return true; })) return undefined;
                return {
                    onWillReceiveMessage(message) { observe('dap-send', () => record('dap-send', { label: launch.label, sessionId: session.id, message })); },
                    onDidSendMessage(message) { observe('dap-receive', () => {
                        launch.dap.push(message);
                        if (message.event === 'process' && message.body?.isLocalProcess === true) {
                            const pid = message.body.systemProcessId;
                            assert(Number.isSafeInteger(pid) && pid > 0, 'Adapter must report a positive local debuggee PID');
                            if (launch.pid) assert.equal(launch.pid, pid);
                            launch.pid = pid;
                            state();
                        }
                        record('dap-receive', { label: launch.label, sessionId: session.id, message });
                    }); },
                    onError(error) { observe('adapter-error', () => record('adapter-error', { label: launch.label, error: String(error) })); },
                };
            },
        }));

        await phase('verify installed local candidate', async () => {
            const dependency = vscode.extensions.getExtension('ms-dotnettools.vscode-dotnet-runtime');
            assert(dependency, 'Pinned runtime dependency must be normally installed');
            assert(within(path.join(root, 'extensions'), dependency.extensionPath));
            assert.equal(dependency.packageJSON.version, expected.dependency.version);
            result.installedDependency = { path: dependency.extensionPath, version: dependency.packageJSON.version };
            const extension = vscode.extensions.getExtension(expected.extensionId);
            assert(extension, 'Candidate extension must be normally installed');
            assert(within(path.join(root, 'extensions'), extension.extensionPath));
            const metadata = JSON.parse(fs.readFileSync(path.join(extension.extensionPath, 'package.json'), 'utf8'));
            assert(metadata.__metadata, 'Editor installer metadata must exist');
            assert.match(metadata.displayName, /LOCAL/);
            assert.equal(metadata.netcoredbgBuild.localCandidate, true);
            assert.equal(metadata.netcoredbgBuild.lifecycleBuildId, expected.candidate.buildId);
            assert.equal(metadata.netcoredbgBuild.target, expected.candidate.target);
            assert.equal(`${process.platform}-${process.arch}`, expected.candidate.target, 'Editor host and candidate must have matching native architecture');
            assert.equal(metadata.main, './.netcoredbg/entry.cjs');
            assert.deepEqual(Object.keys(expected.candidate.ownedModules).sort(), [...MODULES].sort());
            result.installedModules = {};
            for (const name of MODULES) {
                const actual = sha256(path.join(extension.extensionPath, '.netcoredbg', name));
                assert.equal(actual, expected.candidate.ownedModules[name], `Installed module hash: ${name}`);
                result.installedModules[name] = actual;
            }
            result.installedExtension = { path: extension.extensionPath, version: metadata.version,
                displayName: metadata.displayName, metadata: metadata.__metadata, build: metadata.netcoredbgBuild };
            await extension.activate();
            assert((await vscode.commands.getCommands(true)).includes(COMMAND));
            result.checks.push('Normally installed local candidate activates with exact owned module hashes and isolated loaded path');
        });

        const aSource = path.join(root, 'workspace/a.cs');
        const bSource = path.join(root, 'workspace/b.cs');
        const document = await vscode.workspace.openTextDocument(aSource);
        const line = document.getText().split(/\r?\n/).findIndex(value => value.trim() === 'marker += 2;');
        assert(line >= 0, 'Fixture breakpoint statement must exist');
        const breakpoint = new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(line, 0)));
        breakpoints.push(breakpoint);
        vscode.debug.addBreakpoints(breakpoints);
        const aPort = await availablePort();
        let bPort;
        do { bPort = await availablePort(); } while (bPort === aPort);
        let a = await phase('A initial installed-command launch and breakpoint', () => launchFile('A-0', aSource, 'initial', aPort, true, document));
        const b = await phase('B independent installed-command launch', () => launchFile('B', bSource, 'initial', bPort));
        result.checks.push('Two independent real Web sessions respond with distinct owned nonces and PIDs');
        assert.notEqual(a.pid, b.pid);
        assert.notEqual(a.session.id, b.session.id);

        for (let cycle = 0; cycle < expected.cycles; cycle++) {
            await phase(`A cycle ${cycle} targeted stop and owned cleanup`, () => stop(a));
            await phase(`B preserved after A cycle ${cycle}`, () => stillAlive(b));
            result.checks.push(`A cycle ${cycle}: exact session terminates, PID exits, port rebinds and output/terminal queues clear while B survives`);
            if (cycle + 1 < expected.cycles) {
                const revision = `retry-${cycle + 1}`;
                await phase(`A cycle ${cycle + 1} dirty edit and installed-command retry`, async () => {
                    const current = await vscode.workspace.openTextDocument(aSource);
                    const content = current.getText();
                    assert(content.includes(`const string revision = "${a.revision}";`));
                    const replacement = content.replace(`const string revision = "${a.revision}";`, `const string revision = "${revision}";`);
                    const edit = new vscode.WorkspaceEdit();
                    edit.replace(current.uri, new vscode.Range(current.positionAt(0), current.positionAt(content.length)), replacement);
                    assert.equal(await vscode.workspace.applyEdit(edit), true);
                    assert.equal(current.isDirty, true, 'Retry must exercise the installed command\'s source save');
                    a = await launchFile(`A-${cycle + 1}`, aSource, revision, aPort, false, current);
                    assert.equal(fs.readFileSync(aSource, 'utf8'), current.getText());
                });
            }
        }
        await phase('B final targeted stop and owned cleanup', () => stop(b));
        result.checks.push('B final stop releases its exact PID, HTTP port and owned output');
        if (eventError) throw eventError;
        result.success = true;
    } catch (error) {
        result.firstFailure ||= { atMilliseconds: elapsed(start), error: error.stack || String(error) };
        record('first-failure', result.firstFailure);
        state();
        await failureCleanup();
        throw error;
    } finally {
        vscode.debug.removeBreakpoints(breakpoints);
        for (const subscription of subscriptions.reverse()) subscription.dispose();
        result.elapsedMilliseconds = elapsed(start);
        result.launches = launches.map(launch => ({
            label: launch.label, source: launch.source, revision: launch.revision, nonce: launch.nonce,
            origin: launch.origin, port: launch.port, pid: launch.pid, sessionId: launch.session?.id,
            program: launch.program, output: launch.output, response: launch.response,
            commandPending: launch.commandPending,
            startedAtMilliseconds: launch.startedAtMilliseconds,
            stopRequestedAtMilliseconds: launch.stopRequestedAtMilliseconds,
            stopPromiseResolvedAtMilliseconds: launch.stopPromiseResolvedAtMilliseconds,
            terminatedAtMilliseconds: launch.terminatedAtMilliseconds,
            pidGoneAtMilliseconds: launch.pidGoneAtMilliseconds,
            portReusableAtMilliseconds: launch.portReusableAtMilliseconds,
            outputRemovedAtMilliseconds: launch.outputRemovedAtMilliseconds,
        }));
        state();
        fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
