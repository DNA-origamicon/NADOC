# Full size origami VR bottleneck isolation

Desktop rendering contention is a confirmed cause of missed 90 Hz deadlines,
but it does not explain every operation. Large selections also exceed the GPU
frame budget with desktop drawing disabled. Selection changes and topology
commits introduce separate, substantial render-thread stalls.

This follow-up uses the [completed two-hour campaign](vr_ballstick_90hz_20261002.md)
and fresh controlled physical OpenXR runs on private copies of the same 24HB
(24 helices, 76 strands, 6,720 nucleotides). Surface performance is excluded.
The earlier two-attempt results are preserved; these are new diagnostic controls
and validation of the desktop preference, not rewritten earlier results.

## Desktop contention control

Same retained native binary, full-size source, Ball & Stick representation,
controller profile, framing procedure and production eye resolution. The browser
stays visible and focused. Only its native-VR desktop draw gate changes; animation,
trajectory-clock ticks, state updates and transaction callbacks continue.
A one-shot test response override supplies the diagnostic gate, then removes
network interception before the native probe. No production shader or geometry
quality changes. The native eye mirror remains enabled in both conditions.

Representative three-second selected-idle intervals, before inspector polling:

| Selected target | Desktop 3D | Application FPS | Compositor GPU p95 ms | Device utilization median | Browser draws per second |
| --- | --- | ---: | ---: | ---: | ---: |
| Nucleotide | On | 47.46 | 12.71 | 70.5% | 60 |
| Nucleotide | Off | 89.53 | 7.51 | 68.0% | 0 |
| Cluster | On | 44.76 | 18.21 | 82.0% | 52 |
| Cluster | Off | 44.76 | 12.69 | 55.5% | 0 |

All four complete control workflows pass editing, save, reopen and Undo.
Desktop-off callbacks continue at approximately 60 Hz. Nucleotide motion reaches
89.55 and 88.20 FPS, but its commit interval averages 80.59 FPS: this is **not** a
claim of consistent 90 FPS editing. Cluster motion remains about 44.76 FPS and
reaches 18.32 ms GPU p95 during movement even without desktop draws.

A GPU need not report 100% utilization to miss a VR deadline. At 90 Hz the budget
is 11.111 ms. A roughly 12.7 ms GPU span already exceeds it. Falling to a roughly
22.2 ms application cadence introduces idle time; 12.7 / 22.2 is approximately
57%, consistent with the observed cluster utilization. This is a scheduling
interpretation, not a direct measurement of shader occupancy. Device-wide
utilization cannot establish a fundamental hardware ceiling.

Utilization, power and clocks were sampled with `nvidia-smi` every approximately
0.52 seconds. NVIDIA's installed query help defines utilization over a preceding
sample period, so short moving/commit windows have weak utilization attribution.
The stationary rows each have six samples. GPU clocks were automatic: 1770 MHz
for both nucleotide conditions, 1980 MHz for cluster-on and 1770 MHz for
cluster-off. Thus this is a production-condition comparison, not a locked-clock
microbenchmark. The cluster improves despite its lower off-condition clock.
Compositor spans include scheduling effects and are not pure shader execution
measurements. CPU wall time, GPU spans and overlapping calculation scopes must
not be added together.

The first desktop-off setup retained Playwright request interception while its
native probe blocked the test worker. Browser API responses then stalled for
approximately 100 seconds and selection timed out before Ball & Stick. Those two
failed cases are retained under `off`; they provide no Ball & Stick performance
comparison. The corrected `off-corrected` cases remove interception before probes
and both pass. No focus-emulation dependency patches or browser minimization remain.

## Causes by operation

The ranges below summarize per-interval GPU p95 from the earlier 48-case matrix,
not pooled frame percentiles. Later stages of failed workflows remain unverified.

