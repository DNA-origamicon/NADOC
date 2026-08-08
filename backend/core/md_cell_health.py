"""Periodic-cell diagnostics: is the box the right size, and did it settle?

Two failures motivated this module, both measured on the 2hb_1xT 200 ns run
(``experiments/exp47_protocol_delta/RESULTS.md``):

1. **The cell collapsed.** A water-shell carve leaves the box ~37 % vacuum; under a
   barostat NAMD expels exactly that vacuum, shrinking the cell 38 % by volume and
   crashing at ``Periodic cell has become too small for original patch grid!`` on the way
   (the crash sits at ~67 % of the starting volume, the water's equilibrium volume at
   61.8 %, so the crash is unavoidable rather than unlucky).  The Aksimentiev protocol
   treats the box trace as its primary equilibration diagnostic — *"the box should shrink
   in the first 300 ps; after that the box size should become stable"* — which is exactly
   the check that was missing.  :func:`settle_report` is that check.

2. **The box was too small for the solute in the first place.**  Padding is applied to the
   structure's bounding box in its *build* orientation, but an unrestrained solute rotates
   and (for a floppy construct) sprawls: the 2hb reached per-axis extents of
   59.7 x 70.3 x 107.0 A inside a 37.6 x 56.8 x 96.8 A cell, i.e. it exceeded the cell on
   every axis and sat within 3-9 A of its own periodic image for most of the run.
   :func:`solute_envelope` + :func:`box_from_envelope` size the box from the envelope the
   solute actually explores instead of the one frame it was built in.

Everything here is pure and unit-testable; nothing reads NADOC state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

# The tutorial's own criterion: a correctly filled box settles inside ~300 ps and then
# holds.  A cell still marching after that has the wrong amount of water in it.
DEFAULT_SETTLE_PS = 300.0
# A correctly filled box moves by a few percent OF CELL LENGTH — the quantity the
# tutorial plots.  Measured on 2hb_1xT: full water box 2.5 % linear (7.4 % by volume,
# legitimate); water-shell carve 14.8 % linear (38 % by volume, a collapse).  The gate is
# on the linear figure so the threshold means what the protocol says it means.
DEFAULT_MAX_LINEAR_DRIFT_FRAC = 0.03
# Once settled, the volume should stay inside this band of its final value.
DEFAULT_FLAT_TOL_FRAC = 0.01
# Below this fraction of the starting VOLUME the cell is not equilibrating, it is
# collapsing: the box was built with vacuum in it and the run is no longer the one that
# was configured.  Used to decide that an auto-resume would be papering over a defect.
# Sits between the measured legitimate trim (0.926) and the volume at which the carved
# run first crashed (0.67).
COLLAPSE_VOLUME_FRAC = 0.85
# Solute-to-own-periodic-image clearance.  Below 2x the nonbonded cutoff the solute
# interacts with its own image directly; NAMD's default cutoff here is 12 A.
MIN_IMAGE_CLEARANCE_ANG = 24.0
# Slack when judging "is the padding honoured" — extents are measured, not exact.
_PAD_SLACK_ANG = 0.1


# ── the box trace ─────────────────────────────────────────────────────────────
def parse_xst(text: str) -> np.ndarray:
    """NAMD ``.xst`` text → ``(n, 4)`` array of ``(step, a_x, b_y, c_z)``.

    Only the diagonal cell lengths are kept — every NADOC package uses an orthorhombic
    cell (``useFlexibleCell no``).  Comment lines and torn trailing lines are dropped, so
    this is safe on a file NAMD is still writing.
    """
    rows: list[tuple[float, float, float, float]] = []
    for line in text.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        t = line.split()
        if len(t) < 10:
            continue
        try:
            rows.append((float(t[0]), float(t[1]), float(t[5]), float(t[9])))
        except ValueError:
            continue
    return np.asarray(rows, dtype=float).reshape(-1, 4)


def read_xst(path: "str | Path") -> np.ndarray:
    """:func:`parse_xst` on a file; empty array when the file is absent."""
    p = Path(path)
    if not p.exists():
        return np.zeros((0, 4))
    return parse_xst(p.read_text(errors="replace"))


def volumes(rows: np.ndarray) -> np.ndarray:
    """Cell volume (Å³) per row of :func:`read_xst` output."""
    if rows.size == 0:
        return np.zeros(0)
    return rows[:, 1] * rows[:, 2] * rows[:, 3]


def volume_fraction(rows: np.ndarray) -> float:
    """Final cell volume as a fraction of the first row's.  1.0 = unchanged."""
    v = volumes(rows)
    if v.size == 0 or v[0] <= 0:
        return float("nan")
    return float(v[-1] / v[0])


