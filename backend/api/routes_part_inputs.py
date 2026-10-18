"""Explicit immutable-input features for the current standard part."""

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field, StrictBool, StrictInt, field_validator

from backend.api import state
from backend.api.crud import _design_response
from backend.api.part_protein_commands import MAX_PROTEIN_SOURCE_BYTES, build
from backend.core.part_command_errors import CommandContractError
from backend.core.part_input_sources import EmbeddedInput, EmbeddedResolver, InputSource, decode


router = APIRouter()
_MAX_SMALL_ENCODED_BYTES = 4 * ((MAX_PROTEIN_SOURCE_BYTES + 2) // 3)


class ProteinImportRequest(EmbeddedInput):
    source: InputSource
    data_b64: str = Field(max_length=_MAX_SMALL_ENCODED_BYTES)
    name: str = Field(default="", max_length=1_024)
    source_filename: str = Field(default="", max_length=1_024)
    exclude_dna: StrictBool = False
    expected_revision: StrictInt = Field(ge=0)

    @field_validator("source")
    @classmethod
    def supported_source(cls, source):
        if source.format != "pdb" or source.media_type != "chemical/x-pdb":
            raise ValueError("Protein import requires a chemical/x-pdb PDB source")
        if source.size_bytes > MAX_PROTEIN_SOURCE_BYTES:
            raise ValueError("Protein source exceeds the initial 250 KB import contract")
        return source


@router.post("/design/features/import/protein", status_code=201)
def import_protein(body: ProteinImportRequest):
    """Record source import only; placement is a separate authored operation."""
    state.get_or_404()
    blob = EmbeddedInput(data_b64=body.data_b64)
    try:
        # Decode and verify request bytes before the state lock or any snapshot
        # allocation. The callback rechecks the table it will actually publish.
        decode(body.source, blob)
        asset_id = str(uuid4())
        params = {
            "_proof_version": 1, "protein_version": 1, "importer_version": 1,
            "source": body.source.model_dump(mode="json"), "asset_id": asset_id,
            "name": body.name, "source_filename": body.source_filename,
            "exclude_dna": body.exclude_dna,
        }

        def candidate(design):
            existing = design.input_sources.get(body.source.sha256)
            if existing is not None:
                # Never silently overwrite corrupted immutable evidence with a
                # fresh upload, even when another feature reuses the same hash.
                decode(body.source, existing)
            table = {**design.input_sources, body.source.sha256: existing or blob}
            resolver = EmbeddedResolver(table)
            return build("protein-import", design.copy_with(input_sources=table), params,
                         resolver=resolver)

        updated, report, _ = state.mutate_with_feature_log(
            "protein-import", f"Import protein {body.name or body.source_filename or 'Protein'}",
            params, candidate, expected_revision=body.expected_revision,
        )
    except CommandContractError as error:
        raise HTTPException(413 if error.code == "source_limit" else 422,
                            detail={"status": error.status, **error.as_issue()}) from error
    except ValueError as error:
        raise HTTPException(422, detail={"code": "invalid_protein_input", "detail": str(error)}) from error
    return {**_design_response(updated, report), "asset_id": asset_id}
