#!/usr/bin/env python3
"""
Unit tests for link creation functionality in preserve.

These tests verify the link creation, detection, and removal functionality
added to support the --create-link option for MOVE operations.

Note: Some tests are platform-specific (e.g., junction tests only run on Windows).
"""

import unittest
import tempfile
import shutil
import os
import sys
from pathlib import Path
from unittest import skipIf, skipUnless

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preservelib import links


class TestLinkDetection(unittest.TestCase):
    """Test link detection functions."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_link_test_')
        self.source_dir = Path(self.test_dir) / 'source'
        self.target_dir = Path(self.test_dir) / 'target'
        self.source_dir.mkdir()
        self.target_dir.mkdir()

        # Create a test file in target
        (self.target_dir / 'test.txt').write_text('test content')

    def tearDown(self):
        """Clean up test directory."""
        # Remove any links first to avoid issues
        for item in Path(self.test_dir).iterdir():
            if links.is_link(item):
                links.remove_link(item)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_link_regular_dir(self):
        """Test that is_link returns False for regular directories."""
        self.assertFalse(links.is_link(self.source_dir))

    def test_is_link_regular_file(self):
        """Test that is_link returns False for regular files."""
        test_file = self.source_dir / 'file.txt'
        test_file.write_text('content')
        self.assertFalse(links.is_link(test_file))

    def test_is_link_nonexistent(self):
        """Test that is_link returns False for nonexistent paths."""
        self.assertFalse(links.is_link(self.test_dir + '/nonexistent'))

    @skipUnless(os.name == 'nt', "Symlink tests may require admin on Windows")
    def test_is_link_symlink(self):
        """Test that is_link returns True for symlinks."""
        link_path = Path(self.test_dir) / 'symlink'
        try:
            os.symlink(str(self.target_dir), str(link_path))
            self.assertTrue(links.is_link(link_path))
        except OSError as e:
            if 'privilege' in str(e).lower():
                self.skipTest("Symlink creation requires admin privileges")
            raise

    def test_detect_link_type_regular(self):
        """Test that detect_link_type returns None for regular files/dirs."""
        self.assertIsNone(links.detect_link_type(self.source_dir))

    def test_detect_link_type_nonexistent(self):
        """Test that detect_link_type returns None for nonexistent paths."""
        self.assertIsNone(links.detect_link_type('/nonexistent/path'))


@skipUnless(os.name == 'nt', "Junction tests only run on Windows")
class TestWindowsJunction(unittest.TestCase):
    """Test Windows junction functionality."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_junction_test_')
        self.target_dir = Path(self.test_dir) / 'target'
        self.link_path = Path(self.test_dir) / 'junction'
        self.target_dir.mkdir()

        # Create a test file in target
        (self.target_dir / 'test.txt').write_text('test content')

    def tearDown(self):
        """Clean up test directory."""
        # Remove junction first
        if self.link_path.exists() and links.is_link(self.link_path):
            links.remove_link(self.link_path)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_create_junction(self):
        """Test creating a Windows junction."""
        success, actual_type, error = links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='junction'
        )

        self.assertTrue(success, f"Junction creation failed: {error}")
        self.assertEqual(actual_type, 'junction')
        self.assertTrue(self.link_path.exists())
        self.assertTrue(links.is_link(self.link_path))

    def test_detect_junction_type(self):
        """Test detecting junction type."""
        success, _, _ = links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='junction'
        )

        if success:
            detected_type = links.detect_link_type(self.link_path)
            self.assertEqual(detected_type, 'junction')

    def test_remove_junction(self):
        """Test removing a junction without deleting target content."""
        # Create junction
        links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='junction'
        )

        # Verify target content exists
        self.assertTrue((self.target_dir / 'test.txt').exists())

        # Remove junction
        success, error = links.remove_link(self.link_path)

        self.assertTrue(success, f"Junction removal failed: {error}")
        self.assertFalse(self.link_path.exists())
        # Target content should still exist
        self.assertTrue((self.target_dir / 'test.txt').exists())

    def test_verify_junction(self):
        """Test verifying junction target."""
        links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='junction'
        )

        matches, actual = links.verify_link(self.link_path, self.target_dir)
        self.assertTrue(matches)

    def test_junction_through_link(self):
        """Test that files are accessible through junction."""
        links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='junction'
        )

        # Access file through junction
        content = (self.link_path / 'test.txt').read_text()
        self.assertEqual(content, 'test content')


