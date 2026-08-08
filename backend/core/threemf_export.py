"""
3MF export of the molecular surface for multi-colour 3D printing.

STL carries no colour, so multi-material prints need the 3MF format (a zipped
XML package; an ISO standard read natively by PrusaSlicer, Bambu Studio,
OrcaSlicer and Cura).

Colour-encoding choice
----------------------
3MF can encode colour two ways:

* **Per-triangle painting** (``mmu_segmentation`` / ``paint_color`` attributes)
  — slicer-specific and *not* honoured when importing a 3MF authored by another
  tool.  PrusaSlicer opens such a file as if it were a plain STL.
* **Base material per object/part** (Materials & Properties extension) — every
  slicer reads this, and each part is auto-mapped to a filament slot.

We therefore use the second path: the surface is split into one sub-object per
colour group, each tagged with a coloured ``<base>`` material.  The sub-objects
are gathered as ``<component>``s of a single assembly object so they share one
coordinate system (they cannot drift apart in the slicer).  Each part is an
*open* shell along the colour seams, but their union is watertight — exactly how
every "split a model by colour" workflow behaves.

Like ``stl_export``, geometry is auto-scaled nm → mm (3MF declares millimetre
units explicitly, so there is no ambiguity for the slicer).
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from backend.core.models import Design
from backend.core.surface import SurfaceMesh
from backend.core.stl_export import auto_scale, _signed_volume  # noqa: F401 (re-export auto_scale)

__all__ = [
    "auto_scale",
    "scaffold_staple_groups",
    "scaffold_staple_colored_groups",
    "compute_staple_coloring",
    "export_3mf",
    "export_3mf_parts",
]


# ── Colour-group assignment ──────────────────────────────────────────────────


def scaffold_staple_groups(
    mesh: SurfaceMesh, design: Design
) -> tuple[np.ndarray, list[str], list[str]]:
    """Two-colour split: scaffold surface vs. everything else (staples).

    Returns ``(face_group, names, colors)`` where ``face_group`` is an int array
    of length ``len(mesh.faces)`` with values in ``{0, 1}`` (0 = scaffold,
    1 = staples), and ``names`` / ``colors`` are the per-group labels and
    ``#RRGGBB`` hex colours (matching the on-screen scaffold/staple palette).
    """
    names = ["scaffold", "staples"]
    colors = ["#29B6F6", "#FF6B6B"]

    faces = mesh.faces
    if faces.shape[0] == 0:
        return np.zeros(0, dtype=np.int8), names, colors

    scaffold_ids = {s.id for s in design.strands if s.is_scaffold and s.id}

    # Per-vertex: 0 if the nearest strand is the scaffold, else 1 (staple/unassigned).
    vert_is_staple = np.fromiter(
        (0 if sid in scaffold_ids else 1 for sid in mesh.vertex_strand_ids),
        dtype=np.int8,
        count=len(mesh.vertex_strand_ids),
    )

    # A face's group = majority vote of its three vertices (ties → staple).
    tri = vert_is_staple[faces]  # (M, 3) of {0,1}
    face_group = (tri.sum(axis=1) >= 2).astype(np.int8)

    return face_group, names, colors


# Distinct staple-set colours (from the on-screen palette): red / green / yellow.
_STAPLE_SET_COLORS = ["#FF6B6B", "#6BCB77", "#FFD93D"]


def _staple_adjacency(faces: np.ndarray, vert_code: np.ndarray) -> np.ndarray:
    """Unique staple-vs-staple border pairs (regions that touch on the surface).

    ``vert_code[i]`` is the staple index of vertex ``i`` (>= 0), or < 0 for
    scaffold / unassigned vertices.  Two staples are *adjacent* iff some mesh
    edge joins a vertex of one to a vertex of the other — i.e. their coloured
    regions share a border on the printed surface.  Returns an ``(E, 2)`` array
    of sorted, de-duplicated staple-index pairs.
    """
    e = np.concatenate(
        [faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0
    )  # (3M, 2) every directed half-edge
    cu = vert_code[e[:, 0]]
    cv = vert_code[e[:, 1]]
    mask = (cu >= 0) & (cv >= 0) & (cu != cv)
    if not mask.any():
        return np.zeros((0, 2), dtype=np.int64)
    pairs = np.sort(np.stack([cu[mask], cv[mask]], axis=1), axis=1)
    return np.unique(pairs, axis=0)


def _color_staples(n: int, pairs: np.ndarray, k: int) -> tuple[list[int], int]:
    """Greedy ``k``-colour a staple adjacency graph; minimise same-colour borders.

    Largest-degree-first ordering, each node taking the colour shared by the
    fewest already-coloured neighbours (ties broken toward the globally
    least-used colour, so the three sets stay balanced).  Returns
    ``(color_per_staple, n_conflicts)`` where ``n_conflicts`` is the number of
    adjacency pairs that still share a colour (0 when a proper k-colouring was
    found; > 0 only in dense regions a 3-colouring cannot resolve).
    """
    adj: list[set[int]] = [set() for _ in range(n)]
    for a, b in pairs:
        adj[int(a)].add(int(b))
        adj[int(b)].add(int(a))

    order = sorted(range(n), key=lambda s: -len(adj[s]))
    color = [-1] * n
    global_count = [0] * k
    for s in order:
        nb_count = [0] * k
        for nb in adj[s]:
            c = color[nb]
            if c >= 0:
                nb_count[c] += 1
        fewest = min(nb_count)
        cands = [c for c in range(k) if nb_count[c] == fewest]
        best = min(cands, key=lambda c: global_count[c])
        color[s] = best
        global_count[best] += 1

    conflicts = int(sum(1 for a, b in pairs if color[int(a)] == color[int(b)]))
    return color, conflicts


def compute_staple_coloring(
    mesh: SurfaceMesh, design: Design, n_staple_colors: int = 3
) -> tuple[dict[str, int], list[str], list[str], dict]:
    """Map-colour staples → ``(strand_to_group, names, colors, stats)``.

    Every staple strand in the design is coloured into one of ``n_staple_colors``
    sets (group 1..k); the scaffold is group 0.  Adjacency for the colouring is
    "their surface regions touch" — staples joined by a surface mesh edge get
    different colours (graph map-colouring; see ``_staple_adjacency`` /
    ``_color_staples``).  Staples that never reach the surface are isolated nodes
    that simply balance the sets.  ``strand_to_group`` maps every scaffold/staple
    strand id to its group index; ``stats`` holds ``n_staples``, ``conflicts``
    (unavoidable same-colour touching borders) and per-set ``counts``.
    """
    k = max(1, min(int(n_staple_colors), len(_STAPLE_SET_COLORS)))
    names = ["scaffold"] + [f"staples {chr(ord('A') + i)}" for i in range(k)]
    colors = ["#29B6F6"] + _STAPLE_SET_COLORS[:k]
    stats = {"n_staples": 0, "conflicts": 0, "counts": [0] * k}

    scaffold_ids = {s.id for s in design.strands if s.is_scaffold and s.id}
    staple_ids = [s.id for s in design.strands if s.id and not s.is_scaffold]
    sid_to_staple = {sid: i for i, sid in enumerate(staple_ids)}

    strand_to_group: dict[str, int] = {sid: 0 for sid in scaffold_ids}
    stats["n_staples"] = len(staple_ids)
    if not staple_ids:
        return strand_to_group, names, colors, stats

    # Per-surface-vertex code: -1 scaffold, -2 unassigned, >= 0 a staple index.
    vert_code = np.fromiter(
        (
            -1 if sid in scaffold_ids else (sid_to_staple.get(sid, -2) if sid else -2)
            for sid in mesh.vertex_strand_ids
        ),
        dtype=np.int64,
        count=len(mesh.vertex_strand_ids),
    )
    pairs = (
        _staple_adjacency(mesh.faces, vert_code)
        if mesh.faces.shape[0]
        else np.zeros((0, 2), dtype=np.int64)
    )
    staple_color, conflicts = _color_staples(len(staple_ids), pairs, k)
    stats["conflicts"] = conflicts
    for c in staple_color:
        stats["counts"][c] += 1
    for sid, idx in sid_to_staple.items():
        strand_to_group[sid] = 1 + staple_color[idx]

    return strand_to_group, names, colors, stats


def scaffold_staple_colored_groups(
    mesh: SurfaceMesh, design: Design, n_staple_colors: int = 3
) -> tuple[np.ndarray, list[str], list[str], dict]:
    """Per-face group labels for the single-mesh split path (4 groups for k=3).

    Thin wrapper over :func:`compute_staple_coloring`: maps each surface vertex
    to its strand's group, then assigns each face the group most of its three
    vertices belong to.  ``face_group[i]`` ∈ {0=scaffold, 1..k=staple sets}.
    (The manifold export uses :func:`compute_staple_coloring` +
    ``compute_colored_surfaces`` instead; this remains for the simpler split.)
    """
    strand_to_group, names, colors, stats = compute_staple_coloring(
        mesh, design, n_staple_colors
    )
    k = len(colors) - 1
    faces = mesh.faces
    if faces.shape[0] == 0:
        return np.zeros(0, dtype=np.int8), names, colors, stats

    # Per-vertex group: scaffold → 0, staple → its set, unassigned → set A (1).
    vert_group = np.fromiter(
        (strand_to_group.get(sid, 1) for sid in mesh.vertex_strand_ids),
        dtype=np.int64,
        count=len(mesh.vertex_strand_ids),
    )
    g = vert_group[faces]  # (M, 3)
    counts = np.zeros((faces.shape[0], k + 1), dtype=np.int64)
    rows = np.arange(faces.shape[0])
    for j in range(3):
        counts[rows, g[:, j]] += 1
    face_group = counts.argmax(axis=1).astype(np.int8)

    return face_group, names, colors, stats


# ── 3MF model XML ────────────────────────────────────────────────────────────

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_MAT_NS = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"


def _xml_attr(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _hex_rgba(hex_rgb: str) -> str:
    """``#RRGGBB`` → ``#RRGGBBFF`` (3MF displaycolor wants an alpha byte)."""
    h = hex_rgb.lstrip("#").upper()
    if len(h) == 6:
        h += "FF"
    return "#" + h


