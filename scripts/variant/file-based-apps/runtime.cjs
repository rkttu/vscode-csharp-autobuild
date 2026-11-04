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
    const removeOutput = dependencies.removeOutput || ((directory, options) => fs.promises.rm(directory, options));
    const storage = (context.globalStorageUri || context.storageUri)?.fsPath;
    if (!storage) throw new Error('C# file debugging requires an extension storage directory.');
    const outputBase = path.resolve(storage, 'file-based-apps');
    const output = dependencies.output || vscode.window.createOutputChannel('C# File Debugging');
    const pending = new Map();
    const ownedOutputs = new Set();
    const failedCleanups = new Set();
    const cleanupInFlight = new Map();
    const launches = new Map();
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
        // Refuse unsafe paths without rejecting the fire-and-forget termination callback.
        if (!insideDirectory(outputBase, directory)) return;
        if (cleanupInFlight.has(directory)) return cleanupInFlight.get(directory);
        failedCleanups.delete(directory);
        const operation = (async () => {
            try {
                // Node retries transient busy/permission errors with linear backoff, at most three times.
                await removeOutput(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 50 });
                ownedOutputs.delete(directory);
            } catch (error) {
                failedCleanups.add(directory);
                try {
                    output.appendLine(`Could not clean file-app output ${directory}: ${error?.message || String(error)}`);
                } catch {
                    // Cleanup may finish after the extension's output channel is disposed.
                }
            }
        })();
        cleanupInFlight.set(directory, operation);
        try {
            await operation;
        } finally {
            cleanupInFlight.delete(directory);
        }
    }

    async function retryFailedCleanup() {
        // Retry one terminal output per command. Never sweep outputs belonging to live sessions.
        const directory = failedCleanups.values().next().value;
        if (directory !== undefined) await cleanup(directory);
    }

    function matchesLaunch(session, launch) {
        const config = session.configuration;
        return session.type === 'coreclr' && config?.type === 'coreclr' &&
            config.__netcoredbgFileAppOutput === launch.directory && config.program === launch.program &&
            (!launch.session || launch.session.id === session.id);
    }

    async function finishLaunch(launch) {
        launch.terminal = true;
        launches.delete(launch.directory);
        await cleanup(launch.directory);
    }

    function stopCancelledSession(launch) {
        if (!launch.session || launch.terminal) return;
        if (!launch.stopPromise) {
            // Schedule after assigning the promise so reentrant events cannot request a second stop.
            launch.stopPromise = Promise.resolve().then(async () => {
                if (launch.terminal) return;
                try {
                    await vscode.debug.stopDebugging(launch.session);
                    // The editor can resolve stop before emitting termination. Keep output until that event.
                } catch (error) {
                    if (launch.terminal) return;
                    const message = `Could not stop the cancelled C# debug session "${launch.session.name}": ${error?.message || String(error)}. Stop that session manually; its output has been preserved. See the C# File Debugging output.`;
                    try { output.appendLine(`${message}\nSession: ${launch.session.id}\nOutput: ${launch.directory}`); } catch { /* The output channel may already be disposed. */ }
                    showError(message);
                }
            });
        }
        return launch.stopPromise;
    }

    const startedSession = vscode.debug.onDidStartDebugSession(session => {
        const launch = launches.get(session.configuration?.__netcoredbgFileAppOutput);
        if (!launch || launch.terminal || !matchesLaunch(session, launch)) return;
        launch.session = session;
        if (launch.cancelled) void stopCancelledSession(launch);
    });
    const terminated = vscode.debug.onDidTerminateDebugSession(session => {
        const launch = launches.get(session.configuration?.__netcoredbgFileAppOutput);
        if (launch && matchesLaunch(session, launch)) void finishLaunch(launch);
    });

    async function startFileDebugging(folder, config, signal) {
        const launch = { directory: config.__netcoredbgFileAppOutput, program: config.program,
            cancelled: false, terminal: false, session: undefined, stopPromise: undefined };
        launches.set(launch.directory, launch);
        let abort;
        const cancelled = new Promise((_resolve, reject) => {
            abort = () => {
                launch.cancelled = true;
                void stopCancelledSession(launch);
                reject(signal.reason);
            };
            signal.addEventListener('abort', abort, { once: true });
            if (signal.aborted) abort();
        });
        const start = Promise.resolve().then(() => {
            signal.throwIfAborted();
            return vscode.debug.startDebugging(folder, config);
        }).then(async started => {
            if (!started && !launch.session) await finishLaunch(launch);
            signal.throwIfAborted();
            return started;
        }, async error => {
            if (!launch.session) await finishLaunch(launch);
            signal.throwIfAborted();
            throw error;
        });
        try {
            // Cancellation releases the command; the original start remains observed in the background.
            return await Promise.race([start, cancelled]);
        } finally {
            signal.removeEventListener('abort', abort);
        }
    }

    async function debugFile(sourceUri, source, text) {
        const controller = new AbortController();
        controllers.add(controller);
        let generated;
        let launchOwnsOutput = false;
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
                    // From here the launch tracker owns cleanup, including results arriving after cancellation.
                    launchOwnsOutput = true;
                    const started = await startFileDebugging(vscode.workspace.getWorkspaceFolder(sourceUri), {
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
                    }, controller.signal);
                    if (!started) {
                        controller.signal.throwIfAborted();
                        throw new Error('The editor did not start the netcoredbg debug session. Check C# and Debug Console output for details before retrying');
                    }
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
            if (generated && !launchOwnsOutput) await cleanup(generated);
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
                await retryFailedCleanup();
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
    context.subscriptions.push(registered, startedSession, terminated, output, {
        dispose() { for (const controller of controllers) controller.abort(); },
    });
    return { debugActiveFile: command };
}

module.exports = { activate, COMMAND, findDotnet, runProcess, requireFileAppSdk, sdkArchitecture };
