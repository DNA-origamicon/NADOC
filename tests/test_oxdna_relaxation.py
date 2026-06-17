"""
Tests for the local oxDNA relaxation runner (oxdna_job / oxdna_protocol /
oxdna_health / oxdna_runner / routes_oxdna).

The end-to-end runner test uses a MOCK oxDNA binary (a tiny python script that
copies the input conf to last_conf.dat and writes a fake energy.dat), so the
orchestration — staging, sequential runs, health gates, completion — is pinned
without a real oxDNA install.
"""

from __future__ import annotations

import stat
import time

import numpy as np
import pytest

from backend.core.oxdna_health import (
    base_pair_retention,
    energy_is_converged,
    max_backbone_stretch,
    parse_energy_dat,
)
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus, new_oxdna_job
from backend.core.oxdna_protocol import (
    build_relaxation_stages,
    expected_energy_lines,
    render_stage_input,
)
from backend.physics.oxdna_interface import (
    read_configuration_full,
    write_configuration,
)

from tests.conftest import make_6hb_design


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def design():
    return make_6hb_design()


@pytest.fixture
def geometry(design):
    from backend.api.crud import _geometry_for_design
    return _geometry_for_design(design)


# ── oxdna_job: persistence round-trip ─────────────────────────────────────────

def test_job_roundtrip(tmp_path):
    specs = build_relaxation_stages(mc_steps=100, md_relax_steps=200, equil_steps=300)
    job = new_oxdna_job("demo", [s.to_status() for s in specs], n_nucleotides=42)
    job.save(tmp_path)
    loaded = OxdnaJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert loaded.status == OxdnaStatus.queued
    assert [s.name for s in loaded.stages] == ["1_mc_relax", "2_md_relax", "3_equil"]
    assert [s.steps for s in loaded.stages] == [100, 200, 300]
    assert loaded.n_nucleotides == 42


def test_list_jobs(tmp_path):
    for i in range(3):
        new_oxdna_job(f"d{i}", []).save(tmp_path)
    assert len(OxdnaJob.list_jobs(tmp_path)) == 3


# ── oxdna_protocol: input-file generation ─────────────────────────────────────

def test_stage_specs_shape():
    specs = build_relaxation_stages(backend="CUDA", device="1")
    assert [s.kind for s in specs] == ["mc", "md_relax", "equil"]
    # Stage 1 is Monte Carlo (CPU only); MD stages honour the requested backend.
    assert specs[0].backend == "CPU" and specs[0].sim_type == "MC"
    assert specs[1].backend == "CUDA" and specs[1].sim_type == "MD"
    assert specs[2].backend == "CUDA" and specs[2].sim_type == "MD"
    # Modified-backbone force cap on mc+md_relax, removed (standard FENE) on equil.
    assert specs[0].max_backbone_force == 5.0
    assert specs[1].max_backbone_force == 5.0
    assert specs[2].max_backbone_force is None
    # Standard defaults.
    assert specs[0].steps == 1_000
    assert specs[1].steps == 1_000_000


def test_render_cuda_md_input():
    specs = build_relaxation_stages(md_relax_steps=10_000, device="2")
    txt = render_stage_input(specs[1], "/abs/topology.top", "/abs/conf.dat")
    assert "backend = CUDA" in txt
    assert "CUDA_device = 2" in txt
    assert "sim_type = MD" in txt
    assert "dt = 0.002" in txt
    assert "thermostat = bussi" in txt
    assert "bussi_tau = 1000" in txt
    assert "newtonian_steps = 53" in txt
    assert "interaction_type = DNA2" in txt
    assert "max_backbone_force = 5.0" in txt
    assert "topology = /abs/topology.top" in txt
    assert "conf_file = /abs/conf.dat" in txt
    assert "lastconf_file = last_conf.dat" in txt
    assert "energy_file = energy.dat" in txt
    # ~100 energy samples over the stage
    assert "print_energy_every = 100" in txt


def test_render_mc_input_standard_keys():
    specs = build_relaxation_stages(mc_steps=1_000)
    txt = render_stage_input(specs[0], "topology.top", "conf.dat")
    assert "backend = CPU" in txt
    assert "CUDA_device" not in txt
    assert "sim_type = MC" in txt
    assert "ensemble = NVT" in txt
    assert "delta_translation = 0.1" in txt
    assert "delta_rotation = 0.1" in txt
    assert "max_backbone_force = 5.0" in txt
    # MC has no MD-only keys.
    assert "thermostat" not in txt
    assert "dt = " not in txt


def test_render_equil_has_no_force_cap():
    specs = build_relaxation_stages(equil_steps=5_000)
    txt = render_stage_input(specs[2], "t", "c")
    assert "max_backbone_force" not in txt
    assert "sim_type = MD" in txt


def test_expected_energy_lines():
    specs = build_relaxation_stages(md_relax_steps=10_000)
    assert expected_energy_lines(specs[1]) == 100


# ── Mutual-trap external forces (relax aid so the structure holds) ─────────────

def test_mutual_traps_file(design, tmp_path):
    from backend.physics.oxdna_interface import write_mutual_traps, _strand_nucleotide_order
    p = tmp_path / "forces.txt"
    n_pairs = write_mutual_traps(design, p)
    assert n_pairs > 0
    text = p.read_text()
    # Two symmetric mutual_trap entries per designed pair.
    assert text.count("type = mutual_trap") == 2 * n_pairs
    assert "stiff = 1.0" in text and "r0 = 1.2" in text
    # Particle indices are valid 0-based topology indices.
    n_nuc = len(_strand_nucleotide_order(design))
    import re
    for idx in map(int, re.findall(r"particle = (\d+)", text)):
        assert 0 <= idx < n_nuc


def test_stage_external_forces_flags():
    specs = build_relaxation_stages()
    # Traps ON for the MC + MD-relax stages, OFF for the unbiased equil stage.
    assert specs[0].external_forces is True   # mc
    assert specs[1].external_forces is True   # md_relax
    assert specs[2].external_forces is False  # equil


def test_render_includes_forces_only_when_enabled():
    specs = build_relaxation_stages()
    mc = render_stage_input(specs[0], "t.top", "c.dat", forces_name="forces.txt")
    assert "external_forces = true" in mc
    assert "external_forces_file = forces.txt" in mc
    # equil has external_forces=False → keys omitted even if a forces file is passed.
    equil = render_stage_input(specs[2], "t.top", "c.dat", forces_name="forces.txt")
    assert "external_forces" not in equil


