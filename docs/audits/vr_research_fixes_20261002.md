# VR bottleneck research and fixes — 2026-10-02

Research, implementation and bounded validation completed. Start 19:24:47 UTC;
hard deadline 21:24:47 UTC. The 90 FPS goal remains unmet. Maximum two optimization candidates per bottleneck. Ball & Stick
on the full 24HB is the priority; Quick Surface performance is excluded.

The original `workspace/24hb_0xT.nadoc` has 24 helices, 76 strands and 6,720
nucleotides. Its SHA-256 is
`bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
All authoring checks use private copies. Molecular geometry, topology, eye
resolution, picking semantics, motion profiles and timing gates are unchanged.

## Research completed before implementation

1. **Identify the limiting stage and measure again after each change.** NVIDIA's
   pipeline guidance recommends varying stage workload to isolate a bottleneck,
   rather than treating aggregate GPU utilization as a frame-deadline measure.
   Prior evidence already separates browser contention, selection CPU work,
   scene refresh, and cluster GPU cost. This round leaves desktop drawing off.
   [NVIDIA GPU Gems, graphics pipeline performance](https://developer.nvidia.com/gpugems/gpugems/part-v-performance-and-practicalities/chapter-28-graphics-pipeline-performance).
2. **Cache selection relationships at the source lifetime.** Derived lookup
   tables should be invalidated when their primary data changes. The existing
   representation `SourceIndex` provides that boundary; rebuilding it per hit
   would defeat the cache. Preserve first-alias ordering, multi-kind tokens and
   ambiguous endpoint rejection. [Author's Dirty Flag chapter](https://raw.githubusercontent.com/munificent/game-programming-patterns/master/book/dirty-flag.markdown).
3. **Move CPU parsing off the OpenXR frame thread.** GLFW permits a context to
   be current on only one thread at a time. Keep parsing CPU-only, retain the old
   scene during loading, then activate GPU resources and publish the revision on
   the context thread. Avoid prewarming representations not being displayed.
   This does not by itself eliminate activation/upload/destruction stalls.
   [GLFW context and threading guide](https://www.glfw.org/docs/latest/context_guide.html).
4. **Reduce upload traffic only with synchronization evidence.** Updating fewer
   bytes with `glBufferSubData` can still block on buffers referenced by queued
   GPU draws. Current orphaning avoids that hazard. Persistent/ring buffers need
   explicit ownership/fence discipline; do not substitute naive partial writes
   merely because they transfer fewer bytes.
   [Khronos glBufferSubData reference](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Refpages/main/gl4/glBufferSubData.xml).
5. **Investigate early depth rejection for sphere impostors.** The existing
   fragment shader writes analytic sphere depth, which can prevent early depth
   rejection. Conservative-depth declarations permit optimization only if the
   declared bound is mathematically respected. A candidate must preserve
   clipping, final pixels/depth and object IDs; arbitrary early-fragment tests
   would be incorrect for an impostor.
   [Khronos ARB_conservative_depth specification](https://raw.githubusercontent.com/KhronosGroup/OpenGL-Registry/main/extensions/ARB/ARB_conservative_depth.txt).

## Implementation and validation log

- Selection candidate 1: per-source alias/typed-token index; no per-frame typed
  table allocation or linear scene-wide lookup. Focused reference-equivalence
  test covers 6,720 synthetic identities, all selection levels, duplicates,
  multi-kind tokens, missing entries, ambiguous ends and source replacement.
- Refresh candidate 1: asynchronous snapshot parsing; old scene remains live;
  activation/revision remain on the context thread; no prewarming of inactive
  representations. Focused test covers blocked loader/nonblocking polling,
  thread ownership, retry after error, and invalid/replayed records.
- Feature audit defaults desktop drawing off, records the condition, and records
  browser frame traces. `--desktop-rendering on` is an explicit control condition.
  Production preference defaults are unchanged.
- Native interaction and scene-refresh tests passed (2/2).

Final decisions and measured results follow below.

Evidence: `.development-artifacts/vr-research-fixes-20261002/`.

### Candidate evaluation and final retention decisions

| Bottleneck | Candidates used | Final retention decision |
|---|---:|---|
| Owner lookup | 1 | Indexed resolution preserves the reference semantics and removes scene-wide per-hit scans. |
| Highlight CPU work | 2 | Initial sparse-hover path excluded existing selections. Revised path preserves an unchanged selection and weighted preview cache; effective unchanged glow masks cause no GPU upload. Changed selection or deformed/visualized scenes retain the general path. |
| Scene refresh | 2 | Parse off-thread; activate only the requested style once with current highlights/visualization; retire old CPU source data on the existing bounded worker. GL work stays on the context thread. |
| Cluster GPU cost | 2 | Conservative sphere depth rejected: identical pixels, no useful timing change. Cached cylinder coordinate frames also rejected after live rotation regressed despite the isolated GPU improvement. Original shaders/instance layout restored. |
| Preview bounds | 1 | Cache bounds of unchanged instances; inspect edited instances during motion. No change to resulting bounds. |

The rejected cylinder cache preserved the existing eight-sided meshes, radii, colors,
shadows, object IDs and source coordinates. It avoided repeated axis normalization
and basis construction in each vertex invocation. Equal-weight translations
retained the cached frame; rotations, unequal endpoint weights and coordinate
playback updated it. Larger instance records increased upload traffic. The live
steady-fast cluster rotation regressed from the original-renderer control
44.78 FPS to 35.81 FPS; selected idle stayed 44.76 FPS with GPU p95 approximately
12.7 ms. This failed the retention criterion. Both GPU attempts are exhausted;
no GPU shader/mesh change remains in production. The interrupted next variable
profile is labeled administrative cancellation, not an independent tool defect.

The controlled full-24HB renderer uses 137,721 points and 154,917 cylinders,
1852×2056 eyes, both eyes plus shadows, 120 measured samples per condition after
five warmups. It is a serial CPU/GPU diagnostic, not live OpenXR FPS.

| Cluster condition | Original GPU p95 (ms) | Cached-frame GPU p95 (ms) | Original serial p95 (ms) | Cached-frame serial p95 (ms) |
|---|---:|---:|---:|---:|
| Selected idle | 14.48 | 10.46 | 15.40 | 10.91 |
| Translation | 14.30 | 10.39 | 18.29 | 16.81 |
| Rotation | 14.29 | 10.48 | 18.40 | 17.42 |

All four full-size captures (idle, selected idle, translation, rotation) were
byte-identical for the first cylinder-cache comparison. Candidate native regression tests
also passed pixel/depth/picking parity through weighted previews, commit, Undo,
style/owner/source changes, and view volumes. Static-hover tests verify that the
primary style is not rebuilt. Final builds passed interaction, renderer parity,
origin and asynchronous-refresh tests (4/4). Focused reporting tests passed
14 frame-audit, 12 dataset, 1 runtime and 35 tour-catalog tests.

First live CPU measurements, with desktop drawing off:
- Bend owner resolution: maximum 0.694 ms; the previous recorded worst case was
  427.143 ms. These are different runs/profiles, not a controlled speedup ratio.
- Bend highlights still reached 391.866 ms before the static-hover candidate.
- End Resize refresh activation: 1,282.294 ms after asynchronous parsing,
  versus the previous 4,187 ms input stall. The later one-pass/retirement
  candidate's final live result is reported below.
- Cluster Move passed edit, save/reopen and Undo. Bend failed post-commit stereo
  layout with an empty target list (a prior failure mode); End Resize retained
  the previously recorded requested +6 / saved −6 assertion. Neither is relabeled
  as a passing workflow because usable performance data were recorded.


### Final CPU observations

The selection-aware hover path was required: Bend keeps a committed cluster
selected while hovering. The initial empty-selection-only fast path never ran
in Bend. The final implementation compares effective selected/hover masks,
preserves the existing weighted preview channels, and avoids uploads when the
hover is hidden by the unchanged selected color. New parity cases cover that
priority rule, distinct hover geometry and subsequent fractional-weight motion.

Final steady-fast Bend: owner resolution maximum **0.788 ms**, static-hover
update maximum **0.312 ms**, overall highlight update maximum **39.357 ms**.
The first desktop-off candidate's overall highlight maximum was **391.866 ms**.
Selection changes still use the general path. These are whole-session calculation
maxima; ordinary measured Bend reaches remain around 45 FPS because the selected
cluster still exceeds the rendering budget. Empty visualization/style feedback
can still rebuild the style (observed 500+ ms outside the measured reaches).

Final steady-fast End Resize: activation maximum **422.586 ms**, down from
**1,282.294 ms** in the first desktop-off candidate; the largest measured frame
was **431.518 ms**. Other completed profiles observed approximately 436–452 ms
maximum frames. A deliberate-profile startup timeout produced no Ball & Stick
measurement and remains a coverage gap. Requested +6 / saved −6 is still a
workflow failure, independent of the timing improvement.

Both GPU experiments are rejected. No fundamental hardware ceiling has been
established: remaining software work includes staging style/object-ID/GPU
activation across frames, suppressing redundant visualization/style updates,
and moving rigid-owner preview transforms to the GPU without uploading the whole
model on each pose. Those require a new optimization round; the current retry
budget is exhausted for the targeted refresh, highlight and GPU paths.

## Final feature table

Ball & Stick on the full 24HB, browser desktop drawing off. Values are the lowest
application cadence and largest frame across completed requested-style intervals;
they are not averages across tools. Missing measurements remain missing. A workflow
pass includes assertions, not a claim of 90 FPS. Earlier rejected and interrupted
campaigns are excluded from this table. All four profiles were attempted for Move,
cluster Move, Bend and End Resize; other features use steady-fast verification.

| Feature | Measured cases / attempted | Workflow passes | Lowest interval FPS | Largest measured frame (ms) |
|---|---:|---:|---:|---:|
| Nucleotide Move/Rotate | 4/4 | 2 | 83.48 | 23.76 |
| Cluster Move/Rotate | 4/4 | 2 | 43.75 | 39.74 |
| Bend | 3/4 | 0 | 43.68 | 36.09 |
| Twist | 1/1 | 0 | 44.75 | 23.58 |
| End Resize | 3/4 | 0 | 87.34 | 452.05 |
| Extrude | 1/1 | 0 | 89.19 | 18.92 |
| Nick | 1/1 | 0 | 42.51 | 237.73 |
| Ligation | 1/1 | 0 | 20.89 | 261.76 |
| View tools | 1/1 | 0 | 29.48 | 35.94 |
| Simulation review | 1/1 | 0 | 29.85 | 36.33 |
| Dimensions | 1/1 | 1 | 88.21 | 22.26 |
| View volumes | 1/1 | 0 | 51.70 | 22.42 |

No feature is certified here for consistent 90 FPS across all operations/profiles.
Rows with no requested-style measurement are unverified, not hardware-limit findings.
Known failures include post-commit Bend/Twist layout, variable Move target acquisition,
End Resize +6/−6 semantics, and startup/input deadline failures. Exact failures and
intervals are preserved in the CSV/JSON evidence. Surface performance is excluded.

### Full and Stick controls

| Representation / feature | Workflow pass | Lowest interval FPS | Largest measured frame (ms) |
|---|---:|---:|---:|
| full / Nucleotide Move/Rotate | True | 71.61 | 25.28 |
| stick / Nucleotide Move/Rotate | True | 83.56 | 24.52 |
| full / Cluster Move/Rotate | True | 65.86 | 24.08 |
| stick / Cluster Move/Rotate | True | 44.22 | 33.43 |

### Verification and scope

Final retained-code attempts: **28**, with **9** complete workflow passes and **9** valid workflow/audit passes.
Native interaction, scene-refresh, origin and renderer parity checks passed (4/4).
Focused Python checks passed: frame reporting 14, dataset/export 12, runtime 1,
tour catalogue 35. No production frontend or molecular/topological change was made.
The desktop-off change is a benchmark default; the existing production preference
and native left-eye mirror remain as previously implemented.

Measurements use physical OpenXR/SteamVR with scripted controller profiles, not
a human comfort trial. The normal instrumented 90 Hz baseline reads approximately
89.5 application submissions/s. Compositor sampling has about 100 ms boundary
uncertainty. Inclusive calculation scopes overlap; do not sum them. Whole-session
records include diagnostic captures, while the feature table uses explicit intervals.

Evidence and portable review: `.development-artifacts/vr-research-fixes-20261002/`.
The compact `review/review.html` includes filters and CSV downloads. `cases.csv` and
`intervals.csv` at the campaign root also retain explicitly labeled earlier candidates.
The round patch and final source/binary hashes identify the retained implementation.

## Remaining bottleneck evidence

The following samples are the slowest requested-style interval for each feature,
not a sum of all calculations. The GPU column is compositor-reported pre-submit
scene span; it is not isolated shader execution. CPU and GPU values overlap and
must not be added. Short intervals and adjacent stalls can affect these samples.

| Feature | Non-wait frame work p95 (ms) | Compositor GPU span p95 (ms) | Evidence / next investigation |
|---|---:|---:|---|
| Nucleotide Move | 1.68 | 7.64 | Commit cadence dips despite ordinary work fitting the budget; investigate transition/pacing gaps. Variable acquisition still fails. |
| Cluster Move | 3.65 | 13.60 | Selected rendering exceeds 11.111 ms; model-sized preview uploads also remain. Both GPU candidates rejected. |
| Bend | 2.19 | 11.81 | Hover lookup is now cheap; selected rendering and general style updates remain. Post-commit layout fails. |
| Twist | 2.71 | 11.57 | Selected rendering exceeds budget; post-commit stereo layout fails. |
| End Resize | 5.60 | 7.31 | One activation is 443 ms in this interval, including 244 ms style work; frame-wide p95 hides this rare stall. Requested +6 / saved −6 remains. |
| Extrude | 5.76 | 7.85 | Measured reaches approach nominal cadence; input deadline failure prevents complete validation. |
| Nick | 7.05 | 7.73 | A 228 ms style rebuild coincides with the long reach frame and input deadline failure. |
| Ligation | 258.95 | 262.28 | A 253 ms selection/style rebuild dominates this short interval; the GPU span is not evidence of 262 ms shader work. |
| View tools | 5.57 | 32.41 | Rendering span exceeds budget; input deadline failure. Further per-pass GPU isolation needed. |
| Simulation review | 6.50 | 31.00 | Rendering span exceeds budget during review of existing results; capture/input deadline failure. |
| Dimensions | 1.07 | 7.92 | Workflow passes; occasional submission gap remains despite low ordinary work. |
| View volumes | 10.22 | 11.03 | Render-volume scope p95 8.82 ms leaves little margin; stereo visibility assertion also fails. |

Two shared highlight, refresh and GPU candidates were evaluated; this does not
mean two independent fixes were implemented for each feature in the table.
No fundamental hardware limit is proven. Staged scene activation, redundant
style-update suppression and GPU-side rigid preview transforms remain software
avenues for a subsequent round. These were not attempted beyond the retry cap.

Browser traces cover 155 of 238 final requested-style intervals; all sampled
desktop draw rates are zero. Native-only tools have no browser trace. Every final
case records the original design hash, 24 helices and 76 strands. Native audit
proofs omit a nucleotide count; the original full-size source has 6,720.

## Completion and cleanup

Research, implementation, live validation and review finished within the two-hour
limit (start 19:24:47 UTC; completion 2026-10-02T21:12:24.789885+00:00).
All 28 final attempts completed before the live-test cutoff; no final batch was
stopped for time. The retry cap was respected and the 90 FPS goal remains unmet.
View-tools and simulation rows identify the main representation; those features
can replace it with their own visualization streams. Consult CSV override flags.

The offline review was opened in Chromium: 28 coverage rows, 24 Ball & Stick rows,
working tool/representation filters, nine existing CSV download targets and no
JavaScript errors. Two final full-24HB selected-cluster captures are included;
they are diagnostic submitted-eye images outside timed intervals. Memory lint
passes with 0 errors and 62 existing size warnings; `git diff --check` passes.

All audit viewers are closed. Deleted 181 newly created temporary native cache
files (391,029,854 bytes) and 48 empty socket directories after checking process
ownership/references and preserving the preflight inventory. No new test designs,
bridge credentials, tour directories or native runtime files remain. Original
24HB hash is unchanged; user files, preexisting runtime files and managed jobs
are preserved. Failed attempts and raw evidence (approximately 32.0 GiB)
remain under the campaign directory on the Archive drive, outside the user
workspace. `cleanup.json` records removed-file hashes and final inventories.

[Interactive results](../../.development-artifacts/vr-research-fixes-20261002/review/review.html)
· [Compact review ZIP](../../.development-artifacts/vr-research-fixes-20261002/review-bundle.zip)
· [Retained code patch](../../.development-artifacts/vr-research-fixes-20261002/research-round.patch)
