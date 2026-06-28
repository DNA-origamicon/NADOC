"""Feature-log dependency analysis for "surgical delete" (option-1 semantics).

Deleting a feature-log entry should remove BOTH the log row and the geometry it
produced (option 1), while keeping later entries that don't depend on it. This
module computes, for a target entry K, the set of *later* entries that cannot
survive K's removal — its **dependents** — so the caller can either surgically
delete K (when there are none) or ask the user to cascade-delete K + dependents.

A later entry is a dependent of K when it structurally references an id that K
produced (or that a true dependent produced). Reconstructability is deliberately
not part of the dependency decision: baked snapshot entries can survive a clean
delete when their added/modified objects do not point at the removed ids, because
the delete path scrubs those ids out of their baked snapshots.

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
    'overhangs', 'cluster_transforms', 'cluster_joints',
    'flexible_segment_marks', 'flexible_connections',
    'protein_assets', 'protein_attachments',
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


def snapshot_removed(pre, post) -> set:
    """Return ids present in ``pre`` but absent from ``post``."""
    return set(_id_map(pre)) - set(_id_map(post))


def _add(v, out: set) -> None:
    if v:
        out.add(v)


def _strand_domain_refs(strand, out: set) -> None:
    for dom in getattr(strand, 'domains', None) or []:
        _add(getattr(dom, 'helix_id', None), out)
        _add(getattr(dom, 'overhang_id', None), out)
        _add(getattr(dom, 'binds_overhang_id', None), out)


def _strand_domain_helix(design, strand_id: str, domain_index: int):
    for strand in getattr(design, 'strands', None) or []:
        if strand.id != strand_id:
            continue
        domains = getattr(strand, 'domains', None) or []
        if 0 <= domain_index < len(domains):
            return getattr(domains[domain_index], 'helix_id', None)
    return None


def _object_refs(item, design=None) -> set:
    """Return ids referenced by one id-bearing object.

    This intentionally follows the typed model fields that can point at DNA
    topology ids instead of doing a blind string scan over JSON.
    """
    out: set = set()
    name = item.__class__.__name__

    if name == 'Strand':
        _strand_domain_refs(item, out)
    elif name == 'Crossover':
        _add(item.half_a.helix_id, out)
        _add(item.half_b.helix_id, out)
    elif name == 'ForcedLigation':
        _add(item.three_prime_helix_id, out)
        _add(item.five_prime_helix_id, out)
    elif name == 'OverhangSpec':
        _add(item.helix_id, out)
        _add(item.strand_id, out)
        _add(item.parent_overhang_id, out)
    elif name == 'OverhangConnection':
        _add(item.overhang_a_id, out)
        _add(item.overhang_b_id, out)
        _add(getattr(item, 'target_joint_id', None), out)
    elif name == 'OverhangBinding':
        _add(item.sub_domain_a_id, out)
        _add(item.sub_domain_b_id, out)
        _add(item.overhang_a_id, out)
        _add(item.overhang_b_id, out)
        _add(item.target_joint_id, out)
    elif name == 'StrandExtension':
        _add(item.strand_id, out)
    elif name == 'ClusterRigidTransform':
        for ref in item.domain_ids or []:
            _add(ref.strand_id, out)
    elif name == 'ClusterJoint':
        _add(item.cluster_id, out)
    elif name == 'FlexibleSegmentMark':
        _add(item.strand_id, out)
        if design is not None:
            _add(_strand_domain_helix(design, item.strand_id, item.domain_index), out)
    elif name == 'FlexibleConnection':
        _add(item.cluster_a_id, out)
        _add(item.cluster_b_id, out)
        for anchor in [item.anchor_a, item.anchor_b, *(item.segment_bead_keys or [])]:
            _add(anchor.strand_id, out)
            if design is not None:
                _add(_strand_domain_helix(design, anchor.strand_id, anchor.domain_index), out)
    elif name == 'ProteinAttachment':
        _add(getattr(item, 'asset_id', None), out)
        _add(getattr(item, 'helix_id', None), out)
        _add(getattr(item, 'strand_id', None), out)
    else:
        _add(getattr(item, 'helix_id', None), out)
        _add(getattr(item, 'strand_id', None), out)
        _add(getattr(item, 'cluster_id', None), out)
    return out


def structural_reference_targets(pre, post, added: set, modified: set) -> set:
    """Ids referenced by objects this entry added or modified.

    Own-id membership alone is not enough for clean delete: a later entry can
    create a new object whose *fields* point at a removed helix or strand. This
    scan returns those field-level references. Modified strands also target
    their own id, so a later edit to a strand produced by K is considered a true
    dependent even when its domains stay on unrelated helices.
    """
    qm = _id_map(post)
    out: set = set()
    for iid in set(added) | set(modified):
        item = qm.get(iid)
        if item is None:
            continue
        out |= _object_refs(item, post)
        if iid in modified:
            out.add(iid)
    return out


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

    * added/modified — ids this entry created / changed in place. Added ids
      drive transitive growth of the removed set; modified ids are kept for
      reconstruction strategy decisions and as self-targets for structural refs.
    * targets — ids this entry structurally references, or None = 'unknown'
      (treated as a reference to everything ⇒ dependent).
    * reconstructable — retained as metadata for callers that need to choose a
      reconstruction strategy; it does NOT gate dependency analysis.
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
    removed = set(infos[k].added)
    deps: list = []
    for j in range(k + 1, len(infos)):
        r = infos[j]
        if r is None:
            continue
        referenced = (r.targets is None) or bool(r.targets & removed)
        if referenced:
            deps.append(j)
            removed |= set(r.added)
    return deps
