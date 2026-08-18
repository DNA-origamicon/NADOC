---
type: project
status: active
authority: canonical
review_after: 2026-09-01
---

# Native VR expansion

## Mission and current state

Make NADOC's native VR view a faithful, comfortable counterpart to the desktop application, then extend it into editing and simulation-result workflows without creating a second geometry, selection, or job model.

Active branch: `feature/native-vr-navigation` (tracked at `origin/feature/native-vr-navigation`).

Shipped baseline:

- `87ba1698` — native OpenXR viewer fallback.
- `dcc9eb4e` — molecular inspection controls and Steam dashboard access.
- `93da06b1` — self-shadowing and a more faithful Full representation.
- Current VR supports headset/controllers, grab and two-hand scale, recenter, in-VR representation/color menus, near inspection, and SteamVR desktop access.

## Binding invariants

1. Desktop geometry, topology, job data, and visualization state remain authoritative. VR is a projection and intent source, never a competing model.
2. VR selection emits normalized intents through the canonical selection controller; it does not become a second state writer. Assembly selection remains an explicit boundary.
3. DNA polarity and topology follow `REFERENCE_DNA_TOPOLOGY.md`. Ask before encoding an ambiguous handedness, strand order, loop/skip, crossover, or spatial relation.
4. Keep the composition root thin. Cohesive VR logic belongs in testable modules, not `main.js` or route handlers.
5. Never mutate a shared live server merely to verify behavior. Use pure/unit tests, isolated fixtures, or read-only inspection.
6. A visual change needs both a numeric/snapshot oracle and an actual rendered-image or headset check. A status label is not visual verification.
7. Each phase ends in a narrow, reversible checkpoint commit. Stage only phase-owned files in the shared worktree; never stash, reset, restore, or sweep up unrelated edits.
8. Preserve user scale and spatial context across representation changes. Display element sizes must be derived from model-space geometry and one world transform, never camera distance or FOV visibility.

## Phase-boundary loop

At every phase boundary:

1. Record shipped behavior, evidence, known debt, and unresolved questions here; move obsolete history to `project_native_vr_archive.md` only when this head approaches 200 lines.
2. Re-evaluate the complete headset workflow for discoverability, reach, visual legibility, comfort, error recovery, dominant-hand assumptions, and desktop escape hatches.
3. Research or refresh appropriate fidelity, interaction, comfort, and performance metrics from primary/official sources; revise thresholds when evidence warrants it.
4. Update later phases from what was learned, run proportionate automated checks, and record any manual headset validation still owed.
5. Make a clean checkpoint commit after review. Push checkpoints that are useful for remote recovery or user testing.

## Phase ledger

| Phase | Scope | Exit checkpoint | State |
|---|---|---|---|
| 0 | Durable plan, source inventory, validation metrics, fixture strategy | Memory lint; inventory and first acceptance matrix recorded | Complete |
| 1 | Exact static visual fidelity: overhangs, crossovers, forced ligations, extra bases, extensions, same-helix domain gaps, ends/markers/arcs | Primitive/topology parity tests plus headset visual check | Active |
| 2 | Scene-projection contract and representative VR regression fixtures | Stable-ID scene snapshots, tolerance tests, failure diagnostics | Queued |
| 3 | Expanded Quick View on the right controller grip | Gesture is discoverable, reversible, tested, and comfortable | Queued |
| 4 | VR picking and selection intents from cluster through smallest supported element | Canonical selection matrix passes in desktop and VR | Queued |
| 5 | In-headset tools: extrude, twist, bend, move/rotate; previews, confirm/cancel, undo | Each tool has safe transaction semantics and selection-level coverage | Queued |
| 6 | Unified job-list shell and simulation-result navigation in VR | Job identity/status/action parity with desktop | Queued |
| 7 | Every simulation engine's visualization options and time/result controls | Engine-by-option parity matrix and playback checks pass | Queued |
| 8 | UX polish, accessibility, comfort, performance, resilience | Sustained task tests and headset regression checklist pass | Queued |

## Provisional validation contract

