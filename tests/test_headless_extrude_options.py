"""Explicit lattice frames, stale guards and extrusion ownership reach native APIs."""

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import headless_build as hb, state
from backend.api.crud import (
    BundleContinuationRequest, BundleDeformedContinuationRequest,
    BundleSegmentRequest, CircleSegmentRequest,
    add_bundle_continuation, add_bundle_deformed_continuation,
    add_bundle_segment, add_circle_segment, get_deformed_frame,
)
from backend.core.circle_primitive import circle_footprint
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
from backend.core.lattice import make_bundle_design
from backend.core.lattice_frames import append_independent_bundle
from backend.core.models import BendParams, ClusterRigidTransform, DeformationOp, Design, LatticeType
from tests.automation_harness import canonical_topology, roundtrip_nadoc


def cluster_placement(design):
    return sorted((tuple(sorted(c.helix_ids)), tuple(c.translation), tuple(c.rotation), tuple(c.pivot))
                  for c in design.cluster_transforms)


def assert_geometry_and_ownership(actual, expected):
    assert canonical_topology(actual) == canonical_topology(expected)
    assert cluster_placement(actual) == cluster_placement(expected)
    for a, b in zip(actual.helices, expected.helices, strict=True):
        for key in ("positions", "axis_points", "axis_tangents", "radial_hats"):
            np.testing.assert_allclose(deformed_nucleotide_arrays(a, actual)[key],
                                       deformed_nucleotide_arrays(b, expected)[key], atol=1e-9)


def test_frame_scoped_guarded_extrude_matches_native_geometry_and_roundtrip():
    seed = append_independent_bundle(Design(), [[0, 0]], 42, translation_nm=[12, 0, 0])
    seed = append_independent_bundle(seed, [[0, 0]], 84, translation_nm=[30, 0, 0])
    results = []
    for headless in (True, False):
        with hb.scratch_session():
            state.load_design(seed.model_copy(deep=True))
            params = dict(cells=[[0, 0]], length_bp=21, offset_nm=42 * RISE, plane="XY",
                          strand_filter="both", extend_inplace=True, ligate_adjacent=True,
                          source_frame_id=seed.lattice_frames[0].id, separate_fresh_extrusions=False,
                          expected_design_id=seed.id, expected_revision=state.revision())
            assert set(params) == set(BundleContinuationRequest.model_fields)
            if headless:
                hb.extrude(**params)
            else:
                add_bundle_continuation(BundleContinuationRequest(**params))
            result = state.get_or_404().model_copy(deep=True)
            assert [h.length_bp for h in result.helices] == [63, 84]
            assert result.helices[1] == seed.helices[1]
            assert result.cluster_transforms == seed.cluster_transforms
            assert result.feature_log[-1].params == BundleContinuationRequest(**params).model_dump(mode="json")
            np.testing.assert_allclose(np.asarray(deformed_helix_axes(result)[0]["end"])
                                       - deformed_helix_axes(seed)[0]["end"], [0, 0, 21 * RISE])
            assert_geometry_and_ownership(roundtrip_nadoc(result), result)
            state.undo()
            assert_geometry_and_ownership(state.get_or_404(), seed)
            results.append(result)
    assert_geometry_and_ownership(*results)


@pytest.mark.parametrize("guard,status", [("design", 409), ("revision", 409), ("id_only", 422), ("revision_only", 422)])
def test_extrude_native_guards_are_atomic(guard, status):
    with hb.scratch_session():
        hb.create_bundle([(0, 0)], 42, lattice=LatticeType.HONEYCOMB)
        design = state.get_or_404()
        params = dict(expected_design_id=design.id, expected_revision=state.revision())
        if guard == "design":
            params["expected_design_id"] = "another-design"
        elif guard == "revision":
            params["expected_revision"] -= 1
        elif guard == "id_only":
            params.pop("expected_revision")
        else:
            params.pop("expected_design_id")
        before = design.model_dump_json()
        counters = state.revision(), state.undo_depth(), state.redo_depth()
        with pytest.raises(HTTPException) as exc:
            hb.extrude([(0, 0)], 7, 42 * RISE, **params)
        assert exc.value.status_code == status
        assert state.get_or_404().model_dump_json() == before
        assert (state.revision(), state.undo_depth(), state.redo_depth()) == counters


def _seed(kind):
    cell = (1, 0) if kind == "circle" else (0, 0)
    design = make_bundle_design([cell], 42, lattice_type=LatticeType.SQUARE)
    design = design.copy_with(cluster_transforms=[ClusterRigidTransform(
        id="existing", helix_ids=[design.helices[0].id], translation=[5, 0, 0])])
    if kind == "deformed":
        design = design.copy_with(deformations=[DeformationOp(
            type="bend", plane_a_bp=0, plane_b_bp=41,
            affected_helix_ids=[design.helices[0].id], params=BendParams(curvature_deg_per_bp=1))])
    return design


def _create(kind, separate, headless):
    options = dict(separate_fresh_extrusions=separate)
    cells = [[0, 1], [12, 12]]
    if kind == "segment":
        params = dict(cells=cells, length_bp=21, offset_nm=0, **options)
        return hb.extrude_segment(**params) if headless else add_bundle_segment(BundleSegmentRequest(**params))
    if kind == "continuation":
        params = dict(cells=cells, length_bp=21, offset_nm=0, **options)
        return hb.extrude(**params) if headless else add_bundle_continuation(BundleContinuationRequest(**params))
    if kind == "circle":
        if headless:
            return hb.circle_segment(4.8, **options)
        footprint = circle_footprint(4.8)
        return add_circle_segment(CircleSegmentRequest(cells=footprint["cells"], cell_lengths=footprint["cell_lengths"], **options))
    ref = state.get_or_404().helices[0].id
    if headless:
        return hb.bundle_deformed_continuation(cells, 21, source_bp=42, ref_helix_id=ref, **options)
    frame = get_deformed_frame(source_bp=42, ref_helix_id=ref)
    return add_bundle_deformed_continuation(BundleDeformedContinuationRequest(
        cells=cells, length_bp=21, source_bp=42, ref_helix_id=ref, **frame, **options))


@pytest.mark.parametrize("kind", ["segment", "continuation", "circle", "deformed"])
def test_fresh_extrusion_ownership_option_matches_native_placement_and_roundtrip(kind):
    seed = _seed(kind)
    ownership = []
    for separate in (True, False):
        results = []
        for headless in (True, False):
            with hb.scratch_session(LatticeType.SQUARE):
                state.load_design(seed.model_copy(deep=True))
                _create(kind, separate, headless)
                result = state.get_or_404().model_copy(deep=True)
                assert result.feature_log[-1].params["separate_fresh_extrusions"] == separate
                assert_geometry_and_ownership(roundtrip_nadoc(result), result)
                results.append(result)
        assert_geometry_and_ownership(*results)
        ownership.append(cluster_placement(results[0]))
    # This fixture exercises actual ownership differences, not just a saved flag.
    assert ownership[0] != ownership[1]
