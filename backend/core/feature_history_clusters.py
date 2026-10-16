"""Bounded group lifecycle recovery around existing pose/snapshot restoration.

Only authored creation/dissolution metadata and already decoded group records
are read. This is recovery bookkeeping, not native proof or placement work.
"""

from dataclasses import dataclass

from backend.core.models import ClusterRigidTransform


MAX_HISTORY_ENTRIES = 2_000
MAX_ITEMS = 30_000
MAX_BYTES = 8_000_000
MAX_ID_CHARS = 512


class _Budget:
    def __init__(self):
        self.items = self.bytes = 0

    def charge(self, count):
        self.items += count
        self.bytes += 16 * count
        self.check()

    def check(self):
        if self.items > MAX_ITEMS or self.bytes > MAX_BYTES:
            raise ValueError("Group history exceeds its recovery budget")

    def identity(self, identity):
        if type(identity) is not str or not 1 <= len(identity) <= MAX_ID_CHARS:
            raise ValueError("Group history identity exceeds its recovery allowance")
        self.bytes += 4 * len(identity)
        self.check()
        return identity


def _records(groups, budget):
    if type(groups) is not list:
        raise ValueError("Group history requires a typed group list")
    budget.charge(len(groups))
    identities = set()
    for group in groups:
        identity = budget.identity(group.id)
        if identity in identities:
            raise ValueError("Group history contains ambiguous group identities")
        identities.add(identity)
    return identities


def has_group_dissolution(entries):
    # Existing saved histories have no new admission contract. Do not inspect
    # their group inventories or impose dissolution limits on ordinary seeks.
    return any(entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve"
               for entry in entries)


def has_authored_group_history(entries):
    """Recorded group intent suppresses read-time legacy inference, not proof.

    This cheap positive marker check never validates or blesses a recipe. Old
    unversioned migration rows retain their established normalization behavior.
    """
    for entry in entries:
        if entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve":
            return True
        version = getattr(entry, "proof_version", None)
        if type(version) is not int:
            continue
        if entry.feature_type == "cluster_create" and version in (1, 2):
            return True
        if entry.feature_type == "cluster_op" and version == 1:
            return True
    return False


def _dissolved_ids(params, budget):
    from backend.core.part_group_dissolve import parse_command

    if type(params) is dict and "_generator" in params:
        # Match native dependency/execution admission: attribution is not an
        # input; generated scope remains refused.
        if len(params) > 3:
            raise ValueError("Group dissolution has unsupported recovery inputs")
        params = {key: value for key, value in params.items() if key != "_generator"}
    if type(params) is dict and type(params.get("cluster_ids")) is list:
        budget.charge(len(params["cluster_ids"]))
    identities = parse_command(params)
    for identity in identities:
        budget.identity(identity)
    return identities


def _lifecycle(design, position):
    entries = design.feature_log
    if type(entries) is not list or len(entries) > MAX_HISTORY_ENTRIES:
        raise ValueError("Group history exceeds its entry limit")
    if type(position) is not int or position < -2:
        raise ValueError("Group history position is invalid")
    end = len(entries) - 1 if position == -1 else min(position, len(entries) - 1)
    if position == -2:
        end = -1
    budget = _Budget()
    budget.charge(len(entries))
    _records(design.cluster_transforms, budget)
    all_creations, active_creations, repeated, dissolved, touched = set(), {}, set(), set(), set()
    imported = set()
    last_payload = -1
    for index, entry in enumerate(entries):
        active = index <= end
        if (active and entry.feature_type in {"snapshot", "routing-cluster"}
                and not entry.evicted and entry.post_state_gz_b64):
            last_payload = index
        if entry.feature_type == "cluster_create":
            identity = budget.identity(entry.cluster_id)
            if identity in all_creations or identity in imported:
                repeated.add(identity)
            all_creations.add(identity)
            if active:
                active_creations.pop(identity, None)
                active_creations[identity] = index, entry
                dissolved.discard(identity)
        elif entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve":
            identities = _dissolved_ids(entry.params, budget)
            touched.update(identities)
            imported.update(identity for identity in identities if identity not in all_creations)
            if active:
                dissolved.update(identities)
                for identity in identities:
                    active_creations.pop(identity, None)
    return budget, all_creations, active_creations, repeated, dissolved, touched, last_payload, imported


