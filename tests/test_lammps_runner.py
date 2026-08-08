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
    for s in design.strands:  # fully sequence every strand (ACGT, no 'N')
        s.sequence = "ACGT" * 4000
    return design


def _geometry(design):
    from backend.api.crud import _geometry_for_design

    return _geometry_for_design(design)


# ── build_lammps_argv (pure) ──────────────────────────────────────────────────


def test_argv_serial_is_plain_lmp():
    assert R.build_lammps_argv("/x/lmp", "in.lammps", ranks=1) == [
        "/x/lmp",
        "-in",
        "in.lammps",
    ]


def test_argv_mpi_prefixes_mpirun():
    argv = R.build_lammps_argv("/x/lmp", "in.lammps", ranks=8)
    assert argv == ["mpirun", "-np", "8", "/x/lmp", "-in", "in.lammps"]


def test_available_cpu_cores_is_a_positive_int_no_more_than_logical():
    n = R.available_cpu_cores()
    assert isinstance(n, int) and n >= 1
    logical = os.cpu_count() or 1
    assert n <= logical  # physical cores never exceed logical


def test_free_cpu_cores_within_one_and_total():
    total = R.available_cpu_cores()
    free = R.free_cpu_cores()
    assert isinstance(free, int) and 1 <= free <= total


def test_free_cpu_cores_drops_under_load(monkeypatch):
    """A busy machine (high load average) leaves fewer free cores than the total."""
    monkeypatch.setattr(R, "available_cpu_cores", lambda: 16)
    monkeypatch.setattr(R.os, "getloadavg", lambda: (10.0, 8.0, 4.0))
    assert R.free_cpu_cores() == 6  # 16 - round(10)
    monkeypatch.setattr(R.os, "getloadavg", lambda: (0.2, 0.1, 0.1))
    assert R.free_cpu_cores() == 16  # idle → all free
    monkeypatch.setattr(R.os, "getloadavg", lambda: (99.0, 99.0, 99.0))
    assert R.free_cpu_cores() == 1  # over-loaded → clamp to ≥1


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
    assert (
        "atom_style hybrid bond ellipsoid oxdna" in (tmp_path / "in.lammps").read_text()
    )


def test_prepare_rejects_unsequenced_design(tmp_path):
    design = make_6hb_design(length_bp=42)  # no sequence assigned → bases are 'N'
    with pytest.raises(ValueError, match="not fully sequenced"):
        R.prepare_lammps_job(design, _geometry(design), tmp_path)


# ── external-force mapping (oxDNA forces.txt → LAMMPS fixes) ───────────────────


def _conf_for(design, tmp_path):
    """Write the job's conf.dat (via prepare, no forces) and return its path."""
    R.prepare_lammps_job(design, _geometry(design), tmp_path)
    return tmp_path / "conf.dat"


def test_resolve_forces_field_without_anchor_allowed(tmp_path):
    """A field with no anchor is no longer rejected — it resolves to a force spec with
    no anchor ids (the UI warns about the resulting COM drift)."""
    design = _sequenced_design()
    conf = _conf_for(design, tmp_path)
    spec, meta = R.resolve_lammps_forces(
        design, conf, field={"field_pN": 20.0, "dir": [1, 0, 0]}
    )
    assert spec.force is not None  # the uniform field is present
    assert spec.anchor_ids == []  # but no anchor tethers
    assert meta["n_anchored"] == 0


def test_resolve_forces_field_and_anchor(tmp_path):
    design = _sequenced_design()
    conf = _conf_for(design, tmp_path)
    anchors = [{"kind": "strand", "id": design.strands[0].id}]
    spec, meta = R.resolve_lammps_forces(
        design, conf, field={"field_pN": 48.63, "dir": [2, 0, 0]}, anchors=anchors
    )
    # 48.63 pN = exactly 1.0 oxDNA force unit, along the normalised +x direction
    assert spec.force == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert meta["field"]["field_oxdna"] == pytest.approx(1.0, abs=1e-6)
    # oxDNA 0-based particles → LAMMPS 1-based atom ids
    assert meta["n_anchored"] > 0
    assert spec.anchor_ids == [p + 1 for p in meta["anchor_particles"]]
    assert min(spec.anchor_ids) >= 1


def test_resolve_forces_wall_axis_aligned(tmp_path):
    design = _sequenced_design()
    conf = _conf_for(design, tmp_path)
    spec, meta = R.resolve_lammps_forces(
        design, conf, wall={"dir": [0, 0, 1], "offset_nm": 0.5, "stiff": 50.0}
    )
    assert spec.wall["face"] == "zlo"
    assert spec.wall["epsilon"] == 50.0
    assert meta["wall"]["face"] == "zlo" and meta["wall"]["stiff"] == 50.0
    assert spec.force is None and not spec.anchor_ids


def test_prepare_with_forces_writes_fixes_and_meta(tmp_path):
    design = _sequenced_design()
    anchors = [{"kind": "strand", "id": design.strands[0].id}]
    info = R.prepare_lammps_job(
        design,
        _geometry(design),
        tmp_path,
        field={"field_pN": 30.0, "dir": [1, 0, 0]},
        anchors=anchors,
    )
    txt = (tmp_path / "in.lammps").read_text()
    assert "fix efield all addforce" in txt
    assert "fix anchors anchors spring/self" in txt
    assert info["forces"]["field"]["field_pN"] == 30.0
    assert info["forces"]["n_anchored"] > 0


