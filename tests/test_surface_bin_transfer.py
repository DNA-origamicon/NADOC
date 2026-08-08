"""Binary design-surface transfer — ``GET /design/surface-bin`` + ``pack_surface_bin``.

The design surface's JSON payload is dominated by a million-number vertices/faces array whose
``JSON.parse`` blocks the browser main thread (VoltronCore: ~74 MB / minutes).  The binary
route packs the SAME mesh into a compact little-endian blob (~3–4× smaller, decoded as typed
arrays) and — unlike the sim overlay's blob — carries the strand-index table so the design
surface still recolours client-side.  These tests pin: the ``pack_surface_bin`` strand-block
round-trip (incl. the not-ready/empty case) and byte-parity between the binary route and the
JSON route on a real (small) design.
"""

from __future__ import annotations

import json
import struct

import numpy as np
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.core.oxdna_health import pack_surface_bin
from tests.conftest import make_6hb_design

_MAGIC = 0x4E535246


def _unpack(buf: bytes) -> dict:
    """Reference decoder mirroring frontend scene/surface_bin.js parseSurfaceBin."""
    magic, nv, nf, ck = struct.unpack_from("<IIII", buf, 0)
    assert magic == _MAGIC
    off = 16
    verts = np.frombuffer(buf, np.float32, nv * 3, off).reshape(-1, 3)
    off += nv * 3 * 4
    faces = np.frombuffer(buf, np.uint32, nf * 3, off).reshape(-1, 3)
    off += nf * 3 * 4
    out = {"nv": nv, "nf": nf, "color_kind": ck, "vertices": verts, "faces": faces}
    if ck == 1:
        out["rgb"] = np.frombuffer(buf, np.uint8, nv * 3, off)
        off += nv * 3
    elif ck == 2:
        out["rmsf"] = np.frombuffer(buf, np.float32, nv, off)
        off += nv * 4

    def _block(off: int, table_key: str, index_key: str) -> int:
        """One optional ``kind · len · JSON · u32[nv]`` block. Both trailing blocks share
        this shape, which is what lets new ones be appended without a version bump."""
        (kind,) = struct.unpack_from("<I", buf, off)
        off += 4
        if kind != 1:
            return off
        (tbl_len,) = struct.unpack_from("<I", buf, off)
        off += 4
        out[table_key] = json.loads(buf[off : off + tbl_len].decode("utf-8"))
        off += tbl_len
        out[index_key] = np.frombuffer(buf, np.uint32, nv, off)
        off += nv * 4
        return off

    off = _block(off, "strand_table", "strand_index")
    off = _block(off, "nuc_table", "nuc_index")
    assert off == len(buf), f"trailing bytes: parsed {off} of {len(buf)}"
    return out


def test_pack_surface_bin_strand_block_round_trip():
    """A mesh dict with a strand-index table packs + unpacks losslessly (verts/faces/rgb +
    the strand table and per-vertex index that drive client-side recolour)."""
    data = {
        "vertices": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "faces": [0, 1, 2],
        "vertex_colors": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "vertex_strand_index_table": ["scaf", "stap"],
        "vertex_strand_index": [0, 1, 0],
    }
    got = _unpack(pack_surface_bin(data))
    assert got["nv"] == 3 and got["nf"] == 1
    assert got["color_kind"] == 1
    assert got["strand_table"] == ["scaf", "stap"]
    assert list(got["strand_index"]) == [0, 1, 0]
    np.testing.assert_allclose(got["vertices"].ravel(), data["vertices"], atol=1e-6)


def test_pack_surface_bin_no_strand_table_writes_absent_marker():
    """Without a strand table (the sim-overlay case) the blob still ends with a strand_kind=0
    marker — parseable, no dangling bytes."""
    data = {"vertices": [0.0, 0.0, 0.0], "faces": [], "vertex_colors": [0.5, 0.5, 0.5]}
    got = _unpack(pack_surface_bin(data))
    assert "strand_table" not in got


def test_pack_surface_bin_empty_is_not_ready():
    """Empty data → a 20-byte header with nv=0 (the client reads that as not-ready → null)."""
    buf = pack_surface_bin({})
    magic, nv, nf, ck = struct.unpack_from("<IIII", buf, 0)
    assert magic == _MAGIC and nv == 0


