"""Batch-measure the CanDo returns for the bend-gap battery (B1..B4) and tabulate
CanDo bend/R vs the NADOC analytic targets + the native-FEM linear prediction.

For each design: point cloud from the atomic PDB (MODEL 1, C1') if present, else the
coarse deformedShape.bild sphere centers; bend via arc-span + chord-sagitta on the
cross-section-centroid centerline (the A9-safe estimators). RMSF from the coarse
structure_NMA_RMSF.txt. FEM linear bend from build_fem_mesh -> prestress -> linear solve.

Run: uv run python experiments/exp36_cando_fem_validation/process_bend_battery.py
"""
import io
import sys
import zipfile
from pathlib import Path

REPO = Path("/home/joshua/NADOC")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "exp36_cando_fem_validation"))

import numpy as np
import analyze_cando_pdb as acp
from backend.core.models import Design
from backend.physics import fem_solver as fem
import fem_bend_diagnostics as fbd

VAL = REPO / "workspace" / "cando validation"

# design key -> (analytic bend deg, analytic R nm)  [from _bend_diagnostics_manifest.json]
TARGETS = {
    "B1_density_full": (90, 45.5), "B1_density_half": (90, 45.5),
    "B1_density_quarter": (90, 45.5), "B1_density_minimal": (90, 45.5),
    "B2_bend_030": (30, 136.4), "B2_bend_045": (45, 81.8), "B2_bend_060": (60, 68.2),
    "B2_bend_090": (90, 45.5), "B2_bend_135": (135, 29.2),
    "B3_len_105": (45, 40.9), "B3_len_210": (90, 45.5), "B3_len_420": (180, 45.5),
    "B4_2hb_bend": (90, 47.3), "B4_4hb_bend": (90, 40.9),
}
ORDER = ["B1_density_full", "B1_density_half", "B1_density_quarter", "B1_density_minimal",
         "B2_bend_030", "B2_bend_045", "B2_bend_060", "B2_bend_090", "B2_bend_135",
         "B3_len_105", "B3_len_210", "B3_len_420", "B4_2hb_bend", "B4_4hb_bend"]
STAPLE_XO = {"B1_density_full": 112, "B1_density_half": 56, "B1_density_quarter": 28,
             "B1_density_minimal": 1}


def _pdb_cloud(zip_atomic):
    """MODEL 1 C1' coords (Å) from a *_atomic.zip."""
    zf = zipfile.ZipFile(zip_atomic)
    pdb = [n for n in zf.namelist() if n.endswith(".pdb")]
    if not pdb:
        return None
    txt = zf.read(pdb[0]).decode("utf-8", "replace")
    coords, cur, want = [], 0, None
    for ln in txt.splitlines():
        if ln.startswith("MODEL"):
            cur = int(ln.split()[1]); want = (cur == 1)
        elif ln.startswith("ENDMDL"):
            want = False
        elif ln.startswith(("ATOM", "HETATM")) and (want is None or want):
            if ln[12:16].strip() != "C1'":
                continue
            coords.append((float(ln[30:38]), float(ln[38:46]), float(ln[46:54])))
    return np.asarray(coords) if len(coords) >= 20 else None


def _bild_cloud(zip_coarse):
    """Node cloud (Å) from structure_NLSA_deformedShape.bild — the shape is drawn as
    `.cylinder x1 y1 z1 x2 y2 z2 r` segments between consecutive bp nodes; collect each
    segment's first endpoint (+ the last segment's second endpoint)."""
    zf = zipfile.ZipFile(zip_coarse)
    b = [n for n in zf.namelist() if n.endswith("deformedShape.bild")]
    if not b:
        return None
    txt = zf.read(b[0]).decode("utf-8", "replace")
    pts, last = [], None
    for ln in txt.splitlines():
        p = ln.split()
        if p and p[0] == ".cylinder" and len(p) >= 7:
            pts.append((float(p[1]), float(p[2]), float(p[3])))
            last = (float(p[4]), float(p[5]), float(p[6]))
        elif p and p[0] == ".sphere" and len(p) >= 5:
            pts.append((float(p[1]), float(p[2]), float(p[3])))
    if last is not None:
        pts.append(last)
    return np.asarray(pts) if len(pts) >= 20 else None


def _rmsf(zip_coarse):
    zf = zipfile.ZipFile(zip_coarse)
    r = [n for n in zf.namelist() if n.endswith("NMA_RMSF.txt")]
    if not r:
        return None
    vals = []
    for ln in zf.read(r[0]).decode("utf-8", "replace").splitlines():
        parts = ln.split(",")
        if len(parts) < 2:
            continue
        try:                       # "Node, RMSF(nm)": take the 2nd column (the RMSF)
            vals.append(float(parts[1]))
        except ValueError:
            continue               # header row
    v = np.array(vals)
    return None if v.size == 0 else (v.min(), v.max(), v.mean())


