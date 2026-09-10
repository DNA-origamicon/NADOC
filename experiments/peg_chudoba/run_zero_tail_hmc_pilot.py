"""Bounded large-solution HMC timing/acceptance probes after the GPU chain check."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def main():
    root=Path(__file__).parent/'runs';waiting=(root/'zero_tail_gpu_n36_t381/s703').resolve()
    out=root/'zero_tail_hmc_solution_pilot';out.mkdir(parents=True,exist_ok=True)
    source=(root/'eos_zero_tail_n135_t294/n135_t294_p1_s401').resolve()
    plan=[dict(dt_fs=dt,hmc_steps=steps,steps=100,seed=seed,n=135,chains=108,temperature=294,
               pressure_kpa=1,cutoff='zero_tail',sampling='hmc',name=f'dt{dt:g}_s{seed}')
          for dt,steps,seed in [(2,500,811),(1,1000,812),(.5,2000,813)]]
    planfile=out/'plan.json'
    if planfile.exists():
        if json.loads(planfile.read_text())['allocations']!=plan:raise ValueError('Existing pilot plan differs')
    else:planfile.write_text(json.dumps(dict(allocations=plan,source=str(source),wait_for_run=str(waiting),
        purpose='100 proposal acceptance/timing probes per timestep, not calibration or equilibrium estimates',
        trajectory_length='1 ps integration per HMC proposal; accepted proposal sequence has no physical-time interpretation'),indent=2)+'\n')
    while True:
        live=[]
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():continue
            try:
                if (proc/'comm').read_text().strip()=='oxDNA' and (proc/'cwd').resolve()==waiting:live.append(proc.name)
            except OSError:pass
        if not live:break
        print(f'Waiting for existing GPU chain engine PID {live}',flush=True);time.sleep(30)
    if json.loads((waiting/'run.json').read_text())['status']!='completed':raise ValueError('Inspect GPU predecessor before continuing')
    prior=json.loads((source/'run.json').read_text())
    if prior['status']!='completed' or prior['cutoff']!='zero_tail':raise ValueError('Invalid warm source')
    results=[]
    for entry in plan:
        directory=out/entry['name']
        if not directory.exists():
            command=[sys.executable,'-m','experiments.peg_chudoba.run_solution','--initial-run',str(source),'--output',str(directory)]
            for key,value in entry.items():
                if key!='name':command+=['--'+key.replace('_','-'),str(value)]
            subprocess.run(command,check=True)
        meta=json.loads((directory/'run.json').read_text())
        if meta['status']!='completed' or any(meta.get(k)!=v for k,v in entry.items() if k!='name'):
            raise ValueError('Existing pilot incomplete or mismatched')
        last=(directory/'energy.dat').read_text().splitlines()[-1]
        accept=float(re.search(r'HMC_accept=([\d.eE+-]+)',last).group(1))
        row=dict(directory=str(directory),dt_fs=entry['dt_fs'],hmc_steps=entry['hmc_steps'],
                 proposals=entry['steps'],acceptance_fraction=accept,elapsed_seconds=meta['elapsed_seconds'],
                 accepted_proposals_per_second=accept*entry['steps']/meta['elapsed_seconds'],
                 status='Small timing/acceptance probe; mixing not assessed')
        results.append(row);(out/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(row),flush=True)


if __name__=='__main__':main()
