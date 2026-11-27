"""Sequential native 2D smoke and cold pilot; run only after other pilots finish."""
import subprocess
import sys
from pathlib import Path
root=Path('.development-artifacts/equilibrium-tm-20261121').resolve()
binary=Path.home()/'.local/share/nadoc/engines/oxdna/8028cf33b3cba12992b771156085fa54879f50cd-upstream-physics-v3-vmmc-v1/bin/oxDNA'
base=[sys.executable,'-m','tools.oxdna_tm_research.proposals','--job-dir','/media/jojo/Archive/NADOC/oxDNA_jobs/c795362c46bc','--unbound-conf','.development-artifacts/gpu-umbrella/inputs/unbound.dat','--binary',str(binary),'--target-halfwidth','1','--translation','.5','--rotation','1','--maxclust','12','--distance-split','1','--cadence','1000']
for name,seed,tuning,equil,steps,minutes in [('distance_smoke',511100,0,10000,10000,1),('distance',611100,8,200000,1000000,12)]:
    cmd=base+['--output',str(root/name),'--seed',str(seed),'--tuning-rounds',str(tuning),'--training-walkers','4','--equil-steps',str(equil),'--block-steps',str(steps),'--blocks','1','--minutes',str(minutes)]
    with (root/(name+'.log')).open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=minutes*60+20)
    print(name,'complete',flush=True)
