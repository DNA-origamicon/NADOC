"""Headless Sweep must preserve the native exploratory and history workflow."""

import numpy as np
import pytest
from fastapi import HTTPException

from backend.api import headless_build as hb, state
from backend.api.crud import EditFeatureBody, _seek_feature_log, edit_feature
from backend.api.routes_sweep import create_sweep, preview_sweep
from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
from backend.core.models import Design, LatticeType
from backend.core.sweep import SweepRequest
from tests.automation_harness import canonical_topology, roundtrip_nadoc


SWEEP_ID = "20000000-0000-4000-8000-000000000007"
CELLS = [(0, 0), (0, 1)]


def assert_geometry_equal(actual, expected):
    assert canonical_topology(actual) == canonical_topology(expected)
    assert actual.deformations == expected.deformations
    assert [h.id for h in actual.helices] == [h.id for h in expected.helices]
    for a, b in zip(actual.helices, expected.helices, strict=True):
        assert a.loop_skips == b.loop_skips
        aa = deformed_nucleotide_arrays(a, actual)
        bb = deformed_nucleotide_arrays(b, expected)
        for key in ("positions", "axis_points", "axis_tangents", "radial_hats"):
            np.testing.assert_allclose(aa[key], bb[key], atol=1e-9)


def assert_preview_axes(preview, design):
    for ghost, axis in zip(preview["helix_paths_nm"], deformed_helix_axes(design), strict=True):
        # Creation ghosts and evaluated axes use different bounded sampling.
        actual = axis.get("samples") or [axis["start"], axis["end"]]
        np.testing.assert_allclose(np.asarray(ghost)[[0, -1]], np.asarray(actual)[[0, -1]], atol=1e-7)


@pytest.mark.parametrize("plane,strand_filter", [("XY", "both"), ("XZ", "scaffold"), ("YZ", "staples")])
def test_full_request_matches_native_handler_geometry_and_roundtrip(plane, strand_filter):
    seed = Design(lattice_type=LatticeType.SQUARE)
    results = []
    for headless in (True, False):
        with hb.scratch_session(LatticeType.SQUARE):
            state.load_design(seed.model_copy(deep=True))
            params = dict(
                sweep_id=SWEEP_ID, cells=CELLS,
                points_nm=[[4, 2, 1], [4, 2, 11], [9, 2, 20]],
                orientations_deg=[[10, 20, 30], None, [15, 45, 60]],
                plane=plane, strand_filter=strand_filter, ligate_adjacent=False,
                source_helix_id=None, source_end="start", detach_source=True,
                expected_design_id=seed.id, expected_revision=state.revision(),
            )
            # A new request field must enter the parity fixture, not silently
            # become another headless-only omission.
            assert set(params) == set(SweepRequest.model_fields)
            before = state.get_or_404().model_dump_json()
            revision, undo = state.revision(), state.undo_depth()
            preview = hb.preview_sweep(**params) if headless else preview_sweep(SweepRequest(**params))
            assert state.get_or_404().model_dump_json() == before
            assert (state.revision(), state.undo_depth()) == (revision, undo)
            np.testing.assert_allclose(np.asarray(preview["points_nm"])[0] - preview["origin_nm"], params["points_nm"][0])
            response = hb.sweep(**params) if headless else create_sweep(SweepRequest(**params))
            design = state.get_or_404().model_copy(deep=True)
            assert response["vr_transaction"]["target_count"] == len(CELLS)
            assert design.feature_log[-1].params == {**SweepRequest(**params).model_dump(mode="json"), "_proof_version": 1}
            assert design.deformations[-1].id == "sweep_" + SWEEP_ID
            assert_preview_axes(preview, design)
            assert_geometry_equal(roundtrip_nadoc(design), design)
            results.append(design)
    assert_geometry_equal(*results)


