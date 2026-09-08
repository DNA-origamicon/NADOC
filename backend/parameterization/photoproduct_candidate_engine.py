"""Run a gate-neutral, real psfgen/NAMD integration smoke for a CPD candidate.

This module deliberately lives in the parameterization workflow.  It proves that a
candidate is complete enough for controlled engine testing without installing it in the
production force-field registry or claiming that its physics is validated.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

import numpy as np

from backend.core.dcd_fast import cell_to_dimensions, read_frame, read_layout
from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_psf_audit import (
    audit_photoproduct_psf,
    parse_psf_atoms,
    parse_psf_index_section,
)
from backend.core.photoproduct_registry import photoproduct_registry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked_source(record: object, label: str) -> Path:
    if not isinstance(record, dict) or not record.get("path"):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record["path"]))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def _require_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path is outside the storage root: {resolved}") from exc
    return resolved


def _now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _parse_xyz(path: Path, atom_map: list[str]) -> tuple[list[str], np.ndarray]:
    lines = path.read_text().splitlines()
    try:
        count = int(lines[0].strip())
    except (IndexError, ValueError) as exc:
        raise ValueError("boundary XYZ has no valid atom count") from exc
    records = [line.split() for line in lines[2:] if line.strip()]
    if count != len(records) or count != len(atom_map):
        raise ValueError("boundary XYZ and stable atom map counts differ")
    if any(len(record) < 4 for record in records):
        raise ValueError("boundary XYZ contains a malformed atom record")
    elements = [record[0] for record in records]
    try:
        coordinates = np.asarray(
            [[float(value) for value in record[1:4]] for record in records],
            dtype=float,
        )
    except ValueError as exc:
        raise ValueError("boundary XYZ contains a nonnumeric coordinate") from exc
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("boundary XYZ contains a non-finite coordinate")
    return elements, coordinates


def _terminal_atom_name(name: str) -> str:
    return {"HO5'": "H5T", "HO3'": "H3T"}.get(name, charmm_atom_name(name))


def _boundary_pdb(
    atom_map: list[str], elements: list[str], coordinates: np.ndarray
) -> str:
    records = []
    serial = 0
    for endpoint in (1, 2):
        for stable, element, xyz in zip(atom_map, elements, coordinates, strict=True):
            endpoint_text, separator, local = stable.partition(":")
            if not separator or endpoint_text not in {"1", "2"} or not local:
                raise ValueError(f"invalid boundary stable atom reference: {stable!r}")
            if int(endpoint_text) != endpoint:
                continue
            serial += 1
            name = _terminal_atom_name(local)
            records.append(
                f"ATOM  {serial:5d} {name:<4} THY D{endpoint:4d}    "
                f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}"
                f"{1.0:6.2f}{0.0:6.2f}      {'D000':>4} {element:>2}"
            )
    if serial != len(atom_map):
        raise ValueError("boundary stable atom map does not contain endpoints 1 and 2")
    return "\n".join([*records, "END", ""])


def _psfgen_script(
    *,
    topology: Path,
    lesion_topology: Path,
    pdb: Path,
    output_dir: Path,
    product: bool,
    patch_name: str,
) -> str:
    lines = [
        "package require psfgen",
        "resetpsf",
        f"topology {topology}",
    ]
    if product:
        lines.append(f"topology {lesion_topology}")
    lines.extend(
        [
            "segment D000 {",
            " first 5TER",
            " last 3TER",
            " auto angles dihedrals",
            f" pdb {pdb}",
            "}",
            "patch DEO5 D000:1",
            "patch DEOX D000:2",
            f"coordpdb {pdb} D000",
        ]
    )
    if product:
        lines.append(f"patch {patch_name} D000:1 D000:2")
    lines.append("regenerate angles dihedrals")
    stem = "product" if product else "reactant"
    lines.extend(
        [
            "guesscoord",
            f"writepsf {output_dir / f'{stem}.psf'}",
            f"writepdb {output_dir / f'{stem}.pdb'}",
            "exit",
            "",
        ]
    )
    return "\n".join(lines)


_ALLOWED_NAMD_WARNINGS = ("always using force tables for gpu nonbonded kernel",)


def _run_engine(
    command: list[str],
    *,
    cwd: Path,
    stdin: str | None,
    log_path: Path,
    extra_allowed_warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(completed.stdout)
    lower = completed.stdout.lower()
    diagnostics = [
        line.strip()
        for line in completed.stdout.splitlines()
        if any(
            token in line.lower()
            for token in (
                "fatal error",
                "unable to find",
                "missing parameter",
                "duplicate parameter",
                "error:",
            )
        )
    ]
    warnings = [
        line.strip()
        for line in completed.stdout.splitlines()
        if "warning:" in line.lower()
    ]
    unclassified_warnings = [
        line
        for line in warnings
        if not any(
            allowed in line.lower()
            for allowed in (*_ALLOWED_NAMD_WARNINGS, *extra_allowed_warnings)
        )
    ]
    errors = []
    if completed.returncode != 0:
        errors.append(f"engine exited with status {completed.returncode}")
    if diagnostics:
        errors.append("engine log contains error or parameter diagnostics")
    if unclassified_warnings:
        errors.append("engine log contains an unclassified warning")
    return {
        "command": command,
        "returncode": completed.returncode,
        "log": _source(log_path),
        "diagnostics": diagnostics,
        "warnings": warnings,
        "unclassified_warnings": unclassified_warnings,
        "successful_end_marker": "end of program" in lower,
        "errors": errors,
        "passed": not errors,
    }


def _namd_config(
    *,
    topology_psf: Path,
    starting_coordinates: Path,
    nucleic_parameters: Path,
    lesion_parameters: Path,
    output_stem: Path,
    action: str,
    steps: int,
    dcd_path: Path | None = None,
) -> str:
    coordinate_directives = [f"coordinates {topology_psf.with_suffix('.pdb')}"]
    if starting_coordinates.suffix == ".coor":
        coordinate_directives.append(f"binCoordinates {starting_coordinates}")
    else:
        coordinate_directives = [f"coordinates {starting_coordinates}"]
    lines = [
        f"structure {topology_psf}",
        *coordinate_directives,
        "paraTypeCharmm on",
        f"parameters {nucleic_parameters}",
        f"parameters {lesion_parameters}",
        "exclude scaled1-4",
        "oneFourScaling 1.0",
        "cutoff 12.0",
        "switching on",
        "switchdist 10.0",
        "pairlistdist 14.0",
        "margin 2.0",
        "stepspercycle 10",
        "outputEnergies 100",
        "computeEnergies 100",
        "restartfreq 100",
        "binaryrestart yes",
        f"outputName {output_stem}",
    ]
    if action == "load":
        lines.extend(["temperature 0", "rigidBonds none", "timestep 1.0", "run 0"])
    elif action == "minimize":
        lines.extend(
            [
                "temperature 0",
                "rigidBonds none",
                "timestep 1.0",
                f"minimize {steps}",
                "run 0",
            ]
        )
    elif action == "dynamics":
        if dcd_path is None:
            raise ValueError("dynamics requires a DCD output path")
        lines.extend(
            [
                "temperature 310",
                "langevin on",
                "langevinTemp 310",
                "langevinDamping 5.0",
                "langevinHydrogen on",
                "rigidBonds all",
                "timestep 2.0",
                "dcdFreq 10",
                f"dcdFile {dcd_path}",
                f"run {steps}",
            ]
        )
    else:
        raise ValueError(f"unknown candidate smoke action: {action}")
    return "\n".join([*lines, ""])


def _energy_audit(log_path: Path) -> dict[str, Any]:
    energy_lines = [
        line
        for line in log_path.read_text(errors="replace").splitlines()
        if line.lstrip().startswith("ENERGY:")
    ]
    nonfinite = any(
        token.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf"}
        for line in energy_lines
        for token in line.split()
    )
    return {
        "record_count": len(energy_lines),
        "all_finite": bool(energy_lines) and not nonfinite,
    }


def _minimum_nonbonded_heavy_ratio(
    coordinates: np.ndarray,
    heavy: list[int],
    atom_radii: dict[int, float],
    excluded_pairs: set[frozenset[int]],
    dimensions: np.ndarray | None,
) -> tuple[float, tuple[int, int] | None]:
    """Return the exact minimum radius-normalized heavy-atom separation.

    A nearest-neighbor candidate supplies an upper bound. Because every radius sum is
    at most ``max_radius_sum``, a periodic radius query using
    ``upper_bound * max_radius_sum`` necessarily includes every pair capable of beating
    it. This avoids an O(N^2) Python loop without weakening the clash audit.
    """

    from scipy.spatial import cKDTree

    if len(heavy) < 2:
        return math.inf, None
    heavy_array = np.asarray(heavy, dtype=int)
    points = np.asarray(coordinates[heavy_array], dtype=float)
    boxsize = None
    if dimensions is not None:
        boxsize = np.asarray(dimensions[:3], dtype=float)
        points = np.mod(points, boxsize)
    tree = cKDTree(points, boxsize=boxsize)
    best_ratio = math.inf
    best_pair: tuple[int, int] | None = None
    k = min(8, len(heavy))
    while best_pair is None:
        distances, neighbors = tree.query(points, k=k)
        distances = np.atleast_2d(distances)
        neighbors = np.atleast_2d(neighbors)
        for local_first in range(len(heavy)):
            for distance, local_second in zip(
                distances[local_first, 1:], neighbors[local_first, 1:], strict=True
            ):
                if local_second >= len(heavy):
                    continue
                first = heavy[local_first]
                second = heavy[int(local_second)]
                if frozenset((first, second)) in excluded_pairs:
                    continue
                ratio = float(distance) / (atom_radii[first] + atom_radii[second])
                if ratio < best_ratio:
                    best_ratio = ratio
                    best_pair = (first, second)
        if best_pair is not None or k == len(heavy):
            break
        k = min(len(heavy), k * 2)
    if best_pair is None:
        return math.inf, None

    max_radius_sum = 2.0 * max(atom_radii.values())
    local_pairs = tree.query_pairs(
        r=best_ratio * max_radius_sum,
        output_type="ndarray",
    )
    if not len(local_pairs):
        return best_ratio, best_pair
    global_first = heavy_array[local_pairs[:, 0]]
    global_second = heavy_array[local_pairs[:, 1]]
    keep = np.fromiter(
        (
            frozenset((int(first), int(second))) not in excluded_pairs
            for first, second in zip(global_first, global_second, strict=True)
        ),
        dtype=bool,
        count=len(local_pairs),
    )
    if not np.any(keep):
        return best_ratio, best_pair
    local_pairs = local_pairs[keep]
    global_first = global_first[keep]
    global_second = global_second[keep]
    deltas = points[local_pairs[:, 0]] - points[local_pairs[:, 1]]
    if boxsize is not None:
        deltas -= boxsize * np.round(deltas / boxsize)
    pair_distances = np.linalg.norm(deltas, axis=1)
    radius_sums = np.fromiter(
        (
            atom_radii[int(first)] + atom_radii[int(second)]
            for first, second in zip(global_first, global_second, strict=True)
        ),
        dtype=float,
        count=len(global_first),
    )
    ratios = pair_distances / radius_sums
    minimum = int(np.argmin(ratios))
    return float(ratios[minimum]), (
        int(global_first[minimum]),
        int(global_second[minimum]),
    )


def _trajectory_audit(
    psf_path: Path,
    dcd_path: Path,
    *,
    product: str = "TT-CPD",
    stereochemistry: str = "cis-syn",
    endpoints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    definition = load_chemical_definition(product, stereochemistry)
    atoms = parse_psf_atoms(psf_path.read_text(errors="replace"))
    by_identity = {
        (atom.segid, atom.resid, atom.name): index for index, atom in enumerate(atoms)
    }

    endpoint_map = (
        {
            str(item["endpoint"]): (str(item["segid"]), str(item["resid"]))
            for item in endpoints
        }
        if endpoints is not None
        else {"1": ("D000", "1"), "2": ("D000", "2")}
    )
    if set(endpoint_map) != {"1", "2"}:
        raise ValueError("candidate trajectory requires exactly endpoints 1 and 2")

    def resolve(reference: str) -> int:
        endpoint, local = reference.split(":", 1)
        segid, resid = endpoint_map[endpoint]
        return by_identity[(segid, resid, charmm_atom_name(local))]

    layout = read_layout(dcd_path)
    if layout.n_atoms != len(atoms) or layout.n_frames < 2:
        raise ValueError("candidate DCD atom/frame count is incompatible with its PSF")
    timestep_fs = layout.delta_ps * 1000.0 / layout.nsavc
    if not math.isclose(timestep_fs, 2.0, rel_tol=1e-4, abs_tol=1e-6):
        raise ValueError(f"candidate DCD timestep is {timestep_fs:g} fs, not 2 fs")
    crosslinks = [
        (bond["atom_1"], bond["atom_2"])
        for bond in definition["graph_delta"]["bonds_added"]
    ]
    retained = [
        (bond["atom_1"], bond["atom_2"])
        for bond in definition["graph_delta"]["bonds_retained"]
    ]
    bonds = [
        (first - 1, second - 1)
        for first, second in parse_psf_index_section(
            psf_path.read_text(errors="replace"), "!NBOND", 2
        )
    ]
    neighbors: dict[int, set[int]] = {}
    for first, second in bonds:
        neighbors.setdefault(first, set()).add(second)
        neighbors.setdefault(second, set()).add(first)
    excluded_pairs = {frozenset(pair) for pair in bonds}
    for center, attached in neighbors.items():
        for first in attached:
            for second in attached:
                if first != second:
                    excluded_pairs.add(frozenset((first, second)))
    radii = {"C": 0.76, "N": 0.71, "O": 0.66, "P": 1.07}

    def element(atom_index: int) -> str | None:
        mass = atoms[atom_index].mass
        return (
            min(
                radii,
                key=lambda symbol: abs(
                    mass - {"C": 12.011, "N": 14.007, "O": 15.999, "P": 30.974}[symbol]
                ),
            )
            if mass > 5
            else None
        )

    heavy = [index for index in range(len(atoms)) if element(index) is not None]
    atom_radii = {index: radii[element(index)] for index in heavy}
    frames = []
    errors = []
    for frame in range(layout.n_frames):
        coordinates, raw_cell = read_frame(dcd_path, layout, frame)
        dimensions = cell_to_dimensions(raw_cell)
        if dimensions is not None and not np.allclose(
            dimensions[3:], 90.0, atol=1.0e-4
        ):
            raise ValueError("candidate trajectory audit requires an orthorhombic cell")

        def displacement(first: np.ndarray, second: np.ndarray) -> np.ndarray:
            delta = first - second
            if dimensions is not None:
                lengths = dimensions[:3]
                delta = delta - lengths * np.round(delta / lengths)
            return delta

        chirality_coordinates = {}
        for center in definition["product_stereocenters"]:
            for reference in [center["atom"], *center["signed_volume_reference_atoms"]]:
                chirality_coordinates[reference] = coordinates[
                    resolve(reference)
                ].tolist()
        chirality = audit_product_chirality(definition, chirality_coordinates)

        def distances(pairs: list[tuple[str, str]]) -> list[float]:
            return [
                float(
                    np.linalg.norm(
                        displacement(
                            coordinates[resolve(first)], coordinates[resolve(second)]
                        )
                    )
                )
                for first, second in pairs
            ]

        observed = {
            "crosslinks": distances(crosslinks),
            "retained_ring_bonds": distances(retained),
            "glycosidic_bonds": distances([("1:C1'", "1:N1"), ("2:C1'", "2:N1")]),
        }
        closest_ratio, closest_pair = _minimum_nonbonded_heavy_ratio(
            coordinates,
            heavy,
            atom_radii,
            excluded_pairs,
            dimensions,
        )
        frame_errors = []
        if not chirality["passed"]:
            frame_errors.append("product chirality changed")
        if any(not 1.25 <= value <= 1.85 for value in observed["crosslinks"]):
            frame_errors.append("a CPD crosslink left its 1.25-1.85 A safety range")
        if any(not 1.25 <= value <= 1.85 for value in observed["retained_ring_bonds"]):
            frame_errors.append("a retained C5-C6 bond left its safety range")
        if any(not 1.25 <= value <= 1.75 for value in observed["glycosidic_bonds"]):
            frame_errors.append("a glycosidic bond left its safety range")
        if closest_ratio < 0.7:
            frame_errors.append(
                "a nonbonded heavy-atom contact crossed the 0.7 covalent-radius ratio"
            )
        errors.extend(f"frame {frame}: {error}" for error in frame_errors)
        frames.append(
            {
                "frame": frame,
                "chirality_passed": chirality["passed"],
                "distances_angstrom": observed,
                "minimum_nonbonded_covalent_radius_ratio": closest_ratio,
                "closest_nonbonded_heavy_atoms": (
                    [
                        list(atoms[closest_pair[0]].identity),
                        list(atoms[closest_pair[1]].identity),
                    ]
                    if closest_pair is not None
                    else None
                ),
                "errors": frame_errors,
            }
        )
    distance_summary = {}
    for category in ("crosslinks", "retained_ring_bonds", "glycosidic_bonds"):
        values = [
            value for frame in frames for value in frame["distances_angstrom"][category]
        ]
        distance_summary[category] = {
            "minimum_angstrom": min(values),
            "maximum_angstrom": max(values),
            "mean_angstrom": float(np.mean(values)),
        }
    return {
        "timestep_fs": timestep_fs,
        "frame_count": layout.n_frames,
        "chirality_pass_fraction": sum(frame["chirality_passed"] for frame in frames)
        / len(frames),
        "distance_summary": distance_summary,
        "minimum_nonbonded_covalent_radius_ratio": min(
            frame["minimum_nonbonded_covalent_radius_ratio"] for frame in frames
        ),
        "frames": frames,
        "errors": errors,
        "passed": not errors,
    }


def run_candidate_engine_smoke(
    *,
    candidate_manifest_path: Path,
    boundary_manifest_path: Path,
    nucleic_topology_path: Path,
    nucleic_parameters_path: Path,
    psfgen_path: Path,
    namd_path: Path,
    output_dir: Path,
    storage_root: Path,
    minimize_steps: int = 2000,
    dynamics_steps: int = 1000,
) -> dict[str, Any]:
    """Build, audit, minimize, and run one ordinary-mass 2 fs candidate smoke."""

    output_dir = _require_under(output_dir, storage_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite candidate engine smoke: {output_dir}"
        )
    if minimize_steps < 100 or dynamics_steps < 100 or dynamics_steps % 10:
        raise ValueError(
            "candidate smoke steps must be >=100 and dynamics divisible by 10"
        )
    for path, label in (
        (candidate_manifest_path, "candidate manifest"),
        (boundary_manifest_path, "boundary manifest"),
        (nucleic_topology_path, "nucleic topology"),
        (nucleic_parameters_path, "nucleic parameters"),
        (psfgen_path, "psfgen"),
        (namd_path, "NAMD"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is unavailable: {path}")

    candidate = json.loads(candidate_manifest_path.read_text())
    product_id = candidate.get("product_id")
    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == product_id
        ),
        None,
    )
    patch_name = candidate.get("patch_name")
    if (
        candidate.get("schema") != "nadoc.photoproduct-charmm-candidate.v1"
        or candidate.get("gate_effect") != "none"
        or registry_entry is None
        or not isinstance(patch_name, str)
        or re.fullmatch(r"[A-Z][A-Z0-9]{0,7}", patch_name) is None
    ):
        raise ValueError("unsupported candidate CHARMM manifest")
    variant = candidate.get("variant")
    if variant is None:
        variant = {
            "schema": "nadoc.photoproduct-parameter-variant.v1",
            "id": f"legacy-{_sha256(candidate_manifest_path)[:12]}",
            "kind": "legacy_candidate_manifest",
            "parent_candidate_manifest": None,
            "correction_policy": None,
        }
    if (
        not isinstance(variant, dict)
        or variant.get("schema") != "nadoc.photoproduct-parameter-variant.v1"
        or not isinstance(variant.get("id"), str)
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", variant["id"]) is None
    ):
        raise ValueError("candidate manifest has an invalid parameter variant identity")
    candidate_dir = candidate_manifest_path.parent
    assets = candidate.get("assets") or {}

    def candidate_asset(name: str) -> Path:
        record = assets.get(name) or {}
        relative = Path(str(record.get("path") or ""))
        if relative.is_absolute():
            raise ValueError(f"candidate {name} asset path must be relative")
        path = (candidate_dir / relative).resolve()
        try:
            path.relative_to(candidate_dir.resolve())
        except ValueError:
            raise ValueError(f"candidate {name} asset escapes its directory") from None
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            raise ValueError(f"candidate {name} asset is missing or hash-mismatched")
        return path

    lesion_topology = candidate_asset("topology")
    lesion_parameters = candidate_asset("parameters")
    topology_spec_path = candidate_asset("topology_audit_spec")
    boundary = json.loads(boundary_manifest_path.read_text())
    if (
        boundary.get("schema") != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or boundary.get("status") != "quantitatively_screened_boundary"
        or boundary.get("product_id") != product_id
        or boundary.get("atom_count") != 63
        or boundary.get("formal_charge") != -1
        or not (boundary.get("chirality_audit") or {}).get("passed")
    ):
        raise ValueError(
            "boundary manifest is not the screened matching TT-CPD d(TpT) model"
        )
    atom_map = boundary.get("atom_map")
    if not isinstance(atom_map, list) or len(atom_map) != len(set(atom_map)):
        raise ValueError("boundary stable atom map is missing or ambiguous")
    xyz_path = _checked_source(
        (boundary.get("outputs") or {}).get("xyz"), "boundary XYZ"
    )
    atom_map_path = _checked_source(
        (boundary.get("outputs") or {}).get("atom_map"), "boundary atom map"
    )
    if json.loads(atom_map_path.read_text()) != atom_map:
        raise ValueError("boundary manifest and atom-map asset differ")
    elements, coordinates = _parse_xyz(xyz_path, atom_map)

    output_dir.mkdir(parents=True, exist_ok=True)
    pdb_path = output_dir / "boundary.pdb"
    pdb_path.write_text(_boundary_pdb(atom_map, elements, coordinates))
    engine_runs = []
    for product in (False, True):
        stem = "product" if product else "reactant"
        script_path = output_dir / f"build_{stem}.tcl"
        script_path.write_text(
            _psfgen_script(
                topology=nucleic_topology_path.resolve(),
                lesion_topology=lesion_topology,
                pdb=pdb_path,
                output_dir=output_dir,
                product=product,
                patch_name=patch_name,
            )
        )
        run = _run_engine(
            [str(psfgen_path.resolve())],
            cwd=output_dir,
            stdin=script_path.read_text(),
            log_path=output_dir / f"psfgen_{stem}.log",
        )
        run.update({"stage": f"psfgen_{stem}", "input": _source(script_path)})
        engine_runs.append(run)
        if not run["passed"]:
            raise RuntimeError(f"{stem} psfgen build failed; see {run['log']['path']}")

    patch_plan = {
        "patches": [
            {
                "lesion_id": "candidate-model-lesion-1",
                "product_id": product_id,
                "endpoints": [
                    {"endpoint": 1, "segid": "D000", "resid": "1"},
                    {"endpoint": 2, "segid": "D000", "resid": "2"},
                ],
            }
        ],
        "reverse_identity": [
            {
                "lesion_id": "candidate-model-lesion-1",
                "endpoint": endpoint,
                "base_key": f"__candidate_dtpdt__:{endpoint}",
                "segid": "D000",
                "resid": str(endpoint),
            }
            for endpoint in (1, 2)
        ],
    }
    static_audit = audit_photoproduct_psf(
        product_psf_text=(output_dir / "product.psf").read_text(errors="replace"),
        reactant_psf_text=(output_dir / "reactant.psf").read_text(errors="replace"),
        patch_plan=patch_plan,
        topology_specs={product_id: json.loads(topology_spec_path.read_text())},
        # Extended PSF charges are serialized to six decimals.  The workbook's
        # exact pair-charge constraint is checked upstream; this tolerance covers
        # only the accumulated serialization error across 28 replaced atoms.
        charge_tolerance=2e-5,
    )
    static_path = output_dir / "static_topology_audit.json"
    static_path.write_text(json.dumps(static_audit, indent=2) + "\n")
    if not static_audit["passed"]:
        raise RuntimeError("candidate failed the product/reactant PSF topology audit")

    stages = [
        ("00_load", "load", 0, output_dir / "product.pdb", None),
        ("01_minimize", "minimize", minimize_steps, output_dir / "product.pdb", None),
        (
            "02_dynamics_2fs",
            "dynamics",
            dynamics_steps,
            output_dir / "output/01_minimize.coor",
            output_dir / "output/02_dynamics_2fs.dcd",
        ),
    ]
    (output_dir / "output").mkdir(exist_ok=True)
    stage_records = []
    for name, action, steps, start, dcd in stages:
        config = output_dir / f"{name}.conf"
        # NAMD 3.0.x Output.C still copies output prefixes into a 140-byte local
        # buffer.  Archive-backed evidence paths routinely exceed that limit and
        # can corrupt memory after the final coordinates are written.  NAMD runs
        # with output_dir as its cwd, so keep all mutable stage paths relative.
        relative_start = start.relative_to(output_dir)
        relative_dcd = dcd.relative_to(output_dir) if dcd is not None else None
        config.write_text(
            _namd_config(
                topology_psf=Path("product.psf"),
                starting_coordinates=relative_start,
                nucleic_parameters=nucleic_parameters_path.resolve(),
                lesion_parameters=lesion_parameters,
                output_stem=Path("output") / name,
                action=action,
                steps=steps,
                dcd_path=relative_dcd,
            )
        )
        run = _run_engine(
            [str(namd_path.resolve()), "+p1", "+setcpuaffinity", str(config)],
            cwd=output_dir,
            stdin=None,
            log_path=output_dir / f"{name}.log",
        )
        energy = _energy_audit(output_dir / f"{name}.log")
        if not run["successful_end_marker"]:
            run["errors"].append("NAMD log has no successful end marker")
        if not energy["all_finite"]:
            run["errors"].append("NAMD stage has no finite energy records")
        run["passed"] = not run["errors"]
        run.update(
            {
                "stage": name,
                "input": _source(config),
                "energy_audit": energy,
            }
        )
        engine_runs.append(run)
        stage_records.append(run)
        if not run["passed"]:
            raise RuntimeError(f"NAMD stage {name} failed; see {run['log']['path']}")

    dcd_path = output_dir / "output/02_dynamics_2fs.dcd"
    trajectory = _trajectory_audit(
        output_dir / "product.psf",
        dcd_path,
        product=registry_entry["product"],
        stereochemistry=registry_entry["stereochemistry"],
    )
    errors = [
        error for run in engine_runs for error in run.get("errors") or []
    ] + trajectory["errors"]
    report = {
        "schema": "nadoc.photoproduct-candidate-engine-smoke.v1",
        "status": "passed_candidate_engine_smoke_not_released"
        if not errors
        else "failed",
        "passed": not errors,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "product": registry_entry["product"],
        "stereochemistry": registry_entry["stereochemistry"],
        "variant": variant,
        "finished_at": _now(),
        "integrator": {"ordinary_mass": True, "timestep_fs": 2.0, "hmr": False},
        "sources": {
            "candidate_manifest": _source(candidate_manifest_path),
            "boundary_manifest": _source(boundary_manifest_path),
            "nucleic_topology": _source(nucleic_topology_path),
            "nucleic_parameters": _source(nucleic_parameters_path),
            "psfgen": _source(psfgen_path),
            "namd": _source(namd_path),
        },
        "static_topology_audit": _source(static_path),
        "engine_runs": engine_runs,
        "trajectory": {**trajectory, "dcd": _source(dcd_path)},
        "errors": errors,
        "authorization": (
            "This proves candidate completeness and short-run numerical stability only; "
            "it does not install or release the force field for production science."
        ),
    }
    report_path = output_dir / "candidate_engine_smoke.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def _solution_namd_config(
    *,
    topology_psf: Path,
    starting_coordinates: Path,
    nucleic_parameters: Path,
    lesion_parameters: Path,
    water_parameters: Path,
    ion_nbfix_parameters: Path,
    output_stem: Path,
    box_nm: tuple[float, float, float],
    action: str,
    steps: int,
    dcd_path: Path | None = None,
    previous_output: Path | None = None,
) -> str:
    """Render one ordinary-mass, periodic candidate-solution stage."""

    bx, by, bz = (value * 10.0 for value in box_nm)
    directives = [f"coordinates {starting_coordinates}"]
    if starting_coordinates.suffix == ".coor":
        # NAMD still requires an ASCII coordinate declaration as a reference even
        # when a binary restart supplies the active coordinates.
        directives = [
            f"coordinates {topology_psf.with_suffix('.pdb')}",
            f"binCoordinates {starting_coordinates}",
        ]
    if previous_output is not None:
        directives.extend(
            [
                f"binVelocities {previous_output}.vel",
                f"extendedSystem {previous_output}.xsc",
            ]
        )
    lines = [
        f"structure {topology_psf}",
        *directives,
        "paraTypeCharmm on",
        f"parameters {nucleic_parameters}",
        f"parameters {lesion_parameters}",
        f"parameters {water_parameters}",
        f"parameters {ion_nbfix_parameters}",
        "exclude scaled1-4",
        "oneFourScaling 1.0",
        "cutoff 12.0",
        "switching on",
        "switchdist 10.0",
        "pairlistdist 14.0",
        "margin 2.0",
        "stepspercycle 10",
        "nonbondedFreq 1",
        "fullElectFrequency 1",
        "PME yes",
        "PMEGridSpacing 1.0",
        f"cellBasisVector1 {bx:.6f} 0.0 0.0",
        f"cellBasisVector2 0.0 {by:.6f} 0.0",
        f"cellBasisVector3 0.0 0.0 {bz:.6f}",
        f"cellOrigin {bx / 2.0:.6f} {by / 2.0:.6f} {bz / 2.0:.6f}",
        "wrapAll on",
        "wrapWater on",
        "outputEnergies 100",
        "computeEnergies 100",
        "restartfreq 1000",
        "xstFreq 1000",
        "binaryrestart yes",
        f"outputName {output_stem}",
    ]
    if action == "load":
        lines.extend(["temperature 0", "rigidBonds none", "timestep 1.0", "run 0"])
    elif action == "minimize":
        lines.extend(
            [
                "temperature 0",
                "rigidBonds none",
                "timestep 1.0",
                f"minimize {steps}",
                "run 0",
            ]
        )
    elif action in {"heat", "dynamics"}:
        if dcd_path is None:
            raise ValueError(f"{action} requires a DCD output path")
        timestep = 1.0 if action == "heat" else 2.0
        lines.extend(
            [
                "temperature 50" if previous_output is None else "",
                "langevin on",
                "langevinTemp 310",
                "langevinDamping 5.0",
                "langevinHydrogen on",
                "rigidBonds all",
                f"timestep {timestep:.1f}",
                "dcdFreq 100",
                f"dcdFile {dcd_path}",
                f"run {steps}",
            ]
        )
    else:
        raise ValueError(f"unknown candidate solution action: {action}")
    return "\n".join([line for line in lines if line] + [""])


def run_candidate_solution_smoke(
    *,
    candidate_manifest_path: Path,
    vacuum_smoke_report_path: Path,
    nucleic_parameters_path: Path,
    water_parameters_path: Path,
    ion_nbfix_parameters_path: Path,
    namd_path: Path,
    output_dir: Path,
    storage_root: Path,
    padding_nm: float = 1.2,
    ion_conc_mM: float = 150.0,
    seed: int = 42,
    minimize_steps: int = 5000,
    heat_steps: int = 10000,
    dynamics_steps: int = 50000,
) -> dict[str, Any]:
    """Solvate and exercise a passed d(TpT) candidate without releasing it.

    This is deliberately separate from NADOC's production package builder. It accepts
    only a hash-linked, passed gate-neutral vacuum smoke and never changes registry gates.
    """

    from backend.core.md_charge import audit_psf
    from backend.core.namd_solvate import (
        _build_solvated_pdb,
        _extend_psf,
        _find_gmx,
        _find_last_atom_serial,
        _gmx_solvate,
        _place_ions_mixed,
        ion_counts,
    )

    output_dir = _require_under(output_dir, storage_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite candidate solution smoke: {output_dir}"
        )
    if (
        padding_nm < 0.8
        or ion_conc_mM < 0
        or minimize_steps < 100
        or heat_steps < 100
        or dynamics_steps < 100
        or dynamics_steps % 100
    ):
        raise ValueError("invalid candidate solution protocol settings")
    for path, label in (
        (candidate_manifest_path, "candidate manifest"),
        (vacuum_smoke_report_path, "vacuum smoke report"),
        (nucleic_parameters_path, "nucleic parameters"),
        (water_parameters_path, "water/ion parameters"),
        (ion_nbfix_parameters_path, "ion NBFIX parameters"),
        (namd_path, "NAMD"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is unavailable: {path}")

    candidate = json.loads(candidate_manifest_path.read_text())
    vacuum = json.loads(vacuum_smoke_report_path.read_text())
    product_id = candidate.get("product_id")
    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == product_id
        ),
        None,
    )
    expected_candidate = (vacuum.get("sources") or {}).get("candidate_manifest") or {}
    if (
        candidate.get("schema") != "nadoc.photoproduct-charmm-candidate.v1"
        or candidate.get("gate_effect") != "none"
        or registry_entry is None
        or vacuum.get("schema") != "nadoc.photoproduct-candidate-engine-smoke.v1"
        or vacuum.get("passed") is not True
        or vacuum.get("gate_effect") != "none"
        or vacuum.get("product_id") != product_id
        or expected_candidate.get("sha256") != _sha256(candidate_manifest_path)
    ):
        raise ValueError(
            "solution smoke requires the matching passed gate-neutral vacuum smoke"
        )
    vacuum_dir = vacuum_smoke_report_path.parent
    product_psf = vacuum_dir / "product.psf"
    product_pdb = vacuum_dir / "product.pdb"
    if not product_psf.is_file() or not product_pdb.is_file():
        raise FileNotFoundError("vacuum smoke product PSF/PDB pair is missing")
    assets = candidate.get("assets") or {}
    lesion_record = assets.get("parameters") or {}
    lesion_relative = Path(str(lesion_record.get("path") or ""))
    if lesion_relative.is_absolute():
        raise ValueError("candidate lesion parameter path must be relative")
    lesion_parameters = (candidate_manifest_path.parent / lesion_relative).resolve()
    try:
        lesion_parameters.relative_to(candidate_manifest_path.parent.resolve())
    except ValueError:
        raise ValueError(
            "candidate lesion parameter path escapes its directory"
        ) from None
    if not lesion_parameters.is_file() or _sha256(
        lesion_parameters
    ) != lesion_record.get("sha256"):
        raise ValueError("candidate lesion parameters are missing or hash-mismatched")

    output_dir.mkdir(parents=True, exist_ok=True)
    gmx_path = Path(_find_gmx()).resolve()
    with tempfile.TemporaryDirectory(prefix="nadoc_candidate_solution_") as raw_tmp:
        waters, box_nm, recentered_pdb = _gmx_solvate(
            product_pdb.read_text(errors="replace"),
            padding_nm,
            Path(raw_tmp),
            box_mode="bbox",
        )
    solute_charge = float(
        audit_psf(product_psf.read_text(errors="replace")).total_charge
    )
    ions = ion_counts(
        len(waters),
        solute_charge,
        nacl_mM=ion_conc_mM,
        mgcl2_mM=0.0,
        box_nm=box_nm,
        mg_hexahydrate=False,
    )
    waters, na_pos, mg_pos, cl_pos, mgh_clusters = _place_ions_mixed(
        waters,
        ions.n_na,
        ions.n_mg,
        ions.n_cl,
        seed=seed,
        mg_hexahydrate=False,
        dna_pdb_text=recentered_pdb,
    )
    base_serial = _find_last_atom_serial(product_psf.read_text(errors="replace"))
    solvated_psf_text = _extend_psf(
        product_psf.read_text(errors="replace"),
        waters,
        na_pos,
        cl_pos,
        mg_pos=mg_pos,
        mgh_clusters=mgh_clusters,
    )
    solvated_pdb_text = _build_solvated_pdb(
        recentered_pdb,
        waters,
        na_pos,
        cl_pos,
        box_nm,
        base_serial,
        mg_pos=mg_pos,
        mgh_clusters=mgh_clusters,
    )
    solvated_psf = output_dir / "product_solvated.psf"
    solvated_pdb = output_dir / "product_solvated.pdb"
    solvated_psf.write_text(solvated_psf_text)
    solvated_pdb.write_text(solvated_pdb_text)
    topology_audit = audit_psf(
        solvated_psf_text,
        require_neutral=True,
        require_dna_hydrogens=True,
        require_dna_residue_charge=True,
    )
    topology_audit_path = output_dir / "solvated_topology_audit.json"
    topology_audit_path.write_text(
        json.dumps(topology_audit.to_dict(), indent=2) + "\n"
    )
    if not topology_audit.passed:
        raise RuntimeError(
            "candidate solvated topology audit failed: "
            + "; ".join(topology_audit.errors)
        )

    (output_dir / "output").mkdir(exist_ok=True)
    stages = [
        ("00_load", "load", 0, Path("product_solvated.pdb"), None, None),
        (
            "01_minimize",
            "minimize",
            minimize_steps,
            Path("product_solvated.pdb"),
            None,
            None,
        ),
        (
            "02_heat_1fs",
            "heat",
            heat_steps,
            Path("output/01_minimize.coor"),
            Path("output/02_heat_1fs.dcd"),
            None,
        ),
        (
            "03_dynamics_2fs",
            "dynamics",
            dynamics_steps,
            Path("output/02_heat_1fs.coor"),
            Path("output/03_dynamics_2fs.dcd"),
            Path("output/02_heat_1fs"),
        ),
    ]
    engine_runs = []
    for name, action, steps, start, dcd, previous in stages:
        config = output_dir / f"{name}.conf"
        config.write_text(
            _solution_namd_config(
                topology_psf=Path("product_solvated.psf"),
                starting_coordinates=start,
                nucleic_parameters=nucleic_parameters_path.resolve(),
                lesion_parameters=lesion_parameters,
                water_parameters=water_parameters_path.resolve(),
                ion_nbfix_parameters=ion_nbfix_parameters_path.resolve(),
                output_stem=Path("output") / name,
                box_nm=box_nm,
                action=action,
                steps=steps,
                dcd_path=dcd,
                previous_output=previous,
            )
        )
        run = _run_engine(
            [str(namd_path.resolve()), "+p4", "+setcpuaffinity", str(config)],
            cwd=output_dir,
            stdin=None,
            log_path=output_dir / f"{name}.log",
            extra_allowed_warnings=(
                f"ignored {len(waters)} bonds with zero force constants",
                "will get h-h distance in rigid h2o from h-o-h angle",
            ),
        )
        energy = _energy_audit(output_dir / f"{name}.log")
        if not run["successful_end_marker"]:
            run["errors"].append("NAMD log has no successful end marker")
        if not energy["all_finite"]:
            run["errors"].append("NAMD stage has no finite energy records")
        run["passed"] = not run["errors"]
        run.update({"stage": name, "input": _source(config), "energy_audit": energy})
        engine_runs.append(run)
        if not run["passed"]:
            raise RuntimeError(
                f"NAMD solution stage {name} failed; see {run['log']['path']}"
            )

    dcd_path = output_dir / "output/03_dynamics_2fs.dcd"
    trajectory = _trajectory_audit(
        solvated_psf,
        dcd_path,
        product=registry_entry["product"],
        stereochemistry=registry_entry["stereochemistry"],
    )
    errors = [error for run in engine_runs for error in run.get("errors") or []]
    errors.extend(trajectory["errors"])
    report = {
        "schema": "nadoc.photoproduct-candidate-solution-smoke.v1",
        "status": "passed_candidate_solution_smoke_not_released"
        if not errors
        else "failed",
        "passed": not errors,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "product": registry_entry["product"],
        "stereochemistry": registry_entry["stereochemistry"],
        "variant": candidate.get("variant") or vacuum.get("variant"),
        "finished_at": _now(),
        "protocol": {
            "solvent": "TIP3P",
            "nacl_mM": ion_conc_mM,
            "padding_nm": padding_nm,
            "minimize_steps": minimize_steps,
            "heat_steps_1fs": heat_steps,
            "dynamics_steps_2fs": dynamics_steps,
            "ordinary_mass": True,
            "hmr": False,
        },
        "system": {
            "box_nm": list(box_nm),
            "waters": len(waters),
            "sodium": len(na_pos),
            "chloride": len(cl_pos),
            "solute_charge_e": solute_charge,
            "total_charge_e": topology_audit.total_charge,
        },
        "sources": {
            "candidate_manifest": _source(candidate_manifest_path),
            "vacuum_smoke_report": _source(vacuum_smoke_report_path),
            "vacuum_product_psf": _source(product_psf),
            "vacuum_product_pdb": _source(product_pdb),
            "nucleic_parameters": _source(nucleic_parameters_path),
            "lesion_parameters": _source(lesion_parameters),
            "water_parameters": _source(water_parameters_path),
            "ion_nbfix_parameters": _source(ion_nbfix_parameters_path),
            "namd": _source(namd_path),
            "gromacs": _source(gmx_path),
        },
        "solvated_topology_audit": _source(topology_audit_path),
        "engine_runs": engine_runs,
        "trajectory": {**trajectory, "dcd": _source(dcd_path)},
        "errors": errors,
        "authorization": (
            "This is an isolated d(TpT) solution-phase candidate test. It does not "
            "validate duplex/origami transferability or release the force field."
        ),
    }
    report_path = output_dir / "candidate_solution_smoke.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
