'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
const root = __dirname;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
exports.run = async function () {
    const result = { success: false, editorVersion: vscode.version, checks: [], snippets: [],
        scope: { unchangedInstalledCiVsix: true, targetExtensionInjected: false, physicalKeyInput: false,
            snippetCommandUsed: 'editor.action.insertSnippet', userVisibleInstancesTouched: false } };
    try {
        const extension = vscode.extensions.getExtension('dotnetdev-kr-custom.csharp-with-netcoredbg');
        assert(extension, 'Target package must be installed normally');
        assert(path.resolve(extension.extensionPath).toLowerCase().startsWith(path.resolve(root, 'extensions').toLowerCase() + path.sep));
        assert.equal(extension.packageJSON.version, process.env.FBA_SNIPPET_EXPECTED_VERSION);
        result.extensionPath = extension.extensionPath;
        result.version = extension.packageJSON.version;
        const entries = extension.packageJSON.contributes.snippets.filter(item => item.language === 'csharp');
        assert.equal(entries.length, 2, 'Existing C# snippets plus a separate FBA entry are required');
        assert.equal(entries[0].path, './snippets/csharp.json');
        const upstreamBytes = fs.readFileSync(path.join(extension.extensionPath, entries[0].path));
        const upstream = JSON.parse(upstreamBytes);
        assert.equal(Object.keys(upstream).length, 42);
        result.upstream = { entry: entries[0], count: Object.keys(upstream).length, sha256: digest(upstreamBytes) };
        result.checks.push('Installed manifest registers second C# snippet file and preserves 42 upstream snippets');
        const asset = fs.readFileSync(path.join(extension.extensionPath, entries[1].path));
        const snippets = JSON.parse(asset);
        assert(Object.keys(snippets).length > 0);
        result.fba = { entry: entries[1], count: Object.keys(snippets).length, sha256: digest(asset) };
        const names = Object.keys(snippets);
        for (const required of ['fba-shebang', 'fba-disableaot', 'fba-property']) {
            assert(names.some(name => [snippets[name].prefix].flat().includes(required)), `Missing prefix ${required}`);
        }
        result.checks.push('Installed FBA asset includes shebang, disableaot and property prefixes');
        // Commands address registered static snippets by name. No raw snippet body is
        // injected through TextEditor.insertSnippet or a target development override.
        for (const [index, name] of names.entries()) {
            const document = await vscode.workspace.openTextDocument({ language: 'csharp', content: '' });
            await vscode.window.showTextDocument(document);
            for (let attempt = 0; attempt < 20 && !document.getText(); attempt++) {
                await vscode.commands.executeCommand('editor.action.insertSnippet', { langId: 'csharp', name });
                if (!document.getText()) await pause(100);
            }
            const text = document.getText();
            assert(text.length > 0, `Registered snippet did not expand: ${name}`);
            assert(!/\$\{\d|\$\d/.test(text), `Unexpanded tabstop in ${name}`);
            await vscode.commands.executeCommand('leaveSnippet');
            const prefixes = [snippets[name].prefix].flat();
            if (prefixes.includes('fba-shebang')) assert.match(text, /^#!\/usr\/bin\/env(?: -S)? dotnet\b/);
            if (prefixes.includes('fba-disableaot')) assert.match(text, /#:property PublishAot=false/);
            if (prefixes.includes('fba-property')) assert.match(text, /#:property \S+=\S+/);
            const filename = `${String(index + 1).padStart(2, '0')}-${prefixes[0].replace(/[^a-z0-9-]/gi, '_')}.cs`;
            fs.writeFileSync(path.join(root, 'expanded', filename), text);
            result.snippets.push({ name, prefixes, filename, text, selectionCount: vscode.window.activeTextEditor.selections.length });
            await vscode.commands.executeCommand('workbench.action.revertAndCloseActiveEditor');
        }
        assert.equal(result.snippets.length, names.length);
        result.checks.push('Every installed FBA static snippet expands through registered editor command without unresolved tabstops');
        result.success = true;
    } catch (error) {
        result.error = error.stack || String(error);
        throw error;
    } finally {
        fs.writeFileSync(path.join(root, 'editor-result.json'), JSON.stringify(result, null, 2) + '\n');
    }
};
