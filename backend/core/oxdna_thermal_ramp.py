"""Fixed-duration thermal plateaus with informational energy observations."""
from __future__ import annotations

from dataclasses import replace
import json
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ThermalRamp(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_c: float = Field(25, gt=-273.15, le=200)
    end_c: float = Field(85, gt=-273.15, le=200)
    step_c: float = Field(5, gt=0, le=200)
    block_steps: int = Field(10_000_000, ge=1000, le=200_000_000)
    # Read old saved protocols, but never serialize or honor adaptive controls.
    max_steps: int | None = Field(None, exclude=True)
    gate: bool = Field(False, exclude=True)
    window_samples: int = Field(20, exclude=True)
    min_effective_samples: int = Field(10, exclude=True)
    consecutive_passes: int = Field(2, exclude=True)
    energy_tolerance: float = Field(.02, exclude=True)
    pairing_tolerance: float = Field(.02, exclude=True)
    check_pairing: bool = Field(False, exclude=True)

    @model_validator(mode="after")
    def valid_schedule(self):
        if math.ceil(abs(self.end_c - self.start_c) / self.step_c - 1e-10) > 100:
            raise ValueError("Thermal ramps support at most 101 temperature plateaus.")
        self.gate = False
        self.check_pairing = False
        self.max_steps = self.block_steps
        return self

    def temperatures(self):
        distance = abs(self.end_c - self.start_c)
        direction = 1 if self.end_c >= self.start_c else -1
        return [self.start_c + direction * min(i * self.step_c, distance)
                for i in range(math.ceil(distance / self.step_c - 1e-10) + 1)]


def sampling_cadence(cfg, requested=None):
    """Exact divisors keep resumed step accounting and plateau budgets exact."""
    limit = min(requested or min(50_000, max(1, cfg.block_steps // 100)), cfg.block_steps)
    common = cfg.block_steps
    divisors = {d for i in range(1, math.isqrt(common) + 1) if common % i == 0
                for d in (i, common // i) if d <= limit}
    return max(divisors)


def ramp_stages(stage, config):
    """Clone the fully resolved production physics, including frozen CPD forces."""
    if not config:
        return [stage]
    cfg = ThermalRamp.model_validate(config)
    if stage.thermostat == "no":
        raise ValueError("Thermal ramps require a thermostat.")
    return [replace(stage, name=f"{i + 1}_thermal", kind="production",
                    temperature=f"{c + 273.15:.10g}K", steps=cfg.block_steps,
                    max_backbone_force=None, max_backbone_force_far=None,
                    min_bp_retained=0, refresh_vel=True, thermal_ramp=cfg.model_dump(),
                    print_conf_interval_override=sampling_cadence(cfg, stage.print_conf_interval_override),
                    print_energy_every_override=sampling_cadence(cfg, stage.print_energy_every_override))
            for i, c in enumerate(cfg.temperatures())]


def evaluate(directory, design, cfg, *, n_trailing_extra=0, evaluated_steps=None):
    """Record complete energy data, with no fitted model or equilibrium verdict."""
    from backend.core.oxdna_thermal_metrics import energy_observations
    summary, _ = energy_observations(directory, evaluated_steps=evaluated_steps)
    return {"energy": summary}


def advance(job, workspace, specs, idx, design):
    """After native completion/health checks, always advance the fixed schedule."""
    spec = specs[idx]
    if not spec.thermal_ramp:
        return "done"
    reports = dict((job.run_config or {}).get("thermal_progress") or {})
    previous = reports.get(spec.name, {})
    if previous.get('protocol_version') == 4 and previous.get('evaluated_steps') == spec.steps:
        return 'done'
    try:
        metrics = evaluate(job.stage_dir(workspace, spec.name), design,
                           ThermalRamp.model_validate(spec.thermal_ramp), evaluated_steps=spec.steps)
    except Exception as error:
        metrics = {'energy': {'status': 'unavailable', 'reason': str(error)}}
    report = {"temperature": spec.temperature, "evaluated_steps": spec.steps,
              "protocol_version": 4, "metrics": metrics, "gate_enabled": False,
              "stability_status": "not_assessed", "decision": "done"}
    if previous:
        report['previous_decision'] = previous
    reports[spec.name] = report
    job.run_config = {**(job.run_config or {}), "thermal_progress": reports}
    encoded = json.dumps(report, indent=2)
    for filename in ('thermal_check.json', f'thermal_dwell_{spec.steps}.json'):
        (job.stage_dir(workspace, spec.name) / filename).write_text(encoded)
    return 'done'


def configure_child(child, stage, config):
    from backend.core.oxdna_protocol import assign_stage_seeds
    specs = assign_stage_seeds(ramp_stages(stage, config), child.random_seed)
    child.stages = [s.to_status() for s in specs]
    if config:
        child.run_config = {**child.run_config, "thermal_ramp": config.model_dump()}
    else:
        child.run_config.pop("thermal_ramp", None)
    child.run_config.pop("thermal_progress", None)
    return specs


def reset_copy(specs, config):
    if config is not None:
        config.pop("thermal_progress", None)
    return [replace(s, steps=ThermalRamp.model_validate(s.thermal_ramp).block_steps, refresh_vel=True,
                    thermal_ramp=ThermalRamp.model_validate(s.thermal_ramp).model_dump())
            if s.thermal_ramp else s for s in specs]


def recovered_boundary_ready(job, workspace, spec, design):
    """Recovered native completion still needs a valid checkpoint and health check."""
    from backend.core.oxdna_runner import resume_point, capture_bead_count
    from backend.core.oxdna_health import run_oxdna_health_check
    directory = job.stage_dir(workspace, spec.name)
    if not (directory / "last_conf.dat").exists():
        return False
    conf, consumed, _ = resume_point(directory, spec, job.n_nucleotides)
    if conf is None or consumed < spec.steps:
        return False
    result = run_oxdna_health_check(design, directory, kind=spec.kind, min_bp_retained=0,
                                   n_trailing_extra=capture_bead_count(job),
                                   salt_concentration=spec.salt_concentration, temperature=spec.temperature)
    return check_thermal_health(result, job, workspace, spec).passed


def check_thermal_health(result, job, workspace, spec):
    from backend.core.oxdna_runner import conf_is_restartable
    if spec.thermal_ramp and (not result.fene_safe or not conf_is_restartable(
            job.stage_dir(workspace, spec.name) / "last_conf.dat", job.n_nucleotides)):
        result.passed = False
        result.reason = "Thermal plateau has an invalid checkpoint or overstretched backbone."
    return result


def validate_edit(job, updates):
    """Generated plateaus must be edited through their schedule, never silently ignored."""
    from fastapi import HTTPException
    if updates.get("surface_deposition", (job.run_config or {}).get("surface_deposition", False)):
        raise HTTPException(422, "Create a production continuation after deposition to run a thermal ramp.")
    rows = updates.get("stages")
    expected = [{"name": s.name, "kind": s.kind, "steps": s.steps} for s in job.stages]
    if rows is not None and rows != expected:
        raise HTTPException(422, "Edit generated thermal plateaus with thermal_ramp; edit shared physics with stage_overrides.1_production.")


def restart_plateau(job, workspace, specs, idx):
    """Discard evidence from a numerically diverged attempt before a clean restart."""
    spec = specs[idx]
    if not spec.thermal_ramp:
        return
    cfg = ThermalRamp.model_validate(spec.thermal_ramp)
    specs[idx] = replace(spec, steps=cfg.block_steps, refresh_vel=True)
    job.stages[idx].steps = cfg.block_steps
    (job.run_config or {}).get("thermal_progress", {}).pop(spec.name, None)
    directory = job.stage_dir(workspace, spec.name)
    # Retain failed evidence outside the active sampling namespace.
    archive = directory / f"thermal_retry_{job.production_retries}"
    archive.mkdir(exist_ok=True)
    for pattern in ("energy*.dat", "trajectory*.dat", "thermal_check*.json", "thermal_dwell*.json", "thermal_energy_curve.json", "thermal_attempt_*.json", "error_conf.dat"):
        for path in directory.glob(pattern):
            path.replace(archive / path.name)


def require_full_system(config, selection):
    from fastapi import HTTPException
    if config and selection:
        raise HTTPException(422, "Thermal ramps currently require full-system dynamics; disable the simulation submodel box.")


def apply_edit_hardware(prepared, source, updates, specs):
    """Keep wizard hardware edits consistent with the regenerated stage inputs."""
    if not (updates.get("thermal_ramp") is not None or (source.run_config or {}).get("thermal_ramp")):
        return
    from fastapi import HTTPException
    backend = updates.get("backend", source.backend)
    device = str(updates.get("device", source.device))
    try:
        salt = float(updates.get("salt_concentration", source.salt_concentration))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Salt concentration must be positive and finite.") from exc
    if backend not in {"CPU", "CUDA"} or not device.strip() or not math.isfinite(salt) or salt <= 0:
        raise HTTPException(422, "Choose CPU/CUDA, a device and positive finite salt concentration.")
    prepared.backend, prepared.device, prepared.salt_concentration = backend, device, salt
    for spec in specs:
        spec.backend, spec.device, spec.salt_concentration = backend, device, salt
    prepared.run_config.update(backend=backend, device=device, salt_concentration=salt)


def prepare_attempt(spec, job, workspace, idx):
    """Reseeding a restarted native process must not repeat its previous noise."""
    if not spec.thermal_ramp:
        return spec
    import hashlib
    from backend.core.oxdna_job import OXDNA_SEED_MAX
    consumed = job.stages[idx].completed_steps
    retry = job.production_retries
    seed = spec.seed
    if consumed or retry:
        identity = f"thermal:{job.random_seed}:{spec.name}:{consumed}:{retry}"
        seed = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], 'big') % OXDNA_SEED_MAX + 1
        if seed == spec.seed:
            seed = seed % OXDNA_SEED_MAX + 1
    receipt = {"seed": seed, "banked_steps": consumed, "attempt_steps": spec.steps,
               "retry": retry, "temperature": spec.temperature}
    (job.stage_dir(workspace, spec.name) / f"thermal_attempt_{consumed}_retry{retry}.json").write_text(json.dumps(receipt, indent=2))
    return replace(spec, seed=seed)
