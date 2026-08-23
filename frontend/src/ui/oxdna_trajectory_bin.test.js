import { describe, it, expect } from 'vitest'
import { decodeOxdnaTrajectoryBin } from './oxdna_trajectory_bin.js'

function payload(header, floats) {
  const h = new TextEncoder().encode(JSON.stringify(header))
  const off = (12 + h.length + 3) & ~3
  const buf = new ArrayBuffer(off + floats.length * 4)
  new Uint8Array(buf, 0, 8).set(new TextEncoder().encode('NADOTR1\0'))
  new DataView(buf).setUint32(8, h.length, true)
  new Uint8Array(buf, 12, h.length).set(h)
  new Float32Array(buf, off, floats.length).set(floats)
  return buf
}

describe('decodeOxdnaTrajectoryBin', () => {
  it('creates zero-copy Float32 frame views and preserves metadata', () => {
    const r = decodeOxdnaTrajectoryBin(payload({
      ready: true, n_frames: 2, n_nucleotides: 1, keys: [['h', 0, 'F']],
      markers: [], stages: [],
    }, Array.from({ length: 18 }, (_, i) => i + 0.25)))
    expect(r.ready).toBe(true)
    expect(r.frames).toHaveLength(2)
    expect(r.frames[0]).toBeInstanceOf(Float32Array)
    expect(r.frames[1][0]).toBeCloseTo(9.25)
    expect(r.frames[0].buffer).toBe(r.frames[1].buffer)
  })

  it('rejects malformed and truncated payloads', () => {
    expect(decodeOxdnaTrajectoryBin(new ArrayBuffer(12))).toBeNull()
    const bad = payload({ n_frames: 2, n_nucleotides: 1 }, [1, 2])
    expect(decodeOxdnaTrajectoryBin(bad)).toBeNull()
  })
})
