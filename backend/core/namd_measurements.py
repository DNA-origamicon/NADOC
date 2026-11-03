"""Normalize resource evidence without conflating process, workflow and device peaks.

This is offline evidence processing, not a launch-time estimator. A sampled peak
is an observation, never a guarantee that a shorter allocation was not missed.
"""
import math


def receipt_qualification(raw, directory, *, engine_sha256):
    """Strict qualification for standalone probes with a launch-time receipt."""
    import json
    from pathlib import Path
    directory=Path(directory)
    path=directory/'resources.json'
    if not path.exists():
        return ['missing contemporaneous resource receipt']
    try:
        receipt=json.loads(path.read_text());gpu=receipt.get('gpu') or {}
        proof=dict(engine_sha256=receipt['engine']['sha256'],gpu=gpu.get('name'),
                   driver=gpu.get('driver'),threads=receipt['threads'])
        checked={**raw,'executed_configuration_sha256':receipt['configuration']['sha256']}
    except (OSError,ValueError,KeyError,TypeError):
        return ['invalid resource receipt']
    log=directory/'run.log'
    if not log.exists():log=directory/'engine/run.log'
    reasons=qualification_reasons(checked,provenance=proof,engine_sha256=engine_sha256,
        configuration=directory/'probe.conf',log_path=log)
    if receipt.get('errors') or receipt.get('missing_provenance'):
        reasons.append('incomplete resource receipt')
    return reasons


def qualification_reasons(raw, *, provenance, engine_sha256, parent_completed=True,
                          configuration=None, log_path=None, gpu_names=None,
                          drivers=None, threads=None, require_outputs=True):
    """Fail closed before a measurement enters a current fit or pass/fail count.

    Historical successes are usable only with a contemporaneously recorded
    matching engine identity. A later helper/binary hash is not run provenance.
    Parent failure excludes even successful prefix stages from qualification.
    """
    from backend.core.namd_script import validate_static_order, log_completed
    reasons = []
    if raw.get('completed') is not True or raw.get('returncode') != 0:
        reasons.append('run did not complete successfully')
    if parent_completed is not True:
        reasons.append('parent run/chain did not complete successfully')
    if not provenance.get('engine_sha256'):
        reasons.append('missing contemporaneous engine identity')
    elif provenance['engine_sha256'] != engine_sha256:
        reasons.append('obsolete or unqualified engine identity')
    for key, allowed in [('gpu',gpu_names),('driver',drivers),('threads',threads)]:
        value=provenance.get(key)
        if value is None or value == '':
            reasons.append('missing recorded '+key)
        elif allowed is not None and value not in allowed:
            reasons.append('unqualified '+key)
    if any(raw.get(k) for k in ('guard','guard_stop','skipped_reason','errors','validation_error')):
        reasons.append('run was guarded, skipped or reported errors')
    if (raw.get('gpu_sampling') or {}).get('errors'):
        reasons.append('GPU sampling reported errors')
    group=raw.get('cgroup') or {}
    try:
        events=dict(line.split() for line in str(group.get('memory.events','')).splitlines())
        if any(int(events.get(k,0)) for k in ('high','max','oom','oom_kill','oom_group_kill')) or int(group.get('memory.failcnt',0)):
            reasons.append('memory-limit pressure affected the observation')
    except (ValueError,TypeError):
        reasons.append('invalid memory-limit event record')
    outputs = raw.get('output_validation')
    if require_outputs and not outputs:
        reasons.append('missing successful output validation')
    elif outputs and (not isinstance(outputs, dict) or any(
            outputs.get(k) is False for k in ('verified','passed','completed'))
            or outputs.get('error') or outputs.get('errors')):
        reasons.append('output validation failed')
    if configuration is not None:
        try:
            from pathlib import Path
            import hashlib
            content=Path(configuration).read_bytes()
            validate_static_order(content.decode())
            recorded=next((raw[k] for k in ('executed_configuration_sha256','local_config_sha256',
                          'config_sha256','conf_sha256') if raw.get(k)),None)
            if recorded and hashlib.sha256(content).hexdigest()!=recorded:
                reasons.append('executed configuration identity mismatch')
        except (OSError,ValueError) as exc:
            reasons.append('unqualified configuration: '+str(exc))
    if log_path is not None and not log_completed(log_path):
        reasons.append('log lacks clean normal termination')
    return reasons


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _maximum(*values):
    numbers = [n for v in values if (n := _number(v)) is not None]
    return max(numbers) if numbers else None


