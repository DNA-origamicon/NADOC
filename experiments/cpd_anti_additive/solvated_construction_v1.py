"""Isolated paired solvent construction; fixed parameters, finite budget, no MD.

The unpatched control uses the frozen reactant coordinates, with their known
source defects. It is a construction control, not an equilibrated reference.
"""
import argparse
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.spatial import cKDTree

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now
from experiments.cpd_anti_additive.preliminary_protocol import POLICY, require
from experiments.cpd_anti_additive.run_engine_v2 import binary, read_binary
from experiments.cpd_anti_additive.review_source_conditioning_v1 import adjacency, signed_volume
from experiments.cpd_anti_additive.placement_review_v2 import audit, ring_names_for
from backend.core.namd_solvate import _Water, _parse_gro, _extend_psf, _build_solvated_pdb

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-solvated-construction-v1c'
MODEL = ART / 'cpd-anti-fitted-dna-v2-r1'
TOPO = ART / 'cpd-anti-dna-topology-v2b'
SOLVENT = ART / 'cpd-anti-solvent-reference-v1'
NAMD = Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')
GMX = Path('/home/jojo/Applications/gromacs-2024.3-cuda/bin/gmx')
WATER = Path('/home/jojo/Applications/gromacs-2024.3-cuda/share/gromacs/top/spc216.gro')
N = 3043


def pdb_text(psf, x):
    out = io.StringIO()
    app.PDBFile.writeFile(psf.topology, x*u.angstrom, out, keepIds=True)
    # PDB is only an index/reference container; doubles in start.coor drive NAMD.
    return out.getvalue()


def params(paths):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return app.CharmmParameterSet(*(str(p) for p in paths))


def atom_identity(a):
    return (a.system, a.residue.idx, a.name, a.attype, a.charge,
            a.mass.value_in_unit(u.dalton))


def geometry(folder, x):
    """Check solute independently of the water's rigid constraint forces."""
    spec = read(folder/'geometry_reference.json')
    x = x[:N]
    stereo = [r['label'] for r in spec['centers']
              if signed_volume(x[r['indices']])*r['reference_A3'] <= 0]
    ratios = np.array([np.linalg.norm(x[a]-x[b])/eq for a,b,eq in spec['bonds_equilibrium_A']])
    contacts = audit(x, spec['bonds'], spec['rings'], list(range(N)), spec['elements'], spec['labels'])
    base = spec['base_indices']
    ref = np.loadtxt(folder/'source_A.txt')
    displacement = float(np.linalg.norm(x[base]-ref[base], axis=1).max())
    return dict(stereo_passed=not stereo, inverted_centers=stereo, centers_checked=len(spec['centers']),
                bond_ratio_range=[float(min(ratios)),float(max(ratios))],
                bond_integrity_passed=bool(min(ratios)>.7 and max(ratios)<1.3),
                contacts=contacts, max_base_displacement_A=displacement,
                product_displacement_screen_passed=displacement<=3.5)


