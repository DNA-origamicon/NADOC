#!/usr/bin/env python3
"""
Measure mean nearest-neighbour interhelical spacing from a NAMD trajectory.

Method
------
1. Reference geometry = the NADOC-built DNA-only PDB shipped in the package.
   Slab the bundle along its principal axis.  Cluster the C1' atoms of the
   MIDDLE slab into `n_helices` groups (2-D k-means in the plane perpendicular
   to the axis), then propagate that labelling outward slab by slab, seeding
   each slab's k-means from its already-solved neighbour.  Propagation is what
   makes this survive bent bundles, where a single global projection smears
   adjacent helices together.
2. Per slab-helix, drop C1' atoms further than `r_cut` from the slab-helix
   centroid.  Crossover extra bases and frayed ends sit off-axis, so the
   measurement stays duplex-vs-duplex.
3. Neighbour pairs = helix pairs whose reference slab centroids are, in the
   median over slabs, closer than `nb_factor` x (modal nearest-neighbour dist).
4. Per frame, per slab, per neighbour pair: minimum-image centroid separation,
   projected perpendicular to the local bundle axis.  End slabs are dropped.

Every run self-validates (balanced slab occupancy, no sub-15 A reference
"neighbours"); failures are reported rather than silently averaged.
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

import MDAnalysis as mda  # noqa: E402


def _principal_axis(pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    return c, vt[0] / np.linalg.norm(vt[0])


def _min_image(delta: np.ndarray, box: np.ndarray) -> np.ndarray:
    return delta - box * np.round(delta / box)


def _lloyd(xy: np.ndarray, cent: np.ndarray, iters: int = 100) -> tuple[np.ndarray, np.ndarray]:
    labels = np.full(len(xy), -1)
    for _ in range(iters):
        d = np.linalg.norm(xy[:, None, :] - cent[None, :, :], axis=-1)
        new = np.argmin(d, axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for c in range(len(cent)):
            m = labels == c
            if m.any():
                cent[c] = xy[m].mean(axis=0)
    return labels, cent


def _kmeans_seeded(xy: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Farthest-point seeding + Lloyd (deterministic)."""
    seeds = [int(np.argmax(np.linalg.norm(xy - xy.mean(axis=0), axis=1)))]
    while len(seeds) < k:
        d = np.min(np.linalg.norm(xy[:, None, :] - xy[seeds][None, :, :], axis=-1), axis=1)
        seeds.append(int(np.argmax(d)))
    return _lloyd(xy, xy[seeds].copy())


