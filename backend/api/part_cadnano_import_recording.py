"""Record bounded ordinary caDNAno uploads through the pinned import command."""
from fastapi import HTTPException

from backend.core.part_cadnano_source import MAX_SOURCE_BYTES, parse_source
from backend.core.part_input_sources import SourceContractError, describe


def prepare_ordinary(content, *, relax_origami=False):
    """Prepare before publication; never retry a failed native construction.

    Larger/unqualified uploads retain the established legacy import path. This
    is the same qualification boundary as the explicit pinned-import endpoint.
    """
    if len(content) > MAX_SOURCE_BYTES:
        return None, "source exceeds the 100 KB editable-import allowance"
    raw = content.encode("utf-8")
    descriptor = describe(raw, format="cadnano-v2", media_type="application/json")
    try:
        parse_source(raw, descriptor)
    except SourceContractError as error:
        return None, str(error)
    from backend.api.routes_part_cadnano_import import _prepare
    from backend.api.part_import_relaxation import prepare as prepare_relaxation
    from backend.api.crud import _design_response
    from backend.core.part_history_proof import ProofBudgetExceeded
    from backend.core.validator import validate_design
    try:
        design, response = _prepare(raw, None)
        design, relaxation = prepare_relaxation(design, enabled=relax_origami)
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"status": "unverified", "code": "command_limit",
                                        "detail": str(error)}) from error
    if relaxation is not None:
        response.update(_design_response(design, validate_design(design), full_feature_log=True))
        response["relaxation"] = relaxation
        if relaxation["status"] == "skipped":
            response.setdefault("import_warnings", []).append(
                "Automatic relaxation skipped: " + relaxation["message"])
    response["import_history"] = {"status": "reproduced_import", "native_editable": False}
    return (design, response), None