def settle_report(
    rows: np.ndarray,
    timestep_fs: float,
    *,
    settle_ps: float = DEFAULT_SETTLE_PS,
    max_linear_drift_frac: float = DEFAULT_MAX_LINEAR_DRIFT_FRAC,
    flat_tol_frac: float = DEFAULT_FLAT_TOL_FRAC,
) -> dict:
    """Did the periodic cell settle, per the Aksimentiev box-trace criterion?

    ``ok`` requires BOTH that the cell LENGTH moved by less than
    ``max_linear_drift_frac`` (a correctly filled box only needs a few percent) AND that
    the trace was flat to within ``flat_tol_frac`` of its final value from ``settle_ps``
    onward.

    A short trace that has not yet reached ``settle_ps`` returns ``ok=None`` — undecided,
    not passed.
    """
    v = volumes(rows)
    if v.size < 2:
        return {
            "ok": None,
            "reason": "not enough box samples",
            "n_samples": int(v.size),
        }

    ps = rows[:, 0] * timestep_fs / 1000.0
    ps = ps - ps[0]
    drift = float(v[-1] / v[0] - 1.0)
    linear_drift = float((v[-1] / v[0]) ** (1.0 / 3.0) - 1.0)

    settled_from_ps: float | None = None
    flat = None
    if ps[-1] >= settle_ps:
        # Compare BLOCK MEANS, not instantaneous samples, against the final quarter's
        # mean.  A cell's volume fluctuates thermally by sigma/V ~ sqrt(kT*kappa/V) —
        # ~0.24 % for a 33k-atom box — so a raw-sample band flags a perfectly settled
        # run on a 4-sigma excursion.  Measured: a 2 ns arm with 0.43 % total drift,
        # 100 % base pairs intact and -0.19 % energy drift was scored "not settled" by
        # the raw-sample form.  Block means kill that false positive while a genuine
        # march still moves every block.
        ref = float(v[max(1, int(0.75 * len(v))) :].mean())
        tail = ps >= settle_ps
        blocks = [b for b in np.array_split(v[tail], 4) if b.size]
        flat = bool(max(abs(b.mean() / ref - 1.0) for b in blocks) <= flat_tol_frac)
        # earliest sample from which every later BLOCK sits inside the band
        for i in range(len(v)):
            rest = v[i:]
            if rest.size < 4:
                break
            if (
                max(
                    abs(b.mean() / ref - 1.0) for b in np.array_split(rest, 4) if b.size
                )
                <= flat_tol_frac
            ):
                settled_from_ps = float(ps[i])
                break

    ok: bool | None
    reasons: list[str] = []
    if abs(linear_drift) > max_linear_drift_frac:
        reasons.append(
            f"cell length moved {linear_drift * 100:+.1f}% "
            f"({drift * 100:+.1f}% by volume; limit "
            f"+/-{max_linear_drift_frac * 100:.0f}% linear) — the box does not contain "
            "the right amount of water"
        )
    if flat is False:
        reasons.append(f"cell was still moving after {settle_ps:.0f} ps")
    if flat is None:
        ok = None
        reasons.append(
            f"trace is only {ps[-1]:.0f} ps, needs {settle_ps:.0f} ps to judge"
        )
    else:
        ok = not reasons

    return {
        "ok": ok,
        "reason": "; ".join(reasons) if reasons else "cell settled",
        "n_samples": int(v.size),
        "span_ps": float(ps[-1]),
        "volume_start_ang3": float(v[0]),
        "volume_end_ang3": float(v[-1]),
        "drift_frac": drift,
        "linear_drift_frac": linear_drift,
        "settled_from_ps": settled_from_ps,
        "flat_after_settle": flat,
        "cell_start_ang": [float(x) for x in rows[0, 1:]],
        "cell_end_ang": [float(x) for x in rows[-1, 1:]],
    }


def is_collapsing(rows: np.ndarray, *, floor: float = COLLAPSE_VOLUME_FRAC) -> bool:
    """True when the cell has shrunk past ``floor`` of its starting volume.

    This is the discriminator between "NPT trimmed a correctly filled box" (a few
    percent, benign, a patch-grid restart is legitimate) and "the box was built with
    vacuum in it" (tens of percent, and resuming just walks further into a cell that is
    too small for the solute).
    """
    f = volume_fraction(rows)
    return bool(np.isfinite(f) and f < floor)


# ── the solute envelope ───────────────────────────────────────────────────────
def solute_envelope(frames: Iterable[np.ndarray]) -> dict:
    """Size statistics of a solute over an ensemble of coordinate frames (Å).

    ``frames`` is any iterable of ``(n_atoms, 3)`` arrays — one frame is fine (it then
    describes the build pose only, which is exactly the assumption that fails).

    Returns per-axis extents and the radius from the centroid, at p50/p95/max.  The
    radius is the orientation-invariant number: a solute free to rotate needs a box that
    fits ``2 * r_max`` on every axis, not its extent in the pose it was built in.
    """
    ext: list[np.ndarray] = []
    rad: list[float] = []
    n = 0
    for xyz in frames:
        a = np.asarray(xyz, dtype=float)
        if a.ndim != 2 or a.shape[1] != 3 or a.shape[0] == 0:
            raise ValueError("each frame must be a non-empty (n_atoms, 3) array")
        ext.append(a.max(axis=0) - a.min(axis=0))
        rad.append(float(np.linalg.norm(a - a.mean(axis=0), axis=1).max()))
        n += 1
    if not n:
        raise ValueError("no frames given")
    E = np.asarray(ext)
    R = np.asarray(rad)
    pick = lambda arr, q: (
        np.percentile(arr, q, axis=0)  # noqa: E731
        if arr.shape[0] > 1
        else arr[0]
    )
    return {
        "n_frames": n,
        "extent_ang": {
            "p50": [float(x) for x in np.atleast_1d(pick(E, 50))],
            "p95": [float(x) for x in np.atleast_1d(pick(E, 95))],
            "max": [float(x) for x in E.max(axis=0)],
        },
        "radius_ang": {
            "p50": float(np.percentile(R, 50)),
            "p95": float(np.percentile(R, 95)),
            "max": float(R.max()),
        },
    }


