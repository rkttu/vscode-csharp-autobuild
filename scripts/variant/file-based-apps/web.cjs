'use strict';

const fs = require('node:fs/promises');
const net = require('node:net');
const path = require('node:path');

const BUILD_METADATA_ARGS = [
    '-getProperty:UsingMicrosoftNETSdkWeb,UsingMicrosoftNETSdkRazor,UsingMicrosoftNETSdkWorker,OutputType,TargetFrameworkIdentifier,TargetPlatformIdentifier',
    '-getItem:FrameworkReference',
];

function parseBuildMetadata(stdout) {
    const text = typeof stdout === 'string' ? stdout : stdout?.stdout;
    if (typeof text !== 'string') throw new Error('The file-app build did not return MSBuild metadata.');
    // A build can write restore messages before, and summaries after, its JSON result.
    for (let start = text.indexOf('{'); start !== -1; start = text.indexOf('{', start + 1)) {
        let depth = 0;
        let quoted = false;
        let escaped = false;
        for (let end = start; end < text.length; end++) {
            const char = text[end];
            if (quoted) {
                if (escaped) escaped = false;
                else if (char === '\\') escaped = true;
                else if (char === '"') quoted = false;
            } else if (char === '"') quoted = true;
            else if (char === '{') depth++;
            else if (char === '}' && --depth === 0) {
                let value;
                try { value = JSON.parse(text.slice(start, end + 1)); } catch { break; }
                if (!value.Properties || typeof value.Properties !== 'object') break;
                const properties = value.Properties;
                const items = value.Items?.FrameworkReference || [];
                if (!Array.isArray(items)) throw new Error('Invalid FrameworkReference metadata from the file-app build.');
                const frameworkReferences = items.map(item => item.Identity).filter(item => typeof item === 'string');
                const truthy = name => String(properties[name]).toLowerCase() === 'true';
                const web = truthy('UsingMicrosoftNETSdkWeb');
                const executable = /^(exe|winexe)$/i.test(properties.OutputType || '');
                const managed = /^\.NETCoreApp$/i.test(properties.TargetFrameworkIdentifier || '');
                const browser = /browser|webassembly|wasm/i.test(properties.TargetPlatformIdentifier || '');
                const aspnet = frameworkReferences.some(item => /^Microsoft\.AspNetCore\.App$/i.test(item));
                const isWebServer = executable && managed && !browser && (web || (aspnet && !truthy('UsingMicrosoftNETSdkWorker')));
                return { isWebServer, properties, frameworkReferences };
            }
        }
    }
    throw new Error('Could not read evaluated MSBuild metadata from the file-app build.');
}

function parseJsonc(text) {
    let result = '';
    let quoted = false;
    let escaped = false;
    for (let i = 0; i < text.length; i++) {
        const char = text[i];
        if (quoted) {
            result += char;
            if (escaped) escaped = false;
            else if (char === '\\') escaped = true;
            else if (char === '"') quoted = false;
        } else if (char === '"') {
            quoted = true;
            result += char;
        } else if (char === '/' && text[i + 1] === '/') {
            while (i < text.length && text[i] !== '\n') i++;
            result += '\n';
        } else if (char === '/' && text[i + 1] === '*') {
            const end = text.indexOf('*/', i + 2);
            if (end === -1) throw new Error('Unterminated comment in launch profile.');
            result += ' ';
            i = end + 1;
        } else if (char === ',' && /^\s*[}\]]/.test(text.slice(i + 1))) {
            // JSONC permits a comma after the final member or array element.
        } else result += char;
    }
    // Comments can separate a trailing comma from its closing bracket. Scan a
    // second time so comma/bracket text inside string values is untouched.
    let cleaned = '';
    quoted = false;
    escaped = false;
    for (let i = 0; i < result.length; i++) {
        const char = result[i];
        if (quoted) {
            cleaned += char;
            if (escaped) escaped = false;
            else if (char === '\\') escaped = true;
            else if (char === '"') quoted = false;
        } else if (char === '"') { quoted = true; cleaned += char; }
        else if (char !== ',' || !/^\s*[}\]]/.test(result.slice(i + 1))) cleaned += char;
    }
    return JSON.parse(cleaned.replace(/^\uFEFF/, ''));
}

