"""CPD weld metrics — the reaction coordinates for a designed extra-base UV weld.

At an antiparallel **reciprocal** crossover pair carrying extra bases, the inserted
thymines are the intended UV point-weld partners (Dietz-style CPD formation).  Two
coordinates describe how close that pair is to the [2+2] cycloaddition geometry, and the
KIMMDY geometric rate model is a function of exactly these two:

``d_mid``
    Distance between the two C5=C6 **bond midpoints**.  The KIMMDY expression
    ``0.5 * ((C5_b - C5_a) + (C6_b - C6_a))`` simplifies to exactly that, because
    ``0.5*(C5+C6)`` is the midpoint of each base's C5=C6 bond.  C5 and C6 are both
    carbon, so a two-atom centre of mass equals the centre of geometry equals the bond
    midpoint — which is why this is expressible as a plain Colvars ``distance`` between
    two ``{C5, C6}`` groups, with no custom function.

``eta``
    The dihedral ``C5_a - C6_a - C6_b - C5_b``: the twist between the two C5=C6 double
    bonds.  A plain Colvars ``dihedral``.

Pairs come from **design intent** — :func:`junction_topology.reciprocal_pairs` — never
from spatial proximity.  An off-target close approach is not a weld.

Scope limit: ``D0 = 0.157 nm`` is a *cyclobutane C-C bond*, i.e. the product.  A classical
force field cannot reach it; the usable range bottoms out at van der Waals contact
(~0.34 nm).  ``kimmdy_rate`` is a geometric propensity in [0, 1], not an Arrhenius rate.

See ``memory/project_cpd_umbrella_sampling.md``.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

# KIMMDY geometric rate parameters (kimmdy-dimerization schema, GPL-3.0).
K1 = 2.017017017017017      # 1/nm    distance penalty
K2 = 0.03003003003003003    # 1/deg   angle penalty
D0 = 0.157177               # nm      optimal (product) midpoint distance
N0 = 16.743651884789273     # deg     optimal dihedral

#: Below this the pair is treated as "in contact" for display purposes [nm].
REACTIVE_D_NM = 0.45
#: Angular tolerance for the reactive corner [deg].
REACTIVE_ETA_DEG = 45.0
#: van der Waals contact — the floor of what a classical force field can sample [nm].
VDW_FLOOR_NM = 0.34


def angular_separation_deg(eta_deg):
    """|eta - N0| taken the short way round the circle.

    The upstream KIMMDY model uses a plain ``abs(eta - n0)``, which at eta = -175 deg
    returns 191.7 where the true separation is 168.3 — underestimating the rate ~2x.
    Only matters in the antiparallel region, but there is no reason to inherit it.
    """
    d = np.abs(np.asarray(eta_deg, dtype=float) - N0)
    return np.minimum(d, 360.0 - d)


def kimmdy_rate(d_nm, eta_deg):
    """Geometric CPD propensity in [0, 1]; 1.0 at the product geometry."""
    return np.exp(-(K1 * np.abs(np.asarray(d_nm, dtype=float) - D0)
                    + K2 * angular_separation_deg(eta_deg)))


def dihedral_deg(p0, p1, p2, p3):
    """Signed dihedral p0-p1-p2-p3 in degrees. Vectorised over leading axes."""
    p0, p1, p2, p3 = (np.asarray(p, dtype=float) for p in (p0, p1, p2, p3))
    b0, b1, b2 = p0 - p1, p2 - p1, p3 - p2
    b1n = b1 / np.linalg.norm(b1, axis=-1, keepdims=True)
    v = b0 - (b0 * b1n).sum(-1, keepdims=True) * b1n
    w = b2 - (b2 * b1n).sum(-1, keepdims=True) * b1n
    return np.degrees(np.arctan2((np.cross(b1n, v) * w).sum(-1), (v * w).sum(-1)))


def weld_geometry(c5a, c6a, c5b, c6b) -> dict:
    """(d_mid [nm], eta [deg], k) for one pair from its four carbon positions.

    Positions must be in **nanometres** — the unit the design model and the served MD
    frames both use.
    """
    c5a, c6a, c5b, c6b = (np.asarray(p, dtype=float) for p in (c5a, c6a, c5b, c6b))
    mid_a = 0.5 * (c5a + c6a)
    mid_b = 0.5 * (c5b + c6b)
    d = float(np.linalg.norm(mid_b - mid_a))
    eta = float(dihedral_deg(c5a, c6a, c6b, c5b))
    return {"d_nm": d, "eta_deg": eta, "k": float(kimmdy_rate(d, eta)),
            "reactive": bool(d < REACTIVE_D_NM
                             and float(angular_separation_deg(eta)) < REACTIVE_ETA_DEG)}


def _insert_residues_by_crossover(design) -> dict[str, list[tuple[str, int]]]:
    """crossover_id -> [(segid, resid), ...] for its inserted extra bases.

    Residue numbers follow the builder's 5'->3' walk per strand, inserts included — the
    same numbering the packaged PDB/PSF uses (segids ``D000``, ``D001``, ... in
    ``design.strands`` order).
    """
    from backend.core import junction_topology as jt

    junctions = jt._junction_index(design)
    out: dict[str, list[tuple[str, int]]] = {}
    for si, strand in enumerate(design.strands):
        seg = f"D{si:03d}"
        resid = 0
        doms = strand.domains
        for di, dom in enumerate(doms):
            step = 1 if dom.end_bp >= dom.start_bp else -1
            for _bp in range(dom.start_bp, dom.end_bp + step, step):
                resid += 1
            if di + 1 < len(doms):
                nxt = doms[di + 1]
                ka = (dom.helix_id, dom.end_bp, jt._dir_value(dom.direction))
                kb = (nxt.helix_id, nxt.start_bp, jt._dir_value(nxt.direction))
                xid, extra = junctions.get(frozenset((ka, kb)), (None, ""))
                for _ in extra:
                    resid += 1
                    if xid is not None:
                        out.setdefault(xid, []).append((seg, resid))
    return out


def designed_weld_pairs(design) -> list[dict]:
    """Every intended CPD weld pair in the design, from topology alone.

    One entry per (insert on crossover A) x (insert on crossover B) for each
    insert-carrying **reciprocal** crossover pair.  A 1xT design yields exactly one pair
    per reciprocal pair; a 2xT design yields four combinations, of which typically only
    one is geometrically reactive.

    Pure — needs no built model, no topology file and no trajectory.
    """
    from backend.core import junction_topology as jt

    connectors = jt.crossover_connectors(design)
    inserts = _insert_residues_by_crossover(design)

    pairs: list[dict] = []
    for i, j in jt.reciprocal_pairs(connectors):
        xa, xb = connectors[i].crossover_id, connectors[j].crossover_id
        for ka, (sa, ra) in enumerate(inserts.get(xa, [])):
            for kb, (sb, rb) in enumerate(inserts.get(xb, [])):
                pairs.append({
                    "id": f"{xa}:{ka}~{xb}:{kb}",
                    "label": f"{xa[:8]}[k={ka}]~{xb[:8]}[k={kb}]",
                    "crossover_a": xa, "extra_base_k_a": ka,
                    "crossover_b": xb, "extra_base_k_b": kb,
                    "segid_a": sa, "resid_a": ra,
                    "segid_b": sb, "resid_b": rb,
                })
    return pairs


def resolve_weld_serials(pairs: Sequence[dict], universe: Any) -> list[dict]:
    """Attach C5/C6 atom serials to each pair, resolved against a loaded topology.

    ``serial`` is the atom's index in the whole solvated universe — the same key the
    MD atomistic display streams positions under (``md_trajectory.md_atomistic_model``),
    so the frontend can read these straight out of the frame it is already rendering
    instead of running a second coordinate pipeline.  That matters: the display affine is
    handed over rather than re-derived (see ``project_md_viz_tools``), so any independent
    path would land the markers off the atoms.

    Pairs whose residues are absent from the topology are returned with
    ``serials_resolved: False`` rather than raising — a job packaged from a different
    design should degrade, not 500.
    """
    out: list[dict] = []
    for p in pairs:
        entry = dict(p)
        try:
            ra = universe.select_atoms(f"segid {p['segid_a']} and resid {p['resid_a']}")
            rb = universe.select_atoms(f"segid {p['segid_b']} and resid {p['resid_b']}")
            entry.update(
                c5_a=int(ra.select_atoms("name C5")[0].index),
                c6_a=int(ra.select_atoms("name C6")[0].index),
                c5_b=int(rb.select_atoms("name C5")[0].index),
                c6_b=int(rb.select_atoms("name C6")[0].index),
                resname_a=str(ra.residues[0].resname),
                resname_b=str(rb.residues[0].resname),
                serials_resolved=True,
            )
        except Exception:  # noqa: BLE001 - missing residue is a degrade, not an error
            entry["serials_resolved"] = False
        out.append(entry)
    return out


def weld_pairs_for_topology(design, topology_path) -> list[dict]:
    """:func:`designed_weld_pairs` + C5/C6 serials for a packaged PSF."""
    import MDAnalysis as mda  # imported lazily; heavy

    pairs = designed_weld_pairs(design)
    if not pairs:
        return []
    universe = mda.Universe(str(topology_path))
    return resolve_weld_serials(pairs, universe)


# ── trajectory trace ──────────────────────────────────────────────────────────


def make_whole_dna(dna, fragments, box) -> None:
    """Put the DNA back together across the periodic boundary, in place.

    **Mandatory before any weld measurement.**  Per-fragment ``unwrap`` alone is NOT
    enough: it makes each strand whole but leaves the strands in whatever periodic images
    they wrapped into, so a pair straddling the boundary measures a full box length apart.
    Measured on a real run before this was added, a rigid 6-bp duplex "moved" ~9 A and the
    d_mid series was nonsense.

    The second step brings every strand into the image nearest the first strand, which is
    valid here because the whole origami is one compact assembly.
    """
    dna.unwrap(compound="fragments", inplace=True)
    ref = fragments[0].center_of_geometry()
    for frag in fragments[1:]:
        shift = np.round((ref - frag.center_of_geometry()) / box) * box
        if np.any(shift):
            frag.positions = frag.positions + shift


def seed_windows(d_nm: Sequence[float], windows: Sequence[dict], *,
                 frame_indices: Sequence[int] | None = None,
                 tolerance_ang: float | None = None) -> list[dict]:
    """Pick the frame that best seeds each umbrella window.

    PURE — takes a d_mid series (nm, e.g. from :func:`weld_trace`) and a ladder, and for
    each window returns the frame whose separation is closest to that window's centre.
    Starting a window from a structure already near its restraint centre is what keeps its
    equilibration short; starting it far away means the first chunk of sampling is the
    structure being dragged, not the free energy.

    ``tolerance_ang`` defaults to **half the local window spacing** — a seed further off
    than that is closer to a neighbouring window than to its own, which is the honest line
    for "this window has no seed". Those come back ``seeded: False`` so the ladder can be
    fixed (widen the pull, run it slower) BEFORE any GPU time is spent on it.

    ``frame_indices`` maps series positions back to real trajectory frames when the series
    was strided; without it the returned index is the position in the series.
    """
    d = np.asarray(d_nm, dtype=float)
    out: list[dict] = []
    if d.size == 0 or not windows:
        return out
    centers = [float(w.get("center_ang", 0.0)) for w in windows]
    for i, w in enumerate(windows):
        c_ang = centers[i]
        # Half the distance to the nearer neighbour — ladders are not evenly spaced.
        if tolerance_ang is not None:
            tol = float(tolerance_ang)
        else:
            gaps = [abs(c_ang - centers[j]) for j in (i - 1, i + 1)
                    if 0 <= j < len(centers)]
            tol = (min(gaps) / 2.0) if gaps else 0.5
        best = int(np.argmin(np.abs(d * 10.0 - c_ang)))
        actual = float(d[best] * 10.0)
        out.append({
            "center_ang": c_ang,
            "force_constant": w.get("force_constant"),
            "frame": int(frame_indices[best]) if frame_indices is not None else best,
            "series_index": best,
            "actual_ang": round(actual, 3),
            "offset_ang": round(actual - c_ang, 3),
            "tolerance_ang": round(tol, 3),
            "seeded": abs(actual - c_ang) <= tol,
        })
    return out


def seeding_report(seeds: Sequence[dict]) -> dict:
    """Summary of a seeding pass: how much of the ladder is actually startable."""
    total = len(seeds)
    ok = [s for s in seeds if s.get("seeded")]
    gaps = [s for s in seeds if not s.get("seeded")]
    return {
        "n_windows": total,
        "n_seeded": len(ok),
        "n_unseeded": len(gaps),
        "fully_seeded": total > 0 and not gaps,
        "unseeded_centers_ang": [s["center_ang"] for s in gaps],
        "worst_offset_ang": (max((abs(s["offset_ang"]) for s in seeds), default=None)),
    }


def trace_stride(n_total: int, stride: int = 1, max_frames: int = 2000) -> int:
    """Frame step for a bounded trace over ``n_total`` frames.

    WIDENS the stride rather than truncating the run.  This is the whole point of the
    trace: a truncated series over the first N frames of a long run reads as "the pair
    never got close" when it may simply not have been looked at.  Spanning the whole run
    at coarser resolution is the honest answer, and the chart cannot draw millions of
    points anyway.
    """
    step = max(int(stride), 1)
    n_max = max(int(max_frames), 1)
    if n_total // step > n_max:
        step = max(1, -(-n_total // n_max))     # ceil division
    return step


def weld_trace(topology_path, trajectory_paths, design, *, stride: int = 1,
               max_frames: int = 2000, windows: Sequence[dict] | None = None,
               progress=None) -> dict:
    """(d_mid, eta, k) per frame for every designed weld pair.

    This is the "watch it over the whole run" view: the overlay shows the current frame,
    this shows whether the pair *ever* approached.  Returns

        {ready, n_frames, stride, times_ps, pairs: [{id, label, d_nm[], eta_deg[], k[],
         d_min_nm, k_max, reactive_frames}], reason?}

    ``progress(done, total)`` is called as frames are read, for the poller.
    """
    import MDAnalysis as mda

    from backend.core.atomistic_to_nadoc import _GRO_DNA_RESNAMES

    pairs = designed_weld_pairs(design)
    if not pairs:
        return {"ready": True, "n_frames": 0, "pairs": [],
                "reason": "design has no extra-base reciprocal crossover pair"}

    paths = [str(p) for p in trajectory_paths]
    u = mda.Universe(str(topology_path), paths if len(paths) > 1 else paths[0])
    pairs = resolve_weld_serials(pairs, u)
    pairs = [p for p in pairs if p.get("serials_resolved")]
    if not pairs:
        return {"ready": False, "n_frames": 0, "pairs": [],
                "reason": "weld residues are absent from this job's topology"}

    dna = u.select_atoms("resname " + " ".join(_GRO_DNA_RESNAMES))
    frags = list(dna.fragments)
    if not frags:
        return {"ready": False, "n_frames": 0, "pairs": [], "reason": "no DNA in topology"}

    n_total = len(u.trajectory)
    step = trace_stride(n_total, stride, max_frames)

    series = {p["id"]: {"d": [], "eta": [], "k": []} for p in pairs}
    times: list[float] = []
    idx = list(range(0, n_total, step))
    for n_done, fi in enumerate(idx, start=1):
        ts = u.trajectory[fi]
        make_whole_dna(dna, frags, u.dimensions[:3])
        pos = u.atoms.positions
        for p in pairs:
            g = weld_geometry(0.1 * pos[p["c5_a"]], 0.1 * pos[p["c6_a"]],
                              0.1 * pos[p["c5_b"]], 0.1 * pos[p["c6_b"]])
            s = series[p["id"]]
            s["d"].append(round(g["d_nm"], 5))
            s["eta"].append(round(g["eta_deg"], 3))
            s["k"].append(round(g["k"], 5))
        times.append(float(ts.time))
        if progress is not None:
            progress(n_done, len(idx))

    frame_indices = idx
    out = []
    for p in pairs:
        s = series[p["id"]]
        d = np.asarray(s["d"]); eta = np.asarray(s["eta"]); k = np.asarray(s["k"])
        reactive = (d < REACTIVE_D_NM) & (angular_separation_deg(eta) < REACTIVE_ETA_DEG)
        out.append({
            "id": p["id"], "label": p["label"],
            "d_nm": s["d"], "eta_deg": s["eta"], "k": s["k"],
            "d_min_nm": float(d.min()) if len(d) else None,
            "d_mean_nm": float(d.mean()) if len(d) else None,
            "k_max": float(k.max()) if len(k) else None,
            "k_mean": float(k.mean()) if len(k) else None,
            "reactive_frames": int(reactive.sum()),
            # Which umbrella windows this run could actually start. Computed here because
            # it needs the same d series — and knowing a window has no seed is worth far
            # more BEFORE the GPU time than after.
            "seeds": seed_windows(s["d"], windows, frame_indices=frame_indices)
            if windows else [],
        })
        if windows:
            out[-1]["seeding"] = seeding_report(out[-1]["seeds"])
    return {"ready": True, "n_frames": len(times), "stride": step,
            "n_total_frames": n_total, "times_ps": times, "pairs": out}
