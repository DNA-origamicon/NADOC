"""Run a bounded native pilot with already-built isolated move plugins."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def run(output, binary, mode):
    root, binary = Path(output).resolve(), Path(binary).resolve()
    manifest = json.loads((root/'manifest.json').read_text())
    if hashlib.sha256(Path(manifest['source']).read_bytes()).hexdigest() != manifest['source_sha256']:
        raise ValueError('Source changed since staging; prepare a fresh experiment')
    prepared = root/'experiment'
    folder = root/{'downhill':'quench','thermal':'experiment','postquench':'postquench'}[mode]
    plugins = root/('quench_plugins' if mode == 'downhill' else 'plugins')
    if (folder/'run.log').exists():
        raise FileExistsError('Retain previous evidence; prepare a new output directory')
    if mode != 'thermal':
        folder.mkdir()
        for name in ('conf.dat','topology.top','mobile.txt'):
            (folder/name).write_bytes((prepared/name).read_bytes())
        settings = (prepared/'input').read_text().replace(str(root/'plugins'), str(plugins))
        if mode == 'downhill':
            settings = settings.replace('steps = 10000','steps = 20000')
            settings = settings.replace('delta = 0.01','delta = 0.002').replace('delta = 0.025','delta = 0.005')
        else:
            (folder/'conf.dat').write_bytes((root/'quench/last_conf.dat').read_bytes())
        (folder/'input').write_text(settings)
    settings = (folder/'input').read_text()
    reference = settings.replace('steps = 10000','steps = 0').replace('steps = 20000','steps = 0')
    reference = reference.replace('last_conf.dat','initial_normalized.dat').replace('trajectory.dat','initial_trajectory.dat').replace('energy.dat','initial_energy.dat')
    (folder/'initial.input').write_text(reference)
    record = {'mode':mode, 'executable':str(binary),
              'engine_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
              'input_sha256':hashlib.sha256((folder/'input').read_bytes()).hexdigest(),
              'plugins':json.loads((plugins/'upstream.json').read_text())}
    record['configuration_sha256'] = hashlib.sha256((folder/'conf.dat').read_bytes()).hexdigest()
    record['configuration_source'] = str(root/'quench/last_conf.dat' if mode == 'postquench' else prepared/'conf.dat')
    for input_name, log_name in [('initial.input','initial.log'),('input','run.log')]:
        started = time.monotonic()
        with (folder/log_name).open('w') as log:
            result = subprocess.run([str(binary),input_name],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=60)
        record[input_name] = {'exit_code':result.returncode,'wall_seconds':time.monotonic()-started}
        (folder/'execution.json').write_text(json.dumps(record,indent=2))
        result.check_returncode()


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output');p.add_argument('binary');p.add_argument('--mode',choices=['thermal','downhill','postquench'],default='downhill')
    a=p.parse_args();run(a.output,a.binary,a.mode)
