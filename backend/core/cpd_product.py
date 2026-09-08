"""Capability-gated, non-reflective photoproduct coordinate placement.

The numerical placement core is reusable and testable before chemistry assets are
released. Production entry points still require every registry gate and asset hash;
there is no two-bond or restraint fallback.
"""

from __future__ import annotations

import copy
import hashlib
from itertools import permutations
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from backend.core.atomistic import AtomisticModel, VDW_RADIUS
from backend.core.base_keys import ResolvedBase, resolve_base_keys
from backend.core.cpd_forcefield import assert_cpd_simulation_supported, cpd_capability
from backend.core.photoproduct_chemistry import (
    audit_product_chirality,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import REGISTRY_PATH, photoproduct_registry
from backend.core.photoproduct_registry import photoproduct_capability


class ProductPlacementError(RuntimeError):
    """A product template cannot be placed without violating a safety audit."""

    def __init__(self, message: str, *, report: dict[str, Any] | None = None):
        super().__init__(message)
        self.report = report


_BASE_HEAVY_ATOMS = frozenset(
    {"N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"}
)
_RING_ATOMS = frozenset({"1:C5", "1:C6", "2:C5", "2:C6"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unavailable_placement_report(
    base_keys: list[str],
    reactant_geometry: dict[str, Any] | None,
    *,
    stereochemistry: str = "cis-syn",
) -> dict[str, Any]:
    capability = cpd_capability()
    try:
        product_capability = photoproduct_capability("TT-CPD", stereochemistry)
        reasons = product_capability["blockers"]
        product_id = product_capability["id"]
    except KeyError:
        reasons = [f"unregistered chemistry TT-CPD/{stereochemistry}"]
        product_id = None
    return {
        "schema": "nadoc.cpd-product-placement.v1",
        "status": "blocked_parameters_unavailable",
        "passed": False,
        "coordinates_modified": False,
        "endpoint_keys": list(base_keys),
        "product": "TT-CPD",
        "stereochemistry": stereochemistry,
        "product_id": product_id,
        "template_version": None,
        "parameter_version": None,
        "capability_manifest_schema": capability["manifest_schema"],
        "capability_manifest_sha256": capability["manifest_sha256"],
        "assignment_evaluated": False,
        "reactant_geometry": reactant_geometry,
        "reasons": reasons,
    }


def _template_coordinates(
    template: dict[str, Any],
    *,
    allowed_release_statuses: frozenset[str] = frozenset({"released"}),
) -> dict[str, np.ndarray]:
    if template.get("schema") != "nadoc.photoproduct-coordinate-template.v1":
        raise ProductPlacementError("unsupported coordinate-template schema")
    if template.get("units") != "angstrom":
        raise ProductPlacementError("coordinate template units must be angstrom")
    if template.get("reflection_allowed") is not False:
        raise ProductPlacementError("coordinate template must explicitly forbid reflection")
    if template.get("release_status") not in allowed_release_statuses:
        raise ProductPlacementError(
            "coordinate template has not passed required release review/candidate status"
        )
    raw = template.get("coordinates")
    if not isinstance(raw, dict) or not raw:
        raise ProductPlacementError("coordinate template has no atom coordinates")
    coordinates: dict[str, np.ndarray] = {}
    for key, values in raw.items():
        if (
            not isinstance(key, str)
            or not isinstance(values, list)
            or len(values) != 3
            or not all(isinstance(value, (int, float)) for value in values)
        ):
            raise ProductPlacementError(f"invalid template coordinate for {key!r}")
        point = np.asarray(values, dtype=float) * 0.1
        if not np.all(np.isfinite(point)):
            raise ProductPlacementError(f"non-finite template coordinate for {key!r}")
        coordinates[key] = point
    required = {
        *(f"{endpoint}:{name}" for endpoint in (1, 2) for name in _BASE_HEAVY_ATOMS),
        "1:C1'",
        "2:C1'",
        "1:H6",
        "2:H6",
    }
    missing = sorted(required - set(coordinates))
    if missing:
        raise ProductPlacementError(
            "coordinate template lacks required conserved atoms: " + ", ".join(missing)
        )
    provenance = template.get("provenance")
    required_hashes = {
        "optimized_xyz_sha256",
        "optimized_model_audit_sha256",
        "frequency_audit_sha256",
    }
    if not isinstance(provenance, dict) or any(
        not isinstance(provenance.get(name), str)
        or len(provenance[name]) != 64
        or any(character not in "0123456789abcdef" for character in provenance[name])
        for name in required_hashes
    ):
        raise ProductPlacementError("coordinate template provenance hashes are incomplete")
    return coordinates


def _proper_kabsch(
    source: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return a proper rotation/translation and anchor RMSD in source units."""

    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ProductPlacementError("source and target anchor arrays must be Nx3")
    source_center = source.mean(axis=0)
    target_center = target.mean(axis=0)
    covariance = (source - source_center).T @ (target - target_center)
    left, _singular, right_t = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(right_t.T @ left.T))
    rotation = right_t.T @ correction @ left.T
    if np.linalg.det(rotation) < 1.0 - 1e-8:
        raise ProductPlacementError("non-reflective Kabsch fit did not yield a proper rotation")
    translation = target_center - rotation @ source_center
    fitted = (rotation @ source.T).T + translation
    rmsd = float(np.sqrt(np.mean(np.sum((fitted - target) ** 2, axis=1))))
    return rotation, translation, rmsd


def _distance(first: Sequence[float], second: Sequence[float]) -> float:
    return math.sqrt(
        sum((float(a) - float(b)) ** 2 for a, b in zip(first, second, strict=True))
    )


def _ordered_product_ring_keys(
    chemical_definition: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Derive the actual four-membered cycle for either syn or anti connectivity."""

    graph = chemical_definition.get("graph_delta")
    if not isinstance(graph, dict):
        raise ProductPlacementError("chemical definition lacks a product graph")
    adjacency = {atom: set() for atom in _RING_ATOMS}
    edge_count = 0
    for category in ("bonds_added", "bonds_retained"):
        for bond in graph.get(category) or []:
            first = bond.get("atom_1")
            second = bond.get("atom_2")
            product_order = (
                bond.get("order")
                if category == "bonds_added"
                else bond.get("product_order")
            )
            if first in _RING_ATOMS and second in _RING_ATOMS:
                if first == second or product_order != "single":
                    raise ProductPlacementError(
                        "product cyclobutane graph has a non-single or self bond"
                    )
                adjacency[first].add(second)
                adjacency[second].add(first)
                edge_count += 1
    if edge_count != 4 or any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise ProductPlacementError(
            "product C5/C6 graph must be one four-membered single-bond cycle"
        )
    start = "1:C5"
    first = "1:C6"
    if first not in adjacency[start]:
        raise ProductPlacementError("endpoint 1 intrabase C5-C6 bond is not retained")
    cycle = [start, first]
    previous, current = start, first
    while True:
        candidates = adjacency[current] - {previous}
        if len(candidates) != 1:
            raise ProductPlacementError("product cyclobutane graph is branched")
        following = next(iter(candidates))
        if following == start:
            break
        if following in cycle or len(cycle) == 4:
            raise ProductPlacementError("product cyclobutane graph is not a four-cycle")
        cycle.append(following)
        previous, current = current, following
    if len(cycle) != 4 or set(cycle) != _RING_ATOMS:
        raise ProductPlacementError("product cyclobutane cycle omits a C5/C6 atom")
    return tuple(cycle)  # type: ignore[return-value]


def _product_ring_bond_audit(
    *,
    template: dict[str, Any],
    chemical_definition: dict[str, Any],
    coordinates: dict[str, np.ndarray],
    expected_parameter_sha256: str,
) -> dict[str, Any]:
    """Validate product-specific ring ranges supplied by the reviewed parameter set."""

    safety = template.get("placement_safety")
    parameter_hash = (safety or {}).get("parameter_asset_sha256")
    ranges = (safety or {}).get("product_ring_bond_ranges_angstrom")
    if (
        not isinstance(safety, dict)
        or safety.get("schema") != "nadoc.photoproduct-placement-safety.v1"
        or not isinstance(parameter_hash, str)
        or len(parameter_hash) != 64
        or any(character not in "0123456789abcdef" for character in parameter_hash)
        or parameter_hash != expected_parameter_sha256
        or not isinstance(ranges, list)
    ):
        raise ProductPlacementError(
            "released template lacks hash-linked product placement safety bounds"
        )
    expected = {
        frozenset((bond["atom_1"], bond["atom_2"]))
        for category in ("bonds_added", "bonds_retained")
        for bond in chemical_definition["graph_delta"][category]
    }
    by_bond: dict[frozenset[str], dict[str, Any]] = {}
    for record in ranges:
        if not isinstance(record, dict):
            raise ProductPlacementError("malformed product ring bond safety record")
        first = record.get("atom_1")
        second = record.get("atom_2")
        minimum = record.get("minimum_angstrom")
        maximum = record.get("maximum_angstrom")
        authority = record.get("authority")
        identity = frozenset((first, second))
        if (
            not isinstance(first, str)
            or not isinstance(second, str)
            or first == second
            or not isinstance(minimum, (int, float))
            or not isinstance(maximum, (int, float))
            or not math.isfinite(float(minimum))
            or not math.isfinite(float(maximum))
            or not 0 < float(minimum) < float(maximum)
            or not isinstance(authority, str)
            or not authority.strip()
            or identity in by_bond
        ):
            raise ProductPlacementError("malformed product ring bond safety record")
        by_bond[identity] = record
    if set(by_bond) != expected:
        raise ProductPlacementError(
            "placement safety bounds do not exactly cover the reviewed product ring"
        )
    records = []
    for identity in expected:
        record = by_bond[identity]
        first = record["atom_1"]
        second = record["atom_2"]
        if first not in coordinates or second not in coordinates:
            raise ProductPlacementError("placement safety references a missing template atom")
        distance_angstrom = 10.0 * _distance(coordinates[first], coordinates[second])
        passed = (
            float(record["minimum_angstrom"])
            <= distance_angstrom
            <= float(record["maximum_angstrom"])
        )
        records.append(
            {
                "atom_1": first,
                "atom_2": second,
                "distance_angstrom": distance_angstrom,
                "minimum_angstrom": float(record["minimum_angstrom"]),
                "maximum_angstrom": float(record["maximum_angstrom"]),
                "authority": record["authority"],
                "passed": passed,
            }
        )
    records.sort(key=lambda item: (item["atom_1"], item["atom_2"]))
    return {
        "passed": all(record["passed"] for record in records),
        "parameter_asset_sha256": parameter_hash,
        "bonds": records,
    }


def _segment_intersects_triangle(
    start: np.ndarray,
    end: np.ndarray,
    triangle: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    tolerance: float = 1e-8,
) -> bool:
    """Möller–Trumbore segment/triangle test, excluding boundary contacts."""

    first, second, third = triangle
    direction = end - start
    edge_1 = second - first
    edge_2 = third - first
    h = np.cross(direction, edge_2)
    determinant = float(np.dot(edge_1, h))
    if abs(determinant) <= tolerance:
        return False
    inverse = 1.0 / determinant
    s = start - first
    u = inverse * float(np.dot(s, h))
    if u <= tolerance or u >= 1.0 - tolerance:
        return False
    q = np.cross(s, edge_1)
    v = inverse * float(np.dot(direction, q))
    if v <= tolerance or u + v >= 1.0 - tolerance:
        return False
    along = inverse * float(np.dot(edge_2, q))
    return tolerance < along < 1.0 - tolerance


def _placement_relationship(endpoints: Sequence[ResolvedBase]) -> dict[str, str]:
    same_strand = bool(
        endpoints[0].strand_id
        and endpoints[0].strand_id == endpoints[1].strand_id
    )
    return {
        "strand_relationship": (
            "intrastrand" if same_strand else "interstrand"
        ),
        "extra_pairing": (
            "extra-extra"
            if all(endpoint.is_extra for endpoint in endpoints)
            else "native-native"
            if not any(endpoint.is_extra for endpoint in endpoints)
            else "extra-native"
        ),
    }


def place_product_template(
    *,
    atomistic_model: AtomisticModel,
    endpoints: Sequence[ResolvedBase],
    template: dict[str, Any],
    chemical_definition: dict[str, Any],
    expected_parameter_sha256: str,
    max_anchor_rmsd_nm: float = 0.12,
    max_glycosidic_error_nm: float = 0.04,
    max_base_displacement_nm: float = 0.35,
    minimum_clash_ratio: float = 0.50,
    allowed_template_statuses: frozenset[str] = frozenset({"released"}),
) -> tuple[AtomisticModel, dict[str, Any]]:
    """Fit a complete product template and run geometry safety audits.

    Only base heavy atoms move. Sugars/backbones and atom identity are preserved.
    The operation returns a copy and raises on any failed audit, so callers never
    receive a partially modified model.
    """

    if len(endpoints) != 2 or endpoints[0].key == endpoints[1].key:
        raise ProductPlacementError("placement requires two distinct ordered endpoints")
    if template.get("product_id") != chemical_definition.get("id"):
        raise ProductPlacementError("template and chemical-definition identities differ")
    coordinates = _template_coordinates(
        template, allowed_release_statuses=allowed_template_statuses
    )
    serial_to_index = {
        atom.serial: index for index, atom in enumerate(atomistic_model.atoms)
    }
    if len(serial_to_index) != len(atomistic_model.atoms):
        raise ProductPlacementError("atomistic model serials are not unique")
    for endpoint in endpoints:
        missing = _BASE_HEAVY_ATOMS - set(endpoint.atom_serials)
        if "C1'" not in endpoint.atom_serials:
            missing = {*missing, "C1'"}
        if missing:
            raise ProductPlacementError(
                f"endpoint {endpoint.key} lacks conserved atoms: "
                + ", ".join(sorted(missing))
            )

    anchor_names = ("C1'", "N1")
    source_anchors = np.asarray(
        [
            coordinates[f"{number}:{name}"]
            for number in (1, 2)
            for name in anchor_names
        ]
    )
    target_anchors = np.asarray(
        [
            np.asarray(endpoints[number - 1].atom_positions_nm[name], dtype=float)
            for number in (1, 2)
            for name in anchor_names
        ]
    )
    rotation, translation, anchor_rmsd = _proper_kabsch(source_anchors, target_anchors)
    transformed = {
        key: rotation @ point + translation for key, point in coordinates.items()
    }
    determinant = float(np.linalg.det(rotation))

    result = copy.deepcopy(atomistic_model)
    moved_serials: set[int] = set()
    displacements: list[float] = []
    for endpoint_number, endpoint in enumerate(endpoints, start=1):
        for name in sorted(_BASE_HEAVY_ATOMS):
            serial = endpoint.atom_serials[name]
            try:
                atom = result.atoms[serial_to_index[serial]]
            except KeyError as exc:
                raise ProductPlacementError(
                    f"endpoint atom serial {serial} is absent from the atomistic model"
                ) from exc
            target = transformed[f"{endpoint_number}:{name}"]
            displacements.append(_distance((atom.x, atom.y, atom.z), target))
            atom.x, atom.y, atom.z = map(float, target)
            atom.is_modified = True
            moved_serials.add(serial)

    glycosidic_errors: list[dict[str, Any]] = []
    for endpoint_number, endpoint in enumerate(endpoints, start=1):
        c1 = np.asarray(endpoint.atom_positions_nm["C1'"], dtype=float)
        placed_n1 = transformed[f"{endpoint_number}:N1"]
        expected = _distance(
            coordinates[f"{endpoint_number}:C1'"],
            coordinates[f"{endpoint_number}:N1"],
        )
        observed = _distance(c1, placed_n1)
        glycosidic_errors.append(
            {
                "endpoint": endpoint_number,
                "expected_nm": expected,
                "observed_nm": observed,
                "absolute_error_nm": abs(observed - expected),
            }
        )

    transformed_angstrom = {
        key: [float(value * 10.0) for value in point]
        for key, point in transformed.items()
    }
    chirality = audit_product_chirality(chemical_definition, transformed_angstrom)
    ring_bond_audit = _product_ring_bond_audit(
        template=template,
        chemical_definition=chemical_definition,
        coordinates=transformed,
        expected_parameter_sha256=expected_parameter_sha256,
    )

    neighbors: dict[int, set[int]] = {serial: set() for serial in serial_to_index}
    for first_serial, second_serial in result.bonds:
        if first_serial not in neighbors or second_serial not in neighbors:
            raise ProductPlacementError("atomistic bond references an unknown atom serial")
        neighbors[first_serial].add(second_serial)
        neighbors[second_serial].add(first_serial)
    excluded_nonbonded: set[frozenset[int]] = set()
    for origin in neighbors:
        frontier = {origin}
        visited = {origin}
        for _depth in range(3):
            frontier = {
                attached
                for serial in frontier
                for attached in neighbors[serial]
                if attached not in visited
            }
            visited.update(frontier)
            excluded_nonbonded.update(
                frozenset((origin, attached)) for attached in frontier
            )
    clashes: list[dict[str, Any]] = []
    for moved_serial in sorted(moved_serials):
        moved = result.atoms[serial_to_index[moved_serial]]
        for other in result.atoms:
            if (
                other.serial in moved_serials
                or frozenset((moved_serial, other.serial)) in excluded_nonbonded
            ):
                continue
            distance = _distance(
                (moved.x, moved.y, moved.z), (other.x, other.y, other.z)
            )
            radius_sum = VDW_RADIUS.get(moved.element, 0.16) + VDW_RADIUS.get(
                other.element, 0.16
            )
            ratio = distance / radius_sum
            if ratio < minimum_clash_ratio:
                clashes.append(
                    {
                        "moved_serial": moved_serial,
                        "other_serial": other.serial,
                        "distance_nm": distance,
                        "vdw_ratio": ratio,
                    }
                )

    ring_keys = _ordered_product_ring_keys(chemical_definition)
    ring = [transformed[key] for key in ring_keys]
    triangles = ((ring[0], ring[1], ring[2]), (ring[0], ring[2], ring[3]))
    piercings: list[dict[str, int]] = []
    for first_serial, second_serial in result.bonds:
        if first_serial in moved_serials or second_serial in moved_serials:
            continue
        if first_serial not in serial_to_index or second_serial not in serial_to_index:
            raise ProductPlacementError("atomistic bond references an unknown atom serial")
        first = result.atoms[serial_to_index[first_serial]]
        second = result.atoms[serial_to_index[second_serial]]
        start = np.asarray((first.x, first.y, first.z))
        end = np.asarray((second.x, second.y, second.z))
        if any(
            _segment_intersects_triangle(start, end, triangle)
            for triangle in triangles
        ):
            piercings.append(
                {"atom_1_serial": first_serial, "atom_2_serial": second_serial}
            )

    max_displacement = max(displacements, default=0.0)
    maximum_glycosidic_error = max(
        (item["absolute_error_nm"] for item in glycosidic_errors), default=math.inf
    )
    passed = all(
        (
            anchor_rmsd <= max_anchor_rmsd_nm,
            maximum_glycosidic_error <= max_glycosidic_error_nm,
            max_displacement <= max_base_displacement_nm,
            chirality["passed"],
            ring_bond_audit["passed"],
            not clashes,
            not piercings,
        )
    )
    report = {
        "schema": "nadoc.cpd-product-placement.v1",
        "status": "passed" if passed else "rejected",
        "passed": passed,
        "coordinates_modified": passed,
        "endpoint_keys": [endpoint.key for endpoint in endpoints],
        "product": chemical_definition["product"],
        "stereochemistry": chemical_definition["stereochemistry"],
        "relationship": _placement_relationship(endpoints),
        "template_version": template.get("version"),
        "fit": {
            "method": "four-anchor proper-rotation Kabsch; no reflection",
            "rotation_determinant": determinant,
            "anchor_rmsd_nm": anchor_rmsd,
            "max_anchor_rmsd_nm": max_anchor_rmsd_nm,
            "max_base_displacement_nm": max_displacement,
            "allowed_max_base_displacement_nm": max_base_displacement_nm,
        },
        "glycosidic_bond_audit": glycosidic_errors,
        "allowed_max_glycosidic_error_nm": max_glycosidic_error_nm,
        "chirality_audit": chirality,
        "product_ring_bond_audit": ring_bond_audit,
        "clash_audit": {
            "minimum_vdw_ratio": minimum_clash_ratio,
            "count": len(clashes),
            "clashes": clashes,
        },
        "piercing_audit": {
            "ring_atom_cycle": list(ring_keys),
            "count": len(piercings),
            "piercings": piercings,
        },
        "atom_count_before": len(atomistic_model.atoms),
        "atom_count_after": len(result.atoms),
        "bond_graph_unchanged": result.bonds == atomistic_model.bonds,
        "template_provenance": template["provenance"],
    }
    if not passed:
        raise ProductPlacementError(
            "product placement rejected: "
            + json.dumps(
                {
                    "anchor_rmsd_nm": anchor_rmsd,
                    "max_displacement_nm": max_displacement,
                    "max_glycosidic_error_nm": maximum_glycosidic_error,
                    "chirality_passed": chirality["passed"],
                    "product_ring_bonds_passed": ring_bond_audit["passed"],
                    "clash_count": len(clashes),
                    "piercing_count": len(piercings),
                },
                sort_keys=True,
            ),
            report=report,
        )
    return result, report


def select_product_template_assignment(
    *,
    atomistic_model: AtomisticModel,
    endpoints: Sequence[ResolvedBase],
    template: dict[str, Any],
    chemical_definition: dict[str, Any],
    expected_parameter_sha256: str,
) -> tuple[list[ResolvedBase], AtomisticModel, dict[str, Any]]:
    """Evaluate both directional endpoint assignments and choose deterministically.

    Improper signs and anti-product connectivity make patch order chemically meaningful.
    Failed placements remain diagnostics; ties are resolved only by canonical base-key
    order after comparing geometry scores. No reflection is ever introduced.
    """

    if len(endpoints) != 2 or endpoints[0].key == endpoints[1].key:
        raise ProductPlacementError(
            "assignment selection requires two distinct resolved endpoints"
        )
    candidates = []
    successful = []
    for ordered_tuple in permutations(endpoints):
        ordered = list(ordered_tuple)
        keys = [endpoint.key for endpoint in ordered]
        try:
            placed, report = place_product_template(
                atomistic_model=atomistic_model,
                endpoints=ordered,
                template=template,
                chemical_definition=chemical_definition,
                expected_parameter_sha256=expected_parameter_sha256,
            )
        except ProductPlacementError as exc:
            candidates.append(
                {
                    "endpoint_keys": keys,
                    "status": "rejected",
                    "reason": str(exc),
                    "placement_report": exc.report,
                }
            )
            continue
        score = (
            float(report["fit"]["anchor_rmsd_nm"]),
            float(report["fit"]["max_base_displacement_nm"]),
            tuple(keys),
        )
        candidate = {
            "endpoint_keys": keys,
            "status": "passed",
            "score": {
                "anchor_rmsd_nm": score[0],
                "maximum_base_displacement_nm": score[1],
                "canonical_tiebreak": keys,
            },
        }
        candidates.append(candidate)
        successful.append((score, ordered, placed, report))
    if not successful:
        raise ProductPlacementError(
            "neither directional endpoint/template assignment passed placement safety audits",
            report={
                "schema": "nadoc.photoproduct-assignment-selection.v1",
                "status": "rejected",
                "candidates": candidates,
            },
        )
    _score, ordered, placed, report = min(successful, key=lambda item: item[0])
    report["assignment_selection"] = {
        "schema": "nadoc.photoproduct-assignment-selection.v1",
        "status": "passed",
        "method": (
            "both directional released-template placements; anchor RMSD then maximum "
            "base displacement then canonical-key tie break"
        ),
        "selected_endpoint_keys": [endpoint.key for endpoint in ordered],
        "reflection_allowed": False,
        "candidates": candidates,
    }
    return ordered, placed, report


def build_cpd_product_coordinates(design, atomistic_model):
    """Apply all released photoproduct templates after the central capability gate."""

    assert_cpd_simulation_supported(design, path="TT-CPD coordinate builder")
    registry = photoproduct_registry()
    result = atomistic_model
    reports: list[dict[str, Any]] = []
    for lesion in design.photoproduct_junctions:
        if (
            lesion.orientation_method != "released-template-assignment-v1"
            or lesion.patch_order != "base-key-1-first"
        ):
            raise ProductPlacementError(
                "photoproduct orientation predates a released directional template; "
                "remove and recreate it through the current preflight before simulation"
            )
        entry = next(
            item
            for item in registry["products"]
            if item["product"] == lesion.product
            and item["stereochemistry"] == lesion.stereochemistry
        )
        record = entry["assets"]["coordinate_template"]
        template_path = (REGISTRY_PATH.parent / record["path"]).resolve()
        if _sha256(template_path) != record["sha256"]:
            raise ProductPlacementError(
                "coordinate-template digest changed after capability audit"
            )
        template = json.loads(template_path.read_text())
        endpoints, errors = resolve_base_keys(
            design,
            [lesion.base_key_1, lesion.base_key_2],
            atomistic_model=result,
        )
        if errors or len(endpoints) != 2:
            raise ProductPlacementError(
                f"photoproduct endpoint identity is stale: {errors}"
            )
        definition = load_chemical_definition(
            lesion.product, lesion.stereochemistry
        )
        result, report = place_product_template(
            atomistic_model=result,
            endpoints=endpoints,
            template=template,
            chemical_definition=definition,
            expected_parameter_sha256=entry["assets"]["parameters"]["sha256"],
        )
        reports.append(report)
    return result, reports
