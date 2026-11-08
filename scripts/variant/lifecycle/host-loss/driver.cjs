'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');

const DRIVER_ID = 'local-lifecycle-test.host-loss-driver';
const DRIVER_VERSION = '0.0.1';

function report(message, error) {
    // Reporting must never create another discarded rejection.
    try { console.error(`[host-loss driver] ${message}`, error?.stack || String(error)); }
    catch (_) {}
}

function isolatedRoot(context) {
    const configured = process.env.NETCOREDBG_LIFECYCLE_ROOT;
    if (typeof configured !== 'string' || !path.isAbsolute(configured) ||
        context?.extensionMode !== vscode.ExtensionMode.Production || context?.extension?.id !== DRIVER_ID) {
        throw new Error('This local driver requires its prepared, normally installed isolated run.');
    }
    const root = path.resolve(configured);
    const expected = JSON.parse(fs.readFileSync(path.join(root, 'expected.json'), 'utf8').replace(/^\uFEFF/, ''));
    const installation = path.join(root, 'extensions', `${DRIVER_ID}-${DRIVER_VERSION}`);
    const normalize = value => {
        const resolved = path.resolve(value);
        return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
    };
    if (expected.schema !== 1 || expected.scenario !== 'abrupt-extension-host-loss' ||
        expected.testDriver?.id !== DRIVER_ID || expected.testDriver.version !== DRIVER_VERSION ||
        expected.testDriver.localOnly !== true || expected.testDriver.published !== false ||
        expected.candidate?.localOnly !== true || expected.candidate.published !== false ||
        expected.hostLoss?.schema !== 1 || typeof expected.hostLoss.nonce !== 'string' || !expected.hostLoss.nonce ||
        expected.hostLoss.appLaunches !== 1 || expected.hostLoss.extensionDevelopmentPath !== false ||
        expected.hostLoss.extensionTestsPath !== false || typeof context.extension.extensionPath !== 'string' ||
        normalize(context.extension.extensionPath) !== normalize(installation)) {
        throw new Error('The driver installation does not match the prepared local host-loss run.');
    }
    return root;
}

async function quit() {
    try { await vscode.commands.executeCommand('workbench.action.quit'); }
    catch (error) { report('Could not quit the isolated editor.', error); }
}

exports.activate = function activate(context) {
    let root;
    try { root = isolatedRoot(context); }
    catch (error) {
        // Installing or opening this local driver outside its launcher must not
        // run the scenario or close an editor whose ownership is unverified.
        report('Driver is inactive outside its prepared isolated run.', error);
        return;
    }
    // Normally installed: a development-host crash closes its whole window.
    // Activation completes promptly so the replacement host can activate again.
    void Promise.resolve().then(() => require('./extension-test.cjs').run(context)).then(
        () => quit(),
        error => {
            report('Scenario failed.', error);
            try { fs.writeFileSync(path.join(root, 'driver-error.txt'), error?.stack || String(error)); }
            catch (writeError) { report('Could not save driver-error.txt.', writeError); }
            return quit();
        },
    ).catch(error => report('Unexpected driver completion failure.', error));
};
