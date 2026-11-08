'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { getEventListeners } = require('node:events');
const fs = require('node:fs');
const profileIO = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const util = require('node:util');
const { BUILD_METADATA_ARGS, parseBuildMetadata, prepareWebLaunch } = require('./web.cjs');

function metadata(properties = {}, references = []) {
    return { Properties: { UsingMicrosoftNETSdkWeb: 'true', UsingMicrosoftNETSdkWorker: '', OutputType: 'Exe',
        TargetFrameworkIdentifier: '.NETCoreApp', TargetPlatformIdentifier: '', ...properties },
    Items: { FrameworkReference: references.map(Identity => ({ Identity })) } };
}

function fixture(t, options = {}) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'netcoredbg-web-'));
    t.after(() => {
        assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
        assert(path.basename(root).startsWith('netcoredbg-web-'));
        fs.rmSync(root, { recursive: true, force: true });
    });
    const source = path.join(root, 'original name.cs');
    fs.writeFileSync(source, '#:sdk Microsoft.NET.Sdk.Web\n');
    const calls = { processes: [], prompts: [], output: [], progress: [] };
    const input = {
        source, metadata: parseBuildMetadata(JSON.stringify(metadata())), environment: {},
        signal: options.signal,
        runDotnet: async (args, settings) => {
            calls.processes.push({ args, settings });
            return options.runDotnet ? options.runDotnet(args, settings, calls) : { stdout: '', exitCode: 0 };
        },
        vscode: { window: { showWarningMessage: (...args) => {
            calls.prompts.push(args);
            return options.prompt ? options.prompt(...args) : Promise.resolve('Cancel');
        } } },
        output: { appendLine: value => calls.output.push(value) },
        onProgress: value => calls.progress.push(value),
    };
    const write = (profiles, conventional = false) => {
        const filename = conventional ? path.join(root, 'Properties', 'launchSettings.json') : path.join(root, 'original name.run.json');
        fs.mkdirSync(path.dirname(filename), { recursive: true });
        fs.writeFileSync(filename, typeof profiles === 'string' ? profiles : JSON.stringify({ profiles }));
    };
    return { root, source, calls, input, write, prepare: () => prepareWebLaunch(input) };
}

// Run through the public module in a strict child so a rejected original prompt
// fails one parent assertion rather than escaping the test worker's lifecycle.
async function certificatePromptProbe() {
    const assert = require('node:assert/strict');
    const { getEventListeners } = require('node:events');
    const { prepareWebLaunch } = require(process.argv[1]);
    const controller = new AbortController();
    const mode = process.argv[3];
    const failure = new Error('Original certificate prompt rejected after cancellation');
    let processes = 0, prompts = 0;
    const operation = prepareWebLaunch({
        source: process.argv[2], metadata: { isWebServer: true }, environment: {}, signal: controller.signal,
        runDotnet: async () => { processes++; return { exitCode: 7 }; },
        vscode: { window: { showWarningMessage() {
            prompts++;
            if (mode === 'thenable') return { get then() {
                controller.abort();
                return (_resolve, reject) => setImmediate(() => reject(failure));
            } };
            controller.abort();
            return mode === 'immediate' ? Promise.reject(failure) :
                new Promise((_resolve, reject) => setImmediate(() => reject(failure)));
        } } },
    });
    await assert.rejects(operation, { name: 'AbortError' });
    // Flush the original rejection after the cancelled public operation returns.
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(prompts, 1);
    assert.equal(processes, 1, 'Cancellation must not authorize certificate trust');
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
    process.stdout.write(JSON.stringify({ mode, prompts, processes, cancelled: true }) + '\n');
}

test('metadata extracts build JSON around banners and unrelated JSON', () => {
    assert(BUILD_METADATA_ARGS.includes('-getItem:FrameworkReference'));
    const value = parseBuildMetadata('restore {not json}\n{"unrelated":1}\n' + JSON.stringify(metadata()) + '\nBuild succeeded.');
    assert.equal(value.isWebServer, true);
    assert.equal(value.properties.UsingMicrosoftNETSdkWeb, 'true');
    assert.throws(() => parseBuildMetadata('Build succeeded.'), /metadata/);
});

