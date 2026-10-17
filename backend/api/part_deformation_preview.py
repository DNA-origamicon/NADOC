"""Private, bounded feature-stage bend/twist evaluation from native inputs.

The caller supplies independently owned input captured under its source lock
with preserve_entry_types=True. This module has no live document access, cache,
session/revision lease, publication path, geometry DTO, or proof certificate.
Only the prefix is executed; source equivalence and the suffix remain unchecked.
The time allowance is cooperative between native calls, not a hard wall limit.
"""

from copy import deepcopy
from dataclasses import dataclass
from math import ceil, dist, isfinite
from time import monotonic

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import BendParams, DeformationLogEntry, DeformationOp, Design, TwistParams
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import command_rows, root_design
from backend.core.part_group_organization import KINDS as ORGANIZATION_KINDS
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_overlay_commands import command_input, edit_entry
from backend.core.part_verification_capture import CaptureLimit, admit
from backend.core.validator import ValidationReport, validate_design


MAX_COMMANDS = 128
MAX_HELICES = 16
MAX_SLOTS = 1024
MAX_OPERATIONS = 64
MAX_BP_SPAN = 1024
# Native spline transport uses a much finer grid than one station per base.
# Keep that additional one-time prefix work independently bounded; this is not
# a claim that all sweeps fitting MAX_SLOTS also fit the preview path allowance.
MAX_PATH_SAMPLES = 1024
SECONDS = 1.0
EXTRUSIONS = frozenset({"extrude-segment", "extrude-continuation", "extrude-deformed-continuation",
                       "circle-segment", "extrude-frame"})
ROUTING = frozenset({
    "nick", "nick-batch", "strand-end-resize", "domain-shift", "ligate",
    "forced-ligation-create", "forced-ligation-delete", "forced-ligation-delete-batch",
    "crossover-place", "crossover-place-batch", "crossover-move", "crossover-move-batch",
    "crossover-delete", "crossover-delete-batch", "auto-crossover",
    "loop-skip-insert", "loop-skip-twist", "loop-skip-bend", "loop-skip-clear",
    "loop-skip-clear-all", "apply-loop-skips",
})
TRANSFORMS = frozenset({"nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete"})
EXTRA_BASES = frozenset({"crossover-extra-bases", "crossover-extra-bases-batch", "forced-ligation-extra-bases"})
CONSTRAINTS = frozenset({"joint-place", "joint-update", "joint-delete",
                         "flexible-segment-mark", "flexible-segment-unmark"})
PREFIX_KINDS = EXTRUSIONS | ROUTING | ORGANIZATION_KINDS | TRANSFORMS | EXTRA_BASES | CONSTRAINTS | frozenset({
    "bundle-create", "sweep", "deformation", "cluster_create", "cluster_op", "placement-poses",
})
PATCH_FIELDS = frozenset({"type", "plane_a_bp", "plane_b_bp", "params", "cluster_ids", "targets"})


def _reject(detail, code="unsupported_preview_scope"):
    raise CommandContractError(detail, code=code)


def _checkpoint():
    deadline = monotonic() + SECONDS

    def check():
        if monotonic() > deadline:
            _reject("Deformation preview exceeded its cooperative time allowance", "preview_limit")

    return check


def _admit(design, check):
    check()
    try:
        admit(design, preserve_entry_types=True)
    except CaptureLimit as error:
        _reject(str(error), "preview_limit")
    check()


def _identity(value):
    if type(value) is not str or not value or len(value) > 256:
        _reject("Preview requires a bounded stable feature identity", "invalid_preview_definition")
    return value


def _json(value):
    try:
        validate_operation_input(value)
    except ValueError as error:
        _reject(str(error), "invalid_preview_definition")


def _bp(value):
    if type(value) is not int or abs(value) > 1_000_000:
        _reject("Preview requires bounded integer base-pair addresses", "preview_limit")
    return value


def _span(design, *addresses):
    positions = list(addresses)
    for helix in design.helices:
        positions.extend((_bp(helix.bp_start), _bp(helix.bp_start + helix.length_bp - 1)))
    for strand in design.strands:
        for domain in strand.domains:
            positions.extend((_bp(domain.start_bp), _bp(domain.end_bp)))
    if positions and max(positions) - min(positions) + 1 > MAX_BP_SPAN:
        _reject("Deformation preview exceeds its frame-span allowance", "preview_limit")


