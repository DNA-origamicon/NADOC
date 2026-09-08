#!/usr/bin/env python3
"""Atomically extract the latest complete Psi4 geometry as a recovery checkpoint."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

LINE = re.compile(
    r"^\s*([A-Z][a-z]?)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s*$"
)


def latest(text: str, atom_count: int) -> list[tuple[str, str, str, str]]:
    candidates: list[list[tuple[str, str, str, str]]] = []
    lines = text.splitlines()
    for index, row in enumerate(lines):
        if "Geometry (in Angstrom)" not in row:
            continue
        atoms: list[tuple[str, str, str, str]] = []
        started = False
        for atom_row in lines[index + 1 :]:
            match = LINE.match(atom_row)
            if match:
                started = True
                atoms.append(match.groups())
                if len(atoms) == atom_count:
                    candidates.append(atoms)
                    break
            elif started:
                break
    if not candidates:
        raise ValueError("no complete geometry is available")
    return candidates[-1]


def main() -> int:
    job_dir = Path(sys.argv[1])
    manifest = json.loads((job_dir / "job_manifest.json").read_text())
    output = job_dir / "output.dat"
    atoms = latest(output.read_text(errors="replace"), int(manifest["atom_count"]))
    xyz = (
        f"{len(atoms)}\nlatest complete geometry from live Psi4 output\n"
        + "\n".join(f"{e:<2} {x} {y} {z}" for e, x, y, z in atoms)
        + "\n"
    )
    temporary = job_dir / "checkpoint_latest.xyz.tmp"
    temporary.write_text(xyz)
    os.replace(temporary, job_dir / "checkpoint_latest.xyz")
    checkpoint = {
        "schema": "nadoc.photoproduct-qm-live-checkpoint.v1",
        "status": "partial_not_converged",
        "gate_effect": "none",
        "simulation_ready": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "output_bytes_observed": output.stat().st_size,
        "checkpoint_xyz_sha256": hashlib.sha256(xyz.encode()).hexdigest(),
        "atom_count": len(atoms),
    }
    temporary_json = job_dir / "checkpoint_latest.json.tmp"
    temporary_json.write_text(json.dumps(checkpoint, indent=2) + "\n")
    os.replace(temporary_json, job_dir / "checkpoint_latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