// Match ProcessStartInfo.Arguments quoting without invoking a shell. Single quotes
// are ordinary characters; only double quotes group arguments.
function splitCommandLine(text) {
    const args = [];
    let value = '';
    let quoted = false;
    let started = false;
    for (let i = 0; i < text.length; i++) {
        const char = text[i];
        if (!quoted && (char === ' ' || char === '\t')) {
            if (started) args.push(value);
            value = '';
            started = false;
        } else if (char === '\\') {
            let count = 1;
            while (text[i + 1] === '\\') { count++; i++; }
            if (text[i + 1] === '"') {
                value += '\\'.repeat(Math.floor(count / 2));
                if (count % 2) { value += '"'; i++; }
                else {
                    i++;
                    if (quoted && text[i + 1] === '"') { value += '"'; i++; }
                    else quoted = !quoted;
                }
            } else value += '\\'.repeat(count);
            started = true;
        } else if (char === '"') {
            if (quoted && text[i + 1] === '"') { value += '"'; i++; }
            else quoted = !quoted;
            started = true;
        } else {
            value += char;
            started = true;
        }
    }
    if (started) args.push(value);
    return args;
}

function abort(signal) {
    if (signal?.aborted) {
        const error = new Error('Web app launch cancelled.');
        error.name = 'AbortError';
        throw error;
    }
}

function withAbort(promise, signal) {
    // The provider may cancel reentrantly while returning its Promise/thenable.
    // Observe that original result even when cancellation has already happened.
    const observed = Promise.resolve(promise);
    if (!signal) return observed;
    return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (complete, value) => {
            if (settled) return;
            settled = true;
            signal.removeEventListener('abort', cancelled);
            complete(value);
        };
        const cancelled = () => finish(reject, Object.assign(new Error('Web app launch cancelled.'), { name: 'AbortError' }));
        observed.then(value => finish(resolve, value), error => finish(reject, error));
        signal.addEventListener('abort', cancelled, { once: true });
        if (signal.aborted) cancelled();
    });
}

async function readProfile(source, output, signal) {
    const conventional = path.join(path.dirname(source), 'Properties', 'launchSettings.json');
    const adjacent = path.join(path.dirname(source), `${path.basename(source, path.extname(source))}.run.json`);
    const read = async filename => {
        try { return await fs.readFile(filename, { encoding: 'utf8', signal }); }
        catch (error) { if (error.code === 'ENOENT') return undefined; throw error; }
    };
    const [conventionalText, adjacentText] = await Promise.all([read(conventional), read(adjacent)]);
    const filename = conventionalText !== undefined ? conventional : adjacent;
    const text = conventionalText ?? adjacentText;
    if (text === undefined) return undefined;
    if (conventionalText !== undefined && adjacentText !== undefined) output?.appendLine(`Using ${conventional}; ${adjacent} is ignored because Properties/launchSettings.json takes precedence.`);
    let settings;
    try { settings = parseJsonc(text); }
    catch (error) { throw new Error(`Could not read launch profile ${filename}: ${error.message}`); }
    if (!settings?.profiles || typeof settings.profiles !== 'object' || Array.isArray(settings.profiles)) throw new Error(`Launch profile ${filename} must contain a profiles object.`);
    const entries = Object.entries(settings.profiles);
    const selected = entries.find(([, profile]) => profile && profile.commandName === 'Project');
    if (!selected) throw new Error(`No supported Project launch profile was found in ${filename}. Executable and IIS Express profiles cannot launch this managed file app.`);
    const [name, profile] = selected;
    return { name, profile, filename };
}

async function freePorts(signal) {
    const servers = [];
    try {
        const ports = [];
        for (let i = 0; i < 2; i++) {
            abort(signal);
            const server = net.createServer();
            servers.push(server);
            await new Promise((resolve, reject) => {
                const cancelled = () => { server.close(); reject(Object.assign(new Error('Web app launch cancelled.'), { name: 'AbortError' })); };
                signal?.addEventListener('abort', cancelled, { once: true });
                server.once('error', error => { signal?.removeEventListener('abort', cancelled); reject(error); });
                server.listen(0, '127.0.0.1', () => { signal?.removeEventListener('abort', cancelled); resolve(); });
            });
            ports.push(server.address().port);
        }
        return ports;
    } finally {
        // Reserve both simultaneously so they differ. The app still must bind them
        // after release; startup failures must never be treated as server readiness.
        await Promise.all(servers.map(server => new Promise(resolve => server.close(() => resolve()))));
    }
}

