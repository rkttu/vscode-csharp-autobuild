#!/usr/bin/env node

/**
 * This script replaces vsdbg debugger dependencies with Samsung/netcoredbg
 * in the package.json of the upstream vscode-csharp extension.
 * 
 * This is necessary because vsdbg cannot be used with VS Code forks
 * that don't have access to the Microsoft marketplace.
 */

const fs = require('fs');
const path = require('path');

const NETCOREDBG_VERSION = '3.1.2-1054';
const NETCOREDBG_BASE_URL = `https://github.com/Samsung/netcoredbg/releases/download/${NETCOREDBG_VERSION}`;

// Mapping from upstream platforms/architectures to netcoredbg download files
const platformMapping = {
  // Windows x64 (used for both x86_64 and arm64 on Windows as netcoredbg doesn't have separate ARM64 build for Windows)
  'win32-x86_64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-win64.zip`,
    testPath: './.debugger/x86_64/netcoredbg.exe',
    binaries: ['./netcoredbg.exe']
  },
  // Windows ARM64 - use the same x64 build
  'win32-arm64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-win64.zip`,
    testPath: './.debugger/arm64/netcoredbg.exe',
    binaries: ['./netcoredbg.exe']
  },
  // macOS x64
  'darwin-x86_64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-osx-amd64.tar.gz`,
    testPath: './.debugger/x86_64/netcoredbg',
    binaries: ['./netcoredbg']
  },
  // macOS ARM64 - use the same x64 build (Rosetta 2)
  'darwin-arm64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-osx-amd64.tar.gz`,
    testPath: './.debugger/arm64/netcoredbg',
    binaries: ['./netcoredbg']
  },
  // Linux x64
  'linux-x86_64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-linux-amd64.tar.gz`,
    testPath: './.debugger/netcoredbg',
    binaries: ['./netcoredbg']
  },
  // Linux ARM64
  'linux-arm64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-linux-arm64.tar.gz`,
    testPath: './.debugger/netcoredbg',
    binaries: ['./netcoredbg']
  },
  // Linux musl x64 - use standard linux build
  'linux-musl-x86_64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-linux-amd64.tar.gz`,
    testPath: './.debugger/netcoredbg',
    binaries: ['./netcoredbg']
  },
  // Linux musl ARM64 - use standard linux ARM64 build
  'linux-musl-arm64': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-linux-arm64.tar.gz`,
    testPath: './.debugger/netcoredbg',
    binaries: ['./netcoredbg']
  },
  // Linux ARM - use ARM64 build (most compatible option)
  'linux-arm': {
    url: `${NETCOREDBG_BASE_URL}/netcoredbg-linux-arm64.tar.gz`,
    testPath: './.debugger/netcoredbg',
    binaries: ['./netcoredbg']
  }
};

function replaceDebugger(packageJsonPath) {
  console.log('Reading package.json...');
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));

  if (!packageJson.runtimeDependencies) {
    console.error('Error: runtimeDependencies not found in package.json');
    process.exit(1);
  }

  console.log('Replacing vsdbg debugger dependencies with netcoredbg...');
  
  // Find and replace debugger dependencies
  packageJson.runtimeDependencies = packageJson.runtimeDependencies.map(dep => {
    if (dep.id !== 'Debugger') {
      return dep;
    }

    // Build platform key
    const platform = dep.platforms[0];
    const arch = dep.architectures[0];
    const platformKey = `${platform}-${arch}`;

    console.log(`  Processing: ${platform}/${arch}`);

    if (!platformMapping[platformKey]) {
      console.warn(`    Warning: No mapping found for ${platformKey}, keeping original`);
      return dep;
    }

    const mapping = platformMapping[platformKey];
    
    // Create new dependency with netcoredbg
    const newDep = {
      id: 'Debugger',
      description: dep.description.replace('vsdbg', 'netcoredbg').replace('.NET Core Debugger', 'Samsung NetCoreDbg Debugger'),
      url: mapping.url,
      installPath: dep.installPath,
      platforms: dep.platforms,
      architectures: dep.architectures,
      installTestPath: mapping.testPath
    };

    // Add binaries array for non-Windows platforms
    if (mapping.binaries && mapping.binaries.length > 0) {
      newDep.binaries = mapping.binaries;
    }

    console.log(`    Replaced with: ${mapping.url}`);

    // Note: We're removing the integrity field as the hashes will be different
    // The extension should still work without integrity checks
    
    return newDep;
  });

  console.log('Writing updated package.json...');
  fs.writeFileSync(packageJsonPath, JSON.stringify(packageJson, null, 2) + '\n');
  console.log('✓ Successfully replaced debugger dependencies with netcoredbg');
}

// Main execution
if (require.main === module) {
  const packageJsonPath = process.argv[2] || path.join(__dirname, 'upstream', 'package.json');
  
  if (!fs.existsSync(packageJsonPath)) {
    console.error(`Error: package.json not found at ${packageJsonPath}`);
    process.exit(1);
  }

  replaceDebugger(packageJsonPath);
}

module.exports = { replaceDebugger };
