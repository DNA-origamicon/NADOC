"""Regression: NAMD flexibility-map / trajectory P-atom order must use the PSF-segid
map, not the reference-PDB chainID key.

CHARMM psfgen collapses NADOC's multi-char chain ids (``A``, ``AA``, ``AB``, …) into
the reference PDB's single-char ``chainID`` field.  The PDB-key path
(``build_p_pdb_order``) then collides across strands and DROPS the multi-char-chain
P atoms, so ``len(p_order) != `` the simulated structure's DNA-P count.  ``md_rmsf``'s
strict per-frame length guard treats that as "no usable frames" and the panel shows
the flexibility map as *not ready* (the real bug reported for the 3x6x200 job).

These are pure/fast: they drive ``_select_p_order`` with a faked Universe + a written
``charge_audit.json``, no MDAnalysis or on-disk trajectory required.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from backend.core.md_trajectory import _select_p_order

# Two strands whose NADOC chain ids collapse to one PDB chainID letter: 'A' and 'AA'.
# build_chain_map keys by the REAL (multi-char) chain id.
_CM = {
    ("A", 1): ("h0", 1, "FORWARD"),
    ("A", 2): ("h0", 2, "FORWARD"),
    ("AA", 1): ("h1", 1, "REVERSE"),
    ("AA", 2): ("h1", 2, "REVERSE"),
}


def _p_line(serial: int, chain: str, resseq: int, resname: str = "ADE") -> str:
    """A minimal PDB ATOM line for a P atom with exact columns for build_p_pdb_order."""
    line = list(" " * 80)
    line[0:6] = "ATOM  "
    line[6:11] = f"{serial:>5}"
    line[12:16] = " P  "
    line[17:20] = f"{resname:>3}"
    line[21] = chain
    line[22:26] = f"{resseq:>4}"
    return "".join(line)


# Reference PDB as psfgen writes it: BOTH strands land in chainID 'A' (multi-char 'AA'
# collapsed) with continued residue numbering, so ('A',3)/('A',4) miss the chain map.
_PDB_TEXT = (
    "\n".join(
        [
            _p_line(1, "A", 1),
            _p_line(2, "A", 2),
            _p_line(3, "A", 3),  # really strand 'AA' residue 1 — collapsed chainID
            _p_line(4, "A", 4),  # really strand 'AA' residue 2 — collapsed chainID
        ]
    )
    + "\n"
)


class _FakeUniverse:
    """Just enough of an MDAnalysis Universe for build_p_order_from_universe: a
    select_atoms(...) returning DNA-P atoms carrying .segid and .resid (per-segment)."""

    def __init__(self, atoms):
        self._atoms = atoms

    def select_atoms(self, _sel):
        return self._atoms


def _fake_universe():
    return _FakeUniverse(
        [
            SimpleNamespace(segid="D000", resid=1),  # strand A
            SimpleNamespace(segid="D000", resid=2),
            SimpleNamespace(segid="D001", resid=1),  # strand AA
            SimpleNamespace(segid="D001", resid=2),
        ]
    )


def _write_pdb(tmp_path):
    p = tmp_path / "ref.pdb"
    p.write_text(_PDB_TEXT)
    return p


def _write_charge_audit(tmp_path, segments):
    (tmp_path / "charge_audit.json").write_text(json.dumps({"segments": segments}))


def test_pdb_key_path_drops_multichar_chain_atoms(tmp_path):
    """The old behaviour, pinned: with NO charge_audit the fallback reference-PDB path
    silently drops the collapsed multi-char-chain P atoms (2 of 4) — the root cause."""
    pdb = _write_pdb(tmp_path)  # no charge_audit.json in tmp_path
    order, source = _select_p_order(_fake_universe(), _CM, tmp_path, pdb)
    assert source == "reference-pdb"
    assert order == [("h0", 1, "FORWARD"), ("h0", 2, "FORWARD")]  # strand AA lost


def test_segid_path_recovers_all_atoms(tmp_path):
    """The fix: with a complete charge_audit segid map, every DNA-P atom maps — the
    order covers all 4 nucleotides across both strands (no collision, no drop)."""
    pdb = _write_pdb(tmp_path)
    _write_charge_audit(
        tmp_path,
        [
            {"segid": "D000", "chain_id": "A"},
            {"segid": "D001", "chain_id": "AA"},
        ],
    )
    order, source = _select_p_order(_fake_universe(), _CM, tmp_path, pdb)
    assert source == "segid"
    assert order == [
        ("h0", 1, "FORWARD"),
        ("h0", 2, "FORWARD"),
        ("h1", 1, "REVERSE"),
        ("h1", 2, "REVERSE"),
    ]


def test_incomplete_segid_map_falls_back_to_pdb(tmp_path):
    """A charge_audit that maps only some segids (leaving DNA-P atoms unmapped) must
    NOT serve a partial order — it falls back to the reference-PDB path."""
    pdb = _write_pdb(tmp_path)
    _write_charge_audit(tmp_path, [{"segid": "D000", "chain_id": "A"}])  # D001 missing
    order, source = _select_p_order(_fake_universe(), _CM, tmp_path, pdb)
    assert source == "reference-pdb"
    assert order == [("h0", 1, "FORWARD"), ("h0", 2, "FORWARD")]
