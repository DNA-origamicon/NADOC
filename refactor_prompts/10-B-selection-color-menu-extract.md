# Refactor 10-B — Extract `_showColorMenu` from `selection_manager.js`

**Worker prompt. Template: shape similar to 09-A leaf extraction but the moved function is NOT a leaf — it captures closure variables from `initSelectionManager`.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #15, #19 leaf-rule split, #20 dead-import sweep)
3. `REFACTOR_AUDIT.md` Findings #23 (08-A frontend audit; selection_manager.js was top-5 candidate)
4. `frontend/src/scene/selection_manager.js:577-840` — read `_showColorMenu` body in full + identify which closure variables it captures from the enclosing `initSelectionManager`

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

`_showColorMenu` (262 LOC at L577) is a top-5 god-file slice per Finding #23. Extract to `frontend/src/scene/selection_manager/menus/color_menu.js`. Closure-captured variables become explicit function parameters. Caller in `initSelectionManager` becomes 1-2 lines (build args, call function).

## In scope

1. Identify all closure-captured names `_showColorMenu` reads or writes (likely: `store`, `_currentSelection`, helpers like `_selectByStrandColor`, gizmo handles). Enumerate in the worker output before moving.
2. Create `frontend/src/scene/selection_manager/menus/color_menu.js` with `export function showColorMenu(args)` where `args` is an object containing the closure refs.
3. Move the body verbatim except: replace closure refs with `args.X` accesses.
4. Update the caller in `selection_manager.js` to import and call.
5. Confirm `just lint` Δ ≤ 0 and tests baseline-preserved.

## Out of scope

- The other 3 long functions (`_showMultiMenu`, `_openExtensionDialog`, `initSelectionManager` itself) — separate Pass 11+ candidates.
- Refactoring closure-captured helpers themselves — they stay in `selection_manager.js`.
- Hex-color palette extraction (Finding #23 noted 81 hex colors; separate prompt).

## Verification (3× baseline per #1)
```bash
for i in 1 2 3; do just test > /tmp/10B_test_pre$i.txt 2>&1; done
just lint > /tmp/10B_lint_pre.txt 2>&1
```
Post-state: confirm selection_manager.js shrunk by ≈ 250 LOC; confirm color_menu.js compiles via vitest dry-run if available, else just lint.

## Stop conditions
- Step 0 fails → STOP
- Closure-captured names exceed 8 distinct identifiers → STOP, scope is too big for parameter-bag pattern; recommend re-scope to a smaller submenu
- Any test failure not in stable_baseline ∪ flakes → revert, STOP

## Output (Findings #30)

Required fields:
- Move type: extracted-with-edits (closure→params transform)
- LOC delta on selection_manager.js
- color_menu.js size + new arg-shape interface
- Closure-captured names enumerated
- Lint Δ
- USER TODO: load app, test color menu (right-click on a strand → "Color..." menu)
- Linked: #23 (08-A audit named this); #6 (debug-log gating shape — different but instructive)

## USER TODO template (worker fills in)
1. `just frontend` and load any saved `.nadoc`
2. Right-click on a strand → "Color..." submenu
3. Pick a preset color; confirm strand updates
4. Open the multi-strand color flow if applicable
5. Confirm no DevTools console errors

## Do NOT
- Touch `_showMultiMenu`, `_openExtensionDialog`, `initSelectionManager` body
- Inline new closure variables; use the args-object pattern
- Commit / append to REFACTOR_AUDIT.md
