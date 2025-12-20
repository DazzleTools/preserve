#!/usr/bin/env python3
"""
Tests for path cycle detection (Issue #47).

Tests the safety checks that prevent catastrophic data loss when
source and destination resolve to the same location via symlinks/junctions.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path

from preservelib.operations import detect_path_cycle, detect_path_cycles_deep, preflight_checks


class TestDetectPathCycle(unittest.TestCase):
    """Test the detect_path_cycle function directly."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_cycle_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()

        # Create a test file in source
        (self.src / "test.txt").write_text("test content")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_no_cycle_separate_paths(self):
        """No cycle when source and destination are completely separate."""
        issues = detect_path_cycle([str(self.src)], str(self.dst))
        self.assertEqual(issues, [])

    def test_no_cycle_nonexistent_destination(self):
        """No cycle when destination doesn't exist yet."""
        new_dst = self.test_dir / "new_destination"
        issues = detect_path_cycle([str(self.src)], str(new_dst))
        self.assertEqual(issues, [])

    def test_same_path_detected(self):
        """Detect when source and destination are literally the same path."""
        issues = detect_path_cycle([str(self.src)], str(self.src))
        self.assertEqual(len(issues), 1)
        self.assertIn("CRITICAL", issues[0])
        self.assertIn("same location", issues[0])

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_junction_cycle_detected(self):
        """Detect cycle when destination is a junction pointing to source."""
        junction = self.test_dir / "junction_to_src"

        # Create junction: junction_to_src -> source
        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(junction), str(self.src)],
            capture_output=True
        )

        if result.returncode != 0:
            self.skipTest("Could not create junction (may need admin)")

        try:
            issues = detect_path_cycle([str(self.src)], str(junction))
            self.assertEqual(len(issues), 1)
            self.assertIn("CRITICAL", issues[0])
            self.assertIn("same location", issues[0])
        finally:
            # Clean up junction
            if junction.exists():
                junction.rmdir()

    @unittest.skipIf(sys.platform == 'win32', "Symlink test may require admin on Windows")
    def test_symlink_cycle_detected(self):
        """Detect cycle when destination is a symlink pointing to source."""
        symlink = self.test_dir / "symlink_to_src"
        symlink.symlink_to(self.src)

        issues = detect_path_cycle([str(self.src)], str(symlink))
        self.assertEqual(len(issues), 1)
        self.assertIn("CRITICAL", issues[0])
        self.assertIn("same location", issues[0])

    def test_destination_inside_source_detected(self):
        """Detect when destination is inside source directory."""
        nested_dst = self.src / "backup"
        nested_dst.mkdir()

        issues = detect_path_cycle([str(self.src)], str(nested_dst))
        self.assertEqual(len(issues), 1)
        self.assertIn("CRITICAL", issues[0])
        self.assertIn("inside source", issues[0])

    def test_source_inside_destination_detected(self):
        """Detect when source is inside destination directory."""
        nested_src = self.dst / "data"
        nested_src.mkdir()
        (nested_src / "file.txt").write_text("content")

        issues = detect_path_cycle([str(nested_src)], str(self.dst))
        self.assertEqual(len(issues), 1)
        self.assertIn("WARNING", issues[0])
        self.assertIn("inside destination", issues[0])

    def test_multiple_sources_checked(self):
        """All sources are checked, not just the first one."""
        # Create another source that's inside destination
        nested_src = self.dst / "nested"
        nested_src.mkdir()

        issues = detect_path_cycle(
            [str(self.src), str(nested_src)],  # Second source is problematic
            str(self.dst)
        )
        self.assertEqual(len(issues), 1)
        self.assertIn("nested", issues[0])


