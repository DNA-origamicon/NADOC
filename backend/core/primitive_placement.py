"""AF-35: headless multi-op primitive PLACEMENT (preserve-verbatim graft).

Place a *whole* pre-built primitive (e.g. a hinge — two rigid leaves bridged by
forced-ligation links) **additively** into an existing design, rigidly translated
so the primitive's anchor cell lands on a requested lattice cell.

**User decision (2026-06-27): preserve the primitive's routing VERBATIM.**  A
hinge's scaffold strands + cross-gap forced-ligation links *are* what make it a
hinge; placement must not re-route them.  So this is a **graft**, not a replay:
the primitive's own ``helices`` / ``strands`` / ``forced_ligations`` /
``cluster_transforms`` are copied with fresh ids and translated by one rigid
lattice vector, leaving the host design's content untouched.  The placed
sub-structure is therefore a clean rigid translation of the standalone primitive
— pinned by :func:`tests.automation_harness.assert_primitive_placed`.

Why a graft and not an op-replay (the route-driven path):
:mod:`backend.api.headless_hinge_build` builds a hinge from scratch with the
*exact* ``create_bundle`` → resize → ``force_ligate`` op sequence, because the
saved primitives' axis floats only reproduce under that one sequence (the AF-30
ISSUE-13 axis re-trim).  Replaying that sequence *additively at an offset* would
route through ``bundle-segment`` (a different builder → different axis floats) and
risk silent geometry drift.  Copying the primitive's already-correct geometry and
translating it rigidly is what makes "verbatim" literally true.

This is the **service** shape (backlog rule 3): pure, HTTP-free, ``backend.core``
imports nothing from ``backend.api``.  The thin commit wrapper is
``headless_build.place_primitive``.

Three-Layer note: grafting helices + strands + forced-ligation records is a
**topological** write (an allowed edit) — additive, never mutating the host's
existing strand graph.
"""

from __future__ import annotations

import uuid

from backend.core.lattice import _lattice_position
from backend.core.models import Design, LatticeType, Vec3

# Plane → the two world axes the lattice (lx, ly) in-plane coordinates map to.
# Mirrors ``make_bundle_design``: XY helices run along Z (in-plane = x,y); XZ run
# along Y (in-plane = x,z); YZ run along X (in-plane = y,z).
_PLANE_AXES: dict[str, tuple[str, str]] = {
    "XY": ("x", "y"),
    "XZ": ("x", "z"),
    "YZ": ("y", "z"),
}

# Design list-fields the graft does NOT carry.  A primitive that populates any of
# them cannot be placed verbatim, so we refuse rather than silently drop topology
# (keeping the "verbatim" guarantee honest).  ``helices`` / ``strands`` /
# ``forced_ligations`` / ``cluster_transforms`` ARE carried; everything else here
# must be empty.
_UNSUPPORTED_LIST_FIELDS: tuple[str, ...] = (
    "deformations",
    "cluster_joints",
    "overhangs",
    "overhang_connections",
    "overhang_bindings",
    "flexible_segment_marks",
    "flexible_connections",
    "protein_assets",
    "protein_attachments",
    "extensions",
    "representation_overrides",
    "photoproduct_junctions",
    "crossovers",
    "animations",
    "loadouts",
)

_EPS = 1e-6


def detect_plane(primitive: Design) -> str:
    """Return the construction plane (``"XY"``/``"XZ"``/``"YZ"``) of a primitive.

    The plane is the one whose normal is the helix *axis*: an XY-plane bundle has
    helices running along Z, etc.  Read off the first helix's axis direction (the
    component with the largest magnitude is the axis).
    """
    if not primitive.helices:
        raise ValueError("cannot detect a plane for a primitive with no helices")
    h = primitive.helices[0]
    dx = abs(h.axis_end.x - h.axis_start.x)
    dy = abs(h.axis_end.y - h.axis_start.y)
    dz = abs(h.axis_end.z - h.axis_start.z)
    # axis along z → XY, along y → XZ, along x → YZ
    return max((dz, "XY"), (dy, "XZ"), (dx, "YZ"))[1]


def primitive_anchor_cell(primitive: Design) -> tuple[int, int]:
    """The primitive's anchor cell — its min ``grid_pos`` (row, then col).

    Mirrors :func:`primitive_catalog._anchor_cell`; the cell that lands on the
    caller's requested ``anchor_cell`` during placement.
    """
    cells = [h.grid_pos for h in primitive.helices if h.grid_pos is not None]
    if not cells:
        raise ValueError("primitive has no grid-positioned helices to anchor on")
    return min(cells)


