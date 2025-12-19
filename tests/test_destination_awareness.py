#!/usr/bin/env python3
"""
Tests for destination awareness features (0.7.x - Issue #39).

Tests the destination scanning infrastructure including:
- File categorization (identical, conflict, source-only, dest-only)
- Scan result formatting
- Conflict detection
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

from preservelib.destination import (
    scan_destination,
    compare_files,
    compute_destination_path,
    format_scan_report,
    FileCategory,
    ConflictResolution,
    FileComparison,
    DestinationScanResult,
    apply_conflict_resolution,
    generate_renamed_path,
)


class TestFileComparison(unittest.TestCase):
    """Test individual file comparison functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_dest_awareness_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_source_only_file(self):
        """File exists only at source."""
        src_file = self.src / "test.txt"
        src_file.write_text("hello")
        dst_file = self.dst / "test.txt"  # Does not exist

        result = compare_files(src_file, dst_file)
        self.assertEqual(result.category, FileCategory.SOURCE_ONLY)
        self.assertEqual(result.source_size, 5)
        self.assertEqual(result.dest_size, 0)

    def test_identical_files(self):
        """Files with same content should be IDENTICAL."""
        content = "identical content"
        src_file = self.src / "test.txt"
        src_file.write_text(content)
        dst_file = self.dst / "test.txt"
        dst_file.write_text(content)

        result = compare_files(src_file, dst_file)
        self.assertEqual(result.category, FileCategory.IDENTICAL)
        self.assertEqual(result.source_hash, result.dest_hash)

    def test_conflict_different_size(self):
        """Files with different sizes should be CONFLICT."""
        src_file = self.src / "test.txt"
        src_file.write_text("short")
        dst_file = self.dst / "test.txt"
        dst_file.write_text("much longer content")

        result = compare_files(src_file, dst_file, quick_check=True)
        self.assertEqual(result.category, FileCategory.CONFLICT)
        self.assertIn("Size differs", result.resolution_reason)

    def test_conflict_same_size_different_content(self):
        """Files with same size but different content should be CONFLICT."""
        src_file = self.src / "test.txt"
        src_file.write_text("aaaa")
        dst_file = self.dst / "test.txt"
        dst_file.write_text("bbbb")

        result = compare_files(src_file, dst_file)
        self.assertEqual(result.category, FileCategory.CONFLICT)
        self.assertNotEqual(result.source_hash, result.dest_hash)


