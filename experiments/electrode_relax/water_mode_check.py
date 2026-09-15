"""Read completed restart snapshots; quantify rigid-water mode temperatures."""
import argparse
import json
import struct
import time
from pathlib import Path

import numpy as np
from backend.core.md_charge import parse_psf_atoms

# NAMD common.h: internal velocities are A/AKMA and BOLTZMANN is kcal/mol/K.
BOLTZMANN = .001987191


def mode_temperatures(mass, velocities):
    mass=np.asarray(mass);v=np.asarray(velocities)
    total=mass.sum(axis=1)
    com=np.sum(mass[:,:,None]*v,axis=1)/total[:,None]
    translation=.5*np.sum(total[:,None]*com**2)
    rotation=.5*np.sum(mass[:,:,None]*(v-com[:,None,:])**2)
    scale=2/(3*len(mass)*BOLTZMANN)
    return dict(translational_K=float(translation*scale),rotational_K=float(rotation*scale))


def main():
    p=argparse.ArgumentParser();p.add_argument('campaign',type=Path);a=p.parse_args()
    target=a.campaign/'water_modes.jsonl';seen=set();cache={}
    if target.exists():
        seen={(r['job_id'],r['step']) for r in map(json.loads,target.read_text().splitlines())}
    deadline=time.monotonic()+7200
    while time.monotonic()<deadline:
        try:jobs=json.loads((a.campaign/'jobs.json').read_text())
        except json.JSONDecodeError:time.sleep(1);continue
        for job in jobs:
            pkg=Path(job['package']);stem=job['segment'];xsc=pkg/'output'/f'{stem}.restart.xsc';vel=pkg/'output'/f'{stem}.restart.vel'
            if not xsc.exists() or not vel.exists():continue
            try:
                before=xsc.read_bytes();step=int(before.splitlines()[-1].split()[0])
                if (job['job_id'],step) in seen or vel.stat().st_mtime_ns<xsc.stat().st_mtime_ns:continue
                data=vel.read_bytes()
                if xsc.read_bytes()!=before:continue
                n=struct.unpack('<i',data[:4])[0]
                if len(data)!=4+n*24:continue
                v=np.frombuffer(data,dtype='<f8',offset=4).reshape(n,3)
                if not np.isfinite(v).all():continue
                if job['job_id'] not in cache:
                    atoms=parse_psf_atoms((pkg/'system.psf').read_text());mass=np.array([x.mass for x in atoms]);ox=np.array([i for i,x in enumerate(atoms) if x.atomtype=='OT']);ids=ox[:,None]+np.arange(3)
                    assert all([atoms[i+j].atomtype for j in range(3)]==['OT','HT','HT'] for i in ox)
                    cache[job['job_id']]=(mass,ids)
                mass,ids=cache[job['job_id']]
                row=dict(job_id=job['job_id'],series=job['series'],timestep_fs=job['timestep_fs'],step=step,
                    time_ns=job['start_time_ns']+step*job['timestep_fs']/1e6,waters=len(ids),
                    total_kinetic_kcal_mol=float(.5*np.sum(mass[:,None]*v*v)),**mode_temperatures(mass[ids],v[ids]))
                with target.open('a') as f:f.write(json.dumps(row)+'\n')
                seen.add((job['job_id'],step))
            except (OSError,ValueError,IndexError,struct.error):continue
        if len(jobs)==10 and jobs[-1].get('status'):return
        time.sleep(2)


if __name__=='__main__':main()
