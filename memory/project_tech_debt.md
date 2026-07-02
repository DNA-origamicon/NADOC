---
name: tech-debt-ledger
description: Running technical-debt ledger — code paths flagged for review/removal (with why + supersession). Check when touching a flagged area.
metadata: 
  node_type: memory
  type: project
  originSessionId: a42a916c-90da-4711-b831-59182e249f46
---

Running ledger of known technical debt — code that works today but is flagged for
review or removal. Each entry: location, why it's debt, what supersedes it. Append
new items; strike through (and date) when resolved.

## Open

### DELETE-ON-COMPLETION: legacy OverhangSpec pose overlay + standalone orientation panel (superseded by the duplex CLUSTER)
- **Where / delete when [[overhang-duplex-cluster]] ships end-to-end:**
  - `OverhangSpec.rotation` / `OverhangSpec.translation` (backend/core/models.py) — the
    world-frame per-overhang pose. Superseded by the child `ClusterRigidTransform`
    (`overhang_duplex_driver_id`) whose pose is stored in the driver part's rest frame
    (drift-free). Keep the FIELDS until all `.nadoc` are migrated-on-load; delete the
    OVERLAY application.
  - `apply_overhang_rotation_if_needed` Layer-1 whole-overhang rotation/translation +
    `_apply_ovhg_rotations_to_axes` (backend/core/deformation.py) — the overlay + its axis
    follow. Replaced by the cluster (bead + child-aware axis) path. (Layer-2 sub-domain
    chain rotation may outlive this — reassess.)
  - `patch_overhang_rotations_batch` / `OverhangRotationLogEntry` (crud.py, models.py) —
    the overlay's edit API + feature-log entry. **DO NOT DELETE OUTRIGHT** (scope-corrected
    2026-07-01): `OverhangRotationLogEntry` is DUAL-PURPOSE — whole-overhang rotation (→ cluster
    `ClusterOpLogEntry`) AND per-sub-domain θ/φ (NO cluster equivalent). Keep the type + the
    per-sub-domain path; only whole-overhang-duplex slots migrate. Migrate-on-load still REMAINING
    (see [[overhang-duplex-cluster]] P4).
  - `frontend/src/ui/overhang_orientation_panel.js` + `overhang_orientation_menu.js`
    "Edit/Reset Orientation" — **NOT deleted outright** (scope-corrected 2026-07-01). The panel
    also orients STANDALONE/unconnected overhangs (no cluster exists → gizmo can't cover). Retired
    ONLY for duplex-backed overhangs: the menu now routes those to the cluster gizmo ("Move / Rotate
    duplex" + cluster-identity Reset); standalone overhangs keep the panel. The panel + menu STAY.
  - `direct_relax.relax_direct_binding` currently writes the pose onto `OverhangSpec`
    (re-seat + clash). Migrate to write the child cluster (Phase 1b), then this note's
    OverhangSpec writes go away.
- **Why it's debt:** dual representation (overlay AND cluster) risks double-transform; the
  overlay's world-frame storage drifts when the driver part is rotated after the pose is
  set — the whole reason for the child-cluster rebuild.
- **Guard already in place:** `validate_design` flags a duplex cluster whose driver still
  carries a non-identity OverhangSpec pose (double-transform). `materialize_duplex_cluster`
  clears the pose; `dematerialize` restores it. Do NOT delete until Apply/relax/axis are on
  the cluster AND a migration-on-load converts existing `.nadoc`.

### Stale workspace-fixture test skips instead of running (TODO: re-pin or rebuild fixture)
- **Where:** [tests/test_feature_log_snapshot.py](tests/test_feature_log_snapshot.py)
  `test_delete_workspace_independent_strutted_corner_extrude_scrubs_survivors`.
- **Why it's debt:** the test loads `workspace/2x2_strutted_corner.nadoc`, which is
  **gitignored + untracked** (varies per machine). The local copy was regenerated
  with a different routing/feature-log — it no longer has an `extrude-segment` op
  or the helices `h_XY_0_4`/`h_XY_0_5` the test hard-pins to. As of 2026-06-28 the
  stale `assert feature_log[1].op_kind == "extrude-segment"` was converted to a
  **skip-guard** (skip when the fixture doesn't match the pinned structure) so the
  backend suite stays green. The scrub-on-delete behaviour it intended to test is
  still covered fixture-free by `test_delete_independent_parallel_extrusion_survives`.
- **Fix options:** (a) commit a SMALL tracked fixture + re-pin the test to it,
  (b) rebuild the assertion synthetically (no workspace file), or (c) delete the
  test as redundant. Until then it silently skips when the local fixture has drifted.

### Advanced/seamless scaffold routing is hash-seed non-deterministic (TODO: fix)
- **Where:** [seamed_router.py](backend/core/seamed_router.py) `_ham_path_ending`
  (~line 291) + the neighbor key it hands to `_ham_path_search`. Both sort by
  `len(adj[n])` with **no secondary `n` tiebreaker**, so equal-degree nodes keep
  their set-derived (hash-seed-dependent) order. In-code `FIXME(advanced-routing-
  nondeterminism)` marks the exact spot.
- **Why it's debt:** the Hamiltonian path → scaffold routing comes out differently
  run-to-run. `auto_scaffold_seamless` / `auto_scaffold_advanced_seamed` emit a
  **different scaffold-strand count** depending on `PYTHONHASHSEED`. Real-app impact:
  the same design routes differently on different backend runs (not just tests).
- **Repro (2026-06-04):** `tests/test_seamless_router.py::test_teeth_closing_zig`
  (asserts exact `bridge_xovers==6`, `scaf_strands==4`) is **flaky ~50%** — 4 pass /
  4 fail across 8 fresh processes. Also varies `advanced_seamed` on teeth between 1
  and 4 scaffolds (originally misattributed to the live app rewriting the fixture).
- **History:** `seamless_router._ham_path_ending` (its OWN copy) deliberately uses
  `(len(adj[n]), n)` WITH the `n` tiebreaker to avoid exactly this (documented in
  [[seamless-scaffold-router-architecture-and-hard-won-lessons]] lines 29–32). The
  2026-06-01 budgeted-DFS refactor that delegated the search to the shared
  `seamed_router._ham_path_search` dropped the tiebreaker → regression.
- **Action (TODO, NOT done):** add a secondary `n` key to BOTH the starter sort
  (line 291) and the neighbor key passed to `_ham_path_search`, then verify teeth
  routing topology is unchanged (`bridge_xovers==6`, `scaf==4`) and de-flake the
  test. **TOPOLOGY-SENSITIVE — get user review before/after.** Marked by the user as
  work-to-be-done 2026-06-04; surfaced while committing CI fixtures for the router
  tests ([[seamless-scaffold-router-architecture-and-hard-won-lessons]]).

### ~~Overhang Bind/Unbind button (legacy OverhangBinding pair model)~~ — REMOVED 2026-06-30
- **Where:** [overhang_sequences_panel.js](frontend/src/ui/overhang_sequences_panel.js).
- **Resolution (2026-06-30, final):** the per-row Bind/Unbind toggle was **removed entirely**
  — user feedback: mixing bind/relax actions between the Overhangs list and the Overhang
  Connections section was a bad idea; keep each section's job separate. (A short-lived
  intermediate version rewired the toggle to the unified relax; that was scrapped.)
- **Replaced by a LINK ICON:** for any overhang that participates in a connection (a
  `overhang_bindings` / `overhang_connections` / `connection_versions` entry — see pure
  `connectionPairForOverhang(design, ovhgId)`), the last column shows a chain-link button.
  Click → `openConnectionForPair(a, b)` (new export from
  [overhang_connections_panel.js](frontend/src/ui/overhang_connections_panel.js)) which
  expands the Connections section, sets the A/B dropdowns to the pair, and selects the
  pair's **applied** ConnectionVersion (falling back to the live linker/binding row).
  Imported directly (singleton entry point) → **no main.js change**. All bind/unbind /
  relax lives in the Connections section only.
- **Keystone backend fix (kept):** `crud.patch_overhang_binding` passes `driver_side`
  (from `target.driver_oh_id`) into `compute_bind_topology`, so toggling a UNIFIED
  same-rigid-body root-to-root binding's `bound` flag no longer 422s on the same-cluster
  guard. This now serves the Connections section's **Bound checkbox** (the proper home of
  bind/unbind), NOT the removed sidebar button. Legacy bindings (`driver_oh_id=None`)
  unchanged. Pin: `test_direct_connection_unified.py::
  test_unbind_then_rebind_roundtrips_same_body_unified_binding` (proven red without it).
- **Note:** the OverhangBinding model is NOT abandoned — it IS the current unified direct
  connection record (see [[overhang-connections-panel]]). The old "superseded by oh_binder"
  framing was stale.
- **NOT hand-driven in-app** (manual-validation debt): the link icon (appears for connected
  overhangs, click opens the Connections section on the applied version) is pinned by jsdom
  but not exercised against a real overhang-bearing design in the running app.
