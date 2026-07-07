"""Tests for the LAMMPS (CG-DNA) oxDNA runner (backend/core/lammps_runner).

Pure command-building + prepare-job (no LAMMPS needed) are always run; the real
end-to-end run is gated on a CG-DNA-capable ``lmp`` being present (skipped
otherwise) and marked slow (it launches an actual MD run).
"""

from __future__ import annotations

import asyncio
import os

import pytest

import backend.core.lammps_runner as R
from backend.core.lammps_job import LammpsStatus, new_lammps_job
from backend.core.oxdna_runner import find_lammps, lammps_supports_cgdna
from backend.physics import lammps_interface as L
from tests.conftest import make_6hb_design


def _sequenced_design():
    design = make_6hb_design(length_bp=42)
    for s in design.strands:               # fully sequence every strand (ACGT, no 'N')
        s.sequence = "ACGT" * 4000
    return design


def _geometry(design):
    from backend.api.crud import _geometry_for_design
    return _geometry_for_design(design)


# ── build_lammps_argv (pure) ──────────────────────────────────────────────────

def test_argv_serial_is_plain_lmp():
    assert R.build_lammps_argv("/x/lmp", "in.lammps", ranks=1) == ["/x/lmp", "-in", "in.lammps"]


def test_argv_mpi_prefixes_mpirun():
    argv = R.build_lammps_argv("/x/lmp", "in.lammps", ranks=8)
    assert argv == ["mpirun", "-np", "8", "/x/lmp", "-in", "in.lammps"]


# ── resolve_lammps ────────────────────────────────────────────────────────────

def test_resolve_lammps_raises_when_missing(monkeypatch):
    monkeypatch.setattr(R, "find_lammps", lambda: None)
    with pytest.raises(R.LammpsError, match="No LAMMPS binary"):
        R.resolve_lammps()


def test_resolve_lammps_raises_when_not_cgdna(monkeypatch):
    monkeypatch.setattr(R, "find_lammps", lambda: "/x/lmp")
    monkeypatch.setattr(R, "lammps_supports_cgdna", lambda p: False)
    with pytest.raises(R.LammpsError, match="without the CG-DNA package"):
        R.resolve_lammps()


# ── prepare_lammps_job (writes files; no LAMMPS) ───────────────────────────────

def test_prepare_writes_a_complete_job(tmp_path):
    design = _sequenced_design()
    info = R.prepare_lammps_job(design, _geometry(design), tmp_path)
    for key in ("topology", "configuration", "data", "input"):
        assert (tmp_path / os.path.basename(info[key])).exists()
    assert info["n_atoms"] > 0 and info["n_bonds"] > 0
    data = (tmp_path / "data.oxdna").read_text()
    assert f"{info['n_atoms']} atoms" in data
    assert "atom_style hybrid bond ellipsoid oxdna" in (tmp_path / "in.lammps").read_text()


def test_prepare_rejects_unsequenced_design(tmp_path):
    design = make_6hb_design(length_bp=42)     # no sequence assigned → bases are 'N'
    with pytest.raises(ValueError, match="not fully sequenced"):
        R.prepare_lammps_job(design, _geometry(design), tmp_path)


# ── real end-to-end run (gated on a CG-DNA LAMMPS being installed) ─────────────

_LMP = find_lammps()
_HAS_CGDNA = bool(_LMP and lammps_supports_cgdna(_LMP))


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_lammps_real_run_end_to_end(tmp_path):   # auto-marked slow via conftest registry
    """NADOC design → oxDNA files → LAMMPS data → real lmp run → trajectory."""
    design = _sequenced_design()
    params = L.LammpsInputParams(steps=1000, dump_every=500, thermo_every=500)
    R.prepare_lammps_job(design, _geometry(design), tmp_path, params)
    result = asyncio.run(R.run_lammps(tmp_path, ranks=1))
    assert result["rc"] == 0
    assert result["frames"] >= 2            # steps 0, 500, 1000
    assert (tmp_path / "traj.lammpstrj").stat().st_size > 0


# ── managed-job orchestration ─────────────────────────────────────────────────

def test_parse_thermo_step():
    assert R.parse_thermo_step("       500   0.0165   -0.45   0.045   -0.38") == 500
    assert R.parse_thermo_step("Step          Temp          E_pair") is None
    assert R.parse_thermo_step("Per MPI rank memory allocation") is None
    assert R.parse_thermo_step("") is None
    assert R.parse_thermo_step("-10 0.1") == -10


def test_run_job_sets_failed_when_lammps_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "find_lammps", lambda: None)   # resolve_lammps raises
    job = new_lammps_job("d")
    job.save(tmp_path)
    asyncio.run(R.run_job(job, tmp_path))
    assert job.status is LammpsStatus.failed
    assert "No LAMMPS binary" in (job.error or "")


def test_reconcile_flips_dead_running_job_to_stopped(tmp_path):
    job = new_lammps_job("d")
    job.status = LammpsStatus.running
    job.lammps_pid = 999999   # not a live LAMMPS process
    job.save(tmp_path)
    healed = R.reconcile_lammps_status(job, tmp_path)
    assert healed.status is LammpsStatus.stopped
    assert healed.lammps_pid is None


def test_reconcile_leaves_terminal_jobs_untouched(tmp_path):
    job = new_lammps_job("d")
    job.status = LammpsStatus.completed
    assert R.reconcile_lammps_status(job, tmp_path).status is LammpsStatus.completed


def test_stop_job_missing_returns_false(tmp_path):
    assert R.stop_job("nope", tmp_path) is False
