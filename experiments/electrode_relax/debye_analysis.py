"""Finite-cell PB and Debye diagnostics for explicitly selected electrode trajectories.

Standalone scientific analysis; never changes qualification thresholds or job status.
"""
import json
from pathlib import Path
import numpy as np
from scipy.constants import epsilon_0, elementary_charge as E, Boltzmann as KB
from scipy.integrate import solve_bvp
from scipy.optimize import least_squares
from backend.core.dcd_fast import read_layout,read_frame
from backend.core.md_charge import parse_psf_atoms


def bjerrum_nm(eps=78.3,temperature=300.):
    return E*E/(4*np.pi*epsilon_0*eps*KB*temperature)*1e9


def debye_nm(concentration_per_nm3,eps=78.3,temperature=300.):
    return float(1/np.sqrt(8*np.pi*bjerrum_nm(eps,temperature)*concentration_per_nm3))


def closed_pb(length,area,number,sigma_e_nm2,eps=78.3,temperature=300.,stern=.3):
    """Canonical symmetric 1:1 PB, equal/opposite plate charges, fixed ion counts.

    Half-cell integral of c0*cosh(u) enforces N of EACH species in the full cell.
    u=e*potential/kBT; x in nm. Uniform continuum dielectric, point ions.
    """
    mid=length/2; x=np.linspace(stern,mid,121);lb=bjerrum_nm(eps,temperature)
    slope=4*np.pi*lb*abs(sigma_e_nm2);c=number/(area*(length-2*stern))
    y=np.array([slope*(x-mid)/2,np.full_like(x,slope/2),number/(2*area)*(x-stern)/(mid-stern)])
    def fun(x,y,p):
        c0=np.exp(p[0]);u=np.clip(y[0],-40,40)
        return np.array([y[1],8*np.pi*lb*c0*np.sinh(u),c0*np.cosh(u)])
    def bc(a,b,p):return np.array([a[1]-slope,b[0],a[2],b[2]-number/(2*area)])
    result=solve_bvp(fun,bc,x,y,p=[np.log(c)],tol=1e-7,max_nodes=5000)
    if not result.success:raise ValueError(result.message)
    c0=float(np.exp(result.p[0]));grid=np.linspace(stern,length-stern,801)
    left=result.sol(np.minimum(grid,length-grid))[0];u=np.where(grid<=mid,left,-left)
    na=c0*np.exp(-u);cl=c0*np.exp(u)
    # Numerical conservation is an independent check of the closed-cell boundary conditions.
    assert abs(np.trapezoid(na,grid)*area/number-1)<2e-5
    assert abs(np.trapezoid(cl,grid)*area/number-1)<2e-5
    return dict(x_nm=grid.tolist(),u=u.tolist(),na_per_nm3=na.tolist(),cl_per_nm3=cl.tolist(),center_per_nm3=c0,debye_nm=debye_nm(c0,eps,temperature),eps=eps,stern_nm=stern,midplane_field_fraction=float(result.sol(mid)[1]/slope) if slope else None)


def fit_ion_ratio(counts,x,length,exclude=.6):
    """Fit an odd finite-gap Debye shape plus offset; report boundaries, not fake precision."""
    na,cl=np.asarray(counts,dtype=float);mask=(x>=exclude)&(x<=length-exclude)&(na>=5)&(cl>=5)
    if mask.sum()<8:return {'valid':False,'reason':'Too few populated interior bins'}
    u=.5*np.log((cl+.5)/(na+.5));weight=1/np.sqrt(.25*(1/(na+.5)+1/(cl+.5)))
    def model(p):return p[0]*np.sinh((x[mask]-length/2)/p[1])+p[2]
    result=least_squares(lambda p:(model(p)-u[mask])*weight[mask],[.1,.7,0],bounds=([0,.15,-3],[5,5,3]),max_nfev=2000)
    lam=float(result.x[1]);pred=model(result.x);rmse=float(np.sqrt(np.mean((pred-u[mask])**2)))
    return dict(valid=bool(result.success),lambda_nm=lam,amplitude=float(result.x[0]),offset=float(result.x[2]),rmse_dimensionless=rmse,at_bound=bool(lam<.151 or lam>4.99),exclude_nm=exclude,interior_bins=int(mask.sum()))