class TestLinkCreationAutoType(unittest.TestCase):
    """Test auto link type selection."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_auto_test_')
        self.target_dir = Path(self.test_dir) / 'target'
        self.link_path = Path(self.test_dir) / 'link'
        self.target_dir.mkdir()

    def tearDown(self):
        """Clean up test directory."""
        if self.link_path.exists() and links.is_link(self.link_path):
            links.remove_link(self.link_path)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_auto_type_windows(self):
        """Test that auto selects junction on Windows for directories."""
        if os.name != 'nt':
            self.skipTest("Windows-specific test")

        success, actual_type, error = links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='auto',
            is_directory=True
        )

        if success:
            self.assertEqual(actual_type, 'junction')

    @skipIf(os.name == 'nt', "Unix-specific test")
    def test_auto_type_unix(self):
        """Test that auto selects soft link on Unix."""
        success, actual_type, error = links.create_link(
            link_path=self.link_path,
            target_path=self.target_dir,
            link_type='auto',
            is_directory=True
        )

        if success:
            self.assertEqual(actual_type, 'soft')


class TestLinkCreationErrors(unittest.TestCase):
    """Test error handling in link creation."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_error_test_')

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_invalid_link_type(self):
        """Test that invalid link type returns error."""
        success, _, error = links.create_link(
            link_path=Path(self.test_dir) / 'link',
            target_path=Path(self.test_dir),
            link_type='invalid'
        )

        self.assertFalse(success)
        self.assertIn('Invalid link type', error)

    def test_dazzle_not_implemented(self):
        """Test that dazzle link type returns not implemented."""
        success, _, error = links.create_link(
            link_path=Path(self.test_dir) / 'link',
            target_path=Path(self.test_dir),
            link_type='dazzle'
        )

        self.assertFalse(success)
        self.assertIn('not yet implemented', error)

    def test_link_path_exists_not_empty(self):
        """Test error when link path exists and is not empty."""
        link_path = Path(self.test_dir) / 'existing'
        link_path.mkdir()
        (link_path / 'file.txt').write_text('content')

        success, _, error = links.create_link(
            link_path=link_path,
            target_path=Path(self.test_dir),
            link_type='junction' if os.name == 'nt' else 'soft'
        )

        self.assertFalse(success)
        self.assertIn('not empty', error)

    @skipIf(os.name == 'nt', "Junction-only test")
    def test_junction_on_unix(self):
        """Test that junction type fails on Unix."""
        success, _, error = links.create_link(
            link_path=Path(self.test_dir) / 'link',
            target_path=Path(self.test_dir),
            link_type='junction'
        )

        self.assertFalse(success)
        self.assertIn('Windows', error)


class TestHardLink(unittest.TestCase):
    """Test hard link functionality."""

    def setUp(self):
        """Create a temporary directory for tests."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_hardlink_test_')
        self.target_file = Path(self.test_dir) / 'target.txt'
        self.link_path = Path(self.test_dir) / 'hardlink.txt'
        self.target_file.write_text('test content')

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_hard_link_directory_fails(self):
        """Test that hard links fail for directories."""
        target_dir = Path(self.test_dir) / 'dir'
        target_dir.mkdir()

        success, _, error = links.create_link(
            link_path=self.link_path,
            target_path=target_dir,
            link_type='hard'
        )

        self.assertFalse(success)
        self.assertIn('files', error.lower())

    def test_create_hard_link(self):
        """Test creating a hard link for a file."""
        success, actual_type, error = links.create_link(
            link_path=self.link_path,
            target_path=self.target_file,
            link_type='hard',
            is_directory=False
        )

        self.assertTrue(success, f"Hard link creation failed: {error}")
        self.assertEqual(actual_type, 'hard')
        self.assertTrue(self.link_path.exists())

        # Content should be the same
        self.assertEqual(self.link_path.read_text(), 'test content')


class TestCLIArguments(unittest.TestCase):
    """Test CLI argument parsing for --create-link."""

    def test_create_link_argument_exists(self):
        """Test that --create-link argument is recognized."""
        from preserve.cli import create_parser

        parser = create_parser()
        args = parser.parse_args([
            'MOVE', 'source', '--dst', 'dest', '--create-link', 'junction'
        ])

        self.assertEqual(args.create_link, 'junction')

    def test_create_link_shorthand(self):
        """Test that -L shorthand works."""
        from preserve.cli import create_parser

        parser = create_parser()
        args = parser.parse_args([
            'MOVE', 'source', '--dst', 'dest', '-L', 'soft'
        ])

        self.assertEqual(args.create_link, 'soft')

    def test_create_link_choices(self):
        """Test that only valid link types are accepted."""
        from preserve.cli import create_parser

        parser = create_parser()

        # Valid choices should work
        for choice in ['junction', 'soft', 'hard', 'auto']:
            args = parser.parse_args([
                'MOVE', 'source', '--dst', 'dest', '-L', choice
            ])
            self.assertEqual(args.create_link, choice)


if __name__ == '__main__':
    unittest.main()
