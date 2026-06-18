"""Reusable validation spine for the design-automation loop (AF-1, Tier 0).

Every headless wrapper the ``/automate-feature`` loop adds is only trustworthy if
it ships with a way to *prove* it builds the right thing.  This module is that
shared proof surface: the oracles later AF items plug into instead of re-deriving.

Three building blocks:

- :func:`canonical_topology` — the id/order-independent design fingerprint
  (promoted here from ``test_section_router.py`` so any test can import it).
- :func:`roundtrip_nadoc` / :func:`assert_roundtrip_stable` — the round-trip
  oracle: build → export ``.nadoc`` → re-import → assert the topology fingerprint
  is unchanged *and* the design still validates.  This is the one-line acceptance
  test most AF wrappers will use ("does what I built survive a save/load?").
- :func:`headless_coverage_report` — the automated audit: which design/assembly
  mutation routes have a :mod:`backend.api.headless_build` wrapper and which don't,
  computed by *function-object identity* (a wrapper imports the route's handler),
  so the number can never go stale the way a hand-kept list does.

Nothing here mutates the active session: :func:`roundtrip_nadoc` runs inside an
isolated scratch document and returns a standalone deep copy.
"""
from __future__ import annotations

import inspect
from typing import Callable

from backend.api import state as design_state
from backend.api.crud import DesignImportRequest, import_design
from backend.api.headless_build import scratch_session
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.validator import validate_design


# ── Topology fingerprint ──────────────────────────────────────────────────────

def canonical_topology(d: Design):
    """ID- and order-independent fingerprint of a design's topology.

    Helices are keyed by ``grid_pos`` (unique per helix and stable across id
    schemes); strand domains reference helices by that same key.  Two designs
    with this fingerprint equal are topologically identical — the same helices
    in the same lattice cells carrying the same strand paths — regardless of how
    ids were assigned or what order the lists are in.

    (Promoted verbatim from ``test_section_router.py``; that module now imports
    it from here so there is a single definition.)
    """
    gp = {h.id: h.grid_pos for h in d.helices}
    helices = sorted(
        (
            h.grid_pos, h.length_bp, h.bp_start,
            round(h.axis_start.x, 4), round(h.axis_start.y, 4), round(h.axis_start.z, 4),
            round(h.axis_end.x, 4), round(h.axis_end.y, 4), round(h.axis_end.z, 4),
        )
        for h in d.helices
    )
    strands = sorted(
        (
            str(s.strand_type),
            tuple((gp[dm.helix_id], dm.start_bp, dm.end_bp, str(dm.direction)) for dm in s.domains),
        )
        for s in d.strands
    )
    return helices, strands


# ── Assembly topology fingerprint ─────────────────────────────────────────────

def canonical_assembly(a):
    """ID- and order-independent fingerprint of an assembly's structure.

    The assembly analog of :func:`canonical_topology`.  Two assemblies with this
    fingerprint equal place the same parts at the same world transforms with the
    same joints — regardless of instance/joint ids or list order:

    * **Instances** are keyed by a *source* fingerprint (inline → the embedded
      design's :func:`canonical_topology`; file → ``(path, sha256)``) plus the
      placement transform (rounded) and the display/kinematic flags that affect
      the built structure (``mode``, ``representation``, ``fixed``, ``visible``).
      Using the design's canonical topology — not its uuid — means a round-trip
      that re-assigns ids still matches.
    * **Joints** are keyed by their type, the connector labels they mate, and the
      driven value (Phase-1 assemblies have none; included so the fingerprint is
      complete for the AF-8+ mate/joint wrappers).
    * **Gear relations** (AF-9) are keyed by the two joints they couple — by each
      joint's *fingerprint* (NOT its uuid id, so the key is id-independent the same
      way the joint↔part keys are) — plus the ratio, invert flag, and anchors.  A
      gear dropped or rewired to a different joint pair by a round-trip changes the
      fingerprint, so :func:`assert_assembly_roundtrip_stable` now catches it.
    * **Overhang bindings** (AF-9) are keyed by their two endpoints — each the
      bound instance's *source fingerprint* (id-independent, as for joints) plus the
      overhang + sub-domain ids — taken as an unordered pair (the route treats a
      binding as unordered), plus the binding mode and wildcard flag.  A binding
      dropped or rewired by a round-trip changes the fingerprint.  (Note this only
      pins the binding's *structure*; that its endpoints still *resolve* to real
      sub-domains after a round-trip is the separate
      :func:`assert_binding_resolves` oracle, because ``canonical_topology`` does
      not fingerprint overhang sub-domains at all.)

    Returns a 5-tuple ``(instances, joints, gears, belts, bindings)``; callers
    compare the whole tuple for equality.
    """
    def _src_key(src):
        if getattr(src, "type", None) == "file":
            return ("file", src.path, getattr(src, "sha256", None) or "")
        return ("inline", canonical_topology(src.design))

    inst_src = {inst.id: _src_key(inst.source) for inst in a.instances}

    def _joint_fp(j):
        return (
            str(j.joint_type),
            j.connector_a_label or "",
            j.connector_b_label or "",
            # which parts the joint connects, keyed by source fingerprint (NOT the
            # uuid instance id) so the key is id-independent — a mate rewired to a
            # different part changes the fingerprint. ``("world",)`` for a World mate.
            inst_src.get(j.instance_a_id, ("world",)),
            inst_src.get(j.instance_b_id, ("world",)),
            round(float(j.current_value), 6),
        )

    joint_fp = {j.id: _joint_fp(j) for j in a.joints}

    instances = sorted(
        (
            _src_key(inst.source),
            tuple(round(float(v), 4) for v in inst.transform.values),
            str(inst.mode), str(inst.representation), bool(inst.fixed), bool(inst.visible),
        )
        for inst in a.instances
    )
    joints = sorted(_joint_fp(j) for j in a.joints)
    gears = sorted(
        (
            # the coupled joints by their id-independent fingerprints (a gear whose
            # joint pair changed across a round-trip changes this key), then the
            # numeric relation params the gear promises to hold.
            joint_fp.get(g.joint_a_id, ("missing",)),
            joint_fp.get(g.joint_b_id, ("missing",)),
            round(float(g.ratio), 6),
            bool(g.invert),
            round(float(g.joint_a_anchor), 6),
            round(float(g.joint_b_anchor), 6),
        )
        for g in getattr(a, "gear_relations", [])
    )
    belts = sorted(
        (
            # the two coupled pulley joints by their id-independent fingerprints (a
            # belt rewired to a different joint pair across a round-trip changes this
            # key), then each pulley's rim radius + side and the coupling anchors —
            # the params ``_belt_to_relation`` turns into the gear-equivalent ratio.
            joint_fp.get(b.pulley_a.joint_id, ("missing",)),
            joint_fp.get(b.pulley_b.joint_id, ("missing",)),
            round(float(b.pulley_a.radius), 6), str(b.pulley_a.side),
            round(float(b.pulley_b.radius), 6), str(b.pulley_b.side),
            round(float(b.joint_a_anchor), 6),
            round(float(b.joint_b_anchor), 6),
        )
        for b in getattr(a, "belt_paths", [])
    )
    bindings = sorted(
        (
            # the two bound endpoints as an UNORDERED pair (the route's duplicate
            # check is unordered): each endpoint = (instance source fingerprint,
            # overhang id, sub-domain id). Keying the instance by source fingerprint
            # — NOT its uuid — keeps the binding id-independent like the joint keys.
            tuple(sorted((
                (inst_src.get(ob.instance_a_id, ("missing",)), ob.overhang_a_id, ob.sub_domain_a_id),
                (inst_src.get(ob.instance_b_id, ("missing",)), ob.overhang_b_id, ob.sub_domain_b_id),
            ))),
            str(ob.binding_mode),
            bool(ob.allow_n_wildcard),
        )
        for ob in getattr(a, "overhang_bindings", [])
    )
    return instances, joints, gears, belts, bindings


