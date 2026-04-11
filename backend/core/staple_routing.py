"""Staple routing optimization using a thermodynamic scoring framework.

This module implements a prototype of the Aksel et al. (PNAS 2024)
thermodynamic routing idea described by the user. It builds candidate
staples from a set of allowed scaffold breakpoints (precursor positions)
and searches for a minimum-total-DeltaG cover of the scaffold where each
staple domain covers scaffold nucleotides exactly once.

Notes
-----
- This is a pragmatic, self-contained implementation focused on clarity
  and correctness of constraints/scoring. Some physical corrections
  (advanced salt corrections, sophisticated initiation terms) are
  simplified and exposed as tunable constants.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache
import math
from typing import List, Tuple, Optional, Dict, Any

import numpy as np

# Physical constants
R_KCAL_PER_MOL_K = 0.0019872041  # kcal / (mol K)
T_STANDARD = 298.15  # K (25 °C)


@dataclass
class StapleCandidate:
    domains: List[Tuple[int, int]]  # list of (start, end) on scaffold (0-based, end exclusive)
    seqs: List[str]                  # scaffold sequences bound (5'->3' along scaffold)
    total_length: int
    dg_hyb: float                    # sum of duplex deltaG (kcal/mol)
    dg_loop: float                   # sum of loop penalties
    dg_init: float                   # initiation penalties
    score: float                     # total ΔG = hyb + loop + init
    strongest_Tm: float             # Tm (°C) of the strongest domain


# --- SantaLucia 1998 nearest-neighbor parameters (kcal/mol, kcal/mol/K)
# Values taken from literature; these are deltaH (kcal/mol) and deltaS (cal/mol/K).
# Note: deltaS units in the table are cal/(mol K) while deltaH is kcal/mol.
NN_DH = {
    'AA': -7.9, 'TT': -7.9,
    'AT': -7.2, 'TA': -7.2,
    'CA': -8.5, 'TG': -8.5,
    'GT': -8.4, 'AC': -8.4,
    'CT': -7.8, 'AG': -7.8,
    'GA': -8.2, 'TC': -8.2,
    'CG': -10.6,'GC': -9.8,
    'GG': -8.0, 'CC': -8.0,
}

NN_DS = {
    'AA': -22.2, 'TT': -22.2,
    'AT': -20.4, 'TA': -21.3,
    'CA': -22.7, 'TG': -22.7,
    'GT': -22.4, 'AC': -22.4,
    'CT': -21.0, 'AG': -21.0,
    'GA': -22.2, 'TC': -22.2,
    'CG': -27.2, 'GC': -24.4,
    'GG': -19.9, 'CC': -19.9,
}

# Terminal corrections (initiation) in kcal/mol and cal/(mol K)
INIT_DH = 0.2  # kcal/mol per domain (empirical small penalty)
INIT_DS = -5.7  # cal/(mol K) per domain


def _complement(seq: str) -> str:
    comp_map = str.maketrans('ATGCatgc', 'TACGtacg')
    return seq.translate(comp_map)


def nn_calc_dh_ds(seq: str) -> Tuple[float, float]:
    """Compute nearest-neighbor ΔH (kcal/mol) and ΔS (cal/mol/K) for a DNA duplex.

    seq is the scaffold strand 5'->3' that the staple binds (we treat the
    staple as the perfect complement). Returns (ΔH, ΔS).
    """
    dh = 0.0
    ds = 0.0
    s = seq.upper()
    for i in range(len(s) - 1):
        pair = s[i:i+2]
        if pair in NN_DH:
            dh += NN_DH[pair]
            ds += NN_DS[pair]
        else:
            # unknown / N: penalize heavily
            dh += -7.0
            ds += -20.0

    # add initiation
    dh += INIT_DH
    ds += INIT_DS
    return dh, ds


def domain_dG(seq: str, T: float = T_STANDARD) -> float:
    """Return ΔG (kcal/mol) of duplex formation for the given domain at temperature T (K)."""
    dh, ds = nn_calc_dh_ds(seq)
    # ds is in cal/(mol K) -> convert to kcal
    dG = dh - (ds / 1000.0) * T
    return dG


def domain_Tm(seq: str, conc: float = 25e-9, salt_eq: float = 0.0125) -> float:
    """Approximate melting temperature (°C) for an oligo duplex using NN params.

    - conc: total strand concentration (M) (default 25 nM)
    - salt_eq: effective monovalent concentration (M). User provided 12.5 mM Mg2+;
      callers may convert Mg2+ to Na+ equivalent externally. Here we treat
      salt_eq as a tunable effective salt parameter.
    """
    dh, ds = nn_calc_dh_ds(seq)
    dh_kcal = dh
    ds_kcal = ds / 1000.0
    # For non-self-complementary duplex, use C/4 (approximate)
    try:
        tm_k = dh_kcal / (ds_kcal + R_KCAL_PER_MOL_K * math.log(conc / 4.0))
    except Exception:
        return 0.0
    tm_c = tm_k - 273.15
    # very rough salt correction (Owczarzy-like approximations are omitted)
    if salt_eq > 0:
        tm_c += 16.6 * math.log10(salt_eq)
    return tm_c


def loop_penalty(loop_len: int, T: float = T_STANDARD, l_ref: int = 1) -> float:
    if loop_len <= 0:
        return 0.0
    return R_KCAL_PER_MOL_K * T * math.log(loop_len / float(l_ref))


# ---------------------------------------------------------------------------
# Vectorised thermodynamic helpers (prefix-sum approach)
# ---------------------------------------------------------------------------

def _build_nn_lookup_tables():
    """Build 256×256 numpy lookup tables for nearest-neighbor dH and dS."""
    dh_table = np.full((256, 256), -7.0, dtype=np.float64)   # penalty default
    ds_table = np.full((256, 256), -20.0, dtype=np.float64)
    for pair, val in NN_DH.items():
        a, b = ord(pair[0]), ord(pair[1])
        dh_table[a, b] = val
    for pair, val in NN_DS.items():
        a, b = ord(pair[0]), ord(pair[1])
        ds_table[a, b] = val
    return dh_table, ds_table


_DH_TABLE, _DS_TABLE = _build_nn_lookup_tables()

# Precompute Tm constants that don't change
_TM_CONC = 25e-9
_TM_SALT = 0.0125
_TM_LOG_CONC_TERM = R_KCAL_PER_MOL_K * math.log(_TM_CONC / 4.0)
_TM_SALT_CORRECTION = 16.6 * math.log10(_TM_SALT) if _TM_SALT > 0 else 0.0


def _build_prefix_sums(scaffold_seq: str):
    """Compute prefix sums of NN dH and dS along the scaffold.

    Returns (prefix_dh, prefix_ds) arrays of length N-1 where:
        dH for interval [a, b) = prefix_dh[b-1] - prefix_dh[a] + INIT_DH
        dS for interval [a, b) = prefix_ds[b-1] - prefix_ds[a] + INIT_DS

    Prefix arrays use index 0 as a sentinel so that:
        dH for [a, b) = prefix_dh[b-1] - prefix_dh[a]  (no off-by-one)
    Actually we'll use a slightly different convention — see implementation.
    """
    seq_int = np.frombuffer(scaffold_seq.upper().encode(), dtype=np.uint8)
    N = len(seq_int)
    if N < 2:
        return np.zeros(1), np.zeros(1)

    left = seq_int[:-1]   # positions 0..N-2
    right = seq_int[1:]   # positions 1..N-1

    # Per-position NN contributions (length N-1)
    pos_dh = _DH_TABLE[left, right]
    pos_ds = _DS_TABLE[left, right]

    # Prefix sums with a leading zero for easy range queries:
    # prefix[0] = 0, prefix[k] = sum of pos[0..k-1]
    # So dH for interval [a, b) = sum of pos[a..b-2] = prefix[b-1] - prefix[a]
    prefix_dh = np.empty(N, dtype=np.float64)
    prefix_ds = np.empty(N, dtype=np.float64)
    prefix_dh[0] = 0.0
    prefix_ds[0] = 0.0
    np.cumsum(pos_dh, out=prefix_dh[1:])
    np.cumsum(pos_ds, out=prefix_ds[1:])

    return prefix_dh, prefix_ds


def _interval_thermo(prefix_dh, prefix_ds, a: int, b: int):
    """Return (dH, dS, dG, Tm) for scaffold interval [a, b) using prefix sums. O(1)."""
    # NN sum over dinucleotides at positions a..b-2
    dh = float(prefix_dh[b - 1] - prefix_dh[a]) + INIT_DH
    ds = float(prefix_ds[b - 1] - prefix_ds[a]) + INIT_DS

    # dG at standard temperature
    dg = dh - (ds / 1000.0) * T_STANDARD

    # Tm
    ds_kcal = ds / 1000.0
    denom = ds_kcal + _TM_LOG_CONC_TERM
    if abs(denom) < 1e-15:
        tm = 0.0
    else:
        tm = (dh / denom) - 273.15 + _TM_SALT_CORRECTION

    return dh, ds, dg, tm


# ---------------------------------------------------------------------------
# Candidate enumeration with binary search + prefix-sum scoring
# ---------------------------------------------------------------------------

def build_candidates_from_breaks(
    scaffold_seq: str,
    breaks: Optional[List[int]] = None,
    max_domains: int = 3,
    min_domain: int = 8,
    max_domain: int = 21,
    min_total: int = 18,
    max_total: int = 60,
) -> List[StapleCandidate]:
    """Enumerate candidate staples using the allowed breakpoints.

    - scaffold_seq: full scaffold sequence (5'->3' traversal order)
    - breaks: list of allowed positions (0..N). If None, every position is allowed.
    Returns list of StapleCandidate objects.
    """
    N = len(scaffold_seq)
    if breaks is None:
        breaks = list(range(0, N + 1))
    breaks = sorted(set(b for b in breaks if 0 <= b <= N))

    # Phase 1: Prefix-sum NN precomputation
    prefix_dh, prefix_ds = _build_prefix_sums(scaffold_seq)

    # Precompute initiation penalty (constant per discontinuity)
    dg_init_per_discont = INIT_DH - (INIT_DS / 1000.0) * T_STANDARD

    # Precompute log for loop penalty
    _rkt = R_KCAL_PER_MOL_K * T_STANDARD

    # Build single-domain intervals (sorted by start, then end)
    B = len(breaks)
    single_intervals: List[Tuple[int, int]] = []
    # For each break position as start, find valid end breaks
    for i in range(B):
        a = breaks[i]
        # Find the first break >= a + min_domain
        j_start = bisect_left(breaks, a + min_domain, i + 1, B)
        # Find the first break > a + max_domain
        j_end = bisect_right(breaks, a + max_domain, j_start, B)
        for j in range(j_start, j_end):
            single_intervals.append((a, breaks[j]))

    # Precompute thermodynamic properties for all single intervals
    n_si = len(single_intervals)
    si_starts = np.empty(n_si, dtype=np.int64)
    si_ends = np.empty(n_si, dtype=np.int64)
    si_lens = np.empty(n_si, dtype=np.int64)
    si_dg = np.empty(n_si, dtype=np.float64)
    si_tm = np.empty(n_si, dtype=np.float64)

    for idx, (a, b) in enumerate(single_intervals):
        si_starts[idx] = a
        si_ends[idx] = b
        si_lens[idx] = b - a
        _, _, dg, tm = _interval_thermo(prefix_dh, prefix_ds, a, b)
        si_dg[idx] = dg
        si_tm[idx] = tm

    # Sorted start positions for binary search during multi-domain enumeration
    si_starts_sorted = si_starts  # already sorted by construction

    candidates: List[StapleCandidate] = []

    def _make_candidate(domain_indices: List[int]) -> Optional[StapleCandidate]:
        """Build and validate a candidate from single-interval indices."""
        domains = [single_intervals[i] for i in domain_indices]
        lens = [si_lens[i] for i in domain_indices]
        total = sum(lens)
        if total < min_total or total > max_total:
            return None

        # Hybridization dG (sum of domain dGs)
        dg_hyb = sum(float(si_dg[i]) for i in domain_indices)
        tm_best = max(float(si_tm[i]) for i in domain_indices)

        # Loop penalties
        dg_loop = 0.0
        heavy_loop_penalty = 0.0
        for k in range(len(domains) - 1):
            loop_len = domains[k + 1][0] - domains[k][1]
            if loop_len > 0:
                lp = _rkt * math.log(loop_len)
                dg_loop += lp
                if loop_len > 50:
                    heavy_loop_penalty += lp

        # Initiation penalty
        n_discont = len(domains) - 1
        dg_init = n_discont * dg_init_per_discont

        score = dg_hyb + dg_loop + dg_init + heavy_loop_penalty

        # Balance penalty
        if len(lens) > 1 and max(lens) / min(lens) > 3.0:
            score += 2.0

        seqs = [scaffold_seq[a:b] for (a, b) in domains]
        return StapleCandidate(
            domains=domains,
            seqs=seqs,
            total_length=int(total),
            dg_hyb=dg_hyb,
            dg_loop=dg_loop,
            dg_init=dg_init,
            score=score,
            strongest_Tm=tm_best,
        )

    # --- 1-domain candidates ---
    for i in range(n_si):
        if si_lens[i] < min_total or si_lens[i] > max_total:
            continue
        c = _make_candidate([i])
        if c is not None:
            candidates.append(c)

    # --- 2-domain candidates (binary search) ---
    if max_domains >= 2:
        for i1 in range(n_si):
            len1 = int(si_lens[i1])
            end1 = int(si_ends[i1])
            remaining_budget = max_total - len1
            if remaining_budget < min_domain:
                continue
            # Find first interval starting after end1
            j_lo = bisect_right(si_starts_sorted, end1, i1 + 1, n_si)
            for i2 in range(j_lo, n_si):
                len2 = int(si_lens[i2])
                if len2 > remaining_budget:
                    # Since intervals at same start are sorted by end,
                    # later intervals with same start will also exceed budget.
                    # But starts increase, so we can't break globally.
                    # Skip this one.
                    continue
                total = len1 + len2
                if total < min_total:
                    continue
                c = _make_candidate([i1, i2])
                if c is not None:
                    candidates.append(c)

    # --- 3-domain candidates (chained binary search + aggressive pruning) ---
    if max_domains >= 3:
        for i1 in range(n_si):
            len1 = int(si_lens[i1])
            end1 = int(si_ends[i1])
            budget_after_1 = max_total - len1
            if budget_after_1 < 2 * min_domain:
                continue
            j2_lo = bisect_right(si_starts_sorted, end1, i1 + 1, n_si)
            for i2 in range(j2_lo, n_si):
                len2 = int(si_lens[i2])
                if len2 > budget_after_1 - min_domain:
                    continue
                end2 = int(si_ends[i2])
                budget_after_2 = budget_after_1 - len2
                j3_lo = bisect_right(si_starts_sorted, end2, i2 + 1, n_si)
                for i3 in range(j3_lo, n_si):
                    len3 = int(si_lens[i3])
                    if len3 > budget_after_2:
                        continue
                    total = len1 + len2 + len3
                    if total < min_total:
                        continue
                    c = _make_candidate([i1, i2, i3])
                    if c is not None:
                        candidates.append(c)

    return candidates


def optimize_staples_for_scaffold(
    scaffold_seq: str,
    breaks: Optional[List[int]] = None,
    max_domains: int = 3,
) -> Dict[str, Any]:
    """Find a minimum-score cover of the scaffold using candidate staples.

    Returns a dictionary with keys:
      - staples: list of dicts with `domains`, `sequence` (staple seq 5'->3'),
        `dg`, `strongest_Tm`, and `violations`.
      - total_score: float
      - violations: list of global violations (if any)

    Notes
    -----
    This uses a simple recursive search with memoization to find a minimum
    total score cover where staples' domains are disjoint and the union of
    domains covers every scaffold position exactly once.
    """
    N = len(scaffold_seq)
    candidates = build_candidates_from_breaks(
        scaffold_seq, breaks, max_domains=max_domains
    )

    # Phase 3: Bitmask-based coverage for O(1) overlap/union/completion checks
    ALL_BITS = (1 << N) - 1

    # Precompute bitmask for each candidate's coverage
    cand_bits: List[int] = []
    for c in candidates:
        bits = 0
        for a, b in c.domains:
            bits |= ((1 << (b - a)) - 1) << a
        cand_bits.append(bits)

    # Filter out candidates that cover positions outside [0, N)
    filtered_idx = [i for i, bits in enumerate(cand_bits) if bits & ~ALL_BITS == 0]
    candidates = [candidates[i] for i in filtered_idx]
    cand_bits = [cand_bits[i] for i in filtered_idx]

    # Build lookup from first-domain start position to candidate indices
    start_map: Dict[int, List[int]] = {}
    for idx, c in enumerate(candidates):
        start = c.domains[0][0]
        start_map.setdefault(start, []).append(idx)

    @lru_cache(maxsize=None)
    def solve(covered: int) -> Tuple[float, Tuple[int, ...]]:
        if covered == ALL_BITS:
            return 0.0, ()

        # Find first uncovered position (lowest unset bit)
        uncovered = covered ^ ALL_BITS
        first = (uncovered & -uncovered).bit_length() - 1

        best_score = float('inf')
        best_choice: Tuple[int, ...] = ()

        for ci in start_map.get(first, []):
            if cand_bits[ci] & covered:
                continue
            new_covered = covered | cand_bits[ci]
            rest_score, rest_choice = solve(new_covered)
            if rest_score == float('inf'):
                continue
            total = candidates[ci].score + rest_score
            if total < best_score:
                best_score = total
                best_choice = (ci,) + rest_choice

        return best_score, best_choice

    total_score, choice = solve(0)

    staples_out = []
    violations = []
    if total_score == float('inf'):
        violations.append('No cover found with given precursor breaks and constraints')
        return {'staples': [], 'total_score': None, 'violations': violations}

    for ci in choice:
        c = candidates[ci]
        # staple sequence is complement of concatenated scaffold domains
        staple_seq = ''.join(_complement(s) for s in c.seqs)
        # per-staple constraint checks
        vio = []
        if any((b - a) < 8 or (b - a) > 21 for (a, b) in c.domains):
            vio.append('domain_length')
        if c.total_length < 18 or c.total_length > 60:
            vio.append('total_length')
        if c.strongest_Tm < 45.0:
            vio.append('Tm')
        if len(c.domains) - 1 > 2:
            vio.append('too_many_discontinuous_segments')

        staples_out.append({
            'domains': c.domains,
            'sequence': staple_seq,
            'dg': c.score,
            'dg_hyb': c.dg_hyb,
            'dg_loop': c.dg_loop,
            'dg_init': c.dg_init,
            'strongest_Tm': c.strongest_Tm,
            'violations': vio,
        })

    return {'staples': staples_out, 'total_score': total_score, 'violations': violations}
