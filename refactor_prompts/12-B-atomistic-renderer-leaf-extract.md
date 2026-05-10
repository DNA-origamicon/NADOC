# Refactor 12-B — `atomistic_renderer.js` audit + leaf extraction

**Worker prompt. (c) frontend leaf extraction — same template as 09-A (slice_plane lattice_math) + 10-H (helix_renderer palette).**

## Pre-read

1. `CLAUDE.md` (rendering invariants — three-layer law applies; atomistic positions are physical layer)
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #15 hardened-fail, #19 leaf-extraction rule split, #20 dead-import sweep)
3. `REFACTOR_AUDIT.md` Findings #23 (frontend audit; `atomistic_renderer.js` 516 LOC), #26 (09-A slice_plane lattice_math precedent), #36 (10-H helix_renderer palette precedent), policy row 2026-05-10 (atomistic family unlock — first atomistic FRONTEND refactor in scope)
4. `memory/REFERENCE_ATOMISTIC.md` if available
5. `frontend/src/scene/atomistic_renderer.js` (516 LOC) — read FULLY

## Step 0 — CWD safety (precondition #15 — HARDENED)

```bash
pwd
git rev-parse --show-toplevel
if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
    echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
    exit 1
fi
```

## Goal

Audit `atomistic_renderer.js` (516 LOC) and identify a leaf-extraction candidate (palette / pure-math / template-lookup section). Extract it to `frontend/src/scene/atomistic_renderer/<leaf>.js` following the 09-A + 10-H template.

**Two outputs allowed:**
1. **REFACTORED** — clean leaf identified + extracted; LOC reduction documented
2. **INVESTIGATED** (acceptable outcome) — file is too tightly coupled / no clean leaf available; document the closure-capture surface for a future Pass 13+ god-file decomposition

## In scope

If REFACTORED:
- Identify the leaf candidate (constants/palette block, pure-math helper cluster, or template-lookup table)
- Move verbatim to a sibling module under `frontend/src/scene/atomistic_renderer/`
- Apply precondition #19 substantive rule: new module MUST NOT import from `atomistic_renderer.js` or sibling modules under the new directory; may import only ancestor packages or external libs (THREE.js, etc.)
- Apply precondition #20 dead-import sweep: after move, drop unused symbols from atomistic_renderer.js's import block
- Re-export from atomistic_renderer.js if external callers depend on the moved names

If INVESTIGATED:
- Map the file's closure-capture surface (which functions reference module-level state? which reference other functions in the file?)
- Identify the largest pure-leaf candidate available
- Document reasons it can't extract cleanly (closure refs, mutable globals, import cycles)
- Recommend Pass 13+ approach (e.g., kernel pre-pass extraction)

## Out of scope

- Modifying the rendering invariants (per CLAUDE.md, atomistic positions are physical layer; rendering must not write back to topology)
- Touching `_PHASE_*` constants or `_SUGAR` template
- Frontend backend coupling changes (atomistic API contracts)
- Atomistic backend (`atomistic.py`, `atomistic_helpers.py`) — separate scope

## Verification

3× baseline + lint per precondition #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/12B_test_pre$i.txt 2>&1; done
just lint > /tmp/12B_lint_pre.txt 2>&1
cd frontend && npx vite build > /tmp/12B_vite_pre.txt 2>&1
cd frontend && npx vitest run > /tmp/12B_vitest_pre.txt 2>&1
```

If REFACTORED:
- `frontend/src/scene/atomistic_renderer/<leaf>.js` exists
- atomistic_renderer.js LOC decreased by the moved amount
- vite build PASS
- vitest PASS (frontend test set unchanged)
- backend tests unchanged
- Lint Δ ≤ 0

If INVESTIGATED:
- No code change
- Audit notes returned in worker output

## Stop conditions

- Step 0 fails → STOP (literal `exit 1`)
- Rendering invariant touched → revert, STOP
- vite build fails post-extraction → revert, STOP
- Closure-captured state needed by extracted symbols → STOP, recommend INVESTIGATED outcome

## Output (Findings #42)

If REFACTORED:
- LOC delta on atomistic_renderer.js
- New file size + import list (proves leaf purity)
- Test/build/lint deltas
- USER TODO: load saved `.nadoc` with atomistic data; verify atom rendering looks correct (atoms visible, colors correct, cone orientations preserved)
- Linked: #23 (parent audit), #26 (09-A leaf precedent), #36 (10-H leaf precedent), policy row 2026-05-10

If INVESTIGATED:
- Map of closure-capture surface (function names + dependencies)
- Recommended Pass 13+ approach
- Linked: same as above

## USER TODO template (if REFACTORED)

1. `just frontend` and load any saved `.nadoc` with atomistic data
2. Confirm atoms render with expected colors / sizes / cone orientations
3. Switch between rendering modes (atom-only / atom+CG / CG-only)
4. Confirm DevTools console clean
5. If clean, mark Finding #42 USER VERIFIED.

## Do NOT

- Touch the rendering core (atom-positioning logic, frame-orientation calculations)
- Touch atomistic backend
- Change palette/template values (move verbatim)
- Commit / append to REFACTOR_AUDIT.md
