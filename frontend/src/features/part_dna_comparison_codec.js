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
  list(rows, 1024)
  return rows.map(row => {
    if (!Array.isArray(row) || row.length !== DNA_RECORD_COLUMNS.length) fail('invalid fixed-row native DNA transport')
    return Object.fromEntries(DNA_RECORD_COLUMNS.map((field, index) => [field, row[index]]))
  })
}
