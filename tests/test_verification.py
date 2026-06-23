"""
Unit tests for the unified verification module.
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Add parent directory to path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dazzle_preservelib.verification import (
    VerificationStatus,
    FileVerificationResult,
    VerificationResult,
    ThreeWayVerificationResult,
    select_manifest,
    verify_file_against_manifest,
    verify_files_against_manifest,
    find_and_verify_manifest
)
from dazzle_preservelib.manifest import find_available_manifests


class TestVerificationResult(unittest.TestCase):
    """Test the VerificationResult class."""

    def test_verification_result_initialization(self):
        """Test VerificationResult initializes correctly."""
        result = VerificationResult()
        self.assertEqual(len(result.verified), 0)
        self.assertEqual(len(result.failed), 0)
        self.assertEqual(len(result.skipped), 0)
        self.assertEqual(result.total_files, 0)
        self.assertTrue(result.is_successful)

    def test_add_result(self):
        """Test adding file results to VerificationResult."""
        result = VerificationResult()

        # Add verified file
        verified = FileVerificationResult(
            file_path=Path("test.txt"),
            status=VerificationStatus.VERIFIED
        )
        result.add_result(verified)
        self.assertEqual(len(result.verified), 1)

        # Add failed file
        failed = FileVerificationResult(
            file_path=Path("failed.txt"),
            status=VerificationStatus.FAILED
        )
        result.add_result(failed)
        self.assertEqual(len(result.failed), 1)
        self.assertFalse(result.is_successful)

    def test_statistics(self):
        """Test VerificationResult statistics."""
        result = VerificationResult()

        # Add various results
        for i in range(5):
            result.add_result(FileVerificationResult(
                file_path=Path(f"verified_{i}.txt"),
                status=VerificationStatus.VERIFIED
            ))

        for i in range(2):
            result.add_result(FileVerificationResult(
                file_path=Path(f"failed_{i}.txt"),
                status=VerificationStatus.FAILED
            ))

        result.add_result(FileVerificationResult(
            file_path=Path("skipped.txt"),
            status=VerificationStatus.SKIPPED
        ))

        self.assertEqual(result.total_files, 8)
        self.assertEqual(result.success_rate, 5/8)

        summary = result.get_summary()
        self.assertEqual(summary["verified"], 5)
        self.assertEqual(summary["failed"], 2)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["total"], 8)


class TestManifestDiscovery(unittest.TestCase):
    """Test manifest discovery functions."""

    def setUp(self):
        """Set up test directory."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_verification_"))
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

    def test_find_manifests_empty_directory(self):
        """Test finding manifests in empty directory."""
        manifests = find_available_manifests(self.test_dir)
        self.assertEqual(manifests, [])

    def test_find_single_manifest(self):
        """Test finding single unnumbered manifest."""
        manifest_path = self.test_dir / "preserve_manifest.json"
        manifest_path.write_text('{"test": true}')

        manifests = find_available_manifests(self.test_dir)
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0][0], 0)  # Number
        self.assertEqual(manifests[0][1], manifest_path)  # Path
        self.assertIsNone(manifests[0][2])  # Description

    def test_find_numbered_manifests(self):
        """Test finding numbered manifests."""
        # Create numbered manifests
        (self.test_dir / "preserve_manifest_001.json").write_text('{}')
        (self.test_dir / "preserve_manifest_002__backup.json").write_text('{}')
        (self.test_dir / "preserve_manifest_003.json").write_text('{}')

        manifests = find_available_manifests(self.test_dir)
        self.assertEqual(len(manifests), 3)

        # Check ordering and descriptions
        self.assertEqual(manifests[0][0], 1)
        self.assertIsNone(manifests[0][2])

        self.assertEqual(manifests[1][0], 2)
        self.assertEqual(manifests[1][2], "backup")

        self.assertEqual(manifests[2][0], 3)
        self.assertIsNone(manifests[2][2])

    def test_find_mixed_manifests(self):
        """Test finding mix of numbered and unnumbered manifests."""
        (self.test_dir / "preserve_manifest.json").write_text('{}')
        (self.test_dir / "preserve_manifest_001.json").write_text('{}')
        (self.test_dir / "preserve_manifest_002.json").write_text('{}')

        manifests = find_available_manifests(self.test_dir)
        self.assertEqual(len(manifests), 3)

        # Should be sorted by number
        self.assertEqual(manifests[0][0], 0)
        self.assertEqual(manifests[1][0], 1)
        self.assertEqual(manifests[2][0], 2)


