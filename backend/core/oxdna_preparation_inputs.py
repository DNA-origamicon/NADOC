"""Owned full archive for the bounded ordinary local DNA preparation profile.

No geometry, protocol defaults, feature proof, migration or file I/O occurs.
Reference filtering belongs after this independent exact copy.
"""

from copy import deepcopy
from math import isfinite
from time import monotonic

from pydantic import BaseModel

from backend.core import models as m
from backend.core.oxdna_preparation_schema import ENUM_TYPES, HISTORY_TYPES, SCHEMAS
from backend.core.part_capture_graph import CaptureLimit, CaptureShapeError, GraphBudget
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_recovery_storage import RECOVERY_PAYLOAD_FIELDS, retained_recovery_bytes


MAX_NODES = 30_000
MAX_BYTES = 2_000_000
CAPTURE_SECONDS = .025
MAX_HISTORY_ROWS = 2000
_MODEL_DEEPCOPY = BaseModel.__deepcopy__
_EMPTY_FAMILIES = (
    "cluster_join_constraints", "overhang_connections", "overhang_bindings", "connection_versions",
    "duplexes", "flexible_segment_marks", "flexible_connections", "protein_assets", "protein_attachments",
    "nanoparticles", "nanoparticle_conjugations", "nanoparticle_connection_versions", "extensions",
    "photoproduct_junctions",
)
_LIST_FIELDS = frozenset({
    "dimensions", "lattice_frames", "helices", "strands", "deformations", "cluster_transforms",
    "nucleotide_transforms", "cluster_joints", "overhangs", "staple_groups", "representation_overrides",
    "view_volumes", "annotations", "crossovers", "crossover_constraints", "forced_ligations",
    "camera_poses", "animations", "chain_sim_projects", "loadouts", "feature_log", *_EMPTY_FAMILIES,
})


class UnsupportedPreparation(CommandContractError):
    def __init__(self, detail):
        super().__init__(detail, code="oxdna_preparation_unsupported")


def _model_storage(value, fields):
    """Admit a fixed-size ordinary header before mapping/equality behavior."""
    data = value.__dict__
    if (type(data) is not dict or len(data) != len(fields)
            or any(type(key) is not str for key in data) or data.keys() != fields):
        raise CaptureShapeError(f"Preparation archive has an unreviewed {type(value).__name__} header")
    return data


def source_identity(source):
    """Bounded origin header only; the complete profile remains capture-owned.

    Use the currently declared model header here. A newly declared model field
    still reaches the positive archive schema's explicit unknown-profile gate.
    """
    if type(source) is not m.Design:
        raise CaptureShapeError("Preparation requires an ordinary mutable Design origin")
    identity = _model_storage(source, m.Design.model_fields.keys())["id"]
    if type(identity) is not str or not 1 <= len(identity) <= 1024:
        raise CaptureShapeError("Preparation requires a bounded nonempty design identity")
    return identity


def _shape(value):
    """Reject unowned hooks/state before any deepcopy can invoke them."""
    kind = type(value)
    if kind in {str, bool, type(None)} or kind in ENUM_TYPES:
        return
    if kind is int:
        if value.bit_length() <= 64:
            return
        raise CaptureShapeError("Preparation archive contains an unbounded integer")
    if kind is float:
        if isfinite(value):
            return
        raise CaptureShapeError("Preparation archive contains a nonfinite number")
    if kind in {dict, list, tuple}:
        if kind is dict:
            if any(type(key) is not str for key in value):
                raise CaptureShapeError("Preparation archive requires string mapping keys")
        return
    fields = SCHEMAS.get(kind)
    if fields is None:
        raise CaptureShapeError(f"Preparation archive has no copy contract for {kind.__name__}")
    _model_storage(value, fields)
    if (kind.model_fields.keys() != fields
            or value.__pydantic_extra__ is not None or value.__pydantic_private__ is not None
            or kind.__deepcopy__ is not _MODEL_DEEPCOPY
            or type(value.__pydantic_fields_set__) is not set
            or len(value.__pydantic_fields_set__) > len(fields)
            or any(type(name) is not str for name in value.__pydantic_fields_set__)
            or not value.__pydantic_fields_set__ <= fields):
        raise CaptureShapeError(f"Preparation archive has an unreviewed {kind.__name__} shape")
    if kind is m.Domain and value.binds_overhang_id is not None:
        raise CaptureShapeError("Owned DNA preparation has not reviewed bound overhang domains")
    if kind is m.ClusterRigidTransform and value.overhang_duplex_driver_id is not None:
        raise CaptureShapeError("Owned DNA preparation has not reviewed driven duplex poses")


