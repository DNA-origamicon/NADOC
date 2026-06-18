"""Headless (mouse-free) assembly construction.

The sibling of :mod:`backend.api.headless_build` for the *assembly* layer.  Where
that module is the programmatic surface over the design endpoints, this one is the
programmatic surface over ``/assembly/*`` — create an assembly, place part
instances at world transforms, resolve joint constraints — with no server, no
browser, no mouse.  Because every wrapper drives the real route handler (which
wraps ``assembly_state`` + the feature log), a scripted assembly carries a real,
replayable feature log: an assembly built here is indistinguishable from one built
by clicking.

This is the flagship gap the design-automation backlog (AF-7..AF-10) closes:
``headless_build`` already covers design ops, but assembly had **no** programmatic
builder at all.  Phase 1 (this module) is the spine — scratch session + instance
placement + resolve; later phases add mates/joints, gears/belts, and layout
helpers on top.

Isolation: :func:`assembly_scratch_session` binds a unique throwaway ``doc_id``
(via :mod:`backend.api.doc_context`, the same mechanism
``headless_build.scratch_session`` uses) so a one-shot build never disturbs the
active assembly or its undo history.  Capture any result *before* the block exits.

Source convenience: parts can be placed from an in-memory :class:`Design`
(:func:`add_inline_instance` embeds it as a ``PartSourceInline``) or from a
workspace ``.nadoc`` path (:func:`add_file_instance` references a
``PartSourceFile``) — mirroring the two ``PartSource`` variants the UI's "Add
Part" flow produces.
"""

from __future__ import annotations

import contextlib
import itertools

from backend.api import assembly_state
from backend.api import doc_context
from backend.api.assembly import (
    AddInstanceRequest,
    AssemblyImportRequest,
    CreateAssemblyRequest,
    add_instance as _route_add_instance,
    create_assembly as _route_create_assembly,
    import_assembly as _route_import_assembly,
    resolve_assembly as _route_resolve_assembly,
)
from backend.api.routes_assembly_connectors import (
    AddConnectorRequest,
    add_connector as _route_add_connector,
)
from backend.api.routes_assembly_belts import (
    BeltPulleyRequest,
    CreateBeltPathRequest,
    create_belt_path as _route_create_belt_path,
)
from backend.api.routes_assembly_gears import (
    CreateGearRelationRequest,
    create_gear_relation as _route_create_gear_relation,
)
from backend.api.routes_assembly_joints import (
    CreateMateRequest,
    MateConnectorSpec,
    PatchJointRequest,
    create_mate as _route_create_mate,
    patch_joint as _route_patch_joint,
)
from backend.api.routes_assembly_overhangs import (
    CreateAssemblyOverhangBindingRequest,
    PatchAssemblyOverhangBindingRequest,
    create_assembly_overhang_binding as _route_create_overhang_binding,
    delete_assembly_overhang_binding as _route_delete_overhang_binding,
    patch_assembly_overhang_binding as _route_patch_overhang_binding,
)
from backend.api.routes_assembly_polymerize import (
    PolymerizeAssemblyRequest,
    polymerize_assembly as _route_polymerize_assembly,
)
from backend.core.instance_layout import grid_translations, ring_translations
from backend.core.models import Assembly, Design, Mat4x4

_scratch_counter = itertools.count()


@contextlib.contextmanager
def assembly_scratch_session():
    """Bind an isolated throwaway document for the duration of an assembly build.

    Inside the block the construction wrappers operate on a fresh empty assembly;
    on exit the scratch document (and its undo history) is dropped, leaving the
    default session untouched.  Capture any result *before* the block exits
    (deep-copy it — the scratch assembly is gone after the ``with``).
    """
    doc_id = f"__headless_assembly_{next(_scratch_counter)}__"
    token = doc_context.set_current_doc(doc_id)
    try:
        assembly_state.set_assembly(Assembly())
        yield
    finally:
        doc_context.reset_current_doc(token)
        assembly_state.drop_doc(doc_id)


