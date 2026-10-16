"""Organization and frozen selection metadata for native display only.

A retained range's strand/domain address describes the feature-stage source.
Geometry uses its helix/direction/interval; later topology may replace that source
entity. Current group membership and numerical placement references remain live.
This does not resolve authoring inputs or relax recipe replay dependencies.
"""

from backend.core.models import DeformationRange, Direction
from backend.core.part_command_errors import CommandContractError
from backend.core.part_comparison_projection import _identity, _reject
from backend.core.part_group_model import GroupOrganization, PartGroup


def organization_index(design, checkpoint, indices):
    from backend.core.part_dna_comparison_contract import MAX_SELECTORS, _limit
    from backend.core.part_group_organization import _bounded_groups, _members

    organization = design.group_organization
    if organization is None:
        return {}, 0
    if type(organization) is not GroupOrganization or set(vars(organization)) != set(GroupOrganization.model_fields):
        _reject("DNA display requires explicit typed group organization")
    try:
        _bounded_groups(organization)
        selectors = len(organization.groups)
        _limit(selectors, MAX_SELECTORS, "organizational groups")
        groups = {}
        for group in organization.groups:
            checkpoint()
            if type(group) is not PartGroup:
                _reject("DNA display requires typed organizational groups")
            selectors += len(group.helix_ids) + len(group.domain_ids)
            _limit(selectors, MAX_SELECTORS, "organizational selectors")
            if type(group.id) is not str or not 1 <= len(group.id) <= 512 or group.id in groups:
                _reject("DNA display requires unique bounded group identities", "invalid_comparison_reference")
            groups[group.id] = group
            for identity in group.helix_ids:
                _identity(identity)
            for member in group.domain_ids:
                _identity(member.strand_id)
                if type(member.domain_index) is not int or not 0 <= member.domain_index <= 2**53 - 1:
                    _reject("DNA display requires bounded domain ordinals", "invalid_comparison_reference")
            _members(group, indices["helices"], indices["strands"], ["group_organization", group.id])
        return groups, selectors
    except CommandContractError as error:
        code = "comparison_limit" if error.code in {"group_organization_limit", "comparison_limit"} else "invalid_comparison_reference"
        _reject(str(error), code)
    except ValueError as error:
        _reject(str(error), "invalid_comparison_reference")


def validate_owned_organization(design):
    """Full scalar/schema validation only after bounded, privately owned capture."""
    if design.group_organization is not None:
        try:
            GroupOrganization.model_validate(design.group_organization.model_dump(mode="python"))
        except ValueError as error:
            _reject(str(error), "invalid_comparison_reference")


def deformation_references(operation):
    """Typed current dependencies, excluding historical source addresses."""
    from backend.core.part_dna_comparison_contract import _bp
    from backend.core.part_group_selection import target_references
    from backend.core.part_scope_references import referenced_resources

    try:
        selected = target_references(operation.targets)
        if operation.target_ranges is None:
            return referenced_resources(operation) | selected
        references = set(referenced_resources(operation.model_copy(
            update={"targets": None, "target_ranges": None})))
        # Named organization remains an explicit live dependency. Primitive
        # source addresses are historical once the native ranges are frozen.
        references.update(ref for ref in selected if ref[0] == "part_group")
        for target in operation.target_ranges:
            if type(target) is not DeformationRange or set(vars(target)) != set(DeformationRange.model_fields):
                _reject("DNA display requires typed frozen ranges", "invalid_comparison_reference")
            _bp(target.start_bp), _bp(target.end_bp)
            if type(target.direction) is not Direction or target.start_bp > target.end_bp:
                _reject("A frozen interval has invalid direction or bounds", "invalid_comparison_reference")
            references.add(("helix", _identity(target.helix_id)))
            if target.strand_id is None:
                if target.domain_index is not None:
                    _reject("A frozen source address must be paired", "invalid_comparison_reference")
            else:
                _identity(target.strand_id)
                if type(target.domain_index) is not int or not 0 <= target.domain_index <= (2**53 - 1):
                    _reject("A frozen source address requires a bounded ordinal", "invalid_comparison_reference")
        return frozenset(references)
    except (NotImplementedError, ValueError) as error:
        if isinstance(error, CommandContractError):
            raise
        _reject(str(error), "invalid_comparison_reference")
