"""Isolated capture remains equal to deepcopy without model normalization."""
from copy import deepcopy

import pytest
from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic_core import PydanticUndefined

from backend.core.models import Design, Domain, Direction, Strand, Helix, Vec3, Crossover, HalfCrossover
from backend.core.part_model_copy import copy_model_graph, model_copy_hint, allocate_model_copies
from backend.core.part_capture_graph import GraphBudget, CaptureLimit
from backend.core.part_verification_capture import capture


def example():
    domain = Domain(helix_id='h', start_bp=0, end_bp=20, direction=Direction.FORWARD)
    strand = Strand(id='s', domains=[domain, domain], routing_seed=[domain])
    helix = Helix(id='h', axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=7), length_bp=21)
    return Design.model_construct(strands=[strand], helices=[helix])


@pytest.mark.parametrize('pooled', [False, True, 'undersized'])
def test_copy_matches_native_deepcopy_and_preserves_owned_aliases(pooled):
    source = example()
    domain = source.strands[0].domains[0]
    # Cached fields are intentionally retained, not validated or normalized.
    source.strands[0].__dict__['cache'] = {'model': domain, 'fields': domain.__dict__}
    pools = allocate_model_copies(model_copy_hint(source)) if pooled else None
    if pooled == 'undersized':
        pools[Domain].clear()
    result = copy_model_graph(source, model_copies=pools)
    assert result == deepcopy(source)
    copied = result.strands[0]
    assert copied.domains[0] is copied.domains[1] is copied.routing_seed[0] is copied.__dict__['cache']['model']
    assert copied.domains[0].__dict__ is copied.__dict__['cache']['fields']
    copied.domains[0].start_bp = 4
    copied.__pydantic_fields_set__.clear()
    assert domain.start_bp == 0 and source.strands[0].model_fields_set


class Extended(BaseModel):
    model_config = ConfigDict(extra='allow')
    values: list
    _notes: list = PrivateAttr(default_factory=list)


def test_private_extra_cycles_and_custom_copy_hooks_keep_python_semantics():
    source = Extended(values=[{}], extra=[1])
    source._notes.append(source.values[0])
    source.__pydantic_private__['undefined'] = PydanticUndefined
    result = copy_model_graph(source)
    assert result == deepcopy(source)
    assert result._notes[0] is result.values[0] and result.values[0] is not source.values[0]
    assert result.__pydantic_extra__ is not source.__pydantic_extra__
    cycle = []; cycle.append(cycle)
    cloned = copy_model_graph(cycle)
    assert cloned is cloned[0] and cloned is not cycle

    class Custom(Extended):
        def __deepcopy__(self, memo=None):
            return 'custom-copy'
    assert copy_model_graph(Custom(values=[])) == deepcopy(Custom(values=[])) == 'custom-copy'


@pytest.mark.parametrize('limit', ['nodes', 'bytes'])
def test_scalar_accounting_has_exact_original_charges_and_refusals(limit):
    source = example()
    source.strands[0].domains[0].helix_id = 'Unicode-α'
    results = []
    for validation in (None, lambda _: None):
        budget = GraphBudget(max_nodes=10000, max_bytes=100000, seconds=None, clock=lambda: 0)
        budget.charge(source, validate=validation)
        results.append(budget.remaining)
    assert results[0] == results[1]
    nodes, size = 10000 - results[0][0], 100000 - results[0][1]
    for validation in (None, lambda _: None):
        budget = GraphBudget(max_nodes=nodes-(limit == 'nodes'), max_bytes=size-(limit == 'bytes'),
            seconds=None, clock=lambda: 0)
        with pytest.raises(CaptureLimit):
            budget.charge(source, validate=validation)


@pytest.mark.parametrize('limits', [{'seconds': 0}, {'max_nodes': 1}, {'max_bytes': 1}])
def test_empty_destinations_cannot_bypass_capture_admission(limits):
    source = example()
    before = deepcopy(source)
    pools = allocate_model_copies(model_copy_hint(source))
    assert all(all(value is None for value in shell.__dict__.values()) for pool in pools.values() for shell in pool)
    with pytest.raises(CaptureLimit):
        capture(source, model_copies=pools, **limits)
    assert source == before


def test_pooled_capacity_does_not_add_absent_fields_or_field_set_members():
    source = example()
    del source.strands[0].domains[0].__dict__['overhang_id']
    source.strands[0].domains[0].__pydantic_fields_set__.discard('direction')
    source.strands[0].domains[0].__dict__['cached'] = {'mutable': []}
    copied = copy_model_graph(source, model_copies=allocate_model_copies(model_copy_hint(source)))
    assert copied == deepcopy(source)
    assert copied.strands[0].domains[0].__dict__.keys() == source.strands[0].domains[0].__dict__.keys()
    assert copied.strands[0].domains[0].__pydantic_fields_set__ == source.strands[0].domains[0].__pydantic_fields_set__
    assert copied.strands[0].domains[0].__dict__['cached'] is not source.strands[0].domains[0].__dict__['cached']


