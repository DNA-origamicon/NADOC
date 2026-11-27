"""Read-only ion analysis; distances from DNA heavy-atom centers with periodic boundaries.
No authored molecular structures. Run with .venv/bin/python this_file.
"""
import json, hashlib, warnings, sys
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.formats.libdcd import DCDFile
from MDAnalysis.lib.distances import distance_array
from scipy.spatial import cKDTree
from scipy.stats import qmc, spearmanr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore',category=DeprecationWarning)
O=Path(__file__).resolve().parent; ROOT=O.parent
meta=json.loads((ROOT/'2bc15e9e2531/summary.json').read_text()); pkg=Path(meta['package']); fm=meta['files'][0]; dcd=Path(fm['path']); psf=pkg/fm['config']['structure']
u=mda.Universe(str(psf)); dna=u.select_atoms('segid D*'); heavy=dna.select_atoms('not name H*'); mg=u.select_atoms('resname MGH and name MG'); cl=u.select_atoms('resname CLA'); ions=mg+cl
assert len(mg)==66 and len(cl)==39 and np.isclose(dna.charges.sum(),-93,atol=1e-4)
assert np.isclose(u.atoms.charges.sum(),0,atol=.001)
sel=np.r_[heavy.indices,ions.indices].astype(np.int64); nh=len(heavy); nm=len(mg); nq=len(ions)
reskeys=[(r.segid,int(r.resid),r.resname) for r in heavy.residues]; resmap={k[:2]:i for i,k in enumerate(reskeys)}; atomres=np.array([resmap[(a.segid,int(a.resid))] for a in heavy]); nr=len(reskeys)
local=np.array([i for i,a in enumerate(heavy) if (a.segid=='D000' and 7<=a.resid<=9) or (a.segid=='D001' and 14<=a.resid<=16)])
# Nested screening shells and nonoverlapping density shells, in Angstrom.
radii=np.array([5.,8.,10.,12.,15.,20.,25.,30.,40.,60.,200.]); edges=np.r_[np.arange(0,65,5),200.]
qpoints=qmc.Sobol(3,scramble=True,seed=20261112).random_base2(15)
raw=DCDFile(str(dcd)); n=len(raw); assert n==10000
nearest=np.empty((n,nq),np.float32); localdist=np.empty((n,nm),np.float32); counts=np.empty((n,len(radii),2),np.int16); volumes=[]; hist=[]; frames=[]; boxvol=[]
resocc=np.zeros((nr,nm),np.int32); rescounts=np.zeros(nr,np.int64); resany=np.zeros(nr,np.int64); verify=[]; before=dcd.stat(); charge=np.r_[np.full(nm,2.),-np.ones(len(cl))]
# Store residue-Mg contact bits for later residence analysis (10k*98*66 ~65 MB bool).
rescontact=np.empty((n,nr,nm),bool)
for lo in range(0,n,100):
 chunk=raw.readframes(start=lo,stop=min(n,lo+100),indices=sel); boxes=chunk.unitcell[:,[0,2,5]]
 assert np.all(np.isclose(chunk.unitcell[:,[1,3,4]],0)|np.isclose(chunk.unitcell[:,[1,3,4]],90))
 for j,(xx,box) in enumerate(zip(chunk.xyz,boxes)):
  f=lo+j; x=np.asarray(xx,dtype=float)%box; tree=cKDTree(x[:nh],boxsize=box); ion=x[nh:]; dist=tree.query(ion)[0]; nearest[f]=dist; localdist[f]=cKDTree(x[local],boxsize=box).query(ion[:nm])[0]
  counts[f,:,0]=(dist[:nm,None]<=radii).sum(0); counts[f,:,1]=(dist[nm:,None]<=radii).sum(0); boxvol.append(np.prod(box))
  hits=tree.query_ball_point(ion[:nm],8.); contacts=np.zeros((nr,nm),bool)
  for k,aa in enumerate(hits): contacts[np.unique(atomres[aa]),k]=True
  rescontact[f]=contacts; resocc+=contacts; rescounts+=contacts.sum(1); resany+=contacts.any(1)
  if f%25==0:
   vd=tree.query(qpoints*box)[0]; volumes.append(np.histogram(vd,edges)[0]/len(vd)*np.prod(box)); hist.append(np.stack([np.histogram(dist[:nm],edges)[0],np.histogram(dist[nm:],edges)[0]],axis=-1));frames.append(f)
  if f in [0,2499,4999,7499,9999]:
   independent=distance_array(ion,x[:nh],box=np.r_[box,[90,90,90]]).min(1); err=float(abs(independent-dist).max()); assert err<2e-5;verify.append({'frame':f,'max_distance_error_A':err})
 if lo%1000==0: print('frames',lo+100,'/',n,flush=True)