# ── Round-trip oracle ─────────────────────────────────────────────────────────

def roundtrip_nadoc(design: Design) -> Design:
    """Faithful ``.nadoc`` export→import round-trip.

    Mirrors *File → Export Design (.nadoc)* followed by *File → Import*: the
    design is serialised with :meth:`Design.to_json` (exactly the bytes
    ``GET /design/export`` ships) and re-loaded through the real
    ``POST /design/import`` handler — including the migrate / autodetect-overhang
    / backfill post-processing that route applies on every load.  Runs in an
    isolated scratch document so the active session and its undo history are
    untouched; returns a standalone deep copy of the re-imported design.
    """
    text = design.to_json()
    with scratch_session(design.lattice_type):
        import_design(DesignImportRequest(content=text))
        return design_state.get_or_404().model_copy(deep=True)


def assert_roundtrip_stable(
    build_fn: Callable[[], Design],
    *,
    roundtrip: Callable[[Design], Design] = roundtrip_nadoc,
) -> Design:
    """The AF acceptance oracle: a headless build survives a ``.nadoc`` round-trip.

    Calls ``build_fn()`` to produce a design, then asserts:

      1. the freshly-built design passes :func:`validate_design`;
      2. after ``roundtrip`` (default: real export→import), it *still* passes; and
      3. its :func:`canonical_topology` is byte-for-byte unchanged by the round-trip.

    Any AF wrapper can pin itself with ``assert_roundtrip_stable(lambda: my_build())``.
    The ``roundtrip`` seam is injectable so the meta-test can prove this oracle
    actually *fires* on a corrupted round-trip (it must not silently pass).

    Returns the re-imported design so callers can make further assertions on it.
    """
    built = build_fn()
    report_before = validate_design(built)
    assert report_before.passed, f"build did not validate before round-trip:\n{report_before}"

    reloaded = roundtrip(built)

    report_after = validate_design(reloaded)
    assert report_after.passed, f"design did not validate after round-trip:\n{report_after}"

    before, after = canonical_topology(built), canonical_topology(reloaded)
    assert before == after, (
        "round-trip changed the design topology — export/import is not identity for "
        "this build (a real bug). helices "
        f"{len(before[0])}→{len(after[0])}, strands {len(before[1])}→{len(after[1])}."
    )
    return reloaded


# ── Assembly round-trip oracle ────────────────────────────────────────────────

def roundtrip_nass(assembly):
    """Faithful ``.nass`` export→import round-trip (the assembly analog of
    :func:`roundtrip_nadoc`).

    Serialises the assembly with :meth:`Assembly.to_json` (the v2 wire format
    ``GET /assembly/export`` ships) and re-loads it through the real
    ``POST /assembly/import`` handler — including its post-load processing.
    Stays *in memory* (no workspace files): inline part designs travel inside the
    payload, so an inline-source build round-trips without touching disk — exactly
    as :func:`roundtrip_nadoc` round-trips a design through import rather than the
    file-based load.  Runs in an isolated scratch document; returns a standalone
    deep copy of the re-imported assembly.
    """
    from backend.api import assembly_state
    from backend.api.headless_assembly_build import (
        assembly_scratch_session,
        import_assembly as _import,
    )

    text = assembly.to_json()
    with assembly_scratch_session():
        _import(text)
        return assembly_state.get_or_404().model_copy(deep=True)


def assert_assembly_roundtrip_stable(
    build_fn: Callable[[], "object"],
    *,
    roundtrip: Callable[["object"], "object"] = roundtrip_nass,
):
    """The AF assembly acceptance oracle: a headless assembly build survives a
    ``.nass`` round-trip.

    The assembly analog of :func:`assert_roundtrip_stable`.  Calls ``build_fn()``
    to produce an assembly, then asserts:

      1. the freshly-built assembly passes
         :func:`backend.core.assembly_validate.validate_assembly_report`
         (file sources resolve, joint refs/limits hold, ids unique, flatten ok);
      2. after ``roundtrip`` (default: real export→import), it *still* passes; and
      3. its :func:`canonical_assembly` fingerprint is unchanged by the round-trip.

    Any AF assembly wrapper can pin itself with
    ``assert_assembly_roundtrip_stable(lambda: my_build())``.  The ``roundtrip``
    seam is injectable so the meta-test can prove this oracle actually *fires* on
    a corrupted round-trip.  Returns the re-imported assembly.
    """
    from backend.core.assembly_validate import validate_assembly_report

    built = build_fn()
    report_before = validate_assembly_report(built)
    assert report_before["passed"], (
        f"assembly did not validate before round-trip:\n{report_before}"
    )

    reloaded = roundtrip(built)

    report_after = validate_assembly_report(reloaded)
    assert report_after["passed"], (
        f"assembly did not validate after round-trip:\n{report_after}"
    )

    before, after = canonical_assembly(built), canonical_assembly(reloaded)
    assert before == after, (
        "round-trip changed the assembly structure — export/import is not identity "
        f"for this build (a real bug). instances {len(before[0])}→{len(after[0])}, "
        f"joints {len(before[1])}→{len(after[1])}."
    )
    return reloaded


# ── Build-spec faithfulness oracle (AF-11) ────────────────────────────────────

def assert_spec_matches_calls(
    build_from_spec: Callable[[], "object"],
    build_by_hand: Callable[[], "object"],
    *,
    kind: str = "design",
):
    """The AF-11 acceptance oracle: a declarative build-spec produces the SAME
    canonical structure as the equivalent hand-call wrapper sequence.

    The build-spec interpreter (:mod:`backend.api.headless_spec_build`) must be a
    *faithful façade* over the existing headless wrappers — it drives the real
    ``hb.*`` / ``hab.*`` ops, it does not re-implement any of them.  This oracle is
    what proves that: ``build_from_spec`` runs the interpreter on a spec, and
    ``build_by_hand`` runs the equivalent sequence of wrapper calls directly; their
    id/order-independent fingerprints (:func:`canonical_topology` for ``kind="design"``,
    :func:`canonical_assembly` for ``kind="assembly"``) must be byte-for-byte equal.

    An interpreter that dropped an op, mis-ordered the chain, mistranslated a
    parameter, or quietly re-implemented an op with different behaviour fails here.
    A non-emptiness guard (the spec built *something*) keeps it from passing
    vacuously on a spec that builds nothing — the analog of
    :func:`assert_inverse_pair`'s "forward really mutated" guard.

    This is also the **golden pin** the backlog calls for: because the hand-call
    reference is deterministic, "the spec matches the calls" is equivalently "the
    spec always builds this one canonical structure".  Returns the spec-built object.
    """
    fp = canonical_topology if kind == "design" else canonical_assembly
    spec_built = build_from_spec()
    hand_built = build_by_hand()

    if kind == "design":
        assert getattr(spec_built, "helices", None), (
            "the spec built an empty design (no helices) — this oracle would pass "
            "vacuously; use a spec that actually constructs geometry."
        )
    else:
        assert getattr(spec_built, "instances", None), (
            "the spec built an empty assembly (no instances) — this oracle would pass "
            "vacuously; use a spec that actually places parts."
        )

    a, b = fp(spec_built), fp(hand_built)
    assert a == b, (
        "the build-spec interpreter did not produce the same canonical structure as "
        "the equivalent hand-call wrapper sequence — the spec was lowered to a "
        "different build (a dropped/mis-ordered op or a mistranslated parameter)."
    )
    return spec_built


