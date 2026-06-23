"""Pure grammar/parser tests for the declarative build-spec (AF-11).

``backend.core.build_spec`` is the HTTP-free, execution-free half of the
interpreter: spec dict in → ordered ``BuildOp`` list out, or ``BuildSpecError`` on a
malformed spec.  These pin the grammar exhaustively (valid specs normalise correctly;
malformed specs are rejected at parse time, before any build) — the strong contract
the driver leans on so it only ever sees a well-formed op list.
"""
from __future__ import annotations

import pytest

from backend.core.build_spec import (
    BuildSpecError,
    FilePart,
    parse_assembly_spec,
    parse_design_spec,
)
from backend.core.models import Direction, LatticeType


# ── design grammar: happy path + normalisation ────────────────────────────────

def test_design_spec_normalises_lattice_and_ops():
    parsed = parse_design_spec({
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": [[0, 0], [0, 1]], "length_bp": 42, "name": "b"},
            {"op": "extrude", "cells": [[0, 0]], "length_bp": 21, "offset_nm": 14.28},
            {"op": "nick", "helix": [0, 0], "bp_index": 20, "direction": "reverse"},
            {"op": "ligate", "helix": [0, 0], "bp_index": 20, "direction": "FORWARD"},
        ],
    })
    assert parsed.lattice is LatticeType.SQUARE
    assert [o.op for o in parsed.ops] == ["bundle", "extrude", "nick", "ligate"]
    # cells normalised to (row, col) int tuples
    assert parsed.ops[0].params["cells"] == [(0, 0), (0, 1)]
    # defaults filled
    assert parsed.ops[0].params["plane"] == "XY"
    assert parsed.ops[0].params["ligate_adjacent"] is True
    # direction coerced to the enum, case-insensitively
    assert parsed.ops[2].params["direction"] is Direction.REVERSE
    assert parsed.ops[3].params["direction"] is Direction.FORWARD


def test_design_spec_defaults_lattice_to_honeycomb():
    parsed = parse_design_spec({"ops": [{"op": "bundle", "cells": [[0, 1]], "length_bp": 42}]})
    assert parsed.lattice is LatticeType.HONEYCOMB


def test_design_spec_normalises_loop_skip():
    parsed = parse_design_spec({"ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
        {"op": "loop_skip", "helix": [0, 0], "bp_index": 14, "delta": 1},
        {"op": "loop_skip", "helix": [0, 0], "bp_index": 20, "delta": -1},
        {"op": "loop_skip", "helix": [0, 0], "bp_index": 14, "delta": 0},
    ]})
    assert [o.op for o in parsed.ops] == ["bundle", "loop_skip", "loop_skip", "loop_skip"]
    # helix normalised to an (row, col) int tuple; delta preserved verbatim
    assert parsed.ops[1].params["helix"] == (0, 0)
    assert parsed.ops[1].params["delta"] == 1
    assert parsed.ops[2].params["delta"] == -1
    assert parsed.ops[3].params["delta"] == 0


def test_design_spec_normalises_bend_and_twist():
    parsed = parse_design_spec({"ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 84},
        {"op": "bend", "plane_a_bp": 20, "plane_b_bp": 60, "curvature_deg_per_bp": 2.0},
        {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60, "total_degrees": 90},
        {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60, "degrees_per_nm": 30},
    ]})
    assert [o.op for o in parsed.ops] == ["bundle", "bend", "twist", "twist"]
    bend = parsed.ops[1].params
    assert bend["curvature_deg_per_bp"] == 2.0
    assert bend["direction_deg"] == 0.0  # default filled
    # twist carries exactly the one rate it was given, coerced to float
    assert parsed.ops[2].params["total_degrees"] == 90.0
    assert "degrees_per_nm" not in parsed.ops[2].params
    assert parsed.ops[3].params["degrees_per_nm"] == 30.0
    assert "total_degrees" not in parsed.ops[3].params


