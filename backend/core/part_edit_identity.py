"""Editable recipe identities, separate from the pinned numerical ID factory.

The original feature_identity module is an existing duplex-v1 manifest member.
Keep its implementation byte-stable: adding an unrelated editing contract must
not make old numerical rows require an engine upgrade. Its existing protection
table remains the compatibility base; new editing families extend it here.
This module performs no geometry or numerical identity generation.
"""

from backend.core.feature_identity import preserve_proof_identity as _preserve_base


_PROTECTED = {
    # Conversion derives organizational outputs from this complete ordered
    # placement namespace. Pose values are intentionally not pinned here.
    "group-organize": ("expected_placement_ids",),
    "nanoparticle-connection-version-create": ("version_id", "nanoparticle_connection_version",
        "nanoparticle_application_version", "duplex_id", "duplex_created_at"),
    "nanoparticle-connection-version-patch": ("nanoparticle_connection_version",
        "nanoparticle_application_version", "duplex_id", "duplex_created_at"),
    "nanoparticle-connection-version-delete": ("nanoparticle_connection_version", "nanoparticle_application_version"),
}


def preserve_proof_identity(previous, updated, *, kind=None):
    """Preserve only authored output/contract slots, never invent absent ones."""
    result = _preserve_base(previous, updated, kind=kind)
    if kind == "nucleotide-transform" and "crossover_id" in updated:
        # Here the junction is an authored residue target, not a newly created
        # crossover identity. Keep the pinned factory's other families exact.
        result["crossover_id"] = updated["crossover_id"]
    if (kind == "group-create" and type(previous.get("group")) is dict
            and "id" in previous["group"] and type(result.get("group")) is dict):
        # Preserve the nested output only. Membership/style remain authored
        # inputs; malformed replacements still reach their strict parser.
        result = {**result, "group": {**result["group"], "id": previous["group"]["id"]}}
    keys = _PROTECTED.get(kind, ())
    if kind == "overhang-bulk" and previous.get("connection_version_contract") == 1:
        action = previous.get("action")
        if type(action) is str and action in {"connection-version-create", "connection-version-patch", "connection-version-delete"}:
            keys += ("action", "connection_version_contract")
            if action == "connection-version-create":
                keys += ("version_id",)
    if (kind == "overhang-bulk" and previous.get("connection_application_version") == 1
            and previous.get("action") == "connection-version-apply-linker"):
        keys += ("action", "connection_application_version", "connection_id")
    return {**result, **{key: previous[key] for key in keys if key in previous}}
