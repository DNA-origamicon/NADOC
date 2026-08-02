---
name: deformation-cluster-scope
description: LIVE REFERENCE — bend/twist deformations carry a cluster_ids list scoping them to a subset of clusters. Shipped 2026-05-14, in production. Scope is FROZEN into affected_helix_ids at create time; the geometry never reads cluster_ids.
metadata: 
  node_type: memory
  type: project
  originSessionId: a3036cf2-209c-483d-9711-c9abdac2f237
---

# Bend/twist cluster scoping — LIVE REFERENCE

> **Status (audited 2026-07-30, `/audit-plan`): SHIPPED and in production.** Every anchor probed;
> the feature is live end-to-end (model → 4 routes → picker UI). This is **not** an unfinished
> plan — it is the reference for how scoping actually works. **No rank.**
>
> The 2026-05-14…05-27 work log (five backend geometry fixes + the edit-flow history) moved to
> **[project_deformation_cluster_scope_archive.md](project_deformation_cluster_scope_archive.md)**
> — its root-cause explanations are still correct; all its line anchors are dead. Don't read it in
> a routine loop.
>
> Architecture map: [.claude/rules/deformation.md](../.claude/rules/deformation.md) (auto-loads).
> Symptom→diagnosis: `.claude/runbooks/RUNBOOK_DEFORMATION.md` §7.

## The one thing to know

**There are two independent scoping mechanisms, and the geometry math reads neither `cluster_ids`
nor the cluster picker.**

1. **Create/edit time — `resolve_cluster_scope`** intersects the crossing helices with the union
   of the named clusters' `helix_ids` and **freezes the result into `op.affected_helix_ids`**.
   Unknown cluster ids are dropped silently — a stale id narrows the scope, possibly to nothing.
2. **Render time — `_arm_filter_cluster`** picks, per helix, *the first non-default cluster that
   contains that helix*. It never looks at `op.cluster_ids`.

Consequences, all real:

- `affected_helix_ids` is the **actual** enforcement. `cluster_ids` is metadata (used by
  create/edit, copy/paste, dependency cascade, and the debug echo). **If the two drift, geometry
  silently follows `affected_helix_ids`.** A saved op keeps its stored list on load — it is never
  recomputed, so an op saved before a scope-affecting fix stays wrong until re-applied.
- A helix in **two** non-default clusters gets `non_default[0]` — arbitrary list order. This is the
  mechanical root of the known "two clusters sharing a helix conflict" limitation (below).
  **Note (2026-08-01):** overlapping clusters are common enough in real designs
  (`workspace/VoltronCoreScad.nadoc` has a scaffold cluster and a geometry cluster each claiming
  all 59 helices) that the new per-cluster **display** fields had to pick explicit rules rather
  than inherit an arbitrary one — colour resolves *explicit beats unstyled, then last-listed*;
  opacity takes the **minimum** across every cluster covering a nucleotide, matching the sidebar
  visibility toggle, which already unions. Those rules are display-only and change nothing here;
  the geometry conflict below is untouched.
- **PATCH cannot change scope** (`UpdateDeformationBody` is `params` only). Changing the picker
  mid-session deletes and re-creates the preview op.

## Code locations (probed 2026-07-30)

