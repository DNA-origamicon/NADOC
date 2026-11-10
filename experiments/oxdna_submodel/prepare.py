"""Stage a headless, isolated central-14-bp experiment via real NADOC job routes.

Run from the repository with `uv run python -m experiments.oxdna_submodel.prepare
SOURCE OUTPUT`. OUTPUT must not exist. Run build_plugins separately, then the
native executable with experiment/input in its directory. No authored molecular
copy is created: the managed job retains the audited input's entire history.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.api.headless_oxdna_build import create_job, _use_workspace
from backend.api.routes_oxdna import put_oxdna_submodel, get_oxdna_submodel, _seed_geometry
from backend.api.simulation_submodel import SubmodelSelection
from backend.core.models import Design
from backend.core.oxdna_job import OxdnaJob
from backend.physics.oxdna_interface import _strand_nucleotide_order, resolved_nuc_map
from scripts.agent_structure_guard import audit


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    raw = source.read_bytes()
    design = Design.model_validate_json(raw)
    proof = audit(design)
    if len(design.helices) != 1 or design.helices[0].length_bp != 42 or len(design.strands) != 2:
        raise ValueError('This pilot requires a single 42-bp duplex')
    output.mkdir(parents=True, exist_ok=False)
    ws = output/'workspace'
    result = create_job(design, ws, design_source_path=str(source))
    job = OxdnaJob.load(result['job_id'], ws)
    jd = job.job_dir(ws)
    order = _strand_nucleotide_order(design)
    geometry = resolved_nuc_map(design, _seed_geometry(design))
    positions = np.array([geometry[key]['backbone_position'] for key in order])
    target = np.array([14 <= key[1] <= 27 for key in order])
    # This specimen's helix is along z. Boundaries lie halfway between bp planes.
    lo, hi = positions[target].min(axis=0), positions[target].max(axis=0)
    lo[:2] -= .4; hi[:2] += .4
    lo[2] -= .167; hi[2] += .167
    selection = SubmodelSelection(box={'min_corner':lo.tolist(), 'max_corner':hi.tolist()})
    with _use_workspace(ws):
        asyncio.run(put_oxdna_submodel(job.job_id, selection))
        restored = asyncio.run(get_oxdna_submodel(job.job_id))
    assert restored == selection.model_dump(mode='json')
    inside = np.all((positions >= lo) & (positions <= hi), axis=1)
    assert np.array_equal(inside, target) and inside.sum() == 28
    experiment = output/'experiment'
    experiment.mkdir()
    for name in ('conf.dat', 'topology.top'):
        (experiment/name).write_bytes((jd/name).read_bytes())
    (experiment/'mobile.txt').write_text('\n'.join(map(str,np.flatnonzero(inside)))+'\n')
    mapping = [{'particle':i, 'key':list(key), 'mobile':bool(inside[i]),
                'selection_position_nm':positions[i].tolist()} for i,key in enumerate(order)]
    (output/'mapping.json').write_text(json.dumps(mapping, indent=2))
    manifest = {'source':str(source), 'source_sha256':hashlib.sha256(raw).hexdigest(),
                'audit':proof, 'job_id':job.job_id, 'job_directory':str(jd),
                'selection':restored, 'mobile_bp':[14,27], 'mobile_nucleotides':28,
                'fixed_nucleotides':56, 'coordinates':'design backbone positions in nm',
                'boundary':'Full duplex retained; only selected IDs receive MC proposals',
                'upstream_history':str(jd/'design.json')}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2))
    (experiment/'input').write_text(f'''backend = CPU
sim_type = MC2
interaction_type = DNA2
T = 20C
salt_concentration = 0.5
use_average_seq = 1
seed = 271828
steps = 10000
conf_file = conf.dat
topology = topology.top
trajectory_file = trajectory.dat
lastconf_file = last_conf.dat
energy_file = energy.dat
print_energy_every = 100
print_conf_interval = 1000
time_scale = linear
no_stdout_energy = 1
restart_step_counter = 1
refresh_vel = 0
fix_diffusion = false
list_type = no
plugin_search_path = {output/'plugins'}
plugin_move_entry_points = make_move
move_1 = {{
 type = SubmodelTranslation
 delta = 0.01
 prob = 1
}}
move_2 = {{
 type = SubmodelRotation
 delta = 0.025
 prob = 1
}}
''')
    assert source.read_bytes() == raw
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)
