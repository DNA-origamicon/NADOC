"""Two native protein features for the ordinary free-import workflow.

This records a bounded native suffix, not a whole-history certificate. Parsing
and recovery preparation run privately; the host publishes both rows, sources
and the library cache entry under one guarded transaction with one undo copy.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from time import monotonic, perf_counter
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException

from backend.api import doc_context, state
from backend.api.part_protein_commands import MAX_PROTEIN_ATOM_RECORDS, MAX_PROTEIN_SOURCE_BYTES
from backend.api.part_recovery_budget import MAX_RECOVERY_BYTES, RecoveryBudget
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES, create_empty_part
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_input_sources import (
    MAX_SOURCES, SourceContractError, command_sources, decode, describe, embed,
)
from backend.core.part_overlay_commands import command_input
from backend.core.part_recipe_publication import preserve_document_state
from backend.core.part_verification_capture import CaptureLimit, admit, capture


MAX_ROWS = 2000
_METADATA_NODES = 10_000
_METADATA_BYTES = 256_000
_PAYLOADS = ("design_snapshot_gz_b64", "post_state_gz_b64", "pre_state_gz_b64",
             "diff_added_b64", "diff_removed_b64", "diff_modified_b64")


@dataclass(frozen=True)
class ImportCapture:
    session: object
    doc_id: str
    source: Design | None
    revision: int
    isolated: Design
    initial: Design | None
    operation_id: str
    identities: dict
    raw: bytes
    name: str
    exclude_dna: bool
    timestamp: str
    recovery_bytes: int
    metadata_nodes: int
    metadata_bytes: int


@dataclass(frozen=True)
class PreparedImport:
    candidate: Design
    rows: tuple
    asset: object
    validation: object
    stages_ms: dict
    response: dict
    asset_meta: dict


def source_eligibility(text, name):
    """Cheap route selection before any parser/native builder is called."""
    if len(text) > MAX_PROTEIN_SOURCE_BYTES or len(text.encode("utf-8")) > MAX_PROTEIN_SOURCE_BYTES:
        return "source_bytes"
    if len(name) > 1024:
        return "source_name"
    if sum(line[:6].rstrip() in {"ATOM", "HETATM"} for line in text.splitlines()) > MAX_PROTEIN_ATOM_RECORDS:
        return "source_atom_records"
    return None


def _identity(design_id, operation_id):
    namespace = uuid5(NAMESPACE_URL, "nadoc:protein-free-import:v1:" + json.dumps([design_id, operation_id]))
    return {role: str(uuid5(namespace, role)) for role in ("import", "attachment", "asset", "placement")}


def _duplicate(design, operation_id, identity):
    if design is not None and any(
        entry.id == identity or (getattr(entry, "op_kind", None) == "protein-import"
            and entry.params.get("operation_id") == operation_id) for entry in design.feature_log
    ):
        raise HTTPException(409, detail=f"Protein import operation {operation_id} was already committed.")


def _retained_metadata(design, deadline):
    """Admit bounded presentation/proposal state before its undo copy.

    Physical loadouts/results are outside this first ordinary import slice.
    Their presence is checked by field, not by traversing stored simulation
    graphs. Small presentation and repair metadata are preserved exactly.
    """
    if set(type(design).model_fields) != set(FIELD_ROLES):
        raise CaptureLimit("Protein import cannot classify this document schema")
    baseline = Design()
    for name, role in FIELD_ROLES.items():
        if role == "physical" and getattr(design, name) != getattr(baseline, name):
            raise CaptureLimit(f"Native free protein import initially requires default {name}")
    from backend.core.part_repair_capture import _Copier
    from pydantic import BaseModel

    # Narrow reuse of the draft copier; promote the utility only after its two
    # callers settle. Never drop hidden state from an admitted retained model.
    class MetadataCopier(_Copier):
        def clone(self, value, depth=0):
            if isinstance(value, BaseModel) and (
                value.__pydantic_extra__ is not None or value.__pydantic_private__ is not None
                or value.__dict__.keys() != type(value).model_fields.keys()
            ):
                raise CaptureLimit("Protein import cannot classify private or extra retained metadata")
            return super().clone(value, depth)

    values = {name: getattr(design, name) for name, role in FIELD_ROLES.items()
              if role in {"presentation", "repair_draft"}}
    copier = MetadataCopier(_METADATA_NODES, _METADATA_BYTES, max(0, deadline - monotonic()))
    try:
        retained = copier.clone(values)
    except ValueError as error:
        raise CaptureLimit(f"Protein import retained metadata cannot be admitted: {error}") from error
    return retained, _METADATA_NODES - copier.nodes, _METADATA_BYTES - copier.size


def capture_import(text, name, exclude_dna, operation_id, expected_revision):
    """Return an owned input or a pre-native rootless compatibility reason."""
    state.require_compatibility_write("protein_import")
    if type(operation_id) is not str or not 1 <= len(operation_id) <= 256:
        raise HTTPException(422, detail="Protein import operation ID must contain 1..256 characters")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise HTTPException(422, detail="Protein import revision must be a nonnegative integer")
    reason = source_eligibility(text, name)
    raw = text.encode("utf-8") if reason is None else None
    with state._lock:
        session = state._session()
        source, revision = session.design, session.revision
        if expected_revision is not None and expected_revision != revision:
            raise HTTPException(409, detail="Design changed while this import was being prepared.")
        if reason:
            if source is None or source.recipe_root is None:
                return None, reason
            raise HTTPException(413, detail={"code": "protein_import_source_limit", "detail": reason,
                                            "status": "unverified"})
        initial = create_empty_part("Untitled", "HONEYCOMB") if source is None else None
        current = source if source is not None else initial
        identities = _identity(current.id, operation_id)
        state._assert_active_loadout_editable(current)
        try:
            deadline = monotonic() + 0.025
            if current.feature_log_cursor != -1 or current.feature_log_sub_cursor is not None:
                raise CaptureLimit("Native protein import requires the current feature history cursor")
            if len(current.feature_log) > MAX_ROWS - 2:
                raise CaptureLimit("Protein import requires room for two native features")
            # Count definitions without serializing overlay inputs before the
            # bounded authoring traversal has admitted them.
            row_count = len(current.feature_log)
            for entry in current.feature_log:
                if entry.feature_type == "routing-cluster":
                    row_count += len(entry.children)
                if row_count > MAX_ROWS - 2:
                    raise CaptureLimit("Protein import requires room for two native features")
            _duplicate(source, operation_id, identities["import"])
            recovery_bytes = 0
            for entry in current.feature_log:
                for row in [entry, *getattr(entry, "children", [])]:
                    recovery_bytes += sum(len(getattr(row, field, "") or "") for field in _PAYLOADS)
                if recovery_bytes > MAX_RECOVERY_BYTES:
                    raise CaptureLimit("Protein import retained recovery exceeds the existing 8 MB allowance")
            retained, metadata_nodes, metadata_bytes = _retained_metadata(current, deadline)
            isolated = capture(current, max_nodes=30_000 - metadata_nodes, max_bytes=2_000_000 - metadata_bytes,
                               seconds=max(0, deadline - monotonic()), preserve_entry_types=True)
            isolated = isolated.copy_with(**retained)
        except CaptureLimit as error:
            if source is not None and source.recipe_root is None:
                return None, f"legacy_document_scope: {error}"
            raise HTTPException(413, detail={"code": "protein_import_capture_limit", "detail": str(error),
                                            "status": "unverified"}) from error
    return ImportCapture(session, doc_context.get_current_doc(), source, revision,
                         isolated, initial, operation_id, identities, raw, name, exclude_dna,
                         datetime.now(timezone.utc).isoformat(), recovery_bytes, metadata_nodes, metadata_bytes), None


def prepare_import(captured):
    """Execute the existing import once, then its explicitly selected placement."""
    from backend.api.part_proof_commands import execute
    from backend.core.validator import validate_design

    current = captured.isolated
    descriptor = describe(captured.raw, format="pdb", media_type="chemical/x-pdb")
    table = dict(current.input_sources)
    if descriptor.sha256 in table:
        decode(descriptor, table[descriptor.sha256])
    else:
        for entry in current.feature_log:
            for child in entry.children if entry.feature_type == "routing-cluster" else [entry]:
                kind, params = command_input(child)
                try:
                    declarations = command_sources(kind, params)
                except ValueError:
                    # An unrelated already-broken descriptor is not a reason
                    # to certify, repair, or forbid this independent suffix.
                    # Still refuse to fill an old declaration of these bytes.
                    if any(isinstance(params.get(key), dict) and params[key].get("sha256") == descriptor.sha256
                           for key in ("source", "pdb_source", "coverage_source")):
                        raise SourceContractError("Existing feature input is missing; use explicit source repair",
                                                  source=descriptor, code="source_unavailable") from None
                    continue
                for declared in declarations:
                    if declared.sha256 == descriptor.sha256:
                        raise SourceContractError("Existing feature input is missing; use explicit source repair",
                                                  source=declared, code="source_unavailable")
        if len(table) >= MAX_SOURCES:
            raise ProofBudgetExceeded("Protein import exceeds the portable source count allowance")
        table[descriptor.sha256] = embed(descriptor, captured.raw)
    current = current.copy_with(input_sources=table)
    rows, times = [], {}
    budget = RecoveryBudget(MAX_RECOVERY_BYTES - captured.recovery_bytes)

    def append(role, kind, label, params):
        nonlocal current
        started = perf_counter()
        updated = execute(kind, current, params)
        times[role] = (perf_counter() - started) * 1000
        started = perf_counter()
        pre, pre_size = state.encode_design_snapshot(current)
        post, post_size = state.encode_design_snapshot(updated)
        budget.charge(pre, post)
        times["recovery"] = times.get("recovery", 0) + (perf_counter() - started) * 1000
        row = SnapshotLogEntry(id=captured.identities[role], timestamp=captured.timestamp,
            op_kind=kind, label=label, params=params, design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
            post_state_gz_b64=post, post_state_size_bytes=post_size)
        rows.append(row)
        current = updated.copy_with(feature_log=[*current.feature_log, row])

    base = {"_proof_version": 1, "protein_version": 1, "asset_id": captured.identities["asset"]}
    append("import", "protein-import", f"Import protein {captured.name or 'Protein'}", {
        **base, "importer_version": 1, "source": descriptor.model_dump(mode="json"),
        "name": captured.name, "source_filename": captured.name, "exclude_dna": captured.exclude_dna})
    asset = next(item for item in current.protein_assets if item.id == captured.identities["asset"])
    append("placement", "protein-attach", f"Place protein {asset.name}", {
        **base, "attachment_id": captured.identities["attachment"], "target": {"kind": "free"},
        "conjugation_atom_serial": asset.default_conjugation_atom_serial,
        "handle_complement_bp": 0, "handle_spacer_nt": 0, "pose": None, "visible": True})
    # This candidate is already private. Check the same authoring node/byte
    # allowance without making a second isolated graph or imposing a second
    # source-capture deadline. Source isolation above retains its own deadline.
    started = perf_counter()
    admit(current, max_nodes=30_000 - captured.metadata_nodes, max_bytes=2_000_000 - captured.metadata_bytes,
          preserve_entry_types=True)
    times["candidate_admission"] = (perf_counter() - started) * 1000
    validation = validate_design(current)
    from backend.api.crud import _design_response
    from backend.core.protein import protein_asset_meta

    started = perf_counter()
    response = _design_response(current, validation, normalize_legacy=False)
    if not doc_context.should_skip_geometry():
        # Both new rows are absent from the browser's recovery cache. Previous
        # rows remain slim; a native suffix never normalizes a legacy prefix.
        new_rows = {row.id: row.model_dump(mode="json") for row in rows}
        response["design"]["feature_log"] = [new_rows.get(row["id"], row)
            for row in response["design"]["feature_log"]]
    meta = protein_asset_meta(asset)
    times["response"] = (perf_counter() - started) * 1000
    return PreparedImport(current, tuple(rows), asset, validation, times, response, meta)


def _store_library_asset_locked(asset):
    """Publish the cache entry only while the import host owns state._lock."""
    state._require_compatibility_write("protein_import_library")
    state._protein_library[asset.id] = asset


def publish_import(captured, prepared):
    """One undo/revision/library transaction; never reparse under the lock."""
    with state._lock:
        state._require_compatibility_write("protein_import_publication")
        session = state._sessions.get(doc_context.get_current_doc())
        if (session is not captured.session or doc_context.get_current_doc() != captured.doc_id
                or session.design is not captured.source or session.revision != captured.revision):
            raise HTTPException(409, detail="Design changed while this import was being prepared.")
        _duplicate(session.design, captured.operation_id, captured.identities["import"])
        source = captured.source if captured.source is not None else captured.initial
        candidate = preserve_document_state(source, prepared.candidate).copy_with(
            feature_log=[*source.feature_log, *prepared.rows])
        # These are the same publication gates used by state.set_design. The
        # caller already owns its non-reentrant lock, so use the lock-owned
        # replacement primitive rather than re-entering that public wrapper.
        state._assert_active_loadout_editable(session.design, candidate)
        state._assert_photoproduct_dependencies(candidate)
        from backend.api.part_replacement_transaction import publish_replacement

        history, redo = list(session.history), list(session.redo)
        request_revision = doc_context.current_request_revision()
        request_entry = doc_context.current_request_feature_log_entry_id()
        asset_id = prepared.asset.id
        prior_library = state._protein_library.get(asset_id)
        try:
            if captured.source is None:
                session.design = captured.initial
            revision = publish_replacement(session, candidate)
            _store_library_asset_locked(prepared.asset)
            doc_context.set_request_feature_log_entry_id(prepared.rows[-1].id)
        except BaseException:
            session.design = captured.source
            session.history.clear()
            session.history.extend(history)
            session.redo.clear()
            session.redo.extend(redo)
            session.revision = captured.revision
            doc_context.set_request_revision(request_revision)
            doc_context.set_request_feature_log_entry_id(request_entry)
            if prior_library is None:
                state._protein_library.pop(asset_id, None)
            else:
                state._protein_library[asset_id] = prior_library
            raise
    return candidate, prepared.validation, revision


def import_error(error):
    if isinstance(error, CommandContractError):
        return HTTPException(413 if error.code == "source_limit" else 422,
                             detail={"status": error.status, **error.as_issue()})
    if isinstance(error, (CaptureLimit, ProofBudgetExceeded)):
        return HTTPException(413, detail={"status": "unverified", "code": "protein_import_limit", "detail": str(error)})
    return HTTPException(422, detail={"code": "invalid_protein_input", "detail": str(error)})
