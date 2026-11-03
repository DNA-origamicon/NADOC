"""Replay the retained origami resource campaigns; never launch dynamics or install a fit.

Use --output to select the review artifact directory. Its baseline/ contains the
pre-review estimator and current/ contains optional fresh preparation probes.
Old, failed, incomplete and unprovenanced runs are recorded in exclusions.json;
they never contribute to current fits, summaries or pass/fail counts.
"""
import argparse
from collections import defaultdict
import hashlib
import html
import json
import math
from pathlib import Path
import shlex
import sys

import numpy as np
from scipy.optimize import nnls

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from backend.core.resource_spikes import summarize_series
from backend.core.namd_measurements import qualification_reasons
from backend.core.namd_allocation_model import QUALIFIED_ENGINE


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def hardware_provenance(hardware, engine_hash, threads):
    import re
    lines=str(hardware.get('gpu','')).strip().splitlines()
    fields=[s.strip() for s in lines[-1].split(',')] if lines else []
    return dict(engine_sha256=engine_hash, threads=threads,
        gpu=fields[0] if fields else None,
        driver=next((s for s in fields if re.fullmatch(r'\d+\.\d+\.\d+',s)),None))


def qualified_feature_rows(artifacts, rows):
    """Resolve contemporaneous campaign records; never borrow a sizing-helper hash."""
    accepted=[];excluded=[];campaigns={}
    for row in rows:
        ident=row['id'];parent=True;raw={};provenance={};conf=Path(row['configuration']);log=None
        if ident.startswith('namd-geometry-pilot-20261101/'):
            campaign='namd-geometry-pilot-20261101';case_id,phase=ident[len(campaign)+1:].split('/',1)
            if campaign not in campaigns:
                root=artifacts/campaign
                campaigns[campaign]=(read(root/'results.json'),read(root/'hardware.json'),read(root/'provenance.json')['namd_sha256'])
            cases,hardware,engine_hash=campaigns[campaign]
            case=next(c for c in cases if c['id']==case_id)
            raw=next(p for p in case['phases'] if p['phase']==phase)
            parent=case['completed'];provenance=hardware_provenance(hardware,engine_hash,case['threads'])
            log=artifacts/ident/'run.log'
        elif ident.startswith('namd-boundary-fix-20261101/corner_chain/'):
            campaign='namd-boundary-fix-20261101';case_id,phase=ident[len(campaign+'/corner_chain/'):].split('/',1)
            if campaign not in campaigns:
                root=artifacts/campaign
                campaigns[campaign]=(read(root/'corner_chain/results.json'),read(root/'local_hardware.json'),read(root/'protocol.json')['namd_sha256'])
            cases,hardware,engine_hash=campaigns[campaign];case=next(c for c in cases if c['id']==case_id)
            raw=next(p for p in case['phases'] if p['phase']==phase)
            parent=case['completed'];provenance=hardware_provenance(hardware,engine_hash,case['threads'])
            log=artifacts/ident/'run.log'
        elif '/' not in ident:
            root=artifacts/'namd-resource-uncertainty-20261101'
            raw=next((r for r in read(root/'repeat_results.json') if r['id']==ident),{})
            hardware=read(root/'repeat_hardware.json')
            provenance=hardware_provenance(hardware,hardware.get('engine_sha256'),raw.get('threads'))
            log=root/'repeats'/ident/'engine/run.log'
        reasons=qualification_reasons(raw,provenance=provenance,engine_sha256=QUALIFIED_ENGINE,
            parent_completed=parent,configuration=conf,log_path=log,
            gpu_names=['NVIDIA GeForce RTX 3080 Ti'],drivers=['580.178.04'],threads=[16,32])
        if reasons:
            excluded.append(dict(id=ident,reasons=reasons,source=str(conf)))
        else:
            accepted.append({**row,'qualification':dict(eligible=True,**provenance,
                policy='matching engine, completed parent/run, clean log, validated outputs and script order')})
    return accepted,excluded


def series_summary(path):
    """Time-weighted launch-to-last-positive sample mean, independently per gauge.

    Missing GPU samples are absent, not zero. No extrapolation beyond the last
    measurement. Startup is included; process disappearance is excluded.
    """
    if not path.exists():
        return {}
    rows = read(path) if path.suffix == '.json' else [json.loads(s) for s in path.read_text().splitlines()]
    result = {}
    for resource in ('ram', 'gpu'):
        points = []
        for row in rows:
            t = row.get('s', row.get('seconds', row.get('t')))
            if resource == 'ram':
                v = row.get('rss_mib')
                if v is None:
                    b = row.get('rss_bytes', row.get('rss'))
                    v = b / 1024**2 if b is not None else None
            else:
                v = row.get('gpu_mib', row.get('gpu_process_mib'))
            if t is not None and v is not None:
                points.append((t, v))
        positive = [i for i, (_, v) in enumerate(points) if v > 0]
        if positive:
            points = points[:positive[-1] + 1]
        if len(points) >= 2 and points[-1][0] > points[0][0]:
            result[resource] = summarize_series(points, warmup_s=0)
    return result


