"""Pinned caDNAno import into a fresh empty part; legacy upload stays separate."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from starlette.concurrency import run_in_threadpool

from backend.api import part_cadnano_commands as commands, state
from backend.api.crud import _design_response
from backend.api.part_recovery_budget import RecoveryBudget
from backend.core.models import SnapshotLogEntry
from backend.core.part_cadnano_source import MAX_SOURCE_BYTES
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES, create_empty_part
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_input_sources import EmbeddedResolver, describe, embed
from backend.core.validator import validate_design


router = APIRouter()


class ReplacementQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_design_id: str = Field(min_length=1, max_length=256)
    expected_revision: StrictInt = Field(ge=0)
    name_override: str | None = Field(default=None, max_length=1_024)

    @field_validator("expected_revision", mode="before")
    @classmethod
    def decimal_http_revision(cls, value):
        # Query values arrive as strings. Accept decimal revisions only, without
        # Pydantic's normal float/string/bool coercions or unbounded integers.
        if isinstance(value, str):
            if not value.isascii() or not value.isdecimal() or len(value) > 19:
                raise ValueError("expected_revision must be a nonnegative decimal integer")
            return int(value)
        return value


def _current(query):
    source, revision = state.get_design_with_revision()
    if source is None:
        raise HTTPException(404, detail={"code": "active_part_required",
            "detail": "Create a fresh empty part or tab before importing a pinned caDNAno source."})
    if source.id != query.expected_design_id or revision != query.expected_revision:
        raise HTTPException(409, detail={"code": "stale_import_target",
            "detail": "The active part changed before this replacement could be prepared.",
            "expected_design_id": query.expected_design_id, "actual_design_id": source.id,
            "expected_revision": query.expected_revision, "actual_revision": revision})
    try:
        commands._empty_input(source)
        if len(source.recipe_root.initial_name) > 1_024:
            raise ValueError("Empty part name exceeds the bounded import host contract")
        baseline = create_empty_part(source.recipe_root.initial_name, source.recipe_root.lattice_type)
        # A geometrically empty recipe can still retain large imported sources,
        # loadouts, annotations or physical results. Replacing those would make
        # the undo snapshot expensive under the shared state lock. This explicit
        # entry point admits a fresh empty host; pure replay retains its broader
        # source-table/presentation-preservation contract.
        if set(type(source).model_fields) != set(FIELD_ROLES):
            raise ValueError("Part schema contains unclassified fields")
        fields = {name for name, role in FIELD_ROLES.items()
                  if role in {"input_source", "presentation", "physical", "repair_draft"}}
        if any(getattr(source, name) != getattr(baseline, name) for name in fields):
            raise ValueError("Part retains source, presentation, physical or repair draft state")
    except ValueError as error:
        raise HTTPException(422, detail={"code": "fresh_empty_part_required",
            "detail": "Create a fresh empty part or tab for pinned caDNAno import. The existing upload route supports ordinary document replacement."}) from error
    return source


def _transport_error(detail, *, status=413):
    raise HTTPException(status, detail={"code": "source_limit" if status == 413 else "invalid_import_transport",
                                       "detail": detail})


async def _read_source(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        _transport_error("Send the original caDNAno JSON bytes as application/json.", status=415)
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        _transport_error("Compressed source request bodies are unsupported.", status=415)
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1:
        _transport_error("Supply at most one Content-Length header.", status=400)
    if lengths:
        length = lengths[0]
        if not length.isascii() or not length.isdecimal() or len(length) > 19:
            _transport_error("Content-Length must be a nonnegative decimal integer.", status=400)
        if int(length) > MAX_SOURCE_BYTES:
            _transport_error("Pinned caDNAno source exceeds 100,000 bytes.")
    output = bytearray()
    async for chunk in request.stream():
        # Check before retaining/copying another chunk. ASGI transport buffers
        # are server-owned; the application never eagerly reads an entire body.
        if len(chunk) > MAX_SOURCE_BYTES - len(output):
            _transport_error("Pinned caDNAno source exceeds 100,000 bytes.")
        output.extend(chunk)
    return bytes(output)


def _prepare(raw, name_override):
    """Private complete lineage and response; no active document is modified."""
    source = describe(raw, format="cadnano-v2", media_type="application/json")
    initial = create_empty_part(name_override if name_override is not None else "Imported caDNAno", "HONEYCOMB")
    initial = initial.copy_with(input_sources={source.sha256: embed(source, raw)})
    params = {"_proof_version": 1, "lattice_import_version": 1, "importer_version": 1,
        "source": source.model_dump(mode="json"), "history_seed": str(uuid4()),
        "identity_policy": "source-content-v1", "name_override": name_override}
    budget = RecoveryBudget()
    pre, pre_size = state.encode_design_snapshot(initial)
    budget.charge(pre)
    candidate, warnings = commands.evaluate("cadnano-import", initial, params,
                                            resolver=EmbeddedResolver(initial.input_sources))
    post, post_size = state.encode_design_snapshot(candidate)
    budget.charge(post)
    entry = SnapshotLogEntry(op_kind="cadnano-import", label=f"Import caDNAno · {candidate.metadata.name}",
        timestamp=datetime.now(timezone.utc).isoformat(), params=params,
        design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)
    candidate = candidate.copy_with(feature_log=[entry])
    report = validate_design(candidate)
    # Recipe roots explicitly bypass _design_response's legacy normalization,
    # so formatting this private candidate cannot publish a default cluster.
    response = _design_response(candidate, report, full_feature_log=True)
    if warnings:
        response["import_warnings"] = warnings
    return candidate, response


@router.post("/design/features/import/cadnano", status_code=201,
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {
        "schema": {"type": "object", "required": ["vstrands"]},
        "description": "Original UTF-8 caDNAno v2 JSON source, at most 100,000 bytes."}}}})
async def import_cadnano(request: Request, query: Annotated[ReplacementQuery, Query()]):
    """Import a pinned caDNAno recipe into a fresh empty active part, with one undo.

    This is a complete replacement of the fresh empty host, not an append.
    The required target identity and revision must match at preparation and
    publication. Retained sources, history, physical state and presentation
    content require creating another empty part or tab first. Undo restores
    that small fresh part. The legacy /design/import/cadnano endpoint remains
    available for ordinary nonempty document replacement.
    """
    if any(len(request.query_params.getlist(key)) > 1 for key in ReplacementQuery.model_fields):
        _transport_error("Import query fields must not be repeated.", status=422)
    source = _current(query)
    raw = await _read_source(request)
    try:
        candidate, response = await run_in_threadpool(_prepare, raw, query.name_override)
    except CommandContractError as error:
        raise HTTPException(413 if error.code == "source_limit" else 422,
                            detail={"status": error.status, **error.as_issue()}) from error
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"status": "unverified", "code": "command_limit",
                                        "detail": str(error)}) from error
    except ValueError as error:
        raise HTTPException(422, detail={"status": "failed", "code": "invalid_cadnano_input",
                                        "detail": str(error)}) from error
    if await request.is_disconnected():
        raise HTTPException(499, detail="Import cancelled before publication.")
    # This established state helper owns the lock, identity/revision recheck
    # and the single undo snapshot. Never publish the private root temporarily.
    response["revision"] = await run_in_threadpool(state.set_design, candidate,
        expected_revision=query.expected_revision, expected_source=source)
    return response