def _path_work(points):
    if type(points) is not list or not 2 <= len(points) <= MAX_PATH_SAMPLES:
        _reject("Preview requires a bounded native sweep path", "preview_limit")
    if any(type(point) not in {list, tuple} or len(point) != 3 for point in points):
        _reject("Preview requires XYZ sweep controls", "invalid_preview_definition")
    # Admission mirrors path_table's sample-count rule, never its spline or
    # placement math. Its unchanged 0.05 nm spacing/64-sample floor must fit
    # this private preview's smaller allowance before native arrays are built.
    samples = 1
    for first, second in zip(points, points[1:]):
        distance = dist(first, second)
        if not isfinite(distance) or distance > MAX_PATH_SAMPLES * .05:
            _reject("Sweep exceeds the private preview path-work allowance", "preview_limit")
        samples += max(64, ceil(distance / .05))
        if samples > MAX_PATH_SAMPLES:
            _reject("Sweep exceeds the private preview path-work allowance", "preview_limit")


def _operation(op, design, *, retained=False):
    if op.type == "sweep" and retained:
        if op.params.bp_positions_nm is not None or op.params.bp_frames is not None:
            _reject("Sampled generated paths need a separate preview contract")
        _path_work(op.params.points_nm)
        if not 1 <= op.params.steps <= MAX_SLOTS:
            _reject("Sweep exceeds the private preview station allowance", "preview_limit")
    elif op.type not in {"bend", "twist"} or op.type != op.params.kind:
        _reject("This private preview supports ordinary bend and twist definitions only")
    a, b = _bp(op.plane_a_bp), _bp(op.plane_b_bp)
    if a > b or (a == b and op.type != "sweep"):
        _reject("The first deformation plane must precede the second", "invalid_preview_definition")
    # Native endpoint-fit evaluation may construct frame tables across gaps;
    # bounded site counts alone would not bound an outlying control plane.
    _span(design, a, b)


def _slots(design):
    return sum(2 * (helix.length_bp + sum(max(0, mark.delta) for mark in helix.loop_skips))
               for helix in design.helices) + _extra_slots(design)


def _extra_slots(design):
    return (sum(len(item.extra_bases or "") for items in (design.crossovers, design.forced_ligations)
                for item in items)
            + sum(len(item.sequence or "") + bool(item.modification) for item in design.extensions))


def _extra_growth(kind, design, params):
    """Bound inserted material before its unchanged metadata builder runs."""
    forced = kind == "forced-ligation-extra-bases"
    field, identity_key = ("forced_ligations", "fl_id") if forced else ("crossovers", "crossover_id")
    entries = params.get("entries") if kind.endswith("-batch") else [params]
    if type(entries) is not list or len(entries) > MAX_SLOTS:
        _reject("Inserted-base edits exceed the preview work allowance", "preview_limit")
    replacements = {}
    for item in entries:
        if (type(item) is not dict or type(item.get(identity_key)) is not str
                or type(item.get("sequence")) is not str):
            _reject("Inserted-base edits require native junction identities and sequences", "invalid_preview_definition")
        replacements[item[identity_key]] = len(item["sequence"])
    existing = {item.id: len(item.extra_bases or "") for item in getattr(design, field)}
    # Unknown identities remain native reference errors, but their proposed
    # allocation is still charged before dispatch. Duplicate edits use the
    # native last-by-identity semantics.
    total = _slots(design) + sum(length - existing.get(identity, 0)
                                 for identity, length in replacements.items())
    if total > MAX_SLOTS:
        _reject("Inserted material exceeds the preview site allowance", "preview_limit")


def _growth(design, sites, helices=0):
    if sites < 0 or _slots(design) + sites > MAX_SLOTS or len(design.helices) + helices > MAX_HELICES:
        _reject("Prefix growth exceeds the private preview site allowance", "preview_limit")


