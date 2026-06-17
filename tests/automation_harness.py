"""Reusable validation spine for the design-automation loop (AF-1, Tier 0).

Every headless wrapper the ``/automate-feature`` loop adds is only trustworthy if
it ships with a way to *prove* it builds the right thing.  This module is that
shared proof surface: the oracles later AF items plug into instead of re-deriving.

Three building blocks:

- :func:`canonical_topology` — the id/order-independent design fingerprint
  (promoted here from ``test_section_router.py`` so any test can import it).
- :func:`roundtrip_nadoc` / :func:`assert_roundtrip_stable` — the round-trip
  oracle: build → export ``.nadoc`` → re-import → assert the topology fingerprint
  is unchanged *and* the design still validates.  This is the one-line acceptance
  test most AF wrappers will use ("does what I built survive a save/load?").
- :func:`headless_coverage_report` — the automated audit: which design/assembly
  mutation routes have a :mod:`backend.api.headless_build` wrapper and which don't,
  computed by *function-object identity* (a wrapper imports the route's handler),
  so the number can never go stale the way a hand-kept list does.

Nothing here mutates the active session: :func:`roundtrip_nadoc` runs inside an
isolated scratch document and returns a standalone deep copy.
"""
from __future__ import annotations

import inspect
from typing import Callable

from backend.api import state as design_state
from backend.api.crud import DesignImportRequest, import_design
from backend.api.headless_build import scratch_session
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.validator import validate_design


# ── Topology fingerprint ──────────────────────────────────────────────────────

def canonical_topology(d: Design):
    """ID- and order-independent fingerprint of a design's topology.

    Helices are keyed by ``grid_pos`` (unique per helix and stable across id
    schemes); strand domains reference helices by that same key.  Two designs
    with this fingerprint equal are topologically identical — the same helices
    in the same lattice cells carrying the same strand paths — regardless of how
    ids were assigned or what order the lists are in.

    (Promoted verbatim from ``test_section_router.py``; that module now imports
    it from here so there is a single definition.)
    """
    gp = {h.id: h.grid_pos for h in d.helices}
    helices = sorted(
        (
            h.grid_pos, h.length_bp, h.bp_start,
            round(h.axis_start.x, 4), round(h.axis_start.y, 4), round(h.axis_start.z, 4),
            round(h.axis_end.x, 4), round(h.axis_end.y, 4), round(h.axis_end.z, 4),
        )
        for h in d.helices
    )
    strands = sorted(
        (
            str(s.strand_type),
            tuple((gp[dm.helix_id], dm.start_bp, dm.end_bp, str(dm.direction)) for dm in s.domains),
        )
        for s in d.strands
    )
    return helices, strands


# ── Round-trip oracle ─────────────────────────────────────────────────────────

def roundtrip_nadoc(design: Design) -> Design:
    """Faithful ``.nadoc`` export→import round-trip.

    Mirrors *File → Export Design (.nadoc)* followed by *File → Import*: the
    design is serialised with :meth:`Design.to_json` (exactly the bytes
    ``GET /design/export`` ships) and re-loaded through the real
    ``POST /design/import`` handler — including the migrate / autodetect-overhang
    / backfill post-processing that route applies on every load.  Runs in an
    isolated scratch document so the active session and its undo history are
    untouched; returns a standalone deep copy of the re-imported design.
    """
    text = design.to_json()
    with scratch_session(design.lattice_type):
        import_design(DesignImportRequest(content=text))
        return design_state.get_or_404().model_copy(deep=True)


def assert_roundtrip_stable(
    build_fn: Callable[[], Design],
    *,
    roundtrip: Callable[[Design], Design] = roundtrip_nadoc,
) -> Design:
    """The AF acceptance oracle: a headless build survives a ``.nadoc`` round-trip.

    Calls ``build_fn()`` to produce a design, then asserts:

      1. the freshly-built design passes :func:`validate_design`;
      2. after ``roundtrip`` (default: real export→import), it *still* passes; and
      3. its :func:`canonical_topology` is byte-for-byte unchanged by the round-trip.

    Any AF wrapper can pin itself with ``assert_roundtrip_stable(lambda: my_build())``.
    The ``roundtrip`` seam is injectable so the meta-test can prove this oracle
    actually *fires* on a corrupted round-trip (it must not silently pass).

    Returns the re-imported design so callers can make further assertions on it.
    """
    built = build_fn()
    report_before = validate_design(built)
    assert report_before.passed, f"build did not validate before round-trip:\n{report_before}"

    reloaded = roundtrip(built)

    report_after = validate_design(reloaded)
    assert report_after.passed, f"design did not validate after round-trip:\n{report_after}"

    before, after = canonical_topology(built), canonical_topology(reloaded)
    assert before == after, (
        "round-trip changed the design topology — export/import is not identity for "
        "this build (a real bug). helices "
        f"{len(before[0])}→{len(after[0])}, strands {len(before[1])}→{len(after[1])}."
    )
    return reloaded


