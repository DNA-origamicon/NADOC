"""Unit tests for the water-shell NVT-production re-prep helpers."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from backend.core.atomistic import Atom, AtomisticModel
from backend.core.md_shell_reprep import (
    com_restraint_colvars,
    read_namd_coor,
    stamp_relaxed_dna_model,
)


def _atom(serial, x, y, z):
    return Atom(
        serial=serial, name="C1'", element="C", residue="DA", chain_id="A",
        seq_num=1, x=x, y=y, z=z, strand_id="s", helix_id="h", bp_index=0,
        direction="FORWARD",
    )


def _write_coor(path, coords: np.ndarray, endian: str = "<") -> None:
    n = coords.shape[0]
    with open(path, "wb") as fh:
        fh.write(struct.pack(endian + "i", n))
        fh.write(coords.astype(endian + "f8").tobytes())


def test_read_namd_coor_roundtrip_little_endian(tmp_path):
    coords = np.array([[1.0, 2.0, 3.0], [-4.5, 5.5, 6.25], [0.0, 0.0, 0.0]])
    p = tmp_path / "x.coor"
    _write_coor(p, coords, "<")
    got = read_namd_coor(p)
    assert got.shape == (3, 3)
    assert np.allclose(got, coords)


def test_read_namd_coor_detects_big_endian(tmp_path):
    coords = np.array([[7.0, 8.0, 9.0], [1.5, 2.5, 3.5]])
    p = tmp_path / "b.coor"
    _write_coor(p, coords, ">")
    assert np.allclose(read_namd_coor(p), coords)


def test_read_namd_coor_rejects_garbage(tmp_path):
    p = tmp_path / "bad.coor"
    p.write_bytes(b"\x01\x00\x00\x00\x00\x00")  # claims 1 atom but wrong size
    with pytest.raises(ValueError):
        read_namd_coor(p)


def test_com_colvars_pins_all_three_axes_over_the_dna_range():
    cfg = com_restraint_colvars(1234, (10.0, 20.0, 30.0), force_constant=2.5)
    # one colvar + one harmonic per axis
    assert cfg.count("distanceZ") == 3
    assert cfg.count("harmonic") == 3
    # DNA addressed as the leading serial range, not an inline atom dump
    assert "atomNumbersRange 1-1234" in cfg
    assert cfg.count("atomNumbersRange 1-1234") == 3
    # dummy reference at the supplied centre, tunable stiffness
    assert "dummyAtom (10.000, 20.000, 30.000)" in cfg
    assert "forceConstant 2.5" in cfg
    assert "centers 0.0" in cfg


def test_com_colvars_rejects_empty_group():
    with pytest.raises(ValueError):
        com_restraint_colvars(0, (0.0, 0.0, 0.0))


def test_stamp_converts_angstrom_to_nm_and_keeps_topology():
    model = AtomisticModel(atoms=[_atom(0, 0, 0, 0), _atom(1, 0, 0, 0)],
                           bonds=[(0, 1)])
    # 2 DNA rows (small) + 3 water rows spanning a large box
    coor = np.array([
        [10.0, 20.0, 30.0], [15.0, 25.0, 35.0],   # DNA (Å)
        [500.0, 0.0, 0.0], [-500.0, 400.0, 900.0], [0.0, -400.0, -900.0],
    ])
    out = stamp_relaxed_dna_model(model, coor)
    assert out.bonds == [(0, 1)]                    # topology preserved
    assert (out.atoms[0].x, out.atoms[0].y, out.atoms[0].z) == (1.0, 2.0, 3.0)  # Å→nm
    assert (out.atoms[1].x, out.atoms[1].y, out.atoms[1].z) == (1.5, 2.5, 3.5)


def test_stamp_guard_rejects_wrong_atom_order():
    # leading "DNA" rows span the full box on every axis → order assumption broken
    model = AtomisticModel(atoms=[_atom(0, 0, 0, 0), _atom(1, 0, 0, 0)], bonds=[])
    coor = np.array([[-500.0, -500.0, -500.0], [500.0, 500.0, 500.0],
                     [1.0, 1.0, 1.0], [2.0, 2.0, 2.0]])
    with pytest.raises(ValueError):
        stamp_relaxed_dna_model(model, coor)


def test_stamp_rejects_too_few_atoms():
    model = AtomisticModel(atoms=[_atom(0, 0, 0, 0), _atom(1, 0, 0, 0)], bonds=[])
    with pytest.raises(ValueError):
        stamp_relaxed_dna_model(model, np.array([[1.0, 2.0, 3.0]]))
