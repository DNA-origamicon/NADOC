#!/usr/bin/env python3
"""
Experiment 18 — XPBD convergence via genuine loop/skip strand topology.

Full pipeline: make_bundle_design → make_prebreak → make_auto_crossover →
bend_loop_skips → apply_loop_skips → XPBD from straight initial positions.

The bend deformation is applied geometrically (DeformationOp) to compute curved
target positions, while the loop/skip modifications on the strands encode the
arc-length strain that drives XPBD convergence.

WHY BUNDLE SIZE MATTERS
In exp17 the convergence was driven by attractor bonds — every particle had a
direct spring to its target.  Here the only driving forces are the crossover
bonds between helices, whose rest lengths (from the curved geometry) differ from
the actual straight-state distances.  The 2HB has only ~32 inter-helix bonds vs
662 backbone bonds → backbone always wins.  Increasing either the bend angle
(more loop/skip mods → larger per-bond strain) or the number of helices (more
crossovers → collective force) should allow convergence.

This experiment tests three designs:
  A. 2HB  90°     — baseline (expected: no convergence)
  B. 2HB  270°    — extreme bend; max loop/skip strain per helix
  C. 6HB  90°     — 6 helices, many inter-helix crossover bonds

All designs are exported as .nadoc files.

Output
------
  results/design_A_2hb_90.nadoc
  results/design_B_2hb_270.nadoc
  results/design_C_6hb_90.nadoc
  results/sweep_<param>_<design>.png   — per-design parameter sweeps
  results/summary_figure.png
  results/summary.txt
"""

import sys, os, math, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from backend.core.lattice import make_bundle_design, make_prebreak, make_auto_crossover
from backend.core.geometry import nucleotide_positions
from backend.core.deformation import deformed_nucleotide_positions
from backend.core.loop_skip_calculator import (
    bend_loop_skips, apply_loop_skips, min_bend_radius_nm, CELL_BP_DEFAULT
)
from backend.core.models import Design, DeformationOp, BendParams
from backend.core.constants import BDNA_RISE_PER_BP
from backend.physics.xpbd import build_simulation, xpbd_step

# ── Designs ───────────────────────────────────────────────────────────────────

CELLS_2HB = [(0, 0), (0, 1)]
CELLS_6HB = [(0, 0), (0, 1), (1, 0), (0, 2), (1, 2), (2, 1)]

DESIGNS = [
    dict(label='A_2hb_90',  cells=CELLS_2HB, length_bp=168, bend_a=21, bend_b=147, angle=90.0,  direction=0.0),
    dict(label='B_2hb_270', cells=CELLS_2HB, length_bp=168, bend_a=21, bend_b=147, angle=270.0, direction=0.0),
    dict(label='C_6hb_90',  cells=CELLS_6HB, length_bp=168, bend_a=21, bend_b=147, angle=90.0,  direction=90.0),
]

# ── Simulation ────────────────────────────────────────────────────────────────

N_FRAMES           = 200
MEASURE_AT         = set([1, 3, 5, 10, 20, 35, 50, 75, 100, 150, 200])
CONVERGE_THRESHOLD = 2.0    # nm  (relaxed — these are large structures)
EXPLODE_THRESHOLD  = 500.0  # nm

DEFAULTS = dict(
    bond_stiffness=1.0, bend_stiffness=0.8, bp_stiffness=0.8,
    stacking_stiffness=0.5, noise_amplitude=0.0, substeps=50,
)

SWEEPS_PER_DESIGN = {
    'bp_stiffness': [0.0, 0.4, 0.8, 1.0],
    'substeps':     [10, 50, 100, 200],
    'noise':        [0.0, 0.005, 0.015],
}

COMBOS = [
    ('defaults',             dict()),
    ('bp=1.0',               dict(bp_stiffness=1.0)),
    ('bp=1.0, ss=200',       dict(bp_stiffness=1.0, substeps=200)),
    ('bp=0.0',               dict(bp_stiffness=0.0)),
    ('noise=0.01, ss=100',   dict(noise_amplitude=0.01, substeps=100)),
    ('bp=1.0, noise=0.01',   dict(bp_stiffness=1.0, noise_amplitude=0.01)),
]