async function checkCertificate({ runDotnet, source, signal, vscode, output, onProgress }) {
    const check = async () => {
        abort(signal);
        try {
            const result = await runDotnet(['dev-certs', 'https', '--check', '--trust'], { cwd: path.dirname(source), signal });
            return !result || typeof result === 'string' || !result.exitCode;
        } catch (error) {
            abort(signal);
            if (error.name === 'AbortError') throw error;
            output?.appendLine(`HTTPS development certificate needs attention: ${error.message}`);
            return false;
        }
    };
    onProgress?.('Checking HTTPS development certificate');
    if (await check()) return;
    abort(signal);
    const trust = 'Trust development certificate';
    onProgress?.('Waiting for HTTPS certificate consent');
    abort(signal);
    const choice = await withAbort(vscode.window.showWarningMessage('This web app uses HTTPS, but no trusted development certificate was found.', {
        modal: true,
        detail: 'Create or trust the ASP.NET Core development certificate? Your operating system may ask for confirmation.',
    }, trust, 'Cancel'), signal);
    abort(signal);
    if (choice !== trust) throw Object.assign(new Error('HTTPS certificate setup cancelled.'), { name: 'AbortError' });
    onProgress?.('Preparing HTTPS development certificate');
    abort(signal);
    const result = await runDotnet(['dev-certs', 'https', '--trust'], { cwd: path.dirname(source), signal });
    if (result && typeof result !== 'string' && result.exitCode) throw new Error(`HTTPS development certificate setup failed (exit ${result.exitCode}).`);
    onProgress?.('Verifying HTTPS development certificate');
    if (!await check()) throw new Error('HTTPS development certificate is still missing or untrusted after setup.');
}

function endpointConfiguration(environment, overrides = {}, args = []) {
    // WebApplicationBuilder loads ASPNETCORE_ host settings, then DOTNET_, then
    // unprefixed app environment variables, then command-line configuration.
    // Configuration keys are case-insensitive even on a case-sensitive OS.
    const variables = new Map();
    for (const values of [environment, overrides]) {
        for (const [name, value] of Object.entries(values)) variables.set(name.toUpperCase(), value);
    }
    const configuration = {};
    for (const key of ['URLS', 'HTTP_PORTS', 'HTTPS_PORTS']) {
        for (const prefix of ['ASPNETCORE_', 'DOTNET_', '']) {
            if (variables.has(prefix + key)) configuration[key] = variables.get(prefix + key);
        }
    }
    for (let i = 0; i < args.length; i++) {
        const match = /^--(urls|http_ports|https_ports)(?:=(.*))?$/i.exec(args[i]);
        if (!match) continue;
        const value = match[2] === undefined ? args[++i] : match[2];
        if (value !== undefined) configuration[match[1].toUpperCase()] = value;
    }
    return configuration;
}

function hasPorts(value) {
    return typeof value === 'string' && value.split(';').some(port => port.trim() !== '');
}

function expandEnvironmentVariables(value, environment) {
    // SDK launch profiles use Environment.ExpandEnvironmentVariables, not shell
    // interpolation. Expand against the ambient environment once; unknown names
    // stay literal, and earlier profile entries do not create new variables.
    const values = process.platform === 'win32' ?
        Object.fromEntries(Object.entries(environment).map(([name, entry]) => [name.toUpperCase(), entry])) : environment;
    return value.replace(/%([^%]+)%/g, (original, name) => {
        const key = process.platform === 'win32' ? name.toUpperCase() : name;
        return Object.hasOwn(values, key) && typeof values[key] === 'string' ? values[key] : original;
    });
}