def normalize_measurement(raw, *, provenance, kind='engine', legacy_gpu_scope=None):
    """Require an explicit scope before interpreting a legacy GPU peak.

    ``provenance`` is supplied from the retained campaign metadata, not today's
    installed binaries/hardware. Unknown fields stay unknown. Separate component
    maxima cannot be added to obtain a simultaneous workflow peak.
    """
    if kind not in ('engine', 'overlap', 'preparation', 'health', 'reference'):
        raise ValueError('Unknown measurement workload')
    if legacy_gpu_scope not in (None, 'process', 'device'):
        raise ValueError('GPU scope must be process, device or unknown')
    sampling = raw.get('gpu_sampling') or {}
    components = raw.get('components') or {}
    namd = components.get('namd') or {}
    analysis = components.get('analysis') or {}
    generic_rss = _maximum(raw.get('peak_ram_mib'), raw.get('peak_rss_mib'),
                           raw.get('max_rss_mib'), raw.get('observed_hwm_mib'),
                           raw.get('sampled_tree_rss_mib'))
    engine_rss = _maximum(namd.get('peak_rss_mib'), namd.get('time_peak_rss_mib'))
    if engine_rss is None and kind == 'engine':
        engine_rss = generic_rss
    analysis_rss = _maximum(analysis.get('peak_rss_mib'), analysis.get('time_peak_rss_mib'))
    workload_rss = _maximum(raw.get('simultaneous_rss_mib'), generic_rss)
    # Single-engine component high-water is valid for the workflow too. For an
    # overlap, retain only the recorded simultaneous process-tree observation.
    if kind == 'engine':
        workload_rss = _maximum(workload_rss, engine_rss)

    process_gpu = _number(sampling.get('process_peak_mib'))
    device_gpu = _number(sampling.get('total_peak_mib'))
    legacy_gpu = _number(raw.get('gpu_peak_mib', raw.get('sampled_gpu_peak_mib')))
    if process_gpu is None and legacy_gpu_scope == 'process':
        process_gpu = legacy_gpu
    if device_gpu is None and legacy_gpu_scope == 'device':
        device_gpu = legacy_gpu

    problems = []
    if not raw.get('completed'):
        problems.append('incomplete or failed run')
    if raw.get('guard') or raw.get('guard_stop') or raw.get('skipped_reason'):
        problems.append('guarded or skipped run')
    if raw.get('errors') or raw.get('validation_error') or sampling.get('errors'):
        problems.append('run, validation or sampling errors')
    cgroup = raw.get('cgroup') or {}
    events = {}
    for line in str(cgroup.get('memory.events', '')).splitlines():
        parts = line.split()
        if len(parts) == 2:
            events[parts[0]] = _number(parts[1])
    if any(events.get(k) for k in ('high','max','oom','oom_kill','oom_group_kill')) or _number(cgroup.get('memory.failcnt')):
        problems.append('memory-limit pressure affected the observation')
    if raw.get('returncode') not in (None, 0) or any(c.get('returncode') not in (None,0) for c in components.values()):
        problems.append('nonzero process exit')

    estimate = raw.get('estimate') or {}
    forecast_engine = _number(estimate.get('ram_mib')) if kind in ('engine','overlap') else None
    forecast_workload = _number(raw.get('predicted_ram_mib', estimate.get('ram_mib')))
    forecast_gpu = _number(estimate.get('gpu_mib'))
    ratio = lambda value, budget: value/budget if value is not None and budget else None
    missing = [k for k in ('engine_sha256','gpu','driver') if not provenance.get(k)] if kind in ('engine','overlap') else []
    return dict(schema='namd-resource-observation-v1', id=raw.get('id',raw.get('phase')),
        kind=kind, atoms=raw.get('atoms',raw.get('n_atoms',estimate.get('atoms'))),
        profile=raw.get('profile'), phase=raw.get('phase'), threads=raw.get('threads'),
        elapsed_s=_number(raw.get('elapsed_s')), provenance=dict(provenance),
        config_sha256=raw.get('executed_configuration_sha256',raw.get('local_config_sha256',raw.get('conf_sha256'))),
        host=dict(engine_rss_peak_mib=engine_rss, analysis_rss_peak_mib=analysis_rss,
            workload_rss_peak_mib=workload_rss,
            cgroup_peak_mib=(_number(cgroup.get('memory.peak'))/1024**2 if _number(cgroup.get('memory.peak')) is not None else None),
            cgroup_includes_page_cache=True,
            engine_budget_mib=forecast_engine, workload_budget_mib=forecast_workload,
            engine_ratio=ratio(engine_rss,forecast_engine), workload_ratio=ratio(workload_rss,forecast_workload)),
        gpu=dict(process_peak_mib=process_gpu, device_peak_mib=device_gpu,
            process_budget_mib=forecast_gpu, process_ratio=ratio(process_gpu,forecast_gpu),
            sample_interval_s=_number(sampling.get('interval_s',provenance.get('gpu_sampling_period_s'))),
            samples=sampling.get('samples'), sampled=True),
        censored=bool(problems), censor_reasons=problems, missing_provenance=missing,
        comparable_engine_gpu=kind=='engine' and process_gpu is not None and not problems and not missing,
        uncertainty='Sampled GPU peaks may miss transients. Cgroup memory includes file cache. Independent maxima are not simultaneous peaks.')