class TestComputeDestinationPath(unittest.TestCase):
    """Test destination path computation for different path styles."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_dest_path_'))

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_flat_style(self):
        """Flat style should use only filename."""
        src = Path("/some/deep/path/file.txt")
        dst_base = self.test_dir / "dst"

        result = compute_destination_path(src, dst_base, path_style="flat")
        self.assertEqual(result, dst_base / "file.txt")

    @unittest.skipIf(sys.platform != "win32", "Windows-specific test")
    def test_absolute_style_windows(self):
        """Absolute style on Windows should include drive letter."""
        src = Path("C:/Users/test/file.txt")
        dst_base = self.test_dir / "dst"

        result = compute_destination_path(src, dst_base, path_style="absolute")
        self.assertIn("C", str(result))
        self.assertEqual(result.name, "file.txt")

    def test_relative_style_with_base(self):
        """Relative style with source base should strip base."""
        src_base = self.test_dir / "src"
        src_base.mkdir()
        subdir = src_base / "subdir"
        subdir.mkdir()
        src_file = subdir / "file.txt"
        src_file.write_text("test")

        dst_base = self.test_dir / "dst"

        result = compute_destination_path(
            src_file, dst_base, path_style="relative", source_base=src_base
        )
        self.assertEqual(result, dst_base / "subdir" / "file.txt")


class TestScanDestination(unittest.TestCase):
    """Test full destination scanning functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_scan_dest_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_destination(self):
        """Scanning empty destination should show all as source-only."""
        (self.src / "file1.txt").write_text("content1")
        (self.src / "file2.txt").write_text("content2")

        source_files = [self.src / "file1.txt", self.src / "file2.txt"]
        result = scan_destination(source_files, self.dst, path_style="flat")

        self.assertEqual(result.source_only_count, 2)
        self.assertEqual(result.identical_count, 0)
        self.assertEqual(result.conflict_count, 0)
        self.assertEqual(result.dest_only_count, 0)

    def test_all_identical(self):
        """Destination with all identical files."""
        (self.src / "file1.txt").write_text("content1")
        (self.dst / "file1.txt").write_text("content1")

        source_files = [self.src / "file1.txt"]
        result = scan_destination(source_files, self.dst, path_style="flat")

        self.assertEqual(result.source_only_count, 0)
        self.assertEqual(result.identical_count, 1)
        self.assertEqual(result.conflict_count, 0)

    def test_mixed_state(self):
        """Destination with mixed state: identical, conflict, source-only, dest-only."""
        # Identical
        (self.src / "identical.txt").write_text("same content")
        (self.dst / "identical.txt").write_text("same content")

        # Conflict
        (self.src / "conflict.txt").write_text("source version")
        (self.dst / "conflict.txt").write_text("different dest version")

        # Source only
        (self.src / "new.txt").write_text("new file")

        # Dest only
        (self.dst / "extra.txt").write_text("extra at dest")

        source_files = [
            self.src / "identical.txt",
            self.src / "conflict.txt",
            self.src / "new.txt",
        ]
        result = scan_destination(source_files, self.dst, path_style="flat")

        self.assertEqual(result.identical_count, 1)
        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.source_only_count, 1)
        self.assertEqual(result.dest_only_count, 1)

    def test_has_conflicts(self):
        """Test has_conflicts() helper."""
        (self.src / "file.txt").write_text("source")
        (self.dst / "file.txt").write_text("different")

        source_files = [self.src / "file.txt"]
        result = scan_destination(source_files, self.dst, path_style="flat")

        self.assertTrue(result.has_conflicts())

    def test_no_conflicts(self):
        """Test has_conflicts() returns False when no conflicts."""
        (self.src / "file.txt").write_text("content")

        source_files = [self.src / "file.txt"]
        result = scan_destination(source_files, self.dst, path_style="flat")

        self.assertFalse(result.has_conflicts())


class TestConflictResolution(unittest.TestCase):
    """Test conflict resolution strategies."""

    def test_skip_resolution(self):
        """Test SKIP resolution."""
        comparison = FileComparison(
            source_path=Path("src/file.txt"),
            dest_path=Path("dst/file.txt"),
            category=FileCategory.CONFLICT,
        )

        result = apply_conflict_resolution(comparison, ConflictResolution.SKIP)
        self.assertEqual(result.conflict_resolution, ConflictResolution.SKIP)
        self.assertIn("keeping destination", result.resolution_reason.lower())

    def test_overwrite_resolution(self):
        """Test OVERWRITE resolution."""
        comparison = FileComparison(
            source_path=Path("src/file.txt"),
            dest_path=Path("dst/file.txt"),
            category=FileCategory.CONFLICT,
        )

        result = apply_conflict_resolution(comparison, ConflictResolution.OVERWRITE)
        self.assertEqual(result.conflict_resolution, ConflictResolution.OVERWRITE)

    def test_newer_resolution_source_wins(self):
        """Test NEWER resolution when source is newer."""
        comparison = FileComparison(
            source_path=Path("src/file.txt"),
            dest_path=Path("dst/file.txt"),
            category=FileCategory.CONFLICT,
            source_mtime=1000.0,
            dest_mtime=500.0,
        )

        result = apply_conflict_resolution(comparison, ConflictResolution.NEWER)
        self.assertEqual(result.conflict_resolution, ConflictResolution.OVERWRITE)
        self.assertIn("newer", result.resolution_reason.lower())

    def test_newer_resolution_dest_wins(self):
        """Test NEWER resolution when dest is newer."""
        comparison = FileComparison(
            source_path=Path("src/file.txt"),
            dest_path=Path("dst/file.txt"),
            category=FileCategory.CONFLICT,
            source_mtime=500.0,
            dest_mtime=1000.0,
        )

        result = apply_conflict_resolution(comparison, ConflictResolution.NEWER)
        self.assertEqual(result.conflict_resolution, ConflictResolution.SKIP)

    def test_larger_resolution(self):
        """Test LARGER resolution."""
        comparison = FileComparison(
            source_path=Path("src/file.txt"),
            dest_path=Path("dst/file.txt"),
            category=FileCategory.CONFLICT,
            source_size=1000,
            dest_size=500,
        )

        result = apply_conflict_resolution(comparison, ConflictResolution.LARGER)
        self.assertEqual(result.conflict_resolution, ConflictResolution.OVERWRITE)


