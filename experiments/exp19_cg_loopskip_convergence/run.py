#!/usr/bin/env python3
"""
Experiment 19 — CG-XPBD loop/skip convergence on 6HB.
=======================================================

Tests whether the coarse-grained helix-level physics (CG-XPBD) model
produces genuine structural deformation from loop/skip modifications on a
6-helix bundle, compared to the full per-nucleotide XPBD.

Hypothesis:
  The CG model encodes loop/skip mods as backbone rest-length changes:
    loop (+1) at bp k → rest[k→k+1] = 2 × BDNA_RISE_PER_BP (100% compression)
    skip (−1) at bp k → rest[k→k+1] ≈ 0 (strong tension)
  Starting from straight positions, loop/skip bonds create strong forces that
  drive structural deformation.  Crossover bonds (coupling inner and outer
  helices) transmit and amplify this deformation.
  Full XPBD shows < 0.5 nm displacement (< 3% of geometric target).
  CG-XPBD should show ≥ 2 nm displacement driven purely by topology.

Comparison:
  A. Full XPBD  — per-nucleotide, deformed geometry rest lengths (baseline)
  B. CG-XPBD   — axis CPs, topological rest lengths, crossover_weight sweep

Metrics:
  1. RMS displacement from straight initial positions (shows structural motion)
  2. Per-helix centroid Y-shift (measures bending direction: +Y expected for
     direction_deg=90 which puts inner arc at +Y and outer arc at −Y)
  3. XZ side-view projection of final axis positions (visual bending check)

Stability note:
  Skip bonds with rest=0 can create extreme strain.  We apply a floor of
  0.05 × BDNA_RISE_PER_BP to all backbone rest lengths after build to
  prevent numerical collapse.  Crossover_weight is swept in a stable range
  (1–12) with SUBSTEPS=10 to keep per-frame corrections bounded.

Output:
  results/design_6hb_90.nadoc
  results/summary_figure.png
  results/summary.txt
"""

import sys, os, math, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from backend.core.lattice import make_bundle_design, make_prebreak, make_auto_crossover
from backend.core.loop_skip_calculator import (
    bend_loop_skips, apply_loop_skips, min_bend_radius_nm, CELL_BP_DEFAULT,
)
from backend.core.models import Design, DeformationOp, BendParams
from backend.core.constants import BDNA_RISE_PER_BP, HONEYCOMB_HELIX_SPACING
from backend.physics.xpbd import build_simulation, xpbd_step
from backend.physics.cg_xpbd import (
    build_cg_simulation, cg_xpbd_step,
    _axis_position, _vec3_to_np,
)

# ── Output ────────────────────────────────────────────────────────────────────

OUT = os.path.join(os.path.dirname(__file__), 'results')
os.makedirs(OUT, exist_ok=True)

# ── Parameters ────────────────────────────────────────────────────────────────

CELLS_6HB  = [(0, 0), (0, 1), (1, 0), (0, 2), (1, 2), (2, 1)]
LENGTH_BP  = 168
BEND_A     = 21
BEND_B     = 147
ANGLE_DEG  = 90.0
DIRECTION  = 90.0     # +Y in cross-section: inner arc at +Y, outer arc at −Y

N_FRAMES   = 300
MEASURE_AT = sorted({1,2,3,5,8,12,18,25,35,50,70,100,150,200,250,300})

# Backbone rest-length floor: prevents skip-bond collapse (rest=0 is unstable)
REST_FLOOR = 0.05 * BDNA_RISE_PER_BP

# CG substeps per frame (small → stable; 10 keeps corrections ≲ 1 nm/frame)
CG_SUBSTEPS = 10
# Full XPBD substeps (50 = backend default)
FULL_SUBSTEPS = 50

# Crossover weight sweep (stable range: blowup observed for w > 12)
CXO_WEIGHTS = [0, 1, 3, 5, 8, 12]

# ── Style ─────────────────────────────────────────────────────────────────────

_DARK = '#0d1117'; _GRID = '#21262d'; _TEXT = '#c9d1d9'; _MUTED = '#8b949e'
_GREEN = '#3fb950'; _BLUE = '#58a6ff'; _RED = '#f85149'; _YEL = '#d29922'
_ORANGE = '#fb8500'

