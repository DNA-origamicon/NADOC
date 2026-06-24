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
import math
from typing import Callable

from backend.api import state as design_state
from backend.api.crud import DesignImportRequest, import_design
from backend.api.headless_build import scratch_session
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design
from backend.core.oxdna_health import RMSF_PRELIM_FRAMES
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


def assert_periodic_chain_tiles(
    assembly,
    *,
    tol_nm: float = 0.05,
    step_tol_nm: float = 0.05,
    angle_tol_deg: float = 0.5,
    min_step_nm: float = 0.5,
) -> dict:
    """Geometric oracle for *periodic* polymerize: one DERIVED repeat unit tiles the
    whole chain seamlessly.

    ``/assembly/polymerize-periodic`` (``hab.polymerize_periodic``) grows a chain from
    a SINGLE seed instance — there is no hand-defined seed mate.  The repeat transform
    ``delta`` is *derived* from the part's own ``is_periodic_seam`` geometry
    (``derive_periodic_delta``, a Kabsch fit over the seam cross-sections), and copy
    ``k`` is placed at ``T_seed @ delta**k``.  Consecutive copies are tied by
    synthesized **rigid** seam joints (``seam0:3p`` on the low copy → ``seam0:5p`` on
    the high copy).  This is fundamentally different from :func:`assert_polymer_chain`
    (mate-seeded, where the repeat is re-derived from two existing instances): here the
    load-bearing claim is that the *auto-derived* delta actually tiles, at **every**
    junction, not just the one (or two seams) it was fit over.

    Pass the assembly *after* :func:`~backend.api.headless_assembly_build.polymerize_periodic`
    (optionally after :func:`resolve`).  This asserts, over the chain's rigid seam
    junctions:

      1. **A chain was grown.** At least one rigid seam junction exists (else nothing
         was polymerized — the non-emptiness guard).
      2. **Seamless tiling at every junction.** For each junction the low copy's
         ``seam0:3p`` world position coincides with the high copy's ``seam0:5p`` world
         position within ``tol_nm``, resolved with the SAME ``_get_connector_world``
         machinery ``resolve_assembly`` uses (on the instance-overridden design) — so a
         derived delta that docks the seam it was fit on but drifts at later copies, or
         a chain whose copies were placed off the repeat, fails here.
      3. **A single repeat unit (the periodicity invariant).** Every junction's world
         repeat ``T_high @ inv(T_low)`` has the SAME translation length (within
         ``step_tol_nm``) and the same rotation angle (within ``angle_tol_deg``).  This
         is what distinguishes a *periodic* chain from a bag of independent mates: one
         transform repeats.  Magnitudes only → direction-agnostic (forward ``delta`` and
         backward ``delta_inv`` share length + angle, so it holds for any ``direction``).
      4. **Genuine tiling (the can-go-red guard).** That common step length exceeds
         ``min_step_nm``; a degenerate ``delta ≈ I`` would stack every copy on the seed
         and pass vacuously — the analog of :func:`assert_mate_coincident`'s
         non-triviality guard.

    Returns ``{n_junctions, max_gap_nm, step_nm, angle_deg}``.
    """
    import numpy as np

    from backend.api.assembly import _assembly_source_path, _design_with_instance_overrides
    from backend.core.assembly_connectors import _get_connector_world

    inst_by_id = {i.id: i for i in assembly.instances}
    junctions = [
        j for j in assembly.joints
        if j.joint_type == "rigid"
        and (j.connector_a_label or "").startswith("seam0:")
        and (j.connector_b_label or "").startswith("seam0:")
        and j.instance_a_id in inst_by_id and j.instance_b_id in inst_by_id
    ]
    assert junctions, (
        "no rigid periodic-seam junctions in the assembly — nothing was polymerized "
        "(or the seam joints lost their seam0:* connector labels)."
    )

    asm_path = _assembly_source_path(assembly)

    def _mat(inst):
        return np.array(inst.transform.values, dtype=float).reshape(4, 4)

    gaps: list[float] = []
    steps: list[float] = []
    angles: list[float] = []
    for j in junctions:
        a = inst_by_id[j.instance_a_id]   # low copy, presents seam0:3p
        b = inst_by_id[j.instance_b_id]   # high copy, presents seam0:5p
        design_a = _design_with_instance_overrides(a, asm_path)
        design_b = _design_with_instance_overrides(b, asm_path)
        ca = _get_connector_world(a, j.connector_a_label, design_a)
        cb = _get_connector_world(b, j.connector_b_label, design_b)
        assert ca is not None and cb is not None, (
            "could not resolve a seam connector world position "
            f"(a={j.connector_a_label!r}→{ca}, b={j.connector_b_label!r}→{cb})"
        )
        gaps.append(float(np.linalg.norm(np.asarray(ca) - np.asarray(cb))))

        repeat = _mat(b) @ np.linalg.inv(_mat(a))
        steps.append(float(np.linalg.norm(repeat[:3, 3])))
        cos_t = max(-1.0, min(1.0, (float(np.trace(repeat[:3, :3])) - 1.0) / 2.0))
        angles.append(float(np.degrees(np.arccos(cos_t))))

    max_gap = max(gaps)
    assert max_gap <= tol_nm, (
        f"a periodic seam junction is {max_gap:.4f} nm open (> {tol_nm} nm) — the "
        "derived repeat transform does not tile the chain seamlessly (copy k's 3' seam "
        "does not meet copy k+1's 5' seam)."
    )

    step = float(np.mean(steps))
    assert max(abs(s - step) for s in steps) <= step_tol_nm, (
        f"the chain's per-junction step length varies ({min(steps):.3f}…{max(steps):.3f} "
        f"nm, tol {step_tol_nm}) — the chain is not a single repeating unit."
    )
    angle = float(np.mean(angles))
    assert max(abs(a - angle) for a in angles) <= angle_tol_deg, (
        f"the chain's per-junction rotation varies ({min(angles):.3f}…{max(angles):.3f}°, "
        f"tol {angle_tol_deg}) — the chain is not a single repeating unit."
    )
    assert step > min_step_nm, (
        f"the periodic repeat is ~identity (step {step:.4f} nm < {min_step_nm} nm) — "
        "every copy is stacked on the seed, so this oracle would pass vacuously (use a "
        "part whose seam-to-seam length is non-zero)."
    )
    return {"n_junctions": len(junctions), "max_gap_nm": max_gap,
            "step_nm": step, "angle_deg": angle}


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


# ── File-backed part oracle (AF-12 — build from a saved validated primitive) ──

def assert_part_from_file(assembly, instance_id, expected_topology):
    """AF-12: a file-backed part instance resolves to **exactly** the saved ``.nadoc``'s
    validated topology — proving ``{"from_file": …}`` instances the intended primitive
    and nothing silently substituted for it.

    This is the LOAD-BEARING pin for the ``from_file`` grammar, and it is validation
    :func:`canonical_assembly` cannot provide: a *file* instance is fingerprinted by
    ``("file", path, sha256)`` only — the fingerprint NEVER loads the design behind the
    path — so a spec that wired the wrong path, or whose file was edited/renamed after
    authoring, still matches :func:`assert_spec_matches_calls`.  Here we LOAD the design
    the instance actually references (via the same ``_load_design_from_source`` machinery
    the assembly routes use) and compare its :func:`canonical_topology` to the topology
    of the design that was saved (pass ``expected_topology = canonical_topology(saved)``).

    Asserts the instance exists, is genuinely file-backed (an inline instance defeats the
    point — that would be an embedded copy, not a reference), and resolves to
    ``expected_topology``.  Returns the resolved :class:`~backend.core.models.Design`.
    Can-go-red: a wrong/edited primitive resolves to a different topology → mismatch.
    """
    from backend.api.assembly import _assembly_source_path, _load_design_from_source

    inst = next((i for i in assembly.instances if i.id == instance_id), None)
    assert inst is not None, f"no instance {instance_id!r} in the assembly"
    assert getattr(inst.source, "type", None) == "file", (
        f"instance {inst.name!r} is not file-backed (source type "
        f"{getattr(inst.source, 'type', None)!r}) — assert_part_from_file pins the "
        "from_file grammar; an inline instance is an embedded copy, not a reference."
    )
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    actual = canonical_topology(design)
    assert actual == expected_topology, (
        f"file-backed part {inst.name!r} resolved to a DIFFERENT topology than the "
        "saved primitive — a stale/edited/wrong-path file silently substituted. "
        "(canonical_assembly keys a file source by path only and cannot catch this.)"
    )
    return design


def assert_instances_from_file(assembly, expected_topology, *, instance_ids=None):
    """AF-12 follow-up: **every** instance of a (file-backed) parametric layout resolves
    to exactly the saved primitive's validated topology — the layout-AGNOSTIC source pin
    that composes with :func:`assert_instances_on_grid` / :func:`assert_instances_on_ring`
    (which pin the *lattice* but are blind to the part source) to fully pin a file-backed
    ``place_grid`` / ``place_ring``.

    The plural of :func:`assert_part_from_file`: a single-slot check leaves the rest of a
    layout UNPROVEN.  A builder that file-backed only the first slot and embedded inline
    copies for the others (silently defeating the by-reference purpose — ``rows·cols``
    embedded designs instead of one path), or that substituted a wrong path partway
    through, would pass a one-slot pin while every lattice check (which never loads the
    design) still goes green.  This LOADS the design behind every selected instance and
    asserts each is file-backed and resolves to ``expected_topology`` (pass
    ``expected_topology = canonical_topology(saved)``).

    Filtered to ``instance_ids`` if given (else every instance).  Returns the number of
    instances proven.  Can-go-red: an inline / wrong-topology slot anywhere in the layout
    → :func:`assert_part_from_file` raises; an empty selection → the non-vacuity guard.
    """
    insts = [
        i for i in assembly.instances
        if instance_ids is None or i.id in set(instance_ids)
    ]
    assert insts, (
        "assert_instances_from_file selected no instances — nothing to prove (build the "
        "layout first, or pass the placed instance_ids); a vacuous pass is not validation."
    )
    for inst in insts:
        assert_part_from_file(assembly, inst.id, expected_topology)
    return len(insts)


def assert_part_from_primitive(assembly, instance_id, primitive_name, primitives_dir):
    """AF-12 Phase 2: a ``{"from_primitive": "<name>"}`` part instance resolves to **exactly**
    the catalog primitive of that name — proving the grammar's *name→catalog-path resolver*
    picked the right primitive and nothing silently substituted for it.

    This is the load-bearing pin for the ``from_primitive`` grammar, and it adds a check
    ``from_file``'s :func:`assert_part_from_file` cannot: that one trusts a path already on
    the instance; here the **catalog NAME** is the input, so a resolver that mapped the name
    to the wrong/renamed primitive, or to nothing, must be caught.  We *independently*
    re-resolve ``primitive_name`` through the catalog (:func:`primitive_catalog.design_path`,
    NOT the interpreter's own resolution), load that primitive's saved ``.nadoc``, compute
    its :func:`canonical_topology`, and delegate to :func:`assert_part_from_file` — which
    loads the design the *instance* actually references and compares.  So if the build wired
    a different primitive than the name claims, the two topologies diverge and this raises.

    ``primitives_dir`` is the catalog folder (pass the same one handed to ``build_assembly``).
    Asserts the name resolves in the catalog, the instance is genuinely file-backed, and it
    resolves to the named primitive's topology.  Returns the resolved
    :class:`~backend.core.models.Design`.  Can-go-red: a name pointing at a different/renamed
    primitive → topology mismatch; an unknown name → the catalog-resolution guard.
    """
    from pathlib import Path

    from backend.core import primitive_catalog as _pc

    path = _pc.design_path(Path(primitives_dir), primitive_name)
    assert path is not None, (
        f"catalog has no primitive named {primitive_name!r} in {primitives_dir} — "
        "assert_part_from_primitive cannot re-resolve the name; the from_primitive build "
        "should itself have raised BuildSpecError for an unknown name."
    )
    saved = Design.from_json(path.read_text(encoding="utf-8"))
    return assert_part_from_file(assembly, instance_id, canonical_topology(saved))


