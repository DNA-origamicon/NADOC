"""Complete native display parity and refusals before geometry allocation."""

from copy import deepcopy
import json

import pytest

from backend.core import design_geometry, deformation
from backend.core.models import (
    BendParams, ClusterRigidTransform, Crossover, DeformationOp, Design, Direction, Domain,
    DomainRef, ForcedLigation, HalfCrossover, Helix, LatticeFrame, LoopSkip, NucleotideTransform,
    OverhangSpec, SubDomain, SweepParams, TwistParams, Vec3,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison import project
from backend.core.part_dna_comparison_codec import unpack_records
from backend.core.part_dna_comparison_contract import MAX_SLOTS, check_scope, inventory
from tests.conftest import make_minimal_design

from tests.preview_test_limits import preview_test_scale_limits  # noqa: F401  (fixture)

# Bounding-mechanism tests use tiny fixtures at the original test-scale allowances.
pytestmark = pytest.mark.usefixtures("preview_test_scale_limits")



def small(kind="straight"):
    design = make_minimal_design(helix_length_bp=12)
    if kind == "loops":
        design.helices[0].loop_skips = [LoopSkip(bp_index=3, delta=1), LoopSkip(bp_index=8, delta=-1)]
    elif kind == "tails":
        design.strands[0].domains[0].start_bp = -3
        design.strands[0].domains[0].end_bp = 15
    elif kind == "reference":
        design.strands[1].is_reference = True
    elif kind in {"bend", "twist", "periodic"}:
        params = (TwistParams(total_degrees=30) if kind == "twist" else
                  BendParams(curvature_deg_per_bp=2, direction_deg=37,
                             polymer_circle_count=1 if kind == "periodic" else None))
        design.deformations = [DeformationOp(id="deform", type="twist" if kind == "twist" else "bend",
            plane_a_bp=1, plane_b_bp=10, affected_helix_ids=["h0"], params=params)]
        if kind == "periodic":
            design.forced_ligations = [ForcedLigation(id="seam", three_prime_helix_id="h0", three_prime_bp=11,
                three_prime_direction=Direction.FORWARD, five_prime_helix_id="h0", five_prime_bp=0,
                five_prime_direction=Direction.FORWARD, is_periodic_seam=True)]
    elif kind == "sweep":
        design.deformations = [DeformationOp(id="path", type="sweep", plane_a_bp=0, plane_b_bp=11,
            affected_helix_ids=["h0"], params=SweepParams(points_nm=[(0, 0, 0), (.5, 0, 2), (1, 0, 4)],
                origin_nm=(0, 0, 0), initial_rotation=[1, 0, 0, 0, 1, 0, 0, 0, 1],
                initial_tangent=(0, 0, 1), steps=11, path_length_nm=4.13))]
    elif kind in {"cluster", "child", "frame"}:
        design.cluster_transforms = [ClusterRigidTransform(id="parent", helix_ids=["h0"], translation=[3, 2, -1])]
        if kind == "child":
            design.cluster_transforms.append(ClusterRigidTransform(id="child", helix_ids=["h0"],
                domain_ids=[DomainRef(strand_id="stap", domain_index=0)], parent_cluster_id="parent",
                translation=[1, -2, 0], rotation=[0, 0, .6, .8]))
        if kind == "frame":
            design.lattice_frames = [LatticeFrame(id="frame", placement_cluster_id="parent")]
            design.helices[0].lattice_frame_id = "frame"
            design.helices[0].grid_pos = (0, 1)
    elif kind == "base_pose":
        design.nucleotide_transforms = [NucleotideTransform(id="residue", kind="base", helix_id="h0",
            bp_index=4, direction=Direction.REVERSE, translation=[.2, -.3, .4], rotation=[0, .6, 0, .8])]
    elif kind in {"overhang", "subdomain"}:
        design.helices.append(Helix(id="tail", axis_start=Vec3(x=2.5, y=0, z=0),
            axis_end=Vec3(x=2.5, y=0, z=2.04), length_bp=6))
        design.strands[1].domains.append(Domain(helix_id="tail", start_bp=0, end_bp=5,
            direction=Direction.FORWARD, overhang_id="oh"))
        design.overhangs = [OverhangSpec(id="oh", helix_id="tail", strand_id="stap", sequence="AAAAAA",
            rotation=[0, .6, 0, .8], translation=[.1, .2, .3], sub_domains=[SubDomain(id="sd", length_bp=6,
                rotation_theta_deg=20 if kind == "subdomain" else 0,
                rotation_phi_deg=15 if kind == "subdomain" else 0)])]
    elif kind in {"crossover", "ligation"}:
        if kind == "crossover":
            design.crossovers = [Crossover(id="xo", half_a=HalfCrossover(helix_id="h0", index=0, strand=Direction.FORWARD),
                half_b=HalfCrossover(helix_id="h0", index=0, strand=Direction.REVERSE))]
        else:
            design.forced_ligations = [ForcedLigation(id="fl", three_prime_helix_id="h0", three_prime_bp=11,
                three_prime_direction=Direction.FORWARD, five_prime_helix_id="h0", five_prime_bp=11,
                five_prime_direction=Direction.REVERSE)]
    return design


@pytest.mark.parametrize("kind", ["straight", "loops", "tails", "reference", "bend", "twist", "sweep",
                                  "cluster", "child", "frame", "base_pose", "overhang", "subdomain", "crossover", "ligation", "periodic"])
def test_exact_native_records_axes_and_source_are_preserved(kind):
    design = small(kind)
    before = design.model_dump_json()
    records = design_geometry._geometry_for_design(design)
    axes = deformation.deformed_helix_axes(design)
    axes = deformation._apply_ovhg_rotations_to_axes(design, axes, records)
    result = project(design)
    # The JSON boundary must preserve every coordinate, flag and exact owner.
    wire = json.loads(json.dumps(result, allow_nan=False))
    assert unpack_records(wire["nucleotides"]) == records
    assert result["helix_axes"] == axes
    assert result["component_version"] == 3
    assert result["representation"] == "native-full-v1"
    assert result["units"] == "nm"
    assert design.model_dump_json() == before
    lower, upper = result["bounds_nm"]["minimum"], result["bounds_nm"]["maximum"]
    assert all(lower[i] <= n["backbone_position"][i] <= upper[i] for n in records for i in range(3))
    if kind == "loops":
        assert len([n for n in records if n["bp_index"] == 3]) == 4
        assert not [n for n in records if n["bp_index"] == 8]
    if kind == "reference":
        assert any(n["is_reference"] for n in unpack_records(result["nucleotides"]))


def test_empty_source_has_a_complete_empty_component():
    value = project(Design())
    assert value["nucleotides"] == value["helix_axes"] == []
    assert value["bounds_nm"] is None


def test_display_topology_is_closed_and_does_not_reapply_geometry():
    design = small("sweep")
    design.metadata.name = "private authoring metadata"
    value = project(design)["display_topology"]
    assert set(value) == {"helices", "strands", "overhangs", "cluster_transforms", "deformations", "crossovers", "forced_ligations", "group_organization"}
    assert value["deformations"][0]["params"] == {"direction": 1, "start_step": 0}
    assert "params" not in value["helices"][0]
    assert {"direction", "grid_pos", "lattice_frame_id", "loop_skips"} <= set(value["helices"][0])
    moved = project(small("child"))["display_topology"]["cluster_transforms"]
    assert all(not {"translation", "pivot", "rotation", "opacity"} & set(item) for item in moved)


def forbid_geometry(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Admission must refuse before native geometry allocation")
    monkeypatch.setattr(design_geometry, "_geometry_for_design", fail)
    monkeypatch.setattr(deformation, "deformed_helix_axes", fail)


@pytest.mark.parametrize("kind", ["empty_helix", "remote_tail", "domain_walk", "many_insertions", "arm_gap", "selectors", "huge_id"])
def test_resource_limits_precede_native_allocation(kind, monkeypatch):
    design = small()
    if kind == "empty_helix":
        design.strands = []
        design.helices[0].length_bp = 100_000_000
    elif kind == "remote_tail":
        # One occupied remote base is cheap to count but expensive to generate.
        design.strands[0].domains[0].start_bp = design.strands[0].domains[0].end_bp = 900_000
    elif kind == "domain_walk":
        design.strands[0].domains[0].end_bp = 100_000
    elif kind == "many_insertions":
        design.helices[0].loop_skips = [LoopSkip(bp_index=3, delta=1)] * MAX_SLOTS
    elif kind == "arm_gap":
        design = small("bend")
        design.helices.append(design.helices[0].model_copy(update={"id": "remote", "bp_start": 900_000}))
    elif kind == "selectors":
        design.cluster_transforms = [ClusterRigidTransform(helix_ids=["h0"] * 513)]
    else:
        design.helices[0].id = "h" * 257
    forbid_geometry(monkeypatch)
    with pytest.raises(CommandContractError) as failure:
        project(design)
    assert failure.value.code in {"comparison_limit", "invalid_comparison_reference"}


@pytest.mark.parametrize("field", ["extensions", "overhang_connections", "overhang_bindings", "connection_versions",
    "duplexes", "flexible_connections", "flexible_segment_marks", "cluster_joints", "cluster_join_constraints",
    "photoproduct_junctions", "nanoparticle_conjugations", "nanoparticle_connection_versions", "staple_groups"])
def test_unsupported_complete_family_never_disappears(field, monkeypatch):
    # Intentional in-memory sentinel tests the closure guard before inspecting a
    # family's payload; this is not a persisted fixture or schema bypass.
    design = small().model_copy(update={field: [object()]})
    forbid_geometry(monkeypatch)
    with pytest.raises(CommandContractError, match=field) as failure:
        project(design)
    assert failure.value.code == "unsupported_comparison_scope"


@pytest.mark.parametrize("kind", ["missing_helix", "overlap", "cluster_domain", "cluster_cycle", "base_target",
                                  "crossover_target", "ligation_target", "overhang_owner", "native_source", "extra_bases", "traversal"])
def test_ambiguous_or_missing_input_never_projects_partially(kind, monkeypatch):
    design = small()
    if kind == "missing_helix":
        design.strands[0].domains[0].helix_id = "missing"
    elif kind == "overlap":
        design.strands.append(design.strands[0].model_copy(update={"id": "duplicate"}))
    elif kind == "cluster_domain":
        design = small("child")
        design.cluster_transforms[1].domain_ids[0].domain_index = 9
    elif kind == "cluster_cycle":
        design = small("child")
        design.cluster_transforms[1].parent_cluster_id = "child"
    elif kind == "base_target":
        design = small("base_pose")
        design.nucleotide_transforms[0].copy_k = 1
    elif kind == "crossover_target":
        design = small("crossover")
        design.crossovers[0].half_a.index = 99
    elif kind == "ligation_target":
        design = small("ligation")
        design.forced_ligations[0].three_prime_bp = 99
    elif kind == "overhang_owner":
        design = small("overhang")
        design.overhangs[0].strand_id = "scaf"
    elif kind == "native_source":
        design.helices[0].native_source = "imported"
    elif kind == "extra_bases":
        design = small("crossover")
        design.crossovers[0].extra_bases = "TT"
    else:
        design.strands[1].domains[0].start_bp = -1
    forbid_geometry(monkeypatch)
    with pytest.raises(CommandContractError):
        project(design)


@pytest.mark.parametrize("kind", ["missing_nucleotide", "duplicate_nucleotide", "owner", "slab", "extra_field", "missing_axis", "missing_segment"])
def test_native_output_inventory_and_authority_are_checked(kind, monkeypatch):
    design = small()
    records = deepcopy(design_geometry._geometry_for_design(design))
    axes = deepcopy(deformation.deformed_helix_axes(design))
    if kind == "missing_nucleotide":
        records.pop()
    elif kind == "duplicate_nucleotide":
        records.append(deepcopy(records[0]))
    elif kind == "owner":
        records[0]["strand_id"] = "stap"
    elif kind == "slab":
        records[0]["slab_position"][0] += 2
    elif kind == "extra_field":
        records[0]["new_layer"] = True
    elif kind == "missing_axis":
        axes.pop()
    else:
        axes[0]["segments"] = []
    monkeypatch.setattr(design_geometry, "_geometry_for_design", lambda *_: records)
    monkeypatch.setattr(deformation, "deformed_helix_axes", lambda *_: axes)
    with pytest.raises(CommandContractError):
        project(design)


def test_cheap_source_guard_has_checkpoint_boundaries():
    calls = []
    check_scope(small("child"), checkpoint=lambda: calls.append(True))
    assert len(calls) > 20


def test_inventory_proves_loop_copies_and_extended_sites():
    value = inventory(small("loops"))
    assert ("h0", 3, "FORWARD", 1) in value.sites
    assert ("h0", 8, "FORWARD", 0) not in value.sites
    value = inventory(small("tails"))
    assert ("h0", -3, "FORWARD", 0) in value.sites
    assert ("h0", 15, "FORWARD", 0) in value.sites
