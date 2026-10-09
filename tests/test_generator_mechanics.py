"""Physics invariants, real routing budgets, native edits and validation snapshots."""

import json
import numpy as np
import pytest

from backend.core.generator_mechanics import (
    prepare_beam,
    beam_score,
    rigid_projection,
    KBT,
    EA,
)
from backend.core.models import Design, LatticeType, Mat4x4, Nanoparticle
from backend.core.two_np_generator import GeneratorSettings, scaffold_nt
from backend.core.platform_generator import plan_generated


def source():
    points = [
        (0, 0, 0),
        (56.40551466, 0, 0),
        (-7.55155434, 0, 40.35936868),
        (71.42239406, 0, 29.9640429),
    ]
    particles = []
    for point in points:
        pose = np.eye(4)
        pose[:3, 3] = point
        particles.append(Nanoparticle(diameter_nm=10, pose=Mat4x4.from_array(pose)))
    return Design(lattice_type=LatticeType.HONEYCOMB, nanoparticles=particles)


def test_axial_compliance_matches_closed_form_and_rigid_motion_is_removed():
    from backend.core.constants import BDNA_RISE_PER_BP as rise

    length = 300 * rise
    centers = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, length]])
    summary = dict(
        path_start_bp=0,
        nominal_length_bp=301,
        path=dict(station_s={0: 0.0, 1: length}, origin=[0, 0, 0], frame=np.eye(3)),
        sweep_request=dict(points_nm=[[0, 0, 0], [0, 0, length]]),
    )
    beam = prepare_beam(summary, centers, LatticeType.SQUARE, 0)
    p = [dict(cell=(r, c), start_bp=0, end_bp=300) for r in range(2) for c in range(2)]
    score = beam_score(beam, p)
    assert score["pair_variances"][0]["variance_nm2"] == pytest.approx(
        KBT * length / (4 * EA), rel=1e-8
    )
    # Unloaded end extensions spend bases without changing internal compliance.
    extended = {
        **summary,
        "path_start_bp": 21,
        "nominal_length_bp": 343,
        "sweep_request": {"points_nm": [[0, 0, 0], [0, 0, 342 * rise]]},
    }
    long_profile = [{**cell, "end_bp": 342} for cell in p]
    long_score = beam_score(
        prepare_beam(extended, centers, LatticeType.SQUARE, 0), long_profile
    )
    assert long_score["score_nm2"] == pytest.approx(score["score_nm2"], rel=1e-8)
    projection = rigid_projection(centers)
    np.testing.assert_allclose(projection @ np.tile([1.0, 2.0, 3.0], 2), 0, atol=1e-12)
    np.testing.assert_allclose(projection @ projection, projection, atol=1e-12)


@pytest.fixture(scope="module")
def reinforced():
    s = source()
    settings = GeneratorSettings(
        shape="curved-rod", pathing="interior", mechanics="variable"
    )
    c, r = plan_generated(s, settings)
    from backend.api.generated_history import build_recorded

    g, p = build_recorded(s, c, settings)
    return s, c, r, g, p


@pytest.mark.slow
def test_reinforcement_spends_scaffold_on_valid_variable_spans(reinforced):
    s, c, r, g, p = reinforced
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.validator import validate_design

    assert r["mechanics"]["improvement_fraction"] > 0.1
    assert r["mechanics"]["layers"]
    assert len({(x["start_bp"], x["end_bp"]) for x in c.summary["section_profile"]}) > 1
    assert len(c.design.scaffolds()) == 1
    assert (
        max(scaffold_nt(c.design), physical_scaffold_nt(c.design))
        <= c.summary["scaffold_size"]
    )
    assert physical_scaffold_nt(g) <= c.summary["scaffold_size"]
    assert validate_design(g).passed
    np.testing.assert_allclose(
        [x.pose.to_array()[:3, 3] for x in g.nanoparticles],
        [x.pose.to_array()[:3, 3] for x in s.nanoparticles],
    )
    assert max(p["attachment_residuals_nm"]) < 0.02
    children = [
        child
        for entry in g.feature_log
        if entry.feature_type == "routing-cluster"
        for child in entry.children
    ]
    assert any(child.op_subtype == "strand-end-resize" for child in children)
    json.dumps(r)  # Public API contains no numpy arrays or internal path objects.


