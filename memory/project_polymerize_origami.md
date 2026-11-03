---
name: polymerize-origami
description: "Assembly → Polymerize Origami: grow a linear chain of identical mated parts from a single seed AssemblyJoint. Sidebar panel below #properties-section + POST /assembly/polymerize. Shipped 2026-05-15."
metadata: 
  node_type: memory
  type: project
  originSessionId: 82705120-6b9c-4081-a61d-9f0e8369685c
---

# Polymerize Origami (shipped 2026-05-15)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

One-click linear polymerization of identical mated parts. Click an orange joint ring in the viewport while the panel is open, set a chain length and direction, hit Polymerize — backend spawns N new `PartInstance`s + new `AssemblyJoint`s mirroring the seed mate in one atomic feature-log step.

(Joint indicators are the orange shaft + arrowhead + ring drawn by `_buildIndicator` in [frontend/src/scene/assembly_joint_renderer.js](../frontend/src/scene/assembly_joint_renderer.js) — `COLOUR = 0xff8c00`. The ring is also the rotation-drag handle for revolute joints. There is no separate "green ring" — the green color elsewhere (`CONN_PARENT_COL = 0x3fb950`) is for selected connector spheres during mate-define mode only.)

<a id="what-ships"></a>
- [What ships](details/project_polymerize_origami/01-what-ships.md#what-ships)

<a id="data-flow"></a>
- [Data flow](details/project_polymerize_origami/01-what-ships.md#data-flow)

<a id="backend"></a>
- [Backend](details/project_polymerize_origami/01-what-ships.md#backend)

<a id="frontend"></a>
- [Frontend](details/project_polymerize_origami/01-what-ships.md#frontend)

<a id="tests"></a>
- [Tests](details/project_polymerize_origami/01-what-ships.md#tests)

## Math worth remembering

The seed mate's `delta = T_B @ inv(T_A)` is a 4×4 row-major SE3 — both rotation and translation. `delta^i` compounds; for a rigid mate where A and B are colinearly offset on +Z, `delta` is just a pure translation along that axis, and the chain is straight along world +Z (validated by `test_polymerize_forward_extends_chain_to_total_count`).

For a revolute joint at non-zero `current_value`, the *current* relative transform differs from the joint's `base_transform`. v1 polymerizes from the live transforms (T_A, T_B as they sit now); new joints start at `current_value = 0` with `base_transform = new_inst.transform`. This means rotating the seed joint after polymerization doesn't propagate to the chain — each new joint is independent.

## Eligibility rule (mirrored in two places — keep them in sync)

`_sources_match` in [backend/core/assembly_polymer.py](../backend/core/assembly_polymer.py) is authoritative. The frontend's `_sourcesIdenticalish` in [frontend/src/ui/polymerize_panel.js](../frontend/src/ui/polymerize_panel.js) is a UI hint — it accepts any inline pair with the same `design.id`, plus file pairs with the same path. The backend's stricter structural-dump comparison is the source of truth at POST time; if the frontend says "eligible" but the dumps differ, the user sees a 422 with a clear error.

<a id="cylinders--full-upgrade-is-now-fast-shipped-2026-05-15"></a>
- [Cylinders → full upgrade is now fast (shipped 2026-05-15)](details/project_polymerize_origami/02-cylinders--full-upgrade-is-now-fast-shipped-2026-05-15.md#cylinders--full-upgrade-is-now-fast-shipped-2026-05-15)

### Deferred (bigger systemic options)

- **Async-yielding `buildHelixObjects`**: chunk the per-bp loops + `await Promise(setTimeout)` so Chrome's UI thread isn't frozen during heavy builds. Doesn't reduce CPU time but stops the page from feeling hung.
- **Shared `helixCtrl` across identical-source instances**: build one InstancedMesh tree per unique source and represent N clones via N transform matrices. Phase 3 deduplicated the geometry DATA across instances; this step would deduplicate the rendered MESHES. Substantial refactor — per-clone selection / colour overrides / cluster-joint articulation all need new plumbing.
- **Worker-thread geometry build**: move `buildHelixObjects` into a Web Worker that streams matrix/color buffers back to the main thread.

<a id="phases-2--3-of-the-rendering-memory-plan-shipped-2026-05-15"></a>
- [Phases 2 + 3 of the rendering-memory plan (shipped 2026-05-15)](details/project_polymerize_origami/03-phases-2--3-of-the-rendering-memory-plan-shipped-2026-05-15.md#phases-2--3-of-the-rendering-memory-plan-shipped-2026-05-15)

<a id="phase-1-of-the-rendering-memory-plan-shipped-2026-05-15"></a>
- [Phase 1 of the rendering-memory plan (shipped 2026-05-15)](details/project_polymerize_origami/03-phases-2--3-of-the-rendering-memory-plan-shipped-2026-05-15.md#phase-1-of-the-rendering-memory-plan-shipped-2026-05-15)

<a id="oom-on-polymerize-then-cant-reopen-fixed-2026-05-15"></a>
- [OOM-on-polymerize-then-can't-reopen (fixed 2026-05-15)](details/project_polymerize_origami/03-phases-2--3-of-the-rendering-memory-plan-shipped-2026-05-15.md#oom-on-polymerize-then-cant-reopen-fixed-2026-05-15)

### Systemic notes / deferred

- Lazy geometry loading by visibility / LOD would let the renderer keep `'full'` everywhere and only build heavy geometry for the parts in frustum. Out of scope for this fix.
- A real memory-budget tracker (backend tracks estimated MB per instance, refuses to upgrade past a cap) would be more honest than a count-based threshold but needs per-design size metadata cached.
- `_AUTO_DOWNGRADE_FULL_REP_THRESHOLD = 6` is a guess tuned for the Hinge Polys case; revisit if other users hit OOM at lower counts.

<a id="off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15"></a>
- [Off-by-one in pattern additional clone count (fixed 2026-05-15)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15)

<a id="pattern-polymerization--to-pattern-additional-instances-shipped-2026-05-15"></a>
- [Pattern polymerization — "To pattern" additional instances (shipped 2026-05-15)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#pattern-polymerization--to-pattern-additional-instances-shipped-2026-05-15)

<a id="seek-preserves-display-preferences-representation-visibility--fixed-2026-05-15"></a>
- [Seek preserves display preferences (representation, visibility) — fixed 2026-05-15](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#seek-preserves-display-preferences-representation-visibility--fixed-2026-05-15)

<a id="seek-now-preserves-feature_log-entries-fixed-2026-05-15"></a>
- [Seek now preserves feature_log entries (fixed 2026-05-15)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#seek-now-preserves-feature_log-entries-fixed-2026-05-15)

<a id="logged-op-kinds-expansion--duplicate-instance-shipped-2026-05-15"></a>
- [Logged op kinds expansion + duplicate-instance (shipped 2026-05-15)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#logged-op-kinds-expansion--duplicate-instance-shipped-2026-05-15)

<a id="feature-log-per-entry-actions-shipped-2026-05-15"></a>
- [Feature-log per-entry actions (shipped 2026-05-15)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#feature-log-per-entry-actions-shipped-2026-05-15)

<a id="connector-coverage-rule-fixed-2026-05-15-after-hinge-polysnass-repro"></a>
- [Connector-coverage rule (fixed 2026-05-15 after Hinge Polys.nass repro)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#connector-coverage-rule-fixed-2026-05-15-after-hinge-polysnass-repro)

<a id="mate_relative_transform-not-propagated--chains-resolved-position-but-not-orientation-fixed-2026-05-20"></a>
- [mate_relative_transform not propagated → chains resolved position but not orientation (fixed 2026-05-20)](details/project_polymerize_origami/04-off-by-one-in-pattern-additional-clone-count-fixed-2026-05-15.md#mate_relative_transform-not-propagated--chains-resolved-position-but-not-orientation-fixed-2026-05-20)

## Deferred

- Auto-rebuilding the chain when the seed mate is patched (today: chain stays at original placement; user re-runs polymerize after editing the mate if they want updated spacing).
- Replicate `AssemblyOverhangBinding` / `AssemblyOverhangConnection` along the chain (see [project_assembly_overhang_bindings](project_assembly_overhang_bindings.md) — cross-part bindings between (A,B) are NOT propagated to (B,C) / (C,D) by polymerize).
- 2D / 3D crystal patterns (two-axis polymerization). Today only linear chains.
- Joint-bound preservation across chain rotations — new joints inherit `min_limit`/`max_limit` but not the current driven angle. If the user wants a curved chain they need to set per-joint values manually.
- Selection-layer integration: clicking a chain instance in 3D doesn't auto-select the seed mate; selection still works as before.

<a id="polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26"></a>
- [Polymerize (Periodic) — no hand-defined mate (shipped 2026-05-26)](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26)

<a id="3d-rendering-of-the-seam-connector--view-toggle-2026-05-27"></a>
- [3D rendering of the seam connector + View toggle (2026-05-27)](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#3d-rendering-of-the-seam-connector--view-toggle-2026-05-27)

<a id="periodic-chains-re-dock-on-part-feature-changes--live-seam-connectors-2026-05-26"></a>
- [Periodic chains re-dock on part feature changes — LIVE seam connectors (2026-05-26)](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#periodic-chains-re-dock-on-part-feature-changes--live-seam-connectors-2026-05-26)

<a id="part-editor-save-path-now-auto-resolves--faster-cross-tab-sync-2026-05-27"></a>
- [Part-editor save path now auto-resolves + faster cross-tab sync (2026-05-27)](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#part-editor-save-path-now-auto-resolves--faster-cross-tab-sync-2026-05-27)

<a id="part-edit-sync-flood-40-rebuild--hullcylinder-overlay--fixed-2026-05-27"></a>
- [Part-edit sync FLOOD (40× rebuild) + hull/cylinder overlay — fixed 2026-05-27](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#part-edit-sync-flood-40-rebuild--hullcylinder-overlay--fixed-2026-05-27)

<a id="blank-scene--libraryfiles-flood-on-part-edit-refresh--fixed-2026-05-27"></a>
- [Blank scene + /library/files flood on part-edit refresh — fixed 2026-05-27](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#blank-scene--libraryfiles-flood-on-part-edit-refresh--fixed-2026-05-27)

<a id="related"></a>
- [Related](details/project_polymerize_origami/05-polymerize-periodic--no-hand-defined-mate-shipped-2026-05-26.md#related)
