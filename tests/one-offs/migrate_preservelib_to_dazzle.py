"""Rewire preserve's `preservelib` imports to `dazzle_preservelib` (P3 step 10).

The L3 library was extracted to `dazzle-preservelib` (the lifted, filekit/
linklib-delegating preservelib). This script rewrites preserve's CLI source and
test imports from the embedded `preservelib` to the installed
`dazzle_preservelib`, proving the lifted lib is a drop-in by running preserve's
own suite against it.

SCOPE: only `preserve/` (the CLI package) and `tests/` are rewritten. The
top-level embedded `preservelib/` package is left untouched (reversibility +
A/B comparison; its deletion is a separate later step).

Only import STATEMENTS are changed (lines whose stripped form starts with
`from preservelib` or `import preservelib`) -- comments/strings are left alone.
`from preservelib` does not match the already-rewritten `from dazzle_preservelib`
(the `dazzle_` infix), so the transform is idempotent.

Usage:
    python tests/one-offs/migrate_preservelib_to_dazzle.py            # dry-run
    python tests/one-offs/migrate_preservelib_to_dazzle.py --apply    # write
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # .../preserve
SCOPES = [REPO / "preserve", REPO / "tests"]

# Anchored to import statements only (leading whitespace allowed).
FROM_RE = re.compile(r"^(\s*)from preservelib(\b)")
IMPORT_RE = re.compile(r"^(\s*)import preservelib(\b)")
# Dotted-module STRING references (mock.patch targets, logger-name assertions):
# 'dazzle_preservelib.verification.X' -> 'dazzle_preservelib.verification.X'. The
# leading quote stops it matching the already-rewritten 'dazzle_preservelib.'.
STR_RE = re.compile(r"(['\"])preservelib\.")


def rewrite_text(text: str) -> tuple[str, int]:
    out, n = [], 0
    for line in text.splitlines(keepends=True):
        new = FROM_RE.sub(r"\1from dazzle_preservelib\2", line)
        new = IMPORT_RE.sub(r"\1import dazzle_preservelib\2", new)
        new = STR_RE.sub(r"\1dazzle_preservelib.", new)
        if new != line:
            n += 1
        out.append(new)
    return "".join(out), n


def main() -> int:
    apply = "--apply" in sys.argv
    total_files, total_lines = 0, 0
    for scope in SCOPES:
        for py in sorted(scope.rglob("*.py")):
            # newline="" preserves the file's existing CRLF/LF exactly (no
            # translation on read or write) so the diff is import-only.
            with open(py, "r", encoding="utf-8", newline="") as f:
                text = f.read()
            new_text, n = rewrite_text(text)
            if n:
                total_files += 1
                total_lines += n
                rel = py.relative_to(REPO)
                print(f"  {'[WRITE]' if apply else '[DRY] '} {rel}: {n} import line(s)")
                if apply:
                    with open(py, "w", encoding="utf-8", newline="") as f:
                        f.write(new_text)
    print(f"\n{'APPLIED' if apply else 'DRY-RUN'}: {total_lines} import line(s) "
          f"across {total_files} file(s).")
    if not apply:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
