'use strict';

// One normally installed candidate and one actual extension host throughout.
// The foreign-controller receipt is synthetic terminal data, not an old SDK/debuggee.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const vscode = require('vscode');
const COMMAND = 'netcoredbg.debugActiveFile';
const MODULES = ['entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const sha = file => hash(fs.readFileSync(file));
const same = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
const exists = file => { try { fs.lstatSync(file); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; } };
function alive(pid) {
    assert(Number.isSafeInteger(pid) && pid > 0);
    try { process.kill(pid, 0); return true; } catch (e) { if (e.code === 'ESRCH') return false; throw e; }
}
function within(root, file) {
    const r = path.relative(path.resolve(root), path.resolve(file));
    return r && !r.startsWith('..') && !path.isAbsolute(r);
}
async function port() {
    const s = net.createServer(); await new Promise((r, j) => { s.once('error', j); s.listen(0, '127.0.0.1', r); });
    const p = s.address().port; await new Promise((r, j) => s.close(e => e ? j(e) : r())); return p;
}
async function bindable(p) {
    const s = net.createServer(); return new Promise((r, j) => { s.once('error', e => e.code === 'EADDRINUSE' ? r(false) : j(e));
        s.listen(p, '127.0.0.1', () => s.close(e => e ? j(e) : r(true))); });
}
async function probe(origin) {
    const r = await fetch(origin + '/probe', { signal: AbortSignal.timeout(2000) }); assert.equal(r.status, 200); return r.json();
}

exports.run = async function run() {
    const root = process.env.NETCOREDBG_LIFECYCLE_ROOT;
    assert(root && path.isAbsolute(root));
    const read = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8').replace(/^\uFEFF/, ''));
    const write = (name, value) => fs.writeFileSync(path.join(root, name), JSON.stringify(value, null, 2) + '\n');
    const expected = read('expected.json');
    assert.equal(expected.scenario, 'installed-command-recovery-retry');
    const nonce = expected.commandRecovery.nonce;
    const result = { schema: 1, success: false, expected, editorApiVersion: vscode.version,
        extensionHostPid: process.pid, checks: [], launches: [], scope: {
            normallyInstalled: true, appLaunches: 1, hostReload: false, commandApi: true, physicalF5: false,
            platform: `${process.platform}-${process.arch}`, macOS: false, qualification: false,
            syntheticForeignControllerReceipt: true, actualOldHost: false, injectedTargetRuntime: false,
            exactQueuedOutputRmFaultOnly: true, localOnly: true, published: false,
        } };
    const trace = (event, value) => fs.appendFileSync(path.join(root, 'trace.jsonl'),
        JSON.stringify({ atUtc: new Date().toISOString(), event, value }) + '\n');
    const launches = [];
    const byToken = new Map();
    const subscriptions = [];
    const originalRm = fs.promises.rm;
    let observerError;
    let fixture;
    let releaseGate;
    let gateReleased = false;
    let unlocked = false;
    let rmAttempts = 0;
    const faultCalls = [];
    function launchState(l) {
        return { ...l, session: undefined, captured: undefined,
            sessionId: l.session?.id, capturedSessions: [...l.captured.values()].map(c => ({
                sessionId: c.session.id, output: c.output, program: c.program, pid: c.pid, terminated: c.terminated,
            })) };
    }
    function saveLaunches() { write('owned-launches.json', { schema: 1, launches: launches.map(launchState) }); }
    function observe(action) {
        try { action(); } catch (e) { observerError ||= e; trace('observer-error', e.stack); saveLaunches(); }
    }
    async function until(check, label, limit = 90000) {
        const start = performance.now();
        while (true) {
            if (observerError) throw observerError;
            if (await check()) return;
            if (performance.now() - start > limit) throw Error(`Safety timeout: ${label}`);
            await delay(25);
        }
    }
    function capture(s) {
        const l = byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN); if (!l) return;
        // Keep every token-matched session before asserting uniqueness, for failure cleanup.
        if (!l.captured.has(s.id)) l.captured.set(s.id, { session: s,
            output: s.configuration.__netcoredbgFileAppOutput, program: s.configuration.program });
        l.session ||= s;
        saveLaunches();
        assert.equal(l.session.id, s.id, 'Concurrent callers must start one exact session');
        assert.equal(s.type, 'coreclr');
        l.output = s.configuration.__netcoredbgFileAppOutput; l.program = s.configuration.program;
        assert(within(root, l.output) && within(root, l.program) && same(path.dirname(l.program), l.output));
        l.base = path.dirname(path.dirname(l.output));
        saveLaunches();
    }
    function outputLog() {
        const matches = [];
        function visit(d) {
            if (!exists(d)) return;
            for (const e of fs.readdirSync(d, { withFileTypes: true })) {
                const f = path.join(d, e.name);
                if (e.isDirectory()) visit(f); else if (e.isFile() && e.name.endsWith('C# File Debugging.log')) matches.push(f);
            }
        }
        visit(path.join(root, 'profile/logs')); assert(matches.length <= 1); return matches[0];
    }
    function outputText() { const file = outputLog(); return file ? fs.readFileSync(file, 'utf8') : ''; }
    function completions() {
        return outputText().split(/\r?\n/).filter(s => /^Terminal output recovery: scanned=\d+, attempted=\d+, removed=\d+$/.test(s));
    }
    function buildCommands(text, source) {
        return text.split(/\r?\n/).filter(s => s.startsWith('dotnet ')).map(s => {
            const payload = s.slice(7); const args = [...payload.matchAll(/"(?:\\.|[^"\\])*"/g)].map(m => JSON.parse(m[0]));
            assert.equal(args.map(a => JSON.stringify(a)).join(' '), payload);
            return { args, output: args[args.indexOf('--output') + 1] };
        }).filter(c => c.args[0] === 'build' && same(c.args[1], source));
    }
    function preserved() {
        for (const s of fixture.sentinels) assert.equal(fs.readFileSync(s.path, 'utf8'), s.content);
    }
    function queueState(wantReady) {
        const ready = path.join(fixture.base, 'terminal-cleanup-v1');
        const stage = path.join(fixture.base, 'terminal-cleanup-staging-v1');
        const stageNames = exists(stage) ? fs.readdirSync(stage).sort() : [];
        if (JSON.stringify(stageNames) !== JSON.stringify([fixture.recordOnlyId])) return false;
        // Read READY after STAGING to avoid missing a normal cleanup's atomic publication.
        const readyNames = exists(ready) ? fs.readdirSync(ready).sort() : [];
        return JSON.stringify(readyNames) === JSON.stringify(wantReady ? [fixture.entryId] : []);
    }
    async function keep(l) {
        assert(!l.terminated && alive(l.pid) && exists(l.output) && exists(l.program));
        assert.deepEqual(await probe(l.origin), l.response); assert.equal(process.pid, result.extensionHostPid);
        trace('unrelated-preserved', { label: l.label, pid: l.pid, sessionId: l.session.id, response: l.response });
    }
    async function start(label, sourceName, revision, count) {
        const l = { label, source: path.join(root, 'workspace', sourceName), revision,
            nonce: crypto.randomUUID(), port: await port(), captured: new Map(), commandInvocations: count };
        l.origin = `http://127.0.0.1:${l.port}`; launches.push(l); byToken.set(l.nonce, l); saveLaunches();
        fs.writeFileSync(l.source.replace(/\.cs$/, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: l.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: l.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }));
        const document = await vscode.workspace.openTextDocument(l.source);
        await vscode.window.showTextDocument(document);
        l.dirtyBeforeCommand = document.isDirty;
        l.commandPending = true; saveLaunches();
        try {
            const outcomes = await Promise.allSettled(Array.from({ length: count }, () => vscode.commands.executeCommand(COMMAND)));
            const rejection = outcomes.find(o => o.status === 'rejected'); if (rejection) throw rejection.reason;
            l.commandResults = outcomes.map(o => o.value); assert.deepEqual(l.commandResults, Array(count).fill(true));
        } finally { l.commandPending = false; saveLaunches(); }
        assert.equal(document.isDirty, false);
        await until(() => l.started && l.session, `${label} exact session start`);
        assert.equal(l.captured.size, 1); assert(exists(l.program));
        assert.equal(l.session.configuration.env.ASPNETCORE_URLS, l.origin);
        assert.equal(l.session.configuration.serverReadyAction, undefined);
        assert.equal(l.session.configuration.checkForDevCert, false);
        await until(async () => {
            try { l.response = await probe(l.origin); } catch (e) { if (e instanceof assert.AssertionError) throw e; return false; }
            assert.equal(l.response.nonce, l.nonce); assert.equal(l.response.revision, revision); assert.equal(l.response.value, 42);
            if (l.pid) assert.equal(l.pid, l.response.pid); l.pid = l.response.pid; assert(alive(l.pid));
            const c = l.captured.get(l.session.id); if (c.pid) assert.equal(c.pid, l.pid); c.pid = l.pid;
            return true;
        }, `${label} real HTTP ready`);
        l.httpReadyAtUtc = new Date().toISOString();
        saveLaunches(); trace('real-launch-ready', launchState(l)); return l;
    }
    async function stop(l, wantReady) {
        await vscode.debug.stopDebugging(l.session);
        await until(() => l.terminated, `${l.label} exact session termination`);
        await until(() => !alive(l.pid), `${l.label} exact PID exit`);
        await until(() => bindable(l.port), `${l.label} port release`);
        await until(() => !exists(l.output) && queueState(wantReady) && !exists(l.output), `${l.label} settled output and queues`);
        preserved(); saveLaunches(); trace('exact-owned-resources-released', launchState(l));
    }
    try {
        subscriptions.push(vscode.debug.onDidStartDebugSession(s => observe(() => {
            capture(s); const l = byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN); if (l) l.started = true;
        })));
        subscriptions.push(vscode.debug.onDidTerminateDebugSession(s => observe(() => {
            const l = byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN); if (!l) return;
            const c = l.captured.get(s.id); if (c) c.terminated = true;
            if (s.id === l.session?.id) l.terminated = true;
            saveLaunches(); trace('matching-termination', { label: l.label, sessionId: s.id, pid: l.pid });
        })));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr', { createDebugAdapterTracker(s) {
            const l = byToken.get(s.configuration?.env?.LIFECYCLE_TOKEN); if (!l) return;
            observe(() => capture(s));
            return { onDidSendMessage(m) { observe(() => {
                if (m.event === 'process' && m.body?.isLocalProcess) {
                    assert(Number.isSafeInteger(m.body.systemProcessId) && m.body.systemProcessId > 0);
                    l.pid = m.body.systemProcessId; l.captured.get(s.id).pid = l.pid; saveLaunches();
                }
                trace('dap-receive', { sessionId: s.id, message: m });
            }); } };
        } }));
        const extension = vscode.extensions.getExtension(expected.extensionId);
        const dependency = vscode.extensions.getExtension('ms-dotnettools.vscode-dotnet-runtime');
        assert(extension && dependency && within(path.join(root, 'extensions'), extension.extensionPath));
        assert(within(path.join(root, 'extensions'), dependency.extensionPath));
        assert.equal(dependency.packageJSON.version, expected.dependency.version);
        const metadata = JSON.parse(fs.readFileSync(path.join(extension.extensionPath, 'package.json')));
        assert(metadata.__metadata && metadata.netcoredbgBuild.localCandidate);
        assert.equal(metadata.version, expected.candidate.version);
        assert.equal(metadata.netcoredbgBuild.lifecycleBuildId, expected.candidate.buildId);
        assert.equal(`${process.platform}-${process.arch}`, expected.candidate.target);
        result.installedModules = {};
        for (const name of MODULES) {
            const actual = sha(path.join(extension.extensionPath, '.netcoredbg', name));
            assert.equal(actual, expected.candidate.ownedModules[name]); result.installedModules[name] = actual;
        }
        result.installedExtension = { path: extension.extensionPath, version: metadata.version,
            metadata: metadata.__metadata, build: metadata.netcoredbgBuild,
            dependencyPath: dependency.extensionPath, dependencyVersion: dependency.packageJSON.version };
        write('host-ready.json', { schema: 1, nonce, extensionHostPid: process.pid, installed: result.installedExtension });
        await until(() => exists(path.join(root, 'host-ack.json')), 'runner exact host/app lineage acknowledgement', 30000);
        const ack = read('host-ack.json'); assert.equal(ack.nonce, nonce); assert.equal(ack.extensionHostPid, process.pid);
        result.editorPid = ack.editorPid;
        await extension.activate();
        assert((await vscode.commands.getCommands(true)).includes(COMMAND));
        const b = await start('B-live', 'b.cs', 'initial', 1);
        await until(() => completions().length >= 1 && outputText().includes('Phase completed: Starting netcoredbg'), 'initial recovery and B command output flush');
        const initialCompletions = completions(); result.initialRecoveryCompletions = initialCompletions;
        assert(initialCompletions.every(s => s.endsWith('attempted=0, removed=0')));
        assert.equal(buildCommands(outputText(), b.source).length, 1);
        const base = b.base;
        assert(within(root, base));
        // The target controller never owns this run directory. Only this separate fixture publisher does.
        const source = fs.mkdtempSync(path.join(path.dirname(b.output), 'run-'));
        const payloadName = 'synthetic-known-terminal-payload';
        const payloadContent = nonce + ':separate-controller-terminal-fixture';
        fs.writeFileSync(path.join(source, payloadName), payloadContent);
        const { createRecovery } = require(path.join(extension.extensionPath, '.netcoredbg/recovery.cjs'));
        const publisher = createRecovery({ baseDirectory: base, isOwned: d => same(d, source),
            removeOutput: () => { throw Error('The fixture publisher must not delete its own receipt'); },
            log: text => trace('fixture-publisher-log', text) });
        assert.equal(await publisher.preserve(source), true); assert(publisher.has(source)); assert(!exists(source));
        const ready = path.join(base, 'terminal-cleanup-v1');
        const entries = fs.readdirSync(ready); assert.equal(entries.length, 1);
        const entryId = entries[0], entry = path.join(ready, entryId), queuedOutput = path.join(entry, 'output');
        assert.equal(fs.readFileSync(path.join(queuedOutput, payloadName), 'utf8'), payloadContent);
        const recordOnlyId = crypto.randomUUID();
        const recordOnly = path.join(base, 'terminal-cleanup-staging-v1', recordOnlyId);
        const unmarked = fs.mkdtempSync(path.join(path.dirname(b.output), 'run-'));
        fs.mkdirSync(recordOnly, { recursive: true }); fs.mkdirSync(source);
        fixture = { schema: 1, kind: 'synthetic-separate-controller-known-terminal-fixture',
            actualOldHost: false, targetRuntimeOwnsOriginal: false, base, source, entryId, entry,
            output: queuedOutput, recordOnlyId, recordOnly,
            receipt: JSON.parse(fs.readFileSync(path.join(entry, 'record.json'), 'utf8')),
            receiptSha256: sha(path.join(entry, 'record.json')),
            payload: { path: path.join(queuedOutput, payloadName), content: payloadContent, sha256: sha(path.join(queuedOutput, payloadName)) },
            sentinels: [
                { path: path.join(source, 'original-replacement-sentinel'), content: nonce + ':replacement' },
                { path: path.join(unmarked, 'unmarked-sentinel'), content: nonce + ':unmarked' },
                { path: path.join(root, 'external-sentinel'), content: nonce + ':external' },
                { path: path.join(recordOnly, 'record.json'), content: JSON.stringify({ version: 1,
                    kind: 'netcoredbg-terminal-output', entryId: recordOnlyId }) + '\n' },
            ] };
        for (const s of fixture.sentinels) fs.writeFileSync(s.path, s.content);
        assert(queueState(true)); preserved(); write('fixture.json', fixture); trace('late-foreign-controller-receipt-published', fixture);
        const gate = new Promise(resolve => { releaseGate = resolve; });
        fs.promises.rm = async function fixtureOnlyRm(directory, options) {
            if (typeof directory !== 'string' || !same(directory, fixture.output)) return originalRm(directory, options);
            rmAttempts++;
            const call = { attempt: rmAttempts, directory, options, unlocked, invokedAtUtc: new Date().toISOString() };
            faultCalls.push(call); write('fault-calls.json', faultCalls); trace('exact-fixture-rm', call);
            assert.deepEqual(options, { recursive: true, force: true, maxRetries: 3, retryDelay: 50 });
            if (!unlocked) {
                if (rmAttempts === 1) await gate;
                call.injectedCode = 'EBUSY'; call.rejectedAtUtc = new Date().toISOString(); write('fault-calls.json', faultCalls);
                throw Object.assign(new Error('Owned command-recovery fixture EBUSY'), { code: 'EBUSY' });
            }
            const value = await originalRm(directory, options);
            call.removedAtUtc = new Date().toISOString(); write('fault-calls.json', faultCalls); return value;
        };
        const a1 = await start('A-gated', 'a.cs', 'initial', 3);
        await until(() => rmAttempts >= 1, 'first exact fixture recovery delete entered');
        assert(!gateReleased); assert.equal(rmAttempts, 1);
        assert(faultCalls[0].invokedAtUtc <= a1.httpReadyAtUtc, 'A must reach HTTP readiness after the fixture delete gate entered');
        assert.equal(completions().length, initialCompletions.length);
        assert(exists(fixture.output)); await keep(b); preserved();
        result.checks.push('Three concurrent A commands reach real HTTP readiness while exact foreign-receipt deletion is blocked; B remains unchanged');
        gateReleased = true; releaseGate();
        await until(() => completions().length >= initialCompletions.length + 1, 'failed background pass completion');
        assert.equal(completions().length, initialCompletions.length + 1);
        assert.equal(completions().at(-1).split(': ')[1], 'scanned=1, attempted=1, removed=0');
        assert.equal(rmAttempts, 1); assert(queueState(true)); preserved();
        assert.equal(sha(path.join(fixture.entry, 'record.json')), fixture.receiptSha256);
        assert.equal(sha(fixture.payload.path), fixture.payload.sha256);
        await until(() => outputText().includes('Owned command-recovery fixture EBUSY'), 'failed pass error output flush');
        write('failed-pass.json', { schema: 1, receiptRetained: true, payloadRetained: true, rmAttempts,
            completions: completions(), b: launchState(b), a: launchState(a1) });
        await stop(a1, true); await keep(b);
        assert.equal(rmAttempts, 1); assert.equal(completions().length, initialCompletions.length + 1);
        result.checks.push('The failed pass remains journaled with no queued rerun; normal A Stop clears only its own output');
        unlocked = true;
        const document = await vscode.workspace.openTextDocument(a1.source);
        const content = document.getText(); assert(content.includes('const string revision = "initial";'));
        const edit = new vscode.WorkspaceEdit();
        edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(content.length)),
            content.replace('const string revision = "initial";', 'const string revision = "command-retry";'));
        assert.equal(await vscode.workspace.applyEdit(edit), true); assert.equal(document.isDirty, true);
        const a2 = await start('A-retry', 'a.cs', 'command-retry', 3);
        assert.equal(a2.dirtyBeforeCommand, true); assert(!same(a2.output, a1.output));
        await until(() => !exists(fixture.entry) && queueState(false) && completions().length >= initialCompletions.length + 2, 'next command background pass removes corrected foreign receipt');
        assert.equal(rmAttempts, 2); assert.equal(completions().length, initialCompletions.length + 2);
        assert.equal(completions().at(-1).split(': ')[1], 'scanned=1, attempted=1, removed=1');
        preserved(); await keep(b);
        result.checks.push('Later dirty three-caller A command removes the foreign receipt in one bounded pass and starts one fresh real Web A in the same app/host');
        await stop(a2, false); await keep(b); await stop(b, false);
        assert.equal(rmAttempts, 2); assert.equal(process.pid, result.extensionHostPid);
        await until(() => buildCommands(outputText(), a1.source).length === 2 && buildCommands(outputText(), b.source).length === 1 &&
            outputText().split(/\r?\n/).filter(s => s.startsWith('Phase completed: Starting netcoredbg')).length === 3,
        'three real commands persisted output log');
        const log = outputLog(), text = outputText();
        const builds = [...buildCommands(text, a1.source), ...buildCommands(text, b.source)];
        for (const l of launches) assert.equal(builds.filter(c => same(c.output, l.output)).length, 1);
        result.outputLog = { path: log, bytes: fs.statSync(log).size, sha256: sha(log),
            buildCommands: builds, recoveryCompletions: completions() };
        result.fixture = fixture; result.faultCalls = faultCalls; result.launches = launches.map(launchState);
        result.final = { sameExtensionHostPid: process.pid, editorPid: ack.editorPid,
            fixtureEntryAbsent: !exists(fixture.entry), queues: { ready: [], staging: [recordOnlyId] },
            allExactDebuggeePidsGone: launches.every(l => !alive(l.pid)), allOutputsGone: launches.every(l => !exists(l.output)),
            sentinels: fixture.sentinels.map(s => ({ ...s, sha256: sha(s.path), unchanged: true })) };
        assert(result.final.allExactDebuggeePidsGone && result.final.allOutputsGone);
        result.checks.push('Final exact A/B Stop releases all captured PIDs, ports and outputs; only deliberate incomplete/unmarked/external/replacement guards remain');
        result.success = true; write('result.json', result);
    } catch (error) {
        result.error = error.stack || String(error); trace('first-failure', result.error);
        // Let a gated callback settle, restore rm, and release every token-matched session.
        releaseGate?.(); fs.promises.rm = originalRm;
        result.failureCleanup = [];
        for (const l of launches) for (const c of l.captured.values()) {
            const action = { label: l.label, sessionId: c.session.id, pid: c.pid };
            try { if (!c.terminated) await vscode.debug.stopDebugging(c.session); action.stopRequested = true; }
            catch (cause) { action.stopError = String(cause); }
            result.failureCleanup.push(action);
        }
        for (const l of launches) if (l.pid && alive(l.pid)) {
            try { const body = await probe(l.origin); assert.equal(body.pid, l.pid); assert.equal(body.nonce, l.nonce);
                await fetch(l.origin + '/shutdown?token=' + encodeURIComponent(l.nonce), { method: 'POST', signal: AbortSignal.timeout(2000) });
            } catch (cause) { result.shutdownError = String(cause); }
        }
        result.launches = launches.map(launchState); result.fixture = fixture; result.faultCalls = faultCalls;
        saveLaunches(); write('result-failure.json', result); throw error;
    } finally {
        fs.promises.rm = originalRm;
        for (const sub of subscriptions.reverse()) sub.dispose();
    }
};