class TestPreflightCycleIntegration(unittest.TestCase):
    """Test that preflight_checks properly integrates cycle detection."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_preflight_cycle_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "test.txt").write_text("test content")

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_move_same_path_blocked(self):
        """MOVE with same source/destination is blocked (hard issue)."""
        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(self.src),
            operation="MOVE"
        )
        self.assertFalse(all_ok)
        self.assertTrue(any("CRITICAL" in issue for issue in hard_issues))

    def test_copy_same_path_blocked(self):
        """COPY with same source/destination is also blocked."""
        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(self.src),
            operation="COPY"
        )
        self.assertFalse(all_ok)
        self.assertTrue(any("same location" in issue for issue in hard_issues))

    def test_move_dest_inside_source_blocked(self):
        """MOVE with destination inside source is blocked."""
        nested_dst = self.src / "backup"
        nested_dst.mkdir()

        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(nested_dst),
            operation="MOVE"
        )
        self.assertFalse(all_ok)
        self.assertTrue(any("inside source" in issue for issue in hard_issues))

    def test_copy_dest_inside_source_warning(self):
        """COPY with destination inside source is a warning, not blocking."""
        nested_dst = self.src / "backup"
        nested_dst.mkdir()

        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(nested_dst),
            operation="COPY"
        )
        # Should be soft issue for COPY (not blocking)
        self.assertTrue(any("inside source" in issue for issue in soft_issues))

    def test_source_inside_dest_warning(self):
        """Source inside destination is a warning for both COPY and MOVE."""
        nested_src = self.dst / "data"
        nested_src.mkdir()
        (nested_src / "file.txt").write_text("content")

        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(nested_src)],
            str(self.dst),
            operation="COPY"
        )
        self.assertTrue(any("inside destination" in issue for issue in soft_issues))

    def test_no_cycle_passes(self):
        """Normal separate paths pass preflight checks."""
        all_ok, hard_issues, soft_issues, _ = preflight_checks(
            [str(self.src)],
            str(self.dst),
            operation="MOVE"
        )
        # Should pass (no cycle issues)
        cycle_issues = [i for i in hard_issues + soft_issues if "CRITICAL" in i or "inside" in i]
        self.assertEqual(cycle_issues, [])


class TestDeepCycleDetection(unittest.TestCase):
    """Test the detect_path_cycles_deep function for nested junction/symlink scenarios."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_deep_cycle_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()

        # Create subdirectory structure in source
        self.src_sub = self.src / "subdir"
        self.src_sub.mkdir()
        (self.src_sub / "file.txt").write_text("content in subdir")
        (self.src / "root_file.txt").write_text("content in root")

    def tearDown(self):
        """Clean up test environment."""
        # Need to handle junctions specially on Windows
        for item in self.test_dir.rglob("*"):
            try:
                if item.is_symlink() or (sys.platform == 'win32' and item.is_dir()):
                    # Try to remove as junction first
                    try:
                        item.rmdir()
                    except OSError:
                        pass
            except OSError:
                pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_no_links_returns_empty_report(self):
        """When no links exist, link_report should be empty."""
        can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
            [str(self.src)], str(self.dst), "MOVE"
        )
        self.assertTrue(can_proceed)
        self.assertEqual(hard_issues, [])
        self.assertEqual(link_report, [])

    def test_separate_paths_with_links_ok(self):
        """Links pointing to unrelated locations should not block."""
        # Create a link to an unrelated location
        unrelated = self.test_dir / "unrelated"
        unrelated.mkdir()

        link_path = self.src / "link_to_unrelated"

        if sys.platform == 'win32':
            # Create junction on Windows
            import subprocess
            result = subprocess.run(
                ['cmd', '/c', 'mklink', '/J', str(link_path), str(unrelated)],
                capture_output=True, shell=True
            )
            if result.returncode != 0:
                self.skipTest("Could not create junction")
        else:
            link_path.symlink_to(unrelated)

        try:
            can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )
            self.assertTrue(can_proceed)
            self.assertEqual(len(link_report), 1)
            self.assertEqual(hard_issues, [])
        finally:
            if link_path.exists():
                try:
                    link_path.rmdir()
                except OSError:
                    os.unlink(link_path)

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_nested_junction_pointing_to_dest_blocked(self):
        """Junction inside source pointing to destination should BLOCK for MOVE."""
        # This is the critical scenario from Issue #47
        # source/subdir_link -> destination

        link_path = self.src / "dangerous_link"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link_path), str(self.dst)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )

            # Should NOT be able to proceed
            self.assertFalse(can_proceed)
            # Should have a CRITICAL hard issue
            self.assertTrue(any("CRITICAL" in issue for issue in hard_issues))
            self.assertTrue(any("points to" in issue and "destination" in issue for issue in hard_issues))
            # Link should be in report
            self.assertEqual(len(link_report), 1)
            self.assertEqual(link_report[0]['link_type'], 'junction')
        finally:
            if link_path.exists():
                link_path.rmdir()

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_nested_junction_pointing_inside_dest_blocked(self):
        """Junction inside source pointing INTO destination should BLOCK for MOVE."""
        # source/link -> destination/subdir

        dest_sub = self.dst / "existing_subdir"
        dest_sub.mkdir()
        (dest_sub / "existing.txt").write_text("existing content")

        link_path = self.src / "link_to_dest_subdir"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link_path), str(dest_sub)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )

            # Should NOT be able to proceed
            self.assertFalse(can_proceed)
            # Should have a CRITICAL issue about pointing inside destination
            self.assertTrue(any("inside" in issue.lower() or "points inside" in issue.lower()
                               for issue in hard_issues))
        finally:
            if link_path.exists():
                link_path.rmdir()

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_nested_junction_for_copy_is_warning(self):
        """Same dangerous junction should be WARNING (not block) for COPY."""
        link_path = self.src / "dangerous_link"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link_path), str(self.dst)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "COPY"
            )

            # COPY should be able to proceed (with warning)
            self.assertTrue(can_proceed)
            self.assertEqual(hard_issues, [])
            # But should have a warning
            self.assertTrue(any("WARNING" in issue for issue in soft_issues))
        finally:
            if link_path.exists():
                link_path.rmdir()

    @unittest.skipIf(sys.platform == 'win32', "Symlink test may require admin on Windows")
    def test_nested_symlink_pointing_to_dest_blocked(self):
        """Symlink inside source pointing to destination should BLOCK for MOVE."""
        link_path = self.src / "dangerous_symlink"
        link_path.symlink_to(self.dst)

        can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
            [str(self.src)], str(self.dst), "MOVE"
        )

        # Should NOT be able to proceed
        self.assertFalse(can_proceed)
        self.assertTrue(any("CRITICAL" in issue for issue in hard_issues))
        self.assertEqual(len(link_report), 1)
        self.assertEqual(link_report[0]['link_type'], 'soft')

    def test_deeply_nested_link_detected(self):
        """Links deep in the tree should still be detected."""
        # Create deep structure: source/a/b/c/link -> destination
        deep_path = self.src / "a" / "b" / "c"
        deep_path.mkdir(parents=True)
        (deep_path / "deep_file.txt").write_text("deep content")

        link_path = deep_path / "deep_link"

        if sys.platform == 'win32':
            import subprocess
            result = subprocess.run(
                ['cmd', '/c', 'mklink', '/J', str(link_path), str(self.dst)],
                capture_output=True, shell=True
            )
            if result.returncode != 0:
                self.skipTest("Could not create junction")
        else:
            link_path.symlink_to(self.dst)

        try:
            can_proceed, hard_issues, soft_issues, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )

            # Should detect the deeply nested link
            self.assertFalse(can_proceed)
            self.assertEqual(len(link_report), 1)
            self.assertIn("a", link_report[0]['link_path'])
            self.assertIn("b", link_report[0]['link_path'])
            self.assertIn("c", link_report[0]['link_path'])
        finally:
            if link_path.exists():
                try:
                    link_path.rmdir()
                except OSError:
                    os.unlink(link_path)

    def test_link_report_contains_correct_info(self):
        """Link report should contain all expected fields."""
        unrelated = self.test_dir / "target"
        unrelated.mkdir()

        link_path = self.src / "test_link"

        if sys.platform == 'win32':
            import subprocess
            result = subprocess.run(
                ['cmd', '/c', 'mklink', '/J', str(link_path), str(unrelated)],
                capture_output=True, shell=True
            )
            if result.returncode != 0:
                self.skipTest("Could not create junction")
        else:
            link_path.symlink_to(unrelated)

        try:
            _, _, _, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )

            self.assertEqual(len(link_report), 1)
            report = link_report[0]

            # Check required fields
            self.assertIn('link_path', report)
            self.assertIn('link_type', report)
            self.assertIn('target', report)
            self.assertIn('target_resolved', report)
            self.assertIn('target_exists', report)

            self.assertEqual(report['link_path'], str(link_path))
            self.assertTrue(report['target_exists'])
        finally:
            if link_path.exists():
                try:
                    link_path.rmdir()
                except OSError:
                    os.unlink(link_path)


