"""One bounded SQP construction with fitted torsions and explicit chirality.

Retains prior failed verdicts and the 3.5 Å product screen. This isolated job
changes coordinates only and cannot launch dynamics or promote app geometry.
"""
import argparse
import os
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import openmm as mm
from openmm import unit as u
from scipy.optimize import minimize

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.condition_source_v1 import inputs as original_inputs
from experiments.cpd_anti_additive.chiral_constraints import SignedVolumes
from experiments.cpd_anti_additive.relax_dna_placement_v2 import stereo_check,contact_check

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-fitted-conditioning-v2'
MODEL=ART/'cpd-anti-fitted-dna-v2-r1'
PRIOR=ART/'cpd-anti-source-conditioning-v1b'


def inputs():
    d,records,selected,_=original_inputs()
    prior=read(PRIOR/'assessment.json')
    assert prior['error'] is not None and prior['stereo']['passed']
    d['seed']=np.loadtxt(checked(prior['coordinates']))
    constraint=SignedVolumes(d['seed'],d['mobile'],[s[0] for s in selected],[s[1] for s in selected])
    assert min(constraint.values(d['seed'][d['mobile']].ravel()))>.1
    return d,records,selected,constraint


def prepare():
    d,records,selected,constraint=inputs()
    model=read(MODEL/'assessment.json')
    assert model['full_DNA_static_NAMD_passed'] and model['all_other_forces_and_particles_exactly_unchanged']
    ROOT.mkdir(exist_ok=False)
    (ROOT/'worker.py').write_text(Path(__file__).read_text())
    np.savetxt(ROOT/'starting_A.txt',d['seed'])
    save(ROOT/'chirality_constraints.json',[dict(indices=s[0],sign=float(s[1]),label=s[2]) for s in selected])
    paths=[MODEL/n for n in ('assessment.json','system.xml','anti.psf','anti_dna_overlay.prm','plan.json')]
    paths += [PRIOR/n for n in ('assessment.json','independent_review.json','candidate_A.txt','plan.json')]
    paths += [ROOT/'worker.py',ROOT/'starting_A.txt',ROOT/'chirality_constraints.json',
        Path(__file__).with_name('condition_source_v1.py'),Path(__file__).with_name('chiral_constraints.py'),
        Path(__file__).with_name('relax_dna_placement_v2.py')]
    save(ROOT/'plan.json',dict(version='fitted-conditioning-v2',created_at=now(),sources=[source(p) for p in paths],
        scope='Isolated full-DNA coordinate construction, new fitted potential and new constrained optimizer; no dynamics or product integration',
        rationale='Prior trust-constr reached 500 iterations with force 19.7611 kcal/mol/A. The first finite torsion fit now passes energy/representative geometry and native fragment/full-DNA static checks. Test dense sequential quadratic programming with analytic chirality derivatives, then remove the temporary constraints.',
        authorization='User: Continue with next steps to get to NAMD ready; versioned method attempt within resumed diagnostic construction scope',
        prior_failure=source(PRIOR/'assessment.json'),system=source(MODEL/'system.xml'),
        mobile_indices=d['mobile'].tolist(),mobile_atoms=len(d['mobile']),fixed_atoms=len(d['x'])-len(d['mobile']),
        phases=[dict(name='chirality_constrained',method='SLSQP',maxiter=1000,ftol=1e-12,objective_scale=1000,
                     signed_volume_lower_A3=.1),
                dict(name='constraints_removed',method='L-BFGS-B',maxiter=1500,gtol_kcal_A=.001,ftol=1e-13,maxls=30)],
        transition='Constrained solver success, all stereo intact, no clashes/piercings, and all oriented volumes >0.1001 A^3',
        max_energy_evaluations=6000,hard_seconds=7200,expected_seconds=1200,max_attempts=1,max_continuations=0,
        unchanged_limits=dict(max_mobile_force_kcal_A=.01,bond_equilibrium_ratio=[.7,1.3],
            severe_clash_ratio=.5,product_max_base_displacement_A=3.5),
        fail_on_accepted_inversion=True,checkpoint_every=50,threads=2,platform='CPU',
        reference='https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html',
        scipy_version=__import__('scipy').__version__,
        limitations=['Fixed outer DNA; unsolvated charged system; no global-minimum certification.',
            'Energy-fit branch residuals and missing prospective validation remain.',
            '3.5 A product-displacement screen is retained and reported separately; no automatic app integration.'],
        simulation_ready=False))
    print('Prepared',ROOT,'mobile',len(d['mobile']),'constraints',len(selected),flush=True)


