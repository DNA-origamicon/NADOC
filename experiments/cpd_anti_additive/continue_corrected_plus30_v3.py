"""Prepare one reviewed continuation after the +30 v2 force reduction.

Keep the old frozen helpers intact. Only the audited-restart angle admission
changes; native evaluation, targets, optimizer and stationarity limits do not.
"""
from pathlib import Path
import importlib.util
import shutil
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR, checked, now, pin, read, save
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, wrapped
from experiments.cpd_anti_additive.endpoint_scan_constraints import make_scan_constraints as legacy_constraints
from experiments.cpd_anti_additive.endpoint_scan_constraints_v2 import make_scan_constraints
from experiments.cpd_anti_additive.endpoint_scan_restart import validate_scan_seed as legacy_seed
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint


def prepare():
    from ase import Atoms
    archive = Path('/media/jojo/Archive')
    campaign = (REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    if not archive.is_mount() or campaign.stat().st_dev != archive.stat().st_dev or archive.stat().st_dev == Path('/').stat().st_dev:
        raise RuntimeError('Mounted Archive required')
    previous = campaign/'endpoint-1-glyco-branch-plus30-v2'
    root = campaign/'endpoint-1-glyco-branch-plus30-v3'
    review_path = previous/'continuation_review.json'
    if root.exists() or review_path.exists():
        raise FileExistsError('Preserve existing preparation and review')
    audit = read(previous/'completion_audit.json')
    if not all(audit[k] for k in ('passed','native_evidence_passed','scan_target_passed')):
        raise ValueError('Native/scan evidence failed')
    if audit['constrained_stationary'] or audit['optimizer_converged'] or audit['new_gradients'] != 20:
        raise ValueError('Not the reviewed incomplete v2 allocation')
    old = read(checked(audit['plan'])); model = read(checked(old['model']))
    design = read(checked(old['scan_design'])); graph = read(checked(model['graph']))
    seed = read(checked(audit['last_accepted_result'])); x = np.load(checked(seed['geometry']))
    keys = model['atom_keys']
    definitions = read(checked(design['branch_review']))['torsion_definitions']
    reference = read(checked(design['profile_energy_reference']))
    neighbors = [set() for _ in keys]
    for b in graph['bonds']:
        i,j = b['indices']; neighbors[i].add(j); neighbors[j].add(i)
    excluded = set()
    for i in range(len(keys)):
        seen={i}; frontier={i}
        for _ in range(2):
            frontier=set().union(*(neighbors[j] for j in frontier))-seen; seen |= frontier
        excluded.update(tuple(sorted((i,j))) for j in seen)
    def contact(z):
        pairs=sorted((float(np.linalg.norm(z[i]-z[j])*BOHR),keys[i],keys[j])
            for i in range(len(z)) for j in range(i+1,len(z)) if (i,j) not in excluded)
        return [dict(distance_angstrom=d,atoms=[i,j]) for d,i,j in pairs[:10]]
    rows=[]
    for rec in audit['records']:
        z=np.load(checked(rec['geometry']))
        rows.append(dict(result=rec['source'],reused=rec['reused'],
            energy_hartree=rec['energy_hartree'],
            relative_to_branch_zero_kcal_mol=627.509474*(rec['energy_hartree']-reference['energy_hartree']),
            projected_metrics=rec['scan_metrics'],
            torsions_degrees={n:torsion(z,[keys.index(k) for k in atoms]) for n,atoms in definitions.items()}))
    final=next(row for row in rows if row['result']==audit['last_accepted_result'])
    root.mkdir(); (root/'tmp').mkdir()
    shutil.copy2(Path(__file__),root/'preparation_source.py')
    prior_worker=(previous/'executed_source.py').read_text()
    worker=prior_worker.replace('endpoint_scan_restart import validate_scan_seed',
        'endpoint_scan_restart_v2 import validate_scan_seed').replace(
        'endpoint_scan_constraints import make_scan_constraints',
        'endpoint_scan_constraints_v2 import make_scan_constraints').replace(
        "make_scan_constraints(atoms,plan['constraint'])",
        "make_scan_constraints(atoms,plan['constraint'],accepted_restart=bool(plan.get('continuation_audit')))")
    if worker==prior_worker:
        raise ValueError('Worker import repair was not applied')
    (root/'executed_source.py').write_text(worker)
    helpers=[pin(REPO/'experiments/cpd_anti_additive'/n) for n in
        ('endpoint_scan_restart_v2.py','endpoint_scan_constraints_v2.py')]
    plan={**old,'at':now(),'worker':pin(root/'executed_source.py'),
        'seed_result':audit['last_accepted_result'],
        'continuation_audit':pin(previous/'completion_audit.json'),
        'unit':'cpd-corrected-anti1-glyco-branch-plus30-v3',
        'expected_seconds':20*audit['mean_gradient_seconds']+30,
        'seed_precision':'Exact last accepted v2 geometry and full-precision gradient reused without snapping; fresh optimizer history.',
        'completion_semantics':'Allocation completion is not constrained convergence, basin closure, fit acceptance or minimum certification.'}
    old_failures={}
    for name,call in [('restart_angle',lambda:legacy_seed(plan)),
                      ('startup_residual',lambda:legacy_constraints(Atoms(model['elements'],positions=x*BOHR),plan['constraint']))]:
        try: call()
        except ValueError as exc: old_failures[name]=str(exc)
        else: raise ValueError('Expected legacy residual mismatch was not reproduced')
    _,configuration=make_scan_constraints(Atoms(model['elements'],positions=x*BOHR),plan['constraint'],accepted_restart=True)
    save(review_path,dict(at=now(),source=pin(root/'preparation_source.py'),
        completion_audit=pin(previous/'completion_audit.json'),records=rows,
        torsion_definitions=definitions,final_accepted=final,
        max_force_reduction_factor=rows[0]['projected_metrics']['max_atom_gradient_au']/final['projected_metrics']['max_atom_gradient_au'],
        force_limit_ratio=final['projected_metrics']['max_atom_gradient_au']/1.5e-5,
        rms_limit_ratio=final['projected_metrics']['rms_atom_gradient_au']/1e-5,
        last_five_max_force_reduction_fraction=1-final['projected_metrics']['max_atom_gradient_au']/rows[-5]['projected_metrics']['max_atom_gradient_au'],
        last_five_energy_change_kcal_mol=627.509474*(final['energy_hartree']-rows[-5]['energy_hartree']),
        energy_change_kcal_mol=627.509474*audit['energy_change_hartree'],
        torsion_changes_over_chunk_degrees={n:wrapped(final['torsions_degrees'][n]-rows[0]['torsions_degrees'][n]) for n in definitions},
        largest_adjacent_torsion_changes_degrees={n:max(abs(wrapped(b['torsions_degrees'][n]-a['torsions_degrees'][n])) for a,b in zip(rows,rows[1:])) for n in definitions},
        contact_graph_separations_excluded=2,final_contacts=contact(x),
        originally_clashing_pair_distance_angstrom=float(np.linalg.norm(x[keys.index("1:HO5'")]-x[keys.index('2:H52')])*BOHR),
        maximum_evaluated_angle_error_degrees=max(v['scan_metrics']['torsion_error_degrees'] for v in audit['records']),
        legacy_guard_failures=old_failures,restart_configuration=configuration,
        guard_repair='Versioned helpers admit an audited accepted restart using the unchanged native 0.01-degree capped angle tolerance. Strict degree target installation remains. Fresh-seed residual check remains 1e-8 radians. Exact checkpoint coordinates/gradient are not altered. Old helpers and plans remain hash-valid.',
        necessity='Maximum projected force decreased 207-fold overall and 68.1 percent over the last five records; final force is only 3.24 times the unchanged limit. This is continuing convergence, not stalled progress.',
        alternatives='Do not replace this improving checkpoint with an unevaluated clashing seed, lower the force threshold, acquire a full Hessian or revisit completed points. Cached-gradient continuation avoids a duplicate native evaluation; measured ~208-second gradients fit the existing finite budget.',
        decision='One separately audited <=20-new-gradient / 90-minute continuation at the same target and method, stopping on convergence. Review progress before any further extension.',
        optimizer_converged=False,constrained_stationary=False,minimum_certified=False,
        fit_target_accepted=False,simulation_ready=False))
    plan['conformational_review']=pin(review_path)
    plan['sources']=[*old['sources'],*helpers,pin(previous/'completion_audit.json'),pin(review_path),
        seed['input'],seed['geometry'],seed['native'],seed['gradient_binary'],pin(root/'preparation_source.py')]
    save(root/'plan.json',plan)
    spec=importlib.util.spec_from_file_location('accepted_restart_v3',root/'executed_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.context(root)
    module.admit(19,631,plan)
    for attempts,remaining in [(20,900),(0,630)]:
        try:module.admit(attempts,remaining,plan)
        except module.ChunkBoundary:pass
        else:raise ValueError('Allocation guard failed')
    identity=audit_endpoint(x,model)
    assert identity['passed']
    save(root/'preflight.json',dict(at=now(),passed=True,seed_identity=identity,
        configuration=configuration,frozen_context_verified=True,allocation_guards_passed=True,
        exact_checkpoint_and_gradient_reused=True,coordinates_modified=False,
        legacy_failures=old_failures,review=pin(review_path),new_qm_evaluations=0,
        archive_mount=str(archive),output_directory=str(root),scratch_directory=str(root/'tmp'),
        system_disk_fallback=False))
    save(root/'admission.json',dict(at=now(),proceed=True,plan=pin(root/'plan.json'),
        preceding_audit=plan['continuation_audit'],review=pin(review_path),preflight=pin(root/'preflight.json'),
        expected_minutes=plan['expected_seconds']/60,maximum_minutes=90,optimizer_history_reused=False,
        full_precision_seed_gradient_reused=True,one_native_job_at_a_time=True,cloud_spending_usd=0,
        minimum_certified=False,simulation_ready=False))
    driver=(previous/'driver_preflight_source.py').read_text().replace(
        'endpoint_scan_constraints import (','endpoint_scan_constraints_v2 import (').replace(
        "make_scan_constraints(atoms, plan['constraint'])",
        "make_scan_constraints(atoms, plan['constraint'], accepted_restart=True)").replace(
        "verify_constraint_configuration(bad, plan['constraint'])",
        "verify_constraint_configuration(bad, plan['constraint'], accepted_restart=True)")
    (root/'driver_preflight_source.py').write_text(driver)
    print(root)


if __name__=='__main__':
    prepare()
