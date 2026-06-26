---
name: Cluster autodetection — scaffold + geometry dual system
description: How _autodetect_clusters works, algorithm rules for each cluster type, bridge helix handling, and the mixed-cluster frontend bug
type: project
originSessionId: 97d1bf68-963a-4055-a1d4-0a23b4019608
---
## Overview (2026-04-25, kinematics-cleanup)

`_autodetect_clusters(design)` is called on every cadnano/scadnano import. It produces two named sets of clusters stored together in `design.cluster_transforms`:

> **Location (2026-06-16, carve-up #34):** the 5 pure cluster-detection functions — `_autodetect_clusters`, `_cluster_by_scaffold_routing`, `_cluster_by_lattice_neighbors`, `_geometry_clusters_multi_scaffold`, `_cluster_bundle_regions` — now live in `backend/core/cluster_autodetect.py` (pure topology, no api/state deps). crud.py imports the 2 entry points (`_autodetect_clusters`, `_cluster_bundle_regions`) back. `_ensure_default_cluster` stays in crud.py (it calls `design_state.set_design_silent`). Direct unit tests: `tests/test_cluster_autodetect_core.py`.

- **Scaffold Cluster N** — topology-based, one per module scaffold
- **Geometry Cluster N** — rigidity-based, algorithm depends on scaffold count

Both sets are always produced. For single-scaffold designs the scaffold cluster covers everything; geometry clusters subdivide it into rigid sub-segments.

---

## Scaffold clusters — `_cluster_by_scaffold_routing`

One cluster per module scaffold (scaffold visiting ≥ `_MIN_MODULE_HELICES = 3` unique helices).

**Exclusive helices** (visited by exactly one scaffold): listed in `helix_ids`, no `domain_ids` needed. All nucleotides on those helices are implicitly included.

**Bridge helices** (visited by 2+ scaffolds): listed in BOTH clusters' `helix_ids`, AND each cluster gets explicit `DomainRef` entries in `domain_ids` covering:
- The scaffold strand's own domains on that bridge helix
- All non-scaffold domains whose bp range majority-overlaps with that scaffold's coverage on that bridge helix

The deformation backend handles this: when `any_domain_level=True` and a cluster's `domain_ids` has no entries for a given helix (exclusive helix of a mixed cluster), it falls back to full helix-level transform (see `backend/core/deformation.py`).

**Orphan helices** (not visited by any scaffold): absorbed into the scaffold cluster with the most canonical crossovers to it.

---

## Geometry clusters

### Single-scaffold (or no scaffold): `_cluster_by_lattice_neighbors`

Pure lattice-adjacency with FL-only edge removal. Same-scaffold adjacency constraint within each scaffold's exclusive helices. Gives rigid sub-segments separated by forced-ligation joints (e.g. hinge → 3 segments). Named "Geometry Cluster N" by `_autodetect_clusters`.

### Multi-scaffold (≥2 module scaffolds): `_geometry_clusters_multi_scaffold`

One cluster per module scaffold. **Bridge helices are assigned WHOLE** to the scaffold with the most bp coverage on them — no `domain_ids` split. This produces clean non-overlapping rigid bodies:

- Voltron: platform (scaffold 343) exclusive helices → GC1; bridge helices 44–49 + arm exclusive helices → GC2 (scaffold 0 covers ~613 bp on bridge vs scaffold 343's ~164 bp → arm gets the bridges whole)

**Why not use pure lattice-adjacency?** For Voltron, bridge helices are lattice-adjacent to both platform and arm helices, so pure lattice-adj gives one giant cluster.

**Why not use same-scaffold lattice-adj (like `_cluster_by_lattice_neighbors`)?** That algorithm fragmented the arm into 2–3 sub-clusters (GC2: 11 helices, GC3: 2 helices) because the arm's exclusive helices are not all mutually lattice-adjacent.

---

## The mixed-cluster frontend bug (fixed 2026-04-25)

**Symptom:** Clicking a scaffold cluster in the joints panel only glowed the bridge helix portions — the exclusive helices (e.g. all 52 platform helices) were invisible.

**Root cause:** Two places in `frontend/src/main.js` branched on `cluster.domain_ids?.length`:
- If non-empty → only used `domain_ids` to find nucleotides (bridge portions only)
- If empty → used `helix_ids` (whole helices)

Exclusive helices in a mixed cluster (in `helix_ids` but with no `domain_ids` entries) were silently ignored.

**Fix locations in `main.js`:**
1. **Glow highlight** (~line 6390): build `bridgeHelixIds` by looking up each domain_ids entry's helix via `strandMap`. Exclusive helices = `helix_ids` minus `bridgeHelixIds`. Filter backbone entries against both domain key set AND exclusive helix set.
2. **Visibility toggle** (~line 6219): same bridge/exclusive split. Add `d:strand:domain` keys for bridge domains AND `h:helix_id` keys for exclusive helices.

`helix_renderer.js:_isNucHidden` and `unfold_view.js:_isNucHidden` both support the mixed `h:` / `d:` key format already, so no changes needed there.

**How to apply:** Any future frontend code that branches on `domain_ids?.length` for cluster membership must apply the same bridge/exclusive split.

---

## Diagnostic scripts

- `scripts/scaffold_coverage.py <file>` — per-helix bp range for each module scaffold
- `scripts/cluster_coverage.py <file>` — per-helix bp range for each autodetected cluster, compared against scaffold routing, with mismatch report

Both accept `.sc` (scadnano) or `.json` (cadnano) files.

**Known mismatch report caveat:** Cluster order is sorted by minimum helix ID, scaffold order is by strand index. For Voltron, Scaffold Cluster 1 = scaffold 343 (platform, starts at helix 0) and Scaffold Cluster 2 = scaffold 0 (arm, starts at helix 44). The mismatch report may pair them backwards — always verify by helix labels, not by cluster/scaffold index.

---

## Key constants and thresholds

- `_MIN_MODULE_HELICES = 3`: scaffold strands visiting fewer than 3 unique helices are ignored as module boundaries (handles cadnano import artifacts like the hinge's 70 tiny scaffold fragments)
- Bridge helix bp coverage comparison: `max(d.start_bp, d.end_bp) - min(d.start_bp, d.end_bp)` per scaffold per helix, merged across all domains of that scaffold on that helix
