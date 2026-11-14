"""Read existing PSF/DCD evidence for the opt-in inset browser regression.

No files are written, no simulation is run and no design is authored. Output is
transient display transport for the saved inset plus its attachment residues.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_to_nadoc import atom_design_ident, load_segid_chain_map, md_pkey
from backend.core.md_trajectory import _DcdPrefixFile
from backend.core.models import Design

workspace, source, job_id = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
raw = json.loads((workspace / source).read_text())
design = Design.model_validate(raw)
index = json.loads((workspace / 'md_jobs/.archive_index.json').read_text())
jobdir = Path(index.get(job_id, workspace / 'md_jobs' / job_id))
job = json.loads((jobdir / 'job.json').read_text())
frozen = Design.model_validate_json((jobdir / 'design.json').read_text())
assert design.strands == frozen.strands and design.crossovers == frozen.crossovers
package = jobdir / job['package_subdir']
model = build_atomistic_model(design, fast_bridges=True)
keys = {r['key'] for t in raw['zoom_volumes'][0]['targets'] for r in t['refs']}
for crossover in design.crossovers:
    inserts = {f'__xb__:{crossover.id}:{i}' for i in range(len(crossover.extra_bases or ''))}
    if inserts and inserts <= keys:
        for h in (crossover.half_a, crossover.half_b):
            keys.add(f'{h.helix_id}:{h.index}:{h.strand.value}')
residues = {(a.chain_id, a.seq_num): (md_pkey(a), a.strand_id) for a in model.atoms}
segmap = load_segid_chain_map(package)
meta = {}
psf = package / f"{job['name_stem']}_hmr.psf"
if not psf.exists():
    psf = package / f"{job['name_stem']}.psf"
with psf.open() as stream:
    for line in stream:
        if '!NATOM' in line:
            n = int(line.split()[0])
            break
    for i in range(n):
        fields = next(stream).split()
        item = residues.get((segmap.get(fields[1]), int(fields[2])))
        if item is None or fields[4].startswith('H') or fields[4][:1].isdigit():
            continue
        ident = atom_design_ident(*item)
        if ident['base_key'] in keys:
            meta[i] = dict(serial=i, name=fields[4], element=fields[4][0], **ident)
    for line in stream:
        if '!NBOND' in line:
            count = int(line.split()[0]) * 2
            chunks = []
            while count > 0:
                words = next(stream).split()
                chunks.extend(words)
                count -= len(words)
            pairs = np.asarray(chunks, dtype=int).reshape(-1, 2) - 1
            bonds = [[int(a), int(b)] for a, b in pairs if a in meta and b in meta]
            break
paths = sorted((package / 'output').glob('*.dcd'))
assert len(paths) == 1, 'Choose a single-segment evidence job'
reader = _DcdPrefixFile(paths[0], max(meta) + 1)
frames = []
try:
    for index in [0, reader.n_frames - 1]:
        raw, _ = reader.frame(index)
        atoms = [dict(a, x=float(raw[i, 0] / 10), y=float(raw[i, 1] / 10), z=float(raw[i, 2] / 10)) for i, a in meta.items()]
        positions = []
        for atom in atoms:
            if atom['name'] != 'P':
                continue
            key = atom['base_key'].split(':')
            positions.append(dict(helix_id=key[0], bp_index=key[1] if key[0]=='__xb__' else int(key[1]),
                                  direction=int(key[2]) if key[0]=='__xb__' else key[2],
                                  x=atom['x'], y=atom['y'], z=atom['z']))
        inset_atoms = [[a['base_key'], a['name'], a['x'], a['y'], a['z']] for a in atoms]
        frames.append(dict(atoms=atoms, positions=positions, inset_atoms=inset_atoms, source_frame=index))
finally:
    reader.close()
print(json.dumps(dict(frames=frames, bonds=bonds, keys=sorted(keys))))
