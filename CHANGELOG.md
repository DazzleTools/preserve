# 📜 CHANGELOG.md - Preserve

All notable changes to this project will be documented in this file. This project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

## [0.6.2] - 2025-12-17

### Added
- **`--ignore` flag for pre-flight checks** (#40, #41)
  - `--ignore space` - Skip low disk space warnings and proceed with operation
  - `--ignore permissions` - Skip permission pre-flight checks (rely on atomic copy-verify-delete)
  - Comma-separated: `--ignore space,permissions`
- **Interactive prompting for soft warnings** (MOVE operations)
  - When low disk space is detected, prompts "Continue anyway? [y/N]"
  - Non-interactive mode (piped input) fails safely without `--ignore`

### Fixed
- **Smarter disk space checking logic**
  - Previous: 10% of transfer size as margin (flawed - 91GB transfer with 100GB free would fail)
  - New: `recommended_free = max(1GB, transfer_size * 5%)`
  - Hard fail only when transfer literally won't fit
  - Soft warning when remaining space would be below recommended minimum
- **Pre-flight check return types** - Now returns `(all_ok, hard_issues, soft_issues, space_status)` for better handling

### Changed
- MOVE operations use atomic two-phase approach: copy ALL → verify ALL → delete sources
- Space status now returns "OK", "SOFT_WARNING", or "HARD_FAIL" instead of boolean

## [0.6.1] - 2025-12-17

### Added
- **Pre-flight disk space checking** (#40)
  - Validates destination has sufficient space before MOVE/COPY operations
  - Prevents partial transfers due to disk full errors
- **Permission error handling** (#41)
  - Tests write permissions before destructive MOVE operations
  - Clear error messages with remediation suggestions

## [0.6.0] - 2025-12-16

### Added
- **Link Creation on MOVE** (`--create-link` / `-L`)
  - Create filesystem links from source to destination after move
  - Supported link types: `junction` (Windows NTFS), `soft` (symlink), `hard`, `auto`
  - Enables moving large directories (e.g., model caches) while maintaining app compatibility
  - Example: `preserve MOVE "C:\cache\hub" -r --abs --dst "E:\cache" -L junction`
- **Link-aware RESTORE**
  - Automatically detects links at restore destinations
  - Tracks links created by preserve in manifest (`link_result` field)
  - Safely removes links before restoring files
  - Shows clear warnings for untracked links
- **New module `preservelib/links.py`**
  - Cross-platform link detection, creation, and removal
  - Functions: `create_link()`, `remove_link()`, `is_link()`, `detect_link_type()`, `verify_link()`
- **Unit tests for link functionality** (`tests/test_create_link.py`)
  - 20 tests covering junction, symlink, hard link operations
  - CLI argument parsing tests

### Changed
- Manifest schema extended with optional `link_result` field (backward compatible, no version bump)
- MOVE handler now supports link creation after successful file transfer
- RESTORE handler checks for and handles links before restoration

## [0.5.2] - 2025-09-21

### Fixed
- **Subdirectory preservation bug** with `--includeBase` flag (#32) - Files in subdirectories are now correctly preserved with their structure intact
- **RESTORE --dst functionality** (#30) - The `--dst` flag now properly overrides destination paths during restoration
- **Help display regression** - Restored user-friendly examples in help output

### Added
- **Unified Verbosity System** (#9)
  - Progressive verbosity levels: quiet, normal, `-v`, `-vv`, `-vvv`
  - Color-coded output: ✅ success, ❌ errors, ⚠️ warnings, ⊖ skipped
  - Consistent flags across all operations (COPY, MOVE, VERIFY, RESTORE)
  - Parent parser pattern ensures flags work in any position
- **OutputFormatter Class**
  - Structured output with automatic color detection
  - Cross-platform color support with graceful fallback
  - Context-aware message formatting
- **Test Coverage Improvements**
  - Comprehensive test suite for path preservation (15 tests)
  - Test coverage for RESTORE --dst functionality
  - Test scripts for verbosity system validation
- Test coverage for `--loadIncludes` functionality
- End-to-end test for recommended workflow: backup → verify → restore → validate cycle (test_recommended_workflow.py)
- Detailed `--loadIncludes` file format documentation in README
- Complete step-by-step workflow with exact commands for critical data preservation
- Platform-specific hash verification commands (certutil for Windows, sha256sum for Linux/Mac)

### Improved
- README reorganized with most common use cases first
- Clear documentation about `--recursive` flag requirement for directories
- Enhanced Recommended Workflow section with runnable commands for each step
- Better explanation of verification and restoration process
- Unified argument parsing with parent parser pattern
- Improved logging configuration based on effective verbosity

## [0.5.1] - 2025-09-20

### Changed
- Separated changelog from README for better organization (#14)
- README now references CHANGELOG.md for version history
- Enhanced README with improved badges showing version, Python support, license, and platform compatibility

### Improved
- README structure focuses on features and usage
- Version badges now link to proper GitHub repository
- Added Python version requirement badge (3.8+)
- Added platform compatibility badge

## [0.5.0] - 2025-09-20

### Added
- **GitRepoKit Versioning System**: Integrated automated version management with git hooks
  - Version format: `VERSION_BRANCH_BUILD-YYYYMMDD-COMMITHASH` (e.g., `0.5.0_main_23-20250920-abc12345`)
  - Automatic version updates on every commit via pre-commit hooks
  - Full build traceability with branch, build number, date, and commit hash
  - PEP 440 compliant versions for pip/setuptools compatibility
  - Run `./scripts/install-hooks.sh` to enable automatic versioning
- **Version Command**: Run `preserve --version` to see full version details
- **Single Source of Truth**: All version references now come from `preserve/version.py`

### Fixed
- Help system duplication when running `preserve` with no arguments (#15)
- Help system regression from previous versions (#19)
- Hardcoded version "0.3.0" in CLI description now uses dynamic version

### Added
- Test coverage for CLI help system to prevent regressions
- Module entry point (`__main__.py`) for `python -m preserve` support
- Three-level help system:
  1. `preserve` (no args) - Friendly introduction with examples
  2. `preserve -h` - Standard argparse help with examples in epilog
  3. `preserve COMMAND --help` - Command-specific help with examples

### Improved
- Help examples reorganized with most common use case first
- Command help now shows examples at bottom (epilog) instead of top
- Example commands show flags in logical order for easy copy-paste

## [0.4.0] - 2025-09-19

### Added
- **Advanced Filtering**: Added `--exclude` pattern support for glob-based file exclusion
- **Depth Control**: Added `--max-depth` option for limiting directory traversal depth
- **Time-Based Selection**: Enhanced `--newer-than` with support for:
  - Relative times: `--newer-than "2 hours"`, `--newer-than "30 days"`
  - Absolute dates: `--newer-than "2025-01-15"`, `--newer-than "2025-01-15 14:30:00"`
  - Unix timestamps: `--newer-than "1736899200"`

### Fixed
- MagicMock directory creation in tests
- Version display now shows actual version instead of placeholder

## [0.3.0] - 2025-09-18

### Added
- **Three-Way Verification**: Added `--verify` flag to RESTORE operation for comprehensive verification before restoration
- **Numbered Manifest Support**: VERIFY command now fully supports the numbered manifest system (_001, _002, etc.)
- Sequential manifest numbering system (preserve_manifest_001.json, _002, etc.)
- RESTORE --list option to show all available restore points
- RESTORE --number/-n option to restore from specific operation
- Support for user descriptions in manifest filenames (e.g., _001__description.json)
- Colored terminal output for warnings and errors (with graceful fallback)
- Auto-migration of existing single manifests to numbered format

### Fixed
- **Critical**: Fixed manifest overwriting bug when multiple operations target the same destination (#4)
- Path resolution issues in verification
- Double-adding to result lists bug
- Directory operations without --recursive flag now show helpful error messages

### Improved
- **Architecture**: Clarified ownership of hashing functions - preservelib owns the main implementation
- **Enhanced Help System**: Improved command documentation and examples
- RESTORE command now defaults to latest manifest when multiple exist
- Help text for COPY/MOVE operations with common usage examples
- Error messages for Windows path escaping issues

## [0.2.1] - 2025-05-14

### Fixed
- Improved relative path mode fallback behavior: now falls back to absolute path style (preserving structure) instead of flat structure when no common base directory can be found
- Enhanced logging for path resolution to make fallback behavior clearer

### Added
- Test scripts to verify relative path fallback scenarios
- Detailed documentation of relative path handling logic

## [0.2.0] - 2025-05-14

### Fixed
- Relative path mode (`--rel`) now properly preserves directory structure
- RESTORE operation behavior for all path modes
- Duplicate log messages in console output
- Directory structure preservation for files with no common parent

### Added
- Enhanced debugging and error reporting with [DEBUG PATH] prefix
- Verification report generation functionality
- Path tree analysis for better common base directory detection
- Test script for relative path mode verification

### Improved
- Path detection logic with robust common base directory finding
- Logging system with better configuration options
- Error handling during file operations

## [0.1.0] - 2025-05-14

### Added
- Initial implementation with basic functionality
- Core operations:
  - COPY: Copy files with path preservation options
  - MOVE: Move files with verification
  - RESTORE: Return files to original locations
  - VERIFY: Check file integrity with hash verification
  - CONFIG: View and modify configuration
- Path preservation styles:
  - Absolute paths (`--abs`)
  - Relative paths (`--rel`)
  - Flat structure (`--flat`)
- Hash verification using multiple algorithms (MD5, SHA1, SHA256, SHA512)
- Metadata preservation for file attributes
- Manifest system for tracking file operations
- Command-line interface with comprehensive options
- Cross-platform support (Windows, Linux, macOS)
- Basic dazzlelink integration (limited functionality)

### Known Issues
- Dazzlelink integration not fully functional
- Path preservation in relative mode needs improvement
- VERIFY report generation has some errors