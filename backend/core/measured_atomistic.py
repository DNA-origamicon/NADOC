"""MD-measured all-atom nucleotide placement — the atomistic half of "new positioning".

Display-only.  Nothing here is a build constant, no topology is touched, and every
consumer that is not the "new positioning" view keeps the 1ZEW-derived templates in
``atomistic.py``.

Why the old templates could not simply be corrected
───────────────────────────────────────────────────
``measured_positioning.py`` (the CG half) documents the audit that started this: the
1ZEW template is wrong INTERNALLY, and not by a common factor — P, C1' and the base-ring
centroid each miss the free-MD value by a different amount and in different directions,
so no rigid move and no radial affine map can land all three.  That is the signature of
a template defect, and the conclusion recorded there was that the fix is a re-extraction
against measured geometry.  This module is that re-extraction.

How the atomistic bases are positioned now
──────────────────────────────────────────
Not by a rule.  ``scripts/measure_atomistic_template.py`` reads free (unrestrained)
NAMD trajectories and records where every heavy atom of a nucleotide actually sits
relative to the base pair it belongs to, in one frame built from the duplex itself:

    origin  the point on the LOCAL helix axis nearest this base pair
    e_x     outward radial to the FORWARD strand's phosphorus (azimuth zero)
    e_z     local helix axis, along the FORWARD strand's 5'->3'
    e_y     e_z x e_x

Three things follow, and each replaces an assumption the old code made:

1. **Both strands live in ONE frame.**  A base pair's two nucleotides are stamped into
   the same base-pair frame, so their relative placement is the measured one.  The old
   code gave each strand its own frame and then tried to reconcile them with a
   correction applied to the frame ORIGIN, which — because the template's phosphorus
   sits 0.1887 nm off that origin, and the two frames were z-mirrored — rotated the two
   phosphates in OPPOSITE directions and collapsed the separation by 2 x 12.18 deg.
   There is no such correction here; there is nothing to correct.

2. **FORWARD and REVERSE are separately measured, never derived from each other.**  No
   z-mirrored ``_..._REV`` templates, no ``e_z`` sign flip by strand.  ``e_z`` is the
   helix axis for both; the reverse strand runs 3'->5' along it because that is how it
   was measured, not because a sign was flipped.  The two templates come from disjoint
   samples (the measurement alternates which strand it calls FORWARD span by span), so
   how close they land to the pseudo-dyad is a RESULT: measured at 179.84-179.98 deg
   about an axis 0.0-0.32 deg off perpendicular, with the two strands' internal shapes
   agreeing to 0.3-1.6 pm.  The symmetry is real — but it is now evidence, not input.

3. **Every value is a 21 bp average.**  21 bp is two full helical turns, so averaging
   over one span cancels helical-phase bias and the answer does not depend on which span
   was picked (measured between-span RMS 0.063-0.069 nm per atom, SEM ~3 pm).

Provenance and its one caveat
─────────────────────────────
Pooled from five independent free-stage (``MGHH_only``) origami trajectories — 24hb at
0xT/1xT/2xT, 6hbx100_noT and 18hb — 53,088 base pairs, 11.4k-14.6k conformers per
(strand, base) bucket.  Emergent checks, i.e. quantities nothing in the pipeline was
told to reproduce: Watson-Crick N-N 0.272-0.278 nm, C1'-C1' 1.035-1.051 nm, ring
planarity <= 1.4 pm, glycosidic bond 0.146-0.148 nm, bond lengths within 5.8 pm of
reference, and sugar stereocentre signed volumes identical in sign and magnitude across
all eight buckets (no enantiomer split).

⚠ THE CROSS-STRAND AZIMUTH REMAINS PROVISIONAL.  Every trajectory in this repo was
seeded from NADOC's own build, i.e. started with the two phosphates 183.84 deg apart.
This measurement returns ~183 deg (instantaneous circular mean; ~179.5 deg through the
rigid-body average), agreeing with the independent 20 bp duplex measurement of 183.9 deg
but NOT with the 208.5 deg of the 1ZEW crystal.  Radii, internal shape and axial
placement all relaxed demonstrably away from the seed; this one degree of freedom is
slow and soft, and cannot be separated from its seed without MD started from
deliberately different groove angles (``experiments/exp52_groove_seed_sweep``).
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

_DATA = Path(__file__).with_name("data") / "measured_atomistic_template.json"

# Atoms of the sugar-phosphate backbone, in the order the measurement emits them.  The
# rest of each residue's list is its base.  Names match ``atomistic._SUGAR`` and
# ``atomistic.BASE_TEMPLATES`` exactly, so the existing bond tables, element table and
# renderer need no changes at all.
_N_SUGAR = 11


class MeasuredTemplateUnavailable(RuntimeError):
    """The measured template data file is missing or malformed."""


@lru_cache(maxsize=1)
def _payload() -> dict:
    try:
        return json.loads(_DATA.read_text())
    except FileNotFoundError as exc:  # pragma: no cover - packaging
        raise MeasuredTemplateUnavailable(f"missing {_DATA}") from exc
    except json.JSONDecodeError as exc:
        raise MeasuredTemplateUnavailable(f"corrupt {_DATA}: {exc}") from exc


@lru_cache(maxsize=1)
def measured_templates() -> dict[tuple[str, str], tuple[tuple, tuple]]:
    """``(direction, residue) -> (sugar_defs, base_defs)``.

    Each def is the ``(name, element, x, y, z)`` 5-tuple the stamping loop already
    consumes, with the coordinates read in the base-pair frame described above.
    """
    tmpl = _payload()["template"]
    out: dict[tuple[str, str], tuple[tuple, tuple]] = {}
    for direction in ("FORWARD", "REVERSE"):
        for residue in ("DA", "DT", "DG", "DC"):
            defs = tuple(
                (
                    a["name"],
                    a["element"],
                    float(a["xyz"][0]),
                    float(a["xyz"][1]),
                    float(a["xyz"][2]),
                )
                for a in tmpl[direction][residue]
            )
            if len(defs) <= _N_SUGAR or defs[0][0] != "P":
                raise MeasuredTemplateUnavailable(
                    f"unexpected atom order for {direction}/{residue}"
                )
            out[(direction, residue)] = (defs[:_N_SUGAR], defs[_N_SUGAR:])
    return out


@lru_cache(maxsize=1)
def provenance() -> dict:
    """Sources, validation and spread, for the UI and for anyone reading a saved view."""
    rep = _payload().get("report", {})
    return {
        "sources": [s.get("label") for s in rep.get("sources", [])],
        "bp_measured": sum(
            int(s.get("bp_measured", 0)) for s in rep.get("sources", [])
        ),
        "span_bp": _payload().get("report", {}).get("span_bp"),
        "dyad": rep.get("dyad", {}),
        "span_spread": rep.get("span_spread", {}),
        "cross_system": rep.get("cross_system", {}),
    }


@lru_cache(maxsize=1)
def measured_pp_separation_deg() -> float:
    """Azimuth of the REVERSE strand's phosphorus, CCW from the FORWARD strand's.

    Read back off the emitted template rather than stored as its own constant, so it
    cannot drift from the atom positions it describes.  PROVISIONAL — see the module
    docstring.
    """
    tmpl = measured_templates()
    xs, ys = [], []
    for residue in ("DA", "DT", "DG", "DC"):
        _n, _e, x, y, _z = tmpl[("REVERSE", residue)][0][0]  # the P atom
        xs.append(x)
        ys.append(y)
    ang = math.degrees(math.atan2(float(np.mean(ys)), float(np.mean(xs))))
    return ang % 360.0


@lru_cache(maxsize=1)
def _legacy_frame_in_bp_coords() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """The LEGACY ``_atom_frame``, expressed in the base-pair frame, per direction.

    Built by handing ``_atom_frame`` a synthetic helix — axis along +z through the
    origin, forward bead at azimuth 0 — which makes the base-pair frame identical to
    world, so what comes back IS the legacy frame in bp coordinates.  Derived from the
    live function rather than hardcoded, so it cannot drift from it.

    This is well-defined only because the legacy frame turns out to be INDEPENDENT of
    the helix's lattice cell type: ``geometry.py`` places the reverse bead at
    ``fwd +- 150`` deg by cell type and ``_atom_frame`` then corrects by
    ``+58.2``/``-1.8`` deg, and the two paths land on the same azimuth to 2e-16.
    Verified in ``tests/test_measured_atomistic.py``.
    """
    import math as _math

    from backend.core.atomistic import _atom_frame
    from backend.core.constants import HELIX_RADIUS
    from backend.core.geometry import NucleotidePosition
    from backend.core.models import Direction

    axis_pt = np.zeros(3)
    tangent = np.array([0.0, 0.0, 1.0])
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for direction in (Direction.FORWARD, Direction.REVERSE):
        phi = 0.0 if direction == Direction.FORWARD else _math.radians(150.0)
        bead = np.array(
            [HELIX_RADIUS * _math.cos(phi), HELIX_RADIUS * _math.sin(phi), 0.0]
        )
        nuc = NucleotidePosition(
            helix_id="_synthetic",
            bp_index=0,
            direction=direction,
            position=bead,
            base_position=bead * 0.5,
            base_normal=-bead / float(np.linalg.norm(bead)),
            axis_tangent=tangent,
        )
        out[direction.name] = _atom_frame(
            nuc, direction, axis_point=axis_pt, helix_direction=Direction.FORWARD
        )
    return out


@lru_cache(maxsize=1)
def legacy_local_templates() -> dict[tuple[str, str], tuple[tuple, tuple]]:
    """The measured templates re-expressed in LEGACY ``_atom_frame`` local coordinates.

    For the paths that build their frames with ``_atom_frame`` / ``_atom_frames_batch``
    and stamp a fixed local template — the surface atom cloud and the fast client-side
    stamp descriptor.  Because the legacy frame is a fixed rigid transform of the
    base-pair frame (see above), those paths reproduce the measured geometry exactly
    once they are handed these coordinates; no frame changes are needed there.

    NOTE these are per (direction, residue).  The legacy layout shares ONE ``_SUGAR``
    across both strands, which cannot represent what was measured: converted into this
    same frame, the forward and reverse sugars sit 333-371 pm apart (max 635 pm).  That
    gap is the legacy z-mirror construction, not a real difference between the strands
    — the strands themselves agree with the pseudo-dyad to 0.3-1.6 pm — but it is
    exactly why a shared template cannot be used.
    """
    frames = _legacy_frame_in_bp_coords()
    out: dict[tuple[str, str], tuple[tuple, tuple]] = {}
    for (direction, residue), (sugar, base) in measured_templates().items():
        origin, R = frames[direction]

        def _conv(defs):
            return tuple(
                (n, e, *(R.T @ (np.array([x, y, z]) - origin)))
                for n, e, x, y, z in defs
            )

        out[(direction, residue)] = (_conv(sugar), _conv(base))
    return out


def measured_frame(
    forward_position: np.ndarray,
    axis_tangent: np.ndarray,
    axis_point: np.ndarray,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Base-pair frame: ``(origin, R)``, or ``None`` if the inputs are degenerate.

    BOTH nucleotides of a base pair are stamped with this same frame — that is what
    carries their measured relative placement into the render, and it is why the
    reverse strand needs no correction of any kind.  The anchor is therefore always
    the FORWARD strand's backbone bead, passed in explicitly, whichever strand is
    being stamped.

    Taking the forward bead rather than deriving it from the reverse one is deliberate.
    The obvious shortcut — rotate the reverse bead back by the topology layer's groove
    angle — assumes the two beads are exactly +-150 deg apart, and they are not: skips,
    loops and per-helix phase all move them.  Measured on
    ``Examples/2hb_xover_atoms_test.nadoc`` that shortcut put the two strands in
    frames 1.72 nm apart, while reading the forward bead reproduces the template's
    cross-strand geometry to floating point on every design tried.

    An unpaired nucleotide has no base pair and therefore no frame here; the caller
    falls back to the legacy path rather than inventing one.
    """
    t = np.asarray(axis_tangent, dtype=float)
    n_t = float(np.linalg.norm(t))
    if n_t < 1e-12:
        return None
    t = t / n_t

    origin = np.asarray(axis_point, dtype=float)
    radial = np.asarray(forward_position, dtype=float) - origin
    radial = radial - np.dot(radial, t) * t
    n_r = float(np.linalg.norm(radial))
    if n_r < 1e-9:
        return None
    e_x = radial / n_r
    return origin, np.column_stack([e_x, np.cross(t, e_x), t])