# ── Style ─────────────────────────────────────────────────────────────────────

_DARK = '#0d1117'; _GRID = '#21262d'; _TEXT = '#c9d1d9'; _GREEN = '#3fb950'

def _dark(ax):
    ax.set_facecolor(_DARK)
    ax.tick_params(colors=_TEXT, labelsize=8)
    ax.xaxis.label.set_color(_TEXT); ax.yaxis.label.set_color(_TEXT)
    ax.title.set_color(_TEXT)
    for sp in ax.spines.values(): sp.set_edgecolor(_GRID)
    ax.grid(True, color=_GRID, linewidth=0.6)

# ── Pipeline helpers ──────────────────────────────────────────────────────────

def _build_design(cfg: dict):
    cells, length_bp = cfg['cells'], cfg['length_bp']
    bend_a, bend_b   = cfg['bend_a'], cfg['bend_b']
    angle, direction = cfg['angle'], cfg['direction']

    design = make_bundle_design(cells, length_bp, name=f"2HB_{cfg['label']}")

    # Clamp angle so loop/skip mods don't exceed the physical limit
    n_cells   = (bend_b - bend_a) // CELL_BP_DEFAULT
    arc_nm    = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
    helices   = design.helices
    r_min     = min_bend_radius_nm(helices, bend_a, bend_b, direction)
    r_target  = arc_nm / math.radians(angle)
    if r_target < r_min:
        r_target = r_min * 1.05  # stay just above minimum
        angle    = math.degrees(arc_nm / r_target)
        print(f'  [{cfg["label"]}] angle clamped to {angle:.1f}° (min radius {r_min:.2f} nm)')

    op = DeformationOp(
        id=str(uuid.uuid4()), type='bend',
        plane_a_bp=bend_a, plane_b_bp=bend_b,
        affected_helix_ids=[h.id for h in design.helices],
        params=BendParams(angle_deg=angle, direction_deg=direction),
    )
    design = design.model_copy(update={'deformations': [op]})

    design = make_prebreak(design)
    design = make_auto_crossover(design)

    seg_helices = design.helices
    mods = bend_loop_skips(seg_helices, bend_a, bend_b, r_target, direction)
    design = apply_loop_skips(design, mods)

    return design, mods, angle


def _to_geo(design: Design, deformed: bool) -> list[dict]:
    geo = []
    for helix in design.helices:
        nucs = (deformed_nucleotide_positions(helix, design)
                if deformed else nucleotide_positions(helix))
        for nuc in nucs:
            geo.append({
                'helix_id':          helix.id,
                'bp_index':          nuc.bp_index,
                'direction':         nuc.direction.value,
                'backbone_position': nuc.position.tolist(),
            })
    return geo


