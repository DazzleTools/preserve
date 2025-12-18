"""
CLEANUP operation handler for preserve tool.

This module implements the CLEANUP command which helps recover from
partial MOVE operations by either completing them or rolling back.

Part of the 0.7.x Destination Awareness feature (#43).
"""

import os
import sys
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from preservelib.manifest import read_manifest, find_available_manifests, calculate_file_hash
from preservelib.metadata import collect_file_metadata, apply_file_metadata
from preserve.utils import format_bytes_detailed

logger = logging.getLogger(__name__)


class CleanupStatus:
    """Status of files for cleanup operation."""

    def __init__(self):
        # Files that exist at both source and destination
        self.both_exist: List[Tuple[Path, Path, str]] = []  # (src, dst, status)

        # Files that exist only at source (never copied)
        self.source_only: List[Path] = []

        # Files that exist only at destination (successfully moved)
        self.dest_only: List[Tuple[Path, Path]] = []  # (original_src, dst)

        # Files that don't exist at either location (lost)
        self.neither_exist: List[Tuple[Path, Path]] = []  # (src, dst)

        # Files with verification failures
        self.verification_failed: List[Tuple[Path, Path, str]] = []  # (src, dst, reason)

        # Extra files at destination not in manifest
        self.extra_dest_files: List[Path] = []

    def total_manifest_files(self) -> int:
        """Total files tracked in manifest."""
        return (len(self.both_exist) + len(self.source_only) +
                len(self.dest_only) + len(self.neither_exist))

    def is_complete(self) -> bool:
        """Check if move operation appears complete."""
        return (len(self.source_only) == 0 and
                len(self.both_exist) == 0 and
                len(self.neither_exist) == 0)

    def needs_recovery(self) -> bool:
        """Check if recovery is needed."""
        return (len(self.source_only) > 0 or
                len(self.both_exist) > 0 or
                len(self.neither_exist) > 0)


def analyze_cleanup_status(
    manifest_path: Path,
    hash_algorithm: str = "SHA256"
) -> Tuple[CleanupStatus, dict]:
    """
    Analyze the state of a MOVE operation for cleanup.

    Args:
        manifest_path: Path to the manifest file
        hash_algorithm: Hash algorithm for verification

    Returns:
        Tuple of (CleanupStatus, manifest_data)
    """
    status = CleanupStatus()

    # Load manifest
    manifest_obj = read_manifest(manifest_path)
    if not manifest_obj:
        raise ValueError(f"Could not load manifest: {manifest_path}")

    # Access the underlying manifest data dictionary
    manifest_data = manifest_obj.manifest

    # Get operation info - check both old and new locations
    operations = manifest_data.get("operations", [])
    if operations:
        operation = operations[0]  # Get first operation
    else:
        operation = manifest_data.get("operation", {})

    op_type = operation.get("type") or operation.get("operation_type")
    if op_type != "MOVE":
        logger.warning(f"Manifest is for {op_type or 'unknown'} operation, not MOVE")

    # Analyze each file in manifest - files is a dictionary keyed by file_id
    files_dict = manifest_data.get("files", {})
    dest_base = Path(manifest_data.get("dest_base", operation.get("destination_path", "")))

    manifest_dest_paths = set()

    for file_id, file_entry in files_dict.items():
        source_path = Path(file_entry.get("source_path", ""))
        dest_path = Path(file_entry.get("destination_path", ""))

        manifest_dest_paths.add(dest_path)

        source_exists = source_path.exists()
        dest_exists = dest_path.exists()

        if source_exists and dest_exists:
            # Both exist - need to determine which is canonical
            # Verify hashes to check consistency
            expected_hash = file_entry.get("hashes", {}).get(hash_algorithm)
            if expected_hash:
                try:
                    dest_hashes = calculate_file_hash(dest_path, [hash_algorithm])
                    dest_hash = dest_hashes.get(hash_algorithm)
                    if dest_hash and dest_hash.lower() == expected_hash.lower():
                        status.both_exist.append((source_path, dest_path, "dest_verified"))
                    else:
                        status.both_exist.append((source_path, dest_path, "dest_mismatch"))
                except Exception as e:
                    status.both_exist.append((source_path, dest_path, f"verify_error: {e}"))
            else:
                status.both_exist.append((source_path, dest_path, "no_hash"))

        elif source_exists and not dest_exists:
            # Source only - file was never copied
            status.source_only.append(source_path)

        elif not source_exists and dest_exists:
            # Dest only - successfully moved
            status.dest_only.append((source_path, dest_path))

        else:
            # Neither exists - file is lost
            status.neither_exist.append((source_path, dest_path))

    # Find extra destination files not in manifest
    if dest_base.exists():
        for dest_file in dest_base.rglob("*"):
            if dest_file.is_file():
                # Skip manifest files
                if dest_file.name.startswith("preserve_manifest"):
                    continue
                if dest_file.suffix == ".dazzlelink":
                    continue
                if ".preserve" in str(dest_file):
                    continue
                if dest_file not in manifest_dest_paths:
                    status.extra_dest_files.append(dest_file)

    return status, manifest_data