CMAP_CXO = [
    _MUTED, '#adb5bd', '#74c0fc', _BLUE, _GREEN, _ORANGE,
]

def _dark(ax):
    ax.set_facecolor(_DARK)
    ax.tick_params(colors=_TEXT, labelsize=8)
    ax.xaxis.label.set_color(_TEXT)
    ax.yaxis.label.set_color(_TEXT)
    ax.title.set_color(_TEXT)
    for sp in ax.spines.values():
        sp.set_edgecolor(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.5, alpha=0.7)


# ── Design pipeline ───────────────────────────────────────────────────────────

def build_design():
    print("Building 6HB 90° design ...")
    design = make_bundle_design(CELLS_6HB, LENGTH_BP, name="6HB_90deg")
    design = make_prebreak(design)
    design = make_auto_crossover(design)

    r_min   = min_bend_radius_nm(design.helices, BEND_A, BEND_B, DIRECTION)
    n_cells = (BEND_B - BEND_A) // CELL_BP_DEFAULT
    arc_nm  = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
    max_ang = math.degrees(arc_nm / r_min)
    angle   = min(ANGLE_DEG, max_ang)
    if angle < ANGLE_DEG:
        print(f"  Angle clamped: {ANGLE_DEG:.1f}° → {angle:.1f}°  "
              f"(r_min = {r_min:.2f} nm)")

    radius_nm = arc_nm / math.radians(angle)
    mods   = bend_loop_skips(design.helices, BEND_A, BEND_B, radius_nm, DIRECTION)
    design = apply_loop_skips(design, mods)

    deformed_design = design.model_copy(update={
        "deformations": [DeformationOp(
            type='bend', plane_a_bp=BEND_A, plane_b_bp=BEND_B,
            affected_helix_ids=[h.id for h in design.helices],
            params=BendParams(angle_deg=angle, direction_deg=DIRECTION),
        )],
    })

    loops = sum(ls.delta for h in design.helices for ls in h.loop_skips if ls.delta > 0)
    skips = -sum(ls.delta for h in design.helices for ls in h.loop_skips if ls.delta < 0)
    n_cxo = _count_crossover_bonds(design)
    n_cps = sum(h.length_bp for h in design.helices)

    print(f"  Helices: {len(design.helices)}  CPs: {n_cps}  "
          f"Loops: {loops}  Skips: {skips}  CXO bonds: {n_cxo}")
    print(f"  Bend: {angle:.1f}°  Radius: {radius_nm:.2f} nm")

    return design, deformed_design, angle, radius_nm


def _count_crossover_bonds(design) -> int:
    seen, count = set(), 0
    for strand in design.strands:
        for i in range(len(strand.domains) - 1):
            a = strand.domains[i]; b = strand.domains[i + 1]
            if a.helix_id == b.helix_id:
                continue
            key = tuple(sorted([(a.helix_id, a.end_bp), (b.helix_id, b.start_bp)]))
            if key not in seen:
                seen.add(key); count += 1
    return count


# ── Reference geometries ──────────────────────────────────────────────────────

def straight_axes(design) -> dict:
    """Straight-geometry axis positions: (helix_id, bp_index) → ndarray."""
    return {(h.id, k): _axis_position(h, k)
            for h in design.helices for k in range(h.length_bp)}


def deformed_axes(deformed_design) -> dict:
    """Deformed-geometry axis positions from the full geometric computation."""
    from backend.api.crud import _geometry_for_design
    geo = _geometry_for_design(deformed_design)
    fwd, rev = {}, {}
    for nuc in geo:
        key = (nuc['helix_id'], nuc['bp_index'])
        pos = np.array(nuc['backbone_position'], dtype=np.float64)
        (fwd if nuc['direction'] == 'FORWARD' else rev)[key] = pos
    return {k: (fwd[k] + rev[k]) * 0.5 for k in fwd if k in rev}


def rmsd_from(positions, index_map, ref_axes) -> float:
    sq = [np.sum((positions[index_map[k]] - v) ** 2)
          for k, v in ref_axes.items() if k in index_map]
    return float(np.sqrt(np.mean(sq))) if sq else 0.0


