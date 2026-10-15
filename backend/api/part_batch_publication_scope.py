"""Measured full-source envelope for the first public registered batch host.

Pure batch evaluation remains broader. This host envelope accounts for the
complete live source retained by undo, including fields excluded from proof.
It grants no construction authority and does not execute feature builders.
"""

from backend.api.part_recovery_budget import retained_recovery_bytes
from backend.core.models import (
    ClusterCreateLogEntry, ClusterOpLogEntry, Design, MinorMutationLogEntry,
    RoutingClusterLogEntry, SnapshotLogEntry,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES


MAX_PUBLIC_HISTORY_ROWS = 64
_MINOR_KINDS = frozenset({"helix-add", "strand-add"})
_GOLD_KINDS = frozenset({"nanoparticle-create", "nanoparticle-patch", "nanoparticle-delete"})
_AUTHORING_FIELDS = frozenset({"helices", "strands", "cluster_transforms", "nanoparticles", "metadata", "lattice_type"})


def _reject(detail):
    raise CommandContractError(detail, code="unsupported_batch_publication_scope")


def _native_row(row):
    if type(row) in {MinorMutationLogEntry, SnapshotLogEntry} and type(row.params) is not dict:
        _reject("Batch publication requires typed native command inputs")
    if type(row) is MinorMutationLogEntry:
        known = row.op_subtype in _MINOR_KINDS and type(row.params.get("_proof_version")) is int and row.params["_proof_version"] == 1
    elif type(row) is SnapshotLogEntry:
        known = (row.op_kind in _GOLD_KINDS and type(row.params.get("_proof_version")) is int
                 and row.params["_proof_version"] == 1 and type(row.params.get("nanoparticle_version")) is int
                 and row.params["nanoparticle_version"] == 1
                 and not {"coating_version", "quantum_dot_version", "thiol_version"}.intersection(row.params))
    elif type(row) in {ClusterCreateLogEntry, ClusterOpLogEntry}:
        known = type(row.proof_version) is int and row.proof_version == 1
    else:
        known = False
    if not known:
        _reject("Batch publication initially admits only native helix/strand addition, gold and group/pose history")


def admit_batch_source(design, commands=()):
    """Caller owns the source lock; fixed lengths precede bounded traversal.

    Command parameters and current authoring are admitted by ordinary capture
    and validated by the existing worker. A matching envelope is not proof.
    """
    if type(design) is not Design or set(Design.model_fields) != set(FIELD_ROLES):
        _reject("Batch publication cannot classify this document schema")
    root = design.recipe_root
    if (root is None or root.version != 1 or root.kind != "empty"
            or root.source_json is not None or root.source_sha256 is not None):
        _reject("Batch publication initially requires an explicit empty recipe root")
    if design.feature_log_cursor != -1 or design.feature_log_sub_cursor is not None:
        _reject("Batch publication requires the complete current recipe")
    if design.input_sources or design.repair_draft is not None:
        _reject("Batch publication initially excludes imported source tables and pending repair proposals")
    baseline = Design()
    for name, role in FIELD_ROLES.items():
        if ((role == "authoring" and name not in _AUTHORING_FIELDS)
                or role == "physical" or (role == "presentation" and name != "annotations_enabled")):
            if getattr(design, name) != getattr(baseline, name):
                _reject(f"Batch publication initially requires default {name}")
    retained_recovery_bytes(design.feature_log, max_rows=MAX_PUBLIC_HISTORY_ROWS)
    rows = len(design.feature_log)
    for entry in design.feature_log:
        if type(entry) is RoutingClusterLogEntry:
            rows += len(entry.children)
            for child in entry.children:
                if type(child) is not MinorMutationLogEntry:
                    _reject("Batch publication requires ordinary minor routing children")
                _native_row(child)
        else:
            _native_row(entry)
    previous_minor = False
    for command in commands:
        minor = command.kind in _MINOR_KINDS
        rows += 1 + int(minor and not previous_minor)
        previous_minor = minor
    if rows > MAX_PUBLIC_HISTORY_ROWS:
        _reject("Batch publication initially admits at most 64 history rows including routing group headers")
