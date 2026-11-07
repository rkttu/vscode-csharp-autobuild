'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const io = fs.promises;
const root = path.resolve(__dirname);
const outputName = process.argv[2];
assert(/^result-recovery-(node|editor)\.json$/.test(outputName));
const oldEvidence = path.resolve(root, '..', 'installed-web-profile-failure-01');
const expected = JSON.parse(fs.readFileSync(path.join(oldEvidence, 'expected.json')));
const recoveryFile = path.join(oldEvidence, 'extensions', expected.extensionId + '-' + expected.candidate.version, '.netcoredbg', 'recovery.cjs');
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
assert.equal(sha(recoveryFile), expected.candidate.ownedModules['recovery.cjs']);
const { createRecovery } = require(recoveryFile);
const canonical = value => path.toNamespacedPath(path.resolve(value)).toLowerCase();
const result = { schema: 1, scope: 'Existing installed recovery helper, native filesystem only; same-process distinct controllers, not editor/.NET crash qualification',
  command: { argv: process.argv, execArgv: process.execArgv, electronRunAsNode: process.env.ELECTRON_RUN_AS_NODE },
  runtime: { executable: process.execPath, sha256: sha(process.execPath), version: process.version, versions: process.versions, arch: process.arch },
  inputs: { script: { path: __filename, sha256: sha(__filename) }, recovery: { path: recoveryFile, sha256: sha(recoveryFile) },
    originalExpected: { path: path.join(oldEvidence, 'expected.json'), sha256: sha(path.join(oldEvidence, 'expected.json')) } },
  calls: [], log: [] };
const fail = error => ({ code: error.code, message: error.message, stack: error.stack });
(async () => {
  assert.equal(process.platform, 'win32');
  const ownedRoot = await io.mkdtemp(path.join(root, 'recovery-owned-'));
  result.ownedRoot = ownedRoot;
  assert(canonical(ownedRoot).startsWith(canonical(root) + path.sep));
  // The retained initial failure has a 237-character source parent and a
  // 248-character full run name. Recreate those lengths with the v1 shape.
  const baseCharacters = 237 - 25;
  const padding = baseCharacters - ownedRoot.length - 1;
  assert(padding > 0 && padding < 255);
  const base = path.join(ownedRoot, 'b'.repeat(padding));
  const sourceParent = path.join(base, 'a'.repeat(24));
  const source = path.join(sourceParent, 'run-ABC123');
  assert.equal(sourceParent.length, 237);
  assert.equal(source.length, 248);
  result.base = base; result.source = source;
  await io.mkdir(base, { mode: 0o700 });
  await io.mkdir(sourceParent, { mode: 0o700 });
  await io.mkdir(source, { mode: 0o700 });
  await io.writeFile(path.join(source, 'FileApp.dll'), 'owned dummy output payload\n', { flag: 'wx' });
  const unmarked = path.join(base, 'unmarked-probe');
  const external = path.join(ownedRoot, 'external-probe');
  await io.mkdir(unmarked); await io.mkdir(external);
  const guards = [path.join(unmarked, 'keep.txt'), path.join(external, 'keep.txt')];
  for (const file of guards) await io.writeFile(file, 'protected ' + path.dirname(file) + '\n', { flag: 'wx' });
  result.guards = guards.map(file => ({ path: file, sha256: sha(file) }));
  const removeOutput = async (directory, options) => {
    const resolved = path.resolve(directory);
    assert(canonical(resolved).startsWith(canonical(base) + path.sep));
    assert.equal(path.basename(resolved), 'output');
    assert(!fs.lstatSync(resolved).isSymbolicLink());
    result.calls.push({ directory: resolved, options });
    await io.rm(resolved, options);
  };
  const writer = createRecovery({ baseDirectory: base, removeOutput, isOwned: directory => directory === source,
    log: line => result.log.push(line) });
  result.published = await writer.preserve(source);
  result.sourceAbsentAfterPublication = !fs.existsSync(source);
  result.readyEntriesAfterPublication = fs.readdirSync(path.join(base, 'terminal-cleanup-v1'));
  assert.equal(result.published, true);
  assert.equal(result.sourceAbsentAfterPublication, true);
  assert.equal(result.readyEntriesAfterPublication.length, 1);
  const entry = path.join(base, 'terminal-cleanup-v1', result.readyEntriesAfterPublication[0]);
  result.publishedPayload = { path: path.join(entry, 'output', 'FileApp.dll'), sha256: sha(path.join(entry, 'output', 'FileApp.dll')) };
  const reader = createRecovery({ baseDirectory: base, removeOutput, isOwned: () => false,
    log: line => result.log.push(line) });
  result.recovery = await reader.recover();
  result.readyEmpty = fs.readdirSync(path.join(base, 'terminal-cleanup-v1')).length === 0;
  result.stagingEmpty = fs.readdirSync(path.join(base, 'terminal-cleanup-staging-v1')).length === 0;
  result.guardsPreserved = result.guards.every(guard => sha(guard.path) === guard.sha256);
  assert.deepEqual(result.recovery, { scanned: 1, attempted: 1, removed: 1 });
  assert(result.readyEmpty && result.stagingEmpty && result.guardsPreserved);
  assert.equal(result.calls.length, 1);
  result.success = true;
})().catch(error => { result.error = fail(error); result.success = false; process.exitCode = 1; }).finally(async () => {
  // Protected probe guards stay on disk as raw evidence. Only the existing
  // recovery helper's fixed, validated output child is recursively removed.
  await io.writeFile(path.join(root, outputName), JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
  process.stdout.write(JSON.stringify({ output: path.join(root, outputName), success: result.success,
    published: result.published, recovery: result.recovery, readyEmpty: result.readyEmpty,
    stagingEmpty: result.stagingEmpty, guardsPreserved: result.guardsPreserved, error: result.error }) + '\n');
});