def test_design_spec_normalises_circle_segment():
    """circle_segment is a primordial op (may be first) and fills its defaults."""
    parsed = parse_design_spec({"lattice": "square", "ops": [
        {"op": "circle_segment", "radius_nm": 10.6}]})
    assert parsed.lattice is LatticeType.SQUARE
    assert [o.op for o in parsed.ops] == ["circle_segment"]
    p = parsed.ops[0].params
    assert p["radius_nm"] == 10.6
    assert p["plane"] == "XY"            # defaults filled
    assert p["offset_nm"] == 0.0
    assert p["strand_filter"] == "both"
    assert p["ligate_adjacent"] is True
    assert "min_chord_bp" not in p       # optional, omitted by default


def test_design_spec_normalises_routing_ops():
    """The bulk routing ops parse with their defaults filled / fields preserved."""
    parsed = parse_design_spec({"lattice": "square", "ops": [
        {"op": "bundle", "cells": [[0, 0], [0, 1]], "length_bp": 96},
        {"op": "auto_scaffold", "seamless": True},
        {"op": "auto_crossover"},
        {"op": "full_autostaple", "scaffold_name": "p7560"},
        {"op": "apply_loop_skips"},
    ]})
    assert [o.op for o in parsed.ops] == [
        "bundle", "auto_scaffold", "auto_crossover", "full_autostaple", "apply_loop_skips"]
    assert parsed.ops[1].params["seamless"] is True
    assert parsed.ops[2].params == {}                       # no params beyond op
    assert parsed.ops[3].params["scaffold_name"] == "p7560"
    assert "custom_sequence" not in parsed.ops[3].params    # optional, omitted
    assert parsed.ops[4].params == {}


def test_design_spec_routing_ops_defaults():
    """auto_scaffold defaults to seamed; full_autostaple to M13mp18."""
    parsed = parse_design_spec({"lattice": "square", "ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 96},
        {"op": "auto_scaffold"},
        {"op": "full_autostaple"},
    ]})
    assert parsed.ops[1].params["seamless"] is False
    assert parsed.ops[2].params["scaffold_name"] == "M13mp18"


def test_design_spec_normalises_constraints():
    """A design spec's optional ``constraints`` block parses + normalises to AF-13 P3
    constraint dicts (landmark hids = grid_pos tuples the driver resolves)."""
    parsed = parse_design_spec({
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
        "constraints": [
            {"measure": "end_to_end",
             "landmarks": [{"helix": [0, 0], "bp_index": 0, "direction": "forward"},
                           {"helix": [0, 0], "bp_index": 40, "direction": "FORWARD"}],
             "target_nm": 13.6, "tol_nm": 0.5},
            {"measure": "radius_of_gyration", "target_nm": 4.0, "tol_nm": 1.0,
             "min_confidence": 25},
        ],
    })
    assert len(parsed.constraints) == 2
    c0 = parsed.constraints[0]
    assert c0["measure"] == "end_to_end"
    # landmark helix cells normalised to (row, col) tuples; direction → string value
    assert c0["landmarks"] == [((0, 0), 0, "FORWARD"), ((0, 0), 40, "FORWARD")]
    assert c0["min_confidence"] == 50            # AF-13 P3 default (RMSF_PRELIM_FRAMES)
    # radius_of_gyration takes no landmarks; explicit min_confidence honoured
    assert parsed.constraints[1]["landmarks"] == []
    assert parsed.constraints[1]["min_confidence"] == 25


def test_design_spec_defaults_to_no_constraints():
    parsed = parse_design_spec({"ops": [{"op": "bundle", "cells": [[0, 1]], "length_bp": 42}]})
    assert parsed.constraints == []


# ── optimize block grammar (AF-13 P5 — knob → iterate_to_constraint) ───────────

def _optimize_ops():
    return [{"op": "bundle", "cells": [[0, 0], [0, 1]], "length_bp": 42},
            {"op": "bend", "plane_a_bp": 2, "plane_b_bp": 39,
             "curvature_deg_per_bp": 2.0}]


