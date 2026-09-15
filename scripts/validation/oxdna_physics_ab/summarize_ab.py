"""Derived-only audit summary. Independent seeds, not frames, determine intervals."""

from pathlib import Path
import json, math, hashlib
import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def read(name, default=None):
    p = ROOT / name
    return json.loads(p.read_text()) if p.exists() else default


def ci(a, confidence=0.95):
    a = np.asarray(a, dtype=float)
    n = len(a)
    mean = float(a.mean())
    if n < 2:
        return dict(n=n, mean=mean, ci=None)
    half = float(stats.t.ppf((1 + confidence) / 2, n - 1) * a.std(ddof=1) / np.sqrt(n))
    return dict(n=n, mean=mean, ci=[mean - half, mean + half])


def ess(a):
    a = np.asarray(a, dtype=float)
    a = a - a.mean()
    n = len(a)
    v = np.dot(a, a)
    if v == 0:
        return float(n)
    ac = np.correlate(a, a, "full")[n - 1 :] / v
    total = 0
    for i in range(1, n - 1, 2):
        pair = ac[i] + ac[i + 1]
        if pair <= 0:
            break
        total += pair
    return float(min(n, n / max(1, 1 + 2 * total)))


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


out = dict(
    scope="Isolated A/B candidates, no installed-engine or application-default promotion",
    provenance=read("baseline_provenance.json"),
    functional=read("functional.json", []),
    force_controls=[],
    local_gpu="RTX 2080 SUPER",
    remote_cpu_job="32541315",
    new_runpod_compute_spend_usd=0,
)
for v in [
    "baseline",
    "gpu_epsilon1",
    "cpu_epsilon2",
    "combined_epsilon1",
    "combined_epsilon2",
]:
    data = read("functional/" + v + "/pair_report.json", {})
    if not data:
        continue
    errors = []
    mismatches = []
    zero = []
    for c in data["cases"]:
        fs = {}
        for x in c["runs"]:
            epsilon = (
                2
                if not c["name"].startswith("protein_")
                and (
                    v in ["cpu_epsilon2", "combined_epsilon2"]
                    or (v == "baseline" and x["backend"] == "CUDA")
                )
                else 1
            )
            f = np.array(c["force"]) * epsilon
            t = np.array(c["torque"]) * epsilon
            errors.append(
                max(
                    float(
                        np.linalg.norm(np.array(x["force"]) - f)
                        / max(1, np.linalg.norm(f))
                    ),
                    float(
                        np.linalg.norm(np.array(x["torque"]) - t)
                        / max(1, np.linalg.norm(t))
                    ),
                )
            )
            fs[x["backend"], x["dt"]] = np.array(x["force"])
            if not np.linalg.norm(f):
                zero.append(float(np.linalg.norm(x["force"])))
        for dt in [1e-5, 1e-6]:
            a, b = fs["CPU", dt], fs["CUDA", dt]
            mismatches.append(float(np.linalg.norm(a - b) / max(1, np.linalg.norm(a))))
    out["force_controls"].append(
        dict(
            variant=v,
            runs=sum(len(x["runs"]) for x in data["cases"]),
            max_error_vs_intended_amplitude=max(errors),
            max_CPU_GPU_error=max(mismatches),
            max_outside_force=max(zero),
        )
    )
extended = read("extended.json", [])
probe = read("dna_probe.json", [])
additional = read("additional.json", [])
out["additional_controls"] = additional
perf = extended + [x for x in probe + additional if x["test"] == "performance"]
groups = {}
failed = []
for x in perf:
    if x["test"] != "performance":
        continue
    if "error" in x or x["exit_code"] != 0:
        failed.append(dict(label=x["label"], error=x.get("error")))
        continue
    key = (x["geometry"], x["thermostat"], x["candidate"], x["backend"])
    groups.setdefault(key, {}).setdefault(x["replicate"], {})[x["variant"]] = x
