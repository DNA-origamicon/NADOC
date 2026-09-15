"""Second inventory update from measured response, independently re-prepared."""
import json
import numpy as np
import campaign as c
from analyze_campaign import analyze

bulk=np.mean([json.loads((c.ROOT/f'bulk_{s}/npt_analysis.json').read_text())['late_density'] for s in c.SEEDS])
old=[json.loads((c.ROOT/f'slab_{s}_initial/pilot_analysis.json').read_text()) for s in c.SEEDS]
new=[json.loads((c.ROOT/f'slab_{s}_revised/pilot_analysis.json').read_text()) for s in c.SEEDS]
response=(np.mean([r['n_water'] for r in new])-np.mean([r['n_water'] for r in old]))/(np.mean([r['late_density'] for r in new])-np.mean([r['late_density'] for r in old]))
target=int(round(new[0]['n_water']+(bulk-np.mean([r['late_density'] for r in new]))*response))
(c.ROOT/'slit_refinement.json').write_text(json.dumps(dict(target_water=target,bulk_density=bulk,
    observed_response_dN_drho_nm3=response,previous_density_mean=float(np.mean([r['late_density'] for r in new])),
    note='Secant inventory update from the two pilot levels; no force-field fit'),indent=2))
for seed in c.SEEDS:
    p=c.gold('slab',seed,scale=1.22,suffix='calibrated_fixed_ions',target_water=target,ion_pairs=6)
    c.execute(p,'minimize',0,minimize=500)
    c.execute(p,'pilot',300000,'minimize')
    analyze(p,'pilot')
