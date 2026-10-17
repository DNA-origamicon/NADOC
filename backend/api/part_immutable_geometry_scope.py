"""Private native snapshot geometry storage scope; no evaluation or publication authority.

Shares the existing bounded document envelope. A known recipe shape is not proof
that its materialized authoring can be regenerated. Hosts must prove that later.
"""

from backend.api.part_batch_publication_scope import _admit_source
from backend.api.part_geometry_inputs import KINDS
from uuid import UUID
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_overlay_commands import proof_version_supported


# Retain the existing private wire/storage label: this additive catalog keeps
# old extrusion bytes valid; the label is neither proof nor public authority.
SCOPE = "native_extrusion_v1"
_FIELDS = frozenset({"dimensions", "lattice_frames", "helices", "strands", "lattice_type",
    "metadata", "cluster_transforms", "overhangs", "crossovers", "deformations"})


def _row(entry):
    if type(entry) is SnapshotLogEntry:
        params = entry.params
        known = (entry.op_kind in KINDS and type(params) is dict
            and type(params.get("_proof_version")) is int and params["_proof_version"] == 1
            and "_generated_scope" not in params and "_generator" not in params)
        if known and entry.op_kind == "sweep":
            # Storage admission stays cheap: no editor/schema imports inside
            # the worker's capture budget. Native evaluation proves semantics.
            known = type(params.get("sweep_id")) is str
            if known:
                try:
                    UUID(params["sweep_id"])
                except ValueError:
                    known = False
    else:
        known = (type(entry) in {ClusterCreateLogEntry, ClusterOpLogEntry}
            and proof_version_supported(entry.feature_type, entry.proof_version))
    if not known:
        raise CommandContractError("Private extrusion storage requires reviewed native extrusion/placement history",
                                   code="unsupported_geometry_storage_scope")


def admit_source(design):
    try:
        _admit_source(design, (), authoring_fields=_FIELDS, row_check=_row)
    except CommandContractError as error:
        raise CommandContractError(str(error).replace("Batch publication", "Geometry storage"),
                                   code="unsupported_geometry_storage_scope") from error
