"""Portable Alpine WC evaluator: no scientific Python on the compute node."""

import json

import numpy as np

from backend.core import remote_wc_eval as ev
from backend.core.dcd_fast import write_trajectory


def _plan():
    return {
        "version": 1,
        "n_atoms": 4,
        "ref_delta_ang": 0.75,
        "pairs": [
            {"atom_pairs": [[0, 1]], "ref_distances": [3.0]},
            {"atom_pairs": [[2, 3]], "ref_distances": [3.0]},
        ],
    }


def _frames():
    frames = []
    for i in range(12):
        xyz = np.zeros((4, 3), dtype=np.float32)
        xyz[1, 0] = 3.0
        xyz[2, 0] = 10.0
        xyz[3, 0] = 13.0 if i < 2 else 15.0
        frames.append(xyz)
    return frames


def _write_tiny_pair_package(tmp_path):
    atoms = [
        ("DNAA", 1, "DA", "C1'", (0.0, 0.0, 0.0)),
        ("DNAA", 1, "DA", "N1", (1.0, 0.0, 0.0)),
        ("DNAA", 1, "DA", "N6", (1.0, 1.0, 0.0)),
        ("DNAB", 1, "DT", "C1'", (10.0, 0.0, 0.0)),
        ("DNAB", 1, "DT", "N3", (4.0, 0.0, 0.0)),
        ("DNAB", 1, "DT", "O4", (4.0, 1.0, 0.0)),
    ]
    psf = ["PSF", "", f"{len(atoms):8d} !NATOM"]
    pdb = []
    for serial, (segid, resid, resname, name, xyz) in enumerate(atoms, 1):
        psf.append(
            f"{serial:8d} {segid:<4} {resid:<4} {resname:<4} {name:<4} "
            f"{name:<4} 0.000000 12.0000 0"
        )
        pdb.append(
            f"ATOM  {serial:5d} {name:>4} {resname:>3} A{resid:4d}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00      {segid:>4}"
        )
    (tmp_path / "tiny.psf").write_text("\n".join(psf) + "\n")
    (tmp_path / "tiny.pdb").write_text("\n".join(pdb) + "\n")


def test_wc_series_reads_only_trailing_plateau_window(tmp_path):
    dcd = tmp_path / "chunk.dcd"
    write_trajectory(dcd, 4, _frames(), 12)
    assert ev.wc_series(dcd, _plan()) == [0.5] * 10


def test_plan_builder_streams_psf_pdb_and_preserves_global_indices(tmp_path):
    _write_tiny_pair_package(tmp_path)
    plan = ev.build_plan(tmp_path, "tiny")
    assert plan["n_atoms"] == 6
    assert len(plan["pairs"]) == 1
    assert plan["pairs"][0]["atom_pairs"] == [[1, 4], [2, 5]]
    assert plan["pairs"][0]["ref_distances"] == [3.0, 3.0]


def test_cli_writes_cutoff_ready_json(tmp_path):
    dcd = tmp_path / "chunk.dcd"
    plan = tmp_path / "plan.json"
    out = tmp_path / "wc.json"
    write_trajectory(dcd, 4, _frames(), 12)
    plan.write_text(json.dumps(_plan()))
    assert ev.main(["--dcd", str(dcd), "--plan", str(plan), "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == [0.5] * 10


def test_failure_removes_stale_wc_file(tmp_path):
    plan = tmp_path / "plan.json"
    out = tmp_path / "wc.json"
    plan.write_text(json.dumps(_plan()))
    out.write_text("[1.0]")
    assert (
        ev.main(
            [
                "--dcd",
                str(tmp_path / "missing.dcd"),
                "--plan",
                str(plan),
                "--out",
                str(out),
            ]
        )
        == 3
    )
    assert not out.exists()


def test_atom_count_mismatch_fails_closed(tmp_path):
    dcd = tmp_path / "chunk.dcd"
    write_trajectory(dcd, 4, _frames(), 12)
    plan = _plan()
    plan["n_atoms"] = 5
    try:
        ev.wc_series(dcd, plan)
    except ValueError as exc:
        assert "atom-count mismatch" in str(exc)
    else:
        raise AssertionError("mismatched topology plan must not be accepted")
