"""Write-side dazzlelink CLI flags for COPY / MOVE.

Regression guard: handlers/copy.py and handlers/move.py read args.dazzlelink /
dazzlelink_mode / dazzlelink_dir via hasattr, but cli.py never registered the
write-side --dazzlelink flag -- so `preserve COPY ... --dazzlelink` errored as
"unrecognized arguments" and the .dazzlelink creation path was unreachable.
_add_dazzlelink_create_args now wires it for COPY and MOVE.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preserve.cli import create_parser


def test_copy_parser_registers_dazzlelink_create_flags(tmp_path):
    """--dazzlelink (write-side) is a recognized COPY argument. Without the fix
    this parse raises SystemExit (unrecognized arguments)."""
    parser = create_parser()
    src = tmp_path / "a.txt"
    src.write_text("x")
    args = parser.parse_args([
        "COPY", str(src), "--dst", str(tmp_path / "out"),
        "--dazzlelink", "--dazzlelink-mode", "open",
    ])
    assert args.dazzlelink is True
    assert args.dazzlelink_mode == "open"


def test_move_parser_registers_dazzlelink_create_flag(tmp_path):
    """MOVE shares the same write-side handler, so it gets the flag too."""
    parser = create_parser()
    src = tmp_path / "a.txt"
    src.write_text("x")
    args = parser.parse_args([
        "MOVE", str(src), "--dst", str(tmp_path / "out"), "--dazzlelink",
    ])
    assert args.dazzlelink is True


def test_dazzlelink_mode_defaults_to_info(tmp_path):
    parser = create_parser()
    src = tmp_path / "a.txt"
    src.write_text("x")
    args = parser.parse_args(["COPY", str(src), "--dst", str(tmp_path / "out")])
    # Absent --dazzlelink-mode -> 'info' (matches the handler's hasattr default).
    assert getattr(args, "dazzlelink_mode", "info") == "info"
    assert args.dazzlelink is False


def _have_linklib():
    try:
        import dazzle_linklib  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _have_linklib(),
                    reason="dazzle-linklib ([dazzlelink] extra) not installed")
def test_copy_dazzlelink_creates_files(tmp_path):
    """End-to-end: COPY --dazzlelink writes a .dazzlelink per preserved file."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("alpha")
    (src / "b.txt").write_text("bravo")
    dst = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "preserve", "COPY",
         str(src / "a.txt"), str(src / "b.txt"),
         "--dst", str(dst), "--dazzlelink"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    dls = list(dst.rglob("*.dazzlelink"))
    assert len(dls) == 2, f"expected 2 .dazzlelink files, got {[p.name for p in dls]}"
