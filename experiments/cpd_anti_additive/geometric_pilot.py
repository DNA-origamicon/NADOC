"""Isolated geomeTRIC/Psi4 constrained pilot, bounded by actual gradient evaluations."""
import argparse,json,os,re,shutil,sys
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import source,checked,write
from backend.parameterization.photoproduct_qm import _dihedral_degrees,_circular_difference_degrees
ART=REPO/'.development-artifacts'
RUNTIME=ART/'cpd-geometric-runtime-v1'
sys.path.insert(0,str(RUNTIME))
import geometric.engine,geometric.molecule,geometric.optimize
BOHR=.529177210903


def prepare(root):
    root.mkdir(exist_ok=False);shutil.copyfile(__file__,root/'executed_source.py')
    old=json.loads((ART/'cpd-anti-relaxed-glycosidic-v7/plan.json').read_text())['records'][0]
    ref=ART/'cpd-anti-gradient-consistency-v1/reference/result.json';r=json.loads(ref.read_text());data=json.loads(checked(r['input']).read_text());checked(r['native'])
    write(root/'plan.json',dict(record=old,reference=source(ref),input=source(checked(r['input'])),elements=data['elements'],geometry_bohr=data['geometry_bohr'],method='mp2',options=dict(basis='6-31G(d)',reference='rhf',scf_type='df',mp2_type='df',freeze_core=True,e_convergence=1e-12,d_convergence=1e-12,solver_convergence=1e-10,maxiter=300),max_evaluations=40,threads=4,memory_gib=6,optimizer=dict(coordsys='tric',trust=.02,tmax=.05,enforce=.1,conmethod=1,convergence_set='GAU_TIGHT',maxiter=40),runtime_sources=[source(p) for p in sorted((RUNTIME/'geometric').glob('*.py'))],minimum_certified=False))


def screen(x,plan):
    s=np.array(plan['geometry_bohr']);r=plan['record'];graph=json.loads(checked(r['model_graph']).read_text());ns={i:[] for i in range(len(x))};ratios=[];radii={'H':.31,'C':.76,'N':.71,'O':.66}
    for bond in graph['bonds']:
        i,j=bond['indices'];ns[i].append(j);ns[j].append(i);ratios.append(float(np.linalg.norm(x[i]-x[j])*BOHR/(radii[plan['elements'][i]]+radii[plan['elements'][j]])))
    preserved=True
    for n in ns.values():
        if len(n)!=4:continue
        def vol(pos):
            a,b,c,d=pos[n];return float(np.dot(b-a,np.cross(c-a,d-a)))
        preserved &= vol(x)*vol(s)>0 and abs(vol(x))>1e-8
    error=_circular_difference_degrees(_dihedral_degrees(*x[r['torsion_indices']]),r['target_degrees'])
    return dict(passed=bool(preserved and .7<min(ratios) and max(ratios)<1.3 and (not plan.get('freeze_torsion',True) or error<.01)),torsion_error_deg=error,stereo_preserved=bool(preserved),covalent_ratio_range=[min(ratios),max(ratios)])