def helix_centroid_y(positions, index_map, helix) -> float:
    """Mean Y-coordinate of CPs for this helix (measures +Y bending)."""
    ys = [positions[index_map[(helix.id, k)]][1]
          for k in range(helix.length_bp) if (helix.id, k) in index_map]
    return float(np.mean(ys)) if ys else 0.0


# ── Simulation helpers ────────────────────────────────────────────────────────

def _build_cg(design, crossover_weight, backbone_rest_floor=REST_FLOOR):
    sim = build_cg_simulation(design)
    # Apply floor to backbone rest lengths (prevents skip-bond collapse)
    sim.backbone_rest = np.maximum(sim.backbone_rest, backbone_rest_floor)
    sim.crossover_weight   = crossover_weight
    sim.substeps_per_frame = CG_SUBSTEPS
    return sim


def _is_valid(positions) -> bool:
    return np.all(np.isfinite(positions)) and np.all(np.abs(positions) < 1e6)


# ── Full XPBD baseline ────────────────────────────────────────────────────────

def run_full_xpbd(design, deformed_design, s_axes):
    print("Running Full XPBD baseline ...")
    from backend.api.crud import _geometry_for_design
    def_geo  = _geometry_for_design(deformed_design)
    str_geo  = _geometry_for_design(design.model_copy(update={"deformations": []}))
    sim      = build_simulation(design, def_geo, straight_geometry=str_geo)

    # Build helix-level index for axis position extraction
    fwd_idx, rev_idx = {}, {}
    for idx, (hid, bp, d) in enumerate(sim.particles):
        (fwd_idx if d == 'FORWARD' else rev_idx)[(hid, bp)] = idx

    def axis_rmsd():
        sq = []
        for k, ref in s_axes.items():
            fi = fwd_idx.get(k); ri = rev_idx.get(k)
            if fi and ri:
                cur = (sim.positions[fi] + sim.positions[ri]) * 0.5
                sq.append(np.sum((cur - ref) ** 2))
        return float(np.sqrt(np.mean(sq))) if sq else 0.0

    frames, rmsds = [], []
    for step in range(1, N_FRAMES + 1):
        xpbd_step(sim, n_substeps=FULL_SUBSTEPS)
        if step in MEASURE_AT:
            frames.append(step)
            rmsds.append(axis_rmsd())
    print(f"  Displacement at frame {frames[-1]}: {rmsds[-1]:.4f} nm")
    return frames, rmsds


# ── CG sweeps ─────────────────────────────────────────────────────────────────

def run_cg_sweep(design, s_axes, d_axes, init_y_per_helix):
    print("\nRunning CG crossover_weight sweep ...")
    results = {}

    for w in CXO_WEIGHTS:
        print(f"  cxo_w={w:2d} ...", end=' ', flush=True)
        sim = _build_cg(design, crossover_weight=w)
        frames, disp, approach, mean_y_shift = [], [], [], []

        exploded = False
        for step in range(1, N_FRAMES + 1):
            cg_xpbd_step(sim, n_substeps=CG_SUBSTEPS)
            if not _is_valid(sim.positions):
                print(f"[EXPLODED at frame {step}]", end=' ')
                exploded = True
                break
            if step in MEASURE_AT:
                frames.append(step)
                disp.append(rmsd_from(sim.positions, sim.index_map, s_axes))
                approach.append(rmsd_from(sim.positions, sim.index_map, d_axes))
                # Mean absolute Y-centroid shift across helices
                y_shifts = [
                    helix_centroid_y(sim.positions, sim.index_map, h) - init_y_per_helix[h.id]
                    for h in design.helices
                ]
                mean_y_shift.append(float(np.mean(y_shifts)))

        results[w] = dict(
            frames=frames, disp=disp, approach=approach,
            y_shift=mean_y_shift, exploded=exploded,
            final_disp=disp[-1] if disp else float('nan'),
            final_y=mean_y_shift[-1] if mean_y_shift else float('nan'),
        )
        d_final   = results[w]['final_disp']
        y_final   = results[w]['final_y']
        status    = 'EXPLODED' if exploded else f"disp={d_final:.3f} nm  ΔY={y_final:+.3f} nm"
        print(status)

    return results


