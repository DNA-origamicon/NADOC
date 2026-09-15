"""Rebuild inspectable tables/figures from completed runs only."""
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
import campaign as c

def main():
    rows=[]
    for p in sorted(c.ROOT.iterdir()):
        if p.is_dir():
            for a in p.glob('*_analysis.json'):
                r=json.loads(a.read_text());r['path']=str(a.relative_to(c.ROOT));rows.append(r)
    bulk=[r for r in rows if r['kind']=='bulk'];target=np.mean([r['late_density'] for r in bulk])
    runtime=[]
    for p in c.ROOT.glob('*/*.run.json'):
        r=json.loads(p.read_text());runtime.append({'file':str(p.relative_to(c.ROOT)),**r})
    (c.ROOT/'summary.json').write_text(json.dumps(dict(bulk_density_reference=target,cases=rows,
        native_wall_seconds=sum(r.get('wall_s',0) for r in runtime),runs=runtime,
        physical_qualification=False),indent=2))
    lines=['| Case | Waters / Na / Cl | Late water density, nm⁻³ | 20 ps block conditional 95% halfwidth | Na / Cl, mM | Water translation / rotation, K |',
           '| --- | --- | ---: | ---: | --- | --- |']
    for r in rows:
        h=next(b['conditional_95_halfwidth'] for b in r['density_blocks'] if b['block_ps']==20)
        lines.append(f"| {r['case']} | {r['n_water']} / {r['n_na']} / {r['n_cl']} | {r['late_density']:.3f} | {h:.3f} | {r['late_na_mM']:.1f} / {r['late_cl_mM']:.1f} | {r['late_translational_K']:.2f} / {r['late_rotational_K']:.2f} |" if h is not None else '')
    (c.ROOT/'measurements.md').write_text('\n'.join(lines)+'\n')
    fig,axes=plt.subplots(1,3,figsize=(14,4),layout='constrained')
    for r in rows:
        a=c.ROOT/r['case']/f"{r['prefix']}_series.csv";s=np.loadtxt(a,delimiter=',',skiprows=1)
        ax=axes[0 if r['kind']=='bulk' else 1 if r['kind']=='slab' else 2]
        ax.plot(s[:,0],s[:,1],label=r['case'].replace('nanoparticle_','NP_'),alpha=.65,lw=.8)
    for ax,title in zip(axes,['Bulk NPT','Au(111) slit NVT','Nanoparticle NVT']):
        ax.axhline(target,color='black',ls='--',lw=1,label='Measured bulk mean')
        ax.set(title=title,xlabel='Time from dynamics start (ps)',ylabel='Water molecules / nm³');ax.legend(fontsize=6)
    fig.savefig(c.ROOT/'density_traces.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(2,3,figsize=(14,8),layout='constrained')
    for r in rows:
        if r['kind']=='bulk':continue
        s=np.loadtxt(c.ROOT/r['case']/f"{r['prefix']}_profiles.csv",delimiter=',',skiprows=1)
        i=0 if r['kind']=='slab' else 1;ls=':' if r['case'].endswith('initial') else '-'
        label=r['case'].replace('nanoparticle_','NP_')
        axes[i,0].plot(s[:,0],s[:,1],ls,label=label,lw=1)
        axes[i,1].plot(s[:,0],s[:,2],ls,label=label+' Na',lw=1)
        axes[i,1].plot(s[:,0],s[:,3],ls,label=label+' Cl',lw=.7,alpha=.5)
        axes[i,2].plot(s[:,0],s[:,4],ls,label=label,lw=1)
    for i in range(2):
        axes[i,0].axhline(target,color='black',ls='--',lw=1)
        for j,title in enumerate(['Water density (nm⁻³)','Ion density (nm⁻³)','Mean dipole cosine']):
            axes[i,j].set(title=title,xlabel='Distance from inner face (nm)' if i==0 else 'Radius from gold COM (nm)');axes[i,j].legend(fontsize=6)
    fig.suptitle('Last-half profiles: independent preparations; adsorption not qualified')
    fig.savefig(c.ROOT/'interface_profiles.png',dpi=180);plt.close(fig)
    print('cases',len(rows),'native seconds',sum(r.get('wall_s',0) for r in runtime))

if __name__=='__main__':main()
