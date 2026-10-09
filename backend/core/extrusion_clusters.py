"""Operation-scoped clustering for lattice extrusion, independent of adjacency."""
import json
from uuid import NAMESPACE_URL, uuid5

from backend.core.cluster_reconcile import MutationReport
from backend.core.models import ClusterRigidTransform


def extrusion_clusters(before, after, origins, *, placement_helix_id=None):
    """Fresh cells form one cluster; a mixed extrusion follows its continuation.

    Origins match lattice addresses, not neighboring cells. In-place growth also
    counts as continuation. Explicit origins retain their individual parents when
    several existing bodies are extended; fresh cells follow the first source.
    Placement is copied, never shared, for a fresh extrusion in a posed frame.
    """
    old = {h.id: h for h in before.helices}
    added = sorted(h.id for h in after.helices if h.id not in old)
    grown = sorted(h.id for h in after.helices if h.id in old and
                   (h.bp_start, h.length_bp) != (old[h.id].bp_start, old[h.id].length_bp))
    origins = dict(origins)
    parents = sorted(set(origins.values()) - {None})
    if parents or grown:
        source = (parents or grown)[0]
        return after, MutationReport(new_helix_origins={
            hid: origins.get(hid, source) for hid in added
        })
    if not added:
        return after, MutationReport()

    # Frame builders may already append cells to the placement cluster. Copy
    # that placement to an independent cluster and remove those inherited claims.
    placements = [c for c in after.cluster_transforms
                  if set(added) <= set(c.helix_ids)]
    if placement_helix_id is not None:
        placements = [c for c in before.cluster_transforms
                      if placement_helix_id in c.helix_ids]
    pose = {}
    if placements:
        source = placements[-1]
        pose = {key: getattr(source, key) for key in ('translation', 'rotation', 'pivot')}
    names = {c.name for c in after.cluster_transforms}
    number = 1
    while f'Cluster {number}' in names:
        number += 1
    cluster = ClusterRigidTransform(
        id=str(uuid5(NAMESPACE_URL, 'nadoc:extrusion:' + json.dumps([before.id, added]))),
        name=f'Cluster {number}', helix_ids=added, auto_created=False,
        is_default=False, **pose)
    clusters = [c.model_copy(update={'helix_ids': [h for h in c.helix_ids if h not in added]})
                for c in after.cluster_transforms]
    return after.copy_with(cluster_transforms=[*clusters, cluster]), MutationReport(
        new_helix_origins={hid: None for hid in added})