# ── Mate-coincidence oracle (assembly joints) ─────────────────────────────────

def assert_mate_coincident(
    assembly,
    joint_id: str,
    *,
    tol_nm: float = 0.01,
    min_offset_nm: float = 0.5,
) -> float:
    """Geometric oracle: a mate's two connectors are coincident in world space.

    The joint analog of :func:`assert_on_deformed_frame` — it asserts the geometric
    promise a mate makes (``define_mate`` snaps the child so its connector meets the
    parent's), measured on the *built* assembly with the SAME connector-world
    machinery ``resolve_assembly`` uses (``_get_connector_world`` on the
    instance-overridden design), not a re-derivation:

      1. **Coincident.** The world positions of ``connector_a_label`` (on the
         joint's parent instance) and ``connector_b_label`` (on the child) agree to
         within ``tol_nm``.  A builder that registered the joint but failed to snap
         the child — or snapped it to the wrong connector — fails here.
      2. **Non-trivial (the can-go-red guard).** The two mated instances' world
         origins are separated by more than ``min_offset_nm``, so the coincidence is
         genuine alignment work (two offset parts whose connectors nonetheless meet),
         not the vacuous case of both parts stacked at the origin.  This is the mate
         analog of :func:`assert_inverse_pair`'s "forward really mutated" guard;
         place mate connectors at a non-zero local offset from their part origins so
         the snap has to move the child.

    Pass the assembly *after* the mate (and optionally after :func:`resolve`, since
    the constraint must survive a resolve).  Returns the measured discrepancy (nm).
    """
    import numpy as np

    from backend.api.assembly import _assembly_source_path, _design_with_instance_overrides
    from backend.core.assembly_connectors import _get_connector_world

    joint = next((j for j in assembly.joints if j.id == joint_id), None)
    assert joint is not None, f"no joint {joint_id!r} in the assembly"
    assert joint.connector_a_label and joint.connector_b_label, (
        "joint references no connector labels — not a connector mate"
    )
    inst_a = next((i for i in assembly.instances if i.id == joint.instance_a_id), None)
    inst_b = next((i for i in assembly.instances if i.id == joint.instance_b_id), None)
    assert inst_a is not None and inst_b is not None, (
        "mate references an instance that is not in the assembly"
    )

    asm_path = _assembly_source_path(assembly)
    design_a = _design_with_instance_overrides(inst_a, asm_path)
    design_b = _design_with_instance_overrides(inst_b, asm_path)
    ca = _get_connector_world(inst_a, joint.connector_a_label, design_a)
    cb = _get_connector_world(inst_b, joint.connector_b_label, design_b)
    assert ca is not None and cb is not None, (
        "could not resolve a mated connector's world position "
        f"(a={joint.connector_a_label!r}→{ca}, b={joint.connector_b_label!r}→{cb})"
    )

    origin_a = np.array(inst_a.transform.values, dtype=float).reshape(4, 4)[:3, 3]
    origin_b = np.array(inst_b.transform.values, dtype=float).reshape(4, 4)[:3, 3]
    part_sep = float(np.linalg.norm(origin_a - origin_b))
    assert part_sep > min_offset_nm, (
        f"the two mated parts' origins are only {part_sep:.3f} nm apart "
        f"(< {min_offset_nm} nm) — connector coincidence is trivial here, so this "
        "oracle would pass vacuously; place the mate connectors at a non-zero local "
        "offset from their part origins so the snap has to do real work."
    )

    disc = float(np.linalg.norm(np.asarray(ca) - np.asarray(cb)))
    assert disc <= tol_nm, (
        f"mate connectors are {disc:.4f} nm apart (> {tol_nm} nm) — the mate did not "
        f"snap {joint.connector_b_label!r} onto {joint.connector_a_label!r} "
        "(connectors are not coincident)."
    )
    return disc


# ── Gear-ratio oracle (assembly resolve-invariant) ────────────────────────────

def assert_gear_ratio(
    assembly_before,
    assembly_after,
    rel_id: str,
    *,
    expected_ratio: float,
    ratio_tol: float = 0.02,
    min_angle_deg: float = 2.0,
) -> float:
    """Geometric resolve-invariant oracle: a gear relation makes its two coupled
    bodies rotate in the ratio it promises.

    The gear analog of :func:`assert_mate_coincident` — it asserts the geometric
    promise a :class:`GearRelation` makes (driving one revolute drives the other at
    a fixed angular ratio), measured on the *placed instance transforms* the
    kinematics actually moved, **not** on the stored ``joint.current_value`` (which
    would just re-test the route's own ``θ_b = ratio·θ_a`` arithmetic against
    itself).  Pass the assembly *before* and *after* driving one side of the gear
    (e.g. ``hab.drive_joint(joint_a_id, angle)``, whose PATCH auto-propagates the
    relation):

      1. **Ratio honoured.** Each coupled joint's moving body (the gear-endpoint
         instance — child by default, parent for a "backward" revolute) has its
         world rotation magnitude measured between *before* and *after*; the driven
         body rotated ``|expected_ratio|`` times as much as the driver, to within
         ``ratio_tol``.  A builder that registered the gear but failed to propagate
         the motion, or used the wrong ratio, fails here.
      2. **Driver actually moved (the can-go-red guard).** The driver body's
         rotation exceeds ``min_angle_deg``, so the oracle FAILS if nothing was
         driven (a no-op gear would make the ratio ``0/0``) — the analog of
         :func:`assert_inverse_pair`'s "forward really mutated" guard.

    **Direction-agnostic:** it compares only rotation *magnitudes* (the gear's
    ratio), never the bend/twist-style sign or handedness that ``CLAUDE.md`` reserves
    for the user; the ``invert`` flag flips the driven body's *direction* but not the
    magnitude ratio this oracle pins.  ``rel_id`` is the coupling relation's id (stable
    across the drive).

    **Belts reuse this oracle (AF-9).** A :class:`BeltPath` is a gear-equivalent
    coupling (``_belt_to_relation``): pass the belt's synthetic relation id
    (``f"__belt__{belt.id}"``) and ``expected_ratio = radius_a / radius_b`` and this
    same machinery pins that the rim-radius ratio actually drives the two pulleys.

    Returns the measured ratio ``rot_driven / rot_driver``.
    """
    import math

    import numpy as np

    from backend.core.assembly_kinematics import (
        _coupling_relations,
        _gear_endpoint_side,
    )

    # Search ALL coupling relations, not just stored gears: a belt couples its two
    # pulleys via a GearRelation synthesised on the fly by ``_belt_to_relation`` (id
    # ``__belt__<belt id>``) and folded into the same propagation — so this same
    # oracle pins a belt's ratio when handed that synthetic id + ``expected_ratio =
    # radius_a / radius_b`` (the gear path is unchanged: gears are first in the list).
    joints_after = {j.id: j for j in assembly_after.joints}
    rel = next(
        (g for g in _coupling_relations(assembly_after, joints_after) if g.id == rel_id),
        None,
    )
    assert rel is not None, f"no coupling relation {rel_id!r} in the assembly"
    joint_a = joints_after.get(rel.joint_a_id)
    joint_b = joints_after.get(rel.joint_b_id)
    assert joint_a is not None and joint_b is not None, (
        "gear relation references a joint that is not in the assembly"
    )

    inst_before = {i.id: i for i in assembly_before.instances}
    inst_after = {i.id: i for i in assembly_after.instances}

    def _moving_instance_id(which: str, joint):
        side = _gear_endpoint_side(rel, which, joint)
        return joint.instance_a_id if side == "a" else joint.instance_b_id

    def _rotation_magnitude_deg(inst_id: str) -> float:
        b = inst_before.get(inst_id)
        a = inst_after.get(inst_id)
        assert b is not None and a is not None, (
            f"gear-endpoint instance {inst_id!r} is missing from before/after"
        )
        R0 = np.array(b.transform.values, dtype=float).reshape(4, 4)[:3, :3]
        R1 = np.array(a.transform.values, dtype=float).reshape(4, 4)[:3, :3]
        M = R1 @ R0.T
        cos = (float(np.trace(M)) - 1.0) / 2.0
        return float(np.degrees(math.acos(max(-1.0, min(1.0, cos)))))

    rot_driver = _rotation_magnitude_deg(_moving_instance_id("a", joint_a))
    rot_driven = _rotation_magnitude_deg(_moving_instance_id("b", joint_b))

    assert rot_driver > min_angle_deg, (
        f"the gear's driver body rotated by only {rot_driver:.3f}° "
        f"(< {min_angle_deg}°) — nothing was driven, so the ratio is undefined and "
        "this oracle would pass vacuously (drive a real angle through joint_a first)."
    )

    measured = rot_driven / rot_driver
    assert abs(measured - abs(expected_ratio)) <= ratio_tol, (
        f"gear coupled the bodies at ratio {measured:.4f} (driver {rot_driver:.3f}°, "
        f"driven {rot_driven:.3f}°), expected |ratio| = {abs(expected_ratio):.4f} "
        f"(±{ratio_tol}) — the relation did not propagate the promised gear ratio."
    )
    return measured


