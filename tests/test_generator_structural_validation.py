"""CanDo remains explicit; generation retains topology and commit checks."""

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


@pytest.fixture
def no_automatic_cando(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Generate Design must not run automatic CanDo screening")

    monkeypatch.setattr(
        "backend.core.generator_validation.check_generated_structure", unexpected
    )
    monkeypatch.setattr("backend.physics.fem_solver.predict_shape", unexpected)


@pytest.mark.slow
def test_default_plan_and_generation_do_not_run_cando(monkeypatch, no_automatic_cando):
    from backend.api import state, routes_generate_design as routes
    from backend.api.headless_build import scratch_session
    from backend.core.two_np_generator import GeneratorSettings
    from tests.test_two_np_generator import source

    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda *a, **kw: {})
    stages = []
    monkeypatch.setattr(routes, "progress", lambda stage, *a: stages.append(stage))

    def unexpected_job(*args, **kwargs):
        pytest.fail("Default generation must not launch a mechanics job")

    monkeypatch.setattr(
        "backend.core.generator_validation.prepare_validation", unexpected_job
    )
    with scratch_session():
        original = source()
        state.set_design(original)
        revision = state.revision()
        plan = routes.plan_design(GeneratorSettings())
        assert plan["revision"] == revision
        assert state.get_or_404() == original
        assert "structural_validation" not in plan
        response = routes.generate_design(
            routes.GenerateRequest(expected_revision=revision)
        )
        assert "structural_validation" not in response["generation"]
        assert "validation_job" not in response["generation"]
        assert state.revision() > revision
        assert state.get_or_404().helices
        assert len(response["generation"]["connections"]) == 2
        assert max(response["generation"]["attachment_residuals_nm"]) < 0.02
    assert "Validate topology" in stages
    assert not any("CanDo" in stage for stage in stages)


@pytest.mark.parametrize("outcome", ["failed", "edited"])
def test_topology_validation_precedes_atomic_commit(
    monkeypatch, no_automatic_cando, outcome
):
    from backend.api import state, routes_generate_design as routes
    from backend.api.headless_build import scratch_session
    from backend.core.validator import ValidationReport, ValidationResult
    from tests.test_two_np_generator import source

    generated = make_minimal_design()
    monkeypatch.setattr(routes, "plan_generated", lambda *a: (None, {}))
    monkeypatch.setattr(routes, "build_recorded", lambda *a: (generated, {}))
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda *a, **kw: {})
    with scratch_session():
        original = source()
        state.set_design(original)
        revision = state.revision()

        def validate(snapshot):
            assert state.revision() == revision
            assert state.get_or_404() == original
            assert snapshot.helices == generated.helices
            if outcome == "edited":
                edited = original.model_copy(deep=True)
                edited.metadata.name = "Concurrent edit during topology validation"
                state.set_design(edited)
            return ValidationReport(
                [ValidationResult(outcome != "failed", "Generated topology")]
            )

        monkeypatch.setattr(routes, "validate_design", validate)
        with pytest.raises(HTTPException) as error:
            routes.generate_design(routes.GenerateRequest(expected_revision=revision))
        if outcome == "failed":
            assert error.value.status_code == 422
            assert state.revision() == revision
            assert state.get_or_404() == original
        else:
            assert error.value.status_code == 409
            assert state.get_or_404().metadata.name == (
                "Concurrent edit during topology validation"
            )


@pytest.mark.parametrize("mechanics", ["fem-linear", "fem-nonlinear", "oxdna"])
def test_explicit_mechanics_job_still_launches_after_commit(
    monkeypatch, no_automatic_cando, mechanics
):
    from backend.api import state, routes_generate_design as routes
    from backend.api.headless_build import scratch_session
    from tests.test_two_np_generator import source

    generated = make_minimal_design()
    monkeypatch.setattr(routes, "plan_generated", lambda *a: (None, {}))
    monkeypatch.setattr(routes, "build_recorded", lambda *a: (generated, {}))
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda *a, **kw: {})
    events = []
    with scratch_session():
        original = source()
        state.set_design(original)
        revision = state.revision()

        def prepare(snapshot, level, workspace, **kwargs):
            assert state.revision() == revision
            assert snapshot.helices == generated.helices
            assert level == mechanics
            events.append("prepared")

            def launch():
                assert state.revision() > revision
                assert state.get_or_404().helices == generated.helices
                events.append("launched")

            return dict(engine=mechanics, status="queued"), launch

        monkeypatch.setattr("backend.core.generator_validation.prepare_validation", prepare)
        response = routes.generate_design(
            routes.GenerateRequest(expected_revision=revision, mechanics=mechanics)
        )
        assert response["generation"]["validation_job"]["status"] == "queued"
        assert "structural_validation" not in response["generation"]
    assert events == ["prepared", "launched"]
