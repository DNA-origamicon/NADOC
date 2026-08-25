/** Topology-stable binary atom frames from /ws/md-run.
 *
 * Wire v1 (little endian):
 *   char[8] "NADOCMDA"
 *   u32 version, header_bytes, frame_idx, n_frames, atom_count
 *   f64 time_ps
 *   f32 x[atom_count], y[atom_count], z[atom_count]
 *
 * Serial, element, identity, and bonds are static and arrive once in `ready`.
 */

const MAGIC = [78, 65, 68, 79, 67, 77, 68, 65] // NADOCMDA
const HEADER_BYTES = 36
const MAX_ATOMS = 1_000_000

function _indexArray(values, maximum) {
  if (maximum <= 0xff) return Uint8Array.from(values)
  if (maximum <= 0xffff) return Uint16Array.from(values)
  return Uint32Array.from(values)
}

function _intern(values, fallback = '') {
  const table = []
  const byValue = new Map()
  const indices = new Array(values.length)
  for (let i = 0; i < values.length; i++) {
    const value = values[i] == null ? fallback : String(values[i])
    let index = byValue.get(value)
    if (index === undefined) {
      index = table.length
      byValue.set(value, index)
      table.push(value)
    }
    indices[i] = index
  }
  return { table, indices: _indexArray(indices, table.length - 1) }
}

function _identityIndex(values, count, maximum = 0) {
  if (!Array.isArray(values) || values.length !== count) return new Uint8Array(count)
  return _indexArray(values, maximum)
}

/** Build immutable per-row topology once from the JSON `ready` message. */
export function makeMdAtomFrameTopology(ready) {
  const serialValues = ready?.atom_serials
  const elementValues = ready?.atom_elements
  if (!Array.isArray(serialValues) || !Array.isArray(elementValues) ||
      serialValues.length !== elementValues.length || serialValues.length > MAX_ATOMS) {
    return null
  }
  const count = serialValues.length
  const ident = ready?.atom_ident ?? {}
  const element = _intern(elementValues, 'C')
  const name = _intern(
    Array.isArray(ident.names) && ident.names.length === count
      ? ident.names : new Array(count).fill(''),
  )
  const scalarKey = _intern(
    Array.isArray(ident.scalar_keys) && ident.scalar_keys.length === count
      ? ident.scalar_keys : new Array(count).fill(''),
  )
  const baseKey = _intern(
    Array.isArray(ident.base_keys) && ident.base_keys.length === count
      ? ident.base_keys : new Array(count).fill(''),
  )
  const strands = Array.isArray(ident.strands) ? ident.strands : ['']
  const helices = Array.isArray(ident.helices) ? ident.helices : ['']
  const dirs = Array.isArray(ident.dirs) ? ident.dirs : ['']
  return {
    columnar: true,
    count,
    serial: Int32Array.from(serialValues),
    elementTable: element.table,
    elementIdx: element.indices,
    strandTable: strands,
    strandIdx: _identityIndex(ident.strand_idx, count, strands.length - 1),
    helixTable: helices,
    helixIdx: _identityIndex(ident.helix_idx, count, helices.length - 1),
    dirTable: dirs,
    dirIdx: _identityIndex(ident.dir_idx, count, dirs.length - 1),
    bpIndex: Int32Array.from(
      Array.isArray(ident.bp) && ident.bp.length === count
        ? ident.bp : new Array(count).fill(-1),
    ),
    nameTable: name.table,
    nameIdx: name.indices,
    copyK: Int32Array.from(
      Array.isArray(ident.copy_k) && ident.copy_k.length === count
        ? ident.copy_k : new Array(count).fill(0),
    ),
    scalarKeyTable: scalarKey.table,
    scalarKeyIdx: scalarKey.indices,
    baseKeyTable: baseKey.table,
    baseKeyIdx: baseKey.indices,
    auxHelixTable: [''],
    auxHelixIdx: new Uint8Array(count),
    auxT: new Float32Array(count),
  }
}

export function isMdAtomFrameBin(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 8) return false
  const bytes = new Uint8Array(buffer, 0, 8)
  return MAGIC.every((value, index) => bytes[index] === value)
}

/** Return a columnar atom payload whose coordinate arrays are zero-copy views. */
export function parseMdAtomFrameBin(buffer, topology) {
  if (!isMdAtomFrameBin(buffer)) return null
  if (!topology) throw new Error('binary MD atom frame arrived before topology')
  const view = new DataView(buffer)
  const version = view.getUint32(8, true)
  const headerBytes = view.getUint32(12, true)
  const frameIdx = view.getUint32(16, true)
  const nFrames = view.getUint32(20, true)
  const count = view.getUint32(24, true)
  const timePs = view.getFloat64(28, true)
  if (version !== 1 || headerBytes !== HEADER_BYTES || count !== topology.count ||
      count > MAX_ATOMS || nFrames === 0 || frameIdx >= nFrames ||
      buffer.byteLength !== HEADER_BYTES + count * 12) {
    throw new Error('invalid binary MD atom frame')
  }
  return {
    type: 'frame',
    frame_idx: frameIdx,
    n_frames: nFrames,
    time_ps: Number.isFinite(timePs) ? timePs : null,
    atoms: {
      ...topology,
      x: new Float32Array(buffer, HEADER_BYTES, count),
      y: new Float32Array(buffer, HEADER_BYTES + count * 4, count),
      z: new Float32Array(buffer, HEADER_BYTES + count * 8, count),
    },
  }
}
