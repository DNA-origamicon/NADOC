"""Bounded ordinary DNA inventory for the private API transform display.

This is a display admission, not scientific validation or historical command
coverage. Native-residue assets and attached molecular families remain explicit
whole-scope refusals. Saved recovery topology is never a display input.
"""

from dataclasses import dataclass
import json
from math import isfinite
from time import monotonic

from fastapi import HTTPException

from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_capture_graph import GraphBudget
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_verification_capture import CaptureLimit, admit


MAX_HELICES = 16
MAX_STRANDS = 128
MAX_DOMAINS = 256
MAX_RECORDS = 1024
MAX_SELECTORS = 512
MAX_OWNERS = 32
MAX_NATIVE_WORK = 4096
MAX_CONTROL_WORK = 32_768
MAX_AXIS_POINTS = 2048
SECONDS = 2.0
MAX_OUTPUT_NODES = 200_000
MAX_OUTPUT_BYTES = 2_000_000
DISPLAY_FIELDS = frozenset({
    "lattice_frames", "helices", "strands", "deformations", "cluster_transforms",
    "group_organization", "nucleotide_transforms", "cluster_joints", "cluster_join_constraints",
    "overhangs", "overhang_connections", "overhang_bindings", "connection_versions", "duplexes",
    "flexible_segment_marks", "flexible_connections", "extensions", "staple_groups",
    "photoproduct_junctions", "crossovers", "crossover_constraints", "forced_ligations",
})
_NON_GEOMETRY = frozenset({"dimensions", "lattice_type", "metadata", "tm_settings"})


def reject(message, code="unsupported_transform_display"):
    raise CommandContractError(message, code=code)


def limit(value, maximum, label):
    if value > maximum:
        reject(f"Transform display exceeds its {label} allowance", "preview_limit")


def checkpoint():
    deadline = monotonic() + SECONDS
    def check():
        if monotonic() > deadline:
            reject("Transform display exceeded its cooperative time allowance", "preview_limit")
    return check


def bounded(result, *, max_nodes=MAX_OUTPUT_NODES, max_bytes=MAX_OUTPUT_BYTES):
    try:
        GraphBudget(max_nodes=max_nodes, max_bytes=max_bytes, seconds=None, clock=monotonic).charge(result)
        size = 0
        for chunk in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(result):
            size += len(chunk.encode("utf-8"))
            limit(size, max_bytes, "combined response bytes")
    except CaptureLimit as error:
        reject(str(error), "preview_limit")
    except (TypeError, ValueError) as error:
        if isinstance(error, CommandContractError):
            raise
        reject(f"Invalid transform display transport: {error}", "invalid_preview_geometry")
    return result


def identity(value):
    if type(value) is not str or not 1 <= len(value) <= 512:
        reject("Transform display requires bounded identities", "invalid_preview_reference")
    return value


@dataclass(frozen=True, slots=True)
class Inventory:
    indices: dict
    sites: dict
    extensions: dict
    work: int


