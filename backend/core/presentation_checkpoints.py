"""Explicit, replayable presentation states; ordinary autosaves are not commands."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.models import Annotation, ViewVolume

KINDS = frozenset({'annotations-state', 'view-volumes-state'})


class AnnotationState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    annotations: list[Annotation]
    annotations_enabled: bool = True


class VolumeState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    view_volumes: list[ViewVolume]


class SaveCheckpoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: str
    kind: Literal['annotations-state', 'view-volumes-state']
    label: str = Field(default='', max_length=200)


def values(kind, params):
    if type(params.get('_proof_version')) is not int or params['_proof_version'] != 1:
        raise ValueError('Unsupported presentation checkpoint version')
    schema = AnnotationState if kind == 'annotations-state' else VolumeState if kind == 'view-volumes-state' else None
    if schema is None:
        raise ValueError('Unknown presentation checkpoint')
    state = schema.model_validate({k: v for k, v in params.items() if k != '_proof_version'})
    entries = state.annotations if kind == 'annotations-state' else state.view_volumes
    if len({entry.id for entry in entries}) != len(entries):
        raise ValueError('Presentation state contains duplicate identifiers')
    return {name: getattr(state, name) for name in schema.model_fields}


def capture(document, kind):
    fields = AnnotationState.model_fields if kind == 'annotations-state' else VolumeState.model_fields
    return {'_proof_version': 1, **document.model_dump(mode='json', include=set(fields))}


def apply(document, kind, params):
    return document.model_copy(update=values(kind, params))


def at_position(source, candidate, position):
    """Only explicitly checkpointed channels follow history; others stay live.

    Before the first checkpoint the channel is empty. This avoids accidentally
    capturing transient autosaves in unrelated construction snapshots.
    """
    log = source.feature_log
    count = 0 if position == -2 else len(log) if position == -1 else position + 1
    selected = {}
    for index, entry in enumerate(log):
        kind = getattr(entry, 'op_kind', None)
        if kind not in KINDS or getattr(entry, 'suppressed', False):
            continue
        selected.setdefault(kind, {'_proof_version': 1, **(
            {'annotations': [], 'annotations_enabled': True} if kind == 'annotations-state' else {'view_volumes': []})})
        if index < count:
            selected[kind] = entry.params
    restored = candidate.model_copy(update={
        'annotations': source.annotations, 'annotations_enabled': source.annotations_enabled,
        'view_volumes': source.view_volumes})
    for kind, params in selected.items():
        restored = apply(restored, kind, params)
    return restored


def restore_history_channels(current, snapshot):
    """Undo ordinary edits preserves live notes; crossing a checkpoint restores it."""
    def active(document, kind):
        position = document.feature_log_cursor
        count = 0 if position == -2 else len(document.feature_log) if position == -1 else position + 1
        return [(entry.id, entry.params) for entry in document.feature_log[:count]
                if getattr(entry, 'op_kind', None) == kind and not getattr(entry, 'suppressed', False)]

    updates = {'annotations': current.annotations, 'annotations_enabled': current.annotations_enabled}
    for kind in KINDS:
        before, after = active(current, kind), active(snapshot, kind)
        if before == after:
            continue
        params = after[-1][1] if after else {'_proof_version': 1, **(
            {'annotations': [], 'annotations_enabled': True} if kind == 'annotations-state' else {'view_volumes': []})}
        updates.update(values(kind, params))
    return updates
