"""Round-trip pins for the DCD writer in `backend.core.dcd_fast`.

The writer exists so a trajectory export can ship binary coordinates (12 bytes/atom/frame)
plus one topology PDB, instead of a multi-MODEL PDB that re-serialises the whole structure
as ~80 ASCII bytes/atom/frame. Correctness here is checked against this module's OWN reader,
which was written independently (for NAMD output) and parses the real CHARMM layout — so a
round-trip through it is a genuine format check, not a tautology.
"""

import numpy as np
import pytest

from backend.core.dcd_fast import (
    UnsupportedDCD,
    append_frame,
    read_frame,
    read_layout,
    write_header,
    write_trajectory,
)


def _frames(n_frames, n_atoms, seed=0):
    rng = np.random.default_rng(seed)
    return [
        rng.normal(size=(n_atoms, 3)).astype(np.float32) * 25.0 for _ in range(n_frames)
    ]


class TestRoundTrip:
    def test_layout_matches_what_was_written(self, tmp_path):
        path = tmp_path / "t.dcd"
        frames = _frames(7, 40)
        assert write_trajectory(path, 40, frames, 7) == 7

        layout = read_layout(path)
        assert layout.n_atoms == 40
        assert layout.n_frames == 7
        assert layout.has_cell is False
        # No trailing slack: the file is exactly header + n_frames whole records.
        assert path.stat().st_size == layout.header_bytes + 7 * layout.frame_bytes

    def test_every_frame_reads_back_to_float32_precision(self, tmp_path):
        path = tmp_path / "t.dcd"
        frames = _frames(5, 128, seed=3)
        write_trajectory(path, 128, frames, 5)

        layout = read_layout(path)
        for i, original in enumerate(frames):
            coords, cell = read_frame(path, layout, i)
            assert cell is None
            assert coords.shape == (128, 3)
            # float32 in, float32 out — exact, not approximate.
            assert np.array_equal(coords, original)

    def test_frames_stay_distinct_and_ordered(self, tmp_path):
        path = tmp_path / "t.dcd"
        frames = [np.full((10, 3), float(i), dtype=np.float32) for i in range(6)]
        write_trajectory(path, 10, frames, 6)
        layout = read_layout(path)
        for i in range(6):
            assert read_frame(path, layout, i)[0][0, 0] == float(i)

    def test_single_atom_and_single_frame(self, tmp_path):
        path = tmp_path / "t.dcd"
        write_trajectory(path, 1, [np.array([[1.5, -2.5, 3.5]], dtype=np.float32)], 1)
        layout = read_layout(path)
        assert layout.n_atoms == 1 and layout.n_frames == 1
        assert read_frame(path, layout, 0)[0].tolist() == [[1.5, -2.5, 3.5]]

    def test_reading_past_the_end_raises(self, tmp_path):
        path = tmp_path / "t.dcd"
        write_trajectory(path, 8, _frames(2, 8), 2)
        layout = read_layout(path)
        with pytest.raises(IndexError):
            read_frame(path, layout, 2)


class TestDeclaredCountCorrection:
    def test_header_is_rewritten_when_fewer_frames_arrive(self, tmp_path):
        # The header (fixed size, written first) declares NSET before any frame is seen.
        # A short iterable must not leave NSET overstating the file, or a reader computes
        # a frame count the bytes don't support.
        path = tmp_path / "t.dcd"
        written = write_trajectory(path, 16, _frames(3, 16), 10)  # promised 10, gave 3
        assert written == 3
        layout = read_layout(path)
        assert layout.n_frames == 3
        assert path.stat().st_size == layout.header_bytes + 3 * layout.frame_bytes

    def test_zero_frames_still_produces_a_readable_header(self, tmp_path):
        path = tmp_path / "t.dcd"
        assert write_trajectory(path, 12, iter(()), 4) == 0
        layout = read_layout(path)
        assert layout.n_atoms == 12
        assert layout.n_frames == 0


class TestValidation:
    def test_rejects_non_positive_atom_count(self, tmp_path):
        with open(tmp_path / "t.dcd", "wb") as fh:
            with pytest.raises(ValueError):
                write_header(fh, 0, 1)

    def test_rejects_a_wrongly_shaped_frame(self, tmp_path):
        with open(tmp_path / "t.dcd", "wb") as fh:
            write_header(fh, 4, 1)
            with pytest.raises(ValueError):
                append_frame(fh, np.zeros((4, 2), dtype=np.float32))
            with pytest.raises(ValueError):
                append_frame(fh, np.zeros(12, dtype=np.float32))

    def test_a_truncated_file_is_not_mistaken_for_a_dcd(self, tmp_path):
        path = tmp_path / "t.dcd"
        path.write_bytes(b"\x00\x01")
        with pytest.raises(UnsupportedDCD):
            read_layout(path)

    def test_accepts_a_list_of_lists_frame(self, tmp_path):
        # The export path hands over plain Python sequences reshaped from a flat array.
        path = tmp_path / "t.dcd"
        write_trajectory(path, 2, [[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]], 1)
        layout = read_layout(path)
        assert read_frame(path, layout, 0)[0].tolist() == [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ]
