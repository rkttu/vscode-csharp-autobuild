'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const root = __dirname;
const trace = path.join(root, 'editor.dap.jsonl');
const events = [];
const listeners = new Set();
const output = [];
const COMMAND = 'netcoredbg.debugActiveFile';
const invalidSource = 'int answer = 40;\nanswer += 2;\nConsole.WriteLine($"ANSWER={answer}");\n[DllImport("unused-library")]\nstatic extern void NativeCall();\n';
const fixedSource = 'using System.Runtime.InteropServices;\n' + invalidSource;
const webSource = "#:sdk Microsoft.NET.Sdk.Web\nvar builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();\napp.MapGet(\"/probe\", () =>\n{\n    int answer = 40;\n    answer += 2;\n    return Results.Json(new { answer, marker = Environment.GetEnvironmentVariable(\"FBA_WEB_MARKER\"), launchProfile = Environment.GetEnvironmentVariable(\"DOTNET_LAUNCH_PROFILE\"), args });\n});\napp.Run();\n";
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function receive(message) {
    fs.appendFileSync(trace, JSON.stringify({ direction: 'receive', message }) + '\n');
    if (message.event === 'output') output.push(message.body?.output || '');
    if (message.type === 'event') events.push(message);
    for (const listener of [...listeners]) listener();
}

async function event(name, predicate = () => true, timeout = 60000) {
    const deadline = Date.now() + timeout;
    for (;;) {
        const index = events.findIndex(item => item.event === name && predicate(item.body));
        if (index >= 0) return events.splice(index, 1)[0].body;
        const remaining = deadline - Date.now();
        if (remaining <= 0) throw new Error(`Timed out waiting for ${name}`);
        await new Promise((resolve, reject) => {
            let timer;
            const wake = () => { clearTimeout(timer); listeners.delete(wake); resolve(); };
            listeners.add(wake);
            timer = setTimeout(() => { listeners.delete(wake); reject(new Error(`Timed out waiting for ${name}`)); }, remaining);
        });
    }
}

async function bounded(promise, message, timeout = 30000) {
    let timer;
    try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), timeout); })]); }
    finally { clearTimeout(timer); }
}

async function replaceSource(document, text) {
    const edit = new vscode.WorkspaceEdit();
    edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)), text);
    assert.equal(await vscode.workspace.applyEdit(edit), true);
    assert.equal(await document.save(), true);
    await vscode.window.showTextDocument(document);
    assert.equal(document.getText(), text);
}

function snapshotDiagnostics(uri) {
    return vscode.languages.getDiagnostics(uri).map(item => ({ message: item.message, code: item.code, severity: item.severity }));
}

async function snapshotHover(document, word) {
    const index = document.getText().indexOf(word);
    if (index < 0) return [];
    try {
        const hovers = await bounded(vscode.commands.executeCommand('vscode.executeHoverProvider', document.uri, document.positionAt(index + 1)), 'Hover timed out', 5000);
        return (hovers || []).flatMap(item => item.contents).map(item => typeof item === 'string' ? item : item.value);
    } catch (error) { return [{ error: String(error) }]; }
}

function outputLogs(directory, matches = []) {
    if (!fs.existsSync(directory)) return matches;
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const full = path.join(directory, entry.name);
        if (entry.isDirectory()) outputLogs(full, matches);
        else if (/C# File Debugging\.log$/.test(entry.name)) matches.push(full);
    }
    return matches;
}

async function compileFailureEvidence() {
    for (let attempt = 0; attempt < 50; attempt++) {
        for (const file of outputLogs(path.join(root, 'portable-data/user-data/logs'))) {
            const text = fs.readFileSync(file, 'utf8');
            if (/error CS0246.*DllImport/.test(text)) {
                fs.writeFileSync(path.join(root, 'compile-failure-output.txt'), text);
                return { code: 'CS0246', symbol: 'DllImport', capturedOutput: 'compile-failure-output.txt' };
            }
        }
        await delay(100);
    }
    throw new Error('Expected actual compiler CS0246/DllImport error in the isolated C# File Debugging output log');
}

