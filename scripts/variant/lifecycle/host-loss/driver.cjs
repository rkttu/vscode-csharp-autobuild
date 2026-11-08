'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
exports.activate = function activate(context) {
    // Normally installed: a development-host crash closes its whole window.
    void require('./extension-test.cjs').run(context).then(() => vscode.commands.executeCommand('workbench.action.quit')).catch(error => {
        fs.writeFileSync(path.join(process.env.NETCOREDBG_LIFECYCLE_ROOT, 'driver-error.txt'), error.stack || String(error));
        void vscode.commands.executeCommand('workbench.action.quit');
    });
};