# ── Polymer-chain oracle ──────────────────────────────────────────────────────

def assert_polymer_chain(
    assembly_before,
    assembly_after,
    seed_joint_id: str,
    *,
    count: int,
    direction: str = "forward",
    tol_nm: float = 0.01,
    min_delta_nm: float = 0.5,
):
    """Geometric oracle for mate-seeded polymerize: the new copies march along the
    seed mate's repeat transform.

    ``/assembly/polymerize`` grows a chain of identical parts by replicating a seed
    mate (an :class:`AssemblyJoint` between two identical instances ``A`` / ``B``).
    The chain geometry is fully determined by the seed pair's world transforms:

        ``delta = T_B @ inv(T_A)``  (the part-to-part repeat),
        forward copy ``k`` sits at ``delta^k @ T_B``  (``k = 1 … n_forward``),
        backward copy ``k`` sits at ``inv(delta)^k @ T_A``  (``k = 1 … n_backward``).

    Pass the assembly *before* and *after* :func:`~backend.api.headless_assembly_build.polymerize`
    and the seed joint's id.  This asserts:

      1. **Right count.** Exactly ``count - 2`` new instances were added (the seed
         pair already counts as 2 of the chain length).
      2. **Each copy on the lattice.** Every new instance's world transform equals one
         of the analytically re-derived ``delta``-power transforms (matched as an
         id-independent multiset, within ``tol_nm``) — so a builder that dropped a
         copy, mis-ordered the chain, or used the wrong repeat fails.  The expected
         transforms are derived here from the seed pair only (NOT from the route's
         own chain helpers), so this is an independent check, not a tautology.
      3. **Chain actually spread (the can-go-red guard).** ``delta``'s translation
         magnitude exceeds ``min_delta_nm``; if the two seed parts were stacked
         (``delta ≈ I``) every copy would land on top of the seed and the oracle
         would pass vacuously — the analog of :func:`assert_mate_coincident`'s
         non-triviality guard.

    Direction-agnostic on *handedness* — it re-derives the documented forward/backward
    split (``count − 2`` new copies, extra-forward when ``both`` is odd) and checks the
    placed geometry, never a bend/twist sign.  Returns the 4×4 ``delta`` (numpy array).
    """
    import numpy as np

    inst_before = {i.id: i for i in assembly_before.instances}
    joint = next((j for j in assembly_before.joints if j.id == seed_joint_id), None)
    assert joint is not None, f"no seed joint {seed_joint_id!r} in the before-assembly"
    inst_a = inst_before.get(joint.instance_a_id)
    inst_b = inst_before.get(joint.instance_b_id)
    assert inst_a is not None and inst_b is not None, (
        "seed mate must join two existing instances (the polymerize seed pair)"
    )

    def _mat(inst):
        return np.array(inst.transform.values, dtype=float).reshape(4, 4)

    T_A, T_B = _mat(inst_a), _mat(inst_b)
    delta = T_B @ np.linalg.inv(T_A)
    delta_inv = np.linalg.inv(delta)

    assert float(np.linalg.norm(delta[:3, 3])) > min_delta_nm, (
        f"seed repeat delta is ~identity (translation "
        f"{float(np.linalg.norm(delta[:3, 3])):.4f} nm < {min_delta_nm} nm) — the two "
        "seed parts are stacked, so every copy lands on the seed and this oracle would "
        "pass vacuously (place the seed pair at a non-zero separation)."
    )

    # Re-derive the forward/backward split from the documented chain math.
    new_total = count - 2
    assert new_total >= 0, f"count must be ≥ 2, got {count}"
    if direction == "forward":
        n_forward, n_backward = new_total, 0
    elif direction == "backward":
        n_forward, n_backward = 0, new_total
    elif direction == "both":
        n_forward = (new_total + 1) // 2
        n_backward = new_total - n_forward
    else:
        raise ValueError(f"unknown direction {direction!r}")

    expected: list[np.ndarray] = []
    cur = T_B.copy()
    for _ in range(n_forward):
        cur = delta @ cur
        expected.append(cur.copy())
    cur = T_A.copy()
    for _ in range(n_backward):
        cur = delta_inv @ cur
        expected.append(cur.copy())

    before_ids = set(inst_before)
    new_instances = [i for i in assembly_after.instances if i.id not in before_ids]
    assert len(new_instances) == new_total, (
        f"polymerize added {len(new_instances)} new instances, expected {new_total} "
        f"(count {count}, direction {direction!r})."
    )

    # Match each expected transform to a distinct new instance (multiset / id-independent).
    remaining = list(new_instances)
    for T_exp in expected:
        match = next(
            (ni for ni in remaining if np.allclose(_mat(ni), T_exp, atol=tol_nm)),
            None,
        )
        assert match is not None, (
            "a new chain copy is missing from its expected repeat transform "
            f"(within {tol_nm} nm):\n{np.round(T_exp, 3)}"
        )
        remaining.remove(match)
    assert not remaining, (
        f"{len(remaining)} new instance(s) are not on the seed's repeat lattice — "
        "polymerize placed a copy off the chain."
    )
    return delta


