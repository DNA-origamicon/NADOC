"""Thermal fast path must agree with the unchanged full reconstruction."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.physics.fem_solver import build_fem_mesh, deformed_positions_with_axis
from backend.physics.fem_thermal_reconstruction import (
    ThermalReconstruction,
    ensemble_statistics,
)
from tests.conftest import make_minimal_design


@pytest.mark.parametrize(
    "variant", ["plain", "loops_and_tails", "deformed", "cluster", "single_node"]
)
def test_coordinates_match_full_reconstruction_and_do_not_regenerate_geometry(
    variant, monkeypatch
):
    from backend.core.models import (
        LoopSkip,
        StrandExtension,
        DeformationOp,
        TwistParams,
        ClusterRigidTransform,
    )
    import backend.physics.fem_thermal_reconstruction as fast

    design = make_minimal_design()
    if variant == "cluster":
        design.cluster_transforms = [
            ClusterRigidTransform(
                helix_ids=["h0"],
                translation=[7, -2, 3],
                rotation=[0, 0, 0.5, 0.8660254037844386],
            )
        ]
    if variant == "loops_and_tails":
        design.helices[0].loop_skips = [
            LoopSkip(bp_index=10, delta=1),
            LoopSkip(bp_index=20, delta=-1),
        ]
        design.extensions = [
            StrandExtension(strand_id="scaf", end="five_prime", sequence="TTTT"),
            StrandExtension(strand_id="stap", end="three_prime", sequence="AAA"),
        ]
    if variant == "deformed":
        design.deformations = [
            DeformationOp(
                type="twist",
                plane_a_bp=0,
                plane_b_bp=41,
                params=TwistParams(angle_deg=20),
            )
        ]
    before = design.to_json()
    mesh = build_fem_mesh(design)
    if variant == "single_node":
        mesh.nodes = mesh.nodes[:1]
    rng = np.random.default_rng(14)
    base = rng.normal(0, 0.03, 6 * len(mesh.nodes))
    reference, _ = deformed_positions_with_axis(design, mesh, base)
    context = ThermalReconstruction(design, mesh, reference)

    def forbidden(*args, **kwargs):
        raise AssertionError("immutable geometry regenerated inside frame loop")

    monkeypatch.setattr(fast, "nucleotide_positions", forbidden)
    monkeypatch.setattr(fast, "deformed_nucleotide_positions", forbidden)
    for _ in range(3):
        u = base + rng.normal(0, 0.05, base.shape)
        expected, _ = deformed_positions_with_axis(design, mesh, u)
        assert context.keys == [
            [p["helix_id"], p["bp_index"], p["direction"], p["copy"]] for p in expected
        ]
        np.testing.assert_allclose(
            context.coordinates(u),
            [p["backbone_position"] for p in expected],
            atol=1e-11,
            rtol=0,
        )
    assert design.to_json() == before


def test_periodic_assembly_terminal_geometry_matches_full_path():
    from tests.periodic_assembly_fixture import periodic_assembly
    from backend.core.assembly_flatten import flatten_assembly
    from backend.core.models import Design

    _, assembly = periodic_assembly()
    design = Design.from_json(flatten_assembly(assembly).to_json())
    mesh = build_fem_mesh(design)
    u = np.random.default_rng(71).normal(0, 0.02, 6 * len(mesh.nodes))
    reference, _ = deformed_positions_with_axis(design, mesh, u)
    context = ThermalReconstruction(design, mesh, reference)
    assert context.followers  # includes the polymer's terminal strands/extensions
    expected, _ = deformed_positions_with_axis(design, mesh, -u)
    np.testing.assert_allclose(
        context.coordinates(-u),
        [p["backbone_position"] for p in expected],
        atol=1e-10,
        rtol=0,
    )


def test_statistics_matches_full_ensemble_with_loop_copies_and_missing_node():
    frames = np.random.default_rng(3).normal(
        size=(48, 4100 * 3)
    )  # crosses chunk boundary
    keys = [["h", i // 3, "FORWARD", i % 3] for i in range(4100)]
    nodes = [SimpleNamespace(helix_id="h", global_bp=i) for i in range(1368)]
    modal = np.full(len(nodes), 0.3)
    xyz = frames.reshape(48, -1, 3)
    point_msf = np.sum((xyz - np.mean(xyz, axis=0, keepdims=True)) ** 2, axis=2)
    bp_msf = np.empty((48, len(nodes)))
    for i in range(len(nodes)):
        cols = [j for j, key in enumerate(keys) if key[1] == i]
        bp_msf[:, i] = np.mean(point_msf[:, cols], axis=1) if cols else modal[i] ** 2
    rmsf = np.sqrt(np.mean(bp_msf, axis=0))
    target = rmsf**2
    scale = np.maximum(target, max(float(np.mean(target)), 1e-12) * 0.05)
    selected = np.argmin(np.mean(((bp_msf - target) / scale) ** 2, axis=1))
    actual, frame = ensemble_statistics(frames, keys, nodes, modal)
    np.testing.assert_allclose(actual, rmsf, atol=1e-14, rtol=0)
    assert frame == selected


def test_numeric_frames_stream_atomically_and_cancel_cleanly(tmp_path):
    from backend.core.cando_thermal_cache import write_thermal_trajectory

    path = tmp_path / "thermal.json"
    thermal = {
        "frames": np.arange(24, dtype=float).reshape(4, 6),
        "keys": [["h", 0, "FORWARD", 0]],
        "n_frames": 4,
    }
    updates = []
    write_thermal_trajectory(path, thermal, lambda f, label: updates.append((f, label)))
    expected = dict(thermal, frames=thermal["frames"].tolist())
    assert json.loads(path.read_text()) == expected
    assert len(updates) == 4 and updates[-1][0] == 1

    def cancel(*args):
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        write_thermal_trajectory(path, thermal, cancel)
    assert json.loads(path.read_text()) == expected
    assert list(tmp_path.iterdir()) == [path]


def test_native_prediction_reports_each_frame_and_matches_legacy_statistical_contract():
    from backend.physics.fem_solver import predict_shape

    updates = []
    result = predict_shape(
        make_minimal_design(helix_length_bp=8),
        nonlinear=False,
        progress_cb=lambda *args: updates.append(args),
    )
    thermal = result["thermal_trajectory"]
    assert isinstance(thermal["frames"], np.ndarray)
    assert thermal["n_frames"] == 48
    for i in range(49):
        assert any(
            label.endswith(f"· {i}/48 frames")
            for phase, _, label in updates
            if phase == "thermal"
        )
    fractions = [fraction for phase, fraction, _ in updates if phase == "thermal"]
    assert fractions == sorted(fractions) and fractions[-1] == 1
    assert any("fluctuations" in label for _, _, label in updates)
    assert any("selected thermal" in label for _, _, label in updates)
    representative = [
        p["backbone_position"] for p in thermal["representative_positions"]
    ]
    np.testing.assert_allclose(
        thermal["frames"][thermal["representative_frame"]].reshape(-1, 3),
        representative,
        atol=1e-10,
        rtol=0,
    )


def test_runner_cancels_at_progress_boundary_and_stopped_progress_is_not_stale(
    tmp_path, monkeypatch
):
    from backend.core import cando_runner as runner
    from backend.core.cando_job import new_cando_job, CandoStatus
    import backend.physics.fem_solver as solver

    job = new_cando_job("cancel", with_rmsf=True)
    runner.prepare_cando_job(make_minimal_design(), job, tmp_path)
    handle = SimpleNamespace(cancelled=False)
    monkeypatch.setitem(runner._RUNNING, job.job_id, handle)

    def prediction(*args, progress_cb, **kwargs):
        progress_cb("thermal", 0.4, "Reconstruct thermal conformations · 20/48 frames")
        handle.cancelled = True
        progress_cb("thermal", 0.5, "Reconstruct thermal conformations · 21/48 frames")
        pytest.fail("cancelled job continued after a frame boundary")

    monkeypatch.setattr(solver, "predict_shape", prediction)
    runner._run_job(job, tmp_path)
    assert job.status == CandoStatus.stopped
    progress = runner.job_progress(job, tmp_path)
    assert progress["overall"] == 0 and progress["eta_seconds"] is None
    assert not (job.job_dir(tmp_path) / "display.json").exists()


def test_statistics_retains_modal_fallback_when_no_nodes_have_drawable_columns():
    nodes = [SimpleNamespace(helix_id="h", global_bp=i) for i in range(2)]
    modal = np.array([0.2, 0.6])
    rmsf, selected = ensemble_statistics(np.empty((48, 0)), [], nodes, modal)
    np.testing.assert_allclose(rmsf, modal, atol=1e-15, rtol=0)
    assert selected == 0
