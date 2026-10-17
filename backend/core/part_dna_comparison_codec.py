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


def unpack_records(rows):
    """Decode bounded display transport for exact native-parity consumers."""
    from backend.core.part_dna_comparison_contract import MAX_SLOTS

    if (type(rows) is not list or len(rows) > MAX_SLOTS
            or any(type(row) is not list or len(row) != len(RECORD_COLUMNS) for row in rows)):
        raise CommandContractError("Invalid fixed-row native DNA display transport", code="invalid_comparison_geometry")
    return [dict(zip(RECORD_COLUMNS, row, strict=True)) for row in rows]
