"""Native sparse lattice construction and explicitly partitioned scaffold routing.

These commands retain the established branch builders, with authored intervals
and resolved input references instead of a selected generator result. Path
geometry and attachments are deliberately separate feature contracts.
"""

from collections import defaultdict
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.core.models import Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import ProofBudgetExceeded

KINDS = frozenset({"branch-seed", "auto-scaffold-sections"})
_Key = Annotated[str, Field(min_length=1, max_length=128, strict=True)]
_Bp = Annotated[StrictInt, Field(ge=0, le=2015)]
_CellIndex = Annotated[StrictInt, Field(ge=-4096, le=4096)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrackInterval(_Input):
    key: _Key
    lo_bp: _Bp
    hi_bp: _Bp

    @model_validator(mode="after")
    def ordered(self):
        if self.lo_bp > self.hi_bp:
            raise ValueError("Track intervals must have lo_bp <= hi_bp")
        return self


class BranchTrack(_Input):
    key: _Key
    cell: tuple[_CellIndex, _CellIndex]
    intervals: list[TrackInterval] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def disjoint(self):
        if len({interval.key for interval in self.intervals}) != len(self.intervals):
            raise ValueError("Track interval keys must be unique")
        if any(a.hi_bp >= b.lo_bp for a, b in zip(self.intervals, self.intervals[1:])):
            raise ValueError("Track intervals must be ordered and nonoverlapping")
        return self


class BranchSeedRequest(_Input):
    proof_version: Literal[1] = Field(default=1, alias="_proof_version")
    history_seed: UUID
    nominal_length_bp: Annotated[StrictInt, Field(ge=1, le=2016)]
    tracks: list[BranchTrack] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def unique_tracks(self):
        if len({track.key for track in self.tracks}) != len(self.tracks):
            raise ValueError("Track keys must be unique")
        if len({track.cell for track in self.tracks}) != len(self.tracks):
            raise ValueError("A lattice cell must occur in exactly one track")
        if any(interval.hi_bp >= self.nominal_length_bp
               for track in self.tracks for interval in track.intervals):
            raise ValueError("Track interval exceeds its authored helix extent")
        return self


class SectionTrack(_Input):
    helix_id: Annotated[str, Field(min_length=1, max_length=256, strict=True)]
    interval: tuple[_Bp, _Bp]

    @model_validator(mode="after")
    def ordered(self):
        if self.interval[0] > self.interval[1]:
            raise ValueError("Routing intervals must be ordered")
        return self


class SectionWindow(_Input):
    key: _Key
    tracks: list[SectionTrack] = Field(min_length=1, max_length=128)
    splice_interval: tuple[_Bp, _Bp] | None = None
    parent_helix_ids: list[Annotated[str, Field(min_length=1, max_length=256, strict=True)]] | None = Field(
        default=None, min_length=1, max_length=128
    )


class SectionRouteRequest(_Input):
    proof_version: Literal[1] = Field(default=1, alias="_proof_version")
    history_seed: UUID
    trunk: list[SectionTrack] = Field(min_length=1, max_length=128)
    windows: list[SectionWindow] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def partitions(self):
        if len({window.key for window in self.windows}) != len(self.windows):
            raise ValueError("Routing window keys must be unique")
        intervals = defaultdict(list)
        for records in [self.trunk, *(window.tracks for window in self.windows)]:
            if len({track.helix_id for track in records}) != len(records):
                raise ValueError("A section may reference a helix only once")
            for track in records:
                intervals[track.helix_id].append(track.interval)
        for values in intervals.values():
            ordered = sorted(values)
            if any(a[1] >= b[0] for a, b in zip(ordered, ordered[1:])):
                raise ValueError("Routing partitions must not overlap")
        for field in ("splice_interval", "parent_helix_ids"):
            present = [getattr(window, field) is not None for window in self.windows]
            if any(present) and not all(present):
                raise ValueError(f"Specify {field} for every window or none")
        for window in self.windows:
            if window.splice_interval is not None:
                lo, hi = window.splice_interval
                if lo > hi or not any(a <= hi and lo <= b for a, b in
                                      (track.interval for track in window.tracks)):
                    raise ValueError("Splice interval must intersect its branch window")
            if window.parent_helix_ids is not None:
                parents = window.parent_helix_ids
                if len(set(parents)) != len(parents):
                    raise ValueError("Splice parents must be unique")
        return self


def _identity(namespace, *parts):
    import json

    return str(uuid5(namespace, json.dumps(parts, separators=(",", ":"))))


def _budget(track_count, length, interval_count):
    if track_count * length > 50_000 or interval_count > 512:
        raise ProofBudgetExceeded("Branch construction exceeds the proof work budget")


def seed(design, params):
    """Append exactly the native sparse seed, preserving all existing state."""
    from backend.core.branched_generator import branch_seed
    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.feature_identity import identity_factory
    from backend.core.part_scope_references import remap_design

    body = BranchSeedRequest.model_validate(params)
    _budget(len(body.tracks), body.nominal_length_bp,
            sum(len(track.intervals) for track in body.tracks))
    summary = {
        "cells": [list(track.cell) for track in body.tracks],
        "nominal_length_bp": body.nominal_length_bp,
        "branch_tracks": [
            {"cell": list(track.cell), "intervals": [
                [interval.lo_bp, interval.hi_bp] for interval in track.intervals
            ]} for track in body.tracks
        ],
    }
    native = branch_seed(design.lattice_type, summary)
    mapping = {}
    for track in body.tracks:
        row, col = track.cell
        mapping["helix", f"h_XY_{row}_{col}"] = _identity(body.history_seed, "helix", track.key)
        for index, interval in enumerate(track.intervals):
            for role in ("scaf", "stpl"):
                mapping["strand", f"{role}_XY_{row}_{col}_b{index}"] = _identity(
                    body.history_seed, "strand", track.key, role, interval.key
                )
    native = remap_design(native, mapping)
    if ({h.id for h in native.helices} & {h.id for h in design.helices}
            or {s.id for s in native.strands} & {s.id for s in design.strands}):
        raise ValueError("Branch construction identities already exist")
    updated = design.copy_with(
        helices=[*design.helices, *native.helices],
        strands=[*design.strands, *native.strands],
    )
    # Default placement is authored metadata, not response-time migration.
    # Allocate it inside the input command so response formatting cannot add a
    # random cluster after publication/recovery encoding and invalidate proof.
    # Its namespace is stable even when this seed's selected tracks are edited.
    factory = identity_factory(body.history_seed)
    return with_default_cluster(updated, identity_factory=lambda kind, _members: factory(kind, []))


def _records(body):
    for i, track in enumerate(body.trunk):
        yield track, ["trunk", i, "helix_id"]
    for i, window in enumerate(body.windows):
        for j, track in enumerate(window.tracks):
            yield track, ["windows", i, "tracks", j, "helix_id"]


def _issue(detail, identities, paths, *, missing=False):
    raise ReferenceResolutionError(
        detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": "helix", "identity": identity, "parameter_path": paths[identity]}
                    for identity in sorted(identities)],
    )


