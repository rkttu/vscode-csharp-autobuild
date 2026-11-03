const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const root = __dirname;
const trace = path.join(root, 'editor.dap.jsonl');
const result = { success: false, editorVersion: vscode.version, checks: [], sessions: [], diagnostics: [] };
const messages = [];
const output = new Map();
let currentStage;

async function event(stage, name, predicate = () => true) {
    const deadline = Date.now() + 45000;
    while (Date.now() < deadline) {
        const found = messages.findIndex(item => item.stage === stage && item.message.event === name && predicate(item.message.body));
        if (found >= 0) return messages.splice(found, 1)[0].message.body;
        await new Promise(resolve => setTimeout(resolve, 15));
    }
    throw new Error(`Timed out waiting for ${stage}/${name}`);
}

async function command() {
    await Promise.race([
        vscode.commands.executeCommand('netcoredbg.debugActiveFile'),
        new Promise((_, reject) => setTimeout(() => reject(new Error('F5 command timed out')), 30000)),
    ]);
}

async function open(file, breakpoint) {
    const document = await vscode.workspace.openTextDocument(file);
    await vscode.window.showTextDocument(document);
    vscode.debug.removeBreakpoints(vscode.debug.breakpoints);
    if (breakpoint) vscode.debug.addBreakpoints([new vscode.SourceBreakpoint(new vscode.Location(document.uri, new vscode.Position(1, 0)))]);
}

exports.run = async function () {
    fs.writeFileSync(trace, '');
    const tracker = vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
        createDebugAdapterTracker(session) {
            const stage = currentStage;
            let terminated = false;
            result.sessions.push({ stage, name: session.name, configuration: session.configuration });
            return {
                onWillReceiveMessage(message) { fs.appendFileSync(trace, JSON.stringify({ stage, direction: 'send', message }) + '\n'); },
                onDidSendMessage(message) {
                    fs.appendFileSync(trace, JSON.stringify({ stage, direction: 'receive', message }) + '\n');
                    if (message.event === 'terminated') terminated = true;
                    if (message.event === 'output') output.set(stage, (output.get(stage) || '') + (message.body.output || ''));
                    if (message.type === 'event') messages.push({ stage, message });
                },
                onError(error) { result.diagnostics.push({ stage, afterTerminated: terminated, error: String(error) }); },
            };
        },
    });
    try {
        const extension = vscode.extensions.getExtension('dotnetdev-kr-custom.csharp-with-netcoredbg');
        await extension.activate();
        const program03 = path.join(root, 'workspace/03-excluded/Program.cs');

        currentStage = 'scratch-fba';
        await open(path.join(root, 'workspace/03-excluded/scratch.cs'), true);
        await command();
        const scratchStop = await event(currentStage, 'stopped', body => body.reason === 'breakpoint');
        let session = vscode.debug.activeDebugSession;
        assert(session.configuration.__netcoredbgFileAppOutput);
        let frames = (await session.customRequest('stackTrace', { threadId: scratchStop.threadId })).stackFrames;
        assert.equal(frames[0].line, 2);
        assert.equal((await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer', context: 'watch' })).result, '50');
        await session.customRequest('continue', { threadId: scratchStop.threadId });
        assert.equal((await event(currentStage, 'exited')).exitCode, 0);
        await event(currentStage, 'terminated');
        assert(output.get(currentStage).includes('EXCLUDED FBA ANSWER=52'));
        result.checks.push('Excluded scratch.cs first launches as FBA and hits its breakpoint');
        await new Promise(resolve => setTimeout(resolve, 400));

        currentStage = 'included-program-selected04';
        await open(program03, true);
        await command();
        assert.equal((await event(currentStage, 'exited')).exitCode, 0);
        await event(currentStage, 'terminated');
        const wrongSelection = result.sessions.find(item => item.stage === currentStage);
        assert.equal(wrongSelection.name, 'Project: 04-project');
        assert.equal(path.resolve(wrongSelection.configuration.program).toLowerCase(), path.resolve(root, 'workspace/04-project/output/Project.dll').toLowerCase());
        assert.equal(wrongSelection.configuration.__netcoredbgFileAppOutput, undefined);
        assert(!messages.some(item => item.stage === currentStage && item.message.event === 'stopped'));
        assert(output.get(currentStage).includes('SELECTED PROJECT ANSWER=62'));
        result.checks.push('Included Program03 with selected04 runs Project04 quickly and never hits Program03 breakpoint');
        await new Promise(resolve => setTimeout(resolve, 400));

        // Replace this isolated fixture's sole available selection with03; no user instance is edited.
        const config03 = { name: 'Project: 03-excluded', type: 'coreclr', request: 'launch',
            program: path.join(root, 'workspace/03-excluded/output/ExcludedProject.dll'),
            cwd: path.join(root, 'workspace/03-excluded'), console: 'internalConsole', stopAtEntry: false };
        await vscode.workspace.getConfiguration('launch', vscode.workspace.workspaceFolders[0].uri)
            .update('configurations', [config03], vscode.ConfigurationTarget.WorkspaceFolder);
        await new Promise(resolve => setTimeout(resolve, 800));
        currentStage = 'included-program-selected03';
        await open(program03, true);
        await command();
        const projectStop = await event(currentStage, 'stopped', body => body.reason === 'breakpoint');
        session = vscode.debug.activeDebugSession;
        assert.equal(session.name, 'Project: 03-excluded');
        assert.equal(path.resolve(session.configuration.program).toLowerCase(), path.resolve(config03.program).toLowerCase());
        assert.equal(session.configuration.__netcoredbgFileAppOutput, undefined);
        frames = (await session.customRequest('stackTrace', { threadId: projectStop.threadId })).stackFrames;
        assert.equal(frames[0].line, 2);
        assert.equal(path.resolve(frames[0].source.path).toLowerCase(), path.resolve(program03).toLowerCase());
        assert.equal((await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer', context: 'watch' })).result, '40');
        result.checks.push('Selected03 config hits Program03 line2 with local answer40');
        await session.customRequest('next', { threadId: projectStop.threadId });
        const stepped = await event(currentStage, 'stopped', body => body.reason === 'step');
        frames = (await session.customRequest('stackTrace', { threadId: stepped.threadId })).stackFrames;
        assert.equal(frames[0].line, 3);
        assert.equal((await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer', context: 'watch' })).result, '42');
        result.checks.push('Program03 StepOver and changed local answer42');
        await session.customRequest('continue', { threadId: stepped.threadId });
        assert.equal((await event(currentStage, 'exited')).exitCode, 0);
        await event(currentStage, 'terminated');
        assert(output.get(currentStage).includes('EXCLUDED-PROJECT CONTROL ANSWER=42'));
        result.checks.push('Program03 emits expected output and exits0');
        result.success = true;
    } catch (error) {
        result.error = error.stack || String(error);
        throw error;
    } finally {
        result.output = Object.fromEntries(output);
        tracker.dispose();
        fs.writeFileSync(path.join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
