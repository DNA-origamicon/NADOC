"""Resolve authored movement references before native recipe execution.

Only consumed identity families are indexed, once per command. Native residue
address validation stays authoritative; this layer supplies actionable paths,
rejects ambiguous identities and never changes placement or occupancy rules.
"""

from backend.core.part_command_errors import ReferenceResolutionError


KINDS = frozenset({"cluster_op", "placement-poses", "nucleotide-transform", "nucleotide-transform-batch",
                   "nucleotide-transform-delete"})
_FIELDS = {"cluster": "cluster_transforms", "helix": "helices", "strand": "strands",
           "overhang": "overhangs", "nucleotide_transform": "nucleotide_transforms", "joint": "cluster_joints"}


def _fail(kind, identity, path, *, ambiguous=False, detail=None):
    raise ReferenceResolutionError(
        detail or ("Movement target is ambiguous" if ambiguous else "Movement target no longer exists"),
        code="invalid_selection" if ambiguous else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


class _References:
    def __init__(self, design):
        self.design = design
        self.indexes = {}

    def resolve(self, kind, identity, path):
        if kind not in self.indexes:
            values = ([*self.design.crossovers, *self.design.forced_ligations]
                      if kind == "crossover" else getattr(self.design, _FIELDS[kind]))
            index = {}
            for value in values:
                index.setdefault(value.id, []).append(value)
            self.indexes[kind] = index
        matches = self.indexes[kind].get(identity, ())
        if len(matches) != 1:
            _fail(kind, identity, path, ambiguous=bool(matches))
        return matches[0]


def _placement(refs, params, *, path_prefix=None, authored_path=None):
    from backend.core.models import DomainRef

    path_prefix = [] if path_prefix is None else path_prefix
    authored_path = path_prefix if authored_path is None else authored_path
    owner_path = [*path_prefix, "cluster_id"]
    owner = refs.resolve("cluster", params["cluster_id"], owner_path)
    visited = set()
    selected = True
    while owner is not None:
        if owner.id in visited:
            _fail("cluster", owner.id, owner_path, ambiguous=True,
                  detail="Movement placement has a cyclic parent reference")
        visited.add(owner.id)
        explicit_helices = selected and "helix_ids" in params
        explicit_domains = selected and "domain_ids" in params
        helices = params["helix_ids"] if explicit_helices else owner.helix_ids
        domains = params["domain_ids"] if explicit_domains else owner.domain_ids
        for index, identity in enumerate(helices):
            path = [*authored_path, "helix_ids", index] if explicit_helices else owner_path
            refs.resolve("helix", identity, path)
        for index, value in enumerate(domains):
            ref = DomainRef.model_validate(value)
            path = [*authored_path, "domain_ids", index] if explicit_domains else owner_path
            strand = refs.resolve("strand", ref.strand_id, path + ["strand_id"] if explicit_domains else path)
            domain_path = path + ["domain_index"] if explicit_domains else path
            if not 0 <= ref.domain_index < len(strand.domains):
                _fail("domain", f"{strand.id}:{ref.domain_index}", domain_path)
            refs.resolve("helix", strand.domains[ref.domain_index].helix_id, domain_path)
        if owner.overhang_duplex_driver_id is not None:
            # Despite the historical field name, this references an overhang.
            refs.resolve("overhang", owner.overhang_duplex_driver_id, owner_path)
        owner = (refs.resolve("cluster", owner.parent_cluster_id, owner_path)
                 if owner.parent_cluster_id is not None else None)
        selected = False


def _nucleotides(refs, kind, params, *, validate_slots):
    from backend.api.routes_nucleotide_transforms import _target_exists
    from backend.core.models import NucleotideTransform

    batch = kind == "nucleotide-transform-batch"
    bodies = params["transforms"] if batch else [params]
    seen = set()
    for index, body in enumerate(bodies):
        path = ["transforms", index] if batch else []
        # No UUID allocation, source mutation or independent geometry algorithm.
        target = NucleotideTransform.model_validate({**body, "id": "reference-check"})
        if target.kind == "base":
            owner_field = "helix_id"
            refs.resolve("helix", target.helix_id, [*path, owner_field])
            identity = f"{target.helix_id}:{target.bp_index}:{target.direction.value}"
            if target.copy_k:
                identity += f":{target.copy_k}"
            slot_field = "bp_index"
        else:
            owner_field = "crossover_id"
            refs.resolve("crossover", target.crossover_id, [*path, owner_field])
            identity = f"__xb__:{target.crossover_id}:{target.extra_base_k}"
            slot_field = "extra_base_k"
        key = target.target_key()
        if key in seen:
            _fail("nucleotide", identity, [*path, owner_field], ambiguous=True,
                  detail="Movement batch repeats a nucleotide target")
        seen.add(key)
        if validate_slots and not _target_exists(refs.design, target):
            _fail("nucleotide", identity, [*path, slot_field])


def validate_transform_references(kind, design, params, *, validate_slots=True):
    """Refuse absent/ambiguous inputs, retaining native target validity exactly."""
    if kind not in KINDS:
        return
    if kind == "placement-poses":
        from backend.api.part_placement_pose_commands import parse_command, validate_references
        validate_references(design, parse_command(params))
        return
    refs = _References(design)
    if kind == "cluster_op":
        _placement(refs, params)
    elif kind == "nucleotide-transform-delete":
        refs.resolve("nucleotide_transform", params["transform_id"], ["transform_id"])
    else:
        _nucleotides(refs, kind, params, validate_slots=validate_slots)


def build_annotation_with_reference_diagnostics(kind, design, params):
    """Enrich exact native missing-target failure without a second success scan.

    The native builder checks every expanded target before applying any pose.
    Unexplained failures (including implicit CPD partner failures) stay intact;
    this layer never guesses a reference or catches later reconciliation errors.
    """
    from fastapi import HTTPException
    from backend.api.part_annotation_commands import build

    try:
        return build(kind, design, params)
    except HTTPException as error:
        if (kind in {"nucleotide-transform", "nucleotide-transform-batch"}
                and error.status_code == 404 and error.detail == "Missing nucleotide transform target"):
            validate_transform_references(kind, design, params)
        raise
