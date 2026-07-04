"""CanDo-style staged bend diagnostics for the exp36 bend gap.

CanDo's Abaqus deck does not simply solve ``K u = f_prestress`` from the straight
reference.  It first prescribes cumulative register displacements with HJ/ssDNA
elements removed, then adds HJ elements strain-free, then unloads the temperature
eigenstrain.  This script tests linearized versions of that path without changing
the production FEM solver.

Run:
    uv run python experiments/exp36_cando_fem_validation/staged_bend_diagnostics.py
"""
from __future__ import annotations

import math
import sys
import argparse
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import splu, spsolve

REPO = Path("/home/joshua/NADOC")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "exp36_cando_fem_validation"))

from backend.core.models import Design
from backend.physics import fem_solver as fem
import fem_bend_diagnostics as fbd

VAL = REPO / "workspace" / "cando validation"


CASES = [
    ("05_bend_90", 86.9),
    ("06_bend_180", 170.1),
    ("B1_density_full", 86.5),
    ("B1_density_quarter", 89.5),
    ("B2_bend_030", 29.7),
    ("B2_bend_135", 129.0),
    ("B3_len_420", 165.5),
    ("B4_2hb_bend", 75.3),
    ("B4_4hb_bend", 85.8),
]


def _helix_axes(design: Design) -> dict[str, np.ndarray]:
    axes = {}
    for h in design.helices:
        a = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z], dtype=float)
        b = np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z], dtype=float)
        v = b - a
        axes[h.id] = v / (np.linalg.norm(v) + 1e-12)
    return axes


def _link_endpoint_nodes(mesh: fem.FEMMesh) -> set[int]:
    nodes: set[int] = set()
    for lk in mesh.rigid_links:
        nodes.add(lk.node_i)
        nodes.add(lk.node_j)
    for sp in mesh.springs:
        nodes.add(sp.node_i)
        nodes.add(sp.node_j)
    return nodes


def cumulative_register_field(
    design: Design,
    mesh: fem.FEMMesh,
    *,
    sign: float = -1.0,
    include_torsion: bool = True,
) -> np.ndarray:
    """CanDo InitialDisp-like cumulative register field.

    For each node, every loop/skip upstream shifts the downstream crossover
    register by one bp rise and rotates the local material frame by one helical
    step.  The exact sign is frame-convention dependent, so callers test both
    signs and compare bend magnitudes.
    """
    marks = {
        h.id: sorted((ls.bp_index, ls.delta) for ls in h.loop_skips)
        for h in design.helices
    }
    axes = _helix_axes(design)
    u = np.zeros(6 * len(mesh.nodes), dtype=float)
    twist_per_mark = 2.0 * math.pi / fem.BP_PER_TURN

    for i, nd in enumerate(mesh.nodes):
        cum = sum(delta for bp, delta in marks.get(nd.helix_id, ()) if bp <= nd.global_bp)
        if cum == 0:
            continue
        axis = axes[nd.helix_id]
        u[6 * i : 6 * i + 3] = sign * cum * fem.FEM_RISE_PER_BP * axis
        if include_torsion:
            u[6 * i + 3 : 6 * i + 6] = sign * cum * twist_per_mark * axis
    return u


def split_stiffness(mesh: fem.FEMMesh):
    """Return DNA-only and link-only stiffness matrices for the same node set."""
    dna = fem.FEMMesh(nodes=mesh.nodes, elements=mesh.elements, springs=[], rigid_links=[])
    links = fem.FEMMesh(nodes=mesh.nodes, elements=[], springs=mesh.springs,
                        rigid_links=mesh.rigid_links)
    K_dna, _ = fem.assemble_global_stiffness(dna)
    K_link, _ = fem.assemble_global_stiffness(links)
    return K_dna.tocsr(), K_link.tocsr()


def solve_with_rhs(mesh: fem.FEMMesh, K, rhs: np.ndarray) -> np.ndarray:
    Kf, ff, free = fem.apply_boundary_conditions(K, rhs, mesh)
    return fem.solve_equilibrium(Kf, ff, K.shape[0], free)


