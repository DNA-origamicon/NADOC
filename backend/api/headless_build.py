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
    BundleRequest,
    BundleSegmentRequest,
    OverhangExtrudeRequest,
    _FullAutostapleBody,
    _ScaffoldSeqBody,
    add_bundle_continuation as _route_extrude,
    add_bundle_segment as _route_extrude_segment,
    assign_scaffold_sequence_endpoint as _route_assign_scaffold,
    auto_break as _route_auto_break,
    auto_crossover as _route_auto_crossover,
    auto_merge as _route_auto_merge,
    auto_scaffold_seamed_endpoint as _route_auto_scaffold_seamed,
    auto_scaffold_seamless_endpoint as _route_auto_scaffold_seamless,
    create_bundle as _route_create_bundle,
    full_autostaple_endpoint as _route_full_autostaple,
    overhang_extrude as _route_overhang_extrude,
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
