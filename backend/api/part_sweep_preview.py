"""Bounded, owned feature-stage Sweep evaluation from native command inputs.

No live document, recovery decoding or publication authority enters this module.
The prefix is rebuilt once; each evaluation executes only the selected native
Sweep against an independent prefix copy. Apply must separately prove/rebuild
the full recipe. Native spline, attachment and loop/skip algorithms are unchanged.
"""

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from uuid import UUID

from backend.api.part_deformation_preview import (
    _admit, _checkpoint, _identity, _json, _prefix_rows, _replay_prefix, _run,
)
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.sweep import SweepRequest, sweep_preview
from backend.core.validator import ValidationReport, validate_design


_PROTECTED = frozenset({"sweep_id", "_proof_version", "expected_design_id", "expected_revision"})
EDIT_FIELDS = frozenset(SweepRequest.model_fields) - _PROTECTED
_FIELDS = EDIT_FIELDS | _PROTECTED


def _reject(detail, code="invalid_preview_definition"):
    raise CommandContractError(detail, code=code)


def _vectors(value, *, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not list or not 2 <= len(value) <= 256:
        _reject("Sweep requires 2–256 bounded point or orientation entries")
    for item in value:
        if nullable and item is None:
            continue
        if (type(item) is not list or len(item) != 3
                or any(type(number) not in {int, float} or not isfinite(number) for number in item)):
            _reject("Sweep coordinates and orientations require finite numeric triples")


def normalize(previous, patch):
    """Own complete editable inputs without inventing identity or dropping fields."""
    if type(previous) is not dict or type(patch) is not dict:
        _reject("Sweep inputs and patch must be JSON objects")
    _json(previous)
    _json(patch)
    if set(previous) - _FIELDS or set(patch) - _FIELDS:
        _reject("Ordinary Sweep preview requires known, non-generated inputs", "unsupported_preview_scope")
    if type(previous.get("_proof_version")) is not int or previous["_proof_version"] != 1:
        _reject("Sweep preview requires native proof version 1", "missing_proof_contract")
    identity = previous.get("sweep_id")
    if type(identity) is not str:
        _reject("Sweep preview requires its saved stable UUID")
    try:
        UUID(identity)
    except (ValueError, TypeError, AttributeError) as error:
        _reject(f"Invalid saved Sweep identity: {error}")
    for key in _PROTECTED & patch.keys():
        if key not in previous or type(patch[key]) is not type(previous[key]) or patch[key] != previous[key]:
            _reject(f"Sweep history identity and transport fields cannot be edited: {key}")
    values = deepcopy({**previous, **patch})
    for key in ("ligate_adjacent", "detach_source"):
        if key in values and type(values[key]) is not bool:
            _reject(f"{key} must be a boolean")
    cells = values.get("cells")
    if (type(cells) is not list or not cells
            or any(type(cell) is not list or len(cell) != 2
                   or any(type(number) is not int for number in cell) for cell in cells)):
        _reject("Sweep cells require a nonempty list of integer pairs")
    _vectors(values.get("points_nm"))
    _vectors(values.get("orientations_deg"), nullable=True)
    source = values.get("source_helix_id")
    if source is not None and (type(source) is not str or not 1 <= len(source) <= 256):
        _reject("Sweep source helix must be a bounded nonempty identity or null")
    try:
        normalized = SweepRequest.model_validate(values).model_dump(mode="json")
    except (ValueError, TypeError) as error:
        _reject(str(error))
    # Schema defaults belong to authored inputs. Protected slots retain their
    # exact saved representation/presence, never a freshly minted expectation.
    for key in _PROTECTED:
        if key in previous:
            normalized[key] = deepcopy(previous[key])
        else:
            normalized.pop(key, None)
    _json(normalized)
    return normalized


@dataclass(frozen=True, slots=True)
class PreparedSweep:
    feature_id: str
    deformation_id: str
    design_id: str
    _prefix: Design
    _entry: SnapshotLogEntry

    def copy_prefix(self):
        return self._prefix.model_copy(deep=True)


@dataclass(frozen=True, slots=True)
class EvaluatedSweep:
    design: Design
    entry: SnapshotLogEntry
    params: dict
    sweep: dict
    validation: ValidationReport
    stage: str = "feature"
    source_equivalence_checked: bool = False
    downstream_evaluated: bool = False


def _source(prefix, params):
    identity = params.get("source_helix_id")
    if identity is None:
        return
    matches = sum(helix.id == identity for helix in prefix.helices)
    if matches != 1:
        raise ReferenceResolutionError("Selected Sweep source helix is missing or ambiguous",
            code="missing_reference" if matches == 0 else "invalid_selection",
            references=[{"kind": "helix", "identity": identity, "parameter_path": ["source_helix_id"]}])


def prepare_from_capture(captured, feature_id):
    """Prepare the fixed native prefix; suffix coverage is checked, not executed."""
    check = _checkpoint()
    feature_id = _identity(feature_id)
    rows, entries = _prefix_rows(captured, check)
    selected = entries.get(feature_id)
    if selected is None:
        raise ReferenceResolutionError("Selected Sweep feature no longer exists", references=[
            {"kind": "feature", "identity": feature_id, "parameter_path": ["feature_id"]}])
    if type(selected) is not SnapshotLogEntry or selected.op_kind != "sweep":
        _reject("Select an ordinary top-level native Sweep snapshot", "unsupported_preview_scope")
    params = normalize(selected.params, {})
    current = _replay_prefix(captured, rows, check, stop=feature_id)
    _admit(current, check)
    _source(current, params)
    deformation_id = "sweep_" + str(UUID(params["sweep_id"]))
    if any(op.id == deformation_id for op in current.deformations):
        _reject("The selected Sweep operation identity already exists in its prefix")
    entry = selected.model_copy(deep=True, update={"params": params})
    check()
    return PreparedSweep(feature_id, deformation_id, captured.id, current, entry)


def evaluate(prepared, patch):
    """Evaluate one complete selected command; never reuse its mutable output."""
    if type(prepared) is not PreparedSweep:
        _reject("Sweep evaluation requires an owned prepared prefix")
    check = _checkpoint()
    params = normalize(prepared._entry.params, patch)
    prefix = prepared.copy_prefix()
    _source(prefix, params)
    # The shared pipeline performs prospective bounds before native allocation,
    # then organization lineage, placement reconciliation and ligation retry.
    candidate = _run("sweep", prefix, params, check)
    try:
        # Controls use the same unmodified feature-stage source, independently
        # owned even if a native builder changed its disposable input graph.
        metadata, _ = sweep_preview(prepared.copy_prefix(), SweepRequest.model_validate(params),
                                    include_geometry=True)
        validation = validate_design(candidate)
    except CommandContractError:
        raise
    except (ValueError, TypeError, KeyError) as error:
        _reject(str(error))
    entry = prepared._entry.model_copy(deep=True, update={"params": deepcopy(params)})
    check()
    return EvaluatedSweep(candidate, entry, params, metadata, validation)
