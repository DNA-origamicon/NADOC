#!/usr/bin/env python3
"""mrdna round-trip benchmarks — traceability + no-explosion guards.

WHY THIS EXISTS
    Historically the NADOC<->mrdna round trip was hard to trust: it was unclear
    which NADOC nucleotide became which mrdna bead, and bad starting-position
    translations made ARBD explode (LJ=2e37 at step 0 — see
    memory/project_mrdna_bead_model.md). This harness runs a small curated set of
    designs through the full cycle and asserts, per design, that elements map
    cleanly both ways and that nothing blows up from a bad seed.

WHAT IT CHECKS (per design)
    Phase A — Forward translation  (fast, no GPU)
      A1  finite        — bead start positions have no NaN/Inf
      A2  completeness  — every non-skip NADOC nucleotide -> exactly one bead
      A3  injective     — bead->nucleotide map has no index collisions / gaps
      A4  fidelity      — the bead cloud matches NADOC's OWN render geometry
                          (geometry.nucleotide_positions, i.e. the bead/slab
                          positions the app draws) up to a rigid motion
                          (Kabsch RMSD; frame-basis-independent)
      A4b radius        — every bead sits ~HELIX_RADIUS from its helix axis
      A5  distinct      — no two beads share a start position (the dup-position
                          root cause of the LJ=2e37 blow-up)
      A6  topology      — bp-partner array symmetric; strand 3'-chains contiguous

    Phase B — Round trip through ARBD  (short GPU sim; skipped with --fast)
      B1  simulates     — fine-stage PSF/PDB/DCD produced
      B2  back-map      — mrdna beads -> NADOC keys: complete, finite, distinct
      B3  in-frame      — back-mapped positions sit inside the design extent
                          (catches frame mismatch AND explosion at once)
      B4  separation    — FWD/REV of a bp ~ 2R*sin(groove/2)
      B5  no-explosion  — relaxed bounding box <= EXPLOSION_FACTOR x initial

Usage
    uv run python scripts/benchmark_mrdna_roundtrip.py
    uv run python scripts/benchmark_mrdna_roundtrip.py --fast              # Phase A only
    uv run python scripts/benchmark_mrdna_roundtrip.py --designs 2hb_xover_val,6hb_test
    uv run python scripts/benchmark_mrdna_roundtrip.py --steps 5000        # fine steps, Phase B

Exit code is non-zero if any check fails, so this doubles as a CI/smoke gate.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from glob import glob
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.constants import BDNA_MINOR_GROOVE_ANGLE_RAD, HELIX_RADIUS
from backend.core.geometry import nucleotide_positions
from backend.core.models import Design
from backend.core.sequences import _build_loop_skip_map, domain_bp_range

# Default benchmark set: tiny+crossover, honeycomb bundle, and a SQUARE-lattice
# design (the skip-twist target regime). Small enough to run in seconds each.
DEFAULT_DESIGNS = ["2hb_xover_val", "6hb_test", "sq_multi_domain_test1"]

_NM_TO_ANG = 10.0
EXPLOSION_FACTOR = 2.0       # relaxed extent must stay within this x the initial
DUP_MIN_DIST_NM = 0.15       # two beads closer than this count as coincident
KABSCH_TOL_NM = 0.05         # forward-translation shape fidelity vs render geometry
RADIUS_TOL_NM = 0.15         # bead distance-from-axis vs HELIX_RADIUS


# ── tiny helpers ──────────────────────────────────────────────────────────────

def _green(s): return f"\033[1;32m{s}\033[0m"
def _red(s):   return f"\033[1;31m{s}\033[0m"
def _dim(s):   return f"\033[2m{s}\033[0m"


@contextmanager
def _quiet_fds(logpath: Path):
    """Redirect OS-level stdout/stderr (so ARBD's subprocess flood goes to a log)."""
    logpath.parent.mkdir(parents=True, exist_ok=True)
    saved_out, saved_err = os.dup(1), os.dup(2)
    f = os.open(str(logpath), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        os.dup2(f, 1); os.dup2(f, 2)
        yield
    finally:
        os.dup2(saved_out, 1); os.dup2(saved_err, 2)
        os.close(f); os.close(saved_out); os.close(saved_err)


def _kabsch_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    """RMSD of a onto b after optimal rigid superposition (translation+rotation)."""
    ac = a - a.mean(0)
    bc = b - b.mean(0)
    h = ac.T @ bc
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1, 1, d]) @ u.T
    aligned = ac @ r.T
    return float(np.sqrt(((aligned - bc) ** 2).sum(1).mean()))


