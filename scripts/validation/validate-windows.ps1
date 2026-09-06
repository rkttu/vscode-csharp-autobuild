[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('x64', 'arm64')]
    [string] $Architecture
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$source = Join-Path $repo 'validation-inputs/netcoredbg'
$runtime = Join-Path $repo 'validation-inputs/runtime'
$root = $env:VALIDATION_ROOT
if (-not $root -or -not $env:DOTNET_INSTALL_DIR) {
    throw 'VALIDATION_ROOT and DOTNET_INSTALL_DIR must point to isolated validation directories.'
}
$evidence = Join-Path $root 'evidence'
$build = Join-Path $root 'build'
$package = Join-Path $root 'package/netcoredbg'
$dotnet = Join-Path $env:DOTNET_INSTALL_DIR 'dotnet.exe'
New-Item -ItemType Directory -Force $evidence, $build, $package | Out-Null

function Invoke-Logged {
    param([string] $File, [string[]] $Arguments, [string] $LogName)
    & $File @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $evidence $LogName) | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$File failed with exit code $LASTEXITCODE; see $LogName"
    }
}

function Write-Json {
    param($Value, [string] $Path)
    ConvertTo-Json -InputObject $Value -Depth 30 | Set-Content -Encoding utf8NoBOM $Path
}

$status = [ordered]@{
    success = $false
    stage = 'environment'
    architecture = $Architecture
    scope = 'Standalone source build and DAP launch; no VSIX, IDE, attach, or publication validation.'
    netcoredbgTag = $env:NETCOREDBG_TAG
    netcoredbgCommit = $env:NETCOREDBG_SHA
    coreclrCommit = $env:CORECLR_SHA
    sdk8 = $env:SDK8_VERSION
    sdk10 = $env:SDK10_VERSION
    dbgshimVersion = $env:DBGSHIM_VERSION
    runnerImage = $env:ImageOS
    runnerImageVersion = $env:ImageVersion
    workflowCommit = $env:GITHUB_SHA
    runId = $env:GITHUB_RUN_ID
    sourceUnchanged = $false
    runtimeTests = @()
    error = $null
}