def assert_part_is_circular_disc(
    assembly,
    instance_id,
    requested_radius_nm,
    *,
    max_spread_nm=0.5,
    radius_tol_nm=0.5,
):
    """AF-12 Phase 2b: a ``{"from_primitive": "<circle>", "params": {"radius_nm": R}}`` part
    instance is a GENERATIVELY-built circular disc of radius ≈ R — the parametric counterpart
    to :func:`assert_part_from_primitive` (which is file-backed-only and would *fail* on this
    inline part).

    A parametric primitive is not file-referenced: the driver re-derives the disc at the
    requested radius and embeds it INLINE, so the load-bearing check is geometric, not a
    source pin.  We assert the instance is genuinely inline-backed (a parametric primitive
    that resolved to a *file* would be the wrong build path — the saved default-radius disc
    instead of the requested one), load the design the instance embeds (via the same
    ``_load_design_from_source`` the assembly routes use), and delegate to the AF-4
    :func:`assert_circular_disc` geometric oracle — which reads the placed helices' axis
    geometry and proves they trace a circle of the requested radius.

    This pins the full ``params.radius_nm → footprint → circle_segment → placed geometry``
    path *through the assembly layer* — something :func:`canonical_assembly` (which keys an
    inline source by its embedded topology fingerprint, blind to whether that geometry is
    actually circular *of the requested radius*) cannot.  Returns the resolved
    :class:`~backend.core.models.Design`.  Can-go-red: a wrong requested radius → the
    circularity/radius assertion fails; a file-backed (static) instance → the inline guard.
    """
    from backend.api.assembly import _assembly_source_path, _load_design_from_source

    inst = next((i for i in assembly.instances if i.id == instance_id), None)
    assert inst is not None, f"no instance {instance_id!r} in the assembly"
    assert getattr(inst.source, "type", None) == "inline", (
        f"instance {inst.name!r} is not inline-backed (source type "
        f"{getattr(inst.source, 'type', None)!r}) — a parametric from_primitive disc is "
        "built generatively and embedded inline, not referenced by path; a file source means "
        "the static (saved default-radius) primitive was instanced instead of the parametric one."
    )
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    assert_circular_disc(
        design, requested_radius_nm,
        max_spread_nm=max_spread_nm, radius_tol_nm=radius_tol_nm,
    )
    return design


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


# ── Cluster-pose oracle (rigid-translation, geometric) ────────────────────────

def assert_cluster_translated(
    design_before,
    design_after,
    cluster_id: str,
    *,
    translation,
    tol_nm: float = 0.02,
    min_translation_nm: float = 0.5,
):
    """Geometric oracle for a cluster rigid-TRANSLATION pose.

    A :class:`~backend.core.models.ClusterRigidTransform` carries a DISPLAY-layer pose
    (translation / rotation / pivot) that the geometry kernel applies as a post-step
    rigid displacement of the cluster's helices — it never mutates the strand graph
    (the three-layer law).  ``canonical_topology`` is therefore **blind** to a cluster
    pose (the same blind-spot as loop/skip marks and bend/twist overlays), so
    :func:`assert_roundtrip_stable` alone cannot prove a pose flowed into the geometry
    or persisted — only measuring the placed geometry can.

    Pass the design *before* the pose (cluster created, identity pose) and *after*
    :func:`~backend.api.headless_build.transform_cluster` with a pure ``translation``
    (identity rotation).  Reading the cluster-posed axes from
    :func:`backend.core.deformation.deformed_helix_axes` on each design, this asserts:

      1. **Cluster helices translated by exactly the request.** Every helix in
         ``cluster_id`` has its posed ``start`` and ``end`` displaced by ``translation``
         (within ``tol_nm``) — so a kernel that ignored the pose, scaled it, or applied
         it to the wrong frame fails.
      2. **Only the cluster moved.** Every helix *not* in the cluster is unchanged
         (within ``tol_nm``) — the cluster-scoping property (a pose is local to its
         cluster, the default catch-all cluster stays put).
      3. **The pose was non-trivial (the can-go-red guard).** ``‖translation‖`` exceeds
         ``min_translation_nm``; a zero translation would make every helix trivially
         "unchanged" and the oracle pass vacuously.

    **Direction-AGNOSTIC**: a world-space translation is unambiguous (no quaternion
    sign / pivot / frame convention to reason about), so this stays clear of the
    ASK-FIRST DNA-directionality rule.  Rotation poses (where the sign/pivot convention
    *is* a directionality question) are deliberately out of scope here — they belong
    with AF-15 Phase 2's edge-alignment solver.  Returns the number of cluster helices
    measured.
    """
    import numpy as np

    from backend.core.deformation import deformed_helix_axes

    T = np.asarray(translation, dtype=float)
    assert float(np.linalg.norm(T)) > min_translation_nm, (
        f"requested translation is ~zero (‖T‖ = {float(np.linalg.norm(T)):.4f} nm < "
        f"{min_translation_nm} nm) — every helix would read as 'unchanged' and this "
        "oracle would pass vacuously (pose the cluster by a non-zero translation)."
    )

    cluster = next((c for c in design_after.cluster_transforms if c.id == cluster_id), None)
    assert cluster is not None, f"no cluster {cluster_id!r} in design_after"
    cluster_helix_ids = set(cluster.helix_ids)
    assert cluster_helix_ids, f"cluster {cluster_id!r} has no helices — nothing to measure"

    before_axes = {a["helix_id"]: a for a in deformed_helix_axes(design_before)}
    after_axes = {a["helix_id"]: a for a in deformed_helix_axes(design_after)}

    moved = 0
    for hid, after_a in after_axes.items():
        before_a = before_axes.get(hid)
        assert before_a is not None, f"helix {hid} present after but not before the pose"
        bs, be = np.asarray(before_a["start"]), np.asarray(before_a["end"])
        as_, ae = np.asarray(after_a["start"]), np.asarray(after_a["end"])
        if hid in cluster_helix_ids:
            assert np.allclose(as_, bs + T, atol=tol_nm) and np.allclose(ae, be + T, atol=tol_nm), (
                f"cluster helix {hid} did not translate by {list(translation)} nm: "
                f"start {np.round(bs, 3)} → {np.round(as_, 3)} "
                f"(expected {np.round(bs + T, 3)})."
            )
            moved += 1
        else:
            assert np.allclose(as_, bs, atol=tol_nm) and np.allclose(ae, be, atol=tol_nm), (
                f"non-cluster helix {hid} moved {np.round(as_ - bs, 3)} nm — a cluster "
                "pose must be local to its own helices."
            )
    assert moved == len(cluster_helix_ids), (
        f"measured {moved} cluster helices but the cluster lists {len(cluster_helix_ids)} "
        "— a cluster helix is missing from the posed geometry."
    )
    return moved


def assert_cluster_in_feature_log(design, cluster_id: str, *, expect_helix_ids=None):
    """Oracle: a logged cluster-creation is recorded in the design's feature log.

    ``add_cluster(..., log=True)`` must append a ``cluster_create`` feature-log entry
    naming the new cluster and its exact helix set, so a design's construction history
    can replay "group these helices into a bar" — the cluster-creation step of a
    kinematic mechanism (e.g. the generated 4-bar parallelogram part).  Without it the
    history is incomplete: a user replaying the log sees the bundle + the cluster
    transforms + the joints, but never the cluster creation.

    ``canonical_topology`` is **blind** to clusters — they are a display/geometry-layer
    grouping outside the strand graph (the same blind-spot as loop/skip marks and
    bend/twist overlays) — so :func:`assert_roundtrip_stable` *cannot* prove the grouping
    persisted across a save/load; only the feature-log entry can.  Call this on a
    :func:`roundtrip_nadoc` result to prove the entry survived ``.nadoc`` save/load.

    Asserts:

      1. **The entry exists.** Exactly one ``cluster_create`` entry carries
         ``cluster_id`` — a build that created the cluster *without* ``log=True`` leaves
         none (the can-go-red guard).
      2. **It names the right helices.** Its ``helix_ids`` are exactly the live cluster's
         helix set (or ``expect_helix_ids`` when given) — so a build that logged the
         wrong helices, or whose cluster lost/gained helices after logging, fails.
      3. **It names the right cluster.** Its ``name`` matches the live cluster's name.

    Returns the matched log entry.
    """
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    assert cluster is not None, f"no cluster {cluster_id!r} in design.cluster_transforms"

    entries = [
        e for e in design.feature_log
        if getattr(e, "feature_type", None) == "cluster_create" and e.cluster_id == cluster_id
    ]
    assert entries, (
        f"no 'cluster_create' feature-log entry for cluster {cluster_id!r} — the cluster "
        "was created without logging (call add_cluster(..., log=True)); its construction "
        "step is unrepresentable in the design's history."
    )
    assert len(entries) == 1, (
        f"expected exactly one 'cluster_create' entry for {cluster_id!r}, got {len(entries)}."
    )
    entry = entries[0]

    expected = set(expect_helix_ids) if expect_helix_ids is not None else set(cluster.helix_ids)
    source = "requested" if expect_helix_ids is not None else "live cluster"
    assert set(entry.helix_ids) == expected, (
        f"cluster_create entry helix set {sorted(entry.helix_ids)} != {source} helix set "
        f"{sorted(expected)} — the logged grouping does not match the cluster."
    )
    assert entry.name == cluster.name, (
        f"cluster_create entry name {entry.name!r} != live cluster name {cluster.name!r}."
    )
    return entry


