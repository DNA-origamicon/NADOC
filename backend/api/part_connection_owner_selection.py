"""Bounded creator queries for conditional native direct restoration owners.

Recipes retain namespaces, never restoration snapshots. Resolution uses only the
rebuilt prefix; ordinary recording alone consults bounded producer metadata.
"""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.feature_identity import identity_factory
from backend.core.part_saved_topology import snapshot_for

MAX_PRODUCERS = 2000


class OwnerSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    direct_owner_seeds: list[Annotated[str, Field(min_length=36, max_length=36)]] = Field(max_length=128)

    @field_validator('direct_owner_seeds')
    @classmethod
    def canonical_unique(cls, values):
        if len(set(values)) != len(values) or any(str(UUID(value)) != value for value in values):
            raise ValueError('Direct creator namespaces must be canonical and unique')
        return values


def owner_ids(seed):
    identifier = identity_factory(seed)
    return identifier('connection-duplex', []), identifier('connection-binding', [])


def dependency_reads(body):
    from backend.core.part_dependencies import Resource
    return {Resource('duplex', owner_ids(seed)[0]) for seed in getattr(body, 'direct_owner_seeds', ())}


def resolve_selection(design, body, index):
    from backend.api import part_connection_application_commands as common

    if not hasattr(body, 'direct_owner_seeds'):
        return body
    selected = {body.overhang_a_id, body.overhang_b_id}
    owned = {'duplex': set(), 'overhang_binding': set()}
    bindings_by_pair = {}
    for binding in design.overhang_bindings:
        pair = frozenset((binding.overhang_a_id, binding.overhang_b_id))
        bindings_by_pair.setdefault(pair, []).append(binding)
    for seed in body.direct_owner_seeds:
        duplex_id, binding_id = owner_ids(seed)
        duplex = common._resolve(index, 'duplex', duplex_id, 'direct_owner_seeds')
        pair = {duplex.left.overhang_id, duplex.right.overhang_id}
        if not selected.intersection(pair):
            common._fail('Direct creator does not own a selected endpoint', 'duplex', duplex_id, 'direct_owner_seeds')
        bindings = bindings_by_pair.get(frozenset(pair), [])
        if duplex.bound:
            valid = snapshot_for(duplex) is not None and not bindings
        else:
            binding = index.get(('overhang_binding', binding_id))
            valid = (snapshot_for(duplex) is None and len(bindings) == 1
                     and binding is bindings[0] and binding.bound and snapshot_for(binding) is not None)
            if valid:
                owned['overhang_binding'].add(binding_id)
        if not valid:
            common._fail('Direct creator has incomplete or inconsistent restoration owners',
                         'duplex', duplex_id, 'direct_owner_seeds')
        owned['duplex'].add(duplex_id)
    updates = {}
    for kind, collection, field in [('duplex', 'duplexes', 'conflict_duplex_ids'),
                                    ('overhang_binding', 'overhang_bindings', 'conflict_binding_ids')]:
        literal = getattr(body, field)
        actual = [item.id for item in getattr(design, collection) if selected.intersection(
            (item.left.overhang_id, item.right.overhang_id) if kind == 'duplex'
            else (item.overhang_a_id, item.overhang_b_id))]
        if owned[kind].intersection(literal) or [i for i in actual if i not in owned[kind]] != literal:
            common._fail('Creator and literal selections must partition the exact conflict set',
                         kind, next(iter(literal or actual), body.version_id), field)
        if len(actual) > common.MAX_CONFLICTS:
            common._unsupported('Resolved direct owners exceed the conflict allowance')
        updates[field] = actual
    return body.model_copy(update=updates)


def capture_selection(source, values):
    """Replace recognized native owners with creator seeds; leave legacy IDs literal."""
    from backend.api import part_connection_application_commands as common

    if not values['conflict_duplex_ids']:
        return {'direct_owner_seeds': [], 'conflict_duplex_ids': [],
                'conflict_binding_ids': list(values['conflict_binding_ids'])}
    if len(source.feature_log) > MAX_PRODUCERS:
        common._unsupported('Direct creator capture exceeds its producer allowance')
    selected = set(values['conflict_duplex_ids'])
    producers = {}
    for entry in source.feature_log:
        params = getattr(entry, 'params', None)
        if getattr(entry, 'op_kind', None) != 'overhang-bulk' or type(params) is not dict:
            continue
        action = params.get('action')
        marker = {'connection-version-apply-direct': 'direct_application_version',
                  'connection-version-connect-direct': 'direct_composition_version'}.get(action) if isinstance(action, str) else None
        if marker is None:
            continue
        version, seed = params.get(marker), params.get('history_seed')
        if type(version) is not int or version not in (1, 2) or not isinstance(seed, str) or len(seed) > 36:
            continue
        try:
            seed = str(UUID(seed))
        except ValueError:
            continue
        duplex, binding = owner_ids(seed)
        if duplex not in selected:
            continue
        if duplex in producers:
            common._fail('Direct creator namespace has multiple producers', 'duplex', duplex, 'direct_owner_seeds')
        producers[duplex] = seed, binding
    ordered = [producers[i] for i in values['conflict_duplex_ids'] if i in producers]
    bindings = {binding for _, binding in ordered}
    return {'direct_owner_seeds': [seed for seed, _ in ordered],
            'conflict_duplex_ids': [i for i in values['conflict_duplex_ids'] if i not in producers],
            'conflict_binding_ids': [i for i in values['conflict_binding_ids'] if i not in bindings]}