@dataclass(frozen=True)
class _GroupPoseWindow:
    start: int
    stop: int
    active_count: int
    baseline: ClusterRigidTransform | None

    def contains(self, index):
        return self.start <= index < self.stop


def group_pose_windows(design, position):
    """Bound move/Join ownership to the group incarnation at this cursor.

    Only identities named by a dissolution acquire these boundaries. No payload
    is decoded, and histories without that command retain their old behavior.
    """
    if not has_group_dissolution(design.feature_log):
        return {}
    budget, _, creations, _, dissolved, touched, _, _ = _lifecycle(design, position)
    log = design.feature_log
    active_count = len(log) if position == -1 else max(0, min(position + 1, len(log)))
    windows = {}
    for cid in touched:
        start, entry = creations.get(cid, (-1, None))
        baseline = None
        if entry is not None:
            baseline = entry.cluster_snapshot
            if baseline is None:
                budget.charge(len(entry.helix_ids) + len(entry.domain_ids))
                baseline = ClusterRigidTransform(id=cid, name=entry.name,
                    helix_ids=entry.helix_ids, domain_ids=entry.domain_ids)
        windows[cid] = _GroupPoseWindow(start, start if cid in dissolved else len(log), active_count, baseline)
    # A future dissolution/recreation ends the currently displayed incarnation;
    # its future Join PRE poses and moves must not reset the current group.
    for index, entry in enumerate(log):
        if entry.feature_type == "cluster_op":
            budget.identity(entry.cluster_id)
        if index < active_count:
            continue
        if entry.feature_type == "cluster_create":
            identities = (entry.cluster_id,)
        elif entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve":
            identities = _dissolved_ids(entry.params, budget)
        else:
            continue
        for cid in identities:
            window = windows.get(cid)
            if window is not None and index < window.stop:
                windows[cid] = _GroupPoseWindow(window.start, index, active_count, window.baseline)
    return windows


def filter_group_pose_overlays(log, windows, cluster_last, clusters_with_ops, pattern_baselines):
    """Adjust existing overlay inputs without recomputing any geometric pose."""
    if not windows:
        return cluster_last, clusters_with_ops, pattern_baselines
    last = {cid: row for cid, row in cluster_last.items() if cid not in windows}
    with_ops = clusters_with_ops - windows.keys()
    baselines = {cid: group for cid, group in pattern_baselines.items() if cid not in windows}
    for cid, window in windows.items():
        if window.baseline is not None:
            baselines[cid] = window.baseline
        elif window.start == -1 and window.stop > window.start and cid in pattern_baselines:
            # Pattern-created groups have no separate creation row. Their
            # recorded pattern pose remains the initial incarnation's baseline.
            baselines[cid] = pattern_baselines[cid]
    for index, entry in enumerate(log):
        if entry.feature_type != "cluster_op":
            continue
        window = windows.get(entry.cluster_id)
        if window is not None and window.contains(index):
            with_ops.add(entry.cluster_id)
            if index < window.active_count:
                last[entry.cluster_id] = entry
    return last, with_ops, baselines


