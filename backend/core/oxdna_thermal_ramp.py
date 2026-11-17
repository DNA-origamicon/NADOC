"""Temperature plateaus and observable-stability gates (not equilibrium proofs)."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
import json
import math

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ThermalRamp(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start_c: float = Field(25, gt=-273.15, le=200)
    end_c: float = Field(85, gt=-273.15, le=200)
    step_c: float = Field(5, gt=0, le=200)
    block_steps: int = Field(1_000_000, ge=1000, le=200_000_000)
    max_steps: int = Field(10_000_000, ge=1000, le=200_000_000)
    gate: bool = True
    window_samples: int = Field(20, ge=10, le=1000)
    min_effective_samples: int = Field(10, ge=5)
    consecutive_passes: int = Field(2, ge=1, le=10)
    energy_tolerance: float = Field(0.02, gt=0)
    pairing_tolerance: float = Field(0.02, gt=0, le=1)
    check_pairing: bool = True

    @model_validator(mode="after")
    def valid_budget(self):
        if math.ceil(abs(self.end_c - self.start_c) / self.step_c - 1e-10) > 100:
            raise ValueError("Thermal ramps support at most 101 temperature plateaus.")
        if self.gate and self.max_steps < self.block_steps * self.consecutive_passes:
            raise ValueError("Maximum dwell must allow the required number of sampling blocks.")
        if self.gate and self.max_steps % self.block_steps:
            raise ValueError("Maximum dwell must be a whole number of sampling blocks.")
        if self.min_effective_samples > self.window_samples:
            raise ValueError("Minimum effective samples cannot exceed the window size.")
        if self.gate and self.block_steps < 3 * self.window_samples:
            raise ValueError("Each block must accommodate three sampling windows.")
        return self

    def temperatures(self):
        distance = abs(self.end_c - self.start_c)
        direction = 1 if self.end_c >= self.start_c else -1
        return [self.start_c + direction * min(i * self.step_c, distance)
                for i in range(math.ceil(distance / self.step_c - 1e-10) + 1)]


def sampling_cadence(cfg, requested=None):
    """Exact divisors keep resumed step accounting and plateau budgets exact."""
    limit = min(requested or (cfg.block_steps if cfg.gate else max(1, cfg.block_steps // 100)),
                cfg.block_steps // (3 * cfg.window_samples) if cfg.gate else cfg.block_steps)
    common = math.gcd(cfg.block_steps, cfg.max_steps) if cfg.gate else cfg.block_steps
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


def stability(values, tolerance, cfg):
    """Three window means + linear drift + autocorrelation-adjusted sample counts."""
    n = cfg.window_samples
    data = np.asarray(list(values)[-3 * n:], dtype=float)
    if len(data) < 3 * n or not np.isfinite(data).all():
        return {"passed": False, "reason": "insufficient or nonfinite samples", "samples": len(data)}
    windows = data.reshape(3, n)
    ess = []
    for window in windows:
        centered = window - window.mean()
        variance = float(centered @ centered)
        correlation_sum = 0.0
        if variance > 1e-20:
            for lag in range(1, n):
                rho = float(centered[:-lag] @ centered[lag:]) / variance
                if rho <= 0:
                    break
                correlation_sum += rho
        ess.append(n / (1 + 2 * correlation_sum))
    spread = float(np.ptp(windows.mean(axis=1)))
    drift = abs(float(np.polyfit(np.arange(len(data)), data, 1)[0])) * (len(data) - 1)
    return {"passed": bool(spread <= tolerance and drift <= tolerance and min(ess) >= cfg.min_effective_samples),
            "window_means": windows.mean(axis=1).tolist(),
            "mean_spread": spread, "drift": drift, "effective_samples": ess,
            "tolerance": tolerance, "samples": len(data)}


def _recent_files(directory, stem):
    archives = sorted(directory.glob(f"{stem}.r*.dat"), key=lambda p: int(p.stem.split('.r')[-1]))
    return [*archives, directory / f"{stem}.dat"]


def accumulated_stability(values, tolerance, initial_cfg, expanded_cfg):
    """More evidence must not average away a recent shift in the observable."""
    result = stability(values, tolerance, expanded_cfg)
    recent = stability(values, tolerance, initial_cfg)
    result['recent_mean_spread'] = recent.get('mean_spread')
    result['recent_drift'] = recent.get('drift')
    result['passed'] = bool(result['passed'] and recent.get('mean_spread', math.inf) <= tolerance
                            and recent.get('drift', math.inf) <= tolerance)
    return result


def evaluate(directory, design, cfg, *, n_trailing_extra=0, evaluated_steps=None):
    from backend.core.oxdna_health import base_pair_retention, parse_energy_dat
    from backend.physics.oxdna_interface import iter_trajectory_frames_full
    # A fixed tail cannot accumulate independent evidence when a plateau extends.
    # Grow deterministically with completed blocks, never by searching for a pass.
    # Bound each window to the same 1000-observation limit as the UI setting.
    blocks = max(1, (evaluated_steps or cfg.block_steps) // cfg.block_steps)
    initial_cfg = cfg
    cfg = cfg.model_copy(update={'window_samples': min(1000, cfg.window_samples * blocks)})
    energy = deque(maxlen=3 * cfg.window_samples)
    pairing = deque(maxlen=3 * cfg.window_samples)
    for path in reversed(_recent_files(directory, "energy")):
        rows = [u for t, u in parse_energy_dat(path) if t > 0]
        energy.extendleft(reversed(rows[-(energy.maxlen - len(energy)):]))
        if len(energy) == energy.maxlen:
            break
    result = {"energy": accumulated_stability(energy, cfg.energy_tolerance, initial_cfg, cfg)}
    if cfg.check_pairing:
        pairs = 0
        for path in reversed(_recent_files(directory, "trajectory")):
            if path.exists():
                recent = deque(maxlen=pairing.maxlen - len(pairing))
                for frame in iter_trajectory_frames_full(path, design, n_trailing_extra=n_trailing_extra):
                    fraction, pairs = base_pair_retention(design, frame)
                    recent.append(fraction)
                pairing.extendleft(reversed(recent))
                if len(pairing) == pairing.maxlen:
                    break
        result["pairing"] = accumulated_stability(pairing, cfg.pairing_tolerance, initial_cfg, cfg) if pairs else {
            "passed": False, "reason": "No designed pairs; disable the pairing gate for this system."}
    result["passed"] = all(metric["passed"] for metric in result.values())
    return result


def advance(job, workspace, specs, idx, design):
    """Idempotent boundary decision; caller persists the changed stage and job."""
    from backend.core.oxdna_job import OxdnaStatus
    from backend.core.oxdna_runner import capture_bead_count
    spec = specs[idx]
    if not spec.thermal_ramp:
        return "done"
    cfg = ThermalRamp.model_validate(spec.thermal_ramp)
    reports = dict((job.run_config or {}).get("thermal_progress") or {})
    report = reports.get(spec.name, {})
    if report.get("evaluated_steps") != spec.steps or (not cfg.gate and "gate_enabled" not in report):
        metrics = evaluate(job.stage_dir(workspace, spec.name), design, cfg,
                           n_trailing_extra=capture_bead_count(job), evaluated_steps=spec.steps)
        previous_streak = report.get("consecutive_passes", 0) if report.get("gate_version") == 2 else 0
        streak = previous_streak + 1 if metrics["passed"] else 0
        done = not cfg.gate or streak >= cfg.consecutive_passes
        report = {"temperature": spec.temperature, "evaluated_steps": spec.steps, "gate_version": 2,
                  "consecutive_passes": streak, "metrics": metrics, "gate_enabled": cfg.gate,
                  "stability_status": "passed" if metrics["passed"] else "not_demonstrated",
                  "decision": "done" if done else "failed" if spec.steps >= cfg.max_steps else "extend"}
        reports[spec.name] = report
        job.run_config = {**(job.run_config or {}), "thermal_progress": reports}
        # job.json is authoritative for restart; this file is a human-readable export.
        encoded = json.dumps(report, indent=2)
        for filename in ("thermal_check.json", f"thermal_check_{spec.steps}.json"):
            (job.stage_dir(workspace, spec.name) / filename).write_text(encoded)
    if report["decision"] == "extend":
        specs[idx] = replace(spec, steps=min(cfg.max_steps, spec.steps + cfg.block_steps), refresh_vel=False)
        job.stages[idx].steps = specs[idx].steps
        job.stages[idx].status = "pending"
        job.current_stage_idx = idx
    elif report["decision"] == "failed":
        job.stages[idx].status = "failed"
        job.status = OxdnaStatus.failed
        job.error = (f"Thermal plateau {spec.temperature} did not stabilize within {cfg.max_steps:,} steps. "
                     "Temperature was not advanced. Inspect thermal_check.json and increase sampling or review tolerances.")
    return report["decision"]


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
    return [replace(s, steps=ThermalRamp.model_validate(s.thermal_ramp).block_steps, refresh_vel=True)
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
    for pattern in ("energy*.dat", "trajectory*.dat", "thermal_check*.json", "error_conf.dat"):
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