def solve_prescribed(K, rhs: np.ndarray, prescribed: dict[int, float]) -> np.ndarray:
    """Solve K u = rhs with arbitrary prescribed DOF values."""
    K = csr_matrix(K)
    n = K.shape[0]
    fixed = np.array(sorted(prescribed), dtype=int)
    vals = np.array([prescribed[i] for i in fixed], dtype=float)
    all_dofs = np.arange(n, dtype=int)
    free = np.setdiff1d(all_dofs, fixed, assume_unique=True)
    u = np.zeros(n, dtype=float)
    u[fixed] = vals
    if len(free) == 0:
        return u
    eff = rhs[free] - K[free, :][:, fixed] @ vals
    u[free] = spsolve(K[free, :][:, free], eff)
    if np.any(~np.isfinite(u)):
        raise ValueError("prescribed solve produced NaN/Inf")
    return u


def bend_from_u(mesh: fem.FEMMesh, u: np.ndarray) -> float:
    pos = np.array([
        mesh.nodes[i].position + u[6 * i : 6 * i + 3]
        for i in range(len(mesh.nodes))
    ])
    return fbd._bend_deg(fbd._centerline(mesh, pos))


def staged_solve(
    design: Design,
    mesh: fem.FEMMesh,
    *,
    register_reference: str,
    sign: float,
    include_torsion: bool,
    use_release_force: bool,
    link_reference_scale: float = 1.0,
    release_force_scale: float = 1.0,
) -> tuple[float, float]:
    """Linearized InitialDisp -> HJgen -> unload diagnostic.

    ``register_reference``:
      - direct: use the cumulative register field itself as the strain-free HJ state.
      - interp0: DNA-only interpolation from prescribed HJ endpoint register, no load.
      - interpT: same, but include the production prestress force during interpolation.

    Final energy is approximated as:
        1/2 u^T K_dna u - f_release^T u
      + 1/2 (u-u_ref)^T K_link (u-u_ref)
    so the final linear system is:
        (K_dna + K_link) u = f_release + K_link u_ref
    """
    K_dna, K_link = split_stiffness(mesh)
    K_full = K_dna + K_link
    f_release = fem.assemble_prestress_force(mesh, design)
    u_reg = cumulative_register_field(
        design, mesh, sign=sign, include_torsion=include_torsion
    )

    if register_reference == "direct":
        u_ref = u_reg
    else:
        endpoints = _link_endpoint_nodes(mesh)
        prescribed = {}
        for node in endpoints:
            for dof in range(6):
                prescribed[6 * node + dof] = u_reg[6 * node + dof]
        rhs = f_release if register_reference == "interpT" else np.zeros_like(f_release)
        u_ref = solve_prescribed(K_dna, rhs, prescribed)

    rhs_final = link_reference_scale * (K_link @ u_ref)
    if use_release_force:
        rhs_final = rhs_final + release_force_scale * f_release
    u = solve_with_rhs(mesh, K_full, np.asarray(rhs_final).ravel())
    return bend_from_u(mesh, u), bend_from_u(mesh, u_ref)


def staged_components(
    design: Design,
    mesh: fem.FEMMesh,
    *,
    sign: float = -1.0,
    include_torsion: bool = True,
):
    """Precompute matrices/vectors for fast staged-reference scaling sweeps."""
    K_dna, K_link = split_stiffness(mesh)
    K_full = K_dna + K_link
    f_release = fem.assemble_prestress_force(mesh, design)
    u_ref = cumulative_register_field(
        design, mesh, sign=sign, include_torsion=include_torsion
    )
    link_rhs = np.asarray(K_link @ u_ref).ravel()
    return K_full, f_release, link_rhs, u_ref


