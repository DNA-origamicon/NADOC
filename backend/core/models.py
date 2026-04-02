"""
Topological layer — core data models.

This module defines the canonical data structures for a DNA origami design.
All models live at the topological layer: they encode strand connectivity and
crossover graph structure.  No geometry is computed here.

Rules:
- Every model is a Pydantic BaseModel and is JSON-serialisable.
- Geometry (nucleotide positions) is computed in geometry.py from these models.
- Physics output never writes back to these models.
"""

from __future__ import annotations

import json
import math
import uuid
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enumerations ──────────────────────────────────────────────────────────────


class LatticeType(str, Enum):
    """Arrangement of helices within the design."""
    HONEYCOMB = "HONEYCOMB"
    SQUARE = "SQUARE"
    FREE = "FREE"


class Direction(str, Enum):
    """5′→3′ direction of a domain relative to the helix axis."""
    FORWARD = "FORWARD"   # 5′→3′ in the direction of increasing bp index
    REVERSE = "REVERSE"   # 5′→3′ in the direction of decreasing bp index


class CrossoverType(str, Enum):
    """Topological role of a crossover."""
    SCAFFOLD = "SCAFFOLD"
    STAPLE = "STAPLE"
    HALF = "HALF"          # single-stranded nick / half-crossover


class ConnectionType(str, Enum):
    """Chemical nature of an interface point on a Part."""
    BLUNT_END = "BLUNT_END"
    TOEHOLD = "TOEHOLD"
    BIOTIN = "BIOTIN"
    COVALENT = "COVALENT"


class StrandType(str, Enum):
    """Whether a strand is the scaffold or a staple."""
    SCAFFOLD = "scaffold"
    STAPLE = "staple"


# ── Primitive types ───────────────────────────────────────────────────────────


class Vec3(BaseModel):
    """3-component vector in nanometres (or dimensionless unit vectors)."""
    x: float
    y: float
    z: float

    def to_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)

    @classmethod
    def from_array(cls, arr: np.ndarray) -> Vec3:
        return cls(x=float(arr[0]), y=float(arr[1]), z=float(arr[2]))


class Mat4x4(BaseModel):
    """Row-major 4×4 homogeneous transform matrix for Part placement."""
    values: List[float] = Field(default_factory=lambda: [
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ])

    def to_array(self) -> np.ndarray:
        return np.array(self.values, dtype=float).reshape(4, 4)

    @classmethod
    def from_array(cls, arr: np.ndarray) -> Mat4x4:
        return cls(values=[float(v) for v in arr.flatten()])


# ── Core design models ────────────────────────────────────────────────────────


