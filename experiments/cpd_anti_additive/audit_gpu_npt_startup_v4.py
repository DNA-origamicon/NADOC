"""Independent native/cell/restart audit plus stratified geometry replay; no MD."""
import csv
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.native_log_v3 import parse_log
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.gpu_npt_context_v4 import ROOT,N,MASS,physical,box_from_xsc,void_witness,performance
from backend.core.dcd_fast import read_layout,read_frame,cell_to_dimensions


def audit():
    plan=read(ROOT/'startup_plan.json')
    for p in plan['inputs']:checked(p)
    reports=read(ROOT/'startup_assessment.json');assert reports['native_and_registered_geometry_passed']
    native=[];pins=[source(Path(__file__)),source(ROOT/'startup_plan.json'),source(ROOT/'startup_assessment.json')]
    for p in sorted(ROOT.rglob('native_exit.json')):
        f=p.parent;exit=read(p);assert exit['returncode']==0
        log=(f/'run.log').read_text();cfg=(f/'run.conf').read_text();rows=parse_log(f/'run.log')
        resident='GPUresident on\n' in cfg
        assert ('Running with GPU-resident mode' in log)==resident
        assert 'VDW FORCE SWITCHING ACTIVE' in log
        assert ('LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in log)==('LangevinPiston on\n' in cfg)
        assert '+setcpuaffinity' in exit['command']
        if not resident:assert 'run 0\n' in cfg
        native.append(dict(folder=str(f.resolve()),resident=resident,first=rows[0]['TS'],last=rows[-1]['TS']))
        pins += [source(f/name) for name in ['run.log','run.conf','native_exit.json']]
    assert len(native)==42
    for case in ['anti','control']:
        e=[];forces=[]
        for mode in ['reference','resident']:
            f=ROOT/case/f'static-{mode}';e.append(parse_log(f/'run.log')[-1]['POTENTIAL']);forces.append(read_binary(f/'result.force',N))
        report=read(ROOT/case/'static_assessment.json')
        assert abs(e[0]-e[1])<=report['energy_limit_kcal']
        assert np.max(abs(forces[0]-forces[1]))<=report['force_limit_kcal_A']
    stages=[];summaries=[];cell_frames=0;worker_geometries=0;periodic_count=0
    for r in reports['results']:
        case=r['case'];rep=r['replica'];f=ROOT/case/f'replica-{rep}'
        stages.extend([(case,f/'heat',0,25000,500),(case,f/'npt',25000,500000,1000),(case,f/'restart',525000,5000,1000)])
        rows=parse_log(f/'npt/run.log')[-250:]
        b=read(f/'npt/assessment.json')['statistics']['blocks'][-10:]
        summaries.append(dict(case=case,replica=rep,pressure_bar=float(np.mean([v['GPRESSURE'] for v in rows])),temperature_K=float(np.mean([v['TEMP'] for v in rows])),density_g_cm3=float(np.mean([MASS*1.6605390666/v['VOLUME'] for v in rows])),added_NaCl_molar=float(np.mean([63/(v['VOLUME']*6.02214076e-4) for v in rows])),density_half_difference_g_cm3=float(np.mean([v['total_density_g_cm3'] for v in b[5:]])-np.mean([v['total_density_g_cm3'] for v in b[:5]]))))
    stages += [('anti',ROOT/'core-benchmarks'/f'p{c}',530000,100000,5000) for c in [4,2,8]]
    audited=[]
    for case,f,first,steps,stride in stages:
        rows=parse_log(f/'run.log');cadence=500 if stride==500 else 1000
        assert sorted(set(r['TS'] for r in rows))==list(range(first,first+steps+1,cadence))
        a=read(f/'assessment.json');assert a['native_and_registered_geometry_passed']
        layout=read_layout(f/'result.dcd');count=steps//stride
        assert (layout.n_atoms,layout.n_frames,layout.istart,layout.nsavc)==(N,count,first+stride,stride)
        for ext in ['coor','vel']:
            assert np.array_equal(read_binary(f/f'result.{ext}',N),read_binary(f/f'result.restart.{ext}',N))
        box,xsc=box_from_xsc(f/'result.xsc');assert xsc[0]==first+steps and np.array_equal(xsc,np.loadtxt(f/'result.restart.xsc'))
        xs=np.atleast_2d(np.loadtxt(f/'result.xst'));assert np.isfinite(xs).all()
        cells={int(r[0]):r[1:10].reshape(3,3) for r in xs};energy={int(r['TS']):r for r in rows}
        samples=[];chosen={0,count//2,count-1}
        for i in range(count):
            x,cell=read_frame(f/'result.dcd',layout,i);dims=cell_to_dimensions(cell);step=first+(i+1)*stride
            assert dims is not None and np.allclose(dims[3:],90,atol=1e-5)
            assert np.allclose(cells[step],np.diag(dims[:3]),rtol=0,atol=1e-3)
            assert abs(np.prod(dims[:3])-energy[step]['VOLUME'])<1
            if step%50000==0:
                cp=f/f'checkpoint.{step}';cb,cr=box_from_xsc(Path(str(cp)+'.xsc'));assert cr[0]==step
                assert np.allclose(cb,dims[:3],rtol=0,atol=1e-3)
                coor=read_binary(Path(str(cp)+'.coor'),N);vel=read_binary(Path(str(cp)+'.vel'),N)
                assert np.isfinite(vel).all() and np.isfinite(coor).all()
                assert np.all(abs(coor-x.astype(float))<=.5*abs(np.spacing(x).astype(float))+1e-10)
                periodic_count+=1
            if i in chosen:
                g=physical(case,x,np.array(dims[:3]),True);assert g['passed'];samples.append(dict(frame=i,review=g))
        final=read_binary(f/'result.coor',N)
        assert np.allclose(dims[:3],box,rtol=0,atol=1e-3)
        assert np.all(abs(final-x.astype(float))<=.5*abs(np.spacing(x).astype(float))+1e-10)
        g=physical(case,final,box);assert g['passed'];void=void_witness(final,box)
        worker=read(f/'frames_review.json');assert len(worker)==count+1 and all(v['passed'] for v in worker)
        if f.name!='heat':
            cfg=dict((line.split()[0],' '.join(line.split()[1:])) for line in (f/'run.conf').read_text().splitlines())
            prior=Path(cfg['binCoordinates']).parent
            pe=parse_log(prior/'run.log')[-1]['POTENTIAL']
            assert abs(rows[0]['POTENTIAL']-pe)<=max(.01,1e-6*abs(pe))
            rr=parse_log(f/'endpoint-reference/run.log');assert rr[-1]['TS']==first+steps
            assert abs(rr[-1]['POTENTIAL']-rows[-1]['POTENTIAL'])<=max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
        perf=performance((f/'run.log').read_text(),steps)
        telemetry=list(csv.DictReader((f/'gpu_telemetry.csv').open()))
        usable=telemetry[1:]  # Discard process-start sample.
        metrics={}
        for field in [' utilization.gpu [%]',' power.draw [W]',' temperature.gpu',' clocks.current.sm [MHz]']:
            values=[float(row[field].strip().split()[0]) for row in usable]
            if values:metrics[field.strip()]=dict(min=min(values),max=max(values),mean=float(np.mean(values)))
        audited.append(dict(folder=str(f.resolve()),case=case,samples=samples,endpoint_geometry=g,endpoint_void=void,performance=perf,gpu=metrics))
        cell_frames+=count;worker_geometries+=len(worker)
        for name in ['assessment.json','frames_review.json','void_diagnostics.json','result.dcd','result.xst','result.coor','result.vel','result.xsc','gpu_telemetry.csv']:
            pins.append(source(f/name))
        for record in a['regular_checkpoints']:
            for pin in record['files']:checked(pin);pins.append(pin)
    assert cell_frames==3390 and worker_geometries==3411 and periodic_count==66
    selection=read(ROOT/'performance_selection.json');assert selection['selected_cores']==4
    for r in selection['benchmarks']:checked(r['assessment'])
    result=dict(at=now(),passed=True,scope='Independent native/static/cell/periodic-checkpoint audit, stratified geometry replay and physical interpretation inputs; not full independent geometry replay.',input_pins_verified=len(plan['inputs']),native_jobs=len(native),dcd_cells_verified=cell_frames,worker_geometry_records=worker_geometries,independent_sampled_frames=sum(len(r['samples']) for r in audited),independent_binary_endpoints=len(audited),complete_regular_restart_sets=periodic_count,late500ps=summaries,stages=audited,inputs=pins,simulation_ready=False,minimum_certified=False)
    save(ROOT/'startup_native_audit.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['stages','inputs']}))

if __name__=='__main__':audit()
