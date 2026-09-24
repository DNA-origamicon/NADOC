"""Fixed end-to-end acceptance cohort. Missing, failed and duplicate trials fail.

A runner supplies independently verified stage verdicts and evidence references.
This aggregator does not turn a reported verdict into proof of geometric validity.
"""
WORKFLOWS = {
    'desktop_then_vr': ('new_part', 'desktop_6hb', 'enter_vr', 'vr_default',
                        'vr_blunt_end', 'vr_freeform', 'desktop_3d', 'cadnano_edit',
                        'save_reload', 'undo_redo', 'independent_geometry'),
    'vr_first': ('new_part', 'enter_vr', 'vr_default', 'desktop_3d', 'cadnano_edit',
                 'save_reload', 'undo_redo', 'independent_geometry'),
}
PROFILES = ('variable_fast', 'variable_deliberate')
SEEDS = tuple(range(20))
REQUIRED_SUCCESSES = 18


def evaluate(trials):
    indexed = {}
    for trial in trials:
        key = (trial['workflow'], trial['profile'], trial['seed'])
        if (key[0] not in WORKFLOWS or key[1] not in PROFILES
                or type(key[2]) is not int or key[2] not in SEEDS):
            raise ValueError('trial outside fixed validation cohort')
        if key in indexed:
            raise ValueError('duplicate trial; do not replace failed attempts with retries')
        indexed[key] = trial
    groups = []
    for workflow, stages in WORKFLOWS.items():
        for profile in PROFILES:
            passed, missing, failed = [], [], []
            for seed in SEEDS:
                trial = indexed.get((workflow, profile, seed))
                if trial is None:
                    missing.append(seed)
                    continue
                checks = trial.get('stages', {})
                good = all(isinstance(checks.get(stage), dict)
                           and checks[stage].get('passed') is True
                           and isinstance(checks[stage].get('evidence'), str)
                           and bool(checks[stage]['evidence'].strip()) for stage in stages)
                (passed if good else failed).append(seed)
            groups.append({'workflow': workflow, 'profile': profile,
                           'successes': len(passed), 'denominator': len(SEEDS),
                           'success_rate': len(passed)/len(SEEDS),
                           'failed_seeds': failed, 'missing_seeds': missing,
                           'passed': not missing and len(passed) >= REQUIRED_SUCCESSES})
    return {'complete': all(group['passed'] for group in groups), 'groups': groups}
