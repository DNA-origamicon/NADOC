"""Read one SNUPI dynamics frame without materializing its full JSON trajectory.

Legacy trajectories are indexed in place, then served as compact point frames.
Only derived job-local caches are written; the physical result is immutable.
"""

import mmap
import os
from pathlib import Path
import re
import tempfile

import numpy as np
import orjson

from backend.core.cando_visualization import _BUILD_LOCK, pack_view

MAX_FRAME_BYTES = 128 * 1024 * 1024


def _write(path, payload):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _index(source, stamp, path):
    if path.exists():
        cached = orjson.loads(path.read_bytes())
        if cached.get("stamp") == stamp:
            return cached
    with (
        source.open("rb") as f,
        mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        match = re.search(rb'"frames"\s*:\s*\[', data)
        keys = re.search(rb'"keys"\s*:\s*\[', data)
        if not match or not keys:
            raise ValueError("Trajectory has no frames or nucleotide keys")
        # Keys contain strings: honor escaped quotes instead of searching for ']]'.
        start = keys.end() - 1
        depth, end = 0, None
        limit = min(len(data), start + MAX_FRAME_BYTES)
        for token in re.compile(rb'"(?:[^"\\]|\\.)*"|[\[\]]').finditer(
            data, start, limit
        ):
            if token[0] == b"[":
                depth += 1
            elif token[0] == b"]":
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
        if end is None:
            raise ValueError("Trajectory key table exceeds the visualization budget")
        count = len(orjson.loads(data[start:end]))
        if not 0 < count <= MAX_FRAME_BYTES // 24:
            raise ValueError("Trajectory frame exceeds the visualization budget")
        offsets = []
        closed = False
        pos = match.end()
        while pos < len(data):
            while pos < len(data) and data[pos] in b" \r\n\t,":
                pos += 1
            if pos >= len(data):
                break
            if data[pos] == ord("]"):
                closed = True
                break
            if data[pos] != ord("["):
                raise ValueError("Invalid trajectory frame array")
            end = data.find(b"]", pos + 1)
            if end < 0 or end - pos > MAX_FRAME_BYTES:
                raise ValueError("Trajectory frame exceeds the visualization budget")
            offsets.append([pos, end + 1])
            if len(offsets) > 100000:
                raise ValueError("Too many trajectory frames")
            pos = end + 1
        if not offsets or not closed:
            raise ValueError("No trajectory frames available")
    result = dict(stamp=stamp, count=count, offsets=offsets)
    for old in path.parent.glob("trajectory-view-v1-*.bin"):
        old.unlink()
    _write(path, orjson.dumps(result))
    return result


def trajectory_frame(job_dir, frame):
    source = job_dir / "trajectory.json"
    with _BUILD_LOCK:
        st = source.stat()
        if not st.st_size:
            raise ValueError("Empty trajectory")
        stamp = [st.st_mtime_ns, st.st_size]
        index = _index(source, stamp, job_dir / "trajectory-index-v1.json")
        if frame < 0 or frame >= len(index["offsets"]):
            raise ValueError("Trajectory frame out of range")
        target = job_dir / f"trajectory-view-v1-{frame}.bin"
        if target.exists() and target.stat().st_mtime_ns >= st.st_mtime_ns:
            return target.read_bytes()
        start, end = index["offsets"][frame]
        with source.open("rb") as f:
            f.seek(start)
            values = np.asarray(orjson.loads(f.read(end - start)), dtype="<f4")
        if values.ndim != 1 or len(values) != index["count"] * 6:
            raise ValueError("Trajectory frame does not match nucleotide keys")
        payload = pack_view(
            dict(
                kind="deform", frame=frame, frames=len(index["offsets"]), min=0, max=0
            ),
            values.reshape(-1, 6)[:, :3],
            np.full(index["count"], -1, dtype="<f4"),
        )
        _write(target, payload)
        return payload
