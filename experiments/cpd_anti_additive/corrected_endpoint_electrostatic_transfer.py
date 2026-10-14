"""Two fixed-conformer HF diagnostics for unchanged corrected-core charges.

This is exposed development transfer evidence, not blind validation, a new
charge fit, or minimum certification of either sugar-bearing conformer.
"""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.corrected_electrostatic_pilot import audit_hf_native, HF_BOHR_ANGSTROM
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_native import audit_native, NUMBER
from backend.parameterization.photoproduct_esp import build_esp_grid

CAMPAIGN = (REPO / '.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT = CAMPAIGN / 'electrostatic-endpoint-transfer-v1'
PYTHON = Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')
BOHR = HF_BOHR_ANGSTROM


def transfer_charges(keys, core, sugar):
    """Copy exact core charges; only sugar atom names can use the NA template."""
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate endpoint atom key')
    values = []
    for key in keys:
        name = key.split(':')[1]
        if key in core:
            values.append(float(core[key]))
        elif "'" in name and key.startswith('1:') and name in sugar:
            values.append(float(sugar[name]['charge_e']))
        else:
            raise ValueError(f'Unmapped atom {key}')
    q = np.array(values)
    if not np.isfinite(q).all() or abs(q.sum()) > 1e-10:
        raise ValueError('Endpoint charges must be finite and neutral')
    return q


def electrostatic_metrics(xyz, charge, grid, potential, dipole_au, region_masks):
    xyz = np.asarray(xyz, float); charge = np.asarray(charge, float)
    grid = np.asarray(grid, float); potential = np.asarray(potential, float)
    dipole_au = np.asarray(dipole_au, float)
    if (xyz.shape != (len(charge), 3) or grid.ndim != 2 or grid.shape[1] != 3
            or potential.shape != (len(grid),) or dipole_au.shape != (3,)
            or not all(np.isfinite(v).all() for v in (xyz,charge,grid,potential,dipole_au))
            or abs(charge.sum()) > 1e-10):
        raise ValueError('Invalid neutral electrostatic diagnostic')
    distances = np.linalg.norm(grid[:, None, :] - xyz[None, :, :], axis=2)
    if np.any(distances <= 0):
        raise ValueError('ESP grid intersects an atom')
    predicted = (BOHR / distances) @ charge
    error = predicted - potential
    dipole = charge @ xyz * (2.541746473 / BOHR)
    qm = dipole_au * 2.541746473
    regions = {}
    for label, mask in region_masks.items():
        mask = np.asarray(mask, bool)
        if mask.shape != potential.shape or not mask.any():
            raise ValueError('Invalid ESP region')
        denominator = np.linalg.norm(potential[mask])
        regions[label] = dict(points=int(mask.sum()), rmse_au=float(np.sqrt(np.mean(error[mask]**2))),
                             relative_rmse=float(np.linalg.norm(error[mask])/denominator) if denominator else None)
    return dict(net_charge_e=float(charge.sum()), mm_dipole_debye=dipole.tolist(),
                qm_dipole_debye=qm.tolist(), dipole_vector_error_debye=float(np.linalg.norm(dipole-qm)),
                mm_dipole_magnitude_debye=float(np.linalg.norm(dipole)),
                qm_dipole_magnitude_debye=float(np.linalg.norm(qm)), esp_regions=regions)


def native_checks(text, inp, energy, dipole):
    audit = audit_hf_native(text, inp['elements'], inp['geometry_angstrom'], 'df', energy, dipole)
    assert 'Threads set to 4' in text and 'Memory set to   4.000 GiB' in text
    basis = re.search(r'Basis Set: 6-31G\(D\)\n\s*Blend:\s*6-31G\(D\)\n\s*Number of shells:\s*\d+\n\s*Number of basis functions:\s*(\d+)\n\s*Number of Cartesian functions:\s*(\d+)\n\s*Spherical Harmonics\?:\s*(true|false)', text)
    assert basis and basis.groups() == ('449', '449', 'false')
    iterations = re.findall(r'@DF-RHF iter\s+(\d+):\s*('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')', text)
    assert iterations
    iteration, _, delta, density = iterations[-1]
    assert abs(float(delta)) <= 1.001e-12 and abs(float(density)) <= 1.001e-12
    return dict(**audit, cartesian_basis_functions=449, last_iteration=int(iteration),
                last_energy_change_hartree=float(delta), last_density_residual=float(density))


def context(root):
    require_archive(root)
    plan = read(root/'plan.json')
    if checked(plan['worker']) != Path(__file__).resolve():
        raise ValueError('Frozen worker changed')
    for source in plan['sources']:
        checked(source)
    auth = read(checked(plan['authorization']))
    if not auth['user_authorized'] or auth['compute_policy']['cloud_spending_usd'] != 0:
        raise ValueError('Missing local authority')
    if (plan['hard_seconds'], plan['task_timeout_seconds'], len(plan['tasks'])) != (900, 300, 2):
        raise ValueError('Finite allocation changed')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):
        raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution = read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan']) != root/'plan.json':
            raise ValueError('Launched plan changed')
    return plan, read(checked(plan['model']))


