exec(open('analysis/3x6SQ_P2/analyze.py').read().split('rows=[];profiles=[]')[0])
ts=r[-1];x=ts.positions;h=x[heavy].astype(float);box=ts.dimensions[:3];tree=cKDTree(h);results=[]
fig,ax=plt.subplots(1,2,figsize=(13,5))
for shift in shifts:
 v=shift*box
 if np.linalg.norm(np.maximum(abs(v)-np.ptp(h,axis=0),0))>10:continue
 ds,ix=tree.query(h+v,workers=2);hit=np.where(ds<10)[0]
 if len(hit):
  results.append(dict(shift=shift.tolist(),min_A=float(ds.min()),source_atoms_with_neighbor_within_10A=len(hit),source_atoms_with_neighbor_within_4A=int((ds<4).sum()),reference_z_nm_percentiles=np.percentile(ref[heavy[hit],2]/10,[0,10,50,90,100]).tolist()))
  ax[1].hist(ref[heavy[hit],2]/10,bins=35,alpha=.55,label=str(shift.tolist()))
ax[1].set_xlabel('Initial atom z (nm)');ax[1].set_ylabel('DNA heavy atoms within 1 nm of periodic copy');ax[1].legend()
# unwrapped DNA and its y image, projected onto yz, equal physical scale
ax[0].scatter(h[::15,2]/10,h[::15,1]/10,s=.3,label='DNA')
ax[0].scatter(h[::15,2]/10,(h[::15,1]+box[1])/10,s=.3,label='+y periodic copy')
ax[0].set_aspect('equal');ax[0].set_xlabel('z (nm)');ax[0].set_ylabel('y (nm)');ax[0].legend(markerscale=5);fig.suptitle('Final frame (67.8 ns): periodic-image contacts');fig.tight_layout();fig.savefig(out/'contacts.png',dpi=180)
json.dump(results,open(out/'contacts.json','w'),indent=2);print(json.dumps(results,indent=2))
