"""Bounded solvated construction after explicit source chirality repair.

Temporary sugar impropers and fixed repaired frames are removed before the final
geometry review. Stationarity/product screens retain their separate meanings.
"""
import argparse,os,shutil,sys,subprocess,time,traceback
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import app,unit as u
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.preliminary_protocol import POLICY,require
from experiments.cpd_anti_additive.run_engine_v2 import binary,read_binary
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry,configuration
from backend.core.dcd_fast import read_layout,read_frame
from experiments.cpd_anti_additive.review_source_conditioning_v1 import signed_volume
ART=REPO/'.development-artifacts';ROOT=ART/'cpd-anti-stereo-protected-construction-v2'
OLD=ART/'cpd-anti-solvated-construction-v1c';REPAIR=ART/'cpd-anti-source-stereo-explicit-v2'
REF=ART/'cpd-anti-source-stereo-repair-v1b/chemical_references.json'
NAMD=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')


def prepare():
    require('conformational');assert read(REPAIR/'assessment.json')['local_stereo_seed_repair_passed']
    ROOT.mkdir(exist_ok=False);shutil.copyfile(Path(__file__),ROOT/'worker.py')
    files=[POLICY,NAMD,ROOT/'worker.py',REF,REPAIR/'assessment.json',REPAIR/'repair_review.png',
        OLD/'independent_review.json',OLD/'inputs_lock.json',REPO/'experiments/cpd_anti_additive/solvated_construction_v1.py']
    for label in ['anti','control']:
        files.extend(REPAIR/label/n for n in ['assessment.json','candidate.coor','geometry_reference.json'])
    plan=dict(created_at=now(),sources=[source(p) for p in files],cases=['anti','control'],
        purpose='Isolated corrected-reference construction; no dynamics, fitting, product integration or minimum certificate',
        authorization='Resumed user-authorized v2 engineering campaign; reviewed method revision after retained terminal failures',
        method='Keep two reconstructed C3 frames fixed initially while adjoining phosphate bonds repair; temporary harmonic improper restraints protect all288 sugar signs, then reduce and remove every artificial restraint.',
        chemistry_reference='Canonical neighbor mapping to both original QM sugars, replacing source-sign inference; original failed verdicts not revised',
        restraint_definition='NAMD extraBonds improper n=0, U=k*wrapped(theta-theta0)^2 with angle in radians; references are circular means of two original QM neighbor dihedrals. Construction aid only, never exported as force-field parameters.',
        stages=[dict(name='solvent_only',steps=500,k_kcal_A2=0,fixed_solute=True,extra_k=0,fixed_frames=False),
            dict(name='repair_phosphate',steps=1500,k_kcal_A2=5,fixed_solute=False,extra_k=50,fixed_frames=True),
            dict(name='release_frames',steps=1500,k_kcal_A2=1,fixed_solute=False,extra_k=50,fixed_frames=False),
            dict(name='weaken_chirality',steps=1500,k_kcal_A2=0,fixed_solute=False,extra_k=10,fixed_frames=False),
            dict(name='unrestrained',steps=5000,k_kcal_A2=0,fixed_solute=False,extra_k=0,fixed_frames=False)],
        geometry_checkpoint_steps=50,stored_frame_interval=50,native_workers=8,memory_gib=12,hard_seconds=7200,
        max_minimization_steps_per_case=10000,max_attempts=1,max_continuations=0,
        stop='On any saved inversion/ring piercing/new severe solute contact, stop affected case. Retained starting bond/contact defects must be absent at final review.',
        criteria=dict(chemically_mapped_sugars=True,original_QM_lesion_stereo=True,bond_ratio=[.7,1.3],severe_clash_ratio=.5,
            stationarity_report_limit_kcal_A=.01,product_displacement_screen_A=3.5,all_artificial_restraints_removed=True),
        gate_scope='Policy v2 engine requires correct chemistry, complete implementation and safe finite native behavior, not an unconstrained full-DNA minimum. Report .01 stationarity and3.5 placement separately; neither failed historical attempt becomes passed. No MD is chained to this construction.',
        added_force_preflight='Native extra-minus-baseline E/F must match independent OpenMM harmonic torsions at unchanged seed under policy absolute-or-relative limits, before minimization.',
        references=['https://www-s.ks.uiuc.edu/Research/namd/3.0/ug/node29.html','https://pmc.ncbi.nlm.nih.gov/articles/PMC3285246/'],
        simulation_ready=False)
    save(ROOT/'plan.json',plan)
    shutil.copytree(OLD/'forcefield',ROOT/'forcefield');shutil.copyfile(OLD/'assembly.json',ROOT/'parent_assembly.json')
    refs=read(REF)['references']
    for label in plan['cases']:
        folder=ROOT/label;folder.mkdir()
        for name in ['system.psf','solute.psf','fixed.pdb','source_A.txt']:
            shutil.copyfile(OLD/label/name,folder/name)
        shutil.copyfile(REPAIR/label/'geometry_reference.json',folder/'geometry_reference.json')
        shutil.copyfile(REPAIR/label/'candidate.coor',folder/'start.coor')
        x=read_binary(folder/'start.coor',30867);psf=app.CharmmPsfFile(str(folder/'solute.psf'))
        fixed={a.idx for a in psf.atom_list if (a.system,a.residue.idx) in [('D000',7),('D002',26)] and a.name in ("C3'","C2'","C4'","O3'","H3'")}
        assert len(fixed)==10
        ptext=(OLD/label/'system.pdb').read_text().splitlines();i=0;lines=[];mask=[];rest=[]
        for line in ptext:
            if line.startswith(('ATOM  ','HETATM')):
                line=line[:30]+''.join(f'{v:8.3f}' for v in x[i])+line[54:]
                m=float(i in fixed);h=float(i<3043 and psf.atom_list[i].mass.value_in_unit(u.dalton)>2) if i<3043 else 0
                mask.append(line[:60]+f'{m:6.2f}'+line[66:]);rest.append(line[:60]+f'{h:6.2f}'+line[66:]);i+=1
            else:mask.append(line);rest.append(line)
            lines.append(line)
        assert i==30867
        (folder/'system.pdb').write_text('\n'.join(lines)+'\n');(folder/'frame_fixed.pdb').write_text('\n'.join(mask)+'\n');(folder/'restraint.pdb').write_text('\n'.join(rest)+'\n')
        spec=read(folder/'geometry_reference.json');torsions=[]
        for row in spec['centers']:
            if row['label'].startswith('QM:'):continue
            name=row['label'].split(':')[-1];phi=np.radians([r['centers'][name]['dihedral_deg'] for r in refs])
            target=float(np.degrees(np.arctan2(np.sin(phi).mean(),np.cos(phi).mean())))
            torsions.append(dict(label=row['label'],indices=row['indices'],target_deg=target))
        assert len(torsions)==288;save(folder/'temporary_torsions.json',torsions)
        for k in [50,10]:
            (folder/f'chirality_{k}.txt').write_text('\n'.join('improper '+' '.join(str(i) for i in r['indices'])+f" {k} 0 {r['target_deg']:.14g}" for r in torsions)+'\n')
        save(folder/'seed_review.json',geometry(folder,x))
    save(ROOT/'inputs_lock.json',dict(created_at=now(),files=[source(p) for p in sorted(ROOT.rglob('*')) if p.is_file()]))
    print('Prepared protected construction',ROOT,flush=True)