def sweep_link_reference_scale(
    design: Design,
    mesh: fem.FEMMesh,
    target: float,
    *,
    alphas: np.ndarray,
    sign: float = -1.0,
) -> tuple[float, float, list[tuple[float, float]]]:
    """Find the best linear staged-link-reference coefficient for one design."""
    K_full, f_release, link_rhs, _ = staged_components(design, mesh, sign=sign)
    Kf, _, free = fem.apply_boundary_conditions(K_full, np.zeros(K_full.shape[0]), mesh)
    lu = splu(Kf.tocsc())
    out = []
    for alpha in alphas:
        rhs = f_release + alpha * link_rhs
        ff = rhs[free]
        u = np.zeros(K_full.shape[0], dtype=float)
        u[free] = lu.solve(ff)
        out.append((float(alpha), bend_from_u(mesh, u)))
    best = min(out, key=lambda x: abs(x[1] - target))
    return best[0], best[1], out


def corotational_staged_solve(
    design: Design,
    mesh: fem.FEMMesh,
    *,
    link_reference_scale: float,
    n_steps: int = 20,
    sign: float = -1.0,
) -> float:
    """Approximate nonlinear staged release with a strain-free HJ reference.

    This is intentionally diagnostic-grade: DNA beam frames co-rotate with the
    accumulating deformation, while the strain-free HJ reference is kept as the
    InitialDisp register field from the straight deck.  It tests whether the high-
    strain cases need path/large-deflection effects beyond the linear staged term.
    """
    positions = [n.position.copy() for n in mesh.nodes]
    u_total = np.zeros(6 * len(mesh.nodes), dtype=float)
    u_ref = cumulative_register_field(design, mesh, sign=sign, include_torsion=True)

    for _ in range(n_steps):
        fem._reframe_elements(mesh, positions)
        K_dna, K_link = split_stiffness(mesh)
        K_full = K_dna + K_link
        f_release = fem.assemble_prestress_force(mesh, design)
        rhs = (f_release + link_reference_scale * np.asarray(K_link @ u_ref).ravel()) / n_steps
        Kf, ff, free = fem.apply_boundary_conditions(K_full, rhs, mesh)
        du = fem.solve_equilibrium(Kf, ff, K_full.shape[0], free)
        u_total += du
        for i in range(len(positions)):
            positions[i] = positions[i] + du[6 * i : 6 * i + 3]

    fem._reframe_elements(mesh, [n.position for n in mesh.nodes])
    return bend_from_u(mesh, u_total)


