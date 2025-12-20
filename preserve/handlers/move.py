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
from preservelib.links import (
    LinkHandlingMode,
    LinkAction,
    analyze_link,
    decide_link_action,
    remove_link,
)
from preservelib.operations import (
    InsufficientSpaceError,
    PermissionCheckError,
    detect_path_cycles_deep,
)
from preservelib.destination import (
    scan_destination,
    format_scan_report,
    ConflictResolution,
)
from preservelib.path_warnings import (
    check_path_mode_warnings,
    prompt_path_warning,
)
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

    # Parse link handling mode from CLI argument
    link_handling_str = getattr(args, 'link_handling', 'block')
    try:
        link_handling_mode = LinkHandlingMode.from_string(link_handling_str)
    except ValueError as e:
        logger.error(str(e))
        return 1

    # Track links for handling (skip/unlink)
    links_to_skip = []  # Links whose directories should be excluded from traversal
    links_to_unlink = []  # Links to remove after successful move

    # CRITICAL: Early cycle detection on original source paths (before file expansion)
    # This catches nested junctions/symlinks that would cause catastrophic data loss
    # The detection must happen BEFORE os.walk expands directories (which follows links)
    if args.sources:
        can_proceed, cycle_hard, cycle_soft, link_report = detect_path_cycles_deep(
            args.sources, str(dest_path), "MOVE"
        )

        if link_report:
            logger.info(f"Found {len(link_report)} link(s) in source tree")
            for link_info_dict in link_report:
                link_type = link_info_dict.get('link_type', 'unknown')
                link_path = link_info_dict.get('link_path', 'unknown')
                target = link_info_dict.get('target_resolved') or link_info_dict.get('target', 'unknown')
                logger.debug(f"  {link_type}: {link_path} -> {target}")

        # Handle links based on link_handling_mode
        if not can_proceed:
            if link_handling_mode == LinkHandlingMode.BLOCK:
                # Default behavior: block the operation
                logger.error("")
                logger.error("=" * 70)
                logger.error("CRITICAL: Cycle detected - MOVE operation BLOCKED")
                logger.error("=" * 70)
                for issue in cycle_hard:
                    logger.error(f"  {issue}")
                logger.error("")
                logger.error("A MOVE in this configuration would cause CATASTROPHIC DATA LOSS.")
                logger.error("The source contains links that resolve to the destination.")
                logger.error("")
                logger.error("Options:")
                logger.error("  1. Remove the problematic junction/symlink from source")
                logger.error("  2. Use COPY instead (data preserved, but check for duplicates)")
                logger.error("  3. Move the destination to a different location")
                logger.error("  4. Use --link-handling skip to skip links")
                logger.error("  5. Use --link-handling unlink to remove links after move")
                logger.error("=" * 70)
                return 1

            elif link_handling_mode == LinkHandlingMode.SKIP:
                # Skip mode: exclude links from traversal
                logger.warning("")
                logger.warning("=" * 70)
                logger.warning("LINK HANDLING: skip mode - problematic links will be skipped")
                logger.warning("=" * 70)
                for link_info_dict in link_report:
                    if link_info_dict.get('creates_cycle'):
                        link_path = link_info_dict.get('link_path')
                        links_to_skip.append(link_path)
                        logger.warning(f"  SKIP: {link_path}")
                logger.warning("")
                logger.warning(f"Skipping {len(links_to_skip)} link(s), moving everything else.")
                logger.warning("=" * 70)

            elif link_handling_mode == LinkHandlingMode.UNLINK:
                # Unlink mode: remove links pointing to destination after move
                logger.warning("")
                logger.warning("=" * 70)
                logger.warning("LINK HANDLING: unlink mode - links will be removed after move")
                logger.warning("=" * 70)
                for link_info_dict in link_report:
                    if link_info_dict.get('creates_cycle'):
                        link_path = link_info_dict.get('link_path')
                        links_to_skip.append(link_path)  # Also skip during traversal
                        links_to_unlink.append(link_path)  # Mark for removal
                        logger.warning(f"  UNLINK: {link_path}")
                logger.warning("")
                logger.warning(f"Will unlink {len(links_to_unlink)} link(s) after successful move.")
                logger.warning("=" * 70)

            elif link_handling_mode == LinkHandlingMode.RECREATE:
                # Phase 2 - not yet implemented
                logger.error("Link handling mode 'recreate' is not yet implemented.")
                logger.error("Use 'skip' or 'unlink' for now. See issue #48 for progress.")
                return 1

            elif link_handling_mode == LinkHandlingMode.ASK:
                # Phase 2 - not yet implemented
                logger.error("Link handling mode 'ask' is not yet implemented.")
                logger.error("Use 'skip' or 'unlink' for now. See issue #48 for progress.")
                return 1

        if cycle_soft:
            for issue in cycle_soft:
                logger.warning(issue)

    # Filter out files that are inside links_to_skip directories
    if links_to_skip:
        original_count = len(source_files)
        filtered_files = []
        for file_path in source_files:
            skip_this_file = False
            for skip_link in links_to_skip:
                skip_link_path = Path(skip_link)
                try:
                    # Check if file is inside the skip link directory
                    if Path(file_path).is_relative_to(skip_link_path):
                        skip_this_file = True
                        break
                except (ValueError, TypeError):
                    # is_relative_to raises ValueError if not relative
                    pass
            if not skip_this_file:
                filtered_files.append(file_path)

        source_files = filtered_files
        skipped_count = original_count - len(source_files)
        if skipped_count > 0:
            logger.info(f"Filtered out {skipped_count} file(s) inside skipped links")

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

    # Check for path mode warnings (Issue #42)
    skip_path_warning = getattr(args, 'no_path_warning', False)
    if not skip_path_warning and args.sources:
        # Use first source for warning detection
        source_for_check = args.sources[0]
        warnings = check_path_mode_warnings(
            source_path=source_for_check,
            dest_path=str(dest_path),
            path_style=path_style,
            include_base=include_base,
        )
        for warning in warnings:
            should_continue, _ = prompt_path_warning(warning, source_for_check)
            if not should_continue:
                return 1

    # Handle --scan-only mode (0.7.x destination awareness)
    scan_only = getattr(args, 'scan_only', False)
    scan_verbose = getattr(args, 'scan_verbose', False)

    # Determine source_base for directory operations
    source_base = None
    if args.srchPath:
        source_base = args.srchPath[0]
    elif args.sources and len(args.sources) == 1:
        src_path = Path(args.sources[0])
        if src_path.is_dir() and args.recursive:
            source_base = str(src_path)

    if scan_only or dest_path.exists():
        # Perform destination scan for awareness
        logger.info("Scanning destination for existing files...")

        scan_result = scan_destination(
            source_files=source_files,
            dest_base=dest_path,
            path_style=path_style,
            source_base=source_base,
            include_base=include_base,
            hash_algorithm=hash_algorithms[0],
            quick_check=True,
            scan_extra_dest_files=True,
        )

        if scan_only:
            # Just print the report and exit
            print(format_scan_report(scan_result, verbose=scan_verbose or args.verbose > 0))

            # Provide guidance based on results
            if scan_result.has_conflicts():
                print("")
                print("To proceed with conflicts, use one of:")
                print("  --on-conflict=skip      Keep destination files (skip conflicting)")
                print("  --on-conflict=overwrite Replace with source files")
                print("  --on-conflict=newer     Keep whichever is newer")
                print("  --on-conflict=rename    Keep both (rename source)")
            if scan_result.identical_count > 0:
                print("")
                print("To skip identical files and save time:")
                print("  --incorporate-identical  Skip moving, add to manifest only")

            return 0

        # Log scan results for non-scan-only mode
        if scan_result.has_pre_existing():
            logger.info(f"Destination scan: {scan_result.identical_count} identical, "
                       f"{scan_result.conflict_count} conflicts, "
                       f"{scan_result.dest_only_count} pre-existing")

    # Get incorporate_identical flag (0.7.x)
    incorporate_identical = getattr(args, 'incorporate_identical', False)

    # Get on_conflict flag (0.7.x)
    on_conflict = getattr(args, 'on_conflict', None)

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
        'source_base': source_base,
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
        # 0.7.x Destination awareness options
        'incorporate_identical': incorporate_identical,
        'scan_result': scan_result if 'scan_result' in locals() else None,
        'on_conflict': on_conflict,
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

    # Print summary with clear explanation of MOVE process
    print("\n" + "=" * 60)
    print("MOVE Operation Summary")
    print("=" * 60)

    # Get counts from result tracking
    moved_count = len(getattr(result, 'moved_sources', []))
    retained_count = len(getattr(result, 'retained_sources', []))
    delete_errors = getattr(result, 'delete_errors', {})

    # Show file counts
    print(f"  Files processed:  {result.total_count()}")
    print(f"  Copy failed:      {result.failure_count()}")
    print(f"  Skipped:          {result.skip_count()}")

    # Print incorporated files count (0.7.x)
    if result.incorporated_count() > 0:
        print(f"  Incorporated:     {result.incorporated_count()} (identical, not moved)")

    if options['verify']:
        print(f"  Verified:         {result.verified_count()}")

    # Show move-specific results (only for non-dry-run)
    if not options['dry_run']:
        print("")
        print(f"  Successfully MOVED (source deleted):     {moved_count}")
        print(f"  COPIED ONLY (source file retained):      {retained_count}")

    print(f"\n  Total bytes: {format_bytes_detailed(result.total_bytes)}")
    if result.incorporated_bytes > 0:
        print(f"  Bytes incorporated: {format_bytes_detailed(result.incorporated_bytes)}")

    # Determine if move was successful
    move_success = (result.failure_count() == 0 and
                   (not options['verify'] or result.unverified_count() == 0) and
                   retained_count == 0)

    # Provide clear guidance based on outcome
    if options['dry_run']:
        print("\n[DRY RUN] No files were actually moved.")
        print("Remove --dry-run to perform the operation.")
    elif move_success and moved_count > 0:
        print("\nSUCCESS: All files moved. Source files have been deleted.")
    elif retained_count > 0:
        # Partial success - some files copied but sources retained
        print("\n" + "=" * 60)
        print("WARNING: Some source files were NOT deleted")
        print("=" * 60)
        print("")
        print("How MOVE works: Files are COPIED first, then VERIFIED, then")
        print("source files are DELETED only after successful verification.")
        print("")
        print("Your source files are SAFE - nothing was lost.")
        print(f"  - {moved_count} file(s) fully moved (source deleted)")
        print(f"  - {retained_count} file(s) copied but source retained")

        # Show reasons for retention
        verification_skipped = sum(1 for _, _, reason in getattr(result, 'retained_sources', [])
                                   if reason == "verification_skipped")
        delete_failed = sum(1 for _, _, reason in getattr(result, 'retained_sources', [])
                           if reason == "delete_failed")

        if verification_skipped > 0:
            print(f"\n  Verification skipped: {verification_skipped} file(s)")
            print("    These files copied but couldn't be verified.")
            print("    Sources retained for safety.")

        if delete_failed > 0:
            print(f"\n  Delete failed: {delete_failed} file(s)")
            print("    These files copied and verified successfully,")
            print("    but source deletion failed (likely permissions).")

            # Show specific errors if few enough
            if len(delete_errors) <= 3:
                for src, err in delete_errors.items():
                    print(f"      {src}: {err}")

        # Provide actionable guidance
        print("\n" + "-" * 60)
        print("TO COMPLETE THE MOVE:")
        print("-" * 60)
        if delete_failed > 0:
            print("  Option 1: Fix permissions and re-run with --force")
            print(f"    preserve MOVE [same args] --force")
            print("")
            if sys.platform == 'win32':
                print("  Option 2: Run as Administrator")
                print("    Right-click Command Prompt, select 'Run as administrator'")
            else:
                print("  Option 2: Run with sudo")
                print("    sudo preserve MOVE [same args] --force")
        elif verification_skipped > 0:
            print("  Re-run with --force to delete sources without re-verifying:")
            print(f"    preserve MOVE [same args] --force")
            print("")
            print("  Or manually verify files match, then delete sources.")

        print("\n" + "-" * 60)
        print("TO UNDO (delete destination copies, keep sources):")
        print("-" * 60)
        print("  If you want to abort and free destination space:")
        print(f"    preserve RESTORE --src \"{dest_path}\" --dry-run  # Preview first")
        print(f"    # Then manually delete the destination directory")
        print("  Your source files remain untouched.")

    elif result.failure_count() > 0:
        # Copy failures
        print("\n" + "=" * 60)
        print("ERROR: MOVE FAILED - Some files could not be copied")
        print("=" * 60)
        print("")
        print("Your source files are SAFE - nothing was deleted.")
        print(f"  - {result.failure_count()} file(s) failed to copy")
        print(f"  - {moved_count} file(s) successfully moved")
        print("")
        print("Check the errors above and resolve the issues, then re-run.")

    print("=" * 60)

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

    # Handle links_to_unlink after successful move (--link-handling unlink)
    if links_to_unlink and move_success and not options['dry_run']:
        print("")
        print("=" * 60)
        print("UNLINK: Removing links that pointed to destination")
        print("=" * 60)

        unlink_success = 0
        unlink_failed = 0

        for link_path_str in links_to_unlink:
            link_path = Path(link_path_str)
            if links.is_link(link_path):
                success, error = remove_link(link_path)
                if success:
                    print(f"  Unlinked: {link_path}")
                    unlink_success += 1
                else:
                    print(f"  FAILED to unlink {link_path}: {error}")
                    logger.error(f"Failed to unlink {link_path}: {error}")
                    unlink_failed += 1
            else:
                # Link no longer exists or isn't a link
                logger.debug(f"Link already removed or not a link: {link_path}")

        print("")
        print(f"  Unlinked: {unlink_success}, Failed: {unlink_failed}")
        print("=" * 60)

    elif links_to_unlink and options['dry_run']:
        print("")
        print("[DRY RUN] Would unlink the following links:")
        for link_path_str in links_to_unlink:
            print(f"  {link_path_str}")

    # Return success if no failures and (no verification or all verified)
    return 0 if move_success else 1