test('only executable managed server metadata qualifies, including inherited ASP.NET reference', () => {
    const cases = [
        [{ OutputType: 'Library' }, [], false],
        [{ TargetPlatformIdentifier: 'browser' }, [], false],
        [{ TargetFrameworkIdentifier: '.NETFramework' }, [], false],
        [{ UsingMicrosoftNETSdkWeb: '' }, [], false],
        [{ UsingMicrosoftNETSdkWeb: '', UsingMicrosoftNETSdkRazor: 'true', OutputType: 'Library' }, [], false],
        [{ UsingMicrosoftNETSdkWeb: '' }, ['Microsoft.AspNetCore.App'], true],
        [{ UsingMicrosoftNETSdkWeb: '', UsingMicrosoftNETSdkWorker: 'true' }, ['Microsoft.AspNetCore.App'], false],
    ];
    for (const [properties, references, expected] of cases) assert.equal(parseBuildMetadata(JSON.stringify(metadata(properties, references))).isWebServer, expected);
});

test('non-Web launch does not read profiles or run certificate commands', async t => {
    const f = fixture(t);
    f.input.metadata.isWebServer = false;
    f.write('not JSON');
    assert.equal(await f.prepare(), undefined);
    assert.deepEqual(f.calls.processes, []);
});

test('JSONC preserves string contents, comments, trailing commas and source basename', async t => {
    const f = fixture(t);
    f.write(`{
        // source-adjacent profile
        "profiles": {"Local": {"commandName": "Project", "applicationUrl": "http://localhost:5017",
          "environmentVariables": {"LITERAL": "a,} // /* b",}, /* comma followed by comment */
          "launchBrowser": true,
        },},
    }`);
    const result = await f.prepare();
    assert.equal(result.profileName, 'Local');
    assert.equal(result.env.LITERAL, 'a,} // /* b');
    assert.equal(result.requiresHttps, false);
    assert.equal(result.checkForDevCert, false);
    assert(result.serverReadyAction);
    assert.deepEqual(f.calls.processes, []);
});

test('conventional launchSettings wins and first Project profile is selected', async t => {
    const f = fixture(t);
    f.write({ Adjacent: { commandName: 'Project', applicationUrl: 'https://localhost:5001' } });
    f.write({ IIS: { commandName: 'IISExpress' }, First: { commandName: 'Project', applicationUrl: 'http://localhost:5021' }, Second: { commandName: 'Project' } }, true);
    const result = await f.prepare();
    assert.equal(result.profileName, 'First');
    assert.equal(result.env.ASPNETCORE_URLS, 'http://localhost:5021');
    assert(f.calls.output.some(line => /ignored/.test(line)));
    assert.deepEqual(f.calls.processes, []);
});

test('unsupported or malformed profiles fail instead of synthesizing a profile', async t => {
    const f = fixture(t);
    f.write({ Other: { commandName: 'Executable', executablePath: 'something' } });
    await assert.rejects(f.prepare(), /No supported Project/);
    f.write('{"profiles":');
    await assert.rejects(f.prepare(), /Could not read launch profile/);
    assert.deepEqual(f.calls.processes, []);
});

test('profile explicit environment overrides applicationUrl and browser false/absent is honored', async t => {
    const f = fixture(t);
    for (const launchBrowser of [false, undefined]) {
        f.write({ Profile: { commandName: 'Project', applicationUrl: 'https://localhost:5001', launchBrowser,
            environmentVariables: { ASPNETCORE_URLS: 'http://localhost:5080', CUSTOM: 'from profile' } } });
        const result = await f.prepare();
        assert.equal(result.env.ASPNETCORE_URLS, 'http://localhost:5080');
        assert.equal(result.env.DOTNET_LAUNCH_PROFILE, 'Profile');
        assert.equal(result.serverReadyAction, undefined);
        assert.equal(result.requiresHttps, false);
    }
    assert.deepEqual(f.calls.processes, []);
});

test('profile arguments use structured ProcessStartInfo quoting without shell expansion', async t => {
    const f = fixture(t);
    f.write({ Arguments: { commandName: 'Project', commandLineArgs: '"two words" "" C:\\data\\file.txt "a\\\"b" "quoted""quote" ; $(secret)\tlast' } });
    const result = await f.prepare();
    assert.deepEqual(result.args, ['two words', '', 'C:\\data\\file.txt', 'a"b', 'quoted"quote', ';', '$(secret)', 'last']);
    assert.deepEqual(f.calls.processes, []);
});