def _extent_allowance(design, extents):
    """Charge each prospective native helix interval once, including inserts."""
    sites = _extra_slots(design)
    positions = []
    for helix in design.helices:
        lo, hi = extents.get(helix.id, (helix.bp_start, helix.bp_start + helix.length_bp - 1))
        _bp(lo), _bp(hi)
        positions.extend((lo, hi))
        sites += 2 * (hi - lo + 1 + sum(max(0, mark.delta) for mark in helix.loop_skips))
    if sites > MAX_SLOTS:
        _reject("Routing growth exceeds the private preview site allowance", "preview_limit")
    _span(design, *positions)


def _routing_extents(kind, design, params):
    from backend.api.part_command_references import validate_command_references

    validate_command_references(kind, design, params)
    # Native resize adds delta to the selected global endpoint regardless of
    # strand direction; native shift adds it to both endpoints. Only scalar
    # coordinates are projected here, including repeated entries in order.
    strands = {strand.id: strand for strand in design.strands}
    domains = {(strand.id, index): [domain.helix_id, domain.start_bp, domain.end_bp]
               for strand in design.strands for index, domain in enumerate(strand.domains)}
    for entry in params["entries"]:
        delta = _bp(entry["delta_bp"])
        strand = strands[entry["strand_id"]]
        if kind == "domain-shift":
            domain = domains[(strand.id, entry["domain_index"])]
            domain[1] += delta
            domain[2] += delta
        else:
            index = 0 if entry["end"] == "5p" else len(strand.domains) - 1
            domains[(strand.id, index)][1 if entry["end"] == "5p" else 2] += delta
    extents = {}
    for helix_id, first, last in domains.values():
        lo, hi = sorted((first, last))
        current = extents.get(helix_id, (lo, hi))
        extents[helix_id] = (min(lo, current[0]), max(hi, current[1]))
    _extent_allowance(design, extents)


def _continuation_growth(design, params):
    from backend.api.crud import BundleContinuationRequest
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.continuation_source import continuation_source_helices
    from backend.core.lattice import _find_continuation_helix, _find_same_cell_helix

    body = BundleContinuationRequest.model_validate(params)
    source = continuation_source_helices(design, body.source_frame_id, body.plane)
    component = {"XY": "z", "XZ": "y", "YZ": "x"}[body.plane]
    sites, new_helices = 0, 0
    for row, col in body.cells:
        match = _find_continuation_helix(source, row, col, body.plane, body.offset_nm)
        gap = None if match else _find_same_cell_helix(source, row, col, body.plane, body.offset_nm)
        if gap is not None:
            offset = body.offset_nm - getattr(gap.axis_start, component)
            if abs(offset) > MAX_BP_SPAN * BDNA_RISE_PER_BP:
                _reject("Continuation gap exceeds the preview frame-span allowance", "preview_limit")
            # Same scalar extent used by make_bundle_continuation's gap branch;
            # the empty interval is native geometry work even without strands.
            count = round(offset / BDNA_RISE_PER_BP) + abs(body.length_bp)
            sites += 2 * max(0, count - gap.length_bp)
        else:
            sites += 2 * abs(body.length_bp)
            forward = match is not None and abs(getattr(match.axis_end, component) - body.offset_nm) < BDNA_RISE_PER_BP * .05
            if match is None or (forward and not body.extend_inplace):
                new_helices += 1
    return sites, new_helices


def _work(design, check):
    check()
    if len(design.helices) > MAX_HELICES or len(design.deformations) + len(design.cluster_transforms) > MAX_OPERATIONS:
        _reject("Deformation preview exceeds its object allowance", "preview_limit")
    slots = _extra_slots(design)
    if slots > MAX_SLOTS or len(design.nucleotide_transforms) > MAX_SLOTS:
        _reject("Residue poses or inserted material exceed the preview site allowance", "preview_limit")
    if sum(len(getattr(design, field)) for field in (
            "cluster_joints", "flexible_segment_marks", "flexible_connections")) > MAX_SLOTS:
        _reject("Constraint context exceeds the preview work allowance", "preview_limit")
    for helix in design.helices:
        check()
        if type(helix.length_bp) is not int or helix.length_bp < 1:
            _reject("Deformation preview requires positive native helix spans", "invalid_preview_definition")
        slots += 2 * (helix.length_bp + sum(max(0, mark.delta) for mark in helix.loop_skips))
        if slots > MAX_SLOTS:
            _reject("Deformation preview exceeds its native site allowance", "preview_limit")
    walk = sum(abs(domain.end_bp - domain.start_bp) + 1
               for strand in design.strands for domain in strand.domains)
    if walk > MAX_SLOTS:
        _reject("Deformation preview exceeds its occupied-domain allowance", "preview_limit")
    for op in design.deformations:
        _operation(op, design, retained=True)
    _span(design)
    check()


