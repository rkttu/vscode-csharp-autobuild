// Exercise the actual overlaid factory class with isolated VS Code/SDK services.
// Native DAP tests are separate; this does not simulate an extension host.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const source = path.resolve(process.argv[2]);
const ts = createRequire(path.join(source, 'package.json'))('typescript');
const file = path.join(source, 'src/coreclrDebug/activate.ts');
const parsed = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
const factory = parsed.statements.find(s => ts.isClassDeclaration(s) && s.name.text === 'DebugAdapterExecutableFactory');
assert(factory, 'The upstream factory class was moved or removed');
const text = ts.createPrinter().printNode(ts.EmitHint.Unspecified, factory, parsed);
const emitted = ts.transpileModule(text, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
class Adapter { constructor(command, args, options) { Object.assign(this, { command, args, options }); } }
class Util { static existsSync() { return true; } debugAdapterDir() { return '/extension/.debugger'; } }
const isolatedEnv = {};
const sandbox = {
    exports: {}, path, process: { env: isolatedEnv },
    vscode: { DebugAdapterExecutable: Adapter }, CoreClrDebugUtil: Util,
    common: { getExtensionPath: () => '/extension' }, omnisharpOptions: { dotNetCliPaths: [] },
    getDotnetInfo: async () => ({ CliPath: '/native-sdk/dotnet' }),
    getTargetArchitecture: (_platform, requested) => requested || 'x86_64',
};
vm.runInNewContext(emitted, sandbox, { filename: file });
const instance = new sandbox.exports.DebugAdapterExecutableFactory(null, {}, {}, { netcoredbgBuild: { target: 'win32-x64' } }, '/extension');
const executable = new Adapter('/extension/.debugger/netcoredbg/netcoredbg.exe', ['--interpreter=vscode'], { env: { KEEP: 'yes' } });
(async () => {
    const session = { type: 'coreclr', configuration: {} };
    const result = await instance.createDebugAdapterDescriptor(session, executable);
    assert.equal(result.command, executable.command);
    assert.deepEqual(result.args, executable.args);
    assert.equal(result.options.env.DOTNET_ROOT, '/native-sdk');
    assert.equal(result.options.env.KEEP, 'yes');
    isolatedEnv.DOTNET_ROOT = '/explicit-sdk';
    assert.equal((await instance.createDebugAdapterDescriptor(session, executable)).options.env.DOTNET_ROOT, '/explicit-sdk');
    await assert.rejects(instance.createDebugAdapterDescriptor({ type: 'clr', configuration: {} }, executable), /coreclr/);
    await assert.rejects(instance.createDebugAdapterDescriptor(session, undefined), /bundled netcoredbg/);
    await assert.rejects(instance.createDebugAdapterDescriptor({ type: 'coreclr', configuration: { targetArchitecture: 'arm64' } }, executable), /architecture/);
    console.log('Factory checks passed: descriptor, args, SDK discovery, environment, unsupported type, missing descriptor, architecture mismatch.');
})().catch(error => { console.error(error); process.exitCode = 1; });
