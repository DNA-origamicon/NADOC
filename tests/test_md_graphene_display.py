"""Graphene must share the DNA/cell affine and use current DCD coordinates."""
import json
import struct
from types import SimpleNamespace

import numpy as np

from backend.core.md_solvent import (
    DisplayXform, build_solvent_ctx, extract_solvent_frame, pack_solvent_bin,
)


def test_graphene_uses_live_positions_and_periodic_display_alignment():
    atoms = SimpleNamespace(
        names=np.array(['C', 'C', 'C', 'P']),
        resnames=np.array(['GRP', 'GRP', 'GRP', 'ADE']),
        resindices=np.arange(4), positions=np.zeros((4, 3)),
    )
    u = SimpleNamespace(atoms=atoms, dimensions=None)
    ctx = build_solvent_ctx(u)
    # A site across the +X boundary must appear at -X; DNA is excluded.
    pos = np.array([[19, 3, 5], [21, 3, 5], [1, 3, 5], [0, 0, 0.]])
    xf = DisplayXform.build(
        T_dyn=[2, 3, 4], c_box=[1, 1, 1], box_nm=[2, 2, 2],
        mob_c=[2, 3, 4], eq_centroid=[10, 20, 30],
        R=np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]),
    )
    frame = extract_solvent_frame(
        u, ctx, np.zeros((0, 3)), np.zeros((0, 3)), xf,
        water=False, ions=False, box=True, positions_ang=pos,
    )
    expected = [[9.7, 21.9, 30.5], [9.7, 20.1, 30.5], [9.7, 20.1, 30.5]]
    np.testing.assert_allclose(frame['graphene'].reshape(-1, 3), expected, atol=2e-6)
    # Independent decode: both frames preserve the carbon block after the cell.
    blob = pack_solvent_bin({0: frame, 1: frame})
    assert struct.unpack_from('<I', blob, 4)[0] == 3
    length = struct.unpack_from('<I', blob, 16)[0]
    header = json.loads(blob[20:20+length])
    assert header['n_graphene'] == 3
    offset = 20 + length + (-length) % 4
    for _ in range(2):
        offset += 24 * 4
        carbon = np.frombuffer(blob, dtype='<f4', count=9, offset=offset)
        np.testing.assert_allclose(carbon.reshape(-1, 3), expected, atol=2e-6)
        offset += 9 * 4
    assert offset == len(blob)
