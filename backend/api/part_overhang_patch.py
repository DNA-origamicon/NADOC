"""Complete overhang patch command, including sequence dependents."""

from backend.api.overhang_patch import _build_overhang_patch, OverhangPatchRequest


def patch(design, overhang_id, body):
    updated, spec_updates, new_spec = _build_overhang_patch(design, overhang_id, body)

    sequence_was_set = "sequence" in body.model_fields_set

    # The strand spreadsheet's Name and the owning overhang's sidebar label are
    # two views of the same oligo name.
    if "label" in body.model_fields_set:
        synced_name = body.label.strip() if body.label and body.label.strip() else None
        updated = updated.model_copy(
            update={
                "strands": [
                    s.model_copy(update={"name": synced_name})
                    if s.id == new_spec.strand_id
                    else s
                    for s in updated.strands
                ]
            }
        )

    # Auto-assign on set: _build_overhang_patch cleared the parent strand's
    # sequence, so re-derive real bases for it AND any complement / binder domain
    # (binds_overhang_id) that reads this overhang's reverse-complement, so the
    # result is simulation-ready without a manual Assign Staple Sequences. No-op
    # until the scaffold is sequenced.
    #
    # TARGETED, not design-wide: only the strands derived from THIS overhang are
    # re-derived. A whole-design assign_staple_sequences here would silently wipe
    # any sequence the user typed by hand on an unrelated staple.
    if sequence_was_set and not body.defer_reassign:
        from backend.core.sequences import (
            overhang_dependent_strand_ids,
            reassign_strands,
        )

        affected = overhang_dependent_strand_ids(updated, [overhang_id])
        updated = reassign_strands(updated, affected)

    return updated, spec_updates, new_spec


def build(design, params):
    if params.get("action") == "generate-random":
        from backend.api.part_overhang_commands import generated_sequence

        return generated_sequence(
            design, params["overhang_id"], params["sequence"], boundaries=True
        )
    return patch(
        design, params["overhang_id"], OverhangPatchRequest.model_validate(params)
    )[0]
