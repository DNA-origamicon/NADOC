"""Check DNA coverage and numerical invariance of all untouched parent terms."""

from pathlib import Path
import sys
import warnings

import openmm as mm
from openmm import app
import parmed as pmd

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import source, checked, read
from experiments.cpd_anti_additive.prepare_engine_v2 import save

ART=REPO/'.development-artifacts'


def scalar(value):
    return value.value_in_unit_system(mm.unit.md_unit_system) if hasattr(value,'value_in_unit_system') else value


def unmodified_terms(force, changed):
    name=type(force).__name__
    methods={
        'HarmonicBondForce':('getNumBonds','getBondParameters',2),
        'HarmonicAngleForce':('getNumAngles','getAngleParameters',3),
        'PeriodicTorsionForce':('getNumTorsions','getTorsionParameters',4),
        'CustomTorsionForce':('getNumTorsions','getTorsionParameters',4),
    }
    if name not in methods:
        raise ValueError(f'Unreviewed bonded force {name}')
    count,getter,width=methods[name]
    result=[]
    for i in range(getattr(force,count)()):
        values=getattr(force,getter)(i)
        if not changed.intersection(int(v) for v in values[:width]):
            result.append(tuple(scalar(v) if not isinstance(v,(list,tuple)) else tuple(v) for v in values))
    return sorted(result)


def review():
    _,receipt=require('engine')
    root=ART/'cpd-anti-dna-topology-v2b'
    assessment=read(root/'assessment.json')
    plan=read(checked(assessment['plan']))
    for ref in assessment['outputs'].values():checked(ref)
    assert assessment['topology_passed'] and assessment['parameter_coverage_passed']
    parent_paths=[checked(ref) for ref in plan['parent_forcefields']]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        parent=app.CharmmParameterSet(*(str(p) for p in parent_paths))
        merged=app.CharmmParameterSet(*(str(p) for p in parent_paths+[root/'anti_dna_overlay.prm']))
        source_parameters=pmd.charmm.CharmmParameterSet(str(checked(plan['parameter_source'])))
        overlay=pmd.charmm.CharmmParameterSet(str(root/'anti_dna_overlay.prm'))
    psfs=[app.CharmmPsfFile(str(root/f'{s}.psf')) for s in ('reactant','anti')]
    changed={i for i,(a,b) in enumerate(zip(psfs[0].atom_list,psfs[1].atom_list)) if a.attype!=b.attype}
    assert len(changed)==28
    systems=[p.createSystem(q,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
             for p,q in zip(psfs,(parent,merged))]
    force_checks=[]
    original_forces=systems[0].getForces()
    product_forces=systems[1].getForces()
    assert [type(f) for f in original_forces]==[type(f) for f in product_forces]
    for index,(a,b) in enumerate(zip(original_forces,product_forces)):
        name=type(a).__name__
        if name=='NonbondedForce':
            count=0
            for i in range(a.getNumParticles()):
                if i not in changed:
                    assert a.getParticleParameters(i)==b.getParticleParameters(i)
                    count+=1
            old={(a.getExceptionParameters(i)[0],a.getExceptionParameters(i)[1]):a.getExceptionParameters(i)[2:]
                 for i in range(a.getNumExceptions()) if not changed.intersection(a.getExceptionParameters(i)[:2])}
            new={(b.getExceptionParameters(i)[0],b.getExceptionParameters(i)[1]):b.getExceptionParameters(i)[2:]
                 for i in range(b.getNumExceptions()) if not changed.intersection(b.getExceptionParameters(i)[:2])}
            assert old==new
            force_checks.append(dict(index=index,force=name,unchanged_particles=count,unchanged_exceptions=len(old)))
        elif name in ('CMMotionRemover','CMAPTorsionForce'):
            assert mm.XmlSerializer.serialize(a)==mm.XmlSerializer.serialize(b)
            if name=='CMAPTorsionForce':
                force_checks.append(dict(index=index,force=name,unchanged_terms=a.getNumTorsions()))
        else:
            old,new=unmodified_terms(a,changed),unmodified_terms(b,changed)
            assert old==new,(name,len(old),len(new))
            force_checks.append(dict(index=index,force=name,unchanged_terms=len(old)))
    transfer=read(checked(assessment['transfer']))
    def coefficients(kind,p):
        if kind=='bond_types':return (p.k,p.req)
        if kind=='angle_types':return (p.k,p.theteq)
        if kind=='dihedral_types':return tuple((v.phi_k,v.per,v.phase,v.scee,v.scnb) for v in p)
        return (p.psi_k,p.psi_eq)
    for item in transfer['mapping']:
        kind=item['kind']
        before=getattr(source_parameters,kind)[tuple(item['source_types'])]
        after=getattr(overlay,kind)[tuple(item['destination_types'])]
        assert coefficients(kind,before)==coefficients(kind,after),(kind,item)
        if kind=='angle_types':
            a=source_parameters.urey_bradley_types[tuple(item['source_types'])]
            b=overlay.urey_bradley_types[tuple(item['destination_types'])]
            assert (a.k,a.req)==(b.k,b.req)
    for force in systems[1].getForces():
        if isinstance(force,mm.NonbondedForce):
            assert force.getNumParticles()==3043
    output=root/'independent_review.json'
    if output.exists():raise FileExistsError(output)
    report=dict(passed=True,assessment=source(root/'assessment.json'),reviewer=source(Path(__file__)),
        exact_coefficient_transfers=len(transfer['mapping']),parent_invariance=force_checks,
        full_DNA_atoms=3043,changed_base_atoms=28,unchanged_parent_atoms=3015,
        parameter_coverage_passed=True,geometry_safe_for_dynamics=False,native_NAMD_tested=False,
        simulation_ready=False,scope='Independent topology/parameter export check; no energy evaluation or dynamics')
    save(output,report)
    print(report)


if __name__=='__main__':review()
