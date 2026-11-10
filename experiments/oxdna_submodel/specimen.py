"""Read a user specimen's saved region and run isolated cropped native pilots.

The source job/design is read-only. Native topology extraction is a derived
simulation artifact, with its exact source and extraction recipe retained.
"""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from backend.api.routes_oxdna import _seed_geometry
from backend.core.models import Design
from backend.physics.oxdna_interface import _strand_nucleotide_order, resolved_nuc_map
from experiments.oxdna_submodel.analyze import frames
from experiments.oxdna_submodel.production import sha
from experiments.oxdna_submodel.shell import crop
from experiments.oxdna_submodel.sweep_shell import native
from scripts.agent_structure_guard import audit


def run(source, parent, output):
    source, parent, output = map(lambda p: Path(p).resolve(), (source, parent, output))
    design = Design.model_validate_json((parent/'design.json').read_text())
    proof = audit(design)
    selection = json.loads((parent/'submodel_selection.json').read_text())
    order = _strand_nucleotide_order(design)
    geometry = resolved_nuc_map(design, _seed_geometry(design))
    points = np.array([geometry[k]['backbone_position'] for k in order])
    top, conf, recipe = crop((parent/'topology.top').read_text(),
                            (parent/'conf.dat').read_text(), points,
                            selection['box'], selection['box']['shell_nm'])
    output.mkdir(parents=True, exist_ok=False)
    for name in ['design.json', 'submodel_selection.json', 'job.json', 'stages_spec.json']:
        shutil.copy2(parent/name, output/('source_'+name))
    (output/'extraction.json').write_text(json.dumps(recipe, indent=2))
    manifest = {'source':str(source), 'source_sha256':sha(source),
                'job_id':parent.name, 'job_directory':str(parent), 'selection':selection,
                'source_audit':proof, 'source_files':{p.name:sha(p) for p in parent.iterdir() if p.is_file()},
                'particle_order':[list(k) for k in order],
                'mobile':len(recipe['mobile_output_indices']),
                'retained':len(recipe['retained_source_indices']),
                'source_particles':len(order),
                'warning':'Isolated native experiments, not completed managed-app jobs.'}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k:manifest[k] for k in ['mobile','retained','source_particles']}), flush=True)
    old = Path('.development-artifacts/oxdna-submodel-duplex-20261109').resolve()
    production = Path('.development-artifacts/oxdna-submodel-production-20261109').resolve()
    mc = Path.home()/'.local/share/nadoc/engines/oxdna/current/bin/oxDNA'
    md = production/'engine-matched/oxDNA-submodel'
    mobile = recipe['mobile_output_indices']
    fixed = [i for i in range(manifest['retained']) if i not in set(mobile)]
    results = []
    for stage in ['relaxation','production']:
        folder = output/stage
        folder.mkdir()
        (folder/'topology.top').write_text(top)
        (folder/'conf.dat').write_text(conf if stage=='relaxation' else (output/'relaxation/last_conf.dat').read_text())
        (folder/'mobile.txt').write_text('\n'.join(map(str,mobile))+'\n')
        if stage=='relaxation':
            settings = (old/'quench/input').read_text().replace('T = 20C','T = 296K')
            settings += '\nmax_backbone_force = 5\nmax_backbone_force_far = 10\n'
            binary = mc
        else:
            settings = (production/'existing_relaxation/input').read_text().replace('steps = 1000000','steps = 100000')
            settings = settings.replace('print_conf_interval = 10000','print_conf_interval = 1000').replace('dt = 0.003','dt = 0.002')
            binary = md
        # No parent mutual traps are silently reindexed or discarded: this
        # pilot explicitly uses downhill MC, then capped Brownian MD, no traps.
        (folder/'input').write_text(settings)
        seconds = native(folder, binary)
        n = manifest['retained']
        initial = frames(folder/'conf.dat',n)[0]
        saved = frames(folder/'trajectory.dat',n)
        last = frames(folder/'last_conf.dat',n)[0]
        assert saved and all(np.isfinite(f).all() for f in [*saved,last])
        drift = max(float(np.max(abs(f[fixed,:3]-initial[fixed,:3]))) for f in [*saved,last])
        assert drift == 0
        result = {'stage':stage,'seconds':seconds,'frames':len(saved),'fixed_position_drift':drift,
                  'mobile_rms_final_nm':float(np.sqrt(np.mean(np.sum((last[mobile,:3]-initial[mobile,:3])**2,axis=1)))*.8518),
                  'executable':str(binary),'binary_sha256':sha(binary),'input_sha256':sha(folder/'input')}
        results.append(result)
        (output/'results.json').write_text(json.dumps(results,indent=2))
        print(result,flush=True)
    assert sha(source)==manifest['source_sha256']
    assert all(sha(parent/name)==digest for name,digest in manifest['source_files'].items())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['source','parent','output']:p.add_argument(key)
    a=p.parse_args();run(a.source,a.parent,a.output)
