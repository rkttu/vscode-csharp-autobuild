// Execute the actual overlaid packaging functions with synthetic debugger bytes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const source = path.resolve(process.argv[2]);
const ts = createRequire(path.join(source, 'package.json'))('typescript');
const filename = path.join(source, 'tasks/packaging/offlinePackagingTasks.ts');
const parsed = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true);
const functions = ['vsixReleasePackageTask', 'installDebugger'].map(name => {
    const declaration = parsed.statements.find(s => ts.isFunctionDeclaration(s) && s.name?.text === name);
    assert(declaration, `Missing packaging function: ${name}`);
    return ts.createPrinter().printNode(ts.EmitHint.Unspecified, declaration, parsed);
}).join('\n');
const emitted = ts.transpileModule(functions, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'netcoredbg-packaging-test-'));
const debuggerInput = path.join(temporary, 'validated');
const extensionPath = path.join(temporary, 'extension');
fs.mkdirSync(path.join(debuggerInput, 'notices'), { recursive: true });
fs.writeFileSync(path.join(debuggerInput, 'netcoredbg'), 'synthetic debugger bytes', { mode: 0o755 });
fs.writeFileSync(path.join(debuggerInput, 'notices', 'LICENSE'), 'synthetic license');
const env = { VSIX_TARGET: 'linux-arm64', VALIDATED_DEBUGGER_DIRECTORY: debuggerInput };
const entries = ['win32-x64', 'linux-arm64', 'darwin-arm64'].map(vsceTarget => ({ vsixPlatform: { vsceTarget } }));
const calls = [];
const sandbox = {
    exports: {}, fs, path, process: { env }, platformEntries: entries,
    codeExtensionPath: extensionPath,
    doPackageOffline: async (platform, options) => calls.push({ platform, options }),
};
vm.runInNewContext(emitted + '\nglobalThis.installBundledDebugger = installDebugger;', sandbox, { filename });
(async () => {
    try {
        const options = { prerelease: false, outputFolder: path.join(temporary, 'vsix'), codeExtensionPath: extensionPath };
        await sandbox.exports.vsixReleasePackageTask(options);
        assert.equal(calls.length, 1);
        assert.equal(calls[0].platform.vsceTarget, 'linux-arm64');
        assert.equal(calls[0].options, options);
        env.VSIX_TARGET = 'unsupported';
        await assert.rejects(sandbox.exports.vsixReleasePackageTask(options), /Exactly one/);
        delete env.VSIX_TARGET;
        await assert.rejects(sandbox.exports.vsixReleasePackageTask(options), /Exactly one/);
        env.VSIX_TARGET = 'linux-arm64';
        entries.push(entries[1]);
        await assert.rejects(sandbox.exports.vsixReleasePackageTask(options), /Exactly one/);
        assert.equal(calls.length, 1);
        await sandbox.installBundledDebugger({}, {}, extensionPath);
        const installed = path.join(extensionPath, '.debugger', 'netcoredbg');
        assert.equal(fs.readFileSync(path.join(installed, 'netcoredbg'), 'utf8'), 'synthetic debugger bytes');
        assert.equal(fs.readFileSync(path.join(installed, 'notices', 'LICENSE'), 'utf8'), 'synthetic license');
        assert(fs.existsSync(path.join(extensionPath, '.debugger', 'install.complete')));
        if (process.platform !== 'win32') assert(fs.statSync(path.join(installed, 'netcoredbg')).mode & 0o111);
        delete env.VALIDATED_DEBUGGER_DIRECTORY;
        await assert.rejects(sandbox.installBundledDebugger({}, {}, extensionPath), /Validated debugger directory/);
        console.log('Packaging checks passed: exact target, forwarded options, invalid targets, recursive debugger copy, notices, executable mode and required input.');
    } finally {
        fs.rmSync(temporary, { recursive: true, force: true });
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