def _transform_dict(transform) -> dict | None:
    """Normalise a transform argument to the route's Mat4x4 dict (or ``None``).

    Accepts ``None`` (→ identity, the route default), a :class:`Mat4x4`, or a
    flat row-major list/tuple of 16 floats.
    """
    if transform is None:
        return None
    if isinstance(transform, Mat4x4):
        return transform.model_dump(mode="json")
    values = list(transform)
    if len(values) != 16:
        raise ValueError(
            f"transform must be a Mat4x4 or 16 row-major floats, got {len(values)}"
        )
    return {"values": [float(v) for v in values]}


def translation(x: float, y: float, z: float) -> Mat4x4:
    """A pure-translation :class:`Mat4x4` (row-major) — a convenience for placement.

    The last column carries ``(x, y, z)``; rotation block is identity.  Pass the
    result straight to :func:`add_inline_instance` / :func:`add_instance`.
    """
    return Mat4x4(values=[
        1.0, 0.0, 0.0, float(x),
        0.0, 1.0, 0.0, float(y),
        0.0, 0.0, 1.0, float(z),
        0.0, 0.0, 0.0, 1.0,
    ])


def new_assembly(name: str = "Untitled") -> Assembly:
    """Create a fresh empty assembly, replacing any active one (POST /assembly).

    Operates on whatever document is bound (default session, or a scratch one
    inside :func:`assembly_scratch_session`).
    """
    _route_create_assembly(CreateAssemblyRequest(name=name))
    return assembly_state.get_or_404()


def add_instance(source, *, name: str = "Part", transform=None) -> Assembly:
    """Add a PartInstance from a raw ``PartSource`` dict (POST /assembly/instances).

    ``source`` is the discriminated ``PartSource`` payload — either
    ``{"type": "inline", "design": <design dict>}`` or
    ``{"type": "file", "path": "<rel.nadoc>"}`` (a :class:`PartSource*` model is
    also accepted and dumped).  ``transform`` is the part's world placement: a
    :class:`Mat4x4`, a flat list of 16 row-major floats, or ``None`` for identity.
    Records an ``assembly-add-instance`` feature-log entry.  Prefer the typed
    :func:`add_inline_instance` / :func:`add_file_instance` for readability.
    """
    src = source.model_dump(mode="json") if hasattr(source, "model_dump") else source
    _route_add_instance(AddInstanceRequest(
        source=src, name=name, transform=_transform_dict(transform),
    ))
    return assembly_state.get_or_404()


def add_inline_instance(design: Design, *, name: str = "Part", transform=None) -> Assembly:
    """Place a part whose Design is embedded inline (PartSourceInline).

    The whole ``design`` travels inside the assembly (no external ``.nadoc``
    file), so the scripted assembly is self-contained — ideal for tests and for
    a one-shot programmatic build.  ``transform`` placement as in
    :func:`add_instance`.
    """
    return add_instance(
        {"type": "inline", "design": design.to_dict()},
        name=name, transform=transform,
    )


def add_file_instance(path: str, *, name: str = "Part", transform=None,
                      sha256: str | None = None) -> Assembly:
    """Place a part that references a workspace ``.nadoc`` file (PartSourceFile).

    ``path`` is relative to the project root / parts-library (the same resolution
    ``assembly_flatten._load_design`` uses).  ``transform`` placement as in
    :func:`add_instance`.
    """
    src: dict = {"type": "file", "path": path}
    if sha256 is not None:
        src["sha256"] = sha256
    return add_instance(src, name=name, transform=transform)