def assert_edges_collinear(
    design,
    cluster_id: str,
    src_edge,
    *,
    target_edge=None,
    target_line=None,
    tol_nm: float = 0.05,
    tol_deg: float = 1.0,
    min_len_nm: float = 0.5,
):
    """Geometric oracle for the AF-15 Phase 2 cluster OBB-edge alignment solver.

    After :func:`~backend.api.headless_build.align_cluster_edge` poses ``cluster_id``,
    this asserts the cluster's ``src_edge`` (an OBB edge ``(axis, s1, s2)``) is
    **collinear** with the target — i.e. the two edges lie on one shared infinite
    line.  Recomputes the cluster's OBB from the *posed* geometry
    (:func:`backend.core.cluster_obb.cluster_obb`) so it measures where the edge really
    landed, not where the solver claimed it would.  Two conditions:

      1. **Parallel-or-antiparallel directions** — the angle between the src and
         target edge directions is within ``tol_deg`` of 0° or 180° (collinearity is a
         property of the *line*, so either sense passes).
      2. **On the shared line** — both src-edge endpoints lie within ``tol_nm`` of the
         target line (perpendicular distance), so the edges don't merely run parallel
         on different lines.

    **Direction-AGNOSTIC** (a line, not a ray — both senses pass), so this stays clear
    of the ASK-FIRST DNA-directionality rule.  A non-degeneracy guard (both edges
    longer than ``min_len_nm``) keeps it from passing vacuously on a collapsed OBB; the
    geometric assertions themselves go red when a no-op / wrong-target solver leaves the
    edges skew or off-line (the can-go-red property, exercised by the red-tests).

    Target is one of ``target_edge=(other_cluster_id, edge_key)`` (another cluster's OBB
    edge) or ``target_line=(point, direction)`` (a world line).  Returns the measured
    angular deviation from collinear (degrees).
    """
    import math

    import numpy as np

    from backend.core.cluster_obb import cluster_obb

    def _unit(x):
        x = np.asarray(x, dtype=float)
        n = float(np.linalg.norm(x))
        assert n > 1e-12, "cannot normalise a ~zero direction"
        return x / n

    if target_edge is not None and target_line is not None:
        raise ValueError("pass exactly one of target_edge / target_line, not both")

    obb = cluster_obb(design, cluster_id)
    p_lo, p_hi = obb.edge_endpoints(src_edge)
    src_len = float(np.linalg.norm(p_hi - p_lo))
    assert src_len > min_len_nm, (
        f"src edge {src_edge} is degenerate (length {src_len:.3f} nm ≤ {min_len_nm} nm) "
        "— a collapsed OBB would make collinearity vacuous."
    )
    src_dir = (p_hi - p_lo) / src_len

    if target_edge is not None:
        other_id, edge_key = target_edge
        t_obb = cluster_obb(design, other_id)
        q_lo, q_hi = t_obb.edge_endpoints(edge_key)
        tgt_len = float(np.linalg.norm(q_hi - q_lo))
        assert tgt_len > min_len_nm, (
            f"target edge {edge_key} is degenerate (length {tgt_len:.3f} nm) — "
            "collinearity would be vacuous."
        )
        tgt_point = (q_lo + q_hi) / 2.0
        tgt_dir = (q_hi - q_lo) / tgt_len
    elif target_line is not None:
        point, direction = target_line
        tgt_point = np.asarray(point, dtype=float)
        tgt_dir = _unit(direction)
    else:
        raise ValueError("pass target_edge or target_line")

    # (1) directions parallel or antiparallel.
    cos_ang = abs(float(np.dot(src_dir, tgt_dir)))
    ang = math.degrees(math.acos(min(1.0, cos_ang)))
    assert ang < tol_deg, (
        f"src edge is not collinear with the target: directions deviate {ang:.2f}° "
        f"from parallel (tol {tol_deg}°) — the alignment rotation is wrong."
    )

    # (2) both src endpoints lie on the target line.
    for p in (p_lo, p_hi):
        d = p - tgt_point
        perp = d - float(np.dot(d, tgt_dir)) * tgt_dir
        dist = float(np.linalg.norm(perp))
        assert dist < tol_nm, (
            f"src endpoint {np.round(p, 3)} lies {dist:.3f} nm off the target line "
            f"(tol {tol_nm} nm) — the edges are parallel but not on the same line "
            "(the midpoint snap / translation is wrong)."
        )
    return ang


def assert_joint_on_hull_corner(
    design,
    joint_id: str,
    *,
    edge=None,
    corner=None,
    face=None,
    tol_nm: float = 0.05,
    tol_deg: float = 1.0,
    min_len_nm: float = 0.5,
):
    """Geometric oracle for AF-14 Phase 1 cluster-joint placement.

    After :func:`~backend.api.headless_build.place_cluster_joint` anchors a revolute
    joint on a named OBB feature, this asserts the placed joint's world axis really sits
    on that feature of the **independently recomputed** OBB.  It re-derives the joint's
    world axis from its cluster-LOCAL storage and the cluster's current pose
    (:func:`backend.core.models._local_to_world_joint`) — so it measures where the axis
    actually landed after the world→local→world round-trip the route performs, not what
    the placement helper claimed.  Recomputes the OBB from the posed geometry
    (:func:`backend.core.cluster_obb.cluster_obb`), the equivariant frame, so a named
    edge/corner refers to the same physical feature even on a posed cluster.

    Two modes (mirroring :func:`hull_prism_axis`):

      * ``edge=(axis, s1, s2)`` — the joint axis line is **collinear** with the named OBB
        edge: its direction is parallel-or-antiparallel to the edge (within ``tol_deg``)
        AND both edge endpoints lie within ``tol_nm`` of the joint axis line.
      * ``corner=(su, sv, sw)`` with ``face=(axis, sign)`` — the joint axis line passes
        **through** the named corner (perpendicular distance < ``tol_nm``) AND its
        direction is parallel-or-antiparallel to the named face normal (within
        ``tol_deg``).

    **Direction-AGNOSTIC** (a line, not a ray — either sense passes), so it stays clear
    of the ASK-FIRST DNA-directionality rule.  A non-degeneracy guard (the OBB edge is
    longer than ``min_len_nm``) keeps a collapsed box from passing vacuously; the
    on-line / through-corner assertions go red when the joint was placed on a different
    feature (the can-go-red property the red-tests exercise).  Returns the measured
    angular deviation from collinear (degrees).
    """
    import math

    import numpy as np

    from backend.core.cluster_obb import cluster_obb
    from backend.core.models import _local_to_world_joint

    if edge is not None and corner is not None:
        raise ValueError("pass exactly one of edge / corner, not both")

    joint = next((j for j in design.cluster_joints if j.id == joint_id), None)
    assert joint is not None, f"no joint {joint_id!r} in design"
    cluster = next(
        (c for c in design.cluster_transforms if c.id == joint.cluster_id), None
    )
    assert cluster is not None, f"joint {joint_id!r} references missing cluster"

    world_origin, world_dir = _local_to_world_joint(
        joint.local_axis_origin, joint.local_axis_direction, cluster,
    )
    o = np.asarray(world_origin, dtype=float)
    dlen = float(np.linalg.norm(world_dir))
    assert dlen > 1e-9, "joint axis direction is ~zero"
    d = np.asarray(world_dir, dtype=float) / dlen

    def _dist_to_joint_line(p) -> float:
        v = np.asarray(p, dtype=float) - o
        perp = v - float(np.dot(v, d)) * d
        return float(np.linalg.norm(perp))

    obb = cluster_obb(design, cluster.id)

    if edge is not None:
        p_lo, p_hi = obb.edge_endpoints(edge)
        edge_len = float(np.linalg.norm(p_hi - p_lo))
        assert edge_len > min_len_nm, (
            f"OBB edge {edge} is degenerate (length {edge_len:.3f} nm ≤ {min_len_nm} nm)"
            " — collinearity would be vacuous."
        )
        edge_dir = (p_hi - p_lo) / edge_len
        cos_ang = abs(float(np.dot(d, edge_dir)))
        ang = math.degrees(math.acos(min(1.0, cos_ang)))
        assert ang < tol_deg, (
            f"joint axis is not collinear with edge {edge}: directions deviate "
            f"{ang:.2f}° from parallel (tol {tol_deg}°)."
        )
        for p in (p_lo, p_hi):
            dist = _dist_to_joint_line(p)
            assert dist < tol_nm, (
                f"edge endpoint {np.round(p, 3)} lies {dist:.3f} nm off the joint axis "
                f"line (tol {tol_nm} nm) — the joint is parallel but not on the edge."
            )
        return ang

    if corner is not None:
        if face is None:
            raise ValueError("corner mode requires a face=(axis, sign)")
        su, sv, sw = corner
        corner_pt = obb.corner(su, sv, sw)
        dist = _dist_to_joint_line(corner_pt)
        assert dist < tol_nm, (
            f"joint axis line passes {dist:.3f} nm from corner {corner} "
            f"(tol {tol_nm} nm) — the joint is not anchored at that corner."
        )
        f_normal = obb.face_normal(face)
        cos_ang = abs(float(np.dot(d, f_normal / np.linalg.norm(f_normal))))
        ang = math.degrees(math.acos(min(1.0, cos_ang)))
        assert ang < tol_deg, (
            f"joint axis direction deviates {ang:.2f}° from the face {face} normal "
            f"(tol {tol_deg}°) — the swing plane is wrong."
        )
        return ang

    raise ValueError("pass exactly one of edge / corner")


def assert_range_of_motion(
    design,
    cluster_id: str,
    axis,
    expected_deg: float,
    *,
    tol_deg: float = 2.0,
    min_angle_deg: float = -180.0,
    max_angle_deg: float = 180.0,
    pad=None,
    step_deg: float = 2.0,
):
    """Geometric oracle for AF-14 Phase 2 cluster range-of-motion.

    Computes the anchored cluster's collision-free swing about ``axis``
    (:func:`backend.core.cluster_obb.cluster_range_of_motion` — the swept OBB–OBB SAT
    bisection, padded by the helix radius) and asserts it equals ``expected_deg`` within
    ``tol_deg``.  ``axis`` is ``(origin, direction)`` as from ``hull_prism_axis``.

    Two can-go-red properties the tests exercise: with **no obstacle** the swing equals
    the joint's full angular limit (``max − min``, e.g. 360°), and an obstacle moved into
    the swing path **strictly reduces** it — so the green goes red on a wrong angle or a
    blocked joint.  A physical-bound guard (``0 ≤ ROM ≤ max − min``) keeps the sweep from
    silently passing on a runaway angle.  **Direction-AGNOSTIC** total magnitude (no
    handedness), so it stays clear of the ASK-FIRST DNA-directionality rule.  Returns the
    measured ROM in degrees.
    """
    from backend.core.cluster_obb import cluster_range_of_motion
    from backend.core.constants import HELIX_RADIUS

    if pad is None:
        pad = HELIX_RADIUS
    rom = cluster_range_of_motion(
        design, cluster_id, axis,
        min_angle_deg=min_angle_deg, max_angle_deg=max_angle_deg,
        pad=pad, step_deg=step_deg,
    )
    full = max_angle_deg - min_angle_deg
    assert -1e-6 <= rom <= full + tol_deg, (
        f"ROM {rom:.2f}° is outside the physical bound [0, {full:.1f}°] — the sweep "
        "escaped its angular limits."
    )
    assert abs(rom - expected_deg) <= tol_deg, (
        f"cluster {cluster_id!r} ROM about the given axis is {rom:.2f}°, expected "
        f"{expected_deg:.2f}° ± {tol_deg}°."
    )
    return rom