def _translate_vec(v: Vec3, dlx: float, dly: float, plane: str) -> Vec3:
    """Translate a point by an in-plane (dlx, dly) for the given construction plane."""
    a, b = _PLANE_AXES[plane]
    comps = {"x": v.x, "y": v.y, "z": v.z}
    comps[a] += dlx
    comps[b] += dly
    return Vec3(x=comps["x"], y=comps["y"], z=comps["z"])


def _world_delta(
    from_cell: tuple[int, int], to_cell: tuple[int, int], lattice: LatticeType
) -> tuple[float, float]:
    """The in-plane world vector moving ``from_cell`` onto ``to_cell``."""
    fx, fy = _lattice_position(from_cell[0], from_cell[1], lattice)
    tx, ty = _lattice_position(to_cell[0], to_cell[1], lattice)
    return tx - fx, ty - fy


def _fresh_id(base: str, used: set[str]) -> str:
    """A unique id derived from ``base`` (kept verbatim when free, else suffixed)."""
    if base not in used:
        return base
    n = 1
    while f"{base}~{n}" in used:
        n += 1
    return f"{base}~{n}"


def translate_design(
    design: Design,
    grid_delta: tuple[int, int],
    world_delta: tuple[float, float],
    plane: str,
) -> Design:
    """Return a copy of ``design`` rigidly translated by a grid + matching world vector.

    Every helix's ``grid_pos`` shifts by ``grid_delta`` and its axis endpoints by
    ``world_delta`` (in-plane).  Used both to PLACE a primitive (positive delta) and
    to OFFSET-CORRECT a placed sub-structure back for comparison (negative delta).
    Ids are untouched (callers that need fresh ids remap separately).
    """
    dr, dc = grid_delta
    dlx, dly = world_delta
    new_helices = []
    for h in design.helices:
        gp = h.grid_pos
        new_gp = (gp[0] + dr, gp[1] + dc) if gp is not None else None
        new_helices.append(
            h.model_copy(
                update={
                    "grid_pos": new_gp,
                    "axis_start": _translate_vec(h.axis_start, dlx, dly, plane),
                    "axis_end": _translate_vec(h.axis_end, dlx, dly, plane),
                }
            )
        )
    return design.model_copy(update={"helices": new_helices})


