"""
Pure-math helper for "Polymerize (Periodic)" — derive a periodic origami part's
REPEAT TRANSFORM directly from its end-to-end seam geometry, so a polymer chain
can be grown from a SINGLE instance with no hand-defined mate.

Background
----------
A periodic part is one the user has marked with ``is_periodic_seam`` forced
ligations in the cadnano editor's periodic-boundary view.  Each such ligation
records a 3' terminus and a 5' terminus (helix, bp, direction).  When the part
tiles, copy N's far end docks onto copy N+1's near end; the rigid transform that
carries one copy onto the next is the part's repeat transform ``delta``.

This module derives ``delta`` by rigidly registering the part's NEAR-end seam
cross-sections onto its FAR-end seam cross-sections (Kabsch / Umeyama, no scale).
``delta`` is expressed in the part's LOCAL frame and satisfies, for every seam,

    delta @ F_near_local ≈ F_far_local

so that placing copy k at ``T_seed @ delta**k`` lands copy k+1's near end exactly
onto copy k's far end.

Register AXIS GEOMETRY ONLY — never the radial/twist phase (CRITICAL)
--------------------------------------------------------------------
The repeat transform is fit from each seam's AXIS POINT (origin) + AXIS TANGENT
(z) — NOT the cross-strand radial.  This is the fix for a spiral-curvature bug:
the helical twist accumulated over one period (period_bp · 34.3°) is generally
incommensurate (e.g. teeth.nadoc: 251 bp → ~329°).  A rigid transform CANNOT
reproduce a large radial rotation of OFF-CENTRE helices (rotating each helix
about its own axis is non-rigid), so feeding the radial x/y axis-tips into the
Kabsch fit forced a least-squares compromise that leaked the twist into a
perpendicular TILT → a per-copy bend → a visible spiral, even for a perfectly
straight part.  The twist is INTERNAL to each copy and continues through the
ligated backbone topologically; it must not enter the rigid placement.

Registering origin + z-tangent only:
  • straight part  → origins differ by pure axial translation, tangents parallel
                     → ``delta`` is a pure translation (no spurious bend);
  • curved part    → near vs far axis tangents differ in DIRECTION, which the
                     z-tip captures, so a genuine bend is still recovered;
  • twist about the axis falls in the fit's null space → minimal (no) rotation,
    leaving copies un-twisted (the groove phase may jump at incommensurate
    junctions, but the fibre stays straight — the intended result).

The per-terminus frame is direction-independent (origin = true helix axis point,
recovered analytically by undoing the minor-groove offset; z = axis_tangent,
identical for forward/reverse strands), so forward-3'↔reverse-5' seams register
cleanly.  The radial x/y are still computed (the axis-point recovery needs them)
but are deliberately excluded from the registration correspondences.

NEAR vs FAR is assigned by bp value (smaller bp = near, larger bp = far), NOT by
the 3'/5' role: a reverse strand presents its 3' end at the near (low-bp) side, so
keying off bp magnitude is the polarity-robust way to identify the two ends.

No FastAPI imports — unit-testable in isolation (mirrors ``assembly_polymer.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Mat4x4

if TYPE_CHECKING:  # pragma: no cover
    from backend.core.models import Design


class PeriodicSeamError(ValueError):
    """Raised when a design lacks usable periodic-seam geometry."""


def _unit(v: np.ndarray) -> "np.ndarray | None":
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return None
    return v / n


# ── Seam endpoint resolution ───────────────────────────────────────────────────


def _seam_endpoints(design: "Design") -> List[Tuple[Tuple[str, int], Tuple[str, int]]]:
    """Per periodic seam, return ``(near, far)`` where each is ``(helix_id, bp)``.

    ``near`` is the lower-bp endpoint, ``far`` the higher-bp one.  We key off bp
    value (not the 3'/5' role) because a reverse strand presents its 3' end at the
    near/low-bp side — see module docstring.
    """
    seams = [fl for fl in design.forced_ligations if fl.is_periodic_seam]
    if not seams:
        raise PeriodicSeamError("Design has no is_periodic_seam forced ligations.")
    out: List[Tuple[Tuple[str, int], Tuple[str, int]]] = []
    for fl in seams:
        a = (fl.three_prime_helix_id, int(fl.three_prime_bp))
        b = (fl.five_prime_helix_id, int(fl.five_prime_bp))
        near, far = (a, b) if a[1] <= b[1] else (b, a)
        out.append((near, far))
    return out


# ── Cross-section frame at a (helix, bp) ───────────────────────────────────────


def _section_frame_from_arrs(arrs: dict, bp: int) -> "np.ndarray | None":
    """Direction-independent helix cross-section frame (4×4 local SE3) at *bp*.

    ``arrs`` is the dict returned by ``deformed_nucleotide_arrays``.  Returns ``None`` if
    the bp is missing from the helix geometry on either strand — a half-populated bp has no
    well-defined cross-section, and that guard predates the site.

    origin = the forward nucleotide's own helix axis point, z = axis_tangent,
    x = its outward radial, y = z×x.  All three are read from the carried helical site;
    ``helix_dir`` used to be needed for the minor-groove sign and is gone with the solve.
    """
    bp_arr = arrs["bp_indices"]
    dir_arr = arrs["directions"]
    fwd_mask = (bp_arr == bp) & (dir_arr == 0)
    rev_mask = (bp_arr == bp) & (dir_arr == 1)
    if not fwd_mask.any() or not rev_mask.any():
        return None
    # The FORWARD nucleotide alone defines the frame now.  ``ri`` is not read: the old
    # solve needed the reverse bead for its chord, and on a design whose two strands sit in
    # DIFFERENT domain-level clusters that chord spanned two frames — measured on
    # VoltronCore, the reverse bead was 7.5-7.9 nm from the forward bead's axis instead of
    # ~1 nm, and the recovered axis was garbage for 35 of 5549 sampled cross-sections.
    fi = int(fwd_mask.argmax())
    z = _unit(np.asarray(arrs["axis_tangents"][fi], dtype=float))
    if z is None:
        return None

    # The forward backbone's radial direction and its axis point are CARRIED
    # (geometry.NucleotidePosition / project_helical_site.md), so they are read.
    #
    # Until 2026-08-07 this solved a 2×2 for them instead: both backbones sit at
    # HELIX_RADIUS from the axis separated by the signed minor-groove angle, so
    # chord = rev−fwd = HELIX_RADIUS·(Rot_z(Δ)−I)·r_fwd could be inverted for r_fwd.
    # That worked, and it hard-coded the build convention — HELIX_RADIUS and the groove
    # sign — into a consumer, which is why it carried a warning that it is "only correct
    # for beads the geometric layer placed" and would silently return a WRONG axis (not
    # fail) if the measured re-placement ever moved down into geometry.py.  Reading the
    # site retires that entire failure mode: a re-placed bead brings its own site or none.
    x = _unit(np.asarray(arrs["radial_hats"][fi], dtype=float))
    if x is None:
        return None
    origin = np.asarray(arrs["axis_points"][fi], dtype=float)
    y = np.cross(z, x)

    F = np.eye(4, dtype=float)
    F[:3, 0] = x
    F[:3, 1] = y
    F[:3, 2] = z
    F[:3, 3] = origin
    return F


def _axis_points(F: np.ndarray, lever: float) -> List[np.ndarray]:
    """Axis-point + axis-tangent tip of a frame — the 2-point cloud used for the
    Kabsch fit.  Deliberately EXCLUDES the radial (x/y) tips: the radial encodes
    the helical twist phase, which is incommensurate over one period and must not
    enter the rigid repeat (see module docstring — including it bent straight
    parts into a spiral).  Position + tangent direction capture translation and
    genuine curvature; twist is left to the topology."""
    o = F[:3, 3]
    return [o.copy(), o + lever * F[:3, 2]]  # origin, +z (axis tangent) tip


def _bp_step_screw(twist_per_bp_rad: float, rise: float) -> np.ndarray:
    """Body-frame screw advancing one bp along a cross-section frame's own axis.

    A cross-section frame has its origin ON the helix axis and z ALONG it, so
    moving one bp toward higher bp is exactly right-multiplying by this fixed
    matrix: rotate ``twist`` about local-z, translate ``rise`` along local-z.
    """
    c, s = np.cos(twist_per_bp_rad), np.sin(twist_per_bp_rad)
    S = np.eye(4, dtype=float)
    S[:3, :3] = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    S[:3, 3] = np.array([0.0, 0.0, rise])
    return S


# ── Rigid registration ─────────────────────────────────────────────────────────


def _kabsch(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Rigid transform (4×4) mapping ``src`` points onto ``dst`` in a least-
    squares sense (rotation + translation, no scale, reflection-guarded)."""
    src_c = src.mean(axis=0)
    dst_c = dst.mean(axis=0)
    P = src - src_c
    Q = dst - dst_c
    H = P.T @ Q
    U, _S, Vt = np.linalg.svd(H)
    d = float(np.sign(np.linalg.det(Vt.T @ U.T)))
    if d == 0.0:
        d = 1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    T = np.eye(4, dtype=float)
    T[:3, :3] = R
    T[:3, 3] = dst_c - R @ src_c
    return T


