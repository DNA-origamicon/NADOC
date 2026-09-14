"""Build an explicitly incomplete OpenMM model from audited CHARMM candidates."""

from __future__ import annotations

from collections import deque
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.parameterization.charmm_reference import REFERENCE_MANIFEST_PATH
from backend.parameterization.photoproduct_nonbonded_fit import parse_charmm_nonbonded
from backend.parameterization.photoproduct_parameter_coverage import (
    match_charmm_parameter,
    parse_charmm_bonded_parameters,
)
from backend.parameterization.photoproduct_qm import parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_pinned_cgenff_inputs(
    topology_path: Path,
    parameters_path: Path,
    *,
    reference_manifest_path: Path | None = None,
) -> dict[str, str]:
    """Fail closed unless both CGenFF inputs match the pinned reference release."""

    manifest_path = reference_manifest_path or REFERENCE_MANIFEST_PATH
    references = json.loads(manifest_path.read_text())
    reference = references.get("cgenff_reference_library") or {}
    expected_topology = reference.get("topology_sha256")
    expected_parameters = reference.get("parameters_sha256")
    if not expected_topology or not expected_parameters:
        raise ValueError(
            "reference manifest lacks pinned CGenFF topology/parameter hashes"
        )
    actual = {
        "topology_sha256": _sha256(topology_path),
        "parameters_sha256": _sha256(parameters_path),
    }
    if actual["topology_sha256"] != expected_topology:
        raise ValueError(
            "CGenFF topology differs from the pinned reference release: "
            f"expected {expected_topology}, found {actual['topology_sha256']}"
        )
    if actual["parameters_sha256"] != expected_parameters:
        raise ValueError(
            "CGenFF parameters differ from the pinned reference release: "
            f"expected {expected_parameters}, found {actual['parameters_sha256']}"
        )
    return actual


def parse_charmm_masses(topology_path: Path) -> dict[str, dict[str, Any]]:
    """Parse type masses/elements from a CHARMM topology file."""

    result = {}
    for raw in topology_path.read_text(errors="replace").splitlines():
        fields = raw.split("!", 1)[0].split()
        if len(fields) < 4 or fields[0].upper() != "MASS":
            continue
        try:
            mass = float(fields[3])
        except ValueError:
            continue
        atom_type = fields[2]
        element = fields[4].title() if len(fields) >= 5 else None
        result[atom_type] = {"mass_amu": mass, "element": element}
    if not result:
        raise ValueError(f"no CHARMM MASS records parsed from {topology_path}")
    return result


def _unique_values(matches: list[dict[str, Any]], label: str) -> list[float]:
    values = {tuple(float(value) for value in item["values"]) for item in matches}
    if not values:
        raise ValueError(f"{label}: covered term has no parameter match")
    if len(values) != 1:
        raise ValueError(f"{label}: covered term has ambiguous parameter values")
    return list(next(iter(values)))


def _canonical_atom_path(atoms: list[str]) -> tuple[str, ...]:
    forward = tuple(atoms)
    reverse = tuple(reversed(atoms))
    return min(forward, reverse)


def parse_charmm_residue_impropers(
    topology_path: Path, residue_name: str
) -> list[list[str]]:
    """Return ordered ``IMPR`` atom names from one CHARMM residue definition."""

    in_residue = False
    impropers: list[list[str]] = []
    for raw in topology_path.read_text(errors="replace").splitlines():
        fields = raw.split("!", 1)[0].split()
        if not fields:
            continue
        keyword = fields[0].upper()
        if keyword in {"RESI", "PRES"}:
            in_residue = (
                keyword == "RESI"
                and len(fields) >= 2
                and fields[1].upper() == residue_name.upper()
            )
            continue
        if in_residue and keyword in {"IMPR", "IMPH"}:
            atoms = fields[1:]
            if not atoms or len(atoms) % 4:
                raise ValueError(
                    f"{topology_path}: malformed {residue_name} {keyword} record"
                )
            impropers.extend(
                [atoms[position : position + 4] for position in range(0, len(atoms), 4)]
            )
    if not impropers:
        raise ValueError(
            f"{topology_path}: residue {residue_name} has no improper definitions"
        )
    return impropers


