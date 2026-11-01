"""Transfer a library's original input through the existing import publisher."""

from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException

from backend.api import part_protein_import_recording as recording, state
from backend.api.part_protein_library_sources import original_input
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import ProofBudgetExceeded
from backend.core.part_verification_capture import CaptureLimit


def place_library_asset(body, *, kind, operation_id=None):
    from backend.api.routes_design_interchange import NATIVE_FREE_IMPORT_ENABLED

    design = state.get_or_404()
    if not NATIVE_FREE_IMPORT_ENABLED or any(asset.id == body.asset_id for asset in design.protein_assets):
        return None
    started = perf_counter()
    operation_id = operation_id or str(uuid4())
    asset = state.get_protein_asset(body.asset_id)
    if asset is None:
        raise HTTPException(404, detail=f"Protein asset {body.asset_id} not found.")
    if not any(overhang.id == body.overhang_id for overhang in design.overhangs):
        raise HTTPException(404, detail=f"Overhang {body.overhang_id} not found.")
    source_id = getattr(body, "source_attachment_id", None)
    if source_id is not None:
        selected = next((a for a in design.protein_attachments if a.id == source_id), None)
        if selected is None:
            raise HTTPException(404, detail="Source protein attachment not found.")
        if selected.asset_id != asset.id:
            raise HTTPException(400, detail="Source protein attachment does not reference this asset.")
        if selected.target.kind != "free":
            raise HTTPException(409, detail="Only a free protein placement can be converted.")
    stages = {}

    def metrics(outcome):
        return {"schema_version": 1, "operation_id": operation_id, "outcome": outcome,
            "total_ms": round((perf_counter() - started) * 1000, 3),
            "stages_ms": {key: round(value, 3) for key, value in stages.items()}}

    try:
        source = original_input(asset)
        if source is None:
            if design.recipe_root is None:
                return None
            raise HTTPException(422, detail="This library protein has no original PDB input; import its source again.")
        command, raw = source
        if kind == "protein-attach":
            params = {"target": {"kind": "overhang", "overhang_id": body.overhang_id,
                "attach_end": body.attach_end}, "handle_complement_bp": body.handle_complement_bp,
                "handle_spacer_nt": body.handle_spacer_nt, "conjugation_atom_serial": body.conjugation_atom_serial}
        else:
            params = {"overhang_id": body.overhang_id, "azide_end": body.azide_end,
                "source_attachment_id": body.source_attachment_id,
                "conjugation_atom_serial": body.conjugation_atom_serial}
        captured, reason = recording.capture_import(raw.decode("utf-8"), command.name, command.exclude_dna,
            operation_id, getattr(body, "expected_revision", None),
            source_filename=command.source_filename, asset_id=asset.id,
            placement={"kind": kind, "params": params}, publish_library=False)
        if captured is None:
            raise HTTPException(413, detail={"code": "protein_import_capture_limit", "detail": reason,
                                            "status": "unverified"})
        stages["resolve_inputs"] = (perf_counter() - started) * 1000
        stage_started = perf_counter()
        try:
            prepared = recording.prepare_import(captured)
        finally:
            stages["native_preparation"] = (perf_counter() - stage_started) * 1000
        stage_started = perf_counter()
        _, _, revision = recording.publish_import(captured, prepared)
        stages["commit"] = (perf_counter() - stage_started) * 1000
    except (CommandContractError, ProofBudgetExceeded, CaptureLimit, ValueError) as error:
        response = recording.import_error(error)
        if kind == "protein-conjugate" and isinstance(response.detail, dict):
            from backend.core.protein_metrics import record_protein_process
            process = metrics("rejected_invalid")
            record_protein_process("conjugation", process)
            response.detail.update(operation_id=operation_id, process_metrics=process)
        raise response from error
    response = prepared.response
    response.update(revision=revision, attachment_id=response.get("attachment_id", captured.identities["attachment"]),
        recipe_recording={"status": "native_suffix", "whole_design_verified": False,
            "feature_ids": [row.id for row in prepared.rows]})
    if kind == "protein-conjugate":
        from backend.core.protein_metrics import record_protein_process
        response["process_metrics"] = metrics("committed")
        record_protein_process("conjugation", response["process_metrics"])
    return response
