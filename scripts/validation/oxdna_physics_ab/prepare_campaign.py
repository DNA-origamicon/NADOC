"""Frozen one-factor contrasts; independent seeds and identical physical duration."""

from pathlib import Path
import json
import shutil
import tarfile

from ab_common import ROOT, REPO, fixture, settings_for
from make_variants import BASE, FILES, current_k, epsilon, rigid_mask

arms = {
    "A_baseline": dict(variant="baseline", thermostat="bussi"),
    "B_current_K": dict(variant="current_k", thermostat="bussi"),
    "C_brownian_2p5": dict(variant="rigid_mask", thermostat="john", diff_coeff=2.5),
    "D_brownian_0p1": dict(variant="rigid_mask", thermostat="john", diff_coeff=0.1),
    "E_brownian_eps1": dict(
        variant="combined_epsilon1", thermostat="john", diff_coeff=0.1
    ),
    "F_brownian_eps2": dict(
        variant="combined_epsilon2", thermostat="john", diff_coeff=0.1
    ),
}
cases = []
for name in ["ads5", "ads10", "biotin10"]:
    common = fixture(name)
    for seed in [1709, 2801, 3911]:
        for arm, options in arms.items():
            settings = settings_for(
                name, "CPU", 100000, seed, options["thermostat"], cadence=500
            )
            if "diff_coeff" in options:
                settings["diff_coeff"] = options["diff_coeff"]
            # Reference fixture paths relative to the per-case run directory,
            # identical on Alpine and local hardware.
            for key in ["topology", "conf_file", "parfile", "external_forces_file"]:
                settings[key] = (
                    "../../fixtures/" + name + "/" + Path(settings[key]).name
                )
            top = (common / "topology.top").read_text().splitlines()[0].split()
            cases.append(
                dict(
                    name=f"{name}_{seed}_{arm}",
                    geometry=name,
                    seed=seed,
                    arm=arm,
                    variant=options["variant"],
                    settings=settings,
                    particles=int(top[0]),
                    protein=int(top[3]),
                    radius_nm=2.5 if name == "ads5" else 5.0,
                )
            )
plan = dict(
    seeds=[1709, 2801, 3911],
    steps=100000,
    dt=0.0001,
    replicas_are="independent seeds, not trajectory frames",
    arms=arms,
    cases=cases,
    comparisons={
        "B_vs_A": "Current kinetic energy handoff only, same backend amplitude.",
        "C_vs_A": "Bussi versus Brownian; rigid mask independently tested for unchanged physical trajectories.",
        "D_vs_C": "Brownian diffusion coefficient only.",
        "E_vs_D": "CUDA amplitude 2 to 1; CPU physical negative control.",
        "F_vs_D": "CPU amplitude 1 to 2; CUDA physical negative control.",
    },
    acceptance={
        "forces": "Normalized force and torque error < 1e-3; separate zero-force controls.",
        "weak_Bussi": "Off-target single-step K change < 0.1% at tau=1e9.",
        "rigid_mask": "Exactly zero point L; unchanged physical coordinates/velocities at same seed.",
        "sampling": "Report independent-seed intervals, stationarity and effective sample sizes; no equivalence claim from nonsignificance.",
        "performance": "Report paired ratios and uncertainty; hold any reproducible slowdown. Five percent is measurement-resolution target, not an authorized slowdown.",
        "model_parameters": "Sensitivity results, never experimental-accuracy claims without reference data.",
        "promotion": "No automatic production promotion or parameter choice from these tests.",
    },
)
(ROOT / "campaign.json").write_text(json.dumps(plan, indent=2))
for variant in [
    "baseline",
    "current_k",
    "rigid_mask",
    "combined_epsilon1",
    "combined_epsilon2",
]:
    files = dict(BASE)
    if variant in ["current_k", "combined_epsilon1", "combined_epsilon2"]:
        current_k(files)
    if variant in ["rigid_mask", "combined_epsilon1", "combined_epsilon2"]:
        rigid_mask(files)
    if variant == "combined_epsilon2":
        epsilon(files, 2)
    for name in [FILES[0], FILES[2], FILES[4]]:
        p = ROOT / "cpu_sources" / variant / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[name])
shutil.copy2(
    REPO / "scripts/validation/collect_fixed_gold_metrics.py",
    ROOT / "collect_fixed_gold_metrics.py",
)
for name in ["weak_CPU", "mask_CPU_john_32_0"]:
    destination = ROOT / "preflight_inputs" / name
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "functional/baseline/thermostats" / name).iterdir():
        if source.name in [
            "input",
            "conf.dat",
            "topology.top",
            "anm.par",
            "forces.txt",
        ]:
            shutil.copy2(source, destination / source.name)
with tarfile.open(ROOT / "cpu_inputs.tar.gz", "w:gz") as t:
    for path in [
        ROOT / "fixtures",
        ROOT / "cpu_sources",
        ROOT / "campaign.json",
        ROOT / "campaign_worker.py",
        ROOT / "collect_fixed_gold_metrics.py",
        ROOT / "alpine_native_build.sbatch",
        ROOT / "alpine_preflight.py",
        ROOT / "alpine_runs.sbatch",
        ROOT / "preflight_inputs",
    ]:
        t.add(path, arcname=path.name)
print("Prepared", len(cases), "matched cases per backend")
