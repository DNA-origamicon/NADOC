"""Tests for solvation ion placement — esp. the MgH (Mg(H2O)6) path that used to
go quadratic and freeze the prep on origami-scale systems (VoltronCore, ~1.5 M
waters).  See namd_solvate._place_ions_mixed_mgh.
"""

from __future__ import annotations

import time

from backend.core.namd_solvate import (
    _Water,
    _place_ions_mixed,
    _place_ions_mixed_mgh,
)


def _grid_waters(nx: int, ny: int, nz: int, spacing: float = 0.3) -> list[_Water]:
    """A cubic lattice of waters with unique O positions (handy as identities)."""
    out: list[_Water] = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                x, y, z = i * spacing, j * spacing, k * spacing
                out.append(_Water(x, y, z, x + 0.01, y, z, x, y + 0.01, z))
    return out


def _round_xyz(t):
    return tuple(round(c, 4) for c in t)


def test_mgh_counts_and_six_waters_per_cluster():
    waters = _grid_waters(20, 20, 20)  # 8000 waters
    n_na, n_mg, n_cl = 100, 30, 120
    rem, na, mg, cl, clusters = _place_ions_mixed_mgh(waters, n_na, n_mg, n_cl, seed=1)

    assert mg == []  # MGH path returns clusters, not bare Mg
    assert len(clusters) == n_mg
    assert len(na) == n_na
    assert len(cl) == n_cl
    # Each cluster consumes its center + 5 neighbours = 6 waters; ions take 1 each.
    assert len(rem) == len(waters) - (6 * n_mg + n_na + n_cl)


def test_mgh_sites_are_disjoint_from_each_other_and_remaining():
    waters = _grid_waters(20, 20, 20)
    rem, na, _mg, cl, clusters = _place_ions_mixed_mgh(waters, 80, 20, 80, seed=5)

    consumed = (
        [_round_xyz(p) for p in na]
        + [_round_xyz(p) for p in cl]
        + [_round_xyz(c.mg) for c in clusters]
    )
    # No ion/center reuses the same water site.
    assert len(set(consumed)) == len(consumed)
    # And none of them survive in the remaining-water set.
    rem_set = {_round_xyz((w.ox, w.oy, w.oz)) for w in rem}
    assert rem_set.isdisjoint(set(consumed))


def test_mgh_deterministic_for_a_seed():
    waters = _grid_waters(15, 15, 15)
    a = _place_ions_mixed_mgh(waters, 50, 10, 50, seed=7)
    b = _place_ions_mixed_mgh(waters, 50, 10, 50, seed=7)
    assert a[1] == b[1]  # na positions
    assert a[3] == b[3]  # cl positions
    assert [c.mg for c in a[4]] == [c.mg for c in b[4]]


def test_mgh_handles_zero_mg_and_zero_ions():
    waters = _grid_waters(10, 10, 10)
    rem, na, mg, cl, clusters = _place_ions_mixed_mgh(waters, 0, 0, 0, seed=1)
    assert clusters == [] and na == [] and cl == [] and mg == []
    assert len(rem) == len(waters)


def test_mgh_raises_when_too_few_waters():
    import pytest

    waters = _grid_waters(4, 4, 4)  # 64 waters
    with pytest.raises(RuntimeError, match="Not enough water"):
        _place_ions_mixed_mgh(waters, 10, 10, 10, seed=1)  # needs 10+10+60 = 80


def test_mgh_reports_progress():
    waters = _grid_waters(15, 15, 15)
    seen: list[str] = []
    _place_ions_mixed_mgh(
        waters, 50, 20, 50, seed=2, progress=lambda k, f, m="": seen.append(k)
    )
    assert "assemble" in seen


def test_mixed_routes_to_mgh_when_hexahydrate():
    waters = _grid_waters(15, 15, 15)
    rem, na, mg, cl, clusters = _place_ions_mixed(
        waters, 40, 12, 40, seed=3, mg_hexahydrate=True
    )
    assert len(clusters) == 12 and mg == []  # clusters, not bare Mg


def test_mgh_does_not_go_quadratic_at_scale():
    """The old impl rebuilt a tuple of the whole water set per ion + sorted all
    waters per cluster — minutes at this size.  The KDTree+shuffle path is ~linear.
    """
    waters = _grid_waters(40, 40, 40)  # 64000 waters
    t0 = time.monotonic()
    rem, na, _mg, cl, clusters = _place_ions_mixed_mgh(waters, 3000, 300, 3000, seed=3)
    dt = time.monotonic() - t0
    assert len(clusters) == 300 and len(na) == 3000 and len(cl) == 3000
    assert len(rem) == len(waters) - (6 * 300 + 3000 + 3000)
    assert dt < 10.0, f"ion placement took {dt:.1f}s — quadratic regression?"


