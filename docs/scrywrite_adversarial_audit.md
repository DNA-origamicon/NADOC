# ScryWrite adversarial audit

Status: second remediation tranche implemented 2026-08-21; remaining claims are
explicitly bounded below.

## Audit question

For every metric, assertion, and UI cue: can it pass while the tester is wrong, and
does it prove something useful about the eventual browser/native/OpenXR system?

## Findings and dispositions

| Surface | False-positive path | Larger-system fit | Disposition |
|---|---|---|---|
| Headless semantic CLI | Arbitrary identities were accepted and transaction feedback was injected by the same harness. | Useful unit test of the native interaction state machine, not a scene or persistence test. | Retain, but never label it end-to-end. Scene identity and browser acknowledgement remain required for MVP. |
| Witness menu assertions | Menu/hover can pass even if the framebuffer is black; the canonical script previously clicked Move/Rotate without checking the resulting tool state. | Real menu layout and hit-testing are useful independent oracles. | Added `expect tool` and `expect status`; canonical script now requires `move_rotate` and `select_target`. Pixel/readback checks remain open. |
| Witness failure behavior | A failed replay could leave a scripted trigger/grip held. | Unsafe and capable of causing misleading post-failure UI state. | Failure and completion now neutralize every scripted button and hand press. |
| Head frustum guide | Guide was narrower than the 72-degree vertical, 16:9 actor camera. | A misleading guide defeats live diagnosis. | Corrected to the actor capture projection. |
| Software POV “visible” count | A primitive up to 100 pixels outside the viewport counted as visible; a 55-degree wrong-facing view returned success while its PNG was nearly blank. | Useful only as a projection diagnostic, never as proof of OpenGL/OpenXR output. | Replaced by strict expectation manifests and v2 metrics: in-front, in-frame, fully-contained, clipped, readable, occupied projected bounds, and gaze error. Unchecked exports say `not_evaluated`; checked failures exit nonzero. |
| Six-helix flat tile | Could not expose depth, roll, front/back reversal, or handedness mistakes. | Too symmetric for a perspective regression. | Replaced as the default by a tilted diagnostic derivative of `workspace/Chiral_test.nadoc`, retaining its 12-axis asymmetric long/short-arm silhouette and adding four colored endpoint markers. |
| “Origami yaw” metric | PCA has a 180-degree ambiguity and can be unstable for near-square shapes. | Helpful telemetry, not a universal assertion. | Renamed `structure_long_axis_yaw`; no default pass threshold is attached to it. Endpoint markers and exact future object-ID comparison must carry handedness. |
| Scene parser | Evidence loader reads the first natural Full representation and has a smaller grammar than the production viewer; it does not render the frontend hull prism. | A duplicated parser can drift and cannot establish parity. | The chiral fixture is explicitly diagnostic, not topological or renderer parity evidence. Sharing the production scene model is a prerequisite for render-tier claims. |
| “Readable” metric | Projected diameter/length cannot prove text legibility, contrast, occlusion, or correct shading. | Useful rejection of subpixel geometry only. | Metric is named and documented narrowly. Real framebuffer pixels, depth/object ID, and physical-headset checks remain separate gates. |
| In-VR actor monitor | Fixed placement can occlude the observer; semantic hover is not hand-labelled; there is no timeline/scrub control. | Valuable troubleshooting console, incomplete test UX. | Retain for POC. Add hand identity, current/next command, frame, pause/failure cause, movable/dockable panel, and artifact trigger before MVP. |
| HMD pixel liveness | A frame counter can advance while pixels stay black; a hash can change from subpixel jitter while useful content remains frozen; identical pixels are valid for a stationary headset. | Real submitted-eye color is the first bridge between pose telemetry and visible output, but it is not compositor acknowledgement. | Added 64×64 color sampling every 30 mirror frames. Report `BLACK` independently; report unchanged pixels as `STABLE` unless pose moved, then only `FROZEN?`; report changing pixels as `CHANGING`, never the overclaim `OK`. Persist frame, wall time, predicted OpenXR display time, source, signature, luminance, nonblack/change fractions, and pose deltas in JSONL. Thresholds remain diagnostic, not acceptance criteria. |
| Grid versus design | A nonblack/color-changing frame can consist entirely of the diagnostic cage; color segmentation is unsafe because design and grid palettes can overlap. | Coarse render classes close the grid-only false pass before exact object-ID assertions exist. | Added same-pass stencil tags for visible design, reference grid, and overlays. The 64×64 trace reports independent counts/fractions and the title says `DESIGN+GRID`, `DESIGN ONLY`, `GRID ONLY`, or `NO TAGS`. Four samples establish presence. This proves category coverage only, not expected identity, shape, topology, depth, or correctness. |
| Startup placement | A runtime can briefly label a discontinuous startup pose tracked, consuming one-shot head-relative placement before the stable physical pose arrives. | Reliable fixture framing is prerequisite to meaningful visibility diagnostics. | Placement now waits for 15 consecutive fully tracked poses with no step above 5 cm or 5 degrees; any invalid/untracked pose or discontinuity resets the gate. |
| View-relative framing | Hand-authored world coordinates and ad hoc quaternion edits are slow, nonportable, and difficult to reconstruct after a failure. A preset name can still be wrong for the authored model axes. | Repeatable view targeting is the setup layer for every later render and interaction assertion. | Added one-command `scrywrite-frame`, explicit `mirror`/`head`/left/right targets, seven orientation presets, bounded distance/scale/Euler overrides, an `O <PRESET>` title cue, an applied console record, and complete JSONL placement metadata. Presets establish a transform contract, not semantic proof that the chosen face is desirable. |

