"""VR must serialize the sole native poses, including bent and split duplexes."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api.routes_vr import _serialize_scene, _view_rotation, VRCamera
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import BendParams, DeformationOp, NucleotideTransform
from backend.core.native_full_placement import NativePlacementError
from backend.core.vr_scene_contract import parse_scene_contract
from tests.conftest import make_minimal_design

pytestmark = pytest.mark.native_placement


def _vr_quantization(values):
    """The existing scene format is seven significant digits, not decimals."""
    values = np.asarray(values, dtype=float)
    decoded = np.asarray([float(format(value, ".7g")) for value in values.flat]).reshape(values.shape)
    absolute = np.abs(values)
    bounds = np.zeros(values.shape)
    nonzero = absolute > 0
    # Half a decimal unit in the last retained significant place, with two
    # binary ULPs for the decimal-to-binary conversion in the decoded float.
    bounds[nonzero] = (0.5 * np.power(10., np.floor(np.log10(absolute[nonzero])) - 6)
                       + 2 * np.spacing(absolute[nonzero]))
    return decoded, bounds


@pytest.mark.parametrize("bent", [False, True])
@pytest.mark.parametrize("moved", [False, True])
def test_vr_slab_centers_and_axes_are_exact_authoritative_poses(bent, moved, native_placement_evidence):
    design = make_minimal_design()
    if bent:
        design = design.copy_with(deformations=[DeformationOp(type="bend", plane_a_bp=5,
            plane_b_bp=35, params=BendParams(curvature_deg_per_bp=3.1, direction_deg=37))])
    if moved:
        design = design.copy_with(nucleotide_transforms=[NucleotideTransform(kind="base",
            helix_id="h0", bp_index=20, direction="REVERSE", pivot=[1, 2, 3],
            translation=[20, -4, 9], rotation=Rotation.from_rotvec([.4, -.3, .8]).as_quat().tolist())])
    rows = _geometry_for_design(design)
    camera = VRCamera(position=[12, -3, 8], target=[1, 0, 0], up=[0, 1, 0])
    view = _view_rotation(camera)
    full = parse_scene_contract(_serialize_scene(design, rows, [], camera,
        representations={"full"}, atomistic_model=SimpleNamespace(atoms=[], bonds=[])))["full"]
    observed = []
    for record in rows:
        key = f"nuc:{record['strand_id']}:{record['domain_index']}:h0:{record['bp_index']}:{record['direction']}:0:slab"
        values = np.asarray(full[key].values)
        bead_key = key.removesuffix(":slab") + ":backbone"
        actual_bead = np.asarray(full[bead_key].values[:3])
        expected_bead = view @ record["backbone_position"]
        encoded_bead, bead_bounds = _vr_quantization(expected_bead)
        expected_center = view @ record["slab_position"]
        expected_axes = (view @ Rotation.from_quat(record["slab_quaternion"]).as_matrix()
                         @ np.diag([.30, .06, .70])).T
        expected = np.concatenate((expected_center, expected_axes.ravel()))
        encoded, bounds = _vr_quantization(expected)
        observed.append({"identity": key, "expected_center_nm": expected_center.tolist(),
                         "actual_center_nm": values[:3].tolist(),
                         "expected_bead_unquantized_nm": expected_bead.tolist(),
                         "expected_bead_decoded_nm": encoded_bead.tolist(),
                         "actual_bead_decoded_nm": actual_bead.tolist(),
                         "bead_quantization_bound_nm": bead_bounds.tolist(),
                         "expected_pose_unquantized": expected.tolist(),
                         "expected_pose_decoded_7_significant_digits": encoded.tolist(),
                         "actual_pose_decoded": values[:12].tolist(),
                         "per_component_quantization_bound_nm": bounds.tolist()})
        native_placement_evidence(bent=bent, moved=moved, sites=observed[-1:])
        # This is exact file-format parity, not a widened geometric tolerance.
        np.testing.assert_array_equal(actual_bead, encoded_bead)
        assert np.all(np.abs(actual_bead - expected_bead) <= bead_bounds)
        np.testing.assert_array_equal(values[:12], encoded)
        assert np.all(np.abs(values[:12] - expected) <= bounds)
    assert len(observed) == 84


@pytest.mark.parametrize("field,value", [("placement_source", None), ("slab_position", None),
    ("placement_source", ["native-full-o5-v1"]),
    ("slab_quaternion", [0, 0, 0, 0]), ("slab_position", [float("nan"), 0, 0]),
    ("base_position", ["bad", 0, 0]), ("slab_position", ["bad", 0, 0]),
    ("slab_quaternion", ["bad", 0, 0, 1])])
def test_vr_refuses_incomplete_native_geometry(field, value):
    design = make_minimal_design()
    rows = deepcopy(_geometry_for_design(design))
    rows[0][field] = value
    with pytest.raises(NativePlacementError):
        _serialize_scene(design, rows, [], representations={"full"},
            atomistic_model=SimpleNamespace(atoms=[], bonds=[]))


def test_deleted_vr_solver_is_not_available():
    from backend.core import vr_scene_projection
    assert not hasattr(vr_scene_projection, "full_slab_reference_geometry")


@pytest.mark.parametrize("source", ["native-full-extension-v1", "chemical-modification-v1"])
def test_ordinary_native_record_cannot_bypass_authority_by_slabless_source_tag(source):
    from backend.core.native_slab_placement import authoritative_slab_pose
    record = _geometry_for_design(make_minimal_design())[0]
    record.update(placement_source=source, slab_position=None, slab_quaternion=None)
    with pytest.raises(NativePlacementError, match="explicit extension"):
        authoritative_slab_pose(record)


def test_real_extensions_and_modifications_keep_complete_identity_in_incremental_wire():
    from backend.core.models import StrandExtension
    from backend.core.design_geometry import _positions_by_helix
    from backend.core.native_slab_placement import authoritative_slab_pose
    design = make_minimal_design()
    design.extensions = [StrandExtension(id="tail", strand_id=design.strands[0].id,
        end="three_prime", sequence="TT", modification="cy3")]
    records = _geometry_for_design(design)
    slabless = [row for row in records if row.get("extension_id")]
    assert len(slabless) == 3
    buckets = _positions_by_helix(records)
    for record in slabless:
        assert authoritative_slab_pose(record) is None
        bucket = buckets[record["helix_id"]][record["direction"]]
        index = bucket["bp"].index(record["bp_index"])
        for wire, field in (("sid", "strand_id"), ("extid", "extension_id"),
                            ("ismod", "is_modification"), ("mod", "modification")):
            assert bucket[wire][index] == record[field]


@pytest.mark.parametrize("corruption", ["legacy", "shifted_base", "shifted_slab", "rotated_slab"])
def test_vr_rejects_finite_wrong_poses_even_when_tagged_as_native(corruption, native_placement_evidence):
    from backend.core.geometry import nucleotide_positions_arrays

    design = make_minimal_design()
    rows = deepcopy(_geometry_for_design(design))
    record = rows[0]
    if corruption == "legacy":
        provisional = nucleotide_positions_arrays(design.helices[0])
        for field, key in (("backbone_position", "positions"), ("base_position", "base_positions"),
                           ("base_normal", "base_normals"), ("axis_tangent", "axis_tangents")):
            record[field] = provisional[key][0].tolist()
    elif corruption == "shifted_base":
        record["base_position"][0] += 0.01
    elif corruption == "shifted_slab":
        record["slab_position"][1] += 0.01
    else:
        record["slab_quaternion"] = (Rotation.from_rotvec([0.1, 0, 0]) *
            Rotation.from_quat(record["slab_quaternion"])).as_quat().tolist()
    snapshot = deepcopy(record)
    native_placement_evidence(corruption=corruption, supplied_record=snapshot)
    with pytest.raises(NativePlacementError):
        _serialize_scene(design, rows, [], representations={"full"},
            atomistic_model=SimpleNamespace(atoms=[], bonds=[]))
    assert record == snapshot, "a consumer must reject the payload rather than repair it"


def test_quaternion_sign_does_not_change_the_authoritative_pose():
    from backend.core.native_slab_placement import authoritative_slab_pose

    record = _geometry_for_design(make_minimal_design())[0]
    center, frame = authoritative_slab_pose(record)
    record["slab_quaternion"] = (-np.asarray(record["slab_quaternion"])).tolist()
    flipped_center, flipped_frame = authoritative_slab_pose(record)
    np.testing.assert_array_equal(flipped_center, center)
    np.testing.assert_array_equal(flipped_frame, frame)
