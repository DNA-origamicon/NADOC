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
  ``bend`` · ``twist`` · ``circle_segment``
* **assembly** ops — ``add_part`` · ``place_grid`` · ``place_ring`` · ``mate`` ·
  ``gear`` · ``belt``

Helices are referenced declaratively by their lattice ``grid_pos`` ``[row, col]``
(stable across id schemes), assembly instances by a spec-assigned ``ref`` key, and
the joints a ``mate`` creates by an optional ``ref`` key a ``gear`` then couples — so
a spec never needs a runtime-generated id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.models import Direction, LatticeType


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
    """A parsed design spec: a lattice + an ordered op list (first op is a bundle)."""

    lattice: LatticeType
    ops: list[BuildOp]


@dataclass
class AssemblySpec:
    """A parsed assembly spec: a name, a library of parsed part design specs (by key),
    and an ordered op list referencing those parts."""

    name: str
    parts: dict[str, DesignSpec]
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
    return (_as_int(v[0], key="cell.row", where=where), _as_int(v[1], key="cell.col", where=where))


def _as_cells(v, *, where: str) -> list[tuple[int, int]]:
    if not isinstance(v, (list, tuple)) or not v:
        raise BuildSpecError(f"{where}: 'cells' must be a non-empty list of [row, col] pairs")
    return [_as_cell(c, where=where) for c in v]


