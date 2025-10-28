#!/usr/bin/env python3
"""
Test runner for preserve - runs all tests and provides coverage report.

Usage:
    python run_tests.py                 # Run all tests
    python run_tests.py -v              # Run with verbose output
    python run_tests.py --coverage      # Run with coverage report
    python run_tests.py --generate      # Generate test data first
    python run_tests.py test_manifest   # Run specific test module
"""

import sys
import os
import unittest
import argparse
from pathlib import Path
import subprocess
import json

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_test_environment():
    """Set up the test environment."""
    # Ensure test-runs directory exists
    test_runs_dir = Path("test-runs")
    test_runs_dir.mkdir(exist_ok=True)

    # Set environment variables if needed
    os.environ['PRESERVE_TEST_MODE'] = '1'

    print("Test environment setup complete.")


def generate_test_data():
    """Generate test data using the generator script."""
    print("\nGenerating test data...")
    result = subprocess.run(
        [sys.executable, "tests/generate_test_data.py"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("Test data generated successfully.")
        # Parse the output to get the test directory
        for line in result.stdout.split('\n'):
            if line.startswith("Base directory:"):
                test_dir = line.split(":", 1)[1].strip()
                return test_dir
    else:
        print(f"Error generating test data: {result.stderr}")
        return None


def run_tests(test_pattern="test_*.py", verbosity=2, test_dir="tests"):
    """Run the unit tests."""
    # Discover and run tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Get test files but exclude one-offs directory
    test_path = Path(test_dir)
    for test_file in test_path.glob(test_pattern):
        # Skip files in subdirectories like one-offs
        if test_file.parent == test_path:
            module_name = f"{test_dir}.{test_file.stem}"
            try:
                module = __import__(module_name, fromlist=[''])
                suite.addTests(loader.loadTestsFromModule(module))
            except ImportError as e:
                print(f"Warning: Could not import {module_name}: {e}")

    # Run tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    return result.wasSuccessful()


def run_with_coverage(test_pattern="test_*.py", test_dir="tests"):
    """Run tests with coverage reporting."""
    try:
        import coverage
    except ImportError:
        print("Coverage package not installed. Install with: pip install coverage")
        return False

    # Initialize coverage
    cov = coverage.Coverage(
        source=["preserve", "preservelib", "dazzle_filekit"],
        omit=[
            "*/tests/*",
            "*/test_*.py",
            "*/__pycache__/*",
            "*/setup.py"
        ]
    )

    # Start coverage
    cov.start()

    # Run tests
    success = run_tests(test_pattern, verbosity=2, test_dir=test_dir)

    # Stop coverage
    cov.stop()
    cov.save()

    # Generate report
    print("\n" + "=" * 70)
    print("COVERAGE REPORT")
    print("=" * 70)
    cov.report()

    # Generate HTML report
    html_dir = Path("htmlcov")
    cov.html_report(directory=str(html_dir))
    print(f"\nDetailed HTML coverage report generated in: {html_dir.absolute()}")

    return success


def run_specific_test(test_name, verbosity=2):
    """Run a specific test module or test case."""
    loader = unittest.TestLoader()

    # Try to load the specific test
    try:
        if '.' in test_name:
            # Full test path like test_manifest.TestManifest.test_numbering
            suite = loader.loadTestsFromName(f"tests.{test_name}")
        else:
            # Module name like test_manifest
            suite = loader.loadTestsFromModule(
                __import__(f"tests.{test_name}", fromlist=[''])
            )
    except (ImportError, AttributeError) as e:
        print(f"Error loading test '{test_name}': {e}")
        return False

    # Run the test
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    return result.wasSuccessful()


def list_tests():
    """List all available test modules."""
    test_dir = Path("tests")
    test_files = sorted(test_dir.glob("test_*.py"))

    print("\nAvailable test modules:")
    print("-" * 40)
    for test_file in test_files:
        module_name = test_file.stem
        print(f"  {module_name}")

        # Try to get test class names
        try:
            module = __import__(f"tests.{module_name}", fromlist=[''])
            for name in dir(module):
                if name.startswith('Test'):
                    cls = getattr(module, name)
                    if isinstance(cls, type) and issubclass(cls, unittest.TestCase):
                        print(f"    - {name}")
        except ImportError:
            pass

    print("-" * 40)
    print("\nRun specific test with: python run_tests.py <test_name>")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run preserve test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                    # Run all tests
  python run_tests.py -v                 # Run with verbose output
  python run_tests.py --coverage         # Run with coverage report
  python run_tests.py --generate         # Generate test data first
  python run_tests.py test_manifest      # Run specific test module
  python run_tests.py --list             # List available tests
        """
    )

    parser.add_argument(
        "test",
        nargs="?",
        help="Specific test module or test case to run"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose test output"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run tests with coverage analysis"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate test data before running tests"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available test modules"
    )
    parser.add_argument(
        "--test-dir",
        default="tests",
        help="Directory containing test files (default: tests)"
    )

    args = parser.parse_args()

    # Setup test environment
    setup_test_environment()

    # List tests if requested
    if args.list:
        list_tests()
        return 0

    # Generate test data if requested
    if args.generate:
        test_data_dir = generate_test_data()
        if test_data_dir:
            print(f"Test data available in: {test_data_dir}")
        else:
            print("Failed to generate test data")
            return 1

    # Determine verbosity
    verbosity = 2 if args.verbose else 1

    # Run tests
    print("\n" + "=" * 70)
    print("PRESERVE TEST SUITE")
    print("=" * 70)

    if args.test:
        # Run specific test
        print(f"\nRunning specific test: {args.test}")
        success = run_specific_test(args.test, verbosity)
    elif args.coverage:
        # Run with coverage
        print("\nRunning tests with coverage analysis...")
        success = run_with_coverage(test_dir=args.test_dir)
    else:
        # Run all tests
        print("\nRunning all tests...")
        success = run_tests(verbosity=verbosity, test_dir=args.test_dir)

    # Report results
    print("\n" + "=" * 70)
    if success:
        print("ALL TESTS PASSED [OK]")
    else:
        print("SOME TESTS FAILED [FAIL]")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())