def assert_parallelogram_linkage(
    design,
    bar_ids,
    *,
    joint_ids,
    tol_nm: float = 0.1,
    tol_deg: float = 2.0,
    expected_dof: int = 1,
    min_area_nm2: float = 1.0,
    require_movable: bool = True,
):
    """Geometric + kinematic oracle for the headless 4-bar parallelogram (the capstone).

    Proves that four rigid-body clusters — arranged headlessly by composing
    :func:`~backend.api.headless_build.align_cluster_edge` (AF-15 P2) + posed bars and
    hinged with :func:`~backend.api.headless_build.place_cluster_joint` (AF-14 P1) — form
    a genuine **parallelogram four-bar linkage** with the expected mobility.  This is the
    first headless *kinematic mechanism*; nothing before it validated an assembled
    multi-cluster mechanism (the individual pieces — edge collinearity, joint-on-edge,
    per-joint ROM — are pinned by their own AF oracles; this pins their *composition*).

    ``bar_ids`` are the 4 bar clusters in **cyclic order** around the loop; ``joint_ids``
    are the placed :class:`ClusterJoint`s (revolute hinges).  Checks, all measured on the
    *posed* geometry (each bar's equivariant OBB, recomputed here — never trusting the
    solver's claimed transform):

      1. **Closed quadrilateral** — adjacent bars share an OBB corner (the hinge point):
         the minimum corner-to-corner distance between bar ``k`` and bar ``k+1`` is
         < ``tol_nm``.  The 4 shared corners, taken in order, enclose an area
         > ``min_area_nm2`` (the non-degeneracy guard — four collinear/collapsed bars
         fail, so the oracle can't pass vacuously).
      2. **Parallelogram** — opposite bars' long (axial) directions are
         parallel-or-antiparallel within ``tol_deg`` AND equal in length within
         ``tol_nm`` (opposite sides parallel + equal = a parallelogram).
      3. **Mobility** — :func:`backend.core.cluster_obb.grubler_mobility` of the
         ``(len(bar_ids))`` links + ``len(joint_ids)`` revolute joints equals
         ``expected_dof`` (1 for a 4-bar) — the rigorous planar-DOF claim.
      4. **Each hinge movable** (when ``require_movable``) — each joint's world axis,
         re-derived from its cluster-LOCAL storage (so it's the *placed* axis, not a
         re-derivation), admits a **nonzero** collision-free swing against the
         non-adjacent (non-pinned) bars — i.e. the joint is a real movable revolute, not
         frozen.

    **Direction-AGNOSTIC** throughout (parallelism is a line property; ROM is a
    magnitude), so it stays clear of the ASK-FIRST DNA-directionality rule.  Returns a
    dict ``{"corners", "side_lengths", "mobility", "joint_roms"}``.
    """
    import math

    import numpy as np

    from backend.core.cluster_obb import (
        cluster_obb,
        cluster_range_of_motion,
        grubler_mobility,
    )
    from backend.core.models import _local_to_world_joint

    n = len(bar_ids)
    assert n == 4, f"a parallelogram needs exactly 4 bars, got {n}"

    obbs = [cluster_obb(design, bid) for bid in bar_ids]

    def _corners(o):
        return [o.corner(su, sv, sw)
                for su in (-1, 1) for sv in (-1, 1) for sw in (-1, 1)]

    def _long_axis(o):
        i = int(np.argmax(o.half))
        return o.axes[i], 2.0 * float(o.half[i])

    corners = [_corners(o) for o in obbs]

    # (1) adjacent bars share a corner → the 4 hinge points.
    shared = []
    for k in range(n):
        ci, cj = corners[k], corners[(k + 1) % n]
        best = min(((np.linalg.norm(x - y), x, y) for x in ci for y in cj),
                   key=lambda t: t[0])
        d, x, _ = best
        assert d < tol_nm, (
            f"bars {bar_ids[k]!r} and {bar_ids[(k + 1) % n]!r} do not meet at a shared "
            f"corner (nearest corners are {d:.3f} nm apart, tol {tol_nm} nm) — the "
            "linkage is not a closed loop."
        )
        shared.append(x)

    # non-degeneracy: the 4 shared corners enclose a real (planar) area.
    sc = [np.asarray(p, float) for p in shared]
    diag1 = sc[2] - sc[0]
    diag2 = sc[3] - sc[1]
    area = 0.5 * float(np.linalg.norm(np.cross(diag1, diag2)))
    assert area > min_area_nm2, (
        f"the four shared corners enclose only {area:.3f} nm² (≤ {min_area_nm2} nm²) — "
        "the arrangement is degenerate (collinear / collapsed), not a parallelogram."
    )

    # (2) opposite sides parallel + equal length.
    side_lengths = []
    for k in range(n):
        _, L = _long_axis(obbs[k])
        side_lengths.append(L)
    for k in (0, 1):
        d_a, L_a = _long_axis(obbs[k])
        d_b, L_b = _long_axis(obbs[k + 2])
        cos_ang = abs(float(np.dot(d_a, d_b)))
        ang = math.degrees(math.acos(min(1.0, cos_ang)))
        assert ang < tol_deg, (
            f"opposite bars {bar_ids[k]!r} / {bar_ids[k + 2]!r} are not parallel "
            f"(axes deviate {ang:.2f}° from parallel, tol {tol_deg}°) — not a parallelogram."
        )
        assert abs(L_a - L_b) < tol_nm, (
            f"opposite bars {bar_ids[k]!r} / {bar_ids[k + 2]!r} differ in length "
            f"({L_a:.3f} vs {L_b:.3f} nm, tol {tol_nm}) — not a parallelogram."
        )

    # (3) mobility (Grübler/Kutzbach): a 4-link, 4-revolute planar mechanism is 1-DOF.
    mobility = grubler_mobility(n, revolute=len(joint_ids))
    assert mobility == expected_dof, (
        f"mechanism mobility is {mobility}, expected {expected_dof} "
        f"({n} links, {len(joint_ids)} revolute joints) — not a {expected_dof}-DOF linkage."
    )

    # (4) each hinge is a real movable revolute (nonzero swing vs. non-pinned bars).
    joint_roms = {}
    if require_movable:
        bar_index = {bid: i for i, bid in enumerate(bar_ids)}
        for jid in joint_ids:
            joint = next((j for j in design.cluster_joints if j.id == jid), None)
            assert joint is not None, f"no joint {jid!r} in design"
            i = bar_index.get(joint.cluster_id)
            assert i is not None, (
                f"joint {jid!r} is on cluster {joint.cluster_id!r}, not one of the bars"
            )
            cluster = next(c for c in design.cluster_transforms
                           if c.id == joint.cluster_id)
            origin, direction = _local_to_world_joint(
                joint.local_axis_origin, joint.local_axis_direction, cluster,
            )
            # non-adjacent bars = those not pinned to bar i (its neighbours co-move in a
            # real linkage; the collision concern is the un-connected bar(s)).
            obstacles = [bar_ids[j] for j in range(n)
                         if j not in {(i - 1) % n, i, (i + 1) % n}]
            rom = cluster_range_of_motion(
                design, bar_ids[i], (origin, direction), obstacles=obstacles or None,
            )
            assert rom > tol_deg, (
                f"hinge {jid!r} on bar {bar_ids[i]!r} has ROM {rom:.2f}° — the joint is "
                "frozen, not a movable revolute."
            )
            joint_roms[jid] = rom

    return {
        "corners": [p.tolist() for p in sc],
        "side_lengths": side_lengths,
        "mobility": mobility,
        "joint_roms": joint_roms,
    }


def assert_recommended_hinge(
    design,
    cluster_id: str,
    *,
    recommendations=None,
    axial_tol_deg: float = 20.0,
    tol_nm: float = 0.05,
    length_tol_nm: float = 0.1,
):
    """Geometric oracle for AF-14 Phase 3's hinge-joint recommender.

    Pins that :func:`backend.core.cluster_obb.recommend_hinge_joints` surfaces the right
    #1 hinge under the user-fixed priority (2026-06-18).  Asserts the top recommendation:

      1. **is NOT axial** — its edge makes an angle > ``axial_tol_deg`` with the cluster's
         helical (``w``) axis, so it's a fold, not a barrel-roll about the bundle axis;
      2. **is the longest non-axial edge** — its OBB-edge length is ≥ every other
         non-axial candidate's (within ``length_tol_nm``);
      3. **is corner-anchored** — its stored ``axis_origin`` coincides (within ``tol_nm``)
         with an edge endpoint (a face corner) and is **not** the edge midpoint.

    Everything is re-measured on the **independently recomputed** equivariant OBB
    (:func:`backend.core.cluster_obb.cluster_obb`), so the oracle never trusts the
    recommender's own numbers.  Pass ``recommendations=`` a hand-built candidate list to
    drive the can-go-red guards (an axial edge wrongly on top → check 1 fires; a
    midpoint-anchored top → check 3 fires).  **Direction-AGNOSTIC** (edge length +
    angle-to-axis are magnitudes), so it stays clear of the ASK-FIRST rule.  Returns the
    top recommendation dict.
    """
    import math

    import numpy as np

    from backend.core.cluster_obb import cluster_obb, recommend_hinge_joints

    recs = (
        recommendations
        if recommendations is not None
        else recommend_hinge_joints(design, cluster_id)
    )
    assert recs, "recommender returned no hinge candidates"
    top = recs[0]

    obb = cluster_obb(design, cluster_id)
    w = obb.axes[2]  # (u, v, w) — w is the helical/bundle axis

    def _edge_len_angle(edge):
        p_lo, p_hi = obb.edge_endpoints(edge)
        vec = p_hi - p_lo
        length = float(np.linalg.norm(vec))
        ang = math.degrees(math.acos(min(1.0, abs(float((vec / length) @ w)))))
        return p_lo, p_hi, length, ang

    p_lo, p_hi, edge_len, angle = _edge_len_angle(top["edge"])

    # (1) the top hinge is a fold, not an axial barrel-roll.
    assert angle > axial_tol_deg, (
        f"top recommended hinge {top['edge']} is axial — its edge is only {angle:.1f}° "
        f"from the helical axis (≤ {axial_tol_deg}°), a barrel-roll not a fold."
    )

    # (2) it is the longest of the non-axial edges.
    non_axial_lengths = []
    for c in recs:
        _, _, length, ang = _edge_len_angle(c["edge"])
        if ang > axial_tol_deg:
            non_axial_lengths.append(length)
    assert non_axial_lengths, "no non-axial edges among the recommendations"
    longest = max(non_axial_lengths)
    assert edge_len >= longest - length_tol_nm, (
        f"top hinge edge length {edge_len:.2f} nm is not the longest non-axial edge "
        f"(longest is {longest:.2f} nm) — the recommender mis-ranked."
    )

    # (3) the anchor is a face corner, NOT the edge midpoint.  For a real (non-degenerate)
    # edge a corner and the midpoint are half the edge length apart, so a midpoint anchor
    # is far from every corner and fails this single check (the can-go-red guard).
    origin = np.asarray(top["axis_origin"], dtype=float)
    midpoint = (p_lo + p_hi) / 2.0
    d_corner = min(float(np.linalg.norm(origin - p_lo)),
                   float(np.linalg.norm(origin - p_hi)))
    at_midpoint = float(np.linalg.norm(origin - midpoint)) < tol_nm
    assert d_corner < tol_nm, (
        f"hinge anchor {np.round(origin, 3)} is {d_corner:.3f} nm from the nearest edge "
        f"corner (tol {tol_nm} nm) — it is not corner-anchored"
        + (" (it sits at the edge MIDPOINT)." if at_midpoint else ".")
    )
    return top


# ── Headless-coverage audit ───────────────────────────────────────────────────

# ── Full-sequencing oracle (every base defined + WC-complementary) ────────────

def assert_fully_sequenced(design: Design, *, require_wc: bool = True) -> int:
    """A design carries a *complete, correct* sequence: no undefined base AND every
    scaffold-paired staple base is the Watson-Crick complement of its scaffold base.

    The load-bearing property is **zero undefined bases** — exactly the gate
    ``create_oxdna_job`` and every export path enforce (so "fully sequenced" means
    oxDNA/export-ready), measured by the same ``count_undefined_bases`` they use
    (reference 'backdrop' strands excluded).  ``require_wc`` adds the correctness
    proof: walking the strand graph independently of the assignment code, every
    staple base at a scaffold-covered position must equal ``complement_base`` of the
    scaffold base there — so a builder that filled positions with the *wrong* base
    (or the scaffold's own base instead of its complement) fails, not just one that
    left them ``'N'``.  Returns the number of WC-paired positions verified.

    Can-go-red: an unsequenced (or partially sequenced) design trips the undefined
    guard; a corrupted staple base trips the WC guard.
    """
    from backend.core.models import Direction, StrandType
    from backend.core.sequences import complement_base
    from backend.physics.oxdna_interface import count_undefined_bases

    undefined, total = count_undefined_bases(design, exclude_reference=True)
    assert total > 0, "design has no sequenceable nucleotides (oracle would be vacuous)"
    assert undefined == 0, (
        f"{undefined}/{total} bases still undefined — design is not fully sequenced")

    if not require_wc:
        return 0

    def _positions(strand):
        out = []
        for dm in strand.domains:
            lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
            rng = (range(lo, hi + 1) if dm.direction == Direction.FORWARD
                   else range(hi, lo - 1, -1))
            out.extend((dm.helix_id, bp) for bp in rng)
        return out

    scaffold_base: dict[tuple[str, int], str] = {}
    for s in design.strands:
        if s.is_reference or s.strand_type != StrandType.SCAFFOLD:
            continue
        for key, base in zip(_positions(s), s.sequence or ""):
            scaffold_base[key] = base.upper()

    checked = 0
    for s in design.strands:
        if s.is_reference or s.strand_type != StrandType.STAPLE:
            continue
        for key, base in zip(_positions(s), s.sequence or ""):
            scaf = scaffold_base.get(key)
            if scaf is None:
                continue
            expected = complement_base(scaf)
            assert base.upper() == expected, (
                f"staple base {base!r} at {key} is not the WC complement of "
                f"scaffold base {scaf!r} (expected {expected!r})")
            checked += 1
    assert checked > 0, (
        "no scaffold-paired staple positions to verify — WC check would be vacuous")
    return checked


