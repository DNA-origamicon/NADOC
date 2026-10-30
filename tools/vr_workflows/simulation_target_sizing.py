"""Offline, paired-seed target-size estimate using the unchanged human profiles.

Run after building nadoc-vr-simulation-panel-test:
 python -m tools.vr_workflows.simulation_target_sizing --output report.json
This measures isolated, front-facing native control rectangles, not live input,
neighbor interception, physical headset visibility, or human population success.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

import numpy as np

from tools.vr_motion.metrics import rotate
from tools.vr_motion.model import reach
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.profile_input import AcquisitionWindow


def required_windows(trace, reaction, *, signed=False):
    """Dimensions enclosing every sample of each eligible stable-hover window."""
    samples = trace['samples']
    times = np.array([s['t'] for s in samples])
    contacts = []
    for sample in samples:
        pose = sample['hands']['right']
        direction = rotate(pose['orientation'], [0, 0, -1])
        distance = -pose['position'][2] / direction[2]
        contacts.append((np.array(pose['position'][:2]) +
                               distance * np.array(direction[:2]))
                        if distance > 0 else np.array([np.inf, np.inf]))
    contacts = np.array(contacts)
    windows = []
    for i, t in enumerate(times):
        if t < reaction:
            continue
        end = np.searchsorted(times, t + reaction - 1e-9)
        if end < len(times):
            windows.append(2 * np.abs(contacts[i:end+1]).max(axis=0))
    return np.array(windows), contacts if signed else np.abs(contacts)


def run(trials, executable):
    controls = json.loads(subprocess.check_output([executable, '--target-dimensions']))
    scales = [1, 1.3, 1.6, 2, 2.5, 3, 4, 5, 6, 7, 8, 10]
    results = []
    for name, (duration, profile) in PRESETS.items():
        for distance in [.3, .6, .9]:
            counts = np.zeros((len(controls), len(scales)), dtype=int)
            minimum_squares = []
            minimum_scales = []
            minimum_wide_heights = []
            for seed in range(4200, 4200 + trials):
                trace = reach([-.12, -.08, distance], [0, 0, distance],
                              duration_s=duration, rate_hz=20, seed=seed, profile=profile)
                windows, contacts = required_windows(trace, profile.reaction_s)
                minimum_squares.append(np.max(windows, axis=1).min())
                wide = windows[windows[:, 0] <= .2, 1]
                minimum_wide_heights.append(wide.min() if len(wide) else np.inf)
                trial_scale = 0
                for i, control in enumerate(controls):
                    sizes = np.array([control['width_m'], control['height_m']])
                    trial_scale = max(trial_scale, np.max(windows/sizes, axis=1).min())
                    acquired = np.any(np.all(windows[:, None, :] <=
                                              sizes * np.array(scales)[:, None], axis=2), axis=0)
                    counts[i] += acquired
                    # Independently check the optimized window calculation against
                    # the exact feedback policy used by live profile-driven clicks.
                    if seed == 4200:
                        for j, scale in enumerate(scales):
                            window = AcquisitionWindow(duration, profile.reaction_s)
                            observed = False
                            for sample, contact in zip(trace['samples'], contacts):
                                observed |= window.update(sample['t'], bool(np.all(contact <= sizes*scale/2)))
                            assert observed == acquired[j]
                minimum_scales.append(trial_scale)
            row = {'preset': name, 'distance_m': distance,
                   'all_controls_scale_99': float(np.quantile(minimum_scales, .99, method='higher')),
                   'square_99_mm': float(np.quantile(minimum_squares, .99, method='higher')*1000),
                   'width_200mm_height_99_mm': float(np.quantile(minimum_wide_heights, .99, method='higher')*1000),
                   'controls': [{**c, 'success_counts': dict(zip(map(str, scales), map(int, counts[i])))}
                                for i, c in enumerate(controls)]}
            results.append(row)
            print(name, distance, '99% square mm', round(row['square_99_mm'], 1), flush=True)
    return {'method': 'offline isolated rectangle; reaction_then_stable_hover_v1',
            'profiles': {name: {'duration_s': duration, **asdict(profile)}
                         for name, (duration, profile) in PRESETS.items()},
            'trials_per_condition': trials, 'seeds': [4200, 4200+trials-1],
            'sample_rate_hz': 20, 'initial_offset_m': [-.12, -.08, 0],
            'baseline_menu_scale': .45, 'selected_job_multiplier': 1.3,
            'criterion': '99% empirical single-attempt stable-hover acquisition; no retries',
            'limitations': 'Synthetic estimate, not a population guarantee. Front-facing planes; excludes neighboring control interception, live transport and headset comfort. 99% empirical is not a 99% lower confidence bound.',
            'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=int, default=1000)
    parser.add_argument('--native-test', default='native/vr_viewer/build/nadoc-vr-simulation-panel-test')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(run(args.trials, args.native_test), indent=2)+'\n')
