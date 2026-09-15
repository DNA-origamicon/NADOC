from pathlib import Path
import json, shutil, tarfile

ROOT = Path(__file__).resolve().parent
out = ROOT / "full_nve"
out.mkdir(exist_ok=True)
plan = json.loads((ROOT / "campaign.json").read_text())
cases = []
for geometry in ["ads5", "ads10", "biotin10"]:
    base = next(x for x in plan["cases"] if x["geometry"] == geometry)
    for variant in ["combined_epsilon1", "combined_epsilon2"]:
        for dt in [0.0001, 0.00005, 0.000025]:
            c = dict(base)
            s = dict(base["settings"])
            steps = round(1 / dt)
            s.update(
                steps=steps,
                dt=dt,
                thermostat="no",
                refresh_vel="false",
                seed=3191,
                print_conf_interval=steps // 200,
                print_energy_every=steps // 200,
            )
            c.update(name=f"{geometry}_{variant}_{dt}", variant=variant, settings=s)
            cases.append(c)
(out / "campaign.json").write_text(
    json.dumps(
        dict(
            cases=cases,
            criteria=dict(max_range_kBT_per_DOF=0.001, quadratic_exponent=[1.5, 2.5]),
        ),
        indent=2,
    )
)
for name in ["fixtures", "engines"]:
    if not (out / name).exists():
        (out / name).symlink_to("../" + name, target_is_directory=True)
shutil.copy2(ROOT / "full_nve_worker.py", out / "worker.py")
slurm = (
    (ROOT / "alpine_runs.sbatch")
    .read_text()
    .replace("0-53%18", "0-17%18")
    .replace("oxdna_physics_ab", "oxdna_ab_nve")
    .replace("python3 campaign_worker.py", "python3 worker.py")
)
(out / "alpine_runs.sbatch").write_text(slurm)
with tarfile.open(ROOT / "full_nve_inputs.tar.gz", "w:gz") as t:
    for name in ["campaign.json", "worker.py", "alpine_runs.sbatch"]:
        t.add(out / name, arcname=name)
print("Prepared", len(cases), "full-build NVE cases per backend")
