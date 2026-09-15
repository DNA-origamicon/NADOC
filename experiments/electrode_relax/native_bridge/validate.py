"""User-authorized native force-equivalence and timing checks for the isolated bridge."""
import argparse,json,re,shutil,subprocess,time
from pathlib import Path
import numpy as np
ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,required=True);ap.add_argument('--binary',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
p=a.output.resolve();src=a.package.resolve();binary=a.binary.resolve()
shutil.copytree(src,p,ignore=shutil.ignore_patterns('output','*.log','bulk_reference'))
(p/'output').mkdir();m=json.loads((src/'manifest.json').read_text());name=m['segments'][0]['name']
for ext in ('coor','vel','xsc'):shutil.copy2(src/'output'/f'{name}.{ext}',p/f'seed.{ext}')
base=(src/f'{name}.conf').read_text()
for key,value in dict(binCoordinates='seed.coor',binVelocities='seed.vel',extendedSystem='seed.xsc',outputEnergies='100',xstFreq='100',dcdFreq='1000').items():base=re.sub(rf'(?mi)^{key}\s+[^\n]+',f'{key} {value}',base)
base=re.sub(r'(?mi)^GPUresident\s+[^\n]+\n','',base)
original=(src/'electrode_forces.tcl').read_text()
call='nadoc_native_electrode $slab_charges $slab_mobile $slab_axis $slab_coefficient $slab_low $slab_high $slab_wall_k $electrode_sites'
globals='global slab_charges slab_mobile slab_axis slab_coefficient slab_low slab_high slab_wall_k electrode_sites'
normal=original+'\nproc calcforces {} {\n'+globals+'\n'+call+'\n}\n'
(p/'bridge.tcl').write_text(normal);(p/'reference.tcl').write_text(original)
exe='/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3'
results=[]
def run(label,bridge,script,steps,resident=True):
 text=f"GPUresident {'on' if resident else 'off'}\n"+base.replace(name,label).replace('electrode_forces.tcl',script)
 text=re.sub(r'(?m)^run\s+\d+\s*$',f'run {steps}\n',text);(p/f'{label}.conf').write_text(text)
 started=time.time()
 with (p/f'{label}.log').open('w') as log:r=subprocess.run([str(binary) if bridge else exe,'+p1','+devices','0',f'{label}.conf'],cwd=p,stdout=log,stderr=subprocess.STDOUT,timeout=240)
 log=(p/f'{label}.log').read_text(errors='replace')
 assert r.returncode==0 and 'End of program' in log, f'{label} failed: inspect log'
 timings=re.findall(r'Benchmark time:.*? ([0-9.e+-]+) s/step',log)
 rec=dict(label=label,steps=steps,resident=resident,bridge=bridge,normal_exit=True,wall_seconds=time.time()-started,seconds_per_step=float(timings[-1]) if timings else None)
 results.append(rec);(p/'runs.json').write_text(json.dumps(results,indent=2)+'\n');print(rec,flush=True)
checks=[]
for axis in range(3):
 for bridge in (False,True):
  label=f"audit_{axis}_{'bridge' if bridge else 'reference'}"
  # Audit-only bounds activate wall penetration without moving any coordinates.
  setup=f'\nset slab_axis {axis}\nset slab_low {44 if axis==1 else 8}\nset slab_high {76 if axis==1 else 72}\n'
  setup+='set ref [lindex $electrode_sites 1]\nlset ref 0 [expr {[lindex $ref 0]+0.2}]\nlset ref 3 5.0\nlset electrode_sites 1 $ref\n'
  if bridge:
   script=original+setup+'proc calcforces {} {\n'+globals+'\nset r ['+call+' 1]\nset fd [open '+label+'.txt w]\nforeach v $r {puts $fd $v}\nclose $fd\n}\n'
  else:
   script=original+setup+'''
rename calcforces nadoc_original_calcforces
proc calcforces {} {
 global af ae
 rename addforce nadoc_original_addforce
 proc addforce {id f} {global af;set af($id) $f;nadoc_original_addforce $id $f}
 rename addenergy nadoc_original_addenergy
 proc addenergy {e} {global ae;set ae $e;nadoc_original_addenergy $e}
 nadoc_original_calcforces
 set fd [open AUDITPATH w]
 puts $fd $ae
 foreach id [lsort -integer [array names af]] {puts $fd "$id $af($id)"}
 close $fd
 rename addforce {}
 rename nadoc_original_addforce addforce
 rename addenergy {}
 rename nadoc_original_addenergy addenergy
}
'''.replace('AUDITPATH',label+'.txt')
  (p/f'{label}.tcl').write_text(script);run(label,bridge,label+'.tcl',0)
 ref=(p/f'audit_{axis}_reference.txt').read_text().splitlines();got=(p/f'audit_{axis}_bridge.txt').read_text().splitlines()
 rf=np.loadtxt(ref[1:]);gf=np.loadtxt(got[1:]);assert np.array_equal(rf[:,0],gf[:,0])
 delta=float(np.max(np.abs(rf[:,1:]-gf[:,1:])));energy=abs(float(ref[0])-float(got[0]))
 assert delta<1e-7 and energy<1e-7,(axis,delta,energy)
 checks.append(dict(axis=axis,atoms=len(rf),max_force_difference=delta,energy_difference=energy,wall_penetration_and_displaced_spring=True))
(p/'force_equivalence.json').write_text(json.dumps(checks,indent=2)+'\n');print('FORCE CHECKS',checks,flush=True)
for resident in (True,False):
 for bridge in (False,True):
  label=f"timing_{'resident' if resident else 'offload'}_{'bridge' if bridge else 'reference'}"
  run(label,bridge,'bridge.tcl' if bridge else 'reference.tcl',2000,resident)
run('bridge_resident_40ps',True,'bridge.tcl',20000,True)
