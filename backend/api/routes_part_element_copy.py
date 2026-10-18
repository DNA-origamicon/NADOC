"""Explicit same-part rigid copies; frozen clipboard paste is a separate API."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api import part_element_copy_commands as commands, state
from backend.api.crud import _design_response
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import ProofBudgetExceeded


router = APIRouter()
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class ElementCopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protein_ids: list[_Id] = Field(default_factory=list, max_length=commands.MAX_ELEMENTS)
    nanoparticle_ids: list[_Id] = Field(default_factory=list, max_length=commands.MAX_ELEMENTS)
    paste_index: StrictInt = Field(default=1, ge=1, le=10000)
    expected_revision: StrictInt = Field(ge=0)
    expected_design_id: _Id

    @model_validator(mode="after")
    def selected(self):
        if not 1 <= len(self.protein_ids) + len(self.nanoparticle_ids) <= commands.MAX_ELEMENTS:
            raise ValueError(f"Copy requires 1–{commands.MAX_ELEMENTS} selected rigid elements")
        if any(len(set(values)) != len(values) for values in (self.protein_ids, self.nanoparticle_ids)):
            raise ValueError("Copy selections must be unique within each resource kind")
        return self


@router.post("/design/features/copy-elements")
def copy_elements(body: ElementCopyRequest):
    """Resolve current-part sources and record one independent rigid-copy step."""
    state.get_or_404()
    params = {
        "_proof_version": 1, "copy_version": 1,
        "protein_ids": body.protein_ids, "protein_output_ids": [str(uuid4()) for _ in body.protein_ids],
        "nanoparticle_ids": body.nanoparticle_ids,
        "nanoparticle_output_ids": [str(uuid4()) for _ in body.nanoparticle_ids],
        "paste_index": body.paste_index,
    }
    refs = []

    def candidate(design):
        nonlocal refs
        if design.id != body.expected_design_id:
            raise HTTPException(409, detail={"code": "design_identity_mismatch",
                "detail": "The active part changed before the copy could be recorded.",
                "expected_design_id": body.expected_design_id, "actual_design_id": design.id})
        updated, refs = commands.evaluate("element-paste", design, params)
        return updated

    try:
        updated, report, _ = state.mutate_with_feature_log(
            "element-paste", "Copy rigid elements", params, candidate,
            expected_revision=body.expected_revision,
        )
    except CommandContractError as error:
        status = 404 if error.code == "missing_reference" else 413 if error.code == "source_limit" else 422
        raise HTTPException(status, detail={"status": error.status, **error.as_issue()}) from error
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"status": "unverified", "code": "command_limit",
                                        "detail": str(error)}) from error
    except ValueError as error:
        raise HTTPException(422, detail={"status": "failed", "code": "invalid_copy_input",
                                        "detail": str(error)}) from error
    return {**_design_response(updated, report), "pasted_refs": refs}
