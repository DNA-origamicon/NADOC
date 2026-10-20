"""Native Full display component for independently owned comparison inputs.

All placement is delegated to the existing geometry/axis pipeline. This module
checks complete output inventory and shapes a bounded, non-authoritative DTO;
it neither constructs topology nor provides a physical-validity certificate.
"""

from backend.core.part_comparison_projection import _finite, _reject
from backend.core.part_dna_comparison_contract import (
    COMPONENT_VERSION, MAX_AXIS_POINTS, MAX_SELECTORS, MAX_SLOTS, _limit, inventory,
)
from backend.core.part_dna_comparison_codec import RECORD_COLUMNS, pack_records, pack_records_compact


RECORD_FIELDS = frozenset(RECORD_COLUMNS)
SITE_FIELDS = frozenset({"axis_point", "radial_hat", "azimuth_rad", "groove_offset_rad", "phase_roll_rad"})
AXIS_FIELDS = frozenset({"helix_id", "start", "end", "samples", "segments", "ovhg_axes"})
SEGMENT_FIELDS = frozenset({"strand_id", "domain_index", "ovhg_id", "bp_lo", "bp_hi", "domain_ids", "start", "end"})
TOPOLOGY_FIELDS = {
    "helices": {"id", "length_bp", "bp_start", "axis_start", "axis_end", "loop_skips", "direction", "grid_pos", "lattice_frame_id"},
    "strands": {"id", "domains", "strand_type", "sequence", "color", "is_reference"},
    "overhangs": {"id", "helix_id", "strand_id", "sequence", "sub_domains"},
    "cluster_transforms": {"id", "name", "is_default", "helix_ids", "domain_ids", "color", "auto_created"},
    "crossovers": {"id", "half_a", "half_b", "extra_bases"},
    "forced_ligations": {"id", "three_prime_helix_id", "three_prime_bp", "three_prime_direction",
        "five_prime_helix_id", "five_prime_bp", "five_prime_direction", "extra_bases", "is_periodic_seam"},
}
SUBDOMAIN_FIELDS = {"id", "start_bp_offset", "length_bp", "sequence_override", "color"}


def _finite_bulk(values):
    """``_finite`` over many values at once: exact int/float types, all finite."""
    import numpy as np

    if not set(map(type, values)) <= {int, float}:
        _reject("Comparison placement contains nonfinite coordinates", "invalid_comparison_geometry")
    if values and not np.isfinite(np.fromiter(values, dtype=np.float64, count=len(values))).all():
        _reject("Comparison placement contains nonfinite coordinates", "invalid_comparison_geometry")


def _point(value, length=3):
    if not isinstance(value, list) or len(value) != length:
        _reject("DNA comparison has malformed native coordinates", "invalid_comparison_geometry")
    _finite(value)
    return value


def _records(records, expected):
    from backend.core.native_full_placement import SOURCE
    from backend.core.native_slab_placement import authoritative_slab_poses

    _limit(len(records), MAX_SLOTS, "emitted nucleotide count")
    seen = set()
    # Coordinates are gathered and checked in one pass (same shape, type and
    # finiteness rules as ``_point``/``_finite``) instead of per value.
    values = []
    gather = values.extend

    def shaped(value, length=3):
        if type(value) is not list or len(value) != length:
            _reject("DNA comparison has malformed native coordinates", "invalid_comparison_geometry")
        gather(value)

    for record in records:
        if set(record) != RECORD_FIELDS or record["placement_source"] != SOURCE:
            _reject("DNA comparison received an unreviewed native record", "unsupported_comparison_scope")
        key = record["helix_id"], record["bp_index"], record["direction"], record["copy_k"]
        owner = record["strand_id"], record["domain_index"], record["overhang_id"], record["is_reference"]
        if key in seen or expected.sites.get(key) != owner or record["is_flexible_segment"] is not False:
            _reject("DNA comparison nucleotide inventory is incomplete or ambiguous", "invalid_comparison_geometry")
        seen.add(key)
        shaped(record["backbone_position"]), shaped(record["base_position"]), shaped(record["base_normal"])
        shaped(record["axis_tangent"]), shaped(record["slab_position"]), shaped(record["slab_quaternion"], 4)
        site = record["helical_site"]
        if set(site) != SITE_FIELDS:
            _reject("DNA comparison has unreviewed native site fields", "unsupported_comparison_scope")
        shaped(site["axis_point"]), shaped(site["radial_hat"])
        gather((site["azimuth_rad"], site["groove_offset_rad"], site["phase_roll_rad"]))
    _finite_bulk(values)
    if seen != set(expected.sites):
        _reject("DNA comparison omitted occupied nucleotides", "invalid_comparison_geometry")
    # Reuse the native authority to validate bead/base/slab registration. Do not
    # replace coordinates or derive a second representation on validation failure.
    authoritative_slab_poses(records)
    return values