def _coverage(intervals):
    merged = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


def _selected(design, body):
    records = list(_records(body))
    paths = {track.helix_id: path for track, path in records}
    ids = set(paths)
    existing_ids = {helix.id for helix in design.helices}
    if len(existing_ids) != len(design.helices):
        _issue("Branch routing input contains duplicate helix identities", ids, paths)
    for i, window in enumerate(body.windows):
        for j, identity in enumerate(window.parent_helix_ids or []):
            paths.setdefault(identity, ["windows", i, "parent_helix_ids", j])
    missing = set(paths) - existing_ids
    if missing:
        _issue("Branch routing target no longer exists", missing, paths, missing=True)
    prior = {track.helix_id for track in body.trunk}
    for window in body.windows:
        invalid = set(window.parent_helix_ids or []) - prior
        if invalid:
            _issue("Splice parent does not belong to an earlier section", invalid, paths)
        prior.update(track.helix_id for track in window.tracks)
    helices = [helix for helix in design.helices if helix.id in ids]
    if any(helix.grid_pos is None or helix.lattice_frame_id is not None for helix in helices):
        _issue("Branch routing requires unframed lattice tracks", ids, paths)
    if len({helix.grid_pos for helix in helices}) != len(helices):
        _issue("Branch routing targets have ambiguous lattice cells", ids, paths)
    _budget(len(helices), max(helix.length_bp for helix in helices), len(records))
    strands = []
    for strand in design.strands:
        members = {domain.helix_id for domain in strand.domains}
        if not members & ids:
            continue
        if members - ids or strand.is_reference:
            _issue("Branch routing cannot split an existing or reference strand", members & ids, paths)
        strands.append(strand)
    actual, wanted = defaultdict(list), defaultdict(list)
    for strand in strands:
        if strand.is_scaffold:
            for domain in strand.domains:
                actual[domain.helix_id].append(tuple(sorted((domain.start_bp, domain.end_bp))))
    for track, _ in records:
        wanted[track.helix_id].append(track.interval)
    bad = {identity for identity in ids if _coverage(actual[identity]) != _coverage(wanted[identity])}
    if bad:
        _issue("Branch partition no longer matches occupied scaffold intervals", bad, paths)

    def closed(items, members):
        chosen = []
        for item in items:
            targets = set(members(item))
            if targets & ids:
                if targets - ids:
                    _issue("Branch routing selection crosses an existing dependency", targets & ids, paths)
                chosen.append(item)
        return chosen

    selected = Design(
        lattice_type=design.lattice_type, helices=helices, strands=strands,
        crossovers=closed(design.crossovers, lambda c: (c.half_a.helix_id, c.half_b.helix_id)),
        forced_ligations=closed(design.forced_ligations,
                               lambda f: (f.three_prime_helix_id, f.five_prime_helix_id)),
        crossover_constraints=closed(design.crossover_constraints,
                                     lambda c: [*c.helix_ids_a, *c.helix_ids_b]),
        deformations=closed(design.deformations, lambda d: d.affected_helix_ids),
    )
    _check_incoming_references(design, selected, paths)
    return selected.model_copy(deep=True), actual


