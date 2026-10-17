"""Public inputs for the first registered part-command batch catalog.

This is an explicit product allowlist, not a mirror of the replay registry.
Producer identities are typed declarations; feature identities and proof markers
belong to the host. No source bodies, recovery data or executable code are inputs.
"""

from types import MappingProxyType
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from backend.core.part_operation_input import validate_operation_input


MAX_BATCH_COMMANDS = 32
Identity = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector = Annotated[list[Number], Field(min_length=3, max_length=3)]
Quaternion = Annotated[list[Number], Field(min_length=4, max_length=4)]
Version = Annotated[StrictInt, Field(ge=1, le=1)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def declared_uuid(value):
    if str(UUID(value)) != value:
        raise ValueError("Producer identities must be canonical UUID strings")
    return value


def nonzero_rotation(value):
    if not any(value):
        raise ValueError("A rotation needs a nonzero quaternion")
    return value


class Point(_Input):
    x: Number
    y: Number
    z: Number


class HelixAdd(_Input):
    helix_id: Identity
    axis_start: Point
    axis_end: Point
    length_bp: StrictInt = Field(ge=1, le=50_000)
    phase_offset: Number = 0.0

    _identity = field_validator("helix_id")(declared_uuid)


class DomainInput(_Input):
    helix_id: Identity
    start_bp: StrictInt
    end_bp: StrictInt
    direction: Literal["FORWARD", "REVERSE"]


class StrandAdd(_Input):
    strand_id: Identity
    domains: list[DomainInput] = Field(min_length=1, max_length=256)
    strand_type: Literal["scaffold", "staple"] = "staple"
    sequence: Annotated[str, Field(strict=True, max_length=50_000)] | None = None

    _identity = field_validator("strand_id")(declared_uuid)


class GoldCreate(_Input):
    nanoparticle_id: Identity
    diameter_nm: Number = Field(gt=0, le=1000)

    _identity = field_validator("nanoparticle_id")(declared_uuid)


class GizmoMove(_Input):
    pivot: Vector
    translation: Vector
    rotation: Quaternion

    _rotation = field_validator("rotation")(nonzero_rotation)


class GoldPatch(_Input):
    nanoparticle_id: Identity
    diameter_nm: Number | None = Field(default=None, gt=0, le=1000)
    gizmo_move: GizmoMove | None = None

    @model_validator(mode="after")
    def authored_change(self):
        if self.diameter_nm is None and self.gizmo_move is None:
            raise ValueError("Particle patch requires a diameter or gizmo move")
        return self


class GoldDelete(_Input):
    nanoparticle_id: Identity


class ClusterCreate(_Input):
    cluster_id: Identity
    name: Annotated[str, Field(strict=True, min_length=1, max_length=256)]
    helix_ids: list[Identity] = Field(min_length=1, max_length=256)

    _identity = field_validator("cluster_id")(declared_uuid)

    @field_validator("helix_ids")
    @classmethod
    def distinct_members(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Cluster members must be unique")
        return value


class ClusterPose(_Input):
    """Pose only for any uniquely resolved existing cluster, including domain scopes.

    Unlike whole-helix cluster creation, this does not alter membership, parent
    ownership or domain references. It uses the existing native pose semantics.
    """

    cluster_id: Identity
    translation: Vector
    rotation: Quaternion
    pivot: Vector

    _rotation = field_validator("rotation")(nonzero_rotation)


# An immutable declaration catalog; this maps schemas, never native builders.
CATALOG = MappingProxyType({
    "helix-add": HelixAdd, "strand-add": StrandAdd,
    "nanoparticle-create": GoldCreate, "nanoparticle-patch": GoldPatch,
    "nanoparticle-delete": GoldDelete, "cluster_create": ClusterCreate,
    "cluster_op": ClusterPose,
})


class BatchCommand(_Input):
    kind: Literal["helix-add", "strand-add", "nanoparticle-create", "nanoparticle-patch",
                  "nanoparticle-delete", "cluster_create", "cluster_op"]
    version: Version
    params: dict
    label: Annotated[str, Field(strict=True, min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def exact_inputs(self):
        # Copy to an owned normalized dictionary. The native private-field
        # translation happens only after this strict public schema has passed.
        self.params = CATALOG[self.kind].model_validate(self.params).model_dump(mode="json")
        if self.kind in {"cluster_create", "cluster_op"} and self.label is not None:
            raise ValueError("Pose/group records use their existing cluster display names, not arbitrary labels")
        return self


class BatchRequest(_Input):
    batch_version: Version
    expected_design_id: Identity
    expected_revision: StrictInt = Field(ge=0)
    commands: list[BatchCommand] = Field(min_length=1, max_length=MAX_BATCH_COMMANDS)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value
