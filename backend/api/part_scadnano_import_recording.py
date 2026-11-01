"""Choose replayable ordinary scadnano imports before native construction."""

from backend.core.part_input_sources import SourceContractError, describe
from backend.core.part_scadnano_source import MAX_SOURCE_BYTES, parse_source


def prepare_ordinary(content, name):
    """Return a private complete import, or a pre-build scope exclusion.

    The ordinary upload still accepts larger/unsupported source classes using
    its existing converter. Once native preparation starts, errors never retry
    that converter or publish a partial document.
    """
    if len(content) > MAX_SOURCE_BYTES:
        return None, "source exceeds the 100 KB editable-import allowance"
    raw = content.encode("utf-8")
    descriptor = describe(raw, format="scadnano", media_type="application/json")
    try:
        parse_source(raw, descriptor)
    except SourceContractError as error:
        return None, str(error)
    from backend.api.routes_part_cadnano_import import _prepare
    from backend.core.part_history_proof import ProofBudgetExceeded
    from fastapi import HTTPException
    try:
        return _prepare(raw, name or None, kind="scadnano-import"), None
    except ProofBudgetExceeded as error:
        raise HTTPException(413, detail={"status": "unverified", "code": "command_limit",
                                        "detail": str(error)}) from error