def error_summary(rows):
    if not rows:
        return None
    errors = np.array([r['error_pct'] for r in rows])
    return dict(cases=len(rows), median_absolute_pct=float(np.median(abs(errors))),
                p95_absolute_pct=float(np.percentile(abs(errors), 95)),
                maximum_absolute_pct=float(max(abs(errors))),
                minimum_signed_pct=float(min(errors)), maximum_signed_pct=float(max(errors)),
                underpredicted=int(sum(errors < 0)), overpredicted=int(sum(errors > 0)))


def fit_models(rows, old):
    """One physically motivated extra term: patch count for offload only.

    Fit only the eligible current cohort. Resident patch-count coefficient stays
    zero: the same feature worsened its held-group maximum.
    Entire geometry groups are held out together, including both profiles.
    """
    model = json.loads(json.dumps(old))
    model['basis'] = 'origami-20261102-qualified-success-expected-v3'
    model['features'] = model['features'][:7]+['thousand_patches']
    model['qualified_engine_sha256'] = QUALIFIED_ENGINE
    model['evidence_policy'] = 'Only matching-engine, cleanly completed runs and complete parent chains with validated outputs; exclusions retained separately.'
    model['estimate_kind'] = 'expected_process_peak'
    validation = []
    for mode in ('resident', 'offload'):
        group = [r for r in rows if r['mode'] == mode]
        x = np.array([r['x'][:7] + [math.prod(r['features']['neighbor']['grid']) / 1000] for r in group])
        used = 7 if mode == 'resident' else 8
        fit = model['modes'][mode]
        fit['training_cases'] = len(group)
        fit['feature_ranges'] = [[float(c.min()), float(c.max())] for c in x.T]
        fit['validation'] = {}
        for resource in ('ram', 'gpu'):
            actual = np.array([r[resource] for r in group])
            pme = np.array([r['pme'] if resource == 'gpu' else 0 for r in group])
            y = actual - pme
            def coefficients(train):
                a = x[train, :used]
                scale = np.maximum(a.max(axis=0), 1)
                w = 1 / actual[train]
                b = nnls(a / scale * w[:, None], y[train] * w)[0] / scale
                return np.pad(b, (0, 8 - used))
            fit[resource] = coefficients(np.ones(len(group), dtype=bool)).tolist()
            held_rows = []
            for held in sorted({r['group'] for r in group}):
                train = np.array([r['group'] != held for r in group])
                beta = coefficients(train)
                for i in np.where(~train)[0]:
                    predicted = float(x[i] @ beta + pme[i])
                    held_rows.append(dict(id=group[i]['id'], mode=mode, resource=resource,
                        group=held, actual_mib=float(actual[i]), expected_mib=predicted,
                        error_pct=100 * (predicted / actual[i] - 1)))
            fit['validation'][resource] = dict(method='leave-one-geometry-group-out', **error_summary(held_rows))
            validation.extend(held_rows)
    model['scope'] = 'Single qualified GPU/build/driver; expected process peaks, never time averages or admission bounds. Patch count applies only to offload. Empirical profile effects remain; geometry-held-out errors are not statistical coverage guarantees.'
    return model, validation


def predict(row, model, resource):
    x = row['x'][:7] + [math.prod(row['features']['neighbor']['grid']) / 1000]
    return sum(a*b for a, b in zip(x, model['modes'][row['mode']][resource])) + (row['pme'] if resource == 'gpu' else 0)


