"""Independent input accounting and completed-run integrity for screening pilots."""
import json
import re
import numpy as np
from backend.core import namd_gold_package as gp
from backend.core.md_charge import parse_psf_atoms
from experiments.gold_interfaces.native import read_binary, checkpoint_step
from experiments.gold_interfaces.screening.campaign import ROOT


def audit():
    results=[]
    for p in sorted(ROOT.glob('*_*')):
        if not (p/'manifest.json').exists():continue
        m=json.loads((p/'manifest.json').read_text());atoms=parse_psf_atoms((p/'system.psf').read_text())
        for name,digest in m['asset_sha256'].items():assert gp.sha(p/name)==digest,name
        q=np.array([a.charge for a in atoms]);params=np.loadtxt(p/'electrode_gpu.params',skiprows=1)
        assert params.shape==(len(q),6) and np.array_equal(params[:,0],q)
        assert abs(q.sum())<1e-8
        au=np.array([i for i,a in enumerate(atoms) if a.atomtype=='NAUI'])
        assert len(au)==m['n_gold'] and len(atoms)==m['n_atoms']
        expected=m['screening'].get('electrode_charge_magnitude_e',0.)
        # The PSF writes ten decimal places; this bound is its known rounding error.
        serialization_bound=len(au)*.5e-10+1e-10
        assert abs(q[au][q[au]>0].sum()-expected)<=serialization_bound
        assert abs(q[au][q[au]<0].sum()+expected)<=serialization_bound
        neutral=ROOT/p.name.replace('charged','neutral')
        assert gp.sha(p/'system.pdb')==gp.sha(neutral/'system.pdb')
        if expected:
            try:gp.verify_package(p)
            except ValueError as exc:assert 'Gold model specification was modified' in str(exc)
            else:raise AssertionError('Experimental charged model must not masquerade as registered neutral model')
        stages=[]
        for runfile in sorted(p.glob('*.run.json')):
            r=json.loads(runfile.read_text())
            if r['status']!='complete':continue
            stem=runfile.name.removesuffix('.run.json');log=(p/f'{stem}.log').read_text()
            assert gp.sha(p/f'{stem}.conf')==r['config_sha256']
            assert 'End of program' in log and 'Running with GPU-resident mode' in log
            assert not re.search(r'FATAL ERROR|\bNaN\b',log,re.I)
            energy=[list(map(float,s.split()[1:])) for s in log.splitlines() if s.startswith('ENERGY:')]
            assert len(energy) and np.isfinite(energy).all()
            for ext in ('coor','vel'):
                xyz=read_binary(p/'output'/f'{stem}.{ext}')
                assert len(xyz)==len(atoms) and np.isfinite(xyz).all()
            assert checkpoint_step(p,stem)==r['final_step']
            stages.append(stem)
        results.append(dict(case=p.name,input_hashes_verified=True,psf_and_slab_charges_identical=True,
            net_charge_e=float(q.sum()),positive_negative_gold_charge_e=[float(q[au][q[au]>0].sum()),float(q[au][q[au]<0].sum())],
            paired_coordinates_identical=True,completed_stages=stages,physical_validation=False))
    (ROOT/'integrity_audit.json').write_text(json.dumps(results,indent=2)+'\n')
    print([(r['case'],r['completed_stages']) for r in results])

if __name__=='__main__':audit()
