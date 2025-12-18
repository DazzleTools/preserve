#!/usr/bin/env python3
"""
Tests for CLEANUP operation (0.7.x - Issue #43).

Tests the CLEANUP command which helps recover from partial MOVE operations.
"""

import os
import sys
import unittest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime

from preserve.handlers.cleanup import (
    CleanupStatus,
    analyze_cleanup_status,
    format_cleanup_report,
)


class TestCleanupStatus(unittest.TestCase):
    """Test CleanupStatus class."""

    def test_empty_status(self):
        """Empty status should show complete."""
        status = CleanupStatus()
        self.assertTrue(status.is_complete())
        self.assertFalse(status.needs_recovery())
        self.assertEqual(status.total_manifest_files(), 0)

    def test_source_only_needs_recovery(self):
        """Files at source only need recovery."""
        status = CleanupStatus()
        status.source_only = [Path("/some/file.txt")]
        self.assertFalse(status.is_complete())
        self.assertTrue(status.needs_recovery())

    def test_both_exist_needs_recovery(self):
        """Files at both locations need recovery."""
        status = CleanupStatus()
        status.both_exist = [(Path("/src/file.txt"), Path("/dst/file.txt"), "verified")]
        self.assertFalse(status.is_complete())
        self.assertTrue(status.needs_recovery())

    def test_dest_only_is_complete(self):
        """Files only at destination means move is complete."""
        status = CleanupStatus()
        status.dest_only = [(Path("/src/file.txt"), Path("/dst/file.txt"))]
        self.assertTrue(status.is_complete())
        self.assertFalse(status.needs_recovery())


class TestAnalyzeCleanupStatus(unittest.TestCase):
    """Test analyze_cleanup_status function."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_cleanup_'))
        self.src_dir = self.test_dir / "src"
        self.dst_dir = self.test_dir / "dst"
        self.src_dir.mkdir()
        self.dst_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_manifest(self, files, operation_type="MOVE"):
        """Create a test manifest file using PreserveManifest class."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()

        # Add operation
        manifest.add_operation(
            operation_type=operation_type,
            source_path=str(self.src_dir),
            destination_path=str(self.dst_dir),
        )

        # Add files
        for file_entry in files:
            source_path = file_entry.get("source_path", "")
            dest_path = file_entry.get("dest_path", "") or file_entry.get("destination_path", "")
            manifest.add_file(
                source_path=source_path,
                destination_path=dest_path,
            )
            # Add hash if provided
            if "hashes" in file_entry:
                for algo, hash_val in file_entry["hashes"].items():
                    manifest.add_file_hash(dest_path, algo, hash_val)

        # Save manifest
        manifest_path = self.dst_dir / "preserve_manifest.json"
        manifest.save(manifest_path)

        return manifest_path

    def test_analyze_complete_move(self):
        """Analyze a completed move (files only at destination)."""
        # Create file only at destination
        dst_file = self.dst_dir / "file.txt"
        dst_file.write_text("content")

        manifest_path = self._create_manifest([{
            "source_path": str(self.src_dir / "file.txt"),
            "dest_path": str(dst_file),
        }])

        status, manifest = analyze_cleanup_status(manifest_path)

        self.assertEqual(len(status.dest_only), 1)
        self.assertEqual(len(status.source_only), 0)
        self.assertTrue(status.is_complete())

    def test_analyze_partial_move(self):
        """Analyze a partial move (files still at source)."""
        # Create file only at source
        src_file = self.src_dir / "file.txt"
        src_file.write_text("content")

        manifest_path = self._create_manifest([{
            "source_path": str(src_file),
            "dest_path": str(self.dst_dir / "file.txt"),
        }])

        status, manifest = analyze_cleanup_status(manifest_path)

        self.assertEqual(len(status.source_only), 1)
        self.assertEqual(len(status.dest_only), 0)
        self.assertTrue(status.needs_recovery())

    def test_analyze_files_at_both_locations(self):
        """Analyze move with files at both locations."""
        # Create file at both locations
        src_file = self.src_dir / "file.txt"
        src_file.write_text("content")
        dst_file = self.dst_dir / "file.txt"
        dst_file.write_text("content")

        manifest_path = self._create_manifest([{
            "source_path": str(src_file),
            "dest_path": str(dst_file),
        }])

        status, manifest = analyze_cleanup_status(manifest_path)

        self.assertEqual(len(status.both_exist), 1)
        self.assertTrue(status.needs_recovery())

    def test_analyze_lost_files(self):
        """Analyze move with lost files (neither location)."""
        # No files created - both missing

        manifest_path = self._create_manifest([{
            "source_path": str(self.src_dir / "file.txt"),
            "dest_path": str(self.dst_dir / "file.txt"),
        }])

        status, manifest = analyze_cleanup_status(manifest_path)

        self.assertEqual(len(status.neither_exist), 1)
        self.assertTrue(status.needs_recovery())

    def test_analyze_detects_extra_dest_files(self):
        """Analyze should detect extra files at destination."""
        # Create a file at destination that's not in manifest
        dst_file = self.dst_dir / "extra.txt"
        dst_file.write_text("extra content")

        # Empty manifest - no tracked files
        manifest_path = self._create_manifest([])

        status, manifest = analyze_cleanup_status(manifest_path)

        self.assertEqual(len(status.extra_dest_files), 1)
        self.assertEqual(status.extra_dest_files[0].name, "extra.txt")


