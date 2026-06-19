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

from tests.conftest import make_6hb_design, make_18hb_design


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


def test_render_raises_io_rate_limit():
    # Every stage must lift oxDNA's max_io safety valve, else a large design's
    # MB-scale trajectory frames trip the 1 MB/s default and abort a healthy run.
    specs = build_relaxation_stages()
    for spec in specs:
        txt = render_stage_input(spec, "t", "c")
        assert "max_io = 1000.0" in txt


# ── Large-structure validation (imported-cadnano-scale designs) ────────────────
#
# Regression guards for the 2026-06-18 "cadnano imports blow up" fixes, exercised
# at imported scale (an 18-helix bundle, ~14k nucleotides, the size of VoltronCore)
# rather than the tiny 6hb the protocol was originally tuned on.

# oxDNA2 FENE backbone potential diverges at r0+Δ = (0.7525+0.25) length units;
# a bond at/over this can't be evaluated (only the force-cap keeps oxDNA alive),
# so an unrelaxed config should never START a bond past it.
_FENE_MAX_NM = (0.7525 + 0.25) * 0.8518  # ≈ 0.854 nm


def _large_skipped_design(n_skips_per_helix: int = 6):
    """18-helix bundle (~14k nt) with skips peppered down each helix — a
    deletion-heavy, imported-cadnano-scale structure."""
    from backend.core.models import LoopSkip
    d = make_18hb_design(388)
    for h in d.helices:
        step = h.length_bp // (n_skips_per_helix + 1)
        h.loop_skips = [LoopSkip(bp_index=h.bp_start + step * (k + 1), delta=-1)
                        for k in range(n_skips_per_helix)]
    return d


def _intra_backbone_bond_lengths_nm(design, *, compact_skips):
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import backbone_bond_pairs
    geo = _geometry_for_design(design, compact_skips=compact_skips)
    pos = {(n["helix_id"], n["bp_index"], n["direction"]): np.asarray(n["backbone_position"])
           for n in geo}
    out = []
    for a, b in backbone_bond_pairs(design):
        if a[0] != b[0] or a[:3] not in pos or b[:3] not in pos:
            continue  # intra-helix only (this bundle has no crossovers)
        out.append(float(np.linalg.norm(pos[a[:3]] - pos[b[:3]])))
    return np.asarray(out)


def test_large_structure_skip_compaction_no_fene_violation():
    """At imported scale: every intra-helix backbone bond — INCLUDING the ones
    that span a deletion — stays inside oxDNA's FENE-valid range once skips are
    compacted, so the structure doesn't start the relaxation already torn."""
    design = _large_skipped_design()

    compacted = _intra_backbone_bond_lengths_nm(design, compact_skips=True)
    assert len(compacted) > 13_000                 # genuinely large
    assert compacted.max() < _FENE_MAX_NM          # no bond past FENE divergence

    # Meaningfulness: WITHOUT compaction the deletions leave ~2×-rise gaps that
    # DO violate FENE — proving the test exercises the gap the fix removes.
    default = _intra_backbone_bond_lengths_nm(design, compact_skips=False)
    assert default.max() > _FENE_MAX_NM
    assert (default > _FENE_MAX_NM).sum() >= 18 * 6  # ~one stretched bond per skip


def test_large_structure_oxdna_files_self_consistent(tmp_path):
    """Topology N, configuration data lines, and the strand-order count must all
    agree for a large skipped design — the mismatch class behind the 33,716-vs-
    14,774 miscount.  Geometry slots (empty lattice) must NOT leak into the run."""
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import (
        _strand_nucleotide_order, write_topology,
    )
    design = _large_skipped_design()
    for h in design.helices:
        h.length_bp += 40                            # imported-helix empty lattice tail

    n_order = len(_strand_nucleotide_order(design))
    n_geom = len(_geometry_for_design(design, compact_skips=True))
    assert n_geom > n_order                          # empty lattice slots exist (must not leak)

    top = tmp_path / "topology.top"
    write_topology(design, top)
    header_n = int(top.read_text().splitlines()[0].split()[0])
    assert header_n == n_order                       # topology counts real nucleotides

    conf = tmp_path / "conf.dat"
    write_configuration(design, _geometry_for_design(design, compact_skips=True), conf)
    data_lines = [ln for ln in conf.read_text().splitlines()[3:] if ln.strip()]
    assert len(data_lines) == n_order                # conf matches topology exactly


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


# ── measure_end_to_end (the AF-13 P2 constraint primitive — pure geometry) ─────

