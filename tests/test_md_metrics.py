"""MD "Graphs and Metrics" — trajectory and log measurements over a NAMD run.

The heavy PSF/DCD reconstruction (``_build_md_nadoc_ctx`` / ``_extract_md_nadoc_frame``)
is faked so these stay fast + always-on: the point is the metric ASSEMBLY (single pass,
all trajectory metrics, both domains, C1'…C1' pairing) and the route/chain glue, not the
MDAnalysis reader (covered by the env-gated heavy fixtures in test_md_trajectory.py).
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest


def _paired_bundle(n_helix=4, n_axial=12, radius=1.2, rise=0.34):
    """Straight bundle with BOTH strands at every (helix, bp) → designed base pairs.
    Returns (p_order, analytic_reference) sharing (helix, bp, direction) keys."""
    order: list[tuple] = []
    analytic: list[dict] = []
    for h in range(n_helix):
        ang = 2 * math.pi * h / n_helix
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        for i in range(n_axial):
            for d, dx in (("FORWARD", 0.0), ("REVERSE", 0.1)):
                pos = [x + dx, y, rise * i]
                order.append((h, i, d))
                analytic.append(
                    {
                        "helix_id": h,
                        "bp_index": i,
                        "direction": d,
                        "backbone_position": pos,
                    }
                )
    return order, analytic


def _install_fake_reader(monkeypatch, order, analytic, n_frames, *, c1p_offset=0.0):
    """Patch the DCD reader so md_metric_series walks synthetic frames.

    Each frame's backbone = the analytic positions (twist/curvature diff ≈ 0); each
    nucleotide's C1' = backbone + c1p_offset·ẑ, so FORWARD/REVERSE C1' sit 0.1 nm apart
    (paired) unless c1p_offset pushes them past MD_BP_CUTOFF_NM."""
    import backend.core.md_trajectory as mt

    p_nm = np.array([a["backbone_position"] for a in analytic], dtype=float)
    c1p = p_nm + np.array([0.0, 0.0, c1p_offset])

    monkeypatch.setattr(
        mt,
        "_build_md_nadoc_ctx",
        lambda *a, **k: {"p_order": order, "n_frames": n_frames},
    )

    def _fake_extract(ctx, idx, with_c1p=False):
        if with_c1p:
            return p_nm, None, c1p
        return p_nm, None

    monkeypatch.setattr(mt, "_extract_md_nadoc_frame", _fake_extract)


def test_aligned_rmsd_removes_translation_and_rotation():
    from backend.core.md_trajectory import aligned_rmsd_nm

    reference = np.asarray(
        [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 3.0]]
    )
    rotation = np.asarray([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    moved = reference @ rotation.T + np.asarray([8.0, -3.0, 2.0])

    assert aligned_rmsd_nm(moved, reference) == pytest.approx(0.0, abs=1e-12)
    moved[3, 2] += 0.5
    assert aligned_rmsd_nm(moved, reference) > 0.1


def test_md_metric_series_one_pass_all_metrics(monkeypatch):
    from backend.core.md_trajectory import md_metric_series

    order, analytic = _paired_bundle(n_axial=12)
    _install_fake_reader(monkeypatch, order, analytic, 4)

    seen: list[int] = []
    out = md_metric_series(
        "psf", [], "ref", object(), analytic, on_frame=lambda: seen.append(1)
    )
    assert out["ready"] is True
    assert out["n_frames"] == 4
    assert len(seen) == 4  # progress hook fired per frame
    for key in ("twist", "curvature", "base_pairing"):
        assert len(out[key]["temporal"]["per_frame"]) == 4
        assert out[key]["spatial"]  # non-empty profile
    assert out["rmsd"]["temporal"]["per_frame"] == [0.0] * 4
    assert out["rmsd"]["temporal"]["reference"] == "first_trajectory_frame"
    assert out["rmsd"]["spatial"] == []
    # Frames equal the analytic reference → differential twist/curvature ≈ 0.
    assert all(abs(v) < 1e-3 for v in out["twist"]["temporal"]["per_frame"])
    # Every designed pair is within the C1' cutoff → fraction 1.0.
    bp = out["base_pairing"]["temporal"]["per_frame"]
    assert all(v == pytest.approx(1.0) for v in bp)
    assert out["base_pairing"]["temporal"]["n_designed"] == 4 * 12


def test_md_metric_series_pairing_drops_when_c1p_separated(monkeypatch):
    """Push the C1' atoms apart in z so no FORWARD/REVERSE pair is within cutoff → 0."""
    from backend.core.md_trajectory import MD_BP_CUTOFF_NM, md_metric_series

    order, analytic = _paired_bundle(n_axial=12)
    # Same z-offset on every C1' keeps the pair separation... so instead offset would not
    # separate FWD/REV (they share z).  Use a large asymmetric offset via a custom reader.
    import backend.core.md_trajectory as mt

    p_nm = np.array([a["backbone_position"] for a in analytic], dtype=float)
    c1p = p_nm.copy()
    # Shove only REVERSE C1' atoms far in +z so each pair's C1'…C1' >> cutoff.
    for i, (_h, _bp, d) in enumerate(order):
        if d == "REVERSE":
            c1p[i, 2] += MD_BP_CUTOFF_NM * 5
    monkeypatch.setattr(
        mt, "_build_md_nadoc_ctx", lambda *a, **k: {"p_order": order, "n_frames": 3}
    )
    monkeypatch.setattr(
        mt,
        "_extract_md_nadoc_frame",
        lambda ctx, idx, with_c1p=False: (
            (p_nm, None, c1p) if with_c1p else (p_nm, None)
        ),
    )

    out = md_metric_series("psf", [], "ref", object(), analytic)
    assert out["ready"] is True
    assert all(
        v == pytest.approx(0.0) for v in out["base_pairing"]["temporal"]["per_frame"]
    )


