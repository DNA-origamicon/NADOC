"""Assembly complements must share the source part's actual native coordinates."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api.assembly import _linker_geometry_for_assembly
from backend.core.design_geometry import native_full_arrays_for_helix
from backend.core.deformation import deformed_helix_axes
from backend.core.models import (Assembly, PartInstance, PartSourceInline, Mat4x4,
    Strand, StrandType, Domain, BendParams, DeformationOp, LoopSkip, LatticeType)
from backend.core.native_slab_placement import authoritative_slab_pose, attach_native_slab_poses
from backend.core.native_full_placement import NativePlacementError
from tests.conftest import make_minimal_design

pytestmark = pytest.mark.native_placement


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("bent", [False, True])
def test_namespaced_complements_use_real_source_frames_and_loop_copies(lattice, bent, native_placement_evidence):
    source = make_minimal_design(lattice=lattice, with_staple=False)
    helix = source.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=12, delta=2)]})
    source = source.copy_with(helices=[helix], deformations=[DeformationOp(type="bend", plane_a_bp=5,
        plane_b_bp=35, params=BendParams(curvature_deg_per_bp=3.1, direction_deg=37))] if bent else [])
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_rotvec([.5, -.3, .7]).as_matrix()
    matrix[:3, 3] = [10, -3, 7]
    instance = PartInstance(id="part", source=PartSourceInline(design=source), transform=Mat4x4.from_array(matrix))
    strand = Strand(id="__lnk__test__a", strand_type=StrandType.LINKER, domains=[
        Domain(helix_id="part::h0", start_bp=41, end_bp=0, direction="REVERSE")])
    assembly = Assembly(instances=[instance], assembly_strands=[strand])
    original = source.to_json()
    geometry = _linker_geometry_for_assembly(assembly)
    records = geometry["nucleotides"]
    arrays = native_full_arrays_for_helix(helix, source)
    indices = np.flatnonzero(arrays["directions"] == 1)
    assert len(records) == len(indices) == 44
    for record, index in zip(records, indices):
        expected = matrix[:3, :3] @ arrays["positions"][index] + matrix[:3, 3]
        native_placement_evidence(identity={k:record[k] for k in ("helix_id", "bp_index", "direction", "copy_k")},
            lattice=lattice.value, bent=bent, expected_nm=expected.tolist(), actual_nm=record["backbone_position"])
        np.testing.assert_allclose(record["backbone_position"], expected, rtol=0, atol=3e-14)
        assert record["strand_id"] == strand.id
        assert record["domain_index"] == 0
        authoritative_slab_pose(record)
        expected_record = {"direction": "REVERSE", "placement_source": arrays["placement_source"],
            "backbone_position": arrays["positions"][index].tolist(),
            "base_position": arrays["base_positions"][index].tolist(),
            "base_normal": arrays["base_normals"][index].tolist(),
            "axis_tangent": arrays["axis_tangents"][index].tolist()}
        attach_native_slab_poses([expected_record])
        for field in ("base_position", "slab_position"):
            np.testing.assert_allclose(record[field], matrix[:3, :3] @ expected_record[field] + matrix[:3, 3],
                                       rtol=0, atol=3e-14)
        for field in ("base_normal", "axis_tangent"):
            np.testing.assert_allclose(record[field], matrix[:3, :3] @ expected_record[field], rtol=0, atol=3e-14)
        np.testing.assert_allclose(Rotation.from_quat(record["slab_quaternion"]).as_matrix(),
            matrix[:3, :3] @ Rotation.from_quat(expected_record["slab_quaternion"]).as_matrix(), rtol=0, atol=3e-14)
    assert [n["copy_k"] for n in records if n["bp_index"] == 12] == [0, 1, 2]
    axis = next(a for a in geometry["helix_axes"] if a["helix_id"] == "part::h0")
    source_axis = deformed_helix_axes(source)[0]
    for field in ("start", "end", "samples"):
        expected = np.asarray(source_axis[field]) @ matrix[:3, :3].T + matrix[:3, 3]
        np.testing.assert_allclose(axis[field], expected, rtol=0, atol=3e-14)
    assert axis["segments"]
    assert all(s["domain_ids"] == [{"strand_id": strand.id, "domain_index": 0}] for s in axis["segments"])
    assert source.to_json() == original  # Source topology was never modified.


@pytest.mark.parametrize("bottom_row", [[0, 0, .2, 1], [0, 0, 0, 2]])
def test_assembly_complements_reject_nonaffine_instance_matrix(bottom_row):
    source = make_minimal_design(with_staple=False)
    matrix = np.eye(4)
    matrix[3] = bottom_row
    instance = PartInstance(id="part", source=PartSourceInline(design=source), transform=Mat4x4.from_array(matrix))
    strand = Strand(id="__lnk__test__a", strand_type=StrandType.LINKER, domains=[
        Domain(helix_id="part::h0", start_bp=41, end_bp=0, direction="REVERSE")])
    with pytest.raises(NativePlacementError, match="nonrigid nucleotide transform"):
        _linker_geometry_for_assembly(Assembly(instances=[instance], assembly_strands=[strand]))