def restore_dissolve_fields(design, snapshot):
    """Restore selected group records from the already decoded topology state.

    Untouched records retain their current values and relative order. Missing
    selected groups are inserted before their next surviving snapshot neighbor,
    or at the end when no such neighbor survives. No payload is decoded here.
    """
    if not has_group_dissolution(design.feature_log):
        return design
    budget, _, _, _, _, touched, _, _ = _lifecycle(design, -1)
    if not touched:
        return design
    _records(snapshot.cluster_transforms, budget)
    untouched = [group for group in design.cluster_transforms if group.id not in touched]
    remaining = {group.id for group in untouched}
    before, pending = {}, []
    for group in snapshot.cluster_transforms:
        if group.id in touched:
            pending.append(group)
        elif group.id in remaining and pending:
            before[group.id] = pending
            pending = []
    clusters = []
    for group in untouched:
        clusters.extend(before.get(group.id, ()))
        clusters.append(group)
    clusters.extend(pending)
    return design.copy_with(cluster_transforms=clusters)


def apply_cluster_dissolutions(design, position):
    """Filter active tombstones after every creation/pattern/Join restorer.

    A later explicit creation of the same identity clears its earlier tombstone.
    Before all features (-2), no group is removed by this helper.
    """
    if not has_group_dissolution(design.feature_log):
        return design
    _, _, _, _, dissolved, _, _, _ = _lifecycle(design, position)
    if not dissolved or not any(group.id in dissolved for group in design.cluster_transforms):
        return design
    return design.copy_with(cluster_transforms=[
        group for group in design.cluster_transforms if group.id not in dissolved])


def restore_cluster_creations(design, position):
    if not has_group_dissolution(design.feature_log):
        return _restore_legacy_creations(design, position)
    budget, creations, active, repeated, dissolved, _, last_payload, imported = _lifecycle(design, position)
    if not creations:
        if not dissolved or not any(c.id in dissolved for c in design.cluster_transforms):
            return design
        return design.copy_with(cluster_transforms=[c for c in design.cluster_transforms if c.id not in dissolved])
    clusters = [c for c in design.cluster_transforms
                if (c.id not in creations or c.id in active or c.id in imported) and c.id not in dissolved]
    existing = {c.id for c in clusters}
    budget.charge(len(design.helices))
    for helix in design.helices:
        budget.identity(helix.id)
    helix_ids = {h.id for h in design.helices}
    for cid, (index, entry) in active.items():
        budget.charge(len(entry.helix_ids) + len(entry.domain_ids))
        for identity in entry.helix_ids:
            budget.identity(identity)
        present = any(h in helix_ids for h in entry.helix_ids)
        if not present and not (entry.cluster_snapshot is not None and not entry.helix_ids):
            continue
        if cid not in existing or (cid in repeated and index > last_payload):
            group = entry.cluster_snapshot or ClusterRigidTransform(
                id=cid, name=entry.name,
                helix_ids=[h for h in entry.helix_ids if h in helix_ids],
                domain_ids=entry.domain_ids,
            )
            if cid in existing:
                clusters = [group if c.id == cid else c for c in clusters]
            else:
                clusters.append(group)
                existing.add(cid)
    return design.copy_with(cluster_transforms=clusters)


def _restore_legacy_creations(design, position):
    """Preserve established recovery for histories without dissolution rows."""
    entries = design.feature_log
    creations = {
        e.cluster_id: (i, e)
        for i, e in enumerate(entries)
        if e.feature_type == "cluster_create"
    }
    if not creations:
        return design
    end = len(entries) - 1 if position == -1 else position
    active = {cid: e for cid, (i, e) in creations.items() if i <= end}
    clusters = [
        c for c in design.cluster_transforms if c.id not in creations or c.id in active
    ]
    existing = {c.id for c in clusters}
    helix_ids = {h.id for h in design.helices}
    for cid, entry in active.items():
        if cid not in existing and any(h in helix_ids for h in entry.helix_ids):
            clusters.append(
                entry.cluster_snapshot
                or ClusterRigidTransform(
                    id=cid,
                    name=entry.name,
                    helix_ids=[h for h in entry.helix_ids if h in helix_ids],
                    domain_ids=entry.domain_ids,
                )
            )
    return design.copy_with(cluster_transforms=clusters)
