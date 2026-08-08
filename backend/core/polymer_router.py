"""Route-for-polymerization — fill bare scaffold ends with connector staples and
stitch each face-helix into a bridging staple across a periodic boundary.

This is a TOPOLOGY-layer op (Three-Layer Law layer 1): it creates real STAPLE
strands + ``ForcedLigation`` records. Geometry/physical layers derive from the
result; nothing here reads or writes positions.

User-validated design decisions (do not silently change — see the session that
introduced this file and the periodic-boundary / polymerize-origami memories):

* **Seam carrier = bridging STAPLES.** The scaffold stays a per-copy plasmid; the
  generated connector staples are what physically stitch copy N's far end to
  copy N+1's near end.
* **One FIXED connector strand per bare end** — sized to exactly cover that
  helix's unpaired-scaffold run. No tick/grow/merge length rules (those are the
  normal autostaple machinery; a polymer connector is deliberately simple).
* **Every face-helix that has BOTH ends gets a bridging staple, and EVERY bridge
  is flagged ``is_periodic_seam``** — each helix's bridging staple genuinely
  wraps through the periodic boundary, so the duplex is continuous across copies
  on every helix (this is what the cadnano periodic-boundary view renders as a
  through-boundary connection). ``derive_periodic_delta`` reads all of them and
  least-squares-averages the per-helix repeats — that is *more* robust than
  trusting one, not an over-constraint (a straight bundle still resolves to a
  pure axial translation; ragged faces average to a sub-degree residual). The
  assembly mate connector still uses just one seam
  (``principal_seam_connectors`` returns ``frames[0]``), so multiple flags don't
  fight there either. ``principal_seam_id`` in the result is just the first
  bridge, for reporting.
* **Ends are FULLY duplexed** — the connector covers the whole bare run, leaving
  no tip toehold.
* **Warn, never block.** Missing autoscaffold op or a one-sided helix produces a
  warning; the op still does what it can.

The bridging ligation joins the two connectors at their CAP tips (the helix's
low-bp / high-bp terminal faces), NOT their inner edges. That is what makes the
seam endpoints land on the terminal cross-sections, so the derived repeat period
equals the whole part length. ``test_polymer_router`` pins this via the
``derive_periodic_delta`` → pure-axial-translation oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.flexible_segments import unpaired_bead_keys
from backend.core.lattice import (
    _ligate,
    _opposite_direction,
    _scaffold_coverage_by_helix,
)
from backend.core.models import (
    Design,
    Direction,
    Domain,
    ForcedLigation,
    Strand,
    StrandType,
)

_CONNECTOR_COLOR = "#7CFC00"  # chartreuse — visually flags polymer connectors
_CONNECTOR_NOTE = "polymerization connector"

# Feature-log op kinds that count as "the user has run autoscaffold".
_AUTOSCAFFOLD_OP_KINDS = (
    "auto-scaffold",
    "auto-scaffold-seamed",
    "auto-scaffold-matched",
    "auto-scaffold-seamless",
)


@dataclass
class _Ends:
    """Per-helix bare-scaffold end runs (inclusive bp ranges, or None)."""

    near: tuple[int, int] | None  # run touching the low-bp face
    far: tuple[int, int] | None  # run touching the high-bp face
    whole: bool = False  # entire scaffold on this helix is unpaired


@dataclass
class PolymerRouteResult:
    new_connector_strand_ids: list[str] = field(default_factory=list)
    seam_ligation_ids: list[str] = field(default_factory=list)
    principal_seam_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    valid: bool = True
    errors: list[str] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────────────


def _scaffold_dir_by_helix(design: Design) -> dict[str, Direction]:
    """``{helix_id: scaffold direction}`` for every helix carrying scaffold."""
    out: dict[str, Direction] = {}
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD and not s.is_reference:
            for d in s.domains:
                out.setdefault(d.helix_id, d.direction)
    return out


def _contiguous_runs(bps: list[int]) -> list[tuple[int, int]]:
    """Collapse a sorted bp list into inclusive contiguous ``(lo, hi)`` runs."""
    if not bps:
        return []
    runs: list[tuple[int, int]] = []
    start = prev = bps[0]
    for b in bps[1:]:
        if b == prev + 1:
            prev = b
        else:
            runs.append((start, prev))
            start = prev = b
    runs.append((start, prev))
    return runs


def _bare_end_runs(design: Design) -> dict[str, _Ends]:
    """Per-helix unpaired-scaffold runs touching the low/high terminal faces.

    A bp is a bare-scaffold bead when it is occupied by the scaffold strand and
    its Watson-Crick slot (opposite direction, same bp) is empty. Only runs that
    reach a helix's scaffold cap count as a polymer end — interior unpaired runs
    (e.g. a hinge) are left alone.
    """
    cov = _scaffold_coverage_by_helix(design)
    sdir = _scaffold_dir_by_helix(design)
    unpaired = unpaired_bead_keys(design)
    out: dict[str, _Ends] = {}
    for hid, (lo, hi) in cov.items():
        d = sdir.get(hid)
        if d is None:
            continue
        ubps = sorted(bp for (h, bp, dr) in unpaired if h == hid and dr == d)
        runs = _contiguous_runs(ubps)
        near = next((r for r in runs if r[0] == lo), None)
        far = next((r for r in runs if r[1] == hi), None)
        whole = near is not None and near == far  # one run spans the whole helix
        if whole:
            out[hid] = _Ends(near=None, far=None, whole=True)
        else:
            out[hid] = _Ends(near=near, far=far)
    return out


def _complement_strand(
    helix_id: str, lo: int, hi: int, scaffold_dir: Direction
) -> Strand:
    """A single-domain STAPLE antiparallel to the scaffold over ``[lo, hi]``."""
    cdir = _opposite_direction(scaffold_dir)
    # 5'→3' traversal: FORWARD runs low→high, REVERSE runs high→low.
    start, end = (lo, hi) if cdir == Direction.FORWARD else (hi, lo)
    dom = Domain(helix_id=helix_id, start_bp=start, end_bp=end, direction=cdir)
    return Strand(
        domains=[dom],
        strand_type=StrandType.STAPLE,
        color=_CONNECTOR_COLOR,
        notes=_CONNECTOR_NOTE,
    )


def _has_autoscaffold(design: Design) -> bool:
    """True when an autoscaffold op is present (feature log or crossover lineage)."""
    for entry in design.feature_log:
        if getattr(entry, "op_kind", None) in _AUTOSCAFFOLD_OP_KINDS:
            return True
    for xo in design.crossovers:
        if (xo.process_id or "").startswith("auto_scaffold_"):
            return True
    return False


def _helix_label(design: Design, helix_id: str) -> str:
    h = design.find_helix(helix_id)
    if h is not None and h.label:
        return h.label
    # fall back to position in the design's helix order
    for i, hh in enumerate(design.helices):
        if hh.id == helix_id:
            return str(i)
    return helix_id


def _bridge(
    design: Design,
    near_s: Strand,
    far_s: Strand,
    is_periodic_seam: bool,
) -> tuple[Design, ForcedLigation]:
    """Ligate the near + far connectors at their CAP tips into one bridging staple.

    The connector whose cap tip is its 3' end is the three-prime donor; the other
    is the five-prime acceptor. Picking the donor by domain orientation (not by a
    geometric guess) keeps the seam endpoints on the terminal faces for either
    scaffold polarity.
    """
    near_dom = near_s.domains[0]
    near_cap = min(
        near_dom.start_bp, near_dom.end_bp
    )  # near connector's outer (low) cap
    # near connector's cap tip is its 3' end iff its domain ends at the low cap.
    if near_dom.end_bp == near_cap:
        tp_strand, fp_strand = near_s, far_s
    else:
        tp_strand, fp_strand = far_s, near_s

    three_dom = tp_strand.domains[-1]
    five_dom = fp_strand.domains[0]
    fl = ForcedLigation(
        three_prime_helix_id=three_dom.helix_id,
        three_prime_bp=three_dom.end_bp,
        three_prime_direction=three_dom.direction,
        five_prime_helix_id=five_dom.helix_id,
        five_prime_bp=five_dom.start_bp,
        five_prime_direction=five_dom.direction,
        is_periodic_seam=is_periodic_seam,
    )
    design = _ligate(design, tp_strand, fp_strand)
    design = design.model_copy(
        update={
            "forced_ligations": list(design.forced_ligations) + [fl],
        }
    )
    return design, fl


# ── public entry ─────────────────────────────────────────────────────────────


def route_for_polymerization(design: Design) -> tuple[Design, PolymerRouteResult]:
    """Fill bare scaffold ends with connector staples + stitch periodic-seam bridges.

    Returns ``(updated_design, result)``. ``result.valid`` is False (with a
    populated ``errors`` list) only when there is nothing to route at all; every
    softer problem is a non-blocking warning.
    """
    res = PolymerRouteResult()

    if not _has_autoscaffold(design):
        res.warnings.append(
            "No Autoscaffold operation found — the two terminal faces may not be "
            "translation-matched, so polymer copies may not stack cleanly. Run "
            "Autoscaffold (matched ends) first for a clean periodic seam."
        )

    sdir = _scaffold_dir_by_helix(design)
    ends = _bare_end_runs(design)

    new_strands: list[Strand] = []
    bridges: list[tuple[Strand, Strand]] = []  # (near, far) pairs to ligate
    for hid, e in ends.items():
        label = _helix_label(design, hid)
        if e.whole:
            res.warnings.append(
                f"Helix {label}: entire scaffold is unpaired — skipped "
                "(no interior duplex to anchor a polymer seam)."
            )
            continue
        d = sdir[hid]
        near_s = _complement_strand(hid, e.near[0], e.near[1], d) if e.near else None
        far_s = _complement_strand(hid, e.far[0], e.far[1], d) if e.far else None
        if near_s:
            new_strands.append(near_s)
        if far_s:
            new_strands.append(far_s)
        if near_s and far_s:
            bridges.append((near_s, far_s))
        elif near_s or far_s:
            missing = "far (high-bp)" if near_s else "near (low-bp)"
            res.warnings.append(
                f"Helix {label}: no unpaired scaffold at the {missing} end — "
                "connector added on the present end only; no bridge formed."
            )

    if not new_strands:
        res.valid = False
        res.errors.append(
            "No unpaired scaffold ends found — nothing to route. Leave the "
            "scaffold single-stranded at the two terminal faces first."
        )
        return design, res

    design = design.model_copy(update={"strands": list(design.strands) + new_strands})
    res.new_connector_strand_ids = [s.id for s in new_strands]

    for near_s, far_s in bridges:
        # Every bridge IS a periodic seam — each helix's bridging staple wraps
        # through the boundary end-to-end. (principal_seam_id = the first, for
        # reporting + the assembly mate, which only needs one connector pair.)
        design, fl = _bridge(design, near_s, far_s, is_periodic_seam=True)
        res.seam_ligation_ids.append(fl.id)
        if res.principal_seam_id is None:
            res.principal_seam_id = fl.id

    if not bridges:
        res.warnings.append(
            "No helix had unpaired scaffold at BOTH ends — connectors were added "
            "but no periodic seam was formed; the part is not polymerizable yet."
        )

    return design, res
