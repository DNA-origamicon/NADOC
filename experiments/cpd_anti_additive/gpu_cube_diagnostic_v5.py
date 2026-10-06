"""Bounded cubic-box GPU-resident qualification; never launches full context validation."""
import argparse
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

import numpy as np
from scipy.spatial import cKDTree

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry, NAMD
from experiments.cpd_anti_additive.solvated_engine_v3 import geometry_passed
from experiments.cpd_anti_additive.gpu_longbox_validation_v3 import observables
from backend.core.dcd_fast import read_layout, read_frame, cell_to_dimensions

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-gpu-cube-diagnostic-v5'
ASSEMBLY=read(ROOT/'assembly.json')
N,NW,NSOL=ASSEMBLY['cases'][0]['atoms'],ASSEMBLY['waters'],3043
MASS=ASSEMBLY['cases'][0]['mass_Da']


def authorize():
    plan=read(ROOT/'diagnostic_plan.json')
    assert plan['diagnostic_only'] and not plan['full_campaign_admitted']
    checked(plan['legacy_hold'])
    assert time.time()<plan['context_deadline_epoch'] and time.time()<plan['deadline_epoch']
    return plan


def box_from_xsc(path):
    row = np.loadtxt(path)
    assert row.ndim == 1 and len(row) >= 13 and np.isfinite(row).all()
    basis = row[1:10].reshape(3, 3); box = np.diag(basis)
    assert np.all(box > 28) and np.max(abs(basis-np.diag(box))) < 1e-8
    return box, row


def config(case, coor, first=0, seed=41017, cp=None, resident=True, npt=False, stride=1000):
    box = read(ROOT/'assembly.json')['box_A']; folder = ROOT/case
    lines = [f'structure {(folder/"system.psf").resolve()}', f'coordinates {(folder/"system.pdb").resolve()}',
             f'binCoordinates {Path(coor).resolve()}', 'paraTypeCharmm on']
    names = ['par_all36_na.prm','par_all36_cgenff.prm'] + (['anti_dna_overlay.prm'] if case == 'anti' else []) + ['water_ions.prm']
    lines += [f'parameters {(ROOT/"forcefield"/name).resolve()}' for name in names]
    lines += ['exclude scaled1-4','oneFourScaling 1','cutoff 12','switching on','switchdist 10',
              'vdwForceSwitching on','pairlistdist 14','margin 2','PME yes','PMETolerance 0.000001',
              'PMEGridSizeX 144','PMEGridSizeY 144','PMEGridSizeZ 144','wrapAll off',
              'rigidBonds all','useSettle on','rigidTolerance 0.00000001','rigidIterations 200',
              'timestep 2','nonbondedFreq 1','fullElectFrequency 1','stepspercycle 10',
              'GPUresident on' if resident else 'bondedGPU 0','outputName result',
              f'DCDfreq {stride}','DCDunitcell yes',f'XSTfreq {stride}', 'restartfreq 50000','restartsave yes','restartname checkpoint',
              'outputEnergies 500' if stride == 500 else 'outputEnergies 1000', 'outputTiming 1000',
              'binaryoutput yes','binaryrestart yes',f'firsttimestep {first}',f'seed {seed}',
              'langevin on','langevinTemp 300','langevinDamping 1','langevinHydrogen off',
              'useGroupPressure yes','useFlexibleCell no','useConstantArea no',
              'LangevinPiston '+('on' if npt else 'off')]
    if npt:
        lines += ['LangevinPistonTarget 1.01325','LangevinPistonPeriod 200',
                  'LangevinPistonDecay 100','LangevinPistonTemp 300']
    if cp:
        lines += [f'binVelocities {Path(str(cp)+".vel").resolve()}', f'extendedSystem {Path(str(cp)+".xsc").resolve()}']
    else:
        lines += [f'cellBasisVector1 {box[0]} 0 0',f'cellBasisVector2 0 {box[1]} 0',
                  f'cellBasisVector3 0 0 {box[2]}','cellOrigin '+' '.join(str(v/2) for v in box),'temperature 0']
    return '\n'.join(lines)+'\n'


