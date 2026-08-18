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
- `44353007` — faithful overhang half-cylinders and extension markers.
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
| 1 | Exact static visual fidelity: overhangs, crossovers, forced ligations, extra bases, extensions, same-helix domain gaps, ends/markers/arcs | Primitive/topology parity tests plus headset visual check | Manual gate |
| 2 | Scene-projection contract and representative VR regression fixtures | Stable-ID scene snapshots, tolerance tests, failure diagnostics | Complete |
| 3 | Expanded Quick View on the right controller grip | Gesture is discoverable, reversible, tested, and comfortable | Manual gate |
| 4 | VR picking and selection intents from cluster through smallest supported element | Canonical selection matrix passes in desktop and VR | Active |
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
| Overhang/linker arcs | `overhang_link_arcs.js`; canonical linker topology/bridge geometry | ss/ds arcs now serialized; coarse ds bridge cylinder/duplex halves still absent | Connection id/type, anchors, ordered bridge primitives |
| Ends and flexible details | `domain_ends.js`, `flexible_arcs.js`, loop/skip and unligated markers | Flexible runs and visible unligated warnings now project; transient zero-opacity end rings await VR picking | Stable-owner visibility/count plus rendered check |

Implemented slices (pending headset check): Full and cylinder axes consume authoritative domain segments; Full projects explicit cross-helix crossover/forced-ligation chords; crossover inserts project from canonical residue frames into ordered beads, slabs, attachment corners, and backbone links with explicit base colors; extension modification tips use desktop size/chemistry color; scene v5 renders closed overhang half-cylinders while accepting v4 snapshots; and overhang connections now use the canonical complement anchors for desktop-matched ssDNA beads/slabs/backbone plus dsDNA boundary connector arcs in Full and Cylinders. Cylinder mode also reconstructs the deduplicated complement as the opposite half of its overhang and recovers one full ds bridge cylinder from mean endpoint base positions, mirroring desktop coarse geometry. Full now replaces filtered flexible-run beads with the desktop fixed-contour circular pose, obstacle-aware outward bow, 0.12 nm beads, synthetic slabs, and 32-segment centripetal Catmull-Rom backbone; it remains absent in Cylinders by design. The existing 5′ cube/3′ bead distinction is preserved, resting domain-end rings remain omitted because desktop opacity is zero until hover, and visible unligated crossovers receive an amber model-space warning sign at the authoritative midpoint. Targeted route/pure numeric tests, linker/flexible regression tests, and a native build/parser smoke check lock these behaviors.

Phase 2 foundation: scene v6 gives every point/cylinder/half-cylinder/box a URL-safe semantic identity scoped to its representation. The serializer and native reader both reject duplicates; v4/v5 remain readable. Identities derive from design owners (nucleotide/domain/connection/atom/bond) rather than draw order, so tolerance diffs compare moved geometry instead of reporting delete/add churn. `vr_scene_contract.py` now parses v6 and reports owner-readable missing/unexpected/type, position, orientation, dimension, and color differences with explicit tolerances; the native triangle fixture locks all four representations and duplicate rejection.

Phase 3 implementation: scene v7 pairs each natural primitive with an Expanded Quick View pose under the same identity. The backend mirrors desktop's 5.0/2.25 centroid expansion, translates helix-owned geometry and extension parents, recomputes link/flexible projections from shifted inputs, and interpolates crossover-insert atom offsets between source/destination helices. The native reader rejects pose identity mismatches, normalizes both poses in one coordinate frame, and holds the expanded pose only while the original Vive right squeeze/grip is pressed. Release restores natural spacing; press/release haptics and a cyan right pointer expose state. v4/v5/v6 remain readable, v7 has a parser fixture, and the numeric comparator now treats natural and expanded poses independently.

Phase 4 first slice: a pure native ray-intersection layer covers spheres, finite cylinders/capsules, and oriented boxes. With both triggers released, the right controller resolves the nearest primitive in the current representation/expanded pose, extends its cyan ray to the surface, and draws a small world-space hit marker. Hover identity is read-only and logged; it cannot bypass the desktop canonical selection controller. Native unit tests cover hits, misses, and geometry behind the controller. Half-cylinder hover currently uses its enclosing capsule, so exact half-volume discrimination remains regression debt before selection writes.

Phase 4 intent bridge: launch creates a private `0600` event record whose path is passed directly to the native child (never accepted from an HTTP request). Native hover changes overwrite one small sequenced JSON record; `/vr/event` is localhost/origin-gated and validates a 4 KiB size/type boundary. The browser polls this lightweight endpoint at 50 ms only while native VR is active, deduplicates sequence numbers, and clears hover on exit. Identity is retained in diagnostic button state and feeds renderer-only desktop preview—there is no store or canonical selection write. Tests cover partial/oversized records, event deduplication, and poll teardown.

