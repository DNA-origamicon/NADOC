"""Target-local feature evaluation contracts and explainable overwrite analysis.

No persisted 'skipped' flag: another cursor can require an earlier value. The
generic analyzer describes command dependencies conservatively. Runtime seeking
also exploits already-recorded topology, so a snapshot does not need its builder
rerun. These are distinct reasons for avoiding work.
"""
from __future__ import annotations

from dataclasses import dataclass
import os


EVALUATOR_VERSION = 1
Resource = tuple[str, ...]


def optimization_enabled() -> bool:
    """Operational A/B switch; never run both evaluators in user requests."""
    return os.environ.get("NADOC_FEATURE_EVALUATION", "optimized") != "baseline"


@dataclass(frozen=True)
class Effects:
    reads: frozenset[Resource] = frozenset()
    writes: frozenset[Resource] = frozenset()
    known: bool = True


def feature_effects(entry) -> Effects:
    """Audited absolute setters only; relative/topology builders are barriers.

    Pose includes translation, quaternion AND pivot. Sub-domain angles and
    whole-overhang rotations are separate resources, including mixed batches.
    Existence reads stop future contracts from discarding a needed creation.
    """
    if entry.feature_type == "cluster_op":
        return Effects(
            frozenset({("cluster", entry.cluster_id, "exists")}),
            frozenset({("cluster", entry.cluster_id, "pose")}),
        )
    if entry.feature_type == "overhang_rotation":
        reads, writes = set(), set()
        for i, oid in enumerate(entry.overhang_ids):
            sid = entry.sub_domain_ids[i] if i < len(entry.sub_domain_ids) else None
            reads.add(("overhang", oid, "exists"))
            if sid is None:
                writes.add(("overhang", oid, "rotation"))
            else:
                reads.add(("overhang", oid, "subdomain", sid, "exists"))
                writes.add(("overhang", oid, "subdomain", sid, "angles"))
        return Effects(frozenset(reads), frozenset(writes))
    # New command contracts must explicitly account for ALL incidental effects.
    return Effects(known=False)


def analyze_overwrites(effects: list[Effects]) -> list[bool]:
    """True marks an entirely overwritten operation with no intervening reader.

    All final resources are observable. Unknown operations clear the proof;
    partial batch overwrites retain the whole command. O(total resource refs).
    """
    overwritten: set[Resource] = set()
    skipped = [False] * len(effects)
    for i in range(len(effects) - 1, -1, -1):
        effect = effects[i]
        if not effect.known:
            overwritten.clear()
        elif effect.writes and effect.writes <= overwritten:
            skipped[i] = True
        else:
            overwritten.update(effect.writes)
            overwritten.difference_update(effect.reads)
    return skipped


def recorded_effects(child) -> Effects:
    """Explain whole-object POST overwrites (diagnostics only, not hot-path).

    Stored patches need no historical geometric inputs. Modification requires
    the target's existence. Creation/deletion changes order and membership and
    stays a barrier in the explanation; the composer preserves those effects.
    """
    import json
    from backend.core.design_diff import _DIFF_FIELDS, _ungzip_b64, is_diff_child

    if not is_diff_child(child) or child.diff_added_b64 or child.diff_removed_b64:
        return Effects(known=False)
    modified = json.loads(_ungzip_b64(child.diff_modified_b64)) if child.diff_modified_b64 else {}
    targets = [(field, item["id"]) for field, items in modified.get("post", {}).items()
               if field in _DIFF_FIELDS for item in items]
    return Effects(frozenset((*key, "exists") for key in targets),
                   frozenset((*key, "content") for key in targets))


def evaluation_plan(design, position: int, sub_position: int | None = None) -> dict:
    """Read-only diagnostics; intentionally outside the latency-sensitive path.

    Reports conservative semantic decisions plus the recorded-state strategy.
    Full snapshots are not decoded or returned. Child POST patches are inspected
    only for an explicitly requested child prefix. Recomputed on request
    so edits, undo, loading another document, and child cursors cannot stale it.
    """
    log = design.feature_log
    end = -1 if position == -2 else (len(log) - 1 if position == -1 else min(position, len(log) - 1))
    active = log[:end + 1] if end >= 0 else []
    effects = [feature_effects(entry) for entry in active]
    skipped = analyze_overwrites(effects)
    rows = []
    for i, (entry, effect, skip) in enumerate(zip(active, effects, skipped)):
        action = "superseded" if skip else "execute" if effect.known else "unknown"
        reason = ("All written resources are overwritten before any required reader"
                  if skip else "Required absolute state" if effect.known
                  else "No complete command effect contract; preserve dependencies")
        rows.append({"index": i, "id": entry.id, "action": action, "reason": reason,
                     "reads": sorted(effect.reads), "writes": sorted(effect.writes)})

    source = next((i for i in range(end, -1, -1)
                   if getattr(log[i], "post_state_gz_b64", "")
                   and not getattr(log[i], "evicted", False)), None)
    topology = {"source_index": source, "action": "use_live_topology"}
    if source is not None:
        entry = log[source]
        topology["action"] = "apply_recorded_post_state"
        if entry.feature_type == "routing-cluster" and source == end and sub_position is not None:
            if sub_position < -1:
                topology["action"] = "apply_recorded_pre_state"
            elif 0 <= sub_position < len(entry.children):
                topology["action"] = "evaluate_child_prefix"
                from backend.core.design_diff import is_diff_child
                children = entry.children[:sub_position + 1]
                child_effects = [recorded_effects(c) for c in children]
                dead = analyze_overwrites(child_effects)
                topology["children"] = [
                    {"index": j, "id": c.id,
                     "action": "superseded" if dead[j] else "apply_recorded_state" if is_diff_child(c) else "execute",
                     "reason": "All recorded POST objects are overwritten before a replay boundary"
                     if dead[j] else "Compose recorded patches; retain lifecycle effects"
                     if is_diff_child(c) else "Legacy command is a replay boundary",
                     "writes": sorted(child_effects[j].writes)}
                    for j, c in enumerate(children)
                ]
    else:
        first = next((i for i, e in enumerate(log)
                      if not getattr(e, "evicted", False)
                      and (getattr(e, "design_snapshot_gz_b64", "")
                           or getattr(e, "pre_state_gz_b64", ""))), None)
        if first is not None:
            topology = {"source_index": first, "action": "apply_recorded_pre_state"}
    return {"evaluator_version": EVALUATOR_VERSION, "position": position,
            "sub_position": sub_position, "entries": rows, "topology": topology,
            "entries_analysis": "Conservative command dependencies; recorded topology can bypass builders separately",
            "geometry": "Materialize only the requested state; no intermediate render geometry"}


