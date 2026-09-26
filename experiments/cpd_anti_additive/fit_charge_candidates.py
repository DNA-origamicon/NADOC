"""Bounded exploratory additive charge candidates; all inputs are development data."""

import argparse
from pathlib import Path
import sys
import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.water_transfer_diagnostic import (
    load_cases,
    metrics,
    ART,
    checked,
    source,
    write,
)

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--train-endpoint", type=int, choices=[1, 2])
args = parser.parse_args()
from experiments.cpd_anti_additive.validation_gate import require_fit_ready
require_fit_ready()
root = args.root.resolve()
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
cases = load_cases()
keys = sorted(
    k
    for k in set(cases[0]["names"]) & set(cases[1]["names"])
    if "'" not in k and k.split(":")[1] not in ["CM", "HCM1", "HCM2", "HCM3"]
)
assert len(keys) == 28
constraints = [np.ones(len(keys))]
for residue in (1, 2):
    for atom in ["H52", "H53"]:
        row = np.zeros(len(keys))
        row[keys.index(f"{residue}:{atom}")] = 1
        row[keys.index(f"{residue}:H51")] = -1
        constraints.append(row)
C = np.array(constraints)
write(
    root / "plan.json",
    dict(
        train_endpoint=args.train_endpoint,
        retrospective_cross_transfer=True,
        variable_atoms=keys,
        maximum_charge_shift_e=0.15,
        regularization_weights=[1, 10, 100],
        charge_constraints="Sum of base-charge shifts zero; methyl H shifts equal within each base",
        fixed="All sugar/cap charges, LJ, bonded parameters",
        objective="ESP errors scaled by0.005 au and water energies by1 kcal/mol, each endpoint/block normalized by sqrt(sample count); water uses three near-minimum points at -0.2 A shifted geometry and1.16-scaled QM energies; L2 shift penalty on delta/0.1e",
        evidence_role="All data development; no independent validation claim, no selected release",
        sources=[source(ART / "cpd-anti-water-curves-v2/assessment.json")]
        + [
            source(ART / f"cpd-anti-boundary-esp-v2/endpoint-{e}/esp_audit.json")
            for e in (1, 2)
        ],
        simulation_ready=False,
    ),
)
blocks = []
targets = []
for c in cases:
    M = np.zeros((len(c["names"]), len(keys)))
    for j, k in enumerate(keys):
        M[c["names"].index(k), j] = 1
    c["map"] = M
    grid = np.loadtxt(checked(c["esp"]["grid"]))
    pot = np.loadtxt(checked(c["esp"]["potentials"]))
    pot = pot if pot.ndim == 1 else pot[:, -1]
    A = 0.529177210903 / np.linalg.norm(grid[:, None, :] - c["xyz"][None, :, :], axis=2)
    c["esp_matrix"] = A
    c["esp_values"] = pot
    if args.train_endpoint and c["endpoint"] != args.train_endpoint:
        continue
    blocks.append(A @ M / (0.005 * np.sqrt(len(pot))))
    targets.append((pot - A @ c["charges"]) / (0.005 * np.sqrt(len(pot))))
    W = []
    y = []
    for curve in c["curves"]:
        i = int(np.argmin([p["target"] for p in curve["points"]]))
        for p in curve["points"][i - 1 : i + 2]:
            W.append(p["offset_row"])
            y.append(p["target"] - p["offset_lj"])
    W = np.asarray(W)
    y = np.asarray(y)
    blocks.append(W @ M / np.sqrt(len(y)))
    targets.append((y - W @ c["charges"]) / np.sqrt(len(y)))
A = np.vstack(blocks)
b = np.concatenate(targets)
records = []
for strength in [1, 10, 100]:
    H = A.T @ A + strength * 100 * np.eye(len(keys))
    rhs = A.T @ b
    result = minimize(
        lambda q: (0.5 * q @ H @ q - q @ rhs, H @ q - rhs),
        np.zeros(len(keys)),
        jac=True,
        method="SLSQP",
        bounds=[(-0.15, 0.15)] * len(keys),
        constraints=[dict(type="eq", fun=lambda q: C @ q, jac=lambda q: C)],
        options=dict(maxiter=1000, ftol=1e-12),
    )
    delta = result.x
    out = []
    for c in cases:
        q = c["charges"] + c["map"] @ delta
        assert abs(q.sum()) < 1e-8
        errors = c["esp_matrix"] @ q - c["esp_values"]
        dipole = (q[:, None] * c["xyz"]).sum(axis=0) / 0.529177210903
        out.append(
            dict(
                endpoint=c["endpoint"],
                atom_map=c["names"],
                charges_e=q.tolist(),
                water_metrics=metrics(c, q),
                esp_rmse_au=float(np.sqrt(np.mean(errors**2))),
                esp_relative_rmse=float(
                    np.linalg.norm(errors) / np.linalg.norm(c["esp_values"])
                ),
                dipole_vector_error_debye=float(
                    np.linalg.norm(dipole - np.asarray(c["esp"]["dipole"]["vector"]))
                    * 2.541746473
                ),
            )
        )
    records.append(
        dict(
            regularization=strength,
            optimizer_success=bool(result.success),
            message=result.message,
            max_constraint_error=float(abs(C @ delta).max()),
            charge_shifts_e=dict(zip(keys, delta.tolist())),
            endpoints=out,
            simulation_ready=False,
        )
    )
write(
    root / "assessment.json",
    dict(
        records=records,
        simulation_ready=False,
        scope="Exploratory shared base charges across two fragments; fixed sugar/caps and LJ; no PSF export or candidate acceptance",
    ),
)
for r in records:
    print(
        r["regularization"],
        r["optimizer_success"],
        [
            (
                e["endpoint"],
                e["esp_relative_rmse"],
                e["dipole_vector_error_debye"],
                max(abs(w["energy_error_kcal_mol"]) for w in e["water_metrics"]),
            )
            for e in r["endpoints"]
        ],
    )
