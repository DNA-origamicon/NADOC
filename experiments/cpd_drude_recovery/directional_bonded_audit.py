"""Resolve local bonded residuals into fixed and fitted response contributions."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_qm import parse_xyz


def main(stage, fit_path, output):
    manifest_path = stage / "responses/minimum/linear_response_manifest.json"
    m = json.loads(manifest_path.read_text())
    with np.load(checked(m["outputs"]["linear_response_arrays"])) as f:
        a = dict(f)
    fit = json.loads(fit_path.read_text())
    parameters = fit["parameters"]
    coeff = np.array([r["coefficient"] for r in parameters])
    parameter_map = json.loads(
        checked(m["sources"]["linear_parameter_map"]).read_text()
    )
    if isinstance(parameter_map, dict):
        parameter_map = parameter_map.get("parameters", parameter_map)
    assert [p["name"] for p in parameter_map] == [p["name"] for p in parameters]
    atom_map = json.loads(checked(m["sources"]["stable_atom_map"]).read_text())
    names = [r["stable_atom_key"] for r in atom_map]
    idx = {n: i for i, n in enumerate(names)}
    x = np.array(
        [
            row[1:]
            for row in parse_xyz(checked(m["sources"]["target_geometry"]).read_text())[
                0
            ]
        ]
    )
    directions = []
    for ring in (1, 2):
        ci, hi = idx[f"{ring}:C6"], idx[f"{ring}:H6"]
        v = x[hi] - x[ci]
        v /= np.linalg.norm(v)
        q = np.zeros_like(x)
        mc, mh = a["masses_amu"][[ci, hi]]
        q[hi] = v * mc / (mc + mh)
        q[ci] = -v * mh / (mc + mh)
        directions.append((f"{ring}:C6-H6 COM-preserving stretch", q.reshape(-1)))
        ni = idx[f"{ring}:N1"]
        neighbors = [idx[f"{ring}:{n}"] for n in ("C6", "C2", "CM")]
        v = np.cross(
            x[neighbors[1]] - x[neighbors[0]], x[neighbors[2]] - x[neighbors[0]]
        )
        v /= np.linalg.norm(v)
        q = np.zeros_like(x)
        q[ni] = v
        directions.append(
            (f"{ring}:N1 displacement normal to neighbors", q.reshape(-1))
        )
    records = []
    for label, q in directions:
        g = coeff * (a["parameter_gradient_response"] @ q)
        h = coeff * np.einsum("i,pij,j->p", q, a["parameter_hessian_response"], q)
        grouped = {}
        for p, gg, hh in zip(parameters, g, h):
            item = grouped.setdefault(
                p["group_id"], {"gradient": 0.0, "curvature": 0.0}
            )
            item["gradient"] += float(gg)
            item["curvature"] += float(hh)
        bg = float(a["base_gradient_kcal_mol_angstrom"] @ q)
        bh = float(q @ a["base_hessian_kcal_mol_angstrom2"] @ q)
        records.append(
            {
                "coordinate": label,
                "qm_gradient": float(a["qm_gradient_kcal_mol_angstrom"] @ q),
                "predicted_gradient": bg + float(g.sum()),
                "qm_curvature": float(q @ a["qm_hessian_kcal_mol_angstrom2"] @ q),
                "predicted_curvature": bh + float(h.sum()),
                "fixed_gradient": bg,
                "fixed_curvature": bh,
                "fitted_group_contributions": [
                    {"group": k, **v}
                    for k, v in sorted(
                        grouped.items(),
                        key=lambda kv: abs(kv[1]["curvature"]),
                        reverse=True,
                    )
                    if abs(v["curvature"]) > 1e-6 or abs(v["gradient"]) > 1e-6
                ],
            }
        )
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "role": "At the audited QM minimum; no fitting or new acceptance gate. Fixed block contains electrostatic/LJ and transferred bonded terms. Curvature includes all couplings along stated coordinate.",
        "gradient_units": "kcal/mol/angstrom",
        "curvature_units": "kcal/mol/angstrom^2",
        "manifest": source(manifest_path),
        "fit": source(fit_path),
        "code": source(Path(__file__)),
        "records": records,
    }
    write(output, report)
    print(
        json.dumps(
            [
                {k: v for k, v in row.items() if k != "fitted_group_contributions"}
                for row in records
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--fit", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    main(a.stage, a.fit, a.output)
