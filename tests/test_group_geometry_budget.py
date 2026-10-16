"""Scalar expansion admission uses metadata, never geometry or serialized models."""

import pytest
from fastapi import HTTPException

from backend.api.part_group_geometry_budget import require_group_geometry_budget
from backend.core.models import (
    DeformationOp, DeformationRange, Design, Direction, Domain, ForcedLigation,
    Helix, LoopSkip, NativeResidue, OverhangConnection, Strand, StrandExtension,
    SweepParams, TwistParams, Vec3,
)


def source(*, length=10, start=0):
    helix = Helix(id="h", axis_start=Vec3(x=0, y=0, z=0),
                  axis_end=Vec3(x=0, y=0, z=3), length_bp=length, bp_start=start)
    domain = Domain(helix_id="h", start_bp=start, end_bp=start + length - 1,
                    direction=Direction.FORWARD)
    return Design(helices=[helix], strands=[Strand(id="s", domains=[domain])])


def refused(design, *, max_work=50_000, code="group_geometry_limit"):
    with pytest.raises(HTTPException) as caught:
        require_group_geometry_budget(design, max_work=max_work)
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == code


def test_budget_never_serializes_or_builds_native_geometry_and_leaves_input_unchanged(monkeypatch):
    from backend.core import design_geometry, geometry, sweep_path

    design = source()
    before = design.model_dump(mode="json")

    def unexpected(*_args, **_kwargs):
        pytest.fail("Metadata admission reached molecular work or serialization")

    with monkeypatch.context() as patch:
        patch.setattr(Design, "model_dump", unexpected)
        patch.setattr(Design, "model_dump_json", unexpected)
        patch.setattr(geometry, "nucleotide_positions_arrays", unexpected)
        patch.setattr(design_geometry, "fitting_geometry", unexpected)
        patch.setattr(sweep_path, "path_table", unexpected)
        report = require_group_geometry_budget(design)
    assert report["estimated_work"] == 20 and report["maximum_work"] == 50_000
    assert design.model_dump(mode="json") == before


def test_nominal_unoccupied_complement_arrays_obey_inclusive_boundary():
    design = source(length=25_000).copy_with(strands=[])
    assert require_group_geometry_budget(design)["estimated_work"] == 50_000
    refused(design.copy_with(helices=[design.helices[0].model_copy(update={"length_bp": 25_001})]))


@pytest.mark.parametrize("endpoint", [-1_000_000, 1_000_000])
def test_sparse_single_site_domain_still_charges_intervening_array_gap(endpoint):
    design = source(length=1)
    domain = design.strands[0].domains[0].model_copy(update={"start_bp": endpoint, "end_bp": endpoint})
    refused(design.copy_with(strands=[design.strands[0].model_copy(update={"domains": [domain]})]))


def test_negative_global_addresses_are_not_confused_with_array_length():
    design = source(length=10, start=-5)
    domain = design.strands[0].domains[0].model_copy(update={"start_bp": -15, "end_bp": -15})
    result = require_group_geometry_budget(design.copy_with(
        strands=[design.strands[0].model_copy(update={"domains": [domain]})]))
    assert result["helix_work"] == 40


def test_repeated_domain_emissions_and_duplicate_positive_loop_descriptors_are_charged():
    design = source(length=1)
    helix = design.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=0, delta=1)] * 2})
    strand = design.strands[0].model_copy(update={"domains": [design.strands[0].domains[0]] * 10})
    design = design.copy_with(helices=[helix], strands=[strand])
    assert require_group_geometry_budget(design)["domain_work"] == 30
    refused(design, max_work=29)


def test_negative_loop_descriptors_do_not_cancel_positive_allocation_admission():
    design = source(length=1)
    helix = design.helices[0].model_copy(update={"loop_skips": [
        LoopSkip(bp_index=0, delta=10), LoopSkip(bp_index=0, delta=-10)]})
    refused(design.copy_with(helices=[helix]), max_work=21)


def test_native_residue_core_gap_is_charged_before_tail_geometry():
    design = source(length=1)
    site = NativeResidue(bp_index=1_000_000, base="A", source_residue="A1", atoms={})
    helix = design.helices[0].model_copy(update={"native_residues": [site]})
    refused(design.copy_with(helices=[helix]))


