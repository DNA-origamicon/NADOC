"""Matched CPU throughput/RSS benchmark; no changes to source jobs or structures."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess

from experiments.oxdna_submodel.production import sha


def run(specimen, output, steps=20000, repeats=3):
    root, output = Path(specimen).resolve(), Path(output).resolve()
    source = json.loads((root/'manifest.json').read_text())
    recipe = json.loads((root/'extraction.json').read_text())
    parent = Path(source['job_directory'])
    binary = Path('.development-artifacts/oxdna-submodel-production-20261109/engine-matched/oxDNA-submodel').resolve()
    output.mkdir(exist_ok=False,parents=True)
    rows=[]
    for case in ['full_mobile','full_fixed','cropped']:
        folder=output/case;folder.mkdir()
        native_source=root/'production' if case=='cropped' else parent
        for name in ['topology.top','conf.dat']:
            (folder/name).write_bytes((native_source/name).read_bytes())
        # Compare the SAME starting pose: the cropped original input, not its relaxed descendant.
        if case=='cropped':(folder/'conf.dat').write_bytes((root/'relaxation/conf.dat').read_bytes())
        ids=(recipe['mobile_output_indices'] if case=='cropped' else
             recipe['mobile_source_indices'] if case=='full_fixed' else list(range(source['source_particles'])))
        (folder/'mobile.txt').write_text('\n'.join(map(str,ids))+'\n')
        n=int((folder/'topology.top').read_text().split()[0])
        trials=[]
        for repeat in range(repeats):
            trial=folder/str(repeat);trial.mkdir()
            settings=(root/'production/input').read_text().replace('steps = 100000',f'steps = {steps}')
            settings=settings.replace('print_conf_interval = 1000',f'print_conf_interval = {steps}')
            settings=settings.replace('topology = topology.top',f'topology = {folder/"topology.top"}')
            settings=settings.replace('conf_file = conf.dat',f'conf_file = {folder/"conf.dat"}')
            settings=settings.replace('submodel_mobile_file = mobile.txt',f'submodel_mobile_file = {folder/"mobile.txt"}')
            settings=settings.replace('seed = 314159',f'seed = {314159+repeat}')
            (trial/'input').write_text(settings)
            with (trial/'native.log').open('w') as log:
                subprocess.run(['/usr/bin/time','-f','{"wall_seconds":%e,"peak_rss_kib":%M,"cpu_percent":"%P"}','-o','resources.json',str(binary),'input'],
                               cwd=trial,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
            result=json.loads((trial/'resources.json').read_text())
            result['steps_per_second']=steps/result['wall_seconds'];trials.append(result)
        row={'case':case,'particles':n,'mobile':len(ids),'steps':steps,'trials':trials,
             'median_steps_per_second':statistics.median(t['steps_per_second'] for t in trials),
             'peak_rss_kib':max(t['peak_rss_kib'] for t in trials)}
        rows.append(row);print(json.dumps(row),flush=True)
        (output/'results.json').write_text(json.dumps(rows,indent=2))
    (output/'manifest.json').write_text(json.dumps({'source_manifest':str(root/'manifest.json'),
        'source_sha256':sha(root/'manifest.json'),'binary':str(binary),'binary_sha256':sha(binary),
        'timing':'end-to-end native wall time, includes initialization and final output',
        'resource':'/usr/bin/time maximum resident set; CPU only; identical box and force field',
        'fixed_control':'full_fixed and cropped have identical 102 mobile source particles',
        'repeats':repeats,'steps':steps},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('specimen');p.add_argument('output')
    a=p.parse_args();run(a.specimen,a.output)
