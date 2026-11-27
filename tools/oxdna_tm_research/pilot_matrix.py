"""Sequential bounded proposal pilots, at most four native CPU workers."""
import subprocess
import sys
from pathlib import Path

root=Path('.development-artifacts/equilibrium-tm-20261121').resolve()
binary=Path.home()/'.local/share/nadoc/engines/oxdna/8028cf33b3cba12992b771156085fa54879f50cd-upstream-physics-v3-vmmc-v1/bin/oxDNA'
for name,translation,rotation,cap,seed in [('medium',.5,1.,16,311100),('large',1.,2.,16,411100)]:
    cmd=[sys.executable,'-m','tools.oxdna_tm_research.proposals','--job-dir','/media/jojo/Archive/NADOC/oxDNA_jobs/c795362c46bc','--unbound-conf','.development-artifacts/gpu-umbrella/inputs/unbound.dat','--binary',str(binary),'--output',str(root/name),'--minutes','7','--block-steps','1000000','--blocks','1','--seed',str(seed),'--target-halfwidth','1','--translation',str(translation),'--rotation',str(rotation),'--maxclust',str(cap)]
    with (root/(name+'.log')).open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=440)
    print(name,'complete',flush=True)