def place_grid(
    design: Design,
    rows: int,
    cols: int,
    *,
    pitch: float,
    row_pitch: float | None = None,
    plane: str = "XY",
    center: bool = False,
    name: str = "Part",
) -> Assembly:
    """Place ``rows × cols`` copies of *design* on a regular grid (AF-10).

    A parametric-layout helper: it computes the per-slot world translations with
    the pure :func:`backend.core.instance_layout.grid_translations` (slot ``(i, j)``
    at ``(j·pitch, i·row_pitch)`` in the chosen ``plane``; ``center=True`` centres
    the grid on the origin) and drives :func:`add_inline_instance` once per slot, so
    every copy carries a real ``assembly-add-instance`` feature-log entry — the grid
    is indistinguishable from clicking each part in.  ``row_pitch`` defaults to
    ``pitch``.  Parts are translated only (identity orientation).

    Pin the result with :func:`tests.automation_harness.assert_instances_on_grid`
    (the placed instance origins land on the exact ``rows × cols`` lattice).
    """
    for idx, (x, y, z) in enumerate(grid_translations(
        rows, cols, pitch=pitch, row_pitch=row_pitch, plane=plane, center=center,
    )):
        add_inline_instance(design, name=f"{name}_{idx}", transform=translation(x, y, z))
    return assembly_state.get_or_404()


def place_ring(
    design: Design,
    n: int,
    *,
    radius: float,
    plane: str = "XY",
    start_angle_deg: float = 0.0,
    center=(0.0, 0.0, 0.0),
    name: str = "Part",
) -> Assembly:
    """Place ``n`` copies of *design* evenly spaced on a ring (AF-10).

    A parametric-layout helper: it computes the per-slot world translations with the
    pure :func:`backend.core.instance_layout.ring_translations` (slot ``k`` at angle
    ``start_angle_deg + k·360°/n`` on a circle of ``radius`` about ``center``, in the
    chosen ``plane``) and drives :func:`add_inline_instance` once per slot, each with
    its own feature-log entry.  Parts are translated only (identity orientation —
    which way a part *faces* on the ring is an orientation convention this helper
    does not pick).

    Pin the result with :func:`tests.automation_harness.assert_instances_on_ring`
    (the placed origins lie on the ring of the requested radius at the exact angular
    step).
    """
    for idx, (x, y, z) in enumerate(ring_translations(
        n, radius=radius, plane=plane, start_angle_deg=start_angle_deg,
        center=tuple(float(v) for v in center),
    )):
        add_inline_instance(design, name=f"{name}_{idx}", transform=translation(x, y, z))
    return assembly_state.get_or_404()


def add_connector(instance_id: str, label: str, position, normal) -> Assembly:
    """Register a named connector (InterfacePoint) on an instance (POST .../connectors).

    ``position`` / ``normal`` are instance-LOCAL (3-vectors); the connector's world
    position is ``T_inst @ position``.  A connector is the named anchor a mate joins
    — :func:`define_mate` references two of these by label.  Records an
    ``assembly-add-connector`` feature-log entry.
    """
    _route_add_connector(instance_id, AddConnectorRequest(
        label=label, position=[float(v) for v in position], normal=[float(v) for v in normal],
    ))
    return assembly_state.get_or_404()


def define_mate(
    child_instance_id: str,
    parent_instance_id: str,
    *,
    child_label: str,
    parent_label: str,
    joint_type: str = "rigid",
    name: str = "Mate",
    axis_origin=(0.0, 0.0, 0.0),
    axis_direction=(0.0, 0.0, 1.0),
    min_limit: float | None = None,
    max_limit: float | None = None,
) -> Assembly:
    """Mate two existing connectors by label (POST /assembly/joints/create-mate).

    Both ``child_label`` (on ``child_instance_id``) and ``parent_label`` (on
    ``parent_instance_id``) must already be registered — call :func:`add_connector`
    first.  The route SNAPS the child instance so ``child_label``'s world position
    coincides with ``parent_label``'s, then records the joint (default ``rigid``);
    the connector-derived snap aligns the parts, so no FK transform is supplied.
    After this the connectors are coincident (:func:`resolve` re-applies the same
    constraint).  ``joint_type`` may be ``rigid`` / ``revolute`` / ``prismatic`` /
    ``spherical``; ``axis_*`` parameterise the moving DOF for the non-rigid kinds.
    Records an ``assembly-create-mate`` feature-log entry.
    """
    _route_create_mate(CreateMateRequest(
        child_connector=MateConnectorSpec(instance_id=child_instance_id, label=child_label),
        parent_connector=MateConnectorSpec(instance_id=parent_instance_id, label=parent_label),
        joint_type=joint_type,
        name=name,
        axis_origin=[float(v) for v in axis_origin],
        axis_direction=[float(v) for v in axis_direction],
        min_limit=min_limit,
        max_limit=max_limit,
    ))
    return assembly_state.get_or_404()


