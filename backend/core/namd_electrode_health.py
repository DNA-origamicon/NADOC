"""Additional fixed-compartment evidence required before electrode stage skipping."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from backend.core.md_charge import parse_psf_atoms, DNA_RESNAMES
from backend.core.namd_peg_evidence import segment_evidence


def validation_failure(report):
    """Explain which measured gate prevented qualification, without hiding drift."""
    if report.get('passed'):
        return ''
    reasons=[]
    if report.get('reason'):
        reasons.append(report['reason'])
    tolerance=report.get('tolerance',.1)
    for species,drift in zip(('water','Na','Cl','Mg'),report.get('profile_drift',[])):
        if drift>tolerance+1e-12:
            reasons.append(f'{species} profile drift {drift:.3f} exceeds {tolerance:.3f}')
    if report.get('confined') is False:
        reasons.append('water/ions crossed the confinement tolerance')
    if report.get('bulk_reference_validated') is False:
        density=report.get('bulk_water_density_nm3')
        reference=report.get('reference_water_density_nm3')
        reasons.append(f'bulk water density {density} nm^-3 does not match reference {reference} nm^-3 within 5%')
    if report.get('peg_stable') is False:
        reasons.append('PEG chain size has not stabilized')
    return '; '.join(reasons) or 'No passing electrode validation report is available'


def profile_stationarity(histograms, minimum_frames=20, tolerance=.1, window_frames=60):
    """Recent cumulative-profile drift, retaining raw histogram TV for diagnosis.

    The cumulative statistic measures the largest change in the fraction of a
    species between the wall and any sampled plane. Unlike summed binwise noise,
    it remains useful for sparse ion profiles. This is an effect-size heuristic,
    not an independent-sample KS p-value or proof of equilibrium.
    """
    h=np.asarray(histograms,dtype=float)
    if h.ndim!=3 or len(h)<minimum_frames or not np.isfinite(h).all() or np.any(h<0):
        return {'passed':False,'reason':'Insufficient finite profile samples','frames':len(h)}
    total_frames=len(h)
    h=h[-max(minimum_frames,window_frames):]
    a,b=h[:len(h)//2].mean(axis=0),h[len(h)//2:].mean(axis=0)
    totals=(a.sum(axis=1)+b.sum(axis=1))/2
    tv=np.divide(np.abs(a-b).sum(axis=1),2*totals,out=np.zeros_like(totals),where=totals>0)
    normalized=[]
    for values in (a,b):
        total=values.sum(axis=1,keepdims=True)
        normalized.append(np.divide(values,total,out=np.zeros_like(values),where=total>0))
    drift=np.max(np.abs(np.cumsum(normalized[0]-normalized[1],axis=1)),axis=1)
    observations=np.minimum(h[:len(h)//2].sum(axis=(0,2)),h[len(h)//2:].sum(axis=(0,2)))
    sufficient=bool(np.all((totals==0)|(observations>=200)))
    return {'passed':bool(sufficient and np.all(drift<=tolerance+1e-12)),
        'profile_drift':drift.tolist(),'total_variation_drift':tv.tolist(),
        'profile_statistic':'maximum_cumulative_fraction_difference',
        'sampling_sufficient':sufficient,'observations_per_half':observations.tolist(),
        'minimum_observations_per_half':200,
        **({'reason':'Insufficient profile observations per half'} if not sufficient else {}),
        'frames':len(h),'tolerance':tolerance,
        'total_frames':total_frames,'discarded_initial_frames':total_frames-len(h),'window_frames':window_frames}


def electrode_skip_check(package, segment):
    package=Path(package)
    manifest=json.loads((package/'manifest.json').read_text())
    spec=manifest.get('two_electrodes')
    if not spec:return {'passed':True,'applicable':False}
    try:
        # Chunks are checkpoints of the same physical rung, not independent
        # equilibration experiments. Retain its evidence across checkpoint boundaries.
        prefix=segment.rsplit('_p',1)[0]
        names=[]
        for row in manifest.get('segments',[]):
            name=row['name']
            if name.rsplit('_p',1)[0]==prefix:names.append(name)
            if name==segment:break
        if segment not in names:names=[segment]
        samples=[];sample_times=[];elapsed=0.
        for name in names:
            evidence,_,_=segment_evidence(package,name,spec['n_atoms'])
            row=next((row for row in manifest.get('segments',[]) if row['name']==name),{})
            dt=float(row.get('timestep_fs',2.))
            if not np.isfinite(dt) or dt<=0:raise ValueError('Invalid electrode evidence timestep')
            ordered=sorted(evidence)
            samples.extend(evidence[step] for step in ordered)
            sample_times.extend(elapsed+step*dt/1e6 for step in ordered)
            elapsed+=float(row.get('steps',max(ordered,default=0)))*dt/1e6
        atoms=parse_psf_atoms((package/manifest['files']['topology']).read_text())
        groups=[[i for i,a in enumerate(atoms) if a.atomtype=='OT' or (a.resname=='MGH' and 15<a.mass<17)],
                [i for i,a in enumerate(atoms) if a.resname=='SOD'],
                [i for i,a in enumerate(atoms) if a.resname=='CLA'],
                [i for i,a in enumerate(atoms) if a.atomname=='MG']]
        solute=[i for i,a in enumerate(atoms) if a.resname in DNA_RESNAMES | {'PEGM'} and a.mass>2]
        chains={seg:[j for j,b in enumerate(atoms) if b.segid==seg and b.mass>2] for seg in {a.segid for a in atoms if a.resname=='PEGM'}}
        axis=spec['normal_axis'];low,high=spec['normal_bounds_A'];edges=np.linspace(low,high,21)
        histories=[];confined=True;densities=[];polymer=[]
        for sample in samples:
            xyz=sample['xyz'] if isinstance(sample,dict) and 'xyz' in sample else sample[0]
            xyz=np.asarray(xyz)
            if xyz.shape!=(spec['n_atoms'],3) or not np.isfinite(xyz).all():raise ValueError('Invalid electrode trajectory coordinates')
            densities.append(bulk_water_density(xyz/10,groups[0],solute,spec['cell_nm'],axis,low/10,high/10))
            polymer.append([float(np.sqrt(np.mean(np.sum((xyz[g]-xyz[g].mean(axis=0))**2,axis=1)))) for g in chains.values()])
            histories.append([np.histogram(xyz[g,axis],edges)[0] for g in groups])
            confined &= all(np.all((xyz[g,axis]>=low-.5)&(xyz[g,axis]<=high+.5)) for g in groups)
        # A fixed 600 ps window keeps higher output frequency from shortening
        # the stationarity question to a different physical experiment.
        window=max(20,sum(t>sample_times[-1]-.6+1e-10 for t in sample_times)) if sample_times else 60
        result=profile_stationarity(histories,window_frames=window)
        result['requested_window_ns']=.6
        result['observed_window_span_ns']=float(sample_times[-1]-sample_times[-min(len(sample_times),window)]) if sample_times else 0.
        result['evidence_segments']=names
        result['confined']=bool(confined)
        result['passed'] &= bool(confined)
        result['note']='Stationarity is necessary, not proof of correct density or Debye screening.'
        # Solvent loading needs a measured reference. Never silently turn absence into a pass.
        reference=manifest.get('electrode_validation',{}).get('bulk_reference_result',{})
        expected=reference.get('water_number_density_nm3',0)
        recent_densities=densities[-window:]
        density=float(np.mean(recent_densities)) if recent_densities and all(v is not None for v in recent_densities) else None
        result['bulk_water_density_nm3']=density
        result['reference_water_density_nm3']=expected
        result['density_tolerance_fraction']=.05
        result['bulk_reference_validated']=bool(expected>0 and density is not None and abs(density/expected-1)<=.05)
        result['passed'] &= result['bulk_reference_validated']
        result['peg_stable']=True
        if chains:
            values=np.asarray(polymer[-window:])
            result['peg_stable']=bool(len(values)>=20 and np.all(np.abs(values[:len(values)//2].mean(axis=0)-values[len(values)//2:].mean(axis=0))/np.maximum(values.mean(axis=0),1e-9)<.05))
            result['passed'] &= result['peg_stable']
    except (ValueError,KeyError,IndexError,TypeError,OSError) as exc:
        result={'passed':False,'reason':str(exc)}
    result['failure_summary']=validation_failure(result)
    (package/'output'/f'{segment}.electrode-health.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def bulk_water_density(xyz, water, solute, cell, axis, low, high):
    """Voxel estimate of a bulk-like region >=1 nm from walls and solute heavy atoms."""
    lo=np.zeros(3);hi=np.asarray(cell,dtype=float).copy();lo[axis]=low+1;hi[axis]=high-1
    if hi[axis]<=lo[axis]:return None
    counts=np.maximum(1,np.ceil((hi-lo)/.3).astype(int));step=(hi-lo)/counts
    grid=np.array(np.meshgrid(*[lo[i]+(np.arange(counts[i])+.5)*step[i] for i in range(3)],indexing='ij')).reshape(3,-1).T
    waters=xyz[water];use=(waters[:,axis]>=lo[axis])&(waters[:,axis]<hi[axis])
    if solute:
        tree=cKDTree(np.mod(xyz[solute],cell),boxsize=cell)
        accessible=tree.query(grid)[0]>=1
        use &= tree.query(np.mod(waters,cell))[0]>=1
    else:accessible=np.ones(len(grid),dtype=bool)
    volume=float(accessible.sum()*np.prod(step))
    return float(use.sum()/volume) if volume>=5 else None
