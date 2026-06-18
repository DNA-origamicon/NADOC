"""Declarative build-spec interpreter — the driver (AF-11, Tier 4).

The execution half of the build-spec interpreter whose pure grammar/parser lives in
:mod:`backend.core.build_spec`.  Given a spec dict, this builds the design/assembly
it describes by **dispatching each parsed op to its existing headless wrapper** —
:mod:`backend.api.headless_build` for design ops, :mod:`backend.api.headless_assembly_build`
for assembly ops.  It re-implements **no** operation: every op is one of the real
``hb.*`` / ``hab.*`` functions a person's click drives, so a spec-built structure is
byte-for-byte identical (in canonical topology) to the equivalent hand-call sequence —
the property the AF-11 oracle :func:`tests.automation_harness.assert_spec_matches_calls`
pins.  Because it composes already-covered wrappers and wraps no new route, it adds no
headless-coverage (like the AF-10 layout helpers); its value is the *faithful façade*
the text-to-DNA goal rests on.

This is the seed of text-to-DNA-origami: a natural-language request can be lowered to
a JSON spec, which this interpreter turns into a validated, replayable build.

Helices are referenced in nick/ligate/loop_skip ops by lattice ``grid_pos``
``[row, col]`` (resolved to the runtime helix id here); assembly instances are
referenced in ``mate`` ops by the spec's ``ref`` key, and the joints a ``mate``
creates are referenced in ``gear``/``belt``/``polymerize`` ops by the mate's optional
``ref`` key (all resolved to runtime ids here — a ``gear`` op drives
``hab.define_gear`` and a ``belt`` op drives ``hab.define_belt``, the AF-9 wrappers,
each coupling two revolute mate-joints — the gear at a constant ratio, the belt at the
rim-radius ratio ``radius_a / radius_b``; a ``polymerize`` op drives ``hab.polymerize``,
replicating a SINGLE seed mate into a chain of ``count`` identical parts marching along
the seed's part-to-part offset).
``loop_skip`` ops drive ``hb.loop_skip`` (the AF-3 wrapper);
``bend``/``twist`` ops are *unscoped* geometric deformations driven through
``hb.add_bend`` / ``hb.add_twist`` (the AF-6 wrappers); ``circle_segment`` drives
``hb.circle_segment`` (the AF-4 parametric-disc wrapper — takes the *radius* and runs
the same footprint analytic the UI mirror uses).  The bulk routing ops
``auto_scaffold`` / ``auto_crossover`` / ``full_autostaple`` drive the matching
``hb.*`` wrappers (route the scaffold, place all staple crossovers, one-click
sequence+crossover+break); ``apply_loop_skips`` drives ``hb.apply_loop_skip_deformations``
(bake deformations + SQUARE periodic skips into loop/skip marks).  Because these four
ADD/modify strands the strand graph fingerprint sees, ``assert_spec_matches_calls`` is
LOAD-BEARING for the routing ops (a dropped op fails the golden pin) — but, like
loop_skip, the marks ``apply_loop_skips`` bakes live outside the strand graph, so its
load-bearing pin is the geometric per-helix nucleotide-count conservation, not the
faithfulness oracle.  Note ``canonical_topology``
is blind to a loop/skip mark AND to a deformation overlay (both live outside the
strand graph), so the load-bearing pin for a ``loop_skip`` spec is the geometric
:func:`tests.automation_harness.assert_geometric_length_delta` / bare
``geometric_nucleotide_count`` (and for bend/twist,
:func:`~tests.automation_harness.assert_deformation_angle`), **not**
``assert_spec_matches_calls`` — which is vacuous for either.
"""

from __future__ import annotations

from backend.api import assembly_state
from backend.api import headless_assembly_build as hab
from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.build_spec import (
    AssemblySpec,
    BuildOp,
    BuildSpecError,
    DesignSpec,
    parse_assembly_spec,
    parse_design_spec,
)
from backend.core.models import Assembly, Design, LatticeType


# ── design interpreter ────────────────────────────────────────────────────────