# ── Inverse-pair oracle ───────────────────────────────────────────────────────

def assert_inverse_pair(
    start: Design,
    forward: Callable[[], Design],
    inverse: Callable[[], Design],
) -> Design:
    """Inverse-pair invariant: an op then its inverse is topology-identity.

    ``start`` is the design *before* the operation (it must already validate).
    ``forward`` applies the op and ``inverse`` applies its inverse — each returns
    the resulting design.  In practice these are headless wrappers driving the
    active session, e.g. ``lambda: nick(h, bp, d)`` / ``lambda: ligate(h, bp, d)``.

    Asserts, in order:

      1. ``start`` passes :func:`validate_design`;
      2. the design *between* ``forward`` and ``inverse`` validates **and** its
         :func:`canonical_topology` actually differs from ``start`` — proving the
         forward op did something (an inverse pair over a no-op would pass
         vacuously, so this guard is what lets the oracle go red);
      3. after ``inverse`` the design validates and its :func:`canonical_topology`
         is byte-for-byte equal to ``start``.

    Returns the post-inverse design.  Reusable for any add/delete or +δ/−δ pair
    (nick↔ligate, loop +δ↔−δ, …).
    """
    before = canonical_topology(start)
    report0 = validate_design(start)
    assert report0.passed, f"start design did not validate before the op:\n{report0}"

    mid = forward()
    report1 = validate_design(mid)
    assert report1.passed, f"design did not validate after the forward op:\n{report1}"
    assert canonical_topology(mid) != before, (
        "forward op did not change the topology — an inverse pair over a no-op "
        "passes vacuously; pick an operation that actually mutates the design."
    )

    end = inverse()
    report2 = validate_design(end)
    assert report2.passed, f"design did not validate after the inverse op:\n{report2}"
    after = canonical_topology(end)
    assert after == before, (
        "forward then inverse changed the topology — the ops are not inverses for "
        f"this input. helices {len(before[0])}→{len(after[0])}, "
        f"strands {len(before[1])}→{len(after[1])}."
    )
    return end


# ── Geometric length oracle ───────────────────────────────────────────────────

def geometric_nucleotide_count(design: Design, helix_id: str | None = None) -> int:
    """Number of nucleotides the geometry kernel emits for *design*.

    This is the geometry layer's own count — the same ``_geometry_for_design``
    kernel that feeds ``GET /design/geometry`` — so it honours loop/skip marks: a
    skip removes a bp (one fewer nucleotide per strand), a loop adds one.  A duplex
    bp carries two strands (forward + reverse), so a clean bundle's count is twice
    its bp total.  With *helix_id*, counts only that helix's nucleotides.
    """
    nucs = _geometry_for_design(design)
    if helix_id is None:
        return len(nucs)
    return sum(1 for n in nucs if n.get("helix_id") == helix_id)


def assert_geometric_length_delta(
    start: Design,
    op: Callable[[], Design],
    expected_bp_delta: int,
    *,
    helix_id: str | None = None,
    strands_per_bp: int = 2,
) -> Design:
    """Length oracle: *op* changes the geometric nucleotide count by exactly the
    declared amount.

    ``op`` runs a headless mutation on the active design and returns the result;
    *start* is the design *before* it.  Asserts the geometry kernel's nucleotide
    count changed by ``expected_bp_delta`` bp — times ``strands_per_bp`` (geometry
    emits one nucleotide per strand per bp, and a duplex bp carries two strands).

    This pins the topology→geometry conservation law for length-changing ops: a
    loop of ``+δ`` must add δ bp of geometry, a skip of ``−δ`` must remove δ bp, and
    a removal (``delta=0``) must restore the baseline.  It is **direction-agnostic**
    — it counts *how many* nucleotides changed, never *which way* a deformation
    bends — so it is safe to reuse on bend/twist apply without reasoning about sign
    or frame conventions (which ``CLAUDE.md`` says to ask the user about).

    Pass *helix_id* to scope the count to one helix — the strong form for bulk
    apply, where the global net delta may cancel to ~0 but each helix's marks must
    still be reflected one-for-one in its own geometry.

    Returns the post-op design for further assertions.
    """
    before = geometric_nucleotide_count(start, helix_id)
    result = op()
    after = geometric_nucleotide_count(result, helix_id)
    actual = after - before
    expected = expected_bp_delta * strands_per_bp
    where = f" on helix {helix_id}" if helix_id is not None else ""
    assert actual == expected, (
        f"geometric length changed by {actual} nucleotides{where}, expected "
        f"{expected} ({expected_bp_delta:+d} bp × {strands_per_bp} strands/bp) — "
        "the op's effect on the strand graph is not faithfully reflected in geometry."
    )
    return result


