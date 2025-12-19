"""
Utility functions for the preserve command-line tool.

This module provides utility functions for the preserve CLI, including
formatting, colorization, progress reporting, and path operations.
"""

import os
import sys
import time
import json
import logging
import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Callable, TextIO
from preserve.output import VerbosityLevel

# Constants for terminal colors
COLORS = {
    'RESET': '\033[0m',
    'RED': '\033[91m',
    'GREEN': '\033[92m',
    'YELLOW': '\033[93m',
    'BLUE': '\033[94m',
    'MAGENTA': '\033[95m',
    'CYAN': '\033[96m',
    'WHITE': '\033[97m',
    'BOLD': '\033[1m',
    'UNDERLINE': '\033[4m'
}

# Set up module-level logger
logger = logging.getLogger(__name__)

# Flag to indicate if color is enabled
color_enabled = True

def disable_color():
    """Disable colored output."""
    global color_enabled
    color_enabled = False

def enable_color():
    """Enable colored output."""
    global color_enabled
    color_enabled = True

def colorize(text: str, color: str) -> str:
    """
    Add color to text for terminal output.
    
    Args:
        text: The text to colorize
        color: The color to apply (must be a key in COLORS dict)
        
    Returns:
        Colorized string if color is enabled, otherwise the original string
    """
    if not color_enabled or color not in COLORS:
        return text
    
    return f"{COLORS[color]}{text}{COLORS['RESET']}"

def parse_time_spec(time_spec: str) -> float:
    """
    Parse a time specification into a timestamp.
    
    Supports:
    - ISO format dates (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    - Relative times (Nd, Nh, Nm, Ns where N is a number)
    
    Args:
        time_spec: Time specification string
        
    Returns:
        Timestamp as seconds since epoch
    """
    # Check for relative time format
    relative_pattern = re.compile(r'^(\d+)([dhms])$')
    match = relative_pattern.match(time_spec)
    
    if match:
        value, unit = match.groups()
        value = int(value)
        now = time.time()
        
        if unit == 'd':
            # Days
            return now - (value * 86400)
        elif unit == 'h':
            # Hours
            return now - (value * 3600)
        elif unit == 'm':
            # Minutes
            return now - (value * 60)
        elif unit == 's':
            # Seconds
            return now - value
    
    # Check for ISO format date
    try:
        # Try full ISO format with time
        dt = datetime.datetime.fromisoformat(time_spec)
        return dt.timestamp()
    except ValueError:
        try:
            # Try just date
            dt = datetime.datetime.strptime(time_spec, '%Y-%m-%d')
            return dt.timestamp()
        except ValueError:
            raise ValueError(f"Invalid time specification: {time_spec}")

def format_path(path: Union[str, Path], relative_to: Optional[Union[str, Path]] = None) -> str:
    """
    Format a path for display, optionally making it relative to another path.
    
    Args:
        path: The path to format
        relative_to: Path to make the path relative to (optional)
        
    Returns:
        Formatted path string
    """
    path_obj = Path(path)
    
    if relative_to:
        relative_to_path = Path(relative_to)
        try:
            return str(path_obj.relative_to(relative_to_path))
        except ValueError:
            # Can't make relative, use absolute path
            return str(path_obj)
    
    return str(path_obj)

def format_size(size_bytes: int) -> str:
    """
    Format a size in bytes to a human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string
    """
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    elif size_bytes < 1024 * 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024 * 1024):.2f} TB"


def format_bytes_detailed(size_bytes: int) -> str:
    """
    Format bytes with both raw value (with commas) and human-readable size.

    Args:
        size_bytes: Size in bytes

    Returns:
        String like "131,375,979,782 (131.38 GB)"

    Examples:
        >>> format_bytes_detailed(131375979782)
        '131,375,979,782 (131.38 GB)'
        >>> format_bytes_detailed(1024)
        '1,024 (1.0 KB)'
        >>> format_bytes_detailed(500)
        '500 (500 bytes)'
    """
    raw_with_commas = f"{size_bytes:,}"
    human_readable = format_size(size_bytes)
    return f"{raw_with_commas} ({human_readable})"