Phase 4 desktop preview slice: `vrPrimitiveOwner` reconstructs live nucleotide/domain/crossover candidates and compares complete owner prefixes, so colons inside IDs never require ambiguous parsing. The selection manager projects resolved native hover into its existing yellow bead-set/arc preview according to the active cluster/strand/domain/end/xover/base level. This path is characterized as renderer-only: it contains no selection-controller dispatch or store write.

Phase 4 extended owners: atom primitive IDs now embed canonical base ownership instead of relying on their atom index alone; desktop resolves them back through live geometry and previews the complete residue atom set. Flexible bead/slab IDs resolve through canonical `segment_bead_keys`, and ss-linker bead/slab IDs resolve to existing `__lnk__` base keys, both reusing the live cross-renderer base-candidate pool. Atom bonds and non-base linker/flexible backbone segments remain intentionally unresolved pending bond/tool semantics.

Phase 4 Select slice: the original Vive right trackpad click is a dedicated boolean action, leaving trigger grab/two-trigger resize, right-grip Expanded Quick View, and application-menu controls intact. The bounded event record latches selection under an independent sequence so a hover update cannot erase a click before the 50 ms poll. Browser events split back into hover/select intents; select resolves the same stable owner and invokes the existing level-aware bead/arc/base handlers, which alone dispatch through the canonical selection controller. No direct store writer was added.

Phase 4 selection-level slice: the in-headset menu now has separate two-column Representation, Coloring, and Selection Level sections. Auto/Drill, Cluster, Strand, Domain, End, Crossover, and Base mirror the complete canonical desktop level model; launch seeds the native menu from the current desktop level, while menu changes travel as an independently sequenced intent and call the existing `setSelectionLevel` path so desktop buttons remain synchronized. Level selection never creates a second selection store.

Phase 4 acknowledgement slice: browser-confirmed Select results return over a separate server-created `0600` feedback record rather than being inferred by the companion. The browser reports accepted/selected state only after the existing canonical controller path runs; the native parser rejects malformed, stale, future, and invalid-level records. A larger green marker follows the accepted primitive through model transforms and Expanded View, while invalid target/level combinations and canonical deselection clear it. The marker intentionally disappears after switching to a representation that does not contain the exact primitive identity; cross-representation selected-owner projection remains explicit debt rather than fuzzy native ownership matching.

Phase 4 bond/backbone slice: ordinary Full backbone cylinders reconstruct their exact ordered endpoint owners and reuse the live canonical cone/bond adapter. Atomistic covalent bonds now carry both residue base keys: intra-residue bonds resolve to that Base, while inter-residue bonds select only when the live desktop renderer confirms a matching canonical backbone connector (in either serialized orientation). Flexible and ss-linker paths explicitly label every sampled edge with its nearest real/synthetic base index; they no longer leave curve tessellation ownerless or falsely treat 32 display segments as 32 chemical bonds. ds-linker connector arcs resolve to a read-only connection owner but remain non-selecting because canonical selection has no linker-connection ref. Atom spheres remain Base-owned pending the explicit individual-atom product decision.

Phase 4 owner-alias protocol slice: canonical selection acknowledgement now carries an ordered hierarchy of up to eight URL-safe, opaque `selectionRefKey` tokens—exact selected ref first, then applicable Base, Domain, and Strand fallbacks. Feedback v2 is private, bounded, atomically replaced, and strict about token count/length/whitespace; the native parser retains v1 compatibility and rejects stale, future, truncated, or extra-token records. Transport landed independently before consumption so scene ownership could remain an explicit versioned contract; the following slice completes that link.

Phase 4 cross-representation acknowledgement slice: scene v8 attaches explicit bounded `A` owner records to selectable natural/Expanded primitives; it never recovers ownership by parsing delimiter-sensitive primitive IDs. Base/End/Domain/Strand/Cluster, Bond, and Crossover/forced-ligation aliases come from authoritative topology, with cluster identity mirroring desktop's smallest-non-default selection rule rather than its separate color ranking. The native viewer retains v4-v7 readers, rejects unknown/duplicate/pose-mismatched aliases, and resolves feedback tokens by canonical specificity then stable scene order only when the exact clicked primitive is absent. Numeric tests cover IDs containing spaces/colons and Full → Ball-and-Stick → Cylinders fallback; native validators cover legacy v6, valid v8 natural/Expanded parity, and invalid owner references. Focused checks passed (30 Python, 4 native); `just test-smart` passed 7,072 tests with 114 skips. The slow gate remains deferred until the user opens `just test-session` and then runs `just test-slow`.

