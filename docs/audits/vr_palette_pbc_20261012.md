# Controller colour maps and P1 RunPod periodic images — 2026-10-12

Evidence: `.development-artifacts/vr-palette-pbc-20261012` on Archive.

## Changes

The live simulation colour picker uses the existing left-controller prompt dock,
fresh press/slide/release gesture, centre dead zone, three spaced haptic requests,
and tracking/focus-loss suspension. Six annular sectors show each desktop palette
from low at the inner radius to high at the outer radius, without text labels.
Hover and current selection have separate edge highlights. The tablet retains the
horizontal scale/min/max controls. Picker input is modal and cannot leak into
selection, model grabs or other tools on the release frame. The desktop A/B gallery
remains a separate reference viewer.

The P1 RunPod job is `7d5937e569c6`, archived beneath
`/media/jojo/Archive/NADOC_archive`. Its immutable DCD has 1,226 frames and 93
phosphate rows in three PSF segments. Exact strand IDs alone made no difference to
the reported defect. The circular-centroid pose could fold this narrow-cell
assembly and force an already intact strand into an incorrect periodic image.
Additionally, the median of an even-length strand's integer image indices could
be half-integral: scaling that median translated a strand by half a cell.

Shared reassembly now rounds the median lattice index before scaling and includes
the original, sequentially unwrapped assembly among its rigid-fit-scored image
candidates. It preserves the existing global proper rotation/translation and all
recorded local conformations. Playback, Full display, RMSF and metrics use the same
correction; extraction contexts now carry exact PSF segment IDs, including the
lightweight cached context (cache version 5). No topology, molecular backmapping,
force-field constant, saved design, simulation configuration or trajectory changed.

## Measured P1 result

Full-frame comparison uses the job's frozen design and all 1,226 frames. Baseline
shared reassembly was recovered from Git HEAD, where it matched the starting
worktree. Only derived private arrays and reports were written.

| Measurement | Before | After |
|---|---:|---:|
| Maximum aligned phosphate RMSD to design | 2.886 nm | 0.870 nm |
| Mean phosphate RMSF | 1.038 nm | 0.288 nm |
| Maximum phosphate RMSF | 2.471 nm | 0.582 nm |
| Frames with fractional lattice shifts | 53 | 0 |

Relative strand images change in 624 frames. The maximum lattice-index residual
and maximum difference in within-strand displacement vectors are both exactly
zero at the comparison precision. The ordinary `md_rmsf` calculation (150 samples,
including phosphate-free terminal bases) returns mean RMSF 0.28750 nm.

The first invariant script accidentally subtracted float32 inputs before comparing
to float64 output, reporting 2.98e-8 nm subtraction roundoff. Comparing both in
float64 removes that artifact without changing the tolerance. Both logs remain.
The initial 80-frame strand-ID-only diagnosis and candidate comparison remain too.

`pbc-review.png` / `.pdf` show before/after coordinates in a shared design frame,
RMSD and per-phosphate RMSF. These are reconstruction diagnostics, not evidence of
new sampling or improved physical convergence. In-memory browser analyses must be
reloaded/regenerated to replace results calculated before the correction.

## Validation and limitations

Focused periodic reassembly, trajectory binary/prefix extraction, playback tables,
P-order mapping and metric checks: **52 passed**. Native build and all three
selected model/OpenGL checks pass, including radial colour samples and absence of
text rendering. `just smoke`: **23 passed** (1.3 minutes), with console/teardown gates
and zero leftover prefixed artifacts. No production frontend JavaScript changed.
Scoped Ruff passes; `just lint` retains five pre-existing unused imports in
`vr_prompts.py` and CPD tests.

The first live steady-fast run passed in 2.1 minutes. Visual inspection nevertheless
found partial tablet occlusion; its initial pixel test accepted merely varied
colours and was too weak. The final probe places the controller forward/right via
ordinary pose input and requires each radial sample to match the desktop palette
anchors (plus an offscreen negative). No target geometry, profile or timing limit
was changed. Maximum observed colour-channel error was 26.14 / 255 against a 35
threshold, in both submitted eyes; actual desktop mirror delivery also passed.

| Unchanged profile | Final result |
|---|---|
| steady_fast | Complete six-map selection, flex, Load and playback pass (1.5 min) |
| steady_deliberate | Complete six-map selection, flex, Load and playback pass (1.8 min) |
| variable_fast | First wheel and map selection pass; three subsequent attempts miss the existing small palette opener |
| variable_deliberate | Three attempts miss the initial palette opener; no wheel capture |

Failed controller paths and traces are retained. This is unresolved pointer
acquisition debt, not a fully passing four-profile campaign. Through-lens comfort,
physical haptic perception and compact opener tolerance remain MV-43. The test
controller's observation pose is distinct from production dock placement. Debug →
VR Tours & Tests → Left sidebar → Simulation jobs · Full + trajectory includes
these six-choice checks whenever a scalar view is available. The tested viewer
binary was installed at the normal launch path; reopen VR to use it.

The first broad FAST run had 10,711 passes, 93 skips, 18 failures and four CPD errors.
Seventeen failures lacked Node on the shell PATH; one temporary worker socket path
was 111 bytes (AF_UNIX limit). Follow-up uses the installed Node and a short Archive
TMPDIR. The CPD-preview errors report the existing cis-anti-I stereochemistry issue.
All 18 environment failures cleared in focused reruns: 19 representation/axis
checks and eight Alpine worker checks pass. The broad suite was not rerun to hide
its initial failures; its remaining known errors are the four untouched CPD cases.
Slow-test triage found tiny, mocked fixtures dominated by durable Archive I/O:
peer pull took 10.22 s in the sweep but 0.89 s in isolation; shared engine job
preparation took 6.10 s but 2.46 s in isolation. Neither launches a solver or loads a
large scientific fixture. No test reclassification or budget changes were made.

Broad-suite debt, as reported by the selector:

> DEFERRED: this change would have needed the FULL suite, but no test-dedicated
> session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
> This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
> Only request `just test-session` when a broad/full sweep is actually needed.

No production frontend JavaScript changed; `main.js` remains 7,375 lines (task delta 0).

## Cleanup and review artifacts

All task-created temporary workspaces, extracted caches, socket/export scratch and
the temporary smoke report symlink were removed after checking active process and
open-file dependencies. `cleanup-inventory.json` and `cleanup-result.json` retain
the exact inventory. The original 2HB design and archived job/design hashes match
`source-inventory.json`. User dev servers and the pre-existing SteamVR compositor
and monitor remain running. No viewer remains from the tests. No commit or push.

- `controller-palette-vr.png`: final steady-fast submitted-eye capture.
- `pbc-review.png` / `pbc-review.pdf`: shared-frame reconstruction comparison.
- `full-oracle.json`: all-frame numerical invariants and the ordinary RMSF result.
- `native-tests.log`, `final-checks.json`: native/software/smoke outcomes.
- `live-four/result.json`: all four unchanged profiles, including both failures.
