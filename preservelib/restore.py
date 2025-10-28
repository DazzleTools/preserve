"""
Restoration logic for preserve.py.

This module provides functionality for restoring files to their original
locations based on manifests or other tracking mechanisms.
"""

import os
import sys
import shutil
import logging
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

from .manifest import PreserveManifest
from .metadata import apply_file_metadata

# Set up module-level logger
logger = logging.getLogger(__name__)

def restore_file_to_original(
    current_path: Union[str, Path],
    original_path: Union[str, Path],
    metadata: Optional[Dict[str, Any]] = None,
    preserve_attrs: bool = True,
    overwrite: bool = False
) -> bool:
    """
    Restore a file to its original location.
    
    Args:
        current_path: Current path of the file
        original_path: Original path to restore to
        metadata: Metadata to apply (optional)
        preserve_attrs: Whether to preserve file attributes
        overwrite: Whether to overwrite existing file
        
    Returns:
        True if successful, False otherwise
    """
    current = Path(current_path)
    original = Path(original_path)
    
    # Check if current path exists
    logger.debug(f"[DEBUG] Restore: Checking if current file exists: {current}")
    if not current.exists():
        logger.error(f"[DEBUG] Restore: Current file does not exist: {current}")
        # Try to see if file exists with alternate path formats
        alternate_path = None
        # Try looking for just the filename in the same directory
        try:
            parent_dir = current.parent
            if parent_dir.exists():
                # Look for any file with the same name in the parent directory
                filename = current.name
                matching_files = list(parent_dir.glob(filename))
                if matching_files:
                    alternate_path = matching_files[0]
                    logger.info(f"[DEBUG] Restore: Found alternate file with same name: {alternate_path}")
        except Exception as alt_error:
            logger.debug(f"[DEBUG] Restore: Error looking for alternate file: {alt_error}")
        
        if alternate_path and alternate_path.exists():
            logger.info(f"[DEBUG] Restore: Using alternate file: {alternate_path}")
            current = alternate_path
        else:
            return False
    
    # Check if original path exists and overwrite is not enabled
    logger.debug(f"[DEBUG] Restore: Checking if original path exists: {original}, overwrite={overwrite}")
    if original.exists() and not overwrite:
        logger.warning(f"[DEBUG] Restore: Original path exists and overwrite is disabled: {original}")
        return False
    
    try:
        # Create parent directory if it doesn't exist
        original.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy the file
        shutil.copy2(current, original)
        
        # Apply metadata if available and preserve_attrs is enabled
        if metadata and preserve_attrs:
            apply_file_metadata(original, metadata)
        
        logger.info(f"Restored {current} to {original}")
        return True
        
    except Exception as e:
        logger.error(f"Error restoring {current} to {original}: {e}")
        return False


def restore_files_from_manifest(
    manifest: PreserveManifest,
    source_directory: Union[str, Path],
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, bool]:
    """
    Restore files to their original locations based on a manifest.
    
    Args:
        manifest: Preservation manifest
        source_directory: Directory containing preserved files
        options: Restoration options (optional)
        
    Returns:
        Dictionary mapping file IDs to success status
    """
    # Initialize default options
    default_options = {
        'overwrite': False,
        'preserve_attrs': True,
        'verify': True,
        'dry_run': False
    }
    
    # Merge with provided options
    if options:
        default_options.update(options)
    
    options = default_options
    
    # Get source base directory
    source_dir = Path(source_directory)
    
    # Track restoration results
    results = {}
    
    # Process each file in manifest
    for file_id, file_info in manifest.get_all_files().items():
        source_orig_path = file_info.get('source_path')
        dest_orig_path = file_info.get('destination_path')
        
        if not source_orig_path or not dest_orig_path:
            logger.warning(f"Missing source or destination path for file {file_id}")
            results[file_id] = False
            continue
        
        # During restore, the destination is now the source
        current_path = Path(dest_orig_path)
        if not current_path.is_absolute():
            # Relative path, resolve against source directory
            current_path = source_dir / current_path
        
        original_path = Path(source_orig_path)
        
        # Check if current path exists
        if not current_path.exists():
            logger.warning(f"File not found in preserved location: {current_path}")
            results[file_id] = False
            continue
        
        # Dry run just logs what would be done
        if options['dry_run']:
            logger.info(f"[DRY RUN] Would restore {current_path} to {original_path}")
            results[file_id] = True
            continue
        
        # Restore file
        success = restore_file_to_original(
            current_path=current_path,
            original_path=original_path,
            metadata=file_info.get('metadata'),
            preserve_attrs=options['preserve_attrs'],
            overwrite=options['overwrite']
        )
        
        # Record result
        results[file_id] = success
    
    return results


