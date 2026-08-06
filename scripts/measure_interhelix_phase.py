#!/usr/bin/env python
"""Where does a crossover backbone actually sit, relative to the helix it crosses TO?

The question this answers
────────────────────────
NADOC builds every helix with a ``phase_offset`` from ``lattice._lattice_phase_offset``
(FORWARD cells π/2, REVERSE cells 2π/3) and places the two strands ±150° apart
(``BDNA_MINOR_GROOVE_ANGLE_DEG``).  Those numbers are LOCKED, and they were calibrated
against **caDNAno** — ``experiments/exp15_phase_offset_search`` uses caDNAno's own
crossover positions as ground truth.  Nothing in this repo has ever checked them against
an equilibrated origami: ``bundle_extract.py`` cannot (its rotation is the minimal
axis-to-axis rotation, a 2-DOF object with no roll term by construction, which is why its
q3/q5 are documented gimbal-locked), and the one shipped inter-helix angle
(``hj_equilibrium_angle_deg``) comes from a 2-helix isolated DX system.

So this measures the missing quantity directly, from free NAMD trajectories:

    at a crossover from helix A to helix B, what is the AZIMUTH of the crossing
    backbone about A's own axis, measured from the A→B inter-helix direction?

If the phase convention matched equilibrated origami, a crossover backbone would sit at
≈ 0° — pointing at the helix it is about to reach.  Whatever it actually sits at is the
relative phase, measured rather than assumed.

Why it matters (TD-27): the MD-measured CG placement collapses both caDNAno cell types
onto ONE groove separation, which is correct physics — cell type is bookkeeping, not a
molecule.  But the crossover phase was calibrated to the 150°/210° split, so correcting
the duplex while holding the phase swings reverse-cell reverse beads 55.3° off their
partner, and stretches half of all crossovers.  Either the phase or the placement has to
move, and this says which.

Method
──────
No global helix clustering (the slab k-means in ``measure_interhelical_spacing.py`` is
for bent bundles and is overkill here).  Helix membership falls straight out of the
topology:

  1. Base-pair every residue geometrically — mutual-nearest C1′ within a cutoff.
  2. Walk each strand.  Consecutive residues whose PARTNERS are also consecutive are on
     the same duplex; where that breaks, the strand has crossed over.  The runs between
     breaks are the strand's domains, and each domain lies on one helix.
  3. Fit each flanking domain's local axis as the cylinder its phosphates lie on —
     ``measure_cg_registration.fit_phosphate_cylinder``, chosen there because a
     C1′-midpoint fit dissolves the very groove asymmetry being measured.
  4. Project the A→B axis-to-axis vector ⊥ to A's axis; that direction is azimuth zero.
  5. Report the azimuth of the crossing phosphate about A's axis, and the same for B.

Circular statistics throughout — these are angles, so a plain mean is wrong.

Usage
─────
    uv run python scripts/measure_interhelix_phase.py \
        --psf  .../6hbx100_noT.psf \
        --dcd  .../6hbx100_noT_04_300K_NPT_MGHH_only_p50.dcd \
        --label 6hbx100_noT --stride 5 --out phase_6hbx100.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.measure_cg_registration import fit_phosphate_cylinder  # noqa: E402

# Watson-Crick H-bond N...N: ~2.8-3.0 A.  3.6 A admits thermal spread and stays far
# below anything else in the structure.
#
# C1'-C1' was tried first and is NOT discriminating enough: at ~10.5 A for a real pair it
# competes with the cross-strand DIAGONAL to the neighbouring base pair, so mutual-nearest
# on C1' paired only 45 % of residues and found zero crossovers.  The WC nitrogens are
# the actual bond, so they separate cleanly.
_PAIR_CUT_A = 3.6
# The WC H-bond partner atom: N1 on purines, N3 on pyrimidines.
_WC_ATOM = {"ADE": "N1", "GUA": "N1", "THY": "N3", "CYT": "N3",
            "DA": "N1", "DG": "N1", "DT": "N3", "DC": "N3",
            "A": "N1", "G": "N1", "T": "N3", "C": "N3"}
# Two helical turns of phosphates pin a cylinder axis hard; fewer and the fit wanders.
_AXIS_WIN = 21
_MIN_AXIS_P = 8
# A domain shorter than this cannot pin a cylinder axis — many staple domains are 7-8 bp
# and their fits are garbage.  Gating on length alone is not enough, so the fitted radius
# is checked too (below): the phosphate cylinder of real B-DNA sits at 9.0-9.3 A
# (measured_atomistic_template puts r_P at 0.904-0.922 nm), and a bad fit misses wildly.
_MIN_DOMAIN_BP = 4
# Local window (A) of duplex used to fit a helix axis around a crossover.  ~2 turns.
_AXIS_R_A = 26.0
# B-DNA rise is 3.4 A; the next helix's base pairs are a lattice spacing (~24 A) away.
_STACK_CUT_A = 5.0
_R_P_LO_A, _R_P_HI_A = 7.5, 11.5


def _norm(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-300)


def _circ(deg: np.ndarray) -> tuple[float, float, float]:
    """Circular mean, circular std (deg), and resultant length R of an angle sample."""
    r = np.radians(np.asarray(deg, dtype=float))
    c, s = np.cos(r).mean(), np.sin(r).mean()
    R = float(np.hypot(c, s))
    mean = math.degrees(math.atan2(s, c))
    std = math.degrees(math.sqrt(-2.0 * math.log(max(R, 1e-12))))
    return mean, std, R


def base_pairs(wc_pos: np.ndarray, seg_of: np.ndarray, resid_of: np.ndarray) -> dict[int, int]:
    """Mutual-nearest Watson-Crick N partners within the cutoff.

    *wc_pos* holds each residue's N1 (purine) / N3 (pyrimidine) position, NaN where the
    atom is missing.  Same-strand stack neighbours are excluded — they are ~4 A apart
    axially, close enough to compete at a loose cutoff.
    """
    from scipy.spatial import cKDTree

    ok = np.flatnonzero(np.isfinite(wc_pos).all(axis=1))
    if len(ok) == 0:
        return {}
    tree = cKDTree(wc_pos[ok])
    best = np.full(len(wc_pos), -1)
    bestd = np.full(len(wc_pos), np.inf)
    for a, i in enumerate(ok):
        for b in tree.query_ball_point(wc_pos[i], _PAIR_CUT_A):
            j = int(ok[b])
            if j == i:
                continue
            if seg_of[j] == seg_of[i] and abs(int(resid_of[j]) - int(resid_of[i])) <= 2:
                continue
            d = float(np.linalg.norm(wc_pos[j] - wc_pos[i]))
            if d < bestd[i]:
                bestd[i], best[i] = d, j
    pairs: dict[int, int] = {}
    for i, j in enumerate(best):
        if j >= 0 and best[j] == i:          # mutual nearest only
            pairs[i] = int(j)
    return pairs


def strand_domains(order: list[int], pairs: dict[int, int],
                   seg_of: np.ndarray) -> list[list[int]]:
    """Split one strand's residue indices into runs that stay on a single duplex.

    Consecutive residues are on the same helix when their PARTNERS are also consecutive
    (|Δpartner| == 1).  Anything else — a partner jump, or either residue unpaired — ends
    the run.  Unpaired residues (ssDNA, tails) are dropped: they have no duplex, so no
    helix axis, so no azimuth.
    """
    runs: list[list[int]] = []
    cur: list[int] = []
    for k, idx in enumerate(order):
        if idx not in pairs:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
            continue
        if not cur:
            cur = [idx]
            continue
        prev = cur[-1]
        # Same duplex = partners are adjacent residues ON THE SAME partner strand.
        # The segment check matters: two partner indices can differ by 1 across a
        # segment boundary without being stacked at all.
        same = (abs(pairs[idx] - pairs[prev]) == 1
                and seg_of[pairs[idx]] == seg_of[pairs[prev]])
        if same:
            cur.append(idx)
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = [idx]
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def helix_components(pairs: dict[int, int], strands: list[list[int]],
                     seg_of: np.ndarray, bp_mid: np.ndarray | None = None) -> np.ndarray:
    """Label every residue with its HELIX (duplex) id, by union-find.

    A domain — the run of one strand between two crossovers — is only ~7 bp in honeycomb,
    two thirds of a turn, and cannot pin a cylinder axis.  The HELIX it sits on continues
    through many crossovers, so the axis has to be fitted from the duplex, not the domain.

    Two unions build it: a residue is in the same duplex as (a) its Watson-Crick partner,
    and (b) the next residue along its own strand when their partners are also adjacent
    (an ordinary stacked step).  The connected components are the helices.
    """
    n = len(seg_of)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, j in pairs.items():
        union(i, j)
    for order in strands:
        for a, b in zip(order, order[1:]):
            if a in pairs and b in pairs and abs(pairs[a] - pairs[b]) == 1 \
                    and seg_of[pairs[a]] == seg_of[pairs[b]]:
                union(a, b)

    # STACKING is what actually holds a helix together across strand breaks.  Pairing
    # alone fragments it: in honeycomb the staple and scaffold crossovers roughly
    # coincide, so the components come out ~14 bp long (measured: 157 components on a
    # 6hb x 100 where 6 are expected).  Consecutive base-pair MIDPOINTS are one rise
    # apart (3.4 A) within a helix and a full lattice spacing (~24 A) between helices, so
    # a short-range union on midpoints chains each duplex and nothing else.
    if bp_mid is not None:
        from scipy.spatial import cKDTree

        reps = [i for i in pairs if i < pairs[i]]        # one entry per base pair
        mids = bp_mid[reps]
        good = np.isfinite(mids).all(axis=1)
        reps = [r for r, g in zip(reps, good) if g]
        mids = mids[good]
        if len(reps) > 1:
            tree = cKDTree(mids)
            for a, b in tree.query_pairs(_STACK_CUT_A):
                union(reps[a], reps[b])
    return np.array([find(i) for i in range(n)])


def _axis_for(helix_members: np.ndarray, anchor_pos: np.ndarray,
              p_pos: list) -> tuple[np.ndarray, np.ndarray] | None:
    """Local (point, unit axis) of one duplex, from the phosphates near *anchor_pos*.

    Both strands' phosphates are used — one strand alone traces the same cylinder, but
    two give the fit a full circle per turn instead of a single helical arc.  The window
    is a distance ball rather than a residue range, so it needs no ordering along the
    helix and works through a bend.
    """
    pts_all = [(i, p_pos[i]) for i in helix_members if p_pos[i] is not None]
    if not pts_all:
        return None
    arr = np.array([q for _, q in pts_all], dtype=float)
    d = np.linalg.norm(arr - anchor_pos, axis=1)
    pts = arr[d <= _AXIS_R_A]
    if len(pts) < _MIN_AXIS_P:
        return None
    c0 = pts.mean(axis=0)
    # Seed direction: principal axis of the phosphate cloud.
    _, _, vv = np.linalg.svd(pts - c0, full_matrices=False)
    u0 = _norm(vv[0])
    try:
        c, u, r = fit_phosphate_cylinder(pts, u0, c0)
    except Exception:
        return None
    if not (_R_P_LO_A <= r <= _R_P_HI_A):
        return None                       # the fit did not find a B-DNA phosphate cylinder
    return c, _norm(u)


def measure_frame(p_pos, pairs, strands, seg_of, hel_of, hel_members) -> list[dict]:
    """Every crossover in one frame → its two azimuths, in degrees."""
    out: list[dict] = []
    for order in strands:
        doms = strand_domains(order, pairs, seg_of)
        for d_i in range(len(doms) - 1):
            a_dom, b_dom = doms[d_i], doms[d_i + 1]
            if len(a_dom) < _MIN_DOMAIN_BP or len(b_dom) < _MIN_DOMAIN_BP:
                continue
            a_res, b_res = a_dom[-1], b_dom[0]
            if p_pos[a_res] is None or p_pos[b_res] is None:
                continue
            ha, hb = hel_of[a_res], hel_of[b_res]
            if ha == hb:
                continue                       # same duplex — a nick, not a crossover
            fa = _axis_for(hel_members[ha], np.asarray(p_pos[a_res]), p_pos)
            fb = _axis_for(hel_members[hb], np.asarray(p_pos[b_res]), p_pos)
            if fa is None or fb is None:
                continue
            (ca, ua), (cb, ub) = fa, fb

            def foot(c, u, pt):
                return c + float((pt - c) @ u) * u

            # Axis-to-axis direction at the crossover, taken at the same height on each.
            pa, pb = np.asarray(p_pos[a_res]), np.asarray(p_pos[b_res])
            fa_pt, fb_pt = foot(ca, ua, pa), foot(cb, ub, pb)
            ab = fb_pt - fa_pt
            sep = float(np.linalg.norm(ab))
            if sep < 1e-6:
                continue

            def azim(u, foot_pt, ref_vec, atom):
                """Azimuth of *atom* about the axis, 0 deg = the inter-helix direction."""
                e1 = ref_vec - float(ref_vec @ u) * u
                n1 = np.linalg.norm(e1)
                if n1 < 1e-9:
                    return None
                e1 = e1 / n1
                e2 = np.cross(u, e1)
                d = atom - foot_pt
                d = d - float(d @ u) * u
                if np.linalg.norm(d) < 1e-9:
                    return None
                return math.degrees(math.atan2(float(d @ e2), float(d @ e1)))

            phi_a = azim(ua, fa_pt, ab, pa)
            phi_b = azim(ub, fb_pt, -ab, pb)
            if phi_a is None or phi_b is None:
                continue
            out.append({
                "phi_a": phi_a,
                "phi_b": phi_b,
                "interhelix_A": sep,
                "axis_angle_deg": math.degrees(math.acos(
                    float(np.clip(abs(ua @ ub), -1.0, 1.0)))),
            })
    return out


def run(psf: Path, dcd: Path, label: str, stride: int, max_frames: int,
        first_frac: float) -> dict:
    import MDAnalysis as mda

    u = mda.Universe(str(psf), str(dcd))
    dna = u.select_atoms("nucleic")
    if len(dna) == 0:
        raise SystemExit(f"no nucleic atoms in {psf}")

    res = dna.residues
    n = res.n_residues
    seg_of = np.array([r.segment.segid for r in res])
    resid_of = np.array([r.resid for r in res])

    # Per-residue WC-nitrogen / P atom indices (a 5' terminal residue has no P).
    wc_idx = np.full(n, -1)
    p_idx = np.full(n, -1)
    for i, r in enumerate(res):
        want = _WC_ATOM.get(str(r.resname).strip().upper())
        for a in r.atoms:
            if want and a.name == want:
                wc_idx[i] = a.index
            elif a.name == "P":
                p_idx[i] = a.index
    if (wc_idx < 0).any():
        print(f"  note: {int((wc_idx < 0).sum())} residues have no WC nitrogen "
              f"(resnames {sorted({str(r.resname) for i, r in enumerate(res) if wc_idx[i] < 0})})")

    strands: list[list[int]] = []
    for segid in sorted(set(seg_of)):
        m = np.flatnonzero(seg_of == segid)
        strands.append([int(i) for i in m[np.argsort(resid_of[m])]])

    total = len(u.trajectory)
    start = int(total * first_frac)
    frames = list(range(start, total, stride))
    if max_frames:
        frames = frames[:max_frames]
    print(f"  {total} frames, analysing {len(frames)} "
          f"(equilibrated tail from frame {start}, stride {stride})")

    rec: list[dict] = []
    pairs: dict[int, int] = {}
    hel_of = None
    hel_members: dict = {}
    strand_seg = seg_of
    for fi, ts in enumerate(u.trajectory[frames[0]:frames[-1] + 1:stride]):
        pos = u.atoms.positions.astype(float)
        wc = np.array([pos[i] if i >= 0 else [np.nan] * 3 for i in wc_idx])
        p_pos = [pos[i] if i >= 0 else None for i in p_idx]
        if not pairs:
            # Pairing is a topological fact; compute once on the first analysed frame.
            pairs = base_pairs(wc, seg_of, resid_of)
            print(f"  base pairs: {len(pairs) // 2} "
                  f"({100 * len(pairs) / max(1, n):.0f}% of residues paired)")
        if hel_of is None:
            mid = np.full((len(wc_idx), 3), np.nan)
            for i, j in pairs.items():
                mid[i] = 0.5 * (wc[i] + wc[j])
            hel_of = helix_components(pairs, strands, strand_seg, mid)
            hel_members = {}
            for i, h in enumerate(hel_of):
                hel_members.setdefault(int(h), []).append(i)
            sizes = sorted((len(v) for v in hel_members.values()), reverse=True)
            print(f"  helices (duplex components): {len(hel_members)}  "
                  f"largest {sizes[:6]}")
        rec_f = measure_frame(p_pos, pairs, strands, strand_seg, hel_of, hel_members)
        rec.extend(rec_f)
        if fi == 0:
            print(f"  crossovers detected per frame: {len(rec_f)}")

    if not rec:
        raise SystemExit("no crossovers measured — check the pairing cutoff")

    phi = np.array([r["phi_a"] for r in rec] + [r["phi_b"] for r in rec])
    mean, std, R = _circ(phi)
    ih = np.array([r["interhelix_A"] for r in rec])
    ax = np.array([r["axis_angle_deg"] for r in rec])
    return {
        "label": label,
        "n_frames": len(frames),
        "n_crossover_samples": len(rec),
        "phi_crossover_mean_deg": mean,
        "phi_crossover_circstd_deg": std,
        "phi_resultant_R": R,
        "phi_abs_median_deg": float(np.median(np.abs(phi))),
        "interhelix_mean_A": float(ih.mean()),
        "interhelix_std_A": float(ih.std()),
        "axis_angle_mean_deg": float(ax.mean()),
        "phi_histogram_deg": np.histogram(phi, bins=36, range=(-180, 180))[0].tolist(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--psf", required=True)
    ap.add_argument("--dcd", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--first-frac", type=float, default=0.5,
                    help="skip this fraction of the run as un-equilibrated")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    label = a.label or Path(a.dcd).stem
    print(f"\n=== {label} ===")
    res = run(Path(a.psf), Path(a.dcd), label, a.stride, a.max_frames, a.first_frac)
    print(f"  crossover backbone azimuth from the A->B direction: "
          f"{res['phi_crossover_mean_deg']:+.1f} +/- {res['phi_crossover_circstd_deg']:.1f} deg "
          f"(R={res['phi_resultant_R']:.3f}, n={res['n_crossover_samples']})")
    print(f"  |phi| median {res['phi_abs_median_deg']:.1f} deg   "
          f"interhelix {res['interhelix_mean_A']:.2f} +/- {res['interhelix_std_A']:.2f} A")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=2))
        print(f"  wrote {a.out}")


if __name__ == "__main__":
    main()