def native(folder,current,stage,steps,out,box,remaining):
    out.mkdir()
    cfg=configuration(folder,current,stage,steps,box)
    additions=[]
    if stage.get('fixed_frames'):
        additions+=['fixedAtoms on','fixedAtomsFile ../frame_fixed.pdb','fixedAtomsCol B','fixedAtomsForces on']
    if stage.get('extra_k'):
        additions+=['extraBonds on',f"extraBondsFile ../chirality_{stage['extra_k']}.txt"]
    marker=f'minimize {steps}' if steps else 'run 0'
    cfg=cfg.replace(marker,'\n'.join(additions+[marker]))
    (out/'run.conf').write_text(cfg)
    with (out/'run.log').open('w') as f:
        p=subprocess.run([str(NAMD),'+p8','run.conf'],cwd=out,stdout=f,stderr=subprocess.STDOUT,timeout=remaining)
    log=(out/'run.log').read_text();assert p.returncode==0 and 'End of program' in log and 'FATAL ERROR' not in log
    energies=[]
    for line in log.splitlines():
        if line.startswith('ETITLE:'):titles=line.split()[1:]
        if line.startswith('ENERGY:'):
            values=np.array([float(v) for v in line.split()[1:]]);assert len(values)==len(titles) and np.isfinite(values).all()
            energies.append(dict(zip(titles,values.tolist())))
    assert energies
    x=read_binary(out/'result.coor',30867);force=read_binary(out/'result.force',30867)
    return x,force,energies[-1]


