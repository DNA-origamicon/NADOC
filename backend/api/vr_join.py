"""Bounded Join hints and checked bridges for the native render companion."""
import os
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class JoinSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    a: tuple[float, float, float]
    b: tuple[float, float, float]


class JoinSite(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    moving: bool
    position: tuple[float, float, float]
    normal: tuple[float, float, float]


class JoinFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sequence: int = Field(ge=1, le=2**53 - 1)
    tool_sequence: int = Field(ge=0, le=2**53 - 1)
    request_sequence: int = Field(ge=0, le=2**53 - 1)
    status: Literal["ready", "checking", "valid", "invalid", "applying", "applied", "cancelled", "failed"]
    valid: bool = False
    connection_count: int = Field(default=0, ge=0, le=1000000)
    message: str = Field(default="", max_length=512)
    bridges: list[JoinSegment] = Field(default_factory=list, max_length=128)
    sites: list[JoinSite] = Field(default_factory=list, max_length=8192)


def record(body: JoinFeedback, rotation):
    rotation = np.asarray(rotation, dtype=float)
    if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
        raise HTTPException(422, detail="Invalid VR view rotation")
    # The native stroke font/status decoder accepts printable ASCII only.
    message = body.message.replace("…", "...").replace("·", "/").replace("−", "-")
    message = "".join(char if 32 <= ord(char) < 127 else " " for char in message)
    message = quote(message[:512], safe="") or "-"
    lines = [f"NADOC_JOIN_1 {body.sequence} {body.tool_sequence} {body.request_sequence} "
             f"{body.status} {int(body.valid)} {body.connection_count} "
             f"{len(body.bridges)} {len(body.sites)} {message}"]

    def rows(vectors):
        result = np.asarray(vectors, dtype=float).reshape((-1, 3)) @ rotation.T
        if not np.isfinite(result).all() or np.max(np.abs(result), initial=0) > 1e9:
            raise HTTPException(422, detail="Invalid VR Join geometry")
        return result.reshape((-1, 6))

    def values(row):
        return " ".join(f"{value:.17g}" for value in row)

    for row in rows([(bridge.a, bridge.b) for bridge in body.bridges]):
        lines.append(values(row))
    for site, row in zip(body.sites, rows([(site.position, site.normal) for site in body.sites])):
        lines.append(f"{int(site.moving)} " + values(row))
    return "\n".join(lines) + "\n"


@router.post("/vr/join-feedback")
def publish(body: JoinFeedback, request: Request):
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc

    vr._require_local(request)
    with vr._FEEDBACK_LOCK:
        state = vr._read_state()
        if not state or state.get("doc_id") != get_current_doc():
            raise HTTPException(409, detail="Native VR is unavailable or belongs to another document")
        path = Path(state["event_path"] + ".join")
        try:
            current = int(path.read_text().split(" ", 2)[1])
        except (OSError, ValueError, IndexError):
            current = 0
        if body.sequence <= current:
            return {"published": False, "current_sequence": current}
        data = record(body, state.get("view_rotation"))
        temporary = path.with_name(path.name + ".next")
        temporary.write_text(data)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    return {"published": True, "current_sequence": body.sequence}
