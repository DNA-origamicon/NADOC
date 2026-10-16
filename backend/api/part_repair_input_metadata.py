"""On-demand input editors for reviewed repair definitions, never replay proof.

Capture one bounded definition under the document lock. Schema inspection runs
outside it; neither phase reads geometry, source bytes, recovery or solver state.
The repair planner remains the authority for every submitted old/new input.
"""

from time import monotonic

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.api.part_proof_commands import PROOF_MINOR_KINDS
from backend.core.part_command_errors import CommandContractError
from backend.core.models import ClusterCreateLogEntry, DeformationLogEntry
from backend.core.part_repair_capture import _Copier
from backend.core.part_repair_inputs import RepairIdentity
from backend.core.part_repair_expectations import encode_expected_old
from backend.core.part_verification_capture import CaptureLimit


class RepairInputSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_design_id: RepairIdentity
    expected_revision: StrictInt = Field(ge=0)
    feature_id: RepairIdentity
    child_id: RepairIdentity | None = None


def _error(code, detail, status=422):
    raise HTTPException(status, detail={"code": code, "detail": detail})


def _capture(source, selection):
    """Bound identity scanning before cloning only the selected input JSON."""
    deadline = monotonic() + 0.025
    if len(source.feature_log) > 2000:
        raise CaptureLimit("Repair input inspection exceeds the history row allowance")
    seen, count, selected = set(), 0, None
    for entry in source.feature_log:
        children = entry.children if entry.feature_type == "routing-cluster" else ()
        count += 1 + len(children)
        if count > 2000:
            raise CaptureLimit("Repair input inspection exceeds the history row allowance")
        for item in (entry, *children):
            if monotonic() > deadline:
                raise CaptureLimit("Repair input inspection exceeds its capture deadline")
            if type(item.id) is not str or not 1 <= len(item.id) <= 256:
                _error("invalid_feature_identity", "Feature identities must be bounded strings")
            if item.id in seen:
                _error("ambiguous_feature_identity", "Feature and child identities must be unique")
            seen.add(item.id)
        if entry.id != selection.feature_id:
            continue
        if selection.child_id is None:
            if entry.feature_type != "snapshot" and type(entry) not in {ClusterCreateLogEntry, DeformationLogEntry}:
                _error("unsupported_repair_target", "Select a snapshot, explicit routing child, or grouping upgrade")
            selected = entry
        else:
            if entry.feature_type != "routing-cluster":
                _error("invalid_repair_target", "Child input inspection requires its containing group")
            selected = next((child for child in children if child.id == selection.child_id), None)
    if selected is None:
        _error("missing_feature", "The selected feature or child no longer exists", 404)
    copier = _Copier(10_000, 256_000, max(0, deadline - monotonic()))
    if selection.child_id is None and type(selected) is ClusterCreateLogEntry:
        # Preserve the complete typed definition; recognition, serialization
        # and its exact expectation digest belong outside the source lock.
        return "cluster_create", copier.clone(selected)
    if selection.child_id is None and type(selected) is DeformationLogEntry:
        return "deformation", copier.clone(selected)
    kind = getattr(selected, "op_kind", None) or getattr(selected, "op_subtype", None)
    if selection.child_id is not None:
        if kind not in PROOF_MINOR_KINDS:
            _error("unsupported_repair_target", "This routing child has no reviewed minor-command repair contract")
    return copier.clone(kind), copier.clone(selected.params)