test('profile environment values expand ambient percent variables once without shell or argument expansion', async t => {
    const f = fixture(t);
    f.input.environment = { USERPROFILE: 'C:\\Users\\example', LOCAL_WEB_URL: 'https://localhost:7011', NESTED: '%USERPROFILE%', EMPTY: '' };
    f.write({ Expanded: { commandName: 'Project', commandLineArgs: '%USERPROFILE% $(secret)', environmentVariables: {
        DATA: '%USERPROFILE%\\data', UNKNOWN: '%MISSING%', NESTED: '%NESTED%', EMPTY: 'before%EMPTY%after',
        ASPNETCORE_URLS: '%LOCAL_WEB_URL%', LITERAL: '$(secret) ${USERPROFILE}',
        PREVIOUS: 'new profile value', FROM_PREVIOUS: '%PREVIOUS%', CASE: '%userprofile%',
    } } });
    const result = await f.prepare();
    assert.equal(result.env.DATA, 'C:\\Users\\example\\data');
    assert.equal(result.env.UNKNOWN, '%MISSING%');
    assert.equal(result.env.NESTED, '%USERPROFILE%');
    assert.equal(result.env.EMPTY, 'beforeafter');
    assert.equal(result.env.LITERAL, '$(secret) ${USERPROFILE}');
    assert.equal(result.env.FROM_PREVIOUS, '%PREVIOUS%');
    assert.equal(result.env.CASE, process.platform === 'win32' ? 'C:\\Users\\example' : '%userprofile%');
    assert.deepEqual(result.args, ['%USERPROFILE%', '$(secret)']);
    assert.equal(result.requiresHttps, true);
    assert.equal(f.calls.processes.length, 1);
});

test('relative and absolute launch URLs match built-in uriFormat rules', async t => {
    const f = fixture(t);
    f.write({ Local: { commandName: 'Project', launchBrowser: true, launchUrl: 'docs?q=100%25&literal=%s' } });
    let result = await f.prepare();
    assert.equal(result.serverReadyAction.uriFormat.split('%s').length, 2);
    assert.equal(util.format(result.serverReadyAction.uriFormat, 'http://localhost:5010'), 'http://localhost:5010/docs?q=100%25&literal=%25s');
    f.write({ Local: { commandName: 'Project', launchBrowser: true, launchUrl: 'https://example.test/docs?q=%20' } });
    result = await f.prepare();
    const match = new RegExp(result.serverReadyAction.pattern).exec('Now listening on: http://localhost:5000');
    assert.equal(match.length, 1, 'a fixed absolute URI must not capture a substitution');
    assert.equal(result.serverReadyAction.uriFormat, 'https://example.test/docs?q=%20');
    f.write({ Local: { commandName: 'Project', launchBrowser: true, launchUrl: 'https://example.test/docs?literal=%s' } });
    result = await f.prepare();
    assert.equal(result.serverReadyAction.uriFormat, 'https://example.test/docs?literal=%25s');
});

test('no profile synthesizes Development and distinct dynamic HTTPS/HTTP ports with a mocked certificate check', async t => {
    const f = fixture(t);
    const result = await f.prepare();
    assert.equal(result.profileName, undefined);
    assert.equal(result.env.ASPNETCORE_ENVIRONMENT, 'Development');
    const urls = result.env.ASPNETCORE_URLS.split(';').map(value => new URL(value));
    assert.equal(urls[0].protocol, 'https:');
    assert.equal(urls[1].protocol, 'http:');
    assert.notEqual(urls[0].port, urls[1].port);
    assert(urls.every(url => Number(url.port) > 0 && url.hostname === 'localhost'));
    assert.equal(result.requiresHttps, true);
    assert(new RegExp(result.serverReadyAction.pattern).test('Now listening on: https://localhost:5011'));
    assert(new RegExp(result.serverReadyAction.pattern).test('Now listening on: http://localhost:5010'), 'actual HTTP readiness can override the virtual HTTPS policy');
    assert.deepEqual(f.calls.processes.map(call => call.args), [['dev-certs', 'https', '--check', '--trust']]);
    assert.equal(f.calls.processes[0].settings.cwd, path.dirname(f.source));
});

