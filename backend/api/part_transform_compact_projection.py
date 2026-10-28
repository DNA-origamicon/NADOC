"""Lossless transform transport from native arrays, without transient full records.

Only ordinary in-span DNA uses this adapter. Sparse residue poses still run the
existing record authority; companions and out-of-span domains use the general
projection. No geometric arithmetic or cross-request cache lives here.
"""
import base64

import numpy as np

from backend.api.part_transform_display_contract import reject
from backend.core.part_dna_comparison_codec import SCALAR_COLUMNS, VECTOR_FIELDS, SITE_FIELDS


# Keep the explicit scalar serializer tied to the shared fixed wire schema.
assert SCALAR_COLUMNS == ('helix_id', 'bp_index', 'direction', 'copy_k', 'placement_source',
    'strand_id', 'strand_type', 'is_five_prime', 'is_three_prime', 'domain_index',
    'overhang_id', 'is_reference', 'is_flexible_segment', 'is_unpaired')


def compact_native(design, expected, check):
    from backend.core import design_geometry as geometry
    from backend.core.native_full_placement import SOURCE
    from backend.core.native_slab_placement import attach_native_slab_poses, native_slab_poses_for_arrays
    from backend.api.part_transform_projection import _check_slab_block

    if (design.extensions or design.overhangs or design.overhang_connections
            or design.flexible_connections or design.photoproduct_junctions
            or any(h.native_residues or h.native_source or h.id.startswith('__lnk__') for h in design.helices)):
        return None
    helices = expected.indices['helices']
    if any(d.start_bp < helices[d.helix_id].bp_start or d.end_bp < helices[d.helix_id].bp_start
           or max(d.start_bp, d.end_bp) >= helices[d.helix_id].bp_start + helices[d.helix_id].length_bp
           for s in design.strands for d in s.domains):
        return None
    info = geometry._strand_nucleotide_info(design)
    posed = {t.target_key() for t in design.nucleotide_transforms if t.kind == 'base'}
    roll = geometry.native_full_phase_roll_rad(design)
    rows, blocks, all_directions, posed_records, posed_indices = [], [], [], [], []
    slab_batches, slab_indices = [], []
    seen = set()
    for helix in design.helices:
        check()
        arrays = geometry.native_full_arrays_for_helix(helix, design)
        if arrays.get('placement_source') != SOURCE or arrays.get('helix_id') != helix.id:
            return None
        selected, scalars, copies = [], [], {}
        bps, directions = arrays['bp_indices'].tolist(), arrays['directions'].tolist()
        for i, (bp, direction) in enumerate(zip(bps, directions, strict=True)):
            d = ('FORWARD', 'REVERSE')[direction]
            copy = copies.get((bp, d), 0)
            copies[bp, d] = copy + 1
            owner = info.get((helix.id, bp, d))
            if owner is None:
                continue
            key = helix.id, bp, d, copy
            if key in seen or expected.sites.get(key) != (
                    owner['strand_id'], owner['domain_index'], owner['overhang_id'], owner['is_reference']):
                reject('Native display occupancy disagrees with its source', 'invalid_preview_geometry')
            seen.add(key)
            scalars.append([helix.id, bp, d, copy, SOURCE,
                owner['strand_id'], owner['strand_type'], owner['is_five_prime'], owner['is_three_prime'],
                owner['domain_index'], owner['overhang_id'], owner['is_reference'],
                owner['is_flexible_segment'], owner['is_unpaired']])
            selected.append(i)
        if not selected:
            continue
        count, offset = len(selected), len(rows)
        block = np.empty((count, 28), dtype='<f8')
        for start, name in ((0, 'positions'), (3, 'base_positions'), (6, 'base_normals'),
                            (9, 'axis_tangents'), (19, 'axis_points'), (22, 'radial_hats')):
            block[:, start:start + 3] = arrays[name][selected]
        block[:, 25] = arrays['azimuths'][selected]
        block[:, 26] = (arrays['azimuths'][1::2] - arrays['azimuths'][::2])[np.asarray(selected) // 2]
        block[:, 27] = roll
        unposed = []
        for local, (i, scalar) in enumerate(zip(selected, scalars, strict=True)):
            if ('base', helix.id, scalar[1], scalar[2], scalar[3]) in posed:
                # Construct only the sparse posed sites, without slabs, exactly
                # as the general producer does before its final pose pass.
                record = dict(zip(SCALAR_COLUMNS, scalar, strict=True))
                for name, start in (('backbone_position', 0), ('base_position', 3),
                                    ('base_normal', 6), ('axis_tangent', 9)):
                    record[name] = block[local, start:start + 3].tolist()
                record['helical_site'] = dict(axis_point=block[local, 19:22].tolist(),
                    radial_hat=block[local, 22:25].tolist(), azimuth_rad=float(block[local, 25]),
                    groove_offset_rad=float(block[local, 26]), phase_roll_rad=roll)
                posed_records.append(record)
                posed_indices.append(offset + local)
            else:
                unposed.append(i)
                slab_indices.append(offset + local)
        if unposed:
            slab_batches.append({name: arrays[name][unposed] for name in (
                'bp_indices', 'directions', 'positions', 'base_positions', 'base_normals', 'axis_tangents')})
        rows.extend(scalars)
        all_directions.extend(row[2] for row in scalars)
        blocks.append(block)
    if seen != expected.sites.keys() or expected.extensions:
        reject('Native transform display omitted occupied records', 'invalid_preview_geometry')
    values = np.concatenate(blocks) if blocks else np.empty((0, 28), dtype='<f8')
    if slab_batches:
        arrays = {name: np.concatenate([b[name] for b in slab_batches]) for name in slab_batches[0]}
        arrays.update(helix_id=None, placement_source=SOURCE)
        centers, quaternions = native_slab_poses_for_arrays(arrays)
        values[slab_indices, 12:15], values[slab_indices, 15:19] = centers, quaternions
    if posed_records:
        geometry.apply_nucleotide_transforms_to_geometry(posed_records, design)
        attach_native_slab_poses(posed_records)
        for index, record in zip(posed_indices, posed_records, strict=True):
            offset = 0
            for name, length in VECTOR_FIELDS:
                values[index, offset:offset + length] = record[name]
                offset += length
            for name, length in SITE_FIELDS:
                values[index, offset:offset + (length or 1)] = record['helical_site'][name]
                offset += length or 1
    if not np.isfinite(values).all():
        reject('Malformed native transform display coordinates', 'invalid_preview_geometry')
    # Independently check the final slab frames and registration, including
    # sparse poses. Scalar ownership above is checked against source inventory.
    if not _check_slab_block([], values.reshape(-1), native_directions=all_directions):
        return None
    check()
    return ({'encoding': 'f64-block-v1', 'count': len(rows), 'rows': rows,
             'f64': base64.b64encode(values.tobytes()).decode('ascii')}, values.reshape(-1))
