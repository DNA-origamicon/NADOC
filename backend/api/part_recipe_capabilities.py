"""Describe history editing limits separately from executor availability.

Capabilities are static and cheap. They never inspect a document, replay a
command, or confer a certificate. Verification remains an explicit operation.
"""


def editing_capabilities(kinds):
    from backend.api.part_overhang_commands import ACTIONS

    # Existing history editors; other authoring tools edit current objects, not
    # their historical input commands, so must not be advertised as equivalents.
    specialized = {
        "bundle-create",
        "extrude-segment",
        "extrude-continuation",
        "extrude-deformed-continuation",
        "overhang-extrude",
        "sweep",
        "circular-pattern",
        "linear-pattern",
        "deformation",
        "cluster_op",
        "cluster_create",
        "overhang_rotation",
    }
    return {
        "history_edit": {
            "endpoint": "POST /api/design/features/{index}/edit",
            "body": {"params": "partial command input object"},
            "routing_child_query": "sub_index",
            "requires": [
                "latest history cursor",
                "explicit recipe root",
                "all rows have supported versioned contracts",
                "source history independently reproduces authoring state",
            ],
            "limits": [
                "Existing desktop/VR editors expose only their existing fields; other historical parameters require the API.",
                "Existing UI controls can still restrict earlier rows with later snapshots; API regeneration has broader coverage.",
                "Historical-preview edits and mixed/legacy recipes retain recovery editors and cannot gain native proof from snapshots.",
                "Regeneration uses bounded capture and a five-second cooperative deadline; an oversized edit is refused atomically.",
                "Generated native subpart scopes are immutable references; legacy compound branch/asset construction remains unverified.",
                "Native Join requires preview-selected flexible orientation references; older Join receipts without them remain unverified.",
            ],
        },
        "command_editors": {
            kind: {
                "history_api": True,
                "history_ui": "existing_specialized_fields"
                if kind in specialized
                else "not_available",
            }
            for kind in sorted(kinds)
        },
        "photoproduct_create_methods": ["preflight"],
        "unverified_methods": {
            "photoproduct-create:convert": "Native placement solve has no bounded replay contract"
        },
        "overhang_bulk_actions": sorted(ACTIONS),
        "assemblies": "deferred",
    }
