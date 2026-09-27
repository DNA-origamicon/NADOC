"""Transfer the first conformational fit and run a full-DNA static NAMD check."""
import json
from pathlib import Path
import shutil
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app,unit as u

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.prepare_dna_topology_v2 import export_parameters
from experiments.cpd_anti_additive.validation_gate import source,checked,read
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.preliminary_protocol import POLICY,require
from experiments.cpd_anti_additive.run_engine_v2 import binary,read_binary,native
from experiments.cpd_published_comparator.reconstruct import BASE,FF

ART=REPO/'.development-artifacts'
ROOT=ART/'cpd-anti-fitted-dna-v2-r1'
OLD=ART/'cpd-anti-dna-topology-v2b'
CANDIDATE=ART/'cpd-anti-conformational-fit-v2-r1/candidate'


def main():
    require('conformational')
    review=read(ART/'cpd-anti-conformational-native-v2-r1/independent_review.json')
    assert review['passed']
    checked(review['assessment'])
    ROOT.mkdir(exist_ok=False)
    (ROOT/'executed_source.py').write_text(Path(__file__).read_text())
    aliaspath=ART/'cpd-anti-ordered-types-v1/assessment.json'
    aliases={r['alias']:r for r in read(aliaspath)['aliases']}
    parents=[BASE/'top_all36_na.rtf',BASE/'par_all36_na.prm',FF/'top_all36_cgenff.rtf',FF/'par_all36_cgenff.prm']
    prior=ART/'cpd-anti-source-conditioning-v1b'
    coords=checked(read(prior/'assessment.json')['phases'][-1]['coordinates'])
    save(ROOT/'plan.json',dict(at=now(),candidate=source(CANDIDATE/'assessment.json'),
        parameters=source(CANDIDATE/'comparator_last.prm'),native_fragment_review=source(ART/'cpd-anti-conformational-native-v2-r1/independent_review.json'),
        topology=source(OLD/'assessment.json'),topology_review=source(OLD/'independent_review.json'),
        parent_forcefields=[source(p) for p in parents],aliases=source(aliaspath),
        coordinates=source(coords),coordinate_status='Retained failed construction, no claim of stationarity or dynamics readiness',
        scope='Exact fitted torsion transfer and full-DNA static implementation only; no coordinate optimization or dynamics',
        source=source(Path(__file__)),simulation_ready=False))
    export_parameters(CANDIDATE,aliases,ROOT)
    for name in ('anti.psf','anti_dna.rtf'):
        shutil.copyfile(OLD/name,ROOT/name)
    psf=app.CharmmPsfFile(str(ROOT/'anti.psf'))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params=app.CharmmParameterSet(*(str(p) for p in parents+[ROOT/'anti_dna_overlay.prm']))
    system=psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
    (ROOT/'system.xml').write_text(mm.XmlSerializer.serialize(system))
    original=mm.XmlSerializer.deserialize((OLD/'coverage_system.xml').read_text())
    assert system.getNumParticles()==original.getNumParticles()==3043
    assert all(system.getParticleMass(i)==original.getParticleMass(i) for i in range(3043))
    for before,after in zip(original.getForces(),system.getForces()):
        assert type(before)==type(after)
        if not isinstance(before,mm.PeriodicTorsionForce):
            assert mm.XmlSerializer.serialize(before)==mm.XmlSerializer.serialize(after)
    # All changed proper terms must be exactly the four selected attachment keys
    # after restoring the native sugar atom types.
    receipt=read(ART/'cpd-anti-conformational-inputs-v2/receipt.json')
    changed_keys=set()
    for v in receipt['variables']:
        key=tuple(aliases[t]['original_type'] if "'" in aliases[t]['role'] else t for t in v['types'])
        changed_keys.add(min(key,key[::-1]))
    def torsions(s):
        result={}
        for f in s.getForces():
            if not isinstance(f,mm.PeriodicTorsionForce):continue
            for i in range(f.getNumTorsions()):
                a,b,c,d,n,p,k=f.getTorsionParameters(i)
                ids=(a,b,c,d);ids=min(ids,ids[::-1])
                result.setdefault(ids,[]).append((n,p.value_in_unit(u.radian),k.value_in_unit(u.kilocalorie_per_mole)))
        return {k:sorted(v) for k,v in result.items()}
    before,after=torsions(original),torsions(system)
    assert set(before)==set(after)
    changes=[]
    for ids in before:
        if before[ids]==after[ids]:continue
        types=tuple(psf.atom_list[i].attype for i in ids)
        assert min(types,types[::-1]) in changed_keys
        changes.append(dict(indices=ids,types=types,before=before[ids],after=after[ids]))
    assert len(changes)==4
    xyz=np.loadtxt(coords);np.savetxt(ROOT/'starting_A.txt',xyz)
    with (ROOT/'anti.pdb').open('w') as handle:app.PDBFile.writeFile(psf.topology,xyz*u.angstrom,handle)
    binary(ROOT/'start.coor',xyz)
    integrator=mm.VerletIntegrator(.001);ctx=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    ctx.setPositions(xyz*u.angstrom);st=ctx.getState(getEnergy=True,getForces=True)
    energy=st.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
    forces=np.array(st.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    np.savez(ROOT/'openmm_static.npz',energy_kcal=energy,forces_kcal_A=forces)
    executable=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')
    config=['structure anti.psf','coordinates anti.pdb','binCoordinates start.coor','paraTypeCharmm on']
    config.extend('parameters '+str(p) for p in parents if p.suffix=='.prm')
    config.extend(['parameters anti_dna_overlay.prm','exclude scaled1-4','oneFourScaling 1',
        'cutoff 1000','switching off','pairlistdist 1002','margin 2','stepspercycle 1',
        'rigidBonds none','timestep 1','temperature 0','outputName static','run 0','output onlyforces static'])
    save(ROOT/'native_plan.json',dict(namd=source(executable),coordinate_span_A=np.ptp(xyz,axis=0).tolist(),
        cutoff_A=1000,parameters=[source(p) for p in parents if p.suffix=='.prm']+[source(ROOT/'anti_dna_overlay.prm')],
        policy=source(POLICY),full_DNA_dynamics=False))
    values,notes=native(executable,ROOT,'\n'.join(config)+'\n')
    nf=read_binary(ROOT/'static.force',3043)
    de=float(abs(values[-1]['POTENTIAL']-energy));df=float(np.max(abs(nf-forces)))
    policy=read(POLICY)['engine']
    elimit=max(policy['native_equivalence_absolute_energy_kcal'],policy['native_equivalence_relative_limit']*abs(energy))
    flimit=max(policy['native_equivalence_absolute_force_kcal_A'],policy['native_equivalence_relative_limit']*float(np.max(abs(forces))))
    passed=bool(de<=elimit and df<=flimit)
    save(ROOT/'assessment.json',dict(parameter_coverage_passed=True,exact_four_attachment_torsions_changed=True,
        changes=changes,all_other_forces_and_particles_exactly_unchanged=True,full_DNA_static_NAMD_passed=passed,
        energy_error_kcal=de,force_error_kcal_A=df,energy_tolerance=elimit,force_tolerance=flimit,
        reference_energy_kcal=energy,reference_max_force_kcal_A=float(np.max(abs(forces))),
        coordinate_stationarity=False,full_DNA_dynamics_tested=False,preliminary_research_qualified=False,
        simulation_ready=False,native_log=source(ROOT/'run.log'),warnings=notes,
        psf=source(ROOT/'anti.psf'),parameters=source(ROOT/'anti_dna_overlay.prm'),system=source(ROOT/'system.xml')))
    print(json.dumps(dict(full_DNA_static_NAMD_passed=passed,energy_error_kcal=de,force_error_kcal_A=df,changed_torsions=len(changes)),indent=2))
    if not passed:raise RuntimeError('Full-DNA native mismatch')


if __name__=='__main__':main()
