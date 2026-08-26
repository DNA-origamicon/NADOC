import json
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pytest

from backend.core import cpd_metrics
from backend.core.kimmdy_analysis import (
    aggregate_base_likelihoods,
    analyze_kimmdy_trajectory,
    parse_pair_spec,
    resolve_analysis_source,
    sample_frame_indices,
    upstream_kimmdy_propensity,
    write_kimmdy_outputs,
)
from backend.core.md_trajectory import md_photoproduct_likelihood
from tests.reciprocal_design import reciprocal_design


def _two_thymine_trajectory(tmp_path: Path) -> tuple[Path, Path]:
    universe = mda.Universe.empty(
        4,
        n_residues=2,
        n_segments=2,
        atom_resindex=np.asarray([0, 0, 1, 1]),
        residue_segindex=np.asarray([0, 1]),
        trajectory=True,
    )
    universe.add_TopologyAttr("names", ["C5", "C6", "C5", "C6"])
    universe.add_TopologyAttr("types", ["C", "C", "C", "C"])
    universe.add_TopologyAttr("elements", ["C", "C", "C", "C"])
    universe.add_TopologyAttr("resnames", ["DT", "DT"])
    universe.add_TopologyAttr("resids", [1, 1])
    universe.add_TopologyAttr("segids", ["D000", "D001"])

    close = np.asarray(
        [
            [5.0, 5.0, 5.0],
            [6.4, 5.0, 5.0],
            [5.0, 8.4, 5.0],
            [6.4, 8.4, 5.0],
        ],
        dtype=np.float32,
    )
    far = close.copy()
    far[2:, 1] = 17.0
    universe.atoms.positions = close
    universe.dimensions = [40, 40, 40, 90, 90, 90]

    topology = tmp_path / "two_t.pdb"
    trajectory = tmp_path / "two_t.dcd"
    with mda.Writer(str(topology), n_atoms=4) as writer:
        writer.write(universe.atoms)
    with mda.Writer(str(trajectory), n_atoms=4) as writer:
        for positions in (close, far):
            universe.atoms.positions = positions
            universe.dimensions = [40, 40, 40, 90, 90, 90]
            writer.write(universe.atoms)
    return topology, trajectory


def test_frame_cap_spans_the_whole_requested_interval():
    frames = sample_frame_indices(
        10_000, start=100, stop=9_100, stride=2, max_frames=10
    )
    assert frames[0] == 100 and frames[-1] == 9_099
    assert len(frames) <= 10
    assert min(np.diff(frames)) > 2


def test_explicit_pair_parser_preserves_segment_identity():
    assert parse_pair_spec("D000:12~D071:12") == (("D000", 12), ("D071", 12))
    with pytest.raises(ValueError, match="expected"):
        parse_pair_spec("12,13")


def test_upstream_and_periodic_models_are_both_available():
    periodic = float(np.asarray(cpd_metrics.kimmdy_rate(0.34, -175.0)))
    upstream = float(upstream_kimmdy_propensity(0.34, -175.0))
    assert periodic > upstream


def test_pair_propensities_aggregate_to_relative_per_base_scores():
    sites = [
        {
            "site_id": "D000:1",
            "label": "a",
            "segid": "D000",
            "resid": 1,
            "resname": "DT",
            "design_identity": {
                "kind": "base",
                "helix_id": "h0",
                "bp_index": 4,
                "direction": "FORWARD",
            },
        },
        {
            "site_id": "D001:1",
            "label": "b",
            "segid": "D001",
            "resid": 1,
            "resname": "DT",
            "design_identity": {
                "kind": "crossover_insert",
                "crossover_id": "xo7",
                "extra_base_k": 0,
            },
        },
        {
            "site_id": "D002:1",
            "label": "c",
            "segid": "D002",
            "resid": 1,
            "resname": "DT",
            "design_identity": None,
        },
    ]
    pairs = [
        {"site_a": sites[0], "site_b": sites[1], "primary_propensity_mean": 0.2},
        {"site_a": sites[0], "site_b": sites[2], "primary_propensity_mean": 0.1},
    ]
    rows = aggregate_base_likelihoods(sites, pairs)
    by_id = {row["site_id"]: row for row in rows}
    assert by_id["D000:1"]["aggregate_propensity"] == pytest.approx(0.3)
    assert by_id["D000:1"]["relative_likelihood"] == pytest.approx(1.0)
    assert by_id["D001:1"]["relative_likelihood"] == pytest.approx(2 / 3)
    assert by_id["D000:1"]["display_key"] == "h0:4:FORWARD"
    assert by_id["D001:1"]["display_key"] == "__xb__:xo7:0"
    assert by_id["D002:1"]["display_key"] is None


