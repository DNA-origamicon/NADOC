/** Component v2 fixed rows: all native values, no rounding or model construction. */
import { fail, list } from './part_comparison_validation.js'

export const DNA_RECORD_COLUMNS = Object.freeze([
  'helix_id', 'bp_index', 'direction', 'copy_k', 'backbone_position',
  'base_position', 'base_normal', 'axis_tangent', 'placement_source', 'helical_site',
  'strand_id', 'strand_type', 'is_five_prime', 'is_three_prime', 'domain_index',
  'overhang_id', 'is_reference', 'is_flexible_segment', 'is_unpaired',
  'slab_position', 'slab_quaternion',
])

export function decodeDnaComparisonRecords(rows) {
  list(rows, 2_000_000)  // = DNA_DISPLAY_LIMITS.sites (backend MAX_SLOTS)
  return rows.map(row => {
    if (!Array.isArray(row) || row.length !== DNA_RECORD_COLUMNS.length) fail('invalid fixed-row native DNA transport')
    return Object.fromEntries(DNA_RECORD_COLUMNS.map((field, index) => [field, row[index]]))
  })
}

const copyValue = value => Array.isArray(value) ? value.slice()
  : value !== null && typeof value === 'object'
    ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, Array.isArray(item) ? item.slice() : item]))
    : value

/**
 * Decoded rows that share nothing with the transport (same result as
 * structuredClone(decodeDnaComparisonRecords(rows)) for validated rows, whose
 * values are scalars, number arrays and the flat helical_site object), ~5x faster.
 */
export function decodeDnaComparisonRecordsCopy(rows) {
  list(rows, 2_000_000)
  return rows.map(row => {
    if (!Array.isArray(row) || row.length !== DNA_RECORD_COLUMNS.length) fail('invalid fixed-row native DNA transport')
    const record = {}
    for (let index = 0; index < DNA_RECORD_COLUMNS.length; index++) record[DNA_RECORD_COLUMNS[index]] = copyValue(row[index])
    return record
  })
}
