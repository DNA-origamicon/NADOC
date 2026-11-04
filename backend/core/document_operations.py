"""Record and independently replay document intent without autosave noise.

The journal is document-owned, while construction logs remain branch-owned.
Legacy wrappers are not retroactively assigned an initialization operation.
"""
from copy import deepcopy
import hashlib
import json

from backend.core.document_operation_model import DocumentOperation

METADATA_FIELDS = frozenset({'name', 'description', 'author', 'tags'})


def branch_value(design):
    from backend.core.part_history_contract import FIELD_ROLES
    excluded = {name for name, role in FIELD_ROLES.items()
                if role in {'history', 'presentation', 'document_identity', 'repair_draft'}}
    excluded.update({'loadouts', 'active_loadout_id', 'last_editable_loadout_id'})
    value = design.model_dump(mode='json', exclude=excluded)
    for key in ('identity_last_known_path', 'identity_confirmed_at'):
        value['metadata'].pop(key, None)
    return value


def content_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def recipe_inputs(design):
    from backend.core.part_history_proof import command_rows
    return {'state_sha256': content_digest(branch_value(design)),
            'root': design.recipe_root.model_dump(mode='json') if design.recipe_root else None,
            'input_sources': {key: value.model_dump(mode='json') for key, value in design.input_sources.items()},
            'commands': [{'id': identity, 'kind': kind, 'params': deepcopy(params)}
                         for identity, kind, params in command_rows(design, 2000)]}


def record(before, after, kind, params):
    """Called only by the actual operation, before its atomic publication."""
    if (kind == 'loadout-select' and before.active_loadout_id == after.active_loadout_id
            and before.last_editable_loadout_id == after.last_editable_loadout_id
            and branch_value(before) == branch_value(after)):
        return after.model_copy(update={'document_history': before.document_history})
    if len(before.document_history) >= 2000:
        raise ValueError('Document operation allowance exceeded')
    entry = DocumentOperation(kind=kind, params=deepcopy(params),
                              source_loadout_id=before.active_loadout_id,
                              source_recipe=recipe_inputs(before))
    return after.model_copy(update={'document_history': [*before.document_history, entry]})


def initialize(design, *, identity, name):
    from backend.core.design_loadouts import encode_snapshot
    from backend.core.models import DesignLoadout
    if design.loadouts:
        return design
    payload, size = encode_snapshot(design)
    updated = design.model_copy(update={'loadouts': [DesignLoadout(id=identity, name=name,
        design_snapshot_gz_b64=payload, snapshot_size_bytes=size)], 'active_loadout_id': identity})
    return record(design, updated, 'loadout-initialize', {'id': identity, 'name': name})


def _keys(params, required):
    if set(params) != set(required):
        raise ValueError('Unknown document operation parameters')


def replay(entries):
    """Replay semantic state only; this does not certify molecular construction."""
    branches, active, last, metadata = {}, None, None, []
    for raw in entries:
        entry = DocumentOperation.model_validate(raw)
        if entry.source_loadout_id != active:
            raise ValueError('Document operation source branch does not match replay')
        p, kind = entry.params, entry.kind
        if kind in {'loadout-initialize', 'loadout-create'}:
            _keys(p, {'id', 'name'})
            if not isinstance(p['id'], str) or not p['id'] or p['id'] in branches:
                raise ValueError('Duplicate or invalid loadout identity')
            if not isinstance(p['name'], str) or not p['name'].strip():
                raise ValueError('Invalid loadout name')
            if kind == 'loadout-initialize' and branches:
                raise ValueError('Loadouts already initialized')
            if kind == 'loadout-create' and active not in branches:
                raise ValueError('Loadout creation has no source branch')
            branches[p['id']] = {'name': p['name'], 'metadata': deepcopy(metadata)}
            active = p['id']
        elif kind == 'loadout-rename':
            _keys(p, {'id', 'name'})
            if p['id'] not in branches or not isinstance(p['name'], str) or not p['name'].strip():
                raise ValueError('Invalid loadout rename')
            branches[p['id']]['name'] = p['name']
        elif kind == 'loadout-select':
            _keys(p, {'id', 'save_current', 'target_recipe', 'target_metadata'})
            if type(p['save_current']) is not bool or p['id'] not in branches:
                raise ValueError('Invalid loadout selection')
            active = last = p['id']
            metadata = deepcopy(p['target_metadata'])
            branches[active]['metadata'] = deepcopy(metadata)
        elif kind == 'loadout-delete':
            _keys(p, {'id', 'target_recipe', 'target_metadata'})
            if p['id'] not in branches or len(branches) <= 1:
                raise ValueError('Invalid loadout deletion')
            del branches[p['id']]
            if active == p['id']:
                active = next(iter(branches))
                metadata = deepcopy(p['target_metadata'])
                branches[active]['metadata'] = deepcopy(metadata)
            if last == p['id']:
                last = active
        else:
            _keys(p, {'before', 'changes'})
            if not p['changes'] or set(p['changes']) - METADATA_FIELDS or set(p['before']) != set(p['changes']):
                raise ValueError('Invalid document metadata operation')
            metadata.append(deepcopy(p))
            if active in branches:
                branches[active]['metadata'] = deepcopy(metadata)
    return {'branches': branches, 'active': active, 'last': last, 'metadata': metadata}


def apply_metadata_edits(rebuilt, edits):
    """Apply a validated sequence of cosmetic metadata commands."""
    metadata = rebuilt.metadata.model_copy(deep=True)
    for edit in edits:
        _keys(edit, {'before', 'changes'})
        if not edit['changes'] or set(edit['changes']) - METADATA_FIELDS or set(edit['before']) != set(edit['changes']):
            raise ValueError('Invalid document metadata operation')
        if any(getattr(metadata, key) != value for key, value in edit['before'].items()):
            raise ValueError('Document metadata source does not match independent replay')
        metadata = type(metadata).model_validate({**metadata.model_dump(), **edit['changes']})
    return rebuilt.model_copy(update={'metadata': metadata})


def apply_metadata(design, rebuilt):
    """Extend native replay with recorded cosmetic metadata edits only."""
    return apply_metadata_edits(rebuilt, replay(design.document_history)['metadata'])


def verify_document(design):
    """Check the wrapper against intent. Branch content still requires agent audit."""
    state = replay(design.document_history)
    expected = {item.id: item.name for item in design.loadouts}
    if len(expected) != len(design.loadouts) or expected != {key: value['name'] for key, value in state['branches'].items()}:
        raise ValueError('Unrecorded loadout creation, rename or deletion')
    if (state['active'], state['last']) != (design.active_loadout_id, design.last_editable_loadout_id):
        raise ValueError('Unrecorded loadout selection')
    return state


def selection_inputs(target_id, restored, *, save_current):
    return {'id': target_id, 'save_current': save_current,
            'target_recipe': recipe_inputs(restored),
            'target_metadata': replay(restored.document_history)['metadata']}


def deletion_inputs(identity, before, after):
    switched = before.active_loadout_id == identity
    return {'id': identity, 'target_recipe': recipe_inputs(after) if switched else None,
            'target_metadata': replay(after.document_history)['metadata'] if switched else None}
