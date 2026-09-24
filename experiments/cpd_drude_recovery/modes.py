"""Compare equilibrium angles and nuclear modes; no retrospective acceptance gate."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from scipy.constants import Avogadro, atomic_mass, c
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_openmm_linear_response import (
    mass_weighted_rigid_body_projector,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--stationary", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(exist_ok=False)
    (args.output / "modes_snapshot.py").write_text(Path(__file__).read_text())
    manifest_path = args.stage / "responses/minimum/linear_response_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    with np.load(checked(manifest["outputs"]["linear_response_arrays"])) as data:
        arrays = dict(data)
    qm = np.array(
        [
            a[1:]
            for a in parse_xyz(
                checked(manifest["sources"]["target_geometry"]).read_text()
            )[0]
        ]
    )
    mm = np.loadtxt(args.stationary / "stationary_coordinates_angstrom.txt")
    h = np.loadtxt(args.stationary / "nuclear_hessian_kcal_mol_angstrom2.txt")
    assessment = json.loads((args.stationary / "assessment.json").read_text())
    if not assessment["numerical_local_minimum_passed"]:
        raise ValueError("Normal-mode comparison requires a verified local minimum")
    masses = arrays["masses_amu"]
    # Rotate both MM coordinates and its Cartesian Hessian into the QM frame.
    a, b = (
        mm - np.average(mm, axis=0, weights=masses),
        qm - np.average(qm, axis=0, weights=masses),
    )
    left, _, right = np.linalg.svd((a * masses[:, None]).T @ b)
    rotation = left @ np.diag([1, 1, np.linalg.det(left @ right)]) @ right
    mm = a @ rotation + np.average(qm, axis=0, weights=masses)
    transform = np.kron(np.eye(len(mm)), rotation.T)
    h = transform @ h @ transform.T
    inv = np.repeat(1 / np.sqrt(masses), 3)
    factor = np.sqrt(4184 / Avogadro / 1e-20 / atomic_mass) / (2 * np.pi * c * 100)

    def modes(xyz, hessian):
        projector, rank = mass_weighted_rigid_body_projector(xyz, masses)
        if rank != 6:
            raise ValueError("Expected six rigid-body modes")
        vals, vecs = np.linalg.eigh(projector)
        z = vecs[:, vals > 0.5]
        eig, v = np.linalg.eigh(z.T @ (inv[:, None] * hessian * inv[None, :]) @ z)
        return np.sign(eig) * np.sqrt(abs(eig)) * factor, z @ v

    qf, qv = modes(qm, arrays["qm_hessian_kcal_mol_angstrom2"])
    mf, mv = modes(mm, h)
    overlap = (qv.T @ mv) ** 2
    qi, mi = linear_sum_assignment(-overlap)
    rows = [
        {
            "qm_mode": int(i),
            "mm_mode": int(j),
            "qm_cm_inverse": float(qf[i]),
            "mm_cm_inverse": float(mf[j]),
            "squared_overlap": float(overlap[i, j]),
        }
        for i, j in zip(qi, mi)
    ]
    plan = json.loads((args.stage / "bonded_fit_plan.json").read_text())
    # Stable identities come from the separately verified geometry report order.
    from experiments.cpd_drude_recovery.campaign import checked as check_source

    basis = json.loads(
        (args.stage / "basis/linear_fit_basis_manifest.json").read_text()
    )
    skeleton = json.loads(
        check_source(basis["sources"]["skeleton_manifest"]).read_text()
    )
    atom_map = json.loads(
        check_source(skeleton["outputs"]["stable_atom_map"]).read_text()
    )
    idx = {record["stable_atom_key"]: i for i, record in enumerate(atom_map)}
    np.savez(
        args.output / "normal_modes.npz",
        qm_frequencies_cm_inverse=qf,
        mm_frequencies_cm_inverse=mf,
        qm_mass_weighted_eigenvectors=qv,
        mm_mass_weighted_eigenvectors=mv,
        qm_coordinates_angstrom=qm,
        mm_coordinates_angstrom=mm,
        masses_amu=masses,
        atom_names=np.array(list(idx)),
    )
    terms = [
        item["atoms"]
        for item in plan["transfer_candidates"]
        if item["category"] == "angles"
    ]
    terms += [
        item["atoms"]
        for group in plan["uncovered_parameter_groups"]
        if group["category"] == "angles"
        for item in group["occurrences"]
    ]

    def angle(x, ids):
        a, b, d = x[ids]
        v, w = a - b, d - b
        return float(
            np.degrees(
                np.arccos(np.clip(v @ w / np.linalg.norm(v) / np.linalg.norm(w), -1, 1))
            )
        )

    angles = []
    for atoms in terms:
        ids = [idx[name] for name in atoms]
        q, m = angle(qm, ids), angle(mm, ids)
        angles.append(
            {"atoms": atoms, "qm_degrees": q, "mm_degrees": m, "error_degrees": m - q}
        )
    write(
        args.output / "assessment.json",
        {
            "status": "mode_and_angle_diagnostic_requires_physical_review",
            "simulation_ready": False,
            "gate_effect": "none",
            "frequency_scaling": "Unscaled nuclear harmonic frequencies; Drude auxiliary modes excluded.",
            "mode_assignment": "Maximum total squared mass-weighted eigenvector overlap; individual assignments in near-degenerate subspaces may be unstable.",
            "sorted_frequency_rmse_cm_inverse": float(np.sqrt(np.mean((qf - mf) ** 2))),
            "overlap_matched_frequency_rmse_cm_inverse": float(
                np.sqrt(np.mean((qf[qi] - mf[mi]) ** 2))
            ),
            "median_squared_overlap": float(np.median(overlap[qi, mi])),
            "minimum_qm_frequency": float(min(qf)),
            "minimum_mm_frequency": float(min(mf)),
            "maximum_angle_error_degrees": max(abs(a["error_degrees"]) for a in angles),
            "angle_rms_error_degrees": float(
                np.sqrt(np.mean([a["error_degrees"] ** 2 for a in angles]))
            ),
            "angles": sorted(
                angles, key=lambda a: abs(a["error_degrees"]), reverse=True
            ),
            "modes": rows,
            "sources": {
                "qm_response": source(manifest_path),
                "stationary": source(args.stationary / "assessment.json"),
                "mm_hessian": source(
                    args.stationary / "nuclear_hessian_kcal_mol_angstrom2.txt"
                ),
                "code": source(args.output / "modes_snapshot.py"),
            },
        },
    )
    print("Mode and angle diagnostics written; no acceptance asserted.")


if __name__ == "__main__":
    main()
