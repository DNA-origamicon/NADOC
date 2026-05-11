"""
Thermodynamics — short-oligo Tm (SantaLucia 1998 nearest-neighbour model).

Pure functions; no design-state dependency. Used by the sub-domain annotation
pipeline to populate ``SubDomain.tm_celsius`` / ``gc_percent``. Hairpin / dimer
checks live in :mod:`backend.core.overhang_generator`.

References
----------
- SantaLucia (1998), *Proc. Natl. Acad. Sci.*, 95(4):1460-1465 — nearest-neighbour
  ΔH°/ΔS° parameters and the salt correction formula used below.

Notes
-----
- The 10 NN pairs cover all 16 dinucleotides via reverse-complement equivalence
  (e.g. 5'-CG-3'/3'-GC-5' is one entry).  ``_nn_lookup`` rotates the input
  dinucleotide as needed.
- Initiation terms differ depending on whether the terminal bp is A/T vs G/C.
- Non-ACGT bases (N or ambiguous) → returns ``None``: Tm is undefined when the
  sequence isn't fully specified.
"""

from __future__ import annotations

import math
from typing import Optional


# ── SantaLucia 1998 NN table (ΔH in kcal/mol, ΔS in cal/mol·K) ──────────────
#
# Keyed by the 5'→3' dinucleotide of one strand. The two-letter key uniquely
# identifies the NN pair because the other strand is its Watson-Crick
# complement read 3'→5'. Table 1 of SantaLucia 1998.
_NN_TABLE: dict[str, tuple[float, float]] = {
    "AA": (-7.9, -22.2),
    "AT": (-7.2, -20.4),
    "TA": (-7.2, -21.3),
    "CA": (-8.5, -22.7),
    "GT": (-8.4, -22.4),
    "CT": (-7.8, -21.0),
    "GA": (-8.2, -22.2),
    "CG": (-10.6, -27.2),
    "GC": (-9.8, -24.4),
    "GG": (-8.0, -19.9),
}

# Reverse-complement table so any of the 16 dinucleotides resolves to one of
# the 10 canonical NN keys above. e.g. "TT" is the reverse-complement of "AA"
# and shares its ΔH/ΔS.
_COMPLEMENT = str.maketrans("ACGT", "TGCA")


def _nn_lookup(dinuc: str) -> Optional[tuple[float, float]]:
    """Return (ΔH, ΔS) for *dinuc*, or None if any base is non-ACGT."""
    dinuc = dinuc.upper()
    if len(dinuc) != 2 or any(b not in "ACGT" for b in dinuc):
        return None
    if dinuc in _NN_TABLE:
        return _NN_TABLE[dinuc]
    # Try reverse complement: e.g. "TT" → "AA" → in table.
    rc = dinuc.translate(_COMPLEMENT)[::-1]
    return _NN_TABLE.get(rc)


# Initiation terms (kcal/mol, cal/mol·K) — SantaLucia 1998 Table 1.
_INIT_AT = (2.3, 4.1)   # terminal A·T bp
_INIT_GC = (0.1, -2.8)  # terminal G·C bp


def _is_at(base: str) -> bool:
    return base.upper() in ("A", "T")


# Gas constant in kcal/mol·K (1.987 cal/mol·K / 1000).
_R_KCAL = 1.987e-3


def gc_content(seq: str) -> float:
    """GC fraction expressed as a percentage. Returns 0.0 on empty input."""
    if not seq:
        return 0.0
    s = seq.upper()
    gc = s.count("G") + s.count("C")
    return gc / len(s) * 100.0


def tm_nn(seq: str, na_mM: float = 50.0, conc_nM: float = 250.0) -> Optional[float]:
    """Melting temperature in Celsius for *seq* using the SantaLucia 1998
    nearest-neighbour model with a log-linear salt correction.

    Formula
    -------
        Tm°K = ΔH / (ΔS + R·ln(C_T / x))    (x = 4 for non-self-complementary)
        Tm°C = Tm°K − 273.15
        Tm_corrected = Tm°C + 16.6 · log10(Na⁺ M)   (SantaLucia 1998 §3.3, eq. 22)

    Parameters
    ----------
    seq      : DNA sequence, ACGT (case-insensitive). Returns ``None`` if the
               sequence contains any non-ACGT base (e.g. 'N') or is shorter
               than 2 nt.
    na_mM    : monovalent salt concentration in mM (default 50).
    conc_nM  : total oligo strand concentration in nM (default 250).

    Returns
    -------
    Tm in °C, or ``None`` if undefined (too short, ambiguous bases, or
    degenerate ΔS).
    """
    if not isinstance(seq, str) or len(seq) < 2:
        return None
    s = seq.upper()
    if any(b not in "ACGT" for b in s):
        return None

    # ── Nearest-neighbour ΔH / ΔS sum ────────────────────────────────────────
    dH = 0.0
    dS = 0.0
    for i in range(len(s) - 1):
        nn = _nn_lookup(s[i : i + 2])
        if nn is None:
            return None
        dH += nn[0]
        dS += nn[1]

    # ── Initiation terms (5' end + 3' end) ──────────────────────────────────
    for terminal in (s[0], s[-1]):
        i_dH, i_dS = _INIT_AT if _is_at(terminal) else _INIT_GC
        dH += i_dH
        dS += i_dS

    # ── Tm in Kelvin ────────────────────────────────────────────────────────
    # Non-self-complementary form: divisor x = 4. For a short overhang sub-
    # domain we don't try to detect self-complementarity (the user-side
    # hairpin/dimer flags catch the pathological cases separately).
    C_T = conc_nM * 1e-9  # convert nM → M
    if C_T <= 0:
        return None
    # ΔS is in cal/mol·K — convert to kcal/mol·K for consistency with ΔH.
    dS_kcal = dS / 1000.0
    denom = dS_kcal + _R_KCAL * math.log(C_T / 4.0)
    if abs(denom) < 1e-12:
        return None
    tm_kelvin = dH / denom
    tm_c = tm_kelvin - 273.15

    # ── Salt correction (SantaLucia 1998 §3.3, log-linear) ──────────────────
    # Tm_corrected(Na⁺) = Tm(1 M Na⁺) + 16.6 · log10([Na⁺] M)
    if na_mM <= 0:
        return tm_c
    tm_c += 16.6 * math.log10(na_mM / 1000.0)
    return tm_c


__all__ = ["tm_nn", "gc_content"]
