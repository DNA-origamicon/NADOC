#!/usr/bin/env python3
"""Headlessly regenerate the test fixtures that HAVE a code-based build path, and report the
ones that DON'T (a regeneration gap → design-automation backlog).

Motivation: a test fixture whose only provenance is a hand-saved ``.nadoc`` silently drifts when
the builder evolves (the 2x6 hinge golden was overwritten with a *routed* design and no longer
matched ``build_hinge_primitive``). Every fixture should be reproducible from code so drift is a
deliberate, reviewable regen — never a stale mystery.

Usage:
    uv run python scripts/regen_test_fixtures.py            # report only (no writes)
    uv run python scripts/regen_test_fixtures.py --write    # regenerate the buildable fixtures

Buildable today (regenerated with --write):
    workspace/Primitives/{2x2_single,2x4_double,2x6_triple}_hinge_link.nadoc
        ← build_hinge_primitive(name)  (UNROUTED primitive; pinned by
          tests/test_headless_hinge_build.py::test_build_*_matches_golden)
    tests/fixtures/relax_2x2_{binding,closebond}.nadoc
        ← build_applied_2x2_binding(close_bond=...)  (two-leaf hinge + applied end-to-root
          duplex + hinge joint; closebond = over-compressed pose; pinned by the six
          test_duplex_*/relax_2x2 files + test_headless_hinge_build::test_build_applied_2x2_*)

GAPS (no headless builder yet — see design_automation_backlog.md AF-FIXTURES):
    tests/fixtures/test343.nadoc               — hand-saved, no builder
    tests/fixtures/10-6-10hb_seamed.nadoc      — hand-saved, no builder
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
PRIMITIVES = REPO / "workspace" / "Primitives"

# name → (output path, builder thunk). Extend as headless builders land for the gaps below.
FIXTURES = REPO / "tests" / "fixtures"


def _hinge(name):
    from backend.api.headless_hinge_build import build_hinge_primitive
    return build_hinge_primitive(name)


def _applied_2x2(close_bond):
    from backend.api.headless_hinge_build import build_applied_2x2_binding
    return build_applied_2x2_binding(close_bond=close_bond)


BUILDABLE = {
    "2x2_single_hinge_link": (PRIMITIVES / "2x2_single_hinge_link.nadoc", lambda: _hinge("2x2_single_hinge_link")),
    "2x4_double_hinge_link": (PRIMITIVES / "2x4_double_hinge_link.nadoc", lambda: _hinge("2x4_double_hinge_link")),
    "2x6_triple_hinge_link": (PRIMITIVES / "2x6_triple_hinge_link.nadoc", lambda: _hinge("2x6_triple_hinge_link")),
    "relax_2x2_binding":   (FIXTURES / "relax_2x2_binding.nadoc", lambda: _applied_2x2(False)),
    "relax_2x2_closebond": (FIXTURES / "relax_2x2_closebond.nadoc", lambda: _applied_2x2(True)),
}

# Fixtures with NO headless builder yet (regeneration gap). Kept here so the report is honest.
GAPS = [
    ("tests/fixtures/test343.nadoc", "hand-saved, no builder"),
    ("tests/fixtures/10-6-10hb_seamed.nadoc", "hand-saved, no builder"),
]


def main() -> int:
    write = "--write" in sys.argv
    print(f"== regen_test_fixtures ({'WRITE' if write else 'report-only'}) ==\n")

    print("Buildable (headless builder exists):")
    for name, (path, build) in BUILDABLE.items():
        design = build()
        n = len(design.strands)
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(design.to_json(), encoding="utf-8")
            print(f"  [written] {path.relative_to(REPO)}  ({n} strands)")
        else:
            exists = "present" if path.exists() else "MISSING"
            print(f"  [{exists}] {path.relative_to(REPO)}  (builder → {n} strands)")

    print("\nGAPS (no headless builder — see design_automation_backlog.md AF-FIXTURES):")
    for rel, why in GAPS:
        exists = "present" if (REPO / rel).exists() else "MISSING"
        print(f"  [{exists}] {rel}  — {why}")

    if not write:
        print("\n(run with --write to regenerate the buildable fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
