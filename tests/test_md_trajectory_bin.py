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
    monkeypatch.setattr(mt, "_dcd_complete_frame_count", lambda _: n_frames)
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

    def extract(_ctx, frame):
        base = np.arange(n_p * 3, dtype=np.float64).reshape(n_p, 3) / 17 + frame
        normals = np.tile([0.0, 0.0, 1.0], (n_p, 1))
        tpos = np.arange(n_term * 3, dtype=np.float64).reshape(n_term, 3) / 11 + frame
        tnorm = np.tile([1.0, 0.0, 0.0], (n_term, 1))
        p = np.vstack([base, tpos])
        n = np.vstack([normals, tnorm])
        return np.hstack([p, n, np.tile([0., 1., 0.], (len(p), 1)), p + 0.4])

    monkeypatch.setattr(mt, "_extract_md_full_frame", extract)
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
        n_frames, (n_p + n_term) * 12
    )
    assert header == {k: legacy[k] for k in ("keys", "stages", "markers", "frame_start", "total_n_frames", "frame_format")}
    assert np.allclose(frames, legacy["frames"], rtol=1e-6, atol=2e-5)
    assert len(payload) < len(orjson.dumps(legacy)) * 0.45
    assert json.loads(progress.read_text()) == {
        "phase": "pack",
        "done": 1,
        "total": 1,
    }


def test_range_extracts_only_selected_composite_frames(monkeypatch, tmp_path):
    from backend.core import md_trajectory as mt
    monkeypatch.setitem(sys.modules, "MDAnalysis", SimpleNamespace(
        Universe=lambda *_: SimpleNamespace(trajectory=range(10))))
    monkeypatch.setattr(mt, "_build_md_nadoc_ctx", lambda *_a, **_k: {
        "p_order": [("h", 0, "F")], "term_specs": []})
    monkeypatch.setattr(mt, "_dcd_complete_frame_count", lambda _: 10)
    seen = []
    def extract(_ctx, frame, **_):
        seen.append(frame)
        return np.array([[frame, 0, 0, 0, 0, 1, 0, 1, 0, frame + 0.4, 0, 0]])
    monkeypatch.setattr(mt, "_extract_md_full_frame", extract)
    segments = [("a", "md", tmp_path / "a.dcd"), ("b", "md", tmp_path / "b.dcd")]
    payload = mt.md_composite_trajectory_bin("x.psf", segments, "x.pdb", object(),
        stride=2, frame_start=3, frame_end=6)
    _, _, count, _, header_len = struct.unpack_from("<5I", payload)
    header = json.loads(payload[20:20 + header_len])
    assert count == 4
    assert header["frame_start"] == 3
    assert header["total_n_frames"] == 10
    assert seen == [6, 8, 10, 12]