def source_reason(design):
    """Cheap positive profile before copying; None does not certify validity."""
    if type(design) is not m.Design:
        return "Owned preparation requires an ordinary mutable Design"
    if (set(FIELD_ROLES) != SCHEMAS[m.Design]
            or any(model.model_fields.keys() != fields for model, fields in SCHEMAS.items())):
        return "Preparation archive has an unreviewed document or nested model schema"
    try:
        _shape(design)
    except CaptureShapeError as error:
        return str(error)
    if design.group_organization is not None:
        return "Owned DNA preparation has not reviewed separate group organization"
    for name in _LIST_FIELDS:
        value = getattr(design, name)
        if type(value) is not list:
            return f"Preparation archive requires an ordinary {name} list"
    for name in _EMPTY_FAMILIES:
        if getattr(design, name):
            return f"Owned DNA preparation has not reviewed {name}"
    if design.atomistic_reference is not None:
        return "Owned DNA preparation has not reviewed atomistic_reference"
    # Refuse impossible-sized inputs before scanning producer records. The
    # shared walker later counts every field, nested value and repeated alias.
    if len(design.helices) + len(design.strands) + len(design.overhangs) > MAX_NODES:
        raise CaptureLimit("Preparation source exceeds its node allowance")
    for helix in design.helices:
        if type(helix) is not m.Helix:
            return "Preparation requires ordinary helix records"
        if type(helix.id) is not str or type(helix.native_residues) is not list:
            return "Preparation requires ordinary helix identity and residue fields"
        if helix.native_source is not None or helix.native_residues or helix.id.startswith(("__lnk__", "__np__")):
            return "Owned DNA preparation has not reviewed imported or auxiliary residue geometry"
    for strand in design.strands:
        if (type(strand) is not m.Strand or type(strand.strand_type) not in {str, m.StrandType}
                or strand.strand_type not in {m.StrandType.SCAFFOLD, m.StrandType.STAPLE}):
            return "Owned DNA preparation has not reviewed binder/linker strands"
    for overhang in design.overhangs:
        if type(overhang) is not m.OverhangSpec:
            return "Owned DNA preparation requires ordinary unbound overhangs"
        if (type(overhang.auxiliary_endpoint) is not bool or overhang.auxiliary_endpoint
                or (overhang.strand_anim_setup is not None
                    and (type(overhang.strand_anim_setup) is not dict or len(overhang.strand_anim_setup)))):
            return "Owned DNA preparation requires ordinary unbound overhangs"
    return None


def _charge_history(rows, budget):
    """Separate only known top-level recovery strings; preserve every other value.

    Header dictionaries are temporary accounting views, never replacement
    records. Admit each bounded row before allocating the next one's view.
    """
    if len(rows) > MAX_HISTORY_ROWS:
        raise CaptureLimit("Retained history exceeds its publication row allowance")
    count = len(rows)
    budget.charge([], validate=_shape, reject_cycles=True)
    for row in rows:
        if type(row) not in HISTORY_TYPES:
            raise CaptureShapeError("Preparation archive has an unreviewed history record")
        _shape(row)
        header = {name: value for name, value in row.__dict__.items() if name not in RECOVERY_PAYLOAD_FIELDS}
        if type(row) is m.RoutingClusterLogEntry:
            if type(row.children) is not list:
                raise CaptureShapeError("Preparation archive requires ordinary routing child records")
            count += len(row.children)
            if count > MAX_HISTORY_ROWS:
                raise CaptureLimit("Retained history exceeds its publication row allowance")
            header["children"] = []
            budget.charge(header, validate=_shape, reject_cycles=True)
            for child in row.children:
                if type(child) is not m.MinorMutationLogEntry:
                    raise CaptureShapeError("Preparation archive requires ordinary routing child records")
                _shape(child)
                child_header = {name: value for name, value in child.__dict__.items()
                                if name not in RECOVERY_PAYLOAD_FIELDS}
                budget.charge(child_header, validate=_shape, reject_cycles=True)
        else:
            budget.charge(header, validate=_shape, reject_cycles=True)
        budget.finish()
    # Structural checks above precede this existing storage helper's __dict__
    # reads. Payload lengths are counted as stored, never decoded or copied.
    retained_recovery_bytes(rows, max_rows=MAX_HISTORY_ROWS)
    budget.finish()


def capture_archive(source):
    """Caller owns the source lock. Return one full independent model or refuse."""
    budget = GraphBudget(max_nodes=MAX_NODES, max_bytes=MAX_BYTES, seconds=CAPTURE_SECONDS, clock=monotonic)
    try:
        reason = source_reason(source)
        if reason:
            raise UnsupportedPreparation(reason)
        budget.finish()
        _charge_history(source.feature_log, budget)
        # Charge all archival fields, unlike proof's authoring-only projection.
        # Encoded feature recovery alone has its separate fixed storage budget.
        for name in m.Design.model_fields:
            if name != "feature_log":
                budget.charge(getattr(source, name), validate=_shape, reject_cycles=True)
        budget.finish()
        copied = deepcopy(source)
        budget.finish()
        return copied
    except CaptureLimit as error:
        raise CommandContractError(str(error), code="oxdna_input_capture_limit") from error
    except CaptureShapeError as error:
        raise UnsupportedPreparation(str(error)) from error
