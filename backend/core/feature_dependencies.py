"""Feature-log dependency analysis for "surgical delete" (option-1 semantics).

Deleting a feature-log entry should remove BOTH the log row and the geometry it
produced (option 1), while keeping later entries that don't depend on it. This
module computes, for a target entry K, the set of *later* entries that cannot
survive K's removal — its **dependents** — so the caller can either surgically
delete K (when there are none) or ask the user to cascade-delete K + dependents.

A later entry is a dependent of K when it can't be cleanly re-derived on a
K-free base. Two independent reasons:

  1. **Reference dependency** — the entry consumes an id that K produced or
     modified (e.g. a continuation extruded onto a helix K created; a bend
     scoped to a cluster whose helices K built).
  2. **Non-reconstructability** — the entry's result is only available baked
     *with* K's geometry and we have no way to re-run it on a K-free base. Today
     that means everything except the replayable extrusion snapshot ops and the
     pure overlay deltas (deformation / cluster_op / cluster_create /
     overhang_rotation, which `_seek_feature_log` rebuilds from the log).

The two are kept SEPARATE on purpose. The eventual goal (deferred) is to teach
auto-ops (auto-scaffold/break/merge/crossover) to re-run on a new base — at
which point they become *reconstructable*, and only reason (1) would still mark
them as dependents. To get there, flip `reconstructable` for those op_kinds and
give the reconstruction path a way to re-execute them; the analysis below needs
no change. See `EntryInfo.reconstructable` and `analyze_dependents`.

The module is PURE: it operates on already-decoded `Design` objects + log
entries, never touches gzip/snapshots/HTTP. The caller (crud.delete_feature)
decodes snapshots and feeds the results in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Snapshot op_kinds whose builder can be replayed on an arbitrary base design
# via crud._edit_dispatch_run. MUST stay in sync with that dispatcher.
REPLAYABLE_SNAPSHOT_OPS = frozenset({
    'bundle-create',
    'extrude-segment',
    'extrude-continuation',
    'extrude-deformed-continuation',
    'overhang-extrude',
})

# Delta / overlay feature_types — no baked topology; `_seek_feature_log` rebuilds
# their visible effect from the surviving log every time, so they are always
# reconstructable on a new base (as long as their target ids survive).
_DELTA_FEATURE_TYPES = frozenset({
    'deformation', 'cluster_op', 'cluster_create', 'overhang_rotation',
})

# Collections on a Design whose members carry a stable `.id`. Used to diff two
# design states into added / modified id sets.
_ID_COLLECTIONS = (
    'helices', 'strands', 'crossovers', 'overhang_connections',
    'extensions', 'photoproduct_junctions', 'forced_ligations',
    'overhangs', 'protein_assets', 'protein_attachments',
)


def _id_map(design) -> dict:
    """Map every id-bearing item in ``design`` to the item (incl. overhang
    sub-domains). Ids are uuids / structured strings; cross-collection
    collisions don't occur in practice."""
    out: dict = {}
    for coll in _ID_COLLECTIONS:
        for item in getattr(design, coll, None) or []:
            iid = getattr(item, 'id', None)
            if iid is not None:
                out[iid] = item
            for sd in getattr(item, 'sub_domains', None) or []:
                sid = getattr(sd, 'id', None)
                if sid is not None:
                    out[sid] = sd
    return out


def snapshot_delta(pre, post) -> tuple[set, set]:
    """Return (added_ids, modified_ids) going from ``pre`` to ``post``.

    * added — present in post, absent in pre (ids the op *created*)
    * modified — present in both but with different content (ids the op *changed
      in place*, e.g. a helix a continuation extended)

    Removed ids (pre-only) are intentionally ignored: a later entry can only
    reference an id that still existed when it ran, so K's deletions never
    create downstream dependents.
    """
    pm, qm = _id_map(pre), _id_map(post)
    pre_ids, post_ids = set(pm), set(qm)
    added = post_ids - pre_ids
    modified = {i for i in (pre_ids & post_ids) if pm[i] != qm[i]}
    return added, modified


def _cluster_helices(design, cluster_id: str) -> Optional[set]:
    """Helix ids belonging to ``cluster_id``, or None if the cluster is unknown
    (caller treats None as 'can't prove independence' → dependent)."""
    for ct in getattr(design, 'cluster_transforms', None) or []:
        if ct.id == cluster_id:
            return set(ct.helix_ids or [])
    return None


def delta_entry_targets(entry, design) -> Optional[set]:
    """Pre-existing ids a delta entry depends on, or None when undeterminable.

    None is the conservative 'unknown' sentinel: the caller marks the entry as
    a dependent (safer to over-cascade than to keep an entry whose target we
    couldn't resolve and silently corrupt topology)."""
    ft = entry.feature_type
    if ft == 'deformation':
        op = entry.op_snapshot
        if op is None:
            return None
        ids = set(op.affected_helix_ids or [])
        for cid in (op.cluster_ids or []):
            h = _cluster_helices(design, cid)
            if h is None:
                return None
            ids |= h
        return ids
    if ft == 'cluster_op':
        return _cluster_helices(design, entry.cluster_id)
    if ft == 'cluster_create':
        return set(entry.helix_ids or [])
    if ft == 'overhang_rotation':
        return set(entry.overhang_ids or [])
    return None


@dataclass
class EntryInfo:
    """Per-entry summary the dependency graph closure operates on.

    * added/modified — ids this entry created / changed in place (drives
      transitive growth of the removed set when the entry is itself dropped).
    * targets — pre-existing ids this entry consumes, or None = 'unknown'
      (treated as a reference to everything ⇒ dependent).
    * reconstructable — can this entry be re-derived on a K-free base? True for
      replayable extrusion snapshots + overlay deltas; False otherwise (auto-ops,
      circle, protein, assembly, routing-cluster, evicted/diff snapshots). The
      future auto-op-replay work flips this for those op_kinds.
    """
    added: set = field(default_factory=set)
    modified: set = field(default_factory=set)
    targets: Optional[set] = None
    reconstructable: bool = False


def analyze_dependents(infos: list, k: int) -> list:
    """Indices > k that cannot survive removal of entry k, in log order.

    Transitive: when an entry is marked dependent, the ids IT produced join the
    removed set, so entries built on a dependent are caught too.
    """
    removed = set(infos[k].added) | set(infos[k].modified)
    deps: list = []
    for j in range(k + 1, len(infos)):
        r = infos[j]
        if r is None:
            continue
        referenced = (r.targets is None) or bool(r.targets & removed)
        if referenced or not r.reconstructable:
            deps.append(j)
            removed |= set(r.added) | set(r.modified)
    return deps
