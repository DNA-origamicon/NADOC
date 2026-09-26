"""Bounded convergence diagnostics for constrained CPD optimization.

Thresholds are campaign heuristics, not convergence or minimum certificates.
Native optimizer owns trust-region decisions and convergence criteria.
"""
import json
import math
from pathlib import Path
import re

POLICY = dict(window=12, force_tolerance=1.5e-5, stalled_force_multiple=10,
              minimum_force_improvement=.10, tiny_step=3e-4,
              excursion_hartree=.005, excursion_force_multiple=10,
              excursion_patience=3, max_evaluations=60)
OPTIMIZER = dict(dynamic_lvl=1, dynamic_lvl_max=1,
                 consecutive_backsteps=2, intrafrag_step_limit=.05,
                 intrafrag_step_limit_min=.001, intrafrag_step_limit_max=.1)
EFFECTIVE = dict(dynamic_level=1, dynamic_lvl_max=1,
                 consecutive_backsteps_allowed=2, intrafrag_trust=.05,
                 intrafrag_trust_min=.001, intrafrag_trust_max=.1)


def verify_options(params):
    actual = {key: getattr(params, key) for key in EFFECTIVE}
    if actual != EFFECTIVE:
        raise RuntimeError(f'CPD optimizer options not applied: {actual}; expected {EFFECTIVE}')
    return actual


def assess(rows, policy=None):
    p = dict(POLICY, **(policy or {}))
    if not rows:
        return 'continue'
    fields = ('energy', 'max_force', 'rms_force', 'max_step')
    if any(not math.isfinite(r[k]) for r in rows for k in fields):
        return 'nonfinite'
    # This can never certify success: only native optimizer plus final audit can.
    best = min(rows, key=lambda r: r['energy'])
    tail = rows[-p['excursion_patience']:]
    if len(rows) >= p['window'] and all(
        r['energy'] > best['energy'] + p['excursion_hartree'] and
        r['max_force'] > max(p['force_tolerance'] * 100,
                             best['max_force'] * p['excursion_force_multiple'])
        for r in tail
    ):
        return 'sustained_excursion'
    w = rows[-p['window']:]
    if len(w) == p['window']:
        if (min(r['max_force'] for r in w) > p['stalled_force_multiple'] * p['force_tolerance']
            and min(r['max_force'] for r in w) >= (1-p['minimum_force_improvement']) * w[0]['max_force']
            and max(r['max_step'] for r in w) < p['tiny_step']):
            return 'stalled_large_force_tiny_steps'
    if len(rows) >= p['max_evaluations']:
        return 'evaluation_budget'
    return 'continue'


def native_rows(text):
    pattern = r'^\s*(\d+)\s+(-\d+\.\d+)\s+([^\n]+)~\s*$'
    rows = {}
    for m in re.finditer(pattern, text, re.M):
        numbers = m[3].replace('*','').replace('o','').split()
        if len(numbers) != 5:
            continue
        values = list(map(float, numbers))
        rows[int(m[1])] = dict(iteration=int(m[1]),energy=float(m[2]),
            delta_energy=values[0],max_force=values[1],rms_force=values[2],
            max_step=values[3],rms_step=values[4])
    return [rows[k] for k in sorted(rows)]


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def install(folder='optimization_guard'):
    """Instrument the installed native driver only inside this Psi4 process.

    Capture evaluated positions BEFORE OptKing proposes/backtracks a step.
    Abort between evaluations; never terminate a gradient halfway through.
    """
    import numpy as np
    import optking
    folder = Path(folder); folder.mkdir(exist_ok=False)
    cls = optking.opt_helper.CustomHelper
    original_init = cls.__init__
    original_compute, original_post = cls.compute, cls.post_step_str
    records = []
    captured = {}
    save(folder/'policy.json', dict(policy=POLICY,optimizer=OPTIMIZER,
         semantics='Diagnostic stop is not convergence; coordinates in bohr, energies hartree.'))

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        actual = verify_options(self.params)
        save(folder/'effective_options.json', actual)

    def compute(self):
        # Psi4 supplies E/gX and evaluated geometry before compute().
        index = len(records)+1
        evaluated = np.array(self.molsys.geom, copy=True)
        gradient = np.array(self.gX, copy=True)
        energy = float(self.E)
        if not (np.isfinite(evaluated).all() and np.isfinite(gradient).all() and math.isfinite(energy)):
            save(folder/'status.json',dict(state='diagnostic_stop',reason='nonfinite',minimum_certified=False))
            raise RuntimeError('CPD adaptive stop: nonfinite energy/geometry/gradient')
        np.savez(folder/f'evaluation-{index:03d}.npz',geometry_bohr=evaluated,gradient=gradient,energy=energy)
        original_compute(self)
        captured.update(iteration=index,energy=energy,max_force=float(np.max(np.abs(self.fq))),
                        rms_force=float(np.sqrt(np.mean(np.asarray(self.fq)**2))),
                        checkpoint=f'evaluation-{index:03d}.npz')
        if self._Hq is not None:
            np.save(folder/'latest_internal_hessian.npy', self._Hq)

    def post(self):
        text = original_post(self)
        row = dict(captured,max_step=float(np.max(np.abs(self.dq))),
                   rms_step=float(np.sqrt(np.mean(np.asarray(self.dq)**2))),
                   trust_radius=float(self.params.intrafrag_trust))
        records.append(row)
        verdict = assess(records)
        converged = self.status() == 'CONVERGED'
        save(folder/'progress.json',dict(records=records,best_energy_checkpoint=min(records,key=lambda r:r['energy'])['checkpoint'],
             best_force_checkpoint=min(records,key=lambda r:r['max_force'])['checkpoint'],
             native_converged=converged,diagnostic=verdict,minimum_certified=False))
        if verdict != 'continue' and not converged:
            save(folder/'status.json',dict(state='diagnostic_stop',reason=verdict,minimum_certified=False))
            raise RuntimeError('CPD adaptive stop: '+verdict)
        if converged:
            save(folder/'status.json',dict(state='native_converged_unreviewed',minimum_certified=False))
        return text

    cls.__init__, cls.compute, cls.post_step_str = initialize, compute, post