def test_md_metric_series_tolerates_extra_base_inserts(monkeypatch):
    """Regression (MD 'Generate' crash): a design with crossover extra bases interleaves
    ``("__xb__", crossover_id, k)`` keys whose bp_index is a crossover id (a str, not an
    integer column).  Those ssDNA inserts reach the per-frame reference-core filter AND
    the base-pairing spatial profile; both must SKIP them, not ``int()`` them — the bug
    was ``invalid literal for int() with base 10: '<crossover-uuid>'``."""
    import backend.core.md_trajectory as mt
    from backend.core.md_trajectory import md_metric_series

    order, analytic = _paired_bundle(n_axial=12)
    xo_id = "accc07e6-a6df-431d-9090-d24cf77a8ec9"
    # Two inserts threaded in-chain at the junction, keyed like the real extra bases.
    order = order + [("__xb__", xo_id, 0), ("__xb__", xo_id, 1)]
    p_nm = np.array(
        [a["backbone_position"] for a in analytic] + [[0.0, 0.0, 0.5], [0.1, 0.0, 0.6]],
        dtype=float,
    )
    c1p = p_nm.copy()
    monkeypatch.setattr(
        mt, "_build_md_nadoc_ctx", lambda *a, **k: {"p_order": order, "n_frames": 3}
    )
    monkeypatch.setattr(
        mt,
        "_extract_md_nadoc_frame",
        lambda ctx, idx, with_c1p=False: (
            (p_nm, None, c1p) if with_c1p else (p_nm, None)
        ),
    )
    # analytic reference EXCLUDES __xb__ (core_reference_geometry drops _XB_SENTINEL).
    out = md_metric_series("psf", [], "ref", object(), analytic)  # must NOT raise
    assert out["ready"] is True
    # Inserts are ssDNA, not designed pairs, and every profile still resolves.
    assert out["base_pairing"]["temporal"]["n_designed"] == 4 * 12
    assert out["base_pairing"]["spatial"]
    assert out["twist"]["spatial"] and out["curvature"]["spatial"]


def test_filter_to_reference_core_skips_extra_base_inserts():
    """Unit pin on the crash site itself: the core filter drops non-integer bp_index
    (extra-base inserts) instead of int()-ing a crossover-id string."""
    from backend.core.oxdna_health import _filter_to_reference_core

    reference = [
        {
            "helix_id": 0,
            "bp_index": 3,
            "direction": "FORWARD",
            "backbone_position": [0.0, 0.0, 0.0],
        }
    ]
    positions = reference + [
        {
            "helix_id": "__xb__",
            "bp_index": "accc07e6-a6df-431d-9090-d24cf77a8ec9",
            "direction": 0,
            "backbone_position": [1.0, 0.0, 0.0],
        }
    ]
    core = _filter_to_reference_core(positions, reference)  # must NOT raise
    assert [p["helix_id"] for p in core] == [0]  # insert dropped


