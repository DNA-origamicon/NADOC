"""
oxDNA relaxation protocol — stage specs + per-stage input-file generation.

Implements the **standard oxDNA DNA-origami relaxation protocol**
(https://lorenzo-rovigatti.github.io/oxDNA/relaxation.html) as a fixed 3-stage
pipeline that walks a freshly-built (ideal B-DNA) origami toward a physically
relaxed coarse-grained configuration so a subsequent finer-grained (NAMD) run is
less likely to melt at startup:

  Stage 1 — mc       : Monte Carlo relaxation with the modified (capped) backbone
                       potential.  Removes issues needing only small nucleotide
                       displacements.  CPU only (oxDNA MC has no CUDA backend).
                       Standard keys: sim_type=MC, ensemble=NVT,
                       delta_translation=0.1, delta_rotation=0.1,
                       max_backbone_force=5, max_backbone_force_far=10,
                       steps 10²–10⁴.
  Stage 2 — md_relax : MD relaxation, still with the capped backbone potential, to
                       resolve larger-scale displacements.  CUDA-preferred.
                       Standard keys: sim_type=MD, dt=0.002, thermostat=bussi,
                       bussi_tau=1000, newtonian_steps=53, max_backbone_force=5/10,
                       steps ~1e6 (more for highly-stressed structures).
  Stage 3 — equil    : Short unbiased MD with the *standard* backbone potential
                       (force cap removed) — the transition to normal dynamics
                       before handing the relaxed structure onward.

Each stage continues from the previous stage's ``last_conf.dat`` (stage 1 starts
from the design's ``conf.dat``).  Input-file generation lives here (pure
functions → unit-testable); the runner (``oxdna_runner.py``) writes the files
and spawns oxDNA.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.oxdna_job import OxdnaStageStatus


# ── Stage spec ────────────────────────────────────────────────────────────────


@dataclass
class OxdnaStageSpec:
    name:                 str           # "1_mc_relax" / "2_md_relax" / "3_equil"
    kind:                 str           # "mc" / "md_relax" / "equil"
    sim_type:             str           # "MC" / "MD"
    steps:                int
    backend:              str           # "CPU" / "CUDA"
    temperature:          str = "296K"
    max_backbone_force:   float | None = None       # None → standard FENE (equil)
    max_backbone_force_far: float | None = None
    salt_concentration:   float = 0.5
    device:               str = "0"                  # CUDA device index
    # Monte Carlo keys (sim_type == MC)
    ensemble:             str = "NVT"
    delta_translation:    float = 0.1
    delta_rotation:       float = 0.1
    # Molecular dynamics keys (sim_type == MD)
    dt:                   float = 0.002
    thermostat:           str = "bussi"
    bussi_tau:            int = 1000
    newtonian_steps:      int = 53
    # Mutual-trap external forces holding designed WC pairs together (relax aid).
    external_forces:      bool = False
    # External-forces filename in the job dir; None → the default "forces.txt"
    # (mutual traps).  A field stage points this at its own field_forces_N.txt.
    forces_file:          str | None = None
    # Electric-field record (field stages only): {'dir':[x,y,z], 'force_oxdna':f}.
    efield:               dict | None = None
    # Health gate (checked after the stage).
    min_bp_retained:      float = 0.0

    def to_status(self) -> OxdnaStageStatus:
        return OxdnaStageStatus(name=self.name, kind=self.kind, steps=self.steps)


# ── Standard defaults (oxDNA origami relaxation docs) ─────────────────────────
DEFAULT_MC_STEPS:       int = 1_000        # 10²–10⁴ per docs
DEFAULT_MD_RELAX_STEPS: int = 1_000_000    # ~1e6 per docs
DEFAULT_EQUIL_STEPS:    int = 100_000      # short unbiased settle


def build_relaxation_stages(
    *,
    mc_steps:           int = DEFAULT_MC_STEPS,
    md_relax_steps:     int = DEFAULT_MD_RELAX_STEPS,
    equil_steps:        int = DEFAULT_EQUIL_STEPS,
    backend:            str = "CUDA",
    device:             str = "0",
    salt_concentration: float = 0.5,
    min_bp_retained:    float = 0.50,
) -> list[OxdnaStageSpec]:
    """Return the ordered 3-stage standard relaxation spec list.

    ``min_bp_retained`` is the base-pair-retention gate for the MD stages.  It is
    a *catastrophic-melt* detector, not a quality bar: relaxation inherently frays
    the lattice (especially ends), so the default is lenient (0.50) and the exact
    retention % is surfaced per stage as a health readout regardless.

    ``backend`` selects the runtime for the MD stages (2,3).  Stage 1 (MC) is
    always CPU — oxDNA's Monte Carlo backend is CPU-only — and the CUDA-built
    oxDNA binary runs the CPU backend fine.
    """
    return [
        OxdnaStageSpec(
            name="1_mc_relax", kind="mc", sim_type="MC", steps=mc_steps,
            backend="CPU",
            max_backbone_force=5.0, max_backbone_force_far=10.0,
            external_forces=True,          # mutual traps pull designed pairs together
            salt_concentration=salt_concentration, device=device,
            min_bp_retained=0.0,           # MC clears clashes; no bp gate yet
        ),
        OxdnaStageSpec(
            name="2_md_relax", kind="md_relax", sim_type="MD", steps=md_relax_steps,
            backend=backend, dt=0.002,
            max_backbone_force=5.0, max_backbone_force_far=10.0,
            external_forces=True,          # hold pairs while the backbone relaxes
            salt_concentration=salt_concentration, device=device,
            min_bp_retained=min_bp_retained,
        ),
        OxdnaStageSpec(
            name="3_equil", kind="equil", sim_type="MD", steps=equil_steps,
            backend=backend, dt=0.003,
            max_backbone_force=None, max_backbone_force_far=None,
            external_forces=False,         # unbiased: confirm the pairs self-sustain
            salt_concentration=salt_concentration, device=device,
            min_bp_retained=min_bp_retained,
        ),
    ]


# ── Input-file generation ─────────────────────────────────────────────────────


def render_stage_input(
    spec:          OxdnaStageSpec,
    topology_name: str,
    conf_name:     str,
    forces_name:   str | None = None,
) -> str:
    """Render the oxDNA input-file text for *spec*.

    ``conf_name`` is the starting configuration (the design's conf.dat for stage
    1, or the previous stage's last_conf.dat for later stages).  ``forces_name``
    is the mutual-trap external-forces file, referenced only when
    ``spec.external_forces`` is set.  Output files are emitted into the stage's
    own working directory: trajectory.dat / energy.dat / last_conf.dat.

    ``print_energy_every`` is sized to ~100 energy samples over the stage so the
    runner can derive live progress from the energy.dat line count.
    """
    print_energy_every = max(1, spec.steps // 100)
    print_conf_interval = max(1, spec.steps // 10)
    is_md = spec.sim_type == "MD"

    lines: list[str] = []

    # ── Backend ────────────────────────────────────────────────────────────────
    lines.append(f"backend = {spec.backend}")
    if spec.backend == "CUDA":
        lines.append("backend_precision = mixed")
        lines.append("CUDA_list = verlet")
        lines.append(f"CUDA_device = {spec.device}")
        lines.append("use_edge = true")

    # ── Simulation ──────────────────────────────────────────────────────────────
    lines.append("")
    lines.append(f"sim_type = {spec.sim_type}")
    lines.append(f"steps = {spec.steps}")
    lines.append("restart_step_counter = true")
    lines.append("verlet_skin = 0.20")
    lines.append(f"T = {spec.temperature}")

    if is_md:
        lines.append(f"dt = {spec.dt}")
        lines.append(f"thermostat = {spec.thermostat}")
        if spec.thermostat == "bussi":
            lines.append(f"bussi_tau = {spec.bussi_tau}")
        lines.append(f"newtonian_steps = {spec.newtonian_steps}")
        lines.append("refresh_vel = true")
    else:  # Monte Carlo
        lines.append(f"ensemble = {spec.ensemble}")
        lines.append(f"delta_translation = {spec.delta_translation}")
        lines.append(f"delta_rotation = {spec.delta_rotation}")

    # ── Interaction ─────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("interaction_type = DNA2")
    lines.append(f"salt_concentration = {spec.salt_concentration}")

    # ── Mutual-trap external forces (hold designed pairs during relaxation) ──────
    if spec.external_forces and forces_name:
        lines.append("")
        lines.append("external_forces = true")
        lines.append(f"external_forces_file = {forces_name}")

    # ── Relaxation force caps (modified backbone potential) ─────────────────────
    if spec.max_backbone_force is not None:
        lines.append("")
        lines.append(f"max_backbone_force = {spec.max_backbone_force}")
    if spec.max_backbone_force_far is not None:
        lines.append(f"max_backbone_force_far = {spec.max_backbone_force_far}")

    # ── Files ───────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append(f"topology = {topology_name}")
    lines.append(f"conf_file = {conf_name}")
    lines.append("trajectory_file = trajectory.dat")
    lines.append("energy_file = energy.dat")
    lines.append("lastconf_file = last_conf.dat")

    # ── Output cadence ──────────────────────────────────────────────────────────
    lines.append("")
    lines.append("time_scale = linear")
    lines.append(f"print_conf_interval = {print_conf_interval}")
    lines.append(f"print_energy_every = {print_energy_every}")
    # Raise oxDNA's I/O-rate safety valve.  Its default (max_io = 1 MB/s) aborts a
    # run that writes too fast — harmless for the small designs the protocol was
    # tuned on, but a large imported structure writes ~MB-scale trajectory frames
    # and trips it mid-stage (the run "fails" with the structure perfectly healthy).
    # 1000 MB/s still catches a genuine runaway while never false-aborting.
    lines.append("max_io = 1000.0")

    return "\n".join(lines) + "\n"


DEFAULT_PRODUCTION_STEPS: int = 5_000_000


def build_production_stage(
    *,
    name:               str = "4_production",
    steps:              int = DEFAULT_PRODUCTION_STEPS,
    backend:            str = "CUDA",
    device:             str = "0",
    salt_concentration: float = 0.5,
) -> OxdnaStageSpec:
    """Return an unbiased MD production stage (standard backbone potential, no
    traps, no force cap) — the real dynamics run, appended after relaxation passes.
    No base-pair gate: production is sampling, the structure is free to evolve.

    ``name`` is unique per run (``4_production``, ``5_production``, …) so repeated
    "Start Production" clicks each get their own stage dir and continue from the
    previous run's ``last_conf.dat`` instead of overwriting it."""
    return OxdnaStageSpec(
        name=name, kind="production", sim_type="MD", steps=steps,
        backend=backend, dt=0.005,
        max_backbone_force=None, max_backbone_force_far=None,
        external_forces=False,
        salt_concentration=salt_concentration, device=device,
        min_bp_retained=0.0,
    )


DEFAULT_FIELD_STEPS: int = 2_000_000


def build_field_stage(
    *,
    name:               str,
    field_oxdna:        float,
    field_dir:          list[float],
    forces_file:        str,
    steps:              int = DEFAULT_FIELD_STEPS,
    backend:            str = "CUDA",
    device:             str = "0",
    salt_concentration: float = 0.5,
) -> OxdnaStageSpec:
    """An electric-field MD stage: unbiased dynamics (standard FENE, no force cap)
    plus the field/anchor external-forces file ``forces_file`` — a uniform per-
    nucleotide ``string`` force + anchor ``trap``s, written by
    ``oxdna_interface.write_field_forces``.

    No base-pair gate: the field deliberately deflects the structure (and the
    deflected end may fray), so retention is a readout, not a pass/fail gate.
    Continues from the previous (relaxed) stage's ``last_conf.dat`` like a
    production run."""
    return OxdnaStageSpec(
        name=name, kind="field", sim_type="MD", steps=steps,
        backend=backend, dt=0.005,
        max_backbone_force=None, max_backbone_force_far=None,
        external_forces=True, forces_file=forces_file,
        efield={"dir": list(field_dir), "force_oxdna": float(field_oxdna)},
        salt_concentration=salt_concentration, device=device,
        min_bp_retained=0.0,
    )


def expected_energy_lines(spec: OxdnaStageSpec) -> int:
    """How many energy.dat lines a completed stage should produce (~progress denom)."""
    print_energy_every = max(1, spec.steps // 100)
    return max(1, spec.steps // print_energy_every)
