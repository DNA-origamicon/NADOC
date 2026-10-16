"""Prepare a registered command batch without publishing any intermediate state.

The public catalog compiles ordinary input definitions only. The existing replay
registry executes them, and regenerate owns recovery encoding. A future host must
capture/recheck document identity and revision and publish the one complete result.
This module neither grants write authority nor sandboxes local Python processes.
"""

from copy import deepcopy
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID, uuid5

from fastapi import HTTPException

from backend.core.models import (
    ClusterCreateLogEntry, ClusterOpLogEntry, ClusterRigidTransform,
    MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry,
)
from backend.core.part_batch_inputs import BatchRequest
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import ProofBudgetExceeded, command_rows, root_design
from backend.core.part_overlay_commands import command_input


MAX_HELIX_BP = 50_000
# Initial batch workload bound, separately counted from helix base pairs. This
# limits interval loops even when domains overlap or extend beyond helix bounds;
# the scientific validator still reports those conditions. Larger duplex batches
# need separate qualification, not a conversion that doubles this allowance.
MAX_STRAND_NUCLEOTIDES = 50_000
_PRODUCERS = {
    "helix-add": ("helix", "helix_id", "helices"),
    "strand-add": ("strand", "strand_id", "strands"),
    "nanoparticle-create": ("nanoparticle", "nanoparticle_id", "nanoparticles"),
    "cluster_create": ("cluster", "cluster_id", "cluster_transforms"),
}


@dataclass(frozen=True)
class _Step:
    index: int
    kind: str
    feature_id: str
    child_id: str | None
    entry: object
    outputs: tuple

    @property
    def identity(self):
        return self.child_id or self.feature_id

    def descriptor(self):
        return {"command_index": self.index, "kind": self.kind,
                "feature_id": self.feature_id, "child_id": self.child_id,
                "outputs": [{"kind": kind, "identity": identity} for kind, identity in self.outputs]}


def _reference(detail, kind, identity, path, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}])


def _unique(items, kind, identity, path):
    selected = [item for item in items if item.id == identity]
    if len(selected) != 1:
        _reference("Batch reference is missing or ambiguous", kind, identity, path, missing=not selected)
    return selected[0]


def _reserve_work(source, request):
    helices = sum(max(0, item.length_bp) for item in source.helices)
    residues = sum(abs(domain.end_bp - domain.start_bp) + 1
                   for strand in source.strands for domain in strand.domains)
    for command in request.commands:
        if command.kind == "helix-add":
            helices += command.params["length_bp"]
        elif command.kind == "strand-add":
            residues += sum(abs(domain["end_bp"] - domain["start_bp"]) + 1 for domain in command.params["domains"])
    if helices > MAX_HELIX_BP or residues > MAX_STRAND_NUCLEOTIDES:
        raise ProofBudgetExceeded("Registered batch exceeds aggregate helix or strand nucleotide work")