def drive_joint(
    joint_id: str,
    value: float,
    *,
    silent: bool = False,
    endpoint_side: str | None = None,
) -> Assembly:
    """Drive a revolute/prismatic joint to ``current_value = value`` (PATCH .../joints/{id}).

    ``value`` is the joint coordinate the route applies — **radians** for a
    revolute (rotation about ``axis_direction``), nm for a prismatic.  The route
    recomputes the moving body's transform from its ``base_transform`` (so repeated
    drives don't accumulate float drift), and — crucially for AF-9 — **propagates
    any gear/belt relation this joint participates in**: spinning one coupled wheel
    drives the other through the relation's ratio in the same call (path 1, the
    ring-drag path).  ``endpoint_side`` ('a'/'b') overrides which body moves for a
    revolute authored "backward" (fixed axle = child); ``None`` lets the route infer
    it.  Pass ``silent=True`` to suppress the undo push (animation-playback style).
    Records an ``assembly`` mutation feature-log entry.
    """
    _route_patch_joint(joint_id, PatchJointRequest(
        current_value=float(value), silent=silent, endpoint_side=endpoint_side,
    ))
    return assembly_state.get_or_404()


def define_gear(
    joint_a_id: str,
    joint_b_id: str,
    *,
    ratio: float = 1.0,
    invert: bool = False,
    name: str = "Gear",
    capture_anchors_from_current: bool = True,
    endpoint_a_instance_id: str | None = None,
    endpoint_b_instance_id: str | None = None,
    endpoint_a_side: str | None = None,
    endpoint_b_side: str | None = None,
) -> Assembly:
    """Couple two revolute joints with a constant gear ratio (POST /assembly/gear-relations).

    A :class:`GearRelation` makes rotating ``joint_a`` drive ``joint_b`` through
    ``θ_b = anchor_b + sign·(θ_a − anchor_a)·ratio`` (``sign = −1`` if ``invert``) —
    rendered as a row in the Mates list and applied by :func:`drive_joint` /
    :func:`resolve`, never by mutating any embedded Design (display-layer kinematics
    only).  Both ``joint_a_id`` and ``joint_b_id`` must already be **revolute** mates
    (build them with :func:`define_mate` ``joint_type="revolute"``); the route 400s
    otherwise.  By default each side's moving body is the joint's child (instance_b)
    and the anchors snapshot each joint's current value at creation (so the relation
    is satisfied from the current pose with no jump).  Pass ``endpoint_*`` to target
    the parent side of a "backward"-authored revolute (the Big_wheel_base case).
    Records an ``assembly-create-gear`` feature-log entry.
    """
    _route_create_gear_relation(CreateGearRelationRequest(
        name=name,
        joint_a_id=joint_a_id,
        joint_b_id=joint_b_id,
        endpoint_a_instance_id=endpoint_a_instance_id,
        endpoint_b_instance_id=endpoint_b_instance_id,
        endpoint_a_side=endpoint_a_side,
        endpoint_b_side=endpoint_b_side,
        ratio=ratio,
        invert=invert,
        capture_anchors_from_current=capture_anchors_from_current,
    ))
    return assembly_state.get_or_404()


