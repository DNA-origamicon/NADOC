"""Assemble audited CHARMM-style charge targets without inventing a fit.

The resulting bundle is an input to a later MM/QM optimizer. It cannot be released
until Lennard-Jones transfer choices and the objective/validation split are reviewed,
because model-water total interaction energies cannot be fitted as electrostatics alone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_hashed(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"required evidence is missing: {path}")
    return json.loads(path.read_text()), {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
    }


def _structured_charge_constraints(
    atom_map: list[str], total_charge: int, endpoint_pairs: list[list[str]]
) -> dict[str, Any]:
    methyl_groups = [
        [f"{endpoint}:HCM1", f"{endpoint}:HCM2", f"{endpoint}:HCM3"]
        for endpoint in (1, 2)
    ] + [
        [f"{endpoint}:H51", f"{endpoint}:H52", f"{endpoint}:H53"]
        for endpoint in (1, 2)
    ]
    required = {
        key
        for group in methyl_groups
        for key in group
    } | {f"{endpoint}:CM" for endpoint in (1, 2)}
    missing = sorted(required - set(atom_map))
    if missing:
        raise ValueError("stable atom map is missing charge-constraint atoms: " + ", ".join(missing))
    return {
        "total_charge": {"atoms": atom_map, "value_e": total_charge},
        "neutral_n1_methyl_caps": [
            {
                "atoms": [f"{endpoint}:CM", *methyl_groups[endpoint - 1]],
                "value_e": 0.0,
            }
            for endpoint in (1, 2)
        ],
        "equal_charge_groups": [*methyl_groups, *endpoint_pairs],
        "endpoint_exchange_symmetry": {
            "enforced": True,
            "pairs": endpoint_pairs,
            "reason": (
                "audited constitutional-graph automorphism; point charges and Lennard-Jones "
                "types are invariant to R/S labels"
            ),
        },
    }


def build_charge_target_bundle(
    *,
    electrostatic_audit_path: Path,
    water_audit_paths: Sequence[Path],
    scf_calibration_audit_path: Path,
    stereo_candidate_audit_path: Path,
    esp_audit_path: Path | None = None,
    initial_charge_guess_path: Path,
    atom_map_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Combine dipole/water targets and charge constraints into a hash-linked bundle."""

    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite charge target bundle: {output_path}")
    electrostatic, electrostatic_record = _load_hashed(electrostatic_audit_path)
    calibration, calibration_record = _load_hashed(scf_calibration_audit_path)
    stereo_audit, stereo_audit_record = _load_hashed(stereo_candidate_audit_path)
    esp_record = None
    if esp_audit_path is not None:
        esp, esp_record = _load_hashed(esp_audit_path)
        if (
            esp.get("schema") != "nadoc.photoproduct-esp-audit.v1"
            or esp.get("status") != "complete_candidate"
            or not esp.get("passed")
            or (esp.get("product_id"), esp.get("model_id"))
            != (electrostatic.get("product_id"), electrostatic.get("model_id"))
        ):
            raise ValueError("ESP target audit is not a complete matching candidate")
    initial, initial_record = _load_hashed(initial_charge_guess_path)
    atom_map_payload, atom_map_record = _load_hashed(atom_map_path)
    if not isinstance(atom_map_payload, list):
        raise ValueError("atom map must be a JSON list")
    atom_map = atom_map_payload
    if len(atom_map) != len(set(atom_map)):
        raise ValueError("atom map contains duplicate stable keys")
    if (
        electrostatic.get("schema")
        != "nadoc.photoproduct-electrostatic-properties-audit.v1"
        or electrostatic.get("status") != "complete_candidate"
        or not electrostatic.get("passed")
    ):
        raise ValueError("electrostatic target audit has not passed")
    if (
        calibration.get("schema")
        != "nadoc.photoproduct-water-scf-calibration-audit.v1"
        or not calibration.get("passed")
    ):
        raise ValueError("DF/DIRECT water SCF calibration has not passed")
    stereo_record = next(
        (
            item
            for item in stereo_audit.get("candidates") or []
            if item.get("product_id") == electrostatic.get("product_id")
        ),
        None,
    )
    graph_audit = (stereo_record or {}).get("graph_audit") or {}
    endpoint_pairs = graph_audit.get("charge_symmetry_pairs") or []
    if (
        stereo_audit.get("schema") != "nadoc.tt-cpd-stereo-candidate-audit.v1"
        or stereo_audit.get("status") != "passed_candidate"
        or not isinstance(stereo_record, dict)
        or not stereo_record.get("passed")
        or graph_audit.get("endpoint_exchange_graph_symmetry_ignoring_chirality") is not True
        or len(endpoint_pairs) * 2 != len(atom_map)
    ):
        raise ValueError("endpoint charge symmetry lacks a passed constitutional-graph audit")
    if (
        initial.get("schema") != "nadoc.photoproduct-initial-charge-guess.v1"
        or initial.get("status") != "initial_guess_not_fitted"
    ):
        raise ValueError("initial charge guess is missing or already misclassified")
    identity = (electrostatic.get("product_id"), electrostatic.get("model_id"))
    if (initial.get("product_id"), initial.get("model_id")) != identity:
        raise ValueError("initial charges and electrostatic target identities differ")
    initial_atoms = {item.get("model_atom") for item in initial.get("atoms") or []}
    if initial_atoms != set(atom_map) or len(initial.get("atoms") or []) != len(atom_map):
        raise ValueError("initial charges do not exactly cover the stable atom map")

    water_targets = []
    water_records = []
    seen_sites: set[str] = set()
    expected_sites = {
        f"endpoint{endpoint}-{site}"
        for endpoint in (1, 2)
        for site in ("o2-acceptor", "o4-acceptor", "h3-donor")
    }
    for path in water_audit_paths:
        audit, record = _load_hashed(path)
        site = (audit.get("identity") or {}).get("probe_id")
        if (
            audit.get("schema")
            != "nadoc.photoproduct-water-interaction-series-audit.v1"
            or audit.get("status") != "complete_candidate"
            or not audit.get("passed")
            or (
                (audit.get("identity") or {}).get("product_id"),
                (audit.get("identity") or {}).get("model_id"),
            )
            != identity
            or site in seen_sites
        ):
            raise ValueError(f"water target is incomplete, mismatched, or duplicate: {path}")
        seen_sites.add(site)
        points = audit.get("points") or []
        minimum_index = audit.get("minimum_point_index")
        if not isinstance(minimum_index, int) or not 0 < minimum_index < len(points) - 1:
            raise ValueError(f"water target minimum is not bracketed: {site}")
        water_targets.append(
            {
                "site_id": site,
                "target_atom": audit["identity"]["target_atom"],
                "probe_atom": audit["identity"]["probe_atom"],
                "points": points,
                "minimum_point_index": minimum_index,
            }
        )
        water_records.append(record)
    if seen_sites != expected_sites:
        raise ValueError(
            "water targets must cover both O2/O4 acceptors and H3 donors: "
            + ", ".join(sorted(seen_sites))
        )
    total_charge = int(round(float(initial.get("initial_total_charge"))))
    constraints = _structured_charge_constraints(atom_map, total_charge, endpoint_pairs)
    report = {
        "schema": "nadoc.photoproduct-charge-target-bundle.v1",
        "status": "targets_complete_fit_blocked",
        "gate_effect": "none",
        "product_id": identity[0],
        "model_id": identity[1],
        "atom_map": atom_map,
        "initial_charges": initial.get("atoms"),
        "constraints": constraints,
        "targets": {
            "qm_dipole_au": electrostatic.get("dipole_au"),
            "water_interaction_curves": sorted(
                water_targets, key=lambda item: item["site_id"]
            ),
            "proposed_split": {
                "training_sites": sorted(site for site in seen_sites if site.startswith("endpoint1-")),
                "held_out_validation_sites": sorted(
                    site for site in seen_sites if site.startswith("endpoint2-")
                ),
                "rationale": "test endpoint transfer under the audited charge-symmetry mapping",
            },
        },
        "evidence": {
            "electrostatic_audit": electrostatic_record,
            "water_audits": water_records,
            "water_scf_calibration": calibration_record,
            "stereo_candidate_audit": stereo_audit_record,
            "esp_audit": esp_record,
            "initial_charge_guess": initial_record,
            "atom_map": atom_map_record,
        },
        "fit_blockers": [
            "review and freeze atom types plus Lennard-Jones transfer sources",
            "evaluate the same total interaction energies with CHARMM electrostatics and Lennard-Jones terms",
            "freeze objective weights, regularization, and a held-out validation split",
            *(
                []
                if esp_record is not None
                else ["generate a deterministic surface electrostatic-potential target"]
            ),
        ],
        "scientific_warning": (
            "QM model-water values are total interaction energies. Fitting point charges "
            "without the selected Lennard-Jones contribution would be chemically invalid."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
