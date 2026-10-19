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
)
from backend.core.models import (
    Design,
    Direction,
    Domain,
    HalfCrossover,
    Strand,
    StrandType,
)

router = APIRouter()


class _ScaffoldSeqBody(BaseModel):
    scaffold_name: str = "M13mp18"
    custom_sequence: Optional[str] = None  # if set, overrides scaffold_name
    strand_id: Optional[str] = None  # target strand (multi-scaffold support)


class _RegionInterval(BaseModel):
    """Inclusive bp interval on one helix (both directions)."""

    helix_id: str
    lo_bp: int
    hi_bp: int


class _FullAutostapleBody(BaseModel):
    history_seed: str | None = None
    scaffold_name: str = "M13mp18"
    custom_sequence: Optional[str] = None
    strand_id: Optional[str] = None
    # Region autostaple: restaple only staples touching these intervals (the
    # region grows to every touching staple); all other staples, their
    # crossovers and sequences are kept exactly. ``None`` = the whole structure.
    region: list[_RegionInterval] | None = None


def autostaple_params(body: "_FullAutostapleBody") -> dict:
    """Recorded params; whole-structure records keep their historical shape."""
    params = body.model_dump()
    if body.region is None:
        params.pop("region")
    return params


@router.post("/design/assign-scaffold-sequence", status_code=200)
def assign_scaffold_sequence_endpoint(
    body: _ScaffoldSeqBody = _ScaffoldSeqBody(),
) -> dict:
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
                design, body.custom_sequence, strand_id=body.strand_id
            )
            scaffold_len = len(
                body.custom_sequence.strip()
                .upper()
                .replace(" ", "")
                .replace("\n", "")
                .replace("\r", "")
            )
        else:
            updated, total_nt, padded_nt = assign_scaffold_sequence(
                design, body.scaffold_name, strand_id=body.strand_id
            )
            scaffold_len = next(
                (ln for name, ln, _ in SCAFFOLD_LIBRARY if name == body.scaffold_name),
                0,
            )
        _run.info = {
            "total_nt": total_nt,
            "scaffold_len": scaffold_len,
            "padded_nt": padded_nt,
        }
        return updated

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind="assign-scaffold-sequence",
            label="Assign scaffold sequence",
            params=body.model_dump(),
            fn=_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    resp = _design_response(updated, report)
    resp.update(_run.info)
    return resp


@router.get("/design/strand/{strand_id}/sequence-context", status_code=200)
def strand_sequence_context(strand_id: str) -> dict:
    """Everything a sequence editor needs to show one strand, 5'→3'.

    Response fields (all sequence strings are index-aligned and have length
    ``length``):

    * ``sequence`` — the strand's current ``sequence``, or null if unassigned.
    * ``derived``  — what "Assign staple sequences" WOULD produce right now, or
      null when the scaffold has no sequence yet.  Powers the editor's
      "Reset to derived" button.
    * ``partner``  — the base each position PAIRS WITH: the scaffold base at the
      antiparallel (helix, bp) for a duplex domain, the overhang base for a
      binder domain, and ``'-'`` where there is no partner (an overhang tip is
      single-stranded, and the scaffold does not cover every staple position).
      Note this reads **3'→5'** left-to-right, because it is laid out in the
      edited strand's 5'→3' index order and pairs antiparallel to it.
    * ``segments`` — per-domain spans ``{start,length,kind,overhang_id,editable}``
      so the editor can shade overhang regions and lock the ones whose bases are
      owned by sub-domain ``sequence_override``s.

    Read-only; never mutates the design.
    """
    from backend.core.sequences import (
        assign_staple_sequences,
        strand_partner_bases,
        strand_sequence_length,
        strand_sequence_segments,
    )

    design = design_state.get_or_404()
    strand = design.find_strand(strand_id)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")

    partners = strand_partner_bases(design, strand)
    try:
        derived = next(
            (
                s.sequence
                for s in assign_staple_sequences(design).strands
                if s.id == strand_id
            ),
            None,
        )
    except ValueError:
        derived = None  # scaffold not sequenced yet — nothing to derive from

    return {
        "strand_id": strand.id,
        "strand_type": strand.strand_type.value,
        "is_scaffold": strand.is_scaffold,
        "length": strand_sequence_length(design, strand),
        "sequence": strand.sequence,
        "derived": derived,
        "partner": "".join(p if p else "-" for p in partners),
        "segments": strand_sequence_segments(design, strand),
    }


def _manual_connection_positions(design: Design) -> set[tuple[str, int, Direction]]:
    """Endpoints of user-issued connections that LOCK the staple carrying them.

    Both ends of every forced ligation — a join autostaple cannot re-derive, so the
    strand it fuses must survive the rebuild intact.

    A ``process_id == "manual"`` crossover is deliberately **not** here.  A manual
    crossover is an ordinary crossover the user happened to place by hand; it changes
    only how staples are CONNECTED, never where they sit, so it is no reason to
    exclude that staple's 32 bp of body from being woven.  Autostaple must not *undo*
    or *duplicate* it — and it doesn't: ``nick_all_major_ticks`` skips every recorded
    crossover bp, ``_place_auto_crossovers`` seeds ``occupied`` from every existing
    crossover half, and its closing ``ligate_crossover_chains`` rebuilds the junction
    from the surviving record.  Locking the whole strand on top of that only starved
    its neighbours of crossovers (workspace/teeth.nadoc: the hand-routed
    ``stpl_XY_2_2`` blanked bp 0–31 on two helices).
    """
    positions: set[tuple[str, int, Direction]] = set()
    for fl in getattr(design, "forced_ligations", None) or []:
        positions.add(
            (fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction)
        )
        positions.add(
            (fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction)
        )
    return positions


