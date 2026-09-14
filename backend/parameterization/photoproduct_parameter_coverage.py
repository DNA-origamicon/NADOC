"""Audit CHARMM parameter coverage for explicit photoproduct type hypotheses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from backend.parameterization.charmm_reference import REFERENCE_MANIFEST_PATH
from backend.parameterization.photoproduct_terms import (
    build_term_inventory,
    enumerate_graph_terms,
)

_COVERAGE_HYPOTHESES_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "forcefield"
    / "photoproduct_parameter_coverage_hypotheses.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_charmm_bonded_parameters(path: Path) -> list[dict[str, Any]]:
    """Parse bond/angle/dihedral/improper records while retaining source text."""

    section = None
    widths = {"bonds": 2, "angles": 3, "dihedrals": 4, "impropers": 4}
    headers = {
        "BONDS": "bonds",
        "ANGLES": "angles",
        "DIHEDRALS": "dihedrals",
        "DIHEDRAL": "dihedrals",
        "IMPROPER": "impropers",
        "IMPROPERS": "impropers",
    }
    stop = {"CMAP", "NONBONDED", "NBFIX", "HBOND", "END"}
    records = []
    for line_number, raw in enumerate(
        path.read_text(errors="replace").splitlines(), start=1
    ):
        content = raw.split("!", 1)[0].strip()
        if not content:
            continue
        fields = content.split()
        keyword = fields[0].upper()
        if keyword in headers and len(fields) == 1:
            section = headers[keyword]
            continue
        if keyword in stop:
            section = None
            continue
        if section is None:
            continue
        width = widths[section]
        if len(fields) <= width:
            continue
        try:
            values = [float(value) for value in fields[width:]]
        except ValueError:
            continue
        records.append(
            {
                "category": section,
                "types": fields[:width],
                "values": values,
                "source": str(path.resolve()),
                "line_number": line_number,
                "raw": raw.strip(),
            }
        )
    if not records:
        raise ValueError(f"no CHARMM bonded parameters parsed from {path}")
    return records


def _matches(pattern: list[str], actual: list[str]) -> bool:
    return all(
        expected == "X" or expected == observed
        for expected, observed in zip(pattern, actual, strict=True)
    )


def match_charmm_parameter(
    records: Iterable[dict[str, Any]], category: str, atom_types: list[str]
) -> list[dict[str, Any]]:
    """Return all highest-specificity forward/reverse CHARMM matches."""

    matches = []
    reverse = list(reversed(atom_types))
    for record in records:
        if record["category"] != category:
            continue
        pattern = record["types"]
        if _matches(pattern, atom_types) or _matches(pattern, reverse):
            matches.append((sum(value != "X" for value in pattern), record))
    if not matches:
        return []
    specificity = max(item[0] for item in matches)
    return [record for score, record in matches if score == specificity]


def audit_photoproduct_parameter_coverage(
    *,
    atom_type_plan_path: Path,
    hypotheses_path: Path,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path,
    output_path: Path,
    reference_manifest_path: Path = REFERENCE_MANIFEST_PATH,
    coverage_hypotheses_path: Path = _COVERAGE_HYPOTHESES_PATH,
) -> dict[str, Any]:
    """Show exactly which local terms transfer and which still require fitting."""

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite parameter coverage audit: {output_path}"
        )
    plan = json.loads(atom_type_plan_path.read_text())
    hypotheses = json.loads(hypotheses_path.read_text())
    coverage_hypotheses = json.loads(coverage_hypotheses_path.read_text())
    references = json.loads(reference_manifest_path.read_text())
    if (
        plan.get("schema") != "nadoc.photoproduct-atom-type-candidate-plan.v1"
        or hypotheses.get("schema") != "nadoc.photoproduct-nonbonded-fit-hypotheses.v1"
        or plan.get("product_id") != hypotheses.get("product_id")
    ):
        raise ValueError("atom-type plan and hypotheses are incompatible")
    expected_cgenff = references["cgenff_reference_library"]["parameters_sha256"]
    expected_na = references["base_forcefield"]["parameters"]["sha256"]
    if _sha256(cgenff_parameters_path) != expected_cgenff:
        raise ValueError("CGenFF parameter file differs from the pinned release")
    if _sha256(nucleic_parameters_path) != expected_na:
        raise ValueError("nucleic-acid parameter file differs from the pinned release")
    records = [
        *parse_charmm_bonded_parameters(cgenff_parameters_path),
        *parse_charmm_bonded_parameters(nucleic_parameters_path),
    ]
    inventory = build_term_inventory("TT-CPD", "cis-syn")
    type_plan = {item["model_atom"]: item for item in plan["atoms"]}
    if (
        coverage_hypotheses.get("schema")
        != "nadoc.photoproduct-parameter-coverage-hypotheses.v1"
        or coverage_hypotheses.get("status") != "candidate_not_reviewed"
        or coverage_hypotheses.get("product_id") != plan.get("product_id")
        or coverage_hypotheses.get("boundary_source", {}).get("topology_sha256")
        != references["base_forcefield"]["topology"]["sha256"]
    ):
        raise ValueError(
            "parameter-coverage boundary hypotheses are not pinned/reviewable"
        )
    boundary_types = coverage_hypotheses.get("unchanged_boundary_types") or {}
    results = []
    for hypothesis in hypotheses["hypotheses"]:
        type_by_atom: dict[str, str] = {}
        for atom, item in type_plan.items():
            local = atom.split(":", 1)[1]
            if local in {"CM", "HCM1", "HCM2", "HCM3"}:
                continue
            if item["decision"] == "review_transfer_candidate":
                exact = [
                    candidate
                    for candidate in item["candidates"]
                    if candidate["environment_match"] == "exact_candidate"
                ]
                if len(exact) != 1:
                    raise ValueError(f"{atom}: exact type candidate is ambiguous")
                type_by_atom[atom] = exact[0]["source_type"]
            else:
                if local not in hypothesis["unresolved_type_sources"]:
                    raise ValueError(f"{atom}: hypothesis lacks an unresolved type")
                type_by_atom[atom] = hypothesis["unresolved_type_sources"][local]
        for atom in {
            atom
            for category in ("bonds", "angles", "dihedrals")
            for path in inventory["all_local_terms_requiring_type_or_parameter_audit"][
                category
            ]
            for atom in path
            if atom not in type_by_atom
        }:
            local = atom.split(":", 1)[1]
            if local not in boundary_types:
                raise ValueError(f"no explicit unchanged boundary type for {atom}")
            type_by_atom[atom] = boundary_types[local]
        categories = {}
        total_missing = 0
        for category in ("bonds", "angles", "dihedrals"):
            terms = []
            for atom_path in inventory[
                "all_local_terms_requiring_type_or_parameter_audit"
            ][category]:
                atom_types = [type_by_atom[atom] for atom in atom_path]
                matched = match_charmm_parameter(records, category, atom_types)
                specificity = (
                    max(
                        sum(value != "X" for value in item["types"]) for item in matched
                    )
                    if matched
                    else None
                )
                terms.append(
                    {
                        "atoms": atom_path,
                        "types": atom_types,
                        "coverage": (
                            "exact" if specificity == len(atom_types) else "wildcard"
                        )
                        if matched
                        else "missing",
                        "matches": matched,
                    }
                )
            missing_count = sum(item["coverage"] == "missing" for item in terms)
            total_missing += missing_count
            categories[category] = {
                "term_count": len(terms),
                "exact_count": sum(item["coverage"] == "exact" for item in terms),
                "wildcard_count": sum(item["coverage"] == "wildcard" for item in terms),
                "missing_count": missing_count,
                "terms": terms,
            }
        results.append(
            {
                "hypothesis_id": hypothesis["id"],
                "atom_types": type_by_atom,
                "categories": categories,
                "total_missing_terms": total_missing,
                "improper_status": "four ordered product impropers still require review and fitting",
                "release_eligible": False,
            }
        )
    report = {
        "schema": "nadoc.photoproduct-parameter-coverage-audit.v1",
        "status": "coverage_audit_complete_not_releasable",
        "gate_effect": "none",
        "product_id": plan["product_id"],
        "sources": {
            "atom_type_plan": {
                "path": str(atom_type_plan_path.resolve()),
                "sha256": _sha256(atom_type_plan_path),
            },
            "hypotheses": {
                "path": str(hypotheses_path.resolve()),
                "sha256": _sha256(hypotheses_path),
            },
            "coverage_hypotheses": {
                "path": str(coverage_hypotheses_path.resolve()),
                "sha256": _sha256(coverage_hypotheses_path),
            },
            "cgenff_parameters": {
                "path": str(cgenff_parameters_path.resolve()),
                "sha256": _sha256(cgenff_parameters_path),
            },
            "nucleic_parameters": {
                "path": str(nucleic_parameters_path.resolve()),
                "sha256": _sha256(nucleic_parameters_path),
            },
        },
        "results": results,
        "release_blockers": [
            "fit every missing bond, angle, and proper-dihedral type",
            "define and fit four ordered stereochemical impropers",
            "validate transferred terms against QM geometry/Hessian/torsion targets",
            "independently review the final type assignment and all duplicate matches",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def audit_model_graph_parameter_coverage(
    *,
    model_manifest_path: Path,
    nonbonded_fit_path: Path,
    hypothesis_id: str,
    cgenff_parameters_path: Path,
    nucleic_parameters_path: Path | None = None,
    output_path: Path,
) -> dict[str, Any]:
    """Audit the complete capped-QM graph for one explicit type hypothesis.

    The lesion-local inventory is the right scope for a DNA patch.  An MM/QM fitting
    engine additionally needs every cap and unchanged model-compound term.  This audit
    expands the hash-linked model graph without selecting or inventing a missing term.
    """

    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite model parameter coverage audit: {output_path}"
        )
    manifest = json.loads(model_manifest_path.read_text())
    fit = json.loads(nonbonded_fit_path.read_text())
    if manifest.get("schema") != "nadoc.photoproduct-model-compound.v1":
        raise ValueError("unsupported model-compound manifest")
    graph_record = (manifest.get("outputs") or {}).get("graph")
    if not isinstance(graph_record, dict):
        raise ValueError("model manifest has no explicit graph artifact")
    graph_path = Path(graph_record.get("path", ""))
    if not graph_path.is_file() or _sha256(graph_path) != graph_record.get("sha256"):
        raise ValueError("model graph is missing or hash-mismatched")
    graph = json.loads(graph_path.read_text())
    atoms = graph.get("atoms") or []
    atom_keys = [item.get("key") for item in atoms]
    if (
        graph.get("schema") != "nadoc.photoproduct-model-graph.v1"
        or graph.get("atom_count") != len(atoms)
        or len(atom_keys) != len(set(atom_keys))
        or atom_keys != manifest.get("atom_map")
        or graph.get("formal_charge") != manifest.get("charge")
    ):
        raise ValueError("model graph identity, order, or charge is inconsistent")
    graph_bonds = graph.get("bonds") or []
    if graph.get("bond_count") != len(graph_bonds):
        raise ValueError("model graph bond count is inconsistent")
    for record in graph_bonds:
        indices = record.get("indices") or []
        keys = record.get("atoms") or []
        if (
            len(indices) != 2
            or len(keys) != 2
            or any(
                not isinstance(index, int) or not 0 <= index < len(atom_keys)
                for index in indices
            )
            or keys != [atom_keys[index] for index in indices]
            or not isinstance(record.get("order"), (int, float))
        ):
            raise ValueError("model graph contains an invalid or stale bond record")
    if (
        fit.get("schema") != "nadoc.photoproduct-nonbonded-hypothesis-fit.v1"
        or fit.get("product_id") != manifest.get("product_id")
        or fit.get("model_id") != manifest.get("model_id")
    ):
        raise ValueError("nonbonded fit does not match the model manifest")
    result = next(
        (
            item
            for item in fit.get("results") or []
            if item.get("hypothesis_id") == hypothesis_id
        ),
        None,
    )
    if result is None:
        raise ValueError(f"nonbonded fit has no hypothesis {hypothesis_id!r}")
    types_by_atom = result.get("atom_types") or {}
    charges_by_atom = result.get("charges_e") or {}
    if set(types_by_atom) != set(atom_keys) or set(charges_by_atom) != set(atom_keys):
        raise ValueError("selected fit does not exactly cover the model graph")
    if (
        abs(
            sum(float(charges_by_atom[key]) for key in atom_keys)
            - float(graph["formal_charge"])
        )
        > 1e-8
    ):
        raise ValueError("selected fit charges do not conserve model charge")
    expected_parameter_hash = (
        (fit.get("source_records") or {}).get("cgenff_parameters") or {}
    ).get("sha256")
    actual_parameter_hash = _sha256(cgenff_parameters_path)
    if expected_parameter_hash != actual_parameter_hash:
        raise ValueError("CGenFF parameters differ from the nonbonded fit evidence")

    records = parse_charmm_bonded_parameters(cgenff_parameters_path)
    nucleic_parameter_hash = None
    if nucleic_parameters_path is not None:
        references = json.loads(REFERENCE_MANIFEST_PATH.read_text())
        nucleic_parameter_hash = _sha256(nucleic_parameters_path)
        if (
            nucleic_parameter_hash
            != references["base_forcefield"]["parameters"]["sha256"]
        ):
            raise ValueError("nucleic-acid parameters do not match the pinned release")
        records.extend(parse_charmm_bonded_parameters(nucleic_parameters_path))
    terms = enumerate_graph_terms([record["atoms"] for record in graph_bonds])
    categories = {}
    total_missing = 0
    for category in ("bonds", "angles", "dihedrals"):
        term_records = []
        for atom_path in terms[category]:
            atom_types = [types_by_atom[key] for key in atom_path]
            matches = match_charmm_parameter(records, category, atom_types)
            specificity = (
                max(sum(value != "X" for value in match["types"]) for match in matches)
                if matches
                else None
            )
            term_records.append(
                {
                    "atoms": atom_path,
                    "types": atom_types,
                    "coverage": (
                        "exact" if specificity == len(atom_types) else "wildcard"
                    )
                    if matches
                    else "missing",
                    "matches": matches,
                }
            )
        missing_count = sum(item["coverage"] == "missing" for item in term_records)
        total_missing += missing_count
        categories[category] = {
            "term_count": len(term_records),
            "exact_count": sum(item["coverage"] == "exact" for item in term_records),
            "wildcard_count": sum(
                item["coverage"] == "wildcard" for item in term_records
            ),
            "missing_count": missing_count,
            "terms": term_records,
        }
    report = {
        "schema": "nadoc.photoproduct-model-parameter-coverage-audit.v1",
        "status": "coverage_audit_complete_not_releasable",
        "gate_effect": "none",
        "product_id": manifest["product_id"],
        "model_id": manifest["model_id"],
        "hypothesis_id": hypothesis_id,
        "atom_count": len(atom_keys),
        "bond_count": len(graph_bonds),
        "model_charge_e": sum(float(charges_by_atom[key]) for key in atom_keys),
        "categories": categories,
        "total_missing_terms": total_missing,
        "sources": {
            "model_manifest": {
                "path": str(model_manifest_path.resolve()),
                "sha256": _sha256(model_manifest_path),
            },
            "model_graph": {
                "path": str(graph_path.resolve()),
                "sha256": graph_record["sha256"],
            },
            "nonbonded_fit": {
                "path": str(nonbonded_fit_path.resolve()),
                "sha256": _sha256(nonbonded_fit_path),
            },
            "cgenff_parameters": {
                "path": str(cgenff_parameters_path.resolve()),
                "sha256": actual_parameter_hash,
            },
            "nucleic_parameters": (
                {
                    "path": str(nucleic_parameters_path.resolve()),
                    "sha256": nucleic_parameter_hash,
                }
                if nucleic_parameters_path is not None
                else None
            ),
        },
        "release_blockers": [
            "fit every missing model-compound bond, angle, and proper-dihedral type",
            "define the complete reviewed improper list, including four product stereocenters",
            "optimize against coupled QM forces/Hessian and independent conformers",
            "transfer only reviewed DNA-scope terms into the final lesion patch",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
