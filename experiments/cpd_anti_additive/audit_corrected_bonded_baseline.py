"""Audit actual baseline states, preserving stationarity/quality distinctions."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now


def audit(root):
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service');status=read(service/'status.json');ack=read(service/'completion_wake_ack.json')
    assert ack['token']==read(service/'completion_wake.json')['token']
    assert ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('baseline_frozen',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);plan=m.context(root)
    top=read(root/'assessment.json');assert top['error'] is None and len(top['completed'])==2
    records=[]
    for variant,ref in zip(plan['variants'],top['completed'],strict=True):
        result=read(checked(ref));assert checked(result['plan'])==root/'plan.json'
        static=read(checked(result['static_results']));assert len(static['records'])==10
        engines={label:m.Evaluator(checked(f['systems'][variant])) for label,f in plan['fixtures'].items()}
        values={};errors=[]
        for point,row in zip(plan['points'],static['records'],strict=True):
            assert row['label']==point['label'] and row['geometry']==point['geometry'] and row['qm_result']==point['qm_result']
            xyz=np.load(checked(point['geometry']))*m.BOHR;qm=read(checked(point['qm_result']))
            energy,g,parts=engines[point['fixture']].evaluate(xyz,True)
            delta=max(abs(energy-row['energy_kcal_mol']),np.max(abs(g-np.load(checked(row['gradient'])))))
            assert delta<1e-9 and all(abs(parts[k]-v)<1e-9 for k,v in row['force_group_energies'].items())
            target=np.array(qm['gradient_hartree_bohr'])*m.EH/m.BOHR
            assert abs(np.sqrt(np.mean((g-target)**2))-row['qm_gradient_component_rmse_kcal_mol_angstrom'])<1e-9
            errors.append(float(delta));values[row['label']]=row
        x=np.load(checked(result['final_geometry']));e,g,parts=engines['core'].evaluate(x,True)
        assert abs(e-result['energy_kcal_mol'])<1e-9 and np.max(abs(g-np.load(checked(result['final_gradient']))))<1e-9
        history=dict(np.load(checked(result['raw_evaluations'])));accepted=np.load(checked(result['accepted_coordinates']))
        assert len(history['energies_kcal_mol'])==result['evaluations']
        assert np.isfinite(history['energies_kcal_mol']).all() and np.isfinite(history['gradients_kcal_A']).all()
        assert np.max(abs(accepted[-1]-x))<1e-12
        # Every accepted frame must correspond to an actually evaluated state.
        assert all(np.min(np.max(abs(history['coordinates_angstrom']-v),axis=(1,2)))<1e-12 for v in accepted)
        identity=m.geometry_audit(x/m.BOHR,read(checked(plan['fixtures']['core']['model'])))
        force=float(np.linalg.norm(g,axis=1).max());assert identity['passed'] and force<.001
        reference=np.load(checked(plan['points'][0]['geometry']))*m.BOHR
        geometry=m.geometry_differences(reference,x,plan['fixtures']['core'])
        for key in ['max_bond_error_angstrom','max_angle_error_degrees','heavy_atom_proper_alignment_rmsd_angstrom']:
            assert abs(geometry[key]-result['geometry_differences'][key])<1e-12
        energy_zero=values['endpoint-+0'];profile=[]
        for point in plan['points']:
            if point['fixture']!='endpoint':continue
            v=values[point['label']]
            qm=(v['qm_energy_hartree']-energy_zero['qm_energy_hartree'])*m.EH
            mm=v['energy_kcal_mol']-energy_zero['energy_kcal_mol']
            profile.append(dict(offset_degrees=point['offset_degrees'],qm_relative_kcal_mol=qm,
                                vertical_mm_relative_kcal_mol=mm,vertical_error_kcal_mol=mm-qm))
        modes=[]
        for rank in [1,2]:
            minus,plus=[values[f'mode-{rank}-{sign}'] for sign in ['minus','plus']];zero=values['core']
            even_mm=(plus['energy_kcal_mol']+minus['energy_kcal_mol']-2*zero['energy_kcal_mol'])/2
            even_qm=(plus['qm_energy_hartree']+minus['qm_energy_hartree']-2*zero['qm_energy_hartree'])*m.EH/2
            modes.append(dict(rank=rank,step_bohr=.1,mm_even_energy_kcal_mol=even_mm,qm_even_energy_kcal_mol=even_qm,
                              even_energy_relative_error=even_mm/even_qm-1,
                              mm_odd_energy_kcal_mol=(plus['energy_kcal_mol']-minus['energy_kcal_mol'])/2,
                              qm_odd_energy_kcal_mol=(plus['qm_energy_hartree']-minus['qm_energy_hartree'])*m.EH/2,
                              interpretation='Finite coupled-mode displacement response at the QM core, not curvature at an MM minimum or Hessian certification.'))
        records.append(dict(variant=variant,assessment=ref,optimizer_success=result['optimizer_success'],
                            independently_stationary=True,max_atom_gradient_kcal_mol_angstrom=force,
                            identity=identity,accepted_frames_verified=len(accepted),maximum_native_replay_error=max(errors),
                            geometry=geometry,vertical_endpoint_profile=profile,ring_mode_response=modes,
                            core_qm_gradient_component_rmse_kcal_mol_angstrom=values['core']['qm_gradient_component_rmse_kcal_mol_angstrom']))
        for engine in engines.values():engine.close()
    save(out,dict(at=now(),source=pin(Path(__file__)),passed=True,native_evidence_passed=True,
        status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),plan=pin(root/'plan.json'),records=records,
        decision='Acquire a bounded five-point constrained MM profile from the exact QM endpoint conformers before fitting relaxed energies. Use last-row hypothesis as provisional parent: lower core heavy-atom RMSD than first-row, while preserving both failed-quality baselines; not a global-best or source-ambiguity resolution claim.',
        reason='Both cores are stationary and stereochemically intact but geometry errors remain about0.03Angstrom and5degrees; vertical endpoint discrepancies cannot be interpreted as relaxed conformational errors. Core coupled-mode even-energy errors are diagnostic, not a universal5percent gate.',
        selected_provisional_parent='last',constrained_profile_admitted=True,fit_admitted=False,new_qm_admitted=False,
        parameter_fit_round_consumed=False,charge_transfer_validated=False,heldout_accessed=False,
        minimum_certified=False,simulation_ready=False,cloud_spending_usd=0))
    print([dict(variant=r['variant'],rmsd=r['geometry']['heavy_atom_proper_alignment_rmsd_angstrom'],
                angle_error=r['geometry']['max_angle_error_degrees'],ring_relative_errors=[m['even_energy_relative_error'] for m in r['ring_mode_response']],
                vertical_errors=[p['vertical_error_kcal_mol'] for p in r['vertical_endpoint_profile']]) for r in records])


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