def configuration_features(conf, threads):
    """Offline descriptive comparison; current helper identity is not archive provenance."""
    from backend.core.namd_resources import configuration_memory
    from backend.core.namd_allocation_model import prepared_allocation
    estimate = configuration_memory(conf, threads=threads, detailed=False)
    opts = {}; variables = {}
    for line in conf.read_text().splitlines():
        p = shlex.split(line, comments=True)
        if len(p) < 2:
            continue
        if p[0].lower() == 'set' and len(p) == 3:
            variables[p[1]] = p[2]
        value = ' '.join(p[1:])
        for k, v in variables.items():
            value = value.replace('${'+k+'}', v).replace('$'+k, v)
        opts[p[0].lower()] = value
    box = [float(opts['cellbasisvector'+str(i)].split()[i-1]) for i in (1, 2, 3)]
    if 'extendedsystem' in opts and (conf.parent / opts['extendedsystem']).exists():
        data = [s.split() for s in (conf.parent / opts['extendedsystem']).read_text().splitlines()
                if s.strip() and not s.startswith('#')][-1]
        box = [float(data[i]) for i in (1, 5, 9)]
    detail = prepared_allocation(conf, opts, box, estimate, threads=threads)
    if 'neighbor' not in detail or 'expected_mib' not in detail.get('pme', {}):
        raise ValueError(str(detail))
    n = estimate.atoms / 1e6
    x = [1, n, estimate.components['host']['restraints_mib']*1024**2/192/1e6,
         detail['neighbor']['spatial_tile_pair_capacity_mib'],
         n*max(0, (float(opts.get('pairlistdist', 13.5))/13.5)**3-1),
         n if float(opts.get('timestep', 1)) >= 3 else 0,
         n if opts.get('constraints', 'off').lower() in ('on', 'yes', 'true', '1') else 0]
    return dict(x=x, features=detail, pme=detail['pme']['expected_mib'],
                mode='resident' if estimate.gpu_resident else 'offload',
                admission=dict(ram=estimate.ram_mib, gpu=estimate.gpu_mib),
                supported=estimate.supported, limitations=estimate.limitations)


def collect(artifacts, output):
    source_rows = read(output/'frozen_features.json')['rows']
    rows, excluded = qualified_feature_rows(artifacts, source_rows)
    if not rows:raise ValueError('No qualified completed engine observations remain')
    old = read(output/'baseline/backend/data/namd_resource_expected.json')
    model, cv = fit_models(rows, old)
    write(output/'features.json', dict(rows=rows,excluded=excluded,
        qualification_policy=model['evidence_policy']))
    write(output/'candidate_model.json', model)
    write(output/'cross_validation.json', cv)
    cases = []
    for row in rows:
        ident = row['id']
        base = (artifacts/ident if '/' in ident else
                artifacts/'namd-resource-uncertainty-20261101/repeats'/ident/'engine')
        cases.append(dict(**row, cohort='fitted', samples=series_summary(base/'samples.jsonl')))
    # No run-time engine receipt was retained for these old probes. A cuFFT
    # sizing-helper manifest is not a substitute for the executed engine identity.
    for filename in ('probe_results.json', 'control_results.json'):
        for raw in read(artifacts/'namd-resource-refinement-20261101'/filename):
            excluded.append(dict(id='later/'+raw['id'],reasons=['missing contemporaneous run-time engine identity'],
                                 source=str(artifacts/'namd-resource-refinement-20261101'/filename)))
    for raw in read(artifacts/'namd-resource-probes-20261031/results.json'):
        excluded.append(dict(id=raw['id'],reasons=['missing contemporaneous engine identity'],
                             source=str(artifacts/'namd-resource-probes-20261031/results.json')))
    for raw in read(artifacts/'namd-qualification-20261101/local_results.json'):
        if raw.get('kind')=='long':
            excluded.append(dict(id=raw['id'],reasons=['failed run; post-run script error'],
                                 source=str(artifacts/'namd-qualification-20261101/local_results.json')))
    boundary_root=artifacts/'namd-boundary-fix-20261101'
    hardware=read(boundary_root/'local_hardware.json');engine_hash=read(boundary_root/'protocol.json')['namd_sha256']
    for raw in read(boundary_root/'local_results.json'):
        base=boundary_root/'local'/raw['id'];conf=base/'probe.conf'
        provenance=hardware_provenance(hardware,engine_hash,raw['threads'])
        reasons=qualification_reasons(raw,provenance=provenance,engine_sha256=QUALIFIED_ENGINE,
            configuration=conf,log_path=base/'engine/run.log',gpu_names=old['qualified_gpu_names'],
            drivers=old['qualified_drivers'],threads=old['qualified_threads'])
        if reasons:
            excluded.append(dict(id=raw['id'],reasons=reasons,source=str(base)))
            continue
        cache=output/'features'/f"{raw['id']}.json";cache.parent.mkdir(exist_ok=True)
        if cache.exists():detail=read(cache)
        else:
            detail=configuration_features(conf,raw['threads']);write(cache,detail)
        cases.append(dict(id=raw['id'],family='cube20',ram=raw['peak_rss_mib'],gpu=raw['gpu_peak_mib'],
            cohort='boundary_validation',qualification=dict(eligible=True,**provenance),
            samples=series_summary(base/'engine/samples.jsonl'),**detail))
    # Fresh smoke/qualification runs must supply their actual launch-time receipt.
    for path in sorted((output/'engine').glob('*/result.json')):
        raw=read(path);conf=path.parent/'probe.conf';receipt=read(path.parent/'resources.json')
        gpu=receipt.get('gpu') or {}
        provenance=dict(engine_sha256=receipt['engine'].get('sha256'),gpu=gpu.get('name'),
                        driver=gpu.get('driver'),threads=receipt['threads'])
        reasons=qualification_reasons(raw,provenance=provenance,engine_sha256=QUALIFIED_ENGINE,
            configuration=conf,log_path=path.parent/'run.log',gpu_names=old['qualified_gpu_names'],
            drivers=old['qualified_drivers'],threads=old['qualified_threads'])
        if reasons:
            excluded.append(dict(id='current/'+raw['id'],reasons=reasons,source=str(path)))
            continue
        detail=read(path.parent/'features.json')
        cases.append(dict(id='current/'+raw['id'],family=raw['family'],ram=raw['peak_rss_mib'],
            gpu=raw['gpu_peak_mib'],cohort='current_validation',qualification=dict(eligible=True,**provenance),
            samples=series_summary(path.parent/'samples.jsonl'),**detail))
    audits=[]
    for row in cases:
        for resource in ('ram','gpu'):
            actual=row[resource]
            for version,fit in [('before',old),('after',model)]:
                predicted=predict(row,fit,resource)
                audits.append(dict(id=row['id'],group=row.get('group',row.get('family')),cohort=row['cohort'],
                    mode=row['mode'],resource=resource,version=version,actual_mib=actual,
                    expected_mib=predicted,error_pct=100*(predicted/actual-1)))
    write(output/'exclusions.json',excluded)
    write(output/'engine_cases.json',cases)
    write(output/'prediction_errors.json',audits)
    write(output/'fit_comparison.json',dict(before_model_basis=old['basis'],
        new_validation={k:v['validation'] for k,v in model['modes'].items()},
        cohorts={cohort:{version:{resource:error_summary([r for r in audits if
            r['cohort']==cohort and r['version']==version and r['resource']==resource])
            for resource in ('ram','gpu')} for version in ('before','after')}
            for cohort in sorted({r['cohort'] for r in audits})}))


