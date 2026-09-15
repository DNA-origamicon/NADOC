from pathlib import Path
import subprocess,json
root=Path(__file__).resolve().parent;p=root.parents[1]/'workspace/md_jobs/60e854232e8c/package/cube_pore_namd_solvated'
base=(root/'full_baseline_probe/cpu_probe.conf').read_text()
exe='/home/joshua/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3'
for stage in ['01_300K_NPT_ENM_k0p5_p10','04_300K_NPT_MGHH_only_p10']:
 d=root/f'full_static_{stage[:2]}';d.mkdir(exist_ok=True)
 lines=[]
 for l in base.splitlines():
  a=l.split()
  if not a:lines.append(l);continue
  k=a[0]
  if k=='binCoordinates':l=f'{k} {p/"output"/f"cube_pore_{stage}.coor"}'
  elif k=='binVelocities':l=f'{k} {p/"output"/f"cube_pore_{stage}.vel"}'
  elif k=='extendedSystem':l=f'{k} {p/"output"/f"cube_pore_{stage}.xsc"}'
  elif k in ['outputName','dcdFile','xstFile']:l=f'{k} {d/k}'
  elif k=='run':l='run 0'
  # Evaluate physical interaction virial without reference-dependent external restraints/ENM.
  elif k in ['constraints','extraBonds']:l=f'{k} off'
  lines.append(l)
 (d/'probe.conf').write_text('\n'.join(lines)+'\n')
 with (d/'probe.log').open('w') as f:
  code=subprocess.run([exe,'+p4',str(d/'probe.conf')],cwd=d,stdout=f,stderr=subprocess.STDOUT).returncode
 print(stage,code,flush=True)
