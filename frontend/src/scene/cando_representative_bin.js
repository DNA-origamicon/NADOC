/** Decode the compact static CanDo 298 K conformation (little-endian CFRM v1). */
const MAGIC = 0x4D524643
const VERSION = 1
const FIXED_BYTES = 24
const POSITION_BYTES = 52
const AXIS_BYTES = 20

export function parseCandoRepresentativeBin(buf) {
  if (!buf || buf.byteLength < FIXED_BYTES) return null
  const dv = new DataView(buf)
  if (dv.getUint32(0, true) !== MAGIC || dv.getUint32(4, true) !== VERSION) return null
  const nPositions = dv.getUint32(8, true)
  const nAxis = dv.getUint32(12, true)
  const nHelices = dv.getUint32(16, true)
  const headerLen = dv.getUint32(20, true)
  let off = FIXED_BYTES
  if (off + headerLen > buf.byteLength) return null
  let header
  try {
    header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off, headerLen)))
  } catch { return null }
  off += headerLen
  off += (4 - (off % 4)) % 4
  const expected = off + nPositions * POSITION_BYTES + nAxis * AXIS_BYTES
  const helices = header?.helix_ids
  if (expected !== buf.byteLength || !Array.isArray(helices) || helices.length !== nHelices) return null

  const representative_positions = new Array(nPositions)
  for (let i = 0; i < nPositions; i++, off += POSITION_BYTES) {
    const helix = dv.getUint32(off, true)
    if (helix >= helices.length) return null
    const coords = Array.from({ length: 9 }, (_, j) => dv.getFloat32(off + 16 + j * 4, true))
    const row = {
      helix_id: helices[helix], bp_index: dv.getInt32(off + 4, true),
      copy: dv.getInt32(off + 8, true),
      direction: dv.getUint32(off + 12, true) ? 'REVERSE' : 'FORWARD',
      backbone_position: coords.slice(0, 3),
    }
    if (coords.slice(3).every(Number.isFinite)) {
      ;[row.nx, row.ny, row.nz, row.tx, row.ty, row.tz] = coords.slice(3)
    }
    representative_positions[i] = row
  }

  const representative_axis = new Array(nAxis)
  for (let i = 0; i < nAxis; i++, off += AXIS_BYTES) {
    const helix = dv.getUint32(off, true)
    if (helix >= helices.length) return null
    representative_axis[i] = {
      helix_id: helices[helix], bp_index: dv.getInt32(off + 4, true),
      position: [
        dv.getFloat32(off + 8, true),
        dv.getFloat32(off + 12, true),
        dv.getFloat32(off + 16, true),
      ],
    }
  }
  const { helix_ids: _helixIds, ...metadata } = header
  return {
    ready: representative_positions.length > 0,
    ...metadata,
    representative_positions,
    representative_axis,
    binary: true,
  }
}