raw.close(); assert (before.st_size,before.st_mtime_ns)==(dcd.stat().st_size,dcd.stat().st_mtime_ns)
time=fm['first_ns']+np.arange(n)*fm['dt_ns']; dt=fm['dt_ns']; volumes=np.array(volumes);hist=np.array(hist);frames=np.array(frames);boxvol=np.array(boxvol)
net=-93+2*counts[:,:,0]-counts[:,:,1]; compensation=(net+93)/93
np.savez_compressed(O/'timeseries.npz',time_ns=time,radii_A=radii,nearest_ion_DNA_A=nearest,local_Mg_distance_A=localdist,counts=counts,net_charge_e=net,box_volume_A3=boxvol,density_edges_A=edges,density_sample_frames=frames,shell_volume_A3=volumes,shell_counts=hist,residue_Mg_contact_8A=rescontact,residue_keys=np.array(reskeys,dtype=str))
def stats(z):
 z=np.asarray(z);return {'mean':float(z.mean()),'sd':float(z.std()),'quarter_means':[float(a.mean()) for a in np.array_split(z,4)],'late_50_200ns_mean':float(z[2500:].mean())}
# Residence is consecutive SAVED-frame contact, with no gap allowance; edge intervals censored.
def runs(b):
 out=[]
 for k in range(b.shape[1]):
  v=np.r_[False,b[:,k],False].astype(int); starts=np.where(np.diff(v)==1)[0];ends=np.where(np.diff(v)==-1)[0]
  for a,e in zip(starts,ends):out.append((k,a,e,(e-a)*dt,a==0 or e==n))
 return out
residence={}
for label,b in [('DNA_8A',nearest[:,:nm]<=8),('DNA_12A',nearest[:,:nm]<=12),('DNA_20A',nearest[:,:nm]<=20),('target_neighborhood_8A',localdist<=8)]:
 rr=runs(b); complete=[r[3] for r in rr if not r[4]];residence[label]={'unique_Mg_ever':int(b.any(0).sum()),'Mg_present_every_saved_frame':int(b.all(0).sum()),'mean_count':float(b.sum(1).mean()),'longest_observed_interval_ns':float(max(r[3] for r in rr)) if rr else 0,'intervals':len(rr),'censored_intervals':int(sum(r[4] for r in rr)),'uncensored_median_ns':float(np.median(complete)) if complete else None,'uncensored_p95_ns':float(np.percentile(complete,95)) if complete else None}
 np.savetxt(O/(label+'_residence.csv'),np.array(rr),delimiter=',',header='Mg_index,start_frame,end_frame_exclusive,observed_duration_ns,edge_censored',comments='')
# Per-residue contact is not exclusive; one Mg can contact multiple residues.
with (O/'residue_occupancy.csv').open('w') as fh:
 fh.write('segid,resid,resname,p_any_Mg_8A,mean_Mg_8A,unique_Mg_8A,top_Mg_index,top_Mg_occupancy\n')
 for i,k in enumerate(reskeys):fh.write(','.join(map(str,[*k,resany[i]/n,rescounts[i]/n,int((resocc[i]>0).sum()),int(resocc[i].argmax()),resocc[i].max()/n]))+'\n')
# Density denominator is periodic geometrical shell volume, not spherical 4*pi*r^2dr.
# It does not remove water or impose an ion-specific steric radius; first shell is not a free concentration.
factor=1e30/6.02214076e23; density=hist.sum(0)/volumes.sum(0)[:,None]*factor
quarter_density=np.array([hist[g].sum(0)/volumes[g].sum(0)[:,None]*factor for g in np.array_split(np.arange(len(frames)),4)])
np.savetxt(O/'density.csv',np.c_[edges[:-1],edges[1:],volumes.mean(0),density],delimiter=',',header='lower_A,upper_A,mean_shell_volume_A3,Mg_mM,Cl_mM',comments='')
# Same-frame correlations on preexisting 0.1 ns geometry sampling; no independent-frame p values.
geo=np.genfromtxt(ROOT/'2bc15e9e2531_trace.csv',delimiter=',',names=True); ix=np.rint((geo['time_ns']-time[0])/dt).astype(int);assert abs(time[ix]-geo['time_ns']).max()<1e-4
corr={}; loccount=(localdist<=8).sum(1)
for name in ['helix_tilt_deg','helix_centroid_sep_A','d_mid_A','old_reference_local_wc_fraction']:
 corr[name]={'spearman_full':float(spearmanr(loccount[ix],geo[name]).statistic),'spearman_late':float(spearmanr(loccount[ix][ix>=2500],geo[name][ix>=2500]).statistic),'quarter_spearman':[float(spearmanr(loccount[ix][g],geo[name][g]).statistic) for g in np.array_split(np.arange(len(ix)),4)]}
