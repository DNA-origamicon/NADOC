"""Native nick repair and explicit junction edits, independent of sessions."""

from fastapi import HTTPException
from backend.core.models import Direction, Domain, Strand

KINDS = frozenset(
    {
        "ligate",
        "crossover-delete",
        "crossover-delete-batch",
        "crossover-extra-bases",
        "crossover-extra-bases-batch",
        "forced-ligation-extra-bases",
        "forced-ligation-create",
        "forced-ligation-delete",
        "forced-ligation-delete-batch",
    }
)


def build(kind, design, params):
    from backend.api.crud import NickRequest, _desplice_strands_for_crossover

    if kind == "ligate":
        return ligate(design, NickRequest.model_validate(params))
    if "extra-bases" in kind:
        import re

        field, key = (
            ("forced_ligations", "fl_id")
            if kind.startswith("forced")
            else ("crossovers", "crossover_id")
        )
        entries = params["entries"] if kind.endswith("-batch") else [params]
        sequences = {e[key]: e["sequence"].upper() for e in entries}
        if any(re.fullmatch("[ACGTN]*", seq) is None for seq in sequences.values()):
            raise HTTPException(422, detail="Invalid extra-base sequence")
        records = getattr(design, field)
        if sequences.keys() - {r.id for r in records}:
            raise HTTPException(404, detail="Missing junction")
        return design.copy_with(
            **{
                field: [
                    r.model_copy(update={"extra_bases": sequences[r.id] or None})
                    if r.id in sequences
                    else r
                    for r in records
                ]
            }
        )
    if kind == "forced-ligation-create":
        from backend.core.models import ForcedLigation
        from backend.core.lattice import _ligate

        a, b = (
            design.find_strand(params["three_prime_strand_id"]),
            design.find_strand(params["five_prime_strand_id"]),
        )
        if a is None or b is None:
            raise HTTPException(404, detail="Missing ligation strand")
        if a.id == b.id:
            raise HTTPException(409, detail="Cannot ligate a strand to itself")
        ad, bd = a.domains[-1], b.domains[0]
        fl = ForcedLigation(
            id=params["_fl_id"],
            three_prime_helix_id=ad.helix_id,
            three_prime_bp=ad.end_bp,
            three_prime_direction=ad.direction,
            five_prime_helix_id=bd.helix_id,
            five_prime_bp=bd.start_bp,
            five_prime_direction=bd.direction,
            is_periodic_seam=params.get("is_periodic_seam", False),
        )
        updated = _ligate(design, a, b)
        return updated.copy_with(forced_ligations=[*updated.forced_ligations, fl])
    forced = kind.startswith("forced")
    field = "forced_ligations" if forced else "crossovers"
    records = getattr(design, field)
    ids = (
        set(params["forced_ligation_ids" if forced else "crossover_ids"])
        if kind.endswith("-batch")
        else {params["fl_id" if forced else "crossover_id"]}
    )
    if ids - {r.id for r in records}:
        raise HTTPException(404, detail="Missing junction")
    updated = design
    for record in records:
        if record.id in ids:
            strands = (
                _desplice_forced(updated, record)
                if forced
                else _desplice_strands_for_crossover(
                    updated, record.half_a, record.half_b
                )
            )
            updated = updated.copy_with(strands=strands)
    return updated.copy_with(**{field: [r for r in records if r.id not in ids]})


def _desplice_forced(design, fl):
    for strand in design.strands:
        for index, (a, b) in enumerate(zip(strand.domains, strand.domains[1:])):
            if (
                a.helix_id,
                a.end_bp,
                a.direction,
                b.helix_id,
                b.start_bp,
                b.direction,
            ) == (
                fl.three_prime_helix_id,
                fl.three_prime_bp,
                fl.three_prime_direction,
                fl.five_prime_helix_id,
                fl.five_prime_bp,
                fl.five_prime_direction,
            ):
                left = strand.model_copy(
                    update={"domains": list(strand.domains[: index + 1])}
                )
                right = Strand(
                    id=f"{strand.id}_split_{b.helix_id}_{b.start_bp}_{b.direction.value}",
                    domains=list(strand.domains[index + 1 :]),
                    strand_type=strand.strand_type,
                )
                return [s for s in design.strands if s.id != strand.id] + [left, right]
    return list(design.strands)


def ligate(design, body):

    helix_id = body.helix_id
    bp_index = body.bp_index
    direction = body.direction
    adj_bp = bp_index + 1 if direction == Direction.FORWARD else bp_index - 1

    # ── Same-strand domain merge ─────────────────────────────────────────────
    # If a single strand has two adjacent domains at this boundary (e.g. from
    # a forced ligation), merge them — this is the inverse of a nick.
    for s in design.strands:
        for di in range(len(s.domains) - 1):
            d_left = s.domains[di]
            d_right = s.domains[di + 1]
            if (
                d_left.helix_id == helix_id
                and d_left.direction == direction
                and d_left.end_bp == bp_index
                and d_right.helix_id == helix_id
                and d_right.direction == direction
                and d_right.start_bp == adj_bp
            ):
                merged_dom = Domain(
                    helix_id=helix_id,
                    start_bp=d_left.start_bp,
                    end_bp=d_right.end_bp,
                    direction=direction,
                )
                new_domains = (
                    list(s.domains[:di]) + [merged_dom] + list(s.domains[di + 2 :])
                )
                patched = s.model_copy(
                    update={
                        "domains": new_domains,
                        "sequence": None,
                    }
                )

                return design.copy_with(
                    strands=[patched if st.id == s.id else st for st in design.strands]
                )

    # ── Cross-strand ligation ────────────────────────────────────────────────
    # Find strand A: 3′ terminus at bp_index
    strand_a: Strand | None = None
    for s in design.strands:
        if not s.domains:
            continue
        last = s.domains[-1]
        if (
            last.helix_id == helix_id
            and last.direction == direction
            and last.end_bp == bp_index
        ):
            strand_a = s
            break
    if strand_a is None:
        raise HTTPException(
            404,
            detail=(
                f"No strand has a 3′ end at helix={helix_id!r} bp={bp_index} "
                f"direction={direction.value}."
            ),
        )

    # Find strand B: 5′ terminus at adj_bp
    strand_b: Strand | None = None
    for s in design.strands:
        if not s.domains:
            continue
        first = s.domains[0]
        if (
            first.helix_id == helix_id
            and first.direction == direction
            and first.start_bp == adj_bp
        ):
            strand_b = s
            break
    if strand_b is None:
        raise HTTPException(
            404,
            detail=(
                f"No strand has a 5′ end at helix={helix_id!r} bp={adj_bp} "
                f"direction={direction.value}."
            ),
        )
    if strand_b.id == strand_a.id:
        raise HTTPException(409, detail="Cannot ligate a strand to itself.")

    # Merge the two touching domains into one, combine domain lists
    dom_a_last = strand_a.domains[-1]
    dom_b_first = strand_b.domains[0]
    merged_dom = Domain(
        helix_id=helix_id,
        start_bp=dom_a_last.start_bp,
        end_bp=dom_b_first.end_bp,
        direction=direction,
    )
    merged_domains = (
        list(strand_a.domains[:-1]) + [merged_dom] + list(strand_b.domains[1:])
    )

    merged_strand = Strand(
        id=strand_a.id,
        domains=merged_domains,
        strand_type=strand_a.strand_type,
        color=strand_a.color,
        sequence=None,  # topology changed — clear sequence
    )

    return design.copy_with(
        strands=[
            merged_strand if s.id == strand_a.id else s
            for s in design.strands
            if s.id != strand_b.id
        ]
    )
