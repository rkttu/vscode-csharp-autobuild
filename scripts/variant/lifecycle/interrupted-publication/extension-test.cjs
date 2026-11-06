'use strict';

// Candidate normally installed; interrupt a complete staging entry before READY publication.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const vscode = require('vscode');
const COMMAND = 'netcoredbg.debugActiveFile';
const MODULES = ['entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const same = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
const exists = file => { try { fs.lstatSync(file); return true; } catch (e) { if (e.code === 'ENOENT') return false; throw e; } };
const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { if (e.code === 'ESRCH') return false; throw e; } };
function within(root, file) { const r = path.relative(root, path.resolve(file)); return r && !r.startsWith('..') && !path.isAbsolute(r); }
async function until(check, label, limit = 60000) {
    const start = performance.now();
    while (!await check()) { if (performance.now() - start > limit) throw Error(`Safety timeout: ${label}`); await delay(25); }
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
    const phase = read('control-phase.json');
    assert.equal(phase.nonce, expected.interruption.nonce);
    assert(['interrupt', 'recover'].includes(phase.phase));
    const result = { schema: 1, success: false, phase: phase.phase, expected, extensionHostPid: process.pid,
        checks: [], scope: { normallyInstalled: true, explicitSecondLaunch: true, actualExtensionHostExit: true,
            injectedPublicationRename: true, commandApi: true, physicalF5: false, macOS: false, qualification: false } };
    const trace = (event, value) => fs.appendFileSync(path.join(root, `trace-${phase.phase}.jsonl`),
        JSON.stringify({ atUtc: new Date().toISOString(), event, value }) + '\n');
    let launch;
    let target;
    let errorFromEvent;
    let interruptionFailure;
    const subscriptions = [];
    const originalRename = fs.promises.rename;
    const observe = action => { try { action(); } catch (e) { errorFromEvent ||= e; trace('event-error', e.stack); } };
    function capture(session) {
        if (session.configuration?.env?.LIFECYCLE_TOKEN !== launch?.nonce) return;
        assert(!launch.session || launch.session.id === session.id);
        launch.session = session;
        launch.output = session.configuration.__netcoredbgFileAppOutput;
        launch.program = session.configuration.program;
        assert(within(root, launch.output) && same(path.dirname(launch.program), launch.output));
    }
    async function start(label) {
        const source = path.join(root, 'workspace/a.cs');
        launch = { label, source, nonce: crypto.randomUUID(), port: await port() };
        launch.origin = `http://127.0.0.1:${launch.port}`;
        fs.writeFileSync(source.replace(/\.cs$/, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: launch.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }));
        await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(source));
        assert.equal(await vscode.commands.executeCommand(COMMAND), true);
        if (errorFromEvent) throw errorFromEvent;
        await until(() => launch.session, 'captured public-command session');
        if (errorFromEvent) throw errorFromEvent;
        assert(within(root, launch.output) && same(path.dirname(launch.program), launch.output));
        await until(async () => { try { launch.response = await probe(launch.origin); } catch (e) { if (e instanceof assert.AssertionError) throw e; return false; }
            assert.equal(launch.response.nonce, launch.nonce); assert.equal(launch.response.value, 42);
            if (launch.pid) assert.equal(launch.pid, launch.response.pid); launch.pid = launch.response.pid; return true; }, 'real HTTP ready');
        assert(alive(launch.pid)); assert(exists(launch.program));
        if (errorFromEvent) throw errorFromEvent;
        write(`${label}-launch.json`, { ...launch, session: undefined, sessionId: launch.session.id });
        trace('real-launch-ready', { ...launch, session: undefined, sessionId: launch.session.id });
        return launch;
    }
    async function stop() {
        await vscode.debug.stopDebugging(launch.session);
        await until(() => launch.terminated, 'matching editor termination');
        await until(() => !alive(launch.pid), 'exact debuggee PID exit');
        await until(() => bindable(launch.port), 'exact Web port release');
    }
    function preserveSentinels(marker) {
        for (const item of marker.sentinels) assert.equal(fs.readFileSync(item.path, 'utf8'), item.content);
    }
    try {
        subscriptions.push(vscode.debug.onDidStartDebugSession(s => observe(() => capture(s))));
        subscriptions.push(vscode.debug.onDidTerminateDebugSession(s => observe(() => {
            if (s.id === launch?.session?.id) { launch.terminated = true; trace('matching-editor-termination', { id: s.id, pid: launch.pid }); }
        })));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr', { createDebugAdapterTracker(s) {
            if (s.configuration?.env?.LIFECYCLE_TOKEN !== launch?.nonce) return;
            observe(() => capture(s));
            return { onDidSendMessage(m) { observe(() => {
                if (m.event === 'process' && m.body?.isLocalProcess) {
                    assert(Number.isSafeInteger(m.body.systemProcessId) && m.body.systemProcessId > 0); launch.pid = m.body.systemProcessId;
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
        result.installedExtension = { path: extension.extensionPath, metadata: metadata.__metadata, build: metadata.netcoredbgBuild };
        await extension.activate();
        assert((await vscode.commands.getCommands(true)).includes(COMMAND));
        result.checks.push('Exact normally installed native candidate and modules activated');
        if (phase.phase === 'interrupt') {
            assert(!exists(path.join(root, 'crash-ready.json')));
            target = await start('first');
            assert(within(root, target.output));
            const base = path.dirname(path.dirname(target.output));
            const unmarked = fs.mkdtempSync(path.join(path.dirname(target.output), 'run-'));
            const stagingParent = path.join(base, 'terminal-cleanup-staging-v1');
            const recordOnlyId = crypto.randomUUID();
            const recordOnly = path.join(stagingParent, recordOnlyId);
            const invalidId = crypto.randomUUID();
            const invalidEntry = path.join(stagingParent, invalidId);
            fs.mkdirSync(recordOnly, { recursive: true });
            fs.mkdirSync(path.join(invalidEntry, 'output'), { recursive: true });
            const sentinels = [
                { path: path.join(unmarked, 'unmarked-sentinel'), content: expected.interruption.nonce + ':unmarked' },
                { path: path.join(root, 'external-sentinel'), content: expected.interruption.nonce + ':external' },
                { path: path.join(recordOnly, 'record.json'), content: JSON.stringify({
                    version: 1, kind: 'netcoredbg-terminal-output', entryId: recordOnlyId,
                }) + '\n' },
                { path: path.join(invalidEntry, 'record.json'), content: JSON.stringify({
                    version: 99, kind: 'netcoredbg-terminal-output', entryId: invalidId,
                }) + '\n' },
                { path: path.join(invalidEntry, 'output', 'invalid-stage-sentinel'), content: expected.interruption.nonce + ':invalid-stage' },
            ];
            for (const item of sentinels) fs.writeFileSync(item.path, item.content);
            let intercepted = false;
            fs.promises.rename = async function interruptedPublication(source, destination) {
                const exact = typeof source === 'string' && typeof destination === 'string' &&
                    within(base, source) && within(base, destination) &&
                    same(path.dirname(source), stagingParent) &&
                    same(path.dirname(destination), path.join(base, 'terminal-cleanup-v1')) &&
                    path.basename(source) === path.basename(destination);
                if (!exact || intercepted) return originalRename(source, destination);
                intercepted = true;
                try {
                assert(launch.terminated, 'Publication must follow matching editor termination');
                await until(() => !alive(target.pid), 'debuggee exit before controlled interruption');
                await until(() => bindable(target.port), 'port release before controlled interruption');
                const entry = source;
                const directory = path.join(entry, 'output');
                const recordFile = path.join(entry, 'record.json');
                const receipt = JSON.parse(fs.readFileSync(recordFile, 'utf8'));
                assert.equal(receipt.version, 1); assert.equal(receipt.kind, 'netcoredbg-terminal-output');
                assert.equal(receipt.entryId, path.basename(entry));
                assert.deepEqual(fs.readdirSync(entry).sort(), ['output', 'record.json']);
                assert(same(path.dirname(entry), stagingParent));
                assert(!exists(target.output), 'The original output must already have moved into staging');
                assert(!exists(destination), 'Interruption must precede the STAGING-to-READY rename');
                assert(exists(path.join(directory, 'FileApp.dll')));
                assert(exists(path.join(directory, 'FileApp.pdb')));
                fs.writeFileSync(path.join(directory, 'interrupted-owned-sentinel'), expected.interruption.nonce);
                preserveSentinels({ sentinels });
                const marker = { schema: 1, nonce: expected.interruption.nonce, hostPid: process.pid,
                    expectedExitCode: expected.interruption.expectedHostExitCode, entry, output: directory,
                    boundary: 'complete-staging-before-ready-rename', readyEntry: destination,
                    sourceMoved: !exists(target.output), readyAbsent: !exists(destination), publicationRenameInvoked: false,
                    receipt, receiptSha256: sha(recordFile),
                    payload: ['FileApp.dll', 'FileApp.pdb', 'interrupted-owned-sentinel'].map(name => ({
                        path: path.join(directory, name), sha256: sha(path.join(directory, name)),
                    })),
                    originalOutput: target.output, debuggeePid: target.pid, debuggeePidGone: !alive(target.pid),
                    port: target.port, portReusable: await bindable(target.port), sentinels,
                    preservedStagingEntries: [recordOnly, invalidEntry],
                    installed: result.installedExtension, installedModules: result.installedModules };
                trace('complete-staging-before-ready-publication', marker);
                if (errorFromEvent) throw errorFromEvent;
                write('crash-ready.json', marker);
                await until(() => exists(path.join(root, 'crash-ack.json')), 'external exact host ownership acknowledgement', 30000);
                const ack = read('crash-ack.json'); assert.equal(ack.nonce, marker.nonce); assert.equal(ack.pid, process.pid);
                trace('intentional-extension-host-exit', { pid: process.pid, code: marker.expectedExitCode });
                process.exit(marker.expectedExitCode);
                await new Promise(() => {});
                } catch (error) {
                    interruptionFailure = error;
                    trace('interruption-hook-failure', error.stack || String(error));
                    write('interruption-hook-failure.json', { schema: 1, error: error.stack || String(error) });
                    throw error;
                }
            };
            await stop();
            await until(() => interruptionFailure || exists(path.join(root, 'crash-ready.json')), 'complete staging publication interruption barrier');
            if (interruptionFailure) throw interruptionFailure;
            await new Promise(() => {});
        } else {
            const marker = read('crash-ready.json');
            assert.equal(marker.nonce, expected.interruption.nonce);
            assert.notEqual(process.pid, marker.hostPid, 'Recovery must run in another actual extension host');
            assert.deepEqual(marker.installedModules, result.installedModules);
            assert.equal(marker.boundary, 'complete-staging-before-ready-rename');
            assert(marker.sourceMoved && marker.readyAbsent && marker.publicationRenameInvoked === false);
            await until(() => !exists(marker.entry) && !exists(marker.readyEntry), 'new activation publishing and recovering complete staging output');
            preserveSentinels(marker);
            const replacement = read('replacement.json');
            assert.equal(fs.readFileSync(replacement.path, 'utf8'), replacement.content);
            result.firstHost = marker;
            result.recoveryObservedAtUtc = new Date().toISOString();
            result.checks.push('New extension host publishes and removes the complete staging entry while preserving unmarked, incomplete, invalid and replacement paths');
            const retry = await start('retry');
            assert(!same(retry.output, marker.originalOutput));
            assert(!same(retry.output, marker.output));
            await stop();
            const ready = path.join(path.dirname(path.dirname(retry.output)), 'terminal-cleanup-v1');
            const staging = path.join(path.dirname(path.dirname(retry.output)), 'terminal-cleanup-staging-v1');
            const expectedStages = marker.preservedStagingEntries.map(entry => path.basename(entry)).sort();
            await until(() => {
                if (exists(retry.output)) return false;
                const stages = fs.readdirSync(staging).sort();
                if (stages.length !== expectedStages.length || stages.some((name, index) => name !== expectedStages[index])) return false;
                // Check READY after STAGING so an atomic publication between these reads is observed.
                return (!exists(ready) || fs.readdirSync(ready).length === 0) && !exists(retry.output);
            }, 'retry original output and both terminal queues cleared except deliberate staging guards');
            preserveSentinels(marker); assert.equal(fs.readFileSync(replacement.path, 'utf8'), replacement.content);
            assert(!alive(marker.debuggeePid));
            if (errorFromEvent) throw errorFromEvent;
            result.checks.push('Same profile public-command retry builds and starts a real Web session and releases exact PID/port/output');
            result.retry = { ...retry, session: undefined, sessionId: retry.session.id };
            result.success = true;
            write('result.json', result);
        }
    } catch (error) {
        result.error = error.stack || String(error); trace('first-failure', result.error);
        fs.promises.rename = originalRename;
        if (launch?.session && !launch.terminated) {
            try { await vscode.debug.stopDebugging(launch.session); } catch (cause) { result.stopError = String(cause); }
        }
        if (launch?.pid && alive(launch.pid)) {
            try { const body = await probe(launch.origin); assert.equal(body.pid, launch.pid); assert.equal(body.nonce, launch.nonce);
                await fetch(launch.origin + '/shutdown?token=' + encodeURIComponent(launch.nonce), { method: 'POST', signal: AbortSignal.timeout(2000) });
            } catch (cause) { result.shutdownError = String(cause); }
        }
        write(`result-${phase.phase}-failure.json`, result);
        throw error;
    } finally {
        fs.promises.rename = originalRename;
        for (const sub of subscriptions.reverse()) sub.dispose();
    }
};