test('virtual defaults respect ambient environment and HTTP endpoints', async t => {
    const f = fixture(t);
    f.input.environment = { DOTNET_ENVIRONMENT: 'Staging', ASPNETCORE_URLS: 'http://localhost:5090' };
    const result = await f.prepare();
    assert.deepEqual(result.env, {});
    assert.equal(result.requiresHttps, false);
    assert(result.serverReadyAction);
    assert.deepEqual(f.calls.processes, []);
});

test('ambient explicit HTTP/HTTPS ports suppress virtual URLs across all configuration prefixes', async t => {
    const f = fixture(t);
    for (const prefix of ['ASPNETCORE_', 'DOTNET_', '']) {
        for (const protocol of ['HTTP', 'HTTPS']) {
            f.input.environment = { [`${prefix}${protocol}_PORTS`]: '7011;7012' };
            f.calls.processes.length = 0;
            const result = await f.prepare();
            assert.equal(result.env.ASPNETCORE_URLS, undefined, `${prefix}${protocol}_PORTS must not be overwritten`);
            assert.equal(result.requiresHttps, protocol === 'HTTPS');
            assert.equal(f.calls.processes.length, protocol === 'HTTPS' ? 1 : 0);
        }
    }
});

test('effective URLS overrides ports and prefix precedence matches WebApplicationBuilder', async t => {
    const f = fixture(t);
    const cases = [
        [{ ASPNETCORE_HTTPS_PORTS: '7011', DOTNET_URLS: 'http://localhost:5010' }, false],
        [{ ASPNETCORE_URLS: 'https://localhost:7011', DOTNET_URLS: 'http://localhost:5010' }, false],
        [{ DOTNET_URLS: 'https://localhost:7011', URLS: 'http://localhost:5010' }, false],
        [{ DOTNET_URLS: 'http://localhost:5010', URLS: 'https://localhost:7011' }, true],
        [{ ASPNETCORE_HTTPS_PORTS: '7011', DOTNET_HTTPS_PORTS: '', HTTP_PORTS: '5010' }, false],
    ];
    for (const [environment, expected] of cases) {
        f.input.environment = environment;
        f.calls.processes.length = 0;
        const result = await f.prepare();
        assert.equal(result.env.ASPNETCORE_URLS, undefined);
        assert.equal(result.requiresHttps, expected);
        assert.equal(f.calls.processes.length, expected ? 1 : 0);
    }
});

test('profile port variables and lowercase URL keys trigger the selected certificate flow', async t => {
    const f = fixture(t);
    for (const environmentVariables of [{ ASPNETCORE_HTTPS_PORTS: '7011' }, { dotnet_https_ports: '7011' }, { https_ports: '7011' }]) {
        f.write({ Ports: { commandName: 'Project', environmentVariables } });
        assert.equal((await f.prepare()).requiresHttps, true);
    }
    f.write({ Lowercase: { commandName: 'Project', applicationUrl: 'http://localhost:5010', environmentVariables: { aspnetcore_urls: 'https://localhost:7011' } } });
    const result = await f.prepare();
    assert.equal(result.requiresHttps, true);
    if (process.platform === 'win32') {
        assert.equal(result.env.ASPNETCORE_URLS, 'https://localhost:7011');
        assert.equal(result.env.aspnetcore_urls, undefined);
    }
    f.input.environment = { aspnetcore_urls: 'https://localhost:7011', dotnet_environment: 'Staging' };
    f.write({ Ambient: { commandName: 'Project' } });
    assert.equal((await f.prepare()).requiresHttps, true);
});

test('command-line endpoint configuration overrides profile URLs and port variables', async t => {
    const f = fixture(t);
    const cases = [
        ['--urls=https://localhost:7011', true],
        ['--URLS https://localhost:7011', true],
        ['--urls=https://localhost:7011 --urls=http://localhost:5010', false],
        ['--https_ports=7011', false], // profile applicationUrl overrides port-only settings
    ];
    for (const [commandLineArgs, expected] of cases) {
        f.write({ Args: { commandName: 'Project', applicationUrl: 'http://localhost:5010', commandLineArgs } });
        f.calls.processes.length = 0;
        const result = await f.prepare();
        assert.equal(result.requiresHttps, expected);
        assert.equal(f.calls.processes.length, expected ? 1 : 0);
    }
    f.write({ Args: { commandName: 'Project', environmentVariables: { HTTPS_PORTS: '7011' }, commandLineArgs: '--urls http://localhost:5010' } });
    assert.equal((await f.prepare()).requiresHttps, false);
    f.write({ Args: { commandName: 'Project', commandLineArgs: '--https_ports 7011' } });
    assert.equal((await f.prepare()).requiresHttps, true);
});

