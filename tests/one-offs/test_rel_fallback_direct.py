#!/usr/bin/env python3
"""
Direct test script for relative path mode fallback behavior.

This script tests the behavior of relative path mode fallback to absolute path style
when no common base directory exists.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Get the root of the project and add it to sys.path
script_dir = Path(__file__).parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

# Import the preservelib module
from dazzle_preservelib import operations

def setup_test_dirs():
    """Set up test directories with files from diverse locations."""
    # Create base temp dir
    base_dir = tempfile.mkdtemp(prefix="preserve_test_")
    base_path = Path(base_dir)
    
    # Create diverse directory structure
    dir1 = base_path / "dir1" / "subdir1"
    dir2 = base_path / "completely_different" / "path" / "structure"
    dir3 = base_path / "another" / "very" / "different" / "location"
    
    # Create directories
    dir1.mkdir(parents=True, exist_ok=True)
    dir2.mkdir(parents=True, exist_ok=True)
    dir3.mkdir(parents=True, exist_ok=True)
    
    # Create test files
    file1 = dir1 / "test1.txt"
    file2 = dir2 / "test2.txt"
    file3 = dir3 / "test3.txt"
    
    # Write content to files
    file1.write_text("Content for test1")
    file2.write_text("Content for test2")
    file3.write_text("Content for test3")
    
    # Create destination directory
    dest_dir = base_path / "destination"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    return {
        "base_dir": str(base_dir),
        "file1": str(file1),
        "file2": str(file2),
        "file3": str(file3),
        "dest_dir": str(dest_dir),
        "files": [str(file1), str(file2), str(file3)]
    }

def run_test(test_dirs):
    """Run the preserve copy operation with relative path mode."""
    print(f"Running copy operation with files from diverse locations...")
    print(f"File 1: {test_dirs['file1']}")
    print(f"File 2: {test_dirs['file2']}")
    print(f"File 3: {test_dirs['file3']}")
    print(f"Destination: {test_dirs['dest_dir']}")
    
    # Create options for relative path mode
    options = {
        'path_style': 'relative',
        'include_base': False,
        'source_base': None,
        'overwrite': False,
        'preserve_attrs': True,
        'verify': True,
        'hash_algorithm': 'SHA256',
        'create_dazzlelinks': False,
        'dry_run': False
    }
    
    # Run the copy operation
    result = operations.copy_operation(
        source_files=test_dirs["files"],
        dest_base=test_dirs["dest_dir"],
        options=options
    )
    
    print(f"\nOperation result:")
    print(f"Succeeded: {result.success_count()}")
    print(f"Failed: {result.failure_count()}")
    print(f"Skipped: {result.skip_count()}")
    
    return result

def verify_results(test_dirs):
    """Verify that files are copied with directory structure preserved."""
    dest_dir = Path(test_dirs["dest_dir"])
    
    # Check for files in the destination directory
    print("\nChecking destination directory structure:")
    
    # Walk the directory and print all files
    all_files = []
    for root, dirs, files in os.walk(dest_dir):
        for file in files:
            rel_path = Path(root).relative_to(dest_dir)
            if rel_path == Path('.'):
                file_path = Path(file)
            else:
                file_path = rel_path / file
            all_files.append(str(file_path))
    
    print(f"Files found in destination: {all_files}")
    
    # Check if the structure is preserved (not flat)
    # If it's flat, all files would be directly in the destination directory
    is_flat = all(Path(f).parent == Path('.') for f in all_files)
    print(f"Structure is {'flat' if is_flat else 'preserved'}")
    
    # Check if at least some of our directory structure is preserved
    # We'll check if at least one file has a path depth > 1
    has_structure = any(len(Path(f).parts) > 1 for f in all_files)
    print(f"Directory structure is {'preserved' if has_structure else 'not preserved'}")
    
    return not is_flat and has_structure

def main():
    """Main function."""
    print("Testing relative path mode fallback behavior")
    print("===========================================")
    
    # Set up test directories
    test_dirs = setup_test_dirs()
    print(f"Created test directory: {test_dirs['base_dir']}")
    
    try:
        # Run the test
        result = run_test(test_dirs)
        
        # Verify results
        success = verify_results(test_dirs)
        
        if success:
            print("\nTEST PASSED: Directory structure was preserved!")
            return 0
        else:
            print("\nTEST FAILED: Directory structure was not preserved!")
            return 1
        
    finally:
        # Leave the test directory for manual inspection
        print(f"Test directory for manual inspection: {test_dirs['base_dir']}")
        # Uncomment to clean up
        # shutil.rmtree(test_dirs['base_dir'])

if __name__ == "__main__":
    sys.exit(main())