class TestManifestSelection(unittest.TestCase):
    """Test manifest selection logic."""

    def setUp(self):
        """Set up test directory with manifests."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_select_"))
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

        # Create test manifests
        (self.test_dir / "preserve_manifest_001.json").write_text('{}')
        (self.test_dir / "preserve_manifest_002.json").write_text('{}')
        (self.test_dir / "preserve_manifest_003.json").write_text('{}')

    def test_select_by_number(self):
        """Test selecting manifest by number."""
        manifest = select_manifest(self.test_dir, manifest_number=2)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.name, "preserve_manifest_002.json")

    def test_select_latest_by_default(self):
        """Test selecting latest manifest by default."""
        manifest = select_manifest(self.test_dir)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.name, "preserve_manifest_003.json")

    def test_select_explicit_path(self):
        """Test selecting manifest by explicit path."""
        explicit = self.test_dir / "custom_manifest.json"
        explicit.write_text('{}')

        manifest = select_manifest(self.test_dir, manifest_path=explicit)
        self.assertEqual(manifest, explicit)

    def test_select_nonexistent_number(self):
        """Test selecting non-existent manifest number."""
        manifest = select_manifest(self.test_dir, manifest_number=99)
        self.assertIsNone(manifest)

    def test_select_from_preserve_subdirectory(self):
        """Test fallback to .preserve subdirectory."""
        # Remove manifests from main directory
        for f in self.test_dir.glob("*.json"):
            f.unlink()

        # Create .preserve subdirectory with manifest
        preserve_dir = self.test_dir / ".preserve"
        preserve_dir.mkdir()
        (preserve_dir / "preserve_manifest.json").write_text('{}')

        manifest = select_manifest(self.test_dir)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest.parent.name, ".preserve")


class TestFileVerification(unittest.TestCase):
    """Test file verification functions."""

    def setUp(self):
        """Set up test files."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_verify_"))
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

        # Create test file
        self.test_file = self.test_dir / "test.txt"
        self.test_file.write_text("Test content")

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_verify_file_success(self, mock_hash):
        """Test successful file verification."""
        mock_hash.return_value = {"SHA256": "abc123"}

        manifest_entry = {
            "hashes": {"SHA256": "abc123"}
        }

        result = verify_file_against_manifest(
            file_path=self.test_file,
            manifest_entry=manifest_entry,
            base_path=self.test_dir
        )

        self.assertEqual(result.status, VerificationStatus.VERIFIED)
        self.assertEqual(result.expected_hash, "abc123")
        self.assertEqual(result.actual_hash, "abc123")

    @patch('dazzle_preservelib.verification.calculate_file_hash')
    def test_verify_file_hash_mismatch(self, mock_hash):
        """Test file verification with hash mismatch."""
        mock_hash.return_value = {"SHA256": "xyz789"}

        manifest_entry = {
            "hashes": {"SHA256": "abc123"}
        }

        result = verify_file_against_manifest(
            file_path=self.test_file,
            manifest_entry=manifest_entry,
            base_path=self.test_dir
        )

        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertEqual(result.expected_hash, "abc123")
        self.assertEqual(result.actual_hash, "xyz789")
        self.assertIn("Hash mismatch", result.error_message)

    def test_verify_file_not_found(self):
        """Test verification of non-existent file."""
        manifest_entry = {
            "hashes": {"SHA256": "abc123"}
        }

        result = verify_file_against_manifest(
            file_path=Path("nonexistent.txt"),
            manifest_entry=manifest_entry,
            base_path=self.test_dir
        )

        self.assertEqual(result.status, VerificationStatus.NOT_FOUND)
        self.assertIn("not found", result.error_message.lower())

    def test_verify_file_no_hash_in_manifest(self):
        """Test verification when manifest has no hash."""
        manifest_entry = {}

        result = verify_file_against_manifest(
            file_path=self.test_file,
            manifest_entry=manifest_entry,
            base_path=self.test_dir
        )

        self.assertEqual(result.status, VerificationStatus.SKIPPED)
        self.assertIn("No hash information", result.error_message)

    def test_verify_file_old_format(self):
        """Test verification with old manifest format."""
        manifest_entry = {
            "hash": "abc123",
            "hash_algorithm": "SHA256"
        }

        with patch('dazzle_preservelib.verification.calculate_file_hash') as mock_hash:
            mock_hash.return_value = {"SHA256": "abc123"}

            result = verify_file_against_manifest(
                file_path=self.test_file,
                manifest_entry=manifest_entry,
                base_path=self.test_dir
            )

            self.assertEqual(result.status, VerificationStatus.VERIFIED)


class TestThreeWayVerification(unittest.TestCase):
    """Test three-way verification functionality."""

    def test_categorize_all_match(self):
        """Test categorization when all hashes match."""
        result = ThreeWayVerificationResult()

        file_result = result.categorize_difference(
            source_hash="abc123",
            preserved_hash="abc123",
            manifest_hash="abc123",
            file_path=Path("test.txt")
        )

        self.assertEqual(file_result.status, VerificationStatus.VERIFIED)
        self.assertEqual(len(result.all_match), 1)

    def test_categorize_source_modified(self):
        """Test categorization when source is modified."""
        result = ThreeWayVerificationResult()

        file_result = result.categorize_difference(
            source_hash="xyz789",
            preserved_hash="abc123",
            manifest_hash="abc123",
            file_path=Path("test.txt")
        )

        self.assertEqual(file_result.status, VerificationStatus.FAILED)
        self.assertEqual(len(result.source_modified), 1)
        self.assertIn("Source file modified", file_result.error_message)

    def test_categorize_preserved_corrupted(self):
        """Test categorization when preserved file is corrupted."""
        result = ThreeWayVerificationResult()

        file_result = result.categorize_difference(
            source_hash="abc123",
            preserved_hash="xyz789",
            manifest_hash="abc123",
            file_path=Path("test.txt")
        )

        self.assertEqual(file_result.status, VerificationStatus.FAILED)
        self.assertEqual(len(result.preserved_corrupted), 1)
        self.assertIn("Preserved file corrupted", file_result.error_message)

    def test_categorize_both_different(self):
        """Test categorization when all three hashes differ."""
        result = ThreeWayVerificationResult()

        file_result = result.categorize_difference(
            source_hash="aaa111",
            preserved_hash="bbb222",
            manifest_hash="ccc333",
            file_path=Path("test.txt")
        )

        self.assertEqual(file_result.status, VerificationStatus.ERROR)
        # categorize_difference doesn't add to errors list anymore, caller must use add_result
        result.add_result(file_result)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Complex difference", file_result.error_message)


if __name__ == '__main__':
    unittest.main()