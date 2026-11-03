# What ships — supporting detail

[Topic head](../../project_polymerize_origami.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## What ships

### Data flow
- Seed: an existing `AssemblyJoint` whose `instance_a_id` / `instance_b_id` reference two `PartInstance`s with the same `PartSource` (file-backed: same `.path`; inline: same `Design.id` or equal structural dump).
- Per step (forward): new instance at `delta @ T_prev` where `delta = T_B @ inv(T_A)`. Backward uses `inv(delta)`. New joint between `(prev, new)`, axes derived by transforming the seed joint's `axis_origin`/`axis_direction` through `delta^i`.
- Count semantics: total chain length (existing + new). For `direction="both"`, new instances split evenly; the extra goes forward when `(count − 2)` is odd.
- Each new instance deep-copies the source side's per-instance state (representation / mode / overrides / `interface_points`) so the chain is uniform without re-defining connectors.

### Backend
- Pure math in [backend/core/assembly_polymer.py](../../../backend/core/assembly_polymer.py) — `_sources_match`, `_split_count`, `compute_chain_transforms`, `transform_joint_axis`, `compute_chain_joint_axes`. Unit-testable without FastAPI.
- **Record-assembly orchestration also in core now (carve-up #21, 2026-06-08):** `build_polymer_chain(joint, inst_a, inst_b, additional_instances, count, direction, all_instances, all_joints) -> (existing_instances, new_instances, new_joints)` holds the connector-union + clone build + pattern-mate replication (the `_make_clone`/`_clone_id_*` closures). The `polymerize_assembly` HANDLER is now thin (validate→lookup→delegate→commit→respond, ~80 ln). Direct tests in [tests/test_assembly_polymer_core.py](../../../tests/test_assembly_polymer_core.py) (12). **The PERIODIC build span is ALSO in core now (carve-up #22, 2026-06-15):** `build_periodic_chain(seed, delta, delta_inv, specs, count, direction, all_instances) -> (existing_instances, new_instances, new_joints)` holds the chain-split + delta-power placement + seam-IP union/replacement + uniform seam-joint wiring (`_clone`/`_seam_joint` closures); `polymerize_periodic_assembly` HANDLER is now thin (~50 ln). +8 unit tests in the same file (20 total). Both handlers thin → the 3-route ROUTER lift to `routes_assembly_polymerize.py` is the next carve-up step.
- Route `POST /assembly/polymerize` in [backend/api/assembly.py](../../../backend/api/assembly.py) — body `{joint_id, count, direction}`. Errors: 400 on `count < 2`, 404 on unknown joint, 422 on `sources_differ` or single-side joint. `count == 2` is a no-op (no feature_log entry).
- New `SnapshotOpKind` literal `"assembly-polymerize"` ([backend/core/models.py](../../../backend/core/models.py)).
- Feature_log params record `joint_id` / `count` / `direction` + `new_instance_ids` + `new_joint_ids` so the op can be identified later.

### Frontend
- Menu: `Assembly → Polymerize Origami…` in [frontend/index.html](../../../frontend/index.html).
- Panel: new sidebar section [frontend/src/ui/polymerize_panel.js](../../../frontend/src/ui/polymerize_panel.js), mounted as a DOM sibling immediately after `#properties-section`. Hidden until menu fires `open()`; closes on `Esc` or `✕`. Panel has two ways to pick a seed mate: a dropdown listing every joint in the assembly (label `"<joint.name>: <instA.name> ↔ <instB.name>"`) and a 3D click on the orange joint indicator.
- Selection: while open, the pick in [frontend/src/main.js](../../../frontend/src/main.js) `_onAssemblyPointerDown` (~line 8596) uses `assemblyJointRenderer.pickJointAny(e)` — clicking the shaft, cone, OR ring of the indicator selects the mate. `pickJointRing` is still used outside polymerize mode to start revolute drags. (The ring alone is a narrow target — `RING_TUBE = 0.08 nm` — which is why the whole-indicator picker is needed here.)
- Non-identical warning: when the selected mate's two instances don't share a source, the panel shows a yellow `⚠` warning ("polymerization needs the same part on both sides") and the Polymerize button stays disabled. The backend independently 422's the same case.
- Client: `polymerizeAssembly(body)` in [frontend/src/api/client.js](../../../frontend/src/api/client.js).
- **Chain length is UNBOUNDED (2026-05-22).** The old `max="64"` input attr + two
  `Math.min(64, …)` clamps in `polymerize_panel.js` were removed at user request — any count ≥ 2 is
  allowed. The backend never had an upper bound (only `count < 2` → 400). The non-blocking
  `projected >= 20` confirm dialog (OOM warning) stays; it doesn't limit length, just warns.
  Regression: [frontend/e2e/polymerize_no_length_limit.spec.js](../../../frontend/e2e/polymerize_no_length_limit.spec.js).

### Tests
[tests/test_polymerize.py](../../../tests/test_polymerize.py) — 21 tests covering source-match logic, chain math (forward / backward / both / odd-extra-goes-forward), transform-joint-axis math, and the full API path (count=2 no-op, 400/404/422 paths, connector preservation, joint-type/label propagation, feature_log entry). Full suite: 1301 passed (gained 21 from this feature, no regressions).
