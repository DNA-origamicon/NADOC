"""The in-vacuo ENRG-MD pre-stage — Aksimentiev tutorial §3.2.

The tutorial relaxes an origami's SHAPE in vacuum before solvating: a fresh build has
all helices exactly parallel and its Holliday junctions stretched, and a short
ENM-restrained vacuum run folds it into the real chickenwire arrangement.  NADOC did all
of that inside the explicit-solvent ladder — the most expensive place to do it — until
2026-07-30.

The two things that make a vacuum run valid at all are pinned here: NO PME (Coulomb is
truncated, so there must be no reciprocal sum) and NO barostat (there is no solvent to
pressurise, and a piston on an empty cell is what collapsed the carved-box runs).

See backend/core/namd_vacuum.py and experiments/exp48_vacuum_enrgmd/REPORT.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.core.md_protocols import (
    AKSIMENTIEV_STEPS_PER_CYCLE,
    MIN_STEPS_FLOOR,
    SegmentSpec,
    VACUUM_ENRGMD_PROTOCOL,
    _common_header,
    _segment_conf,
    effective_timestep_fs,
    minimize_steps_for_atoms,
)
from backend.core.namd_vacuum import (
    VACUUM_DAMPING,
    VACUUM_MIN_HELICES,
    VACUUM_TEMP_K,
    VACUUM_TIMESTEP_FS,
    build_namd_vacuum_package,
    design_helix_count,
    vacuum_steps,
)
from tests.conftest import make_6hb_design


# ── The vacuum conf shape ─────────────────────────────────────────────────────

def test_vacuum_header_has_no_pme_and_no_periodic_cell():
    h = _common_header("x", (0.0, 0.0, 0.0), False, vacuum=True)
    assert "PME                no" in h
    assert "cellBasisVector" not in h
    assert "cellOrigin" not in h
    assert "gbis" not in h


def test_vacuum_segment_has_no_barostat_even_when_npt_is_requested():
    """A piston on an empty cell compresses it onto the solute — the carved-box
    failure mode.  Vacuum must override npt unconditionally."""
    spec = SegmentSpec(name="s", stage="v", percent=100.0, steps=100, temp=295.0,
                       damping=0.1, scale=0.5, npt=True, previous="m")
    conf = _segment_conf(spec, "x", (0.0, 0.0, 0.0), False, vacuum=True)
    assert "langevinPiston     off" in conf
    assert "langevinPistonPeriod" not in conf


def test_vacuum_never_runs_gpu_resident():
    """GPUresident sizes its tile buffers from cell-average density; there is no cell."""
    spec = SegmentSpec(name="s", stage="v", percent=100.0, steps=100, temp=295.0,
                       damping=0.1, scale=0.5, npt=False, previous="m")
    conf = _segment_conf(spec, "x", (0.0, 0.0, 0.0), False, vacuum=True,
                         fast=True, n_atoms=10_000_000)
    assert "GPUresident" not in conf


def test_push_bonds_file_is_wired_as_an_extra_bonds_file():
    spec = SegmentSpec(name="s", stage="v", percent=100.0, steps=100, temp=295.0,
                       damping=0.1, scale=0.5, npt=False, previous="m")
    conf = _segment_conf(spec, "x", (0.0, 0.0, 0.0), False, vacuum=True,
                         push_bonds_file="x_push.exb")
    assert "extraBonds         on" in conf
    assert "extraBondsFile     x_push.exb" in conf


# ── Step counts ───────────────────────────────────────────────────────────────

def test_vacuum_steps_are_half_a_nanosecond_and_cycle_aligned():
    """exp48: plateau at 0.03-0.64 ns across 2hb/6hb/24hb, so 0.5 ns is ample.  The
    chapter's "less than 2 ns" is an upper bound — its own step-2 script runs ~40 ps."""
    steps = vacuum_steps(0.5, VACUUM_TIMESTEP_FS)
    assert steps == 250_000
    assert steps % AKSIMENTIEV_STEPS_PER_CYCLE == 0


def test_minimisation_scales_with_atom_count():
    """Tutorial Note 2 blames RATTLE failures on under-minimisation; exp48 measured a
    224k-atom build detonating ~130k steps in after a fixed 4800."""
    assert minimize_steps_for_atoms(3_043) == MIN_STEPS_FLOOR      # floor holds
    assert minimize_steps_for_atoms(224_261) > 22_000              # ~1 step per 10 atoms
    assert minimize_steps_for_atoms(224_261) % AKSIMENTIEV_STEPS_PER_CYCLE == 0


def test_effective_timestep_matches_what_the_conf_will_use():
    soft = SegmentSpec(name="s", stage="v", percent=100.0, steps=1, temp=300.0,
                       damping=5.0, scale=None, npt=False, previous="", soft=True)
    hard = SegmentSpec(name="s", stage="v", percent=100.0, steps=1, temp=300.0,
                       damping=5.0, scale=None, npt=False, previous="", soft=False)
    assert effective_timestep_fs(soft, fast=True) == 1.0
    assert effective_timestep_fs(hard, fast=True) == 4.0
    assert effective_timestep_fs(hard, fast=False) == 2.0


# ── A real package ────────────────────────────────────────────────────────────

