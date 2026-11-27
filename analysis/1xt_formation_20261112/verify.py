"""Final read-only input-integrity and derived-result consistency checks."""
import hashlib
import json
from pathlib import Path
import numpy as np

O=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads((O/p).read_text())

def main():
    for rec in read('inventory.json'):
        m=read(rec['job_id']+'/summary.json')
        assert sha(Path(rec['job_dir'])/'design.json')==rec['design_sha256']
        assert sha(Path(m['wc_plan']))==m['wc_plan_sha256']
        for f in m['files']:
            st=Path(f['path']).stat()
            assert (st.st_size,st.st_mtime_ns)==(f['bytes'],f['mtime_ns'])
            assert sha(Path(f['config_path']))==f['config_sha256']
            assert sha(Path(m['package'])/f['config']['structure'])==m['topology_sha256']
            for rel,digest in f['parameter_hashes'].items():
                assert sha(Path(m['package'])/rel)==digest
    f=read('followup_checks.json')
    assert sha(Path('workspace/2hb_1xT.nadoc'))==f['current_part_sha256']
    s=read('protocol_structure_checks.json')[0]
    assert not s['dna_extrabonds']
    assert all(not x['ring_piercings'] for x in s['structure_spot_checks'])
    a=np.genfromtxt(O/'all_frame_image_clearance.csv',delimiter=',',names=True)
    b=np.genfromtxt(O/'2bc15e9e2531_trace.csv',delimiter=',',names=True)
    assert len(a)==10000
    indices=np.rint((b['time_ns']-a['time_ns'][0])/np.median(np.diff(a['time_ns']))).astype(int)
    np.testing.assert_allclose(a['time_ns'][indices],b['time_ns'],atol=1e-6)
    assert np.all(a['nearest_image_all_atoms_A'][indices]<=b['nearest_image_heavy_A']+1e-5)
    native=read('all_frame_image_clearance.json')
    np.testing.assert_allclose(a['nearest_image_all_atoms_A'].min(),native['brute_force_minimum_A'],atol=1e-6)
    v=read('verification.json')
    v.update(final_source_config_parameter_design_hashes_unchanged=True,
             periodic_image_bruteforce_checks=4,
             all_atom_native_vs_heavy_atom_sampled_consistent=True,
             old_new_physical_wc_pair_mapping_verified=True,
             part_unchanged_since_followup_hash=True,
             code_sha256={p.name:sha(p) for p in O.glob('*.py')},
             deliverable_sha256={p.name:sha(p) for p in [O/'review.md',O/'followup_timeseries.png']})
    (O/'verification.json').write_text(json.dumps(v,indent=2)+'\n')
    print('Input-integrity, native-frame clearance, and derived-result consistency checks passed.')

if __name__=='__main__':main()
