"""
Optimize nitrogenous base orientations by rotating each base template rigidly
around C1' (z-axis rotation in template space).

Objective: make all WC H-bond distances within a pair EQUIDISTANT (equal to
each other), while rotating as little as possible from the Entry 4 reference
(C1'-referenced crystal extraction, before any chi adjustment).

WC H-bond atom pairs:
  AT:  N6(A)···O4(T),  N1(A)···N3(T)          — target: both equal
  GC:  O6(G)···N4(C),  N1(G)···N3(C),  N2(G)···O2(C) — target: all equal

A VdW clash penalty prevents ring interpenetration.

Run from the NADOC root:
  python scripts/optimize_base_rotations.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import numpy as np
from scipy.optimize import minimize

from backend.core.lattice import make_bundle_design
from backend.core.atomistic import (
    _atom_frame,
    _DA_BASE, _DT_BASE, _DG_BASE, _DC_BASE,
    _DA_BASE_REV, _DT_BASE_REV, _DG_BASE_REV, _DC_BASE_REV,
)
from backend.core.geometry import nucleotide_positions
from backend.core.models import Direction
from backend.core.constants import BDNA_RISE_PER_BP


# ── Constants ─────────────────────────────────────────────────────────────────

C1P = np.array([0.2248, 0.4334, 0.0])

# Entry 5 chi angles baked into the current templates (wrong — ring interpenetration).
# Un-rotating by these gives Entry 4 (C1'-referenced extraction, zero reference).
E5_CHI_DEG: dict[str, float] = {
    "DA_FWD": +36.524, "DT_FWD":  +3.873, "DG_FWD": +1.973, "DC_FWD": +1.090,
    "DT_REV": -18.541, "DA_REV": +25.811, "DC_REV": +7.735, "DG_REV": +1.512,
}

# VdW clash threshold (nm). Below this distance between any inter-strand base
# atom pair, a penalty is applied. Set below the minimum WC H-bond distance
# (0.287 nm) so genuine H-bond contacts are not penalised.
CLASH_DIST_NM: float = 0.26
LAMBDA_CLASH: float   = 5000.0

# Regularisation: weight on (theta_fwd^2 + theta_rev^2) to prefer small rotations
# from Entry 4. Dimensionally ~ nm^2/rad^2 vs the equidistance variance in nm^2.
LAMBDA_REG: float = 0.0   # no rotation penalty; "minimum change" = chi rotation only


# ── Template helpers ──────────────────────────────────────────────────────────

def tmpl_dict(tmpl: tuple) -> dict[str, np.ndarray]:
    return {name: np.array([n, y, z]) for name, _, n, y, z in tmpl}


def rotate_z_tmpl(atoms: dict[str, np.ndarray], theta: float) -> dict[str, np.ndarray]:
    """Rotate all atoms around C1' in the (n,y) plane by theta radians."""
    ct, st = math.cos(theta), math.sin(theta)
    result = {}
    for name, v in atoms.items():
        dn, dy = v[0] - C1P[0], v[1] - C1P[1]
        result[name] = np.array([
            C1P[0] + ct * dn - st * dy,
            C1P[1] + st * dn + ct * dy,
            v[2],
        ])
    return result


def apply_rotation(tmpl: tuple, theta: float) -> tuple:
    """Return a new template tuple with all atoms rotated by theta around C1'."""
    ct, st = math.cos(theta), math.sin(theta)
    result = []
    for name, elem, n, y, z in tmpl:
        dn, dy = n - C1P[0], y - C1P[1]
        result.append((name, elem,
                        float(C1P[0] + ct * dn - st * dy),
                        float(C1P[1] + st * dn + ct * dy),
                        float(z)))
    return tuple(result)


def entry4_tmpl(e5_tmpl: tuple, key: str) -> tuple:
    """Un-rotate an Entry 5 template to its Entry 4 state."""
    return apply_rotation(e5_tmpl, -math.radians(E5_CHI_DEG[key]))


# ── Frame extraction ──────────────────────────────────────────────────────────

