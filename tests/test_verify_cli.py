"""
Tests for VERIFY CLI command functionality, including --src flag.
"""

import unittest
import tempfile
import shutil
import json
import argparse
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace
from io import StringIO

# Add parent directory to path
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preserve.preserve import handle_verify_operation
from dazzle_preservelib.manifest import PreserveManifest


class TestVerifyCliCommand(unittest.TestCase):
    """Test the VERIFY CLI command functionality."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_verify_cli_"))
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)

        # Create test directories
        self.source_dir = self.test_dir / "source"
        self.preserved_dir = self.test_dir / "preserved"
        self.source_dir.mkdir()
        self.preserved_dir.mkdir()

        # Create a proper logger for tests instead of MagicMock
        self.logger = logging.getLogger('test_verify_cli')
        self.logger.setLevel(logging.WARNING)  # Only show warnings/errors in tests

    def create_test_manifest(self, dest_dir, files_data):
        """Helper to create a test manifest in destination directory."""
        manifest_path = dest_dir / "preserve_manifest.json"
        manifest_data = {
            "manifest_version": 1,
            "created_at": "2025-01-01T00:00:00",
            "files": files_data,
            "operations": [{
                "type": "COPY",
                "timestamp": "2025-01-01T00:00:00",
                "options": {
                    "source_base": str(self.source_dir)
                }
            }]
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2))
        return manifest_path

    def create_test_files(self, source_content="original", preserved_content="original"):
        """Helper to create test files."""
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text(source_content)
        preserved_file.write_text(preserved_content)
        return source_file, preserved_file

    @patch('builtins.print')
    def test_verify_without_src_two_way(self, mock_print):
        """Test VERIFY without --src performs two-way verification."""
        # Create test files
        source_file, preserved_file = self.create_test_files()

        # Create manifest
        self.create_test_manifest(self.preserved_dir, {
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Create args object without src
        args = argparse.Namespace(
            dst=str(self.preserved_dir),
            src=None,  # No source specified
            manifest=None,
            manifest_number=None,
            list=False,
            hash=["SHA256"],
            report=None,
            verbose=False,
            check=None,  # New parameter
            auto=False,  # New parameter
            alt_src=None  # New parameter
        )

        # Mock the verification to succeed
        with patch('dazzle_preservelib.verification.find_and_verify_manifest') as mock_verify:
            # Use SimpleNamespace for manifest to avoid MagicMock directory creation
            manifest = SimpleNamespace(
                manifest_dir=self.preserved_dir,
                manifest_path=self.preserved_dir / "preserve_manifest.json"
            )
            result = MagicMock()
            result.verified_count = 1
            result.failed_count = 0
            result.not_found_count = 0
            mock_verify.return_value = (manifest, result)

            # Run verification
            retval = handle_verify_operation(args, self.logger)

            # Should use two-way verification
            mock_verify.assert_called_once()
            self.assertEqual(retval, 0)

        # Check output mentions two-way verification
        print_calls = [str(call) for call in mock_print.call_args_list]
        self.assertFalse(any("Three-way" in str(call) for call in print_calls))

    @patch('builtins.print')
    @patch('dazzle_preservelib.verification.verify_three_way')
    def test_verify_with_src_three_way(self, mock_verify_three_way, mock_print):
        """Test VERIFY with --src performs three-way verification."""
        # Create test files
        source_file, preserved_file = self.create_test_files()

        # Create manifest
        self.create_test_manifest(self.preserved_dir, {
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Create args object WITH src
        args = argparse.Namespace(
            dst=str(self.preserved_dir),
            src=str(self.source_dir),  # Source specified
            manifest=None,
            manifest_number=None,
            list=False,
            hash=["SHA256"],
            report=None,
            verbose=False,
            check=None,  # New parameter
            auto=False,  # New parameter
            alt_src=None  # New parameter
        )

        # Mock the three-way verification result
        mock_result = MagicMock()
        mock_file_result = SimpleNamespace(file_path=self.source_dir / "test.txt")
        mock_result.all_match = [mock_file_result]
        mock_result.source_modified = []
        mock_result.preserved_corrupted = []
        mock_result.errors = []
        mock_result.not_found = []
        mock_verify_three_way.return_value = mock_result

        # Run verification
        retval = handle_verify_operation(args, self.logger)

        # Should use three-way verification
        mock_verify_three_way.assert_called_once()
        self.assertEqual(retval, 0)

        # Check output mentions three-way verification
        print_calls = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(any("Three-way" in str(call) or "Three-Way" in str(call) for call in print_calls))

    @patch('builtins.print')
    def test_verify_src_not_exists_error(self, mock_print):
        """Test VERIFY with --src that doesn't exist shows error."""
        # Create only preserved files, no source
        preserved_file = self.preserved_dir / "test.txt"
        preserved_file.write_text("content")

        # Create manifest
        self.create_test_manifest(self.preserved_dir, {
            str(preserved_file): {
                "source_path": str(self.source_dir / "test.txt"),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Create args object with non-existent src
        args = argparse.Namespace(
            dst=str(self.preserved_dir),
            src=str(self.test_dir / "nonexistent"),  # Doesn't exist
            manifest=None,
            manifest_number=None,
            list=False,
            hash=["SHA256"],
            report=None,
            verbose=False,
            check=None,  # New parameter
            auto=False,  # New parameter
            alt_src=None  # New parameter
        )

        # Run verification
        retval = handle_verify_operation(args, self.logger)

        # Should return error code
        self.assertEqual(retval, 1)

        # With a real logger, we can't use assert_called()
        # The error is already validated by the return code (1)
        # and we can see it in the captured log output

    @patch('builtins.print')
    @patch('dazzle_preservelib.verification.verify_three_way')
    def test_verify_src_with_modified_files(self, mock_verify_three_way, mock_print):
        """Test VERIFY --src correctly reports modified source files."""
        # Create test files with different content
        source_file = self.source_dir / "test.txt"
        preserved_file = self.preserved_dir / "test.txt"
        source_file.write_text("modified content")
        preserved_file.write_text("original content")

        # Create manifest
        self.create_test_manifest(self.preserved_dir, {
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Create args object with src
        args = argparse.Namespace(
            dst=str(self.preserved_dir),
            src=str(self.source_dir),
            manifest=None,
            manifest_number=None,
            list=False,
            hash=["SHA256"],
            report=None,
            verbose=False,
            check=None,  # New parameter
            auto=False,  # New parameter
            alt_src=None  # New parameter
        )

        # Mock the three-way verification result with modified source
        mock_result = MagicMock()
        mock_result.all_match = []
        mock_file_result = SimpleNamespace(file_path=source_file)
        mock_result.source_modified = [mock_file_result]
        mock_result.preserved_corrupted = []
        mock_result.errors = []
        mock_result.not_found = []
        mock_verify_three_way.return_value = mock_result

        # Run verification
        retval = handle_verify_operation(args, self.logger)

        # Should still return 0 (source modification is not an error)
        self.assertEqual(retval, 0)

        # Check output reports source modification
        print_calls = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(any("Source modified" in str(call) or "source modified" in str(call)
                           for call in print_calls))

    @patch('builtins.print')
    @patch('dazzle_preservelib.verification.verify_three_way')
    def test_verify_src_with_corrupted_preserved(self, mock_verify_three_way, mock_print):
        """Test VERIFY --src correctly reports corrupted preserved files."""
        # Create test files
        source_file, preserved_file = self.create_test_files()

        # Create manifest
        self.create_test_manifest(self.preserved_dir, {
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Create args object with src
        args = argparse.Namespace(
            dst=str(self.preserved_dir),
            src=str(self.source_dir),
            manifest=None,
            manifest_number=None,
            list=False,
            hash=["SHA256"],
            report=None,
            verbose=False,
            check=None,  # New parameter
            auto=False,  # New parameter
            alt_src=None  # New parameter
        )

        # Mock the three-way verification result with corrupted preserved
        mock_result = MagicMock()
        mock_result.all_match = []
        mock_result.source_modified = []
        mock_file_result = SimpleNamespace(file_path=preserved_file)
        mock_result.preserved_corrupted = [mock_file_result]
        mock_result.errors = []
        mock_result.not_found = []
        mock_verify_three_way.return_value = mock_result

        # Run verification
        retval = handle_verify_operation(args, self.logger)

        # Should return 1 (corrupted preserved is an error)
        self.assertEqual(retval, 1)

        # Check output reports corruption
        print_calls = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(any("Preserved corrupted" in str(call) or "preserved corrupted" in str(call)
                           for call in print_calls))

    @patch('builtins.print')
    @patch('dazzle_preservelib.verification.verify_three_way')
    def test_verify_src_complex_difference(self, mock_verify_three_way, mock_print):
        """Test VERIFY --src correctly reports complex differences."""
        # Create test files
        source_file, preserved_file = self.create_test_files()

        # Create manifest
        self.create_test_manifest(self.preserved_dir, {
            str(preserved_file): {
                "source_path": str(source_file),
                "destination_path": str(preserved_file),
                "hashes": {"SHA256": "abc123"}
            }
        })

        # Create args object with src
        args = argparse.Namespace(
            dst=str(self.preserved_dir),
            src=str(self.source_dir),
            manifest=None,
            manifest_number=None,
            list=False,
            hash=["SHA256"],
            report=None,
            verbose=False,
            check=None,  # New parameter
            auto=False,  # New parameter
            alt_src=None  # New parameter
        )

        # Mock the three-way verification result with complex difference
        mock_error = SimpleNamespace(
            error_message=f"Complex difference: {source_file}",
            file_path=source_file
        )
        mock_result = MagicMock()
        mock_result.all_match = []
        mock_result.source_modified = []
        mock_result.preserved_corrupted = []
        mock_result.errors = [mock_error]
        mock_result.not_found = []
        mock_verify_three_way.return_value = mock_result

        # Run verification
        retval = handle_verify_operation(args, self.logger)

        # Should return 1 (complex difference is an error)
        self.assertEqual(retval, 1)

        # Check output reports errors (complex differences show up as errors)
        print_calls = [str(call) for call in mock_print.call_args_list]
        # Complex differences are reported as errors in the output
        self.assertTrue(any("error" in str(call).lower() or "fail" in str(call).lower()
                           for call in print_calls))


class TestVerifySourceAutoDetection(unittest.TestCase):
    """Test future auto-detection of source from manifest."""

    def test_extract_source_from_manifest(self):
        """Test extracting source location from manifest."""
        # This is a placeholder for future auto-detection functionality
        # When implemented, this should test:
        # 1. Extracting source_base from operations
        # 2. Finding common prefix from file source_paths
        # 3. Handling missing source information gracefully
        pass

    def test_verify_with_auto_flag(self):
        """Test VERIFY --auto flag for automatic source detection."""
        # This is a placeholder for future --auto flag functionality
        # When implemented, this should test:
        # 1. Auto-detecting source from manifest
        # 2. Performing three-way verification automatically
        # 3. Falling back to two-way if source not found
        pass


if __name__ == '__main__':
    unittest.main()