def place_primitive_into(
    host: Design,
    primitive: Design,
    *,
    anchor_cell: tuple[int, int],
    plane: str | None = None,
) -> Design:
    """Return a NEW design = ``host`` + a rigidly-translated, id-remapped copy of
    ``primitive`` (preserve-verbatim graft).

    The primitive's anchor cell (its min ``grid_pos``) is moved onto ``anchor_cell``;
    every helix is translated by the single rigid lattice vector that move implies,
    so the placed sub-structure is an exact rigid copy of the primitive.  Helix ids
    are remapped to stay unique in the host, and every internal reference
    (``domain.helix_id``, forced-ligation endpoints, cluster ``helix_ids`` /
    ``domain_ids``) is rewritten to match.  The host's existing helices / strands /
    records are returned untouched (additive).

    Raises ``ValueError`` if:
      * the primitive populates a field the graft does not carry (see
        ``_UNSUPPORTED_LIST_FIELDS``, or a helix carries loop/skips, or a cluster
        names domains we can't map),
      * the host is non-empty and its lattice differs from the primitive's,
      * the grid shift is not a rigid lattice translation (a honeycomb odd-parity
        shift distorts the footprint — same rule as the GUI placement), or
      * a translated helix would collide with a cell the host already occupies.
    """
    if not primitive.helices:
        raise ValueError("cannot place an empty primitive (no helices)")

    for field in _UNSUPPORTED_LIST_FIELDS:
        if getattr(primitive, field):
            raise ValueError(
                f"primitive carries unsupported content {field!r}; placement only "
                "grafts helices/strands/forced_ligations/cluster_transforms verbatim"
            )
    if primitive.plate_layout is not None or primitive.atomistic_reference is not None:
        raise ValueError(
            "primitive carries plate/atomistic data the graft cannot place"
        )
    if any(h.loop_skips for h in primitive.helices):
        raise ValueError("primitive carries loop/skip marks the graft cannot place")

    lattice = primitive.lattice_type
    if host.helices and host.lattice_type != lattice:
        raise ValueError(
            f"cannot place a {lattice} primitive into a {host.lattice_type} design"
        )

    plane = plane or detect_plane(primitive)
    if plane not in _PLANE_AXES:
        raise ValueError(f"unknown plane {plane!r}")

    dst_anchor = anchor_cell  # the requested landing cell (row, col)
    src_anchor = primitive_anchor_cell(primitive)
    grid_delta = (dst_anchor[0] - src_anchor[0], dst_anchor[1] - src_anchor[1])
    world_delta = _world_delta(src_anchor, dst_anchor, lattice)

    # Rigid-translation guard: every helix's own lattice translation must equal the
    # single rigid world_delta.  For SQUARE this is automatic; for HONEYCOMB an
    # odd-parity shift makes the per-cell stagger vary → footprint distortion → raise.
    occupied = {h.grid_pos for h in host.helices if h.grid_pos is not None}
    for h in primitive.helices:
        gp = h.grid_pos
        if gp is None:
            raise ValueError("primitive helix lacks grid_pos; cannot place")
        new_gp = (gp[0] + grid_delta[0], gp[1] + grid_delta[1])
        per_cell = _world_delta(gp, new_gp, lattice)
        if (
            abs(per_cell[0] - world_delta[0]) > _EPS
            or abs(per_cell[1] - world_delta[1]) > _EPS
        ):
            raise ValueError(
                "placement would distort the footprint (a non-rigid lattice shift — "
                "e.g. a honeycomb odd-parity move); choose a shape-preserving anchor cell"
            )
        if new_gp in occupied:
            raise ValueError(
                f"placement collides with the host at cell {new_gp}; choose a clear anchor"
            )

    # ── id remap tables ──────────────────────────────────────────────────────────
    used_h = {h.id for h in host.helices}
    used_s = {s.id for s in host.strands}
    used_c = {c.id for c in host.cluster_transforms}
    hmap: dict[str, str] = {}
    for h in primitive.helices:
        nid = _fresh_id(h.id, used_h)
        used_h.add(nid)
        hmap[h.id] = nid
    smap: dict[str, str] = {}
    for s in primitive.strands:
        nid = _fresh_id(s.id, used_s)
        used_s.add(nid)
        smap[s.id] = nid

    # ── translate + remap the primitive content ──────────────────────────────────
    translated = translate_design(primitive, grid_delta, world_delta, plane)
    placed_helices = [
        h.model_copy(update={"id": hmap[orig.id]})
        for orig, h in zip(primitive.helices, translated.helices)
    ]
    placed_strands = []
    for s in primitive.strands:
        new_domains = [
            dm.model_copy(update={"helix_id": hmap[dm.helix_id]}) for dm in s.domains
        ]
        placed_strands.append(
            s.model_copy(update={"id": smap[s.id], "domains": new_domains})
        )
    placed_fls = [
        fl.model_copy(
            update={
                "id": str(uuid.uuid4()),
                "three_prime_helix_id": hmap[fl.three_prime_helix_id],
                "five_prime_helix_id": hmap[fl.five_prime_helix_id],
            }
        )
        for fl in primitive.forced_ligations
    ]
    placed_clusters = []
    for c in primitive.cluster_transforms:
        new_helix_ids = [hmap[hid] for hid in c.helix_ids]
        new_domain_ids = []
        for ref in c.domain_ids:
            if ref.strand_id not in smap:
                raise ValueError("cluster names a strand the graft did not place")
            new_domain_ids.append(
                ref.model_copy(update={"strand_id": smap[ref.strand_id]})
            )
        nid = _fresh_id(c.id, used_c)
        used_c.add(nid)
        placed_clusters.append(
            c.model_copy(
                update={
                    "id": nid,
                    "helix_ids": new_helix_ids,
                    "domain_ids": new_domain_ids,
                }
            )
        )

    result = host.model_copy(deep=True)
    result.helices = list(result.helices) + placed_helices
    result.strands = list(result.strands) + placed_strands
    result.forced_ligations = list(result.forced_ligations) + placed_fls
    result.cluster_transforms = list(result.cluster_transforms) + placed_clusters
    if not host.helices:
        result.lattice_type = lattice
    return result
