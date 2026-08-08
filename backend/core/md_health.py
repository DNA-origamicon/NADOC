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
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

C1_SEARCH_LO = 8.5  # Å — minimum C1'…C1' distance for a paired candidate
C1_SEARCH_HI = 13.0  # Å — maximum C1'…C1' distance
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
    ("A", "T"): [("N1", "N3"), ("N6", "O4")],
    ("T", "A"): [("N3", "N1"), ("O4", "N6")],
    ("G", "C"): [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
    ("C", "G"): [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
}


# ── Data types ─────────────────────────────────────────────────────────────────


@dataclass
class C1Pairs:
    """Reference C1'...C1' base pairs identified from a reference structure."""

    pi: np.ndarray  # indices into the C1' atom selection (shape: n_pairs,)
    pj: np.ndarray
    d0: np.ndarray  # reference C1'...C1' distances in Å


@dataclass
class WcPair:
    res_a: str  # "SEG:DAnnn"
    res_b: str
    atom_pairs: list[tuple[int, int]]  # global atom indices for H-bond proxies
    ref_distances: list[float]  # Å in reference structure
    #: The bridging hydrogen of the CENTRAL Watson-Crick bond (guanine H1 or thymine
    #: H3), when the topology carries hydrogens.  Only the tutorial's broken-base-pair
    #: criterion uses it — it needs the N1-H...N3 angle, not just the N...N distance.
    #: None on a heavy-atom package, where that criterion degrades to distance only.
    h_index: Optional[int] = None


@dataclass
class HealthCheckResult:
    passed: bool
    # Whether a failure should STOP the run.  A C1' (backbone-pairing) breach or a
    # hard error blocks; a WC-only breach does not — WC ref-relative pairing is a
    # calibration-noisy advisory metric (template-built references inflate many ref
    # distances), so a low WC score warns but lets the run continue.  Defaults True
    # so the early-return error cases below (missing PSF/DCD, no frames) block.
    blocking: bool = True
    reason: str = ""
    c1_paired_fraction: Optional[float] = None
    c1_mean_ang: Optional[float] = None
    c1_p90_ang: Optional[float] = None
    c1_max_ang: Optional[float] = None
    wc_absolute_fraction: Optional[float] = None
    wc_ref_relative_fraction: Optional[float] = None
    wc_mean_hbond_ang: Optional[float] = None
    wc_p90_max_hbond_ang: Optional[float] = None
    n_c1_pairs: int = 0
    n_wc_pairs: int = 0
    frame: Optional[int] = None
    error: Optional[str] = None
    wc_per_frame: list[float] = field(default_factory=list)
    # ── The published equilibration criteria (Methods Mol Biol 1811 §3.4) ──────
    #: Broken base pairs by the TUTORIAL's own definition (countBrokenBps.tcl): the
    #: central WC hydrogen bond within 3.0 Å AND close to linear.  Reported alongside
    #: the ref-relative fraction above, which stays the gate — this one is the number
    #: that is comparable to a published figure.
    broken_bp_count: Optional[int] = None
    broken_bp_per_frame: list[int] = field(default_factory=list)
    #: Net charge (e) within CHARGE_SHELL_NM of the DNA — their ion-atmosphere
    #: convergence check, and the direct instrument for whether the Mg(H₂O)₆ cloud
    #: has actually formed.
    charge_within_shell_e: Optional[float] = None
    charge_per_frame: list[float] = field(default_factory=list)
    n_shell_ions: Optional[int] = None
    #: True once the per-frame diagnostics loop has actually run, so a caller can tell
    #: "measured, and there was nothing there" from "never measured".
    per_frame_ran: bool = False
    #: Why the per-frame diagnostics produced nothing, when they failed.  Kept separate
    #: from ``reason`` on purpose: ``reason`` is the pass/fail explanation shown in the
    #: WC trend tooltip and the production-checkpoint warning, and must not be polluted
    #: with a diagnostics-only failure that does not affect the verdict.
    diagnostics_error: Optional[str] = None
    #: The DCD exists but has too few frames yet — a normal early-in-segment state, NOT
    #: a failure.  The UI keeps such a tile "computing" instead of painting it failed.
    not_ready: bool = False


# ── The tutorial's own equilibration criteria (Methods Mol Biol 1811 §3.4) ────
# NADOC measured base pairing its own way (heavy-atom donor/acceptor within 3.6 Å, plus a
# reference-relative band) and did not measure the ion atmosphere at all.  The
# ref-relative fraction remains the GATE — it is the better signal for catching a run
# going wrong — but neither number was comparable to anything published, and the missing
# one is precisely the diagnostic for whether the counterion cloud has converged.

#: countBrokenBps.tcl: "a base pair is considered intact if the H1 or N1 atom of a purine
#: is within 3 Å of the N3 or H3 atom of a pyrimidine".
BROKEN_BP_DIST_ANG = 3.0
#: The tutorial ALSO requires the N1-H1...N3 angle to exceed 140 degrees.  Not applied:
#: at a 3.0 Å heavy-atom cut the donor and acceptor are already essentially in contact,
#: and the geometries the angle term exists to reject (sheared, stacked) do not survive
#: that cut in practice.  Recorded here so the simplification is visible rather than
#: silently absent, and so it can be added if a run ever shows it mattering.
BROKEN_BP_ANGLE_DEG = 140.0  # noqa: F841 — documented, deliberately not applied
#: measureCharge.sh: "the total charge of all atoms residing within 2 nm of the DNA".
CHARGE_SHELL_NM = 2.0
#: Atoms the shell tree is built from.  The backbone phosphate + sugar carry the charge
#: divalent counterions condense on, and at a 2 nm cutoff the extra resolution of every
#: heavy atom buys nothing while costing ~16x the tree.
CHARGE_TREE_ATOMS = ("P", "C1'")


def wc_hbond_atoms(u) -> tuple[np.ndarray, np.ndarray]:
    """(purine-N1 indices, pyrimidine-N3 indices) — the central WC donor/acceptor set."""
    don = u.select_atoms("(resname ADE GUA DA DG A G) and name N1")
    acc = u.select_atoms("(resname THY CYT DT DC T C) and name N3")
    return don.ix, acc.ix


def count_intact_base_pairs(
    positions: np.ndarray,
    don_idx: np.ndarray,
    acc_idx: np.ndarray,
    *,
    dist_ang: float = BROKEN_BP_DIST_ANG,
    box: Optional[np.ndarray] = None,
) -> int:
    """Intact Watson-Crick pairs by the tutorial's GEOMETRIC test (pure).

    ``countBrokenBps.tcl`` does not consult a partner list: it counts, per frame, how
    many purine-N1 / pyrimidine-N3 contacts are within 3 Å, and subtracts that from the
    number of base pairs in the idealised structure.  This does the same, and that is
    deliberate — an earlier version of this function took its partners from
    :func:`build_wc_pairs`, which assigns them greedily by shortest C1'...C1' distance
    and therefore prefers cross-strand NEIGHBOURS (8.7-9.6 Å) over true partners
    (~10.4 Å).  Measured on an idealised 2hb build: those assigned partners sat 5-8.6 Å
    apart at the WC edge while the correct partner was 2.5-3.5 Å away, so the criterion
    reported 34 of 39 pairs broken on a perfectly healthy structure.

    Matching is greedy nearest-first and one-to-one, so a donor flanked by two acceptors
    cannot be double-counted.
    """
    if don_idx.size == 0 or acc_idx.size == 0:
        return 0
    L = (
        np.asarray(box[:3])
        if box is not None and np.all(np.asarray(box[:3]) > 0)
        else None
    )
    don, acc = positions[don_idx], positions[acc_idx]
    if L is not None:
        don, acc = np.mod(don, L), np.mod(acc, L)
        tree = cKDTree(acc, boxsize=L)
    else:
        tree = cKDTree(acc)
    # All candidate contacts, nearest first, then a one-to-one greedy assignment.
    pairs = tree.query_ball_point(don, r=dist_ang, workers=-1)
    cand = []
    for di, hits in enumerate(pairs):
        for ai in hits:
            diff = don[di] - acc[ai]
            if L is not None:
                diff -= L * np.round(diff / L)
            cand.append((float(np.sqrt((diff * diff).sum())), di, ai))
    cand.sort()
    used_d, used_a, intact = set(), set(), 0
    for _d, di, ai in cand:
        if di in used_d or ai in used_a:
            continue
        used_d.add(di)
        used_a.add(ai)
        intact += 1
    return intact


def count_broken_base_pairs(
    positions: np.ndarray,
    don_idx: np.ndarray,
    acc_idx: np.ndarray,
    n_expected: int,
    *,
    dist_ang: float = BROKEN_BP_DIST_ANG,
    box: Optional[np.ndarray] = None,
) -> int:
    """``n_expected`` minus the intact count, floored at zero — the tutorial's number.

    ``n_expected`` is the intact count measured on the REFERENCE structure, which is what
    "the number of base pairs in the idealized structure" means operationally.  Taking it
    from the reference rather than from topology also makes the metric self-calibrating:
    a build whose geometry the criterion cannot see starts at zero broken, not at N.
    """
    intact = count_intact_base_pairs(
        positions, don_idx, acc_idx, dist_ang=dist_ang, box=box
    )
    return max(0, int(n_expected) - intact)


def charge_within_shell(
    positions: np.ndarray,
    charges: np.ndarray,
    dna_idx: np.ndarray,
    ion_idx: np.ndarray,
    *,
    shell_nm: float = CHARGE_SHELL_NM,
    box: Optional[np.ndarray] = None,
) -> tuple[float, int]:
    """(net charge in e, ion-atom count) within ``shell_nm`` of the DNA (pure).

    Water is EXCLUDED by construction — TIP3P is neutral per molecule, so counting it by
    molecule contributes exactly zero while costing a query over ~10⁶ atoms instead of
    ~10⁵.  The returned charge is therefore the DNA's own charge plus whatever ionic
    atmosphere has gathered, which is what the tutorial's trace plots.
    """
    if ion_idx.size == 0 or dna_idx.size == 0:
        return 0.0, 0
    shell_ang = shell_nm * 10.0
    ion_xyz = positions[ion_idx]
    dna_xyz = positions[dna_idx]
    L = (
        np.asarray(box[:3])
        if box is not None and np.all(np.asarray(box[:3]) > 0)
        else None
    )
    if L is not None:
        # cKDTree's periodic mode needs every coordinate inside [0, L); with wrapAll off
        # (which is what the relax ladder runs) they are not.
        ion_xyz = np.mod(ion_xyz, L)
        dna_xyz = np.mod(dna_xyz, L)
        tree = cKDTree(dna_xyz, boxsize=L)
    else:
        tree = cKDTree(dna_xyz)
    dist, _ = tree.query(ion_xyz, k=1, distance_upper_bound=shell_ang, workers=-1)
    inside = np.isfinite(dist)
    q_ions = float(charges[ion_idx][inside].sum())
    q_dna = float(charges[dna_idx].sum())
    return q_dna + q_ions, int(inside.sum())


def _shell_selections(u) -> tuple[np.ndarray, np.ndarray]:
    """(dna_tree_atom_indices, ion_atom_indices) for the charge shell."""
    dna_sel = " or ".join(f"name {n}" for n in CHARGE_TREE_ATOMS)
    dna = u.select_atoms(f"nucleic and ({dna_sel})")
    if not len(dna):
        dna = u.select_atoms(dna_sel)
    ions = u.select_atoms("resname SOD CLA MG MGH POT NA CL")
    return dna.ix, ions.ix


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
        "n_pairs": int(len(i)),
        "paired_fraction": frac,
        "paired_percent": frac * 100.0,
        "mean_c1_ang": float(d.mean()),
        "p90_c1_ang": float(np.percentile(d, 90)),
        "max_c1_ang": float(d.max()),
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
                d_ref = float(
                    np.linalg.norm(u.atoms[ia].position - u.atoms[ib].position)
                )
                atom_pairs.append((ia, ib))
                ref_distances.append(d_ref)
        if atom_pairs:
            used[i] = used[j] = True
            pairs.append(
                WcPair(
                    res_a=f"{res_a.segid}:{res_a.resname}{res_a.resid}",
                    res_b=f"{res_b.segid}:{res_b.resname}{res_b.resid}",
                    atom_pairs=atom_pairs,
                    ref_distances=ref_distances,
                    h_index=_central_hbond_hydrogen(res_a, res_b),
                )
            )

    return pairs


#: Which residue donates the CENTRAL Watson-Crick hydrogen, and the H's name.  Guanine
#: donates N1-H1 to cytosine N3; thymine donates N3-H3 to adenine N1.  Adenine's N1 and
#: cytosine's N3 are ACCEPTORS and carry no hydrogen, so picking "whichever of H1/H3
#: exists" would silently measure the wrong angle.
_WC_DONOR_H = {
    "DG": "H1",
    "GUA": "H1",
    "G": "H1",
    "DT": "H3",
    "THY": "H3",
    "T": "H3",
}


def _central_hbond_hydrogen(res_a, res_b) -> Optional[int]:
    """Global atom index of the bridging H of the central WC bond, or None."""
    for res in (res_a, res_b):
        name = _WC_DONOR_H.get(res.resname.strip())
        if name is not None:
            return _atom_index(res, name)
    return None


def wc_frame_metrics(
    positions: np.ndarray,
    wc_pairs: list[WcPair],
    *,
    cutoff_ang: float = 3.6,
    ref_delta_ang: float = 0.75,
    box: Optional[np.ndarray] = None,
) -> dict:
    """Compute WC heavy-atom H-bond proxy metrics for one frame."""
    L = (
        np.asarray(box[:3])
        if box is not None and np.all(np.asarray(box[:3]) > 0)
        else None
    )
    pair_ok: list[bool] = []
    ref_ok: list[bool] = []
    mean_hb: list[float] = []
    max_hb: list[float] = []

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
        "n_pairs": len(wc_pairs),
        "absolute_paired_fraction": float(np.mean(pair_ok)) if pair_ok else 0.0,
        "absolute_paired_percent": float(np.mean(pair_ok) * 100.0) if pair_ok else 0.0,
        "ref_relative_paired_fraction": float(np.mean(ref_ok)) if ref_ok else 0.0,
        "ref_relative_paired_percent": float(np.mean(ref_ok) * 100.0)
        if ref_ok
        else 0.0,
        "mean_hbond_proxy_ang": _s(mean_hb),
        "p90_max_hbond_proxy_ang": float(np.percentile(max_hb, 90)) if max_hb else 0.0,
        "max_hbond_proxy_ang": float(max(max_hb)) if max_hb else 0.0,
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
    return wc_frame_metrics(
        u.atoms.positions,
        wc_pairs,
        cutoff_ang=cutoff_ang,
        ref_delta_ang=ref_delta_ang,
        box=L,
    )


# ── Combined health check ─────────────────────────────────────────────────────


def _latest_segment_dcd(output_dir: Path, segment_name: str) -> Path:
    """Newest trajectory for a segment: ``<seg>.dcd`` or the highest ``<seg>.contN.dcd``.

    A segment resumed from its checkpoint (cell-shrink auto-resume, instability rescue)
    writes to ``<seg>.cont1.dcd``, ``cont2``… — so a probe hard-coded to ``<seg>.dcd``
    kept sampling the frozen pre-crash trajectory for the rest of the run.
    """
    base = output_dir / f"{segment_name}.dcd"
    conts = sorted(
        output_dir.glob(f"{segment_name}.cont*.dcd"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
    )
    return conts[-1] if conts else base


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
    per_frame: bool = True,
) -> HealthCheckResult:
    """Run C1' and WC health checks on the last frame of a completed segment.

    package_dir: NAMD working directory containing {name_stem}.psf/.pdb
    segment_name: output name prefix, expects output/{segment_name}.dcd

    ``per_frame`` walks the WHOLE trajectory to build the per-frame series
    (``wc_per_frame`` feeds the early-stop accelerator and the Tier-A remote
    evaluator).  **The default must stay True** — ``remote_health_eval`` runs a staged
    copy of this module on the compute node and exits "no WC" on an empty series,
    which would make every Tier-A stage hold.  An in-flight probe, which discards the
    series anyway, passes ``per_frame=False`` and gets the two scalars from a single
    frame: O(1) instead of O(n_frames), which matters because the probe runs inline in
    the disk guard's poll loop and a 500 ns run reaches tens of thousands of frames.
    """
    psf = package_dir / f"{name_stem}.psf"
    pdb = package_dir / f"{name_stem}.pdb"
    dcd = _latest_segment_dcd(package_dir / "output", segment_name)

    if not psf.exists() or not pdb.exists():
        return HealthCheckResult(
            passed=False, error=f"PSF or PDB not found in {package_dir}"
        )
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
        c1_m = c1_metrics_from_dcd(
            psf, dcd, c1_pairs, safe_back=safe_back, paired_max_ang=paired_max_ang
        )
        if c1_m is None:
            # Normal early-in-segment state, not a failure: NAMD has not written
            # safe_back+1 frames yet.  Flagged so the UI keeps the tile "computing"
            # rather than painting it failed at the start of every run.
            return HealthCheckResult(
                passed=False, not_ready=True, error="DCD has no frames yet"
            )
        if "error" in c1_m:
            return HealthCheckResult(
                passed=False, error=f"C1' read error: {c1_m['error']}"
            )
    except Exception as exc:
        return HealthCheckResult(passed=False, error=f"C1' metrics failed: {exc}")

    try:
        wc_m = wc_metrics_from_dcd(
            psf,
            pdb,
            dcd,
            wc_pairs,
            frame=-1,
            cutoff_ang=cutoff_ang,
            ref_delta_ang=ref_delta_ang,
        )
    except Exception as exc:
        return HealthCheckResult(passed=False, error=f"WC metrics failed: {exc}")

    # Per-frame diagnostics across the full DCD (none of these affect pass/fail).
    # The tutorial's own two trace criteria ride this loop rather than opening the
    # trajectory again: broken base pairs by ITS definition, and the net charge within
    # 2 nm of the DNA (its ion-atmosphere convergence check).  The charge query is over
    # IONS only — TIP3P is neutral per molecule, so counting water by molecule
    # contributes exactly zero while costing a query over ~10x more atoms.
    wc_per_frame: list[float] = []
    broken_per_frame: list[int] = []
    charge_per_frame: list[float] = []
    n_shell_ions: Optional[int] = None
    per_frame_ran = False
    diagnostics_error: Optional[str] = None
    try:
        import MDAnalysis as mda  # noqa: PLC0415

        # NOTE the topology-only Universe for the DCD.  Passing the PDB as a second
        # coordinate file (as this used to) builds a ChainReader whose frame 0 is the
        # reference structure, not a trajectory frame — which silently shifted
        # wc_per_frame (read by the early-stop accelerator) by one and made the [-1]
        # scalars below describe a different instant than c1_paired_fraction.
        u_all = mda.Universe(str(psf), str(dcd))
        try:
            dna_idx, ion_idx = _shell_selections(u_all)
            charges = u_all.atoms.charges
        except Exception as exc:  # noqa: BLE001 — a PSF without charges, say
            dna_idx = ion_idx = np.empty(0, dtype=int)
            charges = None
            diagnostics_error = f"shell selection failed: {exc}"
        # The tutorial's broken-bp count is (idealised intact) − (this frame's intact),
        # so the reference frame sets the baseline.
        don_idx, acc_idx = wc_hbond_atoms(u_all)
        u_ref = mda.Universe(str(psf), str(pdb))
        n_expected = count_intact_base_pairs(u_ref.atoms.positions, don_idx, acc_idx)

        n_frames = len(u_all.trajectory)
        # Honour safe_back here too: NAMD may be mid-write at the DCD tail while a live
        # probe reads it, and a torn frame used to take all three series down with it.
        last = n_frames - safe_back
        frames = (
            range(max(0, last - 1), max(0, last))
            if not per_frame
            else range(max(0, last))
        )
        for i in frames:
            try:
                ts = u_all.trajectory[i]
                box = ts.dimensions
                L = (
                    box[:3]
                    if box is not None and np.all(np.asarray(box[:3]) > 0)
                    else None
                )
                pos = u_all.atoms.positions
                m = wc_frame_metrics(
                    pos,
                    wc_pairs,
                    cutoff_ang=cutoff_ang,
                    ref_delta_ang=ref_delta_ang,
                    box=L,
                )
                wc_per_frame.append(round(m["ref_relative_paired_fraction"], 4))
                broken_per_frame.append(
                    count_broken_base_pairs(pos, don_idx, acc_idx, n_expected, box=L)
                )
                if charges is not None and ion_idx.size:
                    q, n_in = charge_within_shell(pos, charges, dna_idx, ion_idx, box=L)
                    charge_per_frame.append(round(q, 3))
                    n_shell_ions = n_in
            except Exception as exc:  # noqa: BLE001, PERF203 — one torn frame, not the run
                if diagnostics_error is None:
                    diagnostics_error = f"frame {i}: {exc}"
                continue
        per_frame_ran = True
    except Exception as exc:  # noqa: BLE001
        # Diagnostics-only: never changes the pass/fail verdict.  But it must leave a
        # trace — silently emptying these arrays is what made "Broken bp"/"Shell charge"
        # blank with no way to tell "not measured" from "measured as nothing".
        diagnostics_error = f"per-frame diagnostics failed: {exc}"
        logger.exception("run_health_check: per-frame diagnostics failed for %s", dcd)

    c1_frac = c1_m["paired_fraction"]
    wc_frac = wc_m["ref_relative_paired_fraction"]
    c1_below = c1_frac < min_c1_paired
    wc_below = wc_frac < min_wc_ref_relative
    failed_reasons: list[str] = []

    if c1_below:
        failed_reasons.append(
            f"C1' paired {c1_frac * 100:.1f}% < {min_c1_paired * 100:.1f}%"
        )
    if wc_below:
        failed_reasons.append(
            f"WC ref-relative {wc_frac * 100:.1f}% < {min_wc_ref_relative * 100:.1f}%"
        )

    return HealthCheckResult(
        passed=len(failed_reasons) == 0,
        # Only a C1' breach blocks; a WC-only breach is an advisory warning.
        blocking=c1_below,
        reason="; ".join(failed_reasons),
        c1_paired_fraction=c1_frac,
        c1_mean_ang=c1_m["mean_c1_ang"],
        c1_p90_ang=c1_m["p90_c1_ang"],
        c1_max_ang=c1_m["max_c1_ang"],
        wc_absolute_fraction=wc_m["absolute_paired_fraction"],
        wc_ref_relative_fraction=wc_frac,
        wc_mean_hbond_ang=wc_m["mean_hbond_proxy_ang"],
        wc_p90_max_hbond_ang=wc_m["p90_max_hbond_proxy_ang"],
        n_c1_pairs=c1_m["n_pairs"],
        n_wc_pairs=wc_m["n_pairs"],
        frame=c1_m.get("frame"),
        wc_per_frame=wc_per_frame,
        broken_bp_count=broken_per_frame[-1] if broken_per_frame else None,
        broken_bp_per_frame=broken_per_frame,
        charge_within_shell_e=charge_per_frame[-1] if charge_per_frame else None,
        charge_per_frame=charge_per_frame,
        n_shell_ions=n_shell_ions,
        per_frame_ran=per_frame_ran,
        diagnostics_error=diagnostics_error,
    )


def append_health_jsonl(
    output_dir: Path, segment_name: str, stage: str, result: HealthCheckResult
) -> None:
    """Append a health-check result to output/health.jsonl."""
    record = {
        "wall_time": time.time(),
        "segment": segment_name,
        "stage": stage,
        "passed": result.passed,
        "blocking": result.blocking,
        "reason": result.reason,
        "c1_paired_fraction": result.c1_paired_fraction,
        "c1_mean_ang": result.c1_mean_ang,
        "c1_p90_ang": result.c1_p90_ang,
        "wc_ref_relative_fraction": result.wc_ref_relative_fraction,
        "wc_mean_hbond_ang": result.wc_mean_hbond_ang,
        "n_c1_pairs": result.n_c1_pairs,
        "n_wc_pairs": result.n_wc_pairs,
        "frame": result.frame,
        "error": result.error,
        "wc_per_frame": result.wc_per_frame,
        # The tutorial's §3.4 traces.
        "broken_bp_count": result.broken_bp_count,
        "broken_bp_per_frame": result.broken_bp_per_frame,
        "charge_within_shell_e": result.charge_within_shell_e,
        "charge_per_frame": result.charge_per_frame,
        "n_shell_ions": result.n_shell_ions,
        # Why the two traces above are absent, when they are.
        "per_frame_ran": result.per_frame_ran,
        "diagnostics_error": result.diagnostics_error,
        "not_ready": result.not_ready,
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
