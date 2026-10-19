"""Lossless fixed-row transport for the independently bounded DNA display DTO.

This is a wire codec, not an alternative geometry representation or a construction
input. Field order is fixed by component_version=2; the sender cannot supply a
schema. Every full native value, including loop copies and ownership flags, is
retained. Native output validation runs before packing.
"""

from backend.core.part_command_errors import CommandContractError


RECORD_COLUMNS = (
    "helix_id", "bp_index", "direction", "copy_k", "backbone_position",
    "base_position", "base_normal", "axis_tangent", "placement_source", "helical_site",
    "strand_id", "strand_type", "is_five_prime", "is_three_prime", "domain_index",
    "overhang_id", "is_reference", "is_flexible_segment", "is_unpaired",
    "slab_position", "slab_quaternion",
)


def pack_records(records):
    return [[record[field] for field in RECORD_COLUMNS] for record in records]


# Compact preview transport (deformation-preview component v3): the fixed
# coordinate fields travel as one base64 little-endian float64 block (28 values
# per record, in this order); every other column stays a JSON row value. Exact:
# the doubles are the native values bit for bit.
COMPACT_ENCODING = "f64-block-v1"
VECTOR_FIELDS = (("backbone_position", 3), ("base_position", 3), ("base_normal", 3),
                 ("axis_tangent", 3), ("slab_position", 3), ("slab_quaternion", 4))
SITE_FIELDS = (("axis_point", 3), ("radial_hat", 3), ("azimuth_rad", None),
               ("groove_offset_rad", None), ("phase_roll_rad", None))
STRIDE = sum(n for _, n in VECTOR_FIELDS) + sum(n or 1 for _, n in SITE_FIELDS)  # 28
SCALAR_COLUMNS = tuple(field for field in RECORD_COLUMNS
                       if field not in {name for name, _ in VECTOR_FIELDS} | {"helical_site"})


def _invalid(detail="Invalid compact native DNA display transport"):
    raise CommandContractError(detail, code="invalid_comparison_geometry")


def pack_records_compact(records):
    """Compact form of ``pack_records`` for records already shape/finite-checked."""
    import base64
    import numpy as np

    values = []
    extend = values.extend
    for record in records:
        for field, _ in VECTOR_FIELDS:
            extend(record[field])
        site = record["helical_site"]
        extend(site["axis_point"]), extend(site["radial_hat"])
        values.append(site["azimuth_rad"]), values.append(site["groove_offset_rad"]), values.append(site["phase_roll_rad"])
    if len(values) != STRIDE * len(records):
        _invalid("Native DNA coordinates do not match the compact transport layout")
    block = np.asarray(values, dtype="<f8")
    return {"encoding": COMPACT_ENCODING, "count": len(records),
            "rows": [[record[field] for field in SCALAR_COLUMNS] for record in records],
            "f64": base64.b64encode(block.tobytes()).decode("ascii")}


def _unpack_compact(value, limit):
    import base64
    import binascii
    import numpy as np

    if set(value) != {"encoding", "count", "rows", "f64"} or value["encoding"] != COMPACT_ENCODING:
        _invalid()
    count, rows = value["count"], value["rows"]
    if (type(count) is not int or not 0 <= count <= limit or type(rows) is not list or len(rows) != count
            or any(type(row) is not list or len(row) != len(SCALAR_COLUMNS) for row in rows)
            or type(value["f64"]) is not str or len(value["f64"]) > 4 * (STRIDE * 8 * count + 2) // 3 + 4):
        _invalid()
    try:
        raw = base64.b64decode(value["f64"], validate=True)
    except (binascii.Error, ValueError):
        _invalid()
    if len(raw) != STRIDE * 8 * count:
        _invalid()
    floats = np.frombuffer(raw, dtype="<f8").tolist()
    result = []
    for index, row in enumerate(rows):
        record = dict(zip(SCALAR_COLUMNS, row, strict=True))
        offset = index * STRIDE
        for field, size in VECTOR_FIELDS:
            record[field] = floats[offset:offset + size]
            offset += size
        site = {}
        for field, size in SITE_FIELDS:
            site[field] = floats[offset] if size is None else floats[offset:offset + size]
            offset += size or 1
        record["helical_site"] = site
        result.append({field: record[field] for field in RECORD_COLUMNS})
    return result


def unpack_records(rows):
    """Decode bounded display transport for exact native-parity consumers."""
    from backend.core.part_dna_comparison_contract import MAX_SLOTS

    if type(rows) is dict:
        return _unpack_compact(rows, MAX_SLOTS)
    if (type(rows) is not list or len(rows) > MAX_SLOTS
            or any(type(row) is not list or len(row) != len(RECORD_COLUMNS) for row in rows)):
        raise CommandContractError("Invalid fixed-row native DNA display transport", code="invalid_comparison_geometry")
    return [dict(zip(RECORD_COLUMNS, row, strict=True)) for row in rows]
