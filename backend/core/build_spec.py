"""Declarative build-spec grammar + parser (AF-11, Tier 4 — text-to-DNA groundwork).

A *build spec* is a plain JSON/dict description of a design or assembly: a lattice
(or part library) plus an ordered list of construction operations.  This module is
the **pure** half of the interpreter — it validates a spec against the grammar and
normalises it into an ordered :class:`BuildOp` list, with **no execution** and no
import of :mod:`backend.api`.  The thin driver that actually *runs* the op list by
dispatching each op to its existing headless wrapper lives in
:mod:`backend.api.headless_spec_build` (api may import core, not the reverse).

Why split it this way: keeping the grammar pure makes it exhaustively unit-testable
(spec in → op list out, or :class:`BuildSpecError` on a malformed spec) and lets the
parser catch whole classes of error — unknown op, missing/mistyped field, a typo'd
key, a ``mate`` that references an instance that was never added or a connector label
that does not exist — *before* any build runs.  The driver then only ever sees a
well-formed op list.

The grammar is deliberately tiny (the "start small, grow it" of the backlog):

* **design** ops — ``bundle`` · ``extrude`` · ``nick`` · ``ligate`` · ``loop_skip`` ·
  ``bend`` · ``twist`` · ``circle_segment`` · ``auto_scaffold`` · ``auto_crossover`` ·
  ``full_autostaple`` · ``apply_loop_skips``
* **assembly** ops — ``add_part`` · ``place_grid`` · ``place_ring`` · ``mate`` ·
  ``gear`` · ``belt`` · ``polymerize``

Helices are referenced declaratively by their lattice ``grid_pos`` ``[row, col]``
(stable across id schemes), assembly instances by a spec-assigned ``ref`` key, and
the joints a ``mate`` creates by an optional ``ref`` key a ``gear``/``belt``/
``polymerize`` then references — so a spec never needs a runtime-generated id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.core.models import Direction, LatticeType
from backend.core.oxdna_health import ConstraintSpecError, parse_constraint_spec


class BuildSpecError(ValueError):
    """A build spec violated the grammar (unknown op, missing/mistyped field,
    dangling reference, …).  A subclass of :class:`ValueError` so callers can catch
    either."""


@dataclass(frozen=True)
class BuildOp:
    """One normalised, validated construction operation.

    ``op`` is the op name (e.g. ``"bundle"``); ``params`` carries the validated,
    type-coerced parameters (cells as ``(row, col)`` tuples, ``direction`` as a
    :class:`Direction`, transforms normalised to a tagged dict, …) ready for the
    driver to hand straight to a wrapper.
    """

    op: str
    params: dict


@dataclass
class DesignSpec:
    """A parsed design spec: a lattice + an ordered op list (first op is a bundle),
    plus an optional list of declarative relaxed-structure ``constraints`` (AF-13 P3
    specs — physical-layer pass/fail gates the driver REPORTS against an oxDNA run;
    each landmark names a helix by ``grid_pos`` the driver resolves at build time) and
    an optional ``optimize`` block (AF-13 P5 — a parametric ``knob`` + a single
    ``constraint`` the driver drives through the closed
    :func:`~backend.api.headless_oxdna_build.iterate_to_constraint` loop until met)."""

    lattice: LatticeType
    ops: list[BuildOp]
    constraints: list[dict] = field(default_factory=list)
    optimize: dict | None = None


@dataclass
class FilePart:
    """A part referenced by a saved ``.nadoc`` file path (AF-12 ``from_file``) instead
    of an inline design spec — so an assembly spec can instance a hand-authored,
    experimentally-validated saved primitive **by path** rather than re-declaring its
    topology inline.  The driver lowers it to
    :func:`backend.api.headless_assembly_build.add_file_instance` (the part travels as a
    file *reference*, not an embedded copy), and the load-bearing
    :func:`tests.automation_harness.assert_part_from_file` oracle proves the instance
    resolves to *exactly* that file's validated topology — a property
    :func:`~tests.automation_harness.canonical_assembly` is blind to (it keys a file
    source by ``(path, sha256)`` only, never loading the design)."""

    path: str


@dataclass
class PrimitivePart:
    """A part referenced by **catalog name** (AF-12 Phase 2 ``from_primitive``) rather than
    an inline design spec or a raw file path — so an assembly spec can instance a curated,
    pre-validated building block (``6hb_primitive`` / ``18hb_primitive`` / …) by the same
    name the "Add Primitive" UI shows, without knowing where its ``.nadoc`` lives.

    The driver resolves the name → the catalog primitive's saved ``.nadoc`` path
    (:func:`backend.core.primitive_catalog.design_path`) and lowers it through the **exact**
    ``from_file`` machinery (:class:`FilePart`): the part travels as a file *reference*, not
    an embedded copy.  The new, load-bearing piece this adds over ``from_file`` is the
    **name→catalog-path resolver**, pinned by
    :func:`tests.automation_harness.assert_part_from_primitive` (which independently
    re-resolves the name through the catalog and proves the placed instance is that exact
    primitive's validated topology — a name silently pointing at the wrong/renamed primitive
    is invisible to :func:`~tests.automation_harness.canonical_assembly`).

    A *parametric* primitive (``metadata.primitive_kind`` — e.g. the radius-driven circle
    disc, AF-12 Phase 2b) instead carries a ``params`` dict (``{"radius_nm": 12}``) and is
    built **generatively** at build time (lowered to its primordial op, e.g. ``circle_segment``)
    and embedded INLINE — it is NOT a file reference, so :func:`assert_part_from_primitive`
    (file-backed) does not apply; the placed disc is pinned by the AF-4 geometric oracle via
    :func:`tests.automation_harness.assert_part_is_circular_disc`.  The parser stays
    catalog-agnostic: ``params`` is validated as a generic name→number map here, and whether a
    given primitive *requires* / *forbids* params is decided at build time once its
    ``primitive_kind`` is read from the catalog."""

    name: str
    params: dict = field(default_factory=dict)


@dataclass
class AssemblySpec:
    """A parsed assembly spec: a name, a library of parsed parts (by key — each an inline
    :class:`DesignSpec`, a file-backed :class:`FilePart`, or a catalog-named
    :class:`PrimitivePart`), and an ordered op list referencing those parts."""

    name: str
    parts: dict[str, DesignSpec | FilePart | PrimitivePart]
    ops: list[BuildOp] = field(default_factory=list)


# ── primitive field validators ────────────────────────────────────────────────


def _require_keys(d: dict, allowed: set, *, where: str) -> None:
    """Reject any key not in ``allowed`` (catches typo'd field names)."""
    extra = set(d) - allowed
    if extra:
        raise BuildSpecError(
            f"{where}: unknown field(s) {sorted(extra)} — allowed: {sorted(allowed)}"
        )


def _get(d: dict, key: str, *, where: str):
    if key not in d:
        raise BuildSpecError(f"{where}: missing required field {key!r}")
    return d[key]


def _as_int(v, *, key: str, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise BuildSpecError(f"{where}: field {key!r} must be an int, got {v!r}")
    return v


def _as_num(v, *, key: str, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise BuildSpecError(f"{where}: field {key!r} must be a number, got {v!r}")
    return float(v)


def _as_bool(v, *, key: str, where: str) -> bool:
    if not isinstance(v, bool):
        raise BuildSpecError(f"{where}: field {key!r} must be a bool, got {v!r}")
    return v


def _as_str(v, *, key: str, where: str) -> str:
    if not isinstance(v, str):
        raise BuildSpecError(f"{where}: field {key!r} must be a string, got {v!r}")
    return v


def _as_cell(v, *, where: str) -> tuple[int, int]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise BuildSpecError(f"{where}: a cell must be a [row, col] pair, got {v!r}")
    return (
        _as_int(v[0], key="cell.row", where=where),
        _as_int(v[1], key="cell.col", where=where),
    )


def _as_cells(v, *, where: str) -> list[tuple[int, int]]:
    if not isinstance(v, (list, tuple)) or not v:
        raise BuildSpecError(
            f"{where}: 'cells' must be a non-empty list of [row, col] pairs"
        )
    return [_as_cell(c, where=where) for c in v]


def _as_vec3(v, *, key: str, where: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise BuildSpecError(
            f"{where}: field {key!r} must be a 3-number vector, got {v!r}"
        )
    return tuple(_as_num(x, key=key, where=where) for x in v)  # type: ignore[return-value]


def _as_direction(v, *, where: str) -> Direction:
    if isinstance(v, Direction):
        return v
    if isinstance(v, str):
        try:
            return Direction(v.upper())
        except ValueError:
            pass
    raise BuildSpecError(
        f"{where}: 'direction' must be 'forward' or 'reverse', got {v!r}"
    )


def _as_lattice(v, *, where: str) -> LatticeType:
    if isinstance(v, LatticeType):
        return v
    if isinstance(v, str):
        try:
            return LatticeType(v.upper())
        except ValueError:
            pass
    raise BuildSpecError(
        f"{where}: 'lattice' must be 'honeycomb' or 'square', got {v!r}"
    )


def _as_transform(v, *, where: str):
    """Normalise an optional transform → ``None`` | ``{"kind","values"}``.

    Accepts ``None`` (identity), a ``[x, y, z]`` translation, or a flat 16-float
    row-major matrix.  The driver materialises it into a ``Mat4x4`` at run time.
    """
    if v is None:
        return None
    if not isinstance(v, (list, tuple)):
        raise BuildSpecError(
            f"{where}: 'transform' must be null, a [x,y,z] translation, or 16 floats"
        )
    if len(v) == 3:
        return {
            "kind": "translation",
            "values": _as_vec3(v, key="transform", where=where),
        }
    if len(v) == 16:
        return {
            "kind": "matrix",
            "values": [_as_num(x, key="transform", where=where) for x in v],
        }
    raise BuildSpecError(
        f"{where}: 'transform' must have 3 (translation) or 16 (matrix) entries, "
        f"got {len(v)}"
    )


# ── design grammar ────────────────────────────────────────────────────────────

_DESIGN_OP_KEYS = {
    "bundle": {
        "op",
        "cells",
        "length_bp",
        "plane",
        "name",
        "strand_filter",
        "ligate_adjacent",
    },
    "extrude": {
        "op",
        "cells",
        "length_bp",
        "offset_nm",
        "plane",
        "strand_filter",
        "extend_inplace",
        "ligate_adjacent",
    },
    "nick": {"op", "helix", "bp_index", "direction"},
    "ligate": {"op", "helix", "bp_index", "direction"},
    "loop_skip": {"op", "helix", "bp_index", "delta"},
    # Two addressing modes (mutually exclusive, validated in _parse_design_op):
    #   bulk     → {op, sequence, filter}                  (filter ∈ all|scaffold|staple)
    #   precise  → {op, sequence, helix_a, helix_b, bp_index}
    "crossover_extra_bases": {
        "op",
        "sequence",
        "filter",
        "helix_a",
        "helix_b",
        "bp_index",
    },
    "bend": {"op", "plane_a_bp", "plane_b_bp", "curvature_deg_per_bp", "direction_deg"},
    "twist": {"op", "plane_a_bp", "plane_b_bp", "total_degrees", "degrees_per_nm"},
    "circle_segment": {
        "op",
        "radius_nm",
        "plane",
        "offset_nm",
        "strand_filter",
        "ligate_adjacent",
        "min_chord_bp",
    },
    "auto_scaffold": {"op", "seamless"},
    "auto_crossover": {"op"},
    "full_autostaple": {"op", "scaffold_name", "custom_sequence", "strand_id"},
    "apply_loop_skips": {"op"},
}

# Ops that create their own helices from scratch → may be the FIRST op (all others
# need existing helices to extrude/nick/ligate/deform).
_PRIMORDIAL_DESIGN_OPS = {"bundle", "circle_segment"}

# Extra-base sequences are single-stranded inserts — A/C/G/T plus N (any); "" clears.
_EXTRA_BASES_RE = re.compile(r"^[ACGTNacgtn]*$")
_CROSSOVER_FILTERS = ("all", "scaffold", "staple")


def _parse_design_op(raw, *, where: str) -> BuildOp:
    if not isinstance(raw, dict):
        raise BuildSpecError(f"{where}: each op must be an object, got {raw!r}")
    op = _get(raw, "op", where=where)
    if op not in _DESIGN_OP_KEYS:
        raise BuildSpecError(
            f"{where}: unknown design op {op!r} — known: {sorted(_DESIGN_OP_KEYS)}"
        )
    here = f"{where} op={op!r}"
    _require_keys(raw, _DESIGN_OP_KEYS[op], where=here)
    p: dict = {}

    if op in ("bundle", "extrude"):
        p["cells"] = _as_cells(_get(raw, "cells", where=here), where=here)
        p["length_bp"] = _as_int(
            _get(raw, "length_bp", where=here), key="length_bp", where=here
        )
        if p["length_bp"] == 0:
            raise BuildSpecError(f"{here}: 'length_bp' must be non-zero")
        p["plane"] = _as_str(raw.get("plane", "XY"), key="plane", where=here)
        p["strand_filter"] = _as_str(
            raw.get("strand_filter", "both"), key="strand_filter", where=here
        )
        p["ligate_adjacent"] = _as_bool(
            raw.get("ligate_adjacent", True), key="ligate_adjacent", where=here
        )
        if op == "extrude":
            p["offset_nm"] = _as_num(
                _get(raw, "offset_nm", where=here), key="offset_nm", where=here
            )
            p["extend_inplace"] = _as_bool(
                raw.get("extend_inplace", True), key="extend_inplace", where=here
            )
    elif op in ("nick", "ligate"):
        p["helix"] = _as_cell(_get(raw, "helix", where=here), where=here)
        p["bp_index"] = _as_int(
            _get(raw, "bp_index", where=here), key="bp_index", where=here
        )
        if p["bp_index"] < 0:
            raise BuildSpecError(f"{here}: 'bp_index' must be ≥ 0")
        p["direction"] = _as_direction(_get(raw, "direction", where=here), where=here)
    elif op == "loop_skip":
        # A single loop (+1, extra base) / skip (−1, deleted base) / removal (0) on
        # one helix at one bp — a length-changing mark on Helix.loop_skips (outside
        # the strand graph).  delta is route-constrained to {-1, 0, +1}.
        p["helix"] = _as_cell(_get(raw, "helix", where=here), where=here)
        p["bp_index"] = _as_int(
            _get(raw, "bp_index", where=here), key="bp_index", where=here
        )
        if p["bp_index"] < 0:
            raise BuildSpecError(f"{here}: 'bp_index' must be ≥ 0")
        p["delta"] = _as_int(_get(raw, "delta", where=here), key="delta", where=here)
        if p["delta"] not in (-1, 0, 1):
            raise BuildSpecError(
                f"{here}: 'delta' must be -1 (skip), 0 (remove), or +1 (loop), "
                f"got {p['delta']}"
            )
    elif op == "crossover_extra_bases":
        # Set single-stranded extra bases on placed crossover junction(s) — junction
        # metadata, not a strand-graph edit, so it requires crossovers already placed
        # (run auto_crossover / full_autostaple first).  Crossovers carry random uuids,
        # so a junction is addressed declaratively in one of two mutually-exclusive modes:
        #   • bulk    — 'filter' (all|scaffold|staple): annotate every matching crossover
        #   • precise — 'helix_a' + 'helix_b' + 'bp_index': one junction by its two cells
        seq = _as_str(_get(raw, "sequence", where=here), key="sequence", where=here)
        if not _EXTRA_BASES_RE.match(seq):
            raise BuildSpecError(
                f"{here}: 'sequence' must match [ACGTNacgtn]* (\"\" clears), got {seq!r}"
            )
        p["sequence"] = seq.upper()
        has_loc = any(k in raw for k in ("helix_a", "helix_b", "bp_index"))
        has_filter = "filter" in raw
        if has_loc and has_filter:
            raise BuildSpecError(
                f"{here}: give EITHER 'filter' (bulk) OR 'helix_a'+'helix_b'+'bp_index' "
                f"(precise), not both"
            )
        if has_loc:
            p["mode"] = "precise"
            p["helix_a"] = _as_cell(_get(raw, "helix_a", where=here), where=here)
            p["helix_b"] = _as_cell(_get(raw, "helix_b", where=here), where=here)
            p["bp_index"] = _as_int(
                _get(raw, "bp_index", where=here), key="bp_index", where=here
            )
            if p["bp_index"] < 0:
                raise BuildSpecError(f"{here}: 'bp_index' must be ≥ 0")
        else:
            p["mode"] = "bulk"
            filt = _as_str(raw.get("filter", "all"), key="filter", where=here)
            if filt not in _CROSSOVER_FILTERS:
                raise BuildSpecError(
                    f"{here}: 'filter' must be one of {list(_CROSSOVER_FILTERS)}, got {filt!r}"
                )
            p["filter"] = filt
    elif op == "circle_segment":
        # A parametric flat disc: a SQUARE-lattice row of helices whose per-cell
        # lengths trace a circle of radius_nm (the chord profile assumes the SQUARE
        # column pitch — enforced at the spec level in parse_design_spec).  Builds
        # its own helices, so it may be the first op.
        p["radius_nm"] = _as_num(
            _get(raw, "radius_nm", where=here), key="radius_nm", where=here
        )
        if p["radius_nm"] <= 0:
            raise BuildSpecError(f"{here}: 'radius_nm' must be > 0")
        p["plane"] = _as_str(raw.get("plane", "XY"), key="plane", where=here)
        p["offset_nm"] = _as_num(raw.get("offset_nm", 0.0), key="offset_nm", where=here)
        p["strand_filter"] = _as_str(
            raw.get("strand_filter", "both"), key="strand_filter", where=here
        )
        p["ligate_adjacent"] = _as_bool(
            raw.get("ligate_adjacent", True), key="ligate_adjacent", where=here
        )
        if "min_chord_bp" in raw:
            p["min_chord_bp"] = _as_int(
                raw["min_chord_bp"], key="min_chord_bp", where=here
            )
    elif op == "auto_scaffold":
        # Route the scaffold onto the existing helices as a single strand (seamed
        # Hamiltonian path by default; seamless = one end-crossover per helix pair).
        p["seamless"] = _as_bool(raw.get("seamless", False), key="seamless", where=here)
    elif op == "auto_crossover":
        # Place all compliant staple crossovers in bulk — no parameters.
        pass
    elif op == "full_autostaple":
        # One-click routing: assign the scaffold sequence + place crossovers +
        # tick-break/merge staples.  custom_sequence (when set) overrides scaffold_name.
        p["scaffold_name"] = _as_str(
            raw.get("scaffold_name", "M13mp18"), key="scaffold_name", where=here
        )
        if raw.get("custom_sequence") is not None:
            p["custom_sequence"] = _as_str(
                raw["custom_sequence"], key="custom_sequence", where=here
            )
        if raw.get("strand_id") is not None:
            p["strand_id"] = _as_str(raw["strand_id"], key="strand_id", where=here)
    elif op == "apply_loop_skips":
        # Bake every DeformationOp (and, on SQUARE, the periodic skips) into concrete
        # loop/skip marks — no parameters.  Requires crossovers already placed.
        pass
    else:  # bend / twist — a geometric DeformationOp between two bp planes
        p["plane_a_bp"] = _as_int(
            _get(raw, "plane_a_bp", where=here), key="plane_a_bp", where=here
        )
        p["plane_b_bp"] = _as_int(
            _get(raw, "plane_b_bp", where=here), key="plane_b_bp", where=here
        )
        if p["plane_a_bp"] < 0 or p["plane_b_bp"] < 0:
            raise BuildSpecError(f"{here}: plane bp indices must be ≥ 0")
        if p["plane_b_bp"] <= p["plane_a_bp"]:
            raise BuildSpecError(
                f"{here}: 'plane_b_bp' must be greater than 'plane_a_bp'"
            )
        if op == "bend":
            p["curvature_deg_per_bp"] = _as_num(
                _get(raw, "curvature_deg_per_bp", where=here),
                key="curvature_deg_per_bp",
                where=here,
            )
            p["direction_deg"] = _as_num(
                raw.get("direction_deg", 0.0), key="direction_deg", where=here
            )
        else:  # twist — exactly one of total_degrees / degrees_per_nm (mirrors add_twist's XOR)
            has_total = raw.get("total_degrees") is not None
            has_rate = raw.get("degrees_per_nm") is not None
            if has_total == has_rate:
                raise BuildSpecError(
                    f"{here}: pass exactly one of 'total_degrees' / 'degrees_per_nm'"
                )
            if has_total:
                p["total_degrees"] = _as_num(
                    raw["total_degrees"], key="total_degrees", where=here
                )
            else:
                p["degrees_per_nm"] = _as_num(
                    raw["degrees_per_nm"], key="degrees_per_nm", where=here
                )

    return BuildOp(op=op, params=p)


# ── declarative relaxed-structure constraints (AF-13 P3 → grammar) ─────────────

_CONSTRAINT_FIELD_KEYS = {
    "measure",
    "landmarks",
    "target_nm",
    "tol_nm",
    "min_confidence",
}
_LANDMARK_KEYS = {"helix", "bp_index", "direction"}


def _parse_constraint_landmark(raw, *, where: str) -> tuple:
    """A constraint landmark ``{helix: [r,c], bp_index, direction}`` → the AF-13 P3
    ``(hid, bp, direction)`` triple, with ``hid`` carrying the **grid_pos tuple**
    (the driver resolves it to a runtime helix id at build time).  The cell is a
    tuple so the whole triple stays hashable — ``parse_constraint_spec`` dedups the
    landmark list with ``set()``."""
    if not isinstance(raw, dict):
        raise BuildSpecError(
            f"{where}: a landmark must be an object {{helix, bp_index, direction}}, "
            f"got {raw!r}"
        )
    _require_keys(raw, _LANDMARK_KEYS, where=where)
    cell = _as_cell(_get(raw, "helix", where=where), where=where)
    bp = _as_int(_get(raw, "bp_index", where=where), key="bp_index", where=where)
    if bp < 0:
        raise BuildSpecError(f"{where}: 'bp_index' must be ≥ 0")
    direction = _as_direction(_get(raw, "direction", where=where), where=where)
    return (cell, bp, direction.value)


def _parse_design_constraint(raw, *, where: str) -> dict:
    """Validate one declarative relaxed-structure constraint → a normalised AF-13 P3
    constraint dict (landmark hids = grid_pos tuples, resolved by the driver).

    Shape::

        {"measure": "end_to_end",
         "landmarks": [{"helix": [r,c], "bp_index": int, "direction": "forward"}, …],
         "target_nm": num, "tol_nm": num, "min_confidence": int}

    The landmark cells are normalised here, then the whole constraint is handed to
    :func:`backend.core.oxdna_health.parse_constraint_spec` for the measure /
    landmark-arity / number / dedup checks (so a bad constraint fails at PARSE time,
    before any oxDNA run).  ``radius_of_gyration`` takes no landmarks."""
    if not isinstance(raw, dict):
        raise BuildSpecError(f"{where}: each constraint must be an object, got {raw!r}")
    _require_keys(raw, _CONSTRAINT_FIELD_KEYS, where=where)
    landmarks = [
        _parse_constraint_landmark(lm, where=f"{where}.landmarks[{i}]")
        for i, lm in enumerate(raw.get("landmarks") or [])
    ]
    core_spec = {k: v for k, v in raw.items() if k != "landmarks"}
    core_spec["landmarks"] = landmarks
    try:
        return parse_constraint_spec(core_spec)
    except ConstraintSpecError as e:
        raise BuildSpecError(f"{where}: {e}") from e


# ── declarative optimize block (AF-13 P5 — knob → iterate_to_constraint) ────────

_OPTIMIZE_KEYS = {"knob", "constraint"}
_KNOB_KEYS = {"op", "param", "lo", "hi", "initial", "response"}
_KNOB_RESPONSES = {"increasing", "decreasing"}


def _parse_knob(raw, ops: list[BuildOp], *, where: str) -> dict:
    """Validate the optimize ``knob`` → a normalised
    ``{op, param, lo, hi, initial, response}`` dict.

    ``op`` indexes into the design's ``ops`` and ``param`` must name a **numeric**
    parameter of that op (the scalar the loop varies — e.g. a ``bend`` op's
    ``curvature_deg_per_bp``).  ``lo``/``hi`` bracket the search; ``initial`` (default
    the bracket midpoint) seeds it.  ``response`` declares how the *measured* property
    moves as the knob **rises** — ``"decreasing"`` (a bend curvature whose end-to-end
    shrinks) or ``"increasing"``.  That sense is the spec author's **declaration**, not
    a geometric inference: the grammar never reasons about bend sign/handedness (the
    convergence magnitude is direction-agnostic), it just lowers the declared
    monotonicity to the bisection sense in the driver."""
    if not isinstance(raw, dict):
        raise BuildSpecError(f"{where}: 'knob' must be an object, got {raw!r}")
    _require_keys(raw, _KNOB_KEYS, where=where)
    op_idx = _as_int(_get(raw, "op", where=where), key="op", where=where)
    if not 0 <= op_idx < len(ops):
        raise BuildSpecError(
            f"{where}: 'op' index {op_idx} is out of range (0..{len(ops) - 1})"
        )
    param = _as_str(_get(raw, "param", where=where), key="param", where=where)
    target_op = ops[op_idx]
    if param not in target_op.params:
        raise BuildSpecError(
            f"{where}: 'param' {param!r} is not a parameter of op[{op_idx}] "
            f"({target_op.op!r}, has {sorted(target_op.params)})"
        )
    cur = target_op.params[param]
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        raise BuildSpecError(
            f"{where}: 'param' {param!r} of op[{op_idx}] is not numeric (is {cur!r}) "
            "— only a numeric parameter can be a knob"
        )
    lo = _as_num(_get(raw, "lo", where=where), key="lo", where=where)
    hi = _as_num(_get(raw, "hi", where=where), key="hi", where=where)
    if lo >= hi:
        raise BuildSpecError(f"{where}: 'lo' ({lo}) must be < 'hi' ({hi})")
    initial = (
        _as_num(raw["initial"], key="initial", where=where)
        if "initial" in raw
        else (lo + hi) / 2
    )
    if not lo <= initial <= hi:
        raise BuildSpecError(
            f"{where}: 'initial' ({initial}) must be within [lo, hi] = [{lo}, {hi}]"
        )
    response = _as_str(_get(raw, "response", where=where), key="response", where=where)
    if response not in _KNOB_RESPONSES:
        raise BuildSpecError(
            f"{where}: 'response' must be one of {sorted(_KNOB_RESPONSES)}, "
            f"got {response!r}"
        )
    return {
        "op": op_idx,
        "param": param,
        "lo": lo,
        "hi": hi,
        "initial": initial,
        "response": response,
    }


def _parse_optimize(raw, ops: list[BuildOp], *, where: str) -> dict:
    """Validate the optional top-level ``optimize`` block → ``{knob, constraint}``.

    The grammar's *constraint-driven* clause: the driver
    (:func:`backend.api.headless_spec_build.build_and_optimize_design`) varies ``knob``
    through the closed :func:`~backend.api.headless_oxdna_build.iterate_to_constraint`
    loop until ``constraint`` (a single AF-13 P3 relaxed-structure spec) is met.  Both
    halves are validated here so a malformed optimize block fails at PARSE time, before
    any expensive build/relax.  The knob references an op by index (so it must come
    after ``ops`` is parsed); the constraint's landmarks name helices by ``grid_pos``
    (resolved to runtime ids by the driver)."""
    if not isinstance(raw, dict):
        raise BuildSpecError(f"{where}: 'optimize' must be an object, got {raw!r}")
    _require_keys(raw, _OPTIMIZE_KEYS, where=where)
    knob = _parse_knob(_get(raw, "knob", where=where), ops, where=f"{where}.knob")
    constraint = _parse_design_constraint(
        _get(raw, "constraint", where=where), where=f"{where}.constraint"
    )
    return {"knob": knob, "constraint": constraint}


def parse_design_spec(spec, *, where: str = "design") -> DesignSpec:
    """Validate a design spec dict → :class:`DesignSpec` (lattice + ordered op list).

    Grammar::

        {
          "kind": "design",                # optional
          "lattice": "honeycomb"|"square", # optional, default honeycomb
          "ops": [
            {"op": "bundle",  "cells": [[r,c],…], "length_bp": int, …},
            {"op": "extrude", "cells": [[r,c],…], "length_bp": int, "offset_nm": num, …},
            {"op": "nick",    "helix": [r,c], "bp_index": int, "direction": "forward"},
            {"op": "ligate",  "helix": [r,c], "bp_index": int, "direction": "forward"},
            {"op": "loop_skip","helix": [r,c], "bp_index": int, "delta": -1|0|+1},
            {"op": "bend",    "plane_a_bp": int, "plane_b_bp": int,
             "curvature_deg_per_bp": num, "direction_deg": num},
            {"op": "twist",   "plane_a_bp": int, "plane_b_bp": int,
             "total_degrees": num | "degrees_per_nm": num},
            {"op": "circle_segment", "radius_nm": num, "plane": str,
             "offset_nm": num, …},
            {"op": "auto_scaffold", "seamless": bool},
            {"op": "auto_crossover"},
            {"op": "full_autostaple", "scaffold_name": str, …},
            {"op": "apply_loop_skips"}
          ],
          "constraints": [                 # optional, AF-13 P3 relaxed-structure gates
            {"measure": "end_to_end",
             "landmarks": [{"helix": [r,c], "bp_index": int, "direction": "forward"},
                           {"helix": [r,c], "bp_index": int, "direction": "forward"}],
             "target_nm": num, "tol_nm": num, "min_confidence": int}
          ],
          "optimize": {                    # optional, AF-13 P5 — knob → iterate loop
            "knob": {"op": int, "param": str, "lo": num, "hi": num,
                     "initial": num, "response": "increasing"|"decreasing"},
            "constraint": { <one AF-13 P3 constraint, as above> }
          }
        }

    The first op must be a *primordial* op — ``bundle`` or ``circle_segment`` (both
    create their own helices; ``extrude``/``nick``/``ligate``/``loop_skip``/``bend``/
    ``twist`` all need existing helices).  ``circle_segment`` places a parametric flat
    disc of ``radius_nm`` and **requires a ``square`` lattice** (its chord profile
    assumes the SQUARE column pitch) — a non-square lattice is rejected here.
    ``loop_skip`` adds a single
    length-changing mark on one helix at one bp (``delta`` ∈ {-1, 0, +1}; 0 removes
    an existing mark — the route's convention).  ``bend``/``twist`` add an *unscoped*
    geometric :class:`~backend.core.models.DeformationOp` between the two bp planes
    (auto-applies to every helix crossing both — helix/cluster scoping is deferred;
    it would need a grid_pos→id resolution the spec layer does not yet do).  A
    ``twist`` must carry exactly one of ``total_degrees`` / ``degrees_per_nm``.

    ``auto_scaffold`` / ``auto_crossover`` / ``full_autostaple`` are the bulk
    routing ops (route the scaffold, place all staple crossovers, one-click
    sequence+crossover+break respectively); ``apply_loop_skips`` bakes the design's
    deformation ops (and, on SQUARE, the periodic skips) into concrete loop/skip
    marks — it requires crossovers already placed (so it follows ``auto_crossover``
    or ``full_autostaple`` in the op list).  All four need existing helices/strands,
    so none may be the first op.

    An optional top-level ``constraints`` list carries declarative *relaxed-structure*
    gates (AF-13 P3): each is a ``{measure, landmarks, target_nm, tol_nm,
    min_confidence}`` spec whose landmarks name a helix by ``grid_pos`` (resolved to a
    runtime helix id by the driver).  They are validated here (via
    :func:`~backend.core.oxdna_health.parse_constraint_spec`) so a malformed
    constraint fails at parse time, and are *REPORTED* — not executed — by the driver
    :func:`backend.api.headless_spec_build.build_and_check_design` against an oxDNA
    relaxation.

    An optional top-level ``optimize`` block (AF-13 P5) carries a parametric ``knob``
    (an op-index + a numeric ``param`` to vary, a ``lo``/``hi`` bracket, and a declared
    monotone ``response``) plus a single ``constraint``.  The driver
    :func:`~backend.api.headless_spec_build.build_and_optimize_design` lowers it to the
    closed :func:`~backend.api.headless_oxdna_build.iterate_to_constraint` loop —
    rebuild with the knob, relax, measure, bisect — until the constraint is met.  It is
    validated here (knob index/param/bracket + the constraint) so a malformed optimize
    block fails at parse time.  Raises :class:`BuildSpecError` on any grammar violation.
    """
    if not isinstance(spec, dict):
        raise BuildSpecError(
            f"{where}: spec must be an object, got {type(spec).__name__}"
        )
    _require_keys(
        spec, {"kind", "lattice", "ops", "constraints", "optimize"}, where=where
    )
    kind = spec.get("kind", "design")
    if kind != "design":
        raise BuildSpecError(f"{where}: 'kind' must be 'design', got {kind!r}")

    lattice = _as_lattice(spec.get("lattice", "honeycomb"), where=where)
    raw_ops = _get(spec, "ops", where=where)
    if not isinstance(raw_ops, list) or not raw_ops:
        raise BuildSpecError(f"{where}: 'ops' must be a non-empty list")

    ops = [
        _parse_design_op(r, where=f"{where}.ops[{i}]") for i, r in enumerate(raw_ops)
    ]
    if ops[0].op not in _PRIMORDIAL_DESIGN_OPS:
        raise BuildSpecError(
            f"{where}: the first op must be 'bundle' or 'circle_segment' "
            f"(got {ops[0].op!r}) — extrude/nick/ligate/loop_skip/bend/twist/"
            "auto_scaffold/auto_crossover/full_autostaple/apply_loop_skips need "
            "existing helices"
        )
    if any(o.op == "circle_segment" for o in ops) and lattice is not LatticeType.SQUARE:
        raise BuildSpecError(
            f"{where}: 'circle_segment' requires a 'square' lattice (the chord "
            f"profile assumes the SQUARE column pitch), got {lattice.value.lower()!r}"
        )
    raw_constraints = spec.get("constraints") or []
    if not isinstance(raw_constraints, list):
        raise BuildSpecError(f"{where}: 'constraints' must be a list")
    constraints = [
        _parse_design_constraint(c, where=f"{where}.constraints[{i}]")
        for i, c in enumerate(raw_constraints)
    ]
    optimize = (
        None
        if spec.get("optimize") is None
        else _parse_optimize(spec["optimize"], ops, where=f"{where}.optimize")
    )
    return DesignSpec(
        lattice=lattice, ops=ops, constraints=constraints, optimize=optimize
    )


# ── assembly grammar ──────────────────────────────────────────────────────────

_ASSEMBLY_OP_KEYS = {
    "add_part": {"op", "part", "ref", "transform", "name", "connectors"},
    "place_grid": {
        "op",
        "part",
        "rows",
        "cols",
        "pitch",
        "row_pitch",
        "plane",
        "center",
        "name",
    },
    "place_ring": {
        "op",
        "part",
        "n",
        "radius",
        "plane",
        "start_angle_deg",
        "center",
        "name",
    },
    "mate": {
        "op",
        "child",
        "parent",
        "child_label",
        "parent_label",
        "joint_type",
        "ref",
        "name",
        "axis_origin",
        "axis_direction",
        "min_limit",
        "max_limit",
    },
    "gear": {"op", "joint_a", "joint_b", "ratio", "invert", "name"},
    "belt": {"op", "joint_a", "joint_b", "radius_a", "radius_b", "name"},
    "polymerize": {"op", "joint", "count", "direction"},
}
_CONNECTOR_KEYS = {"label", "position", "normal"}


def _parse_connectors(raw, *, where: str) -> list[dict]:
    if not isinstance(raw, list):
        raise BuildSpecError(f"{where}: 'connectors' must be a list")
    out = []
    for i, c in enumerate(raw):
        here = f"{where}.connectors[{i}]"
        if not isinstance(c, dict):
            raise BuildSpecError(f"{here}: a connector must be an object")
        _require_keys(c, _CONNECTOR_KEYS, where=here)
        out.append(
            {
                "label": _as_str(_get(c, "label", where=here), key="label", where=here),
                "position": _as_vec3(
                    _get(c, "position", where=here), key="position", where=here
                ),
                "normal": _as_vec3(
                    _get(c, "normal", where=here), key="normal", where=here
                ),
            }
        )
    return out


def _parse_assembly_op(raw, *, where: str) -> BuildOp:
    if not isinstance(raw, dict):
        raise BuildSpecError(f"{where}: each op must be an object, got {raw!r}")
    op = _get(raw, "op", where=where)
    if op not in _ASSEMBLY_OP_KEYS:
        raise BuildSpecError(
            f"{where}: unknown assembly op {op!r} — known: {sorted(_ASSEMBLY_OP_KEYS)}"
        )
    here = f"{where} op={op!r}"
    _require_keys(raw, _ASSEMBLY_OP_KEYS[op], where=here)
    p: dict = {}

    if op == "add_part":
        p["part"] = _as_str(_get(raw, "part", where=here), key="part", where=here)
        p["transform"] = _as_transform(raw.get("transform"), where=here)
        if "ref" in raw:
            p["ref"] = _as_str(raw["ref"], key="ref", where=here)
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
        p["connectors"] = (
            _parse_connectors(raw["connectors"], where=here)
            if "connectors" in raw
            else []
        )
    elif op == "place_grid":
        p["part"] = _as_str(_get(raw, "part", where=here), key="part", where=here)
        p["rows"] = _as_int(_get(raw, "rows", where=here), key="rows", where=here)
        p["cols"] = _as_int(_get(raw, "cols", where=here), key="cols", where=here)
        p["pitch"] = _as_num(_get(raw, "pitch", where=here), key="pitch", where=here)
        if p["rows"] <= 0 or p["cols"] <= 0:
            raise BuildSpecError(f"{here}: 'rows'/'cols' must be > 0")
        if p["pitch"] <= 0:
            raise BuildSpecError(f"{here}: 'pitch' must be > 0")
        if "row_pitch" in raw:
            p["row_pitch"] = _as_num(raw["row_pitch"], key="row_pitch", where=here)
        p["plane"] = _as_str(raw.get("plane", "XY"), key="plane", where=here)
        p["center"] = _as_bool(raw.get("center", False), key="center", where=here)
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
    elif op == "place_ring":
        p["part"] = _as_str(_get(raw, "part", where=here), key="part", where=here)
        p["n"] = _as_int(_get(raw, "n", where=here), key="n", where=here)
        p["radius"] = _as_num(_get(raw, "radius", where=here), key="radius", where=here)
        if p["n"] <= 0:
            raise BuildSpecError(f"{here}: 'n' must be > 0")
        if p["radius"] <= 0:
            raise BuildSpecError(f"{here}: 'radius' must be > 0")
        p["plane"] = _as_str(raw.get("plane", "XY"), key="plane", where=here)
        p["start_angle_deg"] = _as_num(
            raw.get("start_angle_deg", 0.0), key="start_angle_deg", where=here
        )
        p["center"] = (
            _as_vec3(raw["center"], key="center", where=here)
            if "center" in raw
            else (0.0, 0.0, 0.0)
        )
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
    elif op == "gear":
        # Couple two revolute mate-joints (referenced by their mate's ``ref`` key) at
        # a constant ratio — a display-layer kinematic relation, NOT a topology edit.
        # Both referenced mates must be 'revolute' (checked in parse_assembly_spec).
        p["joint_a"] = _as_str(
            _get(raw, "joint_a", where=here), key="joint_a", where=here
        )
        p["joint_b"] = _as_str(
            _get(raw, "joint_b", where=here), key="joint_b", where=here
        )
        p["ratio"] = _as_num(raw.get("ratio", 1.0), key="ratio", where=here)
        if p["ratio"] == 0:
            raise BuildSpecError(f"{here}: 'ratio' must be non-zero")
        p["invert"] = _as_bool(raw.get("invert", False), key="invert", where=here)
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
    elif op == "belt":
        # Wrap two revolute mate-joints (referenced by their mate's ``ref`` key) with
        # an open belt — a display-layer kinematic coupling at angular ratio
        # ``radius_a / radius_b``, NOT a topology edit.  Both referenced mates must be
        # 'revolute' (checked in parse_assembly_spec).
        p["joint_a"] = _as_str(
            _get(raw, "joint_a", where=here), key="joint_a", where=here
        )
        p["joint_b"] = _as_str(
            _get(raw, "joint_b", where=here), key="joint_b", where=here
        )
        p["radius_a"] = _as_num(
            _get(raw, "radius_a", where=here), key="radius_a", where=here
        )
        p["radius_b"] = _as_num(
            _get(raw, "radius_b", where=here), key="radius_b", where=here
        )
        if p["radius_a"] <= 0 or p["radius_b"] <= 0:
            raise BuildSpecError(f"{here}: 'radius_a'/'radius_b' must be > 0")
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
    elif op == "polymerize":
        # Grow a linear chain of identical parts from a SINGLE seed mate (referenced
        # by its ``ref`` key) — the chain marches along the seed mate's part-to-part
        # offset.  count is the total chain length (the seed pair already counts as 2).
        # Unlike gear/belt the seed mate may be ANY joint_type (rigid/revolute/…); the
        # only seed requirement (the two mated parts share a source design) is enforced
        # by the route at build time, not here.
        p["joint"] = _as_str(_get(raw, "joint", where=here), key="joint", where=here)
        p["count"] = _as_int(_get(raw, "count", where=here), key="count", where=here)
        if p["count"] < 2:
            raise BuildSpecError(
                f"{here}: 'count' must be ≥ 2 (the seed pair is already 2 parts), "
                f"got {p['count']}"
            )
        p["direction"] = _as_str(
            raw.get("direction", "forward"), key="direction", where=here
        )
        if p["direction"] not in ("forward", "backward", "both"):
            raise BuildSpecError(
                f"{here}: 'direction' must be 'forward', 'backward', or 'both', "
                f"got {p['direction']!r}"
            )
    else:  # mate
        p["child"] = _as_str(_get(raw, "child", where=here), key="child", where=here)
        p["parent"] = _as_str(_get(raw, "parent", where=here), key="parent", where=here)
        p["child_label"] = _as_str(
            _get(raw, "child_label", where=here), key="child_label", where=here
        )
        p["parent_label"] = _as_str(
            _get(raw, "parent_label", where=here), key="parent_label", where=here
        )
        p["joint_type"] = _as_str(
            raw.get("joint_type", "rigid"), key="joint_type", where=here
        )
        if "ref" in raw:
            p["ref"] = _as_str(raw["ref"], key="ref", where=here)
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
        if "axis_origin" in raw:
            p["axis_origin"] = _as_vec3(
                raw["axis_origin"], key="axis_origin", where=here
            )
        if "axis_direction" in raw:
            p["axis_direction"] = _as_vec3(
                raw["axis_direction"], key="axis_direction", where=here
            )
        if "min_limit" in raw and raw["min_limit"] is not None:
            p["min_limit"] = _as_num(raw["min_limit"], key="min_limit", where=here)
        if "max_limit" in raw and raw["max_limit"] is not None:
            p["max_limit"] = _as_num(raw["max_limit"], key="max_limit", where=here)

    return BuildOp(op=op, params=p)


_FILE_PART_KEYS = {"from_file"}
_PRIMITIVE_PART_KEYS = {"from_primitive", "params"}


def _parse_part(raw, *, where: str) -> DesignSpec | FilePart | PrimitivePart:
    """Parse one entry of an assembly's ``parts`` library → an inline :class:`DesignSpec`,
    a file-backed :class:`FilePart`, or a catalog-named :class:`PrimitivePart`.

    A ``{"from_file": "<path>"}`` object (AF-12) references a saved validated ``.nadoc``
    by path; a ``{"from_primitive": "<catalog name>"}`` object (AF-12 Phase 2) references a
    curated catalog primitive by name (resolved to its ``.nadoc`` at build time); anything
    else is parsed as an inline design spec.  The three are discriminated by the presence of
    the ``from_file`` / ``from_primitive`` key (a design spec is also an object, but carries
    ``ops`` not either key).  Name validity against the live catalog is checked at *build*
    time (the parser is catalog-agnostic), so an unknown name is a build-time error."""
    if isinstance(raw, dict) and "from_file" in raw:
        _require_keys(raw, _FILE_PART_KEYS, where=where)
        path = _as_str(
            _get(raw, "from_file", where=where), key="from_file", where=where
        )
        if not path.strip():
            raise BuildSpecError(
                f"{where}: 'from_file' must be a non-empty path string"
            )
        return FilePart(path=path)
    if isinstance(raw, dict) and "from_primitive" in raw:
        _require_keys(raw, _PRIMITIVE_PART_KEYS, where=where)
        name = _as_str(
            _get(raw, "from_primitive", where=where), key="from_primitive", where=where
        )
        if not name.strip():
            raise BuildSpecError(
                f"{where}: 'from_primitive' must be a non-empty catalog name string"
            )
        params: dict = {}
        if "params" in raw:
            raw_params = raw["params"]
            if not isinstance(raw_params, dict):
                raise BuildSpecError(
                    f"{where}: 'params' must be an object of primitive parameters, "
                    f"got {raw_params!r}"
                )
            params = {
                str(k): _as_num(v, key=f"params.{k}", where=where)
                for k, v in raw_params.items()
            }
        return PrimitivePart(name=name, params=params)
    return parse_design_spec(raw, where=where)


def parse_assembly_spec(spec, *, where: str = "assembly") -> AssemblySpec:
    """Validate an assembly spec dict → :class:`AssemblySpec`.

    Grammar::

        {
          "kind": "assembly",            # optional
          "name": "My assembly",         # optional
          "parts": { "<key>": <design-spec> | {"from_file": "<path>"}
                              | {"from_primitive": "<catalog name>"[, "params": {…}]}, … },  # part library
          "ops": [
            {"op": "add_part",  "part": "<key>", "ref": "<inst-key>",
             "transform": [x,y,z]|[16 floats]|null, "connectors": [{label,position,normal}]},
            {"op": "place_grid","part": "<key>", "rows": int, "cols": int, "pitch": num, …},
            {"op": "place_ring","part": "<key>", "n": int, "radius": num, …},
            {"op": "mate", "child": "<inst-key>", "parent": "<inst-key>",
             "child_label": str, "parent_label": str, "joint_type": "rigid"|"revolute"|…,
             "ref": "<joint-key>"},
            {"op": "gear", "joint_a": "<joint-key>", "joint_b": "<joint-key>",
             "ratio": num, "invert": bool},
            {"op": "belt", "joint_a": "<joint-key>", "joint_b": "<joint-key>",
             "radius_a": num, "radius_b": num},
            {"op": "polymerize", "joint": "<joint-key>", "count": int,
             "direction": "forward"|"backward"|"both"}
          ]
        }

    Beyond shape/type checks, the parser enforces **referential integrity**: every
    ``part`` names a defined part; every ``mate`` endpoint names an instance defined
    by a prior ``add_part`` ``ref``; each mate ``*_label`` names a connector that
    endpoint actually declares; every ``gear``/``belt`` ``joint_*`` names a joint
    defined by a prior ``mate`` ``ref`` **that is revolute** (a gear/belt couples two
    revolute joints — the route 400s otherwise, caught here at parse time); and a
    ``polymerize`` ``joint`` names a joint defined by a prior ``mate`` ``ref`` (of
    *any* joint_type — polymerize replicates a single seed mate; the route's own
    requirement that the seed mate joins two source-identical parts is enforced at
    build time).  So a structurally-impossible assembly fails at parse time, before
    any build runs.  Raises :class:`BuildSpecError` on any violation.
    """
    if not isinstance(spec, dict):
        raise BuildSpecError(
            f"{where}: spec must be an object, got {type(spec).__name__}"
        )
    _require_keys(spec, {"kind", "name", "parts", "ops"}, where=where)
    kind = spec.get("kind", "assembly")
    if kind != "assembly":
        raise BuildSpecError(f"{where}: 'kind' must be 'assembly', got {kind!r}")

    name = _as_str(spec.get("name", "Untitled"), key="name", where=where)
    raw_parts = _get(spec, "parts", where=where)
    if not isinstance(raw_parts, dict) or not raw_parts:
        raise BuildSpecError(
            f"{where}: 'parts' must be a non-empty object of part specs"
        )
    parts = {
        key: _parse_part(ds, where=f"{where}.parts[{key!r}]")
        for key, ds in raw_parts.items()
    }

    raw_ops = _get(spec, "ops", where=where)
    if not isinstance(raw_ops, list) or not raw_ops:
        raise BuildSpecError(f"{where}: 'ops' must be a non-empty list")
    ops = [
        _parse_assembly_op(r, where=f"{where}.ops[{i}]") for i, r in enumerate(raw_ops)
    ]

    # referential integrity: part refs resolve, mate endpoints + labels resolve,
    # gear joints resolve to prior revolute mates.
    defined: dict[str, set] = {}  # instance-ref-key → declared connector labels
    defined_joints: dict[str, str] = {}  # joint-ref-key → that mate's joint_type
    for i, opn in enumerate(ops):
        loc = f"{where}.ops[{i}] op={opn.op!r}"
        p = opn.params
        if opn.op in ("add_part", "place_grid", "place_ring"):
            if p["part"] not in parts:
                raise BuildSpecError(
                    f"{loc}: references part {p['part']!r} which is not in 'parts' "
                    f"({sorted(parts)})"
                )
            # A file-backed part may be placed by add_part (one reference) OR by
            # place_grid/place_ring (the driver loops add_file_instance with per-slot
            # transforms — AF-12 follow-up — so the saved validated .nadoc travels as a
            # path reference per slot, not rows·cols embedded copies).
        if opn.op == "add_part" and "ref" in p:
            if p["ref"] in defined:
                raise BuildSpecError(f"{loc}: duplicate instance ref {p['ref']!r}")
            defined[p["ref"]] = {c["label"] for c in p["connectors"]}
        if opn.op == "mate":
            for side in ("child", "parent"):
                ref = p[side]
                if ref not in defined:
                    raise BuildSpecError(
                        f"{loc}: mate {side} {ref!r} was not defined by a prior "
                        f"add_part ref ({sorted(defined)})"
                    )
                label = p[f"{side}_label"]
                if label not in defined[ref]:
                    raise BuildSpecError(
                        f"{loc}: mate {side}_label {label!r} is not a connector on "
                        f"instance {ref!r} (has {sorted(defined[ref])})"
                    )
            if "ref" in p:
                if p["ref"] in defined_joints:
                    raise BuildSpecError(f"{loc}: duplicate joint ref {p['ref']!r}")
                defined_joints[p["ref"]] = p["joint_type"]
        if opn.op in ("gear", "belt"):
            for side in ("joint_a", "joint_b"):
                jref = p[side]
                if jref not in defined_joints:
                    raise BuildSpecError(
                        f"{loc}: {opn.op} {side} {jref!r} was not defined by a prior "
                        f"mate ref ({sorted(defined_joints)})"
                    )
                if defined_joints[jref] != "revolute":
                    raise BuildSpecError(
                        f"{loc}: {opn.op} {side} {jref!r} mate must be 'revolute' "
                        f"(is {defined_joints[jref]!r}) — a {opn.op} couples two revolute joints"
                    )
        if opn.op == "polymerize":
            jref = p["joint"]
            if jref not in defined_joints:
                raise BuildSpecError(
                    f"{loc}: polymerize joint {jref!r} was not defined by a prior "
                    f"mate ref ({sorted(defined_joints)})"
                )

    return AssemblySpec(name=name, parts=parts, ops=ops)