def run_case(stem: str, cando_target: float) -> dict[str, float | str]:
    design = Design.model_validate_json((VAL / f"{stem}.nadoc").read_text())
    base_mesh = fem.build_fem_mesh(design)
    baseline, _ = fbd._linear_bend(design, base_mesh)

    out: dict[str, float | str] = {
        "stem": stem,
        "target": cando_target,
        "baseline": baseline,
        "links": len(base_mesh.rigid_links),
        "nodes": len(base_mesh.nodes),
    }
    for sign in (-1.0, 1.0):
        tag = "m" if sign < 0 else "p"
        for ref in ("direct", "interp0", "interpT"):
            mesh = fem.build_fem_mesh(design)
            try:
                bend, ref_bend = staged_solve(
                    design,
                    mesh,
                    register_reference=ref,
                    sign=sign,
                    include_torsion=True,
                    use_release_force=True,
                )
                out[f"{ref}_{tag}"] = bend
                out[f"{ref}_{tag}_ref"] = ref_bend
            except Exception as exc:
                out[f"{ref}_{tag}"] = f"err:{type(exc).__name__}"
    return out


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--nonlinear",
        action="store_true",
        help="also run the slow corotational staged sanity check",
    )
    args = ap.parse_args(argv)

    rows = []
    for stem, target in CASES:
        if not (VAL / f"{stem}.nadoc").exists():
            continue
        rows.append(run_case(stem, target))

    print("\nCanDo staged-path linear diagnostics")
    print("Bend degrees. ref=InitialDisp shape before HJ release; final=after strain-free HJ + release force.")
    print(
        f"{'design':18s} {'CanDo':>7s} {'base':>7s} "
        f"{'direct':>15s} {'interp0':>15s} {'interpT':>15s}"
    )
    print("-" * 84)
    for r in rows:
        def fmt(key: str) -> str:
            v = r[key]
            vr = r.get(f"{key}_ref")
            if isinstance(v, float) and isinstance(vr, float):
                return f"{v:5.1f}/{vr:5.1f}"
            return str(v)

        # Report the larger-magnitude sign result; bend direction sign is arbitrary.
        direct_key = max(("direct_m", "direct_p"),
                         key=lambda k: r[k] if isinstance(r[k], float) else -1)
        interp0_key = max(("interp0_m", "interp0_p"),
                          key=lambda k: r[k] if isinstance(r[k], float) else -1)
        interpT_key = max(("interpT_m", "interpT_p"),
                          key=lambda k: r[k] if isinstance(r[k], float) else -1)
        print(
            f"{str(r['stem']):18s} {float(r['target']):7.1f} {float(r['baseline']):7.1f} "
            f"{fmt(direct_key):>15s} {fmt(interp0_key):>15s} {fmt(interpT_key):>15s}"
        )

    print("\ncell format: final/ref, where ref is the imposed/interpolated InitialDisp bend.")

    print("\nStaged-link coefficient sweep")
    print("Solves K u = f_release + alpha*K_link*u_ref. alpha=0 is baseline; alpha=1 is the full staged term.")
    print(f"{'design':18s} {'CanDo':>7s} {'base':>7s} {'best a':>7s} {'best°':>7s} {'a=0.5':>7s} {'a=0.7':>7s} {'a=1':>7s}")
    print("-" * 78)
    alphas = np.linspace(0.0, 1.2, 13)
    alpha_rows = []
    for stem, target in CASES:
        if not (VAL / f"{stem}.nadoc").exists():
            continue
        design = Design.model_validate_json((VAL / f"{stem}.nadoc").read_text())
        mesh = fem.build_fem_mesh(design)
        baseline, _ = fbd._linear_bend(design, mesh)
        best_a, best_b, sweep = sweep_link_reference_scale(
            design, mesh, target, alphas=alphas, sign=-1.0
        )
        by_alpha = {round(a, 1): b for a, b in sweep}
        alpha_rows.append((stem, target, baseline, best_a, best_b))
        print(
            f"{stem:18s} {target:7.1f} {baseline:7.1f} {best_a:7.2f} {best_b:7.1f} "
            f"{by_alpha.get(0.5, float('nan')):7.1f} {by_alpha.get(0.7, float('nan')):7.1f} "
            f"{by_alpha.get(1.0, float('nan')):7.1f}"
        )

    bend90 = [r for r in alpha_rows if r[0] == "05_bend_90"]
    alpha_05 = bend90[0][3] if bend90 else 0.7
    if args.nonlinear:
        print(f"\nCorotational staged release, using alpha from 05_bend_90 ({alpha_05:.2f})")
        print(f"{'design':18s} {'CanDo':>7s} {'linear':>7s} {'corot':>7s}")
        print("-" * 44)
        # Keep the nonlinear probe small: it is a diagnostic sanity check, not a
        # production solve, and repeated sparse assembly is slow.
        for stem, target in [("05_bend_90", 86.9)]:
            if not (VAL / f"{stem}.nadoc").exists():
                continue
            design = Design.model_validate_json((VAL / f"{stem}.nadoc").read_text())
            mesh_lin = fem.build_fem_mesh(design)
            lin, _ = staged_solve(
                design,
                mesh_lin,
                register_reference="direct",
                sign=-1.0,
                include_torsion=True,
                use_release_force=True,
                link_reference_scale=alpha_05,
            )
            mesh_nl = fem.build_fem_mesh(design)
            nl = corotational_staged_solve(
                design,
                mesh_nl,
                link_reference_scale=alpha_05,
                n_steps=6,
                sign=-1.0,
            )
            print(f"{stem:18s} {target:7.1f} {lin:7.1f} {nl:7.1f}")
    else:
        print("\nSkipping slow corotational staged check. Use --nonlinear for the 05_bend_90 sanity run.")


if __name__ == "__main__":
    main()