# ── Overhang-binding referential-integrity oracle ─────────────────────────────

def assert_binding_resolves(
    assembly,
    binding_id: str,
    *,
    require_cross_part: bool = True,
):
    """Referential-integrity oracle: a cross-part overhang binding's two endpoints
    each resolve to a real overhang sub-domain on their part design.

    An :class:`AssemblyOverhangBinding` is pure metadata — a claim that
    ``sub_domain_a_id`` (on overhang ``overhang_a_id`` of instance A) is paired to
    ``sub_domain_b_id`` on instance B.  It applies no geometry, so the property to
    pin is that the claim's references are *valid* — and, crucially, that they stay
    valid across a ``.nass`` round-trip.  This is validation
    :func:`canonical_assembly` cannot provide: ``canonical_topology`` (the inline
    source fingerprint) does **not** fingerprint a design's overhangs or
    sub-domains, so a round-trip that regenerated a sub-domain id inside a part
    while the binding kept its stale id would slip past the structure fingerprint —
    only resolving the binding's endpoints against the actual part designs catches
    it.  Loading each side's design with the SAME ``_load_design_from_source``
    machinery the route uses, this asserts:

      1. **Both endpoints resolve.** For each side, the instance exists, its design
         carries an overhang with the binding's ``overhang_*_id``, and that overhang
         carries a sub-domain with the binding's ``sub_domain_*_id``.  A binding
         pointing at a dropped/renamed overhang or sub-domain fails here.
      2. **Non-degenerate.** The two endpoints reference distinct
         ``(instance, sub-domain)`` pairs (the route forbids self-binding); with
         ``require_cross_part`` (the default and the whole point of an *assembly*
         binding) the two instances differ.

    Pass the assembly *after* :func:`~backend.api.headless_assembly_build.bind_overhangs`
    (and, to prove durability, after a round-trip).
    """
    from backend.api.assembly import _assembly_source_path, _load_design_from_source

    binding = next((b for b in assembly.overhang_bindings if b.id == binding_id), None)
    assert binding is not None, f"no overhang binding {binding_id!r} in the assembly"

    asm_path = _assembly_source_path(assembly)

    def _resolve(instance_id: str, overhang_id: str, sub_domain_id: str, side: str):
        inst = next((i for i in assembly.instances if i.id == instance_id), None)
        assert inst is not None, (
            f"side {side}: binding instance {instance_id!r} is not in the assembly"
        )
        design = _load_design_from_source(inst.source, asm_path)
        ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
        assert ovhg is not None, (
            f"side {side}: overhang {overhang_id!r} no longer exists on part "
            f"{inst.name!r} — the binding references a dropped overhang."
        )
        assert any(sd.id == sub_domain_id for sd in (ovhg.sub_domains or [])), (
            f"side {side}: sub-domain {sub_domain_id!r} no longer exists on overhang "
            f"{overhang_id!r} of part {inst.name!r} — the binding references a "
            "dropped sub-domain (a round-trip that regenerated sub-domain ids would "
            "trip this, which canonical_assembly cannot see)."
        )

    _resolve(binding.instance_a_id, binding.overhang_a_id, binding.sub_domain_a_id, "A")
    _resolve(binding.instance_b_id, binding.overhang_b_id, binding.sub_domain_b_id, "B")

    key_a = (binding.instance_a_id, binding.sub_domain_a_id)
    key_b = (binding.instance_b_id, binding.sub_domain_b_id)
    assert key_a != key_b, (
        "binding pairs a sub-domain with itself — a degenerate (non-)binding."
    )
    if require_cross_part:
        assert binding.instance_a_id != binding.instance_b_id, (
            f"binding joins one instance to itself ({binding.instance_a_id!r}); an "
            "assembly overhang binding is meant to be cross-part."
        )


# ── Instance-layout oracles (parametric grid / ring placement) ────────────────

def _instance_origin(inst):
    """World origin (translation column) of a placed instance, as ``(x, y, z)``."""
    v = inst.transform.values
    return (float(v[3]), float(v[7]), float(v[11]))


def _project_to_plane(x: float, y: float, z: float, plane: str):
    """Project a world point onto a layout plane → ``(u, v)`` (mirrors
    ``instance_layout._embed``).  ``XY`` → ``(x, y)``; ``XZ`` → ``(x, z)``;
    ``YZ`` → ``(y, z)``."""
    p = plane.upper()
    if p == "XY":
        return (x, y)
    if p == "XZ":
        return (x, z)
    if p == "YZ":
        return (y, z)
    raise ValueError(f"plane must be one of XY/XZ/YZ, got {plane!r}")


def _cluster_1d(values, tol: float):
    """Greedily cluster sorted-1D values within ``tol``; return cluster centres."""
    centres: list[float] = []
    for val in sorted(values):
        if centres and abs(val - centres[-1]) <= tol:
            continue
        centres.append(val)
    return centres


def assert_instances_on_grid(
    assembly,
    rows: int,
    cols: int,
    *,
    pitch: float,
    row_pitch: float | None = None,
    plane: str = "XY",
    tol_nm: float = 0.01,
    min_pitch_nm: float = 0.05,
    instance_ids=None,
):
    """Geometric lattice oracle: the placed instance origins form an exact
    ``rows × cols`` regular grid.

    The layout analog of :func:`assert_circular_disc` — it reads the *placed*
    instance transforms (their world origins), not the layout spec, so it pins the
    whole path ``spec → instance_layout → place_grid → add_instance → placed
    geometry``.  The expected lattice is re-derived from the user-facing
    parameters (``rows``/``cols``/``pitch``) as *properties* of the result, not by
    re-running the placement formula, so a builder bug (wrong pitch, dropped slot,
    transposed axes) is caught rather than mirrored:

      1. **Right count.** Exactly ``rows · cols`` instances (filtered to
         ``instance_ids`` if given).
      2. **Regular spacing.** Projected onto ``plane``, the origins occupy exactly
         ``cols`` distinct ``u`` values evenly spaced by ``pitch`` and ``rows``
         distinct ``v`` values evenly spaced by ``row_pitch`` (default ``pitch``),
         each within ``tol_nm``.
      3. **Every cell filled.** The distinct ``(u, v)`` slot pairs number exactly
         ``rows · cols`` — no two parts share a cell while another is empty.
      4. **Non-degenerate (the can-go-red guard).** The requested pitch exceeds
         ``min_pitch_nm``; a zero pitch would stack every copy and the "spacing ==
         pitch" check would pass vacuously.  The analog of
         :func:`assert_mate_coincident`'s separation guard.

    Returns the ``(u_centres, v_centres)`` it measured.
    """
    rp = pitch if row_pitch is None else row_pitch
    assert pitch > min_pitch_nm and rp > min_pitch_nm, (
        f"requested pitch ({pitch}, {rp} nm) is below the non-degeneracy floor "
        f"{min_pitch_nm} nm — the parts would stack and this oracle would pass "
        "vacuously."
    )

    insts = [
        i for i in assembly.instances
        if instance_ids is None or i.id in set(instance_ids)
    ]
    assert len(insts) == rows * cols, (
        f"grid placed {len(insts)} instances, expected {rows}×{cols} = {rows * cols}."
    )

    uv = [_project_to_plane(*_instance_origin(i), plane) for i in insts]
    u_centres = _cluster_1d((u for u, _ in uv), tol_nm)
    v_centres = _cluster_1d((v for _, v in uv), tol_nm)
    assert len(u_centres) == cols, (
        f"grid has {len(u_centres)} distinct column positions, expected {cols} "
        f"(u={[round(c, 3) for c in u_centres]})."
    )
    assert len(v_centres) == rows, (
        f"grid has {len(v_centres)} distinct row positions, expected {rows} "
        f"(v={[round(c, 3) for c in v_centres]})."
    )

    for a, b in zip(u_centres, u_centres[1:]):
        assert abs((b - a) - pitch) <= tol_nm, (
            f"column spacing {b - a:.4f} nm ≠ pitch {pitch} nm (±{tol_nm}) — "
            "the grid columns are not evenly spaced at the requested pitch."
        )
    for a, b in zip(v_centres, v_centres[1:]):
        assert abs((b - a) - rp) <= tol_nm, (
            f"row spacing {b - a:.4f} nm ≠ row_pitch {rp} nm (±{tol_nm}) — "
            "the grid rows are not evenly spaced at the requested pitch."
        )

    def _nearest(centres, val):
        return min(range(len(centres)), key=lambda k: abs(centres[k] - val))

    slots = {(_nearest(u_centres, u), _nearest(v_centres, v)) for u, v in uv}
    assert len(slots) == rows * cols, (
        f"grid origins occupy {len(slots)} distinct cells, expected {rows * cols} "
        "— some cell is doubled while another is empty."
    )
    return u_centres, v_centres