def _iter_seam_frames(design: "Design") -> List[Tuple[np.ndarray, np.ndarray]]:
    """Resolve every periodic seam to ``(F_near, F_far_next)`` local frames.

    ``F_near`` is the near (low-bp) cross-section frame; ``F_far_next`` is the
    far (high-bp) frame advanced ONE BP toward higher bp.  The seam bonds copy
    N's far nucleotide directly to copy N+1's near nucleotide — a one-rise
    backbone step — so copy N+1's near end abuts one bp *past* copy N's far
    nucleotide.  (Registering near→far alone is one bp short and, for a
    multi-helix bundle, under-rotated — that mismatch produced an inconsistent
    tilted-axis fit before the +1bp advance was added.)

    Raises :class:`PeriodicSeamError` when there are no periodic seams.  Skips
    seams whose helices/bps don't resolve to geometry.

    NOTE: ``ForcedLigation.extra_bases`` (single-stranded junction bases) are
    not yet modelled — only direct (zero-extra-base) seams register exactly.
    """
    from backend.core.deformation import deformed_nucleotide_arrays

    endpoints = _seam_endpoints(design)  # raises if no periodic seams
    arrs_cache: dict = {}

    def _frame(helix_id: str, bp: int) -> "Tuple[np.ndarray, float] | None":
        helix = design.find_helix(helix_id)
        if helix is None:
            return None
        if helix_id not in arrs_cache:
            arrs_cache[helix_id] = deformed_nucleotide_arrays(helix, design)
        F = _section_frame_from_arrs(arrs_cache[helix_id], bp)
        if F is None:
            return None
        return F, float(helix.twist_per_bp_rad)

    out: List[Tuple[np.ndarray, np.ndarray]] = []
    for near, far in endpoints:
        rn = _frame(*near)
        rf = _frame(*far)
        if rn is None or rf is None:
            continue
        f_near, _ = rn
        f_far, twist_far = rf
        # The +1 backbone step is a body-frame screw — twist around local-z +
        # rise along local-z. The bend's curvature contribution to this 1 bp
        # step is not added here: in the κ-direct model, the auto-extended
        # window already covers each helix's near→far_next interval, so the
        # frames at near and far already carry the per-helix rotation
        # κ × (effective_far − effective_near). The +1 step is the ligation
        # gap and stays straight — Kabsch sees the bend rotation from f_far,
        # not from this step.
        f_far_next = f_far @ _bp_step_screw(twist_far, BDNA_RISE_PER_BP)
        out.append((f_near, f_far_next))
    return out


