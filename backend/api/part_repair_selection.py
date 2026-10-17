"""Nonpublishing, typed replacement candidates from a freshly replayed prefix.

The initial catalog admits only reviewed direct-ID slots. Diagnostic references
are not a schema: implicit atoms, domains, closed scopes and compound selectors
require separate adapters. Candidate eligibility is not whole-command validity.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import command_input


MAX_CANDIDATES = 100
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_Token = _Id | Annotated[StrictInt, Field(ge=0)]


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selection_version: StrictInt = Field(ge=1, le=1)
    expected_design_id: _Id
    expected_revision: StrictInt = Field(ge=0)
    feature_id: _Id
    child_id: _Id | None = None
    parameter_path: list[_Token] = Field(min_length=1, max_length=16)
    expected_old: _Id
    limit: StrictInt = Field(default=MAX_CANDIDATES, ge=1, le=MAX_CANDIDATES)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value


class SelectionInputError(CommandContractError):
    status = "failed"


@dataclass(frozen=True)
class ReferenceSlot:
    resource_kind: str
    collection: str
    family: str


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_reference_slot")


def _versions(values, *names):
    if any(type(values.get(name)) is not int or values[name] != 1 for name in ("_proof_version", *names)):
        _unsupported("This reference slot requires its reviewed version 1 command contract")


def reference_slot(kind, params, path):
    """An explicit command-input catalog; no field-name or error-text inference."""
    if "_generated_scope" in params:
        _unsupported("Generated local scopes need a separate selection adapter")
    values = {key: value for key, value in params.items() if key != "_generator"}
    if kind == "overhang-bulk":
        from backend.api.part_connection_repair_selection import reference_slot as connection_slot
        slot = connection_slot(values, path)
        if slot is not None:
            return slot
    if kind == "deformation":
        from backend.core.part_deformation_repair import operation_from_params, reference_index

        try:
            reference_index(operation_from_params(values), path)
        except CommandContractError as error:
            _unsupported(str(error))
        return ReferenceSlot("part_group", "group_organization", "named_group")
    if kind in {"nanoparticle-patch", "nanoparticle-delete"} and path == ["nanoparticle_id"]:
        if "coating_version" in values or "thiol_version" in values:
            _unsupported("Coating and thiol ownership are outside this selection contract")
        _versions(values, "quantum_dot_version" if "quantum_dot_version" in values else "nanoparticle_version")
        from backend.api.part_nanoparticle_commands import parse_command
        parse_command(kind, values)
        return ReferenceSlot("nanoparticle", "nanoparticles", "quantum_dot" if "quantum_dot_version" in values else "gold")
    if kind == "protein-attach" and path == ["asset_id"]:
        _versions(values, "protein_version")
        from backend.api.part_protein_commands import parse_command
        command = parse_command(kind, values)
        if command.target.kind != "free":
            _unsupported("Only free protein asset selection is supported")
        return ReferenceSlot("protein_asset", "protein_assets", "free_asset")
    if kind in {"protein-attach-patch", "protein-attach-delete"} and path == ["attachment_id"]:
        if "conjugation_version" in values:
            _unsupported("Owned conjugates need a separate selection adapter")
        _versions(values, "protein_version")
        from backend.api.part_protein_commands import parse_command
        parse_command(kind, values)
        return ReferenceSlot("protein_attachment", "protein_attachments", "free_attachment")
    if kind == "element-paste" and len(path) == 2 and type(path[1]) is int:
        _versions(values, "copy_version")
        from backend.api.part_element_copy_commands import parse_command
        parse_command(kind, values)
        if path[0] == "protein_ids":
            return ReferenceSlot("protein_attachment", "protein_attachments", "copy_protein")
        if path[0] == "nanoparticle_ids":
            return ReferenceSlot("nanoparticle", "nanoparticles", "copy_particle")
    _unsupported("This input is unknown, protected, or requires a compound reference adapter")


def resolve_prefix(source, feature_id, child_id):
    """Return target and exact preceding log, retaining valid child boundaries."""
    identities = [entry.id for entry in source.feature_log]
    identities.extend(child.id for entry in source.feature_log if entry.feature_type == "routing-cluster"
                      for child in entry.children)
    if len(identities) != len(set(identities)):
        raise SelectionInputError("Feature and routing-child identities are ambiguous", code="ambiguous_feature_identity")
    for index, entry in enumerate(source.feature_log):
        if entry.id != feature_id:
            continue
        prefix = list(source.feature_log[:index])
        if child_id is None:
            if entry.feature_type != "snapshot":
                from backend.core.part_deformation_repair import require_named_entry

                try:
                    require_named_entry(entry)
                except CommandContractError as error:
                    _unsupported(str(error))
            return entry, prefix
        if entry.feature_type != "routing-cluster":
            raise SelectionInputError("A child selection needs its containing routing group", code="invalid_selection_target")
        for child_index, child in enumerate(entry.children):
            if child.id == child_id:
                if child_index:
                    prefix.append(entry.model_copy(update={"children": list(entry.children[:child_index])}))
                return child, prefix
        raise SelectionInputError("Routing child no longer exists in this group", code="missing_feature")
    raise SelectionInputError("Selection target feature no longer exists", code="missing_feature")


def _old_value(params, path):
    current = params
    for token in path:
        if type(current) is dict and type(token) is str and token in current:
            current = current[token]
        elif type(current) is list and type(token) is int and token < len(current):
            current = current[token]
        else:
            raise SelectionInputError("The reference path no longer identifies an input", code="invalid_parameter_path")
    return current


def _candidates(design, slot, kind, params, request, checkpoint):
    if slot.resource_kind == "part_group":
        from backend.core.part_deformation_repair import group_candidates

        return group_candidates(design, params, request, checkpoint)
    if slot.family in {"connection_endpoint", "connection_version"}:
        from backend.api.part_connection_repair_selection import candidates
        return candidates(design, slot, params, request, checkpoint)
    records = getattr(design, slot.collection)
    seen = set()
    for record in records:
        if record.id in seen:
            raise ReferenceResolutionError("Replacement identities are ambiguous in the rebuilt prefix", code="invalid_selection",
                references=[{"kind": slot.resource_kind, "identity": record.id, "parameter_path": request.parameter_path}])
        seen.add(record.id)
    owners = set()
    if slot.resource_kind == "nanoparticle":
        owners = {item.nanoparticle_id for item in design.nanoparticle_conjugations}
        owners.update(item.nanoparticle_id for item in design.nanoparticle_connection_versions)
    assets = {}
    if slot.resource_kind == "protein_attachment" and kind != "protein-attach-delete":
        for asset in design.protein_assets:
            assets.setdefault(asset.id, []).append(asset)
    excluded = set()
    if kind == "element-paste":
        key, index = request.parameter_path
        excluded.update(identity for i, identity in enumerate(params[key]) if i != index)
        excluded.update(params[key.replace("_ids", "_output_ids")])
    from backend.api.part_protein_commands import MAX_PROTEIN_ATOM_RECORDS, MAX_PROTEIN_BONDS
    serial_counts = {}

    def atom_available(asset, serial):
        if serial is None or not asset.atoms:
            return False
        if asset.id not in serial_counts:
            counts = {}
            for atom in asset.atoms:
                counts[atom.serial] = counts.get(atom.serial, 0) + 1
            serial_counts[asset.id] = counts
        return serial_counts[asset.id].get(serial, 0) == 1

    def eligible(record):
        if slot.resource_kind == "nanoparticle":
            if record.coating is not None or record.biotin_dna or record.id in owners:
                return False
            gold = record.kind == "gold_nanosphere" and record.quantum_dot is None
            dot = record.kind == "quantum_dot" and record.quantum_dot is not None
            return gold if slot.family == "gold" else dot if slot.family == "quantum_dot" else gold or dot
        if slot.resource_kind == "protein_asset":
            return atom_available(record, params["conjugation_atom_serial"])
        if record.target.kind != "free" or record.binder_strand_id or record.azide_end:
            return False
        if kind == "protein-attach-delete":
            return True
        matches = assets.get(record.asset_id, [])
        if len(matches) != 1:
            return False
        asset = matches[0]
        if slot.family == "copy_protein" and (len(asset.atoms) > MAX_PROTEIN_ATOM_RECORDS or len(asset.bonds) > MAX_PROTEIN_BONDS):
            return False
        serial = params.get("conjugation_atom_serial")
        return atom_available(asset, serial if serial is not None else record.conjugation_atom_serial)

    candidates, count = [], 0
    for record in records:
        checkpoint()
        if type(record.id) is not str or not 1 <= len(record.id) <= 256 or record.id in excluded or not eligible(record):
            continue
        count += 1
        if len(candidates) < request.limit:
            label = getattr(record, "name", None) or getattr(record, "label", None) or record.id
            candidates.append({"kind": slot.resource_kind, "identity": record.id,
                               "label": label[:256] if isinstance(label, str) else record.id})
    return candidates, count


class _PrefixStopped(Exception):
    def __init__(self, status, issue):
        self.status, self.issue = status, issue


def prepare_selection(source, request, *, source_revision, executor, dependency_resolver, checkpoint=lambda: None):
    """Return bounded preview descriptors, never a publishable Design.

    Recovery encoding is intentionally reused with regenerate for this first
    increment. Its measured overhead can later justify a shared nonrecording
    replay visitor; selection never raises the existing worker/recovery limits.
    """
    from backend.api.part_recipe_edit import regenerate

    request = SelectionRequest.model_validate(request)
    rows, completed, slot = [], [], None
    phase = "admission"

    def result(status, issues, **extra):
        failed = issues[0].get("feature_id") if issues else None
        return {"status": status, "issues": issues, "native_editable": False, "selection": {
            "selection_supported": slot is not None, "source_design_id": source.id, "source_revision": source_revision,
            "target": {"feature_id": request.feature_id, "child_id": request.child_id, "parameter_path": request.parameter_path},
            "phase": phase, "scope": "immediately_before_target", "prefix_only": True,
            "whole_command_validated": False, "whole_recipe_validated": False,
            "completed_prefix": list(completed), "not_evaluated": [identity for identity, _, _ in rows[len(completed):] if identity != failed],
            "candidates": [], **extra}}

    try:
        checkpoint()
        if type(source_revision) is not int or request.expected_revision != source_revision or request.expected_design_id != source.id:
            raise SelectionInputError("Selection belongs to a different part or captured revision", code="selection_conflict")
        if source.recipe_root is None or source.recipe_root.version != 1:
            raise CommandContractError("Selection requires a supported explicit root", code="missing_or_unsupported_recipe_root")
        if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
            raise CommandContractError("Selection requires the complete recipe", code="historical_cursor")
        if set(type(source).model_fields) - FIELD_ROLES.keys():
            raise CommandContractError("Design fields lack proof ownership", code="unclassified_fields")
        rows = list(command_rows(source, 2000))
        target, log = resolve_prefix(source, request.feature_id, request.child_id)
        kind, params = command_input(target)
        slot = reference_slot(kind, params, request.parameter_path)
        if not dependency_resolver(kind, params).known:
            slot = None
            raise CommandContractError("Target has no supported native command schema", code="missing_proof_contract")
        if _old_value(params, request.parameter_path) != request.expected_old:
            raise SelectionInputError("Selected reference changed after this request was prepared", code="selection_conflict")
        prefix_rows = list(command_rows(source.copy_with(feature_log=log), 2000))
        if any(row_kind == "empty-routing-cluster" for _, row_kind, _ in prefix_rows):
            raise CommandContractError("Prefix contains an empty routing group", code="empty_routing_cluster")

        def run(row_kind, current, values):
            nonlocal phase
            phase = "replay"
            identity, expected_kind, _ = prefix_rows[len(completed)]
            if row_kind != expected_kind:
                raise RuntimeError("Selection prefix diverged from its planned command order")
            try:
                if not dependency_resolver(row_kind, values).known:
                    raise CommandContractError("Prefix has no supported native command schema", code="missing_proof_contract")
                updated = executor(row_kind, current, deepcopy(values))
            except CommandContractError as error:
                raise _PrefixStopped(error.status, {**error.as_issue(), "feature_id": identity, "kind": row_kind}) from error
            except ValueError as error:
                raise _PrefixStopped("failed", {"code": "invalid_command_inputs", "detail": str(error)[:2048],
                                                "feature_id": identity, "kind": row_kind}) from error
            except HTTPException as error:
                raise _PrefixStopped("unverified" if error.status_code in {408, 413, 429} else "failed", {
                    "code": "evaluation_rejected", "detail": error.detail, "http_status": error.status_code,
                    "feature_id": identity, "kind": row_kind}) from error
            completed.append(identity)
            phase = "recovery"
            return updated

        phase = "root"
        prefix = regenerate(source, log, checkpoint, executor=run)
        if len(completed) != len(prefix_rows):
            raise RuntimeError("Selection did not execute its complete prefix")
        phase = "selection"
        candidates, count = _candidates(prefix, slot, kind, params, request, checkpoint)
        checkpoint()
        return result("preview", [], resource_kind=slot.resource_kind, candidates=candidates,
                      eligible_count=count, limit=request.limit, truncated=count > request.limit,
                      eligibility="typed_reference_and_ownership_only")
    except _PrefixStopped as error:
        return result(error.status, [error.issue])
    except CommandContractError as error:
        return result(error.status, [error.as_issue()])
    except ProofBudgetExceeded as error:
        return result("unverified", [{"code": "command_limit", "detail": str(error)[:2048]}])
    except HTTPException as error:
        return result("unverified" if error.status_code in {408, 413, 429} else "failed", [{
            "code": "evaluation_rejected", "detail": error.detail, "http_status": error.status_code}])
    except ValueError as error:
        return result("unverified" if str(error) == "entry_limit" else "failed", [{
            "code": "entry_limit" if str(error) == "entry_limit" else "invalid_selection_inputs", "detail": str(error)[:2048]}])
