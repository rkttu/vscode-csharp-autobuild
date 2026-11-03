'use strict';

const crypto = require('node:crypto');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const COMMAND = 'netcoredbg.debugActiveFile';

function findDotnet(env = process.env, platform = process.platform) {
    const executable = platform === 'win32' ? 'dotnet.exe' : 'dotnet';
    const candidates = [];
    if (env.DOTNET_ROOT) candidates.push(path.join(env.DOTNET_ROOT, executable));
    for (let directory of (env.PATH || env.Path || '').split(path.delimiter)) {
        directory = directory.replace(/^"|"$/g, '');
        if (directory) candidates.push(path.join(directory, executable));
    }
    for (const candidate of candidates) {
        try {
            if (fs.statSync(candidate).isFile()) {
                const resolved = fs.realpathSync(candidate);
                return { executable: resolved, root: path.dirname(resolved) };
            }
        } catch (error) {
            if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error;
        }
    }
    throw new Error('Install a native .NET SDK and make dotnet available on PATH before debugging this file.');
}

function runProcess(executable, args, options = {}) {
    return new Promise((resolve, reject) => {
        const child = childProcess.execFile(executable, args, {
            cwd: options.cwd,
            env: { ...process.env, ...options.env, DOTNET_CLI_UI_LANGUAGE: 'en-US', MSBUILDDISABLENODEREUSE: '1' },
            signal: options.signal,
            windowsHide: true,
            timeout: 5 * 60 * 1000,
            maxBuffer: 8 * 1024 * 1024,
            encoding: 'utf8',
        }, (error, stdout, stderr) => {
            if (error) {
                error.stdout = stdout;
                error.stderr = stderr;
                reject(error);
            } else {
                resolve({ stdout, stderr, exitCode: 0 });
            }
        });
        if (options.onOutput) {
            child.stdout.on('data', options.onOutput);
            child.stderr.on('data', options.onOutput);
        }
    });
}

function stdout(result) {
    return typeof result === 'string' ? result : result.stdout;
}

function requireFileAppSdk(version) {
    const match = /^(\d+)\.(\d+)\.(\d+)(?:-([^\s]+))?/.exec(version.trim());
    if (!match || Number(match[1]) < 10 || (Number(match[1]) === 10 && Number(match[2]) === 0 &&
        (Number(match[3]) < 100 || (Number(match[3]) === 100 && match[4])))) {
        throw new Error(`File-based debugging requires .NET SDK 10.0.100 or newer. The source directory selected ${version.trim() || 'an unknown SDK'}. Check its global.json.`);
    }
}

function sdkArchitecture(info) {
    const match = /^\s*Architecture:\s*(arm64|x64|x86)\s*$/mi.exec(info);
    if (!match) throw new Error('Could not determine the selected .NET SDK architecture from dotnet --info.');
    return match[1].toLowerCase();
}

