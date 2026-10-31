"""Geometric clearance for attachment authoring (not a physical relaxation)."""

import numpy as np
from scipy.spatial import cKDTree


def protein_points(design, geometry):
    from backend.core.protein import build_protein_attachment_atoms

    # Visibility is a display choice, never an excluded-volume choice.
    visible = design.model_copy(
        update={
            "protein_attachments": [
                a.model_copy(update={"visible": True})
                for a in design.protein_attachments
            ]
        }
    )
    atoms, _, _ = build_protein_attachment_atoms(visible, geometry=geometry)
    clouds = [
        np.asarray([[a.x, a.y, a.z] for a in atoms], dtype=float).reshape((-1, 3))
    ]
    for particle in design.nanoparticles:
        if particle.coating:
            xyz = np.asarray([[a.x, a.y, a.z] for a in particle.coating.protein.atoms])
            for pose in particle.coating.poses:
                matrix = particle.pose.to_array() @ pose.to_array()
                clouds.append(xyz @ matrix[:3, :3].T + matrix[:3, 3])
    return np.concatenate(clouds)


def duplex_obstacles(geometry, version, root, proteins=()):
    host_strands = {
        n["strand_id"] for n in geometry if n.get("overhang_id") == version.overhang_id
    }
    points = np.asarray(
        [
            n[key]
            for n in geometry
            if n.get("strand_id") != version.strand_id
            and n.get("overhang_id") != version.overhang_id
            for key in ("backbone_position", "base_position")
            if n.get("overhang_id") is not None
            or n.get("strand_id") not in host_strands
            or np.linalg.norm(np.asarray(n[key]) - root) > 2.0
        ],
        dtype=float,
    ).reshape((-1, 3))
    # Only the covalent host receives the near-root contact exemption.
    return cKDTree(np.concatenate([points, np.asarray(proteins).reshape((-1, 3))]))


def particle_clearance(design, geometry, particle_id):
    particle = next(p for p in design.nanoparticles if p.id == particle_id)
    center = particle.pose.to_array()[:3, 3]
    points = np.asarray(
        [n[k] for n in geometry for k in ("backbone_position", "base_position")]
    )
    distances = [
        float(np.linalg.norm(points - center, axis=1).min()) - particle.diameter_nm / 2
    ]
    proteins = protein_points(design, geometry)
    if len(proteins):
        distances.append(
            float(np.linalg.norm(proteins - center, axis=1).min())
            - particle.diameter_nm / 2
            - 0.2
        )
    for other in design.nanoparticles:
        if other.id != particle_id:
            distances.append(
                float(np.linalg.norm(other.pose.to_array()[:3, 3] - center))
                - (particle.diameter_nm + other.diameter_nm) / 2
            )
    return min(distances)
