from pathlib import Path
import re,json
root=Path(__file__).resolve().parent
p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated'
out=root/'full_baseline_probe';out.mkdir(exist_ok=True)
s=(p/'cube_pore_01_300K_NPT_ENM_k0p5_p10.conf').read_text()
# All input paths resolve to immutable source files; all outputs stay in this experiment.
inputs={'structure','coordinates','consref','conskfile','parameters','extraBondsFile','binCoordinates','binVelocities','extendedSystem'}
outputs={'outputName':'probe','dcdFile':'probe.dcd','xstFile':'probe.xst'}
lines=[]
for line in s.splitlines():
 a=line.split()
 if a:
  if a[0] in inputs:line=f'{a[0]} {p/a[1]}'
  elif a[0] in outputs:line=f'{a[0]} {out/outputs[a[0]]}'
  elif a[0]=='run':line='run 2000'
  elif a[0] in ['outputEnergies','xstFreq','dcdFreq','restartfreq']:line=f'{a[0]} 500'
 lines.append(line)
(out/'probe.conf').write_text('\n'.join(lines)+'\n')
(root/'provenance.json').write_text(json.dumps({'source_job':'60e854232e8c','production_job':'a4cb52583c26','purpose':'Isolated cavity cause investigation. No application or existing job changes.','baseline':'Parent stage 01 from minimized coordinates and original velocities; same field-free physics, reduced run/output cadence.'},indent=2)+'\n')
