"""Replay native, cell, checkpoint and stratified chemistry evidence without MD."""
import argparse
import csv
from pathlib import Path
import sys
import time
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.gpu_cube_preparation_v6 import load_engine
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now


def unique_step_rows(rows):
    """Repeated run boundaries are not additional thermodynamic samples."""
    return list({int(row['TS']): row for row in rows}.values())


def audit(plan_path):
    plan = read(plan_path)
    for pin in plan['inputs']:
        checked(pin)
    m = load_engine(plan)
    case, rep = plan['case'], plan['replica']
    folder = m.ROOT/case
    replica = folder/f'replica-{rep}'
    prepared = read(replica/'preparation_assessment.json')
    checked(prepared['plan'])
    assert (prepared['case'], prepared['replica'], prepared['seed']) == (case, rep, plan['seed'])
    pins = [source(plan_path), source(replica/'preparation_assessment.json'), source(Path(__file__))]
    native = []
    native_folders = [folder/'static-reference', folder/'static-resident', folder/'minimize'] if rep == 1 else []
    native_folders += [replica/'heat', replica/'npt', replica/'npt/endpoint-reference', replica/'restart', replica/'restart/endpoint-reference']
    for f in native_folders:
        state = read(f/'native_exit.json'); assert state['returncode'] == 0
        cfg = (f/'run.conf').read_text(); log = (f/'run.log').read_text()
        rows = m.parse_log(f/'run.log')
        resident = 'GPUresident on\n' in cfg
        assert ('Running with GPU-resident mode' in log) == resident
        assert 'VDW FORCE SWITCHING ACTIVE' in log
        assert ('LANGEVIN PISTON PRESSURE CONTROL ACTIVE' in log) == ('LangevinPiston on\n' in cfg)
        assert '+p4' in state['command'] and '+setcpuaffinity' in state['command']
        if not resident:
            assert 'run 0\n' in cfg
        for axis in 'XYZ':
            assert f'PMEGridSize{axis} 144\n' in cfg
        native.append(dict(folder=str(f.resolve()),first=rows[0]['TS'],last=rows[-1]['TS'],resident=resident))
        pins += [source(f/name) for name in ['run.log','run.conf','native_exit.json']]
    energies, forces = [], []
    for mode in ['reference', 'resident']:
        f = folder/f'static-{mode}'
        energies.append(m.parse_log(f/'run.log')[-1]['POTENTIAL'])
        forces.append(m.read_binary(f/'result.force',m.N))
    de = abs(energies[0]-energies[1]); df = float(abs(forces[0]-forces[1]).max())
    el = max(.001,1e-4*abs(energies[0])); fl = max(.001,1e-4*float(abs(forces[0]).max()))
    assert de <= el and df <= fl
    audited = []; cells_count = checkpoints = worker_count = 0
    for stage, first, steps, stride in [('heat',0,25000,500),('npt',25000,500000,1000),('restart',525000,5000,1000)]:
        f = replica/stage; raw = m.parse_log(f/'run.log'); rows = unique_step_rows(raw)
        assert [int(r['TS']) for r in rows] == list(range(first,first+steps+1,stride))
        report = read(f/'assessment.json'); assert report['native_and_registered_geometry_passed']
        layout = m.read_layout(f/'result.dcd'); count = steps//stride
        assert (layout.n_atoms,layout.n_frames,layout.istart,layout.nsavc) == (m.N,count,first+stride,stride)
        box, xsc = m.box_from_xsc(f/'result.xsc')
        assert xsc[0] == first+steps and np.array_equal(xsc,np.loadtxt(f/'result.restart.xsc'))
        for ext in ['coor','vel']:
            assert np.array_equal(m.read_binary(f/f'result.{ext}',m.N),m.read_binary(f/f'result.restart.{ext}',m.N))
        xst = np.atleast_2d(np.loadtxt(f/'result.xst')); assert np.isfinite(xst).all()
        cells = {int(r[0]):r[1:10].reshape(3,3) for r in xst}; energy = {int(r['TS']):r for r in rows}
        samples = []
        for i in range(count):
            x, cell = m.read_frame(f/'result.dcd',layout,i); dims = m.cell_to_dimensions(cell)
            step = first+(i+1)*stride
            assert dims is not None and np.allclose(dims[3:],90,atol=1e-5)
            assert np.allclose(cells[step],np.diag(dims[:3]),rtol=0,atol=1e-3)
            assert abs(np.prod(dims[:3])-energy[step]['VOLUME']) < 1
            if step % 50000 == 0:
                cp = f/f'checkpoint.{step}'; cb, cr = m.box_from_xsc(Path(str(cp)+'.xsc'))
                assert cr[0] == step and np.allclose(cb,dims[:3],rtol=0,atol=1e-3)
                coor = m.read_binary(Path(str(cp)+'.coor'),m.N); vel = m.read_binary(Path(str(cp)+'.vel'),m.N)
                assert np.isfinite(coor).all() and np.isfinite(vel).all()
                assert np.all(abs(coor-x.astype(float)) <= .5*abs(np.spacing(x).astype(float))+1e-10)
                checkpoints += 1
            if i in {0,count//2,count-1}:
                g = m.physical(case,x,np.array(dims[:3]),True); assert g['passed']
                samples.append(dict(frame=i,review=g))
        final = m.read_binary(f/'result.coor',m.N)
        assert np.allclose(dims[:3],box,rtol=0,atol=1e-3)
        assert np.all(abs(final-x.astype(float)) <= .5*abs(np.spacing(x).astype(float))+1e-10)
        g = m.physical(case,final,box); assert g['passed']
        worker = read(f/'frames_review.json'); assert len(worker) == count+1 and all(v['passed'] for v in worker)
        for pin in report['checkpoints']:
            checked(pin); pins.append(pin)
        for record in report['regular_checkpoints']:
            for pin in record['files']:
                checked(pin); pins.append(pin)
        if stage != 'heat':
            cfg = dict((line.split()[0],' '.join(line.split()[1:])) for line in (f/'run.conf').read_text().splitlines())
            prior = m.parse_log(Path(cfg['binCoordinates']).parent/'run.log')[-1]['POTENTIAL']
            assert abs(rows[0]['POTENTIAL']-prior) <= max(.01,1e-6*abs(prior))
            reference = m.parse_log(f/'endpoint-reference/run.log')[-1]
            assert reference['TS'] == first+steps
            assert abs(reference['POTENTIAL']-rows[-1]['POTENTIAL']) <= max(.01,1e-6*abs(rows[-1]['POTENTIAL']))
        stats = m.statistics(rows,stride)
        telemetry = list(csv.DictReader((f/'gpu_telemetry.csv').open()))[1:]
        metrics = {}
        for field in [' utilization.gpu [%]',' power.draw [W]',' temperature.gpu',' clocks.current.sm [MHz]']:
            values = [float(row[field].strip().split()[0]) for row in telemetry]
            if values:
                metrics[field.strip()] = dict(min=min(values),max=max(values),mean=float(np.mean(values)))
        audited.append(dict(stage=stage,samples=samples,endpoint_geometry=g,endpoint_void=m.void_witness(final,box),performance=m.performance((f/'run.log').read_text(),steps),gpu=metrics,statistics=stats,duplicate_boundary_rows=len(raw)-len(rows)))
        cells_count += count; worker_count += len(worker)
        pins += [source(f/name) for name in ['assessment.json','frames_review.json','result.dcd','result.xst','result.coor','result.vel','result.xsc','gpu_telemetry.csv']]
    assert (cells_count,worker_count,checkpoints) == (555,558,10)
    npt = audited[1]; blocks = npt['statistics']['blocks'][-10:]
    late = {key:float(np.mean([b[key] for b in blocks])) for key in ['temperature_K','group_pressure_bar','total_density_g_cm3','added_NaCl_molar','volume_A3']}
    late['density_half_difference_g_cm3'] = float(np.mean([b['total_density_g_cm3'] for b in blocks[5:]])-np.mean([b['total_density_g_cm3'] for b in blocks[:5]]))
    result = dict(at=now(),passed=True,case=case,replica=rep,scope='Independent native/static/cell/checkpoint replay and nine stratified frames plus three binary endpoints using frozen chemistry routines; not independent full-frame chemistry.',input_pins_verified=len(plan['inputs']),native_jobs=len(native),dcd_cells_verified=cells_count,worker_geometry_records=worker_count,independent_sampled_frames=9,independent_binary_endpoints=3,complete_regular_restart_sets=checkpoints,static=dict(energy_error_kcal=de,energy_limit_kcal=el,force_error_kcal_A=df,force_limit_kcal_A=fl),late500ps=late,stages=audited,inputs=pins,simulation_ready=False,minimum_certified=False)
    save(replica/'preparation_native_audit.json',result)
    print({k:v for k,v in result.items() if k not in ['stages','inputs']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--plan',type=Path,required=True)
    audit(parser.parse_args().plan)
