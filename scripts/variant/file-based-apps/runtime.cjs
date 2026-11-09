'use strict';

const crypto = require('node:crypto');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');

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
        let completion;
        let closed = false;
        const finish = () => {
            if (!closed || !completion) return;
            const { error, stdout, stderr } = completion;
            if (error) {
                error.stdout = stdout;
                error.stderr = stderr;
                reject(error);
            } else resolve({ stdout, stderr, exitCode: 0 });
        };
        const child = childProcess.execFile(executable, args, {
            cwd: options.cwd,
            env: { ...process.env, ...options.env, DOTNET_CLI_UI_LANGUAGE: 'en-US', MSBUILDDISABLENODEREUSE: '1' },
            signal: options.signal,
            windowsHide: true,
            timeout: 5 * 60 * 1000,
            maxBuffer: 8 * 1024 * 1024,
            encoding: 'utf8',
        }, (error, stdout, stderr) => {
            completion = { error, stdout, stderr };
            finish();
        });
        // An abort error can arrive before process/stdio close. Do not let callers clean output yet.
        child.once('close', () => { closed = true; finish(); });
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

async function createOutputDirectory(parent, { io = fs.promises, platform = process.platform,
    randomInt = crypto.randomInt, log = () => {} } = {}) {
    try {
        return await io.mkdtemp(path.join(parent, 'run-'));
    } catch (error) {
        if (platform !== 'win32' || error.code !== 'ENAMETOOLONG') throw error;
    }
    // Windows mkdtemp rejects some paths that ordinary mkdir can create. Keep
    // ordinary path spellings and the v1 journal's six-alphanumeric run name.
    // Exclusive creation establishes ownership; an existing path is never ours.
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let collision;
    for (let attempt = 0; attempt < 8; attempt++) {
        let suffix = '';
        for (let index = 0; index < 6; index++) suffix += alphabet[randomInt(alphabet.length)];
        const directory = path.join(parent, `run-${suffix}`);
        try {
            await io.mkdir(directory, { mode: 0o700 });
        } catch (error) {
            if (error.code !== 'EEXIST') throw error;
            collision = error;
            continue;
        }
        try { log(`Created Windows file-app output after mkdtemp ENAMETOOLONG: ${directory}`); }
        catch { /* Diagnostics must not abandon a successfully created output. */ }
        return directory;
    }
    throw collision;
}