async function prepareWebLaunch({ source, metadata, environment = process.env, signal, runDotnet, vscode, output, onProgress }) {
    if (!metadata?.isWebServer) return undefined;
    abort(signal);
    const selected = await readProfile(source, output, signal);
    abort(signal);
    const env = {};
    let args = [];
    let launchBrowser;
    let launchUrl;
    if (selected) {
        const profile = selected.profile;
        for (const key of ['applicationUrl', 'commandLineArgs', 'launchUrl']) {
            if (profile[key] !== undefined && typeof profile[key] !== 'string') throw new Error(`Launch profile ${selected.name}: ${key} must be a string.`);
        }
        if (profile.launchBrowser !== undefined && typeof profile.launchBrowser !== 'boolean') throw new Error(`Launch profile ${selected.name}: launchBrowser must be a boolean.`);
        if (profile.applicationUrl) env.ASPNETCORE_URLS = profile.applicationUrl;
        if (profile.environmentVariables !== undefined) {
            if (!profile.environmentVariables || typeof profile.environmentVariables !== 'object' || Array.isArray(profile.environmentVariables)) throw new Error(`Launch profile ${selected.name}: environmentVariables must be an object.`);
            for (const [key, value] of Object.entries(profile.environmentVariables)) {
                if (typeof value !== 'string') throw new Error(`Launch profile ${selected.name}: environment variable ${key} must be a string.`);
                // Windows environment names are case-insensitive. Avoid emitting
                // both applicationUrl's ASPNETCORE_URLS and its lowercase override.
                const name = process.platform === 'win32' ? key.toUpperCase() : key;
                env[name] = expandEnvironmentVariables(value, environment);
            }
        }
        env.DOTNET_LAUNCH_PROFILE = selected.name;
        args = splitCommandLine(profile.commandLineArgs || '');
        launchBrowser = profile.launchBrowser === true;
        launchUrl = profile.launchUrl;
        output?.appendLine(`Using web launch profile ${selected.name} from ${selected.filename}.`);
    } else {
        const ambient = Object.fromEntries(Object.entries(environment).map(([name, value]) => [name.toUpperCase(), value]));
        if (!ambient.ASPNETCORE_ENVIRONMENT && !ambient.DOTNET_ENVIRONMENT) env.ASPNETCORE_ENVIRONMENT = 'Development';
        const endpoints = endpointConfiguration(environment);
        if (endpoints.URLS === undefined && !hasPorts(endpoints.HTTP_PORTS) && !hasPorts(endpoints.HTTPS_PORTS)) {
            const [httpsPort, httpPort] = await freePorts(signal);
            env.ASPNETCORE_URLS = `https://localhost:${httpsPort};http://localhost:${httpPort}`;
        }
        launchBrowser = true;
        output?.appendLine(`Using an in-memory development profile for ${path.basename(source)}.`);
    }
    const endpoints = endpointConfiguration(environment, env, args);
    const urls = endpoints.URLS || '';
    // Explicit URLS overrides HTTP_PORTS/HTTPS_PORTS in the generic web host.
    const requiresHttps = urls ? urls.split(';').some(url => /^https:\/\//i.test(url.trim())) : hasPorts(endpoints.HTTPS_PORTS);
    if (requiresHttps) await checkCertificate({ runDotnet, source, signal, vscode, output, onProgress });
    abort(signal);
    let serverReadyAction;
    if (launchBrowser) {
        serverReadyAction = {
            action: 'openExternally',
            // Application code can override profile URLs. Follow the endpoint
            // actually reported ready, rather than the certificate-setup guess.
            pattern: '\\bNow listening on:\\s+(https?://\\S+)',
        };
        if (launchUrl) {
            if (/^https?:\/\//i.test(launchUrl)) {
                // Without a capture, VS Code uses the fixed URI without format substitution.
                serverReadyAction.pattern = serverReadyAction.pattern.replace('(', '(?:');
                serverReadyAction.uriFormat = launchUrl.replace(/%s/g, '%25s');
            } else {
                // A literal %s would be mistaken for another substitution by the
                // built-in handler. Encode that percent; escape other format signs.
                const relative = launchUrl.replace(/^\/+/, '').replace(/%s/g, '%25s').replace(/%/g, '%%');
                serverReadyAction.uriFormat = `%s/${relative}`;
            }
        }
    }
    return { env, args, serverReadyAction, checkForDevCert: false, profileName: selected?.name, requiresHttps };
}

module.exports = { BUILD_METADATA_ARGS, parseBuildMetadata, prepareWebLaunch };
