"""Resolve glycosidic probe nonbonded energy differences into exact atom pairs."""

import json
from pathlib import Path
import sys
import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.core_baseline import checked, source, write

ART = Path(".development-artifacts").resolve()
root = ART / "cpd-anti-glycosidic-pairs-v1"
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
plan = json.loads((ART / "cpd-anti-glycosidic-probes-v1/plan.json").read_text())
groups = json.loads(
    (ART / "cpd-anti-glycosidic-decomposition-v1/assessment.json").read_text()
)
records = []
for ref in plan["references"]:
    e = ref["endpoint"]
    names = ref["names"]
    x = (
        np.array(json.loads(checked(ref["input"]).read_text())["geometry_bohr"])
        * 0.529177210903
    )
    sp = ART / f"cpd-anti-ordered-fit-v1/endpoint-{e}/system.xml"
    system = mm.XmlSerializer.deserialize(sp.read_text())
    force = next(f for f in system.getForces() if isinstance(f, mm.NonbondedForce))
    particles = []
    exceptions = {}
    for i in range(force.getNumParticles()):
        q, s, ep = force.getParticleParameters(i)
        particles.append(
            (
                q.value_in_unit(u.elementary_charge),
                s.value_in_unit(u.angstrom),
                ep.value_in_unit(u.kilocalorie_per_mole),
            )
        )
    for i in range(force.getNumExceptions()):
        a, b, q, s, ep = force.getExceptionParameters(i)
        exceptions[tuple(sorted((a, b)))] = (
            q.value_in_unit(u.elementary_charge**2),
            s.value_in_unit(u.angstrom),
            ep.value_in_unit(u.kilocalorie_per_mole),
        )
    for c in plan["cases"]:
        if c["endpoint"] != e:
            continue
        pos = (
            np.array(json.loads(checked(c["input"]).read_text())["geometry_bohr"])
            * 0.529177210903
        )
        pairs = []
        for i in range(len(x)):
            for j in range(i + 1, len(x)):
                q1, s1, ep1 = particles[i]
                q2, s2, ep2 = particles[j]
                q, s, ep = exceptions.get(
                    (i, j), (q1 * q2, (s1 + s2) / 2, np.sqrt(ep1 * ep2))
                )
                r0 = np.linalg.norm(x[i] - x[j])
                r1 = np.linalg.norm(pos[i] - pos[j])
                dc = 332.063713299 * q * (1 / r1 - 1 / r0)
                dl = (
                    4
                    * ep
                    * ((s / r1) ** 12 - (s / r1) ** 6 - (s / r0) ** 12 + (s / r0) ** 6)
                )
                pairs.append(
                    dict(
                        atoms=[names[i], names[j]],
                        exception=(i, j) in exceptions,
                        reference_distance_A=r0,
                        probe_distance_A=r1,
                        coulomb_delta_kcal_mol=dc,
                        lj_delta_kcal_mol=dl,
                        total_delta_kcal_mol=dc + dl,
                    )
                )
        coul = sum(p["coulomb_delta_kcal_mol"] for p in pairs)
        lj = sum(p["lj_delta_kcal_mol"] for p in pairs)
        expected = next(
            r
            for r in groups["records"]
            if r["endpoint"] == e
            and r["candidate"] == "baseline"
            and r["rotation_deg"] == c["rotation_deg"]
        )["delta_energy_terms_kcal_mol"]["NonbondedForce:6"]
        assert abs(coul + lj - expected) < 1e-5
        records.append(
            dict(
                endpoint=e,
                rotation_deg=c["rotation_deg"],
                coulomb_delta_kcal_mol=coul,
                lj_delta_kcal_mol=lj,
                openmm_total_agreement_error=abs(coul + lj - expected),
                largest_changes=sorted(
                    pairs, key=lambda p: abs(p["total_delta_kcal_mol"]), reverse=True
                )[:12],
                system=source(sp),
            )
        )
write(root / "assessment.json", dict(records=records, simulation_ready=False))
print(
    [
        (
            r["endpoint"],
            r["rotation_deg"],
            r["coulomb_delta_kcal_mol"],
            r["lj_delta_kcal_mol"],
            [
                (p["atoms"], round(p["total_delta_kcal_mol"], 2))
                for p in r["largest_changes"][:3]
            ],
        )
        for r in records
    ]
)
