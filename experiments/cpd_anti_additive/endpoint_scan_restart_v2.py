"""Validate exact accepted restarts using the same angle gate as native acquisition.

Versioned separately to preserve every historical source pin.
"""
import numpy as np

from experiments.cpd_anti_additive.corrected_core_stage1 import checked, read
from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle


def validate_scan_seed(plan):
    design = read(checked(plan['scan_design']))
    checked(plan['starting_geometry'])
    task = next(v for v in design['training_tasks'] if v['label'] == plan['scan_label'])
    if task['constraint'] != plan['constraint'] or task['geometry'] != plan['starting_geometry']:
        raise ValueError('Scan differs from frozen training design')
    if not plan.get('continuation_audit'):
        if plan.get('seed_result') is not None:
            raise ValueError('Displaced scan seed cannot reuse reference gradient')
        return
    audit = read(checked(plan['continuation_audit']))
    previous = read(checked(audit['plan']))
    if not audit['passed'] or audit['constrained_stationary'] or audit['optimizer_converged']:
        raise ValueError('No audited unconverged constrained predecessor')
    for key in ('constraint', 'scan_design', 'scan_label', 'starting_geometry',
                'model', 'elements', 'options', 'psi4_version', 'versions', 'optimizer'):
        if plan[key] != previous[key]:
            raise ValueError(f'Constrained continuation changed {key}')
    if plan['seed_result'] != audit['last_accepted_result']:
        raise ValueError('Restart is not the last audited accepted state')
    seed = read(checked(plan['seed_result']))
    if seed['geometry'] != audit['last_accepted_geometry']:
        raise ValueError('Restart geometry lacks accepted-state audit')
    x = np.load(checked(seed['geometry']))
    gradient = np.load(checked(seed['gradient_binary']))
    if not np.isfinite(gradient).all() or not np.array_equal(gradient, np.asarray(seed['gradient_hartree_bohr'])):
        raise ValueError('Restart gradient differs from saved binary')
    if x.shape != gradient.shape or not np.isfinite(x).all():
        raise ValueError('Invalid restart coordinates')
    # The audited optimizer can accept small residuals above the old 1e-6-degree
    # startup threshold. Preserve its exact geometry and gradient and apply the
    # same capped angle tolerance as native acquisition; never snap coordinates.
    require_scan_angle(x, plan['constraint'])
