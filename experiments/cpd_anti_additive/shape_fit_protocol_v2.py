"""A single successor of the closed first candidate, retaining its consumed round."""
from pathlib import Path
from experiments.cpd_anti_additive import preliminary_protocol as old
from experiments.cpd_anti_additive.validation_gate import read, source, checked

STATE = old.REPO/'.development-artifacts/cpd-anti-shape-state-v2-r2'


def require_fit_ready(stage='conformational', state=None):
    state = Path(state or STATE).resolve()
    if stage != 'conformational':
        raise ValueError('Shape revision only supports the conformational stage')
    registration = read(state/'registration.json')
    for ref in registration['files']:
        checked(ref)
    lineage = read(state/'lineage.json')
    parent = Path(lineage['parent_state'])
    if source(parent/'conformational_successor.json') != lineage['successor_claim']:
        raise RuntimeError('Successor claim changed')
    claim = read(checked(lineage['successor_claim']))
    if Path(claim['state']).resolve() != state or claim['input_lock'] != source(state/'conformational_input_lock.json'):
        raise RuntimeError('This is not the registered successor')
    for key in ('parent_candidate_lock','parent_rounds','parent_closeout','parent_activation'):
        checked(lineage[key])
    closeout = read(checked(lineage['parent_closeout']))
    if not closeout['all_four_QM_constrained_stationarity_passed'] or closeout['fit_rounds_used'] != 1:
        raise RuntimeError('First-candidate closeout incomplete')
    parent_rounds = read(checked(lineage['parent_rounds']))
    current = read(state/'conformational_rounds.json')
    if len(parent_rounds) != 1 or current[:1] != parent_rounds or len(current) not in (1,2):
        raise RuntimeError('Consumed fit round was reset or expanded')
    if len(current) == 2 and (current[1]['round'] != 2 or current[1]['output'] != lineage['output']):
        raise RuntimeError('Unregistered second fit round')
    policy, receipt = old.require(stage, state)
    if receipt['case_ids'] != closeout['exposed_case_ids'] or receipt['max_campaign_rounds'] != 2:
        raise RuntimeError('Exposed membership or round budget changed')
    if receipt['revision'] != 'shape-v2.2' or receipt['original_candidate_lock'] != lineage['parent_candidate_lock']:
        raise RuntimeError('Revision identity changed')
    return policy, receipt


def begin_round(output, state=None):
    state = Path(state or STATE).resolve()
    require_fit_ready(state=state)
    lineage = read(state/'lineage.json')
    if str(Path(output).resolve()) != lineage['output']:
        raise RuntimeError('Unregistered fit output')
    return old.begin_round('conformational', output, state)
