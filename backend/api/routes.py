"""
API layer — REST route definitions.

Phase 1 routes:
  GET  /api/health                    — liveness probe
  GET  /api/design/demo               — hardcoded seed Design (single 42 bp helix)
  GET  /api/design/demo/geometry      — NucleotidePosition array for the demo design

Geometry response fields per nucleotide:
  helix_id, bp_index, direction
  backbone_position, base_position, base_normal, axis_tangent  (all nm)
  strand_id, strand_type, is_five_prime, is_three_prime        (topology)
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.geometry import nucleotide_positions
from backend.core.models import (
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)

router = APIRouter()


# ── Seed design ───────────────────────────────────────────────────────────────

def _demo_design() -> Design:
    """
    Single 42 bp helix along +Z, phase_offset=0.
    Scaffold strand: FORWARD (5′ at bp 0, 3′ at bp 41).
    Staple strand:   REVERSE (5′ at bp 41, 3′ at bp 0).
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    helix = Helix(
        id="demo_helix",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=42 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=42,
    )
    scaffold = Strand(
        id="scaffold",
        domains=[Domain(helix_id="demo_helix", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    staple = Strand(
        id="staple_0",
        domains=[Domain(helix_id="demo_helix", start_bp=0, end_bp=41, direction=Direction.REVERSE)],
        strand_type=StrandType.STAPLE,
    )
    return Design(
        id="demo",
        helices=[helix],
        strands=[scaffold, staple],
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="Demo — single 42 bp helix"),
    )


def _strand_nucleotide_info(design: Design) -> dict:
    """
    Build a mapping (helix_id, bp_index, Direction) → strand metadata dict.

    For each strand, computes which nucleotides are the 5′ and 3′ endpoints
    based on domain order and direction.

    Convention: start_bp is always the 5′ end of a domain; end_bp is always
    the 3′ end.  make_bundle_design follows this convention:
      FORWARD domain: start_bp=0,   end_bp=N-1
      REVERSE domain: start_bp=N-1, end_bp=0
    """
    info: dict = {}
    for strand in design.strands:
        if not strand.domains:
            continue
        first = strand.domains[0]
        last  = strand.domains[-1]

        five_prime_key  = (first.helix_id, first.start_bp, first.direction)
        three_prime_key = (last.helix_id,  last.end_bp,   last.direction)

        for di, domain in enumerate(strand.domains):
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                key = (domain.helix_id, bp, domain.direction)
                info[key] = {
                    "strand_id":    strand.id,
                    "strand_type":  strand.strand_type.value,
                    "is_five_prime":  key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                    "domain_index":   di,
                }
    return info


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/design/demo")
def get_demo_design() -> dict:
    """Return the demo Design as a JSON-serialisable dict."""
    return _demo_design().to_dict()


@router.get("/design/demo/geometry")
def get_demo_geometry() -> list[dict]:
    """
    Return a flat array of nucleotide positions enriched with strand topology.

    backbone_position and base_position are in nanometres (world frame).
    base_normal and axis_tangent are unit vectors.

    strand_id / strand_type / is_five_prime / is_three_prime are derived from
    the Design's strand+domain structure so the frontend can draw correct
    strand direction arrows and mark 5′ end cubes without hard-coding anything.
    """
    design = _demo_design()
    nuc_info = _strand_nucleotide_info(design)
    _missing = {"strand_id": None, "strand_type": StrandType.STAPLE.value,
                "is_five_prime": False, "is_three_prime": False, "domain_index": 0}

    result: list[dict] = []
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
            key = (nuc.helix_id, nuc.bp_index, nuc.direction)
            sinfo = nuc_info.get(key, _missing)
            result.append({
                "helix_id":          nuc.helix_id,
                "bp_index":          nuc.bp_index,
                "direction":         nuc.direction.value,
                "backbone_position": nuc.position.tolist(),
                "base_position":     nuc.base_position.tolist(),
                "base_normal":       nuc.base_normal.tolist(),
                "axis_tangent":      nuc.axis_tangent.tolist(),
                **sinfo,
            })
    return result
