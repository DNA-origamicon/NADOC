"""Offline comparison arithmetic and refusal tests; no native simulations."""

from types import SimpleNamespace

import numpy as np
import pytest

from experiments.namd_shell_calibration.comparison import (
    stage_times,
    statistics,
    sampling_budget,
    options,
    one,
)


def test_stage_clock_uses_actual_config_not_manifest_and_offsets_resets():
    layout = SimpleNamespace(istart=250, nsavc=250, n_frames=10, delta_ps=1.0)
    times, elapsed = stage_times(layout, {"timestep": ["4"], "run": ["2500"]}, 155.0)
    np.testing.assert_allclose(times, np.arange(156, 166))
    assert elapsed == 165
    times2, end = stage_times(layout, {"timestep": ["4"], "run": ["2500"]}, elapsed)
    assert times2[0] == 166 and end == 175
    with pytest.raises(ValueError, match="exceed"):
        stage_times(layout, {"timestep": ["4"], "run": ["500"]}, 0)
    with pytest.raises(ValueError, match="timestep mismatch"):
        stage_times(layout, {"timestep": ["2"], "run": ["2500"]}, 0)


def test_global_budget_deduplicates_but_combines_files():
    layouts = {
        "a": SimpleNamespace(frame_bytes=1024**3),
        "b": SimpleNamespace(frame_bytes=1024**3),
    }
    assert sampling_budget({"a": {0, 1}}, layouts, 3) == 2 * 1024**3
    with pytest.raises(ValueError, match="global"):
        sampling_budget({"a": {0, 1}, "b": {0}}, layouts, 3)
    with pytest.raises(ValueError, match="global"):
        sampling_budget({"a": {0}}, layouts, 10_000_000)


def test_intrinsic_ring_metrics_and_within_window_variance():
    ring = np.array([[np.cos(t), np.sin(t), 0] for t in np.arange(6) * np.pi / 3])
    reference = np.concatenate([ring, ring + [0, 0, 4]])
    p = dict(
        core_indices=list(range(12)),
        shell_indices=list(range(6)),
        alignment_indices=list(range(6)),
        atoms=[dict(key=["D", "1", "THY", "C"]) for _ in range(12)],
        inserts=[
            dict(ring_indices=list(range(6))),
            dict(ring_indices=list(range(6, 12))),
        ],
        wc_pairs=[[0, 6]],
    )
    x = np.repeat(reference[None], 5, axis=0)
    metrics, traces, _, _ = statistics(x, reference, p)
    assert metrics["core_heavy"]["median_rmsf_A"] < 1e-12
    np.testing.assert_allclose(traces["insert_0_1_distance_A"], 4)
    np.testing.assert_allclose(traces["insert_0_1_abs_normal_dot"], 1)
    moved = x @ np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) + 80
    _, other, _, _ = statistics(moved, reference, p)
    for key in traces:
        np.testing.assert_allclose(other[key], traces[key])
    # Disjoint windows have zero within-window motion despite differing means.
    pooled = np.concatenate([x, x + 10])
    assert statistics(pooled, reference, p)[0]["core_heavy"]["median_rmsf_A"] > 8
    assert statistics(x + 10, reference, p)[0]["core_heavy"]["median_rmsf_A"] < 1e-12


def test_config_requires_unambiguous_literal_value(tmp_path):
    conf = tmp_path / "run.conf"
    conf.write_text(
        "run 2500 # actual override\ntimestep 4\nparameters a\nparameters b\n"
    )
    opts = options(conf)
    assert one(opts, "RUN") == "2500"
    assert opts["parameters"] == ["a", "b"]
    with pytest.raises(ValueError, match="one literal"):
        one(opts, "parameters")


def test_reprocess_real_dcd_and_refuse_changed_plan_input(tmp_path, monkeypatch):
    from backend.core.dcd_fast import write_trajectory
    from experiments.namd_shell_calibration import comparison as c
    from experiments.namd_shell_calibration.workflow import (
        write_json,
        read_json,
        digest,
    )

    monkeypatch.setattr(
        c, "plot", lambda report, path: path.write_text("plot omitted in unit test")
    )
    xyz = np.array(
        [[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 3], [2, 0, 3], [0, 2, 3]], float
    )
    np.savez_compressed(tmp_path / "reference.npz", coordinates_A=xyz)
    sentinel = tmp_path / "source.txt"
    sentinel.write_text("immutable source")
    plan = dict(
        reference_npz_sha256=digest(tmp_path / "reference.npz"),
        source_hashes={str(sentinel): digest(sentinel)},
        alignment_indices=[0, 1, 2],
        image_edges=[[0, 1]],
        core_indices=[3, 4, 5],
        shell_indices=[3, 4, 5],
        inserts=[dict(ring_indices=[0, 1, 2]), dict(ring_indices=[3, 4, 5])],
        wc_pairs=[[0, 3]],
        atoms=[dict(key=["D", "1", "THY", f"C{i}"]) for i in range(6)],
        limitations=[],
        box=dict(min_corner=[-1] * 3, max_corner=[1] * 3, rotation=[0, 0, 0, 1]),
    )
    groups = []
    for kind, name in [
        ("control", "control_final_10ps"),
        ("reference", "reference_late_sparse"),
    ]:
        package = tmp_path / kind
        package.mkdir()
        (package / "trial.conf").write_text("wrapAll off\n")
        path = package / "trial.dcd"
        frames = [xyz + np.array([0, 0, i * 0.1]) for i in range(5)]
        write_trajectory(path, 6, frames, 5)
        plan.update(
            {
                f"{kind}_package": str(package),
                f"{kind}_indices": list(range(6)),
                f"{kind}_natoms": 6,
            }
        )
        groups.append(
            dict(
                name=name,
                kind=kind,
                blocks=[
                    dict(dcd=str(path), frames=list(range(5)), times_ps=list(range(5)))
                ],
            )
        )
    planpath = tmp_path / "plan.json"
    write_json(planpath, plan)
    recipe = tmp_path / "recipe.json"
    write_json(recipe, dict(plan=str(planpath), groups=groups, notes=[]))
    for name in ["first", "second"]:
        c.run(recipe, tmp_path / name)
    a = read_json(tmp_path / "first/comparison.json")
    b = read_json(tmp_path / "second/comparison.json")
    assert a == b
    assert (
        a["groups"]["control_final_10ps"]["metrics"]["core_heavy"]["median_rmsf_A"]
        < 1e-6
    )
    for filename, expected in read_json(tmp_path / "first/outputs.json").items():
        assert digest(tmp_path / "first" / filename) == expected
    sentinel.write_text("changed")
    with pytest.raises(ValueError, match="Plan input changed"):
        c.run(recipe, tmp_path / "changed")
    assert not (tmp_path / "changed").exists()