def physical(case, x, box, quantized=False):
    x = np.asarray(x, dtype=float); assert x.shape == (N,3) and np.isfinite(x).all()
    g = geometry(ROOT/case, x); sol = x[:NSOL]; tree = cKDTree(sol)
    gap = min(float(tree.query(sol+np.array(t)*box)[0].min()) for t in itertools.product([-1,0,1], repeat=3) if any(t))
    w = x[NSOL:NSOL+3*NW].reshape(-1,3,3); d = w[:,1:]-w[:,:1]; d -= np.rint(d/box)*box
    err = abs(np.linalg.norm(d, axis=2)-.9572)
    half = .5*abs(np.spacing(w.astype(np.float32)).astype(float)) if quantized else np.zeros_like(w)
    excess = float(np.maximum(0, err-np.linalg.norm(half[:,1:]+half[:,:1], axis=2)).max())
    oo = float(cKDTree(w[:,0]%box, boxsize=box).query(w[:,0]%box,k=2)[0][:,1].min())
    return dict(geometry=g,image_clearance_A=gap,min_water_OO_A=oo,max_OH_error_beyond_storage_A=excess,
                passed=bool(geometry_passed(g) and gap>12 and oo>2 and excess<1e-5))


def void_witness(x, box):
    axes = [np.arange(0,v,2.) for v in box]
    points = np.array(np.meshgrid(*axes,indexing='ij')).reshape(3,-1).T
    ds = cKDTree(np.asarray(x,dtype=float)%box,boxsize=box).query(points)[0]; idx = int(ds.argmax())
    return dict(sampled_max_nearest_atom_A=float(ds[idx]),point_A=points[idx].tolist(),grid_spacing_A=2.,
                interpretation='Spatial witness, not a universal physical acceptance threshold.')


def checkpoint(folder, step):
    for ext in ['coor','vel']:
        assert np.array_equal(read_binary(folder/f'result.{ext}',N),read_binary(folder/f'result.restart.{ext}',N))
    box,row = box_from_xsc(folder/'result.restart.xsc')
    assert row[0] == step and np.array_equal(row,np.loadtxt(folder/'result.xsc'))
    return box,[source(folder/f'result.restart.{e}') for e in ['coor','vel','xsc']]



