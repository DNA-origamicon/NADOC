import { describe, expect, it } from 'vitest'
import { parseCandoRepresentativeBin } from './cando_representative_bin.js'

function fixture() {
  const meta = new TextEncoder().encode(JSON.stringify({
    kind: 'normal-mode-ensemble', temperature_k: 298, n_frames: 48,
    representative_frame: 14, helix_ids: ['h0'],
  }))
  let dataOffset = 24 + meta.byteLength
  dataOffset += (4 - (dataOffset % 4)) % 4
  const buf = new ArrayBuffer(dataOffset + 52 + 20)
  const dv = new DataView(buf)
  ;[0x4D524643, 1, 1, 1, 1, meta.byteLength].forEach((v, i) => dv.setUint32(4 * i, v, true))
  new Uint8Array(buf, 24, meta.byteLength).set(meta)
  let off = dataOffset
  dv.setUint32(off, 0, true); dv.setInt32(off + 4, -2, true)
  dv.setInt32(off + 8, 3, true); dv.setUint32(off + 12, 1, true)
  ;[1.25, -2.5, 3.75, 0, 1, 0, 0, 0, 1].forEach((v, i) => dv.setFloat32(off + 16 + 4 * i, v, true))
  off += 52
  dv.setUint32(off, 0, true); dv.setInt32(off + 4, -2, true)
  ;[4, 5, 6].forEach((v, i) => dv.setFloat32(off + 8 + 4 * i, v, true))
  return buf
}

describe('parseCandoRepresentativeBin', () => {
  it('restores renderer rows and representative-axis metadata', () => {
    expect(parseCandoRepresentativeBin(fixture())).toEqual({
      ready: true,
      kind: 'normal-mode-ensemble', temperature_k: 298, n_frames: 48,
      representative_frame: 14, binary: true,
      representative_positions: [{
        helix_id: 'h0', bp_index: -2, copy: 3, direction: 'REVERSE',
        backbone_position: [1.25, -2.5, 3.75],
        nx: 0, ny: 1, nz: 0, tx: 0, ty: 0, tz: 1,
      }],
      representative_axis: [{ helix_id: 'h0', bp_index: -2, position: [4, 5, 6] }],
    })
  })

  it('rejects malformed, truncated, and unsupported payloads', () => {
    expect(parseCandoRepresentativeBin(null)).toBe(null)
    expect(parseCandoRepresentativeBin(new ArrayBuffer(12))).toBe(null)
    const bad = fixture(); new DataView(bad).setUint32(4, 99, true)
    expect(parseCandoRepresentativeBin(bad)).toBe(null)
  })
})