function activate(context, dependencies = {}) {
    const vscode = dependencies.vscode || require('vscode');
    const classifyFile = dependencies.classifyFile || require('./classify.cjs').classifyFile;
    const webSupport = dependencies.webSupport || require('./web.cjs');
    const environment = dependencies.env || process.env;
    const getDotnet = dependencies.findDotnet || (() => findDotnet(environment));
    const removeOutput = dependencies.removeOutput || ((directory, options) => fs.promises.rm(directory, options));
    const now = dependencies.now || (() => performance.now());
    const preparationTimeoutMs = dependencies.preparationTimeoutMs ?? 5 * 60 * 1000;
    const handoffTimeoutMs = dependencies.handoffTimeoutMs ?? 5 * 60 * 1000;
    const saveTimeoutMs = dependencies.saveTimeoutMs ?? 5 * 60 * 1000;
    const webPreparationTimeoutMs = dependencies.webPreparationTimeoutMs ?? 5 * 60 * 1000;
    const scheduleTimeout = dependencies.scheduleTimeout || setTimeout;
    const cancelTimeout = dependencies.clearTimeout || clearTimeout;
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
    const pendingStarts = new Set();
    let disposed = false;
    let resourcesReleased = false;
    let recoveryInFlight;
    let resolveDisposal;
    const disposalReady = new Promise(resolve => { resolveDisposal = resolve; });
    const cleanupLog = message => {
        try { output.appendLine(message); } catch { /* Cleanup may outlive the output channel. */ }
    };
    const disposeResource = resource => {
        try { resource.dispose(); }
        catch (error) { cleanupLog(`Could not dispose file-app resource: ${error?.message || String(error)}`); }
    };
    function releaseDisposedResources() {
        // Graceful disposal can outlive the foreground command. Keep observing
        // exact owned launches until their outcome/termination is known.
        if (!disposed || resourcesReleased || pending.size || controllers.size || pendingStarts.size ||
            launches.size || cleanupInFlight.size || recoveryInFlight) return;
        resourcesReleased = true;
        disposeResource(startedSession);
        disposeResource(terminated);
        if (configurationTracker) disposeResource(configurationTracker);
        disposeResource(output);
        resolveDisposal();
    }
    const recovery = require('./recovery.cjs').createRecovery({
        baseDirectory: outputBase, removeOutput, isOwned: directory => ownedOutputs.has(directory), log: cleanupLog,
    });
    function startRecovery() {
        if (disposed) return Promise.resolve({ scanned: 0, attempted: 0, removed: 0 });
        if (recoveryInFlight) return recoveryInFlight;
        // Register drain ownership before I/O or a provider can reenter disposal.
        // A command arriving during this pass shares it without queuing a later pass.
        const operation = Promise.resolve().then(() => disposed
            ? { scanned: 0, attempted: 0, removed: 0 } : recovery.recover()).catch(error => {
            cleanupLog(`Could not recover terminal file-app outputs: ${error?.message || String(error)}`);
            return { scanned: 0, attempted: 0, removed: 0 };
        }).then(result => {
            cleanupLog(`Terminal output recovery: scanned=${result.scanned}, attempted=${result.attempted}, removed=${result.removed}`);
            return result;
        }).finally(() => {
            recoveryInFlight = undefined;
            releaseDisposedResources();
        });
        recoveryInFlight = operation;
        return operation;
    }
    const packagedTarget = context.extension?.packageJSON?.netcoredbgBuild?.target;
    const expectedArchitecture = packagedTarget ? (packagedTarget.endsWith('-arm64') ? 'arm64' : 'x64') : undefined;

    function showError(message) {
        if (disposed) return;
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
        // Establish drain ownership before a provider can reenter disposal.
        const operation = Promise.resolve().then(async () => {
            try {
                // Publish terminal ownership before the first recursive deletion. If this host
                // exits during that deletion, a fresh activation can recover the exact queued
                // output without inferring safety from a dead PID or an unmarked run path.
                if (!recovery.has(directory) && !await recovery.preserve(directory)) {
                    if (recovery.has(directory)) {
                        throw new Error('Terminal output recovery publication is incomplete; retained for retry');
                    }
                    try {
                        await fs.promises.lstat(directory);
                    } catch (error) {
                        if (error.code !== 'ENOENT') throw error;
                        ownedOutputs.delete(directory);
                        return; // Only confirmed absence can complete without a terminal receipt.
                    }
                    throw new Error('Could not publish terminal output recovery; existing output is retained for retry');
                }
                // The recovery module applies bounded filesystem retries to its fixed output child.
                if (!await recovery.remove(directory)) throw new Error('Terminal output recovery did not confirm deletion');
                ownedOutputs.delete(directory);
            } catch (error) {
                try { await recovery.preserve(directory); }
                catch (cause) { cleanupLog(`Could not persist terminal file-app output ${directory}: ${cause?.message || String(cause)}`); }
                failedCleanups.add(directory);
                cleanupLog(`Could not clean file-app output ${directory}: ${error?.message || String(error)}`);
            }
        });
        cleanupInFlight.set(directory, operation);
        try {
            await operation;
        } finally {
            cleanupInFlight.delete(directory);
            releaseDisposedResources();
        }
    }

    async function retryFailedCleanup() {
        // Do not compete with an existing pass or await it in the foreground.
        // Independent session termination still performs its own idempotent cleanup.
        if (recoveryInFlight || cleanupInFlight.size) return;
        // Start either one same-host retry (which can resume incomplete publication)
        // or one background recovery pass. A fresh command uses a distinct output
        // while cleanup retains drain/output ownership until actual settlement,
        // including any late failure. Do not add both attempts to a command.
        const directory = failedCleanups.values().next().value;
        if (directory !== undefined) void cleanup(directory).catch(error => {
            cleanupLog(`Could not retry terminal file-app output ${directory}: ${error?.message || String(error)}`);
        });
        else void startRecovery();
    }

    function matchesLaunch(session, launch) {
        const config = session.configuration;
        return session.type === 'coreclr' && config?.type === 'coreclr' &&
            config.__netcoredbgFileAppOutput === launch.directory && config.program === launch.program &&
            (!launch.session || launch.session.id === session.id);
    }

    function dispatchTerminalCleanup(directory) {
        // Register actual cleanup/drain ownership before releasing the foreground result.
        // Filesystem settlement may be indefinite; its late failure stays observed.
        void cleanup(directory).catch(error => {
            cleanupLog(`Could not finish terminal file-app output ${directory}: ${error?.message || String(error)}`);
        });
    }

    function finishLaunch(launch) {
        launch.terminal = true;
        launches.delete(launch.directory);
        dispatchTerminalCleanup(launch.directory);
    }

    async function requestCancelledStop(launch, session) {
        try {
            await vscode.debug.stopDebugging(session);
            // Acknowledgement is not termination, even after configuration.
        } catch (error) {
            if (launch.terminal) return;
            const message = `Could not stop the cancelled C# debug session "${session.name}": ${error?.message || String(error)}. Stop that session manually; its output has been preserved. See the C# File Debugging output.`;
            cleanupLog(`${message}\nSession: ${session.id}\nOutput: ${launch.directory}`);
            showError(message);
        }
    }

    function stopCancelledSession(launch) {
        if (!launch.session || launch.terminal) return;
        if (!launch.stopPromise) {
            const session = launch.session;
            // Assign before invoking the API so reentrant events cannot add Stops.
            launch.stopPromise = Promise.resolve().then(async () => {
                if (launch.terminal || !matchesLaunch(session, launch)) return;
                // Readiness can arrive between queueing and actual dispatch.
                launch.stoppedBeforeConfiguration = !launch.configuredSessions.has(session.id);
                await requestCancelledStop(launch, session);
            });
        }
        return launch.stopPromise;
    }

    function stopAfterConfiguration(launch, session) {
        if (!launch.cancelled || launch.terminal || !launch.stoppedBeforeConfiguration ||
            !launch.stopPromise || launch.configurationStopPromise) return;
        // An early Stop can be acknowledged before the adapter finishes
        // configuration. Permit one serialized exact-session follow-up only.
        launch.configurationStopPromise = launch.stopPromise.then(async () => {
            if (launch.terminal || !launch.cancelled || !matchesLaunch(session, launch)) return;
            cleanupLog(`Retrying cancelled C# session Stop after adapter configuration: ${session.id}`);
            await requestCancelledStop(launch, session);
        });
    }

    const configurationTracker = vscode.debug.registerDebugAdapterTrackerFactory?.('coreclr', {
        createDebugAdapterTracker(session) {
            const launch = launches.get(session.configuration?.__netcoredbgFileAppOutput);
            if (!launch || !matchesLaunch(session, launch)) return undefined;
            const requests = new Set();
            let exitedCode;
            let restartObserved = false;
            return {
                onWillReceiveMessage(message) {
                    if (message.type === 'request' && message.command === 'configurationDone' && Number.isSafeInteger(message.seq)) {
                        requests.add(message.seq);
                    }
                },
                onDidSendMessage(message) {
                    if (message.type === 'event' && ['exited', 'terminated'].includes(message.event)) {
                        // During editor shutdown the main-thread termination event may no
                        // longer arrive. Only this exact captured session's explicit debuggee
                        // exit followed by a non-restarting termination can substitute for it.
                        if (!disposed || !launch.cancelled || !launch.session || launch.terminal ||
                            launches.get(launch.directory) !== launch || !ownedOutputs.has(launch.directory) ||
                            !matchesLaunch(session, launch)) {
                            exitedCode = undefined;
                            return;
                        }
                        if (message.event === 'exited') {
                            const code = message.body?.exitCode;
                            exitedCode = !restartObserved && message.body && typeof message.body === 'object' && !Array.isArray(message.body) &&
                                Number.isInteger(code) && code >= -2147483648 && code <= 2147483647 ? code : undefined;
                            return;
                        }
                        const body = message.body;
                        const validBody = body === undefined || body !== null && typeof body === 'object' && !Array.isArray(body);
                        if (validBody && body && 'restart' in body) restartObserved = true;
                        const code = exitedCode;
                        exitedCode = undefined;
                        if (!validBody || restartObserved || code === undefined) return;
                        // finishLaunch marks terminal and removes the live launch before any
                        // await, so duplicate DAP events and a racing API event share cleanup.
                        void finishLaunch(launch);
                        cleanupLog(`Confirmed disposed C# session termination from paired DAP exited/terminated: ${session.id} (exitCode=${code})`);
                        return;
                    }
                    if (message.type !== 'response' || message.command !== 'configurationDone' ||
                        !requests.delete(message.request_seq) || message.success !== true) return;
                    if (launch.terminal || launches.get(launch.directory) !== launch || !matchesLaunch(session, launch)) return;
                    launch.configuredSessions.add(session.id);
                    stopAfterConfiguration(launch, session);
                },
            };
        },
    });

    const startedSession = vscode.debug.onDidStartDebugSession(session => {
        const launch = launches.get(session.configuration?.__netcoredbgFileAppOutput);
        if (!launch || launch.terminal || !matchesLaunch(session, launch)) return;
        launch.session = session;
        if (launch.unconfirmedNoted && !launch.confirmationNoted) {
            launch.confirmationNoted = true;
            cleanupLog(`Confirmed exact owned C# session start: ${session.id}; startRequest=${launch.startState}; output=${launch.directory}`);
        }
        if (launch.cancelled) void stopCancelledSession(launch);
    });
    const terminated = vscode.debug.onDidTerminateDebugSession(session => {
        const launch = launches.get(session.configuration?.__netcoredbgFileAppOutput);
        if (launch && matchesLaunch(session, launch)) void finishLaunch(launch);
    });

    async function startFileDebugging(folder, config, signal, checkpoint) {
        const launch = { directory: config.__netcoredbgFileAppOutput, program: config.program,
            cancelled: false, terminal: false, session: undefined, stopPromise: undefined, configuredSessions: new Set(),
            startState: 'pending', unconfirmedNoted: false, confirmationNoted: false };
        launches.set(launch.directory, launch);
        pendingStarts.add(launch);
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
            checkpoint();
            return vscode.debug.startDebugging(folder, config);
        }).then(started => {
            launch.startState = started ? 'accepted' : 'declined';
            if (started && !launch.session && !launch.terminal && !launch.unconfirmedNoted) {
                launch.unconfirmedNoted = true;
                cleanupLog(`Editor accepted C# launch; awaiting exact owned session start event; output retained: ${launch.directory}; program=${launch.program}; cancelled=${launch.cancelled}`);
            }
            if (!started && !launch.session) finishLaunch(launch);
            signal.throwIfAborted();
            return started;
        }, error => {
            launch.startState = 'rejected';
            if (!launch.session) finishLaunch(launch);
            signal.throwIfAborted();
            throw error;
        }).finally(() => {
            pendingStarts.delete(launch);
            releaseDisposedResources();
        });
        try {
            // Cancellation releases the command; the original start remains observed in the background.
            return await Promise.race([start, cancelled]);
        } finally {
            signal.removeEventListener('abort', abort);
        }
    }

    async function debugFile(document, source, settled) {
        const controller = new AbortController();
        controllers.add(controller);
        let generated;
        let launchOwnsOutput = false;
        let workStarted = false;
        let workSettled = false;
        let foregroundSettled = false;
        let workOutcome;
        let foregroundAbort;
        let closeForeground = () => {};
        const release = () => {
            if (!foregroundSettled || workStarted && !workSettled) return;
            controllers.delete(controller);
            settled();
            releaseDisposedResources();
        };
        const finishWork = () => {
            if (generated && !launchOwnsOutput) dispatchTerminalCleanup(generated);
            workSettled = true;
            release();
        };
        try {
            return await vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: 'Debug C# file',
                cancellable: true,
            }, (progress, cancellation) => {
              const task = (async () => {
                if (foregroundSettled) return false;
                let cancel;
                let progressActive = true;
                let delegatedProject = false;
                const began = now();
                let phase;
                let phaseBegan = began;
                let outcome = 'completed';
                let preparationActive = false;
                let preparationBegan;
                let timer;
                let handoffActive = false;
                let handoffBegan;
                let handoffTimer;
                let saveActive = false;
                let saveBegan;
                let saveTimer;
                let webOpen = false;
                let webRunning = false;
                let webSpent = 0;
                let webSegmentBegan;
                let webTimer;
                let webEpoch = 0;
                const webElapsed = () => webSpent + (webRunning ? now() - webSegmentBegan : 0);
                const expireWeb = elapsed => {
                    if (!webOpen || !webRunning || controller.signal.aborted) return;
                    const error = new Error(`Web preparation timed out during ${phase} after ${Math.round(elapsed)} ms of noninteractive work (limit ${webPreparationTimeoutMs} ms). Certificate consent and trust are excluded from this budget. Unfinished owned work remains observed; retry this file after its workflow drains`);
                    error.name = 'TimeoutError';
                    controller.abort(error);
                };
                const clearWebTimer = () => {
                    webEpoch++;
                    if (webTimer !== undefined) {
                        cancelTimeout(webTimer);
                        webTimer = undefined;
                    }
                };
                const stopWeb = () => {
                    webOpen = false;
                    webRunning = false;
                    clearWebTimer();
                };
                const armWebTimer = () => {
                    clearWebTimer();
                    const epoch = webEpoch;
                    webTimer = scheduleTimeout(() => {
                        if (!webOpen || !webRunning || epoch !== webEpoch || controller.signal.aborted) return;
                        const elapsed = webElapsed();
                        if (elapsed >= webPreparationTimeoutMs) expireWeb(elapsed);
                        else armWebTimer(); // An early callback must not shorten the active-time budget.
                    }, Math.max(0, Math.ceil(webPreparationTimeoutMs - webElapsed())));
                };
                const setWebNonInteractive = active => {
                    if (!webOpen) return; // Late helper callbacks cannot reopen a completed foreground budget.
                    controller.signal.throwIfAborted();
                    if (active === webRunning) { checkpoint(); return; }
                    const sampled = now();
                    if (!active) {
                        const elapsed = webSpent + sampled - webSegmentBegan;
                        if (elapsed >= webPreparationTimeoutMs) {
                            expireWeb(elapsed);
                            controller.signal.throwIfAborted();
                        }
                        webSpent = elapsed;
                        webRunning = false;
                        clearWebTimer();
                    } else {
                        webRunning = true;
                        webSegmentBegan = sampled;
                        armWebTimer();
                    }
                };
                const expire = () => {
                    if (!preparationActive || controller.signal.aborted) return;
                    const error = new Error(`Preparation timed out during ${phase || 'SDK discovery'} after ${Math.round(now() - preparationBegan)} ms (limit ${preparationTimeoutMs} ms). Check project evaluation, SDK and restore output before retrying`);
                    error.name = 'TimeoutError';
                    controller.abort(error);
                };
                const expireHandoff = () => {
                    if (!handoffActive || controller.signal.aborted) return;
                    const error = new Error(`Debugger handoff timed out during Starting netcoredbg after ${Math.round(now() - handoffBegan)} ms (limit ${handoffTimeoutMs} ms). Check C# and Debug Console output. Uncertain start requests remain tracked; late owned sessions are stopped and output is retained until safely terminal`);
                    error.name = 'TimeoutError';
                    controller.abort(error);
                };
                const expireSave = () => {
                    if (!saveActive || controller.signal.aborted) return;
                    const error = new Error(`Editor save timed out during Saving C# file after ${Math.round(now() - saveBegan)} ms (limit ${saveTimeoutMs} ms). The underlying editor save may still finish and remains observed. This file cannot start another save or build until it settles`);
                    error.name = 'TimeoutError';
                    controller.abort(error);
                };
                const checkpoint = () => {
                    if (preparationActive && now() - preparationBegan >= preparationTimeoutMs) expire();
                    if (handoffActive && now() - handoffBegan >= handoffTimeoutMs) expireHandoff();
                    if (saveActive && now() - saveBegan >= saveTimeoutMs) expireSave();
                    if (webOpen && webRunning) {
                        const elapsed = webElapsed();
                        if (elapsed >= webPreparationTimeoutMs) expireWeb(elapsed);
                    }
                    controller.signal.throwIfAborted();
                };
                const stopPreparation = () => {
                    preparationActive = false;
                    if (timer !== undefined) {
                        cancelTimeout(timer);
                        timer = undefined;
                    }
                };
                const stopHandoff = () => {
                    handoffActive = false;
                    if (handoffTimer !== undefined) {
                        cancelTimeout(handoffTimer);
                        handoffTimer = undefined;
                    }
                };
                const stopSave = () => {
                    saveActive = false;
                    if (saveTimer !== undefined) {
                        cancelTimeout(saveTimer);
                        saveTimer = undefined;
                    }
                };
                const phaseLog = message => {
                    try { output.appendLine(message); } catch { /* Diagnostics must not replace the operation result. */ }
                };
                const logPhase = status => {
                    if (phase) phaseLog(`Phase ${status}: ${phase} (${Math.round(now() - phaseBegan)} ms; total ${Math.round(now() - began)} ms)`);
                };
                const setPhase = name => {
                    checkpoint();
                    logPhase('completed');
                    phase = name;
                    phaseBegan = now();
                    phaseLog(`Phase started: ${phase}`);
                    if (progressActive) progress.report({ message: phase });
                    checkpoint();
                };
                let rejectCancelled;
                const cancelled = new Promise((_resolve, reject) => { rejectCancelled = reject; });
                const abortForeground = () => {
                    // A completed workflow wins over later UI cancellation. Existing project
                    // delegation has no owned-session contract, so its dispatched API must settle.
                    if (workOutcome || delegatedProject || foregroundAbort) return;
                    foregroundAbort = controller.signal.reason;
                    outcome = foregroundAbort?.name === 'TimeoutError' ? 'timed out' :
                        foregroundAbort?.name === 'AbortError' ? 'cancelled' : 'failed';
                    stopPreparation();
                    stopHandoff();
                    stopSave();
                    stopWeb();
                    logPhase(outcome);
                    phaseLog(launchOwnsOutput ?
                        `Foreground ${outcome} during ${phase}; uncertain debugger starts remain tracked and their output is retained until safely terminal. A distinct retry can start after this foreground workflow drains, while an earlier request is still pending.` :
                        `Foreground ${outcome} during ${phase || 'C# file preparation'}; unfinished work remains observed. This file cannot retry until that work settles.`);
                    // Cancellation can fall between a successful editor handoff and the
                    // caller resuming. Retain the existing exact-session Stop/termination path.
                    const launch = launchOwnsOutput && launches.get(generated);
                    if (launch && !launch.terminal) {
                        launch.cancelled = true;
                        void stopCancelledSession(launch);
                    }
                    rejectCancelled(foregroundAbort);
                };
                closeForeground = () => {
                    if (!progressActive) return;
                    progressActive = false;
                    stopPreparation();
                    stopHandoff();
                    stopSave();
                    stopWeb();
                    controller.signal.removeEventListener('abort', abortForeground);
                    if (cancel) disposeResource(cancel);
                };
                // Observe both results before a cancellation/provider callback can reenter.
                workStarted = true;
                const work = Promise.resolve().then(async () => {
                  try {
                    if (cancellation.isCancellationRequested || disposed) controller.abort();
                    checkpoint();
                    const sourceUri = document.uri;
                    if (document.isDirty) {
                        saveBegan = now();
                        saveActive = true;
                        saveTimer = scheduleTimeout(expireSave, saveTimeoutMs);
                        setPhase('Saving C# file');
                        // The editor save API has no cancellation token. Keep this exact
                        // save coalesced and observed until settlement; Cancel stops its
                        // continuation without pretending the editor finished saving.
                        checkpoint();
                        const saved = await document.save();
                        checkpoint();
                        stopSave();
                        if (!saved) { outcome = 'not saved'; return false; }
                    }
                    const text = document.getText();
                    checkpoint();
                    // Editor-owned save time is visible in total phase duration but
                    // does not consume the noninteractive SDK preparation budget.
                    preparationBegan = now();
                    preparationActive = true;
                    setPhase('Locating .NET SDK');
                    timer = scheduleTimeout(expire, preparationTimeoutMs);
                    checkpoint();
                    const selected = await getDotnet();
                    checkpoint();
                    const runDotnet = async (args, options = {}) => {
                        checkpoint();
                        const settings = { cwd: path.dirname(source), signal: controller.signal, ...options };
                        phaseLog(`dotnet ${args.map(value => JSON.stringify(value)).join(' ')}`);
                        checkpoint();
                        let streamOutputFailureReported = false;
                        const result = dependencies.runDotnet ?
                            await dependencies.runDotnet(args, { ...settings, dotnetPath: selected.executable }) :
                            await runProcess(selected.executable, args, {
                                ...settings,
                                env: { ...environment, DOTNET_ROOT: selected.root },
                                onOutput: chunk => {
                                    try { output.append(chunk.toString()); }
                                    catch {
                                        if (streamOutputFailureReported) return;
                                        streamOutputFailureReported = true;
                                        phaseLog('Could not write .NET process output; process completion is still being observed.');
                                    }
                                },
                            });
                        checkpoint();
                        if (result && typeof result !== 'string' && result.exitCode && result.exitCode !== 0) {
                            throw new Error(`dotnet exited with code ${result.exitCode}: ${result.stderr || result.stdout || ''}`);
                        }
                        return result;
                    };

                    setPhase('Checking project membership');
                    const classification = await classifyFile({
                        filePath: source,
                        text,
                        dotnetPath: selected.executable,
                        runDotnet,
                        signal: controller.signal,
                    });
                    checkpoint();
                    phaseLog(`${source}: ${classification.kind} (${classification.reason})`);
                    if (classification.kind === 'project') {
                        stopPreparation();
                        setPhase('Starting selected project configuration');
                        delegatedProject = true;
                        return await vscode.commands.executeCommand('workbench.action.debug.start');
                    }
                    if (classification.kind !== 'file') throw new Error('Could not classify the active C# file.');
                    setPhase('Checking .NET SDK');
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
                    setPhase('Preparing build output');
                    const key = crypto.createHash('sha256').update(source).digest('hex').slice(0, 24);
                    const parent = path.join(outputBase, key);
                    await fs.promises.mkdir(parent, { recursive: true });
                    generated = await createOutputDirectory(parent, { log: cleanupLog });
                    ownedOutputs.add(generated);
                    setPhase('Building file-based app');
                    const buildResult = await runDotnet(['build', source, '--configuration', 'Debug', '--output', generated,
                        '-p:AssemblyName=FileApp', '-p:DebugType=portable', '-p:Optimize=false', '-p:PublishAot=false',
                        '-p:UseSharedCompilation=false', '--disable-build-servers', '--nologo',
                        '-target:Build', ...webSupport.BUILD_METADATA_ARGS]);
                    const program = path.join(generated, 'FileApp.dll');
                    await fs.promises.access(program);
                    await fs.promises.access(path.join(generated, 'FileApp.pdb'));
                    checkpoint();
                    // Certificate consent, OS trust and editor-owned launches do not use this deadline.
                    stopPreparation();
                    setPhase('Preparing web launch settings');
                    const metadata = webSupport.parseBuildMetadata(stdout(buildResult));
                    if (metadata?.isWebServer) {
                        webOpen = true;
                        webRunning = true;
                        webSegmentBegan = now();
                        armWebTimer();
                    }
                    checkpoint();
                    const webLaunch = await webSupport.prepareWebLaunch({
                        source,
                        metadata,
                        environment,
                        signal: controller.signal,
                        runDotnet,
                        vscode,
                        output,
                        onProgress: setPhase,
                        onNonInteractive: setWebNonInteractive,
                    });
                    checkpoint();
                    stopWeb();
                    if (phase !== 'Preparing web launch settings') setPhase('Preparing web launch settings');
                    if (webLaunch?.env?.DOTNET_ROOT && comparable(webLaunch.env.DOTNET_ROOT) !== comparable(selected.root)) {
                        throw new Error('The web launch profile DOTNET_ROOT does not identify the selected dotnet installation.');
                    }
                    handoffBegan = now();
                    handoffActive = true;
                    handoffTimer = scheduleTimeout(expireHandoff, handoffTimeoutMs);
                    setPhase('Starting netcoredbg');
                    const folder = vscode.workspace.getWorkspaceFolder(sourceUri);
                    const configuration = {
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
                    };
                    checkpoint();
                    // Transfer only after argument preparation and its cancellation checks.
                    launchOwnsOutput = true;
                    const started = await startFileDebugging(folder, configuration, controller.signal, checkpoint);
                    checkpoint();
                    stopHandoff();
                    if (!started) {
                        controller.signal.throwIfAborted();
                        throw new Error('The editor did not start the netcoredbg debug session. Check C# and Debug Console output for details before retrying');
                    }
                    return started;
                  } catch (error) {
                    const failure = controller.signal.aborted ? controller.signal.reason : error;
                    if (failure !== error && error?.name !== 'AbortError') {
                        phaseLog(`Error observed during ${phase} after cancellation: ${error?.stack || error?.message || String(error)}`);
                    }
                    outcome = failure?.name === 'TimeoutError' ? 'timed out' : failure?.name === 'AbortError' ? 'cancelled' : 'failed';
                    throw failure;
                  } finally {
                    stopPreparation();
                    stopHandoff();
                    stopSave();
                    stopWeb();
                    logPhase(foregroundAbort ? `drained after ${outcome}` : outcome);
                  }
                }).then(value => {
                    if (foregroundAbort) {
                        workOutcome = { error: foregroundAbort };
                        finishWork();
                        throw foregroundAbort;
                    }
                    workOutcome = { value };
                    finishWork();
                    return value;
                }, error => {
                    workOutcome = { error };
                    finishWork();
                    throw error;
                });
                const result = Promise.race([work, cancelled]);
                void result.catch(() => {});
                controller.signal.addEventListener('abort', abortForeground, { once: true });
                try {
                    cancel = cancellation.onCancellationRequested(() => {
                        if (!workOutcome) controller.abort();
                    });
                    if (cancellation.isCancellationRequested || disposed) controller.abort();
                    if (controller.signal.aborted) abortForeground();
                    return await result;
                } catch (error) {
                    if (!controller.signal.aborted) controller.abort(error);
                    throw error;
                } finally { closeForeground(); }
              })();
              void task.catch(() => {});
              return task;
            });
        } catch (error) {
            // A late UI-provider error cannot turn a completed launch into a false
            // cancellation result while leaving its captured session running.
            if (foregroundAbort) {
                if (error !== foregroundAbort) cleanupLog(`Progress provider failed after foreground ${foregroundAbort.name}: ${error?.message || String(error)}`);
                error = foregroundAbort;
            } else if (workOutcome) {
                if (!('error' in workOutcome)) {
                    cleanupLog(`Progress provider failed after C# workflow completion: ${error?.message || String(error)}`);
                    return workOutcome.value;
                }
                error = workOutcome.error;
            } else if (!controller.signal.aborted) controller.abort(error);
            if (error.name !== 'AbortError') {
                cleanupLog(error.stack || error.message || String(error));
                showError(`C# file debugging failed: ${error.message || error}. See the C# File Debugging output.`);
            }
            return false;
        } finally {
            closeForeground();
            foregroundSettled = true;
            release();
        }
    }

    async function command() {
        if (disposed) return false;
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
        // Register pending ownership before invoking callbacks that can dispose
        // this activation reentrantly, including save and cleanup providers.
        let transferred = false;
        const settled = () => {
            if (pending.get(source) === operation) pending.delete(source);
            releaseDisposedResources();
        };
        const operation = Promise.resolve().then(async () => {
            try {
                if (disposed) return false;
                await retryFailedCleanup();
                if (disposed) return false;
                transferred = true;
                return debugFile(document, source, settled);
            } catch (error) {
                cleanupLog(error.stack || error.message || String(error));
                showError(`C# file debugging failed: ${error.message || error}.`);
                return false;
            } finally { if (!transferred) settled(); }
        });
        pending.set(source, operation);
        return await operation;
    }

    const registered = vscode.commands.registerCommand(COMMAND, command);
    function dispose() {
        if (!disposed) {
            disposed = true;
            disposeResource(registered);
            for (const controller of controllers) controller.abort();
            for (const launch of launches.values()) {
                launch.cancelled = true;
                cleanupLog(`Retained C# launch during disposal: startRequest=${launch.startState}; session=${launch.session?.id || 'not observed'}; output=${launch.directory}. Pending start results or exact termination remain required; output is preserved.`);
                void stopCancelledSession(launch);
            }
            releaseDisposedResources();
        }
        return disposalReady;
    }
    context.subscriptions.push({ dispose });
    // Recover validated terminal receipts without holding activation or a file command pending.
    const recoveryReady = startRecovery();
    return { debugActiveFile: command, recoveryReady, dispose, disposalReady };
}

module.exports = { activate, COMMAND, findDotnet, runProcess, requireFileAppSdk, sdkArchitecture, createOutputDirectory };
