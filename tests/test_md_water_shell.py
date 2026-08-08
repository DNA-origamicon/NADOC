"""Water-shell carve for large-design NAMD packages.

A non-globular origami (plate/cross shape) leaves most of its rectangular
solvation box as bulk water far from the DNA.  ``_carve_water_shell`` removes
that bulk so GPU-resident NAMD fits a memory-limited card.  These tests pin the
geometry filter, the salt-concentration correction, and the NVT protocol switch
the carve requires (a carved cell has vacuum corners; an NPT piston would
collapse it onto the DNA's periodic image).
"""

from __future__ import annotations

import pytest

import backend.core.namd_solvate as ns
from backend.core.namd_solvate import (
    _Water,
    _carve_water_shell,
    _ion_counts_mixed,
    _recenter_pdb_in_padded_box,
    _WATER_NUMBER_DENSITY_NM3,
)


def _dna_pdb_single_atom_at_origin() -> str:
    """A one-atom DNA PDB at (0,0,0) Å — the carve reference point."""
    return (
        "ATOM      1  P   DA  A   1       0.000   0.000   0.000  1.00  0.00      DNAA\n"
    )


def test_carve_keeps_near_drops_far():
    """Waters within shell_nm of the DNA atom survive; farther ones are dropped."""
    shell_nm = 1.5
    waters = [
        _Water(0.5, 0, 0, 0.5, 0.1, 0, 0.5, -0.1, 0),  # 0.5 nm  → keep
        _Water(1.4, 0, 0, 1.4, 0.1, 0, 1.4, -0.1, 0),  # 1.4 nm  → keep
        _Water(1.6, 0, 0, 1.6, 0.1, 0, 1.6, -0.1, 0),  # 1.6 nm  → drop
        _Water(5.0, 0, 0, 5.0, 0.1, 0, 5.0, -0.1, 0),  # 5.0 nm  → drop
    ]
    kept = _carve_water_shell(waters, _dna_pdb_single_atom_at_origin(), shell_nm)
    kept_ox = sorted(round(w.ox, 1) for w in kept)
    assert kept_ox == [0.5, 1.4]


def _pdb_atom(serial: int, x: float, y: float, z: float) -> str:
    return (
        f"ATOM  {serial:>5d}  P   DA  A{serial:>4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00      DNAA"
    )


def test_recenter_places_bbox_inside_padded_cell():
    """A DNA model in an off-centre native frame (e.g. min X far negative, plate
    symmetric about Y=0) must be translated so its whole bounding box sits inside
    the [0, span+2*pad] cell — otherwise NAMD's GPU tile-list kernel indexes a
    patch outside the grid and dies with an illegal memory access (buildTileLists).
    """
    pad_nm = 1.2
    pad_a = pad_nm * 10.0
    # Native frame: X far negative, Y symmetric about 0, Z offset — like GT_corner_v2.
    pdb = (
        "\n".join(
            [
                _pdb_atom(1, -188.9, -10.1, -3.4),  # bbox min corner
                _pdb_atom(2, 1002.8, 10.1, 1182.2),  # bbox max corner
            ]
        )
        + "\n"
    )

    out_text, (bx, by, bz) = _recenter_pdb_in_padded_box(pdb, pad_nm, "bbox")

    # Box = span + 2*pad on each axis (nm).
    assert bx == pytest.approx((1002.8 - (-188.9) + 2 * pad_a) / 10.0)
    assert by * 10 == pytest.approx((10.1 - (-10.1)) + 2 * pad_a)

    xs, ys, zs = [], [], []
    for ln in out_text.splitlines():
        if ln.startswith("ATOM"):
            xs.append(float(ln[30:38]))
            ys.append(float(ln[38:46]))
            zs.append(float(ln[46:54]))
    # Every atom is strictly inside [0, L] with the padding preserved at the low face.
    assert min(xs) == pytest.approx(pad_a)
    assert min(ys) == pytest.approx(pad_a)
    assert min(zs) == pytest.approx(pad_a)
    assert max(xs) <= bx * 10 and max(ys) <= by * 10 and max(zs) <= bz * 10
    # Centroid sits at the cell centre (cellOrigin = box/2 will enclose it).
    assert abs((min(xs) + max(xs)) / 2 - bx * 10 / 2) < 1e-6
    assert abs((min(ys) + max(ys)) / 2 - by * 10 / 2) < 1e-6


