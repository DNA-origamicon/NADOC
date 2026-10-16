"""Staging boundary until organization-aware authoring and UI are complete.

Native input replay can qualify the representation independently. No saved flag,
request parameter or environment setting enables it in an ordinary live session.
Remove this boundary only with the finite consumer and desktop rollout exits.
"""

from backend.core.part_command_errors import CommandContractError
from backend.core.part_group_organization import KINDS


def require_live_design(design):
    if design is not None and getattr(design, "group_organization", None) is not None:
        from fastapi import HTTPException
        raise HTTPException(409, detail={
            "code": "group_organization_not_enabled",
            "message": "Separate groups and placements are not enabled for live editing yet.",
        })


def require_native_command(kind, params):
    """Only already-qualified roles may follow conversion in a private recipe."""
    if "_generated_scope" not in params:
        if kind in KINDS:
            return
        if kind == "cluster_op" and not set(params) - {
                "_proof_version", "_generator", "cluster_id", "translation", "rotation", "pivot"}:
            return  # Explicit existing placement, with no organizational writes.
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
