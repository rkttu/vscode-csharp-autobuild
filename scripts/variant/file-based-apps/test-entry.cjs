const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}

const turn = () => new Promise(resolve => setImmediate(resolve));

function fixture(options = {}) {
    const context = { extensionPath: '/extension' };
    const calls = [];
    const timers = new Set();
    const cleared = [];
    const diagnostics = [];
    const result = Promise.resolve({ languageServer: true });
    const upstream = {
        activate(received) { assert.equal(received, context); calls.push('upstream'); return result; },
        customApi: {},
        ...options.upstream,
    };
    const runtime = { dispose() { calls.push('dispose'); return options.dispose ? options.dispose() : Promise.resolve(); } };
    const module = { exports: {} };
    const upstreamPath = path.resolve('/extension/.netcoredbg', '..', './dist/extension');
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'entry.cjs'), 'utf8'), {
        module, __dirname: '/extension/.netcoredbg',
        console: { warn(message) { diagnostics.push(message); options.diagnostic?.(message); } },
        setTimeout(callback, delay) { const timer = { callback, delay }; timers.add(timer); return timer; },
        clearTimeout(timer) { timers.delete(timer); cleared.push(timer); },
        require(name) {
            if (name === 'node:path') return path;
            if (name === '../package.json') return { netcoredbgBuild: { upstreamMain: './dist/extension' } };
            if (name === upstreamPath) return upstream;
            if (name === './runtime.cjs') return { activate(received) {
                assert.equal(received, context); calls.push('file-app'); return runtime;
            } };
            throw new Error(`Unexpected import ${name}`);
        },
    });
    return { entry: module.exports, context, calls, upstream, result, timers, cleared, diagnostics };
}

test('entry preserves upstream exports and the exact activation result while registering owned commands first', async () => {
    const f = fixture();
    assert.equal(f.entry.customApi, f.upstream.customApi);
    assert.equal(f.entry.activate(f.context), f.result);
    assert.deepEqual(f.calls, ['file-app', 'upstream']);
    assert.deepEqual(await f.result, { languageServer: true });
});

test('deactivation starts file disposal and upstream promptly but retains the host until file drain', async () => {
    const drain = deferred(), value = {}, receiver = {}, args = [{}];
    const f = fixture({ dispose: () => drain.promise, upstream: { deactivate(...received) {
        assert.equal(this, receiver);
        assert.deepEqual(received, args);
        assert.equal(f.calls.at(-1), 'dispose');
        f.calls.push('deactivate');
        return value;
    } } });
    f.entry.activate(f.context);
    const operation = f.entry.deactivate.apply(receiver, args);
    assert.deepEqual(f.calls, ['file-app', 'upstream', 'dispose', 'deactivate']);
    let settled = false;
    operation.then(() => { settled = true; });
    await turn();
    assert.equal(settled, false, 'Known file work must keep shutdown pending after upstream completes');
    assert.equal(f.timers.size, 1);
    assert.equal([...f.timers][0].delay, 4000);
    assert.equal(f.entry.deactivate(), operation);
    drain.resolve();
    assert.equal(await operation, value);
    assert.equal(f.timers.size, 0);
    assert.equal(f.cleared.length, 1);
    assert.deepEqual(f.diagnostics, []);
});

test('a completed file drain cancels its timer while upstream shutdown remains pending', async () => {
    const upstream = deferred();
    const f = fixture({ upstream: { deactivate: () => upstream.promise } });
    f.entry.activate(f.context);
    const operation = f.entry.deactivate();
    let settled = false;
    operation.then(() => { settled = true; });
    await turn();
    assert.equal(f.timers.size, 0);
    assert.equal(f.cleared.length, 1);
    assert.equal(settled, false);
    const value = {};
    upstream.resolve(value);
    assert.equal(await operation, value);
});

for (const synchronous of [false, true]) {
    test(`upstream ${synchronous ? 'throw' : 'rejection'} is observed without cutting short file drain`, async () => {
        const drain = deferred(), error = new Error('Upstream shutdown failed');
        let count = 0;
        const f = fixture({ dispose: () => drain.promise, upstream: { deactivate() {
            count++;
            if (synchronous) throw error;
            return Promise.reject(error);
        } } });
        f.entry.activate(f.context);
        const operation = f.entry.deactivate();
        let settled = false;
        const outcome = operation.then(() => assert.fail('Expected upstream failure'), reason => { settled = true; return reason; });
        await turn();
        assert.equal(settled, false);
        assert.equal(f.entry.deactivate(), operation);
        drain.resolve();
        assert.equal(await outcome, error);
        assert.equal(count, 1);
        assert.equal(f.timers.size, 0);
    });
}

