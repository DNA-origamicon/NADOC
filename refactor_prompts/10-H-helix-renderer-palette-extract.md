# Refactor 10-H — Extract `helix_renderer.js` Palette section (LEAF)

**Worker prompt. (c) leaf extraction. Same shape as 09-A `slice_plane/lattice_math.js`.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #15, #19 leaf-rule split, #20 dead-import sweep)
3. `REFACTOR_AUDIT.md` Findings #23 (Pass 8-A audit; helix_renderer.js #1 god-file candidate, in CLAUDE.md's rendering-invariant warning zone), #26 (09-A leaf reference)
4. **`CLAUDE.md` rendering-invariant warning** — known fragile area. **Touching `buildHelixObjects` body is OUT OF SCOPE**.
5. `frontend/src/scene/helix_renderer.js:24-289` — read everything BEFORE `buildHelixObjects` starts. The "Palette" section L29-245 is the safe extraction target.

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

Extract the **Palette section** (`// ── Palette ──` at L29 through `// ── Shared geometries ──` at L245) — ~216 LOC of color/geometry constants, all module-level — to `frontend/src/scene/helix_renderer/palette.js`. Leaf module: imports only `three` (and possibly `frontend/src/constants.js` if it references B-DNA constants — verify in pre-flight).

This is the **lowest-risk slice** of `helix_renderer.js`. The Palette section is BEFORE `buildHelixObjects` starts (L364), so no closure captures, no rendering-invariant risk.

## In scope

Move L29-245 verbatim to `helix_renderer/palette.js`. Re-import names at top of `helix_renderer.js`. Apply precondition #19 (leaf rule split): the new file may import `three` and `frontend/src/constants.js` (stable shared constants); MUST NOT import from `helix_renderer.js` or sibling modules under `helix_renderer/`.

Apply precondition #20: after move, grep `helix_renderer.js` for each moved symbol; drop any unused from the import block.

## Out of scope

- `buildHelixObjects` (L364-end). DO NOT TOUCH. CLAUDE.md flags this as rendering-invariant zone.
- The other `// ── ` sections inside `buildHelixObjects` (Backbone beads, Strand direction cones, Base slabs, Domain cylinders, etc.) — separate Pass 11+ candidates that need closure-capture refactoring.
- The Constants section L24-29 — keep in `helix_renderer.js` if it's small + non-color.
- Hex-color code in any other frontend file.

## Verification

3× baseline. Visual smoke test (USER TODO) since this is rendering code:
```bash
just lint > /tmp/10H_lint_pre.txt 2>&1
for i in 1 2 3; do just test > /tmp/10H_test_pre$i.txt 2>&1; done
```

After move: `wc -l frontend/src/scene/helix_renderer.js` should drop by ~210; `frontend/src/scene/helix_renderer/palette.js` should be ~220 LOC.

## Stop conditions

- Step 0 fails → STOP
- The Palette section references closure-captured names (it shouldn't — it's at module scope; verify)
- Any code change BELOW L289 in helix_renderer.js → revert, STOP. Strict scope.
- Test failure not in baseline → revert, STOP
- Lint Δ > 0 → revert (likely an unused-import F401)

## Output (Findings #36)

Required:
- LOC delta on helix_renderer.js
- palette.js size
- Imports in palette.js (should be `three` + maybe `constants.js`)
- Lint Δ
- USER TODO: rendering smoke test (load design, observe colors of backbone / cones / slabs)
- Linked: #23 (parent audit), #26 (09-A leaf precedent), #19 (rule split)

## USER TODO template
1. `just frontend` and load any saved `.nadoc`
2. Confirm helix beads, backbone color, strand cones, base slabs all render with expected colors (no fallback gray, no missing geometry)
3. Switch between strand-color modes (Strand Color / Domain / Sequence)
4. Confirm DevTools console clean
5. If clean, mark Finding #36 as USER VERIFIED.

## Do NOT
- Touch buildHelixObjects body
- Touch other `// ── ` sections inside the monolith
- Change palette values (move verbatim)
- Commit / append to REFACTOR_AUDIT.md
