"""Compact, bounded browser representations of completed FEM results.

Every nucleotide/axis segment is retained at WebGL float32 precision. Large jobs
use points/lines instead of millions of sphere/slab/cylinder triangles. Derived
files are disposable, source-stamped caches; no design or solver result is changed.
"""

from pathlib import Path
import os
import struct
import tempfile
import threading

import numpy as np
import orjson

# Serialize builds across jobs: repeated radio clicks must not multiply peak RAM.
_BUILD_LOCK = threading.Lock()
_POSITION = np.dtype(
    [
        ("helix", "<u4"),
        ("bp", "<i4"),
        ("copy", "<i4"),
        ("reverse", "<u4"),
        ("coords", "<f4", (9,)),
    ]
)
_AXIS = np.dtype([("helix", "<u4"), ("bp", "<i4"), ("position", "<f4", (3,))])


def read_frame(payload):
    if len(payload) < 24:
        raise ValueError("Incomplete FEM frame")
    magic, version, n, m, nh, length = struct.unpack_from("<6I", payload)
    offset = (24 + length + 3) & ~3
    if magic != 0x4D524643 or version != 1 or len(payload) != offset + n * 52 + m * 20:
        raise ValueError("Invalid FEM frame")
    if length > 1024 * 1024 or 24 + length > len(payload):
        raise ValueError("Invalid FEM header")
    header = orjson.loads(payload[24 : 24 + length])
    if len(header["helix_ids"]) != nh:
        raise ValueError("Invalid FEM helix table")
    return (
        header,
        np.frombuffer(payload, _POSITION, n, offset),
        np.frombuffer(payload, _AXIS, m, offset + n * 52),
    )


def _frame(jd):
    from backend.core.cando_runner import (
        load_thermal_representative_bin,
        load_display,
        pack_static_fem_frame_bin,
    )

    payload = load_thermal_representative_bin(jd)
    thermal = bool(payload)
    if not payload:
        display = load_display(jd)
        if not display or not display.get("positions"):
            raise ValueError("Predicted positions are not ready")
        payload = pack_static_fem_frame_bin(display)
    return (*read_frame(payload), thermal)


def pack_view(meta, positions, scalars, identities=None):
    """CVIZ v1: header, xyz float32, scalar float32, optional identity int32[4]."""
    positions = np.asarray(positions, dtype="<f4").reshape(-1, 3)
    scalars = np.asarray(scalars, dtype="<f4")
    if len(positions) != len(scalars) or not np.isfinite(positions).all():
        raise ValueError("Invalid visualization coordinates")
    header = orjson.dumps(
        dict(meta, count=len(positions), identities=identities is not None)
    )
    prefix = struct.pack("<3I", 0x5A495643, 1, len(header)) + header
    prefix += b"\0" * (-len(prefix) % 4)
    return (
        prefix
        + positions.tobytes()
        + scalars.tobytes()
        + (
            np.asarray(identities, dtype="<i4").tobytes()
            if identities is not None
            else b""
        )
    )


def _build(jd, mode):
    from backend.core.cando_runner import load_rmsf, _load_snapshot_design

    header, records, axis, thermal = _frame(jd)
    names = header["helix_ids"]
    meta = dict(
        kind=mode,
        thermal=thermal,
        frames=header.get("n_frames", 0),
        min=0.0,
        max=0.0,
        rmsd=0.0,
        helix_ids=names,
    )
    rmsf = (load_rmsf(jd) or {}).get("rmsf", []) if mode in ("flex", "cando") else []
    values = {(r["helix_id"], r["bp_index"]): r["rmsf_nm"] for r in rmsf}
    if values:
        meta.update(
            min=min(values.values()),
            max=float(np.percentile(list(values.values()), 95)),
        )
    if mode == "cando":
        from backend.core.cando_cylinders import compute_cylinders, axis_from_backbones

        nodes = [
            dict(
                helix_id=names[r["helix"]],
                bp_index=int(r["bp"]),
                position=r["position"].tolist(),
            )
            for r in axis
        ]
        if not nodes:
            nodes = axis_from_backbones(_position_dicts(records, names), rmsf)
        cylinders = compute_cylinders(_load_snapshot_design(jd), nodes, rmsf)
        points, scalars = [], []
        for helix in cylinders["helices"]:
            for i in range(1, len(helix["points"])):
                points.extend(helix["points"][i - 1 : i + 1])
                pair = [v for v in helix["rmsf"][i - 1 : i + 1] if v is not None]
                value = sum(pair) / len(pair) if pair else -1.0
                scalars.extend([value, value])
        for joint, value in zip(cylinders["joints"], cylinders["joint_rmsf"]):
            points.extend(joint)
            scalars.extend([value if value is not None else -1.0] * 2)
        meta.update(
            helices=cylinders["n_helices"],
            joints=cylinders["n_joints"],
            has_rmsf=bool(values),
        )
        return pack_view(meta, points, scalars)
    positions = records["coords"][:, :3]
    identities = np.column_stack(
        [records[k] for k in ("helix", "bp", "reverse", "copy")]
    )
    scalars = np.full(len(records), -1.0, dtype="<f4")
    if mode == "flex":
        if not values:
            raise ValueError("RMSF is not available for this job")
        scalars[:] = [
            values.get((names[r["helix"]], int(r["bp"])), -1.0) for r in records
        ]
    elif mode == "deviation":
        from backend.core.cando_deviation import compute_deviation

        # Compare the conformation actually displayed, including its loop-copy identity.
        result = compute_deviation(
            _load_snapshot_design(jd), _position_dicts(records, names)
        )
        scalars[:] = [p["deviation"] for p in result["positions"]]
        meta.update(
            min=result["min_deviation"],
            max=result["max_deviation"],
            rmsd=result["rmsd_nm"],
        )
    return pack_view(meta, positions, scalars, identities)


def _position_dicts(records, names):
    return [
        dict(
            helix_id=names[r["helix"]],
            bp_index=int(r["bp"]),
            copy=int(r["copy"]),
            direction="REVERSE" if r["reverse"] else "FORWARD",
            backbone_position=r["coords"][:3].tolist(),
        )
        for r in records
    ]


def visualization_file(job_dir: Path, mode: str) -> Path:
    if mode not in ("deform", "flex", "deviation", "cando"):
        raise ValueError("Unknown visualization mode")
    target = job_dir / f"visualization-v1-{mode}.bin"
    with _BUILD_LOCK:
        sources = [
            job_dir / name
            for name in (
                "display.json",
                "design.json",
                "rmsf.json",
                "thermal_representative.bin",
                "thermal_representative.json",
                "thermal_trajectory.json",
            )
        ]
        newest = max((p.stat().st_mtime_ns for p in sources if p.exists()), default=0)
        if target.exists() and target.stat().st_mtime_ns >= newest:
            return target
        payload = _build(job_dir, mode)
        fd, temporary = tempfile.mkstemp(dir=job_dir, prefix=target.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return target
