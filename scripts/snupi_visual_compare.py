#!/usr/bin/env python3
"""Automated per-VISUAL comparison of the SNUPI/CanDo prediction vs NAMD.

Each in-app SNUPI display mode is backed by a computable quantity; this harness measures every one
against the free (k=0) NAMD trajectory so "how close is each visual to MD?" is a number, not an
eyeball. Covers all the shape solvers (cando, snupi default = ES-free relaxation, snupi corotational
= the opt-in Newton with electrostatics) so the shape-vs-MD gap is attributable.

Per design (only those with an on-disk free-k0 DCD) it reports, for each engine variant:
  • SHAPE (deform / cylinders / deviation modes): per-bp RMSD to the NAMD mean structure (Kabsch-
    aligned) + twist/bend/span descriptors vs NAMD. This is where the default relaxation reads as
    "≈ the straight design" while MD carries a small intrinsic twist/bend.
  • FLEX (RMSF map): per-bp RMSF pattern Pearson/Spearman vs NAMD (the validated channel).
  • CORRELATION (DCCM): off-diagonal Pearson of the bp-bp correlation matrix vs the NAMD DCCM.

DCDs are local-only (gitignored) — a documented analysis, not a CI pin. The visual-COMPUTATION
building blocks are unit-tested separately (tests/test_snupi_visual_compare.py). Writes
experiments/exp42_snupi_cross_compare/visual.json.

Usage:  uv run python scripts/snupi_visual_compare.py [--only 6hbx100_noT,3x4SQ] [--max-frames 150]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.core.models import Design                                  # noqa: E402
from backend.physics.fem_solver import (                               # noqa: E402
    assemble_global_stiffness, assemble_mass_matrix, build_fem_mesh,
    compute_correlation_matrix, predict_shape,
)
from backend.core.cando_shape_source import build_cando_shape_source   # noqa: E402
from backend.core.shape_compare import build_comparison_report         # noqa: E402
from backend.api.skip_twist_tuning import core_reference_geometry      # noqa: E402
from scripts.snupi_cross_compare import BATTERY, WS, OUT_DIR, _load, _md_source  # noqa: E402
from scripts.snupi_dccm_compare import _md_dccm, _fe_dccm, _agree      # noqa: E402


# ── Shape helpers ───────────────────────────────────────────────────────────────

def _kabsch_rmsd(A: np.ndarray, B: np.ndarray) -> float:
    """RMSD (nm) of A onto B after optimal rigid superposition (both (N,3), matched rows)."""
    Ac = A - A.mean(0); Bc = B - B.mean(0)
    U, _, Vt = np.linalg.svd(Ac.T @ Bc)
    d = np.sign(np.linalg.det(U @ Vt))
    R = U @ np.diag([1, 1, d]) @ Vt
    return float(np.sqrt(((Ac @ R - Bc) ** 2).sum(1).mean()))


def _fe_axis_centers(result: dict):
    """(keys, positions) of the FE per-bp axis (helix-centre) nodes, keyed by (helix, bp)."""
    axis = result.get("axis") or []
    keys, pos = [], []
    for a in axis:
        keys.append((a["helix_id"], int(a["bp_index"])))
        p = a.get("position") or a.get("backbone_position")
        pos.append(p)
    return keys, np.array(pos, dtype=float)


def _md_mean_centers(entry: dict, max_frames: int):
    """(keys, mean bp-centre positions) from the free k=0 DCD — the NAMD mean structure."""
    from backend.core.md_trajectory import (
        _build_md_nadoc_ctx, _extract_md_nadoc_frame, _stride_pick)
    md = entry["md"]; jd = WS / "md_jobs" / md["job"]
    pkg = next((jd / "package").glob("*/"), None)
    if pkg is None:
        return None, None
    psf = pkg / f"{md['stem']}.psf"; ref = pkg / f"{md['stem']}.pdb"; dcd = pkg / "output" / md["dcd"]
    if not (psf.exists() and ref.exists() and dcd.exists()):
        return None, None
    design = (Design.model_validate_json((jd / "design.json").read_text())
              if md["design_json"] else Design.model_validate_json((WS / entry["nadoc"]).read_text()))
    ctx = _build_md_nadoc_ctx(str(psf), [str(dcd)], str(ref), design, with_termini=False)
    p_order = ctx["p_order"]; n = ctx["n_frames"]
    if n <= 0 or not p_order:
        return None, None
    idxs = list(range(n)) if n <= max_frames else _stride_pick(list(range(n)), max_frames)
    per_bp: dict = {}
    for i, (hid, bp, direction) in enumerate(p_order):
        per_bp.setdefault((hid, int(bp)), {})[direction] = i
    bp_keys = [k for k, dd in per_bp.items() if len(dd) >= 2]
    fi = np.array([per_bp[k][list(per_bp[k])[0]] for k in bp_keys])
    ri = np.array([per_bp[k][list(per_bp[k])[1]] for k in bp_keys])
    acc = np.zeros((len(bp_keys), 3)); used = 0
    for g in idxs:
        out = _extract_md_nadoc_frame(ctx, g, with_c1p=True, with_termini=False)
        c1p = out[2] if out is not None else None
        if c1p is None or len(c1p) != len(p_order):
            continue
        acc += 0.5 * (c1p[fi] + c1p[ri]); used += 1
    if used < 1:
        return None, None
    return bp_keys, acc / used


def _shape_rmsd_vs_md(fe_keys, fe_pos, md_keys, md_pos):
    if fe_pos is None or md_pos is None:
        return None
    idx = {k: i for i, k in enumerate(md_keys)}
    common = [k for k in fe_keys if k in idx]
    if len(common) < 4:
        return None
    A = np.array([fe_pos[fe_keys.index(k)] for k in common])
    B = np.array([md_pos[idx[k]] for k in common])
    return round(_kabsch_rmsd(A, B), 3)


# ── Per-engine descriptors vs MD (twist/bend/span) via the shared report ────────

def _descriptors(design, result, engine, md_src):
    src = build_cando_shape_source(result["positions"], core_reference_geometry(design),
                                   rmsf=result.get("rmsf"))
    src["engine"] = engine
    rep = build_comparison_report([md_src, src])
    out = {}
    for sc in rep.get("scalars", []):
        c = sc.get("cells", {})
        def val(e):
            v = c.get(e, {}).get("value")
            return round(v, 2) if isinstance(v, float) else v
        out[sc["name"]] = {"md": val("namd"), engine: val(engine)}
    # RMSF agreement vs MD
    for row in rep.get("agreement", []):
        if row["engine"] == engine and row.get("rmsf"):
            out["rmsf_vs_md"] = {k: round(row["rmsf"][k], 4) if isinstance(row["rmsf"].get(k), float)
                                 else row["rmsf"].get(k) for k in ("pearson", "spearman")}
    return out


VARIANTS = [
    ("cando", dict(material="cando")),
    ("snupi", dict(material="snupi")),                       # default = ES-free relaxation
    ("snupi_corot", dict(material="snupi", corotational=True)),
]


def run(entry: dict, max_frames: int) -> dict:
    name = entry["name"]
    print(f"[{name}] visuals vs NAMD …")
    design = _load(entry["nadoc"])
    md_src, _ = _md_source(entry)
    md_keys, md_pos = _md_mean_centers(entry, max_frames)
    md_dkeys, md_dccm = _md_dccm(entry, max_frames)
    out = {"design": name, "lattice": entry["lattice"], "engines": {}}
    for label, kw in VARIANTS:
        eng = "cando" if kw["material"] == "cando" else "snupi"
        res = predict_shape(design, nonlinear=True, with_rmsf=True, **kw)
        desc = _descriptors(design, res, eng, md_src) if md_src else {}
        fe_keys, fe_pos = _fe_axis_centers(res)
        rmsd = _shape_rmsd_vs_md(fe_keys, fe_pos, md_keys, md_pos)
        # DCCM vs MD
        mesh = build_fem_mesh(design)
        K, _ = assemble_global_stiffness(mesh, material=kw["material"], bp_registered_frame=True)
        M = assemble_mass_matrix(mesh, design) if kw["material"] == "snupi" else None
        C = compute_correlation_matrix(K, len(mesh.nodes), M=M)
        fe_ck = [(n.helix_id, int(n.global_bp)) for n in mesh.nodes]
        dccm = _agree(fe_ck, C, md_dkeys, md_dccm)["pearson"] if md_dccm is not None else None
        out["engines"][label] = {
            "shape_rmsd_vs_md_nm": rmsd,
            "twist_deg": desc.get("twist_total_deg"),
            "bend_deg": desc.get("bend_angle_deg"),
            "span_nm": desc.get("axial_span_nm"),
            "rmsf_vs_md": desc.get("rmsf_vs_md"),
            "dccm_vs_md_pearson": dccm,
        }
        print(f"    {label:12} shapeRMSD={rmsd} twist={desc.get('twist_total_deg')} "
              f"bend={desc.get('bend_angle_deg')} rmsf={desc.get('rmsf_vs_md')} dccm={dccm}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="6hbx100_noT,3x4SQ")
    ap.add_argument("--max-frames", type=int, default=150)
    args = ap.parse_args()
    want = {s.strip() for s in args.only.split(",")}
    battery = [e for e in BATTERY if e["name"] in want and e.get("md")]
    results = [run(e, args.max_frames) for e in battery]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "visual.json").write_text(json.dumps({"results": results}, indent=2))
    print(f"\nfull JSON → {OUT_DIR / 'visual.json'}")


if __name__ == "__main__":
    main()