def _before_command(kind, params, design):
    if "_generated_scope" in params:
        _reject(f"Private deformation preview does not yet replay prefix command {kind!r}")
    if kind not in PREFIX_KINDS:
        from backend.api.part_transform_prefix_admission import admit as admit_producer
        if admit_producer(kind, design, {key: value for key, value in params.items() if key != "_generator"}):
            return
        _reject(f"Private deformation preview does not yet replay prefix command {kind!r}")
    # Match the shared dispatcher: provenance annotation is not builder input.
    params = {key: value for key, value in params.items() if key != "_generator"}
    if kind == "flexible-segment-mark":
        marks = params.get("marks")
        retained = 0 if params.get("replace") else len(design.flexible_segment_marks)
        if type(marks) is not list or retained + len(marks) > MAX_SLOTS:
            _reject("Flexible marks exceed the preview work allowance", "preview_limit")
        # The unchanged native builder derives unpaired sites/connections from
        # the bounded current topology. Batch deduplication can only reduce
        # this conservative prospective count.
    elif kind in EXTRA_BASES:
        _extra_growth(kind, design, params)
    elif kind == "nucleotide-transform-batch":
        bodies = params.get("transforms")
        if type(bodies) is not list or len(bodies) > MAX_SLOTS:
            _reject("Transform batch exceeds the private preview work allowance", "preview_limit")
    elif kind == "bundle-create" or kind in EXTRUSIONS:
        # The shared executor still enforces its own 512-cell/50k-bp guard.
        # This lower private-preview allowance bounds its first allocation.
        cells, length = params.get("cells"), params.get("length_bp")
        if type(cells) is not list or len(cells) > MAX_HELICES:
            _reject("Bundle exceeds the private preview site allowance", "preview_limit")
        if kind == "circle-segment":
            lengths = params.get("cell_lengths")
            if (type(lengths) is not list or len(lengths) != len(cells)
                    or any(type(value) is not int for value in lengths)):
                _reject("Circle requires one bounded length per cell", "invalid_preview_definition")
            sites = 2 * sum(abs(value) for value in lengths)
        else:
            if type(length) is not int or (kind == "bundle-create" and length < 1):
                _reject("Bundle requires an integer native span", "invalid_preview_definition")
            sites = 2 * len(cells) * abs(length)
        if kind == "extrude-continuation":
            sites, new_helices = _continuation_growth(design, params)
        else:
            new_helices = len(cells)
        _growth(design, sites, new_helices)
        if params.get("source_bp") is not None:
            _span(design, _bp(params["source_bp"]))
    elif kind == "sweep":
        from backend.core.sweep import SweepRequest, sweep_preview

        # The source and path controls are already structurally admitted. Bound
        # native path planning before it computes exact arc length/strand count.
        body = SweepRequest.model_validate(params)
        _growth(design, 0, len(body.cells))
        _path_work(body.model_dump(mode="json")["points_nm"])
        preview, _source = sweep_preview(design, body, include_geometry=False)
        _growth(design, 2 * preview["total_new_bp"], len(body.cells))
        # execute reuses the same unchanged native planner. This bounded extra
        # preparation is paid once for the prefix, never per slider evaluation.
    elif kind == "deformation":
        try:
            op = DeformationOp.model_validate({k: v for k, v in params.items() if k != "_proof_version"})
        except ValueError as error:
            _reject(str(error), "invalid_preview_definition")
        _operation(op, design)
    elif kind in {"strand-end-resize", "domain-shift"}:
        entries = params.get("entries", [])
        if type(entries) is not list or len(entries) > MAX_SLOTS:
            _reject("Routing exceeds the private preview entry allowance", "preview_limit")
        _routing_extents(kind, design, params)
    elif kind in {"crossover-move", "crossover-move-batch"}:
        entries = params["moves"] if kind.endswith("-batch") else [params]
        if type(entries) is not list or len(entries) > MAX_SLOTS:
            _reject("Routing exceeds the private preview entry allowance", "preview_limit")
        endpoints = []
        for entry in entries:
            endpoints.append(_bp(entry["new_index"]))
        _span(design, *endpoints)
        # Moving a crossover can extend both of its helices to the new site.
        by_id = {item.id: item for item in design.crossovers}
        helices = {item.id: item for item in design.helices}
        extents = {helix.id: (helix.bp_start, helix.bp_start + helix.length_bp - 1)
                   for helix in design.helices}
        for entry in entries:
            crossover = by_id.get(entry["crossover_id"])
            if crossover is None:
                continue  # Shared reference admission supplies its typed error.
            for half in (crossover.half_a, crossover.half_b):
                helix = helices.get(half.helix_id)
                if helix is not None:
                    lo, hi = extents[helix.id]
                    extents[helix.id] = (min(lo, entry["new_index"]), max(hi, entry["new_index"]))
        _extent_allowance(design, extents)
    elif kind in {"loop-skip-twist", "loop-skip-bend", "loop-skip-clear"}:
        a, b = _bp(params["plane_a_bp"]), _bp(params["plane_b_bp"])
        _span(design, a, b)
        # Native per-cell density admission remains authoritative. This bounds
        # its input interval walk before it allocates modification/cell lists.
        if len(params["helix_ids"]) * abs(b - a) > MAX_SLOTS:
            _reject("Loop/skip planning exceeds the private preview work allowance", "preview_limit")
    elif kind == "loop-skip-insert" and params.get("delta") == 1:
        _growth(design, 2)


