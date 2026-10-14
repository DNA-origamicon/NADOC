"""Reopen native endpoint electrostatics and audit unchanged-charge diagnostics."""
from pathlib import Path
import importlib.util
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now


def audit(root):
    out=root/'completion_audit.json'
    if out.exists():raise FileExistsError(out)
    service=root.parent/(root.name+'-service')
    status=read(service/'status.json');ack=read(service/'completion_wake_ack.json')
    assert ack['token']==read(service/'completion_wake.json')['token']
    assert ack['event']==status['state']=='complete' and status['returncode']==0
    spec=importlib.util.spec_from_file_location('frozen_transfer',root/'executed_source.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    plan,model=m.context(root);assignment=read(checked(plan['charge_assignment']))
    review=read(root/'independent_review.json');assessment=read(root/'assessment.json')
    assert assessment['completed']==2 and assessment['error'] is None
    assert checked(review['plan'])==root/'plan.json'
    candidate=read(checked(assignment['candidate']))
    keys=model['atom_keys'];sugar=[i for i,k in enumerate(keys) if "'" in k]
    q=np.array(assignment['charge_vectors_e']['candidate'])
    assert all(q[i]==candidate['charges_e'][k] for i,k in enumerate(keys) if k in candidate['charges_e'])
    assert all(q[i]==assignment['sugar'][keys[i].split(':')[1]]['charge_e'] for i in sugar)
    assert len(sugar)==17 and abs(q[sugar].sum())<1e-12 and abs(q.sum())<1e-12
    records=[]
    for t,stored in zip(plan['tasks'],review['records'],strict=True):
        result_path=root/t['label']/'result.json';v=read(result_path)
        assert checked(stored['result'])==result_path and v['input']==t['input']
        inp=read(checked(t['input']));x=np.array(inp['geometry_angstrom'])
        assert np.max(abs(x/m.BOHR-np.load(checked(inp['source_geometry']))))<5e-14
        native=m.native_checks(checked(v['native']).read_text(),inp,v['energy_hartree'],v['dipole_au'])
        returned=np.load(checked(v['returned_geometry']))
        assert np.max(abs(returned-x))<1e-12 and m.audit_endpoint(returned/m.BOHR,model)['passed']
        grid=np.loadtxt(checked(v['grid']));esp=np.loadtxt(checked(v['potentials']))
        assert v['grid']==inp['grid'] and esp.shape==(len(grid),) and np.isfinite(esp).all()
        reconstructed={}
        for label,charges in assignment['charge_vectors_e'].items():
            charges=np.array(charges)
            predicted=np.array([sum(charges[i]*m.BOHR/np.linalg.norm(p-position)
                                    for i,position in enumerate(x)) for p in grid])
            dipole=np.sum(charges[:,None]*x,axis=0)*(2.541746473/m.BOHR)
            diff=dipole-np.array(v['dipole_au'])*2.541746473
            old=stored['metrics'][label]
            assert np.max(abs(dipole-old['mm_dipole_debye']))<1e-12
            assert abs(np.linalg.norm(diff)-old['dipole_vector_error_debye'])<1e-12
            for region,mask in inp['region_masks'].items():
                mask=np.array(mask,bool)
                rmse=np.sqrt(np.mean((predicted[mask]-esp[mask])**2))
                assert abs(rmse-old['esp_regions'][region]['rmse_au'])<1e-12
            reconstructed[label]=old
        gains={region:1-reconstructed['candidate']['esp_regions'][region]['rmse_au']/
               reconstructed['baseline']['esp_regions'][region]['rmse_au'] for region in inp['region_masks']}
        records.append(dict(label=t['label'],result=pin(result_path),native=native,
                            metrics=reconstructed,esp_rmse_fractional_improvement=gains,
                            dipole_error_fractional_improvement=1-reconstructed['candidate']['dipole_vector_error_debye']/reconstructed['baseline']['dipole_vector_error_debye']))
    assert all(v['dipole_error_fractional_improvement']>0 and all(x>0 for x in v['esp_rmse_fractional_improvement'].values()) for v in records)
    save(out,dict(at=now(),source=pin(Path(__file__)),passed=True,native_evidence_passed=True,
        status=pin(service/'status.json'),acknowledgement=pin(service/'completion_wake_ack.json'),
        plan=pin(root/'plan.json'),independent_review=pin(root/'independent_review.json'),candidate=assignment['candidate'],
        records=records,service_seconds=status['finished_at']-status['started_at'],
        decision='Retain unchanged round-one charges provisionally for corrected bonded-model baseline diagnostics. Both endpoints improve relative to the initial hypothesis, but substantial absolute errors remain. Stop this sufficient two-conformer acquisition; no automatic refit or extra HF/water grid.',
        residual_interpretation='Candidate dipole errors1.024/2.040D and ESP relative RMSE42.5/51.5 percent do not validate transfer accuracy. Nearest-methyl-cap ESP errors remain84.7/89.7 percent; nearest-sugar errors38.3/58.5 percent. Geometric regions do not uniquely identify electronic error sources. Do not compensate uncertain fixed sugar/cap contributions by an unmotivated base-charge fit.',
        bonded_baseline_admitted=True,additional_electrostatic_qm_admitted=False,second_fit_admitted=False,
        conformers_used=3,conformer_budget=3,charge_transfer_validated=False,
        heldout_accessed=False,minimum_certified=False,simulation_ready=False,cloud_spending_usd=0))
    print(dict(passed=True,seconds=status['finished_at']-status['started_at'],
               dipole_errors=[r['metrics']['candidate']['dipole_vector_error_debye'] for r in records]))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
