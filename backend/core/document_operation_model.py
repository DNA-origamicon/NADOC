"""Portable semantic document operations; persistence is not an operation."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class DocumentOperation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: Literal[1] = 1
    kind: Literal['loadout-initialize', 'loadout-create', 'loadout-rename',
                  'loadout-select', 'loadout-delete', 'document-metadata']
    params: dict[str, Any]
    source_loadout_id: str | None = None
    # Exact construction inputs at this semantic action, not an output snapshot.
    source_recipe: dict[str, Any] = Field(default_factory=dict)