class TestGenerateRenamedPath(unittest.TestCase):
    """Test renamed path generation for conflict resolution."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_rename_'))

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_simple_rename(self):
        """Generate renamed path when original doesn't exist."""
        original = self.test_dir / "file.txt"
        renamed = generate_renamed_path(original)
        self.assertEqual(renamed, self.test_dir / "file_001.txt")

    def test_incremental_rename(self):
        """Generate incremental names when previous exist."""
        (self.test_dir / "file_001.txt").write_text("exists")
        (self.test_dir / "file_002.txt").write_text("exists")

        original = self.test_dir / "file.txt"
        renamed = generate_renamed_path(original)
        self.assertEqual(renamed, self.test_dir / "file_003.txt")


class TestFormatScanReport(unittest.TestCase):
    """Test scan report formatting."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_report_'))

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_basic_report_format(self):
        """Test basic report contains expected sections."""
        result = DestinationScanResult(dest_base=self.test_dir)
        result.total_source_files = 10
        result.source_only_count = 5
        result.identical_count = 3
        result.conflict_count = 2

        report = format_scan_report(result)

        self.assertIn("DESTINATION SCAN REPORT", report)
        self.assertIn("SUMMARY", report)
        self.assertIn("Files to copy", report)
        self.assertIn("Identical files", report)
        self.assertIn("Conflicts", report)

    def test_verbose_report_includes_details(self):
        """Test verbose report includes file listings."""
        result = DestinationScanResult(dest_base=self.test_dir)
        result.identical = [
            FileComparison(
                source_path=Path("src/file.txt"),
                dest_path=Path("dst/file.txt"),
                category=FileCategory.IDENTICAL,
                source_size=100,
            )
        ]
        result.update_counts()

        report = format_scan_report(result, verbose=True)

        self.assertIn("IDENTICAL FILES", report)


class TestScanDestinationIntegration(unittest.TestCase):
    """Integration tests for destination scanning with real files."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_scan_int_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_scan_preserves_manifest_files(self):
        """Manifest files should not appear in dest-only list."""
        (self.src / "file.txt").write_text("content")
        (self.dst / "preserve_manifest.json").write_text("{}")
        (self.dst / "file.dazzlelink").write_text("link")

        source_files = [self.src / "file.txt"]
        result = scan_destination(source_files, self.dst, path_style="flat")

        # Manifest and dazzlelink files should be excluded from dest-only
        self.assertEqual(result.dest_only_count, 0)

    def test_scan_with_subdirectories(self):
        """Test scanning with subdirectory structure."""
        # Create nested structure
        (self.src / "sub").mkdir()
        (self.src / "sub" / "file.txt").write_text("content")

        source_files = [self.src / "sub" / "file.txt"]
        result = scan_destination(
            source_files, self.dst, path_style="relative", source_base=self.src
        )

        self.assertEqual(result.source_only_count, 1)
        # Check computed path is correct
        expected_dest = self.dst / "sub" / "file.txt"
        self.assertEqual(result.source_only[0].dest_path, expected_dest)


