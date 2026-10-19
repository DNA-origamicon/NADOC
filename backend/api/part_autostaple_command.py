"""Native full-autostaple pipeline shared by authoring and recipe replay."""


def build_full_autostaple(design, body):
    from backend.core.routing_identity import identity_scope

    with identity_scope(body.history_seed):
        return _build(design, body)


MAX_REGION_INTERVALS = 10_000


def region_staple_ids(design, region):
    """Staples with any base inside the region (helix, inclusive bp interval)."""
    from backend.core.models import StrandType

    if len(region) > MAX_REGION_INTERVALS:
        raise ValueError(f"Region exceeds {MAX_REGION_INTERVALS} intervals.")
    helices = {h.id for h in design.helices}
    spans = {}
    for item in region:
        if item.helix_id not in helices:
            raise ValueError(f"Region helix {item.helix_id!r} not found.")
        lo, hi = sorted((item.lo_bp, item.hi_bp))
        spans.setdefault(item.helix_id, []).append((lo, hi))
    touching = set()
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or strand.is_reference:
            continue
        for d in strand.domains:
            lo, hi = sorted((d.start_bp, d.end_bp))
            if any(lo <= b and a <= hi for a, b in spans.get(d.helix_id, ())):
                touching.add(strand.id)
                break
    return touching


def _build(design, body):
    from backend.api.routes_assign_sequences import (
        _locked_and_overhang_staple_ids,
        _linearize_staple_precursors,
        _assert_no_circular_staples,
    )
    from backend.api.crud import _place_auto_crossovers
    from backend.core.models import StrandType, _backfill_dropped_junctions
    from backend.core.lattice import grow_staples, nick_all_major_ticks
    from backend.core.sequences import (
        SCAFFOLD_LIBRARY,
        assign_custom_scaffold_sequence,
        assign_scaffold_sequence,
        assign_staple_sequences,
    )

    from backend.api.generation_progress import report as progress

    progress("Assign scaffold sequence", body.scaffold_name, 0.30)
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

    # Classify the staples the user hand-routed; every auto stage below leaves
    # them intact.  Locked staples (manual crossover / forced ligation) are
    # never touched and crossovers route around them.  Overhang staples are kept
    # whole through linearization + tick-nicking (preserving their overhang_id),
    # but their duplex BODY is still woven in by crossovers — only the overhang
    # tip/binder domains are protected from crossover placement (an overhang is
    # embedded in the structure, not a standalone strand).
    locked_ids, overhang_ids = _locked_and_overhang_staple_ids(sequenced)
    # Region autostaple (the region grows to every staple touching it): every
    # other staple is kept exactly — never linearized, nicked, merged or
    # crossed, and its crossovers and sequence survive unchanged.
    if body.region is not None:
        if not body.region:
            raise ValueError("Select a region to autostaple, or autostaple the entire structure.")
        inside = region_staple_ids(sequenced, body.region)
        if not inside:
            raise ValueError("No staples touch the selected region.")
        outside = frozenset(
            s.id for s in sequenced.strands
            if s.strand_type == StrandType.STAPLE and not s.is_reference and s.id not in inside)
    else:
        outside = frozenset()
    protected_ids = locked_ids | overhang_ids | outside

    # Order matters: nick the staples on the tick grid FIRST, then place
    # crossovers onto the fragmented substrate, then grow fragments back into
    # ≤56-nt staples.  Placing crossovers after nicking assembles them into
    # open chains (no staple cycles), so every crossover stays traversed and
    # none has to be pruned — which is also why full density is preserved.
    progress("Break staple precursors", "Nick at major ticks", 0.34)
    precursors, precursor_report = _linearize_staple_precursors(sequenced, outside)
    nicked = nick_all_major_ticks(precursors, skip_strand_ids=protected_ids)
    # Iterate crossover placement to a FIXPOINT. A single pass is order-dependent
    # (it nicks staples + recomputes coverage every step but only re-ligates at the
    # end, so progressive fragmentation falsely starves later bow sites — see the
    # WARNING in _place_auto_crossovers).  Each re-run starts from the placed +
    # re-ligated state and fills the gaps; locked/overhang are RE-DETECTED per pass
    # (detection is content-based — overhang_id domains + manual-connection touches —
    # so protection follows the staple even after ligation renames it).
    crossed = nicked
    total_placed = 0
    for _ in range(12):  # safety bound; placement is monotonic so it converges fast
        progress(
            "Route staple crossovers",
            f"Pass {_ + 1}; {total_placed} crossovers placed",
            0.37,
        )
        locked_i, overhang_i = _locked_and_overhang_staple_ids(crossed)
        crossed, crossover_report = _place_auto_crossovers(
            crossed, protected_strand_ids=locked_i - outside, tip_only_strand_ids=overhang_i,
            kept_strand_ids=outside,
        )
        total_placed += crossover_report["placed"]
        if crossover_report["placed"] == 0:
            break
    crossover_report = {**crossover_report, "placed": total_placed}
    progress("Grow staples", "Merge staple fragments up to 56 nucleotides", 0.42)
    clean = grow_staples(crossed, max_merged_length=56, locked_ids=locked_ids | outside)
    progress("Assign staple sequences", "Complement the scaffold", 0.46)
    clean = assign_staple_sequences(clean)
    # Record a Crossover for any bare same-bp lattice-neighbour junction left in the
    # strand graph — chiefly an overhang's body→tip attachment, which crossover
    # placement deliberately skips (the tip is protected) but which IS a real,
    # valid crossover and must be recorded (else the cadnano editor keeps offering
    # "add crossover" there).  Mismatched-bp attachments stay forced ligations.
    _backfill_dropped_junctions(clean)
    _assert_no_circular_staples(clean)
    original = {s.id: s for s in design.strands if s.id in outside}

    def _kept(strand):
        # Topology and any assigned (possibly hand-typed) sequence stay exactly;
        # a cleared sequence (e.g. after a hand resize) is re-derived from the
        # scaffold, as the whole-structure run would.
        kept = original[strand.id]
        if kept.sequence is None:
            return kept.model_copy(update={"sequence": strand.sequence})
        return kept

    clean = clean.copy_with(
        strands=[
            _kept(strand) if strand.id in original
            else strand.model_copy(update={"routing_seed": []})
            if strand.strand_type == StrandType.STAPLE and not strand.is_reference
            else strand
            for strand in clean.strands
        ]
    )
    full_report = {
        "scaffold": {
            "total_nt": total_nt,
            "scaffold_len": scaffold_len,
            "padded_nt": padded_nt,
        },
        "precursors": precursor_report,
        "auto_crossover": crossover_report,
        **({"region": {"restapled": len(inside), "kept": len(outside)}} if body.region is not None else {}),
    }
    return clean, full_report