@dataclass
class OverlayState:
    deformations: list
    cluster_last: dict
    clusters_with_ops: set
    overhang_last: dict
    subdomain_last: dict
    overhangs_with_ops: set
    subdomains_with_ops: set


def collect_overlays(design, log, active_count: int) -> OverlayState:
    """Single pass replacing repeated full-log scans in the reference evaluator.

    This is a projection of recorded absolute states, not replay of geometric
    builders. Snapshots already contain their historical topology effects.
    Deformations retain their complete ordered sequence. All-log membership is
    retained to reset future poses when seeking backward.
    """
    out = OverlayState([], {}, set(), {}, {}, set(), set())
    deform_map = None
    for index, entry in enumerate(log):
        active = index < active_count
        ft = entry.feature_type
        if ft == "deformation" and active:
            op = entry.op_snapshot
            if op is None:
                if deform_map is None:
                    deform_map = {d.id: d for d in design.deformations}
                op = deform_map.get(entry.deformation_id)
            if op is not None:
                out.deformations.append(op)
        elif ft == "cluster_op":
            out.clusters_with_ops.add(entry.cluster_id)
            if active:
                out.cluster_last[entry.cluster_id] = entry
        elif ft == "overhang_rotation":
            for i, oid in enumerate(entry.overhang_ids):
                sid = entry.sub_domain_ids[i] if i < len(entry.sub_domain_ids) else None
                if sid is None:
                    out.overhangs_with_ops.add(oid)
                    if active:
                        out.overhang_last[oid] = entry.rotations[i]
                else:
                    key = (oid, sid)
                    out.subdomains_with_ops.add(key)
                    if active:
                        out.subdomain_last[key] = (float(entry.sub_domain_thetas_deg[i]),
                                                  float(entry.sub_domain_phis_deg[i]))
    return out


def evaluate_child_prefix(anchor, children, replay, *, optimized: bool):
    """Defer all intermediate materialization within recorded runs.

    A legacy builder is a read barrier: flush the recorded state before invoking
    it. Never compose relative commands or defensively reapply deleted history.
    Short prefixes use the reference path to avoid planning overhead.
    """
    from backend.core.design_diff import (
        apply_child_diff_forward, apply_child_diff_run, is_diff_child,
    )

    def flush(state, run):
        if len(run) >= 8:
            return apply_child_diff_run(state, run)
        for child in run:
            state, _ = apply_child_diff_forward(
                state, child.diff_added_b64, child.diff_removed_b64, child.diff_modified_b64,
            )
        return state

    if not optimized or len(children) < 8:
        for child in children:
            if is_diff_child(child):
                anchor, _ = apply_child_diff_forward(
                    anchor, child.diff_added_b64, child.diff_removed_b64, child.diff_modified_b64,
                )
            else:
                anchor = replay(anchor, child.op_subtype, child.params)
        return anchor
    pending = []
    for child in children:
        if is_diff_child(child):
            pending.append(child)
        else:
            anchor = flush(anchor, pending)
            pending = []
            anchor = replay(anchor, child.op_subtype, child.params)
    return flush(anchor, pending)


def batch_target_groups(design, positions, *, optimized: bool):
    """Group exact end-cursor aliases; cache lifetime is a single batch request.

    No fingerprints or mutable global caches. Each distinct animation state is
    still evaluated; only -1, last-index and overshoot aliases share geometry.
    """
    groups = {}
    last = len(design.feature_log) - 1
    for position in dict.fromkeys(positions):
        key = -1 if optimized and (position == -1 or position >= last and position >= 0) else position
        groups.setdefault(key, []).append(position)
    return groups