class TestManifestV3Schema(unittest.TestCase):
    """Test manifest v3.0 schema features (DAG support)."""

    def test_manifest_id_generation(self):
        """New manifests should have a unique manifest_id."""
        from preservelib.manifest import PreserveManifest

        manifest1 = PreserveManifest()
        manifest2 = PreserveManifest()

        self.assertTrue(manifest1.get_manifest_id().startswith("pm-"))
        self.assertTrue(manifest2.get_manifest_id().startswith("pm-"))
        self.assertNotEqual(manifest1.get_manifest_id(), manifest2.get_manifest_id())

    def test_parent_ids_default_empty(self):
        """New manifests should have empty parent_ids array."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()
        self.assertEqual(manifest.get_parent_ids(), [])
        self.assertFalse(manifest.has_parents())

    def test_set_single_parent(self):
        """Test setting a single parent manifest."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()
        manifest.set_parent("pm-abc123")

        self.assertEqual(manifest.get_parent_ids(), ["pm-abc123"])
        self.assertTrue(manifest.has_parents())
        self.assertFalse(manifest.is_merge())

    def test_add_multiple_parents(self):
        """Test adding multiple parents (merge scenario)."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()
        manifest.add_parent("pm-abc123")
        manifest.add_parent("pm-def456")

        self.assertEqual(len(manifest.get_parent_ids()), 2)
        self.assertIn("pm-abc123", manifest.get_parent_ids())
        self.assertIn("pm-def456", manifest.get_parent_ids())
        self.assertTrue(manifest.is_merge())

    def test_lineage_info(self):
        """Test lineage helper fields."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()
        lineage = manifest.get_lineage()

        self.assertIn("root_id", lineage)
        self.assertIn("depth", lineage)
        self.assertIn("is_merge", lineage)

    def test_manifest_version_is_3(self):
        """New manifests should use version 3."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()
        self.assertEqual(manifest.manifest["manifest_version"], 3)

    def test_v2_manifest_migration(self):
        """Loading v2 manifest should add v3 fields."""
        import tempfile
        import json
        from preservelib.manifest import PreserveManifest

        # Create a v2-style manifest file
        v2_manifest = {
            "manifest_version": 2,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
            "operations": [],
            "files": {},
            "metadata": {}
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(v2_manifest, f)
            temp_path = f.name

        try:
            manifest = PreserveManifest(temp_path)

            # Should have v3 fields added
            self.assertIn("manifest_id", manifest.manifest)
            self.assertIn("parent_ids", manifest.manifest)
            self.assertIn("lineage", manifest.manifest)
            self.assertEqual(manifest.manifest["parent_ids"], [])
        finally:
            os.unlink(temp_path)


class TestIncorporateFile(unittest.TestCase):
    """Test file incorporation into manifest."""

    def test_incorporate_file_basic(self):
        """Test incorporating a file without copying."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()

        file_id = manifest.incorporate_file(
            file_id="dst/file.txt",
            source_path="src/file.txt",
            dest_path="dst/file.txt",
            hashes={"SHA256": "abc123"}
        )

        self.assertEqual(file_id, "dst/file.txt")
        self.assertIn("dst/file.txt", manifest.manifest["files"])

        file_entry = manifest.manifest["files"]["dst/file.txt"]
        self.assertTrue(file_entry["incorporated"])
        self.assertEqual(file_entry["hashes"]["SHA256"], "abc123")

    def test_incorporate_file_with_lineage(self):
        """Test incorporating a file with lineage info."""
        from preservelib.manifest import PreserveManifest

        manifest = PreserveManifest()

        manifest.incorporate_file(
            file_id="dst/file.txt",
            source_path="src/file.txt",
            dest_path="dst/file.txt",
            hashes={"SHA256": "abc123"},
            original_manifest_id="pm-original",
            original_source_path="/original/path/file.txt"
        )

        file_entry = manifest.manifest["files"]["dst/file.txt"]
        self.assertIn("lineage", file_entry)
        self.assertEqual(file_entry["lineage"]["original_manifest_id"], "pm-original")
        self.assertEqual(file_entry["lineage"]["original_source_path"], "/original/path/file.txt")


