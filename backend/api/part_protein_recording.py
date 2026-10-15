"""Atomic live adapters for native protein feature commands.

Pure command evaluators are independent of sessions. These adapters resolve live
input defaults and publish one candidate/receipt under the document lock; routes
inject their response helpers to avoid circular imports and preserve API shape.
"""

import time
import uuid

from fastapi import HTTPException

from backend.api import state as design_state


def record_placement(kind, label, params, *, prepare=None):
    """Resolve authored defaults, evaluate and record under the document lock."""
    from backend.api.part_protein_commands import build
    from backend.core.part_command_errors import CommandContractError

    params.update(_proof_version=1, protein_version=1)

    def apply(design):
        if prepare is not None:
            prepare(design, params)
        return build(kind, design, params)

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(kind, label, params, apply)
    except CommandContractError as error:
        raise HTTPException(422, detail={"status": error.status, **error.as_issue()}) from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    return updated, report


def record_conjugate_lifecycle(kind, attachment, patch=None, *, design_response, geometry_response):
    from backend.api.part_protein_conjugate_lifecycle import evaluate
    from backend.core.part_command_errors import CommandContractError
    from backend.core.part_history_proof import ProofBudgetExceeded

    params = {
        "_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
        "attachment_id": attachment.id, "binder_strand_id": attachment.binder_strand_id,
    }
    if patch is not None:
        params.update({key: value for key, value in patch.items() if key in {"gizmo_move", "visible"}})
    effect = None

    def candidate(design):
        nonlocal effect
        updated, effect = evaluate(kind, design, params)
        return updated

    label = "Detach protein" if kind == "protein-attach-delete" else (
        "Move protein" if params.get("gizmo_move") is not None else "Edit protein attachment")
    try:
        updated, report, _entry = design_state.mutate_with_feature_log(kind, label, params, candidate)
    except CommandContractError as error:
        raise HTTPException(422, detail={"status": error.status, **error.as_issue()}) from error
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"code": "source_limit", "detail": str(error),
                                        "status": "unverified"}) from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    if effect["changed_helix_ids"]:
        response = geometry_response(updated, report,
            changed_helix_ids=effect["changed_helix_ids"], compact_deformed=True,
            **({"partial_axes": True} if kind == "protein-attach-patch" else {}))
    else:
        response = design_response(updated, report)
    if effect["protein_constraint"] is not None:
        response["protein_constraint"] = effect["protein_constraint"]
    return response


def record_conjugation(body, operation_id, started, *, strand_occupancy, local_changed_helices, geometry_response):
    from backend.api.part_protein_commands import _selected
    from backend.api.part_protein_conjugation_commands import ConjugationValidationError, evaluate
    from backend.core.part_command_errors import CommandContractError
    from backend.core.part_history_proof import ProofBudgetExceeded
    from backend.core.protein_metrics import record_protein_process

    params = {
        "_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
        "asset_id": body.asset_id, "overhang_id": body.overhang_id,
        "azide_end": body.azide_end, "source_attachment_id": body.source_attachment_id,
        "operation_id": operation_id,
        "attachment_id": body.source_attachment_id or str(uuid.uuid4()),
        "binder_strand_id": f"ohbind_{uuid.uuid4().hex}",
        "group_id": f"conjugate-{uuid.uuid4()}",
    }
    stages_ms = {}
    element_validation = None
    before_occ = None

    def metrics(outcome):
        return {
            "schema_version": 1, "operation_id": operation_id, "outcome": outcome,
            "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "stages_ms": {name: round(value, 3) for name, value in stages_ms.items()},
        }

    def candidate(design):
        nonlocal element_validation, before_occ
        stage_started = time.perf_counter()
        # Recheck under the same document lock that publishes the receipt.
        # Concurrent equal operation IDs can never each create a conjugate.
        if body.operation_id is not None and any(
            getattr(entry, "op_kind", None) == "protein-conjugate"
            and entry.params.get("operation_id") == operation_id for entry in design.feature_log
        ):
            raise HTTPException(409, detail=f"Conjugation operation {operation_id} was already committed.")
        asset = _selected(design.protein_assets, body.asset_id, "protein_asset", ["asset_id"])
        if body.source_attachment_id is not None:
            sources = [item for item in design.protein_attachments if item.id == body.source_attachment_id]
            if not sources:
                raise HTTPException(404, detail="Source protein attachment not found.")
            source = _selected(sources, body.source_attachment_id, "protein_attachment", ["source_attachment_id"])
            if source.asset_id != asset.id:
                raise HTTPException(400, detail="Source protein attachment does not reference this asset.")
            if source.target.kind != "free":
                raise HTTPException(409, detail=(
                    "Only a free protein placement can be converted. Detach an existing "
                    "conjugate before attaching it to another overhang."
                ))
        params["conjugation_atom_serial"] = (
            body.conjugation_atom_serial if body.conjugation_atom_serial is not None
            else asset.default_conjugation_atom_serial
        )
        before_occ = strand_occupancy(design)
        stages_ms["resolve_inputs"] = (time.perf_counter() - stage_started) * 1000.0
        stage_started = time.perf_counter()
        try:
            updated, element_validation = evaluate("protein-conjugate", design, params)
            return updated
        finally:
            stages_ms["native_evaluation"] = (time.perf_counter() - stage_started) * 1000.0

    transaction_started = time.perf_counter()
    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            "protein-conjugate", "Conjugate protein to overhang", params, candidate,
            expected_revision=body.expected_revision,
        )
    except ConjugationValidationError as error:
        process = metrics("rejected_invalid")
        record_protein_process("conjugation", process)
        raise HTTPException(422, detail={
            "message": "Protein conjugate failed element validation; no changes committed.",
            "operation_id": operation_id, "process_metrics": process,
            "status": error.status, **error.as_issue(),
        }) from error
    except CommandContractError as error:
        raise HTTPException(422, detail={"operation_id": operation_id,
                            "status": error.status, **error.as_issue()}) from error
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"code": "source_limit", "detail": str(error),
                            "operation_id": operation_id, "status": "unverified"}) from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    elapsed = (time.perf_counter() - transaction_started) * 1000.0
    stages_ms["commit"] = max(0.0, elapsed - sum(stages_ms.values()))
    changed = local_changed_helices(before_occ, strand_occupancy(updated))
    response = geometry_response(updated, report, changed_helix_ids=changed, compact_deformed=True)
    response.update(attachment_id=params["attachment_id"], binder_strand_id=params["binder_strand_id"],
                    element_validation=element_validation, process_metrics=metrics("committed"))
    record_protein_process("conjugation", response["process_metrics"])
    return response
