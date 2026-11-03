from backend.core.namd_measurements import normalize_measurement


PROVENANCE = dict(engine_sha256='recorded-build',gpu='recorded-gpu',driver='recorded-driver')


def test_device_total_never_substitutes_for_unknown_engine_usage():
    raw=dict(completed=True,gpu_peak_mib=8000,gpu_sampling={'total_peak_mib':8000},estimate={'gpu_mib':7000})
    result=normalize_measurement(raw,provenance=PROVENANCE,legacy_gpu_scope='device')
    assert result['gpu']['device_peak_mib']==8000
    assert result['gpu']['process_peak_mib'] is None
    assert result['gpu']['process_ratio'] is None
    assert not result['comparable_engine_gpu']


def test_cloud_and_local_process_peaks_have_identical_comparison_scope():
    cloud=dict(completed=True,gpu_peak_mib=8000,gpu_sampling={'process_peak_mib':6000,'total_peak_mib':8000},estimate={'gpu_mib':7000})
    local=dict(completed=True,gpu_peak_mib=6000,gpu_sampling={'total_peak_mib':9000},estimate={'gpu_mib':7000})
    a=normalize_measurement(cloud,provenance=PROVENANCE,legacy_gpu_scope='device')
    b=normalize_measurement(local,provenance=PROVENANCE,legacy_gpu_scope='process')
    assert a['gpu']['process_ratio']==b['gpu']['process_ratio']==6000/7000
    assert a['gpu']['device_peak_mib']!=b['gpu']['device_peak_mib']


def test_overlap_keeps_engine_and_simultaneous_workflow_separate():
    raw=dict(completed=True,components={'namd':{'peak_rss_mib':8000},'analysis':{'peak_rss_mib':3000}},
             simultaneous_rss_mib=9500,predicted_ram_mib=12000,estimate={'ram_mib':9000},
             cgroup={'memory.peak':str(15000*1024**2)})
    out=normalize_measurement(raw,provenance=PROVENANCE,kind='overlap')
    assert out['host']['engine_ratio']==8000/9000
    assert out['host']['workload_ratio']==9500/12000
    assert out['host']['workload_rss_peak_mib']!=11000
    assert out['host']['cgroup_peak_mib']==15000


def test_guarded_or_pressure_limited_run_is_retained_but_censored():
    out=normalize_measurement(dict(completed=True,gpu_peak_mib=5000,cgroup={'memory.events':'high 1\noom_kill 0'}),
                              provenance=PROVENANCE,legacy_gpu_scope='process')
    assert out['censored'] and not out['comparable_engine_gpu']
    assert out['gpu']['process_peak_mib']==5000


def test_unknown_provenance_cannot_become_a_calibration_sample():
    out=normalize_measurement(dict(completed=True,gpu_peak_mib=5000),provenance={},legacy_gpu_scope='process')
    assert not out['censored']
    assert set(out['missing_provenance'])=={'engine_sha256','gpu','driver'}
    assert not out['comparable_engine_gpu']


def test_missing_simultaneous_peak_is_not_invented_from_components():
    raw=dict(completed=True,components={'namd':{'peak_rss_mib':8000},'analysis':{'peak_rss_mib':3000}})
    out=normalize_measurement(raw,provenance=PROVENANCE,kind='overlap')
    assert out['host']['workload_rss_peak_mib'] is None


def test_bad_samples_are_not_treated_as_zero_usage():
    raw=dict(completed=True,gpu_peak_mib=float('nan'),gpu_sampling={'process_peak_mib':-1,'errors':[999]})
    out=normalize_measurement(raw,provenance=PROVENANCE,legacy_gpu_scope='process')
    assert out['censored'] and out['gpu']['process_peak_mib'] is None


def test_reports_exclude_unknown_engine_before_parsing_metrics(tmp_path):
    import json
    from scripts.validation.namd_spike_report import report as spikes
    from scripts.validation.namd_startup_report import report as startup
    directory=tmp_path/'engine'/'unknown';directory.mkdir(parents=True)
    (directory/'result.json').write_text(json.dumps(dict(completed=True,returncode=0)))
    (directory/'samples.jsonl').write_text('not valid measurements')
    result=spikes(tmp_path,tmp_path/'absent')
    assert result['rows']==[]
    assert result['excluded'][0]['reasons']==['missing contemporaneous resource receipt']
    directory=tmp_path/'tests'/'unknown'/'engine';directory.mkdir(parents=True)
    (directory/'result.json').write_text(json.dumps(dict(completed=False,returncode=1)))
    (tmp_path/'plan_results.json').write_text(json.dumps([{'id':'unknown'}]))
    result=startup(tmp_path)
    assert not result['rows'] and len(result['excluded'])==1


def test_launch_receipt_must_match_engine_and_executed_configuration(tmp_path):
    import hashlib,json
    from backend.core.namd_measurements import receipt_qualification
    conf=tmp_path/'probe.conf';conf.write_text('run 10\n')
    (tmp_path/'run.log').write_text('End of program\n')
    receipt=dict(engine={'sha256':'known'},configuration={'sha256':hashlib.sha256(conf.read_bytes()).hexdigest()},
                 gpu={'name':'GPU','driver':'driver'},threads=16)
    (tmp_path/'resources.json').write_text(json.dumps(receipt))
    raw=dict(completed=True,returncode=0,output_validation={'verified':True})
    assert receipt_qualification(raw,tmp_path,engine_sha256='known')==[]
    assert receipt_qualification(raw,tmp_path,engine_sha256='other')==['obsolete or unqualified engine identity']
    conf.write_text('run 20\n')
    assert receipt_qualification(raw,tmp_path,engine_sha256='known')==['executed configuration identity mismatch']