def find_restoreable_files(
    directory: Union[str, Path],
    manifest_path: Optional[Union[str, Path]] = None,
    recursive: bool = True
) -> Tuple[Optional[PreserveManifest], Dict[str, Tuple[Path, Path]]]:
    """
    Find restoreable files in a directory.
    
    Args:
        directory: Directory to search
        manifest_path: Path to manifest file (optional)
        recursive: Whether to search recursively
        
    Returns:
        Tuple of (manifest, files) where files is a dictionary
        mapping file IDs to tuples of (current_path, original_path)
    """
    dir_path = Path(directory)
    
    # Find manifest
    manifest = None
    if manifest_path:
        try:
            manifest = PreserveManifest(manifest_path)
        except Exception as e:
            logger.error(f"Error loading manifest {manifest_path}: {e}")
            return None, {}
    else:
        # Look for manifest in common locations
        potential_manifests = [
            dir_path / '.preserve' / 'manifest.json',
            dir_path / '.preserve' / 'preserve_manifest.json',
            dir_path / 'preserve_manifest.json'
        ]
        
        for path in potential_manifests:
            if path.exists():
                try:
                    manifest = PreserveManifest(path)
                    break
                except Exception:
                    continue
    
    if not manifest:
        # Try to find a dazzlelink manifest
        try:
            # This is a placeholder for dazzlelink integration
            # In a full implementation, this would call into the dazzlelink library
            # to find and parse dazzlelink files in the directory
            logger.info("Dazzlelink manifest finding is not yet implemented")
            return None, {}
        except Exception as e:
            logger.error(f"Error finding dazzlelink manifest: {e}")
        
        # No manifest found
        logger.error(f"No manifest found in {directory}")
        return None, {}
    
    # Find restoreable files
    files = {}
    
    # Process files in the manifest
    for file_id, file_info in manifest.get_all_files().items():
        source_path = file_info.get('source_path')
        dest_path = file_info.get('destination_path')
        
        if not source_path or not dest_path:
            continue
        
        # Resolve destination path against directory
        dest_full_path = dir_path / dest_path if not Path(dest_path).is_absolute() else Path(dest_path)
        
        # Check if file exists
        if dest_full_path.exists():
            files[file_id] = (dest_full_path, Path(source_path))
    
    return manifest, files


def create_dazzlelink_manifest(
    directory: Union[str, Path],
    recursive: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Create a manifest-like structure from dazzlelink files.
    
    This is a placeholder for dazzlelink integration. In a full implementation,
    this would scan for dazzlelink files and extract their metadata into a
    format compatible with our manifest structure.
    
    Args:
        directory: Directory to scan for dazzlelink files
        recursive: Whether to search recursively
        
    Returns:
        A dictionary with manifest-like structure, or None if no dazzlelinks found
    """
    # This is where we would integrate with dazzlelink
    # For now, just return None to indicate no dazzlelinks found
    logger.info("Dazzlelink manifest creation is not yet implemented")
    return None


def verify_restore_operation(
    original_paths: List[Path],
    manifest: PreserveManifest,
    hash_algorithm: str = 'SHA256'
) -> Dict[str, bool]:
    """
    Verify that files were correctly restored to their original locations.
    
    Args:
        original_paths: List of restored file paths
        manifest: The manifest used for restoration
        hash_algorithm: Hash algorithm to use for verification
        
    Returns:
        Dictionary mapping file paths to verification status (True/False)
    """
    results = {}
    
    for path in original_paths:
        path_str = str(path)
        # Find the file in the manifest
        file_info = manifest.get_file_by_source(path_str)
        
        if not file_info:
            logger.warning(f"File not found in manifest: {path}")
            results[path_str] = False
            continue
        
        # Check if file exists
        if not path.exists():
            logger.warning(f"Restored file does not exist: {path}")
            results[path_str] = False
            continue
        
        # Verify hash if available
        if 'hashes' in file_info and hash_algorithm in file_info['hashes']:
            expected_hash = {
                hash_algorithm: file_info['hashes'][hash_algorithm]
            }
            
            from .manifest import verify_file_hash
            verified, _ = verify_file_hash(path, expected_hash)
            
            results[path_str] = verified
            
            if not verified:
                logger.warning(f"Hash verification failed for restored file: {path}")
        else:
            # If no hash is available, just check that the file exists
            results[path_str] = True
    
    return results
