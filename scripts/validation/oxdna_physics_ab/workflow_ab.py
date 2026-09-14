"""Native A/B of explicit workflow choices; candidate renderer stays isolated."""

import sys, json, importlib.util, difflib
import numpy as np
from ab_common import ROOT, run, settings_for, fixture

sys.path.insert(0, str(ROOT.parents[2]))
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input

source = (ROOT.parents[2] / "backend/core/oxdna_protocol.py").read_text()
candidate = source.replace(
    "    bussi_tau: int = 1000",
    "    diff_coeff: float | None = None\n    refresh_vel: bool = True\n    bussi_tau: int = 1000",
).replace(
    '        lines.append("refresh_vel = true")',
    '        lines.append(f"refresh_vel = {str(spec.refresh_vel).lower()}")',
    1,
)
needle = '        lines.append(f"newtonian_steps = {spec.newtonian_steps}")'
candidate = candidate.replace(
    needle,
    """        if spec.thermostat in ("john", "brownian", "langevin"):
            if spec.diff_coeff is None or spec.diff_coeff <= 0:
                raise ValueError("An explicit positive diffusion coefficient is required")
            lines.append(f"diff_coeff = {spec.diff_coeff}")
"""
    + needle,
)
path = ROOT / "candidate_protocol.py"
path.write_text(candidate)
(ROOT / "workflow_candidate.patch").write_text(
    "".join(
        difflib.unified_diff(
            source.splitlines(True),
            candidate.splitlines(True),
            fromfile="a/backend/core/oxdna_protocol.py",
            tofile="b/backend/core/oxdna_protocol.py",
        )
    )
)
spec = importlib.util.spec_from_file_location("backend.core._audit_protocol", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
rows = []


def add(r):
    rows.append(r)
    (ROOT / "workflow.json").write_text(json.dumps(rows, indent=2))


def parsed(text):
    return dict(
        (k.strip(), v.strip())
        for k, v in [x.split("=", 1) for x in text.splitlines() if "=" in x]
    )


kwargs = dict(
    name="audit",
    kind="equil",
    sim_type="MD",
    steps=100,
    backend="CPU",
    seed=1919,
    thermostat="john",
    interaction="DNANM",
    parfile="anm.par",
    absolute_forces=True,
)
f = fixture("ads5")
for version, cls, renderer, extra in [
    ("old", OxdnaStageSpec, render_stage_input, {}),
    (
        "candidate",
        module.OxdnaStageSpec,
        module.render_stage_input,
        {"diff_coeff": 0.1, "refresh_vel": False},
    ),
]:
    s = parsed(
        renderer(
            cls(**kwargs, **extra),
            str(f / "topology.top"),
            str(f / "conf.dat"),
            parfile_name=str(f / "anm.par"),
        )
    )
    s.update(
        dt=0.0001,
        fix_diffusion="false",
        print_conf_interval=100,
        print_energy_every=100,
    )
    r = run("renderer_" + version, "baseline", s, True)
    r.update(test="brownian_renderer", version=version)
    add(r)
# Existing Bussi defaults must render byte-for-byte identically.
kwargs["thermostat"] = "bussi"
a = render_stage_input(OxdnaStageSpec(**kwargs), "topology.top", "conf.dat")
b = module.render_stage_input(
    module.OxdnaStageSpec(**kwargs), "topology.top", "conf.dat"
)
add(dict(test="unchanged_default_render", identical=a == b))
# Expanded ordinary DNA force/torque controls, no bath, no cap, small impulse.
f = fixture("dna")
a = np.loadtxt(
    ROOT / "runs/perf_dna_john_rigid_mask_CPU_0_baseline/last_conf.dat", skiprows=3
)
a[:, 9:12] = 0
a[:, 12:] = [1e-9, -2e-9, 3e-9]
conf = ROOT / "dna_impulse.dat"
with conf.open("w") as out:
    out.write("t = 0\nb = 90 90 90\nE = 0 0 0\n")
    np.savetxt(out, a, fmt="%.17g")
for salt, temperature, average in [
    (0.1, "280K", True),
    (0.5, "296K", True),
    (1.0, "320K", True),
    (0.5, "296K", False),
]:
    values = {}
    for backend in ["CPU", "CUDA"]:
        for variant in ["baseline", "combined_epsilon1", "combined_epsilon2"]:
            s = settings_for("dna", backend, 1, thermostat="no", cadence=1)
            s.update(
                dt=1e-6,
                conf_file=conf,
                refresh_vel="false",
                salt_concentration=salt,
                T=temperature,
                use_average_seq=str(average).lower(),
                seq_dep_file=ROOT / "source/oxDNA2_sequence_dependent_parameters.txt",
            )
            label = f"dna_force_{salt}_{temperature}_{average}_{backend}_{variant}"
            r = run(label, variant, s, True)
            r.update(
                test="dna_impulse", salt=salt, temperature=temperature, average=average
            )
            if not r.get("error"):
                z = np.loadtxt(ROOT / "runs" / label / "last_conf.dat", skiprows=3)
                values[backend, variant] = (z[:, 9:] - a[:, 9:]) / 1e-6
                r["force_norm"] = float(np.linalg.norm(values[backend, variant][:, :3]))
                r["potential_per_particle"] = float(
                    np.atleast_2d(np.loadtxt(ROOT / "runs" / label / "energy.dat"))[
                        -1, 1
                    ]
                )
                if variant != "baseline":
                    r["same_backend_max_difference"] = float(
                        abs(
                            values[backend, variant] - values[backend, "baseline"]
                        ).max()
                    )
                if backend == "CUDA":
                    x = values["CPU", variant]
                    y = values["CUDA", variant]
                    r["CPU_GPU_force_normalized_error"] = float(
                        np.linalg.norm(x[:, :3] - y[:, :3])
                        / max(1, np.linalg.norm(x[:, :3]))
                    )
                    r["CPU_GPU_torque_normalized_error"] = float(
                        np.linalg.norm(x[:, 3:] - y[:, 3:])
                        / max(1, np.linalg.norm(x[:, 3:]))
                    )
            add(r)
# Cap and velocity handoff one-factor tests at one step avoid chaotic divergence.
for backend in ["CPU", "CUDA"]:
    for control, extra in [
        ("uncapped", {}),
        ("cap50", {"max_backbone_force": 50}),
        ("refresh", {"refresh_vel": "true"}),
    ]:
        s = settings_for("dna", backend, 1, thermostat="no", cadence=1)
        s.update(
            dt=1e-6,
            conf_file=conf,
            refresh_vel="false",
            **({} if control == "refresh" else extra),
        )
        if control == "refresh":
            s.update(extra)
        label = f"handoff_{backend}_{control}"
        r = run(label, "baseline", s, True)
        r.update(test="handoff_cap", control=control)
        if not r.get("error"):
            z = np.loadtxt(ROOT / "runs" / label / "last_conf.dat", skiprows=3)
            if control == "uncapped":
                base = z
            else:
                r["max_velocity_difference"] = float(
                    abs(z[:, 9:12] - base[:, 9:12]).max()
                )
                r["max_position_difference"] = float(abs(z[:, :3] - base[:, :3]).max())
        add(r)
# Same physical Bussi coupling duration: same application count and random stream.
sys.path.insert(0, str(ROOT.parents[2] / "scripts/validation/oxdna_physics_audit"))
import thermostat_audit as t

t.ROOT = ROOT / "workflow_thermostat"
t.ENGINE = ROOT / "engines/current_k/bin/oxDNA"
for dt, tau, interval in [(0.001, 1000, 10), (0.0005, 2000, 20), (0.0005, 1000, 20)]:
    r = t.run(
        f"tau_{dt}_{tau}",
        "CPU",
        "bussi",
        t.fixture(protein=0, hot=True),
        0,
        round(1 / dt),
        dt=dt,
        stride=round(0.1 / dt),
        settings=f"newtonian_steps = {interval}\nbussi_tau = {tau}",
    )
    r.update(test="physical_tau", dt=dt, tau=tau, physical_tau=dt * tau)
    add(r)

# A legal stretched bond activates the cap; neither case is a claim about an equilibrium ensemble.
f = ROOT / "stretched_bond"
f.mkdir(exist_ok=True)
(f / "topology.top").write_text("2 1\n1 A -1 1\n1 T 0 -1\n")
a = np.zeros((2, 15))
a[:, 3] = 1
a[:, 8] = 1
a[1, 2] = 0.995
a[:, 12:] = 1e-9
with (f / "conf.dat").open("w") as out:
    out.write("t = 0\nb = 20 20 20\nE = 0 0 0\n")
    np.savetxt(out, a, fmt="%.17g")
for backend in ["CPU", "CUDA"]:
    for capped in [False, True]:
        s = settings_for("dna", backend, 1, thermostat="no", cadence=1)
        s.update(
            dt=1e-6,
            topology=f / "topology.top",
            conf_file=f / "conf.dat",
            refresh_vel="false",
        )
        if capped:
            s["max_backbone_force"] = 50
        r = run(f"stretched_{backend}_{capped}", "baseline", s, True)
        r.update(test="active_cap", capped=capped)
        if not r.get("error"):
            z = np.loadtxt(ROOT / "runs" / r["label"] / "last_conf.dat", skiprows=3)
            r["force_norm"] = float(np.linalg.norm(z[:, 9:12]) / 1e-6)
        add(r)
for backend in ["CPU", "CUDA"]:
    for variant in ["baseline", "combined_epsilon1"]:
        for dt in [0.001, 0.0005, 0.00025]:
            s = settings_for(
                "dna", backend, round(1 / dt), thermostat="no", cadence=round(0.01 / dt)
            )
            s.update(dt=dt, conf_file=conf, refresh_vel="false")
            r = run(
                f"dna_nve_{backend}_{variant}_{dt}",
                "baseline" if variant == "baseline" else "combined_epsilon1",
                s,
                True,
            )
            r.update(test="dna_nve", dt=dt)
            if not r.get("error"):
                e = np.loadtxt(ROOT / "runs" / r["label"] / "energy.dat")
                tot = e[:, 1] + e[:, 2]
                r["energy_range_per_particle"] = float(np.ptp(tot))
                r["energy_relative_range"] = float(
                    np.ptp(tot) / max(abs(tot[0]), 1e-15)
                )
            add(r)
# CUDA atomic reductions need a baseline-versus-baseline repeatability control.
# Compare like-duration repeated runs before attributing trajectory divergence to a patch.
for variant in ["baseline", "rigid_mask"]:
    for rep in range(2):
        s = settings_for("cage", "CUDA", 10000, 4001, "john", cadence=100)
        s.update(T="300K", diff_coeff=2.5, newtonian_steps=103)
        r = run(f"cage_repeat_{variant}_{rep}", variant, s, True)
        r.update(test="cuda_repeatability", replicate=rep)
        add(r)

print("Workflow tests complete", flush=True)
