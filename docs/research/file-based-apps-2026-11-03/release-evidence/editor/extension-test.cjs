const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const root = __dirname;
const trace = path.join(root, 'editor.dap.jsonl');
const events = [];
const waiters = [];
const output = [];

function receive(message) {
    fs.appendFileSync(trace, JSON.stringify({ direction: 'receive', message }) + '\n');
    if (message.event === 'output') output.push(message.body?.output || '');
    if (message.type === 'event') events.push(message);
    for (const wake of waiters.splice(0)) wake();
}

async function event(name, predicate = () => true) {
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
        const index = events.findIndex(m => m.event === name && predicate(m.body));
        if (index >= 0) return events.splice(index, 1)[0].body;
        await Promise.race([
            new Promise(resolve => waiters.push(resolve)),
            new Promise((_, reject) => setTimeout(() => reject(new Error(`Timed out waiting for ${name}`)), 60000)),
        ]);
    }
    throw new Error(`Timed out waiting for ${name}`);
}

exports.run = async function () {
    const result = { success: false, editorVersion: vscode.version, checks: [] };
    const tracker = vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
        createDebugAdapterTracker(session) {
            const record = { type: session.type, name: session.name, configuration: session.configuration };
            if (!result.session) result.session = record;
            else result.projectSession = record;
            return {
                onWillReceiveMessage: message => fs.appendFileSync(trace, JSON.stringify({ direction: 'send', message }) + '\n'),
                onDidSendMessage: receive,
                onError: error => { result.adapterError = String(error); },
            };
        },
    });
    try {
        const extension = vscode.extensions.getExtension('dotnetdev-kr-custom.csharp-with-netcoredbg');
        assert(extension, 'Development variant must be installed');
        assert.equal(extension.packageJSON.main, './.netcoredbg/entry.cjs');
        const f5 = extension.packageJSON.contributes.keybindings.find(b => b.command === 'netcoredbg.debugActiveFile');
        assert.equal(f5.key, 'f5');
        assert.match(f5.when, /!inDebugMode/);
        result.checks.push('Actual distribution + owned entry wrapper and F5 manifest binding');
        const source = path.join(root, 'workspace', 'app.cs');
        const document = await vscode.workspace.openTextDocument(source);
        await vscode.window.showTextDocument(document);
        await extension.activate();
        assert((await vscode.commands.getCommands(true)).includes('netcoredbg.debugActiveFile'));
        result.checks.push('Real extension host activation and command registration');
        vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(1, 0)))]);
        const launched = await vscode.commands.executeCommand('netcoredbg.debugActiveFile');
        assert.equal(launched, true, 'F5 command should start a debug session');
        const stopped = await event('stopped', body => body.reason === 'breakpoint');
        const session = vscode.debug.activeDebugSession;
        assert(session, 'Active debug session required');
        let frames = (await session.customRequest('stackTrace', { threadId: stopped.threadId })).stackFrames;
        assert.equal(frames[0].line, 2);
        assert.equal(path.resolve(frames[0].source.path).toLowerCase(), path.resolve(source).toLowerCase());
        result.checks.push('Source breakpoint at app.cs:2');
        const scopes = (await session.customRequest('scopes', { frameId: frames[0].id })).scopes;
        const locals = [];
        for (const scope of scopes) locals.push(...(await session.customRequest('variables', { variablesReference: scope.variablesReference })).variables);
        assert(locals.some(variable => variable.name === 'answer' && variable.value === '40'));
        result.locals = locals;
        result.checks.push('Local answer=40');
        const evaluated = await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer + 2', context: 'watch' });
        assert.equal(evaluated.result, '42');
        result.checks.push('Expression answer + 2=42');
        await session.customRequest('next', { threadId: stopped.threadId });
        const stepped = await event('stopped', body => body.reason === 'step');
        frames = (await session.customRequest('stackTrace', { threadId: stepped.threadId })).stackFrames;
        assert.equal(frames[0].line, 3);
        const changed = await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer', context: 'watch' });
        assert.equal(changed.result, '42');
        result.checks.push('Step Over to line 3 and answer=42');
        await session.customRequest('continue', { threadId: stepped.threadId });
        const exited = await event('exited');
        assert.equal(exited.exitCode, 0);
        await event('terminated');
        assert(output.join('').includes('ANSWER=42'));
        result.output = output.join('');
        result.checks.push('Output ANSWER=42 and exit0');

        // A single existing launch.json configuration is the normal selected project configuration.
        // Keep the standalone app at the workspace root and the real project in a child directory.
        await new Promise(resolve => setTimeout(resolve, 500));
        const projectSource = path.join(root, 'workspace', 'project', 'Program.cs');
        const projectDocument = await vscode.workspace.openTextDocument(projectSource);
        await vscode.window.showTextDocument(projectDocument);
        vscode.debug.removeBreakpoints(vscode.debug.breakpoints);
        vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(projectDocument.uri, new vscode.Position(1, 0)))]);
        await Promise.race([
            vscode.commands.executeCommand('netcoredbg.debugActiveFile'),
            new Promise((_, reject) => setTimeout(() => reject(new Error('Project fallback did not start the existing launch configuration')), 30000)),
        ]);
        const projectStopped = await event('stopped', body => body.reason === 'breakpoint');
        const projectSession = vscode.debug.activeDebugSession;
        assert.equal(projectSession.name, 'Existing project configuration');
        assert.equal(path.resolve(projectSession.configuration.program).toLowerCase(), path.resolve(root, 'workspace/project/output/Regression.dll').toLowerCase());
        assert.equal(projectSession.configuration.__netcoredbgFileAppOutput, undefined);
        result.checks.push('Included project file delegates to the existing selected launch.json configuration');
        const projectFrames = (await projectSession.customRequest('stackTrace', { threadId: projectStopped.threadId })).stackFrames;
        assert.equal(projectFrames[0].line, 2);
        assert.equal(path.resolve(projectFrames[0].source.path).toLowerCase(), path.resolve(projectSource).toLowerCase());
        result.checks.push('Project regression source breakpoint at Program.cs:2');
        await projectSession.customRequest('continue', { threadId: projectStopped.threadId });
        assert.equal((await event('exited')).exitCode, 0);
        await event('terminated');
        assert(output.join('').includes('PROJECT=42'));
        result.projectOutput = output.join('');
        result.checks.push('Project regression output PROJECT=42 and exit0');
        result.success = true;
    } catch (error) {
        result.error = error.stack || String(error);
        throw error;
    } finally {
        tracker.dispose();
        fs.writeFileSync(path.join(root, 'editor-result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