def test_robust_reports_uncertainty_and_uniform_is_a_separate_comparison():
    s = source()
    _, uniform = plan_generated(
        s, GeneratorSettings(shape="curved-rod", pathing="interior", mechanics="beam")
    )
    _, robust = plan_generated(
        s, GeneratorSettings(shape="curved-rod", pathing="interior", mechanics="robust")
    )
    assert all(x["start_bp"] == 0 for x in uniform["mechanics"]["layers"])
    scores = robust["mechanics"]["predicted"]["scenarios"]
    assert len(scores) == 3
    assert robust["mechanics"]["predicted"]["score_nm2"] == max(
        x["score_nm2"] for x in scores
    )
    assert robust["mechanics"]["validation_status"] == "not_run"


def test_mechanical_sizing_rejects_unsupported_shapes():
    with pytest.raises(ValueError, match="curved rod"):
        plan_generated(source(), GeneratorSettings(mechanics="variable"))


@pytest.mark.slow
@pytest.mark.parametrize(
    "level,nonlinear", [("fem-linear", False), ("fem-nonlinear", True)]
)
def test_fem_preparation_uses_generated_snapshot(
    reinforced, tmp_path, monkeypatch, level, nonlinear
):
    from backend.core.generator_validation import prepare_validation
    from backend.core.cando_job import CandoJob
    from backend.core import cando_runner
    from types import SimpleNamespace

    monkeypatch.setattr(
        "backend.core.project_revisions.record_simulation_revision",
        lambda *a: SimpleNamespace(project_id=None, revision_id=None),
    )
    launched = []
    monkeypatch.setattr(
        cando_runner, "start_job", lambda job, workspace: launched.append(job)
    )
    g = reinforced[3]
    info, launch = prepare_validation(g, level, tmp_path)
    assert not launched
    job = CandoJob.load(info["job_id"], tmp_path)
    assert job.nonlinear == nonlinear
    saved = Design.model_validate_json(
        (job.job_dir(tmp_path) / "design.json").read_text()
    )
    assert saved.helices == g.helices
    assert job.with_rmsf and job.with_thermal_fluctuations
    launch()
    assert len(launched) == 1
    assert info["status"] == "queued"


@pytest.mark.slow
def test_oxdna_prepares_mobile_particles_and_unbiased_production(
    reinforced, tmp_path, monkeypatch
):
    from backend.core.generator_validation import prepare_validation
    from backend.core.oxdna_runner import load_stage_specs
    from backend.core import oxdna_runner
    from types import SimpleNamespace

    monkeypatch.setattr(
        "backend.core.project_revisions.record_simulation_revision",
        lambda *a: SimpleNamespace(project_id=None, revision_id=None),
    )
    monkeypatch.setattr(
        "backend.physics.oxdna_mobile_gold.find_mobile_gold_oxdna",
        lambda: "/test/oxDNA",
    )
    calls = []
    monkeypatch.setattr(oxdna_runner, "start_job", lambda *args: calls.append(args))
    info, launch = prepare_validation(reinforced[3], "oxdna", tmp_path)
    directory = tmp_path / "oxdna_jobs" / info["job_id"]
    specs = load_stage_specs(directory)
    assert specs[-1].kind == "production" and specs[-1].steps == 5_000_000
    assert not specs[-1].external_forces
    assert all(s.interaction == "DNA2GOLD" for s in specs)
    assert len({s.seed for s in specs}) == len(specs)
    manifest = json.loads((directory / "mobile_gold.json").read_text())
    assert manifest["n_cores"] == 4 and len(manifest["grafts"]) == 4
    assert not manifest["parameters_qualified"]
    assert not calls
    launch()
    assert len(calls) == 1


@pytest.mark.slow
def test_validation_launch_follows_atomic_generation_commit(reinforced, monkeypatch):
    from backend.api import state
    from backend.api.headless_build import scratch_session
    from backend.api import routes_generate_design as routes

    s, c, r, g, p = reinforced
    events = []
    monkeypatch.setattr(routes, "plan_generated", lambda *a: (c, r.copy()))
    monkeypatch.setattr(routes, "build_recorded", lambda *a: (g, p))
    monkeypatch.setattr(routes, "_design_response_with_geometry", lambda *a, **k: {})

    def prepare(snapshot, level, workspace, **kwargs):
        assert snapshot.helices == g.helices
        events.append("prepared")

        def launch():
            assert state.get_or_404().helices == g.helices
            events.append("launched")

        return dict(engine="cando", job_id="test", status="queued"), launch

    monkeypatch.setattr("backend.core.generator_validation.prepare_validation", prepare)
    with scratch_session(s.lattice_type):
        state.set_design(s)
        revision = state.revision()
        result = routes.generate_design(
            routes.GenerateRequest(
                expected_revision=revision, shape="curved-rod", mechanics="fem-linear"
            )
        )
        assert state.revision() > revision
        assert result["generation"]["validation_job"]["status"] == "queued"
    assert events == ["prepared", "launched"]