def _axes(axes, expected, *, scoped_segments=False):
    seen, overhangs, coverage = set(), set(), {}
    points, segments = 0, 0
    strands = expected.indices["strands"]
    for axis in axes:
        if not {"helix_id", "start", "end", "samples", "segments"} <= set(axis) <= AXIS_FIELDS:
            _reject("DNA comparison has unreviewed native axes", "unsupported_comparison_scope")
        hid = axis["helix_id"]
        if hid not in expected.indices["helices"] or hid in seen:
            _reject("DNA comparison has ambiguous helix axes", "invalid_comparison_geometry")
        seen.add(hid)
        points += len(axis["samples"]) + 2
        segments += len(axis["segments"])
        _limit(segments, MAX_SELECTORS, "axis segments")
        _point(axis["start"]), _point(axis["end"])
        for point in axis["samples"]:
            _point(point)
        for segment in axis["segments"]:
            allowed = SEGMENT_FIELDS | {"samples"} if scoped_segments else SEGMENT_FIELDS
            if not {"strand_id", "domain_index", "ovhg_id", "bp_lo", "bp_hi", "start", "end"} <= set(segment) <= allowed:
                _reject("DNA comparison has unreviewed axis segments", "unsupported_comparison_scope")
            _point(segment["start"]), _point(segment["end"])
            points += 2
            if "samples" in segment:
                samples = segment["samples"]
                if type(samples) is not list:
                    _reject("DNA preview has malformed scoped axis samples", "invalid_comparison_geometry")
                # Count every emitted occurrence, including shared native lists.
                # No sampling or truncation can hide a selected domain's path.
                points += len(samples)
                _limit(points, MAX_AXIS_POINTS, "axis points")
                for point in samples:
                    _point(point)
            refs = segment.get("domain_ids") or ([{"strand_id": segment["strand_id"], "domain_index": segment["domain_index"]}]
                                                if segment["strand_id"] is not None else [])
            for ref in refs:
                sid, index = ref["strand_id"], ref["domain_index"]
                if sid not in strands or type(index) is not int or not 0 <= index < len(strands[sid].domains):
                    _reject("DNA axis segment has a missing domain", "invalid_comparison_geometry")
                domain = strands[sid].domains[index]
                lo, hi = segment["bp_lo"], segment["bp_hi"]
                if (domain.helix_id != hid or type(lo) is not int or type(hi) is not int or lo > hi
                        or lo < min(domain.start_bp, domain.end_bp) or hi > max(domain.start_bp, domain.end_bp)):
                    _reject("DNA axis segment disagrees with its domain", "invalid_comparison_geometry")
                coverage.setdefault((sid, index), set()).update(range(lo, hi + 1))
        for identity, value in axis.get("ovhg_axes", {}).items():
            overhang = expected.indices["overhangs"].get(identity)
            if overhang is None or identity in overhangs or overhang.helix_id != hid:
                _reject("DNA comparison has an unresolved overhang axis", "invalid_comparison_geometry")
            if set(value) != {"bp_min", "bp_max", "start", "end"}:
                _reject("DNA comparison has unreviewed overhang axes", "unsupported_comparison_scope")
            overhangs.add(identity)
            _point(value["start"]), _point(value["end"])
            points += 2
        _limit(points, MAX_AXIS_POINTS, "axis points")
    if seen != set(expected.indices["helices"]) or overhangs != set(expected.indices["overhangs"]):
        _reject("DNA comparison omitted authored axes", "invalid_comparison_geometry")
    for strand in strands.values():
        for index, domain in enumerate(strand.domains):
            if coverage.get((strand.id, index)) != set(range(min(domain.start_bp, domain.end_bp), max(domain.start_bp, domain.end_bp) + 1)):
                _reject("DNA comparison omitted occupied axis segments", "invalid_comparison_geometry")