def test_md_job_chain_resolves_refit_lineage():
    from backend.api.routes_md_metrics import _md_job_chain

    root = SimpleNamespace(job_id="root", parent_job_id=None, created_at=1.0)
    c1 = SimpleNamespace(job_id="c1", parent_job_id="root", created_at=2.0)
    c2 = SimpleNamespace(job_id="c2", parent_job_id="c1", created_at=3.0)
    other = SimpleNamespace(job_id="x", parent_job_id=None, created_at=5.0)
    allj = [c2, other, root, c1]
    assert [j.job_id for j in _md_job_chain("c2", allj)] == ["root", "c1", "c2"]
    assert [j.job_id for j in _md_job_chain("root", allj)] == ["root", "c1", "c2"]
    assert [j.job_id for j in _md_job_chain("x", allj)] == ["x"]
    assert _md_job_chain("missing", allj) == []


def test_md_snapshot_design_walks_parent_chain(tmp_path, monkeypatch):
    # A production child with no snapshot of its own inherits the relaxation root's
    # frozen design.json by walking up parent_job_id — so it can be measured against the
    # design it was seeded from (the 6hbx100_noT "no NAMD trajectory" bug).
    from backend.api import routes_md
    from backend.core.md_job import new_job
    from backend.core.models import Design

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    root = new_job("demo", "p", name_stem="demo", package_subdir="pkg")
    root.save(tmp_path)
    child = new_job(
        "demo", "p", name_stem="demo", package_subdir="pkg", parent_job_id=root.job_id
    )
    child.save(tmp_path)
    grandchild = new_job(
        "demo", "p", name_stem="demo", package_subdir="pkg", parent_job_id=child.job_id
    )
    grandchild.save(tmp_path)
    # Snapshot lives ONLY on the root; neither child nor grandchild has its own.
    (root.job_dir(tmp_path) / "design.json").write_text(Design().model_dump_json())

    assert routes_md._md_snapshot_design(grandchild) is not None
    assert routes_md._md_snapshot_design(child) is not None
    assert routes_md._md_snapshot_design(root) is not None


def test_md_snapshot_design_none_when_no_lineage_snapshot(tmp_path, monkeypatch):
    from backend.api import routes_md
    from backend.core.md_job import new_job

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    root = new_job("demo", "p", name_stem="demo", package_subdir="pkg")
    root.save(tmp_path)
    child = new_job(
        "demo", "p", name_stem="demo", package_subdir="pkg", parent_job_id=root.job_id
    )
    child.save(tmp_path)
    assert routes_md._md_snapshot_design(child) is None


def test_md_metrics_route_unknown_job_404():
    from fastapi import HTTPException

    from backend.api.routes_md_metrics import MdMetricsStartRequest, start_md_metrics

    with pytest.raises(HTTPException) as ei:
        start_md_metrics("nope", MdMetricsStartRequest(scope="latest"))
    assert ei.value.status_code == 404


def test_count_md_frames_missing_files_is_zero():
    from backend.core.md_trajectory import count_md_frames

    assert count_md_frames([("s", "md", "/no/such.dcd")]) == 0
    assert count_md_frames([]) == 0


def test_namd_scalar_series_reads_energy_pressure_and_deduplicates_resume(tmp_path):
    from backend.core.namd_metrics import parse_namd_scalar_series

    header = "ETITLE: TS TOTAL PRESSURE PRESSAVG GPRESSAVG\n"
    base = tmp_path / "prod.log"
    base.write_text(
        header
        + "ENERGY: 100 -1000 8 2 3\n"
        + "ENERGY: 200 -1010 9 2.5 3.5\n"
    )
    resume = tmp_path / "prod.resume1.log"
    resume.write_text(
        header
        + "ENERGY: 200 -1011 10 2.6 3.6\n"
        + "ENERGY: 300 -1020 11 3 4\n"
    )

    out = parse_namd_scalar_series([base, resume])

    assert [s.step for s in out] == [100, 200, 300]
    assert [s.total_energy_kcal for s in out] == [-1000, -1011, -1020]
    assert [s.pressure_bar for s in out] == [2, 2.6, 3]


def test_health_card_metrics_record_persists_total_energy(tmp_path):
    import json

    from backend.core.namd_runner import _append_metrics_jsonl

    log = tmp_path / "prod.log"
    log.write_text(
        "ETITLE: TS TOTAL TEMP PRESSURE\n"
        "ENERGY: 100 -199108.1 300.5 1.2\n"
    )

    _append_metrics_jsonl(tmp_path / "output", "prod", "production", log)

    record = json.loads((tmp_path / "output" / "metrics.jsonl").read_text())
    assert record["total_energy_kcal"] == -199108.1


