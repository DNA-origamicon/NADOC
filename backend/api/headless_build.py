"""Headless (mouse-free) design construction.

The bundle/extrude *endpoints* already are a "give me cells + a length, get a
bundle" API — the UI's extrude tool is just a mouse gesture that POSTs to them.
This module is the programmatic surface over that same path: no server, no
browser, no mouse.  Because it drives the real route handlers (which wrap
``state.mutate_with_feature_log``), a scripted build carries a real, replayable
``feature_log`` — a design built here is indistinguishable from one built by
clicking.

This is the seed for fully programmatic / AI-driven construction: an agent can
``new_design`` → ``create_bundle`` → ``extrude`` … → ``auto_scaffold`` (future)
on the active design exactly as a person would.

Isolation: :func:`build_bundle` runs inside a throwaway document (a unique
``doc_id`` bound via :mod:`backend.api.doc_context`) and drops it on exit, so a
one-shot build never disturbs the active design or its undo history.  The
lower-level :func:`new_design` / :func:`create_bundle` / :func:`extrude`
primitives operate on whatever document is currently bound (the default session
unless a caller scopes one), mirroring the endpoints one-to-one.
"""

from __future__ import annotations

import contextlib
import itertools

from backend.api import doc_context
from backend.api import state as design_state
from backend.api.crud import (
    BundleContinuationRequest,
    BundleDeformedContinuationRequest,
    BundleRequest,
    BundleSegmentRequest,
    CircleSegmentRequest,
    NickRequest,
    OverhangExtrudeRequest,
    add_bundle_continuation as _route_extrude,
    add_bundle_deformed_continuation as _route_deformed_continuation,
    add_bundle_segment as _route_extrude_segment,
    add_circle_segment as _route_circle_segment,
    add_nick as _route_add_nick,
    apply_loop_skips_from_deformations as _route_apply_loop_skip_deformations,
    auto_break as _route_auto_break,
    auto_crossover as _route_auto_crossover,
    auto_merge as _route_auto_merge,
    create_bundle as _route_create_bundle,
    delete_strand as _route_delete_strand,
    get_deformed_frame as _route_deformed_frame,
    ligate_strand as _route_ligate,
    overhang_extrude as _route_overhang_extrude,
)
from backend.api.routes_clusters import (
    AddClusterBody,
    PatchClusterBody,
    add_cluster as _route_add_cluster,
    update_cluster as _route_update_cluster,
)
from backend.api.routes_deformation import (
    AddDeformationBody,
    add_deformation as _route_add_deformation,
)
from backend.api.routes_loop_skip import (
    LoopSkipInsertRequest,
    insert_loop_skip as _route_insert_loop_skip,
)
from backend.api.routes_assign_sequences import (
    _FullAutostapleBody,
    _ScaffoldSeqBody,
    assign_scaffold_sequence_endpoint as _route_assign_scaffold,
    full_autostaple_endpoint as _route_full_autostaple,
)
from backend.api.routes_scaffold_routing import (
    auto_scaffold_seamed_endpoint as _route_auto_scaffold_seamed,
    auto_scaffold_seamless_endpoint as _route_auto_scaffold_seamless,
)
from backend.core.circle_primitive import (
    DEFAULT_MIN_CHORD_BP as _DEFAULT_MIN_CHORD_BP,
    circle_footprint,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Design, Direction, LatticeType

_scratch_counter = itertools.count()


@contextlib.contextmanager
def scratch_session(lattice: LatticeType = LatticeType.HONEYCOMB):
    """Bind an isolated throwaway document for the duration of a build.

    Inside the block the construction primitives operate on a fresh empty design;
    on exit the scratch document (and its undo history) is dropped, leaving the
    default session untouched.  Capture any result *before* the block exits.
    """
    doc_id = f"__headless_build_{next(_scratch_counter)}__"
    token = doc_context.set_current_doc(doc_id)
    try:
        design_state.set_design(Design(lattice_type=lattice))
        yield
    finally:
        doc_context.reset_current_doc(token)
        design_state.drop_doc(doc_id)


def new_design(lattice: LatticeType = LatticeType.HONEYCOMB) -> Design:
    """Replace the active document's design with a fresh empty one (mirrors POST /design)."""
    design_state.clear_history()
    design_state.set_design(Design(lattice_type=lattice))
    return design_state.get_or_404()


def create_bundle(
    cells,
    length_bp: int,
    *,
    lattice: LatticeType,
    name: str = "Bundle",
    plane: str = "XY",
    strand_filter: str = "both",
    ligate_adjacent: bool = True,
) -> Design:
    """Create a bundle on the active design (mirrors POST /design/bundle).

    Records a ``bundle-create`` feature-log entry.  Requires an active design
    (call :func:`new_design` first, or run inside :func:`scratch_session`).
    """
    _route_create_bundle(BundleRequest(
        cells=[list(c) for c in cells],
        length_bp=length_bp,
        name=name,
        plane=plane,
        strand_filter=strand_filter,
        lattice_type=lattice,
        ligate_adjacent=ligate_adjacent,
    ))
    return design_state.get_or_404()


def extrude(
    cells,
    length_bp: int,
    offset_nm: float,
    *,
    plane: str = "XY",
    strand_filter: str = "both",
    extend_inplace: bool = True,
    ligate_adjacent: bool = True,
) -> Design:
    """Extrude a continuation off the blunt ends (mirrors POST /design/bundle-continuation).

    Cells already ending at ``offset_nm`` extend their existing strands; fresh
    cells start new helices.  Records an ``extrude-continuation`` feature-log entry.
    """
    _route_extrude(BundleContinuationRequest(
        cells=[list(c) for c in cells],
        length_bp=length_bp,
        plane=plane,
        offset_nm=offset_nm,
        strand_filter=strand_filter,
        extend_inplace=extend_inplace,
        ligate_adjacent=ligate_adjacent,
    ))
    return design_state.get_or_404()


def extrude_segment(
    cells,
    length_bp: int,
    offset_nm: float,
    *,
    plane: str = "XY",
    strand_filter: str = "both",
    ligate_adjacent: bool = True,
) -> Design:
    """Append a fresh segment of helices at ``offset_nm`` (mirrors POST /design/bundle-segment).

    Unlike :func:`extrude` (continuation, which extends strands ending at the
    offset), this always creates NEW helices at the given cells — the slice-plane
    tool's "segment" mode.  ``length_bp`` may be negative (−axis).  Records an
    ``extrude-segment`` feature-log entry.
    """
    _route_extrude_segment(BundleSegmentRequest(
        cells=[list(c) for c in cells],
        length_bp=length_bp,
        plane=plane,
        offset_nm=offset_nm,
        strand_filter=strand_filter,
        ligate_adjacent=ligate_adjacent,
    ))
    return design_state.get_or_404()


def circle_segment(
    radius_nm: float,
    *,
    plane: str = "XY",
    offset_nm: float = 0.0,
    strand_filter: str = "both",
    ligate_adjacent: bool = True,
    min_chord_bp: int = _DEFAULT_MIN_CHORD_BP,
) -> Design:
    """Place a parametric circle (flat disc) of ``radius_nm`` (POST /design/circle-segment).

    A "circle" is a single row of SQUARE-lattice helices whose per-cell lengths
    trace a circular chord profile, every helix centred on ``offset_nm`` so the
    disc is bisected by the slice plane.  Unlike the route — which takes the
    pre-computed ``cells`` + ``cell_lengths`` the UI's preview derives — this
    wrapper takes the *radius* and runs the same analytic footprint
    (:func:`backend.core.circle_primitive.circle_footprint`) the frontend mirror
    uses, so a scripted disc is identical to a clicked one.  Build inside a SQUARE
    :func:`scratch_session` (the column pitch the chord profile assumes is the
    SQUARE lattice's).  Records a ``circle-segment`` feature-log entry.

    Raises ``ValueError`` if ``radius_nm`` is too small to admit even the centre
    column (no helix clears ``min_chord_bp``).
    """
    footprint = circle_footprint(
        radius_nm, plane=plane, min_chord_bp=min_chord_bp,
    )
    if footprint is None:
        raise ValueError(
            f"radius {radius_nm} nm is too small to place any helix "
            f"(no chord reaches the {min_chord_bp}-bp floor)"
        )
    _route_circle_segment(CircleSegmentRequest(
        cells=footprint["cells"],
        cell_lengths=footprint["cell_lengths"],
        plane=plane,
        offset_nm=offset_nm,
        strand_filter=strand_filter,
        ligate_adjacent=ligate_adjacent,
    ))
    return design_state.get_or_404()


def bundle_deformed_continuation(
    cells,
    length_bp: int,
    *,
    source_bp: int,
    ref_helix_id: str | None = None,
    plane: str = "XY",
) -> Design:
    """Extrude a continuation onto the DEFORMED cross-section frame (POST /design/bundle-deformed-continuation).

    Unlike :func:`extrude` (which continues a *straight* blunt end), this lands the
    new helices on the deformed cross-section at ``source_bp`` — the cell-grid
    rotated and translated to follow an upstream bend/twist.  Mirrors the UI flow
    exactly: it first samples the deformed frame at ``source_bp`` via
    ``GET /design/deformed-frame`` (the same handler the slice-plane tool calls),
    then POSTs the continuation *with* ``source_bp`` so the route RE-derives the
    frame server-side from the live design — the replayable path (if the upstream
    bend is later deleted/edited, re-running re-places the segment; see
    ``BundleDeformedContinuationRequest.source_bp``).  ``length_bp`` may be negative
    (extrude backward along the deformed tangent).  Requires an active design with
    at least one bend/twist op (else the sampled frame is straight and this is just
    a plain continuation).  Records an ``extrude-deformed-continuation`` feature-log
    entry.
    """
    frame = _route_deformed_frame(source_bp=source_bp, ref_helix_id=ref_helix_id)
    _route_deformed_continuation(BundleDeformedContinuationRequest(
        cells=[list(c) for c in cells],
        length_bp=length_bp,
        grid_origin=frame["grid_origin"],
        axis_dir=frame["axis_dir"],
        frame_right=frame["frame_right"],
        frame_up=frame["frame_up"],
        plane=plane,
        ref_helix_id=ref_helix_id,
        source_bp=source_bp,
    ))
    return design_state.get_or_404()


def build_bundle(
    cells,
    length_bp: int,
    *,
    lattice: LatticeType,
    name: str = "Bundle",
    plane: str = "XY",
    strand_filter: str = "both",
    passes=(),
) -> Design:
    """One-shot isolated build: empty design + bundle-create + N extrude passes.

    Returns a standalone deep-copied :class:`Design` carrying the full feature
    log, without disturbing the active/default session.

    ``passes`` mirrors uniform-segment extrusion (the teeth pattern): each entry
    is an ``int`` n (extrude ``cells[:n]``) or an explicit cell list; pass *i*
    (1-based) extrudes ``length_bp`` at ``offset_nm = i × length_bp × rise``.
    Empty ``passes`` yields a single bundle-create (6hb / 18hb / hinge base).
    """
    with scratch_session(lattice):
        create_bundle(
            cells, length_bp, lattice=lattice, name=name,
            plane=plane, strand_filter=strand_filter,
        )
        for pass_idx, spec in enumerate(passes, start=1):
            pass_cells = list(cells)[:spec] if isinstance(spec, int) else list(spec)
            extrude(
                pass_cells, length_bp,
                offset_nm=round(pass_idx * length_bp * BDNA_RISE_PER_BP, 3),
                plane=plane, strand_filter=strand_filter, extend_inplace=True,
            )
        return design_state.get_or_404().model_copy(deep=True)


# ── Strand-edit wrappers (nick / ligate / delete) ────────────────────────────────
# nick and ligate are an exact inverse pair: both take the SAME (helix, bp,
# direction) shape (NickRequest), so ``ligate(*args)`` repairs ``nick(*args)``.
# All three drive the real route handler and mutate the active document, so they
# chain after create_bundle/extrude inside a scratch_session exactly as a person
# clicks.  Handlers raise ``fastapi.HTTPException`` on bad input (e.g. nicking a
# strand's 3′ terminus → 400; ligating where no nick exists → 404).


def nick(helix_id: str, bp_index: int, direction: Direction) -> Design:
    """Break a strand at the 3′ side of (helix_id, bp_index, direction) (POST /design/nick).

    ``bp_index`` becomes the 3′ end of the left fragment; the next nucleotide in
    5′→3′ order becomes the 5′ end of the right fragment.  Inverse of :func:`ligate`
    with the same arguments.  Records a ``nick`` minor-log entry.
    """
    _route_add_nick(NickRequest(helix_id=helix_id, bp_index=bp_index, direction=direction))
    return design_state.get_or_404()


def ligate(helix_id: str, bp_index: int, direction: Direction) -> Design:
    """Repair a nick at (helix_id, bp_index, direction) (POST /design/ligate).

    Merges the strand whose 3′ end sits at ``bp_index`` with the strand whose 5′
    end sits at the adjacent bp.  Exact inverse of :func:`nick` (identical request
    shape).  Records a ``ligate`` minor-log entry.
    """
    _route_ligate(NickRequest(helix_id=helix_id, bp_index=bp_index, direction=direction))
    return design_state.get_or_404()


def delete_strand(strand_id: str) -> Design:
    """Delete a strand by id (DELETE /design/strands/{id}).

    Cascades linker/overhang cleanup the same way the UI's delete does.  Records a
    ``strand-delete`` minor-log entry.
    """
    _route_delete_strand(strand_id)
    return design_state.get_or_404()


# ── Loop/skip wrappers ───────────────────────────────────────────────────────────
# Loop/skip marks live on Helix.loop_skips and change the *effective* bp count of a
# helix: a loop (+1) inserts one extra base, a skip (−1) deletes one — the geometry
# layer emits one fewer / one more nucleotide per strand accordingly (see
# ``geometry.nucleotide_positions``).  Both wrappers drive the real route handler
# and mutate the active document, so they chain after create_bundle/route inside a
# scratch_session.  Handlers raise ``fastapi.HTTPException`` on bad input.


def loop_skip(helix_id: str, bp_index: int, delta: int) -> Design:
    """Insert or remove a single loop/skip at (helix_id, bp_index) (POST /design/loop-skip/insert).

    ``delta=+1`` inserts a loop (extra base → geometry gains one nucleotide per
    strand), ``delta=-1`` inserts a skip (deleted base → geometry loses one per
    strand), and ``delta=0`` *removes* any existing mark at that position — the
    documented "delta=0 removes" convention (a loop/skip's own inverse).  Records a
    ``loop-skip-insert`` minor-log entry.
    """
    _route_insert_loop_skip(LoopSkipInsertRequest(
        helix_id=helix_id, bp_index=bp_index, delta=delta,
    ))
    return design_state.get_or_404()


def apply_loop_skip_deformations() -> Design:
    """Bake every DeformationOp into concrete loop/skip marks (POST /design/loop-skip/apply-deformations).

    Wipes existing marks, then for each bend/twist op (and, on SQUARE lattices, the
    periodic skips) computes the per-helix loop/skip pattern and applies it
    atomically — the topological realisation of a geometric deformation.  Requires
    crossovers placed (cells are 7 bp) and at least one deformation op (or a SQUARE
    design).  Records an ``apply-loop-skips`` feature-log entry.
    """
    _route_apply_loop_skip_deformations()
    return design_state.get_or_404()


# ── Deformation (bend/twist) wrappers ────────────────────────────────────────────
# A bend/twist is a GEOMETRIC overlay (a DeformationOp): topology is never bent (the
# Three-Layer Law). Both wrappers drive the real route handler (add_deformation), so
# /design/deformation flips to covered by function identity and a scripted bend is
# indistinguishable from a clicked one (same revertable DeformationLogEntry). The
# total angle of the result is pinned by automation_harness.assert_deformation_angle
# (a DIRECTION-AGNOSTIC magnitude oracle — the bend/twist SIGN + frame conventions
# are an ASK-FIRST topic per CLAUDE.md, so neither these wrappers nor that oracle
# reason about them).


def add_bend(
    plane_a_bp: int,
    plane_b_bp: int,
    *,
    curvature_deg_per_bp: float,
    direction_deg: float = 0.0,
    affected_helix_ids=(),
    cluster_ids=(),
) -> Design:
    """Add a bend between two bp planes (POST /design/deformation, type='bend').

    The bend's total angle is ``curvature_deg_per_bp × (plane_b_bp − plane_a_bp)``
    (the value the popup reads back as "Angle"); ``direction_deg`` rotates the bend
    plane within the cross-section (0 = +X).  When ``affected_helix_ids`` /
    ``cluster_ids`` are both empty the op auto-applies to every helix crossing both
    planes (the unscoped default).  Records a revertable ``deformation`` feature-log
    entry.  Pin the realised magnitude with
    :func:`tests.automation_harness.assert_deformation_angle`.
    """
    _route_add_deformation(AddDeformationBody(
        type="bend", plane_a_bp=plane_a_bp, plane_b_bp=plane_b_bp,
        affected_helix_ids=list(affected_helix_ids), cluster_ids=list(cluster_ids),
        params={"kind": "bend", "curvature_deg_per_bp": curvature_deg_per_bp,
                "direction_deg": direction_deg},
    ))
    return design_state.get_or_404()


def add_twist(
    plane_a_bp: int,
    plane_b_bp: int,
    *,
    total_degrees: float | None = None,
    degrees_per_nm: float | None = None,
    affected_helix_ids=(),
    cluster_ids=(),
) -> Design:
    """Add a twist between two bp planes (POST /design/deformation, type='twist').

    Specify the twist as either a ``total_degrees`` across the window OR a
    ``degrees_per_nm`` rate — pass exactly one (they are mutually exclusive in
    :class:`TwistParams`).  When ``affected_helix_ids`` / ``cluster_ids`` are both
    empty the op auto-applies to every helix crossing both planes.  Records a
    revertable ``deformation`` feature-log entry.  Pin the realised magnitude with
    :func:`tests.automation_harness.assert_deformation_angle`.
    """
    if (total_degrees is None) == (degrees_per_nm is None):
        raise ValueError("pass exactly one of total_degrees / degrees_per_nm")
    params: dict = {"kind": "twist"}
    if total_degrees is not None:
        params["total_degrees"] = total_degrees
    else:
        params["degrees_per_nm"] = degrees_per_nm
    _route_add_deformation(AddDeformationBody(
        type="twist", plane_a_bp=plane_a_bp, plane_b_bp=plane_b_bp,
        affected_helix_ids=list(affected_helix_ids), cluster_ids=list(cluster_ids),
        params=params,
    ))
    return design_state.get_or_404()


# ── Auto-op wrappers ─────────────────────────────────────────────────────────────
# Each drives the same route handler the UI's button calls and returns the updated
# active design.  They operate on whatever document is bound (default session, or a
# scratch one inside :func:`scratch_session`), so an agent can chain them exactly as
# a person clicks: create_bundle → auto_scaffold → auto_crossover → auto_break → …
# Handlers that fail raise ``fastapi.HTTPException`` (e.g. full_autostaple → 422
# when no scaffold sequence is assigned) — catch it like a status code.


def auto_scaffold(*, seamless: bool = False) -> Design:
    """Route the scaffold to a single strand (POST /design/auto-scaffold-{seamed,seamless}).

    Seamed (default): Hamiltonian path + Holliday-junction seam + matched ends.
    Seamless: one end crossover per helix pair (zig-zag), no seam.
    """
    (_route_auto_scaffold_seamless if seamless else _route_auto_scaffold_seamed)()
    return design_state.get_or_404()


def auto_crossover() -> Design:
    """Place all compliant staple crossovers in bulk (POST /design/crossovers/auto)."""
    _route_auto_crossover()
    return design_state.get_or_404()


def auto_break(algorithm: str = "basic") -> Design:
    """Nick non-scaffold strands into ≤60 nt segments (POST /design/auto-break)."""
    _route_auto_break({"algorithm": algorithm})
    return design_state.get_or_404()


def auto_merge() -> Design:
    """Merge adjacent short staples where legal (POST /design/auto-merge)."""
    _route_auto_merge()
    return design_state.get_or_404()


def assign_scaffold_sequence(
    scaffold_name: str = "M13mp18",
    *,
    custom_sequence: str | None = None,
    strand_id: str | None = None,
) -> Design:
    """Assign a scaffold sequence (POST /design/assign-scaffold-sequence)."""
    _route_assign_scaffold(_ScaffoldSeqBody(
        scaffold_name=scaffold_name,
        custom_sequence=custom_sequence,
        strand_id=strand_id,
    ))
    return design_state.get_or_404()


def full_autostaple(scaffold_name: str = "M13mp18", **kwargs) -> Design:
    """One-click: assign sequence + crossovers + tick-break/merge (POST /design/full-autostaple)."""
    _route_full_autostaple(_FullAutostapleBody(
        scaffold_name=scaffold_name, **kwargs,
    ))
    return design_state.get_or_404()


def overhang_extrude(
    helix_id: str,
    bp_index: int,
    *,
    direction: Direction,
    is_five_prime: bool,
    neighbor_row: int,
    neighbor_col: int,
    length_bp: int,
) -> Design:
    """Extrude a staple-only overhang from a nick into a neighbour cell (POST /design/overhang/extrude)."""
    _route_overhang_extrude(OverhangExtrudeRequest(
        helix_id=helix_id, bp_index=bp_index, direction=direction,
        is_five_prime=is_five_prime, neighbor_row=neighbor_row,
        neighbor_col=neighbor_col, length_bp=length_bp,
    ))
    return design_state.get_or_404()


# ── clusters (rigid-body grouping + DISPLAY-layer pose) ─────────────────────────

def add_cluster(name: str, helix_ids, *, domain_ids=()) -> Design:
    """Create a named rigid-body cluster of helices (POST /design/cluster).

    A cluster groups helices into a rigid body that carries a DISPLAY-layer pose
    (translation / rotation / pivot) — the gizmo, bend/twist, and relax all operate
    on it.  The pose NEVER mutates topology (the three-layer law); it is applied at
    geometry-compute time as a post-step rigid displacement.  Only the auto-created
    default catch-all cluster surrenders helices to the new one (intentional clusters
    are left intact).  Pushes undo.

    The new cluster is the last entry in ``cluster_transforms`` — read its id from the
    returned design (``design.cluster_transforms[-1].id``) to pose it with
    :func:`transform_cluster`.
    """
    _route_add_cluster(AddClusterBody(
        name=name, helix_ids=list(helix_ids), domain_ids=list(domain_ids),
    ))
    return design_state.get_or_404()


def transform_cluster(
    cluster_id: str,
    *,
    translation=None,
    rotation=None,
    pivot=None,
    commit: bool = True,
    log: bool = False,
) -> Design:
    """Pose a cluster by a rigid transform (PATCH /design/cluster/{cluster_id}).

    ``translation`` is ``[x, y, z]`` nm; ``rotation`` a ``[x, y, z, w]`` unit
    quaternion (Three.js / scipy convention); ``pivot`` the ``[x, y, z]`` rotation
    centre.  A DISPLAY-layer pose: it is applied to the geometry kernel's output (via
    :func:`backend.core.deformation.deformed_helix_axes` /
    ``deformed_nucleotide_arrays``), never to the strand graph.  ``commit`` pushes the
    change to the undo stack (the drag-end semantics — default ``True`` for an applied
    pose); ``log`` (with ``commit``) records a ``cluster_op`` feature-log entry.
    Mirrors the live gizmo-drag path.

    Pin the result with :func:`tests.automation_harness.assert_cluster_translated`
    (a pure-translation pose shifts the cluster's helix geometry by exactly the
    requested vector; non-cluster helices stay put).
    """
    _route_update_cluster(cluster_id, PatchClusterBody(
        translation=list(translation) if translation is not None else None,
        rotation=list(rotation) if rotation is not None else None,
        pivot=list(pivot) if pivot is not None else None,
        commit=commit, log=log,
    ))
    return design_state.get_or_404()


def align_cluster_edge(
    cluster_id: str,
    src_edge,
    *,
    target_edge=None,
    target_line=None,
    commit: bool = True,
    log: bool = False,
) -> Design:
    """Pose a cluster so one of its OBB edges lands on a target edge / world line.

    The high-value AF-15 Phase 2 op: the design-layer analog of the AF-8 assembly
    connector-mate, but driven by **OBB edges** instead of named connectors — the
    arrangement primitive behind the headless 4-bar-parallelogram kinematic mechanism
    (cluster the rigid bars, then edge-align them into a parallelogram).

    Solves the rigid transform with
    :func:`backend.core.cluster_obb.align_edge_transform` (a PURE geometry solver —
    minimal rotation / auto-flip / midpoint snap, per the user-fixed convention) and
    drives :func:`transform_cluster` with it.  ``src_edge`` and ``target_edge``'s edge
    key are ``(axis, s1, s2)`` OBB-edge names (see :class:`cluster_obb.OBB`); pass
    exactly one of ``target_edge=(other_cluster_id, edge_key)`` /
    ``target_line=(point, direction)``.

    Pin the result with
    :func:`tests.automation_harness.assert_edges_collinear` (the two edges share a
    line — direction-agnostic).
    """
    from backend.core.cluster_obb import align_edge_transform

    design = design_state.get_or_404()
    quat, translation, pivot = align_edge_transform(
        design, cluster_id, src_edge, target_edge=target_edge, target_line=target_line,
    )
    return transform_cluster(
        cluster_id, translation=translation, rotation=quat, pivot=pivot,
        commit=commit, log=log,
    )