def retained_thymine_impropers(
    *,
    topology_path: Path,
    parameter_paths: list[Path],
    atom_types: dict[str, str],
    removed_impropers: list[list[str]],
) -> list[dict[str, Any]]:
    """Resolve unchanged THY planar impropers for both product endpoints.

    The N-methyl fitting graph calls the native thymine methyl carbon ``C7`` while
    CHARMM36 calls it ``C5M``.  Only topology-declared THY impropers are considered,
    and the exact precursor records replaced by product stereochemical impropers are
    removed by stable atom identity before parameter lookup.
    """

    records = [
        record
        for path in parameter_paths
        for record in parse_charmm_bonded_parameters(path)
    ]
    removed = {tuple(atoms) for atoms in removed_impropers}
    result = []
    for endpoint in (1, 2):
        for local_atoms in parse_charmm_residue_impropers(topology_path, "THY"):
            normalized = ["C7" if atom == "C5M" else atom for atom in local_atoms]
            atoms = [f"{endpoint}:{atom}" for atom in normalized]
            if tuple(atoms) in removed:
                continue
            if any(atom not in atom_types for atom in atoms):
                # Boundary-only sugar impropers, if introduced by a future CHARMM
                # release, are outside the N-methyl model rather than silently guessed.
                continue
            types = [atom_types[atom] for atom in atoms]
            matches = match_charmm_parameter(records, "impropers", types)
            values = _unique_values(matches, "-".join(atoms))
            if len(values) < 3:
                raise ValueError(
                    f"retained CHARMM improper {'-'.join(atoms)} is incomplete"
                )
            result.append(
                {
                    "atoms": atoms,
                    "types": types,
                    "k_kcal_mol_rad2": float(values[0]),
                    "psi0_degrees": float(values[2]),
                    "matches": matches,
                }
            )
    if len(result) != 4:
        raise ValueError(
            "expected exactly four retained planar THY impropers in the two-base model; "
            f"found {len(result)}"
        )
    return result


