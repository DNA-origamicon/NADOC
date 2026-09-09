import { describe, expect, it } from 'vitest'

import { parseOxdnaTrajectoryBin } from './oxdna_trajectory_bin.js'

function fixture() {
  const header = new TextEncoder().encode(JSON.stringify({
    keys: [['h0', 1, 'FORWARD'], ['h0', 1, 'REVERSE', 2]],
    stages: [{ name: 'relax', kind: 'mc', n_frames: 2, field: null }],
    markers: [{ frame: 1, label: 'run', kind: 'production' }],
  }))
  let off = 20 + header.byteLength
  off += (4 - (off % 4)) % 4
  const buf = new ArrayBuffer(off + 2 * 2 * 6 * 4)
  const dv = new DataView(buf)
  dv.setUint32(0, 0x4E54524A, true)
  dv.setUint32(4, 1, true)
  dv.setUint32(8, 2, true)
  dv.setUint32(12, 2, true)
  dv.setUint32(16, header.byteLength, true)
  new Uint8Array(buf, 20, header.byteLength).set(header)
  new Float32Array(buf, off).set(Array.from({ length: 24 }, (_, i) => i + 0.25))
  return buf
}

describe('parseOxdnaTrajectoryBin', () => {
  it('decodes metadata and zero-copy typed frame views', () => {
    const buf = fixture()
    const out = parseOxdnaTrajectoryBin(buf)
    expect(out).toMatchObject({ ready: true, binary: true, n_frames: 2, n_nucleotides: 2 })
    expect(out.keys[1]).toEqual(['h0', 1, 'REVERSE', 2])
    expect(out.stages[0].kind).toBe('mc')
    expect(out.markers[0].frame).toBe(1)
    expect(out.frames).toHaveLength(2)
    expect(out.frames[0]).toBeInstanceOf(Float32Array)
    expect(Array.from(out.frames[0])).toEqual(Array.from({ length: 12 }, (_, i) => i + 0.25))
    expect(Array.from(out.frames[1])).toEqual(Array.from({ length: 12 }, (_, i) => i + 12.25))
    out.frames[0][0] = 99
    expect(new Float32Array(buf).includes(99)).toBe(true) // view, not a copied number array
  })

  it('rejects junk, unknown versions, truncated data, and key-count drift', () => {
    expect(parseOxdnaTrajectoryBin(null)).toBeNull()
    expect(parseOxdnaTrajectoryBin(new ArrayBuffer(4))).toBeNull()
    const version = fixture()
    new DataView(version).setUint32(4, 2, true)
    expect(parseOxdnaTrajectoryBin(version)).toBeNull()
    expect(parseOxdnaTrajectoryBin(fixture().slice(0, -4))).toBeNull()
    const keyDrift = fixture()
    new DataView(keyDrift).setUint32(12, 3, true)
    expect(parseOxdnaTrajectoryBin(keyDrift)).toBeNull()
  })

  it('accepts metadata-only frames for a graphene control with zero nucleotides', () => {
    const header = new TextEncoder().encode(JSON.stringify({
      keys: [], stages: [{ name: 'production', n_frames: 3 }], markers: [],
    }))
    let size = 20 + header.byteLength
    size += (4 - (size % 4)) % 4
    const buf = new ArrayBuffer(size)
    const dv = new DataView(buf)
    dv.setUint32(0, 0x4E54524A, true); dv.setUint32(4, 1, true)
    dv.setUint32(8, 3, true); dv.setUint32(12, 0, true)
    dv.setUint32(16, header.byteLength, true)
    new Uint8Array(buf, 20, header.byteLength).set(header)
    const out = parseOxdnaTrajectoryBin(buf)
    expect(out).toMatchObject({ ready: true, n_frames: 3, n_nucleotides: 0 })
    expect(out.frames).toHaveLength(3)
    expect(out.frames.every(frame => frame.length === 0)).toBe(true)
  })
})
