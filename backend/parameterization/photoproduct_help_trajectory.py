"""Package real, audited NAMD lesion frames for the TT-CPD Help viewer."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.core.dcd_fast import read_frame, read_layout
from backend.core.photoproduct_psf_audit import parse_psf_atoms, parse_psf_index_section
from backend.core.photoproduct_registry import photoproduct_registry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _element(atom_name: str) -> str:
    stripped = atom_name.lstrip("0123456789")
    element = stripped[:1].upper()
    if element not in {"H", "C", "N", "O", "P", "S"}:
        raise ValueError(f"cannot infer DNA element from PSF atom name {atom_name!r}")
    return element


def build_photoproduct_help_trajectory(
    *,
    product_id: str,
    dcd_path: Path,
    psf_path: Path,
    parameter_path: Path,
    static_topology_audit_path: Path,
    namd_smoke_report_path: Path,
    output_path: Path,
    max_frames: int = 120,
) -> dict[str, Any]:
    """Downsample real NAMD frames only after topology and smoke validation pass."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite help trajectory: {output_path}")
    if max_frames < 2:
        raise ValueError("help trajectory requires max_frames >= 2")
    registry = photoproduct_registry()
    entry = next((item for item in registry["products"] if item["id"] == product_id), None)
    if entry is None:
        raise ValueError(f"unregistered photoproduct id: {product_id}")
    required_paths = (
        dcd_path,
        psf_path,
        parameter_path,
        static_topology_audit_path,
        namd_smoke_report_path,
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("required help-trajectory evidence is missing: " + ", ".join(missing))
    static_audit = json.loads(static_topology_audit_path.read_text())
    smoke = json.loads(namd_smoke_report_path.read_text())
    dcd_hash = _sha256(dcd_path)
    psf_hash = _sha256(psf_path)
    parameter_hash = _sha256(parameter_path)
    static_hash = _sha256(static_topology_audit_path)
    if (
        static_audit.get("schema")
        != "nadoc.photoproduct-static-topology-audit.v1"
        or static_audit.get("status") != "passed"
        or not static_audit.get("passed")
    ):
        raise ValueError("help trajectory requires a passed static topology audit")
    if (
        smoke.get("schema") != "nadoc.photoproduct-namd-smoke.v1"
        or smoke.get("status") != "passed"
        or smoke.get("passed") is not True
        or product_id not in (smoke.get("product_ids") or [])
        or smoke.get("psf_sha256") != psf_hash
        or smoke.get("dcd_sha256") != dcd_hash
        or smoke.get("parameters_sha256") != parameter_hash
        or smoke.get("static_topology_audit_sha256") != static_hash
        or float(smoke.get("timestep_fs", math.inf)) > 2.0
        or smoke.get("hmr") is not False
    ):
        raise ValueError("NAMD smoke report is not passed, safe, and hash-linked")
    lesion_records = [
        item for item in static_audit.get("lesions") or [] if item.get("product_id") == product_id
    ]
    if len(lesion_records) != 1:
        raise ValueError("help trajectory requires exactly one audited lesion of the requested type")
    endpoints = lesion_records[0].get("endpoints") or []
    if [item.get("endpoint") for item in endpoints] != [1, 2]:
        raise ValueError("static audit lacks ordered endpoint PSF identities")

    psf_atoms = parse_psf_atoms(psf_path.read_text())
    selected: list[tuple[int, Any, int]] = []
    for endpoint in endpoints:
        matches = [
            atom
            for atom in psf_atoms
            if atom.segid == endpoint["segid"] and atom.resid == str(endpoint["resid"])
        ]
        if not matches:
            raise ValueError(f"PSF endpoint {endpoint['endpoint']} resolves no atoms")
        selected.extend((atom.index - 1, atom, int(endpoint["endpoint"])) for atom in matches)
    selected.sort(key=lambda item: item[0])
    if len({item[0] for item in selected}) != len(selected):
        raise ValueError("ordered lesion endpoints overlap in the PSF")
    local_index = {psf_index: index for index, (psf_index, _atom, _endpoint) in enumerate(selected)}
    atom_keys = [f"{endpoint}:{atom.name}" for _index, atom, endpoint in selected]
    if len(atom_keys) != len(set(atom_keys)):
        raise ValueError("selected lesion atom keys are ambiguous")
    psf_bonds = parse_psf_index_section(psf_path.read_text(), "!NBOND", 2)
    bonds = sorted(
        [local_index[first - 1], local_index[second - 1]]
        for first, second in psf_bonds
        if first - 1 in local_index and second - 1 in local_index
    )
    keyed_bonds = {
        frozenset((atom_keys[first], atom_keys[second])) for first, second in bonds
    }
    required_crosslinks = {
        frozenset(pair.split("--")) for pair in entry["graph_delta"]["bonds_added"]
    }
    if not required_crosslinks.issubset(keyed_bonds):
        raise ValueError("help trajectory PSF lacks the requested isomer's covalent crosslinks")

    layout = read_layout(dcd_path)
    if layout.n_atoms != len(psf_atoms) or layout.n_frames < 2:
        raise ValueError("DCD atom count/frame count is incompatible with the PSF")
    if layout.nsavc <= 0 or layout.delta_ps <= 0:
        raise ValueError("DCD does not record a positive NAMD timestep/stride")
    inferred_timestep_fs = layout.delta_ps * 1000.0 / layout.nsavc
    if not math.isclose(
        inferred_timestep_fs, float(smoke["timestep_fs"]), rel_tol=1e-4, abs_tol=1e-6
    ):
        raise ValueError("DCD header timestep differs from the NAMD smoke report")
    frame_stride = max(1, math.ceil(layout.n_frames / max_frames))
    source_indices = list(range(0, layout.n_frames, frame_stride))
    frames = []
    selected_indices = [item[0] for item in selected]
    for frame_index in source_indices:
        coordinates, _cell = read_frame(dcd_path, layout, frame_index)
        frames.append(coordinates[selected_indices].astype(float).tolist())
    engine = smoke.get("engine")
    engine_label = (
        f"{engine.get('name')} {engine.get('version')}"
        if isinstance(engine, dict)
        else str(engine)
    )
    if not engine_label.strip() or engine_label == "None":
        raise ValueError("NAMD smoke report has no engine identity")
    payload = {
        "schema": "nadoc.photoproduct-help-trajectory.v1",
        "product_id": product_id,
        "units": "angstrom",
        "atom_keys": atom_keys,
        "elements": [_element(atom.name) for _index, atom, _endpoint in selected],
        "bonds": bonds,
        "frames": frames,
        "timestep_fs": float(smoke["timestep_fs"]),
        "stride_steps": int(layout.nsavc * frame_stride),
        "source_frame_indices": source_indices,
        "provenance": {
            "engine": engine_label,
            "source_dcd_sha256": dcd_hash,
            "topology_sha256": psf_hash,
            "parameters_sha256": parameter_hash,
            "static_topology_audit_sha256": static_hash,
            "namd_smoke_report_sha256": _sha256(namd_smoke_report_path),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    return payload
