#!/usr/bin/env python3
"""Change-based backend test selection (a safe, hand-rolled substitute for the
broken pytest-testmon on pytest 9.x).

SLOW-LOCK (the headline rule): heavy (``slow``) tests NEVER run outside a
test-dedicated session (``just test-session``, TTY-only — see scripts/test_session.sh).
Outside one, a FULL/AREAS verdict is downgraded to the fast suite and the owed heavy
groups are parked in ``.nadoc-slow-pending``, where they accumulate until the user opens
a session and runs ``just test-slow`` / ``just test``. So in a normal coding session this
script's answer is always "the fast suite" — under a minute, every time.

The fast suite (``-m "not slow"``, ~21s) is CHEAP and covers every area's unit
tests, so it ALWAYS runs. This script only decides which HEAVY (``slow``) groups
are OWED, based on what source files changed:

  * Change a foundational module (geometry, models, lattice, deformation,
    shared API/infra) -> run EVERYTHING. Broad blast radius.
  * Change a leaf subsystem (oxDNA, CanDo/FEM, NAMD, mrdna, atomistic, MD,
    headless build) -> run the fast suite + only that subsystem's slow group.
  * Change something unrecognized under backend/ -> run EVERYTHING (safe default).
  * Only frontend / docs changed -> fast suite only (run `just test-frontend`
    separately for JS).

Safety property: because the fast suite always runs, a wrong area mapping can at
worst skip a heavy *simulation* test whose fast-suite cousins still ran -- it can
never open a hole in basic geometry/topology coverage.

Usage:
    python scripts/select_tests.py            # vs working-tree changes (uncommitted)
    python scripts/select_tests.py --since-last-full  # vs the last full-suite pass
    python scripts/select_tests.py --base origin/master   # everything since a ref
    python scripts/select_tests.py --dry-run  # print the decision + pytest cmd, don't run

``--since-last-full`` (the default for ``just test-smart``) diffs against the git
SHA recorded the last time the FULL suite passed on THIS machine (stored in the
gitignored ``.nadoc-test-watermark`` at the repo root). This makes affected slow
groups accumulate across sessions/commits: committing your work no longer hides
it from the scope. Whenever this script's decision is FULL and pytest passes, the
watermark is bumped to HEAD, so the expensive full run is only needed before a
push or when a foundational file changes. No watermark yet (fresh clone) -> FULL,
which then establishes the baseline.

Runs pytest with the computed ``-m`` expression and the repo's standard
``-n auto --dist loadfile``. Extra args after ``--`` are forwarded to pytest.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

# Machine-local marker: git SHA at which the FULL suite last passed here. Gitignored
# (each computer tracks its own baseline; never synced). Bumped on any FULL pass.
WATERMARK_FILE = ".nadoc-test-watermark"

# Machine-local: the test-dedicated-session window (scripts/test_session.sh, TTY-only).
# NO SLOW TEST RUNS WITHOUT IT. Outside such a window this script downgrades any
# slow-group selection to the fast suite and *defers* the groups instead.
SESSION_FILE = ".nadoc-test-session"

# Machine-local: heavy groups a change has made stale but that were deferred because
# no test-dedicated session was open. Accumulates across sessions/commits; drained by
# the next slow run inside a session. Holds area names, or the single word FULL.
PENDING_FILE = ".nadoc-slow-pending"

# Area markers that exist on slow tests (must match tests/conftest.py AREA_MARKERS
# and the markers registered in pyproject.toml).
KNOWN_AREAS = ("oxdna", "cando", "namd", "mrdna", "atomistic", "md", "headless")

# --- Foundational / shared source: any change here forces the FULL suite. ------
# Broad reverse-dependency fan-in (measured: models 137, geometry/constants 37,
# atomistic 38, deformation 24, lattice 16), or shared test/build infrastructure.
FULL_TRIGGER_SUBSTRINGS = (
    # foundational geometry / topology core
    "backend/core/lattice.py",
    "backend/core/geometry.py",
    "backend/core/design_geometry.py",
    "backend/core/models.py",
    "backend/core/constants.py",
    "backend/core/deformation.py",
    "backend/core/duplex.py",
    "backend/core/bp_indexing.py",
    "backend/core/bp_analysis.py",
    "backend/core/crossover_positions.py",
    "backend/core/loop_skip_calculator.py",
    "backend/core/instance_layout.py",
    "backend/core/design_diff.py",
    # the atomistic BASE (fan-in 38 across pdb/namd/md/protein/cando) — broad
    "backend/core/atomistic.py",
    "backend/core/atomistic_helpers.py",
    "backend/core/atomistic_cache.py",
    "backend/core/atomistic_to_nadoc.py",
    "backend/core/atomistic_minimisers.py",
    "backend/core/cg_to_atomistic.py",
    # shared execution / engine layer feeding every real-sim runner
    "backend/core/md_executor.py",
    "backend/core/engines.py",
    "backend/core/engine_artifact.py",
    "backend/core/engine_install.py",
    # shared API surface + global state
    "backend/api/main.py",
    "backend/api/ws.py",
    "backend/api/state",
    # test / build infra
    "tests/conftest.py",
    "pyproject.toml",
    "uv.lock",
    "justfile",
)

# --- Leaf areas: (substring in changed path) -> set of slow area markers. -------
# Order matters (first hit classifies the file). Everything here has a narrow,
# well-understood blast radius contained within the listed area(s).
LEAF_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("oxdna", ("oxdna",)),
    ("oxpy", ("oxdna",)),
    ("skip_twist", ("oxdna",)),
    ("efield", ("oxdna",)),
    ("field", ("oxdna",)),
    ("cando", ("cando",)),
    ("fem_solver", ("cando",)),
    ("physics/fem", ("cando",)),
    # SNUPI = the native FEM shape predictor (backend/physics/snupi_*.py,
    # backend/core/snupi_{job,runner}.py). Its heavy solve tests are in the
    # "cando" heavy group, so its source must select that group too.
    ("snupi", ("cando",)),
    ("namd", ("namd",)),
    ("mrdna", ("mrdna",)),
    ("arbd", ("mrdna",)),
    # protein hybrids run in the oxDNA fork -> protein source touches oxdna slow
    ("protein", ("oxdna",)),
    ("conjugation", ("oxdna",)),
    ("benchmark", ("md",)),
    ("openmm", ("md",)),
    # atomistic_validation.py is a leaf (the atomistic BASE is a full-trigger above)
    ("atomistic_validation", ("atomistic",)),
    # per-frame / trajectory / health MD leaves (md_executor is a full-trigger above)
    ("md_", ("md",)),
    ("dcd_", ("md",)),
    ("trajectory", ("md",)),
    # headless routing / build pipeline
    ("hinge_router", ("headless",)),
    ("hinge_weave", ("headless",)),
    ("hinge_ladder", ("headless",)),
    ("scaffold", ("headless",)),
    ("seamless", ("headless",)),
    ("autoscaffold", ("headless",)),
    ("build_spec", ("headless",)),
    ("headless", ("headless",)),
]


def repo_root() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def read_watermark() -> str | None:
    """Return the SHA at which the full suite last passed here, or None if unset."""
    path = os.path.join(repo_root(), WATERMARK_FILE)
    try:
        with open(path) as fh:
            sha = fh.read().strip()
    except FileNotFoundError:
        return None
    return sha or None


def write_watermark() -> str:
    """Record current HEAD as the last full-suite pass. Returns the SHA written."""
    root = repo_root()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()
    with open(os.path.join(root, WATERMARK_FILE), "w") as fh:
        fh.write(head + "\n")
    return head


def session_open() -> bool:
    """True iff a test-dedicated session window is open (see scripts/test_session.sh).
    Only inside one may slow tests run."""
    if os.environ.get("NADOC_TEST_FORCE") == "1":
        return True
    path = os.path.join(repo_root(), SESSION_FILE)
    try:
        with open(path) as fh:
            expiry = int(fh.readline().strip())
    except (OSError, ValueError):
        return False
    return expiry > int(time.time())


def read_pending() -> set[str]:
    """Heavy groups deferred by earlier non-dedicated sessions. {'FULL'} means the
    whole suite is owed (a foundational change landed)."""
    path = os.path.join(repo_root(), PENDING_FILE)
    try:
        with open(path) as fh:
            return {ln.strip() for ln in fh if ln.strip()}
    except OSError:
        return set()


def write_pending(groups: set[str]) -> None:
    path = os.path.join(repo_root(), PENDING_FILE)
    if not groups:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    if "FULL" in groups:
        groups = {"FULL"}  # FULL subsumes every area
    with open(path, "w") as fh:
        fh.write("\n".join(sorted(groups)) + "\n")


def changed_files(base: str | None) -> list[str]:
    """Return repo-relative changed paths. Default (base=None) = uncommitted
    working-tree + staged + untracked. With base=REF = everything since REF."""
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if base:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        # also include still-uncommitted changes on top of the ref
        out += subprocess.run(
            ["git", "diff", "--name-only", base],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        files = set(out.split())
    else:
        # porcelain covers modified, staged, and untracked in one shot
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        files = set()
        for line in out.splitlines():
            if not line.strip():
                continue
            path = line[3:]
            if " -> " in path:  # rename: take the destination
                path = path.split(" -> ", 1)[1]
            files.add(path.strip())
    return sorted(files)


def classify(files: list[str]) -> tuple[str, set[str], list[str]]:
    """Return (decision, areas, reasons).
    decision: 'FULL' | 'AREAS' | 'FAST' | 'NONE'."""
    backend_or_tests = [
        f for f in files
        if (f.startswith("backend/") or f.startswith("tests/")
            or f in ("pyproject.toml", "uv.lock", "justfile", "conftest.py"))
    ]
    reasons: list[str] = []

    if not backend_or_tests:
        if files:
            reasons.append("only frontend/docs/other changed -> fast suite only "
                           "(run `just test-frontend` for JS)")
            return "FAST", set(), reasons
        reasons.append("no changes detected")
        return "NONE", set(), reasons

    # 1) Any foundational / shared change -> FULL.
    for f in backend_or_tests:
        for trig in FULL_TRIGGER_SUBSTRINGS:
            if trig in f:
                reasons.append(f"FULL: {f} matches foundational/shared '{trig}'")
                return "FULL", set(), reasons

    # 2) Classify each remaining file as a leaf area, else FULL (unknown).
    areas: set[str] = set()
    for f in backend_or_tests:
        # A changed TEST file: just run that file's area (or itself). Map via its
        # own name through the same leaf rules; unknown test file -> FULL to be safe.
        hit = None
        for sub, ars in LEAF_RULES:
            if sub in f:
                hit = ars
                reasons.append(f"{f} -> {'+'.join(ars)} (leaf '{sub}')")
                break
        if hit is None:
            reasons.append(f"FULL: {f} is under backend/tests but matches no leaf "
                           f"rule (unknown blast radius)")
            return "FULL", set(), reasons
        areas.update(hit)

    return "AREAS", areas, reasons


def build_pytest_cmd(decision: str, areas: set[str], extra: list[str]) -> list[str] | None:
    base = ["uv", "run", "pytest", "tests/", "-n", "auto", "--dist", "loadfile"]
    if decision == "FULL":
        cmd = base  # no -m: run everything
    elif decision == "AREAS":
        expr = " or ".join(["not slow", *sorted(areas)])
        cmd = base + ["-m", expr]
    elif decision == "FAST":
        cmd = base + ["-m", "not slow"]
    else:  # NONE
        return None
    return cmd + extra


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None,
                    help="git ref to diff against (e.g. origin/master). "
                         "Default: uncommitted working-tree changes.")
    ap.add_argument("--since-last-full", action="store_true",
                    help="diff against the last full-suite pass on this machine "
                         f"(SHA in {WATERMARK_FILE}); no watermark yet -> FULL. "
                         "This is the default for `just test-smart`.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the decision + pytest command, don't run it.")
    ap.add_argument("pytest_args", nargs="*",
                    help="extra args forwarded to pytest (put after --).")
    args = ap.parse_args()

    # --since-last-full resolves the diff base from the watermark. If there is no
    # watermark (or the recorded SHA is gone after a rebase/gc), we can't scope
    # safely -> force FULL, which then re-establishes the baseline on a green run.
    force_full = False
    base = args.base
    if args.since_last_full and base is None:
        wm = read_watermark()
        if wm and subprocess.run(["git", "cat-file", "-e", wm],
                                 cwd=repo_root()).returncode == 0:
            base = wm
        else:
            force_full = True

    files = changed_files(base)
    if force_full:
        decision, areas, reasons = "FULL", set(), [
            f"FULL: no valid {WATERMARK_FILE} baseline -> full run establishes it"]
    else:
        decision, areas, reasons = classify(files)

    print("=== select_tests: change-based test selection ===", file=sys.stderr)
    print(f"changed files ({len(files)}):", file=sys.stderr)
    for f in files[:40]:
        print(f"  {f}", file=sys.stderr)
    if len(files) > 40:
        print(f"  ... (+{len(files) - 40} more)", file=sys.stderr)
    print("routing:", file=sys.stderr)
    for r in reasons:
        print(f"  {r}", file=sys.stderr)

    # --- Slow-lock: heavy groups only run inside a test-dedicated session -------
    # Outside one, a FULL/AREAS verdict is DOWNGRADED to the fast suite and the owed
    # heavy groups are parked in .nadoc-slow-pending. They accumulate there until the
    # user opens a session (`just test-session`) and runs `just test-slow` / `just test`.
    pending = read_pending()
    in_session = session_open()
    deferred_now: set[str] = set()

    if not in_session:
        if decision == "FULL":
            deferred_now = {"FULL"}
        elif decision == "AREAS":
            deferred_now = set(areas)
        if deferred_now:
            decision, areas = "FAST", set()
    else:
        # In a session, drain what earlier sessions deferred on top of today's verdict.
        if "FULL" in pending:
            decision, areas = "FULL", set()
        elif pending and decision == "AREAS":
            areas |= (pending & set(KNOWN_AREAS))
        elif pending and decision in ("FAST", "NONE"):
            decision, areas = "AREAS", (pending & set(KNOWN_AREAS))

    cmd = build_pytest_cmd(decision, areas, args.pytest_args)
    if cmd is None:
        print("decision: NONE -> nothing to run.", file=sys.stderr)
        return 0

    label = {"FULL": "FULL suite", "AREAS": f"fast + slow[{'+'.join(sorted(areas))}]",
             "FAST": "fast suite only"}[decision]
    print(f"decision: {decision}  ({label})"
          f"{'  [test-dedicated session OPEN]' if in_session else ''}", file=sys.stderr)

    if deferred_now:
        owed = "the FULL suite" if "FULL" in deferred_now else \
            f"slow[{'+'.join(sorted(deferred_now))}]"
        print(f"\n  DEFERRED: this change would have needed {owed}, but no "
              f"test-dedicated\n  session is open, so only the fast suite ran. Parked in "
              f"{PENDING_FILE}.\n  Ask the user to run `just test-session` (their terminal), "
              f"then `just test-slow`.\n", file=sys.stderr)

    print(f"$ {' '.join(cmd)}", file=sys.stderr)
    if args.dry_run:
        return 0

    if deferred_now and not args.dry_run:
        write_pending(pending | deferred_now)

    rc = subprocess.call(cmd, cwd=os.getcwd())

    if rc == 0 and in_session:
        # A green heavy run settles the debt it covered.
        if decision == "FULL":
            # Fresh baseline: subsequent scoped runs only re-test what changes after this.
            sha = write_watermark()
            write_pending(set())
            print(f"watermark: {WATERMARK_FILE} -> {sha[:12]} (full suite passed); "
                  f"{PENDING_FILE} cleared", file=sys.stderr)
        elif decision == "AREAS":
            write_pending(pending - areas)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
