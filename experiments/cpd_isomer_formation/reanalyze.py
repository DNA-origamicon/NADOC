"""Reclassify hash-verified cached reactant coordinates with current definitions.

No trajectory reread, simulation, fitting or photochemical rate prediction.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.cpd_isomer_formation.geometry import catalog, features, planar_reactant_audit
from experiments.cpd_isomer_formation.run import pin, summarize_grids


def checked(record):
    p = Path(record['path'])
    if pin(p)['sha256'] != record['sha256']:
        raise ValueError(f'Changed cached input: {p}')
    return p


def reanalyze(source, out):
    started = time.monotonic()
    previous = json.loads((source / 'summary.json').read_text())
    plan_path = checked(previous['plan'])
    oldplan = json.loads(plan_path.read_text())
    cache_path = checked(previous['cached_geometry'])
    products = catalog()
    audit = planar_reactant_audit(products)
    if not audit['passed']:
        raise ValueError('Suprafacial coverage or cis/trans identity preflight failed')
    if previous['isomer_ids'] != [p['id'] for p in products]:
        raise ValueError('Cached and current isomer orders differ')
    out.mkdir(parents=True, exist_ok=False)
    plan = {**oldplan, 'created_at': datetime.now(timezone.utc).isoformat(),
            'products': products, 'reactant_mapping_audit': audit, 'diagnostic_only': False,
            'source_summary': pin(source / 'summary.json'), 'source_plan': pin(plan_path),
            'source_cache': pin(cache_path),
            'source_cache_scope': 'Coordinates, weights, atom indices and frame locators only; old descriptors are superseded',
            'scripts': [pin(Path(__file__)), pin(Path(__file__).with_name('geometry.py')),
                        pin(Path(__file__).with_name('run.py'))]}
    (out / 'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    try:
        with np.load(cache_path, allow_pickle=False) as cache:
            x, w = cache['coordinates_ang'], cache['time_weights_ps']
            if (x.shape != (previous['sample_count'], len(previous['pair_ids']), 12, 3)
                    or w.shape != (len(x),) or not np.isfinite(x).all()
                    or not np.isfinite(w).all() or not (w > 0).all()):
                raise ValueError('Invalid cached coordinates or weights')
            f = features(x, products)
            syn = [i for i,p in enumerate(products) if p['family'] == 'syn']
            for key in f:
                np.testing.assert_allclose(f[key][..., syn], cache[key][..., syn], atol=1e-12, rtol=0)
            grids = summarize_grids(f, w, plan)
        # Recheck immutable input identity after reading, before emitting results.
        checked(previous['cached_geometry'])
        np.savez_compressed(out / 'features.npz', **f)
        result = {**previous, 'plan': pin(out / 'plan.json'), 'grids': grids,
                  'formation_ranking_qualified': False, 'reactant_mapping_passed': True,
                  'stereochemical_detection_passed': True, 'syn_descriptors_unchanged': True,
                  'cached_geometry_scope': plan['source_cache_scope'],
                  'feature_cache': pin(out / 'features.npz'),
                  'elapsed_seconds': time.monotonic()-started}
        (out / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')
        primary = next(g for g in grids if (g['distance_ang'],g['twist_deg'],g['face_margin']) == (4.,45.,.25))
        brief = {'job':oldplan['job_id'], 'samples':len(x), 'pairs':x.shape[1],
                 'primary_counts':dict(zip(previous['isomer_ids'],primary['compatible_sample_counts_by_isomer'])),
                 'elapsed_seconds':result['elapsed_seconds']}
        print(json.dumps(brief, indent=2), flush=True)
        return result
    except Exception as exc:
        (out / 'failure.json').write_text(json.dumps({'error':repr(exc)},indent=2)+'\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reanalyze(args.source, args.out)