class TestPreflightDeepCycleIntegration(unittest.TestCase):
    """Test that preflight_checks uses deep detection for MOVE operations."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_preflight_deep_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "test.txt").write_text("test content")

    def tearDown(self):
        """Clean up test environment."""
        for item in self.test_dir.rglob("*"):
            try:
                if item.is_symlink() or (sys.platform == 'win32' and item.is_dir()):
                    try:
                        item.rmdir()
                    except OSError:
                        pass
            except OSError:
                pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_move_with_nested_junction_blocked_by_preflight(self):
        """MOVE preflight should block when nested junction points to destination."""
        # Create nested junction: source/subdir -> destination
        subdir_link = self.src / "subdir_link"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(subdir_link), str(self.dst)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            all_ok, hard_issues, soft_issues, _ = preflight_checks(
                [str(self.src)],
                str(self.dst),
                operation="MOVE"
            )

            # Should NOT be OK
            self.assertFalse(all_ok)
            # Should have hard issues about the junction
            self.assertTrue(len(hard_issues) > 0)
            self.assertTrue(any("CRITICAL" in issue or "points to" in issue
                               for issue in hard_issues))
        finally:
            if subdir_link.exists():
                subdir_link.rmdir()


class TestLinkHandlingMode(unittest.TestCase):
    """Test LinkHandlingMode enum functionality."""

    def test_from_string_valid_modes(self):
        """from_string should parse all valid modes."""
        from preservelib.links import LinkHandlingMode

        self.assertEqual(LinkHandlingMode.from_string("block"), LinkHandlingMode.BLOCK)
        self.assertEqual(LinkHandlingMode.from_string("skip"), LinkHandlingMode.SKIP)
        self.assertEqual(LinkHandlingMode.from_string("unlink"), LinkHandlingMode.UNLINK)
        self.assertEqual(LinkHandlingMode.from_string("recreate"), LinkHandlingMode.RECREATE)
        self.assertEqual(LinkHandlingMode.from_string("ask"), LinkHandlingMode.ASK)

    def test_from_string_case_insensitive(self):
        """from_string should be case insensitive."""
        from preservelib.links import LinkHandlingMode

        self.assertEqual(LinkHandlingMode.from_string("BLOCK"), LinkHandlingMode.BLOCK)
        self.assertEqual(LinkHandlingMode.from_string("Skip"), LinkHandlingMode.SKIP)
        self.assertEqual(LinkHandlingMode.from_string("UNLINK"), LinkHandlingMode.UNLINK)

    def test_from_string_invalid_raises(self):
        """from_string should raise ValueError for invalid modes."""
        from preservelib.links import LinkHandlingMode

        with self.assertRaises(ValueError) as ctx:
            LinkHandlingMode.from_string("invalid")

        self.assertIn("Invalid link handling mode", str(ctx.exception))
        self.assertIn("invalid", str(ctx.exception))


class TestLinkInfo(unittest.TestCase):
    """Test LinkInfo dataclass functionality."""

    def test_creates_cycle_with_destination_match(self):
        """creates_cycle_with should return True when target is destination."""
        from preservelib.links import LinkInfo

        info = LinkInfo(
            link_path=Path("/source/link"),
            target_is_destination=True
        )
        self.assertTrue(info.creates_cycle_with(Path("/dest")))

    def test_creates_cycle_with_inside_destination(self):
        """creates_cycle_with should return True when target is inside destination."""
        from preservelib.links import LinkInfo

        info = LinkInfo(
            link_path=Path("/source/link"),
            target_inside_destination=True
        )
        self.assertTrue(info.creates_cycle_with(Path("/dest")))

    def test_creates_cycle_with_contains_destination(self):
        """creates_cycle_with should return True when target contains destination."""
        from preservelib.links import LinkInfo

        info = LinkInfo(
            link_path=Path("/source/link"),
            target_contains_destination=True
        )
        self.assertTrue(info.creates_cycle_with(Path("/dest")))

    def test_no_cycle(self):
        """creates_cycle_with should return False when no cycle."""
        from preservelib.links import LinkInfo

        info = LinkInfo(link_path=Path("/source/link"))
        self.assertFalse(info.creates_cycle_with(Path("/dest")))

    def test_to_dict_serialization(self):
        """to_dict should serialize all fields correctly."""
        from preservelib.links import LinkInfo, LinkAction

        info = LinkInfo(
            link_path=Path("/source/link"),
            link_type="junction",
            raw_target="/target",
            resolved_target=Path("/target/resolved"),
            target_is_destination=True,
            action=LinkAction.SKIP,
            action_result="skipped"
        )
        d = info.to_dict()

        # Path serialization varies by platform - check contains key parts
        self.assertIn("source", d["link_path"])
        self.assertIn("link", d["link_path"])
        self.assertEqual(d["link_type"], "junction")
        self.assertEqual(d["raw_target"], "/target")
        self.assertIn("target", d["resolved_target"])
        self.assertIn("resolved", d["resolved_target"])
        self.assertTrue(d["target_is_destination"])
        self.assertEqual(d["action"], "skip")
        self.assertEqual(d["action_result"], "skipped")


class TestDecideLinkAction(unittest.TestCase):
    """Test decide_link_action function."""

    def test_block_mode_with_cycle_blocks(self):
        """Block mode should return BLOCK for cycle-creating links."""
        from preservelib.links import LinkInfo, LinkHandlingMode, LinkAction, decide_link_action

        info = LinkInfo(
            link_path=Path("/source/link"),
            target_is_destination=True
        )
        action = decide_link_action(info, LinkHandlingMode.BLOCK, Path("/dest"))
        self.assertEqual(action, LinkAction.BLOCK)

    def test_block_mode_without_cycle_follows(self):
        """Block mode should return FOLLOW for non-cycle links."""
        from preservelib.links import LinkInfo, LinkHandlingMode, LinkAction, decide_link_action

        info = LinkInfo(link_path=Path("/source/link"))
        action = decide_link_action(info, LinkHandlingMode.BLOCK, Path("/dest"))
        self.assertEqual(action, LinkAction.FOLLOW)

    def test_skip_mode_always_skips(self):
        """Skip mode should always return SKIP."""
        from preservelib.links import LinkInfo, LinkHandlingMode, LinkAction, decide_link_action

        # Even non-cycle links should be skipped
        info = LinkInfo(link_path=Path("/source/link"))
        action = decide_link_action(info, LinkHandlingMode.SKIP, Path("/dest"))
        self.assertEqual(action, LinkAction.SKIP)

    def test_unlink_mode_with_cycle_unlinks(self):
        """Unlink mode should return UNLINK for cycle-creating links."""
        from preservelib.links import LinkInfo, LinkHandlingMode, LinkAction, decide_link_action

        info = LinkInfo(
            link_path=Path("/source/link"),
            target_is_destination=True
        )
        action = decide_link_action(info, LinkHandlingMode.UNLINK, Path("/dest"))
        self.assertEqual(action, LinkAction.UNLINK)

    def test_unlink_mode_without_cycle_skips(self):
        """Unlink mode should return SKIP for non-cycle links."""
        from preservelib.links import LinkInfo, LinkHandlingMode, LinkAction, decide_link_action

        info = LinkInfo(link_path=Path("/source/link"))
        action = decide_link_action(info, LinkHandlingMode.UNLINK, Path("/dest"))
        self.assertEqual(action, LinkAction.SKIP)

    def test_recreate_mode_not_implemented(self):
        """Recreate mode should raise NotImplementedError."""
        from preservelib.links import LinkInfo, LinkHandlingMode, decide_link_action

        info = LinkInfo(link_path=Path("/source/link"))
        with self.assertRaises(NotImplementedError) as ctx:
            decide_link_action(info, LinkHandlingMode.RECREATE, Path("/dest"))

        self.assertIn("recreate", str(ctx.exception))
        self.assertIn("not yet implemented", str(ctx.exception))

    def test_ask_mode_not_implemented(self):
        """Ask mode should raise NotImplementedError."""
        from preservelib.links import LinkInfo, LinkHandlingMode, decide_link_action

        info = LinkInfo(link_path=Path("/source/link"))
        with self.assertRaises(NotImplementedError) as ctx:
            decide_link_action(info, LinkHandlingMode.ASK, Path("/dest"))

        self.assertIn("ask", str(ctx.exception))
        self.assertIn("not yet implemented", str(ctx.exception))


class TestAnalyzeLink(unittest.TestCase):
    """Test analyze_link function."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_analyze_link_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()

    def tearDown(self):
        """Clean up test environment."""
        # Clean up any links first
        for item in self.test_dir.rglob("*"):
            try:
                if item.is_symlink():
                    item.unlink()
                elif sys.platform == 'win32' and item.is_dir():
                    # Could be junction
                    try:
                        item.rmdir()
                    except OSError:
                        pass
            except OSError:
                pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_analyze_junction_to_destination(self):
        """analyze_link should correctly identify junction pointing to destination."""
        from preservelib.links import analyze_link

        link_path = self.src / "link_to_dest"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link_path), str(self.dst)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            info = analyze_link(link_path, self.dst)

            self.assertEqual(info.link_path, link_path)
            self.assertEqual(info.link_type, "junction")
            self.assertTrue(info.target_is_destination)
            self.assertFalse(info.is_broken)
            self.assertTrue(info.creates_cycle_with(self.dst))
        finally:
            if link_path.exists():
                link_path.rmdir()

    @unittest.skipUnless(hasattr(os, 'symlink'), "Symlink not available")
    @unittest.skipIf(sys.platform == 'win32', "Symlink test unreliable on Windows without admin")
    def test_analyze_symlink_inside_destination(self):
        """analyze_link should correctly identify symlink pointing inside destination."""
        from preservelib.links import analyze_link

        # Create a subdirectory in destination
        inside_dst = self.dst / "subdir"
        inside_dst.mkdir()

        link_path = self.src / "link_inside_dest"

        try:
            link_path.symlink_to(inside_dst)
        except OSError:
            self.skipTest("Could not create symlink (may need admin on Windows)")

        try:
            info = analyze_link(link_path, self.dst)

            self.assertEqual(info.link_type, "soft")
            self.assertTrue(info.target_inside_destination)
            self.assertTrue(info.creates_cycle_with(self.dst))
        finally:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()

    def test_analyze_broken_link(self):
        """analyze_link should correctly identify broken links."""
        from preservelib.links import analyze_link

        link_path = self.src / "broken_link"
        nonexistent = self.test_dir / "nonexistent"

        try:
            link_path.symlink_to(nonexistent)
        except OSError:
            self.skipTest("Could not create symlink")

        try:
            info = analyze_link(link_path, self.dst)

            self.assertTrue(info.is_broken)
            self.assertFalse(info.creates_cycle_with(self.dst))
        finally:
            if link_path.is_symlink():
                link_path.unlink()


