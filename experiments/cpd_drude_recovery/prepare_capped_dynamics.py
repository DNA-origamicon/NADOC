"""Prepare isolated thermal diagnostics with physical Drude mass partition."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import sys

import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from experiments.cpd_drude_recovery.engine_compare import NAMD

parser=argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path('.development-artifacts/cpd-capped-dynamics-v1'))
parser.add_argument('--origin', type=Path, default=Path('.development-artifacts/cpd-combined-native-engine-v3'))
parser.add_argument('--stage', type=Path, default=Path('.development-artifacts/cpd-drude-bonded-equilibrium-v2'))
args=parser.parse_args()
root=args.root.resolve()
root.mkdir(exist_ok=False)
origin=args.origin.resolve()
assert json.loads((origin/'assessment.json').read_text())['all_cases_passed']
lines,atoms,sections=atoms_and_terms((origin/'candidate.psf').read_text())
assert len(atoms)==65 and atoms[65][4]=='Q' and float(atoms[65][6])==0
assert all(65 not in t for section in sections.values() for t in section[3])
system_path=(args.stage/'basis/linear_fit_system.xml').resolve()
system=mm.XmlSerializer.deserialize(system_path.read_text())
# Remove the unused zero-charge external test particle and its exclusion pointer.
natom=next(i for i,line in enumerate(lines) if '!NATOM' in line)
del lines[natom+65]
lines[natom]='        64 !NATOM'
adjacency={i:set() for i in atoms}
for a,b in sections['NBOND'][3]: adjacency[a].add(b);adjacency[b].add(a)
records=[]
for i,row in atoms.items():
    if not row[5].startswith('X') or i==65: continue
    nuclear=int(row[5][1:])
    mass=system.getParticleMass(nuclear).value_in_unit(u.dalton)
    drudes=[j for j in adjacency[i] if atoms[j][5]=='DRUD']
    assert len(drudes)<=1
    drude_mass=sum(float(atoms[j][7]) for j in drudes)
    assert not drudes or abs(drude_mass-.4)<1e-12
    new=lines[natom+i].split()
    new[7]=f'{mass-drude_mass:.8f}'
    lines[natom+i]=' '.join(new)
    records.append({'serial':i,'type':row[5],'physical_nuclear_mass':mass,'core_mass':mass-drude_mass,'drude_mass':drude_mass})
assert len(records)==36
nnb=next(i for i,line in enumerate(lines) if '!NNB' in line)
end=next(i for i in range(nnb+1,len(lines)) if '!NGRP' in lines[i])
assert int(lines[nnb].split()[0])==0
pointers=[int(v) for line in lines[nnb+1:end] for v in line.split()]
assert len(pointers)==65 and set(pointers)=={0}
lines[nnb+1:end]=[''.join(f'{0:10d}' for _ in range(min(8,64-i))) for i in range(0,64,8)]+['']
(root/'candidate.psf').write_text('\n'.join(lines)+'\n')
for f in ('candidate.prm','master.prm'): shutil.copy2(origin/f,root/f)
pdb=[line for line in (origin/'candidate.pdb').read_text().splitlines() if not line.startswith(('ATOM','HETATM')) or int(line[6:11])!=65]
(root/'candidate.pdb').write_text('\n'.join(pdb)+'\n')
data=(origin/'case0.coor').read_bytes()
assert struct.unpack('<i',data[:4])[0]==65
xyz=np.frombuffer(data,dtype='<f8',offset=4).reshape(65,3)[:64]
(root/'start.coor').write_bytes(struct.pack('<i',64)+np.asarray(xyz,dtype='<f8').tobytes())
_,newatoms,newsections=atoms_and_terms((root/'candidate.psf').read_text())
assert len(newatoms)==64
assert all(newsections[k][3]==sections[k][3] for k in sections)
assert abs(sum(float(a[7]) for a in newatoms.values())-sum(r['physical_nuclear_mass'] for r in records))<1e-7
assert abs(sum(float(a[6]) for a in newatoms.values()))<1e-5
cases=[]
for dt in (.25,.5):
    for seed in (137,281):
        label=f'dt{str(dt).replace(".","p")}_seed{seed}'
        steps=int(5000/dt)
        cases.append({'id':label,'timestep_fs':dt,'seed':seed,'steps':steps,'duration_ps':5})
        base=(origin/'case0.conf').read_text()
        replaces={'coordinates':'coordinates candidate.pdb','binCoordinates':'binCoordinates start.coor','outputName':f'outputName {label}','temperature':'temperature 300','drudeTemp':'drudeTemp 1','langevinTemp':'langevinTemp 300','langevinDamping':'langevinDamping 5','timestep':f'timestep {dt}','stepspercycle':'stepspercycle 10','outputEnergies':'outputEnergies 100','run':f'run {steps}'}
        conf=[]
        for line in base.splitlines():
            fields=line.split()
            if not fields or fields[0]=='output':continue
            if fields[0]=='run':
                conf += [f'seed {seed}',f'DCDfile {label}.dcd','DCDfreq 20',f'restartfreq {steps}','binaryoutput yes','binaryrestart yes']
            conf.append(replaces.get(fields[0],line))
        (root/f'{label}.conf').write_text('\n'.join(conf)+'\n')
write(root/'plan.json',{'simulation_ready':False,'gate_effect':'none','scope':'Isolated capped candidate thermal/integration diagnostics only. No solvent, nucleotide, DNA or physical parameter acceptance. Unaccepted candidate remains isolated.','cases':cases,'warm_temperature_K':300,'cold_drude_temperature_K':1,'drude_damping_per_ps':20,'warm_damping_per_ps':5,'drude_hard_wall_angstrom':.25,'unchanged_electrostatic_domain_angstrom':.2,'mass_audit':records,'sources':[source(p) for p in (origin/'assessment.json',origin/'candidate.psf',origin/'candidate.prm',system_path,NAMD,Path(__file__))],'method_reference':'https://www.ks.uiuc.edu/Research/namd/cvs/ug/node27.html'})
print('Prepared four 5-ps thermal diagnostics; 36 nuclei,20 Drudes,8 LPs; masses conserved.')
