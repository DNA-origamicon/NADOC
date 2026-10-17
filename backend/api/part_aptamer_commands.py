"""Pinned single-chain aptamer inputs using the unchanged deposited-DNA importer.

This contract reproduces an imported structure; it never certifies native-only
construction. PDB bytes live in the source table, not in feature parameters.
"""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.core.feature_identity import identity_factory
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_input_sources import (
    EmbeddedResolver, InputSource, SourceContractError, decode, describe, embed, verify,
)


KINDS = frozenset({"aptamer-import"})
# Qualified against the bundled templates and a complete boundary fixture in
# aptamer_capture_benchmark_p4.json. Whole-document proof budgets still apply;
# larger/multiple-chain legacy imports remain compatible.
MAX_APTAMER_SOURCE_BYTES = 150_000
MAX_APTAMER_ATOM_RECORDS = 1_000
NATIVE_ROUTE_ENABLED = True
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    aptamer_version: StrictInt = Field(ge=1, le=1)
    importer_version: StrictInt = Field(ge=1, le=1)
    source: InputSource
    name: str = Field(max_length=1_024)
    source_label: str = Field(max_length=1_024)
    helix_id: _Id = Field(alias="_helix_id")
    strand_id: _Id = Field(alias="_strand_id")
    history_seed: _Id
    initialize_metadata: StrictBool

    @model_validator(mode="after")
    def identity_namespace(self):
        UUID(self.history_seed)
        return self


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported pinned aptamer command")
    return ImportRequest.model_validate(params)


def resources(kind, params):
    command = parse_command(kind, params)
    return {"sources": (command.source,), "imports": True}


def _first_model_records(text):
    count = 0
    for line in text.splitlines():
        record = line[:6].strip()
        if record == "ENDMDL":
            break
        if record in {"ATOM", "HETATM"}:
            count += 1
    return count


def _single_chain(imported):
    if not (len(imported.helices) == len(imported.strands) == len(imported.cluster_transforms) == 1):
        return False
    helix, strand, cluster = imported.helices[0], imported.strands[0], imported.cluster_transforms[0]
    return (bool(helix.native_residues) and len(strand.domains) == 1
            and strand.domains[0].helix_id == helix.id and cluster.helix_ids == [helix.id])


def _incoming_resources(design):
    from backend.core.part_scope_references import COLLECTIONS, referenced_resources

    for field in COLLECTIONS:
        for item in getattr(design, field):
            yield referenced_resources(item)


def native_route_eligible(text, imported, design=None):
    """Select compatibility before evaluation, never fall back after a failure."""
    if not (NATIVE_ROUTE_ENABLED and len(text) <= MAX_APTAMER_SOURCE_BYTES
            and len(text.encode("utf-8")) <= MAX_APTAMER_SOURCE_BYTES
            and _first_model_records(text) <= MAX_APTAMER_ATOM_RECORDS
            and _single_chain(imported)):
        return False
    if design is not None:
        try:
            for _ in _incoming_resources(design):
                pass
        except NotImplementedError:
            return False
    return True


def _reference(kind, identity, path, detail):
    raise ReferenceResolutionError(detail, code="invalid_selection", references=[{
        "kind": kind, "identity": identity, "parameter_path": path,
    }])


def _source_text(source, resolver):
    if source.format != "pdb" or source.media_type != "chemical/x-pdb":
        raise SourceContractError("This aptamer importer requires a chemical/x-pdb PDB source",
                                  source=source, code="unsupported_source")
    if source.size_bytes > MAX_APTAMER_SOURCE_BYTES:
        raise SourceContractError("Aptamer source exceeds the initial 150 KB import contract",
                                  source=source, code="source_limit")
    raw = verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourceContractError("The pinned aptamer PDB source must be UTF-8 text",
                                  source=source, code="unsupported_source") from exc
    if _first_model_records(text) > MAX_APTAMER_ATOM_RECORDS:
        raise SourceContractError("Aptamer source exceeds the initial 1,000 first-model atom-record contract",
                                  source=source, code="source_limit")
    return text


def _metadata(design, command, imported):
    if not command.initialize_metadata:
        return design.metadata
    from backend.core.models import Design
    from backend.core.part_history_contract import FIELD_ROLES

    baseline = Design(lattice_type=design.lattice_type)
    if (design.recipe_root is None or design.recipe_root.kind != "empty" or design.feature_log
            or any(getattr(design, key) != getattr(baseline, key)
                   for key, role in FIELD_ROLES.items() if role == "authoring" and key != "metadata")):
        _reference("recipe_root", "empty", ["initialize_metadata"],
                   "Initial aptamer metadata requires an empty authored part")
    return imported.metadata


