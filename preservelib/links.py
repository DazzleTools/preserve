"""
Link operations for preserve.

This module provides cross-platform functionality for creating, detecting,
and managing filesystem links (junctions, symlinks, hard links) as part
of the preserve MOVE operation with link creation.

Supported link types:
- junction: Windows NTFS directory junction (no admin required)
- soft: Symbolic link (cross-platform, may need admin on Windows)
- hard: Hard link (cross-platform, same filesystem only, files only)
- auto: Platform-appropriate default (junction on Windows, soft elsewhere)

Link handling modes (for MOVE operations with existing links in source):
- block: (default) Block operation if cycle-creating links found
- skip: Skip links, only move non-link content
- unlink: Remove source links that point to destination (consolidation)
- recreate: Recreate links at destination with adjusted targets (Phase 2)
- ask: Interactive prompt for each link (Phase 2)
"""

import os
import sys
import logging
import subprocess
import ctypes
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Link type constants
LINK_TYPE_JUNCTION = 'junction'
LINK_TYPE_SOFT = 'soft'
LINK_TYPE_HARD = 'hard'
LINK_TYPE_AUTO = 'auto'
LINK_TYPE_DAZZLE = 'dazzle'  # Future: .dazzlelink metadata file

VALID_LINK_TYPES = [LINK_TYPE_JUNCTION, LINK_TYPE_SOFT, LINK_TYPE_HARD, LINK_TYPE_AUTO, LINK_TYPE_DAZZLE]


# ==============================================================================
# Link Handling Enums and Data Structures
# ==============================================================================


class LinkHandlingMode(Enum):
    """
    How to handle links discovered in the source tree during MOVE operations.

    Used with the --link-handling CLI flag to control behavior when links
    are found that would otherwise block the operation due to cycle detection.
    """
    BLOCK = "block"        # Default: block if cycle-creating links found
    SKIP = "skip"          # Skip links, only move non-link content
    UNLINK = "unlink"      # Remove source links that point to destination
    RECREATE = "recreate"  # Recreate links at destination (Phase 2)
    ASK = "ask"            # Interactive prompt for each link (Phase 2)

    @classmethod
    def from_string(cls, value: str) -> "LinkHandlingMode":
        """Convert string to LinkHandlingMode, with helpful error message."""
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"Invalid link handling mode: '{value}'. Valid modes: {valid}")


class LinkAction(Enum):
    """
    Action to take for a specific link during traversal.

    This is the per-link decision made based on LinkHandlingMode and link analysis.
    """
    FOLLOW = "follow"      # Follow the link (descend into it during traversal)
    SKIP = "skip"          # Skip this link entirely
    UNLINK = "unlink"      # Remove this link from source (consolidation)
    RECREATE = "recreate"  # Recreate this link at destination
    BLOCK = "block"        # Block the entire operation due to this link