test('missing certificate runs trust only after explicit consent, then verifies again', async t => {
    const f = fixture(t, { prompt: async (...args) => args[2], runDotnet: async (_args, _settings, calls) => ({ exitCode: calls.processes.length === 1 ? 6 : 0 }) });
    f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011', launchBrowser: true } });
    const result = await f.prepare();
    assert.equal(result.checkForDevCert, false);
    assert.equal(f.calls.prompts.length, 1);
    assert.equal(f.calls.prompts[0][1].modal, true);
    assert.deepEqual(f.calls.processes.map(call => call.args), [
        ['dev-certs', 'https', '--check', '--trust'], ['dev-certs', 'https', '--trust'], ['dev-certs', 'https', '--check', '--trust'],
    ]);
});

for (const [phase, expectedProcesses, expectedPrompts] of [
    ['Checking HTTPS development certificate', 0, 0],
    ['Waiting for HTTPS certificate consent', 1, 0],
    ['Preparing HTTPS development certificate', 1, 1],
    ['Verifying HTTPS development certificate', 2, 1],
]) {
    test(`certificate phases prevent dispatch after progress cancels during ${phase}`, async t => {
        const controller = new AbortController();
        const f = fixture(t, {
            signal: controller.signal,
            prompt: async (...args) => args[2],
            // Deliberately ignores the signal: the helper must check before dispatch.
            runDotnet: async (_args, _settings, calls) => ({ exitCode: calls.processes.length === 1 ? 7 : 0 }),
        });
        f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
        f.input.onProgress = message => {
            f.calls.progress.push(message);
            if (message === phase) controller.abort();
        };
        await assert.rejects(f.prepare(), { name: 'AbortError' });
        assert.equal(f.calls.progress.at(-1), phase);
        assert.equal(f.calls.processes.length, expectedProcesses, 'No certificate process may dispatch after progress cancels');
        assert.equal(f.calls.prompts.length, expectedPrompts, 'No consent modal may dispatch after progress cancels');
        assert(f.calls.processes.every(call => call.settings.signal === controller.signal));
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
    });
}

test('certificate refusal and cancellation prevent trust and launch preparation', async t => {
    const f = fixture(t, { runDotnet: async () => { throw new Error('certificate not trusted'); } });
    f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
    await assert.rejects(f.prepare(), { name: 'AbortError' });
    assert.equal(f.calls.processes.length, 1);
    const controller = new AbortController();
    controller.abort();
    f.input.signal = controller.signal;
    await assert.rejects(f.prepare(), { name: 'AbortError' });
    assert.equal(f.calls.processes.length, 1);
});

test('web preparation cancellation releases an unanswered certificate modal without later trust', async t => {
    const controller = new AbortController();
    let dismiss;
    const f = fixture(t, { signal: controller.signal, runDotnet: async () => ({ exitCode: 7 }), prompt: () => new Promise(resolve => { dismiss = resolve; }) });
    f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
    const operation = f.prepare();
    while (!dismiss) await new Promise(resolve => setImmediate(resolve));
    assert.equal(getEventListeners(controller.signal, 'abort').length, 1);
    controller.abort();
    await assert.rejects(operation, { name: 'AbortError' });
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0, 'Cancel must release the listener while the original modal is still pending');
    dismiss('Trust development certificate');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.calls.processes.length, 1);
});

