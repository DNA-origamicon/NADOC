"""Small canonical configurational control: two harmonic frequency groups.

This is a diagnostic model, not a gold/strep trajectory or a general test of
ergodicity. Seed replicates, rather than saved frames, are the analysis units.
"""
import json
import numpy as np
from thermostat_audit import ROOT, T, fixture, read_frames, run

results = []
k = np.repeat([1., 16.], 32)
centers = fixture(protein=0)[:, :3]
forces = ''.join('{\ntype = trap\nparticle = %d\npos0 = %g,%g,%g\nstiff = %g\nrate = 0\ndir = 1,0,0\n}\n' % (i, *centers[i], k[i]) for i in range(64))
for seed in [811, 1601, 2819, 3877]:
    rng = np.random.default_rng(seed)
    a = fixture(protein=0)
    a[:, :3] += rng.normal(size=(64, 3))*np.sqrt(T/k)[:, None]
    a[:, 9:15] = rng.normal(size=(64, 6))*np.sqrt(T)
    for name, thermostat, settings, experiment in [
        ('installed_bussi', 'bussi', 'newtonian_steps = 53\nbussi_tau = 1000', False),
        ('current_K_bussi', 'bussi', 'newtonian_steps = 53\nbussi_tau = 1000', True),
        ('john', 'john', 'newtonian_steps = 53\ndiff_coeff = .1', False)]:
        label = f'harmonic_{seed}_{name}'
        row = run(label, 'CPU', thermostat, a, 0, 200000, dt=.002, stride=500,
                  settings=settings, forces=forces, experimental=experiment, random_seed=seed)
        frames = read_frames(ROOT/'thermostats'/label/'trajectory.dat', 64)
        tail = frames[len(frames)//2:]
        row['seed'] = seed
        for lo, hi, group in [(0, 32, 'soft'), (32, 64, 'stiff')]:
            row[group+'_config_T_ratio'] = float(np.mean((tail[:, lo:hi, :3]-centers[lo:hi])**2*k[lo:hi][None, :, None])/T)
            row[group+'_kinetic_T_ratio'] = float(np.mean(tail[:, lo:hi, 9:12]**2)/T)
        results.append(row)
        (ROOT/'harmonic_report.json').write_text(json.dumps(results, indent=2))
        print(label, {key: value for key, value in row.items() if '_T_ratio' in key}, flush=True)