def test_extensions_modification_and_junction_insertions_share_the_total_allowance():
    design = source(length=1)
    extension = StrandExtension(strand_id="s", end="three_prime", sequence="AA", modification="cy3")
    junction = ForcedLigation(three_prime_helix_id="h", three_prime_bp=0,
        three_prime_direction=Direction.FORWARD, five_prime_helix_id="h", five_prime_bp=0,
        five_prime_direction=Direction.REVERSE, extra_bases="AAA")
    design = design.copy_with(extensions=[extension], forced_ligations=[junction])
    assert require_group_geometry_budget(design)["additional_residues"] == 6
    refused(design, max_work=7)


@pytest.mark.parametrize("unit,value", [("bp", 10.0), ("nm", 3.34)])
def test_declared_double_stranded_bridge_uses_native_length_conversion(unit, value):
    from backend.core.lattice import _length_value_to_bp

    design = source(length=1).copy_with(overhang_connections=[OverhangConnection(
        overhang_a_id="a", overhang_a_attach="root", overhang_b_id="b",
        overhang_b_attach="root", linker_type="ds", length_unit=unit, length_value=value)])
    count = 2 * _length_value_to_bp(value, unit)
    assert require_group_geometry_budget(design)["additional_residues"] == count
    refused(design, max_work=count + 1)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), -1.0], ids=["infinite", "nan", "negative"])
def test_unaccountable_bridge_scalar_has_structured_refusal(value):
    connection = OverhangConnection(overhang_a_id="a", overhang_a_attach="root",
        overhang_b_id="b", overhang_b_attach="root", linker_type="ss",
        length_unit="nm", length_value=value)
    refused(source().copy_with(overhang_connections=[connection]), code="group_geometry_scope")


def test_huge_finite_bridge_refuses_before_native_conversion_overflows(monkeypatch):
    from backend.core import lattice

    connection = OverhangConnection(overhang_a_id="a", overhang_a_attach="root",
        overhang_b_id="b", overhang_b_attach="root", linker_type="ds",
        length_unit="nm", length_value=1e308)
    monkeypatch.setattr(lattice, "_length_value_to_bp", lambda *_a: pytest.fail("Huge scalar reached conversion"))
    refused(source().copy_with(overhang_connections=[connection]))


def twist(**updates):
    return DeformationOp(type="twist", plane_a_bp=0, plane_b_bp=10,
                         params=TwistParams(total_degrees=20), **updates)


def test_separated_deformation_arms_charge_the_sparse_frame_array():
    design = source(length=1)
    distant = design.helices[0].model_copy(update={"id": "far", "bp_start": 1_000_000})
    refused(design.copy_with(helices=[*design.helices, distant], deformations=[twist()]))


def test_scoped_evaluation_charges_repeated_full_helix_partitions():
    design = source(length=1)
    ranges = [DeformationRange(helix_id="h", start_bp=0, end_bp=0,
        direction=direction) for direction in (Direction.FORWARD, Direction.REVERSE)]
    design = design.copy_with(deformations=[twist(target_ranges=ranges)])
    assert require_group_geometry_budget(design)["scope_partitions"] == 5
    refused(design, max_work=9)


def sweep(distance):
    params = SweepParams(points_nm=[(0, 0, 0), (0, 0, distance)], origin_nm=(0, 0, 0),
        initial_rotation=[1, 0, 0, 0, 1, 0, 0, 0, 1], steps=10, path_length_nm=distance)
    return DeformationOp(type="sweep", plane_a_bp=0, plane_b_bp=10, params=params)


def test_sweep_table_scalar_size_is_admitted_without_sampling(monkeypatch):
    from backend.core import sweep_path

    monkeypatch.setattr(sweep_path, "path_table", lambda *_a, **_kw: pytest.fail("Admission sampled a spline"))
    design = source(length=1).copy_with(deformations=[sweep(5)])
    assert require_group_geometry_budget(design)["path_samples"] == 101
    refused(source(length=1).copy_with(deformations=[sweep(1_000_000)]))


@pytest.mark.parametrize("field,value", [("length_bp", -1), ("bp_start", True), ("bp_start", 2**80)])
def test_malformed_in_memory_scalar_metadata_is_not_silently_coerced(field, value):
    design = source()
    refused(design.copy_with(helices=[design.helices[0].model_copy(update={field: value})]),
            code="group_geometry_scope")


def test_missing_domain_owner_and_duplicate_helix_are_explicit_scope_failures():
    design = source()
    refused(design.copy_with(helices=[]), code="group_geometry_scope")
    refused(design.copy_with(helices=design.helices * 2), code="group_geometry_scope")