def prepare():
    from openmm import app
    import psi4
    require_archive(CAMPAIGN)
    fitroot = CAMPAIGN/'charge-core-fit-v1'
    audit = read(fitroot/'completion_audit.json')
    assert audit['passed'] and audit['transfer_diagnostic_admitted']
    candidate = read(checked(audit['candidate']))
    policy = read(checked(candidate['policy']))
    model_path = CAMPAIGN/'endpoint-seeds-v2/endpoint-1/model_manifest.json'
    model = read(model_path)
    profile_path = CAMPAIGN/'glycosidic-branch-profile-v1/completed_profile_review.json'
    profile = read(profile_path)
    ROOT.mkdir(); (ROOT/'tmp').mkdir()
    shutil.copy2(Path(__file__), ROOT/'executed_source.py')

    # Native, source-pinned CHARMM terminal deoxythymidine supplies only sugar
    # charges. No legacy anti fitted data or PSF is used.
    topology = REPO/'backend/data/forcefield/top_all36_na.rtf'
    executable = Path(shutil.which('psfgen')).resolve()
    tcl = f'''package require psfgen
resetpsf
topology {topology}
segment S {{
 first 5TER
 last 3TER
 residue 1 THY
}}
patch DEO5 S:1
regenerate angles dihedrals
writepsf {ROOT}/sugar_template.psf
exit
'''
    (ROOT/'sugar_template.tcl').write_text(tcl)
    command = subprocess.run([str(executable), str(ROOT/'sugar_template.tcl')],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    (ROOT/'sugar_template.log').write_text(command.stdout+command.stderr)
    command.check_returncode()
    template = app.CharmmPsfFile(str(ROOT/'sugar_template.psf'))
    sugar = {a.name:dict(atom_type=a.attype,charge_e=float(a.charge))
             for a in template.atom_list if "'" in a.name}
    assert len(sugar) == 17 and abs(sum(v['charge_e'] for v in sugar.values())) < 1e-10
    keys = model['atom_keys']
    baseline = {row['atom']:row['charge_e'] for row in policy['baseline_assignments']}
    charges = dict(baseline=transfer_charges(keys, baseline, sugar).tolist(),
                   candidate=transfer_charges(keys, candidate['charges_e'], sugar).tolist())
    assert len(keys) == 49 and len([k for k in keys if k in candidate['charges_e']]) == 32
    assert charges['candidate'][keys.index("1:C1'")] == .16
    assignments = dict(at=now(),atom_keys=keys,sugar=sugar,charge_vectors_e=charges,
                       candidate=pin(fitroot/'candidate_charges.json'),
                       sugar_sources=[pin(topology),pin(executable),pin(ROOT/'sugar_template.tcl'),
                                      pin(ROOT/'sugar_template.psf'),pin(ROOT/'sugar_template.log')],
                       scope='Exact 28 CPD-base charges and opposite neutral methyl cap transferred; 17 sugar/OH-cap atoms use unchanged native CHARMM NA charges. C1-prime remains +0.16e.')
    save(ROOT/'charge_assignment.json', assignments)
    sources = [pin(fitroot/'completion_audit.json'), pin(fitroot/'candidate_charges.json'),candidate['policy'],
               pin(model_path),model['sdf'],model['graph'],model['definition'],pin(profile_path),
               pin(CAMPAIGN/'endpoint_reference_design_v1.json'),
               pin(CAMPAIGN/'electrostatic-core-pilot-v1/method_choice.json'),
               pin(ROOT/'charge_assignment.json'),*assignments['sugar_sources']]
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','corrected_electrostatic_pilot.py',
                 'prepare_corrected_endpoints.py','endpoint_native.py','audit_corrected_core_stage1.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    sources.append(pin(REPO/'backend/parameterization/photoproduct_esp.py'))
    tasks = []; geometries = []
    for offset, label in [(-30,'minus30'), (30,'plus30')]:
        point = next(p for p in profile['points'] if p['offset_degrees'] == offset)
        prior = read(checked(point['audit'])); result = read(checked(point['result']))
        assert prior['passed'] and prior['constrained_stationary'] and prior['last_accepted_result'] == point['result']
        assert result['geometry'] == point['geometry']
        x = np.load(checked(point['geometry']))
        identity = audit_endpoint(x, model); assert identity['passed']
        e, g, native = audit_native(checked(result['native']).read_text(), model['elements'], x)
        assert abs(e-result['energy_hartree']) < 1e-9
        assert np.max(abs(g-np.array(result['gradient_hartree_bohr']))) < 5.1e-13
        xa = x*BOHR
        folder = ROOT/label; folder.mkdir(); (folder/'scratch').mkdir()
        grid = np.array(build_esp_grid([(el,*v) for el,v in zip(model['elements'],xa)],
                                      radius_scales=[1.4,1.6,1.8,2.0],directions_per_atom=50))
        np.savetxt(folder/'grid.dat',grid,fmt='%.10f')
        grid = np.loadtxt(folder/'grid.dat')
        nearest = np.argmin(np.linalg.norm(grid[:,None,:]-xa[None,:,:],axis=2),axis=1)
        sugar_indices = [i for i,k in enumerate(keys) if "'" in k]
        cap_indices = [i for i,k in enumerate(keys) if k in ['2:CM','2:HCM1','2:HCM2','2:HCM3']]
        regions = dict(all=np.ones(len(grid),bool).tolist(),
                       nearest_base=(~np.isin(nearest,sugar_indices+cap_indices)).tolist(),
                       nearest_sugar=np.isin(nearest,sugar_indices).tolist(),
                       nearest_methyl_cap=np.isin(nearest,cap_indices).tolist())
        assert all(any(mask) for mask in regions.values())
        inp = dict(elements=model['elements'],atom_keys=keys,geometry_angstrom=xa.tolist(),
                   source_geometry=point['geometry'],charge=0,multiplicity=1,method='hf',
                   options=dict(basis='6-31G(d)',reference='rhf',scf_type='df',
                                e_convergence=1e-12,d_convergence=1e-12,maxiter=300),
                   grid=pin(folder/'grid.dat'),region_masks=regions)
        # Check the installed engine's coordinate conversion without an SCF.
        text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(model['elements'],xa))
        molecule=psi4.geometry('0 1\n'+text+'\nunits angstrom\nsymmetry c1\nno_com\nno_reorient')
        assert np.max(abs(np.asarray(molecule.geometry())-x)) < 5e-14
        save(folder/'input.json', inp)
        tasks.append(dict(label=label,offset_degrees=offset,input=pin(folder/'input.json'),
                          prior_audit=point['audit'],prior_result=point['result']))
        sources.extend([point['audit'],point['result'],point['geometry'],result['native'],
                        pin(folder/'input.json'),inp['grid']])
        geometries.append(dict(label=label,identity=identity,mp2_native=native,grid_points=len(grid),
                               regions={k:sum(v) for k,v in regions.items()}))
    plan = dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,
                authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),model=pin(model_path),
                charge_assignment=pin(ROOT/'charge_assignment.json'),tasks=tasks,
                selection='Two existing constrained-stationary endpoint conformers at -30/+30 degrees span the acquired glycosidic interval. No new geometry optimization, holdout, water curve or fitting.',
                justification='Core water/dipole fit passes, but O4 is at its bound, ESP error remains substantial, and the data Jacobian is poorly conditioned. Compare unchanged candidate with the initial hypothesis in sugar-bearing environments before spending a second fit round.',
                interpretation='Compare candidate and baseline dipole vector/magnitude and ESP errors overall and by nearest-atom region. Region attribution is geometric, not a unique quantum decomposition. This diagnostic has numerical validity checks, not a newly invented production-acceptance threshold. Audit residuals before any refit or extra water acquisition.',
                method_scope='Same HF/6-31G(d) DF settings as calibrated core; core DF/DIRECT agreement is not an endpoint-specific error bound. Unscaled HF dipoles; no counterpoise, water corrections or dipole scaling apply to these isolated properties.',
                psi4_version=psi4.__version__,maximum_new_scf=2,hard_seconds=900,task_timeout_seconds=300,
                expected_seconds=180,expected_time_basis='Core DF 20.88sec scaled by (449/332)^3 for two endpoints, plus startup/scheduling margin; first endpoint timing remains unmeasured.',
                threads=4,psi4_memory_gib=4,service_memory_gib=8,
                completion_semantics='Two fixed-geometry HF property calculations; audit actual native evidence and unchanged-charge transfer residuals. Service success is neither physical transfer acceptance nor minimum certification.',
                total_electrostatic_conformers_after=3,maximum_electrostatic_conformers=3,
                second_fit_admitted=False,heldout_accessed=False,full_parameter_hash_lock=False,
                minimum_certified=False,charge_transfer_validated=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json', plan)
    save(ROOT/'preflight.json', dict(at=now(),passed=True,geometries=geometries,
                                   exact_charge_transfer_verified=True,sugar_template_neutral=True,
                                   archive_mount_verified=True,new_qm_evaluations=0))
    print(ROOT)


