"""mrDNA anchor restraints — hold resolved anchor beads immobile in an ARBD CG run.

An *anchor* is a JOB-REQUEST annotation (never a ``Design`` edit — Three-Layer Law):
the user picks a scope in the SHARED oxDNA/CanDo/NAMD anchor picker (overhang / cluster
/ domain / strand / base) and the beads covering that region are pinned to their
starting positions with an ARBD harmonic ``RESTRAINT``.  Under a uniform field or any
COM-drifting protocol this is what keeps the structure from streaming out of the box.

Mapping scope → beads (the "shared scope resolver → per-nt keys → engine bead indices"
contract N2/C1 established, adapted to mrDNA's realities):

  * The shared :func:`resolve_anchor_particles` turns scopes into per-nucleotide
    ``(helix_id, bp, direction)`` keys.
  * mrDNA groups helices by *base-pairing*, not NADOC ``helix_id`` (the reader's
    ``basepairs_and_stacks_to_helixmap``), so a segment's ``name`` is NOT the NADOC
    helix id — name-based mapping is unreliable.  And the CG model collapses each base
    pair to ONE forward bead (1 bead/bp fine, ~5 bp/bead coarse; see
    ``memory/project_mrdna_bead_model.md``).
  * So we map by POSITION: the mrDNA model is built directly from the per-nucleotide
    backbone array ``r`` (Å) — beads sit in that same coordinate frame — so each anchor
    nucleotide's ``r`` position resolves to its nearest bead.  A whole-domain / cluster
    scope yields the contiguous bead run covering it; a lone reverse-strand base may pin
    a bead a bp or two off (its backbone is ~2 nm across the axis from the forward bead),
    which still holds that region.

mrDNA regenerates beads (``clear_beads()`` + ``generate_bead_model()``) between
resolution stages inside ``multiresolution_simulation`` — restraints live on the bead
objects and would be wiped.  :func:`install_anchor_restraints` wraps the model's
``generate_bead_model`` so the restraints are re-applied after every regeneration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from backend.core.models import Design

logger = logging.getLogger(__name__)

# Harmonic spring for a held bead, kcal/mol/Å² (ARBD ``RESTRAINT idx k x y z``).  Stiff
# enough that a pinned CG bead's thermal RMS displacement is well under a bp (kT≈0.6
# kcal/mol at 300 K ⇒ sqrt(kT/2k) ≈ 0.25 Å at k=5); the slow real-ARBD oracle checks
# anchored beads hold while free beads move.
ANCHOR_SPRING_KCAL_MOL_A2 = 5.0


def _model_beads(model) -> list:
    """Flat, stable-order list of the model's DNA beads (excludes orientation beads,
    which ``segment.beads`` already omits).  This order matches the ``.idx`` ARBD
    assigns in ``prepare_for_simulation`` (verified: flat ordinal == bead.idx)."""
    return [b for s in model.segments for b in getattr(s, "beads", [])]


def _anchor_nt_positions(design: "Design", anchors) -> np.ndarray:
    """The (M,3) Å backbone positions of every nucleotide the scopes resolve to.

    Reuses the shared resolver; stale / ssDNA-only / extra-base-insert keys drop
    silently (extra-base inserts carry ``helix_id=None`` so no scope selects them).

    Strand-extension tail beads are dropped EXPLICITLY (``helix_id`` starts ``__ext_``):
    a 'strand' scope does select them, but a floppy terminal ssDNA tail is not a rigid
    tether point, and its key — a 3-tuple whose bp_index is an ordinary int — otherwise
    resolves like a real nucleotide.  (``__lnk__`` virtual linker helices are real duplex
    and stay anchorable, so this tests the extension prefix, not just ``__``.)"""
    if not anchors:
        return np.empty((0, 3))
    from backend.core.mrdna_bridge import _EXT_PREFIX  # noqa: PLC0415
    from backend.physics.oxdna_interface import resolve_anchor_particles  # noqa: PLC0415

    _parts, keys = resolve_anchor_particles(design, anchors)
    hbd = {(k[0], k[1], k[2]) for k in keys
           if len(k) >= 3 and not (isinstance(k[0], str) and k[0].startswith(_EXT_PREFIX))}
    if not hbd:
        return np.empty((0, 3))

    from backend.core.mrdna_bridge import _build_nt_arrays  # noqa: PLC0415

    r, _bp, _stk, _tp, _ori, _seq, nt_key = _build_nt_arrays(design, return_nt_key=True)
    idxs = [idx for (h_id, bp_idx, direction, _k), idx in nt_key.items()
            if not h_id.startswith(_EXT_PREFIX) and (h_id, bp_idx, direction) in hbd]
    if not idxs:
        return np.empty((0, 3))
    return np.asarray(r)[idxs]


def resolve_anchor_beads(design: "Design", model, anchors) -> list:
    """Bead objects (deduped, ``.beads``-order) nearest the anchor-scope nucleotides.

    The model's bead cloud must already be generated (it is, straight out of
    ``mrdna_model_from_nadoc`` / after ``generate_bead_model``)."""
    pos = _anchor_nt_positions(design, anchors)
    beads = _model_beads(model)
    if pos.shape[0] == 0 or not beads:
        return []
    bpos = np.array([b.get_collapsed_position() for b in beads], dtype=float)
    chosen: set[int] = set()
    for p in pos:
        chosen.add(int(np.argmin(((bpos - p) ** 2).sum(axis=1))))
    return [beads[i] for i in sorted(chosen)]


def apply_anchor_restraints(
    design: "Design", model, anchors, *, k: float = ANCHOR_SPRING_KCAL_MOL_A2
) -> list:
    """Pin each resolved anchor bead to its current position with a harmonic
    restraint of spring constant ``k``.  Returns the restrained bead objects.

    A one-element restraint ``(k,)`` tells ARBD to hold the bead at its own current
    (collapsed) position — exactly the anchor semantic."""
    beads = resolve_anchor_beads(design, model, anchors)
    for b in beads:
        b.add_restraint((float(k),))
    return beads


def install_anchor_restraints(
    design: "Design", model, anchors, *, k: float = ANCHOR_SPRING_KCAL_MOL_A2
) -> int:
    """Wire anchor restraints into a model so they survive mrDNA's bead regeneration.

    ``multiresolution_simulation`` calls ``model.clear_beads(); model.generate_bead_model()``
    several times (coarse → fine → frozen-twist); each wipes the previous beads and
    their restraints.  We wrap the instance's ``generate_bead_model`` so the restraints
    are re-resolved + re-applied after every regeneration.  The single coarse pass
    (``model.simulate`` on the as-built beads, no regeneration) is covered by the
    immediate application below.

    Returns the number of beads restrained on the current bead cloud (0 for the fine
    path where beads are regenerated later)."""
    if not anchors:
        return 0

    orig = model.generate_bead_model

    def _wrapped(*args, **kwargs):
        orig(*args, **kwargs)
        n = len(apply_anchor_restraints(design, model, anchors, k=k))
        logger.info("mrdna anchors: re-applied %d bead restraint(s) after bead regen", n)

    model.generate_bead_model = _wrapped

    if any(getattr(s, "beads", None) for s in model.segments):
        n = len(apply_anchor_restraints(design, model, anchors, k=k))
        logger.info("mrdna anchors: applied %d bead restraint(s) to current bead cloud", n)
        return n
    return 0


def restraint_records(model) -> list[tuple[int, float, tuple]]:
    """The ARBD restraint block as ``(bead_idx, k, (x,y,z))`` triples — the content of
    the ``<name>.restraint.txt`` ARBD writes (``RESTRAINT idx k x y z``).

    Calls ``prepare_for_simulation`` so bead ``.idx`` values are assigned, mirroring the
    engine's own write path.  Lets a headless oracle assert the input carries a restraint
    for exactly the resolved anchor beads without launching ARBD."""
    model.prepare_for_simulation()
    out: list[tuple[int, float, tuple]] = []
    for site, restraint in model.get_restraints():
        if len(restraint) == 1:
            k = float(restraint[0])
            pos = tuple(float(c) for c in site.get_collapsed_position())
        elif len(restraint) == 2:
            k = float(restraint[0])
            pos = tuple(float(c) for c in restraint[1])
        else:  # pragma: no cover — 5-tuple form unused by our anchors
            k = float(restraint[1])
            pos = tuple(float(c) for c in restraint[2:5])
        out.append((int(site.idx), k, pos))
    return out
