"""Columnar/binary atomistic display bundle — encoder invariants + a decode round-trip.

The frontend decoder (frontend/src/scene/atomistic_bundle_bin.js) is the only consumer of
this format, so the layout is a contract between the two.  These tests re-implement the
decode here, independently of the encoder's own bookkeeping, so a layout drift on either
side shows up as a failure rather than as silently scrambled atoms on screen.
"""
import json
import struct

import numpy as np
import pytest

from backend.core.atomistic import BundleNotPackable, pack_bundle_bin

_MAGIC = 0x4E414231


def _atom(serial, **kw):
    a = {
        "serial": serial, "name": "P", "element": "P", "residue": "DC", "chain_id": "A",
        "seq_num": 1, "x": 0.0, "y": 0.0, "z": 0.0, "strand_id": "s0", "helix_id": "h0",
        "bp_index": 0, "direction": "FORWARD", "is_modified": False, "aux_helix_id": "",
        "aux_t": 0.0, "crossover_id": None, "extra_base_k": None,
    }
    a.update(kw)
    return a


def _bundle(atoms, bonds=(), *, n_nuc=2):
    n = len(atoms)
    return {
        "atoms": atoms,
        "bonds": [list(b) for b in bonds],
        "element_meta": {"P": {"vdw_radius": 0.19, "cpk_color": 16747520}},
        "topology_hash": "THASH",
        "n_nuc": n_nuc,
        "atom_nuc": [i % n_nuc if i % 3 else -1 for i in range(n)],
        "atom_local": [float(i) for i in range(n * 3)],
        "nonrigid_serials": [i for i in range(n) if not i % 3],
    }


def _decode(buf: bytes) -> dict:
    """Independent re-implementation of atomistic_bundle_bin.js parse."""
    magic, version, n, n_bonds, hlen = struct.unpack_from("<IIIII", buf, 0)
    assert magic == _MAGIC
    assert version == 1
    off = 20
    header = json.loads(buf[off:off + hlen].decode())
    off += hlen
    off += (-off) % 4

    def take(dtype, count):
        nonlocal off
        arr = np.frombuffer(buf, dtype=dtype, count=count, offset=off)
        off += arr.nbytes
        return arr

    out = {"header": header, "n": n}
    for name in ("x", "y", "z"):
        out[name] = take(np.float32, n)
    out["bp_index"] = take(np.int32, n)
    out["aux_t"] = take(np.float32, n)
    for name in ("strand_idx", "helix_idx", "aux_helix_idx"):
        out[name] = take(np.uint16, n)
    for name in ("element_idx", "dir_idx"):
        out[name] = take(np.uint8, n)
    off += (-off) % 4
    out["bonds"] = take(np.uint32, n_bonds * 2)
    n_nuc, n_nonrigid = struct.unpack_from("<II", buf, off)
    off += 8
    out["n_nuc"] = n_nuc
    out["atom_nuc"] = take(np.int32, n)
    out["atom_local"] = take(np.float32, n * 3)
    out["nonrigid_serials"] = take(np.uint32, n_nonrigid)
    assert off == len(buf), f"decoder consumed {off} of {len(buf)} bytes"
    return out


def test_round_trip_preserves_every_field_the_frontend_reads():
    atoms = [
        _atom(0, element="P", x=1.5, y=-2.25, z=3.0, strand_id="sc", helix_id="h_a",
              bp_index=7, direction="FORWARD"),
        _atom(1, element="C", x=0.0, y=0.0, z=0.0, strand_id="st1", helix_id="h_b",
              bp_index=231, direction="REVERSE", aux_helix_id="h_a", aux_t=0.25),
        _atom(2, element="O", x=-9.75, y=4.5, z=0.125, strand_id="sc", helix_id="h_a",
              bp_index=8, direction="REVERSE"),
    ]
    d = _decode(pack_bundle_bin(_bundle(atoms, [(0, 1), (1, 2)])))

    assert d["n"] == 3
    np.testing.assert_allclose(d["x"], [1.5, 0.0, -9.75])
    np.testing.assert_allclose(d["y"], [-2.25, 0.0, 4.5])
    np.testing.assert_allclose(d["z"], [3.0, 0.0, 0.125])
    np.testing.assert_array_equal(d["bp_index"], [7, 231, 8])
    np.testing.assert_allclose(d["aux_t"], [0.0, 0.25, 0.0])
    # String fields survive interning: index → table must reproduce the original value.
    for field, key in (("strand", "strand_table"), ("helix", "helix_table"),
                       ("element", "element_table"), ("dir", "dir_table")):
        got = [d["header"][key][i] for i in d[f"{field}_idx"]]
        src = {"strand": "strand_id", "helix": "helix_id",
               "element": "element", "dir": "direction"}[field]
        assert got == [a[src] for a in atoms], field
    aux = [d["header"]["aux_helix_table"][i] for i in d["aux_helix_idx"]]
    assert aux == ["", "h_a", ""]
    np.testing.assert_array_equal(d["bonds"], [0, 1, 1, 2])
    assert d["header"]["topology_hash"] == "THASH"
    assert d["header"]["element_meta"]["P"]["cpk_color"] == 16747520


