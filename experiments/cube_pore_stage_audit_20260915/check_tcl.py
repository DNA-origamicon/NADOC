"""Execute actual Tcl control flow while recording NAMD commands (no dynamics)."""
from pathlib import Path
import json, subprocess, tempfile
from backend.core.namd_graphene import graphene_pressure_conf
from backend.core.remote_resume_conf import build_resume_conf
from backend.core.md_protocols import build_remote_resume_conf
root=Path(__file__).resolve().parent
p=root.parents[1]/'workspace/md_jobs/d49d12f98a47/package/cube_pore_namd_solvated'
m=json.loads((p/'manifest.json').read_text())
records=[]
harness='''
set started 0
set calls 0
proc unknown {cmd args} {
    global started calls
    if {$cmd in {run minimize}} {set started 1; incr calls; return}
    if {$cmd in {print callback}} {return}
    if {$started} {error "NAMD initialization directive after execution: $cmd"}
}
if {[catch {source audit.conf} error]} {puts stderr $error; exit 1}
puts "execution_calls=$calls"
'''
def check(name,text,expected=0):
    with tempfile.TemporaryDirectory(prefix='nadoc-stage-tcl-') as tmp:
        d=Path(tmp);(d/'output').mkdir();(d/'audit.conf').write_text(text)
        r=subprocess.run(['tclsh'],input=harness,text=True,capture_output=True,cwd=d)
    records.append({'case':name,'exit_code':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr.strip()})
    assert r.returncode==expected,records[-1]
for f in sorted(p.glob('*.conf')):
    text=f.read_text();is_min='NADOC_ADAPTIVE_MIN_BEGIN' in text
    check('original/'+f.name,text,1 if is_min else 0)
    if is_min:check('corrected/'+f.name,graphene_pressure_conf(text,enabled=True,wall=m['graphene_nanopore']))
for s in m['segments']:
    text=(p/(s['name']+'.conf')).read_text()
    for step in [5000,s['steps']-20]:
        check(f"alpine/{s['name']}/{step}",build_resume_conf(text,s['name'],step,s['steps']))
        check(f"continuation/{s['name']}/{step}",build_remote_resume_conf(text,segment_name=s['name'],restart_step=step,total_steps=s['steps']))
(root/'tcl.json').write_text(json.dumps(records,indent=2)+'\n')
print('Verified',len(records),'Tcl executions; only original minimization has a late initialization directive.')