def _compile(source, request, history_seed, timestamp, dependency_resolver):
    if (type(history_seed) is not str or len(history_seed) != 36
            or type(timestamp) is not str or not timestamp or len(timestamp) > 128):
        raise CommandContractError("Batch needs a host UUID and bounded timestamp", code="invalid_batch_context")
    namespace = UUID(history_seed)
    used = {entry.id for entry in source.feature_log}
    existing_count = len(source.feature_log)
    for entry in source.feature_log:
        if entry.feature_type == "routing-cluster":
            used.update(child.id for child in entry.children)
            existing_count += len(entry.children)
    if len(used) != existing_count:
        raise CommandContractError("Existing feature identities are ambiguous", code="ambiguous_feature_identity")

    def allocate(role, index):
        identity = str(uuid5(namespace, f"part-batch-v1/{role}/{index}"))
        if identity in used:
            raise CommandContractError("Host batch identity collides with existing history", code="batch_identity_collision")
        used.add(identity)
        return identity

    reserved = {(kind, item.id) for kind, _, collection in _PRODUCERS.values() for item in getattr(source, collection)}
    log, steps = [], []
    for index, command in enumerate(request.commands):
        kind, params = command.kind, deepcopy(command.params)
        identity = allocate("command", index)
        outputs = ()
        if kind in _PRODUCERS:
            resource, key, _ = _PRODUCERS[kind]
            output = (resource, params[key])
            if output in reserved:
                _reference("Batch output identity already exists or is declared twice", *output, [key])
            reserved.add(output)
            outputs = (output,)
        child_id = None
        if kind in {"helix-add", "strand-add"}:
            key = "helix_id" if kind == "helix-add" else "strand_id"
            params[f"_{key}"] = params.pop(key)
            params["_proof_version"] = 1
            entry = MinorMutationLogEntry(id=identity, op_subtype=kind,
                label=command.label or kind, timestamp=timestamp, params=params)
            if not log or log[-1].feature_type != "routing-cluster":
                log.append(RoutingClusterLogEntry(id=allocate("routing", index), timestamp=timestamp))
            group = log[-1]
            log[-1] = group.model_copy(update={"children": [*group.children, entry]})
            child_id, feature_id = identity, group.id
        elif kind == "cluster_create":
            cluster = ClusterRigidTransform(id=params["cluster_id"], name=params["name"],
                helix_ids=params["helix_ids"], auto_created=False)
            from backend.core.part_overlay_commands import GROUP_CREATE_VERSION
            entry = ClusterCreateLogEntry(id=identity, proof_version=GROUP_CREATE_VERSION, cluster_id=cluster.id,
                name=cluster.name, helix_ids=list(cluster.helix_ids), cluster_snapshot=cluster)
            log.append(entry)
            feature_id = identity
        elif kind == "cluster_op":
            entry = ClusterOpLogEntry(id=identity, proof_version=1, **params)
            log.append(entry)
            feature_id = identity
        else:
            params.update(_proof_version=1, nanoparticle_version=1)
            entry = SnapshotLogEntry(id=identity, op_kind=kind,
                label=command.label or kind, timestamp=timestamp, params=params)
            log.append(entry)
            feature_id = identity
        native_kind, native_params = command_input(entry)
        if not dependency_resolver(native_kind, native_params).known:
            raise CommandContractError("Public command lacks its registered replay contract", code="missing_proof_contract")
        steps.append(_Step(index, kind, feature_id, child_id, entry, outputs))
    # Count routing group headers as well as their children, before any replay.
    needed = len(log) + sum(len(entry.children) for entry in log if entry.feature_type == "routing-cluster")
    list(command_rows(source, 2000 - needed))
    return log, steps


def _references(kind, design, params):
    """Exact selection checks absent from permissive legacy primitive adapters."""
    if kind == "helix-add":
        if any(item.id == params["_helix_id"] for item in design.helices):
            _reference("Helix output already exists", "helix", params["_helix_id"], ["helix_id"])
    elif kind == "strand-add":
        if any(item.id == params["_strand_id"] for item in design.strands):
            _reference("Strand output already exists", "strand", params["_strand_id"], ["strand_id"])
        for index, domain in enumerate(params["domains"]):
            _unique(design.helices, "helix", domain["helix_id"], ["domains", index, "helix_id"])
    elif kind == "cluster_create":
        cluster = params["cluster"]
        if any(item.id == cluster["id"] for item in design.cluster_transforms):
            _reference("Cluster output already exists", "cluster", cluster["id"], ["cluster_id"])
        owned = {identity for item in design.cluster_transforms if not item.is_default for identity in item.helix_ids}
        scoped_indices = defaultdict(set)
        for item in design.cluster_transforms:
            for ref in item.domain_ids:
                scoped_indices[ref.strand_id].add(ref.domain_index)
        # Resolve every matching strand when imported identities are ambiguous;
        # a last-wins dictionary would accidentally hide selected membership.
        scoped_helices = {domain.helix_id for strand in design.strands
                         for index in scoped_indices.get(strand.id, ())
                         for domain in strand.domains[index:index + 1]}
        for index, identity in enumerate(cluster["helix_ids"]):
            _unique(design.helices, "helix", identity, ["helix_ids", index])
            if identity in owned:
                _reference("Whole-helix batch grouping requires unowned or default-cluster members",
                           "helix", identity, ["helix_ids", index])
            if identity in scoped_helices:
                _reference("Whole-helix batch grouping cannot replace domain-scoped membership",
                           "helix", identity, ["helix_ids", index])
    elif kind == "cluster_op":
        _unique(design.cluster_transforms, "cluster", params["cluster_id"], ["cluster_id"])


class _Stopped(Exception):
    def __init__(self, status, issue):
        self.status, self.issue = status, issue


