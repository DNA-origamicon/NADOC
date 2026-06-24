"""
API layer — scaffold/staple *sequence-assignment* endpoints (extracted from crud.py).

This module hosts the three one-click sequence-assignment commands:

  POST /design/assign-scaffold-sequence  — assign M13/p7560/p8064 (or custom) to a scaffold strand
  POST /design/assign-staple-sequences   — Watson-Crick complement every staple base
  POST /design/full-autostaple           — assign + place crossovers + break/merge + re-derive seqs

One reason to change: how NADOC assigns nucleotide sequences to strands. These
sat under crud.py's ``# ── Sequence assignment endpoints`` banner; the
auto-*routing* variants that shared the banner by adjacency (they place
crossovers/seams, NOT sequences) already left for ``routes_scaffold_routing.py``.

The shared response helpers ``_design_response`` / ``_design_response_with_geometry``
stay in crud.py (used by 100+ routes) and are imported back here — same
shared-kernel convention as routes_scaffold_routing.py / routes_clusters.py.
``_place_auto_crossovers`` ALSO stays in crud.py: it lives in the crossover
region, is called by a crossover route there, and is imported by
``tests/test_simple_router.py`` — i.e. shared cross-region (L13 leave-and-import-back).
The two region-only helpers (`_linearize_staple_precursors`,
`_assert_no_circular_staples`) moved IN here with the full-autostaple route.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
# Shared response helpers (100+ crud.py callers) + the cross-region crossover
# placer stay in crud.py and are imported back here (L13 / shared-kernel convention).
from backend.api.crud import (
    _design_response,
    _design_response_with_geometry,
    _place_auto_crossovers,
)
from backend.core.models import Design, Direction, Domain, HalfCrossover, Strand, StrandType

router = APIRouter()


class _ScaffoldSeqBody(BaseModel):
    scaffold_name: str = "M13mp18"
    custom_sequence: Optional[str] = None  # if set, overrides scaffold_name
    strand_id: Optional[str] = None        # target strand (multi-scaffold support)


class _FullAutostapleBody(BaseModel):
    scaffold_name: str = "M13mp18"
    custom_sequence: Optional[str] = None
    strand_id: Optional[str] = None


@router.post("/design/assign-scaffold-sequence", status_code=200)
def assign_scaffold_sequence_endpoint(body: _ScaffoldSeqBody = _ScaffoldSeqBody()) -> dict:
    """Assign a scaffold sequence to a scaffold strand.

    Body fields:
    - ``scaffold_name``: one of "M13mp18", "p7560", "p8064" (default: M13mp18).
    - ``custom_sequence``: raw ATGCN string; when non-empty overrides scaffold_name.
    - ``strand_id``: target a specific scaffold strand (for multi-scaffold designs).

    The response includes ``total_nt``, ``scaffold_len``, and ``padded_nt``.
    """
    from backend.core.sequences import (
        SCAFFOLD_LIBRARY,
        assign_custom_scaffold_sequence,
        assign_scaffold_sequence,
    )
    from fastapi import HTTPException

    # Logged as a feature-log snapshot (op_kind='assign-scaffold-sequence') so the
    # sequenced state is captured in the log — a feature-log seek (incl. an oxDNA/MD
    # job roll) reproduces the sequences instead of dropping them.
    def _run(design):
        use_custom = bool(body.custom_sequence and body.custom_sequence.strip())
        if use_custom:
            updated, total_nt, padded_nt = assign_custom_scaffold_sequence(
                design, body.custom_sequence, strand_id=body.strand_id)
            scaffold_len = len(body.custom_sequence.strip().upper().replace(" ", "").replace("\n", "").replace("\r", ""))
        else:
            updated, total_nt, padded_nt = assign_scaffold_sequence(
                design, body.scaffold_name, strand_id=body.strand_id)
            scaffold_len = next(
                (ln for name, ln, _ in SCAFFOLD_LIBRARY if name == body.scaffold_name), 0)
        _run.info = {"total_nt": total_nt, "scaffold_len": scaffold_len, "padded_nt": padded_nt}
        return updated

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind='assign-scaffold-sequence', label='Assign scaffold sequence',
            params=body.model_dump(), fn=_run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    resp = _design_response(updated, report)
    resp.update(_run.info)
    return resp


def _linearize_staple_precursors(design: Design) -> tuple[Design, dict]:
    """Remove staple crossovers and split staples into single-domain precursors."""
    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}

    def _is_scaffold_half(half: HalfCrossover) -> bool:
        h = helix_map.get(half.helix_id)
        if h is None:
            return False
        row, col = h.grid_pos
        expected = Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE
        return half.strand == expected

    kept_crossovers = [
        xo for xo in design.crossovers
        if _is_scaffold_half(xo.half_a) or _is_scaffold_half(xo.half_b)
    ]
    preserved_strands: list[Strand] = []
    staple_domains: dict[tuple[str, Direction], list[Domain]] = {}
    for strand in design.strands:
        if (
            strand.strand_type != StrandType.STAPLE
            or strand.is_reference
        ):
            preserved_strands.append(strand)
            continue
        for domain in strand.domains:
            if domain.overhang_id is not None or domain.binds_overhang_id is not None:
                preserved_strands.append(strand.model_copy(update={"domains": [domain]}))
                continue
            staple_domains.setdefault((domain.helix_id, domain.direction), []).append(domain)

    rebuilt_staples: list[Strand] = []
    for (helix_id, direction), domains in sorted(
        staple_domains.items(),
        key=lambda item: (item[0][0], item[0][1].value),
    ):
        intervals = sorted((min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)) for d in domains)
        merged: list[tuple[int, int]] = []
        for lo, hi in intervals:
            if not merged or lo > merged[-1][1] + 1:
                merged.append((lo, hi))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        for idx, (lo, hi) in enumerate(merged):
            start_bp, end_bp = (lo, hi) if direction == Direction.FORWARD else (hi, lo)
            rebuilt_staples.append(
                Strand(
                    id=f"full_auto_{helix_id}_{direction.value.lower()}_{idx}",
                    strand_type=StrandType.STAPLE,
                    domains=[
                        Domain(
                            helix_id=helix_id,
                            start_bp=start_bp,
                            end_bp=end_bp,
                            direction=direction,
                        )
                    ],
                )
            )

    updated = design.model_copy(
        update={
            "strands": preserved_strands + rebuilt_staples,
            "crossovers": kept_crossovers,
        }
    )
    return updated, {
        "removed_staple_crossover_count": len(design.crossovers) - len(kept_crossovers),
        "rebuilt_precursor_count": len(rebuilt_staples),
    }


def _assert_no_circular_staples(design: Design) -> None:
    from backend.core.validator import validate_design

    circular_messages = [
        result.message
        for result in validate_design(design).results
        if not result.ok and "Circular staple strand" in result.message
    ]
    if circular_messages:
        raise ValueError("; ".join(circular_messages))


@router.post("/design/assign-staple-sequences", status_code=200)
def assign_staple_sequences_endpoint() -> dict:
    """Assign complementary sequences to all staple strands.

    Each staple base is derived as the Watson-Crick complement of the scaffold
    base at the antiparallel position on the same helix.  Unmatched positions
    (no scaffold coverage) receive 'N'.

    Requires the scaffold to have a sequence assigned first
    (via ``POST /design/assign-scaffold-sequence``).

    Returns 422 if no scaffold or scaffold has no sequence.
    """
    from backend.core.sequences import assign_staple_sequences
    from fastapi import HTTPException

    # Logged (op_kind='assign-staple-sequences') so the sequenced state is captured
    # in the feature log and survives a seek / job roll.
    def _run(design):
        if design.overhangs:
            cleared_overhangs = [o.model_copy(update={"sequence": None}) for o in design.overhangs]
            design = design.model_copy(update={"overhangs": cleared_overhangs})
        return assign_staple_sequences(design)

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind='assign-staple-sequences', label='Assign staple sequences',
            params={}, fn=_run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _design_response(updated, report)


@router.post("/design/full-autostaple", status_code=200)
def full_autostaple_endpoint(body: _FullAutostapleBody = _FullAutostapleBody()) -> dict:
    """Assign sequences, place compliant crossovers, and break staples.

    This is the one-click routing command.  It assigns the scaffold sequence
    first, places all crossovers (skipping a margin around scaffold seams),
    breaks staples at every major tick and merges them up to 56 nt, re-derives
    staple sequences, then prunes any unligated crossover records that would
    circularize a staple if kept.
    """
    from backend.core.lattice import grow_staples, nick_all_major_ticks
    from backend.core.sequences import (
        SCAFFOLD_LIBRARY,
        assign_custom_scaffold_sequence,
        assign_scaffold_sequence,
        assign_staple_sequences,
    )

    params = body.model_dump()

    def _run(design):
        use_custom = bool(body.custom_sequence and body.custom_sequence.strip())
        if use_custom:
            sequenced, total_nt, padded_nt = assign_custom_scaffold_sequence(
                design,
                body.custom_sequence or "",
                strand_id=body.strand_id,
            )
            scaffold_len = len(
                (body.custom_sequence or "")
                .strip()
                .upper()
                .replace(" ", "")
                .replace("\n", "")
                .replace("\r", "")
            )
        else:
            sequenced, total_nt, padded_nt = assign_scaffold_sequence(
                design,
                body.scaffold_name,
                strand_id=body.strand_id,
            )
            scaffold_len = next(
                (ln for name, ln, _ in SCAFFOLD_LIBRARY if name == body.scaffold_name),
                0,
            )

        # Order matters: nick the staples on the tick grid FIRST, then place
        # crossovers onto the fragmented substrate, then grow fragments back into
        # ≤56-nt staples.  Placing crossovers after nicking assembles them into
        # open chains (no staple cycles), so every crossover stays traversed and
        # none has to be pruned — which is also why full density is preserved.
        precursors, precursor_report = _linearize_staple_precursors(sequenced)
        nicked = nick_all_major_ticks(precursors)
        crossed, crossover_report = _place_auto_crossovers(nicked)
        clean = grow_staples(crossed, max_merged_length=56)
        clean = assign_staple_sequences(clean)
        _assert_no_circular_staples(clean)
        _run.full_report = {
            "scaffold": {
                "total_nt": total_nt,
                "scaffold_len": scaffold_len,
                "padded_nt": padded_nt,
            },
            "precursors": precursor_report,
            "auto_crossover": crossover_report,
        }
        return clean

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind='full-autostaple',
            label='Full autostaple',
            params=params,
            fn=_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    resp = _design_response_with_geometry(updated, report)
    resp["full_autostaple"] = getattr(_run, "full_report", {})
    return resp
