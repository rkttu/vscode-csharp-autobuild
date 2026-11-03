const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

test('entry preserves the upstream API and activation result while registering owned commands', async () => {
    const context = { extensionPath: '/extension' };
    const calls = [];
    const api = { languageServer: true };
    const result = Promise.resolve(api);
    const upstream = {
        activate(received) { assert.equal(received, context); calls.push('upstream'); return result; },
        deactivate() {},
        customApi: {},
    };
    const module = { exports: {} };
    const upstreamPath = path.resolve('/extension/.netcoredbg', '..', './dist/extension');
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'entry.cjs'), 'utf8'), {
        module, __dirname: '/extension/.netcoredbg',
        require(name) {
            if (name === 'node:path') return path;
            if (name === '../package.json') return { netcoredbgBuild: { upstreamMain: './dist/extension' } };
            if (name === upstreamPath) return upstream;
            if (name === './runtime.cjs') return { activate(received) {
                assert.equal(received, context); calls.push('file-app');
            } };
            throw new Error(`Unexpected import ${name}`);
        },
    });
    assert.equal(module.exports.deactivate, upstream.deactivate);
    assert.equal(module.exports.customApi, upstream.customApi);
    assert.equal(module.exports.activate(context), result);
    assert.deepEqual(calls, ['file-app', 'upstream']);
    assert.equal(await result, api);
});