def run():
    plan=read(ROOT/'plan.json')
    for s in plan['sources']:checked(s)
    assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
    assert __import__('scipy').__version__==plan['scipy_version']
    d,records,selected,constraint=inputs()
    assert plan['mobile_indices']==d['mobile'].tolist()
    with (ROOT/'started.json').open('x') as handle:
        import json
        json.dump(dict(at=now(),plan=source(ROOT/'plan.json')),handle)
    system=mm.XmlSerializer.deserialize(checked(plan['system']).read_text())
    integrator=mm.VerletIntegrator(.001)
    ctx=mm.Context(system,integrator,mm.Platform.getPlatformByName('CPU'),{'Threads':'2'})
    mobile=d['mobile'];fixed=np.setdiff1d(np.arange(len(d['seed'])),mobile)
    last=d['seed'].copy();start=time.monotonic();evaluations=0;iterations=0;phases=[];error=None
    stage_name='';stage_iterations=0;events=[]
    def evaluate(flat):
        nonlocal evaluations
        if evaluations>=plan['max_energy_evaluations'] or time.monotonic()-start>plan['hard_seconds']:
            raise RuntimeError('Declared evaluation/time budget reached')
        evaluations+=1;x=constraint.positions(flat);ctx.setPositions(x*u.angstrom)
        state=ctx.getState(getEnergy=True,getForces=True)
        energy=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
        gradient=-np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))[mobile].ravel()
        if not np.isfinite(energy) or not np.isfinite(gradient).all():raise RuntimeError('Nonfinite energy/gradient')
        return energy,gradient
    # Independent directional derivative at the actual new-potential seed.
    flat=last[mobile].ravel();e,g=evaluate(flat);j=int(np.argmax(abs(g)));step=1e-4
    plus=flat.copy();minus=flat.copy();plus[j]+=step;minus[j]-=step
    fd=(evaluate(plus)[0]-evaluate(minus)[0])/(2*step)
    # CPU single precision positions add noise at this scale; use Reference for
    # the reproducible preflight and final audit instead of relaxing tolerances.
    ri=mm.VerletIntegrator(.001);rc=mm.Context(system,ri,mm.Platform.getPlatformByName('Reference'))
    def reference(flat):
        rc.setPositions(constraint.positions(flat)*u.angstrom);s=rc.getState(getEnergy=True,getForces=True)
        return s.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),-np.array(s.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))[mobile].ravel()
    re,rg=reference(flat);rfd=(reference(plus)[0]-reference(minus)[0])/(2*step)
    assert abs(rfd-rg[j])<max(1e-3,abs(rg[j])*1e-4)
    save(ROOT/'gradient_preflight.json',dict(index=j,reference_fd_error=abs(rfd-rg[j]),cpu_fd_error=abs(fd-g[j]),
        max_cpu_reference_force_difference=float(np.max(abs(g-rg))),initial_max_mobile_force=float(abs(rg).max())))
    def callback(flat):
        nonlocal last,iterations,stage_iterations
        iterations+=1;stage_iterations+=1;x=constraint.positions(flat)
        stereo=stereo_check(d,x,records)
        if not stereo['passed']:
            np.savetxt(ROOT/f'{stage_name}-rejected_A.txt',x)
            save(ROOT/f'{stage_name}-rejected_stereo.json',stereo)
            raise RuntimeError('Accepted optimizer iterate inverted stereochemistry')
        last=x.copy()
        if stage_iterations%plan['checkpoint_every']==0:
            folder=ROOT/f'{stage_name}-{stage_iterations:05d}';folder.mkdir()
            np.savetxt(folder/'coordinates_A.txt',x);contacts=contact_check(d,x)
            save(folder/'review.json',dict(contacts=contacts,stereo=stereo,
                min_oriented_volume_A3=float(min(constraint.values(flat)))))
            save(ROOT/'progress.json',dict(stage=stage_name,stage_iterations=stage_iterations,
                iterations=iterations,evaluations=evaluations,elapsed_seconds=time.monotonic()-start,
                checkpoint=source(folder/'coordinates_A.txt')))
            print(stage_name,stage_iterations,'evaluations',evaluations,'seconds',time.monotonic()-start,flush=True)
            if contacts['all_piercing_count']:raise RuntimeError('Checkpoint ring piercing')
    with (ROOT/'evaluations.jsonl').open('x') as log:
        def objective(flat):
            energy,gradient=evaluate(flat)
            import json
            log.write(json.dumps(dict(stage=stage_name,evaluation=evaluations,energy_kcal=energy,
                max_mobile_force_kcal_A=float(abs(gradient).max()),elapsed_seconds=time.monotonic()-start))+'\n');log.flush()
            scale=1000 if stage_name=='chirality_constrained' else 1
            return energy/scale,gradient/scale
        try:
            for stage in plan['phases']:
                stage_name=stage['name'];stage_iterations=0
                if stage_name=='chirality_constrained':
                    cons=dict(type='ineq',fun=lambda x:constraint.values(x)-.1,
                              jac=lambda x:constraint.jacobian(x).toarray())
                    result=minimize(objective,last[mobile].ravel(),jac=True,method='SLSQP',constraints=[cons],callback=callback,
                        options=dict(maxiter=stage['maxiter'],ftol=stage['ftol']))
                else:
                    result=minimize(objective,last[mobile].ravel(),jac=True,method='L-BFGS-B',callback=callback,
                        options=dict(maxiter=stage['maxiter'],gtol=stage['gtol_kcal_A'],ftol=stage['ftol'],maxls=stage['maxls']))
                x=constraint.positions(result.x)
                if not stereo_check(d,x,records)['passed']:raise RuntimeError('Terminal stereo failed')
                last=x;np.savetxt(ROOT/f'{stage_name}-final_A.txt',last)
                phase=dict(stage=stage_name,optimizer_success=bool(result.success),message=str(result.message),
                    iterations=int(result.nit),min_oriented_volume_A3=float(min(constraint.values(result.x))))
                phases.append(phase);save(ROOT/'phases.json',phases)
                if not result.success:raise RuntimeError(stage_name+' reached its terminal failure; no extension')
                contacts=contact_check(d,last)
                if contacts['severe_clash_count'] or contacts['all_piercing_count']:raise RuntimeError('Phase geometry integrity failed')
                if stage_name=='chirality_constrained' and phase['min_oriented_volume_A3']<=.1001:
                    raise RuntimeError('Artificial chirality boundary active; cannot release constraints')
        except Exception as exc:
            error=repr(exc);(ROOT/'failure_traceback.txt').write_text(traceback.format_exc())
    re,rg=reference(last[mobile].ravel())
    np.savetxt(ROOT/'candidate_A.txt',last)
    save(ROOT/'final_reference_force.json',dict(energy_kcal=re,gradient_kcal_A=rg.reshape(-1,3).tolist(),mobile_indices=mobile.tolist()))
    stereo=stereo_check(d,last,records);contacts=contact_check(d,last)
    bonds={tuple(sorted(b)) for b in d['bonds']};ratios=[]
    for f in system.getForces():
        if not isinstance(f,mm.HarmonicBondForce):continue
        for i in range(f.getNumBonds()):
            a,b,eq,k=f.getBondParameters(i)
            if tuple(sorted((a,b))) in bonds:
                ratios.append(float(np.linalg.norm(last[a]-last[b])/eq.value_in_unit(u.angstrom)))
    assert len(ratios)==len(bonds)
    bond_pass=bool(.7<min(ratios) and max(ratios)<1.3)
    released=len(phases)==2 and phases[-1]['optimizer_success']
    stationary=bool(np.max(abs(rg))<=.01)
    unchanged=np.array_equal(last[fixed],d['x'][fixed])
    integrity=bool(error is None and released and stationary and bond_pass and stereo['passed'] and unchanged
        and not contacts['severe_clash_count'] and not contacts['all_piercing_count'])
    base=[i for k,i in d['ids'].items() if "'" not in k and k in d['names']]
    displacement=float(np.linalg.norm(last[base]-d['x'][base],axis=1).max())
    report=dict(error=error,phases=phases,total_iterations=iterations,energy_evaluations=evaluations,
        coordinate_integrity_passed=integrity,chirality_constraints_removed=released,
        mobile_stationary=stationary,max_mobile_reference_force_kcal_A=float(abs(rg).max()),
        whole_model_bond_integrity=bond_pass,bond_equilibrium_ratio_range=[min(ratios),max(ratios)],
        fixed_atoms_exactly_unchanged=unchanged,stereo=stereo,contacts=contacts,
        max_base_displacement_A=displacement,inherited_base_displacement_screen_passed=displacement<=3.5,
        minimum_certified=False,full_DNA_dynamics_tested=False,simulation_ready=False,preliminary_research_qualified=False,
        elapsed_seconds=time.monotonic()-start,coordinates=source(ROOT/'candidate_A.txt'),plan=source(ROOT/'plan.json'),
        next='Independent geometry review including shared-frame A/B before any integration. No automatic dynamics or additional optimization.')
    save(ROOT/'assessment.json',report)
    print({k:v for k,v in report.items() if k not in ('stereo','contacts')},flush=True)
    if not integrity:raise RuntimeError('Bounded fitted-DNA construction failed; preserve all evidence')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run'])
    globals()[parser.parse_args().action]()
