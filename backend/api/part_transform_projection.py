"""Lossless native Full transform display, separate from comparison schemas.

Extra crossover bases, flexible arcs, CPD landmarks and ss linkers remain
explicit companion-renderer inputs. Their coordinates are not invented here.
The future renderer must implement every required companion or refuse the pane.
"""

from math import isfinite

from backend.api.part_transform_display_contract import (
    DISPLAY_FIELDS, MAX_AXIS_POINTS, MAX_RECORDS, bounded, checkpoint, inventory, limit, reject,
)


_RECORD_FIELDS = frozenset({"helix_id", "bp_index", "direction", "copy_k", "backbone_position",
    "base_position", "base_normal", "axis_tangent", "placement_source", "helical_site", "strand_id",
    "strand_type", "is_five_prime", "is_three_prime", "domain_index", "overhang_id", "is_reference",
    "is_flexible_segment", "is_unpaired", "slab_position", "slab_quaternion", "extension_id",
    "nucleobase", "is_modification", "modification"})
_REQUIRED = frozenset({"helix_id", "bp_index", "direction", "backbone_position", "base_position",
    "base_normal", "axis_tangent", "placement_source", "strand_id", "strand_type", "is_five_prime",
    "is_three_prime", "domain_index", "overhang_id"})


def point(value, length=3):
    if (type(value) is not list or len(value) != length
            or any(type(v) not in (float, int) or not isfinite(v) for v in value)):
        reject("Malformed native transform display coordinates", "invalid_preview_geometry")


def _check_slab_block(records, block, *, native_directions=None):
    """Validate an already checked codec block with unchanged native arithmetic.

    This private adapter consumes only the block collected from these records.
    Unsupported or failed batches retain the original authority's diagnostics.
    No pose is constructed, repaired, cached, or returned to a consumer.
    """
    import numpy as np
    from scipy.spatial.transform import Rotation
    from backend.core.native_full_placement import SOURCE
    from backend.core.native_slab_placement import (
        _native_registration, _native_slab_array_poses, authoritative_slab_poses,
    )

    count = len(records) if native_directions is None else len(native_directions)
    if count and block.size == count * 28:
        try:
            registration = _native_registration()
            sources_valid = native_directions is not None or all(r.get("placement_source") == SOURCE for r in records)
            record_directions = native_directions if native_directions is not None else [r.get("direction") for r in records]
            if len(registration) == 2 and sources_valid and all(d in registration for d in record_directions):
                values = block.reshape((-1, 28))
                # Match the original contiguous array layout, including at
                # acceptance boundaries; avoid Python per-record extraction.
                arrays = [np.ascontiguousarray(values[:, start:start + 3]) for start in (0, 3, 6, 9)]
                # There are two immutable registrations. Select their rows in
                # NumPy instead of converting the same six Python scalars for
                # every nucleotide. The arithmetic and contiguous inputs below
                # remain those of the native authority.
                directions = tuple(registration)
                selector = np.fromiter((d == directions[1] for d in record_directions),
                                       dtype=np.intp, count=count)
                offsets = np.asarray([registration[d] for d in directions])[selector]
                poses = _native_slab_array_poses(*arrays,
                    np.ascontiguousarray(offsets[:, 0]), np.ascontiguousarray(offsets[:, 1]))
                quaternions = np.ascontiguousarray(values[:, 15:19])
                if (poses is not None and np.all(np.isfinite(quaternions))
                        and np.all(abs(np.linalg.norm(quaternions, axis=1) - 1.) <= 1e-6)):
                    frames = Rotation.from_quat(quaternions).as_matrix()
                    if (np.allclose(values[:, 12:15], poses[0], rtol=0, atol=1e-7)
                            and np.allclose(frames, poses[1], rtol=0, atol=1e-7)):
                        return True
        except (TypeError, ValueError, OverflowError):
            pass
    if native_directions is not None:
        return not count  # Caller falls back to the complete record diagnostics.
    authoritative_slab_poses(records)
    return True


