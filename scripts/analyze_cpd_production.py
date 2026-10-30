"""Read-only saved-frame CPD production audit; write compact results and plots."""
import argparse, json, hashlib
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.distances import minimize_vectors, distance_array
from backend.core.cpd_forcefield import packaged_photoproduct_manifest
from backend.core.photoproduct_chemistry import load_chemical_definition, audit_product_chirality
from backend.core.namd_topology import charmm_atom_name
from backend.core.md_shell_reprep import read_namd_coor


def stats(x):
    x=np.asarray(x);return dict(min=float(x.min()),mean=float(x.mean()),max=float(x.max()),p05=float(np.percentile(x,5)),p95=float(np.percentile(x,95)))

def rmsd(x,y):
    x=x-x.mean(0);y=y-y.mean(0);u,s,v=np.linalg.svd(x.T@y);r=u@np.diag([1,1,np.linalg.det(u@v)])@v
    return float(np.sqrt(np.mean(np.sum((x@r-y)**2,axis=1))))

def analyze(jid, out):
    jd=Path('workspace/md_jobs')/jid;job=json.loads((jd/'job.json').read_text());pkg=jd/job['package_subdir']
    assert job['status']=='completed';seg=job['segments'][0]['name'];dcd=pkg/'output'/f'{seg}.dcd'
    manifest=json.loads((pkg/'manifest.json').read_text());prod=packaged_photoproduct_manifest(pkg)
    lesion=prod['lesions'][0];definition=load_chemical_definition(lesion['product'],lesion['stereochemistry'])
    patch=prod['topology_and_placement_audits']['photoproduct_patch_audit']['patches'][0]
    ends={e['endpoint']:(e['segid'],int(e['resid'])) for e in patch['endpoints']}
    psf=pkg/manifest['files']['topology'];u=mda.Universe(str(psf),str(dcd))
    idx={(a.segid,int(a.resid),a.name):a.index for a in u.atoms}
    def ref(r):
        n,name=r.split(':');return idx[(*ends[int(n)],charmm_atom_name(name))]
    cross=np.array([[ref(b['atom_1']),ref(b['atom_2'])] for b in definition['graph_delta']['bonds_added']])
    bonds=u.bonds.indices; bondset={frozenset(b) for b in bonds};assert all(frozenset(b) in bondset for b in cross)
    core_refs=sorted({r for c in definition['product_stereocenters'] for r in [c['atom'],*c['signed_volume_reference_atoms']]});ci=np.array([ref(r) for r in core_refs])
    dna=u.select_atoms('segid D* and not name H*');di=dna.indices
    local=u.atoms[[a.index for a in dna if any(a.segid==s and abs(int(a.resid)-n)<=1 for s,n in ends.values())]];li=local.indices
    lesion_idx={a.index for a in dna if (a.segid,int(a.resid)) in ends.values()}
    lb=np.array([b for b in bonds if any(int(i) in lesion_idx for i in b) and all(u.atoms[i].mass>2 for i in b)])
    adj={int(i):set() for b in bonds for i in b}
    for a,b in bonds: adj[int(a)].add(int(b));adj[int(b)].add(int(a))
    lx=np.array(sorted(lesion_idx));exclude=np.zeros((len(lx),len(di)),bool)
    for row,a in enumerate(lx):
        near={int(a)}|adj[int(a)]
        for b in adj[int(a)]:near|=adj[b]
        exclude[row]=np.isin(di,list(near))
    wp=json.loads((pkg/'nadoc_wc_plan.json').read_text());pairs=wp['pairs'];flat=np.array([p for w in pairs for p in w['atom_pairs']]);limits=np.array([v+.75 for w in pairs for v in w['ref_distances']]);cuts=np.cumsum([0]+[len(w['atom_pairs']) for w in pairs]);locset=set(li)
    localpair=[i for i,w in enumerate(pairs) if any(a in locset or b in locset for a,b in w['atom_pairs'])]
    start=read_namd_coor(pkg/'output'/f"{job['name_stem']}_00_reseed.coor")
    trace=[];pair_flags=[];bad=[]
    for ts in u.trajectory:
        xyz=ts.positions; box=ts.dimensions
        # Place the tiny stereocenter core in a single periodic image.
        c=xyz[ci[0]]+minimize_vectors(xyz[ci]-xyz[ci[0]],box)
        chir=audit_product_chirality(definition,dict(zip(core_refs,c)))
        if not chir['passed']:bad.append(int(ts.frame))
        dist=lambda ij:np.linalg.norm(minimize_vectors(xyz[ij[:,0]]-xyz[ij[:,1]],box),axis=1)
        cd=dist(cross);bd=dist(lb);wd=dist(flat);ok=np.array([np.all(wd[cuts[i]:cuts[i+1]]<=limits[cuts[i]:cuts[i+1]]) for i in range(len(pairs))]);pair_flags.append(ok)
        dm=distance_array(xyz[lx],xyz[di],box=box);dm[exclude]=np.inf
        trace.append([ts.time/1000,*cd,*[v['signed_volume'] for v in chir['centers']],rmsd(xyz[li],start[li]),rmsd(xyz[di],start[di]),ok.mean(),ok[localpair].mean(),bd.min(),bd.max(),dm.min(),float(np.isfinite(xyz).all())])
    arr=np.array(trace);flags=np.array(pair_flags);names=['time_ns','crosslink_1_A','crosslink_2_A']+[f'volume_{c["atom"]}_A3' for c in definition['product_stereocenters']]+['local_heavy_rmsd_A','dna_heavy_rmsd_A','wc_fraction','local_wc_fraction','lesion_bond_min_A','lesion_bond_max_A','lesion_nonbonded_min_A','all_coordinates_finite']
    np.savetxt(out/f'{jid}_trace.csv',arr,delimiter=',',header=','.join(names),comments='')
    energy=[];header=[];log=(pkg/f'{seg}.log').read_text()
    for line in log.splitlines():
        if line.startswith('ETITLE:'):header=line.split()[1:]
        elif line.startswith('ENERGY:'):energy.append(dict(zip(header,map(float,line.split()[1:]))))
    conf=(pkg/f'{seg}.conf').read_text();extras=(pkg/'mgh_extrabonds.txt').read_text().splitlines();extra_dna=[]
    for line in extras:
        t=line.split()
        if t and t[0]=='bond' and any(int(x) in set(di) for x in t[1:3]):extra_dna.append(line)
    blocks=[]
    for lo,hi in [(0,5),(5,10),(10,15),(15,20.01)]:
        take=(arr[:,0]>lo)&(arr[:,0]<=hi);blocks.append({'time_ns':[lo,min(hi,20)],**{n:stats(arr[take,i]) for i,n in enumerate(names) if i and n!='all_coordinates_finite'}})
    result={'job_id':jid,'isomer':lesion['stereochemistry'],'parent_job':job['parent_job_id'],'frames':len(arr),'first_last_time_ns':[float(arr[0,0]),float(arr[-1,0])],'saved_frame_spacing_ns':float(np.median(np.diff(arr[:,0]))),'psf_sha256':hashlib.sha256(psf.read_bytes()).hexdigest(),'assets_verified':len(prod['assets']),'endpoints':ends,'crosslink_atoms':[[str(u.atoms[i]) for i in b] for b in cross],'chirality_failed_frames':bad,'all_coordinates_finite':bool(arr[:,-1].all()),'statistics':{n:stats(arr[:,i]) for i,n in enumerate(names) if i and n!='all_coordinates_finite'},'blocks':blocks,'wc_pairs':len(pairs),'local_wc_pairs':len(localpair),'pair_occupancy':[{'a':p['res_a'],'b':p['res_b'],'local':i in localpair,'occupancy':float(flags[:,i].mean()),'last5ns':float(flags[arr[:,0]>15,i].mean())} for i,p in enumerate(pairs)],'normal_namd_exit':'End of program' in log,'energy_last_step':energy[-1]['TS'],'energy_statistics':{k:stats([e[k] for e in energy]) for k in ['TEMP','POTENTIAL','TOTAL','GPRESSURE','VOLUME']},'dna_extra_restraints':extra_dna,'config':{'timestep_fs':prod['timestep_fs'],'hmr':prod['hmr_4fs_enabled'],'constraints_off':'constraints        off' in conf},'limitations':['Saved frames only; no claim about unsaved transients.','WC distances are reference-relative proxies, not an angular hydrogen-bond analysis.','RMSD uses unwrapped stored coordinates (wrapAll off), independent rigid alignment to production start.','One replica per isomer; no matched undamaged control; no thermodynamic or photochemical validation.']}
    (out/f'{jid}.json').write_text(json.dumps(result,indent=2)+'\n');print(jid,lesion['stereochemistry'],len(arr),'frames',flush=True)
    return result,arr,names

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('jobs',nargs='+');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    results=[analyze(j,args.output) for j in args.jobs]
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(3,2,figsize=(12,9),sharex=True)
    for col,(r,a,n) in enumerate(results):
        for key in ['crosslink_1_A','crosslink_2_A']:ax[0,col].plot(a[:,0],a[:,n.index(key)],label=key,lw=.7)
        for key in ['local_heavy_rmsd_A','dna_heavy_rmsd_A']:ax[1,col].plot(a[:,0],a[:,n.index(key)],label=key,lw=.7)
        for key in ['wc_fraction','local_wc_fraction']:ax[2,col].plot(a[:,0],a[:,n.index(key)],label=key,lw=.7)
        ax[0,col].set_title(r['isomer']);ax[2,col].set_xlabel('Production time (ns)')
        for row,label in enumerate(['Crosslink length (Å)','Aligned RMSD (Å)','Reference WC fraction']):ax[row,col].set_ylabel(label);ax[row,col].legend(fontsize=7)
    fig.tight_layout();fig.savefig(args.output/'production_review.png',dpi=160)
