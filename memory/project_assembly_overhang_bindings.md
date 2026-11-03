---
name: assembly-overhang-bindings
description: "Cross-part overhang manager — AssemblyOverhangBinding (sub-domain WC pair) + AssemblyOverhangConnection (cross-part linker, ss/ds with bridge sequence) + ported Connection Types tab with exclusion rules + Assembly feature-log target. Shipped 2026-05-14."
metadata: 
  node_type: memory
  type: project
  originSessionId: b3ee46f4-5e87-467e-b773-893ba2171f60
---

# Assembly Overhang Bindings + Connections (shipped 2026-05-14)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

Cross-part Watson-Crick pairing **and** cross-part linker design for the Assembly overhaul. Pure topology metadata — no geometry application, no joint coupling. Connection Types tab from the per-part Overhangs Manager is ported here in full, including exclusion rules.

<a id="-duplex-convergence--backend-shipped-2026-07-11-see-overhang-duplex-foundation"></a>
- [⭐ Duplex convergence — BACKEND SHIPPED 2026-07-11 (see [[overhang-duplex-foundation]])](details/project_assembly_overhang_bindings/01-duplex-convergence--backend-shipped-2026-07-11-see-overhang-dupl.md#-duplex-convergence--backend-shipped-2026-07-11-see-overhang-duplex-foundation)

<a id="phase-b-crud-routes--shipped-2026-07-11-backend"></a>
- [Phase B CRUD routes — SHIPPED 2026-07-11 (backend)](details/project_assembly_overhang_bindings/01-duplex-convergence--backend-shipped-2026-07-11-see-overhang-dupl.md#phase-b-crud-routes--shipped-2026-07-11-backend)

<a id="phase-c-frontend--shipped-2026-07-11-verified-in-app"></a>
- [Phase C frontend — SHIPPED 2026-07-11 (verified in app)](details/project_assembly_overhang_bindings/01-duplex-convergence--backend-shipped-2026-07-11-see-overhang-dupl.md#phase-c-frontend--shipped-2026-07-11-verified-in-app)

<a id="sidebar-overhangs-list--shipped-2026-07-11-verified-in-app"></a>
- [Sidebar Overhangs list — SHIPPED 2026-07-11 (verified in app)](details/project_assembly_overhang_bindings/01-duplex-convergence--backend-shipped-2026-07-11-see-overhang-dupl.md#sidebar-overhangs-list--shipped-2026-07-11-verified-in-app)

<a id="sidebar-overhang-connections-panel--shipped-2026-07-11-verified-in-app"></a>
- [Sidebar Overhang CONNECTIONS panel — SHIPPED 2026-07-11 (verified in app)](details/project_assembly_overhang_bindings/01-duplex-convergence--backend-shipped-2026-07-11-see-overhang-dupl.md#sidebar-overhang-connections-panel--shipped-2026-07-11-verified-in-app)

<a id="what-ships"></a>
- [What ships](details/project_assembly_overhang_bindings/01-duplex-convergence--backend-shipped-2026-07-11-see-overhang-dupl.md#what-ships)

<a id="data-models-both-on-assembly"></a>
- [Data models (both on `Assembly`)](details/project_assembly_overhang_bindings/02-data-models-both-on-assembly.md#data-models-both-on-assembly)

<a id="routes"></a>
- [Routes](details/project_assembly_overhang_bindings/02-data-models-both-on-assembly.md#routes)

<a id="new-snapshotopkind-literals"></a>
- [New `SnapshotOpKind` literals](details/project_assembly_overhang_bindings/02-data-models-both-on-assembly.md#new-snapshotopkind-literals)

<a id="frontend"></a>
- [Frontend](details/project_assembly_overhang_bindings/02-data-models-both-on-assembly.md#frontend)

<a id="tests"></a>
- [Tests](details/project_assembly_overhang_bindings/02-data-models-both-on-assembly.md#tests)

## Mechanics worth remembering

- **Seek semantics**: each assembly mutation pushes one snapshot to `assembly_state._history`. So `feature_log` length == snapshot count. Seek to position N just walks `undo()`/`redo()` until the live feature_log matches `N+1`. No payload embedding, no replay logic. Simple and stack-walking-based.
- **Why `evicted=True`**: assembly entries carry no payload; the snapshot lives in the deque, not in the entry. Mirrors the per-part mutation helper's behaviour at [backend/api/assembly.py:1180](../backend/api/assembly.py#L1180).
- **Inventory data source (frontend)**: popup reads overhangs from `inst.source.design.overhangs` (inline source). File-backed instances need a deferred fetch — not handled in v1.

<a id="cross-part-linker-topology-shipped-2026-05-15"></a>
- [Cross-part linker topology (shipped 2026-05-15)](details/project_assembly_overhang_bindings/03-cross-part-linker-topology-shipped-2026-05-15.md#cross-part-linker-topology-shipped-2026-05-15)

<a id="indirect-zero-length-linkers--ss-connector-arcs-2026-06-07"></a>
- [Indirect (zero-length) linkers + ss connector arcs (2026-06-07)](details/project_assembly_overhang_bindings/03-cross-part-linker-topology-shipped-2026-05-15.md#indirect-zero-length-linkers--ss-connector-arcs-2026-06-07)

<a id="3d-overhang-hoverclick-selection--manager-prefill-shipped-2026-05-20-redesigned-to-hoverproximity-2026-05-21"></a>
- [3D overhang hover/click selection → manager prefill (shipped 2026-05-20; redesigned to hover/proximity 2026-05-21)](details/project_assembly_overhang_bindings/03-cross-part-linker-topology-shipped-2026-05-15.md#3d-overhang-hoverclick-selection--manager-prefill-shipped-2026-05-20-redesigned-to-hoverproximity-2026-05-21)

## Deferred for follow-up tasks

- **Domain Designer tab** (Pathview Three.js + Annotations pane with Tm/GC/Gen + sub-domain split/merge). Sub-domain edits are read-only in the assembly view per current scope decision.
- SVG tile variant picker (currently a plain dropdown).
- Inline editing for name + length on table rows.
- Bound-toggle checkbox in the table's Bound column for bindings.
- Apply geometry on bind (move/rotate parts to satisfy the WC pairing).
- Automatic joint creation between bound parts.
- File-backed PartInstance support in the inventory pane (relies on `inst.source.design` being inline).
- Atomistic linker rendering between bound parts.
- Typed log entries (we currently piggyback on `SnapshotLogEntry` tagged via `op_kind`).
- Selection layer: clicking an assembly linker bead in 3D → highlight the spreadsheet row (and vice versa) needs `selection_manager.js` to understand `assembly_strands`. Not wired in v1.

<a id="related"></a>
- [Related](details/project_assembly_overhang_bindings/04-related.md#related)
