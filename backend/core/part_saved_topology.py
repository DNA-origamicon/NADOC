"""Typed ownership of native binding/duplex restoration state.

These records are derived by binding_relax, never accepted as command inputs.
Saved definitions can be absent from the live model after relocation; current
owners and external references must still resolve. No geometry is recomputed.
"""

from dataclasses import dataclass

from backend.core import models
from backend.core.part_command_errors import ReferenceResolutionError


MAX_SAVED_CROSSOVERS = 4_096
_REQUIRED = frozenset({"driver_oh_id", "driven_oh_id", "driven_helix", "strand_id",
                       "domain_index", "prior_domain", "prior_ovhg_helix_id", "crossovers"})


def _unsupported(detail):
    raise NotImplementedError(f"Unsupported saved binding topology: {detail}")


def _model(model, value):
    if not isinstance(value, dict) or set(value) != set(model.model_fields):
        _unsupported(f"incomplete or unknown {model.__name__} fields")
    try:
        parsed = model.model_validate(value)
    except ValueError as error:
        raise NotImplementedError(f"Malformed saved {model.__name__}") from error
    # Also reject unknown nested fields rather than allowing model validation
    # to silently discard them. Native model_dump(json) is the source format.
    if parsed.model_dump(mode="json") != value:
        _unsupported(f"noncanonical {model.__name__} definition")
    return parsed


@dataclass(frozen=True)
class SavedTopology:
    value: dict
    helix: models.Helix
    crossovers: tuple[models.Crossover, ...]
    ligation: models.ForcedLigation | None

    def definitions(self):
        yield ("helix", self.helix.id), self.helix
        for crossover in self.crossovers:
            yield ("crossover", crossover.id), crossover
        if self.ligation is not None:
            yield ("forced_ligation", self.ligation.id), self.ligation


def snapshot_for(owner):
    if not isinstance(owner, (models.OverhangBinding, models.Duplex)):
        return None
    value = owner.prior_driven_topology
    if not value:
        return None
    if not isinstance(value, dict) or set(value) not in (_REQUIRED, _REQUIRED | {"forced_ligation"}):
        _unsupported("incomplete or unknown snapshot fields")
    for field in ("driver_oh_id", "driven_oh_id", "strand_id", "prior_ovhg_helix_id"):
        if not isinstance(value[field], str) or not value[field]:
            _unsupported(f"invalid {field}")
    if type(value["domain_index"]) is not int or value["domain_index"] < 0:
        _unsupported("invalid domain_index")
    pair = ({owner.overhang_a_id, owner.overhang_b_id}
            if isinstance(owner, models.OverhangBinding)
            else {owner.left.overhang_id, owner.right.overhang_id})
    if len(pair) != 2 or pair != {value["driver_oh_id"], value["driven_oh_id"]}:
        _unsupported("saved endpoints disagree with their owner")
    helix = _model(models.Helix, value["driven_helix"])
    prior = value["prior_domain"]
    if not isinstance(prior, dict) or set(prior) != {"helix_id", "start_bp", "end_bp", "direction"}:
        _unsupported("incomplete or unknown prior domain")
    if (prior["helix_id"] != helix.id or value["prior_ovhg_helix_id"] != helix.id
            or type(prior["start_bp"]) is not int or type(prior["end_bp"]) is not int
            or prior["direction"] not in {item.value for item in models.Direction}):
        _unsupported("inconsistent saved helix/domain identity")
    crossovers = value["crossovers"]
    if not isinstance(crossovers, list) or len(crossovers) > MAX_SAVED_CROSSOVERS:
        _unsupported("saved crossover budget exceeded")
    crossovers = tuple(_model(models.Crossover, item) for item in crossovers)
    if len({item.id for item in crossovers}) != len(crossovers):
        _unsupported("duplicate saved crossover identities")
    ligation = (_model(models.ForcedLigation, value["forced_ligation"])
                if "forced_ligation" in value else None)
    return SavedTopology(value, helix, crossovers, ligation)


def validate_owner(snapshot, live_records):
    """Check current owners separately from restorable historical definitions."""
    value = snapshot.value

    def current(kind, identity):
        result = live_records.get((kind, identity))
        if result is None:
            raise ReferenceResolutionError("Saved binding topology lost its current owner",
                references=[{"kind": kind, "identity": identity,
                             "parameter_path": ["_generated_scope", "input_ids"]}])
        return result

    current("overhang", value["driver_oh_id"])
    driven = current("overhang", value["driven_oh_id"])
    strand = current("strand", value["strand_id"])
    index = value["domain_index"]
    if (driven.strand_id != strand.id or index >= len(strand.domains)
            or strand.domains[index].overhang_id != driven.id
            or strand.domains[index].helix_id != driven.helix_id):
        raise ReferenceResolutionError("Saved binding topology has a different strand/domain owner",
            code="invalid_selection", references=[{
                "kind": "overhang", "identity": driven.id,
                "parameter_path": ["_generated_scope", "input_ids"],
            }])


def remap_snapshot(snapshot, current, historical, mapped_model):
    """Rewrite only explicit identities; preserve saved geometry and text."""
    value = snapshot.value
    result = dict(value)
    for field in ("driver_oh_id", "driven_oh_id"):
        result[field] = current("overhang", value[field])
    result["strand_id"] = current("strand", value["strand_id"])
    result["driven_helix"] = mapped_model(snapshot.helix, historical)
    result["prior_ovhg_helix_id"] = historical("helix", value["prior_ovhg_helix_id"])
    result["prior_domain"] = {**value["prior_domain"],
        "helix_id": historical("helix", value["prior_domain"]["helix_id"])}
    result["crossovers"] = [mapped_model(item, historical) for item in snapshot.crossovers]
    if snapshot.ligation is not None:
        result["forced_ligation"] = mapped_model(snapshot.ligation, historical)
    return result