async function notificationSnapshot() {
    // Observe only this test editor's own renderer; never attach to a user instance.
    const port = Number(process.env.FBA_RETRY_REMOTE_DEBUG_PORT);
    if (!port) return { available: false, reason: 'No isolated test renderer port configured' };
    try {
        await vscode.commands.executeCommand('notifications.showList');
        await delay(100);
        const targets = await bounded(fetch(`http://127.0.0.1:${port}/json/list`).then(response => response.json()), 'Own renderer metadata request timed out', 3000);
        const target = targets.find(item => item.type === 'page' && /workbench/i.test(item.url)) || targets.find(item => item.type === 'page');
        if (!target?.webSocketDebuggerUrl) throw new Error('Own workbench renderer target unavailable');
        const socket = new WebSocket(target.webSocketDebuggerUrl);
        const value = await bounded(new Promise((resolve, reject) => {
            socket.addEventListener('error', event => reject(new Error(`Own renderer socket error: ${event.message || 'unknown'}`)), { once: true });
            socket.addEventListener('open', () => socket.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: {
                expression: 'Array.from(document.querySelectorAll(".notification-list-item, [role=alert]")).map(n => ({text: n.innerText || n.textContent, visible: !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)}))',
                returnByValue: true,
            } })), { once: true });
            socket.addEventListener('message', event => {
                const message = JSON.parse(event.data);
                if (message.id === 1) {
                    socket.close();
                    if (message.error || message.result?.exceptionDetails) reject(new Error(JSON.stringify(message)));
                    else resolve(message.result.result.value);
                }
            });
        }), 'Own notification DOM request timed out', 3000);
        socket.close();
        return { available: true, notifications: value, compileFailureNotificationPresent: value.some(item => /C# file debugging failed:/i.test(item.text || '')) };
    } catch (error) { return { available: false, error: String(error) }; }
}

