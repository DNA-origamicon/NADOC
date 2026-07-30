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
    # The soft strain-relief segment must stay 1 fs / unmodified PSF even when fast mode
    # is requested (HMR + 4 fs need rigid bonds).  GPU-resident is NOT part of that
    # bundle — see test_segment_conf_soft_segment_still_gets_gpu_resident.
    # soft=True is now reached only via force_soft (or the runner's post-RATTLE
    # rewrite); the DEFAULT first segment is the gentle 2 fs tier — see exp49.
    _, segs = M.mgh_slow_release_segments("S", soft=True, timestep_fs=4.0)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, structure_psf="S_hmr.psf")
    assert "timestep           1" in conf
    assert "structure          S.psf" in conf  # original PSF, not HMR


def test_segment_conf_soft_segment_still_gets_gpu_resident():
    """GPU-resident is gated INDEPENDENTLY of fast/soft.

    It used to be `fast and (...)`, so every declash/force_soft package ran its whole
    ladder on CUDA-offload however large.  Measured on an RTX 3080 Ti with the soft
    integrator (1 fs, rigidBonds none), +p16, startup excluded — resident/offload ms/step:
    111k 1.544/1.749, 181k 2.507/3.338, 770k 16.16/32.10, 3.14M 39.0/125.6.  A one-cycle
    probe of the soft conf with `GPUresident on` runs clean ("Info: Running with
    GPU-resident mode", T flat at 299-301 K), so nothing about rigidBonds none forbids it.

    The gain scales UP with N, so SMALL systems are excluded — see
    test_segment_conf_small_system_stays_offload.
    """
    # soft=True is now reached only via force_soft (or the runner's post-RATTLE
    # rewrite); the DEFAULT first segment is the gentle 2 fs tier — see exp49.
    _, segs = M.mgh_slow_release_segments("S", soft=True, timestep_fs=4.0)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, structure_psf="S_hmr.psf")
    assert "GPUresident        on" in conf
    # ...and the soft integrator itself is untouched by that.
    assert "rigidBonds         none" in conf
    assert "timestep           1" in conf


def test_segment_conf_soft_gets_resident_even_with_fast_off():
    """The declash path calls through with fast=False — the real-world case."""
    _, segs = M.mgh_slow_release_segments("S", soft=True)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=False)
    assert "GPUresident        on" in conf
    assert "timestep           1" in conf


def test_segment_conf_small_system_stays_offload():
    """Below _RESIDENT_MIN_ATOMS, GPU-resident is a measured LOSS — not a win.

    On an RTX 3080 Ti at 32.5k atoms (+p16, 1 fs soft): relax 0.862 resident vs 0.840
    offload ms/step (3% slower), unrestrained production 1.266 vs 1.116 (13% slower).
    Both modes are already at a ~0.84 ms/step floor set by fixed per-step kernel-launch
    cost, and resident's extra setup is pure overhead there.
    """
    _, segs = M.mgh_slow_release_segments("S", soft=True)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=False, n_atoms=32_566)
    assert "GPUresident" not in conf
    # ...but the integrator itself is unaffected by the size gate.
    assert "rigidBonds         none" in conf
    assert "timestep           1" in conf


def test_segment_conf_large_system_gets_gpu_resident():
    """111k already wins (1.544 vs 1.749 ms/step); 3.14M wins 3.2x."""
    _, segs = M.mgh_slow_release_segments("S", soft=True)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=False, n_atoms=3_139_238)
    assert "GPUresident        on" in conf


def test_unknown_atom_count_does_not_block_resident():
    """n_atoms=None means 'unknown', not 'small' — only a KNOWN small count gates it off."""
    _, segs = M.mgh_slow_release_segments("S", soft=True)
    soft = next(s for s in segs if s.soft)
    conf = M._segment_conf(soft, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=False, n_atoms=None)
    assert "GPUresident        on" in conf


def test_psf_atom_count_reads_natom_past_a_long_ntitle_block(tmp_path):
    """psfgen emits one REMARKS line per patch, so !NATOM can sit far past 64 KB."""
    psf = tmp_path / "d.psf"
    psf.write_text("PSF\n\n" + "".join(f"REMARKS patch {i}\n" for i in 5000 * [0])
                   + "\n 1228804 !NATOM\n")
    assert M.psf_atom_count(psf) == 1_228_804


def test_psf_atom_count_returns_none_when_missing(tmp_path):
    psf = tmp_path / "d.psf"
    psf.write_text("PSF\n\n 3 !NTITLE\n")
    assert M.psf_atom_count(psf) is None
    assert M.psf_atom_count(tmp_path / "nope.psf") is None


def test_gbis_never_gets_gpu_resident():
    """The one blanket incompatibility: GPU-resident has no implicit-solvent path."""
    _, segs = M.mgh_slow_release_segments("S", timestep_fs=4.0)
    hard = next(s for s in segs if not s.soft)
    conf = M._segment_conf(hard, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, gbis=True, structure_psf="S_hmr.psf")
    assert "GPUresident" not in conf


def test_default_path_keeps_2fs_and_stock_psf():
    # fast=False must reproduce the classic 2 fs / unmodified-PSF conf.  It now also runs
    # GPU-resident (decoupled from fast) — the 2 fs and the PSF are what `fast` governs.
    _, segs = M.mgh_slow_release_segments("S")           # default 2 fs
    hard = next(s for s in segs if not s.soft)
    conf = M._segment_conf(hard, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True)
    assert "timestep           2" in conf
    assert "structure          S.psf" in conf
    assert "GPUresident        on" in conf


def test_segment_conf_carved_but_wellfilled_keeps_gpu_resident():
    # A carved cell that is still WELL-FILLED (tight box the structure fills) runs
    # GPU-resident — the old blanket "carved -> no resident" was over-broad. The
    # one-cycle resident probe is the runtime backstop for a wrong fill estimate.
    _, segs = M.mgh_slow_release_segments("S", timestep_fs=4.0)
    hard = next(s for s in segs if not s.soft)
    conf = M._segment_conf(hard, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, carved=True, fill_fraction=0.95,
                           structure_psf="S_hmr.psf")
    assert "GPUresident        on" in conf


def test_segment_conf_carved_sparse_cell_stays_offload():
    # A big-box concave carve (vacuum corners, low fill) must NOT attempt resident —
    # it would die at step 0 on the exclusion count. Preserves the old offload path.
    _, segs = M.mgh_slow_release_segments("S", timestep_fs=4.0)
    hard = next(s for s in segs if not s.soft)
    conf = M._segment_conf(hard, "S", (100.0, 90.0, 80.0), mgh_extrabonds=True,
                           fast=True, carved=True, fill_fraction=0.30,
                           structure_psf="S_hmr.psf")
    assert "GPUresident" not in conf


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
