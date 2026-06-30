---
name: Autostaple / autocrossover / autobreak — resolved bugs and current status
description: History of crossover linking issues and autobreak bugs; most resolved as of 2026-04-11
type: project
originSessionId: ebee5130-b4fe-4931-8053-4e9bd2cfe8a2
---
# Autostaple / Autocrossover / Autobreak Status (2026-04-11)

## Resolved bugs

### 1. min_crossover_gap=7 impossible for HC
HC lattices have only 6bp between crossover (offset 6) and tick mark (offset 7).
**Fix**: Abandoned gap-based avoidance, switched to tick-mark nicking which inherently avoids non-tick crossover positions.

### 2. FORWARD staple nicks off by +1
`make_nick(bp=T)` places gap at `T+1` for FORWARD but `T` for REVERSE.
**Fix**: Direction-aware tick selection: FORWARD checks `(bp+1) % period`, REVERSE checks `bp % period`.

### 3. `_ligate()` doesn't merge adjacent domains
After merge pass ligates same-helix strands, touching domains persisted as two separate domains.
**Fix**: Added `_merge_adjacent_domains()` call in `_ligate()`.

### 4. Circular crossovers never re-ligated after autobreak
`ligate_crossover_chains` skips `s_from == s_to` (circular). After autobreak nicks the strand, halves end up on different strands but never get re-ligated.
**Fix**: Added pass 3 to `make_autobreak`: `ligate_crossover_chains(max_length=60)`.

### 5. Tests only checked inter-domain boundaries
Crossover junction tests missed cross-strand nicks (valid when combined > 60 nt).
**Fix**: Tests now accept three forms: inter-domain boundary, wrap-around, cross-strand nick.

## Current state

- 559 backend tests pass, 0 failures
- Playwright autobreak edge tests pass (6HB at 42, 84, 126 bp)
- All crossover junctions accounted for after autobreak
- All strands ≤ 60 nt after autobreak
- Full staple coverage in first/last 14 bp verified

## Known remaining items

- **Holliday junction visual test** (`crossover_holliday.spec.js` test 2) has a pre-existing bug: accesses `design0.helices` but API returns `{design: {helices: ...}}`. Not related to crossover logic.
- `_SCAF_MARGIN = 7` excludes ~30% of staple crossover sites near scaffold crossovers — intentional but aggressive. May revisit.

## 2026-06-30 — autostaple missed crossovers (two distinct fixes)

Both surfaced via `workspace/2x2_strutted_corner_v2.nadoc` (SQUARE, 2 overhangs).

### A. Overhang staple bodies not woven in (FIXED)
`full_autostaple` routed crossovers AROUND the WHOLE overhang staple, so the overhang's
duplex BODY got no crossovers — making it a standalone strand, which violates
[[feedback_overhang_definition]] ("overhangs are embedded in the duplex structure, not
standalone"). Cause: `protected_strand_ids = locked_ids | overhang_ids` conflated two
jobs — **linearization** (keep staple whole to preserve `overhang_id`) and **crossover
routing** (skip nick sites). Fix: `_place_auto_crossovers(crud.py)` gained
`tip_only_strand_ids`; overhang staples now protect ONLY their `overhang_id` /
`binds_overhang_id` (tip) domains — the body is woven. Caller passes
`protected_strand_ids=locked_ids, tip_only_strand_ids=overhang_ids`
(`routes_assign_sequences.py`). **Gotcha:** an overhang staple is routinely ALSO `locked`
(by its own overhang-attachment forced ligation), and locked-full was overriding tip-only
→ tip-only must WIN (`fully = id in protected and id not in tip_only`). Pins:
`test_simple_router.py::test_overhang_staple_body_woven_tip_protected` (full-protect→0
body xovers, tip-only→woven) + updated `..._preserves_manual_connections_and_overhangs`
(overhang TIP preserved via `overhang_id`, NOT strand-id — bodies are now split/woven).

### B. Single-pass starvation (FIXED)
`_place_auto_crossovers` nicks staples + recomputes `sr` every iteration but only
re-ligates ONCE at the end → progressive fragmentation makes `_staple_arm_too_short` /
`_coverage_hole` FALSELY reject later bow sites (order-dependent gaps; a lone half of a
double-crossover renders wrong-bowing). A 2nd pass (fresh from placed+ligated state) fills
them → converges only at a **fixpoint**. Fix: **callers iterate to a fixpoint** (re-run
until a pass places 0). `_place_auto_crossovers` stays a SINGLE pass on purpose; looping
lives in the callers — `full_autostaple._run` and `auto_crossover()` — so locked/overhang
protection is **re-detected per pass** (content-based: `overhang_id` domains +
manual-connection touches, so it follows the staple even after ligation renames it). Both
loops are bounded (`range(12)`; placement is monotonic so it converges in 2–3 passes).
NOTE starvation is design-dependent — plain bundles (SQ6/HC6/TEETH) already fill in ONE
pass; it's the fragmentation from protected/overhang staples (Fix A) that induces it.
Pins: `test_simple_router.py::test_overhang_crossover_placement_iterates_to_fixpoint`
(minimal overhang design: pass1=2, pass2=1, pass3=0 → converges).

### C. Overhang body→tip attachment left as a BARE junction (FIXED)
A driver overhang's body→tip attachment (e.g. `(4,0)@40 → (3,0)@40`, same-bp +
lattice-neighbour) IS a real, valid crossover, but `_place_auto_crossovers` SKIPS it
(the tip is protected, Fix A) and nothing else recorded it → bare junction: the strand
backbone draws like a crossover but `design.crossovers` has no record, so the cadnano
editor keeps offering "add crossover" there (clicking just adds the missing record, no
visible change). Same class as the load-path forced-ligation bug, but in the live
pipeline. Fix: full-autostaple `_run` now calls `_backfill_dropped_junctions(clean)`
(the same load-path classifier) at the END — records a Crossover for every bare same-bp
neighbour junction (incl. overhang attachments); MISMATCHED-bp attachments
(e.g. `(1,0)@39 → (3,0)@49`, a loopout) correctly stay forced ligations. Idempotent;
v2 → +1 crossover, 0 validation errors. Pin:
`test_simple_router.py::test_full_autostaple_records_overhang_attachment_crossover`
(headless extrude → asserts no same-bp overhang attachment left bare). The earlier
load-path `_backfill_dropped_junctions` (models.from_json) already healed this on SAVE+LOAD;
this closes the IN-MEMORY gap so it's correct without a round-trip.
