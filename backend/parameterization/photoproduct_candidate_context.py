"""Gate-neutral photoproduct topology validation in real NADOC DNA contexts.

This module deliberately stops at topology. Candidate assets may prove that a patch can
resolve stable base keys and build an exact PSF across strands, but their unrefined design
coordinates are not safe product coordinates and are never passed to NAMD here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from typing import Any

import numpy as np

from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.core.base_keys import resolve_base_keys
from backend.core.cpd_product import place_product_template
from backend.core.md_charge import audit_psf
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    HalfCrossover,
    PhotoproductJunction,
    Strand,
    StrandType,
)
from backend.core.namd_topology import (
    _psfgen_script as _context_psfgen_script,
    _write_segment_pdbs,
    photoproduct_patch_plan,
    charmm_atom_name,
)
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


def _require_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path is outside the storage root: {resolved}") from exc
    return resolved


def _candidate_asset(manifest_path: Path, manifest: dict[str, Any], name: str) -> Path:
    record = (manifest.get("assets") or {}).get(name) or {}
    relative = Path(str(record.get("path") or ""))
    if not relative.parts or relative.is_absolute():
        raise ValueError(f"candidate {name} path must be nonempty and relative")
    path = (manifest_path.parent / relative).resolve()
    try:
        path.relative_to(manifest_path.parent.resolve())
    except ValueError:
        raise ValueError(f"candidate {name} escapes its directory") from None
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"candidate {name} is missing or hash-mismatched")
    return path


def _run_psfgen(psfgen: Path, script: str, cwd: Path, log: Path) -> None:
    completed = subprocess.run(
        [str(psfgen.resolve())],
        input=script,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text(completed.stdout)
    diagnostics = [
        line
        for line in completed.stdout.splitlines()
        if any(token in line.lower() for token in ("fatal", "error", "unknown atom"))
    ]
    if (
        completed.returncode
        or diagnostics
        or "total of" not in completed.stdout.lower()
    ):
        raise RuntimeError(
            f"candidate context psfgen failed; see {log}: "
            + "; ".join(diagnostics[-10:])
        )


def build_reciprocal_crossover_1xt_context(*, stereochemistry: str) -> Design:
    """Return a deterministic cross-segment extra-extra topology fixture.

    The two inserts belong to different routed strands. This fixture validates stable
    identity and patch application only; it is intentionally not called a duplex or a
    coordinate-validation system.
    """

    from backend.core.lattice import make_bundle_design

    base = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=28, plane="XY")
    first_helix, second_helix = (helix.id for helix in base.helices)
    crossover_bp = 16
    first_strand = Strand(
        id="context_strand_a",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id=first_helix,
                start_bp=crossover_bp - 7,
                end_bp=crossover_bp,
                direction=Direction.FORWARD,
            ),
            Domain(
                helix_id=second_helix,
                start_bp=crossover_bp,
                end_bp=crossover_bp - 7,
                direction=Direction.REVERSE,
            ),
        ],
    )
    second_strand = Strand(
        id="context_strand_b",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id=second_helix,
                start_bp=crossover_bp + 8,
                end_bp=crossover_bp + 1,
                direction=Direction.REVERSE,
            ),
            Domain(
                helix_id=first_helix,
                start_bp=crossover_bp + 1,
                end_bp=crossover_bp + 8,
                direction=Direction.FORWARD,
            ),
        ],
    )
    crossovers = [
        Crossover(
            id="context_xo_a",
            half_a=HalfCrossover(
                helix_id=first_helix,
                index=crossover_bp,
                strand=Direction.FORWARD,
            ),
            half_b=HalfCrossover(
                helix_id=second_helix,
                index=crossover_bp,
                strand=Direction.REVERSE,
            ),
            extra_bases="T",
            process_id="photoproduct-validation-fixture-v1",
        ),
        Crossover(
            id="context_xo_b",
            half_a=HalfCrossover(
                helix_id=first_helix,
                index=crossover_bp + 1,
                strand=Direction.FORWARD,
            ),
            half_b=HalfCrossover(
                helix_id=second_helix,
                index=crossover_bp + 1,
                strand=Direction.REVERSE,
            ),
            extra_bases="T",
            process_id="photoproduct-validation-fixture-v1",
        ),
    ]
    lesion = PhotoproductJunction(
        id="context-extra-extra-interstrand",
        base_key_1="__xb__:context_xo_a:0",
        base_key_2="__xb__:context_xo_b:0",
        product="TT-CPD",
        stereochemistry=stereochemistry,
        formation="manual",
        patch_order="base-key-1-first",
        orientation_method="candidate-topology-fixture-v1",
        photoproduct_id="TT-CPD",
    )
    return base.copy_with(
        strands=[first_strand, second_strand],
        crossovers=crossovers,
        photoproduct_junctions=[lesion],
    )


def build_duplex_context(*, stereochemistry: str, relationship: str) -> Design:
    """Return a deterministic native-base duplex context for placement validation."""

    if relationship not in {"adjacent-intrastrand", "antiparallel-interstrand"}:
        raise ValueError(f"unsupported duplex context relationship: {relationship}")
    from backend.core.lattice import make_bundle_design

    design = make_bundle_design(cells=[(0, 0)], length_bp=28, plane="XY")
    strands = [
        strand.model_copy(update={"sequence": "T" * 28}) for strand in design.strands
    ]
    helix_id = design.helices[0].id
    if relationship == "adjacent-intrastrand":
        keys = (f"{helix_id}:13:FORWARD", f"{helix_id}:14:FORWARD")
    else:
        keys = (f"{helix_id}:14:FORWARD", f"{helix_id}:14:REVERSE")
    lesion = PhotoproductJunction(
        id=f"context-{relationship}",
        base_key_1=keys[0],
        base_key_2=keys[1],
        product="TT-CPD",
        stereochemistry=stereochemistry,
        formation="manual",
        patch_order="base-key-1-first",
        orientation_method="candidate-duplex-fixture-v1",
        photoproduct_id="TT-CPD",
    )
    return design.copy_with(strands=strands, photoproduct_junctions=[lesion])


def build_candidate_context_topology(
    *,
    design: Design,
    candidate_manifest_path: Path,
    psfgen_path: Path,
    output_dir: Path,
    storage_root: Path,
    atomistic_model: AtomisticModel | None = None,
    coordinates_product_fitted: bool = False,
) -> dict[str, Any]:
    """Build and audit a candidate product/reactant PSF pair in one design context."""

    output_dir = _require_under(output_dir, storage_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite candidate context: {output_dir}")
    if not candidate_manifest_path.is_file() or not psfgen_path.is_file():
        raise FileNotFoundError(
            "candidate manifest and real psfgen executable are required"
        )
    candidate = json.loads(candidate_manifest_path.read_text())
    product_id = candidate.get("product_id")
    patch_name = candidate.get("patch_name")
    registry_entry = next(
        (
            item
            for item in photoproduct_registry()["products"]
            if item["id"] == product_id
        ),
        None,
    )
    lesions = list(design.photoproduct_junctions)
    if (
        candidate.get("schema") != "nadoc.photoproduct-charmm-candidate.v1"
        or candidate.get("gate_effect") != "none"
        or registry_entry is None
        or not isinstance(patch_name, str)
        or re.fullmatch(r"[A-Z][A-Z0-9]{0,7}", patch_name) is None
        or len(lesions) != 1
        or lesions[0].product != registry_entry["product"]
        or lesions[0].stereochemistry != registry_entry["stereochemistry"]
        or not lesions[0].is_resolved_identity
    ):
        raise ValueError("candidate context requires one matching resolved lesion")
    lesion_topology = _candidate_asset(candidate_manifest_path, candidate, "topology")
    topology_spec_path = _candidate_asset(
        candidate_manifest_path, candidate, "topology_audit_spec"
    )
    topology_record = candidate["assets"]["topology"]
    if topology_record.get("patch_name") not in {None, patch_name}:
        raise ValueError("candidate topology asset and manifest patch names differ")

    design = design.without_reference_geometry()
    model = atomistic_model or build_atomistic_model(design, include_proteins=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    design_snapshot = output_dir / "design_snapshot.json"
    design_snapshot.write_text(design.model_dump_json(indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="nadoc_candidate_context_") as raw_tmp:
        tmpdir = Path(raw_tmp)
        segments, _input_pdb = _write_segment_pdbs(design, tmpdir, model)
        candidate_registry = {
            "products": [
                {
                    "id": product_id,
                    "product": registry_entry["product"],
                    "stereochemistry": registry_entry["stereochemistry"],
                    "assets": {
                        "topology": {
                            "path": lesion_topology.name,
                            "sha256": _sha256(lesion_topology),
                            "patch_name": patch_name,
                        }
                    },
                }
            ]
        }
        staged_topology = tmpdir / lesion_topology.name
        staged_topology.write_bytes(lesion_topology.read_bytes())
        patch_plan = photoproduct_patch_plan(
            design,
            model,
            segments,
            registry=candidate_registry,
            registry_root=tmpdir,
        )
        product_prefix = output_dir / "context_product"
        reactant_prefix = output_dir / "context_reactant"
        product_script = _context_psfgen_script(
            segments,
            product_prefix,
            extra_topologies=patch_plan["topology_paths"],
            photoproduct_patches=patch_plan["patches"],
        )
        reactant_script = _context_psfgen_script(segments, reactant_prefix)
        product_script_path = output_dir / "build_product.tcl"
        reactant_script_path = output_dir / "build_reactant.tcl"
        product_script_path.write_text(product_script)
        reactant_script_path.write_text(reactant_script)
        _run_psfgen(
            psfgen_path,
            reactant_script,
            tmpdir,
            output_dir / "psfgen_reactant.log",
        )
        _run_psfgen(
            psfgen_path,
            product_script,
            tmpdir,
            output_dir / "psfgen_product.log",
        )

    for stem in ("context_product", "context_reactant"):
        if (
            not (output_dir / f"{stem}.psf").is_file()
            or not (output_dir / f"{stem}.pdb").is_file()
        ):
            raise RuntimeError(f"psfgen did not emit the {stem} PSF/PDB pair")
    generic_audit = audit_psf(
        (output_dir / "context_product.psf").read_text(errors="replace"),
        require_dna_hydrogens=True,
        require_dna_residue_charge=True,
    )
    static_audit = audit_photoproduct_psf(
        product_psf_text=(output_dir / "context_product.psf").read_text(
            errors="replace"
        ),
        reactant_psf_text=(output_dir / "context_reactant.psf").read_text(
            errors="replace"
        ),
        patch_plan=patch_plan,
        topology_specs={product_id: json.loads(topology_spec_path.read_text())},
        charge_tolerance=2e-5,
    )
    audit_path = output_dir / "static_topology_audit.json"
    audit_path.write_text(json.dumps(static_audit, indent=2) + "\n")
    errors = list(generic_audit.errors) + list(static_audit["errors"])
    report = {
        "schema": "nadoc.photoproduct-candidate-context-topology.v1",
        "status": "passed_topology_only_not_safe_for_dynamics"
        if not errors
        else "failed",
        "passed": not errors,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "product": registry_entry["product"],
        "stereochemistry": registry_entry["stereochemistry"],
        "finished_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "context": {
            "lesion_id": lesions[0].id,
            "base_keys": [lesions[0].base_key_1, lesions[0].base_key_2],
            "strand_relationship": (
                "interstrand"
                if patch_plan["patches"][0]["endpoints"][0]["segid"]
                != patch_plan["patches"][0]["endpoints"][1]["segid"]
                else "intrastrand"
            ),
            "coordinates_product_fitted": coordinates_product_fitted,
        },
        "sources": {
            "design_snapshot": _source(design_snapshot),
            "candidate_manifest": _source(candidate_manifest_path),
            "candidate_topology": _source(lesion_topology),
            "topology_audit_spec": _source(topology_spec_path),
            "psfgen": _source(psfgen_path),
        },
        "outputs": {
            name: _source(output_dir / name)
            for name in (
                "context_product.psf",
                "context_product.pdb",
                "context_reactant.psf",
                "context_reactant.pdb",
                "build_product.tcl",
                "build_reactant.tcl",
                "psfgen_product.log",
                "psfgen_reactant.log",
                "static_topology_audit.json",
                "design_snapshot.json",
            )
        },
        "patch_plan": {
            **patch_plan,
            "topology_paths": [str(path) for path in patch_plan["topology_paths"]],
        },
        "generic_psf_audit": generic_audit.to_dict(),
        "static_topology_audit": static_audit,
        "errors": errors,
        "authorization": (
            "Topology identity and chemistry only. "
            + (
                "The supplied coordinates are a fitted candidate but this builder does "
                "not audit their local minimization; they must not be simulated."
                if coordinates_product_fitted
                else "The design coordinates have not passed product placement/minimization "
                "and must not be simulated."
            )
        ),
    }
    report_path = output_dir / "candidate_context_topology.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if errors:
        raise RuntimeError(
            "candidate context topology audit failed: " + "; ".join(errors)
        )
    return report


def _namd_binary_coordinates(path: Path, expected_atoms: int) -> np.ndarray:
    raw = path.read_bytes()
    if len(raw) != 4 + 24 * expected_atoms:
        raise ValueError("NAMD binary coordinate size does not match the PSF")
    count = struct.unpack("i", raw[:4])[0]
    if count != expected_atoms:
        raise ValueError("NAMD binary coordinate atom count does not match the PSF")
    coordinates = np.frombuffer(raw, dtype=np.float64, offset=4).reshape(count, 3)
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("NAMD binary coordinates contain non-finite values")
    return coordinates.copy()


def _pdb_coordinates(path: Path) -> np.ndarray:
    values = [
        [float(line[30:38]), float(line[38:46]), float(line[46:54])]
        for line in path.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    return np.asarray(values, dtype=float)


def _pdb_with_coordinates(path: Path, coordinates: np.ndarray) -> str:
    lines = []
    atom_index = 0
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            lines.append(line)
            continue
        if atom_index >= len(coordinates):
            raise ValueError("coordinate array is shorter than the PDB atom list")
        x, y, z = coordinates[atom_index]
        lines.append(f"{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}")
        atom_index += 1
    if atom_index != len(coordinates):
        raise ValueError("coordinate array is longer than the PDB atom list")
    return "\n".join(lines) + "\n"


def _local_constraint_pdb(
    source: Path,
    endpoints: list[dict[str, Any]],
    *,
    residue_radius: int,
    restraint_k: float,
) -> tuple[str, np.ndarray]:
    centers = {(item["segid"], int(item["resid"])) for item in endpoints}
    lines = []
    mobile = []
    for line in source.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            lines.append(line)
            continue
        segid = line[72:76].strip()
        resid = int(line[22:26])
        is_mobile = any(
            segid == center_segid and abs(resid - center_resid) <= residue_radius
            for center_segid, center_resid in centers
        )
        mobile.append(is_mobile)
        beta = 0.0 if is_mobile else restraint_k
        lines.append(f"{line[:60]}{beta:6.2f}{line[66:]}")
    return "\n".join(lines) + "\n", np.asarray(mobile, dtype=bool)


def _context_coordinate_audit(
    *,
    psf_path: Path,
    initial_pdb_path: Path,
    final_coordinates: np.ndarray,
    patch: dict[str, Any],
    definition: dict[str, Any],
    mobile: np.ndarray,
    policy: dict[str, Any],
) -> dict[str, Any]:
    from backend.parameterization.photoproduct_candidate_engine import (
        _minimum_nonbonded_heavy_ratio,
    )

    atoms = parse_psf_atoms(psf_path.read_text(errors="replace"))
    initial = _pdb_coordinates(initial_pdb_path)
    if len(initial) != len(atoms) or len(final_coordinates) != len(atoms):
        raise ValueError("context PDB/PSF/final coordinate counts differ")
    if len(mobile) != len(atoms):
        raise ValueError("context constraint mask does not match PSF atom count")
    endpoints = {item["endpoint"]: item for item in patch["endpoints"]}
    by_identity = {
        (atom.segid, atom.resid, atom.name): index for index, atom in enumerate(atoms)
    }

    def resolve(reference: str) -> int:
        endpoint_text, name = reference.split(":", 1)
        endpoint = endpoints[int(endpoint_text)]
        return by_identity[
            (endpoint["segid"], str(endpoint["resid"]), charmm_atom_name(name))
        ]

    chirality_references = {
        reference
        for center in definition["product_stereocenters"]
        for reference in [center["atom"], *center["signed_volume_reference_atoms"]]
    }
    chirality = audit_product_chirality(
        definition,
        {
            reference: final_coordinates[resolve(reference)].tolist()
            for reference in chirality_references
        },
    )

    def bond_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        minimum, maximum = policy["final_acceptance"][
            "product_ring_bond_range_angstrom"
        ]
        output = []
        for record in records:
            distance = float(
                np.linalg.norm(
                    final_coordinates[resolve(record["atom_1"])]
                    - final_coordinates[resolve(record["atom_2"])]
                )
            )
            output.append(
                {
                    "atom_1": record["atom_1"],
                    "atom_2": record["atom_2"],
                    "distance_angstrom": distance,
                    "passed": minimum <= distance <= maximum,
                }
            )
        return output

    ring_bonds = bond_records(
        [
            *definition["graph_delta"]["bonds_added"],
            *definition["graph_delta"]["bonds_retained"],
        ]
    )
    glycosidic_range = policy["final_acceptance"]["glycosidic_bond_range_angstrom"]
    glycosidic = []
    for endpoint in (1, 2):
        distance = float(
            np.linalg.norm(
                final_coordinates[resolve(f"{endpoint}:C1'")]
                - final_coordinates[resolve(f"{endpoint}:N1")]
            )
        )
        glycosidic.append(
            {
                "endpoint": endpoint,
                "distance_angstrom": distance,
                "passed": glycosidic_range[0] <= distance <= glycosidic_range[1],
            }
        )
    bonds = [
        (first - 1, second - 1)
        for first, second in parse_psf_index_section(
            psf_path.read_text(errors="replace"), "!NBOND", 2
        )
    ]
    selected_residues = {
        (item["segid"], str(item["resid"])) for item in patch["endpoints"]
    }
    flank_range = policy["final_acceptance"]["selected_to_flank_bond_range_angstrom"]
    flank_bonds = []
    for first, second in bonds:
        first_selected = (atoms[first].segid, atoms[first].resid) in selected_residues
        second_selected = (
            atoms[second].segid,
            atoms[second].resid,
        ) in selected_residues
        if first_selected == second_selected:
            continue
        distance = float(
            np.linalg.norm(final_coordinates[first] - final_coordinates[second])
        )
        flank_bonds.append(
            {
                "atom_1": list(atoms[first].identity),
                "atom_2": list(atoms[second].identity),
                "distance_angstrom": distance,
                "passed": flank_range[0] <= distance <= flank_range[1],
            }
        )
    neighbors: dict[int, set[int]] = {}
    excluded = {frozenset(pair) for pair in bonds}
    for first, second in bonds:
        neighbors.setdefault(first, set()).add(second)
        neighbors.setdefault(second, set()).add(first)
    for attached in neighbors.values():
        for first in attached:
            for second in attached:
                if first != second:
                    excluded.add(frozenset((first, second)))
    radii = {"C": 0.76, "N": 0.71, "O": 0.66, "P": 1.07}
    masses = {"C": 12.011, "N": 14.007, "O": 15.999, "P": 30.974}

    def element(index: int) -> str | None:
        if atoms[index].mass < 5:
            return None
        return min(radii, key=lambda key: abs(atoms[index].mass - masses[key]))

    heavy = [index for index in range(len(atoms)) if element(index) is not None]
    atom_radii = {index: radii[element(index)] for index in heavy}
    nonbonded_ratio, closest_pair = _minimum_nonbonded_heavy_ratio(
        final_coordinates, heavy, atom_radii, excluded, None
    )
    displacement = np.linalg.norm(final_coordinates - initial, axis=1)
    fixed = ~mobile
    fixed_maximum = float(np.max(displacement[fixed])) if np.any(fixed) else 0.0
    fixed_rmsd = (
        float(np.sqrt(np.mean(displacement[fixed] ** 2))) if np.any(fixed) else 0.0
    )
    acceptance = policy["final_acceptance"]
    errors = []
    if not chirality["passed"]:
        errors.append("registered product chirality was not retained")
    if not all(item["passed"] for item in ring_bonds):
        errors.append("one or more product ring bonds is outside its safety range")
    if not all(item["passed"] for item in glycosidic):
        errors.append("one or more glycosidic bonds is outside its safety range")
    if not flank_bonds or not all(item["passed"] for item in flank_bonds):
        errors.append("one or more selected-to-flank bonds is outside its safety range")
    if nonbonded_ratio < acceptance["minimum_nonbonded_covalent_radius_ratio"]:
        errors.append("a nonbonded heavy-atom contact failed the safety ratio")
    if fixed_maximum > acceptance["maximum_nonlocal_displacement_angstrom"]:
        errors.append("maximum nonlocal displacement exceeds the policy")
    if fixed_rmsd > acceptance["maximum_nonlocal_rmsd_angstrom"]:
        errors.append("nonlocal RMS displacement exceeds the policy")
    return {
        "passed": not errors,
        "chirality": chirality,
        "ring_bonds": ring_bonds,
        "glycosidic_bonds": glycosidic,
        "selected_to_flank_bonds": flank_bonds,
        "nonbonded": {
            "minimum_covalent_radius_ratio": nonbonded_ratio,
            "closest_pair": (
                [list(atoms[index].identity) for index in closest_pair]
                if closest_pair is not None
                else None
            ),
        },
        "displacement": {
            "maximum_nonlocal_angstrom": fixed_maximum,
            "nonlocal_rmsd_angstrom": fixed_rmsd,
            "maximum_mobile_angstrom": float(np.max(displacement[mobile])),
        },
        "errors": errors,
    }


def _checked_source(record: object, label: str) -> Path:
    if not isinstance(record, dict) or not record.get("path"):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record["path"])).resolve()
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path


def _candidate_coordinate_template(
    *,
    boundary: dict[str, Any],
    qm_release: dict[str, Any],
    parameter_sha256: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Create a non-released placement template from audited full-boundary QM data."""

    atom_map = boundary.get("atom_map")
    if (
        not isinstance(atom_map, list)
        or len(atom_map) != 63
        or len(set(atom_map)) != 63
    ):
        raise ValueError("boundary stable atom map must contain 63 unique atoms")
    xyz_path = _checked_source(
        (boundary.get("outputs") or {}).get("xyz"), "boundary XYZ"
    )
    map_path = _checked_source(
        (boundary.get("outputs") or {}).get("atom_map"), "boundary atom map"
    )
    if json.loads(map_path.read_text()) != atom_map:
        raise ValueError("boundary manifest and atom-map asset differ")
    optimized_xyz = _checked_source(
        (qm_release.get("sources") or {}).get("optimized_xyz"), "released optimized XYZ"
    )
    optimization_audit = _checked_source(
        (qm_release.get("sources") or {}).get("optimization_audit"),
        "optimization audit",
    )
    frequency_audit = _checked_source(
        (qm_release.get("sources") or {}).get("frequency_audit"), "frequency audit"
    )
    optimization = json.loads(optimization_audit.read_text())
    frequency = json.loads(frequency_audit.read_text())
    if (
        optimization.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or optimization.get("status") != "passed_identity_and_chirality"
        or optimization.get("product_id") != qm_release.get("product_id")
        or (optimization.get("chirality_audit") or {}).get("passed") is not True
        or frequency.get("schema") != "nadoc.photoproduct-frequency-audit.v1"
        or frequency.get("status") != "passed_harmonic_minimum"
        or frequency.get("product_id") != qm_release.get("product_id")
        or frequency.get("imaginary_mode_count") != 0
    ):
        raise ValueError("QM template audits do not prove the matching chiral minimum")
    if _sha256(xyz_path) != _sha256(optimized_xyz):
        raise ValueError(
            "screened boundary coordinates differ from the QM-released minimum"
        )
    from backend.parameterization.photoproduct_candidate_engine import _parse_xyz

    _elements, coordinates = _parse_xyz(xyz_path, atom_map)
    coordinate_map = {
        key: [float(value) for value in xyz]
        for key, xyz in zip(atom_map, coordinates, strict=True)
    }
    needed = {
        f"{endpoint}:{name}"
        for endpoint in (1, 2)
        for name in ("C1'", "N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7", "H6")
    }
    missing = sorted(needed - set(coordinate_map))
    if missing:
        raise ValueError(
            "boundary template lacks placement atoms: " + ", ".join(missing)
        )
    minimum, maximum = policy["final_acceptance"]["product_ring_bond_range_angstrom"]
    definition = load_chemical_definition(
        str(qm_release["product"]), str(qm_release["stereochemistry"])
    )
    return {
        "schema": "nadoc.photoproduct-coordinate-template.v1",
        "version": "candidate-full-boundary-precondition-v1",
        "product_id": qm_release["product_id"],
        "units": "angstrom",
        "reflection_allowed": False,
        "release_status": "candidate_validation_only",
        "coordinates": coordinate_map,
        "provenance": {
            "optimized_xyz_sha256": _sha256(optimized_xyz),
            "optimized_model_audit_sha256": _sha256(optimization_audit),
            "frequency_audit_sha256": _sha256(frequency_audit),
        },
        "placement_safety": {
            "schema": "nadoc.photoproduct-placement-safety.v1",
            "parameter_asset_sha256": parameter_sha256,
            "product_ring_bond_ranges_angstrom": [
                {
                    "atom_1": bond["atom_1"],
                    "atom_2": bond["atom_2"],
                    "minimum_angstrom": minimum,
                    "maximum_angstrom": maximum,
                    "authority": "preregistered candidate context precondition policy v1",
                }
                for category in ("bonds_added", "bonds_retained")
                for bond in definition["graph_delta"][category]
            ],
        },
    }