def _topology(design):
    value = {field: [item.model_dump(mode="json", include=fields) for item in getattr(design, field)]
             for field, fields in TOPOLOGY_FIELDS.items()}
    for entry, overhang in zip(value["overhangs"], design.overhangs, strict=True):
        entry["sub_domains"] = [sub.model_dump(mode="json", include=SUBDOMAIN_FIELDS) for sub in overhang.sub_domains]
    value["group_organization"] = (design.group_organization.model_dump(mode="json")
                                   if design.group_organization is not None else None)
    # Native continuity/seam decisions use provenance, but never reapply poses.
    value["deformations"] = []
    for op in design.deformations:
        entry = op.model_dump(mode="json", include={"id", "type", "affected_helix_ids",
                                                    "target_ranges", "plane_a_bp", "plane_b_bp"})
        # Serialize the selected concrete params model directly: applying a
        # partial include through its tagged union produces misleading warnings.
        entry["params"] = op.params.model_dump(mode="json", include={
            "start_step", "direction", "polymer_circle_count", "curvature_deg_per_bp"})
        value["deformations"].append(entry)
    return value


def _project(design, *, scoped_segments=False, compact=False, inventory_cache=None):
    """Common native projection; callers select one closed wire schema."""
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    from backend.core.native_full_placement import NativePlacementError

    expected = inventory(design, previous=inventory_cache)
    try:
        records = _geometry_for_design(design)
        axes = deformed_helix_axes(design)
        axes = _apply_ovhg_rotations_to_axes(design, axes, records)
        coordinate_values = _records(records, expected)
        _axes(axes, expected, scoped_segments=scoped_segments)
    except NativePlacementError as error:
        _reject(str(error), "invalid_comparison_geometry")
    points = [record[field] for record in records for field in ("backbone_position", "base_position", "slab_position")]
    for axis in axes:
        points.extend([axis["start"], axis["end"], *axis["samples"]])
        for segment in axis["segments"]:
            points.extend([segment["start"], segment["end"]])
            if scoped_segments:
                points.extend(segment.get("samples", ()))
        for value in axis.get("ovhg_axes", {}).values():
            points.extend([value["start"], value["end"]])
    bounds = None
    if points:
        import numpy as np
        array = np.asarray(points, dtype=np.float64)
        # Bounds keep the native values themselves (min/max select, never round).
        low, high = array.argmin(axis=0), array.argmax(axis=0)
        bounds = {"minimum": [points[low[i]][i] for i in range(3)],
                  "maximum": [points[high[i]][i] for i in range(3)]}
    return {"component_version": COMPONENT_VERSION, "representation": "native-full-v1", "units": "nm",
            "nucleotides": pack_records_compact(records, coordinate_values=coordinate_values) if compact else pack_records(records), "helix_axes": axes, "display_topology": _topology(design), "bounds_nm": bounds}


def project(design):
    """Complete v3 DNA component, including native scoped axis samples."""
    return _project(design, scoped_segments=True)


def project_for_deformation_preview(design, *, inventory_cache=None):
    """Private preview schema preserving native per-domain axis samples.

    Preview v3 (compact f64 coordinate block) and comparison v3 (JSON rows) share the complete native inventory. The same
    prospective work and emitted-site/axis limits still apply.
    """
    return {**_project(design, scoped_segments=True, compact=True, inventory_cache=inventory_cache),
            "component_kind": "deformation-preview-dna", "component_version": 3}
