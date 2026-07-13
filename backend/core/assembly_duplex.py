"""Cross-part **AssemblyDuplex** helpers — the assembly-level analog of
``backend.core.duplex``.

An :class:`~backend.core.models.AssemblyDuplex` is a register-bearing
hybridization edge between two overhangs on different ``PartInstance`` designs
(see ``memory/project_assembly_overhang_bindings.md`` and
``memory/project_overhang_duplex_foundation.md``). It converges the assembly
overhang/linker layer onto the same Duplex graph the part editor uses.

This module deliberately delegates the topology-sensitive kernels to
``backend.core.duplex`` — the bp↔offset coordinate math (:func:`offset_to_bp`),
the assembled-overhang base slice (:func:`overhang_offset_bases`) and the
antiparallel WC walk (:func:`classify_antiparallel`) are reused verbatim per
side, so the cross-part path can NOT drift from the per-design register/polarity
rules (feedback_crossover_no_reasoning: never re-reason the polarity — reuse the
proven primitive).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from backend.core.duplex import (
    classify_antiparallel,
    offset_to_bp,
    overhang_offset_bases,
)
from backend.core.models import (
    Assembly,
    AssemblyDuplex,
    AssemblyDuplexEnd,
    AssemblyOverhangBinding,
    Design,
    Domain,
    PartInstance,
    SubDomain,
    _overhang_backing_domain,
)


# ── instance / overhang resolution ────────────────────────────────────────────

def _instance_design(inst: PartInstance) -> Optional[Design]:
    """Resolve a PartInstance's source Design (inline or file). Returns None when
    a file source can't be found — a stale reference is harmless (skipped)."""
    from backend.core.assembly_flatten import _load_design
    try:
        return _load_design(inst.source)
    except (FileNotFoundError, ValueError):
        return None


def _instance_map(assembly: Assembly) -> Dict[str, PartInstance]:
    return {inst.id: inst for inst in assembly.instances}


def _resolve_end_context(
    assembly: Assembly, inst_map: Dict[str, PartInstance],
    instance_id: str, overhang_id: str,
) -> Tuple[Optional[Design], Optional[Domain]]:
    """(design, backing_domain) for an overhang on one instance, or (None, None)."""
    inst = inst_map.get(instance_id)
    if inst is None:
        return None, None
    design = _instance_design(inst)
    if design is None:
        return None, None
    _, dom = _overhang_backing_domain(design, overhang_id)
    return design, dom


def _sub_domain(design: Design, overhang_id: str, sub_domain_id: str) -> Optional[SubDomain]:
    for ov in design.overhangs:
        if ov.id != overhang_id:
            continue
        for sd in ov.sub_domains:
            if sd.id == sub_domain_id:
                return sd
    return None


def _end_from_sub_domain(
    instance_id: str, overhang_id: str, dom: Domain, sd: SubDomain, length: int,
) -> AssemblyDuplexEnd:
    """Build an :class:`AssemblyDuplexEnd` covering ``length`` bases from the
    sub-domain's 5' base (mirrors ``backend.core.duplex.subdomain_end`` but for the
    instance-qualified end)."""
    start_bp = offset_to_bp(dom, sd.start_bp_offset)
    end_bp = offset_to_bp(dom, sd.start_bp_offset + length - 1)
    return AssemblyDuplexEnd(
        instance_id=instance_id, overhang_id=overhang_id,
        start_bp=start_bp, end_bp=end_bp,
    )


def assembly_overhang_domain_length(
    assembly: Assembly, inst_map: Dict[str, PartInstance],
    instance_id: str, overhang_id: str,
) -> int:
    _, dom = _resolve_end_context(assembly, inst_map, instance_id, overhang_id)
    return 0 if dom is None else abs(dom.end_bp - dom.start_bp) + 1


# ── connect producer (cross-part mirror of core.duplex.connect_register) ───────