def _check_incoming_references(design, selected, paths):
    """Do not discard state that refers to topology being replaced by routing."""
    from backend.core.part_scope_references import COLLECTIONS, referenced_resources

    resources = {("helix", h.id) for h in selected.helices}
    resources |= {("strand", s.id) for s in selected.strands}
    resources |= {("crossover", c.id) for c in selected.crossovers}
    selected_deformations = {operation.id for operation in selected.deformations}
    handled = {"helices", "strands", "crossovers", "forced_ligations", "crossover_constraints"}
    # Check asset ownership without walking potentially large atom records.
    assets = {"protein_assets", "protein_attachments", "nanoparticles",
              "nanoparticle_conjugations", "nanoparticle_connection_versions"}
    for field in COLLECTIONS.keys() - handled - assets:
        for item in getattr(design, field):
            if field == "cluster_transforms":
                # Whole-helix grouping remains valid: helix identities survive.
                refs = {("strand", ref.strand_id) for ref in item.domain_ids}
            else:
                refs = referenced_resources(item)
                if field == "deformations" and item.id in selected_deformations:
                    # Native section routing retains complete helix paths. It
                    # cannot carry a strand/cluster selection through rerouting
                    # or resolve a dependent path outside this isolated scope.
                    if (item.targets or item.target_ranges or item.cluster_ids
                            or any(kind != "helix" for kind, _ in refs)):
                        _issue("Branch routing requires independent whole-helix deformations", paths.keys(), paths)
                    continue
            if refs & resources:
                _issue(f"Branch routing selection has unsupported {field} dependencies", paths.keys(), paths)
    for particle in design.nanoparticles:
        if any(("helix", item.helix_id) in resources or ("strand", item.strand_id) in resources
               for item in particle.biotin_dna):
            _issue("Branch routing selection is owned by a nanoparticle", paths.keys(), paths)
    for conjugation in design.nanoparticle_conjugations:
        if any(("helix", item.helix_id) in resources or ("strand", item.strand_id) in resources
               for item in conjugation.surface_strands):
            _issue("Branch routing selection is owned by a conjugation", paths.keys(), paths)
    if any(("strand", attachment.binder_strand_id) in resources for attachment in design.protein_attachments):
        _issue("Branch routing selection is attached to a protein", paths.keys(), paths)
    if any(("strand", version.strand_id) in resources for version in design.nanoparticle_connection_versions):
        _issue("Branch routing selection has a nanoparticle connection version", paths.keys(), paths)


