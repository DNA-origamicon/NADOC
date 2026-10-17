"""Editable recipe identities, separate from the pinned numerical ID factory.

The original feature_identity module is an existing duplex-v1 manifest member.
Keep its implementation byte-stable: adding an unrelated editing contract must
not make old numerical rows require an engine upgrade. Its existing protection
table remains the compatibility base; new editing families extend it here.
This module performs no geometry or numerical identity generation.
"""

from backend.core.feature_identity import preserve_proof_identity as _preserve_base


_PROTECTED = {
    "placement-poses": ("_proof_version", "primary_cluster_id", "primary_authored_fields", "legacy_source"),
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
    if kind == "extension-upsert" and type(result.get("entries")) is list:
        old, new = previous.get("entries"), result["entries"]
        if type(old) is not list or len(old) != len(new):
            raise ValueError("Extension edits must retain their authored output slots")
        entries = []
        for before, after in zip(old, new):
            if type(after) is not dict or type(after.get("extension")) is not dict:
                entries.append(after)
                continue  # Strict command admission reports the malformed input.
            ext = after["extension"]
            if before["create"]:
                ext = {**ext, "id": before["extension"]["id"]}
            entries.append({**after, "create": before["create"], "extension": ext})
        result = {**result, "entries": entries}
    if kind in {"nucleotide-transform", "crossover-move", "crossover-delete", "crossover-extra-bases"} and "crossover_id" in updated:
        # Here the junction is an authored target, not a newly created output.
        # The routing normalizer separately protects creator output slots by
        # identity (including batch reorder/add/remove), never by row position.
        # Keep the pinned factory's other families exact.
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
    if (kind == "overhang-bulk" and previous.get("connection_application_version") in (1, 2, 3, 4)
            and previous.get("action") == "connection-version-apply-linker"):
        keys += ("action", "connection_application_version", "connection_id")
    if (kind == "overhang-bulk" and previous.get("connection_composition_version") in (1, 2, 3, 4)
            and previous.get("action") == "connection-version-connect-linker"):
        keys += ("action", "connection_version_contract", "connection_composition_version",
                 "version_id", "created_at", "connection_id")
    if (kind == "overhang-bulk" and previous.get("direct_application_version") in (1, 2)
            and previous.get("action") == "connection-version-apply-direct"):
        keys += ("action", "direct_application_version", "history_seed", "created_at")
    if (kind == "overhang-bulk" and previous.get("direct_composition_version") in (1, 2)
            and previous.get("action") == "connection-version-connect-direct"):
        keys += ("action", "connection_version_contract", "direct_composition_version",
                 "version_id", "history_seed", "created_at")
    return {**result, **{key: previous[key] for key in keys if key in previous}}
