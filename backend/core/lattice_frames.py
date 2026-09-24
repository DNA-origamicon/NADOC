"""Candidate construction for independently placed standard-lattice bundles.

Pure candidate builders shared by frame-cell editing and frame extrusion APIs.
Native VR source resolution and controller-to-part placement remain adapter work.
"""
import math
import uuid
from backend.core.models import ClusterRigidTransform, Design
from backend.core.lattice import make_bundle_design
from backend.core.lattice_frame_model import LatticeFrame
from backend.core.vr_extrude_draft import validate_painted_footprint


def lattice_address(helix):
    """Frame + cell identifies a lattice line, not its potentially multiple segments."""
    return None if helix.grid_pos is None else (helix.lattice_frame_id, *helix.grid_pos)


def _finite_vector(value, size):
    if (not isinstance(value, (list, tuple)) or len(value) != size
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('invalid rigid placement vector')
    return list(value)


def _canonical_bundle(design, cells, length_bp, plane, frame_id, name):
    footprint = validate_painted_footprint({'lattice_type': design.lattice_type.value,
                                           'cells': cells})
    if not footprint['cells'] or type(length_bp) is not int or not 1 <= abs(length_bp) <= 1_000_000:
        raise ValueError('nonempty cells and bounded nonzero length required')
    bundle = make_bundle_design([tuple(c) for c in cells], length_bp, name=name,
        plane=plane, id_suffix='_'+str(uuid.uuid4()), lattice_type=design.lattice_type)
    helices = [h.model_copy(update={'lattice_frame_id': frame_id, 'grid_pos': tuple(cell)})
               for h, cell in zip(bundle.helices, cells, strict=True)]
    return bundle, helices


def append_frame_bundle(design, frame_id, cells, length_bp, *, plane, name='Extrude'):
    """Extrude vacant cells from an existing canonical plane, retaining its placement.

    This is default-plane authoring, not continuation from a blunt end. New axes
    start at canonical bp zero; the source frame's rigid transform applies once.
    """
    frames = [f for f in design.lattice_frames if f.id == frame_id]
    if len(frames) != 1:
        raise ValueError('unknown lattice frame')
    frame = frames[0]
    if plane != frame.plane:
        raise ValueError('source plane does not match lattice frame')
    occupied = {h.grid_pos for h in design.helices if h.lattice_frame_id == frame_id}
    bundle, helices = _canonical_bundle(design, cells, length_bp, plane, frame_id, name)
    if any(h.grid_pos in occupied for h in helices):
        raise ValueError('cell already occupied in this lattice frame')
    clusters = [c.model_copy(update={'helix_ids': [*c.helix_ids, *(h.id for h in helices)]})
                if c.id == frame.placement_cluster_id else c for c in design.cluster_transforms]
    if not any(c.id == frame.placement_cluster_id for c in clusters):
        raise ValueError('lattice frame placement cluster is missing')
    return design.copy_with(helices=[*design.helices, *helices],
        strands=[*design.strands, *bundle.strands], cluster_transforms=clusters)


def append_independent_bundle(design: Design, cells, length_bp, *, plane='XY',
                              translation_nm=(0, 0, 0), rotation_xyzw=(0, 0, 0, 1),
                              name='Extrude') -> Design:
    """Build canonical topology plus one explicit persistent placement, without mutation.

    Native tracking metres/tablet orientation must already have been converted by
    the transaction adapter to a part-rest pose. No ligation to nearby frames is
    inferred. Existing domain traversal, phases and parity come from the builder.
    """
    translation = _finite_vector(translation_nm, 3)
    rotation = _finite_vector(rotation_xyzw, 4)
    if abs(sum(v*v for v in rotation)-1) > 1e-6:
        raise ValueError('placement quaternion must be unit length')
    identifier = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())
    frame = LatticeFrame(id=identifier, plane=plane, placement_cluster_id=cluster_id)
    bundle, helices = _canonical_bundle(design, cells, length_bp, plane, identifier, name)
    placement = ClusterRigidTransform(id=cluster_id, name=name,
        helix_ids=[h.id for h in helices], translation=translation, rotation=rotation,
        pivot=[0, 0, 0], auto_created=False)
    return design.copy_with(helices=[*design.helices, *helices],
        strands=[*design.strands, *bundle.strands],
        lattice_frames=[*design.lattice_frames, frame],
        cluster_transforms=[*design.cluster_transforms, placement])


