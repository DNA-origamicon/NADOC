"""Compact id-keyed topology diffs for Fine Routing per-sub-step revert/delete.

Each minor edit in a Fine Routing cluster records a *content* diff
(before → after, captured post-reconcile) on its ``MinorMutationLogEntry``.
Because the diff is content-based, not operation-based, it captures ANY op
type — including the many that have no ``_replay_minor_op`` builder (ligate,
crossover-move, strands-color-bulk, helix-reorder/extend, forced-ligation-*,
strand-add, …). Intermediate cluster states are then reconstructed by applying
child diffs forward, never by replaying operations.

This mirrors the assembly-level diff pattern in
``backend/api/assembly_state.py`` (encode_diff_snapshot / apply_diff_forward),
generalized over the Design topology fields. Topology collections are id-keyed
lists. Organizational membership is an optional whole-wrapper replacement in
the modified pre/post envelope; its recorded baseline must match exactly.

CORE INVARIANT: diffs are captured AFTER reconcile_cluster_membership +
_retry_pending_ligations, so a child diff already includes reconcile effects.
Reconstruction applies content diffs only and NEVER re-reconciles.
"""

from __future__ import annotations

import base64
import gzip
import json
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.core.models import Design, MinorMutationLogEntry


# Topology-bearing, id-keyed Design fields that minor ops mutate. Matches
# _topology_substitute (crud.py) plus cluster_joints (joint-* subtypes mutate
# it; carrying the joint delta in the diff makes the legacy hand-migration in
# _reconcile_cluster_joints_between a no-op on the diff path).
_DIFF_FIELDS: tuple[str, ...] = (
    "helices",
    "overhangs",
    "strands",
    "crossovers",
    "crossover_constraints",
    "forced_ligations",
    "extensions",
    "overhang_connections",
    "photoproduct_junctions",
    "cluster_joints",
    "cluster_join_constraints",
)

_ORGANIZATION = "group_organization"
_UNCHANGED = object()


def _admit_organization_json(value):
    """Bound decoded/emitted metadata before constructing its typed wrapper.

    The encoder applies this same admission after its typed preflight, so it
    cannot emit a replacement that its reader rejects on structural budget.
    Legacy diffs without this field retain their existing format and reader.
    """
    from backend.core.part_capture_graph import GraphBudget
    from backend.core.part_group_model import PartGroup

    def json_value(item):
        if (item is not None and type(item) not in {dict, list, str, bool, int, float}
                or type(item) is dict and any(type(key) is not str for key in item)
                or type(item) is float and not isfinite(item)
                or type(item) is int and item.bit_length() > 64):
            raise ValueError("Group organization recovery requires finite bounded JSON values")

    GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None,
        clock=lambda: 0).charge(value, validate=json_value, reject_cycles=True)
    if value is None:
        return
    if (type(value) is not dict or set(value) != {"version", "groups"}
            or type(value["groups"]) is not list):
        raise ValueError("Group organization recovery requires a complete wrapper")
    fields = set(PartGroup.model_fields)
    if any(type(group) is not dict or set(group) != fields for group in value["groups"]):
        raise ValueError("Group organization recovery requires complete group metadata")


def _organization_replacement(current, modified):
    """Refuse deleted/changed ancestry instead of restoring unrelated groups.

    Defensive topology replay may append an absent modified strand, but a whole
    organizational replacement cannot safely infer its missing baseline. This
    rule also applies to each transition inside the optimized recorded run.
    """
    from backend.core.part_group_model import GroupOrganization
    from backend.core.part_group_organization import _bounded_groups

    if type(modified) is not dict:
        raise ValueError("Recorded modifications require a pre/post object")
    pre, post = modified.get("pre", {}), modified.get("post", {})
    if type(pre) is not dict or type(post) is not dict:
        raise ValueError("Recorded modifications require pre/post objects")
    has_pre, has_post = _ORGANIZATION in pre, _ORGANIZATION in post
    if not has_pre and not has_post:
        return _UNCHANGED
    if not has_pre or not has_post:
        raise ValueError("Group organization recovery requires both recorded pre and post states")
    before, after = pre[_ORGANIZATION], post[_ORGANIZATION]
    _admit_organization_json(before)
    _admit_organization_json(after)
    expected = GroupOrganization.model_validate(before) if before is not None else None
    replacement = GroupOrganization.model_validate(after) if after is not None else None
    if current is not None:
        _bounded_groups(current)
    if current != expected:
        raise ValueError("Group organization recovery baseline is missing or changed")
    return replacement


