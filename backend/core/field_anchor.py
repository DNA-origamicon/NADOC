"""The "a uniform field needs something to hold it" rule — the ONE source of truth
shared by every oxDNA field path (persisted runs, live sessions, chain-stage validation)
so they can never disagree.

A uniform electric field applies the SAME per-nucleotide force to every base, so its net
effect is a centre-of-mass force that streams the whole structure across the periodic box
unless something holds it in place.  Normally that "something" is ≥1 fixed strand (an
anchor trap).  BUT a hard surface (a repulsion plane) that the field pushes INTO also
holds it: the plane's normal reaction balances the field, so a *deposition* setup — a
field aimed straight into the floor — is stable with no strand anchor.

Rule (user decision, 2026-07-09): a field opposed by a surface no longer requires a strand
anchor.  All the geometry lives here; the frontend mirrors ``surface_opposes_field`` in
``chain_sim_model.js``.  Callers pass the field / surface *direction* vectors (the shared
``{dir: [x,y,z]}`` descriptor) — engine-agnostic, no oxDNA imports.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

# How close to "straight into the plane" the field must point for the surface to fully
# hold it: within ~25° of exactly anti-parallel to the surface normal (cos 25° ≈ 0.906).
# A field with a larger in-plane component drifts sideways unopposed and still needs an
# anchor, so the surface only counts when the field presses nearly perpendicular into it.
_OPPOSE_COS = 0.906


def _unit(v: Optional[Sequence[float]]) -> Optional[list[float]]:
    """Unit vector, or None for a missing / zero / malformed direction."""
    if not v:
        return None
    try:
        comps = [float(c) for c in v]
    except (TypeError, ValueError):
        return None
    if len(comps) != 3:
        return None
    n = math.sqrt(sum(c * c for c in comps))
    return [c / n for c in comps] if n > 1e-12 else None


def surface_opposes_field(
    field_dir: Optional[Sequence[float]],
    surface_dir: Optional[Sequence[float]],
    *,
    cos_tol: float = _OPPOSE_COS,
) -> bool:
    """True when a hard surface with normal ``surface_dir`` HOLDS a uniform field pointing
    ``field_dir`` — the field presses (anti-parallel) into the plane within ``cos_tol``, so
    the plane's reaction balances the field-driven COM drift and no strand anchor is needed.

    A repulsion plane pushes structures along +normal (they sit on the +normal side), so a
    field along −normal presses into the plane and is held; a field along +normal (away) or
    mostly in-plane is NOT held.
    """
    f, s = _unit(field_dir), _unit(surface_dir)
    if f is None or s is None:
        return False
    return sum(a * b for a, b in zip(f, s)) <= -cos_tol


def field_needs_strand_anchor(
    *,
    has_field: bool,
    has_anchors: bool,
    field_dir: Optional[Sequence[float]] = None,
    surface_dir: Optional[Sequence[float]] = None,
) -> bool:
    """Whether a run/stage carrying a uniform field still needs ≥1 strand anchor to avoid
    centre-of-mass drift.  False when it already has anchors, or a surface opposes the field
    (a deposition setup).  This is the exact predicate the field paths gate their 400 on.
    """
    if not has_field or has_anchors:
        return False
    return not surface_opposes_field(field_dir, surface_dir)
