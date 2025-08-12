# vscode-csharp-autobuild

![Open VSX Version](https://img.shields.io/open-vsx/v/dotnetdev-kr-custom/csharp)
[![GitHub Release](https://img.shields.io/github/v/release/rkttu/vscode-csharp-autobuild)](https://github.com/rkttu/vscode-csharp-autobuild/releases)
[![Build and Release](https://github.com/rkttu/vscode-csharp-autobuild/actions/workflows/build-and-release.yml/badge.svg)](https://github.com/rkttu/vscode-csharp-autobuild/actions/workflows/build-and-release.yml)

Automatically build and publish upstream builds of the dotnet/vscode-csharp Extension.

## Overview

This project is an automatic build mirroring system for the [dotnet/vscode-csharp](https://github.com/dotnet/vscode-csharp) extension. It automatically builds new versions of the upstream repository and publishes them as releases, making them available for various environments and use cases.

## Background

Unlike the C# Dev Kit, this project provides automatic builds that do not fall under Microsoft's commercial licensing restrictions. The builds are made available through GitHub releases to ensure wide accessibility while avoiding potential confusion by not registering on the Open VSX registry.

## Key Features

- 🔄 Automatic builds from upstream dotnet/vscode-csharp repository
- 📦 Platform-specific VSIX packages
- 🆓 Free from Microsoft commercial licensing restrictions
- 🚀 Regular releases available through GitHub
- ⏰ Automated monitoring every 6 hours for new upstream releases

## How It Works

This project automatically monitors the upstream [dotnet/vscode-csharp](https://github.com/dotnet/vscode-csharp) repository for new tags every 6 hours. When a new tag is detected, the automated build process is triggered, which:

1. 🔍 **Scans for new tags** - Checks the upstream repository tag list every 6 hours
2. 🏗️ **Triggers automatic build** - Initiates build process when new tags are found
3. 📦 **Generates VSIX packages** - Creates both main and platform-specific packages
4. 🚀 **Publishes releases** - Makes the built packages available through GitHub releases

This ensures that new versions of the C# extension are available shortly after they are released upstream, typically within 6 hours of the original release.

## Installation

To install the extension, follow these steps in order:

1. **Download the VSIX files** from the [Releases](https://github.com/rkttu/vscode-csharp-autobuild/releases) page
   - Download the main VSIX file (usually named `csharp-*.vsix`)
   - Download the platform-specific VSIX file for your system

2. **Install the main extension**

   ```bash
   code --install-extension csharp-*.vsix
   ```

3. **Install the platform-specific extension**

   ```bash
   code --install-extension csharp-*-platform-specific.vsix
   ```

4. **Reload VS Code window**
   - Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS)
   - Type "Developer: Reload Window" and press Enter
   - Or simply restart VS Code

## License

This project adopts the same license as the original dotnet/vscode-csharp project. Please refer to the [LICENSE](LICENSE) file for details.

## Disclaimer

This is an unofficial build of the dotnet/vscode-csharp extension. All rights to the original source code belong to Microsoft and the .NET Foundation. This project only provides automated builds for convenience and accessibility.

## Contributing

This project is primarily automated. If you encounter issues with the builds, please:

1. Check if the issue exists in the upstream [dotnet/vscode-csharp](https://github.com/dotnet/vscode-csharp) repository
2. Report upstream issues to the original repository
3. For build-specific issues, feel free to open an issue in this repository

## Related Projects

- [dotnet/vscode-csharp](https://github.com/dotnet/vscode-csharp) - Original upstream repository
- [Microsoft C# Dev Kit](https://marketplace.visualstudio.com/items?itemName=ms-dotnettools.csdevkit) - Official Microsoft C# extension (commercial license)