def format_cleanup_report(
    status: CleanupStatus,
    manifest: dict,
    verbose: bool = False
) -> str:
    """Format cleanup status as a human-readable report."""
    lines = []

    lines.append("=" * 60)
    lines.append("CLEANUP STATUS REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Get operation info - check both old and new locations
    operations = manifest.get("operations", [])
    if operations:
        operation = operations[0]
    else:
        operation = manifest.get("operation", {})

    op_type = operation.get("type") or operation.get("operation_type", "unknown")
    op_timestamp = operation.get("timestamp", "unknown")
    dest_base = manifest.get("dest_base", operation.get("destination_path", "unknown"))

    lines.append(f"Operation: {op_type}")
    lines.append(f"Timestamp: {op_timestamp}")
    lines.append(f"Dest base: {dest_base}")
    lines.append("")

    lines.append("FILE STATUS SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Total files in manifest:    {status.total_manifest_files():5d}")
    lines.append(f"  Successfully moved:         {len(status.dest_only):5d}")
    lines.append(f"  Still at source (not moved):{len(status.source_only):5d}")
    lines.append(f"  Exist at both locations:    {len(status.both_exist):5d}")
    lines.append(f"  Lost (neither location):    {len(status.neither_exist):5d}")
    lines.append(f"  Extra files at dest:        {len(status.extra_dest_files):5d}")
    lines.append("")

    if status.is_complete():
        lines.append("STATUS: Move operation appears COMPLETE")
        lines.append("        All files are at destination, sources removed.")
    elif status.needs_recovery():
        lines.append("STATUS: Move operation is INCOMPLETE - recovery needed")
        lines.append("")
        lines.append("RECOMMENDED ACTIONS:")
        if status.source_only:
            lines.append(f"  - {len(status.source_only)} files need to be copied to destination")
        if status.both_exist:
            lines.append(f"  - {len(status.both_exist)} files exist at both locations (verify and cleanup)")
        if status.neither_exist:
            lines.append(f"  - {len(status.neither_exist)} files are MISSING from both locations!")
    lines.append("")

    if verbose:
        if status.source_only:
            lines.append("FILES AT SOURCE ONLY (not yet copied)")
            lines.append("-" * 40)
            for src in status.source_only[:10]:
                lines.append(f"  {src}")
            if len(status.source_only) > 10:
                lines.append(f"  ... and {len(status.source_only) - 10} more")
            lines.append("")

        if status.both_exist:
            lines.append("FILES AT BOTH LOCATIONS")
            lines.append("-" * 40)
            for src, dst, verify_status in status.both_exist[:10]:
                lines.append(f"  {src.name} [{verify_status}]")
            if len(status.both_exist) > 10:
                lines.append(f"  ... and {len(status.both_exist) - 10} more")
            lines.append("")

        if status.neither_exist:
            lines.append("MISSING FILES (neither source nor destination)")
            lines.append("-" * 40)
            for src, dst in status.neither_exist[:10]:
                lines.append(f"  {src}")
            if len(status.neither_exist) > 10:
                lines.append(f"  ... and {len(status.neither_exist) - 10} more")
            lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)