class TestOperationResultIncorporated(unittest.TestCase):
    """Test OperationResult incorporated file tracking."""

    def test_incorporated_count(self):
        """Test incorporated file counting."""
        from preservelib.operations import OperationResult

        result = OperationResult("COPY")
        self.assertEqual(result.incorporated_count(), 0)

        result.add_incorporated("src/file1.txt", "dst/file1.txt", 100)
        result.add_incorporated("src/file2.txt", "dst/file2.txt", 200)

        self.assertEqual(result.incorporated_count(), 2)
        self.assertEqual(result.incorporated_bytes, 300)

    def test_incorporated_in_total_count(self):
        """Incorporated files should be included in total count."""
        from preservelib.operations import OperationResult

        result = OperationResult("COPY")
        result.add_success("src/a.txt", "dst/a.txt", 100)
        result.add_incorporated("src/b.txt", "dst/b.txt", 100)
        result.add_skip("src/c.txt", "dst/c.txt", "reason")

        self.assertEqual(result.total_count(), 3)
        self.assertEqual(result.success_count(), 1)
        self.assertEqual(result.incorporated_count(), 1)
        self.assertEqual(result.skip_count(), 1)

    def test_get_summary_includes_incorporated(self):
        """Summary should include incorporated counts."""
        from preservelib.operations import OperationResult

        result = OperationResult("COPY")
        result.add_incorporated("src/file.txt", "dst/file.txt", 500)

        summary = result.get_summary()
        self.assertEqual(summary["incorporated_count"], 1)
        self.assertEqual(summary["incorporated_bytes"], 500)


