#!/usr/bin/env python3
"""
Unit tests for disk space checking functionality.

Tests the pre-flight disk space validation added to prevent
partial transfers due to insufficient disk space.
"""

import unittest
import tempfile
import shutil
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preservelib.operations import (
    calculate_total_size,
    check_disk_space,
    check_write_permission,
    check_source_permissions,
    preflight_checks,
    InsufficientSpaceError,
    PermissionCheckError,
    _format_size,
)


class TestFormatSize(unittest.TestCase):
    """Test the _format_size helper function."""

    def test_bytes(self):
        """Test formatting bytes."""
        self.assertEqual(_format_size(500), "500 bytes")
        self.assertEqual(_format_size(0), "0 bytes")

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        result = _format_size(1024)
        self.assertIn("KB", result)

    def test_megabytes(self):
        """Test formatting megabytes."""
        result = _format_size(1024 * 1024)
        self.assertIn("MB", result)

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        result = _format_size(1024 * 1024 * 1024)
        self.assertIn("GB", result)

    def test_terabytes(self):
        """Test formatting terabytes."""
        result = _format_size(1024 * 1024 * 1024 * 1024)
        self.assertIn("TB", result)


class TestCalculateTotalSize(unittest.TestCase):
    """Test the calculate_total_size function."""

    def setUp(self):
        """Create temporary test files."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_space_test_')

        # Create test files with known sizes
        self.file1 = Path(self.test_dir) / 'file1.txt'
        self.file1.write_text('A' * 100)  # 100 bytes

        self.file2 = Path(self.test_dir) / 'file2.txt'
        self.file2.write_text('B' * 200)  # 200 bytes

        self.file3 = Path(self.test_dir) / 'subdir' / 'file3.txt'
        self.file3.parent.mkdir()
        self.file3.write_text('C' * 300)  # 300 bytes

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_single_file(self):
        """Test calculating size of single file."""
        total = calculate_total_size([self.file1])
        self.assertEqual(total, 100)

    def test_multiple_files(self):
        """Test calculating size of multiple files."""
        total = calculate_total_size([self.file1, self.file2, self.file3])
        self.assertEqual(total, 600)  # 100 + 200 + 300

    def test_empty_list(self):
        """Test calculating size of empty list."""
        total = calculate_total_size([])
        self.assertEqual(total, 0)

    def test_nonexistent_file(self):
        """Test that nonexistent files are skipped."""
        total = calculate_total_size([
            self.file1,
            Path(self.test_dir) / 'nonexistent.txt',
            self.file2
        ])
        self.assertEqual(total, 300)  # Only existing files counted

    def test_directory_ignored(self):
        """Test that directories are ignored (only files counted)."""
        total = calculate_total_size([
            self.file1,
            Path(self.test_dir) / 'subdir',  # Directory, not a file
        ])
        self.assertEqual(total, 100)  # Only file1 counted


class TestCheckDiskSpace(unittest.TestCase):
    """Test the check_disk_space function."""

    def setUp(self):
        """Create temporary test directory."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_space_test_')

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sufficient_space(self):
        """Test that check passes with sufficient space."""
        # Request a small amount that should always be available
        status, recommended, available, message = check_disk_space(
            self.test_dir,
            required_bytes=1024,  # 1 KB
            safety_margin=0.05
        )
        self.assertEqual(status, "OK")
        self.assertIn("OK", message)

    def test_returns_available_space(self):
        """Test that available space is returned."""
        _, _, available, _ = check_disk_space(self.test_dir, 1024)
        self.assertGreater(available, 0)

    def test_recommended_free_uses_absolute_minimum(self):
        """Test that recommended free space uses absolute minimum for small transfers."""
        # For small transfers, 1GB absolute minimum should be used
        status, recommended, _, _ = check_disk_space(
            self.test_dir,
            required_bytes=1000,  # 1 KB transfer
            safety_margin=0.05  # 5%
        )
        # 5% of 1000 = 50 bytes, but minimum is 1GB
        self.assertEqual(recommended, 1 * 1024 * 1024 * 1024)  # 1GB minimum

    def test_recommended_free_uses_percentage_for_large_transfers(self):
        """Test that recommended free uses percentage for large transfers."""
        # For large transfers, percentage should exceed absolute minimum
        large_transfer = 100 * 1024 * 1024 * 1024  # 100GB
        status, recommended, _, _ = check_disk_space(
            self.test_dir,
            required_bytes=large_transfer,
            safety_margin=0.05  # 5%
        )
        # 5% of 100GB = 5GB, which exceeds 1GB minimum
        expected = int(large_transfer * 0.05)
        self.assertEqual(recommended, expected)

    def test_nonexistent_path_uses_parent(self):
        """Test that nonexistent path checks parent directory."""
        nonexistent = Path(self.test_dir) / 'does' / 'not' / 'exist'
        status, _, available, _ = check_disk_space(nonexistent, 1024)
        # Should still work by finding existing parent
        self.assertEqual(status, "OK")
        self.assertGreater(available, 0)

    def test_message_format(self):
        """Test that message contains expected information."""
        _, _, _, message = check_disk_space(self.test_dir, 1024)
        # Message should contain size information
        self.assertTrue(
            "available" in message.lower() or
            "OK" in message or
            "WARNING" in message
        )

    def test_status_values(self):
        """Test that status returns valid values."""
        status, _, _, _ = check_disk_space(self.test_dir, 1024)
        self.assertIn(status, ["OK", "SOFT_WARNING", "HARD_FAIL"])


