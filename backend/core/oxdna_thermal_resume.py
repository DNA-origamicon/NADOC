"""Explicitly extend an exhausted thermal sampling budget without resetting data."""
from copy import deepcopy
from dataclasses import replace
import time

from pydantic import BaseModel, ConfigDict, Field

from backend.core.oxdna_thermal_ramp import ThermalRamp


class ThermalResumeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    thermal_max_steps: int = Field(ge=1000, le=200_000_000)


def extend_budget(job, specs, maximum):
    """Validate everything before modifying metadata; caller persists under job lease."""
    idx = job.current_stage_idx
    if job.status != 'failed' or not 0 <= idx < len(specs) or not specs[idx].thermal_ramp:
        raise ValueError('Only a thermal plateau that exhausted its sampling budget can be extended.')
    spec = specs[idx]
    cfg = ThermalRamp.model_validate(spec.thermal_ramp)
    report = (job.run_config or {}).get('thermal_progress', {}).get(spec.name, {})
    if not cfg.gate or report.get('decision') != 'failed' or report.get('evaluated_steps') != spec.steps:
        raise ValueError('This failure is not an exhausted thermal sampling gate.')
    if maximum <= cfg.max_steps:
        raise ValueError('The new maximum must exceed the exhausted sampling budget.')
    updated_cfg = ThermalRamp.model_validate({**cfg.model_dump(), 'max_steps': maximum})
    if maximum < spec.steps + cfg.block_steps * cfg.consecutive_passes:
        raise ValueError('Allow enough additional blocks for all required consecutive passes.')
    updated = list(specs)
    for i in range(idx, len(specs)):
        if specs[i].thermal_ramp:
            updated[i] = replace(specs[i], thermal_ramp={**specs[i].thermal_ramp, 'max_steps': maximum})
    updated[idx] = replace(updated[idx], steps=spec.steps + cfg.block_steps, refresh_vel=False)
    changes = list((job.run_config or {}).get('thermal_budget_changes', []))
    changes.append({'time': time.time(), 'stage': spec.name, 'old_max_steps': cfg.max_steps,
                    'new_max_steps': maximum, 'previous_check': deepcopy(report)})
    job.run_config = {**job.run_config, 'thermal_ramp': updated_cfg.model_dump(), 'thermal_budget_changes': changes}
    job.stages[idx].steps = updated[idx].steps
    job.stages[idx].status = 'pending'
    return updated