def route(design, params):
    """Regenerate selected sections once and return their native routing report."""
    from backend.api.generated_native_scope import merge_changes
    from backend.core.branched_generator import route_branches
    from backend.core.part_scope_references import remap_design
    from backend.core.routing_identity import identity_scope

    body = SectionRouteRequest.model_validate(params)
    selected, occupied = _selected(design, body)
    cells = {helix.id: helix.grid_pos for helix in selected.helices}
    # Native section selection sorts helix IDs. Keep its established cell names
    # while running so a UUID's lexical order cannot alter the selected route.
    canonical = {("helix", identity): f"h_XY_{cell[0]}_{cell[1]}" for identity, cell in cells.items()}
    inverse = {(kind, value): identity for (kind, identity), value in canonical.items()}
    local = remap_design(selected, canonical)

    def section(records):
        return [{"cell": list(cells[track.helix_id]), "interval": list(track.interval)}
                for track in records]

    summary = {
        "branch_trunk": section(body.trunk),
        "branch_windows": [section(window.tracks) for window in body.windows],
        "branch_tracks": [{"cell": list(cells[identity]), "intervals": [list(pair) for pair in _coverage(intervals)]}
                          for identity, intervals in occupied.items()],
    }
    if body.windows[0].splice_interval is not None:
        summary["branch_junction_intervals"] = [list(window.splice_interval) for window in body.windows]
    if body.windows[0].parent_helix_ids is not None:
        # The existing router uses these records only to resolve splice parents;
        # no connectivity geometry, source model or sampled frames are accepted.
        summary.update(
            branch_geometry="connectivity",
            connectivity_faces=[[list(cells[identity]) for identity in window.parent_helix_ids]
                                for window in body.windows],
            connectivity_junctions=[{"parent": i, "child": i} for i in range(len(body.windows))],
        )
    with identity_scope(body.history_seed):
        updated, report = route_branches(local, summary)
    inverse["strand", "scaffold_section_route"] = _identity(body.history_seed, "section-scaffold")
    updated = remap_design(updated, inverse)
    return merge_changes(design, selected, updated), report


def _planar(summary):
    if summary.get("branch_geometry", "lattice") != "lattice":
        raise ValueError("Only planar lattice branch plans have this native contract")


def compile_seed_params(summary, history_seed):
    """Retain bounded construction inputs from a selected planar branch plan."""
    _planar(summary)
    return compile_sparse_seed_params(summary, history_seed)


def compile_sparse_seed_params(summary, history_seed):
    """Compile only occupied lattice intervals; path geometry is a later step."""
    by_cell = {tuple(track["cell"]): track["intervals"] for track in summary["branch_tracks"]}
    params = {
        "history_seed": str(history_seed), "_proof_version": 1,
        "nominal_length_bp": summary["nominal_length_bp"],
        "tracks": [{"key": f"cell:{cell[0]}:{cell[1]}", "cell": list(cell),
                    "intervals": [{"key": f"span:{i}", "lo_bp": lo, "hi_bp": hi}
                                  for i, (lo, hi) in enumerate(by_cell[tuple(cell)])]}
                   for cell in summary["cells"]],
    }
    return BranchSeedRequest.model_validate(params).model_dump(mode="json", by_alias=True)


def compile_route_params(seed_design, summary, history_seed):
    """Resolve a selected planar partition to its current native helix IDs."""
    _planar(summary)
    return compile_partition_params(seed_design, summary, history_seed)


def compile_partition_params(seed_design, summary, history_seed):
    """Resolve routing sections and splice windows, independently of path shape."""
    ids = {}
    for helix in seed_design.helices:
        if helix.grid_pos in ids:
            raise ValueError("Ambiguous lattice cell while compiling branch routing")
        ids[helix.grid_pos] = helix.id

    def section(records):
        return [{"helix_id": ids[tuple(record["cell"])], "interval": record["interval"]}
                for record in records]

    params = {
        "history_seed": str(history_seed), "_proof_version": 1,
        "trunk": section(summary["branch_trunk"]),
        "windows": [{"key": f"window:{i}", "tracks": section(window)}
                    for i, window in enumerate(summary["branch_windows"])],
    }
    if summary.get("branch_junction_intervals") is not None:
        intervals = summary["branch_junction_intervals"]
        if len(intervals) != len(params["windows"]):
            raise ValueError("Each branch window needs one splice interval")
        for window, interval in zip(params["windows"], intervals):
            window["splice_interval"] = interval
    return SectionRouteRequest.model_validate(params).model_dump(mode="json", by_alias=True)


def build(kind, design, params):
    if kind == "branch-seed":
        return seed(design, params)
    if kind == "auto-scaffold-sections":
        return route(design, params)[0]
    raise NotImplementedError(kind)