@dataclass
class LinkInfo:
    """
    Information about a discovered link in the source tree.

    Captures all details needed to make handling decisions and report to user.
    """
    # Path to the link itself
    link_path: Path

    # Link type (junction, soft, hard)
    link_type: Optional[str] = None

    # Raw target (as stored in the link)
    raw_target: Optional[str] = None

    # Resolved target (absolute path after resolution)
    resolved_target: Optional[Path] = None

    # Relationship to destination
    target_is_destination: bool = False  # Target == destination
    target_inside_destination: bool = False  # Target is child of destination
    target_contains_destination: bool = False  # Destination is child of target

    # Link health
    is_broken: bool = False  # Target doesn't exist
    is_circular: bool = False  # Part of a circular link chain

    # Decision tracking
    action: Optional[LinkAction] = None
    action_result: Optional[str] = None  # Success/error message

    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)

    def creates_cycle_with(self, dest_path: Path) -> bool:
        """Check if this link would create a cycle with the given destination."""
        return (
            self.target_is_destination or
            self.target_inside_destination or
            self.target_contains_destination
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization and reporting."""
        return {
            "link_path": str(self.link_path),
            "link_type": self.link_type,
            "raw_target": self.raw_target,
            "resolved_target": str(self.resolved_target) if self.resolved_target else None,
            "target_is_destination": self.target_is_destination,
            "target_inside_destination": self.target_inside_destination,
            "target_contains_destination": self.target_contains_destination,
            "is_broken": self.is_broken,
            "is_circular": self.is_circular,
            "action": self.action.value if self.action else None,
            "action_result": self.action_result,
        }


def analyze_link(
    link_path: Union[str, Path],
    dest_path: Union[str, Path]
) -> LinkInfo:
    """
    Analyze a link and its relationship to the destination.

    Args:
        link_path: Path to the link
        dest_path: Destination path for the MOVE operation

    Returns:
        LinkInfo with all analysis results
    """
    link_path = Path(link_path)
    dest_path = Path(dest_path).resolve()

    info = LinkInfo(link_path=link_path)

    # Detect link type
    info.link_type = detect_link_type(link_path)

    # Get raw target
    info.raw_target = get_link_target(link_path)

    if info.raw_target is None:
        info.is_broken = True
        return info

    # Resolve target
    try:
        # Handle relative targets
        if not Path(info.raw_target).is_absolute():
            resolved = (link_path.parent / info.raw_target).resolve()
        else:
            resolved = Path(info.raw_target).resolve()

        info.resolved_target = resolved

        # Check if target exists
        if not resolved.exists():
            info.is_broken = True

    except Exception as e:
        logger.debug(f"Error resolving link target {info.raw_target}: {e}")
        info.is_broken = True
        return info

    # Analyze relationship to destination
    if info.resolved_target:
        try:
            # Target IS destination
            if os.path.samefile(info.resolved_target, dest_path):
                info.target_is_destination = True

            # Target is inside destination
            elif info.resolved_target.is_relative_to(dest_path):
                info.target_inside_destination = True

            # Destination is inside target
            elif dest_path.is_relative_to(info.resolved_target):
                info.target_contains_destination = True

        except (OSError, ValueError):
            # samefile can fail, is_relative_to can raise ValueError
            pass

    return info


def decide_link_action(
    link_info: LinkInfo,
    mode: LinkHandlingMode,
    dest_path: Path
) -> LinkAction:
    """
    Decide what action to take for a link based on handling mode.

    Args:
        link_info: Analyzed link information
        mode: Link handling mode from CLI
        dest_path: Destination path

    Returns:
        LinkAction to take for this link
    """
    creates_cycle = link_info.creates_cycle_with(dest_path)

    if mode == LinkHandlingMode.BLOCK:
        if creates_cycle:
            return LinkAction.BLOCK
        else:
            return LinkAction.FOLLOW

    elif mode == LinkHandlingMode.SKIP:
        # Always skip links in skip mode
        return LinkAction.SKIP

    elif mode == LinkHandlingMode.UNLINK:
        if creates_cycle:
            # Unlink links that point to/inside destination (consolidation)
            return LinkAction.UNLINK
        else:
            # Links pointing elsewhere - skip them
            return LinkAction.SKIP

    elif mode == LinkHandlingMode.RECREATE:
        # Phase 2: recreate all links at destination
        raise NotImplementedError(
            "Link handling mode 'recreate' is not yet implemented. "
            "Use 'skip' or 'unlink' for now. See issue #48 for progress."
        )

    elif mode == LinkHandlingMode.ASK:
        # Phase 2: interactive prompt
        raise NotImplementedError(
            "Link handling mode 'ask' is not yet implemented. "
            "Use 'skip' or 'unlink' for now. See issue #48 for progress."
        )

    # Fallback - shouldn't reach here
    return LinkAction.BLOCK


def is_link(path: Union[str, Path]) -> bool:
    """
    Check if a path is any type of link (junction, symlink, etc.).

    Args:
        path: Path to check

    Returns:
        True if path is a link of any type
    """
    path = Path(path)

    if not path.exists() and not path.is_symlink():
        return False

    # Check for symlink first (works cross-platform)
    if path.is_symlink():
        return True

    # On Windows, check for junction (reparse point)
    if os.name == 'nt':
        return is_junction(path)

    return False


def is_junction(path: Union[str, Path]) -> bool:
    """
    Check if a path is a Windows NTFS junction.

    Args:
        path: Path to check

    Returns:
        True if path is a junction
    """
    if os.name != 'nt':
        return False

    path = Path(path)

    if not path.exists():
        return False

    if not path.is_dir():
        return False

    try:
        # Use GetFileAttributesW to check for reparse point
        FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))

        if attrs == -1:  # INVALID_FILE_ATTRIBUTES
            return False

        if not (attrs & FILE_ATTRIBUTE_REPARSE_POINT):
            return False

        # It's a reparse point - could be junction or symlink
        # Junctions and symlinks are both reparse points on Windows
        # For our purposes, we treat directory reparse points as "junction-like"
        # The key distinction is that it's a link, not a real directory
        return True

    except Exception as e:
        logger.debug(f"Error checking junction status for {path}: {e}")
        return False


def is_symlink(path: Union[str, Path]) -> bool:
    """
    Check if a path is a symbolic link.

    Args:
        path: Path to check

    Returns:
        True if path is a symlink
    """
    return Path(path).is_symlink()


def detect_link_type(path: Union[str, Path]) -> Optional[str]:
    """
    Detect what type of link a path is.

    Args:
        path: Path to check

    Returns:
        Link type string ('junction', 'soft', 'hard') or None if not a link
    """
    path = Path(path)

    if not path.exists() and not path.is_symlink():
        return None

    # Check symlink first
    if path.is_symlink():
        return LINK_TYPE_SOFT

    # Check junction on Windows
    if os.name == 'nt' and is_junction(path):
        return LINK_TYPE_JUNCTION

    # Hard links are indistinguishable from regular files
    # We can only detect them by checking link count > 1
    try:
        if path.is_file():
            stat_info = path.stat()
            if hasattr(stat_info, 'st_nlink') and stat_info.st_nlink > 1:
                return LINK_TYPE_HARD
    except Exception:
        pass

    return None


def get_link_target(path: Union[str, Path]) -> Optional[str]:
    """
    Get the target of a link.

    Args:
        path: Path to the link

    Returns:
        Target path as string, or None if not a link or error
    """
    path = Path(path)

    try:
        if path.is_symlink():
            return str(os.readlink(path))

        # For junctions on Windows, use a different approach
        if os.name == 'nt' and is_junction(path):
            return _get_junction_target(path)

    except Exception as e:
        logger.debug(f"Error getting link target for {path}: {e}")

    return None


def _get_junction_target(path: Union[str, Path]) -> Optional[str]:
    """
    Get the target of a Windows junction using fsutil or dir command.

    Args:
        path: Path to the junction

    Returns:
        Target path or None
    """
    try:
        # Try using dir command to get junction target
        result = subprocess.run(
            ['cmd', '/c', 'dir', '/al', str(Path(path).parent)],
            capture_output=True, text=True, check=False
        )

        if result.returncode == 0:
            # Parse output looking for our junction
            name = Path(path).name
            for line in result.stdout.split('\n'):
                if f'<JUNCTION>' in line and name in line:
                    # Extract target from [target] format
                    start = line.find('[')
                    end = line.find(']')
                    if start != -1 and end != -1:
                        return line[start+1:end]

    except Exception as e:
        logger.debug(f"Error getting junction target: {e}")

    return None


def create_link(
    link_path: Union[str, Path],
    target_path: Union[str, Path],
    link_type: str = LINK_TYPE_AUTO,
    is_directory: bool = True
) -> Tuple[bool, str, Optional[str]]:
    """
    Create a filesystem link from link_path pointing to target_path.

    Args:
        link_path: Where to create the link (the source location after move)
        target_path: What the link should point to (the destination after move)
        link_type: Type of link to create ('junction', 'soft', 'hard', 'auto')
        is_directory: Whether the target is a directory (for symlinks)

    Returns:
        Tuple of (success, actual_link_type, error_message)
    """
    link_path = Path(link_path)
    target_path = Path(target_path)

    # Validate link type
    if link_type not in VALID_LINK_TYPES:
        return False, link_type, f"Invalid link type: {link_type}"

    # Handle 'dazzle' type - not yet implemented
    if link_type == LINK_TYPE_DAZZLE:
        return False, link_type, "Dazzle link type not yet implemented"

    # Resolve 'auto' to platform-appropriate type
    if link_type == LINK_TYPE_AUTO:
        if os.name == 'nt' and is_directory:
            link_type = LINK_TYPE_JUNCTION
        else:
            link_type = LINK_TYPE_SOFT
        logger.debug(f"Auto-selected link type: {link_type}")

    # Ensure link_path doesn't exist (or is empty directory we can remove)
    if link_path.exists():
        if link_path.is_dir() and not any(link_path.iterdir()):
            try:
                link_path.rmdir()
            except Exception as e:
                return False, link_type, f"Cannot remove empty directory at link path: {e}"
        else:
            return False, link_type, f"Link path already exists and is not empty: {link_path}"

    # Ensure parent directory exists
    link_path.parent.mkdir(parents=True, exist_ok=True)

    # Create the appropriate link type
    try:
        if link_type == LINK_TYPE_JUNCTION:
            success, error = _create_junction(link_path, target_path)
        elif link_type == LINK_TYPE_SOFT:
            success, error = _create_symlink(link_path, target_path, is_directory)
        elif link_type == LINK_TYPE_HARD:
            success, error = _create_hard_link(link_path, target_path)
        else:
            return False, link_type, f"Unsupported link type: {link_type}"

        if success:
            logger.info(f"Created {link_type} link: {link_path} -> {target_path}")
            return True, link_type, None
        else:
            return False, link_type, error

    except Exception as e:
        return False, link_type, str(e)


def _create_junction(link_path: Path, target_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Create a Windows NTFS junction.

    Args:
        link_path: Where to create the junction
        target_path: What the junction should point to

    Returns:
        Tuple of (success, error_message)
    """
    if os.name != 'nt':
        return False, "Junctions are only supported on Windows"

    try:
        # Use mklink /j command
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/j', str(link_path), str(target_path)],
            capture_output=True, text=True, check=False
        )

        if result.returncode == 0:
            return True, None
        else:
            return False, f"mklink /j failed: {result.stderr.strip()}"

    except Exception as e:
        return False, str(e)


