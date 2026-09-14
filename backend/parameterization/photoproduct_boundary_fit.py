"""Materialize full d(TpT) QM evidence as stable, fit-ready model inputs.

The Alpine boundary campaigns intentionally retain the screened construction model,
optimized coordinates, and frequency job as separate immutable records.  This module
joins those records only after their hashes and chemical identities agree.  It assigns
no atom types, charges, or bonded parameters and therefore has no release-gate effect.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Sequence

from backend.core.photoproduct_chemistry import (
    chemical_definition_asset,
    load_chemical_definition,
)
from backend.core.photoproduct_registry import photoproduct_registry
from backend.parameterization.photoproduct_hessian import build_hessian_target_bundle
from backend.parameterization.photoproduct_models import _expected_boundary_bond_orders
from backend.parameterization.photoproduct_qm import parse_xyz


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _checked_source(record: object, label: str) -> Path:
    if not isinstance(record, dict):
        raise ValueError(f"{label} source record is missing")
    path = Path(str(record.get("path") or ""))
    if not path.is_file() or _sha256(path) != record.get("sha256"):
        raise ValueError(f"{label} source is missing or hash-mismatched")
    return path.resolve()


def _registry_entry(product_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in photoproduct_registry()["products"]
        if item.get("id") == product_id
    ]
    if len(matches) != 1:
        raise ValueError(f"boundary model has no unique registry product {product_id!r}")
    return matches[0]


def _graph_from_sdf(
    sdf_path: Path,
    atom_map: list[str],
    *,
    product_id: str,
) -> dict[str, Any]:
    """Read one V2000 SDF without changing its reviewed bond perception.

    A small fixed-column reader is preferable here to asking a cheminformatics toolkit
    to sanitize or reperceive a deliberately strained fused ring.  V3000 and aromatic
    bond encodings fail closed because boundary builders currently emit V2000 with
    explicit single/double orders.
    """

    lines = sdf_path.read_text(errors="strict").splitlines()
    if len(lines) < 4 or "V2000" not in lines[3] or "$$$$" not in lines:
        raise ValueError("screened boundary SDF must contain one V2000 molecule")
    if lines.count("$$$$") != 1:
        raise ValueError("screened boundary SDF must contain exactly one molecule")
    try:
        atom_count = int(lines[3][0:3])
        bond_count = int(lines[3][3:6])
    except (ValueError, IndexError) as exc:
        raise ValueError("screened boundary SDF has an invalid counts line") from exc
    if atom_count != len(atom_map) or len(atom_map) != len(set(atom_map)):
        raise ValueError("screened boundary SDF and stable atom map differ")
    if len(lines) < 4 + atom_count + bond_count:
        raise ValueError("screened boundary SDF is truncated")
    charge_codes = {0: 0, 1: 3, 2: 2, 3: 1, 5: -1, 6: -2, 7: -3}
    atoms = []
    for index, (line, key) in enumerate(
        zip(lines[4 : 4 + atom_count], atom_map, strict=True)
    ):
        try:
            element = line[31:34].strip()
            charge_code = int(line[36:39].strip() or "0")
            charge = charge_codes[charge_code]
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError("screened boundary SDF has an invalid atom record") from exc
        if not element:
            raise ValueError("screened boundary SDF has an atom without an element")
        atoms.append(
            {
                "index": index,
                "key": key,
                "element": element,
                "formal_charge": charge,
                "aromatic": False,
            }
        )
    property_start = 4 + atom_count + bond_count
    for line in lines[property_start:]:
        if not line.startswith("M  CHG"):
            continue
        fields = line.split()
        try:
            count = int(fields[2])
            pairs = fields[3:]
            if len(pairs) != 2 * count:
                raise ValueError
            for offset in range(0, len(pairs), 2):
                atom_index = int(pairs[offset]) - 1
                charge = int(pairs[offset + 1])
                if not 0 <= atom_index < atom_count:
                    raise ValueError
                atoms[atom_index]["formal_charge"] = charge
        except (ValueError, IndexError) as exc:
            raise ValueError("screened boundary SDF has an invalid M  CHG record") from exc

    bonds = []
    actual_orders: dict[tuple[str, str], float] = {}
    for line in lines[4 + atom_count : 4 + atom_count + bond_count]:
        try:
            first = int(line[0:3]) - 1
            second = int(line[3:6]) - 1
            order_code = int(line[6:9])
        except (ValueError, IndexError) as exc:
            raise ValueError("screened boundary SDF has an invalid bond record") from exc
        if not (0 <= first < atom_count and 0 <= second < atom_count):
            raise ValueError("screened boundary SDF bond index is out of range")
        if order_code not in {1, 2}:
            raise ValueError("screened boundary SDF must use explicit single/double bonds")
        if first > second:
            first, second = second, first
        pair = tuple(sorted((atom_map[first], atom_map[second])))
        order = float(order_code)
        if pair in actual_orders:
            raise ValueError("screened boundary SDF has a duplicate bond")
        actual_orders[pair] = order
        bonds.append(
            {
                "atoms": [atom_map[first], atom_map[second]],
                "indices": [first, second],
                "order": order,
                "aromatic": False,
            }
        )
    bonds.sort(key=lambda item: tuple(item["indices"]))

    entry = _registry_entry(product_id)
    definition = load_chemical_definition(
        entry["product"], entry["stereochemistry"]
    )
    expected_orders = _expected_boundary_bond_orders(definition)
    if set(actual_orders) != set(expected_orders) or any(
        abs(actual_orders[pair] - float(order)) > 1e-8
        for pair, order in expected_orders.items()
    ):
        raise ValueError("screened boundary SDF does not encode the exact product graph")

    graph = {
        "schema": "nadoc.photoproduct-model-graph.v1",
        "atom_count": len(atoms),
        "bond_count": len(bonds),
        "formal_charge": sum(item["formal_charge"] for item in atoms),
        "atoms": atoms,
        "bonds": bonds,
    }
    if graph["atom_count"] != 63 or graph["formal_charge"] != -1:
        raise ValueError("full d(TpT) boundary graph must have 63 atoms and charge -1")
    return graph


def materialize_boundary_fit_model(
    *,
    screened_model_path: Path,
    optimization_job_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Join one screened d(TpT) graph to its audited optimized coordinates."""

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite boundary fit model: {output_dir}")
    screened = json.loads(screened_model_path.read_text())
    job_path = optimization_job_dir / "job_manifest.json"
    audit_path = optimization_job_dir / "optimized_model_audit.json"
    optimized_path = optimization_job_dir / "optimized.xyz"
    if not all(path.is_file() for path in (job_path, audit_path, optimized_path)):
        raise ValueError("optimization job, audit, and optimized XYZ are required")
    job = json.loads(job_path.read_text())
    audit = json.loads(audit_path.read_text())
    identity = (screened.get("product_id"), screened.get("model_id"))
    if (
        screened.get("schema")
        != "nadoc.photoproduct-dna-boundary-model-candidate.v1"
        or screened.get("status") != "quantitatively_screened_boundary"
        or screened.get("simulation_ready") is not False
        or screened.get("gate_effect") != "none"
        or job.get("schema") != "nadoc.photoproduct-qm-job.v1"
        or job.get("job_kind") != "geometry_optimization"
        or (job.get("product_id"), job.get("model_id")) != identity
        or audit.get("schema") != "nadoc.photoproduct-optimized-model-audit.v1"
        or audit.get("status") != "passed_identity_and_chirality"
        or (audit.get("product_id"), audit.get("model_id")) != identity
        or job.get("charge") != -1
        or job.get("multiplicity") != 1
        or job.get("atom_count") != 63
    ):
        raise ValueError("screened model and optimization evidence are incompatible")
    job_model = job.get("model_manifest") or {}
    if (
        Path(str(job_model.get("path") or "")).resolve()
        != screened_model_path.resolve()
        or job_model.get("sha256") != _sha256(screened_model_path)
    ):
        raise ValueError("optimization job is not hash-linked to the screened model")
    if (
        audit.get("optimized_xyz", {}).get("sha256") != _sha256(optimized_path)
        or not audit.get("chirality_audit", {}).get("passed")
        or audit.get("coordinates_finite") is not True
    ):
        raise ValueError("optimized model does not pass its coordinate/chirality audit")

    atom_map_path = _checked_source(screened.get("outputs", {}).get("atom_map"), "atom map")
    sdf_path = _checked_source(screened.get("outputs", {}).get("sdf"), "boundary SDF")
    atom_map = json.loads(atom_map_path.read_text())
    if atom_map != job.get("atom_map") or atom_map != screened.get("atom_map"):
        raise ValueError("screened and optimized stable atom identities differ")
    optimized_atoms, _comment = parse_xyz(optimized_path.read_text())
    if len(optimized_atoms) != len(atom_map):
        raise ValueError("optimized XYZ and stable atom map differ")
    graph = _graph_from_sdf(sdf_path, atom_map, product_id=str(identity[0]))
    if [item["element"] for item in graph["atoms"]] != [
        item[0] for item in optimized_atoms
    ]:
        raise ValueError("optimized XYZ element order differs from the screened graph")

    entry = _registry_entry(str(identity[0]))
    expected_definition = chemical_definition_asset(
        entry["product"], entry["stereochemistry"]
    )
    screened_definition = screened.get("chemical_definition") or {}
    if screened_definition.get("sha256") != expected_definition["sha256"]:
        raise ValueError("screened model chemical definition is stale")

    output_dir.mkdir(parents=True)
    local_xyz = output_dir / "optimized.xyz"
    local_map = output_dir / "atom_map.json"
    local_sdf = output_dir / "model_graph.sdf"
    graph_path = output_dir / "model_graph.json"
    shutil.copyfile(optimized_path, local_xyz)
    shutil.copyfile(atom_map_path, local_map)
    shutil.copyfile(sdf_path, local_sdf)
    graph_path.write_text(json.dumps(graph, indent=2) + "\n")

    report = {
        "schema": "nadoc.photoproduct-model-compound.v1",
        "status": "optimized_full_boundary_fit_input",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_id": identity[0],
        "model_id": identity[1],
        "product": entry["product"],
        "stereochemistry": entry["stereochemistry"],
        "charge": -1,
        "multiplicity": 1,
        "atom_count": 63,
        "atom_map": atom_map,
        "outputs": {
            "xyz": _source(local_xyz),
            "atom_map": _source(local_map),
            "sdf": _source(local_sdf),
            "graph": _source(graph_path),
        },
        "sources": {
            "screened_boundary_model": _source(screened_model_path),
            "optimization_job": _source(job_path),
            "optimization_audit": _source(audit_path),
            "chemical_definition": expected_definition,
        },
        "fit_scope": {
            "purpose": "full_dTpT_QM_target_and_boundary_transfer_validation",
            "parameters_assigned": False,
            "charges_assigned": False,
            "release_eligible": False,
        },
    }
    manifest_path = output_dir / "model_manifest.json"
    manifest_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def build_boundary_fit_input_campaign(
    *,
    optimization_campaign_roots: Sequence[Path],
    frequency_campaign_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Materialize all eight model graphs and Hessian bundles after Alpine QM."""

    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite boundary fit campaign: {output_root}")
    expected_ids = {
        item["id"]
        for item in photoproduct_registry()["products"]
        if item.get("product") == "TT-CPD"
    }
    optimization_by_product: dict[str, tuple[Path, dict[str, Any]]] = {}
    optimization_sources = []
    for root in optimization_campaign_roots:
        collection_path = root / "collection_report.json"
        collection = json.loads(collection_path.read_text())
        if (
            collection.get("schema")
            != "nadoc.photoproduct-alpine-boundary-optimization-collection.v1"
            or collection.get("status") != "passed_import_and_identity_audit"
            or collection.get("passed_product_count") != collection.get("product_count")
        ):
            raise ValueError(f"optimization collection is not passed: {collection_path}")
        optimization_sources.append(_source(collection_path))
        for record in collection.get("products") or []:
            product_id = str(record.get("product_id") or "")
            if product_id in optimization_by_product:
                raise ValueError(f"duplicate optimization product {product_id!r}")
            optimization_by_product[product_id] = (root, record)

    frequency_collection_path = frequency_campaign_root / "collection_report.json"
    frequency = json.loads(frequency_collection_path.read_text())
    frequency_ids = {
        str(record.get("product_id") or "") for record in frequency.get("products") or []
    }
    if (
        set(optimization_by_product) != expected_ids
        or frequency.get("schema")
        != "nadoc.photoproduct-alpine-boundary-frequency-collection.v1"
        or frequency.get("status") != "passed_harmonic_minimum_audits"
        or frequency.get("passed_product_count") != len(expected_ids)
        or frequency_ids != expected_ids
    ):
        raise ValueError("all eight matching optimization/frequency products are required")

    # Validate every cross-campaign link before creating any output.
    plans = []
    for product_id in sorted(expected_ids):
        optimization_root, optimization_record = optimization_by_product[product_id]
        optimization_job_dir = optimization_root / "bundle/cases" / product_id / "job"
        optimization_audit = _checked_source(
            optimization_record.get("optimized_model_audit"),
            f"{product_id} optimization audit",
        )
        if optimization_audit != (optimization_job_dir / "optimized_model_audit.json").resolve():
            raise ValueError(f"{product_id}: optimization audit escapes its campaign case")
        optimization_job = json.loads((optimization_job_dir / "job_manifest.json").read_text())
        screened_model_path = _checked_source(
            optimization_job.get("model_manifest"), f"{product_id} screened model"
        )
        frequency_job_dir = frequency_campaign_root / "bundle/cases" / product_id / "job"
        frequency_job = json.loads((frequency_job_dir / "job_manifest.json").read_text())
        if (
            frequency_job.get("parent_manifest", {}).get("sha256")
            != _sha256(optimization_audit)
            or frequency_job.get("source_xyz", {}).get("sha256")
            != _sha256(optimization_job_dir / "optimized.xyz")
            or frequency_job.get("atom_map") != optimization_job.get("atom_map")
        ):
            raise ValueError(f"{product_id}: frequency and optimization lineage differ")
        plans.append(
            (product_id, screened_model_path, optimization_job_dir, frequency_job_dir)
        )

    output_root.mkdir(parents=True)
    records = []
    for product_id, screened_model_path, optimization_job_dir, frequency_job_dir in plans:
        product_root = output_root / product_id
        model_dir = product_root / "model"
        model = materialize_boundary_fit_model(
            screened_model_path=screened_model_path,
            optimization_job_dir=optimization_job_dir,
            output_dir=model_dir,
        )
        hessian_path = product_root / "hessian_targets.json"
        hessian = build_hessian_target_bundle(
            frequency_job_dir=frequency_job_dir,
            output_path=hessian_path,
        )
        if (
            hessian.get("product_id") != product_id
            or hessian.get("model_id") != model.get("model_id")
            or hessian.get("status") != "complete_candidate_evidence"
            or hessian.get("atom_map") != model.get("atom_map")
        ):
            raise ValueError(f"{product_id}: materialized model and Hessian targets differ")
        records.append(
            {
                "product_id": product_id,
                "model_id": model["model_id"],
                "model_manifest": _source(model_dir / "model_manifest.json"),
                "hessian_targets": _source(hessian_path),
            }
        )

    report = {
        "schema": "nadoc.photoproduct-boundary-fit-input-campaign.v1",
        "status": "passed_fit_input_materialization",
        "gate_effect": "none",
        "simulation_ready": False,
        "product_count": len(records),
        "products": records,
        "sources": {
            "optimization_collections": optimization_sources,
            "frequency_collection": _source(frequency_collection_path),
        },
        "next_required_steps": [
            "fit lesion-local charges while holding the CHARMM36 sugar/phosphate boundary fixed",
            "audit complete CHARMM term coverage for each exact product identity",
            "fit bonded terms against minimum and independent response/conformer targets",
        ],
    }
    index_path = output_root / "campaign_manifest.json"
    index_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
