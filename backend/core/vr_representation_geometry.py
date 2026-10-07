"""Desktop-derived additional VR geometry, immutable and display-only.

Mesh topology is built once in the natural pose. Display transforms move its
vertices using canonical nucleotide displacements, keeping stable face identities.
"""

import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
REPRESENTATIONS = (
    "cylinders",
    "full",
    "ballstick",
    "stick",
    "beads",
    "vdw",
    "hull-prism",
    "surface",
    "mrdna-coarse",
    "mrdna-fine",
    "oxdna",
    "surface-detail",
)


def _surface_owners(surface, source):
    """Keep desktop strand/nucleotide ownership when anchoring VR surface vertices.

    A base-facing vertex can be nearer the opposite strand's backbone. Spatial
    lookup is only a tie-break within the authored identity (including copies),
    or a fallback for older meshes without identity metadata.
    """
    anchors = np.asarray([n["backbone_position"] for n in source])
    by_strand, by_nucleotide = {}, {}
    for i, n in enumerate(source):
        sid = n.get("strand_id", "")
        direction = n.get("direction", "FORWARD")
        direction = getattr(direction, "value", direction)
        nuc = n.get("scalar_key") or f'{n.get("helix_id", "")}:{n.get("bp_index", 0)}:{direction}'
        by_strand.setdefault(sid, []).append(i)
        by_nucleotide.setdefault((sid, nuc), []).append(i)
    vertices = np.asarray(surface.vertices)
    owners = cKDTree(anchors).query(vertices)[1]
    groups = {}
    for i, sid in enumerate(surface.vertex_strand_ids or []):
        nuc = surface.vertex_nuc_ids[i] if surface.vertex_nuc_ids else ""
        groups.setdefault((sid, nuc), []).append(i)
    for identity, rows in groups.items():
        candidates = by_nucleotide.get(identity) or by_strand.get(identity[0])
        if candidates:
            candidates = np.asarray(candidates)
            nearest = cKDTree(anchors[candidates]).query(vertices[rows])[1]
            owners[rows] = candidates[nearest]
    return owners


def build(design, nucleotides, axes, representations=None):
    from backend.api.routes_display_geometry import _build_design_surface_mesh

    from backend.core.vr_scene_projection import normalize_geometry_copy_indices

    nucleotides = normalize_geometry_copy_indices(nucleotides)
    source = [n for n in nucleotides if n.get("backbone_position") is not None]
    if not source:
        return None
    encoded = json.dumps(
        {"design": json.loads(design.to_json()), "geometry": source, "axes": axes, "representations": sorted(representations) if representations is not None else None},
        default=lambda x: x.tolist() if isinstance(x, np.ndarray) else float(x),
    )
    result = subprocess.run(
        ["node", str(ROOT / "frontend/scripts/export-vr-representations.mjs")],
        input=encoded,
        text=True,
        capture_output=True,
        timeout=120,
        check=True,
    )
    desktop = json.loads(result.stdout)
    for rep, detail in [("surface", "coarse"), ("surface-detail", "chimerax")]:
        desktop[rep] = {"vertices": np.empty((0, 3)), "normals": np.empty((0, 3))}
        if representations is None or rep in representations:
            surface = _build_design_surface_mesh(design, 0.20, 0.06, 1.30, 15, detail)
            vertices = np.asarray(surface.vertices)
            normals = np.zeros_like(vertices)
            faces = np.asarray(surface.faces)
            if len(faces):
                triangles = vertices[faces]
                face_normals = np.cross(
                    triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
                )
                for column in range(3):
                    np.add.at(normals, faces[:, column], face_normals)
                normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
            desktop[rep] = {
                "vertices": vertices[faces].reshape(-1, 3),
                "normals": normals[faces].reshape(-1, 3),
                "owners": _surface_owners(surface, source)[faces].reshape(-1),
            }
    desktop["source"] = source
    desktop["anchors"] = np.asarray([n["backbone_position"] for n in source])
    desktop["tree"] = cKDTree(desktop["anchors"])
    return desktop


