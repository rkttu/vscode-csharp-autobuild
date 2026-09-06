const vscode = require('vscode');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.dirname(__dirname);
const timeout = (promise, ms, label) => {
    let timer;
    return Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(label + ' timed out')), ms);
    })]).finally(() => clearTimeout(timer));
};

exports.run = async () => {
    const result = { success: false, editor: vscode.version, extensionId: 'dotnetdev-kr-custom.csharp-with-netcoredbg', tests: [] };
    const subscriptions = [];
    let session;
    try {
        const extension = vscode.extensions.getExtension(result.extensionId);
        assert(extension, 'Installed variant not found');
        result.extensionVersion = extension.packageJSON.version;
        result.extensionPath = extension.extensionPath;
        await timeout(extension.activate(), 120000, 'Extension activation');
        assert(extension.isActive);
        result.activation = true;
        for (const runtime of ['8', '10']) {
            const fixture = path.join(root, 'workspace', 'net' + runtime);
            const source = path.join(fixture, 'Program.cs');
            const lines = fs.readFileSync(source, 'utf8').split('\n');
            const line = text => lines.findIndex(value => value.includes(text));
            const events = [];
            let output = '';
            const trace = [];
            const tracker = vscode.debug.registerDebugAdapterTrackerFactory('coreclr', {
                createDebugAdapterTracker: candidate => {
                    if (candidate.name !== 'netcoredbg editor net' + runtime) return undefined;
                    session = candidate;
                    return {
                        onDidSendMessage: message => {
                            trace.push({ direction: 'adapter', message });
                            if (message.type === 'event') {
                                events.push(message);
                                if (message.event === 'output') output += message.body.output;
                            }
                        },
                        onWillReceiveMessage: message => trace.push({ direction: 'editor', message }),
                    };
                },
            });
            subscriptions.push(tracker);
            const nextEvent = async name => {
                const until = Date.now() + 30000;
                while (Date.now() < until) {
                    const index = events.findIndex(e => e.event === name);
                    if (index >= 0) return events.splice(index, 1)[0].body;
                    await new Promise(resolve => setTimeout(resolve, 20));
                }
                throw new Error('Missing IDE debug event: ' + name);
            };
            const breakpoints = [
                new vscode.SourceBreakpoint(new vscode.Location(vscode.Uri.file(source), new vscode.Position(line('answer += 2;'), 0)), true, 'answer == 40'),
                new vscode.SourceBreakpoint(new vscode.Location(vscode.Uri.file(source), new vscode.Position(line('Console.WriteLine($"AFTER_AWAIT='), 0))),
            ];
            vscode.debug.addBreakpoints(breakpoints);
            try {
                const started = await timeout(vscode.debug.startDebugging(vscode.workspace.workspaceFolders[0], {
                    type: 'coreclr', name: 'netcoredbg editor net' + runtime, request: 'launch',
                    program: path.join(fixture, 'output', 'Probe.dll'), cwd: fixture,
                    stopAtEntry: false, justMyCode: true, console: 'internalConsole',
                }), 60000, 'IDE launch');
                assert(started);
                let stopped = await nextEvent('stopped');
                assert.equal(stopped.reason, 'breakpoint');
                let frames = (await session.customRequest('stackTrace', { threadId: stopped.threadId })).stackFrames;
                assert.equal(frames[0].line, line('answer += 2;') + 1);
                const scopes = (await session.customRequest('scopes', { frameId: frames[0].id })).scopes;
                const variables = (await Promise.all(scopes.map(scope => session.customRequest('variables', { variablesReference: scope.variablesReference })))).flatMap(r => r.variables);
                assert(variables.some(v => v.name === 'answer' && v.value === '40'));
                assert.equal((await session.customRequest('evaluate', { frameId: frames[0].id, expression: 'answer + 2', context: 'watch' })).result, '42');
                await session.customRequest('next', { threadId: stopped.threadId });
                stopped = await nextEvent('stopped');
                assert.equal(stopped.reason, 'step');
                await session.customRequest('continue', { threadId: stopped.threadId });
                stopped = await nextEvent('stopped');
                assert.equal(stopped.reason, 'breakpoint');
                frames = (await session.customRequest('stackTrace', { threadId: stopped.threadId })).stackFrames;
                assert.equal(frames[0].line, line('Console.WriteLine($"AFTER_AWAIT=') + 1);
                await session.customRequest('continue', { threadId: stopped.threadId });
                const exited = await nextEvent('exited');
                assert.equal(exited.exitCode, 0);
                await nextEvent('terminated');
                assert(output.includes('RUNTIME=.NET ' + runtime + '.'));
                assert(output.includes('ARCH=Arm64') && output.includes('DONE'));
                result.tests.push({ runtime, success: true, checks: ['IDE launch', 'conditional breakpoint', 'stack and variables', 'evaluate', 'step', 'post-await breakpoint', 'native runtime output and clean exit'], output });
            } finally {
                vscode.debug.removeBreakpoints(breakpoints);
                tracker.dispose();
                fs.writeFileSync(path.join(root, 'ide-net' + runtime + '.json'), JSON.stringify(trace, null, 2));
            }
        }
        result.success = true;
    } catch (error) {
        result.error = error.stack || String(error);
        throw error;
    } finally {
        if (session) await vscode.debug.stopDebugging(session);
        subscriptions.forEach(s => s.dispose());
        fs.writeFileSync(path.join(root, 'ide-result.json'), JSON.stringify(result, null, 2));
    }
};