class Helix(BaseModel):
    """
    A single double-stranded DNA helix in the design.

    Axis runs from axis_start to axis_end.  phase_offset is the rotational
    phase (radians) at bp index 0; subsequent nucleotides are offset by
    BDNA_TWIST_PER_BP_RAD per step.

    bp_start is the global bp coordinate of local bp index 0 (axis_start end).
    It defaults to 0 for native NADOC designs.  caDNAno-imported designs may
    have bp_start = 0 with the full caDNAno array length stored in length_bp,
    so that domain start_bp/end_bp values directly match caDNAno bp indices.
    Negative bp_start values are valid for helices that extend in -Z from the
    design's slice-plane origin.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    axis_start: Vec3
    axis_end: Vec3
    phase_offset: float = 0.0   # radians
    twist_per_bp_rad: float = math.radians(34.3)  # radians/bp  (default = B-DNA 34.3°)
    length_bp: int
    bp_start: int = 0           # global bp coordinate of local bp index 0
    loop_skips: List[LoopSkip] = Field(default_factory=list)
    """
    Loop (+1) and skip (-1) modifications for this helix.

    Keyed by absolute bp index within the helix. The list may contain at most
    one entry per bp index. Entries must be sorted by bp_index ascending.
    Modifications affect both strands at the given bp position.
    See LoopSkip for the physical mechanism.
    """


class LoopSkip(BaseModel):
    """
    A single-base insertion (loop, delta=+1) or deletion (skip, delta=-1)
    at a specific bp position within a helix.

    Stored at the helix level so both strands share the same modification,
    mirroring the caDNAno convention where a loop/skip at position bp_index
    affects the double-stranded column at that index.

    delta values:
        -1 : skip (deletion) — one bp absent; crossover planes see a shorter
             local segment → locally overtwisted → left-handed torque + pull.
        +1 : loop (insertion) — one extra bp present; locally undertwisted
             → right-handed torque + push.

    Values outside {-1, +1} are not used.  Multiple modifications at adjacent
    bp positions are represented as separate LoopSkip entries.

    Reference: Dietz, Douglas & Shih, Science 2009.
    """
    bp_index: int     # absolute bp index within the helix (0-based)
    delta: int        # +1 = loop (insertion), -1 = skip (deletion)


class OverhangSpec(BaseModel):
    """
    Metadata for a single-stranded overhang domain.

    Overhangs are staple domains that extend beyond the double-stranded bundle
    and are therefore single-stranded.  Each overhang may carry an optional
    user-specified sequence (e.g. for toehold-mediated strand displacement).
    If sequence is None, assign_staple_sequences() fills the domain with 'N'.

    id format: ``ovhg_{source_helix_id}_{bp_index}_{5p|3p}``
    """
    id: str
    helix_id: str           # the overhang helix ID
    strand_id: str          # the parent staple strand ID
    sequence: Optional[str] = None
    label: Optional[str] = None


class Domain(BaseModel):
    """
    A contiguous run of nucleotides on one helix belonging to one strand.

    start_bp and end_bp are inclusive bp indices (0-based) within the helix.
    direction indicates whether the strand travels in the +axis or -axis
    direction through this domain.
    """
    helix_id: str
    start_bp: int
    end_bp: int
    direction: Direction
    overhang_id: Optional[str] = None  # set if this domain is a single-stranded overhang


class Strand(BaseModel):
    """
    A single DNA strand, ordered 5′ to 3′ through its domains.

    Scaffold strands are marked strand_type=StrandType.SCAFFOLD; there should
    be exactly one per design.  sequence, if provided, must have length equal
    to the total number of nucleotides in all domains.

    color, if set, is a 6-digit hex string (e.g. "#F7931E") overriding the
    default STAPLE_PALETTE assignment.  Preserved on caDNAno import/export.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domains: List[Domain] = Field(default_factory=list)
    strand_type: StrandType = StrandType.STAPLE
    sequence: Optional[str] = None
    color: Optional[str] = None   # "#RRGGBB" hex; None → use STAPLE_PALETTE
    notes: Optional[str] = None   # user-defined notes (shown in spreadsheet panel)

    @model_validator(mode='before')
    @classmethod
    def _migrate_is_scaffold(cls, data: object) -> object:
        """Migrate old is_scaffold boolean field from pre-StrandType .nadoc files."""
        if isinstance(data, dict) and 'is_scaffold' in data and 'strand_type' not in data:
            data = dict(data)
            data['strand_type'] = 'scaffold' if data.pop('is_scaffold') else 'staple'
        return data

    @field_validator('domains', mode='before')
    @classmethod
    def _drop_null_domains(cls, v: object) -> object:
        """Strip null entries that corrupt files may contain."""
        if isinstance(v, list):
            return [d for d in v if d is not None]
        return v


