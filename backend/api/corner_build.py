"""Native Corner regeneration from a source design and bounded authored inputs.

All generated paths, strand splits and seam inserts are deterministic outputs.
No recovery snapshot, captured atom reference or private authoring step is used.
"""

from backend.core.cluster_reconcile import MutationReport
from backend.core.constants import SSDNA_CONTOUR_PER_NT_NM
from backend.core.corner_topology import corner_output_id, materialize_corner_topology
from backend.core.corner_wedge_paths import corner_bundle_paths, paths_in_cluster_frame
from backend.core.lattice_frame_model import LatticeFrame
from backend.core.part_scope_references import COLLECTIONS, referenced_resources


def _admit_references(design, selected, cluster_id):
    strands = {s.id for s in design.strands if any(d.helix_id in selected for d in s.domains)}
    if any(s.is_reference for s in design.strands if s.id in strands):
        raise ValueError('Corner cannot author reference strands.')
    if design.atomistic_reference is not None:
        raise ValueError('Corner must resolve the existing atomistic reference before changing its topology.')
    if design.group_organization is not None:
        raise ValueError('Corner placement membership requires the organized-part command adapter.')
    resources = {('helix', identity) for identity in selected}
    resources |= {('strand', identity) for identity in strands}
    resources.add(('cluster', cluster_id))
    handled = {'helices', 'strands', 'crossovers', 'forced_ligations', 'deformations',
               'cluster_transforms', 'lattice_frames'}
    for field in sorted(COLLECTIONS.keys() - handled):
        for record in getattr(design, field):
            try:
                references = referenced_resources(record)
            except NotImplementedError as error:
                raise ValueError(f'Corner cannot classify {field} references: {error}') from error
            if resources & references:
                raise ValueError(f'Corner must remap the selected {field} references before changing this route.')
    for cluster in design.cluster_transforms:
        if selected.intersection(cluster.helix_ids) and (cluster.domain_ids or cluster.base_ids):
            raise ValueError('Corner requires whole-duplex placement membership.')
        if any(ref.strand_id in strands for ref in cluster.domain_ids):
            raise ValueError('Corner must remap domain-scoped placement membership.')
    for op in design.deformations:
        scope = set(op.affected_helix_ids) or {h.id for h in design.helices}
        if scope & selected and scope - selected:
            raise ValueError('Corner must preserve the shared frame of a deformation spanning other clusters.')
    return strands


