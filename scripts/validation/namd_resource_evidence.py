"""Replay archived NAMD resource evidence with explicitly separated memory scopes.

Usage: python scripts/validation/namd_resource_evidence.py --output DIR
Reads original artifacts; never rewrites forecasts or launches a simulation.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.core.namd_measurements import normalize_measurement, qualification_reasons
from backend.core.namd_allocation_model import QUALIFIED_ENGINE


def read(path):
    return json.loads(path.read_text())


def provenance(path, hardware, engine_hash=None):
    text = hardware.get('gpu','').strip().splitlines()
    fields = [x.strip() for x in text[-1].split(',')] if text else []
    driver = next((x for x in fields[1:] if x.count('.')==2 and 'MiB' not in x),None)
    return dict(source=str(path.resolve()),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        gpu=fields[0] if fields else None,driver=driver,engine_sha256=engine_hash,
        gpu_sampling_period_s=hardware.get('gpu_sampling_period_s'))


def qualify(out, raw, *, parent=True, configuration=None, log_path=None):
    proof={**out['provenance'],'threads':raw.get('threads')}
    checked={**raw}
    if 'namd' in (raw.get('components') or {}):
        checked['returncode']=raw['components']['namd'].get('returncode')
    reasons=qualification_reasons(checked,provenance=proof,engine_sha256=QUALIFIED_ENGINE,
        parent_completed=parent,configuration=configuration,log_path=log_path)
    if out['kind']!='engine':
        reasons.append('superseded host implementation; use current host-stage qualification')
    out['qualification']={'eligible':not reasons,'reasons':reasons}
    out['comparable_engine_gpu'] &= not reasons
    return out


def boundary_rows(artifacts):
    root = artifacts/'namd-boundary-fix-20261101'
    protocol = read(root/'protocol.json')
    engine_hash = protocol['namd_sha256']
    local_hw = read(root/'local_hardware.json')
    rows = []
    for raw in read(root/'combined_cloud/cloud_results.json'):
        source = (root/'combined_cloud/results'/raw['id']/'result.json').resolve()
        hardware_path = source.parents[2]/'hardware.json'
        hardware = read(hardware_path) if hardware_path.exists() else {}
        kind = 'overlap' if 'analysis' in (raw.get('components') or {}) else 'engine'
        out = normalize_measurement(raw,kind=kind,legacy_gpu_scope='device',
            provenance=provenance(source,hardware,engine_hash))
        qualify(out,raw,configuration=source.parent/'probe.conf',log_path=source.parent/'namd.log')
        out['campaign']='boundary-cloud'; rows.append(out)
    for raw in read(root/'local_results.json'):
        source=root/'local'/raw['id']/'result.json'
        out=normalize_measurement(raw,legacy_gpu_scope='process',
            provenance=provenance(source,local_hw,engine_hash))
        qualify(out,raw,configuration=source.parent/'probe.conf',log_path=source.parent/'engine/run.log')
        out['campaign']='boundary-local';rows.append(out)
    source=root/'corner_chain/results.json'
    for chain in read(source):
        for phase in chain['phases']:
            kind={'prep':'preparation','health':'health','references':'reference'}.get(phase['phase'],'engine')
            raw={**phase,'id':chain['id']+'/'+phase['phase'],'profile':chain['profile'],
                'atoms':chain['prepared']['atoms'],'threads':chain['threads']}
            out=normalize_measurement(raw,kind=kind,legacy_gpu_scope='process',
                provenance=provenance(source,local_hw,engine_hash))
            directory=root/'corner_chain'/chain['id']/phase['phase']
            qualify(out,raw,parent=chain['completed'],log_path=directory/'run.log')
            out['campaign']='boundary-chain';rows.append(out)
    for filename,kind in [('fresh_cube31/prep/result.json','preparation'),('reference_result.json','reference')]:
        source=root/filename
        out=normalize_measurement(read(source),kind=kind,legacy_gpu_scope='process',
            provenance=provenance(source,local_hw,engine_hash))
        qualify(out,read(source))
        out['campaign']='boundary-'+kind;rows.append(out)
    return rows


def initial_rows(artifacts):
    root=artifacts/'namd-resource-probes-20261031'
    hardware=read(root/'environment.json')
    # This archive retains the binary path, but not a contemporaneous hash. Do
    # not silently substitute the hash of the currently installed executable.
    source=root/'results.json'
    result=[]
    for raw in read(source):
        out=normalize_measurement(raw,legacy_gpu_scope='process',provenance=provenance(source,hardware))
        qualify(out,raw)
        out['campaign']='initial-controlled';out['family']=raw['family'];result.append(out)
    return result


def historical_attempts(artifacts):
    """Preserve failed/skipped pre-fix attempts separately from current budgets.

    Retain successful attempts from that campaign too, so this inventory is not
    selected by outcome. The parent result already includes its engine record.
    """
    root=artifacts/'namd-boundary-stage-20261101'
    engine_hash=read(root/'protocol.json')['namd_sha256']
    paths=list((root/'local').glob('*/result.json'))
    paths+=list((root/'cloud_8/extracted/results').glob('*/result.json'))
    paths+=list(root.glob('excluded_*/result.json'))
    rows=[]
    for path in sorted(paths):
        raw=read(path);cloud='cloud_8' in path.parts
        hardware=read(root/'cloud_8/extracted/hardware.json') if cloud else {}
        kind='overlap' if 'analysis' in (raw.get('components') or {}) else 'engine'
        out=normalize_measurement(raw,kind=kind,legacy_gpu_scope='device' if cloud else 'process',
            provenance=provenance(path,hardware,engine_hash))
        out['campaign']='historical-boundary-before-fixes'
        rows.append(out)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts',type=Path,default=ROOT/'.development-artifacts')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    rows=boundary_rows(args.artifacts)+initial_rows(args.artifacts)
    clean=[r for r in rows if r['qualification']['eligible'] and not r['censored']]
    ratios=[r['gpu']['process_ratio'] for r in clean if r['gpu']['process_ratio'] is not None]
    workloads=[r['host']['workload_ratio'] for r in clean if r['host']['workload_ratio'] is not None]
    violations=[dict(campaign=r['campaign'],id=r['id'],resource=kind,ratio=ratio)
        for r in clean for kind,ratio in [('process_gpu',r['gpu']['process_ratio']),('workload_rss',r['host']['workload_ratio'])]]
    violations=[v for v in violations if v['ratio'] is not None and v['ratio']>1]
    spreads=[]
    initial=[r for r in clean if r['campaign']=='initial-controlled']
    for family in sorted({r['family'] for r in initial}):
        group=[r for r in initial if r['family']==family]
        spread={}
        for key,values in [('ram',[r['host']['engine_rss_peak_mib'] for r in group]),('gpu',[r['gpu']['process_peak_mib'] for r in group])]:
            values=[v for v in values if v is not None]
            spread[key]=dict(min_mib=min(values),max_mib=max(values),spread_pct=100*(max(values)/min(values)-1))
        spreads.append(dict(family=family,cases=len(group),**spread))
    history=historical_attempts(args.artifacts)
    excluded=[dict(id=r['id'],campaign=r['campaign'],reasons=r['qualification']['reasons']) for r in rows if not r['qualification']['eligible']]
    report=dict(schema='namd-evidence-audit-v2',rows=clean,excluded=excluded,historical_attempts=history,
        historical_summary=dict(records=len(history),censored=sum(r['censored'] for r in history),
            interpretation='Pre-fix attempts retain their outcomes and original forecasts; excluded from current-budget comparisons.'),
        summary=dict(records=len(clean),excluded=len(excluded),censored=sum(r['censored'] for r in clean),
            comparable_engine_gpu=sum(r['comparable_engine_gpu'] for r in clean),
            gpu_forecast_comparisons=len(ratios),max_process_gpu_ratio=max(ratios,default=None),
            ram_forecast_comparisons=len(workloads),max_workload_ram_ratio=max(workloads,default=None),overruns=violations),
        controlled_profile_and_checkpoint_spreads=spreads,
        interpretation='Configuration/state spreads are not repeated-identical-run variance. Missing binary provenance excludes old controlled records from cross-build calibration. No statistical confidence level is inferred.')
    (args.output/'normalized_measurements.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('summary','controlled_profile_and_checkpoint_spreads')},indent=2))


if __name__=='__main__':
    main()
