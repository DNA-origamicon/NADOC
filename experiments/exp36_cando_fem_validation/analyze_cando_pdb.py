"""Analyse a CanDo multi-model atomic PDB → global bend angle + radius of curvature
(+ planarity, contour, RMSF availability) from MODEL 1 (the full equilibrium shape).

Robust method (clean atomic structure, planar bend):
  1. C1' atoms of MODEL 1 (one clean point/nucleotide; fall back to all atoms).
  2. PCA → bend plane (2 largest-variance dirs); planarity = λ3/λ2.
  3. Order the centerline: circle-fit the 2D cloud → center → sort by polar angle →
     per-wedge cross-section centroids (monotonic & correct for any planar arc <360°).
  4. Circle-fit the ordered centerline → R. Bend reported TWO geometrically-exact ways
     that must agree: (a) angular span about the fitted center, (b) chord+sagitta
     θ = 2·asin(chord/2R). Agreement is the built-in robustness check.
  (Deliberately NOT used: turning-angle integral — blows up on centerline jitter;
   straight-axis slab binning — mis-slices a curved arc and biases low. Both were
   tried and discarded; see the A9 non-robust-centerline lesson.)

Usage: uv run python analyze_cando_pdb.py <multimodel.pdb> [--expect-bend 90 --expect-R 45.5]
       [--dump-centerline out.txt]
"""
import argparse
import numpy as np


def load_model1(path, atom_name="C1'"):
    """(coords Nx3 Å, bfactors N) for MODEL 1. Filter to atom_name if given (else all)."""
    coords, bf = [], []
    cur, want = 0, None
    with open(path) as fh:
        for ln in fh:
            if ln.startswith("MODEL"):
                cur = int(ln.split()[1]); want = (cur == 1)
            elif ln.startswith("ENDMDL"):
                want = False
            elif ln.startswith(("ATOM", "HETATM")) and (want is None or want):
                if atom_name and ln[12:16].strip() != atom_name:
                    continue
                coords.append((float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
                try: bf.append(float(ln[60:66]))
                except ValueError: bf.append(0.0)
    return np.asarray(coords), np.asarray(bf)


def kasa_circle(xy):
    x, y = xy[:, 0], xy[:, 1]
    A = np.column_stack([x, y, np.ones_like(x)])
    c, *_ = np.linalg.lstsq(A, x**2 + y**2, rcond=None)
    cx, cy = c[0] / 2, c[1] / 2
    return cx, cy, np.sqrt(c[2] + cx**2 + cy**2)


def ordered_centerline(uv, nwedge=50):
    cx, cy, _ = kasa_circle(uv)
    a = np.arctan2(uv[:, 1] - cy, uv[:, 0] - cx)
    lo, hi = np.percentile(a, [0.5, 99.5])
    edges = np.linspace(lo, hi, nwedge + 1)
    cen = [uv[(a >= edges[i]) & (a < edges[i + 1])].mean(0)
           for i in range(nwedge) if ((a >= edges[i]) & (a < edges[i + 1])).sum() >= 4]
    return np.asarray(cen)


def analyze(path, expect_bend=None, expect_R=None, dump=None):
    P, bf = load_model1(path)
    if len(P) < 20:                      # no C1' (unexpected) → use all atoms
        P, bf = load_model1(path, atom_name=None)
    ext = (P.max(0) - P.min(0)) / 10
    print(f"MODEL 1: {len(P)} points | bbox (nm) = [{ext[0]:.1f} {ext[1]:.1f} {ext[2]:.1f}]")
    print(f"RMSF: B-factor nonzero {(bf>0).sum()}/{len(bf)} -> "
          f"{'PRESENT (max %.2f)'%bf.max() if (bf>0).any() else 'ABSENT (shape only)'}")

    c = P.mean(0); Q = P - c
    _, S, Vt = np.linalg.svd(Q, full_matrices=False)
    planar = S[2]**2 / S[1]**2
    print(f"planarity λ3/λ2 = {planar:.3f} "
          f"({'planar' if planar < 0.2 else 'NON-planar (twist?) — bend fit suspect'})")

    uv = np.column_stack([Q @ Vt[0], Q @ Vt[1]])
    cen = ordered_centerline(uv)
    ccx, ccy, R = kasa_circle(cen)

    ca = np.arctan2(cen[:, 1] - ccy, cen[:, 0] - ccx)
    span = np.degrees(abs(np.unwrap(ca)[-1] - np.unwrap(ca)[0]))
    chord = np.linalg.norm(cen[-1] - cen[0])
    sag_theta = np.degrees(2 * np.arcsin(np.clip(chord / (2 * R), -1, 1)))
    contour = np.linalg.norm(np.diff(cen, axis=0), axis=1).sum()

    print("\n── GLOBAL BEND (MODEL 1) ──────────────────────────────")
    print(f"radius of curvature   R = {R/10:6.2f} nm")
    print(f"bend (arc span)         = {span:6.2f}°")
    print(f"bend (chord+sagitta)    = {sag_theta:6.2f}°   (independent check)")
    d = abs(span - sag_theta)
    print(f"  agreement Δ = {d:.2f}° ({'OK' if d < 5 else 'DISAGREE — inspect centerline'})")
    print(f"contour length          = {contour/10:6.2f} nm  (design 210bp×0.34 = 71.4)")

    bend = 0.5 * (span + sag_theta)
    if expect_bend is not None:
        print("\n── vs NADOC analytic ──────────────────────────────────")
        print(f"bend:   expected {expect_bend:.1f}° | CanDo {bend:.1f}° | "
              f"Δ {bend-expect_bend:+.1f}° ({100*bend/expect_bend:.0f}% of ideal)")
    if expect_R is not None:
        print(f"radius: expected {expect_R:.1f} nm | CanDo {R/10:.1f} nm | "
              f"Δ {R/10-expect_R:+.1f} nm")

    if dump:
        np.savetxt(dump, cen / 10, header="centerline x,y (nm) in bend plane", fmt="%.3f")
        print(f"\ncenterline → {dump}")
    return dict(R_nm=R/10, bend_deg=bend, contour_nm=contour/10, planarity=planar,
                rmsf=bool((bf > 0).any()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdb")
    ap.add_argument("--expect-bend", type=float)
    ap.add_argument("--expect-R", type=float)
    ap.add_argument("--dump-centerline")
    a = ap.parse_args()
    analyze(a.pdb, a.expect_bend, a.expect_R, a.dump_centerline)
