# Live menu positioning validation (2026-08-21) — supporting detail

[Topic head](../../project_scrywrite.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Live menu positioning validation (2026-08-21)

- Witness v1 now supports `touch_menu <hand> <left|right|top|bottom>`, which resolves
  a controller position from the current production panel bounds rather than from
  authored world coordinates. `expect placement following|docked` and
  `expect menu_moved <meters>` expose the real `MenuPlacement` state and displacement.
- The canonical menu witness now opens Options, grip-drags its right border into a
  world-docked pose by at least 0.20 m, resets the ray origin away from the panel,
  then opens Tools and activates Move/Rotate with the existing independent hover,
  tool, and status assertions.
- A connected physical SteamVR/Vive run stayed in `SUBMITTED EYE`, passed the complete
  open/position/interact chain at ScryWrite frame 942, and reported a tracked physical
  observer pose. This validates application-side menu behavior on this runtime; it
  does not close the separate wearer-only legibility, stereo, comfort, or reach debt.

## Layered menu debugging and fault oracles (2026-08-21)

- `MenuLayoutAudit` is wired into production menu rendering. It uses the same fitted
  stroke geometry as drawing and exposes `expect layout valid`; the focused fault
  suite catches long-label overflow, below-floor fitted text, control overflow,
  undersized/misaligned/overlapping hit regions, and invalid geometry.
- `expect framing valid` projects the four actual panel corners into the scripted
  72-degree 16:9 actor camera. This was added after the first real actor-eye PNG
  revealed the lower menu was clipped; the corrected capture pose frames the complete
  tablet and excludes witness-only frustum/status overlays from its own image.
- Witness `snapshot` writes a real 960×540 OpenGL actor-eye PNG, a tolerant 32×18
  luminance fingerprint, and semantic JSON. The canonical trace retains five
  baselines: Options open, Tools hover, Tools open, Move/Rotate hover, and active.
  Playwright validates their ordered menu/hover/tool/status/layout sequence and
  attaches all images/state records under tracing.
- Live assertions distinguish `display submitted` from spectator fallback and require
  `tracking tracked` plus `overlay visible`. The final bounded run passed all five
  visual baselines and application assertions at frame 284 on the active Vive.
- `scripts/vr_diagnostics.sh` wraps loader-matched OpenXR core validation and API dump,
  Nsight Systems OpenGL/OS-runtime profiling, and an availability-gated RenderDoc
  workflow. Core validation passed the complete trace with no errors; API dump kept
  the frame-284 pass; Nsight emitted an 18 MB `.qdstrm` (this install lacks its report
  importer and kernel CPU sampling); RenderDoc is not installed and is not claimed.

## Full-origami atomistic MD validation (2026-08-24)

- Canonical runbook: [`docs/scrywrite_atomistic_md.md`](../../../docs/scrywrite_atomistic_md.md).
  Fixture is downloaded Alpine job `fc12195d0636` for `24hb_2xT`: 151,013 displayed
  DNA-heavy atoms and about 169k bonds from a 1,354,425-atom solvated topology.
- Root cause was native `GlScene::setStyle` doing repeated linear ownership/alias/tool
  searches per primitive plus large source copies/uploads. Hash indexes, immutable
  source pointers, atom-token indexing, and a validated shared Ball+Stick/Stick buffer
  path reduced repeated switches from crash-scale work to about 0.001 ms.
- Native atomistic rendering uses sphere impostors, line-bond LOD, and no dense-scene
  shadow pass. Exact physical-HMD scene work measured about 0.22 ms p50 / 1.6 ms p95.
  OpenXR loop duration is not render duration: runtime synchronization may block.
  `scene_p95_within_budget` is scene-only, not a complete budget gate. Include
  input/tool and pre-frame feed work with the opt-in frame calculation audit,
  plus active-headset SteamVR compositor statistics.
- Browser MD frames now use `atomisticRenderer.updateFrame`: stable topology updates
  matrices in place and emits `geometryPath: coordinates`; topology changes fail back
  to `rebuild`. Browser Ball+Stick/Stick changes reuse sphere and bond instances.
- `scripts/vr_atomistic_diagnostics.py` has `system`, `capture-md`, and
  `steamvr-stats`; all emit private JSONL process start/progress/end telemetry. The
  SteamVR gate rejects absent/inactive/timed-out HMD samples.
- `scrywrite_witness_atomistic_24hb.scry` semantically asserts the complete native
  representation boundary chain: Ball+Stick → Full → Ball+Stick → Stick → Full →
  Ball+Stick. The extended Vive run remained submitted/tracked, captured all six
  states, and passed at frame 514. Exact transition times were 309 ms Ball→Full,
  798–815 ms Full→Ball, 0.0005 ms Ball→Stick, and 321 ms Stick→Full. A clean 960×540
  submitted left-eye image visibly contained the complete CPK atom/bond assembly.
- Remaining cost is startup, not interaction: snapshot creation is about 58 seconds;
  the 82 MiB gzip expands to about 726 MiB, parses in about seven seconds, and leaves
  native RSS near 2.9–3.3 GiB. A future versioned format may deduplicate identical
  atomistic bond/ownership blocks only if semantic identity and Expanded parity remain
  strict.

## Live agent interface (2026-09-16)

- Runbook: [`docs/scrywrite_live_agent.md`](../../../docs/scrywrite_live_agent.md).
- Production viewer has opt-in private Unix-socket control (`--scrywrite-live`,
  modes inspect/control/transactions). `frontend/scrywrite/mcp_bridge.py` provides
  stdio MCP tools and follows the backend's private state file across relaunches.
- Browser launch opt-in: `?doc=<isolated-copy>&scrywrite=transactions`, then View in VR.
  Observe supplies session/sequence; stale actions and unsafe input fail closed.
- Native application/IPC gates exercise actual viewer handlers for lattice targets,
  paint/erase, wheel detents/input priority, panel drag, cancellation and input leases.
- Isolated browser gate exercises actual native-event receiver and real backend
  Move/Rotate Cancel/Confirm/Undo. Only the missing headset feedback transport is
  intercepted. This does not close combined native/browser/headset execution.
- Submitted stereo capture adds color, window depth, coarse render classes and
  semantic/transaction metadata. Same-pass uint32 primitive IDs now map to canonical
  owner tokens in `objects.json`, stable within the viewer session. Final overlay
  stencil masks IDs; decorative glow creates none. Compositor acknowledgement is
  still not claimed.
- Painted Extrude footprints remain explicitly unresolved/noncommittable. No new
  extrusion geometry mutation executor was added. Physical comfort/reach gates stay open.
- `just test-scrywrite-browser` uses dedicated ports/workspace and disables backend
  lifespan to avoid cloud autoconnection/job supervision alongside CPD work.

- Physical Vive validation 2026-09-16 passed on the existing SteamVR/X11 direct-mode
  path: focused/tracked submitted stereo, paint/erase, +21 bp wheel adjustment,
  0.10 m real grip drag, Cancel/release. Framed panels occluded design IDs correctly;
  baseline/final identity mappings stayed consistent. The diagnostic scene was the
  chiral fixture, standalone control mode, not browser-linked design editing.
- Retained report/images: `docs/generated/scrywrite/live_agent_20260916/README.md`.
  Raw stereo color/depth/classes/IDs and command traces are under
  `/tmp/nadoc-scrywrite-physical-20260916/` (ephemeral).
- New real-GL regression covers primitive shaders, front/rear occlusion, impostor
  discard, identity persistence, owner mapping, glow exclusion and overlay masking.

Visible-motion follow-up (2026-09-22): state success did not establish visible paint
or traces. Native contact layers now have dedicated stencil IDs and overlap-safe
strokes; new `visual_checks.py` verifies both-eye RGB/route/paint/persistence and
mirror-buffer parity, `desktop_check.py` verifies real X11 client pixels. Inspector
adds stage previews, magnification, and Paint and retain. All four profiles have
completed visibility confirmations; variable wheel detents still fail and long
combined runs have intermittent transport/timing failures. Evidence:
`.development-artifacts/scrywrite-inspector/visibility-05/validation.md`.
