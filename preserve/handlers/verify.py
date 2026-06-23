"""
VERIFY operation handler.

This module handles the VERIFY command for the preserve tool.
Extracted from preserve.py for better code organization.
"""

import logging
import json
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def get_hash_algorithms(args):
    """Get hash algorithms from command-line arguments."""
    if args.hash:
        return args.hash
    else:
        return ['SHA256']  # Default


def handle_verify_operation(args, logger):
    """Handle VERIFY operation with flexible verification modes."""
    logger.info("Starting VERIFY operation")

    # Import from the verification modules
    from dazzle_preservelib.verification import find_and_verify_manifest, verify_three_way
    from dazzle_preservelib.manifest import (
        find_available_manifests,
        read_manifest,
        extract_source_from_manifest,
        PreserveManifest
    )

    # Get destination path
    dest_path = Path(args.dst) if args.dst else None

    # Determine verification mode from --check parameter
    check_mode = None  # Will be determined based on provided arguments
    if hasattr(args, 'check') and args.check:
        check_mode = args.check
        # Normalize check values
        if check_mode == 'src':
            check_mode = 'source'
        elif check_mode == 'dst':
            check_mode = 'dest'
    elif hasattr(args, 'auto') and args.auto:
        check_mode = 'auto'

    # If no explicit mode, determine from provided arguments (for backward compatibility)
    if not check_mode:
        if args.src and args.dst:
            check_mode = 'both'  # Both src and dst provided = three-way
        elif args.dst:
            check_mode = 'dest'  # Only dst provided = two-way
        elif args.src:
            check_mode = 'source'  # Only src provided = source-only
        else:
            check_mode = 'auto'  # Neither provided, try auto-detect

    # If no --dst provided but --manifest is, try to infer dst
    if not dest_path and args.manifest:
        manifest_path = Path(args.manifest)
        if manifest_path.exists():
            # Use manifest's parent directory as destination
            dest_path = manifest_path.parent
            if '.preserve' in dest_path.parts:
                # Go up one more level if manifest is in .preserve directory
                dest_path = dest_path.parent
            logger.info(f"Using manifest location as destination: {dest_path}")

    # Validate destination for modes that need it
    if check_mode in ['dest', 'both'] or (check_mode == 'auto' and not args.src):
        if not dest_path:
            logger.error("Destination path required for verification")
            return 1
        if not dest_path.exists():
            logger.error(f"Destination directory does not exist: {dest_path}")
            return 1

    # Handle --list flag to show available manifests
    if args.list:
        manifests = find_available_manifests(dest_path)
        if not manifests:
            print("No preserve manifests found in destination.")
            return 1

        print(f"Available manifests in {dest_path}:")
        for i, (manifest_num, manifest_path, description) in enumerate(manifests, 1):
            # Try to get basic info from the manifest
            try:
                with open(manifest_path, 'r') as f:
                    import json
                    data = json.load(f)
                    timestamp = data.get('timestamp', 'Unknown')
                    file_count = len(data.get('files', {}))
                    desc_str = f" ({description})" if description else ""
                    print(f"  {i}. {manifest_path.name}{desc_str} - {file_count} files, created {timestamp}")
            except Exception as e:
                print(f"  {i}. {manifest_path.name} - (could not read)")
        return 0

    # Get hash algorithms
    hash_algorithms = get_hash_algorithms(args)

    # Find and load the manifest first
    manifest_path = None
    manifest = None

    # Check for directly specified manifest
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            logger.error(f"Specified manifest does not exist: {manifest_path}")
            return 1
    elif dest_path:
        # Find manifest in destination
        manifests = find_available_manifests(dest_path)
        if hasattr(args, 'manifest_number') and args.manifest_number:
            # User specified a number
            for num, path, desc in manifests:
                if num == args.manifest_number:
                    manifest_path = path
                    break
            if not manifest_path:
                logger.error(f"Manifest number {args.manifest_number} not found")
                return 1
        elif manifests:
            # Use the latest manifest
            manifest_path = manifests[-1][1]
        else:
            logger.error("No manifests found in destination")
            return 1

    # Load the manifest
    if manifest_path:
        manifest = read_manifest(manifest_path)
        if not manifest:
            logger.error(f"Failed to load manifest: {manifest_path}")
            return 1
        logger.info(f"Using manifest: {manifest_path.name}")

    # Determine source path(s) based on mode and available options
    source_paths = []
    source_path = None

    # Add explicitly provided source
    if args.src:
        source_path = Path(args.src)
        if source_path.exists():
            source_paths.append(source_path)
        else:
            logger.error(f"Source directory does not exist: {source_path}")
            # If source was explicitly provided but doesn't exist, that's an error
            return 1

    # Add alternative source paths
    if hasattr(args, 'alt_src') and args.alt_src:
        for alt_src in args.alt_src:
            alt_path = Path(alt_src)
            if alt_path.exists():
                source_paths.append(alt_path)
                logger.info(f"Added alternative source: {alt_path}")
            else:
                logger.warning(f"Alternative source does not exist: {alt_path}")

    # Auto-detect source from manifest if in auto mode or if no source provided
    if check_mode == 'auto' or (check_mode in ['source', 'both'] and not source_paths):
        if manifest:
            detected_source = extract_source_from_manifest(manifest)
            if detected_source and detected_source.exists():
                source_paths.append(detected_source)
                logger.info(f"Auto-detected source from manifest: {detected_source}")
            elif detected_source:
                logger.warning(f"Source extracted from manifest does not exist: {detected_source}")

    # Determine what verification to perform based on mode and available paths
    perform_source_check = False
    perform_dest_check = False
    perform_three_way = False

    if check_mode == 'auto':
        # Auto mode: verify what's available
        if source_paths and dest_path:
            perform_three_way = True
        elif dest_path:
            perform_dest_check = True
        elif source_paths:
            perform_source_check = True
        else:
            logger.error("No paths available for verification")
            return 1
    elif check_mode == 'source':
        if not source_paths:
            logger.error("No source path available for source verification")
            return 1
        perform_source_check = True
    elif check_mode == 'dest':
        if not dest_path:
            logger.error("No destination path available for destination verification")
            return 1
        perform_dest_check = True
    elif check_mode == 'both':
        if not source_paths:
            logger.error("No source path available for verification")
            return 1
        if not dest_path:
            logger.error("No destination path available for verification")
            return 1
        perform_three_way = True

    # Use the first available source path for three-way verification
    if perform_three_way and source_paths:
        source_path = source_paths[0]

    # Perform the appropriate verification
    if perform_three_way and source_path and dest_path:
        # Perform three-way verification
        print(f"\nPerforming three-way verification:")
        print(f"  Source:    {source_path}")
        print(f"  Preserved: {dest_path}")
        print(f"  Manifest:  {manifest_path.name}")
        print()

        result = verify_three_way(
            source_path=source_path,
            preserved_path=dest_path,
            manifest=manifest,
            hash_algorithms=hash_algorithms
        )

        # Display three-way results
        print("Three-Way Verification Results:")
        print("="*50)

        total_files = (len(result.all_match) + len(result.source_modified) +
                      len(result.preserved_corrupted) +
                      len(result.not_found) + len(result.errors))

        # Summary
        if result.all_match:
            print(f"  [OK] All match: {len(result.all_match)}")
        if result.source_modified:
            print(f"  [WARN] Source modified: {len(result.source_modified)}")
        if result.preserved_corrupted:
            print(f"  [FAIL] Preserved corrupted: {len(result.preserved_corrupted)}")
        if result.not_found:
            print(f"  [?] Not found: {len(result.not_found)}")
        if result.errors:
            print(f"  [ERR] Errors: {len(result.errors)}")

        # Detailed output for issues
        if result.source_modified:
            print("\n[WARN] Files modified in source since preservation:")
            for item in result.source_modified[:10]:
                print(f"    - {item.file_path}")
            if len(result.source_modified) > 10:
                print(f"    ... and {len(result.source_modified) - 10} more")

        if result.preserved_corrupted:
            print("\n[FAIL] CRITICAL: Preserved files corrupted:")
            for item in result.preserved_corrupted:
                print(f"    - {item.file_path}")

        if result.errors:
            # Check for complex differences in errors
            complex_diffs = [e for e in result.errors if "Complex difference" in e.error_message]
            other_errors = [e for e in result.errors if "Complex difference" not in e.error_message]

            if complex_diffs:
                print("\n[COMPLEX] Files where all three differ (source != preserved != manifest):")
                for item in complex_diffs[:5]:
                    print(f"    - {item.file_path}")
                if len(complex_diffs) > 5:
                    print(f"    ... and {len(complex_diffs) - 5} more")

            if other_errors:
                print("\n[ERR] Other errors:")
                for item in other_errors[:5]:
                    print(f"    - {item.file_path}: {item.error_message}")
                if len(other_errors) > 5:
                    print(f"    ... and {len(other_errors) - 5} more")

        # Handle report if requested
        if hasattr(args, 'report') and args.report:
            report_path = Path(args.report)
            with open(report_path, 'w') as f:
                f.write(f"Three-Way Verification Report\n")
                f.write(f"="*50 + "\n\n")
                f.write(f"Source:    {source_path}\n")
                f.write(f"Preserved: {dest_path}\n")
                f.write(f"Manifest:  {manifest_path.name}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")
                # Separate complex differences from other errors
                complex_diffs = [e for e in result.errors if "Complex difference" in e.error_message] if result.errors else []
                other_errors = [e for e in result.errors if "Complex difference" not in e.error_message] if result.errors else []

                f.write(f"Summary:\n")
                f.write(f"  All match: {len(result.all_match)}\n")
                f.write(f"  Source modified: {len(result.source_modified)}\n")
                f.write(f"  Preserved corrupted: {len(result.preserved_corrupted)}\n")
                f.write(f"  Complex differences: {len(complex_diffs)}\n")
                f.write(f"  Not found: {len(result.not_found)}\n")
                f.write(f"  Other errors: {len(other_errors)}\n\n")

                if result.source_modified:
                    f.write("Source Modified Files:\n")
                    for item in result.source_modified:
                        f.write(f"  - {item.file_path}\n")
                    f.write("\n")

                if result.preserved_corrupted:
                    f.write("Preserved Corrupted Files:\n")
                    for item in result.preserved_corrupted:
                        f.write(f"  - {item.file_path}\n")
                    f.write("\n")

                if complex_diffs:
                    f.write("Complex Differences (all three differ):\n")
                    for item in complex_diffs:
                        f.write(f"  - {item.file_path}\n")
                    f.write("\n")

                if other_errors:
                    f.write("Other Errors:\n")
                    for item in other_errors:
                        f.write(f"  - {item.file_path}: {item.error_message}\n")

            print(f"\n  Report written to: {report_path}")

        # Return 0 only if no critical issues
        return 0 if (len(result.preserved_corrupted) == 0 and len(result.errors) == 0) else 1

    elif perform_source_check:
        # Source-only verification
        if not source_path and source_paths:
            source_path = source_paths[0]

        if not source_path:
            logger.error("No source path available for source-only verification")
            return 1

        print(f"\nPerforming source-only verification:")
        print(f"  Source:   {source_path}")
        print(f"  Manifest: {manifest_path.name if manifest_path else 'Unknown'}")
        print()

        # Use verify_three_way but only check source vs manifest
        try:
            from dazzle_preservelib.verification import verify_source_against_manifest
            result = verify_source_against_manifest(
                source_path=source_path,
                manifest=manifest,
                hash_algorithms=hash_algorithms
            )
        except (ImportError, AttributeError):
            # Function doesn't exist yet, use three-way with dummy dest
            logger.info("Using three-way verification for source-only check")
            result = verify_three_way(
                source_path=source_path,
                preserved_path=source_path,  # Use source as dest to simplify
                manifest=manifest,
                hash_algorithms=hash_algorithms
            )

        # Display source verification results
        print("Source Verification Results:")
        print("="*50)

        if hasattr(result, 'all_match') and result.all_match:
            print(f"  [OK] Files match manifest: {len(result.all_match)}")
        if hasattr(result, 'source_modified') and result.source_modified:
            print(f"  [CHANGED] Files modified since preservation: {len(result.source_modified)}")
        if hasattr(result, 'not_found') and result.not_found:
            print(f"  [MISSING] Files not found: {len(result.not_found)}")
        if hasattr(result, 'errors') and result.errors:
            print(f"  [ERROR] Verification errors: {len(result.errors)}")

        # Return success if no critical errors
        return 0 if (not hasattr(result, 'errors') or len(result.errors) == 0) else 1

    elif perform_dest_check:
        # Two-way verification (existing behavior)
        print(f"\nPerforming two-way verification (preserved vs manifest):")
        print(f"  Preserved: {dest_path}")
        print(f"  Tip: Use --src to also verify against original source files")
        print()

        # Run verification using the existing module
        try:
            manifest, result = find_and_verify_manifest(
                destination=dest_path,
                manifest_number=args.manifest_number if hasattr(args, 'manifest_number') else None,
                manifest_path=manifest_path,
                hash_algorithms=hash_algorithms
            )

            # Print summary
            print("VERIFY Operation Summary:")
            print(f"  Using manifest: {manifest.manifest_path.name if manifest else 'Unknown'}")
            print(f"  Verified: {result.verified_count}")
            print(f"  Failed: {result.failed_count}")
            print(f"  Missing: {result.missing_count}")

            # Print details if there are issues
            if result.failed_files:
                print("\nFailed files:")
                for file in result.failed_files:
                    print(f"  - {file}")

            if result.missing_files:
                print("\nMissing files:")
                for file in result.missing_files:
                    print(f"  - {file}")

            # Handle report if requested
            if hasattr(args, 'report') and args.report:
                report_path = Path(args.report)
                with open(report_path, 'w') as f:
                    f.write(f"Verification Report\n")
                    f.write(f"==================\n\n")
                    f.write(f"Manifest: {manifest.manifest_path.name if manifest else 'Unknown'}\n")
                    f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")
                    f.write(f"Summary:\n")
                    f.write(f"  Verified: {result.verified_count}\n")
                    f.write(f"  Failed: {result.failed_count}\n")
                    f.write(f"  Missing: {result.missing_count}\n\n")

                    if result.failed_files:
                        f.write("Failed Files:\n")
                        for file in result.failed_files:
                            f.write(f"  - {file}\n")
                        f.write("\n")

                    if result.missing_files:
                        f.write("Missing Files:\n")
                        for file in result.missing_files:
                            f.write(f"  - {file}\n")

                print(f"\n  Report written to: {report_path}")

            # Return success if all files verified
            return 0 if result.is_successful else 1

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return 1