out["performance"] = []
for (g, t, v, b), reps in groups.items():
    pairs = [x for x in reps.values() if "baseline" in x and v in x]
    if len(pairs) < 2:
        continue
    ratios = np.log(
        [x[v]["wall_seconds"] / x["baseline"]["wall_seconds"] for x in pairs]
    )
    c = ci(ratios)
    bounds = np.exp(c["ci"]).tolist()
    out["performance"].append(
        dict(
            geometry=g,
            thermostat=t,
            candidate=v,
            backend=b,
            pairs=len(pairs),
            wall_ratio_geometric_mean=float(np.exp(c["mean"])),
            ratio_95ci=bounds,
            baseline_median_seconds=float(
                np.median([x["baseline"]["wall_seconds"] for x in pairs])
            ),
            candidate_median_seconds=float(
                np.median([x[v]["wall_seconds"] for x in pairs])
            ),
            reproducible_slowdown=bounds[0] > 1,
            within_5percent_resolution=bounds[1] < 1.05,
        )
    )
out["failed_performance_runs"] = failed
out["uncapped_pair_nve"] = [x for x in extended if x["test"] == "uncapped_pair_nve"]
out["dna_starting_state_probe"] = probe
out["workflow_original"] = read("workflow_original.json", [])
out["workflow"] = read("workflow.json", [])
out["high_precision_saved_frame_energy"] = read("precise_energy.json", [])
out["interacting_mask_identity"] = read("interacting_mask_identity.json", [])
# Completed CPU/GPU independent replicas; values are in kelvin or stated nm units.
plan = read("campaign.json")
cases = {x["name"]: x for x in plan["cases"]}
completed = []
pending = []
failures = []
group = {}
for backend in ["CPU", "CUDA"]:
    for i, c in enumerate(plan["cases"]):
        x = read("status_" + backend + "/" + str(i) + ".json", {})
        if x.get("state") == "failed":
            failures.append(x)
        if x.get("state") != "completed":
            pending.append(
                dict(backend=backend, index=i, state=x.get("state", "not_started"))
            )
            continue
        m = dict(x["metrics"]["means"])
        n, prot = c["particles"], c["protein"]
        dna = n - prot
        m["DNA_trans_T"] = m["dna_translational_per_particle"] * 2000
        m["DNA_rot_T"] = m["dna_rotational_per_particle"] * 2000
        m["protein_trans_T"] = (
            (
                n * m["kinetic_per_particle"]
                - dna
                * (
                    m["dna_translational_per_particle"]
                    + m["dna_rotational_per_particle"]
                )
            )
            / prot
            * 2000
        )
        summary = dict(
            backend=backend,
            case=c["name"],
            seed=c["seed"],
            geometry=c["geometry"],
            arm=c["arm"],
            means=m,
            frames=x["metrics"]["frames"],
            final_step=x["metrics"]["final_step"],
            minimum_clearance_nm=x["metrics"]["minimum_clearance_nm"],
            wall_seconds=x["wall_seconds"],
            binary_sha256=x["binary_sha256"],
        )
        diagnostics = {}
        for metric in [
            "dna_translational_per_particle",
            "dna_tip_radius_nm",
            "protein_rg_nm",
        ]:
            v = x["metrics"]["series"][metric]
            k = len(v) // 2
            diagnostics[metric] = dict(
                ESS_second_half=ess(v[k:]),
                first_half_mean=float(np.mean(v[:k])),
                second_half_mean=float(np.mean(v[k:])),
            )
        summary["mixing_diagnostics"] = diagnostics
        completed.append(summary)
        group.setdefault((backend, c["geometry"], c["arm"]), []).append(summary)
out["campaign"] = dict(
    expected=108,
    completed=len(completed),
    pending=pending,
    failed=failures,
    replicas=completed,
    groups=[],
    temperature_tests=[],
)
for (backend, g, arm), replicas in group.items():
    means = {k: ci([x["means"][k] for x in replicas]) for k in replicas[0]["means"]}
    out["campaign"]["groups"].append(
        dict(backend=backend, geometry=g, arm=arm, means=means)
    )
    if len(replicas) == 3:
        for metric in ["DNA_trans_T", "DNA_rot_T", "protein_trans_T"]:
            a = np.array([x["means"][metric] for x in replicas])
            test = stats.ttest_1samp(a, 296)
            out["campaign"]["temperature_tests"].append(
                dict(
                    backend=backend,
                    geometry=g,
                    arm=arm,
                    metric=metric,
                    p=float(test.pvalue),
                    **ci(a),
                )
            )
# Holm family: all complete arm/geometry/backend/subsystem tests; final family 108.
tests = out["campaign"]["temperature_tests"]
ordered = sorted(tests, key=lambda x: x["p"])
previous = 0
for i, x in enumerate(ordered):
    previous = max(previous, min(1, x["p"] * (len(ordered) - i)))
    x["holm_p"] = previous
    x["reject_296K"] = previous < 0.05
