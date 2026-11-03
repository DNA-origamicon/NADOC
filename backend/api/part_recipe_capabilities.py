"""Describe history editing limits separately from executor availability.

Capabilities are static and cheap. They never inspect a document, replay a
command, or confer a certificate. Verification remains an explicit operation.
"""


def editing_capabilities(kinds):
    from backend.api.part_overhang_commands import ACTIONS
    from backend.api.part_aptamer_commands import NATIVE_ROUTE_ENABLED
    from backend.api.part_evaluation_capture import (COATING_APPEND_ENABLED, BIOTIN_APPEND_ENABLED,
        NP_FITTING_APPEND_ENABLED, GENERATED_ASSETS_ENABLED)
    from backend.api.routes_design_interchange import NATIVE_FREE_IMPORT_ENABLED
    from backend.api.part_batch_evaluation import REGISTERED_BATCH_ENABLED
    from backend.api.part_extrusion_edit_inputs import KINDS as EXTRUSIONS
    from backend.api.routes_part_sweep_preview import SWEEP_PREVIEW_ENABLED

    # Existing history editors; other authoring tools edit current objects, not
    # their historical input commands, so must not be advertised as equivalents.
    specialized = {
        "sweep",
        "circular-pattern",
        "linear-pattern",
        "deformation",
        "cluster_op",
        "cluster_create",
        "overhang_rotation",
        "nanoparticle-connection-version-create",
        "nanoparticle-connection-version-patch",
        "nanoparticle-conjugate",
        "nanoparticle-attach-overhang",
        "nanoparticle-patch",
        "nanoparticle-connection-relax",
        "nanoparticle-biotin-dna",
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
                "Native desktop extrusion editors expose complete saved inputs for seven families; other editors expose their existing fields. VR parity remains unqualified.",
                "Native extrusion edits rebuild eligible earlier rows through later features without recovery snapshots; other UI editors may still restrict earlier rows.",
                "Historical-preview edits and mixed/legacy recipes retain recovery editors and cannot gain native proof from snapshots.",
                "Owned extrusion/pattern edits use bounded capture and an isolated worker within a five-second capture/proof/publication budget; response geometry formatting is outside that budget. Other ordinary regeneration remains cooperative.",
                "Generated native subpart scopes retain exact references; admitted graft and fit inputs regenerate downstream construction. Legacy compound construction remains unverified.",
                "Native Join requires preview-selected flexible orientation references; older Join receipts without them remain unverified.",
            ],
        },
        "command_editors": {
            kind: {
                "history_api": True,
                "history_ui": "complete_native_inputs" if kind in EXTRUSIONS else (
                    "existing_specialized_fields" if kind in specialized else "not_available"),
            }
            for kind in sorted(kinds)
        },
        "extrusion_history_editor": {
            "kinds": sorted(EXTRUSIONS),
            "requires": ["native proof version 1", "stable history_seed", "ordinary non-generated feature",
                         "expected_design_id", "expected_revision", "expected_feature_id"],
            "limits": ["512 selected cells", "50000 base-pair-cell work", "existing capture/recovery limits"],
            "references": "Resolved against the independently rebuilt pre-feature design; missing selections refuse without publication",
            "organization": "Existing host rollout gate applies; this editor does not enable organization",
        },
        "sweep_history_editor": {
            "endpoint": "POST /api/design/features/sweep-preview",
            "rollout": "enabled for qualified ordinary desktop scope" if SWEEP_PREVIEW_ENABLED else "disabled",
            "inputs": "Complete ordinary native Sweep inputs, including historical source, footprint, path and orientation",
            "preview": "Isolated selected-feature stage; downstream and source equivalence are not certified",
            "apply": "Fresh full source proof and downstream native regeneration; one source-bound publication and undo",
            "limits": ["128 commands", "16 helices", "1024 sites", "60-second lease", "cooperative deadlines"],
        },
        "evaluation_jobs": {
            "start": "POST /api/design/features/evaluation/jobs",
            "inspect": "GET /api/design/features/evaluation/jobs/{job_id}",
            "cancel": "DELETE /api/design/features/evaluation/jobs/{job_id}",
            "commit": "POST /api/design/features/evaluation/jobs/{job_id}/commit",
            "operations": ["verify", "append", "edit", "delete", "repair", "selection"]
                + (["generate"] if GENERATED_ASSETS_ENABLED else []),
            "append_kinds": ["photoproduct-create", "photoproduct-relax", "duplex-relax"]
                + (["streptavidin-coating"] if COATING_APPEND_ENABLED else [])
                + (["nanoparticle-biotin-dna"] if BIOTIN_APPEND_ENABLED else [])
                + (["nanoparticle-attach-overhang", "nanoparticle-bound-move", "nanoparticle-connection-relax"]
                   if NP_FITTING_APPEND_ENABLED else []),
            "registered_batch_enabled": REGISTERED_BATCH_ENABLED,
            "time_budget_seconds": 180,
            "publication": "explicit revision-bound commit of the evaluated candidate",
            "limits": ["2 MB captured input", "256 KB operation input", "8 MB cumulative recovery encoding",
                       "16 MB candidate transport", "two retained jobs", "15 minute result lifetime"],
        },
        "repair_contract": {
            "version": 1,
            "endpoint": "POST /api/design/features/evaluation/jobs",
            "operation": "repair",
            "requires": ["expected_design_id", "expected_revision", "explicit root", "registered definitions"],
            "actions": ["set_input", "upgrade_numerical_contract", "upgrade_cluster_creation"],
            "targets": "Stable snapshot or routing-child input paths; typed grouping rows only through their explicit version upgrade",
            "cluster_creation_upgrade": {
                "from_version": 1, "to_version": 2, "scope": "coherent typed cluster_create definitions",
                "expectations": ["expected_version", "expected_cluster_id", "expected_definition_sha256"],
                "publication": "Explicit repair evaluation and commit; existing definitions are not silently migrated",
            },
            "limits": ["64 actions", "16 path tokens", "256 KB operation input", "10000 operation nodes"],
            "numerical_upgrade_families": ["native CPD v1", "native duplex relaxation v1", "native streptavidin packing v1",
                                          "native nanoparticle fitting v1/v2", "native biotin attachment v1"],
            "publication": "Explicit commit of a complete regenerated candidate; source state need not reproduce",
            "comparison": "Changed authored fields/counts and numerical provenance; bounded native DNA candidate comparison enabled",
            "drafts": "Bounded proposals persist with the part; explicit rebase preserves exact old-value expectations; saved status is not readiness",
            "draft_endpoints": {
                "inspect": "GET /api/design/features/repair-draft",
                "mutate": "POST /api/design/features/repair-draft",
                "evaluate": "POST /api/design/features/repair-draft/evaluate",
                "source_inspect": "POST /api/design/features/repair-draft/source/inspect",
                "source_upload": "POST /api/design/features/repair-draft/source",
            },
            "source_repair": "Explicit named proposed-input staging or published-source restoration; original bounded bytes and exact prior-byte receipt; restoration requires rebase",
            "draft_evaluation": "Existing isolated repair job; exact saved generation and published base; apply retains proposal; job results expire after 15 minutes",
            "ui": "desktop input/reference repair, saved proposals and candidate review",
        },
        "reference_selection": {
            "version": 1,
            "operation": "selection",
            "endpoint": "POST /api/design/features/evaluation/jobs",
            "basis": "Independently rebuilt prefix immediately before the selected feature",
            "requires": ["expected_design_id", "expected_revision", "feature_id", "parameter_path", "expected_old"],
            "scope": ["unowned gold/QD targets", "free protein asset/attachment targets", "typed rigid-copy input IDs"],
            "limits": ["100 candidates", "existing evaluation and recovery budgets"],
            "publication": "Never publishable; full repair evaluates the chosen replacement",
            "unsupported": ["compound selectors", "generated scopes", "coating/thiol/conjugate ownership"],
            "ui": "desktop reference picker for the admitted slots",
        },
        "photoproduct_create_methods": ["preflight", "convert"],
        "nanoparticle_contract": {
            "version": 1,
            "kinds": ["nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"],
            "scope": "uncoated gold particles without owned DNA or connection versions",
            "legacy": "Receipts without nanoparticle_version remain unverified",
        },
        "nanoparticle_connection_contract": {
            "version": 1,
            "kinds": ["nanoparticle-connection-version-create", "nanoparticle-connection-version-patch",
                      "nanoparticle-connection-version-delete"],
            "scope": "Direct candidates on source-free gold thiol handles; create, rename, apply, reapply, switch, unapply and delete",
            "application_version": 2 if NP_FITTING_APPEND_ENABLED else 1,
            "pending_context_version": 1,
            "ownership": "Exact particle, conjugation, strand, ordinary overhang and version selectors; applied contexts select their active version and duplex",
            "limits": ["128 handles for unbound pending metadata; 16 handles / 4096 bases / 128 versions for application or active context",
                       "10000 reference-inventory nodes / 256KB reference data",
                       "up to four fitted active anchors per particle" if NP_FITTING_APPEND_ENABLED else "one active version per particle"],
            "history_ui": "Names and creation direct variants through guarded historical edits",
            "unsupported": ["coated or catalog particles", "generated application except exact v3 teardown/naming"]
                + ([] if NP_FITTING_APPEND_ENABLED else ["relaxed or multiple active versions", "bound motion"]),
            "legacy": "Sparse older receipts remain unverified; recorded native inputs are required",
        },
        "thiol_contract": {
            "version": 1,
            "additive_version": 2,
            "kinds": ["nanoparticle-conjugate", "nanoparticle-conjugation-delete", "nanoparticle-patch"],
            "scope": "Unbound radial DNA on uncoated gold; exact replacement ownership in v1, exact retained ownership in additive v2",
            "motion": "Exact current conjugation selection; existing native movement and resize calculations",
            "limits": ["128 surface handles", "50000 generated nucleotides"],
            "legacy": "Larger, asset-backed or opaque ownership remains unverified",
        },
        "coating_contract": {
            "version": 1,
            "kind": "nanoparticle-patch",
            "actions": ["set", "move", "remove"],
            "scope": "One unowned gold particle with pinned complete 1STP and optional coverage inputs",
            "execution": "Explicit long evaluation only; set/repack pins implementation and numerical runtime",
            "limits": ["64 requested sites", "350 KB PDB source", "4096 bytes coverage JSON"],
            "live_append": "Enabled for the qualified single-gold-particle scope" if COATING_APPEND_ENABLED else "disabled",
            "capture": "Explicit coating jobs only: 4 MB, 100000 nodes, 100 ms cooperative capture; ordinary limits unchanged",
            "publication_scope": "Explicit empty root, at most one gold particle, bounded native coating/biotin rows and sources, empty default animation and one editable main loadout; authored physical/presentation state refuses",
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
            "ordinary_import_enabled": NATIVE_FREE_IMPORT_ENABLED,
            "library_placement": "Original library input transfers into the document with placement in one publication; missing original bytes cannot become a reproducible import",
            "limits": ["250 KB source", "1000 atom records", "4000 parsed bonds"],
            "placement_scope": "Free and part-overhang placements without owned binders",
            "provenance": "An imported source is reproduced_import even when the recipe starts empty",
            "legacy": "Receipts without protein_version remain unverified",
        },
        "aptamer_contract": {
            "version": 1,
            "kinds": ["aptamer-import"],
            "import_endpoint": "POST /api/design/import/aptamer",
            "native_route_enabled": NATIVE_ROUTE_ENABLED,
            "scope": "One complete logical DNA chain using the existing deposited-structure importer",
            "source": "Pinned UTF-8 PDB bytes; no catalog, library or network fallback during replay",
            "limits": ["150 KB source", "1000 first-model atom records"],
            "provenance": "Deposited native sites are reproduced_import, not native-only construction",
            "legacy": "Larger, multiple-chain or opaque ownership imports retain unverified recovery receipts",
        },
        "rigid_copy_contract": {
            "version": 1,
            "kinds": ["element-paste"],
            "endpoint": "POST /api/design/features/copy-elements",
            "requires": ["expected_design_id", "expected_revision"],
            "scope": "Current-part free proteins with explicit atom selections and undecorated gold/catalog particles",
            "limits": ["16 selected elements", "1000 atoms and 4000 bonds per protein asset", "4000 selected protein atoms total"],
            "identity": "Host-owned stable outputs; source selections and paste index remain editable",
            "legacy": "Frozen clipboard and conjugated element copies remain separate unverified receipts",
        },
        "cadnano_contract": {
            "version": 1,
            "kinds": ["cadnano-import"],
            "source": "Pinned caDNAno v2 JSON; complete existing import and postprocessing pipeline",
            "scope": "Explicit empty root; at most one module scaffold",
            "limits": ["100 KB source", "32 helices", "8192 array slots", "16384 declared nucleotides",
                       "128 strands", "512 conservative domain bound"],
            "identity": "Source-content namespace; replacement bytes invalidate output selections for explicit repair",
            "provenance": "reproduced_import; imported topology does not become native-only construction",
            "endpoint": "POST /api/design/features/import/cadnano",
            "requires": ["fresh empty active part", "expected_design_id", "expected_revision"],
            "transport": "Original application/json source bytes; bounded incremental read",
            "legacy": "Existing upload still supports ordinary document replacement",
        },
        "scadnano_contract": {
            "version": 1,
            "kinds": ["scadnano-import"],
            "source": "Pinned original UTF-8 scadnano JSON; no filesystem or network replay",
            "scope": "Explicit empty root; square/honeycomb lattice; at most one module scaffold",
            "limits": ["100 KB source", "32 helices", "8192 total helix span", "16384 declared nucleotides",
                       "128 strands", "512 conservative domain bound", "65536 domain/modification comparisons"],
            "identity": "Source-content namespace; changed bytes invalidate all output selections for explicit repair",
            "loss_policy": "existing-importer-v1: circular scaffolds are opened, empty helices skipped, warnings retained",
            "unsupported": ["helix transforms/groups", "opaque source fields", "chemical modifications",
                            "circular staples", "multiple-module clustering"],
            "provenance": "reproduced_import; imported topology does not become native-only construction",
            "endpoint": "POST /api/design/features/import/scadnano",
            "requires": ["fresh empty active part", "expected_design_id", "expected_revision"],
        },
        "dna_pdb_contract": {
            "version": 1,
            "kinds": ["dna-pdb-import"],
            "source": "Pinned original UTF-8 DNA PDB bytes; unchanged duplex/atom converter",
            "scope": "Explicit empty root; ordinary non-merge DNA import",
            "limits": ["200 KB source", "2000 atom records", "128 DNA residues", "8 DNA chains",
                       "3000 records", "256 characters per record", "8000 explicit bond declarations"],
            "identity": "Source-content namespace; changed bytes invalidate output selections",
            "loss_policy": "existing-duplex-projection-v1: non-DNA, unpaired and insufficient duplex residues are skipped; warnings retained",
            "atomistic": "Original atoms/bonds are reproducible display output; the existing transient import display is separate from authored duplex geometry",
            "unsupported": ["merge into existing helices", "MODEL containers", "alternate locations", "insertion codes", "ambiguous atom identities"],
            "provenance": "reproduced_import; imported geometry does not become native-only construction",
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
            "nanoparticle-fitting": "Existing fit, bound motion and one-to-four anchor relaxation; explicit selections and numerical pins; "
                + ("ordinary append enabled" if NP_FITTING_APPEND_ENABLED else "append rollout disabled pending qualification"),
            "nanoparticle-biotin-dna": "Pinned original coating/tether source and exact create/remove ownership; "
                + ("ordinary append enabled" if BIOTIN_APPEND_ENABLED else "append rollout disabled pending qualification"),
        },
        "generated_assets": {
            "enabled": GENERATED_ASSETS_ENABLED,
            "endpoint": "POST /api/design/generate-design",
            "operation": "generate",
            "fitting_version": 2,
            "teardown_version": 3,
            "scope": "Native generated DNA with two to four source-free gold particles, additive grafts and exact final anchors",
            "limits": ["12 anchors", "128 handles", "50000 bases", "existing 30,000-node/2 MB capture and 8 MB recovery bounds", "180-second worker deadline"],
            "publication": "Existing cancellable recipe worker; independent full source/candidate proof and one source-bound commit/undo",
            "history_ui": "Generated graft sequence/spacer and fit fixed-center intent; solved geometry remains output",
            "unsupported": ["coated/catalog particles", "imported residue geometry", "unrelated duplex/molecular ownership",
                            "individual nucleotide poses", "scientific mechanics", "experimental branched generation"],
        },
        "unverified_methods": {
            "legacy photoproduct-create:convert": "Receipts without an explicit native source and engine pins remain unverified",
        },
        "overhang_bulk_actions": sorted(ACTIONS),
        "assemblies": "deferred",
    }