## Strict evidence contract

An evidence export may claim PASS only when supplied a bounded
`SCRYWRITE_EVIDENCE 1` manifest. The checked-in chiral manifest currently requires:

- exactly 16 expected primitives;
- 100% intersecting and 100% fully contained in the 1280x720 actor frame;
- zero clipped primitives;
- 100% above the fixed minimum raster footprint (1-pixel thickness and 3-pixel
  segment length, or 3-pixel point diameter);
- at least 2% occupied projected bounding area; and
- no more than 1 degree of gaze-to-structure-center error.

These are geometry/projection checks. They deliberately do not claim occlusion,
shading, menu presence, stereo correctness, physical scale, or compositor output.
The unit mutation rotates the actor 55 degrees away and must fail.

## Desktop view of the physical dummy headset (POC implemented)

The requested desktop mirror is a separate, complementary observer source:

```text
physical HMD pose + OpenXR render permission
                    |
                    +--> SUBMITTED: copy actual app eye image
                    +--> SPECTATOR FALLBACK: live pose/FOV rerender
                    +--> future timestamped artifact/submission correlation

scripted actor camera + semantic overlays
                    |
                    +--> Witness panel / deterministic evidence
```

When OpenXR accepts frames, the POC copies the selected physical eye's undistorted
application swapchain image after NADOC drawing and before release. When the runtime
suppresses rendering, it instead rerenders from the latest located eye pose/FOV and
labels that source `SPECTATOR FALLBACK`. It aspect-fits without cropping and remains
observational. Physical-HMD/scripted-actor split views, screenshot/video hooks, and
OpenXR submission correlation remain. Until then it is a spectator and
troubleshooting view, not an acceptance oracle. See
`docs/scrywrite_desktop_mirror.md`.

The first dummy test reported a black desktop under headset motion. A subsequent
composited-window capture showed the real VR clear-color image but could not prove
pose motion because the design was outside the eye frustum. The opt-in room grid now
surrounds OpenXR LOCAL origin with six direction-colored faces, independent of scene
placement and controller focus. Frame/pose telemetry then isolated a second freeze:
SteamVR returned `shouldRender=false` after its first submitted frame, consistent with
an unworn dummy-mounted headset. The fallback now advances its local frame counter,
tracks pose, displays a pixel heartbeat, and keeps the grid live without implying an
OpenXR submission. Same-direction deliberate headset motion remains the decisive
physical check.

That physical check is now complete for the left eye. The user confirmed that the
desktop mirror moved with the dummy, then disabled SteamVR's idle pause and confirmed
that the room grid and framed asymmetric chiral origami visible in the `SUBMITTED`
desktop eye were also what the physical headset displayed. With the dummy leveled,
live telemetry reported yaw about −110 degrees and pitch about −0.6 degrees while
remaining `TRACKED` and `SUBMITTED`.

The next tranche samples the actual companion eye image before its desktop heartbeat.
The live leveled run established a nonblack baseline near 12.8% and then reported
`PX CHANGING`; its JSONL samples correlate local mirror frame, wall-clock milliseconds,
OpenXR predicted display time, source, pixel signature/statistics, and pose delta.
The high-value `PX` cue now follows the source at the start of the title so the default
companion width does not hide it behind lower-priority pose telemetry.
The next tranche closes the specific grid-only false pass with same-eye-framebuffer
stencil classes. A live `PLACE=off` mutation produced 74/74 `GRID ONLY` samples with
zero design coverage; the framed run produced 276/276 `DESIGN+GRID` samples with up
to 2.44% design coverage and no unknown tags. Antialiasing can still change color
without meaningful content change, 64×64 sampling can miss a small localized defect,
and any design primitive—not necessarily the expected origami—can satisfy the coarse
design class. Exact per-object identity and depth remain the next render-tier gate.

The trace also records synchronous readback CPU milliseconds. This is necessary
because a detector that perturbs frame pacing can manufacture the behavior it claims
to diagnose. Across 276 samples from the classified live build, combined color and
stencil readback averaged 0.44 ms and peaked at 1.45 ms—about one eighth of the
11.1 ms runtime period in the worst observed sample. Earlier stationary runs also
showed `CHANGING` driven by sub-threshold tracking/raster variation, so that label
must not become a movement or correctness pass. The cost is acceptable for this
sparse POC diagnostic, not a production design; asynchronous pixel-buffer readback
should replace it before continuous capture.

## Ordered remaining work

1. Replace the evidence-only scene parser with the production parsed scene model and
   representation selection.
2. Extend the implemented coarse design/grid stencil classes with exact expected
   object IDs and depth/occlusion evidence.
3. Unify the headless and Witness scenario models and correlate commands, frames,
   browser transactions, and artifacts in one trace.
4. Add independent scene locators, ray-hit outcomes, native state, browser persisted
   state, and pixel/object-ID assertions for one isolated Move/Rotate flow.
5. Promote the mirror POC beyond its implemented local frame/predicted-time JSONL and
   black/invariant diagnostics with live eye/split selection, artifact capture, and
   actual runtime/compositor acknowledgement where available.
6. Expand mutation tests for horizontal/vertical clipping, behind-camera geometry,
   mirrored endpoint markers, occlusion, black frames, stale identities, and delayed
   or missing browser acknowledgement.
7. Only then add Monado/runtime CI and calibrated stereo image metrics; retain real
   headset gates for tracking, scale, reach, comfort, haptics, and legibility.
