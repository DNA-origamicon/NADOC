"""Strand-topology checks at crossover junctions.

The atomistic seed builder can produce a junction whose two crossover backbones are
**catenated** — wound around one another with Gauss linking number ``Lk = ±1`` instead
of passing cleanly (``Lk = 0``).  That is non-physical: a real Holliday junction does
not have its two crossover strands interlocked, and because a linking number is a
topological invariant, no amount of minimisation or MD can undo it.  A catenated seed
stays catenated through every relaxation stage and silently corrupts every observable
derived from it.

Base-pairing health checks do not see this at all (a catenated 2hb junction reported
``c1_paired_fraction = 1.0``), so it needs its own detector.

Layer note (CLAUDE.md Three-Layer Law): this module READS the geometric layer and the
topological layer.  It never writes either.

Public API
──────────
``crossover_connectors(design)``  — topological: every point where a strand hops helices
``reciprocal_pairs(connectors)``  — the antiparallel pairs that share a junction
``gauss_linking_number(a, b)``    — Lk between two closed polylines
``catenation_report(design, ...)``— the audit, schema ``nadoc.junction_catenation.v1``
``catenation_over_frames(...)``   — the same audit across a trajectory
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

import numpy as np

# Backbone atoms in 5'→3' order.  The connector polyline walks these through every
# residue between (and including) the two nucleotides flanking the junction.
_BACKBONE_ORDER = ("P", "O5'", "C5'", "C4'", "C3'", "O3'")

# |Lk| above this counts as catenated.  A clean junction returns ~0 and a catenated one
# ~±1, so the midpoint is a wide margin.
_LK_CATENATED = 0.5

# Two connectors further apart than this (centroid separation, nm) cannot be linked —
# each spans an inter-helix gap of ~2.5 nm, so 2.5 nm of slack is generous.
_PROXIMITY_NM = 2.5

# A chord-closed open curve only yields a meaningful linking number if the result is
# close to an integer.  A non-integer Lk means the straight closure chord itself passes
# through the partner loop and the answer is an artefact of the closure, not topology.
_INTEGRALITY_TOL = 0.15

_CLOSURE_SUBDIV = 40

SCHEMA = "nadoc.junction_catenation.v1"


class CatenatedJunctionError(RuntimeError):
    """Raised when a build would ship a topologically catenated junction."""

    def __init__(self, report: dict):
        self.report = report
        n = report.get("n_catenated", 0)
        detail = "; ".join(
            f"{c['helices'][0]}/{c['helices'][1]} bp{c['bp'][0]}-{c['bp'][1]} Lk={c['lk']:+.0f}"
            for c in report.get("catenated", [])[:5]
        )
        super().__init__(
            f"{n} catenated crossover junction(s) in the atomistic build: {detail}. "
            f"The two crossover backbones are wound around each other (linking number "
            f"!= 0); MD cannot undo this. Rebuild with a non-catenating extra-base "
            f"placement, or pass allow_catenated=True / NADOC_ALLOW_CATENATED=1 to "
            f"override deliberately."
        )


# ── Topology ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Connector:
    """One point where a strand leaves one helix and enters another.

    ``from_*`` is the 3' exit (the last nucleotide of the outgoing domain) and ``to_*``
    the 5' entry (the first nucleotide of the incoming domain).  Any inserted extra
    bases sit between them, addressed as ``(crossover_id, k)`` for ``k`` in
    ``range(n_inserts)``.
    """

    strand_id: str
    from_helix: str
    from_bp: int
    from_dir: str
    to_helix: str
    to_bp: int
    to_dir: str
    crossover_id: Optional[str] = None
    n_inserts: int = 0

    @property
    def helices(self) -> frozenset:
        return frozenset((self.from_helix, self.to_helix))


def _dir_value(d) -> str:
    return d.value if hasattr(d, "value") else str(d)


def _junction_index(design) -> dict:
    """(helix_id, bp, direction) pair → (crossover_id, extra_bases).

    Covers both ``design.crossovers`` and ``design.forced_ligations`` (which carry
    inserts through the same builder).  Keyed by the unordered pair of halves so it
    matches regardless of which half the strand exits from.
    """
    idx: dict = {}
    for xo in getattr(design, "crossovers", None) or []:
        ka = (xo.half_a.helix_id, xo.half_a.index, _dir_value(xo.half_a.strand))
        kb = (xo.half_b.helix_id, xo.half_b.index, _dir_value(xo.half_b.strand))
        idx[frozenset((ka, kb))] = (xo.id, xo.extra_bases or "")
    for fl in getattr(design, "forced_ligations", None) or []:
        ka = (
            fl.three_prime_helix_id,
            fl.three_prime_bp,
            _dir_value(fl.three_prime_direction),
        )
        kb = (
            fl.five_prime_helix_id,
            fl.five_prime_bp,
            _dir_value(fl.five_prime_direction),
        )
        idx[frozenset((ka, kb))] = (fl.id, fl.extra_bases or "")
    return idx


def crossover_connectors(design) -> list[Connector]:
    """Every inter-helix hop in the design, walked from the strand domain list.

    Purely topological — no geometry is touched.
    """
    junctions = _junction_index(design)
    out: list[Connector] = []
    for strand in design.strands:
        doms = strand.domains
        for i in range(len(doms) - 1):
            a, b = doms[i], doms[i + 1]
            if a.helix_id == b.helix_id:
                continue  # same-helix domain split, not a crossover
            ka = (a.helix_id, a.end_bp, _dir_value(a.direction))
            kb = (b.helix_id, b.start_bp, _dir_value(b.direction))
            xo_id, extra = junctions.get(frozenset((ka, kb)), (None, ""))
            out.append(
                Connector(
                    strand_id=strand.id,
                    from_helix=a.helix_id,
                    from_bp=a.end_bp,
                    from_dir=_dir_value(a.direction),
                    to_helix=b.helix_id,
                    to_bp=b.start_bp,
                    to_dir=_dir_value(b.direction),
                    crossover_id=xo_id,
                    n_inserts=len(extra),
                )
            )
    return out


def reciprocal_pairs(connectors: Sequence[Connector]) -> list[tuple[int, int]]:
    """Index pairs forming an antiparallel reciprocal crossover.

    Two connectors are reciprocal when they join the same two helices at adjacent bp
    and exit from *opposite* helices — the classic immobile Holliday junction.
    """
    out: list[tuple[int, int]] = []
    for i in range(len(connectors)):
        for j in range(i + 1, len(connectors)):
            a, b = connectors[i], connectors[j]
            if a.helices != b.helices or len(a.helices) != 2:
                continue
            if a.from_helix == b.from_helix:
                continue  # same 3' exit helix → parallel, not reciprocal
            if abs(a.from_bp - b.from_bp) > 1:
                continue
            out.append((i, j))
    return out


# ── Geometry ──────────────────────────────────────────────────────────────────


def _atom_index(model) -> tuple[dict, dict]:
    """(nucleotide key → {atom name: row}, insert key → {atom name: row}).

    Row = the atom's index in ``model.atoms``, which is also its index into any
    position array captured from that model.
    """
    nuc: dict = {}
    ins: dict = {}
    for row, at in enumerate(model.atoms):
        if at.name not in _BACKBONE_ORDER:
            continue
        if at.crossover_id is not None and at.extra_base_k is not None:
            ins.setdefault((at.crossover_id, at.extra_base_k), {})[at.name] = row
        elif at.extension_id is None:
            key = (
                at.strand_id,
                at.helix_id,
                at.bp_index,
                at.direction,
                at.copy_k if at.copy_k else 0,
            )
            nuc.setdefault(key, {})[at.name] = row
    return nuc, ins


def _connector_rows(conn: Connector, nuc: dict, ins: dict) -> list[int]:
    """Backbone atom rows along the connector, 5'→3', or [] if incomplete."""
    residues: list[dict] = []
    a = nuc.get((conn.strand_id, conn.from_helix, conn.from_bp, conn.from_dir, 0))
    if a is None:
        return []
    residues.append(a)
    for k in range(conn.n_inserts):
        e = ins.get((conn.crossover_id, k)) if conn.crossover_id else None
        if e is None:
            return []
        residues.append(e)
    b = nuc.get((conn.strand_id, conn.to_helix, conn.to_bp, conn.to_dir, 0))
    if b is None:
        return []
    residues.append(b)

    rows: list[int] = []
    for res in residues:
        for name in _BACKBONE_ORDER:
            r = res.get(name)
            if r is not None:
                rows.append(r)
    return rows


def _close_loop(path: np.ndarray, subdiv: int = _CLOSURE_SUBDIV) -> np.ndarray:
    """Close an open polyline with a straight chord from its end back to its start."""
    if len(path) < 2:
        return path
    ts = np.linspace(0.0, 1.0, subdiv)[1:]
    chord = path[-1] + (path[0] - path[-1]) * ts[:, None]
    return np.vstack([path, chord])


def _unit(v: np.ndarray) -> np.ndarray:
    """Row-wise normalise, leaving degenerate rows as zero (they contribute nothing)."""
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v), where=n > 1e-12)


def gauss_linking_number(path_a: np.ndarray, path_b: np.ndarray) -> float:
    """Gauss linking number between two CLOSED polylines.

    ±1 for a Hopf link, 0 for unlinked curves.  Inputs must already be closed (see
    :func:`_close_loop`).

    Klenin-Langowski exact solid-angle form, evaluated over all segment pairs at once —
    Phase-5 trajectory scans call this thousands of times, so the pairwise loop is
    broadcast rather than iterated.
    """
    a = np.asarray(path_a, dtype=float)
    b = np.asarray(path_b, dtype=float)
    if len(a) < 2 or len(b) < 2:
        return 0.0

    r1 = a[:-1, None, :]  # (na, 1, 3) segment starts of A
    r2 = a[1:, None, :]  # (na, 1, 3) segment ends of A
    r3 = b[None, :-1, :]  # (1, nb, 3) segment starts of B
    r4 = b[None, 1:, :]  # (1, nb, 3) segment ends of B

    r13 = r3 - r1
    r14 = r4 - r1
    r23 = r3 - r2
    r24 = r4 - r2

    n1 = _unit(np.cross(r13, r14))
    n2 = _unit(np.cross(r14, r24))
    n3 = _unit(np.cross(r24, r23))
    n4 = _unit(np.cross(r23, r13))

    def _asin_dot(p, q):
        return np.arcsin(np.clip(np.einsum("ijk,ijk->ij", p, q), -1.0, 1.0))

    omega = (
        _asin_dot(n1, n2) + _asin_dot(n2, n3) + _asin_dot(n3, n4) + _asin_dot(n4, n1)
    )
    sign = np.sign(np.einsum("ijk,ijk->ij", np.cross(r4 - r3, r2 - r1), r13))
    return float(np.sum(omega * sign) / (4.0 * np.pi))


def _min_segment_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Closest approach between two polylines (endpoint-clamped segment distance)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 2 or len(b) < 2:
        return float("inf")

    p1 = a[:-1, None, :]
    u = (a[1:] - a[:-1])[:, None, :]
    q1 = b[None, :-1, :]
    v = (b[1:] - b[:-1])[None, :, :]
    w = p1 - q1

    dot = lambda x, y: np.einsum(
        "ijk,ijk->ij",
        np.broadcast_to(x, np.broadcast_shapes(x.shape, y.shape)),
        np.broadcast_to(y, np.broadcast_shapes(x.shape, y.shape)),
    )
    uu, uv, vv = dot(u, u), dot(u, v), dot(v, v)
    uw, vw = dot(u, w), dot(v, w)

    den = uu * vv - uv * uv
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = np.where(
            den > 1e-12, (uv * vw - vv * uw) / np.where(den > 1e-12, den, 1.0), 0.0
        )
        tc = np.where(
            den > 1e-12,
            (uu * vw - uv * uw) / np.where(den > 1e-12, den, 1.0),
            np.where(
                np.abs(uv) > 1e-12, uw / np.where(np.abs(uv) > 1e-12, uv, 1.0), 0.0
            ),
        )
    sc = np.clip(sc, 0.0, 1.0)[..., None]
    tc = np.clip(tc, 0.0, 1.0)[..., None]

    diff = (p1 + sc * u) - (q1 + tc * v)
    return float(np.min(np.linalg.norm(diff, axis=-1)))


# ── Report ────────────────────────────────────────────────────────────────────


@dataclass
class _Prepared:
    connectors: list[Connector]
    open_paths: dict  # connector index → open polyline
    closed_paths: dict  # connector index → chord-closed polyline
    centroids: dict


def _prepare(design, model, positions) -> _Prepared:
    nuc, ins = _atom_index(model)
    if positions is None:
        pos = np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
    else:
        pos = np.asarray(positions, dtype=float)
        if pos.shape[0] != len(model.atoms):
            raise ValueError(
                f"positions has {pos.shape[0]} rows but the model has "
                f"{len(model.atoms)} atoms"
            )
    connectors = crossover_connectors(design)
    open_paths: dict = {}
    closed_paths: dict = {}
    centroids: dict = {}
    for k, conn in enumerate(connectors):
        rows = _connector_rows(conn, nuc, ins)
        if len(rows) < 3:
            continue
        p = pos[rows]
        open_paths[k] = p
        closed_paths[k] = _close_loop(p)
        centroids[k] = p.mean(axis=0)
    return _Prepared(connectors, open_paths, closed_paths, centroids)


def _residue_lookup(model):
    """key -> {atom name: row}. Keys: ``("nt", strand, helix, bp, dir)`` or
    ``("xb", crossover_id, k)``. Shared by both winding channels."""
    table: dict = {}
    for row, at in enumerate(model.atoms):
        if at.name not in _BACKBONE_ORDER:
            continue
        if at.crossover_id is not None and at.extra_base_k is not None:
            key = ("xb", at.crossover_id, at.extra_base_k)
        elif at.extension_id is None:
            key = ("nt", at.strand_id, at.helix_id, at.bp_index, at.direction)
        else:
            continue
        table.setdefault(key, {})[at.name] = row
    return lambda k: table.get(k)


def _connector_dict(c: Connector) -> dict:
    return {
        "strand_id": c.strand_id,
        "from_helix": c.from_helix,
        "from_bp": c.from_bp,
        "from_dir": c.from_dir,
        "to_helix": c.to_helix,
        "to_bp": c.to_bp,
        "to_dir": c.to_dir,
        "crossover_id": c.crossover_id,
        "n_inserts": c.n_inserts,
    }


def catenation_report(
    design,
    *,
    model=None,
    positions=None,
    proximity_nm: float = _PROXIMITY_NM,
    max_report: int = 200,
) -> dict:
    """Audit every crossover junction for catenated backbones.

    ``positions`` (an ``(n_atoms, 3)`` array in the model's own atom order) overrides
    the model's own coordinates — that is how a trajectory frame is measured without
    rebuilding.  Otherwise the supplied ``model`` is used, and if that is ``None`` one
    is built from ``design``.

    Tests EVERY pair of connectors within ``proximity_nm`` rather than only the
    topologically reciprocal ones: the wide net costs little and does not assume the
    failure mode.  Each hit records whether it was a reciprocal pair.
    """
    if model is None:
        from backend.core.atomistic import build_atomistic_model

        model = build_atomistic_model(design)

    prep = _prepare(design, model, positions)
    lookup = _residue_lookup(model)
    pos_all = (
        np.asarray(positions, dtype=float)
        if positions is not None
        else np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=float)
    )
    recip = {frozenset(p) for p in reciprocal_pairs(prep.connectors)}

    catenated: list[dict] = []
    n_tested = 0
    n_ambiguous = 0
    keys = sorted(prep.closed_paths)
    for ii in range(len(keys)):
        for jj in range(ii + 1, len(keys)):
            i, j = keys[ii], keys[jj]
            if (
                float(np.linalg.norm(prep.centroids[i] - prep.centroids[j]))
                > proximity_nm
            ):
                continue
            n_tested += 1
            # The verdict comes from the TWO-CHANNEL winding measure — closure-free PCS
            # plus the duplex clamp.  It deliberately does NOT come from a straight-chord
            # Lk: that chord flipped +1 -> 0 -> -1 across three MD stages of a structure
            # that never changed, with zero integrality residual, so the residual guard
            # below could not catch it.  The chord value is still computed and reported,
            # as a legacy diagnostic only.
            from backend.core.junction_winding import (  # noqa: PLC0415
                clamp_sweep,
                combine,
                projected_crossing_number,
            )

            pcs = projected_crossing_number(prep.open_paths[i], prep.open_paths[j])
            clamp = clamp_sweep(
                lookup,
                pos_all,
                _connector_dict(prep.connectors[i]),
                _connector_dict(prep.connectors[j]),
                _BACKBONE_ORDER,
            )
            winding = combine(pcs, clamp)

            lk = gauss_linking_number(prep.closed_paths[i], prep.closed_paths[j])
            residual = abs(lk - round(lk))
            ambiguous = winding["verdict"] == "ambiguous"
            if ambiguous:
                n_ambiguous += 1
            if winding["verdict"] != "wound":
                continue
            a, b = prep.connectors[i], prep.connectors[j]
            if len(catenated) < max_report:
                catenated.append(
                    {
                        "verdict": winding["verdict"],
                        "confidence": winding["confidence"],
                        "pcs_n_mode": winding["pcs"]["n_mode"],
                        "pcs_f_hi": round(winding["pcs"]["f_hi"], 3),
                        "clamp_lk": winding["clamp"].get("lk"),
                        "clamp_lk_by_k": winding["clamp"].get("lk_by_k"),
                        "clamp_converged": winding["clamp"].get("converged"),
                        "lk": round(lk, 4),
                        "lk_int": int(round(lk)),
                        "lk_residual": round(residual, 4),
                        "reciprocal": frozenset((i, j)) in recip,
                        "crossover_ids": [a.crossover_id, b.crossover_id],
                        "strand_ids": [a.strand_id, b.strand_id],
                        "helices": [a.from_helix, a.to_helix],
                        "bp": [a.from_bp, b.from_bp],
                        "n_inserts": [a.n_inserts, b.n_inserts],
                        "min_backbone_dist_nm": round(
                            _min_segment_distance(
                                prep.open_paths[i], prep.open_paths[j]
                            ),
                            4,
                        ),
                    }
                )

    return {
        "schema": SCHEMA,
        "ok": not catenated,
        "n_connectors": len(prep.connectors),
        "n_connectors_measured": len(prep.closed_paths),
        "n_pairs_tested": n_tested,
        "n_reciprocal_pairs": len(recip),
        "n_catenated": len(catenated),
        "n_closure_ambiguous": n_ambiguous,
        "catenated": catenated,
    }


def design_has_extra_bases(design) -> bool:
    """True if any crossover or forced ligation inserts extra bases.

    Cheap topological pre-check: a design without inserts has never been observed to
    catenate (0/28 pairs on every noT build), so the gate can skip building a model.
    """
    for xo in getattr(design, "crossovers", None) or []:
        if xo.extra_bases:
            return True
    for fl in getattr(design, "forced_ligations", None) or []:
        if fl.extra_bases:
            return True
    return False


def assert_not_catenated(
    design, *, model=None, positions=None, allow: bool = False
) -> dict:
    """Build gate: raise :class:`CatenatedJunctionError` unless ``allow``.

    Returns the report either way so the caller can record it — the report goes into the
    package manifest on every build, whether it passed or was overridden.
    """
    report = catenation_report(design, model=model, positions=positions)
    report["override_used"] = bool(allow and not report["ok"])
    if not report["ok"] and not allow:
        raise CatenatedJunctionError(report)
    return report


def gate_seed_topology(design, *, model=None, allow: bool = False) -> dict:
    """The build gate as the packagers call it.

    Skips the model build entirely for designs with no inserted bases (the common case)
    and returns a ``skipped`` verdict, so an ordinary design pays nothing.  ``model``
    should be the model that will actually ship, so a seeded run is gated on its own
    seed rather than on a freshly built one.
    """
    if model is None and not design_has_extra_bases(design):
        return {
            "schema": SCHEMA,
            "gate": "skipped_no_extra_bases",
            "ok": True,
            "n_catenated": 0,
            "n_ring_pierced": 0,
            "override_requested": bool(allow),
        }
    if model is None:  # build once; both checks measure the same seed
        from backend.core.atomistic import build_atomistic_model  # noqa: PLC0415

        model = build_atomistic_model(design)
    report = assert_not_catenated(design, model=model, allow=allow)

    # Second, independent topological defect: a covalent bond threaded through a sugar
    # or base ring.  The connector polyline this module walks takes the C4'->C3' step,
    # so a threaded ring changes no linking number and the check above cannot see it —
    # they have to run together.  Measured on 2hb_2xT job c8c4a87e2033: catenation
    # clean, one phosphodiester bond through a partner insert's ribose, which the
    # relaxation could only convert into a permanently 3.08 A bond.
    from backend.core.ring_piercing import assert_not_pierced  # noqa: PLC0415

    pierce = assert_not_pierced(design, model=model, allow=allow)
    report["n_ring_pierced"] = pierce["n_pierced"]
    report["ring_pierced"] = pierce["pierced"][:20]
    report["ring_piercing_schema"] = pierce["schema"]
    report["ok"] = bool(report["ok"] and pierce["ok"])
    report["override_used"] = bool(
        report.get("override_used") or pierce["override_used"]
    )

    report["gate"] = "overridden" if report.get("override_used") else "passed"
    report["override_requested"] = bool(allow)
    return report


def package_connector_rows(design, package_pdb: "str | Path") -> list[dict]:
    """Map each crossover connector onto ROW INDICES of a NAMD package PDB.

    A psfgen PSF interleaves hydrogens, so the heavy-atom ``AtomisticModel`` order does
    NOT line up with the on-disk PDB/PSF/DCD rows — anything that assumes it does is
    silently measuring the wrong atoms.  The package's own ``{stem}.pdb`` IS in PSF/DCD
    row order, so the robust bridge is to read the connector atoms straight out of it.

    Chains are emitted one per strand in ``design.strands`` order (segids D000, D001, …)
    with residues numbered 1..N in 5'->3' order, inserts included — the same walk
    :func:`crossover_connectors` performs.  The residue count per chain is verified
    against that walk, so a layout change fails loudly instead of returning nonsense.

    Returns one dict per connector: ``{"connector", "rows"}`` where ``rows`` indexes the
    frame's coordinate array.
    """
    # (segid, resid, atom name) -> row index, and per-segid residue count
    rows: dict = {}
    per_seg: dict = {}
    n = 0
    for line in Path(package_pdb).read_text().splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        row = n
        n += 1
        seg = line[72:76].strip()
        if not seg.startswith("D"):
            continue
        resid = int(line[22:26])
        rows[(seg, resid, line[12:16].strip())] = row
        per_seg.setdefault(seg, set()).add(resid)

    segnames = sorted(per_seg)
    junctions = _junction_index(design)
    out: list[dict] = []

    for si, strand in enumerate(design.strands):
        if si >= len(segnames):
            break
        seg = segnames[si]
        # Walk this strand 5'->3', assigning residue numbers exactly as the builder did.
        resid = 0
        doms = strand.domains
        marks: list = []  # (kind, resid) with kind in {"nt", "insert"}
        for di, dom in enumerate(doms):
            step = 1 if dom.end_bp >= dom.start_bp else -1
            for _bp in range(dom.start_bp, dom.end_bp + step, step):
                resid += 1
                marks.append(
                    ("nt", resid, dom.helix_id, _bp, _dir_value(dom.direction))
                )
            if di + 1 < len(doms):
                nxt = doms[di + 1]
                ka = (dom.helix_id, dom.end_bp, _dir_value(dom.direction))
                kb = (nxt.helix_id, nxt.start_bp, _dir_value(nxt.direction))
                _xid, extra = junctions.get(frozenset((ka, kb)), (None, ""))
                for _ in extra:
                    resid += 1
                    marks.append(("insert", resid, None, None, None))
        if resid != len(per_seg[seg]):
            raise ValueError(
                f"{seg}: walked {resid} residues but the package PDB has "
                f"{len(per_seg[seg])} — package residue layout changed"
            )

        # Emit a connector for every helix hop, gathering its backbone rows.
        for k in range(len(marks) - 1):
            kind, rid, hel, bp, dirn = marks[k]
            if kind != "nt":
                continue
            j = k + 1
            while j < len(marks) and marks[j][0] == "insert":
                j += 1
            if j >= len(marks):
                continue
            if marks[j][2] == hel:
                continue  # same helix: not a crossover
            span = [rid] + [marks[m][1] for m in range(k + 1, j)] + [marks[j][1]]
            idxs = [
                rows[(seg, r, nm)]
                for r in span
                for nm in _BACKBONE_ORDER
                if (seg, r, nm) in rows
            ]
            out.append(
                {
                    "strand_id": strand.id,
                    "segid": seg,
                    "from_helix": hel,
                    "from_bp": bp,
                    "from_dir": dirn,
                    "to_helix": marks[j][2],
                    "to_bp": marks[j][3],
                    "n_inserts": j - k - 1,
                    "rows": idxs,
                }
            )
    return out


def read_namd_coor(path: "str | Path") -> np.ndarray:
    """NAMD binary restart coordinates -> (n_atoms, 3) in Angstroms."""
    import struct

    data = Path(path).read_bytes()
    n = struct.unpack("<i", data[:4])[0]
    return np.frombuffer(data[4 : 4 + n * 24], dtype="<f8").reshape(n, 3).copy()


def catenation_in_frame(
    connectors: list[dict],
    coords: np.ndarray,
    proximity_ang: float = 25.0,
    reference: "dict | None" = None,
) -> dict:
    """Topology report for one simulated frame (coords in the PDB's row order).

    Distances are in Angstroms here (NAMD's unit), unlike the nm-based design build —
    ``Lk`` itself is scale-free, so only the proximity cutoff cares.

    **Read the closed ``lk`` on a thermalised frame with care.**  These are OPEN backbone
    arcs closed by an artificial straight chord.  On the ideal build that closure is
    well conditioned (every noT design returns 0, and a catenated build returns a stable
    +/-1), but once MD has jiggled the structure the chord can sweep across the partner
    curve and flip ``lk`` by exactly +/-1 with **zero integrality residual** — so the
    residual check does NOT catch this.  Observed on a real 2hb_2xT run: lk went
    +1 -> 0 -> -1 across three stages while nothing physical happened.

    ``g_open`` is the same Gauss double integral over the UNCLOSED arcs.  It is a
    continuous function of the coordinates, so it cannot jump without atoms moving:
    a genuine strand passage shifts it by ~1, thermal motion by ~0.05.  Pass
    ``reference`` (``{pair_key: g_open}``, normally taken from the seed frame) to get
    ``delta_g`` and a ``changed`` flag per pair.

    So: the SEED measurement establishes whether a pair is catenated; the trajectory
    measurement establishes whether that ever CHANGED.
    """
    paths, cents = {}, {}
    for i, c in enumerate(connectors):
        if len(c["rows"]) < 3:
            continue
        p = coords[c["rows"]]
        paths[i] = p
        cents[i] = p.mean(axis=0)

    linked: list = []
    changed: list = []
    gauss: dict = {}
    tested = 0
    keys = sorted(paths)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            i, j = keys[a], keys[b]
            if float(np.linalg.norm(cents[i] - cents[j])) > proximity_ang:
                continue
            tested += 1
            lk = gauss_linking_number(_close_loop(paths[i]), _close_loop(paths[j]))
            g_open = gauss_linking_number(paths[i], paths[j])
            ci, cj = connectors[i], connectors[j]
            key = f"{ci['segid']}:{ci['from_bp']}|{cj['segid']}:{cj['from_bp']}"
            gauss[key] = round(g_open, 4)

            row = {
                "pair": key,
                "lk": round(lk, 4),
                "lk_int": int(round(lk)),
                "g_open": round(g_open, 4),
                "segids": [ci["segid"], cj["segid"]],
                "bp": [ci["from_bp"], cj["from_bp"]],
                "helices": [ci["from_helix"], ci["to_helix"]],
            }
            if reference is not None and key in reference:
                # A genuine strand passage moves the continuous open integral by ~1;
                # thermal motion moves it by ~0.05.  This, not lk, is what can be
                # trusted frame to frame.
                row["delta_g"] = round(g_open - reference[key], 4)
                if abs(row["delta_g"]) >= 0.5:
                    row["changed"] = True
                    changed.append(row)
            if abs(lk) >= _LK_CATENATED and abs(lk - round(lk)) <= _INTEGRALITY_TOL:
                linked.append(row)

    return {
        "schema": SCHEMA,
        "ok": not linked,
        "n_pairs_tested": tested,
        "n_catenated": len(linked),
        "catenated": linked,
        "gauss_open": gauss,
        "n_changed": len(changed),
        "changed": changed,
    }


def catenation_over_frames(
    design,
    frames: Iterable[np.ndarray],
    *,
    model=None,
    proximity_nm: float = _PROXIMITY_NM,
) -> Iterator[dict]:
    """Yield one :func:`catenation_report` per trajectory frame.

    ``frames`` yields ``(n_atoms, 3)`` position arrays in the model's atom order.  The
    model (and therefore the atom indexing) is built once and reused.
    """
    if model is None:
        from backend.core.atomistic import build_atomistic_model

        model = build_atomistic_model(design)
    for n, pos in enumerate(frames):
        rep = catenation_report(
            design, model=model, positions=pos, proximity_nm=proximity_nm
        )
        rep["frame"] = n
        yield rep
