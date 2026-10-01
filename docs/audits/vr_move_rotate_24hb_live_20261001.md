# Live 24HB versus 6HB Move/Rotate — 2026-10-01

Full scales to the 24HB origami with substantial GPU headroom on typical drag
frames. It does **not** establish a strict 11.1 ms worst-case guarantee: both
model sizes exhibited isolated frame-delivery hitches in the fresh comparison.

## Models and scope

- 24HB: private copy of `workspace/24hb_0xT.nadoc`, 24 helices of 147 bp,
  76 strands, **6,720 rendered nucleotides**. Its molecular state matches the
  saved 24HB snapshots used in the earlier isolated renderer benchmark.
- 6HB: generated six-helix, 42 bp test bundle, plus the existing test's seven-base
  overhang/support helix; **511 rendered nucleotides**. Thus 24HB contains **13.15×**
  as many nucleotides, not simply four times the workload.
- Actual SteamVR/OpenXR native viewer, RTX 3080 Ti, Full representation,
  selected **single-base** translation plus rotation. All four unchanged human
  motion presets completed their drag. This is not a live whole-cluster or
  atomistic-representation test.

The earlier atomistic renderer benchmark already used **this 24HB molecular
state**, not the generated 6HB. Only the earlier live authoring tour used 6HB.

## Fresh live measurements

SteamVR application pre-submit GPU p95 in milliseconds. Repeated/dropped counts
are retained separately; GPU time is not total application CPU-plus-GPU time.

| Profile | 6HB GPU p95 ms | 24HB GPU p95 ms | 6HB repeated / dropped | 24HB repeated / dropped |
| --- | ---: | ---: | ---: | ---: |
| steady_fast | 1.47 | 3.27 | 4 / 5 | 0 / 0 |
| steady_deliberate | 2.26 | 3.60 | 0 / 0 | 0 / 1 |
| variable_fast | 1.41 | 4.26 | 0 / 0 | 4 / 1 |
| variable_deliberate | 1.59 | 3.49 | 0 / 0 | 0 / 0 |

6HB: 529 sampled interval frames, four repeated and five dropped, GPU maximum
66.01 ms. 24HB: 515 sampled interval frames, four repeated and two dropped,
GPU maximum 24.50 ms. Counts are compositor fields, not mutually exclusive
classes of failed frames. Median GPU times across presets were 0.91–1.07 ms
for 6HB and 2.27–2.54 ms for 24HB.

The **previous** 6HB run had p95 1.73 / 1.96 / 2.51 / 1.90 ms in profile order
and no repeated/dropped frames across 520 samples. The fresh 6HB control shows
that a short clean run is insufficient to establish absence of rare hitches.
The 24HB variable-fast spike occurs inside the drag interval, not just at its
boundary. Shared rendering/runtime contention is a plausible contributor, but
these measurements do not isolate its cause.

## Observation conditions and limits

Production shadows, lighting, primitive detail, display resolution, input
sampling, seeds, and acceptance thresholds were retained. Captures and setup
are outside measured drag intervals. Wall-clock polling assigns frame samples
with approximately 100 ms boundary uncertainty. Each drag is only about 0.8 or
2.1 seconds; this is a spot check, not a long-duration percentile estimate.

The normal review gesture oriented and framed each model. 24HB additionally
used an ordinary two-grip **2× presentation zoom** to expose individual bases;
its projected long dimension is approximately 44% of an eye image versus about
22% before the extra zoom. This is a declared observation difference, not a
pixel-matched view comparison. The visible base is chosen from both-eye IDs,
and partial-trigger hover avoids selecting a nearby crossover. Native selection
radii and hit logic are unchanged.

Chromium focus proved inconsistent despite disabling Playwright focus emulation.
Actual frame counters are retained in each `background-rendering.json`:
6HB's desktop renderer was idle only in steady_deliberate; 24HB's was idle only
in steady_fast. The other cases advanced about 32–33 desktop draws per 500 ms.
No renderer was forcibly paused for the final runs. Thus the results include
mixed desktop contention, and the table must not be interpreted as an isolated
GPU scaling ratio. Both variable profiles had desktop rendering active for
both model sizes.

