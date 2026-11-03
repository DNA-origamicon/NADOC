# Data models (both on `Assembly`) — supporting detail

[Topic head](../../project_assembly_overhang_bindings.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Data models (both on `Assembly`)
- `AssemblyOverhangBinding` — sub-domain Watson-Crick pair. References `{instance_a_id, sub_domain_a_id, overhang_a_id, instance_b_id, sub_domain_b_id, overhang_b_id}` plus `binding_mode` / `allow_n_wildcard`. Self-binding rejected by validator.
- `AssemblyOverhangConnection` — cross-part linker. References `{instance_a_id, overhang_a_id, overhang_a_attach}` + B side + `linker_type` (ss/ds), `length_value`, `length_unit` (bp/nm), `bridge_sequence`. Mirrors `OverhangConnection` but qualified per PartInstance.

### Routes
- Bindings: `POST/PATCH/DELETE /assembly/overhang-bindings[/{id}]` — duplicate pair = 409.
- Connections: `POST/PATCH/DELETE /assembly/overhang-connections[/{id}]` — server-side polarity rule (`_check_polarity_allowed` in [backend/api/assembly.py](../../../backend/api/assembly.py)) returns 422 on forbidden combos. Mirrors the frontend's `_isForbidden` function.
- `POST /assembly/features/seek` — `{ position }` -1 / -2 / N walks `assembly_state.undo()/redo()` until `feature_log` length matches target.

All mutations route through `_apply_assembly_mutation_with_feature_log` in [backend/api/assembly.py](../../../backend/api/assembly.py) — snapshot to deque, append `SnapshotLogEntry(evicted=True)` with one of the new op_kinds.

### New `SnapshotOpKind` literals
`assembly-overhang-bind`, `assembly-overhang-bind-patch`, `assembly-overhang-unbind`, `assembly-overhang-connection-add`, `assembly-overhang-connection-patch`, `assembly-overhang-connection-delete`.

### Frontend
- **Assembly → Overhangs Manager…** menu entry at the bottom of the Assembly dropdown. Tools menu's per-part manager untouched.
- New popup [frontend/src/ui/assembly_overhangs_manager_popup.js](../../../frontend/src/ui/assembly_overhangs_manager_popup.js) replaces the v1 list view with a full Connection Types layout:
  - Three columns: Side A overhang list (cyan, grouped by part), center variant picker + length + action button, Side B overhang list (magenta).
  - 12 connection-type variants in dropdown (direct ×2, indirect ×2, ss linker ×4, ds linker ×4).
  - Forbidden-polarity reason shown in red below the dropdown. Action button disables when forbidden / cross-part-same-instance / no selection.
  - Per-side sequence input + Gen button (writes via `patchInstanceOverhang`).
  - Bridge sequence box (shown when a linker row is selected in the table). Input + Gen.
  - Mixed table: linkers (AssemblyOverhangConnection) and bindings (AssemblyOverhangBinding) rendered together, each with Delete button. Connection rows are click-selectable to enable the bridge box.
  - "Make Complementary" button (variant = direct): writes RC(A) to B's sequence, then creates an AssemblyOverhangBinding using each side's first sub-domain.
- Feature Log target dropdown gets `Assembly: <name>` at the top, default-selected when entering assembly mode. New `_assemblyFeatureMode` state + `_rebuildAssemblyFeatureLog` path in [frontend/src/ui/feature_log_panel.js](../../../frontend/src/ui/feature_log_panel.js).

### Tests
[tests/test_assembly_overhang_bindings.py](../../../tests/test_assembly_overhang_bindings.py) — 20 tests: model round-trip, CRUD for bindings and connections, duplicate/self-binding rejection, polarity-forbidden rejection (422), seek to -1/-2/explicit index. All assembly suites (116 tests) green.