function insideDirectory(directory, candidate) {
    const relative = path.relative(path.resolve(directory), path.resolve(candidate));
    return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function activate(context, dependencies = {}) {
    const vscode = dependencies.vscode || require('vscode');
    const classifyFile = dependencies.classifyFile || require('./classify.cjs').classifyFile;
    const webSupport = dependencies.webSupport || require('./web.cjs');
    const environment = dependencies.env || process.env;
    const getDotnet = dependencies.findDotnet || (() => findDotnet(environment));
    const storage = (context.globalStorageUri || context.storageUri)?.fsPath;
    if (!storage) throw new Error('C# file debugging requires an extension storage directory.');
    const outputBase = path.resolve(storage, 'file-based-apps');
    const output = dependencies.output || vscode.window.createOutputChannel('C# File Debugging');
    const pending = new Map();
    const ownedOutputs = new Set();
    const controllers = new Set();
    const packagedTarget = context.extension?.packageJSON?.netcoredbgBuild?.target;
    const expectedArchitecture = packagedTarget ? (packagedTarget.endsWith('-arm64') ? 'arm64' : 'x64') : undefined;

    function showError(message) {
        // The notification promise settles on dismissal, which must not hold a file's pending operation.
        const failed = error => {
            try {
                output.appendLine(`Could not show error notification: ${error?.message || String(error)}`);
            } catch {
                // Notification delivery may finish after the extension's output channel is disposed.
            }
        };
        try {
            void Promise.resolve(vscode.window.showErrorMessage(message)).catch(failed);
        } catch (error) {
            failed(error);
        }
    }

    async function cleanup(directory) {
        // Only paths created by this controller may be removed. Never trust a session's field alone.
        if (!ownedOutputs.has(directory)) return;
        if (!insideDirectory(outputBase, directory)) throw new Error('Refusing to remove a file-app output outside extension storage.');
        ownedOutputs.delete(directory);
        try {
            await fs.promises.rm(directory, { recursive: true, force: true });
        } catch (error) {
            output.appendLine(`Could not clean file-app output ${directory}: ${error.message}`);
        }
    }

    const terminated = vscode.debug.onDidTerminateDebugSession(session => {
        const directory = session.configuration?.__netcoredbgFileAppOutput;
        if (typeof directory === 'string') void cleanup(directory);
    });

    async function debugFile(sourceUri, source, text) {
        const controller = new AbortController();
        controllers.add(controller);
        let generated;
        let handedToDebugger = false;
        try {
            return await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: 'Debug C# file',
                cancellable: true,
            }, async (progress, cancellation) => {
                const cancel = cancellation.onCancellationRequested(() => controller.abort());
                try {
                    if (cancellation.isCancellationRequested) controller.abort();
                    const selected = await getDotnet();
                    const runDotnet = async (args, options = {}) => {
                        const settings = { cwd: path.dirname(source), signal: controller.signal, ...options };
                        output.appendLine(`dotnet ${args.map(value => JSON.stringify(value)).join(' ')}`);
                        const result = dependencies.runDotnet ?
                            await dependencies.runDotnet(args, { ...settings, dotnetPath: selected.executable }) :
                            await runProcess(selected.executable, args, {
                                ...settings,
                                env: { ...environment, DOTNET_ROOT: selected.root },
                                onOutput: chunk => output.append(chunk.toString()),
                            });
                        if (result && typeof result !== 'string' && result.exitCode && result.exitCode !== 0) {
                            throw new Error(`dotnet exited with code ${result.exitCode}: ${result.stderr || result.stdout || ''}`);
                        }
                        return result;
                    };

                    progress.report({ message: 'Checking project membership' });
                    const classification = await classifyFile({
                        filePath: source,
                        text,
                        dotnetPath: selected.executable,
                        runDotnet,
                        signal: controller.signal,
                    });
                    controller.signal.throwIfAborted();
                    output.appendLine(`${source}: ${classification.kind} (${classification.reason})`);
                    if (classification.kind === 'project') {
                        return vscode.commands.executeCommand('workbench.action.debug.start');
                    }
                    if (classification.kind !== 'file') throw new Error('Could not classify the active C# file.');
                    requireFileAppSdk(stdout(await runDotnet(['--version'])));
                    const architecture = sdkArchitecture(stdout(await runDotnet(['--info'])));
                    if (expectedArchitecture && architecture !== expectedArchitecture) {
                        throw new Error(`The selected .NET SDK is ${architecture}, but this netcoredbg package requires ${expectedArchitecture}. Select a matching native SDK.`);
                    }
                    // The adapter itself also honors DOTNET_ROOT, so an invalid inherited root must not be hidden.
                    const comparable = value => {
                        let resolved;
                        try { resolved = fs.realpathSync(value); } catch { resolved = path.resolve(value); }
                        return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
                    };
                    if (environment.DOTNET_ROOT && comparable(environment.DOTNET_ROOT) !== comparable(selected.root)) {
                        throw new Error('DOTNET_ROOT does not identify the selected dotnet installation. Correct DOTNET_ROOT before debugging this file.');
                    }
                    const key = crypto.createHash('sha256').update(source).digest('hex').slice(0, 24);
                    const parent = path.join(outputBase, key);
                    await fs.promises.mkdir(parent, { recursive: true });
                    generated = await fs.promises.mkdtemp(path.join(parent, 'run-'));
                    ownedOutputs.add(generated);
                    progress.report({ message: 'Building file-based app' });
                    const buildResult = await runDotnet(['build', source, '--configuration', 'Debug', '--output', generated,
                        '-p:AssemblyName=FileApp', '-p:DebugType=portable', '-p:Optimize=false', '-p:PublishAot=false',
                        '-p:UseSharedCompilation=false', '--disable-build-servers', '--nologo',
                        '-target:Build', ...webSupport.BUILD_METADATA_ARGS]);
                    const program = path.join(generated, 'FileApp.dll');
                    await fs.promises.access(program);
                    await fs.promises.access(path.join(generated, 'FileApp.pdb'));
                    controller.signal.throwIfAborted();
                    progress.report({ message: 'Preparing web launch settings' });
                    const webLaunch = await webSupport.prepareWebLaunch({
                        source,
                        metadata: webSupport.parseBuildMetadata(stdout(buildResult)),
                        environment,
                        signal: controller.signal,
                        runDotnet,
                        vscode,
                        output,
                        onProgress: message => progress.report({ message }),
                    });
                    controller.signal.throwIfAborted();
                    if (webLaunch?.env?.DOTNET_ROOT && comparable(webLaunch.env.DOTNET_ROOT) !== comparable(selected.root)) {
                        throw new Error('The web launch profile DOTNET_ROOT does not identify the selected dotnet installation.');
                    }
                    progress.report({ message: 'Starting netcoredbg' });
                    const started = await vscode.debug.startDebugging(vscode.workspace.getWorkspaceFolder(sourceUri), {
                        name: `C#: ${path.basename(source)}`,
                        type: 'coreclr',
                        request: 'launch',
                        program,
                        cwd: path.dirname(source),
                        console: 'internalConsole',
                        stopAtEntry: false,
                        justMyCode: true,
                        targetArchitecture: architecture === 'arm64' ? 'arm64' : 'x86_64',
                        ...(webLaunch ? {
                            args: webLaunch.args,
                            serverReadyAction: webLaunch.serverReadyAction,
                            checkForDevCert: false,
                        } : {}),
                        env: { ...webLaunch?.env, DOTNET_ROOT: selected.root },
                        __netcoredbgFileAppOutput: generated,
                    });
                    handedToDebugger = started;
                    return started;
                } finally {
                    cancel.dispose();
                }
            });
        } catch (error) {
            if (error.name !== 'AbortError') {
                output.appendLine(error.stack || error.message || String(error));
                showError(`C# file debugging failed: ${error.message || error}. See the C# File Debugging output.`);
            }
            return false;
        } finally {
            controllers.delete(controller);
            if (generated && !handedToDebugger) await cleanup(generated);
        }
    }

    async function command() {
        if (vscode.workspace.isTrusted === false) {
            showError('Trust this workspace before building or debugging a C# file.');
            return false;
        }
        const document = vscode.window.activeTextEditor?.document;
        if (!document || document.uri.scheme !== 'file' || path.extname(document.uri.fsPath).toLowerCase() !== '.cs') {
            showError('Open a saved C# file before starting file debugging.');
            return false;
        }
        const source = path.resolve(document.uri.fsPath);
        if (pending.has(source)) return pending.get(source);
        const operation = (async () => {
            try {
                if (document.isDirty && !await document.save()) return false;
                return debugFile(document.uri, source, document.getText());
            } catch (error) {
                showError(`C# file debugging failed: ${error.message || error}.`);
                return false;
            }
        })();
        pending.set(source, operation);
        try {
            return await operation;
        } finally {
            pending.delete(source);
        }
    }

    const registered = vscode.commands.registerCommand(COMMAND, command);
    context.subscriptions.push(registered, terminated, output, {
        dispose() { for (const controller of controllers) controller.abort(); },
    });
    return { debugActiveFile: command };
}

module.exports = { activate, COMMAND, findDotnet, runProcess, requireFileAppSdk, sdkArchitecture };