def format_timestamp(timestamp: float) -> str:
    """
    Format a timestamp as a human-readable string.
    
    Args:
        timestamp: The timestamp to format
        
    Returns:
        Formatted timestamp string
    """
    if not timestamp:
        return "Unknown"
    
    try:
        dt = datetime.datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return str(timestamp)

def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds as a human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string
    """
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} hours"

def print_progress(current: int, total: int, prefix: str = '', suffix: str = '', 
                  bar_length: int = 50, file: Any = sys.stdout):
    """
    Print a progress bar.
    
    Args:
        current: Current progress value
        total: Total value for 100% progress
        prefix: String to print before the progress bar
        suffix: String to print after the progress bar
        bar_length: Length of the progress bar in characters
        file: File to print to (default: sys.stdout)
    """
    if total == 0:
        percentage = 100
    else:
        percentage = int(100 * (current / total))
    
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    
    # Use carriage return to overwrite the line
    file.write(f'\r{prefix} |{bar}| {percentage}% {suffix}')
    file.flush()
    
    # Print a newline when we're done
    if current == total:
        file.write('\n')

class ProgressTracker:
    """
    Track progress of a multi-file operation.
    
    This class can be used to track both file count and byte count progress
    and display progress bars or summaries.
    """
    
    def __init__(self, total_files: int = 0, total_bytes: int = 0, show_progress: bool = True):
        """
        Initialize a progress tracker.
        
        Args:
            total_files: Total number of files to process
            total_bytes: Total number of bytes to process
            show_progress: Whether to show progress bars
        """
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.processed_files = 0
        self.processed_bytes = 0
        self.successful_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.start_time = time.time()
        self.show_progress = show_progress
        self.last_update_time = 0
        self.update_interval = 0.1  # Seconds between progress updates
    
    def start(self):
        """Start or reset the progress tracker."""
        self.processed_files = 0
        self.processed_bytes = 0
        self.successful_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.start_time = time.time()
        self.last_update_time = 0
    
    def update(self, file_count: int = 0, byte_count: int = 0, success: bool = True, 
             skipped: bool = False, force_display: bool = False):
        """
        Update progress.
        
        Args:
            file_count: Number of additional files processed
            byte_count: Number of additional bytes processed
            success: Whether the files were processed successfully
            skipped: Whether the files were skipped
            force_display: Whether to force display update even if interval hasn't elapsed
        """
        self.processed_files += file_count
        self.processed_bytes += byte_count
        
        if success and not skipped:
            self.successful_files += file_count
        elif skipped:
            self.skipped_files += file_count
        else:
            self.failed_files += file_count
        
        # Limit updates to avoid excessive display refreshing
        current_time = time.time()
        if force_display or (current_time - self.last_update_time >= self.update_interval):
            self.last_update_time = current_time
            self.display_progress()
    
    def display_progress(self):
        """Display the current progress."""
        if not self.show_progress:
            return
        
        elapsed = time.time() - self.start_time
        
        # Calculate speed
        if elapsed > 0:
            files_per_second = self.processed_files / elapsed
            bytes_per_second = self.processed_bytes / elapsed
        else:
            files_per_second = 0
            bytes_per_second = 0
        
        # Calculate ETA
        if self.total_files > 0 and files_per_second > 0:
            eta_seconds = (self.total_files - self.processed_files) / files_per_second
            eta = format_duration(eta_seconds)
        else:
            eta = "Unknown"
        
        # File progress
        file_prefix = f"Files: {self.processed_files}/{self.total_files}"
        file_suffix = f"ETA: {eta}"
        print_progress(self.processed_files, self.total_files, prefix=file_prefix, suffix=file_suffix)
        
        # For byte progress, only show if we know the total
        if self.total_bytes > 0:
            bytes_prefix = f"Bytes: {format_size(self.processed_bytes)}/{format_size(self.total_bytes)}"
            bytes_suffix = f"Speed: {format_size(bytes_per_second)}/s"
            print_progress(self.processed_bytes, self.total_bytes, prefix=bytes_prefix, suffix=bytes_suffix)
    
    def summarize(self) -> Dict[str, Any]:
        """
        Summarize the progress.
        
        Returns:
            Dictionary with progress summary
        """
        elapsed = time.time() - self.start_time
        
        # Calculate speed
        if elapsed > 0:
            files_per_second = self.processed_files / elapsed
            bytes_per_second = self.processed_bytes / elapsed
        else:
            files_per_second = 0
            bytes_per_second = 0
        
        return {
            'total_files': self.total_files,
            'processed_files': self.processed_files,
            'successful_files': self.successful_files,
            'failed_files': self.failed_files,
            'skipped_files': self.skipped_files,
            'total_bytes': self.total_bytes,
            'processed_bytes': self.processed_bytes,
            'elapsed_time': elapsed,
            'elapsed_formatted': format_duration(elapsed),
            'files_per_second': files_per_second,
            'bytes_per_second': bytes_per_second,
            'bytes_per_second_formatted': format_size(bytes_per_second) + '/s'
        }
    
    def display_summary(self, title: str = 'Operation Summary'):
        """
        Display a summary of the progress.
        
        Args:
            title: Title for the summary
        """
        summary = self.summarize()
        
        print(f"\n{colorize(title, 'BOLD')}:")
        print(f"  Total files: {summary['total_files']}")
        print(f"  Processed:   {summary['processed_files']}")
        print(f"  Successful:  {colorize(str(summary['successful_files']), 'GREEN')}")
        print(f"  Failed:      {colorize(str(summary['failed_files']), 'RED')}")
        print(f"  Skipped:     {colorize(str(summary['skipped_files']), 'YELLOW')}")
        print(f"  Total bytes: {format_size(summary['total_bytes'])}")
        print(f"  Elapsed:     {summary['elapsed_formatted']}")
        print(f"  Speed:       {summary['bytes_per_second_formatted']}")

def save_json(data: Any, file_path: Union[str, Path], pretty: bool = True) -> bool:
    """
    Save data to a JSON file.
    
    Args:
        data: Data to save
        file_path: Path to save to
        pretty: Whether to format the JSON for human readability
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create parent directory if it doesn't exist
        path_obj = Path(file_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path_obj, 'w', encoding='utf-8') as f:
            if pretty:
                json.dump(data, f, indent=2)
            else:
                json.dump(data, f)
        
        return True
    except Exception as e:
        logger.error(f"Error saving JSON to {file_path}: {e}")
        return False

