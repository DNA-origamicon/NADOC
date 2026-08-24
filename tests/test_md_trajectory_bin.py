"""Compact NAMD trajectory wire-format regression tests."""

from __future__ import annotations

import json
import struct
import sys
from types import SimpleNamespace

import numpy as np
import orjson


def test_md_binary_trajectory_matches_full_json_path(monkeypatch, tmp_path):
    """Exercise selection, extraction, packing and wire decode on representative shape."""
    from backend.core import md_trajectory as mt

    n_p, n_term, n_frames = 96, 4, 20
    p_order = [("h", i, "F") for i in range(n_p)]
    term_specs = [(("t", i, "R"),) for i in range(n_term)]
    ctx = {"p_order": p_order, "term_specs": term_specs}

    class FakeUniverse:
        def __init__(self, *_args):
            self.trajectory = range(n_frames)

    monkeypatch.setitem(
        sys.modules, "MDAnalysis", SimpleNamespace(Universe=FakeUniverse)
    )
    monkeypatch.setattr(mt, "_build_md_nadoc_ctx", lambda *_a, **_k: ctx)

    def extract(_ctx, frame, *, with_termini):
        assert with_termini is True
        base = np.arange(n_p * 3, dtype=np.float64).reshape(n_p, 3) / 17 + frame
        normals = np.tile([0.0, 0.0, 1.0], (n_p, 1))
        tpos = np.arange(n_term * 3, dtype=np.float64).reshape(n_term, 3) / 11 + frame
        tnorm = np.tile([1.0, 0.0, 0.0], (n_term, 1))
        return base, normals, tpos, tnorm

    monkeypatch.setattr(mt, "_extract_md_nadoc_frame", extract)
    segments = [("production", "md", tmp_path / "run.dcd")]
    legacy = mt.md_composite_trajectory("x.psf", segments, "x.pdb", object())
    progress = tmp_path / "progress.json"
    payload = mt.md_composite_trajectory_bin(
        "x.psf", segments, "x.pdb", object(), progress_path=str(progress)
    )

    magic, version, got_frames, got_keys, header_len = struct.unpack_from(
        "<5I", payload
    )
    assert (magic, version, got_frames, got_keys) == (
        mt._TRAJECTORY_BIN_MAGIC,
        mt._TRAJECTORY_BIN_VERSION,
        n_frames,
        n_p + n_term,
    )
    header = json.loads(payload[20 : 20 + header_len])
    body_offset = (20 + header_len + 3) & ~3
    frames = np.frombuffer(payload, dtype="<f4", offset=body_offset).reshape(
        n_frames, (n_p + n_term) * 6
    )
    assert header == {k: legacy[k] for k in ("keys", "stages", "markers")}
    assert np.allclose(frames, legacy["frames"], rtol=1e-6, atol=2e-5)
    assert len(payload) < len(orjson.dumps(legacy)) * 0.45
    assert json.loads(progress.read_text()) == {
        "phase": "pack",
        "done": 1,
        "total": 1,
    }
