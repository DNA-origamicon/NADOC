"""Bounded repair actions shared by transient requests and persisted drafts.

These schemas describe proposed inputs, not an executable plan or a proof.
Target resolution, protected identities and command admission remain owned by
the repair evaluator. This module must not import API state or Design.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_operation_input import validate_operation_input
from backend.core.part_repair_expectations import MAX_EXPECTATION_JSON_CHARS, normalize_expected_old


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
    # Retain the exact encoding across draft GET/browser/update. No receipt
    # means the original strict expectation behavior; no persisted null bloat.
    expected_old_json: Annotated[str, Field(strict=True, max_length=MAX_EXPECTATION_JSON_CHARS)] | None = Field(
        default=None, exclude_if=lambda value: value is None)
    value: Any

    @model_validator(mode="before")
    @classmethod
    def lossless_expectation(cls, value):
        return normalize_expected_old(value)


class UpgradeNumericalContract(_Target):
    action: Literal["upgrade_numerical_contract"]
    expected_engine: dict[str, Any]
    expected_template: dict[str, Any] | None = None


class UpgradeClusterCreation(_Target):
    """A single reviewed semantic transition; no caller-selected new version."""

    action: Literal["upgrade_cluster_creation"]
    child_id: None = None
    expected_version: StrictInt = Field(ge=1, le=1)
    expected_cluster_id: RepairIdentity
    expected_definition_sha256: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


RepairAction = Annotated[SetInput | UpgradeNumericalContract | UpgradeClusterCreation, Field(discriminator="action")]
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