# ── Physical-layer (oxDNA) relaxation oracle (AF-13, Tier 5) ──────────────────

def assert_relaxed_geometry_recovered(job, design: Design, workspace, *,
                                      expected_count: int | None = None) -> dict:
    """Tier-5 foundational oracle: a headless oxDNA relaxation reached
    ``completed`` AND its relaxed last frame reads back into a full per-nucleotide
    position map — "we can drive oxDNA headlessly and recover the relaxed geometry."

    Asserts, on the terminal :class:`~backend.core.oxdna_job.OxdnaJob` returned by
    :func:`~backend.api.headless_oxdna_build.run_relaxation`:

    1. the job status is ``completed`` (a silently failed / stopped / still-queued
       run raises — the can-go-red status guard);
    2. the display route reads the relaxed ``last_conf`` back and reports ``ready``;
    3. the recovered map has **exactly one finite position per design nucleotide**,
       and every recovered ``(helix_id, bp_index, direction)`` key is a real key of
       the design's geometry — so a dropped / truncated / mis-keyed conf is caught,
       not silently accepted.

    *Physical-layer only*: it reads the relaxed geometry, it never asserts (or
    requires) that those positions were written into ``Design`` topology.  Returns
    the display dict so callers can inspect the recovered positions.
    """
    from backend.api import headless_oxdna_build as hox

    status = getattr(job.status, "value", str(job.status))
    assert status == "completed", (
        f"oxDNA job did not reach completed (status={status!r}); error={job.error!r}")

    display = hox.read_relaxed_positions(job.job_id, workspace)
    assert display.get("ready") is True, (
        "relaxed last_conf did not read back (display route not ready)")
    positions = display["positions"]

    geom = _geometry_for_design(design)
    expected = expected_count if expected_count is not None else len(geom)
    assert len(positions) == expected, (
        f"recovered {len(positions)} relaxed positions, expected {expected} "
        "(one per design nucleotide)")

    design_keys = {(g["helix_id"], g["bp_index"], g["direction"]) for g in geom}
    for p in positions:
        bb = p["backbone_position"]
        assert len(bb) == 3 and all(math.isfinite(float(c)) for c in bb), (
            f"recovered a non-finite backbone position: {bb!r}")
        key = (p["helix_id"], p["bp_index"], p["direction"])
        assert key in design_keys, (
            f"recovered position key {key!r} is not a nucleotide of the design")

    recovered_keys = {(p["helix_id"], p["bp_index"], p["direction"]) for p in positions}
    assert recovered_keys == design_keys, (
        f"recovered geometry does not cover every design nucleotide "
        f"(missing {len(design_keys - recovered_keys)}, extra "
        f"{len(recovered_keys - design_keys)})")
    return display


def assert_field_ready_specimen(result, design: Design, workspace, *,
                                field_pN: float = 4.0, field_dir=(0, 0, 1),
                                field_steps: int = 2000, anchor_tol_nm: float = 1.0,
                                min_free_proj_nm: float = 0.5) -> dict:
    """AF-18 (Tier 6) composite oracle: an end-to-end-built design is *ready to run
    an electric-field experiment* — fully sequenced, relaxed, and anchorable so that
    a field holds the anchored beads while the rest deflects.

    ``result`` is the dict :func:`~backend.api.headless_oxdna_build.build_field_specimen`
    returns (``{design, job, anchor_keys, anchor}``); ``design`` is the specimen design
    (normally ``result["design"]``).  Composes three independently-proven properties
    into one "field-ready" verdict:

    1. **fully sequenced** — :func:`assert_fully_sequenced` (zero undefined bases AND
       correct WC-complement staples), the gate ``create_oxdna_job`` / every export
       enforces;
    2. **relaxed geometry recovered** — :func:`assert_relaxed_geometry_recovered` on
       ``result["job"]`` (the relaxation reached ``completed`` and the relaxed frame
       reads back as a full per-nucleotide position map);
    3. **anchorable under a field** — ``result["anchor_keys"]`` is non-empty (the
       anchor resolved to real nucleotides) AND a short *probe* field run (a field
       child branched off the relaxed parent, anchoring ``result["anchor"]``) makes
       the anchored beads hold while the free part deflects ALONG the field, verified
       by :func:`~backend.core.oxdna_health.measure_field_response` (``passed``).

    The load-bearing gap this closes: each piece (sequence, relax, anchor) was pinned
    *alone*, but nothing proved they **compose** into a single runnable, anchorable
    specimen — exactly the user's "build → … → set as anchor → run a field" chain.

    *Physical-layer only* — it reads relaxed/field geometry, never writes it into
    ``Design`` (the Three-Layer Law).  ``field_dir``/``field_pN`` drive only the probe
    (magnitudes/projection are measured → direction-agnostic, no sign reasoning).
    Returns ``{n_wc_checked, n_anchored, field_response}``.

    Can-go-red: an unsequenced specimen fails clause 1; a non-completed relaxation
    fails clause 2; an anchor that resolves to nothing (or a field that fails to hold
    the anchor / deflect the body) fails clause 3.
    """
    from pathlib import Path

    from backend.api import headless_oxdna_build as hox
    from backend.core.oxdna_health import field_response_from_confs

    # Clause 1 — export/oxDNA-ready sequence.
    n_wc = assert_fully_sequenced(design)

    # Clause 2 — the relaxation completed and the relaxed geometry reads back.
    job = result["job"]
    assert_relaxed_geometry_recovered(job, design, workspace)

    # Clause 3 — a resolved anchor + a probe field that holds it while the rest moves.
    anchor_keys = result["anchor_keys"]
    assert anchor_keys, (
        "specimen resolved no anchor nucleotides — not field-anchorable (a uniform "
        "field would just stream the whole structure across the box)")
    anchor = result["anchor"]
    child = hox.append_field(job.job_id, workspace, field_pN=field_pN,
                             dir=list(field_dir), anchors=[anchor], steps=field_steps)
    field_job = hox.wait_for_terminal(child["job_id"], workspace)
    status = getattr(field_job.status, "value", str(field_job.status))
    assert status == "completed", (
        f"probe field run did not complete (status={status!r}); error={field_job.error!r}")

    ws = Path(workspace)
    field_conf = field_job.stage_dir(ws, field_job.stages[-1].name) / "last_conf.dat"
    ref_conf = field_job.job_dir(ws) / "conf.dat"
    response = field_response_from_confs(
        design, field_conf, ref_conf, field_dir=list(field_dir),
        anchor_keys=anchor_keys, anchor_tol_nm=anchor_tol_nm,
        min_free_proj_nm=min_free_proj_nm)
    assert response["passed"], (
        f"specimen is not field-ready — the probe field did not confirm "
        f"anchor-held/body-deflected: {response['reason']}")
    return {"n_wc_checked": n_wc, "n_anchored": len(anchor_keys),
            "field_response": response}


def assert_equilibration_timeline(job, workspace, field_dir, anchor_keys, *,
                                  design: Design, melt_floor: float = 0.5,
                                  min_confidence: int = 10):
    """AF-19 (Tier 6) oracle: a field run reaches a stable equilibrium in finite time
    *without melting* — the structure swings to a new pose and holds together.

    ``measure_field_response`` (AF-18) is **endpoint-only**: it compares the final
    field pose to the field-off reference and is blind to (a) *how long* the swing took
    and (b) any *transient* base-pair melt mid-swing.  This oracle reads the whole
    field-stage ``trajectory.dat`` and asserts a **time-resolved** verdict:

    1. **confidence gate** — at least ``min_confidence`` trajectory frames were written
       (a too-short run cannot certify an equilibration timescale; mirrors the Tier-5
       frame-count gate);
    2. **finite positive τ + plateau** — :func:`~backend.core.oxdna_health.measure_field_equilibration`
       finds a monotone-within-noise approach to a stable plateau and a finite positive
       equilibration time τ (a run still climbing at the end has *not* equilibrated →
       ``converged`` is False → this fails);
    3. **non-melt invariant** — base-pair retention never drops below ``melt_floor`` at
       ANY frame across the whole timeline (the "aligns without ripping it apart"
       window the user wants — checked transiently, not just at the end).

    ``job`` is the terminal field child job (from
    :func:`~backend.api.headless_oxdna_build.run_field` or an ``append_field`` child);
    ``anchor_keys`` are the pinned nucleotide keys (the field anchor); ``field_dir`` the
    field direction (magnitudes/projection are measured → direction-agnostic).
    Returns the :func:`measure_field_equilibration` result dict.

    *Physical-layer only* — reads trajectory geometry, never writes it back into
    ``Design``.  Can-go-red: a non-converging (never-plateau) run yields no finite τ
    (clause 2); a melt during the swing breaches the floor (clause 3); too few frames
    is inconclusive (clause 1).
    """
    from pathlib import Path

    from backend.core.oxdna_health import measure_field_equilibration
    from backend.physics.oxdna_interface import read_trajectory_frames_full

    status = getattr(job.status, "value", str(job.status))
    assert status == "completed", (
        f"field job did not reach completed (status={status!r}); error={job.error!r}")

    ws = Path(workspace)
    field_idx = next((i for i, s in enumerate(job.stages) if s.kind == "field"), None)
    assert field_idx is not None, "job has no field stage to read a timeline from"
    stage = job.stages[field_idx]
    traj = job.stage_dir(ws, stage.name) / "trajectory.dat"
    assert traj.exists(), f"field stage wrote no trajectory.dat ({traj})"

    frames = read_trajectory_frames_full(traj, design)
    n_frames = len(frames)
    assert n_frames >= min_confidence, (
        f"field equilibration is INCONCLUSIVE — only {n_frames} trajectory "
        f"frame(s) (need >= {min_confidence}); run a longer field stage to certify "
        "a timescale (the confidence gate)")

    total_steps = getattr(stage, "steps", None)
    steps_per_frame = (total_steps / n_frames) if total_steps else 1.0

    result = measure_field_equilibration(
        frames, field_dir, anchor_keys, design=design,
        steps_per_frame=steps_per_frame, melt_floor=melt_floor)

    assert result["converged"], (
        f"field response did not equilibrate to a stable plateau: {result['reason']}")
    assert result["tau_steps"] is not None and result["tau_steps"] > 0, (
        f"no finite positive equilibration time τ (tau_steps={result['tau_steps']!r})")
    assert not result["melted"], (
        f"structure melted during the field swing — base-pair retention dropped to "
        f"{result['bp_min']:.0%} below the {melt_floor:.0%} floor (it was ripped apart)")
    return result


