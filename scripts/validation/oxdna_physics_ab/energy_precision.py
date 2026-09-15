"""Re-evaluate saved NVE frames at 15-digit precision, with no new dynamics."""

from pathlib import Path
import json, subprocess
import numpy as np
from ab_common import ROOT

binary = Path.home() / ".local/share/nadoc/engines/oxdna/current/bin/DNAnalysis"
rows = []
inputs = json.loads((ROOT / "workflow.json").read_text()) + json.loads(
    (ROOT / "additional.json").read_text()
)
for r in inputs:
    if r["test"] not in ["dna_nve", "explicit_average_nve"] or "error" in r:
        continue
    original = ROOT / "runs" / r["label"]
    d = ROOT / "energy_analysis" / r["label"]
    d.mkdir(parents=True, exist_ok=True)
    settings = dict(
        (k.strip(), v.strip())
        for k, v in [
            line.split("=", 1)
            for line in (original / "input").read_text().splitlines()
            if "=" in line
        ]
    )
    trajectory = d / "frames.dat"
    trajectory.write_text(
        Path(settings["conf_file"]).read_text()
        + (original / "trajectory.dat").read_text()
    )
    settings.update(backend="CPU", trajectory_file=trajectory)
    text = "".join(f"{k} = {v}\n" for k, v in settings.items())
    text += """analysis_data_output_1 = {
name = precise.dat
print_every = 1
col_1 = {
type = step
}
col_2 = {
type = potential_energy
precision = 15
}
col_3 = {
type = kinetic_energy
precision = 15
}
}
"""
    (d / "input").write_text(text)
    with (d / "run.log").open("w") as log:
        p = subprocess.run(
            [str(binary), "input"],
            cwd=d,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
    if p.returncode:
        raise RuntimeError((d / "run.log").read_text()[-1500:])
    e = np.loadtxt(d / "precise.dat")
    energy = e[:, 1] + e[:, 2]
    out = dict(
        label=r["label"],
        test=r["test"],
        backend=r["backend"],
        variant=r["variant"],
        dt=r["dt"],
        samples=len(e),
        energy_range_per_particle=float(np.ptp(energy)),
        relative_energy_range=float(np.ptp(energy) / abs(energy[0])),
    )
    rows.append(out)
    (ROOT / "precise_energy.json").write_text(json.dumps(rows, indent=2))
    print(out, flush=True)