def _create_symlink(link_path: Path, target_path: Path, is_directory: bool) -> Tuple[bool, Optional[str]]:
    """
    Create a symbolic link.

    Args:
        link_path: Where to create the symlink
        target_path: What the symlink should point to
        is_directory: Whether target is a directory

    Returns:
        Tuple of (success, error_message)
    """
    try:
        if os.name == 'nt':
            os.symlink(str(target_path), str(link_path), target_is_directory=is_directory)
        else:
            os.symlink(str(target_path), str(link_path))
        return True, None

    except OSError as e:
        if os.name == 'nt' and e.winerror == 1314:
            return False, "Creating symlinks requires administrator privileges or Developer Mode on Windows"
        return False, str(e)
    except Exception as e:
        return False, str(e)


def _create_hard_link(link_path: Path, target_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Create a hard link (files only, same filesystem).

    Args:
        link_path: Where to create the hard link
        target_path: What file to link to

    Returns:
        Tuple of (success, error_message)
    """
    if not target_path.is_file():
        return False, "Hard links can only be created for files, not directories"

    try:
        os.link(str(target_path), str(link_path))
        return True, None
    except OSError as e:
        if e.errno == 18:  # EXDEV - cross-device link
            return False, "Hard links cannot cross filesystem boundaries"
        return False, str(e)
    except Exception as e:
        return False, str(e)


def remove_link(path: Union[str, Path]) -> Tuple[bool, Optional[str]]:
    """
    Safely remove a link without deleting the target content.

    For junctions and directory symlinks, this removes the link only.
    For file symlinks and hard links, this removes the link only.

    Args:
        path: Path to the link to remove

    Returns:
        Tuple of (success, error_message)
    """
    path = Path(path)

    if not is_link(path):
        return False, f"Path is not a link: {path}"

    link_type = detect_link_type(path)

    try:
        if link_type == LINK_TYPE_JUNCTION:
            # Windows junction: rmdir removes junction, not target
            os.rmdir(path)
        elif link_type == LINK_TYPE_SOFT:
            if path.is_dir():
                # Directory symlink on Windows
                os.rmdir(path)
            else:
                # File symlink
                os.remove(path)
        elif link_type == LINK_TYPE_HARD:
            # Hard link: remove just decrements link count
            os.remove(path)
        else:
            # Unknown link type, try generic removal
            if path.is_dir():
                os.rmdir(path)
            else:
                os.remove(path)

        logger.info(f"Removed {link_type} link: {path}")
        return True, None

    except Exception as e:
        return False, str(e)


def verify_link(path: Union[str, Path], expected_target: Union[str, Path]) -> Tuple[bool, Optional[str]]:
    """
    Verify that a link exists and points to the expected target.

    Args:
        path: Path to the link
        expected_target: Expected target path

    Returns:
        Tuple of (matches, actual_target_or_error)
    """
    path = Path(path)
    expected_target = Path(expected_target)

    if not is_link(path):
        return False, "Path is not a link"

    actual_target = get_link_target(path)

    if actual_target is None:
        return False, "Could not determine link target"

    # Normalize paths for comparison
    try:
        actual_normalized = Path(actual_target).resolve()
        expected_normalized = expected_target.resolve()

        if actual_normalized == expected_normalized:
            return True, str(actual_target)
        else:
            return False, str(actual_target)
    except Exception:
        # Fall back to string comparison
        if str(actual_target) == str(expected_target):
            return True, str(actual_target)
        return False, str(actual_target)


def check_for_links_at_sources(manifest, preserved_dir: Union[str, Path]) -> Dict:
    """
    Check if any original source paths are now links.

    This is used during RESTORE to detect links that need to be removed
    before files can be restored to their original locations.

    Args:
        manifest: PreserveManifest object
        preserved_dir: Directory containing preserved files

    Returns:
        Dictionary with:
        - has_links: bool
        - links: list of link info dicts
    """
    from .manifest import extract_source_from_manifest

    links_found = []

    # First check manifest's link_result (if we created the link)
    for op in manifest.get_all_operations():
        link_result = op.get('link_result')
        if link_result:
            link_path = link_result.get('link_path')
            if link_path and is_link(link_path):
                links_found.append({
                    'path': link_path,
                    'type': link_result.get('type'),
                    'target': link_result.get('target_path'),
                    'tracked': True  # We created this link
                })

    # Also check filesystem for untracked links (safety)
    source_base = extract_source_from_manifest(manifest)
    if source_base and is_link(source_base):
        # Check if we already found this link
        if not any(l['path'] == str(source_base) for l in links_found):
            links_found.append({
                'path': str(source_base),
                'type': detect_link_type(source_base),
                'target': get_link_target(source_base),
                'tracked': False  # Not in manifest - warn user
            })

    return {
        'has_links': len(links_found) > 0,
        'links': links_found
    }
