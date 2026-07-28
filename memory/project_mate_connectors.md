---
name: Mate connector alignment — overhang blunt ends
description: Status and known issues for assembly mate connector placement at overhang blunt ends after overhang rotation transforms
type: project
originSessionId: 292b0b35-a6b9-4693-be07-bd8f4db21d5a
---
**Rank:** P3 — the four blunt-end defects are FIXED (2026-07-25, see below). What's left is one
latent root cause (`_sourceKey` blind to overhang rotation) and a missing route test.

**The computation now lives in its own module:**
[frontend/src/scene/blunt_end_connectors.js](../frontend/src/scene/blunt_end_connectors.js)
(`computeInstanceBluntEnds` + 4 exported pure helpers, 26 vitest tests in the sibling
`.test.js`). The duplicate ~270-line copy inside the legacy `initAssemblyRenderer` is GONE —
both renderer paths call the module, so a fix lands once. **Read the module's header comment
before touching overhang tip geometry: it states the `ovhg_axes` extent convention.**

**Status (audited 2026-07-25):** the atomic create-mate path and the shared-renderer path are
**shipped and wired** — `POST /api/assembly/joints/create-mate`
([routes_assembly_joints.py:326](../backend/api/routes_assembly_joints.py#L326), router registered
in `main.py`), frontend `createMate()` → `_alignAndAddJoint`
([assembly_joint_renderer.js:1608](../frontend/src/scene/assembly_joint_renderer.js#L1608), one
round-trip), `_defineAssemblyMate()` wired to the UI action
([main.js:5082](../frontend/src/main.js#L5082)). Ignore the old "work is on `kinematics-cleanup`
branch" note — it all landed.

## Atomic create-mate endpoint (2026-05-19)
Mate creation used to fire **4 sequential round-trips** from `_alignAndAddJoint` (`assembly_joint_renderer.js`): `addInstanceConnector` ×2 → `propagateFk` → `addAssemblyJoint`. Each replaced `currentAssembly` and ran the renderer's store subscriber; the two connector-register responses carried an unchanged transform and snapped the live preview back to the stored pose ("moved three times" jank).

Now ONE round-trip: `POST /assembly/joints/create-mate` (`createMate()` in client.js). `_alignAndAddJoint` still computes the align transform on the frontend (reads live world connector frames) and passes child/parent connector specs + the moved-instance transform + joint params. Backend (`create_mate` in `backend/api/assembly.py`) registers blunt-end connectors (idempotent), runs FK to the aligned pose, composes the joint, and applies ONE feature-log mutation → ONE store update / ONE undo step.

Refactor: extracted `_propagate_fk_inplace(assembly, instance_id, transform_values, inst_by_id)` (shared by `propagate_fk` endpoint) and `_compose_add_joint(assembly, body) -> (new_assembly, joint, label, params)` (shared by `add_joint` endpoint) so the math isn't duplicated. New `op_kind='assembly-create-mate'` added to the `SnapshotOpKind` Literal in `models.py` (forgetting this = 500 in `_apply_assembly_mutation_with_feature_log`). Also paired with the frontend subscriber fix: the transform-only branch in `main.js` now pushes only instances whose transform actually changed (`_sameInstanceTransform`), so even multi-update flows don't reset a preview. Verified via probe: 1 store update (was 4), joint added, no snap-back.

## Shared-renderer path (2026-05-19, path-to-thousands)
On the shared-instancing renderer (`window.NADOC_SHARED_RENDERER`), `getInstanceBluntEnds()` was previously a stub `() => []`, so clicking **Define Mate** showed no gold connector indicators. Fixed by extracting the legacy ~210-line computation into a module-level pure helper `_computeInstanceBluntEnds(design, helixAxes, mat4, instId, instName)` and adding shared-path `getInstanceBluntEnds` / `getConnectorClusterId` / `getConnectorClusterIds` that iterate `_sources` (per-instance world matrix read from `srcEntry.xformData[i*16..]`). Removed those three from `_SHARED_RENDERER_STUB_DEFAULTS`. `_defineAssemblyMate()` in `main.js` feeds blunt ends directly into `assemblyJointRenderer.setExtraConnectors(...)` regardless of the ambient `bluntEnds` tool-filter (that filter is normal-view display only). Data path note: `getAssemblyGeometry()` passes `helix_axes` as a raw array (client.js), so the `Array.isArray` branch in `_setSourcesFromAssembly` runs `_convertHelixAxesArray`, which camelCases `ovhg_axes`→`ovhgAxes` (the field `_computeInstanceBluntEnds` reads). Verified via Playwright probe: 1-hinge fixture → non-empty connectors + 351 hit-meshes after Define Mate click.

> **Correction (2026-07-25 audit):** "extracted" was only half true — the helper was used only by
> the shared path while the legacy `getInstanceBluntEnds` kept its own inline ~270-line copy.
> **Resolved the same day:** both now call
> [blunt_end_connectors.js](../frontend/src/scene/blunt_end_connectors.js). There is one copy.

## What was fixed (legacy path)
Three-part fix in `assembly_renderer.js` `getInstanceBluntEnds()`:

1. **Backend (`backend/api/assembly.py`):** Both `get_instance_geometry` and `get_assembly_geometry` now call `_apply_ovhg_rotations_to_axes(design, axes, nucleotides)` — previously the rotated ovhg axis data was never included in assembly geometry responses.

2. **`_axesArrayToMap` (`assembly_renderer.js` ~line 193):** Added `ovhgAxes: ax.ovhg_axes ?? null` — previously `ovhg_axes` was silently stripped when converting the array response to a map, so `buildHelixObjects` never received per-domain axis data for assembly instances.

3. **`getInstanceBluntEnds()` (`assembly_renderer.js` ~line 754):** Added `ovhgBpToPos` lookup built from `ax.ovhgAxes` entries. Used to:
   - Patch `localEps[h.id].start/end` for shared-inline stub helices whose endpoints coincide with an ovhgAx `bp_min`/`bp_max`.
   - Override `_posAlongHelix` in the interior strand termini section for overhang domain endpoints — uses the rotated ovhgAx position instead of interpolating along the unrotated stub axis.

For **extrude overhangs** `ax.start`/`ax.end` is updated directly by the backend; the new code is a no-op (extrude stubs have `ovhgAxes: null`).

## Fixed 2026-07-25 (all in `blunt_end_connectors.js`, 26 vitest pins)

Verified two ways: each pin was run against a scratch copy of the pre-fix code and **failed**
there (green-first-run proves nothing for adapted code); and old-vs-new connector sets were
diffed on six real designs with the true backend `ovhg_axes` payload.

1. **Spurious connector at every overhang stub root.** `_isFree` only rejected an endpoint
   coincident with another helix's endpoint; a stub attaches via a crossover at an *interior* bp
   one lattice cell away, so its root looked free. Now `_overhangJunctionBps()` collects the
   overhang-side foot of each overhang↔main junction from the strand walk and the free-endpoint
   loop skips it. Real effect: 9 phantom connectors gone on `Ultimate Polymer Hinge`.
   - **Topology trap found while fixing this** — a foot is not always *only* a foot.
     `2x2_OH_test` h_XY_2_0 carries two **antiparallel** overhangs both spanning bp 40–55: each
     staple 5'-ends where the other crosses off, so bp 40 and bp 55 are each simultaneously one
     staple's foot and the other's free tip. Suppressing on foot-ness alone deleted both real
     tips. `_strandTerminusBps()` now overrides: **a strand terminus is never merely a foot.**
2. **Connectors sat one full bp past the terminal base.** `ovhg_axes.end` is a duplex *extent* —
   the position of `bp_max + 1`, ~0.334 nm beyond the last base (deliberate: `domain_ends.js` and
   `helix_renderer.js` both divide by `bp_max - bp_min + 1` and depend on it). This file alone
   read it as bp_max's position. `_tipAtBpMax()` interpolates back to the base. **The backend was
   not changed** — three other renderer sites rely on the extent convention.
3. **Wrong normals on stubs patched by two domains.** When two overhang domains overwrote the two
   ends of one stub, `end - start` was the line between two independently-rotated domains (and the
   samples branch read the shared, un-rotated axis). Each patched endpoint now takes the direction
   of the domain that positioned it.
4. **Overlapping overhangs stole each other's position.** `ovhgBpToPos` was keyed `helixId:bp`, so
   with two overhangs at identical bp ranges the second silently overwrote the first and a
   connector landed on the wrong shaft. Now keyed by overhang id too, resolved at the lookup site
   from `domain.overhang_id`; the bare key survives as a first-wins fallback.
5. **Nick suppression ate real termini.** `_cov.has(bp-1) && _cov.has(bp+1)` ran off a helix-wide
   union of *all* domains, so the antiparallel scaffold beneath a staple made its free 5' end look
   mid-duplex. Coverage is now keyed `helixId:direction`, and an overhang free tip is exempt
   outright (contiguous overhangs on one stub flank each other). Real effect: +7 to +23 genuine
   staple termini recovered per design. **UX note:** Define Mate now shows noticeably more gold
   dots on staple-dense designs — they were always real, just hidden.
   coincident with another helix's endpoint; a stub attaches via a crossover at an *interior* bp
   one lattice cell away, so its root looked free. Now `_overhangJunctionBps()` collects the
   overhang-side foot of each overhang↔main junction from the strand walk and the free-endpoint
   loop skips it. Real effect: 9 phantom connectors gone on `Ultimate Polymer Hinge`.
   - **Topology trap found while fixing this** — a foot is not always *only* a foot.
     `2x2_OH_test` h_XY_2_0 carries two **antiparallel** overhangs both spanning bp 40–55: each
     staple 5'-ends where the other crosses off, so bp 40 and bp 55 are each simultaneously one
     staple's foot and the other's free tip. Suppressing on foot-ness alone deleted both real
     tips. `_strandTerminusBps()` now overrides: **a strand terminus is never merely a foot.**
2. **Connectors sat one full bp past the terminal base.** `ovhg_axes.end` is a duplex *extent* —
   the position of `bp_max + 1`, ~0.334 nm beyond the last base (deliberate: `domain_ends.js` and
   `helix_renderer.js` both divide by `bp_max - bp_min + 1` and depend on it). This file alone
   read it as bp_max's position. `_tipAtBpMax()` interpolates back to the base. **The backend was
   not changed** — three other renderer sites rely on the extent convention.
3. **Wrong normals on stubs patched by two domains.** When two overhang domains overwrote the two
   ends of one stub, `end - start` was the line between two independently-rotated domains (and the
   samples branch read the shared, un-rotated axis). Each patched endpoint now takes the direction
   of the domain that positioned it.
4. **Overlapping overhangs stole each other's position.** `ovhgBpToPos` was keyed `helixId:bp`, so
   with two overhangs at identical bp ranges the second silently overwrote the first and a
   connector landed on the wrong shaft. Now keyed by overhang id too, resolved at the lookup site
   from `domain.overhang_id`; the bare key survives as a first-wins fallback.
5. **Nick suppression ate real termini.** `_cov.has(bp-1) && _cov.has(bp+1)` ran off a helix-wide
   union of *all* domains, so the antiparallel scaffold beneath a staple made its free 5' end look
   mid-duplex. Coverage is now keyed `helixId:direction`, and an overhang free tip is exempt
   outright (contiguous overhangs on one stub flank each other). Real effect: +7 to +23 genuine
   staple termini recovered per design. **UX note:** Define Mate now shows noticeably more gold
   dots on staple-dense designs — they were always real, just hidden.

## Open items

Status below is what the code shows after the fixes above.

- ~~**Cache invalidation** — call site missing.~~ **MITIGATED.** `invalidateInstance(activeInstanceId)`
  *is* now called right after `patchOverhangRotationsBatch`, then `rebuild()`
  ([overhang_orientation_panel.js:126-137](../frontend/src/ui/overhang_orientation_panel.js#L133);
  same in `overhang_orientation_menu.js:85-88` for the reset-to-identity path), and both have vitest
  coverage. **Root cause NOT fixed:** `_sourceKey`
  ([assembly_renderer.js:1292](../frontend/src/scene/assembly_renderer.js#L1292)) and its shared
  mirror `_sharedSourceKey` (:2505) still key on `file:<path>:ct:<cluster_transform_overrides>` only
  — blind to overhang rotation. So the explicit call is the *only* thing keeping the cache honest;
  any **new** code path that mutates overhang rotations without calling `invalidateInstance` will
  silently serve stale `entry.helixAxes`. Fix = fold ovhg-rotation state into the key, or leave it
  and treat the manual call as the contract (document it at the `_sourceKey` def).

- ~~duplicate connectors on extrude stubs~~ · ~~normal direction on patched `localEps`~~ ·
  ~~nick suppression~~ · ~~bp_max off-by-one~~ — **all FIXED**, see the block above.

- **STILL OPEN — no route test for `POST /assembly/joints/create-mate`.** Only op-coverage
  assertions in `tests/test_headless_assembly_build.py` / `tests/test_automation_harness.py`. The
  *geometry* is now pinned (26 vitest tests) but the atomic endpoint is not.

## Why/How to apply
**Why:** Assembly mate connectors must align with transformed overhang tips so parts can be correctly mated in the assembly view after overhang orientation adjustments.
**How to apply:** Blunt-end geometry now lives in
[blunt_end_connectors.js](../frontend/src/scene/blunt_end_connectors.js) — edit it there, not in
`assembly_renderer.js`, and read its header comment first (the `ovhg_axes` extent convention is
load-bearing and shared with `domain_ends.js` / `helix_renderer.js`). Before changing suppression
rules, re-read the antiparallel-stub trap in the fixed-items block: a bp can be one strand's
crossover foot and another's free tip at the same time. `setExtraConnectors` /
`_syncBluntConnIndicators` (assembly_joint_renderer.js) are unchanged.