def _mesh_xml(verts: np.ndarray, faces: np.ndarray) -> str:
    """``<mesh>`` body (vertices + triangles) for one sub-object's geometry."""
    vx = [f'<vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>' for x, y, z in verts]
    tr = [f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces]
    return (
        "<mesh><vertices>" + "".join(vx) + "</vertices>"
        "<triangles>" + "".join(tr) + "</triangles></mesh>"
    )


def _build_model_xml(
    verts: np.ndarray,
    faces: np.ndarray,
    face_group: np.ndarray,
    names: list[str],
    colors: list[str],
    name: str,
) -> str:
    """Assemble the full ``3D/3dmodel.model`` XML for the multi-part surface.

    Each non-empty colour group becomes its own ``<object>`` (re-indexed to only
    the vertices its faces use) with a default base material; an assembly object
    gathers them as components so they share one coordinate frame.
    """
    parts: list[str] = []
    part_object_ids: list[int] = []
    oid = 2  # id 1 reserved for <basematerials>

    for g in range(len(names)):
        group_faces = faces[face_group == g]
        if group_faces.shape[0] == 0:
            continue
        # Re-index to the vertices this group actually uses.
        used = np.unique(group_faces)
        remap = np.full(verts.shape[0], -1, dtype=np.int64)
        remap[used] = np.arange(used.shape[0])
        body = _mesh_xml(verts[used], remap[group_faces])
        parts.append(
            f'<object id="{oid}" type="model" pid="1" pindex="{g}" '
            f'name="{_xml_attr(names[g])}">{body}</object>'
        )
        part_object_ids.append(oid)
        oid += 1

    bases = "".join(
        f'<base name="{_xml_attr(names[g])}" displaycolor="{_hex_rgba(colors[g])}"/>'
        for g in range(len(names))
    )
    components = "".join(f'<component objectid="{pid}"/>' for pid in part_object_ids)
    assembly_id = oid
    assembly = (
        f'<object id="{assembly_id}" type="model" name="{_xml_attr(name)}">'
        f"<components>{components}</components></object>"
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE_NS}" xmlns:m="{_MAT_NS}">'
        "<resources>"
        f'<basematerials id="1">{bases}</basematerials>'
        + "".join(parts)
        + assembly
        + "</resources>"
        f'<build><item objectid="{assembly_id}"/></build>'
        "</model>"
    )


