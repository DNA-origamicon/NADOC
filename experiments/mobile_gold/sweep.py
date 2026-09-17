"""Native CUDA sweeps; validation parameters are reported, never silently fitted."""
import argparse,json,time
from pathlib import Path
import numpy as np
from experiments.mobile_gold.validate import run_case


def frames(path):
    lines=Path(path).read_text().splitlines();n=next((i for i,l in enumerate(lines[1:],1) if l.startswith('t =')),len(lines))
    return np.array([[[float(x) for x in l.split()] for l in lines[i+3:i+n]] for i in range(0,len(lines)-n+1,n)])


def energy(rows,k):
    a1,a3=rows[:,0,3:6],rows[:,0,6:9];back=-.34*a1+.3408*np.cross(a3,a1)
    arm=3*rows[:,1,3:6]
    delta=rows[:,0,:3]+back-rows[:,1,:3]-arm
    length=np.linalg.norm(delta,axis=1)
    contact=.5*100*np.maximum(3.4-np.linalg.norm(rows[:,0,:3]-rows[:,1,:3],axis=1),0)**2
    return contact+.5*k*(length-.8)**2+.5*np.sum(rows[:,0,9:15]**2,axis=1)+.5*100*np.sum(rows[:,1,9:12]**2,axis=1)+.5*360*np.sum(rows[:,1,12:15]**2,axis=1),length


def main(out):
    out.mkdir(parents=True,exist_ok=False);records=[]
    core=(3.,100.,360.,.01,.0008)
    for dt in (.001,.002,.004):
        for k in (3.,10.,30.):
            name=f'nve_dt{dt}_k{k}'
            final,rec=run_case(out,name,[[4.5,.6,0],[0,0,0]],cores=[core],grafts=[(0,0,3,0,0,.8,k)],steps=10000,dt=dt,sample=100)
            rows=frames(out/name/'trajectory.dat');e,l=energy(rows,k)
            rec.update(dt=dt,k=k,relative_energy_span=float(np.ptp(e)/np.mean(e)),max_linker=float(max(l)),core_displacement=float(np.linalg.norm(final[1,:3])),core_rotation=float(np.arccos(np.clip(final[1,3],-1,1))))
            records.append(rec);(out/'results.json').write_text(json.dumps(records,indent=2));print(rec,flush=True)
    # 32 independent freely diffusing cores: mass/inertia-weighted thermal sampling.
    nc=32;xyz=[[80,80,80]]+[[10*(j%4),10*((j//4)%4),10*(j//16)] for j in range(nc)]
    final,rec=run_case(out,'thermal',xyz,cores=[core]*nc,steps=100000,dt=.002,thermostat='langevin',sample=1000)
    rows=frames(out/'thermal/trajectory.dat')[20:,1:,:]
    temp=.1*296/300
    rec.update(translational_temperature_ratio=float(100*np.mean(rows[:,:,9:12]**2)/temp),rotational_temperature_ratio=float(360*np.mean(rows[:,:,12:15]**2)/temp),max_core_displacement=float(np.max(np.linalg.norm(final[1:,:3]-np.array(xyz[1:]),axis=1))))
    records.append(rec);(out/'results.json').write_text(json.dumps(records,indent=2));print(rec,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output)