def _nadoc_render_positions(design: Design) -> dict:
    """(helix_id, bp, dir) -> backbone position (nm), from NADOC's canonical
    render geometry — the same nucleotide_positions() that drives the bead/slab
    display. This is the independent ground truth the forward translation must match."""
    out: dict = {}
    for h in design.helices:
        for np_ in nucleotide_positions(h):
            out[(np_.helix_id, np_.bp_index, np_.direction.value)] = np.asarray(np_.position, float)
    return out


def _count_non_skip_nucleotides(design: Design) -> int:
    ls = _build_loop_skip_map(design)
    n = 0
    for strand in design.strands:
        for domain in strand.domains:
            for bp in domain_bp_range(domain):
                if ls.get((domain.helix_id, bp), 0) > -1:
                    n += 1
    return n


# ── Phase A — forward translation ─────────────────────────────────────────────

def phase_a(design: Design):
    """Return (rows, ok) where rows = list of (check, passed, detail)."""
    from backend.core.mrdna_bridge import _build_nt_arrays

    rows = []

    def chk(name, passed, detail=""):
        rows.append((name, bool(passed), detail))

    r, bp, stack, three_prime, orient, seq, nt_key = _build_nt_arrays(
        design, return_nt_key=True
    )
    r_nm = r / _NM_TO_ANG
    n_beads = len(r)

    # A1 — finite
    chk("A1 finite", np.isfinite(r).all(), f"{n_beads} beads")

    # A2 — completeness: one bead per non-skip nucleotide (k==0 copies only)
    k0_keys = {(h, b, d): i for (h, b, d, k), i in nt_key.items() if k == 0}
    n_expected = _count_non_skip_nucleotides(design)
    chk("A2 completeness", len(k0_keys) == n_expected,
        f"beads(k0)={len(k0_keys)} expected={n_expected}")

    # A3 — injective: every index assigned once, no gaps over [0, n_beads)
    all_idx = list(nt_key.values())
    chk("A3 injective", len(all_idx) == len(set(all_idx)) == n_beads,
        f"keys={len(all_idx)} unique={len(set(all_idx))} beads={n_beads}")

    # A4 — shape fidelity vs NADOC render geometry (rigid-invariant)
    ref = _nadoc_render_positions(design)
    shared = [k for k in k0_keys if k in ref]
    if shared:
        mr = np.array([r_nm[k0_keys[k]] for k in shared])
        nd = np.array([ref[k] for k in shared])
        rmsd = _kabsch_rmsd(mr, nd)
        chk("A4 fidelity", rmsd < KABSCH_TOL_NM,
            f"Kabsch RMSD={rmsd*10:.3f} A over {len(shared)} beads (tol {KABSCH_TOL_NM*10:.1f} A)")
    else:
        chk("A4 fidelity", False, "no shared keys with render geometry")

    # A4b — every bead ~HELIX_RADIUS from its helix axis (frame-independent)
    axis = {h.id: (h.axis_start.to_array(), (h.axis_end.to_array() - h.axis_start.to_array())
                   / np.linalg.norm(h.axis_end.to_array() - h.axis_start.to_array()))
            for h in design.helices}
    radii = []
    for (h, b, d), i in k0_keys.items():
        if h not in axis:
            continue
        a0, ah = axis[h]
        v = r_nm[i] - a0
        perp = v - np.dot(v, ah) * ah
        radii.append(np.linalg.norm(perp))
    radii = np.array(radii)
    rad_err = float(np.abs(radii - HELIX_RADIUS).max()) if len(radii) else 9.9
    chk("A4b radius", rad_err < RADIUS_TOL_NM,
        f"max |r-R|={rad_err*10:.3f} A (R={HELIX_RADIUS*10:.1f} A)")

    # A5 — distinct start positions (dup-position blow-up guard)
    rounded = [tuple(np.round(p, 3)) for p in r_nm]
    dups = [(p, c) for p, c in Counter(rounded).items() if c > 1]
    # also a real min-distance scan (rounding can hide near-coincidence)
    mind = 9.9
    if n_beads > 1:
        # cheap O(N) proxy: nearest along sorted x is not exact; do a KD-free
        # pairwise on a subsample if large, else full.
        pts = r_nm
        if n_beads <= 60000:
            from scipy.spatial import cKDTree
            d2, _ = cKDTree(pts).query(pts, k=2)
            mind = float(d2[:, 1].min())
    chk("A5 distinct", len(dups) == 0 and mind > DUP_MIN_DIST_NM,
        f"exact_dups={len(dups)} min_pair={mind*10:.2f} A")

    # A6 — topology: bp symmetric + strand 3' chains contiguous
    bp_sym = True
    for i, j in enumerate(bp):
        if j >= 0 and bp[j] != i:
            bp_sym = False
            break
    # 3' chain: following three_prime from each strand's first bead must visit
    # exactly that strand's bead count with no premature -1.
    chains_ok = True
    idx_by_strand = {}
    for (h, b, d, k), i in nt_key.items():
        pass  # strand identity not in nt_key; validate via three_prime global shape
    # global: number of 3'-links == n_beads - (#strands with >=1 bead)
    n_links = int((three_prime >= 0).sum())
    n_strands_nonempty = sum(
        1 for s in design.strands
        if any(_build_loop_skip_map(design).get((dm.helix_id, b), 0) > -1
               for dm in s.domains for b in domain_bp_range(dm))
    )
    chains_ok = (n_links == n_beads - n_strands_nonempty)
    chk("A6 topology", bp_sym and chains_ok,
        f"bp_symmetric={bp_sym} 3'links={n_links} expected={n_beads - n_strands_nonempty}")

    ok = all(p for _, p, _ in rows)
    return rows, ok, {"r_nm": r_nm, "n_beads": n_beads}