def _pos(hid, bp, direction, xyz):
    return {"helix_id": hid, "bp_index": bp, "direction": direction,
            "backbone_position": list(xyz)}




def test_measure_end_to_end_distance():
    """Euclidean distance (nm) between two landmark nucleotides' backbone sites."""
    from backend.core.oxdna_health import measure_end_to_end
    positions = [
        _pos(0, 0, "forward", (0.0, 0.0, 0.0)),
        _pos(0, 9, "forward", (3.0, 4.0, 0.0)),     # 3-4-5 triangle → 5.0 nm
        _pos(1, 0, "reverse", (0.0, 0.0, 10.0)),
    ]
    d = measure_end_to_end(positions, (0, 0, "forward"), (0, 9, "forward"))
    assert abs(d - 5.0) < 1e-9
    # Order-independent.
    assert abs(measure_end_to_end(positions, (0, 9, "forward"),
                                  (0, 0, "forward")) - 5.0) < 1e-9


def test_measure_end_to_end_normalises_direction_enum():
    """A landmark may name its direction as a Direction enum or its string value."""
    from backend.core.models import Direction
    from backend.core.oxdna_health import measure_end_to_end
    # The map keys its direction as the enum's string value ("FORWARD").
    positions = [_pos(0, 0, Direction.FORWARD.value, (0.0, 0.0, 0.0)),
                 _pos(0, 5, Direction.FORWARD.value, (0.0, 0.0, 2.0))]
    d = measure_end_to_end(positions, (0, 0, Direction.FORWARD),
                           (0, 5, Direction.FORWARD))
    assert abs(d - 2.0) < 1e-9


def test_measure_end_to_end_rejects_bad_input():
    """Empty map, identical landmarks, and an absent landmark each raise."""
    from backend.core.oxdna_health import measure_end_to_end
    positions = [_pos(0, 0, "forward", (0.0, 0.0, 0.0)),
                 _pos(0, 5, "forward", (1.0, 0.0, 0.0))]
    with pytest.raises(ValueError, match="empty"):
        measure_end_to_end([], (0, 0, "forward"), (0, 5, "forward"))
    with pytest.raises(ValueError, match="identical"):
        measure_end_to_end(positions, (0, 0, "forward"), (0, 0, "forward"))
    with pytest.raises(ValueError, match="not a nucleotide"):
        measure_end_to_end(positions, (0, 0, "forward"), (9, 9, "forward"))


# ── parse_constraint_spec + check_relaxed_constraint (AF-13 P3 — pure) ─────────

_LANDMARKS = [(0, 0, "forward"), (0, 9, "forward")]   # → 5.0 nm in _CONSTR_POS


def _constr(**over) -> dict:
    spec = {"measure": "end_to_end", "landmarks": _LANDMARKS,
            "target_nm": 5.0, "tol_nm": 0.5, "min_confidence": 50}
    spec.update(over)
    return spec


def _relaxed(n_frames, *, ready=True):
    """A synthetic read_flexibility_map output: landmarks 5.0 nm apart (3-4-5)."""
    positions = [_pos(0, 0, "forward", (0.0, 0.0, 0.0)),
                 _pos(0, 9, "forward", (3.0, 4.0, 0.0))]
    return {"ready": ready, "positions": positions if ready else [],
            "confidence": {"n_frames": n_frames, "preliminary": n_frames < 50}}


def test_parse_constraint_spec_normalises():
    from backend.core.models import Direction
    from backend.core.oxdna_health import parse_constraint_spec
    c = parse_constraint_spec(_constr(
        landmarks=[(0, 0, Direction.FORWARD), (1, 3, Direction.REVERSE)]))
    assert c["landmarks"] == [(0, 0, "FORWARD"), (1, 3, "REVERSE")]
    assert c["target_nm"] == 5.0 and c["tol_nm"] == 0.5 and c["min_confidence"] == 50
    # Idempotent on its own output.
    assert parse_constraint_spec(c) == c


def test_parse_constraint_spec_default_min_confidence():
    from backend.core.oxdna_health import RMSF_PRELIM_FRAMES, parse_constraint_spec
    c = parse_constraint_spec({"measure": "end_to_end", "landmarks": _LANDMARKS,
                               "target_nm": 5.0, "tol_nm": 0.5})
    assert c["min_confidence"] == RMSF_PRELIM_FRAMES


