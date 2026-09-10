"""Complete the independent warm-start GPU check at N=36, 381 K."""
import json
from pathlib import Path
import subprocess
import sys
from experiments.peg_chudoba.analyze_chain import analyze


def main():
    root=Path(__file__).parent/'runs'
    for seed,source_seed in [(904,201),(905,202)]:
        directory=root/f'hmc_n36_t381_raw_warm_s{seed}'
        if directory.exists():
            meta=json.loads((directory/'run.json').read_text())
            if meta['status']!='completed':raise RuntimeError(f'Inspect unfinished HMC run: {directory}')
            assert meta['sampling']=='hmc' and meta['n']==36 and meta['temperature']==381 and meta['steps']==100000
        else:
            subprocess.run([sys.executable,'-m','experiments.peg_chudoba.run_chain',
                '--sampling','hmc','--n','36','--temperature','381','--cutoff','raw',
                '--steps','100000','--hmc-steps','500','--dt-fs','2','--seed',str(seed),
                '--initial-run',str(root/f'equilibrium_raw_381_396/n36_t381_s{source_seed}'),
                '--output',str(directory)],check=True)
        print(json.dumps(analyze(directory)),flush=True)


if __name__=='__main__':main()
