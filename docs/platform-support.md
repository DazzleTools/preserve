# Platform Support

Preserve is designed to work across Windows, Linux, and macOS. This document covers platform-specific details, known quirks, and testing status.

## Support Matrix

| Platform | Status | Tested | Notes |
|----------|--------|--------|-------|
| **Windows 10/11** | Supported | Yes | Primary development platform |
| **Linux** (Ubuntu, Debian, etc.) | Supported | Yes | Tested on Ubuntu 22.04+ |
| **macOS** | Supported | Community | Needs more testing - [help wanted](#help-us-test) |
| **BSD** (FreeBSD, OpenBSD) | Unknown | No | Likely works - [help wanted](#help-us-test) |
| **WSL/WSL2** | Supported | Yes | Works with Windows paths |

## Platform-Specific Behavior

### Windows

- **Junctions**: Windows NTFS junctions are detected and handled during MOVE operations
- **Drive Letters**: Absolute path mode (`--abs`) preserves drive letters as directories (e.g., `C:\data\file.txt` → `backup/C/data/file.txt`)
- **Long Paths**: Supports Windows long paths (260+ characters) when enabled in Windows settings
- **Permissions**: File permissions are preserved where possible; some attributes require administrator privileges

### Linux

- **Symlinks**: Symbolic links are detected during cycle detection
- **Permissions**: Full POSIX permission preservation (owner, group, mode)
- **Case Sensitivity**: Filesystem is typically case-sensitive; preserve respects this

### macOS

- **Symlinks**: Should work like Linux symlinks
- **Case Sensitivity**: Default HFS+/APFS is case-insensitive but case-preserving
- **Extended Attributes**: Resource forks and extended attributes may need additional handling

> **Note**: macOS support is based on code compatibility with Linux. We welcome testing and feedback from macOS users.

### BSD

- **Expected Behavior**: Should work similarly to Linux
- **Untested**: No direct testing has been performed

## Known Quirks

### Path Handling

| Scenario | Windows | Linux/macOS |
|----------|---------|-------------|
| Path separator | `\` (backslash) | `/` (forward slash) |
| Drive letters | `C:\`, `D:\`, etc. | N/A (mount points) |
| Root path | `C:\` | `/` |
| Home directory | `%USERPROFILE%` | `~` or `$HOME` |

Preserve normalizes paths internally and handles cross-platform path differences automatically.

### Symbolic Links vs Junctions

| Feature | Windows Junction | Windows Symlink | Unix Symlink |
|---------|------------------|-----------------|--------------|
| Target type | Directory only | File or directory | File or directory |
| Admin required | No | Yes (or Developer Mode) | No |
| Relative targets | No | Yes | Yes |
| Cross-volume | No | Yes | Yes |

Preserve's `--link-handling` flag works with all link types.

## Installation by Platform

### Windows

```bash
pip install dazzle-preserve[windows]
```

The `[windows]` extra includes `pywin32` for enhanced Windows functionality.

### Linux / macOS / BSD

```bash
pip install dazzle-preserve
```

### All Platforms with Dazzlelink

```bash
pip install dazzle-preserve[dazzlelink]
```

## Help Us Test!

We'd love help testing preserve on platforms we don't have regular access to:

- **macOS** (Intel and Apple Silicon)
- **BSD variants** (FreeBSD, OpenBSD, NetBSD)
- **Other Linux distributions**
- **ARM-based systems**

### How to Help

1. Install preserve on your platform
2. Run some basic operations:
   ```bash
   # Create a test directory with some files
   mkdir -p test-src/subdir
   echo "test" > test-src/file.txt
   echo "nested" > test-src/subdir/nested.txt

   # Test COPY with verification
   preserve COPY test-src/ --dst test-backup/ --rel --includeBase -r --hash SHA256

   # Test VERIFY
   preserve VERIFY --src test-src/ --dst test-backup/ --hash SHA256

   # Test RESTORE
   preserve RESTORE --src test-backup/ --dst test-restored/

   # Compare results
   diff -r test-src/ test-restored/test-src/
   ```
3. Share your results in our [Platform Testing Discussion](https://github.com/DazzleTools/preserve/discussions/54)

### What to Report

- Operating system and version
- Python version (`python --version`)
- Preserve version (`preserve --version`)
- Any errors or unexpected behavior
- Whether all basic operations worked

## Resources

- [Python Downloads](https://www.python.org/downloads/) - Get Python for your platform
- [Windows Terminal](https://aka.ms/terminal) - Modern terminal for Windows
- [Homebrew](https://brew.sh/) - Package manager for macOS (useful for Python)

## See Also

- [CLI Reference](cli-reference.md) - Full command documentation
- [GitHub Discussions](https://github.com/DazzleTools/preserve/discussions) - Community support
- [GitHub Issues](https://github.com/DazzleTools/preserve/issues) - Bug reports and feature requests
