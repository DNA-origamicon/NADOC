"""Native hydrogen-bond observations and durable end-of-dwell melt termination."""
from pathlib import Path
import re


def pairing_output(spec, banked_steps=0):
    """Each resumed attempt has its own observable, using the active force field."""
    if not (spec.thermal_ramp or {}).get('stop_on_unpaired', False):
        return ''
    cadence = spec.print_conf_interval_override or 10000
    return f'''\ndata_output_1 = {{
name = thermal_pairing_{banked_steps}.dat
print_every = {cadence}
col_1 = {{
type = hb_list
}}
}}
'''


def pairing_summary(directory, topology, threshold):
    """Count unique paired DNA bases, including non-designed/intrastrand pairing.

    An empty but complete native HBList frame means zero bonds. Missing, malformed
    or torn data never count as melting. Keep attempt offsets for restart evidence.
    """
    rows = Path(topology).read_text().splitlines()[1:]
    dna = {i for i, line in enumerate(rows)
           if len(line.split()) >= 4 and int(line.split()[0]) > 0
           and line.split()[1] in {'A', 'C', 'G', 'T', 'N'}}
    if not dna:
        return {'status': 'unavailable', 'reason': 'No DNA bases in the exported topology.'}
    paths = sorted(Path(directory).glob('thermal_pairing_*.dat'),
                   key=lambda p: int(p.stem.rsplit('_', 1)[1]))
    first = None
    samples = 0
    maximum = 0.
    for index, path in enumerate(paths):
        offset = int(path.stem.rsplit('_', 1)[1])
        limit = int(paths[index + 1].stem.rsplit('_', 1)[1]) if index + 1 < len(paths) else float('inf')
        step, paired, valid = None, set(), False
        with path.open() as stream:
            for line in stream:
                if line.startswith('# step '):
                    step = int(line.split()[-1]); paired = set(); valid = True
                elif not line.strip() and step is not None:
                    # Native observable writer separates complete frames with a blank line.
                    if valid and offset + step < limit:
                        fraction = 1 - len(paired & dna) / len(dna)
                        samples += 1; maximum = max(maximum, fraction)
                        if first is None and fraction + 1e-12 >= threshold:
                            first = {'step': offset + step, 'unpaired_fraction': fraction}
                    step = None
                elif step is not None:
                    if not re.fullmatch(r'\d+\s+\d+\s*', line):
                        valid = False
                    else:
                        a, b = map(int, line.split())
                        if a == b or a >= len(rows) or b >= len(rows):
                            valid = False
                        elif a in dna and b in dna:
                            paired.update((a, b))
    return {'status': 'recorded' if samples else 'unavailable', 'samples': samples,
            'dna_bases': len(dna), 'threshold': threshold, 'max_unpaired_fraction': maximum,
            'first_crossing': first, 'criterion': 'unique DNA bases without any native hydrogen bond'}


def prune_after_melt(job, idx, report):
    crossing = report.get('metrics', {}).get('pairing', {}).get('first_crossing')
    if not crossing:
        return
    job.run_config['melt_stop'] = {'stage': job.stages[idx].name, **crossing,
        'threshold': report['metrics']['pairing']['threshold'],
        'reason': 'Unpaired-base threshold reached; current temperature dwell completed.'}
    for stage in job.stages[idx + 1:]:
        if stage.status == 'pending':
            stage.status = 'skipped'
