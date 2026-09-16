"""Columnar static MD topology: original sparse serials and all identity fields."""
import struct

import numpy as np
import orjson


def md_atomistic_model_bin(topology, segments, coordinate, design):
    from backend.core.md_trajectory import _build_playback_ctx, _extract_md_atoms_frame, heavy_bond_pairs
    ctx = _build_playback_ctx(topology, [s[2] for s in segments], coordinate, design, with_atoms=True)
    meta = ctx['atom_meta']
    n = len(meta)
    xyz = _extract_md_atoms_frame(ctx, 0, positions_only=True)
    bonds = ctx.get('heavy_bonds')
    if bonds is None:
        bonds = np.asarray(heavy_bond_pairs(ctx['universe'], ctx['heavy_idx']) or [], dtype='<u4').reshape(-1,2)
    columns, tables = [], {}
    data = bytearray()

    def add(name, values, dtype):
        a = np.asarray(values, dtype=dtype).ravel()
        data.extend(b'\0' * ((-len(data)) % 8))
        columns.append(dict(name=name, dtype=dtype, offset=len(data), count=len(a)))
        data.extend(a.tobytes())

    for axis, name in enumerate(('x','y','z')):
        add(name, xyz[:,axis], '<f8')
    add('serial', ctx['heavy_idx'], '<u4')
    add('bpIndex', [m.get('bp_index', -1) for m in meta], '<i4')
    add('copyK', [m.get('copy_k', 0) for m in meta], '<i4')
    for field, name in (('element','element'),('strand_id','strand'),('helix_id','helix'),
                        ('direction','dir'),('name','name'),('scalar_key','scalarKey'),('base_key','baseKey')):
        table, lookup, indices = [], {}, []
        for m in meta:
            value = m.get(field, '')
            if value not in lookup:
                lookup[value] = len(table)
                table.append(value)
            indices.append(lookup[value])
        tables[name + 'Table'] = table
        add(name + 'Idx', indices, '<u4')
    add('bonds', bonds, '<u4')
    header = orjson.dumps(dict(count=n, n_serials=int(ctx['heavy_idx'].max())+1 if n else 0,
                              columns=columns, **tables))
    prefix = struct.pack('<4I', 0x4D44414D, 1, len(header), 0)
    return prefix + header + b'\0' * ((-len(header)) % 8) + data
