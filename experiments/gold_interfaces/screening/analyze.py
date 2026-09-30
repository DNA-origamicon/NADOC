"""Apply the established Debye diagnostics to explicit-Au controls without pass scores."""
import json
import numpy as np
from scipy.stats import t as student_t
from backend.core.dcd_fast import read_layout, read_frame
from backend.core.md_charge import parse_psf_atoms
from experiments.electrode_relax.debye_analysis import fit_ion_ratio, debye_nm, planar_potential, closed_pb, correlation_diagnostic
from experiments.electrode_relax.water_mode_check import mode_temperatures
from experiments.gold_interfaces.screening.campaign import ROOT, REPO


def fit_report(counts,x,length,charge):
    result=fit_ion_ratio(counts,x,length)
    result['optimizer_converged']=result.pop('valid',False)
    result['screening_validated']=False
    result['interpretation']='Exploratory charged-wall fit; requires stationarity, identifiable response and uncertainty' if charge else 'Neutral null control: any fitted length is not evidence of electrode screening'
    return result


def analyze(p):
    manifest=json.loads((p/'manifest.json').read_text());run=json.loads((p/'pilot.run.json').read_text())
    if run['status']!='complete':raise ValueError('Incomplete native trajectory')
    atoms=parse_psf_atoms((p/'system.psf').read_text());q=np.array([a.charge for a in atoms]);mass=np.array([a.mass for a in atoms])
    groups={key:np.array([i for i,a in enumerate(atoms) if a.atomtype==key]) for key in ('SOD','CLA','OT','NAUI')}
    waters=groups['OT'][:,None]+np.arange(3);waterids=waters.ravel();ionids=np.r_[groups['SOD'],groups['CLA']]
    low,high=manifest['geometry']['liquid_bounds_nm'];length=high-low;area=np.prod(manifest['cell_nm'][:2]);mid=(low+high)/2
    edges=np.linspace(low,high,61);x=(edges[1:]+edges[:-1])/2-low;grid=np.linspace(low,high,241)
    coord=p/'output/pilot.dcd';vel=p/'output/pilot.veldcd';layout=read_layout(coord);vl=read_layout(vel)
    assert layout.n_frames==vl.n_frames
    assert np.isclose(layout.delta_ps/layout.nsavc*1000,1.,rtol=1e-5)
    first=int(next(s for s in (p/'pilot.conf').read_text().splitlines() if s.startswith('firsttimestep')).split()[1])
    times=(layout.istart+np.arange(layout.n_frames)*layout.nsavc-first)/1e6
    counts=[];watercounts=[];mode=[];potentials=[];densities=[];outside=[];orient=[]
    for i in range(layout.n_frames):
        xyz=read_frame(coord,layout,i)[0]/10
        counts.append([np.histogram(xyz[groups[key],2],edges)[0] for key in ('SOD','CLA')])
        watercounts.append(np.histogram(xyz[groups['OT'],2],edges)[0])
        densities.append(np.count_nonzero(np.abs(xyz[groups['OT'],2]-mid)<.4)/(area*.8))
        outside.append([int(np.count_nonzero((xyz[groups[k],2]<=low)|(xyz[groups[k],2]>=high))) for k in ('OT','SOD','CLA')])
        vv=read_frame(vel,vl,i)[0];mode.append(list(mode_temperatures(mass[waters],vv[waters]).values()))
        dip=(xyz[waters[:,1]]+xyz[waters[:,2]])/2-xyz[waters[:,0]];dip/=np.linalg.norm(dip,axis=1)[:,None]
        orient.append(np.histogram(xyz[groups['OT'],2],edges,weights=dip[:,2])[0])
        parts=[]
        for ids in (np.arange(len(atoms)),groups['NAUI'],ionids,waterids):
            phi=planar_potential(grid,xyz[ids,2],q[ids],area);phi-=np.interp(mid,grid,phi);parts.append(phi)
        assert np.allclose(parts[0],sum(parts[1:]),atol=1e-8)
        potentials.append(parts)
    h=np.asarray(counts);wh=np.asarray(watercounts);modes=np.asarray(mode);rho=np.asarray(densities);phi=np.asarray(potentials)
    sigma=manifest['screening']['surface_charge_e_nm2'];charge=sigma*area
    # Predeclared window, irrespective of the trajectory's apparent agreement.
    use=(times>.1+1e-9)&(times<=.3+1e-9)
    central=(x>=length/2-.4)&(x<=length/2+.4);half=x<length/2
    c=h[use].mean(axis=0)/(area*np.diff(edges));center=c[:,central].mean(axis=1);c0=center.mean()
    excess=h[:,0,half].sum(axis=1)-h[:,1,half].sum(axis=1)
    fits=[dict(exclusion_nm=d,**fit_report(h[use].sum(axis=0),x,length,charge)) if d==.6 else dict(exclusion_nm=d,**fit_ion_ratio(h[use].sum(axis=0),x,length,d)) for d in (.5,.6,.8)]
    for fit in fits:
        if 'valid' in fit:fit['optimizer_converged']=fit.pop('valid')
        fit['screening_validated']=False
    blockrows=[]
    for lo in (0.,.1,.2):
        sel=(times>lo+1e-9)&(times<=lo+.1+1e-9)
        blockrows.append(dict(start_ns=lo,end_ns=lo+.1,density_nm3=float(rho[sel].mean()),
            halfcell_excess_e=float(excess[sel].mean()),fit=fit_report(h[sel].sum(axis=0),x,length,charge)))
    blockmeans=[rho[(times>start+1e-9)&(times<=start+.02+1e-9)].mean() for start in np.arange(.1,.3,.02)]
    result=dict(case=p.name,model=manifest['screening'],n_atoms=len(atoms),water_count=len(waters),
        frame_count=len(times),duration_ns=float(times[-1]),analysis_window_ns=[.1,.3],
        area_nm2=float(area),gap_nm=length,temperature_K=300.,timestep_fs=1.,
        water_density_nm3=float(rho[use].mean()),water_density_conditional_95_halfwidth=float(student_t.ppf(.975,len(blockmeans)-1)*np.std(blockmeans,ddof=1)/np.sqrt(len(blockmeans))),
        water_translation_rotation_K=modes[use].mean(axis=0).tolist(),center_na_cl_mM=(center/.602214076*1000).tolist(),
        center_ionic_strength_mM=float(c0/.602214076*1000),geometric_salt_mM=64/(area*length*.602214076)*1000,
        classical_lambda_assumed_dielectric_nm={str(eps):debye_nm(c0,eps,300.) for eps in (78.3,100.)},
        halfcell_ionic_excess_e=float(excess[use].mean()),compensation=float(excess[use].mean()/charge) if charge else None,
        fits=fits,blocks_100ps=blockrows,maximum_outside_compartment=np.max(outside,axis=0).tolist(),
        complete_300ps_blocks_in_analysis=0,bootstrap_interval=None,
        ionic_excess_correlation=correlation_diagnostic(excess[use],.001),
        physical_validation=False,constant_potential=False,
        limitation='Only 200 ps analyzed, less than one historical 300 ps bootstrap block. No screening confidence interval or equilibration verdict.')
    near=[]
    for cutoff in (.3,.5,.6,.8,1.):
        left=x<cutoff;right=x>length-cutoff
        left_excess=float((h[use,0][:,left].sum(axis=1)-h[use,1][:,left].sum(axis=1)).mean())
        right_excess=float((h[use,1][:,right].sum(axis=1)-h[use,0][:,right].sum(axis=1)).mean())
        near.append(dict(cutoff_nm=cutoff,lower_Na_minus_Cl_e=left_excess,upper_Cl_minus_Na_e=right_excess,
            interpretation='Geometric charge inventory; cutoff is not a validated Stern-plane location'))
    result['near_surface_ionic_charge']=near
    midmask=np.abs(grid-mid)<=.4+1e-9
    result['central_field_mV_nm']=float(-np.polyfit(grid[midmask],phi[use,0].mean(axis=0)[midmask],1)[0]*1000)
    result['central_field_note']='Slope across central 0.8 nm of the all-charge mean potential; no independent-block confidence interval'
    orientation=np.divide(np.asarray(orient)[use].sum(axis=0),wh[use].sum(axis=0),out=np.full(len(x),np.nan),where=wh[use].sum(axis=0)>0)
    np.savetxt(p/'screening_profiles.csv',np.c_[x,wh[use].mean(axis=0)/(area*np.diff(edges)),c.T/.602214076,orientation],
        delimiter=',',header='distance_nm,water_nm3,Na_M,Cl_M,mean_water_dipole_cos_z',comments='')
    pb=closed_pb(length,area,64,sigma,78.3,300.,stern=.6)
    result['canonical_pb']=pb
    np.savez_compressed(p/'screening_samples.npz',times_ns=times,ion_counts=h,water_counts=wh,density_nm3=rho,mode_K=modes,
        x_nm=x,grid_nm=grid-low,potential_components_V=phi,orientation_sums=orient,halfcell_excess_e=excess)
    result['source_hashes']={str(f.relative_to(p)):__import__('hashlib').sha256(f.read_bytes()).hexdigest() for f in (p/'system.psf',p/'manifest.json',p/'pilot.conf',p/'pilot.run.json')}
    (p/'screening.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def old_reference():
    source=REPO/'.development-artifacts/electrode_remote_40ns_20260914/runpod/through_40ns/debye_analysis.json'
    value=json.loads(source.read_text())
    result=dict(source=str(source),source_sha256=__import__('hashlib').sha256(source.read_bytes()).hexdigest(),
        **{k:value[k] for k in ('area_nm2','gap_nm','ions_per_species','center_ionic_strength_mM','ratio_fits','bootstrap_lambda_quantiles_nm','negative_wall_halfcell_ionic_compensation')})
    cache=source.parents[1]/'screening_frame_cache.npz';z=np.load(cache)
    times=z['times'];h=z['h'];x=np.arange(.05,6,.1);central=(x>=2.6)&(x<=3.4);half=x<3
    windows=[]
    for lo,hi,label in ((.1,.3,'matched early 200 ps'),(20.,40.,'late 20 ns')):
        mask=(times>lo+1e-9)&(times<=hi+1e-9);sample=h[mask]
        windows.append(dict(label=label,window_ns=[lo,hi],frames=int(mask.sum()),
            fit=fit_report(sample.sum(axis=0),x,6.,16.),
            center_ionic_strength_mM=float(sample[:,:,central].mean()/(64*.1*.602214076)*1000),
            compensation=float((sample[:,0,half].sum(axis=1)-sample[:,1,half].sum(axis=1)).mean()/16)))
    result['matched_windows']=windows
    result['cache_sha256']=__import__('hashlib').sha256(cache.read_bytes()).hexdigest()
    return result

if __name__=='__main__':
    rows=[]
    for p in sorted(ROOT.glob('*_*')):
        run=p/'pilot.run.json'
        if run.exists() and json.loads(run.read_text())['status']=='complete':
            rows.append(analyze(p))
    out=ROOT/'comparison.json';out.write_text(json.dumps(dict(gold=rows,historical_abstract_wall=old_reference(),physical_validation=False),indent=2)+'\n')
    print([(r['case'],r['water_density_nm3'],r['compensation'],r['fits'][1].get('lambda_nm')) for r in rows])
