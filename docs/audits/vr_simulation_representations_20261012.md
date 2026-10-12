# Simulation representations and simultaneous VR menus — 2026-10-12

The preceding simulation-menu, palette/PBC and trajectory-wheel work was committed
and pushed to `origin/master` as `a041054bb4ac3d0861ad2e968178c660bff81c80` before
this follow-up began. The follow-up removes the simulation snapshot's forced
closure of the right sidebar. Desktop and native representation controls share
the simulation allowlist: Full, VDW, ball-and-stick, stick, oxDNA, mrDNA coarse and
mrDNA fine. Off/native positions restore beads, cylinders, prisms and surfaces.

The selected simulation frame and scalar colors survive representation changes.
Sampled trajectory pages carry their source start/interval so atomistic requests
use the original frame ID. Comparison meshes reuse their allocations. Engine
atomic pathways remain authoritative; FEM/CG fallbacks use the existing deformed
axis and visualized-position atomistic builders without changing authored data.
Fallback requests are serialized, late responses are discarded, and preparation
uses the existing persistent loading indicator mirrored into VR. Compact FEM
frames retain nucleotide identities and can materialize the job snapshot on a
representation change.

## Checks

- Native simulation panel/trajectory tests: 2 passed; viewer rebuilt successfully.
- Focused frontend after corrections: 261 passed across ten files. SNUPI frame
  acknowledgement waits for the selected representation; cancellation rejects
  late completion. Atomistic fallback retains one in-flight and one newest queued
  frame, and coalesces duplicate requests during reconstruction.
- Focused backend: 9 passed, including a real atomistic-builder translation and
  topology-preservation check and SNUPI random-access frame identity/invalidation.
- Smoke: 23 passed, including real design rendering and Close Session teardown.
- Full frontend attempt: 7,884 passed, one skipped, one failed on the obsolete
  `Preparing Full visualization` text assertion. The corrected assertion passes
  in the focused runs; the full suite was not repeated for this text fix.
- `just test-smart`: 10,733 passed, 92 skipped, four setup errors in
  `tests/test_cpd_preview.py` (`Incorrect preview stereochemistry: cis-anti-I`).
  Those errors concern the separate CPD chemistry work; no CPD files were changed
  for this task. The guard deferred the broad/full sweep to `.nadoc-slow-pending`.
- `just lint`: the same five existing unused imports in `vr_prompts.py` and CPD
  tests. No additional lint errors from these changes.
- `main.js`: 7,375 → 7,363 lines (−12); implementation lives in scene/UI modules.

## Live evidence

Artifacts: `.development-artifacts/vr-simulation-representations-20261012/`.
The private fixture is `2hb_1xT`, P1 RunPod job `7d5937e569c6`, 1,226 source frames.
The tour explicitly loads the requested range, advances beyond the first frame,
opens both menus, checks disabled/reenabled representations, switches all seven
supported styles without changing physical coordinates/source frame, plays the
trajectory, and checks RMSF color retention through four styles and native restore.
Review probes wait for the actual native representation, require model pixels and
visible controls in both submitted eyes, and check delivery to the desktop window.

The model is placed above the two menus with ordinary scene grips and enlarged
once by a factor of two. These are observation adjustments outside measured
navigation reaches. Menu size, hit geometry and all four motion presets remain
unchanged. Per-step placement, input traces, state, stereo pixels and delivery
results are retained with the run.

All four final profiles passed: steady-fast, steady-deliberate, variable-fast and
variable-deliberate. Each completed 11 stereo review captures and two desktop
delivery checks (44 and 8 total). Results are in `final-profiles/result.json` and
the aggregate `review.json`. After this NAMD campaign, the separate SNUPI
reconstruction-wait path and bounded fallback queue received focused regressions
and another smoke check; SNUPI was not a live headset fixture in this campaign.
Rendered stereo and desktop delivery do not establish physical headset comfort,
through-lens legibility or uninterrupted 90 Hz delivery. Compositor and native
frame timing logs remain available; this change makes no new 90 FPS guarantee.
Each profile's approximately 10-second quiet playback sample recorded zero
dropped or reprojected frames at 90 Hz. Loading/switching intervals still recorded
drops; quiet playback must not be generalized to the entire operation.

Retained failures and corrections:

1. `initial/`: missing switcher helper export blocked loading; fixed with a
   regression. Owned validation was stopped and its viewer log retained.
2. `helper-fixed/`: steady-fast passed the dual-menu and trajectory/style path.
3. `visible-review/`: source edits triggered a development reload during capture.
   Subsequent live product validation keeps the source unchanged.
4. `final-steady/`: all trajectory styles and desktop delivery passed, but the
   RMSF review exposed repeated *test-helper* enlargement on reopening the right
   menu. The model occluded controls; the unchanged visibility gate correctly
   failed. Observation setup now enlarges only once per viewer session.
5. `backend-real-final.log`: a real-builder regression exposed native axes in the
   initial FEM atomistic adapter. Reusing the canonical deformed axes fixes the
   translation; the successful rerun is `backend-real-axis.log`.

The persistent app servers and SteamVR are preserved. Tour launchers own and
remove private job copies, documents, test processes and viewers. Immutable
trajectory input files are linked for read-only use in private workspaces; authored
designs and original results are not modified. Headset follow-up remains MV-43.