## Metrics research decisions

- Runtime cadence is authoritative: OpenXR `xrWaitFrame` supplies `predictedDisplayTime`, `predictedDisplayPeriod`, and `shouldRender`; advance one frame from that shared predicted time and skip heavy rendering when `shouldRender` is false. Do not hard-code 90 Hz even though the original Vive normally uses it. Source: [OpenXR frame synchronization](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#frame-synchronization).
- SteamVR's official performance assessment compares rolling average frame time over 32 frames with a runtime-derived target that already includes compositor headroom, and records repeated excursions rather than failing one isolated frame. Phase gates therefore record rolling timing plus burst/p95/p99 evidence and the in-headset assessment; they do not use 11.11 ms as the only pass line. Source: [SteamVR Performance Assessment Overlay](https://partner.steamgames.com/doc/steamhardware/steamframe/compat/perf_criteria).
- Comfort regression uses a short pre/post VR-specific symptom measure, with symptom-level stop criteria. The original SSQ remains a historical reference, but later validation found VRSQ/CSQ more psychometrically suitable for consumer HMD environments; scores are compared to this user's own baseline, not treated as a population diagnosis. Sources: [Kennedy et al. SSQ, DOI 10.1207/s15327108ijap0303_3](https://doi.org/10.1207/s15327108ijap0303_3), [Sevinc and Berkman 2020](https://doi.org/10.1016/j.apergo.2019.102958), [Josupeit 2023 environment-specific VRSQ analysis](https://doi.org/10.3389/frvir.2023.1291078).
- Interaction trials collect objective task completion, wrong-control activations, cancel/undo/re-grab counts, then the six NASA-TLX workload dimensions when a workflow is mature enough to compare. Source: [NASA Task Load Index](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/).
- Projection-space geometry copied from the same authoritative numeric records must agree within `1e-6 nm` and `1e-5°` after serialization, unless a primitive explicitly uses a documented approximation. Rendered-image and human comfort checks are separate gates and do not loosen topology parity.

## Current UX review and manual debt

- Representation switching still preserves one model transform; all new primitives therefore scale through the same two-hand world transform rather than changing apparent size with view/FOV.
- The v5 half-cylinder is closed and shadow-casting. Its axial roll follows the same deterministic but visually arbitrary default as the desktop straight-domain cylinder; no new biological orientation is inferred.
- Manual checkpoint: relaunch VR to obtain a fresh immutable snapshot, then verify (a) a same-helix empty interval stays empty in Full and Cylinders, (b) an unbound overhang reads as a half-cylinder while a direct-bound overhang reads full, (c) 1xT/2xT crossover inserts show ordered beads/slabs and no direct chord, (d) a Cy3 extension tip is a larger orange marker, (e) an unrelaxed ss linker has the same bowed path/base count in desktop Full and VR Full while Cylinders retains only its thin path, (f) each pre-relax ds linker shows two short boundary arcs that collapse after relaxation, while Cylinders reads as two two-tone bound-overhang shafts joined by one full bridge cylinder, (g) a slack flexible run bows away from the bundle with the same base count in desktop/VR Full, straightens when taut, and disappears—not breaks into rigid remnants—in Cylinders, and (h) a known cycle-closing crossover has a readable amber warning centered over it in Full only. Record mirrored/headset evidence before calling Phase 1 complete.
- Phase 3 headset checkpoint: launch a two-or-more-helix part, hold the right wand grip, and confirm helices move laterally apart while beads/slabs/atom radii remain constant; crossovers and linkers must stretch continuously rather than detach. Release must restore the exact natural pose. Repeat in all four representations, while holding a trigger, and at close-inspection scale. **Go** if grip never latches, model/world scale stays fixed, and there is no disorienting viewpoint jump; **no-go** on missing input, detached junctions, pose drift, or a grip/trigger conflict.
- Phase 4 hover checkpoint: with triggers released, point the right wand at a bead, slab, connector, cylinder, and atom. The cyan ray/marker should land on the visible surface, prefer the nearer primitive through overlaps, clear on empty space, and disappear during grab/resize. **No-go** on sticky markers, hits behind the wand, systematic slab misses, or frequent coarse-cylinder false positives.
- Desktop mirror checkpoint: while native VR is open and the normal desktop is visible in SteamVR Dashboard, VR hover over a nucleotide/domain/crossover should produce the same yellow desktop preview as mouse hover at the active selection level, and clear within one poll after leaving the model or exiting VR. **No-go** if canonical green selection changes, undo/history changes, Assembly selection is touched, or stale yellow preview remains.
- Selection checkpoint: at each cluster/strand/domain/end/xover/base level, aim at a valid target and click the right trackpad. Desktop and VR should show the same canonical green selection; invalid target/level pairs must be no-ops, repeated clicks must follow desktop toggle/drill semantics, and clicking must not move/scale the model. **No-go** on duplicate clicks, missed clicks during a steady hover, any trigger/grip conflict, or selection surviving an Assembly boundary incorrectly.
- Selection-menu checkpoint: launch while a non-default desktop level is active and confirm that row starts green in VR. Change through all seven in-headset rows and confirm the matching desktop filter state changes exactly once without selecting or moving geometry; representation/color choices must still work. **No-go** on cramped/overlapping text, ambiguous section labels, wrong desktop level, trigger-driven model motion while using the menu, or a level reverting after the panel closes.
- Selection-feedback checkpoint: click one valid target and confirm a larger green marker replaces ambiguity around the cyan hover cue after the desktop turns green; move/scale and hold Expanded View to confirm the marker follows. Switch through all four representations and confirm exact Base/Bond/Crossover ownership falls back deterministically to the matching Domain, Strand, or Cluster when the finer primitive is absent. Click again to deselect, then try an invalid target at End and Crossover levels. **No-go** if green appears before canonical acknowledgement, survives deselection, attaches outside the selected canonical owner, jumps between primitives on repeated representation switches, lags noticeably, or appears for an invalid pair.
- Bond/backbone checkpoint: in Full, select a thin ordinary backbone connector through default drill and confirm the same desktop bond/cone becomes green. In Ball + Stick and Stick, an inter-residue bond should reach that same connector, an intra-residue bond should select its Base only at a compatible level, and flexible/ss-linker curve edges should choose a nearby visible base rather than an arbitrary curve segment. ds-linker connector arcs must remain no-ops. **No-go** on cross-strand jumps, reversed/wrong connector selection, a green acknowledgement for display-only arcs, or materially biased nearest-base ownership along a curve.
- Next slice: complete the automated Phase 4 level × primitive × representation selection matrix, tighten half-cylinder hit discrimination, and prepare the consolidated manual headset gate before any transactional tool work. Phase 1 and Phase 3 remain pending their manual headset gates.

## Open questions log

- **Q-VR-001 — Right-grip semantics (implemented, validate):** hold-for-expanded/release-to-restore. Reopen only if headset testing finds grip fatigue or trigger conflict.
- **Q-VR-002 — Smallest selection identity:** atom spheres and intra-residue bonds currently resolve to canonical Base because the design selection model has no atom ref. Before atom-level editing/simulation inspection, decide whether individual atoms become canonical design selections or transient tool/result picks beneath Base; do not infer atom identity from an atomistic draw index.
- **Q-VR-003 — Edit safety:** what confirmation, preview, cancel, and undo affordances should VR tools share with desktop editing?
- **Q-VR-004 — Handedness/accessibility:** should menus and tools auto-mirror by dominant hand, expose an explicit setting, or both?
- **Q-VR-005 — Lighting:** should photo shadows remain scene-locked, offer a head-light fill, or expose a small lighting menu for inside-model inspection?
- **Q-VR-006 — Simulation defaults:** which job fields, plots, overlays, and playback controls deserve persistent wrist/panel placement versus on-demand menus?
- **Q-VR-007 — FJC transform authority:** desktop visibly stretches relaxed ssDNA representatives along the live chord, while the older Python `transform_to_chord` currently only rotates/translates despite its docstring. VR intentionally matches desktop locally; decide in a separate science-aware change whether the shared Python helper should be corrected and migrated.
- **Q-VR-008 — Warning-marker style:** the current physical triangular sign stays in model space and scales with the design; when billboard support exists, decide whether unligated warnings should instead remain head-facing like desktop sprites or keep the spatial sign for depth stability.
- **Q-VR-009 — Selection click:** favor right Vive trackpad click because trigger is already grab/resize, grip is Expanded Quick View, and menu opens the wrist/options panel. Validate reach/accidental presses before freezing the binding; future controller profiles may map a primary face button instead.

## Immediate handoff

Complete the Phase 4 selection matrix and half-cylinder picking fidelity, then present the consolidated headset gate. Preserve v4-v7 readers and v8 natural/Expanded owner parity. Phase 1 and Phase 3 stay at manual gates until their headset checklists pass.