def assert_instances_on_ring(
    assembly,
    n: int,
    *,
    radius: float,
    plane: str = "XY",
    center=(0.0, 0.0, 0.0),
    tol_nm: float = 0.01,
    angle_tol_deg: float = 1.0,
    min_radius_nm: float = 0.5,
    instance_ids=None,
):
    """Geometric lattice oracle: the placed instance origins lie on a ring of the
    requested radius at an even angular step.

    The ring analog of :func:`assert_instances_on_grid` — it reads the *placed*
    instance origins and asserts, as properties re-derived from the user-facing
    ``n``/``radius`` (not by re-running the placement formula):

      1. **Right count.** Exactly ``n`` instances (filtered to ``instance_ids``).
      2. **On the ring.** Every origin, projected onto ``plane`` and measured from
         ``center``, is at distance ``radius`` within ``tol_nm``.
      3. **Even angular step.** Sorted by angle, consecutive slots (including the
         wrap from last back to first) differ by exactly ``360°/n`` within
         ``angle_tol_deg``.
      4. **Non-degenerate (the can-go-red guard).** ``radius`` exceeds
         ``min_radius_nm``; a zero radius would stack every copy at ``center`` where
         "distance == radius == 0" passes vacuously — the load-bearing guard for a
         ring (the analog of :func:`assert_polymer_chain`'s ``min_delta`` guard).

    Returns the per-slot radii it measured.
    """
    import math

    assert radius > min_radius_nm, (
        f"requested radius {radius} nm is below the non-degeneracy floor "
        f"{min_radius_nm} nm — the parts would stack at the centre and this oracle "
        "would pass vacuously."
    )

    insts = [
        i for i in assembly.instances
        if instance_ids is None or i.id in set(instance_ids)
    ]
    assert len(insts) == n, f"ring placed {len(insts)} instances, expected {n}."

    cu, cv = _project_to_plane(*(float(c) for c in center), plane)
    radii: list[float] = []
    angles: list[float] = []
    for i in insts:
        u, v = _project_to_plane(*_instance_origin(i), plane)
        du, dv = u - cu, v - cv
        r = math.hypot(du, dv)
        assert abs(r - radius) <= tol_nm, (
            f"a ring instance is {r:.4f} nm from the centre, expected radius "
            f"{radius} nm (±{tol_nm}) — it is off the ring."
        )
        radii.append(r)
        angles.append(math.atan2(dv, du) % (2.0 * math.pi))

    angles.sort()
    step = 2.0 * math.pi / n
    tol = math.radians(angle_tol_deg)
    diffs = [b - a for a, b in zip(angles, angles[1:])]
    diffs.append(angles[0] + 2.0 * math.pi - angles[-1])  # wrap last → first
    for d in diffs:
        assert abs(d - step) <= tol, (
            f"ring angular step {math.degrees(d):.3f}° ≠ {math.degrees(step):.3f}° "
            f"(±{angle_tol_deg}°) — the slots are not evenly spaced around the ring."
        )
    return radii


# ── Inverse-pair oracle ───────────────────────────────────────────────────────

def assert_inverse_pair(
    start: Design,
    forward: Callable[[], Design],
    inverse: Callable[[], Design],
) -> Design:
    """Inverse-pair invariant: an op then its inverse is topology-identity.

    ``start`` is the design *before* the operation (it must already validate).
    ``forward`` applies the op and ``inverse`` applies its inverse — each returns
    the resulting design.  In practice these are headless wrappers driving the
    active session, e.g. ``lambda: nick(h, bp, d)`` / ``lambda: ligate(h, bp, d)``.

    Asserts, in order:

      1. ``start`` passes :func:`validate_design`;
      2. the design *between* ``forward`` and ``inverse`` validates **and** its
         :func:`canonical_topology` actually differs from ``start`` — proving the
         forward op did something (an inverse pair over a no-op would pass
         vacuously, so this guard is what lets the oracle go red);
      3. after ``inverse`` the design validates and its :func:`canonical_topology`
         is byte-for-byte equal to ``start``.

    Returns the post-inverse design.  Reusable for any add/delete or +δ/−δ pair
    (nick↔ligate, loop +δ↔−δ, …).
    """
    before = canonical_topology(start)
    report0 = validate_design(start)
    assert report0.passed, f"start design did not validate before the op:\n{report0}"

    mid = forward()
    report1 = validate_design(mid)
    assert report1.passed, f"design did not validate after the forward op:\n{report1}"
    assert canonical_topology(mid) != before, (
        "forward op did not change the topology — an inverse pair over a no-op "
        "passes vacuously; pick an operation that actually mutates the design."
    )

    end = inverse()
    report2 = validate_design(end)
    assert report2.passed, f"design did not validate after the inverse op:\n{report2}"
    after = canonical_topology(end)
    assert after == before, (
        "forward then inverse changed the topology — the ops are not inverses for "
        f"this input. helices {len(before[0])}→{len(after[0])}, "
        f"strands {len(before[1])}→{len(after[1])}."
    )
    return end


# ── Geometric length oracle ───────────────────────────────────────────────────

def geometric_nucleotide_count(design: Design, helix_id: str | None = None) -> int:
    """Number of nucleotides the geometry kernel emits for *design*.

    This is the geometry layer's own count — the same ``_geometry_for_design``
    kernel that feeds ``GET /design/geometry`` — so it honours loop/skip marks: a
    skip removes a bp (one fewer nucleotide per strand), a loop adds one.  A duplex
    bp carries two strands (forward + reverse), so a clean bundle's count is twice
    its bp total.  With *helix_id*, counts only that helix's nucleotides.
    """
    nucs = _geometry_for_design(design)
    if helix_id is None:
        return len(nucs)
    return sum(1 for n in nucs if n.get("helix_id") == helix_id)


