from pathlib import Path
import json,numpy as np,mmap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from backend.core.md_trajectory import _DcdPrefixFile
root=Path(__file__).resolve().parent;d=root/'open_pore/fill_92_npzat';meta=json.loads((d/'meta.json').read_text());ng=meta['graphene_atoms'];nw=meta['water_count'];n=ng+nw*3+meta['salt_pairs']*2;c=np.array(meta['pore_center_nm']);box0=np.array(meta['box_nm']);water=ng+np.arange(nw)*3
cases=[];pos=[]
with (root/'open_pore/fill_92/system.pdb').open() as f:
 for l in f:
  if l.startswith(('ATOM  ','HETATM')):pos.append([float(l[a:a+8])/10 for a in [30,38,46]])
cases.append(('As solvated, 8% water removed',np.array(pos),box0))
x=np.memmap(d/'start.coor',dtype='<f8',offset=4,shape=(n,3))/10;cases.append(('Depleted checkpoint, 156 ps',x,box0))
r=_DcdPrefixFile(root/'open_pore/fill_92_nvt_offload/run.dcd',0)
with mmap.mmap(r.fd,0,access=mmap.ACCESS_READ) as m:
 f=min(r.n_frames-1,19);sample_ps=(f+1)*10;base=r.frame_start+f*r.frame_bytes;box=np.frombuffer(m,'<f8',6,base+4)[[0,2,5]]/10;x=np.stack([np.frombuffer(m,'<f4',n,base+r.cell_record_bytes+a*r.coord_record_bytes+4).copy()/10 for a in range(3)],axis=1)
cases.append((f'NVT continuation, +{sample_ps} ps',x,box));r.close()
x=np.memmap(d/'run.coor',dtype='<f8',offset=4,shape=(n,3))/10;box=np.array((d/'run.xsc').read_text().splitlines()[-1].split()[1:10],float).reshape(3,3).diagonal()/10;cases.append(('Pressure equilibration, +200 ps',x,box))
fig,axes=plt.subplots(1,4,figsize=(13,4),constrained_layout=True)
for ax,(title,pos,box) in zip(axes,cases):
 rel=pos[water]-c;rel-=box*np.round(rel/box);sel=abs(rel[:,1])<.5;xb=np.linspace(-box[0]/2,box[0]/2,49);zb=np.linspace(-box[2]/2,box[2]/2,int(round(box[2]/.25))+1);h,_,_=np.histogram2d(rel[sel,0],rel[sel,2],bins=[xb,zb]);h=h/(np.diff(xb)[:,None]*np.diff(zb)[None,:])
 im=ax.imshow(h.T,origin='lower',extent=[xb[0],xb[-1],zb[0],zb[-1]],vmin=0,vmax=40,cmap='Blues',aspect='equal');ax.plot([-box[0]/2,-4],[0,0],'k-',lw=3);ax.plot([4,box[0]/2],[0,0],'k-',lw=3);ax.set_title(title,fontsize=10);ax.set(xlim=(-6.3,6.3),ylim=(-6.3,6.3),xlabel='x from pore center (nm)');ax.set_facecolor('#dddddd')
axes[0].set_ylabel('z from membrane (nm)');fig.colorbar(im,ax=axes,label='Water oxygens / nm³',shrink=.7);fig.suptitle('1 nm central slice; black = graphene; gray = outside the periodic cell')
fig.savefig(root/'depletion_density.png',dpi=170);fig.savefig(root/'depletion_density.pdf')
