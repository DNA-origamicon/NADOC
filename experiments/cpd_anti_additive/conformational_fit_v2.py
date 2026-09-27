"""Bounded, exposed-data torsion fit and independent MM re-relaxation.

This is a local ffTK-style relaxed-baseline fit, not an ffTK invocation. It
retains the two-stage distinction between a frozen-coordinate linear fit and
the resulting relaxed landscape. No QM, prospective validation or app writes.
"""

import argparse
import importlib.metadata as metadata
import math
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import warnings

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from backend.parameterization.photoproduct_qm import _dihedral_degrees
from experiments.cpd_anti_additive.preliminary_protocol import STATE, POLICY, lock_inputs, begin_round
from experiments.cpd_anti_additive.validation_gate import checked, read, source, require_fit_ready, geometry_match
from experiments.cpd_anti_additive.sella_pilot import BOHR, now, save, projected_metrics

ART = REPO / '.development-artifacts'
PARENT = ART / 'cpd-anti-engine-candidate-v2g'
INPUTS = ART / 'cpd-anti-conformational-inputs-v2'
OUT = ART / 'cpd-anti-conformational-fit-v2-r1'
EV_KCAL = 23.060547830619


def definitions():
    return [dict(endpoint=e, names=[f'{e}:{n}' for n in names], periodicity=n)
            for e in (1, 2)
            for names in (("O4'", "C1'", 'N1', 'C2'), ("C2'", "C1'", 'N1', 'C6'))
            for n in (1, 2, 3)]


def relative(values, records):
    """Use the exact same conformer reference identity in either method."""
    values = np.asarray(values)
    index = {r['case_id']: i for i, r in enumerate(records)}
    return np.array([values[i]-values[index[r['reference_case_id']]] for i, r in enumerate(records)])


def features(x, names, variables):
    result = []
    for v in variables:
        if all(n in names for n in v['names']):
            ids = [names.index(n) for n in v['names']]
            result.append(math.cos(v['periodicity']*math.radians(_dihedral_degrees(*x[ids]))))
        else:
            result.append(0.)
    return np.array(result)


def energy_summary(values, records):
    predicted = relative(values, records)
    target = np.array([r['qm_relative_kcal_mol'] for r in records])
    error = predicted-target
    return dict(rmse_kcal=float(np.sqrt(np.mean(error**2))), max_abs_kcal=float(abs(error).max()),
        energy_passed=bool(np.sqrt(np.mean(error**2))<=1 and abs(error).max()<=2),
        records=[dict(case_id=r['case_id'], branch=r['branch'], reference=r['reference_case_id'],
            qm_relative_kcal=float(q), mm_relative_kcal=float(m), error_kcal=float(d))
            for r,q,m,d in zip(records,target,predicted,error)])