# ── Circularity oracle (parametric disc primitives) ───────────────────────────

def assert_circular_disc(
    design: Design,
    requested_radius_nm: float,
    *,
    max_spread_nm: float = 0.5,
    radius_tol_nm: float = 0.5,
    helix_ids: set[str] | None = None,
) -> list[int]:
    """Geometric oracle: a built disc's helices actually trace a circle of the
    requested radius.

    Reads the *geometry* of the placed helices (their axis-endpoint spans, not a
    stored ``length_bp`` field) so it pins the full headless path
    ``radius → footprint → route → builder → placed geometry`` end-to-end — the
    pure circularity functions (:mod:`backend.core.circle_primitive`) only pin the
    footprint math in isolation.  Each helix's bp length is its axis span /
    rise; the helices are ordered by lattice column (the disc is a contiguous,
    centre-symmetric row), then fed to the existing circularity oracle:

      1. :func:`circularity_spread` < ``max_spread_nm`` — every column's implied
         radius ``√(x² + (L/2)²)`` agrees to within tolerance (a true circle has
         zero spread);
      2. :func:`fit_radius` is within ``radius_tol_nm`` of ``requested_radius_nm``
         — asking for radius R lands a disc of radius ≈ R.

    Pass *helix_ids* to assess only the disc helices when the design also carries
    pre-existing DNA; default assesses every helix (a clean scratch build).
    Returns the per-column bp lengths it measured.
    """
    from backend.core.circle_primitive import circularity_spread, fit_radius

    helices = [
        h for h in design.helices
        if (helix_ids is None or h.id in helix_ids) and h.grid_pos is not None
    ]
    assert helices, "no disc helices found to assess circularity"
    helices.sort(key=lambda h: h.grid_pos[1])

    lengths: list[int] = []
    for h in helices:
        dx = h.axis_end.x - h.axis_start.x
        dy = h.axis_end.y - h.axis_start.y
        dz = h.axis_end.z - h.axis_start.z
        span_nm = (dx * dx + dy * dy + dz * dz) ** 0.5
        lengths.append(round(span_nm / BDNA_RISE_PER_BP))

    spread = circularity_spread(lengths)
    assert spread < max_spread_nm, (
        f"placed disc is not circular: circularity spread {spread:.3f} nm "
        f"(implied per-column radii disagree by more than {max_spread_nm} nm) — "
        f"lengths={lengths}"
    )
    fitted = fit_radius(lengths)
    assert abs(fitted - requested_radius_nm) <= radius_tol_nm, (
        f"placed disc radius {fitted:.3f} nm differs from the requested "
        f"{requested_radius_nm} nm by more than {radius_tol_nm} nm — "
        f"the radius→geometry path is off."
    )
    return lengths


# ── Deformed-placement oracle (continuation onto a bent/twisted frame) ─────────

