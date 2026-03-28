"""
FEM validation experiments — 3D position and displacement checks.

Experiment 1: Node coverage
  Verify every helix has FEM nodes and backbone positions.

Experiment 2: Position fidelity
  Verify deformed_positions returns backbone positions at HELIX_RADIUS
  from the helix axis (not axis positions themselves).

Experiment 3: Displacement sanity
  With no external loads (crossover gaps ≈ 0 in a well-formed design),
  displacements should be small (sub-nm).  Report per-helix max displacement.

Experiment 4: Key format consistency
  Verify every key produced by deformed_positions and normalize_rmsf
  can be reconstructed by split(':') without ambiguity.

Experiment 5: RMSF physical plausibility
  Crossover-dense regions should have lower RMSF than strand termini.

Experiment 6: Crossover gap magnitude
  Report the actual crossover gap magnitudes to understand pre-stress force scale.
"""

import json
import sys
from pathlib import Path

import numpy as np

# Add repo root to path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.models import Design
from backend.core.geometry import nucleotide_positions
from backend.core.constants import HELIX_RADIUS, BDNA_RISE_PER_BP
from backend.physics.fem_solver import (
    FEMMesh,
    build_fem_mesh,
    assemble_global_stiffness,
    apply_boundary_conditions,
    solve_equilibrium,
    compute_rmsf,
    deformed_positions,
    normalize_rmsf,
)

DESIGN_FILE = Path(__file__).parent.parent / "Examples" / "18hb.nadoc"


def load_design(path: Path) -> Design:
    with open(path) as f:
        return Design.model_validate(json.load(f))


