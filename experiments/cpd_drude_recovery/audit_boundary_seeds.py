"""Re-audit archived sugar-attached anti seeds independently of UFF screening."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_qm import parse_xyz


def read_outputs(manifest_path, manifest):
    paths = {}
    for key, record in manifest["outputs"].items():
        candidate = Path(record["path"])
        if not candidate.exists():
            candidate = manifest_path.parent / candidate.name
        paths[key] = checked({**record, "path": str(candidate)})
    names = json.loads(paths["atom_map"].read_text())
    xyz = np.array([a[1:] for a in parse_xyz(paths["xyz"].read_text())[0]])
    mol = Chem.SDMolSupplier(str(paths["sdf"]), removeHs=False)[0]
    if mol is None or mol.GetNumAtoms() != len(names) or len(xyz) != len(names):
        raise ValueError("Invalid atom correspondence")
    bonds = {
        tuple(sorted((names[b.GetBeginAtomIdx()], names[b.GetEndAtomIdx()])))
        for b in mol.GetBonds()
    }
    return paths, names, xyz, mol, bonds


def volume(xyz, names, ordered):
    a, b, c, d = xyz[[names.index(n) for n in ordered]]
    return float(np.dot(b - a, np.cross(c - a, d - a)))


def main(archive, stage, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    fit_plan_path = stage / "bonded_fit_plan.json"
    fit_plan = json.loads(fit_plan_path.read_text())
    rows = []
    for chain in ("chain-b", "chain-d"):
        path = archive / chain / "candidate_manifest.json"
        m = json.loads(path.read_text())
        assert m["product_id"] == "tt-cpd-cis-anti-i"
        checked(m["chemical_definition"])
        checked(m["quantitative_screening"]["policy_source"])
        paths, names, xyz, mol, bonds = read_outputs(path, m)
        ref_path = checked(m["source_selection"]["reference_manifest"])
        ref = json.loads(ref_path.read_text())
        ref_paths, ref_names, ref_xyz, ref_mol, ref_bonds = read_outputs(ref_path, ref)
        expected = set(ref_bonds)
        for pair in [("1:C5", "2:C5"), ("1:C6", "2:C6")]:
            expected.remove(tuple(sorted(pair)))
        for pair in [("1:C5", "2:C6"), ("1:C6", "2:C5")]:
            expected.add(tuple(sorted(pair)))
        sugar = []
        for endpoint in (1, 2):
            for center, ordered in [
                ("C1'", ["O4'", "C2'", "N1", "H1'"]),
                ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
                ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
            ]:
                ordered = [f"{endpoint}:{n}" for n in ordered]
                before = volume(ref_xyz, ref_names, ordered)
                after = volume(xyz, names, ordered)
                sugar.append(
                    {
                        "center": f"{endpoint}:{center}",
                        "reference_volume": before,
                        "seed_volume": after,
                        "preserved": bool(
                            np.sign(before) == np.sign(after) and abs(after) > 1e-8
                        ),
                    }
                )
        lesion = []
        for c in fit_plan["stereochemical_impropers"]:
            v = volume(xyz, names, c["ordered_atoms_candidate"])
            lesion.append(
                {
                    "center": c["stereocenter"],
                    "volume": v,
                    "preserved": bool(
                        np.sign(v) == np.sign(c["observed_signed_volume"])
                    ),
                }
            )
        checks = {
            "atom_identities": set(names) == set(ref_names),
            "expected_nuclear_graph": bonds == expected,
            "charge_minus_one": Chem.GetFormalCharge(mol) == -1,
            "sugar_stereochemistry": all(c["preserved"] for c in sugar),
            "lesion_stereochemistry": all(c["preserved"] for c in lesion),
        }
        rows.append(
            {
                "chain": chain,
                "checks": checks,
                "structural_seed_checks_passed": all(checks.values()),
                "atom_count": len(names),
                "bond_count": len(bonds),
                "sugar_stereocenters": sugar,
                "lesion_stereocenters": lesion,
                "missing_bonds": sorted(expected - bonds),
                "extra_bonds": sorted(bonds - expected),
                "sources": [
                    source(p)
                    for p in [path, ref_path, *paths.values(), *ref_paths.values()]
                ],
            }
        )
    write(
        root / "assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "Archived UFF starting-geometry structural audit, not QM minima, charges, Drude transfer, or intended interstrand connectivity validation. Source is a covalently linked d(TpT) context.",
            "sources": [source(fit_plan_path), source(root / "source_snapshot.py")],
            "records": rows,
        },
    )
    for r in rows:
        print(r["chain"], r["checks"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for n in ("archive", "stage", "root"):
        p.add_argument("--" + n, type=Path, required=True)
    a = p.parse_args()
    main(a.archive.resolve(), a.stage.resolve(), a.root.resolve())
