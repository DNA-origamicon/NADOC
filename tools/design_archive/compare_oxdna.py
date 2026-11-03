"""Offline NADOC/tacoxDNA/deposited-input audit; never launches oxDNA."""
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
from collections import Counter

import numpy as np

from backend.core.cadnano import import_cadnano
from backend.core.design_geometry import _geometry_for_design
from backend.physics.oxdna_interface import write_configuration, write_topology, _strand_nucleotide_provenance


def topology(path):
    lines = Path(path).read_text().splitlines()
    header = list(map(int, lines[0].split()))
    rows = [line.split() for line in lines[1:] if line.strip()]
    if len(header) != 2 or len(rows) != header[0]:
        raise ValueError('Unsupported or truncated topology')
    counts = Counter(int(row[0]) for row in rows)
    return {'nucleotides': header[0], 'strands': header[1], 'strand_lengths': sorted(counts.values())}, rows


def configuration(path):
    with Path(path).open() as f:
        header = [next(f).strip() for _ in range(3)]
        rows = []
        for line in f:
            if line.startswith('t'): break
            if line.strip(): rows.append([float(x) for x in line.split()])
    array = np.array(rows)
    if array.ndim != 2 or array.shape[1] != 15 or not np.isfinite(array).all():
        raise ValueError('Invalid configuration')
    return header, array


def fit(a, b):
    x, y = a[:, :3] - a[:, :3].mean(0), b[:, :3] - b[:, :3].mean(0)
    u, _, vt = np.linalg.svd(x.T @ y)
    rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    delta = np.linalg.norm(x @ rotation - y, axis=1) * .8518
    metrics = {'particles': len(a), 'rmsd_nm': float(np.sqrt(np.mean(delta ** 2))), 'p95_nm': float(np.percentile(delta, 95)), 'max_nm': float(delta.max())}
    for name, sl in [('a1', slice(3, 6)), ('a3', slice(6, 9))]:
        aa, bb = a[:, sl] @ rotation, b[:, sl]
        cos = np.sum(aa * bb, axis=1) / (np.linalg.norm(aa, axis=1) * np.linalg.norm(bb, axis=1))
        metrics[name + '_median_angle_deg'] = float(np.median(np.degrees(np.arccos(np.clip(cos, -1, 1)))))
    return metrics


