"""Analyze constrained MD without aligning away motion of the fixed boundary."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np
from backend.core.constants import OXDNA_LENGTH_UNIT
from experiments.oxdna_submodel.analyze import frames
from experiments.oxdna_submodel.production import sha


def analyze(root,name,dnanalysis):
    root=Path(root).resolve();folder=root/name
    mapping=json.loads((root/'mapping.json').read_text());n=len(mapping)
    mobile=np.array([row['mobile'] for row in mapping]);initial=frames(folder/'initial_normalized.dat',n)[0]
    trajectory=frames(folder/'trajectory.dat',n);final=frames(folder/'last_conf.dat',n)[0]
    all_frames=np.array([initial,*trajectory,final])
    if not np.isfinite(all_frames).all():raise ValueError('Nonfinite native output')
    drift_pos=float(np.max(np.abs(all_frames[:,~mobile,:3]-initial[~mobile,:3])))
    drift_axes=float(np.max(np.abs(all_frames[:,~mobile,3:9]-initial[~mobile,3:9])))
    fixed_momenta=float(np.max(np.abs(all_frames[:,~mobile,9:15])))
    if drift_pos!=0 or drift_axes!=0 or fixed_momenta!=0:
        raise ValueError(f'Frozen-particle violation: {drift_pos}, {drift_axes}, {fixed_momenta}')
    lineage=json.loads((folder/'lineage.json').read_text())
    assert sha(lineage['source_configuration'])==lineage['source_configuration_sha256']
    assert sha(folder/'conf.dat')==lineage['source_configuration_sha256']
    # Keep source box/time, energies, masks and all input provenance intact.
    (folder/'analysis_frames.dat').write_text((folder/'initial_normalized.dat').read_text()+(folder/'trajectory.dat').read_text())
    text=(folder/'input').read_text().replace('trajectory_file = trajectory.dat','trajectory_file = analysis_frames.dat')
    text+='''\nanalysis_data_output_1 = {
 name = hydrogen_bonds.dat
 print_every = 1
 col_1 = {
  type = hb_list
 }
}
'''
    (folder/'analysis.input').write_text(text)
    with (folder/'analysis.log').open('w') as log:
        subprocess.run([str(Path(dnanalysis).resolve()),'analysis.input'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
    paired={}
    for row in mapping:paired.setdefault(row['key'][1],[]).append(row['particle'])
    expected={tuple(sorted(pair)) for pair in paired.values()}
    selected={p for p in expected if mobile[p[0]] and mobile[p[1]]}
    hb=[]
    for line in (folder/'hydrogen_bonds.dat').read_text().splitlines():
        if line.startswith('# step'):hb.append({'step':int(line.split()[-1]),'pairs':set()})
        elif line.strip():hb[-1]['pairs'].add(tuple(sorted(map(int,line.split()))))
    counts=np.array([len(row['pairs']&expected) for row in hb]);mobile_counts=np.array([len(row['pairs']&selected) for row in hb])
    delta=(all_frames[:,:,:3]-initial[:,:3])*OXDNA_LENGTH_UNIT
    rms=np.sqrt(np.mean(np.sum(delta[:,mobile]**2,axis=-1),axis=1))
    temperature=3000*np.sum(all_frames[:,mobile,9:15]**2,axis=(1,2))/(6*mobile.sum())
    results={'initial_designed_pairs':int(counts[0]),'final_designed_pairs':int(counts[-1]),
      'min_designed_pairs':int(counts.min()),'initial_mobile_pairs':int(mobile_counts[0]),
      'final_mobile_pairs':int(mobile_counts[-1]),'min_mobile_pairs':int(mobile_counts.min()),
      'mean_mobile_pairs':float(mobile_counts.mean()),'mobile_rms_displacement_nm':float(rms[-1]),
      'fixed_position_drift_nm':drift_pos,'fixed_axis_component_drift':drift_axes,'fixed_momenta_max':fixed_momenta,
      'mobile_temperature_mean_K':float(temperature[1:-1].mean()),'degrees_of_freedom':int(6*mobile.sum()),
      'steps':int(hb[-1]['step']),'saved_frames':len(trajectory),'source_frame_unchanged':True,
      'note':'Single short constrained MD trajectory; not an equilibrium or convergence determination.'}
    (folder/'results.json').write_text(json.dumps(results,indent=2))
    (folder/'observations.json').write_text(json.dumps({'steps':[r['step'] for r in hb],
       'mobile_pairs':mobile_counts.tolist(),'all_pairs':counts.tolist(),
       'mobile_rms_nm':rms[:-1].tolist(),'mobile_temperature_K':temperature[:-1].tolist()},indent=2))
    print(name,json.dumps(results,indent=2))
    return results


def plot(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    root=Path(root);fig,axs=plt.subplots(1,3,figsize=(12,3.6),layout='constrained')
    for name,label in [('local_relaxation','Local downhill start'),('existing_relaxation','Existing full relaxation')]:
        row=json.loads((root/name/'observations.json').read_text());t=np.array(row['steps'])/1e6
        axs[0].plot(t,row['mobile_pairs'],label=label)
        axs[1].plot(t,row['mobile_rms_nm'])
        axs[2].plot(t,row['mobile_temperature_K'],alpha=.6)
    axs[0].set(ylabel='Paired mobile bp (of 14)',ylim=(-.5,14.5));axs[0].legend(fontsize=8)
    axs[1].set(ylabel='Mobile RMS displacement (nm)')
    axs[2].set(ylabel='Mobile kinetic temperature (K)')
    for ax in axs:ax.set_xlabel('MD steps (million)')
    fig.savefig(root/'production-comparison.png',dpi=160);plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');p.add_argument('name');p.add_argument('dnanalysis');a=p.parse_args()
    analyze(a.root,a.name,a.dnanalysis)
    if all((Path(a.root)/name/'observations.json').exists() for name in ['local_relaxation','existing_relaxation']):plot(a.root)
