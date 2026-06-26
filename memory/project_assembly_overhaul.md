---
name: Assembly overhaul — planning document
description: Full architectural analysis for multi-origami assembly system — two paths, data model proposals, DOF hierarchy, open decisions
type: project
originSessionId: 56d058db-5d5d-46e6-a16b-461336fcaa1e
---
# NADOC Assembly Overhaul — Planning Document
**Date:** 2026-04-17  
**Branch:** assembly-overhaul  
**Status:** Planning — no implementation started

---

## 1. What Already Exists (build on, not over)

The assembly scaffolding is already partially defined at the bottom of `backend/core/models.py:584`:

```python
class ConnectionType(str, Enum):
    BLUNT_END | TOEHOLD | BIOTIN | COVALENT   # interface chemistry

class InterfacePoint(BaseModel):
    label: str; position: Vec3; normal: Vec3; connection_type: ConnectionType

class FluctuationEnvelope(BaseModel):
    semi_axes: Vec3; source: str   # ellipsoid from XPBD/oxDNA data

class ValidationRecord(BaseModel):
    oxdna_minimized, cando_run, snupi_run, experimental_validated, notes

class Part(BaseModel):             # "future use" comment — now is the time
    id: str
    design: Design                 # ALWAYS inline for now; no file references yet
    interface_points: List[InterfacePoint]
    fluctuation_envelope: Optional[FluctuationEnvelope]
    local_frame: Mat4x4            # placement of Part in some containing frame
    validation_record: ValidationRecord

class Mat4x4(BaseModel):
    values: List[float]            # row-major 4×4 homogeneous transform, already works
```

And already used in the intra-design world:
- `ClusterRigidTransform` — rigid body groups (helix sets) with SE3 transforms  
- `ClusterJoint` — revolute axis on a cluster (position + direction; one DOF)  
- `feature_log: List[FeatureLogEntry]` — undo/redo trail for cluster ops  

**Key architectural constraint:** `Design` is topological ground truth. The assembly layer sits **above** `Design` — it must never modify topology. Placement transforms and joint drives are display-layer only (Three-Layer Law still applies).

---

## 2. Key Lessons from CAD Architecture Research

### 2a. Assembly-ness is emergent (STEP / OpenUSD)
In STEP (ISO 10303) and OpenUSD, "assembly" is not a distinct type — it's emergent from an entity containing instances of other entities. There is no separate file format for assemblies vs. parts; the same schema handles both. This is the right approach for NADOC: a `.nadoc` file can be either a leaf design or an assembly.

### 2b. Instance transform lives on the reference, never on the definition (universal)
The placed Part definition should be transform-free. Only the `PartInstance` (the reference/occurrence) carries the SE3 transform from the Part's local frame to the assembly frame. This matches `Part.local_frame` in the existing stub but needs to move to the instance.

### 2c. Rigid vs. Flexible subassembly controls DOF propagation (CATIA DMU)
CATIA's most relevant concept: when a subassembly is **rigid**, upper-level constraints treat it as a single rigid body and internal DOFs are frozen. When it is **flexible**, internal DOFs remain active and compose with assembly-level DOFs. This maps directly to the user's use case: a DNA arm origami with an internal hinge joint (Part-level ClusterJoint) used in flexible mode so the arm's hinge composes with an assembly-level prismatic joint.

### 2d. External reference strategies
| Strategy | Mechanism | Best for |
|----------|-----------|----------|
| **Inline** | Full Design embedded in assembly JSON | Self-contained sharing, personal projects |
| **Path reference** | Relative file path to `.nadoc` file | Multi-file workflows, separate editing |
| **Hash reference** | SHA256 of part file content | Reproducible archives, team workflows |

A discriminated union (`PartSource`) can support all three without forcing a choice upfront.

### 2e. DOF accounting (Grübler–Kutzbach)
Each rigid body has 6 DOF. Each joint removes DOF:
- Rigid joint: removes 6 (welds parts together)
- Revolute: removes 5 (1 DOF left — rotation)
- Prismatic: removes 5 (1 DOF left — translation)
- Spherical: removes 3 (3 DOF left — all rotations)