def build_reference(pdb: Path, n_helices: int, n_slabs: int, r_cut: float,
                    nb_factor: float):
    ref = mda.Universe(str(pdb))
    c1 = ref.select_atoms("name C1'")
    if len(c1) == 0:
        raise SystemExit(f"no C1' atoms in {pdb}")
    pos = c1.positions.astype(float)

    origin, axis = _principal_axis(pos)
    e1 = np.cross(axis, [0, 0, 1.0])
    if np.linalg.norm(e1) < 1e-6:
        e1 = np.cross(axis, [1.0, 0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)

    rel = pos - origin
    s = rel @ axis
    edges = np.linspace(s.min() - 1e-6, s.max() + 1e-6, n_slabs + 1)
    slab = np.clip(np.digitize(s, edges) - 1, 0, n_slabs - 1)

    labels = np.full(len(pos), -1)
    centroids: dict[int, np.ndarray] = {}          # slab -> (k,2) in-plane
    mid = n_slabs // 2

    def solve(sb: int, seed: np.ndarray | None, n_refine: int = 6):
        m = np.flatnonzero(slab == sb)
        if len(m) < n_helices * 3:
            return None
        r = pos[m] - origin
        xy = np.column_stack([r @ e1, r @ e2])
        if seed is None:
            lab, cent = _kmeans_seeded(xy, n_helices)
        else:
            lab, cent = _lloyd(xy, seed.copy())
        # Refine: crossover extra bases sit between helices and drag the k-means
        # centroids off-axis.  Re-fit each centroid from its duplex core only
        # (atoms within r_cut), then re-assign everything to the refined centres.
        # If that leaves a starved cluster (a helix split in two while another
        # pair merged), repair by retiring the starved centre and splitting the
        # fattest one, then refine again.
        for _repair in range(15):
            for _ in range(n_refine):
                d = np.linalg.norm(xy[:, None, :] - cent[None, :, :], axis=-1)
                lab = np.argmin(d, axis=1)
                moved = 0.0
                for c in range(n_helices):
                    sel = (lab == c) & (d[np.arange(len(xy)), lab] < r_cut)
                    if sel.sum() >= 6:
                        new = xy[sel].mean(axis=0)
                        moved = max(moved, float(np.linalg.norm(new - cent[c])))
                        cent[c] = new
                if moved < 1e-3:
                    break
            d = np.linalg.norm(xy[:, None, :] - cent[None, :, :], axis=-1)
            lab = np.argmin(d, axis=1)
            core = (d[np.arange(len(xy)), lab] < r_cut)
            occ = np.array([int((core & (lab == c)).sum()) for c in range(n_helices)])
            med = float(np.median(occ))
            if occ.min() >= 0.6 * med or n_helices < 2:
                break
            starved, fattest = int(np.argmin(occ)), int(np.argmax(occ))
            pts = xy[lab == fattest]
            if len(pts) < 4:
                break
            mu = pts.mean(axis=0)
            _, _, vv = np.linalg.svd(pts - mu, full_matrices=False)
            off = vv[0] * float(np.std((pts - mu) @ vv[0]))
            cent[starved], cent[fattest] = mu - off, mu + off
        labels[m] = lab
        centroids[sb] = cent
        return cent

    cent = solve(mid, None)
    if cent is None:
        raise SystemExit("middle slab too sparse")
    for sb in range(mid + 1, n_slabs):
        cent = solve(sb, centroids.get(sb - 1))
        if cent is None:
            break
    for sb in range(mid - 1, -1, -1):
        cent = solve(sb, centroids.get(sb + 1))
        if cent is None:
            break

    # 3-D slab-helix centroids in the reference, and the duplex-core filter
    ok = labels >= 0
    keep = np.zeros(len(pos), dtype=bool)
    ref_cent: dict[tuple[int, int], np.ndarray] = {}
    for sb in sorted(centroids):
        for h in range(n_helices):
            m = np.flatnonzero(ok & (slab == sb) & (labels == h))
            if len(m) < 6:
                continue
            c = pos[m].mean(axis=0)
            ref_cent[(h, sb)] = c
            d = np.linalg.norm(pos[m] - c, axis=1)
            # radial only: remove the axial spread of the slab first
            dv = pos[m] - c
            radial = np.linalg.norm(dv - np.outer(dv @ axis, axis), axis=1)
            keep[m[radial < r_cut]] = True

    # neighbour graph: median over slabs of the in-plane centroid distance
    D = np.full((n_helices, n_helices), np.nan)
    for i in range(n_helices):
        for j in range(i + 1, n_helices):
            dd = []
            for sb in sorted(centroids):
                a, b = ref_cent.get((i, sb)), ref_cent.get((j, sb))
                if a is None or b is None:
                    continue
                v = b - a
                dd.append(np.linalg.norm(v - (v @ axis) * axis))
            if dd:
                D[i, j] = D[j, i] = float(np.median(dd))
    nn = np.nanmin(D, axis=1)
    modal = float(np.median(nn))
    pairs = [(i, j) for i in range(n_helices) for j in range(i + 1, n_helices)
             if np.isfinite(D[i, j]) and D[i, j] < nb_factor * modal]

    occ = [int(((labels == h) & keep).sum()) for h in range(n_helices)]
    diag = {
        "core_per_helix": occ,
        "n_dropped": int((~keep).sum()),
        "n_total": int(len(pos)),
        "modal_nn": modal,
        "pair_dists": [float(D[i, j]) for i, j in pairs],
        "n_slabs_solved": len(centroids),
    }
    return {"c1_count": len(pos), "labels": labels, "slab": slab, "keep": keep,
            "pairs": pairs, "axis": axis, "n_slabs": n_slabs, "diag": diag}


def measure(psf: Path, dcd: Path, ref: dict, first_frac: float, stride: int,
            drop_ends: int, n_helices: int):
    u = mda.Universe(str(psf), str(dcd))
    c1 = u.select_atoms("nucleic and name C1'")
    if len(c1) != ref["c1_count"]:
        raise SystemExit(f"C1' count mismatch: traj {len(c1)} vs ref {ref['c1_count']}")

    n_slabs = ref["n_slabs"]
    labels, slab, keep, axis = ref["labels"], ref["slab"], ref["keep"], ref["axis"]
    sel = {}
    for h in range(n_helices):
        for sb in range(n_slabs):
            m = np.flatnonzero(keep & (labels == h) & (slab == sb))
            if len(m) >= 6:
                sel[(h, sb)] = m

    n_frames = len(u.trajectory)
    frames = range(int(n_frames * first_frac), n_frames, stride)
    lo, hi = drop_ends, n_slabs - drop_ends

    per_pair: dict[tuple[int, int], list[float]] = {p: [] for p in ref["pairs"]}
    frame_means: list[float] = []

    for fi in frames:
        u.trajectory[fi]
        box = u.dimensions[:3].astype(float)
        P = c1.positions.astype(float)
        cent = {}
        for key, m in sel.items():
            q = P[m]
            q = q[0] + _min_image(q - q[0], box)
            cent[key] = q.mean(axis=0)

        vals = []
        for (i, j) in ref["pairs"]:
            for sb in range(lo, hi):
                a, b = cent.get((i, sb)), cent.get((j, sb))
                if a is None or b is None:
                    continue
                d = _min_image(b - a, box)
                loc = np.zeros(3)
                for h in (i, j):
                    p0, p1 = cent.get((h, sb - 1)), cent.get((h, sb + 1))
                    if p0 is not None and p1 is not None:
                        v = _min_image(p1 - p0, box)
                        loc += v / np.linalg.norm(v)
                if np.linalg.norm(loc) < 1e-6:
                    loc = axis
                loc = loc / np.linalg.norm(loc)
                val = float(np.linalg.norm(d - (d @ loc) * loc))
                per_pair[(i, j)].append(val)
                vals.append(val)
        if vals:
            frame_means.append(float(np.mean(vals)))

    allv = np.concatenate([np.asarray(v) for v in per_pair.values() if v])
    nb = min(10, max(2, len(frame_means) // 3))
    bs = max(1, len(frame_means) // nb)
    blocks = [float(np.mean(frame_means[k * bs:(k + 1) * bs])) for k in range(nb)
              if frame_means[k * bs:(k + 1) * bs]]
    sem = float(np.std(blocks, ddof=1) / np.sqrt(len(blocks))) if len(blocks) > 1 else float("nan")
    return {"mean": float(allv.mean()), "median": float(np.median(allv)),
            "std": float(allv.std()), "sem_block": sem,
            "n_measurements": int(allv.size), "n_frames": len(frame_means),
            "frame_means": frame_means,
            "per_pair_mean": {f"{i}-{j}": float(np.mean(v))
                              for (i, j), v in per_pair.items() if v}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--psf", required=True)
    ap.add_argument("--pdb", required=True)
    ap.add_argument("--dcd", required=True)
    ap.add_argument("--n-helices", type=int, required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--slabs", type=int, default=14)
    ap.add_argument("--drop-ends", type=int, default=1)
    ap.add_argument("--r-cut", type=float, default=9.0)
    ap.add_argument("--nb-factor", type=float, default=1.35)
    ap.add_argument("--first-frac", type=float, default=0.5)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    ref = build_reference(Path(a.pdb), a.n_helices, a.slabs, a.r_cut, a.nb_factor)
    d = ref["diag"]
    core = d["core_per_helix"]
    bad = []
    if min(core) < 0.6 * np.median(core):
        bad.append(f"unbalanced helix occupancy min={min(core)} med={np.median(core):.0f}")
    if d["pair_dists"] and min(d["pair_dists"]) < 15.0:
        bad.append(f"reference neighbour at {min(d['pair_dists']):.1f} A (split helix)")
    expected_pairs = {6: 6, 24: None}.get(a.n_helices)
    if expected_pairs and len(ref["pairs"]) != expected_pairs:
        bad.append(f"{len(ref['pairs'])} pairs, expected {expected_pairs}")

    print(f"[{a.label}] helices={a.n_helices} slabs_solved={d['n_slabs_solved']}/{a.slabs} "
          f"core/helix min={min(core)} med={np.median(core):.0f} max={max(core)} "
          f"dropped={d['n_dropped']}/{d['n_total']}")
    print(f"[{a.label}] ref modal NN={d['modal_nn']:.2f} A  pairs={len(ref['pairs'])}  "
          f"ref pair dists {min(d['pair_dists']):.2f}-{max(d['pair_dists']):.2f} A")
    if bad:
        print(f"[{a.label}] *** REFERENCE VALIDATION FAILED: {'; '.join(bad)}")

    res = measure(Path(a.psf), Path(a.dcd), ref, a.first_frac, a.stride,
                  a.drop_ends, a.n_helices)
    print(f"[{a.label}] MD spacing = {res['mean']:.2f} +/- {res['sem_block']:.2f} A "
          f"(median {res['median']:.2f}, sd {res['std']:.2f}, "
          f"n={res['n_measurements']} over {res['n_frames']} frames)")

    if a.out:
        Path(a.out).write_text(json.dumps(
            {"label": a.label, "n_helices": a.n_helices, "valid": not bad,
             "problems": bad, "n_pairs": len(ref["pairs"]), **d, **res}, indent=1))


if __name__ == "__main__":
    main()