# ── Solute-biased Mg seeding ──────────────────────────────────────────────────
# The tutorial inserts MGHH into the DRY system before solvating, "because MGHH2+
# molecules diffuse slowly, it is beneficial to place them initially in proximity to
# the DNA origami structure" (Methods Mol Biol 1811 §3.3).  Uniform placement leaves
# the divalent atmosphere to form by diffusion, which will not happen in 19 ns.


def _p_atom_pdb(points_nm) -> str:
    """A minimal PDB of phosphorus atoms at the given nm positions."""
    out = []
    for i, (x, y, z) in enumerate(points_nm, start=1):
        out.append(
            f"ATOM  {i:5d}  P   DA  A{i:4d}    "
            f"{x * 10.0:8.3f}{y * 10.0:8.3f}{z * 10.0:8.3f}  1.00  0.00           P"
        )
    return "\n".join(out)


def _dist(a, b) -> float:
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


def test_mg_clusters_are_seeded_near_the_backbone():
    """Mg centres land in the hydration shell; the bulk stays for water and Cl-."""
    waters = _grid_waters(20, 20, 20)  # 8000 waters spanning ~5.7 nm
    # A "backbone" running up one edge of the box.
    backbone = [(0.0, 0.0, k * 0.3) for k in range(20)]
    pdb = _p_atom_pdb(backbone)

    _rem, _na, _mg, _cl, clusters = _place_ions_mixed_mgh(
        waters, 0, 20, 0, seed=7, dna_pdb_text=pdb
    )

    assert len(clusters) == 20
    near = [min(_dist(c.mg, p) for p in backbone) for c in clusters]
    assert max(near) <= 1.25, f"a cluster was seeded {max(near):.2f} nm from any P atom"


def test_uniform_placement_would_not_have_passed_that():
    """Guards the test above: without the solute the same draw is spread over the
    whole box, so the assertion is measuring the bias and not a coincidence."""
    waters = _grid_waters(20, 20, 20)
    backbone = [(0.0, 0.0, k * 0.3) for k in range(20)]

    _rem, _na, _mg, _cl, clusters = _place_ions_mixed_mgh(waters, 0, 20, 0, seed=7)

    near = [min(_dist(c.mg, p) for p in backbone) for c in clusters]
    assert max(near) > 1.25


def test_shell_biasing_is_deterministic():
    waters = _grid_waters(15, 15, 15)
    pdb = _p_atom_pdb([(0.0, 0.0, k * 0.3) for k in range(10)])
    a = _place_ions_mixed_mgh(waters, 10, 8, 10, seed=11, dna_pdb_text=pdb)
    b = _place_ions_mixed_mgh(waters, 10, 8, 10, seed=11, dna_pdb_text=pdb)
    assert [(_round_xyz(c.mg)) for c in a[4]] == [(_round_xyz(c.mg)) for c in b[4]]


def test_more_clusters_than_shell_sites_falls_back_to_bulk():
    """A tiny solute cannot host every cluster — the overflow must still be placed,
    not dropped or crashed on."""
    waters = _grid_waters(15, 15, 15)  # 3375 waters
    pdb = _p_atom_pdb([(0.0, 0.0, 0.0)])  # one P atom → a small shell
    _rem, _na, _mg, _cl, clusters = _place_ions_mixed_mgh(
        waters, 0, 200, 0, seed=5, dna_pdb_text=pdb
    )
    assert len(clusters) == 200


def test_biasing_stays_within_the_placement_budget():
    """Same 64k-water budget as the quadratic guard: the extra KD-tree is over P
    atoms only (~1/32 of the DNA), so it must not move the needle."""
    waters = _grid_waters(40, 40, 40)  # 64000 waters
    pdb = _p_atom_pdb([(i * 0.05, 1.0, 1.0) for i in range(2000)])
    t0 = time.monotonic()
    _rem, na, _mg, cl, clusters = _place_ions_mixed_mgh(
        waters, 3000, 300, 3000, seed=3, dna_pdb_text=pdb
    )
    dt = time.monotonic() - t0
    assert len(clusters) == 300 and len(na) == 3000 and len(cl) == 3000
    assert dt < 10.0, f"biased ion placement took {dt:.1f}s"
