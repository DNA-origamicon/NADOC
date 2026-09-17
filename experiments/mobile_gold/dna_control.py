"""Retained local CUDA campaign; run as a module from repository root.
Uses original campaign paths; choose fresh output paths before repeating.
"""
from pathlib import Path
from dataclasses import replace
import subprocess,json,numpy as np
from backend.core.oxdna_runner import load_stage_specs
from backend.core.oxdna_protocol import render_stage_input
from backend.physics.oxdna_mobile_gold import find_mobile_gold_oxdna
from backend.core.models import Design
from backend.core.oxdna_health import run_oxdna_health_check
src=Path('experiments/mobile_gold/ws/oxdna_jobs/7c83e7c70d3c').resolve();out=Path('experiments/mobile_gold/ws/mobile_gold_dna_control').resolve();out.mkdir(exist_ok=False)
top=(src/'topology.top').read_text().splitlines();n,ns=map(int,top[0].split());top[0]=f'{n-1} {ns-1}';(out/'topology.top').write_text('\n'.join(top[:-1])+'\n')
lines=(src/'conf.dat').read_text().splitlines();rows=np.loadtxt(src/'conf.dat',skiprows=3)[:-1];rows[:,12:15]=1e-9
(out/'conf.dat').write_text('\n'.join(lines[:3])+'\n'+'\n'.join(' '.join(map(str,r)) for r in rows)+'\n');(out/'forces.txt').write_text((src/'forces.txt').read_text())
design=Design.from_json((src/'design.json').read_text());design.nanoparticles=[];design.nanoparticle_conjugations=[]
conf=out/'conf.dat';records=[]
for spec in load_stage_specs(src):
 spec=replace(spec,interaction='DNA2',gold_file=None);sd=out/spec.name;sd.mkdir()
 text=render_stage_input(spec,str(out/'topology.top'),str(conf),forces_name=str(out/'forces.txt') if spec.external_forces else None)
 text+='\nCUDA_avoid_cpu_calculations = true\nconfiguration_print_energy = false\nprint_initial_energy = false\nno_stdout_energy = true\n'
 (sd/'input').write_text(text)
 with (sd/'run.log').open('w') as log:p=subprocess.run([find_mobile_gold_oxdna(),'input'],cwd=sd,stdout=log,stderr=subprocess.STDOUT,timeout=90)
 if p.returncode:raise RuntimeError((sd/'run.log').read_text()[-1000:])
 result=run_oxdna_health_check(design,sd,kind=spec.kind,min_bp_retained=0,topology_path=out/'topology.top',dnanalysis_bin=None)
 records.append(dict(stage=spec.name,bp_retained_fraction=result.bp_retained_fraction))
 conf=sd/'last_conf.dat'
(out/'results.json').write_text(json.dumps(records,indent=2));print(records)