def _graph_distances(
    atom_keys: list[str], graph_bonds: list[dict[str, Any]]
) -> dict[tuple[int, int], int]:
    index = {key: position for position, key in enumerate(atom_keys)}
    adjacency = {position: set() for position in range(len(atom_keys))}
    for record in graph_bonds:
        first, second = (index[key] for key in record["atoms"])
        adjacency[first].add(second)
        adjacency[second].add(first)
    distances = {}
    for start in range(len(atom_keys)):
        pending = deque([(start, 0)])
        visited = {start}
        while pending:
            current, distance = pending.popleft()
            if distance == 3:
                continue
            for neighbor in adjacency[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_distance = distance + 1
                if start < neighbor:
                    distances[(start, neighbor)] = next_distance
                pending.append((neighbor, next_distance))
    return distances


def build_openmm_candidate_skeleton(
    *,
    fit_plan_path: Path,
    nonbonded_fit_path: Path,
    cgenff_topology_path: Path,
    cgenff_parameters_path: Path,
    nucleic_topology_path: Path | None = None,
    nucleic_parameters_path: Path | None = None,
    output_dir: Path,
) -> dict[str, Any]:
    """Serialize a finite but intentionally incomplete candidate evaluation system.

    Covered CHARMM terms and unchanged THY planar impropers are included verbatim.
    Missing bonded terms and every product-specific improper are omitted and enumerated
    in the manifest. The output is never a simulation topology or a release candidate.
    """

    try:
        import openmm
        from openmm import app, unit
    except ImportError as exc:
        raise RuntimeError(
            "OpenMM is required in the photoproduct QM environment"
        ) from exc
    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite OpenMM candidate skeleton: {output_dir}"
        )
    fit_plan = json.loads(fit_plan_path.read_text())
    nonbonded_fit = json.loads(nonbonded_fit_path.read_text())
    cgenff_hashes = assert_pinned_cgenff_inputs(
        cgenff_topology_path, cgenff_parameters_path
    )
    if (nucleic_topology_path is None) != (nucleic_parameters_path is None):
        raise ValueError("nucleic topology and parameters must be provided together")
    if (
        fit_plan.get("schema") != "nadoc.photoproduct-bonded-fit-plan.v1"
        or fit_plan.get("status") != "candidate_plan_unassigned_not_releasable"
        or fit_plan.get("gate_effect") != "none"
        or nonbonded_fit.get("schema")
        != "nadoc.photoproduct-nonbonded-hypothesis-fit.v1"
    ):
        raise ValueError(
            "bonded fit plan or nonbonded fit is not a gate-neutral candidate"
        )
    for group in fit_plan.get("uncovered_parameter_groups") or []:
        variables = group.get("variables") or {}
        if not variables or any(value is not None for value in variables.values()):
            raise ValueError(
                "fit plan contains assigned or malformed missing-term values"
            )
    hypothesis_id = fit_plan["hypothesis_id"]
    hypothesis = next(
        (
            item
            for item in nonbonded_fit.get("results") or []
            if item.get("hypothesis_id") == hypothesis_id
        ),
        None,
    )
    if (
        hypothesis is None
        or nonbonded_fit.get("product_id") != fit_plan.get("product_id")
        or nonbonded_fit.get("model_id") != fit_plan.get("model_id")
    ):
        raise ValueError("nonbonded fit lacks the selected matching hypothesis")

    sources = fit_plan.get("sources") or {}
    coverage_record = sources.get("model_coverage") or {}
    graph_record = sources.get("model_graph") or {}
    targets_record = sources.get("hessian_targets") or {}
    coverage_path = Path(str(coverage_record.get("path") or ""))
    graph_path = Path(str(graph_record.get("path") or ""))
    targets_path = Path(str(targets_record.get("path") or ""))
    for path, record, label in (
        (coverage_path, coverage_record, "model coverage"),
        (graph_path, graph_record, "model graph"),
        (targets_path, targets_record, "Hessian targets"),
    ):
        if not path.is_file() or _sha256(path) != record.get("sha256"):
            raise ValueError(f"{label} is missing or hash-mismatched")
    coverage = json.loads(coverage_path.read_text())
    graph = json.loads(graph_path.read_text())
    targets = json.loads(targets_path.read_text())
    coverage_fit_record = (coverage.get("sources") or {}).get("nonbonded_fit") or {}
    if (
        coverage.get("hypothesis_id") != hypothesis_id
        or coverage_fit_record.get("sha256") != _sha256(nonbonded_fit_path)
        or ((coverage.get("sources") or {}).get("cgenff_parameters") or {}).get(
            "sha256"
        )
        != _sha256(cgenff_parameters_path)
    ):
        raise ValueError(
            "coverage is not linked to the selected fit and parameter file"
        )

    nucleic_hashes = None
    if nucleic_topology_path is not None and nucleic_parameters_path is not None:
        references = json.loads(REFERENCE_MANIFEST_PATH.read_text())
        nucleic_hashes = {
            "topology_sha256": _sha256(nucleic_topology_path),
            "parameters_sha256": _sha256(nucleic_parameters_path),
        }
        expected = references["base_forcefield"]
        if (
            nucleic_hashes["topology_sha256"] != expected["topology"]["sha256"]
            or nucleic_hashes["parameters_sha256"] != expected["parameters"]["sha256"]
            or ((coverage.get("sources") or {}).get("nucleic_parameters") or {}).get(
                "sha256"
            )
            != nucleic_hashes["parameters_sha256"]
        ):
            raise ValueError(
                "nucleic topology/parameters differ from the pinned coverage release"
            )

    atom_records = graph.get("atoms") or []
    atom_keys = [item["key"] for item in atom_records]
    graph_bonds = graph.get("bonds") or []
    types = hypothesis.get("atom_types") or {}
    charges = hypothesis.get("charges_e") or {}
    if set(types) != set(atom_keys) or set(charges) != set(atom_keys):
        raise ValueError(
            "type/charge hypothesis does not exactly cover the model graph"
        )
    if not math.isclose(
        sum(float(charges[key]) for key in atom_keys),
        float(graph["formal_charge"]),
        abs_tol=1e-8,
    ):
        raise ValueError("candidate charges do not conserve the model charge")
    masses = parse_charmm_masses(cgenff_topology_path)
    nonbonded = parse_charmm_nonbonded(cgenff_parameters_path)
    if nucleic_topology_path is not None and nucleic_parameters_path is not None:
        masses.update(parse_charmm_masses(nucleic_topology_path))
        nucleic_nonbonded = parse_charmm_nonbonded(nucleic_parameters_path)
        conflicts = {
            key
            for key in set(nonbonded) & set(nucleic_nonbonded)
            if nonbonded[key] != nucleic_nonbonded[key]
        }
        if conflicts:
            raise ValueError(
                "CGenFF and nucleic-acid NONBONDED records conflict: "
                + ", ".join(sorted(conflicts))
            )
        nonbonded.update(nucleic_nonbonded)
    missing_types = sorted(set(types.values()) - set(masses))
    missing_lj = sorted(set(types.values()) - set(nonbonded))
    if missing_types or missing_lj:
        raise ValueError(
            "candidate atom types lack mass or nonbonded records: "
            + ", ".join(sorted(set(missing_types + missing_lj)))
        )

    geometry_record = targets.get("source_geometry") or {}
    geometry_path = Path(str(geometry_record.get("path") or ""))
    if not geometry_path.is_file() or _sha256(geometry_path) != geometry_record.get(
        "sha256"
    ):
        raise ValueError("optimized model geometry is missing or hash-mismatched")
    xyz_atoms, _comment = parse_xyz(geometry_path.read_text())
    if [item[0] for item in xyz_atoms] != [item["element"] for item in atom_records]:
        raise ValueError("geometry elements differ from the model graph")
    xyz_angstrom = np.asarray([item[1:] for item in xyz_atoms], dtype=float)
    index = {key: position for position, key in enumerate(atom_keys)}
    retained_impropers = []
    if nucleic_topology_path is not None and nucleic_parameters_path is not None:
        retained_impropers = retained_thymine_impropers(
            topology_path=nucleic_topology_path,
            parameter_paths=[cgenff_parameters_path, nucleic_parameters_path],
            atom_types=types,
            removed_impropers=fit_plan.get(
                "precursor_improper_removal_candidates"
            )
            or [],
        )

    system = openmm.System()
    for key in atom_keys:
        system.addParticle(float(masses[types[key]]["mass_amu"]) * unit.dalton)
    bond_force = openmm.HarmonicBondForce()
    angle_force = openmm.HarmonicAngleForce()
    urey_bradley_force = openmm.HarmonicBondForce()
    torsion_force = openmm.PeriodicTorsionForce()
    retained_improper_force = openmm.CustomTorsionForce(
        "k*delta^2;"
        "delta=atan2(sin(theta-theta0),cos(theta-theta0))"
    )
    retained_improper_force.addPerTorsionParameter("k")
    retained_improper_force.addPerTorsionParameter("theta0")
    nonbonded_force = openmm.NonbondedForce()
    nonbonded_force.setNonbondedMethod(openmm.NonbondedForce.NoCutoff)

    category_terms = coverage.get("categories") or {}
    # A correction plan may deliberately promote a covered CHARMM/CGenFF term into
    # the fit basis.  Such a term must be removed from the base system; otherwise the
    # fitted coefficient would be an undocumented additive correction rather than a
    # replacement parameter.  Stable atom paths make this independent of atom indices.
    fitted_paths: dict[str, set[tuple[str, ...]]] = {
        category: set() for category in ("bonds", "angles", "dihedrals")
    }
    for group in fit_plan.get("uncovered_parameter_groups") or []:
        category = group.get("category")
        if category not in fitted_paths:
            raise ValueError(f"fit plan contains unsupported category: {category!r}")
        for occurrence in group.get("occurrences") or []:
            path = _canonical_atom_path(occurrence.get("atoms") or [])
            if not path or path in fitted_paths[category]:
                raise ValueError(
                    f"fit plan contains a missing or duplicate {category} occurrence"
                )
            fitted_paths[category].add(path)
    seen_fitted_paths = {category: set() for category in fitted_paths}
    covered_counts = {"bonds": 0, "angles": 0, "dihedrals": 0}
    omitted = {"bonds": [], "angles": [], "dihedrals": []}
    for term in category_terms.get("bonds", {}).get("terms") or []:
        path = _canonical_atom_path(term["atoms"])
        if path in fitted_paths["bonds"]:
            seen_fitted_paths["bonds"].add(path)
            omitted["bonds"].append(
                {**term, "fit_reason": "promoted_transfer" if term["coverage"] != "missing" else "missing"}
            )
            continue
        values = _unique_values(term["matches"], "-".join(term["atoms"]))
        if len(values) < 2:
            raise ValueError("covered CHARMM bond record is incomplete")
        first, second = (index[key] for key in term["atoms"])
        bond_force.addBond(
            first,
            second,
            float(values[1]) * unit.angstrom,
            2.0 * float(values[0]) * unit.kilocalorie_per_mole / unit.angstrom**2,
        )
        covered_counts["bonds"] += 1
    for term in category_terms.get("angles", {}).get("terms") or []:
        path = _canonical_atom_path(term["atoms"])
        if path in fitted_paths["angles"]:
            seen_fitted_paths["angles"].add(path)
            omitted["angles"].append(
                {**term, "fit_reason": "promoted_transfer" if term["coverage"] != "missing" else "missing"}
            )
            continue
        values = _unique_values(term["matches"], "-".join(term["atoms"]))
        if len(values) not in {2, 4}:
            raise ValueError("covered CHARMM angle record has unsupported fields")
        first, center, third = (index[key] for key in term["atoms"])
        angle_force.addAngle(
            first,
            center,
            third,
            math.radians(float(values[1])) * unit.radian,
            2.0 * float(values[0]) * unit.kilocalorie_per_mole / unit.radian**2,
        )
        if len(values) == 4 and float(values[2]) != 0.0:
            urey_bradley_force.addBond(
                first,
                third,
                float(values[3]) * unit.angstrom,
                2.0 * float(values[2]) * unit.kilocalorie_per_mole / unit.angstrom**2,
            )
        covered_counts["angles"] += 1
    for term in category_terms.get("dihedrals", {}).get("terms") or []:
        path = _canonical_atom_path(term["atoms"])
        if path in fitted_paths["dihedrals"]:
            seen_fitted_paths["dihedrals"].add(path)
            omitted["dihedrals"].append(
                {**term, "fit_reason": "promoted_transfer" if term["coverage"] != "missing" else "missing"}
            )
            continue
        atom_indices = [index[key] for key in term["atoms"]]
        if not term.get("matches"):
            raise ValueError("covered CHARMM proper has no parameter records")
        for match in term["matches"]:
            values = match["values"]
            if len(values) < 3 or int(values[1]) < 1:
                raise ValueError("covered CHARMM proper record is malformed")
            torsion_force.addTorsion(
                *atom_indices,
                int(values[1]),
                math.radians(float(values[2])) * unit.radian,
                float(values[0]) * unit.kilocalorie_per_mole,
            )
        covered_counts["dihedrals"] += 1

    for improper in retained_impropers:
        retained_improper_force.addTorsion(
            *(index[key] for key in improper["atoms"]),
            [
                4.184 * float(improper["k_kcal_mol_rad2"]),
                math.radians(float(improper["psi0_degrees"])),
            ],
        )

    if seen_fitted_paths != fitted_paths:
        missing = {
            category: sorted(fitted_paths[category] - seen_fitted_paths[category])
            for category in fitted_paths
            if fitted_paths[category] != seen_fitted_paths[category]
        }
        raise ValueError(
            "fit-plan occurrences do not exactly map to model coverage: " + repr(missing)
        )

    for key in atom_keys:
        lj = nonbonded[types[key]]
        sigma_angstrom = 2.0 * float(lj["rmin_half_angstrom"]) / 2.0 ** (1.0 / 6.0)
        nonbonded_force.addParticle(
            float(charges[key]) * unit.elementary_charge,
            sigma_angstrom * unit.angstrom,
            abs(float(lj["epsilon_kcal_mol"])) * unit.kilocalorie_per_mole,
        )
    for (first, second), distance in _graph_distances(atom_keys, graph_bonds).items():
        if distance <= 2:
            nonbonded_force.addException(
                first, second, 0.0, 1.0 * unit.angstrom, 0.0, replace=False
            )
            continue
        first_lj = nonbonded[types[atom_keys[first]]]
        second_lj = nonbonded[types[atom_keys[second]]]
        first_rmin = float(
            first_lj.get("rmin_half_14_angstrom", first_lj["rmin_half_angstrom"])
        )
        second_rmin = float(
            second_lj.get("rmin_half_14_angstrom", second_lj["rmin_half_angstrom"])
        )
        sigma = (first_rmin + second_rmin) / 2.0 ** (1.0 / 6.0)
        first_epsilon = abs(
            float(first_lj.get("epsilon_14_kcal_mol", first_lj["epsilon_kcal_mol"]))
        )
        second_epsilon = abs(
            float(second_lj.get("epsilon_14_kcal_mol", second_lj["epsilon_kcal_mol"]))
        )
        nonbonded_force.addException(
            first,
            second,
            float(charges[atom_keys[first]])
            * float(charges[atom_keys[second]])
            * unit.elementary_charge**2,
            sigma * unit.angstrom,
            math.sqrt(first_epsilon * second_epsilon) * unit.kilocalorie_per_mole,
            replace=False,
        )
    for force in (
        bond_force,
        angle_force,
        urey_bradley_force,
        torsion_force,
        retained_improper_force,
        nonbonded_force,
    ):
        system.addForce(force)

    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    context = openmm.Context(
        system, integrator, openmm.Platform.getPlatformByName("Reference")
    )
    context.setPositions(xyz_angstrom * unit.angstrom)
    state = context.getState(getEnergy=True, getForces=True)
    energy = state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole)
    forces = state.getForces(asNumpy=True).value_in_unit(
        unit.kilocalorie_per_mole / unit.angstrom
    )
    del context, integrator
    if not math.isfinite(float(energy)) or not np.all(np.isfinite(forces)):
        raise ValueError(
            "candidate skeleton produced non-finite OpenMM energy or forces"
        )

    output_dir.mkdir(parents=True)
    xml_path = output_dir / "candidate_system.xml"
    pdb_path = output_dir / "candidate_model.pdb"
    map_path = output_dir / "stable_atom_map.json"
    xml_path.write_text(openmm.XmlSerializer.serialize(system))
    topology = app.Topology()
    chain = topology.addChain("M")
    residue = topology.addResidue("CPD", chain, id="1")
    topology_atoms = []
    for serial, atom_record in enumerate(atom_records, start=1):
        topology_atoms.append(
            topology.addAtom(
                f"A{serial:03d}",
                app.element.get_by_symbol(atom_record["element"]),
                residue,
            )
        )
    for record in graph_bonds:
        first, second = (index[key] for key in record["atoms"])
        topology.addBond(topology_atoms[first], topology_atoms[second])
    with pdb_path.open("w") as handle:
        app.PDBFile.writeFile(topology, xyz_angstrom * unit.angstrom, handle)
    map_path.write_text(
        json.dumps(
            [
                {
                    "index": index,
                    "pdb_atom_name": f"A{index + 1:03d}",
                    "stable_atom_key": key,
                    "atom_type": types[key],
                    "charge_e": charges[key],
                }
                for index, key in enumerate(atom_keys)
            ],
            indent=2,
        )
        + "\n"
    )
    manifest = {
        "schema": "nadoc.photoproduct-openmm-candidate-skeleton.v1",
        "status": "candidate_incomplete_missing_bonded_terms",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": fit_plan["product_id"],
        "model_id": fit_plan["model_id"],
        "hypothesis_id": hypothesis_id,
        "software": {
            "openmm": openmm.version.version,
            "numpy": np.__version__,
        },
        "atom_count": len(atom_keys),
        "model_charge_e": sum(float(charges[key]) for key in atom_keys),
        "covered_term_counts": covered_counts,
        "omitted_missing_term_counts": {
            category: sum(record.get("fit_reason") == "missing" for record in records)
            for category, records in omitted.items()
        },
        "omitted_fit_term_counts": {
            category: len(records) for category, records in omitted.items()
        },
        "promoted_transfer_term_counts": {
            category: sum(
                record.get("fit_reason") == "promoted_transfer" for record in records
            )
            for category, records in omitted.items()
        },
        "retained_precursor_improper_count": len(retained_impropers),
        "retained_precursor_impropers": retained_impropers,
        "product_impropers_included": 0,
        "evaluation": {
            "platform": "Reference",
            "potential_energy_kcal_mol": float(energy),
            "maximum_force_kcal_mol_angstrom": float(
                np.max(np.linalg.norm(forces, axis=1))
            ),
            "finite": True,
            "interpretation": "diagnostic_only_incomplete_energy",
        },
        "outputs": {
            "system_xml": {
                "path": str(xml_path.resolve()),
                "sha256": _sha256(xml_path),
            },
            "model_pdb": {"path": str(pdb_path.resolve()), "sha256": _sha256(pdb_path)},
            "stable_atom_map": {
                "path": str(map_path.resolve()),
                "sha256": _sha256(map_path),
            },
        },
        "sources": {
            "fit_plan": {
                "path": str(fit_plan_path.resolve()),
                "sha256": _sha256(fit_plan_path),
            },
            "nonbonded_fit": {
                "path": str(nonbonded_fit_path.resolve()),
                "sha256": _sha256(nonbonded_fit_path),
            },
            "cgenff_topology": {
                "path": str(cgenff_topology_path.resolve()),
                "sha256": cgenff_hashes["topology_sha256"],
            },
            "cgenff_parameters": {
                "path": str(cgenff_parameters_path.resolve()),
                "sha256": cgenff_hashes["parameters_sha256"],
            },
            "nucleic_topology": (
                {
                    "path": str(nucleic_topology_path.resolve()),
                    "sha256": nucleic_hashes["topology_sha256"],
                }
                if nucleic_topology_path is not None and nucleic_hashes is not None
                else None
            ),
            "nucleic_parameters": (
                {
                    "path": str(nucleic_parameters_path.resolve()),
                    "sha256": nucleic_hashes["parameters_sha256"],
                }
                if nucleic_parameters_path is not None and nucleic_hashes is not None
                else None
            ),
        },
        "release_blockers": [
            "all omitted bonds, angles, and proper terms must be fitted",
            "all four ordered product stereochemical impropers must be fitted and added",
            "candidate transfer terms and Lennard-Jones types require review",
            "the fitted model must be translated to CHARMM and revalidated in psfgen/NAMD",
        ],
        "warning": (
            "The finite energy proves only that the candidate representation can be "
            "evaluated. Missing terms are omitted, so this XML must never be simulated."
        ),
    }
    manifest_path = output_dir / "candidate_skeleton_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