def handle_cleanup_operation(args, logger):
    """Handle CLEANUP operation."""
    logger.info("Starting CLEANUP operation")

    # Find manifest
    if args.manifest:
        manifest_path = Path(args.manifest)
    elif args.src:
        # Find manifests in source directory
        manifests = find_available_manifests(Path(args.src))
        if not manifests:
            logger.error(f"No manifests found in {args.src}")
            return 1

        if args.number:
            # Select by number
            matching = [m for m in manifests if m.get("number") == args.number]
            if not matching:
                logger.error(f"No manifest with number {args.number}")
                return 1
            manifest_path = Path(matching[0]["path"])
        else:
            # Use latest (first in list, sorted by timestamp)
            manifest_path = Path(manifests[0]["path"])
            logger.info(f"Using latest manifest: {manifest_path.name}")
    else:
        logger.error("Please specify --src or --manifest")
        return 1

    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        return 1

    # Get hash algorithm
    hash_algorithms = args.hash if args.hash else ["SHA256"]
    hash_algorithm = hash_algorithms[0]

    # Analyze status
    try:
        status, manifest = analyze_cleanup_status(manifest_path, hash_algorithm)
    except Exception as e:
        logger.error(f"Error analyzing cleanup status: {e}")
        return 1

    # Check if this is a MOVE manifest
    operation = manifest.get("operation", {})
    if operation.get("type") != "MOVE":
        logger.warning(f"This manifest is for a {operation.get('type', 'unknown')} operation, not MOVE")
        logger.warning("CLEANUP is designed for recovering from partial MOVE operations")

    # Handle mode
    mode = args.mode
    execute = args.execute
    verbose = args.verbose > 0

    if mode == "status" or not execute:
        # Just show status report
        print(format_cleanup_report(status, manifest, verbose=True))

        if not execute and mode != "status":
            print("")
            print("This was a DRY RUN. Use --execute to perform the cleanup.")
        return 0

    elif mode == "complete":
        # Complete the move operation
        print(format_cleanup_report(status, manifest, verbose=verbose))
        print("")

        if status.is_complete():
            print("Move operation is already complete. Nothing to do.")
            return 0

        print("=" * 60)
        print("COMPLETING MOVE OPERATION")
        print("=" * 60)
        print("")

        success_count = 0
        failure_count = 0
        skipped_count = 0
        bytes_copied = 0
        sources_removed = 0

        # Step 1: Copy files that only exist at source
        if status.source_only:
            print(f"Copying {len(status.source_only)} files from source to destination...")
            files_dict = manifest.get("files", {})
            # Build lookup by source path - files is a dict keyed by file_id
            files_by_source = {Path(f.get("source_path", "")): f for f in files_dict.values()}

            for source_path in status.source_only:
                file_entry = files_by_source.get(source_path)
                if not file_entry:
                    logger.warning(f"No manifest entry for {source_path}")
                    skipped_count += 1
                    continue

                dest_path = Path(file_entry.get("destination_path", ""))
                if not dest_path:
                    logger.warning(f"No destination path for {source_path}")
                    skipped_count += 1
                    continue

                try:
                    # Create destination directory
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    # Copy file with metadata
                    metadata = collect_file_metadata(source_path)
                    shutil.copy2(source_path, dest_path)
                    if metadata:
                        apply_file_metadata(dest_path, metadata)

                    bytes_copied += source_path.stat().st_size

                    # Verify copy
                    expected_hash = file_entry.get("hashes", {}).get(hash_algorithm)
                    if expected_hash:
                        actual_hashes = calculate_file_hash(dest_path, [hash_algorithm])
                        actual_hash = actual_hashes.get(hash_algorithm)
                        if actual_hash and actual_hash.lower() == expected_hash.lower():
                            # Verified - remove source
                            source_path.unlink()
                            sources_removed += 1
                            success_count += 1
                            logger.info(f"Completed: {source_path.name}")
                        else:
                            logger.warning(f"Verification failed for {source_path}, keeping source")
                            failure_count += 1
                    else:
                        # No hash to verify, remove source anyway
                        source_path.unlink()
                        sources_removed += 1
                        success_count += 1
                        logger.info(f"Completed (no verify): {source_path.name}")

                except Exception as e:
                    logger.error(f"Error completing {source_path}: {e}")
                    failure_count += 1

        # Step 2: Handle files that exist at both locations
        if status.both_exist:
            print(f"Processing {len(status.both_exist)} files at both locations...")

            for source_path, dest_path, verify_status in status.both_exist:
                if verify_status == "dest_verified":
                    # Destination is correct - safe to remove source
                    try:
                        source_path.unlink()
                        sources_removed += 1
                        success_count += 1
                        logger.info(f"Removed duplicate source: {source_path.name}")
                    except Exception as e:
                        logger.error(f"Error removing source {source_path}: {e}")
                        failure_count += 1
                else:
                    # Destination not verified - need to re-copy
                    logger.warning(f"Dest mismatch for {source_path.name}, re-copying")
                    try:
                        metadata = collect_file_metadata(source_path)
                        shutil.copy2(source_path, dest_path)
                        if metadata:
                            apply_file_metadata(dest_path, metadata)

                        # Remove source after re-copy
                        source_path.unlink()
                        sources_removed += 1
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Error re-copying {source_path}: {e}")
                        failure_count += 1

        # Step 3: Report lost files
        if status.neither_exist:
            print("")
            print("WARNING: The following files are MISSING from both locations:")
            for source_path, dest_path in status.neither_exist:
                print(f"  - {source_path}")
            print("These files cannot be recovered.")

        # Summary
        print("")
        print("=" * 60)
        print("CLEANUP COMPLETE SUMMARY")
        print("=" * 60)
        print(f"  Files processed:     {success_count + failure_count + skipped_count}")
        print(f"  Successfully moved:  {success_count}")
        print(f"  Failed:              {failure_count}")
        print(f"  Skipped:             {skipped_count}")
        print(f"  Bytes copied:        {format_bytes_detailed(bytes_copied)}")
        print(f"  Sources removed:     {sources_removed}")
        if status.neither_exist:
            print(f"  Lost files:          {len(status.neither_exist)}")

        return 0 if failure_count == 0 else 1

    elif mode == "rollback":
        # Rollback to original state
        print(format_cleanup_report(status, manifest, verbose=verbose))
        print("")

        if not status.needs_recovery() and len(status.dest_only) == 0:
            print("Nothing to rollback. Files are at original locations.")
            return 0

        print("=" * 60)
        print("ROLLING BACK MOVE OPERATION")
        print("=" * 60)
        print("")

        success_count = 0
        failure_count = 0
        bytes_restored = 0
        dests_removed = 0

        # Step 1: Restore files that only exist at destination back to source
        if status.dest_only:
            print(f"Restoring {len(status.dest_only)} files to original source locations...")

            for original_source, dest_path in status.dest_only:
                try:
                    # Create source directory
                    original_source.parent.mkdir(parents=True, exist_ok=True)

                    # Copy file back with metadata
                    metadata = collect_file_metadata(dest_path)
                    shutil.copy2(dest_path, original_source)
                    if metadata:
                        apply_file_metadata(original_source, metadata)

                    bytes_restored += dest_path.stat().st_size

                    # Verify restoration
                    files_dict = manifest.get("files", {})
                    file_entry = next(
                        (f for f in files_dict.values() if Path(f.get("source_path", "")) == original_source),
                        None
                    )

                    if file_entry:
                        expected_hash = file_entry.get("hashes", {}).get(hash_algorithm)
                        if expected_hash:
                            actual_hashes = calculate_file_hash(original_source, [hash_algorithm])
                            actual_hash = actual_hashes.get(hash_algorithm)
                            if actual_hash and actual_hash.lower() == expected_hash.lower():
                                # Verified - remove destination
                                dest_path.unlink()
                                dests_removed += 1
                                success_count += 1
                                logger.info(f"Restored: {original_source.name}")
                            else:
                                logger.warning(f"Verification failed for restored {original_source}, keeping both")
                                failure_count += 1
                        else:
                            # No hash to verify, remove dest anyway
                            dest_path.unlink()
                            dests_removed += 1
                            success_count += 1
                            logger.info(f"Restored (no verify): {original_source.name}")
                    else:
                        # No manifest entry, remove dest anyway
                        dest_path.unlink()
                        dests_removed += 1
                        success_count += 1
                        logger.info(f"Restored (no manifest): {original_source.name}")

                except Exception as e:
                    logger.error(f"Error restoring {dest_path} to {original_source}: {e}")
                    failure_count += 1

        # Step 2: Handle files that exist at both locations - keep source, remove dest
        if status.both_exist:
            print(f"Cleaning up {len(status.both_exist)} duplicate destination files...")

            for source_path, dest_path, verify_status in status.both_exist:
                # Source exists, so remove the destination copy
                try:
                    dest_path.unlink()
                    dests_removed += 1
                    success_count += 1
                    logger.info(f"Removed destination copy: {dest_path.name}")
                except Exception as e:
                    logger.error(f"Error removing destination {dest_path}: {e}")
                    failure_count += 1

        # Step 3: Handle extra destination files (if --keep-extra not specified)
        keep_extra = getattr(args, 'keep_extra', False)
        if status.extra_dest_files and not keep_extra:
            print(f"Note: {len(status.extra_dest_files)} extra files at destination not in manifest")
            print("      Use --keep-extra to preserve these files, or remove manually")

        # Step 4: Report lost files
        if status.neither_exist:
            print("")
            print("WARNING: The following files are MISSING from both locations:")
            for source_path, dest_path in status.neither_exist:
                print(f"  - {source_path}")
            print("These files cannot be recovered.")

        # Summary
        print("")
        print("=" * 60)
        print("CLEANUP ROLLBACK SUMMARY")
        print("=" * 60)
        print(f"  Files processed:       {success_count + failure_count}")
        print(f"  Successfully restored: {success_count}")
        print(f"  Failed:                {failure_count}")
        print(f"  Bytes restored:        {format_bytes_detailed(bytes_restored)}")
        print(f"  Dest files removed:    {dests_removed}")
        if status.neither_exist:
            print(f"  Lost files:            {len(status.neither_exist)}")

        return 0 if failure_count == 0 else 1

    return 0
