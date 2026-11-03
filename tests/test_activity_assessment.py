"""Bounded decisions preserve unknown evidence and never invoke runtime effects."""
import itertools
from copy import deepcopy

import pytest

from backend.core.activity_assessment import namd_activity, mrdna_activity, raw_mrdna_complete


def old_namd(f):
    if not f['running']: return 'unchanged'
    if f['live']: return 'live'
    if not f['segment_valid']: return 'finalization_required'
    if f['outputs_complete']: return 'segment_finalization_required'
    if f['minimization_missing']: return 'resume_minimization'
    if f['checkpoint']: return 'resume_checkpoint'
    return 'failed_without_checkpoint' if f['log_exists'] else 'resume_unstarted_segment'


def old_mrdna(f):
    if f['live']: return 'live'
    if f['cached']: return 'completed_cache'
    if f['raw_complete']: return 'finalization_required'
    return 'stopped' if f['running'] else 'unchanged'


@pytest.mark.parametrize('assess,oracle,keys', [
    (namd_activity, old_namd, ('running', 'live', 'segment_valid', 'outputs_complete', 'minimization_missing', 'checkpoint', 'log_exists')),
    (mrdna_activity, old_mrdna, ('live', 'cached', 'raw_complete', 'running')),
])
def test_exhaustive_branch_parity_and_unknown_precedence(assess, oracle, keys):
    for combination in itertools.product((False, True), repeat=len(keys)):
        facts = dict(zip(keys, combination));before = deepcopy(facts)
        assert assess(facts).action == oracle(facts)
        assert facts == before
        partial = {}
        for key in keys:
            decision = assess(partial)
            if decision.action != 'unknown': break
            assert decision.missing == key
            assert assess({**partial, key: None}) == decision
            partial[key] = facts[key]
        assert assess(partial).action == oracle(facts)


@pytest.mark.parametrize('bad', [[], {'extra': True}, {'running': 1}, {'live': []},
    {str(i): True for i in range(10)}, {'x' * 1000: True}])
@pytest.mark.parametrize('assess', [namd_activity, mrdna_activity])
def test_closed_scalar_budget(bad, assess):
    with pytest.raises(ValueError): assess(bad)


def test_subclasses_cannot_supply_hooks():
    class Bad(dict):
        def items(self): pytest.fail('Subclass traversal')
    with pytest.raises(ValueError): namd_activity(Bad(running=True))


@pytest.mark.parametrize('steps,progress,expected', [(0, 1., False), (1, None, False),
    (1, .98, False), (1, .99, True), (1, 1., True)])
def test_existing_raw_completion_predicate(steps, progress, expected):
    assert raw_mrdna_complete(steps, progress) is expected


def test_assessment_cannot_create_files_or_use_runtime(tmp_path, monkeypatch):
    from backend.core import simulation_runtime
    monkeypatch.setattr(simulation_runtime, 'is_owned', lambda *a: pytest.fail('Runtime probe'))
    monkeypatch.setattr(simulation_runtime, '_reserve', lambda *a, **k: pytest.fail('Runtime lock'))
    assert namd_activity({'running': True, 'live': False, 'segment_valid': False}).action == 'finalization_required'
    assert mrdna_activity({'live': False, 'cached': False, 'raw_complete': True}).action == 'finalization_required'
    assert not list(tmp_path.iterdir())
