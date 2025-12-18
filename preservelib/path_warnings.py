"""
Path mode warning detection for preserve tool.

This module implements detection of common path mode mistakes:
1. Using --abs with a destination that already contains source path components
2. Using --rel without --includeBase when source directory name matters

Issue #42 - Smart path mode detection
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Tuple, NamedTuple
from dataclasses import dataclass, field


@dataclass
class PathWarning:
    """Represents a detected path mode warning."""
    warning_type: str  # "abs_overlap", "rel_no_includebase"
    message: str
    expected_result: str  # What will actually happen
    suggestions: List[Tuple[str, str]] = field(default_factory=list)  # [(command_change, result), ...]


def normalize_path_for_comparison(path: str) -> List[str]:
    """Normalize a path to a list of components for comparison.

    Handles:
    - Windows/Unix path separators
    - Case-insensitive comparison on Windows
    - Drive letter normalization
    """
    # Convert to Path and get parts
    p = Path(path)
    parts = list(p.parts)

    # Normalize case on Windows
    if sys.platform == 'win32':
        parts = [part.lower() for part in parts]
        # Remove trailing colon and backslash from drive letter (e.g., "C:\\" -> "c")
        if parts and (parts[0].endswith(':') or parts[0].endswith(':\\')):
            parts[0] = parts[0].rstrip(':\\')

    # Remove empty parts and standalone separators
    parts = [p for p in parts if p and p not in ('/', '\\', '')]

    return parts


def find_path_overlap(source_parts: List[str], dest_parts: List[str]) -> int:
    """Find how many trailing components of dest match leading components of source.

    Returns the number of overlapping components.

    Example:
        source: ['c', 'users', 'extreme', '.cache', 'huggingface', 'hub']
        dest:   ['e', 'c', 'users', 'extreme', '.cache', 'huggingface']

        dest ends with: ['c', 'users', 'extreme', '.cache', 'huggingface']
        source starts with: ['c', 'users', 'extreme', '.cache', 'huggingface', 'hub']
        overlap = 5 components
    """
    if not source_parts or not dest_parts:
        return 0

    max_overlap = min(len(source_parts), len(dest_parts))

    for overlap_len in range(max_overlap, 0, -1):
        # Check if the last overlap_len parts of dest match the first overlap_len parts of source
        dest_suffix = dest_parts[-overlap_len:]
        source_prefix = source_parts[:overlap_len]

        if dest_suffix == source_prefix:
            return overlap_len

    return 0


def detect_abs_path_overlap(
    source_path: str,
    dest_path: str,
    threshold: int = 2
) -> Optional[PathWarning]:
    """Detect if using --abs will duplicate path structure.

    Args:
        source_path: The source file/directory path
        dest_path: The destination base path
        threshold: Minimum overlap components to trigger warning (default 2)

    Returns:
        PathWarning if overlap detected, None otherwise
    """
    source_parts = normalize_path_for_comparison(source_path)
    dest_parts = normalize_path_for_comparison(dest_path)

    overlap = find_path_overlap(source_parts, dest_parts)

    if overlap < threshold:
        return None

    # Build the expected result path (what --abs will create)
    # With --abs, the full source path is appended to dest
    source_p = Path(source_path)
    dest_p = Path(dest_path)

    if sys.platform == 'win32':
        drive, path_part = os.path.splitdrive(str(source_p))
        drive = drive.rstrip(':')
        expected = dest_p / drive / path_part.lstrip('\\/')
    else:
        expected = dest_p / str(source_p).lstrip('/')

    # Build what user probably wanted (rel + includeBase)
    wanted = dest_p / source_p.name

    # Build the warning
    overlap_parts = source_parts[:overlap]
    overlap_str = '/'.join(overlap_parts)

    message = (
        f"Destination path contains {overlap} components that overlap with source path:\n"
        f"  Overlapping: {overlap_str}\n\n"
        f"Using --abs will duplicate this structure."
    )

    suggestions = [
        (
            f'--rel --includeBase --dst "{dest_path}"',
            str(wanted / "*") if source_p.is_dir() else str(wanted)
        ),
    ]

    # Suggest --abs with drive root if on Windows
    if sys.platform == 'win32':
        dest_drive = os.path.splitdrive(str(dest_p))[0]
        if dest_drive:
            alt_expected = Path(dest_drive) / drive / path_part.lstrip('\\/')
            suggestions.append(
                (
                    f'--abs --dst "{dest_drive}\\"',
                    str(alt_expected / "*") if source_p.is_dir() else str(alt_expected)
                )
            )

    return PathWarning(
        warning_type="abs_overlap",
        message=message,
        expected_result=str(expected / "*") if source_p.is_dir() else str(expected),
        suggestions=suggestions
    )


def detect_rel_no_includebase(
    source_path: str,
    include_base: bool
) -> Optional[PathWarning]:
    """Detect if using --rel without --includeBase might lose directory context.

    Args:
        source_path: The source directory path
        include_base: Whether --includeBase is specified

    Returns:
        PathWarning if likely mistake detected, None otherwise
    """
    source_p = Path(source_path)

    # Only warn for directories
    if not source_p.is_dir():
        return None

    # Only warn if includeBase is not set
    if include_base:
        return None

    # Check if the directory name seems meaningful
    # (not something generic like 'files' or 'data')
    dirname = source_p.name

    # Skip warning for very generic names that might intentionally be omitted
    generic_names = {'files', 'data', 'output', 'input', 'tmp', 'temp', '.'}
    if dirname.lower() in generic_names:
        return None

    message = (
        f"Using --rel without --includeBase will omit the '{dirname}' directory.\n"
        f"Source directory contents will go directly into destination."
    )

    return PathWarning(
        warning_type="rel_no_includebase",
        message=message,
        expected_result="<dst>/<contents> (no parent folder)",
        suggestions=[
            (
                '--rel --includeBase',
                f"<dst>/{dirname}/<contents>"
            )
        ]
    )


def check_path_mode_warnings(
    source_path: str,
    dest_path: str,
    path_style: str,
    include_base: bool = False,
) -> List[PathWarning]:
    """Check for all path mode warnings.

    Args:
        source_path: The source file/directory path
        dest_path: The destination base path
        path_style: One of 'absolute', 'relative', 'flat'
        include_base: Whether --includeBase is specified

    Returns:
        List of PathWarning objects (may be empty)
    """
    warnings = []

    if path_style == 'absolute':
        warning = detect_abs_path_overlap(source_path, dest_path)
        if warning:
            warnings.append(warning)

    elif path_style == 'relative':
        warning = detect_rel_no_includebase(source_path, include_base)
        if warning:
            warnings.append(warning)

    return warnings


def format_path_warning(warning: PathWarning, source_path: str = "") -> str:
    """Format a PathWarning for display to the user.

    Args:
        warning: The PathWarning to format
        source_path: Original source path for context

    Returns:
        Formatted warning string
    """
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append("PATH MODE WARNING")
    lines.append("=" * 60)
    lines.append("")
    lines.append(warning.message)
    lines.append("")
    lines.append("Expected result with current settings:")
    lines.append(f"  {warning.expected_result}")
    lines.append("")

    if warning.suggestions:
        lines.append("Did you mean one of these instead?")
        lines.append("")
        for i, (cmd_change, result) in enumerate(warning.suggestions, 1):
            lines.append(f"  [{i}] {cmd_change}")
            lines.append(f"      -> {result}")
            lines.append("")

    lines.append(f"  [{len(warning.suggestions) + 1}] Continue with current settings")
    lines.append(f"      -> {warning.expected_result}")
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def prompt_path_warning(
    warning: PathWarning,
    source_path: str = ""
) -> Tuple[bool, Optional[str]]:
    """Display warning and prompt user for choice.

    Args:
        warning: The PathWarning to display
        source_path: Original source path for context

    Returns:
        Tuple of (should_continue, suggested_command_change)
        - (True, None): Continue with current settings
        - (True, cmd_change): User chose a suggestion
        - (False, None): User aborted
    """
    import sys
    import os

    # rel_no_includebase is informational - show but don't block
    # abs_overlap is a likely error - block and require confirmation
    is_blocking = warning.warning_type == "abs_overlap"

    print(format_path_warning(warning, source_path))

    # Check if we're in a truly interactive terminal
    # isatty() can return True in subprocesses that still don't have real input
    is_interactive = sys.stdin.isatty()

    # On Windows, also check if stdin is connected to console
    if sys.platform == 'win32':
        try:
            import msvcrt
            # If stdin is not connected to a real console, select() won't work
            # We'll detect this by the environment
            if os.environ.get('PRESERVE_NON_INTERACTIVE'):
                is_interactive = False
        except ImportError:
            pass

    # Additional check: if running under subprocess without real terminal
    # the stdin might be TTY-like but has no data
    # We'll handle EOFError gracefully

    if not is_interactive:
        if is_blocking:
            # Non-interactive mode - don't continue without explicit flag
            print("Non-interactive mode: Use --no-path-warning to proceed.")
            return False, None
        else:
            # Informational warning - continue with a note
            print("(Continuing in non-interactive mode. Use --no-path-warning to suppress this message.)")
            return True, None

    num_choices = len(warning.suggestions) + 1
    valid_choices = [str(i) for i in range(1, num_choices + 1)]

    try:
        response = input(f"Choice [1-{num_choices}] or 'q' to quit: ").strip().lower()

        if response in ('q', 'quit', 'exit'):
            return False, None

        if response == str(num_choices):
            # Continue with current settings
            return True, None

        if response in valid_choices:
            idx = int(response) - 1
            if idx < len(warning.suggestions):
                cmd_change, _ = warning.suggestions[idx]
                print(f"\nSuggestion noted. Please re-run with: {cmd_change}")
                return False, cmd_change

        print("Invalid choice. Aborting.")
        return False, None

    except (EOFError, KeyboardInterrupt):
        # EOFError means no input available - treat as non-interactive
        if is_blocking:
            print("\nNo input available. Use --no-path-warning to proceed in non-interactive mode.")
            return False, None
        else:
            # Informational warning - continue
            print("\n(No input available. Continuing with current settings.)")
            return True, None