def load_json(file_path: Union[str, Path]) -> Optional[Any]:
    """
    Load data from a JSON file.
    
    Args:
        file_path: Path to load from
        
    Returns:
        Loaded data, or None if loading failed
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading JSON from {file_path}: {e}")
        return None

def confirm_operation(prompt: str, default: bool = False) -> bool:
    """
    Ask the user to confirm an operation.
    
    Args:
        prompt: The prompt to display
        default: Default choice if user presses Enter
        
    Returns:
        True if user confirmed, False otherwise
    """
    yes_choices = ['y', 'yes', 'true', '1']
    no_choices = ['n', 'no', 'false', '0']
    
    if default:
        yes_choices.append('')
        prompt += " [Y/n] "
    else:
        no_choices.append('')
        prompt += " [y/N] "
    
    while True:
        try:
            response = input(prompt).lower()
            if response in yes_choices:
                return True
            elif response in no_choices:
                return False
            else:
                print("Please answer with 'y' or 'n'.")
        except (KeyboardInterrupt, EOFError):
            print()
            return False

def plural(count: int, singular: str, plural: str) -> str:
    """
    Return singular or plural form based on count.
    
    Args:
        count: Count determining singular or plural
        singular: Singular form
        plural: Plural form
        
    Returns:
        Singular or plural form based on count
    """
    return singular if count == 1 else plural

def safe_delete(path: Union[str, Path]) -> bool:
    """
    Safely delete a file or directory.
    
    Args:
        path: Path to delete
        
    Returns:
        True if successful, False otherwise
    """
    path_obj = Path(path)
    
    try:
        if path_obj.is_dir():
            import shutil
            shutil.rmtree(path_obj)
        else:
            path_obj.unlink()
        
        return True
    except Exception as e:
        logger.error(f"Error deleting {path}: {e}")
        return False

def get_terminal_size() -> Dict[str, int]:
    """
    Get the terminal size.
    
    Returns:
        Dictionary with 'columns' and 'lines' keys
    """
    try:
        columns, lines = os.get_terminal_size()
        return {'columns': columns, 'lines': lines}
    except (AttributeError, OSError):
        # Default values if we can't determine the terminal size
        return {'columns': 80, 'lines': 24}

def find_command(command: str) -> Optional[str]:
    """
    Find the full path to a command in PATH.
    
    Args:
        command: Command name to find
        
    Returns:
        Full path to the command, or None if not found
    """
    # If we're on Windows and no extension was provided, we need to check for .exe, .cmd, etc.
    if os.name == 'nt' and not command.lower().endswith(('.exe', '.bat', '.cmd')):
        exts = os.environ.get('PATHEXT', '').split(os.pathsep)
        possible_cmds = [command + ext for ext in exts]
    else:
        possible_cmds = [command]
    
    for path_dir in os.environ.get('PATH', '').split(os.pathsep):
        path_dir = path_dir.strip('"')
        for cmd in possible_cmds:
            cmd_path = os.path.join(path_dir, cmd)
            if os.path.isfile(cmd_path) and os.access(cmd_path, os.X_OK):
                return cmd_path
    
    return None

def truncate_path(path: Union[str, Path], max_length: int = 40) -> str:
    """
    Truncate a path to a maximum length, preserving the filename.
    
    Args:
        path: Path to truncate
        max_length: Maximum length
        
    Returns:
        Truncated path
    """
    path_str = str(path)
    
    if len(path_str) <= max_length:
        return path_str
    
    # Get the filename and directory
    path_obj = Path(path)
    filename = path_obj.name
    directory = path_str[:-len(filename)]
    
    # If the filename itself is too long, truncate it
    if len(filename) > max_length - 4:  # Allow space for ".../"
        return ".../" + filename[:max_length - 4]
    
    # Calculate how much of the directory we can keep
    avail_len = max_length - len(filename) - 4  # Allow space for ".../", "/"
    if avail_len <= 0:
        return ".../" + filename
    
    return ".../" + directory[-avail_len:] + filename

def join_paths(*paths: Union[str, Path]) -> Path:
    """
    Join paths in a cross-platform way.
    
    Args:
        *paths: Path components to join
        
    Returns:
        Joined path
    """
    result = Path(paths[0])
    for path in paths[1:]:
        result = result / path
    return result

def is_within_directory(path: Union[str, Path], directory: Union[str, Path]) -> bool:
    """
    Check if a path is within a directory.
    
    Args:
        path: Path to check
        directory: Directory to check against
        
    Returns:
        True if path is within directory, False otherwise
    """
    path_obj = Path(path).resolve()
    directory_obj = Path(directory).resolve()
    
    try:
        path_obj.relative_to(directory_obj)
        return True
    except ValueError:
        return False


def matches_exclude_pattern(file_path, patterns):
    """
    Check if file matches any exclude pattern.

    Args:
        file_path: Path object to check
        patterns: List of pattern strings (glob-style)

    Returns:
        True if file matches any pattern, False otherwise
    """
    from fnmatch import fnmatch

    # Convert to string for pattern matching
    file_str = str(file_path)
    file_name = file_path.name

    for pattern in patterns:
        # Check full path match (for patterns with / or \)
        if '/' in pattern or os.sep in pattern:
            # Pattern includes path separators, match against full path
            if fnmatch(file_str, pattern):
                return True
            # Also try with forward slashes normalized (for cross-platform)
            if fnmatch(file_str.replace(os.sep, '/'), pattern):
                return True
        else:
            # Pattern without path separators, match against filename only
            if fnmatch(file_name, pattern):
                return True

    return False


# Check for dazzlelink availability
try:
    from preserve import dazzlelink as preserve_dazzlelink
    HAVE_DAZZLELINK = preserve_dazzlelink.is_available()
except ImportError:
    try:
        import dazzlelink as preserve_dazzlelink
        HAVE_DAZZLELINK = preserve_dazzlelink.is_available()
    except ImportError:
        HAVE_DAZZLELINK = False
        preserve_dazzlelink = None


def walk_with_max_depth(path, max_depth=None):
    """Walk directory tree with optional depth limit.

    Args:
        path: Root path to start walking from
        max_depth: Maximum depth to traverse (None for unlimited)

    Yields:
        (root, dirs, files) tuples like os.walk
    """
    path = Path(path)

    if max_depth is None:
        # No depth limit, use regular os.walk
        yield from os.walk(path)
        return

    # Track depth by counting separators from base path
    base_depth = str(path).count(os.sep)

    for root, dirs, files in os.walk(path):
        current_depth = str(root).count(os.sep) - base_depth

        yield root, dirs, files

        # If we've reached max depth, clear dirs to prevent deeper traversal
        if current_depth >= max_depth:
            dirs.clear()


def find_files_from_args(args):
    """Find files based on command-line arguments"""
    source_files = []

    # Direct source files
    if args.sources:
        for src in args.sources:
            src_path = Path(src)
            if src_path.exists():
                if src_path.is_file():
                    source_files.append(src_path)
                elif src_path.is_dir() and hasattr(args, 'recursive') and args.recursive:
                    # Recursively add all files in directory
                    max_depth = getattr(args, 'max_depth', None)
                    for root, _, files in walk_with_max_depth(src_path, max_depth):
                        for file in files:
                            source_files.append(Path(root) / file)
                else:
                    # Not recursive, just add files in top-level directory
                    for item in src_path.glob('*'):
                        if item.is_file():
                            source_files.append(item)

    # Search paths with glob/regex patterns
    if hasattr(args, 'srchPath') and args.srchPath:
        search_paths = [Path(p) for p in args.srchPath]

        if hasattr(args, 'glob') and args.glob:
            # Use glob patterns
            for search_path in search_paths:
                for pattern in args.glob:
                    if hasattr(args, 'recursive') and args.recursive:
                        # Recursive search
                        for file in search_path.glob('**/' + pattern):
                            if file.is_file():
                                source_files.append(file)
                    else:
                        # Non-recursive search
                        for file in search_path.glob(pattern):
                            if file.is_file():
                                source_files.append(file)

        elif hasattr(args, 'regex') and args.regex:
            # Use regex patterns
            patterns = [re.compile(p) for p in args.regex]

            for search_path in search_paths:
                if hasattr(args, 'recursive') and args.recursive:
                    # Recursive search
                    max_depth = getattr(args, 'max_depth', None)
                    for root, _, files in walk_with_max_depth(search_path, max_depth):
                        for file in files:
                            file_path = Path(root) / file
                            if any(p.search(str(file_path)) for p in patterns):
                                source_files.append(file_path)
                else:
                    # Non-recursive search
                    for file in search_path.iterdir():
                        if file.is_file() and any(p.search(str(file)) for p in patterns):
                            source_files.append(file)

    # Handle includes
    if hasattr(args, 'include') and args.include:
        for include in args.include:
            inc_path = Path(include)
            if inc_path.exists():
                if inc_path.is_file():
                    source_files.append(inc_path)
                elif inc_path.is_dir() and hasattr(args, 'recursive') and args.recursive:
                    # Recursively add all files in directory
                    for root, _, files in os.walk(inc_path):
                        for file in files:
                            source_files.append(Path(root) / file)

    # Handle loadIncludes
    if hasattr(args, 'loadIncludes') and args.loadIncludes:
        try:
            with open(args.loadIncludes, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        inc_path = Path(line)
                        if inc_path.exists() and inc_path.is_file():
                            source_files.append(inc_path)
        except Exception as e:
            logger.error(f"Error loading includes from {args.loadIncludes}: {e}")

    # Handle excludes and loadExcludes with pattern matching
    exclude_patterns = []

    if hasattr(args, 'exclude') and args.exclude:
        # Add patterns from command line
        exclude_patterns.extend(args.exclude)

    if hasattr(args, 'loadExcludes') and args.loadExcludes:
        try:
            with open(args.loadExcludes, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        exclude_patterns.append(line)
        except Exception as e:
            logger.error(f"Error loading excludes from {args.loadExcludes}: {e}")

    # Apply newer-than filter if specified
    if hasattr(args, 'newer_than') and args.newer_than:
        try:
            cutoff_time = parse_time_spec(args.newer_than)
            source_files = [f for f in source_files if f.stat().st_mtime > cutoff_time]
        except Exception as e:
            logger.error(f"Error applying newer-than filter: {e}")

    # Apply exclude patterns
    if exclude_patterns:
        source_files = [f for f in source_files
                       if not matches_exclude_pattern(f, exclude_patterns)]

    # Remove duplicates while preserving order
    unique_files = []
    seen = set()
    for file in source_files:
        file_str = str(file)
        if file_str not in seen:
            seen.add(file_str)
            unique_files.append(file)

    return unique_files


def get_hash_algorithms(args):
    """Get hash algorithms from command-line arguments"""
    if hasattr(args, 'hash') and args.hash:
        return args.hash
    else:
        return ['SHA256']  # Default


def get_path_style(args):
    """Get path style from command-line arguments"""
    if hasattr(args, 'rel') and args.rel:
        return 'relative'
    elif hasattr(args, 'abs') and args.abs:
        return 'absolute'
    elif hasattr(args, 'flat') and args.flat:
        return 'flat'
    else:
        return 'relative'  # Default to relative for cleaner, more portable backups


def get_preserve_dir(args, dest_path):
    """Get preserve directory path"""
    if hasattr(args, 'preserve_dir') and args.preserve_dir:
        preserve_dir = Path(dest_path) / '.preserve'
        preserve_dir.mkdir(parents=True, exist_ok=True)
        return preserve_dir
    return None


def get_manifest_path(args, preserve_dir):
    """Get manifest file path with sequential numbering support.

    This function implements a smart naming system:
    - First operation: creates preserve_manifest.json (backward compatible)
    - Second operation: renames first to _001, creates _002
    - Subsequent: creates _003, _004, etc.
    - Supports user descriptions: preserve_manifest_001__description.json
    """
    if hasattr(args, 'no_manifest') and args.no_manifest:
        return None

    if hasattr(args, 'manifest') and args.manifest:
        return Path(args.manifest)

    # Determine destination directory
    dest = preserve_dir if preserve_dir else Path(args.dst)
    single_manifest = dest / 'preserve_manifest.json'

    # Check if single manifest exists
    if single_manifest.exists():
        # Check if we also have numbered manifests
        numbered = list(dest.glob('preserve_manifest_[0-9][0-9][0-9]*.json'))
        if not numbered:
            # This would be the second operation - migrate the single manifest
            # But only if this isn't a read-only operation like --scan-only
            scan_only = getattr(args, 'scan_only', False)
            if scan_only:
                # Don't migrate during scan-only, just return what would be used
                return dest / 'preserve_manifest_002.json'

            new_001 = dest / 'preserve_manifest_001.json'
            print(f"Migrating {single_manifest.name} to {new_001.name}")
            try:
                single_manifest.rename(new_001)
                logger.info(f"Migrated existing manifest to {new_001.name}")
            except Exception as e:
                logger.error(f"Failed to migrate manifest: {e}")
                # Fall back to creating _002 anyway
            return dest / 'preserve_manifest_002.json'

    # Look for existing numbered manifests
    pattern = re.compile(r'preserve_manifest_(\d{3})(?:__.*)?\.json')
    existing_numbers = []

    for file in dest.glob('preserve_manifest_*.json'):
        match = pattern.match(file.name)
        if match:
            existing_numbers.append(int(match.group(1)))

    # If no manifests exist at all, create the simple one
    if not existing_numbers and not single_manifest.exists():
        return single_manifest

    # Find the next sequential number
    if existing_numbers:
        next_num = max(existing_numbers) + 1
        return dest / f'preserve_manifest_{next_num:03d}.json'

    # Edge case: single manifest exists but couldn't be migrated
    # and no numbered manifests exist
    return dest / 'preserve_manifest_002.json'


def get_dazzlelink_dir(args, preserve_dir):
    """
    Get dazzlelink directory path based on user options.

    This function determines where to store dazzlelink files based on
    user arguments. It respects the path preservation style (--abs, --rel, --flat)
    and properly structures the dazzlelink directory to mirror the destination.

    Args:
        args: Command-line arguments
        preserve_dir: Preserve directory path

    Returns:
        Path object for dazzlelink directory or None if not applicable
    """
    if not (hasattr(args, 'dazzlelink') and args.dazzlelink):
        return None

    if hasattr(args, 'dazzlelink_with_files') and args.dazzlelink_with_files:
        return None  # Store alongside files

    # Base destination path
    dest_base = Path(args.dst)

    if hasattr(args, 'dazzlelink_dir') and args.dazzlelink_dir:
        # User specified a custom dazzlelink directory
        # Make it relative to the destination path
        custom_dir = args.dazzlelink_dir

        # If it's an absolute path, use it directly
        if Path(custom_dir).is_absolute():
            dl_dir = Path(custom_dir)
        else:
            # Otherwise, make it relative to the destination
            dl_dir = dest_base / custom_dir

        dl_dir.mkdir(parents=True, exist_ok=True)
        return dl_dir

    if preserve_dir:
        # Default to .preserve/dazzlelinks in the destination directory
        dl_dir = preserve_dir / 'dazzlelinks'
        dl_dir.mkdir(parents=True, exist_ok=True)
        return dl_dir

    # If no preserve directory, create .dazzlelinks in the destination
    dl_dir = dest_base / '.dazzlelinks'
    dl_dir.mkdir(parents=True, exist_ok=True)
    return dl_dir


def _show_directory_help_message(args, logger, src, operation="COPY", is_warning=False):
    """Show helpful message when directory is used without --recursive flag.

    Args:
        args: Command arguments
        logger: Logger instance
        src: Source directory path
        operation: Operation type (COPY or MOVE)
        is_warning: If True, show as warning. If False, show as error.
    """
    # Use generic destination in examples to avoid exposing real paths
    example_dst = "D:\\backup" if "\\" in str(args.dst) else "/backup"

    log_func = logger.warning if is_warning else logger.error
    action = "copied" if operation == "COPY" else "moved"

    if is_warning:
        log_func("")
        log_func(f"WARNING: '{src}' contains subdirectories with files that will NOT be {action}.")
        log_func("         Use --recursive flag to include files from subdirectories.")
    else:
        log_func("No source files found")
        log_func("")
        log_func(f"ERROR: '{src}' is a directory but --recursive flag was not specified.")
        log_func("       The directory may be empty or contain only subdirectories.")

    log_func("")
    log_func(f"To {operation.lower()} all files from a directory, use one of these commands:")
    log_func(f'  preserve {operation} "{src}" --recursive --dst "{example_dst}"')
    log_func(f'  preserve {operation} "{src}" -r --dst "{example_dst}"')
    log_func("")
    log_func("Additional options you may want:")
    log_func("  --includeBase : Include the source directory name in the destination")
    log_func("  --rel         : Preserve relative directory structure")
    log_func("  --abs         : Preserve absolute directory structure")

    if not is_warning:
        log_func("  --flat        : Copy all files directly to destination (no subdirectories)")
        log_func("")
        log_func("Example with common options:")
        log_func(f'  preserve {operation} "{src}" --recursive --rel --includeBase --dst "{example_dst}"')
    else:
        log_func("")


def get_effective_verbosity(args) -> int:
    """
    Get the effective verbosity level from args.

    This function handles the unified verbosity system where flags can be
    specified either globally or at the operation level.

    Args:
        args: Parsed command-line arguments

    Returns:
        int: Verbosity level (VerbosityLevel enum value)
    """
    # Check for quiet flag first (overrides verbose)
    if hasattr(args, 'quiet') and args.quiet:
        return VerbosityLevel.QUIET

    # Check for verbose flag (count gives level)
    if hasattr(args, 'verbose') and args.verbose:
        # verbose can be a count (from action='count') or bool (legacy)
        if isinstance(args.verbose, int):
            # Map count to verbosity levels
            if args.verbose >= 3:
                return VerbosityLevel.DEBUG  # -vvv or more
            elif args.verbose == 2:
                return VerbosityLevel.DETAILED  # -vv
            elif args.verbose == 1:
                return VerbosityLevel.VERBOSE  # -v
        elif args.verbose:  # Legacy boolean True
            return VerbosityLevel.VERBOSE

    # Default to normal verbosity
    return VerbosityLevel.NORMAL
