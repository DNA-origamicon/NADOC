"""Shared document measurements; neither geometry nor topology is modified."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from backend.api import state, assembly_state
from backend.core.dimensions import DimensionChanges, merge_dimensions

router = APIRouter()


def source(kind):
    return assembly_state if kind == 'assembly' else state


def apply_changes(kind, changes):
    def update(document):
        if document.id != changes.document_id:
            raise HTTPException(409, 'Measurement document is no longer active.')
        try:
            document.dimensions = merge_dimensions(document.dimensions, changes)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    document, revision = source(kind).mutate_display_metadata(update)
    return {'document_id': document.id, 'dimensions': [d.model_dump(mode='json') for d in document.dimensions], 'revision': revision}


@router.get('/{kind}/dimensions')
def get_dimensions(kind: Literal['design', 'assembly'], document_id: str):
    module = source(kind)
    document = module.get_or_404()
    if document.id != document_id:
        raise HTTPException(409, 'Measurement document is no longer active.')
    return {'document_id': document.id, 'dimensions': [d.model_dump(mode='json') for d in document.dimensions], 'revision': module.revision()}


@router.patch('/{kind}/dimensions')
def change_dimensions(kind: Literal['design', 'assembly'], body: DimensionChanges):
    return apply_changes(kind, body)
