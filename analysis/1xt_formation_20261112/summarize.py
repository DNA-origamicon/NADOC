import sys,json,csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_isomer_formation.geometry import eligible,features
from additional_shape import summary
O=Path(__file__).resolve().parent
A=json.loads((O/'classifier_audit.json').read_text()); products=A['products'];grid=A['grid']
def episodes(mask,t,dt,gap=0):
 ix=np.flatnonzero(mask)
 if not len(ix):return dict(count=0,longest_observed_span_ns=0)
 groups=np.split(ix,np.flatnonzero(np.diff(t[ix])>dt*1.01+gap)+1)
 return dict(count=len(groups),longest_observed_span_ns=float(max(t[g[-1]]-t[g[0]] for g in groups)))
def summarize():
 results=[];rows=[];competitors=[];blocks=[];events=[]
 inv=json.loads((O/'inventory.json').read_text());fig,axs=plt.subplots(sum(x['production'] for x in inv),2,figsize=(14,24),squeeze=False);axn=0
 for rec in inv:
  p=O/rec['job_id'];m=json.loads((p/'summary.json').read_text());z=np.load(p/'series.npz'); ids=np.flatnonzero(np.isin(z['file_id'],[i for i,f in enumerate(m['files']) if f['production']]))
  if not len(ids):continue
  ids=ids[np.argsort(z['time_ns'][ids],kind='stable')];times=z['time_ns'][ids];_,uniq=np.unique(np.round(times,6),return_index=True);ids=ids[uniq];t=z['time_ns'][ids];dt=float(np.median(np.diff(t)));f={k:z[k][ids] for k in ['signs_match','face_margin','max_forming_distance_ang','min_forming_distance_ang','mapped_twist_deg']};ok=eligible(f);wc=z['wc_fraction'][ids];local=z['local_wc_fraction'][ids];coords=z['coordinates_ang'][ids];mid=np.linalg.norm(coords[:,1:3].mean(1)-coords[:,7:9].mean(1),axis=1);counts=np.array([eligible(f,*v).sum(0) for v in grid]);bits=z['pair_primary_bits'][ids];assert np.array_equal(ok,np.array([(bits[:,m['intended_pair_index']]&(1<<i))!=0 for i in range(8)]).T)
  # Independent recomputation of stored descriptors and rigid-transform invariance.
  sample=coords[::max(1,len(coords)//100)];ff=features(sample,products);rot=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
  gg=features(sample@rot+np.array([121.,-44.,9.]),products)
  for k in ff:np.testing.assert_allclose(ff[k],gg[k],atol=1e-9);np.testing.assert_allclose(ff[k],f[k][::max(1,len(coords)//100)],atol=2e-3)
  label=rec['created'][:16]+' '+rec['job_id'][:4];r=dict(job_id=rec['job_id'],label=label,frames=len(ids),duplicate_frames_removed=int(len(times)-len(ids)),first_ns=float(t[0]),last_ns=float(t[-1]),sampled_exposure_ns=len(ids)*dt,dt_ns=dt,midpoint_mean_A=float(mid.mean()),midpoint_quantiles_A=np.quantile(mid,[0,.1,.5,.9,1]).tolist(),wc_mean=float(wc.mean()),local_wc_mean=float(local.mean()),primary_counts=ok.sum(0).tolist(),grid_min=counts.min(0).tolist(),grid_max=counts.max(0).tolist(),grid_counts=counts.tolist(),primary_any_frames=int(ok.any(1).sum()),distance_only_frames=int(((f['max_forming_distance_ang']<=4)&(f['min_forming_distance_ang']>=2.5)).any(1).sum()),episodes=[episodes(ok[:,i],t,dt) for i in range(8)],merged_100ps_episodes=[episodes(ok[:,i],t,dt,.1) for i in range(8)],merged_500ps_episodes=[episodes(ok[:,i],t,dt,.5) for i in range(8)],paired_conditionals={str(c):dict(frames=int((local>=c).sum()),primary_counts=ok[local>=c].sum(0).tolist()) for c in [.75,.9]},subsample_counts={str(s):ok[::s].sum(0).tolist() for s in [5,10,50]},quarters=[])
  for bi,ix in enumerate(np.array_split(np.arange(len(ids)),4)):
   b=dict(job_id=rec['job_id'],quarter=bi+1,frames=len(ix),midpoint_mean_A=float(mid[ix].mean()),wc_mean=float(wc[ix].mean()),local_wc_mean=float(local[ix].mean()),primary_counts=ok[ix].sum(0).tolist());r['quarters'].append(b);blocks.append(b)
  for pi,pair in enumerate(m['pairs']):
   if pair['intended']:continue
   count=int((bits[:,pi]!=0).sum())
   if count:competitors.append(dict(job_id=rec['job_id'],**pair,frames=count,fraction=count/len(ids),isomer_counts=[int(((bits[:,pi]&(1<<i))!=0).sum()) for i in range(8)]))
  r['late75_acf_diagnostics']={k:summary(x[len(x)//4:],dt) for k,x in [('midpoint_A',mid),('wc_fraction',wc),('local_wc_fraction',local)]};r['geometry_funnel']={str(d):dict(distance_only=int(((f['max_forming_distance_ang']<=d)&(f['min_forming_distance_ang']>=2.5)).any(1).sum()),distance_and_sign=int(((f['max_forming_distance_ang']<=d)&(f['min_forming_distance_ang']>=2.5)&f['signs_match']).any(1).sum()),distance_sign_twist=int(((f['max_forming_distance_ang']<=d)&(f['min_forming_distance_ang']>=2.5)&f['signs_match']&(np.abs(f['mapped_twist_deg'])<=45)).any(1).sum()),complete_primary_angles=int(eligible(f,d,45,.25).any(1).sum())) for d in [3.6,4.,4.5,5.,6.]};r['minimum_max_forming_distance_A']=f['max_forming_distance_ang'].min(0).tolist();r['late_windows']={str(c):dict(frames=len(t[int(c*len(t)):]),midpoint_mean_A=float(mid[int(c*len(t)):].mean()),wc_mean=float(wc[int(c*len(t)):].mean()),primary_counts=ok[int(c*len(t)):].sum(0).tolist()) for c in [.25,.5]};
  for ii in range(8):
   hit=np.flatnonzero(ok[:,ii])
   if len(hit):
    for ix in np.split(hit,np.flatnonzero(np.diff(t[hit])>dt*1.01)+1):events.append(dict(job_id=rec['job_id'],isomer=products[ii]['id'],start_ns=float(t[ix[0]]),end_ns=float(t[ix[-1]]),frames=len(ix),wc_mean=float(wc[ix].mean()),local_wc_mean=float(local[ix].mean())))
  results.append(r);rows.append({k:r[k] for k in ['job_id','label','frames','sampled_exposure_ns','dt_ns','midpoint_mean_A','wc_mean','local_wc_mean','primary_any_frames','distance_only_frames']})
  ax=axs[axn];stride=max(1,len(t)//5000);ax[0].plot(t[::stride],mid[::stride],lw=.35);ax[0].set_title(label);ax[0].set_ylabel('C5=C6 midpoint separation (Å)');ax[1].plot(t[::stride],wc[::stride],lw=.5,label='Whole duplex');ax[1].plot(t[::stride],local[::stride],lw=.5,alpha=.6,label='Local pairing');ax[1].set_ylim(-.03,1.06)
  for i in range(8):
   hit=t[ok[:,i]]
   if len(hit):ax[0].scatter(hit,mid[ok[:,i]],s=5,label=products[i]['id'].replace('tt-cpd-',''))
  if ok.any():ax[0].legend(fontsize=6)
  ax[1].legend(fontsize=6);axn+=1
 for ax in axs[-1]:ax.set_xlabel('Saved trajectory time (ns)')
 fig.tight_layout();fig.savefig(O/'production_timeseries.png',dpi=150);plt.close(fig)
 (O/'encounters.json').write_text(json.dumps(events,indent=2)+'\n');(O/'production_results.json').write_text(json.dumps(results,indent=2)+'\n');(O/'competing_contacts.json').write_text(json.dumps(competitors,indent=2)+'\n');(O/'quarters.json').write_text(json.dumps(blocks,indent=2)+'\n')
 with (O/'production_summary.csv').open('w') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print(json.dumps(results,indent=2))
if __name__=='__main__':summarize()