class Crossover(BaseModel):
    """
    A crossover connecting two domains on (potentially different) helices.

    domain_a_index and domain_b_index are indices into strand.domains for
    strand_a and strand_b respectively.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strand_a_id: str
    domain_a_index: int
    strand_b_id: str
    domain_b_index: int
    crossover_type: CrossoverType


class CrossoverBases(BaseModel):
    """
    Extra single-stranded bases looped at a crossover junction.

    Used to insert a short linker sequence (e.g. "TT") into the backbone of
    one strand at a crossover, placing those bases in the gap between helices.
    This supports CPD (cyclobutane pyrimidine dimer) and other photoproduct
    formation experiments by positioning thymines optimally for UV crosslinking.

    Only valid for SCAFFOLD and STAPLE crossovers (not HALF / nicks).

    The geometry layer places these bases along a quadratic Bézier arc between
    the two anchor nucleotides on either side of the crossover.  They carry a
    synthetic helix_id of the form ``__xb_{id}`` so they can be distinguished
    from regular design nucleotides.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    crossover_id: str           # references Crossover.id
    strand_id: str              # the strand that carries the loop bases
    sequence: str               # user-supplied, e.g. "TT" — chars in ACGTN


class PhotoproductJunction(BaseModel):
    """
    A confirmed CPD (cyclobutane pyrimidine dimer) photoproduct site imported
    from a scadnano_cpd design.  Stores the two thymine stable-IDs and the
    photoproduct type.  Not rendered by NADOC yet — preserved for future use.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    t1_stable_id: str
    t2_stable_id: str
    photoproduct_id: str = "TT-CPD"


# ── Terminal extension models ─────────────────────────────────────────────────


MODIFICATION_COLORS: dict[str, str] = {
    "cy3":     "#ff8c00",
    "cy5":     "#cc0000",
    "fam":     "#00cc00",
    "tamra":   "#cc00cc",
    "bhq1":    "#444444",
    "bhq2":    "#666666",
    "atto488": "#00ffcc",
    "atto550": "#ffaa00",
    "biotin":  "#eeeeee",
}
VALID_MODIFICATIONS = frozenset(MODIFICATION_COLORS.keys())


class StrandExtension(BaseModel):
    """
    A terminal extension on a strand's 5′ or 3′ end.

    At least one of sequence or modification must be provided.
    sequence: ACGTN bases, e.g. "TTTT"
    modification: predefined key from VALID_MODIFICATIONS, e.g. "cy3"

    The geometry layer places beads along a quadratic Bézier arc extending
    radially outward from the terminal nucleotide in XY, with a +Z bow.
    Uses synthetic helix_id ``__ext_{id}``.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strand_id: str
    end: Literal["five_prime", "three_prime"]
    sequence: Optional[str] = None      # ACGTN; None if modification-only
    modification: Optional[str] = None  # key from VALID_MODIFICATIONS
    label: Optional[str] = None

    @model_validator(mode='after')
    def _check_not_both_none(self) -> 'StrandExtension':
        if self.sequence is None and self.modification is None:
            raise ValueError("At least one of sequence or modification must be provided.")
        return self


# ── Deformation models (geometric layer, Phase 6) ─────────────────────────────


class TwistParams(BaseModel):
    """Parameters for a twist deformation segment."""
    kind: Literal['twist'] = 'twist'
    total_degrees: Optional[float] = None    # mutually exclusive with degrees_per_nm
    degrees_per_nm: Optional[float] = None   # positive = right-handed, negative = left-handed


class BendParams(BaseModel):
    """Parameters for a bend deformation segment."""
    kind: Literal['bend'] = 'bend'
    angle_deg: float = 0.0          # total arc angle between plane A and plane B; 0 = straight
    direction_deg: float = 0.0      # 0 = +X in the bundle cross-section plane


