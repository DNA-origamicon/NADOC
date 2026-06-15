"""Tests for write_aksimentiev_enm_files — the base-ring elastic-network restraints.

The KD-tree vectorisation (2026-06-14) replaced a 142M-call Python double-loop
that made large designs (e.g. 3x6Sq, 5.7k bases) appear to hang during NAMD-seed
prep.  These pin that the vectorised output is byte-for-byte the intended bond set:
inter-residue base-ring atom pairs within the cutoff, never intra-residue.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np

from backend.core.md_protocols import write_aksimentiev_enm_files


def _atom_line(serial: int, name: str, resn: str, chain: str, resid: int,
               x: float, y: float, z: float) -> str:
    # Column-accurate PDB ATOM record (name@12, resn@17, chain@21, resid@22, xyz@30).
    return (
        f"ATOM  {serial:5d} {name:<4s} {resn:<3s} {chain}{resid:>4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}"
    )


def _write_pdb(path: Path, atoms: list[tuple]) -> None:
    """atoms: list of (name, resn, chain, resid, x, y, z) — written in order so the
    global 0-based atom index equals the list index."""
    lines = [_atom_line(i + 1, *a) for i, a in enumerate(atoms)]
    path.write_text("\n".join(lines) + "\n")


def _bonds_from_file(path: Path) -> set[tuple[int, int]]:
    out = set()
    for ln in path.read_text().splitlines():
        p = ln.split()
        if p and p[0] == "bond":
            out.add((int(p[1]), int(p[2])))
    return out


def _brute_force(atoms: list[tuple], cut: float = 8.0) -> set[tuple[int, int]]:
    """Reference: inter-residue base-ring atom pairs within `cut` (the intended set)."""
    pos = {i: np.array(a[4:7], float) for i, a in enumerate(atoms)}
    resid = {i: (a[2], a[3]) for i, a in enumerate(atoms)}   # (chain, resid)
    expected = set()
    for i, j in combinations(range(len(atoms)), 2):
        if resid[i] == resid[j]:
            continue
        if np.linalg.norm(pos[i] - pos[j]) <= cut:
            expected.add((min(i, j), max(i, j)))
    return expected


def test_enm_bonds_are_inter_residue_within_cutoff(tmp_path: Path) -> None:
    atoms = [
        ("N1", "ADE", "A", 1, 0.0, 0.0, 0.0),   # idx 0
        ("C2", "ADE", "A", 1, 1.4, 0.0, 0.0),   # idx 1  (intra-pair with 0 — must NOT bond)
        ("N1", "THY", "A", 2, 3.0, 0.0, 0.0),   # idx 2
        ("C2", "THY", "A", 2, 4.4, 0.0, 0.0),   # idx 3
        ("N1", "ADE", "A", 3, 50.0, 0.0, 0.0),  # idx 4  (far — no bonds)
    ]
    pdb = tmp_path / "small.pdb"
    _write_pdb(pdb, atoms)

    report = write_aksimentiev_enm_files(pdb, tmp_path, "small")

    expected = _brute_force(atoms)
    assert expected == {(0, 2), (0, 3), (1, 2), (1, 3)}   # sanity on the fixture

    bonds = _bonds_from_file(tmp_path / "small_k0.5.enm.extra")
    assert bonds == expected
    # intra-residue pairs excluded; the far residue contributes nothing.
    assert (0, 1) not in bonds and (2, 3) not in bonds
    assert all(4 not in pair for pair in bonds)

    assert report["n_restraints_per_file"] == 4
    assert report["n_base_atoms"] == 5
    # all three k-scale files share the identical bond set.
    for k in (0.5, 0.1, 0.01):
        assert _bonds_from_file(tmp_path / f"small_k{k:g}.enm.extra") == expected


def test_enm_matches_brute_force_on_a_denser_cluster(tmp_path: Path) -> None:
    """A 3D grid of base atoms across several residues — the vectorised KD-tree
    set must equal the brute-force inter-residue set exactly."""
    rng = np.random.default_rng(7)
    names = ["N1", "C2", "N3", "C4"]
    atoms: list[tuple] = []
    resid = 0
    for cx in range(4):
        for cy in range(4):
            resid += 1
            base = np.array([cx * 6.0, cy * 6.0, 0.0])   # residues ~6 Å apart → many in range
            for n in names:
                p = base + rng.normal(0, 0.8, 3)
                atoms.append((n, "ADE", "A", resid, float(p[0]), float(p[1]), float(p[2])))
    pdb = tmp_path / "grid.pdb"
    _write_pdb(pdb, atoms)

    write_aksimentiev_enm_files(pdb, tmp_path, "grid")
    bonds = _bonds_from_file(tmp_path / "grid_k0.5.enm.extra")
    assert bonds == _brute_force(atoms)
    assert len(bonds) > 0   # the cluster genuinely produces cross-residue restraints


def test_enm_handles_no_pairs_in_range(tmp_path: Path) -> None:
    """Widely separated residues → zero restraints, no crash, empty files."""
    atoms = [
        ("N1", "ADE", "A", 1, 0.0, 0.0, 0.0),
        ("N1", "THY", "A", 2, 100.0, 0.0, 0.0),
    ]
    pdb = tmp_path / "far.pdb"
    _write_pdb(pdb, atoms)
    report = write_aksimentiev_enm_files(pdb, tmp_path, "far")
    assert report["n_restraints_per_file"] == 0
    assert _bonds_from_file(tmp_path / "far_k0.5.enm.extra") == set()
