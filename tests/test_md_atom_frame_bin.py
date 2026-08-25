import struct

import numpy as np
import pytest

from backend.api.ws import _pack_md_atom_frame


def test_pack_md_atom_frame_is_little_endian_soa_float32() -> None:
    payload = _pack_md_atom_frame({
        "frame_idx": 7,
        "n_frames": 100,
        "time_ps": 42.5,
        "_atom_positions": np.asarray([[1, 2, 3], [-4, 5, 6]], dtype=float),
    })
    assert len(payload) == 36 + 2 * 12
    assert struct.unpack("<8sIIIIId", payload[:36]) == (
        b"NADOCMDA", 1, 36, 7, 100, 2, 42.5,
    )
    # Structure-of-arrays: x[], then y[], then z[].
    np.testing.assert_array_equal(
        np.frombuffer(payload[36:], dtype="<f4"),
        [1, -4, 2, 5, 3, 6],
    )


@pytest.mark.parametrize(
    "frame",
    [
        {"frame_idx": 1, "n_frames": 1, "_atom_positions": [[1, 2, 3]]},
        {"frame_idx": 0, "n_frames": 1, "_atom_positions": [[1, np.nan, 3]]},
        {"frame_idx": 0, "n_frames": 1, "_atom_positions": [1, 2, 3]},
    ],
)
def test_pack_md_atom_frame_rejects_invalid_payload(frame: dict) -> None:
    with pytest.raises(ValueError, match="invalid binary MD atom frame"):
        _pack_md_atom_frame(frame)