# ── Zip container ────────────────────────────────────────────────────────────

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


def _zip_store(files: list[tuple[str, bytes]]) -> bytes:
    """Minimal deflate ZIP archive holding the named files (no external deps)."""
    out = bytearray()
    central = bytearray()
    records: list[tuple[str, int, int, int, int]] = []

    for arcname, data in files:
        name_b = arcname.encode("utf-8")
        crc = zlib.crc32(data) & 0xFFFFFFFF
        comp = zlib.compressobj(6, zlib.DEFLATED, -15)
        body = comp.compress(data) + comp.flush()
        offset = len(out)
        out += struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0,
            8,
            0,
            0,
            crc,
            len(body),
            len(data),
            len(name_b),
            0,
        )
        out += name_b + body
        records.append((arcname, offset, crc, len(body), len(data)))

    for arcname, offset, crc, csize, usize in records:
        name_b = arcname.encode("utf-8")
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0,
            8,
            0,
            0,
            crc,
            csize,
            usize,
            len(name_b),
            0,
            0,
            0,
            0,
            0,
            offset,
        )
        central += name_b

    cd_offset = len(out)
    out += central
    out += struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        len(records),
        len(records),
        len(central),
        cd_offset,
        0,
    )
    return bytes(out)


def export_3mf(
    mesh: SurfaceMesh,
    face_group: np.ndarray,
    names: list[str],
    colors: list[str],
    scale: float = 1.0,
    name: str = "surface",
) -> bytes:
    """Serialise a SurfaceMesh as a multi-colour 3MF (vertices × ``scale``, mm).

    ``face_group`` (length == number of faces) assigns each triangle to colour
    group ``0..len(names)-1``; ``colors[g]`` is the ``#RRGGBB`` for group ``g``.
    """
    verts = mesh.vertices.astype(np.float64) * float(scale)
    faces = mesh.faces.astype(np.int64)
    fg = np.asarray(face_group, dtype=np.int64)

    # Same global orientation safety net as the STL path.
    if faces.shape[0] and _signed_volume(verts, faces) < 0.0:
        faces = faces[:, ::-1]

    model_xml = _build_model_xml(verts, faces, fg, names, colors, name)
    files = [
        ("[Content_Types].xml", _CONTENT_TYPES.encode("utf-8")),
        ("_rels/.rels", _RELS.encode("utf-8")),
        ("3D/3dmodel.model", model_xml.encode("utf-8")),
    ]
    return _zip_store(files)