test('deactivation drains owned work when upstream has no shutdown callback', async () => {
    const drain = deferred();
    const f = fixture({ dispose: () => drain.promise });
    f.entry.activate(f.context);
    const operation = f.entry.deactivate();
    let settled = false;
    operation.then(() => { settled = true; });
    await turn();
    assert.equal(settled, false);
    drain.resolve();
    assert.equal(await operation, undefined);
    assert.equal(f.timers.size, 0);
});

test('deactivation before activation calls upstream once without file work or a grace timer', async () => {
    let count = 0;
    const value = {};
    const f = fixture({ upstream: { deactivate() { count++; return value; } } });
    const operation = f.entry.deactivate();
    assert.equal(f.entry.deactivate(), operation);
    assert.equal(await operation, value);
    assert.equal(count, 1);
    assert.deepEqual(f.calls, []);
    assert.equal(f.timers.size, 0);
    assert.equal(await fixture().entry.deactivate(), undefined);
});

test('reentrant file and upstream callbacks share the original shutdown and execute once', async () => {
    const drain = deferred();
    let fromDispose, fromUpstream, count = 0;
    const f = fixture({ dispose() { fromDispose = f.entry.deactivate(); return drain.promise; }, upstream: {
        deactivate() { count++; fromUpstream = f.entry.deactivate(); return 'done'; },
    } });
    f.entry.activate(f.context);
    const operation = f.entry.deactivate();
    assert.equal(fromDispose, operation);
    assert.equal(fromUpstream, operation);
    assert.equal(count, 1);
    assert.equal(f.calls.filter(call => call === 'dispose').length, 1);
    drain.resolve();
    assert.equal(await operation, 'done');
    assert.equal(f.timers.size, 0);
});

test('a file disposal throw and failing diagnostic do not skip upstream shutdown', async () => {
    let count = 0;
    const f = fixture({ dispose() { throw new Error('File disposal failed'); },
        diagnostic() { throw new Error('Logger failed'); },
        upstream: { deactivate() { count++; return 'upstream result'; } },
    });
    f.entry.activate(f.context);
    assert.equal(await f.entry.deactivate(), 'upstream result');
    assert.equal(count, 1);
    assert.equal(f.timers.size, 0);
    assert(f.diagnostics.some(message => message.includes('File disposal failed')));
});

test('a file drain rejection is observed without replacing the upstream result or retaining its timer', async () => {
    const drain = deferred();
    const f = fixture({ dispose: () => drain.promise, upstream: { deactivate: () => 'upstream result' } });
    f.entry.activate(f.context);
    const operation = f.entry.deactivate();
    drain.reject(new Error('File drain failed'));
    assert.equal(await operation, 'upstream result');
    assert.equal(f.timers.size, 0);
    assert(f.diagnostics.some(message => message.includes('File drain failed')));
});

test('timeout bounds file drain without redisposing resources and observes a later rejection quietly', async () => {
    const drain = deferred(), value = {};
    let count = 0;
    const f = fixture({ dispose: () => drain.promise, upstream: { deactivate() { count++; return value; } } });
    f.entry.activate(f.context);
    const operation = f.entry.deactivate();
    const [timer] = f.timers;
    assert(timer, 'Pending file work must have a bounded grace');
    timer.callback();
    assert.equal(await operation, value);
    assert.equal(f.entry.deactivate(), operation);
    assert.equal(f.timers.size, 0);
    assert.equal(f.cleared.length, 1);
    assert.equal(f.calls.filter(call => call === 'dispose').length, 1);
    assert.equal(count, 1);
    assert.equal(f.diagnostics.length, 1);
    assert.match(f.diagnostics[0], /4000 ms; uncertain output is preserved/);
    drain.reject(new Error('Drain rejected after timeout'));
    await turn();
    assert.equal(f.diagnostics.length, 1);
});
