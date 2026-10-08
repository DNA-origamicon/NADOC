"""Independent copies of rigid elements and their owned conjugate oligos."""

import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.models import (
    Design,
    Mat4x4,
    NucleotideTransform,
    ProteinTargetFree,
    Vec3,
)


def paste_elements(design, source, protein_ids, nanoparticle_ids, paste_index=1):
    proteins = [a for a in source.protein_attachments if a.id in protein_ids]
    particles = [p for p in source.nanoparticles if p.id in nanoparticle_ids]
    if len(proteins) != len(set(protein_ids)) or len(particles) != len(
        set(nanoparticle_ids)
    ):
        raise ValueError("Copied element no longer exists in the snapshot.")
    if not proteins and not particles:
        raise ValueError("Select a nanoparticle or protein to copy.")
    conjugations = [
        c
        for c in source.nanoparticle_conjugations
        if c.nanoparticle_id in nanoparticle_ids
    ]
    sids = {a.binder_strand_id for a in proteins if a.binder_strand_id}
    sids.update(r.strand_id for c in conjugations for r in c.surface_strands)
    sids.update(r.strand_id for p in particles for r in p.biotin_dna)
    strands = [s for s in source.strands if s.id in sids]
    hids = {d.helix_id for s in strands for d in s.domains}
    helices = [h for h in source.helices if h.id in hids]
    overhangs = [o for o in source.overhangs if o.strand_id in sids]
    extensions = [e for e in source.extensions if e.strand_id in sids]
    groups = [g for g in source.staple_groups if sids.intersection(g.strand_ids)]
    records = [
        *proteins,
        *particles,
        *conjugations,
        *strands,
        *helices,
        *overhangs,
        *extensions,
        *groups,
    ]
    ids = {r.id: str(uuid.uuid4()) for r in records}
    for s in strands:
        for d in s.domains:
            if d.overhang_id and d.overhang_id not in ids:
                ids[d.overhang_id] = str(uuid.uuid4())
    for o in overhangs:
        for sub in o.sub_domains:
            ids[sub.id] = str(uuid.uuid4())
    # NP movement recognizes its private helices by prefix.
    for h in helices:
        if h.id.startswith("__np__") or any(
            r.helix_id == h.id for c in conjugations for r in c.surface_strands
        ):
            ids[h.id] = "__np__" + ids[h.id]

    def remap(value):
        if isinstance(value, str):
            return ids.get(value, value)
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value

    def clone(obj):
        return type(obj).model_validate(remap(obj.model_dump(mode="json")))

    from backend.core.design_geometry import fitting_geometry

    geometry = (
        fitting_geometry(source)
        if strands or any(a.target.kind != "free" for a in proteins)
        else []
    )
    points = [n["backbone_position"] for n in geometry if n.get("strand_id") in sids]
    for p in particles:
        center = p.pose.to_array()[:3, 3]
        points.extend([center - p.diameter_nm / 2, center + p.diameter_nm / 2])
    from backend.core.protein import (
        compose_protein_world_transform,
        resolve_overhang_anchor,
    )

    assets = {a.id: a for a in source.protein_assets}
    worlds = {}
    for a in proteins:
        tip, outward = (
            resolve_overhang_anchor(geometry, a.target.overhang_id, a.target.attach_end)
            if a.target.kind == "overhang"
            else (None, None)
        )
        world = compose_protein_world_transform(assets[a.asset_id], a, tip, outward)
        worlds[a.id] = world
        points.extend(
            (world @ np.array([atom.x, atom.y, atom.z, 1.0]))[:3]
            for atom in assets[a.asset_id].atoms
        )
    width = float(np.ptp(np.asarray(points)[:, 0])) if points else 0.0
    offset = np.array([(width + 5.0) * paste_index, 0.0, 0.0])
    shift = np.eye(4)
    shift[:3, 3] = offset
    copied_helices = [clone(h) for h in helices]
    for h in copied_helices:
        for field in ("axis_start", "axis_end"):
            v = getattr(h, field)
            setattr(
                h,
                field,
                Vec3(**dict(zip(("x", "y", "z"), np.array([v.x, v.y, v.z]) + offset))),
            )
        h.grid_pos = None
        h.lattice_frame_id = None
        for residue in h.native_residues:
            residue.atoms = {
                k: Vec3(x=v.x + offset[0], y=v.y, z=v.z)
                for k, v in residue.atoms.items()
            }
    copied_strands = [clone(s) for s in strands]
    for s in copied_strands:
        for d in s.domains:
            d.binds_overhang_id = None
    copied_overhangs = [clone(o) for o in overhangs]
    for o in copied_overhangs:
        o.rotation = [0.0, 0.0, 0.0, 1.0]
        o.translation = [0.0, 0.0, 0.0]
        o.parent_overhang_id = None
    fragment = Design(
        helices=copied_helices, strands=copied_strands, overhangs=copied_overhangs
    )
    # Preserve the exact displayed DNA pose, including bound, rotated and deformed handles.
    original = {
        (ids[n["strand_id"]], n["bp_index"], n.get("copy_k", n.get("copy", 0))): n
        for n in geometry
        if n.get("strand_id") in sids
    }
    poses = []

    def frame(n):
        z = np.asarray(n["axis_tangent"])
        z = z / np.linalg.norm(z)
        x = np.asarray(n["base_normal"])
        x = x - z * np.dot(x, z)
        x /= np.linalg.norm(x)
        return np.column_stack((x, np.cross(z, x), z))

    for n in fitting_geometry(fragment):
        old = original.get(
            (n.get("strand_id"), n["bp_index"], n.get("copy_k", n.get("copy", 0)))
        )
        if old is None:
            continue
        delta = np.asarray(old["backbone_position"]) + offset - n["backbone_position"]
        rotation = frame(old) @ frame(n).T
        if np.linalg.norm(delta) < 1e-8 and np.linalg.norm(rotation - np.eye(3)) < 1e-8:
            continue
        poses.append(
            NucleotideTransform(
                kind="base",
                helix_id=n["helix_id"],
                bp_index=n["bp_index"],
                direction=n["direction"],
                copy_k=n.get("copy_k", n.get("copy", 0)),
                pivot=n["backbone_position"],
                translation=delta.tolist(),
                rotation=Rotation.from_matrix(rotation).as_quat().tolist(),
            )
        )
    copied_proteins = []
    for a in proteins:
        copy = clone(a)
        copy.target = ProteinTargetFree()
        copy.pose = Mat4x4.from_array(shift @ worlds[a.id])
        copied_proteins.append(copy)
    copied_particles = [clone(p) for p in particles]
    for old, new in zip(particles, copied_particles):
        new.pose = Mat4x4.from_array(shift @ old.pose.to_array())
    copied_conjugations = [clone(c) for c in conjugations]
    for c in copied_conjugations:
        for r in c.surface_strands:
            r.bound_overhang_id = None
    copied_groups = [clone(g) for g in groups]
    for old, new in zip(groups, copied_groups):
        new.strand_ids = [ids[s] for s in old.strand_ids if s in sids]
    # Assets are immutable, but a clipboard also survives deletion of its source.
    existing_assets = {a.id for a in design.protein_assets}
    additions = dict(
        helices=copied_helices,
        strands=copied_strands,
        overhangs=copied_overhangs,
        extensions=[clone(e) for e in extensions],
        staple_groups=copied_groups,
        protein_attachments=copied_proteins,
        nanoparticles=copied_particles,
        nanoparticle_conjugations=copied_conjugations,
        nucleotide_transforms=poses,
        protein_assets=[
            assets[a]
            for a in {p.asset_id for p in proteins}
            if a not in existing_assets
        ],
    )
    result = design.model_copy(
        update={
            key: [*getattr(design, key), *items] for key, items in additions.items()
        }
    )
    return result, [{"kind": "protein", "id": a.id} for a in copied_proteins] + [
        {"kind": "nanoparticle", "id": p.id} for p in copied_particles
    ]


def move_free_conjugate(design, strand_id, delta):
    """Move a detached conjugate with its rigid protein, composing saved residue poses."""
    from backend.core.design_geometry import fitting_geometry

    existing = {t.target_key(): t for t in design.nucleotide_transforms}
    for n in fitting_geometry(design):
        if n.get("strand_id") != strand_id:
            continue
        key = (
            "base",
            n["helix_id"],
            n["bp_index"],
            n["direction"],
            n.get("copy_k", n.get("copy", 0)),
        )
        old = existing.get(key)
        matrix = np.eye(4)
        if old:
            matrix[:3, :3] = Rotation.from_quat(old.rotation).as_matrix()
            pivot = np.asarray(old.pivot)
            matrix[:3, 3] = pivot - matrix[:3, :3] @ pivot + old.translation
        matrix = delta @ matrix
        existing[key] = NucleotideTransform(
            id=old.id if old else str(uuid.uuid4()),
            kind="base",
            helix_id=key[1],
            bp_index=key[2],
            direction=key[3],
            copy_k=key[4],
            translation=matrix[:3, 3].tolist(),
            rotation=Rotation.from_matrix(matrix[:3, :3]).as_quat().tolist(),
        )
    design.nucleotide_transforms = list(existing.values())