def export_3mf_parts(
    parts: list[tuple[SurfaceMesh | None, str, str]],
    scale: float = 1.0,
    name: str = "surface",
) -> bytes:
    """Serialise distinct CLOSED part meshes as a manifold multi-material 3MF.

    ``parts`` is a list of ``(mesh, group_name, hex_color)``.  Each non-empty
    part becomes its own ``<object>`` — an independent watertight solid — with a
    default base material; all are gathered as ``<component>``s of one assembly
    object so they stay aligned.  Unlike :func:`export_3mf` (which splits one
    shell into open parts), every object here is closed, and the shared interface
    walls between colours coincide, so the package satisfies the 3MF watertight
    requirement that slicers enforce.
    """
    bases: list[str] = []
    objects: list[str] = []
    comp_ids: list[int] = []
    oid = 2  # id 1 reserved for <basematerials>

    for mesh, gname, color in parts:
        if mesh is None or mesh.faces.shape[0] == 0:
            continue
        verts = mesh.vertices.astype(np.float64) * float(scale)
        faces = mesh.faces.astype(np.int64)
        if _signed_volume(verts, faces) < 0.0:  # outward winding per part
            faces = faces[:, ::-1]
        pindex = len(bases)
        bases.append(
            f'<base name="{_xml_attr(gname)}" displaycolor="{_hex_rgba(color)}"/>'
        )
        objects.append(
            f'<object id="{oid}" type="model" pid="1" pindex="{pindex}" '
            f'name="{_xml_attr(gname)}">{_mesh_xml(verts, faces)}</object>'
        )
        comp_ids.append(oid)
        oid += 1

    assembly_id = oid
    components = "".join(f'<component objectid="{c}"/>' for c in comp_ids)
    assembly = (
        f'<object id="{assembly_id}" type="model" name="{_xml_attr(name)}">'
        f"<components>{components}</components></object>"
    )
    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{_CORE_NS}" xmlns:m="{_MAT_NS}">'
        "<resources>"
        f'<basematerials id="1">{"".join(bases)}</basematerials>'
        + "".join(objects)
        + assembly
        + "</resources>"
        f'<build><item objectid="{assembly_id}"/></build>'
        "</model>"
    )
    files = [
        ("[Content_Types].xml", _CONTENT_TYPES.encode("utf-8")),
        ("_rels/.rels", _RELS.encode("utf-8")),
        ("3D/3dmodel.model", model_xml.encode("utf-8")),
    ]
    return _zip_store(files)