out["campaign"]["temperature_family_complete"] = len(tests) == 108
out["campaign"]["within_backend_contrasts"] = []
for backend in ["CPU", "CUDA"]:
    for geometry in ["ads5", "ads10", "biotin10"]:
        for baseline, candidate in [
            ("A_baseline", "B_current_K"),
            ("A_baseline", "C_brownian_2p5"),
            ("C_brownian_2p5", "D_brownian_0p1"),
            ("D_brownian_0p1", "E_brownian_eps1"),
            ("D_brownian_0p1", "F_brownian_eps2"),
        ]:
            a = {x["seed"]: x for x in group.get((backend, geometry, baseline), [])}
            b = {x["seed"]: x for x in group.get((backend, geometry, candidate), [])}
            seeds = sorted(set(a) & set(b))
            if len(seeds) < 2:
                continue
            differences = {
                k: ci([b[s]["means"][k] - a[s]["means"][k] for s in seeds])
                for k in [
                    "DNA_trans_T",
                    "DNA_rot_T",
                    "protein_trans_T",
                    "dna_tip_radius_nm",
                    "protein_rg_nm",
                    "anchor_rms_nm",
                    "anm_rms_extension_nm",
                ]
            }
            out["campaign"]["within_backend_contrasts"].append(
                dict(
                    backend=backend,
                    geometry=geometry,
                    baseline=baseline,
                    candidate=candidate,
                    differences=differences,
                )
            )
out["campaign"]["CPU_GPU_contrasts"] = []
for g in ["ads5", "ads10", "biotin10"]:
    for arm in ["E_brownian_eps1", "F_brownian_eps2"]:
        a = {x["seed"]: x for x in group.get(("CPU", g, arm), [])}
        b = {x["seed"]: x for x in group.get(("CUDA", g, arm), [])}
        seeds = sorted(set(a) & set(b))
        if len(seeds) < 2:
            continue
        d = {
            k: ci([b[s]["means"][k] - a[s]["means"][k] for s in seeds])
            for k in [
                "DNA_trans_T",
                "DNA_rot_T",
                "protein_trans_T",
                "dna_tip_radius_nm",
                "protein_rg_nm",
                "anchor_rms_nm",
                "anm_rms_extension_nm",
            ]
        }
        out["campaign"]["CPU_GPU_contrasts"].append(
            dict(geometry=g, arm=arm, difference_GPU_minus_CPU=d)
        )
sens = read("sensitivity.json", [])
sg = {}
for x in sens:
    if "error" not in x and x["exit_code"] == 0:
        sg.setdefault(x["prior"], []).append(x)
out["sensitivity_diagnostics"] = read("sensitivity_diagnostics.json", [])
out["final_provenance"] = read("final_provenance.json", {})
out["application_source_hashes"] = read("application_source_hashes.json", {})
out["application_renderer_unchanged"] = all(
    hashlib.sha256((REPO / f).read_bytes()).hexdigest() == v
    for f, v in out["application_source_hashes"].items()
)
out["sensitivity"] = dict(
    completed=sum(len(x) for x in sg.values()),
    failed=[x for x in sens if "error" in x],
    groups=[],
)
for prior, reps in sg.items():
    means = {
        k: ci([x["means_second_half"][k] for x in reps])
        for k in reps[0]["means_second_half"]
    }
    out["sensitivity"]["groups"].append(dict(prior=prior, means=means))
