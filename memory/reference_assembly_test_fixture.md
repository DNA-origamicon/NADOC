---
name: reference_assembly_test_fixture
description: "workspace/Belt_test1.nass is the reference-standard comprehensive assembly fixture (parts, groups, mates, polymers, belts, parts-on-belts)"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 4ffd7390-a668-46dd-92d7-cc526b07f467
---

**`workspace/Belt_test1.nass` is the reference standard for assembly tests/exercises** — the user designated it (2026-06-04) as the go-to fixture because it exercises every assembly subsystem at once.

What it contains (verified, `.nass` `format_version: 2`):
- **10 instances** (`instances_v2`) from **3 deduped `sources`** — includes polymer copies (polymerized chain from a seed).
- **2 groups** of 4 instances each (PartGroups — see [[project_assembly_groups]]).
- **8 joints** (mates between parts).
- **1 belt path** + **1 belt rider** (a part mated onto the belt — see [[project_belt_paths]], [[project_polymerize_origami]]).
- `gear_relations`/`overhang_bindings`/`overhang_connections` are empty here (use other fixtures if you need those).

**Use it when** a task touches assembly rendering, group/part selection, the shared GPU-instancing renderer ([[project_path_to_thousands]]), gizmos, belts, polymers, or the main.js assembly-pointer/group-gizmo carve-up regions ([[project_assembly_overhaul]]) — it's a single load that surfaces parts+groups+mates+belts together rather than needing a hand-built multi-part assembly.

Caveat from extraction-loop convention: e2e/gesture specs that build assemblies use the `__e2e__` workspace prefix (auto-cleaned). This is a *persistent* fixture under `workspace/` — load it read-only; don't let a test overwrite it.
