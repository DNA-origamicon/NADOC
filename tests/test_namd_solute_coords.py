"""Solute-coordinate injection for BLADE-seeded NAMD (build_namd_solvated_package's
``solute_coords`` hook).  Overwriting the built solute PDB's x/y/z must seed a
CONFORMATION without disturbing the topology columns (serial/name/resname/chain),
in exact atom order — that order-preservation is what makes a BLADE-relaxed seed
line up with the same PSF the reference dataset was exported against.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.namd_solvate import _overwrite_solute_coords

_PDB = (
    "ATOM      1  P   GUA A   1      10.000  20.000  30.000  1.00  0.00      DNA  P\n"
    "ATOM      2  O1P GUA A   1      11.000  21.000  31.000  1.00  0.00      DNA  O\n"
    "HETATM    3  MG   MG B   1      -5.500   0.250  99.999  1.00  0.00      ION MG\n"
)


def _xyz(line: str):
    return (float(line[30:38]), float(line[38:46]), float(line[46:54]))


def test_overwrites_xyz_in_order_and_preserves_columns():
    new = np.array([[1.5, 2.5, 3.5], [-4.0, 5.0, -6.25], [7.0, 8.0, 9.0]])
    out = _overwrite_solute_coords(_PDB, new).splitlines()
    for i, line in enumerate(out):
        assert _xyz(line) == tuple(new[i]), f"row {i} coords not written"
    # topology columns untouched: serial, atom name, resname, chain, element tail
    assert out[0][:30] == _PDB.splitlines()[0][:30]
    assert out[0][54:] == _PDB.splitlines()[0][54:]
    assert out[2].startswith("HETATM    3  MG")


def test_row_count_mismatch_raises():
    with pytest.raises(ValueError, match="rows but the built PDB"):
        _overwrite_solute_coords(_PDB, np.zeros((2, 3)))  # too few
    with pytest.raises(ValueError, match="rows but the built PDB|more atoms"):
        _overwrite_solute_coords(_PDB, np.zeros((4, 3)))  # too many


def test_bad_shape_and_nonfinite_rejected():
    with pytest.raises(ValueError, match="must be"):
        _overwrite_solute_coords(_PDB, np.zeros((3, 2)))
    with pytest.raises(ValueError, match="non-finite"):
        bad = np.zeros((3, 3))
        bad[1, 1] = np.inf
        _overwrite_solute_coords(_PDB, bad)


def test_out_of_field_coords_rejected():
    with pytest.raises(ValueError, match="9999"):
        big = np.zeros((3, 3))
        big[0, 0] = 12345.0
        _overwrite_solute_coords(_PDB, big)


def test_non_atom_lines_passed_through():
    doc = "REMARK test\n" + _PDB + "END\n"
    out = _overwrite_solute_coords(doc, np.zeros((3, 3)))
    assert out.startswith("REMARK test\n") and out.rstrip().endswith("END")
