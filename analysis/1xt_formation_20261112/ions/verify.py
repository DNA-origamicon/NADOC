"""Independent checks of saved ionic-analysis artifacts and geometric shell volumes."""
import json, warnings
from pathlib import Path
import numpy as np
import MDAnalysis as mda
from MDAnalysis.lib.distances import distance_array
from scipy.spatial import cKDTree
from scipy.stats import qmc
warnings.filterwarnings('ignore',category=DeprecationWarning)
O=Path(__file__).resolve().parent;s=json.loads((O/'summary.json').read_text());z=np.load(O/'timeseries.npz');p=Path(s['source_dcd']);meta=json.loads((O.parent/'2bc15e9e2531/summary.json').read_text());u=mda.Universe(str(Path(meta['package'])/meta['files'][0]['config']['structure']),str(p));h=u.select_atoms('segid D* and not name H*');mg=u.select_atoms('resname MGH and name MG');cl=u.select_atoms('resname CLA')
assert np.all(np.diff(z['counts'],axis=1)>=0);assert np.all(z['net_charge_e'][:,-1]==0)
assert np.allclose(z['shell_volume_A3'].sum(1),z['box_volume_A3'][z['density_sample_frames']]);assert np.all(z['shell_counts'].sum(1)==[66,39])
checks=[]
for f in [0,2500,5000,7500,9975]:
 ts=u.trajectory[f];box=ts.dimensions[:3].astype(float);dx=distance_array(mg.positions,h.positions,box=ts.dimensions).min(1);np.testing.assert_allclose(dx,z['nearest_ion_DNA_A'][f,:66],atol=1e-4)
 tree=cKDTree(h.positions.astype(float)%box,boxsize=box);pts=qmc.Sobol(3,scramble=True,seed=f+777).random_base2(18)*box;d=tree.query(pts)[0];v=np.histogram(d,z['density_edges_A'])[0]/len(d)*np.prod(box);i=np.where(z['density_sample_frames']==f)[0][0];old=z['shell_volume_A3'][i]
 mask=z['density_edges_A'][:-1]>=20;checks.append({'frame':f,'max_shell_volume_difference_fraction_box':float(abs(v-old).max()/np.prod(box)),'far_20A_relative_volume_difference':float((v[mask].sum()-old[mask].sum())/v[mask].sum())})
assert max(abs(c['far_20A_relative_volume_difference']) for c in checks)<.02
out={'passed':True,'checks':['monotone enclosed counts','full-cell net charge zero','density shell volumes sum to instantaneous cell volume','density shell counts conserve 66 Mg and 39 Cl','independent MDAnalysis minimum-image Mg distances at 5 frames','independent scrambled Sobol volume integration with 8x points at 5 frames; far-field volume within 2%'],'volume_checks':checks}
(O/'verification.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