def prepare():
    from openmm import app
    INPUTS.mkdir(exist_ok=False)
    inventory_path = ART/'cpd-anti-conformational-inventory-v2b/inventory.json'
    inventory = read(inventory_path)
    records = inventory['records']
    assert len(records)==19 and inventory['all_declared_qm_geometries_present']
    assert all(r['qm_relative_kcal_mol']<=12 for r in records)
    variables = definitions()
    artifacts = [source(inventory_path), source(POLICY)]
    for e in (1,2):
        folder = PARENT/f'endpoint-{e}'
        psf = app.CharmmPsfFile(str(folder/'fragment.psf'))
        names = read(folder/'atom_map.json')
        actual = {min(tuple(a.attype for a in (t.atom1,t.atom2,t.atom3,t.atom4)),
                      tuple(a.attype for a in (t.atom4,t.atom3,t.atom2,t.atom1))) for t in psf.dihedral_list}
        for v in variables:
            if v['endpoint']!=e:
                continue
            types = tuple(psf.atom_list[names.index(n)].attype for n in v['names'])
            v['types'] = list(min(types,types[::-1]))
            assert tuple(v['types']) in actual
        assert all(r['atom_map']==names for r in records if r['endpoint']==e)
    for label in ('endpoint-1','endpoint-2','endpoint-2-remote','core','two-nucleosides'):
        artifacts.extend(source(PARENT/label/name) for name in
            ('fragment.psf','system.xml','atom_map.json','starting_A.txt','minimum_A.txt'))
    artifacts += [source(PARENT/'comparator_last.prm')]
    for r in records:
        artifacts.extend(r[k] for k in ('qm_source','geometry_source','native'))
        artifacts.extend(r['record'][k] for k in ('model_graph','scan_plan'))
        for key in ('final_result','independent_review','acquisition_plan'):
            if r.get(key): artifacts.append(r[key])
    shutil.copyfile(__file__, INPUTS/'worker.py')
    artifacts.extend(source(p) for p in (INPUTS/'worker.py',
        REPO/'experiments/cpd_anti_additive/prepare_engine_v2.py',
        REPO/'experiments/cpd_anti_additive/sella_pilot.py',
        REPO/'experiments/cpd_anti_additive/validation_gate.py',
        REPO/'experiments/cpd_anti_additive/preliminary_protocol.py'))
    unique = {a['path']: a for a in artifacts}
    plan = dict(schema='nadoc.cpd-anti-conformational-fit.v2.1', created_at=now(),
        stage='conformational', ready=True, case_ids=[r['case_id'] for r in records],
        artifacts=list(unique.values()), inventory=source(inventory_path), parent=str(PARENT.resolve()),
        variables=variables, common_references=inventory['common_reference_proposal'],
        method='One bounded linear fit to independently relaxed baseline MM coordinates, then fresh QM-seeded candidate MM relaxations',
        versions={name:metadata.version(name) for name in ('sella','ase','openmm','scipy','numpy')},
        references=['https://doi.org/10.1002/jcc.23422','https://www.ks.uiuc.edu/Research/vmd/plugins/fftk/'],
        rationale='ffTK-style restrained baseline plus Fourier fitting; retain all exposed branches and independently test the changed relaxed landscape.',
        variable_rationale='Two chemically distinct proper torsions per ordered C1-prime/N1 attachment: the scanned O4-prime/C1-prime/N1/C2 angle and C2-prime/C1-prime/N1/C6, which can distinguish same-scan-angle conformers. No cyclobutane or parent sugar/backbone terms added.',
        bounds=dict(signed_cosine_coefficient_change_kcal=[-5.,5.], phases_deg=[0,180],periodicities=[1,2,3]),
        objective='mean((MM_relative-QM_relative)/1 kcal)^2 + 0.05*mean((delta_K/3 kcal)^2)',
        optimizer=dict(name='scipy.optimize.lsq_linear',method='trf',tol=1e-12,max_iter=200),
        mm=dict(optimizer='Sella order=0, internal=True, eig=False', max_steps=400,max_evaluations=600,
            projected_max_atom_force_kcal_A=.001, torsion_error_deg=.01,
            constraints='Freeze measured QM glycosidic angle for all scan/reference records; remote-unconstrained is fully free',
            seeds='Each baseline and candidate starts independently from its own QM conformer; no nearest-angle branch substitution',
            branch_reporting='All-atom-order-fixed heavy RMSD and all heavy proper torsions; flags use historical 0.25 A / 20 degree descriptors, not a new success shortcut'),
        limits=dict(fit_rounds=1,hard_seconds=7200,automatic_continuations=0),
        representative_minima=['core','endpoint-1','endpoint-2-remote'],
        engineering_fixtures=['core','endpoint-1','endpoint-2','endpoint-2-remote','two-nucleosides'],
        fixed='Charges, LJ, all bond/angle/improper and nonselected proper coefficients; no parent DNA refit',
        acceptance=read(POLICY)['conformational'],
        historical_caveats=inventory['caveats'], prospective_QM_launched=False,
        simulation_ready=False, no_product_integration=True)
    save(INPUTS/'receipt.json',plan)
    lock_inputs('conformational', INPUTS/'receipt.json')
    print('Conformational stage locked:', INPUTS/'receipt.json', flush=True)


