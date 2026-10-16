"""Closed organizational membership, independent of numerical placement owners.

Absent organization state means the legacy combined group/placement regime.
The explicit v1 state never contains poses or redirects a placement identity.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


GroupId = Annotated[str, Field(min_length=1, max_length=512)]


class GroupDomainRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    strand_id: GroupId
    domain_index: Annotated[StrictInt, Field(ge=0)]


class PartGroup(BaseModel):
    """Selection/style only; domain selectors retain their legacy precedence."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: GroupId
    name: Annotated[str, Field(max_length=512)] = "Group"
    helix_ids: list[GroupId] = Field(default_factory=list, max_length=30_000)
    domain_ids: list[GroupDomainRef] = Field(default_factory=list, max_length=30_000)
    color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] | None = None
    opacity: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 1.0
    is_default: bool = False
    auto_created: bool = False


class GroupOrganization(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    groups: list[PartGroup] = Field(default_factory=list, max_length=2_000)

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Group organization requires integer version 1")
        return value
