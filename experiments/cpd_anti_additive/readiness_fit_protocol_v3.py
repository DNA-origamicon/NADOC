"""Separate user-authorized readiness continuation, preserving closed v2 ledgers."""
from pathlib import Path
import time
from experiments.cpd_anti_additive import preliminary_protocol as old
from experiments.cpd_anti_additive.validation_gate import read,checked,source
STATE=old.REPO/'.development-artifacts/cpd-anti-readiness-fit-state-v3'


def require_fit_ready(stage='conformational',state=None):
    state=Path(state or STATE)
    if stage!='conformational':raise ValueError('Only conformational fitting is registered')
    lineage=read(state/'lineage.json')
    for pin in read(state/'registration.json')['files']:checked(pin)
    contract=read(checked(lineage['contract']))
    if time.time()>=contract['deadline_epoch']:raise RuntimeError('Readiness compute deadline reached')
    for pin in lineage['historical_locks']:checked(pin)
    if not lineage.get('new_user_authorized_continuation'):raise RuntimeError('Missing continuation authorization')
    policy,receipt=old.require(stage,state)
    points=read(checked(receipt['points']));original=read(checked(lineage['old_points']))
    if points[:23]!=original or len(points)!=24:raise RuntimeError('Old exposed targets changed or membership wrong')
    if receipt['max_model_evaluations']!=240 or receipt['limits']['hard_seconds']!=7200:raise RuntimeError('Fit budget changed')
    if receipt['variables']!=read(checked(lineage['old_receipt']))['variables']:raise RuntimeError('Unregistered parameter model change')
    return policy,receipt


def begin_round(output):
    require_fit_ready()
    return old.begin_round('conformational',output,STATE)
