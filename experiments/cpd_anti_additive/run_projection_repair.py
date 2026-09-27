"""Run a prepared, explicitly approved convergence-metric repair. Never self-authorize."""

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import checked, read, source
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive import geometric_pilot
from experiments.cpd_anti_additive.exact_constraint_projection import exact_gradient_projection
from geometric.internal import DelocalizedInternalCoordinates


def run(root):
    require('optimizer')
    approval = read(root / 'explicit_restart_approval.json')
    if approval.get('approved_by_user') is not True or not approval.get('user_instruction'):
        raise RuntimeError('Original v2 permits no continuation; explicit bounded-restart approval required')
    proposal = read(checked(approval['proposal']))
    if proposal['max_new_gradients'] != 15 or proposal['campaign_max_new_gradients'] != 40:
        raise RuntimeError('Unexpected scientific budget')
    for ref in proposal['sources']:
        checked(ref)
    plan = read(root / 'plan.json')
    if proposal['prepared_plan'] != source(root / 'plan.json') or plan['max_new_evaluations'] != 15:
        raise RuntimeError('Prepared plan changed')
    original = DelocalizedInternalCoordinates.calcGradProj
    try:
        DelocalizedInternalCoordinates.calcGradProj = exact_gradient_projection
        geometric_pilot.run(root)
    finally:
        DelocalizedInternalCoordinates.calcGradProj = original


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
