"""
Tests for backend/core/models.py — serialisation round-trips and model invariants.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from backend.core.models import (
    ConnectionType,
    Crossover,
    CrossoverType,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    FluctuationEnvelope,
    Helix,
    InterfacePoint,
    LatticeType,
    Mat4x4,
    Part,
    Strand,
    StrandType,
    ValidationRecord,
    Vec3,
)


# ── Vec3 ───────────────────────────────────────────────────────────────────────


def test_vec3_to_array():
    v = Vec3(x=1.0, y=2.0, z=3.0)
    arr = v.to_array()
    assert arr.shape == (3,)
    np.testing.assert_array_equal(arr, [1.0, 2.0, 3.0])


def test_vec3_from_array():
    arr = np.array([4.0, 5.0, 6.0])
    v = Vec3.from_array(arr)
    assert v.x == 4.0 and v.y == 5.0 and v.z == 6.0


def test_vec3_roundtrip():
    v = Vec3(x=1.5, y=-2.5, z=0.0)
    assert Vec3.model_validate(v.model_dump()) == v


# ── Mat4x4 ─────────────────────────────────────────────────────────────────────


def test_mat4x4_identity_default():
    m = Mat4x4()
    arr = m.to_array()
    np.testing.assert_array_equal(arr, np.eye(4))


def test_mat4x4_roundtrip():
    import random
    vals = [float(i) for i in range(16)]
    m = Mat4x4(values=vals)
    m2 = Mat4x4.from_array(m.to_array())
    assert m.values == m2.values


# ── Helix ─────────────────────────────────────────────────────────────────────


def test_helix_serialise():
    h = Helix(
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=10.0),
        phase_offset=0.0,
        length_bp=30,
    )
    d = h.model_dump()
    h2 = Helix.model_validate(d)
    assert h2.id == h.id
    assert h2.length_bp == 30
    assert h2.phase_offset == 0.0


# ── Strand and Domain ──────────────────────────────────────────────────────────


def test_strand_serialise():
    domain = Domain(helix_id="h1", start_bp=0, end_bp=20, direction=Direction.FORWARD)
    strand = Strand(domains=[domain], strand_type=StrandType.SCAFFOLD)
    d = strand.model_dump()
    s2 = Strand.model_validate(d)
    assert s2.strand_type == StrandType.SCAFFOLD
    assert len(s2.domains) == 1
    assert s2.domains[0].helix_id == "h1"


# ── Design round-trip ──────────────────────────────────────────────────────────


def _minimal_design() -> Design:
    h = Helix(
        id="h1",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=7.0),
        phase_offset=0.0,
        length_bp=21,
    )
    scaffold_domain = Domain(helix_id="h1", start_bp=0, end_bp=20, direction=Direction.FORWARD)
    scaffold = Strand(id="s_scaffold", domains=[scaffold_domain], strand_type=StrandType.SCAFFOLD)
    staple_domain = Domain(helix_id="h1", start_bp=0, end_bp=20, direction=Direction.REVERSE)
    staple = Strand(id="s_staple", domains=[staple_domain], strand_type=StrandType.STAPLE)
    xo = Crossover(
        strand_a_id="s_scaffold",
        domain_a_index=0,
        strand_b_id="s_staple",
        domain_b_index=0,
        crossover_type=CrossoverType.SCAFFOLD,
    )
    return Design(
        helices=[h],
        strands=[scaffold, staple],
        crossovers=[xo],
        lattice_type=LatticeType.HONEYCOMB,
    )


def test_design_to_dict_from_dict():
    design = _minimal_design()
    d = design.to_dict()
    design2 = Design.from_dict(d)
    assert design2.id == design.id
    assert len(design2.helices) == 1
    assert len(design2.strands) == 2
    assert len(design2.crossovers) == 1


def test_design_to_json_from_json():
    design = _minimal_design()
    text = design.to_json()
    # Verify it's valid JSON.
    parsed = json.loads(text)
    assert "helices" in parsed
    # Round-trip.
    design2 = Design.from_json(text)
    assert design2.id == design.id
    assert design2.lattice_type == LatticeType.HONEYCOMB


def test_design_scaffold_accessor():
    design = _minimal_design()
    scaffold = design.scaffold()
    assert scaffold is not None
    assert scaffold.strand_type == StrandType.SCAFFOLD
    assert scaffold.id == "s_scaffold"


def test_design_no_scaffold_returns_none():
    design = Design()
    assert design.scaffold() is None


def test_design_json_is_utf8_string():
    design = _minimal_design()
    text = design.to_json()
    assert isinstance(text, str)


# ── Part ──────────────────────────────────────────────────────────────────────


def test_part_serialise():
    design = _minimal_design()
    ip = InterfacePoint(
        label="blunt_top",
        position=Vec3(x=0, y=0, z=7.0),
        normal=Vec3(x=0, y=0, z=1.0),
        connection_type=ConnectionType.BLUNT_END,
    )
    fe = FluctuationEnvelope(semi_axes=Vec3(x=0.5, y=0.5, z=1.0), source="test")
    part = Part(
        design=design,
        interface_points=[ip],
        fluctuation_envelope=fe,
    )
    d = part.model_dump()
    part2 = Part.model_validate(d)
    assert part2.id == part.id
    assert len(part2.interface_points) == 1
    assert part2.fluctuation_envelope is not None
    assert part2.fluctuation_envelope.semi_axes.x == 0.5


def test_validation_record_defaults():
    vr = ValidationRecord()
    assert not vr.oxdna_minimized
    assert not vr.cando_run
    assert not vr.snupi_run
    assert not vr.experimental_validated
