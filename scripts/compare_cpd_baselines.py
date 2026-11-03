"""Compare existing 2hb_1xT production windows against the saved CPD audit."""
import json
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.distances import minimize_vectors
from backend.core.md_shell_reprep import read_namd_coor
from backend.core.cpd_metrics import make_whole_dna
from scripts.analyze_cpd_production import rmsd,stats
OUT=Path('docs/audits/cpd_production_20ns_20261019')

def identity(a):return (a.segid,int(a.resid),a.name)

def main():
    cp=Path('workspace/md_jobs/e345c67349bf');cj=json.loads((cp/'job.json').read_text());cp/=cj['package_subdir'];cm=json.loads((cp/'manifest.json').read_text());cu=mda.Universe(str(cp/cm['files']['topology']))
    wp=json.loads((cp/'nadoc_wc_plan.json').read_text());pairs=wp['pairs'];thresholds=np.array([v+.75 for w in pairs for v in w['ref_distances']]);cuts=np.cumsum([0]+[len(w['atom_pairs']) for w in pairs]);atom_pairs=[(identity(cu.atoms[a]),identity(cu.atoms[b])) for w in pairs for a,b in w['atom_pairs']]
    ends=[('D001',15),('D000',8)]
    ids=[identity(a) for a in cu.select_atoms('segid D* and not name H*')]
    all_results=[]
    for jid in ['bd13e4dfa6c5','07d7cd2766e3','29c5b267380f']:
        jd=Path('/media/jojo/Archive/NADOC_archive')/jid;j=json.loads((jd/'job.json').read_text());p=jd/j['package_subdir'];m=json.loads((p/'manifest.json').read_text());seg=j['segments'][0]['name'];conf=(p/(seg+'.conf')).read_text();direct={l.split()[0].lower():l.split()[1] for l in conf.splitlines() if len(l.split())>=2 and not l.startswith('#')}
        u=mda.Universe(str(p/direct['structure']),str(p/'output'/(seg+'.dcd')));ix={identity(a):a.index for a in u.atoms};assert all(k in ix for k in ids)
        # Atom identity and base sequence must match, not merely index counts.
        assert all(u.atoms[ix[identity(a)]].resname==a.resname for a in cu.select_atoms('segid D*'))
        di=np.array([ix[k] for k in ids]);li=np.array([ix[k] for k in ids if any(k[0]==s and abs(k[1]-r)<=1 for s,r in ends)]);flat=np.array([(ix[a],ix[b]) for a,b in atom_pairs]);localset=set(li);localpairs=[i for i,w in enumerate(pairs) if any(ix[a] in localset or ix[b] in localset for a,b in atom_pairs[cuts[i]:cuts[i+1]])]
        dna=u.select_atoms('segid D*');frags=dna.fragments;start=read_namd_coor(p/direct['bincoordinates']);u.atoms.positions=start
        wrapped=direct.get('wrapall','off').lower()=='on'
        if wrapped:make_whole_dna(dna,frags,u.dimensions[:3])
        start=u.atoms.positions.copy();trace=[];flags=[]
        for ts in u.trajectory:
            t=round(ts.time/1000,6)
            if t>20:break
            if t<=0:continue
            if wrapped:make_whole_dna(dna,frags,ts.dimensions[:3])
            x=ts.positions;dist=np.linalg.norm(minimize_vectors(x[flat[:,0]]-x[flat[:,1]],ts.dimensions),axis=1);ok=np.array([np.all(dist[cuts[i]:cuts[i+1]]<=thresholds[cuts[i]:cuts[i+1]]) for i in range(len(pairs))]);flags.append(ok)
            trace.append([t,rmsd(x[li],start[li]),rmsd(x[di],start[di]),ok.mean(),ok[localpairs].mean()])
        a=np.array(trace);f=np.array(flags);names=['time_ns','local_heavy_rmsd_A','dna_heavy_rmsd_A','wc_fraction','local_wc_fraction'];assert abs(a[-1,0]-20)<.021
        blocks=[]
        for lo,hi in [(0,5),(5,10),(10,15),(15,20)]:
            take=(a[:,0]>lo)&(a[:,0]<=hi);blocks.append({'time_ns':[lo,hi],**{n:stats(a[take,i]) for i,n in enumerate(names) if i}})
        result={'job_id':jid,'parent_job':j['parent_job_id'],'design_name':j['design_name'],'frames':len(a),'time_ns':[float(a[0,0]),float(a[-1,0])],'native_spacing_ps':float(u.trajectory.dt),'shared_heavy_atoms':len(di),'local_heavy_atoms':len(li),'common_wc_pairs':len(pairs),'local_wc_pairs':len(localpairs),'coordinate_unwrapping_applied':wrapped,'parameters':{k:direct.get(k) for k in ['timestep','rigidbonds','structure','langevindamping','constraints','extrabondsfile','wrapall']},'atoms':len(u.atoms),'initial_config_box_A':[[float(v) for v in next(l for l in conf.splitlines() if l.startswith('cellBasisVector'+str(i))).split()[1:]] for i in [1,2,3]],'statistics':{n:stats(a[:,i]) for i,n in enumerate(names) if i},'blocks':blocks,'pair_occupancy':[{'a':p['res_a'],'b':p['res_b'],'local':i in localpairs,'occupancy':float(f[:,i].mean()),'last5ns':float(f[a[:,0]>15,i].mean())} for i,p in enumerate(pairs)]}
        (OUT/f'baseline_{jid}.json').write_text(json.dumps(result,indent=2)+'\n');np.savetxt(OUT/f'baseline_{jid}_trace.csv',a,delimiter=',',header=','.join(names),comments='');all_results.append(result);print(jid,result['statistics'],flush=True)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(2,2,figsize=(12,8),sharex=True)
    for jid,label,color in [('edb512c46112','CPD cis-syn-I','tab:blue'),('e345c67349bf','CPD cis-anti-I','tab:red'),('baseline_bd13e4dfa6c5','Baseline replica A','0.35'),('baseline_07d7cd2766e3','Baseline replica B','tab:green'),('baseline_29c5b267380f','Older baseline (small box)','tab:purple')]:
        a=np.genfromtxt(OUT/f'{jid}_trace.csv',delimiter=',',names=True)
        for ax,key,title in zip(axs.flat,['dna_heavy_rmsd_A','local_heavy_rmsd_A','wc_fraction','local_wc_fraction'],['Whole-DNA aligned RMSD (Å)','Six-residue aligned RMSD (Å)','All 42 reference base pairs','Four flanking reference base pairs']):
            # Nonoverlapping 1 ns means, keeping raw values in CSV.
            times=np.round(a['time_ns'],6);means=[a[key][(times>lo)&(times<=lo+1)].mean() for lo in range(20)]
            ax.plot(np.arange(20)+.5,means,label=label,color=color);ax.set_title(title);ax.set_xlabel('Time in production job (ns)');ax.grid(alpha=.2)
    axs[0,0].legend(fontsize=7);axs[1,0].set_ylabel('Paired fraction');axs[1,1].set_ylabel('Paired fraction');fig.tight_layout();fig.savefig(OUT/'baseline_comparison.png',dpi=160)
if __name__=='__main__':main()
