# Viewer extraction inventory

Checkpoint: Phase 0 committed as `978e5dda`; shared runtime and experimental static
prepared packages now extend the decoder extraction. `viewer.html` opens supported
visible-scene snapshots without an editor backend. Temporary public HTTPS sharing
and camera-only presenter rooms extend that snapshot path. Full phase acceptance remains open.

| Component | Current dependency | Standalone boundary / acceptance |
| --- | --- | --- |
| Scene/navigation | `viewer/runtime.js`; `scene/scene.js` compatibility export | Editor and prepared viewer reuse controls, loop and resize; runtime disposal cancels frames/animation, removes input listeners, disconnects resize and releases renderer/controls. |
| Full part rendering | `scene/design_renderer.js`: injected store; helix renderer and display overlays | Feed prepared geometry through a viewer state adapter; preserve subscriber order and physical overrides. |
| Geometry decoding | Previously embedded/duplicated in `api/client.js` | Now `viewer/geometry_codec.js`; editor imports it. Same coordinates/metadata and shared assembly arrays, no API/store dependencies. |
| Full assemblies | `assembly_renderer_shared.js`: injected API, batch/instance requests, store | Supply scene-source adapter; preserve unique-source geometry and instance transforms. Include linkers/connectors and per-instance overrides. |
| Proteins | `protein_subsystem.js`: direct `/api/design/protein/atomistic` fetch | Export required protein model assets and inject their provider. Verify conjugation/placement against Voltron. |
| Nanoparticles | `nanoparticle_subsystem.js`: editor patch/delete imports | Separate visual construction from edit gestures; preserve handles, sizes, materials, and selection. |
| Atomistic/surface | Backend-generated models; renderer geometry builders | Package static topology/model assets; request only agreed representations. No hidden editor API fallback. |
| Scientific selection | `selection_ref.js`, selection controller/manager, ownership maps | Stable references, guest selection and presenter attention separated, assembly instance IDs retained. |
| Recorded MD | Existing binary atom model/frame parsers and trajectory paging/cache | Preserve model/serial identity; bounded on-demand frames; handle cancellation, out-of-order arrival and reconnection. |
| Graphene/solvent/ions | Graphene display controls and MD transport-specific overlays | Preserve membrane coordinates, solvent subsets, periodic cell, units and transport-analysis context. A DNA-only package is insufficient. |
| Application startup | `main.js` boot and store subscriptions | Extract factories while preserving order; no second copy of the editor composition root. |

## Selected scientific fixtures

Read-only inventory on 2026-09-20 (files may legitimately evolve afterward):

| Fixture | Bytes | SHA-256 | Coverage |
| --- | ---: | --- | --- |
| `workspace/VoltronCoreArmV2.nadoc` | 83,744,004 | `f0c03351c3962b6a50ae96e7e8cfb5e6722701572be36d9aca3b85df066148f6` | 71 helices, 449 strands, one protein asset/attachment and one nanoparticle; 109 feature entries. |
| `workspace/cube_pore.nadoc` | 587,952 | `124aa73e89681935185a224c998b16fe1b843e3d54f3fc716087f4646fbef1c3` | 36 helices, 43 strands; recorded MD with graphene, ions, solvent/cell and transport context. |

Completed cube_pore jobs include `796c568b5690` (100 ns named production DCD,
20,282,697,580 bytes) and `a4cb52583c26` (200 ns named production DCD,
47,859,659,852 bytes). These are file-size/status observations, not a validation of
physical completion or convergence. Job metadata and graphene metadata were read;
no trajectories were copied, altered, or run. Use a frozen selected frame interval
and immutable topology when this benchmark reaches recorded-playback extraction.

A small repeated-part assembly remains useful for instance deduplication checks;
the existing assembly smoke harness provides that software check. A large assembly
fixture still needs to be selected/generated in an isolated workspace.

## Capture coverage and remaining evidence

- Implemented: repeatable orbit and freeform frame sampling, copyable logs, build
  identity, invalid-run handling, sampled heap availability, render resource counts.
- Implemented: detached baseline preparation and opt-in real-design headless probe.
  The latter uses a copied test identity and omits feature history. It measures
  renderer interaction, not the original file's full load cost or scientific parity.
- Verified: production-build repeated static Voltron GPU A/B on the user's hardware;
  initial gates pass, with identical overview PNGs and restored camera/controls.
  See [the comparison](audits/viewer_ab_production_20260920/README.md).
- Pending: full-scene readiness and picking latency, geometry/asset/trajectory content hashes,
  capture overhead measurement, trajectory playback and large-assembly evidence.
- Phase 1 first extraction has unit checks for coordinate/identity preservation,
  optional metadata, legacy input, error propagation and shared array identity.
  Further viewer restructuring is gated by the broader performance/visual evidence.

