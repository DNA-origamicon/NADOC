"""Preserve endpoint-2 restart provenance and adapt the passed endpoint-1 audit."""

import json
from pathlib import Path
import re
import sys
import numpy as np
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from experiments.cpd_drude_recovery.audit_repaired_fragment_qm import sugar_checks
from backend.parameterization.photoproduct_qm import generate_psi4_job
from backend.parameterization.photoproduct_models import (
    audit_product_chirality,
    _covalent_bond_radius_ratio_range,
    _minimum_nonbonded_covalent_ratio,
)
from backend.parameterization.photoproduct_distributed_hessian import (
    prepare_distributed_hessian,
)

ORIGIN = Path(".development-artifacts/cpd-anti-additive-boundary-qm-v2").resolve()
ROOT = Path(".development-artifacts/cpd-anti-additive-next-v2").resolve()


def evaluated_geometry(text, count):
    block = text.rsplit("Geometry (in Angstrom)", 1)[1]
    rows = re.findall(
        r"^\s*([CHNO])\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)(?:\s+[-+\d.Ee]+)?\s*$",
        block,
        re.M,
    )
    if len(rows) != count:
        raise ValueError(f"Expected {count} native geometry rows, found {len(rows)}")
    return [(r[0], *map(float, r[1:])) for r in rows]


def main():
    ROOT.mkdir(exist_ok=False)
    (ROOT / "executed_source.py").write_text(Path(__file__).read_text())
    a1 = ORIGIN / "endpoint-1/independent_qm_geometry_audit.json"
    audit = json.loads(a1.read_text())
    assert audit["all_endpoints_passed"] and len(audit["records"]) == 1
    for src in audit["records"][0]["sources"]:
        checked(src)
    model = json.loads(
        (
            Path(
                ".development-artifacts/cpd-repaired-anti-fragments-v1/endpoint-1/model_manifest.json"
            )
        ).read_text()
    )
    xyz = ORIGIN / "endpoint-1/qm-endpoint-1/optimized.xyz"
    parent = ROOT / "endpoint1_optimized_model_audit.json"
    write(
        parent,
        dict(
            schema="nadoc.photoproduct-optimized-model-audit.v1",
            status="passed_candidate_identity_and_chirality",
            product_id=model["product_id"],
            model_id=model["model_id"],
            optimized_xyz=source(xyz),
            atom_map=model["atom_map"],
            simulation_ready=False,
            gate_effect="none",
            adapter_scope="Schema adapter of actual independent audited optimization; no new optimization or minimum claim.",
            independent_audit=source(a1),
            checks=audit["records"][0]["checks"],
        ),
    )
    generate_psi4_job(
        product_id=model["product_id"],
        model_id=model["model_id"],
        xyz_path=xyz,
        output_dir=ROOT / "endpoint1-frequency",
        job_kind="frequency",
        charge=0,
        multiplicity=1,
        atom_map=model["atom_map"],
        parent_manifest_path=parent,
        memory_gib=3,
        threads=4,
        protocol_path=Path(
            "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json"
        ),
    )
    plan = prepare_distributed_hessian(
        job_dir=ROOT / "endpoint1-frequency", output_dir=ROOT / "endpoint1-hessian"
    )
    # Each convergence row is linked to the immediately preceding printed evaluated
    # geometry, not the proposed next geometry or an unconverged final iterate.
    ep = ORIGIN / "endpoint-2"
    qplan = json.loads((ep / "qm_plan.json").read_text())
    seeds = json.loads(checked(qplan["seed_assessment"]).read_text())
    seed = seeds["records"][0]
    mod = json.loads(checked(seed["model_manifest"]).read_text())
    boundary = json.loads(checked(mod["source_boundary_manifest"]).read_text())
    definition = json.loads(checked(boundary["chemical_definition"]).read_text())
    mol = Chem.SDMolSupplier(str(checked(mod["outputs"]["sdf"])), removeHs=False)[0]
    names = mod["atom_map"]
    elements = [a.GetSymbol() for a in mol.GetAtoms()]
    text = (ep / "qm-endpoint-2/output.dat").read_text()
    limits = json.loads(
        Path(
            "backend/data/forcefield/photoproduct_flexible_boundary_seed_policy_v1.json"
        ).read_text()
    )["thresholds"]
    rows = []
    coords = {}
    for m in re.finditer(r"^\s*(\d+)\s+(-\d+\.\d+)\s+([^\n]+)~\s*$", text, re.M):
        values = m[3].replace("*", " ").replace("o", " ").split()
        if len(values) != 5:
            continue
        values = list(map(float, values))
        atoms = evaluated_geometry(text[: m.start()], len(names))
        x = np.array([a[1:] for a in atoms])
        sugar = sugar_checks(x, names, 2, seed["sugar_centers"])
        lesion = audit_product_chirality(definition, dict(zip(names, x.tolist())))
        lo, hi = _covalent_bond_radius_ratio_range(mol, x, elements)
        contact = _minimum_nonbonded_covalent_ratio(mol, x, elements)
        bound = limits["covalent_bond_radius_ratio"]
        passed = (
            [a[0] for a in atoms] == elements
            and all(r["preserved"] for r in sugar)
            and lesion["passed"]
            and bound["minimum"] <= lo <= hi <= bound["maximum"]
            and contact >= limits["minimum_nonbonded_covalent_radius_ratio"]
        )
        key = len(rows)
        coords[key] = atoms
        rows.append(
            dict(
                record=key,
                step=int(m[1]),
                energy=float(m[2]),
                max_force=values[1],
                rms_force=values[2],
                passed=bool(passed),
                sugar=sugar,
                lesion=lesion,
                covalent_range=[lo, hi],
                minimum_contact=contact,
            )
        )
    eligible = [r for r in rows if r["passed"]]
    if not eligible:
        raise ValueError("No stereochemically intact restart candidate")
    best = min(eligible, key=lambda r: r["max_force"])
    atoms = coords[best["record"]]
    restart = ROOT / "endpoint2_restart.xyz"
    restart.write_text(
        f"{len(atoms)}\nAudited evaluated step {best['step']}; not converged\n"
        + "\n".join(f"{e} {x:.12f} {y:.12f} {z:.12f}" for e, x, y, z in atoms)
        + "\n"
    )
    write(
        ROOT / "endpoint2_restart_audit.json",
        dict(
            selected=best,
            records=rows,
            seed=source(restart),
            sources=[
                source(ep / "qm-endpoint-2/output.dat"),
                source(ep / "qm_plan.json"),
            ],
            criterion="Smallest reported max force among native evaluated geometries retaining original graph distance screen and all sugar/lesion centers.",
            simulation_ready=False,
        ),
    )
    print(
        json.dumps(
            {
                "hessian_tasks": plan["task_count"],
                "restart_step": best["step"],
                "restart_force": best["max_force"],
                "screened_candidates": len(eligible),
                "records": len(rows),
            }
        )
    )


if __name__ == "__main__":
    main()
