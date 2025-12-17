#!/usr/bin/env python3
"""
Manual test script for link creation functionality.

This script creates a full workflow test:
1. Create test source directory with files
2. Run MOVE with --create-link junction
3. Verify junction was created
4. Run RESTORE to verify it detects and removes the junction
5. Clean up

Run this script manually to test the full link workflow:
    python tests/one-offs/test_link_manual.py

This is NOT part of the automated test suite.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from preservelib import links


def create_test_structure(base_dir: Path) -> Path:
    """Create a test directory structure."""
    source = base_dir / 'source'
    source.mkdir()

    # Create some files
    (source / 'file1.txt').write_text('Content of file 1')
    (source / 'file2.txt').write_text('Content of file 2')

    subdir = source / 'subdir'
    subdir.mkdir()
    (subdir / 'nested.txt').write_text('Nested content')

    return source


def test_link_creation():
    """Test basic link creation."""
    print("="*60)
    print("TEST: Basic Link Creation")
    print("="*60)

    with tempfile.TemporaryDirectory(prefix='preserve_link_test_') as tmpdir:
        tmpdir = Path(tmpdir)
        target = tmpdir / 'target'
        link_path = tmpdir / 'link'

        target.mkdir()
        (target / 'test.txt').write_text('test')

        print(f"\nTarget: {target}")
        print(f"Link:   {link_path}")

        # Create junction on Windows, soft link on Unix
        link_type = 'junction' if os.name == 'nt' else 'soft'
        print(f"\nCreating {link_type} link...")

        success, actual_type, error = links.create_link(
            link_path=link_path,
            target_path=target,
            link_type=link_type
        )

        if success:
            print(f"SUCCESS: Created {actual_type} link")

            # Verify link
            print(f"\nVerifying link...")
            print(f"  is_link: {links.is_link(link_path)}")
            print(f"  detect_type: {links.detect_link_type(link_path)}")
            print(f"  get_target: {links.get_link_target(link_path)}")

            # Access through link
            content = (link_path / 'test.txt').read_text()
            print(f"  content through link: {content}")

            # Remove link
            print(f"\nRemoving link...")
            success, error = links.remove_link(link_path)
            if success:
                print(f"SUCCESS: Link removed")
                print(f"  Target still exists: {target.exists()}")
                print(f"  Target content intact: {(target / 'test.txt').read_text()}")
            else:
                print(f"FAILED: {error}")
        else:
            print(f"FAILED: {error}")


def test_move_with_link():
    """Test MOVE operation with --create-link."""
    print("\n" + "="*60)
    print("TEST: MOVE with --create-link")
    print("="*60)

    # This test requires running the actual CLI
    print("\nTo test MOVE with --create-link, run:")
    print("")
    print("  # Create test directory")
    print("  mkdir test-runs\\link_test_source")
    print("  echo test > test-runs\\link_test_source\\file.txt")
    print("")
    print("  # Run MOVE with link creation")
    print("  python -m preserve MOVE test-runs\\link_test_source -r --abs \\")
    print("      --dst test-runs\\link_test_dest -L junction")
    print("")
    print("  # Verify junction was created")
    print("  dir test-runs\\link_test_source")
    print("")
    print("  # Test RESTORE")
    print("  python -m preserve RESTORE --src test-runs\\link_test_dest --dry-run")
    print("")


def test_auto_link_type():
    """Test auto link type selection."""
    print("\n" + "="*60)
    print("TEST: Auto Link Type Selection")
    print("="*60)

    with tempfile.TemporaryDirectory(prefix='preserve_auto_test_') as tmpdir:
        tmpdir = Path(tmpdir)
        target = tmpdir / 'target'
        link_path = tmpdir / 'link'

        target.mkdir()

        print(f"\nPlatform: {os.name}")
        print(f"Creating link with type='auto'...")

        success, actual_type, error = links.create_link(
            link_path=link_path,
            target_path=target,
            link_type='auto',
            is_directory=True
        )

        if success:
            print(f"SUCCESS: Auto selected '{actual_type}'")

            # Clean up
            links.remove_link(link_path)
        else:
            print(f"FAILED: {error}")


def main():
    print("Preserve Link Functionality Manual Test")
    print("="*60)
    print(f"Platform: {sys.platform}")
    print(f"Python: {sys.version}")
    print("")

    try:
        test_link_creation()
        test_auto_link_type()
        test_move_with_link()

        print("\n" + "="*60)
        print("Manual tests completed!")
        print("="*60)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
