"""Hardware-scoped timing evidence for local previews, separate from memory bounds."""

from functools import lru_cache
import json
from pathlib import Path
import subprocess
import time
import re
import statistics

from backend.core.namd_allocation_model import QUALIFIED_ENGINE
from backend.core.namd_provenance import file_identity


@lru_cache(maxsize=8)
def _gpu_identity(devices, time_bucket):
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--id=" + devices,
                "--query-gpu=name,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) != 1:
            return None
        name, driver = (value.strip() for value in lines[0].split(","))
        return dict(gpu=name, driver=driver)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def gpu_identity(devices="0"):
    return _gpu_identity(str(devices), int(time.monotonic() // 60))


def local_identity(devices="0"):
    from backend.core.namd_runner import find_namd

    if str(devices).lower() in ("cpu", "none"):
        return None
    try:
        identity = gpu_identity(devices)
        engine = file_identity(find_namd())
        if identity and engine["sha256"]:
            return dict(**identity, engine_sha256=engine["sha256"])
    except (OSError, RuntimeError, FileNotFoundError):
        pass
    return None


def matches_local(proof, *, devices="0", threads=16):
    identity = local_identity(devices)
    return bool(
        identity
        and all(proof.get(key) == value for key, value in identity.items())
        and proof.get("threads") == threads
        and (not proof.get("cpu_model") or proof["cpu_model"] == cpu_model())
    )


@lru_cache(maxsize=1)
def cpu_model():
    try:
        return next(
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        )
    except (OSError, StopIteration):
        return None


@lru_cache(maxsize=1)
def _evidence():
    return json.loads(
        (Path(__file__).parent.parent / "data" / "namd_timing.json").read_text()
    )


def local_step_ms(n_atoms, *, resident=True, devices="0", threads=16):
    """Interpolate completed current-engine probes on this exact GPU/driver.

    No extrapolation to unmeasured atom counts, offload paths or other devices.
    This is a throughput estimate for standard late-stage dynamics, not a
    completion guarantee or a calibrated prediction interval.
    """
    try:
        evidence = _evidence()
        proof = evidence["provenance"]
        if proof["engine_sha256"] != QUALIFIED_ENGINE or not resident:
            return None
        if not matches_local(proof, devices=devices, threads=threads):
            return None
        points = evidence["points"]
        if not points[0]["atoms"] <= n_atoms <= points[-1]["atoms"]:
            return None
        for left, right in zip(points, points[1:]):
            if left["atoms"] <= n_atoms <= right["atoms"]:
                weight = (n_atoms - left["atoms"]) / (right["atoms"] - left["atoms"])
                return (
                    left["ms_per_step"] * (1 - weight) + right["ms_per_step"] * weight
                )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def sustained_timing(log_path, *, max_bytes=2 * 1024**2):
    """Recent wall TIMING windows, with bounded I/O even for multi-GB logs.

    Early Benchmark lines describe warmup and miss later load/neighbor changes.
    Keep a spread and window count alongside the median so learning can retain
    variation instead of turning one warmup observation into an exact rate.
    """
    try:
        with Path(log_path).open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - max_bytes))
            text = stream.read(max_bytes).decode(errors="replace")
        values = [
            float(v)
            for v in re.findall(
                r"TIMING:.*?Wall:\s*[\d.eE+-]+,\s*([\d.eE+-]+)/step", text
            )
        ]
        values = [v for v in values[-64:] if v > 0]
        if len(values) < 3:
            return None
        return dict(
            seconds_per_step=statistics.median(values),
            low_s=min(values),
            high_s=max(values),
            intervals=len(values),
            basis="recent wall TIMING windows",
        )
    except (OSError, ValueError):
        return None
