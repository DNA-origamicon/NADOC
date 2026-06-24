"""Water-shell carve for large-design NAMD packages.

A non-globular origami (plate/cross shape) leaves most of its rectangular
solvation box as bulk water far from the DNA.  ``_carve_water_shell`` removes
that bulk so GPU-resident NAMD fits a memory-limited card.  These tests pin the
geometry filter, the salt-concentration correction, and the NVT protocol switch
the carve requires (a carved cell has vacuum corners; an NPT piston would
collapse it onto the DNA's periodic image).
"""

from __future__ import annotations

import backend.core.namd_solvate as ns
from backend.core.namd_solvate import (
    _Water,
    _carve_water_shell,
    _ion_counts_mixed,
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
        _Water(0.5, 0, 0, 0.5, 0.1, 0, 0.5, -0.1, 0),   # 0.5 nm  → keep
        _Water(1.4, 0, 0, 1.4, 0.1, 0, 1.4, -0.1, 0),   # 1.4 nm  → keep
        _Water(1.6, 0, 0, 1.6, 0.1, 0, 1.6, -0.1, 0),   # 1.6 nm  → drop
        _Water(5.0, 0, 0, 5.0, 0.1, 0, 5.0, -0.1, 0),   # 5.0 nm  → drop
    ]
    kept = _carve_water_shell(waters, _dna_pdb_single_atom_at_origin(), shell_nm)
    kept_ox = sorted(round(w.ox, 1) for w in kept)
    assert kept_ox == [0.5, 1.4]


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


def test_ion_count_volume_override_matches_water_volume():
    """Salt count scales with the supplied solvent volume, not the box volume.

    A carved cell (mostly empty box) must base its molarity on the water it
    actually contains, else it ends up over-salted.
    """
    box = (60.0, 20.0, 76.0)            # full box ~ 91200 nm³
    n_waters = 1_000_000
    water_vol = n_waters / _WATER_NUMBER_DENSITY_NM3  # ~29940 nm³

    # No override → uses the (much larger) full box volume.
    n_na_box, _, n_cl_box = _ion_counts_mixed(n_waters, 0.0, 150.0, 0.0, box)
    # Override → uses the carved water volume.
    n_na_carve, _, n_cl_carve = _ion_counts_mixed(
        n_waters, 0.0, 150.0, 0.0, box, volume_nm3=water_vol
    )

    assert n_cl_carve < n_cl_box  # less volume → fewer bulk ions
    # Carved salt count should match a direct 150 mM × water-volume calculation.
    expected = round(150.0 * 1e-3 * ns._NA * water_vol * 1e-24)
    assert n_cl_carve == expected


def test_soft_start_first_segment_only():
    """The first dynamics segment runs soft (1 fs, rigidBonds none); rest rigid.

    A freshly built model has a residual local strain that crashes 2 fs rigid-bond
    RATTLE on the first steps; the soft start relaxes it, then speed resumes.
    """
    from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

    _, segs = mgh_slow_release_segments("S")
    assert segs[0].soft, "first segment should be soft"
    assert not any(s.soft for s in segs[1:]), "later segments should be rigid"

    box = (80.0, 80.0, 200.0)
    first = _segment_conf(segs[0], "S", box, False)
    second = _segment_conf(segs[1], "S", box, False)
    assert "rigidBonds         none" in first and "timestep           1" in first
    assert "rigidBonds         all" in second and "timestep           2" in second


def test_no_explicit_margin_in_configs():
    """No explicit ``margin`` keyword — a large margin breaks NAMD's GPU tile-list
    kernel (cudaStreamSynchronize in buildTileLists) on a carved box. The soft
    start, not a margin, is what fixes the first-stage RATTLE crash."""
    from backend.core.md_protocols import _segment_conf, mgh_slow_release_segments

    box = (80.0, 80.0, 200.0)
    _, segs = mgh_slow_release_segments("S")
    conf = _segment_conf(segs[1], "S", box, False)
    assert "\nmargin " not in conf


def test_segments_nvt_only_disables_barostat():
    """nvt_only forces every ladder stage's barostat off; default leaves it on."""
    from backend.core.md_protocols import mgh_slow_release_segments

    _, npt_segs = mgh_slow_release_segments("X", nvt_only=False)
    _, nvt_segs = mgh_slow_release_segments("X", nvt_only=True)

    assert any(s.npt for s in npt_segs), "default ladder should be NPT"
    assert all(not s.npt for s in nvt_segs), "carved ladder must be NVT throughout"
    # Same number/identity of stages — only the ensemble flag changes.
    assert [s.name for s in npt_segs] == [s.name for s in nvt_segs]
