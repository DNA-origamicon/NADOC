# Refactor 13-F — `atomistic_renderer.js` closure-capture decomposition

**Worker prompt. (c) frontend god-file decomposition — first record-passing refactor in this codebase. Consume Pass 12-B's surface map.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #15 hardened-fail, #19 leaf rule split, #24 tangled-scope pre-pass pattern)
3. **`REFACTOR_AUDIT.md` Finding #42 (Pass 12-B atom_palette leaf extract + DETAILED CLOSURE-CAPTURE SURFACE MAP)** — this is the load-bearing input
4. `frontend/src/scene/atomistic_renderer.js` (498 LOC post-12-B) — read FULLY
5. `frontend/src/scene/atomistic_renderer/atom_palette.js` (33 LOC post-12-B) — already-extracted leaf reference
6. Pattern reference: 12-B's surface map recommends "introduce `_state` object inside factory + extract pure helpers taking `(state, ...args)`"

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

Per Pass 12-B's surface map, decompose atomistic_renderer.js's factory closure by:

1. **Introducing `_state` object** inside the factory containing the factory-scoped mutable state:
   `_elementMeshes`, `_elementAtoms`, `_elementRadius`, `_bondMesh`, `_bondAtomPairs`, `_lastSel`, `_lastMulti`, `scene`, `_lastData`

2. **Extracting pure helpers** that take `(state, ...args)` as parameters. Candidate pure functions per 12-B's map:
   - `_atomOffset` (L56-62)
   - `_sphereMatrix` (L76-81)
   - `_bondMatrix` (L83-94)
   - `_colorForAtom` (~52 LOC)
   - `_resolveAtomColor` (~14 LOC)
   - **Note**: these use shared THREE temps (`_tmpMat`, `_tmpQ`, `_tmpS`, `_tColor`, `_Y_AXIS`, `_ZERO3`, `_SPHERE_GEO`, `_CYLINDER_GEO`). Bundle the temps into the extracted module to keep allocation-avoidance contract intact.

3. **Move candidates to a new module** `frontend/src/scene/atomistic_renderer/geometry_builder.js` (or similar; pick the most descriptive name). The new module exports `(state, atoms, bonds) → {meshes, pairs}` style functions.

4. **Factory wrapper becomes thin**: atomistic_renderer.js shrinks to mostly init + state-object construction + delegation calls.

## In scope

Apply preconditions #19 (substantive leaf rule) and #20 (dead-import sweep) strictly.

The new module may import:
- `three` (external)
- `frontend/src/scene/atomistic_renderer/atom_palette.js` (ancestor — already-extracted leaf)
- NO imports from `atomistic_renderer.js` itself (substantive rule)

If during extraction the closure-capture surface widens unexpectedly (i.e., the surface map under-counted some refs), STOP and re-scope to a smaller extraction.

## Out of scope

- Touching the rendering invariants (per CLAUDE.md atomistic = physical layer; rendering must not write back to topology)
- Modifying atomistic backend
- Touching `_SUGAR` / `_PHASE_*` (locked)
- Module-mutable state (`_colorMode`, `_vdwScale`, `_strandColors`, `_baseColors`) — Pass 14+ scope per 12-B's map; this pass only addresses factory-scoped state

## Verification

3× baseline + lint + vite + vitest:

```bash
for i in 1 2 3; do just test > /tmp/13F_test_pre$i.txt 2>&1; done
just lint > /tmp/13F_lint_pre.txt 2>&1
cd frontend && npx vite build > /tmp/13F_vite_pre.txt 2>&1
cd frontend && npx vitest run > /tmp/13F_vitest_pre.txt 2>&1
```

Post:
- atomistic_renderer.js LOC reduced by ≥ 100 LOC
- New geometry_builder.js (or similar) module exists
- vite build PASS — check chunk hashes; ideally identical pre/post (proves tree-shake equivalence) but a small hash change is acceptable for surface-changing refactor
- vitest PASS (26/26 baseline)
- Backend tests unchanged
- Lint Δ ≤ 0

## Stop conditions

- Step 0 fails → STOP (literal `exit 1`)
- Closure-capture surface widens beyond 12-B's map → STOP, re-scope to smaller extraction
- Rendering invariant touched → revert, STOP
- vite build fails → revert, STOP
- vitest regression → revert, STOP

## Output (Findings #49)

Required:
- `_state` object schema (fields + initial values)
- Functions moved to new module (list + LOC each)
- atomistic_renderer.js LOC delta
- New module size + import list (proves leaf purity)
- vite chunk hash diff (identical or list changed hashes)
- vitest PASS count
- Lint Δ
- Apparent-bug flags (if any)
- Linked: #36 (10-H helix_renderer palette precedent), #42 (12-B surface map — the load-bearing input), #19 (rule split), #20 (dead-import sweep)
- Remaining surface for Pass 14+ (module-mutable state extraction, closure-internal method extractions)

## USER TODO template

1. `just frontend` and load saved `.nadoc` with atomistic data
2. Toggle atomistic display modes (off → vdw → ballstick)
3. Confirm CPK colours correct, selection highlight works, dim cascade works
4. Switch color modes (Strand Color / Domain / Sequence)
5. Confirm DevTools console clean
6. If clean, mark Finding #49 USER VERIFIED.

## Do NOT

- Touch rendering core (atom positioning, frame orientation)
- Touch atomistic backend
- Touch module-mutable state (`_colorMode` etc. — separate Pass 14+ scope)
- Commit / append to REFACTOR_AUDIT.md