def run(root):
    import psi4
    os.chdir(root);plan=json.loads((root/'plan.json').read_text())
    for s in plan['runtime_sources']:checked(s)
    x=np.array(plan['geometry_bohr']);assert screen(x,plan)['passed']
    M=geometric.molecule.Molecule();M.elem=plan['elements'];M.xyzs=[x*BOHR];M.bonds=[tuple(b['indices']) for b in json.loads(checked(plan['record']['model_graph']).read_text())['bonds']];M.top_settings['read_bonds']=True;M.build_topology(force_bonds=False)
    M.write(str(root/'starting.xyz'))
    indices=plan['record']['torsion_indices'];constraint=root/'constraints.txt';constraint.write_text('$freeze\ndihedral '+' '.join(str(i+1) for i in indices)+'\n')
    scratch=Path(plan.get('scratch_dir',str(Path('/home/jojo/.cache/nadoc-qm')/root.name)));scratch.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(scratch).free<15*1024**3:raise RuntimeError('Insufficient local scratch')
    psi4.set_num_threads(plan['threads']);psi4.set_memory(f"{plan['memory_gib']} GiB");psi4.core.IOManager.shared_object().set_default_path(str(scratch));psi4.set_options(plan['options'])
    records=[]
    replay=[]
    for src in plan.get('replay_sources', []):
        rr=json.loads(checked(src).read_text());checked(rr['native'])
        replay.append((np.load(checked(rr['geometry'])),rr,src))
    class Engine(geometric.engine.Engine):
        def calc_new(self,coords,dirname):
            if len(records)>=plan['max_evaluations']:raise RuntimeError('CPD gradient evaluation budget reached')
            xyz=np.asarray(coords).reshape(-1,3);audit=screen(xyz,plan)
            if not audit['passed']:raise RuntimeError('CPD trial geometry/constraint screen failed')
            folder=root/f'evaluation-{len(records)+1:03d}';folder.mkdir(exist_ok=False)
            np.save(folder/'geometry_bohr.npy',xyz)
            matches=[(rr,src) for xx,rr,src in replay if np.max(abs(xyz-xx))<1e-10]
            reused_source=None
            if matches:
                ref,reused_source=matches[0];energy=ref['energy'];g=np.array(ref['gradient']);native=ref['native'];reused=True
            elif not records and plan.get('reference') and np.max(abs(xyz-x))<1e-10:
                ref=json.loads(checked(plan['reference']).read_text());checked(ref['input']);checked(ref['native']);energy=ref['energy'];g=np.array(ref['gradient']);native=ref['native'];reused=True
            else:
                if sum(not r['reused'] for r in records)>=plan.get('max_new_evaluations',plan['max_evaluations']):
                    raise RuntimeError('CPD new-gradient evaluation budget reached')
                psi4.set_output_file(str(folder/'output.dat'),False)
                text='\n'.join(f'{el} '+ ' '.join(f'{v:.15f}' for v in pos) for el,pos in zip(plan['elements'],xyz))
                mol=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
                grad,wfn=psi4.gradient(plan['method'],molecule=mol,return_wfn=True);energy=float(wfn.energy());g=np.array(grad);psi4.core.clean()
                native=source(folder/'output.dat');res=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',(folder/'output.dat').read_text())]
                if plan['method']=='mp2':assert res and max(res)<=1e-10
                reused=False
            assert g.shape==xyz.shape and np.isfinite(g).all() and np.isfinite(energy)
            write(folder/'result.json',dict(energy=energy,gradient=g.tolist(),geometry=source(folder/'geometry_bohr.npy'),native=native,reused=reused,reused_source=reused_source,audit=audit))
            records.append(dict(energy=energy,result=source(folder/'result.json'),reused=reused));write(root/'progress.json',dict(evaluations=records,minimum_certified=False))
            return dict(energy=energy,gradient=g.ravel())
    engine=Engine(M)
    try:
        result=geometric.optimize.run_optimizer(customengine=engine,input=str(root/'starting.xyz'),constraints=str(constraint) if plan.get('freeze_torsion',True) else None,prefix=str(root/'geometric'),**plan['optimizer'])
        final=np.array(result.xyzs[-1])/BOHR;audit=screen(final,plan);assert audit['passed'];result[-1].write(str(root/'optimized.xyz'))
        write(root/'assessment.json',dict(native_optimizer_converged=True,geometry_audit=audit,evaluations=len(records),minimum_certified=False,simulation_ready=False,scope='geomeTRIC stationarity only; no Hessian certification',freeze_torsion=plan.get('freeze_torsion',True),optimized=source(root/'optimized.xyz'),log=source(root/'geometric.log')))
    except Exception as exc:
        write(root/'assessment.json',dict(native_optimizer_converged=False,error=repr(exc),evaluations=len(records),minimum_certified=False,simulation_ready=False));raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('root',type=Path);a=p.parse_args();globals()[a.action](a.root.resolve())