def _model_classes() -> dict[str, type]:
    """Map each diffed field to its element model class (lazy import to avoid
    import-time coupling)."""
    from backend.core.models import (
        ClusterJoint,
        ClusterJoinConstraint,
        Crossover,
        CrossoverConstraint,
        ForcedLigation,
        Helix,
        OverhangConnection,
        OverhangSpec,
        PhotoproductJunction,
        Strand,
        StrandExtension,
    )

    return {
        "helices": Helix,
        "overhangs": OverhangSpec,
        "strands": Strand,
        "crossovers": Crossover,
        "crossover_constraints": CrossoverConstraint,
        "forced_ligations": ForcedLigation,
        "extensions": StrandExtension,
        "overhang_connections": OverhangConnection,
        "photoproduct_junctions": PhotoproductJunction,
        "cluster_joints": ClusterJoint,
        "cluster_join_constraints": ClusterJoinConstraint,
    }


def _gzip_b64(raw: bytes) -> str:
    return base64.b64encode(gzip.compress(raw, compresslevel=6)).decode("ascii")


def _ungzip_b64(payload_b64: str) -> bytes:
    return gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))


def encode_child_diff(pre: "Design", post: "Design") -> tuple[str, str, str, int]:
    """Diff the topology fields of ``pre`` vs ``post`` by object id.

    Returns ``(added_b64, removed_b64, modified_b64, size_bytes)`` where
    ``size_bytes`` is the total uncompressed JSON length (for the eviction
    budget). Empty diffs round-trip as empty strings so ``is_diff_child``
    distinguishes a recorded-but-empty diff from a legacy (never-recorded) one
    — see note below.

    Per field:
      - added:    full POST objects whose id is in post but not pre
      - removed:  ``{id, idx}`` for objects in pre but not post (idx = pre-list
                  index, kept for forward-apply determinism / future inverse)
      - modified: ``{pre: [...], post: [...]}`` for ids in both whose content
                  differs (whole-object; strands carry their nested domains).
    """
    added: dict[str, list] = {}
    removed: dict[str, list] = {}
    mod_pre: dict = {}
    mod_post: dict = {}

    pre_organization, post_organization = pre.group_organization, post.group_organization
    if pre_organization is not post_organization:
        from backend.core.part_group_organization import _bounded_groups

        # Admit both inputs before either serializer can expand shared values.
        for organization in (pre_organization, post_organization):
            if organization is not None:
                _bounded_groups(organization)
        if pre_organization != post_organization:
            for target, organization in ((mod_pre, pre_organization), (mod_post, post_organization)):
                value = organization.model_dump(mode="json") if organization is not None else None
                _admit_organization_json(value)
                target[_ORGANIZATION] = value

    for field in _DIFF_FIELDS:
        pre_list = list(getattr(pre, field) or [])
        post_list = list(getattr(post, field) or [])
        pre_by_id = {o.id: o for o in pre_list}
        post_by_id = {o.id: o for o in post_list}
        pre_idx = {o.id: k for k, o in enumerate(pre_list)}
        pre_ids = set(pre_by_id)
        post_ids = set(post_by_id)

        added_ids = post_ids - pre_ids
        removed_ids = pre_ids - post_ids
        if added_ids:
            added[field] = [post_by_id[i].model_dump(mode="json") for i in added_ids]
        if removed_ids:
            removed[field] = [
                {"id": i, "idx": pre_idx[i]}
                for i in sorted(removed_ids, key=lambda i: pre_idx[i])
            ]

        mp: list = []
        mq: list = []
        for i in pre_ids & post_ids:
            if pre_by_id[i] != post_by_id[i]:
                mp.append(pre_by_id[i].model_dump(mode="json"))
                mq.append(post_by_id[i].model_dump(mode="json"))
        if mp:
            mod_pre[field] = mp
            mod_post[field] = mq

    added_json = json.dumps(added) if added else ""
    removed_json = json.dumps(removed) if removed else ""
    modified_obj = {"pre": mod_pre, "post": mod_post} if mod_pre else {}
    modified_json = json.dumps(modified_obj) if modified_obj else ""

    size = len(added_json) + len(removed_json) + len(modified_json)
    return (
        _gzip_b64(added_json.encode("utf-8")) if added_json else "",
        _gzip_b64(removed_json.encode("utf-8")) if removed_json else "",
        _gzip_b64(modified_json.encode("utf-8")) if modified_json else "",
        size,
    )


