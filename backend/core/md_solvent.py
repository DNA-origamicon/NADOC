"""Explicit solvent + periodic cell for the NAMD display path.

A solvated NADOC job simulates TIP3P water and Na+/Cl-/Mg2+ in a periodic box, but
every display path funnels through a positive DNA-resname whitelist
(``atomistic_to_nadoc._GRO_DNA_RESNAMES``, applied in ``md_trajectory``), so none of
it ever reached the viewer.  This module is the one place that reads it back.

Three things live here and nowhere else:

1. **The display affine** (:class:`DisplayXform` / :func:`apply_xform`).  Frames are
   NOT served in the simulation's own frame — ``md_trajectory`` and ``ws.py``
   reassemble the DNA across periodic images and then Kabsch-align it onto the
   design pose, so a served coordinate is
   ``(x_pre - mob_c) @ R.T + eq_centroid``.  Solvent coordinates and the box
   corners must ride the SAME map or they will not line up with the DNA.  That
   expression is computed at four call sites today (the bead and heavy-atom
   extractors in ``md_trajectory``, and both branches of ``ws.py::_seek_sync``);
   this module does not recompute it — each site hands over what it already
   built.  A fifth copy is exactly the failure mode recorded in
   ``memory/project_md_viz_tools.md``: a shared PBC-snap fix once changed nothing
   on screen because ``ws.py`` carried its own inlined copy of the snap.

2. **Solvent selection and periodic imaging.**  Water is bounded by a hydration
   shell around DNA heavy atoms (the whole box is optional and capped); ions are
   never bounded.  Both are imaged to sit beside the structure rather than
   wherever the wrap left them.

3. **The wire format** (:func:`pack_solvent_bin`).  Whole-box atomistic water on a
   large job is millions of numbers per frame — as JSON that is tens of MB and a
   ``JSON.parse`` that materialises a JS number array before it can be narrowed.
   Mirrors ``oxdna_health.pack_surface_bin`` / ``atomistic.pack_bundle_bin``.

Nothing here imports MDAnalysis at module scope: the selection helpers are plain
numpy over name/resname arrays, so the fast test suite can exercise them without
a topology.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

import numpy as np

# ── Resnames ─────────────────────────────────────────────────────────────────
# Canonical sets live in backend/core/md_charge.py (the charge audit uses them);
# imported rather than re-listed so a new ion species is added in one place.
from backend.core.md_charge import ION_RESNAMES, WATER_RESNAMES

# Hexahydrated magnesium: one MG atom plus six waters, all under resname MGH.
# The MG atom is the ion and rides the ion toggle; its six waters are water and
# ride the water toggle.  No special case anywhere — that is both less code and
# physically honest (they are ordinary waters, just tightly bound).
_MGH_RESNAME = "MGH"

# Resnames whose oxygens are water oxygens.
WATER_ISH_RESNAMES = frozenset(WATER_RESNAMES) | {_MGH_RESNAME}

# md_charge.ION_RESNAMES is the CHARMM set the charge audit counts; an AMBER-built
# package uses bare element names instead (gromacs_package._ion_names → "MG"/"CL").
# Extended here rather than in md_charge so the audit's arithmetic is untouched.
ION_ISH_RESNAMES = frozenset(ION_RESNAMES) | {"NA", "CL", "K", "CA", "CAL", "CES"}

# Species code == index.  The frontend keys its colour/radius table off this, so
# APPEND only — never reorder.
SPECIES = ("NA", "CL", "MG", "K", "CA")

# Ion CORE atom name → species.  Resolved by NAME (qualified by resname, see
# `ion_rows`) rather than by element, because MDAnalysis element-guessing from a
# name mistypes SOD→S and CLA→C — the same trap ml/propagator/windows.py:56
# documents.  Qualifying by resname additionally keeps a protein alpha-carbon
# (atom name "CA", resname ALA/GLY/…) from being read as a calcium ion.
_ION_NAME_SPECIES = {
    "SOD": "NA",
    "NA": "NA",
    "CLA": "CL",
    "CL": "CL",
    "POT": "K",
    "K": "K",
    "CES": "K",
    "MG": "MG",
    "CAL": "CA",
    "CA": "CA",
}

# Ions are never bounded by the water shell, but they still need a periodic image
# chosen.  An ion within this distance of DNA is placed beside its nearest DNA
# atom (so a Na+ condensed on a lobe that pokes past the wrap boundary does not
# jump a full box); everything further away is simply wrapped into the drawn cell.
ION_ANCHOR_CUTOFF_NM = 1.2

_MAGIC = 0x4E534C56  # "NSLV"
_VERSION = 2


# ── The display affine ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class DisplayXform:
    """How a raw simulation coordinate becomes a served (display) coordinate.

    Two stages, matching what the extractors already do:

      pre     = <periodic reassembly> + ``T_dyn``      (per-atom, caller's job)
      display = (pre - ``mob_c``) @ ``R``.T + ``eq_centroid``

    ``R is None`` means no Kabsch step ran (a frame with no box, or too few rigid
    atoms to fit); with ``mob_c``/``eq_centroid`` zero that degenerates to the
    identity, which is what those code paths do.

    ``c_box`` is the PBC-robust DNA centroid in BOX coordinates — the anchor the
    cell is drawn around, see :func:`box_corners`.
    """

    T_dyn: np.ndarray  # (3,) nm
    c_box: np.ndarray  # (3,) nm, box frame
    box_nm: np.ndarray  # (3,) nm cell lengths (zeros ⇒ no periodic box)
    mob_c: np.ndarray  # (3,) nm, pre frame
    eq_centroid: np.ndarray  # (3,) nm, design frame
    R: np.ndarray | None = None  # (3,3) or None

    @staticmethod
    def build(
        *, T_dyn, c_box, box_nm, mob_c=None, eq_centroid=None, R=None
    ) -> "DisplayXform":
        """Coerce whatever the extractors have on hand into a frozen transform."""
        z = np.zeros(3, dtype=float)
        return DisplayXform(
            T_dyn=_vec3(T_dyn, z),
            c_box=_vec3(c_box, z),
            box_nm=_vec3(box_nm, z),
            mob_c=_vec3(mob_c, z),
            eq_centroid=_vec3(eq_centroid, z),
            R=None if R is None else np.asarray(R, dtype=float).reshape(3, 3),
        )

    @property
    def has_box(self) -> bool:
        return bool(np.all(self.box_nm > 0))


def _vec3(v, default: np.ndarray) -> np.ndarray:
    if v is None:
        return default.copy()
    return np.asarray(v, dtype=float).reshape(3)


def apply_xform(pts_pre: np.ndarray, xf: DisplayXform) -> np.ndarray:
    """Map ``pre``-frame points into the served display frame.

    Byte-for-byte the expression the extractors apply to DNA
    (``md_trajectory._extract_md_atoms_frame``: ``(pos_pre - mob_c) @ R_align.T +
    eq_centroid``).  Pinned against it in tests/test_md_solvent_transform.py.
    """
    pts = np.asarray(pts_pre, dtype=float)
    if pts.size == 0:
        return pts.reshape(-1, 3)
    centred = pts - xf.mob_c
    if xf.R is not None:
        centred = centred @ xf.R.T
    return centred + xf.eq_centroid


def min_image(delta: np.ndarray, box_nm) -> np.ndarray:
    """Fold displacement vectors into the nearest periodic image. Axes with a
    non-positive box length are left alone (a non-periodic or unknown dimension)."""
    d = np.asarray(delta, dtype=float)
    if d.size == 0:
        return d.reshape(-1, 3)
    box = np.asarray(box_nm, dtype=float).reshape(3)
    good = box > 0
    if good.any():
        d = d.copy()
        d[:, good] -= np.round(d[:, good] / box[good]) * box[good]
    return d


def box_corners(xf: DisplayXform) -> np.ndarray:
    """The 8 periodic-cell corners in the DISPLAY frame, (8,3).

    Corner *k* takes the ``+`` half-length on axis *a* when bit *a* of *k* is set,
    so two corners share an edge exactly when their indices differ in one bit
    (:data:`BOX_EDGES`).

    **The origin is the structure, not the lab cell.**  A NAMD DCD stores cell
    LENGTHS but no cell origin, so there is no lab-frame origin to recover; the
    cell is drawn centred on ``c_box``, the PBC-robust DNA centroid the
    reassembly already computed.  Lengths and orientation are the simulation's
    own (so the box breathes with the barostat and rotates with the design
    alignment) — only where it sits is pinned to the solute.
    """
    if not xf.has_box:
        return np.zeros((0, 3), dtype=float)
    centre_pre = xf.c_box + xf.T_dyn
    half = xf.box_nm / 2.0
    signs = np.array(
        [[1.0 if (k >> a) & 1 else -1.0 for a in range(3)] for k in range(8)]
    )
    return apply_xform(centre_pre + signs * half, xf)


#: The 12 cuboid edges as corner-index pairs (each differs in exactly one bit).
BOX_EDGES = tuple(
    (k, k | (1 << a)) for k in range(8) for a in range(3) if not (k >> a) & 1
)


# ── Topology: which atoms are water / ions ───────────────────────────────────


def water_triplets(
    names, resnames, resindices
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split every water molecule into parallel (O, H1, H2) index arrays.

    Water oxygens are the O-named atoms of a water-ish residue — ``OH2`` in TIP3,
    ``OHA``…``OHF`` in a magnesium hexahydrate.  The MG atom of an MGH residue is
    not O-named, so it drops out here and is picked up by :func:`ion_rows`.

    Both real topologies store each molecule as a contiguous ``O, H, H`` run, which
    is what lets the wire format ship water as bare coordinates with no identity
    table.  That is ASSERTED, not assumed: any molecule that fails the contiguity
    check falls back to scanning its own residue for the next two hydrogens.
    """
    names = np.asarray(names, dtype="U8")
    resnames = np.asarray(resnames, dtype="U8")
    resindices = np.asarray(resindices, dtype=np.int64)
    n = names.shape[0]
    if n == 0:
        return (np.zeros(0, np.int64),) * 3

    is_waterish = np.isin(resnames, np.array(sorted(WATER_ISH_RESNAMES), dtype="U8"))
    o_rows = np.flatnonzero(is_waterish & np.char.startswith(names, "O"))
    if o_rows.size == 0:
        return (np.zeros(0, np.int64),) * 3

    is_h = np.char.startswith(names, "H")
    # Fast path: the two atoms right after the oxygen are its hydrogens.
    ok = o_rows + 2 < n
    h1 = np.where(ok, np.minimum(o_rows + 1, n - 1), 0)
    h2 = np.where(ok, np.minimum(o_rows + 2, n - 1), 0)
    ok &= is_h[h1] & is_h[h2]
    ok &= (resindices[h1] == resindices[o_rows]) & (
        resindices[h2] == resindices[o_rows]
    )

    if not ok.all():
        # Slow path, per offending molecule only: the next two H atoms inside the
        # oxygen's own residue, in index order.
        for k in np.flatnonzero(~ok):
            o = int(o_rows[k])
            found = [
                j for j in range(o + 1, n) if resindices[j] == resindices[o] and is_h[j]
            ][:2]
            if len(found) == 2:
                h1[k], h2[k] = found
                ok[k] = True

    keep = np.flatnonzero(ok)
    return o_rows[keep], h1[keep], h2[keep]


def ion_rows(names, resnames) -> tuple[np.ndarray, np.ndarray]:
    """Ion CORE atoms and their species codes (indices into :data:`SPECIES`).

    Qualified by resname AND name: resname alone would sweep in the six waters of
    an MGH hexahydrate, and name alone would read every protein alpha-carbon
    ("CA") as calcium.
    """
    names = np.asarray(names, dtype="U8")
    resnames = np.asarray(resnames, dtype="U8")
    if names.shape[0] == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.uint8)

    ion_res = np.isin(resnames, np.array(sorted(ION_ISH_RESNAMES), dtype="U8"))
    rows, codes = [], []
    for i in np.flatnonzero(ion_res):
        sp = _ION_NAME_SPECIES.get(str(names[i]).strip().upper())
        if sp is None:
            continue  # an MGH water, or a hydrogen on one
        rows.append(int(i))
        codes.append(SPECIES.index(sp))
    return np.asarray(rows, dtype=np.int64), np.asarray(codes, dtype=np.uint8)


