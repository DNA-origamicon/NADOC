"""Read-only PEG checkpoint inventory for a NAMD handoff, never a backmapper."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.core.constants import NM_TO_OXDNA
from backend.core.surface_periodic import unwrap_chains
from backend.core.surface_transforms import transform_surface
from backend.physics.oxdna_peg import PEG_BTYPE, PegParameters
from backend.physics.oxdna_surface_geometry import resolved_wall


def require_supported_namd_source(job):
    """Prevent an incomplete PEG source from silently becoming DNA-only NAMD."""
    coating = (job.run_config or {}).get('surface_strands') or {}
    # Built particles remain present even if an old UI disabled its coating toggle.
    if coating.get('material') == 'PEG':
        raise FileNotFoundError(
            'PEG NAMD seed requires a target representation, complete particle/atom '
            'mapping and validated force-field assets. Use /api/oxdna/peg/namd-seed '
            'for the read-only source inventory; DNA-only seeding is refused.'
        )


def inspect_peg_checkpoint(topology_text, checkpoint_text, coating, surface, *, dna_keys):
    """Validate an entire DNA2PEG snapshot and inventory each appended particle.

    Particle/chain identities come from persisted topology and build metadata.
    No statistical bead is interpreted as a chemical repeat or target atom.
    """
    if surface.get('plane_point_nm') is None and surface.get('position_nm') is None:
        raise ValueError('source surface is unresolved; an absolute plane is required')
    params = PegParameters.model_validate(coating)
    built = coating.get('built') or {}
    top = [line.split() for line in topology_text.splitlines() if line.strip()]
    if not top or len(top[0]) != 2 or any(len(row) != 4 for row in top[1:]):
        raise ValueError('expected a DNA2PEG topology with a two-count header')
    total, n_strands = map(int, top[0])
    rows = top[1:]
    if len(rows) != total or total <= 0:
        raise ValueError('topology particle count mismatch')
    lines = [line.strip() for line in checkpoint_text.splitlines() if line.strip()]
    if (len(lines) != total + 3 or not lines[0].startswith('t =')
            or not lines[1].startswith('b =') or not lines[2].startswith('E =')):
        raise ValueError('checkpoint is partial or its particle count/header is invalid')
    # Validate all 15 columns, not just positions: reject truncated/nonfinite frames.
    data = np.asarray([[float(v) for v in line.split()] for line in lines[3:]])
    if data.shape != (total, 15) or not np.isfinite(data).all():
        raise ValueError('checkpoint requires 15 finite values per particle')
    box = np.asarray([float(v) for v in lines[1].split('=', 1)[1].split()]) / NM_TO_OXDNA
    n_dna = len(dna_keys)
    length = params.segments + 1
    n_peg = total - n_dna
    if n_dna <= 0 or n_peg <= 0 or n_peg % length:
        raise ValueError('DNA snapshot/PEG particle counts do not match')
    chains = n_peg // length
    if (built.get('n_beads') != n_peg or built.get('n_strands') != chains
            or built.get('beads_per_chain') != length):
        raise ValueError('PEG build metadata does not match checkpoint/topology counts')
    if any(row[1] == str(PEG_BTYPE) or int(row[0]) <= 0 for row in rows[:n_dna]):
        raise ValueError('DNA prefix contains PEG/protein particles')
    if len({int(row[0]) for row in rows}) != n_strands:
        raise ValueError('topology strand count mismatch')
    for i, row in enumerate(rows[:n_dna]):
        for column, reciprocal in ((2, 3), (3, 2)):
            neighbor = int(row[column])
            if neighbor == -1:
                continue
            if not 0 <= neighbor < n_dna or int(rows[neighbor][reciprocal]) != i:
                raise ValueError('DNA connectivity crosses the PEG boundary or is inconsistent')
    used_strands = {int(row[0]) for row in rows[:n_dna]}
    chain_indices = []
    for c in range(chains):
        start = n_dna + c * length
        strand = int(rows[start][0])
        if strand in used_strands:
            raise ValueError('PEG chain strand identity overlaps another chain')
        used_strands.add(strand)
        for j in range(length):
            row = rows[start + j]
            expected = [str(strand), str(PEG_BTYPE),
                        str(start + j + 1 if j < length - 1 else -1),
                        str(start + j - 1 if j else -1)]
            if row != expected:
                raise ValueError('PEG chain connectivity/type does not match build metadata')
        chain_indices.append(list(range(c * length, (c + 1) * length)))
    traps = built.get('trap_anchors') or []
    starts = [n_dna + c * length for c in range(chains)]
    terminals = [p + length - 1 for p in starts]
    if [p for p, _ in traps] != starts or built.get('terminal_particles') != terminals:
        raise ValueError('PEG graft/terminal identities do not match topology')
    grafts = np.asarray([xyz for _, xyz in traps], float) / NM_TO_OXDNA
    positions = data[:, :3] / NM_TO_OXDNA
    whole = unwrap_chains(positions[n_dna:], chain_indices, box, graft_sites_nm=grafts)
    plane = resolved_wall(surface, data[:n_dna, :3])
    plane.update(graft_sites_nm=grafts.tolist(), peg_positions_nm=whole.tolist())
    return {
        'schema': 'nadoc.peg_seed_source.v1', 'units': 'nm',
        'dna_particles': [{'source_particle': i, 'design_key': list(key)}
                          for i, key in enumerate(dna_keys)],
        'dna_positions_nm': positions[:n_dna].tolist(),
        'dna_a1': data[:n_dna, 3:6].tolist(),
        'dna_a3': data[:n_dna, 6:9].tolist(),
        'dna_positions_periodic': True,
        'box_nm': box.tolist(), 'surface': plane,
        'chains': [{'chain': c, 'source_particles': list(range(p, p + length)),
                    'graft_particle': p, 'terminal_particle': p + length - 1,
                    'target_particles': None, 'target_atoms': None}
                   for c, p in enumerate(starts)],
        'peg_parameters': params.model_dump(),
    }


def transformed_peg_source(source, transform):
    """Transform a whole source; wrapped DNA must first be made whole by its adapter."""
    if source.get('dna_positions_periodic'):
        raise ValueError('make DNA whole using its topology before transforming the assembly')
    result = deepcopy(source)
    result['dna_positions_nm'] = transform.points(source['dna_positions_nm']).tolist()
    result['surface'] = transform_surface(source['surface'], transform)
    for key in ('dna_a1', 'dna_a3'):
        result[key] = (np.asarray(source[key]) @ np.asarray(transform.rotation).T).tolist()
    result['source_box_nm'] = result.pop('box_nm')
    result['cell_vectors_nm'] = (
        np.diag(source['box_nm']) @ np.asarray(transform.rotation).T
    ).tolist()
    result['cell_origin_nm'] = list(transform.translation_nm)
    result['source_to_target'] = {
        'rotation': [list(row) for row in transform.rotation],
        'translation_nm': list(transform.translation_nm), 'angstrom_per_nm': 10,
    }
    return result


def inspect_peg_job(job_id, workspace_dir, target_representation=None):
    from backend.core.oxdna_runner import OxdnaJob, _latest_relaxed_conf, _load_snapshot_design
    from backend.physics.oxdna_interface import _strand_nucleotide_order, topology_rows

    job = OxdnaJob.load(job_id, workspace_dir)
    root = job.job_dir(workspace_dir)
    design = _load_snapshot_design(root)
    if design is None:
        raise ValueError('source job has no readable design snapshot')
    config = job.run_config or {}
    coating = config.get('surface_strands') or {}
    if coating.get('material') != 'PEG':
        raise ValueError('source job has no persisted PEG coating')
    conf, stage = _latest_relaxed_conf(job, workspace_dir)
    if conf is None:
        raise FileNotFoundError('source job has no relaxed checkpoint')
    paths = {'design': root / 'design.json', 'topology': root / 'topology.top',
             'checkpoint': Path(conf)}
    if not (coating.get('built') or {}).get('trap_anchors'):
        paths['initial_configuration'] = root / 'conf.dat'
    blobs = {name: path.read_bytes() for name, path in paths.items()}
    # Parse the captured design bytes, not a second potentially changing snapshot.
    design = type(design).from_json(blobs['design'].decode())
    if 'initial_configuration' in blobs:
        # Persisted jobs compact their build record to trap particle identities.
        # The root configuration is the source of the emitted fixed trap centers.
        # Never substitute the relaxed bead positions for those reference sites.
        coating = deepcopy(coating)
        lines = [line.strip() for line in blobs['initial_configuration'].decode().splitlines() if line.strip()]
        values = np.asarray([[float(v) for v in line.split()] for line in lines[3:]])
        total = int(blobs['topology'].decode().split()[0])
        if values.shape != (total, 15) or not np.isfinite(values).all():
            raise ValueError('initial configuration is partial or nonfinite; graft references unavailable')
        particles = (coating.get('built') or {}).get('trap_particles') or []
        if any(isinstance(p, bool) or not isinstance(p, int) or not 0 <= p < total for p in particles):
            raise ValueError('invalid persisted graft particle index')
        coating['built']['trap_anchors'] = [[p, values[p, :3].tolist()] for p in particles]
    expected_rows, _ = topology_rows(design)
    actual_rows = [line.split() for line in blobs['topology'].decode().splitlines() if line.strip()][1:]
    if actual_rows[:len(expected_rows)] != [list(map(str, row)) for row in expected_rows]:
        raise ValueError('source DNA topology does not match its design snapshot')
    source = inspect_peg_checkpoint(blobs['topology'].decode(), blobs['checkpoint'].decode(),
                                    coating, config.get('surface') or {},
                                    dna_keys=_strand_nucleotide_order(design))
    from backend.core.surface_periodic import unwrap_connected
    from backend.physics.oxdna_interface import _build_unwrap_adjacency
    keys = [tuple(p['design_key']) for p in source['dna_particles']]
    indices = {key: i for i, key in enumerate(keys)}
    if len(indices) != len(keys):
        raise ValueError('source design particle identities are ambiguous')
    adjacency = _build_unwrap_adjacency(dict.fromkeys(keys), design)
    edges = [(indices[a], indices[b]) for a, neighbors in adjacency.items()
             for b in neighbors if indices[a] < indices[b]]
    source['dna_positions_nm'] = unwrap_connected(
        source['dna_positions_nm'], edges, source['box_nm']
    ).tolist()
    source['dna_positions_periodic'] = False
    source['periodic_image_policy'] = 'DNA component roots retain source images; PEG roots use recorded grafts'
    if any(path.read_bytes() != blobs[name] for name, path in paths.items()):
        raise ValueError('source files changed during inspection; retry a stable checkpoint')
    blobs['run_config'] = json.dumps(config, sort_keys=True, allow_nan=False).encode()
    barriers = [
        {'code': 'target_mapping', 'message': 'No target particle/atom mapping has been supplied.'},
        {'code': 'target_assets', 'message': 'PEG topology, force-field and DNA/surface cross interactions need validated assets.'},
        {'code': 'engine_validation', 'message': 'Molecular backmapping and engine validation have not been performed.'},
    ]
    if target_representation is None:
        barriers.insert(0, {'code': 'target_representation',
                            'message': 'Choose coarse-grained PEG or atomistic PEG.'})
    return {'status': 'source_review', 'launch_ready': False,
            'source_job_id': job_id, 'source_stage': stage,
            'source_hashes': {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()},
            'target_representation': target_representation, 'source': source, 'barriers': barriers}