def derive_periodic_delta(design: "Design", lever_nm: float = 1.0) -> np.ndarray:
    """Repeat transform (4×4 part-local SE3) carrying one copy onto the next.

    Rigidly registers (Kabsch, no scale) the NEAR seam AXIS POINTS + AXIS
    TANGENTS onto the ONE-BP-PAST-FAR ones over all periodic seams, so a chain
    placed at ``T_seed @ delta**k`` docks copy k+1's near end onto copy k's far
    end.  Only axis geometry is fit — the radial/twist phase is excluded so a
    straight part stays straight (see module docstring: registering the radial
    leaked the incommensurate per-period twist into a spurious bend → spiral).

    Raises :class:`PeriodicSeamError` when no periodic seam resolves to geometry.
    """
    frames = _iter_seam_frames(design)  # raises if no periodic seams
    src_pts: List[np.ndarray] = []
    dst_pts: List[np.ndarray] = []
    for f_near, f_far_next in frames:
        src_pts.extend(_axis_points(f_near, lever_nm))
        dst_pts.extend(_axis_points(f_far_next, lever_nm))
    if not src_pts:
        raise PeriodicSeamError("No periodic seam resolved to helix geometry.")
    return _kabsch(np.asarray(src_pts, dtype=float), np.asarray(dst_pts, dtype=float))


