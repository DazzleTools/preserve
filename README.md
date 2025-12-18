# Preserve

[![Version](https://img.shields.io/github/v/release/djdarcy/preserve)](https://github.com/djdarcy/preserve/releases)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL%20v3-green.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

> **Track files and always get them back to where you need them.**

A cross-platform file preservation tool with path normalization, verification, and restoration capabilities. Preserve tracks where your files came from so you can always restore them - whether to their original location or anywhere else you need them.

## Why another backup tool?

Have you ever had a situation where you ran out of space on a hard-drive and needed to [robocopy](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy) / [rsync](https://rsync.samba.org/) / [move](https://www.gnu.org/software/coreutils/manual/html_node/mv-invocation.html#mv-invocation) an assortment of adhoc folders and files from one drive to another, but you needed an easy way to map those files back to the original source directory later? 

Or perhaps you've needed to copy a batch of folders from one machine to multiple lab computers that all shared a similar folder layout, and you got tired of manually copying the folders one-by-one for each box when there are subtle differences (*pro-tip: [Syncthing](https://syncthing.net/) and [BTSync/Resilio](https://www.resilio.com/sync/download/) are handy but not perfect when there are differences to sort out with [Beyond Compare](https://www.scootersoftware.com/download/download)*). 

Or get frustrated with creating one-off scripts each time files needed to be distributed; and worried whether that copy actually transferred correctly and all files are intact?

Enter `preserve`...

## Features

- **Path Preservation**: Copy or move files with multiple path preservation styles:
  - Relative paths that maintain directory structure (`--rel`)
  - Absolute paths with drive letter preservation (`--abs`)
  - Flat structure with all files in one directory (`--flat`)
- **Verification**: File integrity verification with multiple hash algorithms (MD5, SHA1, SHA256, SHA512)
- **Metadata**: Preserve file attributes (timestamps, permissions, etc.)
- **Manifests**: Detailed operation tracking with automatic versioning for multiple operations
- **Restoration**: Restore files to their original locations with verification
- **DazzleLink**: Optional integration with dazzlelink for enhanced metadata storage and file references
- **Cross-Platform**: Works on Windows, Linux, and macOS

## Installation

```bash
pip install dazzle-preserve
```

**Note**: The PyPI package is named `dazzle-preserve`, but you still import and use it as `preserve`:
```python
import preserve  # Import name stays the same
```

For full functionality on Windows, install with the Windows extras:

```bash
pip install dazzle-preserve[windows]
```

For [dazzlelink](https://github.com/djdarcy/dazzlelink) integration:

```bash
pip install dazzle-preserve[dazzlelink]
```

## Usage

### Basic Usage

**Most common: Backup an entire directory with all subdirectories**

```bash
preserve COPY "C:/my-project" --recursive --rel --includeBase --dst "E:/backup"
```

**Important**: Always use `--recursive` (or `-r`) when copying directories. Without it, preserve will only look for files directly in the source directory, not in subdirectories.

**Copy specific file types from a directory tree**

```bash
preserve COPY --glob "*.docx" --srchPath "C:/documents" --recursive --dst "D:/archive"
```

**Copy files from a list (loadIncludes)**

```bash
preserve COPY --loadIncludes "files-to-copy.txt" --dst "E:/backup" --rel
```

The `files-to-copy.txt` file should contain one file or directory path per line:
```
C:/data/report.docx
C:/projects/myapp/src/main.py
C:/photos/vacation/
```

**Verify backup integrity**

```bash
preserve VERIFY --src "C:/my-project" --dst "E:/backup" --hash SHA256
```

**Restore files to their original locations**

```bash
# Restore latest backup
preserve RESTORE --src "E:/backup"

# List all available restore points
preserve RESTORE --src "E:/backup" --list

# Restore specific operation by number
preserve RESTORE --src "E:/backup" --number 2
```

### Path Preservation Options

- `--rel`: Preserve relative paths
- `--abs`: Preserve absolute paths (with drive letter as directory)
- `--flat`: Flatten directory structure (all files in destination root)
- `--includeBase`: Include base directory name in destination path

### Other Options

- `--hash`: Specify hash algorithm(s) for verification (MD5, SHA1, SHA256, SHA512)
- `--verify`: Verify files after operation
- `--dazzlelink`: Create dazzlelinks to original files
- `--dry-run`: Show what would be done without making changes
- `--overwrite`: Overwrite existing files in destination

See `preserve --help` for full documentation and examples.

## Working with Multiple Operations

Preserve automatically manages manifests when you run multiple operations to the same destination:

### Sequential Operations Example

```bash
# First operation - copies dataset A
preserve COPY "C:/data/dataset-A" -r --includeBase --rel --dst "E:/backup"
# Creates: preserve_manifest.json

# Second operation - copies dataset B
preserve COPY "C:/data/dataset-B" -r --includeBase --rel --dst "E:/backup"
# Auto-migrates first manifest to preserve_manifest_001.json
# Creates: preserve_manifest_002.json

# Third operation - copies dataset C
preserve COPY "C:/data/dataset-C" -r --includeBase --rel --dst "E:/backup"
# Creates: preserve_manifest_003.json
```

### Managing Multiple Manifests

```bash
# List all available restore points
preserve RESTORE --src "E:/backup" --list
# Output:
#   1. preserve_manifest_001.json (2025-09-18 14:30:00, 150 files)
#   2. preserve_manifest_002.json (2025-09-18 14:55:00, 75 files)
#   3. preserve_manifest_003.json (2025-09-18 15:20:00, 200 files)

# Restore specific dataset (e.g., dataset B from operation 2)
preserve RESTORE --src "E:/backup" --number 2

# Restore latest operation (dataset C)
preserve RESTORE --src "E:/backup"

# Restore with short option
preserve RESTORE --src "E:/backup" -n 1  # Restores dataset A
```

### User-Friendly Manifest Naming

You can rename manifests to include descriptions:

```bash
# Rename manifests for clarity (Windows)
ren preserve_manifest_001.json preserve_manifest_001__dataset-A.json
ren preserve_manifest_002.json preserve_manifest_002__dataset-B.json

# On Linux/Mac
mv preserve_manifest_001.json preserve_manifest_001__dataset-A.json

# The descriptions appear in --list output:
preserve RESTORE --src "E:/backup" --list
#   1. preserve_manifest_001__dataset-A.json - dataset-A (2025-09-18 14:30:00, 150 files)
#   2. preserve_manifest_002__dataset-B.json - dataset-B (2025-09-18 14:55:00, 75 files)
```

### Important Notes

- **No Overwrites**: Each operation creates a new manifest, preserving all history
- **Backward Compatible**: Single operations still work exactly as before
- **Auto-Migration**: The system automatically handles the transition from single to multiple manifests
- **Independent Restoration**: Each manifest can be restored independently

## Recommended Workflow for Important Data

For data you really care about, follow this multi-step workflow to ensure end-to-end data integrity:

### Step 1: Pre-Verification (Create baseline hashes)

```bash
# Windows: Use certutil to create SHA256 hashes
cd C:\my-project
for /r %i in (*) do certutil -hashfile "%i" SHA256 >> ..\source-hashes.txt

# Linux/Mac: Use shasum or sha256sum
cd /path/to/my-project
find . -type f -exec sha256sum {} \; > ../source-hashes.txt
```

### Step 2: Copy with Structure Preservation

```bash
# Copy with relative paths and include base directory
preserve COPY "C:/my-project" --recursive --rel --includeBase --dst "E:/backup" --hash SHA256
```

### Step 3: Post-Copy Verification

```bash
# Verify all files match their source
preserve VERIFY --src "C:/my-project" --dst "E:/backup" --hash SHA256 --report verify-report.txt

# Check the report for any mismatches
type verify-report.txt
```

### Step 4: Test Restoration

```bash
# First, do a dry run to see what would be restored
preserve RESTORE --src "E:/backup" --dry-run

# If everything looks correct, restore to a test location
preserve RESTORE --src "E:/backup" --dst "C:/test-restore" --verify
```

#### Understanding RESTORE --dst Behavior

When using `--dst` to restore to a different location, **preserve maintains the backup's directory structure**, not the original source structure. This respects the path style choice (`--rel`, `--abs`, `--flat`) made during backup creation.

**Examples:**

1. **Relative with Base Directory** (`--rel --includeBase`):
   ```bash
   # Backup created with:
   preserve COPY my-project/ --dst backup/ --rel --includeBase
   # Creates: backup/my-project/file.txt

   # Restore to new location:
   preserve RESTORE --src backup/ --dst restored/
   # Result: restored/my-project/file.txt
   ```

2. **Flat Structure** (`--flat`):
   ```bash
   # Backup created with:
   preserve COPY my-project/ --dst backup/ --flat
   # Creates: backup/file.txt (no subdirectories)

   # Restore to new location:
   preserve RESTORE --src backup/ --dst restored/
   # Result: restored/file.txt (maintains flat structure)
   ```

3. **Absolute Paths** (`--abs`):
   ```bash
   # Backup created with:
   preserve COPY C:/data/file.txt --dst backup/ --abs
   # Creates: backup/C/data/file.txt

   # Restore to new location:
   preserve RESTORE --src backup/ --dst restored/
   # Result: restored/C/data/file.txt (preserves full path structure)
   ```

**Key Point**: The restored structure mirrors what's in your backup directory, preserving your original backup organization choice.

### Step 5: Validate Restoration

```bash
# Compare restored files with original hashes
# Windows
cd C:\test-restore\my-project
for /r %i in (*) do certutil -hashfile "%i" SHA256 >> ..\..\restored-hashes.txt
fc ..\..\source-hashes.txt ..\..\restored-hashes.txt

# Linux/Mac
cd /path/to/test-restore/my-project
find . -type f -exec sha256sum {} \; > ../../restored-hashes.txt
diff ../../source-hashes.txt ../../restored-hashes.txt
```

### Step 6: Source Cleanup (Only after validation)

```bash
# Only remove originals after all verifications pass
# Keep the preserve_manifest*.json files in the backup for future restoration
```

**Important**: Never delete your source files until you've verified the backup AND successfully tested restoration.

## What's New

See [CHANGELOG.md](CHANGELOG.md) for a detailed history of changes.

### Latest Release (v0.5.x)

This is a maintenance development cycle. The current goal is stabilize and fully test all major uses of preserve (COPY, MOVE, RESTORE, and VERIFY) with no missing flags / functionality before 0.6.x.

### Recent Highlights
- **Advanced Filtering**: Exclude patterns, depth control, time-based selection
- **Three-Way Verification**: Source, destination, or both forms of verifications during restore operations
- **Sequential Manifests**: Support for multiple operations to same destination
- **GitRepoKit Versioning**: Automated version management with git hooks
- **Document Tidying**: Improving versioning, README, CHANGELOG, and other docs

## Contributing

Contributions are welcome! Feel free to submit a pull request.

Like the project?

[!["Buy Me A Coffee"](https://camo.githubusercontent.com/0b448aabee402aaf7b3b256ae471e7dc66bcf174fad7d6bb52b27138b2364e47/68747470733a2f2f7777772e6275796d6561636f666665652e636f6d2f6173736574732f696d672f637573746f6d5f696d616765732f6f72616e67655f696d672e706e67)](https://www.buymeacoffee.com/djdarcy)

## Acknowledgments

- [dazzlelink](https://github.com/djdarcy/dazzlelink) - Enhanced metadata storage and file references
- [GitRepoKit](https://github.com/djdarcy/GitRepoKit) - Automated version management system
- Community contributors - Testing, feedback, and improvements

## License

preserve, aka preserve.py, Copyright (C) 2025 Dustin Darcy

This program is free software: you can redistribute it and/or modify it under the terms of the [GNU General Public License](LICENSE) as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see http://www.gnu.org/licenses/.