def append_frame_cell(design, frame_id, row, col, *, length_bp=42, populate_strands=False):
    """Add a canonical local cell to one existing frame and its placement cluster."""
    from backend.core.constants import BDNA_RISE_PER_BP
    frames = [f for f in design.lattice_frames if f.id == frame_id]
    if len(frames) != 1:
        raise ValueError('unknown lattice frame')
    frame = frames[0]
    members = [h for h in design.helices if h.lattice_frame_id == frame_id]
    if any(h.grid_pos == (row, col) for h in members):
        raise ValueError('cell already occupied in this lattice frame')
    validate_painted_footprint({'lattice_type': design.lattice_type.value, 'cells': [[row,col]]})
    reference = min(members, key=lambda h: abs(h.grid_pos[0]-row)+abs(h.grid_pos[1]-col)) if members else None
    offset = reference.bp_start * BDNA_RISE_PER_BP if reference else 0
    length = reference.length_bp if reference else length_bp
    if type(length) is not int or not 1 <= length <= 1_000_000:
        raise ValueError('invalid helix length')
    bundle = make_bundle_design([(row,col)],length,plane=frame.plane,
        offset_nm=offset,id_suffix='_'+str(uuid.uuid4()),lattice_type=design.lattice_type)
    helix = bundle.helices[0].model_copy(update={'lattice_frame_id':frame_id,'grid_pos':(row,col)})
    clusters = [c.model_copy(update={'helix_ids':[*c.helix_ids,helix.id]})
                if c.id == frame.placement_cluster_id else c for c in design.cluster_transforms]
    return design.copy_with(helices=[*design.helices,helix],
        strands=[*design.strands,*(bundle.strands if populate_strands else [])],
        cluster_transforms=clusters), helix


def register_created_bundle_frames(design, plane, cells):
    """Attach canonical cells, placement clusters and identities to a fresh bundle.

    Source plane comes from the authoring request, never inferred from the view.
    Preserve all existing topology, IDs and rigid transforms. Disconnected bodies
    need separate identities because their placement clusters can move apart.
    """
    if design.lattice_frames or any(h.lattice_frame_id for h in design.helices):
        raise ValueError('fresh bundle already has lattice frame identities')
    from backend.core.cluster_autodetect import _cluster_bundle_regions, with_default_cluster
    validate_painted_footprint({'lattice_type':design.lattice_type.value, 'cells':[list(c) for c in cells]})
    design = design.copy_with(helices=[h.model_copy(update={'grid_pos':tuple(cell)})
        for h, cell in zip(design.helices, cells, strict=True)])
    design = with_default_cluster(_cluster_bundle_regions(design))
    membership = {}
    frames = []
    for cluster in design.cluster_transforms:
        frame = LatticeFrame(id=str(uuid.uuid4()), plane=plane, placement_cluster_id=cluster.id)
        for identifier in cluster.helix_ids:
            if identifier in membership:
                raise ValueError('fresh bundle has ambiguous placement membership')
            membership[identifier] = frame.id
        frames.append(frame)
    if any(h.id not in membership or h.grid_pos is None for h in design.helices):
        raise ValueError('fresh bundle requires canonical cells and placement membership')
    return design.copy_with(lattice_frames=frames,
        helices=[h.model_copy(update={'lattice_frame_id':membership[h.id]}) for h in design.helices])
