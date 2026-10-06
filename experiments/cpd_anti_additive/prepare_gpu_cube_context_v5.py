"""Prepare final matched cubic inputs using frozen diagnostic salt calibration.

Asset construction only: no dynamics, deadline change, or production admission.
"""
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
ART=REPO/'.development-artifacts';ROOT=ART/'cpd-anti-gpu-cube-context-v5';PARENT=ART/'cpd-anti-context-v3';BOX=np.array([140.,140.,140.]);SHIFT=(BOX-np.array([44.93,67.438,112.763]))/2;N=3043

QUALIFICATION=ART/'cpd-anti-gpu-force-switch-qualification-v3'
PACKING_SOURCE=ART/'cpd-anti-gpu-cube-diagnostic-v5/packing/water.gro'

def preparation_plan():
 failure=ART/'cpd-anti-gpu-npt-anti-1-failure-audit-v4/assessment.json'
 evidence=read(failure);assert evidence['audit_complete'] and evidence['non_image_failures']==0
 D=evidence['maximum_observed_solute_diameter_A'];assert D<113
 dependencies=[Path(__file__),PACKING_SOURCE,REPO/'backend/core/namd_solvate.py',failure]
 from experiments.cpd_anti_additive.native_log_v3 import parse_log
 diagnostic=ART/'cpd-anti-gpu-cube-diagnostic-v5'
 logs=[diagnostic/c/'replica-1/npt/run.log' for c in ['anti','control']]
 dependencies+=logs+[diagnostic/'startup_assessment.json',diagnostic/'diagnostic_plan.json']
 for pin in read(diagnostic/'diagnostic_plan.json')['inputs']:checked(pin)
 volume=float(np.mean([r['VOLUME'] for log in logs for r in parse_log(log)[-250:]]))
 dependencies += [REPO/'experiments/cpd_anti_additive'/f'{name}.py' for name in ['validation_gate','sella_pilot','run_engine_v2','solvated_construction_v1','solvated_engine_v3','native_log_v3']]
 inputs=dependencies+[PARENT/'started.json',PARENT/'observables_registration.json']
 inputs += sorted(p for p in (PARENT/'forcefield').iterdir() if p.is_file())
 for case in ['anti','control']:
  inputs += [PARENT/case/n for n in ['start.coor','geometry_reference.json','source_A.txt']]
  inputs += [ART/'cpd-anti-solvated-engine-v3'/case/'solute.psf']
 pairs=round(.150*volume*6.02214076e-4);assert pairs==237
 return dict(at=now(),schema='nadoc.cpd-cube-final-preparation.v5',scope='Static final237-pair matched preparation; full campaign awaits explicit replacement budget admission.',
  calibration=dict(salt_pairs=pairs,sodium=pairs+93,chloride=pairs,neutralizing_sodium=93,target_added_NaCl_molar=.150,pooled_late500ps_volume_A3=volume,predicted_added_NaCl_molar=pairs/(volume*6.02214076e-4),rule='Nearest150mM frompooledlate500ps ofboth cubicNPTdiagnostics, frozen before finalpreparation. ReportactualfinalNPTconcentration without outcome-driven tuning.',convention='Added NaCl pairs/full cell volume, excludes neutralizing sodium.'),
  cell_design=dict(initial_box_A=BOX.tolist(),observed_Dmax_A=D,recorded_rotation_independent_minimum_A=D+12,initial_clearance_lower_bound_A=140-D,
   contraction_allowance='Even5percent linear shrink gives133A, 20.43A above observed diameter. Actual NPT cells and future conformations must still be checked against unchanged12A gate.',
   alternative='Virtualy+20 passes recordedframes but leaves shorterx and rotational vulnerability. Cube selected to address orientation, not merely the failedframe.'),
  assembly=dict(box_A=BOX.tolist(),translation_A=SHIFT.tolist(),source='Original pre-startup solutes, freshly packed common water, no failed trajectory coordinates.',ion_random_seed=41017,shared_solvent=True),
  intended_dynamics='Freshsixmatched10ns GPUresident force-switch NPT after exactfinal-systemqualification; campaign budget approval pending.',
  full_campaign_admitted=False,simulation_ready=False,minimum_certified=False,inputs=[source(p) for p in inputs])

