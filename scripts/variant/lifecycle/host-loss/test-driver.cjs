'use strict';

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Probes execute the actual driver source in a VM, with no editor or real
// artifact writes. A child process isolates discarded-rejection observation
// from the Node test runner's own unhandled-rejection listener.
async function probe(scenario, driverFile) {
    const root = path.resolve(__dirname, '__isolated_host_loss_probe__');
    const id = 'local-lifecycle-test.host-loss-driver';
    const expected = { schema: 1, scenario: 'abrupt-extension-host-loss',
        testDriver: { id, version: '0.0.1', localOnly: true, published: false },
        candidate: { localOnly: true, published: false },
        hostLoss: { schema: 1, nonce: 'probe-only', appLaunches: 1,
            extensionDevelopmentPath: false, extensionTestsPath: false } };
    const context = { extensionMode: 1, extension: { id, extensionPath: path.join(root, 'extensions', id + '-0.0.1') } };
    const state = { scenario, runCalls: 0, quitCalls: 0, writes: [], errors: [], unhandled: [],
        activationReturned: false, activationResult: undefined };
    const environment = { NETCOREDBG_LIFECYCLE_ROOT: root };
    if (scenario === 'missing-root') delete environment.NETCOREDBG_LIFECYCLE_ROOT;
    if (scenario === 'relative-root') environment.NETCOREDBG_LIFECYCLE_ROOT = 'relative-run';
    if (scenario === 'outside-installation') context.extension.extensionPath = path.resolve(root, '..', 'unrelated-extension');
    if (scenario === 'development-mode') context.extensionMode = 2;
    if (scenario === 'wrong-identity') context.extension.id = 'unrelated.extension';
    if (scenario === 'published-run') expected.testDriver.published = true;
    const failedRun = ['run-error', 'write-error', 'combined-errors'].includes(scenario);
    process.on('unhandledRejection', error => state.unhandled.push(error?.stack || String(error)));
    const exports = {};
    const modules = {
        'node:fs': {
            readFileSync(file, encoding) {
                assert.equal(file, path.join(root, 'expected.json'));
                assert.equal(encoding, 'utf8');
                if (scenario === 'missing-preparation') throw new Error('expected.json unavailable');
                return JSON.stringify(expected);
            },
            writeFileSync(file, content) {
                state.writes.push({ file, content });
                if (['write-error', 'combined-errors'].includes(scenario)) throw new Error('error artifact write denied');
            },
        },
        'node:path': path,
        vscode: { ExtensionMode: { Production: 1 }, commands: { executeCommand(command) {
            assert.equal(command, 'workbench.action.quit');
            state.quitCalls++;
            if (scenario === 'quit-throws') throw new Error('quit command threw');
            return ['quit-rejects', 'combined-errors'].includes(scenario)
                ? Promise.reject(new Error('quit command rejected')) : Promise.resolve();
        } } },
        './extension-test.cjs': { run(actual) {
            assert.equal(actual, context);
            state.runCalls++;
            // The real async scenario rejects its root assertion before setup.
            if (['missing-root', 'relative-root'].includes(scenario)) return Promise.reject(new Error('original scenario root assertion failed'));
            if (scenario === 'run-throws') throw new Error('original synchronous scenario error');
            if (scenario === 'pending-run') return new Promise(() => {});
            return failedRun ? Promise.reject(new Error('original scenario error')) : Promise.resolve();
        } },
    };
    vm.runInNewContext(fs.readFileSync(driverFile, 'utf8'), { exports,
        process: { env: environment, platform: process.platform },
        console: { error(...values) { state.errors.push(values.map(String).join(' ')); } },
        require(name) { assert(Object.hasOwn(modules, name), 'Unexpected driver dependency: ' + name); return modules[name]; },
    }, { filename: driverFile });
    try {
        state.activationResult = typeof exports.activate(context);
        state.activationReturned = true;
    } catch (error) { state.activationError = error.stack || String(error); }
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    return state;
}

if (process.argv[2] === '--probe') {
    probe(process.argv[3], process.argv[4]).then(value => process.stdout.write(JSON.stringify(value) + '\n'), error => {
        console.error(error);
        process.exitCode = 1;
    });
} else {
    const test = require('node:test');
    const driverFile = process.env.HOST_LOSS_TEST_DRIVER_SOURCE || path.join(__dirname, 'driver.cjs');
    const run = scenario => JSON.parse(childProcess.execFileSync(process.execPath,
        ['--unhandled-rejections=throw', __filename, '--probe', scenario, driverFile], { encoding: 'utf8', windowsHide: true }));
    const returned = value => {
        assert.equal(value.activationReturned, true);
        assert.equal(value.activationResult, 'undefined');
        assert.equal(value.activationError, undefined);
        assert.deepEqual(value.unhandled, []);
    };
    for (const scenario of ['missing-root', 'relative-root', 'outside-installation', 'development-mode', 'wrong-identity', 'published-run', 'missing-preparation']) {
        test(`an unverified ${scenario} driver neither starts the scenario nor quits its editor`, () => {
            const value = run(scenario);
            returned(value);
            assert.equal(value.runCalls, 0);
            assert.equal(value.quitCalls, 0);
            assert.deepEqual(value.writes, []);
            assert(value.errors.some(line => line.includes('Driver is inactive')));
        });
    }
    test('a valid successful driver quits only after starting the scenario', () => {
        const value = run('success');
        returned(value);
        assert.equal(value.runCalls, 1);
        assert.equal(value.quitCalls, 1);
        assert.deepEqual(value.writes, []);
        assert.deepEqual(value.errors, []);
    });
    test('a pending scenario leaves activation complete for later host restart', () => {
        const value = run('pending-run');
        returned(value);
        assert.equal(value.runCalls, 1);
        assert.equal(value.quitCalls, 0);
        assert.deepEqual(value.errors, []);
    });
    for (const scenario of ['run-error', 'run-throws']) {
        test(`${scenario} retains the original failure and attempts isolated quit`, () => {
            const value = run(scenario);
            returned(value);
            assert.equal(value.runCalls, 1);
            assert.equal(value.quitCalls, 1);
            assert.equal(value.writes.length, 1);
            assert(value.writes[0].file.endsWith(path.sep + 'driver-error.txt'));
            assert(value.writes[0].content.includes('original'));
            assert(value.errors.some(line => line.includes('original')));
        });
    }
    test('a failed error-artifact write retains original diagnostics and still quits', () => {
        const value = run('write-error');
        returned(value);
        assert.equal(value.runCalls, 1);
        assert.equal(value.quitCalls, 1);
        assert.equal(value.writes.length, 1);
        assert(value.errors.some(line => line.includes('original scenario error')));
        assert(value.errors.some(line => line.includes('error artifact write denied')));
    });
    for (const scenario of ['quit-rejects', 'quit-throws', 'combined-errors']) {
        test(`${scenario} is observed without a discarded rejection`, () => {
            const value = run(scenario);
            returned(value);
            assert.equal(value.runCalls, 1);
            assert.equal(value.quitCalls, 1);
            assert(value.errors.some(line => line.includes('Could not quit the isolated editor')));
            if (scenario === 'combined-errors') {
                assert(value.errors.some(line => line.includes('original scenario error')));
                assert(value.errors.some(line => line.includes('error artifact write denied')));
            }
        });
    }
}