def assembly_longest_driver(
    assembly: Assembly, inst_map: Dict[str, PartInstance],
    left: AssemblyDuplexEnd, right: AssemblyDuplexEnd,
) -> str:
    """Default driver = the LONGER overhang's side (Q4 longest-drives; the shorter
    partner rides its helix). Ties → 'left'. Cross-part mirror of
    ``backend.core.duplex.longest_driver``."""
    la = assembly_overhang_domain_length(assembly, inst_map, left.instance_id, left.overhang_id)
    lb = assembly_overhang_domain_length(assembly, inst_map, right.instance_id, right.overhang_id)
    return 'right' if lb > la else 'left'


def assembly_connect_register(
    assembly: Assembly, inst_map: Dict[str, PartInstance],
    inst_a_id: str, oh_a_id: str, attach_a: str,
    inst_b_id: str, oh_b_id: str, attach_b: str,
) -> Tuple[AssemblyDuplexEnd, AssemblyDuplexEnd]:
    """Compute the register for CONNECTING two cross-part overhangs at their attach
    ends — the producer for a fresh :class:`AssemblyDuplex`. MECHANICAL (no polarity
    reasoning): reuses the same ``_sub_domain_at_attach`` + ``_end_from_sub_domain``
    construction as the binding→duplex migration, so it inherits the proven polarity.
    Honors length-preservation: ``length = min(attach sub-domain lengths)``, no resize
    of either overhang; the longer keeps its excess as a toehold.

    ``attach_*`` is ``'root'`` (embedded 5' end) or ``'free_end'`` (protruding 3'
    tip). Raises ``ValueError`` on unresolved instance / overhang / sub-domain /
    domain."""
    from backend.core.models import _sub_domain_at_attach
    design_a, dom_a = _resolve_end_context(assembly, inst_map, inst_a_id, oh_a_id)
    design_b, dom_b = _resolve_end_context(assembly, inst_map, inst_b_id, oh_b_id)
    if design_a is None or design_b is None:
        raise ValueError("both overhang instances must resolve to a design")
    if dom_a is None or dom_b is None:
        raise ValueError("both overhangs need a backing domain")
    sd_a_id = _sub_domain_at_attach(design_a, oh_a_id, attach_a)
    sd_b_id = _sub_domain_at_attach(design_b, oh_b_id, attach_b)
    if sd_a_id is None or sd_b_id is None:
        raise ValueError("both overhangs need at least one sub-domain to connect")
    sd_a = _sub_domain(design_a, oh_a_id, sd_a_id)
    sd_b = _sub_domain(design_b, oh_b_id, sd_b_id)
    if sd_a is None or sd_b is None:
        raise ValueError("both overhangs must resolve their attach sub-domain")
    length = min(sd_a.length_bp, sd_b.length_bp)
    if length <= 0:
        raise ValueError("attach sub-domain has zero length")
    return (_end_from_sub_domain(inst_a_id, oh_a_id, dom_a, sd_a, length),
            _end_from_sub_domain(inst_b_id, oh_b_id, dom_b, sd_b, length))


# ── migration: AssemblyOverhangBinding → AssemblyDuplex ────────────────────────

def _binding_driver_side(
    assembly: Assembly, inst_map: Dict[str, PartInstance], b: AssemblyOverhangBinding,
) -> str:
    """Default driver = the LONGER overhang's side (Q4 longest-drives; the
    AssemblyOverhangBinding carries no explicit driver). Ties → 'left'."""
    la = assembly_overhang_domain_length(assembly, inst_map, b.instance_a_id, b.overhang_a_id)
    lb = assembly_overhang_domain_length(assembly, inst_map, b.instance_b_id, b.overhang_b_id)
    return 'right' if lb > la else 'left'


