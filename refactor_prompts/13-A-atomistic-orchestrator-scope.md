# Refactor 13-A — `atomistic.py` orchestrator scope-mapping + opportunistic extraction

**Worker prompt. (c) god-file decomposition — scope-map + leaf extraction if feasible.**

## Pre-read

1. `CLAUDE.md` (Three-Layer Law: atomistic positions are physical layer)
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #15 hardened-fail, #19/#20 leaf rules)
3. `REFACTOR_AUDIT.md` Findings #27 (09-B gromacs_helpers precedent), #29 (10-A namd_helpers precedent), #38 (Pass 11-A atomistic_helpers extract — pure-math chipped off; orchestrator remains)
4. `backend/core/atomistic.py` (2204 LOC) — read FULLY
5. `backend/core/atomistic_helpers.py` (483 LOC) — what was already extracted in Pass 11-A
6. `memory/REFERENCE_ATOMISTIC.md` if available

## Step 0 — CWD safety (precondition #15 HARDENED)

```bash
pwd
git rev-parse --show-toplevel
if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
    echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
    exit 1
fi
```

## Goal

Two acceptable outcomes:

1. **REFACTORED** — identify a clean leaf/sub-orchestrator extraction (e.g. PDB/PSF formatting cluster, atom-positioning sub-pipeline, frame-orientation helpers) AND execute it. Continue the 09-B/10-A/11-A template.

2. **INVESTIGATED** — produce a comprehensive closure-capture surface map for Pass 14+ god-file decomposition. Document:
   - All module-level mutable state (and which functions mutate it)
   - All factory/closure-scoped mutable state (and which methods capture it)
   - All shared scratch objects (numpy arrays, temp matrices)
   - The `build_atomistic_model` call graph (what calls what; depth of nesting)
   - Recommended decomposition strategy (record-passing? state-object factory? function-pure splits?)

Pick (1) if a clean leaf ≥ 100 LOC is identifiable. Otherwise (2).

## In scope

If REFACTORED:
- Identify a self-contained sub-cluster (suggested candidates from prior reads):
  - **PDB/PSF formatting cluster** — `_format_pdb_atom_line` (Pass 10-A reused for namd_package); is there an atomistic equivalent? Check if atomistic.py has its own atom-line writers separate from namd_package.
  - **Atom-positioning math** — `_atom_pos`, `_set_atom_pos`, `_translate_atom` (read-only / write-only pair pattern)
  - **Frame computation** — `_atom_frame`, `_extra_base_frame`
  - **Rigid-body transforms** — `_rb_extract`, `_rb_world`, `_rb_apply`
  - **Phosphate placement** — `_apply_phosphate`
- Move verbatim to a sibling module (e.g. `backend/core/atomistic_orchestrators.py` or `backend/core/atomistic_positioning.py` — pick the most descriptive name)
- Apply preconditions #19, #20 strictly
- Add unit tests for the extracted cluster (calibrated coverage target per #21)

If INVESTIGATED:
- No code change beyond the surface map
- Map should be actionable for Pass 14+ (Pass 12-B's renderer-map is the model)

## Out of scope

- Touching `_PHASE_*`, `_SUGAR`, `_FRAME_ROT_RAD`, `_ATOMISTIC_*` constants
- Modifying `_apply_backbone_torsions` semantics (atomistic calibration workstream)
- The atomistic-helpers extract already done in Pass 11-A (don't re-extract)
- Subprocess wrappers (different template)

## Verification

3× baseline + lint per #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/13A_test_pre$i.txt 2>&1; done
just lint > /tmp/13A_lint_pre.txt 2>&1
```

Post (REFACTORED case):
- atomistic.py LOC decreases by ≥ 100 LOC
- New module exists with leaf-pure imports (check precondition #19)
- Tests for the new module pass
- Failure set ⊆ baseline
- Lint Δ ≤ 0

Post (INVESTIGATED case):
- No code change in backend/
- Detailed surface map returned in worker output

## Stop conditions

- Step 0 fails → STOP (literal `exit 1`)
- Any extraction breaks `_apply_backbone_torsions` or `build_atomistic_model` semantics → revert, STOP
- `_PHASE_*` constant touched → STOP
- Test failure not in baseline → revert, STOP
- Closure-capture surface for candidate extraction exceeds 8 refs → declare INVESTIGATED

## Output (Findings #44)

If REFACTORED:
- Functions moved (list + LOC each)
- atomistic.py LOC delta
- New module size + import list (proves leaf purity)
- Test count + coverage
- Lint Δ
- Closure-capture surface map for REMAINING extraction surface (queued Pass 14+)

If INVESTIGATED:
- Full closure-capture surface map
- Recommended decomposition strategy
- 3+ specific extraction candidates for Pass 14+ (function name + estimated LOC + closure-capture surface for each)
- Lint Δ (should be 0; no code change)

## Do NOT

- Modify `_apply_backbone_torsions` semantics
- Touch `_PHASE_*` / `_SUGAR` / `_FRAME_ROT_RAD`
- Re-extract already-moved helpers from Pass 11-A
- Commit / append to REFACTOR_AUDIT.md
