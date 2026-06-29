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

from fastapi import HTTPException

from backend.api import doc_context
from backend.api import state as design_state
from backend.api.crud import (
    BatchCrossoverExtraBasesRequest,
    BundleContinuationRequest,
    BundleDeformedContinuationRequest,
    BundleRequest,
    BundleSegmentRequest,
    CircleSegmentRequest,
    CrossoverExtraBasesBatchEntry,
    CrossoverExtraBasesRequest,
    ForcedLigationRequest,
    HalfCrossoverRequest,
    NickRequest,
    OverhangConnectionCreateRequest,
    OverhangExtrudeRequest,
    PlaceCrossoverRequest,
    RelaxBondEndpoint,
    RelaxBondRequest,
    RelaxLinkerRequest,
    StrandEndResizeEntry,
    StrandEndResizeRequest,
    add_bundle_continuation as _route_extrude,
    add_bundle_deformed_continuation as _route_deformed_continuation,
    add_bundle_segment as _route_extrude_segment,
    add_circle_segment as _route_circle_segment,
    add_nick as _route_add_nick,
    apply_loop_skips_from_deformations as _route_apply_loop_skip_deformations,
    auto_break as _route_auto_break,
    auto_crossover as _route_auto_crossover,
    auto_merge as _route_auto_merge,
    batch_patch_crossover_extra_bases as _route_batch_xo_extra_bases,
    ConnectionVersionCreateRequest,
    apply_connection_version as _route_apply_connection_version,
    create_bundle as _route_create_bundle,
    create_connection_version as _route_create_connection_version,
    create_overhang_connection as _route_create_overhang_connection,
    delete_crossover as _route_delete_crossover,
    delete_forced_ligation as _route_delete_forced_ligation,
    delete_strand as _route_delete_strand,
    forced_ligation as _route_forced_ligation,
    get_deformed_frame as _route_deformed_frame,
    ligate_strand as _route_ligate,
    overhang_extrude as _route_overhang_extrude,
    patch_crossover_extra_bases as _route_set_xo_extra_bases,
    place_crossover as _route_place_crossover,
    relax_bond_endpoint as _route_relax_bond,
    relax_overhang_connection as _route_relax_overhang_connection,
    select_loadout as _route_select_loadout,
    strand_end_resize as _route_strand_end_resize,
)
from backend.api.routes_clusters import (
    AddClusterBody,
    PatchClusterBody,
    add_cluster as _route_add_cluster,
    update_cluster as _route_update_cluster,
)
from backend.api.routes_cluster_joints import (
    AddJointBody,
    add_joint as _route_add_joint,
)
from backend.api.routes_deformation import (
    AddDeformationBody,
    add_deformation as _route_add_deformation,
)
from backend.api.routes_feature_log import (
    SeekFeaturesBody,
    seek_features as _route_seek_features,
)
from backend.api.routes_flexible_segments import (
    FlexibleRelaxBody,
    FlexibleRelaxTransform,
    flexible_relax as _route_flexible_relax,
)
from backend.api.routes_loop_skip import (
    LoopSkipInsertRequest,
    insert_loop_skip as _route_insert_loop_skip,
)
from backend.api.routes_assign_sequences import (
    _FullAutostapleBody,
    _ScaffoldSeqBody,
    assign_scaffold_sequence_endpoint as _route_assign_scaffold,
    assign_staple_sequences_endpoint as _route_assign_staples,
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
from backend.core.flexible_relax import compute_relax_transforms
from backend.core.models import Design, Direction, LatticeType, StrandType

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


def resize_strand_end(
    strand_id: str,
    helix_id: str,
    end: str,
    delta_bp: int,
) -> Design:
    """Grow/shrink a terminal strand domain by a signed *delta_bp* (POST /design/strand-end-resize).

    The cadnano drag-arrow op: ``end`` selects the ``"5p"`` or ``"3p"`` terminus of
    ``strand``'s terminal domain on ``helix_id``; a positive ``delta_bp`` moves that
    end toward higher global bp, a negative one toward lower.  When the new bp lies
    outside the helix's current bp span the helix axis grows to accommodate it (and
    re-trims when it shrinks), so a resize that *defines* a helix's extent changes
    that helix's emitted geometry one bp at a time.

    **Mechanical pass-through** — the caller supplies the explicit end + signed delta;
    the wrapper does NOT decide *where* to resize (no geometric reasoning).  ``+δ``
    then ``−δ`` at the same end is its own inverse (canonical topology restored).
    Records a ``strand-end-resize`` minor-log entry.
    """
    _route_strand_end_resize(StrandEndResizeRequest(entries=[
        StrandEndResizeEntry(
            strand_id=strand_id, helix_id=helix_id, end=end, delta_bp=delta_bp,
        ),
    ]))
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


# ── Manual crossover place / delete wrappers ─────────────────────────────────────
# The manual counterpart to ``auto_crossover``: place (or remove) a SINGLE named
# crossover at explicit half-sites — the scripted analog of the cadnano editor's
# crossover drag.  Both are MECHANICAL pass-throughs: the caller supplies the two
# half-sites + the two nick bp (the bow-direction nick positions the editor derives
# from the click), so the wrapper forwards them verbatim — it does NOT decide *where*
# to cross (``feedback_crossover_no_reasoning``: never reason geometrically about
# crossover placement).  CROSSOVER = nick + ligate + record (a topological edit).
#
# Edge case the route handles and the oracle must too: when ligating the two halves
# would close a cycle (both ends already on the same strand), the route RECORDS the
# crossover but leaves it UNLIGATED (returns ``placement_warnings``); the marker auto-
# clears when the strand is later nicked.  ``unligated_crossover_ids`` reports which.


def place_crossover(
    half_a: tuple[str, int, Direction],
    half_b: tuple[str, int, Direction],
    nick_bp_a: int,
    nick_bp_b: int,
    *,
    process_id: str = "manual",
) -> Design:
    """Place one crossover at two explicit half-sites (POST /design/crossovers/place).

    ``half_a`` / ``half_b`` are ``(helix_id, index, strand)`` triples (``strand`` a
    :class:`~backend.core.models.Direction`); ``nick_bp_a`` / ``nick_bp_b`` are the
    bp at which to nick each helix before ligating (the bow-direction positions the
    editor computes — often ``index`` or ``index±1``).  The op is atomic: nick +
    ligate + record, recorded as a ``crossover-place`` minor-log entry, exactly like
    a clicked crossover.  The new :class:`~backend.core.models.Crossover` is the LAST
    entry of the returned design's ``crossovers``.

    If ligating the two halves would circularize a strand the crossover is recorded
    but left UNLIGATED (the strands stay split); :func:`backend.api.crud.unligated_crossover_ids`
    reports it.  Pin the result with
    :func:`tests.automation_harness.assert_crossover_joins` (which handles both the
    ligated and the unligated-to-avoid-circular outcome).
    """
    _route_place_crossover(PlaceCrossoverRequest(
        half_a=HalfCrossoverRequest(helix_id=half_a[0], index=half_a[1], strand=half_a[2]),
        half_b=HalfCrossoverRequest(helix_id=half_b[0], index=half_b[1], strand=half_b[2]),
        nick_bp_a=nick_bp_a,
        nick_bp_b=nick_bp_b,
        process_id=process_id,
    ))
    return design_state.get_or_404()


def delete_crossover(crossover_id: str) -> Design:
    """Remove a crossover by id (DELETE /design/crossovers/{id}).

    The exact inverse of :func:`place_crossover`: if the crossover joins two domains
    of one multi-domain strand, the strand is split back (desplice) into its two
    single-helix fragments.  Records a ``crossover-delete`` minor-log entry.
    """
    _route_delete_crossover(crossover_id)
    return design_state.get_or_404()


# ── Forced-ligation wrappers (manual-only — scripted-manual entry, NOT autorouting) ──
# Forced ligation connects ANY 3' end to ANY 5' end bypassing the crossover lookup
# tables, merging two strands into ONE multi-domain strand + a ForcedLigation record.
# The route contract is explicit that it must NEVER be called by autocrossover /
# autobreak / any automated routing pipeline — so this wrapper is the *scripted-manual*
# replay of a user's pencil-tool ligation, not a hook an autorouter may reach for.
# The FL record lives on ``design.forced_ligations`` (OFF the strand graph), so it is
# invisible to ``canonical_topology`` — pin its persistence by reading the record after
# a ``.nadoc`` round-trip (the same blind-spot as clusters / overhang-connections).


def force_ligate(
    three_prime_strand_id: str,
    five_prime_strand_id: str,
    *,
    is_periodic_seam: bool = False,
) -> Design:
    """Forced-ligate a 3' end to a 5' end (POST /design/forced-ligation).

    Connects the 3' end of ``three_prime_strand_id`` to the 5' end of
    ``five_prime_strand_id`` regardless of helix adjacency or crossover lookup
    tables, merging the two strands into ONE multi-domain strand and appending a
    :class:`~backend.core.models.ForcedLigation` record (NO crossover record is
    created — this is not a canonical crossover site).  ``is_periodic_seam`` marks
    a ligation made across the 2D editor's periodic-boundary mirror.

    **Manual-only / scripted-manual.** Forced ligation must never be driven by
    autocrossover, autobreak, or any automated routing pipeline; this wrapper is
    the headless replay of a user's manual pencil-tool ligation, NOT an autorouting
    entry point.

    The new ForcedLigation is the LAST entry of the returned design's
    ``forced_ligations``.  Pin the result with
    :func:`tests.automation_harness.assert_forced_ligation`.
    """
    _route_forced_ligation(ForcedLigationRequest(
        three_prime_strand_id=three_prime_strand_id,
        five_prime_strand_id=five_prime_strand_id,
        is_periodic_seam=is_periodic_seam,
    ))
    return design_state.get_or_404()


def delete_forced_ligation(fl_id: str) -> Design:
    """Remove a forced ligation by id (DELETE /design/forced-ligations/{id}).

    The exact inverse of :func:`force_ligate`: splits the merged strand back into
    its two fragments at the junction and drops the ForcedLigation record.
    """
    _route_delete_forced_ligation(fl_id)
    return design_state.get_or_404()


# ── Crossover extra-bases wrappers ───────────────────────────────────────────────
# Extra bases are single-stranded nucleotides inserted at a placed crossover junction
# (``Crossover.extra_bases``, e.g. "TT" to relieve strain) — junction METADATA, not a
# strand-graph edit, so they're invisible to ``canonical_topology`` (pin the effect by
# reading ``extra_bases`` directly, the way loop/skip pins read ``Helix.loop_skips``).
# Both wrappers drive the real PATCH route handlers (single + batch), so a scripted
# extra-base set is the same ``crossover-extra-bases`` minor-log entry the UI records,
# and they chain after auto_crossover inside a build (the crossovers must exist first).
# ``auto_crossover`` assigns crossovers random UUIDs, so neither wrapper takes an id:
# the junction is addressed declaratively — by its two helices + bp (precise) or by a
# scaffold/staple/all filter (bulk) — and the id is resolved here against the live design.

_CROSSOVER_FILTERS = ("all", "scaffold", "staple")


def set_crossover_extra_bases(
    helix_a_id: str, helix_b_id: str, bp_index: int, sequence: str,
) -> Design:
    """Set (or clear) extra bases on the crossover linking two helices at ``bp_index``.

    Addresses the junction by its two helices (order-independent) and shared bp index
    rather than by uuid, so it survives a rebuild.  ``sequence`` must match
    ``[ACGTNacgtn]*``; ``""`` clears the extra bases.  Drives
    ``PATCH /design/crossovers/{id}/extra-bases`` → records a ``crossover-extra-bases``
    minor-log entry.  Raises ``HTTPException(404)`` if no such crossover exists.
    """
    design = design_state.get_or_404()
    pair = {helix_a_id, helix_b_id}
    match = next(
        (x for x in design.crossovers
         if x.half_a.index == bp_index
         and {x.half_a.helix_id, x.half_b.helix_id} == pair),
        None,
    )
    if match is None:
        raise HTTPException(
            404,
            detail=f"No crossover links helices {helix_a_id!r} and {helix_b_id!r} "
                   f"at bp {bp_index}.",
        )
    _route_set_xo_extra_bases(match.id, CrossoverExtraBasesRequest(sequence=sequence))
    return design_state.get_or_404()


def set_crossover_extra_bases_bulk(sequence: str, *, crossover_filter: str = "all") -> Design:
    """Set (or clear) extra bases on every crossover matching ``crossover_filter``.

    ``crossover_filter`` ∈ ``{"all", "scaffold", "staple"}`` — the common strain-relief
    sweep (e.g. a poly-T loop at every staple junction).  ``sequence`` must match
    ``[ACGTNacgtn]*``; ``""`` clears.  Drives the atomic batch route
    ``PATCH /design/crossovers/extra-bases/batch`` → one ``crossover-extra-bases-batch``
    minor-log entry.  Raises ``HTTPException`` on a bad filter or when no crossover matches.
    """
    if crossover_filter not in _CROSSOVER_FILTERS:
        raise HTTPException(
            422,
            detail=f"crossover_filter must be one of {_CROSSOVER_FILTERS}, "
                   f"got {crossover_filter!r}.",
        )
    from backend.core.crossover_positions import enumerate_crossovers  # noqa: PLC0415

    design = design_state.get_or_404()
    ids = [
        rec["id"] for rec in enumerate_crossovers(design)
        if crossover_filter == "all" or rec["crossover_type"] == crossover_filter
    ]
    if not ids:
        raise HTTPException(
            404,
            detail=f"No {crossover_filter} crossovers to annotate "
                   f"(design has {len(design.crossovers)} crossover(s)).",
        )
    _route_batch_xo_extra_bases(BatchCrossoverExtraBasesRequest(
        entries=[CrossoverExtraBasesBatchEntry(crossover_id=i, sequence=sequence) for i in ids],
    ))
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


def assign_staple_sequences() -> Design:
    """Watson-Crick-complement every staple base from the assigned scaffold
    (POST /design/assign-staple-sequences).

    Requires the scaffold to already carry a sequence (call
    :func:`assign_scaffold_sequence` or :func:`full_sequence` first); a position
    with no scaffold coverage is left ``'N'``.
    """
    _route_assign_staples()
    return design_state.get_or_404()


def full_sequence(
    scaffold_name: str = "M13mp18",
    *,
    custom_sequence: str | None = None,
    strand_id: str | None = None,
) -> Design:
    """Fully sequence a routed origami: assign the scaffold sequence to every
    scaffold strand, then Watson-Crick-complement every staple — leaving no
    undefined base, so the design is export / oxDNA ready.

    This is *pure sequencing*: it does NOT route staples or place crossovers (use
    :func:`full_autostaple` for the routing path).  It's the headless analog of
    clicking "Assign scaffold sequence" then "Assign staple sequences".  The staple
    complement is taken from the active (single) scaffold, so a complete result
    needs a routed **single-scaffold** origami — call :func:`auto_scaffold` first on
    a raw bundle (one scaffold strand per helix won't fully cover the staples).
    Pass ``strand_id`` to sequence one named scaffold instead of all of them.
    """
    if strand_id is not None:
        assign_scaffold_sequence(
            scaffold_name, custom_sequence=custom_sequence, strand_id=strand_id)
    else:
        scaffold_ids = [
            s.id for s in design_state.get_or_404().strands
            if s.strand_type == StrandType.SCAFFOLD and not s.is_reference
        ]
        for sid in scaffold_ids:
            assign_scaffold_sequence(
                scaffold_name, custom_sequence=custom_sequence, strand_id=sid)
    return assign_staple_sequences()


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


def connect_overhangs(
    overhang_a_id: str,
    overhang_b_id: str,
    *,
    overhang_a_attach: str = "free_end",
    overhang_b_attach: str = "free_end",
    linker_type: str = "ds",
    length_value: float,
    length_unit: str = "bp",
    name: str | None = None,
    bridge_sequence: str | None = None,
) -> Design:
    """Tie two overhangs together with a length-defined LINKER strand
    (POST /design/overhang-connections).

    This is the hinge-confinement keystone: a script can extrude an overhang on
    each of two leaves, but only this op joins them with a linker whose contour
    length (``length_value`` bp/nm) physically *confines the hinge angle*.  The
    route appends a metadata :class:`OverhangConnection` AND generates its linker
    complement strand(s) — for ``ds`` also a virtual ``__lnk__`` bridge helix —
    so this is a real (replayable, feature-logged) **topological** edit, not a
    display pose.

    ``overhang_*_attach`` is ``"root"`` (the embedded crossover end) or
    ``"free_end"`` (the protruding tip); ``linker_type`` is ``"ss"`` or ``"ds"``.
    The accepted (attach × end × linker_type) combos are constrained by the
    Watson-Crick polarity rule the route enforces — a mismatched combo raises
    ``HTTPException`` 400, exactly as the UI greys it out.  The new connection is
    the LAST entry of the returned design's ``overhang_connections``.

    Pin the connection with
    :func:`tests.automation_harness.assert_linker_connects`.
    """
    _route_create_overhang_connection(OverhangConnectionCreateRequest(
        overhang_a_id=overhang_a_id,
        overhang_a_attach=overhang_a_attach,
        overhang_b_id=overhang_b_id,
        overhang_b_attach=overhang_b_attach,
        linker_type=linker_type,
        length_value=length_value,
        length_unit=length_unit,
        name=name,
        bridge_sequence=bridge_sequence,
    ))
    return design_state.get_or_404()


def create_connection_version(
    overhang_a_id: str,
    overhang_b_id: str,
    *,
    connection_type: str,
    overhang_a_seq: str | None = None,
    overhang_b_seq: str | None = None,
    bridge_length: int = 0,
    bridge_seq: str | None = None,
    applied: bool = False,
    name: str | None = None,
) -> Design:
    """Append a candidate ConnectionVersion for an overhang pair
    (POST /design/connection-versions).

    A ConnectionVersion is a persisted *candidate* for how a pair should connect
    (its ``connection_type`` is a CT-variant id such as ``"end-to-root"`` or
    ``"root-to-root-dsdna-linker"``, plus per-side sequences / bridge length).
    Creating one does NOT materialize topology — that's :func:`apply_connection_version`.
    Use this + apply for the DIRECT binding / end-to-root path; use
    :func:`connect_overhangs` only for the linker path.

    The new version is the LAST entry of the returned design's
    ``connection_versions``.
    """
    _route_create_connection_version(ConnectionVersionCreateRequest(
        overhang_a_id=overhang_a_id,
        overhang_b_id=overhang_b_id,
        connection_type=connection_type,
        overhang_a_seq=overhang_a_seq,
        overhang_b_seq=overhang_b_seq,
        bridge_length=bridge_length,
        bridge_seq=bridge_seq,
        applied=applied,
        name=name,
    ))
    return design_state.get_or_404()


def apply_connection_version(version_id: str) -> Design:
    """Materialize a ConnectionVersion atomically (one undo)
    (POST /design/connection-versions/{version_id}/apply).

    Sets both overhang sequences, tears down the pair's current connection /
    binding, then (re)creates the version's connection type:
      • linker variants → an :class:`OverhangConnection` + linker strand(s);
      • ``root-to-root`` → an :class:`OverhangBinding` record;
      • ``end-to-root`` → regenerate overhang B as A's reverse-complement binder,
        splicing the binder domain into B's root staple (consumes B).

    Pin the end-to-root case with
    :func:`tests.automation_harness.assert_end_to_root_binder`.
    """
    _route_apply_connection_version(version_id)
    return design_state.get_or_404()


def relax_flexible_segments(
    *,
    scope: str = "all",
    conn_id: str | None = None,
    label: str | None = None,
) -> Design:
    """Relax overstretched flexible ssDNA segments headlessly
    (computes the pose, then commits via POST /design/flexible-relax).

    The hinge ssDNA-scaffold counterpart to :func:`connect_overhangs`: where a
    linker confines a hinge by its contour length, the *flexible scaffold tether*
    sets the hinge's geometric rest pose.  This runs the **same** position-based
    constraint solver the in-app "Relax flexible segments" command runs (ported
    to :mod:`backend.core.flexible_relax`), pulling the smaller cluster of each
    flexible-connected pair in until no tether exceeds its contour length
    ("free until taut"), then commits all moved clusters as ONE feature-log step.

    ``scope="all"`` sweeps every flexible pair; ``scope="one"`` relaxes just the
    pair of ``conn_id``.  **Display/pose-layer only** — moves
    ``cluster_transforms``, never the strand graph.  Returns the relaxed design
    (unchanged when nothing was overstretched — the route is not called, so no
    empty feature-log entry is written).

    Pin with :func:`tests.automation_harness.assert_flexible_segments_relaxed`.
    """
    design = design_state.get_or_404()
    transforms, _residual = compute_relax_transforms(design, scope=scope, conn_id=conn_id)
    if not transforms:
        return design
    _route_flexible_relax(FlexibleRelaxBody(
        transforms=[FlexibleRelaxTransform(**t) for t in transforms],
        label=label,
    ))
    return design_state.get_or_404()


def relax_overhang_connection(
    conn_id: str,
    *,
    joint_ids: list[str] | None = None,
    bin_index: int | None = None,
    r_ee_min_nm: float | None = None,
    r_ee_max_nm: float | None = None,
) -> Design:
    """Relax a linker connection's display POSE
    (POST /design/overhang-connections/{conn_id}/relax).

    The relax counterpart to :func:`connect_overhangs`: once two leaves are tied
    by a length-defined linker, this swings the joint-connected rigid cluster(s)
    so the linker's connector arcs collapse toward their natural duplex/FJC span —
    the geometric rest pose that *confines the hinge angle* by the linker's contour
    length.  ``joint_ids`` omitted → the 1-DOF auto-pick path (the route requires
    exactly one joint between the two overhangs' clusters); pass an explicit list
    for the multi-DOF case.  ``bin_index`` / ``r_ee_*`` select the ss-linker FJC
    histogram bin + kinematic limits (ds linkers ignore them).

    **Three-Layer note — this is a DISPLAY/POSE move, NOT a topological edit.**
    The route rotates ``cluster_transforms`` (and logs one ``ClusterOpLogEntry``
    per touched cluster); it never edits the strand graph, so
    ``canonical_topology`` is unchanged — that invariant is the load-bearing pin
    in :func:`tests.automation_harness.assert_linker_relaxed_pose`.

    Pin with :func:`tests.automation_harness.assert_linker_relaxed_pose`.
    """
    _route_relax_overhang_connection(conn_id, RelaxLinkerRequest(
        joint_ids=joint_ids,
        bin_index=bin_index,
        r_ee_min_nm=r_ee_min_nm,
        r_ee_max_nm=r_ee_max_nm,
    ))
    return design_state.get_or_404()


def relax_bond(
    bond_type: str,
    *,
    bond_id: str | None = None,
    linker_side: str | None = None,
    side_a: dict | None = None,
    side_b: dict | None = None,
    side_to_move: str | None = None,
    joint_ids: list[str] | None = None,
    target_nm: float | None = None,
) -> Design:
    """Relax any stretched backbone bond's display POSE (POST /design/relax-bond).

    The generic sibling of :func:`relax_overhang_connection`: one entry point for
    crossovers, forced ligations, linker connector arcs, and intra-strand
    cross-helix arcs.  Identify the bond by EITHER a record id (``bond_id``, with
    ``linker_side`` for a ``linker_arc``) OR the two nucleotide endpoints
    (``side_a`` + ``side_b``, each a dict ``{helix_id, bp_index, direction,
    strand_id?}``).  ``side_to_move`` is required for the 0-DOF rigid-translate
    case (no joints between the two clusters); it is ignored once a joint exists.
    ``target_nm`` overrides the type-default chord target (crossover ~0.13 nm,
    ligation 0, linker/strand arc ~0.67 nm).

    **Three-Layer note — POSE only.**  Like the linker relax, this moves
    ``cluster_transforms`` (0-DOF translate / 1-DOF or N-DOF joint rotate) and
    never edits the strand graph; ``canonical_topology`` is unchanged.

    Pin with :func:`tests.automation_harness.assert_bond_relaxed_pose`.
    """
    _route_relax_bond(RelaxBondRequest(
        bond_type=bond_type,
        bond_id=bond_id,
        linker_side=linker_side,
        side_a=RelaxBondEndpoint(**side_a) if side_a is not None else None,
        side_b=RelaxBondEndpoint(**side_b) if side_b is not None else None,
        side_to_move=side_to_move,
        joint_ids=joint_ids,
        target_nm=target_nm,
    ))
    return design_state.get_or_404()


# ── feature-log timeline navigation (scrub / seek — undo the build to a point) ──

def seek_features(position: int, sub_position: int | None = None) -> Design:
    """Scrub the feature-log timeline to *position* (POST /design/features/seek).

    The single primitive behind "roll a design back to an earlier build state" —
    the headless analog of dragging the Feature Log rail thumb.  It replays the
    log up to *position* and rebuilds the derived geometry/topology, **without
    truncating the log** (unlike revert): only the active cursor + the realised
    state move, so a later ``seek_features(-1)`` restores the latest state exactly.

    ``position`` — ``-2`` empties the design (no features active), ``-1`` seeks to
    the latest (all entries active), ``>=0`` makes that index the last active
    entry (dropping the effect of every op after it).  ``sub_position`` is honored
    only when *position* indexes a routing-cluster entry (mid-cluster scrub).

    Pin the scrub invariants with
    :func:`tests.automation_harness.assert_feature_seek`.
    """
    _route_seek_features(SeekFeaturesBody(position=position, sub_position=sub_position))
    return design_state.get_or_404()


def return_to_latest(loadout_id: str) -> Design:
    """Return to the "Latest" loadout branch a job-roll saved, restoring the edits
    that were in place before the roll (POST /design/loadouts/{id}/select?save_current=false).

    ``save_current=False`` so the rolled run-state (reproducible from the job) is NOT
    folded back over the branch holding the user's latest edits.  The counterpart to
    :func:`backend.api.headless_oxdna_build.roll_job_to_run_state`.
    """
    _route_select_loadout(loadout_id, save_current=False)
    return design_state.get_or_404()


# ── clusters (rigid-body grouping + DISPLAY-layer pose) ─────────────────────────

def add_cluster(name: str, helix_ids, *, domain_ids=(), log: bool = False) -> Design:
    """Create a named rigid-body cluster of helices (POST /design/cluster).

    A cluster groups helices into a rigid body that carries a DISPLAY-layer pose
    (translation / rotation / pivot) — the gizmo, bend/twist, and relax all operate
    on it.  The pose NEVER mutates topology (the three-layer law); it is applied at
    geometry-compute time as a post-step rigid displacement.  Only the auto-created
    default catch-all cluster surrenders helices to the new one (intentional clusters
    are left intact).  Pushes undo.

    ``log=True`` records a ``cluster_create`` feature-log entry (naming the cluster +
    its exact helix set), so a generated multi-cluster part's construction history can
    replay the *grouping* step, not just the later poses/joints.  Pin it with
    :func:`tests.automation_harness.assert_cluster_in_feature_log`; ``canonical_topology``
    is blind to clusters, so the feature-log entry is what proves the grouping persisted
    across a round-trip.

    The new cluster is the last entry in ``cluster_transforms`` — read its id from the
    returned design (``design.cluster_transforms[-1].id``) to pose it with
    :func:`transform_cluster`.
    """
    _route_add_cluster(AddClusterBody(
        name=name, helix_ids=list(helix_ids), domain_ids=list(domain_ids), log=log,
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


def place_cluster_joint(
    cluster_id: str,
    *,
    edge=None,
    corner=None,
    face=None,
    anchor: str = "midpoint",
    name: str = "Joint",
    surface_detail: int = 6,
    min_angle_deg: float = -180.0,
    max_angle_deg: float = 180.0,
) -> Design:
    """Place a revolute joint anchored on a named OBB edge/corner (AF-14 Phase 1).

    A ``ClusterJoint`` is a **topological/design-layer** intent — which rigid cluster
    swings about what axis — so placing one is an allowed write (the hull prism / OBB it
    is anchored to is a pure geometric *read* that never writes back; clean Three-Layer,
    mirroring how AF-6 deformation reads the frame).  This is the headless analog of the
    gizmo gesture where the user clicks a face of the cluster's hull approximation.

    The anchor is a named feature of the cluster's hull-prism OBB
    (:func:`backend.core.cluster_obb.hull_prism_axis`):

      * ``edge=(axis, s1, s2)`` — the revolute hinge runs ALONG that OBB edge (the
        door-jamb placement that maximises range of motion);
      * ``corner=(su, sv, sw)`` with ``face=(axis, sign)`` — a point pivot AT the corner,
        swinging in the named face's plane.

    ``anchor`` (edge mode): ``"midpoint"`` (default) stores the edge centre; ``"corner"``
    stores a face corner (the AF-14 Phase 3 convention) — same hinge line either way.

    Drives the real ``POST /design/cluster/{id}/joint`` handler (``add_joint``), which
    converts the world axis into the cluster's LOCAL frame for drift-free storage.  Read
    the new joint id from ``design.cluster_joints[-1].id``.

    Pin the result with
    :func:`tests.automation_harness.assert_joint_on_hull_corner` (the placed joint's
    re-derived world axis lies along the named edge / passes through the named corner of
    the independently recomputed OBB).
    """
    from backend.core.cluster_obb import hull_prism_axis

    design = design_state.get_or_404()
    origin, direction = hull_prism_axis(
        design, cluster_id, edge=edge, corner=corner, face=face, anchor=anchor,
    )
    _route_add_joint(cluster_id, AddJointBody(
        axis_origin=list(origin),
        axis_direction=list(direction),
        surface_detail=surface_detail,
        name=name,
        min_angle_deg=min_angle_deg,
        max_angle_deg=max_angle_deg,
    ))
    return design_state.get_or_404()


# ── Multi-op primitive PLACEMENT (AF-35 — preserve-verbatim graft) ────────────────
# Place a WHOLE pre-built primitive (a hinge: two rigid leaves + cross-gap forced-
# ligation links) additively into the active design, rigidly translated so its anchor
# cell lands on a requested lattice cell.  Unlike the single-op ``extrude_segment``
# placement (one bundle-create footprint), a hinge is a MULTI-op primitive whose
# scaffold + FL routing must survive placement verbatim (user decision 2026-06-27) —
# so this GRAFTS the primitive's own helices/strands/forced_ligations/cluster_transforms
# (see ``backend.core.primitive_placement``) rather than re-running its build ops at an
# offset (which would route through a different builder and risk geometry drift).
# Commits via snapshot + set_design_silent → one undo step (additive + revertable).


def _source_hinge_primitive(name: str) -> Design:
    """Build a named hinge primitive standalone (the placement source).

    Lazy import to avoid the ``headless_hinge_build`` → ``headless_build`` cycle.
    """
    from backend.api import headless_hinge_build as hhb

    if name not in hhb.HINGE_PRIMITIVE_NAMES:
        raise ValueError(
            f"unknown primitive {name!r}; pass primitive=<Design> for non-hinge "
            f"primitives (built-in hinge names: {hhb.HINGE_PRIMITIVE_NAMES})"
        )
    return hhb.build_hinge_primitive(name)


def place_primitive(
    name: str | None = None,
    *,
    anchor_cell,
    plane: str | None = None,
    primitive: Design | None = None,
) -> Design:
    """Place a whole primitive into the active design, anchored at ``anchor_cell``.

    Replays a primitive additively (its anchor cell → ``anchor_cell``), preserving
    its scaffold + forced-ligation routing **verbatim** (a rigid graft, not a
    re-route).  ``name`` builds a built-in hinge primitive as the source; for any
    other primitive pass ``primitive=<Design>`` (e.g. ``Design.from_json(...)``).
    ``plane`` defaults to the primitive's own construction plane.

    The placed sub-structure is a clean rigid translation of the standalone
    primitive (fresh ids, host content untouched).  Commits as a single undoable
    step.  Pin with :func:`tests.automation_harness.assert_primitive_placed`.

    Raises ``ValueError`` (via ``place_primitive_into``) on a lattice mismatch, a
    footprint-distorting (honeycomb odd-parity) shift, a host collision, or a
    primitive carrying content the graft cannot place verbatim.
    """
    from backend.core.primitive_placement import place_primitive_into

    if primitive is None:
        if name is None:
            raise ValueError("pass a primitive name or an explicit primitive=<Design>")
        primitive = _source_hinge_primitive(name)

    host = design_state.get_or_404()
    placed = place_primitive_into(
        host, primitive, anchor_cell=tuple(anchor_cell), plane=plane,
    )
    design_state.snapshot()
    design_state.set_design_silent(placed)
    return placed
