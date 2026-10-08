"""Compose generated construction into the ordinary feature timeline.

New runs emit native operations with snapshots or replayable deltas. Legacy v1
histories retain their isolated dependent-rebuild path for parameter edits.
"""

from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import uuid
import math

from fastapi import HTTPException
from backend.api import state
from backend.core.models import Design, SnapshotLogEntry


def _ids(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "id" and isinstance(child, str):
                yield child
            else:
                yield from _ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _ids(child)


class _StopRecording(Exception):
    """The requested surviving history prefix is complete."""


class GeneratedHistory:
    def __init__(
        self,
        source,
        settings,
        *,
        group_id=None,
        overrides=None,
        entry_ids=None,
        stop_key=None,
        standard=True,
    ):
        self.standard = standard
        self.design = source.model_copy(deep=True)
        self.settings = settings.model_dump()
        self.group_id = group_id or str(uuid.uuid4())
        self.overrides = deepcopy(overrides or {})
        self.entry_ids = entry_ids or {}
        self.stop_key = stop_key
        # Only imported particle-owned objects keep their IDs. New bundles can
        # occupy the same lattice cells as existing DNA without replacing it.
        self.source_ids = {p.id for p in source.nanoparticles}
        owned_strands = set()
        for c in source.nanoparticle_conjugations:
            self.source_ids.add(c.id)
            for r in c.surface_strands:
                self.source_ids.update((r.strand_id, r.helix_id, r.overhang_id))
                owned_strands.add(r.strand_id)
        self.source_ids.update(
            g.id
            for g in source.staple_groups
            if owned_strands.intersection(g.strand_ids)
        )
        for spec in source.overhangs:
            if spec.strand_id in owned_strands:
                self.source_ids.update(_ids(spec.model_dump()))
        self.renames = {}
        self.seen = set()

    def params(self, key, defaults, editable=()):
        patch = self.overrides.get(key, {})
        unknown = set(patch) - set(editable)
        if unknown:
            raise ValueError(
                f"Unsupported parameters for {key}: {', '.join(sorted(unknown))}"
            )
        for name, value in patch.items():
            if name in ("sequence", "scaffold_name", "path_order", "pathing"):
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be text.")
            elif (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite number.")
            elif name in ("bp_index", "length_bp") and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer.")
        return {**defaults, **patch}

    def _map(self, value):
        if isinstance(value, str):
            return self.renames.get(value, value)
        if isinstance(value, list):
            return [self._map(x) for x in value]
        if isinstance(value, dict):
            return {k: self._map(v) for k, v in value.items()}
        return value

    def record(
        self, before, after, kind, label, params, key, editable=(), *, scoped=True
    ):
        self.seen.add(key)
        if scoped:
            # Existing NP/handle IDs keep their identity. New DNA gets its own
            # namespace, including when an existing rod uses the same grid cells.
            for identifier in _ids(
                after.model_dump(exclude={"feature_log", "loadouts"})
            ):
                if identifier not in self.source_ids:
                    prefix = "__np__" if identifier.startswith("__np__") else ""
                    self.renames.setdefault(
                        identifier, f"{prefix}gen_{self.group_id}_{identifier}"
                    )
            old = self._map(before.model_dump(exclude={"feature_log", "loadouts"}))
            new = self._map(after.model_dump(exclude={"feature_log", "loadouts"}))
            merged = self.design.model_dump()
            for field, values in new.items():
                prior = old[field]
                if values == prior or not isinstance(values, list):
                    continue
                if not all(
                    isinstance(v, dict) and "id" in v for v in [*values, *prior]
                ):
                    raise ValueError(f"Cannot compose generated field {field}.")
                before_by_id = {v["id"]: v for v in prior}
                after_by_id = {v["id"]: v for v in values}
                removed = set(before_by_id) - set(after_by_id)
                changed = {
                    i: v for i, v in after_by_id.items() if before_by_id.get(i) != v
                }
                if field == "staple_groups":
                    for previous in merged[field]:
                        if previous["id"] in changed:
                            changed[previous["id"]]["strand_ids"] = list(
                                dict.fromkeys(
                                    [
                                        *previous["strand_ids"],
                                        *changed[previous["id"]]["strand_ids"],
                                    ]
                                )
                            )
                current_ids = {v["id"] for v in merged[field]}
                merged[field] = [
                    changed.get(v["id"], v)
                    for v in merged[field]
                    if v["id"] not in removed
                ]
                merged[field] += [v for i, v in changed.items() if i not in current_ids]
            updated = Design.model_validate(merged)
        else:
            updated = after.copy_with(
                feature_log=self.design.feature_log,
                loadouts=self.design.loadouts,
                active_loadout_id=self.design.active_loadout_id,
                last_editable_loadout_id=self.design.last_editable_loadout_id,
            )
        if self.standard and updated == self.design:
            return
        pre, pre_size = state.encode_design_snapshot(self.design)
        post, post_size = state.encode_design_snapshot(updated)
        pre_clusters = {c.id: c for c in self.design.cluster_transforms}
        post_clusters = {c.id: c for c in updated.cluster_transforms}
        touched_clusters = sorted(
            i
            for i in pre_clusters.keys() | post_clusters.keys()
            if pre_clusters.get(i) != post_clusters.get(i)
        )
        entry = SnapshotLogEntry(
            id=self.entry_ids.get(key, str(uuid.uuid4())),
            op_kind=kind,
            label=label,
            timestamp=datetime.now(timezone.utc).isoformat(),
            params={
                **params,
                "_generator": {
                    "version": 1,
                    "group_id": self.group_id,
                    "key": key,
                    "settings": self.settings,
                    "overrides": self.overrides,
                    "editable": list(editable),
                    "cluster_ids": touched_clusters,
                },
            },
            design_snapshot_gz_b64=pre,
            snapshot_size_bytes=pre_size,
            post_state_gz_b64=post,
            post_state_size_bytes=post_size,
        )
        entries = [entry]
        if self.standard:
            from backend.api.generated_commands import ordinary_entries
            entry.params = self._map(entry.params)
            entries = ordinary_entries(self.design, updated, entry, key)
        self.design = updated.copy_with(
            feature_log=[*self.design.feature_log, *entries],
            feature_log_cursor=-1,
            feature_log_sub_cursor=None,
        )

        if key == self.stop_key:
            raise _StopRecording()


def build_recorded(
    source,
    candidate,
    settings,
    *,
    group_id=None,
    overrides=None,
    entry_ids=None,
    stop_key=None,
    standard=True,
):
    from backend.api.two_np_build import materialize
    from backend.api.routes_nanoparticles import _set_np_version_applied
    from backend.core.duplex_cluster import (
        dematerialize_duplex_cluster,
        duplex_cluster_for,
    )

    history = GeneratedHistory(
        source,
        settings,
        group_id=group_id,
        overrides=overrides,
        entry_ids=entry_ids,
        stop_key=stop_key,
        standard=standard,
    )
    prepared = source.model_copy(deep=True)
    particle_ids = {p.id for p in source.nanoparticles if p.kind == "gold_nanosphere"}
    try:
        for v in list(prepared.nanoparticle_connection_versions):
            if v.applied and v.nanoparticle_id in particle_ids:
                before = prepared
                cluster = duplex_cluster_for(prepared, v.overhang_id)
                if cluster:
                    prepared = dematerialize_duplex_cluster(prepared, v.overhang_id)
                prepared = _set_np_version_applied(prepared, v.id, False)
                history.record(
                    before,
                    prepared,
                    "nanoparticle-connection-version-patch",
                    "Detach previous nanoparticle connection",
                    {"version_id": v.id, "applied": False},
                    f"detach:{v.id}",
                    scoped=False,
                )
        _, report = materialize(prepared, candidate, settings, history=history)
    except _StopRecording:
        report = {}
    if stop_key and stop_key not in history.seen:
        raise ValueError(
            "The last retained construction step no longer exists after this edit. "
            "Revert to an earlier step before changing these parameters."
        )
    required = (
        set(history.overrides) & set(entry_ids)
        if stop_key and entry_ids
        else set(history.overrides)
    )
    missing = required - history.seen
    if missing:
        raise ValueError(
            f"Edited steps are no longer reachable: {', '.join(sorted(missing))}"
        )
    return history.design, history._map(report)


def edit_generated_feature(index, params):
    from backend.core.two_np_generator import GeneratorSettings
    from backend.core.platform_generator import plan_generated
    from backend.core.validator import validate_design
    from backend.api.crud import _design_response_with_geometry

    current, revision = state.copy_for_persist()
    entry = current.feature_log[index]
    meta = entry.params["_generator"]
    group = meta["group_id"]
    indices = [
        i
        for i, e in enumerate(current.feature_log)
        if getattr(e, "params", {}).get("_generator", {}).get("group_id") == group
    ]
    start, end = min(indices), max(indices)
    if indices != list(range(start, end + 1)) or end != len(current.feature_log) - 1:
        raise HTTPException(
            409,
            detail="Later manual features depend on this generated run. Revert those later features before editing it.",
        )
    allowed = meta["editable"]
    patch = {k: v for k, v in params.items() if k in allowed}
    invalid = set(params) - set(allowed)
    if invalid:
        raise HTTPException(
            422, detail=f"Unsupported editable parameters: {', '.join(sorted(invalid))}"
        )
    overrides = deepcopy(meta["overrides"])
    overrides[meta["key"]] = {**overrides.get(meta["key"], {}), **patch}
    baseline = state.decode_design_snapshot(
        current.feature_log[start].design_snapshot_gz_b64
    )
    baseline = baseline.copy_with(
        feature_log=current.feature_log[:start],
        loadouts=current.loadouts,
        active_loadout_id=current.active_loadout_id,
        last_editable_loadout_id=current.last_editable_loadout_id,
    )
    settings = GeneratorSettings(**meta["settings"])
    pathing = overrides.get("curve-path", {}).get("pathing", settings.pathing)
    if pathing not in ("colocalized", "interior", "exterior"):
        raise HTTPException(
            422, detail="Pathing must be colocalized, interior, or exterior."
        )
    settings = settings.model_copy(update={"pathing": pathing})
    order_text = overrides.get("curve-path", {}).get("path_order")
    if order_text is not None:
        try:
            numbers = [int(s.strip()) for s in order_text.split(",")]
            gold = [p for p in baseline.nanoparticles if p.kind == "gold_nanosphere"]
            if sorted(numbers) != list(range(1, len(gold) + 1)):
                raise ValueError()
            settings = settings.model_copy(
                update={"particle_order": [gold[i - 1].id for i in numbers]}
            )
        except (ValueError, AttributeError):
            raise HTTPException(
                422,
                detail="Path order must list every particle number once, separated by commas.",
            )
    ids = {
        e.params["_generator"]["key"]: e.id
        for e in current.feature_log[start : end + 1]
    }
    try:
        candidate, _ = plan_generated(baseline, settings)
        rebuilt, _ = build_recorded(
            baseline,
            candidate,
            settings,
            group_id=group,
            overrides=overrides,
            entry_ids=ids,
            stop_key=current.feature_log[end].params["_generator"]["key"],
            standard=False,
        )
        validation = validate_design(rebuilt)
        if not validation.passed:
            raise ValueError(str(validation))
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    state.set_design(rebuilt, expected_revision=revision)
    return _design_response_with_geometry(
        rebuilt, validate_design(rebuilt), full_feature_log=True
    )
