import { describe, expect, it } from 'vitest'

import { makeAtomTable } from './atom_table.js'
import {
  isMdAtomFrameBin,
  makeMdAtomFrameTopology,
  parseMdAtomFrameBin,
} from './md_atom_frame_bin.js'

function frameBuffer({ frameIdx = 7, nFrames = 100, xyz = [[1, 2, 3], [-4, 5, 6]] } = {}) {
  const count = xyz.length
  const buffer = new ArrayBuffer(36 + count * 12)
  const bytes = new Uint8Array(buffer)
  bytes.set(new TextEncoder().encode('NADOCMDA'))
  const view = new DataView(buffer)
  view.setUint32(8, 1, true)
  view.setUint32(12, 36, true)
  view.setUint32(16, frameIdx, true)
  view.setUint32(20, nFrames, true)
  view.setUint32(24, count, true)
  view.setFloat64(28, 42.5, true)
  const values = new Float32Array(buffer, 36)
  for (let i = 0; i < count; i++) {
    values[i] = xyz[i][0]
    values[count + i] = xyz[i][1]
    values[count * 2 + i] = xyz[i][2]
  }
  return buffer
}

const READY = {
  binary_atom_frames: true,
  atom_serials: [4021, 9107],
  atom_elements: ['P', 'O'],
  atom_ident: {
    strands: ['scaffold'], helices: ['h0'], dirs: ['FORWARD'],
    strand_idx: [0, 0], helix_idx: [0, 0], dir_idx: [0, 0], bp: [3, 3],
    names: ['P', "O3'"], copy_k: [0, 0],
    scalar_keys: ['h0:3:FORWARD', 'h0:3:FORWARD'],
    base_keys: ['scaffold:3', 'scaffold:3'],
  },
}

describe('binary MD atom frames', () => {
  it('decodes zero-copy XYZ columns over immutable sparse-serial topology', () => {
    const topology = makeMdAtomFrameTopology(READY)
    const buffer = frameBuffer()
    expect(isMdAtomFrameBin(buffer)).toBe(true)
    const frame = parseMdAtomFrameBin(buffer, topology)
    expect(frame).toMatchObject({ type: 'frame', frame_idx: 7, n_frames: 100, time_ps: 42.5 })
    expect(Array.from(frame.atoms.x)).toEqual([1, -4])
    expect(Array.from(frame.atoms.y)).toEqual([2, 5])
    expect(Array.from(frame.atoms.z)).toEqual([3, 6])

    const table = makeAtomTable(frame.atoms)
    expect(table.serial(0)).toBe(4021)
    expect(table.element(1)).toBe('O')
    expect(table.materialize(1)).toMatchObject({
      serial: 9107, name: "O3'", base_key: 'scaffold:3', x: -4, y: 5, z: 6,
    })
  })

  it('distinguishes solvent blobs and rejects topology/count mismatches', () => {
    expect(isMdAtomFrameBin(new ArrayBuffer(40))).toBe(false)
    const topology = makeMdAtomFrameTopology(READY)
    expect(() => parseMdAtomFrameBin(frameBuffer({ xyz: [[1, 2, 3]] }), topology))
      .toThrow('invalid binary MD atom frame')
    expect(() => parseMdAtomFrameBin(frameBuffer(), null)).toThrow('before topology')
  })
})