Ratify thresholds during Phase 0 research; do not silently turn provisional numbers into science gates.

- Geometry fidelity: primitive count/type/visibility by stable design identity; topology-edge parity; position RMS and maximum error in nm; orientation angular error; dimension/scale error; negative-space checks for intentional gaps.
- Styling fidelity: representation/color parity and, where screenshots are deterministic, perceptual image difference. Lighting may differ stereoscopically but must not obscure topology.
- Interaction: selection hit/miss and false-positive rates; task completion time; accidental activation, re-grab, cancel, and undo counts; menu acquisition time; controller travel/reach.
- Comfort/performance: target the active headset refresh rate (original Vive normally 90 Hz); record application CPU/GPU frame-time p50/p95/p99, missed frames/reprojection, long-frame bursts, and scale/pose stability. The 90 Hz frame interval is 11.11 ms, but application budgets must leave compositor margin.
- Manual comfort: short symptom rating before/after demanding tasks, with explicit stop criteria for eyestrain, nausea, disorientation, or loss of balance. Never optimize comfort by merely blocking close inspection.
- Simulation UX: job/state mapping completeness; engine-option parity; frame/time identity; seek latency; playback stalls; overlay correctness; preserved user context when switching results.

## Phase 0 inventory targets

- Authoritative desktop primitives: helices/domains, gaps, beads/slabs, strand ends, crossovers and forced-ligation variants, extra-base geometry, overhang/extension/link arcs, proteins, and deformed geometry.
- VR projection path: backend scene records and native OpenXR rendering, including identity, visibility, representation, color, lighting, and transform ownership.
- Regression fixtures: compact designs that isolate one visual fact each plus one mixed design that exercises interactions between facts.
- Rendering evidence: deterministic desktop/VR scene snapshots first; repeatable headset captures or mirrored screenshots for user-visible acceptance.

## Phase 0 findings and acceptance map

| Visual fact | Desktop authority | VR baseline gap | First oracle |
|---|---|---|---|
| Same-helix domain gaps | `deformation.deformed_helix_axes[].segments`; `helix_renderer` per-segment shafts | VR consumed the whole `samples` shaft and filled gaps | Segment endpoint/count parity, including negative space |
| Crossover / forced ligation | `Design.crossovers` / `forced_ligations`; `getCrossHelixConnections`; `unfold_view` arcs | Cross-helix joins were omitted; only inferred same-helix backbone links existed | Explicit endpoint-pair parity; periodic-seam default visibility |
| Crossover extra bases | `atomistic_helpers.crossover_extra_base_placements` mirrored by `crossover_extra_placement.js`; `crossover_connections.js` | No VR bead/slab/connector projection | Stable crossover id + k; centre/frame/dimension tolerance |
| Extensions | `_strand_extension_geometry`; `helix_renderer` plus extension modification beads | DNA tail beads partly arrive, but slabs, modification tips, and explicit ownership are incomplete | Extension id + ordered bead/modification parity |
| Overhangs | Geometry `overhang_id`; `helix_renderer` half/full domain cylinders | Full beads arrive; cylinder view loses ss half-cylinder/duplex distinction | Domain identity, length, half/full primitive and colour parity |
| Overhang/linker arcs | `overhang_link_arcs.js`; canonical linker topology/bridge geometry | Not serialized | Connection id/type, anchors, ordered bridge primitives |
| Ends and flexible details | `domain_ends.js`, `flexible_arcs.js`, loop/skip and unligated markers | Missing or filtered from VR | Stable-owner visibility/count plus rendered check |

Implemented slices (pending headset check): Full and cylinder axes consume authoritative domain segments; Full projects explicit cross-helix crossover/forced-ligation chords; crossover inserts project from canonical residue frames into ordered beads, slabs, attachment corners, and backbone links with explicit base colors; extension modification tips use desktop size/chemistry color; and scene v5 renders closed overhang half-cylinders while accepting v4 snapshots. Targeted route and pure numeric tests plus a native build/parser smoke check lock these behaviors.

## Metrics research decisions