def build(kind, design, params, *, resolver=None):
    """Derive exact native sites from pinned bytes; normalize identities only."""
    command = parse_command(kind, params)
    cluster_id = identity_factory(command.history_seed)("aptamer-cluster", [command.helix_id])
    for records, identity, ref_kind, path in (
        (design.helices, command.helix_id, "helix", ["_helix_id"]),
        (design.strands, command.strand_id, "strand", ["_strand_id"]),
        (design.cluster_transforms, cluster_id, "cluster", ["history_seed"]),
    ):
        if any(item.id == identity for item in records):
            _reference(ref_kind, identity, path, "Aptamer output identity already exists")
    outputs = {("helix", command.helix_id): ["_helix_id"],
               ("strand", command.strand_id): ["_strand_id"],
               ("cluster", cluster_id): ["history_seed"]}
    try:
        for refs in _incoming_resources(design):
            for kind, identity in sorted(refs & outputs.keys()):
                _reference(kind, identity, outputs[(kind, identity)],
                           "Aptamer output identity already has an incoming reference")
    except NotImplementedError as exc:
        raise CommandContractError(f"Aptamer output ownership cannot be resolved: {exc}",
                                   code="unsupported_aptamer_source") from exc
    text = _source_text(command.source, resolver)
    from backend.core.aptamer import import_aptamer

    imported = import_aptamer(text, command.name, command.source_label)
    if not _single_chain(imported):
        raise SourceContractError("This aptamer contract requires one complete logical DNA chain",
                                  source=command.source, code="unsupported_source")
    helix = imported.helices[0].model_copy(update={"id": command.helix_id})
    strand = imported.strands[0].model_copy(update={"id": command.strand_id, "domains": [
        imported.strands[0].domains[0].model_copy(update={"helix_id": command.helix_id}),
    ]})
    cluster = imported.cluster_transforms[0].model_copy(update={
        "id": cluster_id, "helix_ids": [command.helix_id],
    })
    return design.copy_with(helices=[*design.helices, helix], strands=[*design.strands, strand],
        cluster_transforms=[*design.cluster_transforms, cluster], metadata=_metadata(design, command, imported))


def record_import(text, name, source_label, *, expected_revision=None):
    """Pin one selected input and publish source/definition/output atomically."""
    from fastapi import HTTPException

    from backend.api import state
    from backend.core.part_history_contract import create_empty_part

    # This entry point is used only after eligibility has been selected. Keep
    # hard bounds here too so no alternate caller allocates unbounded bytes.
    if len(text) > MAX_APTAMER_SOURCE_BYTES:
        raise HTTPException(413, detail="Aptamer source exceeds the initial 150 KB import contract")
    raw = text.encode("utf-8")
    if len(raw) > MAX_APTAMER_SOURCE_BYTES:
        raise HTTPException(413, detail="Aptamer source exceeds the initial 150 KB import contract")
    source = describe(raw, format="pdb", media_type="chemical/x-pdb")
    blob = embed(source, raw)
    initial = create_empty_part(name, "HONEYCOMB")
    params = {"_proof_version": 1, "aptamer_version": 1, "importer_version": 1,
              "source": source.model_dump(mode="json"), "name": name, "source_label": source_label,
              "_helix_id": f"apt_{uuid4().hex[:12]}", "_strand_id": str(uuid4()),
              "history_seed": str(uuid4()), "initialize_metadata": False}

    def apply(design):
        params["initialize_metadata"] = design.id == initial.id
        existing = design.input_sources.get(source.sha256)
        if existing is not None:
            decode(source, existing)
        candidate = design.copy_with(input_sources={**design.input_sources,
            source.sha256: existing if existing is not None else blob})
        return build("aptamer-import", candidate, params, resolver=EmbeddedResolver(candidate.input_sources))

    try:
        return state.mutate_with_feature_log("aptamer-import", f"Import aptamer {name}", params, apply,
            expected_revision=expected_revision, initial_design=initial)
    except CommandContractError as exc:
        raise HTTPException(413 if exc.code == "source_limit" else 422,
                            detail={"status": exc.status, **exc.as_issue()}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
