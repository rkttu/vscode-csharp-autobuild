'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const root = __dirname;
const command = 'netcoredbg.debugActiveFile';
const webSource = '#:sdk Microsoft.NET.Sdk.Web\nvar builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();\nConsole.WriteLine($"WEB_TYPE={app.GetType().FullName}");\n';
const queue = [];
const listeners = new Set();
const output = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function bounded(promise, timeout, message) {
    let timer;
    try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), timeout); })]); }
    finally { clearTimeout(timer); }
}
async function event(name) {
    const deadline = Date.now() + 60000;
    for (;;) {
        const index = queue.findIndex(item => item.event === name);
        if (index >= 0) return queue.splice(index, 1)[0].body;
        await new Promise((resolve, reject) => {
            let timer;
            const wake = () => { clearTimeout(timer); listeners.delete(wake); resolve(); };
            listeners.add(wake);
            timer = setTimeout(() => { listeners.delete(wake); reject(new Error(`Timed out waiting for ${name}`)); }, Math.max(1, deadline - Date.now()));
        });
    }
}
function diagnostics(uri) {
    return vscode.languages.getDiagnostics(uri).map(item => ({ code: item.code, message: item.message, severity: item.severity }));
}
async function hover(document, word) {
    try {
        const values = await bounded(vscode.commands.executeCommand('vscode.executeHoverProvider', document.uri,
            document.positionAt(document.getText().indexOf(word) + 1)), 3000, 'Hover provider timed out');
        return (values || []).flatMap(item => item.contents).map(item => typeof item === 'string' ? item : item.value);
    } catch (error) { return [{ error: String(error) }]; }
}
async function waitLanguage(document, word, records) {
    const started = Date.now();
    for (let attempt = 0; attempt < 30; attempt++) {
        const current = { elapsedMilliseconds: Date.now() - started, hover: await hover(document, word), diagnostics: diagnostics(document.uri) };
        records.push(current);
        if (current.hover.some(item => typeof item === 'string' && item.includes(word)) &&
            !current.diagnostics.some(item => String(typeof item.code === 'object' ? item.code.value : item.code) === 'CS0103')) return true;
        await delay(1000);
    }
    return false;
}

exports.run = async function () {
    const result = { success: false, editorVersion: vscode.version, scope: 'Published 11.7.18002 unchanged; plain file opened then Web directive edited/saved before its first F5; real command not physical key', checks: [], plainLanguageTimeline: [], webLanguageTimeline: [], sessions: [] };
    const tracker = vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
        createDebugAdapterTracker(session) {
            result.sessions.push({ name: session.name, type: session.type, configuration: session.configuration });
            return {
                onWillReceiveMessage: message => fs.appendFileSync(path.join(root, 'editor.dap.jsonl'), JSON.stringify({ direction: 'send', message }) + '\n'),
                onDidSendMessage: message => {
                    fs.appendFileSync(path.join(root, 'editor.dap.jsonl'), JSON.stringify({ direction: 'receive', message }) + '\n');
                    if (message.event === 'output') output.push(message.body?.output || '');
                    if (message.type === 'event') queue.push(message);
                    for (const listener of [...listeners]) listener();
                },
                onError: error => { (result.adapterDiagnostics ||= []).push(String(error)); },
            };
        },
    });
    try {
        const extension = vscode.extensions.getExtension('dotnetdev-kr-custom.csharp-with-netcoredbg');
        assert(extension);
        assert.equal(extension.packageJSON.version, '11.7.18002');
        result.installedExtensionPath = extension.extensionPath;
        assert(path.resolve(extension.extensionPath).toLowerCase().startsWith(path.resolve(root, 'extensions').toLowerCase() + path.sep));
        result.binding = extension.packageJSON.contributes.keybindings.find(item => item.command === command);
        assert.equal(result.binding.key, 'f5');
        result.checks.push('Published 11.7.18002 installed unchanged as production extension; binding checked');
        const source = path.join(root, 'workspace/app.cs');
        const document = await vscode.workspace.openTextDocument(source);
        await vscode.window.showTextDocument(document);
        await extension.activate();
        result.plainLanguageReady = await waitLanguage(document, 'Console', result.plainLanguageTimeline);
        assert.equal(result.sessions.length, 0, 'No F5/build before changing the SDK directive');
        const edit = new vscode.WorkspaceEdit();
        edit.replace(document.uri, new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)), webSource);
        assert.equal(await vscode.workspace.applyEdit(edit), true);
        assert.equal(await document.save(), true);
        result.checks.push('Same open plain C# document gains Web SDK directive and WebApplication code through editor edit/save');
        result.webLanguageReady = await waitLanguage(document, 'WebApplication', result.webLanguageTimeline);
        await vscode.window.showTextDocument(document);
        await vscode.commands.executeCommand('workbench.action.focusActiveEditorGroup');
        const commands = await vscode.commands.getCommands(true);
        result.beforeFirstF5 = { languageId: document.languageId, isDirty: document.isDirty,
            activeSourceMatches: vscode.window.activeTextEditor?.document.uri.toString() === document.uri.toString(),
            commandRegistered: commands.includes(command), standardDebugCommandRegistered: commands.includes('workbench.action.debug.start'),
            workspaceTrusted: vscode.workspace.isTrusted, activeDebugSession: vscode.debug.activeDebugSession?.name || null,
            windowFocused: vscode.window.state.focused, contextScope: 'Extension API observations; editor focus command issued; raw context keys not read; no physical key sent' };
        assert(result.beforeFirstF5.commandRegistered);
        assert.equal(result.beforeFirstF5.activeDebugSession, null);
        vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(3, 0)))]);
        const start = Date.now();
        result.firstF5Return = await bounded(vscode.commands.executeCommand(command), 30000, 'First F5 command stayed pending after Web SDK edit');
        result.firstF5ElapsedMilliseconds = Date.now() - start;
        assert.equal(result.firstF5Return, true);
        result.checks.push('First F5 contributed command remains registered and starts after Web SDK edit');
        const stopped = await event('stopped');
        assert.equal(stopped.reason, 'breakpoint');
        const session = vscode.debug.activeDebugSession;
        const frames = (await session.customRequest('stackTrace', { threadId: stopped.threadId })).stackFrames;
        assert.equal(frames[0].line, 4);
        assert.equal(path.resolve(frames[0].source.path).toLowerCase(), source.toLowerCase());
        const scopes = (await session.customRequest('scopes', { frameId: frames[0].id })).scopes;
        const variables = [];
        for (const scope of scopes) variables.push(...(await session.customRequest('variables', { variablesReference: scope.variablesReference })).variables);
        result.webAppLocal = variables.find(item => item.name === 'app');
        assert(result.webAppLocal?.type.includes('WebApplication'));
        result.checks.push('Web SDK build reaches source breakpoint with a WebApplication local');
        await session.customRequest('continue', { threadId: stopped.threadId });
        assert.equal((await event('exited')).exitCode, 0);
        await event('terminated');
        result.output = output.join('');
        assert(result.output.includes('WEB_TYPE=Microsoft.AspNetCore.Builder.WebApplication'));
        result.checks.push('Web application prints its framework type and exits0');
        result.success = true;
    } catch (error) { result.error = error.stack || String(error); throw error; }
    finally {
        tracker.dispose();
        fs.writeFileSync(path.join(root, 'editor-result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