test('web preparation cancellation forwards the launch signal to both profile reads', { timeout: 5000 }, async t => {
    const controller = new AbortController();
    const f = fixture(t, { signal: controller.signal });
    const reads = [];
    const profile = JSON.stringify({ profiles: { Http: { commandName: 'Project', applicationUrl: 'http://localhost:5010' } } });
    const originalRead = profileIO.readFile;
    t.mock.method(profileIO, 'readFile', (filename, options) => {
        if (!path.resolve(filename).startsWith(f.root + path.sep)) return originalRead(filename, options);
        return new Promise((resolve, reject) => {
            let settled = false;
            const index = reads.length;
            const signal = options?.signal;
            const finish = (complete, value) => {
                if (settled) return;
                settled = true;
                signal?.removeEventListener('abort', cancelled);
                complete(value);
            };
            const cancelled = () => {
                if (index === 0) finish(reject, Object.assign(new Error('Cooperative profile read cancelled'), { name: 'AbortError' }));
            };
            reads.push({ filename, options, get settled() { return settled; },
                rejectLate: () => finish(reject, new Error('Original sibling read rejected after cancellation')),
                release: () => finish(resolve, profile) });
            signal?.addEventListener('abort', cancelled, { once: true });
            if (signal?.aborted) cancelled();
        });
    });
    const operation = f.prepare();
    try {
        assert.equal(reads.length, 2);
        assert.deepEqual(reads.map(read => read.options?.encoding), ['utf8', 'utf8']);
        assert(reads.every(read => read.options.signal === controller.signal), 'Both profile reads must receive the exact launch cancellation signal');
        controller.abort();
        await assert.rejects(operation, { name: 'AbortError' });
        assert.equal(reads[1].settled, false, 'Public cancellation does not prove that every sibling read or OS request settled');
        reads[1].rejectLate();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.prompts, []);
    } finally {
        controller.abort();
        for (const read of reads) read.release();
        await operation.catch(() => {});
    }
});

for (const mode of ['immediate', 'late', 'thenable']) {
    test(`web preparation cancellation observes a ${mode} reentrant certificate prompt rejection`, { timeout: 10000 }, t => {
        const f = fixture(t);
        f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
        const child = spawnSync(process.execPath, ['--unhandled-rejections=strict', '-e',
            '(' + certificatePromptProbe.toString() + ')()', require.resolve('./web.cjs'), f.source, mode], {
            encoding: 'utf8', timeout: 5000, windowsHide: true,
        });
        assert.equal(child.error, undefined, 'The isolated prompt probe must finish within its test safety limit');
        assert.equal(child.status, 0, `The original ${mode} prompt rejection must remain observed after cancellation.\n${child.stderr}`);
        assert.deepEqual(JSON.parse(child.stdout), { mode, prompts: 1, processes: 1, cancelled: true });
    });
}

test('web preparation cancellation preserves an uncancelled prompt rejection with and without a signal', async t => {
    const failure = new Error('Original uncancelled certificate prompt failure');
    for (const signal of [new AbortController().signal, undefined]) {
        const f = fixture(t, { signal, runDotnet: async () => ({ exitCode: 7 }), prompt: () => Promise.reject(failure) });
        f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
        await assert.rejects(f.prepare(), error => error === failure);
        assert.equal(f.calls.processes.length, 1);
        assert.equal(f.calls.prompts.length, 1);
        if (signal) assert.equal(getEventListeners(signal, 'abort').length, 0);
    }
});

test('failed trust and failed post-trust validation stop preparation', async t => {
    const f = fixture(t, { prompt: async (...args) => args[2], runDotnet: async () => ({ exitCode: 7 }) });
    f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
    await assert.rejects(f.prepare(), /setup failed/);
    f.input.runDotnet = async args => ({ exitCode: args.includes('--check') ? 7 : 0 });
    await assert.rejects(f.prepare(), /still missing or untrusted/);
});

test('foreground diagnostics preserve selected and virtual HTTP profiles when profile logging throws', async t => {
    for (const selected of [true, false]) {
        const f = fixture(t);
        if (selected) f.write({ Local: { commandName: 'Project', applicationUrl: 'http://localhost:5017',
            commandLineArgs: '--message "hello world"', environmentVariables: { USER_VALUE: 'unchanged' },
            launchBrowser: true, launchUrl: 'health' } });
        else f.input.environment = { ASPNETCORE_URLS: 'http://localhost:5017' };
        const expected = await f.prepare();
        const attemptedDiagnostics = [];
        f.input.output.appendLine = line => {
            attemptedDiagnostics.push(line);
            throw new Error('Profile diagnostic unavailable');
        };
        assert.deepEqual(await f.prepare(), expected);
        assert.equal(attemptedDiagnostics.length, 1);
        assert.match(attemptedDiagnostics[0], selected ? /^Using web launch profile / : /^Using an in-memory development profile /);
        assert.equal(expected.requiresHttps, false);
        assert.deepEqual(f.calls.processes, []);
        assert.deepEqual(f.calls.prompts, []);
    }
});

