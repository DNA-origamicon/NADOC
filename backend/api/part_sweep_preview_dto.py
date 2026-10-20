"""Closed native Sweep display and fixed-prefix controls; no live state access."""

from copy import deepcopy
from uuid import UUID

from backend.api.part_deformation_preview_dto import _admit, _bounded, _envelope, _native, _validated_panes
from backend.api.part_sweep_preview import EvaluatedSweep, SweepGuides, normalize
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError


PROJECTION_VERSION = 1
_HELIX_FIELDS = {"id", "label", "grid_pos", "lattice_frame_id", "bp_start", "length_bp", "axis_start", "axis_end"}


def _reject(detail):
    raise CommandContractError(detail, code="invalid_preview_definition")


def _inputs(prefix, evaluated):
    if type(prefix) is not Design or type(evaluated) not in {EvaluatedSweep, SweepGuides}:
        _reject("Sweep display requires owned prefix and evaluation values")
    _admit(prefix)
    if type(evaluated) is EvaluatedSweep:
        _admit(evaluated.design)
    entry = evaluated.entry
    if type(entry) is not SnapshotLogEntry or entry.op_kind != "sweep":
        _reject("Sweep display requires its selected native snapshot")
    params = normalize(evaluated.params, {})
    identity = "sweep_" + str(UUID(params["sweep_id"]))
    matches = (evaluated.design_id == prefix.id and evaluated.deformation_id == identity
               if type(evaluated) is SweepGuides else
               prefix.id == evaluated.design.id and bool(evaluated.design.deformations)
               and evaluated.design.deformations[-1].id == identity
               and evaluated.design.deformations[-1].type == "sweep")
    if (params != entry.params or not matches
            or any(op.id == identity for op in prefix.deformations)):
        _reject("Sweep display does not match its selected feature-stage operation")
    if evaluated.stage != "feature" or evaluated.source_equivalence_checked or evaluated.downstream_evaluated:
        _reject("Sweep preview cannot assert source or downstream proof")
    return params


def _base(evaluated):
    return {"projection_version": PROJECTION_VERSION, "stage": "feature",
            "source_equivalence_checked": False, "downstream_evaluated": False,
            "physical_validity": False, "sweep_preview": deepcopy(evaluated.sweep)}


def prepare_display(prefix, evaluated, *, envelope=None):
    from backend.core.part_dna_comparison import project_for_deformation_preview

    envelope = _envelope(envelope)
    params = _inputs(prefix, evaluated)
    result = {**_base(evaluated), "control_context": {
        "inputs": params,
        "lattice_type": prefix.lattice_type.value,
        "helices": [helix.model_dump(mode="json", include=_HELIX_FIELDS) for helix in prefix.helices],
        "lattice_frames": [frame.model_dump(mode="json") for frame in prefix.lattice_frames],
    }, "before": _native(project_for_deformation_preview, prefix),
        "candidate": None}
    result.update(envelope)
    return _bounded(result, trusted=_validated_panes(result))


def evaluate_display(prefix, evaluated, *, include_geometry=True, envelope=None):
    if type(include_geometry) is not bool:
        _reject("Sweep geometry choice must be a boolean")
    envelope = _envelope(envelope)
    _inputs(prefix, evaluated)
    # Sweep edits display their native path, nodes and cross-sections. Full DNA
    # is regenerated and validated by Apply, not projected for each draft update.
    result = {**_base(evaluated), "candidate": None}
    result.update(envelope)
    return _bounded(result, trusted=_validated_panes(result))
