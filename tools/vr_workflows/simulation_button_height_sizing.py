"""Height-only estimates at the selected menu's existing 1.3x scale.

Uses unchanged profiles and native control dimensions/order. Isolated targets
estimate a reflowed layout; fixed-layout estimates enlarge one target at a time
and model first-match rectangle interception. No UI dimensions are changed.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

import numpy as np

from tools.vr_motion.model import reach
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.profile_input import AcquisitionWindow
from tools.vr_workflows.simulation_target_sizing import required_windows

TARGETS = ['sim:local:t:309', 'sim:local:transport', 'sim:local:overlays',
           'sim:local:t:306', 'sim:v:0', 'sim:v:1', 'sim:local:t:303',
           'sim:local:t:310', 'sim:local:t:312', 'sim:local:t:308']
HEIGHTS_MM = [40, 50, 60, 75, 85, 90, 110, 140]


def run(trials, executable):
    layout = json.loads(subprocess.check_output([executable, '--target-layout']))
    sizes = np.array([[c['width_m'], c['height_m']] for c in layout])*1.3
    centers = np.array([c['center_m'] for c in layout])*1.3
    targets = [i for i, c in enumerate(layout) if c['id'] in TARGETS and c['enabled']]
    results = []
    for preset, (duration, profile) in PRESETS.items():
        for distance in [.3, .6, .9]:
            isolated = np.zeros((len(targets), len(HEIGHTS_MM)+1), dtype=int)
            fixed = np.zeros_like(isolated)
            endpoint = np.zeros_like(isolated)
            required = [[] for _ in targets]
            for seed in range(4200, 4200+trials):
                trace = reach([-.12, -.08, distance], [0, 0, distance],
                              duration_s=duration, rate_hz=20, seed=seed, profile=profile)
                windows, contacts = required_windows(trace, profile.reaction_s, signed=True)
                times = np.array([s['t'] for s in trace['samples']])
                starts = np.flatnonzero((times >= profile.reaction_s) &
                                       (times+profile.reaction_s <= times[-1]+1e-9))
                ends = np.searchsorted(times, times[starts]+profile.reaction_s-1e-9)
                for k, i in enumerate(targets):
                    heights = np.r_[sizes[i, 1], np.array(HEIGHTS_MM)/1000]
                    fits_width = windows[:, 0] <= sizes[i, 0]
                    minimum = windows[fits_width, 1]
                    required[k].append(float(minimum.min()) if len(minimum) else float('inf'))
                    isolated[k] += np.any(fits_width[:, None] & (windows[:, 1, None] <= heights), axis=0)
                    endpoint[k] += ((abs(contacts[-1, 0]) <= sizes[i, 0]/2) &
                                    (abs(contacts[-1, 1]) <= heights/2))
                    # Current production hit routing returns the first rectangle,
                    # including disabled controls. Expanded target retains order.
                    points = contacts+centers[i]
                    blocked = np.any(np.all(abs(points[:, None, :]-centers[None, :i, :])
                                            <= sizes[None, :i, :]/2, axis=2), axis=1)
                    intercepted = np.array([blocked[a:b+1].any() for a, b in zip(starts, ends)])
                    assert len(intercepted) == len(windows)
                    if seed == 4200:
                        for h in heights:
                            policy = AcquisitionWindow(duration, profile.reaction_s)
                            hit = (np.abs(contacts[:, 0]) <= sizes[i, 0]/2) & (np.abs(contacts[:, 1]) <= h/2) & ~blocked
                            observed = False
                            for t, inside in zip(times, hit):
                                observed |= policy.update(t, bool(inside))
                            assert observed == np.any(fits_width & (windows[:, 1] <= h) & ~intercepted)
                    fixed[k] += np.any(fits_width[:, None] & (windows[:, 1, None] <= heights) &
                                       ~intercepted[:, None], axis=0)
            rows = []
            for k, i in enumerate(targets):
                ordered = np.sort(required[k])
                def threshold(fraction):
                    # Minimum size with at least ceil(fraction*N) successes.
                    value = ordered[int(np.ceil(trials*fraction))-1]*1000
                    return float(value) if np.isfinite(value) else None
                heights = [float(sizes[i, 1]*1000)]+HEIGHTS_MM
                earlier = np.all(abs(centers[:i]-centers[i]) <
                                 (sizes[:i]+[sizes[i, 0], .075])/2, axis=1)
                rows.append({'id': layout[i]['id'], 'label': layout[i]['label'],
                             'width_mm_fixed': float(sizes[i, 0]*1000),
                             'current_height_mm': heights[0],
                             'minimum_height_95_mm': threshold(.95),
                             'minimum_height_99_mm': threshold(.99),
                             'width_only_success_ceiling_pct': float(np.mean(np.isfinite(ordered))*100),
                             'earlier_overlaps_at_75mm': [layout[j]['id'] for j in np.flatnonzero(earlier)],
                             'height_trials': [{'height_mm': h, 'stable_success_isolated': int(isolated[k, j]),
                                                'stable_success_fixed_layout': int(fixed[k, j]),
                                                'endpoint_hits_isolated': int(endpoint[k, j])}
                                               for j, h in enumerate(heights)]})
            results.append({'preset': preset, 'distance_m': distance, 'controls': rows})
            print(preset, distance, 'complete', flush=True)
    return {'trials_per_condition': trials, 'seed_range': [4200, 4200+trials-1],
            'profiles': {n: {'duration_s': d, **asdict(p)} for n, (d, p) in PRESETS.items()},
            'menu_scale': .585, 'sample_rate_hz': 20, 'initial_offset_m': [-.12, -.08, 0],
            'criterion': 'Single-attempt reaction_then_stable_hover_v1, no retries. Endpoint hit counts also recorded.',
            'method': __doc__,
            'limitations': 'Synthetic front-facing ray-plane model; fixed-layout calculation uses native rectangle order but does not run live XR or cylinder-wheel input ownership. Isolated/reflowed result assumes neighbors are moved out of enlarged bounds. 99% empirical is not a population guarantee. Null height threshold means fixed width prevents reaching that rate.',
            'native_layout_original_scale': layout, 'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=1000)
    parser.add_argument('--native-test', default='native/vr_viewer/build/nadoc-vr-simulation-panel-test')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(run(args.trials, args.native_test), indent=2)+'\n')
