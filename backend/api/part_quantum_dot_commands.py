"""Catalog-backed particle recipes with immutable inputs and native pose math.

Catalog metadata is an imported source, not evidence of native construction.
The optional vendor spectra image is presentation data; no recipe reads its
path or URL. Coated/coupled particles retain their separate legacy contract.
"""

import json
import math
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.api.part_nanoparticle_commands import GizmoMove, _Diameter, _Number
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_input_sources import EmbeddedResolver, InputSource, SourceContractError, decode, verify


KINDS = frozenset({"nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"})
MAX_CATALOG_BYTES = 65_536
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    quantum_dot_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: _Id


class CreateRequest(_Input):
    source: InputSource
    catalog_id: _Id
    # Resolve the default once in the live adapter and retain the chosen size.
    diameter_nm: Annotated[float, Field(strict=True, gt=0, le=1000, allow_inf_nan=False)]


class DeleteRequest(_Input):
    pass


class PatchRequest(_Input):
    diameter_nm: _Diameter | None = None
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: GizmoMove | None = None
    coating: None = None


def parse_command(kind, params):
    model = {"nanoparticle-create": CreateRequest, "nanoparticle-patch": PatchRequest,
             "nanoparticle-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported quantum dot command")
    return model.model_validate(params)


def resources(kind, params):
    command = parse_command(kind, params)
    return {"sources": (command.source,), "imports": True} if kind == "nanoparticle-create" else {
        "sources": (), "imports": False,
    }


def _fail(identity, detail, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": "nanoparticle", "identity": identity, "parameter_path": ["nanoparticle_id"]}])


def native_target(design, identity):
    from backend.api.part_nanoparticle_commands import _incoming_owner

    matches = [item for item in design.nanoparticles if item.id == identity]
    if len(matches) != 1:
        _fail(identity, "Quantum dot target is missing or ambiguous", missing=not matches)
    particle = matches[0]
    return (particle.kind == "quantum_dot" and particle.quantum_dot is not None
            and particle.coating is None and not particle.biotin_dna and not _incoming_owner(design, identity))


def route_native_target(design, identity):
    try:
        return native_target(design, identity)
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error


def _catalog(command, resolver):
    from backend.core.models import QuantumDotSpec

    source = command.source
    if source.format != "quantum-dot-catalog" or source.media_type != "application/json":
        raise SourceContractError("Quantum dot import requires a pinned catalog entry", source=source,
                                  code="unsupported_source")
    if source.size_bytes > MAX_CATALOG_BYTES:
        raise SourceContractError("Quantum dot catalog entry exceeds 64 KiB", source=source, code="source_limit")
    raw = verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate catalog field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite catalog value")

    try:
        entry = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_object,
                           parse_constant=invalid_constant)
    except (ValueError, RecursionError) as error:
        raise SourceContractError("Quantum dot catalog is not supported JSON", source=source,
                                  code="unsupported_source") from error
    if (not isinstance(entry, dict) or entry.get("catalog_id") != command.catalog_id
            or entry.get("import_enabled") is not True):
        raise SourceContractError("Catalog entry identity or import policy disagrees with the command",
                                  source=source, code="unsupported_source")
    try:
        spec = QuantumDotSpec.model_validate(entry)
        pending = [spec.model_dump()]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, (list, tuple)):
                pending.extend(value)
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Catalog numbers must be finite")
        for bounds in (spec.diameter_range_nm, spec.core_diameter_range_nm):
            if bounds is not None and not 0 < bounds[0] <= bounds[1]:
                raise ValueError("Catalog diameter ranges must be positive and ordered")
    except ValueError as error:
        raise SourceContractError(f"Unsupported quantum dot specification: {error}", source=source,
                                  code="unsupported_source") from error
    return entry


def build(kind, design, params, *, resolver=None):
    from backend.api.part_nanoparticle_commands import _incoming_owner
    from backend.core.nanoparticle import replace_gold_nanosphere
    from backend.core.quantum_dots import create_quantum_dot_from_entry, validate_quantum_dot_diameter

    command = parse_command(kind, params)
    identity = command.nanoparticle_id
    if kind == "nanoparticle-create":
        if any(item.id == identity for item in design.nanoparticles) or _incoming_owner(design, identity):
            _fail(identity, "Quantum dot output identity already exists or has dependent ownership")
        particle = create_quantum_dot_from_entry(_catalog(command, resolver), command.diameter_nm,
                                                nanoparticle_id=identity)
        return design.copy_with(nanoparticles=[*design.nanoparticles, particle])
    if not native_target(design, identity):
        _fail(identity, "Native quantum dot changes require an uncoated particle without DNA or connection ownership")
    if kind == "nanoparticle-delete":
        return design.copy_with(nanoparticles=[item for item in design.nanoparticles if item.id != identity])
    particle = next(item for item in design.nanoparticles if item.id == identity)
    if command.diameter_nm is not None:
        validate_quantum_dot_diameter(particle.quantum_dot, command.diameter_nm)
    return replace_gold_nanosphere(design, identity, diameter_nm=command.diameter_nm, pose=command.pose,
                                  gizmo_move=command.gizmo_move.model_dump() if command.gizmo_move else None)


def record(kind, label, inputs, *, source_blob=None, expected_revision=None):
    from backend.api import state

    params = {**inputs, "_proof_version": 1, "quantum_dot_version": 1}

    def native(design):
        try:
            candidate = design
            if source_blob is not None:
                source = InputSource.model_validate(params["source"])
                existing = design.input_sources.get(source.sha256)
                if existing is not None:
                    decode(source, existing)
                candidate = design.copy_with(input_sources={**design.input_sources,
                    source.sha256: existing or source_blob})
            return build(kind, candidate, params, resolver=EmbeddedResolver(candidate.input_sources))
        except ReferenceResolutionError as error:
            raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error
        except SourceContractError as error:
            raise HTTPException(422, detail=error.as_issue()) from error
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error

    return state.mutate_with_feature_log(kind, label, params, native, expected_revision=expected_revision)


def record_import(catalog_id, diameter_nm, *, expected_revision=None):
    """Capture a library input once; keep its native route adapter declarative."""
    from uuid import uuid4
    from backend.core.part_input_sources import describe, embed
    from backend.core.quantum_dots import catalog_entry, create_quantum_dot_from_entry

    try:
        raw = json.dumps(catalog_entry(catalog_id), sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(raw) > MAX_CATALOG_BYTES:
            raise HTTPException(413, detail="Quantum dot catalog entry exceeds 64 KiB")
        identity = str(uuid4())
        particle = create_quantum_dot_from_entry(json.loads(raw), diameter_nm, nanoparticle_id=identity)
    except KeyError:
        raise HTTPException(404, detail="Quantum dot not found in catalog.")
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    source = describe(raw, format="quantum-dot-catalog", media_type="application/json")
    updated, report, _ = record("nanoparticle-create",
        f"Import {particle.quantum_dot.product_name} quantum dot ({particle.diameter_nm:g} nm)",
        {"nanoparticle_id": identity, "catalog_id": catalog_id,
         "source": source.model_dump(), "diameter_nm": particle.diameter_nm},
        source_blob=embed(source, raw), expected_revision=expected_revision)
    return updated, report, identity
