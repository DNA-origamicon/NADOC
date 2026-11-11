"""Check the restart-capable adapter preserves benchmark trajectories exactly."""
from pathlib import Path
import json
import subprocess
from backend.core.oxdna_submodel import installation


def run(output):
    output=Path(output).resolve()
    root=output/'adapter-check';root.mkdir(exist_ok=False)
    old=Path.home()/'.local/share/nadoc/engines/oxdna-submodel/3f2b75086bc1b990/md/oxDNA-submodel'
    new=Path(installation()['md'])
    results=[]
    for case in ('full_mobile','cropped'):
        source=(output/case/'0/input').read_text().replace('steps = 20000','steps = 1000').replace('print_conf_interval = 20000','print_conf_interval = 1000')
        for name,binary in [('before',old),('after',new)]:
            folder=root/case/name;folder.mkdir(parents=True)
            (folder/'input').write_text(source)
            with (folder/'log').open('w') as log:
                subprocess.run([str(binary),'input'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,check=True)
        for file in ('last_conf.dat','energy.dat'):
            assert (root/case/'before'/file).read_bytes()==(root/case/'after'/file).read_bytes(),(case,file)
        results.append({'case':case,'steps':1000,'configuration_and_energy':'byte-identical'})
    (root/'results.json').write_text(json.dumps(results,indent=2));print(results)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
