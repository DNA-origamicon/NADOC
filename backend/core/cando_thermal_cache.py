"""Bounded-memory, atomic persistence of thermal trajectories (same JSON schema)."""

import os
import tempfile
from pathlib import Path

import orjson


def write_thermal_trajectory(path: Path, thermal: dict, progress=None):
    """Serialize one numeric frame at a time, without boxing the entire ensemble."""
    frames = thermal["frames"]
    descriptor, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(b"{")
            first = True
            for key, value in thermal.items():
                if not first:
                    output.write(b",")
                first = False
                output.write(orjson.dumps(key) + b":")
                if key != "frames":
                    output.write(orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY))
                    continue
                output.write(b"[")
                for index, frame in enumerate(frames):
                    if index:
                        output.write(b",")
                    output.write(orjson.dumps(frame, option=orjson.OPT_SERIALIZE_NUMPY))
                    if progress:
                        progress(
                            (index + 1) / len(frames),
                            f"Save thermal trajectory · {index + 1}/{len(frames)} frames",
                        )
                output.write(b"]")
            output.write(b"}")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