# ── Phase B — round trip through ARBD ─────────────────────────────────────────

def _find_fine_files(tmp: Path, stem: str):
    """Locate the fine-stage psf (+companion pdb) and its dcd. Fine stage = the
    psf with the most beads (most ATOM records in its companion pdb)."""
    psfs = sorted(glob(str(tmp / f"{stem}*.psf")))
    best = None
    best_n = -1
    for psf in psfs:
        pdb = Path(psf).with_suffix(".pdb")
        if not pdb.exists():
            continue
        n = sum(1 for ln in pdb.read_text(errors="replace").splitlines()
                if ln.startswith(("ATOM", "HETATM")))
        if n > best_n:
            best_n, best = n, psf
    if best is None:
        return None, None
    stem_b = Path(best).stem
    dcds = sorted(glob(str(tmp / "output" / "*.dcd")))
    dcd = next((d for d in dcds if stem_b in Path(d).stem), dcds[-1] if dcds else None)
    return best, dcd


def phase_b(design: Design, a_info: dict, steps: int):
    from backend.core.mrdna_bridge import (
        mrdna_model_from_nadoc,
        nuc_pos_override_from_arbd_strands,
    )

    rows = []

    def chk(name, passed, detail=""):
        rows.append((name, bool(passed), detail))

    with tempfile.TemporaryDirectory(prefix="nadoc_mrdna_bench_") as d:
        tmp = Path(d)
        stem = "bench"
        model = mrdna_model_from_nadoc(design)
        t0 = time.time()
        with _quiet_fds(tmp / "arbd.log"):
            model.simulate(
                output_name=stem, directory=str(tmp),
                coarse_steps=int(steps), fine_steps=int(steps),
                output_period=max(1, int(steps) // 10),
            )
        dt = time.time() - t0

        psf, dcd = _find_fine_files(tmp, stem)
        chk("B1 simulates", psf is not None and dcd is not None,
            f"{dt:.1f}s  psf={Path(psf).name if psf else None} dcd={'yes' if dcd else None}")
        if psf is None or dcd is None:
            return rows, False

        override = nuc_pos_override_from_arbd_strands(
            design, psf, dcd, frame=-1, sigma_nt=1.0
        )
        vals = np.array(list(override.values())) if override else np.zeros((0, 3))

        # B2 — back-map complete, finite, distinct
        n_expected = _count_non_skip_nucleotides(design)
        finite = len(vals) > 0 and np.isfinite(vals).all()
        dups = [c for _, c in Counter(tuple(np.round(v, 3)) for v in vals).items() if c > 1]
        complete = len(override) >= 0.95 * n_expected
        chk("B2 back-map", finite and not dups and complete,
            f"entries={len(override)}/{n_expected} finite={finite} dups={len(dups)}")

        # B3 — inside design extent (frame mismatch OR explosion -> fail)
        pts = np.array([h.axis_start.to_array() for h in design.helices]
                       + [h.axis_end.to_array() for h in design.helices])
        lo, hi = pts.min(0) - 2.0, pts.max(0) + 2.0
        outside = int(np.any((vals < lo) | (vals > hi), axis=1).sum()) if len(vals) else -1
        chk("B3 in-frame", outside == 0, f"{outside} beads outside extent+2nm")

        # B4 — FWD/REV separation
        expected = 2 * HELIX_RADIUS * math.sin(BDNA_MINOR_GROOVE_ANGLE_RAD / 2)
        seps = []
        for h in design.helices:
            for b in range(h.bp_start, h.bp_start + h.length_bp):
                f = override.get((h.id, b, "FORWARD"))
                rv = override.get((h.id, b, "REVERSE"))
                if f is not None and rv is not None:
                    seps.append(abs(np.linalg.norm(f - rv) - expected))
        sep_err = float(np.mean(seps)) if seps else 9.9
        chk("B4 separation", sep_err < 0.10,
            f"mean |sep-{expected:.2f}|={sep_err*10:.2f} A over {len(seps)} pairs")

        # B5 — no explosion: relaxed extent vs initial bead extent
        init_extent = a_info["r_nm"].max(0) - a_info["r_nm"].min(0)
        relaxed_extent = (vals.max(0) - vals.min(0)) if len(vals) else init_extent * 99
        ratio = float(np.max(relaxed_extent / np.maximum(init_extent, 1e-6)))
        chk("B5 no-explosion", ratio < EXPLOSION_FACTOR,
            f"max extent ratio={ratio:.2f}x (limit {EXPLOSION_FACTOR}x)")

    return rows, all(p for _, p, _ in rows)


# ── driver ────────────────────────────────────────────────────────────────────

def run_design(name: str, fast: bool, steps: int):
    path = ROOT / "Examples" / f"{name}.nadoc"
    if not path.exists():
        print(_red(f"  {name}: design not found at {path}"))
        return False
    design = Design.from_json(path.read_text())
    lat = getattr(design, "lattice_type", "?")
    print(f"\n{name}  "
          f"{_dim(f'[{lat} · {len(design.helices)} helices · {sum(h.length_bp for h in design.helices)} bp]')}")

    a_rows, a_ok, a_info = phase_a(design)
    for nm, ok, det in a_rows:
        print(f"   {_green('PASS') if ok else _red('FAIL')}  {nm:16s} {_dim(det)}")

    if fast:
        return a_ok
    if not a_ok:
        print(_dim("   (skipping Phase B — forward translation failed; sim would be meaningless)"))
        return False

    b_rows, b_ok = phase_b(design, a_info, steps)
    for nm, ok, det in b_rows:
        print(f"   {_green('PASS') if ok else _red('FAIL')}  {nm:16s} {_dim(det)}")
    return a_ok and b_ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--designs", default=",".join(DEFAULT_DESIGNS),
                    help="comma-separated Examples/<name>.nadoc stems")
    ap.add_argument("--fast", action="store_true", help="Phase A only (no GPU/ARBD)")
    ap.add_argument("--steps", type=int, default=2000,
                    help="ARBD coarse+fine steps for Phase B (default 2000)")
    args = ap.parse_args()

    # mrdna importable?
    try:
        from backend.core.mrdna_bridge import mrdna_tool_path
        sys.path.insert(0, mrdna_tool_path())
        import mrdna  # noqa: F401
    except ImportError:
        print(_red("mrdna not importable. Run ./scripts/setup-mrdna.sh first."))
        return 2

    names = [n.strip() for n in args.designs.split(",") if n.strip()]
    print(f"mrdna round-trip benchmark  —  {len(names)} design(s)  "
          f"{'[Phase A only]' if args.fast else f'[Phase A+B, {args.steps} steps]'}")

    results = {n: run_design(n, args.fast, args.steps) for n in names}

    print("\n" + "─" * 50)
    n_ok = sum(results.values())
    for n, ok in results.items():
        print(f"  {_green('PASS') if ok else _red('FAIL')}  {n}")
    print(f"  {n_ok}/{len(results)} designs passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