class TestFormatCleanupReport(unittest.TestCase):
    """Test format_cleanup_report function."""

    def test_format_empty_report(self):
        """Format report for empty status."""
        status = CleanupStatus()
        manifest = {
            "operation": {"type": "MOVE", "timestamp": "2025-01-01T00:00:00"},
            "dest_base": "/tmp/dst",
        }

        report = format_cleanup_report(status, manifest)

        self.assertIn("CLEANUP STATUS REPORT", report)
        self.assertIn("MOVE", report)
        self.assertIn("COMPLETE", report)

    def test_format_incomplete_report(self):
        """Format report for incomplete status."""
        status = CleanupStatus()
        status.source_only = [Path("/src/file.txt")]
        manifest = {
            "operation": {"type": "MOVE", "timestamp": "2025-01-01T00:00:00"},
            "dest_base": "/tmp/dst",
        }

        report = format_cleanup_report(status, manifest)

        self.assertIn("INCOMPLETE", report)
        self.assertIn("recovery needed", report)


class TestCleanupComplete(unittest.TestCase):
    """Test CLEANUP --mode complete functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_cleanup_complete_'))
        self.src_dir = self.test_dir / "src"
        self.dst_dir = self.test_dir / "dst"
        self.src_dir.mkdir()
        self.dst_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_manifest(self, files):
        """Create a test manifest file using PreserveManifest class."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()

        # Add operation
        manifest.add_operation(
            operation_type="MOVE",
            source_path=str(self.src_dir),
            destination_path=str(self.dst_dir),
        )

        # Add files
        for file_entry in files:
            source_path = file_entry.get("source_path", "")
            dest_path = file_entry.get("dest_path", "") or file_entry.get("destination_path", "")
            manifest.add_file(
                source_path=source_path,
                destination_path=dest_path,
            )

        # Save manifest
        manifest_path = self.dst_dir / "preserve_manifest.json"
        manifest.save(manifest_path)

        return manifest_path

    def test_complete_mode_status_detection(self):
        """Complete mode should correctly detect partial move state."""
        # Set up partial move: file only at source
        src_file = self.src_dir / "file.txt"
        src_file.write_text("content")

        manifest_path = self._create_manifest([{
            "source_path": str(src_file),
            "destination_path": str(self.dst_dir / "file.txt"),
        }])

        status, _ = analyze_cleanup_status(manifest_path)

        # Should need recovery
        self.assertTrue(status.needs_recovery())
        self.assertEqual(len(status.source_only), 1)


class TestCleanupRollback(unittest.TestCase):
    """Test CLEANUP --mode rollback functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_cleanup_rollback_'))
        self.src_dir = self.test_dir / "src"
        self.dst_dir = self.test_dir / "dst"
        self.src_dir.mkdir()
        self.dst_dir.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_manifest(self, files):
        """Create a test manifest file using PreserveManifest class."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()

        # Add operation
        manifest.add_operation(
            operation_type="MOVE",
            source_path=str(self.src_dir),
            destination_path=str(self.dst_dir),
        )

        # Add files
        for file_entry in files:
            source_path = file_entry.get("source_path", "")
            dest_path = file_entry.get("dest_path", "") or file_entry.get("destination_path", "")
            manifest.add_file(
                source_path=source_path,
                destination_path=dest_path,
            )

        # Save manifest
        manifest_path = self.dst_dir / "preserve_manifest.json"
        manifest.save(manifest_path)

        return manifest_path

    def test_rollback_mode_status_detection(self):
        """Rollback mode should correctly detect completed move state."""
        # Set up completed move: file only at destination
        dst_file = self.dst_dir / "file.txt"
        dst_file.write_text("content")

        manifest_path = self._create_manifest([{
            "source_path": str(self.src_dir / "file.txt"),
            "dest_path": str(dst_file),
        }])

        status, _ = analyze_cleanup_status(manifest_path)

        # Should have files at dest only (for rollback)
        self.assertEqual(len(status.dest_only), 1)
        self.assertTrue(status.is_complete())


if __name__ == '__main__':
    unittest.main()