def test_stamp_descriptor_round_trips_with_the_negative_sentinel():
    """atom_nuc uses -1 for 'non-rigid'; a u32 column would turn that into 4294967295 and
    expandStampFrames would index frames[] far out of range instead of skipping the atom."""
    atoms = [_atom(i) for i in range(6)]
    b = _bundle(atoms)
    d = _decode(pack_bundle_bin(b))
    np.testing.assert_array_equal(d["atom_nuc"], b["atom_nuc"])
    assert (d["atom_nuc"] < 0).any(), "fixture should exercise the sentinel"
    np.testing.assert_allclose(d["atom_local"], b["atom_local"])
    np.testing.assert_array_equal(d["nonrigid_serials"], b["nonrigid_serials"])
    assert d["n_nuc"] == b["n_nuc"]


def test_seven_unread_fields_are_not_in_the_payload():
    """name/residue/chain_id/seq_num/is_modified/crossover_id/extra_base_k are read
    nowhere in frontend/src — they were ~40% of the JSON atom payload."""
    atoms = [_atom(i, name="ZZUNIQUE", residue="QQUNIQUE", chain_id="Z") for i in range(4)]
    buf = pack_bundle_bin(_bundle(atoms))
    assert b"ZZUNIQUE" not in buf
    assert b"QQUNIQUE" not in buf


def test_bondless_and_nonrigidless_bundles_pack():
    atoms = [_atom(i, bp_index=i) for i in range(4)]
    b = _bundle(atoms)
    b["bonds"] = []
    b["nonrigid_serials"] = []
    b["atom_nuc"] = [0, 0, 1, 1]
    d = _decode(pack_bundle_bin(b))
    assert d["bonds"].size == 0
    assert d["nonrigid_serials"].size == 0


@pytest.mark.parametrize("serials", [[0, 1, 3], [1, 2, 3], [2, 1, 0]])
def test_non_dense_serials_refuse_to_pack(serials):
    """serial IS the row index in this format (that's what lets the column be dropped and
    the serial-keyed relaxed frames be indexed directly). If that ever stops holding, the
    route must 409 and the client fall back to JSON — never ship scrambled atoms."""
    atoms = [_atom(s) for s in serials]
    b = _bundle(atoms)
    b["atom_nuc"] = [0] * len(atoms)
    b["atom_local"] = [0.0] * (3 * len(atoms))
    with pytest.raises(BundleNotPackable):
        pack_bundle_bin(b)


def test_empty_bundle_refuses_to_pack():
    with pytest.raises(BundleNotPackable):
        pack_bundle_bin({"atoms": []})


def test_descriptor_length_mismatch_refuses_to_pack():
    atoms = [_atom(i) for i in range(3)]
    b = _bundle(atoms)
    b["atom_local"] = [0.0, 1.0]      # should be 3*n
    with pytest.raises(BundleNotPackable):
        pack_bundle_bin(b)


def test_packed_blob_is_far_smaller_than_the_json_it_replaces():
    """The whole point. 600 atoms is enough to show the asymptotic ratio."""
    atoms = [_atom(i, x=i * 0.1, y=i * 0.2, z=i * 0.3, bp_index=i % 200,
                   strand_id=f"strand_{i % 40}", helix_id=f"h_{i % 12}",
                   direction="FORWARD" if i % 2 else "REVERSE") for i in range(600)]
    b = _bundle(atoms, [(i, i + 1) for i in range(599)])
    packed = len(pack_bundle_bin(b))
    as_json = len(json.dumps(b))
    assert packed * 4 < as_json, f"packed {packed} vs json {as_json} — expected ≥4×"