def assert_field_sweep_map(sweep, *, benign_range, destructive_range,
                           melt_floor=0.5, tau_tol_steps=1e-6,
                           min_tau_drop_steps=1.0):
    """AF-20 (Tier 6) oracle: a swept ``(|E|, direction)`` field response surface is
    a *complete, physically-sensible* map — the first automated MULTI-config physical
    experiment.  Where Tier 5 measured one structure at one condition, this asserts a
    **response surface**: a non-destructive operating window + the field-strength ↔
    equilibration-timeline correlation the user wants.

    ``sweep`` is the dict :func:`~backend.api.headless_oxdna_build.sweep_field_response`
    returns (``map`` keyed by ``(pN, dir_tuple)`` + ``skipped`` + ``intensities_pN`` +
    ``directions``).  Four clauses:

    1. **no gaps** — no cell was skipped, and every ``(pN, direction)`` grid cell
       carries a verdict (a sweep that silently dropped a condition is not a map).
    2. **a non-destructive window exists** — at least one cell whose ``|E|`` lies in
       ``benign_range`` is non-destructive (aligned to a new pose AND its base-pair
       retention stayed above ``melt_floor`` for the whole swing).  *Recomputed here*
       from the raw measured ``aligned``/``bp_min`` fields, not the wrapper's stored
       ``destructive`` flag (so the oracle measures the surface, it doesn't echo it).
    3. **the destructive regime is destructive** — ``destructive_range`` covers ≥1
       swept cell AND every such cell IS destructive (it melted / failed to hold) —
       the "without ripping it apart" window has a real upper bound.
    4. **τ decreases with |E|** — within each direction's *responsive band* (the
       non-destructive, aligned cells, ordered by ``|E|``) the equilibration time τ
       is monotone non-increasing AND actually falls (the strongest responsive field
       equilibrates faster than the weakest — the field↔τ correlation, not a flat
       line).  ``≥ 2`` responsive cells are required so the trend is non-vacuous.

    ``benign_range``/``destructive_range`` are inclusive ``(lo_pN, hi_pN)`` bands.
    Direction-agnostic (τ + retention are magnitudes).  Returns a summary dict.

    Can-go-red: a skipped/incomplete grid (clause 1); a benign band with no safe
    cell (clause 2); a destructive band that did not melt, i.e. a "non-empty"
    (still-intact) destructive window (clause 3); a flat, field-independent τ
    (clause 4).
    """
    cells = sweep["map"]
    assert not sweep["skipped"], (
        f"field sweep skipped {len(sweep['skipped'])} cell(s) {sweep['skipped']} — "
        "the response surface is incomplete (a field job failed or wrote no "
        "trajectory); no silent truncation of the grid")

    # Clause 1 — every grid cell present.
    grid = [(pN, d) for pN in sweep["intensities_pN"] for d in sweep["directions"]]
    assert grid, "field sweep covered no (|E|, direction) cells (empty grid)"
    for key in grid:
        assert key in cells, f"field sweep has no verdict for cell {key} (a gap in the map)"

    def _nondestructive(cell):
        # Recompute from the raw measured fields (NOT cell["destructive"]).
        return bool(cell["aligned"]) and cell["bp_min"] >= melt_floor

    # Clause 2 — a non-destructive operating window exists in the benign band.
    blo, bhi = benign_range
    benign_safe = [k for k, c in cells.items()
                   if blo <= k[0] <= bhi and _nondestructive(c)]
    assert benign_safe, (
        f"no non-destructive cell in the benign |E| range {benign_range} pN — the "
        "specimen has no safe operating window where it aligns without melting")

    # Clause 3 — the destructive band covers real cells and they all melted.
    dlo, dhi = destructive_range
    destr_cells = [(k, c) for k, c in cells.items() if dlo <= k[0] <= dhi]
    assert destr_cells, (
        f"destructive |E| range {destructive_range} pN covers no swept cell — the "
        "sweep cannot certify an upper bound (vacuous)")
    still_intact = [k for k, c in destr_cells if _nondestructive(c)]
    assert not still_intact, (
        f"cells {still_intact} in the destructive range {destructive_range} pN did "
        "NOT melt — the non-destructive window is not bounded above (the structure "
        "survives a field that should rip it apart)")

    # Clause 4 — τ decreases with |E| in each direction's responsive band.
    n_checked = 0
    for d in sweep["directions"]:
        band = sorted((k[0], c) for k, c in cells.items()
                      if k[1] == d and _nondestructive(c))
        taus = [c["tau_steps"] for _pN, c in band]
        assert len(taus) >= 2, (
            f"direction {d}: responsive band has {len(taus)} cell(s) (<2) — cannot "
            "test a τ-vs-|E| trend; widen the responsive intensity range")
        for (lo_pN, a), (hi_pN, b) in zip(band, band[1:]):
            assert b["tau_steps"] <= a["tau_steps"] + tau_tol_steps, (
                f"direction {d}: equilibration time τ rose from {a['tau_steps']:.1f} "
                f"({lo_pN} pN) to {b['tau_steps']:.1f} ({hi_pN} pN) — stronger field "
                "should equilibrate at least as fast (τ non-increasing in |E|)")
        assert taus[0] - taus[-1] >= min_tau_drop_steps, (
            f"direction {d}: τ is flat across |E| ({taus}) — no field↔equilibration "
            "correlation (the response is field-strength independent)")
        n_checked += 1

    return {"n_cells": len(cells), "n_benign_safe": len(benign_safe),
            "n_destructive": len(destr_cells), "n_directions_checked": n_checked}


def _campaign_tau_signature(sweep, *, melt_floor):
    """The τ of every *non-destructive* (aligned ∧ retained) cell of one sweep, keyed
    by ``(pN, dir)`` — a design's field-response signature.  Recomputed from the raw
    measured ``aligned``/``bp_min`` (NOT the wrapper's stored ``destructive`` flag), so
    a campaign oracle that compares signatures measures the surface, not an echo of it.
    """
    sig = {}
    for key, cell in sweep["map"].items():
        if bool(cell["aligned"]) and cell["bp_min"] >= melt_floor:
            sig[key] = cell["tau_steps"]
    return sig


def assert_field_campaign(campaign, *, benign_range, destructive_range,
                          expect_distinguishable=True, melt_floor=0.5,
                          min_tau_separation_steps=1.0, repro=None,
                          tau_tol_steps=1e-6, min_tau_drop_steps=1.0):
    """AF-23 (Tier 6 CAPSTONE) oracle: a cross-design field-response *campaign* is a
    complete, design-discriminating, reproducible study — the user's stated goal,
    tying text→design (the AF-11/12 grammar) + field sweep (AF-20) + equilibration
    (AF-19) into ONE automated experiment reusable for any origami.

    ``campaign`` is the dict :func:`~backend.api.headless_oxdna_build.run_field_campaign`
    returns (``sweeps`` keyed by design name + ``skipped`` + ``names`` + the shared
    ``intensities_pN``/``directions`` grid).  Four clauses:

    1. **no dropped design** — ``skipped`` is empty and ``sweeps`` is non-empty (a
       campaign that silently lost a design is not a study; mirrors the AF-20
       no-silent-truncation rule, one level up).
    2. **every design is a valid response surface** — each design's sweep passes
       :func:`assert_field_sweep_map` (a populated grid, a non-destructive operating
       window in ``benign_range``, a destructive upper bound in ``destructive_range``,
       and τ falling with ``|E|``).  So every design carries a *reported* non-destructive
       window, the per-design half of the capstone deliverable.
    3. **designs are distinguishable** — when ``expect_distinguishable`` (the default),
       at least two designs differ in their response: there is a shared responsive
       ``(|E|, direction)`` cell where their equilibration times τ differ by ≥
       ``min_tau_separation_steps`` (a floppier / longer-lever design equilibrates on a
       different timescale).  Recomputed from the measured τ, not echoed.  This is the
       load-bearing NEW assertion over AF-20: AF-20 pins ONE surface; nothing before
       proved the campaign produces design-*discriminating* surfaces (the whole point of
       sweeping "various designs").  With ``expect_distinguishable=False`` the clause is
       skipped (e.g. a control of identical designs).
    4. **reproducible** — when ``repro`` (a second :func:`run_field_campaign` result over
       the same specimens) is supplied, every shared design + cell's τ matches within
       ``tau_tol_steps`` (the deterministic-mock campaign re-runs identically — a
       prerequisite for trusting any automated cross-design conclusion).

    ``benign_range``/``destructive_range`` are inclusive ``(lo_pN, hi_pN)`` bands shared
    across designs.  Direction-agnostic (τ + retention are magnitudes).  Returns a
    summary dict.

    Can-go-red: a skipped design (clause 1); a design whose surface is incomplete or has
    no safe/destructive window (clause 2, via ``assert_field_sweep_map``); a campaign of
    indistinguishable designs (clause 3); a non-deterministic re-run (clause 4).
    """
    sweeps = campaign["sweeps"]

    # Clause 1 — no design dropped.
    assert not campaign["skipped"], (
        f"field campaign skipped {len(campaign['skipped'])} design(s) "
        f"{campaign['skipped']} — a build/sweep failed; the cross-design study is "
        "incomplete (no silent truncation of the campaign)")
    assert sweeps, "field campaign produced no design response surfaces (empty)"

    # Clause 2 — every design is itself a valid, windowed response surface.
    per_design = {}
    for name, sweep in sweeps.items():
        per_design[name] = assert_field_sweep_map(
            sweep, benign_range=benign_range, destructive_range=destructive_range,
            melt_floor=melt_floor, tau_tol_steps=tau_tol_steps,
            min_tau_drop_steps=min_tau_drop_steps)

    # Build each design's τ signature over its non-destructive cells.
    signatures = {name: _campaign_tau_signature(sweep, melt_floor=melt_floor)
                  for name, sweep in sweeps.items()}

    # Clause 3 — the designs are distinguishable (the capstone's reason to exist).
    n_distinguishing = 0
    if expect_distinguishable:
        assert len(sweeps) >= 2, (
            "expect_distinguishable requires >= 2 designs to compare (the campaign "
            f"has {len(sweeps)})")
        names = list(signatures)
        max_sep = 0.0
        sep_cell = None
        for ai in range(len(names)):
            for bi in range(ai + 1, len(names)):
                sa, sb = signatures[names[ai]], signatures[names[bi]]
                shared = set(sa) & set(sb)
                for cell in shared:
                    sep = abs(sa[cell] - sb[cell])
                    if sep >= min_tau_separation_steps:
                        n_distinguishing += 1
                    if sep > max_sep:
                        max_sep, sep_cell = sep, cell
        assert n_distinguishing >= 1, (
            "field campaign designs are INDISTINGUISHABLE — no shared responsive "
            f"(|E|, direction) cell separates any two designs' τ by >= "
            f"{min_tau_separation_steps} steps (largest τ separation seen: "
            f"{max_sep:.1f} steps at {sep_cell}); the campaign cannot tell the "
            "structures apart")

    # Clause 4 — deterministic re-run reproduces every τ.
    n_repro = 0
    if repro is not None:
        repro_sigs = {name: _campaign_tau_signature(sweep, melt_floor=melt_floor)
                      for name, sweep in repro["sweeps"].items()}
        shared_designs = set(signatures) & set(repro_sigs)
        assert shared_designs, (
            "reproducibility check: the re-run campaign shares no design names with "
            "the original (nothing to compare)")
        for name in shared_designs:
            a, b = signatures[name], repro_sigs[name]
            assert set(a) == set(b), (
                f"design {name!r}: re-run's responsive cell set differs from the "
                f"original ({set(a) ^ set(b)}) — the campaign is not deterministic")
            for cell, tau in a.items():
                assert abs(tau - b[cell]) <= tau_tol_steps, (
                    f"design {name!r} cell {cell}: τ {tau:.3f} (run 1) vs "
                    f"{b[cell]:.3f} (run 2) differ > {tau_tol_steps} — the campaign "
                    "is not reproducible")
                n_repro += 1

    return {"n_designs": len(sweeps), "n_distinguishing_cells": n_distinguishing,
            "n_repro_cells": n_repro, "per_design": per_design}