exports.run = async function () {
    const result = { success: false, editorVersion: vscode.version, checks: [], sessions: [], notificationDismissCommandsIssued: 0, physicalF5KeypressSent: false };
    const tracker = vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
        createDebugAdapterTracker(session) {
            result.sessions.push({ type: session.type, name: session.name, configuration: session.configuration });
            return {
                onWillReceiveMessage: message => fs.appendFileSync(trace, JSON.stringify({ direction: 'send', message }) + '\n'),
                onDidSendMessage: receive,
                onError: error => { (result.adapterDiagnostics ||= []).push(String(error)); },
            };
        },
    });
    try {
        const extension = vscode.extensions.getExtension('dotnetdev-kr-custom.csharp-with-netcoredbg');
        assert(extension, 'Target extension must be installed unchanged through the CLI');
        result.installedExtensionPath = extension.extensionPath;
        assert(path.resolve(extension.extensionPath).toLowerCase().startsWith(path.resolve(root, 'extensions').toLowerCase() + path.sep));
        assert.equal(extension.packageJSON.version, process.env.FBA_RETRY_EXPECTED_VERSION);
        assert.equal(extension.packageJSON.main, './.netcoredbg/entry.cjs');
        const binding = extension.packageJSON.contributes.keybindings.find(item => item.command === COMMAND);
        assert.equal(binding.key, 'f5');
        assert.match(binding.when, /!inDebugMode/);
        result.version = extension.packageJSON.version;
        result.targetInstalledAsProduction = true;
        result.f5Binding = binding;
        result.checks.push('CI VSIX installed unchanged as production extension; F5 binding verified');
        const source = path.join(root, 'workspace/app.cs');
        fs.writeFileSync(source, invalidSource);
        const document = await vscode.workspace.openTextDocument(source);
        await vscode.window.showTextDocument(document);
        await extension.activate();
        const failureStart = Date.now();
        const failed = await bounded(vscode.commands.executeCommand(COMMAND), 'Failed build command stayed pending while its notification was undismissed');
        assert.equal(failed, false);
        assert.equal(vscode.debug.activeDebugSession, undefined);
        result.failedBuild = { returned: failed, elapsedMilliseconds: Date.now() - failureStart, compiler: await compileFailureEvidence() };
        result.notificationAfterFailure = await notificationSnapshot();
        result.checks.push('Actual missing-using compiler error returns false without dismissing its notification');

        // Do not invoke a notification-close command between failure, source repair and retry.
        await replaceSource(document, fixedSource);
        const retryLine = fixedSource.split('\n').findIndex(line => line.includes('answer += 2;')) + 1;
        vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(retryLine - 1, 0)))]);
        assert.equal(await bounded(vscode.commands.executeCommand(COMMAND), 'Fixed-source F5 retry did not complete'), true);
        result.notificationAfterRetryStarted = await notificationSnapshot();
        result.checks.push('Same-file F5 retry starts after source repair while old notification remains undismissed');
        const stopped = await event('stopped', body => body.reason === 'breakpoint');
        const session = vscode.debug.activeDebugSession;
        let frames = (await session.customRequest('stackTrace', { threadId: stopped.threadId })).stackFrames;
        assert.equal(frames[0].line, retryLine);
        assert.equal(path.resolve(frames[0].source.path).toLowerCase(), source.toLowerCase());
        const scopes = (await session.customRequest('scopes', { frameId: frames[0].id })).scopes;
        const locals = [];
        for (const scope of scopes) locals.push(...(await session.customRequest('variables', { variablesReference: scope.variablesReference })).variables);
        assert(locals.some(item => item.name === 'answer' && item.value === '40'));
        result.locals = locals;
        result.checks.push('Retried app hits its source breakpoint with local answer=40');
        assert.equal((await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer + 2', context: 'watch' })).result, '42');
        await session.customRequest('next', { threadId: stopped.threadId });
        const stepped = await event('stopped', body => body.reason === 'step');
        frames = (await session.customRequest('stackTrace', { threadId: stepped.threadId })).stackFrames;
        assert.equal(frames[0].line, retryLine + 1);
        assert.equal((await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer', context: 'watch' })).result, '42');
        result.checks.push('Retried app supports evaluate and Step Over to answer=42');
        await session.customRequest('continue', { threadId: stepped.threadId });
        assert.equal((await event('exited')).exitCode, 0);
        await event('terminated');
        assert(output.join('').includes('ANSWER=42'));
        result.checks.push('Retried app prints ANSWER=42 and exits0');
        await delay(300);

        await replaceSource(document, webSource);
        const initiallyObservedBrowserFile = path.join(root, 'browser-observer/output/browser-observation.jsonl');
        fs.rmSync(initiallyObservedBrowserFile, { force: true });
        result.webLanguageServiceBeforeBuild = { diagnostics: snapshotDiagnostics(document.uri), hover: await snapshotHover(document, 'WebApplication') };
        const net = require('node:net');
        const reservation = net.createServer();
        await new Promise((resolve, reject) => { reservation.once('error', reject); reservation.listen(0, '127.0.0.1', resolve); });
        const port = reservation.address().port;
        await new Promise(resolve => reservation.close(resolve));
        const origin = `http://127.0.0.1:${port}`;
        const profilePath = path.join(root, 'workspace/app.run.json');
        const profile = { profiles: { OwnedHttpProbe: {
            commandName: 'Project', applicationUrl: origin,
            commandLineArgs: '--probe "hello world" --switch enabled', launchBrowser: false,
            environmentVariables: { ASPNETCORE_ENVIRONMENT: 'Development', FBA_WEB_MARKER: 'owned-http-editor' },
        } } };
        fs.writeFileSync(profilePath, JSON.stringify(profile, null, 2) + '\n');
        result.httpProfile = { profilePath, profile, origin, certificateTrustExecuted: false, automaticBrowserRequested: false };
        const webLine = webSource.split('\n').findIndex(line => line.includes('answer += 2;')) + 1;
        vscode.debug.removeBreakpoints(vscode.debug.breakpoints);
        vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(webLine - 1, 0)))]);
        const webStart = Date.now();
        assert.equal(await bounded(vscode.commands.executeCommand(COMMAND), 'HTTP Web SDK switch failed to start debugging'), true);
        const webSession = vscode.debug.activeDebugSession;
        assert(webSession, 'Expected a real Web debug session');
        assert.deepEqual(webSession.configuration.args, ['--probe', 'hello world', '--switch', 'enabled']);
        assert.equal(webSession.configuration.env.ASPNETCORE_URLS, origin);
        assert.equal(webSession.configuration.env.FBA_WEB_MARKER, 'owned-http-editor');
        assert.equal(webSession.configuration.env.DOTNET_LAUNCH_PROFILE, 'OwnedHttpProbe');
        assert.equal(webSession.configuration.serverReadyAction, undefined);
        assert.equal(webSession.configuration.checkForDevCert, false);
        const runtimeConfig = JSON.parse(fs.readFileSync(path.join(path.dirname(webSession.configuration.program), 'FileApp.runtimeconfig.json'), 'utf8'));
        const frameworks = runtimeConfig.runtimeOptions.frameworks || [runtimeConfig.runtimeOptions.framework];
        assert(frameworks.some(item => item?.name === 'Microsoft.AspNetCore.App'));
        result.webSwitch = { sameSourcePath: source, frameworks, configuration: webSession.configuration };
        result.checks.push('Same file gains Web SDK; real launch applies HTTP run.json args/env and no browser or certificate setup');
        const readyDeadline = Date.now() + 30000;
        while (!output.join('').includes(`Now listening on: ${origin}`)) {
            if (Date.now() > readyDeadline) throw new Error('Actual Web process did not emit its selected listening endpoint');
            await delay(50);
        }
        result.httpProfile.actualReadyOutput = output.join('').split('\n').find(line => line.includes(`Now listening on: ${origin}`));
        result.httpProfile.readyMilliseconds = Date.now() - webStart;
        result.checks.push('Actual ASP.NET Core process emits Now listening on selected owned-loopback HTTP endpoint');
        const request = fetch(`${origin}/probe`).then(async response => ({ status: response.status, body: await response.json() }));
        const webStopped = await event('stopped', body => body.reason === 'breakpoint');
        const webFrames = (await webSession.customRequest('stackTrace', { threadId: webStopped.threadId })).stackFrames;
        assert.equal(webFrames[0].line, webLine);
        assert.equal(path.resolve(webFrames[0].source.path).toLowerCase(), source.toLowerCase());
        const webScopes = (await webSession.customRequest('scopes', { frameId: webFrames[0].id })).scopes;
        const webLocals = [];
        for (const scope of webScopes) webLocals.push(...(await webSession.customRequest('variables', { variablesReference: scope.variablesReference })).variables);
        assert(webLocals.some(item => item.name === 'answer' && item.value === '40'));
        result.webSwitch.endpointLocals = webLocals;
        assert.equal((await webSession.customRequest('evaluate', { frameId: webFrames[0].id, expression: 'answer + 2', context: 'watch' })).result, '42');
        result.checks.push('HTTP request hits same-file endpoint source breakpoint with local answer=40 and evaluate=42');
        await webSession.customRequest('next', { threadId: webStopped.threadId });
        const webStepped = await event('stopped', body => body.reason === 'step');
        const steppedFrames = (await webSession.customRequest('stackTrace', { threadId: webStepped.threadId })).stackFrames;
        assert.equal((await webSession.customRequest('evaluate', { frameId: steppedFrames[0].id, expression: 'answer', context: 'watch' })).result, '42');
        await webSession.customRequest('continue', { threadId: webStepped.threadId });
        const response = await bounded(request, 'Owned HTTP request did not finish');
        assert.deepEqual(response, { status: 200, body: { answer: 42, marker: 'owned-http-editor', launchProfile: 'OwnedHttpProbe', args: ['--probe', 'hello world', '--switch', 'enabled'] } });
        result.httpResponse = response;
        result.checks.push('Step Over changes answer to42; HTTP200 response proves child process received profile arguments and environment');
        result.webLanguageServiceAfterBuild = { diagnostics: snapshotDiagnostics(document.uri), hover: await snapshotHover(document, 'WebApplication') };
        await vscode.debug.stopDebugging(webSession);
        await event('terminated');
        const sessionStopDeadline = Date.now() + 15000;
        while (vscode.debug.activeDebugSession?.id === webSession.id && Date.now() < sessionStopDeadline) await delay(100);
        assert.equal(vscode.debug.activeDebugSession, undefined);
        let serverStillListening = false;
        try { await fetch(`${origin}/probe`, { signal: AbortSignal.timeout(2000) }); serverStillListening = true; } catch {}
        assert.equal(serverStillListening, false);
        result.httpProfile.stoppedServerNoLongerListening = true;
        assert(!fs.existsSync(initiallyObservedBrowserFile), 'launchBrowser=false must not invoke the configured external launcher');
        result.httpProfile.externalLauncherNotInvoked = true;
        result.checks.push('Stopping owned Web session terminates server and releases its HTTP endpoint');

        // Exercise the built-in serverReadyAction through the editor's external-browser
        // launcher setting. The recorder accepts only an owned-loopback HTTP URL;
        // it does not alter the target extension or the Windows default browser.
        const observerExecutable = path.join(root, 'browser-observer/output/BrowserObserver.exe');
        const observerFile = path.join(root, 'browser-observer/output/browser-observation.jsonl');
        assert(fs.existsSync(observerExecutable));
        fs.rmSync(observerFile, { force: true });
        await vscode.workspace.getConfiguration('workbench').update('externalBrowser', observerExecutable, vscode.ConfigurationTarget.Global);
        profile.profiles.OwnedHttpProbe.launchBrowser = true;
        profile.profiles.OwnedHttpProbe.launchUrl = 'probe?via=ready';
        fs.writeFileSync(profilePath, JSON.stringify(profile, null, 2) + '\n');
        vscode.debug.removeBreakpoints(vscode.debug.breakpoints);
        const browserOutputStart = output.length;
        const browserStart = Date.now();
        assert.equal(await bounded(vscode.commands.executeCommand(COMMAND), 'Browser-ready HTTP profile failed to start'), true);
        const browserSession = vscode.debug.activeDebugSession;
        assert.equal(browserSession.configuration.serverReadyAction.action, 'openExternally');
        assert.equal(browserSession.configuration.serverReadyAction.uriFormat, '%s/probe?via=ready');
        const expectedBrowserUrl = `${origin}/probe?via=ready`;
        let browserRecord;
        const browserDeadline = Date.now() + 15000;
        while (Date.now() < browserDeadline) {
            if (fs.existsSync(observerFile)) {
                browserRecord = fs.readFileSync(observerFile, 'utf8').trim().split('\n').map(line => JSON.parse(line)).find(item => item.url === expectedBrowserUrl);
                if (browserRecord) break;
            }
            await delay(100);
        }
        assert(browserRecord, 'Built-in serverReadyAction must invoke the configured isolated external launcher');
        assert(Date.parse(browserRecord.recordedAt) >= browserStart);
        const browserReadyOutput = output.slice(browserOutputStart).join('').split('\n').find(line => line.includes(`Now listening on: ${origin}`));
        assert(browserReadyOutput, 'Browser launch must be preceded by real listening output from this session');
        result.browserReady = { expectedUrl: expectedBrowserUrl, record: browserRecord,
            actualReadyOutput: browserReadyOutput, externalBrowserSettingScope: 'Isolated test user profile only',
            osDefaultBrowserChanged: false, targetExtensionInjected: false,
            browserUiRendered: false, tlsTested: false };
        result.checks.push('Built-in serverReadyAction consumes real listening event and invokes isolated OS launcher with correct loopback launchUrl');
        await vscode.debug.stopDebugging(browserSession);
        await event('terminated');
        const browserStopDeadline = Date.now() + 15000;
        while (vscode.debug.activeDebugSession?.id === browserSession.id && Date.now() < browserStopDeadline) await delay(100);
        assert.equal(vscode.debug.activeDebugSession, undefined);
        events.length = 0;

        const projectSource = path.join(root, 'workspace/project/Program.cs');
        const projectDocument = await vscode.workspace.openTextDocument(projectSource);
        await vscode.window.showTextDocument(projectDocument);
        vscode.debug.removeBreakpoints(vscode.debug.breakpoints);
        vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(projectDocument.uri, new vscode.Position(1, 0)))]);
        await bounded(vscode.commands.executeCommand(COMMAND), 'Existing selected project configuration did not start');
        const projectStopped = await event('stopped', body => body.reason === 'breakpoint');
        const projectSession = vscode.debug.activeDebugSession;
        assert.equal(projectSession.name, 'Existing project configuration');
        assert.equal(projectSession.configuration.__netcoredbgFileAppOutput, undefined);
        const projectFrames = (await projectSession.customRequest('stackTrace', { threadId: projectStopped.threadId })).stackFrames;
        assert.equal(projectFrames[0].line, 2);
        assert.equal(path.resolve(projectFrames[0].source.path).toLowerCase(), projectSource.toLowerCase());
        result.checks.push('Included project file still launches selected project configuration and hits its source breakpoint');
        await projectSession.customRequest('continue', { threadId: projectStopped.threadId });
        assert.equal((await event('exited')).exitCode, 0);
        await event('terminated');
        assert(output.join('').includes('PROJECT=42'));
        result.checks.push('Selected project prints PROJECT=42 and exits0');
        result.output = output.join('');
        for (const file of outputLogs(path.join(root, 'portable-data/user-data/logs'))) assert(!/dotnet.*dev-certs/i.test(fs.readFileSync(file, 'utf8')), 'HTTP-only probe must not run certificate commands');
        result.certificateCommandsObserved = false;
        result.scope = { actualInstalledCiVsix: true, targetExtensionInjected: false, physicalF5KeypressSent: false, automaticBrowserLauncherTested: true, realBrowserUiTested: false, httpsCertificateTrustTested: false, existingUserEditorTouched: false };
        result.success = true;
    } catch (error) {
        result.error = error.stack || String(error);
        throw error;
    } finally {
        tracker.dispose();
        fs.writeFileSync(path.join(root, 'editor-result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
