"""Compile isolated CPU symbol overrides from the matching installed source.

These are diagnostic libraries, not installable engine fixes. Only explicitly
selected child processes use them through LD_PRELOAD. The source must match the
binary ABI, including NADOC's existing rigid-body bookkeeping patch.
"""
import difflib
import os
from pathlib import Path
import subprocess

from pair_audit import ROOT

source = Path(os.environ.get('NADOC_OXDNA_AUDIT_SOURCE', str(
    Path.home()/'.local/share/nadoc/engines/oxdna/source'))).resolve()
p = source/'src/Backends/Thermostats/BussiThermostat.cpp'
original = p.read_text()
needle = '\t_update_K(_K_t, _current_translational_degrees_of_freedom());'
assert original.count(needle) == 1
assert 'Bussi rigid-body DOF fix v1:' in original, 'Requires matching NADOC v2 source and binary'
modified = original.replace(needle, '\t_K_t = K_now_t;\n\t_K_r = K_now_r;\n'+needle)
for name, text, label in [('baseline_experiment', original, 'unchanged Bussi control'),
                          ('current_k_experiment', modified, 'current-K Bussi experiment')]:
    text = text.replace('Bussi rigid-body DOF fix v1:', 'AUDIT ONLY '+label+':')
    cpp = ROOT/(name+'.cpp')
    cpp.write_text(text)
    command = ['g++', '-std=c++14', '-shared', '-fPIC', '-O2', '-DJSON_ENABLED',
               '-iquote', str(p.parent), '-I', str(source/'src/extern'),
               str(cpp), '-o', str(ROOT/(name+'.so'))]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    (ROOT/(name+'.build.log')).write_text(completed.stdout+completed.stderr)
(ROOT/'current_k_experiment.patch').write_text(''.join(difflib.unified_diff(
    original.splitlines(True), modified.splitlines(True),
    fromfile='installed/BussiThermostat.cpp', tofile='audit-only/BussiThermostat.cpp')))
