"""Audit relaxed-ring native outputs without treating geometry as force-field validation."""

import argparse
import importlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, checked, write, audit_graph
from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral


def geometry_checks(xyz, reference, names, bonds, stereo, indices, target):
    xyz = np.asarray(xyz, dtype=float)
    if xyz.shape != reference.shape or not np.isfinite(xyz).all():
        raise ValueError("Invalid relaxed geometry")
    index = {n: i for i, n in enumerate(names)}
    angle = _dihedral(*xyz[indices])
    delta = (angle - target + 180) % 360 - 180
    stereochemistry = []
    for item in stereo:
        a, b, c, d = xyz[[index[n] for n in item["ordered_atoms_candidate"]]]
        volume = float(np.dot(b - a, np.cross(c - a, d - a)))
        stereochemistry.append(
            {
                "center": item["stereocenter"],
                "volume_angstrom3": volume,
                "preserved": bool(
                    np.sign(volume) == np.sign(item["observed_signed_volume"])
                ),
            }
        )
    rows = []
    for a, b in bonds:
        r = float(np.linalg.norm(xyz[a] - xyz[b]))
        r0 = float(np.linalg.norm(reference[a] - reference[b]))
        rows.append(
            {
                "atoms": [names[a], names[b]],
                "reference_angstrom": r0,
                "relaxed_angstrom": r,
                "change_angstrom": r - r0,
            }
        )
    return {
        "dihedral_degrees": angle,
        "constraint_error_degrees": delta,
        "constraint_satisfied": abs(delta) <= 0.001,
        "stereocenters": stereochemistry,
        "all_stereo_preserved": all(r["preserved"] for r in stereochemistry),
        "bonds": rows,
        "maximum_reference_bond_change_angstrom": max(
            abs(r["change_angstrom"]) for r in rows
        ),
    }


def main(root, recovery, stage):
    plan_path = root / "plan.json"
    plan = json.loads(plan_path.read_text())
    checked(plan["worker"])
    checked(plan["source_scan_plan"])
    sys.path.insert(0, str(recovery))
    d = importlib.import_module("drude_model")
    assert Path(d.__file__).resolve().parent == recovery
    registry_path = Path("backend/data/forcefield/photoproduct_registry.json")
    graph = audit_graph(d.ATOM_NAMES, d._bonds(), json.loads(registry_path.read_text()))
    reference = np.array(
        [
            [float(v) for v in l.split()[1:]]
            for l in plan["molecule"].splitlines()
            if len(l.split()) == 4
        ]
    )
    fit_plan_path = stage / "bonded_fit_plan.json"
    fit_plan = json.loads(fit_plan_path.read_text())
    records = []
    missing = []
    sources = [
        source(p)
        for p in (
            plan_path,
            fit_plan_path,
            registry_path,
            Path(d.__file__),
            Path(__file__),
        )
    ]
    for case in plan["cases"]:
        folder = root / case["id"]
        result_path = folder / "result.json"
        if not result_path.exists():
            missing.append(case["id"])
            continue
        result = json.loads(result_path.read_text())
        if (
            result["case_id"] != case["id"]
            or result["plan_sha256"] != source(plan_path)["sha256"]
            or result["psi4_version"] != "1.11"
        ):
            raise ValueError("QM result provenance mismatch")
        native = (folder / "output.dat").read_text()
        if (
            "Final optimized geometry and variables:" not in native
            or "DF-MP2" not in native
        ):
            raise ValueError(
                "Missing native constrained-optimization completion evidence"
            )
        energy = float(result["energy_hartree"])
        if not np.isfinite(energy):
            raise ValueError("Nonfinite energy")
        checks = geometry_checks(
            result["geometry_angstrom"],
            reference,
            d.ATOM_NAMES,
            d._bonds(),
            fit_plan["stereochemical_impropers"],
            plan["indices_zero_based"],
            case["target_degrees"],
        )
        if abs(checks["dihedral_degrees"] - result["final_dihedral_degrees"]) > 1e-6:
            raise ValueError("Independent dihedral mismatch")
        records.append({"case_id": case["id"], "energy_hartree": energy, **checks})
        sources.extend([source(result_path), source(folder / "output.dat")])
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Constrained-QM execution, torsion, reference bond-change and chirality audit. Bond changes are diagnostic, not a new force-field gate; no inferred bond-order or solution validation.",
        "status": "complete_geometry_audit"
        if not missing
        else "incomplete_geometry_audit",
        "missing_cases": missing,
        "graph": graph,
        "records": records,
        "sources": sources,
    }
    write(root / "geometry_audit.json", report)
    print("Completed relaxed-ring audits", len(records), "missing", missing)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for n in ("root", "recovery", "stage"):
        p.add_argument("--" + n, type=Path, required=True)
    a = p.parse_args()
    main(a.root.resolve(), a.recovery.resolve(), a.stage.resolve())
