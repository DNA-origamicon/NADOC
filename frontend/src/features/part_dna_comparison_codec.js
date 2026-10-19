/**
 * Native DNA display records: fixed JSON rows (comparison v3, preview v2) or the
 * compact preview v3 form whose coordinates travel as one base64 little-endian
 * float64 block. Both decode to the same records: all native values, no rounding.
 */
import { fail, list } from './part_comparison_validation.js'

export const DNA_RECORD_COLUMNS = Object.freeze([
  'helix_id', 'bp_index', 'direction', 'copy_k', 'backbone_position',
  'base_position', 'base_normal', 'axis_tangent', 'placement_source', 'helical_site',
  'strand_id', 'strand_type', 'is_five_prime', 'is_three_prime', 'domain_index',
  'overhang_id', 'is_reference', 'is_flexible_segment', 'is_unpaired',
  'slab_position', 'slab_quaternion',
])

const MAX_RECORDS = 2_000_000  // = DNA_DISPLAY_LIMITS.sites (backend MAX_SLOTS)
export const COMPACT_ENCODING = 'f64-block-v1'
// Same order as backend/core/part_dna_comparison_codec.py VECTOR_FIELDS / SITE_FIELDS.
const VECTOR_FIELDS = [['backbone_position', 3], ['base_position', 3], ['base_normal', 3],
  ['axis_tangent', 3], ['slab_position', 3], ['slab_quaternion', 4]]
const SITE_FIELDS = [['axis_point', 3], ['radial_hat', 3], ['azimuth_rad', 0], ['groove_offset_rad', 0], ['phase_roll_rad', 0]]
const STRIDE = 28
const VECTOR_NAMES = new Set([...VECTOR_FIELDS.map(([name]) => name), 'helical_site'])
export const SCALAR_COLUMNS = Object.freeze(DNA_RECORD_COLUMNS.filter(name => !VECTOR_NAMES.has(name)))
const UNROLLED_SCALARS = ['helix_id', 'bp_index', 'direction', 'copy_k', 'placement_source', 'strand_id', 'strand_type',
  'is_five_prime', 'is_three_prime', 'domain_index', 'overhang_id', 'is_reference', 'is_flexible_segment', 'is_unpaired']
if (SCALAR_COLUMNS.join() !== UNROLLED_SCALARS.join()) throw new Error('Compact DNA decoder layout is out of date')
const littleEndian = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1

function bytesFromBase64(text) {
  if (typeof Uint8Array.fromBase64 === 'function') return Uint8Array.fromBase64(text)
  const binary = atob(text), bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

// The validator decodes each compact block once; the layer builder then takes
// those freshly allocated records instead of decoding again (they are not
// retained by the validator). Any other caller gets its own decode.
const decodedCompact = new WeakMap()

function decodeCompact(value) {
  const keys = Object.keys(value)
  if (keys.length !== 4 || !['encoding', 'count', 'rows', 'f64'].every(key => Object.hasOwn(value, key))
      || value.encoding !== COMPACT_ENCODING) fail('invalid compact native DNA transport')
  const { count, rows, f64 } = value
  if (!Number.isSafeInteger(count) || count < 0 || count > MAX_RECORDS || !Array.isArray(rows) || rows.length !== count
      || typeof f64 !== 'string') fail('invalid compact native DNA transport')
  let bytes
  try { bytes = bytesFromBase64(f64) } catch { fail('invalid compact native DNA transport') }
  if (bytes.length !== count * STRIDE * 8) fail('invalid compact native DNA transport')
  let floats
  if (littleEndian && bytes.byteOffset % 8 === 0) floats = new Float64Array(bytes.buffer, bytes.byteOffset, count * STRIDE)
  else {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    floats = new Float64Array(count * STRIDE)
    for (let i = 0; i < floats.length; i++) floats[i] = view.getFloat64(i * 8, true)
  }
  // Unrolled for speed (18k records x 8 arrays); layout = VECTOR_FIELDS then
  // SITE_FIELDS, 28 doubles per record. Field order of each record follows
  // DNA_RECORD_COLUMNS exactly.
  const columns = SCALAR_COLUMNS.length, records = new Array(count)
  for (let index = 0; index < count; index++) {
    const row = rows[index]
    if (!Array.isArray(row) || row.length !== columns) fail('invalid compact native DNA transport')
    const f = floats, o = index * STRIDE
    records[index] = {
      helix_id: row[0], bp_index: row[1], direction: row[2], copy_k: row[3],
      backbone_position: [f[o], f[o + 1], f[o + 2]],
      base_position: [f[o + 3], f[o + 4], f[o + 5]],
      base_normal: [f[o + 6], f[o + 7], f[o + 8]],
      axis_tangent: [f[o + 9], f[o + 10], f[o + 11]],
      placement_source: row[4],
      helical_site: { axis_point: [f[o + 19], f[o + 20], f[o + 21]], radial_hat: [f[o + 22], f[o + 23], f[o + 24]],
        azimuth_rad: f[o + 25], groove_offset_rad: f[o + 26], phase_roll_rad: f[o + 27] },
      strand_id: row[5], strand_type: row[6], is_five_prime: row[7], is_three_prime: row[8], domain_index: row[9],
      overhang_id: row[10], is_reference: row[11], is_flexible_segment: row[12], is_unpaired: row[13],
      slab_position: [f[o + 12], f[o + 13], f[o + 14]],
      slab_quaternion: [f[o + 15], f[o + 16], f[o + 17], f[o + 18]],
    }
  }
  return records
}

export function decodeDnaComparisonRecords(rows) {
  if (rows !== null && typeof rows === 'object' && !Array.isArray(rows)) {
    const records = decodeCompact(rows)
    decodedCompact.set(rows, records)
    return records
  }
  list(rows, MAX_RECORDS)
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
  if (rows !== null && typeof rows === 'object' && !Array.isArray(rows)) {
    const taken = decodedCompact.get(rows)
    decodedCompact.delete(rows)
    return taken ?? decodeCompact(rows)  // compact decoding allocates fresh arrays
  }
  list(rows, MAX_RECORDS)
  return rows.map(row => {
    if (!Array.isArray(row) || row.length !== DNA_RECORD_COLUMNS.length) fail('invalid fixed-row native DNA transport')
    const record = {}
    for (let index = 0; index < DNA_RECORD_COLUMNS.length; index++) record[DNA_RECORD_COLUMNS[index]] = copyValue(row[index])
    return record
  })
}
