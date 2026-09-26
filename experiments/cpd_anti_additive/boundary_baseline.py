"""Anti endpoint-1 additive transfer baseline; isolated, no fitted or released model."""

import argparse
import json, subprocess, warnings
from pathlib import Path
import sys
import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.reconstruct import (
    BASE,
    FF,
    ATOMS,
    source,
    write,
)
from experiments.cpd_published_comparator.local_benchmarks import checked, angle, volume

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--endpoint", type=int, choices=[1, 2], default=1)
parser.add_argument("--audit", type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
candidate = Path(".development-artifacts/cpd-published-comparator-v1").resolve()
write(
    root / "plan.json",
    {
        "candidate": source(candidate / "comparator_last.prm"),
        "scope": f"One 49-atom anti endpoint-{args.endpoint} sugar-attached QM fragment; no fitting",
        "criteria": {
            "boundary_bond_max_A": 0.03,
            "boundary_angle_max_deg": 3,
            "stereochemistry": "all sugar and lesion signs retained",
        },
        "gas_phase_minimum_not_solution_validation": True,
    },
)
# Obtain standard terminal deoxythymidine sugar types/charges via native psfgen.
tcl = f"""package require psfgen
resetpsf
topology {BASE}/top_all36_na.rtf
segment S {{
 first 5TER
 last 3TER
 residue 1 THY
}}
patch DEO5 S:1
regenerate angles dihedrals
writepsf {root}/sugar_template.psf
exit
"""
(root / "sugar_template.tcl").write_text(tcl)
p = subprocess.run(
    ["psfgen", str(root / "sugar_template.tcl")], capture_output=True, text=True
)
(root / "sugar_template.log").write_text(p.stdout + p.stderr)
p.check_returncode()
template = app.CharmmPsfFile(str(root / "sugar_template.psf"))
sugar = {a.name: (a.attype, a.charge) for a in template.atom_list}
sugar["H5T"] = sugar["HO5'"]
sugar["H3T"] = sugar["HO3'"]
assert abs(sum(a.charge for a in template.atom_list)) < 1e-7
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    params = app.CharmmParameterSet(
        str(BASE / "top_all36_na.rtf"),
        str(BASE / "par_all36_na.prm"),
        str(FF / "top_all36_cgenff.rtf"),
        str(FF / "par_all36_cgenff.prm"),
        str(candidate / "comparator_last.prm"),
    )
reports = []
for endpoint in [args.endpoint]:
    out = root / f"endpoint-{endpoint}"
    out.mkdir()
    folder = (
        Path(".development-artifacts/cpd-repaired-anti-fragments-v1")
        / f"endpoint-{endpoint}"
    )
    model_path = folder / "model_manifest.json"
    model = json.loads(model_path.read_text())
    names = model["atom_map"]
    idx = {n: i for i, n in enumerate(names)}
    audit_path = args.audit.resolve()
    audit = json.loads(audit_path.read_text())
    assert audit["status"] == "passed_candidate_identity_and_chirality"
    assert audit["model_id"] == model["model_id"]
    assert audit["atom_map"] == names
    checked(audit["independent_audit"])
    xp = checked(audit["optimized_xyz"])
    xyz = np.array(
        [
            list(map(float, l.split()[1:]))
            for l in xp.read_text().splitlines()[2:]
            if l.strip()
        ]
    )
    graph = json.loads(checked(model["outputs"]["model_graph"]).read_text())
    assert [a["key"] for a in graph["atoms"]] == names
    cap = {
        "CM": ("CG331", -0.27),
        "HCM1": ("HGA3", 0.09),
        "HCM2": ("HGA3", 0.09),
        "HCM3": ("HGA3", 0.09),
    }
    aliases = {"C7": "C5M", "HO5'": "H5T", "HO3'": "H3T"}
    assignments = []
    for name in names:
        n = name.split(":")[1]
        native = aliases.get(n, n)
        assignments.append(
            cap[n] if n in cap else ATOMS[native] if native in ATOMS else sugar[native]
        )
    assert abs(sum(q for _, q in assignments)) < 1e-7
    from experiments.cpd_drude_recovery.campaign import audit_graph

    registry = json.loads(
        Path("backend/data/forcefield/photoproduct_registry.json").read_text()
    )
    graph_audit = audit_graph(
        names, [tuple(b["indices"]) for b in graph["bonds"]], registry
    )
    write(out / "graph_audit.json", graph_audit)
    wanted = {t for t, _ in assignments}
    masses = []
    for i, t in enumerate(sorted(wanted), 1):
        masses.append(f"MASS -1 {t} {params.atom_types_str[t].mass}")
    rtf = [
        "* Frozen CPD sugar-boundary validation\n*\n36 1",
        *masses,
        "AUTO ANGLES DIHE",
        "RESI CPDB 0.0",
        "GROUP",
    ]
    for i, (typ, q) in enumerate(assignments):
        rtf.append(f"ATOM A{i:03d} {typ} {q:.8f}")
    for b in graph["bonds"]:
        a, c = b["indices"]
        rtf.append(f"BOND A{a:03d} A{c:03d}")
    for r in [1, 2]:
        for seq in [("C2", "N1", "N3", "O2"), ("C4", "N3", "C5", "O4")]:
            rtf.append("IMPR " + " ".join(f"A{idx[f'{r}:{n}']:03d}" for n in seq))
    rtf.append("END")
    (out / "fragment.rtf").write_text("\n".join(rtf) + "\n")
    tcl = f"""package require psfgen
resetpsf
topology {out}/fragment.rtf
segment B {{
 first NONE
 last NONE
 residue 1 CPDB
}}
regenerate angles dihedrals
writepsf {out}/fragment.psf
exit
"""
    (out / "build.tcl").write_text(tcl)
    p = subprocess.run(
        ["psfgen", str(out / "build.tcl")], capture_output=True, text=True
    )
    (out / "build.log").write_text(p.stdout + p.stderr)
    p.check_returncode()
    psf = app.CharmmPsfFile(str(out / "fragment.psf"))
    assert len(psf.atom_list) == 49 and len(psf.bond_list) == 52
    actual = {tuple(sorted((b.atom1.idx, b.atom2.idx))) for b in psf.bond_list}
    expected = {tuple(sorted(b["indices"])) for b in graph["bonds"]}
    assert actual == expected
    system = psf.createSystem(
        params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False
    )
    (out / "system.xml").write_text(mm.XmlSerializer.serialize(system))
    it = mm.VerletIntegrator(0.001)
    ctx = mm.Context(system, it, mm.Platform.getPlatformByName("Reference"))

    def obj(flat, ctx=ctx):
        ctx.setPositions(flat.reshape(-1, 3) * u.angstrom)
        st = ctx.getState(getEnergy=True, getForces=True)
        return st.getPotentialEnergy().value_in_unit(
            u.kilocalorie_per_mole
        ), -np.asarray(
            st.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        ).ravel()

    sol = minimize(
        obj,
        xyz.ravel(),
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 8000, "ftol": 1e-15, "gtol": 1e-7, "maxls": 40},
    )
    final = sol.x.reshape(-1, 3)
    np.savetxt(out / "minimum_A.txt", final)
    glyco = {idx[f"{endpoint}:N1"], idx[f"{endpoint}:C1'"]}
    bond_error = float(
        np.linalg.norm(final[list(glyco)[0]] - final[list(glyco)[1]])
        - np.linalg.norm(xyz[list(glyco)[0]] - xyz[list(glyco)[1]])
    )
    angles = []
    for a in psf.angle_list:
        ids = [a.atom1.idx, a.atom2.idx, a.atom3.idx]
        if glyco.issubset(ids):
            angles.append(
                {
                    "atoms": [names[i] for i in ids],
                    "qm_deg": angle(xyz, ids),
                    "mm_deg": angle(final, ids),
                    "error_deg": angle(final, ids) - angle(xyz, ids),
                }
            )
    centers = []
    for center, seq in [
        ("C1'", ["O4'", "C2'", "N1", "H1'"]),
        ("C3'", ["C2'", "C4'", "O3'", "H3'"]),
        ("C4'", ["O4'", "C3'", "C5'", "H4'"]),
    ]:
        ids = [idx[f"{endpoint}:{n}"] for n in seq]
        v0, v1 = volume(xyz, ids), volume(final, ids)
        centers.append(
            {
                "center": f"{endpoint}:{center}",
                "qm": v0,
                "mm": v1,
                "preserved": v0 * v1 > 0,
            }
        )
    for r in [1, 2]:
        for center, seq in [
            ("C5", [f"{r}:C4", f"{r}:C6", f"{r}:C7", f"{3 - r}:C6"]),
            ("C6", [f"{r}:N1", f"{r}:C5", f"{r}:H6", f"{3 - r}:C5"]),
        ]:
            ids = [idx[n] for n in seq]
            v0, v1 = volume(xyz, ids), volume(final, ids)
            centers.append(
                {
                    "center": f"{r}:{center}",
                    "qm": v0,
                    "mm": v1,
                    "preserved": v0 * v1 > 0,
                }
            )
    report = {
        "endpoint": endpoint,
        "net_charge": sum(q for _, q in assignments),
        "parameter_load": "passed",
        "boundary_bond_error_A": bond_error,
        "max_boundary_angle_error_deg": max(abs(a["error_deg"]) for a in angles),
        "angles": angles,
        "centers": centers,
        "max_force": float(max(abs(obj(sol.x)[1]))),
        "optimizer_success": bool(sol.success),
        "sources": [
            source(xp),
            source(model_path),
            source(checked(model["outputs"]["model_graph"])),
        ],
    }
    report["all_bond_max_error_A"] = max(
        abs(
            np.linalg.norm(final[b.atom1.idx] - final[b.atom2.idx])
            - np.linalg.norm(xyz[b.atom1.idx] - xyz[b.atom2.idx])
        )
        for b in psf.bond_list
    )
    report["all_angle_max_error_deg"] = max(
        abs(
            angle(final, [a.atom1.idx, a.atom2.idx, a.atom3.idx])
            - angle(xyz, [a.atom1.idx, a.atom2.idx, a.atom3.idx])
        )
        for a in psf.angle_list
    )
    report["assignment_scope"] = (
        "Published cis-syn charges/types transferred as a test hypothesis on the independently audited anti graph; anti electrostatic validation outstanding."
    )
    report["boundary_geometry_passed"] = (
        abs(bond_error) <= 0.03 and report["max_boundary_angle_error_deg"] <= 3
    )
    report["stereochemistry_passed"] = all(c["preserved"] for c in centers)
    write(out / "assessment.json", report)
    reports.append(report)
    del ctx, it
write(
    root / "assessment.json",
    {
        "simulation_ready": False,
        "scope": "Independent sugar-attachment geometry test, not complete dinucleotide/solution acceptance",
        "records": reports,
    },
)
for r in reports:
    print(
        "endpoint",
        r["endpoint"],
        "bond",
        r["boundary_bond_error_A"],
        "angle",
        r["max_boundary_angle_error_deg"],
        "stereo",
        r["stereochemistry_passed"],
    )
