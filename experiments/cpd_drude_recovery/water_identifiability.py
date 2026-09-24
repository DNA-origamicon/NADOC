"""Geometry-only local LJ sensitivity; does not read or fit QM energies."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write


def main(prediction_root, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    policy_path = prediction_root / "policy.json"
    policy = json.loads(policy_path.read_text())
    batch = json.loads(checked(policy["batch"]).read_text())
    names = list(policy["pairs"])
    assert len(names) == 36
    schemes = {
        "shared_carbonyl_and_H3": {"carbonyl": ["O2", "O4"], "H3": ["H3"]},
        "separate_O2_O4_and_H3": {"O2": ["O2"], "O4": ["O4"], "H3": ["H3"]},
    }
    records = []
    for scheme, groups in schemes.items():
        derivatives = []
        case_ids = []
        distances = []
        fd_errors = []
        columns = [f"{g}:{p}" for g in groups for p in ("log_epsilon", "log_rmin")]
        for case in batch["cases"]:
            if case["partition"] != "training":
                continue
            xyz = np.array(
                [
                    [float(v) for v in l.split()[1:]]
                    for l in case["molecule"].splitlines()
                    if len(l.split()) == 4
                ]
            )
            row = []
            drow = {}
            for group, atoms in groups.items():
                eps = []
                rmin = []
                dist = []
                for i, name in enumerate(names):
                    if name.split(":")[1] not in atoms:
                        continue
                    pair = policy["pairs"][name]
                    eps.append(pair["epsilon_kcal_mol"])
                    rmin.append(pair["rmin_angstrom"])
                    dist.append(np.linalg.norm(xyz[i] - xyz[-3]))
                eps, rmin, dist = map(np.array, (eps, rmin, dist))
                six = (rmin / dist) ** 6
                analytic = np.array(
                    [
                        np.sum(eps * (six**2 - 2 * six)),
                        np.sum(12 * eps * (six**2 - six)),
                    ]
                )

                def energy(logeps, logr):
                    ratio = (rmin * np.exp(logr) / dist) ** 6
                    return float(np.sum(eps * np.exp(logeps) * (ratio**2 - 2 * ratio)))

                step = 1e-5
                finite = np.array(
                    [
                        (energy(step, 0) - energy(-step, 0)) / (2 * step),
                        (energy(0, step) - energy(0, -step)) / (2 * step),
                    ]
                )
                fd_errors.append(float(abs(analytic - finite).max()))
                row.extend(analytic.tolist())
                drow[group] = dist.tolist()
            derivatives.append(row)
            case_ids.append(case["id"])
            distances.append(drow)
        jac = np.array(derivatives)
        norm = np.linalg.norm(jac, axis=0)
        scaled = jac / np.where(norm > 0, norm, 1)
        _, sv, vh = np.linalg.svd(scaled, full_matrices=False)
        records.append(
            {
                "scheme": scheme,
                "columns": columns,
                "case_ids": case_ids,
                "sensitivity_kcal_mol_per_log_parameter": jac.tolist(),
                "column_norms": norm.tolist(),
                "column_normalized_singular_values": sv.tolist(),
                "column_normalized_condition_number": float(sv[0] / sv[-1]),
                "rank_at_relative_1e_minus8": int(np.sum(sv > sv[0] * 1e-8)),
                "weakest_column_normalized_direction": vh[-1].tolist(),
                "maximum_analytic_fd_difference": max(fd_errors),
                "water_oxygen_pair_distances_angstrom": distances,
            }
        )
    write(
        root / "assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "qm_values_read": False,
            "scope": "Training-geometry local sensitivity of grouped pair epsilon/Rmin log changes. All other LJ and frozen electrostatics held fixed. SVD conditioning does not establish physical validation or globally unique fitting.",
            "sources": [
                source(p)
                for p in (
                    policy_path,
                    checked(policy["batch"]),
                    root / "source_snapshot.py",
                )
            ],
            "records": records,
        },
    )
    for r in records:
        print(
            r["scheme"],
            "rank",
            r["rank_at_relative_1e_minus8"],
            "of",
            len(r["columns"]),
            "condition",
            r["column_normalized_condition_number"],
            "FD error",
            r["maximum_analytic_fd_difference"],
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prediction-root", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    main(a.prediction_root.resolve(), a.root.resolve())