class TestInsufficientSpaceError(unittest.TestCase):
    """Test the InsufficientSpaceError exception."""

    def test_error_message(self):
        """Test that error message contains relevant info."""
        error = InsufficientSpaceError(
            required=1024 * 1024 * 1024,  # 1 GB
            available=512 * 1024 * 1024,   # 512 MB
            destination="/test/path"
        )
        message = str(error)
        self.assertIn("/test/path", message)
        self.assertIn("GB", message)
        self.assertIn("MB", message)

    def test_error_attributes(self):
        """Test that error has expected attributes."""
        error = InsufficientSpaceError(
            required=1000,
            available=500,
            destination="/test"
        )
        self.assertEqual(error.required, 1000)
        self.assertEqual(error.available, 500)
        self.assertEqual(error.destination, "/test")


class TestIntegration(unittest.TestCase):
    """Integration tests for space checking."""

    def setUp(self):
        """Create temporary test directory with files."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_space_test_')
        self.source_dir = Path(self.test_dir) / 'source'
        self.dest_dir = Path(self.test_dir) / 'dest'
        self.source_dir.mkdir()
        self.dest_dir.mkdir()

        # Create test files
        self.files = []
        for i in range(5):
            f = self.source_dir / f'file{i}.txt'
            f.write_text('X' * 1000)
            self.files.append(f)

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_workflow(self):
        """Test complete workflow: calculate size then check space."""
        # Calculate total size of files
        total_size = calculate_total_size(self.files)
        self.assertEqual(total_size, 5000)

        # Check if destination has space
        status, recommended, available, message = check_disk_space(
            self.dest_dir,
            total_size,
            safety_margin=0.05
        )

        # Should pass for this small amount
        self.assertEqual(status, "OK")
        # recommended should be 1GB minimum (since 5% of 5000 is tiny)
        self.assertEqual(recommended, 1 * 1024 * 1024 * 1024)


class TestCheckWritePermission(unittest.TestCase):
    """Test the check_write_permission function."""

    def setUp(self):
        """Create temporary test directory."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_perm_test_')

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_writable_directory(self):
        """Test that writable directory passes check."""
        has_perm, message = check_write_permission(self.test_dir)
        self.assertTrue(has_perm)
        self.assertIn("verified", message.lower())

    def test_nonexistent_uses_parent(self):
        """Test that nonexistent path checks parent directory."""
        nonexistent = Path(self.test_dir) / 'does' / 'not' / 'exist'
        has_perm, message = check_write_permission(nonexistent)
        # Should pass if parent (test_dir) is writable
        self.assertTrue(has_perm)