def derive_periodic_delta_mat4(design: "Design") -> Mat4x4:
    """Thin wrapper returning the repeat transform as a :class:`Mat4x4`."""
    return Mat4x4.from_array(derive_periodic_delta(design))


def solve_closing_curvature(design: "Design", count: int) -> "float | None":
    """Return ``curvature_deg_per_bp`` that closes the chain in ``count`` copies.

    Solves ``count × δ_rotation(κ) == 360°`` numerically: probes the design at
    a small reference κ to read off the linear relationship ``δ_rot = α · κ``
    (true to floating-point precision since the bend math is linear in κ once
    the window is fixed), then sets ``κ_close = (360° / count) / α``.

    Returns ``None`` when the design has exactly one bend op (so there's a
    single κ to set); the caller is expected to assign κ to that op. When the
    design has no bend op, no curvature is needed (chain is already straight)
    — returns ``0.0``. When more than one bend op, returns ``None`` because the
    target κ is ambiguous (multiple knobs).

    Raises :class:`PeriodicSeamError` when no periodic seam resolves.
    """
    import math as _math

    bend_ops = [
        op for op in design.deformations if getattr(op.params, "kind", None) == "bend"
    ]
    if not bend_ops:
        return 0.0
    if len(bend_ops) != 1:
        return None
    op = bend_ops[0]

    # Probe with κ_probe = 1.0 — the bend math is linear in κ on a fixed
    # window, so this single sample is enough to invert.
    original_kappa = op.params.curvature_deg_per_bp
    op.params.curvature_deg_per_bp = 1.0
    try:
        delta = derive_periodic_delta(design)
    finally:
        op.params.curvature_deg_per_bp = original_kappa
    R = delta[:3, :3]
    cos_t = max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))
    rot_per_unit_kappa = float(_math.degrees(_math.acos(cos_t)))
    if rot_per_unit_kappa < 1e-9:
        return None
    return (360.0 / float(count)) / rot_per_unit_kappa


def closure_residual(design: "Design", count: int) -> "Tuple[float, float]":
    """Predict how far a chain of ``count`` copies misses closing the ring.

    Returns ``(rotation_residual_deg, translation_residual_nm)`` — the rotation
    and translation magnitudes of ``δ**count`` away from identity. Both ≈ 0 ⇔
    chain closes exactly. Used by the polymerize-periodic UI to warn the user
    when their bend's per-period angle doesn't divide 360° evenly (i.e. won't
    form a closed ring). A value of 0/0 for count=4 means the 4-tile ring is
    geometrically closed; non-zero means the user should adjust κ.

    Raises :class:`PeriodicSeamError` when the design has no periodic seam.
    """
    if count < 1:
        return 0.0, 0.0
    delta = derive_periodic_delta(design)
    out = np.eye(4)
    for _ in range(int(count)):
        out = out @ delta
    R = out[:3, :3]
    t = out[:3, 3]
    cos_t = max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))
    angle_deg = float(np.degrees(np.arccos(cos_t)))
    trans_nm = float(np.linalg.norm(t))
    return angle_deg, trans_nm


def principal_seam_connectors(
    design: "Design",
) -> "Tuple[Tuple[list, list], Tuple[list, list]] | None":
    """Local connector anchors for the FIRST resolvable periodic seam.

    Returns ``((p_5p, n_5p), (p_3p, n_3p))`` where each is ``(position, normal)``
    in part-local coordinates: the 5' (near) anchor at the near frame origin and
    the 3' (far) anchor one bp past the far nucleotide (so copy k's 3p coincides
    with copy k+1's 5p).  Normals are the cross-section z (axis tangent).  One
    pair is enough — a rigid joint carrying ``mate_relative_transform`` fixes all
    6 DOF; extra seams would over-constrain.  Returns ``None`` if no seam resolves.
    """
    frames = _iter_seam_frames(design)
    if not frames:
        return None
    f_near, f_far_next = frames[0]
    near = (f_near[:3, 3].tolist(), f_near[:3, 2].tolist())
    far = (f_far_next[:3, 3].tolist(), f_far_next[:3, 2].tolist())
    return near, far
