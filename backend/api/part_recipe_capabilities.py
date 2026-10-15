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
                "Ordinary regeneration uses bounded capture and a five-second cooperative deadline; longer work requires an explicit evaluation job.",
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
        "evaluation_jobs": {
            "start": "POST /api/design/features/evaluation/jobs",
            "inspect": "GET /api/design/features/evaluation/jobs/{job_id}",
            "cancel": "DELETE /api/design/features/evaluation/jobs/{job_id}",
            "commit": "POST /api/design/features/evaluation/jobs/{job_id}/commit",
            "operations": ["verify", "append", "edit", "delete"],
            "append_kinds": ["photoproduct-create", "photoproduct-relax", "duplex-relax"],
            "time_budget_seconds": 180,
            "publication": "explicit revision-bound commit of the evaluated candidate",
            "limits": ["2 MB captured input", "256 KB operation input", "8 MB cumulative recovery encoding",
                       "16 MB candidate transport", "two retained jobs", "15 minute result lifetime"],
        },
        "photoproduct_create_methods": ["preflight", "convert"],
        "nanoparticle_contract": {
            "version": 1,
            "kinds": ["nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"],
            "scope": "uncoated gold particles without owned DNA or connection versions",
            "legacy": "Receipts without nanoparticle_version remain unverified",
        },
        "thiol_contract": {
            "version": 1,
            "kinds": ["nanoparticle-conjugate", "nanoparticle-conjugation-delete"],
            "scope": "Unbound radial DNA on uncoated gold; explicit exact replacement ownership",
            "limits": ["128 surface handles", "50000 generated nucleotides"],
            "legacy": "Larger, asset-backed or opaque ownership remains unverified",
        },
        "quantum_dot_contract": {
            "version": 1,
            "kinds": ["nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"],
            "scope": "Uncoated catalog particles without DNA or connection ownership",
            "source": "Pinned selected catalog JSON; no library or network fallback during replay",
            "limits": ["64 KiB catalog entry"],
            "provenance": "Catalog input is reproduced_import; particle diameter and pose remain editable",
            "presentation": "Optional vendor spectra plots are not authoring inputs",
        },
        "protein_contract": {
            "version": 1,
            "kinds": ["protein-import", "protein-attach", "protein-attach-patch", "protein-attach-delete"],
            "import_endpoint": "POST /api/design/features/import/protein",
            "source": "Pinned PDB bytes embedded in the portable part; no library or network fallback",
            "limits": ["250 KB source", "1000 atom records", "4000 parsed bonds"],
            "placement_scope": "Free and part-overhang placements without owned binders",
            "provenance": "An imported source is reproduced_import even when the recipe starts empty",
            "legacy": "Receipts without protein_version remain unverified",
        },
        "protein_conjugation_contract": {
            "version": 1,
            "kinds": ["protein-conjugate", "protein-attach-patch", "protein-attach-delete"],
            "scope": "A captured small protein and one unbound part overhang; optional free placement conversion",
            "limits": ["1000 protein atoms", "4000 parsed bonds", "50000 nucleotide geometry work"],
            "lifecycle": "Explicit binder ownership; constrained delta moves, visibility and guarded deletion",
            "unsupported": ["linker-containing designs", "duplex or nanoparticle target ownership",
                            "absolute or free-conjugate moves", "conjugate atom-site changes"],
            "validation": "Existing native chemical-site and element-validation gate",
        },
        "duplex_contract": {
            "kinds": ["duplex-create", "duplex-connect", "duplex-patch", "duplex-delete", "duplex-sync-bindings", "duplex-relax"],
            "scope": "Explicit part endpoints, registers and binding selections with stable identities",
            "load": "Recipe-backed files preserve authored state; rootless files retain legacy migration",
        },
        "long_job_methods": {
            "photoproduct-create:convert": "Explicit native-source contract with pinned template and numerical engine",
            "photoproduct-relax": "Existing native CPD with pinned template and numerical engine",
            "duplex-relax": "Existing bound native DNA duplex with explicit joint/cluster selections and numerical engine",
        },
        "unverified_methods": {
            "legacy photoproduct-create:convert": "Receipts without an explicit native source and engine pins remain unverified",
        },
        "overhang_bulk_actions": sorted(ACTIONS),
        "assemblies": "deferred",
    }