class DeformationOp(BaseModel):
    """One twist or bend applied to a segment of the bundle."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal['twist', 'bend']
    plane_a_bp: int                  # fixed plane (5′ side); must be < plane_b_bp
    plane_b_bp: int                  # mobile plane (3′ side)
    affected_helix_ids: List[str] = Field(default_factory=list)
    cluster_id: Optional[str] = None  # cluster this deformation was scoped to (display only)
    params: Annotated[Union[TwistParams, BendParams], Field(discriminator='kind')]


class DomainRef(BaseModel):
    """Reference to a single domain within a strand (strand_id + domain_index)."""
    strand_id: str
    domain_index: int


class ClusterRigidTransform(BaseModel):
    """
    A named cluster of helices (or sub-helix domains) with a persistent
    rigid-body transform.

    The transform is applied AFTER all bend/twist DeformationOps, as a
    per-helix post-step rigid displacement.

    rotation is a unit quaternion [x, y, z, w] (Three.js / scipy convention).
    translation is in nanometres.
    pivot is the world-space centroid of the cluster's deformed bounding box
    at the time the cluster was last activated; used as the rotation centre.

    When domain_ids is non-empty, only the nucleotides belonging to those
    domains are transformed; helix_ids still lists the helices involved (for
    pivot computation and backward compatibility) but the transform is applied
    at domain granularity.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Cluster"
    is_default: bool = False          # True when auto-created to contain all helices
    helix_ids: List[str] = Field(default_factory=list)
    domain_ids: List[DomainRef] = Field(default_factory=list)
    translation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    pivot: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class CameraPose(BaseModel):
    """
    A named saved camera viewpoint for animation and presentation purposes.

    Stores the full Three.js camera state so it can be restored exactly.
    position/target/up are in Three.js world space (nanometres).
    orbit_mode matches the viewport control mode at time of capture.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Camera Pose"
    position: List[float] = Field(default_factory=lambda: [6.0, 3.0, 7.0])
    target: List[float] = Field(default_factory=lambda: [0.0, 0.0, 7.0])
    up: List[float] = Field(default_factory=lambda: [0.0, 1.0, 0.0])
    fov: float = 55.0
    orbit_mode: str = "trackball"  # 'trackball' | 'turntable'


class DeformationLogEntry(BaseModel):
    """Feature log entry for a bend or twist deformation operation."""
    feature_type: Literal['deformation'] = 'deformation'
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    deformation_id: str   # references a DeformationOp.id in design.deformations
    op_snapshot: Optional[DeformationOp] = None   # full op data for seek replay


class ClusterOpLogEntry(BaseModel):
    """Feature log entry for a cluster translate/rotate operation."""
    feature_type: Literal['cluster_op'] = 'cluster_op'
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_id: str
    translation: List[float]   # absolute cluster state AFTER this op
    rotation: List[float]      # [qx, qy, qz, qw]
    pivot: List[float]


FeatureLogEntry = Annotated[
    Union[DeformationLogEntry, ClusterOpLogEntry],
    Field(discriminator='feature_type'),
]


class AnimationKeyframe(BaseModel):
    """
    A single keyframe in a DesignAnimation.

    camera_pose_id: ID of a CameraPose to transition to; None = keep current camera.
    feature_log_index: feature log position to seek to at this keyframe; None = no change.
    hold_duration_s: seconds to hold this state after arriving.
    transition_duration_s: seconds to tween from the previous keyframe into this one.
    easing: interpolation curve for the transition.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    camera_pose_id: Optional[str] = None
    feature_log_index: Optional[int] = None  # feature log position to seek to; None = no change
    hold_duration_s: float = 1.0
    transition_duration_s: float = 0.5
    easing: Literal["linear", "ease-in", "ease-out", "ease-in-out"] = "ease-in-out"


