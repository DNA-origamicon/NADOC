"""Prepare and launch only a specifically authorized corrected-core stage-one job."""
from __future__ import annotations
import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    BOHR, FORCE_FACTOR, HARTREE_EV, checked, geometry_audit, now, pin, read, save, xyz,
)

CAMPAIGN = (REPO/".development-artifacts/cpd-corrected-cis-anti-i-refinement-v1").resolve()
PROPOSAL = REPO/"docs/audits/cpd_corrected_cis_anti_i_refinement_plan_20261010.json"
RUNTIME = Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def prepare(phase, attempt=1):
    import psi4
    from rdkit import Chem
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella
    from backend.parameterization.photoproduct_models import _ccd_atom_rows
    from backend.parameterization.photoproduct_stereo_candidates import (
        _candidate_full_molecule, _cip_codes, _prune_to_n1_methyl_model, _stable_atom_map,
    )

    proposal = read(PROPOSAL)
    sources = []
    for ref in proposal['source_pins']:
        path = Path(ref['path'])
        if not path.is_absolute(): path = REPO/path
        sources.append(pin(checked({**ref, 'path': str(path)})))
    CAMPAIGN.mkdir(exist_ok=True)
    root = CAMPAIGN/(phase if attempt == 1 else f'{phase}-v{attempt}')
    root.mkdir(exist_ok=False)
    construction = (REPO/'.development-artifacts/cpd-anti-definition-correction-v1/constructed').resolve()
    model = construction/'tt-cpd-cis-anti-i'
    definition = REPO/'backend/data/forcefield/photoproducts/tt-cpd-cis-anti-i/chemical_definition.json'
    keys = read(model/'atom_map.json')
    coords = read(model/'coordinates.json')
    mol = Chem.MolFromMolFile(str(model/'construction.sdf'), removeHs=False)
    elements = [a.GetSymbol() for a in mol.GetAtoms()]
    if len(keys) != 36 or len(set(keys)) != 36 or Chem.GetFormalCharge(mol) != 0:
        raise ValueError('Core atom map or charge failure')
    crosslinks = {tuple(sorted((keys[b.GetBeginAtomIdx()], keys[b.GetEndAtomIdx()])))
                 for b in mol.GetBonds()
                 if keys[b.GetBeginAtomIdx()].split(':')[0] != keys[b.GetEndAtomIdx()].split(':')[0]}
    if crosslinks != {('1:C5','2:C6'), ('1:C6','2:C5')}:
        raise ValueError('Wrong anti crosslinks')
    source_refs = read(construction/'audit.json')['sources']
    paths = {Path(r['path']).name: checked(r) for r in source_refs}
    source_mol = Chem.MolFromMolFile(str(paths['TTD_ideal.sdf']), removeHs=False)
    for atom, row in zip(source_mol.GetAtoms(), _ccd_atom_rows(paths['TTD.cif'])):
        atom.SetProp('ccd_atom_id', row['_chem_comp_atom.atom_id'])
    full = _candidate_full_molecule(source_mol, 'cis-anti-I')
    cip = _cip_codes(full)
    if cip != dict(zip(('C5','C6','C5T','C6T'), ('S','R','S','R'))):
        raise ValueError('Accurate full-graph CIP reconstruction failed')
    canonical = REPO/'backend/data/forcefield/photoproducts/tt-cpd-cis-syn/chemical_definition.json'
    rebuilt = _prune_to_n1_methyl_model(full, read(canonical))
    if (_stable_atom_map(rebuilt, read(canonical)) != keys or
            Chem.MolToInchiKey(rebuilt) != Chem.MolToInchiKey(mol)):
        raise ValueError('Capped model differs from corrected full graph')
    options = dict(basis='6-31G(d)', reference='rhf', scf_type='df', mp2_type='df',
                   freeze_core=True, e_convergence=1e-12, d_convergence=1e-12,
                   solver_convergence=1e-10, maxiter=300)
    for filename in ['corrected_core_stage1.py','prepare_corrected_core_stage1.py']:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/filename,root/filename)
    sources += source_refs + [pin(canonical), pin(root/'prepare_corrected_core_stage1.py')]
    for filename in ['backend/parameterization/photoproduct_stereo_candidates.py',
                     'backend/parameterization/photoproduct_models.py']:
        sources.append(pin(REPO/filename))
    import sella, ase
    sources += [pin(p) for p in sorted(Path(sella.__file__).parent.rglob('*.py'))]
    sources += [pin(Path(ase.__file__).parent/n) for n in
                ('atoms.py','calculators/calculator.py','optimize/optimize.py')]
    basis_dir = Path(psi4.core.get_datadir())/'basis'
    sources += [pin(p) for p in sorted(basis_dir.glob('*.gbs'))]
    plan = dict(schema='nadoc.corrected-core-stage1.v1', phase=phase, created_at=now(),
                campaign_root=str(CAMPAIGN), sources=sources, definition=pin(definition),
                sdf=pin(model/'construction.sdf'), atom_keys=keys, elements=elements,
                geometry_bohr=(np.array([coords[k] for k in keys])/BOHR).tolist(),
                options=options, psi4_version=psi4.__version__, runtime_python=str(RUNTIME),
                versions={n: metadata.version(n) for n in ('sella','ase','numpy','scipy','rdkit','jax','jaxlib')},
                scratch=str(root/'scratch'), hard_seconds=3600 if phase=='pilot' else 14400,
                max_new_gradients=1 if phase=='pilot' else 60,
                restart='Last accepted geometry; fresh Sella history if resumed in a separately approved attempt.',
                minimum_certified=False, simulation_ready=False)
    if phase == 'optimization':
        decision = CAMPAIGN/'pilot_continuation_decision.json'
        review = read(checked(read(decision)['pilot_review']))
        if not read(decision)['proceed'] or not review['passed']:
            raise ValueError('Pilot not admitted')
        result = read(checked(review['last_result']))
        plan.update(pilot_continuation_decision=pin(decision), seed_gradient=review['last_result'],
                    geometry_bohr=np.load(checked(result['geometry'])).tolist())
        plan['sources'] += [pin(decision), read(decision)['pilot_review'], review['last_result']]
    audit = geometry_audit(plan['geometry_bohr'], plan)
    if not audit['passed']: raise ValueError('Seed geometry failed')
    save(root/'starting_audit.json', dict(full_dna_graph_cip=cip, **audit))
    (root/'starting.xyz').write_text(xyz(elements, plan['geometry_bohr'], 'Corrected static core; no minimum claim'))
    save(root/'identity_review_packet.json', dict(status='pending_human_review', product_id='tt-cpd-cis-anti-i',
         definition=pin(definition), sdf=plan['sdf'], atom_map=pin(model/'atom_map.json'),
         exact_geometry=pin(root/'starting.xyz'), automated_audit=pin(root/'starting_audit.json'),
         full_dna_graph_cip=cip, minimum_certified=False, registry_gate_changed=False,
         scope='Fresh candidate identity packet. Compute authorization is not human chemical-definition approval.'))

    # Pin resolved basis definitions without evaluating electronic energy or gradients.
    psi4.set_output_file(str(root/'basis_preflight.dat'), False)
    psi4.set_options(options)
    molecule = psi4.geometry('0 1\n'+'\n'.join(el+' '+' '.join(map(str,pos)) for el,pos in
                            zip(elements, plan['geometry_bohr']))+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    resolved = {}
    for key, role in [('BASIS','ORBITAL'), ('DF_BASIS_SCF','JKFIT'), ('DF_BASIS_MP2','RIFIT')]:
        basis = psi4.core.BasisSet.build(molecule, key, '6-31G(d)' if key=='BASIS' else '', role, '6-31G(d)')
        resolved[key] = dict(name=basis.name(), nbf=basis.nbf())
        basis.print_detail_out()
    psi4.core.flush_outfile()
    plan['resolved_basis'] = resolved
    plan['sources'].append(pin(root/'basis_preflight.dat'))

    # An independent analytic potential exercises the installed optimizer, no QM.
    toy = Atoms('H2', positions=[[0,0,0],[.9,0,0]])
    class BondPotential(Calculator):
        implemented_properties = ['energy','forces']
        def calculate(self, atoms=None, properties=('energy','forces'), system_changes=all_changes):
            super().calculate(atoms, properties, system_changes)
            delta = self.atoms.positions[1]-self.atoms.positions[0]
            length = np.linalg.norm(delta)
            force = (length-.74)*delta/length
            self.results = dict(energy=.5*(length-.74)**2, forces=np.array([force,-force]))
    toy.calc = BondPotential()
    optimizer = Sella(toy, order=0, internal=True, eig=False, max_cpu_threads=1,
                      logfile=str(root/'analytic_preflight.log'))
    passed = bool(optimizer.run(fmax=1e-7, steps=20))
    if not passed or abs(toy.get_distance(0,1)-.74)>1e-6:
        raise ValueError('Analytic unconstrained optimizer preflight failed')
    direction = np.arange(108).reshape(36,3)/108
    gradient = np.linspace(-.1,.1,108).reshape(36,3)
    h = 1e-5
    finite_difference = (np.sum(gradient*direction*h/BOHR)*HARTREE_EV-
                         np.sum(gradient*(-direction)*h/BOHR)*HARTREE_EV)/(2*h)
    if not np.isclose(finite_difference, np.sum(gradient*FORCE_FACTOR*direction), atol=1e-12):
        raise ValueError('Energy-force conversion failed')
    save(root/'preflight.json', dict(passed=True, new_qm_evaluations=0,
         analytic_optimizer_passed=passed, unit_conversion_passed=True,
         identity=pin(root/'starting_audit.json'), basis=resolved))
    save(root/'plan.json', plan)
    save(root/'authorization.json', dict(recorded_at=now(), user_authorized=True,
         user_instruction='Ok, proceed with the first stage.', approved_proposal=pin(PROPOSAL),
         execution_plan=pin(root/'plan.json'), worker=pin(root/'corrected_core_stage1.py'),
         preflight=pin(root/'preflight.json'), no_cloud=True, phase=phase,
         scope='First stage only: one <=1h gradient pilot, then one <=4h/60-new-gradient optimization after pilot audit.'))
    print(root)


def launch(phase, attempt=1):
    root = CAMPAIGN/(phase if attempt == 1 else f'{phase}-v{attempt}')
    from experiments.cpd_anti_additive.corrected_core_stage1 import validate
    # Validate through the actual frozen worker so its path check remains meaningful.
    import importlib.util
    spec = importlib.util.spec_from_file_location('frozen_stage1', root/'corrected_core_stage1.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    plan = module.validate(root)
    mem = {line.split(':')[0]: int(line.split()[1])*1024 for line in
           Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','SwapFree:'))}
    if mem['MemAvailable'] < 12*1024**3:
        raise RuntimeError('Available RAM below approved 12 GiB admission floor')
    if shutil.disk_usage(CAMPAIGN).free < 20*1024**3:
        raise RuntimeError('Insufficient Archive space')
    units = subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line for line in units.splitlines()):
        raise RuntimeError('A CPD service is already running; review it before launch')
    if subprocess.run(['pgrep','-x','namd3'], capture_output=True).returncode == 0:
        raise RuntimeError('NAMD is already running')
    codex = shutil.which('codex')
    if not codex: raise RuntimeError('Completion watcher executable unavailable')
    thread = os.environ['CODEX_THREAD_ID']
    service = CAMPAIGN/(root.name+'-service')
    service.mkdir(exist_ok=False)
    for old,new in [('launch.py','supervisor.py'), ('watch.py','watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    unit = f'cpd-corrected-anti1-{phase}-v{attempt}'
    seconds = plan['hard_seconds']
    stamp = time.time()
    (root/'tmp').mkdir(exist_ok=False)
    save(service/'watcher_config.json', dict(codex_executable=str(Path(codex).resolve()),
         expected_seconds=seconds-300, review_deadline_epoch=stamp+seconds-120,
         review_deadline_id='corrected-core-'+phase, self_test=False))
    command = [str(RUNTIME),str(root/'corrected_core_stage1.py'),'run',str(root)]
    save(service/'execution_plan.json', dict(unit=unit,thread=thread,command=command,cwd=str(root),
         runtime_hours=seconds/3600, memory_gib=8, omp_threads=4,
         plan=pin(root/'plan.json'), completion_semantics='Native task only; audit stage1 identity, stationarity and measured cost. No Hessian or later stage authorized.'))
    save(root/'launch_receipt.json', dict(launched_at=now(), deadline_epoch=stamp+seconds,
         service_root=str(service), unit=unit, prelaunch_memory=mem,
         execution_plan=pin(service/'execution_plan.json'),
         supervisor=pin(service/'supervisor.py'), watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G',
         '--property=MemorySwapMax=0',f'--property=RuntimeMaxSec={seconds}s',
         '--property=TimeoutStopSec=15s','--property=KillMode=control-group',
         '--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}',
         '--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1',
         '--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','--setenv=JAX_PLATFORMS=cpu',
         f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp',
         '/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)], check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','launch'))
    parser.add_argument('phase', choices=('pilot','optimization'))
    parser.add_argument('--attempt', type=int, choices=(1,2), default=1,
                        help='Explicit new directory; never retries native work automatically')
    args=parser.parse_args()
    (prepare if args.action=='prepare' else launch)(args.phase,args.attempt)
