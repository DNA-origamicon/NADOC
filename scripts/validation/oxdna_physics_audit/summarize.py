"""Consolidate measured results and matching engine/source provenance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
from scipy import stats
from pair_audit import ROOT, ENGINE

reports = {}
for name in ['pair', 'pair_nve', 'thermostat', 'harmonic', 'workflow', 'baseline_interposer']:
    path = ROOT/(name+'_report.json')
    if path.exists():
        reports[name] = json.loads(path.read_text())

summary = []
for method in ['installed_bussi', 'current_K_bussi', 'john']:
    rows = [r for r in reports.get('harmonic', []) if r['name'].endswith(method)]
    if not rows:
        continue
    assert len({r['random_seed'] for r in rows}) == len(rows)
    for key in ['soft_config_T_ratio', 'soft_kinetic_T_ratio',
                'stiff_config_T_ratio', 'stiff_kinetic_T_ratio']:
        x = np.array([r[key] for r in rows])
        interval = stats.t.interval(.95, len(x)-1, loc=x.mean(), scale=stats.sem(x))
        summary.append(dict(method=method, metric=key, n=len(x), mean=float(x.mean()),
            CI95=list(interval), p=float(stats.ttest_1samp(x, 1).pvalue)))
maximum = 0.
for rank, i in enumerate(np.argsort([r['p'] for r in summary])):
    maximum = max(maximum, min(1., (len(summary)-rank)*summary[i]['p']))
    summary[i]['holm_p'] = maximum
reports['harmonic_summary'] = summary

source = Path(os.environ.get('NADOC_OXDNA_AUDIT_SOURCE', str(
    Path.home()/'.local/share/nadoc/engines/oxdna/source'))).resolve()
files = ['src/Interactions/DNANMInteraction.cpp',
    'src/CUDA/Interactions/CUDA_DNANM.cuh', 'src/model.h',
    'src/Backends/Thermostats/BussiThermostat.cpp',
    'src/CUDA/Thermostats/CUDABussiThermostat.cu',
    'src/Backends/Thermostats/BrownianThermostat.cpp',
    'src/CUDA/Thermostats/CUDABrownianThermostat.cu']
try:
    gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], text=True).strip()
except (FileNotFoundError, subprocess.CalledProcessError):
    gpu = 'unavailable'
reports['provenance'] = dict(engine=str(ENGINE),
    engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
    source_revision=subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
    source_files={name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in files},
    interaction_diff=subprocess.check_output(['git', '-C', str(source), 'diff', '--', *files[:3]], text=True),
    backend_precision='mixed', GPU=gpu, paid_computation_added=False,
    installed_engine_changed=False, application_defaults_changed=False)
reports['interpretation'] = {
    'protein_DNA_force_ratio': 'Confirmed different amplitudes; intended published epsilon is unresolved.',
    'GPU_conservation': 'Isolated collision approximately conserves K + twice the CPU contact potential.',
    'bussi_weak_limit': 'Installed CPU/CUDA fail; isolated current-K CPU experiment restores the limit.',
    'harmonic_sampling': 'Four seeds; no Holm-adjusted rejection; not an equivalence validation.',
    'interacting_overheating_cause': 'Not established by this audit; corrected interacting replicas remain needed.'}
(ROOT/'report.json').write_text(json.dumps(reports, indent=2)+'\n')
print(ROOT/'report.json')
