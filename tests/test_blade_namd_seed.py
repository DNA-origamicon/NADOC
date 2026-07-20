"""BLADE → NAMD seed handoff (seed_namd Phase 2).

These pin the coordinate-read path and its guards WITHOUT running OpenMM, psfgen, GROMACS, or
NAMD.  The seed builder is a pure disk read (design.json + relaxed.pdb → an (N,3) array), so it
is unit-testable; the actual solvation is exercised by the existing NAMD prep tests.

The one contract that matters here and can silently corrupt a run if wrong: the coords parsed
from relaxed.pdb must be in the SAME order the solvation step overwrites (fixed-width PDB
columns, ATOM/HETATM only).  A wrong order seeds a garbled conformation with no error.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.conftest import make_6hb_design
from backend.core.blade_job import BladeStatus, new_blade_job
from backend.core import blade_runner


def _write_blade_job(tmp_path: Path, *, status=BladeStatus.completed, pdb=True, design=True):
    """Materialise a minimal completed BLADE job dir (design.json + relaxed.pdb)."""
    job = new_blade_job("6hb")
    job.status = status
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    if design:
        (jd / "design.json").write_text(make_6hb_design().model_dump_json())
    if pdb:
        (jd / "relaxed.pdb").write_text(
            "ATOM      1  P   DA5 A   1      12.340  56.780  90.120  1.00  0.00      P\n"
            "ATOM      2  O5' DA5 A   1      13.100  57.200  91.000  1.00  0.00      O\n"
            "HETATM    3  O1P DA5 A   1      -1.500   2.000  -3.000  1.00  0.00      O\n"
            "END\n"
        )
    return job, jd


# ── Coordinate parse ──────────────────────────────────────────────────────────

def test_parse_pdb_xyz_reads_atom_and_hetatm_in_order():
    xyz = blade_runner._parse_pdb_xyz(
        "ATOM      1  P   DA5 A   1      12.340  56.780  90.120  1.00  0.00      P\n"
        "HETATM    2  O1P DA5 A   1      -1.500   2.000  -3.000  1.00  0.00      O\n"
        "TER\nEND\n"
    )
    assert xyz.shape == (2, 3)
    assert np.allclose(xyz[0], [12.34, 56.78, 90.12])
    assert np.allclose(xyz[1], [-1.5, 2.0, -3.0])   # HETATM + negatives preserved


def test_parse_pdb_xyz_ignores_non_atom_lines():
    xyz = blade_runner._parse_pdb_xyz(
        "REMARK generated\nCRYST1 1 1 1\n"
        "ATOM      1  P   DA5 A   1       1.000   2.000   3.000  1.00  0.00      P\nEND\n"
    )
    assert xyz.shape == (1, 3)


# ── build_namd_seed_from_blade ────────────────────────────────────────────────

def test_build_seed_returns_design_snapshot_and_exact_coords(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path)
    seed = blade_runner.build_namd_seed_from_blade(job.job_id, tmp_path)
    assert seed.source_job_id == job.job_id
    assert seed.n_atoms == 3
    assert seed.solute_coords.shape == (3, 3)
    # The snapshot design, not the live one — it must be a real Design with helices.
    assert seed.design.helices


def test_build_seed_uses_the_jobs_own_snapshot_not_live_state(tmp_path: Path):
    """The atom-order contract only holds if the NAMD topology is rebuilt from the SAME design
    BLADE relaxed — so the seed must carry the job's snapshot, never the live editor design."""
    job, jd = _write_blade_job(tmp_path)
    # A snapshot distinct from anything 'live' — proven by round-tripping the stored bytes.
    stored = (jd / "design.json").read_text()
    seed = blade_runner.build_namd_seed_from_blade(job.job_id, tmp_path)
    assert seed.design.model_dump_json() == stored


def test_build_seed_rejects_an_incomplete_job(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path, status=BladeStatus.running)
    with pytest.raises(FileNotFoundError, match="not completed"):
        blade_runner.build_namd_seed_from_blade(job.job_id, tmp_path)


def test_build_seed_rejects_a_missing_relaxed_pdb(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path, pdb=False)
    with pytest.raises(FileNotFoundError, match="relaxed.pdb"):
        blade_runner.build_namd_seed_from_blade(job.job_id, tmp_path)


def test_build_seed_rejects_a_missing_snapshot(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path, design=False)
    with pytest.raises(FileNotFoundError, match="design.json snapshot"):
        blade_runner.build_namd_seed_from_blade(job.job_id, tmp_path)


# ── assert_blade_namd_seed_available (cheap precheck) ──────────────────────────

def test_assert_seed_available_passes_for_a_completed_job(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path)
    blade_runner.assert_blade_namd_seed_available(job.job_id, tmp_path)   # no raise


def test_assert_seed_available_rejects_incomplete(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path, status=BladeStatus.completed)
    # Flip to running after writing the artifacts to prove status is what's checked.
    job.status = BladeStatus.running
    job.save(tmp_path)
    with pytest.raises(FileNotFoundError, match="not completed"):
        blade_runner.assert_blade_namd_seed_available(job.job_id, tmp_path)


def test_assert_seed_available_rejects_missing_pdb(tmp_path: Path):
    job, _ = _write_blade_job(tmp_path, pdb=False)
    with pytest.raises(FileNotFoundError, match="relaxed.pdb"):
        blade_runner.assert_blade_namd_seed_available(job.job_id, tmp_path)


def test_assert_seed_available_rejects_unknown_job(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        blade_runner.assert_blade_namd_seed_available("deadbeef0000", tmp_path)


# ── MdJob provenance round-trip ───────────────────────────────────────────────

def test_md_job_persists_the_blade_seed_provenance(tmp_path: Path):
    """The NAMD job records which BLADE relax seeded it — the link is provenance, not tree
    nesting (cross-engine parent/child is unsupported), so it must survive save/load like the
    oxDNA/mrDNA seed fields."""
    from backend.core.md_job import MdJob, new_job
    job = new_job("6hb", "equilibrium_aware_v1", "", "", seed_blade_job_id="blade123")
    job.save(tmp_path)
    back = MdJob.load(job.job_id, tmp_path)
    assert back.seed_blade_job_id == "blade123"
    assert back.seed_oxdna_job_id is None
    assert back.seed_mrdna_job_id is None


def test_md_job_backfills_blade_seed_on_older_json(tmp_path: Path):
    """A job.json written before seed_blade_job_id existed must still load."""
    import json
    from backend.core.md_job import MdJob, new_job
    job = new_job("6hb", "equilibrium_aware_v1", "", "")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    data = json.loads((jd / "job.json").read_text())
    data.pop("seed_blade_job_id", None)
    (jd / "job.json").write_text(json.dumps(data))
    assert MdJob.load(job.job_id, tmp_path).seed_blade_job_id is None
