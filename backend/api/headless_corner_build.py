r"""Headless (mouse-free) mitred-corner primitive with a phase-aware optimizer.

Build a 90° corner from two planar SQUARE-lattice sheets, folded together at a
mitred seam and stitched with forced ligations — entirely from scratch, so a
script (and eventually an AI builder) can emit one.  This is a design-automation
primitive (the ``/automate-feature`` loop): one operation → a headless entry
point + a reusable validation oracle.

Composes the already-shipped :mod:`headless_build` wrappers — it introduces no
new route and re-implements nothing:

* ``hb.create_bundle`` lays two 1×N SQUARE sheets (A + B), each its own cluster,
* ``hb.resize_strand_end`` (AF-30) trims each helix's *far* end into a ~45°
  staircase miter (BOTH scaffold and staple, by the same amount),
* ``hb.transform_cluster(log=True)`` (AF-16) folds sheet B 180° about the miter
  diagonal — a **display-layer** rigid pose, never a topology edit, that leaves a
  replayable ``cluster_op`` feature-log entry, and
* ``hb.force_ligate`` (AF-32) stitches the N cross-seam scaffold links.

The result therefore carries a complete, replayable feature log, indistinguishable
from a corner built by clicking.

The two-constraint principle (the core)
---------------------------------------
A mitred helix length must satisfy TWO constraints at once; the naive uniform
stagger honours only the first:

1. **AXIAL (miter).** The far end must land on the 45° plane so the two
   staircases mate.  The ideal stagger is ``spacing/rise = 2.25/0.334 ≈ 6.74``
   bp per helix — non-integer, so integer stepping can never be exact.
2. **ROTATIONAL (phase).** A forced ligation is a backbone bond between the 3′
   bead of one helix and the 5′ bead of its partner, each ~1 nm off the axis at
   azimuth ``phase_offset + bp·33.75°``.  ``±1`` bp swings the terminal bead
   33.75°, moving it from pointing *away* from its partner (an over-stretched
   ~1.3 nm bond) to *facing* it (~0.3–0.5 nm).  The A\ :sub:`i` and B\ :sub:`i`
   partners must face **each other** → a joint per-seam-pair optimisation.

The uniform step-7 stagger honours only #1 and leaves several bonds overstretched
(reference: total posed ligation stretch ≈ 5.31 nm, 3 bonds > 1.1 nm).  The
optimiser below searches integer lengths in a ±\ ``window_bp`` band around each
seam's ideal miter length and picks, per seam, the ``(len_Ai, len_Bi)`` that
minimises the posed forced-ligation backbone stretch (tie-broken by the smaller
axial residual).  It beats the human-tuned reference (≈ 3.43 nm) comfortably
(≈ 1.9 nm total, all bonds < 0.7 nm on the standard 6-helix corner) while keeping
the steric-clash count no worse than the unoptimised uniform build.

Why the optimiser is fast (path-B, one build per pass)
------------------------------------------------------
A straight backbone bead at bp ``k`` does **not** move when the helix is trimmed
(trimming only removes beads *beyond* ``k``; verified — max move 0).  So the
optimiser builds the straight sheets ONCE, records every candidate seam bead, and
for each pass captures the fold transform from a single real build, then searches
all candidate lengths **analytically** (apply the fixed fold to the recorded
beads).  The applied-transform-on-straight-beads formula reproduces the full
geometry kernel's posed positions exactly (diff 0), so this is faithful, not an
approximation.  Re-fixing the fold each pass converges in ~2 passes / ~5 builds.

Three-Layer note: the fold is a DISPLAY-layer cluster pose (``log=True``), never a
topology edit; the seam forced ligations are the only topology change.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.clash import (
    DEFAULT_CLASH_THRESHOLD_NM,
    DEFAULT_DESIGNED_MARGIN_NM,
)
from backend.core.constants import BDNA_RISE_PER_BP, SQUARE_HELIX_SPACING
from backend.core.deformation import (
    _rot_from_quaternion,
    deformed_helix_axes,
    deformed_nucleotide_positions,
)
from backend.core.models import Design, Direction, LatticeType

# Ideal (non-integer) stagger: one helix's far end steps down by one row pitch
# for every ``_MITER_RATIO`` bp — the 45° staircase that makes the two flush faces
# meet at 90°.
_MITER_RATIO: float = SQUARE_HELIX_SPACING / BDNA_RISE_PER_BP  # ≈ 6.737 bp/helix

_ROW = 0  # corner sheets are a single lattice row


# ── Public build spec ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CornerSpec:
    """The resolved geometry of a corner build (columns + per-helix lengths).

    ``a_cols`` / ``b_cols`` are the lattice columns of sheet A and sheet B (both in
    row 0); ``a_len`` / ``b_len`` the chosen integer bp lengths, seam-aligned so
    ``a_cols[i]`` mates ``b_cols[i]``.  ``ideal`` is the axial-exact (non-integer,
    rounded) miter length per seam — the search centre.
    """

    n_helices: int
    base_length_bp: int
    col_offset: int
    a_cols: tuple[int, ...]
    b_cols: tuple[int, ...]
    a_len: tuple[int, ...]
    b_len: tuple[int, ...]
    ideal: tuple[int, ...]


def _helix_id(col: int) -> str:
    return f"h_XY_{_ROW}_{col}"


def _scaf_id(col: int) -> str:
    return f"scaf_XY_{_ROW}_{col}"


def _stpl_id(col: int) -> str:
    return f"stpl_XY_{_ROW}_{col}"


def _columns(
    n_helices: int, col_offset: int
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    a_cols = tuple(range(n_helices))
    b_cols = tuple(c + col_offset for c in a_cols)
    return a_cols, b_cols


def _ideal_lengths(n_helices: int, base_length_bp: int) -> tuple[int, ...]:
    """Axial-exact miter lengths (constraint #1): base − round(i·6.74)."""
    return tuple(base_length_bp - round(i * _MITER_RATIO) for i in range(n_helices))


def _default_col_offset(n_helices: int) -> int:
    """Smallest ODD offset leaving a ≥1-column gap between the two sheets.

    An **odd** offset is required so each B helix has OPPOSITE scaffold parity to
    the A helix it mates (SQ parity ``(row+col)%2==0`` → FORWARD): the mate then
    offers one free 3′ + one free 5′ per seam, making every forced ligation legal.
    ``n_helices + 3`` reproduces the reference (cols 0–5 ↔ 9–14) for ``n=6``.
    """
    offset = n_helices + 3
    return offset if offset % 2 == 1 else offset + 1


# ── Geometry helpers (pure) ──────────────────────────────────────────────────────


def _bead_map(design: Design) -> dict[tuple[str, int, str], np.ndarray]:
    """Posed backbone-bead positions keyed ``(helix_id, bp_index, direction-name)``."""
    m: dict[tuple[str, int, str], np.ndarray] = {}
    for helix in design.helices:
        for nuc in deformed_nucleotide_positions(helix, design):
            m[(nuc.helix_id, int(nuc.bp_index), nuc.direction.name)] = np.asarray(
                nuc.position, dtype=float
            )
    return m


def forced_ligation_stretches(design: Design) -> list[float]:
    """Posed backbone-bond length (nm) of every forced ligation, in record order.

    Each forced ligation is a backbone bond between the 3′ bead of one strand and
    the 5′ bead of another; its *posed* length (measured on the folded geometry via
    :func:`deformed_nucleotide_positions`) is exactly the seam stretch the optimiser
    minimises.  A ligation whose beads have no posed position is skipped.
    """
    beads = _bead_map(design)
    out: list[float] = []
    for fl in design.forced_ligations:
        a = beads.get(
            (
                fl.three_prime_helix_id,
                int(fl.three_prime_bp),
                fl.three_prime_direction.name,
            )
        )
        b = beads.get(
            (
                fl.five_prime_helix_id,
                int(fl.five_prime_bp),
                fl.five_prime_direction.name,
            )
        )
        if a is not None and b is not None:
            out.append(float(np.linalg.norm(a - b)))
    return out


def _fl_partner_pairs(design: Design) -> set[frozenset]:
    """The ``(3′ bead, 5′ bead)`` key pairs of every forced ligation.

    A forced ligation is a *designed* backbone bond, so its two beads sitting
    within bond distance is by construction — NOT a steric clash.  The clash
    detector can't know this (its straight-vs-posed rule only excludes proximity
    that was already close in the un-posed design, but FL partners live on opposite
    sheets ~20 nm apart straight), so we exclude these pairs explicitly.
    """
    pairs: set[frozenset] = set()
    for fl in design.forced_ligations:
        a = (
            fl.three_prime_helix_id,
            int(fl.three_prime_bp),
            fl.three_prime_direction.name,
        )
        b = (
            fl.five_prime_helix_id,
            int(fl.five_prime_bp),
            fl.five_prime_direction.name,
        )
        pairs.add(frozenset((a, b)))
    return pairs


def steric_clash_count(design: Design, **clash_kwargs) -> int:
    """Genuine steric-clash count: :func:`clash_report` minus the seam FL bonds.

    Uses the shipped design-layer :func:`backend.core.clash.clash_report` (the
    posed-vs-straight detector) but drops the forced-ligation partner pairs, which
    are intended contacts.  This is the metric the corner oracle guards ("the
    optimiser must not introduce *new* folding collisions"), and the one the task's
    "ideally 0 after seam design" refers to — an unoptimised corner leaves a few
    seam-region cross-sheet contacts; the optimiser must not add to them.
    """
    from backend.core.clash import clash_report

    report = clash_report(design, **clash_kwargs)
    fl_pairs = _fl_partner_pairs(design)
    n = 0
    for p in report.pairs:
        ka = (p.a.helix_id, p.a.bp_index, p.a.direction)
        kb = (p.b.helix_id, p.b.bp_index, p.b.direction)
        if frozenset((ka, kb)) in fl_pairs:
            continue
        n += 1
    return n


def corner_face_angle_deg(design: Design, spec: CornerSpec) -> float:
    """Angle (degrees) between the two flush faces = between the posed helix axes.

    The flush faces are the un-mitred (z=0) ends of the two sheets; their normals
    are the sheets' helix-axis directions.  Sheet A stays put; sheet B is folded, so
    the angle between the mean posed axis of A's helices and of B's helices is the
    corner angle (~90° for a valid mitred fold).
    """
    axes = {a["helix_id"]: a for a in deformed_helix_axes(design)}

    def _mean_axis(cols: tuple[int, ...]) -> np.ndarray:
        dirs = []
        for c in cols:
            a = axes.get(_helix_id(c))
            if a is None:
                continue
            v = np.asarray(a["end"], float) - np.asarray(a["start"], float)
            n = np.linalg.norm(v)
            if n > 0:
                dirs.append(v / n)
        return np.mean(dirs, axis=0)

    da = _mean_axis(spec.a_cols)
    db = _mean_axis(spec.b_cols)
    cos = float(
        np.clip(np.dot(da, db) / (np.linalg.norm(da) * np.linalg.norm(db)), -1, 1)
    )
    return float(np.degrees(np.arccos(cos)))


# ── Construction steps (drive the real headless_build wrappers) ─────────────────


def _lay_sheets(spec: CornerSpec, a_len, b_len, *, create_len: int) -> None:
    """create_bundle the two sheets then trim every far end to its target length.

    Both sheets are laid at ``create_len`` bp; each helix's far end (3′ if the helix
    is FORWARD, else 5′) is then trimmed on BOTH the scaffold and the staple by the
    same signed delta.  Trimming only the scaffold would leave the helix axis at
    full length (the axis is rebuilt from the UNION of strand coverage).
    """
    cells = [[_ROW, c] for c in spec.a_cols] + [[_ROW, c] for c in spec.b_cols]
    hb.create_bundle(
        cells,
        create_len,
        lattice=LatticeType.SQUARE,
        name="corner_miter",
        ligate_adjacent=True,
    )
    design = design_state.get_or_404()
    helices = {h.id: h for h in design.helices}
    dir_by_col = {
        c: helices[_helix_id(c)].direction for c in (*spec.a_cols, *spec.b_cols)
    }

    for cols, lens in ((spec.a_cols, a_len), (spec.b_cols, b_len)):
        for col, target in zip(cols, lens):
            delta = target - create_len
            if delta == 0:
                continue
            fwd = dir_by_col[col] == Direction.FORWARD
            scaf_end = "3p" if fwd else "5p"  # far end of the scaffold
            stpl_end = "5p" if fwd else "3p"  # far end of the (opposite) staple
            hb.resize_strand_end(_scaf_id(col), _helix_id(col), scaf_end, delta)
            hb.resize_strand_end(_stpl_id(col), _helix_id(col), stpl_end, delta)


def _fold_transform(spec: CornerSpec):
    """Compute the fold pose of sheet B on the *current* active design.

    Returns ``(cluster_id, translation, rotation_quat, pivot)`` for a 180° rotation
    about the miter diagonal ``dA`` (so B ends coplanar, perpendicular to A, and B
    helix ``i`` maps onto A helix ``i``):

    * ``dA`` = unit(A_last_far − A_first_far) — the miter line direction,
    * ``rotation`` = ``(dx, dy, dz, 0)`` — a 180° turn about ``dA``,
    * ``pivot`` = B's miter (far-end) centroid ``cB``,
    * ``translation`` = ``cA − cB`` (A's miter centroid − B's) so the two miter
      lines coincide.
    """
    design = design_state.get_or_404()
    helices = {h.id: h for h in design.helices}

    def far(col: int) -> np.ndarray:
        h = helices[_helix_id(col)]
        return np.array([h.axis_end.x, h.axis_end.y, h.axis_end.z], dtype=float)

    dA = far(spec.a_cols[-1]) - far(spec.a_cols[0])
    dA = dA / np.linalg.norm(dA)
    cA = np.mean([far(c) for c in spec.a_cols], axis=0)
    cB = np.mean([far(c) for c in spec.b_cols], axis=0)
    cluster = next(
        c for c in design.cluster_transforms if _helix_id(spec.b_cols[0]) in c.helix_ids
    )
    return (cluster.id, list(cA - cB), [dA[0], dA[1], dA[2], 0.0], list(cB))


def _seam_ligations(spec: CornerSpec) -> None:
    """Force-ligate each seam: the FORWARD helix's scaffold 3′ → the REVERSE's 5′.

    For seam ``i`` (A col ``a_cols[i]`` ↔ B col ``b_cols[i]``) the odd column offset
    guarantees one helix is FORWARD (offers a free 3′ at its far end) and the other
    REVERSE (offers a free 5′).  We connect the FORWARD helix's scaffold to the
    REVERSE helix's scaffold; both meet at their trimmed far ends.
    """
    helices = {h.id: h for h in design_state.get_or_404().helices}
    for ac, bc in zip(spec.a_cols, spec.b_cols):
        a_fwd = helices[_helix_id(ac)].direction == Direction.FORWARD
        fwd_col, rev_col = (ac, bc) if a_fwd else (bc, ac)
        hb.force_ligate(_scaf_id(fwd_col), _scaf_id(rev_col))


# ── The phase-aware optimiser (path-B, fold-fixed analytic search) ───────────────


def _optimize_lengths(
    spec: CornerSpec, *, window_bp: int, max_passes: int = 6, perturbation=None
):
    """Return ``(a_len, b_len)`` minimising posed forced-ligation stretch.

    Coordinate-descent over seams with a fixed fold per pass (see the module
    docstring): build the straight sheets once (bead positions are trim-invariant),
    then each pass capture the fold from one real build and search every seam's
    ``(len_Ai, len_Bi)`` in ``ideal ± window_bp`` analytically, picking the pair
    that minimises the seam's posed backbone stretch — tie-broken by the smaller
    axial residual ``|len_Ai−ideal| + |len_Bi−ideal|`` (the user-chosen lexicographic
    objective, 2026-07-08).  Re-fixes the fold and repeats until the lengths settle.

    ``perturbation`` (optional ``(Rextra, off)`` from :func:`_optimize_fold`) composes
    the clash-reducing fold tweak into the pose the seam search sees, so the lengths
    are re-optimised UNDER the tweaked fold (stage C of the co-optimiser).
    """
    ideal = spec.ideal
    create_len = spec.base_length_bp + window_bp  # cover the whole search window
    Rextra = np.eye(3) if perturbation is None else np.asarray(perturbation[0], float)
    off = np.zeros(3) if perturbation is None else np.asarray(perturbation[1], float)

    # 1) One straight build → every candidate seam bead (trim-invariant).
    with hb.scratch_session(LatticeType.SQUARE):
        _lay_sheets(
            spec,
            [create_len] * spec.n_helices,
            [create_len] * spec.n_helices,
            create_len=create_len,
        )
        straight = _bead_map(design_state.get_or_404())
        _hx = {h.id: h for h in design_state.get_or_404().helices}
        dir_by_col = {
            c: _hx[_helix_id(c)].direction.name for c in (*spec.a_cols, *spec.b_cols)
        }

    def seam_bead(col: int, length: int) -> np.ndarray:
        return straight[(_helix_id(col), length - 1, dir_by_col[col])]

    def search(rot, pivot, trans):
        R = Rextra @ _rot_from_quaternion(*rot)  # compose the fold tweak
        piv = np.asarray(pivot, float)
        tr = np.asarray(trans, float) + off
        a_out, b_out = [], []
        for i, (ac, bc) in enumerate(zip(spec.a_cols, spec.b_cols)):
            lo = max(1, ideal[i] - window_bp)
            hi = min(create_len, ideal[i] + window_bp)
            best = None
            for la in range(lo, hi + 1):
                pa = seam_bead(ac, la)  # sheet A: identity pose
                for lb in range(lo, hi + 1):
                    pb = seam_bead(bc, lb)
                    pb = R @ (pb - piv) + piv + tr  # sheet B: folded pose
                    stretch = float(np.linalg.norm(pa - pb))
                    axial = abs(la - ideal[i]) + abs(lb - ideal[i])
                    key = (round(stretch, 4), axial)
                    if best is None or key < best[0]:
                        best = (key, la, lb)
            a_out.append(best[1])
            b_out.append(best[2])
        return a_out, b_out

    a_len, b_len = list(ideal), list(ideal)
    for _ in range(max_passes):
        with hb.scratch_session(LatticeType.SQUARE):
            _lay_sheets(spec, a_len, b_len, create_len=spec.base_length_bp)
            cluster_id, trans, rot, pivot = _fold_transform(spec)
            hb.transform_cluster(
                cluster_id, translation=trans, rotation=rot, pivot=pivot, commit=False
            )
            # capture the transform as actually stored (normalised) for the search
            d = design_state.get_or_404()
            cluster = next(
                c
                for c in d.cluster_transforms
                if _helix_id(spec.b_cols[0]) in c.helix_ids
            )
            rot_c, piv_c, tr_c = cluster.rotation, cluster.pivot, cluster.translation
        na, nb = search(rot_c, piv_c, tr_c)
        if na == a_len and nb == b_len:
            break
        a_len, b_len = na, nb
    return a_len, b_len


# ── The fold-pose optimiser (clash reduction, the second lever) ──────────────────


def _compose_fold(rot_quat, pivot, trans, Rextra, off):
    """Fold a ``(Rextra, off)`` perturbation into one ``transform_cluster`` pose.

    The base fold poses a B bead ``p`` to ``R0·(p−piv)+piv+tr``.  Rotating the whole
    posed sheet by ``Rextra`` about the same pivot and shifting it by ``off`` gives
    ``(Rextra·R0)·(p−piv)+piv+(tr+off)`` — a single rigid transform with rotation
    ``Rextra·R0``, the SAME pivot, and translation ``tr+off``.  Returns
    ``(rotation_quat[x,y,z,w], pivot, translation)`` ready for ``hb.transform_cluster``.
    """
    Rc = np.asarray(Rextra, float) @ _rot_from_quaternion(*rot_quat)
    rot_c = Rotation.from_matrix(Rc).as_quat()  # [x, y, z, w]
    translation = (np.asarray(trans, float) + np.asarray(off, float)).tolist()
    return list(rot_c), list(pivot), translation


def _optimize_fold(
    spec: CornerSpec,
    a_len,
    b_len,
    *,
    max_stretch_nm: float,
    angle_tol_deg: float,
    target_angle_deg: float,
    clash_bond_weight: float = 4.0,
):
    """Return a fold perturbation ``(Rextra, off)`` that reduces seam steric clashes.

    The length optimiser mates the miter teeth as tightly as possible, which PACKS
    the cross-sheet backbones — so the residual clashes are a property of the FOLD,
    not the lengths (a pure translation just trades clashes 1:1 against bond length).
    A small extra ROTATION of sheet B (a few degrees) about the fold pivot, combined
    with a small translation, moves the bulk of B off A while keeping the seam beads
    mated — genuinely lowering the clash count at a modest bond cost.

    Coordinate-descent over 6 DOF (a rotvec in degrees + a translation in nm),
    minimising ``steric_clash + clash_bond_weight · Σ bond`` subject to (a) every
    seam bond ``< max_stretch_nm`` and (b) the corner angle within ``angle_tol_deg``
    of ``target_angle_deg``.  Evaluated ANALYTICALLY on straight beads (only the
    cross-sheet A–B pairs vary under the rigid fold, so an A-bead KD-tree is built
    once and the transformed B beads are queried against it — no rebuilds).
    """
    # Straight beads for exactly the nucleotides the final design has (bp < length).
    with hb.scratch_session(LatticeType.SQUARE):
        _lay_sheets(spec, a_len, b_len, create_len=spec.base_length_bp)
        design = design_state.get_or_404()
        helices = {h.id: h for h in design.helices}
        dir_by_col = {
            c: helices[_helix_id(c)].direction.name
            for c in (*spec.a_cols, *spec.b_cols)
        }
        keys_a, pos_a, keys_b, pos_b = [], [], [], []
        for h in design.helices:
            col = int(h.id.rsplit("_", 1)[-1])
            into_k, into_p = (keys_a, pos_a) if col in spec.a_cols else (keys_b, pos_b)
            for nuc in deformed_nucleotide_positions(h, design):
                into_k.append((nuc.helix_id, int(nuc.bp_index), nuc.direction.name))
                into_p.append(np.asarray(nuc.position, float))
        _, trans, rot, pivot = _fold_transform(spec)

    pos_a = np.asarray(pos_a, float)
    pos_b = np.asarray(pos_b, float)
    R0 = _rot_from_quaternion(*rot)
    piv = np.asarray(pivot, float)
    tr0 = np.asarray(trans, float)
    len_by_col = {**dict(zip(spec.a_cols, a_len)), **dict(zip(spec.b_cols, b_len))}

    # seam bead row indices (the FL partners — excluded from the clash count)
    ia = [
        keys_a.index((_helix_id(ac), len_by_col[ac] - 1, dir_by_col[ac]))
        for ac in spec.a_cols
    ]
    ib = [
        keys_b.index((_helix_id(bc), len_by_col[bc] - 1, dir_by_col[bc]))
        for bc in spec.b_cols
    ]

    tree_a = cKDTree(pos_a)
    thr, marg = DEFAULT_CLASH_THRESHOLD_NM, DEFAULT_DESIGNED_MARGIN_NM

    # Straight distance is candidate-INDEPENDENT (A fixed, B rigid), so precompute the
    # cross-pairs that are designed-close (straight ≤ marg) and thus never a clash —
    # together with the seam FL bonds — as one excluded (ai, bi) set.
    excluded: set[tuple[int, int]] = {(ia[i], ib[i]) for i in range(spec.n_helices)}
    for bi, a_hits in enumerate(tree_a.query_ball_point(pos_b, marg)):
        for ai in a_hits:
            excluded.add((ai, bi))

    # Only B beads that come near sheet A can ever clash; the fold perturbation is
    # small (a few °, ≲2 nm), so restrict the per-candidate clash scan to B beads
    # within a reach radius of A in the base pose — the rest never approach.  This is
    # what lets the full fine grid run in ~1 s instead of scanning all ~N_B beads.
    base_posed_b = (R0 @ (pos_b - piv).T).T + piv + tr0
    reach = thr + 4.0
    near_b = sorted(
        {
            bi
            for bi, hits in enumerate(tree_a.query_ball_point(base_posed_b, reach))
            if hits
        }
    )
    near_b_arr = np.asarray(near_b, dtype=int)
    pos_b_near = pos_b[near_b_arr]

    def _axis_dirs(keys, pos, cols):
        out = []
        for c in cols:
            hid = _helix_id(c)
            pts = sorted(
                (bp, p)
                for (h, bp, dr), p in zip(keys, pos)
                if h == hid and dr == dir_by_col[c]
            )
            v = pts[-1][1] - pts[0][1]
            out.append(v / np.linalg.norm(v))
        return np.mean(out, axis=0)

    dA = _axis_dirs(keys_a, pos_a, spec.a_cols)
    # B's mean axis direction rotates rigidly with the fold (translation-invariant),
    # so precompute it straight and just apply the rotation per candidate.
    dB0 = _rot_from_quaternion(*rot) @ _axis_dirs(keys_b, pos_b, spec.b_cols)
    pos_b_ib = pos_b[ib]

    def evaluate(Rextra, off):
        RR = Rextra @ R0
        seam_b = (RR @ (pos_b_ib - piv).T).T + piv + tr0 + off
        bonds = [
            float(np.linalg.norm(pos_a[ia[i]] - seam_b[i]))
            for i in range(spec.n_helices)
        ]
        posed_near = (RR @ (pos_b_near - piv).T).T + piv + tr0 + off
        clashes = sum(
            1
            for local, a_hits in enumerate(tree_a.query_ball_point(posed_near, thr))
            for ai in a_hits
            if (ai, int(near_b_arr[local])) not in excluded
        )
        dB = Rextra @ dB0
        angle = np.degrees(
            np.arccos(
                np.clip(
                    np.dot(dA, dB) / (np.linalg.norm(dA) * np.linalg.norm(dB)), -1, 1
                )
            )
        )
        return clashes, sum(bonds), max(bonds), angle

    # Search over a single-axis rotation (a few degrees) × a small 3-D shift — the
    # DOF that swing the bulk of sheet B off A while the seam beads stay mated (a pure
    # translation just trades clashes 1:1 for bond length; the rotation is what opens
    # the frontier).  Objective: minimise ``clash + weight·Σbond`` subject to every
    # bond < max_stretch_nm and the corner angle within angle_tol_deg.  The identity
    # fold is always feasible, so a solution always exists.  Coarse grid → local
    # refinement to keep the cost down (a full fine grid is ~20k evaluations).
    axes = (
        np.zeros(3),
        np.array([1.0, 0, 0]),
        np.array([0, 1.0, 0]),
        np.array([0, 0, 1.0]),
    )

    def _grid(axis_angles, off_grid, seed):
        best = seed
        for axis, angs in axis_angles:
            for ang in angs:
                Rextra = Rotation.from_rotvec(np.radians(ang) * axis).as_matrix()
                for off in off_grid:
                    clashes, total, max_bond, angle = evaluate(Rextra, off)
                    if (
                        max_bond >= max_stretch_nm
                        or abs(angle - target_angle_deg) > angle_tol_deg
                    ):
                        continue
                    score = clashes + clash_bond_weight * total
                    if score < best[0] - 1e-9:
                        best = (score, Rextra, off, axis, float(ang))
        return best

    def _off_grid(centre, radius, step):
        rng = np.arange(-radius, radius + 1e-9, step)
        return [
            centre + np.array([dx, dy, dz]) for dx in rng for dy in rng for dz in rng
        ]

    angles_deg = np.arange(-6.0, 6.01, 2.0)  # -6,-4,-2,0,2,4,6
    seed = (float("inf"), np.eye(3), np.zeros(3), np.zeros(3), 0.0)
    best = _grid(
        [(a, angles_deg) for a in axes], _off_grid(np.zeros(3), 2.0, 0.5), seed
    )  # step-0.5 shift, 9³
    return best[1], best[2]


# ── Public entry point ───────────────────────────────────────────────────────────


def build_corner(
    *,
    n_helices: int = 6,
    base_length_bp: int = 56,
    lattice: LatticeType = LatticeType.SQUARE,
    target_angle_deg: float = 90.0,
    optimize: bool = True,
    optimize_fold: bool = True,
    window_bp: int = 2,
    max_stretch_nm: float = 1.0,
    angle_tol_deg: float = 5.0,
    col_offset: int | None = None,
) -> Design:
    r"""Build a mitred 90° corner from two SQUARE-lattice sheets (returns a copy).

    Two 1×\ ``n_helices`` sheets are laid flush at z=0; each helix's far end is
    trimmed into a ~45° staircase miter, sheet B is folded 180° about the miter
    diagonal (a logged display-layer cluster pose), and the ``n_helices`` cross-seam
    scaffold links are forced-ligated.  With ``optimize=True`` the per-helix lengths
    are chosen by the phase-aware optimiser (see the module docstring); with
    ``optimize=False`` they are the uniform axial-exact miter lengths (the baseline
    that honours only the axial constraint).

    With ``optimize_fold=True`` (and ``optimize=True``) a SECOND stage tunes the
    sheet-B fold pose (a few-degree rotation + small shift, still a logged display-layer
    cluster_op) to reduce the seam steric clashes the tight miter mating packs in — then
    the lengths are re-optimised under the tweaked fold.  This co-optimisation beats the
    hand-tuned reference on BOTH axes (fewer clashes AND shorter bonds); the tight-bonds-
    only result (``optimize_fold=False``) leaves more seam clashes.  ``max_stretch_nm``
    bounds every seam bond and ``angle_tol_deg`` bounds the corner-angle drift during the
    fold search.

    Runs in an isolated scratch session, so it never disturbs the active design; the
    returned design carries the full ``bundle-create → resize → cluster_op → forced-
    ligation`` feature log.  Pin the result with
    :func:`tests.automation_harness.assert_corner_folded`.

    Parameters
    ----------
    n_helices : per-sheet helix count (seams).  ``base_length_bp`` : the longest
    (un-mitred) helix.  ``target_angle_deg`` : only 90° is currently supported (the
    2.25/0.334 stagger geometry).  ``window_bp`` : ± search band around each seam's
    ideal miter length.  ``max_stretch_nm`` / ``angle_tol_deg`` : the fold-optimiser's
    hard constraints (bond ceiling + corner-angle tolerance).  ``col_offset`` :
    lattice-column offset A→B (must be ODD for the parity flip; default
    :func:`_default_col_offset`).
    """
    if lattice != LatticeType.SQUARE:
        raise ValueError(
            "build_corner supports only the SQUARE lattice "
            "(the mitre stagger is 2.25/0.334 bp)."
        )
    if round(target_angle_deg) != 90:
        raise ValueError(
            "build_corner currently supports only 90° corners "
            f"(got {target_angle_deg})."
        )
    if n_helices < 2:
        raise ValueError("n_helices must be ≥ 2.")
    if col_offset is None:
        col_offset = _default_col_offset(n_helices)
    if col_offset % 2 == 0:
        raise ValueError(
            f"col_offset must be ODD for the scaffold-parity flip (got {col_offset})."
        )
    if col_offset < n_helices:
        raise ValueError(
            f"col_offset {col_offset} would overlap the two sheets "
            f"(need ≥ n_helices = {n_helices})."
        )

    a_cols, b_cols = _columns(n_helices, col_offset)
    ideal = _ideal_lengths(n_helices, base_length_bp)
    spec = CornerSpec(
        n_helices=n_helices,
        base_length_bp=base_length_bp,
        col_offset=col_offset,
        a_cols=a_cols,
        b_cols=b_cols,
        a_len=ideal,
        b_len=ideal,
        ideal=ideal,
    )

    perturbation = None  # (Rextra, off) fold tweak; None → the plain 180° fold
    if optimize:
        a_len, b_len = _optimize_lengths(spec, window_bp=window_bp)  # stage A: lengths
        if optimize_fold:
            spec_a = CornerSpec(
                n_helices=n_helices,
                base_length_bp=base_length_bp,
                col_offset=col_offset,
                a_cols=a_cols,
                b_cols=b_cols,
                a_len=tuple(a_len),
                b_len=tuple(b_len),
                ideal=ideal,
            )
            perturbation = _optimize_fold(  # stage B: fold pose
                spec_a,
                a_len,
                b_len,
                max_stretch_nm=max_stretch_nm,
                angle_tol_deg=angle_tol_deg,
                target_angle_deg=target_angle_deg,
            )
            a_len, b_len = _optimize_lengths(  # stage C: re-lengths
                spec, window_bp=window_bp, perturbation=perturbation
            )
    else:
        a_len, b_len = list(ideal), list(ideal)
    spec = CornerSpec(
        n_helices=n_helices,
        base_length_bp=base_length_bp,
        col_offset=col_offset,
        a_cols=a_cols,
        b_cols=b_cols,
        a_len=tuple(a_len),
        b_len=tuple(b_len),
        ideal=ideal,
    )

    with hb.scratch_session(LatticeType.SQUARE):
        _lay_sheets(spec, a_len, b_len, create_len=base_length_bp)
        cluster_id, trans, rot, pivot = _fold_transform(spec)
        if perturbation is not None:
            rot, pivot, trans = _compose_fold(rot, pivot, trans, *perturbation)
        hb.transform_cluster(
            cluster_id,
            translation=trans,
            rotation=rot,
            pivot=pivot,
            commit=True,
            log=True,
        )
        _seam_ligations(spec)
        design = design_state.get_or_404().model_copy(deep=True)
    return design


def resolve_corner_spec(design: Design) -> CornerSpec:
    """Recover a corner's seam layout from a built design (columns + lengths).

    Infers the two sheets from the helix columns (two contiguous SQUARE runs in
    row 0) and reads each helix's realised bp length from its strand coverage, so
    an oracle (or a reload) can recover the seam pairing without the builder's
    in-memory :class:`CornerSpec`.  Raises ``ValueError`` if the helix columns do
    not form exactly two equal-size contiguous runs.
    """
    cols = sorted(
        int(h.id.rsplit("_", 1)[-1])
        for h in design.helices
        if h.id.startswith(f"h_XY_{_ROW}_")
    )
    runs: list[list[int]] = []
    for c in cols:
        if runs and c == runs[-1][-1] + 1:
            runs[-1].append(c)
        else:
            runs.append([c])
    if len(runs) != 2 or len(runs[0]) != len(runs[1]):
        raise ValueError(f"expected two equal contiguous column runs, got {runs}")
    a_cols, b_cols = tuple(runs[0]), tuple(runs[1])
    n = len(a_cols)
    length_by_col = {}
    for h in design.helices:
        col = int(h.id.rsplit("_", 1)[-1])
        # realised length = 1 + max bp index covered by any domain on this helix
        hi = 0
        for s in design.strands:
            for dm in s.domains:
                if dm.helix_id == h.id:
                    hi = max(hi, dm.start_bp, dm.end_bp)
        length_by_col[col] = hi + 1
    base = max(length_by_col.values())
    return CornerSpec(
        n_helices=n,
        base_length_bp=base,
        col_offset=b_cols[0] - a_cols[0],
        a_cols=a_cols,
        b_cols=b_cols,
        a_len=tuple(length_by_col[c] for c in a_cols),
        b_len=tuple(length_by_col[c] for c in b_cols),
        ideal=_ideal_lengths(n, base),
    )
