---
name: bond-relax-framework
description: "Generic Relax Bond — single endpoint + frontend menu that closes any stretched backbone bond (crossover / forced ligation / linker arc / strand arc) via cluster transforms. 0-DOF rigid translate with user-picked side, 1-DOF joint rotate, N-DOF Powell. Shipped 2026-05-13."
metadata: 
  node_type: memory
  type: project
  originSessionId: 5c11bc26-cb88-4409-bb0d-db68fb3a646f
---

Subsumes the special-case linker relax + binding-pose math into a single optimiser. Reaches any stretched backbone bond:

- **Crossover record** — `design.crossovers[i]` by id.
- **Forced ligation record** — `design.forced_ligations[i]` by id.
- **Linker connector arc** — one side of an `OverhangConnection` (`bond_id` = conn id, `linker_side` = `a`/`b`).
- **Strand arc / direct-binding line** — anything addressable by two nucleotide endpoints (half-edge) `side_a` + `side_b`.

## Backend

**[backend/core/bond_relax.py](backend/core/bond_relax.py)** — generic optimiser. `relax_bond(design, *, anchor_a, anchor_b, cluster_a_id, cluster_b_id, target_nm, side_to_move, joint_ids, source_tag)` dispatches:

- **0-DOF** (`_relax_translate`): no joints between the two clusters → rigid translation of `side_to_move`'s cluster along the anchor-to-anchor chord by `chord_mag − target_nm`. Requires the user to pick the moving side.
- **1-DOF** (`_relax_one_joint`): exactly one joint connects the clusters → bounded brent search on θ via `_optimize_angle_chord_target` (mirrors `linker_relax._optimize_angle`, all-grid-minima + small-|θ| tiebreak). Rotates the joint's owning cluster.
- **N-DOF** (`_relax_n_joints`): Powell with scalar chord-magnitude loss + `_THETA_REG_LAMBDA · Σθ²` regulariser. Each joint rotates its own cluster.

All paths share `_commit_clusters`: replaces `design.cluster_transforms`, appends one `ClusterOpLogEntry(source=<source_tag>)` per moved cluster, resets `feature_log_cursor` to −1.

