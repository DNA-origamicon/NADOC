"""
Hairpin / self-dimer checker for designed single-stranded DNA.

Pure functions over a :class:`Design`; never mutates topology. Drives the
Tools → Sequencing → "Hairpin/Dimer Checker" command, the automatic check after
overhang-sequence generation, and the warning icons in the Plates & tubes tab,
the Overhang Connections panel and the strand spreadsheet.

What is analysed
----------------
- **Overhang strands** — each overhang's single-stranded bases, assembled 5'→3'
  exactly as ``assign_staple_sequences`` writes them (sub-domain overrides →
  parent sequence → 'N', padded to the backing-domain length):

  * hairpin — intramolecular, within the overhang;
  * self-dimer — the overhang on one copy of the strand against the same
    overhang on another copy (origami–origami bridging);
  * a strand carrying two or more overhangs also gets a cross-dimer for every
    pair of its overhangs (overhang A on one copy × overhang B on another).

  The scaffold-bound body is excluded: it is duplexed in the folded structure
  and its sequence is fixed by the scaffold, so it is not a design choice.
- **Linker strands** (``StrandType.LINKER``) — the whole strand, free in
  solution before it hybridises: complement domains are the Watson–Crick
  complement of the bound overhang's bases (bp-aligned, as
  ``strand_partner_bases`` pairs them) and bridge domains carry the
  connection's ``bridge_sequence`` (reverse-complemented on the ds ``b`` half),
  the same composition the Overhang Connections panel displays.

Thermodynamics
--------------
primer3's thermodynamic alignment (``thal``: nearest-neighbour ΔH/ΔS with
loop, mismatch and dangling-end terms). Hairpin Tm is unimolecular
(ΔH/ΔS, concentration-independent); dimer Tm uses the oligo concentration.
Default conditions are a standard DNA-origami folding buffer (user-specified):
0 mM Na⁺, 10 mM Mg²⁺, 0 mM dNTP, 200 nM oligo; ΔG is reported at 37 °C.
primer3 folds Mg²⁺ into a monovalent equivalent (≈ 120·√[Mg²⁺] mM, so
10 mM Mg²⁺ ≈ 380 mM Na⁺). These deliberately do NOT follow the design's
``tm_settings`` (50 mM Na⁺ / 250 nM, used by the sub-domain Tm annotations).
To compare with IDT OligoAnalyzer's defaults pass
``Conditions(na_mM=50, mg_mM=0, conc_nM=250)``.

Limits
------
- thal aligns at most 60 nt per sequence. Longer sequences are scanned with
  60-nt windows at a 10-nt stride, so every structure spanning ≤ 51 nt is
  evaluated exactly; longer-range structures (loops beyond ~45 nt) are not.
- 'N' bases cannot be evaluated. A sequence is split into maximal A/C/G/T runs;
  hairpins are evaluated within runs and dimers between every pair of runs.
  Such results carry ``status == "partial"``; an all-N sequence is
  ``"unsequenced"`` and never flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from backend.core.models import Design, Strand, StrandType
from backend.core.sequences import (
    _assemble_overhang_5to3,
    build_overhang_bp_bases,
    complement_base,
)

DEFAULT_THRESHOLD_C = 30.0  # flagged ("warning", amber ⚠) above this Tm
DEFAULT_SEVERE_C = 50.0  # "critical" (red ⚠) above this Tm

_THAL_MAX_NT = 60  # primer3 THAL_MAX_ALIGN
_WINDOW_STRIDE = 10
_MIN_SEGMENT_NT = 4  # shortest A/C/G/T run that can close a hairpin / pair
_LINKER_PREFIX = "__lnk__"
_RUN_RE = re.compile(r"[ACGT]+")
_RC = str.maketrans("ACGTN", "TGCAN")

METHOD = (
    "primer3 thermodynamic alignment (nearest-neighbour); "
    "60-nt windows at 10-nt stride beyond 60 nt"
)


@dataclass(frozen=True)
class Conditions:
    """Solution conditions passed to primer3 (its units: mM, nM, °C).

    Defaults = DNA-origami folding buffer: no NaCl, 10 mM MgCl₂, 200 nM oligo.
    """

    na_mM: float = 0.0
    mg_mM: float = 10.0
    dntp_mM: float = 0.0
    conc_nM: float = 200.0
    temp_c: float = 37.0

    def __post_init__(self):
        if min(self.na_mM, self.mg_mM, self.dntp_mM) < 0 or self.conc_nM <= 0:
            raise ValueError("Concentrations must be non-negative (oligo > 0).")
        if self.na_mM + self.mg_mM <= 0:
            # primer3's salt correction takes log(cation); with none it returns
            # Tm = -273 °C / ΔG = inf rather than an error.
            raise ValueError("Need Na⁺ or Mg²⁺ > 0 for a salt-corrected Tm.")

    def primer3_kwargs(self) -> dict:
        return {
            "mv_conc": self.na_mM,
            "dv_conc": self.mg_mM,
            "dntp_conc": self.dntp_mM,
            "dna_conc": self.conc_nM,
            "temp_c": self.temp_c,
        }

    def to_dict(self) -> dict:
        return {
            "na_mM": self.na_mM,
            "mg_mM": self.mg_mM,
            "dntp_mM": self.dntp_mM,
            "conc_nM": self.conc_nM,
            "temp_c": self.temp_c,
        }


ORIGAMI_BUFFER = Conditions()


# ── Sequence-level thermodynamics ────────────────────────────────────────────


def _reverse_complement(seq: str) -> str:
    return seq.translate(_RC)[::-1]


def _segments(seq: str) -> list[tuple[int, str]]:
    """Maximal A/C/G/T runs of *seq* long enough to form structure."""
    return [
        (m.start(), m.group())
        for m in _RUN_RE.finditer(seq.upper())
        if len(m.group()) >= _MIN_SEGMENT_NT
    ]


def _windows(seq: str) -> list[tuple[int, str]]:
    n = len(seq)
    if n <= _THAL_MAX_NT:
        return [(0, seq)]
    starts = list(range(0, n - _THAL_MAX_NT + 1, _WINDOW_STRIDE))
    if starts[-1] != n - _THAL_MAX_NT:
        starts.append(n - _THAL_MAX_NT)
    return [(s, seq[s : s + _THAL_MAX_NT]) for s in starts]


def _structure_lines(result) -> list[str]:
    lines = getattr(result, "ascii_structure_lines", None) or []
    return [line.split("\t", 1)[-1] for line in lines]


def _hit(result, structure_result, offset: int) -> dict:
    return {
        "tm": round(float(result.tm), 2),
        "dg": round(float(result.dg) / 1000.0, 2),  # cal/mol → kcal/mol
        "dh": round(float(result.dh) / 1000.0, 2),
        "ds": round(float(result.ds), 2),  # cal/(mol·K)
        "offset": offset,
        "structure": _structure_lines(structure_result),
    }


def _better(a: Optional[tuple], b: Optional[tuple]) -> Optional[tuple]:
    """Keep the candidate with the higher Tm (ties → first)."""
    if b is None:
        return a
    if a is None or b[0].tm > a[0].tm:
        return b
    return a


def hairpin(seq: str, conditions: Conditions) -> Optional[dict]:
    """Most stable (highest-Tm) hairpin in *seq*, or ``None`` if none forms."""
    from primer3 import bindings

    kw = conditions.primer3_kwargs()
    best = None
    for seg_start, seg in _segments(seq):
        for win_start, win in _windows(seg):
            r = bindings.calc_hairpin(win, **kw)
            if r.structure_found:
                best = _better(best, (r, win, seg_start + win_start))
    if best is None:
        return None
    r, win, offset = best
    return _hit(r, bindings.calc_hairpin(win, output_structure=True, **kw), offset)


def _pair_dimer(a: str, b: str, kw: dict, bindings):
    """Best duplex between *a* and *b* (either may exceed 60 nt)."""
    if len(a) > _THAL_MAX_NT and len(b) <= _THAL_MAX_NT:
        a, b = b, a
    best = None
    pieces = _windows(a) if len(b) > _THAL_MAX_NT else [(0, a)]
    for _, piece in pieces:
        r = bindings.calc_heterodimer(piece, b, **kw)
        if r.structure_found:
            best = _better(best, (r, piece, b))
    return best


def dimer(seq_a: str, seq_b: str, conditions: Conditions) -> Optional[dict]:
    """Most stable intermolecular duplex between *seq_a* and *seq_b*.

    For a self-dimer pass the same sequence twice: every A/C/G/T run of one
    copy is aligned against every run of the other.
    """
    from primer3 import bindings

    kw = conditions.primer3_kwargs()
    segs_a = _segments(seq_a)
    segs_b = _segments(seq_b)
    same = seq_a.upper() == seq_b.upper()
    best = None
    for i, (_, a) in enumerate(segs_a):
        for j, (_, b) in enumerate(segs_b):
            if same and j < i:
                continue  # symmetric: run i × run j already covered
            best = _better(best, _pair_dimer(a, b, kw, bindings))
    if best is None:
        return None
    r, a, b = best
    return _hit(r, bindings.calc_heterodimer(a, b, output_structure=True, **kw), 0)


def _status(seq: str) -> str:
    """``unsequenced`` (no defined base), ``partial`` (some N) or ``checked``.

    A fully defined sequence shorter than ``_MIN_SEGMENT_NT`` is ``checked``: it
    was analysed and simply cannot form a structure.
    """
    s = seq.upper()
    if not any(b in "ACGT" for b in s):
        return "unsequenced"
    return "checked" if set(s) <= set("ACGT") else "partial"


def _finish(entry: dict, threshold_c: float, severe_c: float) -> dict:
    tms = [h["tm"] for h in (entry.get("hairpin"), entry.get("dimer")) if h]
    entry["max_tm"] = max(tms) if tms else None
    entry["flagged"] = entry["max_tm"] is not None and entry["max_tm"] > threshold_c
    entry["severity"] = (
        None
        if not entry["flagged"]
        else ("critical" if entry["max_tm"] > severe_c else "warning")
    )
    return entry


# ── Design scoping ───────────────────────────────────────────────────────────


def domains_signature(strand: Strand) -> str:
    """Stable per-strand layout key; the frontend recomputes it to detect staleness."""
    return "|".join(
        f"{d.helix_id}:{d.start_bp}:{d.end_bp}:{d.direction.value}"
        for d in strand.domains
    )


def _live_overhangs(design: Design) -> dict[str, tuple]:
    """overhang_id → (spec, strand, backing-domain length) for checkable overhangs."""
    strands = {s.id: s for s in design.strands}
    backing: dict[str, tuple[Strand, int]] = {}
    for s in design.strands:
        if s.is_reference:
            continue
        for d in s.domains:
            if d.overhang_id and d.overhang_id not in backing:
                backing[d.overhang_id] = (s, abs(d.end_bp - d.start_bp) + 1)
    out: dict[str, tuple] = {}
    for spec in design.overhangs:
        if spec.auxiliary_endpoint or spec.id not in backing:
            continue
        strand, length = backing[spec.id]
        if spec.strand_id and spec.strand_id in strands:
            strand = strands[spec.strand_id]
        if strand.is_reference:
            continue
        out[spec.id] = (spec, strand, length)
    return out


def _linker_parts(strand_id: str) -> tuple[Optional[str], str]:
    """``__lnk__<conn_id>__<a|b|s>`` → (conn_id, suffix)."""
    if not strand_id.startswith(_LINKER_PREFIX):
        return None, ""
    conn_id, sep, suffix = strand_id[len(_LINKER_PREFIX) :].rpartition("__")
    return (conn_id, suffix) if sep else (None, "")


def linker_strand_sequence(
    design: Design, strand: Strand, overhang_bp_bases: dict | None = None
) -> str:
    """Bases of a linker strand 5'→3' as ordered (see module docstring)."""
    if overhang_bp_bases is None:
        overhang_bp_bases = build_overhang_bp_bases(design)
    conn_id, suffix = _linker_parts(strand.id)
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    bridge = (conn.bridge_sequence or "").upper() if conn else ""
    if conn is not None and conn.linker_type == "ds" and suffix == "b":
        bridge = _reverse_complement(bridge)
    stored = (strand.sequence or "").upper()
    bases: list[str] = []
    for d in strand.domains:
        span = abs(d.end_bp - d.start_bp) + 1
        if d.helix_id.startswith(_LINKER_PREFIX):
            bases.extend(bridge[:span].ljust(span, "N"))
        elif d.binds_overhang_id is not None:
            bp_map = overhang_bp_bases.get(d.binds_overhang_id, {})
            step = 1 if d.end_bp >= d.start_bp else -1
            for bp in range(d.start_bp, d.end_bp + step, step):
                base = bp_map.get(bp)
                bases.append(complement_base(base) if base else "N")
        else:
            bases.extend(stored[len(bases) : len(bases) + span].ljust(span, "N"))
    return "".join(bases)


def check_design(
    design: Design,
    *,
    overhang_ids: Iterable[str] | None = None,
    strand_ids: Iterable[str] | None = None,
    threshold_c: float = DEFAULT_THRESHOLD_C,
    severe_c: float = DEFAULT_SEVERE_C,
    conditions: Conditions | None = None,
) -> dict:
    """Run the hairpin / self-dimer check (default: :data:`ORIGAMI_BUFFER`).

    With neither *overhang_ids* nor *strand_ids*, checks every overhang and
    every linker strand (``scope == "all"``). Otherwise checks only the named
    overhangs (plus cross-dimers on their strands and the linker strands that
    bind them) and the overhangs / linker strands of the named strands.

    A flagged check (max Tm > *threshold_c*) has ``severity`` ``"warning"``,
    or ``"critical"`` when its max Tm also exceeds *severe_c*.
    """
    conditions = conditions or ORIGAMI_BUFFER
    live = _live_overhangs(design)
    want_ovhg = set(overhang_ids or ())
    want_strand = set(strand_ids or ())
    scope_all = not want_ovhg and not want_strand

    by_strand: dict[str, list[str]] = {}
    for oid, (_, strand, _) in live.items():
        by_strand.setdefault(strand.id, []).append(oid)

    def ovhg_in_scope(oid: str) -> bool:
        return scope_all or oid in want_ovhg or live[oid][1].id in want_strand

    assembled = {
        oid: "".join(_assemble_overhang_5to3(spec, length))
        for oid, (spec, _, length) in live.items()
    }

    checks: list[dict] = []
    for oid, (spec, strand, _) in live.items():
        if not ovhg_in_scope(oid):
            continue
        seq = assembled[oid]
        entry = {
            "key": f"overhang:{oid}",
            "kind": "overhang",
            "strand_id": strand.id,
            "overhang_ids": [oid],
            "sequence": seq,
            "length": len(seq),
            "status": _status(seq),
            "hairpin": hairpin(seq, conditions),
            "dimer": dimer(seq, seq, conditions),
            "inputs": {"overhangs": {oid: seq}},
        }
        checks.append(_finish(entry, threshold_c, severe_c))

    for sid, oids in by_strand.items():
        ordered = sorted(oids)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if not (ovhg_in_scope(a) or ovhg_in_scope(b)):
                    continue
                sa, sb = assembled[a], assembled[b]
                statuses = {_status(sa), _status(sb)}
                entry = {
                    "key": f"overhang_pair:{a}|{b}",
                    "kind": "overhang_pair",
                    "strand_id": sid,
                    "overhang_ids": [a, b],
                    "sequence": f"{sa}/{sb}",
                    "length": len(sa) + len(sb),
                    "status": "unsequenced"
                    if "unsequenced" in statuses
                    else ("checked" if statuses == {"checked"} else "partial"),
                    "hairpin": None,
                    "dimer": dimer(sa, sb, conditions),
                    "inputs": {"overhangs": {a: sa, b: sb}},
                }
                checks.append(_finish(entry, threshold_c, severe_c))

    overhang_bp_bases = None
    for strand in design.strands:
        if strand.strand_type != StrandType.LINKER or strand.is_reference:
            continue
        bound = sorted(
            {d.binds_overhang_id for d in strand.domains if d.binds_overhang_id}
        )
        if not (
            scope_all
            or strand.id in want_strand
            or any(oid in want_ovhg for oid in bound)
        ):
            continue
        if overhang_bp_bases is None:
            overhang_bp_bases = build_overhang_bp_bases(design)
        seq = linker_strand_sequence(design, strand, overhang_bp_bases)
        conn_id, _ = _linker_parts(strand.id)
        conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
        entry = {
            "key": f"linker:{strand.id}",
            "kind": "linker",
            "strand_id": strand.id,
            "connection_id": conn.id if conn else None,
            "overhang_ids": bound,
            "sequence": seq,
            "length": len(seq),
            "status": _status(seq),
            "hairpin": hairpin(seq, conditions),
            "dimer": dimer(seq, seq, conditions),
            "inputs": {
                "overhangs": {oid: assembled[oid] for oid in bound if oid in assembled},
                "bridge": (conn.bridge_sequence or "").upper() if conn else "",
                "domains": domains_signature(strand),
            },
        }
        checks.append(_finish(entry, threshold_c, severe_c))

    return {
        "design_id": design.id,
        "scope": "all" if scope_all else "partial",
        "threshold_c": threshold_c,
        "severe_threshold_c": severe_c,
        "conditions": conditions.to_dict(),
        "method": METHOD,
        "checks": checks,
        "summary": {
            "checked": sum(1 for c in checks if c["status"] != "unsequenced"),
            "flagged": sum(1 for c in checks if c["flagged"]),
            "critical": sum(1 for c in checks if c["severity"] == "critical"),
            "unsequenced": sum(1 for c in checks if c["status"] == "unsequenced"),
        },
    }


__all__ = [
    "DEFAULT_SEVERE_C",
    "DEFAULT_THRESHOLD_C",
    "ORIGAMI_BUFFER",
    "Conditions",
    "check_design",
    "dimer",
    "domains_signature",
    "hairpin",
    "linker_strand_sequence",
]