@pytest.mark.parametrize('extended', [False, True])
def test_capture_copies_charged_leaves_once_without_changing_aliases_or_extensions(extended):
    source = example()
    domain = source.strands[0].domains[0]
    if extended:
        domain.__dict__['extension'] = {'notes': []}
    source.strands[0].__dict__['cache'] = {'fields': domain.__dict__}
    source.helices[0].axis_end = source.helices[0].axis_start
    result = capture(source, seconds=1, model_copies=allocate_model_copies(model_copy_hint(source)))
    assert result.strands == deepcopy(source.strands) and result.helices == deepcopy(source.helices)
    copied = result.strands[0]
    assert copied.domains[0] is copied.domains[1] is copied.routing_seed[0]
    assert copied.domains[0].__dict__ is copied.__dict__['cache']['fields']
    assert result.helices[0].axis_end is result.helices[0].axis_start
    copied.domains[0].start_bp = 3
    assert domain.start_bp == 0


@pytest.mark.parametrize('extended', [False, True])
def test_crossover_capture_preserves_endpoint_aliases_and_unknown_fields(extended):
    half = HalfCrossover(helix_id='α', index=12, strand=Direction.FORWARD)
    first = Crossover(id='a', half_a=half, half_b=half)
    second = Crossover(id='b', half_a=half, half_b=half, extra_bases='TT')
    if extended:
        first.__dict__['cached'] = {'fields': half.__dict__, 'notes': []}
    source = Design.model_construct(crossovers=[first, second, first])
    result = capture(source, seconds=1, model_copies=allocate_model_copies(model_copy_hint(source)))
    assert result.crossovers == deepcopy(source.crossovers)
    a, b, repeated = result.crossovers
    assert a is repeated and a.half_a is a.half_b is b.half_a is b.half_b
    if extended:
        assert a.__dict__['cached']['fields'] is a.half_a.__dict__
    a.half_a.index = 5
    assert half.index == 12
    charges = []
    for specialized in (False, True):
        budget = GraphBudget(max_nodes=1000, max_bytes=10000, seconds=None, clock=lambda: 0)
        budget.charge(source.crossovers, scalar_atoms=specialized)
        charges.append(budget.remaining)
    assert charges[0] == charges[1]
    for specialized in (False, True):
        for node_limit, byte_limit in ((1000-charges[0][0]-1, 10000), (1000, 10000-charges[0][1]-1)):
            budget = GraphBudget(max_nodes=node_limit, max_bytes=byte_limit, seconds=None, clock=lambda: 0)
            with pytest.raises(CaptureLimit):
                budget.charge(source.crossovers, scalar_atoms=specialized)


def test_acyclic_copy_does_not_retain_its_memo_until_cyclic_collection():
    from weakref import ref
    source = example()
    copied = copy_model_graph(source)
    reference = ref(copied)
    del copied
    assert reference() is None


def test_header_construction_preserves_native_defaults_and_explicit_fields_set():
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_capture_inputs import _construct
    values = dict(id='header', op_kind='nanoparticle-create', label='Create', params={'count': 2})
    expected = SnapshotLogEntry.model_construct(**values)
    first = _construct(SnapshotLogEntry, **values)
    second = _construct(SnapshotLogEntry, **values)
    assert first == expected and first.__dict__ == expected.__dict__
    assert first.model_fields_set == expected.model_fields_set == set(values)
    first.diff_removed_ids.append('private')
    assert second.diff_removed_ids == expected.diff_removed_ids == []


def test_complete_publication_copy_keeps_history_display_and_cross_field_aliases():
    from backend.core.models import SnapshotLogEntry, DesignAnimation
    from backend.core.part_capture_copy import copy_complete_design
    source = example()
    source.animations = [DesignAnimation(name='Retained animation')]
    source.feature_log = [SnapshotLogEntry(id='row', op_kind='nanoparticle-create', label='Retained',
        params={'fields': source.strands[0].domains[0].__dict__}, post_state_gz_b64='opaque recovery')]
    expected = deepcopy(source)
    result = copy_complete_design(source, model_copies=allocate_model_copies(model_copy_hint(source)))
    assert result == expected
    assert result.feature_log[0].params['fields'] is result.strands[0].domains[0].__dict__
    result.animations[0].name = 'Changed privately'
    result.feature_log[0].params['fields']['start_bp'] = 3
    assert source.animations[0].name == 'Retained animation'
    assert source.strands[0].domains[0].start_bp == 0


def test_scalar_sequence_accounting_matches_unspecialized_walk():
    source = [list(range(130)), ('α', None, True, 1.5)]
    charges = []
    for validation in (None, lambda _: None):
        budget = GraphBudget(max_nodes=1000, max_bytes=10000, seconds=None, clock=lambda: 0)
        budget.charge(source, validate=validation)
        charges.append(budget.remaining)
    assert charges[0] == charges[1]
    for validation in (None, lambda _: None):
        budget = GraphBudget(max_nodes=1000-charges[0][0]-1, max_bytes=10000, seconds=None, clock=lambda: 0)
        with pytest.raises(CaptureLimit):
            budget.charge(source, validate=validation)