def get_frames(design, hid: str, bp_list: list, direction) -> dict:
    helix = next(h for h in design.helices if h.id == hid)
    nuc_pos_map = {
        (nuc.bp_index, nuc.direction): nuc
        for nuc in nucleotide_positions(helix)
    }
    ax_start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
    ax_end   = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
    ax_hat   = (ax_end - ax_start) / np.linalg.norm(ax_end - ax_start)
    frames = {}
    for bp in bp_list:
        nuc = nuc_pos_map.get((bp, direction))
        if nuc is None:
            continue
        axis_pt = ax_start + (bp - helix.bp_start) * BDNA_RISE_PER_BP * ax_hat
        origin, R = _atom_frame(
            nuc, direction,
            axis_point=axis_pt,
            helix_direction=helix.direction,
        )
        frames[bp] = (origin, R)
    return frames


# ── Objective ─────────────────────────────────────────────────────────────────

def objective(
    params,
    fwd_base0: dict,    # Entry 4 FWD atoms
    rev_base0: dict,    # Entry 4 REV atoms
    hbonds_f: list,     # FWD H-bond atom names
    hbonds_r: list,     # REV H-bond atom names
    hb_target: float,   # common H-bond target distance (nm) for all bonds in pair
    origin_fwd, R_fwd,
    origin_rev, R_rev,
) -> float:
    theta_f, theta_r = params

    fwd_rot = rotate_z_tmpl(fwd_base0, theta_f)
    rev_rot = rotate_z_tmpl(rev_base0, theta_r)

    fwd_world = {n: origin_fwd + R_fwd @ p for n, p in fwd_rot.items()}
    rev_world = {n: origin_rev + R_rev @ p for n, p in rev_rot.items()}

    # Equidistance term: all H-bonds minimise toward the same target distance.
    # Using a single shared target makes every bond contribute equally and
    # avoids degenerate solutions at d → ∞ that pure-variance minimisation allows.
    hb_loss = sum(
        (float(np.linalg.norm(fwd_world[af] - rev_world[ar])) - hb_target) ** 2
        for af, ar in zip(hbonds_f, hbonds_r)
    )

    # Regularisation: prefer small rotation from Entry 4 reference
    reg_loss = LAMBDA_REG * (theta_f ** 2 + theta_r ** 2)

    # VdW clash penalty
    clash_loss = 0.0
    fwd_vals = list(fwd_world.values())
    rev_vals = list(rev_world.values())
    for fp in fwd_vals:
        for rp in rev_vals:
            d = float(np.linalg.norm(fp - rp))
            if d < CLASH_DIST_NM:
                clash_loss += (CLASH_DIST_NM - d) ** 2

    return hb_loss + reg_loss + LAMBDA_CLASH * clash_loss


# ── Optimizer ─────────────────────────────────────────────────────────────────

def optimize_pair(
    label: str,
    e4_fwd: tuple,    # Entry 4 FWD template
    e4_rev: tuple,    # Entry 4 REV template
    hbonds_f: list,
    hbonds_r: list,
    hb_target: float, # common H-bond target (mean of canonical WC distances)
    origin_fwd, R_fwd,
    origin_rev, R_rev,
    grid_steps: int = 36,
    n_best: int = 5,
) -> tuple[float, float]:
    fwd_base0 = tmpl_dict(e4_fwd)
    rev_base0 = tmpl_dict(e4_rev)

    angles = np.linspace(-math.pi, math.pi, grid_steps, endpoint=False)

    print(f"  Grid ({grid_steps}×{grid_steps}): {label} ...", flush=True)
    grid_results = []
    for tf in angles:
        for tr in angles:
            obj = objective((tf, tr), fwd_base0, rev_base0,
                            hbonds_f, hbonds_r, hb_target,
                            origin_fwd, R_fwd, origin_rev, R_rev)
            grid_results.append((obj, tf, tr))

    grid_results.sort(key=lambda x: x[0])
    best_obj, best_tf, best_tr = grid_results[0]
    print(f"    Best grid: θ_f={math.degrees(best_tf):+.1f}° "
          f"θ_r={math.degrees(best_tr):+.1f}°  obj={best_obj:.6f}")

    best_res_obj = float("inf")
    best_res_x   = (best_tf, best_tr)
    for obj0, tf0, tr0 in grid_results[:n_best]:
        res = minimize(
            objective, [tf0, tr0], method="Nelder-Mead",
            args=(fwd_base0, rev_base0, hbonds_f, hbonds_r, hb_target,
                  origin_fwd, R_fwd, origin_rev, R_rev),
            options={"xatol": 1e-10, "fatol": 1e-14, "maxiter": 200000},
        )
        if res.fun < best_res_obj:
            best_res_obj = res.fun
            best_res_x   = res.x

    tf, tr = best_res_x
    print(f"    Refined:   θ_f={math.degrees(tf):+.3f}° "
          f"θ_r={math.degrees(tr):+.3f}°  obj={best_res_obj:.8f}")
    return float(tf), float(tr)


