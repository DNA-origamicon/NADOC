"""Consolidate existing QM/MM branch evidence without acquiring new QM targets."""
from pathlib import Path
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR,read,save,pin,checked,now
from experiments.cpd_anti_additive.corrected_bonded_baseline import Evaluator,EH,proper_rmsd
from experiments.cpd_anti_additive.corrected_fixed_core_boundary import free_projection
from experiments.cpd_anti_additive.corrected_mm_endpoint_profile import descriptors,heavy_torsions
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive


def review():
    campaign=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    root=campaign/'alternate-sugar-qm-release-v1';out=root/'consolidated_candidate_review.json'
    require_archive(root)
    if out.exists():raise FileExistsError(out)
    auditpath=root/'completion_audit.json';a=read(auditpath);assert a['passed'] and a['native_evidence_passed']
    p=read(checked(a['plan']));model=read(checked(p['model']));keys=model['atom_keys']
    mp=read(campaign/'mm-endpoint-profile-v2/plan.json');fixture=mp['fixture'];assert fixture['model']==p['model']
    ma=read(campaign/'mm-endpoint-profile-v2/completion_audit.json');assert ma['passed']
    historical=next(v for v in ma['records'] if v['offset_degrees']==0)
    mr=read(checked(historical['assessment']));mx=np.load(checked(mr['final_geometry']))
    fit=read(campaign/'core-bonded-fit-v1/completion_audit.json');assert fit['passed']
    candidate=read(checked(fit['candidate']));chi=p['constraint']['indices']
    references={'original_qm':p['reference_result'],'alternate_qm':a['last_accepted_result']}
    geometries={'historical_parent_mm':mx};qm={};sources=[]
    for label,ref in references.items():
        v=read(checked(ref));x=np.load(checked(v['geometry']));g=np.load(checked(v['gradient_binary']))
        assert audit_endpoint(x,model)['passed']
        geometries[label]=x*BOHR
        qm[label]=dict(result=ref,energy_hartree=v['energy_hartree'],gradient_kcal_A=g*EH/BOHR)
        sources.extend([ref,v['geometry'],v['gradient_binary'],v['native']])
    qdelta=(qm['alternate_qm']['energy_hartree']-qm['original_qm']['energy_hartree'])*EH
    models={};raw={}
    for label,system in [('parent',mp['system']),('core_round1',candidate['endpoint'])]:
        engine=Evaluator(checked(system));rows={};raw[label]={}
        try:
            for geometry,x in geometries.items():
                e,g,parts=engine.evaluate(x,True)
                tangent=free_projection(x,g,[],chi)
                row=dict(energy_kcal_mol=e,maximum_chi_projected_atom_gradient_kcal_A=float(np.linalg.norm(tangent,axis=1).max()),force_group_energies=parts)
                if geometry in qm:
                    qg=qm[geometry]['gradient_kcal_A'];qtangent=free_projection(x,qg,[],chi)
                    row.update(gradient_component_rmse_vs_qm_kcal_A=float(np.sqrt(np.mean((g-qg)**2))),
                        tangent_gradient_component_rmse_vs_qm_kcal_A=float(np.sqrt(np.mean((tangent-qtangent)**2))))
                if label=='parent' and geometry=='historical_parent_mm':
                    assert abs(e-mr['energy_kcal_mol'])<1e-9
                    assert np.max(abs(g-np.load(checked(mr['final_gradient']))))<1e-9
                    assert row['maximum_chi_projected_atom_gradient_kcal_A']<.001
                rows[geometry]=row;raw[label][geometry]=dict(gradient_kcal_A=g.tolist(),energy_kcal_mol=e)
            delta=rows['alternate_qm']['energy_kcal_mol']-rows['original_qm']['energy_kcal_mol']
            models[label]=dict(system=system,points=rows,alternate_minus_original_vertical_kcal_mol=delta,
                error_vs_observed_qm_difference_kcal_mol=delta-qdelta,
                interpretation='Both MM energies at the same acquired QM geometries, using one original reference per method; no separate basin re-zeroing. Alternate QM geometry not yet stationary. Diagnostic only.')
        finally:engine.close()
    ts=heavy_torsions(fixture)
    comparisons={label:descriptors(geometries[label],mx,fixture,ts) for label in qm}
    save(root/'consolidated_mm_evaluations.json',dict(at=now(),coordinate_units='angstrom',bohr_conversion=BOHR,
        geometry_order='Original model atom order; historical MM coordinates reused exactly in their stored Angstrom units.',
        geometries_angstrom={k:v.tolist() for k,v in geometries.items()},evaluations=raw))
    stop_same_problem=a['constrained_stationary']
    finish_admitted=bool(not stop_same_problem and a['numerical_progress_supports_continuation'])
    report=dict(at=now(),source=pin(Path(__file__)),completion_audit=pin(auditpath),big_picture_review=pin(campaign/'big-picture-audit-20261011/review.json'),
        sources=sources+[pin(campaign/'mm-endpoint-profile-v2/plan.json'),pin(campaign/'mm-endpoint-profile-v2/completion_audit.json'),historical['assessment'],
            mr['final_geometry'],mr['final_gradient'],pin(campaign/'core-bonded-fit-v1/completion_audit.json'),fit['candidate']],
        native_mm_evaluations=pin(root/'consolidated_mm_evaluations.json'),passed=True,mm_systems=models,
        qm_alternate_minus_original_kcal_mol=qdelta,historical_parent_mm_comparison=comparisons,
        scope='Six static OpenMM Reference energy/gradient evaluations. Existing QM and accepted MM coordinates only. No new relaxation, QM, fit, or target-grid acquisition.',
        retained_candidate_limits=dict(candidate_qualified=fit['candidate_qualified'],core_force_gradient_rmse_blocks=fit['objective_blocks'],
            ring_training_response=fit['ring_training_response'],previous_vertical_endpoint_transfer=fit['vertical_endpoint_transfer'],
            full_precision_psf_export_pending=candidate['full_precision_psf_export_pending'],charge_transfer_validated=fit['charge_transfer_validated']),
        conclusion='The lower-energy QM branch is directly comparable with the already observed MM alternative. Use branch-matched evidence to judge shape, but retain the magnitude of the MM/QM conformational energy discrepancy and incomplete force/curvature transfer. A diagnostic geometric match alone does not qualify the force field.',
        candidate_decision='Keep round1 parameters provisional and unmodified. Do not spend the second fit on forcing the original sugar conformer. Finish this single existing chi-constrained QM target, then evaluate the smallest candidate correction justified by the consolidated residuals. Existing reference/failed cases remain exposed development evidence.',
        continuation_admitted=finish_admitted,continuation_target='Only current alternate zero-offset endpoint; same single chi,49atoms,method,thresholds and exact accepted seed/gradient.',
        continuation_max_new_gradients=30,continuation_hard_seconds=7200,task_timeout_seconds=600,
        continuation_necessity='Remaining maximum force2.85times and RMS1.68times limits after149.6fold overall and85.1% recent maximum-force reduction. A bounded finish resolves reference-stationarity bookkeeping without another grid or Hessian. Stop immediately at audited optimizer stationarity; budget is not a requested evaluation count.',
        next_after_stationarity='Stop QM optimization; compare the stationary matched conformer against existing MM and core-response data before a finite remaining fit decision. Address provisional NAMD export/energy-force engineering separately. No automatic extra endpoint Hessian or profile.',
        new_qm_evaluations=0,additional_angular_grid_admitted=False,endpoint_hessian_admitted=False,second_fit_admitted=False,
        heldout_accessed=False,minimum_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(out,report)
    print(dict(qm_relative_kcal=qdelta,models={k:dict(relative=v['alternate_minus_original_vertical_kcal_mol'],error=v['error_vs_observed_qm_difference_kcal_mol'],
        gradient_rmse_original=v['points']['original_qm']['gradient_component_rmse_vs_qm_kcal_A'],gradient_rmse_alternate=v['points']['alternate_qm']['gradient_component_rmse_vs_qm_kcal_A']) for k,v in models.items()},
        mm_rmsd={k:v['heavy_atom_rmsd_angstrom'] for k,v in comparisons.items()},max_torsion_change={k:v['maximum_heavy_proper_change_degrees'] for k,v in comparisons.items()},continuation_admitted=finish_admitted))


if __name__=='__main__':review()
