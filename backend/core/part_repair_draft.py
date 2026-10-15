"""A portable proposed repair, independent of geometry and job results.

Design persists this as branch metadata, separately from feature recovery and
proof inputs. A host must capture a stable base, check the draft generation and explicitly rebase stale
proposals before turning their actions into a fresh RepairRequest. Never infer
verification from a matching fingerprint.
"""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_input_sources import Digest
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_repair_inputs import RepairActions, RepairIdentity


class RepairBaseFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: StrictInt = Field(ge=1, le=1)
    root_sha256: Digest
    commands_sha256: Digest
    sources_sha256: Digest


class RepairDraft(BaseModel):
    """One bounded proposal per part branch; no persisted readiness certificate.

    Frozen top-level fields do not make nested action JSON immutable. Hosts must
    own/copy accepted values rather than sharing client-mutable action objects.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: StrictInt = Field(ge=1, le=1)
    draft_id: RepairIdentity
    generation: StrictInt = Field(ge=0)
    base_design_id: RepairIdentity
    base: RepairBaseFingerprint
    repair_version: StrictInt = Field(ge=1, le=1)
    actions: RepairActions

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        # Charge the complete envelope, including expected_old values, before
        # Pydantic constructs nested objects. Shares the existing request limit.
        validate_operation_input(value)
        return value
