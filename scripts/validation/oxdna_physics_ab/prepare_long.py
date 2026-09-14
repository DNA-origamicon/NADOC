from pathlib import Path
import json, shutil, tarfile

ROOT = Path(__file__).resolve().parent
out = ROOT / "long_campaign"
out.mkdir(exist_ok=True)
plan = json.loads((ROOT / "campaign.json").read_text())
plan["cases"] = [
    x
    for x in plan["cases"]
    if x["geometry"] == "biotin10"
    and x["arm"] in ["A_baseline", "B_current_K", "E_brownian_eps1"]
]
for x in plan["cases"]:
    x["settings"].update(
        steps=1000000, print_conf_interval=5000, print_energy_every=5000
    )
plan.update(
    steps=1000000,
    purpose="Post-screen convergence follow-up; preserves original screening results",
    selection="Most complex biotin-linked geometry; baseline, current-K, and matched-amplitude local bath",
    timeout=6000,
)
(out / "campaign.json").write_text(json.dumps(plan, indent=2))
worker = (ROOT / "campaign_worker.py").read_text()
worker = worker.replace("timeout=1200", "timeout=6000")
(out / "campaign_worker.py").write_text(worker)
shutil.copy2(
    ROOT / "collect_fixed_gold_metrics.py", out / "collect_fixed_gold_metrics.py"
)
for name in ["fixtures", "engines"]:
    if not (out / name).exists():
        (out / name).symlink_to("../" + name, target_is_directory=True)
slurm = (
    (ROOT / "alpine_runs.sbatch")
    .read_text()
    .replace("00:30:00", "01:15:00")
    .replace("0-53%18", "0-8%9")
    .replace("oxdna_physics_ab", "oxdna_ab_long")
)
(out / "alpine_runs.sbatch").write_text(slurm)
with tarfile.open(ROOT / "long_inputs.tar.gz", "w:gz") as t:
    for name in [
        "campaign.json",
        "campaign_worker.py",
        "collect_fixed_gold_metrics.py",
        "alpine_runs.sbatch",
    ]:
        t.add(out / name, arcname=name)
print("Prepared", len(plan["cases"]), "long cases per backend")
