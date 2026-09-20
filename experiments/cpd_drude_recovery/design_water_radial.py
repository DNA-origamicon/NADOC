"""Freeze geometry-only radial extensions and quantify LJ sensitivity coverage."""

import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, checked, write


def main(prediction_root, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    policy_path = prediction_root / "policy.json"
    policy = json.loads(policy_path.read_text())
    batch_path = checked(policy["batch"])
    batch = json.loads(batch_path.read_text())
    names = list(policy["pairs"])
    index = {n: i for i, n in enumerate(names)}
    cases = []
    for case in batch["cases"]:
        if case["partition"] != "training":
            continue
        m = re.fullmatch(
            r"training-endpoint([12])-(o2|o4|h3)-(acceptor|donor)", case["id"]
        )
        if not m:
            raise ValueError("Unrecognized canonical training orientation")
        endpoint, atom, role = m.groups()
        solute = index[f"{endpoint}:{atom.upper()}"]
        lines = [
            l.split() for l in case["molecule"].splitlines() if len(l.split()) == 4
        ]
        xyz = np.array([[float(v) for v in l[1:]] for l in lines])
        assert xyz.shape == (39, 3)
        contact = (
            36
            if role == "donor"
            else min((37, 38), key=lambda j: np.linalg.norm(xyz[j] - xyz[solute]))
        )
        vector = xyz[contact] - xyz[solute]
        distance = float(np.linalg.norm(vector))
        assert abs(distance - 1.8) < 1e-8
        water_dist = np.linalg.norm(xyz[-3:, None, :] - xyz[None, -3:, :], axis=2)
        for target in (1.6, 1.8, 2.2, 2.6):
            proposed = xyz.copy()
            proposed[-3:] += (target - distance) * vector / distance
            assert np.max(abs(proposed[:36] - xyz[:36])) == 0
            assert (
                np.max(
                    abs(
                        np.linalg.norm(
                            proposed[-3:, None, :] - proposed[None, -3:, :], axis=2
                        )
                        - water_dist
                    )
                )
                < 1e-10
            )
            assert (
                abs(np.linalg.norm(proposed[contact] - proposed[solute]) - target)
                < 1e-10
            )
            cases.append(
                {
                    "id": f"{case['id']}-r{target:.1f}",
                    "source_case_id": case["id"],
                    "contact_distance_angstrom": target,
                    "solute_contact_atom": names[solute],
                    "water_contact_index": contact - 36,
                    "reuses_existing_geometry": target == 1.8,
                    "geometry_angstrom": proposed.tolist(),
                    "elements": [l[0] for l in lines],
                }
            )
    analyses = []
    for levels in ((1.8,), (1.8, 2.2), (1.6, 1.8, 2.2, 2.6)):
        for scheme, groups in [
            ("shared_carbonyl", {"carbonyl": ["O2", "O4"], "H3": ["H3"]}),
            ("split_carbonyl", {"O2": ["O2"], "O4": ["O4"], "H3": ["H3"]}),
        ]:
            jac = []
            for case in cases:
                if case["contact_distance_angstrom"] not in levels:
                    continue
                xyz = np.array(case["geometry_angstrom"])
                row = []
                for atoms in groups.values():
                    derivatives = np.zeros(2)
                    for i, name in enumerate(names):
                        if name.split(":")[1] not in atoms:
                            continue
                        pair = policy["pairs"][name]
                        six = (
                            pair["rmin_angstrom"] / np.linalg.norm(xyz[i] - xyz[36])
                        ) ** 6
                        eps = pair["epsilon_kcal_mol"]
                        derivatives += np.array(
                            [eps * (six**2 - 2 * six), 12 * eps * (six**2 - six)]
                        )
                    row.extend(derivatives)
                jac.append(row)
            jac = np.array(jac)
            norm = np.linalg.norm(jac, axis=0)
            sv = np.linalg.svd(jac / norm, compute_uv=False)
            analyses.append(
                {
                    "contact_distances_angstrom": levels,
                    "scheme": scheme,
                    "cases": len(jac),
                    "column_normalized_singular_values": sv.tolist(),
                    "condition_number": float(sv[0] / sv[-1]),
                }
            )
    write(
        root / "plan.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "qm_values_read": False,
            "execution_authorized_by_this_file": False,
            "scope": "Geometry-only candidate radial extension. Original CPD nuclei and rigid-water orientation/internal geometry retained, water translated along existing contact axis. No QM execution, no model fitting, no independent-validation assertion.",
            "source_batch": source(batch_path),
            "source_native_pairs": source(policy_path),
            "script": source(root / "source_snapshot.py"),
            "method_if_executed": "Existing unscaled counterpoise frozen-core DF-MP2/cc-pVQZ convention; no automatic lower-basis substitution.",
            "new_cases": 18,
            "existing_geometry_cases": 6,
            "cases": cases,
            "sensitivity_design_comparison": analyses,
        },
    )
    for a in analyses:
        print(a["contact_distances_angstrom"], a["scheme"], a["condition_number"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prediction-root", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    main(a.prediction_root.resolve(), a.root.resolve())
