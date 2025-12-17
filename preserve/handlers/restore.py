"""
RESTORE operation handler for preserve tool.

This module implements the RESTORE command which restores preserved files
back to their original locations based on the manifest.

TODO: Future refactoring opportunities:
- Extract manifest selection logic into a reusable component
- Create a common verification module for pre-restore checks
- The three-way verification logic could be shared with verify handler
- Consider creating a ManifestSelector class for manifest discovery
"""

import os
import sys
import logging
from pathlib import Path

from preservelib import operations
from preservelib import links
from preservelib.manifest import PreserveManifest, find_available_manifests
from preserve.utils import get_hash_algorithms, get_effective_verbosity
from preserve.output import configure_formatter, VerbosityLevel

logger = logging.getLogger(__name__)


def handle_restore_operation(args, logger):
    """Handle RESTORE operation with support for multiple manifests"""

    # Get unified verbosity level
    verbosity = get_effective_verbosity(args)

    formatter = configure_formatter(
        verbosity=verbosity,
        use_color=not (hasattr(args, 'no_color') and args.no_color),
        use_unicode=True
    )

    # Only log at verbose levels
    if verbosity >= VerbosityLevel.VERBOSE:
        logger.info("Starting RESTORE operation")
    logger.debug(f"[DEBUG] RESTORE called with args: {args}")

    # Get source path
    source_path = Path(args.src)
    if not source_path.exists():
        logger.error(f"Source directory does not exist: {source_path}")
        return 1

    # Warning about hardcoded paths in the code
    source_name = source_path.name
    if source_name != 'dst2' and 'dst2' in str(source_path):
        print(f"\nNOTE: You're running RESTORE on directory '{source_name}', but the code might have some ")
        print(f"references to 'dst2'. If you encounter issues, please report this.")

    # Handle --list option to show available manifests
    if hasattr(args, 'list') and args.list:
        manifests = find_available_manifests(source_path)
        if not manifests:
            print("No manifests found in source directory")
            return 1

        print("Available restore points:")
        for num, path, desc in manifests:
            try:
                # Load manifest to get metadata
                test_man = PreserveManifest(path)
                created = test_man.manifest.get('created_at', 'Unknown')
                file_count = len(test_man.manifest.get('files', {}))

                if num == 0:
                    print(f"  [Single] {path.name} ({created}, {file_count} files)")
                else:
                    desc_str = f" - {desc}" if desc else ""
                    print(f"  {num}. {path.name}{desc_str} ({created}, {file_count} files)")
            except Exception as e:
                logger.debug(f"Could not read manifest {path}: {e}")
                if num == 0:
                    print(f"  [Single] {path.name} (unreadable)")
                else:
                    print(f"  {num}. {path.name} (unreadable)")

        print("\nUse --number N or -n N to restore from a specific operation")
        print("Use --manifest FILENAME to specify a manifest file directly")
        return 0

    # Select manifest based on user options
    manifest_path = None

    if args.manifest:
        # User specified manifest directly
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            # Try relative to source directory
            test_path = source_path / args.manifest
            if test_path.exists():
                manifest_path = test_path
    elif hasattr(args, 'number') and args.number:
        # User specified by number
        manifests = find_available_manifests(source_path)
        for num, path, desc in manifests:
            if num == args.number:
                manifest_path = path
                if verbosity >= VerbosityLevel.VERBOSE:
                    logger.info(f"Selected manifest #{num}: {path.name}")
                break
        else:
            logger.error(f"No manifest found with number {args.number}")
            return 1
    else:
        # Default: use the latest (highest numbered) manifest
        manifests = find_available_manifests(source_path)
        if manifests:
            # Take the last one (highest number)
            manifest_path = manifests[-1][1]
            if verbosity >= VerbosityLevel.VERBOSE:
                logger.info(f"Using latest manifest: {manifest_path.name}")
        else:
            # Fall back to old logic for compatibility
            potential_manifests = [
                source_path / '.preserve' / 'manifest.json',
                source_path / '.preserve' / 'preserve_manifest.json',
                source_path / 'preserve_manifest.json'
            ]

            for path in potential_manifests:
                if path.exists():
                    manifest_path = path
                    break

    # Check for manifest
    if manifest_path and manifest_path.exists():
        try:
            # Just verify the manifest exists and is valid
            test_man = PreserveManifest(manifest_path)
            if verbosity >= VerbosityLevel.VERBOSE:
                logger.info(f"Found valid manifest at {manifest_path}")
        except Exception as e:
            logger.warning(f"Found manifest at {manifest_path}, but it is invalid: {e}")
            manifest_path = None

    # Determine dazzlelink usage
    use_dazzlelinks = True  # Default is to use dazzlelinks if no manifest
    if args.no_dazzlelinks:
        use_dazzlelinks = False
    elif args.use_dazzlelinks:
        use_dazzlelinks = True

    # If no manifest and dazzlelinks disabled, report error
    if not manifest_path and not use_dazzlelinks:
        logger.error("No manifest found and dazzlelink usage is disabled")
        logger.error("Use --use-dazzlelinks to enable restoration from dazzlelinks")
        return 1

    # Get hash algorithms
    hash_algorithms = get_hash_algorithms(args)

    # Prepare operation options
    options = {
        'overwrite': args.overwrite if hasattr(args, 'overwrite') else False,
        'preserve_attrs': True,
        'verify': True,
        'hash_algorithm': hash_algorithms[0],
        'dry_run': args.dry_run if hasattr(args, 'dry_run') else False,
        'force': args.force if hasattr(args, 'force') else False,
        'use_dazzlelinks': use_dazzlelinks,
        'destination_override': args.dst if hasattr(args, 'dst') and args.dst else None,
        'formatter': formatter  # Pass the formatter to operations
    }

    logger.debug(f"[DEBUG] RESTORE options: {options}")

    # Create command line for logging
    command_line = f"preserve RESTORE {' '.join(sys.argv[2:])}"

    # Perform three-way verification if requested
    if hasattr(args, 'verify') and args.verify and manifest_path:
        if verbosity >= VerbosityLevel.VERBOSE:
            logger.info("Performing three-way verification before restoration...")

        # Load the manifest
        try:
            manifest = PreserveManifest(manifest_path)

            # Get source directory from manifest's first file
            files = manifest.manifest.get('files', {})
            if files:
                # Try to determine source directory from manifest entries
                first_file_info = next(iter(files.values()))
                source_orig_path = first_file_info.get('source_path', '')
                if source_orig_path:
                    source_orig = Path(source_orig_path)
                    # Try to find common parent of source files
                    if source_orig.is_absolute():
                        # For absolute paths, we need to find the actual source
                        if verbosity >= VerbosityLevel.VERBOSE:
                            logger.info(f"Source path from manifest: {source_orig}")
                        # Check if parent directories exist
                        possible_source = source_orig.parent
                        while not possible_source.exists() and possible_source.parent != possible_source:
                            possible_source = possible_source.parent
                        if possible_source.exists():
                            source_base = possible_source
                        else:
                            # Can't find source, skip three-way verification
                            logger.warning("Cannot determine source directory for three-way verification")
                            source_base = None
                    else:
                        # For relative paths, assume current directory
                        source_base = Path.cwd()
                else:
                    source_base = None
            else:
                source_base = None

            if source_base:
                from preservelib.verification import verify_three_way

                verification_result = verify_three_way(
                    source_path=source_base,
                    preserved_path=source_path,
                    manifest=manifest,
                    hash_algorithms=[options['hash_algorithm']]
                )

                # Report verification results
                print("\nThree-way Verification Results:")
                print(f"  All match: {len(verification_result.all_match)}")
                print(f"  Source modified: {len(verification_result.source_modified)}")
                print(f"  Preserved corrupted: {len(verification_result.preserved_corrupted)}")
                print(f"  Errors: {len(verification_result.errors)}")
                print(f"  Not found: {len(verification_result.not_found)}")

                # Show details if there are issues
                if verification_result.source_modified:
                    print("\nFiles modified in source since preservation:")
                    for result in verification_result.source_modified[:5]:
                        print(f"  - {result.file_path}")
                    if len(verification_result.source_modified) > 5:
                        print(f"  ... and {len(verification_result.source_modified) - 5} more")

                if verification_result.preserved_corrupted:
                    print("\nCorrupted preserved files:")
                    for result in verification_result.preserved_corrupted[:5]:
                        print(f"  - {result.file_path}")
                    if len(verification_result.preserved_corrupted) > 5:
                        print(f"  ... and {len(verification_result.preserved_corrupted) - 5} more")

                # Ask for confirmation if issues found
                if not verification_result.is_successful and not options['force']:
                    print("\nVerification found issues. Continue with restoration anyway? (use --force to skip this prompt)")
                    response = input("Continue? [y/N]: ").strip().lower()
                    if response != 'y':
                        print("Restoration cancelled.")
                        return 1
            else:
                logger.warning("Cannot perform three-way verification: source directory unknown")
                print("\nWarning: Three-way verification skipped (source directory not found)")

        except Exception as e:
            logger.warning(f"Could not perform three-way verification: {e}")
            print(f"\nWarning: Three-way verification failed: {e}")

    # Check for links at source locations that need to be removed before restore
    if manifest_path:
        try:
            manifest_for_links = PreserveManifest(manifest_path)
            link_info = links.check_for_links_at_sources(manifest_for_links, source_path)

            if link_info['has_links']:
                print("\n" + "="*60)
                print("LINKS DETECTED AT RESTORE DESTINATION")
                print("="*60)

                for link_data in link_info['links']:
                    link_type = link_data.get('type', 'unknown')
                    link_path = link_data.get('path', 'unknown')
                    target = link_data.get('target', 'unknown')
                    tracked = link_data.get('tracked', False)

                    print(f"\n  Type:    {link_type}")
                    print(f"  Path:    {link_path}")
                    print(f"  Target:  {target}")
                    if tracked:
                        print(f"  Status:  Tracked (created by preserve)")
                    else:
                        print(f"  Status:  UNTRACKED - may have been created manually")

                print("\n" + "-"*60)
                print("These links must be removed before files can be restored.")
                print("Removing a link does NOT delete the target content.")
                print("-"*60)

                if not options['force'] and not options['dry_run']:
                    response = input("\nRemove links and proceed with restore? [y/N]: ").strip().lower()
                    if response != 'y':
                        print("Restore cancelled.")
                        return 1

                # Remove the links
                for link_data in link_info['links']:
                    link_path = link_data.get('path')
                    if link_path:
                        if options['dry_run']:
                            print(f"\n[DRY RUN] Would remove link: {link_path}")
                        else:
                            print(f"\nRemoving link: {link_path}")
                            success, error = links.remove_link(link_path)
                            if success:
                                print(f"  Link removed successfully")
                            else:
                                print(f"  ERROR: Failed to remove link: {error}")
                                if not options['force']:
                                    print("  Use --force to continue anyway")
                                    return 1

        except Exception as e:
            logger.warning(f"Error checking for links: {e}")
            if verbosity >= VerbosityLevel.VERBOSE:
                print(f"\nWarning: Could not check for links at restore destination: {e}")

    # Perform restoration
    result = operations.restore_operation(
        source_directory=source_path,
        manifest_path=manifest_path,
        options=options,
        command_line=command_line
    )

    # Print summary using formatter
    summary = formatter.format_summary("RESTORE")
    if summary:
        print(summary)

    # Print detailed skipped file info only if verbose enough
    # In quiet mode or normal mode, don't show the detailed list
    if verbosity >= VerbosityLevel.VERBOSE and result.skip_count() > 0:
        # At -v, show just a few examples
        # At -vv or higher, show more details
        max_to_show = 3 if verbosity == VerbosityLevel.VERBOSE else 10

        print(f"\nSkipped Files (first {max_to_show}):")
        skip_count = 0
        for source, dest in result.skipped:
            reason = result.error_messages.get(source, "Unknown reason")

            # At -v, just show the file and reason
            if verbosity == VerbosityLevel.VERBOSE:
                print(f"  {os.path.basename(dest)}: {reason}")
            else:
                # At -vv or higher, show full details
                source_exists = Path(source).exists()
                print(f"  {source} -> {dest}")
                print(f"    Reason: {reason}")
                print(f"    Source exists: {source_exists}")
                if not source_exists and verbosity >= VerbosityLevel.DETAILED:
                    # Only show file search at -vv or higher
                    source_dir = Path(args.src)
                    filename = Path(source).name
                    matching_files = list(source_dir.glob(f"**/{filename}"))
                    if matching_files:
                        print(f"    Found similar files:")
                        for i, match in enumerate(matching_files[:3]):
                            print(f"      {match}")
                        if len(matching_files) > 3:
                            print(f"      ... and {len(matching_files) - 3} more")
                    else:
                        print(f"    No similar files found")
                print("")

            skip_count += 1
            if skip_count >= max_to_show:
                if result.skip_count() > max_to_show:
                    print(f"  ... and {result.skip_count() - max_to_show} more")
                break

    # Show verification counts only if verify was enabled and not in quiet mode
    if options['verify'] and verbosity > VerbosityLevel.QUIET:
        print(f"  Verified: {result.verified_count()}")
        print(f"  Unverified: {result.unverified_count()}")

    # Return success if no failures and (no verification or all verified)
    return 0 if (result.failure_count() == 0 and
                (not options['verify'] or result.unverified_count() == 0)) else 1