# ── Production stage ──────────────────────────────────────────────────────────

def test_production_stage_spec():
    from backend.core.oxdna_protocol import build_production_stage
    p = build_production_stage(steps=2_000_000, backend="CUDA")
    assert p.kind == "production" and p.sim_type == "MD"
    assert p.max_backbone_force is None      # standard backbone potential
    assert p.external_forces is False        # unbiased — no traps
    assert p.min_bp_retained == 0.0          # sampling: no bp gate
    txt = render_stage_input(p, "t.top", "c.dat", forces_name="forces.txt")
    assert "max_backbone_force" not in txt and "external_forces" not in txt


def test_job_progress_eta(tmp_path):
    """job_progress reports an ETA from the live rate of the running stage + the
    remaining (current + pending) steps."""
    from backend.core.oxdna_runner import job_progress

    specs = build_relaxation_stages(mc_steps=1000, md_relax_steps=100_000, equil_steps=50_000)
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    job.current_stage_idx = 1
    job.stages[0].status = "done"
    job.stages[1].status = "running"
    job.stages[1].started_at = time.time() - 10.0       # 10 s into md_relax
    job.save(tmp_path)
    sd = job.stage_dir(tmp_path, job.stages[1].name)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "energy.dat").write_text("\n".join("0 -1 0.5 -0.5" for _ in range(30)) + "\n")

    prog = job_progress(job, tmp_path, specs)
    assert prog["stage_fraction"] == pytest.approx(0.30, abs=0.02)   # 30/100 lines
    # 30% of 100k = 30k steps in 10 s → 3000 st/s; remaining 70k + 50k = 120k → ~40 s.
    assert prog["eta_seconds"] is not None
    assert 20 < prog["eta_seconds"] < 80


def test_production_rmsd(design, geometry, tmp_path):
    """Production RMSD: per-frame backbone RMSD vs the relaxed reference, with each
    frame PBC-unwrapped + Kabsch-aligned (so rigid drift contributes ~0)."""
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        write_configuration, read_trajectory_frames_full,
    )
    from backend.core.oxdna_health import production_rmsd

    ref = tmp_path / "ref.dat"
    write_configuration(design, geometry, ref, box_nm=50.0)
    lines = ref.read_text().splitlines()
    hdr, data = lines[:3], [l for l in lines[3:] if l.strip()]

    def frame(xshift_ox):                       # rigid x-translation → Kabsch removes it
        out = list(hdr)
        for ln in data:
            p = ln.split()
            p[0] = f"{float(p[0]) + xshift_ox:.6f}"
            out.append(" ".join(p))
        return out

    traj = tmp_path / "traj.dat"
    traj.write_text("\n".join(frame(0.0) + frame(3.0 * NM_TO_OXDNA)) + "\n")

    frames = read_trajectory_frames_full(traj, design)
    assert len(frames) == 2

    r = production_rmsd(design, traj, ref)
    assert r["n_frames"] == 2
    assert len(r["series"]) == 2
    # Both frames are rigid transforms of the reference → RMSD ≈ 0 after alignment.
    assert r["mean"] < 0.1 and r["max"] < 0.1


def test_production_rmsf(design, geometry, tmp_path):
    """Per-base RMSF (flexibility map): a single nucleotide that moves between
    frames must show a markedly higher RMSF than the rest, and the payload carries
    a mean position + colour-ready scalar per base."""
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import write_configuration
    from backend.core.oxdna_health import production_rmsf

    ref = tmp_path / "ref.dat"
    write_configuration(design, geometry, ref, box_nm=80.0)
    lines = ref.read_text().splitlines()
    hdr, data = lines[:3], [l for l in lines[3:] if l.strip()]

    def frame(move_first_by_ox):
        out = list(hdr)
        for i, ln in enumerate(data):
            p = ln.split()
            if i == 0:                          # perturb ONLY the first nucleotide
                p[0] = f"{float(p[0]) + move_first_by_ox:.6f}"
            out.append(" ".join(p))
        return out

    traj = tmp_path / "traj.dat"
    traj.write_text("\n".join(frame(0.0) + frame(6.0 * NM_TO_OXDNA)) + "\n")

    r = production_rmsf(design, traj, ref)
    assert r["ready"] is True
    assert r["n_frames"] == 2
    assert len(r["positions"]) > 0
    p0 = r["positions"][0]
    assert {"helix_id", "bp_index", "direction", "backbone_position", "nx", "ny", "nz", "rmsf"} <= set(p0)
    # The moved base is far more flexible than the rest.
    assert r["max_rmsf"] > 0.5
    assert r["max_rmsf"] > r["min_rmsf"] + 0.4


def _write_traj(design, geometry, path, n_frames, box_nm=80.0):
    """Write a tiny oxDNA trajectory of n_frames identical frames at *path*."""
    from backend.physics.oxdna_interface import write_configuration
    tmp = path.parent / "_one.dat"
    write_configuration(design, geometry, tmp, box_nm=box_nm)
    lines = tmp.read_text().splitlines()
    hdr, data = lines[:3], [l for l in lines[3:] if l.strip()]
    out = []
    for _ in range(n_frames):
        out += hdr + data
    path.write_text("\n".join(out) + "\n")


def test_build_production_stage_custom_name():
    """Each production re-run gets its own uniquely-named stage dir."""
    from backend.core.oxdna_protocol import build_production_stage
    assert build_production_stage().name == "4_production"
    assert build_production_stage(name="5_production").kind == "production"
    assert build_production_stage(name="5_production").name == "5_production"


def test_production_rmsf_pools_multiple_trajectories(design, geometry, tmp_path):
    """Passing a LIST of production trajectories pools their frames (all runs)."""
    from backend.core.oxdna_health import production_rmsf
    ref = tmp_path / "ref.dat"
    _write_traj(design, geometry, ref, 1)
    t1 = tmp_path / "p1.dat"; _write_traj(design, geometry, t1, 2)
    t2 = tmp_path / "p2.dat"; _write_traj(design, geometry, t2, 3)
    single = production_rmsf(design, t1, ref)
    pooled = production_rmsf(design, [t1, t2], ref)
    assert single["n_frames"] == 2
    assert pooled["n_frames"] == 5            # 2 + 3 frames across both runs