def _run(kind, design, params, check):
    check()
    try:
        _before_command(kind, params, design)
        check()
        updated = execute(kind, design, params)
    except CommandContractError:
        raise
    except (ValueError, TypeError, KeyError, NotImplementedError) as error:
        _reject(str(error), "preview_command_failed")
    check()
    _admit(updated, check)
    _work(updated, check)
    return updated


@dataclass(frozen=True, slots=True)
class PreparedPreview:
    """Internal retained inputs; callers receive copies, never the owned prefix.

    Its private models are not an immutable public API or a host lease. The
    future host must own this object exclusively and bind it to its session.
    """

    feature_id: str
    deformation_id: str
    design_id: str
    _prefix: Design
    _entry: DeformationLogEntry

    def copy_prefix(self):
        """Independent control-context input; contains no recovery/history rows."""
        return self._prefix.model_copy(deep=True)


@dataclass(frozen=True, slots=True)
class EvaluatedPreview:
    design: Design
    entry: DeformationLogEntry
    validation: ValidationReport
    stage: str = "feature"
    source_equivalence_checked: bool = False
    downstream_evaluated: bool = False


@dataclass(frozen=True, slots=True)
class PreparedCreation:
    """One private latest-stage prefix; there is no candidate operation yet."""

    feature_id: str
    deformation_id: str
    design_id: str
    _prefix: Design
    kind: str
    _targets: list | None
    _cluster_ids: list[str]

    def copy_prefix(self):
        return self._prefix.model_copy(deep=True)

    def creation_inputs(self):
        return {"type": self.kind, "targets": deepcopy(self._targets),
                "cluster_ids": list(self._cluster_ids)}