def synthesize_assembly_duplexes_from_bindings(assembly: Assembly) -> List[AssemblyDuplex]:
    """Convert every legacy :class:`AssemblyOverhangBinding` into an equivalent
    :class:`AssemblyDuplex`. Pure — returns a new list, does not mutate
    ``assembly``. Bindings whose sub-domains / designs no longer resolve are
    skipped (a stale binding is harmless, matching the per-design migration and
    the load validators' leniency). Mirrors
    ``backend.core.duplex.synthesize_duplexes_from_bindings``."""
    inst_map = _instance_map(assembly)
    out: List[AssemblyDuplex] = []
    for i, b in enumerate(assembly.overhang_bindings):
        design_a, dom_a = _resolve_end_context(
            assembly, inst_map, b.instance_a_id, b.overhang_a_id)
        design_b, dom_b = _resolve_end_context(
            assembly, inst_map, b.instance_b_id, b.overhang_b_id)
        if dom_a is None or dom_b is None:
            continue
        sd_a = _sub_domain(design_a, b.overhang_a_id, b.sub_domain_a_id)
        sd_b = _sub_domain(design_b, b.overhang_b_id, b.sub_domain_b_id)
        if sd_a is None or sd_b is None:
            continue
        length = min(sd_a.length_bp, sd_b.length_bp)
        if length <= 0:
            continue
        out.append(AssemblyDuplex(
            name=b.name or f"AD{i + 1}",
            created_at=b.created_at,
            left=_end_from_sub_domain(b.instance_a_id, b.overhang_a_id, dom_a, sd_a, length),
            right=_end_from_sub_domain(b.instance_b_id, b.overhang_b_id, dom_b, sd_b, length),
            driver=_binding_driver_side(assembly, inst_map, b),
            bound=False,
            binding_mode=b.binding_mode,
            allow_n_wildcard=b.allow_n_wildcard,
        ))
    return out


def smallest_unused_assembly_duplex_name(assembly: Assembly) -> str:
    used = {d.name for d in assembly.duplexes if d.name}
    n = 1
    while f"AD{n}" in used:
        n += 1
    return f"AD{n}"


def sync_assembly_duplexes_from_bindings(assembly: Assembly) -> Assembly:
    """Idempotently ensure every legacy binding pair also has a display
    :class:`AssemblyDuplex`. Skips pairs that already carry a duplex; assigns
    fresh unique names. Mirrors ``backend.core.duplex.sync_duplexes_from_bindings``.
    """
    def _pair(dx: AssemblyDuplex):
        return frozenset({
            (dx.left.instance_id, dx.left.overhang_id),
            (dx.right.instance_id, dx.right.overhang_id),
        })

    existing = {_pair(dx) for dx in assembly.duplexes}
    additions: List[AssemblyDuplex] = []
    for dx in synthesize_assembly_duplexes_from_bindings(assembly):
        pair = _pair(dx)
        if pair in existing:
            continue
        existing.add(pair)
        probe = assembly.model_copy(update={
            "duplexes": [*assembly.duplexes, *additions]})
        additions.append(dx.model_copy(update={
            "name": smallest_unused_assembly_duplex_name(probe)}))
    if not additions:
        return assembly
    return assembly.model_copy(update={
        "duplexes": [*assembly.duplexes, *additions]})


# ── cross-part classifier / coverage (reuses the per-design kernel) ────────────

def classify_assembly_duplex(assembly: Assembly, duplex: AssemblyDuplex) -> dict:
    """Per-base classification of one cross-part duplex. Sources each side's
    backing domain + assembled bases from its OWN instance design, then delegates
    the antiparallel WC walk to :func:`backend.core.duplex.classify_antiparallel`
    (same kernel as the per-design classifier — no forked polarity/register math).
    Same return shape as ``classify_duplex_pairing``."""
    inst_map = _instance_map(assembly)
    design_a, left_dom = _resolve_end_context(
        assembly, inst_map, duplex.left.instance_id, duplex.left.overhang_id)
    design_b, right_dom = _resolve_end_context(
        assembly, inst_map, duplex.right.instance_id, duplex.right.overhang_id)
    left_bases = (overhang_offset_bases(design_a, duplex.left.overhang_id)
                  if design_a is not None else [])
    right_bases = (overhang_offset_bases(design_b, duplex.right.overhang_id)
                   if design_b is not None else [])
    return classify_antiparallel(
        left_dom, right_dom, duplex.left, duplex.right,
        left_bases, right_bases, duplex.allow_n_wildcard,
    )


