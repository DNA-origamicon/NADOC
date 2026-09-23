"""Bounded profile-driven wheel acquisition and length correction."""
import json
import math
from pathlib import Path
from tools.vr_motion.metrics import norm, target_metrics
from tools.vr_motion.model import Profile, reach
from tools.vr_motion.presets import PRESETS
from tools.vr_motion.extrude_probe import drag
from tools.vr_workflows.profile_input import reach_target


def wheel_travel(current, target, period, notch):
    if period <= 0 or notch <= 0 or (target-current) % period:
        raise ValueError('target must be reachable in whole wheel detents')
    detents = (target-current)//period
    return math.copysign((abs(detents)+.5)*notch, detents) if detents else 0


def fine_length(live, target, period, click, record):
    """At most one detent's worth of single-base clicks; verify each effect."""
    remaining = target-live.state['extrude']['length_bp']
    if abs(remaining) > period:
        raise ValueError('fine correction exceeds one detent')
    cells = [list(cell) for cell in live.state['extrude']['cells']]
    for _ in range(abs(remaining)):
        before = live.state['extrude']['length_bp']
        sign = 1 if target > before else -1
        click('+' if sign > 0 else '-')
        after = live.state['extrude']['length_bp']
        record({'before_bp':before,'after_bp':after,'expected_bp':before+sign})
        if after != before+sign or live.state['extrude']['cells'] != cells:
            raise RuntimeError('Fine length click changed unexpected state')


def set_wheel_length(live, output, target, preset, seed=0, fine_click=None):
    output = Path(output)
    trials = []
    cells = live.state['extrude']['cells']
    def save():
        output.write_text(json.dumps(trials,indent=2)+'\n')
    for correction in range(4):
        before = live.state['extrude']['length_bp']
        if before == target:
            return trials
        state = live.state['extrude']
        if fine_click and abs(target-before) <= state['base_pairs_per_detent']:
            trial = {'before_bp':before,'target_bp':target,'fine_clicks':[]}
            trials.append(trial)
            def record(step):
                trial['fine_clicks'].append(step)
                save()
            fine_length(live,target,state['base_pairs_per_detent'],fine_click,record)
            return trials
        if correction == 3:
            break  # Final fine correction is allowed; a fourth wheel drag is not.
        travel = wheel_travel(before,target,state['base_pairs_per_detent'],state['wheel_notch_travel_m'])
        control = next(c for c in live.state['controls'] if c['label']=='EXTRUDE LENGTH WHEEL')
        trial = {'before_bp':before,'target_bp':target,'travel_m':travel,'acquisition':[]}
        trials.append(trial)
        acquired = False
        for attempt in range(3):
            motion = reach_target(live,control['position'],preset,seed+correction*100+attempt)
            metrics = target_metrics(control,live.state['hands'][1])
            hit = metrics['predicted_hit'] and live.state['extrude']['wheel_hovered']
            motion.update(metrics=metrics,hit=hit)
            trial['acquisition'].append(motion);save()
            if hit:
                live.send('button',hand=1,button='trigger',pressed=True);live.frame()
                acquired = live.state['extrude']['wheel_dragging']
                break
        if not acquired:
            live.send('button',hand=1,button='trigger',pressed=False);live.frame()
            raise RuntimeError('Profile wheel acquisition failed')
        try:
            pose = live.state['hands'][1]
            up = control['hit_half_up']; magnitude = norm(up)
            endpoint = [p+travel*u/magnitude for p,u in zip(pose['position'],up)]
            duration,profile = PRESETS[preset]
            args = dict(start_q=pose['orientation_xyzw'],target_q=pose['orientation_xyzw'],
                        duration_s=duration,rate_hz=20,seed=seed+correction*100+50)
            intended = reach(pose['position'],endpoint,**args,profile=Profile(
                position_sigma_m=0,rotation_sigma_deg=0,overshoot_fraction=0,reaction_s=profile.reaction_s))
            noisy = reach(pose['position'],endpoint,**args,profile=profile)
            trial['samples'] = drag(live,noisy,intended)
        finally:
            live.send('button',hand=1,button='trigger',pressed=False);live.frame()
        trial['after_bp'] = live.state['extrude']['length_bp'];save()
        if live.state['extrude']['cells'] != cells:
            raise RuntimeError('Wheel motion changed painted cells')
    if live.state['extrude']['length_bp'] != target:
        raise RuntimeError('Profile wheel length still incorrect after three drags')
    return trials