def assert_on_deformed_frame(
    design_before: Design,
    design_after: Design,
    source_bp: int,
    cells,
    *,
    ref_helix_id: str | None = None,
    pos_tol_nm: float = 0.02,
    min_deflection_nm: float = 0.5,
) -> float:
    """Geometric oracle: a deformed continuation's new helices land on the DEFORMED
    cross-section frame at ``source_bp`` — and *not* where a straight extrude would
    put them.

    A ``bundle-deformed-continuation`` places each new helix's ``axis_start`` at the
    cross-section grid point ``grid_origin + frame_right·lx + frame_up·ly`` of the
    deformed frame sampled at ``source_bp``.  This oracle pins the whole headless
    path ``source_bp → deformed-frame → route → builder → placed geometry`` by:

      1. **On the deformed frame.** Independently re-derives the deformed frame
         (:func:`deformed_frame_at_bp` on *design_before*, the same input the route
         uses when ``source_bp`` is set) and the per-cell placement, then asserts
         every newly-appended helix's ``axis_start`` matches its cell's deformed
         placement to within ``pos_tol_nm``.  A builder that mis-applied the frame
         (swapped right/up, wrong lattice pitch, used the *straight* blunt-end
         instead of the frame) fails here.
      2. **Not the straight frame (the can-go-red guard).** Recomputes the same
         placement on a copy of *design_before* with its deformations stripped (the
         frame a plain continuation would use) and asserts the deformed placement is
         displaced from it by more than ``min_deflection_nm`` for at least one cell.
         Without this the oracle would pass vacuously on an un-deformed design — it
         is the analog of :func:`assert_inverse_pair`'s "forward really mutated"
         guard.

    Direction-agnostic: it only measures *that* the placement moved and *where* it
    landed, never reasoning about bend/twist sign or frame handedness (which
    ``CLAUDE.md`` reserves for the user).  ``cells`` is the ``(row, col)`` list
    passed to the continuation; *design_before* is the design *before* it ran.
    Returns the maximum deformed-vs-straight deflection (nm) it observed.
    """
    import numpy as np

    from backend.core.deformation import deformed_frame_at_bp
    from backend.core.lattice import honeycomb_position

    before_ids = {h.id for h in design_before.helices}
    new_helices = [h for h in design_after.helices if h.id not in before_ids]
    cells = [tuple(c) for c in cells]
    assert len(new_helices) == len(cells), (
        f"expected one appended helix per cell ({len(cells)}), got {len(new_helices)}"
    )

    def _placements(design):
        frame = deformed_frame_at_bp(design, source_bp, ref_helix_id)
        origin = np.array(frame["grid_origin"], dtype=float)
        right = np.array(frame["frame_right"], dtype=float)
        up = np.array(frame["frame_up"], dtype=float)
        out = {}
        for row, col in cells:
            lx, ly = honeycomb_position(row, col)
            out[(row, col)] = origin + right * lx + up * ly
        return out

    deformed = _placements(design_before)
    straight_design = design_before.model_copy(deep=True)
    straight_design.deformations = []
    straight = _placements(straight_design)

    # Each new helix must sit on exactly one cell's deformed placement.
    remaining = dict(deformed)
    for h in new_helices:
        start = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        hit = None
        for cell, p in remaining.items():
            if float(np.linalg.norm(start - p)) <= pos_tol_nm:
                hit = cell
                break
        assert hit is not None, (
            f"new helix {h.id} at {start.tolist()} is not within {pos_tol_nm} nm of "
            f"any deformed-frame cell placement {[p.tolist() for p in remaining.values()]} "
            "— the continuation did not land on the deformed cross-section."
        )
        del remaining[hit]

    max_deflection = max(
        float(np.linalg.norm(deformed[cell] - straight[cell])) for cell in deformed
    )
    assert max_deflection > min_deflection_nm, (
        f"deformed placement differs from a straight extrude by at most "
        f"{max_deflection:.3f} nm (< {min_deflection_nm} nm) — the deformation had no "
        "geometric effect, so this oracle would pass vacuously (use a design with a "
        "real bend/twist, or this is a bug where source_bp was ignored)."
    )
    return max_deflection


# ── Deformation-angle oracle (bend/twist magnitude) ───────────────────────────