def assembly_overhang_pairing_map(
    assembly: Assembly, instance_id: str, overhang_id: str,
) -> Dict[int, str]:
    """bp → ``'paired'`` | ``'mismatch'`` | ``'unpaired'`` for every bp of an
    overhang's backing domain on one instance, aggregating ALL AssemblyDuplexes
    that touch it (multivalency). Cross-part mirror of
    ``backend.core.duplex.overhang_pairing_map``; a maximal ``'unpaired'`` run is a
    toehold."""
    inst_map = _instance_map(assembly)
    _, dom = _resolve_end_context(assembly, inst_map, instance_id, overhang_id)
    if dom is None:
        return {}
    lo, hi = sorted((dom.start_bp, dom.end_bp))
    result: Dict[int, str] = {bp: 'unpaired' for bp in range(lo, hi + 1)}
    for dx in assembly.duplexes:
        ends = ((dx.left.instance_id, dx.left.overhang_id, 'left'),
                (dx.right.instance_id, dx.right.overhang_id, 'right'))
        if not any(iid == instance_id and oid == overhang_id
                   for iid, oid, _ in ends):
            continue
        cls = classify_assembly_duplex(assembly, dx)
        for p in cls["positions"]:
            for (iid, oid, side), bp in (
                ((dx.left.instance_id, dx.left.overhang_id, 'left'), p["left_bp"]),
                ((dx.right.instance_id, dx.right.overhang_id, 'right'), p["right_bp"]),
            ):
                if iid == instance_id and oid == overhang_id and bp in result:
                    result[bp] = 'paired' if p["complementary"] else 'mismatch'
    return result


def assembly_duplex_wc_ok(assembly: Assembly, duplex: AssemblyDuplex) -> Tuple[bool, str]:
    """Watson-Crick gate (kept for parity with the per-design ``duplex_wc_ok``): a
    duplex is acceptable iff no position is a REAL mismatch (N wildcards pass when
    ``allow_n_wildcard``). Returns ``(ok, reason)``."""
    cls = classify_assembly_duplex(assembly, duplex)
    for p in cls["positions"]:
        if not p["complementary"]:
            return False, (
                f"position {p['offset']} ({p['left_base']}/{p['right_base']}) "
                f"is not Watson-Crick complementary"
            )
    return True, ""


def summarize_assembly_duplexes(assembly: Assembly) -> dict:
    """Headless oracle: compact readout of the whole cross-part duplex graph —
    per-duplex paired/mismatch counts + per-(instance,overhang) paired/mismatch/
    toehold bp totals. Mirrors ``backend.core.duplex.summarize_duplexes``."""
    per_duplex = []
    for dx in assembly.duplexes:
        cls = classify_assembly_duplex(assembly, dx)
        per_duplex.append({
            "id": dx.id, "name": dx.name, "driver": dx.driver, "bound": dx.bound,
            "length": cls["length"],
            "n_complementary": cls["n_complementary"],
            "n_mismatch": cls["n_mismatch"],
        })
    per_overhang = {}
    touched = {(e.instance_id, e.overhang_id)
               for dx in assembly.duplexes for e in (dx.left, dx.right)}
    for iid, oid in sorted(touched):
        cov = assembly_overhang_pairing_map(assembly, iid, oid)
        vals = list(cov.values())
        per_overhang[f"{iid}::{oid}"] = {
            "paired": vals.count('paired'),
            "mismatch": vals.count('mismatch'),
            "toehold": vals.count('unpaired'),
        }
    return {"duplexes": per_duplex, "overhangs": per_overhang}