def assert_oxpy_equilibrium_parity(live_result, batch_result, *, tol_nm: float = 0.5,
                                   bp_tol: float = 0.05, min_confidence: int = 2,
                                   require_mutation: bool = True):
    """AF-21 (Tier 6) oracle: the PERSISTENT in-process oxpy engine is physically
    equivalent to the validated one-shot batch engine, AND its live field control
    actually steers the body.

    Every prior physical oracle (AF-13/18/19/20/23) drove the *batch* CLI binary.
    AF-21 introduces a second engine — a burst-stepped, live-field-mutating oxpy
    session.  If "real-time" output is to be trusted it must reach the SAME
    equilibrium the batch path reaches, and a field re-aim must actually move the
    structure.  This oracle asserts both, on two ``run_live_field``/batch result
    dicts (schema ``{"observables": {alignment_nm, radius_of_gyration_nm,
    bp_retention}, "confidence": int, "mutation": {...} | None}``):

    1. **confidence gate** — both runs carry ``confidence >= min_confidence``
       (a too-short burst budget cannot certify an equilibrium; the Tier-5 gate,
       here over bursts/frames).  A stochastic thermostat forbids *trajectory*
       parity, so this asserts **equilibrium-property** parity, not step-by-step.
    2. **equilibrium parity** — the live and batch ``alignment_nm`` and
       ``radius_of_gyration_nm`` agree within ``tol_nm`` and ``bp_retention``
       within ``bp_tol`` (the new pose + compactness + survival the field drives to
       is engine-independent — burst-stepping does not change where it ends up).
    3. **live field-following** — (when ``require_mutation``) the live run carries a
       ``mutation`` record whose ``followed`` is True: re-aiming the field mid-run
       increased the free body's deflection ALONG the new vector (the substance
       behind "drag the field and it follows", distinct from a responsive UI).

    Direction-agnostic (alignment/τ are magnitudes); the parity clause is testable
    GPU-free against the binary ``_FIELD_MOCK_OXDNA`` (an in-process mock stepper
    mirrors its deflection model); the live-mutation clause is exercised by the
    real oxpy build.  Returns ``{alignment_delta_nm, rg_delta_nm, bp_delta,
    followed}``.

    Can-go-red: a live run diverging from batch beyond tol (clause 2); a field
    re-aim that does not move the body (``followed`` False, clause 3); a run below
    the confidence gate (clause 1).
    """
    lc = int(live_result.get("confidence", 0))
    bc = int(batch_result.get("confidence", 0))
    assert lc >= min_confidence and bc >= min_confidence, (
        f"oxpy parity is INCONCLUSIVE — confidence live={lc} batch={bc} "
        f"(need >= {min_confidence}); run more bursts/frames (the confidence gate)")

    lo = live_result["observables"]
    bo = batch_result["observables"]
    da = abs(lo["alignment_nm"] - bo["alignment_nm"])
    dr = abs(lo["radius_of_gyration_nm"] - bo["radius_of_gyration_nm"])
    db = abs(lo["bp_retention"] - bo["bp_retention"])
    assert da <= tol_nm, (
        f"oxpy/batch equilibrium DIVERGED in alignment: live "
        f"{lo['alignment_nm']:.3f} nm vs batch {bo['alignment_nm']:.3f} nm "
        f"(Δ {da:.3f} > {tol_nm} nm) — the interactive engine is not reaching the "
        "batch engine's equilibrium pose")
    assert dr <= tol_nm, (
        f"oxpy/batch equilibrium DIVERGED in radius of gyration: live "
        f"{lo['radius_of_gyration_nm']:.3f} nm vs batch "
        f"{bo['radius_of_gyration_nm']:.3f} nm (Δ {dr:.3f} > {tol_nm} nm)")
    assert db <= bp_tol, (
        f"oxpy/batch equilibrium DIVERGED in base-pair retention: live "
        f"{lo['bp_retention']:.3f} vs batch {bo['bp_retention']:.3f} "
        f"(Δ {db:.3f} > {bp_tol})")

    followed = None
    if require_mutation:
        mut = live_result.get("mutation")
        assert mut is not None, (
            "live run carries no field-mutation record — cannot prove the field "
            "steers the body (pass mutate_dir to run_live_field, or "
            "require_mutation=False for a parity-only check)")
        followed = bool(mut["followed"])
        assert followed, (
            f"the live field re-aim did NOT steer the body: deflection along the "
            f"new vector went {mut['proj_on_to_before_nm']:.3f} → "
            f"{mut['proj_on_to_after_nm']:.3f} nm (expected an increase) — a dead "
            "field vector mutation")

    return {"alignment_delta_nm": da, "rg_delta_nm": dr, "bp_delta": db,
            "followed": followed}


def assert_live_field_following(timeline, *, melt_floor: float = 0.5,
                                min_following_nm: float = 0.5):
    """AF-22 (Tier 6) oracle: a STEERED live-field timeline produces real
    field-following without melting — the substance behind "play with the field in
    real time", distinct from a merely responsive UI.

    Where :func:`assert_oxpy_equilibrium_parity` (AF-21) proves ONE field re-aim
    steers the body, this proves an arbitrary *path* of waypoints does: for the
    timeline :func:`backend.api.headless_oxdna_build.steer_field_session` returns
    (``{"timeline": [{field_dir, proj_before_nm, proj_after_nm, bp_retention, …}, …],
    "n_waypoints": N}``), it asserts:

    1. **non-vacuity** — ≥2 waypoints (a steered path needs at least a change), and at
       least one waypoint whose field-following move (``proj_after − proj_before``) is
       ≥ ``min_following_nm`` (so the body genuinely chased a re-aim, not floating
       noise); a timeline of stationary zeros cannot pass.
    2. **field-following** — at EVERY waypoint the free body's deflection along that
       waypoint's field vector ROSE across the burst (``proj_after > proj_before``):
       running under the re-aimed field moved the structure toward the new direction.
       A body that ignored a waypoint change (the projection did not rise) fails here.
    3. **no melt during steering** — ``bp_retention`` stays ≥ ``melt_floor`` at every
       waypoint (the structure followed the field WITHOUT ripping apart, across the
       whole path — the "without melting" half of the user's goal, now over a
       trajectory of field changes, not one).

    Load-bearing because nothing before proved the interactive control LOOP (many
    field changes in sequence) produces sustained field-following without a melt —
    AF-21 pins a single re-aim's equilibrium, blind to a multi-step steered path.
    Direction-agnostic (signed projections along each leg's own vector → no
    handedness reasoning).  Returns ``{n_waypoints, n_following_moves, min_bp,
    max_following_nm}``.

    Can-go-red: a waypoint the body ignored (clause 2); a melt at any waypoint
    (clause 3); a stationary all-zero timeline (clause 1 non-vacuity).
    """
    wps = timeline["timeline"] if isinstance(timeline, dict) else list(timeline)
    assert len(wps) >= 2, (
        f"a steered field timeline needs >= 2 waypoints to prove following "
        f"(got {len(wps)}) — a single field cannot show the body chasing a re-aim")

    moves = [float(wp["proj_after_nm"]) - float(wp["proj_before_nm"]) for wp in wps]
    bps = [float(wp["bp_retention"]) for wp in wps]

    for i, (wp, move, bp) in enumerate(zip(wps, moves, bps)):
        assert bp >= melt_floor, (
            f"waypoint {i} (field {wp['field_dir']}) MELTED during steering: "
            f"bp retention {bp:.3f} < {melt_floor} — the structure ripped apart "
            "following the field")
        assert move > 1e-9, (
            f"waypoint {i} (field {wp['field_dir']}) did NOT follow the field "
            f"re-aim: deflection along its vector went {wp['proj_before_nm']:.3f} "
            f"→ {wp['proj_after_nm']:.3f} nm (expected a rise) — a dead waypoint "
            "the body ignored")

    n_following = sum(1 for m in moves if m >= min_following_nm)
    assert n_following >= 1, (
        f"no waypoint moved the body by >= {min_following_nm} nm along its field "
        f"(max move {max(moves):.3f} nm) — the steering is vacuous (the body never "
        "substantially chased a re-aim)")

    return {"n_waypoints": len(wps), "n_following_moves": n_following,
            "min_bp": min(bps), "max_following_nm": max(moves)}


def assert_relaxed_measurement(job, measure_spec, target_nm, tol_nm, *,
                               workspace, min_confidence=RMSF_PRELIM_FRAMES):
    """Tier-5 constraint primitive: a *measured* geometric property of the
    relaxed, **noise-averaged** structure lies within ``tol_nm`` of ``target_nm``,
    **gated by confidence** — the first stochastic-class oracle.

    Unlike the deterministic Tiers 0–4 (exact fingerprints / analytic geometry),
    a relaxed measurement is a property of a thermally-fluctuating ensemble, so it
    is asserted *within a tolerance* and is only trustworthy once enough frames
    have been pooled.  The oracle therefore:

    1. requires the job to have ``completed`` (the status guard);
    2. reads the production **mean structure** via
       :func:`~backend.api.headless_oxdna_build.read_flexibility_map` (pooled,
       PBC-unwrapped, Kabsch-aligned) — preferred over a single frame because the
       mean cancels thermal noise;
    3. **the confidence gate** — if fewer than ``min_confidence`` production
       frames were pooled the measurement is *inconclusive* and the oracle raises
       (a too-short run cannot certify a target; this is the load-bearing guard
       AF-13 Phase 3's checker formalises as "met requires confidence");
    4. computes the measurement and asserts it is within ``tol_nm`` of
       ``target_nm``.  Four measures are implemented: ``end_to_end`` (the Euclidean
       distance between two ``(helix_id, bp_index, direction)`` landmark
       nucleotides, via :func:`measure_end_to_end`), ``radius_of_gyration``
       (the whole-structure compactness over ALL nucleotides — no landmarks — via
       :func:`measure_radius_of_gyration`), ``segment_angle`` (the bend angle in
       DEGREES at the middle of three landmarks, via :func:`measure_segment_angle`),
       and ``inter_helix_spacing`` (the radial centre-to-centre nm gap between the
       axes of the two helices named by the landmarks, via
       :func:`measure_inter_helix_spacing`).

    ``measure_spec`` is ``{"measure": "end_to_end", "landmarks": [a, b]}`` /
    ``{"measure": "segment_angle", "landmarks": [a, b, c]}`` (each landmark a
    ``(helix_id, bp_index, direction)`` key, ``b`` the angle vertex) or
    ``{"measure": "radius_of_gyration"}`` (no landmarks).  For the angular measure
    ``target_nm``/``tol_nm`` carry DEGREES (the field names are kept for backward
    compatibility).  Returns ``{measured_nm, target_nm, tol_nm, n_frames,
    confidence}`` so callers can surface the value + how trustworthy it is.

    *Physical-layer only*: it reads relaxed geometry, it never writes it back to
    ``Design``.
    """
    from backend.api import headless_oxdna_build as hox
    from backend.core.oxdna_health import (
        measure_end_to_end,
        measure_inter_helix_spacing,
        measure_radius_of_gyration,
        measure_segment_angle,
    )

    status = getattr(job.status, "value", str(job.status))
    assert status == "completed", (
        f"oxDNA job did not reach completed (status={status!r}); error={job.error!r}")

    rmsf = hox.read_flexibility_map(job.job_id, workspace)
    assert rmsf.get("ready") is True, (
        "no production mean structure available — run append_production before "
        f"measuring (rmsf route: {rmsf.get('reason')!r})")
    confidence = rmsf.get("confidence") or {}
    n_frames = confidence.get("n_frames", rmsf.get("n_frames", 0))
    assert n_frames >= min_confidence, (
        f"relaxed measurement is INCONCLUSIVE — only {n_frames} production "
        f"frame(s) pooled (need >= {min_confidence}); run a longer production to "
        "certify the target (the confidence gate)")

    kind = measure_spec.get("measure")
    unit = "nm"
    if kind == "end_to_end":
        landmark_a, landmark_b = measure_spec["landmarks"]
        measured = measure_end_to_end(rmsf["positions"], landmark_a, landmark_b)
        label = "end-to-end"
    elif kind == "radius_of_gyration":
        measured = measure_radius_of_gyration(rmsf["positions"])
        label = "radius of gyration"
    elif kind == "segment_angle":
        # Angular measure → target_nm/tol_nm carry DEGREES (the field names are kept
        # for backward compatibility); the vertex is the middle landmark.
        landmark_a, landmark_b, landmark_c = measure_spec["landmarks"]
        measured = measure_segment_angle(
            rmsf["positions"], landmark_a, landmark_b, landmark_c)
        label, unit = "segment angle", "deg"
    elif kind == "inter_helix_spacing":
        # Each landmark names a helix (any nucleotide on it); the measure groups
        # every site of that helix to fit its axis, then the radial centre-to-centre
        # spacing in nm.
        landmark_a, landmark_b = measure_spec["landmarks"]
        measured = measure_inter_helix_spacing(
            rmsf["positions"], landmark_a, landmark_b)
        label = "inter-helix spacing"
    else:
        raise AssertionError(
            f"assert_relaxed_measurement: unsupported measure {kind!r} "
            "(implemented: 'end_to_end', 'radius_of_gyration', 'segment_angle')")
    assert abs(measured - target_nm) <= tol_nm, (
        f"relaxed {label} {measured:.3f} {unit} is not within {tol_nm} {unit} of "
        f"the target {target_nm} {unit} (off by {abs(measured - target_nm):.3f} "
        f"{unit})")
    return {"measured_nm": measured, "target_nm": target_nm, "tol_nm": tol_nm,
            "n_frames": n_frames, "confidence": confidence}