def worker(root, label):
    plan, model = context(root)
    task = next(t for t in plan['tasks'] if t['label'] == label)
    inp = read(checked(task['input'])); folder = root/label
    x = np.array(inp['geometry_angstrom']); checked(inp['grid'])
    assert np.max(abs(x/BOHR-np.load(checked(inp['source_geometry'])))) < 5e-14
    assert audit_endpoint(x/BOHR, model)['passed']
    require_archive(folder/'scratch')
    with (folder/'started.json').open('x') as f:
        f.write(now()+'\n')
    import psi4
    assert psi4.__version__ == plan['psi4_version'] and psi4.constants.bohr2angstroms == BOHR
    os.chdir(folder)
    psi4.set_output_file(str(folder/'output.dat'),False)
    psi4.set_memory('4 GiB'); psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(folder/'scratch'))
    psi4.set_options(inp['options'])
    text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(inp['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits angstrom\nsymmetry c1\nno_com\nno_reorient')
    start=time.monotonic()
    energy,wfn=psi4.energy('hf',molecule=molecule,return_wfn=True)
    psi4.oeprop(wfn,'DIPOLE','GRID_ESP')
    dipole=np.asarray(wfn.variable('DIPOLE'))
    actual=np.asarray(wfn.molecule().geometry())*BOHR
    psi4.core.print_out('NADOC_DIPOLE_AU %.12f %.12f %.12f\n'%tuple(dipole))
    np.save(folder/'returned_geometry_angstrom.npy',actual)
    # Retain returned evidence even if downstream parsing fails.
    raw=dict(at=now(),input=task['input'],energy_hartree=float(energy),dipole_au=dipole.tolist(),
             returned_geometry=pin(folder/'returned_geometry_angstrom.npy'),
             grid=inp['grid'],potentials=pin(folder/'grid_esp.dat'),wall_seconds=time.monotonic()-start)
    save(folder/'raw_result.json',raw)
    psi4.core.clean();psi4.core.flush_outfile();psi4.core.close_outfile()
    audit=native_checks((folder/'output.dat').read_text(),inp,energy,dipole)
    assert np.max(abs(actual-x)) < 1e-12
    assert audit_endpoint(actual/BOHR,model)['passed']
    potential=np.loadtxt(checked(raw['potentials']))
    assert potential.shape == (len(np.loadtxt(checked(inp['grid']))),) and np.isfinite(potential).all()
    save(folder/'result.json',dict(**raw,native=pin(folder/'output.dat'),native_audit=audit,
                                  minimum_certified=False,simulation_ready=False))


def review(root):
    plan, model = context(root)
    assignment=read(checked(plan['charge_assignment']))
    records=[]
    for task in plan['tasks']:
        folder=root/task['label'];result=read(folder/'result.json');inp=read(checked(task['input']))
        assert result['input'] == task['input'] and result['grid'] == inp['grid']
        native=native_checks(checked(result['native']).read_text(),inp,result['energy_hartree'],result['dipole_au'])
        x=np.array(inp['geometry_angstrom'])
        assert np.max(abs(np.load(checked(result['returned_geometry']))-x)) < 1e-12
        assert audit_endpoint(x/BOHR,model)['passed']
        grid=np.loadtxt(checked(result['grid']));potential=np.loadtxt(checked(result['potentials']))
        metrics={name:electrostatic_metrics(x,q,grid,potential,result['dipole_au'],inp['region_masks'])
                 for name,q in assignment['charge_vectors_e'].items()}
        records.append(dict(label=task['label'],result=pin(folder/'result.json'),native=native,
                            wall_seconds=result['wall_seconds'],metrics=metrics))
    report=dict(at=now(),plan=pin(root/'plan.json'),native_evidence_passed=True,records=records,
                requires_completion_audit=True,second_fit_admitted=False,charge_transfer_validated=False,
                minimum_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(root/'independent_review.json',report)
    return report


def run(root):
    plan,_=context(root)
    with (root/'started.json').open('x') as f:
        f.write(now()+'\n')
    deadline=read(root/'launch_receipt.json')['deadline_epoch'];completed=[];error=None
    try:
        for task in plan['tasks']:
            context(root)
            if deadline-time.time() < plan['task_timeout_seconds']+30:
                raise RuntimeError('Insufficient allocation for next SCF')
            folder=root/task['label']
            env={**os.environ,'TMPDIR':str(folder/'scratch'),'PSI_SCRATCH':str(folder/'scratch')}
            with (folder/'runner.log').open('x') as log:
                child=subprocess.run([str(PYTHON),str(checked(plan['worker'])),'worker',str(root),'--label',task['label']],
                                     cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=plan['task_timeout_seconds'])
            if child.returncode:
                raise RuntimeError(f"Native task {task['label']} failed: {child.returncode}")
            completed.append(pin(folder/'result.json'))
            save(root/'progress.json',dict(at=now(),completed=completed))
        review(root)
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),completed=len(completed),error=error,
                                    requires_completion_audit=True,charge_transfer_validated=False,
                                    minimum_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    plan,_=context(root)
    assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):
        raise RuntimeError('Another CPD calculation active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(line.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for line in processes):
        raise RuntimeError('Another native job active')
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    if available < 12*1024**3 or shutil.disk_usage(root).free < 30*1024**3:
        raise RuntimeError('Insufficient resource headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-electrostatic-endpoint-transfer-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),
         expected_seconds=plan['expected_seconds'],review_deadline_epoch=start+720,
         review_deadline_id='endpoint-electrostatic-transfer-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],
         command=[str(PYTHON),str(checked(plan['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,
         memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=plan['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,
         available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),
         supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G',
        '--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s',
        '--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',
        f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1',
        '--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',
        f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp',
        '/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','launch','run','worker','review'])
    parser.add_argument('root',nargs='?',type=Path,default=ROOT);parser.add_argument('--label')
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='worker':worker(root,args.label)
    elif args.action=='run':sys.exit(run(root))
    elif args.action=='review':print(review(root))
    else:launch(root)
