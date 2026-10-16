"""Metadata-only admission before a group pivot derives native Full geometry.

The host already owns a 30k-node/2 MB capture. This additional provisional
50k residue-work allowance closes scalar expansion (spans, loops and paths).
It is neither a heap/latency guarantee nor a scientific validity assessment.
No native placement, model serialization, recovery or solver runs here.
"""

from bisect import bisect_left, bisect_right
from math import ceil, dist, isfinite

from fastapi import HTTPException


MAX_NATIVE_WORK = 50_000
MAX_BP_ADDRESS = 2**53 - 1


def _scope(message):
    raise HTTPException(409, detail={"code": "group_geometry_scope", "message": message})


def _integer(value, *, nonnegative=False):
    if type(value) is not int or abs(value) > MAX_BP_ADDRESS or (nonnegative and value < 0):
        _scope("Pivot geometry needs finite, bounded integer residue addresses and counts.")
    return value


def _sequence_length(value):
    if value is not None and type(value) is not str:
        _scope("Pivot geometry sequence metadata must be text.")
    return len(value or "")


def _path_samples(params, limit):
    # Indexed sweeps interpolate their existing station arrays; the ordinary
    # path samples below are not constructed on this branch of sweep_frames.
    if params.bp_positions_nm is not None:
        if params.bp_frames is None or len(params.bp_frames) != len(params.bp_positions_nm):
            _scope("Indexed sweep stations are incomplete.")
        return len(params.bp_positions_nm)
    points = params.points_nm
    if not 2 <= len(points) <= 256:
        _scope("Pivot geometry needs a bounded native sweep path.")
    if any(len(point) != 3 or any(type(value) not in (int, float) or not isfinite(value)
                                for value in point) for point in points):
        _scope("Sweep coordinates must be finite XYZ values.")
    # Exactly the allocation rule in native sweep_path.path_table, not spline
    # evaluation or a new physical resolution. Guard overflow before ceil.
    samples = 1
    for first, second in zip(points, points[1:]):
        distance = dist(first, second)
        if not isfinite(distance) or distance > limit * .05:
            return limit + 1
        samples += max(64, ceil(distance / .05))
        if samples > limit:
            return samples
    return samples


def require_group_geometry_budget(design, *, max_work=None):
    """Refuse scalar-driven expansion of an independently captured source.

    Counts are conservative: virtual helices and declared bridges may both be
    charged, skips never cancel positive work, and deformation arms use the
    whole source span. Unsupported/malformed scalar metadata fails closed;
    ordinary native helpers retain all placement and reference semantics.
    """
    limit = MAX_NATIVE_WORK if max_work is None else max_work
    if type(limit) is not int or limit < 1:
        raise ValueError("Geometry admission needs a positive integer work allowance")

    def checked(amount):
        if amount > limit:
            raise HTTPException(409, detail={"code": "group_geometry_limit",
                "message": "Pivot geometry exceeds its provisional native residue-work allowance.",
                "maximum_work": limit, "estimated_work": amount})
        return amount

    spans, loops, native_extents = {}, {}, {}
    for helix in design.helices:
        if helix.id in spans:
            _scope("Pivot geometry has ambiguous helix identities.")
        start = _integer(helix.bp_start)
        length = _integer(helix.length_bp, nonnegative=True)
        checked(2 * length)
        spans[helix.id] = [start, start + length - 1]
        marks = []
        for mark in helix.loop_skips:
            marks.append((_integer(mark.bp_index), max(0, _integer(mark.delta))))
        positions, prefix = [], [0]
        for position, positive in sorted(marks):
            positions.append(position)
            prefix.append(checked(prefix[-1] + positive))
        loops[helix.id] = positions, prefix
        if helix.native_residues:
            native_bps = [_integer(site.bp_index) for site in helix.native_residues]
            native_extents[helix.id] = (min(start, min(native_bps)),
                                       max(start + length - 1, max(native_bps)))

    emitted = 0
    for strand in design.strands:
        for domain in strand.domains:
            if domain.helix_id not in spans:
                _scope("A pivot geometry domain has no unambiguous helix owner.")
            lo, hi = sorted((_integer(domain.start_bp), _integer(domain.end_bp)))
            extent = spans[domain.helix_id]
            extent[0], extent[1] = min(extent[0], lo), max(extent[1], hi)
            positions, prefix = loops[domain.helix_id]
            # Repeated domains cost again; repeated +1 descriptors sum in the
            # native array path and must not be deduplicated by position.
            emitted = checked(emitted + hi - lo + 1
                + prefix[bisect_right(positions, hi)] - prefix[bisect_left(positions, lo)])
    span_work = checked(sum(2 * (max(0, hi - lo + 1) + loops[key][1][-1])
                            for key, (lo, hi) in spans.items()))
    # Aptamer/native-residue tails can prepare each end independently before
    # producing the final nominal array. Charge their full sparse core extent.
    native_work = checked(sum(6 * max(0, hi - lo + 1) for lo, hi in native_extents.values()))

    additions = 0
    for extension in design.extensions:
        additions = checked(additions + _sequence_length(extension.sequence)
                            + int(extension.modification is not None))
    for junction in (*design.crossovers, *design.forced_ligations):
        additions = checked(additions + _sequence_length(junction.extra_bases))
    if design.overhang_connections:
        from backend.core.lattice import _length_value_to_bp
        for connection in design.overhang_connections:
            value = connection.length_value
            if (type(value) not in (int, float) or not isfinite(value) or value < 0
                    or connection.length_unit not in {"bp", "nm"}
                    or connection.linker_type not in {"ss", "ds"}):
                _scope("Pivot geometry needs finite native linker length metadata.")
            # Both admitted native units produce at least this many residues
            # (up to rounding). Refuse before a huge finite nm value overflows
            # the native conversion's intermediate division to infinity.
            if value > limit:
                checked(limit + 1)
            # Reuse the native conversion; never invent a separate nm→bp rule.
            count = max(_length_value_to_bp(value, connection.length_unit),
                        _sequence_length(connection.bridge_sequence))
            additions = checked(additions + count * (2 if connection.linker_type == "ds" else 1))

    frame_work, path_samples, partitions = 0, 0, 1
    if design.deformations:
        # Unrelated short arms can still be far apart in global bp coordinates.
        # _precompute_arm_frames allocates from arm_min_bp through the last bp.
        if spans:
            width = max(hi for _, hi in spans.values()) - min(lo for lo, _ in spans.values()) + 1
            frame_work = checked(max(0, width) * len(spans))
        ranges = 0
        for operation in design.deformations:
            if operation.type not in {"bend", "twist", "sweep"}:
                _scope("This deformation has no reviewed pivot geometry work accounting.")
            if operation.target_ranges is not None:
                ranges += len(operation.target_ranges)
            if operation.type == "sweep":
                path_samples = checked(path_samples + _path_samples(operation.params, limit))
        # Each interval adds at most two new membership boundaries. The native
        # scoped path can evaluate a full helix for each resulting partition.
        partitions += 2 * ranges
    estimate = checked(max(emitted, (span_work + native_work) * partitions,
                           frame_work * partitions) + additions + path_samples)
    return {"estimated_work": estimate, "maximum_work": limit, "domain_work": emitted,
            "helix_work": span_work, "native_tail_work": native_work,
            "frame_work": frame_work, "scope_partitions": partitions,
            "additional_residues": additions, "path_samples": path_samples}