def scheduling_review(output):
    pairs=[]
    for filename,label in [('results.json','simultaneous arrival'),('late_results.json','playback during health peak')]:
        path=output/'scheduling'/filename
        if not path.exists():continue
        rows=read(path)
        for family in sorted({r['family'] for r in rows}):
            control=next(r for r in rows if r['family']==family and r['mode'].startswith('concurrent'))
            scheduled=next(r for r in rows if r['family']==family and r['mode'].startswith('scheduled'))
            for r in (control,scheduled):
                if r['returncode'] or not r['worker']['completed'] or any(r['events'].values()) or r['swap_peak_bytes']:
                    raise ValueError('Scheduling measurement failed or was pressure-censored: '+r['mode'])
            same=all(control['worker'][k]==scheduled['worker'][k] for k in ('body_sha256','health'))
            if not same:raise ValueError('Scheduling changed playback or health outputs')
            active=0;maximum=0
            for e in sorted(scheduled['worker']['events'],key=lambda e:e['s']):
                if e['event']=='start':active+=1;maximum=max(active,maximum)
                elif e['event']=='end':active-=1
            if active or maximum!=1:raise ValueError('Trajectory scheduling did not serialize operations')
            old=control['tree_rss_peak_mib'];new=scheduled['tree_rss_peak_mib']
            pairs.append(dict(family=family,scenario=label,control_peak_mib=old,scheduled_peak_mib=new,
                saved_mib=old-new,reduction_pct=100*(1-new/old),
                control_s=control['worker']['operation_s'],scheduled_s=scheduled['worker']['operation_s'],
                identical_outputs=same,maximum_active=maximum,source=str(path)))
    return pairs


