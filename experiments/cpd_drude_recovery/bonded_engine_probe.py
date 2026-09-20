"""Isolated native CHARMM energy/force probe for the frozen 178-term candidate."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,write


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, default=Path('.development-artifacts/cpd-drude-bonded-equilibrium-v2'))
    parser.add_argument('--root', type=Path, default=Path('.development-artifacts/cpd-bonded-native-engine-v1'))
    args=parser.parse_args()
    stage=args.stage.resolve()
    root=args.root.resolve()
    root.mkdir(exist_ok=False)
    fitpath=stage/'selected_response_fit.json'
    fit=json.loads(fitpath.read_text())
    transform_path=stage/'charmm_bonded_transform.json'
    transformed=json.loads(transform_path.read_text())['terms']
    bygroup={t['group_id']:(category,t) for category,terms in transformed.items() for t in terms}
    params={p['name']:p for p in fit['parameters']}
    xmlpath=stage/'basis/linear_fit_system.xml'
    system=mm.XmlSerializer.deserialize(xmlpath.read_text())
    count=system.getNumParticles()
    types=[f'X{i:02d}' for i in range(count)]
    names=[f'A{i:02d}' for i in range(count)]
    terms={k:{} for k in ('bonds','angles','dihedrals','impropers')}
    offset=0.
    def add(category,atoms,values):
        atoms=tuple(map(int,atoms))
        key=atoms if category=='impropers' else min(atoms,atoms[::-1])
        terms[category].setdefault(key,[]).append(values)
    for f in system.getForces():
        if isinstance(f,mm.HarmonicBondForce):
            assert f.getNumBonds()==0
        elif isinstance(f,mm.HarmonicAngleForce):
            assert f.getNumAngles()==0
        elif isinstance(f,mm.PeriodicTorsionForce):
            for i in range(f.getNumTorsions()):
                a,b,c,d,n,phase,k=f.getTorsionParameters(i)
                add('dihedrals',(a,b,c,d),(k.value_in_unit(u.kilocalorie_per_mole),int(n),phase.value_in_unit(u.degree)))
        elif isinstance(f,mm.CustomTorsionForce) and f.getNumGlobalParameters()==0:
            assert f.getEnergyFunction()=='k*atan2(sin(theta-theta0),cos(theta-theta0))^2'
            for i in range(f.getNumTorsions()):
                a,b,c,d,p=f.getTorsionParameters(i)
                add('impropers',(a,b,c,d),(float(p[0])/4.184,0,np.degrees(p[1])))
        else:
            globals=[f.getGlobalParameterName(i) for i in range(f.getNumGlobalParameters())]
            groups={params[n]['group_id'] for n in globals}
            assert len(groups)==1
            category,t=bygroup[groups.pop()]
            if category=='bonds':
                for i in range(f.getNumBonds()):
                    a,b,_=f.getBondParameters(i)
                    add(category,(a,b),(t['k_kcal_mol_a2'],t['r0_angstrom']))
                    offset+=t['k_kcal_mol_a2']*t['r0_angstrom']**2
            elif category=='angles':
                assert t['urey_bradley'] is None
                for i in range(f.getNumBonds()):
                    atoms,_=f.getBondParameters(i)
                    add(category,atoms,(t['k_kcal_mol_rad2'],t['theta0_degrees']))
                    offset+=t['k_kcal_mol_rad2']*np.radians(t['theta0_degrees'])**2
            elif category=='dihedrals':
                for i in range(f.getNumTorsions()):
                    *atoms,_=f.getTorsionParameters(i)
                    for p in t['fourier_terms']:
                        add(category,atoms,(p['k_kcal_mol'],p['periodicity'],p['delta_degrees']))
                        offset+=p['k_kcal_mol']
            elif category=='impropers':
                for i in range(f.getNumTorsions()):
                    *atoms,_=f.getTorsionParameters(i)
                    add(category,atoms,(t['k_kcal_mol_rad2'],0,t['psi0_degrees']))
            else:
                raise ValueError(category)
    # Unique atom types prevent accidental wildcard matches or alias collisions.
    prm=['* Isolated bonded candidate engine probe','*','BONDS']
    for category,header in [('bonds','BONDS'),('angles','ANGLES'),('dihedrals','DIHEDRALS'),('impropers','IMPROPERS')]:
        if category!='bonds': prm.append(header)
        for atoms,values in terms[category].items():
            assert category=='dihedrals' or len(values)==1
            for value in values:
                prm.append(' '.join([*(types[i] for i in atoms),*(f'{v:.15g}' for v in value)]))
    prm+=['NONBONDED nbxmod 5 atom cdiel shift vatom vdistance vswitch -','cutnb 100.0 ctofnb 98.0 ctonnb 96.0 eps 1.0 e14fac 1.0 wmin 1.5']
    prm += [f'{t} 0.0 0.0 1.0' for t in types]
    prm+=['END']
    (root/'candidate.prm').write_text('\n'.join(prm)+'\n')
    psf=['PSF','', '       1 !NTITLE',' REMARKS isolated bonded candidate, all nonbonded interactions zero','',f'{count:8d} !NATOM']
    for i in range(count):
        mass=system.getParticleMass(i).value_in_unit(u.dalton)
        psf.append(f'{i+1:8d} X    1    CPD  {names[i]:<4} {types[i]:<4} 0.000000 {mass:.8f} 0')
    for category,tag in [('bonds','NBOND'),('angles','NTHETA'),('dihedrals','NPHI'),('impropers','NIMPHI')]:
        psf+=['',f'{len(terms[category]):8d} !{tag}']
        flat=[i+1 for atoms in terms[category] for i in atoms]
        psf += [''.join(f'{i:8d}' for i in flat[j:j+8]) for j in range(0,len(flat),8)]
    psf+=['','       0 !NDON','','       0 !NACC','','       0 !NNB',''.join(f'{0:8d}' for _ in range(count)),'','       1       0 !NGRP NST2','       0       0       0','']
    (root/'candidate.psf').write_text('\n'.join(psf))
    integrator=mm.VerletIntegrator(.001)
    context=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
    for name,p in params.items(): context.setParameter(name,p['coefficient'])
    xyz=np.loadtxt(stage/'minimized_nuclear_coordinates_angstrom.txt')
    binary=Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++.cpu/namd3')
    policy={'simulation_ready':False,'gate_effect':'none','energy_tolerance_kcal_mol':0.001,'max_force_tolerance_kcal_mol_angstrom':0.0001,'scope':'Complete candidate nuclear bonded potential only. Nonbonded interactions zero; not full Drude dynamics or physical accuracy validation.','energy_offset_charmm_minus_linear_kcal_mol':offset,'sources':[source(p) for p in (fitpath,transform_path,xmlpath,binary,Path(__file__))]}
    write(root/'policy.json',policy)
    rng=np.random.default_rng(103)
    records=[]
    for j,x in enumerate([xyz,*[xyz+rng.normal(scale=.015,size=xyz.shape) for _ in range(4)]]):
        label=f'case{j}'
        (root/f'{label}.coor').write_bytes(struct.pack('<i',count)+np.asarray(x,dtype='<f8').tobytes())
        (root/f'{label}.pdb').write_text('\n'.join(f'ATOM  {i+1:5d} {names[i]:<4} CPD X   1    {p[0]:8.3f}{p[1]:8.3f}{p[2]:8.3f}  1.00  0.00      X   ' for i,p in enumerate(x))+'\nEND\n')
        conf=f'''structure candidate.psf
coordinates {label}.pdb
binCoordinates {label}.coor
paraTypeCharmm on
parameters candidate.prm
exclude scaled1-4
1-4scaling 1.0
switching off
cutoff 100
pairlistdist 110
margin 2
outputName {label}
temperature 0
rigidBonds none
timestep 1
stepspercycle 1
outputEnergies 1
run 0
output onlyforces {label}
'''
        (root/f'{label}.conf').write_text(conf)
        with (root/f'{label}.log').open('w') as out:
            subprocess.run([str(binary),'+p1',f'{label}.conf'],cwd=root,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=60)
        log=(root/f'{label}.log').read_text()
        assert 'End of program' in log
        title=next(l.split()[1:] for l in log.splitlines() if l.startswith('ETITLE:'))
        energy=dict(zip(title,map(float,[l.split()[1:] for l in log.splitlines() if l.startswith('ENERGY:')][-1])))
        data=(root/f'{label}.force').read_bytes()
        assert struct.unpack('<i',data[:4])[0]==count
        native_force=np.frombuffer(data,dtype='<f8',offset=4).reshape(count,3)
        context.setPositions(x*u.angstrom)
        state=context.getState(getEnergy=True,getForces=True)
        expected=state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)+offset
        expected_force=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
        delta_energy=float(energy['POTENTIAL']-expected)
        delta_force=float(abs(native_force-expected_force).max())
        records.append({'case':label,'energy_difference_kcal_mol':delta_energy,'max_force_difference_kcal_mol_angstrom':delta_force,'passed':abs(delta_energy)<=.001 and delta_force<=.0001})
        write(root/'results.json',{'simulation_ready':False,'gate_effect':'none','completed_cases':len(records),'planned_cases':5,'records':records,'all_cases_passed':len(records)==5 and all(r['passed'] for r in records)})
    print(json.dumps(records,indent=2))

if __name__=='__main__': main()