def _records(records, expected):
    import numpy as np
    from backend.core.native_full_placement import SOURCE
    from backend.core.native_slab_placement import SLABLESS_SOURCES

    limit(len(records), MAX_RECORDS, "emitted records")
    seen = set()
    coordinates = []
    checked_fields = set()
    def point(value, length=3):
        if type(value) is not list or len(value) != length:
            reject("Malformed native transform display coordinates", "invalid_preview_geometry")
        coordinates.extend(value)

    for value in records:
        if type(value) is not dict:
            reject("Unreviewed native transform record fields")
        fields = tuple(value)
        if fields not in checked_fields:
            if not _REQUIRED <= value.keys() <= _RECORD_FIELDS:
                reject("Unreviewed native transform record fields")
            checked_fields.add(fields)
        key = value["helix_id"], value["bp_index"], value["direction"], value.get("copy_k", 0)
        if key in seen:
            reject("Duplicate native transform display record", "invalid_preview_geometry")
        seen.add(key)
        for name in ("backbone_position", "base_position", "base_normal", "axis_tangent"):
            point(value[name])
        if key in expected.extensions:
            extension = expected.extensions[key]
            if (value["placement_source"] not in SLABLESS_SOURCES or value.get("extension_id") != extension.id
                    or value["strand_id"] != extension.strand_id):
                reject("Extension display identity disagrees with its source", "invalid_preview_geometry")
        else:
            owner = value["strand_id"], value["domain_index"], value["overhang_id"], value.get("is_reference", False)
            if expected.sites.get(key) != owner or value["placement_source"] != SOURCE:
                reject("Native display occupancy disagrees with its source", "invalid_preview_geometry")
            site = value.get("helical_site")
            if type(site) is not dict or set(site) != {"axis_point", "radial_hat", "azimuth_rad", "groove_offset_rad", "phase_roll_rad"}:
                reject("Unreviewed native transform helical site")
            # Match the existing compact codec's vector-then-site layout so
            # its encoder can consume this exact checked coordinate block.
            point(value.get("slab_position")), point(value.get("slab_quaternion"), 4)
            point(site["axis_point"]), point(site["radial_hat"])
            coordinates.extend((site["azimuth_rad"], site["groove_offset_rad"], site["phase_roll_rad"]))
    if seen != expected.sites.keys() | expected.extensions.keys():
        reject("Native transform display omitted occupied records", "invalid_preview_geometry")
    # Same exact numeric-type/finiteness checks, batched before the unchanged
    # native bead/base/slab authority. Avoid a Python generator per vector.
    if not set(map(type, coordinates)) <= {int, float}:
        reject("Malformed native transform display coordinates", "invalid_preview_geometry")
    block = np.fromiter(coordinates, dtype="<f8", count=len(coordinates))
    if not np.isfinite(block).all():
        reject("Malformed native transform display coordinates", "invalid_preview_geometry")
    _check_slab_block(records, block)
    return block


def _axes(values, expected, design):
    from backend.core.part_dna_comparison import AXIS_FIELDS, SEGMENT_FIELDS

    helices = {key for key in expected.indices["helices"] if not key.startswith("__lnk__")}
    seen, covered, count = set(), {}, 0
    for axis in values:
        if not {"helix_id", "start", "end", "samples", "segments"} <= axis.keys() <= AXIS_FIELDS | {"residue_transformed"}:
            reject("Unreviewed native transform axis")
        if "residue_transformed" in axis and type(axis["residue_transformed"]) is not bool:
            reject("Malformed native transform axis flag", "invalid_preview_geometry")
        hid = axis["helix_id"]
        if hid not in helices or hid in seen:
            reject("Native transform axis identity mismatch", "invalid_preview_geometry")
        seen.add(hid)
        for value in (axis["start"], axis["end"], *axis["samples"]):
            point(value)
            count += 1
        for segment in axis["segments"]:
            if not {"strand_id", "domain_index", "ovhg_id", "bp_lo", "bp_hi", "start", "end"} <= segment.keys() <= SEGMENT_FIELDS | {"samples"}:
                reject("Unreviewed native transform axis segment")
            for value in (segment["start"], segment["end"], *segment.get("samples", [])):
                point(value)
                count += 1
            refs = segment.get("domain_ids") or ([{"strand_id": segment["strand_id"], "domain_index": segment["domain_index"]}]
                if segment["strand_id"] is not None else [])
            for ref in refs:
                strand = expected.indices["strands"].get(ref["strand_id"])
                ordinal = ref["domain_index"]
                if strand is None or type(ordinal) is not int or not 0 <= ordinal < len(strand.domains):
                    reject("Native transform axis has unresolved domain", "invalid_preview_geometry")
                domain = strand.domains[ordinal]
                lo, hi = segment["bp_lo"], segment["bp_hi"]
                if (type(lo) is not int or type(hi) is not int or lo > hi or domain.helix_id != hid
                        or lo < min(domain.start_bp, domain.end_bp) or hi > max(domain.start_bp, domain.end_bp)):
                    reject("Native transform axis disagrees with its domain", "invalid_preview_geometry")
                covered.setdefault((strand.id, ordinal), set()).update(range(lo, hi + 1))
        for oid, value in axis.get("ovhg_axes", {}).items():
            overhang = expected.indices["overhangs"].get(oid)
            if overhang is None or overhang.helix_id != hid or set(value) != {"bp_min", "bp_max", "start", "end"}:
                reject("Native transform overhang axis mismatch", "invalid_preview_geometry")
            point(value["start"]), point(value["end"])
            count += 2
        limit(count, MAX_AXIS_POINTS, "axis points")
    if seen != helices:
        reject("Native transform display omitted helix axes", "invalid_preview_geometry")
    # Use the native range authority: flexible sites have no axis stick, while
    # residue poses split/transform segments without dropping their coverage.
    from backend.core.deformation import _segments_for_helix
    required = {}
    for helix in design.helices:
        if helix.id not in helices:
            continue
        for segment in _segments_for_helix(design, helix):
            refs = segment.get("domain_ids", [])
            for ref in refs:
                required.setdefault((ref["strand_id"], ref["domain_index"]), set()).update(
                    range(segment["bp_lo"], segment["bp_hi"] + 1))
    if covered != required:
        reject("Native transform display omitted domain axes", "invalid_preview_geometry")