# ── Report ────────────────────────────────────────────────────────────────────

def report_pair(
    label: str,
    e4_fwd: tuple, e4_rev: tuple,
    hbonds_f: list, hbonds_r: list,
    theta_f: float, theta_r: float,
    origin_fwd, R_fwd, origin_rev, R_rev,
) -> None:
    fwd_rot  = rotate_z_tmpl(tmpl_dict(e4_fwd), theta_f)
    rev_rot  = rotate_z_tmpl(tmpl_dict(e4_rev), theta_r)
    fwd_world = {n: origin_fwd + R_fwd @ p for n, p in fwd_rot.items()}
    rev_world = {n: origin_rev + R_rev @ p for n, p in rev_rot.items()}

    print(f"\n  {label}")
    print(f"    θ_FWD = {math.degrees(theta_f):+.3f}°   θ_REV = {math.degrees(theta_r):+.3f}°  (both from Entry 4)")

    dists = []
    for af, ar in zip(hbonds_f, hbonds_r):
        d = float(np.linalg.norm(fwd_world[af] - rev_world[ar]))
        dists.append(d)
        print(f"    {af}(FWD)···{ar}(REV) = {d:.4f} nm")
    print(f"    H-bond std dev = {np.std(dists)*1000:.2f} pm  mean = {np.mean(dists)*1000:.1f} pm")

    # AT-specific diagnostic: N1(A)···O4(T) must be large
    if "N1" in fwd_world and "O4" in rev_world:
        d = float(np.linalg.norm(fwd_world["N1"] - rev_world["O4"]))
        flag = "✓" if d > 0.40 else "✗ CLASH"
        print(f"    N1(A-FWD)···O4(T-REV) = {d:.4f} nm  (>> 0.40 nm) {flag}")
    if "O4" in fwd_world and "N1" in rev_world:
        d = float(np.linalg.norm(fwd_world["O4"] - rev_world["N1"]))
        flag = "✓" if d > 0.40 else "✗ CLASH"
        print(f"    O4(T-FWD)···N1(A-REV) = {d:.4f} nm  (>> 0.40 nm) {flag}")

    # Minimum inter-strand distance and clash list
    min_d, min_pair = float("inf"), ("?", "?")
    clashes = []
    for fn, fp in fwd_world.items():
        for rn, rp in rev_world.items():
            d = float(np.linalg.norm(fp - rp))
            if d < min_d:
                min_d, min_pair = d, (fn, rn)
            if d < CLASH_DIST_NM:
                clashes.append((fn, rn, d))
    clash_flag = "✓" if min_d >= CLASH_DIST_NM else "✗"
    print(f"    Min inter-strand: {min_d:.4f} nm  ({min_pair[0]}···{min_pair[1]}) {clash_flag}")
    if clashes:
        clashes.sort(key=lambda x: x[2])
        print(f"    *** {len(clashes)} clash(es) < {CLASH_DIST_NM} nm:")
        for fn, rn, d in clashes[:5]:
            print(f"      {fn}···{rn} = {d:.4f} nm")
    else:
        print(f"    No clashes (threshold {CLASH_DIST_NM} nm)")