def planar_potential(grid_nm,positions_nm,charges_e,area_nm2):
    """Exact planar charge integration with zero field below a neutral isolated slab.

    Prefix sums evaluate sum(q * (z-z_i) * H(z-z_i)) without histogram dipole error.
    Potential is in volts, using epsilon_r=1 for all explicit atomic charges.
    """
    order=np.argsort(positions_nm);z=np.asarray(positions_nm)[order];q=np.asarray(charges_e)[order]
    index=np.searchsorted(z,grid_nm,side='right')
    total=np.r_[0,np.cumsum(q)];moment=np.r_[0,np.cumsum(q*z)]
    return -E*1e9/(epsilon_0*area_nm2)*(np.asarray(grid_nm)*total[index]-moment[index])


def frame_times_ns(job, layout, manifest):
    """Use persisted integrator metadata, cross-checked against the DCD header."""
    spec = next(row for row in manifest['segments'] if row['name'] == job['segment'])
    dt = float(spec['timestep_fs'])
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError('Invalid segment timestep')
    if 'timestep_fs' in job and not np.isclose(float(job['timestep_fs']), dt):
        raise ValueError('Campaign and segment timestep disagree')
    if layout.delta_ps and not np.isclose(layout.delta_ps / layout.nsavc * 1000, dt, rtol=1e-5):
        raise ValueError('DCD header and segment timestep disagree')
    return float(job['start_time_ns'])+(layout.istart+np.arange(layout.n_frames)*layout.nsavc)*dt/1e6


def physical_block_frames(times, duration_ns=.3):
    cadence = float(np.median(np.diff(times)))
    if not np.isfinite(cadence) or cadence <= 0:
        raise ValueError('Trajectory needs a finite increasing physical time axis')
    if not np.allclose(np.diff(times),cadence,rtol=1e-4,atol=1e-8):
        raise ValueError('Analyze constant-cadence series separately before pooling')
    return max(1, round(duration_ns/cadence))


def selected_frames(package, segment, manifest, job):
    """Stream final restart lineage without retaining complete coordinates in RAM."""
    from backend.core.namd_peg_evidence import continuation_epochs
    selected = {}
    for _, _, path, start in continuation_epochs(package, segment):
        layout = read_layout(path)
        times = frame_times_ns(job, layout, manifest)
        selected = {step: value for step,value in selected.items() if step <= start}
        for i in range(layout.n_frames):
            step = layout.istart+i*layout.nsavc
            if step > start:
                selected[step]=(path,layout,i,times[i])
    for step in sorted(selected):
        path,layout,index,time = selected[step]
        yield time, read_frame(path,layout,index)[0]