def test_design_surface_bin_matches_json_route():
    """The binary route decodes to the SAME mesh + strand table the JSON route serves, and is
    materially smaller."""
    design_state.set_design(make_6hb_design())
    client = TestClient(app)
    q = "color_mode=strand&detail=coarse"
    js = client.get(f"/api/design/surface?{q}").json()
    buf = client.get(f"/api/design/surface-bin?{q}").content
    got = _unpack(buf)

    assert got["nv"] == js["stats"]["n_verts"] and got["nf"] == js["stats"]["n_faces"]
    np.testing.assert_allclose(got["vertices"].ravel(), js["vertices"], atol=1e-4)
    assert list(got["faces"].ravel()) == list(js["faces"])
    assert got["strand_table"] == js["vertex_strand_index_table"]
    assert list(got["strand_index"]) == list(js["vertex_strand_index"])
    # binary is the more compact transfer (no per-number JSON text)
    assert len(buf) < len(json.dumps(js).encode("utf-8"))


def test_pack_surface_bin_nuc_block_round_trip():
    """The per-vertex NUCLEOTIDE block packs + unpacks losslessly, alongside the strand
    block rather than instead of it.

    This is what makes per-cluster surface colouring correct: a strand can pass through
    several clusters and the scaffold passes through nearly all of them, so a strand-keyed
    lookup paints the whole scaffold one colour (LESSONS D15)."""
    data = {
        "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
        "faces": [0, 1, 2],
        "vertex_strand_index_table": ["scaf"],
        "vertex_strand_index": [0, 0, 0],
        "vertex_nuc_index_table": ["h0:5:FORWARD", "h1:9:REVERSE"],
        "vertex_nuc_index": [0, 1, 0],
    }
    got = _unpack(pack_surface_bin(data))
    assert got["strand_table"] == ["scaf"]
    assert got["nuc_table"] == ["h0:5:FORWARD", "h1:9:REVERSE"]
    assert list(got["nuc_index"]) == [0, 1, 0]


def test_pack_surface_bin_nuc_block_absent_when_not_supplied():
    """A producer with no nucleotide identity (the oxDNA frame-surface overlay) still
    packs — the block writes its absent marker and the client falls back to strands."""
    data = {
        "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
        "faces": [0, 1, 2],
        "vertex_strand_index_table": ["scaf"],
        "vertex_strand_index": [0, 0, 0],
    }
    got = _unpack(pack_surface_bin(data))
    assert got["strand_table"] == ["scaf"]
    assert "nuc_table" not in got


def test_pack_surface_bin_is_backward_compatible_for_old_decoders():
    """An OLD decoder stops after the strand block. Adding the nucleotide block must
    therefore only ever APPEND — the bytes up to and including the strand block have to
    be byte-identical to what a pre-2026-08-01 packer produced."""
    base = {
        "vertices": [0, 0, 0, 1, 0, 0, 0, 1, 0],
        "faces": [0, 1, 2],
        "vertex_strand_index_table": ["scaf"],
        "vertex_strand_index": [0, 0, 0],
    }
    without = pack_surface_bin(base)
    with_nuc = pack_surface_bin(
        {
            **base,
            "vertex_nuc_index_table": ["h0:5:FORWARD"],
            "vertex_nuc_index": [0, 0, 0],
        }
    )
    # `without` ends with the nuc-absent marker (4 bytes); everything before it is the
    # legacy payload and must be a strict prefix of the extended one.
    assert with_nuc[: len(without) - 4] == without[: len(without) - 4]
    assert len(with_nuc) > len(without)


def test_design_surface_carries_per_vertex_nucleotide_keys():
    """The real route emits the nucleotide table, and every vertex resolves to a key of
    the app-wide `helix:bp:direction` shape."""
    design_state.set_design(make_6hb_design())
    client = TestClient(app)
    r = client.get("/api/design/surface?detail=coarse")
    assert r.status_code == 200, r.text
    js = r.json()
    tbl = js.get("vertex_nuc_index_table")
    idx = js.get("vertex_nuc_index")
    assert tbl, "surface payload carries no nucleotide table"
    assert len(idx) == len(js["vertex_strand_index"])
    for key in tbl:
        helix, bp, direction = key.rsplit(":", 2)
        assert helix and bp.isdigit()
        assert direction in ("FORWARD", "REVERSE")


def test_surface_nucleotide_keys_are_finer_than_strand_ids():
    """The whole point: a scaffold threading many helices must map to MANY nucleotide
    keys while collapsing to ONE strand id."""
    design_state.set_design(make_6hb_design())
    client = TestClient(app)
    js = client.get("/api/design/surface?detail=coarse").json()
    assert len(js["vertex_nuc_index_table"]) > len(js["vertex_strand_index_table"])
