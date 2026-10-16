"""Private replay adapter forwarding passive native domain-lineage events."""

from backend.core.part_command_errors import CommandContractError


def build(kind, design, params, *, lineage):
    from backend.api import crud

    if kind == "strand-end-resize":
        return crud._build_strand_end_resize(
            design, crud.StrandEndResizeRequest.model_validate(params), lineage=lineage
        )
    if kind == "domain-shift":
        return crud._build_domain_shift(
            design, crud.DomainShiftRequest.model_validate(params), lineage=lineage
        )
    raise CommandContractError(
        "This command has no passive resize/shift adapter.",
        code="unsupported_group_lineage_command",
    )
