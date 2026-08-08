"""Tests for backend.core.conjugation — azide-oligo conjugation site finder."""

import math

from backend.core.conjugation import (
    atom_sasa,
    find_conjugation_candidates,
)
from backend.core.models import ProteinAsset, ProteinAtom


def _atom(serial, name, element, res_name, res_seq, xyz, chain="A"):
    x, y, z = xyz
    return ProteinAtom(
        serial=serial,
        name=name,
        element=element,
        res_name=res_name,
        chain_id=chain,
        res_seq=res_seq,
        x=x,
        y=y,
        z=z,
    )


def _shell(start_serial, center, res_seq, radius=0.30, n=60, res_name="LYS"):
    """A dense Fibonacci shell of carbons around `center` — encloses an atom."""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    cx, cy, cz = center
    for i in range(n):
        z = 1.0 - (2.0 * i + 1.0) / n
        r = math.sqrt(max(0.0, 1.0 - z * z))
        th = golden * i
        p = (
            cx + radius * r * math.cos(th),
            cy + radius * r * math.sin(th),
            cz + radius * z,
        )
        out.append(_atom(start_serial + i, "CX", "C", res_name, res_seq, p))
    return out


def test_sasa_isolated_atom_fully_accessible():
    asset = ProteinAsset(atoms=[_atom(1, "NZ", "N", "LYS", 1, (0, 0, 0))])
    sasa = atom_sasa(asset)
    assert sasa[1] == 1.0


def test_sasa_enclosed_atom_buried():
    center = (0.0, 0.0, 0.0)
    atoms = [_atom(1, "NZ", "N", "LYS", 1, center)] + _shell(2, center, 1)
    asset = ProteinAsset(atoms=atoms)
    sasa = atom_sasa(asset)
    # Enclosed atom near zero accessibility.
    assert sasa[1] < 0.1


def test_sasa_monotonic_isolated_above_enclosed():
    iso = ProteinAsset(atoms=[_atom(1, "NZ", "N", "LYS", 1, (0, 0, 0))])
    center = (0.0, 0.0, 0.0)
    enc = ProteinAsset(
        atoms=[_atom(1, "NZ", "N", "LYS", 1, center)] + _shell(2, center, 1)
    )
    assert atom_sasa(iso)[1] > atom_sasa(enc)[1]


def _candidate_asset():
    """N-terminus (res 1), exposed Lys (res 5), buried Lys (res 6), exposed Cys (res 7)."""
    atoms = [
        # res 1 ALA — N-terminus (backbone N is the functional atom), placed far away.
        _atom(1, "N", "N", "ALA", 1, (10.0, 0.0, 0.0)),
        _atom(2, "CA", "C", "ALA", 1, (10.15, 0.0, 0.0)),
        # res 5 LYS — exposed NZ.
        _atom(10, "N", "N", "LYS", 5, (0.0, 10.0, 0.0)),
        _atom(11, "NZ", "N", "LYS", 5, (0.0, 10.5, 0.0)),
        # res 7 CYS — exposed SG.
        _atom(20, "N", "N", "CYS", 7, (0.0, 0.0, 10.0)),
        _atom(21, "SG", "S", "CYS", 7, (0.0, 0.5, 10.0)),
    ]
    # res 6 LYS — buried NZ (its serial 30, shelled by carbons 31..90).
    buried_center = (-10.0, 0.0, 0.0)
    atoms.append(_atom(30, "NZ", "N", "LYS", 6, buried_center))
    atoms += _shell(31, buried_center, 6)
    return ProteinAsset(atoms=atoms)


def test_candidates_pick_exposed_drop_buried():
    cands = find_conjugation_candidates(_candidate_asset())
    by_chem = {(c["chemistry"], c["res_seq"]) for c in cands}
    assert ("nterm", 1) in by_chem  # N-terminal backbone N
    assert ("lys", 5) in by_chem  # exposed Lys NZ
    assert ("cys", 7) in by_chem  # exposed Cys SG
    assert ("lys", 6) not in by_chem  # buried Lys NZ rejected


def test_candidate_functional_atom_serials_and_coords():
    cands = {c["chemistry"]: c for c in find_conjugation_candidates(_candidate_asset())}
    assert cands["lys"]["functional_atom_serial"] == 11
    assert cands["cys"]["functional_atom_serial"] == 21
    assert cands["nterm"]["functional_atom_serial"] == 1
    # Coordinates are the functional atom's own position (nm, local frame).
    assert cands["cys"]["x"] == 0.0 and cands["cys"]["z"] == 10.0


def test_chemistry_filter_restricts_set():
    cands = find_conjugation_candidates(_candidate_asset(), chemistries=("cys",))
    assert {c["chemistry"] for c in cands} == {"cys"}


def test_nterm_only_first_residue_per_chain():
    # The Lys at res 5 has a backbone N too, but it must NOT be flagged nterm.
    cands = find_conjugation_candidates(_candidate_asset())
    nterm = [c for c in cands if c["chemistry"] == "nterm"]
    assert len(nterm) == 1 and nterm[0]["res_seq"] == 1