def reconstruct_heavy_pre(
    heavy_ag, dna_p, pos_raw, p_raw, p_pre, box_nm, rows_cache: dict | None = None
):
    """DNA heavy-atom positions in the ``pre`` frame, from already-corrected P atoms.

    ``heavy = corrected_P + minimum_image(raw_heavy - raw_P)`` — the residue-local
    reconstruction the atomistic display already uses, hoisted here so the COARSE
    display path can produce shell anchors too.

    Without this the live CG view would have to measure its hydration shell to
    phosphates only, which is a different quantity from the trajectory view's
    heavy-atom shell — the same setting would show different water in the two
    views. Anchors are a topology question (which P owns which atom), identical
    every frame, so ``rows_cache`` memoises them per Universe; the per-frame cost
    is then one array op.

    Returns ``pos_pre`` (N,3) nm, aligned with ``heavy_ag`` order.
    """
    from backend.core.md_trajectory import _build_heavy_anchor_rows

    rows = None if rows_cache is None else rows_cache.get("_heavy_anchor_rows")
    if rows is None:
        rows = _build_heavy_anchor_rows(heavy_ag, dna_p)
        if rows_cache is not None:
            rows_cache["_heavy_anchor_rows"] = rows

    pos_pre = np.asarray(pos_raw, dtype=float).copy()
    have = rows >= 0
    if have.any():
        anchor = rows[have]
        delta = min_image(np.asarray(pos_raw)[have] - np.asarray(p_raw)[anchor], box_nm)
        pos_pre[have] = np.asarray(p_pre)[anchor] + delta
    return pos_pre


