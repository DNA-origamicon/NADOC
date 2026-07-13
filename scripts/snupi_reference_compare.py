#!/usr/bin/env python3
"""Autonomous NADOC → real-SNUPI → mimic comparator loop (machine-local).

Runs the *actual* SNUPI software (compiled MATLAB binary + MATLAB Runtime) on a
NADOC design, parses its ground-truth output, runs our FEM mimic on the same
design, and quantifies per-observable agreement:

    shape   — per-bp RMSD (Kabsch) of the mimic's predicted shape vs SNUPI _STT
    RMSF    — per-bp Pearson/Spearman of the free-free NMA RMSF pattern
    MAC     — Modal Assurance Criterion, mimic modes vs SNUPI's 5 saved modes
              (the new observable — "does the mimic capture SNUPI's lowest
               bending/torsion modes?" answered against ground truth)
    corr    — off-diagonal agreement of the bp-bp correlation matrix (if in .mat)
    L_p     — bending persistence length, mimic vs SNUPI frequencies (best-effort)

Three mimic shape columns are reported (cando, snupi-default = ES-free, snupi
corotational = ES-on Newton) so the shape gap (electrostatics + G10 twist) is
bracketed — the loop MEASURES that gap, it does not "fix" the mimic to SNUPI.

Where a free-k0 NAMD DCD exists, the RMSF/shape are reported 3-way vs MD too.

SNUPI + the MATLAB Runtime are LOCAL-ONLY (never in CI) — like the exp42 DCD
scripts, this is a local analysis tool.  Paths come from the environment:

    SNUPI_HOME   (default ~/SNUPI)              — the SNUPI install dir
    SNUPI_MCR    (default ~/MATLAB_Runtime/R2022b)

The CI-safe pieces (parsers, node-matcher, observable math) live in the tested
module backend/physics/snupi_reference.py.

Usage:
    uv run python scripts/snupi_reference_compare.py --only 6hbx100_noT
    uv run python scripts/snupi_reference_compare.py --only 6hbx100_noT,3x4SQ
    uv run python scripts/snupi_reference_compare.py --only 6hbx100_noT --no-nma  # quick round-trip
    uv run python scripts/snupi_reference_compare.py --parse-only 6hbx100_noT     # reuse last run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.core.models import Design, LatticeType                     # noqa: E402
from backend.core.cadnano import export_cadnano_with_labels             # noqa: E402
from backend.physics.fem_solver import (                               # noqa: E402
    assemble_global_stiffness, assemble_mass_matrix, build_fem_mesh,
    compute_correlation_matrix, compute_generalized_correlation_matrix,
    compute_rmsf_nma, _nma_modes, persistence_length_from_nma, predict_shape,
)
from backend.physics import snupi_reference as sr                       # noqa: E402

SNUPI_HOME = Path(os.environ.get("SNUPI_HOME", str(Path.home() / "SNUPI")))
SNUPI_MCR = Path(os.environ.get("SNUPI_MCR", str(Path.home() / "MATLAB_Runtime" / "R2022b")))
RUNS_SUBDIR = "NADOC_RUNS"                       # under SNUPI_HOME (relative Input.txt path)
WS = REPO / "workspace"
OUT_DIR = REPO / "experiments" / "exp42_snupi_cross_compare"

# The three mimic shape columns compared against SNUPI's _STT shape.
VARIANTS = [
    ("cando", dict(material="cando")),
    ("snupi", dict(material="snupi")),                       # default ES-free relaxation
    ("snupi_corot", dict(material="snupi", corotational=True)),
]

# Designs with an on-disk free-k0 NAMD DCD for the optional 3-way.  DCD name is
# GLOBBED (protocol suffixes like _p100 vary), never hard-coded.
BATTERY = {
    "6hbx100_noT": {"nadoc": "6hbx100_noT.nadoc", "md_job": "892ad3d12d4f", "stem": "6hbx100_noT"},
    "3x4SQ": {"nadoc": "3x4SQ.nadoc", "md_job": "93cdbbd3a3f1", "stem": "3x4SQ"},
}


# ── .snp option file ─────────────────────────────────────────────────────────

# Options we override on top of Default.snp for a static + electrostatics + NMA
# (with RMSF, correlation, 5 saved mode shapes) run.  Heavy/plot outputs off for
# a headless run; PDB_OB_IND 1 keeps RMSF in the PDB occupancy column.
_SNP_OVERRIDES = {
    "DO_STT": "1",
    "DO_ES": "1", "ES_TEMP": "300", "ES_MG": "20", "ES_R_CUT": "2.5", "ES_ITER_NUM": "3",
    "DO_NMA": "1", "NMA_MODE_NUM": "200", "NMA_SAVE_NUM": "5",
    "DO_NMA_RMSF": "1", "DO_NMA_CORR": "1", "RMSF_CORR_TEMP": "300",
    "PDB_OB_IND": "1", "NMA_PLOT_IND": "0", "STT_PLOT_IND": "0",
    "STT_FINL_STL": "0", "STT_FINL_OX": "0", "STT_FINL_PDB": "0", "STT_TRAJ_MODEL": "0",
    "DO_DYN": "0",
}
_SNP_NO_NMA = {**_SNP_OVERRIDES, "DO_NMA": "0", "DO_ES": "0"}   # quick round-trip


def _write_snp(dest: Path, overrides: dict) -> None:
    """Patch Default.snp with our overrides (keeps every key SNUPI expects)."""
    template = (SNUPI_HOME / "Default.snp").read_text().splitlines()
    remaining = dict(overrides)
    out = []
    for line in template:
        m = re.match(r"^([A-Z0-9_]+)(\s+)(.*)$", line)
        if m and m.group(1) in remaining:
            key = m.group(1)
            out.append(f"{key}{m.group(2)}{remaining.pop(key)}")
        else:
            out.append(line)
    # Append any override not present in the template.
    for key, val in remaining.items():
        out.append(f"{key}\t\t{val}")
    dest.write_text("\n".join(out) + "\n")


# ── SNUPI subprocess orchestration ───────────────────────────────────────────

def _load(nadoc: str) -> Design:
    return Design.model_validate_json((WS / nadoc).read_text())


def prep_snupi_inputs(design: Design, basename: str, *, with_nma: bool) -> tuple[Path, list[dict], str]:
    """Write <SNUPI_HOME>/NADOC_RUNS/<basename>/<basename>.{json,snp} + return
    (run_dir, labels, lattice_letter)."""
    cad, labels = export_cadnano_with_labels(design)
    snupi_json = sr.nadoc_json_to_snupi_json(cad)
    snupi_json["name"] = basename
    run_dir = SNUPI_HOME / RUNS_SUBDIR / basename
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{basename}.json").write_text(json.dumps(snupi_json))
    _write_snp(run_dir / f"{basename}.snp", _SNP_OVERRIDES if with_nma else _SNP_NO_NMA)
    lattice = "S" if design.lattice_type == LatticeType.SQUARE else "H"
    return run_dir, labels, lattice


def run_snupi(basename: str, lattice: str, *, timeout_s: int = 2400) -> Path:
    """Point Input.txt at our single design, run SNUPI headless, return the new
    timestamped OUTPUT dir.  Input.txt is saved and restored."""
    if not (SNUPI_HOME / "run_SNUPI.sh").exists():
        raise FileNotFoundError(f"SNUPI not found at {SNUPI_HOME} (set SNUPI_HOME)")
    if not SNUPI_MCR.exists():
        raise FileNotFoundError(f"MATLAB Runtime not found at {SNUPI_MCR} (set SNUPI_MCR)")
    input_txt = SNUPI_HOME / "Input.txt"
    saved = input_txt.read_text() if input_txt.exists() else None
    rel = f"{RUNS_SUBDIR}/{basename}/{basename}"
    before = set((SNUPI_HOME / "OUTPUT").glob(f"{basename}_*"))
    try:
        input_txt.write_text(f"{lattice}  {rel}\n")
        t0 = time.time()
        print(f"    [snupi] running {basename} (lattice {lattice}) … ", flush=True)
        proc = subprocess.run(
            ["./run_SNUPI.sh", str(SNUPI_MCR)],
            cwd=str(SNUPI_HOME), capture_output=True, text=True, timeout=timeout_s,
        )
        print(f"    [snupi] finished in {time.time() - t0:.0f}s (rc={proc.returncode})")
        if proc.returncode != 0:
            tail = "\n".join(proc.stdout.splitlines()[-15:])
            raise RuntimeError(f"SNUPI exited {proc.returncode}. stdout tail:\n{tail}")
    finally:
        if saved is not None:
            input_txt.write_text(saved)
    out = sr.find_snupi_output(SNUPI_HOME / "OUTPUT", basename)
    if out is None or out in before:
        raise RuntimeError(f"No new OUTPUT dir for {basename}")
    return out


# ── Mimic side ───────────────────────────────────────────────────────────────

def _mimic_mesh_nodes(design: Design):
    mesh = build_fem_mesh(design)
    keys = [(n.helix_id, int(n.global_bp)) for n in mesh.nodes]
    pos = np.array([n.position for n in mesh.nodes], dtype=float)
    return mesh, keys, pos


def _mimic_shape_positions(design: Design, keys, **kw) -> Optional[np.ndarray]:
    """Predicted axis positions aligned to the mesh-node order (keys)."""
    res = predict_shape(design, nonlinear=True, with_rmsf=False, **kw)
    axis = {(a["helix_id"], int(a["bp_index"])): a.get("position") for a in res.get("axis", [])}
    try:
        return np.array([axis[k] for k in keys], dtype=float)
    except KeyError:
        return None


# ── Optional 3-way NAMD (read-only reuse; safe alongside a concurrent MD session) ─

def _md_bp_centers_and_rmsf(entry: dict, max_frames: int = 150):
    """(keys, mean bp-center positions nm, per-bp RMSF nm) from the free-k0 DCD, or Nones."""
    try:
        from backend.core.md_trajectory import (
            _build_md_nadoc_ctx, _extract_md_nadoc_frame, _stride_pick)
    except Exception:
        return None, None, None
    jd = WS / "md_jobs" / entry["md_job"]
    pkg = next((jd / "package").glob("*/"), None)
    if pkg is None:
        return None, None, None
    stem = entry["stem"]
    psf, ref = pkg / f"{stem}.psf", pkg / f"{stem}.pdb"
    dcd = _pick_free_k0_dcd(pkg / "output", stem)
    if not (psf.exists() and ref.exists() and dcd):
        return None, None, None
    print(f"    [md] free-k0 DCD: {dcd.name}")
    design = _load(entry["nadoc"])
    try:
        ctx = _build_md_nadoc_ctx(str(psf), [str(dcd)], str(ref), design, with_termini=False)
    except Exception as e:
        print(f"    [md] skipped ({e})")
        return None, None, None
    p_order, n = ctx["p_order"], ctx["n_frames"]
    if n <= 0 or not p_order:
        return None, None, None
    idxs = list(range(n)) if n <= max_frames else _stride_pick(list(range(n)), max_frames)
    per_bp: dict = {}
    for i, (hid, bp, d) in enumerate(p_order):
        per_bp.setdefault((hid, int(bp)), {})[d] = i
    bp_keys = [k for k, dd in per_bp.items() if len(dd) >= 2]
    fi = np.array([per_bp[k][list(per_bp[k])[0]] for k in bp_keys])
    ri = np.array([per_bp[k][list(per_bp[k])[1]] for k in bp_keys])
    frames = []
    for g in idxs:
        out = _extract_md_nadoc_frame(ctx, g, with_c1p=True, with_termini=False)
        c1p = out[2] if out is not None else None
        if c1p is None or len(c1p) != len(p_order):
            continue
        frames.append(0.5 * (c1p[fi] + c1p[ri]))
    if not frames:
        return None, None, None
    arr = np.array(frames)                        # (F, Nbp, 3)
    # Remove rigid-body tumbling before RMSF: Kabsch-align each frame to the
    # running mean (2 iterations to converge the reference).
    mean = arr.mean(0)
    for _ in range(2):
        for k in range(len(arr)):
            R, t, _r = sr._kabsch(arr[k], mean)
            arr[k] = arr[k] @ R.T + t
        mean = arr.mean(0)
    rmsf = np.sqrt(((arr - mean) ** 2).sum(2).mean(0))
    return bp_keys, mean, rmsf


def _pick_free_k0_dcd(output_dir: Path, stem: str) -> Optional[Path]:
    """Pick the genuinely-free (k=0) production DCD.

    The annealing runs name the restraint constant as ``k5 … k0p5 k0p2 … k0``;
    the ``_p10/_p50/_p100`` suffix is the trajectory PERCENTAGE, not a restraint.
    Only ``k0`` as a whole token (``_k0_`` or ``_k0.``) is unrestrained — a naive
    ``*k0*`` glob also matches the restrained ``k0p5`` runs.  Prefer a production
    run, longest ns, full (``_p100``) trajectory, largest file.
    """
    cands = [p for p in output_dir.glob(f"{stem}*.dcd")
             if re.search(r"_k0(?=[._])", p.name)]
    if not cands:
        return None

    def _score(p: Path):
        n = p.name
        mns = re.search(r"(\d+(?:p\d+)?)ns", n)
        ns = float(mns.group(1).replace("p", ".")) if mns else 0.0
        return (1 if "production" in n else 0, ns,
                1 if "_p100" in n else 0, p.stat().st_size)

    return max(cands, key=_score)


# ── Full per-design comparison ───────────────────────────────────────────────

def compare(name: str, out_dir: Path, labels: list[dict], design: Design,
            *, with_nma: bool, max_frames: int) -> dict:
    basename = name
    files = sr.snupi_output_files(out_dir, basename)
    report: dict = {"design": name, "snupi_output": str(out_dir),
                    "lattice": "square" if design.lattice_type == LatticeType.SQUARE else "honeycomb"}

    init_nodes = sr.parse_snupi_pdb(files["init_pdb"])
    stt_nodes = sr.parse_snupi_pdb(files["stt_pdb"]) if files["stt_pdb"].exists() else init_nodes
    mesh, keys, mimic_pos0 = _mimic_mesh_nodes(design)

    match = sr.match_nodes(init_nodes, keys, mimic_pos0, labels=labels)
    report["node_match"] = {
        "method": match.method, "ok": match.ok, "reason": match.reason,
        "residual_nm": match.residual_nm, "n_snupi": match.n_snupi, "n_mimic": match.n_mimic,
        "n_matched": match.n_matched, "n_snupi_unmatched": match.n_snupi_unmatched,
        "n_mimic_unmatched": match.n_mimic_unmatched, "warnings": match.warnings,
    }
    print(f"    [match] {match.method} ok={match.ok} residual={match.residual_nm}nm "
          f"matched={match.n_matched}/{match.n_snupi} — {match.reason}")
    if not match.ok:
        print("    [match] NOT VALIDATED — refusing to compute RMSD/RMSF/MAC (would be meaningless)")
        report["observables"] = None
        return report

    pairs = match.pairs
    snupi_stt_pos = np.array([nd.pos for nd in stt_nodes])

    # Full-precision NMA data from the .mat.  The PDB occupancy column is a
    # DIFFERENT, low-precision quantity (1 decimal, physically not the NMA RMSF);
    # NMA_RMSF from the .mat is the flexibility channel.
    mat = sr.parse_snupi_nma_mat(files["stt_mat"]) if files["stt_mat"].exists() else {}
    if mat.get("eigenvectors") is not None:
        sc = sr.self_consistency(mat)
        report["self_consistency"] = sc
        print(f"    [self-check] parse-fidelity ok={sc.get('ok')} "
              f"RMSF={sc.get('rmsf_median_pct')}% Pearson|Δ|={sc.get('pearson_median_abs')}")
    if "rmsf" in mat and len(mat["rmsf"]) == len(stt_nodes):
        snupi_rmsf = list(mat["rmsf"])
        report["rmsf_source"] = "mat:NMA_RMSF"
    else:
        snupi_rmsf = [nd.rmsf for nd in stt_nodes]
        report["rmsf_source"] = "pdb_occupancy(low-precision fallback)"

    # Lowest SNUPI modes for MAC (full-precision eigenvectors; xyz fallback).
    n_mac_modes = 12
    snupi_modes = sr.snupi_translational_modes(mat, n_mac_modes) if with_nma else []
    if with_nma and not snupi_modes:
        for mode in range(1, int(_SNP_OVERRIDES["NMA_SAVE_NUM"]) + 1):
            mv = sr.parse_snupi_mode_vector(out_dir, basename, mode)
            if mv is not None:
                snupi_modes.append(mv)

    obs = {"shape": {}, "rmsf": {}, "mac": {}, "correlation": {}, "persistence_length": {}}

    # Shape RMSD per mimic variant (predicted shape vs SNUPI _STT).
    for label, kw in VARIANTS:
        shp = _mimic_shape_positions(design, keys, **kw)
        obs["shape"][label] = sr.shape_rmsd_nm(snupi_stt_pos, shp, pairs) if shp is not None else None

    if with_nma:
        # NMA-derived observables use the snupi-material free-free NMA (the validated channel).
        K, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
        M = assemble_mass_matrix(mesh, design)
        mimic_rmsf = compute_rmsf_nma(K, len(mesh.nodes), M=M)
        obs["rmsf"] = sr.rmsf_agreement(snupi_rmsf, mimic_rmsf, pairs)

        if snupi_modes:
            _, phi = _nma_modes(K, M=M)
            if phi is not None:
                mac = sr.mac_matrix(snupi_modes, phi, pairs)
                # Annotate each SNUPI mode with its rigid-body fraction: SNUPI's
                # free-free NMA does NOT project out the 6 zero-frequency rigid
                # modes, so its lowest saved modes are rigid-body residuals
                # (rigid_frac~1) with no elastic mimic counterpart.  Elastic
                # modes (rigid_frac<0.5) are the meaningful MAC comparison.
                s_idx = np.array([si for si, _ in pairs])
                m_idx = np.array([mi for _, mi in pairs])
                matched_pos = np.array([n.position for n in mesh.nodes])[m_idx]
                for a, mode in zip(mac["assignment"], snupi_modes):
                    a["rigid_frac"] = round(sr.rigid_body_fraction(mode[s_idx], matched_pos), 3)
                mac["note"] = ("SNUPI leaves rigid-body residuals in its low modes; "
                               "compare only rigid_frac<0.5 (elastic) entries")
                obs["mac"] = mac

        snupi_pear = mat.get("pearson_correlation")
        if snupi_pear is not None:
            C = compute_correlation_matrix(K, len(mesh.nodes), M=M)
            obs["correlation"]["pearson_vs_snupi"] = sr.correlation_agreement(snupi_pear, C, pairs)
        snupi_gen = mat.get("generalized_correlation")
        if snupi_gen is not None:
            Cg = compute_generalized_correlation_matrix(K, len(mesh.nodes), M=M)
            obs["correlation"]["generalized_vs_snupi"] = sr.correlation_agreement(snupi_gen, Cg, pairs)
        if snupi_pear is None and snupi_gen is None:
            obs["correlation"]["note"] = "SNUPI correlation matrices not found in .mat"

        lp = persistence_length_from_nma(K, mesh, design, M=M)
        lp_mimic = lp.get("L_p_bend_nm")
        obs["persistence_length"]["mimic"] = {k: (round(v, 2) if isinstance(v, float) else v)
                                              for k, v in lp.items()}
        # Apples-to-apples SNUPI L_p via the fundamental-bending amplitude ratio
        # (unit-free: only physical nm fluctuations enter; anchored to the mimic's
        # frequency-based L_p).  See snupi_reference.bending_amplitude_variance.
        if mat.get("eigenvectors") is not None and lp_mimic:
            lamM, phiM = _nma_modes(K, M=M)
            # STT (relaxed) positions — the config SNUPI's NMA linearizes around.
            # Each engine uses its OWN geometry frame (they are rigidly rotated
            # relative to each other; mixing frames corrupts the projection).
            snupi_pos = np.array([nd.pos for nd in stt_nodes])
            a1_s, L_s = sr.bending_amplitude_variance(
                mat["eigenvalues"], mat["eigenvectors"], snupi_pos, n_rigid=sr.SNUPI_N_RIGID)
            a1_m, L_m = sr.bending_amplitude_variance(
                lamM, phiM.T, np.array([n.position for n in mesh.nodes]), n_rigid=0, kbt=4.11)
            if a1_s > 0:
                lp_snupi = lp_mimic * (a1_m / a1_s) * (L_s / L_m) ** 3
                obs["persistence_length"]["snupi_L_p_bend_nm"] = round(lp_snupi, 1)
                obs["persistence_length"]["mimic_over_snupi_softness"] = round(a1_m / a1_s, 3)

    # Optional 3-way vs NAMD.
    entry = BATTERY.get(name)
    if entry:
        md_keys, md_mean, md_rmsf = _md_bp_centers_and_rmsf(entry, max_frames)
        if md_keys is not None:
            md_idx = {k: i for i, k in enumerate(md_keys)}
            three = {}
            # SNUPI shape vs MD mean (over nodes common to match + MD).
            common = [(si, mi) for si, mi in pairs if keys[mi] in md_idx]
            if len(common) >= 4:
                A = snupi_stt_pos[[si for si, _ in common]]
                B = md_mean[[md_idx[keys[mi]] for _, mi in common]]
                three["snupi_shape_rmsd_vs_md_nm"] = sr.shape_rmsd_nm(A, B, [(i, i) for i in range(len(common))])
                if with_nma:
                    s_r = np.array([snupi_rmsf[si] for si, _ in common], dtype=float)
                    m_r = np.array([md_rmsf[md_idx[keys[mi]]] for _, mi in common])
                    three["snupi_rmsf_vs_md"] = sr.rmsf_agreement(list(s_r), list(m_r),
                                                                  [(i, i) for i in range(len(common))])
            obs["three_way_namd"] = three
            print(f"    [md] 3-way: {three}")

    report["observables"] = obs
    # Compact console summary.
    print(f"    [shape] mimic-vs-SNUPI RMSD nm: {obs['shape']}")
    if with_nma:
        print(f"    [rmsf ] {report['rmsf_source']}: {obs['rmsf']}")
        mac_assign = obs.get("mac", {}).get("assignment", [])
        elastic = [(a['snupi_mode'], a['best_mimic_mode'], a['mac'])
                   for a in mac_assign if a.get('rigid_frac', 0) < 0.5]
        n_rigid = sum(1 for a in mac_assign if a.get('rigid_frac', 0) >= 0.5)
        print(f"    [mac  ] {n_rigid} SNUPI rigid-residual modes skipped; "
              f"elastic (snupi→mimic, MAC): {elastic[:6]}")
        print(f"    [corr ] {obs['correlation']}")
        pl = obs['persistence_length']
        print(f"    [L_p  ] mimic {pl.get('mimic', {}).get('L_p_bend_nm')} nm vs SNUPI "
              f"{pl.get('snupi_L_p_bend_nm')} nm (mimic {pl.get('mimic_over_snupi_softness')}× softer)")
    return report


def run_one(name: str, *, with_nma: bool, parse_only: bool, max_frames: int, timeout_s: int) -> dict:
    entry = BATTERY.get(name)
    nadoc = entry["nadoc"] if entry else f"{name}.nadoc"
    design = _load(nadoc)
    print(f"\n[{name}] preparing SNUPI inputs …")
    _, labels, lattice = prep_snupi_inputs(design, name, with_nma=with_nma)
    if parse_only:
        out = sr.find_snupi_output(SNUPI_HOME / "OUTPUT", name)
        if out is None:
            raise RuntimeError(f"--parse-only but no prior OUTPUT for {name}")
        print(f"[{name}] reusing {out}")
    else:
        out = run_snupi(name, lattice, timeout_s=timeout_s)
    return compare(name, out, labels, design, with_nma=with_nma, max_frames=max_frames)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="6hbx100_noT")
    ap.add_argument("--no-nma", action="store_true", help="quick static-only round-trip")
    ap.add_argument("--parse-only", action="store_true", help="reuse the last OUTPUT dir")
    ap.add_argument("--max-frames", type=int, default=150)
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--out", default=str(OUT_DIR / "reference.json"))
    args = ap.parse_args()

    names = [s.strip() for s in args.only.split(",") if s.strip()]
    results = []
    for name in names:
        try:
            results.append(run_one(name, with_nma=not args.no_nma, parse_only=args.parse_only,
                                   max_frames=args.max_frames, timeout_s=args.timeout))
        except Exception as e:
            print(f"[{name}] FAILED: {e}")
            results.append({"design": name, "error": str(e)})

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"results": results}, indent=2))
    print(f"\nfull JSON → {args.out}")


if __name__ == "__main__":
    main()
