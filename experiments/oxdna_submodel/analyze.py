"""Audit frozen degrees of freedom, native HB lists and the full input process."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from backend.core.constants import OXDNA_LENGTH_UNIT
from backend.core.models import Design
from scripts.agent_structure_guard import audit


def frames(path, count):
    lines = path.read_text().splitlines()
    if len(lines) % (count+3):
        raise ValueError('Incomplete trajectory')
    return [np.array([[float(x) for x in line.split()] for line in lines[i+3:i+count+3]])
            for i in range(0,len(lines),count+3)]


def analyze(output, binary, run_name="experiment"):
    output = Path(output).resolve(); run = output/run_name
    manifest = json.loads((output/'manifest.json').read_text())
    mapping = json.loads((output/'mapping.json').read_text())
    mobile = np.array([x['mobile'] for x in mapping]); n = len(mobile)
    source = Path(manifest['source'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['source_sha256']
    audit(Design.model_validate_json(Path(manifest['upstream_history']).read_text()))
    initial = frames(run/'initial_normalized.dat', n)[0]
    trajectory = frames(run/'trajectory.dat', n)
    final = frames(run/'last_conf.dat', n)[0]
    assert np.isfinite(np.array(trajectory)).all()
    fixed_pos = max(float(abs(frame[~mobile,:3]-initial[~mobile,:3]).max()) for frame in trajectory+[final])
    fixed_axes = max(float(abs(frame[~mobile,3:9]-initial[~mobile,3:9]).max()) for frame in trajectory+[final])
    assert fixed_pos == 0 and fixed_axes == 0
    (run/'analysis_frames.dat').write_text((run/'initial_normalized.dat').read_text()+(run/'trajectory.dat').read_text())
    (run/'analysis.input').write_text('''interaction_type = DNA2
T = 20C
salt_concentration = 0.5
use_average_seq = 1
topology = topology.top
trajectory_file = analysis_frames.dat
list_type = no
analysis_data_output_1 = {
 name = hydrogen_bonds.dat
 print_every = 1
 col_1 = {
  type = hb_list
 }
}
''')
    with (run/'analysis.log').open('w') as log:
        subprocess.run([str(Path(binary).resolve()), 'analysis.input'], cwd=run, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    by_bp = {}
    for row in mapping:
        by_bp.setdefault(row['key'][1],[]).append(row['particle'])
    expected = {tuple(sorted(pair)) for pair in by_bp.values()}
    hb_frames = []
    for line in (run/'hydrogen_bonds.dat').read_text().splitlines():
        if line.startswith('# step'):
            hb_frames.append({'step':int(line.split()[-1]), 'pairs':set()})
        elif line.strip():
            hb_frames[-1]['pairs'].add(tuple(sorted(map(int,line.split()))))
    retained = [len(frame['pairs'] & expected) for frame in hb_frames]
    mobile_pairs = {pair for pair in expected if mobile[pair[0]] and mobile[pair[1]]}
    mobile_retained = [len(frame['pairs'] & mobile_pairs) for frame in hb_frames]
    displacements = np.linalg.norm(final[:,:3]-initial[:,:3],axis=1)*OXDNA_LENGTH_UNIT
    energy = np.loadtxt(run/'energy.dat')
    if run_name == 'quench':
        assert np.max(np.diff(energy[:,1])) <= 1e-6
    results = {'fixed_position_drift_nm':fixed_pos*OXDNA_LENGTH_UNIT,
               'fixed_axis_component_drift':fixed_axes,
               'checked_frames_including_final':len(trajectory)+1,
               'mobile_rms_displacement_nm':float(np.sqrt(np.mean(displacements[mobile]**2))),
               'mobile_max_displacement_nm':float(displacements[mobile].max()),
               'designed_pairs_initial':retained[0], 'designed_pairs_final':retained[-1],
               'designed_pairs_min':min(retained), 'mobile_pairs_final':mobile_retained[-1],
               'mobile_pairs_min':min(mobile_retained),
               'energy_initial_per_nucleotide':float(energy[0,1]),
               'energy_final_per_nucleotide':float(energy[-1,1]),
               'translation_acceptance':float(energy[-1,2]), 'rotation_acceptance':float(energy[-1,3]),
               'steps':int(energy[-1,0]), 'source_unchanged':True,
               'interpretation':('Downhill-only stochastic relaxation at the 20 C potential; not thermal sampling or dynamics.' if run_name == 'quench' else 'Finite-temperature constrained MC relaxation, not energy minimization or dynamics; no convergence claim.')}
    (output/f'{run_name}-results.json').write_text(json.dumps(results,indent=2))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,3,figsize=(12,4),layout='constrained')
    for s in range(2):
        sl=slice(42*s,42*(s+1))
        a=initial[sl,:3]*OXDNA_LENGTH_UNIT; b=final[sl,:3]*OXDNA_LENGTH_UNIT
        axes[0].plot(a[:,0],a[:,2],color='0.7',lw=1)
        axes[0].plot(b[:,0],b[:,2],lw=1,color=['#e4ad20','#1686c4'][s])
    axes[0].axhspan(manifest['selection']['box']['min_corner'][2],manifest['selection']['box']['max_corner'][2],alpha=.1,color='green')
    axes[0].set(xlabel='x (nm)',ylabel='z (nm)',title='Initial grey; final coloured')
    axes[0].set_aspect('equal')
    axes[0].set_xticks([2])
    axes[1].plot([x['key'][1] for x in mapping[:42]],displacements[:42],label='Scaffold')
    axes[1].plot([x['key'][1] for x in mapping[42:]],displacements[42:],label='Staple')
    axes[1].axvspan(13.5,27.5,color='green',alpha=.1)
    axes[1].set(xlabel='Helix bp index',ylabel='Displacement (nm)',title='Motion confined to selected bases');axes[1].legend()
    axes[2].plot(energy[:,0],energy[:,1]);axes[2].set(xlabel='MC sweep (84 proposals)',ylabel='oxDNA energy / nucleotide',title=('Downhill-only relaxation' if run_name == 'quench' else '20 °C constrained MC'))
    fig.savefig(output/f'{run_name}-relaxation.png',dpi=160);plt.close(fig)
    hashes={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.rglob('*') if p.is_file() and p.name!='hashes.json'}
    (output/'hashes.json').write_text(json.dumps(hashes,indent=2))
    print(json.dumps(results,indent=2))

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output');p.add_argument('dnanalysis');p.add_argument('--run',default='experiment');a=p.parse_args()
    analyze(a.output,a.dnanalysis,a.run)
