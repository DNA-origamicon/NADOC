"""Bounded repair actions shared by transient requests and persisted drafts.

These schemas describe proposed inputs, not an executable plan or a proof.
Target resolution, protected identities and command admission remain owned by
the repair evaluator. This module must not import API state or Design.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_operation_input import validate_operation_input


MAX_REPAIR_ACTIONS = 64
RepairIdentity = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
RepairToken = RepairIdentity | Annotated[StrictInt, Field(ge=0)]


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    feature_id: RepairIdentity
    child_id: RepairIdentity | None = None


class SetInput(_Target):
    action: Literal["set_input"]
    parameter_path: list[RepairToken] = Field(min_length=1, max_length=16)
    expected_old: Any
    value: Any


class UpgradeNumericalContract(_Target):
    action: Literal["upgrade_numerical_contract"]
    expected_engine: dict[str, Any]
    expected_template: dict[str, Any] | None = None


RepairAction = Annotated[SetInput | UpgradeNumericalContract, Field(discriminator="action")]
RepairActions = Annotated[list[RepairAction], Field(min_length=1, max_length=MAX_REPAIR_ACTIONS)]


class RepairRequest(BaseModel):
    """Transient request; session revision guards are intentionally not durable."""

    model_config = ConfigDict(extra="forbid", strict=True)
    repair_version: StrictInt = Field(ge=1, le=1)
    expected_design_id: RepairIdentity
    expected_revision: StrictInt = Field(ge=0)
    actions: RepairActions

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value
