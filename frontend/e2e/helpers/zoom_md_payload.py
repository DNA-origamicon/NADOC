"""Read existing PSF/DCD evidence for the opt-in inset browser regression.

No files are written, no simulation is run and no design is authored. Output is
transient display transport for the saved inset plus its attachment residues.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.core.md_trajectory import _DcdPrefixFile, _build_playback_ctx
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
keys = {r['key'] for t in raw['zoom_volumes'][0]['targets'] for r in t['refs']}
for crossover in design.crossovers:
    inserts = {f'__xb__:{crossover.id}:{i}' for i in range(len(crossover.extra_bases or ''))}
    if inserts and inserts <= keys:
        for h in (crossover.half_a, crossover.half_b):
            keys.add(f'{h.helix_id}:{h.index}:{h.strand.value}')
paths = sorted((package / 'output').glob('*.dcd'))
assert len(paths) == 1, 'Choose a single-segment evidence job'
psf = package / f"{job['name_stem']}_hmr.psf"
if not psf.exists():
    psf = package / f"{job['name_stem']}.psf"
ctx = _build_playback_ctx(psf, paths, package / f"{job['name_stem']}.pdb", design, with_atoms=True)
meta = {int(m['serial']): m for m in ctx['atom_meta'] if m.get('base_key') in keys}
bonds = [[int(a), int(b)] for a, b in ctx['heavy_bonds'] if a in meta and b in meta]
ctx['dcd_prefix'].close()
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