def assert_geometric_length_delta(
    start: Design,
    op: Callable[[], Design],
    expected_bp_delta: int,
    *,
    helix_id: str | None = None,
    strands_per_bp: int = 2,
) -> Design:
    """Length oracle: *op* changes the geometric nucleotide count by exactly the
    declared amount.

    ``op`` runs a headless mutation on the active design and returns the result;
    *start* is the design *before* it.  Asserts the geometry kernel's nucleotide
    count changed by ``expected_bp_delta`` bp — times ``strands_per_bp`` (geometry
    emits one nucleotide per strand per bp, and a duplex bp carries two strands).

    This pins the topology→geometry conservation law for length-changing ops: a
    loop of ``+δ`` must add δ bp of geometry, a skip of ``−δ`` must remove δ bp, and
    a removal (``delta=0``) must restore the baseline.  It is **direction-agnostic**
    — it counts *how many* nucleotides changed, never *which way* a deformation
    bends — so it is safe to reuse on bend/twist apply without reasoning about sign
    or frame conventions (which ``CLAUDE.md`` says to ask the user about).

    Pass *helix_id* to scope the count to one helix — the strong form for bulk
    apply, where the global net delta may cancel to ~0 but each helix's marks must
    still be reflected one-for-one in its own geometry.

    Returns the post-op design for further assertions.
    """
    before = geometric_nucleotide_count(start, helix_id)
    result = op()
    after = geometric_nucleotide_count(result, helix_id)
    actual = after - before
    expected = expected_bp_delta * strands_per_bp
    where = f" on helix {helix_id}" if helix_id is not None else ""
    assert actual == expected, (
        f"geometric length changed by {actual} nucleotides{where}, expected "
        f"{expected} ({expected_bp_delta:+d} bp × {strands_per_bp} strands/bp) — "
        "the op's effect on the strand graph is not faithfully reflected in geometry."
    )
    return result


# ── Circularity oracle (parametric disc primitives) ───────────────────────────

def assert_circular_disc(
    design: Design,
    requested_radius_nm: float,
    *,
    max_spread_nm: float = 0.5,
    radius_tol_nm: float = 0.5,
    helix_ids: set[str] | None = None,
) -> list[int]:
    """Geometric oracle: a built disc's helices actually trace a circle of the
    requested radius.

    Reads the *geometry* of the placed helices (their axis-endpoint spans, not a
    stored ``length_bp`` field) so it pins the full headless path
    ``radius → footprint → route → builder → placed geometry`` end-to-end — the
    pure circularity functions (:mod:`backend.core.circle_primitive`) only pin the
    footprint math in isolation.  Each helix's bp length is its axis span /
    rise; the helices are ordered by lattice column (the disc is a contiguous,
    centre-symmetric row), then fed to the existing circularity oracle:

      1. :func:`circularity_spread` < ``max_spread_nm`` — every column's implied
         radius ``√(x² + (L/2)²)`` agrees to within tolerance (a true circle has
         zero spread);
      2. :func:`fit_radius` is within ``radius_tol_nm`` of ``requested_radius_nm``
         — asking for radius R lands a disc of radius ≈ R.

    Pass *helix_ids* to assess only the disc helices when the design also carries
    pre-existing DNA; default assesses every helix (a clean scratch build).
    Returns the per-column bp lengths it measured.
    """
    from backend.core.circle_primitive import circularity_spread, fit_radius

    helices = [
        h for h in design.helices
        if (helix_ids is None or h.id in helix_ids) and h.grid_pos is not None
    ]
    assert helices, "no disc helices found to assess circularity"
    helices.sort(key=lambda h: h.grid_pos[1])

    lengths: list[int] = []
    for h in helices:
        dx = h.axis_end.x - h.axis_start.x
        dy = h.axis_end.y - h.axis_start.y
        dz = h.axis_end.z - h.axis_start.z
        span_nm = (dx * dx + dy * dy + dz * dz) ** 0.5
        lengths.append(round(span_nm / BDNA_RISE_PER_BP))

    spread = circularity_spread(lengths)
    assert spread < max_spread_nm, (
        f"placed disc is not circular: circularity spread {spread:.3f} nm "
        f"(implied per-column radii disagree by more than {max_spread_nm} nm) — "
        f"lengths={lengths}"
    )
    fitted = fit_radius(lengths)
    assert abs(fitted - requested_radius_nm) <= radius_tol_nm, (
        f"placed disc radius {fitted:.3f} nm differs from the requested "
        f"{requested_radius_nm} nm by more than {radius_tol_nm} nm — "
        f"the radius→geometry path is off."
    )
    return lengths


# ── Deformed-placement oracle (continuation onto a bent/twisted frame) ─────────

def assert_on_deformed_frame(
    design_before: Design,
    design_after: Design,
    source_bp: int,
    cells,
    *,
    ref_helix_id: str | None = None,
    pos_tol_nm: float = 0.02,
    min_deflection_nm: float = 0.5,
) -> float:
    """Geometric oracle: a deformed continuation's new helices land on the DEFORMED
    cross-section frame at ``source_bp`` — and *not* where a straight extrude would
    put them.

    A ``bundle-deformed-continuation`` places each new helix's ``axis_start`` at the
    cross-section grid point ``grid_origin + frame_right·lx + frame_up·ly`` of the
    deformed frame sampled at ``source_bp``.  This oracle pins the whole headless
    path ``source_bp → deformed-frame → route → builder → placed geometry`` by:

      1. **On the deformed frame.** Independently re-derives the deformed frame
         (:func:`deformed_frame_at_bp` on *design_before*, the same input the route
         uses when ``source_bp`` is set) and the per-cell placement, then asserts
         every newly-appended helix's ``axis_start`` matches its cell's deformed
         placement to within ``pos_tol_nm``.  A builder that mis-applied the frame
         (swapped right/up, wrong lattice pitch, used the *straight* blunt-end
         instead of the frame) fails here.
      2. **Not the straight frame (the can-go-red guard).** Recomputes the same
         placement on a copy of *design_before* with its deformations stripped (the
         frame a plain continuation would use) and asserts the deformed placement is
         displaced from it by more than ``min_deflection_nm`` for at least one cell.
         Without this the oracle would pass vacuously on an un-deformed design — it
         is the analog of :func:`assert_inverse_pair`'s "forward really mutated"
         guard.

    Direction-agnostic: it only measures *that* the placement moved and *where* it
    landed, never reasoning about bend/twist sign or frame handedness (which
    ``CLAUDE.md`` reserves for the user).  ``cells`` is the ``(row, col)`` list
    passed to the continuation; *design_before* is the design *before* it ran.
    Returns the maximum deformed-vs-straight deflection (nm) it observed.
    """
    import numpy as np

    from backend.core.deformation import deformed_frame_at_bp
    from backend.core.lattice import honeycomb_position

    before_ids = {h.id for h in design_before.helices}
    new_helices = [h for h in design_after.helices if h.id not in before_ids]
    cells = [tuple(c) for c in cells]
    assert len(new_helices) == len(cells), (
        f"expected one appended helix per cell ({len(cells)}), got {len(new_helices)}"
    )

    def _placements(design):
        frame = deformed_frame_at_bp(design, source_bp, ref_helix_id)
        origin = np.array(frame["grid_origin"], dtype=float)
        right = np.array(frame["frame_right"], dtype=float)
        up = np.array(frame["frame_up"], dtype=float)
        out = {}
        for row, col in cells:
            lx, ly = honeycomb_position(row, col)
            out[(row, col)] = origin + right * lx + up * ly
        return out

    deformed = _placements(design_before)
    straight_design = design_before.model_copy(deep=True)
    straight_design.deformations = []
    straight = _placements(straight_design)

    # Each new helix must sit on exactly one cell's deformed placement.
    remaining = dict(deformed)
    for h in new_helices:
        start = np.array([h.axis_start.x, h.axis_start.y, h.axis_start.z])
        hit = None
        for cell, p in remaining.items():
            if float(np.linalg.norm(start - p)) <= pos_tol_nm:
                hit = cell
                break
        assert hit is not None, (
            f"new helix {h.id} at {start.tolist()} is not within {pos_tol_nm} nm of "
            f"any deformed-frame cell placement {[p.tolist() for p in remaining.values()]} "
            "— the continuation did not land on the deformed cross-section."
        )
        del remaining[hit]

    max_deflection = max(
        float(np.linalg.norm(deformed[cell] - straight[cell])) for cell in deformed
    )
    assert max_deflection > min_deflection_nm, (
        f"deformed placement differs from a straight extrude by at most "
        f"{max_deflection:.3f} nm (< {min_deflection_nm} nm) — the deformation had no "
        "geometric effect, so this oracle would pass vacuously (use a design with a "
        "real bend/twist, or this is a bug where source_bp was ignored)."
    )
    return max_deflection


