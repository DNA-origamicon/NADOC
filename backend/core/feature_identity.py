"""Explicit deterministic IDs for audited feature builders; no global UUID patch."""
import json
from uuid import UUID, uuid5


def identity_factory(seed):
    namespace = UUID(str(seed))

    def identifier(kind, members):
        key = json.dumps([kind, sorted(members)], separators=(",", ":"))
        return str(uuid5(namespace, key))
    return identifier


def preserve_proof_identity(previous, updated, *, kind=None):
    """Parameter edits retain the authored identity namespace and contract."""
    keys = ("_generated_scope", "binding_id", "created_at", "conn_id", "_sub_domain_id", "_scaffold_id", "_staple_id", "_source_helix_ids", "_fl_id", "bridge_identity_seed", "history_seed", "sweep_id", "crossover_id", "_helix_id", "_strand_id", "_proof_version")
    # Output identities survive parameter edits. A consumer's reference (such
    # as the constraint selected for deletion) remains an editable input.
    keys += {"fork-path": ("deformation_id",), "connectivity-path": ("deformation_id",),
             "joined-crossbar-path": ("deformation_id",),
             "photoproduct-create": ("conversion_version", "template", "engine"),
             "photoproduct-relax": ("conversion_version", "template", "engine"),
             "nanoparticle-create": ("nanoparticle_id", "nanoparticle_version", "quantum_dot_version"),
             "nanoparticle-patch": ("nanoparticle_version", "quantum_dot_version", "coating_version", "importer_version", "engine"),
             "nanoparticle-delete": ("nanoparticle_version", "quantum_dot_version"),
             "nanoparticle-conjugate": ("conjugation_id", "thiol_version"),
             "nanoparticle-conjugation-delete": ("thiol_version",),
             "protein-import": ("asset_id", "protein_version", "importer_version"),
             "protein-conjugate": ("attachment_id", "binder_strand_id", "group_id",
                                   "protein_version", "conjugation_version", "operation_id"),
             "protein-attach": ("attachment_id", "protein_version"),
             "protein-attach-patch": ("protein_version", "conjugation_version"),
             "protein-attach-delete": ("protein_version", "conjugation_version"),
             "element-paste": ("copy_version", "protein_output_ids", "nanoparticle_output_ids"),
             "duplex-relax": ("relaxation_version", "engine"),
             "duplex-sync-bindings": ("duplex_ids",),
             "duplex-create": ("duplex_id",),
             "duplex-connect": ("duplex_id",),
             "crossover-constraint-create": ("constraint_id",)}.get(kind, ())
    return {**updated, **{key: previous[key] for key in keys if key in previous}}
