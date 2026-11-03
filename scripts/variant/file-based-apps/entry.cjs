// Add repository-owned F5 behavior while retaining the upstream extension API.
const path = require('node:path');
const metadata = require('../package.json');
const upstream = require(path.resolve(__dirname, '..', metadata.netcoredbgBuild.upstreamMain));

Object.assign(module.exports, upstream);
module.exports.activate = function activate(context) {
    require('./runtime.cjs').activate(context);
    return upstream.activate(context);
};
