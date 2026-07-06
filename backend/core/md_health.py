"""
MD Health Analysis — C1' base-pair fraction and Watson-Crick heavy-atom proxy.

Reusable library functions ported from the experiment scripts:
  experiments/exp25_full_origami_relaxation/scripts/basepair_monitor.py
  experiments/exp25_full_origami_relaxation/scripts/watson_crick_monitor.py

Call build_c1_pairs() and build_wc_pairs() once on the reference PDB, then
call the metrics functions on each new frame/DCD.  All functions are
import-guarded on MDAnalysis so modules that don't use them can import this
file without MDAnalysis installed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from scipy.spatial import cKDTree


# ── Constants ─────────────────────────────────────────────────────────────────

C1_SEARCH_LO = 8.5    # Å — minimum C1'…C1' distance for a paired candidate
C1_SEARCH_HI = 13.0   # Å — maximum C1'…C1' distance
C1_PAIRED_MAX_DEFAULT = 12.0  # Å — threshold for "paired" call

# Watson-Crick canonical H-bond donor/acceptor heavy-atom pairs
WC_ATOMS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("DA", "DT"): [("N1", "N3"), ("N6", "O4")],
    ("DT", "DA"): [("N3", "N1"), ("O4", "N6")],
    ("DG", "DC"): [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
    ("DC", "DG"): [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
    ("ADE", "THY"): [("N1", "N3"), ("N6", "O4")],
    ("THY", "ADE"): [("N3", "N1"), ("O4", "N6")],
    ("GUA", "CYT"): [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
    ("CYT", "GUA"): [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
    ("A",  "T"):  [("N1", "N3"), ("N6", "O4")],
    ("T",  "A"):  [("N3", "N1"), ("O4", "N6")],
    ("G",  "C"):  [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
    ("C",  "G"):  [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
}


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class C1Pairs:
    """Reference C1'...C1' base pairs identified from a reference structure."""
    pi:  np.ndarray   # indices into the C1' atom selection (shape: n_pairs,)
    pj:  np.ndarray
    d0:  np.ndarray   # reference C1'...C1' distances in Å


@dataclass
class WcPair:
    res_a:        str               # "SEG:DAnnn"
    res_b:        str
    atom_pairs:   list[tuple[int, int]]   # global atom indices for H-bond proxies
    ref_distances: list[float]            # Å in reference structure


@dataclass
class HealthCheckResult:
    passed:                      bool
    # Whether a failure should STOP the run.  A C1' (backbone-pairing) breach or a
    # hard error blocks; a WC-only breach does not — WC ref-relative pairing is a
    # calibration-noisy advisory metric (template-built references inflate many ref
    # distances), so a low WC score warns but lets the run continue.  Defaults True
    # so the early-return error cases below (missing PSF/DCD, no frames) block.
    blocking:                    bool = True
    reason:                      str  = ""
    c1_paired_fraction:          Optional[float] = None
    c1_mean_ang:                 Optional[float] = None
    c1_p90_ang:                  Optional[float] = None
    c1_max_ang:                  Optional[float] = None
    wc_absolute_fraction:        Optional[float] = None
    wc_ref_relative_fraction:    Optional[float] = None
    wc_mean_hbond_ang:           Optional[float] = None
    wc_p90_max_hbond_ang:        Optional[float] = None
    n_c1_pairs:                  int  = 0
    n_wc_pairs:                  int  = 0
    frame:                       Optional[int] = None
    error:                       Optional[str] = None
    wc_per_frame:                list[float] = field(default_factory=list)


# ── C1' pair builder ──────────────────────────────────────────────────────────

def build_c1_pairs(
    psf: Path,
    pdb: Path,
    *,
    exclude_residues: Optional[set[tuple[str, str]]] = None,
) -> C1Pairs:
    """Identify C1'...C1' base pairs from the reference structure.

    All cross-segment candidate pairs within [C1_SEARCH_LO, C1_SEARCH_HI] Å
    are collected, sorted by distance, and then greedily assigned shortest-first.
    This makes intra-duplex pairs (~10 Å) win over inter-helix contacts
    (~12+ Å) regardless of atom-index ordering or PSF segment layout.

    ``exclude_residues`` is a set of ``(chain, resid)`` keys (as produced by
    ``md_protocols.identify_unpaired_residues``) for deliberately single-stranded
    residues — crossover extra bases and other designed ssDNA.  Candidates that
    touch one are skipped so these bases never contribute a (weak, floppy) pair
    that then "fails" during dynamics and depresses the health fraction.
    """
    import MDAnalysis as mda  # noqa: PLC0415

    u = mda.Universe(str(psf), str(pdb))
    c1 = _select_c1(u)
    pos = c1.positions
    segids = c1.atoms.segids
    excl = exclude_residues or set()

    candidates: list[tuple[float, int, int]] = []
    for i, j in cKDTree(pos).query_pairs(C1_SEARCH_HI):
        if segids[i] == segids[j]:
            continue
        if _residue_key(c1[i]) in excl or _residue_key(c1[j]) in excl:
            continue
        d = float(np.linalg.norm(pos[i] - pos[j]))
        if d >= C1_SEARCH_LO:
            candidates.append((d, i, j))
    candidates.sort()

    used = np.zeros(len(pos), dtype=bool)
    pi_list: list[int] = []
    pj_list: list[int] = []
    for _, i, j in candidates:
        if used[i] or used[j]:
            continue
        used[i] = used[j] = True
        pi_list.append(i)
        pj_list.append(j)

    if not pi_list:
        raise RuntimeError("No C1' base pairs found in reference structure.")

    pi_arr = np.asarray(pi_list, dtype=int)
    pj_arr = np.asarray(pj_list, dtype=int)
    d0 = np.linalg.norm(pos[pi_arr] - pos[pj_arr], axis=1)
    return C1Pairs(pi=pi_arr, pj=pj_arr, d0=d0)


def c1_frame_metrics(
    u_or_positions: Any,
    pairs: C1Pairs,
    *,
    paired_max_ang: float = C1_PAIRED_MAX_DEFAULT,
    box: Optional[np.ndarray] = None,
) -> dict:
    """Compute C1' health metrics for one frame.

    Parameters
    ----------
    u_or_positions:
        Either an MDAnalysis Universe (trajectory already seeked to the desired
        frame) or a bare numpy positions array aligned to the C1' atom order.
    pairs:
        C1Pairs from build_c1_pairs().
    paired_max_ang:
        C1'...C1' distance cutoff for calling a pair "paired".
    box:
        PBC box dimensions [bx, by, bz] in Å for minimum-image correction.
        If None, no PBC correction is applied.
    """
    import MDAnalysis as mda  # noqa: PLC0415

    if isinstance(u_or_positions, mda.Universe):
        c1_pos = _select_c1(u_or_positions).positions
        ts_box = u_or_positions.trajectory.ts.dimensions
        if box is None and ts_box is not None and len(ts_box) >= 3:
            box = ts_box[:3]
    else:
        c1_pos = u_or_positions

    i, j = pairs.pi, pairs.pj
    diff = c1_pos[i] - c1_pos[j]
    if box is not None and np.all(np.asarray(box) > 0):
        L = np.asarray(box[:3])
        diff -= L * np.round(diff / L)
    d = np.sqrt((diff * diff).sum(axis=1))
    frac = float((d < paired_max_ang).mean())
    return {
        "n_pairs":          int(len(i)),
        "paired_fraction":  frac,
        "paired_percent":   frac * 100.0,
        "mean_c1_ang":      float(d.mean()),
        "p90_c1_ang":       float(np.percentile(d, 90)),
        "max_c1_ang":       float(d.max()),
    }


def c1_metrics_from_dcd(
    psf: Path,
    dcd: Path,
    pairs: C1Pairs,
    *,
    safe_back: int = 2,
    paired_max_ang: float = C1_PAIRED_MAX_DEFAULT,
) -> dict | None:
    """Return C1' metrics for the latest safe frame in a growing DCD.

    Returns None if the DCD does not yet have enough frames.
    Returns {"error": ...} on read failure.
    """
    import MDAnalysis as mda  # noqa: PLC0415

    if not dcd.exists() or dcd.stat().st_size == 0:
        return None
    try:
        u = mda.Universe(str(psf), str(dcd))
        n = len(u.trajectory)
        if n <= safe_back:
            return None
        frame_idx = n - 1 - safe_back
        u.trajectory[frame_idx]
        m = c1_frame_metrics(u, pairs, paired_max_ang=paired_max_ang)
        m["frame"] = int(frame_idx)
        m["n_frames"] = int(n)
        return m
    except Exception as exc:
        return {"error": str(exc)}


# ── Watson-Crick pair builder ─────────────────────────────────────────────────

def build_wc_pairs(
    psf: Path,
    pdb: Path,
    *,
    lo: float = C1_SEARCH_LO,
    hi: float = C1_SEARCH_HI,
    exclude_residues: Optional[set[tuple[str, str]]] = None,
) -> list[WcPair]:
    """Build WC H-bond proxy pair list from reference structure.

    Only residue pairs that have a WC_ATOMS entry (i.e. known base-type
    complement) are included — mismatches and abasic sites are skipped.

    Candidates are sorted by C1'…C1' distance before greedy assignment so
    intra-duplex pairs win over inter-helix contacts regardless of atom order.
    Non-WC-compatible candidates do not consume atoms, allowing each atom to
    be re-evaluated with the next-shortest candidate.

    ``exclude_residues`` is a set of ``(chain, resid)`` keys (as produced by
    ``md_protocols.identify_unpaired_residues``) for deliberately single-stranded
    residues — crossover extra bases and other designed ssDNA.  These are never
    Watson-Crick base-paired in the design, so an occasional geometric ss→partner
    pairing (e.g. an inserted T that lands near a real A across the gap) is a
    spurious WC pair; excluding them keeps the WC fraction measuring the intended
    duplex.
    """
    import MDAnalysis as mda  # noqa: PLC0415

    u = mda.Universe(str(psf), str(pdb))
    c1 = _select_c1(u)
    pos = c1.positions
    excl = exclude_residues or set()

    candidates: list[tuple[float, int, int]] = []
    for i, j in cKDTree(pos).query_pairs(hi):
        if c1[i].segid == c1[j].segid:
            continue
        if _residue_key(c1[i]) in excl or _residue_key(c1[j]) in excl:
            continue
        d = float(np.linalg.norm(pos[i] - pos[j]))
        if d >= lo:
            candidates.append((d, i, j))
    candidates.sort()

    used = np.zeros(len(pos), dtype=bool)
    pairs: list[WcPair] = []

    for _, i, j in candidates:
        if used[i] or used[j]:
            continue
        res_a = c1[i].residue
        res_b = c1[j].residue
        key = (res_a.resname.strip(), res_b.resname.strip())
        hbonds = WC_ATOMS.get(key, [])
        atom_pairs: list[tuple[int, int]] = []
        ref_distances: list[float] = []
        for name_a, name_b in hbonds:
            ia = _atom_index(res_a, name_a)
            ib = _atom_index(res_b, name_b)
            if ia is not None and ib is not None:
                d_ref = float(np.linalg.norm(u.atoms[ia].position - u.atoms[ib].position))
                atom_pairs.append((ia, ib))
                ref_distances.append(d_ref)
        if atom_pairs:
            used[i] = used[j] = True
            pairs.append(WcPair(
                res_a        = f"{res_a.segid}:{res_a.resname}{res_a.resid}",
                res_b        = f"{res_b.segid}:{res_b.resname}{res_b.resid}",
                atom_pairs   = atom_pairs,
                ref_distances = ref_distances,
            ))

    return pairs


def wc_frame_metrics(
    positions: np.ndarray,
    wc_pairs: list[WcPair],
    *,
    cutoff_ang: float = 3.6,
    ref_delta_ang: float = 0.75,
    box: Optional[np.ndarray] = None,
) -> dict:
    """Compute WC heavy-atom H-bond proxy metrics for one frame."""
    L = np.asarray(box[:3]) if box is not None and np.all(np.asarray(box[:3]) > 0) else None
    pair_ok: list[bool] = []
    ref_ok:  list[bool] = []
    mean_hb: list[float] = []
    max_hb:  list[float] = []

    for pair in wc_pairs:
        dists = []
        for ia, ib in pair.atom_pairs:
            diff = positions[ia] - positions[ib]
            if L is not None:
                diff -= L * np.round(diff / L)
            dists.append(float(np.sqrt((diff * diff).sum())))
        arr = np.asarray(dists)
        ref = np.asarray(pair.ref_distances)
        pair_ok.append(bool(np.all(arr <= cutoff_ang)))
        ref_ok.append(bool(np.all(arr <= ref + ref_delta_ang)))
        mean_hb.append(float(arr.mean()))
        max_hb.append(float(arr.max()))

    def _s(v: list[float]) -> float:
        return float(np.mean(v)) if v else 0.0

    return {
        "n_pairs":                    len(wc_pairs),
        "absolute_paired_fraction":   float(np.mean(pair_ok)) if pair_ok else 0.0,
        "absolute_paired_percent":    float(np.mean(pair_ok) * 100.0) if pair_ok else 0.0,
        "ref_relative_paired_fraction": float(np.mean(ref_ok)) if ref_ok else 0.0,
        "ref_relative_paired_percent":  float(np.mean(ref_ok) * 100.0) if ref_ok else 0.0,
        "mean_hbond_proxy_ang":       _s(mean_hb),
        "p90_max_hbond_proxy_ang":    float(np.percentile(max_hb, 90)) if max_hb else 0.0,
        "max_hbond_proxy_ang":        float(max(max_hb)) if max_hb else 0.0,
    }


def wc_metrics_from_dcd(
    psf: Path,
    pdb: Path,
    dcd: Path,
    wc_pairs: list[WcPair],
    *,
    frame: int = -1,
    cutoff_ang: float = 3.6,
    ref_delta_ang: float = 0.75,
) -> dict:
    """Return WC metrics for a specific frame in a DCD."""
    import MDAnalysis as mda  # noqa: PLC0415

    u = mda.Universe(str(psf), str(pdb), str(dcd))
    u.trajectory[frame]
    box = u.trajectory.ts.dimensions
    L = box[:3] if box is not None and len(box) >= 3 else None
    return wc_frame_metrics(u.atoms.positions, wc_pairs, cutoff_ang=cutoff_ang,
                            ref_delta_ang=ref_delta_ang, box=L)


# ── Combined health check ─────────────────────────────────────────────────────

def run_health_check(
    package_dir: Path,
    segment_name: str,
    name_stem: str,
    *,
    min_c1_paired: float = 0.90,
    min_wc_ref_relative: float = 0.85,
    paired_max_ang: float = C1_PAIRED_MAX_DEFAULT,
    cutoff_ang: float = 3.6,
    ref_delta_ang: float = 0.75,
    safe_back: int = 0,
) -> HealthCheckResult:
    """Run C1' and WC health checks on the last frame of a completed segment.

    package_dir: NAMD working directory containing {name_stem}.psf/.pdb
    segment_name: output name prefix, expects output/{segment_name}.dcd
    """
    psf = package_dir / f"{name_stem}.psf"
    pdb = package_dir / f"{name_stem}.pdb"
    dcd = package_dir / "output" / f"{segment_name}.dcd"

    if not psf.exists() or not pdb.exists():
        return HealthCheckResult(passed=False, error=f"PSF or PDB not found in {package_dir}")
    if not dcd.exists() or dcd.stat().st_size == 0:
        return HealthCheckResult(passed=False, error=f"DCD not found or empty: {dcd}")

    try:
        # Exclude deliberately single-stranded residues (crossover extra bases +
        # other designed ssDNA) so they don't contribute spurious pairs that fail
        # during dynamics.  Empty for fully-duplex designs (no declash marker).
        excl = _unpaired_exclusion_set(psf, pdb)
        c1_pairs = build_c1_pairs(psf, pdb, exclude_residues=excl)
        wc_pairs = build_wc_pairs(psf, pdb, exclude_residues=excl)
    except Exception as exc:
        return HealthCheckResult(passed=False, error=f"Pair build failed: {exc}")

    try:
        c1_m = c1_metrics_from_dcd(psf, dcd, c1_pairs,
                                   safe_back=safe_back, paired_max_ang=paired_max_ang)
        if c1_m is None:
            return HealthCheckResult(passed=False, error="DCD has no frames yet")
        if "error" in c1_m:
            return HealthCheckResult(passed=False, error=f"C1' read error: {c1_m['error']}")
    except Exception as exc:
        return HealthCheckResult(passed=False, error=f"C1' metrics failed: {exc}")

    try:
        wc_m = wc_metrics_from_dcd(psf, pdb, dcd, wc_pairs,
                                   frame=-1, cutoff_ang=cutoff_ang,
                                   ref_delta_ang=ref_delta_ang)
    except Exception as exc:
        return HealthCheckResult(passed=False, error=f"WC metrics failed: {exc}")

    # Per-frame WC across the full DCD (diagnostic — does not affect pass/fail)
    wc_per_frame: list[float] = []
    try:
        import MDAnalysis as mda  # noqa: PLC0415
        u_all = mda.Universe(str(psf), str(pdb), str(dcd))
        for ts in u_all.trajectory:
            box = ts.dimensions
            L = box[:3] if box is not None and np.all(np.asarray(box[:3]) > 0) else None
            m = wc_frame_metrics(u_all.atoms.positions, wc_pairs,
                                 cutoff_ang=cutoff_ang, ref_delta_ang=ref_delta_ang, box=L)
            wc_per_frame.append(round(m["ref_relative_paired_fraction"], 4))
    except Exception:
        pass

    c1_frac = c1_m["paired_fraction"]
    wc_frac = wc_m["ref_relative_paired_fraction"]
    c1_below = c1_frac < min_c1_paired
    wc_below = wc_frac < min_wc_ref_relative
    failed_reasons: list[str] = []

    if c1_below:
        failed_reasons.append(
            f"C1' paired {c1_frac*100:.1f}% < {min_c1_paired*100:.1f}%"
        )
    if wc_below:
        failed_reasons.append(
            f"WC ref-relative {wc_frac*100:.1f}% < {min_wc_ref_relative*100:.1f}%"
        )

    return HealthCheckResult(
        passed                   = len(failed_reasons) == 0,
        # Only a C1' breach blocks; a WC-only breach is an advisory warning.
        blocking                 = c1_below,
        reason                   = "; ".join(failed_reasons),
        c1_paired_fraction       = c1_frac,
        c1_mean_ang              = c1_m["mean_c1_ang"],
        c1_p90_ang               = c1_m["p90_c1_ang"],
        c1_max_ang               = c1_m["max_c1_ang"],
        wc_absolute_fraction     = wc_m["absolute_paired_fraction"],
        wc_ref_relative_fraction = wc_frac,
        wc_mean_hbond_ang        = wc_m["mean_hbond_proxy_ang"],
        wc_p90_max_hbond_ang     = wc_m["p90_max_hbond_proxy_ang"],
        n_c1_pairs               = c1_m["n_pairs"],
        n_wc_pairs               = wc_m["n_pairs"],
        frame                    = c1_m.get("frame"),
        wc_per_frame             = wc_per_frame,
    )


def append_health_jsonl(output_dir: Path, segment_name: str, stage: str,
                        result: HealthCheckResult) -> None:
    """Append a health-check result to output/health.jsonl."""
    record = {
        "wall_time":    time.time(),
        "segment":      segment_name,
        "stage":        stage,
        "passed":       result.passed,
        "blocking":     result.blocking,
        "reason":       result.reason,
        "c1_paired_fraction":        result.c1_paired_fraction,
        "c1_mean_ang":               result.c1_mean_ang,
        "c1_p90_ang":                result.c1_p90_ang,
        "wc_ref_relative_fraction":  result.wc_ref_relative_fraction,
        "wc_mean_hbond_ang":         result.wc_mean_hbond_ang,
        "n_c1_pairs":                result.n_c1_pairs,
        "n_wc_pairs":                result.n_wc_pairs,
        "frame":                     result.frame,
        "error":                     result.error,
        "wc_per_frame":              result.wc_per_frame,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "health.jsonl").open("a") as fh:
        fh.write(json.dumps(record) + "\n")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _select_c1(u: Any) -> Any:
    sel = u.select_atoms("name C1'")
    if not len(sel):
        sel = u.select_atoms("name C1X")
    if not len(sel):
        raise RuntimeError("No C1' atoms found in universe.")
    return sel


def _residue_key(atom: Any) -> tuple[str, str]:
    """(chain, resid) key matching md_protocols.identify_unpaired_residues.

    Chain = last character of the PSF segid (DNAA→A … DNAI→I), resid = str(int).
    """
    return (str(atom.segid)[-1], str(int(atom.resid)))


def _unpaired_exclusion_set(psf: Path, pdb: Path) -> set[tuple[str, str]]:
    """Deliberately single-stranded residues to exclude from health pairs.

    Only computed for declashed / extra-base designs (detected by the
    ``{stem}_build.pdb`` backup the declash rebuild leaves behind); a fully
    duplex design has no such marker, so this returns an empty set and health
    scoring is byte-identical to before.  Reuses the SAME ss detection that the
    declash protocol excludes from the ENM, so the metric judges exactly the
    residues that are actually restrained/expected to pair.
    """
    build_backup = pdb.with_name(f"{pdb.stem}_build.pdb")
    if not build_backup.exists():
        return set()
    try:
        from backend.core.md_protocols import identify_unpaired_residues  # noqa: PLC0415
        return identify_unpaired_residues(psf, pdb)
    except Exception:
        return set()


def _atom_index(residue: Any, name: str) -> int | None:
    for atom in residue.atoms:
        if atom.name.strip() == name:
            return int(atom.index)
    return None
