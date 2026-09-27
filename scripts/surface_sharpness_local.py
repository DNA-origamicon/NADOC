"""Read-only local field/atom attribution for the surface sharpness audit."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import map_coordinates, zoom
from backend.core.atomistic import build_atomistic_model
from backend.core.junction_topology import crossover_connectors
from backend.core.surface import _sphere_struct, _stamp_spheres
from backend.core.surface_acceleration import close_volume
from backend.core.surface_field import continuous_surface_field


def enrich_hotspots(design, positions, radii, strand_ids, raw, final, points, probe):
    atoms = build_atomistic_model(design, fast_bridges=True).atoms

    def key(a):
        direction = getattr(a.direction, "value", a.direction)
        return (a.strand_id, a.helix_id, a.bp_index, direction, a.name)

    atom_index = {key(a): a for a in atoms}
    segments = {}
    for c in crossover_connectors(design):
        a = atom_index.get((c.strand_id, c.from_helix, c.from_bp, c.from_dir, "C3'"))
        b = atom_index.get((c.strand_id, c.to_helix, c.to_bp, c.to_dir, "C5'"))
        if a is not None and b is not None:
            segments.setdefault(c.strand_id, []).append(
                (c, np.array([a.x, a.y, a.z]), np.array([b.x, b.y, b.z]))
            )
    groups = {}
    for i, sid in enumerate(strand_ids):
        groups.setdefault(sid, []).append(i)
    atom_groups = {}
    for a in atoms:
        atom_groups.setdefault(a.strand_id, []).append(a)
    for point_index, point in enumerate(points):
        pos = np.array(point["position_nm"])
        sid = point["strand_id"]
        nearest = None
        for c, a, b in segments.get(sid, []):
            ab = b - a
            t = np.clip((pos - a) @ ab / max(ab @ ab, 1e-30), 0, 1)
            distance = float(np.linalg.norm(pos - (a + t * ab)))
            if nearest is None or distance < nearest["distance_to_C3_C5_segment_nm"]:
                nearest = {
                    "id": c.crossover_id,
                    "from": [c.from_helix, c.from_bp, c.from_dir],
                    "to": [c.to_helix, c.to_bp, c.to_dir],
                    "distance_to_C3_C5_segment_nm": distance,
                }
        point["nearest_crossover"] = nearest
        local_atoms = atom_groups[sid]
        ap = np.array([[a.x, a.y, a.z] for a in local_atoms])
        distances = np.linalg.norm(ap - pos, axis=1)
        point["nearest_atoms"] = [
            {
                "name": local_atoms[i].name,
                "element": local_atoms[i].element,
                "helix": local_atoms[i].helix_id,
                "bp": local_atoms[i].bp_index,
                "distance_nm": float(distances[i]),
            }
            for i in np.argsort(distances)[:5]
        ]
        # Reconstruct a bounded field patch with the same global lattice and a
        # conservative full morphology/filter halo. Only this strand contributes.
        gs = 0.05
        center = np.rint(pos / gs).astype(int)
        radius = int(np.ceil(2 * probe / gs)) + 12
        lo = center - radius
        hi = center + radius
        rows = np.asarray(groups[sid])
        seeds = np.rint(positions[rows] / gs).astype(int)
        rows_keep = np.all((seeds >= lo - 5) & (seeds <= hi + 5), axis=1)
        seeds = seeds[rows_keep]
        rs = np.round(radii[rows][rows_keep], 6)
        grid = np.zeros(tuple(hi - lo + 1), bool)
        for r in np.unique(rs):
            _stamp_spheres(grid, seeds[rs == r] - lo, r / gs)
        if probe:
            open_field = continuous_surface_field(grid, grid_spacing=gs)
            point["field_without_probe_closing_at_hotspot"] = float(
                map_coordinates(open_field, ((pos / gs - lo)[:, None]), order=1)[0]
            )
            grid = close_volume(grid, _sphere_struct(probe / gs))
        field = continuous_surface_field(grid, grid_spacing=gs)
        point["closed_field_at_hotspot"] = float(
            map_coordinates(field, ((pos / gs - lo)[:, None]), order=1)[0]
        )
        # Diagnose meshing independently from atom sampling: resample the SAME
        # scalar field, with linear vs cubic interpolation, then re-extract locally.
        if point_index == 0 or (
            point["before_mesh_smoothing_deg"] < 60
            and not any(
                "extraction_comparison" in p and p["before_mesh_smoothing_deg"] < 60
                for p in points[:point_index]
            )
        ):
            from skimage.measure import marching_cubes
            from backend.core.surface import SurfaceMesh
            from backend.core.surface_quality import surface_quality

            comparison = []
            for label, order in [
                ("native_grid", None),
                ("half_spacing_linear", 1),
                ("half_spacing_cubic", 3),
            ]:
                refined = (
                    field
                    if order is None
                    else zoom(
                        field,
                        (2 * np.array(field.shape) - 1) / np.array(field.shape),
                        order=order,
                    )
                )
                spacing = gs if order is None else gs / 2
                v, f, _, _ = marching_cubes(refined, 0.5, allow_degenerate=False)
                v = v * spacing + lo * gs
                keep = np.linalg.norm(v[f].mean(axis=1) - pos, axis=1) < 0.18
                q = surface_quality(SurfaceMesh(v, f[keep], []), hotspot_limit=0)
                comparison.append(
                    {
                        "method": label,
                        "max_turn_deg": q["normal_turn_max_deg"],
                        "edges_over_60": q["thresholds"]["60"]["edges"],
                        "edges_over_90": q["thresholds"]["90"]["edges"],
                    }
                )
            point["extraction_comparison"] = comparison
        gradient = np.gradient(field, gs)
        face_ids = point["face_indices"]
        for name, m in [("raw", raw), ("final", final)]:
            centroids = m.vertices[m.faces[face_ids]].mean(axis=1)
            coords = (centroids / gs - lo).T
            g = np.column_stack(
                [map_coordinates(v, coords, order=1, mode="nearest") for v in gradient]
            )
            magnitude = np.linalg.norm(g, axis=1)
            turn = float(
                np.degrees(
                    np.arccos(
                        np.clip((g[0] @ g[1]) / max(magnitude.prod(), 1e-30), -1, 1)
                    )
                )
            )
            point[name + "_field_gradient_turn_deg"] = turn
            point[name + "_field_gradient_magnitude_per_nm"] = magnitude.tolist()
            point[name + "_field_values_at_face_centroids"] = map_coordinates(
                field, coords, order=1, mode="nearest"
            ).tolist()
    return points


def plot_hotspot(raw, final, point, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    center = np.asarray(point["position_nm"])
    sid = point["strand_id"]
    owner = np.array(raw.vertex_strand_ids) == sid
    face_keep = np.all(owner[raw.faces], axis=1) & (
        np.linalg.norm(raw.vertices[raw.faces].mean(axis=1) - center, axis=1) < 0.23
    )
    fig = plt.figure(figsize=(10, 5))
    for col, (title, m) in enumerate(
        [("Before mesh smoothing", raw), ("After 4 iterations", final)], 1
    ):
        ax = fig.add_subplot(1, 2, col, projection="3d")
        triangles = m.vertices[m.faces[face_keep]] - center
        ax.add_collection3d(
            Poly3DCollection(
                triangles,
                facecolors="#a7c9d9",
                edgecolors="#456070",
                linewidths=0.35,
                alpha=0.85,
            )
        )
        a, b = point["vertex_indices"]
        edge = m.vertices[[a, b]] - center
        ax.plot(*edge.T, color="red", linewidth=3)
        for setter in [ax.set_xlim, ax.set_ylim, ax.set_zlim]:
            setter(-0.23, 0.23)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=15, azim=-75)
        ax.set_title(title)
        ax.set_xlabel("x (nm)")
        ax.set_ylabel("y (nm)")
        ax.set_zlabel("z (nm)")
    fig.suptitle(
        f"Same mesh edge: {point['before_mesh_smoothing_deg']:.1f}° → {point['normal_turn_deg']:.1f}°"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
