"""
Rare-sequence overhang generator.

Finds short DNA sequences that are rare in the scaffold + staple corpus,
have acceptable GC content, and avoid hairpin / self-dimer formation.
"""
from __future__ import annotations

import itertools
import random
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPLEMENT = str.maketrans("ACGTacgt", "TGCAtgca")


def reverse_complement(seq: str) -> str:
    return seq.translate(_COMPLEMENT)[::-1]


def _all_kmers(k: int) -> list[str]:
    return ["".join(b) for b in itertools.product("ACGT", repeat=k)]


def _count_occurrences(query: str, text: str) -> int:
    """Count overlapping occurrences of *query* in *text*."""
    count = 0
    start = 0
    qlen = len(query)
    while True:
        pos = text.find(query, start)
        if pos == -1:
            break
        count += 1
        start = pos + 1
    return count


def gc_content(seq: str) -> float:
    s = seq.upper()
    return (s.count("G") + s.count("C")) / len(s) * 100.0


def _has_hairpin(seq: str, max_hairpins: int = 3) -> bool:
    """Return True if the number of hairpin possibilities exceeds *max_hairpins*.

    A hairpin possibility: a window of length >= 4 is the reverse complement
    of another window at least 3 positions away in the same sequence.
    """
    n = len(seq)
    count = 0
    for win_len in range(4, n // 2 + 1):
        for i in range(n - win_len + 1):
            window = seq[i : i + win_len]
            rc_win = reverse_complement(window)
            # Look for rc_win in positions that are >= 3 away from i
            for j in range(n - win_len + 1):
                if abs(i - j) < 3:
                    continue
                if seq[j : j + win_len] == rc_win:
                    count += 1
                    if count > max_hairpins:
                        return True
    return False


def _has_dimer(seq: str, max_dimers: int = 1) -> bool:
    """Return True if self-dimer count exceeds *max_dimers*.

    Self-dimer: a suffix of length k is the reverse complement of a prefix
    of the same length (k in 4..len(seq)-1).
    """
    count = 0
    for k in range(4, len(seq)):
        if seq[-k:] == reverse_complement(seq[:k]):
            count += 1
            if count > max_dimers:
                return True
    return False


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _build_score_map(corpus: list[str], k: int) -> dict[str, int]:
    """Count overlapping k-mer occurrences across all corpus strings."""
    score_map: dict[str, int] = {kmer: 0 for kmer in _all_kmers(k)}
    for text in corpus:
        text_upper = text.upper()
        tlen = len(text_upper)
        if tlen < k:
            continue
        for i in range(tlen - k + 1):
            kmer = text_upper[i : i + k]
            if kmer in score_map:
                score_map[kmer] += 1
    return score_map


def _select_seeds(score_map: dict[str, int]) -> list[str]:
    """Return seeds at <= 1st percentile; relax up to 50th if fewer than 10 found."""
    counts = np.array(list(score_map.values()), dtype=float)
    seeds: list[str] = []
    for pct in range(1, 51):
        threshold = float(np.percentile(counts, pct))
        seeds = [kmer for kmer, cnt in score_map.items() if cnt <= threshold]
        if len(seeds) >= 10:
            break
    return seeds


def _extend_seeds(
    seeds: list[str],
    target_length: int,
    score_map: dict[str, int],
    k: int,
) -> list[str]:
    """Extend each seed to *target_length* using the greedy 5-mer scoring rule."""
    if target_length <= k:
        # Seeds are already at or beyond target length — just truncate/return as-is
        return [s[:target_length] for s in seeds]

    results: list[str] = []
    # Subsample if too many seeds to keep runtime manageable
    working = seeds[:200] if len(seeds) > 200 else list(seeds)

    for seed in working:
        seq = seed
        local_map = dict(score_map)  # per-seed copy so mutations don't cross-contaminate
        while len(seq) < target_length:
            best_append_score = None
            best_append_bases: list[str] = []
            for base in "ACGT":
                kmer = (seq[-(k - 1) :] + base)[-k:]
                s = local_map.get(kmer, 0)
                if best_append_score is None or s < best_append_score:
                    best_append_score = s
                    best_append_bases = [base]
                elif s == best_append_score:
                    best_append_bases.append(base)

            best_prepend_score = None
            best_prepend_bases: list[str] = []
            for base in "ACGT":
                kmer = (base + seq[: k - 1])[:k]
                s = local_map.get(kmer, 0)
                if best_prepend_score is None or s < best_prepend_score:
                    best_prepend_score = s
                    best_prepend_bases = [base]
                elif s == best_prepend_score:
                    best_prepend_bases.append(base)

            if best_append_score <= best_prepend_score:
                chosen_base = random.choice(best_append_bases)
                chosen_kmer = (seq[-(k - 1) :] + chosen_base)[-k:]
                seq = seq + chosen_base
            else:
                chosen_base = random.choice(best_prepend_bases)
                chosen_kmer = (chosen_base + seq[: k - 1])[:k]
                seq = chosen_base + seq

            local_map[chosen_kmer] = local_map.get(chosen_kmer, 0) + 1

        results.append(seq)
    return results


def _filter_gc(seqs: list[str], gc_min: float, gc_max: float) -> list[str]:
    return [s for s in seqs if gc_min <= gc_content(s) <= gc_max]


def _filter_structure(seqs: list[str]) -> list[str]:
    return [s for s in seqs if not _has_hairpin(s) and not _has_dimer(s)]


def _filter_corpus_score(seqs: list[str], score_map: dict[str, int], k: int) -> list[str]:
    """Keep sequences at or below the 45th percentile of summed k-mer scores."""
    if len(seqs) < 2:
        return seqs
    totals = []
    for seq in seqs:
        total = sum(score_map.get(seq[j : j + k], 0) for j in range(len(seq) - k + 1))
        totals.append(total)
    threshold = float(np.percentile(totals, 45))
    return [s for s, t in zip(seqs, totals) if t <= threshold]


def _random_fallback(length: int) -> str:
    return "".join(random.choice("ACGT") for _ in range(length))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_overhang_sequences(
    scaffold_seq: str,
    staple_seqs: list[str],
    length: int,
    count: int = 1,
    gc_min: float = 35.0,
    gc_max: float = 75.0,
    staple_weight: int = 5,
) -> list[str]:
    """Generate *count* unique overhang sequences of *length* bases.

    Uses a 5-mer (or k-mer for length < 5) scoring algorithm to find
    sequences that are rare in the scaffold + staple corpus, pass GC
    content constraints, and avoid hairpins / self-dimers.

    Falls back to random sequences if the algorithm cannot find enough
    candidates within the maximum iteration budget.

    Parameters
    ----------
    scaffold_seq:
        Full scaffold sequence (may be empty string if not yet assigned).
    staple_seqs:
        List of assembled staple strand sequences.
    length:
        Target overhang length in bases.
    count:
        Number of unique overhangs to generate.
    gc_min:
        Minimum GC content percentage (inclusive). Default 35.
    gc_max:
        Maximum GC content percentage (inclusive). Default 75.
    staple_weight:
        Each staple sequence is repeated this many times in the corpus to
        increase its penalty relative to the scaffold. Default 5.
    """
    if length <= 0:
        return [""] * count

    k = min(length, 5)

    results: list[str] = []
    extra_seqs: list[str] = []  # grows as we collect overhangs (diversity)

    max_outer = 50

    for _outer in range(max_outer):
        if len(results) >= count:
            break

        # Build corpus for this iteration
        corpus: list[str] = []
        if scaffold_seq:
            corpus.append(scaffold_seq.upper())
        for s in staple_seqs:
            if s:
                for _ in range(staple_weight):
                    corpus.append(s.upper())
        for s in extra_seqs:
            corpus.append(s.upper())

        score_map = _build_score_map(corpus, k)
        seeds = _select_seeds(score_map)

        candidates = _extend_seeds(seeds, length, score_map, k)
        candidates = list(set(candidates))  # deduplicate
        candidates = _filter_gc(candidates, gc_min, gc_max)
        candidates = _filter_structure(candidates)
        candidates = _filter_corpus_score(candidates, score_map, k)

        # Shuffle so we don't always pick the lexicographically smallest
        random.shuffle(candidates)

        for seq in candidates:
            if seq not in results:
                results.append(seq)
                # Add to extra corpus for diversity on subsequent iterations
                rc = reverse_complement(seq)
                extra_seqs.append(seq * 10)
                extra_seqs.append(rc * 10)
                if len(results) >= count:
                    break

    # Fill any remaining slots with random fallbacks
    while len(results) < count:
        fb = _random_fallback(length)
        if fb not in results:
            results.append(fb)

    return results[:count]
