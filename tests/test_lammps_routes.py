"""HTTP tests for the LAMMPS job REST API (backend/api/routes_lammps).

The full create→run→complete lifecycle is a real background LAMMPS run, gated on a
CG-DNA-capable ``lmp`` being installed (skipped otherwise) and registered slow.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import backend.api.routes_lammps as routes_lammps
from backend.api import state as design_state
from backend.api.main import app
from backend.core.oxdna_runner import find_lammps, lammps_supports_cgdna
from tests.conftest import make_6hb_design

_LMP = find_lammps()
_HAS_CGDNA = bool(_LMP and lammps_supports_cgdna(_LMP))
client = TestClient(app)


def _sequenced_design():
    design = make_6hb_design(length_bp=42)
    for s in design.strands:
        s.sequence = "ACGT" * 4000
    return design


def test_available_reports_shape():
    r = client.get("/api/lammps/available")
    assert r.status_code == 200
    body = r.json()
    assert "available" in body and "cgdna_capable" in body
    assert isinstance(body["max_ranks"], int) and body["max_ranks"] >= 1
    assert isinstance(body["free_ranks"], int) and 1 <= body["free_ranks"] <= body["max_ranks"]


def test_create_rejects_ranks_over_core_count(monkeypatch, tmp_path):
    """ranks > physical cores is refused fast (before any design/prep work) — MPI
    would otherwise fail to launch. Guard runs regardless of LAMMPS being installed."""
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(
        routes_lammps, "lammps_available",
        lambda: {"available": True, "lammps_bin": "/x/lmp", "cgdna_capable": True})
    monkeypatch.setattr(routes_lammps.lammps_runner, "available_cpu_cores", lambda: 2)
    r = client.post("/api/lammps/jobs", json={"steps": 500, "ranks": 3})
    assert r.status_code == 400
    assert "MPI ranks" in r.json()["detail"] and "2" in r.json()["detail"]


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_create_rejects_unsequenced_design(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    design_state.set_design(make_6hb_design(length_bp=42))   # unsequenced → 'N' bases
    r = client.post("/api/lammps/jobs", json={"steps": 500})
    assert r.status_code == 400
    assert "undefined base" in r.json()["detail"]


def test_stop_unknown_job_404(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    assert client.post("/api/lammps/jobs/nope/stop").status_code == 404


def test_get_unknown_job_404(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    assert client.get("/api/lammps/jobs/nope").status_code == 404


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_create_runs_to_completion_and_lists(monkeypatch, tmp_path):
    """POST a job on a sequenced design → it runs in the background → completes with
    a trajectory, appears in the list, and reads back by id."""
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    design_state.set_design(_sequenced_design())

    r = client.post("/api/lammps/jobs", json={"steps": 1000, "dump_every": 500})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] in ("preparing", "running", "queued")
    assert job["n_atoms"] > 0 and job["n_bonds"] > 0
    job_id = job["job_id"]

    # it shows up in the list immediately
    assert any(j["job_id"] == job_id for j in client.get("/api/lammps/jobs").json())

    # poll to a terminal state
    deadline = time.time() + 120
    status = job["status"]
    while time.time() < deadline:
        status = client.get(f"/api/lammps/jobs/{job_id}").json()["status"]
        if status in ("completed", "failed", "stopped"):
            break
        time.sleep(0.5)
    final = client.get(f"/api/lammps/jobs/{job_id}").json()
    assert final["status"] == "completed", final.get("error")
    assert final["frames"] >= 2
    assert (tmp_path / "lammps_jobs" / job_id / "traj.lammpstrj").stat().st_size > 0

    # trajectory read-back: the dump → oxDNA .dat → viewer payload (same design loaded)
    traj = client.get(f"/api/lammps/jobs/{job_id}/trajectory").json()
    assert traj["ready"] is True, traj.get("reason")
    assert traj["n_frames"] >= 2
    assert traj["n_nucleotides"] == final["n_atoms"]
    assert len(traj["keys"]) == final["n_atoms"]
    assert len(traj["frames"][0]) == final["n_atoms"] * 6   # x,y,z,nx,ny,nz per nucleotide

    # the visualization views reuse the oxDNA health code on the transcoded .dat
    disp = client.get(f"/api/lammps/jobs/{job_id}/display").json()
    assert disp["ready"] is True and disp["n_positions"] == final["n_atoms"]
    assert set(disp["positions"][0]) >= {"helix_id", "bp_index", "direction", "backbone_position", "nx"}

    rmsf = client.get(f"/api/lammps/jobs/{job_id}/rmsf").json()
    assert rmsf["ready"] is True and rmsf["n_frames"] >= 2
    assert len(rmsf["positions"]) == final["n_atoms"]

    dev = client.get(f"/api/lammps/jobs/{job_id}/deviation").json()
    assert dev["ready"] is True and dev["mean_deviation"] is not None


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_create_field_without_anchor_is_400(monkeypatch, tmp_path):
    """An E-field with no resolvable anchor is rejected (an unanchored uniform force
    just drifts the whole structure — oxDNA GOTCHA 1).  Fast: prepare raises before
    any lmp run is launched."""
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    design_state.set_design(_sequenced_design())
    r = client.post("/api/lammps/jobs", json={
        "steps": 500, "field": {"field_pN": 20.0, "dir": [1, 0, 0]}})
    assert r.status_code == 400
    assert "anchor" in r.json()["detail"].lower()


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_create_with_field_and_anchor_records_forces(monkeypatch, tmp_path):
    """A steered create (field + strand anchor) writes the LAMMPS fixes and records
    the applied-forces meta on the job (auto-marked slow — real lmp run)."""
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    design = _sequenced_design()
    design_state.set_design(design)
    r = client.post("/api/lammps/jobs", json={
        "steps": 1000, "dump_every": 500,
        "field": {"field_pN": 30.0, "dir": [1, 0, 0]},
        "anchors": [{"kind": "strand", "id": design.strands[0].id}]})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["forces"]["field"]["field_pN"] == 30.0
    assert job["forces"]["n_anchored"] > 0
    inp = (tmp_path / "lammps_jobs" / job["job_id"] / "in.lammps").read_text()
    assert "fix efield all addforce" in inp
    assert "fix anchors anchors spring/self" in inp

    deadline = time.time() + 120
    while time.time() < deadline:
        if client.get(f"/api/lammps/jobs/{job['job_id']}").json()["status"] in (
                "completed", "failed", "stopped"):
            break
        time.sleep(0.5)
    final = client.get(f"/api/lammps/jobs/{job['job_id']}").json()
    assert final["status"] == "completed", final.get("error")
    assert final["forces"]["field"]["field_pN"] == 30.0   # persisted across the run


def test_trajectory_guard_on_design_mismatch(monkeypatch, tmp_path):
    """A trajectory can't be mapped onto a different/edited design (nucleotide count differs)."""
    monkeypatch.setattr(routes_lammps, "_WORKSPACE_DIR", tmp_path)
    from backend.core.lammps_job import LammpsStatus, new_lammps_job
    job = new_lammps_job("d", n_atoms=999)
    job.status = LammpsStatus.completed
    (job.job_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
    (job.job_dir(tmp_path) / "traj.lammpstrj").write_text("ITEM: TIMESTEP\n0\n")
    job.save(tmp_path)
    design_state.set_design(make_6hb_design(length_bp=42))   # far fewer than 999 nucleotides
    r = client.get(f"/api/lammps/jobs/{job.job_id}/trajectory").json()
    assert r["ready"] is False
    assert "nucleotides" in r["reason"]
