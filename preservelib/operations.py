"""
High-level operations for preserve.py.

This module provides the core operations for copying, moving, verifying,
and restoring files with path preservation and verification.
"""

import os
import sys
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set, Tuple

# Import from dazzle_filekit if available, otherwise use local imports
try:
    from dazzle_filekit import paths, operations, verification
except ImportError:
    # Local imports for development/testing
    from pathlib import Path
    import sys

    sys.path.append(str(Path(__file__).parent.parent.parent))
    try:
        from dazzle_filekit import paths, operations, verification
    except ImportError:
        # Fallbacks for testing
        paths = None
        operations = None
        verification = None

from .manifest import PreserveManifest, calculate_file_hash, verify_file_hash
from .metadata import collect_file_metadata, apply_file_metadata

# Set up module-level logger
logger = logging.getLogger(__name__)


class OperationResult:
    """
    Result of a preserve operation.

    Contains information about succeeded and failed files, as well as
    verification results and the operation manifest.
    """

    def __init__(self, operation_type: str, command_line: Optional[str] = None):
        """
        Initialize a new operation result.

        Args:
            operation_type: Type of operation (COPY, MOVE, VERIFY, RESTORE)
            command_line: Original command line that triggered the operation (optional)
        """
        self.operation_type = operation_type
        self.command_line = command_line
        self.succeeded = []  # List of successful file paths
        self.failed = []  # List of failed file paths
        self.skipped = []  # List of skipped file paths
        self.verified = []  # List of verified file paths
        self.unverified = []  # List of unverified file paths
        self.manifest = None  # Operation manifest
        self.start_time = None  # Operation start time
        self.end_time = None  # Operation end time
        self.total_bytes = 0  # Total bytes processed
        self.error_messages = {}  # Map of file paths to error messages

    def add_success(self, source_path: str, dest_path: str, size: int = 0) -> None:
        """
        Add a successful file operation.

        Args:
            source_path: Source file path
            dest_path: Destination file path
            size: File size in bytes
        """
        self.succeeded.append((source_path, dest_path))
        self.total_bytes += size

    def add_failure(self, source_path: str, dest_path: str, error: str) -> None:
        """
        Add a failed file operation.

        Args:
            source_path: Source file path
            dest_path: Destination file path
            error: Error message
        """
        self.failed.append((source_path, dest_path))
        self.error_messages[source_path] = error

    def add_skip(self, source_path: str, dest_path: str, reason: str) -> None:
        """
        Add a skipped file operation.

        Args:
            source_path: Source file path
            dest_path: Destination file path
            reason: Reason for skipping
        """
        self.skipped.append((source_path, dest_path))
        self.error_messages[source_path] = reason

    def add_verification(
        self, path: str, verified: bool, details: Optional[Any] = None
    ) -> None:
        """
        Add a verification result.

        Args:
            path: File path
            verified: Whether verification succeeded
            details: Additional verification details
        """
        if verified:
            self.verified.append((path, details))
        else:
            self.unverified.append((path, details))

    def set_manifest(self, manifest: PreserveManifest) -> None:
        """
        Set the operation manifest.

        Args:
            manifest: Operation manifest
        """
        self.manifest = manifest

    def set_times(self, start_time, end_time) -> None:
        """
        Set operation start and end times.

        Args:
            start_time: Operation start time
            end_time: Operation end time
        """
        self.start_time = start_time
        self.end_time = end_time

    def success_count(self) -> int:
        """Get the number of successful operations."""
        return len(self.succeeded)

    def failure_count(self) -> int:
        """Get the number of failed operations."""
        return len(self.failed)

    def skip_count(self) -> int:
        """Get the number of skipped operations."""
        return len(self.skipped)

    def verified_count(self) -> int:
        """Get the number of verified files."""
        return len(self.verified)

    def unverified_count(self) -> int:
        """Get the number of unverified files."""
        return len(self.unverified)

    def total_count(self) -> int:
        """Get the total number of files processed."""
        return self.success_count() + self.failure_count() + self.skip_count()

    def is_success(self) -> bool:
        """
        Check if the operation was completely successful.

        Returns:
            True if all files succeeded and were verified, False otherwise
        """
        return (
            self.failure_count() == 0
            and self.unverified_count() == 0
            and self.success_count() > 0
        )

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the operation.

        Returns:
            Dictionary with operation summary
        """
        return {
            "operation_type": self.operation_type,
            "command_line": self.command_line,
            "success_count": self.success_count(),
            "failure_count": self.failure_count(),
            "skip_count": self.skip_count(),
            "verified_count": self.verified_count(),
            "unverified_count": self.unverified_count(),
            "total_count": self.total_count(),
            "total_bytes": self.total_bytes,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "success": self.is_success(),
        }


def copy_operation(
    source_files: List[Union[str, Path]],
    dest_base: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    options: Optional[Dict[str, Any]] = None,
    command_line: Optional[str] = None,
) -> OperationResult:
    """
    Copy files to a destination with path preservation.

    Args:
        source_files: List of source files
        dest_base: Destination base directory
        manifest_path: Path to save the manifest (optional)
        options: Additional options (optional)
        command_line: Original command line (optional)

    Returns:
        Operation result
    """
    # Initialize default options
    default_options = {
        "path_style": "absolute",  # Default to absolute path style for better preservation
        "include_base": False,
        "source_base": None,
        "overwrite": False,
        "preserve_attrs": True,
        "verify": True,
        "hash_algorithm": "SHA256",
        "create_dazzlelinks": False,
        "dazzlelink_dir": None,
        "dazzlelink_mode": "info",  # Default execution mode for dazzlelinks
        "dry_run": False,
    }

    # Merge with provided options
    if options:
        default_options.update(options)

    options = default_options

    # Initialize operation result
    result = OperationResult("COPY", command_line)

    # Create manifest
    manifest = PreserveManifest()
    operation_id = manifest.add_operation(
        operation_type="COPY",
        source_path=",".join(str(s) for s in source_files),
        destination_path=str(dest_base),
        options=options,
        command_line=command_line,
    )

    # Ensure destination directory exists
    dest_base_path = Path(dest_base)
    dest_base_path.mkdir(parents=True, exist_ok=True)

    # If using relative paths, make all source files available to find common base
    if options["path_style"] == "relative":
        options["all_source_files"] = source_files

        # See if we can determine a common base directory
        if not options["source_base"]:
            # Define a robust function to find the longest common prefix
            def find_longest_common_path_prefix(paths):
                """Find the longest common directory prefix of a list of paths."""
                if not paths:
                    return None

                # Convert all paths to Path objects and normalize separators
                normalized_paths = []
                for p in paths:
                    try:
                        # Convert to string for consistent handling
                        path_str = str(p)
                        # Convert to forward slashes for consistency
                        norm_path = path_str.replace("\\", "/")
                        normalized_paths.append(norm_path)
                    except Exception:
                        # Skip invalid paths
                        continue

                if not normalized_paths:
                    return None

                # Split all paths into parts
                parts_list = [p.split("/") for p in normalized_paths]

                # Find common prefix parts
                common_parts = []
                for parts_tuple in zip(*parts_list):
                    if (
                        len(set(parts_tuple)) == 1
                    ):  # All parts at this position are the same
                        common_parts.append(parts_tuple[0])
                    else:
                        break

                # Special handling for Windows drive letters
                if sys.platform == "win32" and len(common_parts) > 0:
                    # If only the drive letter is common, it's not a useful prefix
                    if len(common_parts) == 1 and common_parts[0].endswith(":"):
                        drive_letter = common_parts[0]
                        # Check if next part is common even if not all paths have it
                        next_parts = set()
                        for parts in parts_list:
                            if len(parts) > 1:
                                next_parts.add(parts[1])
                        # If there's a common next part, include it
                        if len(next_parts) == 1:
                            common_parts.append(next_parts.pop())

                # Build the common prefix
                if not common_parts:
                    return None

                # Join with appropriate separator and convert back to Path
                common_prefix = "/".join(common_parts)
                # For Windows, we need to add back the path separator if it's just a drive
                if sys.platform == "win32" and common_prefix.endswith(":"):
                    common_prefix += "/"

                # Convert to a proper Path object using original separators
                if sys.platform == "win32":
                    common_prefix = common_prefix.replace("/", "\\")

                return Path(common_prefix)

            # Import pathutils for path tree analysis
            try:
                from . import pathutils

                # Check if a common prefix was already computed in args
                if (
                    "args" in locals()
                    and hasattr(args, "common_prefix")
                    and args.common_prefix
                ):
                    logger.info(
                        f"Using pre-computed common path prefix: {args.common_prefix}"
                    )
                    options["source_base"] = args.common_prefix
                else:
                    # Use the path tree to find the common base directory
                    common_base = pathutils.find_common_base_directory(source_files)
                    if common_base:
                        logger.info(
                            f"Found common base directory using path tree: {common_base}"
                        )
                        options["source_base"] = common_base
                    else:
                        # Fall back to simple common prefix algorithm
                        common_prefix = find_longest_common_path_prefix(source_files)
                        if common_prefix:
                            logger.info(
                                f"Found common parent directory for all files: {common_prefix}"
                            )
                            options["source_base"] = common_prefix
            except ImportError as e:
                # Fall back to original algorithm if pathutils not available
                logger.warning(
                    f"PathTree not available, using simple prefix algorithm: {e}"
                )
                common_prefix = find_longest_common_path_prefix(source_files)
                if common_prefix:
                    logger.info(
                        f"Found common parent directory for all files: {common_prefix}"
                    )
                    options["source_base"] = common_prefix

    # Process each source file
    for source_file in source_files:
        source_path = Path(source_file)

        # Skip if source doesn't exist or isn't a file
        if not source_path.exists():
            result.add_skip(str(source_path), "", "Source file does not exist")
            continue

        if not source_path.is_file():
            result.add_skip(str(source_path), "", "Source is not a file")
            continue

        try:
            # Determine destination path
            # For relative path style, we need to find a common base directory for all files if not explicitly provided
            if options["path_style"] == "relative" and not options["source_base"]:
                # Use the parent folder of the file by default
                source_base = Path(source_path).parent
                logger.debug(
                    f"[DEBUG PATH] Initial source_base for {source_path}: {source_base}"
                )

                # If we can detect the most common parent folder among all source files, use that instead
                if hasattr(options, "all_source_files") and options["all_source_files"]:
                    # This is the list of all source files being processed
                    all_files = options["all_source_files"]
                    logger.debug(
                        f"[DEBUG PATH] Found {len(all_files)} files in options.all_source_files"
                    )

                    # Try to find common parent directories
                    if len(all_files) > 1:
                        logger.debug(
                            f"[DEBUG PATH] Finding common base path for {len(all_files)} files"
                        )
                        # Get all parent directories for each file
                        parent_dirs = []
                        for file in all_files:
                            file_path = Path(file)
                            logger.debug(
                                f"[DEBUG PATH]   Analyzing parents for: {file_path}"
                            )
                            # Add all parents to the list
                            current = file_path.parent
                            parent_count = 0
                            while current != current.parent:  # Stop at root
                                parent_dirs.append(str(current))
                                if parent_count < 3:  # Limit logging to first 3 levels
                                    logger.debug(
                                        f"[DEBUG PATH]     Parent {parent_count}: {current}"
                                    )
                                parent_count += 1
                                current = current.parent

                        # Count occurrences of each parent directory
                        from collections import Counter

                        parent_counts = Counter(parent_dirs)

                        # Log the top 3 most common parent directories for debugging
                        logger.debug(f"[DEBUG PATH] Most common parent directories:")
                        for i, (parent, count) in enumerate(
                            parent_counts.most_common(3)
                        ):
                            coverage_pct = (count / len(all_files)) * 100
                            logger.debug(
                                f"[DEBUG PATH]   {i+1}. {parent}: {count} files ({coverage_pct:.1f}%)"
                            )

                        # Find the most common parent that's at least 2 levels deep
                        for parent, count in parent_counts.most_common():
                            parent_path = Path(parent)
                            # Check if this parent contains at least 75% of the files
                            coverage_pct = (count / len(all_files)) * 100
                            parts = len(parent_path.parts)

                            logger.debug(
                                f"[DEBUG PATH] Evaluating parent: {parent_path} ({coverage_pct:.1f}% coverage, {parts} path parts)"
                            )

                            if count >= len(all_files) * 0.75:
                                # Ensure it's not just the root or a shallow directory
                                if (sys.platform == "win32" and parts > 1) or (
                                    sys.platform != "win32" and parts > 1
                                ):
                                    logger.debug(
                                        f"[DEBUG PATH] Selected common parent directory: {parent_path} ({coverage_pct:.1f}% coverage)"
                                    )
                                    source_base = parent_path
                                    logger.info(
                                        f"Using common parent directory for relative paths: {source_base}"
                                    )
                                    break
                                else:
                                    logger.debug(
                                        f"[DEBUG PATH] Rejected parent as too shallow: {parent_path} ({parts} parts)"
                                    )
                            else:
                                logger.debug(
                                    f"[DEBUG PATH] Rejected parent due to low coverage: {parent_path} ({coverage_pct:.1f}%)"
                                )
            else:
                source_base = (
                    options["source_base"]
                    if options["source_base"]
                    else Path(source_path).parent
                )
                logger.debug(
                    f"[DEBUG] Final source_base for {source_path}: {source_base}"
                )

            if options["path_style"] == "relative":
                # Relative to source_base
                try:
                    # Try different strategies to find a meaningful relative path
                    source_path_str = str(source_path)

                    # Add detailed logging for path structure
                    logger.debug(
                        f"[DEBUG PATH] Processing relative path for: {source_path}"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Source path parts: {list(Path(source_path).parts)}"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Options source_base: {options['source_base'] if options['source_base'] else 'None'}"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Calculated source_base: {source_base if source_base else 'None'}"
                    )
                    logger.debug(f"[DEBUG PATH] Destination base: {dest_base_path}")

                    # Test if source path is actually within the calculated source_base
                    if source_base:
                        is_within_source_base = False
                        try:
                            # Convert both to strings with normalized separators for comparison
                            source_str = str(source_path).replace("\\", "/")
                            base_str = str(source_base).replace("\\", "/")

                            # Check if source starts with base
                            is_within_source_base = source_str.startswith(base_str)
                            logger.debug(
                                f"[DEBUG PATH] Is source within source_base: {is_within_source_base}"
                            )
                            logger.debug(
                                f"[DEBUG PATH] Source normalized: {source_str}"
                            )
                            logger.debug(f"[DEBUG PATH] Base normalized: {base_str}")
                        except Exception as path_check_error:
                            logger.debug(
                                f"[DEBUG PATH] Error checking if path is within source_base: {path_check_error}"
                            )

                    # Define a helper function to handle potential errors
                    def try_relative_to(base_path, fallback=None):
                        try:
                            rel = source_path.relative_to(base_path)
                            logger.debug(
                                f"[DEBUG PATH] Successfully made relative to {base_path}: {rel}"
                            )
                            return rel
                        except ValueError as ve:
                            logger.debug(
                                f"[DEBUG PATH] Failed to make relative to {base_path}: {ve}"
                            )
                            return fallback

                    # Use a while True loop with break statements for clearer strategy flow control
                    # This ensures we exit after the first successful strategy
                    while True:
                        # Strategy 1: Use the computed common prefix from options (if available)
                        if options["source_base"]:
                            logger.debug(
                                f"[DEBUG PATH] Trying Strategy 1: options['source_base'] = {options['source_base']}"
                            )

                            if options["include_base"]:
                                # Include the base directory name (last component of source_base)
                                # To include the base name, we need to get relative path from parent
                                source_base_path = Path(options["source_base"])
                                base_parent = source_base_path.parent
                                logger.debug(
                                    f"[DEBUG PATH] Using base parent with include_base: {base_parent}"
                                )

                                # Get relative path from parent of source_base
                                # This will include the source_base name in the relative path
                                rel_path = try_relative_to(base_parent)
                                if rel_path:
                                    dest_path = dest_base_path / rel_path
                                    logger.debug(
                                        f"[DEBUG PATH] Strategy 1A - include_base SUCCESS: {rel_path} → {dest_path}"
                                    )
                                    break  # Successfully found a path, so exit the strategy loop
                                else:
                                    logger.debug(
                                        f"[DEBUG PATH] Strategy 1A - include_base FAILED"
                                    )

                            # Just the path relative to source_base (standard relative path)
                            source_base_path = Path(options["source_base"])
                            rel_path = try_relative_to(source_base_path)
                            if rel_path:
                                # This is the key fix - properly preserve subdirectory structure
                                dest_path = dest_base_path / rel_path
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 1B - relative to source_base SUCCESS: {rel_path} → {dest_path}"
                                )
                                break  # Successfully found a path, so exit the strategy loop
                            else:
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 1B - relative to source_base FAILED"
                                )
                        else:
                            logger.debug(
                                f"[DEBUG PATH] Strategy 1 SKIPPED - No options['source_base'] available"
                            )

                        # Strategy 2: Use the locally calculated source_base
                        if source_base:
                            logger.debug(
                                f"[DEBUG PATH] Trying Strategy 2: calculated source_base = {source_base}"
                            )

                            try:
                                # Try to use the source_base directly
                                rel_path = source_path.relative_to(source_base)
                                if rel_path:
                                    # Preserve the full subdirectory structure from the common base
                                    dest_path = dest_base_path / rel_path
                                    logger.debug(
                                        f"[DEBUG PATH] Strategy 2 - relative to calculated source_base SUCCESS: {rel_path} → {dest_path}"
                                    )
                                    break  # Successfully found a path, so exit the strategy loop
                                else:
                                    logger.debug(
                                        f"[DEBUG PATH] Strategy 2 - Empty rel_path, continuing"
                                    )
                            except ValueError as ve:
                                # If we can't make it relative to source_base, log and continue to next strategy
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 2 FAILED - Unable to make relative to {source_base}: {ve}"
                                )
                        else:
                            logger.debug(
                                f"[DEBUG PATH] Strategy 2 SKIPPED - No calculated source_base available"
                            )

                        # Strategy 3: Find a common parent directory (dynamically)
                        logger.debug(
                            f"[DEBUG PATH] Trying Strategy 3: parent directory"
                        )
                        if source_path.parent != source_path:
                            try:
                                parent_dir = source_path.parent
                                logger.debug(
                                    f"[DEBUG PATH] Parent directory: {parent_dir}"
                                )

                                # We'll use the source filename as the relative path component
                                rel_filename = source_path.name

                                # Use parent directory name to preserve some structure
                                # For deeper directory structure, we could use more parent components
                                dest_path = (
                                    dest_base_path / parent_dir.name / rel_filename
                                )
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 3 - parent directory SUCCESS: {parent_dir.name}/{rel_filename} → {dest_path}"
                                )
                                break  # Successfully found a path, so exit the strategy loop
                            except Exception as e:
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 3 FAILED - Error using parent directory: {e}"
                                )
                        else:
                            logger.debug(
                                f"[DEBUG PATH] Strategy 3 SKIPPED - Source path has no parent (root path)"
                            )

                        # Strategy 4: Use absolute path style as fallback instead of flat structure
                        # This preserves more directory info than the previous flat fallback
                        logger.debug(
                            f"[DEBUG PATH] Trying Strategy 4: absolute path fallback"
                        )

                        # Important: This should only run if we don't already have a dest_path
                        # This is a safety check to make sure we don't override previous successful strategies
                        if "dest_path" not in locals():
                            # Use the absolute path style instead of flat
                            if sys.platform == "win32":
                                # Windows: use drive letter as directory
                                drive, path = os.path.splitdrive(str(source_path))
                                drive = drive.rstrip(":")  # Remove colon
                                stripped_path = path.lstrip("\\/")
                                dest_path = dest_base_path / drive / stripped_path
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 4 - Windows absolute path fallback: {drive}/{stripped_path} → {dest_path}"
                                )
                            else:
                                # Unix: use root-relative path
                                unix_path = str(source_path).lstrip("/")
                                dest_path = dest_base_path / unix_path
                                logger.debug(
                                    f"[DEBUG PATH] Strategy 4 - Unix absolute path fallback: {unix_path} → {dest_path}"
                                )

                            logger.info(
                                f"Using absolute path fallback instead of flat structure for {source_path}"
                            )
                        else:
                            logger.debug(
                                f"[DEBUG PATH] Strategy 4 SKIPPED - dest_path already set by a previous strategy"
                            )

                        # If we've gone through all strategies, exit the loop now
                        logger.debug(
                            f"[DEBUG PATH] All strategies processed, breaking loop"
                        )
                        break

                except ValueError as e:
                    # Not relative to source_base or any other strategy, use absolute style
                    logger.warning(
                        f"Path {source_path} could not be made relative: {e}, using absolute path style to preserve directory structure"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Falling back to absolute path style for {source_path}"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Source path parts: {list(Path(source_path).parts)}"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Source base: {source_base if 'source_base' in locals() else 'not defined'}"
                    )

                    if sys.platform == "win32":
                        # Windows: use drive letter as directory
                        drive, path = os.path.splitdrive(str(source_path))
                        drive = drive.rstrip(":")  # Remove colon
                        dest_path = dest_base_path / drive / path.lstrip("\\/")
                        logger.debug(
                            f"[DEBUG PATH] Windows path components - drive: {drive}, path: {path}"
                        )
                        logger.debug(f"[DEBUG PATH] Final absolute path: {dest_path}")
                    else:
                        # Unix: use root-relative path
                        unix_path = str(source_path).lstrip("/")
                        dest_path = dest_base_path / unix_path
                        logger.debug(
                            f"[DEBUG PATH] Unix path components - path: {unix_path}"
                        )
                        logger.debug(
                            f"[DEBUG PATH] Final Unix absolute path: {dest_path}"
                        )

                    logger.info(
                        f"Using absolute path style instead of flat structure for {source_path}"
                    )
                except Exception as e:
                    # Unknown error, use absolute style
                    logger.warning(
                        f"Error processing relative path for {source_path}: {e}, using absolute path style to preserve directory structure"
                    )
                    logger.debug(
                        f"[DEBUG PATH] Exception during relative path handling: {str(e)}"
                    )
                    logger.debug(f"[DEBUG PATH] Exception type: {type(e).__name__}")

                    if sys.platform == "win32":
                        # Windows: use drive letter as directory
                        drive, path = os.path.splitdrive(str(source_path))
                        drive = drive.rstrip(":")  # Remove colon
                        dest_path = dest_base_path / drive / path.lstrip("\\/")
                        logger.debug(
                            f"[DEBUG PATH] Windows path components - drive: {drive}, path: {path}"
                        )
                        logger.debug(f"[DEBUG PATH] Final absolute path: {dest_path}")
                    else:
                        # Unix: use root-relative path
                        unix_path = str(source_path).lstrip("/")
                        dest_path = dest_base_path / unix_path
                        logger.debug(
                            f"[DEBUG PATH] Unix path components - path: {unix_path}"
                        )
                        logger.debug(
                            f"[DEBUG PATH] Final Unix absolute path: {dest_path}"
                        )

                    logger.info(
                        f"Using absolute path style instead of flat structure for {source_path}"
                    )

            elif options["path_style"] == "absolute":
                # Preserve absolute path
                if sys.platform == "win32":
                    # Windows: use drive letter as directory
                    drive, path = os.path.splitdrive(str(source_path))
                    drive = drive.rstrip(":")  # Remove colon
                    dest_path = dest_base_path / drive / path.lstrip("\\/")
                else:
                    # Unix: use root-relative path
                    dest_path = dest_base_path / str(source_path).lstrip("/")

            elif options["path_style"] == "flat":
                # Flat structure: just use filename
                dest_path = dest_base_path / source_path.name

            else:
                # Unknown style, default to relative
                logger.warning(
                    f"Unknown path style: {options['path_style']}, using relative"
                )
                rel_path = source_path.relative_to(source_base)
                dest_path = dest_base_path / rel_path

            # Create parent directories
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if destination exists
            if dest_path.exists() and not options["overwrite"]:
                result.add_skip(
                    str(source_path),
                    str(dest_path),
                    "Destination exists and overwrite not enabled",
                )
                continue

            # Enhanced debug output for path resolution in relative mode
            if options["path_style"] == "relative":
                logger.debug(
                    f"[DEBUG PATH] Relative path resolution results for {source_path}:"
                )
                logger.debug(f"[DEBUG PATH]   - Source path: {source_path}")
                logger.debug(f"[DEBUG PATH]   - Source base: {source_base}")
                logger.debug(f"[DEBUG PATH]   - Destination path: {dest_path}")
                logger.debug(
                    f"[DEBUG PATH]   - Source path components: {list(Path(source_path).parts)}"
                )
                if "dest_path" in locals():
                    try:
                        rel_structure = list(
                            Path(dest_path).relative_to(dest_base_path).parts
                        )
                        logger.debug(
                            f"[DEBUG PATH]   - Resulting subdirectory structure: {rel_structure}"
                        )
                        logger.debug(
                            f"[DEBUG PATH]   - Subdirectory depth preserved: {len(rel_structure) > 0}"
                        )
                    except ValueError:
                        logger.debug(
                            f"[DEBUG PATH]   - Could not determine relative structure to {dest_base_path}"
                        )
                    # Additional detail about the destination path
                    logger.debug(
                        f"[DEBUG PATH]   - Destination exists: {Path(dest_path).exists()}"
                    )
                    logger.debug(
                        f"[DEBUG PATH]   - Destination parent: {Path(dest_path).parent}"
                    )
                    logger.debug(
                        f"[DEBUG PATH]   - Destination parent exists: {Path(dest_path).parent.exists()}"
                    )
                else:
                    logger.warning(f"[DEBUG PATH]   - No destination path was set!")

            # In dry run mode, just log what would be done
            if options["dry_run"]:
                result.add_success(
                    str(source_path), str(dest_path), source_path.stat().st_size
                )
                logger.info(f"[DRY RUN] Would copy {source_path} to {dest_path}")
                continue

            # Collect metadata before copying
            metadata = None
            if options["preserve_attrs"]:
                metadata = collect_file_metadata(source_path)

            # Copy the file
            shutil.copy2(source_path, dest_path)

            # Apply metadata
            if options["preserve_attrs"] and metadata:
                apply_file_metadata(dest_path, metadata)

            # Calculate hash if verification is enabled
            file_hashes = {}
            if options["verify"]:
                file_hashes = calculate_file_hash(
                    dest_path, [options["hash_algorithm"]]
                )

            # Add to manifest
            file_id = manifest.add_file(
                source_path=str(source_path),
                destination_path=str(dest_path),
                file_info={"size": source_path.stat().st_size},
                operation_id=operation_id,
            )

            # Add hash to manifest
            for algorithm, hash_value in file_hashes.items():
                manifest.add_file_hash(file_id, algorithm, hash_value)

            # Create dazzlelink if enabled
            if options["create_dazzlelinks"]:
                _create_dazzlelink(
                    source_path=source_path,
                    dest_path=dest_path,
                    dazzlelink_dir=options["dazzlelink_dir"],
                    path_style=options["path_style"],
                    dest_base=dest_base,
                    mode=options.get(
                        "dazzlelink_mode", "info"
                    ),  # Use the configured mode
                    options=options,  # Pass all options including all_source_files
                )

            # Add success to result
            result.add_success(
                str(source_path), str(dest_path), source_path.stat().st_size
            )

            # Verify the copy if enabled
            if options["verify"]:
                source_hash = calculate_file_hash(
                    source_path, [options["hash_algorithm"]]
                )

                verified, details = verify_file_hash(dest_path, source_hash)
                result.add_verification(str(dest_path), verified, details)

                if not verified:
                    logger.warning(f"Verification failed for {dest_path}")

        except Exception as e:
            # Log error and add failure to result
            logger.error(f"Error copying {source_path} to {dest_path}: {e}")
            result.add_failure(str(source_path), str(dest_path), str(e))

    # Save manifest if path provided
    if manifest_path and not options["dry_run"]:
        manifest_path = Path(manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest.save(manifest_path)

    # Set manifest in result
    result.set_manifest(manifest)

    return result


def move_operation(
    source_files: List[Union[str, Path]],
    dest_base: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    options: Optional[Dict[str, Any]] = None,
    command_line: Optional[str] = None,
) -> OperationResult:
    """
    Move files to a destination with path preservation.

    Files are first copied, then verified if enabled, and finally
    removed from the source location.

    Args:
        source_files: List of source files
        dest_base: Destination base directory
        manifest_path: Path to save the manifest (optional)
        options: Additional options (optional)
        command_line: Original command line (optional)

    Returns:
        Operation result
    """
    # Initialize default options
    default_options = {
        "path_style": "absolute",  # Default to absolute path style for better preservation
        "include_base": False,
        "source_base": None,
        "overwrite": False,
        "preserve_attrs": True,
        "verify": True,
        "hash_algorithm": "SHA256",
        "create_dazzlelinks": False,
        "dazzlelink_dir": None,
        "dazzlelink_mode": "info",  # Default execution mode for dazzlelinks
        "dry_run": False,
        "force": False,  # Force removal even if verification fails
    }

    # Merge with provided options
    if options:
        default_options.update(options)

    options = default_options

    # Initialize operation result
    result = OperationResult("MOVE", command_line)

    # Create manifest
    manifest = PreserveManifest()
    operation_id = manifest.add_operation(
        operation_type="MOVE",
        source_path=",".join(str(s) for s in source_files),
        destination_path=str(dest_base),
        options=options,
        command_line=command_line,
    )

    # First, copy the files
    # Set verify to True to ensure files are copied correctly
    copy_options = options.copy()
    copy_options["verify"] = True

    copy_result = copy_operation(
        source_files=source_files,
        dest_base=dest_base,
        manifest_path=None,  # Don't save manifest yet
        options=copy_options,
        command_line=command_line,
    )

    # Update result with copy results
    result.succeeded = copy_result.succeeded
    result.failed = copy_result.failed
    result.skipped = copy_result.skipped
    result.verified = copy_result.verified
    result.unverified = copy_result.unverified
    result.error_messages = copy_result.error_messages
    result.total_bytes = copy_result.total_bytes

    # Now remove source files if they were successfully copied and verified
    if not options["dry_run"]:
        for source_path, dest_path in copy_result.succeeded:
            # Skip if verification failed and force is not enabled
            if not options["force"]:
                verified = any(path == dest_path for path, _ in copy_result.verified)
                if not verified:
                    continue

            try:
                # Remove the source file
                os.unlink(source_path)
                logger.debug(f"Removed source file: {source_path}")
            except Exception as e:
                logger.error(f"Error removing source file {source_path}: {e}")
                result.error_messages[source_path] = f"Error removing source file: {e}"

    # Save manifest if path provided
    if manifest_path and not options["dry_run"]:
        # Copy manifest from copy operation
        result.manifest = copy_result.manifest

        # Update operation type
        for op in result.manifest.manifest["operations"]:
            if op["type"] == "COPY":
                op["type"] = "MOVE"

        # Save manifest
        manifest_path = Path(manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        result.manifest.save(manifest_path)

    return result


def verify_operation(
    source_files: Optional[List[Path]] = None,
    dest_files: Optional[List[Path]] = None,
    manifest_path: Optional[Path] = None,
    options: Optional[Dict[str, Any]] = None,
    command_line: Optional[str] = None,
) -> OperationResult:
    """
    Wrapper function for verify operation to maintain API compatibility.

    This function delegates to the new verification module while maintaining
    the original API contract.

    Args:
        source_files: Source files to verify against
        dest_files: Destination files to verify
        manifest_path: Path to manifest file
        options: Operation options including hash_algorithm
        command_line: Command line string for logging

    Returns:
        OperationResult with verification results
    """
    from .verification import find_and_verify_manifest

    # Create result object
    result = OperationResult("VERIFY")

    # Set up defaults
    if options is None:
        options = {}

    # Extract destination directory from dest_files or options
    dest_directory = None
    if dest_files and dest_files[0]:
        dest_directory = (
            dest_files[0].parent if dest_files[0].is_file() else dest_files[0]
        )
    elif options.get("dest_directory"):
        dest_directory = Path(options["dest_directory"])

    if not dest_directory:
        logger.error("No destination directory specified for verification")
        result.add_failure("", "", "No destination directory specified")
        return result

    # Get hash algorithms
    hash_algorithms = [options.get("hash_algorithm", "SHA256")]

    try:
        # Use the new verification module
        manifest, verification_result = find_and_verify_manifest(
            destination=dest_directory,
            manifest_path=manifest_path,
            hash_algorithms=hash_algorithms,
        )

        # Convert verification result to OperationResult format
        # Add verified files as successful
        for _ in range(verification_result.verified_count):
            result.add_success("", "")  # Simplified for wrapper

        # Add failed files
        for file_path in verification_result.failed_files:
            result.add_failure(str(file_path), str(file_path), "Hash mismatch")

        # Add missing files as unverified
        for file_path in verification_result.missing_files:
            result.add_unverified(str(file_path), str(file_path))

        # Generate report if requested
        if options.get("report_path"):
            _generate_verification_report(result, options["report_path"])

    except Exception as e:
        logger.error(f"Verification operation failed: {e}")
        result.add_failure("", "", str(e))

    # Log the command line if provided
    if command_line:
        logger.debug(f"Command: {command_line}")

    return result


def restore_operation(
    source_directory: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    options: Optional[Dict[str, Any]] = None,
    command_line: Optional[str] = None,
) -> OperationResult:
    """
    Restore files to their original locations.

    Args:
        source_directory: Directory containing files to restore
        manifest_path: Path to manifest file (optional)
        options: Additional options (optional)
        command_line: Original command line (optional)

    Returns:
        Operation result
    """
    # Initialize default options
    default_options = {
        "overwrite": False,
        "preserve_attrs": True,
        "verify": True,
        "hash_algorithm": "SHA256",
        "dry_run": False,
        "force": False,  # Force restoration even if verification fails
        "use_dazzlelinks": True,  # Use dazzlelinks if no manifest found
        "destination_override": None,  # Override destination path for restoration
        "formatter": None,  # Output formatter for progress display
    }

    # Merge with provided options
    if options:
        default_options.update(options)

    options = default_options

    # Get formatter if provided
    formatter = options.get('formatter')
    if formatter:
        # Import here to avoid circular dependencies
        from preserve.output import get_formatter
        # If no formatter provided, get the global one
        if formatter is None:
            formatter = get_formatter()

    # Initialize operation result
    result = OperationResult("RESTORE", command_line)

    # Source directory path
    source_dir_path = Path(source_directory)

    # Find manifest if not provided
    manifest = None
    if not manifest_path:
        potential_manifests = [
            source_dir_path / ".preserve" / "manifest.json",
            source_dir_path / ".preserve" / "preserve_manifest.json",
            source_dir_path / "preserve_manifest.json",
        ]

        for path in potential_manifests:
            if path.exists():
                manifest_path = path
                try:
                    manifest = PreserveManifest(manifest_path)
                    logger.info(f"Loaded manifest from {manifest_path}")
                    break
                except Exception as e:
                    logger.warning(f"Error loading manifest {manifest_path}: {e}")

    # If manifest path provided but not loaded yet, try to load it
    if manifest_path and not manifest:
        try:
            manifest = PreserveManifest(manifest_path)
            logger.info(f"Loaded manifest from {manifest_path}")
        except Exception as e:
            logger.error(f"Error loading manifest {manifest_path}: {e}")
            # Don't return immediately - we might be able to use dazzlelinks

    # If no manifest, check for dazzlelinks
    used_dazzlelinks = False
    if not manifest and options["use_dazzlelinks"]:
        try:
            # First check if dazzlelink is available
            try:
                from .dazzlelink import (
                    find_dazzlelinks_in_dir,
                    dazzlelink_to_manifest,
                    is_available,
                )

                if not is_available():
                    logger.warning("Dazzlelink integration not available")
                    # Continue with no manifest and no dazzlelinks
                else:
                    # Search for dazzlelinks
                    dazzlelinks = find_dazzlelinks_in_dir(
                        source_directory, recursive=True
                    )
                    if dazzlelinks:
                        # Convert dazzlelinks to a manifest structure
                        manifest_data = dazzlelink_to_manifest(dazzlelinks)
                        if (
                            manifest_data
                            and "files" in manifest_data
                            and manifest_data["files"]
                        ):
                            # Create a manifest from the dazzlelink data
                            manifest = PreserveManifest()
                            # Replace the default manifest data with our converted data
                            manifest.manifest = manifest_data
                            logger.info(
                                f"Created manifest from {len(dazzlelinks)} dazzlelinks"
                            )
                            used_dazzlelinks = True
                        else:
                            logger.warning(
                                "No valid file information found in dazzlelinks"
                            )
                    else:
                        logger.warning(f"No dazzlelinks found in {source_directory}")
            except ImportError:
                logger.warning("Dazzlelink module not available")
        except Exception as e:
            logger.error(f"Error using dazzlelinks: {e}")

    # If we still don't have a manifest, we can't continue
    if not manifest:
        logger.error(f"No manifest or dazzlelinks found in {source_directory}")
        result.add_failure("", "", "No manifest or dazzlelinks found")
        return result

    # Create new operation in manifest (excluding formatter)
    manifest_options = {k: v for k, v in options.items() if k != 'formatter'}
    operation_id = manifest.add_operation(
        operation_type="RESTORE",
        source_path=str(source_directory),
        options=manifest_options,
        command_line=command_line,
    )

    # Process each file in manifest
    from .restore import restore_file_to_original

    # Get total file count for progress
    all_files = manifest.get_all_files()
    total_files = len(all_files)
    current_file_num = 0

    # Show header if formatter available
    if formatter:
        header = formatter.format_header(f"Restoring {total_files} files...")
        if header:
            print(header)

    for file_id, file_info in all_files.items():
        current_file_num += 1
        source_orig_path = file_info.get("source_path")
        dest_orig_path = file_info.get("destination_path")

        if not source_orig_path or not dest_orig_path:
            continue

        # During restore, the destination is now the source
        # If we created the manifest from dazzlelinks, the source and destination are swapped
        if used_dazzlelinks:
            current_path = Path(
                str(source_orig_path).replace("\\", "/")
            )  # From dazzlelink, this is the original path
            original_path = Path(
                str(source_orig_path).replace("\\", "/")
            )  # Restore to the same path
            logger.debug(
                f"RESTORE (dazzlelink): current={current_path}, original={original_path}"
            )
        else:
            # Normal manifest case
            current_path = Path(str(dest_orig_path).replace("\\", "/"))
            original_path = Path(str(source_orig_path).replace("\\", "/"))
            logger.debug(
                f"RESTORE (manifest): current={current_path}, original={original_path}"
            )

        # Make absolute if needed but avoid double-prefixing with source_dir_path
        if not current_path.is_absolute():
            # We need to resolve the current path against the source directory
            # while avoiding double-prefixing of paths
            try:
                # Convert to string for consistent handling
                current_path_str = str(current_path)
                source_dir_str = str(source_dir_path)
                source_dir_name = Path(source_dir_path).name

                logger.debug(
                    f"RESTORE: Processing path: {current_path_str}, source dir: {source_dir_str}, source dir name: {source_dir_name}"
                )

                # Check if the current_path already includes source_dir_path
                if current_path_str.startswith(source_dir_str):
                    # Already includes the source_dir, don't add it again
                    logger.debug(
                        f"RESTORE: Path already includes source directory, using as is: {current_path}"
                    )
                else:
                    # First try to find the source directory name in the path
                    path_parts = current_path_str.split("\\")

                    # Try to detect if this path already contains the destination directory name
                    # This is more generic than the hardcoded 'dst2' approach
                    if source_dir_name in path_parts:
                        # Find the index of the source directory name in the path
                        dir_index = path_parts.index(source_dir_name)
                        if dir_index + 1 < len(path_parts):
                            # Keep only the part after the source directory name
                            relevant_path = "\\".join(path_parts[dir_index + 1 :])
                            current_path = source_dir_path / relevant_path
                            logger.debug(
                                f"RESTORE: Extracted path after {source_dir_name}: {current_path}"
                            )
                        else:
                            # Just use the source_dir as is if there's nothing after it
                            current_path = source_dir_path
                            logger.debug(
                                f"RESTORE: Using source directory as is: {current_path}"
                            )
                    else:
                        # Check for any known destination directory names that might be in the path
                        # This handles the case where the destination folder name is not the same as source_dir_name
                        known_dest_dirs = [
                            "dst",
                            "dst2",
                            "dst3",
                            "dest",
                            "destination",
                            "backup",
                            "archive",
                        ]
                        found_dir = False

                        for dest_dir in known_dest_dirs:
                            if dest_dir in path_parts:
                                dir_index = path_parts.index(dest_dir)
                                if dir_index + 1 < len(path_parts):
                                    # Keep only the part after the known destination directory
                                    relevant_path = "\\".join(
                                        path_parts[dir_index + 1 :]
                                    )
                                    current_path = source_dir_path / relevant_path
                                    logger.debug(
                                        f"RESTORE: Extracted path after known directory {dest_dir}: {current_path}"
                                    )
                                    found_dir = True
                                    break

                        # If no known directory pattern found, just append to source directory
                        if not found_dir:
                            current_path = source_dir_path / current_path
                            logger.debug(
                                f"RESTORE: No known directory pattern found, appending to source directory: {current_path}"
                            )

            except Exception as e:
                # In case of any errors, fall back to the original behavior
                logger.debug(
                    f"RESTORE: Error processing path, using default resolution: {e}"
                )
                current_path = source_dir_path / current_path

            logger.debug(f"RESTORE: Final current_path: {current_path}")

        # Check if current path exists
        logger.debug(
            f"RESTORE: Checking current_path: {current_path}, exists: {current_path.exists()}"
        )
        if not current_path.exists():
            skip_reason = f"Source file does not exist: {current_path}"
            logger.debug(f"RESTORE: SKIPPING - {skip_reason}")
            result.add_skip(str(current_path), str(original_path), skip_reason)

            # Show status if formatter available
            if formatter:
                status_msg = formatter.format_restore_status(
                    'skip', str(original_path), skip_reason,
                    current_file_num, total_files
                )
                if status_msg:
                    print(status_msg)
            continue

        # Check if original path's parent directory exists
        logger.debug(f"RESTORE: Attempting to restore {current_path} to {original_path}")

        if not original_path.parent.exists():
            try:
                # Create parent directory
                logger.debug(
                    f"[DEBUG] RESTORE: Creating parent directory: {original_path.parent}"
                )
                original_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"[DEBUG] RESTORE: Error creating parent directory: {e}")
                error_msg = f"Error creating parent directory: {e}"
                result.add_failure(
                    str(current_path),
                    str(original_path),
                    error_msg,
                )

                # Show status if formatter available
                if formatter:
                    status_msg = formatter.format_restore_status(
                        'error', str(original_path), error_msg,
                        current_file_num, total_files
                    )
                    if status_msg:
                        print(status_msg)
                continue

        # Check if original path exists and overwrite is not enabled
        logger.debug(
            f"RESTORE: Checking original_path: {original_path}, exists: {original_path.exists()}, overwrite: {options['overwrite']}"
        )
        if original_path.exists() and not options["overwrite"]:
            skip_reason = "Destination exists (use --force to overwrite)"
            logger.debug(f"RESTORE: SKIPPING - Destination exists and overwrite not enabled: {original_path}")
            result.add_skip(str(current_path), str(original_path), skip_reason)

            # Show status if formatter available
            if formatter:
                status_msg = formatter.format_restore_status(
                    'skip', str(original_path), skip_reason,
                    current_file_num, total_files
                )
                if status_msg:
                    print(status_msg)
            continue

        # Apply destination override if provided
        if options.get("destination_override"):
            destination_override = Path(options["destination_override"])

            # IMPORTANT: RESTORE --dst preserves the backup's directory structure,
            # not the original source structure. This respects the user's path style
            # choice (--rel, --abs, --flat) made during backup creation.
            #
            # Examples:
            # 1. Backed up with: COPY source/ --dst backup/ --rel --includeBase
            #    Backup contains: backup/source/file.txt
            #    RESTORE --src backup/ --dst new/
            #    Result: new/source/file.txt (preserves "source/" from backup)
            #
            # 2. Backed up with: COPY source/ --dst backup/ --flat
            #    Backup contains: backup/file.txt
            #    RESTORE --src backup/ --dst new/
            #    Result: new/file.txt (no subdirectories, as backed up)
            #
            # 3. Backed up with: COPY C:/data/file.txt --dst backup/ --abs
            #    Backup contains: backup/C/data/file.txt
            #    RESTORE --src backup/ --dst new/
            #    Result: new/C/data/file.txt (preserves full absolute structure)

            dest_orig_path = Path(str(dest_orig_path).replace("\\", "/"))
            source_orig_path_clean = Path(str(source_orig_path).replace("\\", "/"))

            try:
                # Find the relative path from the backup source to the backed up file
                backup_source = source_dir_path  # This is the --src directory for restore

                if dest_orig_path.is_relative_to(backup_source):
                    # Get the relative path within the backup directory
                    # This preserves the exact structure as stored in the backup
                    relative_backup_path = dest_orig_path.relative_to(backup_source)
                    # Apply the same relative structure to the destination override
                    original_path = destination_override / relative_backup_path
                else:
                    # Fallback: preserve the filename only
                    original_path = destination_override / original_path.name

            except (ValueError, OSError) as e:
                # Final fallback: just use destination override + filename
                original_path = destination_override / original_path.name

        # In dry run mode, just log what would be done
        if options["dry_run"]:
            result.add_success(
                str(current_path), str(original_path), current_path.stat().st_size
            )
            logger.info(f"[DRY RUN] Would restore {current_path} to {original_path}")
            continue

        # Restore file
        try:
            success = restore_file_to_original(
                current_path=current_path,
                original_path=original_path,
                metadata=file_info.get("metadata"),
                preserve_attrs=options["preserve_attrs"],
                overwrite=options["overwrite"],
            )

            if success:
                result.add_success(
                    str(current_path), str(original_path), current_path.stat().st_size
                )

                # Show status if formatter available
                if formatter:
                    status_msg = formatter.format_restore_status(
                        'success', str(original_path), None,
                        current_file_num, total_files
                    )
                    if status_msg:
                        print(status_msg)

                # Verify restoration if enabled
                if (
                    options["verify"]
                    and "hashes" in file_info
                    and options["hash_algorithm"] in file_info["hashes"]
                ):
                    expected_hash = {
                        options["hash_algorithm"]: file_info["hashes"][
                            options["hash_algorithm"]
                        ]
                    }

                    verified, details = verify_file_hash(original_path, expected_hash)
                    result.add_verification(str(original_path), verified, details)

                    if not verified:
                        logger.warning(f"Verification failed for {original_path}")
            else:
                error_msg = "Restoration failed"
                result.add_failure(
                    str(current_path), str(original_path), error_msg
                )

                # Show status if formatter available
                if formatter:
                    status_msg = formatter.format_restore_status(
                        'error', str(original_path), error_msg,
                        current_file_num, total_files
                    )
                    if status_msg:
                        print(status_msg)

        except Exception as e:
            logger.error(f"Error restoring {current_path} to {original_path}: {e}")
            error_msg = str(e)
            result.add_failure(str(current_path), str(original_path), error_msg)

            # Show status if formatter available
            if formatter:
                status_msg = formatter.format_restore_status(
                    'error', str(original_path), error_msg,
                    current_file_num, total_files
                )
                if status_msg:
                    print(status_msg)

    # Update manifest if it came from a file (not from dazzlelinks)
    if not options["dry_run"] and manifest_path and not used_dazzlelinks:
        try:
            manifest.save(manifest_path)
        except Exception as e:
            logger.error(f"Error updating manifest: {e}")

    # Set manifest in result
    result.set_manifest(manifest)

    # Update formatter counters with final results if formatter available
    if formatter:
        formatter.counters['total'] = result.total_count()
        formatter.counters['success'] = result.success_count()
        formatter.counters['skip'] = result.skip_count()
        formatter.counters['error'] = result.failure_count()

    return result


def _create_dazzlelink(
    source_path: Union[str, Path],
    dest_path: Union[str, Path],
    dazzlelink_dir: Optional[Union[str, Path]] = None,
    path_style: str = "relative",
    dest_base: Optional[Union[str, Path]] = None,
    mode: str = "info",  # Default execution mode
    options: Optional[
        Dict[str, Any]
    ] = None,  # Optional settings including all_source_files
) -> bool:
    """
    Create a dazzlelink from destination to source.

    Args:
        source_path: Original source path
        dest_path: Destination path
        dazzlelink_dir: Directory for dazzlelinks (optional)
        path_style: Path preservation style ('relative', 'absolute', 'flat')
        dest_base: Base destination directory

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if dazzlelink module is available
        try:
            from .dazzlelink import create_dazzlelink, is_available

            if not is_available():
                logger.warning(
                    "Dazzlelink integration not available, skipping dazzlelink creation"
                )
                return False
        except ImportError:
            logger.warning(
                "Dazzlelink module not available, skipping dazzlelink creation"
            )
            return False

        # Create the link
        logger.debug(
            f"[DEBUG] Calling create_dazzlelink with source_path={source_path}, dest_path={dest_path}, dazzlelink_dir={dazzlelink_dir}, path_style={path_style}, dest_base={dest_base}"
        )

        # If we have all_source_files in options, pass them for context
        all_source_files = None
        if options and "all_source_files" in options:
            all_source_files = options.get("all_source_files")
            logger.debug(
                f"[DEBUG] Passing {len(all_source_files)} source files for context"
            )

        link_path = create_dazzlelink(
            source_path=str(source_path),
            dest_path=str(dest_path),
            dazzlelink_dir=dazzlelink_dir,
            path_style=path_style,
            dest_base=dest_base,
            mode=mode,
            all_source_files=all_source_files,  # Pass source files for path pattern detection
            options=options,  # Also pass the options dictionary for any other settings
        )

        if link_path:
            logger.debug(f"[DEBUG] Created dazzlelink: {link_path} -> {source_path}")
            # Check if link_path has the correct extension
            if not str(link_path).endswith(".dazzlelink"):
                logger.warning(
                    f"[DEBUG] WARNING: Created dazzlelink file doesn't have .dazzlelink extension: {link_path}"
                )
            else:
                logger.debug(
                    f"[DEBUG] Confirmed dazzlelink file has correct .dazzlelink extension: {link_path}"
                )
            return True
        else:
            logger.warning(f"[DEBUG] Failed to create dazzlelink for {dest_path}")
            return False

    except Exception as e:
        logger.error(f"Error creating dazzlelink: {e}")
        return False


