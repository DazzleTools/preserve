#!/usr/bin/env python3
"""
Capture current behavior of preserve operations before refactoring.

This test creates a golden record of how COPY, MOVE, VERIFY, and RESTORE
currently work, so we can ensure our refactoring doesn't break anything.
"""

import os
import sys
import shutil
import json
import subprocess
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class CurrentBehaviorCapture:
    """Capture current behavior of preserve operations."""

    def __init__(self, test_dir=None):
        """Initialize the behavior capture."""
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
        self.results_dir = self.test_dir / "behavior_capture"
        self.results_dir.mkdir(exist_ok=True)

    def run_command(self, cmd, capture_output=True):
        """Run a preserve command and capture output."""
        print(f"\nRunning: {cmd}")
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=capture_output,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return result

    def save_result(self, operation, command, result, extra_data=None):
        """Save command result for comparison."""
        output_file = self.results_dir / f"{operation}_output.json"
        data = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timestamp": datetime.now().isoformat()
        }
        if extra_data:
            data.update(extra_data)

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"  Saved to: {output_file}")

    def test_copy_operation(self):
        """Test COPY operation with various options."""
        print("\n" + "="*60)
        print("Testing COPY operation")
        print("="*60)

        source = self.test_dir / "source"
        dest = self.test_dir / "dest_copy_test"

        # Clean destination if exists
        if dest.exists():
            shutil.rmtree(dest)

        # Test basic COPY
        cmd = f'preserve COPY "{source}" -r --dst "{dest}" --includeBase --rel'
        result = self.run_command(cmd)
        self.save_result("copy_basic", cmd, result)

        # Check manifest was created
        manifest_files = list(dest.glob("preserve_manifest*.json"))
        manifest_data = None
        if manifest_files:
            with open(manifest_files[0]) as f:
                manifest_data = json.load(f)

        self.save_result("copy_manifest", cmd, result, {"manifest": manifest_data})

        return result.returncode == 0

    def test_verify_operation(self):
        """Test VERIFY operation with current implementation."""
        print("\n" + "="*60)
        print("Testing VERIFY operation")
        print("="*60)

        # First do a COPY to have something to verify
        source = self.test_dir / "source"
        dest = self.test_dir / "dest_verify_test"

        # Clean and create destination
        if dest.exists():
            shutil.rmtree(dest)

        # Copy first
        cmd_copy = f'preserve COPY "{source}" -r --dst "{dest}" --includeBase'
        self.run_command(cmd_copy)

        # Test VERIFY with single manifest
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.save_result("verify_single", cmd, result)

        # Create second copy to same destination (will create numbered manifest)
        source2 = self.test_dir / "docs"
        cmd_copy2 = f'preserve COPY "{source2}" -r --dst "{dest}" --includeBase'
        self.run_command(cmd_copy2)

        # Test VERIFY again (should still work with multiple manifests)
        cmd = f'preserve VERIFY --dst "{dest}" --hash SHA256'
        result = self.run_command(cmd)
        self.save_result("verify_multiple", cmd, result)

        # Try VERIFY with --list (if it works currently)
        cmd_list = f'preserve VERIFY --dst "{dest}" --list'
        result_list = self.run_command(cmd_list)
        self.save_result("verify_list_attempt", cmd_list, result_list)

        return result.returncode == 0

    def test_restore_operation(self):
        """Test RESTORE operation with current implementation."""
        print("\n" + "="*60)
        print("Testing RESTORE operation")
        print("="*60)

        # Set up a preserved directory
        source = self.test_dir / "source"
        preserved = self.test_dir / "dest_restore_test"

        # Clean and create
        if preserved.exists():
            shutil.rmtree(preserved)

        # Preserve files
        cmd_copy = f'preserve COPY "{source}" -r --dst "{preserved}" --includeBase --rel'
        self.run_command(cmd_copy)

        # Move source to simulate it being gone
        source_backup = self.test_dir / "source_backup"
        if source_backup.exists():
            shutil.rmtree(source_backup)
        shutil.move(str(source), str(source_backup))

        # Test RESTORE
        cmd = f'preserve RESTORE --src "{preserved}"'
        result = self.run_command(cmd)
        self.save_result("restore_basic", cmd, result)

        # Test RESTORE --list
        cmd_list = f'preserve RESTORE --src "{preserved}" --list'
        result_list = self.run_command(cmd_list)
        self.save_result("restore_list", cmd_list, result_list)

        # Restore source for other tests
        if source_backup.exists() and not source.exists():
            shutil.move(str(source_backup), str(source))

        return result.returncode == 0

    def test_move_operation(self):
        """Test MOVE operation."""
        print("\n" + "="*60)
        print("Testing MOVE operation")
        print("="*60)

        # Create a test file to move
        source_file = self.test_dir / "test_move.txt"
        source_file.write_text("Test file for MOVE operation")

        dest = self.test_dir / "dest_move_test"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir()

        # Test MOVE
        cmd = f'preserve MOVE "{source_file}" --dst "{dest}"'
        result = self.run_command(cmd)
        self.save_result("move_file", cmd, result)

        return result.returncode == 0

    def create_summary(self):
        """Create a summary of all captured behaviors."""
        summary = {
            "test_directory": str(self.test_dir),
            "timestamp": datetime.now().isoformat(),
            "operations_tested": []
        }

        for result_file in self.results_dir.glob("*.json"):
            with open(result_file) as f:
                data = json.load(f)
                summary["operations_tested"].append({
                    "operation": result_file.stem,
                    "command": data["command"],
                    "success": data["returncode"] == 0
                })

        summary_file = self.results_dir / "behavior_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"\n{'='*60}")
        print(f"Summary saved to: {summary_file}")
        print(f"{'='*60}")

        return summary

    def run_all_tests(self):
        """Run all behavior capture tests."""
        print("\n" + "="*60)
        print("CAPTURING CURRENT BEHAVIOR OF PRESERVE OPERATIONS")
        print("="*60)

        results = {
            "COPY": self.test_copy_operation(),
            "VERIFY": self.test_verify_operation(),
            "RESTORE": self.test_restore_operation(),
            "MOVE": self.test_move_operation()
        }

        print("\n" + "="*60)
        print("RESULTS SUMMARY")
        print("="*60)
        for op, success in results.items():
            status = "PASSED" if success else "FAILED"
            print(f"  {op}: {status}")

        summary = self.create_summary()

        print("\nBehavior capture complete!")
        print(f"Results saved in: {self.results_dir}")
        print("\nYou can now make changes and re-run this test to compare behaviors.")

        return all(results.values())


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Capture current behavior of preserve operations")
    parser.add_argument("--test-dir", help="Specific test directory to use")
    args = parser.parse_args()

    try:
        capture = CurrentBehaviorCapture(args.test_dir)
        success = capture.run_all_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()