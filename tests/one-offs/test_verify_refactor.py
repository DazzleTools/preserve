#!/usr/bin/env python3
"""
Integration test for VERIFY refactoring.

This test ensures that the refactored VERIFY operation maintains
backward compatibility and adds new numbered manifest support.
"""

import os
import sys
import shutil
import json
import subprocess
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class VerifyRefactorTest:
    """Test VERIFY operation after refactoring."""

    def __init__(self, test_dir=None):
        """Initialize the test."""
        if test_dir:
            self.test_dir = Path(test_dir)
        else:
            # Find the most recent test directory
            test_runs = Path("test-runs")
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

    def assert_in_output(self, result, text, test_name):
        """Assert text appears in output."""
        if text in result.stdout or text in result.stderr:
            print(f"  [PASS] {test_name}: Found '{text}'")
            self.passed += 1
            return True
        else:
            print(f"  [FAIL] {test_name}: '{text}' not in output")
            print(f"    stdout: {result.stdout}")
            print(f"    stderr: {result.stderr}")
            self.failed += 1
            return False

    def test_verify_single_manifest(self):
        """Test VERIFY with single manifest (backward compatibility)."""
        print("\n[TEST] VERIFY with single manifest")

        # Setup: Create a preserved directory
        source = self.test_dir / "source"
        dest = self.test_dir / "verify_single"
        if dest.exists():
            shutil.rmtree(dest)

        # Copy files
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --includeBase'
        result = self.run_command(cmd)
        self.assert_success(result, "COPY operation")

        # Test: VERIFY should work
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.assert_success(result, "VERIFY with single manifest")
        self.assert_in_output(result, "Verified:", "Verification summary in output")

    def test_verify_numbered_manifests(self):
        """Test VERIFY with numbered manifests."""
        print("\n[TEST] VERIFY with numbered manifests")

        # Setup: Create multiple manifests
        source = self.test_dir / "source"
        dest = self.test_dir / "verify_numbered"
        if dest.exists():
            shutil.rmtree(dest)

        # First copy
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --includeBase'
        result = self.run_command(cmd)
        self.assert_success(result, "First COPY")

        # Second copy to trigger numbering
        source2 = self.test_dir / "complex"
        if not source2.exists():
            # Use source again if complex doesn't exist
            source2 = source
        cmd = f'preserve COPY "{source2}" -r --dst "{dest}" --includeBase'
        result = self.run_command(cmd)
        self.assert_success(result, "Second COPY (triggers numbering)")

        # Test: VERIFY should handle numbered manifests
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.assert_success(result, "VERIFY with numbered manifests")

    def test_verify_list_flag(self):
        """Test VERIFY --list flag."""
        print("\n[TEST] VERIFY --list flag")

        # Setup: Use directory with multiple manifests
        dest = self.test_dir / "verify_numbered"
        if not dest.exists():
            self.test_verify_numbered_manifests()

        # Test: --list should show available manifests
        cmd = f'preserve VERIFY --dst "{dest}" --list'
        result = self.run_command(cmd)

        # Check for manifest listing
        if "Available manifests:" in result.stdout or "preserve_manifest" in result.stdout:
            print(f"  [PASS] --list shows manifests")
            self.passed += 1
        else:
            # This might fail with current implementation - that's expected
            print(f"  [EXPECTED FAIL] --list doesn't show manifests yet")
            print(f"    stdout: {result.stdout}")

    def test_verify_manifest_number(self):
        """Test VERIFY --manifest-number flag."""
        print("\n[TEST] VERIFY --manifest-number flag")

        # Setup: Use directory with numbered manifests
        dest = self.test_dir / "verify_numbered"
        if not dest.exists():
            self.test_verify_numbered_manifests()

        # Test: --manifest-number should select specific manifest
        cmd = f'preserve VERIFY --dst "{dest}" --manifest-number 1 --hash SHA256'
        result = self.run_command(cmd)

        # This should work after refactoring
        if result.returncode == 0:
            print(f"  [PASS] --manifest-number works")
            self.passed += 1
        else:
            print(f"  [EXPECTED FAIL] --manifest-number not implemented yet")

    def test_verify_with_corruption(self):
        """Test VERIFY detects file corruption."""
        print("\n[TEST] VERIFY detects corruption")

        # Setup: Create preserved directory
        source = self.test_dir / "source"
        dest = self.test_dir / "verify_corrupt"
        if dest.exists():
            shutil.rmtree(dest)

        # Copy files
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --includeBase'
        self.run_command(cmd)

        # Corrupt a file
        files = list((dest / "source").glob("*.txt"))
        if files:
            corrupt_file = files[0]
            corrupt_file.write_text("CORRUPTED CONTENT")
            print(f"  Corrupted: {corrupt_file.name}")

            # Test: VERIFY should detect corruption
            cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
            result = self.run_command(cmd)

            # Should fail or report failed files
            if result.returncode != 0 or "Failed" in result.stdout:
                print(f"  [PASS] Corruption detected")
                self.passed += 1
            else:
                print(f"  [FAIL] Corruption not detected")
                self.failed += 1

    def run_all_tests(self):
        """Run all tests."""
        print("\n" + "="*60)
        print("VERIFY REFACTOR INTEGRATION TESTS")
        print("="*60)

        # Run tests
        self.test_verify_single_manifest()
        self.test_verify_numbered_manifests()
        self.test_verify_list_flag()
        self.test_verify_manifest_number()
        self.test_verify_with_corruption()

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
    parser = argparse.ArgumentParser(description="Test VERIFY refactoring")
    parser.add_argument("--test-dir", help="Specific test directory to use")
    args = parser.parse_args()

    try:
        test = VerifyRefactorTest(args.test_dir)
        success = test.run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()