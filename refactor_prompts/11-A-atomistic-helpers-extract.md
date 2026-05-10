# Refactor 11-A — `atomistic.py` pure-helper extraction + tests

**Worker prompt. (c)+(test) — same template as 09-B (gromacs_helpers) + 10-A (namd_helpers). Third application of the proven pattern.**

## Pre-read

1. `CLAUDE.md` (Three-Layer Law: atomistic positions are physical layer — read-only output; never write back to topology)
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #19 leaf-rule split, #20 dead-import sweep, #21 calibrated coverage targets)
3. `REFACTOR_AUDIT.md` Findings #27 (09-B gromacs_helpers precedent), #29 (10-A namd_helpers precedent)
4. `REFACTOR_AUDIT.md` audit-log row "2026-05-10 | policy" — atomistic family **UNLOCKED**; this is the first atomistic refactor in scope
5. `memory/REFERENCE_ATOMISTIC.md` (Phase AA template + PDB/PSF export specifics) — load if available
6. `backend/core/atomistic.py` — read FULLY before identifying pure-helper candidates (2602 LOC; budget time accordingly)

## Step 0 — CWD safety

```bash
pwd
git rev-parse --show-toplevel
# Must equal $WORKTREE_PATH. If not, STOP and report (precondition #15).
```

## Goal

Identify and extract **pure-text/pure-math helpers** from `atomistic.py` to a new module `backend/core/atomistic_helpers.py`. Add unit tests with calibrated coverage target per precondition #21.

**Pure-helper definition** (load-bearing):
- No `subprocess` calls
- No `os.system` / `os.environ` mutation (reads OK if absolutely required)
- No `pathlib` / `open(...)` filesystem I/O
- No mutable global state
- Returns its output (str / numeric / dict / Design instance) — does not write to disk
- Imports limited to: `__future__`, math/numpy, `backend.core.models` (Design + related types), `backend.core.constants` (B-DNA constants)

The helper's body should be testable with synthetic inputs and pure-output assertions.

## In scope

1. **Read all 2602 LOC of atomistic.py.** Identify functions matching the pure-helper definition. Likely candidates (verify by reading the function bodies):
   - PDB/PSF text formatting helpers (atom-line formatters, residue-name normalizers)
   - Pure-math helpers (Bezier curve evaluation, sugar pucker phase calculation, glycosidic angle computation)
   - Template lookup / interpolation (nucleotide template selection from B-DNA tables)
   - Cost-function leaves (`_repulsion_cost`, `_glycosidic_cost`, `_backbone_bridge_cost`, etc.) — Pass 5-C surfaced these as @60 vulture candidates; verify which are pure-math

2. Move ≥3 functions (or ≥150 LOC of helper code, whichever is smaller) to `backend/core/atomistic_helpers.py`. Match each move with a unit test class.

3. Re-import the moved names back into `atomistic.py` so external callers continue to work. Use `# noqa: F401` only where strictly necessary (per precondition #20: dead-import sweep — drop any moved symbol that has zero remaining call sites in `atomistic.py`).

4. Apply precondition #19 (leaf rule split): the new helpers file may import `__future__`, math/numpy, `backend.core.models`, `backend.core.constants`. MUST NOT import from `atomistic.py` itself or any other backend.core module that would create a cycle.

## Out of scope

- The atomistic optimization orchestrator (`build_atomistic_design`, `_apply_backbone_torsions`, etc.) — these are the god-file core that needs closure-capture analysis (deferred to Pass 12+ god-file decomposition).
- Subprocess wrappers (mrdna invocation, GROMACS/NAMD command builders) — different template needed.
- `_PHASE_*` constants in `backend/core/lattice.py` — LOCKED.
- The atomistic UI in `frontend/src/scene/atomistic_renderer.js` — separate Pass 11+ candidate.
- `_SUGAR` template label/docstring drift apparent-bug (Finding #18) — calibration-workstream task; don't touch.
- Modifying any current behavior of moved functions. Move bodies verbatim.

## Verification

3× baseline + lint pre/post per precondition #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/11A_test_pre$i.txt 2>&1; done
just lint > /tmp/11A_lint_pre.txt 2>&1
```

After move:
- `backend/core/atomistic.py` LOC decreases by the moved amount
- `backend/core/atomistic_helpers.py` exists with imports + helpers
- Tests for the new module pass
- Test failure set ⊆ stable_baseline ∪ KNOWN_FLAKES
- Lint Δ ≤ 0
- Coverage on `atomistic_helpers.py` ≥ 90% (per Pass 9-B + 10-A precedent)

```bash
just test-file tests/test_atomistic_helpers.py 2>&1 | tail -5
just test-file tests/test_atomistic_helpers.py --cov=backend.core.atomistic_helpers --cov-report=term 2>&1 | tail -10
just lint > /tmp/11A_lint_post.txt 2>&1
```

## Stop conditions

- Step 0 fails → STOP
- Fewer than 3 pure-helper candidates identifiable → STOP, report ("atomistic.py has too few pure-helpers; god-file decomposition needs closure-capture analysis instead")
- Any moved function depends on closure-captured state from `atomistic.py` module body (mutable globals, module-private caches) → STOP, scope tangled
- Any moved function reads a `_PHASE_*` constant directly → STOP, locked area
- Test failure not in baseline → revert, STOP
- Lint Δ > 0 → revert (likely an unused-import F401)

## Output (Findings #38)

Required:
- Functions moved (list with LOC each)
- atomistic.py LOC delta
- atomistic_helpers.py size + import list (proves leaf purity)
- Test count + per-class breakdown
- Coverage % on atomistic_helpers.py
- Lint Δ
- Apparent-bug flags (if any; do NOT fix per `feedback_interrupt_before_doubting_user.md`)
- Linked: #18 (apparent-bug history), #27 (gromacs_helpers precedent), #29 (namd_helpers precedent), policy row 2026-05-10 (atomistic unlock)

## USER TODO template

Atomistic refactors don't typically need an in-app smoke test if the pure-helpers are mathematical (no UI surface). If any moved helper is exercised in a user-visible path (e.g. PDB export atom-line formatting visible in exported file), include a USER TODO:

1. `just dev` and load any saved `.nadoc` with atomistic data (or generate via Phase AA workflow)
2. Export PDB; visually verify atom lines look correct (column alignment, residue numbering, chain IDs)
3. If clean, mark Finding #38 as USER VERIFIED.

## Do NOT

- Touch the atomistic orchestrator (`build_atomistic_design` core)
- Touch `_PHASE_*` constants
- Move impure functions (subprocess, file I/O)
- Change function bodies (move verbatim)
- Commit / append to REFACTOR_AUDIT.md (manager aggregates)
