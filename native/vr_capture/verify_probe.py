"""Check actual GPU capture against the probe's independent frame counter.

This verifies submitted X11 test images, never claims HMD scanout verification.
Run after nadoc_capture_probe exits; every recorded pixel is checked.
"""

import argparse
import ctypes
import json
from pathlib import Path
import statistics
import zlib


def decode_frame(path: Path, raw_bytes: int, *, offset: int = 0, size: int | None = None) -> bytes:
    assert offset >= 0 and (size is None or size > 0)
    with path.open("rb") as stream:
        stream.seek(offset)
        encoded = stream.read() if size is None else stream.read(size)
    assert size is None or len(encoded) == size, "Truncated frame segment"
    if path.suffix != ".zst":
        return zlib.decompress(encoded)
    library = ctypes.CDLL("libzstd.so.1")
    library.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    library.ZSTD_decompress.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    destination = ctypes.create_string_buffer(raw_bytes)
    result = library.ZSTD_decompress(destination, raw_bytes, encoded, len(encoded))
    assert not library.ZSTD_isError(result) and result == raw_bytes, "Invalid Zstandard capture"
    return destination.raw


def verify(directory: Path, *, pixels: bool) -> dict:
    rows = [json.loads(line) for path in directory.glob("events-*.jsonl") for line in path.read_text().splitlines()]
    expected = {row["present"]: row for row in map(json.loads, (directory / "probe-expected.jsonl").read_text().splitlines())}
    starts = [row for row in rows if row["event"] == "capture_start"]
    assert len(starts) == 1, f"Expected one recording interval, got {len(starts)}"
    start = starts[0]
    present = [r for r in rows if r["event"] == "present" and (bool(r["armed"]) and r["request"] == start["request"] if "armed" in r else start["start_ns"] <= r["driver_call_ns"] < start["end_ns"])]
    saved = [r for r in rows if r["event"] == "frame_saved"]
    assert len(present) >= 5, "Insufficient exercised frames"
    assert all(r["result"] == 0 and r["image_result"] == 0 for r in present), "Presentation failed"
    if pixels:
        assert {r["present"] for r in saved} == {r["present"] for r in present}, "Captured present IDs have gaps or extras"
        assert len(saved) == len(present), "Duplicate capture records"
        for row in saved:
            frame = expected[row["present"]]
            channels = [frame["b"], frame["g"], frame["r"], 255] if row["format"] == 44 else [frame["r"], frame["g"], frame["b"], 255]
            assert row["format"] in (37, 44), "Unexpected format for exact UNORM oracle"
            raw = decode_frame(directory / row["file"], row["raw_bytes"], offset=row.get("file_offset", 0), size=row["compressed_bytes"])
            assert raw == bytes(channels) * (row["width"] * row["height"]), f"Pixel/counter mismatch at present {row['present']}"
    else:
        assert not saved and not list(directory.glob("*.bgra.*")) and not list(directory.glob("*.frames.*")), "Metadata mode unexpectedly read pixels"
        assert all(not r["copied"] for r in present)
    failures = [r for r in rows if r["event"] in ("pixel_drop", "frame_write_failed", "capture_prepare_failed", "copy_fence_error")]
    assert not failures, failures
    assert any(r["event"] == "capture_complete" for r in rows), "Final accounting absent"
    durable = any(r["event"] == "layer_start" and r.get("durable_pixel_files") is True for r in rows)
    if pixels and durable:
        complete = next(r for r in rows if r["event"] == "capture_complete")
        assert complete["persistence_ok"] is True and complete["directory_synced"] is True
        assert complete["released_compressed_bytes"] > 0 and complete["released_raw_bytes"] > 0
        assert all(r["file_fdatasynced"] is True and r["file_closed"] is True for r in saved)
        assert all(r["write_begin_ns"] >= start["end_ns"] for r in saved)
    copy = [r for r in rows if r["event"] == "copy_complete"]
    return {"test_surface_only": True, "pixel_oracle_passed": pixels, "active_presents": len(present), "saved_frames": len(saved), "hook_before_driver_median_us": statistics.median(r["hook_before_driver_ns"] for r in present) / 1000, "copy_gpu_median_us": statistics.median(r["copy_gpu_ns"] for r in copy) / 1000 if copy else None, "host_memcpy_median_us": statistics.median(r["host_memcpy_ns"] for r in copy) / 1000 if copy else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--metadata", action="store_true")
    args = parser.parse_args()
    result = verify(args.directory, pixels=not args.metadata)
    print(json.dumps(result, indent=2))
    (args.directory / "probe-verification.json").write_text(json.dumps(result, indent=2) + "\n")
