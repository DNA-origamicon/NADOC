"""Open a local assembly without transferring its source through the browser.

Delegates to the existing import command, retaining its validation, migration,
memory policy, feature history, source resolution and response contract.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import assembly

router = APIRouter()


class OpenAssemblyRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


@router.post("/library/open-assembly")
def open_library_assembly(body: OpenAssemblyRequest) -> dict:
    source = assembly._safe_workspace_path(body.path)
    if source.suffix.lower() != ".nass":
        raise HTTPException(400, "Expected a .nass assembly")
    if not source.is_file():
        raise HTTPException(404, "Assembly not found in workspace")
    try:
        content = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HTTPException(400, "Could not read assembly") from exc
    return assembly.import_assembly(assembly.AssemblyImportRequest(content=content))