def test_recenter_keeps_the_structure_inside_the_cell_in_EVERY_box_mode():
    """The tile-list protection above is mode-independent: whatever rule sizes the cell,
    every atom must land inside it with at least the padding at each face.  ``rotation``
    is the default, so this is the case that actually ships."""
    pad_nm, pad_a = 1.2, 12.0
    pdb = (
        "\n".join(
            [
                _pdb_atom(1, -188.9, -10.1, -3.4),
                _pdb_atom(2, 1002.8, 10.1, 1182.2),
            ]
        )
        + "\n"
    )
    for mode in ("bbox", "rotation"):
        out_text, box = _recenter_pdb_in_padded_box(pdb, pad_nm, mode)
        pts = [
            (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
            for ln in out_text.splitlines()
            if ln.startswith("ATOM")
        ]
        for axis in range(3):
            lo = min(p[axis] for p in pts)
            hi = max(p[axis] for p in pts)
            assert lo >= pad_a - 1e-6, f"{mode}: atom inside the low-face padding"
            assert hi <= box[axis] * 10 - pad_a + 1e-6, (
                f"{mode}: atom past the high face"
            )
    # rotation is cubic and never smaller than bbox on any axis
    _, bb = _recenter_pdb_in_padded_box(pdb, pad_nm, "bbox")
    _, rot = _recenter_pdb_in_padded_box(pdb, pad_nm, "rotation")
    assert rot[0] == rot[1] == rot[2]
    assert all(r >= b - 1e-9 for r, b in zip(rot, bb))


def test_recenter_preserves_internal_geometry():
    """Re-centring is a pure translation — all pairwise distances are unchanged."""
    pdb = (
        "\n".join(
            [
                _pdb_atom(1, 500.0, 0.0, 500.0),
                _pdb_atom(2, 503.4, 4.0, 500.0),
            ]
        )
        + "\n"
    )
    out_text, _ = _recenter_pdb_in_padded_box(pdb, 1.2)
    coords = [
        (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
        for ln in out_text.splitlines()
        if ln.startswith("ATOM")
    ]
    import math

    d = math.dist(coords[0], coords[1])
    assert abs(d - math.dist((500, 0, 500), (503.4, 4.0, 500.0))) < 1e-6


def test_carve_distance_is_to_nearest_dna_atom():
    """Distance is measured to the *nearest* DNA atom, not the first."""
    # Two DNA atoms: origin and (10 nm, 0, 0).  A water at 9.5 nm is far from the
    # origin but only 0.5 nm from the second atom → must be kept.
    dna = (
        "ATOM      1  P   DA  A   1       0.000   0.000   0.000  1.00  0.00      DNAA\n"
        "ATOM      2  P   DA  A   2     100.000   0.000   0.000  1.00  0.00      DNAA\n"
    )
    waters = [_Water(9.5, 0, 0, 9.5, 0.1, 0, 9.5, -0.1, 0)]
    kept = _carve_water_shell(waters, dna, 1.5)
    assert len(kept) == 1


def test_carve_no_dna_reference_keeps_all():
    """With no ATOM records to carve against, all water is preserved (fail-safe)."""
    waters = [_Water(50.0, 0, 0, 50.0, 0.1, 0, 50.0, -0.1, 0)]
    assert _carve_water_shell(waters, "REMARK no atoms here\n", 1.5) == waters


def _capture_solvate_cmd(monkeypatch, tmp_path, *, water_shell_nm):
    """Drive _gmx_solvate with gmx stubbed out; return the `gmx solvate` argv it built.

    Asserts the Python carve is NOT invoked (it would raise) — a shell request must be
    satisfied by gmx's native ``-shell``, never by the full-box fill + KD-tree carve
    that OOM-crashed WSL on a large design.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd, cwd=None, hard_timeout_s=None):
        calls.append(cmd)
        (tmp_path / "solvated.gro").write_text("title\n0\n   1.0   1.0   1.0\n")

    monkeypatch.setattr(ns, "_run_watched", _fake_run)
    monkeypatch.setattr(
        ns, "_parse_gro", lambda text, progress=None: ([], (1.0, 1.0, 1.0))
    )
    monkeypatch.setattr(ns, "_find_gmx", lambda: "gmx")
    monkeypatch.setattr(
        ns,
        "_carve_water_shell",
        lambda *a, **k: pytest.fail("carve must not run when gmx -shell is used"),
    )

    pdb = (
        "ATOM      1  P   DA  A   1     500.000 500.000 500.000  1.00  0.00      DNAA\n"
        "ATOM      2  P   DA  A   2     503.400 504.000 500.000  1.00  0.00      DNAA\n"
    )
    ns._gmx_solvate(pdb, 1.2, tmp_path, water_shell_nm=water_shell_nm)
    solvate = next(c for c in calls if "solvate" in c)
    return solvate


def test_shell_request_uses_native_gmx_shell(monkeypatch, tmp_path):
    """A hydration-shell request adds `gmx solvate -shell <nm>` (no full-box fill)."""
    cmd = _capture_solvate_cmd(monkeypatch, tmp_path, water_shell_nm=0.6)
    assert "-shell" in cmd
    assert cmd[cmd.index("-shell") + 1] == "0.6000"


def test_no_shell_fills_box_without_shell_flag(monkeypatch, tmp_path):
    """No shell requested → plain fill (no -shell); the small system fits as-is."""
    # carve must not run here either — the no-shell path never carves.
    cmd = _capture_solvate_cmd(monkeypatch, tmp_path, water_shell_nm=None)
    assert "-shell" not in cmd


def _rod_pdb(n: int = 120, rise_ang: float = 3.4, width_ang: float = 44.0) -> str:
    """A high-aspect-ratio solute — the shape rotation sizing punishes hardest."""
    return "".join(
        _pdb_atom(i, j * rise_ang, (j % 2) * width_ang, 0.0) + "\n"
        for i, j in enumerate(range(n), start=1)
    )


def test_a_short_free_run_gets_a_bbox_cell():
    """Rotation sizing protects a LONG unrestrained run from the minimum-image problem.
    A relaxation ladder is restrained throughout bar one 4.8 ns stage, over which a rod
    reorients by ~4 degrees — it cannot reach its own image, and a rotation-sized cell
    costs several times the water for nothing (measured: 2hb 32.6k -> 166k atoms)."""
    from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD, resolve_box_mode

    mode, note = resolve_box_mode(_rod_pdb(), 1.2, max_atoms=10**9, free_ns=4.8)
    assert mode == "bbox"
    assert "unrestrained" in note and "not" in note.lower()
    # ...and the boundary is inclusive.
    assert (
        resolve_box_mode(
            _rod_pdb(), 1.2, max_atoms=10**9, free_ns=ROTATION_FREE_NS_THRESHOLD
        )[0]
        == "bbox"
    )


def test_a_long_free_run_still_gets_a_rotation_cell():
    from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD, resolve_box_mode

    assert (
        resolve_box_mode(
            _rod_pdb(), 1.2, max_atoms=10**9, free_ns=ROTATION_FREE_NS_THRESHOLD + 0.1
        )[0]
        == "rotation"
    )
    assert (
        resolve_box_mode(_rod_pdb(), 1.2, max_atoms=10**9, free_ns=200.0)[0]
        == "rotation"
    )


def test_unknown_free_time_sizes_for_rotation():
    """None means "no idea how long this runs free" — size for the worst case."""
    from backend.core.namd_solvate import resolve_box_mode

    assert (
        resolve_box_mode(_rod_pdb(), 1.2, max_atoms=10**9, free_ns=None)[0]
        == "rotation"
    )


def test_bbox_is_dramatically_cheaper_for_a_rod():
    """The reason this matters at all."""
    from backend.core.namd_solvate import (
        _recenter_pdb_in_padded_box,
        estimate_box_atoms,
    )

    pdb = _rod_pdb()
    _, bb = _recenter_pdb_in_padded_box(pdb, 1.2, "bbox")
    _, rot = _recenter_pdb_in_padded_box(pdb, 1.2, "rotation")
    assert estimate_box_atoms(rot, 120, 120) > 10 * estimate_box_atoms(bb, 120, 120)


def test_the_relax_ladder_declares_its_free_time_to_the_sizer():
    """Regression guard for the wiring: if prepare stops passing free_ns, every relax
    package silently goes back to paying for a rotation cell."""
    from backend.core.md_protocols import _LADDER_FREE_NS
    from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD

    assert _LADDER_FREE_NS == 4.8  # the k=0 stage, the only free one
    assert _LADDER_FREE_NS <= ROTATION_FREE_NS_THRESHOLD


def test_bulk_salt_scales_with_solvent_volume_not_box_volume():
    """Molarity is charged over the water the cell actually holds, always.

    A rotation-sized cell around an anisotropic origami is mostly empty corner, and
    a carved cell is emptier still.  Charging bulk salt for the *box* over-salts
    both.  The solvent volume is now the default, so passing it explicitly (what the
    carve path does) must be a no-op rather than a correction.
    """
    box = (60.0, 20.0, 76.0)  # full box ~ 91200 nm³
    n_waters = 1_000_000
    water_vol = n_waters / _WATER_NUMBER_DENSITY_NM3  # ~29940 nm³

    _, _, n_cl_default = _ion_counts_mixed(n_waters, 0.0, 150.0, 0.0, box)
    _, _, n_cl_explicit = _ion_counts_mixed(
        n_waters, 0.0, 150.0, 0.0, box, volume_nm3=water_vol
    )

    expected = round(150.0 * 1e-3 * ns._NA * water_vol * 1e-24)
    assert n_cl_default == expected
    assert n_cl_explicit == expected  # explicit solvent volume is now redundant

    # An override still wins when it disagrees — the carve path relies on that.
    _, _, n_cl_half = _ion_counts_mixed(
        n_waters, 0.0, 150.0, 0.0, box, volume_nm3=water_vol / 2
    )
    assert n_cl_half < n_cl_default


def test_soft_start_first_segment_only():
    """The first FREE dynamics segment runs GENTLE (2 fs, rigid bonds); rest full speed.

    A freshly built model carries residual local strain, and 4 fs + HMR blows up on it.
    exp49 measured how much protection that actually needs: a 25 ps probe as the first
    dynamics after minimisation, on ideal builds with 2 / 24 / 60 inserted crossover
    bases.  2 fs with rigid bonds survived all of them; only 4 fs failed.  The old 1 fs
    flexible-bond tier cost 2x for protection that was never needed.

    "First free" and not simply segs[0]: the Note-4 settle stage runs before it holding
    every DNA heavy atom on a stiff restraint, so no solute strain can relieve there and
    no solute RATTLE can fail there — softening it would spend the protection on the
    wrong segment.
    """
    from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

    _, segs = mgh_slow_release_segments("S")
    free = [s for s in segs if s.restraint_ref_file is None]
    assert free[0].gentle, "first free segment should be gentle"
    assert not free[0].soft, (
        "gentle is rigid-bonded — 1 fs flexible is the escape hatch"
    )
    assert not any(s.gentle or s.soft for s in free[1:]), (
        "later segments run full speed"
    )

    box = (80.0, 80.0, 200.0)
    first = _segment_conf(
        free[0], "S", box, False, fast=True, structure_psf="S_hmr.psf"
    )
    second = _segment_conf(
        free[1], "S", box, False, fast=True, structure_psf="S_hmr.psf"
    )
    # The gentle segment keeps rigid bonds but refuses the 4 fs/HMR path.
    assert "rigidBonds         all" in first and "timestep           2" in first
    assert "structure          S.psf" in first
    assert "rigidBonds         all" in second and "timestep           4" in second


def test_no_margin_on_a_carved_nvt_config():
    """A carved box never carries ``margin`` — a large margin broke NAMD's GPU tile-list
    kernel (cudaStreamSynchronize in buildTileLists) on a carved box, and a fixed cell
    has nothing for a margin to buy.  The soft start, not a margin, is what fixes the
    first-stage RATTLE crash.

    A carved package is NVT throughout (``nvt_only``), so this is structural: margin is
    emitted only alongside a barostat.  See ``md_protocols._pressure_block``.
    """
    from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

    box = (80.0, 80.0, 200.0)
    _, carved = mgh_slow_release_segments("S", nvt_only=True)
    for seg in carved:
        conf = _segment_conf(seg, "S", box, False)
        assert "\nmargin " not in conf
        assert "langevinPiston     off" in conf


def test_npt_config_carries_a_small_patch_grid_margin():
    """An NPT stage DOES carry a small margin: without it NAMD FATALs with "Periodic
    cell has become too small for original patch grid" as soon as the cell trims, which
    is exactly what a correctly filled box does in its first 300 ps.

    Small is the point — the historical GPU tile-list crash was a LARGE margin on a
    carved cell, and a correctly filled box only trims ~2-3 % of its length.
    """
    from backend.core.md_protocols import (
        NPT_MARGIN_ANG,
        _segment_conf,
        mgh_slow_release_segments,
    )

    box = (80.0, 80.0, 200.0)
    _, segs = mgh_slow_release_segments("S", nvt_only=False)
    npt_seg = next(s for s in segs if s.npt)
    conf = _segment_conf(npt_seg, "S", box, False)
    assert f"\nmargin             {NPT_MARGIN_ANG:g}\n" in conf
    assert "langevinPiston     on" in conf
    assert NPT_MARGIN_ANG <= 5.0, (
        "a large margin is what broke the GPU tile-list kernel"
    )


def test_segments_nvt_only_disables_barostat():
    """nvt_only forces every ladder stage's barostat off; default leaves it on."""
    from backend.core.md_protocols import mgh_slow_release_segments

    _, npt_segs = mgh_slow_release_segments("X", nvt_only=False)
    _, nvt_segs = mgh_slow_release_segments("X", nvt_only=True)

    assert any(s.npt for s in npt_segs), "default ladder should be NPT"
    assert all(not s.npt for s in nvt_segs), "carved ladder must be NVT throughout"
    # The RELAXATION stages are identical — only the ensemble flag changes.  A carved
    # ladder additionally has no Note-4 settle stage: that stage exists to let the
    # barostat find the box the water wants, and a carved cell never runs a barostat.
    assert [s.name for s in npt_segs if s.restraint_ref_file is None] == [
        s.name for s in nvt_segs
    ]
    assert not any(s.restraint_ref_file for s in nvt_segs)
