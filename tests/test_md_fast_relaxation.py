"""Fast-relaxation lever: HMR PSF + GPU-resident + 4 fs (capped-box NPT speedup)."""
from pathlib import Path

import pytest

import backend.core.md_protocols as M

# Minimal PSF: one DNA carbon with 4 H + one TIP3 water (O + 1 H shown).
_PSF = """PSF

       1 !NTITLE
 REMARKS test

       7 !NATOM
       1 SOL  1    DNA  C    CT   -0.300000       12.0110           0
       2 SOL  1    DNA  H1   HA    0.100000        1.0080           0
       3 SOL  1    DNA  H2   HA    0.100000        1.0080           0
       4 SOL  1    DNA  H3   HA    0.100000        1.0080           0
       5 SOL  1    DNA  H4   HA    0.100000        1.0080           0
       6 W    2    TIP3 OH2  OT   -0.834000       15.9994           0
       7 W    2    TIP3 H1   HT    0.417000        1.0080           0

       5 !NBOND: bonds
       1       2       1       3       1       4       1       5       6       7
"""


def _masses(psf_text: str) -> dict[int, float]:
    out = {}
    in_atoms = False
    for line in psf_text.splitlines():
        if "!NATOM" in line:
            in_atoms = True
            continue
        if "!NBOND" in line:
            break
        if in_atoms and line.split():
            t = line.split()
            out[int(t[0])] = float(t[7])
    return out


def test_write_hmr_psf_heavy_residues_scale_up_and_skip_hmr(tmp_path: Path):
    """heavy_residues (dangling extra bases) are NOT HMR-lightened — every atom is scaled
    UP by heavy_factor from physical mass, to slow their fast heavy-atom modes below the
    4 fs limit. Water untouched; the residue's H are not repartitioned."""
    src = tmp_path / "s.psf"
    dst = tmp_path / "s_heavy.psf"
    src.write_text(_PSF)

    # mark the DNA residue (segid SOL, resid 1) heavy
    n = M.write_hmr_psf(src, dst, heavy_residues={("SOL", "1")}, heavy_factor=8.0)
    assert n == 0  # no H repartitioned — the only DNA residue is heavy, water is skipped

    m = _masses(dst.read_text())
    assert abs(m[1] - 12.011 * 8.0) < 1e-3   # carbon scaled x8 from physical (NOT lightened)
    assert abs(m[2] - 1.008 * 8.0) < 1e-3    # each H scaled x8 (NOT the 3.024 HMR value)
    assert abs(m[6] - 15.9994) < 1e-4        # water O untouched
    assert abs(m[7] - 1.008) < 1e-4          # water H untouched
    # column widths preserved
    assert [len(l) for l in _PSF.splitlines()] == [len(l) for l in dst.read_text().splitlines()]


def test_write_hmr_psf_conserves_mass_and_skips_water(tmp_path: Path):
    src = tmp_path / "s.psf"
    dst = tmp_path / "s_hmr.psf"
    src.write_text(_PSF)

    n = M.write_hmr_psf(src, dst)
    assert n == 4  # 4 DNA hydrogens; water H skipped

    m = _masses(dst.read_text())
    assert abs(m[2] - 3.024) < 1e-3              # H 1.008 -> 3.024
    assert abs(m[1] - (12.011 - 4 * 2.016)) < 1e-3  # C loses 4 * 2.016
    assert abs(m[6] - 15.9994) < 1e-4            # water O untouched
    assert abs(m[7] - 1.008) < 1e-4              # water H untouched

    assert abs(sum(_masses(_PSF).values()) - sum(m.values())) < 1e-6  # total conserved

    # column widths preserved → atom block byte-identical except mass tokens
    orig_lines = _PSF.splitlines()
    new_lines = dst.read_text().splitlines()
    assert [len(l) for l in orig_lines] == [len(l) for l in new_lines]


def test_segment_conf_fast_hard_segment_uses_gpu_resident_hmr_4fs():
    _, segs = M.mgh_slow_release_segments("S", timestep_fs=4.0)
    hard = next(s for s in segs if not s.soft)
    conf = M._segment_conf(hard, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, structure_psf="S_hmr.psf")
    assert "GPUresident        on" in conf
    assert "timestep           4" in conf
    assert "S_hmr.psf" in conf and "structure          S_hmr.psf" in conf


def test_segment_conf_soft_segment_ignores_fast():
    # The soft strain-relief segment must stay 1 fs / unmodified PSF / standard CUDA
    # even when fast mode is requested (HMR + 4 fs need rigid bonds).
    _, segs = M.mgh_slow_release_segments("S", timestep_fs=4.0)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, structure_psf="S_hmr.psf")
    assert "GPUresident" not in conf
    assert "timestep           1" in conf
    assert "structure          S.psf" in conf  # original PSF, not HMR


def test_default_path_unchanged():
    # fast=False must reproduce the classic 2 fs standard-CUDA conf.
    _, segs = M.mgh_slow_release_segments("S")           # default 2 fs
    hard = next(s for s in segs if not s.soft)
    conf = M._segment_conf(hard, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True)
    assert "GPUresident" not in conf
    assert "timestep           2" in conf
    assert "structure          S.psf" in conf


def test_fast_mode_halves_steps_to_hold_ns_per_stage():
    _, slow = M.mgh_slow_release_segments("S", timestep_fs=2.0)
    _, fast = M.mgh_slow_release_segments("S", timestep_fs=4.0)
    # same number of segments, fast steps ~= half (same simulated ns)
    assert len(slow) == len(fast)
    slow_total = sum(s.steps for s in slow)
    fast_total = sum(s.steps for s in fast)
    assert abs(fast_total - slow_total / 2) / slow_total < 0.01


def test_base_name_stem_ignores_hmr_sibling(tmp_path: Path):
    """Regression: a package ships both {stem}.psf and {stem}_hmr.psf; the base
    stem must be derived from the non-_hmr file regardless of glob order, else
    downstream "{name_stem}.pdb" lookups open a nonexistent "{stem}_hmr.pdb"."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    # Write the _hmr sibling FIRST so a naive glob could return it first.
    (pkg / "2hb_noT_hmr.psf").write_text("hmr")
    (pkg / "2hb_noT.psf").write_text("base")
    assert M._base_name_stem(pkg) == "2hb_noT"


def test_base_name_stem_raises_without_base(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "x_hmr.psf").write_text("hmr")   # only a derived psf, no base
    with pytest.raises(RuntimeError):
        M._base_name_stem(pkg)
