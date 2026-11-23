"""Validated Alpine settings shared by SNUPI and mrDNA (no credentials)."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SolverClusterSettings(BaseModel):
    python: str = Field(min_length=1, description="Absolute Python path in the remote solver environment")
    partition: str = "acpu"
    qos: str = "cpu-normal"
    account: str = "ucb-general"
    cores: int = Field(8, ge=1, le=256)
    mem_gb: int = Field(64, ge=1, le=2048)
    walltime_minutes: int = Field(120, ge=1, le=10080)
    arbd: str = ""

    @field_validator("python", "arbd")
    @classmethod
    def absolute_path(cls, value):
        if value and (not value.startswith("/") or any(c in value for c in "\n\r\0")):
            raise ValueError("Use an absolute remote path without control characters")
        return value

    @field_validator("partition", "qos", "account")
    @classmethod
    def token(cls, value):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid scheduler name")
        return value


class SolverRunpodSettings(BaseModel):
    gpu_id: str = Field(min_length=1)
    quoted_rate: float = Field(gt=0, allow_inf_nan=False)
    budget_usd: float = Field(5, gt=0, le=1000, allow_inf_nan=False)
    mem_gb: int = Field(64, ge=1, le=2048)
    cores: int = Field(8, ge=1, le=256)
    walltime_minutes: int = Field(120, ge=5, le=10080)
    python: str = "/workspace/nadoc-solver-env/bin/python"
    arbd: str = ""

    @field_validator("python", "arbd")
    @classmethod
    def absolute_path(cls, value):
        return SolverClusterSettings.absolute_path(value)


class SolverExecutionRequest(BaseModel):
    execution_target: Literal["local", "alpine", "runpod"] = "local"
    cluster_settings: SolverClusterSettings | None = None
    runpod_settings: SolverRunpodSettings | None = None


def validate_settings(engine, settings, workspace):
    from backend.core.cluster_config import load_profiles
    config = SolverClusterSettings.model_validate(settings)
    profile = load_profiles(workspace)["alpine"]
    partition = profile.partition(config.partition)
    if partition is None:
        raise ValueError("Choose an Alpine partition from the cluster profile")
    if engine == "mrdna" and partition.kind != "gpu":
        raise ValueError("mrDNA requires a GPU partition")
    if config.cores > partition.max_cores:
        raise ValueError(f"{partition.name} allows at most {partition.max_cores} cores")
    if partition.allowed_qos and config.qos not in partition.allowed_qos:
        raise ValueError("QoS is not supported by this partition")
    qos = profile.qos(config.qos)
    if qos is None or config.walltime_minutes > qos.max_walltime_h * 60:
        raise ValueError("Walltime exceeds the selected QoS limit")
    if engine == "mrdna" and not config.arbd:
        raise ValueError("Set the absolute path to the remote ARBD executable")
    return config, profile, partition