| Operation or setting | Earlier GPU p95 ms | Isolated cause or evidence | Remaining uncertainty or next target |
| --- | ---: | --- | --- |
| Nucleotide Move | 12.35–14.45 | Fresh draw-only control recovers nominal 90 Hz selected idle; desktop contention confirmed | Motion/commit outliers remain; inspect buffer upload, transport and runtime phases |
| Cluster Move | 17.90–23.11 | Fresh desktop-off native GPU span still 12.69 ms idle and 18.32 ms in motion | Extra selection glow and full-channel preview uploads are concrete software targets; their separate GPU shares are not measured |
| Bend | 17.00–17.78 | 838 ms selection frame contains 427 ms owner resolution and 401 ms style rebuild | Sustained GPU cost resembles large-selection workload; a Bend-specific desktop-off control is still needed |
| Twist | 16.54–17.36 | Sustained half-rate submission with GPU span above budget | Selection/glow and desktop contention are likely contributors, not independently proven for Twist |
| End Resize | 7.32–14.25 | 4,211.52 ms frame contains 4,187.00 ms synchronous input/application work, with a scene-refresh log in that frame | Stage replacement scene work; separately time parsing, scene construction, GPU uploads and old-scene destruction |
| Nick and Ligation | 12.04–13.81 | GPU spans exceed budget even in stationary observations | Desktop contention likely from same browser workload; completed topology commits need separate refresh profiling |
| Extrude | 7.44–14.45 | Some intervals sustain nominal 90 Hz; others exceed GPU budget | Conditions and incomplete workflow stages prevent attributing every failure to one cause |
| View Tools | 12.05–13.83 | Stationary half-rate behavior with GPU span above budget | Isolate desktop contention, panel render cost and individual toggles |
| Simulation controls | 12.13–13.20 | Control-panel sessions exceed GPU budget | Does not measure active simulation compute or dynamic trajectory playback |
| Dimensions | 7.56–8.57 | Usually nominal 90 Hz; occasional ~22 ms frames despite GPU headroom | Runtime/scheduling outliers, not evidence of sustained GPU saturation |
| View Volumes | 11.27–11.47 | Native-only run: GPU just over budget and non-runtime-wait work p95 ~10.7 ms | Multiple scene passes and serialized work; desktop-off alone cannot explain this case |

## Source level mechanisms

* **Selection owner lookup:** `resolveSelectionVolumeHits` rebuilds a token-kind
  vector each call. `selectionVolumeOwnerToken` linearly searches all aliases for
  each hit and the token-kind vector for each candidate owner; default selection
  can resolve the same hit several times. Cache identity-to-owner and typed-token
  indexes when the source representation changes, preserving exact selection rules.
* **Highlight invalidation:** `setSelectionHighlights` correctly skips identical
  sets, but any changed snap/selection set calls full `setStyle`. This is not an
  every-idle-frame rebuild. Separate changing highlights from stable base buffers;
  invalidate geometry only for geometry changes.
* **Scene refresh:** `sceneRefresh_.poll` calls `loadScene`, constructs `GlScene`,
  applies style, visualization and selection, swaps scenes, and destroys the old
  scene synchronously inside `syncActions`. `VR_SCENE_APPLIED revision=7` appears
  immediately before the End Resize 4,187 ms input trace. The broad scope confirms
  a render-thread blockage, not that all 4.19 seconds is pure CPU arithmetic.
  Use the existing asynchronous preparation/staged-upload approach for refreshes,
  while preserving revision guards and atomic activation.
* **Move preview:** only edited instance entries are transformed, but each changed
  channel uploads its entire buffer, and bounds visit all points, cylinders and
  boxes. A single-base edit can therefore still transfer model-sized buffers.
  Track affected ranges or retain transforms on the GPU, with exact endpoint
  weights, bounds, picking, commit and Undo parity checks.
* **Selected rendering:** enlarged additive glow instances are drawn for selected
  spheres/bonds in each eye with depth writes disabled. A whole-cluster selection
  substantially expands this work. It is a strong candidate for the residual GPU
  cost, but this audit did not disable glow to measure its isolated contribution.
