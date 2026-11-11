"""Read-only source-job reproducer and negative control for frozen FENE bonds."""
import json
from pathlib import Path
import re
import subprocess
import numpy as np
from backend.core.oxdna_submodel import installation
from backend.core.oxdna_submodel_runner import Projector


def run(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    source=Path('workspace/oxdna_jobs/52d968f5e2cc/1_production/submodel').resolve()
    engines=installation();original=(source/'input.txt').read_text()
    recipe=json.loads((source/'extraction.json').read_text())
    trials={}
    for case in ('original','fixed_shell','mobile_bond_control'):
        folder=output/case;folder.mkdir()
        text=re.sub(r'(?m)^steps = .*','steps = 10000',original)
        text=re.sub(r'(?m)^print_conf_interval = .*','print_conf_interval = 100',text)
        text=re.sub(r'(?m)^print_energy_every = .*','print_energy_every = 100',text)
        if case!='original':
            text=text.replace('interaction_type = DNA2','interaction_type = SubmodelDNA2')
            text+=f"\nplugin_search_path = {engines['plugins']}\n"
        if case=='mobile_bond_control':
            (folder/'mobile.txt').write_text((source/'mobile.txt').read_text()+'129\n')
            text=re.sub(r'(?m)^submodel_mobile_file = .*',f"submodel_mobile_file = {folder/'mobile.txt'}",text)
        (folder/'input.txt').write_text(text)
        with (folder/'log').open('w') as log:
            result=subprocess.run([engines['md'],'input.txt'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=90)
        trials[case]={'exit_code':result.returncode,'log_tail':(folder/'log').read_text()[-1400:]}
        if case=='fixed_shell':
            assert result.returncode==0,trials[case]
            projector=Projector(source,folder,recipe,(source/'context.dat').read_text())
            projector.expand((folder/'last_conf.dat').read_text())
            frames=(folder/'trajectory.dat').read_text().splitlines();size=len(recipe['retained_source_indices'])+3
            for i in range(0,len(frames),size):projector.expand('\n'.join(frames[i:i+size])+'\n')
            trials[case]['validated_fixed_frames']=len(frames)//size
            assert np.isfinite(np.loadtxt(folder/'energy.dat')).all()
        else:assert result.returncode!=0
    (output/'results.json').write_text(json.dumps(trials,indent=2));print(trials)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
