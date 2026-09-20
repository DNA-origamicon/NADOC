"""Isolated UFF boundary relaxation with source-sugar handedness constraints."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from rdkit.Chem import AllChem
from scipy.optimize import minimize, NonlinearConstraint

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.audit_boundary_seeds import read_outputs, volume
from experiments.cpd_drude_recovery.campaign import checked, source, write


def main(manifest_path, root, initial_path=None):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    manifest = json.loads(manifest_path.read_text())
    paths, names, xyz, mol, bonds = read_outputs(manifest_path, manifest)
    refpath = checked(manifest["source_selection"]["reference_manifest"])
    ref = json.loads(refpath.read_text())
    _, refnames, refxyz, _, _ = read_outputs(refpath, ref)
    base = {
        "N1",
        "C2",
        "O2",
        "N3",
        "H3",
        "C4",
        "O4",
        "C5",
        "C7",
        "C6",
        "H51",
        "H52",
        "H53",
        "H6",
    }
    moving = np.array([i for i, n in enumerate(names) if n.split(":")[1] not in base])
    fixed = np.array([i for i, n in enumerate(names) if n.split(":")[1] in base])
    assert len(fixed) == 28
    assert AllChem.UFFHasAllMoleculeParams(mol)
    ff = AllChem.UFFGetMoleculeForceField(
        mol, confId=0, ignoreInterfragInteractions=False
    )
    ff.Initialize()
    definitions = []
    for endpoint in (1, 2):
        for center, neighbor in [
            ("C1'", ["O4'", "C2'", "N1", "H1'"]),
            ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
            ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
        ]:
            ordered = [f"{endpoint}:{n}" for n in neighbor]
            v = volume(refxyz, refnames, ordered)
            definitions.append(
                {
                    "center": f"{endpoint}:{center}",
                    "ordered": ordered,
                    "indices": [names.index(n) for n in ordered],
                    "sign": float(np.sign(v)),
                    "lower_bound": 0.5 * abs(v),
                }
            )
    write(
        root / "policy.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "role": "Isolated chirality-preserving UFF seed experiment; not QM or production coordinates.",
            "source": source(manifest_path),
            "reference": source(refpath),
            "fixed_atom_names": [names[i] for i in fixed],
            "sugar_constraints": definitions,
            "script": source(root / "source_snapshot.py"),
            "warm_start": source(initial_path) if initial_path else None,
        },
    )

    def coords(x):
        p = xyz.copy()
        p[moving] = x.reshape(-1, 3)
        return p

    def objective(x):
        p = tuple(coords(x).ravel())
        return ff.CalcEnergy(p), np.array(ff.CalcGrad(p)).reshape(-1, 3)[moving].ravel()

    def constraints(x):
        p = coords(x)
        values = []
        jac = []
        for row in definitions:
            ids = row["indices"]
            a, b, c, d = p[ids]
            gb = np.cross(c - a, d - a)
            gc = np.cross(d - a, b - a)
            gd = np.cross(b - a, c - a)
            gradients = np.zeros_like(p)
            gradients[ids] = np.array([-gb - gc - gd, gb, gc, gd]) * row["sign"]
            values.append(row["sign"] * np.dot(b - a, np.cross(c - a, d - a)))
            jac.append(gradients[moving].ravel())
        return np.array(values), np.array(jac)

    initial = xyz[moving].ravel()
    if initial_path:
        start = np.loadtxt(initial_path)
        if start.shape != xyz.shape or np.max(abs(start[fixed] - xyz[fixed])) > 1e-9:
            raise ValueError("Warm-start geometry changes the fixed lesion core")
        initial = start[moving].ravel()
    step = 1e-5
    # Check both gradients against a deterministic nontrivial coordinate direction.
    direction = np.sin(np.arange(len(initial)) + 0.3)
    direction /= np.linalg.norm(direction)
    fd = (
        objective(initial + step * direction)[0]
        - objective(initial - step * direction)[0]
    ) / (2 * step)
    analytic = objective(initial)[1] @ direction
    if abs(fd - analytic) > 1e-4 * max(1, abs(fd)):
        raise ValueError("UFF derivative check failed")
    fd_c = (
        constraints(initial + step * direction)[0]
        - constraints(initial - step * direction)[0]
    ) / (2 * step)
    assert np.max(abs(fd_c - constraints(initial)[1] @ direction)) < 1e-7
    result = minimize(
        objective,
        initial,
        jac=True,
        method="SLSQP" if initial_path else "trust-constr",
        constraints=[
            NonlinearConstraint(
                lambda x: constraints(x)[0],
                [r["lower_bound"] for r in definitions],
                np.inf,
                jac=lambda x: constraints(x)[1],
            )
        ],
        options={"ftol": 1e-10, "maxiter": 2000}
        if initial_path
        else {
            "initial_tr_radius": 0.05,
            "gtol": 1e-5,
            "xtol": 1e-10,
            "maxiter": 3000,
        },
    )
    constraint_values, constraint_jac = constraints(result.x)
    lower = np.array([r["lower_bound"] for r in definitions])
    violation = float(np.maximum(lower - constraint_values, 0).max())
    gradient = objective(result.x)[1]
    active = constraint_jac[constraint_values - lower < 1e-5]
    if len(active):
        multipliers = np.linalg.lstsq(active.T, gradient, rcond=1e-12)[0]
        lagrangian = gradient - active.T @ multipliers
        dual_violation = float(np.maximum(-multipliers, 0).max())
    else:
        lagrangian = gradient
        dual_violation = 0.0
    final = coords(result.x)
    np.savetxt(root / "candidate_coordinates_angstrom.txt", final)
    elements = [a.GetSymbol() for a in mol.GetAtoms()]
    (root / "candidate.xyz").write_text(
        str(len(names))
        + "\nisolated chirality-constrained UFF candidate; not validated\n"
        + "".join(
            f"{e} {p[0]:.12f} {p[1]:.12f} {p[2]:.12f}\n"
            for e, p in zip(elements, final)
        )
    )
    write(
        root / "assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "optimizer_success": bool(result.success),
            "message": str(result.message),
            "iterations": int(result.nit),
            "maximum_constraint_violation": violation,
            "dual_multiplier_violation": dual_violation,
            "lagrangian_gradient_max": float(abs(lagrangian).max()),
            "initial_energy": float(objective(initial)[0]),
            "final_energy": float(result.fun),
            "fixed_core_displacement": float(abs(final[fixed] - xyz[fixed]).max()),
            "signed_sugar_volumes": constraints(result.x)[0].tolist(),
            "policy": source(root / "policy.json"),
            "requires": "Independent lesion/sugar, bond-order, bond-length and clash audit before any QM use.",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--initial", type=Path)
    a = p.parse_args()
    main(
        a.manifest.resolve(),
        a.root.resolve(),
        a.initial.resolve() if a.initial else None,
    )