def _resolve_helix_id(grid_pos: tuple[int, int]) -> str:
    """Look up the active design's helix at ``grid_pos`` → its runtime id."""
    design = design_state.get_or_404()
    for h in design.helices:
        if h.grid_pos is not None and tuple(h.grid_pos) == grid_pos:
            return h.id
    raise BuildSpecError(
        f"no helix at grid position {list(grid_pos)} — nick/ligate references a cell "
        "that no op created"
    )


def _run_design_op(op: BuildOp, lattice: LatticeType) -> None:
    """Drive one design op through its real headless wrapper on the active design."""
    p = op.params
    if op.op == "bundle":
        hb.create_bundle(
            p["cells"], p["length_bp"], lattice=lattice, name=p.get("name", "Bundle"),
            plane=p["plane"], strand_filter=p["strand_filter"],
            ligate_adjacent=p["ligate_adjacent"],
        )
    elif op.op == "extrude":
        hb.extrude(
            p["cells"], p["length_bp"], p["offset_nm"], plane=p["plane"],
            strand_filter=p["strand_filter"], extend_inplace=p["extend_inplace"],
            ligate_adjacent=p["ligate_adjacent"],
        )
    elif op.op == "nick":
        hb.nick(_resolve_helix_id(p["helix"]), p["bp_index"], p["direction"])
    elif op.op == "ligate":
        hb.ligate(_resolve_helix_id(p["helix"]), p["bp_index"], p["direction"])
    elif op.op == "loop_skip":
        hb.loop_skip(_resolve_helix_id(p["helix"]), p["bp_index"], p["delta"])
    elif op.op == "circle_segment":
        kwargs = {"plane": p["plane"], "offset_nm": p["offset_nm"],
                  "strand_filter": p["strand_filter"], "ligate_adjacent": p["ligate_adjacent"]}
        if "min_chord_bp" in p:
            kwargs["min_chord_bp"] = p["min_chord_bp"]
        hb.circle_segment(p["radius_nm"], **kwargs)
    elif op.op == "bend":
        hb.add_bend(
            p["plane_a_bp"], p["plane_b_bp"],
            curvature_deg_per_bp=p["curvature_deg_per_bp"],
            direction_deg=p["direction_deg"],
        )
    elif op.op == "twist":
        if "total_degrees" in p:
            hb.add_twist(p["plane_a_bp"], p["plane_b_bp"], total_degrees=p["total_degrees"])
        else:
            hb.add_twist(p["plane_a_bp"], p["plane_b_bp"], degrees_per_nm=p["degrees_per_nm"])
    elif op.op == "auto_scaffold":
        hb.auto_scaffold(seamless=p["seamless"])
    elif op.op == "auto_crossover":
        hb.auto_crossover()
    elif op.op == "full_autostaple":
        kwargs = {"scaffold_name": p["scaffold_name"]}
        if "custom_sequence" in p:
            kwargs["custom_sequence"] = p["custom_sequence"]
        if "strand_id" in p:
            kwargs["strand_id"] = p["strand_id"]
        hb.full_autostaple(**kwargs)
    elif op.op == "apply_loop_skips":
        hb.apply_loop_skip_deformations()
    else:  # unreachable — parse_design_spec rejects unknown ops
        raise BuildSpecError(f"unsupported design op {op.op!r}")


def _build_design_from_parsed(parsed: DesignSpec) -> Design:
    """Run a parsed design spec in an isolated scratch session → standalone Design."""
    with hb.scratch_session(parsed.lattice):
        for op in parsed.ops:
            _run_design_op(op, parsed.lattice)
        return design_state.get_or_404().model_copy(deep=True)


def build_design(spec) -> Design:
    """Build the design a spec describes (parse → drive wrappers) → standalone Design.

    Runs in an isolated scratch document so the active session is untouched; returns a
    deep copy carrying the full replayable feature log.  Raises
    :class:`backend.core.build_spec.BuildSpecError` on a malformed spec (at parse time,
    before anything is built).  Pin the result with
    :func:`tests.automation_harness.assert_roundtrip_stable` (survives a ``.nadoc``
    round-trip) and :func:`~tests.automation_harness.assert_spec_matches_calls` (builds
    the same canonical topology as the equivalent hand-call sequence).
    """
    return _build_design_from_parsed(parse_design_spec(spec))


# ── assembly interpreter ──────────────────────────────────────────────────────