def build_solvent_ctx(universe) -> dict:
    """Resolve the solvent topology ONCE per Universe (it never changes per frame)."""
    atoms = universe.atoms
    try:
        resindices = atoms.resindices
    except Exception:  # noqa: BLE001 — a topology with no residue info
        resindices = np.zeros(len(atoms), dtype=np.int64)
    o, h1, h2 = water_triplets(atoms.names, atoms.resnames, resindices)
    irows, icodes = ion_rows(atoms.names, atoms.resnames)
    return {
        "water_o": o,
        "water_h1": h1,
        "water_h2": h2,
        "ion_rows": irows,
        "ion_species": icodes,
        "n_waters_total": int(o.size),
        "n_ions": int(irows.size),
    }


# ── Per-frame extraction ─────────────────────────────────────────────────────


def _nearest_anchor(sel_ang: np.ndarray, dna_ang: np.ndarray, cutoff_ang: float, dims):
    """(selected rows, anchor rows, distance) for points within ``cutoff_ang`` of DNA.

    Uses MDAnalysis' neighbour grid — a brute-force O(n_water · n_dna) distance
    matrix is not an option (884k waters × 300k DNA atoms).
    """
    from MDAnalysis.lib.distances import capped_distance

    if sel_ang.shape[0] == 0 or dna_ang.shape[0] == 0:
        return (np.zeros(0, np.int64),) * 2 + (np.zeros(0, float),)
    pairs, dists = capped_distance(
        sel_ang.astype(np.float32),
        dna_ang.astype(np.float32),
        max_cutoff=float(cutoff_ang),
        box=dims,
        return_distances=True,
    )
    if len(pairs) == 0:
        return (np.zeros(0, np.int64),) * 2 + (np.zeros(0, float),)
    # Sort by distance so np.unique's first-occurrence index IS the nearest DNA atom.
    order = np.argsort(dists, kind="stable")
    w_sorted = pairs[order, 0]
    uniq, first = np.unique(w_sorted, return_index=True)
    return (
        uniq.astype(np.int64),
        pairs[order, 1][first].astype(np.int64),
        dists[order][first],
    )