@pytest.mark.parametrize("spec, match", [
    ("nope", "must be a dict"),
    ({"measure": "end_to_end", "landmarks": _LANDMARKS, "target_nm": 5.0,
      "tol_nm": 0.5, "bogus": 1}, "unknown key"),
    (_constr(measure="radius"), "measure must be one of"),
    (_constr(landmarks=[(0, 0, "forward")]), "needs exactly 2 landmarks"),
    (_constr(landmarks=[(0, 0, "forward"), (0, 0, "forward")]), "identical"),
    (_constr(landmarks=[(0, "x", "forward"), (0, 9, "forward")]), "bp_index must be"),
    (_constr(landmarks=[(0, 0), (0, 9, "forward")]), "must be a .*triple"),
    (_constr(target_nm="far"), "target_nm must be a finite number"),
    (_constr(target_nm=-1.0), "target_nm must be non-negative"),
    (_constr(tol_nm=0.0), "tol_nm must be positive"),
    (_constr(tol_nm=-0.5), "tol_nm must be positive"),
    (_constr(min_confidence=0), "min_confidence must be an integer"),
    (_constr(min_confidence=2.5), "min_confidence must be an integer"),
])
def test_parse_constraint_spec_rejects(spec, match):
    from backend.core.oxdna_health import ConstraintSpecError, parse_constraint_spec
    with pytest.raises(ConstraintSpecError, match=match):
        parse_constraint_spec(spec)


def test_check_constraint_met():
    """Enough frames + within tolerance → met."""
    from backend.core.oxdna_health import check_relaxed_constraint
    r = check_relaxed_constraint(_constr(target_nm=5.0, tol_nm=0.5), _relaxed(60))
    assert r["status"] == "met" and r["met"] is True
    assert abs(r["measured_nm"] - 5.0) < 1e-9
    assert r["n_frames"] == 60 and r["min_confidence"] == 50


def test_check_constraint_unmet():
    """Enough frames but out of tolerance → unmet (met False), value still reported."""
    from backend.core.oxdna_health import check_relaxed_constraint
    r = check_relaxed_constraint(_constr(target_nm=10.0, tol_nm=0.5), _relaxed(60))
    assert r["status"] == "unmet" and r["met"] is False
    assert abs(r["measured_nm"] - 5.0) < 1e-9


def test_check_constraint_tolerance_bracket():
    """The met/unmet boundary is |measured − target| <= tol (measured = 5.0)."""
    from backend.core.oxdna_health import check_relaxed_constraint
    on = check_relaxed_constraint(_constr(target_nm=4.5, tol_nm=0.5), _relaxed(60))
    off = check_relaxed_constraint(_constr(target_nm=4.4, tol_nm=0.5), _relaxed(60))
    assert on["status"] == "met"          # |5.0 − 4.5| = 0.5 <= 0.5
    assert off["status"] == "unmet"       # |5.0 − 4.4| = 0.6 >  0.5


def test_check_constraint_low_confidence_never_met():
    """THE LOAD-BEARING GUARD: too few frames → inconclusive, met False — even
    though the measured value is squarely within tolerance."""
    from backend.core.oxdna_health import check_relaxed_constraint
    r = check_relaxed_constraint(_constr(target_nm=5.0, tol_nm=0.5), _relaxed(10))
    assert r["status"] == "inconclusive" and r["met"] is False
    assert abs(r["measured_nm"] - 5.0) < 1e-9      # within tol, yet NOT met
    assert r["n_frames"] == 10


def test_check_constraint_no_production_inconclusive():
    """No production mean structure yet → inconclusive, met False, no measurement."""
    from backend.core.oxdna_health import check_relaxed_constraint
    r = check_relaxed_constraint(_constr(), _relaxed(0, ready=False))
    assert r["status"] == "inconclusive" and r["met"] is False
    assert r["measured_nm"] is None


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


def test_delete_parent_cascades_to_field_children(monkeypatch, tmp_path):
    """Deleting a relaxed parent also deletes every electric-field child job."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_oxdna, "is_running", lambda jid: False)

    parent = new_oxdna_job("d", [])
    parent.status = OxdnaStatus.completed
    parent.save(tmp_path)
    children = []
    for _ in range(2):
        c = new_oxdna_job("d · field", [], parent_job_id=parent.job_id)
        c.status = OxdnaStatus.completed
        c.save(tmp_path)
        children.append(c)

    r = TestClient(app).delete(f"/api/oxdna/jobs/{parent.job_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_children"] == 2
    assert set(body["deleted"]) == {parent.job_id, children[0].job_id, children[1].job_id}
    for j in (parent, *children):
        assert not j.job_dir(tmp_path).exists()


def test_delete_parent_blocked_when_a_child_is_running(monkeypatch, tmp_path):
    """A running field child blocks deleting its parent (nothing is removed)."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    parent = new_oxdna_job("d", []); parent.status = OxdnaStatus.completed; parent.save(tmp_path)
    child = new_oxdna_job("d · field", [], parent_job_id=parent.job_id)
    child.status = OxdnaStatus.running; child.save(tmp_path)
    monkeypatch.setattr(routes_oxdna, "is_running", lambda jid: jid == child.job_id)

    r = TestClient(app).delete(f"/api/oxdna/jobs/{parent.job_id}")
    assert r.status_code == 400
    assert parent.job_dir(tmp_path).exists()          # nothing deleted
    assert child.job_dir(tmp_path).exists()


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


