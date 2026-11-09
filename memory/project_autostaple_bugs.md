---
name: Autostaple / autocrossover / autobreak — resolved bugs and current status
description: History of crossover linking issues and autobreak bugs; most resolved as of 2026-04-11
type: project
originSessionId: ebee5130-b4fe-4931-8053-4e9bd2cfe8a2
---
# Autostaple / Autocrossover / Autobreak Status (2026-04-11)

## 2026-11-05 — Cluster folding-order assignment and routing

The Clustering sidebar has a collapsible Folding Order card. Each part cluster
stores `folding_order` (1–999 or null); lower stages precede higher stages, ties
share priority, and null means Undefined/default routing. Edits and clears use
the recorded cluster PATCH command, persist with the part, and support undo and
independent replay. The feature log labels these assignments as Folding Order.

The Experimental popup now enables actual whole-part honeycomb folding-order
routing. It targets per-cluster median estimated staple Tfold with a configurable
2 °C default inter-stage gap. The earliest stage uses 42-bp crossover repeats;
later stages use 21-bp repeats and receive native nicks when needed. Undefined
and interface sites use the baseline repeat; cross-cluster staples are excluded
from scoring. Unsupported
estimates, conflicting overlapping assignments and infeasible gaps fail atomically.
This does not guarantee cooperative kinetic folding order. The report exposes
ranges, counts, caps and nicks. See `docs/staple_temperature.md` for the Castro
Marras et al. (2016) crossover-removal mechanism, model assumptions and bounded-search limitations. Assembly-wide
routing remains undefined; the UI directs users to the part editor.

Actual routing validation: 9 routing tests and 5 thermodynamic-parity tests pass,
including native saved/reopened replay and atomic rejection. Frontend: 10,142
passed, 1 skipped (878 files). Browser: 25 passed, including real assignment →
ordered routing and rendered 6HB/18HB reviews; isolated artifacts cleaned. Backend
FAST: 20,661 passed, 19 skipped, known CPD contract failure plus a VR subprocess
mock/background-precompute interference failure (exact VR retry passed). FULL
remains deferred. Final timing report has no per-test violators; guards unchanged.
Evidence: `.development-artifacts/folding-routing-validation.json`.

Prior assignment-UI checkpoint validation: 62 focused backend and 166 focused frontend checks pass, including
guarded saved/reopened replay, undo/redo, and history preview compatibility. The
real browser assignment/collapse/popup exercise and smoke checks pass across
targeted retries; temporary browser artifacts were removed. FAST: 20,648 passed,
19 skipped, one previously logged CPD display-contract failure. FULL remains
deferred; timing triage left guards unchanged after the flagged native-linker
case passed below its call-time limit in isolation. Compact evidence:
`.development-artifacts/folding-order-validation.json`.

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

## 2026-11-04 — Sweep frames shadowed their source bundle (ISSUE-178)

`all_valid_crossover_sites` indexed only `(row, col)`, so later sweep/extrusion
helices replaced an earlier frame's cells. In `workspace/test.nadoc`, full-autostaple
placed 193 staple crossovers on the sweep and none on the original bundle. Lookup
now uses `(lattice_frame_id, row, col)`, retains multiple segments, and checks
neighbor bp coverage. The ordinary crossover-site query, auto-crossover and
full-autostaple share this fix. New routing records include
`frame_scoped_crossovers: true`; replay of records lacking that parameter uses the
old lookup, preserving historical construction rather than silently rewriting it.
Apply a new routing command to use the correction on an existing design.

`tests/test_autostaple_frames.py` composes bundle → sweep → scaffold → autostaple
through recorded user commands and checks both frames, independent ordering,
standalone crossover recording, legacy replay and guarded save/reopen/replay.
The original `test.nadoc` was read only; its independent agent audit also identifies
unrecorded loadout fields, so no corrected derivative of that file was published.

## 2026-11-04 — Experimental 42 bp honeycomb routing

Autostaple now opens a Standard/Experimental method chooser (OK/Cancel).
Standard retains the existing algorithm; Experimental opens settings after scope
selection. `experimental` in the full-autostaple request/feature record contains
`crossover_repeat_bp` (21 or 42), `pattern` (0/A or 1/B), `min_length` and
`max_merged_length`. Missing/null experimental settings replay Standard behavior.
Experimental routing rejects non-HC designs before mutation.

`backend/core/experimental_autostaple.py` selects alternate 21 bp repeats by the
existing crossover pair's lower nick boundary. Both members of a pair survive or
are omitted together. The same filter skips preliminary nicks in omitted repeats;
placement still uses the existing lattice rules. Absolute bp coordinates anchor
the pattern, including negative bp coordinates. Regional routing retains its
whole-touching-staple scope and outside-strand protections. Manual connections,
forced ligations and overhang protections remain in force; they and boundaries
can produce departures from the nominal pattern.

The growth limit is explicitly a merge parameter, not a strict oligo length cap.
The result dialog reports staple nucleotide counts and domain lattice spans for
the routed scope. Spans are not sequence-based hybridization lengths when there
are insertions/deletions or unpaired domains. No cluster folding-temperature
prediction is made. Thermodynamic scoring, preferred-length optimization and a
pre-apply geometric routing preview remain future extensions.

Regression coverage: `tests/test_experimental_autostaple.py` authors native 6HB
and standard-example-cross-section 18HB bundles, tests both patterns, crossover
traversal, preserved coverage, regional isolation, Standard recovery, and guarded
publication/save/reopen/independent replay. `scripts/build_autostaple_review.py`
builds guarded browser fixtures; the isolated smoke run exercises both bundles
through the method/settings/results dialogs.

## 2026-11-04 — User-selected ordering maximum

The Experimental settings dialog accepts a hard `max_staple_length` (21–300 nt,
UI default 60). The method chooser contains only Standard/Experimental and OK/Cancel.
Standard sends its original request and retains its existing routing and length behavior. It is distinct from the
experimental lattice-span merge limit. Missing/None preserves legacy replay;
new UI commands record the chosen limit in the native full-autostaple feature.
After growth, a deterministic partition adds ordinary editor nicks inside domains,
retaining crossover traversals and coverage. It prefers the growth minimum,
requires new fragments of at least 7 nt, and keeps cuts 7 lattice bases from
domain ends. Infeasible limits reject the whole command. This can shorten the
long binding domains encouraged by 42 bp routing; it does not predict folding
kinetics or temperature.

Length includes loop/skip-adjusted sequence spans, overhang/binder sequences,
terminal extension bases and junction inserts. Strands carrying extensions or
junction inserts remain intact in capped routing, as do forced-ligation and
overhang strands during the final cap pass; over-limit protected strands cause
an explicit failure. Outside-region staples are exempt and unchanged. This is a
routing constraint, not an estimate of vendor prices or a change to order export.
Focused recorded 6HB/18HB tests cover maximum 42, crossover/coverage preservation,
saved-file publication plus independent replay, regional exclusions, insertion/
deletion accounting, validation and atomic rejection of a long extension.
