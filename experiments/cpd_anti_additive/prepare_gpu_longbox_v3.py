"""Re-solvate frozen pre-startup solutes; no forcefield or chemistry changes."""
import os,sys,shutil,subprocess,warnings
from pathlib import Path
import numpy as np
import openmm as mm
from openmm import app,unit as u
from scipy.spatial import cKDTree
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.run_engine_v2 import binary,read_binary
from experiments.cpd_anti_additive.solvated_construction_v1 import GMX,WATER,pdb_text,params,geometry,atom_identity
from experiments.cpd_anti_additive.solvated_engine_v3 import geometry_passed
from backend.core.namd_solvate import _Water,_parse_gro,_extend_psf,_build_solvated_pdb
ART=REPO/'.development-artifacts';ROOT=ART/'cpd-anti-gpu-longbox-v3';PARENT=ART/'cpd-anti-context-v3';BOX=np.array([64.93,87.438,132.763]);SHIFT=np.array([10.,10.,10.]);N=3043

def prepare():
 ROOT.mkdir(exist_ok=False);shutil.copyfile(Path(__file__),ROOT/'preparation_source.py')
 shutil.copytree(PARENT/'forcefield',ROOT/'forcefield')
 seeds={case:read_binary(PARENT/case/'start.coor',30867)[:N]+SHIFT for case in ['anti','control']}
 union=np.concatenate(list(seeds.values()));assert (union>0).all() and (union<BOX).all();tree=cKDTree(union,boxsize=BOX)
 pack=ROOT/'packing';pack.mkdir()
 with (pack/'gmx.log').open('w') as f:
  subprocess.run([str(GMX),'solvate','-cs',str(WATER),'-box',*(str(v/10) for v in BOX),'-o','water.gro','-nobackup'],cwd=pack,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=300)
 waters,box=_parse_gro((pack/'water.gro').read_text());assert np.max(abs(np.array(box)*10-BOX))<.00011
 kept=[]
 for w in waters:
  x=np.array([w.ox,w.oy,w.oz,w.h1x,w.h1y,w.h1z,w.h2x,w.h2y,w.h2z]).reshape(3,3)*10
  v=x[1:]-x[0];v-=BOX*np.rint(v/BOX);e1=v[0]/np.linalg.norm(v[0]);e2=v[1]-v[1]@e1*e1;e2/=np.linalg.norm(e2)
  t=np.deg2rad(104.52);x[1]=x[0]+.9572*e1;x[2]=x[0]+.9572*(np.cos(t)*e1+np.sin(t)*e2)
  ds=tree.query(x%BOX)[0]
  if ds[0]>=3 and min(ds)>=1.5:kept.append(x)
 xyz=np.array(kept);ox=xyz[:,0]%BOX;pairs=round(.150*np.prod(BOX)*6.02214076e-4);nna=pairs+93;ncl=pairs;chosen=[]
 for i in np.random.default_rng(41017).permutation(len(ox)):
  if tree.query(ox[i])[0]<5:continue
  if chosen:
   d=ox[chosen]-ox[i];d-=BOX*np.rint(d/BOX)
   if np.linalg.norm(d,axis=1).min()<5:continue
  chosen.append(int(i))
  if len(chosen)==nna+ncl:break
 assert len(chosen)==nna+ncl
 na=ox[chosen[:nna]]/10;cl=ox[chosen[nna:]]/10;remaining=np.delete(xyz,chosen,axis=0)
 waters=[_Water(*(x.ravel()/10)) for x in remaining];solvent=np.concatenate([remaining.reshape(-1,3),na*10,cl*10]);reports=[]
 for case in ['anti','control']:
  out=ROOT/case;out.mkdir();old=ART/'cpd-anti-solvated-engine-v3'/case
  shutil.copyfile(old/'solute.psf',out/'solute.psf');shutil.copyfile(PARENT/case/'geometry_reference.json',out/'geometry_reference.json')
  np.savetxt(out/'source_A.txt',np.loadtxt(PARENT/case/'source_A.txt')+SHIFT)
  sol=app.CharmmPsfFile(str(out/'solute.psf'));assert len(sol.atom_list)==N
  x=np.vstack([seeds[case],solvent]);binary(out/'start.coor',x)
  (out/'system.psf').write_text(_extend_psf((out/'solute.psf').read_text(),waters,na.tolist(),cl.tolist()))
  (out/'system.pdb').write_text(_build_solvated_pdb(pdb_text(sol,seeds[case]),waters,na.tolist(),cl.tolist(),tuple(BOX/10),N))
  full=app.CharmmPsfFile(str(out/'system.psf'));assert len(full.atom_list)==len(x)
  assert [atom_identity(a) for a in full.atom_list[:N]]==[atom_identity(a) for a in sol.atom_list]
  assert abs(sum(a.charge for a in full.atom_list))<1e-8
  assert {tuple(sorted([b.atom1.idx,b.atom2.idx])) for b in full.bond_list if b.atom1.idx<N or b.atom2.idx<N}=={tuple(sorted([b.atom1.idx,b.atom2.idx])) for b in sol.bond_list}
  names=['par_all36_na.prm','par_all36_cgenff.prm']+(['anti_dna_overlay.prm'] if case=='anti' else [])+['water_ions.prm']
  par=params([ROOT/'forcefield'/name for name in names]);full.setBox(*(float(v)*u.angstrom for v in BOX))
  system=full.createSystem(par,nonbondedMethod=app.PME,nonbondedCutoff=1.2*u.nanometer,constraints=app.HBonds,rigidWater=True,ewaldErrorTolerance=1e-6)
  masses=[system.getParticleMass(i).value_in_unit(u.dalton) for i in range(len(x))]
  assert np.allclose(masses,[a.mass.value_in_unit(u.dalton) for a in full.atom_list],atol=1e-10,rtol=0)
  (out/'coverage_system.xml').write_text(mm.XmlSerializer.serialize(system));g=geometry(out,x);assert geometry_passed(g)
  save(out/'seed_geometry.json',g)
  reports.append(dict(case=case,atoms=len(x),solute_atoms=N,charge_e=float(sum(a.charge for a in full.atom_list)),solute_identity_and_bonds_preserved=True,ordinary_masses=True,parameter_coverage=True,source_coordinates=source(PARENT/case/'start.coor'),coordinates=source(out/'start.coor')))
 shutil.copyfile(PARENT/'observables_registration.json',ROOT/'observables_registration.json')
 save(ROOT/'assembly.json',dict(at=now(),box_A=BOX.tolist(),translation_A=SHIFT.tolist(),waters=len(waters),sodium=nna,chloride=ncl,salt_pairs=pairs,excess_salt_molar=pairs/(np.prod(BOX)*6.02214076e-4),cases=reports,shared_solvent=True,original_context_clock=source(PARENT/'started.json'),source_history='Original pre-startup seeds; differing historical conditioning disclosed. Failed GPU/context trajectories not reused.',simulation_ready=False))
 save(ROOT/'preparation_inputs.json',dict(at=now(),inputs=[source(GMX),source(WATER),source(Path(__file__)),source(REPO/'backend/core/namd_solvate.py')]+[source(PARENT/case/'start.coor') for case in ['anti','control']]))
 print(dict(atoms=reports[0]['atoms'],waters=len(waters),sodium=nna,chloride=ncl,box_A=BOX.tolist()))

if __name__=='__main__':prepare()
