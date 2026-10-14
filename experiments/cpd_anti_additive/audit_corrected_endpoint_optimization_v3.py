"""Completion audit of native endpoint gradients and accepted restart evidence."""
from pathlib import Path
import argparse,importlib.util,sys
import numpy as np
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,BOHR,FORCE_FACTOR,HARTREE_EV,metrics,stationary
from experiments.cpd_anti_additive.endpoint_native import audit_native
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_scan_geometry import constraint_metrics
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import load_xyz

def audit(root):
    from ase.io import read as ase_read
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    spec=importlib.util.spec_from_file_location('frozen_endpoint',root/'executed_source.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    plan,model=m.context(root);service=root.parent/(root.name+'-service')
    status=read(service/'status.json');assessment=read(root/'assessment.json');progress=read(root/'progress.json')
    ack=read(service/'completion_wake_ack.json');wake=read(service/'completion_wake.json')
    assert ack['token']==wake['token'] and ack['event']==status['state']
    assert status['state']=='complete' and status['returncode']==0 and assessment['error'] is None
    assert status['finished_at']-status['started_at']<plan['hard_seconds']
    records=[];coordinates=[];gradients=[];energies=[];native_seconds=[]
    for row in progress['evaluations']:
        result=read(checked(row['result']));inp=read(checked(result['input']));x=np.load(checked(result['geometry']))
        assert np.array_equal(x,np.array(inp['geometry_bohr'])) and inp['options']==plan['options']
        assert inp['method']=='mp2' and inp['charge']==0 and inp['multiplicity']==1 and inp['elements']==plan['elements']
        g=np.array(result['gradient_hartree_bohr']);e,gn,electronic=audit_native(checked(result['native']).read_text(),plan['elements'],x)
        assert abs(e-result['energy_hartree'])<1e-9 and np.max(abs(g-gn))<5.1e-13
        identity=audit_endpoint(x,model);assert identity['passed']
        reused=row.get('reused',False)
        if not reused:
            assert np.array_equal(g,np.load(checked(result['gradient_binary'])))
            assert np.max(abs(np.load(checked(result['returned_geometry']))-x))<1e-14
            native_seconds.append(result['wall_seconds'])
        records.append(dict(source=row['result'],native=result['native'],input=result['input'],geometry=result['geometry'],reused=reused,energy_hartree=e,gradient_metrics=metrics(g),identity=identity,electronic=electronic,wall_seconds=result['wall_seconds']))
        coordinates.append(x);gradients.append(g);energies.append(e)
    assert len(native_seconds)==assessment['new_gradients_completed']<=plan['max_new_gradients']
    assert len(records)==assessment['evaluated_records']==len(native_seconds)+sum(v['reused'] for v in records)
    checkpoints=[]
    for path in sorted(root.glob('accepted-*.xyz')):
        x=load_xyz(path,plan['elements'])
        matches=[i for i,v in enumerate(coordinates) if np.allclose(v,x,atol=1e-12,rtol=0)]
        assert matches and audit_endpoint(x,model)['passed']
        checkpoints.append(dict(geometry=pin(path),evaluated_source=records[matches[-1]]['source']))
    frames=ase_read(root/'sella.traj',index=':')
    for frame in frames:
        x=frame.positions/BOHR;assert frame.get_chemical_symbols()==plan['elements']
        matches=[i for i,v in enumerate(coordinates) if np.allclose(v,x,atol=1e-12,rtol=0)];assert matches
        i=matches[-1];assert abs(frame.get_potential_energy()/HARTREE_EV-energies[i])<1e-9
        assert np.max(abs(-frame.get_forces()/FORCE_FACTOR-gradients[i]))<1e-12
    restart=read(root/'restart_checkpoint.json');checked(restart['geometry']);checked(restart['evaluated_source'])
    assert restart['evaluated_source']==checkpoints[-1]['evaluated_source']
    last=read(checked(restart['evaluated_source']));last_x=np.load(checked(last['geometry']));last_g=np.array(last['gradient_hartree_bohr'])
    assert np.allclose(load_xyz(checked(restart['geometry']),plan['elements']),last_x,atol=1e-12,rtol=0)
    raw_limits=metrics(last_g);limits=raw_limits;projections=[];constrained_stationary=None
    if plan.get('constraint'):
        projections=[constraint_metrics(last_x,last_g,plan['constraint'],h)[0] for h in (1e-4,1e-5,1e-6)]
        limits=projections[1];constrained_stationary=all(v['passed'] for v in projections)
        from ase import Atoms
        from sella import Constraints
        atoms=Atoms(plan['elements'],positions=last_x*BOHR);c=Constraints(atoms);c.fix_dihedral(tuple(plan['constraint']['indices']))
        normal=c.jacobian()[0].reshape(last_g.shape)
        independent=metrics(last_g-normal*np.sum(normal*last_g)/np.sum(normal**2))
        assert abs(independent['max_atom_gradient_au']-limits['max_atom_gradient_au'])<1e-10
        assert abs(independent['rms_atom_gradient_au']-limits['rms_atom_gradient_au'])<1e-10
        if assessment['optimizer_converged']:assert constrained_stationary
    elif assessment['optimizer_converged']:assert stationary(raw_limits)
    convergence=read(root/'latest_convergence.json')
    assert np.isclose(limits['max_atom_gradient_au'],convergence['gradient_metrics']['max_atom_gradient_au'],atol=1e-14,rtol=0)
    data=dict(at=now(),passed=True,source=pin(Path(__file__)),plan=pin(root/'plan.json'),status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),assessment=pin(root/'assessment.json'),records=records,checkpoints=checkpoints,trajectory=pin(root/'sella.traj'),trajectory_frames_verified=len(frames),new_gradients=len(native_seconds),native_gradient_components=147*len(records),native_geometry_tables=2*len(records),new_gradient_components=147*len(native_seconds),restart=pin(root/'restart_checkpoint.json'),last_accepted_result=restart['evaluated_source'],last_accepted_geometry=last['geometry'],last_gradient_metrics=limits,stationary=stationary(raw_limits),constrained_stationary=constrained_stationary,projection_checks=projections,gradient_metric_scope='constrained' if plan.get('constraint') else 'unconstrained',optimizer_converged=assessment['optimizer_converged'],allocation_boundary=assessment['allocation_boundary'],service_seconds=status['finished_at']-status['started_at'],native_seconds=sum(native_seconds),mean_gradient_seconds=float(np.mean(native_seconds)),max_gradient_seconds=max(native_seconds),initial_gradient_metrics=records[0]['gradient_metrics'],last_ten_gradient_metrics=[v['gradient_metrics'] for v in records[-10:]],energy_change_hartree=energies[-1]-energies[0],last_ten_energy_change_hartree=energies[-1]-energies[-min(10,len(energies))],minimum_certified=False,simulation_ready=False)
    save(out,data)
    print({k:data[k] for k in ['passed','new_gradients','native_gradient_components','trajectory_frames_verified','last_gradient_metrics','stationary','service_seconds','mean_gradient_seconds','max_gradient_seconds','energy_change_hartree']})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);audit(p.parse_args().root.resolve())
