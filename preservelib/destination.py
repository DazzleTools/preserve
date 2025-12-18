"""
Destination scanning and analysis for preserve.

This module provides functionality to scan a destination directory and compare
it against source files to identify conflicts, matches, and pre-existing files.

Part of the 0.7.x Destination Awareness feature (#39).
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .manifest import calculate_file_hash

# Set up module-level logger
logger = logging.getLogger(__name__)


class FileCategory(Enum):
    """Categories for files during destination scanning."""
    IDENTICAL = "identical"      # Same hash, can incorporate
    CONFLICT = "conflict"        # Different hash, needs resolution
    SOURCE_ONLY = "source_only"  # Only exists in source
    DEST_ONLY = "dest_only"      # Only exists in destination (pre-existing)


class ConflictResolution(Enum):
    """Conflict resolution strategies."""
    SKIP = "skip"           # Don't copy, keep destination
    OVERWRITE = "overwrite" # Replace destination with source
    NEWER = "newer"         # Keep whichever is newer (mtime)
    LARGER = "larger"       # Keep whichever is larger
    RENAME = "rename"       # Keep both, rename new file
    FAIL = "fail"           # Abort operation on conflict
    ASK = "ask"             # Interactive prompt


@dataclass
class FileComparison:
    """Result of comparing a source file with potential destination."""
    source_path: Path
    dest_path: Path
    category: FileCategory
    source_hash: Optional[str] = None
    dest_hash: Optional[str] = None
    source_size: int = 0
    dest_size: int = 0
    source_mtime: float = 0.0
    dest_mtime: float = 0.0
    conflict_resolution: Optional[ConflictResolution] = None
    resolution_reason: str = ""


@dataclass
class DestinationScanResult:
    """Complete result of scanning a destination."""
    dest_base: Path
    total_source_files: int = 0
    total_dest_files: int = 0

    # Files by category
    identical: List[FileComparison] = field(default_factory=list)
    conflicts: List[FileComparison] = field(default_factory=list)
    source_only: List[FileComparison] = field(default_factory=list)
    dest_only: List[Path] = field(default_factory=list)

    # Summary
    identical_count: int = 0
    conflict_count: int = 0
    source_only_count: int = 0
    dest_only_count: int = 0

    # Bytes to transfer
    bytes_to_copy: int = 0
    bytes_identical: int = 0
    bytes_conflict: int = 0

    # Errors encountered during scan
    scan_errors: List[Tuple[str, str]] = field(default_factory=list)

    def __post_init__(self):
        """Update summary counts after initialization."""
        self.update_counts()

    def update_counts(self):
        """Update summary counts from lists."""
        self.identical_count = len(self.identical)
        self.conflict_count = len(self.conflicts)
        self.source_only_count = len(self.source_only)
        self.dest_only_count = len(self.dest_only)

        # Calculate byte totals
        self.bytes_identical = sum(f.source_size for f in self.identical)
        self.bytes_conflict = sum(f.source_size for f in self.conflicts)
        self.bytes_to_copy = sum(f.source_size for f in self.source_only)

    def has_conflicts(self) -> bool:
        """Check if any conflicts were found."""
        return self.conflict_count > 0

    def has_pre_existing(self) -> bool:
        """Check if any pre-existing files were found."""
        return self.dest_only_count > 0 or self.identical_count > 0 or self.conflict_count > 0

    def get_action_summary(self) -> Dict[str, int]:
        """Get summary of actions needed."""
        return {
            "copy_new": self.source_only_count,
            "incorporate_identical": self.identical_count,
            "resolve_conflicts": self.conflict_count,
            "pre_existing_ignored": self.dest_only_count,
        }


def compute_destination_path(
    source_path: Path,
    dest_base: Path,
    path_style: str = "absolute",
    source_base: Optional[Path] = None,
    include_base: bool = False,
) -> Path:
    """
    Compute the destination path for a source file.

    This mirrors the path computation logic in operations.py to ensure
    scanning uses the same paths that the actual operation would use.

    Args:
        source_path: Source file path
        dest_base: Destination base directory
        path_style: Path style ('absolute', 'relative', 'flat')
        source_base: Source base for relative paths
        include_base: Whether to include base directory in relative paths

    Returns:
        Computed destination path
    """
    if path_style == "flat":
        return dest_base / source_path.name

    elif path_style == "absolute":
        if sys.platform == "win32":
            drive, path = os.path.splitdrive(str(source_path))
            drive = drive.rstrip(":")
            return dest_base / drive / path.lstrip("\\/")
        else:
            return dest_base / str(source_path).lstrip("/")

    elif path_style == "relative":
        if source_base:
            try:
                if include_base:
                    # Include base directory name
                    rel_path = source_path.relative_to(source_base.parent)
                else:
                    rel_path = source_path.relative_to(source_base)
                return dest_base / rel_path
            except ValueError:
                # Fall back to absolute style if relative fails
                logger.debug(f"Could not make {source_path} relative to {source_base}")
                if sys.platform == "win32":
                    drive, path = os.path.splitdrive(str(source_path))
                    drive = drive.rstrip(":")
                    return dest_base / drive / path.lstrip("\\/")
                else:
                    return dest_base / str(source_path).lstrip("/")
        else:
            # No source base, use parent directory
            return dest_base / source_path.name

    else:
        # Unknown style, default to absolute
        logger.warning(f"Unknown path style: {path_style}, using absolute")
        if sys.platform == "win32":
            drive, path = os.path.splitdrive(str(source_path))
            drive = drive.rstrip(":")
            return dest_base / drive / path.lstrip("\\/")
        else:
            return dest_base / str(source_path).lstrip("/")


def compare_files(
    source_path: Path,
    dest_path: Path,
    hash_algorithm: str = "SHA256",
    quick_check: bool = True,
) -> FileComparison:
    """
    Compare a source file with a potential destination file.

    Args:
        source_path: Source file path
        dest_path: Destination file path
        hash_algorithm: Hash algorithm to use for comparison
        quick_check: If True, use size comparison first (faster)

    Returns:
        FileComparison with category and details
    """
    comparison = FileComparison(
        source_path=source_path,
        dest_path=dest_path,
        category=FileCategory.SOURCE_ONLY,
    )

    # Get source file info
    try:
        source_stat = source_path.stat()
        comparison.source_size = source_stat.st_size
        comparison.source_mtime = source_stat.st_mtime
    except OSError as e:
        logger.warning(f"Could not stat source file {source_path}: {e}")
        return comparison

    # Check if destination exists
    if not dest_path.exists():
        comparison.category = FileCategory.SOURCE_ONLY
        return comparison

    # Get destination file info
    try:
        dest_stat = dest_path.stat()
        comparison.dest_size = dest_stat.st_size
        comparison.dest_mtime = dest_stat.st_mtime
    except OSError as e:
        logger.warning(f"Could not stat destination file {dest_path}: {e}")
        comparison.category = FileCategory.SOURCE_ONLY
        return comparison

    # Quick check: if sizes differ, they're definitely different
    if quick_check and comparison.source_size != comparison.dest_size:
        comparison.category = FileCategory.CONFLICT
        comparison.resolution_reason = f"Size differs: source={comparison.source_size}, dest={comparison.dest_size}"
        return comparison

    # Full comparison: compute hashes
    try:
        source_hashes = calculate_file_hash(source_path, [hash_algorithm])
        comparison.source_hash = source_hashes.get(hash_algorithm)

        dest_hashes = calculate_file_hash(dest_path, [hash_algorithm])
        comparison.dest_hash = dest_hashes.get(hash_algorithm)

        if comparison.source_hash and comparison.dest_hash:
            if comparison.source_hash.lower() == comparison.dest_hash.lower():
                comparison.category = FileCategory.IDENTICAL
            else:
                comparison.category = FileCategory.CONFLICT
                comparison.resolution_reason = "Hash mismatch"
        else:
            # Could not compute hashes, treat as conflict
            comparison.category = FileCategory.CONFLICT
            comparison.resolution_reason = "Could not compute hash"

    except Exception as e:
        logger.warning(f"Error comparing files {source_path} vs {dest_path}: {e}")
        comparison.category = FileCategory.CONFLICT
        comparison.resolution_reason = f"Comparison error: {e}"

    return comparison


def scan_destination(
    source_files: List[Union[str, Path]],
    dest_base: Union[str, Path],
    path_style: str = "absolute",
    source_base: Optional[Union[str, Path]] = None,
    include_base: bool = False,
    hash_algorithm: str = "SHA256",
    quick_check: bool = True,
    scan_extra_dest_files: bool = True,
    progress_callback: Optional[callable] = None,
) -> DestinationScanResult:
    """
    Scan destination directory and compare against source files.

    This is the main entry point for destination scanning. It:
    1. Computes destination paths for all source files
    2. Categorizes each file (identical, conflict, source-only)
    3. Optionally finds extra files in destination not in source

    Args:
        source_files: List of source file paths
        dest_base: Destination base directory
        path_style: Path preservation style
        source_base: Source base for relative paths
        include_base: Include base directory in relative paths
        hash_algorithm: Hash algorithm for comparisons
        quick_check: Use size comparison before hash (faster)
        scan_extra_dest_files: Also scan for dest-only files
        progress_callback: Optional callback for progress updates

    Returns:
        DestinationScanResult with categorized files
    """
    dest_base = Path(dest_base)
    source_base = Path(source_base) if source_base else None

    result = DestinationScanResult(dest_base=dest_base)
    result.total_source_files = len(source_files)

    # Track all expected destination paths (for dest-only detection)
    expected_dest_paths: Set[Path] = set()

    # Process each source file
    for i, source_file in enumerate(source_files):
        source_path = Path(source_file)

        # Progress callback
        if progress_callback:
            progress_callback(f"Scanning {i+1}/{len(source_files)}: {source_path.name}")

        # Skip non-files
        if not source_path.is_file():
            result.scan_errors.append((str(source_path), "Not a file or does not exist"))
            continue

        # Compute destination path
        dest_path = compute_destination_path(
            source_path=source_path,
            dest_base=dest_base,
            path_style=path_style,
            source_base=source_base,
            include_base=include_base,
        )
        expected_dest_paths.add(dest_path)

        # Compare files
        comparison = compare_files(
            source_path=source_path,
            dest_path=dest_path,
            hash_algorithm=hash_algorithm,
            quick_check=quick_check,
        )

        # Categorize
        if comparison.category == FileCategory.IDENTICAL:
            result.identical.append(comparison)
        elif comparison.category == FileCategory.CONFLICT:
            result.conflicts.append(comparison)
        elif comparison.category == FileCategory.SOURCE_ONLY:
            result.source_only.append(comparison)

    # Scan for dest-only files if requested and destination exists
    if scan_extra_dest_files and dest_base.exists():
        if progress_callback:
            progress_callback("Scanning destination for extra files...")

        for dest_file in dest_base.rglob("*"):
            if dest_file.is_file() and dest_file not in expected_dest_paths:
                # Skip preserve-internal files
                if dest_file.name.startswith("preserve_manifest") or \
                   dest_file.name.endswith(".dazzlelink") or \
                   ".preserve" in str(dest_file):
                    continue
                result.dest_only.append(dest_file)

        result.total_dest_files = len(expected_dest_paths) + len(result.dest_only)

    # Update summary counts
    result.update_counts()

    return result


def apply_conflict_resolution(
    comparison: FileComparison,
    resolution: ConflictResolution,
) -> FileComparison:
    """
    Apply a conflict resolution strategy to a file comparison.

    Args:
        comparison: The file comparison to resolve
        resolution: The resolution strategy to apply

    Returns:
        Updated FileComparison with resolution set
    """
    comparison.conflict_resolution = resolution

    if resolution == ConflictResolution.SKIP:
        comparison.resolution_reason = "Skipping - keeping destination"

    elif resolution == ConflictResolution.OVERWRITE:
        comparison.resolution_reason = "Overwriting destination with source"

    elif resolution == ConflictResolution.NEWER:
        if comparison.source_mtime > comparison.dest_mtime:
            comparison.resolution_reason = "Source is newer - will overwrite"
            comparison.conflict_resolution = ConflictResolution.OVERWRITE
        else:
            comparison.resolution_reason = "Destination is newer - skipping"
            comparison.conflict_resolution = ConflictResolution.SKIP

    elif resolution == ConflictResolution.LARGER:
        if comparison.source_size > comparison.dest_size:
            comparison.resolution_reason = "Source is larger - will overwrite"
            comparison.conflict_resolution = ConflictResolution.OVERWRITE
        else:
            comparison.resolution_reason = "Destination is larger - skipping"
            comparison.conflict_resolution = ConflictResolution.SKIP

    elif resolution == ConflictResolution.RENAME:
        comparison.resolution_reason = "Will rename source file to avoid conflict"

    elif resolution == ConflictResolution.FAIL:
        comparison.resolution_reason = "Operation will fail due to conflict"

    elif resolution == ConflictResolution.ASK:
        comparison.resolution_reason = "Will prompt user for resolution"

    return comparison


def generate_renamed_path(dest_path: Path) -> Path:
    """
    Generate a renamed path for conflict resolution.

    Adds a numeric suffix to avoid overwriting existing files.
    Example: file.txt -> file_001.txt

    Args:
        dest_path: Original destination path

    Returns:
        New path with numeric suffix
    """
    stem = dest_path.stem
    suffix = dest_path.suffix
    parent = dest_path.parent

    counter = 1
    while True:
        new_name = f"{stem}_{counter:03d}{suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1
        if counter > 999:
            raise ValueError(f"Could not find available rename for {dest_path}")


def format_scan_report(
    result: DestinationScanResult,
    verbose: bool = False,
) -> str:
    """
    Format a scan result as a human-readable report.

    Args:
        result: The scan result to format
        verbose: Include detailed file listings

    Returns:
        Formatted report string
    """
    lines = []

    lines.append("=" * 60)
    lines.append("DESTINATION SCAN REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Destination: {result.dest_base}")
    lines.append(f"Total source files: {result.total_source_files}")
    lines.append("")

    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Files to copy (new):          {result.source_only_count:5d}")
    lines.append(f"  Identical files (can skip):   {result.identical_count:5d}")
    lines.append(f"  Conflicts (need resolution):  {result.conflict_count:5d}")
    lines.append(f"  Pre-existing dest-only:       {result.dest_only_count:5d}")
    lines.append("")

    # Byte summary
    def format_bytes(b: int) -> str:
        if b < 1024:
            return f"{b} B"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        elif b < 1024 * 1024 * 1024:
            return f"{b / (1024 * 1024):.1f} MB"
        else:
            return f"{b / (1024 * 1024 * 1024):.2f} GB"

    lines.append("TRANSFER SIZE")
    lines.append("-" * 40)
    lines.append(f"  Bytes to copy:                {format_bytes(result.bytes_to_copy):>10}")
    lines.append(f"  Bytes identical (can skip):   {format_bytes(result.bytes_identical):>10}")
    lines.append(f"  Bytes in conflict:            {format_bytes(result.bytes_conflict):>10}")
    lines.append("")

    if result.has_conflicts():
        lines.append("CONFLICTS REQUIRING RESOLUTION")
        lines.append("-" * 40)
        for comp in result.conflicts[:10]:  # Show first 10
            lines.append(f"  {comp.dest_path.name}")
            lines.append(f"    Source: {comp.source_size} bytes, {comp.source_hash[:8] if comp.source_hash else 'N/A'}...")
            lines.append(f"    Dest:   {comp.dest_size} bytes, {comp.dest_hash[:8] if comp.dest_hash else 'N/A'}...")
        if len(result.conflicts) > 10:
            lines.append(f"  ... and {len(result.conflicts) - 10} more")
        lines.append("")

    if verbose:
        if result.identical:
            lines.append("IDENTICAL FILES (will incorporate)")
            lines.append("-" * 40)
            for comp in result.identical[:10]:
                lines.append(f"  {comp.dest_path.name} ({format_bytes(comp.source_size)})")
            if len(result.identical) > 10:
                lines.append(f"  ... and {len(result.identical) - 10} more")
            lines.append("")

        if result.dest_only:
            lines.append("PRE-EXISTING DESTINATION FILES (will ignore)")
            lines.append("-" * 40)
            for path in result.dest_only[:10]:
                lines.append(f"  {path.name}")
            if len(result.dest_only) > 10:
                lines.append(f"  ... and {len(result.dest_only) - 10} more")
            lines.append("")

    if result.scan_errors:
        lines.append("SCAN ERRORS")
        lines.append("-" * 40)
        for path, error in result.scan_errors[:5]:
            lines.append(f"  {path}: {error}")
        if len(result.scan_errors) > 5:
            lines.append(f"  ... and {len(result.scan_errors) - 5} more errors")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)
