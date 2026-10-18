"""Convert the open part's legacy history to a verified recipe (re-plan R2).

POST /design/history/convert
  {"apply": false}  -> dry-run report only; nothing changes.
  {"apply": true, "expected_revision": n}
                    -> replace the open design with the converted one as one
                       undoable step. The frontend saves it under a new file
                       name; this route never writes files.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state

router = APIRouter()


class ConvertHistoryBody(BaseModel):
    apply: bool = False
    expected_revision: int | None = None


def convert(design):
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_legacy_conversion import convert_legacy_history

    return convert_legacy_history(design, execute=execute, dependencies=dependencies,
                                  decode=state.decode_design_snapshot, assess=assess_part_history)


@router.post("/design/history/convert")
def convert_history(body: ConvertHistoryBody) -> dict:
    source, revision = state.get_design_with_revision()
    if source is None:
        raise HTTPException(404, detail="No active design.")
    if body.expected_revision is not None and body.expected_revision != revision:
        raise HTTPException(409, detail="The part changed; review the conversion again.")
    result = convert(source.model_copy(deep=True))
    summary = {**result.summary(), "rows": len(source.feature_log)}
    if not body.apply or result.status != "converted":
        return {"conversion": summary, "revision": revision}
    state.set_design(result.design, expected_revision=revision)
    from backend.api.crud import _design_response
    from backend.core.validator import validate_design

    current, current_revision = state.get_design_with_revision()
    return {**_design_response(current, validate_design(current), revision=current_revision,
                               full_feature_log=True),
            "conversion": summary}
