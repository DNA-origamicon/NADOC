"""Native ordinary connection fixtures and reversible test-only rollout gates."""

from contextlib import contextmanager
from uuid import UUID

from backend.core.part_history_contract import create_empty_part
from tests.conftest import valid_overhang_sites
from tests.test_part_pending_connection_versions import append

FIXTURES = {f'connection-{kind}' for kind in (
    'opposite', 'same', 'a-longer', 'b-longer', 'same-a-longer', 'same-b-longer', 'shared', 'large', 'blank')}


def fixture(kind):
    design = create_empty_part('__e2e__Connection acceptance', 'HONEYCOMB')
    length = 252 if kind == 'connection-large' else 42
    design = append(design, 'bundle-create', {'_proof_version': 1, 'history_seed': str(UUID(int=701)),
        'cells': [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]],
        'length_bp': length, 'name': '__e2e__Connection acceptance', 'lattice_type': 'HONEYCOMB'}, 'connection-bundle')
    for index in range(2):
        same = kind.startswith('connection-same')
        five_prime = False if same else index == 1
        site = next(item for item in valid_overhang_sites(design) if item['is_five_prime'] == five_prime)
        size = (8 if kind.endswith('a-longer') else 16 if kind.endswith('b-longer') else 12) if index else 12
        design = append(design, 'overhang-extrude', {'_proof_version': 1,
            'history_seed': str(UUID(int=702 + index)), **site, 'direction': site['direction'].value,
            'length_bp': size, 'reuse_existing_helix': kind == 'connection-shared'}, f'connection-endpoint-{index}')
    if kind != 'connection-blank':
        # Authored sequence commands keep cold replay independent of fixtures.
        for index, spec in enumerate(design.overhangs):
            design = append(design, 'overhang-sequence', {'_proof_version': 1, 'overhang_id': spec.id,
                'action': 'set', 'sequence': ('A' if index == 0 else 'T') * sum(sd.length_bp for sd in spec.sub_domains)},
                f'connection-sequence-{index}')
    return design


@contextmanager
def enabled():
    from backend.api import routes_connection_versions as routes, part_connection_disconnect as disconnect
    from backend.api import part_connection_version_commands as metadata
    selected = [(routes, 'NATIVE_CONNECTION_OWNER_SELECTION_ENABLED'), (disconnect, 'ENABLED'),
                (metadata, 'APPLIED_METADATA_ENABLED')]
    previous = [(module, name, getattr(module, name)) for module, name in selected]
    try:
        for module, name in selected:
            setattr(module, name, True)
        yield
    finally:
        for module, name, value in previous:
            setattr(module, name, value)
