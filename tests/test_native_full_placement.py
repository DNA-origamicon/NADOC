"""Critical native DNA placement invariants: wrong geometry must never render.

These compare local physical dimensions, independent rigid transforms, and
distinct response paths. They deliberately include split partners, bends whose
endpoint chord is not their local axis, and malformed source frames.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.design_geometry import (
    _compact_geometry_from_nucleotides, _geometry_for_design,
    _positions_by_helix, _positions_for_design, apply_nucleotide_transforms_to_geometry,
)
from backend.core.geometry import nucleotide_positions_arrays
from backend.core.models import (
    BendParams, ClusterRigidTransform, DeformationOp, DeformationRange, Design,
    Direction, DomainRef, LatticeType, LoopSkip, NucleotideTransform, TwistParams,
)
from backend.core.native_full_placement import SOURCE, NativePlacementError, place_native_full
from tests.conftest import make_minimal_design


pytestmark = pytest.mark.native_placement


def test_clash_inputs_and_interior_connectors_use_exact_native_records():
    from backend.core.clash import _bead_arrays
    from backend.core.assembly_connectors import _resolve_blunt_label_local

    design = _changed_design("bend")
    helix = design.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=12, delta=2)]})
    design = design.copy_with(helices=[helix], nucleotide_transforms=[NucleotideTransform(
        kind="base", helix_id="h0", bp_index=12, direction=Direction.FORWARD,
        copy_k=0, translation=[2, 3, 4])])
    expected = _geometry_for_design(design)
    keys, actual = _bead_arrays(design)
    assert keys == [(n["helix_id"], n["bp_index"], n["direction"], n["copy_k"]) for n in expected]
    assert len(keys) == len(set(keys))
    np.testing.assert_array_equal(actual, [n["backbone_position"] for n in expected])
    record = next(n for n in expected if n["bp_index"] == 12)
    position, normal = _resolve_blunt_label_local(design, "blunt:h0:bp12")
    np.testing.assert_array_equal(position, record["backbone_position"])
    np.testing.assert_array_equal(normal, record["axis_tangent"])


def test_interior_connector_cannot_use_an_unoccupied_construction_bead():
    from backend.core.assembly_connectors import _resolve_blunt_label_local
    design = make_minimal_design(with_scaffold=False, with_staple=False)
    with pytest.raises(NativePlacementError) as caught:
        _resolve_blunt_label_local(design, "blunt:h0:bp12")
    assert caught.value.details["helix_id"] == "h0"
    assert caught.value.details["bp_index"] == 12


def _changed_design(kind, *, scoped=False, lattice=LatticeType.HONEYCOMB):
    design = make_minimal_design(lattice=lattice)
    op = DeformationOp(
        type=kind, plane_a_bp=5, plane_b_bp=35,
        params=(BendParams(curvature_deg_per_bp=3.1, direction_deg=37)
                if kind == "bend" else TwistParams(total_degrees=127)),
        target_ranges=([DeformationRange(helix_id="h0", start_bp=0, end_bp=41,
                                       direction=Direction.FORWARD)] if scoped else None),
    )
    return design.copy_with(deformations=[op])


@pytest.mark.parametrize("cell", [Direction.FORWARD, Direction.REVERSE, None])
@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_bent_sites_preserve_radii_axial_offsets_and_groove(kind, cell, native_placement_evidence):
    design = _changed_design(kind)
    helix = design.helices[0].model_copy(update={"direction": cell})
    design = design.copy_with(helices=[helix])
    sites = deformed_nucleotide_arrays(helix, design)
    actual = place_native_full(sites)
    tangent = sites["axis_tangents"]
    radial_positions = []
    for field, expected_radii, expected_offsets in [
        ("positions", [0.8491, 0.8481], [-0.0152, 0.0156]),
        ("base_positions", [0.3136, 0.3127], [0.0326, -0.0320]),
    ]:
        delta = actual[field] - sites["axis_points"]
        axial = np.sum(delta * tangent, axis=1)
        radial = delta - axial[:, None] * tangent
        radii = np.linalg.norm(radial, axis=1)
        expected = np.tile(expected_radii, len(radii) // 2)
        native_placement_evidence(
            helix_id=helix.id, deformation=kind, cell=str(cell), field=field,
            expected_radii_nm=expected.tolist(), actual_radii_nm=radii.tolist(),
            max_displacement_nm=float(np.max(abs(radii - expected))),
        )
        np.testing.assert_allclose(radii, expected, rtol=0, atol=2e-12)
        np.testing.assert_allclose(axial, np.tile(expected_offsets, len(radii) // 2), rtol=0, atol=2e-12)
        radial_positions.append(radial)
    f, r = radial_positions[0][0::2], radial_positions[0][1::2]
    angle = np.degrees(np.arctan2(
        np.sum(np.cross(f, r) * tangent[0::2], axis=1), np.sum(f * r, axis=1))) % 360
    np.testing.assert_allclose(angle, 162.79, rtol=0, atol=2e-10)


@pytest.mark.parametrize("direction", [0, 1])
def test_independently_moved_partner_carries_identical_chemical_geometry(direction):
    design = make_minimal_design()
    sites = nucleotide_positions_arrays(design.helices[0])
    baseline = place_native_full(sites)
    angle = math.radians(113)
    rotation = np.array([[math.cos(angle), 0, math.sin(angle)], [0, 1, 0],
                         [-math.sin(angle), 0, math.cos(angle)]])
    shift = np.array([9.1, -3.8, 4.2])
    mask = sites["directions"] == direction
    sites["axis_points"][mask] = sites["axis_points"][mask] @ rotation.T + shift
    for key in ("radial_hats", "axis_tangents"):
        sites[key][mask] = sites[key][mask] @ rotation.T
    # Rendering must be independent of provisional construction bead/base values.
    sites["positions"][:] = np.nan
    sites["base_positions"][:] = 1e9
    moved = place_native_full(sites)
    for key in ("positions", "base_positions"):
        np.testing.assert_allclose(moved[key][mask], baseline[key][mask] @ rotation.T + shift, rtol=0, atol=3e-14)
        np.testing.assert_array_equal(moved[key][~mask], baseline[key][~mask])
    np.testing.assert_allclose(moved["base_normals"][mask], baseline["base_normals"][mask] @ rotation.T, rtol=0, atol=3e-14)


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
def test_full_compact_and_reloaded_records_are_identical(kind, scoped, lattice):
    design = _changed_design(kind, scoped=scoped, lattice=lattice)
    full = _geometry_for_design(design)
    compact, _ = _positions_for_design(design)
    assert compact == _positions_by_helix(full)
    assert _geometry_for_design(Design.from_json(design.to_json())) == full
    wire = _compact_geometry_from_nucleotides(full)
    for hid, directions in wire.items():
        for direction, rows in directions.items():
            for field in ("bp", "bb", "bs", "bn", "at", "sp", "sq", "pv"):
                assert rows[field] == compact[hid][direction][field]
            assert set(rows["pv"]) == {SOURCE}


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_selected_strand_does_not_change_stationary_partner(kind):
    changed = _changed_design(kind, scoped=True)
    initial = changed.copy_with(deformations=[])
    before = [n for n in _geometry_for_design(initial) if n["direction"] == "REVERSE"]
    after = [n for n in _geometry_for_design(changed) if n["direction"] == "REVERSE"]
    assert before == after


def test_domain_cluster_rotation_preserves_native_placement_for_both_strands():
    design = _changed_design("bend")
    before = _geometry_for_design(design)
    angle = math.radians(73)
    q = [0.0, 0.0, math.sin(angle / 2), math.cos(angle / 2)]
    cluster = ClusterRigidTransform(helix_ids=["h0"], domain_ids=[DomainRef(strand_id="scaf", domain_index=0)],
                                    rotation=q, translation=[3, -7, 2])
    changed = design.copy_with(cluster_transforms=[cluster])
    after = _geometry_for_design(changed)
    rot = np.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    for a, b in zip(before, after):
        if a["direction"] == "REVERSE":
            assert a == b
        else:
            for field in ("backbone_position", "base_position", "slab_position"):
                np.testing.assert_allclose(b[field], rot @ a[field] + [3, -7, 2], atol=2e-12, rtol=0)


def test_loop_copies_keep_independent_sites_and_compact_parity():
    design = _changed_design("bend")
    helix = design.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=12, delta=2), LoopSkip(bp_index=20, delta=-1)]})
    design = design.copy_with(helices=[helix])
    full = _geometry_for_design(design)
    compact, _ = _positions_for_design(design)
    assert compact == _positions_by_helix(full)
    copies = [n for n in full if n["bp_index"] == 12 and n["direction"] == "FORWARD"]
    assert len(copies) == 3
    assert len({tuple(n["backbone_position"]) for n in copies}) == 3


def test_residue_transform_transports_existing_slab_and_only_its_loop_copy():
    from copy import deepcopy
    from scipy.spatial.transform import Rotation

    design = make_minimal_design()
    helix = design.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=12, delta=2)]})
    design = design.copy_with(helices=[helix])
    baseline = _geometry_for_design(design)
    transform = NucleotideTransform(kind="base", helix_id="h0", bp_index=12,
        direction=Direction.FORWARD, copy_k=1, translation=[3, 4, 5], pivot=[1, 2, 3],
        rotation=[0.3, 0.2, 0.1, 0.7])
    changed = design.copy_with(nucleotide_transforms=[transform])
    fresh = _geometry_for_design(changed)
    transported = deepcopy(baseline)
    assert apply_nucleotide_transforms_to_geometry(transported, changed) == {transform.id}
    moved = 0
    for before, after, rebuilt in zip(baseline, transported, fresh):
        for field in ("backbone_position", "base_position", "slab_position"):
            np.testing.assert_allclose(after[field], rebuilt[field], atol=2e-14, rtol=0)
        np.testing.assert_allclose(Rotation.from_quat(after["slab_quaternion"]).as_matrix(),
                                   Rotation.from_quat(rebuilt["slab_quaternion"]).as_matrix(), atol=2e-14, rtol=0)
        moved += before["backbone_position"] != after["backbone_position"]
    assert moved == 1


@pytest.mark.parametrize("missing", ["axis_points", "radial_hats", "axis_tangents", "azimuths"])
def test_missing_frame_is_a_fatal_error(missing):
    arrs = nucleotide_positions_arrays(make_minimal_design().helices[0])
    del arrs[missing]
    with pytest.raises(NativePlacementError, match="missing canonical site"):
        place_native_full(arrs)


@pytest.mark.parametrize("field", ["axis_points", "radial_hats", "axis_tangents", "azimuths", "bp_indices"])
def test_nonnumeric_site_data_uses_the_reported_integrity_error(field):
    arrs = nucleotide_positions_arrays(make_minimal_design().helices[0])
    corrupt = arrs[field].astype(object)
    corrupt.flat[0] = "not-a-coordinate"
    arrs[field] = corrupt
    with pytest.raises(NativePlacementError) as caught:
        place_native_full(arrs)
    assert caught.value.details["field"] == field
    assert caught.value.details["identity"] == "helix h0"


@pytest.mark.parametrize("corruption", ["nan", "zero", "skew", "identity", "duplicate"])
def test_corrupt_frame_is_a_fatal_error(corruption):
    arrs = nucleotide_positions_arrays(make_minimal_design().helices[0])
    if corruption == "nan":
        arrs["axis_points"][3, 1] = np.nan
    elif corruption == "zero":
        arrs["axis_tangents"][3] = 0
    elif corruption == "skew":
        arrs["radial_hats"][3] = arrs["axis_tangents"][3]
    elif corruption == "identity":
        arrs["bp_indices"][3] += 1
    else:
        arrs = place_native_full(arrs)
    with pytest.raises(NativePlacementError):
        place_native_full(arrs)


@pytest.mark.parametrize("argument", ["measured_positioning", "junction_balance"])
def test_deleted_options_fail_and_defaults_are_canonical(argument):
    design = make_minimal_design(lattice=LatticeType.SQUARE)
    with pytest.raises(NativePlacementError):
        _geometry_for_design(design, **{argument: False})
    assert _geometry_for_design(design) == _geometry_for_design(design, measured_positioning=True, junction_balance=True)


@pytest.mark.parametrize("corruption", ["missing", "legacy", "shifted"])
def test_a_source_tag_cannot_disguise_legacy_or_missing_landmarks(corruption):
    from backend.core.native_slab_placement import attach_native_slab_poses

    design = make_minimal_design()
    record = _geometry_for_design(design)[0]
    if corruption == "missing":
        del record["base_position"]
    elif corruption == "legacy":
        provisional = nucleotide_positions_arrays(design.helices[0])
        for field, key in (("backbone_position", "positions"), ("base_position", "base_positions"),
                           ("base_normal", "base_normals"), ("axis_tangent", "axis_tangents")):
            record[field] = provisional[key][0].tolist()
    else:
        record["base_position"][2] += 0.1
    assert record["placement_source"] == SOURCE
    with pytest.raises(NativePlacementError):
        attach_native_slab_poses([record])


def test_manual_benchy_entire_model_has_one_native_placement():
    path = Path("workspace/Manual_Benchy.nadoc")
    if not path.exists():
        pytest.skip("preserved local Manual_Benchy not available")
    original = path.read_bytes()
    design = Design.model_validate_json(original)
    full = _geometry_for_design(design)
    assert len(full) == 2526
    assert {n["placement_source"] for n in full} == {SOURCE}
    compact, _ = _positions_for_design(design)
    assert compact == _positions_by_helix(full)
    assert path.read_bytes() == original
