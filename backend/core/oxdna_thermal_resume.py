"""Compatibility validation for retired adaptive-budget requests."""

from pydantic import BaseModel, ConfigDict, Field



class ThermalResumeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    thermal_max_steps: int = Field(ge=1000, le=200_000_000)


def extend_budget(job, specs, maximum):
    """Reject obsolete adaptive-budget requests without modifying saved protocols."""
    raise ValueError('Adaptive thermal progression has been removed. Set a fixed Steps per temperature in the wizard.')