def print_template(label: str, tmpl: tuple) -> None:
    print(f"    # {label}")
    for name, elem, n, y, z in tmpl:
        print(f'    ("{name}", "{elem}", {n:7.4f}, {y:7.4f}, {z:7.4f}),')


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    fwd_seq = "ATGCATGCATGCATGCATGC"
    comp    = {"A": "T", "T": "A", "G": "C", "C": "G"}
    rev_seq = "".join(comp[b] for b in reversed(fwd_seq))

    design = make_bundle_design(cells=[(0, 0)], length_bp=20, plane="XY")
    for strand in design.strands:
        has_fwd = any(d.direction == Direction.FORWARD for d in strand.domains)
        strand.sequence = fwd_seq if has_fwd else rev_seq

    hid = design.helices[0].id
    bps = [0, 1, 2, 3]
    frames_fwd = get_frames(design, hid, bps, Direction.FORWARD)
    frames_rev = get_frames(design, hid, bps, Direction.REVERSE)

    print("=" * 70)
    print("WC Chi Rotation — Equidistance + Minimum Rotation  (Entry 6)")
    print(f"CLASH_DIST = {CLASH_DIST_NM} nm  LAMBDA_CLASH = {LAMBDA_CLASH}")
    print(f"LAMBDA_REG = {LAMBDA_REG}  (prefer small rotation from Entry 4)")
    print(f"Grid: {36}×{36} full ±180°,  Multi-start Nelder-Mead (n_best=5)")
    print("=" * 70)
    print()

    # Build Entry 4 templates (un-rotate the current Entry 5 templates)
    e4 = {
        "DA_FWD": entry4_tmpl(_DA_BASE,     "DA_FWD"),
        "DT_FWD": entry4_tmpl(_DT_BASE,     "DT_FWD"),
        "DG_FWD": entry4_tmpl(_DG_BASE,     "DG_FWD"),
        "DC_FWD": entry4_tmpl(_DC_BASE,     "DC_FWD"),
        "DT_REV": entry4_tmpl(_DT_BASE_REV, "DT_REV"),
        "DA_REV": entry4_tmpl(_DA_BASE_REV, "DA_REV"),
        "DC_REV": entry4_tmpl(_DC_BASE_REV, "DC_REV"),
        "DG_REV": entry4_tmpl(_DG_BASE_REV, "DG_REV"),
    }

    # Common H-bond targets (mean of canonical WC distances per pair type).
    # All H-bonds in a pair share the same target so they are treated equally.
    #   AT canonical: N6···O4 = 0.290 nm,  N1···N3 = 0.300 nm  → mean 0.295 nm
    #   GC canonical: O6···N4 = 0.287 nm,  N1···N3 = 0.293 nm,
    #                 N2···O2 = 0.287 nm                        → mean 0.289 nm
    T_AT: float = (0.290 + 0.300) / 2          # 0.295 nm
    T_GC: float = (0.287 + 0.293 + 0.287) / 3  # 0.289 nm

    # bp=0: FWD=DA / REV=DT   (AT, FWD=A)
    # bp=1: FWD=DT / REV=DA   (AT, FWD=T)
    # bp=2: FWD=DG / REV=DC   (GC, FWD=G)
    # bp=3: FWD=DC / REV=DG   (GC, FWD=C)
    pairs = [
        ("AT  FWD=DA / REV=DT",
         "DA_FWD", "DT_REV",
         ["N6", "N1"], ["O4", "N3"], T_AT, 0),
        ("AT  FWD=DT / REV=DA",
         "DT_FWD", "DA_REV",
         ["O4", "N3"], ["N6", "N1"], T_AT, 1),
        ("GC  FWD=DG / REV=DC",
         "DG_FWD", "DC_REV",
         ["O6", "N1", "N2"], ["N4", "N3", "O2"], T_GC, 2),
        ("GC  FWD=DC / REV=DG",
         "DC_FWD", "DG_REV",
         ["N4", "N3", "O2"], ["O6", "N1", "N2"], T_GC, 3),
    ]

    results: dict[str, float] = {}   # key → theta_rad from Entry 4

    for (label, fwd_key, rev_key, hbonds_f, hbonds_r, hb_target, bp) in pairs:
        origin_fwd, R_fwd = frames_fwd[bp]
        origin_rev, R_rev = frames_rev[bp]

        theta_f, theta_r = optimize_pair(
            label,
            e4[fwd_key], e4[rev_key],
            hbonds_f, hbonds_r, hb_target,
            origin_fwd, R_fwd, origin_rev, R_rev,
        )
        results[fwd_key] = theta_f
        results[rev_key] = theta_r

    # ── Diagnostic report ─────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("DIAGNOSTIC REPORT")
    print("=" * 70)

    for (label, fwd_key, rev_key, hbonds_f, hbonds_r, hb_target, bp) in pairs:
        origin_fwd, R_fwd = frames_fwd[bp]
        origin_rev, R_rev = frames_rev[bp]
        report_pair(
            label,
            e4[fwd_key], e4[rev_key],
            hbonds_f, hbonds_r,
            results[fwd_key], results[rev_key],
            origin_fwd, R_fwd, origin_rev, R_rev,
        )

    # ── C1'–N bond lengths ────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print("C1'–N CHECK (preserved exactly by chi rotation)")
    print("=" * 70)
    n_atoms = {
        "DA_FWD": "N9", "DT_FWD": "N1", "DG_FWD": "N9", "DC_FWD": "N1",
        "DT_REV": "N1", "DA_REV": "N9", "DC_REV": "N1", "DG_REV": "N9",
    }
    e4_orig_map = {
        "DA_FWD": _DA_BASE, "DT_FWD": _DT_BASE, "DG_FWD": _DG_BASE, "DC_FWD": _DC_BASE,
        "DT_REV": _DT_BASE_REV, "DA_REV": _DA_BASE_REV,
        "DC_REV": _DC_BASE_REV, "DG_REV": _DG_BASE_REV,
    }
    for key, n_name in n_atoms.items():
        new_tmpl = apply_rotation(e4[key], results.get(key, 0.0))
        d_map    = {name: np.array([n, y, z]) for name, _, n, y, z in new_tmpl}
        if n_name in d_map:
            d = float(np.linalg.norm(d_map[n_name] - C1P)) * 10  # Å
            print(f"  {key}: C1'–{n_name} = {d:.3f} Å")

    # ── Output new template values ────────────────────────────────────────────
    print()
    print("=" * 70)
    print("NEW TEMPLATE VALUES — copy into atomistic.py")
    print("=" * 70)

    rev_orig = {
        "DT_REV": _DT_BASE_REV, "DA_REV": _DA_BASE_REV,
        "DC_REV": _DC_BASE_REV, "DG_REV": _DG_BASE_REV,
    }
    ordered = [
        ("_DA_BASE",     "DA_FWD", _DA_BASE),
        ("_DT_BASE",     "DT_FWD", _DT_BASE),
        ("_DG_BASE",     "DG_FWD", _DG_BASE),
        ("_DC_BASE",     "DC_FWD", _DC_BASE),
        ("_DT_BASE_REV", "DT_REV", _DT_BASE_REV),
        ("_DA_BASE_REV", "DA_REV", _DA_BASE_REV),
        ("_DC_BASE_REV", "DC_REV", _DC_BASE_REV),
        ("_DG_BASE_REV", "DG_REV", _DG_BASE_REV),
    ]

    for var_name, key, e5_orig in ordered:
        theta_from_e4 = results.get(key, 0.0)
        new_tmpl      = apply_rotation(e4[key], theta_from_e4)
        print(f"\n{var_name}:  θ_from_E4 = {math.degrees(theta_from_e4):+.3f}°")
        print_template(
            f"Rigid rotation {math.degrees(theta_from_e4):+.3f}° around C1′ from Entry 4",
            new_tmpl,
        )

    print()
    print("Done.")


if __name__ == "__main__":
    main()
