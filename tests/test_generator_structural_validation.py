"""Mandatory FEM screening must reject disconnected or unsolved generated cores."""

import pytest
from fastapi import HTTPException

from backend.core.generator_validation import check_generated_structure
from tests.conftest import make_minimal_design


def disconnected_design():
    from backend.core.lattice import make_bundle_design
    return make_bundle_design([(0, 0), (4, 4)], 42)


def test_disconnected_core_rejected_before_solver(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Disconnected structures must be rejected before solving")
    monkeypatch.setattr("backend.physics.fem_solver.predict_shape", unexpected)
    design = disconnected_design()
    with pytest.raises(ValueError, match="2 disconnected components"):
        check_generated_structure(design, [h.id for h in design.helices])


def test_real_linear_screen_and_existing_unrelated_part():
    design = disconnected_design()
    result = check_generated_structure(design, [design.helices[0].id])
    assert result["status"] == "passed"
    assert result["connected_components"] == 1
    assert result["max_rmsf_nm"] > 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_missing_or_invalid_normal_modes_do_not_pass(monkeypatch, value):
    from backend.physics import fem_solver
    design = make_minimal_design()
    mesh = fem_solver.build_fem_mesh(design)
    result = dict(
        positions=[dict(helix_id="h0", backbone_position=[0, 0, 0])],
        rmsf=[dict(helix_id=n.helix_id, rmsf_nm=value) for n in mesh.nodes],
    )
    monkeypatch.setattr(fem_solver, "predict_shape", lambda *a, **kw: result)
    with pytest.raises(ValueError, match="CanDo validation failed"):
        check_generated_structure(design, ["h0"])


def test_large_flexibility_is_explicit_warning(monkeypatch):
    from backend.physics import fem_solver
    design = make_minimal_design()
    mesh = fem_solver.build_fem_mesh(design)
    monkeypatch.setattr(fem_solver, "predict_shape", lambda *a, **kw: dict(
        positions=[dict(helix_id="h0", backbone_position=[0, 0, 0])],
        rmsf=[dict(helix_id=n.helix_id, rmsf_nm=6.0) for n in mesh.nodes],
    ))
    result = check_generated_structure(design, ["h0"])
    assert result["status"] == "warning"
    assert result["warnings"]


@pytest.mark.parametrize("outcome", ["failed", "passed", "edited"])
def test_default_generation_checks_before_commit(monkeypatch, outcome):
    from backend.api import state, routes_generate_design as routes
    from backend.api.headless_build import scratch_session
    from tests.test_two_np_generator import source
    generated = make_minimal_design()
    monkeypatch.setattr(routes, "plan_generated", lambda *a: (None, {}))
    monkeypatch.setattr(routes, "build_recorded", lambda *a: (generated, {"generated_helix_ids": ["h0"]}))
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda *a, **kw: {})
    with scratch_session():
        original = source()
        state.set_design(original)
        revision = state.revision()
        def check(snapshot, helix_ids):
            assert state.revision() == revision
            assert state.get_or_404() == original
            assert helix_ids == ["h0"]
            if outcome == "failed":
                raise ValueError("CanDo validation failed: disconnected")
            if outcome == "edited":
                edited = original.model_copy(deep=True)
                edited.metadata.name = "Concurrent edit during CanDo"
                state.set_design(edited)
            return {"status": "passed"}
        monkeypatch.setattr("backend.core.generator_validation.check_generated_structure", check)
        request = routes.GenerateRequest(expected_revision=revision)
        if outcome != "passed":
            with pytest.raises(HTTPException) as error:
                routes.generate_design(request)
            if outcome == "failed":
                assert error.value.status_code == 422
                assert state.revision() == revision
                assert state.get_or_404() == original
            else:
                assert error.value.status_code == 409
                assert state.get_or_404().metadata.name == "Concurrent edit during CanDo"
        else:
            response = routes.generate_design(request)
            assert response["generation"]["structural_validation"]["status"] == "passed"
            assert state.revision() > revision
