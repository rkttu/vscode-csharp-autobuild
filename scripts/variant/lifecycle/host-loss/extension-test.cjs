'use strict';
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
const exists = file => { try { fs.lstatSync(file); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; } };
const same = (left, right) => path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase();
function within(root, file) { const relative = path.relative(root, path.resolve(file)); return relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative); }
function alive(pid) { assert(Number.isSafeInteger(pid) && pid > 0); try { process.kill(pid, 0); return true; } catch (error) { if (error.code === 'ESRCH') return false; throw error; } }
async function availablePort() { const server = net.createServer(); await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); }); const port = server.address().port; await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve())); return port; }
async function bindable(port) { const server = net.createServer(); return new Promise((resolve, reject) => { server.once('error', error => error.code === 'EADDRINUSE' ? resolve(false) : reject(error)); server.listen(port, '127.0.0.1', () => server.close(error => error ? reject(error) : resolve(true))); }); }
async function probe(origin) { const response = await fetch(origin + '/probe', { signal: AbortSignal.timeout(2000) }); assert.equal(response.status, 200); return response.json(); }

exports.run = async function run(context) {
    const root = path.resolve(process.env.NETCOREDBG_LIFECYCLE_ROOT || '');
    assert(process.env.NETCOREDBG_LIFECYCLE_ROOT && path.isAbsolute(process.env.NETCOREDBG_LIFECYCLE_ROOT));
    const read = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8').replace(/^\uFEFF/, ''));
    const expected = read('expected.json');
    assert.equal(expected.scenario, 'abrupt-extension-host-loss');
    const previous = exists(path.join(root, 'phase.json')) ? read('phase.json') : undefined;
    const phase = previous ? 2 : 1;
    const traceFile = path.join(root, `trace-host-${phase}.jsonl`);
    fs.writeFileSync(traceFile, '', { flag: 'wx' });
    const trace = (event, detail) => fs.appendFileSync(traceFile, JSON.stringify({ atUtc: new Date().toISOString(), phase, host: process.pid, event, detail }) + '\n');
    function write(name, value, once = false) {
        const file = path.join(root, name);
        assert(within(root, file));
        if (once) assert(!exists(file));
        const temporary = file + '.' + process.pid + '.' + crypto.randomUUID() + '.tmp';
        fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
        fs.renameSync(temporary, file);
    }
    const launches = [];
    const byToken = new Map();
    const subscriptions = [];
    let observerError;
    const serialized = launch => ({ ...launch, session: undefined, captured: undefined,
        commandOperation: undefined,
        sessionId: launch.session?.id || launch.sessionId,
        capturedSessions: launch.captured ? [...launch.captured.values()].map(item => ({ ...item, session: undefined, sessionId: item.session.id })) : launch.capturedSessions });
    const save = () => write('owned-launches.json', { schema: 1, nonce: expected.hostLoss.nonce,
        launches: [...(previous ? [previous.launch] : []), ...launches.map(serialized)] });
    const result = { schema: 1, success: false, mechanicsCompleted: false, expected, phase, host: process.pid,
        scope: { installedCandidate: true, normallyInstalledDriver: true, extensionDevelopmentPath: false,
            extensionTestsPath: false, actualAbruptHostKill: true, activeBuildAtFault: false,
            injectedTargetRuntime: false, commandApi: true, unrelatedEditorB: false, physicalF5: false,
            macOS: false, localOnly: true, published: false, qualification: false } };
    async function until(predicate, label, limit = 90000, observeErrors = true) {
        const began = performance.now();
        while (true) {
            if (observeErrors && observerError) throw observerError;
            if (await predicate()) return;
            if (performance.now() - began >= limit) throw new Error('Safety timeout: ' + label);
            await delay(25);
        }
    }
    async function bounded(operation, label, milliseconds) {
        let timer;
        try { return await Promise.race([operation, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Safety timeout: ' + label)), milliseconds); })]); }
        finally { clearTimeout(timer); }
    }
    function observe(action) { try { action(); } catch (error) { observerError ||= error; trace('observer-error', error.stack || String(error)); save(); } }
    function capture(session) {
        const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN);
        if (!launch) return;
        if (!launch.captured.has(session.id)) launch.captured.set(session.id, { session, program: session.configuration.program, output: session.configuration.__netcoredbgFileAppOutput });
        launch.session ||= session;
        save();
        assert.equal(launch.session.id, session.id);
        assert.equal(session.type, 'coreclr');
        launch.program = session.configuration.program;
        launch.output = session.configuration.__netcoredbgFileAppOutput;
        assert(within(root, launch.output) && within(launch.output, launch.program));
        assert(same(path.dirname(launch.program), launch.output));
        launch.base = path.dirname(path.dirname(launch.output));
        save();
    }
    function channels() {
        const files = [];
        function visit(directory) { if (!exists(directory)) return; for (const entry of fs.readdirSync(directory, { withFileTypes: true })) { const file = path.join(directory, entry.name); if (entry.isDirectory()) visit(file); else if (entry.isFile() && entry.name.endsWith('C# File Debugging.log')) files.push(file); } }
        visit(path.join(root, 'profile/logs'));
        return files;
    }
    function queueEmpty(base) { return ['terminal-cleanup-v1', 'terminal-cleanup-staging-v1'].every(name => { const directory = path.join(base, name); return !exists(directory) || fs.readdirSync(directory).length === 0; }); }
    function proof(file) { const value = { path: file, exists: exists(file) }; if (value.exists) { const stat = fs.lstatSync(file); assert(stat.isFile() && !stat.isSymbolicLink()); value.size = stat.size; value.sha256 = sha(file); } return value; }
    function preserves(files) { return files.every(file => exists(file.path) && sha(file.path) === file.sha256); }
    async function snapshot(launch, adapterPid) {
        const item = { atUtc: new Date().toISOString(), pid: launch.pid, pidRespondsToSignalZero: alive(launch.pid),
            port: launch.port, portBindable: await bindable(launch.port), output: launch.output,
            outputExists: exists(launch.output), programExists: exists(launch.program), terminalQueuesEmpty: queueEmpty(launch.base) };
        if (adapterPid) { item.adapterPid = adapterPid; item.adapterPidRespondsToSignalZero = alive(adapterPid); }
        try { item.http = await probe(launch.origin); assert.deepEqual(item.http, launch.response); item.httpOwned = true; }
        catch (error) { if (error instanceof assert.AssertionError) throw error; item.httpOwned = false; item.httpError = String(error); }
        if (launch.preservedFiles) { item.files = launch.preservedFiles.map(file => proof(file.path)); item.unknownFilesPreserved = preserves(launch.preservedFiles); }
        return item;
    }
    async function start(label, revision, calls, document) {
        const launch = { label, revision, source: path.join(root, 'workspace/a.cs'), nonce: crypto.randomUUID(),
            port: await availablePort(), captured: new Map(), dap: [], requests: [] };
        launch.origin = 'http://127.0.0.1:' + launch.port;
        launches.push(launch); byToken.set(launch.nonce, launch); save();
        fs.writeFileSync(launch.source.replace(/\.cs$/, '.run.json'), JSON.stringify({ profiles: { LifecycleHttp: {
            commandName: 'Project', applicationUrl: launch.origin, launchBrowser: false,
            environmentVariables: { LIFECYCLE_TOKEN: launch.nonce, ASPNETCORE_ENVIRONMENT: 'Development' },
        } } }, null, 2) + '\n');
        document ||= await vscode.workspace.openTextDocument(launch.source);
        await vscode.window.showTextDocument(document);
        trace('public-command-start', { label, command: COMMAND, callers: calls, dirty: document.isDirty });
        launch.commandPending = true;
        launch.commandOperation = Promise.allSettled(Array.from({ length: calls }, () => vscode.commands.executeCommand(COMMAND))).then(outcomes => {
            launch.commandPending = false; launch.commandReturnedAtUtc = new Date().toISOString(); save(); return outcomes;
        });
        launch.commandOperation.catch(() => {});
        const outcomes = await bounded(launch.commandOperation, label + ' public command results', 90000);
        const rejected = outcomes.find(outcome => outcome.status === 'rejected'); if (rejected) throw rejected.reason;
        launch.commandResults = outcomes.map(outcome => outcome.value); assert.deepEqual(launch.commandResults, Array(calls).fill(true));
        assert.equal(document.isDirty, false); assert.equal(fs.readFileSync(launch.source, 'utf8'), document.getText());
        await until(() => launch.started && launch.session, label + ' matching real session'); assert.equal(launch.captured.size, 1);
        await until(async () => {
            let body; try { body = await probe(launch.origin); } catch (error) { if (error instanceof assert.AssertionError) throw error; return false; }
            assert.equal(body.nonce, launch.nonce); assert.equal(body.revision, revision); assert.equal(body.value, 42);
            assert(Number.isSafeInteger(body.pid) && body.pid > 0); if (launch.pid) assert.equal(body.pid, launch.pid);
            launch.pid = body.pid; launch.response = body; assert(alive(launch.pid));
            launch.captured.get(launch.session.id).pid = launch.pid; save(); return true;
        }, label + ' owned HTTP readiness');
        const processEvent = launch.dap.find(message => message.event === 'process' && message.body?.isLocalProcess === true);
        assert(processEvent, 'The actual native adapter must report this local debuggee PID');
        assert.equal(processEvent.body.systemProcessId, launch.pid);
        launch.dapProcessEvent = processEvent;
        launch.sourceProof = proof(launch.source); launch.profileProof = proof(launch.source.replace(/\.cs$/, '.run.json'));
        trace('real-web-ready', serialized(launch)); return launch;
    }
    async function stop(launch) {
        launch.testStopRequestedAtUtc = new Date().toISOString(); trace('exact-stop-request', { sessionId: launch.session.id, pid: launch.pid });
        await vscode.debug.stopDebugging(launch.session);
        await until(() => launch.terminated, 'matching retry termination'); await until(() => !alive(launch.pid), 'retry PID exit');
        await until(() => bindable(launch.port), 'retry port release'); await until(() => !exists(launch.output) && queueEmpty(launch.base), 'retry output/queue release');
        launch.resourcesReleasedAtUtc = new Date().toISOString(); save(); trace('exact-retry-cleanup', serialized(launch));
    }
    try {
        assert.equal(context.extensionMode, vscode.ExtensionMode.Production);
        assert.equal(context.extension.id, expected.testDriver.id);
        assert(within(path.join(root, 'extensions'), context.extension.extensionPath));
        const driverMetadata = JSON.parse(fs.readFileSync(path.join(context.extension.extensionPath, 'package.json'), 'utf8'));
        assert(driverMetadata.__metadata); assert.equal(driverMetadata.version, expected.testDriver.version);
        for (const name of ['driver.cjs', 'extension-test.cjs']) assert.equal(sha(path.join(context.extension.extensionPath, name)), expected.testDriver.payload['extension/' + name]);
        const preparedPackage = path.join(root, 'driver/package.json'); assert.equal(sha(preparedPackage), expected.testDriver.payload['extension/package.json']);
        const { __metadata: installerMetadata, ...installedManifest } = driverMetadata;
        assert.deepEqual(installedManifest, JSON.parse(fs.readFileSync(preparedPackage, 'utf8')));
        result.driver = { path: context.extension.extensionPath, extensionMode: context.extensionMode, metadata: installerMetadata,
            packageProof: proof(path.join(context.extension.extensionPath, 'package.json')), manifest: installedManifest };
        subscriptions.push(vscode.debug.onDidStartDebugSession(session => observe(() => { capture(session); const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN); if (launch) launch.started = true; trace('editor-start', { sessionId: session.id, token: session.configuration?.env?.LIFECYCLE_TOKEN }); })));
        subscriptions.push(vscode.debug.onDidTerminateDebugSession(session => observe(() => { const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN); const captured = launch?.captured.get(session.id); if (captured) { captured.terminated = true; launch.terminated = true; trace('editor-terminate', { sessionId: session.id, outputExists: exists(launch.output) }); save(); } })));
        subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('coreclr', { createDebugAdapterTracker(session) {
            const launch = byToken.get(session.configuration?.env?.LIFECYCLE_TOKEN); if (!launch) return undefined; observe(() => capture(session));
            return { onWillReceiveMessage(message) { observe(() => { launch.requests.push(message); trace('dap-send', { sessionId: session.id, message }); }); },
                onDidSendMessage(message) { observe(() => { launch.dap.push(message); if (message.event === 'process' && message.body?.isLocalProcess === true) { const pid = message.body.systemProcessId; assert(Number.isSafeInteger(pid) && pid > 0); if (launch.pid) assert.equal(launch.pid, pid); launch.pid = pid; launch.captured.get(session.id).pid = pid; save(); } trace('dap-receive', { sessionId: session.id, message }); }); },
                onExit(code, signal) { trace('adapter-exit', { sessionId: session.id, code, signal }); } };
        } }));
        const candidate = vscode.extensions.getExtension(expected.extensionId), dependency = vscode.extensions.getExtension('ms-dotnettools.vscode-dotnet-runtime');
        assert(candidate && dependency && within(path.join(root, 'extensions'), candidate.extensionPath) && within(path.join(root, 'extensions'), dependency.extensionPath));
        const metadata = JSON.parse(fs.readFileSync(path.join(candidate.extensionPath, 'package.json'), 'utf8'));
        assert(metadata.__metadata && metadata.netcoredbgBuild.localCandidate); assert.equal(metadata.netcoredbgBuild.lifecycleBuildId, expected.candidate.buildId);
        assert.equal(`${process.platform}-${process.arch}`, expected.candidate.target); assert.equal(dependency.packageJSON.version, expected.dependency.version);
        result.installedModules = {}; for (const name of MODULES) { const actual = sha(path.join(candidate.extensionPath, '.netcoredbg', name)); assert.equal(actual, expected.candidate.ownedModules[name]); result.installedModules[name] = actual; }
        result.installed = { path: candidate.extensionPath, metadata: metadata.__metadata, build: metadata.netcoredbgBuild, dependencyPath: dependency.extensionPath };
        if (previous) { result.candidateAlreadyActiveBeforeExplicitActivation = candidate.isActive; result.immediateOldObservationBeforeExplicitActivation = await snapshot(previous.launch); }
        write(`host-${phase}.json`, { schema: 1, nonce: expected.hostLoss.nonce, phase, extensionHostPid: process.pid,
            editorApiVersion: vscode.version, platform: `${process.platform}-${process.arch}`,
            driver: result.driver, installed: result.installed, installedModules: result.installedModules }, true);
        await until(() => exists(path.join(root, `ack-${phase}.json`)), 'verified isolated host acknowledgement', 30000);
        const ack = read(`ack-${phase}.json`); assert.equal(ack.nonce, expected.hostLoss.nonce); assert.equal(ack.extensionHostPid, process.pid); result.editorPid = ack.editorPid;
        await candidate.activate(); assert((await vscode.commands.getCommands(true)).includes(COMMAND));
        if (!previous) {
            const launch = await start('A-before-abrupt-host-loss', 'initial', 1);
            let firstLog; await until(() => { const files = channels(); assert(files.length <= 1); firstLog = files[0]; return firstLog && /Terminal output recovery: scanned=\d+, attempted=\d+, removed=\d+/.test(fs.readFileSync(firstLog, 'utf8')); }, 'first-host recovery completion');
            const sentinel = path.join(launch.output, 'host-loss-owned-sentinel.txt'); fs.writeFileSync(sentinel, expected.hostLoss.nonce, { flag: 'wx' });
            const guardDirectory = fs.mkdtempSync(path.join(path.dirname(launch.output), 'run-')); const guard = path.join(guardDirectory, 'unmarked-host-loss-guard.txt'); fs.writeFileSync(guard, expected.hostLoss.nonce, { flag: 'wx' });
            launch.preservedFiles = [launch.program, path.join(launch.output, 'FileApp.pdb'), sentinel, guard].map(proof);
            assert(launch.preservedFiles.every(file => file.exists && file.size > 0));
            const before = await snapshot(launch); assert(before.pidRespondsToSignalZero && before.httpOwned && before.outputExists && before.terminalQueuesEmpty && !before.portBindable);
            assert(!launch.requests.some(message => ['disconnect', 'terminate'].includes(message.command)));
            const adapterPath = path.join(candidate.extensionPath, expected.hostLoss.adapterRelativePath); assert.equal(sha(adapterPath), expected.hostLoss.adapterSha256);
            const checkpoint = { schema: 1, nonce: expected.hostLoss.nonce, stage: 'armed', firstHost: process.pid, editorPid: ack.editorPid,
                launch: serialized(launch), before, firstHostLogPaths: [firstLog], driver: result.driver, installedModules: result.installedModules,
                firstHostLogs: channels().map(file => { const text = fs.readFileSync(file, 'utf8'); return { path: file,
                    prefixCharacters: text.length, prefixSha256: crypto.createHash('sha256').update(text).digest('hex') }; }),
                adapter: { path: adapterPath, sha256: expected.hostLoss.adapterSha256 } };
            write('phase.json', checkpoint, true); trace('armed-for-exact-host-kill', checkpoint);
            write('fault-ready.json', { schema: 1, nonce: expected.hostLoss.nonce, extensionHostPid: process.pid, editorPid: ack.editorPid,
                phaseSha256: sha(path.join(root, 'phase.json')), launch: checkpoint.launch, adapter: checkpoint.adapter }, true);
            // No deactivation, Stop or Reload is requested. Only the external
            // retained OS handle fault can end this host's pending phase.
            await new Promise(() => {});
        } else {
            assert.equal(previous.nonce, expected.hostLoss.nonce); assert.notEqual(previous.firstHost, process.pid); assert.equal(previous.editorPid, ack.editorPid);
            result.firstHost = previous.firstHost; result.firstLaunch = previous.launch;
            await until(() => exists(path.join(root, 'host-kill-receipt.json')), 'exact host fault receipt', 30000);
            const receipt = read('host-kill-receipt.json'); assert.equal(receipt.nonce, expected.hostLoss.nonce); assert.equal(receipt.success, true); assert.equal(receipt.killedProcessId, previous.firstHost);
            result.killReceiptProof = proof(path.join(root, 'host-kill-receipt.json'));
            let newLog, recoverySlice;
            await until(() => {
                const candidates = [];
                for (const file of channels()) {
                    const text = fs.readFileSync(file, 'utf8'), old = previous.firstHostLogs.find(item => same(item.path, file));
                    const offset = old?.prefixCharacters || 0;
                    if (old) assert.equal(crypto.createHash('sha256').update(text.slice(0, offset)).digest('hex'), old.prefixSha256, 'An existing logger must retain its exact first-host prefix');
                    const tail = text.slice(offset);
                    if (/Terminal output recovery: scanned=\d+, attempted=\d+, removed=\d+/.test(tail)) candidates.push({ file,
                        slice: { kind: old ? 'verified-appended-log' : 'new-log', prefixCharacters: offset,
                            prefixSha256: old?.prefixSha256 || crypto.createHash('sha256').update('').digest('hex'),
                            tailCharacters: tail.length, tailSha256: crypto.createHash('sha256').update(tail).digest('hex'), text: tail } });
                }
                assert(candidates.length <= 1, 'Replacement-host recovery must have one unambiguous new or verified appended log slice');
                if (!candidates.length) return false;
                newLog = candidates[0].file; recoverySlice = candidates[0].slice; return true;
            }, 'replacement-host initial recovery in a verified log slice');
            result.newHostInitialRecoveryLog = { ...proof(newLog), ...recoverySlice };
            const adapterPid = receipt.identities.adapter.processId;
            result.afterInitialRecovery = await snapshot(previous.launch, adapterPid);
            assert(preserves(previous.launch.preservedFiles), 'Unknown original output and unmarked guard must be preserved');
            assert.equal(sha(previous.launch.source), previous.launch.sourceProof.sha256);
            const prefix = fs.readFileSync(newLog, 'utf8');
            const document = await vscode.workspace.openTextDocument(previous.launch.source); const text = document.getText(); assert(text.includes('const string revision = "initial";'));
            const edit = new vscode.WorkspaceEdit(); edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(text.length)), text.replace('const string revision = "initial";', 'const string revision = "host-loss-retry";'));
            assert.equal(await vscode.workspace.applyEdit(edit), true); assert.equal(document.isDirty, true);
            const retry = await start('A-after-abrupt-host-loss', 'host-loss-retry', 3, document); assert.notEqual(retry.output, previous.launch.output); assert.notEqual(retry.nonce, previous.launch.nonce); assert.notEqual(retry.session.id, previous.launch.sessionId);
            let tail; await until(() => { const current = fs.readFileSync(newLog, 'utf8'); assert.equal(current.slice(0, prefix.length), prefix); tail = current.slice(prefix.length); return tail.includes('Phase completed: Starting netcoredbg'); }, 'replacement host retry output');
            const commands = tail.split(/\r?\n/).filter(line => line.startsWith('dotnet "build" ')).map(line => [...line.slice(7).matchAll(/"(?:\\.|[^"\\])*"/g)].map(match => JSON.parse(match[0])));
            assert.equal(commands.length, 1); assert(same(commands[0][1], retry.source)); assert(same(commands[0][commands[0].indexOf('--output') + 1], retry.output));
            assert.equal(tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Building file-based app')).length, 1);
            assert.equal(tail.split(/\r?\n/).filter(line => line.startsWith('Phase completed: Starting netcoredbg')).length, 1);
            result.retryLog = { path: newLog, prefixCharacters: prefix.length, prefixSha256: crypto.createHash('sha256').update(prefix).digest('hex'), tailCharacters: tail.length, tailSha256: crypto.createHash('sha256').update(tail).digest('hex'), commands };
            await stop(retry); result.retry = serialized(retry); result.finalOldObservation = await snapshot(previous.launch, adapterPid);
            assert(preserves(previous.launch.preservedFiles)); result.unknownOutputAndGuardPreserved = true;
            result.mechanicsCompleted = true;
            result.nativeResourcesReleased = !result.finalOldObservation.pidRespondsToSignalZero && !result.finalOldObservation.adapterPidRespondsToSignalZero && !result.finalOldObservation.httpOwned && result.finalOldObservation.portBindable;
            result.success = result.nativeResourcesReleased;
            trace('observational-control-completed', result); write('result.json', result, true);
            if (!result.success) throw new Error('Original native resources remain after abrupt host loss; first observations precede fixture cleanup');
        }
    } catch (error) {
        result.firstFailure ||= error.stack || String(error); trace('first-failure', result.firstFailure); write(`phase-${phase}-failure.json`, result, true); throw error;
    } finally {
        // This block cannot run in the force-killed first host. Never reconstruct
        // an old DebugSession in its replacement, and never delete unknown output.
        if (result.firstFailure) for (const launch of launches) if (launch.commandOperation) {
            try { await bounded(launch.commandOperation, 'failure public-command drain', 15000); }
            catch (error) { trace('failure-command-drain-error', String(error)); }
        }
        for (const launch of launches) for (const captured of launch.captured.values()) if (!captured.terminated) {
            try { trace('failure-exact-stop', { sessionId: captured.session.id }); await bounded(vscode.debug.stopDebugging(captured.session), 'failure exact-session Stop', 5000); } catch (error) { trace('failure-stop-error', String(error)); }
        }
        if (result.firstFailure) for (const launch of [...(previous ? [previous.launch] : []), ...launches]) {
            try { const body = await probe(launch.origin); assert.equal(body.pid, launch.pid); assert.equal(body.nonce, launch.nonce);
                await fetch(launch.origin + '/shutdown?token=' + encodeURIComponent(launch.nonce), { method: 'POST', signal: AbortSignal.timeout(2000) });
                trace('failure-fixture-http-shutdown', { pid: body.pid, nonce: body.nonce });
            } catch (error) { trace('failure-http-shutdown-unavailable', String(error)); }
        }
        for (const subscription of subscriptions) subscription.dispose(); save();
    }
};