class TestOnConflictSkip(unittest.TestCase):
    """Test --on-conflict=skip mode (default behavior)."""

    def setUp(self):
        """Set up test environment with conflicting files."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_conflict_skip_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

        # Create source file
        self.src_file = self.src / "file.txt"
        self.src_file.write_text("source content")

        # Create conflicting destination file
        self.dst_file = self.dst / "file.txt"
        self.dst_file.write_text("destination content")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_skip_preserves_destination(self):
        """Skip mode should preserve destination file."""
        from preservelib.operations import copy_operation

        result = copy_operation(
            source_files=[str(self.src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "skip",
                "verify": False,
            }
        )

        # Should skip the file
        self.assertEqual(result.skip_count(), 1)
        self.assertEqual(result.success_count(), 0)

        # Destination should be unchanged
        self.assertEqual(self.dst_file.read_text(), "destination content")

    def test_default_is_skip(self):
        """Default conflict behavior should be skip."""
        from preservelib.operations import copy_operation

        result = copy_operation(
            source_files=[str(self.src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "verify": False,
            }
        )

        # Should skip (default behavior)
        self.assertEqual(result.skip_count(), 1)
        self.assertEqual(self.dst_file.read_text(), "destination content")


class TestOnConflictOverwrite(unittest.TestCase):
    """Test --on-conflict=overwrite mode."""

    def setUp(self):
        """Set up test environment with conflicting files."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_conflict_overwrite_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

        # Create source file
        self.src_file = self.src / "file.txt"
        self.src_file.write_text("source content")

        # Create conflicting destination file
        self.dst_file = self.dst / "file.txt"
        self.dst_file.write_text("destination content")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_overwrite_replaces_destination(self):
        """Overwrite mode should replace destination file."""
        from preservelib.operations import copy_operation

        result = copy_operation(
            source_files=[str(self.src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "overwrite",
                "verify": False,
            }
        )

        # Should succeed
        self.assertEqual(result.success_count(), 1)
        self.assertEqual(result.skip_count(), 0)

        # Destination should have source content
        self.assertEqual(self.dst_file.read_text(), "source content")

    def test_legacy_overwrite_flag(self):
        """Legacy --overwrite flag should work like --on-conflict=overwrite."""
        from preservelib.operations import copy_operation

        result = copy_operation(
            source_files=[str(self.src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "overwrite": True,  # Legacy flag
                "verify": False,
            }
        )

        # Should succeed
        self.assertEqual(result.success_count(), 1)
        self.assertEqual(self.dst_file.read_text(), "source content")


class TestOnConflictNewer(unittest.TestCase):
    """Test --on-conflict=newer mode."""

    def setUp(self):
        """Set up test environment with conflicting files."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_conflict_newer_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_newer_source_overwrites(self):
        """Newer source should overwrite destination."""
        import time
        from preservelib.operations import copy_operation

        # Create destination first (older)
        dst_file = self.dst / "file.txt"
        dst_file.write_text("old content")

        # Wait a moment
        time.sleep(0.1)

        # Create source (newer)
        src_file = self.src / "file.txt"
        src_file.write_text("new content")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "newer",
                "verify": False,
            }
        )

        # Source is newer, should overwrite
        self.assertEqual(result.success_count(), 1)
        self.assertEqual(result.skip_count(), 0)
        self.assertEqual(dst_file.read_text(), "new content")

    def test_newer_destination_skips(self):
        """Newer destination should be preserved."""
        import time
        from preservelib.operations import copy_operation

        # Create source first (older)
        src_file = self.src / "file.txt"
        src_file.write_text("old content")

        # Wait a moment
        time.sleep(0.1)

        # Create destination (newer)
        dst_file = self.dst / "file.txt"
        dst_file.write_text("new content")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "newer",
                "verify": False,
            }
        )

        # Destination is newer, should skip
        self.assertEqual(result.skip_count(), 1)
        self.assertEqual(result.success_count(), 0)
        self.assertEqual(dst_file.read_text(), "new content")


class TestOnConflictLarger(unittest.TestCase):
    """Test --on-conflict=larger mode."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_conflict_larger_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_larger_source_overwrites(self):
        """Larger source should overwrite destination."""
        from preservelib.operations import copy_operation

        # Create smaller destination
        dst_file = self.dst / "file.txt"
        dst_file.write_text("small")

        # Create larger source
        src_file = self.src / "file.txt"
        src_file.write_text("much larger content here")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "larger",
                "verify": False,
            }
        )

        # Source is larger, should overwrite
        self.assertEqual(result.success_count(), 1)
        self.assertEqual(dst_file.read_text(), "much larger content here")

    def test_larger_destination_skips(self):
        """Larger destination should be preserved."""
        from preservelib.operations import copy_operation

        # Create larger destination
        dst_file = self.dst / "file.txt"
        dst_file.write_text("much larger content here")

        # Create smaller source
        src_file = self.src / "file.txt"
        src_file.write_text("small")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "larger",
                "verify": False,
            }
        )

        # Destination is larger, should skip
        self.assertEqual(result.skip_count(), 1)
        self.assertEqual(dst_file.read_text(), "much larger content here")