def _bend_from_cloud(P):
    """Arc-span + chord-sagitta bend (deg), R (nm), planarity — same math as analyze()."""
    c = P.mean(0); Q = P - c
    _, S, Vt = np.linalg.svd(Q, full_matrices=False)
    planar = S[2] ** 2 / S[1] ** 2
    uv = np.column_stack([Q @ Vt[0], Q @ Vt[1]])
    cen = acp.ordered_centerline(uv)
    ccx, ccy, R = acp.kasa_circle(cen)
    ca = np.arctan2(cen[:, 1] - ccy, cen[:, 0] - ccx)
    un = np.unwrap(ca)
    span = np.degrees(abs(un[-1] - un[0]))
    chord = np.linalg.norm(cen[-1] - cen[0])
    sag = np.degrees(2 * np.arcsin(np.clip(chord / (2 * R), -1, 1)))
    return 0.5 * (span + sag), R / 10.0, planar, abs(span - sag)


def _fem_linear_bend(stem):
    """FEM linear bend measured with the SAME arc-span estimator used for CanDo.

    NB: an earlier version used an end-tangent estimator here while CanDo used arc-span —
    an inconsistent-estimator bug that fabricated a ~0.68 'bend gap'. The end-tangent
    reads low on real FEM arcs (straightened ends): 05 reads 61° by end-tangent but 78°
    by arc-span, where CanDo is 87°. Measure BOTH with arc-span (see bend_diagnostics_results).
    """
    p = VAL / f"{stem}.nadoc"
    if not p.exists():
        return None
    design = Design.model_validate_json(p.read_text())
    mesh = fem.build_fem_mesh(design)
    try:
        K, _ = fem.assemble_global_stiffness(mesh)
        f = fem.assemble_prestress_force(mesh, design)
        Kf, ff, free = fem.apply_boundary_conditions(K, f, mesh)
        u = fem.solve_equilibrium(Kf, ff, K.shape[0], free)
        # deformed node cloud → same arc-span estimator as CanDo (_bend_from_cloud)
        cloud = np.array([mesh.nodes[i].position + u[6 * i:6 * i + 3]
                          for i in range(len(mesh.nodes))]) * 10.0  # nm→Å (estimator is Å)
        bend, _, _, _ = _bend_from_cloud(cloud)
        return bend
    except Exception as e:
        return f"err:{type(e).__name__}"


def main():
    rows = []
    for key in ORDER:
        coarse = VAL / f"{key}.zip"
        atomic = VAL / f"{key}_atomic.zip"
        if not coarse.exists() and not atomic.exists():
            continue
        P = _pdb_cloud(atomic) if atomic.exists() else None
        src = "atomic"
        if P is None and coarse.exists():
            P = _bild_cloud(coarse)
            src = "bild"
        if P is None:
            print(f"{key}: NO usable geometry"); continue
        bend, R, planar, agree = _bend_from_cloud(P)
        rmsf = _rmsf(coarse) if coarse.exists() else None
        femb = _fem_linear_bend(key)
        tb, tR = TARGETS[key]
        rows.append(dict(key=key, src=src, npts=len(P), cando_bend=bend, cando_R=R,
                         planar=planar, agree=agree, target_bend=tb, target_R=tR,
                         ratio=bend / tb, fem=femb, rmsf=rmsf,
                         staple_xo=STAPLE_XO.get(key)))

    print(f"\n{'design':20s} {'src':6s} {'CanDo°':>7s} {'R nm':>6s} {'plan':>5s} "
          f"{'targ°':>6s} {'ratio':>6s} {'FEM°':>7s} {'FEMratio':>8s}  RMSF(min/mean/max nm)")
    print("-" * 108)
    for r in rows:
        femtxt = f"{r['fem']:.1f}" if isinstance(r["fem"], (int, float)) else str(r["fem"])
        femrat = f"{r['fem']/r['target_bend']:.2f}" if isinstance(r["fem"], (int, float)) else "-"
        rm = (f"{r['rmsf'][0]:.2f}/{r['rmsf'][2]:.2f}/{r['rmsf'][1]:.2f}"
              if r["rmsf"] else "-")
        sus = "  <-NONPLANAR/suspect" if r["planar"] > 0.35 else ""
        print(f"{r['key']:20s} {r['src']:6s} {r['cando_bend']:7.1f} {r['cando_R']:6.1f} "
              f"{r['planar']:5.2f} {r['target_bend']:6.0f} {r['ratio']:6.2f} "
              f"{femtxt:>7s} {femrat:>8s}  {rm}{sus}")

    # B1 density-sweep slope: does CanDo bend depend on staple-crossover count?
    b1 = [r for r in rows if r["key"].startswith("B1_")]
    if b1:
        print("\n── B1 crossover-density sweep (the decisive plot) ──")
        for r in sorted(b1, key=lambda x: -x["staple_xo"]):
            femtxt = f"{r['fem']:.1f}" if isinstance(r["fem"], (int, float)) else str(r["fem"])
            print(f"  staple_xo={r['staple_xo']:4d}  CanDo={r['cando_bend']:5.1f}°  "
                  f"FEM={femtxt}°  ratio={r['ratio']:.2f}")


if __name__ == "__main__":
    main()
