"""Pair retention and visualization compatibility for the saved-box pilot."""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from experiments.oxdna_submodel.analyze import frames as read_frames

from backend.core.models import Design
from backend.physics.oxdna_interface import assert_topology_matches_design, StaleJobTopologyError


def analyze(root):
    root = Path(root).resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    recipe = json.loads((root/'extraction.json').read_text())
    retained = recipe['retained_source_indices']
    mobile = set(recipe['mobile_output_indices'])
    order = manifest['particle_order']
    paired = {}
    for new,old in enumerate(retained):
        key = order[old]
        if len(key)==3 and not str(key[0]).startswith('__'):
            paired.setdefault(tuple(key[:2]),[]).append(new)
    expected = {tuple(sorted(ids)) for ids in paired.values() if len(ids)==2 and any(i in mobile for i in ids)}
    binary = Path.home()/'.local/share/nadoc/engines/oxdna/current/bin/DNAnalysis'
    report = {'designed_pairs_touching_mobile':len(expected), 'stages':[]}
    for stage in ['relaxation','production']:
        folder = root/stage
        (folder/'analysis_frames.dat').write_text((folder/'conf.dat').read_text()+(folder/'trajectory.dat').read_text())
        text=(folder/'input').read_text().replace('trajectory_file = trajectory.dat','trajectory_file = analysis_frames.dat')
        text+='\nanalysis_data_output_1 = {\n name = hb.dat\n print_every = 1\n col_1 = {\n type = hb_list\n }\n}\n'
        (folder/'analysis.input').write_text(text)
        with (folder/'analysis.log').open('w') as log:
            subprocess.run([str(binary),'analysis.input'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
        frames=[]
        for line in (folder/'hb.dat').read_text().splitlines():
            if line.startswith('# step'):frames.append(set())
            elif line.strip():frames[-1].add(tuple(sorted(map(int,line.split()))))
        counts=[len(p&expected) for p in frames]
        poses=np.array(read_frames(folder/'trajectory.dat',len(retained)))
        initial=read_frames(folder/'conf.dat',len(retained))[0]
        fixed=[i for i in range(len(retained)) if i not in mobile]
        drift=float(np.max(abs(poses[:,fixed,:3]-initial[fixed,:3])))
        axes=float(np.max(abs(poses[:,fixed,3:9]-poses[0,fixed,3:9])))
        momenta=float(np.max(abs(poses[:,fixed,9:15])))
        assert drift==0 and axes==0 and momenta==0 and np.isfinite(poses).all()
        report['stages'].append({'stage':stage,'initial_pairs':counts[0],'final_pairs':counts[-1],'minimum_pairs':min(counts),'counts':counts,
            'fixed_position_drift':drift,'fixed_axis_drift_across_saved_frames':axes,'fixed_momenta_max':momenta,
            'mobile_rms_final_nm':float(np.sqrt(np.mean(np.sum((poses[-1,list(mobile),:3]-initial[list(mobile),:3])**2,axis=1)))*.8518)})
    design=Design.model_validate_json((root/'source_design.json').read_text())
    try:
        assert_topology_matches_design(root/'production/topology.top',design)
    except StaleJobTopologyError as exc:
        report['managed_visualization_compatibility']={'supported':False,'error':str(exc),
          'reason':'Existing job readers require full source nucleotide order; cropped native indices need a dedicated mapping adapter.'}
    else:
        raise AssertionError('Expected a cropped topology to require mapped reading')
    (root/'analysis.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');analyze(p.parse_args().root)
