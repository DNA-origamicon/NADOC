#!/usr/bin/env python3
"""Measure, from a free MD trajectory, where the coarse-grained bead and base slab
*should* sit relative to the base pair they belong to.

Why this exists
---------------
NADOC's geometric layer places a backbone bead at ``HELIX_RADIUS`` (1.0 nm) and the
partner strand's bead at ``±BDNA_MINOR_GROOVE_ANGLE_RAD`` (150°, sign chosen by the
helix's lattice cell type).  The atomistic layer does NOT trust those numbers: it
re-places the phosphorus at ``_ATOMISTIC_P_RADIUS`` (0.886 nm) with a 208.2° P–P
separation, both measured from the 1ZEW crystal, and then rotates the whole all-atom
model by a hand-tuned −32° so it visually overlays the (uncorrected) bead model.

Nothing in that chain was ever measured against a simulation.  This script does that.

The frame (label-free, so CG and MD are directly comparable)
-----------------------------------------------------------
For every base pair k it builds a local frame from the *base pair itself*:

    e_z  local helix axis — SVD through the C1'–C1' midpoints of a window of
         base pairs centred on k, signed along the FORWARD strand's 5'→3'
    o    the ORIGIN is the point of that fitted axis line closest to base pair k,
         not the C1'–C1' midpoint.  ``HELIX_RADIUS`` is a distance from the axis,
         so the comparison is only meaningful measured from the axis; the offset
         between the two is itself reported (``r_mid``, the x-displacement).
    e_x  the C1'(fwd) → C1'(rev) direction, orthogonalised against e_z
    e_y  e_z × e_x

Every landmark (P, C1', base-ring centroid, WC N) is then reported as
(r, phi, z) in that frame, with ``phi`` measured CCW about e_z starting from e_x.
Because the frame is defined by the base pair, the same numbers can be computed
analytically for NADOC's CG model and compared one-to-one — no reliance on matching
residue numbering, chain ids, or strand labels between the two.

Usage
-----
    uv run python scripts/measure_cg_registration.py \
        --psf  workspace/md_jobs/<job>/package/<stem>_namd_solvated/<stem>.psf \
        --dcd  workspace/md_jobs/<job>/package/<stem>_namd_solvated/output/<stem>_04_..._MGHH_only_p10.dcd \
        --label duplex_20bp

Use a FREE stage only (``MGHH_only`` or a ``_k0`` production).  Anything with ``ENM``
in the name is restrained to the built geometry and will hand the design's own
constants back to you.

Only plain two-chain duplexes are handled here on purpose: a duplex is where the
question "where does a bead belong relative to its base pair" has an unambiguous
answer.  Bundle-context deviation is a separate measurement.
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

PURINE_RING = ["N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4"]
PYRIMIDINE_RING = ["N1", "C2", "N3", "C4", "C5", "C6"]
PURINES = {"ADE", "GUA", "DA", "DG", "A", "G"}
PYRIMIDINES = {"THY", "CYT", "DT", "DC", "T", "C"}

# The Watson-Crick hydrogen-bond donor/acceptor that sits on the pseudo-dyad:
# purine N1 pairs with pyrimidine N3.
WC_ATOM = {"purine": "N1", "pyrimidine": "N3"}


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _perp_basis(u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Any orthonormal pair spanning the plane perpendicular to ``u``."""
    seed = np.array([1.0, 0.0, 0.0]) if abs(u[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    a = _norm(np.cross(u, seed))
    return a, np.cross(u, a)


def fit_phosphate_cylinder(
    p_atoms: np.ndarray,
    u0: np.ndarray,
    c0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit the local helix axis as the axis of the cylinder the phosphates lie on.

    Returns ``(point_on_axis, unit_direction, radius)``.

    Why not a line through the C1'–C1' midpoints: those midpoints sit only ~0.2 nm
    off the axis, so their radial signal is comparable to their thermal noise and the
    fitted line wanders.  Measured on the 20 bp duplex, the midpoint fit never
    converged — widening the window drove the apparent P–P azimuthal separation
    monotonically toward exactly 180°, i.e. it dissolved the groove asymmetry that
    is the whole point of the measurement.  The phosphates sit at ~0.9 nm and sweep
    a full circle over a turn, so they pin the axis position hard.
    """
    from scipy.optimize import least_squares

    e1, e2 = _perp_basis(u0)

    def unpack(q):
        # Direction as two small tilts off u0; position as an offset in the
        # perpendicular plane.  Keeps the parameterisation free of gimbal issues
        # for the small corrections we are actually solving for.
        u = _norm(u0 + q[0] * e1 + q[1] * e2)
        c = c0 + q[2] * e1 + q[3] * e2
        return u, c

    def resid(q):
        u, c = unpack(q)
        d = p_atoms - c
        d = d - np.outer(d @ u, u)
        r = np.linalg.norm(d, axis=1)
        return r - r.mean()

    sol = least_squares(resid, np.zeros(4), method="lm", xtol=1e-12, ftol=1e-12)
    u, c = unpack(sol.x)
    d = p_atoms - c
    d = d - np.outer(d @ u, u)
    return c, u, float(np.linalg.norm(d, axis=1).mean())


def _kind(resname: str) -> str:
    rn = resname.strip().upper()
    if rn in PURINES:
        return "purine"
    if rn in PYRIMIDINES:
        return "pyrimidine"
    raise ValueError(f"not a DNA base: {resname!r}")


def _ring_names(resname: str) -> list[str]:
    return PURINE_RING if _kind(resname) == "purine" else PYRIMIDINE_RING


def _wrap_deg(a: float) -> float:
    """Wrap to (-180, 180]."""
    return (a + 180.0) % 360.0 - 180.0


def _wrap360(a: float) -> float:
    """Wrap to [0, 360)."""
    return a % 360.0


def _circmean_deg(vals: np.ndarray) -> tuple[float, float]:
    """Circular mean and circular standard deviation, in degrees."""
    r = np.radians(np.asarray(vals, dtype=float))
    c, s = np.cos(r).mean(), np.sin(r).mean()
    mean = math.degrees(math.atan2(s, c))
    # Clamp: on a perfectly uniform set (an ideal built model, where every base pair
    # gives the identical angle) R comes out a hair above 1.0 and log(R) goes positive.
    R = min(1.0, math.hypot(c, s))
    std = math.degrees(math.sqrt(-2.0 * math.log(R))) if R > 1e-12 else float("nan")
    return mean, std


# ── residue-level accessors ───────────────────────────────────────────────────


class ResidueView:
    """Positions of one nucleotide in one frame, in nm."""

    __slots__ = ("resname", "_pos")

    def __init__(self, resname: str, names: list[str], coords: np.ndarray):
        self.resname = resname
        self._pos = {n: coords[i] for i, n in enumerate(names)}

    def has(self, name: str) -> bool:
        return name in self._pos

    def pos(self, name: str) -> np.ndarray:
        return self._pos[name]

    def ring_centroid(self) -> np.ndarray:
        names = [n for n in _ring_names(self.resname) if n in self._pos]
        return np.mean([self._pos[n] for n in names], axis=0)

    def ring_normal(self) -> np.ndarray:
        names = [n for n in _ring_names(self.resname) if n in self._pos]
        pts = np.array([self._pos[n] for n in names])
        _, _, vh = np.linalg.svd(pts - pts.mean(axis=0))
        return _norm(vh[2])

    def wc_atom(self) -> np.ndarray:
        return self._pos[WC_ATOM[_kind(self.resname)]]


# ── per-frame measurement ─────────────────────────────────────────────────────


def measure_frame(
    fwd: list[ResidueView],
    rev: list[ResidueView],
    window: int,
    exclude_terminal: int,
    axis_mode: str = "phosphate",
) -> list[dict]:
    """Measure every inner base pair of one frame.

    ``fwd[k]`` and ``rev[k]`` are Watson-Crick partners.  ``fwd`` is ordered 5'→3';
    ``rev`` is given in the SAME base-pair order (so ``rev`` runs 3'→5' in sequence).
    """
    n = len(fwd)
    mids = np.array([(fwd[k].pos("C1'") + rev[k].pos("C1'")) / 2.0 for k in range(n)])

    # Global axis only to fix the sign convention: +e_z runs along fwd 5'→3'.
    g_centroid = mids.mean(axis=0)
    _, _, vh = np.linalg.svd(mids - g_centroid)
    g_axis = _norm(vh[0])
    if np.dot(mids[-1] - mids[0], g_axis) < 0:
        g_axis = -g_axis

    out: list[dict] = []
    half = window // 2
    for k in range(exclude_terminal, n - exclude_terminal):
        lo, hi = max(0, k - half), min(n, k + half + 1)
        if hi - lo < 3:
            continue
        w = mids[lo:hi]
        w_centroid = w.mean(axis=0)
        _, _, vhw = np.linalg.svd(w - w_centroid)
        e_z = _norm(vhw[0])
        if np.dot(e_z, g_axis) < 0:
            e_z = -e_z

        if axis_mode == "phosphate":
            ps = [r.pos("P") for r in fwd[lo:hi] if r.has("P")]
            ps += [r.pos("P") for r in rev[lo:hi] if r.has("P")]
            if len(ps) < 8:
                continue
            c_fit, e_z, _ = fit_phosphate_cylinder(np.array(ps), e_z, w_centroid)
            if np.dot(e_z, g_axis) < 0:
                e_z = -e_z
            w_centroid = c_fit

        c1_f, c1_r = fwd[k].pos("C1'"), rev[k].pos("C1'")
        e_x = c1_r - c1_f
        e_x = _norm(e_x - np.dot(e_x, e_z) * e_z)
        e_y = np.cross(e_z, e_x)

        # Origin = the point ON the fitted axis nearest this base pair.  Using the
        # C1'-C1' midpoint instead would fold the base pair's own x-displacement
        # into every radius and make them incomparable to HELIX_RADIUS.
        origin = w_centroid + np.dot(mids[k] - w_centroid, e_z) * e_z

        def cyl(p: np.ndarray) -> tuple[float, float, float]:
            d = p - origin
            z = float(np.dot(d, e_z))
            x = float(np.dot(d, e_x))
            y = float(np.dot(d, e_y))
            return math.hypot(x, y), math.degrees(math.atan2(y, x)), z

        rec: dict[str, float] = {"bp": k}

        for tag, res in (("fwd", fwd[k]), ("rev", rev[k])):
            if res.has("P"):
                r, phi, z = cyl(res.pos("P"))
                rec[f"r_P_{tag}"] = r
                rec[f"phi_P_{tag}"] = phi
                rec[f"z_P_{tag}"] = z
            r, phi, z = cyl(res.pos("C1'"))
            rec[f"r_C1_{tag}"] = r
            rec[f"phi_C1_{tag}"] = phi
            r, phi, z = cyl(res.ring_centroid())
            rec[f"r_base_{tag}"] = r
            rec[f"phi_base_{tag}"] = phi
            r, phi, z = cyl(res.wc_atom())
            rec[f"r_wc_{tag}"] = r

        if "phi_P_fwd" in rec and "phi_P_rev" in rec:
            rec["dphi_PP"] = _wrap360(rec["phi_P_rev"] - rec["phi_P_fwd"])

        # Displacement of the base pair itself off the axis (B-form x-displacement).
        d_mid = mids[k] - origin
        rec["r_mid"] = math.hypot(float(np.dot(d_mid, e_x)), float(np.dot(d_mid, e_y)))
        rec["phi_mid"] = math.degrees(
            math.atan2(float(np.dot(d_mid, e_y)), float(np.dot(d_mid, e_x)))
        )

        rec["c1c1_nm"] = float(np.linalg.norm(c1_r - c1_f))
        rec["wc_nm"] = float(np.linalg.norm(fwd[k].wc_atom() - rev[k].wc_atom()))

        # Base-pair plane inclination: mean ring normal vs the local axis.
        nf, nr = fwd[k].ring_normal(), rev[k].ring_normal()
        if np.dot(nf, nr) < 0:
            nr = -nr
        bp_normal = _norm(nf + nr)
        if np.dot(bp_normal, e_z) < 0:
            bp_normal = -bp_normal
        rec["inclination_deg"] = math.degrees(
            math.acos(max(-1.0, min(1.0, float(np.dot(bp_normal, e_z)))))
        )

        # Rise / twist across the whole window, as a least-squares SLOPE against
        # base-pair index.  A consecutive difference against a *locally re-fitted*
        # axis is biased HIGH: the fit tilts toward that step's own thermal noise,
        # so the noise projects onto e_z instead of away from it.  Measured on the
        # 20 bp duplex the step estimator read 0.365 nm against a 0.349 nm global
        # span — a 4.6 % inflation that the slope form removes.
        ks = np.arange(lo, hi, dtype=float)
        zs = (w - w_centroid) @ e_z
        rec["rise_nm"] = float(np.polyfit(ks, zs, 1)[0])

        ang = []
        for j in range(lo, hi):
            xj = rev[j].pos("C1'") - fwd[j].pos("C1'")
            xj = _norm(xj - np.dot(xj, e_z) * e_z)
            ang.append(math.degrees(math.atan2(float(np.dot(xj, e_y)), float(np.dot(xj, e_x)))))
        ang = np.unwrap(np.radians(ang))
        rec["twist_deg"] = math.degrees(float(np.polyfit(ks, ang, 1)[0]))

        out.append(rec)
    return out


# ── trajectory driver ─────────────────────────────────────────────────────────


def run(
    psf: Path,
    dcd: Path,
    stride: int,
    max_frames: int,
    window: int,
    exclude_terminal: int,
    dna_sel: str,
    axis_mode: str = "phosphate",
) -> dict:
    import MDAnalysis as mda
    from MDAnalysis import transformations as trans

    u = mda.Universe(str(psf), str(dcd))
    dna = u.select_atoms(dna_sel)
    if len(dna) == 0:
        raise SystemExit(f"selection {dna_sel!r} matched no atoms")

    segs = sorted({s.segid for s in dna.segments})
    if len(segs) != 2:
        raise SystemExit(
            f"expected exactly 2 DNA chains for a duplex, found {len(segs)}: {segs}. "
            "This script measures plain duplexes only."
        )

    # Unwrap across the periodic boundary — these boxes barely exceed the DNA.
    u.trajectory.add_transformations(trans.unwrap(dna))

    seg_a = dna.select_atoms(f"segid {segs[0]}")
    seg_b = dna.select_atoms(f"segid {segs[1]}")
    res_a = list(seg_a.residues)
    res_b = list(seg_b.residues)
    if len(res_a) != len(res_b):
        raise SystemExit(f"chain lengths differ: {len(res_a)} vs {len(res_b)}")
    n_bp = len(res_a)

    # Antiparallel pairing: a[0] pairs with b[-1].
    pairs = [(res_a[i], res_b[n_bp - 1 - i]) for i in range(n_bp)]

    # Cache the atom-index slices once; per-frame work is then pure numpy.
    def _slice(res):
        names = [str(x) for x in res.atoms.names]
        return names, res.atoms.indices

    slices = [((_slice(a)), (_slice(b))) for a, b in pairs]
    names_a = [s[0][0] for s in slices]
    idx_a = [s[0][1] for s in slices]
    names_b = [s[1][0] for s in slices]
    idx_b = [s[1][1] for s in slices]
    rn_a = [str(a.resname) for a, _ in pairs]
    rn_b = [str(b.resname) for _, b in pairs]

    frames = range(0, len(u.trajectory), max(1, stride))
    frames = list(frames)[:max_frames]

    records: list[dict] = []
    n_used = 0
    for fi in frames:
        u.trajectory[fi]
        pos = u.atoms.positions / 10.0  # Å → nm
        fwd = [ResidueView(rn_a[k], names_a[k], pos[idx_a[k]]) for k in range(n_bp)]
        rev = [ResidueView(rn_b[k], names_b[k], pos[idx_b[k]]) for k in range(n_bp)]

        # Reject frames whose duplex has melted — a broken pair makes the bp frame
        # meaningless and would quietly poison the average.
        c1 = np.array(
            [np.linalg.norm(fwd[k].pos("C1'") - rev[k].pos("C1'")) for k in range(n_bp)]
        )
        inner = c1[exclude_terminal : n_bp - exclude_terminal]
        if np.any(inner > 1.35) or np.any(inner < 0.75):
            continue

        # Orient so that the FORWARD strand is the one running 5'→3' along +axis.
        # NADOC's convention (pdb_import.calibrate_from_pdb): chain A = FORWARD,
        # e_z = +axis_dir along its 5'→3'.  Residue order within a segment is 5'→3'.
        records.extend(measure_frame(fwd, rev, window, exclude_terminal, axis_mode))
        n_used += 1

    if not records:
        raise SystemExit("no usable frames (all rejected as melted?)")

    keys_linear = [
        "r_P_fwd", "r_P_rev", "r_C1_fwd", "r_C1_rev",
        "r_base_fwd", "r_base_rev", "r_wc_fwd", "r_wc_rev", "r_mid",
        "z_P_fwd", "z_P_rev", "c1c1_nm", "wc_nm", "inclination_deg", "rise_nm",
        "twist_deg",
    ]
    keys_circular = [
        "phi_P_fwd", "phi_P_rev", "phi_C1_fwd", "phi_C1_rev",
        "phi_base_fwd", "phi_base_rev", "phi_mid", "dphi_PP",
    ]

    summary: dict[str, dict] = {}
    for k in keys_linear:
        v = np.array([r[k] for r in records if k in r], dtype=float)
        if v.size:
            summary[k] = {"mean": float(v.mean()), "std": float(v.std()), "n": int(v.size)}
    for k in keys_circular:
        v = np.array([r[k] for r in records if k in r], dtype=float)
        if v.size:
            m, s = _circmean_deg(v)
            summary[k] = {"mean": float(m), "std": float(s), "n": int(v.size)}

    # dphi_PP is a [0,360) quantity; report it on that branch.
    if "dphi_PP" in summary:
        summary["dphi_PP"]["mean"] = _wrap360(summary["dphi_PP"]["mean"])

    return {
        "psf": str(psf),
        "dcd": str(dcd),
        "n_bp": n_bp,
        "exclude_terminal": exclude_terminal,
        "window": window,
        "axis_mode": axis_mode,
        "frames_scanned": len(frames),
        "frames_used": n_used,
        "samples": len(records),
        "summary": summary,
    }


# ── the CG model, in the same frame ───────────────────────────────────────────


def cg_prediction(groove_deg: float, radius_nm: float, base_disp_nm: float) -> dict:
    """What NADOC's geometric layer puts at the same landmarks, analytically.

    ``groove_deg`` is signed: +150 for a FORWARD-cell helix, −150 for REVERSE
    (``geometry.py`` picks the sign from ``helix.direction``).
    """
    g = math.radians(groove_deg)
    fwd_bb = np.array([radius_nm, 0.0, 0.0])
    rev_bb = np.array([radius_nm * math.cos(g), radius_nm * math.sin(g), 0.0])
    bp_hat = _norm(rev_bb - fwd_bb)
    fwd_base = fwd_bb + base_disp_nm * bp_hat
    rev_base = rev_bb - base_disp_nm * bp_hat

    # The CG frame's e_x is the fwd→rev chord; the MD frame's e_x is C1'→C1'.
    # Both run from the forward strand to the reverse strand across the pair, so
    # they are the same axis of the same frame.
    ex = bp_hat
    ez = np.array([0.0, 0.0, 1.0])
    ey = np.cross(ez, ex)
    origin = np.zeros(3)   # the helix axis point for this base pair

    def cyl(p):
        d = p - origin
        return (
            math.hypot(float(np.dot(d, ex)), float(np.dot(d, ey))),
            math.degrees(math.atan2(float(np.dot(d, ey)), float(np.dot(d, ex)))),
        )

    r_f, phi_f = cyl(fwd_bb)
    r_r, phi_r = cyl(rev_bb)
    rb_f, phib_f = cyl(fwd_base)
    rb_r, phib_r = cyl(rev_base)
    return {
        "groove_deg": groove_deg,
        "r_bead_fwd": r_f, "phi_bead_fwd": phi_f,
        "r_bead_rev": r_r, "phi_bead_rev": phi_r,
        "r_basebead_fwd": rb_f, "phi_basebead_fwd": phib_f,
        "r_basebead_rev": rb_r, "phi_basebead_rev": phib_r,
        "dphi_bead": _wrap360(phi_r - phi_f),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", required=True, type=Path)
    ap.add_argument("--dcd", required=True, type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--max-frames", type=int, default=600)
    ap.add_argument("--window", type=int, default=7, help="bp window for the local axis fit")
    ap.add_argument("--exclude-terminal", type=int, default=3)
    ap.add_argument("--dna-sel", default="nucleic")
    ap.add_argument("--axis-mode", default="phosphate", choices=("phosphate", "midpoint"),
                    help="how the local helix axis is located (see fit_phosphate_cylinder)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    res = run(
        args.psf, args.dcd, args.stride, args.max_frames,
        args.window, args.exclude_terminal, args.dna_sel, args.axis_mode,
    )
    res["label"] = args.label

    s = res["summary"]
    print(f"\n=== {args.label or args.dcd.name} ===")
    print(f"frames used {res['frames_used']}/{res['frames_scanned']}   "
          f"bp samples {res['samples']}   ({res['n_bp']} bp, "
          f"{res['exclude_terminal']} terminal excluded each end)")

    def row(k, unit="nm", scale=1.0):
        if k not in s:
            return
        d = s[k]
        print(f"  {k:<18} {d['mean']*scale:9.3f} ± {d['std']*scale:6.3f} {unit}")

    print("\n-- radial distance from the local helix axis --")
    for k in ("r_P_fwd", "r_P_rev", "r_C1_fwd", "r_C1_rev",
              "r_base_fwd", "r_base_rev", "r_wc_fwd", "r_wc_rev", "r_mid"):
        row(k)
    print("\n-- azimuth about the axis, 0 deg = C1'(fwd) -> C1'(rev) --")
    for k in ("phi_P_fwd", "phi_P_rev", "dphi_PP", "phi_C1_fwd", "phi_C1_rev",
              "phi_base_fwd", "phi_base_rev", "phi_mid"):
        row(k, "deg")
    print("\n-- helical parameters --")
    for k in ("rise_nm",):
        row(k)
    for k in ("twist_deg", "inclination_deg"):
        row(k, "deg")
    print("\n-- pairing sanity --")
    for k in ("c1c1_nm", "wc_nm"):
        row(k)

    print("\n-- what NADOC's CG layer puts there (analytic) --")
    for gd in (150.0, -150.0):
        c = cg_prediction(gd, 1.0, 0.3)
        cell = "FORWARD cell" if gd > 0 else "REVERSE cell"
        print(f"  {cell} (groove {gd:+.0f} deg):")
        print(f"    bead  fwd r={c['r_bead_fwd']:.3f} nm  phi={c['phi_bead_fwd']:+8.2f} deg"
              f"   rev r={c['r_bead_rev']:.3f} nm  phi={c['phi_bead_rev']:+8.2f} deg"
              f"   dphi={c['dphi_bead']:7.2f} deg")
        print(f"    base  fwd r={c['r_basebead_fwd']:.3f} nm  phi={c['phi_basebead_fwd']:+8.2f} deg"
              f"   rev r={c['r_basebead_rev']:.3f} nm  phi={c['phi_basebead_rev']:+8.2f} deg")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