def test_composite_trajectory(design, geometry, tmp_path):
    """Composite trajectory concatenates stages, sends keys once, flat float
    frames, and a transition marker at each stage boundary."""
    from backend.core.oxdna_health import composite_trajectory
    ref = tmp_path / "conf.dat"; _write_traj(design, geometry, ref, 1)
    e = tmp_path / "equil.dat";  _write_traj(design, geometry, e, 2)
    p = tmp_path / "prod.dat";   _write_traj(design, geometry, p, 3)
    stages = [("3_equil", "equil", e), ("4_production", "production", p)]
    r = composite_trajectory(design, stages, ref)
    assert r["n_frames"] == 5                       # 2 + 3
    M = r["n_nucleotides"]
    assert M > 0 and len(r["keys"]) == M
    assert all(len(f) == 6 * M for f in r["frames"])  # 6 floats (bb xyz + a1) per key
    assert [s["kind"] for s in r["stages"]] == ["equil", "production"]
    assert len(r["markers"]) == 1                   # one transition equil→production
    assert r["markers"][0]["frame"] == 2 and r["markers"][0]["kind"] == "production"


def test_composite_trajectory_downsamples_keeping_each_stage(design, geometry, tmp_path):
    """Downsampling to a small cap keeps ≥1 frame per stage + the boundary marker."""
    from backend.core.oxdna_health import composite_trajectory
    ref = tmp_path / "conf.dat"; _write_traj(design, geometry, ref, 1)
    a = tmp_path / "a.dat"; _write_traj(design, geometry, a, 20)
    b = tmp_path / "b.dat"; _write_traj(design, geometry, b, 20)
    r = composite_trajectory(design, [("3_equil", "equil", a), ("4_production", "production", b)],
                             ref, max_frames=6)
    assert r["n_frames"] <= 6
    assert all(s["n_frames"] >= 1 for s in r["stages"])
    assert len(r["markers"]) == 1


def test_oxdna_continue_production_unique_stage(monkeypatch, tmp_path):
    """A completed job that already has a production run can start ANOTHER; it
    appends a uniquely-named production stage (continues from the last run)."""
    import json as _json
    from dataclasses import asdict
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna
    from backend.core.oxdna_protocol import build_production_stage

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/fake/oxDNA")
    monkeypatch.setattr(routes_oxdna, "start_job", lambda job, ws, specs: None)

    specs = build_relaxation_stages()
    specs.append(build_production_stage(name="4_production"))   # one run already done
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    job.status = OxdnaStatus.completed
    for s in job.stages:
        s.status = "done"
    job.current_stage_idx = len(specs)
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "stages_spec.json").write_text(
        _json.dumps([asdict(s) for s in specs], indent=2))

    r = TestClient(app).post(f"/api/oxdna/jobs/{job.job_id}/production", json={"steps": 1000})
    assert r.status_code == 200
    reloaded = OxdnaJob.load(job.job_id, tmp_path)
    prod_names = [s.name for s in reloaded.stages if s.kind == "production"]
    assert prod_names == ["4_production", "5_production"]   # second run, unique name
    assert reloaded.status == OxdnaStatus.running


