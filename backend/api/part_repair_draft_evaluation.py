"""Saved-proposal admission into the existing part evaluation job lifecycle."""

from fastapi import HTTPException

from backend.api import doc_context
from backend.core.part_command_errors import CommandContractError
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft_evaluation import compile_draft_evaluation, parse_evaluation_request
from backend.core.part_repair_fingerprint import RepairFingerprintLimit
from backend.core.part_repair_proposal import DraftInputError
from backend.core.part_verification_capture import CaptureLimit


def start_draft_evaluation(value):
    """Fingerprint privately, then recapture through the guarded ordinary host.

    No worker/catalog/candidate cache is added. Trusted source/session guards
    close the interval between fingerprinting and the existing job's capture.
    Metadata edits invalidate jobs by revision like other document mutations.
    """
    from backend.api import part_evaluation_jobs as jobs, state as host

    try:
        request = parse_evaluation_request(value)
        with host._lock:
            host._require_compatibility_write("repair_draft_evaluation")
            session = host._session()
            source, revision = session.design, session.revision
            if source is None:
                raise HTTPException(404, detail="No active design.")
            draft = source.repair_draft
            if (source.id != request.expected_design_id or revision != request.expected_revision
                    or draft is None or draft.draft_id != request.expected_draft_id
                    or draft.generation != request.expected_generation):
                raise DraftInputError("The part, revision or saved proposal changed", code="draft_conflict")
            host._assert_active_loadout_editable(source)
            captured = capture_draft_inputs(source, source_revision=revision, draft=draft)
            session_identity, doc_id = session.identity, doc_context.get_current_doc()
        repair = compile_draft_evaluation(captured, request)
        if doc_context.get_current_doc() != doc_id:
            raise DraftInputError("The active document changed before evaluation", code="draft_conflict")
        result = jobs.start({"operation": "repair", "expected_revision": revision,
            "repair": repair.model_dump(mode="json")},
            expected_source=source, expected_session_identity=session_identity)
        return {**result, "repair_draft": {"draft_id": request.expected_draft_id,
                                          "generation": request.expected_generation}}
    except (CaptureLimit, RepairFingerprintLimit) as error:
        raise HTTPException(413, detail={"code": "draft_capture_limit", "detail": str(error)}) from error
    except CommandContractError as error:
        conflict = error.code in {"draft_conflict", "draft_rebase_required", "repair_conflict", "source_changed"}
        raise HTTPException(409 if conflict else 422, detail=error.as_issue()) from error
    except ValueError as error:
        raise HTTPException(422, detail={"code": "invalid_draft_evaluation", "detail": str(error)}) from error
