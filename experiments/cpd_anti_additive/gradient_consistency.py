"""Bounded local energy/gradient consistency check; not optimization or a Hessian certificate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json,os,re,shutil,subprocess,sys
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees,_circular_difference_degrees


def prepare(root, step_scale=1.0):
    old=REPO/'.development-artifacts/cpd-anti-relaxed-glycosidic-v7'
    record=json.loads((old/'plan.json').read_text())['records'][0]
    job=Path(record['job_dir']);run=json.loads((job/'run_manifest.json').read_text());checked(run['outputs']['output.dat'])
    first=job/'optimization_guard/evaluation-001.npz';second=job/'optimization_guard/evaluation-002.npz'
    a=np.load(first);b=np.load(second);x=a['geometry_bohr'];g=a['gradient'];q=(b['geometry_bohr']-x).ravel()
    indices=record['torsion_indices']
    # Project out first-order constraint normal. Finite differences deliberately
    # use a Cartesian straight line: no claim of finite-step constraint satisfaction.
    normal=np.zeros(147);eps=1e-5
    for i in range(147):
        plus=x.copy().ravel();minus=plus.copy();plus[i]+=eps;minus[i]-=eps
        ap=_dihedral_degrees(*plus.reshape(-1,3)[indices]);am=_dihedral_degrees(*minus.reshape(-1,3)[indices])
        normal[i]=((ap-am+180)%360-180)/(2*eps)
    q-=normal*np.dot(normal,q)/np.dot(normal,normal);q/=np.linalg.norm(q)
    assert abs(q@normal)<1e-8
    atoms,_=parse_xyz(checked(record['seed']).read_text());elements=[a[0] for a in atoms]
    root.mkdir(exist_ok=False);shutil.copyfile(__file__,root/'executed_source.py');cases=[]
    for label,h in [('reference',0),('plus-full',.002),('minus-full',-.002),('plus-half',.001),('minus-half',-.001)]:
        h *= step_scale
        folder=root/label;folder.mkdir();pos=x+h*q.reshape(-1,3)
        angle=_dihedral_degrees(*pos[indices]);err=_circular_difference_degrees(angle,record['target_degrees']);assert err<.01
        graph=json.loads(checked(record['model_graph']).read_text());neighbors={i:[] for i in range(49)}
        for bond in graph['bonds']:
            i,j=bond['indices'];neighbors[i].append(j);neighbors[j].append(i)
            ratio=np.linalg.norm(pos[i]-pos[j])/np.linalg.norm(x[i]-x[j]);assert .99<ratio<1.01
        for ns in neighbors.values():
            if len(ns)==4:
                def volume(z):
                    aa,bb,cc,dd=z[ns];return np.dot(bb-aa,np.cross(cc-aa,dd-aa))
                assert volume(pos)*volume(x)>0
        write(folder/'input.json',dict(elements=elements,geometry_bohr=pos.tolist(),step_bohr=h,torsion_error_deg=err))
        cases.append(dict(label=label,input=source(folder/'input.json')))
    write(root/'plan.json',dict(cases=cases,finite_steps=[.002*step_scale,.001*step_scale],direction=q.tolist(),reference_gradient=g.tolist(),reference_energy=float(a['energy']),sources=[source(first),source(second),source(job/'run_manifest.json')],electronic_options=dict(basis='6-31G(d)',reference='rhf',scf_type='df',mp2_type='df',freeze_core=True,e_convergence=1e-12,d_convergence=1e-12,solver_convergence=1e-10,maxiter=300),minimum_certified=False,scope='Local straight-line derivative consistency, tangent to frozen torsion at reference; not constrained curvature certification'))


def worker(root,label):
    import psi4
    plan=json.loads((root/'plan.json').read_text());c=next(c for c in plan['cases'] if c['label']==label);d=json.loads(checked(c['input']).read_text());folder=root/label
    assert not (folder/'output.dat').exists()
    scratch=Path('/home/jojo/.cache/nadoc-qm')/root.name/label;scratch.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(scratch).free<15*1024**3:raise RuntimeError('Scratch headroom insufficient')
    os.chdir(folder);psi4.set_num_threads(4);psi4.set_memory('6 GiB');psi4.core.IOManager.shared_object().set_default_path(str(scratch));psi4.set_output_file(str(folder/'output.dat'),False)
    text='\n'.join(f'{el} '+ ' '.join(f'{v:.15f}' for v in xyz) for el,xyz in zip(d['elements'],d['geometry_bohr']))
    mol=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient');psi4.set_options(plan['electronic_options']);grad,wfn=psi4.gradient('mp2',molecule=mol,return_wfn=True)
    g=np.asarray(grad);assert g.shape==(49,3) and np.isfinite(g).all();energy=float(wfn.energy());assert np.isfinite(energy)
    native=(folder/'output.dat').read_text();res=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)];assert res and max(res)<=1e-10
    write(folder/'result.json',dict(energy=energy,gradient=g.tolist(),response_residuals=res,input=source(folder/'input.json'),native=source(folder/'output.dat')));psi4.core.clean()


def run(root):
    os.sched_setaffinity(0,set(range(16)));plan=json.loads((root/'plan.json').read_text())
    for src in plan['sources']:checked(src)
    def task(c):
        folder=root/c['label']
        with (folder/'run.log').open('w') as log:
            p=subprocess.run([sys.executable,str(root/'executed_source.py'),'worker',str(root),'--label',c['label']],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':str(REPO)})
        return dict(label=c['label'],returncode=p.returncode)
    with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(task,plan['cases']))
    write(root/'execution.json',dict(records=records))
    if any(r['returncode'] for r in records):raise RuntimeError('Diagnostic calculation failed; preserve all outputs')
    assess(root)


def assess(root):
    plan=json.loads((root/'plan.json').read_text())
    for src in plan['sources']:checked(src)
    results={c['label']:json.loads((root/c['label']/'result.json').read_text()) for c in plan['cases']}
    if 'reuse_reference' in plan:
        results['reference']=json.loads(checked(plan['reuse_reference']).read_text())
    for r in results.values():checked(r['input']);checked(r['native'])
    ref=results['reference'];q=np.array(plan['direction']);slope=float(q@np.array(ref['gradient']).ravel());finite=[]
    for suffix,h in zip(['full','half'],plan.get('finite_steps',[.002,.001])):
        pp=results['plus-'+suffix];mm=results['minus-'+suffix];finite.append(dict(step_bohr=h,energy_derivative=(pp['energy']-mm['energy'])/(2*h),gradient_curvature=float(q@(np.array(pp['gradient'])-np.array(mm['gradient'])).ravel()/(2*h))))
    report=dict(reference_gradient_max_difference=float(abs(np.array(ref['gradient']).reshape(49,3)-np.array(plan['reference_gradient']).reshape(49,3)).max()),reference_energy_difference=ref['energy']-plan['reference_energy'],analytic_directional_derivative=slope,finite_differences=finite,minimum_certified=False,simulation_ready=False,scope=plan['scope'],sources=[source(root/c['label']/'result.json') for c in plan['cases']])
    write(root/'assessment.json',report)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','worker','assess']);p.add_argument('root',type=Path);p.add_argument('--label');a=p.parse_args();root=a.root.resolve()
    if a.action=='worker':worker(root,a.label)
    else:globals()[a.action](root)