def test_oxdna_create_counts_strand_nucleotides_not_lattice(monkeypatch, tmp_path):
    """n_nucleotides must be the simulated nucleotide count (strand order), NOT
    len(geometry): the geometry endpoint emits a slot for every lattice position
    in each helix's full length_bp grid, so a helix with empty sites (the norm for
    imported cadnano designs) would over-count the real oxDNA system size."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api.crud import _geometry_for_design
    from backend.physics.oxdna_interface import _strand_nucleotide_order
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    d = _sequence_for_oxdna(make_6hb_design())
    d.helices[0].length_bp += 60          # add empty lattice slots (no strands there)
    _set_active_design(d)

    n_strand = len(_strand_nucleotide_order(d))
    n_geom = len(_geometry_for_design(d))
    assert n_geom > n_strand              # empty slots inflate the geometry count

    created = TestClient(app).post("/api/oxdna/jobs", json={"backend": "CPU", "autostart": False})
    assert created.status_code == 200, created.text
    assert created.json()["n_nucleotides"] == n_strand


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


def test_oxdna_rmsf_gating_before_frames(monkeypatch, tmp_path):
    """The flexibility-map (RMSF) endpoint reports why it isn't ready yet:
    no production stage at all → 'no production run yet'; a started production
    stage that hasn't written any frames → 'production starting — no frames yet'."""
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
    assert r["ready"] is False and r["reason"] == "no production or field run yet"

    # Production stage present + running but no trajectory.dat written yet.
    job.stages.append(build_production_stage(steps=1000).to_status())
    job.stages[-1].status = "running"
    job.save(tmp_path)
    r2 = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/rmsf").json()
    assert r2["ready"] is False and r2["reason"] == "sampling starting — no frames yet"