def describe_inputs(kind, params):
    """Reviewed field adapters; command-kind membership alone grants nothing."""
    from backend.api.part_proof_commands import dependencies
    from backend.api.part_repair_contracts import recognize_gold_inputs
    from backend.api.part_repair_selection import reference_slot
    from backend.api.part_repair_source_policy import admit_descriptor
    from backend.core.part_input_sources import command_source_bindings

    result = {"definition_supported": False, "inputs_valid": None, "reason": None,
              "fields": [], "upgrades": []}

    def unsupported(code, detail):
        result.update(reason={"code": code, "detail": detail}, fields=[])
        return result

    if kind == "cluster_create":
        from backend.core.part_group_repair import upgrade_action

        try:
            action = upgrade_action(params)
        except CommandContractError as error:
            return unsupported(error.code, str(error)[:512])
        return {**result, "definition_supported": True, "inputs_valid": True,
                "upgrades": [{"label": "Preserve empty group owners (v2)", "action": action}]}

    if kind == "deformation":
        from backend.core.part_deformation_repair import require_named_entry
        from backend.core.part_overlay_commands import command_input

        try:
            require_named_entry(params)
            params = command_input(params)[1]
        except CommandContractError as error:
            return unsupported(error.code, str(error)[:512])

    if type(params) is not dict or "_generated_scope" in params:
        return unsupported("unsupported_repair_inputs", "Generated scopes require a separate input editor")
    values = {key: value for key, value in params.items() if key != "_generator"}
    try:
        executable = dependencies(kind, values).known
        recognition = None if executable else recognize_gold_inputs(kind, values)
        if not executable and recognition is None:
            return unsupported("missing_proof_contract", "This definition has no recognized native input contract")
        result["inputs_valid"] = executable
        if not executable:
            result["reason"] = {"code": "invalid_editable_inputs",
                "detail": "The native feature is recognized, but its diameter or pose must be corrected before regeneration."}
        fields = result["fields"]

        def add(name, label, input_type, **constraints):
            if name in values:
                fields.append({"parameter_path": [name], "expected_old": values[name],
                               "expected_old_json": encode_expected_old(values[name]),
                               "label": label, "input_type": input_type, **constraints})

        def reference(path, label):
            slot = reference_slot(kind, values, path)
            old = values
            for token in path:
                old = old[token]
            fields.append({"parameter_path": path, "expected_old": old, "label": label,
                           "expected_old_json": encode_expected_old(old),
                           "input_type": "reference", "reference_selection": {
                               "resource_kind": slot.resource_kind, "max_candidates": 100}})

        if kind == "deformation":
            for index in range(len(values["targets"])):
                reference(["targets", index, "id"], f"Organizational group {index + 1}")
        elif kind in {"nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"} and not {
                "coating_version", "thiol_version"}.intersection(values):
            from backend.api.part_nanoparticle_commands import parse_command
            if executable:
                parse_command(kind, values)
            if executable and kind != "nanoparticle-create":
                reference(["nanoparticle_id"], "Particle")
            add("diameter_nm", "Diameter (nm)", "number", exclusive_minimum=0, maximum=1000,
                nullable=kind == "nanoparticle-patch")
            add("pose", "Pose matrix", "number_list", length=16, nullable=True)
            add("catalog_id", "Catalog identity", "string", min_length=1, max_length=256)
        elif kind in {"protein-import", "protein-attach", "protein-attach-patch", "protein-attach-delete"}:
            from backend.api.part_protein_commands import parse_command
            if "conjugation_version" in values:
                return unsupported("unsupported_repair_inputs", "Owned conjugates require a separate input editor")
            command = parse_command(kind, values)
            if kind == "protein-import":
                add("name", "Protein name", "string", max_length=1024)
                add("source_filename", "Source filename", "string", max_length=1024)
                add("exclude_dna", "Exclude DNA records", "boolean")
            elif kind == "protein-attach":
                if command.target.kind != "free":
                    return unsupported("unsupported_repair_inputs", "Owned attachment targets require a separate input editor")
                reference(["asset_id"], "Protein asset")
            else:
                reference(["attachment_id"], "Protein placement")
            nullable = kind == "protein-attach-patch"
            add("conjugation_atom_serial", "Attachment atom serial", "integer", minimum=1, nullable=nullable)
            add("handle_complement_bp", "Handle complement (bp)", "integer", minimum=0, maximum=50_000, nullable=nullable)
            add("handle_spacer_nt", "Handle spacer (nt)", "integer", minimum=0, maximum=50_000, nullable=nullable)
            add("pose", "Pose matrix", "number_list", length=16, nullable=True)
            add("visible", "Visible", "boolean", nullable=nullable)
        elif kind == "element-paste":
            from backend.api.part_element_copy_commands import parse_command
            parse_command(kind, values)
            for name, label in (("protein_ids", "Protein"), ("nanoparticle_ids", "Particle")):
                for index in range(len(values[name])):
                    reference([name, index], f"{label} {index + 1}")
            add("paste_index", "Copy spacing index", "integer", minimum=1, maximum=10_000)
        # Additional source-owning families expose only their reviewed named
        # upload binding. They do not gain arbitrary parameter editing.
        for parameter, source in command_source_bindings(kind, values):
            source_policy = admit_descriptor(kind, values, parameter, source)
            fields.append({"parameter_path": [parameter], "expected_old": values[parameter],
                "expected_old_json": encode_expected_old(values[parameter]),
                "label": parameter.replace("_", " ").capitalize(), "input_type": "source",
                "source_binding": {"parameter": parameter, "source": source.model_dump(mode="json"),
                    **source_policy, "operation": "restore_published", "inspection_required": True}})
    except (ValueError, KeyError, TypeError, CommandContractError) as error:
        return unsupported("unsupported_repair_inputs", str(error)[:512])
    if not fields:
        return unsupported("unsupported_repair_inputs", "This definition needs a reviewed input editor")
    result["definition_supported"] = True
    return result


def inspect_inputs(selection):
    from backend.api import state
    from backend.api.doc_context import get_current_doc

    selection = RepairInputSelection.model_validate(selection)
    try:
        with state._lock:
            session = state._sessions.get(get_current_doc())
            source = None if session is None else session.design
            if source is None:
                _error("missing_design", "No active design", 404)
            if (source.id, session.revision) != (selection.expected_design_id, selection.expected_revision):
                _error("repair_input_conflict", "The part or revision changed before input inspection", 409)
            if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
                _error("repair_input_conflict", "Return to the complete current recipe before inspecting repair inputs", 409)
            kind, params = _capture(source, selection)
        return {"version": 1, "design_id": selection.expected_design_id,
                "revision": selection.expected_revision, "feature_id": selection.feature_id,
                "child_id": selection.child_id, "kind": kind, "assessment": "inputs_only",
                "references_checked": False, **describe_inputs(kind, params)}
    except CaptureLimit as error:
        _error("repair_input_capture_limit", str(error), 413)
    except ValueError as error:
        _error("invalid_repair_inputs", str(error))
