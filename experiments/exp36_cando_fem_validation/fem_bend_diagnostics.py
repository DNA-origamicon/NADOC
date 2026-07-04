"""In-code FEM bend-gap diagnostics (HANDOFF section 5 — no CanDo run needed).

Given today's .inp finding that CanDo 05 has 117 HJ crossover elements vs our 122
(SAME inter-helix coupling density; HJ = compliant beams, not rigid links), these
experiments decide whether our ~0.68 bend deficit is a COUPLING problem or an
EIGENSTRAIN-CONVERSION problem:

  E1  baseline bend  — native FEM (rigid-link crossovers) on 05 & 06, nonlinear solve.
  E2  dense coupling — add rigid links between adjacent helices at EVERY duplex bp
      (not just at crossovers). If bend rises toward 87deg -> our coupling is too
      sparse (but CanDo isn't denser -> the fix is HOW the crossover couples). If bend
      does NOT rise -> coupling isn't the lever; it's the eigenstrain->bend conversion.
  E3  axial/bend energy partition — how much of the eigenstrain differential relieves
      as internal AXIAL strain vs converts to bending (the shear-lag fingerprint).

Run: uv run python experiments/exp36_cando_fem_validation/fem_bend_diagnostics.py
"""
import sys
from pathlib import Path

REPO = Path("/home/joshua/NADOC")
sys.path.insert(0, str(REPO))

import numpy as np

from backend.core.models import Design
from backend.physics import fem_solver as fem

VAL = REPO / "workspace" / "cando validation"


# ── Bend measurement (end-tangent angle on the cross-section centerline) ────────

def _centerline(mesh, positions):
    """Ordered centerline: per unique global_bp slice, centroid of that slice's nodes."""
    by_bp = {}
    for i, nd in enumerate(mesh.nodes):
        by_bp.setdefault(nd.global_bp, []).append(positions[i])
    bps = sorted(by_bp)
    return np.array([np.mean(by_bp[b], axis=0) for b in bps])