kz=np.load(ROOT/'kimmdy/timeseries.npz');ki=list(kz['pair_ids']).index('D000:8~D001:15');assert np.allclose(kz['times_ps']/1000,time,atol=1e-5)
score=kz['upstream_propensity'][ki]
corr['intended_KIMMDY_upstream_propensity']={'spearman_full':float(spearmanr(loccount,score).statistic),'spearman_late':float(spearmanr(loccount[2500:],score[2500:]).statistic),'quarter_spearman':[float(spearmanr(loccount[g],score[g]).statistic) for g in np.array_split(np.arange(n),4)]}
summary={'job_id':'2bc15e9e2531','source_dcd':str(dcd),'source_psf_sha256':hashlib.sha256(psf.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256((O/'analyze.py').read_bytes()).hexdigest(),'source_unchanged':True,'frames':n,'time_ns':[float(time[0]),float(time[-1])],'dt_ns':dt,'inventory':{'DNA_charge_e':float(dna.charges.sum()),'Mg':nm,'Cl':len(cl),'total_charge_e':float(u.atoms.charges.sum())},'screening':{str(r):{'Mg':stats(counts[:,i,0]),'Cl':stats(counts[:,i,1]),'net_DNA_plus_ions_e':stats(net[:,i]),'compensation_fraction':stats(compensation[:,i])} for i,r in enumerate(radii)},'residence':residence,'target_neighborhood_Mg8A':stats(loccount),'correlations':corr,'distance_verification':verify,'density':{'edges_A':edges.tolist(),'Mg_Cl_mM':density.tolist(),'quarter_Mg_Cl_mM':quarter_density.tolist(),'shell_volume_fraction':(volumes.sum(0)/boxvol[frames].sum()).tolist(),'sample_frames':len(frames),'quasi_MC_points_per_frame':len(qpoints)},'definitions':['Distances are minimum-image distances to nearest DNA heavy-atom center, not van der Waals surface.','Screening charge = all DNA charge (-93e) + 2*Mg centers within r - Cl within r; excludes solvent polarization and Mg hydration-shell partial charges.','Target neighborhood: D000 residues 7-9 and D001 residues 14-16 heavy atoms; no inferred topology.','8A contacts are hydrated-Mg proximity, not evidence of direct coordination.','Residence intervals resolve 20ps snapshots; edge intervals are censored, not binding lifetimes.','Density uses periodic union-of-shell geometric volume by scrambled Sobol integration, 0.5 ns frame spacing. No ion-specific steric-volume correction.','Single trajectory: no causal box/salt comparison; correlations are descriptive and autocorrelated.']}
# Far-field diagnostic using pooled >=20A and >=25A volumes, matched sampled frames.
summary['far_field']={}
for cutoff in [15,20,25,30]:
 mask=edges[:-1]>=cutoff; vv=volumes[:,mask].sum(1);hh=hist[:,mask].sum(1); dd=hh.sum(0)/vv.sum()*factor
 summary['far_field'][str(cutoff)]={'volume_fraction':float(vv.sum()/boxvol[frames].sum()),'Mg_Cl_mM':dd.tolist(),'quarter_Mg_Cl_mM':[(hh[g].sum(0)/vv[g].sum()*factor).tolist() for g in np.array_split(np.arange(len(frames)),4)],'mean_Mg_Cl_count':hh.mean(0).tolist()}
assert np.all(net[:,-1]==0); assert np.all(counts[:,-1,0]==nm); assert np.all(counts[:,-1,1]==len(cl));assert np.all(hist.sum(1)==[nm,len(cl)])
(O/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
fig,ax=plt.subplots(2,2,figsize=(12,8)); mid=(edges[:-2]+edges[1:-1])/20
for k,l in enumerate(['Mg','Cl']):
 ax[0,0].plot(mid,density[:-1,k],'o-',label=l)
 ax[0,0].fill_between(mid,quarter_density[:,:-1,k].min(0),quarter_density[:,:-1,k].max(0),alpha=.18)
ax[0,0].set(xlabel='Distance to nearest DNA heavy atom (nm)',ylabel='Geometric shell concentration (mM)',ylim=(1,700),yscale='log');ax[0,0].legend();ax[0,0].set_title('Shading: range of four 50 ns blocks')
for r in [8,12,20,25]:
 ii=list(radii).index(r); zz=net[:,ii].reshape(100,100).mean(1);ax[0,1].plot(time.reshape(100,100).mean(1),zz,label=f'{r/10:g} nm')
ax[0,1].axhline(0,color='k',lw=.6);ax[0,1].set(xlabel='Time (ns)',ylabel='DNA + enclosed ion charge (e)');ax[0,1].legend()
ax[1,0].plot(time.reshape(100,100).mean(1),loccount.reshape(100,100).mean(1));ax[1,0].set(xlabel='Time (ns)',ylabel='Mg within 0.8 nm of target neighborhood')
for i,k in enumerate(reskeys):ax[1,1].scatter(i,resany[i]/n,s=12,color='C0' if k[0]=='D000' else 'C1' if k[0]=='D001' else 'C2')
ax[1,1].set(xlabel='Residue index (D000, D001, D002)',ylabel='Fraction with Mg within 0.8 nm',ylim=(0,1.02))
fig.tight_layout();fig.savefig(O/'screening_occupancy.png',dpi=160);plt.close(fig)
print(json.dumps({'far_field':summary['far_field'],'residence':residence,'correlations':corr},indent=2),flush=True)
