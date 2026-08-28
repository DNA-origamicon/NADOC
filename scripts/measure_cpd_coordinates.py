#!/usr/bin/env python3
"""Measure the CPD reaction coordinates for a design's DESIGNED extra-base welds.

At an antiparallel reciprocal crossover pair carrying extra bases, the inserted
thymines are the intended UV point-weld partners.  This measures, per frame, the two
coordinates the KIMMDY geometric rate model is a function of:

    d_mid = | midpoint(C5,C6)_a - midpoint(C5,C6)_b |        [nm]
    eta   = dihedral( C5_a, C6_a, C6_b, C5_b )               [deg]
    k     = exp( -( k1*|d - d0| + k2*|eta - eta0| ) )        propensity in [0,1]

`d_mid` is the distance between the two C5=C6 BOND MIDPOINTS -- the KIMMDY expression
0.5*((C5b-C5a) + (C6b-C6a)) simplifies to exactly that.  C5 and C6 are both carbon, so a
two-atom centre of mass equals the centre of geometry equals the bond midpoint; this is
why both CVs are expressible as plain Colvars components (`distance` over a {C5,C6}
group pair, and `dihedral`) with no custom function.

Pairs come from DESIGN INTENT -- `junction_topology.reciprocal_pairs()` -- never from
spatial proximity.  Off-target close approaches are not welds.

The extra bases are located two independent ways and must agree:
  (1) the design's own 5'->3' insert walk (authoritative for which residue is an insert)
  (2) unpaired-thymine detection by Watson-Crick geometry in frame 0
Everything runs in MDAnalysis PSF/DCD index space, which avoids the heavy-atom-vs-PDB
The design-side pair enumeration is kept separate from trajectory atom-row lookup.

    uv run python scripts/measure_cpd_coordinates.py workspace/2hb_1xT.nadoc \
        PKG/2hb_1xT.psf PKG/output/run.dcd [more.dcd ...] --stride 10

    # just the as-built geometric seed, no trajectory
    uv run python scripts/measure_cpd_coordinates.py workspace/2hb_1xT.nadoc --seed-only

Exit status is 1 if the two identifications disagree, so it can gate a script.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

# KIMMDY geometric rate parameters (kimmdy-dimerization, GPL-3.0)
K1, K2, D0, N0 = 2.017017017017017, 0.03003003003003003, 0.157177, 16.743651884789273

_PUR = {"ADE", "GUA", "DA", "DG"}
_THY = {"THY", "DT", "T"}
_COMP = {
    ("ADE", "THY"),
    ("THY", "ADE"),
    ("GUA", "CYT"),
    ("CYT", "GUA"),
    ("DA", "DT"),
    ("DT", "DA"),
    ("DG", "DC"),
    ("DC", "DG"),
}


def kimmdy_rate(d_nm, eta_deg):
    """Periodic-aware KIMMDY propensity. NOTE: the upstream model uses a plain
    |eta - eta0|, which overestimates the penalty near eta = -180 (191.7 deg where the
    true separation is 168.3). This uses the angular separation."""
    dth = np.minimum(np.abs(eta_deg - N0), 360.0 - np.abs(eta_deg - N0))
    return np.exp(-(K1 * np.abs(d_nm - D0) + K2 * dth))


def dihedral(p0, p1, p2, p3):
    b0, b1, b2 = p0 - p1, p2 - p1, p3 - p2
    b1n = b1 / np.linalg.norm(b1, axis=-1, keepdims=True)
    v = b0 - (b0 * b1n).sum(-1, keepdims=True) * b1n
    w = b2 - (b2 * b1n).sum(-1, keepdims=True) * b1n
    return np.degrees(np.arctan2((np.cross(b1n, v) * w).sum(-1), (v * w).sum(-1)))


def designed_pairs(design):
    """[(label, (segid_a, resid_a), (segid_b, resid_b)), ...] for every insert-carrying
    reciprocal crossover pair. Residue numbers follow the builder's 5'->3' walk, which is
    the numbering the package PDB/PSF uses."""
    from backend.core import junction_topology as jt
    from backend.core.namd_topology import psfgen_dna_segids_for_design

    connectors = jt.crossover_connectors(design)
    junctions = jt._junction_index(design)
    segnames = psfgen_dna_segids_for_design(len(design.strands))

    # crossover_id -> [(segid, resid), ...] for its inserts
    inserts: dict[str, list[tuple[str, int]]] = {}
    for si, strand in enumerate(design.strands):
        seg, resid, doms = segnames[si], 0, strand.domains
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
                        inserts.setdefault(xid, []).append((seg, resid))

    out = []
    for i, j in jt.reciprocal_pairs(connectors):
        ia = inserts.get(connectors[i].crossover_id, [])
        ib = inserts.get(connectors[j].crossover_id, [])
        for ka, a in enumerate(ia):
            for kb, b in enumerate(ib):
                out.append(
                    (
                        f"{connectors[i].crossover_id[:8]}[k={ka}]"
                        f"~{connectors[j].crossover_id[:8]}[k={kb}]",
                        a,
                        b,
                    )
                )
    return out, connectors


def unpaired_thymines(dna):
    """(segid, resid) of thymines with no Watson-Crick partner in the current frame."""
    sites = []
    for r in dna.residues:
        base = r.resname.rstrip("35")
        a = r.atoms.select_atoms("name N1" if base in _PUR else "name N3")
        if len(a) == 1:
            sites.append((r, base, a[0].position))
    if not sites:
        return []
    P = np.array([s[2] for s in sites])
    D = np.linalg.norm(P[:, None] - P[None, :], axis=-1)
    np.fill_diagonal(D, 1e9)
    out = []
    for i, (r, base, _) in enumerate(sites):
        j = int(np.argmin(D[i]))
        bonded = (
            D[i, j] < 3.3 and (base, sites[j][1]) in _COMP and int(np.argmin(D[j])) == i
        )
        if not bonded and base in _THY:
            out.append((r.segid, int(r.resid)))
    return out


def make_whole(dna, frags, box):
    """Delegates to backend.core.cpd_metrics.make_whole_dna -- one implementation, since
    getting this wrong silently produces plausible-looking nonsense rather than an error."""
    from backend.core.cpd_metrics import make_whole_dna

    make_whole_dna(dna, frags, box)


def seed_geometry(design, pairs):
    """``(d_nm, eta)`` for the first intended pair in the geometric build."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.namd_topology import psfgen_dna_segids_for_design

    model = build_atomistic_model(design)
    segid_by_strand = dict(
        zip(
            (strand.id for strand in design.strands),
            psfgen_dna_segids_for_design(len(design.strands)),
        )
    )
    xb: dict[tuple[str, int], dict[str, np.ndarray]] = {}
    for at in model.atoms:
        key = (segid_by_strand.get(at.strand_id, ""), int(at.seq_num))
        if key[0] and at.name in {"C5", "C6"}:
            xb.setdefault(key, {})[at.name] = np.array([at.x, at.y, at.z], float)
    if not pairs:
        return None
    _label, key_a, key_b = pairs[0]
    a, b = xb.get(key_a, {}), xb.get(key_b, {})
    if not {"C5", "C6"} <= a.keys() or not {"C5", "C6"} <= b.keys():
        return None
    bond = np.linalg.norm(a["C5"] - a["C6"])
    scale = 1.0 if bond < 0.5 else 0.1  # model may be nm or Angstrom
    ma, mb = 0.5 * (a["C5"] + a["C6"]), 0.5 * (b["C5"] + b["C6"])
    return float(np.linalg.norm(mb - ma)) * scale, float(
        dihedral(a["C5"], a["C6"], b["C6"], b["C5"])
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("design", type=Path, help=".nadoc design (defines the pairs)")
    ap.add_argument("topology", type=Path, nargs="?", help="package PSF (needs bonds)")
    ap.add_argument("trajectories", nargs="*", type=Path, help="DCD(s)")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument(
        "--already-whole",
        action="store_true",
        help=(
            "skip DNA PBC reconstruction; valid for NAMD trajectories produced with "
            "wrapAll off"
        ),
    )
    ap.add_argument(
        "--summary-only",
        action="store_true",
        help="suppress the per-pair listing and report junction-level aggregates",
    )
    ap.add_argument(
        "--seed-only",
        action="store_true",
        help="report the geometric build only, no trajectory",
    )
    ap.add_argument("--npz", type=Path, default=None, help="write raw series here")
    args = ap.parse_args(argv)

    warnings.filterwarnings("ignore")
    from backend.core.models import Design

    design = Design(**json.loads(args.design.read_text()))
    pairs, connectors = designed_pairs(design)
    print(f"design   {args.design.name}")
    print(f"  connectors {len(connectors)}, designed weld pairs {len(pairs)}")
    if not args.summary_only:
        for label, a, b in pairs:
            print(f"    {label}   {a[0]}:{a[1]}  <->  {b[0]}:{b[1]}")
    if not pairs:
        print("  no insert-carrying reciprocal pairs -- nothing to measure")
        return 0

    # A single arbitrary seed pair is misleading for a many-site summary and building
    # a full origami atomistically only to print it is expensive.  Trajectory identity
    # is still independently checked below against every designed insert.
    seed = None if args.summary_only and len(pairs) > 1 else seed_geometry(design, pairs)
    if seed:
        d, e = seed
        print(
            f"\n  as-built seed: d_mid = {d * 10:.2f} A   eta = {e:+.1f} deg   "
            f"k = {kimmdy_rate(np.array(d), np.array(e)):.4f}"
        )
        print(
            "  (seed eta is NOT meaningful -- the insert spin DOF is free in the "
            "joint solve; only MD-relaxed eta counts)"
        )
    if args.seed_only or not args.trajectories:
        return 0

    import MDAnalysis as mda

    u = mda.Universe(str(args.topology), [str(t) for t in args.trajectories])
    dna = u.select_atoms(
        "nucleic or resname DA DT DG DC ADE THY GUA CYT DA5 DT5 DG5 DC5 DA3 DT3 DG3 DC3"
    )
    frags = list(dna.fragments)
    n = len(u.trajectory)
    print(
        f"\ntrajectory  {n} frames, stride {args.stride}, "
        f"{dna.n_atoms} DNA atoms in {len(frags)} strands"
    )

    u.trajectory[0]
    if not args.already_whole:
        make_whole(dna, frags, u.dimensions[:3])

    # cross-check identification
    walk = sorted({p for _l, a, b in pairs for p in (a, b)})
    geom = sorted(unpaired_thymines(dna))
    if not set(walk) <= set(geom):
        print("\n  *** identification mismatch -- refusing to measure ***")
        print(f"      design insert walk : {walk}")
        print(f"      unpaired thymines  : {geom}")
        return 1
    if args.summary_only:
        print(
            f"  extra-base identification agrees ({len(walk)} designed inserts; "
            f"{len(geom)} geometrically unpaired thymines)"
        )
    else:
        print(f"  extra-base identification agrees (walk {walk} within unpaired {geom})")

    idx = {}
    for seg, resid in walk:
        r = u.select_atoms(f"segid {seg} and resid {resid}")
        idx[(seg, resid)] = (
            r.select_atoms("name C5")[0].index,
            r.select_atoms("name C6")[0].index,
        )

    series = {label: {"d": [], "eta": []} for label, _a, _b in pairs}
    times = []
    for i, ts in enumerate(u.trajectory[:: args.stride]):
        if not args.already_whole:
            make_whole(dna, frags, u.dimensions[:3])
        Q = u.atoms.positions
        for label, a, b in pairs:
            (c5a, c6a), (c5b, c6b) = idx[a], idx[b]
            ma, mb = 0.5 * (Q[c5a] + Q[c6a]), 0.5 * (Q[c5b] + Q[c6b])
            series[label]["d"].append(0.1 * float(np.linalg.norm(mb - ma)))
            series[label]["eta"].append(float(dihedral(Q[c5a], Q[c6a], Q[c6b], Q[c5b])))
        times.append(ts.time)

    times = np.array(times)
    span = (times[-1] - times[0]) / 1000.0 if len(times) > 1 else 0.0
    print(f"\n  measured {len(times)} frames spanning {span:.1f} ns\n")
    if not args.summary_only:
        print(
            f"  {'pair':<28} {'d mean':>8} {'d min':>7} {'eta sd':>7} "
            f"{'<k>':>8} {'d<4.5A':>8} {'reactive':>9}"
        )
    metrics = {}
    for label, _a, _b in pairs:
        d = np.array(series[label]["d"])
        e = np.array(series[label]["eta"])
        k = kimmdy_rate(d, e)
        dth = np.minimum(np.abs(e - N0), 360 - np.abs(e - N0))
        react = (d < 0.45) & (dth < 45)
        metrics[label] = {"contact": d < 0.45, "reactive": react, "k": k}
        if not args.summary_only:
            print(
                f"  {label:<28} {d.mean() * 10:>6.2f} A {d.min() * 10:>6.2f} "
                f"{e.std():>7.1f} {k.mean():>8.4f} "
                f"{100 * (d < 0.45).mean():>7.2f}% {100 * react.mean():>8.3f}%"
            )

    # A 2xT reciprocal junction has four candidate insert registers.  Its efficacy is
    # the probability that ANY intended register is reactive, not the sum of four pair
    # occupancies (which would grant a mechanical multiplicity advantage).
    grouped: dict[str, list[dict]] = {}
    for label, row in metrics.items():
        site = "~".join(part.split("[k=")[0] for part in label.split("~"))
        grouped.setdefault(site, []).append(row)
    site_rows = []
    for site, rows in grouped.items():
        contact = np.any(np.stack([row["contact"] for row in rows]), axis=0)
        reactive = np.any(np.stack([row["reactive"] for row in rows]), axis=0)
        max_k = np.max(np.stack([row["k"] for row in rows]), axis=0)
        site_rows.append((site, contact, reactive, max_k))

    site_contact = np.stack([row[1] for row in site_rows])
    site_reactive = np.stack([row[2] for row in site_rows])
    site_k = np.stack([row[3] for row in site_rows])
    contact_pct = 100.0 * site_contact.mean(axis=1)
    reactive_pct = 100.0 * site_reactive.mean(axis=1)
    print("\n  junction-level aggregate (ANY intended register per reciprocal site)")
    print(
        f"    sites {len(site_rows)}, registers/site "
        f"{min(len(v) for v in grouped.values())}-{max(len(v) for v in grouped.values())}"
    )
    print(
        f"    site-frame contact {100 * site_contact.mean():.3f}%   "
        f"reactive {100 * site_reactive.mean():.4f}%   <max k> {site_k.mean():.4f}"
    )
    print(
        f"    sites ever contacting {int((contact_pct > 0).sum())}/{len(site_rows)}   "
        f"ever reactive {int((reactive_pct > 0).sum())}/{len(site_rows)}"
    )
    print(
        "    per-site reactive occupancy "
        f"median {np.median(reactive_pct):.4f}%   "
        f"p90 {np.percentile(reactive_pct, 90):.4f}%   max {reactive_pct.max():.4f}%"
    )
    if site_reactive.shape[1] >= 2:
        mid = site_reactive.shape[1] // 2
        print(
            f"    reactive first/second half "
            f"{100 * site_reactive[:, :mid].mean():.4f}% / "
            f"{100 * site_reactive[:, mid:].mean():.4f}%"
        )
    ranked = sorted(
        zip((row[0] for row in site_rows), contact_pct, reactive_pct),
        key=lambda row: (-row[2], -row[1], row[0]),
    )
    print("    top reactive sites:")
    for site, cpct, rpct in ranked[:10]:
        print(f"      {site:<17} contact {cpct:7.3f}%   reactive {rpct:7.4f}%")

    print("\n  reactive corner = d < 4.5 A AND |eta - eta0| < 45 deg")
    print("  a classical force field cannot reach d0 = 1.57 A (a covalent bond);")
    print("  the usable PMF range bottoms out at vdW contact, ~3.4 A.")

    if args.npz:
        args.npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            args.npz,
            times=times,
            **{f"d__{l}": np.array(s["d"]) for l, s in series.items()},
            **{f"eta__{l}": np.array(s["eta"]) for l, s in series.items()},
        )
        print(f"\n  wrote {args.npz}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