def box_from_envelope(
    envelope: dict,
    padding_nm: float,
    *,
    mode: str = "rotation",
    percentile: str = "p95",
) -> tuple[float, float, float]:
    """Box dimensions (nm) that keep ``2 x padding`` of solvent around the solute.

    ``mode``:

    * ``"bbox"``      — per-axis extent + 2·padding.  Today's rule.  Correct only while
      the solute keeps the orientation it was built in.
    * ``"rotation"``  — a cubic cell of ``2·r_max + 2·padding``.  Orientation-proof: no
      rotation of the solute can bring it closer than ``padding`` to a face.
    * ``"axis"``      — per-axis extent + 2·padding, but taken over the supplied ensemble
      rather than one frame.  The middle option: it covers the motion the ensemble
      actually showed without paying for orientations it never visited.

    ``percentile`` selects which envelope statistic to size against (``p50``/``p95``/``max``).
    """
    pad_a = padding_nm * 10.0
    if percentile not in ("p50", "p95", "max"):
        raise ValueError(f"unknown percentile {percentile!r}")
    if mode == "rotation":
        side = 2.0 * envelope["radius_ang"][percentile] + 2.0 * pad_a
        return (side / 10.0,) * 3
    if mode in ("bbox", "axis"):
        ext = envelope["extent_ang"][percentile]
        return tuple(float(e + 2.0 * pad_a) / 10.0 for e in ext)  # type: ignore[return-value]
    raise ValueError(f"unknown box mode {mode!r}")


def box_adequacy(
    box_nm: Sequence[float],
    envelope: dict,
    *,
    padding_nm: float,
    percentile: str = "p95",
) -> dict:
    """Is this cell big enough for the solute — in the pose it was built in, and after it
    turns?

    Two verdicts:

    * ``fits_as_built`` — the padding survives in the build orientation.  This is what
      today's sizing rule guarantees, and it is all it guarantees.
    * ``fits_rotated``  — the padding survives ANY rotation, i.e. the smallest box axis
      still clears ``2·r_max``.  An unrestrained solute rotates, so this is the one that
      matters for a free run.

    ``clearance_*_ang`` is the solute-to-face gap; twice it is the solute-to-image gap,
    which is what has to stay above :data:`MIN_IMAGE_CLEARANCE_ANG`.
    """
    box_a = np.asarray(box_nm, dtype=float) * 10.0
    ext = np.asarray(envelope["extent_ang"][percentile], dtype=float)
    r = float(envelope["radius_ang"][percentile])
    pad_a = padding_nm * 10.0

    clear_built = (box_a - ext) / 2.0
    clear_rot = (box_a - 2.0 * r) / 2.0
    return {
        "box_ang": [float(x) for x in box_a],
        "extent_ang": [float(x) for x in ext],
        "radius_ang": r,
        "clearance_as_built_ang": [float(x) for x in clear_built],
        "clearance_rotated_ang": [float(x) for x in clear_rot],
        "image_gap_as_built_ang": float(2.0 * clear_built.min()),
        "image_gap_rotated_ang": float(2.0 * clear_rot.min()),
        # absolute slack, not relative: the caller's extents are measured numbers, and
        # a hair under the nominal padding is not a defect
        "fits_as_built": bool(clear_built.min() >= pad_a - _PAD_SLACK_ANG),
        "fits_rotated": bool(clear_rot.min() >= pad_a - _PAD_SLACK_ANG),
        "image_clearance_ok": bool(2.0 * clear_rot.min() >= MIN_IMAGE_CLEARANCE_ANG),
        "percentile": percentile,
    }


def min_image_distance(positions: np.ndarray, box_ang: Sequence[float]) -> float:
    """Smallest distance (Å) between the solute and any of its 26 periodic images.

    ``positions`` must be a single, UNWRAPPED image of the solute — a wrapped frame
    gives a meaningless answer.  Below ``MIN_IMAGE_CLEARANCE_ANG`` the solute is
    interacting with itself through the boundary.
    """
    from scipy.spatial import cKDTree  # noqa: PLC0415 — optional at import time

    X = np.asarray(positions, dtype=float)
    box = np.asarray(box_ang, dtype=float)
    tree = cKDTree(X)
    best = np.inf
    for sx in (-1, 0, 1):
        for sy in (-1, 0, 1):
            for sz in (-1, 0, 1):
                if sx == sy == sz == 0:
                    continue
                shift = np.array([sx, sy, sz]) * box
                best = min(best, float(tree.query(X + shift, k=1)[0].min()))
    return best
