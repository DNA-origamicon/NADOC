# Viewer extraction inventory

Checkpoint: Phase 0 diagnostics plus the first Phase 1 wire-decoder extraction.
This is an implementation checklist, not a claim that standalone viewing exists.

| Component | Current dependency | Standalone boundary / acceptance |
| --- | --- | --- |
| Scene/navigation | `scene/scene.js`: canvas, controls, animation loop, resize | Reuse controls; add complete lifecycle disposal before independently mounting/unmounting viewers. |
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

## Current checkpoint verification

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
- No backend behavior changed; no simulations, deployment, commits, or pushes.