def _prefix_rows(captured, check, *, reserved=0, future_feature=None, future_operation=None):
    """Shared bounded history admission, before any native prefix execution."""
    check()
    if type(captured) is not Design or set(Design.model_fields) != set(FIELD_ROLES):
        _reject("Preview requires the reviewed standard-part schema")
    _admit(captured, check)
    if captured.recipe_root is None:
        _reject("Preview requires an explicit recipe root", "missing_recipe_root")
    if captured.recipe_root.version != 1 or captured.recipe_root.kind != "empty":
        _reject("This private preview supports version-one empty native roots only")
    if captured.feature_log_cursor != -1 or captured.feature_log_sub_cursor is not None:
        _reject("Return to the latest history position before previewing an edit", "historical_cursor")
    seen, by_id, count = set(), {}, 0
    for parent in captured.feature_log:
        entries = [parent, *parent.children] if parent.feature_type == "routing-cluster" else [parent]
        for entry in entries:
            check()
            count += 1
            if count + reserved > MAX_COMMANDS:
                _reject("Preview exceeds its command-count allowance", "preview_limit")
            identity = _identity(entry.id)
            if identity in seen:
                _reject(f"Duplicate feature identity {identity!r}", "ambiguous_feature")
            seen.add(identity)
            by_id[identity] = entry
    if future_feature is not None and future_feature in seen:
        _reject("The new feature identity already exists", "ambiguous_feature")
    if future_operation is not None and (
            future_operation == future_feature
            or any(op.id == future_operation for op in captured.deformations)
            or any(type(entry) is DeformationLogEntry and entry.deformation_id == future_operation
                   for entry in by_id.values())):
        _reject("The new deformation identity already exists", "ambiguous_feature")
    rows = []
    for identity, kind, params in command_rows(captured, MAX_COMMANDS):
        check()
        _json(params)
        try:
            known = dependencies(kind, params).known
        except (ValueError, KeyError, TypeError) as error:
            _reject(f"Invalid command {identity!r}: {error}", "invalid_preview_definition")
        if not known:
            _reject(f"Feature {identity!r} lacks a native proof contract", "missing_proof_contract")
        rows.append((identity, kind, params))
    return rows, by_id


def _replay_prefix(captured, rows, check, *, stop=None, runner=None):
    try:
        current = root_design(captured.recipe_root).copy_with(id=captured.id)
    except (ValueError, TypeError) as error:
        _reject(str(error), "invalid_recipe_root")
    for identity, kind, params in rows:
        if identity == stop:
            break
        updated = (_run(kind, current, params, check) if runner is None
                   else runner(identity, kind, current, params, check))
        current = updated.copy_with(
            id=captured.id, recipe_root=captured.recipe_root,
        )
    return current


def prepare_from_capture(captured, feature_id):
    """Replay only the selected prefix; neither suffix nor source is proved."""
    check = _checkpoint()
    feature_id = _identity(feature_id)
    rows, entries = _prefix_rows(captured, check)
    selected = entries.get(feature_id)
    if selected is None:
        raise ReferenceResolutionError("The selected preview feature no longer exists", references=[
            {"kind": "feature", "identity": feature_id, "parameter_path": ["feature_id"]},
        ])
    if type(selected) is not DeformationLogEntry:
        _reject("Select a typed native deformation entry; capture must preserve entry types")
    if selected.proof_version != 1:
        _reject("Selected deformation lacks a native proof contract", "missing_proof_contract")
    if selected.op_snapshot is None or selected.deformation_id != selected.op_snapshot.id:
        _reject("Deformation feature and operation identities disagree", "invalid_preview_definition")
    _identity(selected.deformation_id)
    current = _replay_prefix(captured, rows, check, stop=feature_id)
    _operation(selected.op_snapshot, current)
    _admit(current, check)
    # Builders derive a fresh graph from empty inputs. The sole remaining
    # mutable alias into captured history is the selected native definition.
    entry = selected.model_copy(deep=True)
    check()
    return PreparedPreview(feature_id, entry.deformation_id, captured.id, current, entry)


