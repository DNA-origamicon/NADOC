"""Shared strand metadata/sequence command, including overhang synchronization."""

from fastapi import HTTPException


def build(design, strand_id, body):
    from backend.core.sequences import (
        normalize_sequence_input,
        strand_sequence_length,
        strand_sequence_segments,
    )

    strand = design.find_strand(strand_id)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")

    setting_sequence = "sequence" in body.model_fields_set and body.sequence is not None
    clearing_sequence = "sequence" in body.model_fields_set and body.sequence is None

    patch: dict = {}
    if body.name is not None or "name" in body.model_fields_set:
        patch["name"] = body.name.strip() if body.name and body.name.strip() else None
    if body.notes is not None or "notes" in body.model_fields_set:
        patch["notes"] = body.notes
    if body.color is not None or "color" in body.model_fields_set:
        patch["color"] = body.color

    new_seq: str | None = None
    if setting_sequence:
        try:
            new_seq = normalize_sequence_input(body.sequence or "")
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc))
        expected = strand_sequence_length(design, strand)
        if len(new_seq) != expected:
            raise HTTPException(
                422,
                detail=(
                    f"Sequence length {len(new_seq)} does not match strand "
                    f"{strand_id!r}, which has {expected} nucleotides."
                ),
            )
        patch["sequence"] = new_seq
    elif clearing_sequence:
        patch["sequence"] = None

    new_strands = [
        s.model_copy(update=patch) if s.id == strand_id else s for s in design.strands
    ]

    new_overhangs = design.overhangs
    if "name" in patch:
        owned_overhang_ids = {
            d.overhang_id for d in strand.domains if d.overhang_id is not None
        }
        new_overhangs = [
            o.model_copy(update={"label": patch["name"]})
            if o.id in owned_overhang_ids
            else o
            for o in new_overhangs
        ]
    if clearing_sequence:
        strand_overhang_ids = {
            d.overhang_id for d in strand.domains if d.overhang_id is not None
        }
        if strand_overhang_ids:
            new_overhangs = [
                o.model_copy(update={"sequence": None})
                if o.id in strand_overhang_ids
                else o
                for o in design.overhangs
            ]
    elif setting_sequence:
        # Write each overhang span back onto its OverhangSpec. Set the field
        # DIRECTLY rather than via _build_overhang_patch — that helper resizes the
        # overhang domain to len(sequence), and here the slice is the domain's
        # existing length by construction, so no resize must happen.
        oh_slices = {
            seg["overhang_id"]: new_seq[seg["start"] : seg["start"] + seg["length"]]
            for seg in strand_sequence_segments(design, strand)
            if seg["kind"] == "overhang" and seg["editable"] and seg["overhang_id"]
        }
        if oh_slices:
            new_overhangs = [
                o.model_copy(update={"sequence": oh_slices[o.id]})
                if o.id in oh_slices
                else o
                for o in design.overhangs
            ]

    updated = design.model_copy(
        update={"strands": new_strands, "overhangs": new_overhangs}
    )

    return updated, patch, setting_sequence, clearing_sequence, new_seq
