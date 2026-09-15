"""Audit native integrity, preparation identities and budget; no physics verdict."""
import json
import re
import numpy as np
import campaign as c

checks=[]
for p in sorted(c.ROOT.iterdir()):
    if not p.is_dir() or not (p/'manifest.json').exists():continue
    m=json.loads((p/'manifest.json').read_text())
    atoms=c.parse_psf_atoms((p/'system.psf').read_text())
    c.gold_model.validate_electrolyte((p/'forcefield/toppar_water_ions_cufix.str').read_text())
    for name,digest in m['asset_sha256'].items():
        if c.gp.sha(p/name)!=digest:raise ValueError(f'Changed asset {p/name}')
    if len(atoms)!=m['n_atoms'] or abs(sum(a.charge for a in atoms))>1e-8:raise ValueError('Atom/neutrality bookkeeping failure')
    for record in p.glob('*.run.json'):
        r=json.loads(record.read_text())
        if r['status']!='complete':continue
        name=record.name.removesuffix('.run.json');conf=(p/f'{name}.conf').read_text();log=(p/f'{name}.log').read_text()
        first=re.search(r'firsttimestep (\d+)',conf);mini=re.search(r'^minimize (\d+)',conf,re.M)
        expected=(int(first[1]) if first else 0)+r['steps']+(int(mini[1]) if mini else 0)
        step=c.checkpoint_step(p,name)
        if step!=expected or 'Running with GPU-resident mode' not in log:raise ValueError('Native stage identity failure')
        if 'FATAL ERROR' in log or re.search(r'constraint failure|\bNaN\b',log,re.I):raise ValueError(f'Native stage diagnostic failure: {p/name}')
        rows=[s for s in log.splitlines() if s.startswith('ENERGY:')]
        if any(not np.isfinite(np.array(s.split()[1:],float)).all() for s in rows):raise ValueError('Nonfinite energy')
        checks.append(dict(case=p.name,stage=name,final_step=step,finite_energy_rows=len(rows),
            native_wall_s=r['wall_s'],config_sha256=c.gp.sha(p/f'{name}.conf'),status='integrity_verified'))
result=dict(checks=checks,n_complete_stages=len(checks),all_completed_integrity_checks_pass=True,
    total_recorded_native_seconds=sum(json.loads(p.read_text()).get('wall_s',0) for p in c.ROOT.glob('*/*.run.json')),
    physical_qualification=False)
(c.ROOT/'integrity_audit.json').write_text(json.dumps(result,indent=2))
print(len(checks),'completed stages verified')