def assert_relax_honors_hardware_default(design: Design, workspace, *,
                                         backend: str, device: str = "0", **params):
    """Tier-5 bridge oracle: a benchmarked hardware default actually *reaches the
    simulation* — a headless relaxation tuned from ``metadata.hardware_defaults``
    runs on the recommended ``backend``/``device``, with a safe CPU fallback when
    nothing was benchmarked.

    The Benchmark button discovers the fastest config and writes it to the design's
    metadata, but until now that value was only read by the *frontend* to pre-fill the
    panel — **no backend path consumed it into a run**, so nothing proved the chosen
    device ever reaches oxDNA.  This oracle closes that gap end-to-end:

    1. **Baseline / fallback** — ``run_relaxation_tuned`` on ``design`` *before* applying
       any default must complete on the portable ``CPU``/``"0"`` fallback (so ``design``
       must carry no ``hardware_defaults`` entry for this host; this also proves the
       non-CPU result below comes from the stored default, not a constant);
    2. **Tuned** — apply the recommendation ``{backend, device}``
       (:func:`~backend.api.headless_oxdna_build.apply_oxdna_benchmark`), relax again,
       and assert the terminal :class:`~backend.core.oxdna_job.OxdnaJob` carries that
       exact ``backend``/``device`` — i.e. the metadata flowed
       benchmark→``hardware_defaults``→relaxation config;
    3. **Non-vacuity** — the requested config must DIFFER from the CPU fallback
       (otherwise a bridge that ignored the default would pass), so this oracle is only
       meaningful for a non-default config (e.g. ``backend="CUDA"`` / ``device="1"``).

    ``params`` forward to ``run_relaxation_tuned`` (``min_bp_retained`` / step counts).
    Returns the tuned terminal job.  *Physical-layer only*: reads the run's config, never
    writes relaxed geometry into ``Design``.
    """
    from backend.api import headless_oxdna_build as hox
    from backend.core import hardware

    if (backend, device) == ("CPU", "0"):
        raise AssertionError(
            "assert_relax_honors_hardware_default is vacuous for the CPU/0 fallback — "
            "request a non-default config (e.g. backend='CUDA', device='1')")

    host = hardware.hostname()
    if design.metadata.hardware_defaults.get(host) is not None:
        raise AssertionError(
            "design already carries a hardware default for this host — pass a design "
            "with no benchmarked default so the baseline fallback is meaningful")

    base = hox.run_relaxation_tuned(design, workspace, **params)
    base_status = getattr(base.status, "value", str(base.status))
    assert base_status == "completed", (
        f"baseline relaxation did not complete (status={base_status!r}); "
        f"error={base.error!r}")
    assert (base.backend, base.device) == ("CPU", "0"), (
        f"expected the CPU/0 fallback with no benchmarked default, got "
        f"{base.backend}/{base.device}")

    tuned_design = hox.apply_oxdna_benchmark(design, {"backend": backend, "device": device})
    job = hox.run_relaxation_tuned(tuned_design, workspace, **params)
    status = getattr(job.status, "value", str(job.status))
    assert status == "completed", (
        f"tuned relaxation did not complete (status={status!r}); error={job.error!r}")
    assert (job.backend, job.device) == (backend, device), (
        f"relaxation did not honour the benchmarked default: requested "
        f"{backend}/{device}, but the job ran {job.backend}/{job.device}")
    return job


def assert_converges_to_constraint(result, *, target_nm, tol_nm,
                                   min_confidence=RMSF_PRELIM_FRAMES):
    """AF-13 Phase 4 capstone oracle: a closed build→relax→measure→adjust loop
    (:func:`~backend.api.headless_oxdna_build.iterate_to_constraint`) *converged* a
    parametric topology knob to a relaxed-structure target — and got there honestly,
    with **every** verdict certified by the P3 confidence gate.

    ``result`` is the dict :func:`iterate_to_constraint` returns.  Asserts:

    1. the loop reached ``status == "met"`` within its iteration budget (an
       unreachable target / exhausted run raises — the can-go-red guard);
    2. the **winning** verdict is genuinely ``met`` AND was pooled from
       ``>= min_confidence`` frames — the loop did not declare victory on a noisy,
       under-sampled estimate (the load-bearing AF-13 P3 gate, now enforced across a
       *closed loop* rather than a single read);
    3. **no** intermediate iteration ever flipped ``met`` below ``min_confidence``
       frames either (the gate held on every step, not just the last);
    4. the final measured value is within ``tol_nm`` of ``target_nm``;
    5. **non-vacuity** — the FIRST attempt was NOT already ``met``, so the run
       actually exercised the adjust loop (a knob that started on-target would prove
       nothing about convergence).

    *Physical-layer only*: reads the loop's verdicts, never the relaxed coordinates.
    Returns ``result`` so callers can chain on it.
    """
    assert isinstance(result, dict) and "status" in result, (
        f"assert_converges_to_constraint expects an iterate_to_constraint result "
        f"dict, got {result!r}")
    history = result.get("iterations") or []
    assert history, "iterate loop ran zero iterations — nothing was attempted"

    assert result["status"] == "met", (
        f"iterate loop did not converge (status={result['status']!r} after "
        f"{len(history)} iteration(s)); final verdict={result.get('verdict')!r}")

    final = result.get("verdict")
    assert final and final.get("status") == "met" and final.get("met") is True, (
        f"loop reported converged but the final verdict is not a clean 'met': "
        f"{final!r}")
    assert final["n_frames"] >= min_confidence, (
        f"loop declared the target met on only {final['n_frames']} pooled frame(s) "
        f"(< {min_confidence}) — the confidence gate was bypassed on the winning "
        "verdict")
    assert abs(final["measured_nm"] - target_nm) <= tol_nm, (
        f"final measured {final['measured_nm']:.3f} nm is not within {tol_nm} nm of "
        f"the target {target_nm} nm (off by {abs(final['measured_nm'] - target_nm):.3f})")

    for i, step in enumerate(history):
        v = step.get("verdict")
        if v and v.get("met"):
            assert v["n_frames"] >= min_confidence, (
                f"iteration {i} flipped 'met' on only {v['n_frames']} frame(s) "
                f"(< {min_confidence}) — the confidence gate must hold on EVERY "
                "step, not just the last")

    first = history[0].get("verdict")
    assert first is not None and first.get("status") != "met", (
        "loop converged on the FIRST attempt — the initial knob already met the "
        "constraint, so this run does not exercise the adjust loop (vacuous); start "
        "from a knob that is off-target")
    return result


def assert_spec_constraints_reported(spec_result, hand_verdicts, *, measured_tol=1e-6):
    """AF-13-grammar oracle: a design spec's ``constraints`` block reports the SAME
    relaxed-structure verdicts as the equivalent hand-driven
    :func:`~backend.core.oxdna_health.check_relaxed_constraint` calls.

    ``spec_result`` is the dict
    :func:`~backend.api.headless_spec_build.build_and_check_design` returns
    (``{"design", "verdicts"}``); ``hand_verdicts`` is the verdict list computed
    independently — build the same design by hand, relax it by hand, and call
    ``check_relaxed_constraint`` with the runtime-id landmarks.

    This is the **load-bearing** pin for the constraint grammar path, because
    :func:`assert_spec_matches_calls` is *blind* to a physical-layer verdict — the
    canonical-topology fingerprint cannot see whether a constraint was attached,
    resolved, or reported at all.  Only verdict-equality proves the grammar lowered the
    ``constraints`` block faithfully: that it resolved each landmark's ``grid_pos`` to
    the right helix, evaluated the right measure, and applied the confidence gate the
    same way a hand call does.  Asserts, per constraint (spec order):

    * same ``status`` (``met`` / ``unmet`` / ``inconclusive``) and ``met`` flag;
    * same ``measured_nm`` (within ``measured_tol``; ``None`` only matches ``None``).

    A **non-vacuity guard** requires at least one verdict (a spec with an empty
    ``constraints`` block reports nothing and would pass vacuously).  Goes red when the
    grammar drops a constraint (count mismatch), resolves a landmark to the wrong helix
    (measured diverges), or reports a different status.  Returns the spec verdict list.
    """
    assert isinstance(spec_result, dict) and "verdicts" in spec_result, (
        f"assert_spec_constraints_reported expects a build_and_check_design result "
        f"dict, got {spec_result!r}")
    spec_verdicts = spec_result["verdicts"]
    assert spec_verdicts, (
        "the spec reported no constraint verdicts — this oracle would pass vacuously; "
        "use a spec that actually carries a 'constraints' block")
    assert len(spec_verdicts) == len(hand_verdicts), (
        f"constraint count mismatch: the spec reported {len(spec_verdicts)} verdict(s) "
        f"but the hand build reported {len(hand_verdicts)} — a constraint was dropped "
        "or duplicated in the lowering")
    for i, (sv, hv) in enumerate(zip(spec_verdicts, hand_verdicts)):
        assert sv["status"] == hv["status"], (
            f"constraint {i}: spec status {sv['status']!r} != hand status "
            f"{hv['status']!r} — the grammar reported a different verdict")
        assert sv["met"] == hv["met"], (
            f"constraint {i}: spec met={sv['met']} != hand met={hv['met']}")
        sm, hm = sv["measured_nm"], hv["measured_nm"]
        if sm is None or hm is None:
            assert sm == hm, (
                f"constraint {i}: spec measured {sm!r} != hand measured {hm!r}")
        else:
            assert abs(sm - hm) <= measured_tol, (
                f"constraint {i}: spec measured {sm:.4f} != hand measured {hm:.4f} "
                f"(off by {abs(sm - hm):.4g}) — a landmark resolved to the wrong helix "
                "or the wrong measure ran")
    return spec_verdicts


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

    return _coverage_report(
        (headless_build, headless_assembly_build),
        lambda path: "/design" in path or "/assembly" in path,
    )


def oxdna_coverage_report() -> dict:
    """Automated audit for the *physical* layer: ``/oxdna`` mutation routes vs.
    :mod:`backend.api.headless_oxdna_build` wrappers (AF-13, Tier 5).

    Kept separate from :func:`headless_coverage_report` (which is scoped to the
    design/assembly surface) so the oxDNA tier has its own coverage number without
    perturbing the design/assembly denominator the AF-1..AF-12 metrics report.
    Same function-identity matching: a wrapper imports the exact route handler, so
    the report tracks reality and can't silently rot.
    """
    from backend.api import headless_oxdna_build

    return _coverage_report((headless_oxdna_build,), lambda path: "/oxdna" in path)


def _coverage_report(modules, path_predicate) -> dict:
    """Shared core of the coverage audits: which mutation routes whose path passes
    ``path_predicate`` have a function-identity wrapper in one of ``modules``."""
    from backend.api.main import app

    wrapped_fns = {
        obj
        for module in modules
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
        if not path_predicate(path):
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
