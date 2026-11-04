const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = __dirname;
const raw = fs.readFileSync(path.join(root, 'result.json'));
const result = JSON.parse(raw);
const digest = name => crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex');
const summary = {
    date: '2026-11-04', success: result.success, platform: result.platform,
    sdkVersion: result.sdkVersion, runtimeVersion: result.runtimeVersion, runtimeSha256: result.runtimeSha256,
    scope: result.scope, checks: result.checks,
    deadlineInjection: {
        defaultBudgetMs: 300000,
        testClockOffsetAddedMs: 300001,
        callbackScheduledAfterFirstBuildPhaseReportMs: 50,
        interpretation: 'The first timeout uses a test-only clock offset and explicit deadline callback. Its reported cumulative milliseconds are synthetic, not a five-minute wait or measured performance. Actual dotnet commands execute natively without a runDotnet replacement. Retry runs in the same runtime instance with a fresh preparation budget and constant clock offset.',
    },
    phaseLogs: result.logs.filter(line => line.startsWith('Phase ')),
    positiveBuildTiming: result.logs.find(line => line.startsWith('Phase completed: Building file-based app')),
    positiveBuildTimingInterpretation: 'Only the successful second build has no changing clock offset during the operation; its phase and cumulative durations are observed elapsed times for this one local run, not latency budgets or qualification.',
    cleanup: { firstRunOutputsAbsentAfterTimeout: result.success, retryDllAndPdbPresentBeforeMockedTermination: result.success, retryOutputAbsentAfterMockedTermination: result.success },
    artifactSha256: { 'control.cjs': digest('control.cjs'), 'result.json': crypto.createHash('sha256').update(raw).digest('hex') },
};
fs.writeFileSync(path.join(root, 'evidence-summary.json'), JSON.stringify(summary, null, 2) + '\n');
process.stdout.write(JSON.stringify({ success: summary.success, runtimeSha256: summary.runtimeSha256, positiveBuildTiming: summary.positiveBuildTiming }) + '\n');
