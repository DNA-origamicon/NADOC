"""Checked transform transport must retain the native slab authority's verdict."""
from copy import deepcopy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api.part_transform_projection import _check_slab_block
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import BendParams, DeformationOp, TwistParams
from backend.core.native_full_placement import NativePlacementError
from backend.core.native_slab_placement import authoritative_slab_poses, attach_native_slab_poses
from tests.conftest import make_minimal_design


def block(records):
    return np.asarray([
        [*r["backbone_position"], *r["base_position"], *r["base_normal"], *r["axis_tangent"],
         *r["slab_position"], *r["slab_quaternion"],
         *r["helical_site"]["axis_point"], *r["helical_site"]["radial_hat"],
         r["helical_site"]["azimuth_rad"], r["helical_site"]["groove_offset_rad"],
         r["helical_site"]["phase_roll_rad"]]
        for r in records
    ], dtype="<f8").reshape(-1)


def verdict(call):
    try:
        call()
    except NativePlacementError as error:
        return str(error), error.details
    return None


@pytest.mark.parametrize("kind", ["straight", "bend", "twist"])
@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
@pytest.mark.parametrize("field", ["base_position", "slab_position", "frame", "quaternion_norm"])
@pytest.mark.parametrize("factor", [.999, 1.001, 10])
def test_block_preserves_threshold_adjacent_authority(kind, direction, field, factor):
    design = make_minimal_design()
    if kind != "straight":
        design = design.copy_with(deformations=[DeformationOp(type=kind, plane_a_bp=5, plane_b_bp=35,
            params=BendParams(curvature_deg_per_bp=2, direction_deg=37) if kind == "bend"
            else TwistParams(total_degrees=127))])
    records = _geometry_for_design(design)
    target = next(r for r in records if r["direction"] == direction)
    if field == "quaternion_norm":
        target["slab_quaternion"] = (np.asarray(target["slab_quaternion"]) * (1 + factor * 1e-6)).tolist()
    elif field == "frame":
        target["slab_quaternion"] = (Rotation.from_rotvec([factor * 1e-7, 0, 0])
                                     * Rotation.from_quat(target["slab_quaternion"])).as_quat().tolist()
    elif field == "base_position":
        frame = Rotation.from_quat(target["slab_quaternion"]).as_matrix()
        target[field] = (np.asarray(target[field]) + frame[:, 0] * factor * 1e-7).tolist()
    else:
        target[field][0] += factor * 1e-7
    original = deepcopy(records)
    assert verdict(lambda: _check_slab_block(records, block(records))) == verdict(
        lambda: authoritative_slab_poses(records))
    assert records == original


def test_valid_block_uses_shared_arithmetic_without_reextracting_records(monkeypatch):
    records = _geometry_for_design(make_minimal_design())
    def unexpected(_records):
        pytest.fail("valid native block unexpectedly re-extracted the record arrays")
    monkeypatch.setattr("backend.core.native_slab_placement.authoritative_slab_poses", unexpected)
    _check_slab_block(records, block(records))


@pytest.mark.parametrize("source", ["authored-residue-c1-v1", "native-full-extension-v1", "unknown"])
def test_non_native_and_mixed_sources_preserve_original_authority(source):
    records = _geometry_for_design(make_minimal_design())
    records[0].update(placement_source=source, extension_id="extension", is_modification=False)
    if source != "unknown":
        attach_native_slab_poses(records)
    # Mixed records are deliberately outside the compact adapter's shape.
    assert verdict(lambda: _check_slab_block(records, np.empty(0))) == verdict(
        lambda: authoritative_slab_poses(records))


def test_empty_block_retains_original_authority():
    _check_slab_block([], np.empty(0))


@pytest.mark.parametrize("field,value", [
    ("direction", "unknown"), ("base_normal", [0, 0, 0]),
    ("axis_tangent", [0, 0, 0]), ("slab_quaternion", [0, 0, 0, 0]),
])
def test_invalid_block_retains_site_diagnostic(field, value):
    records = _geometry_for_design(make_minimal_design())
    records[5][field] = value
    assert verdict(lambda: _check_slab_block(records, block(records))) == verdict(
        lambda: authoritative_slab_poses(records))
