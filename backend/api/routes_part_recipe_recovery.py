"""Explicit saved-file recovery; never enters a live part publication path."""

from fastapi import APIRouter, Request

from backend.api.part_recipe_file_transport import recover_file

router = APIRouter()


@router.post("/part-recipe/recovery")
async def recover_saved_recipe(request: Request):
    return await recover_file(request)
