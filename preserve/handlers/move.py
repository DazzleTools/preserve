"""
MOVE operation handler for preserve tool.

This module implements the MOVE command which moves files to a destination
while preserving their paths and creating verification manifests. Files are
only deleted from source after successful verification.

TODO: Future refactoring opportunities:
- Extract common path validation logic shared with COPY
- Share Windows path validation with copy.py
- Consider creating common base class for copy/move operations
- The verification and deletion logic could be extracted for reuse
"""

import os
import sys
import logging
import datetime
from pathlib import Path

from preservelib import operations
from preservelib import links
from preservelib.operations import InsufficientSpaceError, PermissionCheckError
from preserve.utils import (
    find_files_from_args,
    get_hash_algorithms,
    get_path_style,
    get_preserve_dir,
    get_manifest_path,
    get_dazzlelink_dir,
    format_bytes_detailed,
    _show_directory_help_message,
    HAVE_DAZZLELINK
)

logger = logging.getLogger(__name__)


def handle_move_operation(args, logger):
    """Handle MOVE operation"""
    logger.info("Starting MOVE operation")

    # Check for common issue: trailing backslash in source path on Windows
    if args.sources and sys.platform == 'win32':
        for src in args.sources:
            # Check if the path looks like it might have eaten subsequent arguments
            # (happens when trailing \ escapes the closing quote)
            if '--' in src or src.count(' ') > 2:
                logger.error("")
                logger.error("ERROR: It appears the source path may have captured command-line arguments.")
                logger.error("       This usually happens when a path ends with a backslash (\\) before a quote.")
                logger.error("")
                logger.error("Problem: The trailing backslash escapes the closing quote.")
                logger.error("  Example: \"C:\\path\\to\\dir\\\" <- The \\ escapes the \"")
                logger.error("")
                logger.error("Solution: Remove the trailing backslash:")
                logger.error("  Correct: \"C:\\path\\to\\dir\"")
                logger.error("  Or use:  C:\\path\\to\\dir (without quotes if no spaces)")
                return 1
            elif src.endswith('\\'):
                logger.warning("")
                logger.warning(f"WARNING: Source path has a trailing backslash: '{src}'")
                logger.warning("         This can cause issues on Windows command line.")
                logger.warning("         Consider removing it: '{}'".format(src[:-1]))

    # Check for common issue: trailing backslash in destination path on Windows
    if hasattr(args, 'dst') and args.dst and sys.platform == 'win32':
        dst = args.dst
        # Check if the destination path looks like it captured subsequent arguments
        if '--' in dst or '-L' in dst or dst.count(' ') > 2:
            logger.error("")
            logger.error("ERROR: It appears the destination path may have captured command-line arguments.")
            logger.error(f"       Received: '{dst}'")
            logger.error("")
            logger.error("Problem: The trailing backslash escapes the closing quote.")
            logger.error("  Example: --dst \"E:\\\" <- The \\ escapes the \"")
            logger.error("")
            logger.error("Solution: Remove the trailing backslash from the destination:")
            logger.error("  Correct: --dst \"E:\"")
            logger.error("  Or use:  --dst E:\\ (without quotes)")
            return 1

    # Find source files
    source_files = find_files_from_args(args)

    # Check if user provided a directory without --recursive and it has subdirectories
    # Only show warning if we found SOME files (but are missing subdirectory files)
    if source_files and args.sources and not args.recursive:
        for src in args.sources:
            src_path = Path(src)
            if src_path.exists() and src_path.is_dir():
                # Check if there are subdirectories with files
                has_subdirs_with_files = False
                for root, dirs, files in os.walk(src_path):
                    if root != str(src_path) and files:
                        has_subdirs_with_files = True
                        break

                if has_subdirs_with_files:
                    _show_directory_help_message(args, logger, src, operation="MOVE", is_warning=True)

    if not source_files:
        # Check if the user provided a directory without --recursive flag
        if args.sources:
            for src in args.sources:
                src_path = Path(src)
                if src_path.exists() and src_path.is_dir() and not args.recursive:
                    _show_directory_help_message(args, logger, src, operation="MOVE", is_warning=False)
                    return 1

        logger.error("No source files found")
        return 1

    logger.info(f"Found {len(source_files)} source files")

    # Get destination path
    dest_path = Path(args.dst)
    if not dest_path.exists():
        dest_path.mkdir(parents=True, exist_ok=True)

    # Get preserve directory
    preserve_dir = get_preserve_dir(args, dest_path)

    # Get manifest path
    manifest_path = get_manifest_path(args, preserve_dir)

    # Get dazzlelink directory
    dazzlelink_dir = get_dazzlelink_dir(args, preserve_dir) if HAVE_DAZZLELINK else None

    # Get path style and source base
    path_style = get_path_style(args)
    include_base = args.includeBase if hasattr(args, 'includeBase') else False

    # Get hash algorithms
    hash_algorithms = get_hash_algorithms(args)

    # Get link creation option
    create_link = getattr(args, 'create_link', None)
    link_force = getattr(args, 'link_force', False)

    # Parse --ignore flag for safety check options
    ignore_checks = []
    if hasattr(args, 'ignore') and args.ignore:
        ignore_checks = [x.strip().lower() for x in args.ignore.split(',')]

    # Define prompt callback for soft warnings (interactive mode)
    def prompt_on_warning(issues):
        """Prompt user to continue on soft warnings. Returns True to continue."""
        import sys
        if not sys.stdin.isatty():
            # Non-interactive mode - don't continue without explicit --ignore
            return False
        print("\nWARNING: The following issues were detected:")
        for issue in issues:
            print(f"  - {issue}")
        print("")
        try:
            response = input("Continue anyway? [y/N]: ").strip().lower()
            return response in ('y', 'yes')
        except (EOFError, KeyboardInterrupt):
            return False

    # Prepare operation options
    options = {
        'path_style': path_style,
        'include_base': include_base,
        'source_base': args.srchPath[0] if args.srchPath else None,
        'overwrite': args.overwrite if hasattr(args, 'overwrite') else False,
        'preserve_attrs': not args.no_preserve_attrs if hasattr(args, 'no_preserve_attrs') else True,
        'verify': not args.no_verify if hasattr(args, 'no_verify') else True,
        'hash_algorithm': hash_algorithms[0],  # Use first algorithm for primary verification
        'create_dazzlelinks': args.dazzlelink if hasattr(args, 'dazzlelink') else False,
        'dazzlelink_dir': dazzlelink_dir,
        'dazzlelink_mode': args.dazzlelink_mode if hasattr(args, 'dazzlelink_mode') else 'info',
        'dry_run': args.dry_run if hasattr(args, 'dry_run') else False,
        'force': args.force if hasattr(args, 'force') else False,
        'create_link': create_link,
        'ignore_space_warning': 'space' in ignore_checks,
        'check_permissions': 'permissions' not in ignore_checks,
        'prompt_on_warning': prompt_on_warning,
    }

    # Create command line for logging
    command_line = f"preserve MOVE {' '.join(sys.argv[2:])}"

    # Perform move operation
    try:
        result = operations.move_operation(
            source_files=source_files,
            dest_base=dest_path,
            manifest_path=manifest_path,
            options=options,
            command_line=command_line
        )
    except InsufficientSpaceError as e:
        print("")
        print("=" * 60)
        print("ERROR: Insufficient disk space")
        print("=" * 60)
        print(f"  Destination: {e.destination}")
        print(f"  Required:    {e.required:,} bytes ({e.required / (1024**3):.2f} GB)")
        print(f"  Available:   {e.available:,} bytes ({e.available / (1024**3):.2f} GB)")
        print(f"  Shortfall:   {(e.required - e.available):,} bytes")
        print("")
        print("No files were moved. Free up space or use a different destination.")
        print("=" * 60)
        return 1
    except PermissionCheckError as e:
        print("")
        print("=" * 60)
        print("ERROR: Permission denied")
        print("=" * 60)
        print(f"  Operation: {e.operation}")
        print(f"  Path:      {e.path}")
        print(f"  Details:   {e.details}")
        print("")
        if e.is_admin_required:
            print("This operation may require administrator privileges.")
            print("Try running as Administrator.")
        else:
            print("Check file/folder permissions and try again.")
        print("")
        print("No files were moved. Resolve permission issues first.")
        print("=" * 60)
        return 1

    # Print summary
    print("\nMOVE Operation Summary:")
    print(f"  Total files: {result.total_count()}")
    print(f"  Succeeded: {result.success_count()}")
    print(f"  Failed: {result.failure_count()}")
    print(f"  Skipped: {result.skip_count()}")

    if options['verify']:
        print(f"  Verified: {result.verified_count()}")
        print(f"  Unverified: {result.unverified_count()}")

    print(f"  Total bytes: {format_bytes_detailed(result.total_bytes)}")

    # Determine if move was successful
    move_success = (result.failure_count() == 0 and
                   (not options['verify'] or result.unverified_count() == 0))

    # Handle link creation after successful move
    link_result = None
    if create_link and move_success:
        # Determine the source directory that was moved
        # For directory moves, this is the common parent of all source files
        if args.sources:
            source_base_path = Path(args.sources[0])
            if source_base_path.is_file():
                source_base_path = source_base_path.parent
        else:
            # Find common parent from source files
            if source_files:
                source_base_path = Path(source_files[0]).parent
            else:
                source_base_path = None

        if source_base_path:
            # Determine the destination path (where the link should point to)
            # This must match the path construction logic in operations.py
            if path_style == 'absolute':
                # In absolute mode, full path is recreated under destination
                if sys.platform == 'win32':
                    drive, path_part = os.path.splitdrive(str(source_base_path))
                    drive = drive.rstrip(':')  # Remove colon from drive letter
                    target_path = dest_path / drive / path_part.lstrip('\\/')
                else:
                    # Unix: use root-relative path
                    target_path = dest_path / str(source_base_path).lstrip('/')
            elif path_style == 'flat':
                # Flat mode: warn that links don't make sense
                logger.warning("Link creation with --flat mode is not recommended - "
                             "directory structure is lost")
                target_path = dest_path
            else:
                # Relative mode
                if include_base:
                    target_path = dest_path / source_base_path.name
                else:
                    target_path = dest_path

            link_path = source_base_path

            # Check if source is now empty or link_force is set
            source_is_empty = (not link_path.exists() or
                              (link_path.is_dir() and not any(link_path.iterdir())))

            if source_is_empty or link_force:
                if options['dry_run']:
                    print(f"\n[DRY RUN] Would create {create_link} link:")
                    print(f"  {link_path} -> {target_path}")
                else:
                    print(f"\nCreating {create_link} link...")
                    print(f"  {link_path} -> {target_path}")

                    success, actual_type, error = links.create_link(
                        link_path=link_path,
                        target_path=target_path,
                        link_type=create_link,
                        is_directory=True
                    )

                    if success:
                        print(f"  Link created successfully ({actual_type})")
                        link_result = {
                            'type': actual_type,
                            'link_path': str(link_path),
                            'target_path': str(target_path),
                            'created_at': datetime.datetime.now().isoformat(),
                            'verified': True
                        }

                        # Update manifest with link_result
                        try:
                            from preservelib.manifest import PreserveManifest
                            manifest = PreserveManifest(manifest_path)
                            # Add link_result to the last operation
                            ops = manifest.manifest.get('operations', [])
                            if ops:
                                ops[-1]['link_result'] = link_result
                                manifest.save()
                                logger.info(f"Updated manifest with link_result")
                        except Exception as e:
                            logger.warning(f"Could not update manifest with link_result: {e}")
                    else:
                        print(f"  ERROR: Failed to create link: {error}")
                        logger.error(f"Link creation failed: {error}")
            else:
                print(f"\nWARNING: Cannot create link - source directory not empty: {link_path}")
                print("  Use --link-force to create link anyway")
                logger.warning(f"Source directory not empty, skipping link creation: {link_path}")

    # Return success if no failures and (no verification or all verified)
    return 0 if move_success else 1