# Provenance check of unchanged installed engine and source patch.
installed = Path(out["provenance"]["installed_engine"])
out["installed_binary_unchanged"] = (
    hashlib.sha256(installed.read_bytes()).hexdigest() == out["provenance"]["sha256"]
)
# Longer follow-up is reported separately and never substitutes for the screen.
long_plan = read("long_campaign/campaign.json", {})
long_rows = []
long_pending = []
long_groups = {}
for backend in ["CPU", "CUDA"]:
    for i, c in enumerate(long_plan.get("cases", [])):
        x = read("long_campaign/status_" + backend + "/" + str(i) + ".json", {})
        if x.get("state") != "completed":
            long_pending.append(
                dict(
                    backend=backend,
                    index=i,
                    state=x.get("state", "not_started"),
                    error=x.get("error"),
                )
            )
            continue
        m = dict(x["metrics"]["means"])
        n, prot = c["particles"], c["protein"]
        dna = n - prot
        m["DNA_trans_T"] = m["dna_translational_per_particle"] * 2000
        m["DNA_rot_T"] = m["dna_rotational_per_particle"] * 2000
        m["protein_trans_T"] = (
            (
                n * m["kinetic_per_particle"]
                - dna
                * (
                    m["dna_translational_per_particle"]
                    + m["dna_rotational_per_particle"]
                )
            )
            / prot
            * 2000
        )
        diag = {}
        for metric in [
            "dna_translational_per_particle",
            "dna_rotational_per_particle",
            "dna_tip_radius_nm",
        ]:
            v = x["metrics"]["series"][metric]
            half = len(v) // 2
            diag[metric] = dict(
                ESS_second_half=ess(v[half:]),
                first_half_mean=float(np.mean(v[:half])),
                second_half_mean=float(np.mean(v[half:])),
            )
        row = dict(
            backend=backend,
            arm=c["arm"],
            seed=c["seed"],
            means=m,
            diagnostics=diag,
            wall_seconds=x["wall_seconds"],
            final_step=x["metrics"]["final_step"],
            frames=x["metrics"]["frames"],
            minimum_clearance_nm=x["metrics"]["minimum_clearance_nm"],
            binary_sha256=x["binary_sha256"],
        )
        long_rows.append(row)
        long_groups.setdefault((backend, c["arm"]), []).append(row)
out["long_followup"] = dict(
    expected=18,
    completed=len(long_rows),
    pending=long_pending,
    replicas=long_rows,
    groups=[],
    temperature_tests=[],
    within_backend_contrasts=[],
    CPU_GPU_contrasts=[],
)
for (backend, arm), replicas in long_groups.items():
    means = {k: ci([x["means"][k] for x in replicas]) for k in replicas[0]["means"]}
    out["long_followup"]["groups"].append(dict(backend=backend, arm=arm, means=means))
    if len(replicas) == 3:
        for metric in ["DNA_trans_T", "DNA_rot_T", "protein_trans_T"]:
            values = [x["means"][metric] for x in replicas]
            p = float(stats.ttest_1samp(values, 296).pvalue)
            out["long_followup"]["temperature_tests"].append(
                dict(backend=backend, arm=arm, metric=metric, p=p, **ci(values))
            )
ordered = sorted(out["long_followup"]["temperature_tests"], key=lambda x: x["p"])
previous = 0
for i, x in enumerate(ordered):
    previous = max(previous, min(1, x["p"] * (len(ordered) - i)))
    x["holm_p"] = previous
    x["reject_296K"] = previous < 0.05
for backend in ["CPU", "CUDA"]:
    a = {x["seed"]: x for x in long_groups.get((backend, "A_baseline"), [])}
    for arm in ["B_current_K", "E_brownian_eps1"]:
        b = {x["seed"]: x for x in long_groups.get((backend, arm), [])}
        seeds = sorted(set(a) & set(b))
        if len(seeds) < 2:
            continue
        differences = {
            k: ci([b[s]["means"][k] - a[s]["means"][k] for s in seeds])
            for k in [
                "DNA_trans_T",
                "DNA_rot_T",
                "protein_trans_T",
                "dna_tip_radius_nm",
                "anchor_rms_nm",
                "anm_rms_extension_nm",
            ]
        }
        out["long_followup"]["within_backend_contrasts"].append(
            dict(
                backend=backend,
                candidate=arm,
                differences=differences,
                descriptive_wall_ratio=ci(
                    [b[s]["wall_seconds"] / a[s]["wall_seconds"] for s in seeds]
                ),
            )
        )
a = {x["seed"]: x for x in long_groups.get(("CPU", "E_brownian_eps1"), [])}
b = {x["seed"]: x for x in long_groups.get(("CUDA", "E_brownian_eps1"), [])}
seeds = sorted(set(a) & set(b))
if len(seeds) > 1:
    out["long_followup"]["CPU_GPU_contrasts"].append(
        {
            k: ci([b[s]["means"][k] - a[s]["means"][k] for s in seeds])
            for k in [
                "DNA_trans_T",
                "DNA_rot_T",
                "protein_trans_T",
                "dna_tip_radius_nm",
                "anchor_rms_nm",
                "anm_rms_extension_nm",
            ]
        }
    )