The final comparison uses the existing semantic Move/Rotate activation entry
point solely for setup. Subsequent selection, handle acquisition, translation,
rotation and release use real production input processing and unchanged human
profiles. This does **not** validate human menu acquisition; the ordinary menu
matrix still fails its 150 ms replay deadline before editing on some profiles.

## Correctness and separate authoring failure

All four 24HB drags pass stereo pixel checks and exact backend geometry scope:
one nucleotide moves and 6,719 stay unchanged. Over 11,000 common neighboring
visible primitives per eye retain their positions. Commit acknowledges without
a scene re-export, and the saved file contains the transform and feature entry.

**24HB's full authoring test remains failed:** after save, the VR Undo request
receives HTTP 404 `Nothing to undo.` and reports `UNDO FAILED` in all four cases.
The subsequent reopen assertion is therefore not reached. This remains a
separate unresolved authoring issue; it is not counted as a drag performance
failure or hidden by a passing result. Fresh 6HB passes all four complete
move/commit/scope/save/Undo/reopen workflows.

## Changes made for this check

- `move_tour --design` imports a complete design into a separate temporary
  workspace for every target/profile. Copied revision-store pointers are reset;
  embedded geometry and history remain intact. Existing nucleotide transforms
  are rejected by this exact-scope fixture. The source file's SHA-256 is unchanged.
- `--keep-going` retains independent failed profile results while still exiting
  nonzero; `--direct-activation` explicitly declares the performance setup.
- The live observer now exposes `scene_hover` separately from menu hover and
  omits inactive Nick bond coordinates while Move/Rotate or Bend is active,
  marking `ligation.bonds_omitted`. On 24HB the former response was about 661 KB,
  mostly irrelevant Nick coordinates. This avoids inspector socket backpressure
  during measured control. Normal rendering is unchanged; Nick observations
  outside these tools retain their previous contract.
- The test waits for imported geometry, records actual browser render counters,
  checks visible nucleotide hover before selection, and fails promptly on an
  explicit authoring error instead of waiting 90 seconds.

## Evidence and reproduction

Final 24HB evidence: `.development-artifacts/vr-move-24hb-live-drag-matrix/`.
Fresh 6HB control: `.development-artifacts/vr-move-6hb-live-comparison/`.
Each contains `compositor.jsonl`, `compositor-summary.json`, exact interval JSON,
per-eye depth/IDs/PNGs, acquisition records, browser render counters and logs.
The 24HB committed `steady_fast` mirror visibly contains the full origami;
submitted-eye evidence does not establish physical through-lens comfort.

```sh
uv run python -m tools.vr_workflows.move_tour \
  --design workspace/24hb_0xT.nadoc --target base --validate \
  --keep-going --direct-activation --output /new/evidence/directory
```

The retained `run_live.py` wraps this command with the read-only OpenVR timing
sampler. Omit `--design` for the generated 6HB control. Omit direct activation
when validating the complete menu route rather than isolating drag performance.

Failed/intermediate attempts remain under `vr-move-24hb-live*`: imported API
snapshots lacked loadout/history payloads; normal opening changed the document
name and removed the inspector URL option; browser focus/hidden-tab attempts
were rejected or failed; large inactive Nick replies delayed replay; a crossover
was selected instead of a base; and an initially selected base was occluded in
one eye. The `hover` run completed a drag but failed stereo visibility and showed
an 18 ms spike. None of these attempts is silently reclassified as passing.

The earlier isolated 24HB renderer results remain the atomistic feasibility
comparison: whole-cluster p95 update plus draw was **14.09 ms Stick, 16.49 ms
Ball & Stick, and 3.43 ms VDW**; small-base edits were below 11.1 ms in those
controlled conditions. See [the optimization audit](vr_move_rotate_optimization_20261001.md).

Validation after the observer changes: the rebuilt rigid-preview regression,
move-panel, ligation and staged-representation CTests pass; all 31 tour-catalog
tests pass. JavaScript/Python syntax and whitespace checks pass.

All owned test viewers and private workspaces are cleaned up. SteamVR remains
running. No user design or runtime rendering settings were changed.
