"""Candidate-specific native checks; never replaces an older immutable lock."""
import argparse
import os
from pathlib import Path
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import checked,read,source
from experiments.cpd_anti_additive.preliminary_protocol import POLICY,STATE,require
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import native,fixture,configuration,read_binary,smoke
from backend.core.dcd_fast import read_layout,read_frame

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-conformational-native-v2-r1'
CANDIDATE=ART/'cpd-anti-conformational-fit-v2-r1/candidate'
NAMD=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')


def prepare():
    require('conformational')
    report=read(CANDIDATE/'assessment.json')
    assert report['representative_engineering_stability_passed']
    assert report['candidate']==source(CANDIDATE/'comparator_last.prm')
    ROOT.mkdir(exist_ok=False)
    (ROOT/'worker.py').write_text(Path(__file__).read_text())
    cases=['core','endpoint-1','endpoint-2','endpoint-2-remote','two-nucleosides']
    sources=[source(CANDIDATE/'assessment.json'),report['candidate'],source(POLICY),source(NAMD),
        source(ROOT/'worker.py'),source(REPO/'experiments/cpd_anti_additive/run_engine_v2.py'),
        source(REPO/'experiments/cpd_anti_additive/prepare_engine_v2.py'),
        source(STATE/'conformational_input_lock.json')]
    for label in cases:
        for name in ('starting_A.txt','minimum_A.txt','fragment.psf','system.xml','atom_map.json','assessment.json'):
            sources.append(source(CANDIDATE/label/name))
    plan=dict(schema='nadoc.cpd-anti-candidate-native.v2.1',created_at=now(),sources=sources,
        candidate=str(CANDIDATE.resolve()),cases=cases,namd=source(NAMD),
        engine_policy=read(POLICY)['engine'],max_hours=2,minimization_steps=1000,
        md_steps=100000,timestep_fs=1,temperature_K=300,seed=41017,
        limitations=['19-case exposed energy regression passes; branch descriptors remain mismatched for some points.',
            'Prospective four-point validation not acquired; no preliminary research qualification.',
            'Vacuum two-nucleoside engineering smoke only; full DNA and native parent-backbone transfer remain separate.',
            'Older candidate and failures retained; no product integration.'],
        simulation_ready=False)
    save(ROOT/'plan.json',plan)
    print('Prepared candidate-specific native verification',ROOT)


def run():
    plan=read(ROOT/'plan.json')
    for s in plan['sources']:checked(s)
    assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
    with (ROOT/'started.json').open('x') as f:
        import json
        json.dump(dict(at=now(),plan=source(ROOT/'plan.json')),f)
    candidate=Path(plan['candidate']);settings=plan['engine_policy']
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params=app.CharmmParameterSet(str(candidate/'comparator_last.prm'))
    comparisons=[]
    for label in plan['cases']:
        src=candidate/label;psf=app.CharmmPsfFile(str(src/'fragment.psf'))
        original=mm.XmlSerializer.deserialize((src/'system.xml').read_text())
        reload=psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        for geometry in ('starting','minimum'):
            x=np.loadtxt(src/f'{geometry}_A.txt');values=[]
            for system in (original,reload):
                integ=mm.VerletIntegrator(.001);ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
                ctx.setPositions(x*u.angstrom);state=ctx.getState(getEnergy=True,getForces=True)
                values.append((state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),
                    np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))))
                del ctx,integ
            (energy,force),(re,rf)=values
            assert abs(re-energy)<=settings['static_export_energy_kcal']
            assert np.max(abs(rf-force))<=settings['static_export_force_kcal_A']
            folder=ROOT/f'{label}-{geometry}';fixture(folder,src,candidate,x)
            energies,notes=native(checked(plan['namd']),folder,configuration([
                'outputName static','temperature 0','run 0','output onlyforces static']))
            nf=read_binary(folder/'static.force',len(x))
            de=float(abs(energies[-1]['POTENTIAL']-energy));df=float(np.max(abs(nf-force)))
            passed=bool(de<=max(settings['native_equivalence_absolute_energy_kcal'],settings['native_equivalence_relative_limit']*abs(energy)) and
                df<=max(settings['native_equivalence_absolute_force_kcal_A'],settings['native_equivalence_relative_limit']*np.max(abs(force))))
            comparisons.append(dict(case=label,geometry=geometry,passed=passed,energy_error_kcal=de,
                max_force_error_kcal_A=df,reference_energy_kcal=energy,reference_max_force_kcal_A=float(np.max(abs(force))),
                reload_energy_error=abs(re-energy),reload_force_error=float(np.max(abs(rf-force))),
                log=source(folder/'run.log'),forces=source(folder/'static.force'),warnings=notes))
            save(ROOT/'progress.json',dict(native_equivalence=comparisons))
            if not passed: raise RuntimeError('Native energy/force mismatch; no dynamics')
    smoke(ROOT,candidate,checked(plan['namd']),plan,comparisons)
    # Independently bind the ten real stereocenters to the original QM fragment
    # coordinates, rather than only to the assembled MM smoke seed.
    names=read(candidate/'two-nucleosides/atom_map.json');centers=[]
    psf=app.CharmmPsfFile(str(candidate/'two-nucleosides/fragment.psf'))
    assert len(psf.atom_list)==62 and len(psf.bond_list)==66 and abs(sum(a.charge for a in psf.atom_list))<1e-8
    links={tuple(sorted((names[b.atom1.idx],names[b.atom2.idx]))) for b in psf.bond_list if names[b.atom1.idx][0]!=names[b.atom2.idx][0]}
    assert links=={('1:C5','2:C6'),('1:C6','2:C5')}
    def volume(x):
        a,b,c,d=x
        return float(np.dot(b-a,np.cross(c-a,d-a)))
    for e in (1,2):
        src=candidate/f'endpoint-{e}';ns=read(src/'atom_map.json');q=np.loadtxt(src/'starting_A.txt')
        fragment=app.CharmmPsfFile(str(src/'fragment.psf'))
        for atom in ('C5','C6',"C1'","C3'","C4'"):
            key=f'{e}:{atom}';idx=ns.index(key)
            neighbors=[]
            for b in fragment.bond_list:
                i,j=b.atom1.idx,b.atom2.idx
                if i==idx:neighbors.append(j)
                elif j==idx:neighbors.append(i)
            assert len(neighbors)==4
            centers.append(dict(key=key,indices=[names.index(ns[i]) for i in neighbors],reference=volume(q[neighbors])))
    layout=read_layout(ROOT/'smoke/smoke.dcd')
    frames=[read_frame(ROOT/'smoke/smoke.dcd',layout,i)[0] for i in range(layout.n_frames)]
    frames.append(read_binary(ROOT/'smoke/smoke.coor',62))
    for c in centers:c['all_frames_preserved']=bool(all(volume(x[c['indices']])*c['reference']>0 for x in frames))
    assert layout.n_frames==101 and all(c['all_frames_preserved'] for c in centers)
    save(ROOT/'independent_review.json',dict(passed=True,assessment=source(ROOT/'assessment.json'),centers=centers,
        inspected_frames_including_final=len(frames),native_comparisons=len(comparisons),
        exact_psf_reuse=all((candidate/l/'fragment.psf').read_bytes()==(ART/'cpd-anti-engine-candidate-v2g'/l/'fragment.psf').read_bytes() for l in plan['cases']),
        full_DNA_NAMD_tested=False,preliminary_research_qualified=False,simulation_ready=False,reviewed_at=now()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run'])
    globals()[parser.parse_args().action]()
