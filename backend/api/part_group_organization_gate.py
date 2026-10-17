"""Staging boundary until organization-aware authoring and UI are complete.

Native input replay can qualify the representation independently. No saved flag,
request parameter or environment setting enables it in an ordinary live session.
Remove this boundary only with the finite consumer and desktop rollout exits.
"""

from backend.core.part_command_errors import CommandContractError
from backend.core.part_group_organization import KINDS


# One trusted host switch. Saved documents, request bodies and environment
# variables cannot enable authoring or its explicitly reviewed lifecycle paths.
GROUP_ORGANIZATION_ENABLED = False
_LIFECYCLES = frozenset({"load_design", "restore_doc_design", "set_design_branch",
    "copy_for_workspace_save", "acknowledge_workspace_save", "undo", "redo",
    "repair_draft", "repair_draft_evaluation"})


def _refuse():
    from fastapi import HTTPException
    raise HTTPException(409, detail={
        "code": "group_organization_not_enabled",
        "message": "Separate groups and placements are not enabled for this live operation.",
    })


def require_group_edit_enabled():
    if GROUP_ORGANIZATION_ENABLED is not True:
        _refuse()


def require_live_design(design, *, lifecycle=None):
    """Generic writes stay closed; named host lifecycle adapters are separate."""
    if design is not None and getattr(design, "group_organization", None) is not None:
        if type(lifecycle) is str and lifecycle in _LIFECYCLES:
            require_group_edit_enabled()
            return
        _refuse()


def require_group_publication(source, candidate, checked):
    """Called only after the publisher validates its opaque registered permit."""
    if checked is not None and checked.admission.scope_tag == "group_organization_v1":
        if checked.evidence_class != "owned_group_edit":
            _refuse()
        require_group_edit_enabled()
        return
    if checked is not None and checked.admission.scope_tag == "organized_recipe_v1":
        if (checked.evidence_class != "owned_recipe_rebuild"
                or checked.admission.operation not in {"repair", "deformation_preview", "sweep_preview", "transform_preview", "pattern", "extrusion_edit"}):
            _refuse()
        require_group_edit_enabled()
        return
    require_live_design(source)
    require_live_design(candidate)


def require_native_command(kind, params):
    """Only already-qualified roles may follow conversion in a private recipe."""
    from backend.core.part_group_lineage import KINDS as LINEAGE_KINDS
    if "_generated_scope" not in params:
        if kind in KINDS or kind in LINEAGE_KINDS:
            return
        if kind in {"linear-pattern", "circular-pattern"}:
            from backend.core.part_pattern_organization import parse_organization_copy
            if parse_organization_copy(params.get("_organization_copy")) is not None:
                return
        if kind == "deformation":
            return  # Typed named selections resolve separately from placement context.
        if kind == "extension-delete":
            return  # Deletion bypasses reconciliation and preserves all owners/membership.
        if kind == "cluster_op" and not set(params) - {
                "_proof_version", "_generator", "cluster_id", "translation", "rotation", "pivot"}:
            return  # Explicit existing placement, with no organizational writes.
        if kind == "placement-poses":
            from backend.api.part_placement_pose_commands import parse_command
            if not parse_command(params)["primary_authored_fields"]:
                return  # Explicit complete poses, with no legacy membership/style writes.
        # These native numerical contracts explicitly preserve the new authoring
        # metadata, have closed source inventories and exact manifest transitions.
        if (kind == "photoproduct-relax" or
                (kind == "photoproduct-create" and params.get("method") == "convert") or
                kind == "duplex-relax" or
                (kind == "nanoparticle-patch" and "coating_version" in params)):
            return
    raise CommandContractError(
        "This native command has not qualified separate organizational groups and placement owners.",
        code="unsupported_group_organization_command",
    )