# Full-build NVE: conservation and second-order scaling are distinct gates.
nve_plan = read("full_nve/campaign.json", {})
nve_rows = []
nve_pending = []
nve_groups = {}
for backend in ["CPU", "CUDA"]:
    for i, c in enumerate(nve_plan.get("cases", [])):
        x = read("full_nve/status_" + backend + "/" + str(i) + ".json", {})
        if x.get("state") != "completed":
            nve_pending.append(
                dict(
                    backend=backend,
                    index=i,
                    state=x.get("state", "not_started"),
                    error=x.get("error"),
                )
            )
            continue
        nve_rows.append(x)
        nve_groups.setdefault((backend, c["geometry"], c["variant"]), []).append(x)
out["full_build_nve"] = dict(
    expected=36,
    completed=len(nve_rows),
    pending=nve_pending,
    criteria=nve_plan.get("criteria"),
    replicas=nve_rows,
    groups=[],
)
for (backend, geometry, variant), rows in nve_groups.items():
    rows = sorted(rows, key=lambda x: x["dt"], reverse=True)
    exponents = [math.log2(a["sigma"] / b["sigma"]) for a, b in zip(rows, rows[1:])]
    out["full_build_nve"]["groups"].append(
        dict(
            backend=backend,
            geometry=geometry,
            variant=variant,
            dt=[x["dt"] for x in rows],
            ranges_kBT_per_DOF=[x["range_kBT_per_DOF"] for x in rows],
            sigma=[x["sigma"] for x in rows],
            exponents=exponents,
            conservation_pass=all(x["conservation_pass"] for x in rows),
            quadratic_scaling_pass=len(rows) == 3
            and all(1.5 <= v <= 2.5 for v in exponents),
        )
    )
out["long_followup"]["cpu_timing_hardware"] = {
    "indices_0_through_6": "c3cpu-e2-u3: Genoa EPYC 9534",
    "index_7": "c3cpu-c15-u1-1: Milan EPYC 7713",
    "index_8": "c3cpu-c13-u1-1: Milan EPYC 7713P",
    "limitation": "Long-run CPU wall ratios are confounded by CPU generation; use randomized same-hardware controls for code overhead.",
}

out["acceptance_summary"] = {
    "candidate_promoted": False,
    "protein_DNA_numerical_matching": "Both amplitude choices pass isolated controls; experimentally intended amplitude unresolved",
    "Bussi_current_K_limit": "Candidate passes; baseline fails vanishing-coupling limit",
    "point_rotation_mask": "Tested physical identity and point-angular-momentum controls pass; ensemble equivalence not established",
    "ordinary_DNA2_average_parameters": "Default CPU/GPU force matching fails; upstream explicit average-file input passes tested controls",
    "raw_ideal_DNA_CUDA": "Fails with nonfinite output; zero-vector guard not built or tested",
    "full_build_NVE_conservation": "pending"
    if len(nve_rows) != 36
    else ("pass" if all(x["conservation_pass"] for x in nve_rows) else "fail"),
    "full_build_NVE_quadratic_scaling": "pending"
    if len(nve_rows) != 36
    else (
        "pass"
        if all(x["quadratic_scaling_pass"] for x in out["full_build_nve"]["groups"])
        else "not met"
    ),
    "CPU_GPU_ensemble_equivalence": "inconclusive; three replicas and substantial positional autocorrelation do not establish equivalence",
    "experimental_coating_validation": "unavailable; sensitivity tests do not establish accuracy",
    "runtime": "No reproducible slowdown detected in paired controls; small overhead and time per independent sample remain unresolved",
    "relaxation_efficiency": "Time to a common relaxation endpoint was not established; no default promoted on throughput alone",
}

path = REPO / "docs/validation/oxdna_physics_ab_2026-09-13.json"
path.write_text(json.dumps(clean(out), indent=2, allow_nan=False))
print(
    "summary:",
    out["campaign"]["completed"],
    "/108 campaign cases;",
    out["sensitivity"]["completed"],
    "/24 model-sensitivity cases",
)
print("temperature family complete:", out["campaign"]["temperature_family_complete"])
print(
    "reproducible slowdown:",
    [
        (x["geometry"], x["backend"], x["candidate"])
        for x in out["performance"]
        if x["reproducible_slowdown"]
    ],
)
