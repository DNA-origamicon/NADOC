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
import uuid
from enum import Enum
from typing import List, Optional

import numpy as np
from pydantic import BaseModel, Field


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
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    axis_start: Vec3
    axis_end: Vec3
    phase_offset: float = 0.0   # radians
    length_bp: int


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


class Strand(BaseModel):
    """
    A single DNA strand, ordered 5′ to 3′ through its domains.

    scaffold strands are marked is_scaffold=True; there should be exactly one
    per design.  sequence, if provided, must have length equal to the total
    number of nucleotides in all domains.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domains: List[Domain] = Field(default_factory=list)
    is_scaffold: bool = False
    sequence: Optional[str] = None


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

    # Convenience accessor — returns the scaffold strand or None.
    def scaffold(self) -> Optional[Strand]:
        for s in self.strands:
            if s.is_scaffold:
                return s
        return None

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