def _rmsd(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    diff = a[:n] - b[:n]
    return float(np.sqrt(np.mean(np.sum(diff ** 2, axis=1))))


def _run_trial(params, deformed_geo, straight_geo, design, target):
    p = {**DEFAULTS, **params}
    sim = build_simulation(design, deformed_geo, straight_geometry=straight_geo)
    sim.bond_stiffness     = p['bond_stiffness']
    sim.bend_stiffness     = p['bend_stiffness']
    sim.bp_stiffness       = p['bp_stiffness']
    sim.stacking_stiffness = p['stacking_stiffness']
    sim.noise_amplitude    = p['noise_amplitude']
    sim.substeps_per_frame = p['substeps']

    rmsds    = {}
    blown    = False
    converge = None
    ss       = p['substeps']

    for frame in range(1, N_FRAMES + 1):
        xpbd_step(sim, ss)
        if frame in MEASURE_AT:
            r = _rmsd(sim.positions, target)
            if np.isnan(r) or r > EXPLODE_THRESHOLD:
                blown = True
                for f in [f for f in MEASURE_AT if f >= frame]:
                    rmsds[f] = float('nan')
                break
            rmsds[frame] = r
            if converge is None and r <= CONVERGE_THRESHOLD:
                converge = frame

    return {'rmsds': rmsds, 'blown': blown, 'converge': converge}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    out = os.path.join(os.path.dirname(__file__), 'results')
    os.makedirs(out, exist_ok=True)

    summary   = ['Experiment 18 — loop/skip convergence\n\n']
    all_data  = []   # (label, init_rmsd, mods, sweep_results, combo_results)

    for cfg in DESIGNS:
        label = cfg['label']
        print(f'\n=== Design {label} ===')
        design, mods, actual_angle = _build_design(cfg)

        # Export
        nadoc_path = os.path.join(out, f'design_{label}.nadoc')
        with open(nadoc_path, 'w') as f:
            f.write(design.to_json())
        print(f'  exported {nadoc_path}')

        # Summarise mods
        total_mods = sum(len(v) for v in mods.values())
        n_inner = sum(len(v) for k, v in mods.items() if any(ls.delta < 0 for ls in v))
        for hid, ls in mods.items():
            ins = sum(1 for x in ls if x.delta > 0)
            dels = sum(1 for x in ls if x.delta < 0)
            print(f'  {hid}: +{ins} inserts, -{dels} deletes')

        summary.append(f'--- {label} (angle={actual_angle:.1f}°) ---\n')
        summary.append(f'  total mods: {total_mods}\n')

        # Geometry
        deformed_geo    = _to_geo(design, deformed=True)
        straight_design = design.model_copy(update={'deformations': []})
        straight_geo    = _to_geo(straight_design, deformed=False)

        ref_sim   = build_simulation(design, deformed_geo)
        target    = ref_sim.positions.copy()
        init_sim  = build_simulation(design, deformed_geo, straight_geometry=straight_geo)
        init_rmsd = _rmsd(init_sim.positions, target)
        n_p       = len(target)
        n_bonds   = len(ref_sim.bond_ij)

        print(f'  {n_p} particles,  {n_bonds} bonds,  initial RMSD: {init_rmsd:.3f} nm')
        summary.append(f'  particles: {n_p},  bonds: {n_bonds},  init_rmsd: {init_rmsd:.3f} nm\n')

        # Sweeps
        sweep_results = {}
        for param, values in SWEEPS_PER_DESIGN.items():
            results = []
            for val in values:
                p_key = ('noise_amplitude' if param == 'noise' else param)
                res   = _run_trial({p_key: val}, deformed_geo, straight_geo, design, target)
                results.append(res)
                status = ('BLOWN' if res['blown'] else
                          (f'conv@{res["converge"]}' if res['converge'] else
                           f'final={res["rmsds"].get(N_FRAMES, "?"):.3f}nm'))
                print(f'  {param}={val}  {status}')
                summary.append(f'  {param}={val}  {status}\n')
            sweep_results[param] = (values, results)

        # Combos
        combo_results = []
        print('  Combos:')
        for name, params in COMBOS:
            res = _run_trial(params, deformed_geo, straight_geo, design, target)
            combo_results.append((name, params, res))
            status = ('BLOWN' if res['blown'] else
                      (f'conv@{res["converge"]}' if res['converge'] else
                       f'final={res["rmsds"].get(N_FRAMES, "?"):.3f}nm'))
            print(f'    [{name}]  {status}')
            summary.append(f'  combo [{name}]  {status}\n')

        all_data.append((label, init_rmsd, n_p, n_bonds, mods,
                         actual_angle, sweep_results, combo_results))
        summary.append('\n')

    # ── Summary figure ────────────────────────────────────────────────────────
    n_designs = len(all_data)
    n_params  = len(SWEEPS_PER_DESIGN)
    fig = plt.figure(figsize=(5 * (n_params + 2), 4.5 * n_designs + 2))
    fig.patch.set_facecolor(_DARK)
    gs = gridspec.GridSpec(n_designs, n_params + 2, figure=fig,
                           hspace=0.5, wspace=0.35,
                           left=0.05, right=0.98, top=0.94, bottom=0.05)
    cmap_s = plt.cm.plasma
    cmap_c = plt.cm.tab10

    for row, (label, init_rmsd, n_p, n_bonds, mods,
              actual_angle, sweep_results, combo_results) in enumerate(all_data):
        row_label = f'{label} ({n_p}p, {n_bonds}b, {actual_angle:.0f}°)'

        # Sweep panels
        for col, (param, (values, results)) in enumerate(sweep_results.items()):
            ax = fig.add_subplot(gs[row, col]); _dark(ax)
            for i, (val, res) in enumerate(zip(values, results)):
                col_c = cmap_s(i / max(len(values) - 1, 1))
                frames = sorted(res['rmsds'])
                rmsds  = [res['rmsds'][f] for f in frames]
                label_s = f'{val}' + (f' ✓{res["converge"]}' if res['converge'] else '')
                ax.plot(frames, rmsds, color=col_c, linewidth=1.5,
                        linestyle='--' if res['blown'] else '-', label=label_s)
            ax.axhline(CONVERGE_THRESHOLD, color=_GREEN, linewidth=1, linestyle=':')
            ax.set_yscale('log')
            ax.set_title(f'{row_label}\n{param}', color=_TEXT, fontsize=8)
            ax.set_xlabel('frame', fontsize=8)
            if col == 0: ax.set_ylabel('RMSD (nm)', fontsize=8)
            leg = ax.legend(fontsize=6, loc='upper right', title=param, title_fontsize=6,
                            facecolor='#161b22', edgecolor=_GRID, labelcolor=_TEXT)
            leg.get_title().set_color(_TEXT)

        # Combo panel
        ax_c = fig.add_subplot(gs[row, n_params]); _dark(ax_c)
        for i, (name, _, res) in enumerate(combo_results):
            col_c  = cmap_c(i / 10)
            frames = sorted(res['rmsds'])
            rmsds  = [res['rmsds'][f] for f in frames]
            label_s = name[:20] + (f' ✓{res["converge"]}' if res['converge'] else '')
            ax_c.plot(frames, rmsds, color=col_c, linewidth=1.5,
                      linestyle='--' if res['blown'] else '-', label=label_s)
        ax_c.axhline(CONVERGE_THRESHOLD, color=_GREEN, linewidth=1, linestyle=':')
        ax_c.set_yscale('log')
        ax_c.set_title(f'{row_label}\ncombos', color=_TEXT, fontsize=8)
        ax_c.set_xlabel('frame', fontsize=8)
        leg = ax_c.legend(fontsize=5.5, loc='upper right',
                          facecolor='#161b22', edgecolor=_GRID, labelcolor=_TEXT)

        # Convergence bar chart
        ax_b = fig.add_subplot(gs[row, n_params + 1]); _dark(ax_b)
        entries = [(n, r['converge'], r['rmsds'].get(N_FRAMES), r['blown'])
                   for n, _, r in combo_results]
        entries.sort(key=lambda x: (x[3], x[1] is None, x[1] or 9999, x[2] or 9999))
        bar_labels = [e[0] for e in entries]
        bar_vals   = []
        bar_cols   = []
        for _, conv, final, blown in entries:
            if blown:
                bar_vals.append(N_FRAMES); bar_cols.append('#ff4444')
            elif conv:
                bar_vals.append(conv); bar_cols.append(_GREEN)
            else:
                frac = (final / init_rmsd) if (final and init_rmsd) else 1.0
                bar_vals.append(N_FRAMES * frac); bar_cols.append('#f0c030')
        xp = np.arange(len(bar_labels))
        ax_b.barh(xp, bar_vals, color=bar_cols, height=0.6, edgecolor=_GRID)
        ax_b.set_yticks(xp)
        ax_b.set_yticklabels(bar_labels, fontsize=7)
        ax_b.set_xlabel('frames', fontsize=8)
        ax_b.set_title(f'{row_label}\nconvergence', color=_TEXT, fontsize=8)
        ax_b.axvline(N_FRAMES, color=_GRID, linewidth=1, linestyle='--')
        ax_b.invert_yaxis()

    fig.suptitle(
        f'Exp18: Loop/Skip XPBD Convergence  |  {N_FRAMES} frames × substeps  |  '
        f'threshold {CONVERGE_THRESHOLD} nm',
        color=_TEXT, fontsize=11, y=0.98,
    )
    out_fig = os.path.join(out, 'summary_figure.png')
    fig.savefig(out_fig, dpi=130, facecolor=_DARK)
    plt.close(fig)
    print(f'\n  saved {out_fig}')

    with open(os.path.join(out, 'summary.txt'), 'w') as f:
        f.writelines(summary)
    print('Done.')


if __name__ == '__main__':
    main()
