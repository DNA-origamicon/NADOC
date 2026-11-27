"""Compare saved analyses and verify protocol identity; no molecular authoring."""
import hashlib
import itertools
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import MDAnalysis as mda
import numpy as np
from scipy.spatial.distance import cdist

O = Path(__file__).resolve().parent
OLD = O.parent / '1xt_formation_20261110'
JID = '2bc15e9e2531'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    m = json.loads((O/JID/'summary.json').read_text())
    r = json.loads((O/'production_results.json').read_text())[0]
    shapes = json.loads((O/'additional_shape_results.json').read_text())[0]
    a = np.genfromtxt(O/(JID+'_trace.csv'), delimiter=',', names=True)
    pkg = Path(m['package'])
    u = mda.Universe(str(pkg/m['files'][0]['config']['structure']))
    dna = u.select_atoms('segid D*')
    def identity(ag):
        return sorted((x.segid, int(x.resid), x.name, x.type, round(float(x.charge), 6)) for x in ag)
    oldm = json.loads((OLD/'a9261569b8c7'/'summary.json').read_text())
    oldpkg = Path(oldm['package'])
    ou = mda.Universe(str(oldpkg/oldm['files'][0]['config']['structure']))
    newwp = json.loads(Path(m['wc_plan']).read_text())
    oldwp = json.loads(Path(oldm['wc_plan']).read_text())
    # The old reference plan belongs to its own topology, not necessarily the
    # topology of the comparison production job.
    wu = mda.Universe(str(next(Path(oldm['wc_plan']).parent.glob('*.psf'))))
    def pairs(universe, plan):
        return {tuple(sorted((universe.atoms[i].segid, int(universe.atoms[i].resid), universe.atoms[i].name)
                             for i in pair)): distance
                for p in plan['pairs'] for pair, distance in zip(p['atom_pairs'], p['ref_distances'])}
    oldpairs, newpairs = pairs(wu, oldwp), pairs(u, newwp)
    assert oldpairs.keys() == newpairs.keys()
    delta = np.array([newpairs[k]-v for k, v in oldpairs.items()])
    thermal = json.loads((O/'thermal_results.json').read_text())[0]['logs'][0]
    volume = thermal['statistics']['VOLUME']['mean']
    factors = 1e30 / (6.02214076e23 * volume)
    protocol = dict(
        actual_config=m['files'][0]['config'], total_atoms=len(u.atoms), dna_atoms=len(dna),
        dna_charge_e=float(dna.charges.sum()),
        h6_masses_amu=np.unique(dna.select_atoms('name H6').masses).tolist(),
        ions=m['ion_residue_counts'],
        mean_volume_A3=volume,
        total_Mg_mM=m['ion_residue_counts']['MGH']*factors,
        chloride_mM=m['ion_residue_counts']['CLA']*factors,
        chloride_equivalent_MgCl2_mM=m['ion_residue_counts']['CLA']*factors/2,
        note='Number densities, not free ion concentrations. Mg includes DNA-neutralizing counterions.',
        dna_identity_type_charge_matches_October=identity(dna)==identity(ou.select_atoms('segid D*')),
        shared_parameter_hash_matches={k:v==oldm['files'][0]['parameter_hashes'].get(k)
                                      for k,v in m['files'][0]['parameter_hashes'].items()},
        manifest_solvation=json.loads((pkg/'manifest.json').read_text())['solvation'],
        pairing=dict(same_physical_atom_pairs=True, old_plan_sha256=sha(Path(oldm['wc_plan'])),
                     new_plan_sha256=sha(Path(m['wc_plan'])), reference_delta_min_mean_max_A=[float(delta.min()), float(delta.mean()), float(delta.max())],
                     old_reference_sampled_mean=float(a['old_reference_wc_fraction'].mean()),
                     old_reference_sampled_local_mean=float(a['old_reference_local_wc_fraction'].mean()),
                     new_reference_native_mean=r['wc_mean'], new_reference_native_local_mean=r['local_wc_mean']))
    # Independent, brute-force verification of the tree-based nearest image
    # calculation on first, closest-image and last sampled conformations.
    heavy = dna.select_atoms('not name H*')
    u.load_new(m['files'][0]['path'])
    verification = []
    for si in sorted(set([0, int(np.argmin(a['nearest_image_heavy_A'])), len(a)-1])):
        fi = int(round((a['time_ns'][si]-m['files'][0]['first_ns'])/m['files'][0]['dt_ns']))
        ts = u.trajectory[fi]
        x = heavy.positions.astype(float)
        box = ts.dimensions[:3]
        # All potentially closer images, no bounding-box pruning or KD tree.
        v = min(float(cdist(x, x+np.array(shift)*box).min())
                for shift in itertools.product(*[range(-n,n+1) for n in np.floor((np.ptp(x,axis=0)+min(box))/box).astype(int)]) if shift != (0,0,0))
        np.testing.assert_allclose(v, a['nearest_image_heavy_A'][si], atol=1e-5)
        verification.append(dict(frame=fi, time_ns=float(a['time_ns'][si]), minimum_image_A=v))
    image = dict(sampled_frames=len(a), sample_interval_ns=float(np.median(np.diff(a['time_ns']))),
                 minimum_A=float(a['nearest_image_heavy_A'].min()),
                 minimum_time_ns=float(a['time_ns'][np.argmin(a['nearest_image_heavy_A'])]),
                 quantiles_A=np.quantile(a['nearest_image_heavy_A'],[0,.05,.5,.95,1]).tolist(),
                 frames_below_10A=int(sum(a['nearest_image_heavy_A']<10)),
                 frames_below_12A=int(sum(a['nearest_image_heavy_A']<12)),
                 brute_force_verification=verification,
                 qualification='Heavy-atom nearest-image distances at 0.1 ns; does not exclude between-frame encounters or finite-size electrostatic effects.')
    quarters = []
    for i, ix in enumerate(np.array_split(np.arange(len(a)), 4)):
        quarters.append(dict(quarter=i+1, **{k:float(a[k][ix].mean()) for k in a.dtype.names if k!='time_ns'}))
    # Confirm actual atom order used by the earlier classifier, rather than
    # inheriting the reversed endpoint order in its narrative report.
    oldends = {p.parent.name:json.loads(p.read_text())['ordered_endpoints']
               for p in OLD.glob('*/summary.json')}
    assert all(v == m['ordered_endpoints'] for v in oldends.values())
    out=dict(protocol=protocol, periodic_images=image, shape_quarters=quarters,
             classifier_endpoint_order=m['ordered_endpoints'], old_endpoint_orders=oldends,
             previous_classifier_source_sha256=json.loads((OLD/'classifier_audit.json').read_text())['source_sha256'],
             current_classifier_source_sha256=sha(Path('experiments/cpd_isomer_formation/geometry.py')),
             current_part_sha256=sha(Path('workspace/2hb_1xT.nadoc')))
    (O/'followup_checks.json').write_text(json.dumps(out, indent=2)+'\n')

    z=np.load(O/JID/'series.npz');t=z['time_ns'];coords=z['coordinates_ang']
    midpoint=np.linalg.norm(coords[:,1:3].mean(1)-coords[:,7:9].mean(1),axis=1)
    fig,axs=plt.subplots(4,1,figsize=(11,10),sharex=True)
    axs[0].plot(t,midpoint,lw=.35,color='#1764a0');axs[0].set_ylabel('T–T midpoint (Å)')
    axs[0].set_title('2hb_1xT · created 2026-11-11 09:56 MST · completed 200 ns')
    axs[1].plot(t,z['wc_fraction'],lw=.35,label='Whole duplex (new reference)')
    axs[1].plot(t,z['local_wc_fraction'],lw=.35,alpha=.6,label='Four junction-adjacent pairs')
    axs[1].set_ylabel('Paired fraction');axs[1].legend(loc='lower left',fontsize=8)
    axs[2].plot(a['time_ns'],a['helix_tilt_deg'],lw=.6,color='#9b59b6');axs[2].set_ylabel('Helix tilt (°)')
    native=np.genfromtxt(O/'all_frame_image_clearance.csv',delimiter=',',names=True)
    axs[3].plot(native['time_ns'],native['nearest_image_all_atoms_A'],lw=.4,color='#2c8061')
    axs[3].axhline(10,color='#555555',ls=':',label='10 Å nonbonded cutoff')
    axs[3].axhline(12,color='#b24136',ls='--',label='12 Å pair-list distance')
    axs[3].set_ylabel('Nearest DNA image (Å)\nIncluding hydrogens');axs[3].legend(fontsize=8)
    axs[3].set_xlabel('Production time (ns)')
    for ax in axs:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(O/'followup_timeseries.png',dpi=160);plt.close(fig)
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()