def test_oxdna_trajectory_not_ready_without_frames(monkeypatch, tmp_path):
    """GET /trajectory degrades gracefully when no stage has written a trajectory."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    job = new_oxdna_job("d", [s.to_status() for s in build_relaxation_stages()])
    job.save(tmp_path)
    r = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/trajectory")
    assert r.status_code == 200
    assert r.json()["ready"] is False


# ── PBC unwrap for display ────────────────────────────────────────────────────

def test_read_configuration_unwrapped(design, geometry, tmp_path):
    """A relaxed conf wrapped across the oxDNA box unwraps to a compact structure
    re-seated at the reference (design) location."""
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        write_configuration, read_configuration_full, read_configuration_unwrapped,
    )
    box_nm = 50.0
    orig = tmp_path / "conf.dat"
    write_configuration(design, geometry, orig, box_nm=box_nm)
    orig_map = read_configuration_full(orig, design)
    O = np.array([v["backbone_position"] for v in orig_map.values()])

    # Build a "relaxed" conf: rigidly ROTATE + translate the structure (simulating
    # diffusion + tumbling) and wrap into [0, box) — splitting it across a face.
    box_ox = box_nm * NM_TO_OXDNA
    th = 0.6
    rot = np.array([[np.cos(th), -np.sin(th), 0.0],
                    [np.sin(th),  np.cos(th), 0.0],
                    [0.0, 0.0, 1.0]])
    trans = np.array([box_ox - 2.0, 5.0, -3.0])
    lines_in = orig.read_text().splitlines()
    out = ["t = 0", f"b = {box_ox:.6f} {box_ox:.6f} {box_ox:.6f}", "E = 0 0 0"]
    for ln in lines_in:
        if ln.startswith(("t ", "b ", "E ")) or not ln.strip():
            continue
        p = ln.split()
        pos = rot @ np.array([float(p[0]), float(p[1]), float(p[2])]) + trans
        for i in range(3):
            p[i] = f"{pos[i] % box_ox:.6f}"   # rotate + translate + wrap
        out.append(" ".join(p))
    wrapped = tmp_path / "wrapped.dat"
    wrapped.write_text("\n".join(out) + "\n")

    raw = read_configuration_full(wrapped, design)
    R = np.array([v["backbone_position"] for v in raw.values()])
    assert (R.max(0) - R.min(0)).max() > (O.max(0) - O.min(0)).max() * 1.5  # wrapped = exploded

    unw = read_configuration_unwrapped(wrapped, design, orig)
    U = np.array([unw[k]["backbone_position"] for k in orig_map])
    # Kabsch recovers the rigid rotation+translation → the structure re-seats onto
    # the original frame (small RMSD), centroid matches.
    rmsd = float(np.sqrt(((U - O) ** 2).sum(1).mean()))
    assert rmsd < 0.5, rmsd
    assert np.allclose(U.mean(0), O.mean(0), atol=0.5)


def test_oxdna_backbone_site_widens_duplex():
    """oxdna_backbone_site reconstructs the true backbone from the CM, which sits
    inward — so paired backbones come out wider than the raw CM-CM (otherwise the
    rendered duplex collapses and the base-pair slabs overlap)."""
    from backend.physics.oxdna_interface import oxdna_backbone_site
    cm_f, cm_r = np.array([0.0, 0, 0]), np.array([1.04, 0, 0])
    a1_f, a1_r = np.array([1.0, 0, 0]), np.array([-1.0, 0, 0])   # a1 toward partner
    a3 = np.array([0.0, 0, 1.0])
    bb_f = oxdna_backbone_site(cm_f, a1_f, a3)
    bb_r = oxdna_backbone_site(cm_r, a1_r, a3)
    d_cm = float(np.linalg.norm(cm_f - cm_r))
    d_bb = float(np.linalg.norm(bb_f - bb_r))
    assert d_bb > d_cm * 1.3          # backbones meaningfully wider than CMs
    assert 1.4 < d_bb < 2.0           # ≈ real DNA backbone-backbone


# ── oxdna_health: energy parsing + convergence ────────────────────────────────

def test_parse_energy_dat(tmp_path):
    p = tmp_path / "energy.dat"
    p.write_text("0 -1.50 0.5 -1.0\n1000 -1.55 0.5 -1.05\n# comment\n2000 -1.56 0.5 -1.06\n")
    samples = parse_energy_dat(p)
    assert len(samples) == 3
    assert samples[0] == (0.0, -1.50)
    assert samples[-1][1] == pytest.approx(-1.56)


def test_energy_convergence():
    # Flat tail → converged.
    flat = [(i, -1.0 - 0.5 * (1 - np.exp(-i / 3))) for i in range(30)]
    assert energy_is_converged(flat, window=10, rel_tol=0.05)
    # Steadily dropping → not converged.
    dropping = [(i, -float(i)) for i in range(30)]
    assert not energy_is_converged(dropping, window=10, rel_tol=0.02)


# ── oxdna_health: base-pair metric (oxDNA H-bond geometry) ────────────────────

def test_base_pair_retention_formed_vs_broken():
    """The geometric proxy measures actual H-bond-range proximity at the oxDNA base
    site (CM + 0.4·a1), NOT loose partner proximity: a pair is formed only when the
    two base sites are within ~0.8 nm (calibrated to oxDNA's HBList)."""
    from backend.core.oxdna_health import base_pair_retention, OXDNA_BASE_SITE_NM
    b = OXDNA_BASE_SITE_NM
    fm = {}
    for i in range(4):
        x = i * 5.0
        # FORWARD base site at x+b; REVERSE base site at (rev_bb − b).
        fm[("h", i, "FORWARD")] = {"backbone_position": np.array([x, 0.0, 0.0]),
                                   "a1": np.array([1.0, 0, 0]), "a3": np.array([0, 0, 1.0])}
        # i<3 → base sites coincide (bonded); i==3 → 5 nm apart (broken).
        rev_bb = x + 2 * b if i < 3 else x + 5.0
        fm[("h", i, "REVERSE")] = {"backbone_position": np.array([rev_bb, 0.0, 0.0]),
                                   "a1": np.array([-1.0, 0, 0]), "a3": np.array([0, 0, -1.0])}
    frac, n = base_pair_retention(None, fm)
    assert n == 4
    assert frac == 0.75          # 3 of 4 within H-bond range


def test_bp_metric_low_on_unrelaxed_nadoc_geometry(design, geometry, tmp_path):
    """Freshly-built NADOC geometry has backbones ~1.9 nm apart → base sites ~1.25 nm
    apart → NOT hydrogen-bonded yet → the metric correctly reads LOW (it's oxDNA that
    forms the bonds during relaxation). Backbone bonds are healthy (no clash)."""
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    full_map = read_configuration_full(conf, design)
    frac, n_pairs = base_pair_retention(design, full_map)
    assert n_pairs > 0
    assert frac < 0.1            # NADOC geometry is not oxDNA-bonded

    max_d, n_clash = max_backbone_stretch(design, full_map)
    assert max_d < 1.5
    assert n_clash == 0


def test_bp_retention_drops_when_melted(design, geometry, tmp_path):
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    full_map = read_configuration_full(conf, design)
    for key, v in full_map.items():
        if key[2] == "REVERSE":
            v["backbone_position"] = v["backbone_position"] + np.array([50.0, 0.0, 0.0])
    frac, _ = base_pair_retention(design, full_map)
    assert frac < 0.05


# ── Mock oxDNA binary ─────────────────────────────────────────────────────────

_MOCK_OXDNA = '''#!/usr/bin/env python3
import sys, re, shutil
from pathlib import Path
inp = Path(sys.argv[1])
text = inp.read_text()
def val(key):
    m = re.search(r"^" + key + r"\\s*=\\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None
conf = val("conf_file")
lastconf = val("lastconf_file") or "last_conf.dat"
energy = val("energy_file") or "energy.dat"
steps = int(val("steps") or "100")
cwd = Path.cwd()
shutil.copy(conf, cwd / lastconf)
n = max(1, steps // 100)
with open(cwd / energy, "w") as f:
    for i in range(n):
        f.write(f"{i} {-1.5 - 0.001*i} 0.5 -1.0\\n")
'''


@pytest.fixture
def mock_oxdna(tmp_path, monkeypatch):
    p = tmp_path / "mock_oxdna.py"
    p.write_text(_MOCK_OXDNA)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


def _wait_terminal(job_id, workspace, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = OxdnaJob.load(job_id, workspace)
        if j.status in (OxdnaStatus.completed, OxdnaStatus.failed, OxdnaStatus.stopped):
            return j
        time.sleep(0.1)
    return OxdnaJob.load(job_id, workspace)


# ── End-to-end runner orchestration (mock binary) ─────────────────────────────

def test_runner_end_to_end(design, geometry, tmp_path, mock_oxdna):
    from backend.core import oxdna_runner

    # min_bp_retained=0: the mock copies the unrelaxed conf (no real H-bonds), so
    # this test validates the ORCHESTRATION (staging, sequential runs, completion),
    # not bp quality (the gate is covered by test_runner_gate_fails_on_melted).
    specs = build_relaxation_stages(mc_steps=100, md_relax_steps=100, equil_steps=100,
                                    min_bp_retained=0.0)
    job = new_oxdna_job("6hb", [s.to_status() for s in specs], n_nucleotides=len(geometry))
    oxdna_runner.prepare_oxdna_job(design, geometry, job, tmp_path, specs)

    # Files staged.
    jd = job.job_dir(tmp_path)
    assert (jd / "topology.top").exists()
    assert (jd / "conf.dat").exists()
    assert (jd / "design.json").exists()
    assert (jd / "stages_spec.json").exists()
    assert (jd / "forces.txt").exists()          # mutual-trap external forces

    job.status = OxdnaStatus.queued
    job.save(tmp_path)
    oxdna_runner.start_job(job, tmp_path, specs)

    done = _wait_terminal(job.job_id, tmp_path)
    assert done.status == OxdnaStatus.completed, done.error
    assert all(s.status == "done" for s in done.stages)
    assert done.current_stage_idx == 3

    # Health samples recorded for each stage, all passed (no bp gate here).
    assert len(done.health_samples) == 3
    assert all(h.passed for h in done.health_samples)
    relax = next(h for h in done.health_samples if h.stage == "2_md_relax")
    assert relax.bp_retained_fraction is not None

    # Display reads back a last_conf with orientation.
    full_map = read_configuration_full(jd / "3_equil" / "last_conf.dat", design)
    assert len(full_map) == len(read_configuration_full(jd / "conf.dat", design))


def test_runner_gate_fails_on_melted(design, geometry, tmp_path, monkeypatch):
    """If the relax stage produces a melted conf, the bp gate fails the job."""
    from backend.core import oxdna_runner

    # Mock that writes a MELTED last_conf (reverse strands shoved away).
    melt = tmp_path / "melt_oxdna.py"
    melt.write_text('''#!/usr/bin/env python3
import sys, re
from pathlib import Path
inp = Path(sys.argv[1]); text = inp.read_text()
def val(k):
    m = re.search(r"^"+k+r"\\s*=\\s*(.+)$", text, re.M); return m.group(1).strip() if m else None
conf = Path(val("conf_file")); cwd = Path.cwd()
lines = conf.read_text().splitlines()
out = []; i = 0
for ln in lines:
    if ln.startswith(("t ","b ","E ")) or not ln.strip():
        out.append(ln); continue
    p = ln.split()
    # Distinct per-nucleotide displacement so WC partners separate (melt).
    p[0] = str(float(p[0]) + (i % 7) * 8.0)
    p[1] = str(float(p[1]) + (i % 5) * 8.0)
    p[2] = str(float(p[2]) + (i % 3) * 8.0)
    out.append(" ".join(p)); i += 1
(cwd/"last_conf.dat").write_text("\\n".join(out)+"\\n")
(cwd/"energy.dat").write_text("0 -1.0 0.5 -0.5\\n")
''')
    melt.chmod(melt.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(melt))

    specs = build_relaxation_stages(mc_steps=100, md_relax_steps=100, equil_steps=100,
                                    min_bp_retained=0.80)
    job = new_oxdna_job("6hb", [s.to_status() for s in specs], n_nucleotides=len(geometry))
    oxdna_runner.prepare_oxdna_job(design, geometry, job, tmp_path, specs)
    job.status = OxdnaStatus.queued
    job.save(tmp_path)
    oxdna_runner.start_job(job, tmp_path, specs)

    done = _wait_terminal(job.job_id, tmp_path)
    assert done.status == OxdnaStatus.failed
    # Min stage has no bp gate (passes); relax stage gate catches the melt.
    assert done.stages[1].status == "failed"
    assert "retention" in (done.error or "")


# ── Real-binary end-to-end (auto-skips when oxDNA is not installed) ────────────
# Validates begin → monitor → finish statuses with the actual oxDNA executable:
# the MC (CPU) + MD (CUDA/CPU) stages, live progress, per-stage health, and a
# readable relaxed frame for the OxDNA-display toggle.

_WC = {"A": "T", "T": "A", "G": "C", "C": "G"}


def _sequence_for_oxdna(design):
    """Assign a realistic complementary sequence (standard M13 scaffold + WC-complement
    staples) so oxDNA holds the structure.  A homopolymer (all-A/all-T) is the least
    stable case and frays in the untrapped equil stage; M13+complement is what real
    designs use and what holds at ~100% retention."""
    from backend.core.models import Direction
    from backend.core.sequences import assign_scaffold_sequence

    def bp_keys(strand):
        keys = []
        for dm in strand.domains:
            lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
            rng = range(lo, hi + 1) if dm.direction == Direction.FORWARD else range(hi, lo - 1, -1)
            keys.extend((dm.helix_id, bp) for bp in rng)
        return keys

    for sid in [s.id for s in design.strands if s.strand_type.value == "scaffold"]:
        design, _, _ = assign_scaffold_sequence(design, "M13mp18", strand_id=sid)
    scaf_base = {}
    for s in design.strands:
        if s.strand_type.value == "scaffold":
            scaf_base.update(zip(bp_keys(s), s.sequence or ""))
    new = []
    for s in design.strands:
        if s.strand_type.value == "staple":
            seq = "".join(_WC.get(scaf_base.get(k, "N"), "N") for k in bp_keys(s))
            new.append(s.model_copy(update={"sequence": seq}))
        else:
            new.append(s)
    return design.model_copy(update={"strands": new})


@pytest.mark.skipif(
    __import__("backend.core.oxdna_runner", fromlist=["find_oxdna"]).find_oxdna() is None,
    reason="oxDNA binary not installed (set $OXDNA_BIN or build ~/oxDNA/build/bin/oxDNA)",
)
def test_runner_real_binary_status_lifecycle(design, geometry, tmp_path):
    """Real oxDNA run: statuses progress queued→running→completed, stages all done,
    progress is monotonic, health is recorded per stage, and the relaxed frame is
    readable for display."""
    from backend.core import oxdna_runner

    sequenced = _sequence_for_oxdna(design)
    geom = __import__("backend.api.crud", fromlist=["_geometry_for_design"])._geometry_for_design(sequenced)

    # Small step counts for a fast real run; protocol is identical to standard.
    # No bp gate — this test validates the STATUS LIFECYCLE, not physics quality.
    # bp retention now uses oxDNA's real H-bond count, which is genuinely low for a
    # short CPU run, so gating here would be flaky; the gate is covered by the melt
    # test, and bp quality by the manual long run + HBList calibration.
    specs = build_relaxation_stages(mc_steps=500, md_relax_steps=5000, equil_steps=2000,
                                    backend="CPU", min_bp_retained=0.0)
    job = new_oxdna_job("6hb_real", [s.to_status() for s in specs], n_nucleotides=len(geom))
    oxdna_runner.prepare_oxdna_job(sequenced, geom, job, tmp_path, specs)
    job.status = OxdnaStatus.queued
    job.save(tmp_path)

    assert OxdnaJob.load(job.job_id, tmp_path).status == OxdnaStatus.queued  # begin
    oxdna_runner.start_job(job, tmp_path, specs)

    # Monitor: collect status + overall-progress samples until terminal.
    seen_running = False
    last_overall = -1.0
    deadline = time.time() + 120
    while time.time() < deadline:
        j = OxdnaJob.load(job.job_id, tmp_path)
        prog = oxdna_runner.job_progress(j, tmp_path, specs)
        if j.status == OxdnaStatus.running:
            seen_running = True
        assert prog["overall"] >= last_overall - 1e-9  # monotonic non-decreasing
        last_overall = prog["overall"]
        if j.status in (OxdnaStatus.completed, OxdnaStatus.failed, OxdnaStatus.stopped):
            break
        time.sleep(0.2)

    done = OxdnaJob.load(job.job_id, tmp_path)
    assert seen_running, "never observed a running status"
    assert done.status == OxdnaStatus.completed, done.error  # finish
    assert [s.status for s in done.stages] == ["done", "done", "done"]
    assert done.current_stage_idx == 3
    assert len(done.health_samples) == 3
    # bp retention recorded per stage (oxDNA HBList ground truth — value depends on
    # run length; the lifecycle, not the quality, is what's pinned here).
    md = next(h for h in done.health_samples if h.stage == "2_md_relax")
    assert md.bp_retained_fraction is not None
    assert md.steps_per_s and md.steps_per_s > 0

    # Display path: the relaxed last_conf is readable with orientation.
    full = read_configuration_full(job.stage_dir(tmp_path, "3_equil") / "last_conf.dat", sequenced)
    assert len(full) == len(geom)
    any_v = next(iter(full.values()))
    assert "a1" in any_v and "backbone_position" in any_v


@pytest.mark.skipif(
    __import__("backend.core.oxdna_runner", fromlist=["find_dnanalysis"]).find_dnanalysis() is None,
    reason="DNAnalysis binary not installed",
)
def test_count_hbonds_ground_truth(tmp_path):
    """count_hbonds runs oxDNA's HBList and returns a valid bond count.  On the
    unrelaxed (wide) NADOC geometry oxDNA finds few/no bonds → a small int, never
    the loose-proxy's inflated number."""
    from backend.physics.oxdna_interface import write_topology, write_configuration, count_hbonds
    from backend.core.oxdna_runner import find_dnanalysis

    d = _sequence_for_oxdna(make_6hb_design())
    geom = __import__("backend.api.crud", fromlist=["_geometry_for_design"])._geometry_for_design(d)
    write_topology(d, tmp_path / "t.top")
    write_configuration(d, geom, tmp_path / "c.dat")
    n = count_hbonds(tmp_path / "c.dat", tmp_path / "t.top", find_dnanalysis())
    assert n is not None and isinstance(n, int) and n >= 0


# ── HTTP route layer (FastAPI TestClient) ─────────────────────────────────────
# Validates the sidebar's actual endpoints: router mount, the unsequenced 400
# guard, and (with a real binary) the full create → monitor → finish → display
# flow over HTTP.

def _set_active_design(d):
    from backend.api import state as design_state
    design_state.set_design(d)


def test_oxdna_available_route():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    r = TestClient(app).get("/api/oxdna/available")
    assert r.status_code == 200
    body = r.json()
    assert "available" in body and "oxdna_bin" in body


def test_oxdna_create_rejects_unsequenced(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    _set_active_design(make_6hb_design())   # unsequenced → all 'N'
    r = TestClient(app).post("/api/oxdna/jobs", json={"backend": "CPU", "autostart": False})
    assert r.status_code == 400
    assert "sequence" in r.json()["detail"].lower()


def _full_seq(strand, base="A"):
    n = sum(abs(d.end_bp - d.start_bp) + 1 for d in strand.domains)
    return base * n


def test_count_undefined_bases_all_unsequenced():
    from backend.physics.oxdna_interface import count_undefined_bases
    undef, total = count_undefined_bases(make_6hb_design())
    assert total > 0
    assert undef == total          # every base is 'N'


def test_count_undefined_bases_fully_sequenced():
    from backend.physics.oxdna_interface import count_undefined_bases
    d = make_6hb_design()
    for s in d.strands:
        s.sequence = _full_seq(s)
    undef, total = count_undefined_bases(d)
    assert total > 0
    assert undef == 0


def test_count_undefined_bases_partial():
    from backend.physics.oxdna_interface import count_undefined_bases
    d = make_6hb_design()
    for s in d.strands[1:]:         # leave the first strand unsequenced
        s.sequence = _full_seq(s)
    undef, total = count_undefined_bases(d)
    assert 0 < undef < total


def test_count_undefined_bases_excludes_reference():
    from backend.physics.oxdna_interface import count_undefined_bases
    d = make_6hb_design()
    for s in d.strands:
        s.sequence = _full_seq(s)
    d.strands[0].is_reference = True   # backdrop strand, all 'N'
    d.strands[0].sequence = None
    assert count_undefined_bases(d, exclude_reference=True)[0] == 0
    assert count_undefined_bases(d, exclude_reference=False)[0] > 0


def test_oxdna_create_rejects_partial_sequence(monkeypatch, tmp_path):
    """A design with SOME undefined bases is blocked (not just all-unsequenced)."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "find_oxdna", lambda: "/fake/oxDNA")
    d = make_6hb_design()
    for s in d.strands[1:]:            # one strand left unsequenced
        s.sequence = _full_seq(s)
    _set_active_design(d)
    r = TestClient(app).post("/api/oxdna/jobs", json={"backend": "CPU", "autostart": False})
    assert r.status_code == 400
    assert "undefined base" in r.json()["detail"].lower()


def test_oxdna_production_requires_completed(monkeypatch, tmp_path):
    """Production is rejected unless the relaxation job has completed."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    specs = build_relaxation_stages()
    job = new_oxdna_job("d", [s.to_status() for s in specs])   # status=queued
    job.save(tmp_path)
    r = TestClient(app).post(f"/api/oxdna/jobs/{job.job_id}/production", json={"steps": 1000})
    assert r.status_code == 400
    assert "completed" in r.json()["detail"].lower()


def test_oxdna_rmsd_not_ready_without_production(monkeypatch, tmp_path):
    """The RMSD endpoint reports not-ready until a production run exists."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    specs = build_relaxation_stages()
    job = new_oxdna_job("d", [s.to_status() for s in specs])   # relax stages only
    job.save(tmp_path)
    r = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/rmsd")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert "production" in body["reason"].lower()


def test_oxdna_rmsf_waiting_for_production(monkeypatch, tmp_path):
    """The flexibility-map (RMSF) endpoint is not ready until a production stage
    has FINISHED — gating the panel's toggle with 'waiting for production'."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.core.oxdna_protocol import build_production_stage
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    # No production stage at all → "no production run yet".
    specs = build_relaxation_stages()
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    job.save(tmp_path)
    r = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/rmsf").json()
    assert r["ready"] is False and "production" in r["reason"].lower()

    # Production stage present but still running → "waiting for production".
    job.stages.append(build_production_stage(steps=1000).to_status())
    job.stages[-1].status = "running"
    job.save(tmp_path)
    r2 = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/rmsf").json()
    assert r2["ready"] is False and r2["reason"] == "waiting for production"


@pytest.mark.skipif(
    __import__("backend.core.oxdna_runner", fromlist=["find_oxdna"]).find_oxdna() is None,
    reason="oxDNA binary not installed",
)
def test_oxdna_job_name_from_source_path(monkeypatch, tmp_path):
    """The job name comes from the loaded file name, not stale design.metadata.name
    (a 'save as' can leave the old name behind)."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    d = _sequence_for_oxdna(make_6hb_design())
    d.metadata.name = "stale_old_name"
    _set_active_design(d)
    r = TestClient(app).post("/api/oxdna/jobs", json={
        "backend": "CPU", "autostart": False,
        "design_source_path": "/ws/6hb_OxDNA_test.nadoc",
    })
    assert r.status_code == 200, r.text
    assert r.json()["design_name"] == "6hb_OxDNA_test"


@pytest.mark.skipif(
    __import__("backend.core.oxdna_runner", fromlist=["find_oxdna"]).find_oxdna() is None,
    reason="oxDNA binary not installed",
)
def test_oxdna_http_lifecycle(monkeypatch, tmp_path):
    """Full sidebar flow over HTTP: POST create+autostart → poll status to
    completed → GET /display returns relaxed positions."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    _set_active_design(_sequence_for_oxdna(make_6hb_design()))
    client = TestClient(app)

    created = client.post("/api/oxdna/jobs", json={
        "backend": "CPU", "mc_steps": 500, "md_relax_steps": 5000, "equil_steps": 2000,
        "min_bp_retained": 0.0, "autostart": True,
    })
    assert created.status_code == 200, created.text
    job_id = created.json()["job_id"]

    # Monitor via the status endpoint until terminal.
    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        s = client.get(f"/api/oxdna/jobs/{job_id}").json()
        status = s["status"]
        if status in ("completed", "failed", "stopped"):
            break
        time.sleep(0.3)
    assert status == "completed", status

    # Progress endpoint reports 100%.
    prog = client.get(f"/api/oxdna/jobs/{job_id}/progress").json()
    assert prog["overall"] == pytest.approx(1.0, abs=1e-6)

    # Display endpoint returns a ready frame with positions + orientation.
    disp = client.get(f"/api/oxdna/jobs/{job_id}/display").json()
    assert disp["ready"] is True
    assert disp["n_positions"] > 0
    p0 = disp["positions"][0]
    assert {"helix_id", "bp_index", "direction", "backbone_position", "nx", "ny", "nz"} <= set(p0)

    # Health endpoint returns per-stage records.
    health = client.get(f"/api/oxdna/jobs/{job_id}/health").json()
    assert len(health) == 3

    # Production: appends an unbiased MD stage and runs it to completion.
    pr = client.post(f"/api/oxdna/jobs/{job_id}/production", json={"steps": 1000})
    assert pr.status_code == 200, pr.text
    deadline = time.time() + 120
    while time.time() < deadline:
        s = client.get(f"/api/oxdna/jobs/{job_id}").json()
        if s["status"] in ("completed", "failed", "stopped"):
            break
        time.sleep(0.3)
    final = client.get(f"/api/oxdna/jobs/{job_id}").json()
    assert final["status"] == "completed", final
    assert [st["kind"] for st in final["stages"]] == ["mc", "md_relax", "equil", "production"]
    assert final["stages"][-1]["status"] == "done"


# ── Phase 2: NAMD-seed handoff ────────────────────────────────────────────────
# build_namd_seed reconstructs a NAMD starting structure from a completed oxDNA
# job's OWN design.json + latest relaxed last_conf, using the true backbone site.

def _stage_a_relaxed_job(tmp_path, design, geometry, *, write_conf=True):
    """Create an oxDNA job dir with a design.json snapshot and (optionally) a
    relaxed last_conf.dat in the final stage — the inputs build_namd_seed reads."""
    specs = build_relaxation_stages()
    job = new_oxdna_job("seed_src", [s.to_status() for s in specs],
                        n_nucleotides=len(geometry))
    job.status = OxdnaStatus.completed
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "design.json").write_text(design.model_dump_json())
    if write_conf:
        last = job.stages[-1]
        sdir = job.stage_dir(tmp_path, last.name)
        sdir.mkdir(parents=True, exist_ok=True)
        write_configuration(design, geometry, sdir / "last_conf.dat", box_nm=50.0)
    return job


def test_build_namd_seed_uses_snapshot_and_backbone_site(tmp_path, geometry):
    """build_namd_seed reads the job's OWN design.json (not the live editor design)
    and returns an AtomisticModel whose cross-pair backbone is widened toward
    B-DNA (the §18 fix), with correct provenance."""
    from backend.core.oxdna_runner import build_namd_seed

    design = _sequence_for_oxdna(make_6hb_design())
    geom = __import__("backend.api.crud", fromlist=["_geometry_for_design"])._geometry_for_design(design)
    job = _stage_a_relaxed_job(tmp_path, design, geom)

    seed = build_namd_seed(job.job_id, tmp_path)
    assert seed.source_job_id == job.job_id
    assert seed.stage_name == job.stages[-1].name
    assert seed.conf_path.name == "last_conf.dat"
    # The snapshot drove the model: same nucleotide count as the snapshot design.
    assert len(seed.atomistic_model.atoms) > 0
    assert seed.design.metadata is not None

    # The seed must carry a WIDER cross-pair duplex than the raw oxDNA centre of
    # mass — proving the backbone-site reconstruction (§18) is in the path, not
    # the collapsed ~1.0 nm CM that would clash at NAMD startup.
    from backend.core.cg_to_atomistic import read_backbone_positions
    from backend.physics.oxdna_interface import read_configuration
    bb = read_backbone_positions(seed.conf_path, design)
    cm = read_configuration(seed.conf_path, design)
    # Find any designed WC pair present in both maps.
    fwd = {(h, b) for (h, b, d) in bb if d == "FORWARD"}
    rev = {(h, b) for (h, b, d) in bb if d == "REVERSE"}
    h, b = sorted(fwd & rev)[0]
    bb_sep = float(np.linalg.norm(bb[(h, b, "FORWARD")] - bb[(h, b, "REVERSE")]))
    cm_sep = float(np.linalg.norm(cm[(h, b, "FORWARD")] - cm[(h, b, "REVERSE")]))
    assert bb_sep > cm_sep, f"backbone {bb_sep:.2f} not wider than CM {cm_sep:.2f}"


def test_build_namd_seed_missing_conf_raises(tmp_path, geometry):
    """No relaxed last_conf.dat yet → a clear FileNotFoundError (the route maps
    this to a 400)."""
    from backend.core.oxdna_runner import build_namd_seed

    design = _sequence_for_oxdna(make_6hb_design())
    geom = __import__("backend.api.crud", fromlist=["_geometry_for_design"])._geometry_for_design(design)
    job = _stage_a_relaxed_job(tmp_path, design, geom, write_conf=False)
    with pytest.raises(FileNotFoundError):
        build_namd_seed(job.job_id, tmp_path)


def _write_detached_job(tmp_path, *, production=True, production_complete=True):
    """Build a job whose runner DIED leaving status=running (server-restart case):
    relax stages have complete energy.dat + last_conf; the trailing stage's
    completeness is controlled by `production_complete`."""
    from dataclasses import asdict
    from backend.core.oxdna_protocol import build_production_stage, expected_energy_lines
    specs = list(build_relaxation_stages())
    if production:
        specs.append(build_production_stage(steps=1000))
    job = new_oxdna_job("detached", [s.to_status() for s in specs])
    # Relax stages done; the last stage left "running" (runner died before marking it).
    for i in range(len(job.stages) - 1):
        job.stages[i].status = "done"
    job.stages[-1].status = "running"
    job.current_stage_idx = len(job.stages) - 1
    job.status = OxdnaStatus.running
    job.oxdna_pid = None
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "stages_spec.json").write_text(
        __import__("json").dumps([asdict(s) for s in specs])
    )
    # Write per-stage outputs.
    for i, spec in enumerate(specs):
        sdir = job.stage_dir(tmp_path, job.stages[i].name)
        sdir.mkdir(parents=True, exist_ok=True)
        last = (i == len(specs) - 1)
        complete = (not last) or production_complete
        n = expected_energy_lines(spec) + 1 if complete else 1
        sdir.joinpath("energy.dat").write_text(
            "".join(f"{k} -1.5 0.5 -1.0\n" for k in range(n))
        )
        if complete:
            sdir.joinpath("last_conf.dat").write_text("t = 0\nb = 1 1 1\nE = 0 0 0\n")
    return job


def test_reconcile_completes_detached_finished_production(tmp_path):
    """A finished production whose runner thread died (status stuck at running) is
    recovered to completed with the production stage marked done."""
    from backend.core.oxdna_runner import reconcile_oxdna_status
    job = _write_detached_job(tmp_path, production=True, production_complete=True)
    out = reconcile_oxdna_status(OxdnaJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == OxdnaStatus.completed
    assert out.stages[-1].kind == "production"
    assert out.stages[-1].status == "done"
    # Persisted, so a re-load sees it too.
    assert OxdnaJob.load(job.job_id, tmp_path).status == OxdnaStatus.completed


def test_reconcile_interrupted_midstage_to_stopped(tmp_path):
    """A run interrupted partway through a stage (energy.dat incomplete, no
    last_conf) is recovered to stopped, not falsely completed."""
    from backend.core.oxdna_runner import reconcile_oxdna_status
    job = _write_detached_job(tmp_path, production=True, production_complete=False)
    out = reconcile_oxdna_status(OxdnaJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == OxdnaStatus.stopped
    assert out.stages[-1].status != "done"


def test_reconcile_keeps_running_when_process_still_alive(monkeypatch, tmp_path):
    """An orphaned-but-alive oxDNA process (e.g. detached by a dev-server reload)
    must NOT be mislabeled stopped — the /proc detection keeps it running."""
    import backend.core.oxdna_runner as runner
    job = _write_detached_job(tmp_path, production=True, production_complete=False)
    # Simulate the still-running orphan that the in-memory registry lost.
    monkeypatch.setattr(runner, "_external_oxdna_running", lambda j, w: True)
    out = runner.reconcile_oxdna_status(OxdnaJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == OxdnaStatus.running          # left running, not stopped
    assert OxdnaJob.load(job.job_id, tmp_path).status == OxdnaStatus.running


def test_reconcile_noop_for_terminal_job(tmp_path):
    """Completed/failed jobs are never touched by reconciliation."""
    from backend.core.oxdna_runner import reconcile_oxdna_status
    specs = build_relaxation_stages()
    job = new_oxdna_job("done", [s.to_status() for s in specs])
    job.status = OxdnaStatus.completed
    for s in job.stages:
        s.status = "done"
    job.save(tmp_path)
    out = reconcile_oxdna_status(OxdnaJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == OxdnaStatus.completed
    assert [s.status for s in out.stages] == ["done"] * len(out.stages)


def test_oxdna_list_route_reconciles_detached(monkeypatch, tmp_path):
    """GET /oxdna/jobs surfaces the recovered status so the panel re-enables
    Show RMSD / Use-as-NAMD-seed without a manual restart."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    job = _write_detached_job(tmp_path, production=True, production_complete=True)
    listed = TestClient(app).get("/api/oxdna/jobs").json()
    row = next(j for j in listed if j["job_id"] == job.job_id)
    assert row["status"] == "completed"
    assert row["stages"][-1]["status"] == "done"


def test_md_create_with_bad_oxdna_seed_returns_400(monkeypatch, tmp_path):
    """POST /md/jobs with an unknown oxdna_job_id fails fast (400) before any
    expensive solvation — the seed lookup happens up front."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_md as routes_md

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    r = TestClient(app).post("/api/md/jobs", json={
        "autostart": False,
        "oxdna_job_id": "does_not_exist",
    })
    assert r.status_code == 400