def test_lightweight_preview_retains_native_counts_warnings_and_revision():
    with hb.scratch_session():
        params = dict(cells=[(0, i) for i in range(9)], points_nm=[[0, 0, 0], [0, 0, 5], [5, 0, 5]])
        before = state.get_or_404().model_dump_json()
        full = hb.preview_sweep(**params)
        light = hb.preview_sweep(**params, include_geometry=False)
        assert "helix_paths_nm" in full and "helix_paths_nm" not in light
        assert light["feasibility"]["status"] == "warning"
        assert light["feasibility"]["warning_segments"]
        for key in ("feasibility", "length_bp", "total_new_bp", "revision"):
            assert light[key] == full[key]
        assert state.get_or_404().model_dump_json() == before
        hb.sweep(**params)  # Native feasibility warnings allow creation.
        assert state.get_or_404().helices


@pytest.mark.parametrize("end", ["start", "end"])
def test_moved_origin_detaches_preserving_source_history_and_edit_preview(end):
    with hb.scratch_session():
        source = hb.create_bundle(CELLS, 21, lattice=LatticeType.HONEYCOMB).model_copy(deep=True)
        sign = -1 if end == "start" else 1
        hb.sweep(CELLS, [[0, 0, 0], [0, 0, sign * 10]], source_helix_id=source.helices[0].id,
                 source_end=end, ligate_adjacent=False, sweep_id=SWEEP_ID)
        attached = state.get_or_404().model_copy(deep=True)
        index = len(attached.feature_log) - 1
        source_ids = {h.id for h in source.helices}
        added_ids = {h.id for h in attached.helices} - source_ids
        assert any(len(s.domains) > 1 for s in attached.strands)
        changes = dict(points_nm=[[4, 2, 0], [0, 0, sign * 10]],
                       orientations_deg=[[15, 0, 0], [0, 0, 45]],
                       expected_design_id=attached.id, expected_revision=state.revision())
        preview = hb.preview_sweep_edit(index, **changes)
        assert preview["source_detached"]
        assert state.get_or_404() == attached
        hb.edit_sweep(index, **changes)
        detached = state.get_or_404().model_copy(deep=True)
        assert detached.feature_log[index].id == attached.feature_log[index].id
        assert detached.feature_log[index].params["sweep_id"] == SWEEP_ID
        assert detached.feature_log[index].params["detach_source"]
        assert [h.id for h in detached.helices] == [h.id for h in attached.helices]
        assert_preview_axes(preview, detached)
        for strand in detached.strands:
            ids = {d.helix_id for d in strand.domains}
            assert not (ids & source_ids and ids & added_ids)
        for h in source.helices:
            np.testing.assert_allclose(deformed_nucleotide_arrays(detached.find_helix(h.id), detached)["positions"],
                                       deformed_nucleotide_arrays(h, source)["positions"], atol=1e-9)
        restored = roundtrip_nadoc(detached)
        assert_geometry_equal(restored, detached)
        assert_geometry_equal(_seek_feature_log(restored, -1), detached)
        state.undo()
        assert_geometry_equal(state.get_or_404(), attached)
        state.redo()
        assert_geometry_equal(state.get_or_404(), detached)
        # A patch keeps the persistent detachment flag even at the old origin.
        hb.edit_sweep(index, points_nm=[[0, 0, 0], [0, 0, sign * 10]], orientations_deg=None)
        assert state.get_or_404().feature_log[index].params["detach_source"]


def test_edit_patch_matches_native_handler_and_preserves_identity_and_later_nick():
    with hb.scratch_session():
        hb.sweep(CELLS, [[0, 0, 0], [0, 0, 14]], ligate_adjacent=False, sweep_id=SWEEP_ID)
        first = state.get_or_404()
        hb.nick(first.helices[0].id, 10, "FORWARD")
        seed = state.get_or_404().model_copy(deep=True)
    changes = dict(points_nm=[[0, 0, 0], [8, 0, 28]], orientations_deg=[None, [15, 45, 60]],
                   sweep_id="20000000-0000-4000-8000-000000000008")
    results = []
    for headless in (True, False):
        with hb.scratch_session():
            state.load_design(seed.model_copy(deep=True))
            if headless:
                preview = hb.preview_sweep_edit(0, **changes)
                hb.edit_sweep(0, **changes)
            else:
                edit_feature(0, EditFeatureBody(params=changes))
            result = state.get_or_404().model_copy(deep=True)
            assert result.feature_log[0].params["sweep_id"] == SWEEP_ID
            assert [h.id for h in result.helices] == [h.id for h in seed.helices]
            assert [s.id for s in result.strands] == [s.id for s in seed.strands]
            if headless:
                assert_preview_axes(preview, result)
            assert_geometry_equal(_seek_feature_log(roundtrip_nadoc(result), -1), result)
            results.append(result)
    assert_geometry_equal(*results)


