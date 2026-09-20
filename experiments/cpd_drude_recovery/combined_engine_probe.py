"""Assemble isolated capped CPD bonded, LJ and Drude native force comparison."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import numpy as np
import openmm as mm
from openmm import app,unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded,PROBE,source,write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from experiments.cpd_drude_recovery.engine_compare import NAMD

parser=argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path('.development-artifacts/cpd-combined-native-engine-v3'))
parser.add_argument('--bondroot', type=Path, default=Path('.development-artifacts/cpd-bonded-native-engine-v1'))
parser.add_argument('--stage', type=Path, default=Path('.development-artifacts/cpd-drude-bonded-equilibrium-v2'))
args=parser.parse_args()
root=args.root.resolve()
root.mkdir(exist_ok=False)
original=Path('.development-artifacts/cpd-corrected-engine-v1').resolve()
bondroot=args.bondroot.resolve()
stage=args.stage.resolve()
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
frozen=recovery/'corrected_parameters.training_frozen.json'
physical=AdiabaticNonbonded(recovery,frozen)
d=physical.d
model=physical.model
native_names=[l.split()[1] for l in (original/'cpd.rtf').read_text().splitlines() if l.startswith('ATOM ')][:-1]
mapping=dict(zip(native_names,d.NAMES))
lines,atoms,sections=atoms_and_terms((original/'cpd_q0.psf').read_text())
rows=list(atoms.values())
order=[]
for i,row in enumerate(rows):
    if row[4] in mapping: j=d.NAMES.index(mapping[row[4]])
    elif row[5]=='DRUD': j=model.drude_indices[d.POLARIZABLE.index(mapping[rows[i-1][4]])]
    elif row[4]=='Q': j=model.external_index
    else: raise ValueError('Unmapped particle')
    order.append(j)
nuclear_to_serial={j:i+1 for i,j in enumerate(order) if j<36}
_,_,bonded=atoms_and_terms((bondroot/'candidate.psf').read_text())
# Retain the audited nuclear/Drude/lone-pair bonds; add explicit candidate
# angles/torsions/impropers instead of asking psfgen to infer them.
assert {tuple(sorted(nuclear_to_serial[i-1] for i in pair)) for pair in bonded['NBOND'][3]}=={tuple(sorted(pair)) for pair in sections['NBOND'][3] if all(order[i-1]<36 for i in pair)}
for tag in sorted(('NTHETA','NPHI','NIMPHI'),key=lambda t:sections[t][0],reverse=True):
    start,end,width,_=sections[tag]
    terms=[tuple(nuclear_to_serial[i-1] for i in term) for term in bonded[tag][3]]
    flat=[i for term in terms for i in term]
    lines[start:end]=[f'{len(terms):10d} !{tag}']+[''.join(f'{v:10d}' for v in flat[i:i+8]) for i in range(0,len(flat),8)]
natom=next(i for i,line in enumerate(lines) if '!NATOM' in line)
for i,j in enumerate(order):
    if j>=36: continue
    row=lines[natom+1+i].split()
    row[5]=f'X{j:02d}'
    lines[natom+1+i]=' '.join(row)
(root/'candidate.psf').write_text('\n'.join(lines)+'\n')
pars=app.CharmmParameterSet(*[str(PROBE/n) for n in ('master.rtf','master.prm','na.prm')])
text=(bondroot/'candidate.prm').read_text().split('NONBONDED')[0]
extra=[]
for i in range(36):
    extra += [f'X{i:02d} DRUD {pars.bond_types[("DRUD","X")].k:.15g} 0.0',f'X{i:02d} LPDNA1 0.0 0.35']
text=text.replace('ANGLES\n','\n'.join(extra)+'\nANGLES\n',1)
text+='NONBONDED nbxmod 5 atom cdiel shift vatom vdistance vswitch -\ncutnb 110.0 ctofnb 100.0 ctonnb 99.0 eps 1.0 e14fac 1.0 wmin 1.5\n'
for i,name in enumerate(d.ATOM_NAMES):
    p=pars.atom_types_str[physical.types[name.split(':')[1]]]
    text+=f'X{i:02d} 0 {-abs(p.epsilon):.15g} {p.rmin:.15g} 0 {-abs(p.epsilon_14):.15g} {p.rmin_14:.15g}\n'
text+='QEXT 0 0 0.01\nEND\n'
(root/'candidate.prm').write_text(text)
shutil.copy2(original/'master.prm',root/'master.prm')
shutil.copy2(original/'cpd_built.pdb',root/'candidate.pdb')
system=mm.XmlSerializer.deserialize((stage/'basis/linear_fit_system.xml').read_text())
integrator=mm.VerletIntegrator(.001)
context=mm.Context(system,integrator,mm.Platform.getPlatformByName('Reference'))
fit=json.loads((stage/'selected_response_fit.json').read_text())
for p in fit['parameters']: context.setParameter(p['name'],p['coefficient'])
offset=json.loads((bondroot/'policy.json').read_text())['energy_offset_charmm_minus_linear_kcal_mol']
write(root/'policy.json',{'simulation_ready':False,'gate_effect':'none','scope':'Complete capped anti candidate: bonded, intramolecular LJ including 1-4, Drude electrostatics and virtual LP force redistribution. Fixed coordinates only; no physical accuracy, nucleotide or DNA acceptance.','energy_tolerance_kcal_mol':.001,'maximum_force_tolerance_kcal_mol_angstrom':.001,'sources':[source(p) for p in (frozen,stage/'selected_response_fit.json',stage/'basis/linear_fit_system.xml',bondroot/'candidate.prm',bondroot/'candidate.psf',original/'cpd_q0.psf',NAMD,Path(__file__))]})
records=[]
for case in range(5):
    data=(bondroot/f'case{case}.coor').read_bytes()
    assert struct.unpack('<i',data[:4])[0]==36
    xyz=np.frombuffer(data,dtype='<f8',offset=4).reshape(36,3)
    energy_nb,gradient_nb=physical.energy_gradient(xyz)
    state=model.context.getState(getPositions=True,getForces=True)
    full=np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    force_nb=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    native_xyz=full[order]
    label=f'case{case}'
    (root/f'{label}.coor').write_bytes(struct.pack('<i',len(order))+np.asarray(native_xyz,dtype='<f8').tobytes())
    context.setPositions(xyz*u.angstrom)
    bonded_state=context.getState(getEnergy=True,getForces=True)
    expected_energy=float(energy_nb+bonded_state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)+offset)
    expected_force=force_nb.copy()
    expected_force[:36]+=np.array(bonded_state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    template=(Path('.development-artifacts/cpd-drude-nuclear-force-probe-v3')/'baseline.conf').read_text()
    conf=template.replace('structure cpd_q0.psf','structure candidate.psf').replace('coordinates cpd_built.pdb','coordinates candidate.pdb').replace('parameters cpd.prm','parameters candidate.prm')
    conf='\n'.join(f'binCoordinates {label}.coor' if line.startswith('binCoordinates ') else line for line in conf.splitlines())+'\n'
    conf=conf.replace('outputName baseline',f'outputName {label}').replace('output onlyforces baseline',f'output onlyforces {label}')
    (root/f'{label}.conf').write_text(conf)
    with (root/f'{label}.log').open('w') as out:
        subprocess.run([str(NAMD),'+p1',f'{label}.conf'],cwd=root,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=60)
    log=(root/f'{label}.log').read_text()
    assert 'End of program' in log
    titles=next(l.split()[1:] for l in log.splitlines() if l.startswith('ETITLE:'))
    energy=dict(zip(titles,map(float,[l.split()[1:] for l in log.splitlines() if l.startswith('ENERGY:')][-1])))
    force_data=(root/f'{label}.force').read_bytes()
    assert struct.unpack('<i',force_data[:4])[0]==len(order)
    native=np.frombuffer(force_data,dtype='<f8',offset=4).reshape(-1,3)
    physical_indices=[i for i,j in enumerate(order) if j<36 or j in model.drude_indices]
    error=float(abs(native[physical_indices]-expected_force[order][physical_indices]).max())
    ediff=float(energy['POTENTIAL']-expected_energy)
    records.append({'case':label,'energy_difference_kcal_mol':ediff,'max_force_difference_kcal_mol_angstrom':error,'max_drude_displacement_angstrom':physical.max_displacement,'max_drude_residual_force':physical.max_drude_force,'passed_diagnostic':abs(ediff)<.001 and error<.001,'native_log':source(root/f'{label}.log'),'forces':source(root/f'{label}.force'),'coordinates':source(root/f'{label}.coor')})
    write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','completed_cases':len(records),'planned_cases':5,'all_cases_passed':len(records)==5 and all(r['passed_diagnostic'] for r in records),'records':records})
print(json.dumps([{k:v for k,v in r.items() if k not in ('native_log','forces','coordinates')} for r in records],indent=2))