def define_belt(
    joint_a_id: str,
    joint_b_id: str,
    *,
    radius_a: float,
    radius_b: float,
    name: str = "Belt",
    side_a: str | None = None,
    side_b: str | None = None,
    instance_a_id: str | None = None,
    instance_b_id: str | None = None,
    connector_a_label: str | None = None,
    connector_b_label: str | None = None,
) -> Assembly:
    """Wrap two revolute pulleys with an open belt (POST /assembly/belt-paths).

    An open :class:`BeltPath` couples its two pulley joints so rotating one drives
    the other at angular ratio ``radius_a / radius_b`` in the same world rotational
    sense (equal rim/tangential speed) — the belt is a :class:`GearRelation`-equivalent
    coupling, synthesised on the fly by ``_belt_to_relation`` and folded into the SAME
    propagation :func:`drive_joint` triggers (so spinning one pulley drives the other,
    exactly like a gear).  Both ``joint_a_id`` and ``joint_b_id`` must already be
    **revolute** mates (build them with :func:`define_mate` ``joint_type="revolute"``);
    the route 400s otherwise, and rejects a non-positive radius.  ``radius_a`` /
    ``radius_b`` are each pulley's rim radius — the kinematic knob that sets the ratio
    (the route stores them as advisory geometry; the coupling derives the ratio from
    them).  Default each pulley's moving body is its joint's child (side ``'b'``); pass
    ``side_*`` / ``instance_*`` for a "backward"-authored revolute.  The belt's coupling
    relation surfaces with the synthetic id ``f"__belt__{<belt id>}"`` (the id to hand
    :func:`tests.automation_harness.assert_gear_ratio` with ``expected_ratio =
    radius_a / radius_b``).  Records an ``assembly-create-belt`` feature-log entry.
    """
    _route_create_belt_path(CreateBeltPathRequest(
        name=name,
        pulley_a=BeltPulleyRequest(
            joint_id=joint_a_id, side=side_a, instance_id=instance_a_id,
            connector_label=connector_a_label, radius=float(radius_a),
        ),
        pulley_b=BeltPulleyRequest(
            joint_id=joint_b_id, side=side_b, instance_id=instance_b_id,
            connector_label=connector_b_label, radius=float(radius_b),
        ),
    ))
    return assembly_state.get_or_404()


def polymerize(
    joint_id: str,
    count: int,
    *,
    direction: str = "forward",
    additional_instance_ids=None,
) -> Assembly:
    """Grow a chain of identical parts from a seed mate (POST /assembly/polymerize).

    Replicate an existing mate (``joint_id`` — an :class:`AssemblyJoint` between two
    *identical* PartInstances ``A`` / ``B``) into a linear polymer of ``count`` total
    parts (the seed pair counts as 2).  The repeat transform is
    ``delta = T_B @ inv(T_A)``; forward copy ``k`` is placed at ``delta**k @ T_B``,
    backward copy ``k`` at ``inv(delta)**k @ T_A`` — so the chain marches along the
    seed mate's part-to-part offset.  ``direction`` is ``"forward"`` / ``"backward"`` /
    ``"both"`` (``both`` splits the new copies, extra forward when odd).  Consecutive
    copies are tied by replicated joints carrying the seed mate's
    ``mate_relative_transform`` so the chain re-resolves on edits and is feature-logged
    / undoable.  ``additional_instance_ids`` carries extra pattern-unit parts along at
    each step.  The route 422s unless the joint mates two identical parts.  Records an
    ``assembly-polymerize`` feature-log entry.

    Pin the result with :func:`tests.automation_harness.assert_polymer_chain` (every
    new copy sits on the ``delta``-power lattice + the count is exact).
    """
    _route_polymerize_assembly(PolymerizeAssemblyRequest(
        joint_id=joint_id,
        count=count,
        direction=direction,
        additional_instance_ids=list(additional_instance_ids or []),
    ))
    return assembly_state.get_or_404()


