---
name: cadnano-editor-end-drag-resize-status-and-known-issues
description: State of the drag-to-resize strand end feature in the cadnano pathview editor; known issues remain unresolved at end of session.
metadata: 
  node_type: memory
  type: project
  originSessionId: ef45814a-5d47-4a6a-a518-afa79a2a81d1
---

## What was implemented

`frontend/src/cadnano-editor/pathview.js`:
- `_endDragActive`, `_endDragEntries`, `_endDragDeltaBp`, `_endDragMinDelta/MaxDelta`, `_endDragStartWX` state variables (alongside lasso state, ~line 272)
- `_resolveEndDragEntries()` — scans `_selectedElements` for `end:` keys, finds containing domain+strand
- `_computeEndDragLimits(entries)` — per-end constraint math: crossover attachment pins end (delta=0); inner crossovers block shrink; adjacent domain endpoints block extension; returns shared `{ minDelta, maxDelta }`
- `_drawEndDragGhost()` — draws 55%-opacity red rect at `origBp + _endDragDeltaBp` per entry
- `pointerdown` (select tool): intercepts end hits before lasso, selects end, starts drag
- `pointermove`: converts world-x displacement → snapped bp delta, clamps to limits
- `pointerup`: calls `onResizeEnds?.(apiEntries)` if delta ≠ 0
- `pointerleave` / `pointercancel`: cancels without committing
- `onResizeEnds` added to `initPathview` options

`frontend/src/cadnano-editor/api.js`:
- `resizeStrandEnds(entries)` — `POST /design/strand-end-resize`

`frontend/src/cadnano-editor/main.js`:
- imports `resizeStrandEnds`, wires `onResizeEnds: (entries) => resizeStrandEnds(entries)`

**Why:** `POST /design/strand-end-resize` backend endpoint already existed and handles both scaffold and staple terminal domain resizing; helix axis grows automatically.

**How to apply:** Resume here — the drag interaction and ghost rendering are scaffolded but the user reported unspecified issues remain.

## Known issues (unresolved at end of session)

User confirmed "we still have issues with resizing" but did not describe specific failure modes before ending the session. Issues were not debugged.

Likely candidates to investigate:
1. Ghost does not appear or snaps incorrectly (check `_endDragStartWX` capture and `Math.round` snap)
2. Constraints are too tight or too loose (`_computeEndDragLimits` — verify inner-xover and adjacent-endpoint logic)
3. `pointerdown` end-hit check uses `_selectFilter` — if `ends` filter is off the drag never starts; consider using unfiltered hit for drag initiation
4. Multi-selected ends have conflicting constraints → `minDelta > maxDelta` clamps to zero → no movement
5. Bidirectional sync (3D ↔ cadnano) was analyzed and appears correct via `design-changed` BroadcastChannel, but was not tested end-to-end

## FIXED 2026-05-24 — couldn't resize/nick THROUGH an inline overhang split

Symptom: extend a staple end past the scaffold (e.g. Hinge `h_XY_2_5`/display
helix 17, end 221→256) → reconcile splits it into a collinear duplex+overhang
pair (`[216,221]` + `[222,256]`, same helix/dir, bp-adjacent, NO crossover
between — just the inline-overhang classification, `overhang_id` on the tail).
Then you couldn't retract the end below 222, nor nick at the 221/222 boundary.

Root cause = TWO frontend gates treating that collinear split as a hard wall
(backend was already fine):
- `_computeEndDragLimits` (pathview.js) floored the shrink at the terminal
  domain's own `domHi-domLo` (=222), never looking at the previous collinear
  domain. Fix: new `collinearRun(strandId,helixId,dir,domLo,domHi)` walks
  same-helix/same-dir/bp-adjacent neighbours of the SAME strand; the shrink
  fallback + innerXovers now use `runHi-runLo` / the run range, so the end
  retracts continuously to the run's far edge (the real crossover at 216).
- The nick handler clamped `nickBp` to `[lo, hi-1]`, excluding a domain's own
  3′ terminus → couldn't nick at the boundary. Fix: new `_nickBpForDomain(dom,
  col)` widens the FORWARD upper clamp to `hi` when the strand continues
  collinearly past it (REVERSE already reaches its 3′ edge `lo`). Used by both
  the nick click (~3578) and hover-ghost (~3868) paths.

Backend needed NO change: `_reconcile_inline_overhangs` already merges the
inline tail back + re-splits at the scaffold boundary on resize (test
`test_resize_inline_overhang_removed_when_trimmed_back`), and `make_nick`
already handles an inter-domain-boundary nick (lattice.py:1328/1355). `_needsNick`
in pathview.js is DEAD CODE (no callers) — the live nick logic is the inline
handler at ~3545. Logic validated via a node harness on the Hinge scenario;
resize/lattice suites 72/72. **UI drag/nick NOT exercised in-app by implementer.**

## FIXED 2026-05-24 — negative-bp ends couldn't be resized/dragged

Symptom: ends at a NEGATIVE bp (e.g. bp=-3) couldn't be resized in the cadnano
editor (worked fine in 3D). Root cause: the selection-key parsers in
`pathview.js` used `(\d+)` (positive ints only). Keys are built as
`end:<helix>_<bp>_<dir>` and `line:<helix>_<lo>_<hi>_<dir>` where bp/lo/hi can be
negative, so `_resolveEndDragEntries` (`pathview.js:2341`) and
`_resolveDomainDragEntries` (`pathview.js:2503`) matched nothing → drag resolved
zero entries → no-op. Fix: `(\d+)` → `(-?\d+)` in both regexes. Greedy `(.+)`
helix-id capture + backtracking still extracts the right helix id; positive bp
unaffected. (Hit-testing, handle rendering, `_bpToX`/`_xToBp` all already handled
negative bp — only the key regexes were the gap.)