Assembly mechanism DOF = 6n − Σ(DOF removed by joints), where n = number of free bodies. The system should display this count so users know if the assembly is under/over constrained.

---

## 3. Core Design Decisions (must settle before coding)

These are open questions that need user input:

**D1. Mixed-lattice assemblies?**  
Can an HC-lattice origami and a SQ-lattice origami be placed in the same assembly? Or does the assembly have a single lattice type? (Likely yes to mixing — assemblies are above the lattice.)

**D2. Linker strands between parts?**  
The physical connection between two origamis is often a strand extension (blunt-end stacking, toehold hybridization, biotin-streptavidin). Should linker strands be editable at the assembly level, or must they be defined within each Part?

**D3. Scaffold continuity across parts?**  
In multi-scaffold assemblies, each Part has its own scaffold strand. Inter-part scaffold connections are impossible (each is a separate DNA molecule). Should the assembly enforce this, or allow "virtual" scaffold connections for visualization?

**D4. Physics at assembly level?**  
XPBD/oxDNA simulations are currently per-design. Does the assembly need to run joint physics (computing equilibrium joint angles), or is kinematic positioning (user-driven angles) sufficient for Phase 1?

**D5. Animation at assembly level?**  
The existing animation system drives ClusterRigidTransforms via keyframes. Should assembly-level joint drives also be keyframeable? (Probably yes, but this is additional scope.)

**D6. Undo/redo scope?**  
Does Ctrl+Z undo assembly-level operations (moving a part instance, driving a joint) or only intra-part operations? Both means the assembly's feature_log must be distinct from each Part's feature_log.

---

## 4. Path A — Inline Assembly (Recommended First)

### Philosophy
Extend the existing `.nadoc` format with a top-level `Assembly` model. Parts are embedded inline (same `Design` schema). Assembly-level joints connect Part instances. The file is self-contained. This builds directly on the existing `Part` stub and `ClusterJoint` infrastructure.

### New models (additions to `backend/core/models.py`)

```python
# ── Assembly source (discriminated union) ─────────────────────────────────────

class PartSourceInline(BaseModel):
    """Part Design is embedded in this file."""
    type: Literal["inline"] = "inline"
    design: Design

class PartSourceFile(BaseModel):
    """Part Design lives in a separate .nadoc file (path-relative to this file)."""
    type: Literal["file"] = "file"
    path: str               # relative path to .nadoc file
    sha256: Optional[str] = None  # content hash; None = not verified

PartSource = Annotated[Union[PartSourceInline, PartSourceFile],
                       Field(discriminator="type")]


# ── Part Instance ──────────────────────────────────────────────────────────────

class PartInstance(BaseModel):
    """
    One placed occurrence of a Part in an Assembly.

    transform: SE3 expressed as a 4×4 matrix (row-major, nanometres + radians).
    Transforms the Part's local-frame axis_start/axis_end into assembly world-space.

    mode:
      "rigid"    — Part treated as single rigid body; its internal ClusterJoints frozen.
      "flexible" — Internal ClusterJoints active; they compose with assembly-level joints.

    joint_states: current driven angle/displacement for each ClusterJoint in the source
    design (joint_id → float in radians or nm). Only meaningful when mode="flexible".

    cluster_transform_overrides: per-instance overrides for cluster positions
    (equivalent to Design.cluster_transforms, but scoped to this instance).
    Only meaningful when mode="flexible".
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Part"
    source: PartSource
    transform: Mat4x4 = Field(default_factory=Mat4x4)
    mode: Literal["rigid", "flexible"] = "flexible"
    visible: bool = True
    # DOF state for intra-part joints when mode="flexible"
    joint_states: dict[str, float] = Field(default_factory=dict)  # joint_id → rad|nm
    cluster_transform_overrides: List[ClusterRigidTransform] = Field(default_factory=list)
    # Assembly-level interface points (overrides Part.interface_points when set)
    interface_points: List[InterfacePoint] = Field(default_factory=list)


# ── Assembly Joint ─────────────────────────────────────────────────────────────

class AssemblyJoint(BaseModel):
    """
    A kinematic joint connecting two PartInstances in an Assembly.

    instance_a_id: "parent" body. None = world/ground frame.
    instance_b_id: "child" body being constrained relative to instance_a.
    cluster_id_a / cluster_id_b: optional — if set, the joint axis is relative to
    that specific cluster within the Part (allows joints at Part sub-regions).

    axis_origin / axis_direction: in assembly world-space at zero-angle/displacement.

    current_value: current DOF value (radians for revolute, nm for prismatic).
    Stored here for persistence; driven by animation or user interaction.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Joint"
    joint_type: Literal["revolute", "prismatic", "spherical", "rigid"] = "revolute"
    instance_a_id: Optional[str] = None   # None = ground
    cluster_id_a:  Optional[str] = None
    instance_b_id: str
    cluster_id_b:  Optional[str] = None
    axis_origin:    List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    axis_direction: List[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    current_value:  float = 0.0           # rad (revolute) | nm (prismatic)
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None


# ── Assembly ──────────────────────────────────────────────────────────────────

class Assembly(BaseModel):
    """
    A multi-origami assembly.

    Contains PartInstances (each wrapping a Design with a placement transform)
    and AssemblyJoints that define kinematic constraints between instances.

    assembly_helices / assembly_strands: helices and strands that exist at the
    assembly level (e.g., linker strands connecting two Parts). May be empty.

    feature_log: undo/redo trail for assembly-level operations only (instance
    moves, joint drives). Each Part's own feature_log is separate.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: DesignMetadata = Field(default_factory=DesignMetadata)
    instances: List[PartInstance] = Field(default_factory=list)
    joints: List[AssemblyJoint] = Field(default_factory=list)
    # Assembly-level helices (linkers between parts, not belonging to any Part)
    assembly_helices: List[Helix] = Field(default_factory=list)
    assembly_strands: List[Strand] = Field(default_factory=list)
    # Camera and animation at assembly level
    camera_poses: List[CameraPose] = Field(default_factory=list)
    animations: List[DesignAnimation] = Field(default_factory=list)
    # Undo/redo for assembly-level ops
    feature_log: List[FeatureLogEntry] = Field(default_factory=list)
    feature_log_cursor: int = -1

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "Assembly":
        return cls.model_validate(data)
```