# ── Deformation-angle oracle (bend/twist magnitude) ───────────────────────────

def assert_deformation_angle(
    design_after: Design,
    plane_a_bp: int,
    plane_b_bp: int,
    expected_total_deg: float,
    *,
    ref_helix_id: str | None = None,
    angle_tol_deg: float = 1.0,
    step_bp: int = 1,
    min_angle_deg: float = 5.0,
) -> float:
    """Geometric magnitude oracle: a bend/twist rotates the deformed cross-section
    frame by exactly the requested total angle across ``[plane_a_bp, plane_b_bp]``.

    *design_after* is the design *after* the deformation was added (e.g. via
    :func:`backend.api.headless_build.add_bend` / :func:`~.add_twist`).  The oracle
    walks the deformed frame (:func:`deformed_frame_at_bp`) in ``step_bp`` bp
    increments from ``plane_a_bp`` to ``plane_b_bp`` and **sums the magnitude of
    each step's relative frame rotation** (the angle of ``R(p₁)·R(p₀)ᵀ``, taken from
    the orthonormal frame ``[frame_right | frame_up | axis_dir]``).  Summing per-step
    magnitudes — rather than the single ``plane_a→plane_b`` relative rotation —
    UNWRAPS angles past 180°/360°: a 540° twist reads as 540°, not 180°.  It pins the
    whole headless path ``request → route → DeformationOp → deformed frame``:

      1. **Matches the request.** The accumulated rotation is within
         ``angle_tol_deg`` of ``expected_total_deg`` — for a bend that is
         ``curvature_deg_per_bp × (plane_b − plane_a)``; for a twist the total twist
         (``total_degrees``, or ``degrees_per_nm × span_nm``).  A builder that scaled
         the curvature wrong, ignored the planes, or dropped the op fails here.
      2. **Is non-trivial (the can-go-red guard).** The measured angle exceeds
         ``min_angle_deg``, so the oracle FAILS on an un-deformed design instead of
         passing vacuously — the analog of :func:`assert_inverse_pair`'s "forward
         really mutated" guard.

    **Direction-agnostic by construction:** it measures only the *magnitude* of the
    frame rotation (an ``arccos`` is always ≥ 0), never the bend/twist sign or frame
    handedness — which ``CLAUDE.md`` reserves for the user.  Pass *ref_helix_id* to
    sample the arm containing that helix.  Returns the measured cumulative angle (°).
    """
    import numpy as np

    from backend.core.deformation import deformed_frame_at_bp

    assert plane_b_bp > plane_a_bp, "plane_b_bp must be greater than plane_a_bp"

    def _frame_R(bp: int):
        f = deformed_frame_at_bp(design_after, bp, ref_helix_id)
        return np.column_stack([f["frame_right"], f["frame_up"], f["axis_dir"]])

    bps = list(range(plane_a_bp, plane_b_bp, step_bp))
    if bps[-1] != plane_b_bp:
        bps.append(plane_b_bp)

    total = 0.0
    for p0, p1 in zip(bps, bps[1:]):
        M = _frame_R(p1) @ _frame_R(p0).T
        cos = (float(np.trace(M)) - 1.0) / 2.0
        total += float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))

    assert total > min_angle_deg, (
        f"deformed frame rotated by only {total:.3f}° across "
        f"[{plane_a_bp}, {plane_b_bp}] (< {min_angle_deg}°) — the design appears "
        "un-deformed, so this oracle would pass vacuously (apply a real bend/twist "
        "first, or the planes/params were ignored)."
    )
    assert abs(total - expected_total_deg) <= angle_tol_deg, (
        f"deformed frame rotated by {total:.3f}° across "
        f"[{plane_a_bp}, {plane_b_bp}], expected {expected_total_deg:.3f}° "
        f"(±{angle_tol_deg}°) — the realised curvature does not match the request."
    )
    return total


# ── Headless-coverage audit ───────────────────────────────────────────────────

_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def headless_coverage_report() -> dict:
    """Automated audit: design/assembly mutation routes vs. headless wrappers.

    A route counts as *covered* when its endpoint function is imported by
    :mod:`backend.api.headless_build` (design ops) or
    :mod:`backend.api.headless_assembly_build` (assembly ops) — every wrapper
    there pulls in the exact route handler it drives (e.g.
    ``create_bundle as _route_create_bundle``).  Matching by the function object,
    not by a string, means this report tracks reality automatically: add a wrapper
    and the route flips to covered; rename a route and nothing silently rots.

    Returns ``{total, covered, uncovered, covered_routes, uncovered_routes}``
    where each ``*_routes`` entry is ``{"methods", "path", "endpoint"}`` sorted by
    path.  ``uncovered_routes`` is the live backlog of AF wrapper candidates.
    """
    from backend.api import headless_assembly_build, headless_build
    from backend.api.main import app

    wrapped_fns = {
        obj
        for module in (headless_build, headless_assembly_build)
        for obj in vars(module).values()
        if inspect.isfunction(obj)
    }

    covered_routes: list[dict] = []
    uncovered_routes: list[dict] = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods or not (methods & _MUTATION_METHODS):
            continue
        if "/design" not in path and "/assembly" not in path:
            continue
        row = {
            "methods": sorted(methods & _MUTATION_METHODS),
            "path": path,
            "endpoint": route.endpoint.__name__,
        }
        (covered_routes if route.endpoint in wrapped_fns else uncovered_routes).append(row)

    covered_routes.sort(key=lambda r: r["path"])
    uncovered_routes.sort(key=lambda r: r["path"])
    total = len(covered_routes) + len(uncovered_routes)
    return {
        "total": total,
        "covered": len(covered_routes),
        "uncovered": len(uncovered_routes),
        "covered_routes": covered_routes,
        "uncovered_routes": uncovered_routes,
    }