def correlation_diagnostic(values, cadence_ns):
    """Descriptive first-positive-lobe IAT; not proof of equilibrium/independence."""
    from scipy.signal import correlate
    v=np.asarray(values,dtype=float);v=v-v.mean();n=len(v)
    if n<4 or np.dot(v,v)==0:
        return {'effective_frames':None,'reason':'Insufficient fluctuations'}
    ac=correlate(v,v,mode='full',method='fft')[n-1:]/np.arange(n,0,-1)
    ac/=ac[0];negative=np.flatnonzero(ac[1:]<=0)
    stop=int(negative[0])+1 if len(negative) else max(2,n//4)
    stop=min(stop,max(2,n//4))
    g=max(1.,1+2*ac[1:stop].sum())
    return dict(statistical_inefficiency=float(g),effective_frames=float(n/g),
        correlation_time_ns=float(cadence_ns*g/2),positive_lobe_cutoff_ns=float(stop*cadence_ns),
        note='Descriptive estimate; shared initialization and slow drift can invalidate nominal effective sample counts.')


def analyze(campaign,output=None,start_ns=.24,end_ns=None):
    campaign=Path(campaign);output=Path(output or campaign);output.mkdir(parents=True,exist_ok=True)
    jobs=json.loads((campaign/'jobs.json').read_text()); histories=[];times=[];charges_hist=[];potential_history=[]
    first=Path(jobs[0]['package']);m=json.loads((first/'manifest.json').read_text());spec=m['two_electrodes'];axis=spec['normal_axis'];low,high=np.array(spec['normal_bounds_A'])/10;length=high-low;area=np.prod([v for i,v in enumerate(spec['cell_nm']) if i!=axis]);atoms=parse_psf_atoms((first/'system.psf').read_text());q=np.array([a.charge for a in atoms])
    groups=[[i for i,a in enumerate(atoms) if a.resname==r] for r in ('SOD','CLA')]
    edges=np.linspace(low,high,round(length/.1)+1);x=(edges[:-1]+edges[1:])/2-low;fine=np.linspace(0,spec['cell_nm'][axis],round(spec['cell_nm'][axis]/.025)+1)
    for job in jobs:
        if not job.get('status'):continue  # a milestone uses only finished chunks
        p=Path(job['package']);path=p/'output'/f"{job['segment']}.dcd"
        if not path.exists():continue
        manifest=json.loads((p/'manifest.json').read_text())
        for frame_time, coordinates in selected_frames(p,job['segment'],manifest,job):
            assert len(coordinates)==len(atoms)
            xyz=coordinates/10
            times.append(frame_time)
            histories.append([np.histogram(xyz[g,axis],edges)[0] for g in groups])
            charges_hist.append(np.histogram(xyz[:,axis],fine,weights=q)[0])
            potential_history.append(planar_potential(fine,xyz[:,axis],q,area))
    h=np.asarray(histories);times=np.asarray(times);qh=np.asarray(charges_hist)
    assert len(times) and np.all(np.diff(times)>0)
    np.savez_compressed(output/'profile_samples.npz',times_ns=times,ion_histograms=h,charge_histograms=qh,ion_edges_nm=edges-low,charge_edges_nm=fine-low)
    # All subsequent estimates use only the equilibrating trajectory after the 240 ps packing check.
    use=(times>start_ns+1e-8)&(times<=float(end_ns)+1e-8 if end_ns is not None else True)
    if use.sum()<20:return {'frames':len(times),'reason':'Need more post-packing frames'}
    last=float(times[use][-1]);hh=h[use];n=len(hh);counts=hh.sum(axis=0);conc=hh.mean(axis=0)/(area*np.diff(edges));central=(x>=length/2-.4)&(x<=length/2+.4);c0=float(conc[:,central].mean())
    models=[closed_pb(length,area,len(groups[0]),abs(spec['working_charge_e'])/area,eps,300.,stern) for eps in (78.3,100.) for stern in (.3,.5)]
    fits=[fit_ion_ratio(counts,x,length,d) for d in (.5,.6,.8)]
    interior=(x>=.5)&(x<=length-.5)
    for model in models:
        pred=np.array([np.interp(x,model['x_nm'],model[key]) for key in ('na_per_nm3','cl_per_nm3')])
        model['interior_concentration_rmse_M']=float(np.sqrt(np.mean((pred[:,interior]-conc[:,interior])**2))/.602214076)
    half=x<length/2
    compensation=float((hh[:,0,half].sum(axis=1)-hh[:,1,half].sum(axis=1)).mean()/abs(spec['working_charge_e']))
    block=physical_block_frames(times[use], .3) # Always 300 ps, independent of saved-frame cadence
    blocks=[hh[i:i+block] for i in range(0,n-block+1,block)]
    rng=np.random.default_rng(20260914);bootstrap=[]
    if len(blocks)>=4:
        for _ in range(300):
            sample=np.concatenate([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))])
            fit=fit_ion_ratio(sample.sum(axis=0),x,length)
            if fit.get('valid'):bootstrap.append(fit['lambda_nm'])
    # Microscopic potential includes all explicit-water and electrode charges, epsilon_r=1.
    mean_q=qh[use].mean(axis=0)/area
    potential=np.asarray(potential_history)[use].mean(axis=0);potential-=np.interp((low+high)/2,fine,potential)
    odd_potential=(potential-np.interp(low+high-fine,fine,potential))/2
    block_odd=[]
    for start in range(0,n-block+1,block):
        phi=np.asarray(potential_history)[use][start:start+block].mean(axis=0)
        block_odd.append((phi-np.interp(low+high-fine,fine,phi))/2)
    odd_sem=np.std(block_odd,axis=0,ddof=1)/np.sqrt(len(block_odd)) if len(block_odd)>1 else np.zeros_like(odd_potential)
    np.savez_compressed(output/'microscopic_potential.npz',distance_nm=fine-low,potential_V=potential,antisymmetric_potential_V=odd_potential,antisymmetric_block_sem_V=odd_sem,antisymmetric_block_potential_V=np.asarray(block_odd))
    # Same physical-duration half-window drift, avoiding cadence-dependent comparisons.
    windows=[]
    for duration in (.6,1.2,2.4):
        sel=(times>last-duration+1e-8)&use
        if sel.sum()<20 or duration>times[use][-1]-times[use][0]+.011:continue
        sample=h[sel];a,b=np.array_split(sample,2);aa=a.sum(axis=0);bb=b.sum(axis=0);drift=np.max(abs(np.cumsum(aa/aa.sum(axis=1)[:,None]-bb/bb.sum(axis=1)[:,None],axis=1)),axis=1)
        windows.append(dict(duration_ns=duration,frames=int(sel.sum()),na_cl_drift=drift.tolist()))
    result=dict(frames=n,end_ns=last,ions_per_species=len(groups[0]),area_nm2=area,gap_nm=length,nominal_salt_mM=spec['salt_mM'],realized_global_mM=1000*len(groups[0])/(area*length*.602214076),center_ionic_strength_mM=c0/.602214076*1000,center_na_cl_mM=(conc[:,central].mean(axis=1)/.602214076*1000).tolist(),negative_wall_halfcell_ionic_compensation=compensation,classical_lambda_from_center_nm={str(eps):debye_nm(c0,eps) for eps in (78.3,100.)},pb=models,ratio_fits=fits,windows=windows,block_frames=block,complete_blocks=len(blocks),bootstrap_lambda_quantiles_nm=np.quantile(bootstrap,[.025,.5,.975]).tolist() if bootstrap else None,bootstrap_bound_fraction=float(np.mean(np.array(bootstrap)>4.99)) if bootstrap else None,net_charge_e_per_nm2=float(mean_q.sum()),limitations=['One starting configuration per analysis; finite closed electrolyte inventory and fixed-charge abstract walls.','Dielectric 78.3 and 100 are comparison assumptions, not measured model permittivity.','Ion-ratio potential assumes Boltzmann behavior; microscopic potential independently includes water charges.', 'The antisymmetric microscopic potential removes the even interface background; no neutral-wall control was subtracted.','Block bootstrap uses 300 ps blocks; independence and long-time stationarity remain to be checked.'])
    result['analysis_start_ns']=start_ns
    result['analysis_end_ns']=last
    cadence=float(np.median(np.diff(times[use])))
    center_series=hh[:,:,central].sum(axis=(1,2))/(2*area*np.diff(edges)[0]*central.sum()*.602214076)*1000
    compensation_series=(hh[:,0,half].sum(axis=1)-hh[:,1,half].sum(axis=1))/abs(spec['working_charge_e'])
    result['sampling_diagnostics']={'frame_interval_ps':cadence*1000,
        'central_salt':correlation_diagnostic(center_series,cadence),
        'ionic_compensation':correlation_diagnostic(compensation_series,cadence),
        'physical_blocks':[]}
    for duration in (.3,.6,1.2):
        frames=physical_block_frames(times[use],duration)
        rows=[]
        for index in range(0,n-frames+1,frames):
            sample=hh[index:index+frames]
            rows.append(dict(start_ns=float(times[use][index]),end_ns=float(times[use][index+frames-1]),
                center_mM=float(center_series[index:index+frames].mean()),
                compensation=float(compensation_series[index:index+frames].mean()),
                fit=fit_ion_ratio(sample.sum(axis=0),x,length)))
        result['sampling_diagnostics']['physical_blocks'].append(dict(duration_ns=duration,blocks=rows))
    mid_mask=np.abs(fine-(low+high)/2)<=.4+1e-8
    fields=np.array([-np.polyfit(fine[mid_mask],phi[mid_mask],1)[0]*1000 for phi in block_odd])
    result['central_field_mV_nm']=dict(value=float(-np.polyfit(fine[mid_mask],odd_potential[mid_mask],1)[0]*1000),block_values=fields.tolist(),block_sem=float(np.std(fields,ddof=1)/np.sqrt(len(fields))) if len(fields)>1 else None,fit_width_nm=.8,note='Slope over central 0.8 nm, not a pointwise field; block SEM assumes independent blocks.')
    result['microscopic_potential_method']='Exact planar integration of atomic charges; no spatial charge binning'
    (output/'debye_analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(2,2,figsize=(12,9),layout='constrained')
    for i,label in enumerate(('Na','Cl')):
        axs[0,0].plot(x,conc[i]/.602214076,label=f'MD {label}')
        for model in models[:1]:axs[0,0].plot(model['x_nm'],np.array(model['na_per_nm3' if i==0 else 'cl_per_nm3'])/.602214076,'--',label=f'PB {label}, ε=78.3')
    axs[0,0].set(xlabel='Distance from negative electrode (nm)',ylabel='Concentration (M)',title='Ion distributions and canonical PB');axs[0,0].legend()
    u=.5*np.log((counts[1]+.5)/(counts[0]+.5));populated=(counts>=5).all(axis=0);axs[0,1].plot(x[populated],u[populated]*KB*300/E*1000,'o',label='MD ion-ratio estimate')
    for model in (models[0],models[2]):axs[0,1].plot(model['x_nm'],np.array(model['u'])*KB*300/E*1000,label=f"PB ε={model['eps']}")
    axs[0,1].set(xlabel='Distance (nm)',ylabel='Potential relative to midplane (mV)',title='Continuum / ion-ratio comparison');axs[0,1].legend()
    axs[1,0].plot(fine-low,odd_potential*1000,label='All-charge MD: antisymmetric part')
    axs[1,0].fill_between(fine-low,(odd_potential-odd_sem)*1000,(odd_potential+odd_sem)*1000,alpha=.2,label='300 ps block SEM')
    for model in (models[0],models[2]):axs[1,0].plot(model['x_nm'],np.array(model['u'])*KB*300/E*1000,'--',label=f"PB ε={model['eps']}")
    axs[1,0].set(xlim=(-.3,length+.3),xlabel='Distance (nm)',ylabel='Potential relative to midplane (mV)',title='Explicit-water polarization included; odd component');axs[1,0].legend()
    inset=axs[1,0].inset_axes([.3,.1,.4,.3])
    inset.plot(fine-low,odd_potential*1000)
    inset.fill_between(fine-low,(odd_potential-odd_sem)*1000,(odd_potential+odd_sem)*1000,alpha=.2)
    for model in (models[0],models[2]):inset.plot(model['x_nm'],np.array(model['u'])*KB*300/E*1000,'--')
    inset.set(xlim=(.6,length-.6),ylim=(-30,30));inset.tick_params(labelsize=7);inset.grid(alpha=.2)
    for i,label in enumerate(('Na','Cl')):
        center_hist=h[:,i,central].sum(axis=1)/(area*np.diff(edges)[0]*central.sum()*.602214076)
        axs[1,1].plot(times[use],center_hist[use],alpha=.55,label=label)
    axs[1,1].set(xlabel='Time (ns)',ylabel='Central concentration (M)',title='Bulk-like central 0.8 nm');axs[1,1].legend()
    for ax in axs.ravel():ax.grid(alpha=.2)
    fig.suptitle(f"Electrode screening diagnostic through {last:.2f} ns; {len(groups[0])} ions/species")
    fig.savefig(output/'debye_panel.png',dpi=160);fig.savefig(output/'debye_panel.pdf')
    return {k:v for k,v in result.items() if k!='pb'}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('campaign',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--start-ns',type=float,default=.24);parser.add_argument('--end-ns',type=float);args=parser.parse_args()
    print(json.dumps(analyze(args.campaign,args.output,args.start_ns,args.end_ns),indent=2))
