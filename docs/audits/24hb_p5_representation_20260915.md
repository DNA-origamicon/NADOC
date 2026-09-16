# 24hb_0xT Alpine representation audit — 2026-09-15

Both reported symptoms have general NADOC display-code causes. The interrupted run is not needed to reproduce either cause. This was a read-only diagnostic: no renderer, design, simulation input, or trajectory was changed. Numerical/code verification was performed; no interactive browser visual verification was performed.

## Runs and data integrity

- Interrupted 24hb_0xT: `594917c0d119`, status `stopped`, error `Interrupted by Alpine restart; preserved trajectory, no restart checkpoint.` Its preserved production DCD contains 6,032 complete frames, with no partial-frame bytes at the end.
- Completed 24hb_0xT parent: `2f281ba1a83a`, 2,399 complete frames in the primary production DCD, no partial-frame bytes.
- Independent completed control: 2hb_1-0xT `4aab8c445579`, 2,000 frames in the sampled production DCD.

The two local 24hb jobs lack a frozen design snapshot and their older ancestor is not present locally. The audit therefore used their recorded source `workspace/24hb_0xT.nadoc`, matching the application's source-file fallback. All 6,720 mapped base letters agree with each job's packaged PDB residue identities: **zero sequence mismatches**. This does not certify all historical geometry settings, but rules out a current sequence/PDB mismatch as the cause of the color discrepancy.

## Base colors: identity-key collisions

`frontend/src/scene/color_util.js:28` (`atomColorsFromLetters`) stores colors under `strand_id:bp_index:direction`. `frontend/src/scene/atomistic_renderer/color_resolver.js:114` uses the same incomplete key. Helix identity and insertion-copy identity are omitted. A strand revisiting the same bp index and direction on another helix overwrites the earlier nucleotide's color. The Full palette uses nucleotide-specific entries from `buildNucLetterMap` and does not have this particular collision.

Executed the real frontend `buildNucLetterMap`, `atomColorsFromLetters`, and `resolveAtomColor` functions on the geometry returned by the backend's measured/junction-balanced design geometry path:

| Design | Base-letter entries | Atomistic map entries | Different colors |
|---|---:|---:|---:|
| 24hb_0xT | 6,720 | 1,701 | 3,744 (55.7%) |
| 2hb_1-0xT control | 94 | 94 | 0 |

For example, scaffold nucleotide `h_XY_0_1:67:REVERSE` is A in Full/the packaged PDB but resolves to T's color in atomistic mode. Of the 3,528 scaffold bases, 2,390 resolve to a different color.

This affects the shared atomistic coloring path, including ordinary design viewing, not only interrupted NAMD jobs. It is general but not visible on every design: the 2hb control has no such key collisions. Counts describe ordinary base mode without selection highlights or scalar overlays.

## Positions: trajectory transport omits measured base centers

`backend/core/md_trajectory.py:2620` calls `_extract_md_nadoc_frame(..., with_termini=True)` without `with_base_centers=True`. Its composite trajectory packs six floats per nucleotide: phosphate position and P-to-C1' direction. `frontend/src/ui/oxdna_display.js:286` converts these legacy six-float frames into updates without `base_position` or a live axis tangent.

Consequently, `frontend/src/scene/helix_renderer.js:4260` constructs the base target via `translatedBasePosition`: **design base position + live phosphate − design phosphate**. The offset retains the design pose rather than the actual trajectory residue conformation. Slab orientation also falls back to the design tangent. Ball-and-stick uses the measured atomic coordinates after periodic imaging and global alignment.

Compared frame 0, midpoint, and last frame from each primary DCD. Used the normal coarse context, installed the production topology-only heavy-atom layout into that same context, and ran both production frame extractors against the identical raw frame. This isolates representation behavior from frame scheduling and design-reference differences.

| Run, last frame (zero-based) | Median inferred-base error | 95th percentile | Maximum |
|---|---:|---:|---:|
| Interrupted 24hb, 6031 | 0.265 nm | 0.604 nm | 1.294 nm |
| Completed 24hb, 2398 | 0.259 nm | 0.560 nm | 1.351 nm |
| Completed 2hb, 1999 | 0.266 nm | 0.785 nm | 1.174 nm |

