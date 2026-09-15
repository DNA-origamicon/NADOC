"""Time-resolved densities and mode temperatures; no universal pass thresholds."""
import json
import re
import warnings
import numpy as np
import MDAnalysis as mda
from scipy.stats import t as student_t
from scipy.spatial import cKDTree
from backend.core.md_charge import parse_psf_atoms
from experiments.electrode_relax.water_mode_check import mode_temperatures
import campaign as c

def blocks(time,values,start,block_ps):
    time=np.asarray(time);values=np.asarray(values)
    ids=np.floor((time-start)/block_ps).astype(int)
    end=time[-1]+.5*np.median(np.diff(time))
    means=[float(np.mean(values[(ids==i)&(time>=start)])) for i in range(int((end-start)/block_ps+1e-6))
           if np.any((ids==i)&(time>=start))]
    sem=float(np.std(means,ddof=1)/np.sqrt(len(means))) if len(means)>1 else None
    return dict(block_ps=block_ps,block_means=means,mean=float(np.mean(means)) if means else None,
        conditional_95_halfwidth=float(student_t.ppf(.975,len(means)-1)*sem) if sem is not None else None,
        note='Conditional on stationary, independent block means; not an equilibrium certificate')

def analyze(p,prefix):
    m=json.loads((p/'manifest.json').read_text());atoms=parse_psf_atoms((p/'system.psf').read_text())
    first_step=int(re.search(r'firsttimestep (\d+)',(p/f'{prefix}.conf').read_text())[1])
    duration=json.loads((p/f'{prefix}.run.json').read_text())['steps']/1000
    types=np.array([a.atomtype for a in atoms]);mass=np.array([a.mass for a in atoms])
    ids={s:np.flatnonzero(types==s) for s in ('OT','NAUI','SOD','CLA')};ox=ids['OT'];wid=ox[:,None]+np.arange(3)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        u=mda.Universe(str(p/'system.psf'),str(p/'output'/f'{prefix}.dcd'))
        vu=mda.Universe(str(p/'system.psf'),str(p/'output'/f'{prefix}.veldcd'),format='DCD')
    kind=m['geometry']['kind'];series=[]
    if kind=='slab':
        lo,hi=m['geometry']['liquid_bounds_nm'];edges=np.linspace(0,(hi-lo)/2,61)
        vols=2*np.prod(m['cell_nm'][:2])*np.diff(edges)
    elif kind=='nanoparticle':
        edges=np.linspace(0,min(m['cell_nm'])/2,81);vols=4*np.pi/3*np.diff(edges**3)
    hist=np.zeros((3,len(edges)-1)) if kind!='bulk' else None
    orient=np.zeros(len(edges)-1) if hist is not None else None
    nprofiles=0
    for ts in u.trajectory:
        xyz=ts.positions.astype(float)/10;cell=ts.dimensions[:3].astype(float)/10
        if kind=='bulk':
            vol=np.prod(cell);rho=len(ox)/vol;na=len(ids['SOD'])/vol/.602214076*1000;cl=len(ids['CLA'])/vol/.602214076*1000
            cosine=np.nan;outside=0
        else:
            center=xyz[ids['NAUI']].mean(axis=0)
            distances={};cos=None
            for j,s in enumerate(('OT','SOD','CLA')):
                if kind=='slab':
                    z=xyz[ids[s],2];distances[s]=np.minimum(z-lo,hi-z)
                    select=abs(z-(lo+hi)/2)<.5;vol=np.prod(cell[:2])
                else:
                    dr=xyz[ids[s]]-center;dr-=np.round(dr/cell)*cell
                    distances[s]=np.linalg.norm(dr,axis=1)
                    inner=m['geometry']['radius_nm']+1.;outer=min(cell)/2
                    select=(distances[s]>inner)&(distances[s]<outer);vol=4*np.pi/3*(outer**3-inner**3)
                density=select.sum()/vol
                if s=='OT': rho=density
                elif s=='SOD': na=density/.602214076*1000
                else: cl=density/.602214076*1000
            dip=(xyz[ox+1]+xyz[ox+2])/2-xyz[ox];dip/=np.linalg.norm(dip,axis=1)[:,None]
            if kind=='slab':
                cos=dip[:,2]*np.where(xyz[ox,2]<(lo+hi)/2,1.,-1.)
                outside=int(np.sum(distances['OT']<0))
            else:
                dr=xyz[ox]-center;dr-=np.round(dr/cell)*cell
                cos=np.sum(dip*dr/np.linalg.norm(dr,axis=1)[:,None],axis=1);outside=0
            cosine=float(np.mean(cos))
            if ts.frame>=len(u.trajectory)//2:
                for j,s in enumerate(('OT','SOD','CLA')): hist[j]+=np.histogram(distances[s],edges)[0]
                orient+=np.histogram(distances['OT'],edges,weights=cos)[0];nprofiles+=1
        series.append([ts.time,rho,na,cl,cosine,outside])
    series=np.array(series);series[:,0]-=first_step/1000
    modes=[]
    # NAMD Output::output_veldcdfile writes internal A/AKMA floats without the
    # PDBVELFACTOR conversion used for PDB/IMD velocities.
    for ts in vu.trajectory:
        modes.append([ts.time,*mode_temperatures(mass[wid],ts.positions.astype(float)[wid]).values()])
    modes=np.array(modes);modes[:,0]-=first_step/1000
    start=duration/2
    report=dict(case=p.name,prefix=prefix,kind=kind,frames=len(series),duration_ps=duration,
      n_water=len(ox),n_na=len(ids['SOD']),n_cl=len(ids['CLA']),
      density_blocks=[blocks(series[:,0],series[:,1],start,b) for b in (10.,20.,50.)],
      early_density=float(series[series[:,0]<start,1].mean()),late_density=float(series[series[:,0]>=start,1].mean()),
      late_na_mM=float(series[series[:,0]>=start,2].mean()),late_cl_mM=float(series[series[:,0]>=start,3].mean()),
      late_translational_K=float(modes[modes[:,0]>=start,1].mean()),late_rotational_K=float(modes[modes[:,0]>=start,2].mean()),
      maximum_waters_outside_slit=int(series[:,5].max()),mode_blocks={k:blocks(modes[:,0],modes[:,i],start,20.) for k,i in [('translation',1),('rotation',2)]})
    if kind!='bulk':
        cell=np.array(m['cell_nm']);xyz0=mda.Universe(str(p/'system.pdb')).atoms.positions[ids['NAUI']]/10
        samples=np.random.default_rng(997).uniform(size=(100000,3))*cell
        tree=cKDTree(np.mod(xyz0,cell),boxsize=cell);dist=tree.query(samples)[0]
        available=np.ones(len(samples),dtype=bool)
        if kind=='slab':available&=(samples[:,2]>lo)&(samples[:,2]<hi)
        volumes={s:float(np.mean(available&(dist>=c.gold_model.contact_distance_nm(s,6.)))*np.prod(cell)) for s in ('OT','SOD','CLA')}
        report['operational_accessible_volume_nm3']=volumes
        report['accessible_volume_MC_standard_error_nm3']={s:float(np.sqrt((v/np.prod(cell))*(1-v/np.prod(cell))/len(samples))*np.prod(cell)) for s,v in volumes.items()}
        report['accessible_volume_definition']='Monte Carlo volume outside initial Au pair exclusion at 6 kcal/mol; preparation convention, not thermodynamic volume'
        report['geometric_liquid_volume_nm3']=float(np.prod(cell[:2])*(hi-lo) if kind=='slab' else np.prod(cell))
        report['inventory_correction_waters']=None
        mid=(edges[1:]+edges[:-1])/2
        profile=np.c_[mid,(hist/(vols*nprofiles)).T,np.divide(orient,hist[0],out=np.full_like(orient,np.nan),where=hist[0]>0)]
        np.savetxt(p/f'{prefix}_profiles.csv',profile,delimiter=',',header='distance_nm,water_nm3,Na_nm3,Cl_nm3,cos_dipole',comments='')
    np.savetxt(p/f'{prefix}_series.csv',series,delimiter=',',header='time_ps,density_nm3,Na_mM,Cl_mM,mean_cos,waters_outside',comments='')
    np.savetxt(p/f'{prefix}_modes.csv',modes,delimiter=',',header='time_ps,translational_K,rotational_K',comments='')
    (p/f'{prefix}_analysis.json').write_text(json.dumps(report,indent=2))
    print(p.name,report['late_density'],report['late_translational_K'],report['late_rotational_K'],flush=True)
    return report

if __name__=='__main__':
    for p in sorted(c.ROOT.iterdir()):
        if p.is_dir():
            for r in p.glob('*.run.json'):
                if json.loads(r.read_text()).get('status')=='complete' and json.loads(r.read_text()).get('steps',0)>0:
                    prefix=r.name.removesuffix('.run.json')
                    if not (p/f'{prefix}_analysis.json').exists():analyze(p,prefix)