def prepare():
 plan=preparation_plan()
 ROOT.mkdir(exist_ok=False);shutil.copyfile(Path(__file__),ROOT/'preparation_source.py')
 save(ROOT/'preparation_plan.json',plan)
 for pin in plan['inputs']:checked(pin)
 shutil.copytree(PARENT/'forcefield',ROOT/'forcefield')
 seeds={case:read_binary(PARENT/case/'start.coor',30867)[:N]+SHIFT for case in ['anti','control']}
 union=np.concatenate(list(seeds.values()));assert (union>0).all() and (union<BOX).all();tree=cKDTree(union,boxsize=BOX)
 pack=ROOT/'packing';pack.mkdir()
 shutil.copyfile(PACKING_SOURCE,pack/'water.gro')
 save(pack/'provenance.json',dict(packing_source=source(PACKING_SOURCE),same_empty140A_cube_packing=True,no_new_gromacs_run=True))
 waters,box=_parse_gro((pack/'water.gro').read_text());assert np.max(abs(np.array(box)*10-BOX))<.00011
 kept=[]
 for w in waters:
  x=np.array([w.ox,w.oy,w.oz,w.h1x,w.h1y,w.h1z,w.h2x,w.h2y,w.h2z]).reshape(3,3)*10
  v=x[1:]-x[0];v-=BOX*np.rint(v/BOX);e1=v[0]/np.linalg.norm(v[0]);e2=v[1]-v[1]@e1*e1;e2/=np.linalg.norm(e2)
  t=np.deg2rad(104.52);x[1]=x[0]+.9572*e1;x[2]=x[0]+.9572*(np.cos(t)*e1+np.sin(t)*e2)
  ds=tree.query(x%BOX)[0]
  if ds[0]>=3 and min(ds)>=1.5:kept.append(x)
 xyz=np.array(kept);ox=xyz[:,0]%BOX;pairs=plan['calibration']['salt_pairs'];nna=pairs+93;ncl=pairs;chosen=[]
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
  assert len(x)==N+3*len(waters)+nna+ncl and (nna,ncl)==(330,237)
  assert np.allclose(masses,[a.mass.value_in_unit(u.dalton) for a in full.atom_list],atol=1e-10,rtol=0)
  (out/'coverage_system.xml').write_text(mm.XmlSerializer.serialize(system));g=geometry(out,x);assert geometry_passed(g)
  save(out/'seed_geometry.json',g)
  reports.append(dict(case=case,atoms=len(x),solute_atoms=N,mass_Da=float(sum(masses)),charge_e=float(sum(a.charge for a in full.atom_list)),solute_identity_and_bonds_preserved=True,ordinary_masses=True,parameter_coverage=True,source_coordinates=source(PARENT/case/'start.coor'),coordinates=source(out/'start.coor')))
 shutil.copyfile(PARENT/'observables_registration.json',ROOT/'observables_registration.json')
 save(ROOT/'assembly.json',dict(at=now(),box_A=BOX.tolist(),translation_A=SHIFT.tolist(),waters=len(waters),sodium=nna,chloride=ncl,salt_pairs=pairs,initial_added_NaCl_molar=pairs/(np.prod(BOX)*6.02214076e-4),salt_calibration=plan['calibration'],actual_equilibrated_concentration_pending=True,cases=reports,shared_solvent=True,original_context_clock=source(PARENT/'started.json'),source_history='Original pre-startup seeds; differing historical conditioning disclosed. Failed GPU/context trajectories not reused.',simulation_ready=False))
 assert np.array_equal(read_binary(ROOT/'anti/start.coor',reports[0]['atoms'])[N:],read_binary(ROOT/'control/start.coor',reports[1]['atoms'])[N:])
 for path in (ROOT/'forcefield').iterdir():assert source(path)['sha256']==source(PARENT/'forcefield'/path.name)['sha256']
 for pin in plan['inputs']:checked(pin)
 save(ROOT/'preparation_inputs.json',dict(at=now(),plan=source(ROOT/'preparation_plan.json'),inputs=plan['inputs'],shared_solvent_exact=True,forcefield_bytes_unchanged=True,no_native_runs=True,production_hold=True,budget_extension_approved=False,simulation_ready=False,minimum_certified=False))
 save(ROOT/'inputs_lock.json',dict(at=now(),files=[source(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and p.name!='inputs_lock.json']))
 print(dict(atoms=reports[0]['atoms'],waters=len(waters),sodium=nna,chloride=ncl,box_A=BOX.tolist()))

if __name__=='__main__':prepare()