def run():
    for record in read(ROOT/'inputs_lock.json')['files']:checked(record)
    assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
    plan=read(ROOT/'plan.json');box=read(ROOT/'parent_assembly.json')['box_A'];start=time.monotonic()
    with (ROOT/'started.json').open('x') as f:
        import json
        json.dump(dict(at=now(),plan=source(ROOT/'plan.json')),f)
    def remaining():
        value=plan['hard_seconds']-(time.monotonic()-start)
        if value<=0:raise RuntimeError('Two-case time cap reached')
        return value
    reports=[]
    for label in plan['cases']:
        folder=ROOT/label;current=(folder/'start.coor').resolve();history=[];total=0;error=None
        seed=read(folder/'seed_review.json');assert seed['stereo_passed']
        contacts={tuple(sorted(r['indices'])) for r in seed['contacts']['severe_clashes']}
        spec=read(folder/'geometry_reference.json')
        try:
            zero=dict(name='preflight',k_kcal_A2=0,fixed_solute=False,extra_k=0)
            x,f0,e0=native(folder,current,zero,0,folder/'preflight_plain',box,remaining())
            x,f1,e1=native(folder,current,dict(zero,extra_k=50),0,folder/'preflight_extra',box,remaining())
            system=mm.System()
            for _ in range(3043):system.addParticle(1)
            force=mm.CustomTorsionForce('k*min(d,2*pi-d)^2;d=abs(theta-t0);pi=3.141592653589793')
            force.addPerTorsionParameter('k');force.addPerTorsionParameter('t0')
            for row in read(folder/'temporary_torsions.json'):force.addTorsion(*row['indices'],[50*4.184,np.radians(row['target_deg'])])
            system.addForce(force);it=mm.VerletIntegrator(.001);ctx=mm.Context(system,it,mm.Platform.getPlatformByName('Reference'))
            ctx.setPositions(x[:3043]*u.angstrom);s=ctx.getState(getEnergy=True,getForces=True)
            e=s.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            f=np.array(s.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom));del ctx,it
            de=abs(e1['POTENTIAL']-e0['POTENTIAL']-e);df=float(np.max(abs(f1[:3043]-f0[:3043]-f)))
            p=read(POLICY)['engine'];ep=max(.001,1e-4*abs(e));fp=max(.001,1e-4*float(abs(f).max()))
            passed=bool(de<=ep and df<=fp)
            save(folder/'extra_force_preflight.json',dict(passed=passed,energy_error_kcal=de,force_error_kcal_A=df,energy_limit=ep,force_limit=fp,independent_added_energy_kcal=e,
                independent_added_max_force=float(abs(f).max()),policy=source(POLICY)))
            assert passed,'Temporary improper native force convention mismatch'
            for stage in plan['stages']:
                for done in range(0,stage['steps'],plan['geometry_checkpoint_steps']):
                    steps=min(plan['geometry_checkpoint_steps'],stage['steps']-done);out=folder/f"{stage['name']}-{done+steps:05d}"
                    x,f,e=native(folder,current,stage,steps,out,box,remaining());total+=steps
                    g=geometry(folder,x);wrong=[];dcd=out/'result.dcd'
                    if dcd.exists():
                        layout=read_layout(dcd)
                        for index in range(layout.n_frames):
                            frame=read_frame(dcd,layout,index)[0]
                            wrong.extend(r['label'] for r in spec['centers'] if signed_volume(frame[r['indices']])*r['reference_A3']<=0)
                    new_contacts={tuple(sorted(r['indices'])) for r in g['contacts']['severe_clashes']}
                    record=dict(stage=stage['name'],steps=steps,total_steps=total,geometry=g,saved_frame_inversions=sorted(set(wrong)),
                        max_solute_force_component_kcal_A=float(abs(f[:3043]).max()),native=e,coordinates=source(out/'result.coor'),forces=source(out/'result.force'),log=source(out/'run.log'))
                    save(out/'review.json',record);history.append(record)
                    save(ROOT/'progress.json',dict(case=label,total_steps=total,last=record,elapsed_seconds=time.monotonic()-start))
                    if total%250==0:print(label,stage['name'],total,'force',record['max_solute_force_component_kcal_A'],flush=True)
                    if not g['stereo_passed'] or wrong or g['contacts']['all_piercing_count'] or new_contacts-contacts:
                        raise RuntimeError('Checkpoint chemistry/contact failure; retain outputs, no continuation')
                    contacts=new_contacts;current=(out/'result.coor').resolve()
        except Exception as exc:
            error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc())
        last=history[-1] if history else None;g=last['geometry'] if last else seed
        free=bool(error is None and total==10000 and last['stage']=='unrestrained')
        safe=bool(free and g['stereo_passed'] and g['bond_integrity_passed'] and not g['contacts']['severe_clash_count'] and not g['contacts']['all_piercing_count'])
        report=dict(case=label,error=error,steps=total,history=history,artificial_restraints_removed=free,geometry_eligible_for_engine_review=safe,
            stationary_under_existing_criterion=bool(free and last['max_solute_force_component_kcal_A']<=.01),
            product_displacement_screen_passed=g['product_displacement_screen_passed'],minimum_certified=False,full_DNA_dynamics_tested=False,simulation_ready=False)
        save(folder/'assessment.json',report);reports.append(report)
    save(ROOT/'assessment.json',dict(completed_at=now(),plan=source(ROOT/'plan.json'),cases=[source(ROOT/r['case']/'assessment.json') for r in reports],
        geometry_eligible_for_engine_review=all(r['geometry_eligible_for_engine_review'] for r in reports),elapsed_seconds=time.monotonic()-start,
        minimum_certified=False,full_DNA_dynamics_tested=False,simulation_ready=False))
    if not all(r['geometry_eligible_for_engine_review'] for r in reports):raise RuntimeError('Protected construction failed its geometry gate; no automatic continuation or MD')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run']);globals()[parser.parse_args().action]()