def records(data, nucleotides):
    """Yield (representation, kind, identity, coordinates, owners, color, normals)."""
    if data is None:
        return

    def key(n):
        return (
            n.get("helix_id"),
            n.get("bp_index"),
            n.get("direction"),
            n.get("copy", 0),
            n.get("strand_id"),
        )

    current = {
        key(n): np.asarray(n["backbone_position"])
        for n in nucleotides
        if n.get("backbone_position") is not None
    }
    offsets = np.asarray(
        [
            current.get(key(n), anchor) - anchor
            for n, anchor in zip(data["source"], data["anchors"])
        ]
    )
    tree = data["tree"]

    def moved(points, owners=None):
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        if owners is None:
            owners = tree.query(points)[1]
        return points + offsets[owners], owners

    for rep, meshes in [
        ("cylinders", data.get("cylinders", [])),
        ("hull-prism", data["hull"]),
        ("surface", [data["surface"]]),
        ("surface-detail", [data["surface-detail"]] if "surface-detail" in data else []),
    ]:
        face_id = 0
        for mesh in meshes:
            points, owners = moved(mesh["vertices"], mesh.get("owners"))
            normals = np.asarray(mesh["normals"]).reshape(-1, 3)
            colors = (
                np.asarray(mesh["colors"]).reshape(-1, 3)
                if mesh.get("colors") is not None
                else None
            )
            # Construct face frames in one NumPy pass; large desktop surfaces
            # have hundreds of thousands of faces in each display pose.
            triangles = points.reshape(-1, 3, 3)
            a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
            face_normals = np.cross(b - a, c - a)
            lengths = np.linalg.norm(face_normals, axis=1)
            valid = lengths > 1e-12
            face_normals[valid] /= lengths[valid, None]
            face_normals[~valid] = normals[::3][~valid]
            frames = np.concatenate(
                ((b + c) * 0.5, b - a, c - a, face_normals * 1e-5), axis=1
            )
            for i in range(0, len(points), 3):
                coords = frames[i // 3]
                color = mesh["palettes"] if rep == "cylinders" else (
                    np.tile(
                        colors[i : i + 3].mean(axis=0)
                        if colors is not None
                        else [0.45, 0.48, 0.52],
                        4,
                    )
                    if rep == "hull-prism"
                    else None
                )
                yield (
                    rep,
                    "B",
                    f"{rep}:face:{face_id}",
                    coords,
                    owners[i : i + 3],
                    color,
                    normals[i : i + 3],
                )
                face_id += 1
    for resolution, radius in [("coarse", 0.55), ("fine", 0.28)]:
        rep = "mrdna-" + resolution
        if resolution not in data["mrdna"]:
            continue
        preview = data["mrdna"][resolution]
        points, owners = moved([[p["x"], p["y"], p["z"]] for p in preview["points"]])
        blue = np.tile([0x58 / 255, 0xA6 / 255, 1], 4)
        pale = np.tile([0xCD / 255, 0xD8 / 255, 0xEE / 255], 4)
        for i, point in enumerate(points):
            yield (
                rep,
                "P",
                f"{rep}:site:{i}",
                np.r_[point, radius],
                [owners[i]],
                blue,
                None,
            )
        for i, (a, b) in enumerate(preview["edges"]):
            yield (
                rep,
                "C",
                f"{rep}:bond:{i}",
                np.r_[points[a], points[b], 0.13],
                [owners[a], owners[b]],
                pale,
                None,
            )
    for group in data["oxdna"]:
        primitive = group["primitive"]
        for i, entry in enumerate(group["entries"]):
            matrix = np.asarray(entry["matrix"]).reshape(4, 4).T
            center = matrix[:3, 3]
            moved_center, owner = moved([center])
            ident = f"oxdna:{primitive}:{i}"
            color = entry["colors"]
            if primitive == "backbone":
                yield (
                    "oxdna",
                    "P",
                    ident,
                    np.r_[moved_center[0], np.linalg.norm(matrix[:3, 0])],
                    owner,
                    color,
                    None,
                )
            elif primitive == "base":
                yield (
                    "oxdna",
                    "B",
                    ident,
                    np.r_[moved_center[0], matrix[:3, :3].T.reshape(-1) * 2],
                    owner,
                    color,
                    None,
                )
            else:
                ends, owners = moved(
                    [center - matrix[:3, 1] * 0.5, center + matrix[:3, 1] * 0.5]
                )
                bottom = group.get("radiusBottom", 1) * np.linalg.norm(matrix[:3, 0])
                top = group.get("radiusTop", 1) * np.linalg.norm(matrix[:3, 0])
                yield (
                    "oxdna",
                    "C",
                    ident,
                    np.r_[ends.reshape(-1), bottom],
                    owners,
                    color,
                    top,
                )


def append_records(
    data,
    nucleotides,
    rotation,
    begin,
    emit,
    lines,
    nucleotide_owner_tokens,
    base_key,
    palette_for_index,
    progress=lambda fraction: None,
):
    from urllib.parse import quote

    if data is None:
        return
    by_key = {base_key(n): i for i, n in enumerate(nucleotides)}
    # Canonical aliases and colors depend on the source nucleotide, not on the
    # number of adjacent surface triangles. Compute each once per display pose.
    source_aliases = [nucleotide_owner_tokens(n) for n in data["source"]]
    source_palettes = [
        palette_for_index(by_key.get(base_key(n), 0)) for n in data["source"]
    ]
    total = (sum(len(m["vertices"]) // 9 for m in data.get("cylinders", []))
             + sum(len(m["vertices"]) // 9 for m in data["hull"])
             + len(data["surface"]["vertices"]) // 3
             + len(data.get("surface-detail", {}).get("vertices", [])) // 3
             + sum(len(p["points"]) + len(p["edges"]) for p in data["mrdna"].values())
             + sum(len(g["entries"]) for g in data["oxdna"]))
    active = None
    for record_index, (rep, kind, identity, coordinates, owners, palette, annotation) in enumerate(records(data, nucleotides)):
        if record_index % 256 == 0:
            progress(record_index / max(1, total))
        if active != rep:
            begin(rep)
            active = rep
        aliases = tuple(
            dict.fromkeys(t for i in owners for t in source_aliases[int(i)])
        )[:8]
        if palette is None:
            color_owner = owners[0]
            if rep in {"surface", "surface-detail"} and len(owners) == 3:
                # Native triangles have one palette. Match desktop crisp zones:
                # majority strand, with a first-corner tie break.
                a, b, c = (data["source"][int(i)].get("strand_id", "") for i in owners)
                if a != b and a != c and b == c:
                    color_owner = owners[1]
            palette = source_palettes[int(color_owner)]
        coords = np.asarray(coordinates).copy()
        if kind == "P":
            coords[:3] = rotation @ coords[:3]
        elif kind == "C":
            coords[:6] = (coords[:6].reshape(2, 3) @ rotation.T).reshape(-1)
        else:
            coords = (coords.reshape(4, 3) @ rotation.T).reshape(-1)
        emit(kind, identity, *coords, *palette, aliases=aliases)
        encoded = quote(identity, safe="-_.:~")
        if kind == "B" and annotation is not None:
            normal_values = (np.asarray(annotation) @ rotation.T).reshape(-1)
            lines.append(f"N {encoded} " + " ".join(f"{v:.7g}" for v in normal_values))
        elif kind == "C" and annotation is not None:
            lines.append(f"U {encoded} {annotation:.7g}")