def is_diff_child(child: "MinorMutationLogEntry") -> bool:
    """True iff *child* carries a recorded diff (any of the three diff_*_b64
    fields non-empty). All-empty = legacy entry → caller falls back to replay.

    Note: a genuinely no-op-on-topology edit (none of the diffed fields
    changed) also produces all-empty diffs and is therefore treated as legacy.
    That is harmless: reconstructing across it is a no-op whether by empty-diff
    apply or by replay, and such edits are rare (most minor ops touch at least
    one diffed field — e.g. strands-color-bulk changes Strand.color).
    """
    return bool(
        child.diff_added_b64 or child.diff_removed_b64 or child.diff_modified_b64
    )


def apply_child_diff_forward(
    anchor: "Design",
    added_b64: str,
    removed_b64: str,
    modified_b64: str,
    *,
    defensive: bool = False,
) -> tuple["Design", list[str]]:
    """Apply one child's diff to ``anchor`` (= the state BEFORE that child) and
    return ``(post_state, warnings)``.

    Per field, in order: drop removed ids, replace modified by their POST
    object, append added objects. An optional organization replacement restores
    membership only after its recorded pre-state matches. Feature history,
    deformations and numerical cluster transforms pass through unchanged.

    ``defensive=True`` (used only by per-step DELETE when applying the tail of
    survivors after an earlier step was removed): a removal whose id is absent
    is skipped, and a modify whose id is absent is appended as its POST object
    (the POST payload is self-contained). Each such anomaly is recorded in
    ``warnings`` so the caller can flag a best-effort result. With
    ``defensive=False`` the prefix is internally consistent and no anomalies
    are expected.
    """
    classes = _model_classes()
    added = json.loads(_ungzip_b64(added_b64).decode("utf-8")) if added_b64 else {}
    removed = (
        json.loads(_ungzip_b64(removed_b64).decode("utf-8")) if removed_b64 else {}
    )
    modified = (
        json.loads(_ungzip_b64(modified_b64).decode("utf-8")) if modified_b64 else {}
    )
    mod_post = modified.get("post", {}) if modified else {}
    organization = _organization_replacement(anchor.group_organization, modified)

    warnings: list[str] = []
    overrides: dict = {}
    if organization is not _UNCHANGED:
        overrides[_ORGANIZATION] = organization

    for field in _DIFF_FIELDS:
        model_cls = classes[field]
        removed_ids = {r["id"] for r in removed.get(field, [])}
        post_by_id = {d["id"]: d for d in mod_post.get(field, [])}
        added_dicts = added.get(field, [])
        if not (removed_ids or post_by_id or added_dicts):
            continue  # field untouched by this child

        current = list(getattr(anchor, field) or [])
        present_ids = {o.id for o in current}
        new_list = []
        applied_mod = set()
        for obj in current:
            if obj.id in removed_ids:
                continue
            if obj.id in post_by_id:
                new_list.append(model_cls.model_validate(post_by_id[obj.id]))
                applied_mod.add(obj.id)
            else:
                new_list.append(obj)
        for d in added_dicts:
            new_list.append(model_cls.model_validate(d))

        if defensive:
            absent_removes = removed_ids - present_ids
            if absent_removes:
                warnings.append(
                    f"{field}: {len(absent_removes)} item(s) to remove were already gone"
                )
            absent_mods = set(post_by_id) - applied_mod
            dropped = 0
            for mid in sorted(absent_mods):
                # Modify of an absent object → re-add its POST state (self-contained),
                # except a strand whose bases are now occupied by another strand:
                # re-adding it would put two bases in one slot.
                item = model_cls.model_validate(post_by_id[mid])
                if field == "strands":
                    from backend.core.occupancy import occupancy_conflicts
                    probe = anchor.copy_with(strands=new_list)
                    if (occupancy_conflicts(probe.copy_with(strands=[*new_list, item]), limit=0)[1]
                            > occupancy_conflicts(probe, limit=0)[1]):
                        dropped += 1
                        continue
                new_list.append(item)
            if absent_mods:
                readded = len(absent_mods) - dropped
                if readded:
                    warnings.append(
                        f"{field}: {readded} modified item(s) were re-added (their base step was deleted)"
                    )
                if dropped:
                    warnings.append(
                        f"{field}: {dropped} later edit(s) to strands created by the deleted step were "
                        "dropped (their bases are now covered by the restored strand)"
                    )

        overrides[field] = new_list

    if not overrides:
        return anchor, warnings
    return anchor.copy_with(**overrides), warnings


