'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname);
const outputName = process.argv[2] || 'result.json';
assert(/^result(?:-[a-z]+)?\.json$/.test(outputName));
const evidence = path.resolve(root, '..', 'installed-web-profile-failure-01');
const io = fs.promises;
const result = { schema: 1, scope: 'Native Node filesystem probe; not installed VSCodium or .NET/DAP qualification',
  node: { executable: process.execPath, version: process.version, versions: process.versions, arch: process.arch, platform: process.platform }, cases: [] };
const canonical = value => path.toNamespacedPath(path.resolve(value)).toLowerCase();
const owned = [];
const parentDirs = [];
let ownedRoot;
function assertOwned(target) {
  assert(canonical(target).startsWith(canonical(ownedRoot) + path.sep), 'Target must be a child of the exact new probe root');
  assert(canonical(ownedRoot).startsWith(canonical(root) + path.sep));
}
function failure(error) { return { code: error.code, syscall: error.syscall, path: error.path, message: error.message, stack: error.stack }; }
function insideDirectory(directory, candidate) {
  const relative = path.relative(path.resolve(directory), path.resolve(candidate));
  return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}
function findLog(directory) {
  for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, item.name);
    if (item.isDirectory()) { const child = findLog(file); if (child) return child; }
    else if (item.isFile() && item.name.endsWith('C# File Debugging.log')) return file;
  }
}
(async () => {
  assert.equal(process.platform, 'win32');
  const sourceLog = findLog(path.join(evidence, 'profile', 'logs'));
  const sourceBytes = fs.readFileSync(sourceLog);
  const sourceText = sourceBytes.toString('utf8');
  const errorLine = sourceText.split(/\r?\n/).find(line => line.includes('ENAMETOOLONG') && line.includes('mkdtemp'));
  const failedTemplate = /mkdtemp '([^']+)'/.exec(errorLine)?.[1];
  assert(failedTemplate && failedTemplate.endsWith('run-XXXXXX'));
  result.originalFailure = { sourceLog, sha256: crypto.createHash('sha256').update(sourceBytes).digest('hex'), errorLine,
    failedTemplate, templateCharacters: failedTemplate.length, parentCharacters: path.dirname(failedTemplate).length };
  ownedRoot = await io.mkdtemp(path.join(root, 'owned-'));
  result.exactOwnedRoot = ownedRoot;
  const targetParentLength = path.dirname(failedTemplate).length;
  for (const variant of ['bare-mkdtemp', 'namespaced-mkdtemp', 'bare-mkdir', 'namespaced-mkdir']) {
    const caseRoot = path.join(ownedRoot, variant);
    await io.mkdir(caseRoot, { mode: 0o700 }); parentDirs.push(caseRoot);
    const paddingLength = targetParentLength - caseRoot.length - 1;
    assert(paddingLength > 0 && paddingLength < 255);
    const parent = path.join(caseRoot, 'p'.repeat(paddingLength));
    assert.equal(parent.length, targetParentLength);
    await io.mkdir(parent, { mode: 0o700 }); parentDirs.push(parent);
    const prefix = path.join(parent, 'run-');
    const item = { variant, parent, prefix, prefixCharacters: prefix.length, expectedOutputCharacters: prefix.length + 6 };
    result.cases.push(item);
    try {
      const namespaced = variant.startsWith('namespaced');
      const mkdir = variant.endsWith('-mkdir');
      const candidate = mkdir ? prefix + 'ABC123' : prefix;
      item.argument = namespaced ? path.toNamespacedPath(candidate) : candidate;
      let directory;
      if (mkdir) { await io.mkdir(item.argument, { mode: 0o700 }); directory = candidate; }
      else directory = await io.mkdtemp(item.argument);
      assertOwned(directory);
      owned.push(directory);
      item.created = true;
      item.returnedDirectory = directory;
      item.nameEligible = /^run-[A-Za-z0-9]{6}$/.test(path.basename(directory));
      item.currentRuntimeInsideDirectory = insideDirectory(ownedRoot, directory);
      item.relativeFromBareBase = path.relative(path.resolve(ownedRoot), path.resolve(directory));
      const marker = path.join(directory, 'probe.txt');
      assertOwned(marker);
      try {
        await io.writeFile(marker, 'owned Windows path probe\n', { flag: 'wx' });
        item.fileReadback = (await io.readFile(marker, 'utf8')) === 'owned Windows path probe\n';
        await io.unlink(marker);
        item.fileRemoved = true;
      } catch (error) { item.fileError = failure(error); }
      await io.rmdir(directory);
      owned.splice(owned.indexOf(directory), 1);
      item.directoryRemoved = true;
    } catch (error) { item.error = failure(error); }
  }
})().catch(error => { result.unexpectedError = failure(error); process.exitCode = 1; }).finally(async () => {
  result.cleanupErrors = [];
  // Only exact returned directories and exact parents created above are visited;
  // no recursive deletion or scan of the original evidence is performed.
  for (const directory of owned.reverse()) {
    try { assertOwned(directory); await io.unlink(path.join(directory, 'probe.txt')).catch(error => { if (error.code !== 'ENOENT') throw error; }); await io.rmdir(directory); }
    catch (error) { result.cleanupErrors.push({ directory, error: failure(error) }); }
  }
  for (const directory of parentDirs.reverse()) {
    try { assertOwned(directory); await io.rmdir(directory); }
    catch (error) { result.cleanupErrors.push({ directory, error: failure(error) }); }
  }
  if (ownedRoot) {
    try { assert(canonical(ownedRoot).startsWith(canonical(root) + path.sep)); await io.rmdir(ownedRoot); result.ownedRootRemoved = true; }
    catch (error) { result.cleanupErrors.push({ directory: ownedRoot, error: failure(error) }); }
  }
  const bytes = JSON.stringify(result, null, 2) + '\n';
  await io.writeFile(path.join(root, outputName), bytes, { flag: 'wx' });
  process.stdout.write(JSON.stringify({ output: path.join(root, outputName), cases: result.cases.map(x => ({ variant: x.variant, created: x.created, errorCode: x.error?.code, inside: x.currentRuntimeInsideDirectory, fileReadback: x.fileReadback, removed: x.directoryRemoved })), cleanupErrors: result.cleanupErrors, ownedRootRemoved: result.ownedRootRemoved, unexpectedError: result.unexpectedError }) + '\n');
});