## Committed diagnostic checkpoint verification

- Full frontend suite after production automation: 471 files, 6,672 tests passed.
- Latest targeted transport/server/bridge suite: 3 files, 11 tests passed.
- Standard smoke: 23 passed; final capture + assembly teardown exercise: 2 passed.
- Production frontend build and repository lint passed. Build retains the existing
  large-chunk warning; no bundle-size optimization is claimed.
- Historical headless and user-reference records remain under `docs/audits/`.
  The static Voltron production checkpoint passes initial performance gates;
  standalone package, assembly, recorded playback, and meeting gates remain open.
- Test-created prefixed workspace files were checked absent after teardown. Source
  scientific designs/trajectories and unrelated working-tree edits were untouched.
- `main.js`: +2 lines of import/initialization wiring. `api/client.js`: net −95 lines.
- No backend behavior changed; no simulations, deployment, or pushes. This
  checkpoint was subsequently committed as `978e5dda`.

## Prepared snapshot checkpoint

The verification results above describe the diagnostic checkpoint.
The subsequent implementation adds binary typed-array packages and a standalone
static viewer. Existing visible Full meshes, proteins and nanoparticles can be
packaged without duplicating scientific geometry computation. The prototype
preserves shared geometry/materials, instance transforms/colors/alpha and PNG
textures. Unknown shaders fail explicitly; shared assembly transforms and atomistic
impostors require adapters before parity can be claimed. Scientific selection,
recorded frames and rooms remain open. See `prepared_viewer.md` for limitations,
manual performance controls, and the distinction from completed phase acceptance.
The prepared snapshot implementation passes 6,685 frontend tests, 23 smoke tests,
and small/Voltron round-trip application checks. Its real-GPU A/B gate is still
open; retained evidence is in `audits/prepared_viewer_20260920/README.md`.

## Local sharing control checkpoint

Help → Share link reuses the prepared export factory. A loopback-only editor
middleware controls a separate temporary native Node host through a file-only
credential. WSL uses a local Windows subprocess for control transport; guest
traffic uses the Windows LAN interface. Guests receive independent immutable
part links with name entry and isolated session cookies; the guest viewer still
has no editor/Python dependency. Shared highlights, recorded trajectories and
HTTPS remote transport remain outside this static LAN checkpoint. See
`audits/share_link_menu_20260920/README.md` for actual clipboard/guest-flow checks,
Windows launch fixes, and the separate backend-test limitations.

## Internet and presenter checkpoints

The LAN checkpoint above is historical. The Help menu now starts temporary public
HTTPS sharing through Tailscale Funnel, with a generated password, isolated guest
and management listeners, and hidden native Windows hosting. See
`audits/internet_viewer_20260920/README.md`; committed and pushed as `302d50f6`.

Camera-only rooms add `meeting_presentation.js` on the guest/presenter side and
`prepared_room_state.mjs` on the host. A package-byte SHA-256 binds camera state to
the immutable exported view. Separate presenter credentials authorize coalesced
POST updates; ordered server-sent events synchronize willing guests. No scientific
geometry, editor-store subscriptions, assembly transforms or main.js wiring change.
The package still lacks stable scientific selection references; camera targets
cannot substitute for base/domain/cluster identity. That contract remains necessary for presenter selection highlights. Recorded-data
playback now uses exported render-buffer patches without claiming scientific selection identity.


## Job publication and streaming (2026-09-23)

`job_sharing.js` owns explicit oxDNA/NAMD job publication independently of editor
selection. `live_frame_capture.js` reads the existing scene buffers;
`prepared_live_frame.mjs` validates and retains one absolute compressed patch;
`meeting_live_frame.js` automatically fetches/applies it while preserving the
guest camera. Geometry/material layout changes reuse same-link scene replacement.
The WSL streaming controls use `prepared_share_bridge.mjs` over a persistent local
pipe. No public editor APIs or host credentials are exposed to guests.
See [current sharing workflow](prepared_viewer.md#job-sharing-through-one-invitation-2026-09-23).

`presentation_controls.js` owns the persistent editor-canvas Presenting indicator,
accessible glasses toggle, and End action. `share_link.js` coordinates camera authority
between embedded `editor_broadcast.js` (native camera only) and `job_sharing.js` (live
job visualization plus optional camera). No presenter-tab link is exposed in the
editor. The main initialization file needs no additional wiring for these controls.

`visualization_progress.js` reads existing visualization-card progress, relayed by
the job lease; `meeting_status.js` owns the guest loading and terminal screens.
Room closure publishes a final ended event before closing SSE connections.
`prepared_wide_lines.js` restores nanopore thick lines through bundled Three.js
LineMaterial/LineSegments2 constructors with validated data-only settings. It adds
no third-party dependency or arbitrary shader execution.