def test_design_spec_normalises_optimize():
    """A design spec's optional ``optimize`` block parses → {knob, constraint}: the knob
    references an op by index + a numeric param, the constraint is an AF-13 P3 spec
    (landmarks the driver resolves)."""
    parsed = parse_design_spec({
        "lattice": "honeycomb",
        "ops": _optimize_ops(),
        "optimize": {
            "knob": {"op": 1, "param": "curvature_deg_per_bp",
                     "lo": 0.0, "hi": 4.0, "initial": 2.0, "response": "decreasing"},
            "constraint": {"measure": "end_to_end",
                           "landmarks": [{"helix": [0, 0], "bp_index": 0, "direction": "forward"},
                                         {"helix": [0, 1], "bp_index": 41, "direction": "reverse"}],
                           "target_nm": 12.0, "tol_nm": 0.5},
        },
    })
    opt = parsed.optimize
    assert opt is not None
    assert opt["knob"] == {"op": 1, "param": "curvature_deg_per_bp",
                           "lo": 0.0, "hi": 4.0, "initial": 2.0, "response": "decreasing"}
    # the constraint is a fully-parsed AF-13 P3 dict (landmarks → grid_pos tuples)
    assert opt["constraint"]["measure"] == "end_to_end"
    assert opt["constraint"]["landmarks"][0] == ((0, 0), 0, "FORWARD")
    assert opt["constraint"]["landmarks"][1] == ((0, 1), 41, "REVERSE")


def test_design_spec_optimize_defaults_initial_to_midpoint():
    """``initial`` is optional — it defaults to the bracket midpoint."""
    parsed = parse_design_spec({
        "ops": _optimize_ops(),
        "optimize": {
            "knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 1.0, "hi": 3.0,
                     "response": "decreasing"},
            "constraint": {"measure": "radius_of_gyration", "target_nm": 5.0, "tol_nm": 1.0},
        },
    })
    assert parsed.optimize["knob"]["initial"] == 2.0   # (lo + hi) / 2


def test_design_spec_defaults_to_no_optimize():
    parsed = parse_design_spec({"ops": [{"op": "bundle", "cells": [[0, 1]], "length_bp": 42}]})
    assert parsed.optimize is None