def build_corner(design, command, *, on_progress=None, check_cancel=None):
    from backend.api.corner_junction_evaluation import evaluate_corner_junctions
    from backend.core.occupancy import require_unique_occupancy

    backbone_limit = 1.2 if command.proof_version == 1 else SSDNA_CONTOUR_PER_NT_NM
    guide, routes, seams = evaluate_corner_junctions(design, command.inputs(),
        on_progress=on_progress, check_cancel=check_cancel, first_within_nm=backbone_limit)
    check = check_cancel or (lambda: None)
    check()
    if command.angle_deg == 0:
        return design.copy_with(), MutationReport()
    selected = {cut['helix_id'] for cut in guide['cuts']}
    _admit_references(design, selected, command.cluster_id)
    helices = [h for h in design.helices if h.id in selected]
    outgoing = {h.id: corner_output_id(command.operation_id, 'outgoing-helix', h.id) for h in helices}
    if set(outgoing.values()) & {h.id for h in design.helices}:
        raise ValueError('Corner operation identity has already been used.')
    # v1 used the ordinary crossover envelope, which can overextend an ssDNA
    # insert chain. v2 uses the existing per-nucleotide contour limit instead.
    # Preserve v1 replay exactly. Neither screen is an atomistic approval.
    sequences = {}
    for seam in seams:
        fitting = [candidate for candidate in seam.candidates if candidate.max_backbone_length_nm <= backbone_limit]
        if not fitting:
            raise ValueError('No short native insert candidate spans a corner seam within the backbone screening envelope.')
        sequences[(seam.strand_id, seam.exit_domain)] = min(fitting, key=lambda c: (len(c.sequence), c.max_backbone_length_nm)).sequence
    ls_map = {(h.id, ls.bp_index): ls.delta for h in design.helices for ls in h.loop_skips}
    topology = materialize_corner_topology(design.strands, routes,
        operation_id=command.operation_id, outgoing_helix_ids=outgoing,
        bridge_sequences=sequences, loop_skips=ls_map,
        new_tip_sequences=command.proof_version >= 3)
    paths = corner_bundle_paths(design, helices, operation_id=command.operation_id,
        outgoing_helix_ids=outgoing, center_nm=guide['center_nm'], rotation=guide['rotation'])
    owner = next(c for c in design.cluster_transforms if c.id == command.cluster_id)
    paths = paths_in_cluster_frame(paths, owner)
    check()

    occupied = {}
    for strand in topology.strands:
        for domain in strand.domains:
            occupied.setdefault((domain.helix_id, domain.direction.value), []).append(
                tuple(sorted((domain.start_bp, domain.end_bp))))

    def endpoint(hid, bp, direction):
        value = getattr(direction, 'value', direction)
        if hid not in selected:
            return hid, bp, direction
        mapped = topology.endpoint_map.get((hid, bp, value))
        target = mapped[0] if mapped else (hid if bp < command.position_bp else outgoing[hid])
        if not any(lo <= bp <= hi for lo, hi in occupied.get((target, value), [])):
            raise ValueError('An existing connection endpoint is removed by the miter; local connection rerouting is required.')
        return target, bp, direction

    crossovers = []
    for crossover in design.crossovers:
        halves = {}
        for name in ('half_a', 'half_b'):
            half = getattr(crossover, name)
            hid, bp, direction = endpoint(half.helix_id, half.index, half.strand)
            halves[name] = half.model_copy(update={'helix_id': hid, 'index': bp, 'strand': direction})
        crossovers.append(crossover.model_copy(update=halves))
    ligations = []
    for connection in design.forced_ligations:
        patch = {}
        for end in ('three_prime', 'five_prime'):
            hid, bp, direction = endpoint(getattr(connection, end + '_helix_id'),
                getattr(connection, end + '_bp'), getattr(connection, end + '_direction'))
            patch.update({end + '_helix_id': hid, end + '_bp': bp, end + '_direction': direction})
        ligations.append(connection.model_copy(update=patch))

    frame_a = corner_output_id(command.operation_id, 'incoming-frame', command.cluster_id)
    frame_b = corner_output_id(command.operation_id, 'outgoing-frame', command.cluster_id)
    if {frame_a, frame_b} & {frame.id for frame in design.lattice_frames}:
        raise ValueError('Corner frame identities already exist.')
    frames = [*design.lattice_frames, LatticeFrame(id=frame_a, placement_cluster_id=command.cluster_id),
              LatticeFrame(id=frame_b, placement_cluster_id=command.cluster_id)]
    new_helices = [h.model_copy(update={'lattice_frame_id': frame_a}) if h.id in selected else h
                   for h in design.helices]
    new_helices.extend(h.model_copy(update={'id': outgoing[h.id], 'lattice_frame_id': frame_b,
                                           'label': (h.label + '′') if h.label else None}) for h in helices)
    clusters = []
    for cluster in design.cluster_transforms:
        if cluster.id == command.cluster_id:
            clusters.append(cluster.model_copy(update={'helix_ids': [*cluster.helix_ids, *outgoing.values()]}))
        elif selected.intersection(cluster.helix_ids):
            clusters.append(cluster.model_copy(update={'helix_ids': [hid for hid in cluster.helix_ids if hid not in selected]}))
        else:
            clusters.append(cluster)
    deformations = []
    all_ids = {h.id for h in design.helices}
    for op in design.deformations:
        scope = set(op.affected_helix_ids) or all_ids
        if not scope.intersection(selected):
            deformations.append(op)
        elif scope - selected:
            deformations.append(op.model_copy(update={'affected_helix_ids': sorted(scope - selected)}))
    updated = design.copy_with(helices=new_helices, strands=list(topology.strands),
        crossovers=crossovers, forced_ligations=[*ligations, *topology.seam_connections],
        lattice_frames=frames, cluster_transforms=clusters, deformations=[*deformations, *paths])
    require_unique_occupancy(updated)
    check()
    # Membership is explicit above, including owner-local path rebasing. The
    # recorder and replay executor preserve it rather than inferring ancestry.
    return updated, MutationReport()
