#!/usr/bin/env python3
"""Verify the checked-in test fixtures against the digests in PROVENANCE.md.

The fixture set under ``tests/data/`` is what makes a clean checkout able to run
``python3 -m pytest -q``. That only stays true if the set is exactly what the
repository says it is: a file that quietly changed, a fixture that was added
without provenance, or a fixture that went missing all silently weaken the
tests that depend on it.

This check is deliberately strict in both directions -- missing files AND
unexpected files -- because "the tests still pass" is not evidence when a test
skipped itself for a missing golden.

    python3 tests/data/verify_fixtures.py            # verify
    python3 tests/data/verify_fixtures.py --list     # print the table

Exit codes: 0 everything matches; 1 a mismatch; 2 the provenance table itself is
unreadable (a setup problem, not a finding).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVENANCE = HERE / "PROVENANCE.md"
# `| `path` | 1234 | `sha256` |`
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-f]{64})`\s*\|$")
# The document itself is not a fixture; it is the manifest of them. This script
# is the checker, not data: listing its own digest would make every edit to the
# checker a fixture change, and it cannot contain its own hash anyway.
SKIP = {"PROVENANCE.md", "verify_fixtures.py"}


def expected() -> dict[str, tuple[int, str]]:
    if not PROVENANCE.exists():
        raise FileNotFoundError(f"missing {PROVENANCE}")
    table: dict[str, tuple[int, str]] = {}
    for line in PROVENANCE.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line.strip())
        if match:
            name, size, digest = match.groups()
            table[name] = (int(size), digest)
    if not table:
        raise ValueError(f"{PROVENANCE} lists no fixtures")
    return table


def actual() -> dict[str, tuple[int, str]]:
    found: dict[str, tuple[int, str]] = {}
    for path in sorted(HERE.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(HERE))
        if rel in SKIP:
            continue
        # Compiled Python and editor droppings are not fixtures; they are what
        # running the checker leaves behind.
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        found[rel] = (path.stat().st_size,
                      hashlib.sha256(path.read_bytes()).hexdigest())
    return found


def verify() -> list[str]:
    want, have = expected(), actual()
    problems: list[str] = []
    for name, (size, digest) in sorted(want.items()):
        if name not in have:
            problems.append(f"missing: {name}")
            continue
        got_size, got_digest = have[name]
        if got_size != size:
            problems.append(f"size changed: {name} ({got_size} != {size})")
        if got_digest != digest:
            problems.append(f"digest changed: {name} ({got_digest[:16]}… != {digest[:16]}…)")
    for name in sorted(set(have) - set(want)):
        problems.append(f"unlisted: {name} (add it to PROVENANCE.md with its digest)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true",
                        help="print the expected table and exit")
    args = parser.parse_args()
    try:
        table = expected()
    except (OSError, ValueError) as exc:
        print(f"cannot read the provenance table: {exc}", file=sys.stderr)
        return 2
    if args.list:
        for name, (size, digest) in sorted(table.items()):
            print(f"{digest}  {size:>9}  {name}")
        print(f"{len(table)} fixtures, {sum(s for s, _ in table.values())} bytes")
        return 0
    problems = verify()
    if problems:
        print(f"fixture check FAILED ({len(problems)}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"fixture check OK: {len(table)} files, "
          f"{sum(s for s, _ in table.values())} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
