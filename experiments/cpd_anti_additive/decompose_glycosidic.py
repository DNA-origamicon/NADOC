"""Force-group energy differences on fresh glycosidic probes, without refitting."""

import json
from pathlib import Path
import sys
import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.core_baseline import source, checked, write

ART = Path(".development-artifacts").resolve()
root = ART / "cpd-anti-glycosidic-decomposition-v1"
root.mkdir(exist_ok=False)
(root / "executed_source.py").write_text(Path(__file__).read_text())
probe = ART / "cpd-anti-glycosidic-probes-v1"
plan = json.loads((probe / "plan.json").read_text())
records = []
for ref in plan["references"]:
    e = ref["endpoint"]
    x = (
        np.array(json.loads(checked(ref["input"]).read_text())["geometry_bohr"])
        * 0.529177210903
    )
    for label, folder in [
        ("baseline", ART / "cpd-anti-ordered-fit-v1"),
        ("charge-1", ART / "cpd-anti-ordered-coupled-v1/geometry-1"),
    ]:
        path = folder / f"endpoint-{e}/system.xml"
        system = mm.XmlSerializer.deserialize(path.read_text())
        labels = []
        for i, f in enumerate(system.getForces()):
            f.setForceGroup(i)
            labels.append(type(f).__name__ + f":{i}")
        it = mm.VerletIntegrator(0.001)
        ctx = mm.Context(system, it, mm.Platform.getPlatformByName("Reference"))

        def terms(pos, ctx=ctx):
            ctx.setPositions(pos * u.angstrom)
            return [
                ctx.getState(getEnergy=True, groups=1 << i)
                .getPotentialEnergy()
                .value_in_unit(u.kilocalorie_per_mole)
                for i in range(len(labels))
            ]

        initial = np.array(terms(x))
        for c in plan["cases"]:
            if c["endpoint"] != e:
                continue
            pos = (
                np.array(json.loads(checked(c["input"]).read_text())["geometry_bohr"])
                * 0.529177210903
            )
            delta = np.array(terms(pos)) - initial
            records.append(
                dict(
                    endpoint=e,
                    candidate=label,
                    rotation_deg=c["rotation_deg"],
                    delta_energy_terms_kcal_mol=dict(zip(labels, delta.tolist())),
                    total_delta_energy_kcal_mol=float(delta.sum()),
                    system=source(path),
                )
            )
        del terms, ctx, it
write(
    root / "assessment.json",
    dict(
        records=records,
        simulation_ready=False,
        scope="MM force-group diagnostics on frozen geometries; no parameter update",
    ),
)
print(json.dumps(records, indent=2))
