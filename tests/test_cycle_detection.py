#!/usr/bin/env python3
"""
Tests for path cycle detection (Issue #47).

Tests the safety checks that prevent catastrophic data loss when
source and destination resolve to the same location via symlinks/junctions.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

from preservelib.operations import detect_path_cycle, preflight_checks


class TestDetectPathCycle(unittest.TestCase):
    """Test the detect_path_cycle function directly."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_cycle_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()

        # Create a test file in source
        (self.src / "test.txt").write_text("test content")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_no_cycle_separate_paths(self):
        """No cycle when source and destination are completely separate."""
        issues = detect_path_cycle([str(self.src)], str(self.dst))
        self.assertEqual(issues, [])

    def test_no_cycle_nonexistent_destination(self):
        """No cycle when destination doesn't exist yet."""
        new_dst = self.test_dir / "new_destination"
        issues = detect_path_cycle([str(self.src)], str(new_dst))
        self.assertEqual(issues, [])

    def test_same_path_detected(self):
        """Detect when source and destination are literally the same path."""
        issues = detect_path_cycle([str(self.src)], str(self.src))
        self.assertEqual(len(issues), 1)
        self.assertIn("CRITICAL", issues[0])
        self.assertIn("same location", issues[0])

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_junction_cycle_detected(self):
        """Detect cycle when destination is a junction pointing to source."""
        junction = self.test_dir / "junction_to_src"

        # Create junction: junction_to_src -> source
        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(junction), str(self.src)],
            capture_output=True
        )

        if result.returncode != 0:
            self.skipTest("Could not create junction (may need admin)")

        try:
            issues = detect_path_cycle([str(self.src)], str(junction))
            self.assertEqual(len(issues), 1)
            self.assertIn("CRITICAL", issues[0])
            self.assertIn("same location", issues[0])
        finally:
            # Clean up junction
            if junction.exists():
                junction.rmdir()

    @unittest.skipIf(sys.platform == 'win32', "Symlink test may require admin on Windows")
    def test_symlink_cycle_detected(self):
        """Detect cycle when destination is a symlink pointing to source."""
        symlink = self.test_dir / "symlink_to_src"
        symlink.symlink_to(self.src)

        issues = detect_path_cycle([str(self.src)], str(symlink))
        self.assertEqual(len(issues), 1)
        self.assertIn("CRITICAL", issues[0])
        self.assertIn("same location", issues[0])

    def test_destination_inside_source_detected(self):
        """Detect when destination is inside source directory."""
        nested_dst = self.src / "backup"
        nested_dst.mkdir()

        issues = detect_path_cycle([str(self.src)], str(nested_dst))
        self.assertEqual(len(issues), 1)
        self.assertIn("CRITICAL", issues[0])
        self.assertIn("inside source", issues[0])

    def test_source_inside_destination_detected(self):
        """Detect when source is inside destination directory."""
        nested_src = self.dst / "data"
        nested_src.mkdir()
        (nested_src / "file.txt").write_text("content")

        issues = detect_path_cycle([str(nested_src)], str(self.dst))
        self.assertEqual(len(issues), 1)
        self.assertIn("WARNING", issues[0])
        self.assertIn("inside destination", issues[0])

    def test_multiple_sources_checked(self):
        """All sources are checked, not just the first one."""
        # Create another source that's inside destination
        nested_src = self.dst / "nested"
        nested_src.mkdir()

        issues = detect_path_cycle(
            [str(self.src), str(nested_src)],  # Second source is problematic
            str(self.dst)
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("nested", issues[0])


class TestPreflightCycleIntegration(unittest.TestCase):
    """Test that preflight_checks properly integrates cycle detection."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_preflight_cycle_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "test.txt").write_text("test content")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_move_same_path_blocked(self):
        """MOVE with same source/destination is blocked (hard issue)."""
        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(self.src),
            operation="MOVE"
        )
        self.assertFalse(all_ok)
        self.assertTrue(any("CRITICAL" in issue for issue in hard_issues))

    def test_copy_same_path_blocked(self):
        """COPY with same source/destination is also blocked."""
        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(self.src),
            operation="COPY"
        )
        self.assertFalse(all_ok)
        self.assertTrue(any("same location" in issue for issue in hard_issues))

    def test_move_dest_inside_source_blocked(self):
        """MOVE with destination inside source is blocked."""
        nested_dst = self.src / "backup"
        nested_dst.mkdir()

        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(nested_dst),
            operation="MOVE"
        )
        self.assertFalse(all_ok)
        self.assertTrue(any("inside source" in issue for issue in hard_issues))

    def test_copy_dest_inside_source_warning(self):
        """COPY with destination inside source is a warning, not blocking."""
        nested_dst = self.src / "backup"
        nested_dst.mkdir()

        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(nested_dst),
            operation="COPY"
        )
        # Should be soft issue for COPY (not blocking)
        self.assertTrue(any("inside source" in issue for issue in soft_issues))

    def test_source_inside_dest_warning(self):
        """Source inside destination is a warning for both COPY and MOVE."""
        nested_src = self.dst / "data"
        nested_src.mkdir()
        (nested_src / "file.txt").write_text("content")

        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(nested_src)],
            str(self.dst),
            operation="COPY"
        )
        self.assertTrue(any("inside destination" in issue for issue in soft_issues))

    def test_no_cycle_passes(self):
        """Normal separate paths pass preflight checks."""
        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(self.dst),
            operation="MOVE"
        )
        # Should pass (no cycle issues)
        cycle_issues = [i for i in hard_issues + soft_issues if "CRITICAL" in i or "inside" in i]
        self.assertEqual(cycle_issues, [])


if __name__ == '__main__':
    unittest.main()