def topology(design):
    from backend.core.cpd_representation import inject_cpd_representation

    result = {}
    for field in DISPLAY_FIELDS - {"group_organization"}:
        excluded = ({"prior_driven_topology"} if field in {"duplexes", "overhang_bindings"} else
                    {"bond_relaxation"} if field == "photoproduct_junctions" else
                    {"routing_seed"} if field == "strands" else set())
        result[field] = [value.model_dump(mode="json", exclude=excluded) for value in getattr(design, field)]
    result["group_organization"] = design.group_organization.model_dump(mode="json") if design.group_organization is not None else None
    inject_cpd_representation(result)
    for source, projected in zip(design.photoproduct_junctions, result["photoproduct_junctions"], strict=True):
        if source.design_coordinates and set(projected["representation_geometry"]) != set(source.design_coordinates):
            reject("CPD display requires all native residue landmarks", "invalid_preview_geometry")
    return result


def project_admitted(design, expected, check, *, compact=False):
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.deformation import deformed_helix_axes, _apply_ovhg_rotations_to_axes
    from backend.core.native_full_placement import NativePlacementError

    check()
    try:
        from backend.api.part_transform_compact_projection import compact_native
        try:
            direct = compact_native(design, expected, check) if compact else None
        except NativePlacementError:
            direct = None  # Preserve general-path residue identities in diagnostics.
        records = [] if direct is not None else _geometry_for_design(design)
        check()
        coordinates = direct[1] if direct is not None else _records(records, expected)
        axes = deformed_helix_axes(design)
        check()
        axes = _apply_ovhg_rotations_to_axes(design, axes, records)
        _axes(axes, expected, design)
    except NativePlacementError as error:
        reject(str(error), "invalid_preview_geometry")
    display = topology(design)
    companions = []
    for present, name in ((any(c.extra_bases for c in (*design.crossovers, *design.forced_ligations)), "extra-bases"),
            (bool(design.photoproduct_junctions), "photoproducts"), (bool(design.flexible_connections), "flexible-arcs"),
            (any(c.linker_type == "ss" for c in design.overhang_connections), "ss-linker-arcs")):
        if present:
            companions.append(name)
    from backend.core.part_dna_comparison_codec import RECORD_COLUMNS, pack_records_compact
    # Reuse the existing lossless f64 transport only for its exact native
    # record schema. Companions with extra fields or slabless/flexible records
    # keep the complete object transport; never drop fields to make them fit.
    compact_fields = frozenset(RECORD_COLUMNS)
    packed = direct is not None or compact and all(n.keys() == compact_fields and n["is_flexible_segment"] is False
                            and n["slab_position"] is not None and n["slab_quaternion"] is not None
                            for n in records)
    points = [] if packed else [n[name] for n in records for name in ("backbone_position", "base_position")]
    if not packed:
        points.extend(n["slab_position"] for n in records if n.get("slab_position") is not None)
    for axis in axes:
        points.extend((axis["start"], axis["end"], *axis["samples"]))
        for segment in axis["segments"]:
            points.extend((segment["start"], segment["end"], *segment.get("samples", [])))
        for value in axis.get("ovhg_axes", {}).values():
            points.extend((value["start"], value["end"]))
    bounds = None
    if points or (packed and coordinates.size):
        import numpy as np
        # Bounds use precisely the same bead/base/slab points as the object
        # path. The checked block already owns these doubles; avoid converting
        # tens of thousands of small lists back into an array.
        blocks = []
        if packed and coordinates.size:
            values = coordinates.reshape((-1, 28))
            blocks.extend((values[:, :6].reshape((-1, 3)), values[:, 12:15]))
        if points:
            blocks.append(np.asarray(points, dtype=np.float64))
        block = np.concatenate(blocks)
        bounds = {"minimum": block.min(axis=0).tolist(), "maximum": block.max(axis=0).tolist()}
    check()
    return {"component_kind": "transform-preview-dna", "component_version": 2 if packed else 1, "representation": "native-full-v1",
            "units": "nm", "nucleotides": direct[0] if direct is not None else pack_records_compact(records, coordinate_values=coordinates) if packed else records, "helix_axes": axes, "display_topology": display,
            "required_renderers": companions, "bounds_nm": bounds}


def project(design):
    """Standalone owned-model projection; host adds its whole-response bound."""
    check = checkpoint()
    return bounded(project_admitted(design, inventory(design, check), check))
