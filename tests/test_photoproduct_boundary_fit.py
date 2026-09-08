import hashlib
import json
from pathlib import Path

from backend.core.photoproduct_chemistry import (
    chemical_definition_asset,
    load_chemical_definition,
)
from backend.parameterization.photoproduct_boundary_fit import (
    materialize_boundary_fit_model,
)
from backend.parameterization.photoproduct_models import (
    _expected_boundary_bond_orders,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _element(key: str) -> str:
    local = key.split(":", 1)[1]
    if local.startswith("H"):
        return "H"
    return local[0]


def _write_exact_boundary_sdf(path: Path, atom_map: list[str], bonds) -> None:
    index = {key: position for position, key in enumerate(atom_map)}
    lines = [
        "NADOC test boundary",
        "  NADOC",
        "",
        f"{len(atom_map):>3}{len(bonds):>3}  0  0  0  0  0  0  0  0999 V2000",
    ]
    for key in atom_map:
        lines.append(
            f"    0.0000    0.0000    0.0000 {_element(key):<3}"
            " 0  0  0  0  0  0  0  0  0  0  0  0"
        )
    for (first, second), order in bonds.items():
        lines.append(
            f"{index[first] + 1:>3}{index[second] + 1:>3}{int(order):>3}"
            "  0  0  0  0"
        )
    lines.extend([f"M  CHG  1{index['2:OP1'] + 1:>4}  -1", "M  END", "$$$$"])
    path.write_text("\n".join(lines) + "\n")


def test_materializes_hash_linked_noncanonical_boundary_fit_model(tmp_path: Path):
    product_id = "tt-cpd-trans-syn-i"
    product = "TT-CPD"
    stereochemistry = "trans-syn-I"
    model_id = f"{product_id}-dtpdt-test"
    definition = load_chemical_definition(product, stereochemistry)
    bonds = _expected_boundary_bond_orders(definition)
    atom_map = sorted({atom for pair in bonds for atom in pair})
    assert len(atom_map) == 63

    source = tmp_path / "source"
    source.mkdir()
    atom_map_path = source / "atom_map.json"
    atom_map_path.write_text(json.dumps(atom_map) + "\n")
    sdf_path = source / "candidate.sdf"
    _write_exact_boundary_sdf(sdf_path, atom_map, bonds)
    screened_path = source / "screened.json"
    screened = {
        "schema": "nadoc.photoproduct-dna-boundary-model-candidate.v1",
        "status": "quantitatively_screened_boundary",
        "simulation_ready": False,
        "gate_effect": "none",
        "product_id": product_id,
        "model_id": model_id,
        "atom_map": atom_map,
        "chemical_definition": chemical_definition_asset(product, stereochemistry),
        "outputs": {
            "atom_map": {"path": str(atom_map_path), "sha256": _sha256(atom_map_path)},
            "sdf": {"path": str(sdf_path), "sha256": _sha256(sdf_path)},
        },
    }
    screened_path.write_text(json.dumps(screened, indent=2) + "\n")

    job_dir = tmp_path / "optimization-job"
    job_dir.mkdir()
    optimized = job_dir / "optimized.xyz"
    optimized.write_text(
        f"{len(atom_map)}\ntest optimized boundary\n"
        + "".join(
            f"{_element(key)} {position * 0.1:.4f} 0.0 0.0\n"
            for position, key in enumerate(atom_map)
        )
    )
    job = {
        "schema": "nadoc.photoproduct-qm-job.v1",
        "job_kind": "geometry_optimization",
        "product_id": product_id,
        "model_id": model_id,
        "charge": -1,
        "multiplicity": 1,
        "atom_count": 63,
        "atom_map": atom_map,
        "model_manifest": {
            "path": str(screened_path),
            "sha256": _sha256(screened_path),
        },
    }
    (job_dir / "job_manifest.json").write_text(json.dumps(job, indent=2) + "\n")
    audit = {
        "schema": "nadoc.photoproduct-optimized-model-audit.v1",
        "status": "passed_identity_and_chirality",
        "product_id": product_id,
        "model_id": model_id,
        "optimized_xyz": {"path": str(optimized), "sha256": _sha256(optimized)},
        "coordinates_finite": True,
        "chirality_audit": {"passed": True},
    }
    (job_dir / "optimized_model_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n"
    )

    report = materialize_boundary_fit_model(
        screened_model_path=screened_path,
        optimization_job_dir=job_dir,
        output_dir=tmp_path / "fit-model",
    )

    assert report["product_id"] == product_id
    assert report["stereochemistry"] == stereochemistry
    assert report["atom_count"] == 63
    assert report["charge"] == -1
    assert report["fit_scope"]["parameters_assigned"] is False
    graph = json.loads(Path(report["outputs"]["graph"]["path"]).read_text())
    assert graph["formal_charge"] == -1
    assert graph["bond_count"] == len(bonds)
    assert len(
        [
            item
            for item in graph["bonds"]
            if set(item["atoms"]) in ({"1:C5", "2:C5"}, {"1:C6", "2:C6"})
        ]
    ) == 2
