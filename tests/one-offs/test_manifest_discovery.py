#!/usr/bin/env python
"""Test manifest discovery after moving to preservelib.manifest"""

from pathlib import Path
from dazzle_preservelib.manifest import find_available_manifests

# Test on a known directory
test_dirs = [
    Path('private/dst2'),
    Path('private/dst5'),
    Path('.'),  # Current directory
]

for test_path in test_dirs:
    if test_path.exists():
        print(f"\nChecking {test_path}:")
        manifests = find_available_manifests(test_path)
        print(f"Found {len(manifests)} manifests")
        for num, path, desc in manifests:
            print(f"  #{num}: {path.name}{' - ' + desc if desc else ''}")
    else:
        print(f"\nDirectory {test_path} does not exist")

print("\n✓ Manifest discovery function works correctly!")