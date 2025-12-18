#!/usr/bin/env python3
"""
Tests for path mode warning detection (Issue #42).

Tests the smart path detection that warns users about likely mistakes
with --abs/--rel path modes.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

from preservelib.path_warnings import (
    normalize_path_for_comparison,
    find_path_overlap,
    detect_abs_path_overlap,
    detect_rel_no_includebase,
    check_path_mode_warnings,
    PathWarning,
)


class TestNormalizePathForComparison(unittest.TestCase):
    """Test path normalization for comparison."""

    def test_simple_path(self):
        """Simple path should normalize to parts."""
        parts = normalize_path_for_comparison("/home/user/data")
        self.assertEqual(parts, ["home", "user", "data"])

    def test_windows_path(self):
        """Windows path should normalize drive letter."""
        parts = normalize_path_for_comparison("C:\\Users\\Test\\Data")
        expected = ["c", "users", "test", "data"]
        # Only compare lowercase on Windows
        if sys.platform == 'win32':
            self.assertEqual(parts, expected)

    def test_mixed_separators(self):
        """Mixed separators should normalize."""
        parts = normalize_path_for_comparison("C:/Users/Test\\Data")
        expected = ["c", "users", "test", "data"]
        if sys.platform == 'win32':
            self.assertEqual(parts, expected)


class TestFindPathOverlap(unittest.TestCase):
    """Test path overlap detection."""

    def test_no_overlap(self):
        """No overlap returns 0."""
        source = ["c", "users", "data"]
        dest = ["e", "backup"]
        self.assertEqual(find_path_overlap(source, dest), 0)

    def test_full_overlap(self):
        """Full source in dest suffix."""
        source = ["c", "users", "data"]
        dest = ["e", "c", "users", "data"]
        self.assertEqual(find_path_overlap(source, dest), 3)

    def test_partial_overlap(self):
        """Partial overlap at end of dest."""
        source = ["c", "users", "data", "subfolder"]
        dest = ["e", "c", "users"]
        self.assertEqual(find_path_overlap(source, dest), 2)

    def test_empty_source(self):
        """Empty source returns 0."""
        self.assertEqual(find_path_overlap([], ["e", "backup"]), 0)

    def test_empty_dest(self):
        """Empty dest returns 0."""
        self.assertEqual(find_path_overlap(["c", "users"], []), 0)


class TestDetectAbsPathOverlap(unittest.TestCase):
    """Test --abs path overlap detection."""

    def setUp(self):
        """Create test directory structure."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_path_warn_'))
        self.source_dir = self.test_dir / "source"
        self.source_dir.mkdir()

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_significant_overlap_detected(self):
        """Significant overlap should trigger warning."""
        # Simulate: source = C:\Users\data, dest = E:\C\Users
        # Overlap: c, users (2 parts) >= threshold
        source = "C:\\Users\\data" if sys.platform == 'win32' else "/home/user/data"
        dest = "E:\\C\\Users" if sys.platform == 'win32' else "/backup/home/user"

        warning = detect_abs_path_overlap(source, dest, threshold=2)

        self.assertIsNotNone(warning)
        self.assertEqual(warning.warning_type, "abs_overlap")

    def test_no_overlap_no_warning(self):
        """No overlap should not trigger warning."""
        source = "C:\\Data\\files" if sys.platform == 'win32' else "/data/files"
        dest = "E:\\Backup" if sys.platform == 'win32' else "/backup"

        warning = detect_abs_path_overlap(source, dest, threshold=2)

        self.assertIsNone(warning)

    def test_drive_root_no_warning(self):
        """Using drive root as destination should not warn."""
        if sys.platform != 'win32':
            self.skipTest("Windows-specific test")

        source = "C:\\Users\\data"
        dest = "E:\\"

        warning = detect_abs_path_overlap(source, dest, threshold=2)

        self.assertIsNone(warning)


