'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('vscode');
exports.activate = function activate() {
    void require('./extension-test.cjs').run().then(() => vscode.commands.executeCommand('workbench.action.quit')).catch(error => {
        fs.writeFileSync(path.join(process.env.NETCOREDBG_LIFECYCLE_ROOT, 'driver-error.txt'), error.stack || String(error));
        void vscode.commands.executeCommand('workbench.action.quit');
    });
};
