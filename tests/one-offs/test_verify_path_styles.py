#!/usr/bin/env python3
"""
Test VERIFY operation with different path preservation styles.

This test ensures VERIFY works correctly with:
- Relative paths (--rel)
- Absolute paths (--abs)
- Flat structure (--flat)
"""

import os
import sys
import shutil
import json
import subprocess
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class VerifyPathStylesTest:
    """Test VERIFY with different path preservation styles."""

    def __init__(self, test_dir=None):
        """Initialize the test."""
        if test_dir:
            self.test_dir = Path(test_dir)
        else:
            # Use existing test data or generate new
            test_runs = Path("test-runs")
            if not test_runs.exists():
                # Run generate_test_data.py to create test structure
                import subprocess
                result = subprocess.run(
                    [sys.executable, "tests/generate_test_data.py"],
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(f"Failed to generate test data: {result.stderr}")

            # Find the most recent test directory
            test_dirs = sorted([
                d for d in test_runs.iterdir()
                if d.is_dir() and d.name.startswith("test_")
            ])
            if not test_dirs:
                raise RuntimeError("No test directories found. Run generate_test_data.py first.")
            self.test_dir = test_dirs[-1]

        print(f"Using test directory: {self.test_dir}")
        self.passed = 0
        self.failed = 0

        # Verify we have the expected test structure
        source = self.test_dir / "source"
        if not source.exists():
            raise RuntimeError(f"Source directory not found in {self.test_dir}")

        # List available source directories for reference
        print(f"  Available test data:")
        for item in self.test_dir.iterdir():
            if item.is_dir() and not item.name.startswith("dest"):
                file_count = sum(1 for _ in item.rglob("*") if _.is_file())
                print(f"    - {item.name}: {file_count} files")

    def run_command(self, cmd):
        """Run a preserve command."""
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return result

    def assert_success(self, result, test_name):
        """Assert command succeeded."""
        if result.returncode == 0:
            print(f"  [PASS] {test_name}")
            self.passed += 1
            return True
        else:
            print(f"  [FAIL] {test_name}")
            print(f"    stdout: {result.stdout}")
            print(f"    stderr: {result.stderr}")
            self.failed += 1
            return False

    def verify_file_structure(self, dest_path, expected_files, test_name):
        """Verify the file structure matches expectations."""
        dest = Path(dest_path)
        found_files = set()

        for root, dirs, files in os.walk(dest):
            for file in files:
                if file != "preserve_manifest.json" and not file.startswith("preserve_manifest_"):
                    file_path = Path(root) / file
                    relative = file_path.relative_to(dest)
                    found_files.add(str(relative).replace("\\", "/"))

        expected = set(expected_files)

        if found_files == expected:
            print(f"  [PASS] {test_name}: File structure correct")
            self.passed += 1
            return True
        else:
            print(f"  [FAIL] {test_name}: File structure mismatch")
            print(f"    Expected: {sorted(expected)}")
            print(f"    Found:    {sorted(found_files)}")
            missing = expected - found_files
            extra = found_files - expected
            if missing:
                print(f"    Missing:  {sorted(missing)}")
            if extra:
                print(f"    Extra:    {sorted(extra)}")
            self.failed += 1
            return False

    def test_relative_paths(self):
        """Test VERIFY with relative path preservation (--rel)."""
        print("\n[TEST] VERIFY with relative paths (--rel)")

        source = self.test_dir / "source"
        dest = self.test_dir / "dest_relative"
        if dest.exists():
            shutil.rmtree(dest)

        # Copy with relative paths
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --rel'
        result = self.run_command(cmd)
        self.assert_success(result, "COPY with --rel")

        # Expected structure with relative paths
        # Based on the standard test structure from generate_test_data.py
        expected_files = [
            "config.json",
            "large_file.txt",
            "readme.txt",
            "documents/notes.md",
            "documents/report.txt",
            "media/data.dat",
            "media/image.bin",
            "project/src/components/main.py",
            "project/src/components/utils.py",
            "special_chars/file with spaces.txt",
            "special_chars/file-with-dashes.txt"
        ]
        self.verify_file_structure(dest, expected_files, "Relative path structure")

        # Verify the files
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.assert_success(result, "VERIFY with relative paths")

        # Check verification output
        if "Verified:" in result.stdout and "Failed: 0" in result.stdout:
            print(f"  [PASS] All files verified successfully")
            self.passed += 1
        else:
            print(f"  [FAIL] Verification output incorrect")
            self.failed += 1

    def test_absolute_paths(self):
        """Test VERIFY with absolute path preservation (--abs)."""
        print("\n[TEST] VERIFY with absolute paths (--abs)")

        source = self.test_dir / "source"
        dest = self.test_dir / "dest_absolute"
        if dest.exists():
            shutil.rmtree(dest)

        # Copy with absolute paths
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --abs'
        result = self.run_command(cmd)
        self.assert_success(result, "COPY with --abs")

        # With absolute paths, the structure includes the full source path
        # We need to check what actually gets created
        print(f"  Checking created structure in {dest}...")

        # List actual files created
        found_files = []
        for root, dirs, files in os.walk(dest):
            for file in files:
                if file != "preserve_manifest.json" and not file.startswith("preserve_manifest_"):
                    file_path = Path(root) / file
                    relative = file_path.relative_to(dest)
                    found_files.append(str(relative).replace("\\", "/"))

        if found_files:
            print(f"  Found {len(found_files)} files in absolute structure")
            for f in sorted(found_files)[:3]:  # Show first 3 as examples
                print(f"    - {f}")

        # Verify the files
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.assert_success(result, "VERIFY with absolute paths")

        # Check verification output
        if "Verified:" in result.stdout:
            print(f"  [PASS] Files verified with absolute paths")
            self.passed += 1
        else:
            print(f"  [FAIL] Verification with absolute paths failed")
            self.failed += 1

    def test_flat_structure(self):
        """Test VERIFY with flat structure (--flat)."""
        print("\n[TEST] VERIFY with flat structure (--flat)")

        source = self.test_dir / "source"
        dest = self.test_dir / "dest_flat"
        if dest.exists():
            shutil.rmtree(dest)

        # Copy with flat structure
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --flat'
        result = self.run_command(cmd)
        self.assert_success(result, "COPY with --flat")

        # Expected flat structure (all files at root level)
        expected_files = [
            "config.json",
            "large_file.txt",
            "readme.txt",
            "notes.md",
            "report.txt",
            "data.dat",
            "image.bin",
            "main.py",
            "utils.py",
            "file with spaces.txt",
            "file-with-dashes.txt"
        ]
        self.verify_file_structure(dest, expected_files, "Flat structure")

        # Verify the files
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.assert_success(result, "VERIFY with flat structure")

        # Check verification output
        if "Verified:" in result.stdout and "Failed: 0" in result.stdout:
            print(f"  [PASS] All files verified in flat structure")
            self.passed += 1
        else:
            print(f"  [FAIL] Verification in flat structure incorrect")
            self.failed += 1

    def test_numbered_manifests_with_path_styles(self):
        """Test numbered manifests with different path styles."""
        print("\n[TEST] Numbered manifests with different path styles")

        source = self.test_dir / "source"
        dest = self.test_dir / "dest_numbered"
        if dest.exists():
            shutil.rmtree(dest)

        # First copy with relative paths
        cmd = f'preserve COPY "{source}/documents" -r --dst "{dest}" --rel'
        result = self.run_command(cmd)
        self.assert_success(result, "First COPY (relative)")

        # Second copy with flat structure to trigger numbering
        cmd = f'preserve COPY "{source}/media" -r --dst "{dest}" --flat'
        result = self.run_command(cmd)
        self.assert_success(result, "Second COPY (flat, triggers numbering)")

        # List manifests
        cmd = f'preserve VERIFY --dst "{dest}" --list'
        result = self.run_command(cmd)

        if "preserve_manifest_001.json" in result.stdout and "preserve_manifest_002.json" in result.stdout:
            print(f"  [PASS] Numbered manifests created")
            self.passed += 1
        else:
            print(f"  [FAIL] Numbered manifests not found")
            print(f"    stdout: {result.stdout}")
            self.failed += 1

        # Verify with specific manifest number
        cmd = f'preserve VERIFY --dst "{dest}" --manifest-number 1 --hash SHA256'
        result = self.run_command(cmd)

        if result.returncode == 0:
            print(f"  [PASS] VERIFY with --manifest-number 1")
            self.passed += 1
        else:
            print(f"  [FAIL] VERIFY with --manifest-number 1")
            print(f"    stderr: {result.stderr}")
            self.failed += 1

    def test_includebase_absolute(self):
        """Test --includeBase with absolute paths."""
        print("\n[TEST] VERIFY with --includeBase (absolute paths)")

        source = self.test_dir / "source"
        dest = self.test_dir / "dest_includebase"
        if dest.exists():
            shutil.rmtree(dest)

        # Copy with --includeBase (implies absolute paths)
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --includeBase'
        result = self.run_command(cmd)
        self.assert_success(result, "COPY with --includeBase")

        # List what was actually created
        print(f"  Checking structure created by --includeBase...")
        found_files = []
        for root, dirs, files in os.walk(dest):
            for file in files:
                if file != "preserve_manifest.json" and not file.startswith("preserve_manifest_"):
                    file_path = Path(root) / file
                    relative = file_path.relative_to(dest)
                    found_files.append(str(relative).replace("\\", "/"))

        if found_files:
            print(f"  Found {len(found_files)} files")
            # Show structure sample
            for f in sorted(found_files)[:3]:
                print(f"    - {f}")

        # Verify the files
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)

        # Even if paths are nested, VERIFY should handle them
        if result.returncode == 0:
            print(f"  [PASS] VERIFY handles --includeBase structure")
            self.passed += 1
        else:
            print(f"  [FAIL] VERIFY failed with --includeBase structure")
            print(f"    stderr: {result.stderr}")
            self.failed += 1

    def run_all_tests(self):
        """Run all path style tests."""
        print("\n" + "="*60)
        print("VERIFY PATH STYLES TEST SUITE")
        print("="*60)

        # Run tests
        self.test_relative_paths()
        self.test_absolute_paths()
        self.test_flat_structure()
        self.test_numbered_manifests_with_path_styles()
        self.test_includebase_absolute()

        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"  Passed: {self.passed}")
        print(f"  Failed: {self.failed}")
        total = self.passed + self.failed
        if total > 0:
            print(f"  Success Rate: {self.passed*100/total:.1f}%")

        print("\n" + "="*60)
        if self.failed == 0:
            print("ALL TESTS PASSED!")
        else:
            print(f"SOME TESTS FAILED ({self.failed} failures)")
        print("="*60)

        return self.failed == 0


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Test VERIFY with different path styles")
    parser.add_argument("--test-dir", help="Specific test directory to use")
    args = parser.parse_args()

    try:
        test = VerifyPathStylesTest(args.test_dir)
        success = test.run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()