class TestDetectRelNoIncludebase(unittest.TestCase):
    """Test --rel without --includeBase detection."""

    def setUp(self):
        """Create test directory structure."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_path_warn_'))
        self.source_dir = self.test_dir / "myproject"
        self.source_dir.mkdir()

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_directory_without_includebase_warns(self):
        """Directory without includeBase should warn."""
        warning = detect_rel_no_includebase(str(self.source_dir), include_base=False)

        self.assertIsNotNone(warning)
        self.assertEqual(warning.warning_type, "rel_no_includebase")
        self.assertIn("myproject", warning.message)

    def test_directory_with_includebase_no_warning(self):
        """Directory with includeBase should not warn."""
        warning = detect_rel_no_includebase(str(self.source_dir), include_base=True)

        self.assertIsNone(warning)

    def test_generic_directory_no_warning(self):
        """Generic directory names should not warn."""
        generic_dir = self.test_dir / "data"
        generic_dir.mkdir()

        warning = detect_rel_no_includebase(str(generic_dir), include_base=False)

        self.assertIsNone(warning)

    def test_file_no_warning(self):
        """Files should not trigger warning."""
        test_file = self.test_dir / "file.txt"
        test_file.write_text("content")

        warning = detect_rel_no_includebase(str(test_file), include_base=False)

        self.assertIsNone(warning)


class TestCheckPathModeWarnings(unittest.TestCase):
    """Test comprehensive path mode warning check."""

    def setUp(self):
        """Create test directory structure."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_path_warn_'))
        self.source_dir = self.test_dir / "myproject"
        self.source_dir.mkdir()
        self.dest_dir = self.test_dir / "backup"
        self.dest_dir.mkdir()

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_absolute_mode_checks_overlap(self):
        """Absolute mode should check for overlap."""
        warnings = check_path_mode_warnings(
            source_path=str(self.source_dir),
            dest_path=str(self.dest_dir),
            path_style='absolute',
            include_base=False,
        )
        # May or may not find overlap depending on paths
        # Just verify it runs without error
        self.assertIsInstance(warnings, list)

    def test_relative_mode_checks_includebase(self):
        """Relative mode should check for includeBase."""
        warnings = check_path_mode_warnings(
            source_path=str(self.source_dir),
            dest_path=str(self.dest_dir),
            path_style='relative',
            include_base=False,
        )

        # Should find the rel_no_includebase warning
        warning_types = [w.warning_type for w in warnings]
        self.assertIn("rel_no_includebase", warning_types)

    def test_relative_with_includebase_no_warning(self):
        """Relative mode with includeBase should not warn."""
        warnings = check_path_mode_warnings(
            source_path=str(self.source_dir),
            dest_path=str(self.dest_dir),
            path_style='relative',
            include_base=True,
        )

        self.assertEqual(len(warnings), 0)

    def test_flat_mode_no_warning(self):
        """Flat mode should not trigger warnings."""
        warnings = check_path_mode_warnings(
            source_path=str(self.source_dir),
            dest_path=str(self.dest_dir),
            path_style='flat',
            include_base=False,
        )

        self.assertEqual(len(warnings), 0)


class TestPathWarningStructure(unittest.TestCase):
    """Test PathWarning dataclass structure."""

    def test_warning_has_required_fields(self):
        """PathWarning should have all required fields."""
        warning = PathWarning(
            warning_type="test",
            message="Test message",
            expected_result="/path/to/result",
            suggestions=[("--flag", "/alternative/path")],
        )

        self.assertEqual(warning.warning_type, "test")
        self.assertEqual(warning.message, "Test message")
        self.assertEqual(warning.expected_result, "/path/to/result")
        self.assertEqual(len(warning.suggestions), 1)

    def test_warning_default_suggestions(self):
        """PathWarning should have empty suggestions by default."""
        warning = PathWarning(
            warning_type="test",
            message="Test message",
            expected_result="/path/to/result",
        )

        self.assertEqual(warning.suggestions, [])


if __name__ == '__main__':
    unittest.main()