class TestCheckSourcePermissions(unittest.TestCase):
    """Test the check_source_permissions function."""

    def setUp(self):
        """Create temporary test files."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_src_test_')
        self.file1 = Path(self.test_dir) / 'file1.txt'
        self.file1.write_text('content')

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_readable_files(self):
        """Test that readable files pass check."""
        all_ok, errors = check_source_permissions([self.file1])
        self.assertTrue(all_ok)
        self.assertEqual(len(errors), 0)

    def test_nonexistent_file(self):
        """Test that nonexistent files are reported."""
        nonexistent = Path(self.test_dir) / 'nonexistent.txt'
        all_ok, errors = check_source_permissions([nonexistent])
        self.assertFalse(all_ok)
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])


class TestPreflightChecks(unittest.TestCase):
    """Test the combined preflight_checks function."""

    def setUp(self):
        """Create temporary test structure."""
        self.test_dir = tempfile.mkdtemp(prefix='preserve_preflight_test_')
        self.source_dir = Path(self.test_dir) / 'source'
        self.dest_dir = Path(self.test_dir) / 'dest'
        self.source_dir.mkdir()
        self.dest_dir.mkdir()

        # Create test files
        self.files = []
        for i in range(3):
            f = self.source_dir / f'file{i}.txt'
            f.write_text('X' * 100)
            self.files.append(f)

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_all_checks_pass(self):
        """Test that all checks pass for valid setup."""
        all_ok, hard_issues, soft_issues, space_status = preflight_checks(
            source_files=self.files,
            dest_path=self.dest_dir,
            operation="COPY"
        )
        self.assertTrue(all_ok)
        self.assertEqual(len(hard_issues), 0)
        # Soft issues may exist (low space warning) but shouldn't block
        self.assertIn(space_status, ["OK", "SOFT_WARNING", ""])

    def test_move_checks_delete_permission(self):
        """Test that MOVE operation checks delete permissions."""
        all_ok, hard_issues, soft_issues, space_status = preflight_checks(
            source_files=self.files,
            dest_path=self.dest_dir,
            operation="MOVE"
        )
        # Should pass for normal files in user temp directory
        self.assertTrue(all_ok)
        self.assertEqual(len(hard_issues), 0)

    def test_nonexistent_source_fails(self):
        """Test that nonexistent source files cause failure."""
        nonexistent = Path(self.test_dir) / 'nonexistent.txt'
        all_ok, hard_issues, soft_issues, space_status = preflight_checks(
            source_files=[nonexistent],
            dest_path=self.dest_dir,
            operation="COPY"
        )
        self.assertFalse(all_ok)
        self.assertGreater(len(hard_issues), 0)

    def test_returns_space_status(self):
        """Test that space_status is returned."""
        all_ok, hard_issues, soft_issues, space_status = preflight_checks(
            source_files=self.files,
            dest_path=self.dest_dir,
            operation="COPY"
        )
        self.assertIn(space_status, ["OK", "SOFT_WARNING", "HARD_FAIL"])


class TestPermissionCheckError(unittest.TestCase):
    """Test the PermissionCheckError exception."""

    def test_error_message(self):
        """Test that error message contains relevant info."""
        error = PermissionCheckError(
            path="/test/path",
            operation="MOVE",
            details="Access denied",
            is_admin_required=True
        )
        message = str(error)
        self.assertIn("/test/path", message)
        self.assertIn("MOVE", message)
        self.assertIn("Access denied", message)

    def test_error_attributes(self):
        """Test that error has expected attributes."""
        error = PermissionCheckError(
            path="/test",
            operation="COPY",
            details="Test error",
            is_admin_required=False
        )
        self.assertEqual(error.path, "/test")
        self.assertEqual(error.operation, "COPY")
        self.assertEqual(error.details, "Test error")
        self.assertFalse(error.is_admin_required)


if __name__ == '__main__':
    unittest.main()
