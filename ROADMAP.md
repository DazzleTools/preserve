# Preserve Roadmap

> **Track files and always get them back to where you need them.**

This document outlines the development direction for preserve. Each major feature links to a GitHub issue for detailed discussion and tracking.

**Project Board**: [Preserve Development Roadmap](https://github.com/orgs/DazzleTools/projects/1) - Visual Kanban with priorities and dependencies.

## Current Release: v0.6.x (Safety & Reliability)

The 0.6.x series focused on making preserve safer and more reliable:

- **v0.6.0**: Link creation (`--link symlink/junction/hardlink`), link verification
- **v0.6.1**: Pre-flight disk space checking, permission error handling
- **v0.6.2**: Fixed space check logic, `--ignore` flag, enhanced MOVE messaging

## Next: v0.7.x (Destination Awareness)

**Theme**: Handle real-world scenarios where destinations aren't empty.

| Feature | Issue | Description |
|---------|-------|-------------|
| Destination-Aware Operations | [#39](https://github.com/djdarcy/preserve/issues/39) | Detect and handle pre-existing files during MOVE/COPY |
| CLEANUP Command | [#43](https://github.com/djdarcy/preserve/issues/43) | Recover from partial MOVE operations |
| Smart Path Detection | [#42](https://github.com/djdarcy/preserve/issues/42) | Warn about likely user errors with --abs/--rel |
| Conflict Resolution | [#39](https://github.com/djdarcy/preserve/issues/39) | `--on-conflict` options (skip, overwrite, newer, rename, ask) |

**Key capabilities:**
- `--scan-only` to preview destination state before operations
- `--incorporate-identical` to adopt matching files without re-copying
- Enhanced manifest schema with `parent_ids` array (DAG-ready)

## Planned: v0.8.x (File Lineage & Versioning)

**Theme**: Track file identity and history across operations.

| Feature | Issue | Description |
|---------|-------|-------------|
| File Lineage Tracking | [#44](https://github.com/djdarcy/preserve/issues/44) | Track files across multiple operations |
| Manifest Chaining | [#44](https://github.com/djdarcy/preserve/issues/44) | Link manifests to show operation history |
| Content-Addressed Identity | [#44](https://github.com/djdarcy/preserve/issues/44) | File identity based on hash, not path |

**Key capabilities:**
- Query: "Where did this file originally come from?"
- DAG traversal for manifest relationships
- Optional version storage in `.preserve/versions/`

## Planned: v0.9.x (Journey Tracking)

**Theme**: Visualize and navigate file history.

| Feature | Issue | Description |
|---------|-------|-------------|
| TRACE Command | [#45](https://github.com/djdarcy/preserve/issues/45) | Show a file's complete journey through the system |
| Journey Visualization | [#25](https://github.com/djdarcy/preserve/issues/25) | DazzleTreeLib integration for visual output |
| Relink Resolution | [#44](https://github.com/djdarcy/preserve/issues/44) | Find all historical locations for a file |

**Key capabilities:**
- `preserve TRACE --file "backup/main.py"` shows full history
- ASCII/tree visualization of file journeys
- "Restore to any point in time" functionality

## Future: v1.0.x (Stable Release)

**Theme**: Production-ready with full journey tracking.

- All core features stable and well-tested
- Cross-platform verified (Windows, Linux, macOS)
- Dazzlelink deep integration
- Performance optimization for large file sets

## Enhancement Backlog

These features are planned but not yet assigned to a specific release:

| Feature | Issue | Description |
|---------|-------|-------------|
| UPDATE Command | [#34](https://github.com/djdarcy/preserve/issues/34) | Incremental backup synchronization |
| Progress Bar | [#29](https://github.com/djdarcy/preserve/issues/29) | Visual progress for long operations |
| Follow Symlinks | [#24](https://github.com/djdarcy/preserve/issues/24) | `--follow-symlinks` option |
| UNC Share Fixes | [#13](https://github.com/djdarcy/preserve/issues/13) | Permission handling for SMB shares |
| Context Preservation | [#2](https://github.com/djdarcy/preserve/issues/2) | Maintain context of surrounding files |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved. Feature requests and bug reports are welcome via [GitHub Issues](https://github.com/djdarcy/preserve/issues).

## Design Documents

Detailed analysis documents are maintained in `private/.../` for major features. Key documents:

- Destination-aware operations analysis
- File lineage and versioning analysis
- Manifest DAG architecture decision

These are referenced in the corresponding GitHub issues.