**[backend/api/crud.py:8703](backend/api/crud.py#L8703) `POST /design/relax-bond`** (`relax_bond_endpoint`) — single endpoint. Schema:

```python
class RelaxBondRequest(BaseModel):
    bond_type:    Literal["crossover", "ligation", "linker_arc", "strand_arc"]
    bond_id:      Optional[str] = None         # record-id path (crossover/ligation/linker_arc)
    linker_side:  Optional[Literal["a","b"]] = None   # required for linker_arc
    side_a:       Optional[RelaxBondEndpoint] = None  # half-edge path (strand_arc, fallback)
    side_b:       Optional[RelaxBondEndpoint] = None
    side_to_move: Optional[Literal["a","b"]] = None   # required in 0-DOF case
    joint_ids:    Optional[list[str]] = None
    target_nm:    Optional[float] = None        # overrides type-default
```

`_resolve_relax_bond_request` dispatches to the right anchor lookup per bond type and resolves `(anchor_a, anchor_b, cluster_a_id, cluster_b_id, target_nm, source_tag)`. Type-default chord targets:

| bond_type    | target_nm | rationale |
|---           |---        |---        |
| `crossover`  | 0.67 nm   | B-DNA backbone bond (matches `linker_relax._ARC_TARGET_NM`) |
| `ligation`   | 0.0 nm    | Ligated endpoints should coincide |
| `linker_arc` | 0.67 nm   | Bridge boundary → anchor gap |
| `strand_arc` | 0.67 nm   | Generic cross-helix backbone bond |

Source tag on the emitted `ClusterOpLogEntry` is `"bond-relax:<bond_type>"` so the feature-log panel can distinguish bond-relax events from manual moves and the legacy linker relax.

## Frontend

**[frontend/src/api/client.js:1281+](frontend/src/api/client.js#L1281)** — `relaxBond(bond, opts)` client method. Mirrors `relaxLinker` shape (cluster-only / positions-only fast paths).

**[frontend/src/scene/selection_manager.js:1225](frontend/src/scene/selection_manager.js#L1225) `_showCrossoverMenu`** — extended to include relax items below the extra-bases section:
- 0-DOF (no joints between clusters): two items `Relax bond — move <cluster_A>` / `— move <cluster_B>`.
- 1-DOF or N-DOF: a single `Relax bond (N DOF)` item — server-side auto-picks all joints between the clusters.
- Same-cluster bond: no relax items shown (backend would 422 anyway).

The crossover menu is reached for both `Crossover` records AND `ForcedLigation` records via the right-click arc hit path at line 2482-2489. Detection is by schema shape (`xo.half_a` for crossover; `xo.three_prime_helix_id` for ligation).

## What's NOT wired yet (future follow-up)

- **Linker connector arc right-click** — `_showColorMenu` has the existing `relax linker` action; not yet rewritten to use the generic `relaxBond`. Both flows work; the generic one is feature-complete but the existing linker-relax UI hasn't been replaced.
- **Direct-binding pre-bind line right-click** — when two complementary overhangs are unbound, the dashed line between their tips currently has no right-click handler.
- **Ball-joint auto-suggest in the relax submenu** — Phase 2 of this framework. See [[ball-joint]] for the scope doc. Goal: let the user one-click create a spherical joint anchored at the non-moving side's bead so a 0-DOF forced-scaffold-ligation case promotes to 3-DOF without picking an axis manually.

(Originally this list also included "Strand-arc right-click on stretched cross-helix arcs not tied to a Crossover record" — but in practice every cross-helix scaffold transition is already classified into either a `Crossover` or a `ForcedLigation` record by `extract_crossovers_from_strands`, so the existing `arcHit.crossover_id` path covers it. The original concern was actually the dual-cluster picker bug below — see "Dual-cluster picker fix".)

The backend supports all four bond types now; the frontend just needs more hit-test paths added incrementally.

## Arc right-click dispatch order (2026-05-13 fix)

The right-click handler in `selection_manager.js` had two ordering issues that hid the Relax bond menu when the user right-clicked the OH→parent crossover:

1. **OH-domain-mode intercept** (line ~2451) routed ALL right-clicks to `_showOverhangOrientMenu` whenever the user had an OH domain selected — including right-clicks on the OH→parent crossover arc. Fix: pre-compute `arcHit` and yield to the arc dispatch when the cursor is over an arc with a `crossover_id`.
2. **Selected-strand color-menu wins over crossover-id check** (line ~2525) — when the user had the OH-bearing strand selected and right-clicked the arc, the color menu fired before the crossover-id check, so Relax never appeared. Fix: re-order so the `arcHit.crossover_id` check fires FIRST. The strand color menu is still reachable by right-clicking the strand body / cone.

Net effect: right-clicking the visible crossover arc ALWAYS opens the crossover menu (now with the Relax bond submenu), regardless of selection state. The semantic is "you're acting on the bond itself, so the bond-context menu wins."

## Tests

**[tests/test_relax_bond.py](tests/test_relax_bond.py)** — 7 tests:
- `test_relax_bond_crossover_0_dof_translates_chosen_side` — 0-DOF rigid translate with `side_to_move=b`.
- `test_relax_bond_0_dof_requires_side_to_move` — 422 without side_to_move.
- `test_relax_bond_1_dof_rotates_joint_cluster` — single joint → joint optimisation.
- `test_relax_bond_ligation_record_path` — forced ligation lookup + target=0.
- `test_relax_bond_half_edge_addressing` — `strand_arc` path via `side_a` + `side_b` endpoints.
- `test_relax_bond_same_cluster_refused` — 422 when both endpoints share a cluster.
- `test_relax_bond_target_nm_override` — request body's `target_nm` overrides type-default.

Full backend: 1235 pass (the 7 new tests + everything else); 7 pre-existing failures + 9 pre-existing errors unrelated.

## Gotchas

1. **Bond addressing — record id vs half-edge** — record-backed types (crossover, ligation, linker_arc) prefer `bond_id` resolution since the endpoint lookup is cheap. `strand_arc` MUST use half-edge `side_a`/`side_b`. The endpoint accepts both paths simultaneously and prefers the record path when both are supplied.
2. **`side_to_move` is only consulted in the 0-DOF case** — for 1-DOF and N-DOF the joint axes determine which cluster moves. Passing `side_to_move` alongside joints is silently ignored; this matches user expectation (joint topology wins).
3. **target_nm semantics** — the optimiser targets a chord MAGNITUDE, not a direction. The translated cluster slides along the current anchor-to-anchor chord. For 0-DOF, the result is geometrically valid only if the chord direction is what the user wants; if they want a different placement they can rotate the cluster manually afterward.
4. **Crossover halves' `strand` direction is the half's strand direction (FORWARD/REVERSE)** — when resolving anchors via half-edge lookup we use that as the `direction` field. Matches the geometry response shape.
5. **The legacy `POST /design/overhang-connections/{id}/relax` endpoint is unchanged** — both old and new endpoints coexist. To fully subsume linker relax, port the frontend `relaxLinker` callers to use `relaxBond` with `bond_type="linker_arc"`. Backend will tolerate either.

## Files

**Backend (new + modified)**
- `backend/core/bond_relax.py` — NEW.
- `backend/api/crud.py` — added `RelaxBondRequest`, `RelaxBondEndpoint`, `_resolve_relax_bond_request`, `_resolve_linker_arc_endpoints`, `_cluster_id_for_helix`, `relax_bond_endpoint`, `_BOND_TYPE_DEFAULT_TARGET_NM`. Also `import numpy as np`.

**Frontend (modified)**
- `frontend/src/api/client.js` — `relaxBond(bond, opts)` export.
- `frontend/src/scene/selection_manager.js` — extended `_showCrossoverMenu` with relax items.

**Tests (new)**
- `tests/test_relax_bond.py`.

## Undo-after-relax "double rotation" bug — FIXED 2026-05-14

User reported: after `relax-bond` rotated a cluster by θ ≈ 55° around a joint axis, Ctrl-Z did NOT return the cluster to its PRE position. Instead the cluster rotated by ~2θ in the undo direction, landing roughly θ past PRE.

**Root cause:** the cluster_only / positions_only delta was being applied **twice** per undo/redo. Once via the `_responseDeltaHandler` that `_syncClusterOnlyDiff` invokes inside `api.undo()` / `api.redo()`, and a second time in each of the five undo/redo handlers in main.js (menu-edit-undo, menu-edit-redo, Ctrl+Z shortcut, Ctrl+Y redo, Ctrl+Shift+Z redo). Someone migrated the delta-apply into the centralized client.js layer at some point and forgot to remove the explicit calls in main.js.

The relax wasn't affected because relaxBond goes through `_syncClusterOnlyDiff` once → handler applies once. The user clicks an arbitrary button. No double-call site.

**Fix:** removed the duplicated `_applyClusterUndoRedoDeltas` / `_applyPositionsOnlyDiff` blocks from all five undo/redo handlers in main.js. Added a one-line comment at each site noting the delta is applied inside `api.undo()` / `api.redo()` via the registered handler.

**Files**
- `frontend/src/main.js` — removed 5 duplicate delta-apply call sites at the menu-edit-undo / menu-edit-redo handlers and the Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z shortcut handlers. Net: −18 lines.

**Tests / verification**
- `scripts/probe_undo_after_relax.py` (committed) confirms backend correctly restores cluster_transforms on undo.
- `frontend/e2e/relax_undo_bug.spec.js` (committed) — Playwright test that loads hinge, binds, relaxes, undoes, and asserts max bead drift PRE→UNDO < 0.01 nm. Run when a responsive backend is available.

## Dual-cluster picker fix — 2026-05-14

User reported: right-clicking the `f07a513b` forced-scaffold ligation arc (h_XY_3_3 bp 136 ↔ h_XY_5_2 bp 90) in `Ultimate Polymer Hinge 191016.nadoc` opened the crossover menu with only "Add extra bases…" — the Relax bond submenu items never appeared.

**Root cause:** `_autodetect_clusters` produces overlapping cluster sets — one "Scaffold Cluster N" wrapping a whole scaffold AND several "Geometry Cluster N" entries that cover its rigid sub-bodies (see [[cluster-autodetect]]). For the hinge, both helices are in *Scaffold Cluster 1* (the first entry in `cluster_transforms`) AND in distinct geometry clusters (GC1, GC3).

`_cluster_id_for_helix` did a naive first-match lookup, returning the scaffold cluster for both halves of every forced scaffold ligation. The same-cluster guard (`clusterA.id !== clusterB.id`) silently dropped the Relax items, both in `_showCrossoverMenu` (frontend) and via 422 from `_resolve_relax_bond_request` (backend) if the menu had reached the call anyway.

**Fix:** new helper `_cluster_pair_for_bond_relax(design, helix_a, helix_b)` in [crud.py:8804+](backend/api/crud.py#L8804) enumerates the full cluster membership of both helices and returns the first `(a, b)` pair with differing ids. Falls back to first-match if no differing pair exists (so genuinely intra-cluster bonds still hit the 422). Frontend `_showCrossoverMenu` mirrors the same enumeration inline ([selection_manager.js:1250+](frontend/src/scene/selection_manager.js#L1250)).

For the hinge case, both halves now resolve to the geometry clusters (GC1 for h_XY_3_3, GC3 for h_XY_5_2) and the 0-DOF rigid-translate items appear. `cluster_joints` is still empty, so this is 0-DOF only — promotion to 1-DOF / 3-DOF requires adding a joint (see [[ball-joint]] for the planned auto-suggest UX).

**Files**
- `backend/api/crud.py` — added `_cluster_pair_for_bond_relax`, swapped two `_cluster_id_for_helix` calls in `_resolve_relax_bond_request`. The standalone `_cluster_id_for_helix` is kept for the debug scripts under `scripts/probe_*.py`.
- `frontend/src/scene/selection_manager.js` — replaced two `.find()` calls in the Relax bond block with an enumerate-pairs loop.

**Tests**
- `tests/test_relax_bond.py::test_relax_bond_overlapping_scaffold_cluster_picks_geometry_pair` — overlapping scaffold + geometry clusters; first-match would return same-cluster, pair-picker resolves the geometry pair. `just test-file tests/test_relax_bond.py`: 8/8 pass.
- Full suite: 1239 passed, 57 skipped, 7 failed + 9 errors all pre-existing (animation geometry batch, routers, atomistic round-trip).