def test_all_tt_analysis_screens_once_and_returns_ranked_series(tmp_path):
    topology, trajectory = _two_thymine_trajectory(tmp_path)
    report, series = analyze_kimmdy_trajectory(
        topology,
        [trajectory],
        reciprocal_design(None),
        pair_mode="all-tt",
        screen_cutoff_ang=6.0,
        max_frames=None,
    )

    assert report["n_topology_thymines"] == 2
    assert report["n_candidates"] == 1
    assert report["screen"]["n_screen_hits"] == 1
    pair = report["pairs"][0]
    assert report["rate_model"] == "upstream"
    assert pair["site_a"]["segid"] == "D000"
    assert pair["site_b"]["segid"] == "D001"
    assert pair["d_mid_min_nm"] == pytest.approx(0.34, abs=1e-5)
    assert pair["pct_d_mid_below_screen_cutoff"] == pytest.approx(50.0)
    assert pair["primary_propensity_mean"] == pair["upstream_propensity_mean"]
    assert pair["representative_max_propensity"]["frame"] == 0
    assert pair["representative_max_propensity"]["trajectory_index"] == 0
    assert pair["representative_max_propensity"]["trajectory_frame"] == 0
    assert len(report["base_likelihoods"]) == 2
    assert report["base_likelihoods"][0]["relative_likelihood"] == pytest.approx(1.0)
    assert series["d_mid_nm"].shape == (1, 2)
    assert series["pair_ids"].tolist() == [pair["id"]]
    assert series["trajectory_indices"].tolist() == [0, 0]
    assert series["trajectory_local_frames"].tolist() == [0, 1]


def test_explicit_mode_handles_duplicate_resids_on_different_segments(tmp_path):
    topology, trajectory = _two_thymine_trajectory(tmp_path)
    report, _series = analyze_kimmdy_trajectory(
        topology,
        [trajectory],
        reciprocal_design(None),
        pair_mode="explicit",
        explicit_pairs=["D000:1~D001:1"],
    )
    assert report["pairs"][0]["id"] == "D000:1~D001:1"


def test_namd_photoproduct_payload_uses_only_production_and_is_display_ready(tmp_path):
    topology, trajectory = _two_thymine_trajectory(tmp_path)
    design = reciprocal_design(None)
    progress_path = tmp_path / "progress.json"
    result = md_photoproduct_likelihood(
        topology,
        [("prod", "production", trajectory)],
        topology,
        design,
        max_frames=2,
        progress_path=str(progress_path),
    )
    assert result["ready"] is True
    assert result["n_sampled_frames"] == 2
    assert result["n_display_bases"] == 2
    assert result["base_likelihoods"][0]["display_key"] is not None
    progress = json.loads(progress_path.read_text())
    assert progress["phase"] == "serializing"
    assert progress["fraction"] == pytest.approx(0.99)

    unavailable = md_photoproduct_likelihood(
        topology,
        [("equil", "equilibration", trajectory)],
        topology,
        design,
    )
    assert unavailable["ready"] is False
    assert "production" in unavailable["reason"]


def test_job_resolver_and_output_bundle_are_reusable(tmp_path):
    topology, trajectory = _two_thymine_trajectory(tmp_path)
    job = tmp_path / "job"
    package = job / "package" / "demo_namd_solvated"
    output = package / "output"
    output.mkdir(parents=True)
    (job / "design.json").write_text(reciprocal_design(None).model_dump_json())
    (job / "job.json").write_text(
        json.dumps(
            {
                "package_subdir": "package/demo_namd_solvated",
                "name_stem": "demo",
            }
        )
    )
    (package / "demo.psf").write_text("placeholder topology; explicit override is used")
    production = output / "demo_01_production_1ns_k0.dcd"
    production.write_bytes(trajectory.read_bytes())

    source = resolve_analysis_source(job_dir=job, topology_path=topology)
    assert source.design_path == job / "design.json"
    assert source.trajectory_paths == (production,)

    report, series = analyze_kimmdy_trajectory(
        source.topology_path,
        source.trajectory_paths,
        reciprocal_design(None),
        pair_mode="all-tt",
        max_frames=None,
    )
    paths = write_kimmdy_outputs(report, series, source.output_dir)
    assert all(Path(path).is_file() for path in paths.values())
    saved = np.load(paths["timeseries_npz"])
    assert saved["d_mid_nm"].shape == (1, 2)


def test_job_resolver_rejects_ambiguous_dcd_series(tmp_path):
    job = tmp_path / "job"
    package = job / "package" / "demo_namd_solvated"
    output = package / "output"
    output.mkdir(parents=True)
    (job / "design.json").write_text(reciprocal_design(None).model_dump_json())
    (job / "job.json").write_text(
        json.dumps(
            {
                "package_subdir": "package/demo_namd_solvated",
                "name_stem": "demo",
            }
        )
    )
    (package / "demo.psf").write_text("placeholder")
    (output / "demo_01_production.dcd").write_bytes(b"")
    (output / "demo_02_production.dcd").write_bytes(b"")

    with pytest.raises(ValueError, match="multiple independent DCD series"):
        resolve_analysis_source(job_dir=job)
