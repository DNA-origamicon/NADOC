"""Sequential, isolated screening of less-covered desktop operations."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/benchmarks/desktop'
BASELINE='2f3b962966b4917d9f626e486d56680306600363'


def main():
    if os.environ.get('NADOC_VALIDATION_SCOPE')!='1':
        raise SystemExit('Use scripts/validation_guard.sh')
    scratch=Path(os.environ['TMPDIR']).resolve()
    if not Path('/media/jojo/Archive').is_mount() or not scratch.is_relative_to('/media/jojo/Archive'):
        raise SystemExit('Mounted Archive TMPDIR required')
    workspace=scratch/'workspace';workspace.mkdir(exist_ok=True)
    env=dict(os.environ,NADOC_WORKSPACE=str(workspace),NADOC_DISABLE_SESSION_CACHE='1',PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1')
    commands=[('colour_surface',['node','frontend/scripts/benchmark-surface-colouring.mjs',BASELINE]),
              ('solvent_protein',['node','frontend/scripts/benchmark-solvent-proteins.mjs']),
              ('pending_connections',[sys.executable,'-m','scripts.benchmark_pending_overhang_connections','--repeats','3'])]
    sources=['frontend/src/scene/surface_renderer.js','frontend/src/scene/atomistic_renderer.js','frontend/src/scene/md_solvent_overlay.js','frontend/src/scene/protein_trace_renderer.js','backend/api/routes_connection_versions.py']
    report=dict(scope='Screening current CPU costs and existing historical controls, not new optimization gains or E2E latency.',source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},runs=[])
    for name,command in commands:
        start=time.perf_counter();print('Screening '+name,flush=True)
        try:
            r=subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True,timeout=180)
            row=dict(operation=name,command=command,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr[-5000:],wall_seconds=time.perf_counter()-start)
        except subprocess.TimeoutExpired:
            row=dict(operation=name,command=command,exit_code=None,error='180-second limit')
        report['runs'].append(row)
        (OUT/'round3_screen.json').write_text(json.dumps(report,indent=2)+'\n')
        print(name,row['exit_code'],flush=True)
    return int(any(r['exit_code']!=0 for r in report['runs']))


if __name__=='__main__':raise SystemExit(main())
