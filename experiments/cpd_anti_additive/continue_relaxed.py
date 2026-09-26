"""Screened coordinate continuations; preserve the interrupted batch verbatim."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.relaxed_glycosidic import audit, PROTOCOL
from experiments.cpd_anti_additive.core_baseline import checked, source, write
from backend.parameterization.photoproduct_qm import generate_torsion_scan_job, run_psi4_job, parse_xyz, _dihedral_degrees, _circular_difference_degrees


def prepare(root, prior_root=None, tighter=False):
    old = prior_root or REPO / '.development-artifacts/cpd-anti-relaxed-glycosidic-v1'
    prior = json.loads((old / 'plan.json').read_text())
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / 'executed_source.py')
    records = []
    for r in prior['records']:
        if r['label'] == 'endpoint-1--15':
            completed = json.loads((old / r['label'] / 'geometry_audit.json').read_text())
            checked(completed['native']); checked(completed['optimized_xyz'])
            assert completed['passed']
            continue
        native = Path(r['job_dir']) / 'output.dat'
        if not native.exists():
            # Queued point never started: retain its existing native seed source.
            native = checked(r['prior_native'])
        text = native.read_text()
        # Latest printed actual evaluation geometry, never OptKing proposed coordinates.
        rows = re.findall(r'^\s*([CHNO])\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)(?:\s+[-+\d.Ee]+)?\s*$', text.rsplit('Geometry (in Angstrom)', 1)[1], re.M)
        assert len(rows) == 49
        x = np.array([[float(v) for v in row[1:]] for row in rows])
        original, _ = parse_xyz(checked(r['seed']).read_text())
        assert [row[0] for row in rows] == [a[0] for a in original]
        s = np.array([a[1:] for a in original])
        graph = json.loads(checked(r['model_graph']).read_text())
        neighbors = {i: [] for i in range(49)}
        radii = {'H': .31, 'C': .76, 'N': .71, 'O': .66}
        ratios = []
        for b in graph['bonds']:
            i, j = b['indices']; neighbors[i].append(j); neighbors[j].append(i)
            ratios.append(float(np.linalg.norm(x[i]-x[j])/(radii[rows[i][0]]+radii[rows[j][0]])))
        assert min(ratios) > .7 and max(ratios) < 1.3
        for ns in neighbors.values():
            if len(ns) != 4: continue
            def vol(pos):
                a,b,c,d=pos[ns]; return np.dot(b-a,np.cross(c-a,d-a))
            assert vol(s)*vol(x)>0 and abs(vol(x))>1e-8
        error = _circular_difference_degrees(_dihedral_degrees(*x[r['torsion_indices']]),r['target_degrees'])
        assert error < .01
        folder = root / r['label']; folder.mkdir()
        xyz = folder / 'starting.xyz'
        xyz.write_text('49\nScreened latest native evaluation geometry; fresh optimizer history\n'+'\n'.join(f'{row[0]} '+ ' '.join(row[1:]) for row in rows)+'\n')
        pp = json.loads(checked(r['scan_plan']).read_text())
        pp.update(reviewed_by='Native-coordinate graph, tetrahedral-sign and fixed-angle screen', review_rationale='Continue interrupted point from last printed evaluation geometry; preserve target, method and convergence policy; fresh optimizer history', points=[dict(id=r['label'],target_degrees=r['target_degrees'],xyz_sha256=source(xyz)['sha256'])])
        plan = folder / 'scan-plan.json'; write(plan, pp)
        job = folder / 'qm'
        generate_torsion_scan_job(scan_plan_path=plan, point_id=r['label'], xyz_path=xyz, output_dir=job, memory_gib=6, threads=4, protocol_path=PROTOCOL)
        if tighter:
            inp = job / 'input.dat'
            generated = source(inp)
            text = inp.read_text().replace('  g_convergence gau_tight', '  g_convergence gau_tight\n  e_convergence 12\n  d_convergence 12\n  cphf_r_convergence 10\n  geom_maxiter 150')
            inp.write_text(text)
            manifest_path = job / 'job_manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['input']['sha256'] = source(inp)['sha256']
            manifest['campaign_override'] = dict(generated_input=generated, e_convergence=12, d_convergence=12, cphf_r_convergence=10, geom_maxiter=150, reason='Tighten electronic noise and extend iteration budget; unchanged geometry convergence criteria')
            write(manifest_path, manifest)
        record = dict(r,job_dir=str(job),manifest=source(job/'job_manifest.json'),scan_plan=source(plan),seed=source(xyz),prior_native=source(native),input_screen=dict(torsion_error_deg=error,covalent_ratio_range=[min(ratios),max(ratios)],tetrahedral_signs_preserved=True),scratch_dir=str(Path('/home/jojo/.cache/nadoc-qm')/root.name/r['label']))
        records.append(record)
    assert len(records)==3
    write(root/'plan.json',dict(records=records,protocol=source(PROTOCOL),workers=2,simulation_ready=False,scope='Coordinate continuations only, no optimizer-history restart or harmonic certification; original completed point reused'))


def run(root):
    os.sched_setaffinity(0,set(range(16)))
    plan=json.loads((root/'plan.json').read_text());checked(plan['protocol'])
    def task(r):
        try:
            checked(r['manifest']);checked(r['prior_native'])
            if shutil.disk_usage('/home/jojo').free < 15*1024**3:
                raise RuntimeError('Insufficient local scratch headroom (15 GiB reserve)')
            result = run_psi4_job(job_dir=Path(r['job_dir']),psi4_executable=Path('/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4'),scratch_dir=Path(r['scratch_dir']))
            if result['status'] == 'failed':
                return dict(label=r['label'],state='failed',reason='Native QM execution/convergence checks failed',run_manifest=source(Path(r['job_dir'])/'run_manifest.json'))
            report=audit(r)
            return dict(label=r['label'],state='audited' if report['passed'] else 'failed_geometry_screen',audit=report)
        except Exception as exc:
            return dict(label=r['label'],state='failed',error=repr(exc))
    records=[]
    with ThreadPoolExecutor(max_workers=plan.get('workers', 2)) as pool:
        for future in as_completed([pool.submit(task,r) for r in plan['records']]):
            records.append(future.result());write(root/'progress.json',dict(records=records,total=len(plan['records'])));print(records[-1]['label'],records[-1]['state'],flush=True)
    write(root/'assessment.json',dict(records=records,simulation_ready=False))
    if any(r['state']!='audited' for r in records):raise RuntimeError('Continuation failure; preserve evidence')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('root',type=Path);a=p.parse_args();globals()[a.action](a.root.resolve())