def _cap(sel: np.ndarray, anchors: np.ndarray, dist: np.ndarray, max_n: int | None):
    """Trim to ``max_n``, keeping the CLOSEST molecules (or an even stride when there
    are no distances). Never a bare prefix — that would silently show one corner of
    the box and look like the whole thing."""
    if max_n is None or sel.size <= max_n or max_n <= 0:
        return sel, anchors, dist, False
    if dist.size == sel.size:
        keep = np.argsort(dist, kind="stable")[:max_n]
        keep.sort()
    else:
        keep = np.linspace(0, sel.size - 1, max_n).astype(np.int64)
    return (
        sel[keep],
        anchors[keep] if anchors.size == sel.size else anchors,
        dist[keep] if dist.size == sel.size else dist,
        True,
    )


def extract_solvent_frame(
    universe,
    sctx: dict,
    dna_raw: np.ndarray,
    dna_pre: np.ndarray,
    xf: DisplayXform,
    *,
    water: bool = True,
    ions: bool = True,
    box: bool = True,
    shell_nm: float | None = 0.5,
    atomistic: bool = False,
    max_waters: int | None = None,
) -> dict:
    """Solvent + cell for the CURRENT frame of ``universe``, in the display frame.

    ``dna_raw`` / ``dna_pre`` are the DNA heavy-atom positions (nm) in the raw
    simulation frame and in the reassembled ``pre`` frame — the same arrays the
    caller already built for the DNA itself.  They are the shell anchors: each
    solvent molecule is placed beside the DNA atom it is nearest, which both
    chooses its periodic image and guarantees the shell survives the display
    transform (a rotation is an isometry, so "within 5 Å of that atom" is true
    before and after).

    ``shell_nm=None`` selects the whole cell instead, imaged around ``c_box``.
    """
    # `n_ions` / `has_box` describe what this payload ACTUALLY CONTAINS, not what the
    # system contains — the reader walks the frame blocks by them, so a header that
    # advertises ions or a cell that were never written desynchronises every
    # subsequent read. (That is exactly how Water-alone and Ions-alone shipped
    # broken: only the all-on combination happened to line up.) Totals travel
    # separately, as `*_total`.
    out: dict = {
        "n_waters_total": sctx["n_waters_total"],
        "n_ions_total": sctx["n_ions"],
        "n_ions": 0,
        "has_box": False,
        "atomistic": bool(atomistic),
        "capped": False,
        "shell_nm": shell_nm,
        "n_water": 0,
    }
    dims = getattr(universe, "dimensions", None)
    pos_all = universe.atoms.positions

    # ── Water ────────────────────────────────────────────────────────────────
    if water and sctx["n_waters_total"]:
        o_rows = sctx["water_o"]
        o_raw = pos_all[o_rows] / 10.0
        if shell_nm is not None and dna_raw.shape[0]:
            sel, anchor, dist = _nearest_anchor(
                o_raw * 10.0, dna_raw * 10.0, shell_nm * 10.0, dims
            )
            sel, anchor, dist, capped = _cap(sel, anchor, dist, max_waters)
            o_sel = o_raw[sel]
            o_pre = dna_pre[anchor] + min_image(o_sel - dna_raw[anchor], xf.box_nm)
        else:
            sel = np.arange(o_rows.size, dtype=np.int64)
            sel, _a, _d, capped = _cap(sel, sel, np.zeros(0), max_waters)
            o_sel = o_raw[sel]
            # Whole cell: image every molecule around the DNA centroid, i.e. into
            # exactly the box that box_corners() draws.
            o_pre = (xf.c_box + xf.T_dyn) + min_image(o_sel - xf.c_box, xf.box_nm)
        out["capped"] = out["capped"] or capped
        out["n_water"] = int(sel.size)

        if atomistic and sel.size:
            # H rides the same displacement as its O. The intramolecular O–H
            # vector is min-imaged too: in raw coordinates a molecule can straddle
            # the cell boundary, and at ~0.096 nm the nearest image is always the
            # real bond.
            h1_raw = pos_all[sctx["water_h1"][sel]] / 10.0
            h2_raw = pos_all[sctx["water_h2"][sel]] / 10.0
            h1_pre = o_pre + min_image(h1_raw - o_sel, xf.box_nm)
            h2_pre = o_pre + min_image(h2_raw - o_sel, xf.box_nm)
            mol = np.empty((sel.size, 9), dtype=np.float32)
            mol[:, 0:3] = apply_xform(o_pre, xf)
            mol[:, 3:6] = apply_xform(h1_pre, xf)
            mol[:, 6:9] = apply_xform(h2_pre, xf)
            out["water"] = mol.reshape(-1)
        else:
            out["water"] = apply_xform(o_pre, xf).astype(np.float32).reshape(-1)
    else:
        out["water"] = np.zeros(0, dtype=np.float32)

    # ── Ions (never bounded) ─────────────────────────────────────────────────
    if ions and sctx["n_ions"]:
        irows = sctx["ion_rows"]
        i_raw = pos_all[irows] / 10.0
        i_pre = (xf.c_box + xf.T_dyn) + min_image(i_raw - xf.c_box, xf.box_nm)
        if dna_raw.shape[0]:
            sel, anchor, _d = _nearest_anchor(
                i_raw * 10.0, dna_raw * 10.0, ION_ANCHOR_CUTOFF_NM * 10.0, dims
            )
            if sel.size:
                i_pre[sel] = dna_pre[anchor] + min_image(
                    i_raw[sel] - dna_raw[anchor], xf.box_nm
                )
        out["ions"] = apply_xform(i_pre, xf).astype(np.float32).reshape(-1)
        out["ion_species"] = sctx["ion_species"]
        out["n_ions"] = int(sctx["n_ions"])
    else:
        out["ions"] = np.zeros(0, dtype=np.float32)
        out["ion_species"] = np.zeros(0, dtype=np.uint8)

    # ── Cell ─────────────────────────────────────────────────────────────────
    corners = box_corners(xf) if box else np.zeros((0, 3))
    out["box"] = corners.astype(np.float32).reshape(-1)
    out["has_box"] = corners.shape[0] == 8
    return out