def test_oxdna_rmsf_available_mid_run_with_confidence(monkeypatch, tmp_path, design, geometry):
    """As soon as a STILL-RUNNING production stage has written frames, the map is
    available (not blocked) and carries a confidence block flagging it preliminary."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.physics.oxdna_interface import write_configuration
    from backend.core.oxdna_protocol import build_production_stage
    import backend.api.routes_oxdna as routes_oxdna

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    specs = build_relaxation_stages()
    prod = build_production_stage(steps=1000)
    job = new_oxdna_job("d", [s.to_status() for s in specs] + [prod.to_status()])
    # Production is RUNNING (killed/in-progress), not done.
    job.stages[-1].status = "running"
    job.save(tmp_path)

    jd = job.job_dir(tmp_path)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "design.json").write_text(design.model_dump_json())
    write_configuration(design, geometry, jd / "conf.dat", box_nm=80.0)
    sdir = job.stage_dir(tmp_path, prod.name)
    sdir.mkdir(parents=True, exist_ok=True)
    _write_traj(design, geometry, sdir / "trajectory.dat", 3)
    # An archived partial run from a prior resume must ALSO be pooled (no frames
    # lost to the resume) — 2 archived + 3 current = 5 frames.
    _write_traj(design, geometry, sdir / "trajectory.r1.dat", 2)

    r = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/rmsf").json()
    assert r["ready"] is True
    assert r["n_frames"] == 5                        # 2 archived + 3 current pooled
    assert r["production_running"] is True
    assert r["confidence"]["n_frames"] == 5
    assert r["confidence"]["preliminary"] is True   # 5 frames ≪ RMSF_PRELIM_FRAMES
    assert r["confidence"]["rel_error"] > 0


def test_rmsf_confidence_metric():
    """Statistical confidence: rel-error shrinks with frames; preliminary flips off
    once enough frames are pooled."""
    from backend.core.oxdna_health import rmsf_confidence, RMSF_PRELIM_FRAMES

    assert rmsf_confidence(0)["preliminary"] is True
    assert rmsf_confidence(0)["rel_error"] is None
    assert rmsf_confidence(1)["rel_error"] is None
    few = rmsf_confidence(8)
    many = rmsf_confidence(2000)
    assert few["preliminary"] is True
    assert many["preliminary"] is False
    assert many["rel_error"] < few["rel_error"]            # more frames → tighter
    assert rmsf_confidence(RMSF_PRELIM_FRAMES)["preliminary"] is False


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


def test_starting_conf_resumes_from_own_checkpoint(tmp_path):
    """Resume continues from the killed stage's OWN checkpoint last_conf.dat
    (keeps simulated progress), not the previous stage / design conf."""
    from backend.core import oxdna_runner
    specs = build_relaxation_stages(mc_steps=100, md_relax_steps=100, equil_steps=100)
    job = new_oxdna_job("d", [s.to_status() for s in specs])
    job.save(tmp_path)

    s0 = job.stage_dir(tmp_path, specs[0].name); s0.mkdir(parents=True, exist_ok=True)
    (s0 / "last_conf.dat").write_text("prev\n")
    s1 = job.stage_dir(tmp_path, specs[1].name); s1.mkdir(parents=True, exist_ok=True)
    (s1 / "last_conf.dat").write_text("t 0\nb 1 1 1\nE 0 0 0\n")   # partial checkpoint

    # Resuming AT the interrupted stage → its own checkpoint (progress kept).
    assert oxdna_runner._starting_conf(job, tmp_path, specs, 1, 1) == (s1 / "last_conf.dat").resolve()
    # A downstream stage (not the resume point) chains from the previous stage.
    assert oxdna_runner._starting_conf(job, tmp_path, specs, 2, 1) == (s1 / "last_conf.dat").resolve()
    # An EMPTY checkpoint is ignored → restart from the previous stage's last_conf.
    (s1 / "last_conf.dat").write_text("")
    assert oxdna_runner._starting_conf(job, tmp_path, specs, 1, 1) == (s0 / "last_conf.dat").resolve()
    # Stage 0 with no checkpoint → the design conf.
    (s0 / "last_conf.dat").unlink()
    assert oxdna_runner._starting_conf(job, tmp_path, specs, 0, 0) == (job.job_dir(tmp_path) / "conf.dat").resolve()


def test_archive_partial_outputs_preserves_frames(tmp_path):
    """Resuming a stage archives its partial trajectory/energy (so the sampled
    frames survive oxDNA's truncate-on-open) — last_conf is left as the checkpoint."""
    from backend.core.oxdna_runner import _archive_partial_outputs
    sdir = tmp_path / "5_production"; sdir.mkdir()
    (sdir / "trajectory.dat").write_text("frames-A\n")
    (sdir / "energy.dat").write_text("0 -1.5 0.5 -1.0\n")
    (sdir / "last_conf.dat").write_text("checkpoint\n")

    archived = _archive_partial_outputs(sdir)
    assert set(archived) == {"trajectory.r1.dat", "energy.r1.dat"}
    assert not (sdir / "trajectory.dat").exists()           # moved aside
    assert (sdir / "trajectory.r1.dat").read_text() == "frames-A\n"
    assert (sdir / "last_conf.dat").read_text() == "checkpoint\n"   # checkpoint untouched

    # A second resume bumps the index; an empty file is skipped.
    (sdir / "trajectory.dat").write_text("frames-B\n")
    (sdir / "energy.dat").write_text("")                    # empty → not archived
    archived2 = _archive_partial_outputs(sdir)
    assert archived2 == ["trajectory.r2.dat"]
    assert (sdir / "trajectory.r2.dat").read_text() == "frames-B\n"


def test_stage_trajectories_chronological_order(tmp_path):
    """_stage_trajectories returns archived resume parts (oldest→newest) then the
    current trajectory.dat, skipping empties — so playback scrubs in time order."""
    from backend.api.routes_oxdna import _stage_trajectories
    sdir = tmp_path / "5_production"; sdir.mkdir()
    (sdir / "trajectory.r1.dat").write_text("a\n")
    (sdir / "trajectory.r2.dat").write_text("b\n")
    (sdir / "trajectory.dat").write_text("c\n")
    (sdir / "trajectory.r3.dat").write_text("")             # empty → skipped
    names = [p.name for p in _stage_trajectories(sdir)]
    assert names == ["trajectory.r1.dat", "trajectory.r2.dat", "trajectory.dat"]


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


# ── Electric-field forces + anchors + oracle (oxDNA E-field) ──────────────────

def test_pn_to_oxdna_force():
    from backend.physics.oxdna_interface import pn_to_oxdna_force, OXDNA_FORCE_PN
    assert pn_to_oxdna_force(OXDNA_FORCE_PN) == pytest.approx(1.0)
    assert pn_to_oxdna_force(0) == 0.0


def test_resolve_anchor_particles_domain_cluster_unknown(design):
    from backend.physics.oxdna_interface import (
        resolve_anchor_particles, _strand_nucleotide_order)
    order = _strand_nucleotide_order(design)
    # Domain anchor → exactly that domain's nucleotides, valid sorted indices.
    s0 = design.strands[0]
    dom = s0.domains[0]
    n_expected = abs(dom.end_bp - dom.start_bp) + 1
    parts, keys = resolve_anchor_particles(
        design, [{"kind": "domain", "strand_id": s0.id, "domain_index": 0}])
    assert len(parts) == n_expected == len(keys)
    assert parts == sorted(parts)
    assert all(0 <= p < len(order) for p in parts)
    # Cluster anchor → all nucleotides on the cluster's helices.
    ct = design.cluster_transforms[0]
    cparts, _ = resolve_anchor_particles(design, [{"kind": "cluster", "id": ct.id}])
    expected_cluster = sum(1 for k in order if k[0] in set(ct.helix_ids))
    assert len(cparts) == expected_cluster > 0
    # Unknown id / kind → nothing (stale selection drops silently, no raise).
    assert resolve_anchor_particles(design, [{"kind": "overhang", "id": "nope"}]) == ([], [])
    assert resolve_anchor_particles(design, [{"kind": "bogus"}]) == ([], [])


def test_write_field_forces(design, geometry, tmp_path):
    from backend.physics.oxdna_interface import (
        write_field_forces, write_configuration, resolve_anchor_particles,
        pn_to_oxdna_force)
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    s0 = design.strands[0]
    anchors = [{"kind": "domain", "strand_id": s0.id, "domain_index": 0}]
    parts, _ = resolve_anchor_particles(design, anchors)
    f_ox = pn_to_oxdna_force(2.0)
    out = tmp_path / "field_forces.txt"
    info = write_field_forces(out, design, conf, field_oxdna=f_ox,
                              field_dir=[0, 0, 5], anchors=anchors)
    text = out.read_text()
    import re
    # One uniform field string force over all particles (anchored beads feel it
    # too but their stiff traps hold them — oxDNA rejects range particle-specs).
    assert text.count("type = string") == 1
    assert "particle = -1" in text
    assert f"F0 = {f_ox:.6g}" in text
    assert "dir = 0,0,1" in text                       # direction normalized
    # One static trap per anchored nucleotide, with the immobile default stiffness.
    assert text.count("type = trap") == len(parts) == info["n_anchored"]
    from backend.physics.oxdna_interface import DEFAULT_ANCHOR_STIFF
    assert DEFAULT_ANCHOR_STIFF >= 500     # immobile, not the old soft 5.0
    assert f"stiff = {DEFAULT_ANCHOR_STIFF:.6g}" in text
    trap_particles = set(map(int, re.findall(r"type = trap\nparticle = (\d+)", text)))
    assert trap_particles == set(parts)


def test_write_field_forces_returns_anchor_keys(design, geometry, tmp_path):
    """write_field_forces returns the anchored 3-tuple keys (the display's
    positional-alignment frame), one per anchored nucleotide."""
    from backend.physics.oxdna_interface import write_field_forces, write_configuration
    conf = tmp_path / "conf.dat"; write_configuration(design, geometry, conf)
    s0 = design.strands[0]
    info = write_field_forces(tmp_path / "f.txt", design, conf, field_oxdna=0.04,
                              field_dir=[1, 0, 0],
                              anchors=[{"kind": "domain", "strand_id": s0.id, "domain_index": 0}])
    assert len(info["anchor_keys"]) == info["n_anchored"]
    k0 = info["anchor_keys"][0]
    assert len(k0) == 3 and k0[2] in ("FORWARD", "REVERSE")   # [helix, bp, direction]


def test_unwrap_anchor_positional_no_rotation():
    """Field-run display alignment: anchored beads are a POSITIONAL reference
    (translated onto their design spot) but NOT a rotational one — a swing of the
    rest is preserved, not Kabsch-aligned away."""
    from backend.physics.oxdna_interface import unwrap_align_to_reference
    from backend.core.models import Design
    box = np.array([100.0, 100.0, 100.0])

    def nuc(p):
        return {"backbone_position": np.array(p, float),
                "a1": np.array([1.0, 0, 0]), "a3": np.array([0, 0, 1.0])}

    kA = ("hA", 0, "FORWARD"); kB = ("hB", 0, "FORWARD"); kF = ("hF", 0, "FORWARD")
    ref = {kA: nuc([0, 0, 0]), kB: nuc([2, 0, 0]), kF: nuc([10, 0, 0])}
    # whole thing drifted +7 in x; the free bead ALSO swung +5 in y.
    relax = {kA: nuc([7, 0, 0]), kB: nuc([9, 0, 0]), kF: nuc([17, 5, 0])}

    out = unwrap_align_to_reference(relax, ref, Design(), box,
                                    align_keys=[kA, kB], rotate=False)
    # Anchors land back on their reference positions (drift removed = positional ref).
    assert np.allclose(out[kA]["backbone_position"], [0, 0, 0], atol=1e-6)
    assert np.allclose(out[kB]["backbone_position"], [2, 0, 0], atol=1e-6)
    # The free bead's +y swing is PRESERVED (ref 10 + swing 5), not aligned away.
    assert np.allclose(out[kF]["backbone_position"], [10, 5, 0], atol=1e-6)
    # rotate=False leaves orientation vectors untouched.
    assert np.allclose(out[kF]["a1"], [1, 0, 0])


def test_field_display_aligns_to_design_not_drifted_seed(design, geometry, monkeypatch, tmp_path):
    """A field run's display must anchor onto the DESIGN geometry (origin frame),
    NOT the job's conf.dat — which is the relaxation-drifted seed.  A seed shifted
    far from origin must still display with the anchor at its design position."""
    import shutil
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna
    from backend.core.oxdna_protocol import build_field_stage
    from backend.core.constants import NM_TO_OXDNA
    from backend.physics.oxdna_interface import (
        write_configuration, read_configuration_full, resolve_anchor_particles)

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    s0 = design.strands[0]
    anchors = [{"kind": "domain", "strand_id": s0.id, "domain_index": 0}]
    parts, keys = resolve_anchor_particles(design, anchors)
    akeys = [list(k[:3]) for k in keys]

    stage = build_field_stage(name="1_field", field_oxdna=0.04, field_dir=[1, 0, 0],
                              forces_file="field_forces.txt", steps=2000)
    job = new_oxdna_job("d · field", [stage.to_status()], parent_job_id="P0",
                        efield={"force_pN": 2.0, "dir": [1, 0, 0],
                                "n_anchored": len(parts), "anchor_keys": akeys})
    job.stages[0].status = "done"; job.status = OxdnaStatus.completed; job.current_stage_idx = 1
    job.save(tmp_path)
    jd = job.job_dir(tmp_path); (jd / "design.json").write_text(design.model_dump_json())
    sd = job.stage_dir(tmp_path, "1_field"); sd.mkdir(parents=True, exist_ok=True)

    # conf.dat (the relaxed seed) + last_conf = design geometry shifted +30 oxDNA
    # units in x — i.e. the relaxation diffused the structure far from origin.
    write_configuration(design, geometry, jd / "conf.dat", box_nm=80.0)
    SHIFT_OX = 30.0
    lines = (jd / "conf.dat").read_text().splitlines()
    shifted = lines[:3]
    for ln in lines[3:]:
        if not ln.strip():
            shifted.append(ln); continue
        p = ln.split(); p[0] = f"{float(p[0]) + SHIFT_OX:.6f}"; shifted.append(" ".join(p))
    (jd / "conf.dat").write_text("\n".join(shifted) + "\n")
    shutil.copy(jd / "conf.dat", sd / "last_conf.dat")

    disp = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/display").json()
    pos = {(p["helix_id"], p["bp_index"], p["direction"]): np.array(p["backbone_position"])
           for p in disp["positions"]}
    dref = tmp_path / "dg.dat"; write_configuration(design, geometry, dref, box_nm=80.0)
    gm = read_configuration_full(dref, design)
    aset = {tuple(k) for k in akeys}
    design_ac = np.mean([gm[k]["backbone_position"] for k in aset], axis=0)
    disp_ac = np.mean([pos[k] for k in aset if k in pos], axis=0)
    # Anchor displays at the DESIGN position (~0), not the +30-oxDNA-unit drift.
    assert np.linalg.norm(disp_ac - design_ac) < 1.0
    assert abs(disp_ac[0] - design_ac[0]) < (SHIFT_OX / NM_TO_OXDNA) / 2


def test_write_field_forces_requires_anchor(design, geometry, tmp_path):
    from backend.physics.oxdna_interface import write_field_forces, write_configuration
    conf = tmp_path / "conf.dat"
    write_configuration(design, geometry, conf)
    with pytest.raises(ValueError, match="needs ≥1 anchor"):
        write_field_forces(tmp_path / "f.txt", design, conf, field_oxdna=0.04,
                           field_dir=[1, 0, 0], anchors=[])


def test_build_field_stage_and_render():
    from backend.core.oxdna_protocol import build_field_stage, render_stage_input
    st = build_field_stage(name="4_field", field_oxdna=0.04, field_dir=[1, 0, 0],
                           forces_file="field_forces_4.txt", steps=5000)
    assert st.kind == "field" and st.sim_type == "MD"
    assert st.external_forces is True
    assert st.forces_file == "field_forces_4.txt"
    assert st.max_backbone_force is None               # standard FENE, no cap
    assert st.min_bp_retained == 0.0                   # field deflects → no bp gate
    assert st.efield["force_oxdna"] == 0.04 and st.efield["dir"] == [1, 0, 0]
    txt = render_stage_input(st, "t.top", "c.dat", forces_name=st.forces_file)
    assert "external_forces = true" in txt
    assert "external_forces_file = field_forces_4.txt" in txt
    assert "max_backbone_force" not in txt


def test_measure_field_response_pass_and_fail():
    """The oracle asserts a physical property: anchors held + free moved ALONG the
    field.  It must go green when that holds and red on either failure mode."""
    from backend.core.oxdna_health import measure_field_response
    ref = [_pos(0, 0, "forward", (0, 0, 0)),   # anchor
           _pos(0, 1, "forward", (1, 0, 0)),   # anchor
           _pos(0, 8, "forward", (8, 0, 0)),   # free
           _pos(0, 9, "forward", (9, 0, 0))]   # free
    anchors = [(0, 0, "forward"), (0, 1, "forward")]

    # Anchors held, free displaced +2 nm along +z → passes.
    moved = [_pos(0, 0, "forward", (0, 0, 0)), _pos(0, 1, "forward", (1, 0, 0)),
             _pos(0, 8, "forward", (8, 0, 2)), _pos(0, 9, "forward", (9, 0, 2))]
    r = measure_field_response(moved, ref, [0, 0, 1], anchors)
    assert r["passed"] is True
    assert r["anchored_max_drift_nm"] == pytest.approx(0.0)
    assert r["free_proj_along_field_nm"] == pytest.approx(2.0)
    assert r["n_anchored"] == 2 and r["n_free"] == 2

    # Free moved OPPOSITE the field → fails (deflection check).
    against = [_pos(0, 0, "forward", (0, 0, 0)), _pos(0, 1, "forward", (1, 0, 0)),
               _pos(0, 8, "forward", (8, 0, -2)), _pos(0, 9, "forward", (9, 0, -2))]
    assert measure_field_response(against, ref, [0, 0, 1], anchors)["passed"] is False

    # Anchors dragged far → fails (anchor-held check).
    drifted = [_pos(0, 0, "forward", (0, 0, 5)), _pos(0, 1, "forward", (1, 0, 5)),
               _pos(0, 8, "forward", (8, 0, 2)), _pos(0, 9, "forward", (9, 0, 2))]
    r3 = measure_field_response(drifted, ref, [0, 0, 1], anchors)
    assert r3["passed"] is False
    assert r3["anchored_max_drift_nm"] == pytest.approx(5.0)


def test_rmsf_route_works_for_a_field_run(design, geometry, monkeypatch, tmp_path):
    """The flexibility map (RMSF) pools a field run's trajectory, not just
    production — a field CHILD job's /rmsf returns a ready map."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_oxdna as routes_oxdna
    from backend.core.oxdna_protocol import build_field_stage
    from backend.physics.oxdna_interface import write_configuration

    monkeypatch.setattr(routes_oxdna, "_WORKSPACE_DIR", tmp_path)
    stage = build_field_stage(name="1_field", field_oxdna=0.04, field_dir=[1, 0, 0],
                              forces_file="field_forces.txt", steps=2000)
    job = new_oxdna_job("d · field", [stage.to_status()], parent_job_id="P0")
    job.stages[0].status = "done"
    job.status = OxdnaStatus.completed
    job.current_stage_idx = 1
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "design.json").write_text(design.model_dump_json())
    write_configuration(design, geometry, jd / "conf.dat", box_nm=80.0)
    sd = job.stage_dir(tmp_path, "1_field"); sd.mkdir(parents=True, exist_ok=True)
    _write_traj(design, geometry, sd / "trajectory.dat", n_frames=3)

    r = TestClient(app).get(f"/api/oxdna/jobs/{job.job_id}/rmsf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready"] is True
    assert body["n_frames"] == 3
    assert len(body["positions"]) > 0