### File format change

Top-level `.nadoc` JSON gains a `file_type` discriminator:

```json
// Legacy/leaf part file (unchanged):
{ "id": "...", "helices": [...], "strands": [...], ... }

// Assembly file (new):
{
  "file_type": "assembly",
  "assembly": {
    "id": "...",
    "metadata": { "name": "My Assembly" },
    "instances": [
      {
        "id": "inst-1",
        "name": "Arm A",
        "source": {
          "type": "inline",
          "design": { /* full Design object */ }
        },
        "transform": { "values": [1,0,0,0, 0,1,0,0, 0,0,1,0, 10,5,0,1] },
        "mode": "flexible",
        "joint_states": { "joint-uuid-1": 0.523 }
      },
      {
        "id": "inst-2",
        "name": "Base",
        "source": {
          "type": "file",
          "path": "./base_origami.nadoc",
          "sha256": "abc123..."
        },
        "transform": { "values": [1,0,0,0, ...identity...] },
        "mode": "rigid"
      }
    ],
    "joints": [
      {
        "id": "jnt-1",
        "name": "Arm-Base hinge",
        "joint_type": "revolute",
        "instance_a_id": "inst-2",
        "instance_b_id": "inst-1",
        "axis_origin": [10, 5, 0],
        "axis_direction": [0, 1, 0],
        "current_value": 0.523
      }
    ]
  }
}
```

Backward compatibility: absence of `file_type` means legacy leaf design.

### Backend changes needed

1. **`backend/api/assembly_state.py`** (new) — `AssemblyState` class mirroring `DesignState`; holds active `Assembly` + undo stack; provides `get_or_404()`.

