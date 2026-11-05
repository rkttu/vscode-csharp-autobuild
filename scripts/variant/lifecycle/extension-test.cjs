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
    const scenario = expected.scenario || 'web-lifecycle';
    assert(['web-lifecycle', 'build-failure-retry'].includes(scenario));
    assert(Number.isInteger(expected.cycles) && expected.cycles >= 2 && expected.cycles <= 10);
    const start = process.hrtime.bigint();
    const result = {
        schema: 1, success: false, expected, editorApiVersion: vscode.version,
        safetyTimeoutMilliseconds: SAFETY_TIMEOUT_MS, checks: [], phases: [], launches: [], cleanup: [], failedBuildAttempts: [],
        scope: { installedCandidate: true, invocation: 'command-api', physicalF5: false,
            VSCodium: true, platform: `${process.platform}-${process.arch}`, macOS: process.platform === 'darwin',
            qualification: false, localOnly: true, published: false, directWebDebuggee: true,
            spawnedGrandchildren: false, hostReload: false, injectedTargetRuntime: false,
            scenario, actualCompilerFailure: scenario === 'build-failure-retry' },
    };
    const launches = [];
    const failedBuildAttempts = [];
    // Includes unexpected sessions from an intended failed build for targeted cleanup.
    const ownedAttempts = [];
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
            launches: ownedAttempts.map(launch => ({
                label: launch.label, source: launch.source, revision: launch.revision, nonce: launch.nonce,
                origin: launch.origin, port: launch.port, pid: launch.pid, sessionId: launch.session?.id,
                program: launch.program, output: launch.output, terminated: launch.terminated,
                capturedSessions: capturedSessionState(launch),
                commandPending: launch.commandPending,
                expectedBuildFailure: launch.expectedBuildFailure,
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
                const callbackFailure = { atMilliseconds: elapsed(start), event, error: error.stack || String(error) };
                result.firstFailure ||= callbackFailure;
                result.firstCallbackError = callbackFailure;
                record('observer-failure', callbackFailure);
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
        // Retain every exact token-matched session before checking uniqueness.
        // A broken coalescing path must fail without abandoning its extra session.
        launch.capturedSessions ||= new Map();
        if (!launch.capturedSessions.has(session.id)) {
            launch.capturedSessions.set(session.id, { session, program: session.configuration?.program,
                output: session.configuration?.__netcoredbgFileAppOutput });
        }
        launch.session ||= session;
        assert.equal(launch.session.id, session.id, 'One launch token must identify exactly one session');
        assert.equal(session.type, 'coreclr');
        assert(within(root, session.configuration.program), 'Debuggee program must be inside this isolated artifact root');
        assert(within(root, session.configuration.__netcoredbgFileAppOutput), 'Owned output must be inside this isolated artifact root');
        assert(samePath(path.dirname(session.configuration.program), session.configuration.__netcoredbgFileAppOutput));
        launch.program = session.configuration.program;
        launch.output = session.configuration.__netcoredbgFileAppOutput;
        launch.base = path.dirname(path.dirname(launch.output));
        assert(!launch.expectedBuildFailure, 'The compiler-failed attempt must not create a debug adapter or session');
    }

    function capturedSessionState(launch) {
        return [...(launch.capturedSessions?.values() || [])].map(captured => ({
            sessionId: captured.session.id, primary: captured.session.id === launch.session?.id,
            program: captured.program, output: captured.output, pid: captured.pid,
            terminated: captured.terminated, terminatedAtMilliseconds: captured.terminatedAtMilliseconds,
        }));
    }

    function outputLog() {
        const matches = [];
        function visit(directory) {
            if (!exists(directory)) return;
            for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
                const file = path.join(directory, entry.name);
                if (entry.isDirectory()) visit(file);
                else if (entry.isFile() && entry.name.endsWith('C# File Debugging.log')) matches.push(file);
            }
        }
        visit(path.join(root, 'profile/logs'));
        assert(matches.length <= 1, 'One isolated editor must have one unambiguous file-debugging output log');
        return matches[0];
    }

    function buildCommands(text, source) {
        const commands = [];
        for (const line of text.split(/\r?\n/)) {
            if (!line.startsWith('dotnet ')) continue;
            const payload = line.slice('dotnet '.length);
            const args = [...payload.matchAll(/"(?:\\.|[^"\\])*"/g)].map(match => JSON.parse(match[0]));
            assert.equal(args.map(value => JSON.stringify(value)).join(' '), payload, 'Build argument log must retain JSON-quoted tokens');
            if (args[0] !== 'build' || !samePath(args[1], source)) continue;
            const outputIndex = args.indexOf('--output');
            assert(outputIndex >= 0 && args[outputIndex + 1]);
            const output = args[outputIndex + 1];
            assert(path.isAbsolute(output) && within(root, output), 'Logged build output must be inside the isolated root');
            commands.push({ args, output });
        }
        return commands;
    }

    function logSnapshot(file) {
        const text = fs.readFileSync(file, 'utf8');
        return { path: file, offsetCharacters: text.length,
            prefixSha256: crypto.createHash('sha256').update(text).digest('hex') };
    }

    function logTail(snapshot) {
        const text = fs.readFileSync(snapshot.path, 'utf8');
        const prefix = text.slice(0, snapshot.offsetCharacters);
        assert.equal(crypto.createHash('sha256').update(prefix).digest('hex'), snapshot.prefixSha256,
            'Earlier output log evidence must not be replaced or truncated');
        return text.slice(snapshot.offsetCharacters);
    }

    function logEvidence(snapshot, tail, source) {
        return { ...snapshot, tailCharacters: tail.length,
            tailSha256: crypto.createHash('sha256').update(tail).digest('hex'),
            buildCommands: buildCommands(tail, source),
            compilerDiagnostics: tail.split(/\r?\n/).filter(line => line.includes('CS0103')),
            failedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase failed: Building file-based app')),
            completedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')) };
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
            const captured = launch.capturedSessions.get(launch.session.id);
            if (captured.pid) assert.equal(captured.pid, body.pid);
            captured.pid = body.pid;
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

    async function launchFile(label, source, revision, port, inspectBreakpoint = false, document, commandInvocations = 1) {
        const nonce = crypto.randomUUID();
        const launch = { label, source, revision, nonce, port, origin: `http://127.0.0.1:${port}`, dap: [] };
        launches.push(launch);
        ownedAttempts.push(launch);
        byToken.set(nonce, launch);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        const opened = document || await vscode.workspace.openTextDocument(source);
        await vscode.window.showTextDocument(opened);
        launch.commandPending = true;
        launch.commandInvocations = commandInvocations;
        state();
        try {
            // Observe every concurrent request before handling a rejection so a
            // later owned session can still be captured for failure cleanup.
            const outcomes = await Promise.allSettled(Array.from({ length: commandInvocations }, () => vscode.commands.executeCommand(COMMAND)));
            const rejected = outcomes.find(outcome => outcome.status === 'rejected');
            if (rejected) throw rejected.reason;
            launch.commandResults = outcomes.map(outcome => outcome.value);
            assert.deepEqual(launch.commandResults, Array(commandInvocations).fill(true), `${label} installed commands must start debugging`);
        } finally {
            launch.commandPending = false;
            state();
        }
        assert.equal(opened.isDirty, false, 'Installed command must save the dirty source before building');
        await until(() => launch.started, `${label} exact owned session start`);
        assert.equal(launch.capturedSessions.size, 1, 'One launch token must have exactly one captured session');
        assert(exists(launch.program));
        assert(exists(launch.output));
        assert.equal(launch.session.configuration.env.ASPNETCORE_URLS, launch.origin);
        assert.equal(launch.session.configuration.serverReadyAction, undefined);
        assert.equal(launch.session.configuration.checkForDevCert, false);
        assert(!launches.some(previous => previous !== launch && previous.output === launch.output), 'Every launch needs a fresh output directory');
        assert(!failedBuildAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse failed build output');
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

    async function compilerFailure(source, revision, port, a, b) {
        let file;
        // Start the failure window after both earlier successful commands have
        // reached the persisted log, even if the logger flushes asynchronously.
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B command output log flush');
        const snapshot = logSnapshot(file);
        const opened = await vscode.workspace.openTextDocument(source);
        const content = opened.getText();
        assert(content.includes('marker += 2;'));
        const broken = content.replace('marker += 2;', 'marker += __missingLifecycleValue;');
        const edit = new vscode.WorkspaceEdit();
        edit.replace(opened.uri, new vscode.Range(opened.positionAt(0), opened.positionAt(content.length)), broken);
        assert.equal(await vscode.workspace.applyEdit(edit), true);
        assert.equal(opened.isDirty, true, 'Compiler failure must begin with an unsaved source edit');
        await vscode.window.showTextDocument(opened);
        const attempt = { label: 'A-compile-failure', source, revision, port, origin: `http://127.0.0.1:${port}`,
            nonce: crypto.randomUUID(), expectedBuildFailure: true, dap: [] };
        failedBuildAttempts.push(attempt);
        ownedAttempts.push(attempt);
        byToken.set(attempt.nonce, attempt);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: attempt.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: attempt.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        attempt.commandPending = true;
        attempt.invokedAtMilliseconds = elapsed(start);
        record('expected-build-failure-request', { label: attempt.label, nonce: attempt.nonce });
        state();
        try { attempt.commandResult = await vscode.commands.executeCommand(COMMAND); }
        finally { attempt.commandPending = false; attempt.returnedAtMilliseconds = elapsed(start); state(); }
        assert.equal(attempt.commandResult, false, 'The actual compiler error must decline debug launch');
        assert.equal(opened.isDirty, false, 'The installed command must save the broken source');
        assert.equal(fs.readFileSync(source, 'utf8'), broken);
        attempt.sourceSaved = true;
        assert.equal(attempt.session, undefined, 'The compiler-failed attempt must have no session');
        let tail;
        await until(() => {
            tail = logTail(snapshot);
            return tail.includes('CS0103') && tail.includes('Phase failed: Building file-based app');
        }, 'actual compiler error and failed build phase output');
        attempt.log = logEvidence(snapshot, tail, source);
        assert.equal(attempt.log.buildCommands.length, 1, 'The failed attempt must execute exactly one actual build');
        attempt.output = attempt.log.buildCommands[0].output;
        attempt.program = path.join(attempt.output, 'FileApp.dll');
        attempt.base = path.dirname(path.dirname(attempt.output));
        assert(samePath(attempt.base, a.base), 'Failed and successful A output must share the known owned output base');
        assert.notEqual(attempt.output, a.output);
        assert(!exists(attempt.output), 'The exact failed output must be gone at the post-return resource check');
        assert(queueEmpty(attempt.base), 'The failed attempt must leave no terminal recovery queue');
        attempt.outputRemovedAtMilliseconds = elapsed(start);
        assert(await canBind(port), 'A compiler failure must leave the A HTTP port free');
        attempt.portReusableAtMilliseconds = elapsed(start);
        attempt.noSession = !attempt.session;
        await stillAlive(b);
        record('expected-build-failure-confirmed', { label: attempt.label, output: attempt.output, nonce: attempt.nonce,
            compilerDiagnostics: attempt.log.compilerDiagnostics, commandResult: attempt.commandResult });
        result.checks.push('Actual CS0103 returns false, saves broken source, starts no session and removes exact failed output while B survives');
        state();
        return attempt;
    }

    async function failureCleanup() {
        // Keep evidence when exact API stop or fixture ownership verification fails.
        // Do not issue global Stop, process-tree kill or filesystem cleanup.
        const visited = new Set();
        for (const launch of ownedAttempts.slice().reverse()) {
            const captured = [...(launch.capturedSessions?.values() || [])].reverse();
            if (!captured.length) captured.push({});
            for (const owned of captured) {
                const session = owned.session;
                if (session && visited.has(session.id)) continue;
                if (session) visited.add(session.id);
                const cleanup = { label: launch.label, sessionId: session?.id };
                result.cleanup.push(cleanup);
                try {
                    if (session && !owned.terminated) {
                        await bounded(vscode.debug.stopDebugging(session), `failure cleanup exact session ${launch.label}/${session.id}`, 5000);
                        cleanup.exactSessionStopRequested = true;
                    }
                } catch (error) { cleanup.sessionStopError = String(error); }
                // A tracker can receive its process event while Stop is pending.
                const pid = owned.pid || (session?.id === launch.session?.id ? launch.pid : undefined);
                cleanup.pid = pid;
                try {
                    if (pid && pidAlive(pid)) {
                        const body = await request(launch.origin);
                        assert.equal(body.pid, pid);
                        assert.equal(body.nonce, launch.nonce);
                        await request(launch.origin, `/shutdown?token=${encodeURIComponent(launch.nonce)}`, { method: 'POST' });
                        cleanup.verifiedFixtureShutdownRequested = true;
                    }
                } catch (error) { cleanup.fixtureShutdownError = String(error); }
                try {
                    if (pid) {
                        await waitUntil(() => !pidAlive(pid), `failure cleanup PID ${pid}`, 5000);
                        cleanup.pidGone = true;
                    }
                } catch (error) { cleanup.pidExitError = String(error); }
                state();
                // Include token-owned sessions captured while earlier Stops settled.
                for (const extra of launch.capturedSessions?.values() || []) {
                    if (!visited.has(extra.session.id) && !captured.includes(extra)) captured.push(extra);
                }
            }
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
            const captured = launch?.capturedSessions?.get(session.id);
            if (!captured) return;
            captured.terminated = true;
            captured.terminatedAtMilliseconds = elapsed(start);
            if (launch.session?.id === session.id) {
                launch.terminated = true;
                launch.terminatedAtMilliseconds = captured.terminatedAtMilliseconds;
            }
            record('editor-terminate', { label: launch.label, sessionId: session.id,
                programExists: typeof captured.program === 'string' && exists(captured.program),
                outputExists: typeof captured.output === 'string' && exists(captured.output) });
            state();
        })));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
            createDebugAdapterTracker(session) {
                const launch = ownedLaunch(session);
                if (!launch) return undefined;
                observe('adapter-session', () => captureSession(session, launch));
                // Keep the tracker even if uniqueness validation failed: it can
                // still identify the extra owned debuggee for targeted cleanup.
                return {
                    onWillReceiveMessage(message) { observe('dap-send', () => record('dap-send', { label: launch.label, sessionId: session.id, message })); },
                    onDidSendMessage(message) { observe('dap-receive', () => {
                        launch.dap.push(message);
                        if (message.event === 'process' && message.body?.isLocalProcess === true) {
                            const pid = message.body.systemProcessId;
                            assert(Number.isSafeInteger(pid) && pid > 0, 'Adapter must report a positive local debuggee PID');
                            const captured = launch.capturedSessions.get(session.id);
                            const earlierPid = captured.pid;
                            captured.pid = pid;
                            if (earlierPid) assert.equal(earlierPid, pid);
                            if (launch.session?.id === session.id) {
                                if (launch.pid) assert.equal(launch.pid, pid);
                                launch.pid = pid;
                            }
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
            const failed = scenario === 'build-failure-retry' && cycle === 0
                ? await phase('A actual compiler failure and owned cleanup while B survives', () => compilerFailure(aSource, a.revision, aPort, a, b))
                : undefined;
            if (cycle + 1 < expected.cycles) {
                const revision = `retry-${cycle + 1}`;
                await phase(`A cycle ${cycle + 1} dirty edit and installed-command retry`, async () => {
                    const current = await vscode.workspace.openTextDocument(aSource);
                    const content = current.getText();
                    assert(content.includes(`const string revision = "${a.revision}";`));
                    let replacement = content.replace(`const string revision = "${a.revision}";`, `const string revision = "${revision}";`);
                    if (failed) {
                        assert(content.includes('marker += __missingLifecycleValue;'));
                        replacement = replacement.replace('marker += __missingLifecycleValue;', 'marker += 2;');
                    }
                    const edit = new vscode.WorkspaceEdit();
                    edit.replace(current.uri, new vscode.Range(current.positionAt(0), current.positionAt(content.length)), replacement);
                    assert.equal(await vscode.workspace.applyEdit(edit), true);
                    assert.equal(current.isDirty, true, 'Retry must exercise the installed command\'s source save');
                    const snapshot = failed ? logSnapshot(failed.log.path) : undefined;
                    a = await launchFile(`A-${cycle + 1}`, aSource, revision, aPort, false, current, failed ? 3 : 1);
                    assert.equal(fs.readFileSync(aSource, 'utf8'), current.getText());
                    if (failed) {
                        let tail;
                        await until(() => { tail = logTail(snapshot); return tail.includes('Phase completed: Starting netcoredbg'); },
                            'corrected coalesced retry command output');
                        const log = logEvidence(snapshot, tail, aSource);
                        assert.equal(log.buildCommands.length, 1, 'Three concurrent corrected commands must share exactly one build');
                        assert.equal(log.completedPhaseDiagnostics.length, 1, 'Three concurrent corrected commands must share one handoff');
                        assert.equal(log.failedPhaseDiagnostics.length, 0);
                        assert(samePath(log.buildCommands[0].output, a.output), 'Coalesced build output must identify the one captured session');
                        assert(!exists(failed.output));
                        result.coalescedRetry = { label: a.label, commandInvocations: a.commandInvocations,
                            commandResults: a.commandResults, sessionId: a.session.id, output: a.output,
                            sessionIds: [...a.capturedSessions.keys()],
                            log, failedOutput: failed.output, freshOutput: a.output !== failed.output };
                        await stillAlive(b);
                        result.checks.push('Dirty compiler correction retries with three concurrent commands sharing one build/session and fresh output while B survives');
                        record('coalesced-corrected-retry-confirmed', result.coalescedRetry);
                    }
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
            commandInvocations: launch.commandInvocations, commandResults: launch.commandResults,
            capturedSessions: capturedSessionState(launch),
            startedAtMilliseconds: launch.startedAtMilliseconds,
            stopRequestedAtMilliseconds: launch.stopRequestedAtMilliseconds,
            stopPromiseResolvedAtMilliseconds: launch.stopPromiseResolvedAtMilliseconds,
            terminatedAtMilliseconds: launch.terminatedAtMilliseconds,
            pidGoneAtMilliseconds: launch.pidGoneAtMilliseconds,
            portReusableAtMilliseconds: launch.portReusableAtMilliseconds,
            outputRemovedAtMilliseconds: launch.outputRemovedAtMilliseconds,
        }));
        result.failedBuildAttempts = failedBuildAttempts.map(attempt => ({
            label: attempt.label, source: attempt.source, revision: attempt.revision, nonce: attempt.nonce,
            origin: attempt.origin, port: attempt.port, expectedBuildFailure: true,
            commandPending: attempt.commandPending, commandResult: attempt.commandResult,
            invokedAtMilliseconds: attempt.invokedAtMilliseconds, returnedAtMilliseconds: attempt.returnedAtMilliseconds,
            sourceSaved: attempt.sourceSaved, sessionId: attempt.session?.id, pid: attempt.pid, terminated: attempt.terminated,
            capturedSessions: capturedSessionState(attempt),
            output: attempt.output, program: attempt.program, base: attempt.base,
            outputRemovedAtMilliseconds: attempt.outputRemovedAtMilliseconds,
            portReusableAtMilliseconds: attempt.portReusableAtMilliseconds, noSession: attempt.noSession, log: attempt.log,
        }));
        state();
        fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