def relax_point(folder, point, system, plan, deadline):
    import openmm as mm
    from openmm import unit as u
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella, Constraints
    from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check
    from openmm import app
    folder.mkdir(parents=True,exist_ok=False)
    x0 = np.array(point['geometry_bohr'])*BOHR
    indices = point['record']['torsion_indices']
    constrained = point['branch']!='remote-unconstrained'
    integrator = mm.VerletIntegrator(.001)
    context = mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    psf = app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{point['endpoint']}"/'fragment.psf'))
    evaluations = []
    class MMCalculator(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self, atoms=None, properties=None, system_changes=all_changes):
            super().calculate(atoms,properties,system_changes)
            if len(evaluations)>=plan['mm']['max_evaluations'] or time.monotonic()>deadline:
                raise RuntimeError('Declared MM evaluation/wall budget reached')
            x=atoms.positions.copy()
            context.setPositions(x*u.angstrom)
            state=context.getState(getEnergy=True,getForces=True)
            energy=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            gradient=-np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
            if not np.isfinite(energy) or not np.isfinite(gradient).all():
                raise RuntimeError('Nonfinite MM evaluation')
            evaluations.append(dict(energy=energy,x=x,gradient=gradient))
            self.results=dict(energy=energy/EV_KCAL,forces=-gradient/EV_KCAL)
    atoms=Atoms(point['elements'],positions=x0)
    atoms.calc=MMCalculator()
    constraints=Constraints(atoms)
    if constrained: constraints.fix_dihedral(tuple(indices))
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces))
            gradient=-atoms.get_forces(apply_constraint=False)*EV_KCAL
            if constrained:
                force=projected_metrics(atoms.positions,gradient,indices)['max_projected_atom_gradient']
            else: force=float(np.linalg.norm(gradient,axis=1).max())
            return native and force<plan['mm']['projected_max_atom_force_kcal_A']
    error=None
    converged=False
    try:
        opt=AuditedSella(atoms,constraints=constraints,order=0,internal=True,eig=False,
            delta0=.1,constraints_tol=1e-8,refine_initial_hessian=False,max_cpu_threads=1,
            logfile=str(folder/'sella.log'),trajectory=str(folder/'sella.traj'))
        converged=bool(opt.run(fmax=plan['mm']['projected_max_atom_force_kcal_A']/EV_KCAL,
                               steps=plan['mm']['max_steps']))
    except Exception as exc:
        error=repr(exc)
        (folder/'failure_traceback.txt').write_text(traceback.format_exc())
    if not evaluations: raise RuntimeError(error or 'No MM evaluation')
    # Always assess an actually evaluated geometry, never an unevaluated last step.
    last=evaluations[-1]
    x=last['x']; gradient=last['gradient']
    np.savez_compressed(folder/'evaluations.npz',coordinates_A=np.array([r['x'] for r in evaluations]),
        gradients_kcal_A=np.array([r['gradient'] for r in evaluations]),energies_kcal=np.array([r['energy'] for r in evaluations]))
    np.savetxt(folder/'final_A.txt',x)
    geometry=geometry_check(psf,x0,x)
    metrics=(projected_metrics(x,gradient,indices) if constrained else
             dict(max_projected_atom_gradient=float(np.linalg.norm(gradient,axis=1).max())))
    difference=abs((_dihedral_degrees(*x[indices])-point['actual_dihedral_deg']+180)%360-180)
    match=geometry_match(x0,x,point['elements'],point['heavy_torsion_indices'])
    branch=match['basin_rmsd_A']<=.25 and match['basin_max_torsion_deg']<=20
    passed=bool(converged and metrics['max_projected_atom_gradient']<.001 and
        (not constrained or difference<.01) and geometry['stereo_preserved'] and geometry['graph_distances_passed'])
    result=dict(case_id=point['case_id'],branch=point['branch'],native_optimizer_converged=converged,
        independent_stationarity_and_chemistry_passed=passed,energy_kcal=last['energy'],
        error=error,evaluations=len(evaluations),constraint_applied=constrained,
        torsion_difference_deg=difference,geometry=geometry,projection=metrics,
        branch_descriptors=match,branch_descriptor_match=bool(branch),
        minimum_certified=False,final_geometry=source(folder/'final_A.txt'),
        raw_evaluations=source(folder/'evaluations.npz'))
    save(folder/'assessment.json',result)
    del context,integrator
    print(point['case_id'],'passed',passed,'evaluations',len(evaluations),'branch',bool(branch),flush=True)
    return result,x