def _locked_and_overhang_staple_ids(design: Design) -> tuple[set[str], set[str]]:
    """Classify staples full-autostaple must leave intact.

    Returns ``(locked_ids, overhang_ids)``:
      * **locked** — staples touching a forced ligation.  Autostaple cannot re-derive
        that join, so these are never linearized, nicked, or merged, and auto-crossovers
        route around them.  A manual *crossover* does NOT lock its staple — see
        ``_manual_connection_positions``.
      * **overhang** — staples carrying an overhang domain.  Never split or nicked,
        but may still grow by absorbing a free co-linear neighbour (the merge is
        capped at 48 + overhang nt — see ``_merge_cap`` in lattice.py).

    A strand can be in both sets; the two are used for different stages.
    """
    manual_pos = _manual_connection_positions(design)
    locked: set[str] = set()
    overhang: set[str] = set()
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or s.is_reference:
            continue
        if any(
            d.overhang_id is not None or d.binds_overhang_id is not None
            for d in s.domains
        ):
            overhang.add(s.id)
        for d in s.domains:
            if (d.helix_id, d.start_bp, d.direction) in manual_pos or (
                d.helix_id,
                d.end_bp,
                d.direction,
            ) in manual_pos:
                locked.add(s.id)
                break
    return locked, overhang


def _linearize_staple_precursors(
    design: Design, keep_strand_ids: frozenset[str] = frozenset()
) -> tuple[Design, dict]:
    """Drop *auto* staple crossovers and split free staples into single-domain
    precursors, leaving user-issued connections intact.

    Manual crossovers are kept (auto crossovers are dropped and re-placed). Locked
    staples (touching a manual crossover / forced ligation) and overhang staples
    are preserved whole and excluded from the rebuild; the auto stages downstream
    route around them.

    ``keep_strand_ids`` (region autostaple) are preserved whole as well, together
    with every crossover that belongs to one of them.
    """
    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}
    kept_ends = {
        (d.helix_id, bp, d.direction)
        for s in design.strands if s.id in keep_strand_ids
        for d in s.domains for bp in (d.start_bp, d.end_bp)
    }

    def _kept_half(half: HalfCrossover) -> bool:
        return (half.helix_id, half.index, half.strand) in kept_ends

    def _is_scaffold_half(half: HalfCrossover) -> bool:
        h = helix_map.get(half.helix_id)
        if h is None:
            return False
        row, col = h.grid_pos
        expected = Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE
        return half.strand == expected

    kept_crossovers = [
        xo
        for xo in design.crossovers
        if xo.process_id == "manual"
        or _is_scaffold_half(xo.half_a)
        or _is_scaffold_half(xo.half_b)
        or _kept_half(xo.half_a)
        or _kept_half(xo.half_b)
    ]

    locked_ids, overhang_ids = _locked_and_overhang_staple_ids(design)
    preserve_ids = locked_ids | overhang_ids | set(keep_strand_ids)

    preserved_strands: list[Strand] = []
    staple_domains: dict[tuple[str, Direction], list[Domain]] = {}
    for strand in design.strands:
        if (
            strand.strand_type != StrandType.STAPLE
            or strand.is_reference
            or strand.id in preserve_ids
        ):
            preserved_strands.append(strand)
            continue
        for domain in strand.domains:
            staple_domains.setdefault((domain.helix_id, domain.direction), []).append(
                domain
            )

    rebuilt_staples: list[Strand] = []
    taken = {s.id for s in preserved_strands}
    for (helix_id, direction), domains in sorted(
        staple_domains.items(),
        key=lambda item: (item[0][0], item[0][1].value),
    ):
        intervals = sorted(
            (min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)) for d in domains
        )
        merged: list[tuple[int, int]] = []
        for lo, hi in intervals:
            if not merged or lo > merged[-1][1] + 1:
                merged.append((lo, hi))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        for idx, (lo, hi) in enumerate(merged):
            start_bp, end_bp = (lo, hi) if direction == Direction.FORWARD else (hi, lo)
            identity = f"full_auto_{helix_id}_{direction.value.lower()}_{idx}"
            while identity in taken:  # a preserved staple can carry an earlier run's id
                identity += "_r"
            taken.add(identity)
            rebuilt_staples.append(
                Strand(
                    id=identity,
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
        "locked_strand_count": len(locked_ids),
        "overhang_strand_count": len(overhang_ids),
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
    #
    # User-assigned overhang sequences are PRESERVED here — assign_staple_sequences
    # reads each overhang's stored sequence (via _assemble_overhang_5to3) and threads
    # it into the containing staple, so re-running this must not clear or reassign
    # them. (An earlier version wiped overhang sequences to None first; that was
    # removed deliberately.)
    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind="assign-staple-sequences",
            label="Assign staple sequences",
            params={},
            fn=assign_staple_sequences,
        )
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
    from backend.api.part_autostaple_command import build_full_autostaple
    from uuid import uuid4
    body = body.model_copy(update={"history_seed": body.history_seed or str(uuid4())})
    params = autostaple_params(body)
    full_report = {}

    def _run(design):
        nonlocal full_report
        updated, full_report = build_full_autostaple(design, body)
        return updated

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind="full-autostaple",
            label="Full autostaple" if body.region is None else "Region autostaple",
            params=params,
            fn=_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    resp = _design_response_with_geometry(updated, report)
    resp["full_autostaple"] = full_report
    return resp
