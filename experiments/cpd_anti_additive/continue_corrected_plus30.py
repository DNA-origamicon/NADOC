"""Review the clashing +30 seed and prepare one finite same-target restart."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR, checked, now, pin, read, save
from experiments.cpd_anti_additive.endpoint_scan_geometry import constraint_metrics, rotate_sugar, torsion, wrapped
from experiments.cpd_anti_additive.endpoint_scan_constraints import make_scan_constraints
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint


def prepare():
    from ase import Atoms
    archive = Path('/media/jojo/Archive')
    campaign = (REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    if not archive.is_mount() or campaign.stat().st_dev != archive.stat().st_dev or archive.stat().st_dev == Path('/').stat().st_dev:
        raise RuntimeError('Mounted Archive required')
    prior = campaign/'endpoint-1-glyco-branch-plus30-v1'
    root = campaign/'endpoint-1-glyco-branch-plus30-v2'
    review_path = prior/'continuation_review.json'
    if root.exists() or review_path.exists():
        raise FileExistsError('Preserve prior preparation/review')
    audit = read(prior/'completion_audit.json')
    if not all(audit[k] for k in ('passed','native_evidence_passed','scan_target_passed')):
        raise ValueError('Native/scan integrity failed')
    if audit['constrained_stationary'] or audit['optimizer_converged'] or audit['new_gradients'] != 20:
        raise ValueError('Not the reviewed incomplete first chunk')
    old = read(checked(audit['plan'])); model = read(checked(old['model']))
    design = read(checked(old['scan_design'])); graph = read(checked(model['graph']))
    seed = read(checked(audit['last_accepted_result'])); x = np.load(checked(seed['geometry']))
    plus15_audit = read(campaign/'endpoint-1-glyco-branch-plus15-v1/completion_audit.json')
    if not all(plus15_audit[k] for k in ('passed','native_evidence_passed','scan_target_passed','constrained_stationary')):
        raise ValueError('Alternative source unaudited')
    plus15 = read(checked(plus15_audit['last_accepted_result']))
    plus15_x = np.load(checked(plus15['geometry']))
    bonds = [b['indices'] for b in graph['bonds']]
    alternative, moving = rotate_sugar(plus15_x,bonds,old['constraint']['indices'],
        wrapped(old['constraint']['target_degrees']-torsion(plus15_x,old['constraint']['indices'])))
    keys = model['atom_keys']; neighbors = [set() for _ in keys]
    for i,j in bonds:
        neighbors[i].add(j); neighbors[j].add(i)
    excluded = set()
    for i in range(len(keys)):
        seen = {i}; frontier = {i}
        for _ in range(2):
            frontier = set().union(*(neighbors[j] for j in frontier))-seen; seen |= frontier
        excluded.update(tuple(sorted((i,j))) for j in seen)
    def contacts(z):
        pairs = sorted((float(np.linalg.norm(z[i]-z[j])*BOHR),keys[i],keys[j])
            for i in range(len(z)) for j in range(i+1,len(z)) if (i,j) not in excluded)
        return [dict(distance_angstrom=d,atoms=[i,j]) for d,i,j in pairs[:10]]
    root.mkdir(); (root/'tmp').mkdir()
    shutil.copy2(Path(__file__),root/'preparation_source.py')
    np.save(root/'alternative_plus15_rotated_bohr.npy',alternative)
    original_x = np.load(checked(old['starting_geometry']))
    contact_review = {}
    for name,z in [('original_seed',original_x),('accepted_checkpoint',x),('plus15_rotated_alternative',alternative)]:
        identity = audit_endpoint(z,model)
        if not identity['passed']:
            raise ValueError(f'Geometry identity failed: {name}')
        contact_review[name] = dict(identity=identity,contacts=contacts(z),torsion_degrees=torsion(z,old['constraint']['indices']))
    definitions = read(checked(design['branch_review']))['torsion_definitions']
    reference = read(checked(design['profile_energy_reference']))
    rows = []
    for rec in audit['records']:
        z = np.load(checked(rec['geometry']))
        rows.append(dict(result=rec['source'],energy_hartree=rec['energy_hartree'],
            relative_to_branch_zero_kcal_mol=627.509474*(rec['energy_hartree']-reference['energy_hartree']),
            projected_metrics=rec['scan_metrics'],
            torsions_degrees={n:torsion(z,[keys.index(k) for k in atoms]) for n,atoms in definitions.items()}))
    projected,_ = constraint_metrics(x,np.asarray(seed['gradient_hartree_bohr']),old['constraint'])
    save(review_path,dict(at=now(),source=pin(root/'preparation_source.py'),completion_audit=pin(prior/'completion_audit.json'),
        original_preflight=pin(prior/'preflight.json'),original_starting_geometry=old['starting_geometry'],
        accepted_checkpoint=audit['last_accepted_result'],contacts_exclude_graph_separations_up_to_bonds=2,
        contact_review=contact_review,alternative_geometry=pin(root/'alternative_plus15_rotated_bohr.npy'),
        alternative_source=plus15_audit['last_accepted_result'],alternative_new_qm_evaluations=0,
        torsion_definitions=definitions,records=rows,final_projected_metrics=projected,
        maximum_evaluated_angle_error_degrees=max(v['scan_metrics']['torsion_error_degrees'] for v in audit['records']),
        force_limit_ratio=projected['max_atom_gradient_au']/1.5e-5,
        last_five_energy_change_kcal_mol=627.509474*(rows[-1]['energy_hartree']-rows[-5]['energy_hartree']),
        last_five_max_force_reduction_fraction=1-rows[-1]['projected_metrics']['max_atom_gradient_au']/rows[-5]['projected_metrics']['max_atom_gradient_au'],
        diagnosis='The original rigid 30-degree seed has a 0.58-A nonbonded H/H contact and +161.22 kcal/mol energy relative to branch zero. Bond/stereochemistry preflight did not screen nonbonded seed contacts. All prior native data remain valid at their recorded coordinates; none is a converged +30 target.',
        preflight_limitation='Preserve the old passed identity/constraint preflight. It did not establish acceptable nonbonded starting contacts. Inspect contact distances in future seed preparation before spending QM; these contacts are diagnostic, not new fitting/minimum acceptance thresholds.',
        necessity='Plus30 remains unresolved at ~673 times the force limit. Large initial repulsion was relieved, energy still decreases and cap/sugar coordinates still move. One fresh-history restart tests continued relaxation after that large initial deformation.',
        alternatives='Do not repeat the original seed. A rigid plus15-to-plus30 seed still has a 1.31-A H/H contact, shorter than 1.93 A at the accepted checkpoint, and has no evaluated gradient. Its apparent disadvantage does not prove energy/basin ordering. Reuse the known checkpoint/gradient before spending on that alternative or a Hessian.',
        decision='One <=20-new-gradient / 90-minute continuation from the exact accepted checkpoint, fresh Sella optimizer history, same degree target and method. Audit force progress, conformation and necessity before any further work; no automatic extension if force remains stalled.',
        proceed_with_one_constrained_continuation=True,constrained_stationary=False,minimum_certified=False,fit_target_accepted=False,simulation_ready=False))
    shutil.copy2(prior/'executed_source.py',root/'executed_source.py')
    plan = {**old,'at':now(),'worker':pin(root/'executed_source.py'),
        'seed_result':audit['last_accepted_result'],'continuation_audit':pin(prior/'completion_audit.json'),
        'conformational_review':pin(review_path),
        'sources':[*old['sources'],pin(prior/'completion_audit.json'),pin(review_path),
            seed['input'],seed['geometry'],seed['native'],seed['gradient_binary'],pin(root/'preparation_source.py')],
        'unit':'cpd-corrected-anti1-glyco-branch-plus30-v2',
        'expected_seconds':20*audit['mean_gradient_seconds']+30,
        'seed_precision':'Exact accepted v1 geometry and full-precision gradient reused; unchanged fixed angle, fresh Sella history.',
        'completion_semantics':'Reviewed same-target continuation. Allocation completion is not constrained convergence, basin closure, fit acceptance or minimum certification.'}
    save(root/'plan.json',plan)
    spec = importlib.util.spec_from_file_location('reviewed_scan_continuation',root/'executed_source.py')
    worker = importlib.util.module_from_spec(spec);spec.loader.exec_module(worker);worker.context(root)
    _,config = make_scan_constraints(Atoms(model['elements'],positions=x*BOHR),plan['constraint'])
    worker.admit(19,631,plan)
    for attempts,remaining in [(20,900),(0,630)]:
        try: worker.admit(attempts,remaining,plan)
        except worker.ChunkBoundary: pass
        else: raise ValueError('Allocation guard failed')
    save(root/'preflight.json',dict(at=now(),passed=True,frozen_context_verified=True,
        seed_identity=audit_endpoint(x,model),configuration=config,constraint_metrics=projected,
        same_target_full_precision_restart_verified=True,allocation_guards_passed=True,
        contact_review=pin(review_path),new_qm_evaluations=0,archive_mount=str(archive),
        output_directory=str(root),scratch_directory=str(root/'tmp'),system_disk_fallback=False))
    save(root/'admission.json',dict(at=now(),proceed=True,plan=pin(root/'plan.json'),
        preceding_audit=plan['continuation_audit'],conformational_review=plan['conformational_review'],
        preflight=pin(root/'preflight.json'),expected_minutes=plan['expected_seconds']/60,maximum_minutes=90,
        optimizer_history_reused=False,full_precision_seed_gradient_reused=True,
        one_native_job_at_a_time=True,cloud_spending_usd=0,minimum_certified=False,simulation_ready=False))
    print(root)


if __name__ == '__main__':
    prepare()