def export_parameters(parent, destination, variables, shifts):
    """Replace exact proper keys; retain every other original parameter line."""
    from openmm import app
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params=app.CharmmParameterSet(str(parent))
    chosen={tuple(v['types']) for v in variables}
    rows=[]
    coefficient_records=[]
    for key in sorted(chosen):
        original=params.dihedral_types[key]
        by_n={}
        for term in original:
            assert min(abs(term.phase),abs(term.phase-180),abs(term.phase-360))<1e-7
            assert term.per not in by_n, ('Duplicate effective multiplicity',key)
            by_n[term.per]=float(term.phi_k*math.cos(math.radians(term.phase)))
        for v,shift in zip(variables,shifts):
            if tuple(v['types'])==key:
                before=by_n.get(v['periodicity'],0.)
                by_n[v['periodicity']]=before+float(shift)
                coefficient_records.append(dict(**v,baseline_signed_kcal=before,shift_kcal=float(shift),
                    fitted_signed_kcal=before+float(shift)))
        for n,value in sorted(by_n.items()):
            rows.append(' '.join(key)+f' {abs(value):.15g} {n} {0 if value>=0 else 180}')
    lines=[]; section=None;inserted=False
    for line in parent.read_text().splitlines():
        fields=line.split('!')[0].split()
        if fields and fields[0].upper() in ('BONDS','ANGLES','DIHEDRALS','IMPROPER','IMPROPERS','CMAP','NONBONDED','NBFIX','END','ATOMS'):
            new=fields[0].upper()
            if section=='DIHEDRALS' and new!='DIHEDRALS':
                lines.extend(['! Frozen conformational-v2 fit: selected attachment proper torsions',*rows])
                inserted=True
            section=new
        if section=='DIHEDRALS' and len(fields)>=7:
            key=tuple(fields[:4])
            if min(key,key[::-1]) in chosen: continue
        lines.append(line)
    assert inserted
    destination.write_text('\n'.join(lines)+'\n')
    return coefficient_records