def creation_scope(prefix, targets, cluster_ids, *, planes=None):
    """Resolve authored selection with existing native semantics, never []→all."""
    from backend.core.deformation import helices_crossing_planes, resolve_cluster_scope
    from backend.core.part_group_selection import resolve_deformation_targets, target_references

    _json({"targets": targets, "cluster_ids": cluster_ids})
    if (type(cluster_ids) is not list or any(type(identity) is not str or not 0 < len(identity) <= 256
                                           for identity in cluster_ids)
            or len(cluster_ids) != len(set(cluster_ids))):
        _reject("Placement selection requires unique bounded identities", "invalid_preview_reference")
    placements = {cluster.id for cluster in prefix.cluster_transforms}
    if set(cluster_ids) - placements:
        _reject("A selected numerical placement no longer exists", "invalid_preview_reference")
    if targets is not None:
        target_references(targets)  # Close legacy selector grammar before native parsing too.
        try:
            ranges = resolve_deformation_targets(prefix, targets)
        except CommandContractError:
            raise
        except ValueError as error:
            _reject(str(error), "invalid_preview_reference")
        if not ranges or (planes is not None and not any(
                item.start_bp < planes[1] and item.end_bp > planes[0] for item in ranges)):
            _reject("Selection does not intersect the deformation window", "invalid_preview_reference")
        return sorted({item.helix_id for item in ranges}), ranges
    available = ([helix.id for helix in prefix.helices] if planes is None else
                 helices_crossing_planes(prefix, *planes))
    resolved = resolve_cluster_scope(prefix, cluster_ids, available)
    if not resolved["helix_ids"]:
        _reject("Selected placement or whole-part scope contains no deformable helices",
                "invalid_preview_reference")
    return resolved["helix_ids"], None


def prepare_creation_from_capture(captured, *, feature_id, deformation_id, kind, targets, cluster_ids):
    """Prepare the complete current stage, with no fabricated operation/planes."""
    check = _checkpoint()
    feature_id, deformation_id = _identity(feature_id), _identity(deformation_id)
    if type(kind) is not str or kind not in {"bend", "twist"}:
        _reject("Creation supports ordinary Bend and Twist", "invalid_preview_definition")
    rows, _entries = _prefix_rows(captured, check, reserved=1,
                                  future_feature=feature_id, future_operation=deformation_id)
    current = _replay_prefix(captured, rows, check)
    _work(current, check)
    if len(current.deformations) + len(current.cluster_transforms) >= MAX_OPERATIONS:
        _reject("Creation exceeds the private preview operation allowance", "preview_limit")
    creation_scope(current, targets, cluster_ids)
    _admit(current, check)
    check()
    return PreparedCreation(feature_id, deformation_id, captured.id, current, kind,
                            deepcopy(targets), list(cluster_ids))


def _evaluate_creation(prepared, prefix, patch, check):
    import json

    if type(patch) is not dict:
        _reject("Creation requires complete plane and parameter inputs", "invalid_preview_definition")
    _json(patch)
    required = {"plane_a_bp", "plane_b_bp", "params"}
    if not required <= set(patch) or set(patch) - (required | {"cluster_ids"}):
        _reject("Creation requires complete planes/parameters and cannot replace its selection or identity",
                "invalid_preview_definition")
    if type(patch["plane_a_bp"]) is not int or type(patch["plane_b_bp"]) is not int:
        _reject("Creation planes require integer base-pair addresses", "invalid_preview_definition")
    a, b = _bp(patch["plane_a_bp"]), _bp(patch["plane_b_bp"])
    if a >= b:
        _reject("The first deformation plane must precede the second", "invalid_preview_definition")
    cluster_ids = patch.get("cluster_ids", prepared._cluster_ids)
    if prepared._targets is not None and cluster_ids != prepared._cluster_ids:
        _reject("Typed selection cannot change its numerical placement context", "invalid_preview_definition")
    values = patch["params"]
    model = BendParams if prepared.kind == "bend" else TwistParams
    if (type(values) is not dict or set(values) - set(model.model_fields)
            or values.get("kind", prepared.kind) != prepared.kind):
        _reject("Creation parameters do not match the deformation family", "invalid_preview_definition")
    try:
        native_params = model.model_validate_json(json.dumps(values, allow_nan=False), strict=True)
    except ValueError as error:
        _reject(str(error), "invalid_preview_definition")
    ids, ranges = creation_scope(prefix, prepared._targets, cluster_ids, planes=(a, b))
    op = DeformationOp(id=prepared.deformation_id, type=prepared.kind, plane_a_bp=a, plane_b_bp=b,
                       targets=deepcopy(prepared._targets), target_ranges=ranges,
                       affected_helix_ids=ids, cluster_ids=list(cluster_ids), params=native_params)
    entry = DeformationLogEntry(id=prepared.feature_id, deformation_id=op.id, op_snapshot=op, proof_version=1)
    kind, params = command_input(entry)
    candidate = _run(kind, prefix, params, check)
    report = validate_design(candidate)
    check()
    entry = entry.model_copy(update={"op_snapshot": candidate.deformations[-1].model_copy(deep=True)})
    return EvaluatedPreview(candidate, entry, report)


