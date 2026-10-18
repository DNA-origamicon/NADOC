"""Convert pre-overhaul part history to a verified recipe (re-plan R2, option B).

Legacy rows carry no proof version, so none of them can be regenerated as is.
Conversion:

1. Upgrade each top-level row to its version-1 contract where the saved inputs
   are already complete (overlays such as Bend/Twist, unseeded snapshot kinds,
   routing children). Rows whose contract needs inputs legacy files never
   recorded (``history_seed`` for bundles, extrusions, auto-scaffold, autostaple,
   ...) stay non-replayable.
2. Place the boundary after the last non-replayable row. The saved state at that
   boundary becomes an explicit, user-visible *import* root; every later row is
   kept as an editable native command.
3. Accept only if replaying the root plus those rows reproduces the saved design
   exactly (``assess_part_history`` status ``reproduced_import``). Otherwise move
   the boundary later and retry; in the limit the whole current state becomes
   the import (nothing editable, but still exact).

Rows before the boundary are absorbed into the import and leave the feature log.
Recovery snapshots are used only as that explicit import input, never as proof:
the result is verified by replay. Nothing here reads or writes files.
"""

from dataclasses import dataclass, field

from backend.core.part_history_proof import command_rows, import_root
from backend.core.part_overlay_commands import KINDS as OVERLAY_KINDS


@dataclass
class ConversionResult:
    status: str                    # converted | already_native | refused
    design: object = None          # converted Design (None unless converted)
    boundary: int = 0              # index of the first retained (editable) row
    absorbed: int = 0              # legacy rows folded into the import root
    editable: list = field(default_factory=list)   # [(feature_type or op_kind, label)]
    attempts: int = 0
    frozen: int = 0                # retained rows replaying a frozen legacy routing result
    reason: str = ""

    def summary(self):
        return {"status": self.status, "boundary": self.boundary, "absorbed": self.absorbed,
                "editable": [kind for kind, _ in self.editable], "attempts": self.attempts,
                "frozen": self.frozen,
                "reason": self.reason}


def _upgrade(entry):
    """Version-1 copy of one top-level row; the contract check decides if it is replayable."""
    if entry.feature_type in OVERLAY_KINDS:
        return entry.model_copy(update={"proof_version": 1})
    if entry.feature_type == "routing-cluster":
        return entry.model_copy(update={"children": [
            child.model_copy(update={"params": {**child.params, "_proof_version": 1}})
            for child in entry.children]})
    if entry.feature_type == "snapshot":
        return entry.model_copy(update={"params": {**entry.params, "_proof_version": 1}})
    return entry


def _replayable(design, entry, dependencies):
    try:
        rows = list(command_rows(design.model_copy(update={"feature_log": [entry]}), 10_000))
    except (ValueError, KeyError, TypeError):
        return False
    return bool(rows) and all(dependencies(kind, params).known for _, kind, params in rows)


def _freeze(log, index, decode):
    """Frozen stand-in for an unreplayable deformation-independent legacy routing row."""
    from backend.core import part_frozen_topology as frozen
    from backend.core.part_replay_cache import DEFORMATION_INDEPENDENT

    entry = log[index]
    kind = getattr(entry, "op_kind", None)
    if entry.feature_type != "snapshot" or kind not in DEFORMATION_INDEPENDENT \
            or getattr(entry, "evicted", False) or not entry.post_state_gz_b64:
        return None
    pre = _pre_state(log, index, decode)
    try:
        post = decode(entry.post_state_gz_b64)
    except (ValueError, OSError):
        return None
    if pre is None:
        return None
    label = entry.label or kind
    return entry.model_copy(update={"label": f"{label} (frozen legacy result)",
                                    "params": frozen.params_for(pre, post, legacy_params=entry.params)})


def _pre_state(log, index, decode):
    """Saved authoring state immediately before row ``index``, or None."""
    entry = log[index]
    payload = None
    if entry.feature_type == "snapshot" and not getattr(entry, "pre_state_from_previous", False) \
            and not getattr(entry, "evicted", False):
        payload = entry.design_snapshot_gz_b64
    elif entry.feature_type == "routing-cluster" and not getattr(entry, "evicted", False):
        payload = entry.pre_state_gz_b64
    if not payload and index > 0:
        previous = log[index - 1]
        if previous.feature_type in {"snapshot", "routing-cluster"} and not getattr(previous, "evicted", False):
            payload = previous.post_state_gz_b64
    if not payload:
        return None
    try:
        return decode(payload)
    except (ValueError, OSError):
        return None