| Thing | Where |
|---|---|
| `DeformationOp.cluster_ids: List[str]` | `backend/core/models.py:1129` (class `:1120`). Empty = unscoped |
| `ClusterRigidTransform.color` / `.opacity` (display-only, 2026-08-01) | `backend/core/models.py` — `color: Optional[str]` "#rrggbb", None = auto palette; `opacity: float = 1.0`. PATCH whitelist in `routes_clusters.py::PatchClusterBody` (`color: ""` clears). Consumed by `frontend/src/scene/helix_renderer/palette.js::buildClusterColorLookup` and `scene/cluster_entries.js::clusterAlphaKeys` → `helix_renderer.setClusterAlphas`. Rides `model_copy` through `cluster_copy.py`, so paste keeps them. Tests: `tests/test_cluster_style.py` |
| `resolve_cluster_scope(design, cluster_ids, helix_ids) -> dict` | `backend/core/deformation.py:2683` |
| — called from | `routes_deformation.py:111` (POST) · `core/feature_log_edit.py:162` (edit) · **`routes_loop_skip.py:269`** |
| `helices_crossing_planes` (overlap test, not full-span) | `deformation.py:2646`; callers `feature_log_edit.py:159`, `routes_deformation.py:105`, `routes_loop_skip.py:266` |
| `_ops_affecting_helix` (per-helix short-circuit) | `deformation.py:585`; 5 callers `:1453,:1568,:1663,:1755,:2416` |
| `_arm_filter_cluster` (prefers first non-default) | `deformation.py:603`; 5 callers `:1464,:1578,:1685,:1751,:2443` |
| `_frame_at_bp` (arm anchor = `min(h.bp_start ...)`) | `deformation.py:460`, anchor at `:487` |
| `_precompute_arm_frames(… arm_min_bp …)` | `deformation.py:1363`; `arm_min_bp` computed `:2467`, passed `:1491`,`:1704` |
| `_bundle_centroid_and_tangent` (projects to `arm_min_bp_start`) | `deformation.py:189`, 8 call sites. **Name collision** with an unrelated one at `loop_skip_calculator.py:148` |
| `deformed_helix_axes` / `deformed_nucleotide_positions` | `deformation.py:2332` / same module |
| Routes (all mount `/api`) | `routes_deformation.py` — POST `:90`, PATCH `:148`, DELETE `:177`, GET debug `:203` |
| `AddDeformationBody.cluster_ids` | `routes_deformation.py:46`, field `:53`. `UpdateDeformationBody` `:58` = **params only** |
| Feature-log edit (rebuild from LOG) | **`backend/core/feature_log_edit.py:109` `edit_deformation_entry`** — `op_snapshot` `:147/:167/:178`, 409 `:147-151`, `rebuilt_ops` `:182`, `copy_with(...)` `:187`. `crud.py:9876` is a 10-line shell |
| Other `op.cluster_ids` readers | `cluster_copy.py:293-318`/`:503` (scope + id remap on paste) · `feature_dependencies.py:217` (cascade; returns `None` if a cluster id is missing) · `headless_build.py:501/529` (`cluster_ids=()`) |
| `addDeformation(type, planeA, planeB, params, helixIds, preview, clusterIds = [])` | `frontend/src/api/client.js:1324`; `updateDeformation` `:1366` |
| Session scope | `deformation_editor.js` — `_sessionClusterIds` `:560`, `setDeformSessionClusterIds` `:567` (async, delete+recreate), `_defaultClusterIds` `:550` (exported as `getDeformDefaultClusterIds` `:585`), `_effectiveClusterIds` `:576` (also scopes plane picking, `:595`) |
| Picker | `ui/bend_twist_popup.js` — All `:100` / None `:104`, gate `:383-387`, default via `:192` |
| Picker markup | `frontend/index.html:6774-6786` — `#def-cluster-section`, `-all-btn`, `-none-btn`, `-list`, `-empty-msg` |
| Plane picking (nearest helix, longest-helix default) | `deformation_editor.js:710` `_pickBpFromPoint`, `:469` `_defaultBpForPlaneB` |
| Tests | `tests/test_deformation_clusters.py` (**10**) · `tests/test_deformation_params_core.py` (**9**, core-level `resolve_cluster_scope`) · `test_geometry.py:455/:471` · `test_feature_log_snapshot.py:689` |
| Fixtures the history rests on | `tests/fixtures/teeth.nadoc`, `workspace/Ultimate Polymer Hinge 191016.nadoc` (the hinge's bp_starts are cited in live code, `deformation.py:2464-2466`) |

## Corrections to what this file used to say

- **"Old `.nadoc` files with singular `cluster_id` fail to load — hard break" is FALSE.**
  `models.py` declares no `model_config`, so pydantic v2's default `extra='ignore'` applies: the
  legacy field is **silently dropped** and the file loads. The op survives as *unscoped* with its
  persisted `affected_helix_ids` intact. The real risk is quiet scope-metadata loss, not a load
  failure. (`RUNBOOK_DEFORMATION.md:146` inherited the wrong claim — corrected 07-30.)
- **`_resolve_cluster_scope` in `crud.py` is gone** — it is `resolve_cluster_scope` in
  `deformation.py`, and it has **four** callers, not one (see table).
- **The edit-in-place PATCH flow described in the archive was replaced.** `_onEditFeature`
  (`main.js:1441`) now **peels** the op off with a transient `deleteDeformation(op.id, preview=true)`
  (`:1513`), records `origOpId` (`:1505`), and re-enters through the *new-op preview* path with
  `startDeformToolForEdit(..., opId=null, op.params)` (`:1523`) so the popup can show a
  before/after solid-vs-ghost. `skipInitialPreview` is now hardcoded `false` (`:1427`). It still
  does **not** seek (✔ as documented) and still calls `_watchDeformState()` itself (`:1530`).
- **Test coverage doubled** — 10 cases in `test_deformation_clusters.py` (this file said five),
  plus the 9-test `test_deformation_params_core.py` that didn't exist when this was written.
- **Loop-skip is an undocumented second consumer** of `helices_crossing_planes` +
  `resolve_cluster_scope` (`routes_loop_skip.py:266-269`). Any change to the resolver's contract
  has a blast radius this file never described.

## Known limitations (unchanged, still true)

- **Two clusters sharing a helix still conflict.** Disjoint `helix_ids` works; a shared helix has
  one axis-frame stack, so a bend deforms it for both. Phase 2 (per-cluster sub-axis isolation) is
  **not implemented and not started** — verified: `deformation.py:2470-2473` samples exactly one
  `_frame_at_bp` stack per helix. The `seg_geoms` subdivision at `:2477-2482` is cluster **rigid
  transform** subdivision applied to points already sampled off the single shared curve, which is a
  different thing. If Phase 2 is ever taken on, the hard parts are `deformed_nucleotide_positions`
  and `deformed_helix_axes`.
- Un-affected helices are kept still by *side-stepping* an identity-preservation weakness in the
  frame math (the `_ops_affecting_helix` short-circuit), not by fixing it — see the archive.

## Open defects on the shipped code

1. **The in-place-PATCH edit branch is orphaned.** `_editOpId`/`_editOrigParams`/`_editDirty`/
   `_editCommitted` (`deformation_editor.js:60-63`), set only in `startToolForEdit:163-166`, and
   the revert-on-exit guard `:510-516` are fully written but **unreachable** — the only UI caller
   now passes `opId=null` (`main.js:1523`). `markEditCommitted` (`:117`) is still called
   (`main.js:1383`) but only feeds the unreachable guard. Decide: delete the branch, or restore a
   caller. Do not "simplify" it away without checking headless/script callers first.
2. **`_arm_filter_cluster` picks arbitrarily when a helix is in ≥2 non-default clusters** —
   `non_default[0]` is list order, not the op's scope. Making it consult `op.cluster_ids` is the
   obvious narrowing, and is a prerequisite for any Phase 2 work.

## How to apply

- **Always set `cluster_ids` explicitly** when scoping a bend/twist, even with a single cluster —
  the "use the only cluster" fallback fires only when no scope is supplied.
- Changing scope mid-edit requires **delete + recreate**, never PATCH.
- New tests: follow `tests/test_deformation_clusters.py` (bundle design, two disjoint clusters,
  assert both `op.cluster_ids` **and** `op.affected_helix_ids` after POST — asserting only the
  former proves nothing, per the two-mechanism split above).

Related: [[cluster-copy-paste]] (id remap on paste) · [[cluster-joints]] · [[cluster-reconcile]]
