"""Bind semantic document actions to the session they actually inspected."""
from fastapi import HTTPException
from backend.api import state


def source():
    design, revision = state.get_design_with_revision()
    if design is None:
        raise HTTPException(404, detail='No active design.')
    return design, revision
