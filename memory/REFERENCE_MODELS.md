---
name: REFERENCE_MODELS
description: Domain model conventions, overhang system, Design class hierarchy, start_bp/end_bp semantics
type: project
---

## Domain Model Convention (binding)
- `start_bp` = 5′ end of domain, `end_bp` = 3′ end — **regardless of direction**
- FORWARD native: start_bp=0, end_bp=N-1
- REVERSE native: start_bp=N-1, end_bp=0
- caDNAno-imported: start_bp/end_bp = global bp indices; `bp_start` = first active bp; `length_bp` = full array length

## Design Class Hierarchy
```
Design
├── metadata: DesignMetadata (name, description, author, tags, created_at, modified_at)
├── lattice_type: LatticeType (HONEYCOMB | SQUARE)
├── helices: List[Helix]
├── strands: List[Strand]
├── deformations: List[DeformationOp]
├── cluster_transforms: List[ClusterRigidTransform]
├── overhangs: List[OverhangSpec]
├── extensions: List[StrandExtension]
├── camera_poses: List[CameraPose]
└── animations: List[DesignAnimation]
    (NO `configurations` field — configurations are assembly-scoped only:
     AssemblyConfigurationSnapshot. `DesignConfiguration` never existed. Verified 2026-07-30.)

Helix
├── id, axis_start: Vec3, axis_end: Vec3
├── phase_offset: float, twist_per_bp_rad: float
├── length_bp: int, bp_start: int (global offset)
└── loop_skips: List[LoopSkip]

Strand
├── id, strand_type: StrandType (SCAFFOLD | STAPLE)
├── domains: List[Domain]
├── sequence: Optional[str]
├── color: Optional[str]
└── notes: Optional[str]

Domain
├── helix_id, start_bp, end_bp
├── direction: Direction (FORWARD | REVERSE)
└── overhang_id: Optional[str]

DeformationOp
├── id, type: str ('twist' | 'bend')
├── plane_a_bp, plane_b_bp, affected_helix_ids
└── params: TwistParams | BendParams

ClusterRigidTransform
├── id, name, helix_ids: List[str]
├── translation: [float×3], rotation: [float×4] (quaternion)
└── pivot: [float×3]
```

## Overhang System (binding, 2026-03-18 + UX-3)
```
OverhangSpec: {id, helix_id, strand_id, sequence?, label?}  — stored in Design.overhangs
Domain.overhang_id: str — tags domain as single-stranded overhang

Extrude-style ID: ovhg_{helix_id}_{bp_index}_{5p|3p}
  → dedicated helix; patch_overhang resizes that helix

Inline overhang ID: ovhg_inline_{strand_id}_{5p|3p}
  → shares helix with main strand (staple extended past scaffold)
  → patch_overhang detects is_inline and skips helix resize
```
Key functions: `_scaffold_coverage_by_helix(design)`, `_reconcile_inline_overhangs(...)` in `lattice.py`
Auto-scaffold skips helices where ALL domains have `overhang_id` set.

## Strand Extension (terminal 5'/3' overhang)
```python
StrandExtension:
  id, strand_id, end: str ('five_prime' | 'three_prime')
  sequence: Optional[str], modification: Optional[str], label: Optional[str]

VALID_MODIFICATIONS = ['cy3','cy5','fam','tamra','bhq1','bhq2','atto488','atto550','biotin']
```
Geometry: quadratic Bézier arc radially outward from terminal nucleotide.
Synthetic helix_id: `__ext_{id}`; `domain_index = -1.0` (5') or `float(len(domains))` (3').

## Loop/Skip
```python
LoopSkip: {bp_index: int, delta: Literal[-1, +1]}  # on Helix.loop_skips
# delta +1 = loop (insert), -1 = skip (delete)
```

## NucleotidePosition (geometry layer, immutable)
```python
NucleotidePosition:
  helix_id, bp_index, direction
  position: np.array[3]      # backbone bead center
  base_position: np.array[3] # base bead center (BASE_DISPLACEMENT inward)
  base_normal: np.array[3]   # points toward base from backbone
  axis_tangent: np.array[3]  # helix axis direction at this bp
```
DTP-0a: Both backbone AND base bead positions are computed. BASE_DISPLACEMENT = 0.3 nm.

## caDNAno-Imported Design Notes
- `bp_start` = global bp offset (helix may start at bp 50, not bp 0)
- `length_bp` = full array length (including unused positions)
- Strand start/end bp = global indices, not local helix indices
- HC row step = 3.375 nm in caDNAno coords (converted to NADOC 2.25 nm on import)