test('foreground diagnostics preserve profile precedence and the original malformed-profile error', async t => {
    const f = fixture(t);
    f.write({ Adjacent: { commandName: 'Project', applicationUrl: 'http://localhost:5017' } });
    f.write('{invalid conventional profile', true);
    let diagnosticAttempts = 0;
    f.input.output.appendLine = line => {
        if (!line.includes('Properties/launchSettings.json takes precedence.')) return;
        diagnosticAttempts++;
        throw new Error('Precedence diagnostic unavailable');
    };
    await assert.rejects(f.prepare(), error => error.message.startsWith('Could not read launch profile ') &&
        error.message.includes(path.join(f.root, 'Properties', 'launchSettings.json')) &&
        !error.message.includes('Precedence diagnostic unavailable'));
    f.write({ IIS: { commandName: 'IISExpress' }, Conventional: { commandName: 'Project',
        applicationUrl: 'http://localhost:5021', commandLineArgs: '--source conventional',
        environmentVariables: { PROFILE_SOURCE: 'conventional' } } }, true);
    const result = await f.prepare();
    assert.equal(result.profileName, 'Conventional');
    assert.equal(result.env.ASPNETCORE_URLS, 'http://localhost:5021');
    assert.equal(result.env.PROFILE_SOURCE, 'conventional');
    assert.deepEqual(result.args, ['--source', 'conventional']);
    assert.equal(diagnosticAttempts, 2);
    assert.deepEqual(f.calls.processes, []);
    assert.deepEqual(f.calls.prompts, []);
});

test('foreground diagnostics preserve certificate consent and business errors without swallowing progress errors', async t => {
    for (const mode of ['trust', 'refuse', 'verification', 'trust-exit', 'trust-provider']) {
        const failure = new Error('Original trust provider rejection');
        const f = fixture(t, {
            prompt: async (...args) => mode === 'refuse' ? 'Cancel' : args[2],
            runDotnet: async (_args, _settings, calls) => {
                if (calls.processes.length === 1) throw new Error('Original missing certificate');
                if (calls.processes.length === 2 && mode === 'trust-provider') throw failure;
                if (calls.processes.length === 2 && mode === 'trust-exit') return { exitCode: 7 };
                if (calls.processes.length === 3 && mode === 'verification') throw new Error('Original failed verification');
                return { exitCode: 0 };
            },
        });
        f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
        let diagnosticAttempts = 0;
        f.input.output.appendLine = line => {
            if (!line.startsWith('HTTPS development certificate needs attention:')) return;
            diagnosticAttempts++;
            throw new Error('Certificate diagnostic unavailable');
        };
        if (mode === 'trust') assert.equal((await f.prepare()).requiresHttps, true);
        else if (mode === 'refuse') await assert.rejects(f.prepare(), { name: 'AbortError' });
        else if (mode === 'verification') await assert.rejects(f.prepare(), /still missing or untrusted after setup/);
        else if (mode === 'trust-exit') await assert.rejects(f.prepare(), /setup failed \(exit 7\)/);
        else await assert.rejects(f.prepare(), error => error === failure);
        assert.equal(diagnosticAttempts, mode === 'verification' ? 2 : 1);
        assert.equal(f.calls.prompts.length, 1);
        assert.deepEqual(f.calls.processes.map(call => call.args), [
            ['dev-certs', 'https', '--check', '--trust'],
            ...(mode === 'refuse' ? [] : [['dev-certs', 'https', '--trust']]),
            ...(['trust', 'verification'].includes(mode) ? [['dev-certs', 'https', '--check', '--trust']] : []),
        ]);
    }

    const failure = new Error('Original Web progress failure');
    const f = fixture(t);
    f.write({ Https: { commandName: 'Project', applicationUrl: 'https://localhost:5011' } });
    f.input.onProgress = () => { throw failure; };
    await assert.rejects(f.prepare(), error => error === failure);
    assert.deepEqual(f.calls.processes, []);
    assert.deepEqual(f.calls.prompts, []);
});
