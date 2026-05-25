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
generalized over the Design topology fields. Every diffed field is an id-keyed
list of Pydantic v2 models, so ``!=`` detects "modified" and
``model_validate(model_dump(mode="json"))`` round-trips a single object.

CORE INVARIANT: diffs are captured AFTER reconcile_cluster_membership +
_retry_pending_ligations, so a child diff already includes reconcile effects.
Reconstruction applies content diffs only and NEVER re-reconciles.
"""

from __future__ import annotations

import base64
import gzip
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.core.models import Design, MinorMutationLogEntry


# Topology-bearing, id-keyed Design fields that minor ops mutate. Matches
# _topology_substitute (crud.py) plus cluster_joints (joint-* subtypes mutate
# it; carrying the joint delta in the diff makes the legacy hand-migration in
# _reconcile_cluster_joints_between a no-op on the diff path).
_DIFF_FIELDS: tuple[str, ...] = (
    "helices",
    "strands",
    "crossovers",
    "forced_ligations",
    "extensions",
    "overhang_connections",
    "photoproduct_junctions",
    "cluster_joints",
)


def _model_classes() -> dict[str, type]:
    """Map each diffed field to its element model class (lazy import to avoid
    import-time coupling)."""
    from backend.core.models import (
        ClusterJoint,
        Crossover,
        ForcedLigation,
        Helix,
        OverhangConnection,
        PhotoproductJunction,
        Strand,
        StrandExtension,
    )
    return {
        "helices": Helix,
        "strands": Strand,
        "crossovers": Crossover,
        "forced_ligations": ForcedLigation,
        "extensions": StrandExtension,
        "overhang_connections": OverhangConnection,
        "photoproduct_junctions": PhotoproductJunction,
        "cluster_joints": ClusterJoint,
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
    mod_pre: dict[str, list] = {}
    mod_post: dict[str, list] = {}

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
    return bool(child.diff_added_b64 or child.diff_removed_b64 or child.diff_modified_b64)


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
    object, append added objects. Topology fields only — feature_log,
    deformations, cluster_transforms, overhangs etc. pass through unchanged.

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
    removed = json.loads(_ungzip_b64(removed_b64).decode("utf-8")) if removed_b64 else {}
    modified = json.loads(_ungzip_b64(modified_b64).decode("utf-8")) if modified_b64 else {}
    mod_post = modified.get("post", {}) if modified else {}

    warnings: list[str] = []
    overrides: dict[str, list] = {}

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
            for mid in absent_mods:
                # Modify of an absent object → re-add its POST state (self-contained).
                new_list.append(model_cls.model_validate(post_by_id[mid]))
            if absent_mods:
                warnings.append(
                    f"{field}: {len(absent_mods)} modified item(s) were re-added (their base step was deleted)"
                )

        overrides[field] = new_list

    if not overrides:
        return anchor, warnings
    return anchor.copy_with(**overrides), warnings