class DesignAnimation(BaseModel):
    """An ordered sequence of keyframes that can be played back or exported."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Animation"
    fps: int = 30
    loop: bool = False
    keyframes: List[AnimationKeyframe] = Field(default_factory=list)


class DesignMetadata(BaseModel):
    """Freeform metadata attached to a design."""
    name: str = "Untitled"
    description: str = ""
    author: str = ""
    created_at: str = ""
    modified_at: str = ""
    tags: List[str] = Field(default_factory=list)


class Design(BaseModel):
    """
    Top-level design object.  This is the ground truth for a DNA origami
    structure; all geometry and physics are derived from it.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    helices: List[Helix] = Field(default_factory=list)
    strands: List[Strand] = Field(default_factory=list)
    crossovers: List[Crossover] = Field(default_factory=list)
    lattice_type: LatticeType = LatticeType.HONEYCOMB
    metadata: DesignMetadata = Field(default_factory=DesignMetadata)
    deformations: List[DeformationOp] = Field(default_factory=list)
    cluster_transforms: List[ClusterRigidTransform] = Field(default_factory=list)
    overhangs: List[OverhangSpec] = Field(default_factory=list)
    crossover_bases: List[CrossoverBases] = Field(default_factory=list)
    extensions: List[StrandExtension] = Field(default_factory=list)
    photoproduct_junctions: List[PhotoproductJunction] = Field(default_factory=list)
    camera_poses: List[CameraPose] = Field(default_factory=list)
    animations: List[DesignAnimation] = Field(default_factory=list)
    feature_log: List[FeatureLogEntry] = Field(default_factory=list)
    feature_log_cursor: int = -1   # -1 = at end; ≥0 = index of last active entry

    @field_validator('feature_log', mode='before')
    @classmethod
    def _drop_checkpoint_entries(cls, v: object) -> object:
        """Strip legacy checkpoint entries from old designs (configurations removed)."""
        if isinstance(v, list):
            return [e for e in v if not (isinstance(e, dict) and e.get('feature_type') == 'checkpoint')]
        return v

    @field_validator('strands', mode='after')
    @classmethod
    def _drop_empty_strands(cls, v: list) -> list:
        """Remove strands that have no domains (can occur in corrupt files)."""
        return [s for s in v if s.domains]

    # Convenience accessor — returns the scaffold strand or None.
    def scaffold(self) -> Optional[Strand]:
        for s in self.strands:
            if s.strand_type == StrandType.SCAFFOLD:
                return s
        return None

    def copy_with(self, **overrides: object) -> "Design":
        """Return a shallow copy with specified fields replaced.

        Usage: existing_design.copy_with(helices=new_helices, strands=new_strands)
        All fields not in overrides are carried forward unchanged, including
        extensions, deformations, cluster_transforms, and any future fields.
        """
        return self.model_copy(update=overrides)

    # ── Persistence helpers ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise to a plain Python dict (JSON-safe)."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> Design:
        """Deserialise from a plain Python dict."""
        return cls.model_validate(data)

    def to_json(self, indent: int = 2) -> str:
        """Serialise to a JSON string."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, text: str) -> Design:
        """Deserialise from a JSON string."""
        return cls.model_validate(json.loads(text))


# ── Assembly / parts library models ──────────────────────────────────────────


class InterfacePoint(BaseModel):
    """
    A named connection point on a Part, expressed in the Part's local frame.
    """
    label: str
    position: Vec3
    normal: Vec3
    connection_type: ConnectionType


class FluctuationEnvelope(BaseModel):
    """
    Optional envelope describing thermal fluctuation of a Part as derived
    from XPBD or oxDNA ensemble data.  Stored as semi-axis lengths (nm) of an
    approximate ellipsoid in the Part's local frame.
    """
    semi_axes: Vec3                  # half-widths in x, y, z (nm)
    source: str = ""                 # e.g. "oxdna_50ns"


class ValidationRecord(BaseModel):
    """Audit trail of external validation runs performed on a Part."""
    oxdna_minimized: bool = False
    cando_run: bool = False
    snupi_run: bool = False
    experimental_validated: bool = False
    notes: str = ""


class Part(BaseModel):
    """
    Export wrapper for the assembly CAD layer (future use).

    A Part wraps a Design with assembly-level metadata: the coordinate frame
    in which it sits, named interface points, and a record of what validation
    has been performed.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    design: Design
    interface_points: List[InterfacePoint] = Field(default_factory=list)
    fluctuation_envelope: Optional[FluctuationEnvelope] = None
    local_frame: Mat4x4 = Field(default_factory=Mat4x4)
    validation_record: ValidationRecord = Field(default_factory=ValidationRecord)
