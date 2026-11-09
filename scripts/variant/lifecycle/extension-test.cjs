'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const childProcess = require('node:child_process');
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
    // Observe forward publication order so a staging-to-ready rename is not missed between reads.
    for (const name of ['terminal-cleanup-staging-v1', 'terminal-cleanup-v1']) {
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
    assert(['web-lifecycle', 'build-failure-retry', 'native-build-cancel', 'web-profile-failure-retry', 'sdk-selection-failure-retry', 'debug-handoff-declined-retry', 'native-host-failure-retry', 'native-adapter-loss', 'concurrent-files', 'native-handoff-cancel', 'native-f5'].includes(scenario));
    assert(Number.isInteger(expected.cycles) && expected.cycles >= 2 && expected.cycles <= 10);
    const start = process.hrtime.bigint();
    const result = {
        schema: 1, success: false, expected, editorApiVersion: vscode.version,
        safetyTimeoutMilliseconds: SAFETY_TIMEOUT_MS, checks: [], phases: [], launches: [], cleanup: [], failedBuildAttempts: [],
        cancelledBuildAttempts: [], cancelledHandoffAttempts: [], failedWebProfileAttempts: [], failedSdkSelectionAttempts: [], failedHandoffAttempts: [], failedNativeHostAttempts: [],
        scope: { installedCandidate: true, invocation: 'command-api', physicalF5: false,
            VSCodium: true, platform: `${process.platform}-${process.arch}`, macOS: process.platform === 'darwin',
            qualification: false, localOnly: true, published: false, directWebDebuggee: true,
            spawnedGrandchildren: false, hostReload: false, injectedTargetRuntime: false,
            scenario, actualCompilerFailure: scenario === 'build-failure-retry',
            actualWebProfileFailure: scenario === 'web-profile-failure-retry',
            actualSdkSelectionFailure: scenario === 'sdk-selection-failure-retry',
            actualNativeHostFailure: scenario === 'native-host-failure-retry',
            injectedEditorRejection: scenario === 'debug-handoff-declined-retry', nativeAdapterFailure: scenario === 'native-adapter-loss',
            actualAdapterProcessKill: scenario === 'native-adapter-loss',
            concurrentSeparateFiles: scenario === 'concurrent-files',
            injectedEditorHandoffGate: scenario === 'native-handoff-cancel',
            actualProgressCancelUi: ['native-build-cancel', 'native-handoff-cancel'].includes(scenario), injectedCancellationToken: false },
    };
    const launches = [];
    const failedBuildAttempts = [];
    const failedWebProfileAttempts = [];
    const failedSdkSelectionAttempts = [];
    const failedHandoffAttempts = [];
    const failedNativeHostAttempts = [];
    const handoffProviders = new Map();
    const handoffGates = new Map();
    const cancelledHandoffAttempts = [];
    const cancelledBuildAttempts = [];
    const nativeF5 = scenario === 'native-f5' ? expected.nativeF5 : undefined;
    let nativeF5Closed = false;
    let nativeF5Operation;
    const nativeF5LateStops = [];
    if (nativeF5) {
        assert.equal(typeof nativeF5.nonce, 'string');
        assert(nativeF5.nonce.length > 0 && nativeF5.windowTitle.includes(nativeF5.nonce));
        assert.deepEqual(nativeF5.inputs.map(input => input.sequence), Array.from({ length: expected.cycles }, (_, index) => index + 1));
        const files = [nativeF5.closed, ...nativeF5.inputs.flatMap(input => [input.request, input.receipt])];
        assert.equal(new Set(files).size, 2 * expected.cycles + 1);
        for (const file of files) assert(path.isAbsolute(file) && within(root, file) && !exists(file) && !exists(file + '.tmp'));
        delete result.scope.physicalF5;
        Object.assign(result.scope, { invocation: 'native-injected-f5', nativeInjectedF5: true,
            hardwareKeypress: false, noFolderWindow: true, trustUiExercised: false,
            setupCommand: 'workbench.action.toggleKeybindingsLog', targetCommandApiLaunch: false });
        result.nativeF5 = { inputs: [], inputReceiptsAreAttestations: true,
            actualKeyEvidenceRequiredSeparately: true, setupCommands: [], postStartApiActions: [] };
    } else assert.notEqual(scenario, 'native-f5');
    const nativeCancellation = scenario === 'native-build-cancel' ? expected.nativeCancellation : undefined;
    const handoffCancellation = scenario === 'native-handoff-cancel' ? expected.handoffCancellation : undefined;
    if (handoffCancellation) {
        assert.equal(typeof handoffCancellation.nonce, 'string');
        assert(handoffCancellation.nonce.length > 0);
        assert.equal(typeof handoffCancellation.windowTitle, 'string');
        for (const name of ['request', 'receipt']) {
            assert(path.isAbsolute(handoffCancellation[name]) && within(root, handoffCancellation[name]));
            assert(!exists(handoffCancellation[name]) && !exists(handoffCancellation[name] + '.tmp'));
        }
    } else assert.notEqual(scenario, 'native-handoff-cancel');
    const concurrent = scenario === 'concurrent-files' ? expected.concurrent : undefined;
    const concurrentOperations = [];
    let concurrentStopping = false;
    if (concurrent) {
        assert.equal(concurrent.entries.length, 2);
        assert(path.isAbsolute(concurrent.target) && within(root, concurrent.target));
        assert.equal(sha256(concurrent.target), expected.harness['fixtures/concurrent-build.targets']);
        for (const entry of concurrent.entries) {
            assert.equal(typeof entry.nonce, 'string');
            assert(entry.nonce.length > 0);
            for (const key of ['source', 'marker', 'release']) assert(path.isAbsolute(entry[key]) && within(root, entry[key]));
            assert(!exists(entry.marker) && !exists(entry.marker + '.tmp') && !exists(entry.release));
        }
        assert.notEqual(concurrent.entries[0].nonce, concurrent.entries[1].nonce);
    } else assert.notEqual(scenario, 'concurrent-files');
    const adapterLoss = scenario === 'native-adapter-loss' ? expected.adapterLoss : undefined;
    if (adapterLoss) {
        assert.equal(typeof adapterLoss.nonce, 'string');
        assert(adapterLoss.nonce.length > 0);
        for (const key of ['marker', 'receipt', 'helper']) assert(path.isAbsolute(adapterLoss[key]) && within(root, adapterLoss[key]));
        assert(!exists(adapterLoss.marker) && !exists(adapterLoss.receipt));
        assert.equal(sha256(adapterLoss.helper), expected.harness['adapter-loss.ps1']);
    } else assert.notEqual(scenario, 'native-adapter-loss');
    if (nativeCancellation) {
        assert.equal(typeof nativeCancellation.nonce, 'string');
        assert(nativeCancellation.nonce.length > 0);
        assert.equal(typeof nativeCancellation.windowTitle, 'string');
        assert(nativeCancellation.windowTitle.length > 0);
        for (const name of ['marker', 'release', 'target']) {
            assert(path.isAbsolute(nativeCancellation[name]) && within(root, nativeCancellation[name]),
                `Native build ${name} must be an exact path inside the isolated root`);
        }
        assert(exists(nativeCancellation.target));
        for (const file of [nativeCancellation.marker, nativeCancellation.release,
            path.join(root, 'needs-ui-cancel.json'), path.join(root, 'ui-cancel-action.json')]) {
            assert(!exists(file), 'Native cancellation evidence must begin with fresh marker, release and UI receipt paths');
        }
    } else assert.notEqual(scenario, 'native-build-cancel', 'Native cancellation needs an explicit isolated fixture identity');
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

    function closeNativeF5(reason) {
        if (!nativeF5 || nativeF5Closed) return;
        nativeF5Closed = true;
        const detail = { schema: 1, nonce: nativeF5.nonce, reason, closedAtUtc: new Date().toISOString() };
        fs.writeFileSync(nativeF5.closed, JSON.stringify(detail, null, 2) + '\n', { flag: 'wx' });
        record('f5-input-closed', detail);
    }

    function requireNativeF5Open() {
        assert(!nativeF5Closed && !result.firstFailure, 'Native F5 input closed after completion or first failure');
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
                expectedBuildCancellation: launch.expectedBuildCancellation,
                expectedWebProfileFailure: launch.expectedWebProfileFailure,
                expectedSdkSelectionFailure: launch.expectedSdkSelectionFailure,
                expectedHandoffDeclined: launch.expectedHandoffDeclined,
                expectedNativeHostFailure: launch.expectedNativeHostFailure,
                expectedHandoffCancellation: launch.expectedHandoffCancellation,
                providerPending: launch.providerPending, gateReleased: launch.gateReleased,
                providerCallCount: launch.providerCalls?.length, providerDisposed: launch.providerDisposed,
                buildPid: launch.buildPid,
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
        assert(!launch.expectedBuildCancellation, 'The cancelled build attempt must not create a debug adapter or session');
        assert(!launch.expectedWebProfileFailure, 'The Web-profile-failed attempt must not create a debug adapter or session');
        assert(!launch.expectedSdkSelectionFailure, 'The SDK-selection-failed attempt must not create a debug adapter or session');
        assert(!launch.expectedHandoffDeclined, 'The editor-declined attempt must not create a debug adapter or session');
        if (launch.expectedNativeHostFailure && !launch.builtArtifacts) {
            const config = session.configuration;
            assert.equal(config.request, 'launch');
            assert(samePath(launch.base, launch.expectedBase));
            assert.notEqual(launch.output, launch.previousOutput);
            assert.notEqual(launch.output, launch.bBefore.output);
            assert.equal(path.basename(launch.program), 'FileApp.dll');
            assert.match(path.basename(launch.output), /^run-[A-Za-z0-9]{6}$/);
            assert(samePath(config.cwd, path.dirname(launch.source)));
            assert(samePath(config.env.DOTNET_ROOT, expected.sdk.root));
            assert.equal(config.env.DOTNET_ROLL_FORWARD, launch.invalidRollForward);
            assert.equal(config.env.ASPNETCORE_URLS, launch.origin);
            assert.equal(config.serverReadyAction, undefined);
            assert.equal(config.checkForDevCert, false);
            const outputStat = fs.lstatSync(launch.output);
            assert(outputStat.isDirectory() && !outputStat.isSymbolicLink());
            launch.builtArtifacts = ['FileApp.dll', 'FileApp.pdb', 'FileApp.runtimeconfig.json'].map(name => {
                const artifact = path.join(launch.output, name);
                const stat = fs.lstatSync(artifact);
                assert(stat.isFile() && !stat.isSymbolicLink() && stat.size > 0);
                return { path: artifact, size: stat.size, sha256: sha256(artifact) };
            });
            launch.runtimeConfigSnapshot = fileSnapshot(path.join(launch.output, 'FileApp.runtimeconfig.json'));
            const runtimeConfig = JSON.parse(Buffer.from(launch.runtimeConfigSnapshot.base64, 'base64'));
            assert(runtimeConfig.runtimeOptions.frameworks.some(framework => framework.name === 'Microsoft.NETCore.App'));
            launch.capturedConfiguration = JSON.parse(JSON.stringify(config));
            record('native-host-failure-built-artifacts', { label: launch.label, sessionId: session.id,
                configuration: launch.capturedConfiguration, artifacts: launch.builtArtifacts });
        }
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
            cancelledPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase cancelled: Building file-based app')),
            buildCompletedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Building file-based app')),
            webPreparationFailedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase failed: Preparing web launch settings')),
            webProfileRootDiagnostics: tail.split(/\r?\n/).filter(line => line.includes('The web launch profile DOTNET_ROOT does not identify the selected dotnet installation.')),
            completedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')) };
    }

    function fileSnapshot(file) {
        const bytes = fs.readFileSync(file);
        return { path: file, size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
            base64: bytes.toString('base64') };
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

    function readConcurrentMarker(entry) {
        const marker = JSON.parse(fs.readFileSync(entry.marker, 'utf8'));
        assert.equal(marker.schema, 1);
        assert.equal(marker.nonce, entry.nonce);
        assert(Number.isSafeInteger(marker.pid) && marker.pid > 0);
        assert(samePath(marker.source, entry.source));
        assert(marker.compileInputs.split(';').some(source => samePath(source, entry.source)),
            'The configured source must be an actual Compile item in this SDK process');
        assert(samePath(marker.executable, expected.sdk.executable));
        assert(path.isAbsolute(marker.output) && within(root, marker.output));
        assert.match(path.basename(path.resolve(marker.output)), /^run-[A-Za-z0-9]{6}$/);
        assert(Number.isFinite(Date.parse(marker.startUtc)));
        return marker;
    }

    async function sdkProcessSnapshot(marker) {
        const script = `$item = Get-CimInstance Win32_Process -Filter 'ProcessId=${marker.pid}'; ` +
            `if (!$item) { throw 'SDK process is absent' }; ` +
            `[ordered]@{ processId=[int]$item.ProcessId; parentProcessId=[int]$item.ParentProcessId; ` +
            `executablePath=[string]$item.ExecutablePath; commandLine=[string]$item.CommandLine; ` +
            `creationUtc=$item.CreationDate.ToUniversalTime().ToString('o') } | ConvertTo-Json -Compress`;
        const powershell = path.join(process.env.SystemRoot, 'System32/WindowsPowerShell/v1.0/powershell.exe');
        const text = await new Promise((resolve, reject) => childProcess.execFile(powershell,
            ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script],
            { windowsHide: true, encoding: 'utf8', timeout: 10000 }, (error, stdout) => error ? reject(error) : resolve(stdout)));
        const identity = JSON.parse(text.replace(/^\uFEFF/, ''));
        assert.equal(identity.processId, marker.pid);
        assert(samePath(identity.executablePath, expected.sdk.executable));
        const command = identity.commandLine.replaceAll('/', '\\').toLowerCase();
        assert(command.includes(marker.source.replaceAll('/', '\\').toLowerCase()));
        assert(command.includes(path.resolve(marker.output).replaceAll('/', '\\').toLowerCase()));
        assert(command.includes('--output'));
        assert(Math.abs(Date.parse(identity.creationUtc) - Date.parse(marker.startUtc)) <= 1,
            'The CIM process creation time must match the marker process instance');
        return identity;
    }

    function releaseConcurrentBarrier(entry, marker, safetyCleanup = false) {
        assert.equal(marker.nonce, entry.nonce);
        assert(samePath(marker.source, entry.source));
        assert(pidAlive(marker.pid), 'Only the captured live SDK barrier may be released');
        if (exists(entry.release)) {
            assert.equal(fs.readFileSync(entry.release, 'utf8').trim(), entry.nonce);
            return undefined;
        }
        const atMilliseconds = elapsed(start);
        fs.writeFileSync(entry.release, entry.nonce + '\n', { flag: 'wx' });
        const receipt = { label: entry.label, pid: marker.pid, nonce: entry.nonce,
            atMilliseconds, safetyCleanup, snapshot: fileSnapshot(entry.release) };
        record('concurrent-build-barrier-released', receipt);
        return receipt;
    }

    async function concurrentFiles(aSource, bSource, aPort, bPort, document) {
        const evidence = result.concurrent = { entries: concurrent.entries, dispatch: [], releases: [],
            targetSnapshot: fileSnapshot(concurrent.target), sourceSnapshots: concurrent.entries.map(entry => fileSnapshot(entry.source)) };
        let logFile;
        await until(() => { logFile = outputLog(); return !!logFile; }, 'output channel before concurrent commands');
        assert.equal(buildCommands(fs.readFileSync(logFile, 'utf8'), aSource).length, 0);
        assert.equal(buildCommands(fs.readFileSync(logFile, 'utf8'), bSource).length, 0);
        const initialLog = logSnapshot(logFile);
        function dispatch(entry, port, inspectBreakpoint, opened) {
            assert(!concurrentStopping);
            let resolveDispatch, rejectDispatch;
            const dispatched = new Promise((resolve, reject) => { resolveDispatch = resolve; rejectDispatch = reject; });
            const item = { label: entry.label, settled: false };
            concurrentOperations.push(item);
            item.operation = launchFile(entry.label === 'A' ? 'A-0' : 'B', entry.source, entry.revision, port,
                inspectBreakpoint, opened, 3, launch => {
                    item.launch = launch;
                    const detail = { label: entry.label, source: entry.source, activeSource: vscode.window.activeTextEditor?.document.uri.fsPath,
                        nonce: launch.nonce, commandInvocations: 3, atMilliseconds: elapsed(start) };
                    assert(samePath(detail.activeSource, entry.source));
                    evidence.dispatch.push(detail);
                    record('concurrent-file-command-dispatched', detail);
                    resolveDispatch(launch);
                });
            // Observe each partial operation immediately, including an A setup
            // failure before B is dispatched. Keep outcomes for bounded cleanup.
            item.observed = item.operation.then(value => {
                item.value = value; item.status = 'fulfilled'; item.settled = true;
            }, error => {
                item.error = error; item.status = 'rejected'; item.settled = true; rejectDispatch(error);
            });
            return { item, dispatched };
        }
        const first = dispatch(concurrent.entries[0], aPort, true, document);
        await first.dispatched; // Dispatch only; never await A's command results here.
        const second = dispatch(concurrent.entries[1], bPort, false);
        await second.dispatched;
        await until(() => {
            const failed = concurrentOperations.find(item => item.status === 'rejected');
            if (failed) throw failed.error;
            return concurrent.entries.every(entry => exists(entry.marker));
        }, 'both independent real SDK build barriers');
        const markers = concurrent.entries.map(readConcurrentMarker);
        assert.notEqual(markers[0].pid, markers[1].pid);
        for (let index = 0; index < markers.length; index++) {
            assert(!markers[index].compileInputs.split(';').some(source => samePath(source, concurrent.entries[1 - index].source)),
                'A file build must not include the other independently requested source');
        }
        const identities = [];
        for (const marker of markers) identities.push(await sdkProcessSnapshot(marker));
        let beforeReleaseTail;
        await until(() => {
            beforeReleaseTail = logTail(initialLog);
            return concurrent.entries.every(entry => buildCommands(beforeReleaseTail, entry.source).length === 1);
        }, 'one logged actual build for each held source');
        const beforeRelease = evidence.beforeFirstRelease = { atMilliseconds: elapsed(start), markers, identities,
            markerSnapshots: concurrent.entries.map(entry => fileSnapshot(entry.marker)),
            pidAlive: markers.map(marker => pidAlive(marker.pid)),
            commandPending: concurrentOperations.map(item => !!item.launch?.commandPending),
            operationsSettled: concurrentOperations.map(item => item.settled),
            releasesAbsent: concurrent.entries.map(entry => !exists(entry.release)),
            log: { ...initialLog, tailSha256: crypto.createHash('sha256').update(beforeReleaseTail).digest('hex'),
                tailCharacters: beforeReleaseTail.length,
                builds: concurrent.entries.map(entry => ({ source: entry.source, commands: buildCommands(beforeReleaseTail, entry.source) })) } };
        assert.deepEqual(beforeRelease.pidAlive, [true, true]);
        assert.deepEqual(beforeRelease.commandPending, [true, true]);
        assert.deepEqual(beforeRelease.operationsSettled, [false, false]);
        assert.deepEqual(beforeRelease.releasesAbsent, [true, true]);
        for (let index = 0; index < markers.length; index++) {
            assert(samePath(beforeRelease.log.builds[index].commands[0].output, markers[index].output));
        }
        record('concurrent-builds-held-before-first-release', beforeRelease);
        for (let index = 0; index < markers.length; index++) {
            evidence.releases.push(releaseConcurrentBarrier(concurrent.entries[index], markers[index]));
        }
        await Promise.all(concurrentOperations.map(item => item.observed));
        const failed = concurrentOperations.find(item => item.status === 'rejected');
        if (failed) throw failed.error;
        const a = first.item.value, b = second.item.value;
        let tail;
        await until(() => {
            tail = logTail(initialLog);
            return tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'two real concurrent command handoffs');
        evidence.log = logEvidence(initialLog, tail, aSource);
        evidence.builds = concurrent.entries.map((entry, index) => {
            const launch = index === 0 ? a : b;
            const commands = buildCommands(tail, entry.source);
            assert.equal(commands.length, 1);
            assert(samePath(commands[0].output, markers[index].output));
            assert(samePath(commands[0].output, launch.output));
            assert.deepEqual(launch.commandResults, [true, true, true]);
            assert.equal(launch.capturedSessions.size, 1);
            assert(!pidAlive(markers[index].pid), 'The direct real SDK process must close before native launch readiness');
            assert.equal(sha256(entry.marker), beforeRelease.markerSnapshots[index].sha256);
            return { label: entry.label, source: entry.source, commands, sdkPid: markers[index].pid,
                sdkPidGoneObservedAtMilliseconds: elapsed(start), sessionId: launch.session.id,
                program: launch.program, output: launch.output, response: launch.response,
                commandResults: launch.commandResults, capturedSessions: capturedSessionState(launch),
                configuration: JSON.parse(JSON.stringify(launch.session.configuration)),
                sourceSnapshot: fileSnapshot(entry.source), profileSnapshot: fileSnapshot(entry.source.replace(/\.cs$/i, '.run.json')),
                artifacts: ['FileApp.dll', 'FileApp.pdb'].map(name => { const file = path.join(launch.output, name);
                    return { path: file, size: fs.statSync(file).size, sha256: sha256(file) }; }) };
        });
        assert.equal(evidence.log.buildCompletedPhaseDiagnostics.length, 2);
        assert.equal(evidence.log.completedPhaseDiagnostics.length, 2);
        assert.equal(evidence.log.failedPhaseDiagnostics.length, 0);
        assert.equal(evidence.log.cancelledPhaseDiagnostics.length, 0);
        assert.notEqual(a.output, b.output);
        assert.notEqual(a.session.id, b.session.id);
        assert.notEqual(a.pid, b.pid);
        assert.notEqual(a.nonce, b.nonce);
        assert.equal(a.response.revision, concurrent.entries[0].revision);
        assert.equal(b.response.revision, concurrent.entries[1].revision);
        evidence.completedAtMilliseconds = elapsed(start);
        record('concurrent-files-confirmed', evidence);
        result.checks.push('Three A and three B callers capture their own active files, overlap in two verified real SDK barriers, then share one build/session per file with distinct HTTP ownership');
        return { a, b };
    }

    async function nativeAdapterLoss(a, b) {
        assert(adapterLoss);
        await stillAlive(a);
        await stillAlive(b);
        assert(!a.terminated && !b.terminated);
        assert.equal(a.stopRequestedAtMilliseconds, undefined);
        assert(!a.dapRequests.some(item => ['disconnect', 'terminate'].includes(item.message.command)));
        assert(a.dap.some(message => message.type === 'response' && message.command === 'configurationDone' && message.success === true));
        const adapterPath = path.join(result.installedExtension.path, adapterLoss.adapterRelativePath);
        const adapterSha256 = sha256(adapterPath);
        assert.equal(adapterSha256, adapterLoss.adapterSha256, 'Installed native bytes must match the prepared archive before the fault');
        const launcher = JSON.parse(fs.readFileSync(path.join(root, 'launch.json'), 'utf8'));
        assert(samePath(launcher.work, root));
        assert(Number.isSafeInteger(launcher.pid) && launcher.pid > 0);
        const fixture = launch => ({ sessionId: launch.session.id, pid: launch.pid, nonce: launch.nonce,
            source: launch.source, program: launch.program, output: launch.output, port: launch.port, response: launch.response });
        const marker = { schema: 1, nonce: adapterLoss.nonce, root, extensionHostPid: process.pid, editorPid: launcher.pid,
            adapter: { path: adapterPath, sha256: adapterSha256 }, a: fixture(a), b: fixture(b) };
        const evidence = result.adapterLoss = { nonce: adapterLoss.nonce, observationOnly: true,
            before: { a: fixture(a), b: fixture(b), aDap: [...a.dap], aRequests: [...a.dapRequests],
                aSource: fileSnapshot(a.source), bSource: fileSnapshot(b.source),
                aProfile: fileSnapshot(a.source.replace(/\.cs$/i, '.run.json')),
                bProfile: fileSnapshot(b.source.replace(/\.cs$/i, '.run.json')) }, observations: [] };
        const temporaryMarker = adapterLoss.marker + '.tmp';
        assert(!exists(temporaryMarker) && !exists(adapterLoss.marker) && !exists(adapterLoss.receipt));
        fs.writeFileSync(temporaryMarker, JSON.stringify(marker, null, 2) + '\n', { flag: 'wx' });
        fs.renameSync(temporaryMarker, adapterLoss.marker);
        evidence.markerSnapshot = fileSnapshot(adapterLoss.marker);
        evidence.helperRequestedAtMilliseconds = elapsed(start);
        record('exact-adapter-loss-ready', { marker, markerSha256: evidence.markerSnapshot.sha256 });
        state();
        await until(() => exists(adapterLoss.receipt), 'external exact adapter process fault receipt');
        evidence.receiptSnapshot = fileSnapshot(adapterLoss.receipt);
        const receipt = evidence.receipt = JSON.parse(Buffer.from(evidence.receiptSnapshot.base64, 'base64'));
        assert.equal(receipt.nonce, adapterLoss.nonce);
        assert(samePath(receipt.root, root));
        assert.equal(receipt.markerSha256, evidence.markerSnapshot.sha256);
        assert.equal(receipt.helperSha256, expected.harness['adapter-loss.ps1']);
        assert.equal(receipt.success, true, receipt.error || 'Exact adapter fault helper failed');
        assert.equal(receipt.killRequested, true);
        assert.equal(receipt.killedOnlyAdapter, true);
        assert.equal(receipt.identities.aDebuggee.processId, a.pid);
        assert.equal(receipt.identities.bDebuggee.processId, b.pid);
        assert.equal(receipt.killedProcessId, receipt.identities.aAdapter.processId);
        assert.equal(receipt.identities.aDebuggee.parentProcessId, receipt.killedProcessId);
        assert.notEqual(receipt.killedProcessId, receipt.identities.bAdapter.processId);
        assert.equal(receipt.identities.aAdapter.parentProcessId, process.pid);
        assert(samePath(receipt.identities.aAdapter.executablePath, adapterPath));
        evidence.faultReceiptObservedAtMilliseconds = elapsed(start);
        record('exact-adapter-loss-receipt', receipt);
        async function observeResources(label) {
            const item = { label, atMilliseconds: elapsed(start), aTerminated: !!a.terminated,
                aPidRespondsToSignalZero: pidAlive(a.pid), aProgramExists: exists(a.program), aOutputExists: exists(a.output),
                terminalQueuesEmpty: queueEmpty(a.base), aAdapterExits: [...(a.adapterExits || [])] };
            try {
                const body = await request(a.origin);
                assert.deepEqual(body, a.response, 'Any surviving A HTTP endpoint must retain the captured PID/nonce/revision/value');
                item.aOwnedHttpResponse = body;
            } catch (error) {
                if (error instanceof assert.AssertionError) throw error;
                item.aHttpError = String(error);
            }
            item.aPortBindable = await canBind(a.port);
            await stillAlive(b);
            item.b = { ...fixture(b), response: await request(b.origin), outputExists: exists(b.output), programExists: exists(b.program) };
            evidence.observations.push(item);
            record('adapter-loss-resource-observation', item);
            state();
            return item;
        }
        await observeResources('receipt');
        await delay(250);
        await observeResources('after-250ms');
        await delay(750);
        await observeResources('after-1000ms');
        try {
            await until(() => a.terminated && !pidAlive(a.pid) && !exists(a.output) && queueEmpty(a.base),
                'observed adapter-loss session/PID/output settlement', 5000);
        } catch (error) { evidence.settlementWaitError = error.stack || String(error); }
        const settled = await observeResources('settlement');
        evidence.aDapAfterFault = [...a.dap];
        evidence.aRequestsAfterFault = [...a.dapRequests];
        evidence.aAdapterExits = [...(a.adapterExits || [])];
        evidence.aEditorTerminatedAtMilliseconds = a.terminatedAtMilliseconds;
        evidence.sourceAndProfilesUnchanged = [evidence.before.aSource, evidence.before.bSource,
            evidence.before.aProfile, evidence.before.bProfile].every(snapshot => sha256(snapshot.path) === snapshot.sha256);
        assert.equal(evidence.sourceAndProfilesUnchanged, true);
        // Persist actual post-fault ownership before any test-only fallback or
        // retry. Editor termination does not by itself prove debuggee exit.
        evidence.liveOwnedHttpAfterEditorTermination = evidence.observations.some(item => item.aTerminated && item.aOwnedHttpResponse);
        evidence.outputRemovedWhileOwnedHttpAlive = evidence.observations.some(item => !item.aOutputExists && item.aOwnedHttpResponse);
        evidence.observationCompletedAtMilliseconds = elapsed(start);
        record('adapter-loss-observation-complete', { ...evidence, before: undefined });
        if (!settled.aTerminated || settled.aPidRespondsToSignalZero || settled.aOwnedHttpResponse ||
            !settled.aPortBindable || settled.aOutputExists || !settled.terminalQueuesEmpty) {
            result.observedProductGap = { kind: 'adapter-loss-resources-not-released', observedAtMilliseconds: elapsed(start),
                sessionId: a.session.id, pid: a.pid, output: a.output, settled,
                liveOwnedHttpAfterEditorTermination: evidence.liveOwnedHttpAfterEditorTermination,
                outputRemovedWhileOwnedHttpAlive: evidence.outputRemovedWhileOwnedHttpAlive };
            throw new Error('Observed adapter-loss resources remain; retain this first control before considering a product fix');
        }
        evidence.observationOnly = false;
        let retryLogFile;
        await until(() => {
            retryLogFile = outputLog();
            if (!retryLogFile) return false;
            const text = fs.readFileSync(retryLogFile, 'utf8');
            return buildCommands(text, a.source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B output flush before adapter-loss dirty retry');
        const retryLogStart = logSnapshot(retryLogFile);
        const document = await vscode.workspace.openTextDocument(a.source);
        const content = document.getText();
        const revision = 'adapter-loss-retry';
        assert(content.includes(`const string revision = "${a.revision}";`));
        const edit = new vscode.WorkspaceEdit();
        edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(content.length)),
            content.replace(`const string revision = "${a.revision}";`, `const string revision = "${revision}";`));
        assert.equal(await vscode.workspace.applyEdit(edit), true);
        assert.equal(document.isDirty, true);
        const retry = await launchFile('A-adapter-loss-retry', a.source, revision, a.port, false, document, 3);
        assert.notEqual(retry.output, a.output);
        assert.notEqual(retry.session.id, a.session.id);
        assert.notEqual(retry.nonce, a.nonce);
        let retryTail;
        await until(() => {
            retryTail = logTail(retryLogStart);
            return retryTail.includes('Phase completed: Starting netcoredbg');
        }, 'coalesced adapter-loss retry command output');
        const retryLog = logEvidence(retryLogStart, retryTail, a.source);
        assert.equal(retryLog.buildCommands.length, 1, 'Three adapter-loss retry callers must share exactly one actual build');
        assert.equal(retryLog.buildCompletedPhaseDiagnostics.length, 1);
        assert.equal(retryLog.completedPhaseDiagnostics.length, 1);
        assert.equal(retryLog.failedPhaseDiagnostics.length, 0);
        assert.equal(retryLog.cancelledPhaseDiagnostics.length, 0);
        assert(samePath(retryLog.buildCommands[0].output, retry.output));
        assert.equal(fs.readFileSync(retry.source, 'utf8'), document.getText());
        await stillAlive(b);
        evidence.retry = { ...fixture(retry), commandResults: retry.commandResults, commandInvocations: retry.commandInvocations,
            freshOutput: true, freshSession: true, freshToken: true, log: retryLog,
            sourceSnapshot: fileSnapshot(retry.source), profileSnapshot: fileSnapshot(retry.source.replace(/\.cs$/i, '.run.json')),
            configuration: JSON.parse(JSON.stringify(retry.session.configuration)) };
        result.checks.push('Exact installed A adapter process loss is observed separately from debuggee/session/output release; B survives and three dirty retry callers share one new real session');
        return retry;
    }

    function rendererLog() {
        const matches = [];
        function visit(directory) {
            if (!exists(directory)) return;
            for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
                const file = path.join(directory, entry.name);
                if (entry.isDirectory()) visit(file);
                else if (entry.isFile() && entry.name === 'renderer.log') matches.push(file);
            }
        }
        visit(path.join(root, 'profile/logs'));
        assert(matches.length <= 1, 'Native F5 requires exactly one isolated renderer log');
        return matches[0];
    }

    async function launchFromNativeF5(input, source, revision, port, document) {
        requireNativeF5Open();
        assert.equal(vscode.workspace.workspaceFolders?.length || 0, 0, 'Native F5 control must have no workspace folder');
        assert.equal(vscode.workspace.workspaceFile, undefined);
        assert.equal(vscode.debug.activeDebugSession, undefined, 'F5 must start a new session, not Continue an active one');
        assert.equal(document.isDirty, input.sequence > 1);
        const nonce = crypto.randomUUID();
        const launch = { label: `F5-${input.sequence}`, source, revision, nonce, port,
            origin: `http://127.0.0.1:${port}`, dap: [] };
        launches.push(launch);
        ownedAttempts.push(launch);
        byToken.set(nonce, launch);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        launch.profileSnapshot = fileSnapshot(source.replace(/\.cs$/i, '.run.json'));
        await vscode.window.showTextDocument(document);
        requireNativeF5Open();
        assert(samePath(vscode.window.activeTextEditor.document.uri.fsPath, source));
        assert.equal(document.languageId, 'csharp');
        const line = document.getText().split(/\r?\n/).findIndex(value => value.trim() === 'marker += 2;');
        assert(line >= 0);
        const breakpoint = new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(line, 0)));
        breakpoints.push(breakpoint);
        vscode.debug.addBreakpoints([breakpoint]);
        let renderer;
        await until(() => { requireNativeF5Open(); return (renderer = rendererLog()); }, 'native F5 renderer trace created');
        const rendererBefore = logSnapshot(renderer);
        const priorOutput = outputLog();
        const outputBefore = priorOutput ? logSnapshot(priorOutput) : undefined;
        const buffer = Buffer.from(document.getText(), 'utf8');
        const diskBefore = fileSnapshot(source);
        const bufferSha256 = crypto.createHash('sha256').update(buffer).digest('hex');
        assert.equal(diskBefore.sha256 === bufferSha256, input.sequence === 1,
            'First input must be saved; every later input must have a distinct unsaved buffer');
        const request = { schema: 1, nonce: nativeF5.nonce, sequence: input.sequence, launchToken: nonce,
            windowTitle: nativeF5.windowTitle, source, languageId: document.languageId,
            editorWindowFocused: vscode.window.state.focused, activeSource: vscode.window.activeTextEditor.document.uri.fsPath,
            noFolderWindow: true, workspaceFolders: [], activeDebugSessionId: null, isDirty: document.isDirty, diskBefore,
            bufferBefore: { bytes: buffer.length, sha256: bufferSha256 },
            action: 'press-key', key: 'F5', mechanism: 'native-injected',
            requestedAtUtc: new Date().toISOString(),
            expiresAtUtc: new Date(Date.now() + SAFETY_TIMEOUT_MS).toISOString(),
            receipt: input.receipt, closed: nativeF5.closed,
            instructions: 'Observe the exact visible window and C# editor focus; check closed/firstFailure before input. Send one native F5. Only then publish the matching receipt. Never use a command API launch fallback.' };
        const detail = { sequence: input.sequence, label: launch.label, request,
            rendererBefore, outputBefore, profileSnapshot: launch.profileSnapshot };
        result.nativeF5.inputs.push(detail);
        state();
        // All exact-token session/DAP observers and the breakpoint are already
        // armed. External root CUA supplies the key; this function never invokes
        // COMMAND and cannot observe a command-return boolean from native input.
        assert(!exists(input.request), 'Never replace an earlier native input request');
        fs.writeFileSync(input.request + '.tmp', JSON.stringify(request, null, 2) + '\n', { flag: 'wx' });
        fs.renameSync(input.request + '.tmp', input.request);
        detail.requestSnapshot = fileSnapshot(input.request);
        record('needs-f5-input', { ...request, requestPath: input.request, requestSha256: detail.requestSnapshot.sha256 });
        await until(() => { requireNativeF5Open(); return exists(input.receipt); }, `${launch.label} native key action receipt`);
        requireNativeF5Open();
        const receipt = JSON.parse(fs.readFileSync(input.receipt, 'utf8').replace(/^\uFEFF/, ''));
        assert.equal(receipt.schema, 1);
        for (const key of ['nonce', 'sequence', 'launchToken', 'windowTitle', 'action', 'key', 'mechanism']) {
            assert.equal(receipt[key], request[key], `Native F5 receipt ${key}`);
        }
        assert.equal(receipt.requestSha256, detail.requestSnapshot.sha256);
        assert.equal(receipt.tool, 'sky.press_key');
        assert.equal(receipt.editorFocusedBeforeInput, true, 'Native input needs separately observed editor focus');
        assert.equal(typeof receipt.observedWindowTitle, 'string');
        assert(receipt.observedWindowTitle.includes(nativeF5.windowTitle), 'Retain the actual OS title including the unique expected token');
        assert(['string', 'number'].includes(typeof receipt.windowId) && String(receipt.windowId).length > 0);
        assert(Number.isFinite(Date.parse(receipt.inputAtUtc)) && Date.parse(receipt.inputAtUtc) >= Date.parse(request.requestedAtUtc));
        assert(Date.parse(receipt.inputAtUtc) <= Date.parse(request.expiresAtUtc), 'Native input must occur before its request expires');
        assert(Date.parse(receipt.inputAtUtc) <= Date.now() + 1000);
        for (const key of ['observationPath', 'inputRecordPath']) {
            assert(path.isAbsolute(receipt[key]) && within(root, receipt[key]) && exists(receipt[key]), `Retain original native input evidence: ${key}`);
        }
        detail.receipt = receipt;
        detail.receiptSnapshot = fileSnapshot(input.receipt);
        detail.observationSnapshot = fileSnapshot(receipt.observationPath);
        detail.inputRecordSnapshot = fileSnapshot(receipt.inputRecordPath);
        record('native-f5-receipt-observed', detail.receiptSnapshot);
        await until(() => { requireNativeF5Open(); return launch.started; }, `${launch.label} exact owned session start`);
        assert.equal(launch.capturedSessions.size, 1);
        assert.equal(launch.session.configuration.env.ASPNETCORE_URLS, launch.origin);
        assert.equal(launch.session.configuration.serverReadyAction, undefined);
        assert.equal(launch.session.configuration.checkForDevCert, false);
        assert(exists(launch.program) && exists(launch.output));
        assert(!launches.some(previous => previous !== launch && previous.output === launch.output));
        await until(() => {
            requireNativeF5Open();
            return launch.dap.some(message => message.event === 'stopped' && message.body?.reason === 'breakpoint');
        }, `${launch.label} source breakpoint`);
        const stopped = launch.dap.find(message => message.event === 'stopped' && message.body?.reason === 'breakpoint');
        const frames = (await launch.session.customRequest('stackTrace', { threadId: stopped.body.threadId })).stackFrames;
        requireNativeF5Open();
        assert(samePath(frames[0].source.path, source));
        assert.equal(frames[0].line, line + 1);
        const evaluated = await launch.session.customRequest('evaluate', { frameId: frames[0].id, expression: 'marker', context: 'watch' });
        requireNativeF5Open();
        assert.equal(evaluated.result, '40');
        detail.breakpoint = { source: frames[0].source.path, line: frames[0].line, expression: 'marker', result: evaluated.result };
        assert.equal(document.isDirty, false, 'F5 must save the dirty buffer before its build');
        assert.equal(sha256(source), bufferSha256);
        assert.equal(fs.readFileSync(source, 'utf8'), document.getText());
        detail.diskAfter = fileSnapshot(source);
        if (input.sequence > 1) {
            assert(detail.savedEvents?.length > 0, 'Dirty F5 repeat must observe a source save event');
            assert.notEqual(detail.diskAfter.sha256, diskBefore.sha256);
        }
        let outputTail, rendererTail;
        await until(() => {
            requireNativeF5Open();
            const file = outputLog();
            if (!file) return false;
            outputTail = outputBefore ? logTail(outputBefore) : fs.readFileSync(file, 'utf8');
            rendererTail = logTail(rendererBefore);
            return outputTail.includes('Phase completed: Starting netcoredbg') &&
                /KeybindingService#dispatch\s+F5\s+\[ Will dispatch command netcoredbg\.debugActiveFile \]/.test(rendererTail);
        }, `${launch.label} actual F5 dispatch and file-debug output flush`);
        const f5Dispatches = rendererTail.split(/\r?\n/).filter(value => /KeybindingService#dispatch\s+F5\s/.test(value));
        const targetCommands = rendererTail.split(/\r?\n/).filter(value => /CommandService#executeCommand\s+netcoredbg\.debugActiveFile\s*$/.test(value));
        assert.equal(f5Dispatches.length, 1, 'One external F5 must have one resolver dispatch');
        assert.equal(targetCommands.length, 1, 'One native F5 must route to one owned command');
        const builds = buildCommands(outputTail, source);
        assert.equal(builds.length, 1);
        assert(samePath(builds[0].output, launch.output));
        assert.equal(outputTail.split(/\r?\n/).filter(value => value.startsWith('Phase completed: Starting netcoredbg')).length, 1);
        detail.route = { ...rendererBefore, tailCharacters: rendererTail.length,
            tailSha256: crypto.createHash('sha256').update(rendererTail).digest('hex'), f5Dispatches, targetCommands };
        detail.builds = builds;
        detail.configuration = JSON.parse(JSON.stringify(launch.session.configuration));
        vscode.debug.removeBreakpoints([breakpoint]);
        breakpoints.splice(breakpoints.indexOf(breakpoint), 1);
        result.nativeF5.postStartApiActions.push({ action: 'DAP continue', sessionId: launch.session.id, sequence: input.sequence });
        await launch.session.customRequest('continue', { threadId: stopped.body.threadId });
        requireNativeF5Open();
        await ready(launch);
        requireNativeF5Open();
        detail.response = launch.response;
        result.checks.push(`${launch.label}: external native F5 dispatch starts one saved real build, exact breakpoint/evaluation and owned HTTP revision`);
        return launch;
    }

    async function launchFile(label, source, revision, port, inspectBreakpoint = false, document, commandInvocations = 1, onDispatched) {
        const nonce = crypto.randomUUID();
        const launch = { label, source, revision, nonce, port, origin: `http://127.0.0.1:${port}`, dap: [] };
        launches.push(launch);
        ownedAttempts.push(launch);
        byToken.set(nonce, launch);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        if (['web-profile-failure-retry', 'sdk-selection-failure-retry', 'debug-handoff-declined-retry', 'native-host-failure-retry', 'native-handoff-cancel'].includes(scenario)) launch.profileSnapshot = fileSnapshot(source.replace(/\.cs$/i, '.run.json'));
        const opened = document || await vscode.workspace.openTextDocument(source);
        await vscode.window.showTextDocument(opened);
        if (concurrent && concurrentStopping) throw new Error('Concurrent fixture cleanup already began; no late command dispatch is permitted');
        launch.commandPending = true;
        launch.commandInvocations = commandInvocations;
        state();
        try {
            // Observe every concurrent request before handling a rejection so a
            // later owned session can still be captured for failure cleanup.
            launch.commandOperation = Promise.allSettled(Array.from({ length: commandInvocations }, () => vscode.commands.executeCommand(COMMAND)));
            launch.dispatchedAtMilliseconds = elapsed(start);
            if (onDispatched) onDispatched(launch);
            const outcomes = await launch.commandOperation;
            const rejected = outcomes.find(outcome => outcome.status === 'rejected');
            if (rejected) throw rejected.reason;
            launch.commandResults = outcomes.map(outcome => outcome.value);
            assert.deepEqual(launch.commandResults, Array(commandInvocations).fill(true), `${label} installed commands must start debugging`);
        } finally {
            launch.commandPending = false;
            launch.returnedAtMilliseconds = elapsed(start);
            state();
        }
        assert.equal(opened.isDirty, false, 'Installed command must save the dirty source before building');
        if (['web-profile-failure-retry', 'sdk-selection-failure-retry', 'debug-handoff-declined-retry', 'native-host-failure-retry', 'native-handoff-cancel'].includes(scenario)) launch.sourceSnapshot = fileSnapshot(source);
        await until(() => launch.started, `${label} exact owned session start`);
        assert.equal(launch.capturedSessions.size, 1, 'One launch token must have exactly one captured session');
        assert(exists(launch.program));
        assert(exists(launch.output));
        assert.equal(launch.session.configuration.env.ASPNETCORE_URLS, launch.origin);
        assert.equal(launch.session.configuration.serverReadyAction, undefined);
        assert.equal(launch.session.configuration.checkForDevCert, false);
        assert(!launches.some(previous => previous !== launch && previous.output === launch.output), 'Every launch needs a fresh output directory');
        assert(!failedBuildAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse failed build output');
        assert(!cancelledBuildAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse cancelled build output');
        assert(!failedWebProfileAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse Web-profile-failed output');
        assert(!failedHandoffAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse editor-declined output');
        assert(!failedNativeHostAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse native-host-failed output');
        assert(!cancelledHandoffAttempts.some(previous => previous.output === launch.output), 'A retry must not reuse cancelled handoff output');
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
        await until(() => !exists(attempt.output) && queueEmpty(attempt.base), 'compiler-failed owned output and terminal queues cleanup');
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

    async function webProfileFailure(source, revision, port, a, b) {
        let file;
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B command output before Web profile failure');
        const snapshot = logSnapshot(file);
        const opened = await vscode.workspace.openTextDocument(source);
        assert.equal(opened.isDirty, false, 'The failure must change only the disk launch profile');
        assert.equal(opened.getText(), fs.readFileSync(source, 'utf8'));
        assert(opened.getText().includes('marker += 2;'), 'The source must remain valid through Web preparation');
        await vscode.window.showTextDocument(opened);
        const attempt = { label: 'A-web-profile-failure', source, revision, port, origin: `http://127.0.0.1:${port}`,
            nonce: crypto.randomUUID(), expectedWebProfileFailure: true, dap: [], adapterCreationCount: 0, editorStartCount: 0 };
        failedWebProfileAttempts.push(attempt);
        ownedAttempts.push(attempt);
        byToken.set(attempt.nonce, attempt);
        attempt.invalidRoot = path.join(root, 'invalid-web-profile-root', attempt.nonce);
        assert(within(root, attempt.invalidRoot) && !samePath(attempt.invalidRoot, expected.sdk.root));
        assert(!exists(attempt.invalidRoot), 'The profile fault must name a fresh absent path, never an existing SDK alias');
        const profile = source.replace(/\.cs$/i, '.run.json');
        fs.writeFileSync(profile, JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: attempt.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: attempt.nonce, ASPNETCORE_ENVIRONMENT: 'Development', DOTNET_ROOT: attempt.invalidRoot },
        } } }, null, 2) + '\n');
        attempt.profileSnapshot = fileSnapshot(profile);
        attempt.sourceSnapshot = fileSnapshot(source);
        attempt.sourceWasDirty = opened.isDirty;
        attempt.ambientDotnetRootBefore = process.env.DOTNET_ROOT ?? null;
        attempt.commandPending = true;
        attempt.invokedAtMilliseconds = elapsed(start);
        record('expected-web-profile-failure-request', { label: attempt.label, nonce: attempt.nonce,
            profileSha256: attempt.profileSnapshot.sha256, sourceSha256: attempt.sourceSnapshot.sha256 });
        state();
        try { attempt.commandResult = await vscode.commands.executeCommand(COMMAND); }
        finally { attempt.commandPending = false; attempt.returnedAtMilliseconds = elapsed(start); state(); }
        assert.equal(attempt.commandResult, false, 'The invalid per-file root must decline before debugger handoff');
        assert.equal(opened.isDirty, false);
        attempt.profileAfterSha256 = sha256(profile);
        assert.equal(attempt.profileAfterSha256, attempt.profileSnapshot.sha256, 'The failed command must read the retained invalid profile bytes');
        attempt.sourceAfterSha256 = sha256(source);
        assert.equal(attempt.sourceAfterSha256, attempt.sourceSnapshot.sha256, 'Only the launch profile may change in the failed attempt');
        attempt.sourceUnchanged = true;
        attempt.ambientDotnetRootAfter = process.env.DOTNET_ROOT ?? null;
        assert.equal(attempt.ambientDotnetRootAfter, attempt.ambientDotnetRootBefore, 'A per-file fault must not change the host environment');
        let tail;
        await until(() => {
            tail = logTail(snapshot);
            return tail.includes('The web launch profile DOTNET_ROOT does not identify the selected dotnet installation.') &&
                tail.includes('Phase failed: Preparing web launch settings');
        }, 'successful build and exact Web profile root failure output');
        attempt.log = logEvidence(snapshot, tail, source);
        assert.equal(attempt.log.buildCommands.length, 1, 'The profile-failed attempt must execute one actual build');
        assert.equal(attempt.log.buildCompletedPhaseDiagnostics.length, 1, 'The actual build must succeed before the Web guard');
        assert.equal(attempt.log.webPreparationFailedPhaseDiagnostics.length, 1);
        assert(attempt.log.webProfileRootDiagnostics.length > 0);
        assert.equal(attempt.log.failedPhaseDiagnostics.length, 0);
        assert.equal(attempt.log.cancelledPhaseDiagnostics.length, 0);
        assert.equal(attempt.log.compilerDiagnostics.length, 0);
        assert(!tail.includes('Phase started: Starting netcoredbg'), 'The Web failure must precede the handoff phase');
        assert(!tail.includes('dotnet "dev-certs"'), 'An explicit HTTP profile must not run certificate commands');
        assert.equal(attempt.adapterCreationCount, 0, 'No token-matched adapter tracker may be created');
        assert.equal(attempt.editorStartCount, 0, 'No token-matched editor session may start');
        assert.equal(attempt.capturedSessions?.size || 0, 0);
        assert.equal(attempt.session, undefined);
        assert(!attempt.dap.some(message => message.event === 'process'), 'No token-matched DAP process event may be reported');
        attempt.noSession = true;
        attempt.noAdapter = true;
        attempt.noProcessEvent = true;
        attempt.output = attempt.log.buildCommands[0].output;
        attempt.program = path.join(attempt.output, 'FileApp.dll');
        attempt.base = path.dirname(path.dirname(attempt.output));
        assert(samePath(attempt.base, a.base));
        assert.notEqual(attempt.output, a.output);
        await until(() => !exists(attempt.output) && queueEmpty(attempt.base), 'Web-profile-failed owned output and terminal queues cleanup');
        assert(!exists(attempt.output), 'The exact profile-failed output must be absent after command return');
        assert(queueEmpty(attempt.base), 'The profile-failed attempt must leave both terminal queues empty');
        attempt.outputRemovedAtMilliseconds = elapsed(start);
        assert(await canBind(port), 'The profile-failed A attempt must leave its HTTP port reusable');
        attempt.portReusableAtMilliseconds = elapsed(start);
        await stillAlive(b);
        record('expected-web-profile-failure-confirmed', { label: attempt.label, output: attempt.output,
            commandResult: attempt.commandResult, sourceUnchanged: true, noAdapter: true, noSession: true, noProcessEvent: true });
        result.checks.push('Actual successful build then per-file Web root failure returns false before handoff, preserves source, removes owned output and leaves B unchanged');
        state();
        return attempt;
    }

    async function nativeHostFailure(source, revision, port, a, b) {
        let file;
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B command output before actual native host failure');
        const snapshot = logSnapshot(file);
        const opened = await vscode.workspace.openTextDocument(source);
        assert.equal(opened.isDirty, false);
        assert.equal(opened.getText(), fs.readFileSync(source, 'utf8'));
        assert(opened.getText().includes('marker += 2;'), 'The host-failed attempt must retain valid source');
        await vscode.window.showTextDocument(opened);
        const profile = source.replace(/\.cs$/i, '.run.json');
        const attempt = { label: 'A-native-host-failure', source, revision, port, origin: a.origin,
            nonce: crypto.randomUUID(), expectedNativeHostFailure: true,
            invalidRollForward: 'LIFECYCLE_INVALID_ROLL_FORWARD', dap: [], dapRequests: [], adapterExits: [],
            adapterCreationCount: 0, editorStartCount: 0, commandInvocations: 3,
            expectedBase: a.base, previousOutput: a.output, sourceSnapshot: fileSnapshot(source), sourceWasDirty: opened.isDirty,
            ambientDotnetRootBefore: process.env.DOTNET_ROOT ?? null,
            ambientRollForwardBefore: process.env.DOTNET_ROLL_FORWARD ?? null };
        assert(!byToken.has(attempt.nonce));
        failedNativeHostAttempts.push(attempt);
        ownedAttempts.push(attempt);
        byToken.set(attempt.nonce, attempt);
        // Change only this file's ordinary launch profile. The build and adapter
        // payload remain real; no configuration provider or target runtime is injected.
        fs.writeFileSync(profile, JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: attempt.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: attempt.nonce, ASPNETCORE_ENVIRONMENT: 'Development',
                DOTNET_ROLL_FORWARD: attempt.invalidRollForward },
        } } }, null, 2) + '\n');
        attempt.profileSnapshot = fileSnapshot(profile);
        await stillAlive(b);
        attempt.bBefore = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
        attempt.commandPending = true;
        attempt.invokedAtMilliseconds = elapsed(start);
        record('expected-native-host-failure-request', { label: attempt.label, nonce: attempt.nonce,
            profileSha256: attempt.profileSnapshot.sha256, sourceSha256: attempt.sourceSnapshot.sha256,
            invalidRollForward: attempt.invalidRollForward });
        state();
        try {
            attempt.commandOperation = Promise.allSettled(Array.from({ length: attempt.commandInvocations }, () => vscode.commands.executeCommand(COMMAND)));
            const outcomes = await attempt.commandOperation;
            const rejected = outcomes.find(outcome => outcome.status === 'rejected');
            if (rejected) throw rejected.reason;
            attempt.commandResults = outcomes.map(outcome => outcome.value);
        } finally { attempt.commandPending = false; attempt.returnedAtMilliseconds = elapsed(start); state(); }
        // An editor may acknowledge the session before configurationDone fails.
        // Retain its measured result instead of assuming every native error is false.
        assert.equal(typeof attempt.commandResults[0], 'boolean');
        assert.deepEqual(attempt.commandResults, Array(attempt.commandInvocations).fill(attempt.commandResults[0]));
        assert.equal(opened.isDirty, false);
        attempt.sourceAfterSnapshot = fileSnapshot(source);
        attempt.profileAfterSnapshot = fileSnapshot(profile);
        assert.equal(attempt.sourceAfterSnapshot.sha256, attempt.sourceSnapshot.sha256);
        assert.equal(attempt.profileAfterSnapshot.sha256, attempt.profileSnapshot.sha256);
        attempt.ambientDotnetRootAfter = process.env.DOTNET_ROOT ?? null;
        attempt.ambientRollForwardAfter = process.env.DOTNET_ROLL_FORWARD ?? null;
        assert.equal(attempt.ambientDotnetRootAfter, attempt.ambientDotnetRootBefore);
        assert.equal(attempt.ambientRollForwardAfter, attempt.ambientRollForwardBefore);
        await until(() => attempt.dap.some(message => message.type === 'response' &&
            message.command === 'configurationDone' && message.success === false), 'native configurationDone failure response');
        const requests = command => attempt.dapRequests.filter(item => item.message.type === 'request' && item.message.command === command);
        const initialization = requests('initialize');
        assert.equal(initialization.length, 1);
        const initializeResponse = attempt.dap.find(message => message.type === 'response' && message.command === 'initialize' &&
            message.request_seq === initialization[0].message.seq);
        assert.equal(initializeResponse?.success, true, 'The real bundled adapter must answer initialize successfully');
        attempt.initializeResponse = { request: initialization[0], response: initializeResponse };
        const configurations = requests('configurationDone');
        assert.equal(configurations.length, 1);
        const configurationDoneFailure = attempt.dap.find(message => message.type === 'response' && message.command === 'configurationDone' &&
            message.request_seq === configurations[0].message.seq && message.success === false);
        assert(configurationDoneFailure, 'The native failure must answer this exact configurationDone request');
        attempt.configurationDoneFailure = { request: configurations[0], response: configurationDoneFailure };
        const launches = requests('launch');
        assert.equal(launches.length, 1);
        attempt.nativeLaunchRequest = launches[0];
        assert(samePath(attempt.nativeLaunchRequest.message.arguments.program, attempt.program));
        assert.equal(attempt.nativeLaunchRequest.message.arguments.env.LIFECYCLE_TOKEN, attempt.nonce);
        assert.equal(attempt.nativeLaunchRequest.message.arguments.env.DOTNET_ROLL_FORWARD, attempt.invalidRollForward);
        const diagnostic = "Invalid value for environment variable 'DOTNET_ROLL_FORWARD'.";
        attempt.hostDiagnostics = attempt.dap.filter(message => message.event === 'output' &&
            typeof message.body?.output === 'string' && message.body.output.includes(diagnostic));
        assert(attempt.hostDiagnostics.length > 0, 'The real .NET host must report its exact environment-value error through native DAP output');
        assert.equal(attempt.adapterCreationCount, 1);
        assert.equal(attempt.capturedSessions.size, 1);
        assert(attempt.editorStartCount === 0 || attempt.editorStartCount === 1);
        assert(attempt.builtArtifacts?.length === 3);
        // A native process can exit before CoreCLR attach, which precedes the
        // adapter's process event. Event absence is not OS-process absence evidence.
        attempt.processEvents = attempt.dap.filter(message => message.event === 'process');
        await until(() => attempt.terminated, 'native-host-failed exact editor session termination');
        attempt.terminationObservedWithoutTestStop = true;
        if (attempt.pid) {
            await until(() => !pidAlive(attempt.pid), 'reported native-host-failed PID exit');
            attempt.reportedPidGoneAtMilliseconds = elapsed(start);
        }
        let tail;
        await until(() => {
            tail = logTail(snapshot);
            return tail.includes('Phase completed: Starting netcoredbg') || tail.includes('Phase failed: Starting netcoredbg');
        }, 'measured native-host-failed command phase output');
        attempt.log = { ...logEvidence(snapshot, tail, source),
            webPreparationCompletedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Preparing web launch settings')),
            handoffFailedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase failed: Starting netcoredbg')) };
        assert.equal(attempt.log.buildCommands.length, 1, 'Three callers must share one actual successful build');
        assert.equal(attempt.log.buildCompletedPhaseDiagnostics.length, 1);
        assert.equal(attempt.log.webPreparationCompletedPhaseDiagnostics.length, 1);
        assert.equal(attempt.log.completedPhaseDiagnostics.length + attempt.log.handoffFailedPhaseDiagnostics.length, 1);
        assert.equal(attempt.log.completedPhaseDiagnostics.length, Number(attempt.commandResults[0]));
        assert.equal(attempt.log.failedPhaseDiagnostics.length, 0);
        assert.equal(attempt.log.cancelledPhaseDiagnostics.length, 0);
        assert.equal(attempt.log.compilerDiagnostics.length, 0);
        assert.equal(attempt.log.webPreparationFailedPhaseDiagnostics.length, 0);
        assert(!tail.includes('dotnet "dev-certs"'));
        assert(samePath(attempt.log.buildCommands[0].output, attempt.output));
        await until(() => !exists(attempt.output) && queueEmpty(attempt.base), 'native-host-failed owned output and terminal queues cleanup');
        attempt.outputRemovedAtMilliseconds = elapsed(start);
        attempt.outputAbsent = true;
        attempt.terminalQueuesEmpty = true;
        assert(await canBind(port));
        attempt.portReusableAtMilliseconds = elapsed(start);
        await stillAlive(b);
        attempt.bAfter = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
        assert.deepEqual(attempt.bAfter, attempt.bBefore);
        record('actual-native-host-failure-confirmed', { label: attempt.label, commandResults: attempt.commandResults,
            output: attempt.output, sessionId: attempt.session.id, configurationDoneFailure: attempt.configurationDoneFailure,
            hostDiagnostics: attempt.hostDiagnostics, editorStartCount: attempt.editorStartCount,
            processEvents: attempt.processEvents, terminationObservedWithoutTestStop: true });
        result.checks.push('Three installed commands share one real build and adapter; the .NET host rejects the per-file roll-forward value, the exact session terminates and output/queues clear while B survives');
        state();
        return attempt;
    }

    async function nativeHandoffCancellation(source, revision, port, a, b) {
        let file;
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B output before UI handoff cancellation');
        const snapshot = logSnapshot(file);
        const document = await vscode.workspace.openTextDocument(source);
        assert.equal(document.isDirty, false);
        assert.equal(document.getText(), fs.readFileSync(source, 'utf8'));
        await vscode.window.showTextDocument(document);
        const profile = source.replace(/\.cs$/i, '.run.json');
        const attempt = { label: 'A-handoff-cancel', source, revision, port, origin: a.origin, nonce: crypto.randomUUID(),
            expectedHandoffCancellation: true, commandInvocations: 3, dap: [], dapRequests: [], dapTimeline: [], adapterExits: [],
            adapterCreationCount: 0, editorStartCount: 0, providerCalls: [], providerPending: false, providerActive: true,
            providerPassthroughCount: 0, providerDisposed: false, providerDisposalCount: 0, providerTokenEvents: [],
            gateReleased: false, gateSettled: false, testStopRequested: false, sourceSnapshot: fileSnapshot(source) };
        cancelledHandoffAttempts.push(attempt);
        ownedAttempts.push(attempt);
        byToken.set(attempt.nonce, attempt);
        fs.writeFileSync(profile, JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: attempt.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: attempt.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        attempt.profileSnapshot = fileSnapshot(profile);
        await stillAlive(b);
        attempt.bBefore = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
        let originalConfig, providerToken, resolveGate;
        const gatePromise = new Promise(resolve => { resolveGate = resolve; });
        const tokenSubscriptions = [];
        const provider = vscode.debug.registerDebugConfigurationProvider('coreclr', {
            resolveDebugConfigurationWithSubstitutedVariables(_folder, config, token) {
                if (config?.env?.LIFECYCLE_TOKEN !== attempt.nonce) {
                    attempt.providerPassthroughCount++;
                    return config;
                }
                if (!attempt.providerActive) return undefined;
                return observe('handoff-provider-held', () => {
                    attempt.program = config.program;
                    attempt.output = config.__netcoredbgFileAppOutput;
                    assert(within(root, attempt.output) && within(attempt.output, attempt.program));
                    attempt.base = path.dirname(path.dirname(attempt.output));
                    assert(samePath(attempt.base, a.base));
                    assert.notEqual(attempt.output, a.output);
                    assert(samePath(path.dirname(attempt.program), attempt.output));
                    assert.equal(path.basename(attempt.program), 'FileApp.dll');
                    assert.equal(config.type, 'coreclr');
                    assert.equal(config.request, 'launch');
                    assert(samePath(config.cwd, path.dirname(source)));
                    assert(samePath(config.env.DOTNET_ROOT, expected.sdk.root));
                    assert.equal(config.env.ASPNETCORE_URLS, attempt.origin);
                    assert.equal(config.serverReadyAction, undefined);
                    assert.equal(config.checkForDevCert, false);
                    const outputStat = fs.lstatSync(attempt.output);
                    assert(outputStat.isDirectory() && !outputStat.isSymbolicLink());
                    const call = { atMilliseconds: elapsed(start), configuration: JSON.parse(JSON.stringify(config)),
                        providerTokenCancelled: token?.isCancellationRequested ?? null,
                        artifacts: ['FileApp.dll', 'FileApp.pdb'].map(name => {
                            const artifact = path.join(attempt.output, name), stat = fs.lstatSync(artifact);
                            assert(stat.isFile() && !stat.isSymbolicLink() && stat.size > 0);
                            return { path: artifact, size: stat.size, sha256: sha256(artifact) };
                        }) };
                    attempt.providerCalls.push(call);
                    assert.equal(attempt.providerCalls.length, 1);
                    originalConfig = config;
                    providerToken = token;
                    if (token) tokenSubscriptions.push(token.onCancellationRequested(() => observe('handoff-provider-token-cancelled', () => {
                        const event = { atMilliseconds: elapsed(start), gateMode: attempt.gateMode ?? null };
                        attempt.providerTokenEvents.push(event);
                        record('handoff-provider-token-cancelled', event);
                    })));
                    attempt.providerPending = true;
                    record('handoff-provider-held', { label: attempt.label, nonce: attempt.nonce, call });
                    state();
                    return gatePromise.then(value => {
                        attempt.providerPending = false;
                        attempt.providerReturnedAtMilliseconds = elapsed(start);
                        record('handoff-provider-returned', { label: attempt.label, gateMode: attempt.gateMode,
                            originalObjectReturned: value === originalConfig, providerTokenCancelled: providerToken?.isCancellationRequested ?? null });
                        state();
                        return value;
                    });
                });
            },
        });
        const owner = {
            settle(mode) {
                if (attempt.gateSettled) return;
                if (mode === 'valid-original') {
                    assert(originalConfig);
                    assert.equal(originalConfig.program, attempt.program);
                    assert.equal(originalConfig.__netcoredbgFileAppOutput, attempt.output);
                    assert.deepEqual(JSON.parse(JSON.stringify(originalConfig)), attempt.providerCalls[0].configuration);
                }
                attempt.gateSettled = true;
                attempt.gateMode = mode;
                attempt.gateSettledAtMilliseconds = elapsed(start);
                attempt.gateReleased = mode === 'valid-original';
                attempt.originalObjectReleased = mode === 'valid-original';
                record('handoff-gate-settled', { label: attempt.label, mode, originalObjectReleased: attempt.originalObjectReleased });
                resolveGate(mode === 'valid-original' ? originalConfig : undefined);
            },
            dispose() {
                if (!attempt.providerActive) return;
                if (!attempt.gateSettled) owner.settle('decline-safety');
                attempt.providerActive = false;
                try { provider.dispose(); }
                finally {
                    for (const subscription of tokenSubscriptions) subscription.dispose();
                    attempt.providerDisposed = true;
                    attempt.providerDisposalCount++;
                    attempt.providerDisposedAtMilliseconds = elapsed(start);
                    handoffGates.delete(owner);
                    record('handoff-gate-provider-disposed', { label: attempt.label, count: attempt.providerDisposalCount });
                    state();
                }
            },
        };
        handoffGates.set(owner, attempt);
        subscriptions.push(owner);
        let completed = false;
        try {
            attempt.commandPending = true;
            attempt.invokedAtMilliseconds = elapsed(start);
            attempt.commandOperation = Promise.allSettled(Array.from({ length: 3 }, () => vscode.commands.executeCommand(COMMAND)))
                .finally(() => { attempt.commandPending = false; attempt.returnedAtMilliseconds = elapsed(start); state(); });
            await until(() => {
                assert(attempt.commandPending, 'Commands must remain pending at the exact provider gate');
                return attempt.providerPending;
            }, 'post-build exact-token debugger provider gate');
            let tail;
            await until(() => {
                tail = logTail(snapshot);
                return tail.includes('Phase started: Starting netcoredbg');
            }, 'real completed build/Web preparation before held handoff');
            const prepared = logEvidence(snapshot, tail, source);
            assert.equal(prepared.buildCommands.length, 1);
            assert.equal(prepared.buildCompletedPhaseDiagnostics.length, 1);
            assert(tail.includes('Phase completed: Preparing web launch settings'));
            assert(samePath(prepared.buildCommands[0].output, attempt.output));
            assert.equal(attempt.adapterCreationCount, 0);
            assert.equal(attempt.editorStartCount, 0);
            await stillAlive(b);
            const uiRequest = { schema: 1, nonce: handoffCancellation.nonce, token: attempt.nonce,
                windowTitle: handoffCancellation.windowTitle, phase: 'Starting netcoredbg', stage: 'provider-held',
                source, program: attempt.program, output: attempt.output, providerCallCount: attempt.providerCalls.length };
            const temporary = handoffCancellation.request + '.tmp';
            fs.writeFileSync(temporary, JSON.stringify(uiRequest, null, 2) + '\n', { flag: 'wx' });
            fs.renameSync(temporary, handoffCancellation.request);
            attempt.uiRequestSnapshot = fileSnapshot(handoffCancellation.request);
            attempt.uiRequestedAtMilliseconds = elapsed(start);
            record('needs-ui-cancel', uiRequest);
            const outcomes = await attempt.commandOperation;
            const rejected = outcomes.find(outcome => outcome.status === 'rejected');
            if (rejected) throw rejected.reason;
            attempt.commandResults = outcomes.map(outcome => outcome.value);
            assert.deepEqual(attempt.commandResults, [false, false, false]);
            await until(() => exists(handoffCancellation.receipt), 'actual handoff progress Cancel UI receipt');
            attempt.uiActionSnapshot = fileSnapshot(handoffCancellation.receipt);
            attempt.uiAction = JSON.parse(Buffer.from(attempt.uiActionSnapshot.base64, 'base64').toString('utf8').replace(/^\uFEFF/, ''));
            for (const [name, value] of Object.entries({ schema: 1, nonce: handoffCancellation.nonce,
                automation: '@oai/sky', method: 'click', control: 'progress Cancel', notificationTitle: 'Debug C# file',
                message: 'Starting netcoredbg', expectedWindowTitle: handoffCancellation.windowTitle })) {
                assert.equal(attempt.uiAction[name], value);
            }
            assert(attempt.uiAction.window?.title?.includes(handoffCancellation.windowTitle));
            assert(attempt.uiAction.window.app && attempt.uiAction.window.id !== undefined);
            assert(Number.isFinite(Date.parse(attempt.uiAction.actionStartedUtc)));
            assert(Date.parse(attempt.uiAction.actionCompletedUtc) >= Date.parse(attempt.uiAction.actionStartedUtc));
            attempt.uiObservations = ['beforeObservationFile', 'afterObservationFile'].map(name => {
                const file = attempt.uiAction[name];
                assert(path.isAbsolute(file) && within(root, file));
                const stat = fs.statSync(file);
                assert(stat.isFile() && stat.size > 0);
                return { path: file, size: stat.size, sha256: sha256(file) };
            });
            assert.equal(attempt.providerPending, true);
            assert.equal(attempt.gateSettled, false);
            attempt.providerTokenCancelledAfterForeground = providerToken?.isCancellationRequested ?? null;
            assert.equal(attempt.providerTokenCancelledAfterForeground, false, 'Cancel must target the file-command progress, not debugger initialization');
            assert.equal(attempt.adapterCreationCount, 0);
            assert.equal(attempt.editorStartCount, 0);
            assert.equal(attempt.capturedSessions?.size || 0, 0);
            await until(() => { tail = logTail(snapshot); return tail.includes('Phase cancelled: Starting netcoredbg'); },
                'quiet foreground handoff cancellation phase');
            attempt.log = { ...logEvidence(snapshot, tail, source),
                handoffCancelledDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase cancelled: Starting netcoredbg')) };
            assert.equal(attempt.log.handoffCancelledDiagnostics.length, 1);
            assert.equal(attempt.log.buildCommands.length, 1);
            assert.equal(attempt.log.buildCompletedPhaseDiagnostics.length, 1);
            assert.equal(attempt.log.webPreparationFailedPhaseDiagnostics.length, 0);
            assert.equal(attempt.log.failedPhaseDiagnostics.length, 0);
            assert.equal(attempt.log.cancelledPhaseDiagnostics.length, 0);
            assert.equal(attempt.log.compilerDiagnostics.length, 0);
            assert.equal(attempt.log.completedPhaseDiagnostics.length, 0);
            assert(!tail.includes('Phase failed: Starting netcoredbg') && !tail.includes('Phase timed out:'));
            assert(!tail.includes('The editor did not start the netcoredbg debug session.'));
            const heldArtifacts = attempt.providerCalls[0].artifacts.map(artifact => ({ ...artifact,
                retainedSha256: sha256(artifact.path), retainedSize: fs.statSync(artifact.path).size }));
            for (const artifact of heldArtifacts) {
                assert.equal(artifact.retainedSha256, artifact.sha256);
                assert.equal(artifact.retainedSize, artifact.size);
            }
            await stillAlive(b);
            attempt.heldAfterForeground = { atMilliseconds: elapsed(start), providerPending: true, gateSettled: false,
                outputExists: exists(attempt.output), artifacts: heldArtifacts, terminalQueuesEmpty: queueEmpty(attempt.base),
                portBindable: await canBind(port), b: { sessionId: b.session.id, pid: b.pid, nonce: b.nonce,
                    output: b.output, response: await request(b.origin) } };
            assert.equal(attempt.heldAfterForeground.outputExists, true);
            assert.equal(attempt.heldAfterForeground.terminalQueuesEmpty, true);
            assert.equal(attempt.heldAfterForeground.portBindable, true);
            assert.deepEqual(attempt.heldAfterForeground.b, attempt.bBefore);
            record('handoff-cancelled-foreground-output-retained', attempt.heldAfterForeground);
            owner.settle('valid-original');
            await until(() => attempt.started && attempt.adapterCreationCount > 0, 'late real cancelled session start');
            assert.equal(attempt.capturedSessions.size, 1);
            assert.equal(attempt.editorStartCount, 1);
            assert.equal(attempt.adapterCreationCount, 1);
            const requests = command => attempt.dapRequests.filter(item => item.message.type === 'request' && item.message.command === command);
            await until(() => attempt.dap.some(message => message.type === 'response' && message.command === 'initialize'),
                'late real adapter initialization transcript');
            const initialize = requests('initialize');
            assert.equal(initialize.length, 1);
            attempt.nativeInitialize = { request: initialize[0], response: attempt.dap.find(message => message.type === 'response' &&
                message.command === 'initialize' && message.request_seq === initialize[0].message.seq) };
            assert.equal(attempt.nativeInitialize.response?.success, true);
            await until(() => attempt.terminated, 'matching late cancelled session termination');
            await until(() => attempt.adapterExits.length > 0, 'late cancelled native adapter exit');
            const launches = requests('launch');
            assert(launches.length <= 1);
            attempt.launchRequestObserved = launches.length === 1;
            attempt.nativeLaunchRequest = launches[0] ?? null;
            if (launches.length) {
                assert.equal(launches[0].message.arguments.program, attempt.program);
                assert.equal(launches[0].message.arguments.env.LIFECYCLE_TOKEN, attempt.nonce);
            }
            attempt.nativeStopRequests = attempt.dapRequests.filter(item => ['terminate', 'disconnect'].includes(item.message.command));
            assert(attempt.nativeStopRequests.length > 0, 'The cancelled real session must receive a native stop/teardown request');
            if (attempt.pid) {
                await until(() => !pidAlive(attempt.pid), 'captured late cancelled debuggee PID exit');
                attempt.reportedPidGoneAtMilliseconds = elapsed(start);
            }
            attempt.pidReported = !!attempt.pid;
            await until(() => !exists(attempt.output) && queueEmpty(attempt.base), 'late cancelled owned output and queues cleanup');
            attempt.outputRemovedAtMilliseconds = elapsed(start);
            attempt.outputAbsent = !exists(attempt.output);
            attempt.terminalQueuesEmpty = queueEmpty(attempt.base);
            attempt.portBindable = await canBind(port);
            assert(attempt.portBindable);
            attempt.portReusableAtMilliseconds = elapsed(start);
            attempt.sourceAfterSnapshot = fileSnapshot(source);
            attempt.profileAfterSnapshot = fileSnapshot(profile);
            assert.equal(attempt.sourceAfterSnapshot.sha256, attempt.sourceSnapshot.sha256);
            assert.equal(attempt.profileAfterSnapshot.sha256, attempt.profileSnapshot.sha256);
            await stillAlive(b);
            attempt.bAfter = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
            assert.deepEqual(attempt.bAfter, attempt.bBefore);
            attempt.lateTerminationObservedWithoutTestStop = true;
            record('native-handoff-cancel-confirmed', { label: attempt.label, commandResults: attempt.commandResults,
                sessionId: attempt.session.id, pid: attempt.pid, output: attempt.output, nativeStopRequests: attempt.nativeStopRequests });
            completed = true;
            result.checks.push('Actual progress Cancel returns three false callers while the editor provider remains held and output/B are preserved; the original released config starts a real late session that terminates without test Stop and releases owned resources');
            return attempt;
        } finally {
            // Failure cleanup owns settling/draining a still-pending editor
            // start before this provider and exact-session observers disappear.
            if (completed) owner.dispose();
        }
    }

    async function debugHandoffDeclined(source, revision, port, a, b) {
        let file;
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B command output before injected editor rejection');
        const snapshot = logSnapshot(file);
        const opened = await vscode.workspace.openTextDocument(source);
        assert.equal(opened.isDirty, false);
        assert.equal(opened.getText(), fs.readFileSync(source, 'utf8'));
        assert(opened.getText().includes('marker += 2;'), 'The declined attempt must retain valid source');
        await vscode.window.showTextDocument(opened);
        const profile = source.replace(/\.cs$/i, '.run.json');
        const attempt = { label: 'A-editor-handoff-declined', source, revision, port, origin: a.origin,
            nonce: crypto.randomUUID(), expectedHandoffDeclined: true, dap: [], adapterCreationCount: 0, editorStartCount: 0,
            providerCalls: [], providerPassthroughCount: 0, providerDisposed: false, providerDisposalCount: 0,
            commandInvocations: 3, sourceSnapshot: fileSnapshot(source),
            sourceWasDirty: opened.isDirty, ambientDotnetRootBefore: process.env.DOTNET_ROOT ?? null };
        assert(!byToken.has(attempt.nonce), 'The failure must have a fresh token distinct from both prior sessions');
        failedHandoffAttempts.push(attempt);
        ownedAttempts.push(attempt);
        byToken.set(attempt.nonce, attempt);
        let ownedProvider;
        let firstError;
        try {
            fs.writeFileSync(profile, JSON.stringify({ profiles: { LifecycleHttp: {
                commandName: 'Project', applicationUrl: attempt.origin, launchBrowser: false,
                environmentVariables: { LIFECYCLE_TOKEN: attempt.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
            } } }, null, 2) + '\n');
            attempt.profileSnapshot = fileSnapshot(profile);
            await stillAlive(b);
            attempt.bBefore = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
            // This supported editor API deliberately rejects one exact test token.
            // It is not a native adapter failure or an injected product runtime.
            const provider = vscode.debug.registerDebugConfigurationProvider('coreclr', {
                resolveDebugConfigurationWithSubstitutedVariables(_folder, config) {
                    if (config?.env?.LIFECYCLE_TOKEN !== attempt.nonce) {
                        attempt.providerPassthroughCount++;
                        return config;
                    }
                    const call = { atMilliseconds: elapsed(start), configuration: JSON.parse(JSON.stringify(config)) };
                    attempt.providerCalls.push(call);
                    observe('injected-editor-rejection', () => {
                        // Capture paths before validation so failed runs retain the owned evidence.
                        attempt.program = config.program;
                        attempt.output = config.__netcoredbgFileAppOutput;
                        assert.equal(typeof attempt.program, 'string');
                        assert.equal(typeof attempt.output, 'string');
                        assert(within(root, attempt.output) && within(attempt.output, attempt.program));
                        attempt.base = path.dirname(path.dirname(attempt.output));
                        assert(samePath(attempt.base, a.base));
                        assert(samePath(path.dirname(attempt.program), attempt.output));
                        assert.equal(path.basename(attempt.program), 'FileApp.dll');
                        assert.match(path.basename(attempt.output), /^run-[A-Za-z0-9]{6}$/);
                        assert.notEqual(attempt.output, a.output);
                        assert.equal(config.type, 'coreclr');
                        assert.equal(config.request, 'launch');
                        assert(samePath(config.cwd, path.dirname(source)));
                        assert(samePath(config.env.DOTNET_ROOT, expected.sdk.root));
                        assert.equal(config.env.ASPNETCORE_URLS, attempt.origin);
                        assert.equal(config.serverReadyAction, undefined);
                        assert.equal(config.checkForDevCert, false);
                        const outputStat = fs.lstatSync(attempt.output);
                        assert(outputStat.isDirectory() && !outputStat.isSymbolicLink());
                        call.artifacts = ['FileApp.dll', 'FileApp.pdb'].map(name => {
                            const artifact = path.join(attempt.output, name);
                            const stat = fs.lstatSync(artifact);
                            assert(stat.isFile() && !stat.isSymbolicLink() && stat.size > 0);
                            return { path: artifact, size: stat.size, sha256: sha256(artifact) };
                        });
                        record('injected-editor-rejection', { label: attempt.label, nonce: attempt.nonce, call });
                        state();
                    });
                    // A callback captured before disposal must still reject this exact token.
                    return undefined; // null would open launch configuration UI instead of simply aborting.
                },
            });
            attempt.providerActive = true;
            attempt.providerRegisteredAtMilliseconds = elapsed(start);
            ownedProvider = { dispose() {
                if (!attempt.providerActive) return;
                attempt.providerActive = false;
                try { provider.dispose(); }
                finally {
                    attempt.providerDisposed = true;
                    attempt.providerDisposalCount++;
                    attempt.providerDisposedAtMilliseconds = elapsed(start);
                    handoffProviders.delete(ownedProvider);
                    record('injected-editor-rejection-provider-disposed', { label: attempt.label, count: attempt.providerDisposalCount });
                    state();
                }
            } };
            handoffProviders.set(ownedProvider, attempt);
            // A phase timeout may outrun this helper: run-level cleanup also owns disarming it.
            subscriptions.push(ownedProvider);
            record('injected-editor-rejection-provider-registered', { label: attempt.label, nonce: attempt.nonce });
            attempt.commandPending = true;
            attempt.invokedAtMilliseconds = elapsed(start);
            state();
            try {
                attempt.commandOperation = Promise.allSettled(Array.from({ length: attempt.commandInvocations }, () => vscode.commands.executeCommand(COMMAND)));
                const outcomes = await attempt.commandOperation;
                const rejected = outcomes.find(outcome => outcome.status === 'rejected');
                if (rejected) throw rejected.reason;
                attempt.commandResults = outcomes.map(outcome => outcome.value);
            } finally { attempt.commandPending = false; attempt.returnedAtMilliseconds = elapsed(start); state(); }
            assert.deepEqual(attempt.commandResults, [false, false, false], 'All three callers must observe the one editor-declined start');
            assert.equal(attempt.providerCalls.length, 1, 'Three failed callers must share one actual editor handoff');
            assert.equal(opened.isDirty, false);
            attempt.sourceAfterSnapshot = fileSnapshot(source);
            attempt.profileAfterSnapshot = fileSnapshot(profile);
            assert.equal(attempt.sourceAfterSnapshot.sha256, attempt.sourceSnapshot.sha256);
            assert.equal(attempt.profileAfterSnapshot.sha256, attempt.profileSnapshot.sha256);
            attempt.ambientDotnetRootAfter = process.env.DOTNET_ROOT ?? null;
            assert.equal(attempt.ambientDotnetRootAfter, attempt.ambientDotnetRootBefore);
            const diagnostic = 'The editor did not start the netcoredbg debug session. Check C# and Debug Console output for details before retrying';
            let tail;
            await until(() => {
                tail = logTail(snapshot);
                return tail.includes(diagnostic) && tail.includes('Phase failed: Starting netcoredbg');
            }, 'exact editor-declined start diagnostic and handoff failure phase');
            attempt.log = { ...logEvidence(snapshot, tail, source),
                webPreparationCompletedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Preparing web launch settings')),
                handoffFailedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase failed: Starting netcoredbg')),
                declinedStartDiagnostics: tail.split(/\r?\n/).filter(line => line.includes(diagnostic)) };
            assert.equal(attempt.log.buildCommands.length, 1, 'Three failed callers must share one real build');
            assert.equal(attempt.log.buildCompletedPhaseDiagnostics.length, 1);
            assert.equal(attempt.log.webPreparationCompletedPhaseDiagnostics.length, 1);
            assert.equal(attempt.log.handoffFailedPhaseDiagnostics.length, 1);
            assert(attempt.log.declinedStartDiagnostics.length > 0);
            assert.equal(attempt.log.completedPhaseDiagnostics.length, 0);
            assert.equal(attempt.log.failedPhaseDiagnostics.length, 0);
            assert.equal(attempt.log.cancelledPhaseDiagnostics.length, 0);
            assert.equal(attempt.log.compilerDiagnostics.length, 0);
            assert.equal(attempt.log.webPreparationFailedPhaseDiagnostics.length, 0);
            assert(!tail.includes('dotnet "dev-certs"'), 'The explicit HTTP profile must avoid certificate commands');
            assert(samePath(attempt.log.buildCommands[0].output, attempt.output));
            assert.equal(attempt.adapterCreationCount, 0);
            assert.equal(attempt.editorStartCount, 0);
            assert.equal(attempt.capturedSessions?.size || 0, 0);
            assert.equal(attempt.session, undefined);
            assert(!attempt.dap.some(message => message.event === 'process'));
            attempt.noSession = true;
            attempt.noAdapter = true;
            attempt.noProcessEvent = true;
            await until(() => !exists(attempt.output) && queueEmpty(attempt.base), 'editor-declined owned output and terminal queues cleanup');
            assert(!exists(attempt.output), 'The editor-declined output must be absent after the resource observation');
            attempt.outputAbsentAfterReturn = true;
            attempt.terminalQueuesEmpty = queueEmpty(attempt.base);
            assert(attempt.terminalQueuesEmpty, 'Both terminal queues must be empty after the declined handoff');
            attempt.outputRemovedAtMilliseconds = elapsed(start);
            assert(await canBind(port));
            attempt.portReusableAtMilliseconds = elapsed(start);
            await stillAlive(b);
            attempt.bAfter = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
            assert.deepEqual(attempt.bAfter, attempt.bBefore);
            record('injected-editor-rejection-confirmed', { label: attempt.label, commandResults: attempt.commandResults,
                output: attempt.output, providerCallCount: attempt.providerCalls.length, noAdapter: true, noSession: true, noProcessEvent: true });
            result.checks.push('Three installed commands share one real successful build and injected editor rejection, return false, remove owned output/queues, release the HTTP port and preserve B');
        } catch (error) {
            firstError = error;
            throw error;
        } finally {
            try { ownedProvider?.dispose(); }
            catch (error) {
                attempt.providerDisposalError = error.stack || String(error);
                if (!firstError) throw error;
            } finally { state(); }
        }
        assert.equal(attempt.providerDisposalCount, 1);
        return attempt;
    }

    async function sdkSelectionFailure(source, revision, port, a, b) {
        const fixture = expected.sdkSelection;
        assert(fixture && fixture.unavailableVersion === '99.0.100');
        const globalJson = path.join(root, 'workspace/global.json');
        const inventory = path.join(root, 'logs/sdk-inventory.txt');
        assert(within(root, globalJson) && within(root, inventory));
        assert(samePath(fixture.globalJson, globalJson) && samePath(fixture.inventory, inventory));
        const inventorySnapshot = fileSnapshot(inventory);
        const inventoryText = Buffer.from(inventorySnapshot.base64, 'base64').toString('utf8');
        const installedVersions = inventoryText.split(/\r?\n/).map(line => /^(\S+)\s+\[/.exec(line)?.[1]).filter(Boolean);
        assert(installedVersions.includes(expected.sdk.version), 'Captured native inventory must include the pinned selected SDK');
        assert(!installedVersions.includes(fixture.unavailableVersion), 'The requested SDK must actually be unavailable');
        let file;
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B command output before SDK selection failure');
        const snapshot = logSnapshot(file);
        const opened = await vscode.workspace.openTextDocument(source);
        assert.equal(opened.isDirty, false);
        assert.equal(opened.getText(), fs.readFileSync(source, 'utf8'));
        assert(opened.getText().startsWith('#:sdk Microsoft.NET.Sdk.Web'), 'The explicit directive must classify without an SDK evaluation');
        await vscode.window.showTextDocument(opened);
        const profile = source.replace(/\.cs$/i, '.run.json');
        const attempt = { label: 'A-sdk-selection-failure', source, revision, port, origin: a.origin, nonce: a.nonce,
            expectedSdkSelectionFailure: true, dap: [], adapterCreationCount: 0, editorStartCount: 0,
            inventorySnapshot, installedVersions, unavailableVersion: fixture.unavailableVersion,
            globalJsonSnapshot: fileSnapshot(globalJson), sourceSnapshot: fileSnapshot(source), profileSnapshot: fileSnapshot(profile),
            sourceWasDirty: opened.isDirty, ambientDotnetRootBefore: process.env.DOTNET_ROOT ?? null,
            previousOutput: a.output, outputParent: path.dirname(a.output), base: a.base };
        assert.equal(attempt.globalJsonSnapshot.sha256, fixture.originalGlobalJsonSha256);
        assert.deepEqual(JSON.parse(Buffer.from(attempt.globalJsonSnapshot.base64, 'base64')), {
            sdk: { version: expected.sdk.version, rollForward: 'disable' },
        });
        assert.equal(JSON.parse(Buffer.from(attempt.profileSnapshot.base64, 'base64')).profiles.LifecycleHttp.environmentVariables.LIFECYCLE_TOKEN, attempt.nonce);
        attempt.outputParentBefore = fs.readdirSync(attempt.outputParent).sort();
        assert(queueEmpty(attempt.base));
        await stillAlive(b);
        attempt.bBefore = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
        failedSdkSelectionAttempts.push(attempt);
        ownedAttempts.push(attempt);
        // Retain the unchanged profile's token after its previous session has stopped.
        byToken.set(attempt.nonce, attempt);
        const originalBytes = Buffer.from(attempt.globalJsonSnapshot.base64, 'base64');
        let firstError;
        try {
            fs.writeFileSync(globalJson, JSON.stringify({ sdk: { version: fixture.unavailableVersion, rollForward: 'disable' } }) + '\n');
            attempt.invalidGlobalJsonSnapshot = fileSnapshot(globalJson);
            attempt.commandPending = true;
            attempt.invokedAtMilliseconds = elapsed(start);
            record('expected-sdk-selection-failure-request', { label: attempt.label, nonce: attempt.nonce,
                globalJsonSha256: attempt.invalidGlobalJsonSnapshot.sha256, inventorySha256: inventorySnapshot.sha256 });
            state();
            try { attempt.commandResult = await vscode.commands.executeCommand(COMMAND); }
            finally { attempt.commandPending = false; attempt.returnedAtMilliseconds = elapsed(start); state(); }
            assert.equal(attempt.commandResult, false, 'An unavailable SDK must decline the installed command');
            assert.equal(opened.isDirty, false);
            attempt.sourceAfterSnapshot = fileSnapshot(source);
            attempt.profileAfterSnapshot = fileSnapshot(profile);
            assert.equal(attempt.sourceAfterSnapshot.sha256, attempt.sourceSnapshot.sha256);
            assert.equal(attempt.profileAfterSnapshot.sha256, attempt.profileSnapshot.sha256);
            attempt.ambientDotnetRootAfter = process.env.DOTNET_ROOT ?? null;
            assert.equal(attempt.ambientDotnetRootAfter, attempt.ambientDotnetRootBefore);
            let tail;
            await until(() => {
                tail = logTail(snapshot);
                return tail.includes('A compatible .NET SDK was not found.') &&
                    tail.includes(`Requested SDK version: ${fixture.unavailableVersion}`) &&
                    tail.includes('Phase failed: Checking .NET SDK');
            }, 'native unavailable SDK diagnostics and exact SDK-check failure phase');
            attempt.log = { ...logEvidence(snapshot, tail, source),
                dotnetCommands: tail.split(/\r?\n/).filter(line => line.startsWith('dotnet ')),
                sdkFailedPhaseDiagnostics: tail.split(/\r?\n/).filter(line => line.startsWith('Phase failed: Checking .NET SDK')),
                sdkNotFoundDiagnostics: tail.split(/\r?\n/).filter(line => line.includes('A compatible .NET SDK was not found.') ||
                    line.includes(`Requested SDK version: ${fixture.unavailableVersion}`)) };
            assert.deepEqual(attempt.log.dotnetCommands, ['dotnet "--version"'], 'SDK failure must precede --info and every build');
            assert.equal(attempt.log.sdkFailedPhaseDiagnostics.length, 1);
            assert.equal(attempt.log.buildCommands.length, 0);
            for (const name of ['Preparing build output', 'Building file-based app', 'Preparing web launch settings', 'Starting netcoredbg']) {
                assert(!tail.includes(`Phase started: ${name}`), `SDK failure must precede ${name}`);
            }
            assert.equal(attempt.adapterCreationCount, 0);
            assert.equal(attempt.editorStartCount, 0);
            assert.equal(attempt.capturedSessions?.size || 0, 0);
            assert.equal(attempt.session, undefined);
            assert(!attempt.dap.some(message => message.event === 'process'));
            attempt.noSession = true;
            attempt.noAdapter = true;
            attempt.noProcessEvent = true;
            attempt.outputParentAfter = fs.readdirSync(attempt.outputParent).sort();
            assert.deepEqual(attempt.outputParentAfter, attempt.outputParentBefore, 'No new output may remain after a pre-allocation SDK failure');
            assert(queueEmpty(attempt.base));
            attempt.noOutputAllocated = true;
            attempt.resourcesCheckedAtMilliseconds = elapsed(start);
            assert(await canBind(port));
            attempt.portReusableAtMilliseconds = elapsed(start);
            await stillAlive(b);
            attempt.bAfter = { sessionId: b.session.id, pid: b.pid, nonce: b.nonce, output: b.output, response: await request(b.origin) };
            assert.deepEqual(attempt.bAfter, attempt.bBefore);
            record('expected-sdk-selection-failure-confirmed', { label: attempt.label, commandResult: attempt.commandResult,
                noOutputAllocated: true, noAdapter: true, noSession: true, noProcessEvent: true });
            result.checks.push('Actual unavailable SDK returns false during SDK checking before output allocation or handoff while source, profile, ambient root and B remain unchanged');
        } catch (error) {
            firstError = error;
            throw error;
        } finally {
            try {
                try { attempt.globalJsonAfterSnapshot = fileSnapshot(globalJson); }
                finally {
                    fs.writeFileSync(globalJson, originalBytes);
                    attempt.restoredGlobalJsonSnapshot = fileSnapshot(globalJson);
                    assert.equal(attempt.restoredGlobalJsonSnapshot.sha256, attempt.globalJsonSnapshot.sha256);
                    attempt.globalJsonRestoredAtMilliseconds = elapsed(start);
                }
                assert.equal(attempt.globalJsonAfterSnapshot.sha256, attempt.invalidGlobalJsonSnapshot.sha256,
                    'The failed command must retain the exact unavailable SDK configuration until restoration');
                record('sdk-selection-original-config-restored', { sha256: attempt.restoredGlobalJsonSnapshot.sha256 });
            } catch (error) {
                attempt.restorationError = error.stack || String(error);
                if (!firstError) throw error;
            } finally { state(); }
        }
        return attempt;
    }

    function readCancellationMarker() {
        const marker = JSON.parse(fs.readFileSync(nativeCancellation.marker, 'utf8').replace(/^\uFEFF/, ''));
        assert.equal(marker.schema, 1);
        assert.equal(marker.nonce, nativeCancellation.nonce, 'Build readiness must belong to this exact isolated fixture');
        assert(Number.isSafeInteger(marker.pid) && marker.pid > 0, 'Build readiness must report its in-process SDK PID');
        return marker;
    }

    async function nativeBuildCancellation(source, revision, port, a, b) {
        let file;
        await until(() => {
            file = outputLog();
            if (!file) return false;
            const text = fs.readFileSync(file, 'utf8');
            return buildCommands(text, source).length === 1 && buildCommands(text, b.source).length === 1 &&
                text.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length === 2;
        }, 'initial A/B command output before native cancellation');
        const snapshot = logSnapshot(file);
        const opened = await vscode.workspace.openTextDocument(source);
        const content = opened.getText();
        const disabled = '#:property LifecycleCancelEnabled=false';
        const enabled = '#:property LifecycleCancelEnabled=true';
        assert.equal(content.split(disabled).length, 2, 'Only A must contain one disabled cancellation fixture gate');
        const replacement = content.replace(disabled, enabled);
        const edit = new vscode.WorkspaceEdit();
        edit.replace(opened.uri, new vscode.Range(opened.positionAt(0), opened.positionAt(content.length)), replacement);
        assert.equal(await vscode.workspace.applyEdit(edit), true);
        assert.equal(opened.isDirty, true, 'Native build cancellation must begin with an unsaved source edit');
        await vscode.window.showTextDocument(opened);
        const attempt = { label: 'A-build-cancel', source, revision, port, origin: `http://127.0.0.1:${port}`,
            nonce: crypto.randomUUID(), expectedBuildCancellation: true, commandInvocations: 3, dap: [] };
        cancelledBuildAttempts.push(attempt);
        ownedAttempts.push(attempt);
        byToken.set(attempt.nonce, attempt);
        fs.writeFileSync(source.replace(/\.cs$/i, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: attempt.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: attempt.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        attempt.commandPending = true;
        attempt.invokedAtMilliseconds = elapsed(start);
        record('native-build-cancel-request', { label: attempt.label, nonce: attempt.nonce, fixtureNonce: nativeCancellation.nonce });
        state();
        let commandsSettled = false;
        const commands = Promise.allSettled(Array.from({ length: attempt.commandInvocations }, () => vscode.commands.executeCommand(COMMAND)))
            .finally(() => {
                commandsSettled = true;
                attempt.commandPending = false;
                attempt.returnedAtMilliseconds = elapsed(start);
                state();
            });
        attempt.commandOperation = commands;
        await until(() => {
            assert(!commandsSettled, 'The native build commands must remain pending until the actual readiness marker');
            return exists(nativeCancellation.marker);
        }, 'nonce-owned in-process native SDK build readiness marker');
        attempt.marker = readCancellationMarker();
        attempt.buildPid = attempt.marker.pid;
        assert(pidAlive(attempt.buildPid), 'The SDK build PID must still be alive at the cancellation barrier');
        attempt.buildReadyAtMilliseconds = elapsed(start);
        assert.equal(opened.isDirty, false, 'The public command must save A before the actual SDK build');
        assert.equal(fs.readFileSync(source, 'utf8'), replacement);
        attempt.sourceSaved = true;
        let tail;
        await until(() => {
            assert(!commandsSettled, 'The SDK build must stay pending before UI cancellation is requested');
            tail = logTail(snapshot);
            return buildCommands(tail, source).length > 0;
        }, 'actual cancellation-attempt build command output');
        const building = buildCommands(tail, source);
        assert.equal(building.length, 1, 'Three concurrent cancellation commands must share one actual build');
        attempt.output = building[0].output;
        attempt.program = path.join(attempt.output, 'FileApp.dll');
        attempt.base = path.dirname(path.dirname(attempt.output));
        assert(samePath(attempt.base, a.base));
        assert.notEqual(attempt.output, a.output);
        assert(exists(attempt.output), 'The live build must retain its owned output at the barrier');
        assert.equal(attempt.session, undefined);
        await stillAlive(b);
        assert(!commandsSettled && pidAlive(attempt.buildPid), 'The SDK build must still be waiting for actual UI Cancel');
        const requestFile = path.join(root, 'needs-ui-cancel.json');
        const uiRequest = { schema: 1, nonce: nativeCancellation.nonce, pid: attempt.buildPid,
            source, port, output: attempt.output, windowTitle: nativeCancellation.windowTitle };
        fs.writeFileSync(requestFile, JSON.stringify(uiRequest, null, 2) + '\n', { flag: 'wx' });
        attempt.uiRequestedAtMilliseconds = elapsed(start);
        record('needs-ui-cancel', uiRequest);
        state();

        const outcomes = await commands;
        const rejected = outcomes.find(outcome => outcome.status === 'rejected');
        if (rejected) throw rejected.reason;
        attempt.commandResults = outcomes.map(outcome => outcome.value);
        assert.deepEqual(attempt.commandResults, [false, false, false], 'Actual progress cancellation must decline all three callers');
        const receiptFile = path.join(root, 'ui-cancel-action.json');
        await until(() => exists(receiptFile), 'actual editor Cancel UI action receipt');
        attempt.uiAction = JSON.parse(fs.readFileSync(receiptFile, 'utf8').replace(/^\uFEFF/, ''));
        assert.equal(attempt.uiAction.schema, 1);
        assert.equal(attempt.uiAction.nonce, nativeCancellation.nonce);
        assert.equal(attempt.uiAction.windowTitle, nativeCancellation.windowTitle);
        assert.equal(attempt.uiAction.action, 'click-cancel');
        assert(!exists(nativeCancellation.release), 'A successful cancellation must not rely on releasing the fixture barrier');
        assert.equal(attempt.session, undefined, 'Cancellation must prevent A debugger handoff');
        await until(() => !pidAlive(attempt.buildPid), 'cancelled direct SDK build PID exit');
        attempt.buildPidGoneObservedAtMilliseconds = elapsed(start);
        record('direct-sdk-pid-gone-observed', { label: attempt.label, pid: attempt.buildPid });
        await until(() => {
            tail = logTail(snapshot);
            return tail.includes('Phase cancelled: Building file-based app');
        }, 'cancelled native build phase diagnostics');
        attempt.log = logEvidence(snapshot, tail, source);
        assert.equal(attempt.log.buildCommands.length, 1);
        assert.equal(attempt.log.cancelledPhaseDiagnostics.length, 1);
        assert.equal(attempt.log.failedPhaseDiagnostics.length, 0);
        assert.equal(attempt.log.completedPhaseDiagnostics.length, 0);
        assert(!tail.includes('Phase timed out:'), 'Expected UI cancellation must stay distinct from a timeout');
        await until(() => !exists(attempt.output) && queueEmpty(attempt.base), 'cancelled-build owned output and terminal queues cleanup');
        assert(!exists(attempt.output), 'The exact cancelled output must be gone at the post-return resource observation');
        assert(queueEmpty(attempt.base));
        attempt.outputRemovedAtMilliseconds = elapsed(start);
        assert(await canBind(port), 'The cancelled A build must leave its HTTP port reusable');
        attempt.portReusableAtMilliseconds = elapsed(start);
        attempt.noSession = !attempt.session;
        await stillAlive(b);
        record('native-build-cancel-confirmed', { label: attempt.label, commandResults: attempt.commandResults,
            buildPid: attempt.buildPid, output: attempt.output, uiAction: attempt.uiAction });
        result.checks.push('Actual progress Cancel during one real SDK build returns false for three callers, starts no A session, releases the direct build PID/output/port and preserves B');
        state();
        return attempt;
    }

    async function failureCleanup() {
        // Foreground cancellation can already have returned while the editor's
        // original start is still waiting on our provider. Settle that provider
        // explicitly; unregistering it cannot settle an existing callback.
        for (const [owner, attempt] of [...handoffGates]) {
            const cleanup = { label: attempt.label, pendingHandoffGate: true, validConfigAlreadyReleased: attempt.gateReleased };
            result.cleanup.push(cleanup);
            try {
                if (!attempt.gateSettled) owner.settle('decline-safety');
                if (attempt.commandOperation) {
                    const outcomes = await bounded(attempt.commandOperation, 'pending handoff foreground command drain', 15000);
                    cleanup.commandOutcomes = outcomes.map(outcome => ({ status: outcome.status,
                        ...(outcome.status === 'fulfilled' ? { value: outcome.value } : { reason: String(outcome.reason) }) }));
                }
                if (attempt.output) await waitUntil(() => !exists(attempt.output) || (attempt.capturedSessions?.size || 0) > 0,
                    'held editor start declines or exposes its exact late session', 15000);
            } catch (error) { cleanup.gateDrainError = error.stack || String(error); }
        }
        if (concurrent) {
            concurrentStopping = true;
            // These fresh fixed paths and nonces belong only to this prepared
            // fixture. Prepublishing a matching release also covers a task that
            // reaches its marker after the first failure; no process is killed.
            for (const entry of concurrent.entries) {
                const cleanup = { label: entry.label, concurrentBarrierSafetyRelease: true };
                result.cleanup.push(cleanup);
                try {
                    if (exists(entry.marker)) {
                        cleanup.marker = readConcurrentMarker(entry);
                        cleanup.pidRespondsToSignalZero = pidAlive(cleanup.marker.pid);
                    } else cleanup.prepublishedForLateBarrier = true;
                    if (exists(entry.release)) assert.equal(fs.readFileSync(entry.release, 'utf8').trim(), entry.nonce);
                    else fs.writeFileSync(entry.release, entry.nonce + '\n', { flag: 'wx' });
                    cleanup.releaseSnapshot = fileSnapshot(entry.release);
                } catch (error) { cleanup.releaseError = error.stack || String(error); }
            }
            try {
                await bounded(Promise.all(concurrentOperations.flatMap(item => [item.observed, item.launch?.commandOperation].filter(Boolean))), 'concurrent partial command failure drain', 15000);
            } catch (error) { result.cleanup.push({ concurrentCommandDrainError: error.stack || String(error) }); }
            result.concurrentCommandOutcomes = concurrentOperations.map(item => ({ label: item.label, settled: item.settled,
                status: item.status, ...(item.error ? { error: item.error.stack || String(item.error) } : {}),
                commandResults: item.launch?.commandResults, sessionId: item.launch?.session?.id }));
        }
        // phase() can time out before its action settles. Keep the exact-token
        // rejection armed during this bounded drain, then disarm before session cleanup.
        for (const attempt of [...failedHandoffAttempts, ...failedNativeHostAttempts].filter(item => item.commandPending && item.commandOperation)) {
            const cleanup = { label: attempt.label, pendingHandoffCommand: true };
            result.cleanup.push(cleanup);
            try {
                const outcomes = await bounded(attempt.commandOperation, 'failure cleanup pending editor-handoff command outcomes', 15000);
                cleanup.pendingCommandOutcomes = outcomes.map(outcome => ({ status: outcome.status,
                    ...(outcome.status === 'fulfilled' ? { value: outcome.value } : { reason: String(outcome.reason) }) }));
            } catch (error) { cleanup.pendingCommandError = error.stack || String(error); }
            state();
        }
        for (const [provider, attempt] of [...handoffProviders]) {
            const cleanup = { label: attempt.label, injectedEditorProvider: true };
            result.cleanup.push(cleanup);
            try {
                provider.dispose();
                cleanup.providerDisposed = attempt.providerDisposed;
            } catch (error) { cleanup.providerDisposalError = error.stack || String(error); }
        }
        // Keep evidence when exact API stop or fixture ownership verification fails.
        // Do not issue global Stop, process-tree kill or filesystem cleanup.
        // Release only this exact nonce/PID-verified in-process fixture barrier;
        // this is failure safety, never a substitute for the successful Cancel UI.
        if (nativeCancellation) {
            const attempt = cancelledBuildAttempts.at(-1);
            const cleanup = { label: 'native-cancellation-fixture-barrier' };
            result.cleanup.push(cleanup);
            try {
                if (attempt?.buildPid && exists(nativeCancellation.marker)) {
                    const marker = readCancellationMarker();
                    assert.equal(marker.pid, attempt.buildPid);
                    if (pidAlive(marker.pid)) {
                        fs.writeFileSync(nativeCancellation.release, nativeCancellation.nonce + '\n', { flag: 'wx' });
                        cleanup.verifiedFixtureBarrierReleased = true;
                        cleanup.pid = marker.pid;
                        await waitUntil(() => !pidAlive(marker.pid), 'failure cleanup direct SDK build PID', 10000);
                        cleanup.pidGone = true;
                    }
                }
            } catch (error) { cleanup.fixtureBarrierError = String(error); }
            try {
                for (const pending of cancelledBuildAttempts.filter(item => item.commandPending && item.commandOperation)) {
                    const outcomes = await bounded(pending.commandOperation, 'failure cleanup pending cancelled-build command outcomes', 15000);
                    cleanup.pendingCommandOutcomes = outcomes.map(outcome => ({ status: outcome.status,
                        ...(outcome.status === 'fulfilled' ? { value: outcome.value } : { error: String(outcome.reason) }) }));
                }
            } catch (error) { cleanup.pendingCommandError = String(error); }
        }
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
                        if (launch.expectedHandoffCancellation) {
                            launch.testStopRequested = true;
                            launch.safetyStopRequestedAtMilliseconds = elapsed(start);
                        }
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
        for (const [owner, attempt] of [...handoffGates]) {
            const cleanup = { label: attempt.label, handoffGateDisposal: true };
            result.cleanup.push(cleanup);
            try {
                if (attempt.output) await waitUntil(() => !exists(attempt.output) &&
                    [...(attempt.capturedSessions?.values() || [])].every(captured => captured.terminated),
                'cancelled handoff background ownership settlement before provider disposal', 15000);
                cleanup.outputAbsent = !attempt.output || !exists(attempt.output);
            } catch (error) { cleanup.backgroundStartError = error.stack || String(error); }
            finally {
                try { owner.dispose(); cleanup.providerDisposed = attempt.providerDisposed; }
                catch (error) { cleanup.providerDisposalError = error.stack || String(error); }
            }
        }
    }

    try {
        if (nativeF5) subscriptions.push(vscode.workspace.onDidSaveTextDocument(document => observe('native-f5-source-save', () => {
            const detail = result.nativeF5.inputs.at(-1);
            if (!detail || !samePath(document.uri.fsPath, detail.request.source)) return;
            detail.savedEvents ||= [];
            const saved = { atMilliseconds: elapsed(start), source: document.uri.fsPath, disk: fileSnapshot(document.uri.fsPath) };
            detail.savedEvents.push(saved);
            record('native-f5-source-save', saved);
        })));
        subscriptions.push(vscode.debug.onDidStartDebugSession(session => observe('editor-start', () => {
            const launch = ownedLaunch(session);
            if (!launch) {
                if (nativeF5) throw new Error(`Unexpected non-owned session during native F5 control: ${session.id}`);
                return;
            }
            if (launch.expectedWebProfileFailure || launch.expectedSdkSelectionFailure || launch.expectedHandoffDeclined || launch.expectedNativeHostFailure || launch.expectedHandoffCancellation) launch.editorStartCount++;
            captureSession(session, launch);
            launch.started = true;
            launch.startedAtMilliseconds = elapsed(start);
            record('editor-start', { label: launch.label, sessionId: session.id, configuration: session.configuration });
            state();
            if (nativeF5Closed) {
                // A first failure closes external input, but an already injected
                // key can still expose a late exact session. Observe and request
                // only that handle's Stop; do not infer global terminal state.
                const stop = Promise.resolve().then(() => vscode.debug.stopDebugging(session)).then(
                    () => record('native-f5-late-exact-stop-acknowledged', { sessionId: session.id }),
                    error => record('native-f5-late-exact-stop-error', { sessionId: session.id, error: String(error) }));
                nativeF5LateStops.push(stop);
                stop.catch(() => {});
            }
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
                if (launch.expectedWebProfileFailure || launch.expectedSdkSelectionFailure || launch.expectedHandoffDeclined || launch.expectedNativeHostFailure || launch.expectedHandoffCancellation) launch.adapterCreationCount++;
                observe('adapter-session', () => captureSession(session, launch));
                // Keep the tracker even if uniqueness validation failed: it can
                // still identify the extra owned debuggee for targeted cleanup.
                return {
                    onWillReceiveMessage(message) { observe('dap-send', () => {
                        if (launch.expectedHandoffCancellation) launch.dapRequests.push({ sessionId: session.id, message, atMilliseconds: elapsed(start) });
                        else if (launch.expectedNativeHostFailure || adapterLoss) {
                            launch.dapRequests ||= [];
                            launch.dapRequests.push({ sessionId: session.id, message });
                        }
                        record('dap-send', { label: launch.label, sessionId: session.id, message });
                    }); },
                    onDidSendMessage(message) { observe('dap-receive', () => {
                        launch.dap.push(message);
                        if (launch.expectedHandoffCancellation) launch.dapTimeline.push({ sessionId: session.id, message, atMilliseconds: elapsed(start) });
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
                    onExit(code, signal) { observe('adapter-exit', () => {
                        const detail = { label: launch.label, sessionId: session.id, code, signal, atMilliseconds: elapsed(start) };
                        if (launch.expectedNativeHostFailure || launch.expectedHandoffCancellation || adapterLoss) {
                            launch.adapterExits ||= [];
                            launch.adapterExits.push(detail);
                        }
                        record('adapter-exit', detail);
                    }); },
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
            if (nativeF5) {
                const bindings = metadata.contributes.keybindings.filter(binding => binding.command === COMMAND);
                assert.equal(bindings.length, 1);
                assert.equal(bindings[0].key, 'f5');
                assert.equal(bindings[0].when, 'editorTextFocus && editorLangId == csharp && !inDebugMode');
                result.nativeF5.installedBinding = bindings[0];
            }
            await extension.activate();
            assert((await vscode.commands.getCommands(true)).includes(COMMAND));
            result.checks.push('Normally installed local candidate activates with exact owned module hashes and isolated loaded path');
        });

        if (nativeF5) {
            const source = path.join(root, 'workspace/a.cs');
            const document = await vscode.workspace.openTextDocument(source);
            assert.equal(vscode.workspace.workspaceFolders?.length || 0, 0);
            assert.equal(vscode.workspace.workspaceFile, undefined);
            assert.equal(vscode.workspace.getConfiguration('files', document.uri).get('autoSave'), 'off');
            await phase('native F5 setup-only keybinding logging', async () => {
                requireNativeF5Open();
                result.nativeF5.setupCommands.push({ command: 'workbench.action.toggleKeybindingsLog', purpose: 'input diagnostics only; not a debugger launch' });
                await vscode.commands.executeCommand('workbench.action.toggleKeybindingsLog');
                requireNativeF5Open();
                // The troubleshooting command can open Output; restore the C#
                // editor before publishing any input request. Root CUA must
                // still observe/click the real editor focus before its key.
                await vscode.window.showTextDocument(document);
                requireNativeF5Open();
            });
            const port = await availablePort();
            let previous;
            for (const input of nativeF5.inputs) {
                requireNativeF5Open();
                const revision = input.sequence === 1 ? 'initial' : `retry-f5-${input.sequence}`;
                if (input.sequence > 1) await phase(`native F5 input ${input.sequence} dirty repeat preparation after exact cleanup`, async () => {
                    requireNativeF5Open();
                    assert(previous.terminated && !pidAlive(previous.pid) && !exists(previous.output) && queueEmpty(previous.base));
                    assert.equal(await canBind(port), true);
                    requireNativeF5Open();
                    const content = document.getText();
                    const priorRevision = `const string revision = "${previous.revision}";`;
                    assert.equal(content.split(priorRevision).length, 2, 'The previous revision must occur exactly once');
                    const replacement = content.replace(priorRevision, `const string revision = "${revision}";`);
                    const edit = new vscode.WorkspaceEdit();
                    edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(content.length)), replacement);
                    assert.equal(await vscode.workspace.applyEdit(edit), true);
                    requireNativeF5Open();
                    assert.equal(document.isDirty, true);
                });
                const launch = await phase(`native F5 input ${input.sequence} breakpoint and HTTP revision`, () => {
                    requireNativeF5Open();
                    nativeF5Operation = launchFromNativeF5(input, source, revision, port, document);
                    return nativeF5Operation;
                });
                nativeF5Operation = undefined;
                if (previous) {
                    assert.notEqual(launch.session.id, previous.session.id);
                    assert.notEqual(launch.nonce, previous.nonce);
                    assert.notEqual(launch.output, previous.output);
                }
                await phase(`native F5 input ${input.sequence} exact API Stop and actual cleanup`, async () => {
                    requireNativeF5Open();
                    result.nativeF5.postStartApiActions.push({ action: 'vscode.debug.stopDebugging', sessionId: launch.session.id, sequence: input.sequence });
                    await stop(launch);
                    requireNativeF5Open();
                });
                previous = launch;
            }
            assert.equal(launches.length, expected.cycles);
            assert.equal(result.nativeF5.inputs.length, expected.cycles);
            assert(result.nativeF5.inputs.every(input => input.route && input.response && input.receipt));
            for (const key of ['nonce', 'output']) assert.equal(new Set(launches.map(launch => launch[key])).size, expected.cycles, `Every native input needs a distinct ${key}`);
            assert.equal(new Set(launches.map(launch => launch.session.id)).size, expected.cycles, 'Every native input needs a distinct session');
            assert.equal(document.isDirty, false);
            closeNativeF5(`${expected.cycles}-cycle control completed`);
            result.checks.push(`One no-folder profile: ${expected.cycles} external native injected F5 inputs, dirty save/revision repeats, exact per-session Stop and PID/port/output cleanup; not full qualification or hardware keyboard input`);
            if (eventError) throw eventError;
            result.success = true;
            return;
        }

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
        let a, b;
        if (concurrent) ({ a, b } = await phase('A and B concurrent installed commands with independent SDK barriers',
            () => concurrentFiles(aSource, bSource, aPort, bPort, document)));
        else {
            a = await phase('A initial installed-command launch and breakpoint', () => launchFile('A-0', aSource, 'initial', aPort, true, document));
            b = await phase('B independent installed-command launch', () => launchFile('B', bSource, 'initial', bPort));
        }
        result.checks.push('Two independent real Web sessions respond with distinct owned nonces and PIDs');
        assert.notEqual(a.pid, b.pid);
        assert.notEqual(a.session.id, b.session.id);
        if (adapterLoss) a = await phase('A exact native adapter process loss observed while B survives', () => nativeAdapterLoss(a, b));

        for (let cycle = 0; cycle < expected.cycles; cycle++) {
            await phase(`A cycle ${cycle} targeted stop and owned cleanup`, () => stop(a));
            await phase(`B preserved after A cycle ${cycle}`, () => stillAlive(b));
            result.checks.push(`A cycle ${cycle}: exact session terminates, PID exits, port rebinds and output/terminal queues clear while B survives`);
            const failed = scenario === 'build-failure-retry' && cycle === 0
                ? await phase('A actual compiler failure and owned cleanup while B survives', () => compilerFailure(aSource, a.revision, aPort, a, b))
                : scenario === 'native-build-cancel' && cycle === 0
                    ? await phase('A actual progress Cancel during native build while B survives', () => nativeBuildCancellation(aSource, a.revision, aPort, a, b))
                    : scenario === 'web-profile-failure-retry' && cycle === 0
                        ? await phase('A actual Web profile failure after successful build while B survives', () => webProfileFailure(aSource, a.revision, aPort, a, b))
                        : scenario === 'sdk-selection-failure-retry' && cycle === 0
                            ? await phase('A actual unavailable SDK before output allocation while B survives', () => sdkSelectionFailure(aSource, a.revision, aPort, a, b))
                            : scenario === 'debug-handoff-declined-retry' && cycle === 0
                                ? await phase('A injected editor rejection after successful real build while B survives', () => debugHandoffDeclined(aSource, a.revision, aPort, a, b))
                                : scenario === 'native-host-failure-retry' && cycle === 0
                                    ? await phase('A actual native host startup failure after successful real build while B survives', () => nativeHostFailure(aSource, a.revision, aPort, a, b))
                                    : scenario === 'native-handoff-cancel' && cycle === 0
                                        ? await phase('A actual progress Cancel during held editor handoff and late native session cleanup', () => nativeHandoffCancellation(aSource, a.revision, aPort, a, b))
                        : undefined;
            if (cycle + 1 < expected.cycles) {
                const revision = `retry-${cycle + 1}`;
                await phase(`A cycle ${cycle + 1} dirty edit and installed-command retry`, async () => {
                    if (failed?.expectedHandoffDeclined) {
                        assert.equal(failed.providerActive, false);
                        assert.equal(failed.providerDisposed, true);
                        assert.equal(failed.providerDisposalCount, 1);
                        assert.equal(sha256(failed.profileSnapshot.path), failed.profileSnapshot.sha256);
                    }
                    if (failed?.expectedHandoffCancellation) {
                        assert.equal(failed.providerDisposed, true);
                        assert.equal(failed.providerDisposalCount, 1);
                        assert.equal(failed.providerPending, false);
                        assert.equal(failed.lateTerminationObservedWithoutTestStop, true);
                    }
                    const current = await vscode.workspace.openTextDocument(aSource);
                    const content = current.getText();
                    assert(content.includes(`const string revision = "${a.revision}";`));
                    let replacement = content.replace(`const string revision = "${a.revision}";`, `const string revision = "${revision}";`);
                    if (concurrent && cycle === 0) {
                        assert(content.includes('#:property LifecycleConcurrentEnabled=true'));
                        replacement = replacement.replace('#:property LifecycleConcurrentEnabled=true', '#:property LifecycleConcurrentEnabled=false');
                    }
                    if (failed?.expectedBuildFailure) {
                        assert(content.includes('marker += __missingLifecycleValue;'));
                        replacement = replacement.replace('marker += __missingLifecycleValue;', 'marker += 2;');
                    } else if (failed?.expectedBuildCancellation) {
                        assert(content.includes('#:property LifecycleCancelEnabled=true'));
                        replacement = replacement.replace('#:property LifecycleCancelEnabled=true', '#:property LifecycleCancelEnabled=false');
                    }
                    const edit = new vscode.WorkspaceEdit();
                    edit.replace(current.uri, new vscode.Range(current.positionAt(0), current.positionAt(content.length)), replacement);
                    assert.equal(await vscode.workspace.applyEdit(edit), true);
                    assert.equal(current.isDirty, true, 'Retry must exercise the installed command\'s source save');
                    const concurrentRetry = concurrent && cycle === 0;
                    const snapshot = failed ? logSnapshot(failed.log.path) : concurrentRetry ? logSnapshot(outputLog()) : undefined;
                    a = await launchFile(`A-${cycle + 1}`, aSource, revision, aPort, false, current, failed || concurrentRetry ? 3 : 1);
                    assert.equal(fs.readFileSync(aSource, 'utf8'), current.getText());
                    if (concurrentRetry) {
                        let tail;
                        await until(() => { tail = logTail(snapshot); return tail.includes('Phase completed: Starting netcoredbg'); },
                            'three-caller dirty retry after concurrent A Stop');
                        const log = logEvidence(snapshot, tail, aSource);
                        assert.equal(log.buildCommands.length, 1);
                        assert.equal(log.buildCompletedPhaseDiagnostics.length, 1);
                        assert.equal(log.completedPhaseDiagnostics.length, 1);
                        assert.equal(log.failedPhaseDiagnostics.length, 0);
                        assert.equal(log.cancelledPhaseDiagnostics.length, 0);
                        assert(samePath(log.buildCommands[0].output, a.output));
                        assert.equal(a.capturedSessions.size, 1);
                        assert(current.getText().includes('#:property LifecycleConcurrentEnabled=false'));
                        const initial = result.concurrent.builds[0];
                        assert.notEqual(a.output, initial.output);
                        assert.notEqual(a.session.id, initial.sessionId);
                        assert.notEqual(a.nonce, initial.response.nonce);
                        assert(!exists(initial.output));
                        await stillAlive(b);
                        result.concurrent.retry = { label: a.label, source: a.source, revision, nonce: a.nonce,
                            pid: a.pid, sessionId: a.session.id, output: a.output, response: a.response,
                            commandResults: a.commandResults, commandInvocations: a.commandInvocations, log,
                            sourceSnapshot: fileSnapshot(aSource), profileSnapshot: fileSnapshot(aSource.replace(/\.cs$/i, '.run.json')),
                            disabledBarrier: true, freshOutput: true, freshSession: true, freshToken: true,
                            bCheckpoint: { sessionId: b.session.id, pid: b.pid, response: await request(b.origin), output: b.output,
                                sourceSnapshot: fileSnapshot(b.source), profileSnapshot: fileSnapshot(b.source.replace(/\.cs$/i, '.run.json')) } };
                        assert.equal(result.concurrent.retry.bCheckpoint.sourceSnapshot.sha256, result.concurrent.builds[1].sourceSnapshot.sha256);
                        assert.equal(result.concurrent.retry.bCheckpoint.profileSnapshot.sha256, result.concurrent.builds[1].profileSnapshot.sha256);
                        for (let index = 0; index < concurrent.entries.length; index++) {
                            assert.equal(sha256(concurrent.entries[index].marker), result.concurrent.beforeFirstRelease.markerSnapshots[index].sha256);
                        }
                        record('concurrent-files-dirty-retry-confirmed', result.concurrent.retry);
                        result.checks.push('After concurrent preparation, exact A Stop preserves B and a dirty A revision with the one-shot barrier disabled retries through one real build/session shared by three callers');
                    }
                    if (failed) {
                        let tail;
                        await until(() => { tail = logTail(snapshot); return tail.includes('Phase completed: Starting netcoredbg'); },
                            'corrected coalesced retry command output');
                        const log = logEvidence(snapshot, tail, aSource);
                        assert.equal(log.buildCommands.length, 1, 'Three concurrent corrected commands must share exactly one build');
                        assert.equal(log.completedPhaseDiagnostics.length, 1, 'Three concurrent corrected commands must share one handoff');
                        assert.equal(log.failedPhaseDiagnostics.length, 0);
                        assert.equal(log.cancelledPhaseDiagnostics.length, 0);
                        if (failed.expectedWebProfileFailure) {
                            assert.equal(log.buildCompletedPhaseDiagnostics.length, 1);
                            assert.equal(log.webPreparationFailedPhaseDiagnostics.length, 0);
                            assert.equal(log.webProfileRootDiagnostics.length, 0);
                            assert.notEqual(a.profileSnapshot.sha256, failed.profileSnapshot.sha256);
                            assert(!Object.hasOwn(JSON.parse(Buffer.from(a.profileSnapshot.base64, 'base64')).profiles.LifecycleHttp.environmentVariables, 'DOTNET_ROOT'));
                        }
                        if (failed.expectedHandoffDeclined) {
                            assert.equal(log.buildCompletedPhaseDiagnostics.length, 1);
                            assert.equal(log.webPreparationFailedPhaseDiagnostics.length, 0);
                            assert(!tail.includes('Phase failed: Starting netcoredbg'));
                            assert(!tail.includes('The editor did not start the netcoredbg debug session.'));
                            assert.notEqual(a.nonce, failed.nonce);
                            assert.notEqual(a.sourceSnapshot.sha256, failed.sourceSnapshot.sha256);
                            assert.notEqual(a.profileSnapshot.sha256, failed.profileSnapshot.sha256);
                            assert.equal(failed.providerCalls.length, 1, 'The disposed provider cannot intercept the corrected retry');
                        }
                        if (failed.expectedNativeHostFailure) {
                            assert.equal(log.buildCompletedPhaseDiagnostics.length, 1);
                            assert.equal(log.webPreparationFailedPhaseDiagnostics.length, 0);
                            assert(!tail.includes('Phase failed: Starting netcoredbg'));
                            assert.notEqual(a.nonce, failed.nonce);
                            assert.notEqual(a.sourceSnapshot.sha256, failed.sourceSnapshot.sha256);
                            assert.notEqual(a.profileSnapshot.sha256, failed.profileSnapshot.sha256);
                            const profileEnvironment = JSON.parse(Buffer.from(a.profileSnapshot.base64, 'base64')).profiles.LifecycleHttp.environmentVariables;
                            assert(!Object.hasOwn(profileEnvironment, 'DOTNET_ROLL_FORWARD'));
                            assert(!Object.hasOwn(a.session.configuration.env, 'DOTNET_ROLL_FORWARD'));
                            assert(!a.dap.some(message => message.type === 'response' && message.command === 'configurationDone' && message.success === false));
                            assert(!a.dap.some(message => message.event === 'output' && message.body?.output?.includes("Invalid value for environment variable 'DOTNET_ROLL_FORWARD'.")));
                            assert.equal(process.env.DOTNET_ROLL_FORWARD ?? null, failed.ambientRollForwardBefore);
                        }
                        if (failed.expectedHandoffCancellation) {
                            assert.equal(log.buildCompletedPhaseDiagnostics.length, 1);
                            assert.equal(log.webPreparationFailedPhaseDiagnostics.length, 0);
                            assert(!tail.includes('Phase cancelled: Starting netcoredbg') && !tail.includes('Phase failed: Starting netcoredbg'));
                            assert.equal(failed.providerCalls.length, 1);
                            assert.notEqual(a.nonce, failed.nonce);
                            assert.notEqual(a.sourceSnapshot.sha256, failed.sourceSnapshot.sha256);
                            assert.notEqual(a.profileSnapshot.sha256, failed.profileSnapshot.sha256);
                        }
                        assert(samePath(log.buildCommands[0].output, a.output), 'Coalesced build output must identify the one captured session');
                        if (failed.expectedSdkSelectionFailure) {
                            assert.equal(sha256(failed.restoredGlobalJsonSnapshot.path), failed.globalJsonSnapshot.sha256);
                            assert.equal(log.buildCompletedPhaseDiagnostics.length, 1);
                            assert(!tail.includes('Phase failed: Checking .NET SDK'));
                        } else assert(!exists(failed.output));
                        result.coalescedRetry = { label: a.label, commandInvocations: a.commandInvocations,
                            commandResults: a.commandResults, sessionId: a.session.id, output: a.output,
                            sessionIds: [...a.capturedSessions.keys()],
                            log,
                            ...(failed.expectedSdkSelectionFailure ? {
                                previousOutput: failed.previousOutput, freshOutput: a.output !== failed.previousOutput,
                                failedAttemptAllocatedOutput: false, globalJsonSnapshot: fileSnapshot(failed.restoredGlobalJsonSnapshot.path),
                            } : { failedOutput: failed.output, freshOutput: a.output !== failed.output }),
                            ...((failed.expectedWebProfileFailure || failed.expectedSdkSelectionFailure || failed.expectedHandoffDeclined || failed.expectedNativeHostFailure || failed.expectedHandoffCancellation) ? { profileSnapshot: a.profileSnapshot, sourceSnapshot: a.sourceSnapshot } : {}),
                            ...(failed.expectedHandoffDeclined ? { providerDisposedBeforeRetry: failed.providerDisposed,
                                failedNonce: failed.nonce, nonce: a.nonce, freshToken: a.nonce !== failed.nonce } : {}),
                            ...(failed.expectedNativeHostFailure ? { correctedRollForwardProfile: true,
                                failedNonce: failed.nonce, nonce: a.nonce, freshToken: a.nonce !== failed.nonce,
                                nativeLaunchEnvironment: a.session.configuration.env } : {}),
                            ...(failed.expectedHandoffCancellation ? { providerDisposedBeforeRetry: true, failedNonce: failed.nonce,
                                nonce: a.nonce, freshToken: a.nonce !== failed.nonce } : {}) };
                        if (failed.expectedSdkSelectionFailure) {
                            assert(result.coalescedRetry.freshOutput);
                            assert(!exists(failed.previousOutput));
                        }
                        await stillAlive(b);
                        result.checks.push(failed.expectedBuildCancellation
                            ? 'Dirty retry after native build cancellation shares one saved build/session and fresh output across three callers while B survives'
                            : failed.expectedWebProfileFailure
                                ? 'Corrected Web profile and dirty revision retry share one saved build/session and fresh output across three callers while B survives'
                                : failed.expectedSdkSelectionFailure
                                    ? 'Original SDK configuration restored and dirty revision retry share one saved build/session and fresh output across three callers while B survives'
                                    : failed.expectedHandoffDeclined
                                        ? 'Injected editor provider disposed and dirty valid revision retries with three callers sharing one saved build/session, fresh token/output and unchanged B'
                                        : failed.expectedNativeHostFailure
                                            ? 'Corrected per-file roll-forward profile and dirty revision retry share one saved real build/session and fresh token/output across three callers while B survives'
                                            : failed.expectedHandoffCancellation
                                                ? 'After actual handoff UI Cancel and late native session cleanup, the disposed gate permits one fresh dirty build/session shared by three callers while B survives'
                                : 'Dirty compiler correction retries with three concurrent commands sharing one build/session and fresh output while B survives');
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
        if (nativeF5) {
            try { closeNativeF5('first failure; do not inject another key'); }
            catch (closeError) { result.nativeF5.closeError = String(closeError); }
        }
        record('first-failure', result.firstFailure);
        state();
        if (nativeF5Operation) {
            // phase's timeout does not cancel its action. Closing the input gate
            // makes all subsequent polls/continuations fail before another key
            // request, edit or Continue. A stuck editor API remains uncertainty.
            try { await bounded(Promise.allSettled([nativeF5Operation]), 'native F5 failed observer continuation drain', 5000); }
            catch (drainError) { result.nativeF5.observerDrainError = String(drainError); }
        }
        await failureCleanup();
        if (nativeF5LateStops.length) {
            try { await bounded(Promise.allSettled(nativeF5LateStops), 'native F5 late exact Stop acknowledgements', 5000); }
            catch (stopError) { result.nativeF5.lateStopDrainError = String(stopError); }
        }
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
            profileSnapshot: launch.profileSnapshot, sourceSnapshot: launch.sourceSnapshot,
            dap: adapterLoss ? launch.dap : undefined, dapRequests: launch.dapRequests, adapterExits: launch.adapterExits,
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
        result.failedWebProfileAttempts = failedWebProfileAttempts.map(attempt => ({
            label: attempt.label, source: attempt.source, revision: attempt.revision, nonce: attempt.nonce,
            origin: attempt.origin, port: attempt.port, expectedWebProfileFailure: true,
            commandPending: attempt.commandPending, commandResult: attempt.commandResult,
            invokedAtMilliseconds: attempt.invokedAtMilliseconds, returnedAtMilliseconds: attempt.returnedAtMilliseconds,
            profileSnapshot: attempt.profileSnapshot, profileAfterSha256: attempt.profileAfterSha256, invalidRoot: attempt.invalidRoot,
            sourceSnapshot: attempt.sourceSnapshot, sourceAfterSha256: attempt.sourceAfterSha256, sourceUnchanged: attempt.sourceUnchanged,
            sourceWasDirty: attempt.sourceWasDirty, ambientDotnetRootBefore: attempt.ambientDotnetRootBefore,
            ambientDotnetRootAfter: attempt.ambientDotnetRootAfter,
            adapterCreationCount: attempt.adapterCreationCount, editorStartCount: attempt.editorStartCount,
            sessionId: attempt.session?.id, pid: attempt.pid, capturedSessions: capturedSessionState(attempt), dap: attempt.dap,
            output: attempt.output, program: attempt.program, base: attempt.base,
            outputRemovedAtMilliseconds: attempt.outputRemovedAtMilliseconds,
            portReusableAtMilliseconds: attempt.portReusableAtMilliseconds,
            noSession: attempt.noSession, noAdapter: attempt.noAdapter, noProcessEvent: attempt.noProcessEvent, log: attempt.log,
        }));
        result.failedSdkSelectionAttempts = failedSdkSelectionAttempts.map(attempt => {
            const { session, capturedSessions, ...evidence } = attempt;
            return { ...evidence, sessionId: session?.id, capturedSessions: capturedSessionState(attempt) };
        });
        result.failedHandoffAttempts = failedHandoffAttempts.map(attempt => {
            const { session, capturedSessions, commandOperation, ...evidence } = attempt;
            return { ...evidence, sessionId: session?.id, capturedSessions: capturedSessionState(attempt) };
        });
        result.failedNativeHostAttempts = failedNativeHostAttempts.map(attempt => {
            const { session, capturedSessions, commandOperation, ...evidence } = attempt;
            return { ...evidence, sessionId: session?.id, capturedSessions: capturedSessionState(attempt) };
        });
        result.cancelledHandoffAttempts = cancelledHandoffAttempts.map(attempt => {
            const { session, capturedSessions, commandOperation, ...evidence } = attempt;
            return { ...evidence, sessionId: session?.id, capturedSessions: capturedSessionState(attempt) };
        });
        result.cancelledBuildAttempts = cancelledBuildAttempts.map(attempt => ({
            label: attempt.label, source: attempt.source, revision: attempt.revision, nonce: attempt.nonce,
            origin: attempt.origin, port: attempt.port, expectedBuildCancellation: true,
            commandPending: attempt.commandPending, commandInvocations: attempt.commandInvocations, commandResults: attempt.commandResults,
            invokedAtMilliseconds: attempt.invokedAtMilliseconds, returnedAtMilliseconds: attempt.returnedAtMilliseconds,
            sourceSaved: attempt.sourceSaved, sessionId: attempt.session?.id, capturedSessions: capturedSessionState(attempt),
            marker: attempt.marker, buildPid: attempt.buildPid, buildReadyAtMilliseconds: attempt.buildReadyAtMilliseconds,
            buildPidGoneObservedAtMilliseconds: attempt.buildPidGoneObservedAtMilliseconds,
            uiRequestedAtMilliseconds: attempt.uiRequestedAtMilliseconds, uiAction: attempt.uiAction,
            output: attempt.output, program: attempt.program, base: attempt.base,
            outputRemovedAtMilliseconds: attempt.outputRemovedAtMilliseconds,
            portReusableAtMilliseconds: attempt.portReusableAtMilliseconds, noSession: attempt.noSession, log: attempt.log,
        }));
        state();
        fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