def prepare_creation_append(captured, prepared, patch, checkpoint):
    """Prove the fresh source, rebuild its recovery, then append one native row."""
    from fastapi import HTTPException
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_structure_gate import require_valid_structure

    if type(prepared) is not PreparedCreation or captured.id != prepared.design_id:
        _reject("Creation belongs to a different owned source", "invalid_preview_definition")
    _prefix_rows(captured, checkpoint, reserved=1, future_feature=prepared.feature_id,
                 future_operation=prepared.deformation_id)
    replay = ReplayPrefix(captured, len(captured.feature_log))
    last = None

    def prove(kind, current, params):
        nonlocal last
        last = replay.execute(lambda k, d, p: _run(k, d, p, checkpoint), kind, current, params)
        return last

    proof = assess_part_history(captured, execute=prove, dependencies=dependencies, checkpoint=checkpoint)
    if proof["status"] != "verified":
        raise HTTPException(409, detail={"code": "recipe_not_reproducible", "assessment": proof})
    current = (last if last is not None else root_design(captured.recipe_root)).copy_with(id=captured.id)
    evaluated = _evaluate_creation(prepared, current, patch, checkpoint)
    candidate = evaluated.design.copy_with(recipe_root=captured.recipe_root,
        input_sources=dict(captured.input_sources), feature_log=[*replay.log, evaluated.entry],
        feature_log_cursor=-1, feature_log_sub_cursor=None)
    require_valid_structure(candidate, checkpoint=checkpoint)
    checkpoint()
    return candidate, evaluated.validation


def evaluate(prepared, patch):
    """Build one isolated edited overlay; never replay prefix/suffix or publish."""
    check = _checkpoint()
    check()
    if type(prepared) is PreparedCreation:
        _admit(prepared._prefix, check)
        return _evaluate_creation(prepared, prepared.copy_prefix(), patch, check)
    if type(prepared) is not PreparedPreview or type(patch) is not dict:
        _reject("Preview requires prepared native inputs and an object patch", "invalid_preview_definition")
    _json(patch)
    if set(patch) - PATCH_FIELDS:
        _reject("This preview edits parameters, planes, or reviewed group selection only")
    original = prepared._entry.op_snapshot
    if patch.get("type", original.type) != original.type:
        _reject("A preview cannot change the recorded deformation family")
    if original.targets is not None and patch.get("cluster_ids", original.cluster_ids) != original.cluster_ids:
        _reject("Changing cluster scope requires a separately reviewed selection workflow")
    if "cluster_ids" in patch:
        ids = patch["cluster_ids"]
        if type(ids) is not list or any(type(identity) is not str for identity in ids):
            _reject("Cluster selection must contain native identities", "invalid_preview_definition")
        if len(ids) != len(set(ids)) or set(ids) - {cluster.id for cluster in prepared._prefix.cluster_transforms}:
            _reject("Cluster selection no longer exists in this feature prefix", "invalid_preview_reference")
    if "params" in patch:
        values = patch["params"]
        model = BendParams if original.type == "bend" else TwistParams
        if type(values) is not dict or set(values) - set(model.model_fields):
            _reject("Preview parameters do not match the native deformation schema", "invalid_preview_definition")
    _admit(prepared._prefix, check)
    # Each evaluation owns both the mutable native input and edited definition.
    # An exception or consumer mutation cannot affect the next slider result.
    prefix = prepared.copy_prefix()
    entry = prepared._entry.model_copy(deep=True)
    from copy import deepcopy
    try:
        entry = edit_entry(entry, deepcopy(patch), prefix=prefix)
    except CommandContractError:
        raise
    except ValueError as error:
        _reject(str(error), "invalid_preview_definition")
    kind, params = command_input(entry)
    candidate = _run(kind, prefix, params, check)
    report = validate_design(candidate)
    check()
    entry = entry.model_copy(update={"op_snapshot": candidate.deformations[-1].model_copy(deep=True)})
    return EvaluatedPreview(candidate, entry, report)