def build_report(artifacts, output):
    from backend.core.namd_resources import (health_memory_mib, health_expected_mib,
        preparation_memory_mib, preparation_expected_mib)
    cases = read(output/'engine_cases.json')
    errors = read(output/'prediction_errors.json')
    comparisons = read(output/'fit_comparison.json')
    summaries = []
    groups = defaultdict(list)
    for row in cases:
        groups[(row['cohort'], row.get('family', row.get('group')), row.get('mode'))].append(row)
    for (cohort, family, mode), rows in groups.items():
        result = dict(cohort=cohort, family=family, mode=mode, cases=len(rows), resources={})
        for resource in ('ram', 'gpu'):
            measured = [r['samples'][resource] for r in rows if resource in r.get('samples', {})]
            duration = sum(s['observed_s'] for s in measured)
            result['resources'][resource] = dict(mean_stage_peak_mib=float(np.mean([r[resource] for r in rows])),
                maximum_mib=max(r[resource] for r in rows),
                time_mean_mib=sum(s['mean_mib']*s['observed_s'] for s in measured)/duration if duration else None,
                sampled_runs=len(measured), observed_s=duration)
        summaries.append(result)

    auxiliary = []
    optimization = artifacts/'namd-ram-optimization-20261102'
    previous = read(optimization/'report.json')
    for pair in previous['pairs']:
        mode = pair['mode']; raw = pair['after']; worker = raw['worker']
        if mode.startswith('health_'):
            family = mode.removeprefix('health_').removesuffix('_full')
            atoms = read(artifacts/f'namd-resource-probes-20261031/{family}_late_fast/trial.json')['n_atoms']
            expected = health_expected_mib(atoms); budget = health_memory_mib(atoms)
            old_budget = math.ceil(512 + atoms/1e6*1200)
            kind = 'health'; bonds = None
        elif mode.startswith('prep_'):
            family = 'cube31'; atoms = worker['atoms']; kind = 'preparation'
            bonds = max((sum(1 for line in p.open() if line.split()[:1]==['bond'])
                         for p in Path(worker['package']).glob('*.extra')), default=0)
            expected = preparation_expected_mib(atoms, extra_bonds=bonds)
            budget = preparation_memory_mib(atoms, extra_bonds=bonds)
            old_budget = math.ceil(1024 + atoms/1e6*1600 + bonds*192/1024**2)
        else:
            # Cache costs have a different independent variable (frames/output
            # atoms). Do not retrofit them to the health/engine atom formula.
            auxiliary.append(dict(id=mode, kind='analysis_cache', peak_mib=pair['peak_after_mib'],
                samples=series_summary(optimization/raw['stage']/mode/'samples.jsonl'),
                estimate=None, note='Separate response/frame budget; not an engine or health allocation.'))
            continue
        auxiliary.append(dict(id=mode, family=family, kind=kind, atoms=atoms, extra_bonds=bonds,
            peak_mib=pair['peak_after_mib'], expected_mib=expected, budget_mib=budget, old_budget_mib=old_budget,
            error_pct=100*(expected/pair['peak_after_mib']-1),
            samples=series_summary(optimization/raw['stage']/mode/'samples.jsonl')))
    fresh = []
    for path in sorted((output/'current').glob('*/result.json')):
        raw = read(path); w = raw['worker']; fresh.append(raw)
        if raw['returncode'] or not w['completed']:
            continue
        atoms = w['atoms']; bonds = w['extra_bonds']; peak = max(raw['sampled_tree_rss_mib'], w['peak_rss_mib'])
        expected = preparation_expected_mib(atoms, extra_bonds=bonds)
        auxiliary.append(dict(id=w['mode'], family=w['family'], kind='preparation', atoms=atoms,
            extra_bonds=bonds, peak_mib=peak, expected_mib=expected,
            budget_mib=preparation_memory_mib(atoms, extra_bonds=bonds),
            old_budget_mib=math.ceil(1024+atoms/1e6*1600+bonds*192/1024**2),
            error_pct=100*(expected/peak-1), samples=series_summary(path.parent/'samples.jsonl')))
    # Leave a complete family out of these very small auxiliary fits. These
    # errors describe the pilot, not statistical coverage of arbitrary chemistry.
    auxiliary_cv = []
    for kind in ('health', 'preparation'):
        rows = [r for r in auxiliary if r['kind']==kind]
        x = np.array([[1, r['atoms']/1e6]+([r['extra_bonds']/1e6] if kind=='preparation' else []) for r in rows])
        y = np.array([r['peak_mib'] for r in rows])
        for family in sorted({r['family'] for r in rows}):
            train = np.array([r['family']!=family for r in rows])
            b = nnls(x[train]/y[train,None], np.ones(sum(train)))[0]
            for i in np.where(~train)[0]:
                auxiliary_cv.append(dict(id=rows[i]['id'], kind=kind, held_family=family,
                    error_pct=100*(float(x[i]@b)/y[i]-1)))

    refined_gpu = {r['id']:r['candidate_budget'] for r in read(artifacts/'namd-resource-refinement-20261101/pme_admission_candidate_audit.json')}
    admission = []
    for r in cases:
        budget = r.get('admission')
        if r['cohort']=='fitted':
            budget = dict(ram=r['old_ram'], gpu=refined_gpu.get(r['id'],r['old_gpu']))
        if budget:
            for resource in ('ram','gpu'):
                admission.append(dict(id=r['id'], cohort=r['cohort'], resource=resource,
                    actual_mib=r[resource], budget_mib=budget[resource], ratio=r[resource]/budget[resource]))
    # Cloud observations retain their hardware scope and the prior audited
    # resolved-PME ceilings. Do not feed another GPU into the local residual fit.
    cloud = [];cloud_root=artifacts/'namd-boundary-fix-20261101'
    raw_cloud={r['id']:r for r in read(cloud_root/'combined_cloud/cloud_results.json')}
    engine_hash=read(cloud_root/'protocol.json')['namd_sha256'];excluded=read(output/'exclusions.json')
    for item in read(artifacts/'namd-resource-refinement-20261101/cloud_pme_admission_audit.json'):
        raw=raw_cloud[item['id']];directory=(cloud_root/'combined_cloud/results'/item['id']).resolve()
        hardware=read(directory.parents[1]/'hardware.json')
        provenance=hardware_provenance(hardware,engine_hash,raw['threads'])
        component=raw.get('components',{}).get('namd',{})
        checked={**raw,'returncode':component.get('returncode')}
        reasons=qualification_reasons(checked,provenance=provenance,engine_sha256=QUALIFIED_ENGINE,
            configuration=directory/'probe.conf',log_path=directory/'namd.log')
        if len(raw.get('components',{}))>1:
            reasons.append('overlap includes a superseded analysis implementation')
        if reasons:
            excluded.append(dict(id='cloud/'+item['id'],reasons=reasons,source=str(directory)))
            continue
        cloud.append(item)
        admission.append(dict(id=item['id'],cohort='cloud_boundary',resource='gpu',actual_mib=item['actual_gpu'],
            budget_mib=item['new_budget'],ratio=item['ratio']))
        peak=max(component.get('peak_rss_mib',0),component.get('time_peak_rss_mib',0))
        budget=raw['estimate']['ram_mib']
        admission.append(dict(id=item['id'],cohort='cloud_boundary',resource='ram',actual_mib=peak,
            budget_mib=budget,ratio=peak/budget))
    write(output/'exclusions.json',excluded)
    notes = [
        'Only matching-engine, successful runs with clean termination, validated output and complete parent chains contribute to current fits or checks. Old/unprovenanced/failed runs are listed in exclusions.json without contributing averages, extrema or pass counts.',
        'Mean stage peak is the arithmetic mean of measured per-run maxima. Time mean uses elapsed-time-weighted samples from launch to the last positive process observation, including startup. Short-run averages are not steady-state requirements; missing GPU samples are never zeros.',
        'RAM and VRAM maxima need not occur together. OS/application memory, file cache and unrelated GPU allocations remain separate.',
        'Current engine identity comes from retained run receipts or contemporaneous campaign launch provenance, never a later sizing-helper manifest. Cloud hardware remains separate from the local residual fit.',
        'The shared-PME experimental binary is excluded from default-engine qualification. Its grid-dependent savings are not silently credited to the installed engine.',
        'New compact preparation and health allowances include headroom beyond observed peaks; fallback allowances remain outside their atom/restraint domain. Their code path is unchanged by this scheduling review.',
        'Geometry groups are held out together, but related stages remain correlated. These engineering checks are not a 99% statistical confidence guarantee.',
    ]
    checks = dict(engine_comparisons=len(cases), excluded_records=len(excluded), fresh_preparations=len(fresh),
        all_fresh_completed=all(r['returncode']==0 and r['worker']['completed'] for r in fresh),
        fresh_limit_events=sum(sum(r['events'].values()) for r in fresh),
        fresh_swap_bytes=sum(r['swap_peak_bytes'] for r in fresh),
        fresh_worker_seconds=sum(r['worker']['elapsed_s'] for r in fresh),
        admission_comparisons=len(admission), admission_underruns=[r for r in admission if r['ratio']>1],
        auxiliary_underruns=[r for r in auxiliary if r.get('budget_mib',float('inf'))<r['peak_mib']],
        cloud_spend_usd=0)
    scheduling=scheduling_review(output)
    checks['fresh_engine_checks']=sum(r['cohort']=='current_validation' for r in cases)
    checks['scheduling_pairs']=len(scheduling)
    write(output/'scheduling_review.json',scheduling)
    test_log=output/'tests.log'
    if test_log.exists():
        checks['tests_summary']=next((line for line in reversed(test_log.read_text().splitlines())
                                      if 'passed' in line),'No completed test result')
    sources = [output/'frozen_features.json', output/'baseline/backend/data/namd_resource_expected.json',
               artifacts/'namd-resource-probes-20261031/results.json', optimization/'report.json',
               REPO/'backend/data/namd_resource_expected.json',REPO/'backend/core/namd_resources.py',
               REPO/'backend/core/namd_allocation_model.py',Path(__file__)]
    provenance = {str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = dict(schema='namd-estimator-review-v3', summaries=summaries, auxiliary=auxiliary,scheduling=scheduling,
        auxiliary_validation={kind:error_summary([r for r in auxiliary_cv if r['kind']==kind]) for kind in ('health','preparation')},
        auxiliary_holdouts=auxiliary_cv, comparisons=comparisons, admission=admission, cloud_boundaries=cloud,
        exclusions=excluded, verification=checks, notes=notes, provenance=provenance)
    write(output/'report.json',report);write(output/'verification.json',checks)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for ax, resource in zip(axes[:2], ('ram','gpu')):
        for mode, color in [('resident','#176d91'),('offload','#c76d29')]:
            selected=[r for r in errors if r['version']=='after' and r['cohort']=='fitted'
                      and r['resource']==resource and r['mode']==mode]
            ax.scatter([r['actual_mib']/1024 for r in selected],
                       [r['expected_mib']/1024 for r in selected],s=14,alpha=.6,label=mode,color=color)
        top=max(r[k]/1024 for r in errors if r['resource']==resource and r['cohort']=='fitted'
                for k in ('actual_mib','expected_mib'))*1.05
        ax.plot([0,top],[0,top],color='#777',ls='--',lw=1)
        ax.set(xlabel='Measured process peak (GiB)',ylabel='Expected process peak (GiB)',
               title=resource.upper()+' · fitted stages',xlim=(0,top),ylim=(0,top))
        ax.grid(alpha=.15);ax.legend()
    selected=[r for r in auxiliary if r['id'] in ('prep_18hb_aksimentiev','prep_3x6hb_fast','health_18hb_full','health_3x6hb')]
    x=np.arange(len(selected));width=.25
    for offset,field,label,color in [(-1,'old_budget_mib','Old allowance','#b7c1ca'),
            (0,'budget_mib','New allowance','#176d91'),(1,'peak_mib','Measured peak','#269a75')]:
        axes[2].barh(x+offset*width,[r[field]/1024 for r in selected],width,label=label,color=color)
    axes[2].set(yticks=x,yticklabels=[r['id'].replace('_',' ') for r in selected],
                xlabel='GiB',title='Compact host stages')
    axes[2].invert_yaxis();axes[2].legend();axes[2].grid(axis='x',alpha=.15)
    fig.suptitle('NAMD estimator review · measured peaks and remaining forecast spread')
    fig.tight_layout();fig.savefig(output/'estimator_comparison.png',dpi=160)
    fig.savefig(output/'estimator_comparison.pdf');plt.close(fig)
    body=['<!doctype html><html><meta charset="utf-8"><title>NAMD memory estimator review</title>',
          '<style>body{font:16px system-ui;max-width:1300px;margin:40px auto;padding:0 24px;color:#183247}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border:1px solid #c6d3dc;text-align:left}th{background:#e6eef4}p,li{line-height:1.5}img{width:100%}</style><body>',
          '<h1>Average usage, measured maxima and estimator errors</h1>',
          '<p>Compact health/preparation budgets updated; offload expected peaks now include patch count. The engine residual model is refitted using only eligible completed chains; admission envelopes remain unchanged.</p>',
          '<p><a href="report.json">Full report</a> · <a href="prediction_errors.json">All prediction errors</a> · <a href="engine_cases.json">Engine measurements and sampled averages</a> · <a href="exclusions.json">Excluded records and reasons</a> · <a href="cross_validation.json">Geometry holdouts</a> · <a href="candidate_model.json">Model</a></p>',
          '<img src="estimator_comparison.png" alt="Expected versus measured engine peaks, and reduced preparation and health allowances">',
          '<h2>Engine measurements (GiB)</h2><p>Each resource column shows time mean / mean stage peak / largest stage peak. Time means include startup; rows without sufficient traces show “—”. Unprovenanced and unsuccessful runs are excluded from these current summaries.</p>',
          '<table><tr><th>Model / cohort / mode</th><th>Runs</th><th>RAM: time mean / mean peak / max</th><th>VRAM: time mean / mean peak / max</th></tr>']
    for s in summaries:
        cells=[]
        for resource in ('ram','gpu'):
            v=s['resources'][resource]
            cells.append(' / '.join('—' if v[k] is None else f'{v[k]/1024:.3f}' for k in ('time_mean_mib','mean_stage_peak_mib','maximum_mib')))
        body.append(f'<tr><td>{html.escape(str(s["family"]))} · {s["cohort"]} · {s["mode"]}</td><td>{s["cases"]}</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>')
    body+=['</table><h2>Cloud extreme cases (GiB)</h2><p>Process peaks on the separately qualified cloud hardware; these do not train the local expected-usage model. Superseded analysis-overlap runs are excluded.</p>',
           '<table><tr><th>Case</th><th>RAM peak / allowance</th><th>VRAM peak / allowance</th></tr>']
    cloud_ram={r['id']:r for r in admission if r['cohort']=='cloud_boundary' and r['resource']=='ram'}
    for c in cloud:
        h=cloud_ram.get(c['id'])
        ram=f'{h["actual_mib"]/1024:.3f} / {h["budget_mib"]/1024:.3f}' if h else '—'
        body.append(f'<tr><td>{c["id"]}</td><td>{ram}</td><td>{c["actual_gpu"]/1024:.3f} / {c["new_budget"]/1024:.3f}</td></tr>')
    body+=['</table><h2>Optimized host stages (MiB)</h2><table><tr><th>Case</th><th>Measured peak</th><th>Expected peak</th><th>Old → new allowance</th><th>Expected error</th></tr>']
    for r in auxiliary:
        error=f'{r["error_pct"]:+.1f}%' if 'error_pct' in r else '—'
        body.append(f'<tr><td>{r["id"]}</td><td>{r["peak_mib"]:.1f}</td><td>{r.get("expected_mib","Separate budget")}</td><td>{r.get("old_budget_mib","—")} → {r.get("budget_mib","—")}</td><td>{error}</td></tr>')
    body+=['</table><h2>Remaining largest expected-peak errors</h2><table><tr><th>Cohort</th><th>Resource</th><th>Direction</th><th>Case</th><th>Error</th></tr>']
    for cohort in sorted({r['cohort'] for r in errors}):
        for resource in ('ram','gpu'):
            group=[r for r in errors if r['cohort']==cohort and r['resource']==resource and r['version']=='after']
            for direction, key in [('Lowest',min),('Highest',max)]:
                r=key(group,key=lambda r:r['error_pct'])
                body.append(f'<tr><td>{cohort}</td><td>{resource}</td><td>{direction}</td><td>{html.escape(r["id"])}</td><td>{r["error_pct"]:+.2f}%</td></tr>')
    body+=['</table><h2>Trajectory scheduling (MiB)</h2><p>Current algorithms and identical inputs; combined parent/worker RSS sampled every 10 ms. A simulation scheduling lease prevents unrelated bulk work, but no engine runs during these probes. Playback bytes and health results must match exactly. These CPU operations do not measure a VRAM reduction.</p>',
           '<table><tr><th>Family / arrival scenario</th><th>Concurrent → scheduled peak</th><th>RAM reduction</th><th>Batch seconds</th></tr>']
    for r in scheduling:
        body.append(f'<tr><td>{r["family"]} · {r["scenario"]}</td><td>{r["control_peak_mib"]:.1f} → {r["scheduled_peak_mib"]:.1f}</td><td>{r["saved_mib"]:.1f} MiB ({r["reduction_pct"]:.1f}%)</td><td>{r["control_s"]:.2f} → {r["scheduled_s"]:.2f}</td></tr>')
    body+=['</table><h2>Validation and limits</h2><pre>'+html.escape(json.dumps(checks,indent=2))+'</pre>',
           '<ul>'+''.join('<li>'+html.escape(n)+'</li>' for n in notes)+'</ul>',
           '<p>Reproduce with <code>.venv/bin/python scripts/validation/namd_estimator_audit.py --output '+html.escape(str(output))+'</code>. Cached prepared features avoid repeating coordinate/FFT sizing. Raw observations are never rewritten.</p></body></html>']
    (output/'report.html').write_text('\n'.join(body))
    print(json.dumps(checks,indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, default=REPO/'.development-artifacts')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    collect(args.artifacts, args.output)
    build_report(args.artifacts, args.output)


if __name__ == '__main__':
    main()