def prepare():
    require('conformational')
    assert read(MODEL/'assessment.json')['full_DNA_static_NAMD_passed']
    ROOT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), ROOT/'worker.py')
    model_plan = read(MODEL/'plan.json')
    parent_paths = [checked(r) for r in model_plan['parent_forcefields']]
    sources = parent_paths + [MODEL/'anti.psf',MODEL/'anti_dna_overlay.prm',MODEL/'starting_A.txt',
        TOPO/'reactant.psf',TOPO/'reactant.pdb',TOPO/'assessment.json',
        ART/'cpd-anti-placement-review-v2/current_A.txt',
        ART/'cpd-anti-fitted-conditioning-v2/assessment.json',
        ART/'cpd-anti-source-conditioning-v1b/assessment.json',
        ART/'cpd-anti-conformational-native-service-v2-r1/completion_delivery_verified.json',
        SOLVENT/'toppar_water_ions.str',SOLVENT/'acquisition.json',
        SOLVENT/'water_ions_namd.prm',SOLVENT/'namd_export.json',POLICY,NAMD,GMX,WATER,
        ART/'cpd-anti-solvated-construction-v1/assessment.json',
        ART/'cpd-anti-solvated-construction-v1/anti/static_preflight-00000/run.log',
        ART/'cpd-anti-solvated-construction-v1/control/static_preflight-00000/run.log',
        ART/'cpd-anti-solvated-construction-v1b/preparation_failure.json',
        ROOT/'worker.py',REPO/'backend/core/namd_solvate.py',
        REPO/'experiments/cpd_anti_additive/placement_review_v2.py']
    assert all(p.is_file() for p in sources)
    plan = dict(schema='nadoc.cpd-anti-solvated-construction.v1.2',created_at=now(),
        startup_repair='V1 native startup rejected CHARMM directives; V1b preparation caught a title-line parsing error. Both precede energy/minimization. Validated parameter-only export retains numerical records and exact full OpenMM System. Both failed preparations retained; no physical budget extension.',
        scope='Two isolated native NAMD minimization diagnostics; no dynamics, no refitting, no integration',
        authorization='User-authorized campaign continuation toward NAMD testable cis-anti CPDs',
        sources=[source(p) for p in sources], cases=['anti','control'],
        anti_seed='Earlier stereo/bond-safe source-conditioning endpoint, also used in fitted-DNA static validation; fails stationarity and 3.5 A placement',
        control_seed='Frozen unpatched reactant PSF/PDB; retains known inherited source-geometry defects, not an equilibrated undamaged reference',
        comparison_limit='Same strand graph, atom identity, box, solvent/ions and protocol. Seed conditioning histories differ; not a controlled causal estimate of solvent or lesion effects.',
        solvent=dict(model='Standard CHARMM modified TIP3P; official February 2026 water/ion stream, including its documented NBFIX',
            salt_molar=.150,neutralizing_sodium=93,padding_A=12,ion_seed=41017,
            placement='Common solvent excludes union of both solute seeds: oxygen >=3 A from any solute atom; all water atoms >=1.5 A; ions >=5 A from union and each other under PBC',
            salt_count='round(0.150 mol/L * total cell volume in A^3 * 6.02214076e-4); add 93 Na counterions separately',
            water_geometry='SPC216 oxygen packing/orientation only; reconstruct exact CHARMM TIP3P 0.9572 A / 104.52 degrees before use'),
        native=dict(namd=source(NAMD),threads=8,periodic=True,PME=True,PME_tolerance=1e-6,
            cutoff_A=12,switchdist_A=10,pairlistdist_A=14,rigidBonds='water',timestep_fs=1,temperature_K=0),
        stages=[dict(name='solvent_only',steps=500,fixed_solute=True,k_kcal_A2=0),
                dict(name='heavy_restraint_5',steps=1500,fixed_solute=False,k_kcal_A2=5),
                dict(name='heavy_restraint_1',steps=2000,fixed_solute=False,k_kcal_A2=1),
                dict(name='unrestrained',steps=6000,fixed_solute=False,k_kcal_A2=0)],
        restraint_definition='NAMD positional U=k*sum((r-r_seed)^2), solute heavy atoms only; seed PDB rounded to 0.001 A; final stage no positional restraints',
        max_minimization_steps_per_case=10000,max_attempts=1,max_continuations=0,hard_seconds=7200,
        checkpoint_steps=250,execution='Sequential cases; check each 250-step endpoint before continuing. Stop affected case on inversion, new severe contact or ring piercing; control may continue after anti failure.',
        transition='No inversion/new contact/piercing at checkpoints. Known control seed bond/contact defects may be repaired during restrained stages, but final acceptance requires all original geometry screens.',
        final_limits=dict(max_solute_force_component_kcal_A=.01,bond_ratio=[.7,1.3],severe_clash_ratio=.5,
            all_sugar_centers_preserved=True,all_anti_QM_centers_preserved=True,max_product_base_displacement_A=3.5),
        temperature_note='No MD in this attempt. Subsequent engineering MD, if justified by a separate review, retains 300 K and <=100 ps cap.',
        outcome='Completion is budget exhaustion unless independent stationarity and geometry checks pass. No Hessian/minimum certification.',
        references=['https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/',
            'https://manual.gromacs.org/documentation/2024.3/onlinehelp/gmx-solvate.html',
            'https://mackerell.umaryland.edu/charmm_ff.shtml'],simulation_ready=False)
    save(ROOT/'plan.json',plan)  # Frozen BEFORE packing or any energy/minimization.
    ff = ROOT/'forcefield'; ff.mkdir()
    for p in parent_paths+[MODEL/'anti_dna_overlay.prm',SOLVENT/'toppar_water_ions.str']:
        shutil.copyfile(p,ff/p.name)
    # The standalone export has already passed a full-system equivalence check.
    checked(read(SOLVENT/'namd_export.json')['source'])
    checked(read(SOLVENT/'namd_export.json')['output'])
    shutil.copyfile(SOLVENT/'water_ions_namd.prm',ff/'water_ions.prm')
    shutil.copyfile(SOLVENT/'namd_export.json',ff/'water_export.json')
    parents = [ff/p.name for p in parent_paths]
    anti_psf=app.CharmmPsfFile(str(MODEL/'anti.psf'))
    control_psf=app.CharmmPsfFile(str(TOPO/'reactant.psf'))
    assert [(a.system,a.residue.idx,a.name) for a in anti_psf.atom_list]==[(a.system,a.residue.idx,a.name) for a in control_psf.atom_list]
    seeds={'anti':np.loadtxt(MODEL/'starting_A.txt'),
           'control':np.array(app.PDBFile(str(TOPO/'reactant.pdb')).positions.value_in_unit(u.angstrom))}
    assert all(x.shape==(N,3) and np.isfinite(x).all() for x in seeds.values())
    union=np.concatenate(list(seeds.values())); low=union.min(axis=0);high=union.max(axis=0)
    box=np.ceil((high-low+24)*1000)/1000;shift=box/2-(high+low)/2
    for key in seeds: seeds[key]=seeds[key]+shift
    union=np.concatenate(list(seeds.values()));tree=cKDTree(union,boxsize=box)
    pack=ROOT/'packing';pack.mkdir()
    command=[str(GMX),'solvate','-cs',str(WATER),'-box',*(str(v/10) for v in box),'-o','water.gro','-nobackup']
    with (pack/'gmx.log').open('w') as f:
        subprocess.run(command,cwd=pack,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=300)
    waters,parsed_box=_parse_gro((pack/'water.gro').read_text())
    assert np.max(abs(np.array(parsed_box)*10-box))<.00011
    packed_count=len(waters); kept=[]
    for w in waters:
        x=np.array([w.ox,w.oy,w.oz,w.h1x,w.h1y,w.h1z,w.h2x,w.h2y,w.h2z]).reshape(3,3)*10
        v=x[1:]-x[0];v-=box*np.rint(v/box)
        e1=v[0]/np.linalg.norm(v[0]);e2=v[1]-v[1]@e1*e1;e2/=np.linalg.norm(e2)
        theta=np.deg2rad(104.52)
        x[1]=x[0]+.9572*e1;x[2]=x[0]+.9572*(np.cos(theta)*e1+np.sin(theta)*e2)
        ds=tree.query(x%box)[0]
        if ds[0]>=3 and min(ds)>=1.5: kept.append(x)
    xyz=np.array(kept);ox=xyz[:,0]%box
    n_pairs=int(round(.150*np.prod(box)*6.02214076e-4));nna=n_pairs+93;ncl=n_pairs
    chosen=[]
    for i in np.random.default_rng(41017).permutation(len(ox)):
        if tree.query(ox[i])[0]<5:continue
        if chosen:
            delta=ox[chosen]-ox[i];delta-=box*np.rint(delta/box)
            if np.min(np.linalg.norm(delta,axis=1))<5:continue
        chosen.append(int(i))
        if len(chosen)==nna+ncl:break
    assert len(chosen)==nna+ncl
    na=ox[chosen[:nna]]/10;cl=ox[chosen[nna:]]/10
    remaining=np.delete(xyz,chosen,axis=0)
    waters=[_Water(*(x.ravel()/10)) for x in remaining]
    solvent_x=np.concatenate([remaining.reshape(-1,3),na*10,cl*10])
    site=read(TOPO/'assessment.json'); frozen=np.loadtxt(ART/'cpd-anti-placement-review-v2/current_A.txt')+shift
    case_reports=[]
    for label,psf,psfpath in [('anti',anti_psf,MODEL/'anti.psf'),('control',control_psf,TOPO/'reactant.psf')]:
        folder=ROOT/label;folder.mkdir();x=np.vstack([seeds[label],solvent_x])
        shutil.copyfile(psfpath,folder/'solute.psf')
        np.savetxt(folder/'source_A.txt',frozen)
        np.savetxt(folder/'seed_A.txt',seeds[label])
        text=_extend_psf(psfpath.read_text(),waters,na.tolist(),cl.tolist())
        (folder/'system.psf').write_text(text)
        ptext=_build_solvated_pdb(pdb_text(psf,seeds[label]),waters,na.tolist(),cl.tolist(),tuple(box/10),N)
        (folder/'system.pdb').write_text(ptext);binary(folder/'start.coor',x)
        # Preserve solute PSF records verbatim, including 12-decimal CPD charges.
        solv=app.CharmmPsfFile(str(folder/'system.psf'))
        assert [atom_identity(a) for a in solv.atom_list[:N]]==[atom_identity(a) for a in psf.atom_list]
        assert len(solv.atom_list)==len(x) and abs(sum(a.charge for a in solv.atom_list))<1e-8
        assert {tuple(sorted((b.atom1.idx,b.atom2.idx))) for b in solv.bond_list if b.atom1.idx<N or b.atom2.idx<N}=={tuple(sorted((b.atom1.idx,b.atom2.idx))) for b in psf.bond_list}
        pp=parents+([ff/'anti_dna_overlay.prm'] if label=='anti' else [])
        before=psf.createSystem(params(pp),nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        after=psf.createSystem(params(pp+[ff/'toppar_water_ions.str']),nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        assert mm.XmlSerializer.serialize(before)==mm.XmlSerializer.serialize(after), 'Water/ion file changed solute-only potential'
        solv.setBox(*(float(v)*u.angstrom for v in box))
        full=solv.createSystem(params(pp+[ff/'toppar_water_ions.str']),nonbondedMethod=app.PME,nonbondedCutoff=1.2*u.nanometer,
            constraints=None,rigidWater=True,ewaldErrorTolerance=1e-6)
        reloaded=solv.createSystem(params(pp+[ff/'water_ions.prm']),nonbondedMethod=app.PME,nonbondedCutoff=1.2*u.nanometer,
            constraints=None,rigidWater=True,ewaldErrorTolerance=1e-6)
        assert mm.XmlSerializer.serialize(full)==mm.XmlSerializer.serialize(reloaded), 'NAMD parameter-only conversion changed potential'
        (folder/'coverage_system.xml').write_text(mm.XmlSerializer.serialize(full))
        ns=adjacency(psf);centers=[]
        for atom in psf.atom_list:
            if atom.name in ("C1'","C3'","C4'"):
                ids=ns[atom.idx];assert len(ids)==4
                centers.append(dict(label=f'{atom.system}:{atom.residue.idx}:{atom.name}',indices=ids,reference_A3=signed_volume(frozen[ids])))
        assert len(centers)==288
        ids={f'{e["endpoint"]}:{a.name}':a.idx for e in site['endpoints'] for a in psf.atom_list if (a.system,a.residue.idx)==(e['segid'],e['resid'])}
        if label=='anti':
            for ep in (1,2):
                qfolder=ART/f'cpd-anti-conformational-fit-v2-r1/candidate/endpoint-{ep}'
                names=read(qfolder/'atom_map.json');q=np.loadtxt(qfolder/'starting_A.txt')
                adj=adjacency(app.CharmmPsfFile(str(qfolder/'fragment.psf')))
                for name in ('C5','C6',"C1'","C3'","C4'"):
                    key=f'{ep}:{name}';local=adj[names.index(key)]
                    centers.append(dict(label='QM:'+key,indices=[ids[names[i]] for i in local],reference_A3=signed_volume(q[local])))
        bonds=[(b.atom1.idx,b.atom2.idx) for b in psf.bond_list];eqs=[]
        for force in before.getForces():
            if isinstance(force,mm.HarmonicBondForce):
                for i in range(force.getNumBonds()):
                    a,b,eq,k=force.getBondParameters(i)
                    if tuple(sorted((a,b))) in {tuple(sorted(b)) for b in bonds}:eqs.append([a,b,eq.value_in_unit(u.angstrom)])
        assert len(eqs)==len(bonds)
        rings=[]
        for r in psf.residue_list:
            named={a.name:a.idx for a in r.atoms}
            for kind,cycle in ring_names_for(named):rings.append((f'{r.system}:{r.idx}/{kind}',kind,[named[n] for n in cycle]))
        if label=='anti':rings.append(('lesion','cyclobutane',[ids[k] for k in ('1:C5','1:C6','2:C5','2:C6')]))
        localnames=read(ART/'cpd-anti-conformational-fit-v2-r1/candidate/two-nucleosides/atom_map.json')
        base=[i for k,i in ids.items() if "'" not in k and k in localnames]
        elements=[a.element.symbol for a in psf.topology.atoms()]
        save(folder/'geometry_reference.json',dict(centers=centers,bonds=bonds,bonds_equilibrium_A=eqs,rings=rings,
            elements=elements,labels=[f'{a.system}:{a.residue.idx}:{a.name}' for a in psf.atom_list],base_indices=base))
        # Dedicated beta masks, no dependence on atom names in a runtime selection.
        for name,values in [('fixed.pdb',[1]*N+[0]*(len(x)-N)),
                            ('restraint.pdb',[float(e!='H') for e in elements]+[0]*(len(x)-N))]:
            lines=[];i=0
            for line in ptext.splitlines():
                if line.startswith(('ATOM  ','HETATM')):
                    line=line[:60]+f'{values[i]:6.2f}'+line[66:];i+=1
                lines.append(line)
            assert i==len(x);(folder/name).write_text('\n'.join(lines)+'\n')
        review=geometry(folder,x);save(folder/'seed_review.json',review)
        assert review['stereo_passed'] and not review['contacts']['all_piercing_count']
        case_reports.append(dict(case=label,atoms=len(x),charge_e=float(sum(a.charge for a in solv.atom_list)),
            solute_atom_records_exact=True,solute_bonds_exact=True,solute_only_potential_unchanged=True,
            all_parameters_found=True,water_parameter_export_system_exact=True,seed_review=source(folder/'seed_review.json')))
    save(ROOT/'assembly.json',dict(created_at=now(),plan=source(ROOT/'plan.json'),box_A=box.tolist(),translation_A=shift.tolist(),
        packed_waters=packed_count,waters=len(waters),sodium=nna,chloride=ncl,salt_pairs=n_pairs,
        achieved_excess_salt_molar=n_pairs/(np.prod(box)*6.02214076e-4),cases=case_reports,
        common_solvent_coordinates=True,solute_coordinates_unmodified_except_translation=True,simulation_ready=False))
    files=sorted(p for p in ROOT.rglob('*') if p.is_file() and p.name!='inputs_lock.json')
    save(ROOT/'inputs_lock.json',dict(created_at=now(),files=[source(p) for p in files]))
    print('Prepared',ROOT,case_reports,'water',len(waters),'Na/Cl',nna,ncl,flush=True)


def configuration(folder, current, stage, steps, box):
    common=['structure ../system.psf','coordinates ../system.pdb',f'binCoordinates {current}',
        'paraTypeCharmm on','parameters ../../forcefield/par_all36_na.prm',
        'parameters ../../forcefield/par_all36_cgenff.prm']
    if folder.name=='anti':common.append('parameters ../../forcefield/anti_dna_overlay.prm')
    common += ['parameters ../../forcefield/water_ions.prm','exclude scaled1-4','oneFourScaling 1',
        'cutoff 12','switching on','switchdist 10','pairlistdist 14','margin 2',
        'PME yes','PMETolerance 0.000001','PMEGridSpacing 1.0',
        f'cellBasisVector1 {box[0]} 0 0',f'cellBasisVector2 0 {box[1]} 0',f'cellBasisVector3 0 0 {box[2]}',
        'cellOrigin '+' '.join(str(v/2) for v in box),'wrapAll off',
        'rigidBonds water','useSettle on','timestep 1','nonbondedFreq 1','fullElectFrequency 1',
        'stepspercycle 1','temperature 0','outputName result','outputEnergies 50','DCDfreq 50']
    if stage['fixed_solute']:
        common+=['fixedAtoms on','fixedAtomsFile ../fixed.pdb','fixedAtomsCol B','fixedAtomsForces on']
    if stage['k_kcal_A2']:
        common+=['constraints on','consref ../system.pdb','conskfile ../restraint.pdb','conskcol B','consexp 2',
                 f"constraintScaling {stage['k_kcal_A2']}"]
    common += [f'minimize {steps}' if steps else 'run 0','output result','output onlyforces result']
    return '\n'.join(common)+'\n'


def run():
    lock=read(ROOT/'inputs_lock.json')
    for s in lock['files']:checked(s)
    assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
    plan=read(ROOT/'plan.json');assembly=read(ROOT/'assembly.json');start=time.monotonic()
    with (ROOT/'started.json').open('x') as f:
        import json
        json.dump(dict(at=now(),input_lock=source(ROOT/'inputs_lock.json')),f)
    reports=[]
    for label in plan['cases']:
        folder=ROOT/label; current=(folder/'start.coor').resolve();seed=read(folder/'seed_review.json')
        old_contacts={tuple(sorted(r['indices'])) for r in seed['contacts']['severe_clashes']}
        history=[];error=None;total=0
        count=next(r['atoms'] for r in assembly['cases'] if r['case']==label)
        try:
            # Initial native run 0 is a load/finite-energy preflight, not an
            # independent PME cross-engine equivalence or geometry pass.
            phases=[dict(name='static_preflight',steps=0,fixed_solute=False,k_kcal_A2=0)]+plan['stages']
            for stage in phases:
                done=0
                while done<stage['steps'] or stage['name']=='static_preflight' and not done:
                    steps=min(plan['checkpoint_steps'],stage['steps']-done)
                    out=folder/f"{stage['name']}-{done+steps:05d}";out.mkdir()
                    (out/'run.conf').write_text(configuration(folder,current,stage,steps,assembly['box_A']))
                    remaining=plan['hard_seconds']-(time.monotonic()-start)
                    if remaining<=0:raise RuntimeError('Total two-case wall-time budget exhausted')
                    with (out/'run.log').open('w') as f:
                        proc=subprocess.run([str(NAMD),'+p8','run.conf'],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=remaining)
                    log=(out/'run.log').read_text()
                    assert proc.returncode==0 and 'End of program' in log and 'FATAL ERROR' not in log
                    energies=[]
                    for line in log.splitlines():
                        if line.startswith('ETITLE:'):titles=line.split()[1:]
                        if line.startswith('ENERGY:'):
                            values=np.array([float(v) for v in line.split()[1:]])
                            assert len(values)==len(titles) and np.isfinite(values).all()
                            energies.append(dict(zip(titles,values.tolist())))
                    assert energies
                    x=read_binary(out/'result.coor',count);force=read_binary(out/'result.force',count)
                    result=geometry(folder,x);new_contacts={tuple(sorted(r['indices'])) for r in result['contacts']['severe_clashes']}
                    record=dict(stage=stage['name'],steps=steps,total_steps=total+steps,geometry=result,
                        native_final=energies[-1],max_solute_force_component_kcal_A=float(np.max(abs(force[:N]))),
                        restraint_k_kcal_A2=stage['k_kcal_A2'],coordinates=source(out/'result.coor'),forces=source(out/'result.force'),log=source(out/'run.log'))
                    save(out/'review.json',record);history.append(record);total+=steps
                    save(ROOT/'progress.json',dict(case=label,total_steps=total,last=record,elapsed_seconds=time.monotonic()-start))
                    print(label,stage['name'],total,'force',record['max_solute_force_component_kcal_A'],'stereo',result['stereo_passed'],flush=True)
                    if not result['stereo_passed'] or result['contacts']['all_piercing_count'] or new_contacts-old_contacts:
                        raise RuntimeError('Checkpoint inversion, piercing or new severe contact; no continuation')
                    old_contacts=new_contacts;current=(out/'result.coor').resolve();done+=steps
                    if steps==0:break
        except Exception as exc:
            error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc())
        last=history[-1] if history else None
        released=bool(last and last['stage']=='unrestrained' and total==10000 and error is None)
        force_pass=bool(released and last['max_solute_force_component_kcal_A']<=.01)
        g=last['geometry'] if last else seed
        integrity=bool(g['stereo_passed'] and g['bond_integrity_passed'] and not g['contacts']['severe_clash_count'] and not g['contacts']['all_piercing_count'])
        passed=bool(released and force_pass and integrity and (label=='control' or g['product_displacement_screen_passed']))
        report=dict(case=label,error=error,steps=total,history=history,all_restraints_removed=released,
            solute_stationary=force_pass,geometry_integrity_passed=integrity,construction_passed=passed,
            minimum_certified=False,full_DNA_dynamics_tested=False,preliminary_research_qualified=False,simulation_ready=False)
        save(folder/'assessment.json',report);reports.append(report)
    passed=all(r['construction_passed'] for r in reports)
    save(ROOT/'assessment.json',dict(completed_at=now(),plan=source(ROOT/'plan.json'),cases=[source(ROOT/r['case']/'assessment.json') for r in reports],
        construction_passed=passed,elapsed_seconds=time.monotonic()-start,minimum_certified=False,full_DNA_dynamics_tested=False,simulation_ready=False))
    if not passed:raise RuntimeError('Bounded solvent construction failed acceptance; retain native evidence, no automatic extension or dynamics')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run'])
    globals()[parser.parse_args().action]()
