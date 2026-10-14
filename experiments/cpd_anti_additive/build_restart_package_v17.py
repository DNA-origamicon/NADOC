"""Build portable research restart inputs without modifying historical evidence."""
import hashlib,json,re,shutil
from pathlib import Path
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
REPO=Path(__file__).resolve().parents[2];ART=REPO/'.development-artifacts';ROOT=ART/'cpd-anti-gpu-cube-context-v5'
OUT=ART/'cpd-anti-restart-package-v17'
ENDPOINTS={
'anti-1':'anti/replica-1/validation-remaining-v8/segment-10',
'anti-2':'anti/replica-2/validation-remaining-v11/segment-10',
'anti-3':'anti/replica-3/validation-resume-v15/segment-10-remainder',
'control-1':'control/replica-1/validation/segment-10',
'control-2':'control/replica-2/validation-resume-v13/segment-10-remainder',
'control-3':'control/replica-3/validation/segment-10'}

def build():
 OUT.mkdir(exist_ok=False);sources=[];states={}
 def copy(src,rel):
  dest=OUT/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest);sources.append(dict(destination=rel,source=source(src)))
 for p in (ROOT/'forcefield').iterdir():
  if p.is_file():copy(p,'forcefield/'+p.name)
 for case in ['anti','control']:
  for ext in ['psf','pdb']:copy(ROOT/case/f'system.{ext}',f'systems/{case}/system.{ext}')
 for index,(key,rel) in enumerate(ENDPOINTS.items()):
  f=ROOT/rel;case=key.split('-')[0]
  a=read(f/'assessment.json');assert a['native_and_registered_geometry_passed']
  for pin in a['checkpoints']:checked(pin)
  for ext in ['coor','vel','xsc']:copy(f/f'result.restart.{ext}',f'states/{key}/state.{ext}')
  log=(f/'run.log').read_text();assert 'End of program' in log
  headers=next(l.split()[1:] for l in log.splitlines() if l.startswith('ETITLE:'))
  row=dict(zip(headers,map(float,[l for l in log.splitlines() if l.startswith('ENERGY:')][-1].split()[1:])));assert row['TS']==5530000
  states[key]=dict(step=5530000,validated_ns=10,potential_kcal=row['POTENTIAL'],declared_restart_seed=710001+index,source_checkpoint=source(f/'result.restart.xsc'))
  for mode,path in [('probe',f/'endpoint-reference/run.conf'),('continue',f/'run.conf')]:
   lines=[]
   for line in path.read_text().splitlines():
    parts=line.split(maxsplit=1);cmd=parts[0] if parts else ''
    if cmd in ['structure','coordinates']:line=f'{cmd} {{@ROOT@/systems/{case}/system.{"psf" if cmd=="structure" else "pdb"}}}'
    elif cmd=='parameters':line=f'parameters {{@ROOT@/forcefield/{Path(parts[1]).name}}}'
    elif cmd in ['binCoordinates','binVelocities','extendedSystem']:
     ext={'binCoordinates':'coor','binVelocities':'vel','extendedSystem':'xsc'}[cmd];line=f'{cmd} {{@ROOT@/states/{key}/state.{ext}}}'
    elif cmd=='firsttimestep':line='firsttimestep 5530000'
    elif cmd=='seed':line=f'seed {710001+index}'
    elif cmd=='run':line='run 0' if mode=='probe' else 'run @STEPS@'
    lines.append(line)
   text='\n'.join(lines)+'\n';assert '/media/' not in text and '/home/' not in text
   target=OUT/'templates'/f'{key}.{mode}.conf';target.parent.mkdir(exist_ok=True);target.write_text(text)
   sources.append(dict(destination=str(target.relative_to(OUT)),template_source=source(path),changes='Relocatedpaths,finalcheckpoint,first5530000,declaredfreshseed,boundedstepplaceholder; method unchanged'))
 copy(REPO/'experiments/cpd_anti_additive/portable_restart_v17.py','restart.py')
 copy(Path(__file__),'evidence/build_restart_package_v17.py')
 for name in ['assembly.json','observables_registration.json','startup_endpoints_lock_v6.json','replicate_comparison_v17.json','campaign_review_v17.json','provenance_errata_v17.json']:
  copy(ROOT/name,'evidence/'+name)
 for case in ['anti','control']:
  for rep in [1,2,3]:copy(ROOT/case/f'replica-{rep}/validation/completion_review.json',f'evidence/{case}-{rep}-completion_review.json')
 readme='''# CPD cis-anti-I research restart package

Six final10ns endpoints for the existing interstrand TT DNA context. These are
restartable research inputs, not unrestricted force-field release or certification
of an energy minimum, equilibrium, mechanics, isoform transfer or full production
readiness. See evidence/campaign_review_v17.json and provenance_errata_v17.json.
All original failures and raw trajectories remain in the source archive; source
paths/hashes here are provenance references,not runtime dependencies.

Requires Python3 and a compatible NAMD3 CUDA build/GPU. NAMD is not bundled.
The qualified source build was NAMD Git2025-12-04, fourCPU workers, GPU0.
Check hashes after relocation:

    python3 restart.py --verify-only

A static restart check (no dynamics; new output directory required):

    python3 restart.py --case anti-1 --namd /path/to/namd3 --output /path/to/new-check

Repeat for anti-2,anti-3,control-1,control-2,control-3 as needed. Default steps=0.
An explicitly chosen research continuation uses --steps500000 (write as
`--steps 500000`) for at most1ns, at2fs, with a two-hour process timeout.
There is no automatic chaining. Audit native completion,fullcell/checkpoints,
chemistry,water,image clearance>12A,pressure/density/voids,registered structure
and performance before another chunk. The runner only checks hashes,native
completion and initial energy; its passed field is NOT that scientific audit.
Preserve failures; restart from a verified complete triple in a new directory.
Do not re-run this package endpoint when intending to continue a later chunk:
create a newly pinned plan for that later checkpoint and its ENERGY row.

Full velocities and extended-system state are restored at5530000. Each case has
an explicit fresh seed; bitwise Langevin trajectory continuity is not promised.
NPT300K/1.01325bar,isotropic,PME144cubed,force-switch10–12A,ordinary masses,
2fs,H-bond constraints,100ps restarts,10ps DCD remain unchanged. No timestep,
mass,ensemble or electrostatics tuning is qualified by this package.

No long production simulation is launched or automatically authorized here.
The final ensemble exhibits replica and initial-state variability; retain all
six outcomes. Parameter assets retain original headers and provenance.
'''
 (OUT/'README.md').write_text(readme)
 save(OUT/'sources.json',dict(at=now(),files=sources))
 files={str(p.relative_to(OUT)):source(p)['sha256'] for p in sorted(OUT.rglob('*')) if p.is_file()}
 save(OUT/'manifest.json',dict(at=now(),files=files,states=states,simulation_ready=False,minimum_certified=False,scope='Portable final-state research restart package; static relocation validation reported separately'))
 print(OUT.resolve())
if __name__=='__main__':build()