Errors compare the inferred `liveBaseMap` target to the corresponding simulated base-ring centroid, **not the final stylized slab mesh center**, which receives additional paired-plane/body placement. Phosphate coordinates from the two extractors agree exactly at all nine sampled frames. The optional measured base-center extraction agrees with atomistic ring centroids within 0.000009 nm. Position statistics cover mapped phosphate-bearing residues, not phosphate-less termini or unmatched synthetic extras.

This specifically identifies the NAMD composite-trajectory path. Live Display MD and the flexibility map already carry measured base centers through separate paths; oxDNA's newer nine-float format also has a different reconstruction path. The result is not a claim that every NADOC representation or engine has the same position defect.

## Scope and repair direction

The data supports display defects rather than an interruption-induced sequence or global alignment failure. It does not certify the entire simulation's physical quality or every DCD frame. No production rendering changes were made as part of this investigation.

A repair should use a collision-free nucleotide identity for atomistic colors and carry measured base centers/live frame orientation through the NAMD composite trajectory protocol and its caches. The latter should retain separate NAMD and oxDNA semantics, cover phosphate-less termini, and be checked with a same-frame visual overlay before changing normal slab placement.

Detailed frame measurements, color examples, and integrity counts are in `24hb_p5_representation_20260915.json`. Diagnostic scripts and generated geometry remain under `/tmp/nadoc-p5-audit/` for this session.

## Repair follow-up

The subsequent user-authorized fix adds NTRJ v2 measured ring centers/planes, including
O5′ termini, and collision-free atomistic nucleotide color keys. Deeper renderer
inspection also found `_slabCenterAt` ignores its `baseMap` argument and reconstructs
the slab from `localCenterOffset`. Thus the original numerical table above diagnoses
the inferred `liveBaseMap` target, not that final rendered offset. The fix explicitly
uses measured NAMD centers in `applyFemPositions`; the ordinary native placement is
unchanged. A regression now checks the actual slab instance matrix, plane orientation,
visibility refresh, and restoration of the original design.

After the fix, the color audit has zero mismatches in all 6,720 24hb bases. The emitted
float32 ring centers agree with the atomistic ring centroids within 0.000004 nm across
the first/middle/last sampled P5 frames; the completed 2hb control agrees within
0.000001 nm. These are coordinate extraction checks; app verification is recorded below.

The separate browser requests exposed an additional ~0.0094 nm registration difference:
coarse playback aligned against the measured/junction-balanced display reference while
the all-atom path aligned against native model phosphates. Both now use the same active
display reference, retaining model-only synthetic keys for periodic imaging.

Final automated checks:

- Frontend: 442 files, 6,483 tests passed.
- Focused backend (ring extraction, binary transport, segment handling): 16 passed.
- `just test-smart`: `decision: FAST  (fast suite only)`; 8,528 passed, 110 skipped,
  27 failed, 9 errors. Remaining failures are outside the changed paths: oxDNA build
  freshness, absent assembly fixtures, and aptamer setup. The worker-transport failure
  in an earlier run passed its isolated recheck and the final FAST run.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.
```

### Running-app verification

`frontend/e2e/namd_measured_bases.spec.js` passed on the real preserved P5 job using
dedicated servers. It loaded the new binary trajectory, selected the last frame,
compared all 6,720 actual Full slab matrices against the measured centers, switched
to ball-and-stick, and compared actual rendered atom positions/colors. Results:
**137,493 atoms checked, zero color mismatches, 6,720 base rings checked, maximum
slab-center/ring-centroid difference 0.0000520617 nm** (atom-coordinate transport rounds
to 0.0001 nm). Switching back to Full preserved the frame and all slab centers. No
uncaught page errors occurred. Both screenshots were inspected. Playwright removed its
screenshots/traces/reports, and no test-prefixed workspace or session artifact remained.

Reload NADOC and reopen the trajectory to discard any already-loaded legacy frame data.
No simulation rerun is required.