def bind_overhangs(
    instance_a_id: str,
    instance_b_id: str,
    *,
    overhang_a_id: str,
    sub_domain_a_id: str,
    overhang_b_id: str,
    sub_domain_b_id: str,
    binding_mode: str | None = None,
    allow_n_wildcard: bool | None = None,
) -> Assembly:
    """Create a cross-part Watson-Crick binding between two overhangs (POST
    /assembly/overhang-bindings).

    An :class:`AssemblyOverhangBinding` is *pure topology metadata* — it records
    that sub-domain ``sub_domain_a_id`` (on overhang ``overhang_a_id`` of
    ``instance_a_id``) is Watson-Crick paired to ``sub_domain_b_id`` on
    ``instance_b_id``; it applies **no geometry** and moves no part (unlike a mate
    or a linker connection).  Both referenced (overhang, sub-domain) pairs must
    already exist on their respective part designs — the route 404s otherwise — and
    the two endpoints must be distinct (no self-binding, 400) and not duplicate an
    existing binding (409, unordered).  ``binding_mode`` is ``'duplex'`` (default)
    or ``'toehold'``; ``allow_n_wildcard`` toggles N-base wildcard matching.
    Records an ``assembly-overhang-bind`` feature-log entry.

    Pin the result with :func:`tests.automation_harness.assert_binding_resolves`
    (both endpoints resolve to a real overhang sub-domain — even after a ``.nass``
    round-trip, which ``canonical_assembly`` alone cannot prove because it does not
    fingerprint overhang sub-domains).
    """
    _route_create_overhang_binding(CreateAssemblyOverhangBindingRequest(
        instance_a_id=instance_a_id,
        sub_domain_a_id=sub_domain_a_id,
        overhang_a_id=overhang_a_id,
        instance_b_id=instance_b_id,
        sub_domain_b_id=sub_domain_b_id,
        overhang_b_id=overhang_b_id,
        binding_mode=binding_mode,
        allow_n_wildcard=allow_n_wildcard,
    ))
    return assembly_state.get_or_404()


def patch_binding(
    binding_id: str,
    *,
    binding_mode: str | None = None,
    allow_n_wildcard: bool | None = None,
) -> Assembly:
    """Patch ``binding_mode`` / ``allow_n_wildcard`` on a binding (PATCH
    /assembly/overhang-bindings/{id}).

    Only the fields explicitly passed are sent (and changed); passing neither is a
    400.  Records an ``assembly-overhang-bind-patch`` feature-log entry.
    """
    fields: dict = {}
    if binding_mode is not None:
        fields["binding_mode"] = binding_mode
    if allow_n_wildcard is not None:
        fields["allow_n_wildcard"] = allow_n_wildcard
    _route_patch_overhang_binding(
        binding_id, PatchAssemblyOverhangBindingRequest(**fields))
    return assembly_state.get_or_404()


def unbind_overhangs(binding_id: str) -> Assembly:
    """Remove a cross-part overhang binding (DELETE /assembly/overhang-bindings/{id}).

    The inverse of :func:`bind_overhangs`; restores the assembly's binding set to
    its pre-bind fingerprint.  Records an ``assembly-overhang-unbind`` feature-log
    entry.
    """
    _route_delete_overhang_binding(binding_id)
    return assembly_state.get_or_404()


def resolve() -> Assembly:
    """Re-apply all joint constraints in topological order (POST /assembly/resolve).

    A no-op for a jointless assembly (Phase 1 placements); the entry point the
    mate/joint wrappers lean on to snap mated connectors coincident.
    """
    _route_resolve_assembly()
    return assembly_state.get_or_404()


def import_assembly(content: str) -> Assembly:
    """Load an assembly from a raw ``.nass`` JSON string (POST /assembly/import).

    Mirrors *File → Open Assembly* on a browser upload.  Used by the round-trip
    oracle (:func:`tests.automation_harness.roundtrip_nass`); operates on the bound
    document, so wrap it in :func:`assembly_scratch_session` to stay isolated.
    """
    _route_import_assembly(AssemblyImportRequest(content=content))
    return assembly_state.get_or_404()