def run_candidate_context_precondition(
    *,
    design: Design,
    candidate_manifest_path: Path,
    boundary_manifest_path: Path,
    qm_release_report_path: Path,
    nucleic_parameters_path: Path,
    psfgen_path: Path,
    namd_path: Path,
    policy_path: Path,
    output_dir: Path,
    storage_root: Path,
) -> dict[str, Any]:
    """Place and locally minimize one candidate in a stable-key NADOC context."""

    from backend.parameterization.photoproduct_candidate_engine import (
        _energy_audit,
        _namd_config,
        _run_engine,
    )

    output_dir = _require_under(output_dir, storage_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite context precondition: {output_dir}"
        )
    for path, label in (
        (candidate_manifest_path, "candidate manifest"),
        (boundary_manifest_path, "boundary manifest"),
        (qm_release_report_path, "QM release report"),
        (nucleic_parameters_path, "nucleic parameters"),
        (psfgen_path, "psfgen"),
        (namd_path, "NAMD"),
        (policy_path, "precondition policy"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is unavailable: {path}")
    policy = json.loads(policy_path.read_text())
    if (
        policy.get("schema") != "nadoc.photoproduct-context-precondition-policy.v1"
        or policy.get("version") != "1.0.0"
        or policy.get("gate_effect") != "none"
    ):
        raise ValueError("unsupported context precondition policy")
    candidate = json.loads(candidate_manifest_path.read_text())
    boundary = json.loads(boundary_manifest_path.read_text())
    qm_release = json.loads(qm_release_report_path.read_text())
    product_id = candidate.get("product_id")
    boundary_is_screened = (
        boundary.get("schema") == "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        and boundary.get("status") == "quantitatively_screened_boundary"
        and boundary.get("formal_charge") == -1
        and (boundary.get("chirality_audit") or {}).get("passed") is True
    )
    boundary_is_optimized = (
        boundary.get("schema") == "nadoc.photoproduct-model-compound.v1"
        and boundary.get("status") == "optimized_full_boundary_fit_input"
        and boundary.get("charge") == -1
    )
    if boundary_is_optimized and (
        ((boundary.get("sources") or {}).get("optimization_audit") or {}).get("sha256")
        != ((qm_release.get("sources") or {}).get("optimization_audit") or {}).get(
            "sha256"
        )
    ):
        raise ValueError("optimized boundary model and QM release audit lineage differ")
    if (
        candidate.get("schema") != "nadoc.photoproduct-charmm-candidate.v1"
        or candidate.get("gate_effect") != "none"
        or not (boundary_is_screened or boundary_is_optimized)
        or boundary.get("product_id") != product_id
        or boundary.get("atom_count") != 63
        or qm_release.get("schema")
        != "nadoc.photoproduct-qm-reference-release-audit.v1"
        or qm_release.get("status") != "passed"
        or qm_release.get("passed") is not True
        or qm_release.get("simulation_ready") is not False
        or qm_release.get("product_id") != product_id
    ):
        raise ValueError(
            "candidate, boundary model, and QM release identities do not match"
        )
    parameters = _candidate_asset(candidate_manifest_path, candidate, "parameters")
    template = _candidate_coordinate_template(
        boundary=boundary,
        qm_release=qm_release,
        parameter_sha256=_sha256(parameters),
        policy=policy,
    )
    definition = load_chemical_definition(
        str(qm_release["product"]), str(qm_release["stereochemistry"])
    )
    lesions = list(design.photoproduct_junctions)
    if (
        len(lesions) != 1
        or lesions[0].product != qm_release["product"]
        or (lesions[0].stereochemistry != qm_release["stereochemistry"])
    ):
        raise ValueError("context design does not contain the matching single lesion")
    clean_design = design.without_reference_geometry()
    model = build_atomistic_model(clean_design, include_proteins=True)
    endpoints, resolution_errors = resolve_base_keys(
        clean_design,
        [lesions[0].base_key_1, lesions[0].base_key_2],
        atomistic_model=model,
    )
    if resolution_errors or len(endpoints) != 2:
        raise ValueError(
            "context lesion endpoints do not resolve: " + json.dumps(resolution_errors)
        )
    seed = policy["placement_seed"]
    placed_model, placement = place_product_template(
        atomistic_model=model,
        endpoints=endpoints,
        template=template,
        chemical_definition=definition,
        expected_parameter_sha256=_sha256(parameters),
        max_anchor_rmsd_nm=float(seed["maximum_anchor_rmsd_angstrom"]) / 10.0,
        max_glycosidic_error_nm=float(seed["maximum_glycosidic_error_angstrom"]) / 10.0,
        max_base_displacement_nm=float(seed["maximum_base_displacement_angstrom"])
        / 10.0,
        minimum_clash_ratio=float(seed["minimum_nonbonded_vdw_ratio"]),
        allowed_template_statuses=frozenset({"candidate_validation_only"}),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    placement_path = output_dir / "placement_seed_audit.json"
    placement_path.write_text(json.dumps(placement, indent=2) + "\n")
    topology_dir = output_dir / "topology"
    topology = build_candidate_context_topology(
        design=clean_design,
        candidate_manifest_path=candidate_manifest_path,
        psfgen_path=psfgen_path,
        output_dir=topology_dir,
        storage_root=storage_root,
        atomistic_model=placed_model,
        coordinates_product_fitted=True,
    )
    patch = topology["patch_plan"]["patches"][0]
    local = policy["local_minimization"]
    constraints_text, mobile = _local_constraint_pdb(
        topology_dir / "context_product.pdb",
        patch["endpoints"],
        residue_radius=int(local["mobile_residue_radius"]),
        restraint_k=float(local["nonlocal_harmonic_k_kcal_mol_angstrom2"]),
    )
    constraints_path = output_dir / "local_constraints.pdb"
    constraints_path.write_text(constraints_text)
    steps = int(local["steps"])
    output_stem = output_dir / "local_minimized"
    config = _namd_config(
        topology_psf=topology_dir / "context_product.psf",
        starting_coordinates=topology_dir / "context_product.pdb",
        nucleic_parameters=nucleic_parameters_path.resolve(),
        lesion_parameters=parameters,
        output_stem=output_stem,
        action="minimize",
        steps=steps,
    )
    constraint_block = "\n".join(
        (
            "constraints on",
            f"consref {constraints_path}",
            f"conskfile {constraints_path}",
            "conskcol B",
        )
    )
    config = config.replace(
        f"minimize {steps}", f"{constraint_block}\nminimize {steps}"
    )
    config_path = output_dir / "local_minimize.namd"
    config_path.write_text(config)
    engine = _run_engine(
        [str(namd_path.resolve()), "+p1", str(config_path)],
        cwd=output_dir,
        stdin=None,
        log_path=output_dir / "local_minimize.log",
    )
    energy = _energy_audit(output_dir / "local_minimize.log")
    if (
        not engine["passed"]
        or not engine["successful_end_marker"]
        or not energy["all_finite"]
    ):
        raise RuntimeError("candidate context local minimization failed engine audit")
    final_coor = output_stem.with_suffix(".coor")
    coordinates = _namd_binary_coordinates(final_coor, len(mobile))
    final_pdb = output_dir / "local_minimized.pdb"
    final_pdb.write_text(
        _pdb_with_coordinates(topology_dir / "context_product.pdb", coordinates)
    )
    coordinate_audit = _context_coordinate_audit(
        psf_path=topology_dir / "context_product.psf",
        initial_pdb_path=topology_dir / "context_product.pdb",
        final_coordinates=coordinates,
        patch=patch,
        definition=definition,
        mobile=mobile,
        policy=policy,
    )
    coordinate_audit_path = output_dir / "final_coordinate_audit.json"
    coordinate_audit_path.write_text(json.dumps(coordinate_audit, indent=2) + "\n")
    errors = list(coordinate_audit["errors"])
    report = {
        "schema": "nadoc.photoproduct-candidate-context-precondition.v1",
        "status": "passed_candidate_coordinate_seed" if not errors else "failed",
        "passed": not errors,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "product": qm_release["product"],
        "stereochemistry": qm_release["stereochemistry"],
        "finished_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "context": topology["context"],
        "placement_seed": placement,
        "topology_audit": {
            "report": _source(topology_dir / "candidate_context_topology.json"),
            "passed": topology["passed"],
        },
        "local_minimization": {"engine": engine, "energy": energy, "steps": steps},
        "final_coordinate_audit": coordinate_audit,
        "sources": {
            "candidate_manifest": _source(candidate_manifest_path),
            "boundary_manifest": _source(boundary_manifest_path),
            "qm_release_report": _source(qm_release_report_path),
            "nucleic_parameters": _source(nucleic_parameters_path),
            "lesion_parameters": _source(parameters),
            "precondition_policy": _source(policy_path),
            "psfgen": _source(psfgen_path),
            "namd": _source(namd_path),
        },
        "outputs": {
            "placement_seed_audit": _source(placement_path),
            "constraints": _source(constraints_path),
            "namd_config": _source(config_path),
            "namd_log": _source(output_dir / "local_minimize.log"),
            "final_coordinates": _source(final_coor),
            "final_pdb": _source(final_pdb),
            "coordinate_audit": _source(coordinate_audit_path),
        },
        "errors": errors,
        "authorization": (
            "Candidate coordinate seed for controlled explicit-solvent validation only; "
            "this report cannot open a production force-field or NAMD packaging gate."
        ),
    }
    report_path = output_dir / "candidate_context_precondition.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if errors:
        raise RuntimeError(
            "candidate context coordinate audit failed: " + "; ".join(errors)
        )
    return report


def run_candidate_context_solution_smoke(
    *,
    candidate_manifest_path: Path,
    precondition_report_path: Path,
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
    heat_steps: int = 5000,
    dynamics_steps: int = 5000,
) -> dict[str, Any]:
    """Run a short explicit-solvent smoke from an audited context precondition."""

    from backend.core.namd_solvate import (
        _build_solvated_pdb,
        _extend_psf,
        _find_gmx,
        _find_last_atom_serial,
        _gmx_solvate,
        _place_ions_mixed,
        ion_counts,
    )
    from backend.parameterization.photoproduct_candidate_engine import (
        _energy_audit,
        _run_engine,
        _solution_namd_config,
        _trajectory_audit,
    )

    output_dir = _require_under(output_dir, storage_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"refusing to overwrite context solution smoke: {output_dir}"
        )
    if (
        padding_nm < 0.8
        or ion_conc_mM < 0
        or min(minimize_steps, heat_steps, dynamics_steps) < 100
        or dynamics_steps % 100
    ):
        raise ValueError("invalid context solution protocol settings")
    for path, label in (
        (candidate_manifest_path, "candidate manifest"),
        (precondition_report_path, "context precondition report"),
        (nucleic_parameters_path, "nucleic parameters"),
        (water_parameters_path, "water parameters"),
        (ion_nbfix_parameters_path, "ion NBFIX parameters"),
        (namd_path, "NAMD"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is unavailable: {path}")
    candidate = json.loads(candidate_manifest_path.read_text())
    precondition = json.loads(precondition_report_path.read_text())
    expected_candidate = (precondition.get("sources") or {}).get(
        "candidate_manifest"
    ) or {}
    if (
        candidate.get("schema") != "nadoc.photoproduct-charmm-candidate.v1"
        or candidate.get("gate_effect") != "none"
        or precondition.get("schema")
        != "nadoc.photoproduct-candidate-context-precondition.v1"
        or precondition.get("passed") is not True
        or precondition.get("simulation_ready") is not False
        or precondition.get("gate_effect") != "none"
        or precondition.get("product_id") != candidate.get("product_id")
        or expected_candidate.get("sha256") != _sha256(candidate_manifest_path)
    ):
        raise ValueError("context solution requires its matching passed precondition")
    topology_report_path = _checked_source(
        (precondition.get("topology_audit") or {}).get("report"),
        "context topology report",
    )
    topology = json.loads(topology_report_path.read_text())
    if (
        topology.get("schema") != "nadoc.photoproduct-candidate-context-topology.v1"
        or topology.get("passed") is not True
        or topology.get("product_id") != candidate.get("product_id")
        or not (topology.get("context") or {}).get("coordinates_product_fitted")
    ):
        raise ValueError("context topology lineage is not a fitted passed candidate")
    product_psf = _checked_source(
        (topology.get("outputs") or {}).get("context_product.psf"),
        "context product PSF",
    )
    product_pdb = _checked_source(
        (precondition.get("outputs") or {}).get("final_pdb"),
        "preconditioned product PDB",
    )
    endpoints = (
        (topology.get("patch_plan") or {}).get("patches", [{}])[0].get("endpoints")
    )
    if not isinstance(endpoints, list) or len(endpoints) != 2:
        raise ValueError("context topology has no exact two-endpoint patch plan")
    lesion_parameters = _candidate_asset(
        candidate_manifest_path, candidate, "parameters"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    gmx_path = Path(_find_gmx()).resolve()
    with tempfile.TemporaryDirectory(prefix="nadoc_context_solution_") as raw_tmp:
        waters, box_nm, recentered_pdb = _gmx_solvate(
            product_pdb.read_text(errors="replace"),
            padding_nm,
            Path(raw_tmp),
            box_mode="bbox",
        )
    solute_psf_text = product_psf.read_text(errors="replace")
    solute_charge = float(audit_psf(solute_psf_text).total_charge)
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
    base_serial = _find_last_atom_serial(solute_psf_text)
    solvated_psf_text = _extend_psf(
        solute_psf_text,
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
        raise RuntimeError("context solvated topology audit failed")

    (output_dir / "output").mkdir()
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
            raise RuntimeError(f"NAMD context solution stage {name} failed")
    dcd_path = output_dir / "output/03_dynamics_2fs.dcd"
    trajectory = _trajectory_audit(
        solvated_psf,
        dcd_path,
        product=str(precondition["product"]),
        stereochemistry=str(precondition["stereochemistry"]),
        endpoints=endpoints,
    )
    errors = [error for run in engine_runs for error in run["errors"]]
    errors.extend(trajectory["errors"])
    report = {
        "schema": "nadoc.photoproduct-candidate-context-solution-smoke.v1",
        "status": "passed_context_solution_smoke_not_released"
        if not errors
        else "failed",
        "passed": not errors,
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": candidate["product_id"],
        "product": precondition["product"],
        "stereochemistry": precondition["stereochemistry"],
        "context": precondition["context"],
        "finished_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
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
            "precondition_report": _source(precondition_report_path),
            "context_product_psf": _source(product_psf),
            "preconditioned_product_pdb": _source(product_pdb),
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
            "Short explicit-solvent candidate context smoke only; this cannot release "
            "parameters, prove equilibrium stability, or authorize production packaging."
        ),
    }
    report_path = output_dir / "candidate_context_solution_smoke.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