def assert_deformation_angle(
    design_after: Design,
    plane_a_bp: int,
    plane_b_bp: int,
    expected_total_deg: float,
    *,
    ref_helix_id: str | None = None,
    angle_tol_deg: float = 1.0,
    step_bp: int = 1,
    min_angle_deg: float = 5.0,
) -> float:
    """Geometric magnitude oracle: a bend/twist rotates the deformed cross-section
    frame by exactly the requested total angle across ``[plane_a_bp, plane_b_bp]``.

    *design_after* is the design *after* the deformation was added (e.g. via
    :func:`backend.api.headless_build.add_bend` / :func:`~.add_twist`).  The oracle
    walks the deformed frame (:func:`deformed_frame_at_bp`) in ``step_bp`` bp
    increments from ``plane_a_bp`` to ``plane_b_bp`` and **sums the magnitude of
    each step's relative frame rotation** (the angle of ``R(p₁)·R(p₀)ᵀ``, taken from
    the orthonormal frame ``[frame_right | frame_up | axis_dir]``).  Summing per-step
    magnitudes — rather than the single ``plane_a→plane_b`` relative rotation —
    UNWRAPS angles past 180°/360°: a 540° twist reads as 540°, not 180°.  It pins the
    whole headless path ``request → route → DeformationOp → deformed frame``:

      1. **Matches the request.** The accumulated rotation is within
         ``angle_tol_deg`` of ``expected_total_deg`` — for a bend that is
         ``curvature_deg_per_bp × (plane_b − plane_a)``; for a twist the total twist
         (``total_degrees``, or ``degrees_per_nm × span_nm``).  A builder that scaled
         the curvature wrong, ignored the planes, or dropped the op fails here.
      2. **Is non-trivial (the can-go-red guard).** The measured angle exceeds
         ``min_angle_deg``, so the oracle FAILS on an un-deformed design instead of
         passing vacuously — the analog of :func:`assert_inverse_pair`'s "forward
         really mutated" guard.

    **Direction-agnostic by construction:** it measures only the *magnitude* of the
    frame rotation (an ``arccos`` is always ≥ 0), never the bend/twist sign or frame
    handedness — which ``CLAUDE.md`` reserves for the user.  Pass *ref_helix_id* to
    sample the arm containing that helix.  Returns the measured cumulative angle (°).
    """
    import numpy as np

    from backend.core.deformation import deformed_frame_at_bp

    assert plane_b_bp > plane_a_bp, "plane_b_bp must be greater than plane_a_bp"

    def _frame_R(bp: int):
        f = deformed_frame_at_bp(design_after, bp, ref_helix_id)
        return np.column_stack([f["frame_right"], f["frame_up"], f["axis_dir"]])

    bps = list(range(plane_a_bp, plane_b_bp, step_bp))
    if bps[-1] != plane_b_bp:
        bps.append(plane_b_bp)

    total = 0.0
    for p0, p1 in zip(bps, bps[1:]):
        M = _frame_R(p1) @ _frame_R(p0).T
        cos = (float(np.trace(M)) - 1.0) / 2.0
        total += float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))

    assert total > min_angle_deg, (
        f"deformed frame rotated by only {total:.3f}° across "
        f"[{plane_a_bp}, {plane_b_bp}] (< {min_angle_deg}°) — the design appears "
        "un-deformed, so this oracle would pass vacuously (apply a real bend/twist "
        "first, or the planes/params were ignored)."
    )
    assert abs(total - expected_total_deg) <= angle_tol_deg, (
        f"deformed frame rotated by {total:.3f}° across "
        f"[{plane_a_bp}, {plane_b_bp}], expected {expected_total_deg:.3f}° "
        f"(±{angle_tol_deg}°) — the realised curvature does not match the request."
    )
    return total


# ── Headless-coverage audit ───────────────────────────────────────────────────

_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def headless_coverage_report() -> dict:
    """Automated audit: design/assembly mutation routes vs. headless wrappers.

    A route counts as *covered* when its endpoint function is imported by
    :mod:`backend.api.headless_build` (every wrapper there pulls in the exact
    route handler it drives — e.g. ``create_bundle as _route_create_bundle``).
    Matching by the function object, not by a string, means this report tracks
    reality automatically: add a wrapper and the route flips to covered; rename a
    route and nothing silently rots.

    Returns ``{total, covered, uncovered, covered_routes, uncovered_routes}``
    where each ``*_routes`` entry is ``{"methods", "path", "endpoint"}`` sorted by
    path.  ``uncovered_routes`` is the live backlog of AF wrapper candidates.
    """
    from backend.api import headless_build
    from backend.api.main import app

    wrapped_fns = {
        obj for obj in vars(headless_build).values() if inspect.isfunction(obj)
    }

    covered_routes: list[dict] = []
    uncovered_routes: list[dict] = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods or not (methods & _MUTATION_METHODS):
            continue
        if "/design" not in path and "/assembly" not in path:
            continue
        row = {
            "methods": sorted(methods & _MUTATION_METHODS),
            "path": path,
            "endpoint": route.endpoint.__name__,
        }
        (covered_routes if route.endpoint in wrapped_fns else uncovered_routes).append(row)

    covered_routes.sort(key=lambda r: r["path"])
    uncovered_routes.sort(key=lambda r: r["path"])
    total = len(covered_routes) + len(uncovered_routes)
    return {
        "total": total,
        "covered": len(covered_routes),
        "uncovered": len(uncovered_routes),
        "covered_routes": covered_routes,
        "uncovered_routes": uncovered_routes,
    }
