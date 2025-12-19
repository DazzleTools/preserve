# Preserve CLI Reference

This document covers the destination awareness features added in v0.7.x.

## Destination Awareness (v0.7.x)

### Overview

Preserve now scans destination directories before COPY/MOVE operations to detect conflicts and provide pre-operation reporting.

### Conflict Resolution Options

Use `--on-conflict` to specify how to handle files that already exist at the destination:

| Mode | Behavior |
|------|----------|
| `skip` | Keep destination file, skip source |
| `overwrite` | Replace destination with source |
| `newer` | Keep whichever file is newer (by mtime) |
| `larger` | Keep whichever file is larger |
| `rename` | Keep both, rename source with suffix |
| `fail` | Abort operation if any conflicts |
| `ask` | Prompt user for each conflict (interactive) |

```bash
# Skip files that already exist
preserve COPY src -r --rel --dst dest --on-conflict=skip

# Overwrite older files
preserve COPY src -r --rel --dst dest --on-conflict=newer

# Keep larger version
preserve COPY src -r --rel --dst dest --on-conflict=larger
```

### Incorporating Identical Files

Use `--incorporate-identical` to resume interrupted operations. Files that already exist at the destination with matching content are marked as "incorporated" rather than re-copied.

```bash
# Resume an interrupted copy
preserve COPY src -r --rel --dst dest --incorporate-identical
```

### Scan-Only Mode

Use `--scan-only` to analyze the destination without performing any operations:

```bash
# See what would happen without making changes
preserve COPY src -r --rel --dst dest --scan-only
```

Output shows:
- Files that would be new
- Files that would conflict
- Identical files that could be incorporated

## Path Mode Warnings (v0.7.x)

### Overview

Preserve detects common path mode mistakes and warns before proceeding.

### Warning Types

#### 1. Absolute Path Overlap (Blocking)

When using `--abs` mode, preserve warns if the destination path contains components from the source path, which could cause unwanted duplication:

```
WARNING: Potential path duplication detected with --abs mode

Source: D:\photos\vacation
Dest:   E:\backup\photos\vacation

With --abs, files will be preserved as:
  E:\backup\photos\vacation\D\photos\vacation\image.jpg
                            ^^^^^^^^^^^^^^^^^^^^^^^
                            Duplicated path structure

This is usually not intended. Consider:
  --rel mode: E:\backup\photos\vacation\image.jpg
  Different dest: E:\backup\D_drive_photos
```

#### 2. Relative Without Base (Informational)

When using `--rel` without `--includeBase`, preserve shows what the result will look like:

```
NOTE: Using --rel without --includeBase

Files will be preserved without their parent folder name:
  source/file.txt -> dest/file.txt  (not dest/source/file.txt)

Add --includeBase to include the source folder name.
```

### Suppressing Warnings

```bash
# Skip all path mode warnings
preserve COPY src -r --abs --dst dest --no-path-warning
```

## CLEANUP Command (v0.7.x)

### Overview

The CLEANUP command helps recover from interrupted MOVE operations where some files were copied but source deletion was incomplete.

### Modes

#### Status Mode (Default)

Analyze the state of a partial move without making changes:

```bash
preserve CLEANUP dest --mode status
```

Shows:
- Files successfully moved (exist at dest, deleted from source)
- Files partially moved (exist at both locations)
- Files not moved (exist only at source)

#### Complete Mode

Finish an interrupted move by copying remaining files and deleting sources:

```bash
# Preview what would happen
preserve CLEANUP dest --mode complete --dry-run

# Actually complete the move
preserve CLEANUP dest --mode complete
```

#### Rollback Mode

Undo a partial move by restoring files to the source:

```bash
# Preview what would happen
preserve CLEANUP dest --mode rollback --dry-run

# Actually rollback
preserve CLEANUP dest --mode rollback
```

### Options

| Option | Description |
|--------|-------------|
| `--mode` | Operation mode: `status`, `complete`, or `rollback` |
| `--dry-run` | Show what would happen without making changes |
| `--manifest` | Specify manifest file (default: auto-detect) |
| `-v, --verbose` | Show detailed progress |

## Quick Reference

### New Flags in v0.7.x

| Flag | Command | Description |
|------|---------|-------------|
| `--on-conflict=MODE` | COPY, MOVE | Conflict resolution strategy |
| `--incorporate-identical` | COPY, MOVE | Resume interrupted operations |
| `--scan-only` | COPY, MOVE | Analyze without executing |
| `--no-path-warning` | COPY, MOVE | Skip path mode warnings |

### New Commands in v0.7.x

| Command | Description |
|---------|-------------|
| `CLEANUP` | Recover from interrupted MOVE operations |

## Examples

### Resume Interrupted Copy

```bash
# Original copy was interrupted
preserve COPY /data -r --rel --dst /backup

# Resume, incorporating already-copied files
preserve COPY /data -r --rel --dst /backup --incorporate-identical --on-conflict=skip
```

### Safe Migration with Conflict Handling

```bash
# First, scan to see what would happen
preserve MOVE /old -r --rel --dst /new --scan-only

# Then execute, keeping newer versions
preserve MOVE /old -r --rel --dst /new --on-conflict=newer
```

### Recover from Failed Move

```bash
# Check the state
preserve CLEANUP /new --mode status

# Complete the move if most files transferred
preserve CLEANUP /new --mode complete

# Or rollback if you want to start over
preserve CLEANUP /new --mode rollback
```

## Related Issues

- #39 - Destination-aware operations
- #42 - Smart path mode detection
- #43 - CLEANUP command
- #46 - Configurable time comparison for --on-conflict=newer (planned)