def _materialize_transform(t):
    """Normalised transform dict (from the parser) → the wrapper's transform arg."""
    if t is None:
        return None
    if t["kind"] == "translation":
        return hab.translation(*t["values"])
    return list(t["values"])  # 16 floats; add_instance accepts a row-major list


def _run_assembly_op(
    op: BuildOp,
    part_designs: dict[str, Design],
    refs: dict[str, str],
    joint_refs: dict[str, str],
) -> None:
    """Drive one assembly op through its real wrapper, tracking instance + joint refs."""
    p = op.params
    if op.op == "add_part":
        hab.add_inline_instance(
            part_designs[p["part"]], name=p.get("name", p["part"]),
            transform=_materialize_transform(p["transform"]),
        )
        new_id = assembly_state.get_or_404().instances[-1].id
        for conn in p["connectors"]:
            hab.add_connector(new_id, conn["label"], conn["position"], conn["normal"])
        if "ref" in p:
            refs[p["ref"]] = new_id
    elif op.op == "place_grid":
        kwargs = {"pitch": p["pitch"], "plane": p["plane"], "center": p["center"],
                  "name": p.get("name", p["part"])}
        if "row_pitch" in p:
            kwargs["row_pitch"] = p["row_pitch"]
        hab.place_grid(part_designs[p["part"]], p["rows"], p["cols"], **kwargs)
    elif op.op == "place_ring":
        hab.place_ring(
            part_designs[p["part"]], p["n"], radius=p["radius"], plane=p["plane"],
            start_angle_deg=p["start_angle_deg"], center=p["center"],
            name=p.get("name", p["part"]),
        )
    elif op.op == "mate":
        kwargs = {
            "child_label": p["child_label"], "parent_label": p["parent_label"],
            "joint_type": p["joint_type"], "name": p.get("name", "Mate"),
        }
        for key in ("axis_origin", "axis_direction", "min_limit", "max_limit"):
            if key in p:
                kwargs[key] = p[key]
        hab.define_mate(refs[p["child"]], refs[p["parent"]], **kwargs)
        if "ref" in p:
            joint_refs[p["ref"]] = assembly_state.get_or_404().joints[-1].id
    elif op.op == "gear":
        hab.define_gear(
            joint_refs[p["joint_a"]], joint_refs[p["joint_b"]],
            ratio=p["ratio"], invert=p["invert"], name=p.get("name", "Gear"),
        )
    elif op.op == "belt":
        hab.define_belt(
            joint_refs[p["joint_a"]], joint_refs[p["joint_b"]],
            radius_a=p["radius_a"], radius_b=p["radius_b"], name=p.get("name", "Belt"),
        )
    elif op.op == "polymerize":
        hab.polymerize(joint_refs[p["joint"]], p["count"], direction=p["direction"])
    else:  # unreachable — parse_assembly_spec rejects unknown ops
        raise BuildSpecError(f"unsupported assembly op {op.op!r}")


def _build_assembly_from_parsed(parsed: AssemblySpec) -> Assembly:
    # Build each named part design first (own scratch session per part), then place.
    part_designs = {key: _build_design_from_parsed(ds) for key, ds in parsed.parts.items()}
    with hab.assembly_scratch_session():
        hab.new_assembly(parsed.name)
        refs: dict[str, str] = {}
        joint_refs: dict[str, str] = {}
        for op in parsed.ops:
            _run_assembly_op(op, part_designs, refs, joint_refs)
        return assembly_state.get_or_404().model_copy(deep=True)


def build_assembly(spec) -> Assembly:
    """Build the assembly a spec describes (parse → drive wrappers) → standalone Assembly.

    Each named part in ``spec['parts']`` is built once via :func:`build_design` (its own
    isolated scratch design), then placed/mated by the op list inside an isolated scratch
    assembly.  Returns a deep copy.  Raises
    :class:`backend.core.build_spec.BuildSpecError` on a malformed spec (at parse time).
    Pin the result with :func:`tests.automation_harness.assert_assembly_roundtrip_stable`
    and :func:`~tests.automation_harness.assert_spec_matches_calls` (``kind='assembly'``).
    """
    return _build_assembly_from_parsed(parse_assembly_spec(spec))