def _generate_verification_report(
    result: OperationResult, report_path: Union[str, Path]
) -> bool:
    """
    Generate a verification report.

    Args:
        result: Operation result
        report_path: Path to save the report

    Returns:
        True if successful, False otherwise
    """
    try:
        import datetime

        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"Verification Report\n")
            f.write(f"===================\n\n")
            f.write(f"Operation: {result.operation_type}\n")
            if result.command_line:
                f.write(f"Command: {result.command_line}\n")
            f.write(f"Date: {datetime.datetime.now().isoformat()}\n\n")

            f.write(f"Summary\n")
            f.write(f"-------\n")
            f.write(f"Total files: {result.total_count()}\n")
            f.write(f"Succeeded: {result.success_count()}\n")
            f.write(f"Failed: {result.failure_count()}\n")
            f.write(f"Skipped: {result.skip_count()}\n")
            f.write(f"Verified: {result.verified_count()}\n")
            f.write(f"Unverified: {result.unverified_count()}\n\n")

            if result.unverified:
                f.write(f"Unverified Files\n")
                f.write(f"---------------\n")
                for path, details in result.unverified:
                    f.write(f"File: {path}\n")
                    if details:
                        for algorithm, (match, expected, actual) in details.items():
                            f.write(f"  {algorithm}:\n")
                            f.write(f"    Expected: {expected}\n")
                            f.write(f"    Actual: {actual}\n")
                    else:
                        f.write(f"  No hash details available\n")
                    f.write("\n")

            if result.failed:
                f.write(f"Failed Files\n")
                f.write(f"-----------\n")
                for source, dest in result.failed:
                    f.write(f"Source: {source}\n")
                    f.write(f"Destination: {dest}\n")
                    if source in result.error_messages:
                        f.write(f"Error: {result.error_messages[source]}\n")
                    f.write("\n")

        logger.info(f"Verification report saved to {report_path}")
        return True

    except Exception as e:
        logger.error(f"Error generating verification report: {e}")
        return False
