"""Assemble the five audited development points without promoting fitting gates."""
from pathlib import Path
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion,wrapped,rotate_sugar


def review():
    campaign=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    root=campaign/'glycosidic-branch-profile-v1'
    out=root/'completed_profile_review.json'
    if out.exists():raise FileExistsError(out)
    prior=read(root/'progress-after-plus15.json');design=read(checked(prior['design']))
    model=read(checked(design['model']));graph=read(checked(model['graph']))
    keys=model['atom_keys'];bonds=[b['indices'] for b in graph['bonds']]
    definitions=read(checked(design['branch_review']))['torsion_definitions']
    final_path=campaign/'endpoint-1-glyco-branch-plus30-v3/completion_audit.json'
    plus30=read(final_path)
    sources=[(v['offset_degrees'],v['audit']) for v in prior['points']]+[(30,pin(final_path))]
    zero=read(checked(design['profile_energy_reference']));rows=[]
    for offset,ref in sources:
        audit=read(checked(ref))
        if not all(audit[k] for k in ('passed','native_evidence_passed','scan_target_passed','optimizer_converged','constrained_stationary')):
            raise ValueError('Profile point not audited/converged')
        plan=read(checked(audit['plan']));v=read(checked(audit['last_accepted_result']))
        assert plan['model']==design['model']
        assert abs(plan['constraint']['target_degrees']-(design['reference_torsion_degrees']+offset))<1e-8
        x=np.load(checked(v['geometry']));g=np.asarray(v['gradient_hartree_bohr'])
        plus,_=rotate_sugar(x,bonds,plan['constraint']['indices'],.001)
        minus,_=rotate_sugar(x,bonds,plan['constraint']['indices'],-.001)
        rows.append(dict(offset_degrees=offset,audit=ref,result=audit['last_accepted_result'],
            geometry=v['geometry'],energy_hartree=v['energy_hartree'],
            relative_to_branch_zero_kcal_mol=627.509474*(v['energy_hartree']-zero['energy_hartree']),
            projected_gradient=audit['last_gradient_metrics'],
            constrained_stationary=True,minimum_certified=False,
            conformer_torsions_degrees={n:torsion(x,[keys.index(k) for k in atoms]) for n,atoms in definitions.items()},
            slope_kcal_mol_per_degree=float(np.sum(g*(plus-minus))/.002*627.509474)))
    adjacent=[]
    for a,b in zip(rows,rows[1:]):
        adjacent.append(dict(offsets_degrees=[a['offset_degrees'],b['offset_degrees']],
            energy_difference_kcal_mol=b['relative_to_branch_zero_kcal_mol']-a['relative_to_branch_zero_kcal_mol'],
            torsion_changes_degrees={n:wrapped(b['conformer_torsions_degrees'][n]-a['conformer_torsions_degrees'][n]) for n in definitions}))
    record=dict(at=now(),source=pin(Path(__file__)),design=prior['design'],
        preceding_progress=pin(root/'progress-after-plus15.json'),points=rows,
        torsion_definitions=definitions,adjacent_point_comparisons=adjacent,
        converged_offsets_degrees=[-30,-15,0,15,30],pending_offsets_degrees=[],
        maximum_plus30_chunk_angle_error_degrees=max(r['scan_metrics']['torsion_error_degrees'] for r in plus30['records']),
        completed_glycosidic_acquisition=True,observations_exposed_development=True,
        derivative_method='Chain rule using saved native gradient and central rigid sugar rotation (+/-0.001 degree); no new electronic energies. Local slope is not a fitted curve or barrier estimate.',
        decision='Stop all five completed optimizations. Proceed to the previously planned four coupled-core distortions. Adjacent final geometries vary gradually; no observed final-profile discontinuity currently justifies an extra reverse scan.',
        interpretation='Finite samples and continuous torsion trends support provisional profile bookkeeping, not proof of a common basin or endpoint minimum. Sugar/cap relaxation contributes to these energies. Keep every geometry for matched QM/MM comparison before fitting acceptance; require a targeted closure check if that comparison reveals branch mismatch.',
        heldout_offsets_degrees=[-22.5,22.5],heldout_acquisition=False,
        fit_target_accepted=False,basin_closure_certified=False,minimum_certified=False,
        simulation_ready=False,new_qm_evaluations=0)
    save(out,record)
    print([(v['offset_degrees'],v['relative_to_branch_zero_kcal_mol']) for v in rows])


if __name__=='__main__':review()
