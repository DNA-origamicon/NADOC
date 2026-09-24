"""Independent structural screen for the isolated chirality-constrained seed."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.audit_boundary_seeds import read_outputs, volume
from experiments.cpd_drude_recovery.campaign import source, checked, write
from backend.parameterization.photoproduct_models import (
    _expected_boundary_bond_orders,
    _covalent_bond_radius_ratio_range,
    _minimum_nonbonded_covalent_ratio,
    audit_product_chirality,
)


def main(root):
    p = root / "policy.json"
    policy = json.loads(p.read_text())
    manifest_path = checked(policy["source"])
    manifest = json.loads(manifest_path.read_text())
    paths, names, initial, mol, bonds = read_outputs(manifest_path, manifest)
    refpath = checked(policy["reference"])
    ref = json.loads(refpath.read_text())
    _, refnames, refxyz, _, _ = read_outputs(refpath, ref)
    xyz = np.loadtxt(root / "candidate_coordinates_angstrom.txt")
    assert xyz.shape == initial.shape and np.isfinite(xyz).all()
    definition_path = checked(manifest["chemical_definition"])
    definition = json.loads(definition_path.read_text())
    actual = {
        tuple(sorted((names[b.GetBeginAtomIdx()], names[b.GetEndAtomIdx()]))): float(
            b.GetBondTypeAsDouble()
        )
        for b in mol.GetBonds()
    }
    expected = _expected_boundary_bond_orders(definition)
    elements = [a.GetSymbol() for a in mol.GetAtoms()]
    bond_min, bond_max = _covalent_bond_radius_ratio_range(mol, xyz, elements)
    contact = _minimum_nonbonded_covalent_ratio(mol, xyz, elements)
    sugar = []
    for row in policy["sugar_constraints"]:
        before = volume(refxyz, refnames, row["ordered"])
        after = volume(xyz, names, row["ordered"])
        sugar.append(
            {
                "center": row["center"],
                "source_volume": before,
                "candidate_volume": after,
                "preserved": bool(
                    np.sign(before) == np.sign(after) and abs(after) > 1e-8
                ),
            }
        )
    lesion = audit_product_chirality(definition, dict(zip(names, xyz.tolist())))
    glyco = [
        float(
            np.linalg.norm(xyz[names.index(f"{e}:C1'")] - xyz[names.index(f"{e}:N1")])
        )
        for e in (1, 2)
    ]
    cross = [
        float(
            np.linalg.norm(
                xyz[names.index(b["atom_1"])] - xyz[names.index(b["atom_2"])]
            )
        )
        for b in definition["graph_delta"]["bonds_added"]
    ]
    fixed = [names.index(n) for n in policy["fixed_atom_names"]]
    fixed_error = float(abs(xyz[fixed] - initial[fixed]).max())
    limits_path = Path(
        "backend/data/forcefield/photoproduct_flexible_boundary_seed_policy_v1.json"
    )
    limits = json.loads(limits_path.read_text())["thresholds"]
    numerical = json.loads((root / "assessment.json").read_text())

    def inside(values, key):
        return all(
            limits[key]["minimum"] <= v <= limits[key]["maximum"] for v in values
        )

    checks = {
        "exact_graph_and_orders": actual == expected,
        "charge_minus_one": Chem.GetFormalCharge(mol) == -1,
        "all_sugar_stereocenters": all(r["preserved"] for r in sugar),
        "all_lesion_stereocenters": lesion["passed"],
        "fixed_core": fixed_error
        <= limits["fixed_product_core_maximum_displacement_angstrom"],
        "glycosidic_bonds": inside(glyco, "glycosidic_bond_length_angstrom"),
        "crosslinks": inside(cross, "product_crosslink_distance_angstrom"),
        "covalent_bonds": inside([bond_min, bond_max], "covalent_bond_radius_ratio"),
        "nonbonded_contacts": contact
        >= limits["minimum_nonbonded_covalent_radius_ratio"],
        "numerical_convergence": numerical["optimizer_success"]
        and numerical["lagrangian_gradient_max"] <= 1e-4
        and numerical["maximum_constraint_violation"] <= 1e-8
        and numerical["dual_multiplier_violation"] <= 1e-8,
    }
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "passed_starting_geometry_screen": all(checks.values()),
        "checks": checks,
        "sugar_stereochemistry": sugar,
        "lesion_stereochemistry": lesion,
        "glycosidic_distances_angstrom": glyco,
        "crosslink_distances_angstrom": cross,
        "covalent_radius_ratio_range": [bond_min, bond_max],
        "minimum_nonbonded_covalent_radius_ratio": contact,
        "fixed_core_max_displacement_angstrom": fixed_error,
        "scope": "Isolated QM-starting-geometry screen only. UFF charge warning retained; no QM, Drude-transfer, NAMD or interstrand-weld validation.",
        "sources": [
            source(v)
            for v in [
                p,
                root / "assessment.json",
                root / "candidate_coordinates_angstrom.txt",
                manifest_path,
                refpath,
                definition_path,
                limits_path,
                Path(__file__),
            ]
        ],
    }
    write(root / "independent_structural_audit.json", report)
    print(
        json.dumps(
            {"checks": checks, "glycosidic": glyco, "contact": contact}, indent=2
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root.resolve())