def _bend_deg(cl):
    """End-to-end bend = angle between the mean tangent of the first vs last 20%."""
    n = len(cl)
    if n < 6:
        return 0.0
    k = max(2, n // 5)
    t0 = cl[k] - cl[0]
    t1 = cl[-1] - cl[-1 - k]
    t0 /= np.linalg.norm(t0) + 1e-12
    t1 /= np.linalg.norm(t1) + 1e-12
    return float(np.degrees(np.arccos(np.clip(t0 @ t1, -1, 1))))


# ── E2: dense inter-helix coupling ──────────────────────────────────────────────

def add_dense_coupling(mesh):
    """Add a rigid link between every pair of ADJACENT-helix nodes that share a bp.

    'Adjacent' = a helix pair that already has >=1 crossover (so we only couple true
    neighbours, not across the bundle). This turns the discrete crossover coupling into
    a continuous one — the shear-lag stress test."""
    # neighbour pairs from existing rigid links
    nbr = set()
    for lk in mesh.rigid_links:
        ha = mesh.nodes[lk.node_i].helix_id
        hb = mesh.nodes[lk.node_j].helix_id
        nbr.add(frozenset((ha, hb)))
    # node index by (helix, bp)
    idx = {(nd.helix_id, nd.global_bp): i for i, nd in enumerate(mesh.nodes)}
    existing = {(lk.node_i, lk.node_j) for lk in mesh.rigid_links}
    added = 0
    for pair in nbr:
        ha, hb = tuple(pair)
        bps_a = {nd.global_bp for nd in mesh.nodes if nd.helix_id == ha}
        bps_b = {nd.global_bp for nd in mesh.nodes if nd.helix_id == hb}
        for bp in bps_a & bps_b:
            i, j = idx[(ha, bp)], idx[(hb, bp)]
            if (i, j) in existing or (j, i) in existing:
                continue
            off = mesh.nodes[j].position - mesh.nodes[i].position
            mesh.rigid_links.append(fem.FEMRigidLink(node_i=i, node_j=j, offset=off))
            added += 1
    return added


# ── E3: axial vs bending strain-energy partition ────────────────────────────────

def energy_partition(mesh, design, u):
    """Split the stored elastic energy of the DNA beams into AXIAL vs BENDING+TORSION.

    For each DNA beam, take the 12-DOF element displacement, transform to local frame,
    and evaluate ½ dᵀ K_local d split by DOF group: axial (local-z translation) vs the
    rest (bending + shear + torsion). Reports the axial fraction of relieved energy."""
    e_axial = e_bend = 0.0
    for el in mesh.elements:
        hi = mesh.nodes[el.node_i].helix_id
        if hi != mesh.nodes[el.node_j].helix_id:
            continue  # crossover link, skip
        L = el.length if el.length > 1e-9 else fem.FEM_RISE_PER_BP
        Kl = fem._beam_stiffness_local(L, el.ea, el.ei, el.gj)
        di, dj = 6 * el.node_i, 6 * el.node_j
        d_glob = np.concatenate([u[di:di + 6], u[dj:dj + 6]])
        # rotate translations+rotations into local frame (R columns = local axes)
        Rt = el.R.T
        d_loc = d_glob.copy()
        for b in range(4):
            d_loc[3 * b:3 * b + 3] = Rt @ d_glob[3 * b:3 * b + 3]
        fl = Kl @ d_loc
        # axial DOFs in local frame: index 2 (u_z node i) and 8 (u_z node j)
        axial_dofs = [2, 8]
        e_ax = 0.5 * sum(d_loc[k] * fl[k] for k in axial_dofs)
        e_tot = 0.5 * float(d_loc @ fl)
        e_axial += e_ax
        e_bend += (e_tot - e_ax)
    tot = e_axial + e_bend
    return {"E_axial": e_axial, "E_bend_torsion": e_bend,
            "axial_fraction": (e_axial / tot) if tot else 0.0}


# ── Driver ───────────────────────────────────────────────────────────────────

def _linear_bend(design, mesh):
    """Single-shot linear solve → (bend_deg, displacement u, node_positions)."""
    K, _ = fem.assemble_global_stiffness(mesh)
    f = fem.assemble_prestress_force(mesh, design)
    Kf, ff, free = fem.apply_boundary_conditions(K, f, mesh)
    u = fem.solve_equilibrium(Kf, ff, K.shape[0], free)
    pos = np.array([mesh.nodes[i].position + u[6 * i:6 * i + 3]
                    for i in range(len(mesh.nodes))])
    return _bend_deg(_centerline(mesh, pos)), u


def run(stem, target_bend, do_nonlinear=False):
    design = Design.model_validate_json((VAL / f"{stem}.nadoc").read_text())

    # E1 baseline (linear) + E3 partition on the same displacement field
    mesh = fem.build_fem_mesh(design)
    bend_lin, u = _linear_bend(design, mesh)
    part = energy_partition(mesh, design, u)

    # E2 dense coupling (linear — fast, still answers "does more coupling raise the bend")
    mesh_d = fem.build_fem_mesh(design)
    n_added = add_dense_coupling(mesh_d)
    bend_d, _ = _linear_bend(design, mesh_d)

    print(f"\n=== {stem}  (target CanDo bend ~ {target_bend} deg) ===", flush=True)
    print(f"  nodes={len(mesh.nodes)}  crossover rigid-links={len(mesh.rigid_links)}", flush=True)
    print(f"  E1 bend (linear)     = {bend_lin:6.1f} deg   ({bend_lin/target_bend:.2f} of CanDo)", flush=True)
    print(f"  E2 dense coupling    = {bend_d:6.1f} deg   ({bend_d/target_bend:.2f} of CanDo)  "
          f"[+{n_added} links → {len(mesh.rigid_links)+n_added} total]", flush=True)
    print(f"  E3 axial energy frac = {part['axial_fraction']*100:5.1f}%  "
          f"(E_axial={part['E_axial']:.3g}, E_bend+tors={part['E_bend_torsion']:.3g} pN·nm)", flush=True)
    out = {"stem": stem, "target": target_bend, "bend_linear": round(bend_lin, 1),
           "bend_dense": round(bend_d, 1), "n_links": len(mesh.rigid_links),
           "n_dense_added": n_added, "axial_fraction": round(part["axial_fraction"], 3)}
    if do_nonlinear:
        mesh_nl = fem.build_fem_mesh(design)
        pos_nl = fem.solve_prestress_shape(design, mesh_nl, n_steps=30)
        bend_nl = _bend_deg(_centerline(mesh_nl, pos_nl))
        print(f"  E1 bend (nonlinear)  = {bend_nl:6.1f} deg   ({bend_nl/target_bend:.2f} of CanDo)", flush=True)
        out["bend_nonlinear"] = round(bend_nl, 1)
    return out


def main():
    results = []
    for stem, tgt in [("05_bend_90", 86.9), ("06_bend_180", 170.1)]:
        if (VAL / f"{stem}.nadoc").exists():
            results.append(run(stem, tgt))
        else:
            print(f"SKIP {stem}: .nadoc not found")
    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  {r['stem']}: lin {r['bend_linear']:.0f} / dense {r['bend_dense']:.0f} "
              f"vs CanDo {r['target']:.0f}  |  axial-relief {r['axial_fraction']*100:.0f}%")
    return results


if __name__ == "__main__":
    main()