def sep(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print('─'*60)


def run_all(design: Design):
    sep("Building FEM mesh")
    mesh = build_fem_mesh(design)
    print(f"  Helices  : {len(design.helices)}")
    print(f"  Nodes    : {len(mesh.nodes)}")
    print(f"  Elements : {len(mesh.elements)}")
    print(f"  Springs  : {len(mesh.springs)}")

    # ── Experiment 1: Node coverage ──────────────────────────────────────────
    sep("Experiment 1 — Node coverage per helix")
    helix_node_counts = {}
    for node in mesh.nodes:
        helix_node_counts[node.helix_id] = helix_node_counts.get(node.helix_id, 0) + 1
    missing = [h.id for h in design.helices if h.id not in helix_node_counts]
    for hid, count in sorted(helix_node_counts.items()):
        expected = next(h.length_bp for h in design.helices if h.id == hid)
        geom_n = round(
            np.linalg.norm(
                np.array([next(h for h in design.helices if h.id == hid).axis_end.x,
                          next(h for h in design.helices if h.id == hid).axis_end.y,
                          next(h for h in design.helices if h.id == hid).axis_end.z]) -
                np.array([next(h for h in design.helices if h.id == hid).axis_start.x,
                          next(h for h in design.helices if h.id == hid).axis_start.y,
                          next(h for h in design.helices if h.id == hid).axis_start.z])
            ) / BDNA_RISE_PER_BP
        )
        match = "✓" if count == geom_n else f"✗ (length_bp={expected}, geom_n={geom_n})"
        print(f"  {hid}: {count} nodes {match}")
    if missing:
        print(f"  MISSING helices: {missing}")
    else:
        print(f"  All {len(helix_node_counts)} helices have nodes ✓")

    # ── Experiment 6: Crossover spring node separation ───────────────────────
    sep("Experiment 6 — Crossover spring node separations (no pre-stress force)")
    seps = [float(np.linalg.norm(mesh.nodes[sp.node_j].position - mesh.nodes[sp.node_i].position))
            for sp in mesh.springs]
    if seps:
        print(f"  Springs   : {len(seps)}")
        print(f"  Sep min   : {min(seps):.4f} nm")
        print(f"  Sep max   : {max(seps):.4f} nm")
        print(f"  Sep mean  : {np.mean(seps):.4f} nm")
        print(f"  (These are designed axis-axis distances; no force is derived from them)")
    else:
        print("  No crossover springs — check design has crossovers!")

    # ── Assemble & solve ─────────────────────────────────────────────────────
    sep("Assembling stiffness & solving")
    K, f = assemble_global_stiffness(mesh)
    print(f"  K shape  : {K.shape}")
    print(f"  f max    : {np.max(np.abs(f)):.4f} pN")

    K_free, f_free, free_dofs = apply_boundary_conditions(K, f, mesh)
    print(f"  Free DOFs: {len(free_dofs)} / {K.shape[0]}")

    positions = np.array([n.position for n in mesh.nodes])
    centroid = positions.mean(axis=0)
    fixed_node = int(np.argmin(np.linalg.norm(positions - centroid, axis=1)))
    fn = mesh.nodes[fixed_node]
    print(f"  Fixed node: {fixed_node} → {fn.helix_id} bp{fn.global_bp} "
          f"(centroid dist={np.linalg.norm(fn.position - centroid):.3f} nm)")

    u = solve_equilibrium(K_free, f_free, K.shape[0], free_dofs)
    print(f"  u max    : {np.max(np.abs(u)):.4f} nm")
    print(f"  u RMS    : {np.sqrt(np.mean(u**2)):.4f} nm")

    # ── Experiment 3: Per-helix displacement ─────────────────────────────────
    sep("Experiment 3 — Per-helix displacement magnitude")
    node_idx_map = {n.helix_id: [] for n in mesh.nodes}
    for i, n in enumerate(mesh.nodes):
        node_idx_map[n.helix_id].append(i)
    for hid, idxs in sorted(node_idx_map.items()):
        disps = [np.linalg.norm(u[6*i:6*i+3]) for i in idxs]
        print(f"  {hid}: max={max(disps):.4f} nm  mean={np.mean(disps):.4f} nm  "
              f"n={len(idxs)} nodes")

    # ── Experiment 2: Position fidelity ──────────────────────────────────────
    sep("Experiment 2 — Backbone position radial offset check")
    results = deformed_positions(design, mesh, u)
    print(f"  Entries returned: {len(results)}")

    # Build node index lookup for radial check
    node_by_key = {(n.helix_id, n.global_bp): (i, n) for i, n in enumerate(mesh.nodes)}
    radial_errors = []
    missing_keys = 0
    per_helix_radial = {}
    for r in results:
        nidx, node = node_by_key.get((r['helix_id'], r['bp_index']), (None, None))
        if nidx is None:
            missing_keys += 1
            continue
        bp_pos = np.array(r['backbone_position'])
        disp = u[6*nidx:6*nidx+3]
        deformed_axis = node.position + disp
        radial = float(np.linalg.norm(bp_pos - deformed_axis))
        radial_errors.append(radial)
        hid = r['helix_id']
        per_helix_radial.setdefault(hid, []).append(radial)

    if radial_errors:
        print(f"  Radial offset — expect ~{HELIX_RADIUS:.3f} nm")
        print(f"    min={min(radial_errors):.4f}  max={max(radial_errors):.4f}  "
              f"mean={np.mean(radial_errors):.4f} nm")
        bad = [(r['helix_id'], r['bp_index'], r['direction'])
               for r, rad in zip(results, radial_errors) if abs(rad - HELIX_RADIUS) > 0.1]
        if bad:
            print(f"  ⚠  {len(bad)} entries with radial offset far from {HELIX_RADIUS} nm:")
            for b in bad[:5]:
                print(f"    {b}")
        else:
            print(f"  All radial offsets within 0.1 nm of HELIX_RADIUS ✓")
    if missing_keys:
        print(f"  ⚠ {missing_keys} entries had no matching FEM node")

    print(f"\n  Per-helix radial offset (mean ± std nm):")
    for hid, rads in sorted(per_helix_radial.items()):
        print(f"    {hid}: {np.mean(rads):.4f} ± {np.std(rads):.4f}")

    # ── Experiment 4: Key format consistency ─────────────────────────────────
    sep("Experiment 4 — Key format / split consistency")
    pos_keys = set()
    for r in results:
        k = f"{r['helix_id']}:{r['bp_index']}:{r['direction']}"
        pos_keys.add(k)
        # Verify round-trip via split
        parts = k.split(':')
        if len(parts) != 3:
            print(f"  ⚠ Key has {len(parts)} parts (expect 3): {k!r}")
        else:
            hid, bp, dirn = parts
            if hid != r['helix_id'] or int(bp) != r['bp_index'] or dirn != r['direction']:
                print(f"  ⚠ Round-trip mismatch for key {k!r}")

    # Count geometry entries for comparison
    geom_keys = set()
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
            geom_keys.add(f"{nuc.helix_id}:{nuc.bp_index}:{nuc.direction.value}")

    in_both = pos_keys & geom_keys
    only_fem = pos_keys - geom_keys
    only_geom = geom_keys - pos_keys
    print(f"  Geometry keys : {len(geom_keys)}")
    print(f"  FEM pos keys  : {len(pos_keys)}")
    print(f"  Matched       : {len(in_both)}")
    if only_fem:
        print(f"  ⚠ In FEM only (helix_id mismatch?): {len(only_fem)}")
        for k in sorted(only_fem)[:3]: print(f"    {k!r}")
    if only_geom:
        print(f"  In geometry only (no FEM node): {len(only_geom)}")
        for k in sorted(only_geom)[:3]: print(f"    {k!r}")
    if not only_fem:
        print(f"  Key format consistent ✓")

    # ── Experiment 5: RMSF physical plausibility ─────────────────────────────
    sep("Experiment 5 — RMSF plausibility")
    rmsf = compute_rmsf(K_free, free_dofs, len(mesh.nodes))
    rmsf_dict = normalize_rmsf(rmsf, mesh)

    print(f"  Raw RMSF range: [{rmsf.min():.4f}, {rmsf.max():.4f}] nm")
    print(f"  Normalised    : [{min(rmsf_dict.values()):.3f}, {max(rmsf_dict.values()):.3f}]")

    # Crossover nodes (highly connected) vs terminal nodes (free ends)
    # Build crossover connectivity
    xo_node_ids = set()
    for sp in mesh.springs:
        xo_node_ids.add(sp.node_i)
        xo_node_ids.add(sp.node_j)
    non_xo_ids = set(range(len(mesh.nodes))) - xo_node_ids
    terminal_ids = set()
    # Terminal: nodes at the start or end of a helix
    by_helix: dict = {}
    for i, n in enumerate(mesh.nodes):
        by_helix.setdefault(n.helix_id, []).append(i)
    for hid, idxs in by_helix.items():
        terminal_ids.add(min(idxs))
        terminal_ids.add(max(idxs))

    xo_rmsf   = [rmsf[i] for i in xo_node_ids if i < len(rmsf)]
    term_rmsf = [rmsf[i] for i in terminal_ids if i < len(rmsf)]
    inter_rmsf = [rmsf[i] for i in range(len(rmsf)) if i not in xo_node_ids and i not in terminal_ids]

    if xo_rmsf:
        print(f"\n  Crossover nodes  : n={len(xo_rmsf)} mean={np.mean(xo_rmsf):.4f} nm")
    if inter_rmsf:
        print(f"  Interior nodes   : n={len(inter_rmsf)} mean={np.mean(inter_rmsf):.4f} nm")
    if term_rmsf:
        print(f"  Terminal nodes   : n={len(term_rmsf)} mean={np.mean(term_rmsf):.4f} nm")
    if xo_rmsf and term_rmsf:
        if np.mean(term_rmsf) > np.mean(xo_rmsf):
            print(f"  Terminals more flexible than crossover nodes ✓ (expected)")
        else:
            print(f"  ⚠ Terminals NOT more flexible than crossover nodes (unexpected)")

    sep("Summary")
    ok = (
        not missing
        and len(seps) > 0
        and np.max(np.abs(u)) < 0.01            # u ≈ 0 (no pre-stress force)
        and not only_fem
        and abs(np.mean(radial_errors) - HELIX_RADIUS) < 0.1
    )
    print(f"  Overall: {'PASS ✓' if ok else 'REVIEW NEEDED ⚠'}")
    return ok


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DESIGN_FILE
    print(f"Loading design: {path}")
    design = load_design(path)
    print(f"  {len(design.helices)} helices, {len(design.strands)} strands, "
          f"{len(design.crossovers)} crossovers, {len(design.crossover_bases)} xo_bases")
    run_all(design)