class TestLinkReportCreatesField(unittest.TestCase):
    """Test that link_report includes creates_cycle field."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = Path(tempfile.mkdtemp(prefix='test_link_report_'))
        self.src = self.test_dir / "source"
        self.dst = self.test_dir / "destination"
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "file.txt").write_text("content")

    def tearDown(self):
        """Clean up test environment."""
        for item in self.test_dir.rglob("*"):
            try:
                if item.is_symlink():
                    item.unlink()
                elif sys.platform == 'win32' and item.is_dir():
                    try:
                        item.rmdir()
                    except OSError:
                        pass
            except OSError:
                pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_creates_cycle_true_for_cycle_link(self):
        """Link report should have creates_cycle=True for cycle-creating links."""
        link_path = self.src / "cycle_link"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link_path), str(self.dst)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            _, _, _, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )

            self.assertEqual(len(link_report), 1)
            self.assertIn('creates_cycle', link_report[0])
            self.assertTrue(link_report[0]['creates_cycle'])
        finally:
            if link_path.exists():
                link_path.rmdir()

    @unittest.skipIf(sys.platform != 'win32', "Junction test requires Windows")
    def test_creates_cycle_false_for_safe_link(self):
        """Link report should have creates_cycle=False for non-cycle links."""
        # Create a link to unrelated location
        unrelated = self.test_dir / "unrelated"
        unrelated.mkdir()

        link_path = self.src / "safe_link"

        import subprocess
        result = subprocess.run(
            ['cmd', '/c', 'mklink', '/J', str(link_path), str(unrelated)],
            capture_output=True, shell=True
        )
        if result.returncode != 0:
            self.skipTest("Could not create junction")

        try:
            _, _, _, link_report = detect_path_cycles_deep(
                [str(self.src)], str(self.dst), "MOVE"
            )

            self.assertEqual(len(link_report), 1)
            self.assertIn('creates_cycle', link_report[0])
            self.assertFalse(link_report[0]['creates_cycle'])
        finally:
            if link_path.exists():
                link_path.rmdir()


if __name__ == '__main__':
    unittest.main()