class TestOnConflictRename(unittest.TestCase):
    """Test --on-conflict=rename mode."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_conflict_rename_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_rename_keeps_both(self):
        """Rename mode should keep both files."""
        from preservelib.operations import copy_operation

        # Create destination file
        dst_file = self.dst / "file.txt"
        dst_file.write_text("original")

        # Create source file
        src_file = self.src / "file.txt"
        src_file.write_text("new content")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "rename",
                "verify": False,
            }
        )

        # Should succeed
        self.assertEqual(result.success_count(), 1)
        self.assertEqual(result.skip_count(), 0)

        # Original should be unchanged
        self.assertEqual(dst_file.read_text(), "original")

        # Renamed file should exist
        renamed_file = self.dst / "file_001.txt"
        self.assertTrue(renamed_file.exists())
        self.assertEqual(renamed_file.read_text(), "new content")

    def test_rename_increments_counter(self):
        """Rename should increment counter for multiple conflicts."""
        from preservelib.operations import copy_operation

        # Create destination files
        dst_file = self.dst / "file.txt"
        dst_file.write_text("original")

        # Also create file_001.txt to force increment
        existing_renamed = self.dst / "file_001.txt"
        existing_renamed.write_text("already renamed once")

        # Create source file
        src_file = self.src / "file.txt"
        src_file.write_text("new content")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "rename",
                "verify": False,
            }
        )

        # Should succeed
        self.assertEqual(result.success_count(), 1)

        # Should be file_002.txt since file_001.txt exists
        renamed_file = self.dst / "file_002.txt"
        self.assertTrue(renamed_file.exists())
        self.assertEqual(renamed_file.read_text(), "new content")


class TestOnConflictFail(unittest.TestCase):
    """Test --on-conflict=fail mode."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_conflict_fail_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_fail_aborts_on_conflict(self):
        """Fail mode should abort operation on conflict."""
        from preservelib.operations import copy_operation

        # Create destination file (conflict)
        dst_file = self.dst / "file.txt"
        dst_file.write_text("original")

        # Create source file
        src_file = self.src / "file.txt"
        src_file.write_text("new content")

        result = copy_operation(
            source_files=[str(src_file)],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "fail",
                "verify": False,
            }
        )

        # Should fail
        self.assertEqual(result.failure_count(), 1)
        self.assertEqual(result.success_count(), 0)

        # Destination should be unchanged
        self.assertEqual(dst_file.read_text(), "original")

    def test_fail_stops_processing(self):
        """Fail mode should stop processing remaining files."""
        from preservelib.operations import copy_operation

        # Create first file with conflict
        (self.dst / "a.txt").write_text("original a")
        (self.src / "a.txt").write_text("new a")

        # Create second file (no conflict)
        (self.src / "b.txt").write_text("new b")

        result = copy_operation(
            source_files=[str(self.src / "a.txt"), str(self.src / "b.txt")],
            dest_base=str(self.dst),
            options={
                "path_style": "flat",
                "on_conflict": "fail",
                "verify": False,
            }
        )

        # Should fail on first file
        self.assertEqual(result.failure_count(), 1)

        # Second file should not have been copied (operation aborted)
        self.assertFalse((self.dst / "b.txt").exists())


class TestScanOnlyNoSideEffects(unittest.TestCase):
    """Test that --scan-only mode has no filesystem side effects."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_scan_only_'))
        self.src = self.test_dir / "src"
        self.dst = self.test_dir / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_scan_only_does_not_migrate_manifest(self):
        """--scan-only should not trigger manifest migration.

        Bug: get_manifest_path() was migrating preserve_manifest.json to
        preserve_manifest_001.json even during --scan-only operations.
        This violates the read-only contract of scan-only mode.
        """
        from preserve.utils import get_manifest_path
        from argparse import Namespace

        # Create a single manifest (simulating first operation completed)
        manifest = self.dst / "preserve_manifest.json"
        manifest.write_text('{"version": "3.0", "files": {}}')

        # Create args with scan_only=True
        args = Namespace(
            dst=str(self.dst),
            manifest=None,
            no_manifest=False,
            scan_only=True,
        )

        # Call get_manifest_path - this should NOT migrate the manifest
        result_path = get_manifest_path(args, self.dst)

        # Original manifest should still exist (not renamed)
        self.assertTrue(manifest.exists(),
            "preserve_manifest.json should NOT be migrated during --scan-only")

        # Should not have created _001
        self.assertFalse((self.dst / "preserve_manifest_001.json").exists(),
            "preserve_manifest_001.json should NOT be created during --scan-only")

        # Return path should be what WOULD be used for next operation
        self.assertEqual(result_path.name, "preserve_manifest_002.json",
            "Should return _002 path (what would be used if not scan-only)")

    def test_scan_only_with_no_existing_manifest(self):
        """--scan-only with no existing manifest should not create one."""
        from preserve.utils import get_manifest_path
        from argparse import Namespace

        # No manifest exists
        args = Namespace(
            dst=str(self.dst),
            manifest=None,
            no_manifest=False,
            scan_only=True,
        )

        # Call get_manifest_path
        result_path = get_manifest_path(args, self.dst)

        # Should return path for first manifest
        self.assertEqual(result_path.name, "preserve_manifest.json")

        # But should NOT have created it
        self.assertFalse(result_path.exists(),
            "Manifest file should NOT be created during --scan-only")


if __name__ == '__main__':
    unittest.main()
