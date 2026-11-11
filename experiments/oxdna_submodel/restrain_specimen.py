"""Follow a saved-box downhill pilot with explicitly remapped pairing restraints."""
import argparse
import json
import re
from pathlib import Path
import shutil

import numpy as np
from experiments.oxdna_submodel.analyze import frames
from experiments.oxdna_submodel.production import sha
from experiments.oxdna_submodel.sweep_shell import native


def run(root):
    root=Path(root).resolve()
    original=json.loads((root/'manifest.json').read_text())
    recipe=json.loads((root/'extraction.json').read_text())
    parent=Path(original['job_directory'])
    mapping={old:new for new,old in enumerate(recipe['retained_source_indices'])}
    mobile=set(recipe['mobile_source_indices'])
    text=(parent/'forces.txt').read_text()
    blocks=re.findall(r'\{([^{}]*)\}',text,re.S)
    kept=[]
    for block in blocks:
        fields=dict(re.findall(r'(\w+)\s*=\s*(\S+)',block))
        if fields['type']!='mutual_trap':raise ValueError('Only pair traps supported in this pilot')
        a,b=int(fields['particle']),int(fields['ref_particle'])
        if a not in mapping or b not in mapping:
            if a in mobile or b in mobile:raise ValueError('A mobile restraint partner was cropped out')
            continue
        block=re.sub(r'(?m)^(particle|ref_particle)\s*=\s*(\d+)',lambda m:f'{m[1]} = {mapping[int(m[2])]}',block)
        kept.append('{'+block+'}')
    output=root/'restrained'
    output.mkdir(exist_ok=False)
    for name in ['manifest.json','extraction.json','source_design.json']:
        shutil.copy2(root/name,output/name)
    (output/'pair_traps.txt').write_text('\n'.join(kept))
    (output/'restraint_recipe.json').write_text(json.dumps({
        'source':str(parent/'forces.txt'),'source_sha256':sha(parent/'forces.txt'),
        'source_blocks':len(blocks),'retained_blocks':len(kept),
        'policy':'Keep and remap both retained endpoints; reject any missing mobile endpoint partner.',
        'seed_configuration':str(root/'relaxation/last_conf.dat'),
        'seed_sha256':sha(root/'relaxation/last_conf.dat')},indent=2))
    base=(root/'production/input').read_text()
    md=Path('.development-artifacts/oxdna-submodel-production-20261109/engine-matched/oxDNA-submodel').resolve()
    conf=root/'relaxation/last_conf.dat'
    results=[]
    for stage in ['relaxation','production']:
        folder=output/stage
        folder.mkdir()
        for name in ['topology.top','mobile.txt']:shutil.copy2(root/'production'/name,folder/name)
        shutil.copy2(conf,folder/'conf.dat')
        settings=base.replace('seq_dep_file = '+str(Path('.development-artifacts/oxdna-submodel-production-20261109/existing_relaxation/oxDNA2_average_sequence_parameters.txt').resolve()),
                              'seq_dep_file = '+str(parent/'oxDNA2_average_sequence_parameters.txt'))
        if stage=='relaxation':
            settings=settings.replace('steps = 100000','steps = 1000000').replace('print_conf_interval = 1000','print_conf_interval = 10000')
            settings=settings.replace('max_backbone_force = 50.0','max_backbone_force = 5.0').replace('max_backbone_force_far = 100.0','max_backbone_force_far = 10.0')
            settings+=f'\nexternal_forces = true\nexternal_forces_file = {output/"pair_traps.txt"}\n'
        (folder/'input').write_text(settings)
        seconds=native(folder,md,timeout=900)
        initial=frames(folder/'conf.dat',len(mapping))[0]
        output_frames=frames(folder/'trajectory.dat',len(mapping))
        fixed=[i for i in range(len(mapping)) if i not in recipe['mobile_output_indices']]
        assert all(np.isfinite(f).all() and np.max(abs(f[fixed,:3]-initial[fixed,:3]))==0 for f in output_frames)
        result={'stage':stage,'seconds':seconds,'frames':len(output_frames),
                'input_sha256':sha(folder/'input'),'binary_sha256':sha(md),
                'configuration_source':str(conf),'configuration_sha256':sha(conf)}
        results.append(result);(output/'results.json').write_text(json.dumps(results,indent=2))
        print(result,flush=True)
        conf=folder/'last_conf.dat'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');run(p.parse_args().root)
