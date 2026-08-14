"""HTTP endpoints for generating standalone and overhang DNA sequences."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.core.models import StrandType
from backend.core.overhang_generator import (
    generate_overhang_sequence_with_overrides,
    generate_overhang_sequences,
    reverse_complement,
)
from backend.core.overhang_ops import (
    _apply_boundary_hairpin_warnings,
    _ovhg_domain_lengths,
)
from backend.core.sequences import assign_staple_sequences

router = APIRouter()


class RandomSequenceRequest(BaseModel):
    length: int


def _sequence_corpus(design):
    scaffold = design.scaffold()
    scaffold_sequence = scaffold.sequence if scaffold and scaffold.sequence else ""
    staple_sequences = [
        strand.sequence
        for strand in design.strands
        if strand.strand_type != StrandType.SCAFFOLD and strand.sequence
    ]
    return scaffold_sequence, staple_sequences


@router.post("/design/random-sequence", status_code=200)
def random_sequence(body: RandomSequenceRequest) -> dict:
    """Generate one structure-safe sequence against the current design corpus."""
    if body.length <= 0:
        raise HTTPException(400, detail="length must be a positive integer.")
    design = design_state.get_or_404()
    scaffold_sequence, staple_sequences = _sequence_corpus(design)
    sequence = generate_overhang_sequences(
        scaffold_sequence, staple_sequences, length=body.length, count=1
    )[0]
    return {"sequence": sequence}


def _generated_sequence(design, spec, length: int, extra_sequences=()):
    scaffold_sequence, staple_sequences = _sequence_corpus(design)
    corpus = staple_sequences + list(extra_sequences)
    sub_domains = list(spec.sub_domains or [])
    if sub_domains and any(sd.sequence_override for sd in sub_domains):
        return generate_overhang_sequence_with_overrides(
            scaffold_sequence, corpus, sub_domains
        )
    return generate_overhang_sequences(
        scaffold_sequence, corpus, length=length, count=1
    )[0]


def _replace_overhang_sequences(design, generated: dict[str, str]):
    return design.model_copy(
        update={
            "overhangs": [
                spec.model_copy(update={"sequence": generated[spec.id]})
                if spec.id in generated
                else spec
                for spec in design.overhangs
            ]
        }
    )


@router.post("/design/overhang/{overhang_id}/generate-random", status_code=200)
def generate_overhang_random_sequence(overhang_id: str) -> dict:
    """Generate and assign a sequence for one overhang."""
    from backend.api.crud import _design_response
    from backend.api.overhang_patch import _resplice_overhang_in_strand

    design = design_state.get_or_404()
    spec = next((item for item in design.overhangs if item.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    domain_length = _ovhg_domain_lengths(design).get(overhang_id)
    if domain_length is None:
        raise HTTPException(404, detail=f"No domain references overhang {overhang_id!r}.")

    sequence = _generated_sequence(design, spec, domain_length)
    updated = _replace_overhang_sequences(design, {overhang_id: sequence})
    updated = _resplice_overhang_in_strand(updated, overhang_id, spec.strand_id)
    for strand in list(updated.strands):
        if strand.id != spec.strand_id and any(
            domain.binds_overhang_id == overhang_id for domain in strand.domains
        ):
            updated = _resplice_overhang_in_strand(updated, overhang_id, strand.id)
    updated = _apply_boundary_hairpin_warnings(updated, overhang_id)
    updated, report, _ = design_state.mutate_with_feature_log(
        op_kind="overhang-sequence",
        label=f"Generate overhang sequence: {sequence}",
        params={"overhang_id": overhang_id, "action": "generate-random"},
        fn=lambda _design: updated,
    )
    return _design_response(updated, report)


@router.post("/design/generate-overhang-sequences", status_code=200)
def generate_all_overhang_sequences() -> dict:
    """Generate mutually diverse sequences for every overhang."""
    from backend.api.crud import _design_response

    design = design_state.get_or_404()
    if not design.overhangs:
        raise HTTPException(422, detail="No overhangs found.")
    lengths = _ovhg_domain_lengths(design)
    generated: dict[str, str] = {}
    extra_sequences: list[str] = []
    for spec in design.overhangs:
        domain_length = lengths.get(spec.id)
        if domain_length is None:
            continue
        sequence = _generated_sequence(design, spec, domain_length, extra_sequences)
        generated[spec.id] = sequence
        extra_sequences.extend((sequence * 10, reverse_complement(sequence) * 10))

    affected_strands = {spec.strand_id for spec in design.overhangs if spec.id in generated}
    affected_strands.update(
        strand.id
        for strand in design.strands
        if any(domain.binds_overhang_id in generated for domain in strand.domains)
    )
    updated = _replace_overhang_sequences(design, generated)
    scaffold = updated.scaffold()
    if scaffold is not None and scaffold.sequence is not None:
        sequenced = {strand.id for strand in design.strands if strand.sequence is not None}
        targets = affected_strands & sequenced
        if targets:
            try:
                derived = assign_staple_sequences(updated)
                sequences = {s.id: s.sequence for s in derived.strands if s.id in targets}
                updated = updated.model_copy(
                    update={
                        "strands": [
                            strand.model_copy(update={"sequence": sequences[strand.id]})
                            if strand.id in sequences
                            else strand
                            for strand in updated.strands
                        ]
                    }
                )
            except Exception:
                pass

    updated, report, _ = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label="Generate overhang sequences",
        params={"generated_count": len(generated), "action": "generate-sequences"},
        fn=lambda _design: updated,
    )
    result = _design_response(updated, report)
    result["generated_count"] = len(generated)
    return result