def test_builds_a_dry_package_for_a_6hb(tmp_path: Path):
    design = make_6hb_design(length_bp=42)
    subdir, stem, segments = build_namd_vacuum_package(design, tmp_path, ns=0.5)
    pkg = tmp_path / subdir

    # Dry: topology + coordinates, and NOTHING solvent-related.
    assert (pkg / f"{stem}.psf").exists()
    assert (pkg / f"{stem}.pdb").exists()
    assert not (pkg / "mgh_extrabonds.txt").exists()
    assert not list(pkg.glob("*.gro"))

    manifest = json.loads((pkg / "manifest.json").read_text())
    assert manifest["protocol"] == VACUUM_ENRGMD_PROTOCOL
    assert manifest["solvent"]["model"] == "vacuum"
    assert manifest["box_ang"] is None
    assert manifest["mgh_extrabonds"] is False
    assert manifest["helices"] == 6

    assert len(segments) == 1
    seg = segments[0]
    assert seg.npt is False
    assert seg.damping == VACUUM_DAMPING
    assert seg.temp == VACUUM_TEMP_K
    assert seg.timestep_fs == VACUUM_TIMESTEP_FS

    conf = (pkg / f"{seg.name}.conf").read_text()
    assert "PME                no" in conf
    assert "langevinPiston     off" in conf
    assert f"langevinDamping    {VACUUM_DAMPING:g}" in conf
    assert "rigidBonds         all" in conf


def test_a_two_helix_design_yields_no_push_bonds(tmp_path: Path):
    """Not a failure: the rule needs a >22 nt crossover-free span, and a 2hb has none.
    exp48 measured exactly this (2hb → 0, 6hb → 11, 24hb → 495)."""
    from tests.conftest import make_minimal_design

    design = make_minimal_design()
    _subdir, _stem, _segments = build_namd_vacuum_package(design, tmp_path, ns=0.5)
    manifest = json.loads((tmp_path / _subdir / "manifest.json").read_text())
    assert manifest["push_bonds"]["n_bonds"] == 0
    assert "none qualify" in manifest["push_bonds"]["reason"]
    # ...and with no push bonds there is no file to reference.
    assert "push_bonds" not in manifest["files"]


def test_helix_count_drives_the_skip_prompt_threshold():
    """Below VACUUM_MIN_HELICES the step is measurably counter-productive — a 2hb's
    rotation box GREW 6.8 % — so the UI asks before running it."""
    assert VACUUM_MIN_HELICES == 4
    assert design_helix_count(make_6hb_design(length_bp=42)) == 6
    assert design_helix_count(make_6hb_design(length_bp=42)) >= VACUUM_MIN_HELICES


# ── The hand-off to solvation ─────────────────────────────────────────────────

def test_the_prestage_never_runs():
    """RETIRED 2026-07-30.  NADOC geometry is derived from topology + B-DNA constants +
    deformations, so a design never arrives as an abstract parallel-helix lattice the way
    a caDNAno file does — measured: a 90-degree design's ideal build already holds ~98.5
    degrees of per-helix bend.  And the step was not neutral: its interhelical repulsion
    surrogate needs a >22 nt crossover-free span while honeycomb crossovers recur every
    21 nt, so dense bundles got ZERO push bonds and swelled 5.6-10% under unscreened,
    truncated Coulomb — away from the Mg-screened equilibrium the ladder converges on.

    Pinned as a hard False rather than deleted: the builder stays dormant and revivable,
    and this is where the decision is visible to anyone re-enabling it.
    """
    from backend.api.routes_md import CreateJobRequest, _wants_vacuum_prestage

    design = object()
    assert _wants_vacuum_prestage(CreateJobRequest(), design) is False
    for update in ({"skip_vacuum_prestage": False}, {"relax_preset": "standard"},
                   {"relax_preset": "fast_shape"}, {"protocol": "equilibrium_aware_namd"}):
        assert _wants_vacuum_prestage(
            CreateJobRequest().model_copy(update=update), design) is False


def test_the_retired_preset_is_not_offered():
    from backend.core.md_presets import FAST_SHAPE, preset_catalogue

    entry = next(p for p in preset_catalogue() if p["id"] == FAST_SHAPE)
    assert entry["available"] is False
    assert entry["unavailable_reason"]


def test_seed_refuses_an_atom_count_mismatch(tmp_path: Path, monkeypatch):
    """A wrong-length coordinate array would be assigned to the wrong atoms and
    scramble the whole structure — it must fail loudly, not seed."""
    import numpy as np
    import pytest

    from backend.core import namd_vacuum as nv

    pkg = tmp_path / "pkg"
    (pkg / "output").mkdir(parents=True)
    (pkg / "x.psf").write_text("PSF\n")
    (pkg / "x.pdb").write_text(
        "ATOM      1  P   DA  A   1       0.000   0.000   0.000\n" * 5)
    (pkg / "manifest.json").write_text(json.dumps({"segments": [{"name": "seg"}]}))
    (pkg / "output" / "seg.coor").write_bytes(b"\x00")

    class _Job:
        name_stem = "x"

        def package_dir(self, _ws):
            return pkg

    class _Atoms:
        positions = np.zeros((3, 3))       # 3 atoms vs the PDB's 5

    class _U:
        atoms = _Atoms()

        def __init__(self, *a, **k):
            pass

    import backend.core.md_job as md_job
    monkeypatch.setattr(md_job.MdJob, "load", classmethod(lambda cls, j, w: _Job()))
    import MDAnalysis
    monkeypatch.setattr(MDAnalysis, "Universe", _U)

    with pytest.raises(RuntimeError, match="atom-count mismatch"):
        nv.build_namd_seed_from_vacuum("jid", tmp_path)