# Document-level settings that legacy files changed outside the command history
# (renames, Tm settings, saved dimensions). No geometry/topology command produces
# them, so the import baseline carries the saved file's final values.
DOCUMENT_FIELDS = ("metadata", "tm_settings", "dimensions")


def _later_state(log, index, decode, final):
    """Nearest saved state at or after row ``index`` (the final design if none)."""
    for later in range(index + 1, len(log) + 1):
        state = final if later == len(log) else _pre_state(log, later, decode)
        if state is not None:
            return state
    return final


def _with_implicit_default_clusters(state, later):
    """Legacy NADOC created default clusters lazily, without a history row.

    Add default clusters that the nearest later saved state has and this one lacks,
    leaving every existing cluster untouched. Returns None when nothing applies.
    """
    present = {cluster.id for cluster in state.cluster_transforms}
    missing = [c for c in later.cluster_transforms if c.id not in present and c.is_default]
    if not missing:
        return None
    return state.model_copy(update={"cluster_transforms": [*state.cluster_transforms,
                                                           *(c.model_copy(deep=True) for c in missing)]})


def _history_free(state, final):
    return state.model_copy(update={
        "feature_log": [], "feature_log_cursor": -1, "feature_log_sub_cursor": None,
        "recipe_root": None, "repair_draft": None,
        **{name: getattr(final, name) for name in DOCUMENT_FIELDS},
    })


def convert_legacy_history(design, *, execute, dependencies, decode, assess):
    """Return a ConversionResult; ``design`` itself is never modified."""
    if design.recipe_root is not None:
        return ConversionResult("already_native", reason="The part already has an explicit recipe root")
    if design.feature_log_cursor != -1 or design.feature_log_sub_cursor is not None:
        return ConversionResult("refused", reason="Return to the latest history position before converting")
    log = list(design.feature_log)
    upgraded = [_upgrade(entry) for entry in log]
    frozen_rows = 0
    for i, entry in enumerate(upgraded):
        if not _replayable(design, entry, dependencies):
            replacement = _freeze(log, i, decode)
            if replacement is not None:
                upgraded[i] = replacement
                frozen_rows += 1
    blocked = [i for i, entry in enumerate(upgraded) if not _replayable(design, entry, dependencies)]
    start = blocked[-1] + 1 if blocked else 0
    attempts = 0
    last_reason = ""
    for boundary in range(start, len(log) + 1):
        saved = design if boundary == len(log) else _pre_state(log, boundary, decode)
        if saved is None:
            continue
        baselines = [(saved, "")]
        if boundary < len(log):
            backfilled = _with_implicit_default_clusters(saved, _later_state(log, boundary, decode, design))
            if backfilled is not None:
                baselines.append((backfilled, "implicit default cluster added to the imported baseline"))
        for baseline, note in baselines:
            attempts += 1
            try:
                root = import_root(_history_free(baseline, design))
            except ValueError:  # includes pydantic validation of the import-size limit
                last_reason = "the imported baseline exceeds the 1 MB import-root size limit"
                continue
            candidate = design.model_copy(update={
                "recipe_root": root, "feature_log": upgraded[boundary:],
                "feature_log_cursor": -1, "feature_log_sub_cursor": None,
            })
            report = assess(candidate, execute=execute, dependencies=dependencies)
            if report["status"] != "reproduced_import":
                last_reason = "; ".join(i.get("code", "") for i in report.get("issues", [])) or report["status"]
                continue
            return ConversionResult(
                "converted", candidate, boundary=boundary, absorbed=boundary, attempts=attempts, reason=note,
                frozen=sum("_frozen_legacy" in (getattr(e, "params", None) or {}) for e in upgraded[boundary:]),
                editable=[(getattr(e, "op_kind", None) or e.feature_type, getattr(e, "label", "") or "")
                          for e in upgraded[boundary:]])
    return ConversionResult("refused", attempts=attempts,
                            reason=f"No exact baseline reproduced the saved part ({last_reason})")
