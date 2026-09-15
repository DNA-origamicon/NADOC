"""Isolated open-pore controls using NADOC's existing solvent/topology writers."""
from pathlib import Path
import numpy as np, json, subprocess, shutil
from backend.core.namd_solvate import _hetatm_record,_graphene_identity,_parse_gro,_exclude_waters_near_graphene,_extend_psf,_build_solvated_pdb
from backend.core.namd_package import complete_psf
from backend.core.models import Design
root=Path(__file__).resolve().parent
source=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated'
base=root/'open_pore';base.mkdir(exist_ok=True)
box=np.array([29*.426,50*np.sqrt(3)*.142,12.]);center=box/2
atoms=[]
for i in range(29):
 for j in range(50):
  for a,b in [(0,0),(1/3,0),(1/2,1/2),(5/6,1/2)]:
   xy=(np.array([i+a,j+b])*[.426,np.sqrt(3)*.142]+center[:2])%box[:2]
   d=xy-center[:2];d-=box[:2]*np.round(d/box[:2])
   if d@d<16:continue
   seg,rid=_graphene_identity(len(atoms));atoms.append(_hetatm_record(len(atoms)+1,'C','GRP','G',rid,xy[0]*10,xy[1]*10,center[2]*10,seg))
dry='\n'.join(atoms+['END','']);(base/'dry.pdb').write_text(dry)
for cmd in [['gmx','editconf','-f','dry.pdb','-o','dry.gro','-noc','-box',*[str(x) for x in box],'-nobackup'],['gmx','solvate','-cp','dry.gro','-cs','spc216.gro','-o','solvated.gro','-nobackup']]:
 with (base/(cmd[1]+'.log')).open('w') as f:subprocess.run(cmd,cwd=base,stdout=f,stderr=subprocess.STDOUT,check=True)
waters,_=_parse_gro((base/'solvated.gro').read_text());waters,removed=_exclude_waters_near_graphene(waters,dry,clearance_nm=.3,box_nm=box)
# Neutral 150 mM NaCl; identical composition model, not DNA counterion excess.
rng=np.random.default_rng(6142026);nsalt=round(np.prod(box)*.15*.602214076)
idx=rng.choice(len(waters),2*nsalt,replace=False);coords=[(waters[i].ox,waters[i].oy,waters[i].oz) for i in idx];na=coords[:nsalt];cl=coords[nsalt:];ix=set(idx);waters=[w for i,w in enumerate(waters) if i not in ix]
for fraction in [1.0,.96,.92]:
 label=f'fill_{round(fraction*100)}';folder=base/label;folder.mkdir(exist_ok=True)
 # Random whole-molecule removal diagnoses underfill without an imposed cavity.
 keep=np.sort(rng.choice(len(waters),round(fraction*len(waters)),replace=False));w=[waters[i] for i in keep]
 psf=_extend_psf(complete_psf(Design()),w,na,cl,graphene_atoms=len(atoms));pdb=_build_solvated_pdb(dry,w,na,cl,box,len(atoms))
 (folder/'system.psf').write_text(psf);(folder/'system.pdb').write_text(pdb)
 restraint='\n'.join(l[:60]+f'{50.0 if l[17:21].strip()=="GRP" else 0.0:6.2f}'+l[66:] if l.startswith(('ATOM  ','HETATM')) else l for l in pdb.splitlines())+'\n';(folder/'wall.pdb').write_text(restraint)
 meta={'box_nm':box.tolist(),'pore_center_nm':center.tolist(),'pore_radius_nm':4,'water_count':len(w),'salt_pairs':nsalt,'graphene_atoms':len(atoms),'fill_fraction_of_solvated':fraction,'removed_overlapping_waters':removed}
 (folder/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
 conf=f'''structure {folder/'system.psf'}
coordinates {folder/'system.pdb'}
paraTypeCharmm on
'''+''.join(f'parameters {source/"forcefield"/param}\n' for param in ['par_all36_na.prm','par_all36m_prot.prm','par_np_thiol.prm','toppar_water_ions_cufix.str','par_stub_ions_nbfix.str'])+f'''cellBasisVector1 {box[0]*10} 0 0
cellBasisVector2 0 {box[1]*10} 0
cellBasisVector3 0 0 {box[2]*10}
cellOrigin {center[0]*10} {center[1]*10} {center[2]*10}
wrapAll off
wrapWater on
PME yes
PMEGridSpacing 1.5
cutoff 10
switching on
switchdist 8
pairlistdist 13.5
exclude scaled1-4
oneFourScaling 1
rigidBonds all
rigidTolerance 1e-8
timestep 2
nonbondedFreq 1
fullElectFrequency 2
stepspercycle 20
GPUresident on
langevin on
langevinTemp 300
langevinDamping 5
langevinHydrogen off
langevinPiston off
constraints on
consref {folder/'system.pdb'}
conskfile {folder/'wall.pdb'}
conskcol B
consexp 2
outputName {folder/'run'}
dcdFile {folder/'run.dcd'}
dcdFreq 5000
xstFreq 1000
restartfreq 5000
outputEnergies 1000
binaryrestart yes
temperature 0
seed 6142026
minimize 2000
reinitvels 300
run 250000
'''
 (folder/'run.conf').write_text(conf)
 print(label,meta,flush=True)