# ── Wire format ──────────────────────────────────────────────────────────────


def pack_solvent_bin(frames: dict, meta: dict | None = None) -> bytes:
    """Pack ``{composite_frame_index: extract_solvent_frame(...)}`` into one blob.

    Layout (little-endian; every float block lands on a 4-byte boundary because
    the JSON header is zero-padded up to one)::

        u32 magic 0x4E534C56 "NSLV" · u32 version · u32 n_frames · u32 reserved
        u32 header_len · header_len bytes UTF-8 JSON · zero pad to 4
        per frame, in the header's frame_ids order:
            f32[per_frame_nw[i] * (atomistic ? 9 : 3)]  water  (O,H,H per molecule)
            f32[n_ions * 3]                     ions, omitted entirely when n_ions == 0
            f32[24]                             8 box corners, only when has_box
            f32[n_serials * 3]                  DNA, only when n_serials > 0

    EVERY block is optional and the header alone says which are present:
    ``per_frame_nw`` / ``n_ions`` / ``has_box`` / ``n_serials`` are the counts of
    what was WRITTEN, not of what the system contains (totals ride separately as
    ``n_waters_total`` / ``n_ions_total``). The reader walks the blocks by those
    numbers, so a header that advertises a block the packer skipped puts every
    later read at the wrong offset — which is precisely how Water-alone and
    Ions-alone shipped broken in v1, while all-three-on happened to line up.

    The optional trailing DNA block is the ``include_dna`` piggyback: serial-indexed
    flat coordinates in the same shape ``md_frames_atomistic(positions_only=True)``
    returns, so an atomistic-rep scrub gets DNA and solvent from ONE request and
    pays the ~30 s MDAnalysis context build once instead of twice.  It is binary
    like everything else — routing 10^6 DNA coordinates through the JSON header
    would give back exactly the parse cost this format exists to avoid.

    ``n_frames == 0`` is the "nothing to draw" payload (a bare 20-byte header),
    which is what the routes return for a job with no trajectory yet.
    """
    ids = sorted(frames.keys(), key=lambda k: int(k))
    header = {
        "frame_ids": [int(k) for k in ids],
        "atomistic": False,
        "n_waters_total": 0,
        "n_ions": 0,
        "shell_nm": None,
        "capped": False,
        "n_ions_total": 0,
        "has_box": False,
        "species_table": list(SPECIES),
        "ion_species": [],
        "per_frame_nw": [],
        "n_serials": 0,
        **(meta or {}),
    }
    blocks: list[bytes] = []
    n_serials = int(header["n_serials"])
    for k in ids:
        f = frames[k]
        header["atomistic"] = bool(f.get("atomistic", header["atomistic"]))
        header["n_waters_total"] = int(
            f.get("n_waters_total", header["n_waters_total"])
        )
        header["n_ions"] = int(f.get("n_ions", header["n_ions"]))
        header["n_ions_total"] = int(f.get("n_ions_total", header["n_ions_total"]))
        header["has_box"] = bool(header["has_box"] or f.get("has_box"))
        header["capped"] = bool(header["capped"] or f.get("capped"))
        if f.get("shell_nm") is not None:
            header["shell_nm"] = float(f["shell_nm"])
        if not header["ion_species"] and f.get("ion_species") is not None:
            header["ion_species"] = [
                int(c) for c in np.asarray(f["ion_species"]).ravel()
            ]
        header["per_frame_nw"].append(int(f.get("n_water", 0)))
        for key in ("water", "ions", "box"):
            blocks.append(np.asarray(f.get(key, []), dtype=np.float32).tobytes())
        # A frame that skipped a block the header claims is present would desync the
        # reader; assert the two agree rather than shipping a silently unreadable blob.
        assert np.asarray(f.get("ions", [])).size == 3 * int(f.get("n_ions", 0)), (
            "ion block size disagrees with the header's n_ions"
        )
        assert np.asarray(f.get("box", [])).size == (24 if f.get("has_box") else 0), (
            "box block size disagrees with the header's has_box"
        )
        if n_serials:
            d = np.zeros(n_serials * 3, dtype=np.float32)
            src = np.asarray(f.get("dna", []), dtype=np.float32).ravel()
            d[: src.size] = src[: d.size]
            blocks.append(d.tobytes())

    hb = json.dumps(header, separators=(",", ":")).encode("utf-8")
    pad = (-len(hb)) % 4
    return (
        struct.pack("<IIII", _MAGIC, _VERSION, len(ids), 0)
        + struct.pack("<I", len(hb))
        + hb
        + b"\x00" * pad
        + b"".join(blocks)
    )


def empty_solvent_bin() -> bytes:
    """The 'no trajectory / not ready' payload."""
    return pack_solvent_bin({})