# ── Shape snapshots ───────────────────────────────────────────────────────────

def axis_xz(positions, index_map, helices):
    """X and Z coordinates of each helix's CP chain."""
    proj = {}
    for h in helices:
        zs, xs = [], []
        for k in range(h.length_bp):
            idx = index_map.get((h.id, k))
            if idx is not None:
                pos = positions[idx]
                xs.append(pos[0]); zs.append(pos[2])
        if zs:
            proj[h.id] = (np.array(zs), np.array(xs))
    return proj


def shape_snapshot(design, w, n_frames):
    """Run CG for n_frames with weight w; return final positions."""
    sim = _build_cg(design, crossover_weight=w)
    for f in range(n_frames):
        cg_xpbd_step(sim, n_substeps=CG_SUBSTEPS)
        if not _is_valid(sim.positions):
            break
    return sim.positions, sim.index_map


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    design, deformed_design, angle, radius_nm = build_design()

    # Export design
    nadoc_path = os.path.join(OUT, 'design_6hb_90.nadoc')
    with open(nadoc_path, 'w') as f:
        json.dump(design.model_dump(), f, indent=2)
    print(f"  Exported: {nadoc_path}")

    s_axes = straight_axes(design)
    d_axes = deformed_axes(deformed_design)

    # Initial RMSD straight→target
    init_rmsd = float(np.sqrt(np.mean([
        np.sum((s_axes[k] - d_axes[k])**2) for k in s_axes if k in d_axes
    ])))
    print(f"  Initial RMSD straight → target: {init_rmsd:.3f} nm")

    # Initial Y centroids per helix (baseline for Y-shift metric)
    sim0 = build_cg_simulation(design)
    init_y = {h.id: helix_centroid_y(sim0.positions, sim0.index_map, h)
              for h in design.helices}

    # Full XPBD baseline
    full_frames, full_disp = run_full_xpbd(design, deformed_design, s_axes)

    # CG sweep
    cg_res = run_cg_sweep(design, s_axes, d_axes, init_y)

    # Shape snapshots for best stable weight and w=0
    best_stable = max(
        [w for w in CXO_WEIGHTS if not cg_res[w]['exploded']],
        key=lambda w: cg_res[w]['final_disp']
    )
    print(f"\nRecording shape snapshots for cxo_w={best_stable} ...")
    pos_final, idx_final = shape_snapshot(design, best_stable, N_FRAMES)
    pos_w0,   idx_w0    = shape_snapshot(design, 0, N_FRAMES)

    # Target axis XZ for reference
    target_xz = {}
    for h in design.helices:
        zs, xs = [], []
        for k in range(h.length_bp):
            p = d_axes.get((h.id, k))
            if p is not None:
                xs.append(p[0]); zs.append(p[2])
        if zs:
            target_xz[h.id] = (np.array(zs), np.array(xs))

    # ── Figure ────────────────────────────────────────────────────────────────
    print("\nGenerating figure ...")

    fig = plt.figure(figsize=(16, 10), facecolor=_DARK)
    gs  = gridspec.GridSpec(2, 4, figure=fig, hspace=0.44, wspace=0.38,
                            left=0.06, right=0.97, top=0.91, bottom=0.08)

    # Panel 1: Displacement from straight — CG vs Full XPBD
    ax1 = fig.add_subplot(gs[0, 0:2])
    _dark(ax1)
    for i, w in enumerate(CXO_WEIGHTS):
        r = cg_res[w]
        if r['frames']:
            lbl = f'CG cxo_w={w}' + (' ⚠' if r['exploded'] else '')
            ax1.plot(r['frames'], r['disp'], color=CMAP_CXO[i], lw=1.8, label=lbl)
    ax1.plot(full_frames, full_disp, color=_RED, lw=2.5, ls='--',
             label='Full XPBD (baseline)')
    ax1.axhline(2.0, color=_GREEN, lw=0.9, ls=':', alpha=0.7,
                label='pass threshold (2 nm)')
    ax1.set_xlabel('Frame', color=_TEXT)
    ax1.set_ylabel('RMS displacement from straight (nm)', color=_TEXT)
    ax1.set_title('Structural Displacement: CG vs Full XPBD', color=_TEXT,
                  fontsize=10, fontweight='bold')
    ax1.legend(fontsize=7, facecolor='#161b22', labelcolor=_TEXT, edgecolor=_GRID,
               loc='upper left')

    # Panel 2: Y-centroid shift (bending direction)
    ax2 = fig.add_subplot(gs[0, 2:4])
    _dark(ax2)
    for i, w in enumerate(CXO_WEIGHTS):
        r = cg_res[w]
        if r['frames'] and not r['exploded']:
            ax2.plot(r['frames'], r['y_shift'], color=CMAP_CXO[i], lw=1.8,
                     label=f'cxo_w={w}')
    ax2.axhline(0, color=_MUTED, lw=0.8, ls='--', alpha=0.5)
    ax2.set_xlabel('Frame', color=_TEXT)
    ax2.set_ylabel('Mean centroid ΔY (nm)', color=_TEXT)
    ax2.set_title('Bending Direction (ΔY > 0 = correct +Y bend)', color=_TEXT,
                  fontsize=10, fontweight='bold')
    ax2.legend(fontsize=7, facecolor='#161b22', labelcolor=_TEXT, edgecolor=_GRID)

    # Panel 3: Initial straight — XZ side view (no loop/skip forces)
    ax3 = fig.add_subplot(gs[1, 0])
    _dark(ax3)
    init_xz = axis_xz(sim0.positions, sim0.index_map, design.helices)
    for hid, (zs, xs) in init_xz.items():
        ax3.plot(zs, xs, lw=1.2, alpha=0.75, color=_BLUE)
    ax3.set_xlabel('Z (nm)', color=_TEXT)
    ax3.set_ylabel('X (nm)', color=_TEXT)
    ax3.set_title('Initial (straight)', color=_TEXT, fontsize=10, fontweight='bold')
    ax3.set_aspect('equal')

    # Panel 4: CG w=0 (backbone only, no crossover amplification)
    ax4 = fig.add_subplot(gs[1, 1])
    _dark(ax4)
    xz_w0 = axis_xz(pos_w0, idx_w0, design.helices)
    for hid, (zs, xs) in xz_w0.items():
        ax4.plot(zs, xs, lw=1.2, alpha=0.75, color='#adb5bd')
    ax4.set_xlabel('Z (nm)', color=_TEXT)
    ax4.set_ylabel('X (nm)', color=_TEXT)
    ax4.set_title(f'CG w=0 (backbone only, frame {N_FRAMES})',
                  color=_TEXT, fontsize=10, fontweight='bold')
    ax4.set_aspect('equal')

    # Panel 5: CG best stable weight — final shape
    ax5 = fig.add_subplot(gs[1, 2])
    _dark(ax5)
    xz_best = axis_xz(pos_final, idx_final, design.helices)
    for hid, (zs, xs) in xz_best.items():
        ax5.plot(zs, xs, lw=1.2, alpha=0.75, color=_GREEN)
    d_best = cg_res[best_stable]['final_disp']
    ax5.set_xlabel('Z (nm)', color=_TEXT)
    ax5.set_ylabel('X (nm)', color=_TEXT)
    ax5.set_title(f'CG w={best_stable}  disp={d_best:.2f} nm  (frame {N_FRAMES})',
                  color=_TEXT, fontsize=10, fontweight='bold')
    ax5.set_aspect('equal')

    # Panel 6: Target geometric deformation
    ax6 = fig.add_subplot(gs[1, 3])
    _dark(ax6)
    for hid, (zs, xs) in target_xz.items():
        ax6.plot(zs, xs, lw=1.2, alpha=0.75, color=_YEL)
    ax6.set_xlabel('Z (nm)', color=_TEXT)
    ax6.set_ylabel('X (nm)', color=_TEXT)
    ax6.set_title(f'Target (geometric {angle:.0f}° bend)',
                  color=_TEXT, fontsize=10, fontweight='bold')
    ax6.set_aspect('equal')

    fig.suptitle(
        f'Exp19 — CG-XPBD Loop/Skip Convergence  |  '
        f'6HB  {angle:.0f}°  ·  {N_FRAMES} frames  ·  '
        f'{sum(h.length_bp for h in design.helices)} CPs  ·  '
        f'{_count_crossover_bonds(design)} crossover bonds',
        color=_TEXT, fontsize=11, fontweight='bold',
    )

    fig_path = os.path.join(OUT, 'summary_figure.png')
    fig.savefig(fig_path, dpi=150, facecolor=_DARK)
    plt.close(fig)
    print(f"  Saved: {fig_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    loops = sum(ls.delta for h in design.helices for ls in h.loop_skips if ls.delta > 0)
    skips = -sum(ls.delta for h in design.helices for ls in h.loop_skips if ls.delta < 0)
    n_cxo = _count_crossover_bonds(design)

    lines = [
        "Exp19 — CG-XPBD Loop/Skip Convergence on 6HB",
        f"  Cells: {CELLS_6HB}",
        f"  Length: {LENGTH_BP} bp  Bend: bp {BEND_A}–{BEND_B}  "
        f"Angle: {angle:.1f}°  Radius: {radius_nm:.2f} nm",
        f"  Helices: {len(design.helices)}  Loops: {loops}  Skips: {skips}",
        f"  CG CPs: {sum(h.length_bp for h in design.helices)}  "
        f"CXO bonds: {n_cxo}",
        f"  Initial RMSD (straight→target): {init_rmsd:.3f} nm",
        f"  CG substeps/frame: {CG_SUBSTEPS}  "
        f"Full-XPBD substeps/frame: {FULL_SUBSTEPS}",
        "",
        f"Full XPBD baseline (frame {full_frames[-1]}):",
        f"  Displacement: {full_disp[-1]:.4f} nm  "
        f"({'PASS <0.5nm' if full_disp[-1] < 0.5 else 'FAIL ≥0.5nm'})",
        "",
        "CG sweep results (frame {N_FRAMES}):".format(N_FRAMES=N_FRAMES),
    ]
    for w in CXO_WEIGHTS:
        r = cg_res[w]
        if r['exploded']:
            lines.append(f"  cxo_w={w:2d}  EXPLODED")
        else:
            lines.append(
                f"  cxo_w={w:2d}  disp={r['final_disp']:.3f} nm  "
                f"ΔY={r['final_y']:+.3f} nm  "
                f"{'PASS ≥2nm' if r['final_disp'] >= 2.0 else 'FAIL <2nm'}"
            )

    # Pass/fail
    p1 = full_disp[-1] < 0.5
    p2 = any(not cg_res[w]['exploded'] and cg_res[w]['final_disp'] >= 2.0
             for w in CXO_WEIGHTS)
    # Check if bending is in correct direction (+Y shift) for at least one weight
    p3 = any(not cg_res[w]['exploded'] and cg_res[w]['final_y'] > 0
             for w in CXO_WEIGHTS if w > 0)
    # Check monotonic displacement for w=1,3,5
    stable = [w for w in [1,3,5] if not cg_res.get(w, {}).get('exploded')]
    p4 = (len(stable) >= 2 and
          all(cg_res[stable[i+1]]['final_disp'] > cg_res[stable[i]]['final_disp']
              for i in range(len(stable)-1)))

    lines += [
        "",
        "Pass/Fail:",
        f"  1. Full XPBD displacement < 0.5 nm: {'PASS' if p1 else 'FAIL'}",
        f"  2. CG displacement ≥ 2 nm (any stable weight): {'PASS' if p2 else 'FAIL'}",
        f"  3. CG bending in correct direction (ΔY > 0): {'PASS' if p3 else 'FAIL'}",
        f"  4. Higher weight → larger displacement (monotone 1<3<5): {'PASS' if p4 else 'FAIL'}",
        f"",
        f"Overall: {'PASS' if all([p1,p2,p3,p4]) else 'PARTIAL' if any([p1,p2,p3,p4]) else 'FAIL'}",
    ]

    txt_path = os.path.join(OUT, 'summary.txt')
    with open(txt_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    for line in lines:
        print(line)
    print(f"\nDone.")


if __name__ == '__main__':
    main()