@pytest.mark.parametrize("opt,match", [
    # knob op index out of range
    ({"knob": {"op": 5, "param": "curvature_deg_per_bp", "lo": 0, "hi": 4, "response": "decreasing"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "out of range"),
    # knob param names something that isn't a parameter of that op
    ({"knob": {"op": 1, "param": "wibble", "lo": 0, "hi": 4, "response": "decreasing"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "not a parameter"),
    # knob param is non-numeric (a bundle's 'plane' is a string → can't be a knob)
    ({"knob": {"op": 0, "param": "plane", "lo": 0, "hi": 4, "response": "decreasing"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "not numeric"),
    # lo must be < hi
    ({"knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 4, "hi": 1, "response": "decreasing"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "must be <"),
    # initial outside the bracket
    ({"knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 0, "hi": 4, "initial": 9,
               "response": "decreasing"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "within"),
    # unknown response
    ({"knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 0, "hi": 4, "response": "sideways"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "response"),
    # typo'd knob field
    ({"knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 0, "hi": 4, "responce": "decreasing"},
      "constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}}, "unknown field"),
    # optimize missing its knob
    ({"constraint": {"measure": "radius_of_gyration", "target_nm": 5, "tol_nm": 1}},
     "missing required field 'knob'"),
    # optimize missing its constraint
    ({"knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 0, "hi": 4, "response": "decreasing"}},
     "missing required field 'constraint'"),
    # a malformed constraint inside optimize propagates the AF-13 P3 rejection
    ({"knob": {"op": 1, "param": "curvature_deg_per_bp", "lo": 0, "hi": 4, "response": "decreasing"},
      "constraint": {"measure": "wibble", "target_nm": 5, "tol_nm": 1, "landmarks": []}},
     "measure must be one of"),
])
def test_design_spec_optimize_rejects(opt, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_design_spec({"lattice": "honeycomb", "ops": _optimize_ops(), "optimize": opt})


# ── design grammar: rejections ────────────────────────────────────────────────

@pytest.mark.parametrize("bad,match", [
    ({"ops": []}, "non-empty"),
    ({"ops": [{"op": "extrude", "cells": [[0, 0]], "length_bp": 1, "offset_nm": 1}]}, "first op must be 'bundle'"),
    ({"ops": [{"op": "frobnicate"}]}, "unknown design op"),
    ({"lattice": "triangular", "ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 1}]}, "lattice"),
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "lenght_bp": 1}]}, "unknown field"),  # typo'd key
    ({"ops": [{"op": "bundle", "cells": [], "length_bp": 1}]}, "non-empty list"),
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 0}]}, "non-zero"),
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 1.5}]}, "must be an int"),
    ({"ops": [{"op": "bundle", "cells": [[0]], "length_bp": 1}]}, "row, col"),
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 1},
              {"op": "nick", "helix": [0, 0], "bp_index": 1, "direction": "sideways"}]}, "direction"),
    # loop_skip with an out-of-range delta (route allows only -1/0/+1)
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
              {"op": "loop_skip", "helix": [0, 0], "bp_index": 14, "delta": 2}]}, "delta"),
    # loop_skip missing its required delta
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
              {"op": "loop_skip", "helix": [0, 0], "bp_index": 14}]}, "delta"),
    # loop_skip with a negative bp_index
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
              {"op": "loop_skip", "helix": [0, 0], "bp_index": -1, "delta": 1}]}, "bp_index"),
    # loop_skip can't be the first op (needs existing helices)
    ({"ops": [{"op": "loop_skip", "helix": [0, 0], "bp_index": 14, "delta": 1}]},
     "first op must be 'bundle'"),
    # bend missing its required curvature
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 84},
              {"op": "bend", "plane_a_bp": 20, "plane_b_bp": 60}]}, "curvature_deg_per_bp"),
    # bend with planes out of order
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 84},
              {"op": "bend", "plane_a_bp": 60, "plane_b_bp": 20, "curvature_deg_per_bp": 2}]},
     "must be greater than"),
    # twist with neither rate
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 84},
              {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60}]}, "exactly one"),
    # twist with both rates
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 84},
              {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60,
               "total_degrees": 90, "degrees_per_nm": 30}]}, "exactly one"),
    # bend can't be the first op (needs existing helices)
    ({"ops": [{"op": "bend", "plane_a_bp": 20, "plane_b_bp": 60, "curvature_deg_per_bp": 2}]},
     "first op must be 'bundle'"),
    # circle_segment missing its required radius
    ({"lattice": "square", "ops": [{"op": "circle_segment", "plane": "XY"}]}, "radius_nm"),
    # circle_segment with a non-positive radius
    ({"lattice": "square", "ops": [{"op": "circle_segment", "radius_nm": 0}]}, "must be > 0"),
    # circle_segment requires a SQUARE lattice (honeycomb is the default)
    ({"ops": [{"op": "circle_segment", "radius_nm": 10.6}]}, "requires a 'square' lattice"),
    # circle_segment with a typo'd field
    ({"lattice": "square",
      "ops": [{"op": "circle_segment", "radius_nm": 10.6, "raidus": 5}]}, "unknown field"),
    # routing ops can't be first (all need existing helices/strands)
    ({"ops": [{"op": "auto_scaffold"}]}, "first op must be 'bundle'"),
    ({"ops": [{"op": "auto_crossover"}]}, "first op must be 'bundle'"),
    ({"ops": [{"op": "full_autostaple"}]}, "first op must be 'bundle'"),
    ({"ops": [{"op": "apply_loop_skips"}]}, "first op must be 'bundle'"),
    # auto_scaffold seamless must be a bool
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
              {"op": "auto_scaffold", "seamless": "yes"}]}, "must be a bool"),
    # full_autostaple with a typo'd field
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
              {"op": "full_autostaple", "scafold_name": "M13mp18"}]}, "unknown field"),
    # auto_crossover takes no params
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42},
              {"op": "auto_crossover", "density": 1.0}]}, "unknown field"),
    # constraint with an unknown measure
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": [{"measure": "wibble", "landmarks": [], "target_nm": 1, "tol_nm": 1}]},
     "measure must be one of"),
    # end_to_end needs exactly 2 landmarks (one given)
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": [{"measure": "end_to_end", "target_nm": 1, "tol_nm": 1,
                       "landmarks": [{"helix": [0, 0], "bp_index": 0, "direction": "forward"}]}]},
     "needs exactly 2 landmarks"),
    # radius_of_gyration takes no landmarks
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": [{"measure": "radius_of_gyration", "target_nm": 1, "tol_nm": 1,
                       "landmarks": [{"helix": [0, 0], "bp_index": 0, "direction": "forward"}]}]},
     "takes no landmarks"),
    # constraint tol must be positive
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": [{"measure": "radius_of_gyration", "target_nm": 4, "tol_nm": 0}]},
     "tol_nm must be positive"),
    # constraint landmark missing a field
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": [{"measure": "end_to_end", "target_nm": 1, "tol_nm": 1,
                       "landmarks": [{"helix": [0, 0], "bp_index": 0},
                                     {"helix": [0, 0], "bp_index": 40, "direction": "forward"}]}]},
     "missing required field 'direction'"),
    # constraint with a typo'd field
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": [{"measure": "radius_of_gyration", "target_nm": 4, "tol_nm": 1,
                       "min_confidance": 50}]}, "unknown field"),
    # constraints must be a list
    ({"ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42}],
      "constraints": {"measure": "radius_of_gyration"}}, "must be a list"),
])
def test_design_spec_rejects_malformed(bad, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_design_spec(bad)


def test_design_spec_rejects_non_dict():
    with pytest.raises(BuildSpecError, match="must be an object"):
        parse_design_spec([1, 2, 3])


# ── assembly grammar: happy path + referential integrity ──────────────────────

_BEAM = {"lattice": "honeycomb", "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}]}


def test_assembly_spec_parses_parts_and_ops():
    parsed = parse_assembly_spec({
        "name": "rig",
        "parts": {"beam": _BEAM},
        "ops": [
            {"op": "add_part", "part": "beam", "ref": "A",
             "connectors": [{"label": "t", "position": [5, 0, 0], "normal": [1, 0, 0]}]},
            {"op": "add_part", "part": "beam", "ref": "B", "transform": [20, 0, 0],
             "connectors": [{"label": "t", "position": [-5, 0, 0], "normal": [-1, 0, 0]}]},
            {"op": "place_grid", "part": "beam", "rows": 2, "cols": 3, "pitch": 10},
            {"op": "place_ring", "part": "beam", "n": 4, "radius": 12},
            {"op": "mate", "child": "B", "parent": "A", "child_label": "t", "parent_label": "t"},
        ],
    })
    assert parsed.name == "rig"
    assert set(parsed.parts) == {"beam"}
    assert parsed.parts["beam"].lattice is LatticeType.HONEYCOMB
    assert [o.op for o in parsed.ops] == ["add_part", "add_part", "place_grid", "place_ring", "mate"]
    # transform normalised to a tagged translation
    assert parsed.ops[1].params["transform"] == {"kind": "translation", "values": (20.0, 0.0, 0.0)}


def test_assembly_spec_accepts_16float_matrix_transform():
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    parsed = parse_assembly_spec({
        "parts": {"beam": _BEAM},
        "ops": [{"op": "add_part", "part": "beam", "transform": identity}],
    })
    assert parsed.ops[0].params["transform"]["kind"] == "matrix"
    assert len(parsed.ops[0].params["transform"]["values"]) == 16


# ── file-backed parts (AF-12 — from_file) ─────────────────────────────────────

def test_assembly_spec_parses_file_part():
    """A ``{"from_file": "<path>"}`` part parses to a FilePart marker (the driver lowers
    it to add_file_instance); an inline part still parses to a DesignSpec."""
    parsed = parse_assembly_spec({
        "parts": {"hinge": {"from_file": "parts-library/hinge_6hb.nadoc"}, "beam": _BEAM},
        "ops": [{"op": "add_part", "part": "hinge"}],
    })
    assert parsed.parts["hinge"] == FilePart(path="parts-library/hinge_6hb.nadoc")
    assert parsed.parts["beam"].lattice is LatticeType.HONEYCOMB   # inline still a DesignSpec


@pytest.mark.parametrize("bad,match", [
    # from_file must be a non-empty string
    ({"parts": {"h": {"from_file": ""}}, "ops": [{"op": "add_part", "part": "h"}]},
     "non-empty path"),
    ({"parts": {"h": {"from_file": 7}}, "ops": [{"op": "add_part", "part": "h"}]},
     "from_file"),
    # extra keys on a file part are rejected (catches a half-inline/half-file typo)
    ({"parts": {"h": {"from_file": "x.nadoc", "lattice": "honeycomb"}},
      "ops": [{"op": "add_part", "part": "h"}]}, "unknown field"),
    # a file part cannot be placed by place_grid / place_ring (one instance, by ref)
    ({"parts": {"h": {"from_file": "x.nadoc"}},
      "ops": [{"op": "place_grid", "part": "h", "rows": 2, "cols": 2, "pitch": 10}]},
     "can only be placed with 'add_part'"),
    ({"parts": {"h": {"from_file": "x.nadoc"}},
      "ops": [{"op": "place_ring", "part": "h", "n": 4, "radius": 12}]},
     "can only be placed with 'add_part'"),
])
def test_assembly_spec_file_part_rejects(bad, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_assembly_spec(bad)


@pytest.mark.parametrize("bad,match", [
    ({"parts": {}, "ops": [{"op": "add_part", "part": "x"}]}, "non-empty object"),
    ({"parts": {"beam": _BEAM}, "ops": [{"op": "add_part", "part": "ghost"}]}, "not in 'parts'"),
    ({"parts": {"beam": _BEAM}, "ops": [{"op": "wobble", "part": "beam"}]}, "unknown assembly op"),
    # mate references an instance never added
    ({"parts": {"beam": _BEAM}, "ops": [
        {"op": "add_part", "part": "beam", "ref": "A",
         "connectors": [{"label": "t", "position": [5, 0, 0], "normal": [1, 0, 0]}]},
        {"op": "mate", "child": "Z", "parent": "A", "child_label": "t", "parent_label": "t"}]},
     "was not defined"),
    # mate references a connector label that doesn't exist on that instance
    ({"parts": {"beam": _BEAM}, "ops": [
        {"op": "add_part", "part": "beam", "ref": "A",
         "connectors": [{"label": "t", "position": [5, 0, 0], "normal": [1, 0, 0]}]},
        {"op": "add_part", "part": "beam", "ref": "B",
         "connectors": [{"label": "t", "position": [-5, 0, 0], "normal": [-1, 0, 0]}]},
        {"op": "mate", "child": "B", "parent": "A", "child_label": "nope", "parent_label": "t"}]},
     "is not a connector"),
    # duplicate instance ref
    ({"parts": {"beam": _BEAM}, "ops": [
        {"op": "add_part", "part": "beam", "ref": "A"},
        {"op": "add_part", "part": "beam", "ref": "A"}]},
     "duplicate instance ref"),
    # bad transform length
    ({"parts": {"beam": _BEAM}, "ops": [{"op": "add_part", "part": "beam", "transform": [1, 2]}]},
     "3 .translation. or 16"),
    # place_grid degenerate
    ({"parts": {"beam": _BEAM}, "ops": [{"op": "place_grid", "part": "beam", "rows": 0, "cols": 1, "pitch": 1}]},
     "must be > 0"),
    ({"parts": {"beam": _BEAM}, "ops": [{"op": "place_ring", "part": "beam", "n": 4, "radius": 0}]},
     "must be > 0"),
])
def test_assembly_spec_rejects_malformed(bad, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_assembly_spec(bad)


def test_assembly_spec_propagates_bad_part_spec():
    with pytest.raises(BuildSpecError, match=r"parts\['beam'\]"):
        parse_assembly_spec({
            "parts": {"beam": {"ops": [{"op": "extrude", "cells": [[0, 0]], "length_bp": 1, "offset_nm": 1}]}},
            "ops": [{"op": "add_part", "part": "beam"}],
        })


# ── gear op grammar (AF-11 Phase 2 — assembly relations cluster) ───────────────

def _gear_ops(*, ratio=2.0, joint_type="revolute", extra=None):
    """Two parts, each revolute-mated to the other (refs ja/jb), then a gear."""
    ops = [
        {"op": "add_part", "part": "beam", "ref": "A",
         "connectors": [{"label": "t", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "add_part", "part": "beam", "ref": "B", "transform": [20, 0, 0],
         "connectors": [{"label": "t", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "mate", "child": "B", "parent": "A", "child_label": "t", "parent_label": "t",
         "joint_type": joint_type, "axis_direction": [0, 0, 1], "ref": "ja"},
        {"op": "add_part", "part": "beam", "ref": "C", "transform": [40, 0, 0],
         "connectors": [{"label": "t", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "mate", "child": "C", "parent": "A", "child_label": "t", "parent_label": "t",
         "joint_type": joint_type, "axis_direction": [0, 0, 1], "ref": "jb"},
        {"op": "gear", "joint_a": "ja", "joint_b": "jb", "ratio": ratio},
    ]
    if extra is not None:
        ops[-1].update(extra)
    return {"parts": {"beam": _BEAM}, "ops": ops}


def test_assembly_spec_normalises_gear():
    parsed = parse_assembly_spec(_gear_ops(ratio=2.0, extra={"invert": True}))
    assert [o.op for o in parsed.ops] == ["add_part", "add_part", "mate", "add_part", "mate", "gear"]
    g = parsed.ops[-1].params
    assert g["joint_a"] == "ja" and g["joint_b"] == "jb"
    assert g["ratio"] == 2.0 and g["invert"] is True
    # the mates carry their joint refs
    assert parsed.ops[2].params["ref"] == "ja"


def test_assembly_spec_gear_defaults_ratio_and_invert():
    spec = {"parts": {"beam": _BEAM}, "ops": _gear_ops()["ops"]}
    spec["ops"][-1] = {"op": "gear", "joint_a": "ja", "joint_b": "jb"}
    parsed = parse_assembly_spec(spec)
    g = parsed.ops[-1].params
    assert g["ratio"] == 1.0 and g["invert"] is False


@pytest.mark.parametrize("bad,match", [
    # gear references a joint ref never defined by a mate
    (_gear_ops(extra={"joint_b": "ghost"}), "was not defined by a prior mate ref"),
    # gear couples a RIGID mate → rejected at parse time (route would 400)
    (_gear_ops(joint_type="rigid"), "must be 'revolute'"),
    # ratio must be non-zero
    (_gear_ops(extra={"ratio": 0}), "must be non-zero"),
])
def test_assembly_spec_gear_rejects(bad, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_assembly_spec(bad)


def test_assembly_spec_rejects_duplicate_joint_ref():
    spec = _gear_ops()
    spec["ops"][4]["ref"] = "ja"  # second mate reuses the first mate's ref
    with pytest.raises(BuildSpecError, match="duplicate joint ref"):
        parse_assembly_spec(spec)


def test_assembly_spec_gear_missing_joint_raises():
    spec = _gear_ops()
    spec["ops"][-1] = {"op": "gear", "joint_a": "ja"}  # no joint_b
    with pytest.raises(BuildSpecError, match="missing required field 'joint_b'"):
        parse_assembly_spec(spec)


# ── belt op grammar (AF-11 Phase 2 — assembly relations cluster, sub-op 2) ─────
# A belt reuses the gear's joint-``ref`` namespace verbatim: it couples two revolute
# mate-joints, but by their rim-radius ratio instead of a literal gear ratio.

def _belt_ops(*, radius_a=2.0, radius_b=1.0, joint_type="revolute", extra=None):
    """Two parts, each revolute-mated to a base (refs ja/jb), then a belt."""
    ops = [
        {"op": "add_part", "part": "beam", "ref": "A",
         "connectors": [{"label": "t", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "add_part", "part": "beam", "ref": "B", "transform": [20, 0, 0],
         "connectors": [{"label": "t", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "mate", "child": "B", "parent": "A", "child_label": "t", "parent_label": "t",
         "joint_type": joint_type, "axis_direction": [0, 0, 1], "ref": "ja"},
        {"op": "add_part", "part": "beam", "ref": "C", "transform": [40, 0, 0],
         "connectors": [{"label": "t", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "mate", "child": "C", "parent": "A", "child_label": "t", "parent_label": "t",
         "joint_type": joint_type, "axis_direction": [0, 0, 1], "ref": "jb"},
        {"op": "belt", "joint_a": "ja", "joint_b": "jb",
         "radius_a": radius_a, "radius_b": radius_b},
    ]
    if extra is not None:
        ops[-1].update(extra)
    return {"parts": {"beam": _BEAM}, "ops": ops}


def test_assembly_spec_normalises_belt():
    parsed = parse_assembly_spec(_belt_ops(radius_a=3.0, radius_b=1.5, extra={"name": "drive"}))
    assert [o.op for o in parsed.ops] == ["add_part", "add_part", "mate", "add_part", "mate", "belt"]
    b = parsed.ops[-1].params
    assert b["joint_a"] == "ja" and b["joint_b"] == "jb"
    assert b["radius_a"] == 3.0 and b["radius_b"] == 1.5 and b["name"] == "drive"


@pytest.mark.parametrize("bad,match", [
    # belt references a joint ref never defined by a mate
    (_belt_ops(extra={"joint_b": "ghost"}), "was not defined by a prior mate ref"),
    # belt couples a RIGID mate → rejected at parse time (route would 400)
    (_belt_ops(joint_type="rigid"), "must be 'revolute'"),
    # radii must be positive
    (_belt_ops(radius_a=0), "must be > 0"),
    (_belt_ops(radius_b=-1.0), "must be > 0"),
])
def test_assembly_spec_belt_rejects(bad, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_assembly_spec(bad)


def test_assembly_spec_belt_missing_radius_raises():
    spec = _belt_ops()
    spec["ops"][-1] = {"op": "belt", "joint_a": "ja", "joint_b": "jb", "radius_a": 2.0}
    with pytest.raises(BuildSpecError, match="missing required field 'radius_b'"):
        parse_assembly_spec(spec)


# ── polymerize op grammar (AF-11 Phase 2 — assembly relations cluster, sub-op 3) ─
# Polymerize reuses the joint-``ref`` namespace too, but references a SINGLE seed mate
# (not a pair) and — unlike gear/belt — accepts ANY joint_type (it replicates the seed
# mate, it does not couple two revolute joints). So there is no revolute gate here.

def _polymerize_ops(*, count=4, direction="forward", joint_type="rigid", extra=None):
    """Two identical parts mated (ref ``seed``), then polymerized into a chain."""
    ops = [
        {"op": "add_part", "part": "beam", "ref": "A",
         "connectors": [{"label": "t", "position": [5, 0, 0], "normal": [1, 0, 0]}]},
        {"op": "add_part", "part": "beam", "ref": "B", "transform": [20, 0, 0],
         "connectors": [{"label": "t", "position": [-5, 0, 0], "normal": [-1, 0, 0]}]},
        {"op": "mate", "child": "B", "parent": "A", "child_label": "t", "parent_label": "t",
         "joint_type": joint_type, "ref": "seed"},
        {"op": "polymerize", "joint": "seed", "count": count, "direction": direction},
    ]
    if extra is not None:
        ops[-1].update(extra)
    return {"parts": {"beam": _BEAM}, "ops": ops}


def test_assembly_spec_normalises_polymerize():
    parsed = parse_assembly_spec(_polymerize_ops(count=5, direction="both"))
    assert [o.op for o in parsed.ops] == ["add_part", "add_part", "mate", "polymerize"]
    pm = parsed.ops[-1].params
    assert pm["joint"] == "seed" and pm["count"] == 5 and pm["direction"] == "both"


def test_assembly_spec_polymerize_defaults_direction():
    spec = _polymerize_ops()
    spec["ops"][-1] = {"op": "polymerize", "joint": "seed", "count": 4}
    parsed = parse_assembly_spec(spec)
    assert parsed.ops[-1].params["direction"] == "forward"


def test_assembly_spec_polymerize_allows_rigid_seed():
    # polymerize replicates the seed mate, so a RIGID seed is fine (no revolute gate)
    parsed = parse_assembly_spec(_polymerize_ops(joint_type="rigid"))
    assert parsed.ops[-1].op == "polymerize"


@pytest.mark.parametrize("bad,match", [
    # polymerize references a joint ref never defined by a mate
    (_polymerize_ops(extra={"joint": "ghost"}), "was not defined by a prior mate ref"),
    # count must be ≥ 2 (the seed pair)
    (_polymerize_ops(count=1), "must be ≥ 2"),
    # direction must be one of the three
    (_polymerize_ops(direction="sideways"), "must be 'forward', 'backward', or 'both'"),
])
def test_assembly_spec_polymerize_rejects(bad, match):
    with pytest.raises(BuildSpecError, match=match):
        parse_assembly_spec(bad)


def test_assembly_spec_polymerize_missing_count_raises():
    spec = _polymerize_ops()
    spec["ops"][-1] = {"op": "polymerize", "joint": "seed"}
    with pytest.raises(BuildSpecError, match="missing required field 'count'"):
        parse_assembly_spec(spec)
