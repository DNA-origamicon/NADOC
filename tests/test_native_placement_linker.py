"""A bridge's emitted beads, virtual host, and relax objective share one frame."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.assembly_linker import _make_world_virtual_linker_helix, _world_anchor
from backend.core.assembly_linker_relax import _world_anchor_axial
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.design_geometry import _emit_bridge_nucs, _geometry_for_design
from backend.core.lattice import _linker_anchor_nuc, _make_virtual_linker_helix
from backend.core.linker_relax import (
    _arc_chord_lengths, bridge_axis_geometry, linker_anchor_nucleotide,
)
from backend.core.models import (
    BendParams, DeformationOp, Design, Direction, Domain, LatticeType, Mat4x4,
    NucleotideTransform, OverhangConnection, PartInstance, PartSourceInline,
    Strand, StrandType,
)
from backend.core.native_full_placement import SOURCE, NativePlacementError
from tests.conftest import make_minimal_design

pytestmark = pytest.mark.native_placement


def _bridge_fixture(length, cfa, cfb):
    conn = OverhangConnection(id="bridge", overhang_a_id="a_5p", overhang_b_id="b_5p",
        overhang_a_attach="free_end" if cfa else "root",
        overhang_b_attach="free_end" if cfb else "root",
        linker_type="ds", length_value=length, length_unit="bp")
    strands, records = [], []
    pa, pb, normal = np.array([3.4, -6.8, 1.3]), np.array([8.1, 2.7, 9.2]), np.array([.7, -.3, .1])
    for side, forward, point in [("a", cfa, pa), ("b", not cfb, pb)]:
        direction = Direction.FORWARD if forward else Direction.REVERSE
        bridge = Domain(helix_id="__lnk__bridge", start_bp=0 if forward else length-1,
                        end_bp=length-1 if forward else 0, direction=direction)
        strands.append(Strand(id=f"__lnk__bridge__{side}", strand_type=StrandType.LINKER,
            domains=[Domain(helix_id=side, start_bp=0, end_bp=0, direction=Direction.REVERSE), bridge]))
        records.extend([
            {"helix_id": side, "bp_index": 0, "overhang_id": f"{side}_5p", "is_five_prime": True},
            {"helix_id": side, "bp_index": 0, "strand_id": f"__lnk__bridge__{side}",
             "backbone_position": point.tolist(), "base_normal": normal.tolist()},
        ])
    return Design(strands=strands, overhang_connections=[conn]), records, pa, normal, pb


@pytest.mark.parametrize("length", [1, 8, 19])
@pytest.mark.parametrize("cfa,cfb", [(False, False), (False, True), (True, False), (True, True)])
def test_relax_distances_are_exact_emitted_native_o5_boundaries(length, cfa, cfb, native_placement_evidence):
    design, records, pa, normal, pb = _bridge_fixture(length, cfa, cfb)
    _emit_bridge_nucs(design, {}, records)
    bridge = [n for n in records if n["helix_id"] == "__lnk__bridge"]
    geometry = bridge_axis_geometry(pa, normal, pb, length, cfa, cfb)
    a = next(n for n in bridge if n["strand_id"].endswith("__a") and n["bp_index"] == 0)
    b = next(n for n in bridge if n["strand_id"].endswith("__b") and n["bp_index"] == length-1)
    actual = np.array([np.linalg.norm(np.array(a["backbone_position"])-pa),
                       np.linalg.norm(np.array(b["backbone_position"])-pb)])
    objective = _arc_chord_lengths(pa, normal, pb, length, cfa, cfb)
    native_placement_evidence(length=length, comp_first=[cfa, cfb],
        emitted_boundary_a=a["backbone_position"], emitted_boundary_b=b["backbone_position"],
        actual_gaps_nm=actual.tolist(), objective_gaps_nm=list(objective))
    np.testing.assert_array_equal(a["backbone_position"], geometry["boundary_a"])
    np.testing.assert_array_equal(b["backbone_position"], geometry["boundary_b"])
    np.testing.assert_array_equal(actual, objective)
    # Independent physical dimensions prevent an emitter/objective pair from
    # agreeing on the same retired radius or losing O5′ axial registration.
    for n in bridge:
        reverse = n["direction"] == "REVERSE"
        center = geometry["axis_start"] + geometry["fz"] * n["bp_index"] * BDNA_RISE_PER_BP
        delta = np.array(n["backbone_position"])-center
        axial = np.dot(delta, geometry["fz"])
        np.testing.assert_allclose(axial, .0156 if reverse else -.0152, rtol=0, atol=4e-15)
        np.testing.assert_allclose(np.linalg.norm(delta-axial*geometry["fz"]),
                                   .8481 if reverse else .8491, rtol=0, atol=4e-15)
        assert n["placement_source"] == SOURCE


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("comp_first", [False, True])
def test_virtual_bridge_phase_handoff_reproduces_the_emitter(lattice, comp_first, monkeypatch):
    design, records, pa, normal, pb = _bridge_fixture(8, comp_first, comp_first)
    design = design.copy_with(lattice_type=lattice)
    _emit_bridge_nucs(design, {}, records)
    expected = [n for n in records if n["helix_id"] == "__lnk__bridge"]
    conn = design.overhang_connections[0]
    monkeypatch.setattr("backend.core.lattice._linker_anchor_nuc",
        lambda _d, oh, _attach, _dom: SimpleNamespace(position=pa if oh == "a_5p" else pb,
                                                     base_normal=normal))
    helix = _make_virtual_linker_helix(design, "__lnk__bridge", 8, conn=conn, grid_pos=(11, 12))
    hosts = [helix]
    if lattice == LatticeType.HONEYCOMB:
        hosts.append(_make_world_virtual_linker_helix("__lnk__bridge", 8, pa, normal, pb,
                                                      comp_first, comp_first))
    for host in hosts:
        synthetic = design.copy_with(helices=[host], overhang_connections=[])
        actual = _geometry_for_design(synthetic, include_linker_helices=True)
        assert len(actual) == len(expected) == 16
        lookup = {(n["bp_index"], n["direction"]): n for n in actual}
        for n in expected:
            other = lookup[n["bp_index"], n["direction"]]
            for field in ("backbone_position", "base_position", "base_normal", "axis_tangent"):
                np.testing.assert_allclose(other[field], n[field], rtol=0, atol=6e-15)


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("attach", ["root", "free_end"])
def test_prospective_anchor_readers_match_full_bent_and_individually_posed_sites(lattice, attach):
    design = make_minimal_design(lattice=lattice)
    original = design.strands[0]
    oh = original.domains[0].model_copy(update={"overhang_id": "a_5p"})
    original = original.model_copy(update={"domains": [oh]})
    bp = 0 if attach == "free_end" else 41
    design = design.copy_with(strands=[original, design.strands[1]],
        deformations=[DeformationOp(type="bend", plane_a_bp=0, plane_b_bp=41,
                                   params=BendParams(curvature_deg_per_bp=1.7, direction_deg=23))],
        nucleotide_transforms=[NucleotideTransform(kind="base", helix_id="h0", bp_index=bp,
            direction=Direction.REVERSE, translation=[2, -3, 4], rotation=[0, 0, .3, .7])])
    full = next(n for n in _geometry_for_design(design) if n["bp_index"] == bp and n["direction"] == "REVERSE")
    local = _linker_anchor_nuc(design, "a_5p", attach, oh)
    np.testing.assert_array_equal(local.position, full["backbone_position"])
    np.testing.assert_array_equal(local.base_normal, full["base_normal"])
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_rotvec([.3, -.2, .7]).as_matrix()
    matrix[:3, 3] = [3, 4, 5]
    instance = PartInstance(id="part", name="test", source=PartSourceInline(design=design),
                            transform=Mat4x4(values=matrix.ravel().tolist()))
    expected = matrix[:3, :3] @ full["backbone_position"] + matrix[:3, 3]
    world = _world_anchor(design, instance, "a_5p", attach, oh)
    axial = _world_anchor_axial(design, instance, "a_5p", attach, oh)
    np.testing.assert_allclose(world[0], expected, rtol=0, atol=4e-15)
    np.testing.assert_array_equal(axial[0], world[0])
    np.testing.assert_allclose(world[1], matrix[:3, :3] @ full["base_normal"], rtol=0, atol=2e-15)


def test_bridge_uses_final_individually_transformed_anchors_once():
    design, _, *_ = _bridge_fixture(8, True, True)
    strands = []
    for i, side in enumerate(("a", "b")):
        hid = f"h{i}"
        link = design.strands[i]
        strands.append(link.model_copy(update={"domains": [
            link.domains[0].model_copy(update={"helix_id": hid}), link.domains[1]]}))
        strands.append(Strand(id=f"oh-{side}", strand_type=StrandType.STAPLE,
            domains=[Domain(helix_id=hid, start_bp=0, end_bp=0,
                            direction=Direction.FORWARD, overhang_id=f"{side}_5p")]))
    design = design.copy_with(helices=make_minimal_design(n_helices=2).helices,
        strands=strands, nucleotide_transforms=[NucleotideTransform(kind="base", helix_id="h0",
            bp_index=0, direction=Direction.REVERSE, translation=[0, 2, 3], rotation=[0, .2, 0, .8])])
    records = _geometry_for_design(design)
    conn = design.overhang_connections[0]
    a = linker_anchor_nucleotide(records, conn, "a_5p", True)
    b = linker_anchor_nucleotide(records, conn, "b_5p", False)
    geometry = bridge_axis_geometry(a["backbone_position"], a["base_normal"],
                                    b["backbone_position"], 8, True, True)
    for side, bp in [("a", 0), ("b", 7)]:
        actual = next(n for n in records if n["helix_id"] == "__lnk__bridge"
                      and n["strand_id"].endswith(f"__{side}") and n["bp_index"] == bp)
        np.testing.assert_array_equal(actual["backbone_position"], geometry[f"boundary_{side}"])


@pytest.mark.parametrize("bad", ["coincident", "parallel", "missing", "nonnumeric", "nonfinite"])
def test_invalid_bridge_frame_is_fatal_everywhere(bad):
    pa, pb, normal = np.zeros(3), np.array([0., 0., 3.]), np.array([1., 0., 0.])
    if bad == "coincident":
        pb = pa.copy()
    elif bad == "parallel":
        normal = [0., 0., 1.]
    elif bad == "missing":
        normal = None
    elif bad == "nonnumeric":
        normal = ["bad", 0, 0]
    else:
        pa = [np.nan, 0, 0]
    with pytest.raises(NativePlacementError) as caught:
        bridge_axis_geometry(pa, normal, pb, 8, True, True,
                             identity={"connection_id": "invalid-link", "overhang_a_id": "a_5p"})
    assert caught.value.details["connection_id"] == "invalid-link"
    assert caught.value.details["overhang_a_id"] == "a_5p"
    assert "anchor_a_nm" in caught.value.details
    assert "anchor_b_nm" in caught.value.details
    with pytest.raises(NativePlacementError):
        _make_world_virtual_linker_helix("__lnk__bad", 8, pa, normal, pb, True, True)


def test_missing_bridge_anchors_cannot_create_origin_or_use_other_strand():
    with pytest.raises(NativePlacementError):
        _make_virtual_linker_helix(Design(), "__lnk__bad", 8)
    design, records, *_ = _bridge_fixture(8, True, True)
    with pytest.raises(NativePlacementError, match="other strand cannot substitute"):
        linker_anchor_nucleotide([records[0]], design.overhang_connections[0], "a_5p", True)


def test_retired_bridge_placement_is_absent():
    from backend.core import linker_relax
    for name in ("_MINOR_GROOVE_RAD", "_HELIX_RADIUS_NM", "_bridge_boundary_radials"):
        assert not hasattr(linker_relax, name)