def inventory(design, check):
    from backend.api.part_group_geometry_budget import require_group_geometry_budget
    from backend.core.part_dna_display_scope import deformation_references, organization_index
    from backend.core.part_scope_references import COLLECTIONS, referenced_resources

    if type(design) is not m.Design or set(m.Design.model_fields) != set(FIELD_ROLES):
        reject("Transform display requires the reviewed standard-part model")
    for name, role in FIELD_ROLES.items():
        if role == "authoring" and name not in DISPLAY_FIELDS | _NON_GEOMETRY and getattr(design, name):
            reject(f"Transform display does not yet cover {name}")
    try:
        admit(design, preserve_entry_types=True)
        def finite(value):
            if type(value) is float and not isfinite(value):
                reject("Transform display requires finite source values", "invalid_preview_geometry")
        GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None, clock=monotonic).charge(
            {field: getattr(design, field) for field in DISPLAY_FIELDS}, validate=finite)
    except CaptureLimit as error:
        reject(str(error), "preview_limit")
    check()
    limit(len(design.helices), MAX_HELICES, "helix count")
    limit(len(design.strands), MAX_STRANDS, "strand count")
    limit(sum(len(s.domains) for s in design.strands), MAX_DOMAINS, "domain count")
    limit(len(design.cluster_transforms), MAX_OWNERS, "placement count")
    # Charge all record occurrences before native allocation, including repeated
    # domain spans, loop descriptors, remote tails, splines and bridge scalars.
    try:
        work = require_group_geometry_budget(design, max_work=MAX_NATIVE_WORK)["estimated_work"]
    except HTTPException as error:
        if not isinstance(error.detail, dict) or error.detail.get("code") not in {"group_geometry_limit", "group_geometry_scope"}:
            raise
        reject(error.detail["message"], "preview_limit" if error.detail["code"].endswith("limit") else "invalid_preview_reference")

    indices, resources = {}, set()
    for field in DISPLAY_FIELDS - {"group_organization"}:
        values = getattr(design, field)
        limit(len(values), MAX_SELECTORS, field)
        index = {}
        for value in values:
            check()
            key = identity(value.id)
            if key in index:
                reject(f"Ambiguous transform display {field} identity", "invalid_preview_reference")
            index[key] = value
            resources.add((COLLECTIONS[field], key))
        indices[field] = index
    if indices["crossovers"].keys() & indices["forced_ligations"].keys():
        reject("Crossover and ligation extra-base identities collide", "invalid_preview_reference")
    try:
        groups, _ = organization_index(design, check, indices)
        indices["group_organization"] = groups
        resources.update(("part_group", key) for key in groups)
        for overhang in design.overhangs:
            for sub in overhang.sub_domains:
                key = ("sub_domain", identity(sub.id))
                if key in resources:
                    reject("Ambiguous overhang subdomain", "invalid_preview_reference")
                resources.add(key)
        available = resources | {("crossover", item.id) for item in design.forced_ligations}
        for field in DISPLAY_FIELDS - {"group_organization", "photoproduct_junctions"}:
            for value in getattr(design, field):
                check()
                # Archived removal inputs are not current display dependencies.
                if isinstance(value, (m.Duplex, m.OverhangBinding)):
                    value = value.model_copy(update={"prior_driven_topology": None})
                refs = deformation_references(value) if field == "deformations" else referenced_resources(value)
                # Native extra-base transforms share the crossover/ligation ID namespace.
                if refs - available:
                    reject(f"Transform display has unresolved {field} references", "invalid_preview_reference")
    except CommandContractError as error:
        if error.code.startswith("comparison_") or error.code.startswith("invalid_comparison"):
            reject(str(error), "preview_limit" if error.code == "comparison_limit" else "invalid_preview_reference")
        raise
    except NotImplementedError as error:
        reject(str(error))

    def domain_ref(sid, ordinal):
        strand = indices["strands"].get(sid)
        if strand is None or type(ordinal) is not int or not 0 <= ordinal < len(strand.domains):
            reject("Transform display has an unresolved domain", "invalid_preview_reference")
        return strand.domains[ordinal]

    for owner in design.cluster_transforms:
        limit(len(owner.helix_ids) + len(owner.domain_ids), MAX_SELECTORS, "placement selectors")
        for ref in owner.domain_ids:
            domain_ref(ref.strand_id, ref.domain_index)
        visited, current = set(), owner
        while current is not None:
            if current.id in visited:
                reject("Transform display has cyclic parent placements", "invalid_preview_reference")
            visited.add(current.id)
            current = indices["cluster_transforms"].get(current.parent_cluster_id)
    for anchor in [*design.flexible_segment_marks,
                   *(a for connection in design.flexible_connections for a in
                     (connection.anchor_a, connection.anchor_b, *connection.segment_bead_keys))]:
        domain = domain_ref(anchor.strand_id, anchor.domain_index)
        if (anchor.direction != domain.direction or type(anchor.bp_index) is not int
                or not min(domain.start_bp, domain.end_bp) <= anchor.bp_index <= max(domain.start_bp, domain.end_bp)):
            reject("Transform display has an unresolved flexible anchor", "invalid_preview_reference")

    deltas, sites, occupied = {}, {}, set()
    for helix in design.helices:
        if helix.native_source or helix.native_residues or helix.id.startswith(("__np__", "__strep_dna__")):
            reject("Native-residue and attachment helices require their own display contract")
        if helix.length_bp <= 0:
            reject("Transform display requires positive helix spans", "invalid_preview_reference")
        for mark in helix.loop_skips:
            if mark.delta not in {-1, 1} or not helix.bp_start <= mark.bp_index < helix.bp_start + helix.length_bp:
                reject("Transform display requires ordinary in-span loop marks", "invalid_preview_reference")
            key = helix.id, mark.bp_index
            deltas[key] = deltas.get(key, 0) + mark.delta
    for strand in design.strands:
        if not strand.domains:
            reject("Transform display requires occupied strands", "invalid_preview_reference")
        for ordinal, domain in enumerate(strand.domains):
            if type(domain.direction) is not m.Direction:
                reject("Transform display requires typed domain directions", "invalid_preview_reference")
            for bp in range(min(domain.start_bp, domain.end_bp), max(domain.start_bp, domain.end_bp) + 1):
                key = domain.helix_id, bp, domain.direction.value
                if key in occupied:
                    reject("Transform display has overlapping directional occupancy", "invalid_preview_reference")
                occupied.add(key)
                if domain.helix_id.startswith("__lnk__"):
                    connection = indices["overhang_connections"].get(domain.helix_id[len("__lnk__"):])
                    if connection is None:
                        reject("Linker domain has no exact connection owner", "invalid_preview_reference")
                    if connection.linker_type == "ss":
                        continue  # Explicit ss-linker companion topology, not a native Full record.
                for copy_k in range(max(0, 1 + deltas.get((domain.helix_id, bp), 0))):
                    sites[(*key, copy_k)] = strand.id, ordinal, domain.overhang_id, strand.is_reference
                    limit(len(sites), MAX_RECORDS, "emitted sites")
    extensions = {}
    for extension in design.extensions:
        strand = indices["strands"][extension.strand_id]
        domain = strand.domains[0 if extension.end == "five_prime" else -1]
        count = len(extension.sequence or "") + bool(extension.modification)
        for index in range(count):
            extensions[(f"__ext_{extension.id}", index, domain.direction.value, 0)] = extension
        limit(len(sites) + len(extensions), MAX_RECORDS, "emitted sites")
    # Existing native target authority, including extra-base copy and CPD pairs.
    from backend.api.routes_nucleotide_transforms import _target_exists
    for transform in design.nucleotide_transforms:
        if not _target_exists(design, transform):
            reject("Transform display has an unresolved nucleotide pose", "invalid_preview_reference")
    from backend.core.base_keys import parse_base_key
    junctions = {**indices["crossovers"], **indices["forced_ligations"]}
    for lesion in design.photoproduct_junctions:
        for key in (lesion.base_key_1, lesion.base_key_2):
            parsed = parse_base_key(key) if type(key) is str else None
            if parsed is None:
                reject("Transform display needs resolved CPD endpoints", "invalid_preview_reference")
            if parsed.family == "xover":
                junction = junctions.get(parsed.crossover_id)
                valid = junction is not None and parsed.k < len(junction.extra_bases or "")
            else:
                valid = (parsed.helix_id, parsed.bp_index, parsed.direction, parsed.copy) in sites
            if not valid:
                reject("Transform display has an unresolved CPD endpoint", "invalid_preview_reference")
    check()
    return Inventory(indices, sites, extensions, work)