2. **`backend/api/assembly_crud.py`** (new) — REST routes:
   ```
   GET    /assembly/                  → current assembly or 404
   POST   /assembly/new               → create empty assembly
   POST   /assembly/load              → load .nadoc assembly file
   GET    /assembly/download          → download as .nadoc
   POST   /assembly/instances         → add PartInstance (inline or by path)
   PATCH  /assembly/instances/{id}    → update transform/mode/name
   DELETE /assembly/instances/{id}    → remove instance
   POST   /assembly/joints            → add AssemblyJoint
   PATCH  /assembly/joints/{id}       → update joint value/axis
   DELETE /assembly/joints/{id}       → remove joint
   GET    /assembly/geometry          → flattened geometry (all instances, all parts)
   GET    /assembly/dof-count         → Grübler–Kutzbach DOF for current joints
   ```

3. **`backend/core/assembly.py`** (new) — assembly geometry computation:
   - `flatten_assembly(assembly, load_file_sources) → List[FlattenedHelix]` — apply each instance's `transform` + mode-dependent joint transforms to produce world-space helix axes and nucleotide positions for rendering.
   - `apply_part_transform(design, mat4x4) → Design` — return a copy with all axis_start/axis_end/nucleotide positions transformed by mat4x4. Reads topology only, returns new geometry.
   - `compute_assembly_dof(assembly) → int` — Grübler–Kutzbach count.

4. **`backend/core/models.py`** — add the 4 new model classes above. The existing `Part` stub can be repurposed or retired (its fields are now split between `PartInstance` and `PartSourceInline`).

### Frontend changes needed

1. **`frontend/src/state/assembly_store.js`** — Zustand store for assembly state (mirrors design store). Keys: `currentAssembly`, `assemblyMode` (bool), `selectedInstanceId`, `helixAxesByInstance`.

2. **`frontend/src/scene/assembly_renderer.js`** — renders flattened assembly geometry. Each PartInstance gets its own sub-group in the scene; the flat `helix_renderer.js` can be reused per-instance.

3. **`frontend/src/ui/assembly_panel.js`** — panel to manage instances (list, add, remove, rename, toggle visible/rigid).

4. **`frontend/src/scene/assembly_gizmo.js`** — 3D transform gizmo for placing/moving PartInstances (can reuse or adapt `cluster_gizmo.js`).

5. **`frontend/src/api/client.js`** — new `assemblyApi` group (add/remove/move instances, joints, download).

6. **Mode switching in `main.js`** — "design mode" vs "assembly mode" toggle. In assembly mode, clicking a Part instance activates it for instance-level operations. In design mode (double-click to enter), topology editing works on the active Part.

### DOF composition model (Path A)

The hierarchy from user's perspective:

```
Assembly.joints                 ← inter-part DOF (new)
  └── PartInstance.joint_states ← override intra-part joint states
        └── Design.cluster_joints ← intra-part DOF (existing ClusterJoint)
              └── Design.cluster_transforms ← rigid body positions
                    └── Design.helices ← topology (never touched)
```

**Flexible mode flow** (user drives an assembly joint that moves one Part instance):
1. Assembly joint drive updates `AssemblyJoint.current_value` + `PartInstance.transform`.
2. For flexible instances, the renderer also applies `PartInstance.joint_states` which maps `ClusterJoint` drives inside the Part's Design.
3. Geometry backend receives the composed transform (instance_transform × joint_driven_cluster_transform).

**Rigid mode flow:** `PartInstance.transform` is updated; all intra-part cluster_transforms are applied as if they were at their reference state. The instance moves as a single rigid body.

---

## 5. Path B — External Reference Assembly

### Philosophy
A new file type `.nassembly` (or `.nadoc` with `"file_type": "assembly"`) holds only references to separate `.nadoc` part files, plus placement transforms and inter-part joints. No Design data is embedded. Parts must be loaded from disk on assembly open.

### Key differences from Path A
- `PartSourceFile` is the only source type (no inline)
- Backend `AssemblyState` must resolve file paths and cache loaded Designs
- Broken-link handling is required (file moved/deleted)
- "Pack" operation embeds all referenced parts for portable sharing

### Additional models needed (beyond Path A)
```python
class PartLibraryEntry(BaseModel):
    """Registry of known .nadoc files for quick re-use in new assemblies."""
    id: str
    name: str
    path: str
    sha256: str
    thumbnail_b64: Optional[str] = None
    interface_points: List[InterfacePoint] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

class PartLibrary(BaseModel):
    """User's local library of available Part files."""
    entries: List[PartLibraryEntry] = Field(default_factory=list)
```