* **Hidden browser:** cluster commits await two `requestAnimationFrame` callbacks.
  Minimizing/hiding the browser can suspend them. Suppressing drawing while the
  document remains visible avoids that dependency; the new preference does not
  claim to repair hidden-tab transaction scheduling.

Source anchors and exact log excerpts are retained in `source-findings.json` and
`end-resize-scene-refresh-evidence.json` in the evidence directory.

## Desktop visualization preference

**Help → Desktop 3D during VR** now controls the browser's main 3D viewport during
native VR. The current enabled default is preserved; the user's choice persists
locally. Turning it off displays a paused notice and a **Resume desktop 3D** button.
Leaving native VR resumes normal desktop drawing automatically, while preserving
the preference for the next VR session. Browser WebXR rendering is not suppressed.

Scene updates, callbacks, editing and synchronization remain active. This is
not suspension of browser computation or every auxiliary preview renderer, and
it does not disable the native eye mirror. Keep the browser document visible;
hidden-tab animation suspension remains a separate issue. No saved origami
geometry or representation quality changes. `main.js` grows by two lines, for
one import and one factory initialization; behavior resides in the tested module.

## Verification and artifacts

Frontend unit suite: **7,345 passed, one skipped, 590 files passed**.
Application smoke and teardown checks: **23 passed**. Tour/catalog checks:
**35 passed**. Repository lint passes; memory lint has zero errors and 62 existing
size warnings.
Final live preference validation (`preference-off`) covers nucleotide and cluster
Move under all four motion profiles: **four of eight complete workflows pass**.
Both steady profiles pass for both targets, including toggle/resume, zero desktop
draws with advancing callbacks, edit/save/reopen/Undo and automatic restoration
on VR exit. The variable profiles retain the earlier target-acquisition failures:
“selected geometry was not pointed at” for nucleotide and “grab was not remote”
for cluster. No thresholds were relaxed. The native tool's later stages remain
unverified in those cases.

Consistent 90 Hz is still unmet: the steady-fast nucleotide commit contains a
51.53 ms frame (43.76 ms maximum `xr_end` phase, 14.32 ms maximum non-runtime-wait
work; these maxima are not summed). Its commit interval averages 74.99 FPS.
The steady-deliberate commit averages 78.35 FPS. Desktop-off therefore fixes the
sustained nucleotide selected-idle bottleneck, not every transaction/frame outlier.
Cluster selected idle and motion remain around 45 FPS.

Visual inspection caught the paused notice clipped behind a sidebar. Its final
placement uses the viewport instead of the scrolled canvas, with an occlusion
assertion added to the live check. Final UI verification is recorded separately
under `ui-final` (complete workflow passed); `ui-review` additionally dismisses
the focus-held Help menu for an unobstructed review image and also passes the
complete workflow. Neither is a new
rendering optimization candidate.

[Compact review ZIP](../../.development-artifacts/vr-bottleneck-isolation-20261002-review.zip)
and [evidence directory](../../.development-artifacts/vr-bottleneck-isolation-20261002/)
contains raw logs, stereo images, browser draw/callback traces, GPU samples,
source hashes, individual intervals and source findings. `ab-summary.json` retains
all measured intervals; `on`, `off-corrected` and `preference-off` are distinct
conditions. The original failed `off` setup is retained separately. The source
24HB hash remains the reference from the earlier campaign. Captured stereo views
prove rendered output, not physical wearer comfort or panel scanout.

Cleanup verification confirms 16 source proofs with the exact full-size counts,
the unchanged original design and native binary, no active owned viewer, no
remaining private workspaces or new browser-bridge credentials, and no default
Playwright report/output directories. Six stale credentials from the initial
controls were removed only after verifying their processes had exited; older
unrelated credentials were preserved. Later runs clean up automatically through
the corrected teardown. All changes remain local and uncommitted.