- Runtime cadence is authoritative: OpenXR `xrWaitFrame` supplies `predictedDisplayTime`, `predictedDisplayPeriod`, and `shouldRender`; advance one frame from that shared predicted time and skip heavy rendering when `shouldRender` is false. Do not hard-code 90 Hz even though the original Vive normally uses it. Source: [OpenXR frame synchronization](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#frame-synchronization).
- SteamVR's official performance assessment compares rolling average frame time over 32 frames with a runtime-derived target that already includes compositor headroom, and records repeated excursions rather than failing one isolated frame. Phase gates therefore record rolling timing plus burst/p95/p99 evidence and the in-headset assessment; they do not use 11.11 ms as the only pass line. Source: [SteamVR Performance Assessment Overlay](https://partner.steamgames.com/doc/steamhardware/steamframe/compat/perf_criteria).
- Comfort regression uses a short pre/post VR-specific symptom measure, with symptom-level stop criteria. The original SSQ remains a historical reference, but later validation found VRSQ/CSQ more psychometrically suitable for consumer HMD environments; scores are compared to this user's own baseline, not treated as a population diagnosis. Sources: [Kennedy et al. SSQ, DOI 10.1207/s15327108ijap0303_3](https://doi.org/10.1207/s15327108ijap0303_3), [Sevinc and Berkman 2020](https://doi.org/10.1016/j.apergo.2019.102958), [Josupeit 2023 environment-specific VRSQ analysis](https://doi.org/10.3389/frvir.2023.1291078).
- Interaction trials collect objective task completion, wrong-control activations, cancel/undo/re-grab counts, then the six NASA-TLX workload dimensions when a workflow is mature enough to compare. Source: [NASA Task Load Index](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/).
- Projection-space geometry copied from the same authoritative numeric records must agree within `1e-6 nm` and `1e-5°` after serialization, unless a primitive explicitly uses a documented approximation. Rendered-image and human comfort checks are separate gates and do not loosen topology parity.

## Current UX review and manual debt

- Representation switching still preserves one model transform; all new primitives therefore scale through the same two-hand world transform rather than changing apparent size with view/FOV.
- The v5 half-cylinder is closed and shadow-casting. Its axial roll follows the same deterministic but visually arbitrary default as the desktop straight-domain cylinder; no new biological orientation is inferred.
- Manual checkpoint: relaunch VR to obtain a fresh immutable snapshot, then verify (a) a same-helix empty interval stays empty in Full and Cylinders, (b) an unbound overhang reads as a half-cylinder while a direct-bound overhang reads full, (c) 1xT/2xT crossover inserts show ordered beads/slabs and no direct chord, and (d) a Cy3 extension tip is a larger orange marker. Record mirrored/headset evidence before calling Phase 1 complete.
- Next slices: linker/overhang arcs and duplex halves, flexible segments, terminal/end and unligated markers, then stable primitive identities for regression diagnostics.

## Open questions log

- **Q-VR-001 — Right-grip semantics:** hold-for-expanded, click-to-toggle, or contextual hold? Favor hold while it remains easy to discover and does not conflict with grab.
- **Q-VR-002 — Smallest selection identity:** should atomistic atoms become canonical design selections, or remain transient tool/result picks beneath the current `base` level?
- **Q-VR-003 — Edit safety:** what confirmation, preview, cancel, and undo affordances should VR tools share with desktop editing?
- **Q-VR-004 — Handedness/accessibility:** should menus and tools auto-mirror by dominant hand, expose an explicit setting, or both?
- **Q-VR-005 — Lighting:** should photo shadows remain scene-locked, offer a head-light fill, or expose a small lighting menu for inside-model inspection?
- **Q-VR-006 — Simulation defaults:** which job fields, plots, overlays, and playback controls deserve persistent wrist/panel placement versus on-demand menus?

## Immediate handoff

Finish Phase 0 by mapping every priority visual detail to its authoritative source and present VR gap, researching metric thresholds, and defining the smallest isolated fixtures. Then implement Phase 1 in narrow slices, with no topology guesswork and a checkpoint after each coherent group.
