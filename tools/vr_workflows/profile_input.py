"""Measured profile-driven reaches to live exported targets; no endpoint snapping."""
import math
import time
from tools.vr_motion.model import Profile, reach, vector
from tools.vr_motion.metrics import pose_error
from tools.vr_motion.presets import PRESETS


def aim_orientation(origin, target):
    delta = [b-a for a,b in zip(vector(origin,3), vector(target,3))]
    length = math.sqrt(sum(x*x for x in delta))
    if length < 1e-9:
        raise ValueError('target coincides with controller')
    x,y,z = [v/length for v in delta]
    if z > 1-1e-12:
        return [1,0,0,0]
    q = [y,-x,0,1-z]  # Shortest rotation from the controller's local -Z ray.
    length = math.sqrt(sum(v*v for v in q))
    return [v/length for v in q]


def target_reaches(pose, target, preset, seed, target_position=None, target_orientation=None):
    duration, profile = PRESETS[preset]
    destination = pose['position'] if target_position is None else vector(target_position,3)
    args = dict(start_q=pose['orientation_xyzw'],
                target_q=(aim_orientation(destination, target) if target_orientation is None
                          else target_orientation),
                duration_s=duration, rate_hz=20, seed=seed)
    intended = reach(pose['position'], destination, **args,
                     profile=Profile(position_sigma_m=0, rotation_sigma_deg=0,
                                     overshoot_fraction=0, reaction_s=profile.reaction_s))
    desired = reach(pose['position'], destination, **args, profile=profile)
    return intended, desired


class AcquisitionWindow:
    """Require continuous feedback after the initial reaction interval."""
    def __init__(self, duration, reaction):
        self.eligible_at = reaction
        self.reaction = reaction
        self.since = None

    def update(self, t, hit):
        if t < self.eligible_at or not hit:
            self.since = None
            return False
        if self.since is None:
            self.since = t
        return t-self.since+1e-9 >= self.reaction


def reach_target(live, target, preset, seed, acquired=None, target_position=None,
                 target_orientation=None):
    """Aim at a point, or reach an explicit pose retaining its requested wrist roll."""
    intended, desired = target_reaches(live.state['hands'][1], target, preset, seed,
                                      target_position, target_orientation)
    samples = []
    duration, profile = PRESETS[preset]
    window = AcquisitionWindow(duration, profile.reaction_s)
    stopped = False
    started = time.monotonic()
    for ideal, noisy in zip(intended['samples'], desired['samples'], strict=True):
        time.sleep(max(0, started+noisy['t']-time.monotonic()))
        lag = time.monotonic()-started-noisy['t']
        if lag > .15:
            raise TimeoutError(f'profile playback late by {lag:.3f}s')
        pose = noisy['hands']['right']
        live.send('pose', hand=1, position=pose['position'], orientation=pose['orientation'])
        live.frame()
        actual = dict(live.state['hands'][1])
        samples.append({'t':noisy['t'], 'lag_s':lag, 'frame':live.state['frame'],
                        'intended':ideal['hands']['right'], 'desired':pose, 'actual':actual,
                        'applied_error':pose_error(pose,actual)})
        if acquired is not None:
            hit = bool(acquired(live.state))
            samples[-1]['target_hover'] = hit
            if window.update(noisy['t'],hit):
                stopped = True
                break
    return {'preset':preset, 'seed':seed, 'target':target, 'samples':samples,
            'target_position':target_position,
            'target_orientation':target_orientation,
            'position_policy':('explicit_pose' if target_orientation is not None else
                               'translated_aim' if target_position is not None else 'stationary_aim'),
            'acquired_with_feedback':stopped,
            'acquisition_policy':'reaction_then_stable_hover_v1' if acquired is not None else 'endpoint',
            'planned_duration_s':desired['samples'][-1]['t'],
            'stop_reason':'stable_hover' if stopped else 'completed_reach'}


def zoom_scene(live, center, factor):
    """Existing two-hand grip gesture, used as declared presentation setup."""
    if not .125 <= factor <= 8:
        raise ValueError('diagnostic zoom must be .125..8')
    for half_width in [0.04, 0.04*factor]:
        for hand, sign in [(0,-1),(1,1)]:
            position = [center[0]+sign*half_width, center[1]-0.25, center[2]]
            live.send('pose',hand=hand,position=position,orientation=[0,0,0,1])
        live.frame()
        if half_width == 0.04:
            for hand in [0,1]:live.send('button',hand=hand,button='grip',pressed=True)
            live.frame()
    for hand in [0,1]:live.send('button',hand=hand,button='grip',pressed=False)
    live.frame()