def _as_vec3(v, *, key: str, where: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise BuildSpecError(f"{where}: field {key!r} must be a 3-number vector, got {v!r}")
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
        return {"kind": "translation", "values": _as_vec3(v, key="transform", where=where)}
    if len(v) == 16:
        return {"kind": "matrix",
                "values": [_as_num(x, key="transform", where=where) for x in v]}
    raise BuildSpecError(
        f"{where}: 'transform' must have 3 (translation) or 16 (matrix) entries, "
        f"got {len(v)}"
    )


# ── design grammar ────────────────────────────────────────────────────────────

_DESIGN_OP_KEYS = {
    "bundle": {"op", "cells", "length_bp", "plane", "name", "strand_filter", "ligate_adjacent"},
    "extrude": {"op", "cells", "length_bp", "offset_nm", "plane", "strand_filter",
                "extend_inplace", "ligate_adjacent"},
    "nick": {"op", "helix", "bp_index", "direction"},
    "ligate": {"op", "helix", "bp_index", "direction"},
    "loop_skip": {"op", "helix", "bp_index", "delta"},
    "bend": {"op", "plane_a_bp", "plane_b_bp", "curvature_deg_per_bp", "direction_deg"},
    "twist": {"op", "plane_a_bp", "plane_b_bp", "total_degrees", "degrees_per_nm"},
    "circle_segment": {"op", "radius_nm", "plane", "offset_nm", "strand_filter",
                       "ligate_adjacent", "min_chord_bp"},
}

# Ops that create their own helices from scratch → may be the FIRST op (all others
# need existing helices to extrude/nick/ligate/deform).
_PRIMORDIAL_DESIGN_OPS = {"bundle", "circle_segment"}


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
        p["length_bp"] = _as_int(_get(raw, "length_bp", where=here), key="length_bp", where=here)
        if p["length_bp"] == 0:
            raise BuildSpecError(f"{here}: 'length_bp' must be non-zero")
        p["plane"] = _as_str(raw.get("plane", "XY"), key="plane", where=here)
        p["strand_filter"] = _as_str(raw.get("strand_filter", "both"), key="strand_filter", where=here)
        p["ligate_adjacent"] = _as_bool(raw.get("ligate_adjacent", True), key="ligate_adjacent", where=here)
        if op == "extrude":
            p["offset_nm"] = _as_num(_get(raw, "offset_nm", where=here), key="offset_nm", where=here)
            p["extend_inplace"] = _as_bool(raw.get("extend_inplace", True), key="extend_inplace", where=here)
    elif op in ("nick", "ligate"):
        p["helix"] = _as_cell(_get(raw, "helix", where=here), where=here)
        p["bp_index"] = _as_int(_get(raw, "bp_index", where=here), key="bp_index", where=here)
        if p["bp_index"] < 0:
            raise BuildSpecError(f"{here}: 'bp_index' must be ≥ 0")
        p["direction"] = _as_direction(_get(raw, "direction", where=here), where=here)
    elif op == "loop_skip":
        # A single loop (+1, extra base) / skip (−1, deleted base) / removal (0) on
        # one helix at one bp — a length-changing mark on Helix.loop_skips (outside
        # the strand graph).  delta is route-constrained to {-1, 0, +1}.
        p["helix"] = _as_cell(_get(raw, "helix", where=here), where=here)
        p["bp_index"] = _as_int(_get(raw, "bp_index", where=here), key="bp_index", where=here)
        if p["bp_index"] < 0:
            raise BuildSpecError(f"{here}: 'bp_index' must be ≥ 0")
        p["delta"] = _as_int(_get(raw, "delta", where=here), key="delta", where=here)
        if p["delta"] not in (-1, 0, 1):
            raise BuildSpecError(
                f"{here}: 'delta' must be -1 (skip), 0 (remove), or +1 (loop), "
                f"got {p['delta']}"
            )
    elif op == "circle_segment":
        # A parametric flat disc: a SQUARE-lattice row of helices whose per-cell
        # lengths trace a circle of radius_nm (the chord profile assumes the SQUARE
        # column pitch — enforced at the spec level in parse_design_spec).  Builds
        # its own helices, so it may be the first op.
        p["radius_nm"] = _as_num(_get(raw, "radius_nm", where=here), key="radius_nm", where=here)
        if p["radius_nm"] <= 0:
            raise BuildSpecError(f"{here}: 'radius_nm' must be > 0")
        p["plane"] = _as_str(raw.get("plane", "XY"), key="plane", where=here)
        p["offset_nm"] = _as_num(raw.get("offset_nm", 0.0), key="offset_nm", where=here)
        p["strand_filter"] = _as_str(raw.get("strand_filter", "both"), key="strand_filter", where=here)
        p["ligate_adjacent"] = _as_bool(raw.get("ligate_adjacent", True), key="ligate_adjacent", where=here)
        if "min_chord_bp" in raw:
            p["min_chord_bp"] = _as_int(raw["min_chord_bp"], key="min_chord_bp", where=here)
    else:  # bend / twist — a geometric DeformationOp between two bp planes
        p["plane_a_bp"] = _as_int(_get(raw, "plane_a_bp", where=here), key="plane_a_bp", where=here)
        p["plane_b_bp"] = _as_int(_get(raw, "plane_b_bp", where=here), key="plane_b_bp", where=here)
        if p["plane_a_bp"] < 0 or p["plane_b_bp"] < 0:
            raise BuildSpecError(f"{here}: plane bp indices must be ≥ 0")
        if p["plane_b_bp"] <= p["plane_a_bp"]:
            raise BuildSpecError(f"{here}: 'plane_b_bp' must be greater than 'plane_a_bp'")
        if op == "bend":
            p["curvature_deg_per_bp"] = _as_num(
                _get(raw, "curvature_deg_per_bp", where=here),
                key="curvature_deg_per_bp", where=here,
            )
            p["direction_deg"] = _as_num(raw.get("direction_deg", 0.0), key="direction_deg", where=here)
        else:  # twist — exactly one of total_degrees / degrees_per_nm (mirrors add_twist's XOR)
            has_total = raw.get("total_degrees") is not None
            has_rate = raw.get("degrees_per_nm") is not None
            if has_total == has_rate:
                raise BuildSpecError(
                    f"{here}: pass exactly one of 'total_degrees' / 'degrees_per_nm'"
                )
            if has_total:
                p["total_degrees"] = _as_num(raw["total_degrees"], key="total_degrees", where=here)
            else:
                p["degrees_per_nm"] = _as_num(raw["degrees_per_nm"], key="degrees_per_nm", where=here)

    return BuildOp(op=op, params=p)


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
             "offset_nm": num, …}
          ]
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
    Raises :class:`BuildSpecError` on any grammar violation.
    """
    if not isinstance(spec, dict):
        raise BuildSpecError(f"{where}: spec must be an object, got {type(spec).__name__}")
    _require_keys(spec, {"kind", "lattice", "ops"}, where=where)
    kind = spec.get("kind", "design")
    if kind != "design":
        raise BuildSpecError(f"{where}: 'kind' must be 'design', got {kind!r}")

    lattice = _as_lattice(spec.get("lattice", "honeycomb"), where=where)
    raw_ops = _get(spec, "ops", where=where)
    if not isinstance(raw_ops, list) or not raw_ops:
        raise BuildSpecError(f"{where}: 'ops' must be a non-empty list")

    ops = [_parse_design_op(r, where=f"{where}.ops[{i}]") for i, r in enumerate(raw_ops)]
    if ops[0].op not in _PRIMORDIAL_DESIGN_OPS:
        raise BuildSpecError(
            f"{where}: the first op must be 'bundle' or 'circle_segment' "
            f"(got {ops[0].op!r}) — extrude/nick/ligate/loop_skip/bend/twist need "
            "existing helices"
        )
    if (any(o.op == "circle_segment" for o in ops)
            and lattice is not LatticeType.SQUARE):
        raise BuildSpecError(
            f"{where}: 'circle_segment' requires a 'square' lattice (the chord "
            f"profile assumes the SQUARE column pitch), got {lattice.value.lower()!r}"
        )
    return DesignSpec(lattice=lattice, ops=ops)


# ── assembly grammar ──────────────────────────────────────────────────────────

_ASSEMBLY_OP_KEYS = {
    "add_part": {"op", "part", "ref", "transform", "name", "connectors"},
    "place_grid": {"op", "part", "rows", "cols", "pitch", "row_pitch", "plane", "center", "name"},
    "place_ring": {"op", "part", "n", "radius", "plane", "start_angle_deg", "center", "name"},
    "mate": {"op", "child", "parent", "child_label", "parent_label", "joint_type",
             "ref", "name", "axis_origin", "axis_direction", "min_limit", "max_limit"},
    "gear": {"op", "joint_a", "joint_b", "ratio", "invert", "name"},
    "belt": {"op", "joint_a", "joint_b", "radius_a", "radius_b", "name"},
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
        out.append({
            "label": _as_str(_get(c, "label", where=here), key="label", where=here),
            "position": _as_vec3(_get(c, "position", where=here), key="position", where=here),
            "normal": _as_vec3(_get(c, "normal", where=here), key="normal", where=here),
        })
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
        p["connectors"] = _parse_connectors(raw["connectors"], where=here) if "connectors" in raw else []
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
        p["start_angle_deg"] = _as_num(raw.get("start_angle_deg", 0.0), key="start_angle_deg", where=here)
        p["center"] = _as_vec3(raw["center"], key="center", where=here) if "center" in raw else (0.0, 0.0, 0.0)
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
    elif op == "gear":
        # Couple two revolute mate-joints (referenced by their mate's ``ref`` key) at
        # a constant ratio — a display-layer kinematic relation, NOT a topology edit.
        # Both referenced mates must be 'revolute' (checked in parse_assembly_spec).
        p["joint_a"] = _as_str(_get(raw, "joint_a", where=here), key="joint_a", where=here)
        p["joint_b"] = _as_str(_get(raw, "joint_b", where=here), key="joint_b", where=here)
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
        p["joint_a"] = _as_str(_get(raw, "joint_a", where=here), key="joint_a", where=here)
        p["joint_b"] = _as_str(_get(raw, "joint_b", where=here), key="joint_b", where=here)
        p["radius_a"] = _as_num(_get(raw, "radius_a", where=here), key="radius_a", where=here)
        p["radius_b"] = _as_num(_get(raw, "radius_b", where=here), key="radius_b", where=here)
        if p["radius_a"] <= 0 or p["radius_b"] <= 0:
            raise BuildSpecError(f"{here}: 'radius_a'/'radius_b' must be > 0")
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
    else:  # mate
        p["child"] = _as_str(_get(raw, "child", where=here), key="child", where=here)
        p["parent"] = _as_str(_get(raw, "parent", where=here), key="parent", where=here)
        p["child_label"] = _as_str(_get(raw, "child_label", where=here), key="child_label", where=here)
        p["parent_label"] = _as_str(_get(raw, "parent_label", where=here), key="parent_label", where=here)
        p["joint_type"] = _as_str(raw.get("joint_type", "rigid"), key="joint_type", where=here)
        if "ref" in raw:
            p["ref"] = _as_str(raw["ref"], key="ref", where=here)
        if "name" in raw:
            p["name"] = _as_str(raw["name"], key="name", where=here)
        if "axis_origin" in raw:
            p["axis_origin"] = _as_vec3(raw["axis_origin"], key="axis_origin", where=here)
        if "axis_direction" in raw:
            p["axis_direction"] = _as_vec3(raw["axis_direction"], key="axis_direction", where=here)
        if "min_limit" in raw and raw["min_limit"] is not None:
            p["min_limit"] = _as_num(raw["min_limit"], key="min_limit", where=here)
        if "max_limit" in raw and raw["max_limit"] is not None:
            p["max_limit"] = _as_num(raw["max_limit"], key="max_limit", where=here)

    return BuildOp(op=op, params=p)


def parse_assembly_spec(spec, *, where: str = "assembly") -> AssemblySpec:
    """Validate an assembly spec dict → :class:`AssemblySpec`.

    Grammar::

        {
          "kind": "assembly",            # optional
          "name": "My assembly",         # optional
          "parts": { "<key>": <design-spec>, … },   # named part library
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
             "radius_a": num, "radius_b": num}
          ]
        }

    Beyond shape/type checks, the parser enforces **referential integrity**: every
    ``part`` names a defined part; every ``mate`` endpoint names an instance defined
    by a prior ``add_part`` ``ref``; each mate ``*_label`` names a connector that
    endpoint actually declares; and every ``gear``/``belt`` ``joint_*`` names a joint
    defined by a prior ``mate`` ``ref`` **that is revolute** (a gear/belt couples two
    revolute joints — the route 400s otherwise, caught here at parse time).  So a
    structurally-impossible assembly fails at parse time, before any build runs.
    Raises :class:`BuildSpecError` on any violation.
    """
    if not isinstance(spec, dict):
        raise BuildSpecError(f"{where}: spec must be an object, got {type(spec).__name__}")
    _require_keys(spec, {"kind", "name", "parts", "ops"}, where=where)
    kind = spec.get("kind", "assembly")
    if kind != "assembly":
        raise BuildSpecError(f"{where}: 'kind' must be 'assembly', got {kind!r}")

    name = _as_str(spec.get("name", "Untitled"), key="name", where=where)
    raw_parts = _get(spec, "parts", where=where)
    if not isinstance(raw_parts, dict) or not raw_parts:
        raise BuildSpecError(f"{where}: 'parts' must be a non-empty object of part specs")
    parts = {
        key: parse_design_spec(ds, where=f"{where}.parts[{key!r}]")
        for key, ds in raw_parts.items()
    }

    raw_ops = _get(spec, "ops", where=where)
    if not isinstance(raw_ops, list) or not raw_ops:
        raise BuildSpecError(f"{where}: 'ops' must be a non-empty list")
    ops = [_parse_assembly_op(r, where=f"{where}.ops[{i}]") for i, r in enumerate(raw_ops)]

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

    return AssemblySpec(name=name, parts=parts, ops=ops)
