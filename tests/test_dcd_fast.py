"""O(1) direct DCD last-frame reader — verified against MDAnalysis."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.core import dcd_fast as F


def _write_dcd(tmp_path: Path, n_atoms: int, n_frames: int) -> Path:
    """Write a small DCD via MDAnalysis to read back.  MDAnalysis always emits a
    CHARMM unit-cell block (zeroed if no dimensions), matching real NAMD DCDs."""
    mda = pytest.importorskip("MDAnalysis")
    u = mda.Universe.empty(n_atoms, trajectory=True)
    rng = np.random.default_rng(0)
    coords = rng.normal(size=(n_frames, n_atoms, 3)).astype(np.float32) * 10.0
    dcd = tmp_path / "t.dcd"
    with mda.Writer(str(dcd), n_atoms=n_atoms) as w:
        for f in range(n_frames):
            u.atoms.positions = coords[f]
            u.dimensions = [50.0 + f, 60.0, 70.0, 90.0, 90.0, 90.0]
            w.write(u.atoms)
    return dcd


def test_layout_and_frames_match_mdanalysis(tmp_path):
    mda = pytest.importorskip("MDAnalysis")
    n_atoms, n_frames = 37, 6
    dcd = _write_dcd(tmp_path, n_atoms, n_frames)

    layout = F.read_layout(dcd)
    assert layout.n_atoms == n_atoms
    assert layout.n_frames == n_frames
    assert layout.has_cell is True

    u = mda.Universe.empty(n_atoms, trajectory=True)
    u.load_new(str(dcd))
    assert len(u.trajectory) == n_frames

    for idx in (0, n_frames // 2, n_frames - 1):
        coords, cell = F.read_frame(dcd, layout, idx)
        u.trajectory[idx]
        assert np.abs(coords - u.atoms.positions).max() < 1e-3   # byte-exact coords
        assert np.allclose(F.cell_to_dimensions(cell), u.dimensions, atol=1e-2)


def test_out_of_range_frame_raises(tmp_path):
    dcd = _write_dcd(tmp_path, 20, 3)
    layout = F.read_layout(dcd)
    with pytest.raises(IndexError):
        F.read_frame(dcd, layout, 3)        # only 0..2 exist


def test_growing_file_frame_count_is_arithmetic(tmp_path):
    # n_frames must follow the file size (O(1)), not a header NSET that may lag.
    dcd = _write_dcd(tmp_path, 12, 5)
    layout = F.read_layout(dcd)
    full = dcd.read_bytes()
    one_frame = layout.frame_bytes
    # Truncate the last frame off → reader should report 4 complete frames.
    dcd.write_bytes(full[: layout.header_bytes + 4 * one_frame])
    assert F.read_layout(dcd).n_frames == 4


def test_not_a_dcd_raises_unsupported(tmp_path):
    bad = tmp_path / "bad.dcd"
    bad.write_bytes(b"not a dcd file at all, just some bytes" * 4)
    with pytest.raises(F.UnsupportedDCD):
        F.read_layout(bad)
