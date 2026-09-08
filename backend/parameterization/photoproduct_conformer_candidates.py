"""Deterministic, gate-neutral coupled-conformer candidates from an audited Hessian."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.parameterization.photoproduct_coupled_conformer import (
    _chirality,
    _coordinates,
    _geometry_metrics,
    _graph,
    _source,
    _stable_keys,
    _stereo_records,
)
from backend.parameterization.photoproduct_definition_review import (
    _load_equivalent_hessian_references,
)
from backend.parameterization.photoproduct_distributed_hessian import (
    _frequency_reference,
)
from backend.parameterization.photoproduct_hessian import _load_square_matrix
from backend.parameterization.photoproduct_qm import parse_xyz


_ATOMIC_MASS = {
    "H": 1.00784,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "P": 30.973761998,
    "S": 32.06,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} is missing or hash-mismatched")
    return path.resolve()


def build_coupled_conformer_mode_source(
    *,
    model_graph_path: Path,
    stable_atom_map_path: Path,
    stereochemistry_evidence_path: Path,
    output_path: Path,
    frequency_job_dir: Path | None = None,
    equivalent_hessian_reference_path: Path | None = None,
) -> dict[str, Any]:
    """Expose an audited minimum response for conformer generation, never fitting.

    Exactly one direct frequency directory or endpoint-equivalence reference is required.
    Unlike a Hessian target bundle, this artifact enumerates no force-field terms and
    therefore cannot bypass the reviewed chemical-definition gate.
    """

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite conformer mode source: {output_path}")
    if (frequency_job_dir is None) == (equivalent_hessian_reference_path is None):
        raise ValueError(
            "exactly one frequency job directory or equivalent-Hessian reference is required"
        )
    keys = _stable_keys(stable_atom_map_path)
    graph = _graph(model_graph_path, keys)

    evidence_sources: dict[str, Any]
    source_product_id = None
    derived_geometry_text: str | None = None
    derived_hessian: np.ndarray | None = None
    derived_geometry_path: Path | None = None
    derived_hessian_path: Path | None = None
    if frequency_job_dir is not None:
        job_dir = frequency_job_dir.resolve()
        job_path = job_dir / "job_manifest.json"
        audit_path = job_dir / "frequency_audit.json"
        hessian_path = job_dir / "hessian_hartree_per_bohr2.txt"
        if not all(path.is_file() for path in (job_path, audit_path, hessian_path)):
            raise ValueError("direct mode source requires frequency job, audit, and Hessian")
        job = json.loads(job_path.read_text())
        audit = json.loads(audit_path.read_text())
        product_id = str(job.get("product_id") or "")
        model_id = str(job.get("model_id") or "")
        if (
            job.get("schema") != "nadoc.photoproduct-qm-job.v1"
            or job.get("job_kind") != "frequency"
            or job.get("atom_map") != keys
            or job.get("atom_count") != len(keys)
            or audit.get("schema") != "nadoc.photoproduct-frequency-audit.v1"
            or audit.get("status")
            not in {"passed_harmonic_minimum", "passed_candidate_harmonic_minimum"}
            or audit.get("gate_effect") != "none"
            or audit.get("product_id") != product_id
            or audit.get("model_id") != model_id
            or audit.get("imaginary_mode_count") != 0
        ):
            raise ValueError("direct frequency evidence is not a matching audited minimum")
        source_path = _frequency_reference(
            job_dir=job_dir,
            job=job,
            key="source_xyz",
            label="frequency source geometry",
        )
        hessian_record = audit.get("cartesian_hessian") or {}
        if (
            hessian_record.get("status") != "passed"
            or hessian_record.get("units") != "hartree/bohr^2"
            or hessian_record.get("sha256") != _sha256(hessian_path)
        ):
            raise ValueError("frequency audit does not hash-link a passed Cartesian Hessian")
        frequency_status = audit["status"]
        evidence_sources = {
            "frequency_job": _source(job_path),
            "frequency_audit": _source(audit_path),
        }
    else:
        reference_path = equivalent_hessian_reference_path.resolve()
        records = _load_equivalent_hessian_references([reference_path])
        reference = json.loads(reference_path.read_text())
        product_id = str(reference.get("target_product_id") or "")
        if product_id not in records:
            raise ValueError("equivalent-Hessian reference target is inconsistent")
        source_map = reference.get("source_atom_map")
        target_map = reference.get("target_atom_map_in_source_matrix_order")
        if (
            not isinstance(source_map, list)
            or not isinstance(target_map, list)
            or len(source_map) != len(keys)
            or len(target_map) != len(keys)
            or len(source_map) != len(set(source_map))
            or len(target_map) != len(set(target_map))
            or set(target_map) != set(keys)
        ):
            raise ValueError(
                "equivalent-Hessian source/target atom maps do not bijectively cover the model"
        )
        stereo_document = json.loads(stereochemistry_evidence_path.read_text())
        model_id = str(
            stereo_document.get("model_id")
            or (
                (stereo_document.get("model_compounds") or {}).get("charge_model")
                or {}
            ).get("id")
            or ""
        )
        if not model_id:
            raise ValueError("equivalent target stereochemistry evidence has no model ID")
        source_frequency = reference.get("source_frequency") or {}
        original_source_path = _checked(
            source_frequency.get("source_geometry"), "equivalent source geometry"
        )
        original_hessian_path = _checked(
            source_frequency.get("cartesian_hessian"),
            "equivalent source Cartesian Hessian",
        )
        source_atoms, _comment = parse_xyz(original_source_path.read_text())
        if len(source_atoms) != len(source_map):
            raise ValueError("equivalent source geometry and atom map lengths differ")
        source_hessian_rows, _source_symmetry = _load_square_matrix(
            original_hessian_path, 3 * len(source_map)
        )
        atom_permutation = [target_map.index(key) for key in keys]
        coordinate_permutation = [
            3 * atom_index + component
            for atom_index in atom_permutation
            for component in range(3)
        ]
        reordered_atoms = [source_atoms[index] for index in atom_permutation]
        expected_elements = [str(item.get("element")) for item in graph["atoms"]]
        if [atom[0] for atom in reordered_atoms] != expected_elements:
            raise ValueError(
                "equivalent atom-map permutation changes model element identity"
            )
        derived_geometry_text = (
            f"{len(reordered_atoms)}\n"
            f"{product_id} endpoint-exchange matrix-order permutation; no rotation\n"
            + "\n".join(
                f"{element:<2} {x: .12f} {y: .12f} {z: .12f}"
                for element, x, y, z in reordered_atoms
            )
            + "\n"
        )
        source_matrix = np.asarray(source_hessian_rows, dtype=float)
        derived_hessian = source_matrix[
            np.ix_(coordinate_permutation, coordinate_permutation)
        ]
        derived_geometry_path = output_path.with_name(
            f"{output_path.stem}.source_geometry.xyz"
        )
        derived_hessian_path = output_path.with_name(
            f"{output_path.stem}.hessian_hartree_per_bohr2.txt"
        )
        if derived_geometry_path.exists() or derived_hessian_path.exists():
            raise FileExistsError(
                "refusing to overwrite equivalent mode-source derived arrays"
            )
        source_path = derived_geometry_path
        hessian_path = derived_hessian_path
        frequency_status = "passed_equivalent_source_candidate"
        source_product_id = reference.get("source_product_id")
        evidence_sources = {
            "equivalent_hessian_reference": _source(reference_path),
            "source_frequency_audit": _source(
                _checked(source_frequency.get("frequency_audit"), "source frequency audit")
            ),
            "matrix_order_derivation": {
                "source_geometry": _source(original_source_path),
                "source_cartesian_hessian": _source(original_hessian_path),
                "source_atom_map": source_map,
                "target_atom_map_in_source_matrix_order": target_map,
                "output_target_atom_map": keys,
                "atom_permutation_zero_based": atom_permutation,
                "coordinate_permutation_zero_based": coordinate_permutation,
                "spatial_transform": "none",
                "tensor_operation": "simultaneous row-and-column permutation only",
            },
        }

    stereo_payload, stereo = _stereo_records(
        stereochemistry_evidence_path, product_id, model_id
    )
    if derived_geometry_text is not None and derived_hessian is not None:
        preview_coordinates = {
            key: [float(x), float(y), float(z)]
            for key, (_element, x, y, z) in zip(
                keys, reordered_atoms, strict=True
            )
        }
        if _chirality(stereo, preview_coordinates).get("passed") is not True:
            raise ValueError(
                "permuted equivalent minimum fails pinned product stereochemistry"
            )
        assert derived_geometry_path is not None
        assert derived_hessian_path is not None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        derived_geometry_path.write_text(derived_geometry_text)
        np.savetxt(derived_hessian_path, derived_hessian, fmt="%.16e")
    _reference, coordinates = _coordinates(source_path, graph, keys)
    chirality = _chirality(stereo, coordinates)
    if chirality.get("passed") is not True:
        raise ValueError("mode-source minimum fails pinned product stereochemistry")
    _matrix, symmetry_error = _load_square_matrix(hessian_path, 3 * len(keys))
    mode_source = {
        "schema": "nadoc.photoproduct-conformer-mode-source.v1",
        "status": "candidate_mode_source_not_fit_target",
        "simulation_ready": False,
        "gate_effect": "none",
        "contains_parameter_targets": False,
        "chemical_definition_gate_required_before_fit_targets": True,
        "product_id": product_id,
        "model_id": model_id,
        "source_product_id": source_product_id,
        "frequency_evidence_status": frequency_status,
        "atom_map": keys,
        "source_geometry": _source(source_path),
        "cartesian_hessian": {
            **_source(hessian_path),
            "units": "hartree/bohr^2",
            "dimension": 3 * len(keys),
            "maximum_symmetry_error": symmetry_error,
        },
        "chirality_audit": chirality,
        "sources": {
            **evidence_sources,
            "model_graph": _source(model_graph_path),
            "stable_atom_map": _source(stable_atom_map_path),
            "stereochemistry_evidence": _source(stereochemistry_evidence_path),
        },
        "stereochemistry_evidence_schema": stereo_payload.get("schema"),
        "interpretation": (
            "This gate-neutral response may select geometries for human conformer review. "
            "It enumerates no CHARMM terms and is not a Hessian fitting target."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(mode_source, indent=2) + "\n")
    return mode_source


def _ring_cycle(graph: dict[str, Any], active: Sequence[str]) -> list[str]:
    """Return a deterministic four-membered active cycle or fail closed."""

    if len(active) != 4:
        raise ValueError(
            "current coupled-ring mode selector requires exactly four active atoms"
        )
    active_set = set(active)
    adjacency = {key: set() for key in active}
    for bond in graph["bonds"]:
        first, second = bond["atoms"]
        if first in active_set and second in active_set:
            adjacency[first].add(second)
            adjacency[second].add(first)
    if any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise ValueError("active atoms do not form one unambiguous four-membered ring")
    order_index = {key: index for index, key in enumerate(active)}
    start = active[0]
    previous = None
    current = start
    cycle = []
    while current not in cycle:
        cycle.append(current)
        choices = sorted(
            adjacency[current] - ({previous} if previous is not None else set()),
            key=order_index.get,
        )
        if not choices:
            break
        previous, current = current, choices[0]
    if len(cycle) != 4 or current != start:
        raise ValueError("active ring traversal is not a single four-membered cycle")
    return cycle


def _plane_rms(coordinates: np.ndarray) -> float:
    centered = coordinates - np.mean(coordinates, axis=0)
    _left, _singular, right = np.linalg.svd(centered, full_matrices=False)
    normal = right[-1]
    return float(np.sqrt(np.mean((centered @ normal) ** 2)))


def _dihedral_degrees(points: np.ndarray) -> float:
    first = points[1] - points[0]
    second = points[2] - points[1]
    third = points[3] - points[2]
    normal_1 = np.cross(first, second)
    normal_2 = np.cross(second, third)
    norm_1 = np.linalg.norm(normal_1)
    norm_2 = np.linalg.norm(normal_2)
    norm_bond = np.linalg.norm(second)
    if min(norm_1, norm_2, norm_bond) <= 1.0e-12:
        raise ValueError("ring torsion is undefined for collinear atoms")
    normal_1 /= norm_1
    normal_2 /= norm_2
    bond = second / norm_bond
    return float(
        np.degrees(
            np.arctan2(
                np.dot(np.cross(normal_1, normal_2), bond),
                np.dot(normal_1, normal_2),
            )
        )
    )


def _angle_difference_degrees(first: float, second: float) -> float:
    return (first - second + 180.0) % 360.0 - 180.0


def _ring_mode_metrics(
    *,
    reference: np.ndarray,
    displacement: np.ndarray,
    cycle_indices: np.ndarray,
    active_indices: np.ndarray,
) -> dict[str, float]:
    active_rms = float(
        np.sqrt(np.mean(np.sum(displacement[active_indices] ** 2, axis=1)))
    )
    if active_rms <= 0.0:
        raise ValueError("normal mode has zero active-region displacement")
    probe_amplitude = 0.02
    scaled = displacement * (probe_amplitude / active_rms)
    ring_reference = reference[cycle_indices]
    reference_pucker = _plane_rms(ring_reference)
    reference_torsion = _dihedral_degrees(ring_reference)
    ring_bonds = tuple(zip(range(4), (1, 2, 3, 0), strict=True))
    reference_lengths = np.asarray(
        [
            np.linalg.norm(ring_reference[first] - ring_reference[second])
            for first, second in ring_bonds
        ]
    )
    pucker_changes = []
    torsion_changes = []
    bond_strains = []
    for sign in (-1.0, 1.0):
        ring = (reference + sign * scaled)[cycle_indices]
        pucker_changes.append(abs(_plane_rms(ring) - reference_pucker))
        torsion_changes.append(
            abs(_angle_difference_degrees(_dihedral_degrees(ring), reference_torsion))
        )
        lengths = np.asarray(
            [np.linalg.norm(ring[first] - ring[second]) for first, second in ring_bonds]
        )
        bond_strains.append(
            float(
                np.sqrt(
                    np.mean(((lengths - reference_lengths) / reference_lengths) ** 2)
                )
            )
        )
    return {
        "probe_active_rmsd_angstrom": probe_amplitude,
        "reference_ring_plane_rms_angstrom": reference_pucker,
        "reference_ring_torsion_degrees": reference_torsion,
        "maximum_ring_plane_rms_change_per_angstrom": max(pucker_changes)
        / probe_amplitude,
        "maximum_ring_torsion_change_degrees_per_angstrom": max(torsion_changes)
        / probe_amplitude,
        "maximum_ring_bond_fractional_rms_change_per_angstrom": max(bond_strains)
        / probe_amplitude,
    }


def build_coupled_conformer_candidates(
    *,
    hessian_targets_path: Path,
    model_graph_path: Path,
    stable_atom_map_path: Path,
    stereochemistry_evidence_path: Path,
    active_atom_keys: Sequence[str],
    output_dir: Path,
    mode_pair_count: int = 4,
    active_rmsd_amplitudes_angstrom: Sequence[float] = (0.04, 0.08),
) -> dict[str, Any]:
    """Displace active-region-rich normal modes without optimization or reflection.

    The outputs are only candidates for human review.  A normal-mode displacement is a
    reproducible way to span coupled local coordinates; it is not evidence that a
    structure is an important conformer or that any parameter value is correct.
    """

    if output_dir.exists():
        raise FileExistsError(
            f"refusing to overwrite conformer candidates: {output_dir}"
        )
    if mode_pair_count < 1:
        raise ValueError("mode_pair_count must be positive")
    amplitudes = [float(value) for value in active_rmsd_amplitudes_angstrom]
    if (
        not amplitudes
        or len(amplitudes) != len(set(amplitudes))
        or any(
            not np.isfinite(value) or value <= 0.0 or value > 0.25
            for value in amplitudes
        )
    ):
        raise ValueError(
            "active-region RMSD amplitudes must be unique in (0, 0.25] angstrom"
        )
    target = json.loads(hessian_targets_path.read_text())
    target_schema = target.get("schema")
    hessian_target = target_schema == "nadoc.photoproduct-hessian-target-bundle.v1"
    mode_source = target_schema == "nadoc.photoproduct-conformer-mode-source.v1"
    valid_status = target.get("frequency_evidence_status") in {
        "passed_harmonic_minimum",
        "passed_candidate_harmonic_minimum",
        "passed_equivalent_source_candidate",
    }
    if (
        not (hessian_target or mode_source)
        or not valid_status
        or target.get("gate_effect") != "none"
        or (
            mode_source
            and (
                target.get("status") != "candidate_mode_source_not_fit_target"
                or target.get("simulation_ready") is not False
                or target.get("contains_parameter_targets") is not False
                or target.get("chemical_definition_gate_required_before_fit_targets")
                is not True
            )
        )
    ):
        raise ValueError(
            "candidate generation requires an audited minimum Hessian target"
        )
    keys = _stable_keys(stable_atom_map_path)
    if keys != target.get("atom_map"):
        raise ValueError("minimum Hessian and stable atom map orders differ")
    graph = _graph(model_graph_path, keys)
    product_id = str(target.get("product_id") or "")
    model_id = str(target.get("model_id") or "")
    _stereo_payload, stereo = _stereo_records(
        stereochemistry_evidence_path, product_id, model_id
    )
    geometry_path = _checked(target.get("source_geometry"), "minimum geometry")
    hessian_path = _checked(
        target.get("cartesian_hessian"), "minimum Cartesian Hessian"
    )
    reference, reference_coordinates = _coordinates(geometry_path, graph, keys)
    if not _chirality(stereo, reference_coordinates)["passed"]:
        raise ValueError("minimum geometry fails pinned product stereochemistry")
    active = list(active_atom_keys)
    if (
        len(active) != 4
        or len(active) != len(set(active))
        or not set(active).issubset(keys)
    ):
        raise ValueError(
            "active coupled region requires exactly four unique mapped atoms"
        )
    cycle = _ring_cycle(graph, active)
    dimension = 3 * len(keys)
    hessian = np.loadtxt(hessian_path, ndmin=2)
    if (
        hessian.shape != (dimension, dimension)
        or not np.all(np.isfinite(hessian))
        or not np.allclose(hessian, hessian.T, atol=1.0e-8)
    ):
        raise ValueError("minimum Cartesian Hessian is malformed")
    elements = [str(item["element"]) for item in graph["atoms"]]
    try:
        masses = np.asarray([_ATOMIC_MASS[element] for element in elements])
    except KeyError as exc:
        raise ValueError(f"no normal-mode mass for element {exc.args[0]}") from exc
    inverse_sqrt_mass = np.repeat(1.0 / np.sqrt(masses), 3)
    mass_weighted = inverse_sqrt_mass[:, None] * hessian * inverse_sqrt_mass[None, :]
    eigenvalues, eigenvectors = np.linalg.eigh((mass_weighted + mass_weighted.T) / 2.0)
    largest = float(np.max(np.abs(eigenvalues)))
    if largest <= 0.0:
        raise ValueError("minimum Hessian has no nonzero vibrational response")
    active_indices = np.asarray([keys.index(key) for key in active], dtype=int)
    cycle_indices = np.asarray([keys.index(key) for key in cycle], dtype=int)
    heavy_indices = np.asarray(
        [index for index, element in enumerate(elements) if element != "H"], dtype=int
    )
    scored = []
    for mode_index, eigenvalue in enumerate(eigenvalues):
        if eigenvalue <= largest * 1.0e-8:
            continue
        cartesian = (inverse_sqrt_mass * eigenvectors[:, mode_index]).reshape((-1, 3))
        total = float(np.sum(cartesian[heavy_indices] ** 2))
        active_norm = float(np.sum(cartesian[active_indices] ** 2))
        if total <= 0.0 or active_norm <= 0.0:
            continue
        ring_metrics = _ring_mode_metrics(
            reference=reference,
            displacement=cartesian,
            cycle_indices=cycle_indices,
            active_indices=active_indices,
        )
        active_fraction = active_norm / total
        deformation_numerator = (
            ring_metrics["maximum_ring_plane_rms_change_per_angstrom"]
            + ring_metrics["maximum_ring_torsion_change_degrees_per_angstrom"] / 180.0
        )
        deformation_denominator = (
            1.0
            + 10.0
            * ring_metrics["maximum_ring_bond_fractional_rms_change_per_angstrom"]
        )
        scored.append(
            {
                "mode_index_zero_based": mode_index,
                "eigenvalue_hartree_per_bohr2_per_amu": float(eigenvalue),
                "active_heavy_displacement_fraction": active_fraction,
                "ring_deformation_metrics": ring_metrics,
                "coupled_ring_deformation_score": (
                    active_fraction * deformation_numerator / deformation_denominator
                ),
                "cartesian": cartesian,
            }
        )
    scored.sort(
        key=lambda item: (
            -item["coupled_ring_deformation_score"],
            item["mode_index_zero_based"],
        )
    )
    # Reject modes whose non-active hydrogens or substituents move so strongly that even
    # the smallest requested +/- displacement damages the molecular graph.  Continue
    # down the ranked list instead of silently returning fewer usable mode pairs.
    selected = []
    rejected_modes = []
    precheck_amplitude = min(amplitudes)
    for mode in scored:
        displacement = mode["cartesian"]
        active_rms = float(
            np.sqrt(np.mean(np.sum(displacement[active_indices] ** 2, axis=1)))
        )
        prechecks = []
        for sign in (-1, 1):
            candidate = reference + sign * displacement * (
                precheck_amplitude / active_rms
            )
            coordinates = {
                key: point.tolist() for key, point in zip(keys, candidate, strict=True)
            }
            prechecks.append(
                {
                    "sign": sign,
                    "chirality_passed": _chirality(stereo, coordinates)["passed"],
                    "geometry_passed": _geometry_metrics(
                        graph=graph,
                        keys=keys,
                        reference=reference,
                        candidate=candidate,
                    )["passed"],
                }
            )
        if all(
            item["chirality_passed"] and item["geometry_passed"] for item in prechecks
        ):
            selected.append(mode)
            if len(selected) == mode_pair_count:
                break
        else:
            rejected_modes.append(
                {
                    "mode_index_zero_based": mode["mode_index_zero_based"],
                    "coupled_ring_deformation_score": mode[
                        "coupled_ring_deformation_score"
                    ],
                    "precheck_active_rmsd_angstrom": precheck_amplitude,
                    "prechecks": prechecks,
                    "reason": "smallest_amplitude_damages_graph_or_stereochemistry",
                }
            )
    if len(selected) != mode_pair_count:
        raise ValueError(
            "too few positive, geometry-safe modes to build requested coupled candidates"
        )
    atoms, _comment = parse_xyz(geometry_path.read_text())
    output_dir.mkdir(parents=True)
    records = []
    rejected = []
    for rank, mode in enumerate(selected, start=1):
        displacement = mode["cartesian"]
        active_rms = float(
            np.sqrt(np.mean(np.sum(displacement[active_indices] ** 2, axis=1)))
        )
        if active_rms <= 0.0:
            raise ValueError("selected normal mode has zero active-region displacement")
        for amplitude in amplitudes:
            for sign in (-1, 1):
                candidate = reference + sign * displacement * (amplitude / active_rms)
                coordinates = {
                    key: point.tolist()
                    for key, point in zip(keys, candidate, strict=True)
                }
                chirality = _chirality(stereo, coordinates)
                geometry = _geometry_metrics(
                    graph=graph,
                    keys=keys,
                    reference=reference,
                    candidate=candidate,
                )
                candidate_id = (
                    f"mode-{mode['mode_index_zero_based']:03d}-"
                    f"{'minus' if sign < 0 else 'plus'}-"
                    f"{int(round(amplitude * 1000)):03d}mA"
                )
                audit = {
                    "id": candidate_id,
                    "mode_rank_by_active_fraction": rank,
                    "mode_index_zero_based": mode["mode_index_zero_based"],
                    "mode_eigenvalue_hartree_per_bohr2_per_amu": mode[
                        "eigenvalue_hartree_per_bohr2_per_amu"
                    ],
                    "active_heavy_displacement_fraction": mode[
                        "active_heavy_displacement_fraction"
                    ],
                    "coupled_ring_deformation_score": mode[
                        "coupled_ring_deformation_score"
                    ],
                    "ring_deformation_metrics": mode["ring_deformation_metrics"],
                    "signed_active_rmsd_angstrom": sign * amplitude,
                    "chirality_audit": chirality,
                    "geometry_audit": geometry,
                }
                if not chirality["passed"] or not geometry["passed"]:
                    rejected.append({**audit, "reason": "chirality_or_geometry_gate"})
                    continue
                path = output_dir / f"{candidate_id}.xyz"
                path.write_text(
                    f"{len(atoms)}\n{product_id} gate-neutral normal-mode candidate {candidate_id}\n"
                    + "\n".join(
                        f"{atom[0]:<2} {point[0]: .12f} {point[1]: .12f} {point[2]: .12f}"
                        for atom, point in zip(atoms, candidate, strict=True)
                    )
                    + "\n"
                )
                records.append({**audit, "geometry": _source(path)})
    if len(records) < 2:
        raise ValueError(
            "normal-mode displacement produced fewer than two valid candidates"
        )
    manifest = {
        "schema": "nadoc.photoproduct-coupled-conformer-candidates.v1",
        "status": "candidates_not_reviewed",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "model_id": model_id,
        "active_atom_keys": active,
        "active_ring_cycle": cycle,
        "generation": {
            "method": "mass-weighted minimum-Hessian normal-mode displacement",
            "mode_selection": (
                "largest proper-rotation ring-pucker/torsion response after penalizing "
                "ring-bond strain, weighted by active-heavy displacement fraction"
            ),
            "mode_pair_count": mode_pair_count,
            "active_rmsd_amplitudes_angstrom": amplitudes,
            "proper_rotation_only": True,
            "optimization_performed": False,
        },
        "sources": {
            (
                "hessian_targets"
                if hessian_target
                else "conformer_mode_source"
            ): _source(hessian_targets_path),
            "minimum_geometry": _source(geometry_path),
            "minimum_cartesian_hessian": _source(hessian_path),
            "model_graph": _source(model_graph_path),
            "stable_atom_map": _source(stable_atom_map_path),
            "stereochemistry_evidence": _source(stereochemistry_evidence_path),
        },
        "candidates": records,
        "rejected_candidates": rejected,
        "rejected_modes_during_preselection": rejected_modes,
        "warning": (
            "These deterministic distortions only propose sampling geometries. Human "
            "structural review and an independent validation split are mandatory before QM."
        ),
    }
    manifest_path = output_dir / "coupled_conformer_candidates.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
