'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');

// Directives must start a source line, rather than occur in a comment or string.
// Keep lexical state across lines and interpolation expressions. In particular,
// a verbatim/raw literal nested inside interpolation is still string content,
// even when it contains a line that looks like a file-app directive.
function fileBasedMarker(source) {
    const text = String(source).replace(/^\uFEFF/, '');
    if (text.startsWith('#!')) return 'shebang';
    const contexts = [{ mode: 'code' }];
    let lineStart = true;
    for (let i = 0; i < text.length; i++) {
        const c = text[i];
        const context = contexts.at(-1);
        if (lineStart && contexts.length === 1) {
            const rest = text.slice(i);
            if (/^[\t ]*#:/.test(rest)) return 'directive';
        }
        lineStart = c === '\n' || c === '\r';
        if (context.mode === 'line-comment') {
            if (lineStart) contexts.pop();
            continue;
        }
        if (context.mode === 'block-comment') {
            if (c === '*' && text[i + 1] === '/') { contexts.pop(); i++; }
            continue;
        }
        if (context.mode !== 'code') {
            if (context.dollars && c === '{') {
                let count = 1;
                while (text[i + count] === '{') count++;
                if (context.mode === 'raw') {
                    if (count >= context.dollars) contexts.push({ mode: 'code', closingBraces: context.dollars, depth: 0 });
                    i += count - 1;
                } else if (count % 2) {
                    contexts.push({ mode: 'code', closingBraces: 1, depth: 0 });
                    i += count - 1;
                } else i += count - 1;
            } else if (context.mode === 'raw' && c === '"') {
                let count = 1;
                while (text[i + count] === '"') count++;
                if (count >= context.quotes) contexts.pop();
                i += count - 1;
            } else if (context.mode === 'verbatim' && c === '"') {
                if (text[i + 1] === '"') i++;
                else contexts.pop();
            } else if (context.mode === 'string' || context.mode === 'char') {
                if (c === '\\') i++;
                else if (c === (context.mode === 'char' ? "'" : '"')) contexts.pop();
            }
            continue;
        }
        if (context.closingBraces && c === '{') context.depth++;
        else if (context.closingBraces && c === '}') {
            if (context.depth) context.depth--;
            else {
                let count = 1;
                while (text[i + count] === '}') count++;
                if (count >= context.closingBraces) { contexts.pop(); i += context.closingBraces - 1; }
            }
        } else if (c === '/' && text[i + 1] === '/') { contexts.push({ mode: 'line-comment' }); i++; }
        else if (c === '/' && text[i + 1] === '*') { contexts.push({ mode: 'block-comment' }); i++; }
        else if (c === "'") contexts.push({ mode: 'char' });
        else if (c === '"') {
            let count = 1;
            while (text[i + count] === '"') count++;
            const verbatim = text[i - 1] === '@' || (text[i - 1] === '$' && text[i - 2] === '@');
            let dollarIndex = text[i - 1] === '@' ? i - 2 : i - 1;
            let dollars = 0;
            while (text[dollarIndex--] === '$') dollars++;
            if (count >= 3) { contexts.push({ mode: 'raw', quotes: count, dollars }); i += count - 1; }
            else contexts.push({ mode: verbatim ? 'verbatim' : 'string', dollars });
        }
    }
    return undefined;
}

function hasFileBasedMarker(text) { return fileBasedMarker(text) !== undefined; }

function checkCancellation(signal) {
    if (signal?.aborted) throw signal.reason || new Error('C# file classification was cancelled.');
}

async function discoverProjects(filePath, options = {}) {
    const fileSystem = options.fs || fs;
    const projects = [];
    let directory = path.dirname(path.resolve(filePath));
    for (;;) {
        checkCancellation(options.signal);
        let entries;
        try { entries = await fileSystem.readdir(directory, { withFileTypes: true }); }
        catch (cause) { throw new Error(`Cannot inspect projects in ${directory}: ${cause.message}`, { cause }); }
        const names = [];
        for (const entry of entries) {
            if (!/\.csproj$/i.test(entry.name)) continue;
            if (entry.isFile()) names.push(entry.name);
            else if (entry.isSymbolicLink()) {
                try {
                    if ((await (fileSystem.stat || fs.stat)(path.join(directory, entry.name))).isFile()) names.push(entry.name);
                } catch (cause) {
                    throw new Error(`Cannot inspect C# project ${path.join(directory, entry.name)}: ${cause.message}`, { cause });
                }
            }
        }
        names.sort();
        projects.push(...names.map(name => path.join(directory, name)));
        const parent = path.dirname(directory);
        if (parent === directory) break;
        directory = parent;
    }
    return projects;
}

function normalizePath(filePath) {
    const normalized = path.normalize(path.resolve(filePath));
    return process.platform === 'win32' ? normalized.toLowerCase() : normalized;
}

async function canonicalPath(filePath, fileSystem) {
    try { return normalizePath(await fileSystem.realpath(filePath)); }
    catch (cause) {
        if (cause.code !== 'ENOENT' && cause.code !== 'ENOTDIR') throw cause;
        return normalizePath(filePath);
    }
}

// The SDK can write a first-use banner or warnings before its JSON result.
function parseEvaluation(stdout, projectPath) {
    const text = String(stdout || '').replace(/^\uFEFF/, '').trim();
    for (let start = text.indexOf('{'); start >= 0; start = text.indexOf('{', start + 1)) {
        let depth = 0;
        let quoted = false;
        let escaped = false;
        for (let end = start; end < text.length; end++) {
            const c = text[end];
            if (quoted) {
                if (escaped) escaped = false;
                else if (c === '\\') escaped = true;
                else if (c === '"') quoted = false;
            } else if (c === '"') quoted = true;
            else if (c === '{') depth++;
            else if (c === '}' && --depth === 0) {
                try {
                    const value = JSON.parse(text.slice(start, end + 1));
                    if (Array.isArray(value.Items?.Compile) && value.Properties && typeof value.Properties === 'object') return value;
                } catch { /* Try the next complete object. */ }
                break;
            }
        }
    }
    throw new Error(`MSBuild did not return evaluated Compile items for ${projectPath}. Use a .NET SDK with MSBuild 17.8 or later.`);
}

async function evaluateProject(projectPath, framework, options) {
    const args = ['msbuild', projectPath, '-nologo', '-verbosity:quiet',
        '-getProperty:TargetFramework,TargetFrameworks', '-getItem:Compile',
        `-property:Configuration=${options.configuration || 'Debug'}`];
    if (framework) args.push(`-property:TargetFramework=${framework}`);
    checkCancellation(options.signal);
    try {
        const result = await options.runDotnet(args, {
            cwd: path.dirname(projectPath), signal: options.signal, dotnetPath: options.dotnetPath,
        });
        const exitCode = typeof result === 'string' ? 0 : result.exitCode ?? result.code ?? 0;
        if (exitCode !== 0) throw new Error(result.stderr || result.stdout || `MSBuild exited with code ${exitCode}`);
        return parseEvaluation(typeof result === 'string' ? result : result.stdout, projectPath);
    } catch (cause) {
        checkCancellation(options.signal);
        throw new Error(`Cannot evaluate C# project ${projectPath}${framework ? ` (${framework})` : ''}: ${cause.message}`, { cause });
    }
}

async function includesSource(evaluation, sourcePath, projectPath, fileSystem) {
    for (const item of evaluation.Items.Compile) {
        const itemPath = item.FullPath || (item.Identity && path.resolve(path.dirname(projectPath), item.Identity));
        if (!itemPath) throw new Error(`MSBuild returned a Compile item without a path in ${projectPath}.`);
        if (await canonicalPath(itemPath, fileSystem) === sourcePath) return true;
    }
    return false;
}

/**
 * runDotnet(args, { cwd, signal, dotnetPath }) returns stdout text or
 * { stdout, stderr?, exitCode? }. No build targets are run for classification.
 */
async function classifyFile(options) {
    const marker = fileBasedMarker(options.text);
    if (marker) return { kind: 'file', reason: marker, projects: [] };
    const fileSystem = options.fs || fs;
    const projects = await discoverProjects(options.filePath, { fs: fileSystem, signal: options.signal });
    if (projects.length === 0) return { kind: 'file', reason: 'no-project', projects };
    if (typeof options.runDotnet !== 'function') throw new TypeError('A runDotnet function is required to evaluate project membership.');
    const sourcePath = await canonicalPath(options.filePath, fileSystem);
    const failures = [];
    for (const projectPath of projects) {
        try {
            const outer = await evaluateProject(projectPath, undefined, options);
            const frameworks = String(outer.Properties.TargetFrameworks || '').split(';').map(value => value.trim()).filter(Boolean);
            if (frameworks.length) {
                // Outer builds can omit conditional Compile items, or include
                // items that every inner build removes. Check real inner builds.
                for (const framework of new Set(frameworks)) {
                    try {
                        const inner = await evaluateProject(projectPath, framework, options);
                        if (await includesSource(inner, sourcePath, projectPath, fileSystem)) {
                            return { kind: 'project', reason: 'included', projectPath, targetFramework: framework, projects };
                        }
                    } catch (cause) {
                        checkCancellation(options.signal);
                        failures.push(cause);
                    }
                }
            } else if (await includesSource(outer, sourcePath, projectPath, fileSystem)) {
                return { kind: 'project', reason: 'included', projectPath,
                    targetFramework: outer.Properties.TargetFramework || undefined, projects };
            }
        } catch (cause) {
            checkCancellation(options.signal);
            failures.push(cause);
        }
    }
    if (failures.length) {
        throw new AggregateError(failures,
            `Project membership could not be determined. Fix the project evaluation errors before treating this file as a file-based app.\n${failures.map(error => error.message).join('\n')}`);
    }
    return { kind: 'file', reason: 'excluded', projects };
}

module.exports = { fileBasedMarker, hasFileBasedMarker, discoverProjects, classifyFile };
