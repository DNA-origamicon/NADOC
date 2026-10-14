"""Lossless stereo format, timing fidelity, and failed-export retention."""
import json
from pathlib import Path
import struct
import zlib

import pytest

from tools.vr_recording import export, frame_durations, png


def test_timing_uses_capture_gaps_not_assumed_90_fps():
    frames = [{"elapsed_seconds": t} for t in [.002, .024, .091, 4.97]]
    assert frame_durations(frames, 5) == pytest.approx([.024, .067, 4.879, .03])
    assert sum(frame_durations(frames, 5)) == pytest.approx(5)
    for times in [[], [-.1], [5], [.1, .1], [.2, .1], [.1, 5]]:
        with pytest.raises(ValueError):
            frame_durations([{"elapsed_seconds": t} for t in times], 5)


def test_png_preserves_orientation_and_rgb():
    # Bottom row blue/green, top row red/white. Independent PNG chunk decoding.
    bottom_up = bytes([0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255])
    encoded = png(bottom_up, 2, 2)
    offset, image = 8, b""
    while offset < len(encoded):
        size = struct.unpack_from(">I", encoded, offset)[0]
        kind, data = encoded[offset + 4:offset + 8], encoded[offset + 8:offset + 8 + size]
        if kind == b"IDAT":
            image += data
        offset += size + 12
    assert zlib.decompress(image) == b"\0" + bottom_up[6:] + b"\0" + bottom_up[:6]
    with pytest.raises(ValueError):
        png(bottom_up[:-1], 2, 2)


def fixture(path: Path):
    (path / "recording.json").write_text(json.dumps(dict(
        schema=1, format="zlib-rgb24-left-then-right-bottom-up", width=2, height=2,
        duration_seconds=5, saved_frames=2, dropped_pairs=0,
    )))
    for frame, elapsed in [(4, .01), (9, 3.25)]:
        (path / f"{frame}.json").write_text(json.dumps(dict(
            frame=frame, elapsed_seconds=elapsed, xr_end_frame_succeeded=True,
            eyes=[{"eye": 1}, {"eye": 0}], menus_open=[elapsed < 3, True],
        )))
        (path / f"{frame}.rgbz").write_bytes(zlib.compress(bytes([255, 0, 0] * 4 + [0, 0, 255] * 4)))


def test_export_keeps_pairs_and_nonuniform_timing(tmp_path, monkeypatch):
    fixture(tmp_path)
    calls = []

    def encoder(args, **kwargs):
        source = Path(args[args.index("-i") + 1])
        calls.append(source.read_text())
        assert source.read_text().count("duration ") == 2
        assert "duration 3.250000000" in source.read_text()
        assert "duration 1.750000000" in source.read_text()
        assert "-fps_mode" in args and "vfr" in args
        assert (source.parent / "4-0.png").read_bytes() != (source.parent / "4-1.png").read_bytes()

    monkeypatch.setattr("tools.vr_recording.subprocess.run", encoder)
    result = export(tmp_path)
    assert len(calls) == 2
    assert result["maximum_frame_gap_seconds"] == 3.25
    assert (tmp_path / "index.html").is_file()
    assert (tmp_path / "4.rgbz").is_file()
    assert not (tmp_path / ".encoding").exists()


def test_failure_preserves_lossless_frames(tmp_path, monkeypatch):
    fixture(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("No encoder")
    monkeypatch.setattr("tools.vr_recording.subprocess.run", fail)
    with pytest.raises(OSError, match="No encoder"):
        export(tmp_path)
    assert (tmp_path / "9.rgbz").is_file()
    assert not (tmp_path / ".encoding").exists()
    assert not (tmp_path / "timeline.json").exists()


def test_rejects_unsubmitted_or_incomplete_stereo(tmp_path):
    fixture(tmp_path)
    p = tmp_path / "4.json"
    frame = json.loads(p.read_text())
    frame["eyes"] = [{"eye": 0}, {"eye": 0}]
    p.write_text(json.dumps(frame))
    with pytest.raises(ValueError, match="Incomplete stereo"):
        export(tmp_path)
    frame["xr_end_frame_succeeded"] = False
    p.write_text(json.dumps(frame))
    with pytest.raises(ValueError, match="Unsubmitted"):
        export(tmp_path)