def regular_checkpoints(folder, first, last):
    records=[]
    for step in range((first//50000+1)*50000,last+1,50000):
        cp=folder/f'checkpoint.{step}'
        box,row=box_from_xsc(Path(str(cp)+'.xsc'));assert row[0]==step
        for ext in ['coor','vel']:
            array=read_binary(Path(str(cp)+'.'+ext),N)
            assert array.shape==(N,3) and np.isfinite(array).all()
        records.append(dict(step=step,files=[source(Path(str(cp)+'.'+ext)) for ext in ['coor','vel','xsc']]))
    return records


def performance(text, steps):
    wall = float(re.findall(r'WallClock:\s*([\d.]+)',text)[-1])
    timing = re.findall(r'TIMING:\s*(\d+).*?Wall:\s*[\d.eE+\-]+,\s*([\d.eE+\-]+)/step',text)
    timing = [(int(step),float(seconds)) for step,seconds in timing]
    assert wall > 0 and timing
    # Late half avoids startup/load-balancing timing and initial GPU transients.
    selected = timing[len(timing)//2:]; seconds = float(np.median([r[1] for r in selected]))
    assert np.isfinite(seconds) and seconds > 0
    duration_ns = steps*2e-6
    return dict(atoms=N,timestep_fs=2,native_wall_seconds=wall,duration_ns=duration_ns,
                native_seconds_per_ns=wall/duration_ns,native_ns_per_day=86400*duration_ns/wall,
                late_median_seconds_per_step=seconds,late_ns_per_day=.1728/seconds,
                late_nanoseconds_wall_per_atom_step=seconds*1e9/N,
                timing_samples=len(timing),late_timing_samples=len(selected),
                caveat='Per-atom normalization is local comparison only; PME, ensemble, precision, timestep and hardware must match.')


def native(out, cfg, deadline, cores=4, resident=True):
    authorize(); assert deadline > time.time()
    if 'run 0\n' in cfg:
        cfg = cfg.replace('outputEnergies 1000\n','outputEnergies 500\n')
    out.mkdir(parents=True, exist_ok=False); (out/'run.conf').write_text(cfg)
    command = [str(NAMD),f'+p{cores}','+setcpuaffinity','+devices','0','run.conf']
    telemetry = None
    with (out/'gpu_telemetry.csv').open('w') as gpu, (out/'run.log').open('w') as log:
        telemetry = subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,name,utilization.gpu,memory.used,power.draw,power.limit,temperature.gpu,clocks.sm,clocks.mem','--format=csv','-l','10'],stdout=gpu,stderr=subprocess.STDOUT)
        started = time.monotonic()
        try:
            p = subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=max(.01,deadline-time.time()))
        finally:
            telemetry.terminate()
            try: telemetry.wait(timeout=5)
            except subprocess.TimeoutExpired: telemetry.kill();telemetry.wait()
    save(out/'native_exit.json',dict(at=now(),returncode=p.returncode,command=command,elapsed_seconds=time.monotonic()-started))
    assert p.returncode == 0
    text = (out/'run.log').read_text()
    assert ('Running with GPU-resident mode' in text) == resident
    assert 'VDW FORCE SWITCHING ACTIVE' in text
    assert ('LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in text) == ('LangevinPiston on\n' in cfg)
    return parse_log(out/'run.log')


def statistics(rows, cadence, window=None):
    rows = rows[1:]
    if window: rows = rows[-window:]
    size = 25000//cadence; blocks=[]
    for i in range(0,len(rows),size):
        part=rows[i:i+size]
        if len(part) != size: continue
        blocks.append(dict(first_step=part[0]['TS'],last_step=part[-1]['TS'],
            temperature_K=float(np.mean([r['TEMP'] for r in part])),
            group_pressure_bar=float(np.mean([r['GPRESSURE'] for r in part])),
            volume_A3=float(np.mean([r['VOLUME'] for r in part])),
            total_density_g_cm3=float(np.mean([MASS*1.66053906660/r['VOLUME'] for r in part])),
            added_NaCl_molar=float(np.mean([ASSEMBLY['salt_pairs']/(r['VOLUME']*6.02214076e-4) for r in part]))))
    return dict(blocks=blocks,mass_Da=MASS,interpretation='50 ps blocks of raw sampled values; overlapping NAMD AVG columns not used. Equilibrium and block independence are not assumed.')


def review(case,out,first,steps,stride,rows,deadline,with_observables=False):
    started=time.monotonic(); cadence=500 if stride==500 else 1000
    assert rows[0]['TS']==first and rows[-1]['TS']==first+steps
    assert sorted(set(r['TS'] for r in rows))==list(range(first,first+steps+1,cadence))
    layout=read_layout(out/'result.dcd'); count=steps//stride
    assert (layout.n_atoms,layout.n_frames,layout.nsavc,layout.istart)==(N,count,stride,first+stride)
    box,pins=checkpoint(out,first+steps)
    periodic=regular_checkpoints(out,first,first+steps)
    xst=np.atleast_2d(np.loadtxt(out/'result.xst')); assert np.isfinite(xst).all()
    cells={int(r[0]):r[1:10].reshape(3,3) for r in xst}; energies={int(r['TS']):r for r in rows}
    spec=read(ROOT/'observables_registration.json') if with_observables else None
    records=[];voids=[]
    for i in range(count+1):
        assert time.time()<deadline
        if i<count:
            x,cell=read_frame(out/'result.dcd',layout,i); dims=cell_to_dimensions(cell)
            assert dims is not None and np.allclose(dims[3:],90,atol=1e-5)
            current_box=np.array(dims[:3]);step=first+(i+1)*stride
            assert np.allclose(cells[step],np.diag(current_box),rtol=0,atol=1e-3)
            assert abs(float(np.prod(current_box))-energies[step]['VOLUME'])<1
            if step%50000==0:
                saved=read_binary(out/f'checkpoint.{step}.coor',N)
                assert np.all(abs(saved-x.astype(float))<=.5*abs(np.spacing(x).astype(float))+1e-10)
                saved_box,_=box_from_xsc(out/f'checkpoint.{step}.xsc')
                assert np.allclose(saved_box,current_box,rtol=0,atol=1e-3)
        else:
            x=read_binary(out/'result.coor',N);current_box=box;step=first+steps
            last,cell=read_frame(out/'result.dcd',layout,count-1)
            assert np.allclose(cell_to_dimensions(cell)[:3],box,rtol=0,atol=1e-3)
            assert np.all(abs(x-last.astype(float))<=.5*abs(np.spacing(last).astype(float))+1e-10)
        reference_box=np.diag(next(iter(cells.values())))
        assert np.allclose(current_box/current_box[0],reference_box/reference_box[0],rtol=0,atol=1e-5)
        r=physical(case,x,current_box,i<count);r.update(frame=i,step=step,final=i==count,box_A=current_box.tolist())
        if spec:r['observables']=observables(np.asarray(x,dtype=float),spec,case)
        records.append(r)
        if i==count or (step-first)%25000==0:voids.append(dict(step=step,**void_witness(x,current_box)))
        if not r['passed']:
            save(out/'failed_frame_review.json',records);raise RuntimeError(f'Physical gate failed: {case}/{out.name}/frame {i}')
    save(out/'frames_review.json',records);save(out/'void_diagnostics.json',voids)
    stat=statistics(rows,cadence)
    perf=performance((out/'run.log').read_text(),steps)
    result=dict(at=now(),native_and_registered_geometry_passed=True,case=case,first_step=first,last_step=first+steps,
                geometries=count+1,checkpoints=pins,regular_checkpoints=periodic,minimum_image_A=min(r['image_clearance_A'] for r in records),
                maximum_void_witness_A=max(r['sampled_max_nearest_atom_A'] for r in voids),statistics=stat,
                performance=perf,review_seconds=time.monotonic()-started,simulation_ready=False,minimum_certified=False)
    save(out/'assessment.json',result)
    return result


def endpoint_reference(case,out,step,seed,rows,deadline,cores):
    ref=out/'endpoint-reference'
    rr=native(ref,config(case,out/'result.restart.coor',step,seed,out/'result.restart',False,False)+'run 0\n',deadline,cores,False)
    assert rr[-1]['TS']==step
    error=abs(rr[-1]['POTENTIAL']-rows[-1]['POTENTIAL']);limit=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
    assert error<=limit,'Stored endpoint potential mismatch'
    return dict(error_kcal=error,limit_kcal=limit,log=source(ref/'run.log'))


def run_stage(case,out,cp,first,steps,seed,stride,deadline,cores=4,with_observables=False):
    prior=parse_log(cp.parent/'run.log')[-1]['POTENTIAL']
    rows=native(out,config(case,Path(str(cp)+'.coor'),first,seed,cp,True,True,stride)+f'run {steps}\noutput result.restart\noutput result\n',deadline,cores)
    error=abs(rows[0]['POTENTIAL']-prior);limit=max(.01,1e-6*abs(prior))
    assert error<=limit,'Restart potential mismatch'
    result=review(case,out,first,steps,stride,rows,deadline,with_observables)
    result.update(restart_error_kcal=error,restart_limit_kcal=limit,
                  endpoint_reference=endpoint_reference(case,out,first+steps,seed,rows,deadline,cores))
    save(out/'assessment.json',result)
    return result


def startup():
    plan=read(ROOT/'diagnostic_plan.json')
    for p in plan['inputs']:checked(p)
    activation=authorize();deadline=min(time.time()+10800,activation['context_deadline_epoch'],activation['deadline_epoch'])
    save(ROOT/'startup_started.json',dict(at=now(),deadline_epoch=deadline,plan=source(ROOT/'diagnostic_plan.json')))
    initial_box=np.array(read(ROOT/'assembly.json')['box_A']);reports=[]
    for case in ['anti','control']:
        folder=ROOT/case;x=read_binary(folder/'start.coor',N);initial=physical(case,x,initial_box)
        assert geometry_passed(initial['geometry']) and initial['image_clearance_A']>12 and initial['min_water_OO_A']>1.5 and initial['max_OH_error_beyond_storage_A']<1e-5
        save(folder/'initial_review.json',initial);energies=[];forces=[]
        for mode,resident in [('reference',False),('resident',True)]:
            out=folder/f'static-{mode}'
            rows=native(out,config(case,folder/'start.coor',resident=resident)+'run 0\noutput onlyforces result\n',deadline,4,resident)
            energies.append(rows[-1]['POTENTIAL']);forces.append(read_binary(out/'result.force',N))
        de=abs(energies[0]-energies[1]);df=float(abs(forces[0]-forces[1]).max())
        el=max(.001,1e-4*abs(energies[0]));fl=max(.001,1e-4*float(abs(forces[0]).max()))
        save(folder/'static_assessment.json',dict(passed=bool(de<=el and df<=fl),energy_error_kcal=de,energy_limit_kcal=el,force_error_kcal_A=df,force_limit_kcal_A=fl))
        assert de<=el and df<=fl
        out=folder/'minimize';native(out,config(case,folder/'start.coor')+'minimize 1000\noutput result.restart\noutput result\n',deadline)
        g=physical(case,read_binary(out/'result.coor',N),initial_box);save(out/'geometry.json',g);assert g['passed']
    for rep,seed in enumerate(plan['paired_seeds'],1):
        for case in ['anti','control']:
            folder=ROOT/case/f'replica-{rep}';out=folder/'heat'
            cfg=config(case,ROOT/case/'minimize/result.coor',seed=seed,stride=500)+'reinitvels 50\n'
            for target in range(75,301,25):cfg+=f'langevinTemp {target}\nrun 2500\n'
            rows=native(out,cfg+'output result.restart\noutput result\n',deadline)
            heat=review(case,out,0,25000,500,rows,deadline)
            npt=run_stage(case,folder/'npt',out/'result.restart',25000,500000,seed+1000,1000,deadline)
            restart=run_stage(case,folder/'restart',folder/'npt/result.restart',525000,5000,seed+2000,1000,deadline)
            reports.append(dict(case=case,replica=rep,seed=seed,heat=heat,npt=npt,restart=restart))
            save(ROOT/'startup_progress.json',dict(at=now(),completed=reports))
    bench=[];cp=ROOT/'anti/replica-1/restart/result.restart'
    for cores in [4,2,8]:
        out=ROOT/'core-benchmarks'/f'p{cores}'
        r=run_stage('anti',out,cp,530000,50000,99001,5000,deadline,cores)
        bench.append(dict(cores=cores,assessment=source(out/'assessment.json'),performance=r['performance']))
    best=min(bench,key=lambda r:r['performance']['late_median_seconds_per_step'])
    base=bench[0]['performance']['late_median_seconds_per_step']
    selected=best['cores'] if best['performance']['late_median_seconds_per_step']<.95*base else 4
    save(ROOT/'performance_selection.json',dict(at=now(),benchmarks=bench,selected_cores=selected,
        rule='Retain p4 unless another tested count improves late median step time by more than 5%; same NPT method and 100 ps per count; diagnostic branches not counted as validation.',
        references=['https://www.ks.uiuc.edu/Research/namd/3.0/ug/node102.html','https://www.ks.uiuc.edu/Research/namd/3.0/ug/node88.html']))
    save(ROOT/'startup_assessment.json',dict(at=now(),native_and_registered_geometry_passed=True,results=reports,
        performance_selection=source(ROOT/'performance_selection.json'),physical_and_budget_review_pending=True,
        simulation_ready=False,minimum_certified=False))



if __name__=='__main__':
    try: startup()
    except BaseException:
        (ROOT/'diagnostic_failure_traceback.txt').write_text(traceback.format_exc())
        raise
