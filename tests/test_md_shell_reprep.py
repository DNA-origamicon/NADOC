"""Tests for NAMD checkpoint and orientation-restraint helpers."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from backend.core.md_shell_reprep import (
    orientation_restraint_colvars,
    read_namd_coor,
    write_orientation_reference_xyz,
)


def _write_coor(path, coords: np.ndarray, endian: str = "<") -> None:
    n = coords.shape[0]
    with open(path, "wb") as fh:
        fh.write(struct.pack(endian + "i", n))
        fh.write(coords.astype(endian + "f8").tobytes())


def test_read_namd_coor_roundtrip_little_endian(tmp_path):
    coords = np.array([[1.0, 2.0, 3.0], [-4.5, 5.5, 6.25], [0.0, 0.0, 0.0]])
    path = tmp_path / "x.coor"
    _write_coor(path, coords)
    assert np.allclose(read_namd_coor(path), coords)


def test_read_namd_coor_detects_big_endian(tmp_path):
    coords = np.array([[7.0, 8.0, 9.0], [1.5, 2.5, 3.5]])
    path = tmp_path / "b.coor"
    _write_coor(path, coords, ">")
    assert np.allclose(read_namd_coor(path), coords)


def test_read_namd_coor_rejects_garbage(tmp_path):
    path = tmp_path / "bad.coor"
    path.write_bytes(b"\x01\x00\x00\x00\x00\x00")
    with pytest.raises(ValueError):
        read_namd_coor(path)


def test_orientation_colvars_restrains_identity_quaternion():
    cfg = orientation_restraint_colvars(1234, "reference.xyz", force_constant=250)
    assert "atomNumbersRange 1-1234" in cfg
    assert "refPositionsFile reference.xyz" in cfg
    assert "centers (1.0, 0.0, 0.0, 0.0)" in cfg
    assert "forceConstant 250" in cfg


def test_orientation_reference_is_dna_only_and_high_precision(tmp_path):
    coords = np.array([[1 / 3, 2 / 3, 3 / 7], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0], [99, 99, 99]])
    path = tmp_path / "reference.xyz"
    write_orientation_reference_xyz(path, coords, 3)
    lines = path.read_text().splitlines()
    assert lines[0] == "3"
    assert len(lines) == 5
    assert "99.0000000000" not in path.read_text()