def apply_child_diff_run(anchor: "Design", children) -> "Design":
    """Compose a contiguous recorded prefix without materializing each child.

    This is *state-patch* evaluation, never command coalescing: even a resize's
    deletion of a different object survives. Ordered maps preserve remove/re-add
    order; modifications of absent ids remain ignored, matching forward apply.
    Only the final surviving POST objects require Pydantic construction. No
    reconcile, geometry generation, shared cache, or mutation of the anchor.

    The contract is the same recorded-field coverage as apply_child_diff_forward,
    not a claim that legacy diffs describe all Design fields. Non-diff children
    must be replayed outside this function. Duplicate ids (noncanonical history)
    fall back to the reference path, whose list semantics allow duplicates.
    """
    children = tuple(children)
    if len(children) < 2:
        for child in children:
            if not is_diff_child(child):
                raise ValueError("A recorded diff run cannot contain legacy operations")
            anchor, _ = apply_child_diff_forward(
                anchor, child.diff_added_b64, child.diff_removed_b64,
                child.diff_modified_b64,
            )
        return anchor

    classes = _model_classes()
    collections: dict[str, dict] = {}
    organization = anchor.group_organization
    organization_changed = False

    def reference():
        state = anchor
        for child in children:
            state, _ = apply_child_diff_forward(
                state, child.diff_added_b64, child.diff_removed_b64,
                child.diff_modified_b64,
            )
        return state

    for child in children:
        if not is_diff_child(child):
            raise ValueError("A recorded diff run cannot contain legacy operations")
        added = json.loads(_ungzip_b64(child.diff_added_b64)) if child.diff_added_b64 else {}
        removed = json.loads(_ungzip_b64(child.diff_removed_b64)) if child.diff_removed_b64 else {}
        modified = json.loads(_ungzip_b64(child.diff_modified_b64)) if child.diff_modified_b64 else {}
        post = modified.get("post", {})
        replacement = _organization_replacement(organization, modified)
        if replacement is not _UNCHANGED:
            organization = replacement
            organization_changed = True
        for field in (added.keys() | removed.keys() | post.keys()) & classes.keys():
            if field not in collections:
                original = getattr(anchor, field) or []
                current = {obj.id: obj for obj in original}
                if len(current) != len(original):
                    return reference()
                collections[field] = current
            current = collections[field]
            for item in removed.get(field, []):
                current.pop(item["id"], None)
            for item in post.get(field, []):
                if item["id"] in current:
                    current[item["id"]] = item
            for item in added.get(field, []):
                if item["id"] in current:
                    return reference()
                current[item["id"]] = item

    overrides = {
        field: [classes[field].model_validate(obj) if isinstance(obj, dict) else obj
                for obj in current.values()]
        for field, current in collections.items()
    }
    if organization_changed:
        overrides[_ORGANIZATION] = organization
    return anchor.copy_with(**overrides) if overrides else anchor