def test_edit_preview_does_not_reuse_creation_revision_guard():
    with hb.scratch_session():
        hb.sweep(CELLS, [[0, 0, 0], [0, 0, 10]], expected_design_id=state.get_or_404().id,
                 expected_revision=state.revision())
        before = state.get_or_404().model_dump_json()
        assert state.get_or_404().feature_log[0].params["expected_revision"] < state.revision()
        preview = hb.preview_sweep_edit(0, points_nm=[[0, 0, 0], [0, 0, 12]])
        assert preview["revision"] == state.revision()
        assert state.get_or_404().model_dump_json() == before
        hb.edit_sweep(0, points_nm=[[0, 0, 0], [0, 0, 12]],
                      expected_design_id=state.get_or_404().id, expected_revision=preview["revision"])
        assert_preview_axes(preview, state.get_or_404())


@pytest.mark.parametrize("operation", ["create", "preview", "edit", "preview_edit"])
@pytest.mark.parametrize("guard", ["design", "revision"])
def test_native_stale_guards_leave_design_revision_and_history_unchanged(operation, guard):
    with hb.scratch_session():
        hb.sweep([(0, 0)], [[0, 0, 0], [0, 0, 10]])
        before = state.get_or_404().model_dump_json()
        counters = state.revision(), state.undo_depth(), state.redo_depth()
        guards = dict(expected_design_id="wrong-design" if guard == "design" else state.get_or_404().id,
                      expected_revision=state.revision() if guard == "design" else state.revision() - 1)
        with pytest.raises(HTTPException) as exc:
            if operation == "create":
                hb.sweep([(2, 0)], [[0, 0, 0], [0, 0, 10]], **guards)
            elif operation == "preview":
                hb.preview_sweep([(2, 0)], [[0, 0, 0], [0, 0, 10]], **guards)
            elif operation == "edit":
                hb.edit_sweep(0, points_nm=[[0, 0, 0], [0, 0, 12]], **guards)
            else:
                hb.preview_sweep_edit(0, points_nm=[[0, 0, 0], [0, 0, 12]], **guards)
        assert exc.value.status_code == 409
        assert state.get_or_404().model_dump_json() == before
        assert (state.revision(), state.undo_depth(), state.redo_depth()) == counters


@pytest.mark.parametrize("options", [dict(unknown_option=True), dict(orientations_deg=[[0, 0, 0]]), dict(expected_revision=0)])
def test_native_request_validation_is_not_bypassed(options):
    with hb.scratch_session():
        before = state.get_or_404().model_dump_json()
        for operation in (hb.sweep, hb.preview_sweep):
            with pytest.raises(ValueError):
                operation(CELLS, [[0, 0, 0], [0, 0, 10]], **options)
        assert state.get_or_404().model_dump_json() == before


def test_edit_helpers_reject_other_feature_types_and_missing_indices():
    with hb.scratch_session():
        hb.create_bundle(CELLS, 21, lattice=LatticeType.HONEYCOMB)
        before = state.get_or_404().model_dump_json()
        for operation in (hb.edit_sweep, hb.preview_sweep_edit):
            for index, status in [(0, 422), (-1, 404), (1, 404)]:
                with pytest.raises(HTTPException) as exc:
                    operation(index, points_nm=[[0, 0, 0], [0, 0, 12]])
                assert exc.value.status_code == status
        assert state.get_or_404().model_dump_json() == before