def run(root, source, record_filter=None):
    converter = (root / 'tacoxDNA/src/cadnano_oxDNA.py').resolve()
    sys.path.insert(0, str(converter.parent))
    inventory = json.loads(Path('frontend/src/data/nanobase_inventory.json').read_text())['records']
    manifests = {r['id']: r for r in json.loads((root / 'starting-oxdna/manifest.json').read_text())}
    report = json.loads((root / 'export-comparison.json').read_text()) if record_filter is not None else []
    report = [r for r in report if r['id'] != record_filter]
    for record in inventory:
        if record_filter is not None and record['id'] != record_filter: continue
        if record['id'] not in manifests or not manifests[record['id']]['files']: continue
        for native in record['files']:
            if native.get('schema') != 'caDNAno v2': continue
            result = {'id': record['id'], 'native': native['name'], 'deposited_comparisons': []}
            work = root / 'export-audit' / str(record['id']) / Path(native['name']).stem
            work.mkdir(parents=True, exist_ok=True)
            try:
                path = source / 'native' / str(record['id']) / native['name']
                data = json.loads(path.read_text())
                result['native_normalized_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                design, warnings = import_cadnano(data)
                result['import_warnings'] = warnings
                result['lattice'] = design.lattice_type.value if hasattr(design, 'lattice_type') else str(design.lattice)
                write_topology(design, work / 'nadoc.top')
                write_configuration(design, _geometry_for_design(design), work / 'nadoc.dat')
                nt, nr = topology(work / 'nadoc.top')
                _, nc = configuration(work / 'nadoc.dat')
                result['nadoc'] = nt
                lattice = 'sq' if 'SQUARE' in result['lattice'].upper() else 'he'
                command = [sys.executable, str(converter), str(path.resolve()), lattice, '-e', '1234', '-p']
                completed = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=120, env=os.environ.copy())
                (work / 'converter.log').write_text(completed.stdout + completed.stderr)
                result['converter_returncode'] = completed.returncode
                if completed.returncode: raise ValueError('Converter failed; see converter.log')
                tt, tr = topology(work / (native['name'] + '.top'))
                _, tc = configuration(work / (native['name'] + '.oxdna'))
                result['tacoxdna'] = tt
                result['same_strand_length_multiset'] = nt == tt
                # Only load our locally generated converter mapping, never deposited pickle files.
                with (work / 'virt2nuc').open('rb') as f: mapping, _ = pickle.load(f)
                active = [v for v in data['vstrands'] if any(x != [-1]*4 for k in ('scaf','stap') for x in v[k])]
                helix_nums = {h.id: v['num'] for h, v in zip(design.helices, active)}
                strand_types = {s.id: 'scaf' if s.strand_type.value == 'scaffold' else 'stap' for s in design.strands}
                nm = {}
                for p in _strand_nucleotide_provenance(design):
                    key = (strand_types[p['strand_id']], helix_nums.get(p['helix_id']), p['bp'])
                    nm.setdefault(key, []).append(p['particle'])
                tm = {(kind, helix, bp): value[1] for kind, entries in [('scaf', mapping._scaf), ('stap', mapping._stap)] for (helix,bp),value in entries.items()}
                keys = [k for k in nm if len(nm[k]) == 1 and len(tm.get(k, [])) == 1]
                ni = np.array([nm[k][0] for k in keys]); ti = np.array([tm[k][0] for k in keys])
                result['mapping'] = {'matched_single_copy_sites': len(keys), 'nadoc_sites': len(nm), 'converter_sites': len(tm), 'unmatched_nadoc_sites': len(nm.keys()-tm.keys()), 'unmatched_converter_sites': len(tm.keys()-nm.keys()), 'loop_copy_alignment': 'excluded; no assumed within-insertion order'}
                if len(keys) >= 3:
                    result['aligned_geometry'] = fit(nc[ni], tc[ti])
                    index_map = dict(zip(ni.tolist(), ti.tolist()))
                    tested, mismatched = 0, 0
                    for nidx,tidx in index_map.items():
                        for col in (2,3):
                            neighbor = int(nr[nidx][col]); target = int(tr[tidx][col])
                            if neighbor == -1 or neighbor in index_map:
                                tested += 1
                                mismatched += ((-1 if neighbor == -1 else index_map[neighbor]) != target)
                    result['directed_neighbor_comparison'] = {'tested': tested, 'mismatched': mismatched}
                for deposited in manifests[record['id']]['files']:
                    if deposited.get('error') or not deposited['name'].endswith(('.dat','.oxdna')): continue
                    comparison = {'file': deposited['name'], 'description': deposited['description'], 'status': 'ordering not established'}
                    try:
                        header, dc = configuration(deposited['path'])
                        comparison.update(header=header, particles=len(dc))
                        tops = []
                        for top in manifests[record['id']]['files']:
                            if top['name'].endswith('.top') and not top.get('error'):
                                dt, dr = topology(top['path'])
                                # Matching full ordered adjacency still cannot prove equal placement/sequence register.
                                if dt == tt and len(dc) == len(tc) and [r[0:1]+r[2:] for r in dr] == [r[0:1]+r[2:] for r in tr]: tops.append(top['name'])
                        comparison['compatible_ordered_topologies'] = tops
                        if tops:
                            comparison['conditional_index_aligned_geometry'] = fit(dc, tc)
                            comparison['status'] = 'ordered connectivity compatible; index alignment conditional on strand/register identity'
                    except Exception as exc: comparison['error'] = str(exc)
                    result['deposited_comparisons'].append(comparison)
            except Exception as exc: result['error'] = str(exc)
            report.append(result)
            (root / 'export-comparison.json').write_text(json.dumps(report, indent=2))
            print(result['id'],result['native'],result.get('error',result.get('aligned_geometry')),flush=True)


if __name__ == '__main__':
    run(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else None)