try {
    $osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    if ($osArch -ne $Architecture) { throw "Expected native $Architecture OS; found $osArch" }
    if ((& git -C $source rev-parse HEAD).Trim() -ne $env:NETCOREDBG_SHA) { throw 'Samsung source SHA mismatch' }
    if ((& git -C $runtime rev-parse HEAD).Trim() -ne $env:CORECLR_SHA) { throw 'CoreCLR source SHA mismatch' }

    $env:DOTNET_ROOT = $env:DOTNET_INSTALL_DIR
    Set-Item -Path "Env:DOTNET_ROOT_$($Architecture.ToUpperInvariant())" -Value $env:DOTNET_ROOT
    $env:PATH = "$($env:DOTNET_ROOT);$($env:PATH)"
    $env:DOTNET_CLI_HOME = Join-Path $root 'dotnet-home'
    $env:NUGET_PACKAGES = Join-Path $root 'nuget-packages'
    $env:NUGET_HTTP_CACHE_PATH = Join-Path $root 'nuget-http-cache'
    $env:DOTNET_CLI_USE_MSBUILD_SERVER = '0'
    $env:MSBUILDDISABLENODEREUSE = '1'
    $env:DirectoryBuildTargetsPath = Join-Path $PSScriptRoot 'ManagedDependencies.targets'
    Write-Json @{ sdk = @{ version = $env:SDK10_VERSION; rollForward = 'disable' } } (Join-Path $root 'global.json')

    Invoke-Logged python @('--version') 'python-version.log'
    Invoke-Logged cmake @('--version') 'cmake-version.log'
    Invoke-Logged $dotnet @('--info') 'dotnet-info.log'
    Invoke-Logged $dotnet @('--list-runtimes') 'dotnet-runtimes.log'
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    Invoke-Logged $vswhere @('-all', '-products', '*', '-format', 'json') 'visual-studio.json'
    Invoke-Logged python @((Join-Path $PSScriptRoot 'audit.py'), 'snapshot', '--source', $source,
        '--output', (Join-Path $evidence 'source-before.json')) 'source-snapshot.log'
    Invoke-Logged python @((Join-Path $PSScriptRoot 'audit.py'), 'pe', '--arch', $Architecture,
        '--output', (Join-Path $evidence 'dotnet-architecture.json'), $dotnet) 'dotnet-architecture.log'

    $status.stage = 'configure'
    $cmakeArch = if ($Architecture -eq 'arm64') { 'ARM64' } else { 'x64' }
    Invoke-Logged cmake @('-S', $source, '-B', $build, '-G', 'Visual Studio 17 2022', '-A', $cmakeArch,
        '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DCMAKE_BUILD_TYPE=Release',
        "-DCMAKE_INSTALL_PREFIX=$package", "-DCORECLR_DIR=$runtime/src/coreclr", "-DDOTNET_DIR=$($env:DOTNET_ROOT)",
        "-DCLR_CMAKE_HOST_ARCH=$Architecture", "-DCLR_CMAKE_TARGET_ARCH=$Architecture", '-DRID_NAME=win',
        '-DBUILD_MANAGED=OFF', '-DINTEROP_DEBUGGING=OFF', '-DBUILD_TESTING=OFF') 'configure.log'

    # Upstream places managed project.assets.json beside native .vcxproj files.
    # MSVC's corguids project can then read the managed assets as its own NuGet
    # inputs. Build native targets first and publish managed files separately.
    $status.stage = 'native-build'
    Invoke-Logged cmake @('--build', $build, '--config', 'Release', '--target', 'netcoredbg',
        '--parallel', '4', '--', '/nodeReuse:false') 'build.log'
    $status.stage = 'install'
    Invoke-Logged cmake @('--install', $build, '--config', 'Release') 'install.log'
    Copy-Item (Join-Path $build 'CMakeCache.txt') $evidence

    $status.stage = 'managed-build'
    $managed = Join-Path $root 'managed'
    $managedOutput = Join-Path $managed 'publish'
    New-Item -ItemType Directory -Force $managed | Out-Null
    Push-Location $root
    try {
        Invoke-Logged $dotnet @('publish', (Join-Path $source 'src/managed/ManagedPart.csproj'),
            '-r', "win-$Architecture", '--self-contained', '-c', 'Release', '-o', $managedOutput,
            "-p:BaseIntermediateOutputPath=$managed/obj/", "-p:BaseOutputPath=$managed/bin/",
            '-p:UseDbgShimDependency=true') 'managed-build.log'
    } finally { Pop-Location }
    $managedFiles = @('dbgshim.dll', 'ManagedPart.dll', 'Microsoft.CodeAnalysis.dll',
        'Microsoft.CodeAnalysis.CSharp.dll', 'Microsoft.CodeAnalysis.Scripting.dll', 'Microsoft.CodeAnalysis.CSharp.Scripting.dll')
    foreach ($name in $managedFiles) { Copy-Item (Join-Path $managedOutput $name) $package }

    $assetsPath = Join-Path $managed 'obj/project.assets.json'
    $assets = Get-Content -Raw $assetsPath | ConvertFrom-Json
    Write-Json $assets.libraries (Join-Path $evidence 'resolved-libraries.json')
    $shim = $assets.libraries.PSObject.Properties.Name | Where-Object { $_ -eq "Microsoft.Diagnostics.DbgShim/$($env:DBGSHIM_VERSION)" }
    if (-not $shim) { throw 'The external dbgshim version override was not applied.' }

    $status.stage = 'package-inspection'
    $required = @('netcoredbg.exe', 'dbgshim.dll', 'ManagedPart.dll', 'Microsoft.CodeAnalysis.dll',
        'Microsoft.CodeAnalysis.CSharp.dll', 'Microsoft.CodeAnalysis.Scripting.dll', 'Microsoft.CodeAnalysis.CSharp.Scripting.dll')
    foreach ($name in $required) {
        if (-not (Test-Path (Join-Path $package $name))) { throw "Missing installed file: $name" }
    }
    # Preserve component notices with this experimental artifact. It is not a release package.
    $notices = Join-Path $package 'notices'
    New-Item -ItemType Directory -Force $notices | Out-Null
    Copy-Item (Join-Path $source 'LICENSE') (Join-Path $notices 'Samsung-netcoredbg-LICENSE')
    Copy-Item (Join-Path $source 'third_party/linenoise-ng/LICENSE') (Join-Path $notices 'linenoise-ng-LICENSE')
    Copy-Item (Join-Path $source 'third_party/json/LICENSE.MIT') (Join-Path $notices 'json-LICENSE.MIT')
    Copy-Item (Join-Path $runtime 'LICENSE.TXT') (Join-Path $notices 'dotnet-runtime-LICENSE.TXT')
    Get-ChildItem $env:NUGET_PACKAGES -Recurse -File |
        Where-Object { $_.Name -match '^(LICENSE|COPYING|THIRD-PARTY-NOTICES)' } |
        ForEach-Object {
            $relative = [IO.Path]::GetRelativePath($env:NUGET_PACKAGES, $_.FullName)
            $target = Join-Path $notices "nuget/$relative"
            New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
            Copy-Item $_.FullName $target
        }
    # Run from a fresh copy, not the CMake installation directory.
    $relocated = Join-Path $root 'relocated/netcoredbg'
    New-Item -ItemType Directory -Force $relocated | Out-Null
    Copy-Item (Join-Path $package '*') $relocated -Recurse
    $debugger = Join-Path $relocated 'netcoredbg.exe'
    Invoke-Logged python @((Join-Path $PSScriptRoot 'audit.py'), 'pe', '--arch', $Architecture,
        '--output', (Join-Path $evidence 'debugger-architectures.json'), $debugger,
        (Join-Path $relocated 'dbgshim.dll')) 'debugger-architectures.log'
    Invoke-Logged $debugger @('--version') 'debugger-version.log'

    $status.stage = 'runtime-tests'
    $failedTests = @()
    foreach ($version in @('8', '10')) {
        $fixture = Join-Path $root "fixture-net$version"
        New-Item -ItemType Directory -Force $fixture | Out-Null
        Copy-Item (Join-Path $PSScriptRoot 'fixture/*') $fixture
        $sdkVersion = if ($version -eq '8') { $env:SDK8_VERSION } else { $env:SDK10_VERSION }
        Write-Json @{ sdk = @{ version = $sdkVersion; rollForward = 'disable' } } (Join-Path $fixture 'global.json')
        $test = [ordered]@{ runtime = $version; sdk = $sdkVersion; success = $false; error = $null }
        Push-Location $fixture
        try {
            $observedSdk = (& $dotnet --version).Trim()
            if ($LASTEXITCODE -ne 0 -or $observedSdk -ne $sdkVersion) { throw "Expected SDK $sdkVersion; found $observedSdk" }
            Invoke-Logged $dotnet @('build', 'Probe.csproj', '-c', 'Debug', '-o', 'output', "-p:ValidationTargetFramework=net$version.0") "fixture-net$version-build.log"
            Invoke-Logged $dotnet @((Join-Path $fixture 'output/Probe.dll')) "fixture-net$version-direct.log"
            Invoke-Logged python @((Join-Path $PSScriptRoot 'dap_probe.py'), '--engine', 'netcoredbg',
                '--debugger', $debugger, '--program', (Join-Path $fixture 'output/Probe.dll'),
                '--source', (Join-Path $fixture 'Program.cs'), '--expected-arch', $Architecture,
                '--expected-runtime', $version, '--log', (Join-Path $evidence "dap-net$version.jsonl"),
                '--result', (Join-Path $evidence "dap-net$version-result.json")) "dap-net$version-console.log"
            $test.success = $true
        } catch {
            $test.error = $_.Exception.Message
            $failedTests += "net$version"
        } finally {
            Pop-Location
            $status.runtimeTests += $test
        }
    }
    if ($failedTests.Count) { throw "Runtime tests failed: $($failedTests -join ', ')" }
    $status.success = $true
    $status.stage = 'complete'
} catch {
    $status.error = $_.Exception.Message
    Write-Host "Validation failed at $($status.stage): $($status.error)"
} finally {
    $cache = Join-Path $build 'CMakeCache.txt'
    if (Test-Path $cache) { Copy-Item $cache $evidence }
    $before = Join-Path $evidence 'source-before.json'
    if (Test-Path $before) {
        try {
            Invoke-Logged python @((Join-Path $PSScriptRoot 'audit.py'), 'compare', '--source', $source,
                '--before', $before, '--output', (Join-Path $evidence 'source-integrity.json')) 'source-integrity.log'
            $status.sourceUnchanged = $true
        } catch {
            $status.success = $false
            $status.error = "$($status.error) Source integrity failed: $($_.Exception.Message)"
        }
    }
    $hashes = @(Get-ChildItem $package -Recurse -File | ForEach-Object {
        @{ file = [IO.Path]::GetRelativePath($package, $_.FullName); sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    Write-Json $hashes (Join-Path $evidence 'package-sha256.json')
    Write-Json $status (Join-Path $evidence 'result.json')
    if ($env:GITHUB_STEP_SUMMARY) {
        @"
## Windows $Architecture netcoredbg validation

- Passed: $($status.success)
- Last stage: $($status.stage)
- Original Samsung files unchanged: $($status.sourceUnchanged)
- Samsung tag: $($status.netcoredbgTag)
- Samsung commit: $($status.netcoredbgCommit)
- Error: $($status.error)

See the artifact's result.json, DAP results, source-integrity.json, and logs.
Scope: standalone debugger validation; no VSIX, IDE, attach, or publication checks.
"@ | Add-Content -Encoding utf8 $env:GITHUB_STEP_SUMMARY
    }
}
if (-not $status.success) { exit 1 }