def test_job_scalar_series_uses_simulated_ns_and_appends_segments(tmp_path):
    from backend.api.routes_md_metrics import _job_scalar_series

    package = tmp_path / "pkg"
    package.mkdir()
    segments = [
        SimpleNamespace(name="s1", steps=200, status="done"),
        SimpleNamespace(name="s2", steps=100, status="running"),
    ]
    job = SimpleNamespace(
        segments=segments,
        live_metrics=None,
        package_dir=lambda _ws: package,
    )
    for name in ("s1", "s2"):
        (package / f"{name}.conf").write_text("timestep 4\n")
    header = "ETITLE: TS TOTAL PRESSURE PRESSAVG\n"
    (package / "s1.log").write_text(
        header + "ENERGY: 100 -1000 8 2\nENERGY: 200 -1010 9 2.5\n"
    )
    (package / "s2.log").write_text(
        header + "ENERGY: 50 -1020 10 3\nENERGY: 100 -1030 11 3.5\n"
    )

    out = _job_scalar_series(job, ["s1", "s2"], tmp_path)

    # 4 fs × 200 completed steps = 0.0008 ns before segment 2 begins.
    assert out["energy"]["x_values"] == [0.0004, 0.0008, 0.001, 0.0012]
    assert out["energy"]["per_frame"] == [-1000, -1010, -1020, -1030]
    assert out["pressure"]["per_frame"] == [2, 2.5, 3, 3.5]


def test_md_metrics_compute_includes_energy_and_pressure_result_blocks(
    tmp_path, monkeypatch
):
    from backend.api import routes_md_metrics as route
    from backend.api import skip_twist_tuning
    from backend.core import md_trajectory

    job = SimpleNamespace(job_id="j1")
    inputs = ("psf", "ref", [("prod", "production", "prod.dcd")], object())
    monkeypatch.setattr(route, "_resolve_jobs", lambda *_a: [job])
    monkeypatch.setattr(route, "_job_inputs", lambda *_a: inputs)
    monkeypatch.setattr(md_trajectory, "count_md_frames", lambda _segments: 2)
    monkeypatch.setattr(skip_twist_tuning, "core_reference_geometry", lambda _d: [])
    monkeypatch.setattr(
        md_trajectory,
        "md_metric_series",
        lambda *_a, **_k: {
            "ready": True,
            "n_frames": 2,
            "n_frames_raw": 2,
            "frame_indices": [0, 1],
            "twist": {"temporal": {"per_frame": [0, 1]}, "spatial": [[0, 0]]},
            "curvature": {
                "temporal": {"per_frame": [0, 0.1]},
                "spatial": [[0, 0]],
            },
            "base_pairing": {
                "temporal": {"per_frame": [1, 0.9], "n_designed": 10},
                "spatial": [[0, 1]],
            },
            "rmsd": {"temporal": {"per_frame": [0, 0.25]}, "spatial": []},
        },
    )
    monkeypatch.setattr(
        route,
        "_job_scalar_series",
        lambda *_a: {
            "energy": {"x_values": [0.1, 0.2], "per_frame": [-1000, -1010]},
            "pressure": {"x_values": [0.1, 0.2], "per_frame": [1.2, 0.8]},
            "duration_ns": 0.2,
        },
    )
    run_id = "scalar-result"
    route._RUNS.pop(run_id, None)

    route._compute(run_id, "j1", route.MdMetricsStartRequest(), tmp_path)

    result = route._RUNS[run_id]["result"]
    assert result["energy"]["temporal"] == {
        "per_frame": [-1000, -1010],
        "x_values": [0.1, 0.2],
        "boundaries": [{"job_id": "j1", "start_x": 0.0}],
    }
    assert result["pressure"]["temporal"]["per_frame"] == [1.2, 0.8]
    assert result["energy"]["spatial"] == []
    assert result["rmsd"]["temporal"] == {
        "per_frame": [0, 0.25],
        "frame_indices": [0, 1],
        "boundaries": [
            {
                "job_id": "j1",
                "start_frame": 0,
                "start_point": 0,
                "n_frames": 2,
                "n_frames_raw": 2,
            }
        ],
        "reference": "first_trajectory_frame_per_job",
        "selection": "designed_dsDNA_core_phosphates",
    }
