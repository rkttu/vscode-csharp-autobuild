// Add repository-owned F5 behavior while retaining the upstream extension API.
const path = require('node:path');
const metadata = require('../package.json');
const upstream = require(path.resolve(__dirname, '..', metadata.netcoredbgBuild.upstreamMain));
const FILE_DRAIN_GRACE_MS = 4000;
let fileRuntime;
let deactivation;

function diagnostic(message) {
    try { console.warn(`C# file debugging deactivation: ${message}`); }
    catch { /* Diagnostics must not replace upstream deactivation behavior. */ }
}

function waitForFileDrain(drain) {
    return new Promise(resolve => {
        let settled = false;
        const finish = message => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            if (message) diagnostic(message);
            resolve();
        };
        // The editor also bounds extension shutdown. This is a best-effort grace,
        // not permission to discard uncertain output or stop observing a session.
        const timer = setTimeout(() => finish('file-app work is still draining after 4000 ms; uncertain output is preserved'), FILE_DRAIN_GRACE_MS);
        Promise.resolve(drain).then(() => finish(), error => finish(`file-app drain failed: ${error?.message || String(error)}`));
    });
}

Object.assign(module.exports, upstream);
module.exports.activate = function activate(context) {
    fileRuntime = require('./runtime.cjs').activate(context);
    return upstream.activate(context);
};
module.exports.deactivate = function deactivate(...args) {
    if (deactivation) return deactivation;
    let resolveDeactivation;
    let rejectDeactivation;
    // Cache before any provider can reenter deactivation, including disposal.
    deactivation = new Promise((resolve, reject) => { resolveDeactivation = resolve; rejectDeactivation = reject; });
    let drain;
    try { drain = fileRuntime?.dispose(); }
    catch (error) { diagnostic(`could not start file-app disposal: ${error?.message || String(error)}`); }
    const fileReady = drain === undefined ? Promise.resolve() : waitForFileDrain(drain);
    let upstreamResult;
    try { upstreamResult = typeof upstream.deactivate === 'function' ? upstream.deactivate.apply(this, args) : undefined; }
    catch (error) { upstreamResult = Promise.reject(error); }
    // Run both paths promptly, but do not let an early upstream rejection cut
    // short the file-app grace. Preserve the upstream result or original error.
    void Promise.allSettled([fileReady, upstreamResult]).then(([, result]) => {
        if (result.status === 'fulfilled') resolveDeactivation(result.value);
        else rejectDeactivation(result.reason);
    });
    return deactivation;
};
