"""Audit descriptive isomer opportunity counts from corrected cached screens.

No new trajectories. Pair/frame counts are not independent events or rates.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.cpd_isomer_formation.geometry import catalog, eligible, planar_reactant_audit
from experiments.cpd_isomer_formation.reanalyze import checked
from experiments.cpd_isomer_formation.run import pin


def describe(mask, weights, pair_ids, selected):
    x = mask[:, selected]
    counts = x.sum(axis=0)
    indices = np.flatnonzero(selected)
    order = np.argsort(-counts, kind='stable')
    return {
        'pair_frame_count': int(x.sum()),
        'distinct_pairs': int(np.count_nonzero(counts)),
        'frames_with_any': int(np.count_nonzero(x.any(axis=1))),
        'candidate_pair_denominator': len(indices),
        'time_weighted_mean_compatible_pairs_per_snapshot': float(np.average(x.sum(axis=1), weights=weights)),
        'four_sequential_sample_block_counts': [int(block.sum()) for block in np.array_split(x, 4)],
        'top_pairs': [{'pair_id': pair_ids[indices[i]], 'count': int(counts[i])}
                      for i in order[:5] if counts[i]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=ROOT/'docs/audits/cpd_anti_detection_correction_20261010.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    products = catalog()
    assert planar_reactant_audit(products)['passed']
    ids = [p['id'] for p in products]
    audit = json.loads(args.audit.read_text())
    jobs = []
    for record in audit['reanalyses']:
        summary_path = checked(record['summary'])
        summary = json.loads(summary_path.read_text())
        assert summary['stereochemical_detection_passed'] and summary['isomer_ids'] == ids
        plan_path = checked(summary['plan'])
        plan = json.loads(plan_path.read_text())
        assert [p['definition']['sha256'] for p in plan['products']] == [p['definition']['sha256'] for p in products]
        feature_path = checked(summary['feature_cache'])
        with np.load(feature_path, allow_pickle=False) as data:
            f = {k:data[k] for k in data.files}
        cache_path = checked(summary['cached_geometry'])
        with np.load(cache_path, allow_pickle=False) as data:
            weights, locators = data['time_weights_ps'], data['locators']
        assert len(weights) == summary['sample_count'] and (weights > 0).all()
        classes = np.array([p['class'] for p in summary['pairs']])
        cohorts = {
            'all': np.ones(len(classes), dtype=bool),
            'intended': classes == 'intended_weld',
            'competing': classes != 'intended_weld',
            'competing_interstrand': np.char.startswith(classes, 'interstrand:'),
            'competing_intrastrand_adjacent': np.char.startswith(classes, 'intrastrand_adjacent:'),
            'competing_intrastrand_nonadjacent': np.char.startswith(classes, 'intrastrand_nonadjacent:'),
        }
        primary = eligible(f)
        grid_summaries = []
        for grid in summary['grids']:
            mask = eligible(f, grid['distance_ang'], grid['twist_deg'], grid['face_margin'])
            np.testing.assert_array_equal(mask.sum(axis=(0,1)), grid['compatible_sample_counts_by_isomer'])
            np.testing.assert_allclose(np.average(mask, axis=0, weights=weights), grid['compatible_fraction_by_pair_isomer'], atol=1e-12)
            grid_summaries.append({
                **{k:grid[k] for k in ('distance_ang','twist_deg','face_margin')},
                'counts_by_cohort': {key:mask[:,v].sum(axis=(0,1)).tolist() for key,v in cohorts.items()},
                'ambiguous_pair_frame_count': int((mask.sum(axis=-1)>1).sum()),
            })
        records = {}
        for k, product_id in enumerate(ids):
            counts = {key:describe(primary[:,:,k],weights,summary['pair_ids'],selected) for key,selected in cohorts.items()}
            ranges = {}
            for key in cohorts:
                vals = [g['counts_by_cohort'][key][k] for g in grid_summaries]
                ranges[key] = {'minimum':min(vals),'maximum':max(vals),'windows_with_any':sum(v>0 for v in vals)}
            records[product_id] = {'primary':counts, 'sensitivity_27_windows':ranges}
        jobs.append({
            'job_id':plan['job_id'], 'lineage_id':plan['lineage_id'], 'name':record['name'],
            'sampled_frames':len(weights), 'represented_time_ns':float(weights.sum()/1000),
            'source_pins':[pin(summary_path),pin(plan_path),pin(feature_path),pin(cache_path)],
            'sample_time_gaps_ps': sorted(np.unique(np.diff(locators[:,2])).tolist()),
            'products':records, 'sensitivity_grid':grid_summaries,
        })
    aggregate = {}
    for pid in ids:
        aggregate[pid] = {cohort:{metric:sum(j['products'][pid]['primary'][cohort][metric] for j in jobs)
                                for metric in ('pair_frame_count','distinct_pairs')}
                          for cohort in cohorts}
    report = {
        'schema':'nadoc.cpd-isomer-opportunity-priority.v1',
        'created_at':datetime.now(timezone.utc).isoformat(), 'source_audit':pin(args.audit),
        'script':pin(Path(__file__)), 'products':products, 'jobs':jobs,
        'aggregate_descriptive_counts':aggregate,
        'aggregation_rule':'Counts and distinct (job, ordered-pair) observations only; not a duration-weighted pooled population or number of independent sites/events.',
        'primary_window':audit['primary_window'],
        'scope':'Three corrected unwelded pilot jobs, 200 sampled frames each; includes competing thymine pairs.',
        'refinement_priority_order_excluding_existing_cis_syn_i_reference':[
            'tt-cpd-cis-anti-i','tt-cpd-cis-syn-ii','tt-cpd-trans-syn-ii','tt-cpd-cis-anti-ii',
            'tt-cpd-trans-syn-i','tt-cpd-trans-anti-i','tt-cpd-trans-anti-ii'],
        'ranking_rule':'Practical judgment using intended-weld relevance, competing-product coverage, distinct pairs, cutoff sensitivity, and existing reusable core evidence. Not a calibrated kinetic ranking or significance test.',
        'limits':[
            'Snapshots and sites within a design are correlated; no p-values or confidence interval from frame counts.',
            'Only one screened 24HB lineage; different designs and durations cannot be pooled as exchangeable replicates.',
            'Equal photochemical factors across isomers have not been established.',
            'Counts use fixed ordered endpoints; I/II names can change on endpoint relabeling.',
            'No reactions, independent encounter lifetimes, simultaneous weld yields, or melting shifts inferred.',
            'All old anti QM/MM/MD evidence requires corrected-identity requalification.',
        ],
        'new_md_or_qm_runs':0, 'cloud_spending':0,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as stream:
        json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(aggregate,indent=2))


if __name__ == '__main__':
    main()
