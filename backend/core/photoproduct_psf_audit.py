"""Chemical completeness audit for a patched photoproduct PSF."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any, Iterable, Sequence

from backend.core.photoproduct_registry import photoproduct_registry


@dataclass(frozen=True, slots=True)
class PsfAtom:
    index: int
    segid: str
    resid: str
    resname: str
    name: str
    atom_type: str
    charge: float
    mass: float

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.segid, self.resid, self.name


def _header_index(lines: list[str], marker: str) -> tuple[int, int]:
    matches = [
        (index, line)
        for index, line in enumerate(lines)
        if marker in line
    ]
    if len(matches) != 1:
        raise ValueError(f"PSF must contain exactly one {marker} section")
    line_index, line = matches[0]
    try:
        count = int(line.split()[0])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"malformed {marker} header") from exc
    return line_index, count


def parse_psf_atoms(text: str) -> list[PsfAtom]:
    lines = text.splitlines()
    start, count = _header_index(lines, "!NATOM")
    atoms: list[PsfAtom] = []
    for line in lines[start + 1 :]:
        if len(atoms) == count:
            break
        fields = line.split()
        if not fields:
            continue
        if len(fields) < 8:
            raise ValueError("malformed PSF atom record")
        try:
            atom = PsfAtom(
                index=int(fields[0]),
                segid=fields[1],
                resid=fields[2],
                resname=fields[3],
                name=fields[4],
                atom_type=fields[5],
                charge=float(fields[6]),
                mass=float(fields[7]),
            )
        except ValueError as exc:
            raise ValueError("malformed numeric field in PSF atom record") from exc
        atoms.append(atom)
    if len(atoms) != count or [atom.index for atom in atoms] != list(range(1, count + 1)):
        raise ValueError("PSF atom count or ordering does not match !NATOM")
    return atoms


def parse_psf_index_section(text: str, marker: str, width: int) -> list[tuple[int, ...]]:
    lines = text.splitlines()
    start, count = _header_index(lines, marker)
    values: list[int] = []
    for line in lines[start + 1 :]:
        if len(values) == count * width:
            break
        if "!" in line:
            break
        for token in line.split():
            try:
                values.append(int(token))
            except ValueError as exc:
                raise ValueError(f"malformed integer in {marker} section") from exc
            if len(values) == count * width:
                break
    if len(values) != count * width:
        raise ValueError(f"{marker} count does not match its index data")
    return [tuple(values[index : index + width]) for index in range(0, len(values), width)]


def _canonical(path: Iterable[int]) -> tuple[int, ...]:
    value = tuple(path)
    reverse = tuple(reversed(value))
    return min(value, reverse)


def _graph_terms(bonds: Iterable[Sequence[int]]) -> dict[str, set[tuple[int, ...]]]:
    bond_set = {_canonical(pair) for pair in bonds}
    neighbors: dict[int, set[int]] = {}
    for first, second in bond_set:
        neighbors.setdefault(first, set()).add(second)
        neighbors.setdefault(second, set()).add(first)
    angles = {
        _canonical((first, center, second))
        for center, attached in neighbors.items()
        for first in attached
        for second in attached
        if first != second
    }
    dihedrals = {
        _canonical((outer_1, center_1, center_2, outer_2))
        for center_1, center_2 in bond_set
        for outer_1 in neighbors[center_1] - {center_2}
        for outer_2 in neighbors[center_2] - {center_1}
        if len({outer_1, center_1, center_2, outer_2}) == 4
    }
    return {"bonds": bond_set, "angles": angles, "dihedrals": dihedrals}


def _resolve_atom_reference(
    reference: str,
    patch: dict[str, Any],
    atom_by_identity: dict[tuple[str, str, str], PsfAtom],
) -> PsfAtom:
    endpoint_text, separator, atom_name = reference.partition(":")
    if not separator or not endpoint_text.isdigit() or not atom_name:
        raise ValueError(f"invalid topology-audit atom reference: {reference!r}")
    endpoint = next(
        (
            item
            for item in patch["endpoints"]
            if item["endpoint"] == int(endpoint_text)
        ),
        None,
    )
    if endpoint is None:
        raise ValueError(f"patch has no endpoint {endpoint_text}")
    identity = (endpoint["segid"], str(endpoint["resid"]), atom_name)
    try:
        return atom_by_identity[identity]
    except KeyError as exc:
        raise ValueError(f"patched PSF is missing atom {reference} at {identity[:2]}") from exc


def _resolved_path(
    references: Sequence[str],
    patch: dict[str, Any],
    atom_by_identity: dict[tuple[str, str, str], PsfAtom],
) -> tuple[int, ...]:
    return tuple(
        _resolve_atom_reference(reference, patch, atom_by_identity).index
        for reference in references
    )


def audit_photoproduct_psf(
    *,
    product_psf_text: str,
    reactant_psf_text: str,
    patch_plan: dict[str, Any],
    topology_specs: dict[str, dict[str, Any]],
    charge_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Compare product/reactant PSFs and prove the complete reviewed patch delta."""

    product_atoms = parse_psf_atoms(product_psf_text)
    reactant_atoms = parse_psf_atoms(reactant_psf_text)
    product_atom_by_identity = {atom.identity: atom for atom in product_atoms}
    reactant_atom_by_identity = {atom.identity: atom for atom in reactant_atoms}
    errors: list[str] = []
    registry_by_id = {
        item["id"]: item for item in photoproduct_registry()["products"]
    }
    if len(product_atom_by_identity) != len(product_atoms):
        errors.append("product PSF atom identities are not unique")
    if len(reactant_atom_by_identity) != len(reactant_atoms):
        errors.append("reactant PSF atom identities are not unique")
    if set(product_atom_by_identity) != set(reactant_atom_by_identity):
        errors.append("product and reactant PSFs do not conserve atom identity")
    if len(product_atoms) != len(reactant_atoms):
        errors.append("product and reactant PSFs do not conserve atom count")
    product_charge = sum(atom.charge for atom in product_atoms)
    reactant_charge = sum(atom.charge for atom in reactant_atoms)
    if not math.isclose(product_charge, reactant_charge, abs_tol=charge_tolerance):
        errors.append("product and reactant PSFs do not conserve total charge")

    sections = {
        "bonds": ("!NBOND", 2),
        "angles": ("!NTHETA", 3),
        "dihedrals": ("!NPHI", 4),
        "impropers": ("!NIMPHI", 4),
    }
    parsed_product = {
        name: parse_psf_index_section(product_psf_text, marker, width)
        for name, (marker, width) in sections.items()
    }
    parsed_reactant = {
        name: parse_psf_index_section(reactant_psf_text, marker, width)
        for name, (marker, width) in sections.items()
    }
    for name in ("bonds", "angles", "dihedrals"):
        canonical = [_canonical(path) for path in parsed_product[name]]
        if any(count != 1 for count in Counter(canonical).values()):
            errors.append(f"product PSF contains duplicate {name}")

    expected_added_bonds: set[tuple[int, ...]] = set()
    expected_added_impropers: set[tuple[int, ...]] = set()
    expected_removed_impropers: set[tuple[int, ...]] = set()
    lesion_reports: list[dict[str, Any]] = []
    if not patch_plan.get("patches"):
        errors.append("photoproduct patch plan contains no lesions")
    for patch in patch_plan.get("patches", []):
        spec = topology_specs.get(patch["product_id"])
        if not isinstance(spec, dict) or spec.get("schema") != (
            "nadoc.photoproduct-topology-audit-spec.v1"
        ):
            errors.append(f"{patch['product_id']}: missing topology audit specification")
            continue
        if spec.get("product_id") != patch["product_id"]:
            errors.append(f"{patch['product_id']}: topology audit specification mismatch")
            continue
        lesion_errors: list[str] = []
        product_atoms_spec = spec.get("expected_product_atoms") or []
        crosslinks_spec = spec.get("crosslinks") or []
        impropers_added_spec = spec.get("impropers_added") or []
        if not product_atoms_spec:
            lesion_errors.append("audit specification declares no product atom types/charges")
        required_ring_atoms = {
            f"{endpoint}:{atom_name}"
            for endpoint in (1, 2)
            for atom_name in ("C5", "C6")
        }
        declared_atoms = {item.get("atom") for item in product_atoms_spec}
        if not required_ring_atoms.issubset(declared_atoms):
            lesion_errors.append(
                "audit specification omits one or more C5/C6 product atom types/charges"
            )
        if len(crosslinks_spec) != 2:
            lesion_errors.append(
                "TT-CPD audit specification must declare exactly two covalent crosslinks"
            )
        registry_entry = registry_by_id.get(patch["product_id"])
        if registry_entry is None:
            lesion_errors.append("patch product is absent from the photoproduct registry")
        else:
            declared_crosslinks = {frozenset(item) for item in crosslinks_spec}
            required_crosslinks = {
                frozenset(item.split("--"))
                for item in registry_entry["graph_delta"]["bonds_added"]
            }
            if declared_crosslinks != required_crosslinks:
                lesion_errors.append(
                    f"{patch['product_id']} crosslinks do not match its ordered registry graph"
                )
        if len(impropers_added_spec) < 4:
            lesion_errors.append(
                "TT-CPD audit specification must declare at least four stereochemical "
                "product impropers"
            )
        endpoint_identities = {
            (endpoint["segid"], str(endpoint["resid"]))
            for endpoint in patch["endpoints"]
        }
        product_pair_charge = sum(
            atom.charge
            for atom in product_atoms
            if (atom.segid, atom.resid) in endpoint_identities
        )
        reactant_pair_charge = sum(
            atom.charge
            for atom in reactant_atoms
            if (atom.segid, atom.resid) in endpoint_identities
        )
        if not math.isclose(
            product_pair_charge, reactant_pair_charge, abs_tol=charge_tolerance
        ):
            lesion_errors.append("ordered endpoint pair charge is not conserved")
        for expected in product_atoms_spec:
            atom = _resolve_atom_reference(
                expected["atom"], patch, product_atom_by_identity
            )
            if atom.atom_type != expected["type"]:
                lesion_errors.append(
                    f"{expected['atom']} type {atom.atom_type} != {expected['type']}"
                )
            if not math.isclose(
                atom.charge, float(expected["charge"]), abs_tol=charge_tolerance
            ):
                lesion_errors.append(
                    f"{expected['atom']} charge {atom.charge} != {expected['charge']}"
                )
        for references in crosslinks_spec:
            expected_added_bonds.add(
                _canonical(_resolved_path(references, patch, product_atom_by_identity))
            )
        for references in spec.get("retained_bonds", []):
            path = _canonical(
                _resolved_path(references, patch, product_atom_by_identity)
            )
            if path not in {_canonical(item) for item in parsed_product["bonds"]}:
                lesion_errors.append(f"retained product bond is missing: {references}")
        for references in impropers_added_spec:
            expected_added_impropers.add(
                _resolved_path(references, patch, product_atom_by_identity)
            )
        for references in spec.get("impropers_removed", []):
            expected_removed_impropers.add(
                _resolved_path(references, patch, product_atom_by_identity)
            )
        errors.extend(f"{patch['lesion_id']}: {message}" for message in lesion_errors)
        lesion_reports.append(
            {
                "lesion_id": patch["lesion_id"],
                "product_id": patch["product_id"],
                "endpoints": patch["endpoints"],
                "reactant_pair_charge": reactant_pair_charge,
                "product_pair_charge": product_pair_charge,
                "errors": lesion_errors,
            }
        )

    product_bonds = {_canonical(item) for item in parsed_product["bonds"]}
    reactant_bonds = {_canonical(item) for item in parsed_reactant["bonds"]}
    actual_added_bonds = product_bonds - reactant_bonds
    actual_removed_bonds = reactant_bonds - product_bonds
    if actual_added_bonds != expected_added_bonds:
        errors.append("PSF bond delta does not exactly match reviewed photoproduct crosslinks")
    if actual_removed_bonds:
        errors.append("photoproduct patch unexpectedly removed covalent bonds")

    expected_graph = _graph_terms([*reactant_bonds, *expected_added_bonds])
    reactant_graph = _graph_terms(reactant_bonds)
    for name in ("angles", "dihedrals"):
        product_terms = {_canonical(item) for item in parsed_product[name]}
        reactant_terms = {_canonical(item) for item in parsed_reactant[name]}
        actual_added = product_terms - reactant_terms
        actual_removed = reactant_terms - product_terms
        expected_added = expected_graph[name] - reactant_graph[name]
        if actual_added != expected_added:
            errors.append(f"regenerated {name} do not match the patched bond graph")
        if actual_removed:
            errors.append(f"photoproduct patch unexpectedly removed {name}")

    product_impropers = set(parsed_product["impropers"])
    reactant_impropers = set(parsed_reactant["impropers"])
    # A patch may intentionally DELETE and re-add the same ordered improper after
    # changing its atom types.  The PSF can prove its final presence but cannot
    # encode that command history as a set delta.  Treat exact overlap as a
    # replacement and continue to require all non-overlapping deltas exactly.
    expected_replaced_impropers = (
        expected_added_impropers & expected_removed_impropers
    )
    if not expected_replaced_impropers.issubset(product_impropers):
        errors.append("one or more replaced product impropers are absent")
    if product_impropers - reactant_impropers != (
        expected_added_impropers - expected_replaced_impropers
    ):
        errors.append("added impropers do not exactly match the reviewed specification")
    if reactant_impropers - product_impropers != (
        expected_removed_impropers - expected_replaced_impropers
    ):
        errors.append("removed impropers do not exactly match the reviewed specification")

    reverse_identity = patch_plan.get("reverse_identity", [])
    expected_reverse_count = 2 * len(patch_plan.get("patches", []))
    if len(reverse_identity) != expected_reverse_count or len(
        {(item["lesion_id"], item["endpoint"]) for item in reverse_identity}
    ) != expected_reverse_count:
        errors.append("reverse design-to-PSF identity mapping is incomplete or ambiguous")
    return {
        "schema": "nadoc.photoproduct-static-topology-audit.v1",
        "status": "passed" if not errors else "failed",
        "passed": not errors,
        "atom_count_conserved": len(product_atoms) == len(reactant_atoms),
        "reactant_atom_count": len(reactant_atoms),
        "product_atom_count": len(product_atoms),
        "reactant_total_charge": reactant_charge,
        "product_total_charge": product_charge,
        "expected_added_bonds": [list(item) for item in sorted(expected_added_bonds)],
        "actual_added_bonds": [list(item) for item in sorted(actual_added_bonds)],
        "actual_removed_bonds": [list(item) for item in sorted(actual_removed_bonds)],
        "expected_replaced_impropers": [
            list(item) for item in sorted(expected_replaced_impropers)
        ],
        "lesions": lesion_reports,
        "reverse_identity": reverse_identity,
        "errors": errors,
    }