def test_prepare_without_forces_reports_none(tmp_path):
    design = _sequenced_design()
    info = R.prepare_lammps_job(design, _geometry(design), tmp_path)
    assert info["forces"] is None
    assert "addforce" not in (tmp_path / "in.lammps").read_text()


# ── real end-to-end run (gated on a CG-DNA LAMMPS being installed) ─────────────

_LMP = find_lammps()
_HAS_CGDNA = bool(_LMP and lammps_supports_cgdna(_LMP))


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_lammps_real_run_end_to_end(tmp_path):  # auto-marked slow via conftest registry
    """NADOC design → oxDNA files → LAMMPS data → real lmp run → trajectory."""
    design = _sequenced_design()
    params = L.LammpsInputParams(steps=1000, dump_every=500, thermo_every=500)
    R.prepare_lammps_job(design, _geometry(design), tmp_path, params)
    result = asyncio.run(R.run_lammps(tmp_path, ranks=1))
    assert result["rc"] == 0
    assert result["frames"] >= 2  # steps 0, 500, 1000
    assert (tmp_path / "traj.lammpstrj").stat().st_size > 0


def _dump_frames(text):
    """Parse a LAMMPS custom dump → list of id-sorted (N,3) position arrays."""
    import numpy as np

    frames = []
    for blk in text.split("ITEM: TIMESTEP")[1:]:
        lines = blk.splitlines()
        start = cols = None
        for i, ln in enumerate(lines):
            if ln.startswith("ITEM: ATOMS"):
                cols = ln.split()[2:]
                start = i + 1
                break
        ci = {c: k for k, c in enumerate(cols)}
        rows = []
        for ln in lines[start:]:
            p = ln.split()
            if len(p) < len(cols):
                break
            rows.append(
                (
                    int(p[ci["id"]]),
                    float(p[ci["x"]]),
                    float(p[ci["y"]]),
                    float(p[ci["z"]]),
                )
            )
        rows.sort()
        frames.append(np.array([[r[1], r[2], r[3]] for r in rows]))
    return frames


@pytest.mark.skipif(not _HAS_CGDNA, reason="no CG-DNA-capable LAMMPS installed")
def test_lammps_field_holds_anchor_and_deflects_free(tmp_path):
    """A real field+anchor run: anchored beads stay put; free beads drift ALONG the
    field.  The physics proof that the oxDNA string/trap → addforce/spring mapping
    steers a LAMMPS run correctly (auto-marked slow)."""
    import numpy as np

    design = _sequenced_design()
    anchors = [{"kind": "strand", "id": design.strands[0].id}]
    params = L.LammpsInputParams(
        steps=40000, dump_every=2000, relax_iters=300, thermo_every=40000
    )
    info = R.prepare_lammps_job(
        design,
        _geometry(design),
        tmp_path,
        params,
        field={"field_pN": 200.0, "dir": [1, 0, 0]},
        anchors=anchors,
    )
    assert asyncio.run(R.run_lammps(tmp_path, ranks=1))["rc"] == 0

    frames = _dump_frames((tmp_path / "traj.lammpstrj").read_text())
    f0, fN = frames[0], frames[-1]  # frame 0 = the anchor tether point
    anchored = np.array(info["forces"]["anchor_particles"])
    mask = np.zeros(len(f0), bool)
    mask[anchored] = True
    disp = fN - f0
    anchored_drift = np.linalg.norm(disp[mask], axis=1).mean()
    # Mean displacement VECTOR of the free beads: the field imposes a NET drift along
    # +x while thermal motion averages to ~0 in y/z.  (We test the net drift vector,
    # not per-bead magnitude: at the physical timestep free beads also diffuse
    # thermally, so |displacement| is thermal-dominated even though the net drift is
    # cleanly along the field.)
    net = disp[~mask].mean(axis=0)
    # anchors held (spring/self K=1000 → ≪0.1 oxDNA units)
    assert anchored_drift < 0.1
    # free part drifted along the +field (x) direction, far more than the anchors moved
    assert net[0] > 3 * anchored_drift
    # and +x (the field) is the dominant direction of the NET drift (y/z average out)
    assert net[0] > abs(net[1]) and net[0] > abs(net[2])


# ── managed-job orchestration ─────────────────────────────────────────────────


def test_parse_thermo_step():
    assert R.parse_thermo_step("       500   0.0165   -0.45   0.045   -0.38") == 500
    assert R.parse_thermo_step("Step          Temp          E_pair") is None
    assert R.parse_thermo_step("Per MPI rank memory allocation") is None
    assert R.parse_thermo_step("") is None
    assert R.parse_thermo_step("-10 0.1") == -10


def test_run_job_sets_failed_when_lammps_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "find_lammps", lambda: None)  # resolve_lammps raises
    job = new_lammps_job("d")
    job.save(tmp_path)
    asyncio.run(R.run_job(job, tmp_path))
    assert job.status is LammpsStatus.failed
    assert "No LAMMPS binary" in (job.error or "")


def test_reconcile_flips_dead_running_job_to_stopped(tmp_path):
    job = new_lammps_job("d")
    job.status = LammpsStatus.running
    job.lammps_pid = 999999  # not a live LAMMPS process
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