def fit():
    import openmm as mm
    from openmm import app, unit as u
    from scipy.optimize import lsq_linear
    require_fit_ready(stage='conformational')
    policy,plan,round_number=begin_round('conformational',OUT)
    for name,version in plan['versions'].items():
        if metadata.version(name)!=version: raise RuntimeError('Fitting runtime changed: '+name)
    OUT.mkdir(exist_ok=False)
    save(OUT/'plan.json',dict(input_lock=source(STATE/'conformational_input_lock.json'),
        receipt=source(INPUTS/'receipt.json'),round=round_number,worker=source(Path(__file__))))
    deadline=time.monotonic()+plan['limits']['hard_seconds']
    records=read(checked(plan['inventory']))['records']
    variables=plan['variables']
    parent=Path(plan['parent'])
    try:
        systems={e:mm.XmlSerializer.deserialize((parent/f'endpoint-{e}/system.xml').read_text()) for e in (1,2)}
        baseline=[];matrix=[]
        for point in records:
            result,x=relax_point(OUT/'baseline'/point['case_id'],point,systems[point['endpoint']],plan,deadline)
            baseline.append(result);matrix.append(features(x,point['atom_map'],variables))
            save(OUT/'baseline_progress.json',baseline)
        if not all(r['independent_stationarity_and_chemistry_passed'] for r in baseline):
            raise RuntimeError('Baseline MM stationarity/chemistry failed; no fit performed')
        base_energy=np.array([r['energy_kcal'] for r in baseline])
        matrix=relative(matrix,records)
        target=np.array([r['qm_relative_kcal_mol'] for r in records])-relative(base_energy,records)
        design=np.vstack([matrix/math.sqrt(len(records)),math.sqrt(.05/len(variables))*np.eye(len(variables))/3])
        response=np.r_[target/math.sqrt(len(records)),np.zeros(len(variables))]
        solution=lsq_linear(design,response,bounds=(-5.,5.),method='trf',tol=1e-12,max_iter=200)
        shifts=solution.x
        np.savez(OUT/'linear_fit.npz',relative_features=matrix,energy_target=target,design=design,response=response,shifts=shifts)
        candidate=OUT/'candidate';candidate.mkdir()
        coefficients=export_parameters(parent/'comparator_last.prm',candidate/'comparator_last.prm',variables,shifts)
        predicted=base_energy+np.array([features(np.loadtxt(checked(r['final_geometry'])),p['atom_map'],variables)@shifts for p,r in zip(records,baseline)])
        fit_report=dict(optimizer_success=bool(solution.success),message=str(solution.message),iterations=solution.nit,
            optimality=float(solution.optimality),rank=int(np.linalg.matrix_rank(matrix)),coefficients=coefficients,
            at_bounds=[i for i,v in enumerate(shifts) if abs(v)>4.9999],baseline=energy_summary(base_energy,records),
            frozen_coordinate_prediction=energy_summary(predicted,records),
            candidate=source(candidate/'comparator_last.prm'),minimum_certified=False,simulation_ready=False)
        save(OUT/'fit.json',fit_report)
        if not solution.success: raise RuntimeError('Bounded linear solver failed')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            params=app.CharmmParameterSet(str(candidate/'comparator_last.prm'))
        new_systems={}
        for e in (1,2):
            psf=app.CharmmPsfFile(str(parent/f'endpoint-{e}/fragment.psf'))
            new_systems[e]=psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        # Verify exported parameter changes against an independent added Fourier
        # force at every baseline geometry. An endpoint
        # constant shift is expected from converting signed cosine to CHARMM K.
        reload_checks=[];shifts_by_endpoint={}
        analytic_systems={}
        for e in (1,2):
            analytic=mm.XmlSerializer.deserialize(mm.XmlSerializer.serialize(systems[e]))
            correction=mm.CustomTorsionForce('delta*cos(n*theta)')
            correction.addPerTorsionParameter('delta');correction.addPerTorsionParameter('n')
            names=read(parent/f'endpoint-{e}/atom_map.json')
            for v,shift in zip(variables,shifts):
                if all(n in names for n in v['names']):
                    correction.addTorsion(*[names.index(n) for n in v['names']],
                        [float(shift)*4.184,v['periodicity']])
            analytic.addForce(correction);analytic_systems[e]=analytic
        for point,b in zip(records,baseline):
            e=point['endpoint'];x=np.loadtxt(checked(b['final_geometry']))
            values=[]
            for system in (new_systems[e],analytic_systems[e]):
                integ=mm.VerletIntegrator(.001);ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
                ctx.setPositions(x*u.angstrom);state=ctx.getState(getEnergy=True,getForces=True)
                values.append((state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),
                    np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))))
                del ctx,integ
            en=values[0][0]
            d=float(en-b['energy_kcal']-features(x,point['atom_map'],variables)@shifts)
            shifts_by_endpoint.setdefault(e,d)
            err=abs(d-shifts_by_endpoint[e])
            force_error=float(np.max(abs(values[0][1]-values[1][1])))
            basis_error=abs(values[1][0]-b['energy_kcal']-features(x,point['atom_map'],variables)@shifts)
            reload_checks.append(dict(case_id=point['case_id'],energy_residual_kcal=err,
                force_error_kcal_A=force_error,analytic_basis_error_kcal=basis_error))
            assert err<policy['engine']['static_export_energy_kcal']
            assert basis_error<policy['engine']['static_export_energy_kcal']
            assert force_error<policy['engine']['static_export_force_kcal_A']
        save(OUT/'export_checks.json',dict(records=reload_checks,endpoint_constant_offsets=shifts_by_endpoint))
        after=[]
        for point in records:
            result,x=relax_point(OUT/'candidate_profiles'/point['case_id'],point,new_systems[point['endpoint']],plan,deadline)
            after.append(result);save(OUT/'candidate_progress.json',after)
        from experiments.cpd_anti_additive.prepare_engine_v2 import relax
        representatives={}
        for label in plan['engineering_fixtures']:
            folder=candidate/label;folder.mkdir()
            shutil.copyfile(parent/label/'fragment.psf',folder/'fragment.psf')
            names=read(parent/label/'atom_map.json');x=np.loadtxt(parent/label/'starting_A.txt')
            result,_,_=relax(folder,params,names,x,target=x if label!='two-nucleosides' else None)
            representatives[label]=result
            save(OUT/'representative_progress.json',representatives)
            if time.monotonic()>deadline: raise RuntimeError('Declared wall budget reached')
        # Geometry criteria apply to lesion/attachment terms; unmodified parent
        # sugar and cap geometries are reported separately, never silently folded
        # into the lesion scope. All existing bond/angle coefficients remain fixed.
        from experiments.cpd_published_comparator.local_benchmarks import angle
        scope_geometry=[]
        for label in plan['representative_minima']:
            folder=candidate/label;psf=app.CharmmPsfFile(str(folder/'fragment.psf'))
            names=read(folder/'atom_map.json');x=np.loadtxt(folder/'minimum_A.txt');q=np.loadtxt(folder/'starting_A.txt')
            def lesion(ids):
                roles=[names[i].split(':')[1] for i in ids]
                return any("'" not in role and role not in ('CM','HCM1','HCM2','HCM3') for role in roles)
            bonds=[(b.atom1.idx,b.atom2.idx) for b in psf.bond_list]
            angles=[(a.atom1.idx,a.atom2.idx,a.atom3.idx) for a in psf.angle_list]
            data={}
            for included,name in ((True,'lesion_attachment'),(False,'parent_cap')):
                be=[abs(np.linalg.norm(x[a]-x[b])-np.linalg.norm(q[a]-q[b])) for a,b in bonds if lesion((a,b))==included]
                ae=[abs(angle(x,ids)-angle(q,ids)) for ids in angles if lesion(ids)==included]
                data[name]=dict(max_bond_A=float(max(be,default=0)),max_angle_deg=float(max(ae,default=0)))
            data.update(case=label,passed=bool(data['lesion_attachment']['max_bond_A']<=.03 and data['lesion_attachment']['max_angle_deg']<=3))
            scope_geometry.append(data)
        energy=energy_summary([r['energy_kcal'] for r in after],records)
        stationarity=all(r['independent_stationarity_and_chemistry_passed'] for r in after)
        branch=all(r['branch_descriptor_match'] for r in after)
        geometry=all(r['passed'] for r in scope_geometry)
        engineering=all(r['engineering_stability_passed'] for r in representatives.values())
        report=dict(round=round_number,fit=source(OUT/'fit.json'),relaxed_energy=energy,
            all_profile_stationarity_and_chemistry_passed=stationarity,all_branch_descriptors_matched=branch,
            representative_geometry=scope_geometry,representative_geometry_passed=geometry,
            representative_engineering_stability_passed=engineering,
            development_parameter_passed=bool(energy['energy_passed'] and stationarity and branch and geometry),
            prospective_validation_complete=False,conformational_stage_passed=False,
            native_NAMD_tested=False,full_DNA_NAMD_tested=False,preliminary_research_qualified=False,
            simulation_ready=False,finished_at=now(),candidate=source(candidate/'comparator_last.prm'),
            profile_results=source(OUT/'candidate_progress.json'),representatives=source(OUT/'representative_progress.json'),
            next='Review fixed residuals before using the second round; native engineering may proceed only if representative stability passes; no automatic prospective QM or product promotion')
        save(OUT/'assessment.json',report)
        save(candidate/'assessment.json',report)
        print('ASSESSMENT',report,flush=True)
    except Exception as exc:
        save(OUT/'failure.json',dict(error=repr(exc),traceback=traceback.format_exc(),at=now(),simulation_ready=False))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','fit'])
    args=parser.parse_args()
    globals()[args.action]()