### Backend changes beyond Path A
- File resolver: `resolve_part_source(source: PartSourceFile, assembly_path: str) → Design`
- Library manager: CRUD for `PartLibrary` persisted to `~/.nadoc_library.json`
- "Pack" endpoint: embed all `PartSourceFile` references as `PartSourceInline`
- Hash verification: on load, check sha256 matches; warn if stale

### Frontend changes beyond Path A
- Part library panel (browse, drag-and-drop into assembly viewport)
- Broken-link UI (missing file warning with re-link button)
- "Part editor" mode — double-click on instance opens the part's `.nadoc` file in a separate window or panel

### Why Path B is harder
- Context switching (which file is "active"?) is non-trivial in a single-window app
- Undo/redo spans file boundaries
- File management overhead for a personal research tool
- Requires library management infrastructure before it's useful

---

## 6. Comparison

| | Path A (Inline) | Path B (External Refs) |
|--|--|--|
| File format | `.nadoc` gains `file_type: "assembly"` | `.nassembly` or `.nadoc` assembly |
| Part reuse | Manual (copy design into new assembly) | Automatic (same `.nadoc` file) |
| Self-contained | Yes — one file shares everything | No — need all referenced files |
| File size | Grows with number of parts | Assembly file stays thin |
| Implementation complexity | Medium — builds on existing stack | High — file resolver, library, context switching |
| Undo/redo | Straightforward — assembly has own log | Hard — spans file boundaries |
| Broken links | Impossible (inline) | Needs handling |
| Upgrade path | Can add `PartSourceFile` later | N/A (already external) |
| Right for personal research tool | **Yes** | Only once library grows |

---

## 7. Recommended Path

**Path A first, with PartSource discriminated union from the start.**

The `PartSource` union (`PartSourceInline | PartSourceFile`) is the crucial architectural decision that keeps Path B open as a future upgrade without forcing it now. All other Path A models already accommodate file references; the backend just doesn't need to resolve them yet.

**Implementation order:**
1. Add `PartSource`, `PartInstance`, `AssemblyJoint`, `Assembly` models to `models.py`  
   (retire/integrate existing `Part` stub)
2. `AssemblyState` + basic CRUD in `assembly_crud.py`
3. `flatten_assembly()` → flattened geometry endpoint
4. Frontend: assembly mode toggle, instance list panel, transform gizmo (reuse cluster_gizmo)
5. Frontend: inter-part joint definition (reuse joint_renderer surface picker)
6. Animation integration: drive assembly joints from keyframes
7. **Phase 2 (later):** `PartSourceFile` resolver, part library, "pack" operation

**The existing `Part` stub should evolve to:**
- `Part` → retire or repurpose as a "published part" wrapper (keeps interface_points, validation_record, fluctuation_envelope)
- `Part.design` → moves to `PartSourceInline.design`
- `Part.local_frame` → moves to `PartInstance.transform`

---

## 8. Open Questions for Next Session

Before writing any code, confirm with user:

1. **Mixed lattice?** — HC + SQ origamis in one assembly? (Probably yes)
2. **Linker strand scope?** — Editable at assembly level, or must live in Parts? If assembly-level, assembly_helices/assembly_strands need topology editing support.
3. **Scaffold continuity?** — Virtual scaffold connections across Parts for viz? Or treat all scaffold strands as independent?
4. **Physics scope?** — Kinematic-only (user drives joints) or constraint-solving (joints seek equilibrium)? Phase 1 should be kinematic.
5. **Animation scope?** — Assembly joints keyframeable in Phase 1? (Requires adding `AssemblyJointDriveEntry` to feature log.)
6. **Part library scope?** — Phase 1 with inline-only, or include `PartSourceFile` + library panel from the start?
7. **Undo scope** — Does Ctrl+Z undo assembly-level ops or only intra-part ops? (Recommend: separate undo stacks per level, one Ctrl+Z step per level boundary.)
8. **ID namespacing** — When two Parts have helices with the same ID (both h_0), how are they disambiguated in the flattened representation? Recommend prefixing with instance ID: `inst-1::h_0`.
