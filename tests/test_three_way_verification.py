"""
Tests for three-way verification functionality.
"""

import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directory to path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dazzle_preservelib.verification import (
    VerificationStatus,
    FileVerificationResult,
    ThreeWayVerificationResult,
    verify_three_way
)
from dazzle_preservelib.manifest import PreserveManifest


class TestThreeWayVerificationFunction(unittest.TestCase):
    """Test the verify_three_way function."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_three_way_"))
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

        # Create test directories
        self.source_dir = self.test_dir / "source"
        self.preserved_dir = self.test_dir / "preserved"
        self.source_dir.mkdir()
        self.preserved_dir.mkdir()

    def create_test_manifest(self, files_data):
        """Helper to create a test manifest."""
        manifest = PreserveManifest()
        manifest.manifest = {
            "files": files_data,
            "created_at": "2025-01-01T00:00:00",
            "manifest_version": 1
        }
        return manifest

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_all_files_match(self, mock_hash):
        """Test when all three versions match."""
        # Create test files
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("content")
        preserved_file.write_text("content")

        # Mock hash function to return same hash
        mock_hash.return_value = {"SHA256": "abc123"}

        # Create manifest with expected hash
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.all_match), 1)
        self.assertEqual(len(result.source_modified), 0)
        self.assertEqual(len(result.preserved_corrupted), 0)
        self.assertTrue(result.is_successful)

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_source_modified(self, mock_hash):
        """Test when source file is modified after preservation."""
        # Create test files
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("modified content")
        preserved_file.write_text("original content")

        # Mock hash function to return different hashes
        def hash_side_effect(file_path, algorithms):
            if "source" in str(file_path):
                return {"SHA256": "xyz789"}  # Modified
            else:
                return {"SHA256": "abc123"}  # Original

        mock_hash.side_effect = hash_side_effect

        # Create manifest with original hash
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.all_match), 0)
        self.assertEqual(len(result.source_modified), 1)
        self.assertEqual(len(result.preserved_corrupted), 0)
        self.assertFalse(result.is_successful)

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_preserved_corrupted(self, mock_hash):
        """Test when preserved file is corrupted."""
        # Create test files
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("original content")
        preserved_file.write_text("corrupted content")

        # Mock hash function to return different hashes
        def hash_side_effect(file_path, algorithms):
            if "preserved" in str(file_path):
                return {"SHA256": "xyz789"}  # Corrupted
            else:
                return {"SHA256": "abc123"}  # Original

        mock_hash.side_effect = hash_side_effect

        # Create manifest with original hash
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.all_match), 0)
        self.assertEqual(len(result.source_modified), 0)
        self.assertEqual(len(result.preserved_corrupted), 1)
        self.assertFalse(result.is_successful)

    def test_preserved_file_missing(self):
        """Test when preserved file doesn't exist."""
        # Create only source file
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("content")
        # preserved_file doesn't exist

        # Create manifest
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.not_found), 1)
        self.assertFalse(result.is_successful)

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_complex_difference(self, mock_hash):
        """Test when all three hashes are different."""
        # Create test files
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("source content")
        preserved_file.write_text("preserved content")

        # Mock hash function to return different hashes
        def hash_side_effect(file_path, algorithms):
            if "source" in str(file_path):
                return {"SHA256": "aaa111"}
            else:
                return {"SHA256": "bbb222"}

        mock_hash.side_effect = hash_side_effect

        # Create manifest with yet another hash
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "ccc333"}
            }
        })

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.errors), 1)
        self.assertFalse(result.is_successful)
        error = result.errors[0]
        self.assertIn("Complex difference", error.error_message)

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_multiple_files(self, mock_hash):
        """Test verification with multiple files having different states."""
        # Create test files
        files_data = {}

        # File 1: All match
        source1 = self.source_dir / "file1.txt"
        preserved1 = self.preserved_dir / "file1.txt"
        source1.write_text("content1")
        preserved1.write_text("content1")
        files_data[str(preserved1)] = {
            "source_path": str(source1),
            "destination_path": str(preserved1),
            "hashes": {"SHA256": "hash1"}
        }

        # File 2: Source modified
        source2 = self.source_dir / "file2.txt"
        preserved2 = self.preserved_dir / "file2.txt"
        source2.write_text("modified")
        preserved2.write_text("original")
        files_data[str(preserved2)] = {
            "source_path": str(source2),
            "destination_path": str(preserved2),
            "hashes": {"SHA256": "hash2"}
        }

        # Mock hash function
        def hash_side_effect(file_path, algorithms):
            path_str = str(file_path)
            if "file1" in path_str:
                return {"SHA256": "hash1"}
            elif "file2" in path_str:
                if "source" in path_str:
                    return {"SHA256": "modified_hash"}
                else:
                    return {"SHA256": "hash2"}
            return {}

        mock_hash.side_effect = hash_side_effect

        # Create manifest
        manifest = self.create_test_manifest(files_data)

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.all_match), 1)
        self.assertEqual(len(result.source_modified), 1)
        self.assertEqual(result.total_files, 2)
        self.assertFalse(result.is_successful)

    def test_no_hash_in_manifest(self):
        """Test when manifest has no hash information."""
        # Create test files
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("content")
        preserved_file.write_text("content")

        # Create manifest without hashes
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file)
                # No hashes field
            }
        })

        # Perform verification
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest
        )

        # Verify results
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0].status, VerificationStatus.SKIPPED)

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_progress_callback(self, mock_hash):
        """Test that progress callback is called correctly."""
        # Create test file
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("content")
        preserved_file.write_text("content")

        mock_hash.return_value = {"SHA256": "abc123"}

        # Create manifest
        manifest = self.create_test_manifest({
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Track progress calls
        progress_calls = []
        def progress_callback(current, total, file_name):
            progress_calls.append((current, total, file_name))

        # Perform verification with callback
        result = verify_three_way(
            source_path=self.source_dir,
            preserved_path=self.preserved_dir,
            manifest=manifest,
            progress_callback=progress_callback
        )

        # Verify callback was called
        self.assertGreater(len(progress_calls), 0)
        # Should have called with (0, 1, file) and (1, 1, "Complete")
        self.assertEqual(progress_calls[-1], (1, 1, "Complete"))


if __name__ == '__main__':
    unittest.main()