def prepare_batch(source, request, *, source_revision, history_seed, timestamp,
                  executor=None, dependency_resolver=None, checkpoint=lambda: None):
    """Return one complete candidate plus validation, or structured diagnostics.

    The revision and UUID seed must be supplied by the trusted capture host.
    The default executor is the ordinary registry: existing long-job refusals
    and all normal command/recovery budgets remain in force. Ready is not a
    cold-replay certificate or a statement that scientific validation passed.
    """
    from backend.api.part_proof_commands import dependencies, execute
    from backend.api.part_recipe_edit import regenerate
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.core.validator import validate_design

    request = BatchRequest.model_validate(request)
    executor, dependency_resolver = executor or execute, dependency_resolver or dependencies
    steps, completed, source_proof = [], [], None
    phase = "admission"

    def metadata():
        return {"phase": phase, "source_design_id": source.id, "source_revision": source_revision,
            "commands": [step.descriptor() for step in steps], "completed": list(completed),
            "not_evaluated": [step.identity for step in steps[len(completed):]],
            "candidate_replay_verified": False}

    def failure(status, issues):
        detail = metadata()
        failed = {issue.get("child_id") or issue.get("feature_id") for issue in issues}
        detail["not_evaluated"] = [identity for identity in detail["not_evaluated"] if identity not in failed]
        return {"status": status, "issues": issues, "batch": detail, "source_assessment": source_proof}

    try:
        checkpoint()
        if (type(source_revision) is not int or source_revision < 0
                or source.id != request.expected_design_id or source_revision != request.expected_revision):
            raise CommandContractError("Batch belongs to a different part or captured revision", code="batch_conflict")
        _reserve_work(source, request)
        log, steps = _compile(source, request, history_seed, timestamp, dependency_resolver)
        prefix = ReplayPrefix(source, len(source.feature_log))
        last = None

        def prove(kind, current, params):
            nonlocal last
            last = prefix.execute(executor, kind, current, deepcopy(params))
            return last

        phase = "source_proof"
        source_proof = assess_part_history(source, execute=prove, dependencies=dependency_resolver, checkpoint=checkpoint)
        if source_proof["status"] not in {"verified", "reproduced_import"}:
            return failure(source_proof["status"], source_proof["issues"])
        prefix.design = (last if last is not None else root_design(source.recipe_root, input_sources=source.input_sources)).copy_with(
            id=source.id, feature_log=list(prefix.log))

        def run(kind, current, params):
            nonlocal phase
            step = steps[len(completed)]
            if step.kind != kind:
                raise RuntimeError("Batch replay diverged from its compiled order")
            phase = "execution"
            try:
                _references(kind, current, params)
                updated = executor(kind, current, deepcopy(params))
            except CommandContractError as error:
                raise _Stopped(error.status, {**error.as_issue(), **step.descriptor()}) from error
            except ValueError as error:
                raise _Stopped("failed", {"code": "invalid_command_inputs", "detail": str(error)[:2048], **step.descriptor()}) from error
            except HTTPException as error:
                raise _Stopped("unverified" if error.status_code in {408, 413, 429} else "failed",
                    {"code": "evaluation_rejected", "detail": error.detail, "http_status": error.status_code,
                     **step.descriptor()}) from error
            completed.append(step.identity)
            phase = "recovery"
            return updated

        candidate = regenerate(source, [*prefix.log, *log], checkpoint, prefix=prefix, executor=run)
        if len(completed) != len(steps):
            raise RuntimeError("Batch did not execute every compiled command")
        phase = "validation"
        validation = validate_design(candidate)
        checkpoint()
        phase = "complete"
        return {"status": "ready", "issues": [], "candidate": candidate, "validation": validation,
                "batch": metadata(), "source_assessment": source_proof}
    except _Stopped as error:
        return failure(error.status, [error.issue])
    except CommandContractError as error:
        return failure(error.status, [error.as_issue()])
    except ProofBudgetExceeded as error:
        return failure("unverified", [{"code": "command_limit", "detail": str(error)[:2048]}])
    except ValueError as error:
        code = "entry_limit" if str(error) == "entry_limit" else "invalid_batch_inputs"
        return failure("unverified" if code == "entry_limit" else "failed", [{"code": code, "detail": str(error)[:2048]}])
