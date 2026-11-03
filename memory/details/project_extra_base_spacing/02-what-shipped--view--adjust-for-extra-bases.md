# What shipped — View ▸ Adjust for Extra Bases — supporting detail

[Topic head](../../project_extra_base_spacing.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## What shipped — View ▸ Adjust for Extra Bases

Display-only. Toggle OFF = the as-built 2.25 nm lattice (unchanged default); ON = the relaxed
table below, chosen by the design's **largest** extra-base count (a design mixing T and TT is
adjusted as if every crossover carried TT — the lattice is one rigid frame, so the widest junction
sets the pitch).

| extra bases | spacing |
|---|---|
| 0 | 2.45 nm |
| 1 | 2.53 nm |
| 2 | 2.55 nm |

- `scene/extra_base_spacing.js` — pure table + `maxExtraBaseCount` / `adjustedSpacingForDesign`.
  15 vitest tests. **The provenance comment in that file is the primary record; keep it in sync.**
- `scene/expanded_spacing.js` — grew a `_mode` (`'manual'` = the Q slider, `'extra-base'` = this).
  **One offset channel, one writer**: reusing the existing `applyUnfoldOffsets` fan-out rather than
  adding a parallel position writer is deliberate — see `.claude/rules/unfold.md`, which calls this
  module the second implementation of that contract. A third writer would race both.
- `_desiredOn` (synchronous) vs `_active` (settles when the 300 ms animation lands): the menu pill
  and the next toggle's direction read `_desiredOn`, or a second click inside the animation window
  expands twice instead of collapsing. `_active`'s meaning was left alone — `isActive()` has other
  consumers.
- `e2e/extra_base_spacing.spec.js` asserts the resolved spacing off the module's own `[EXPAND]` log
  (noT → 2.45, 2xT → 2.55) plus real bead movement. It copies its fixtures because **the library
  hides `__`-prefixed files**, so the usual `__e2e__` convention is unclickable here.
