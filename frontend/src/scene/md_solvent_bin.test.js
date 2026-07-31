import { describe, it, expect } from 'vitest'
import { parseSolventBin, solventDnaFrames } from './md_solvent_bin.js'

const MAGIC = 0x4E534C56

/**
 * Build a payload byte-for-byte the way backend/core/md_solvent.pack_solvent_bin does.
 * Written independently of the parser so a layout drift on either side shows up here
 * rather than as solvent silently drawn in the wrong place.
 */
function packSolventBin(frames, header = {}) {
  const ids = Object.keys(frames).map(Number).sort((a, b) => a - b)
  const h = {
    frame_ids: ids,
    atomistic: false,
    n_waters_total: 0,
    n_ions: 0,
    n_ions_total: 0,
    has_box: true,
    shell_nm: null,
    capped: false,
    species_table: ['NA', 'CL', 'MG', 'K', 'CA'],
    ion_species: [],
    per_frame_nw: ids.map((i) => frames[i].nWater ?? (frames[i].water.length / 3)),
    n_serials: 0,
    ...header,
  }
  const hb = new TextEncoder().encode(JSON.stringify(h))
  const pad = (4 - (hb.length % 4)) % 4

  const blocks = []
  for (const i of ids) {
    const f = frames[i]
    blocks.push(f.water, f.ions)
    if (h.has_box) blocks.push(f.box)
    if (h.n_serials) blocks.push(f.dna)
  }
  const floatBytes = blocks.reduce((n, b) => n + b.length * 4, 0)

  const buf = new ArrayBuffer(20 + hb.length + pad + floatBytes)
  const dv = new DataView(buf)
  dv.setUint32(0, MAGIC, true)
  dv.setUint32(4, 2, true)
  dv.setUint32(8, ids.length, true)
  dv.setUint32(12, 0, true)
  dv.setUint32(16, hb.length, true)
  new Uint8Array(buf, 20, hb.length).set(hb)
  let off = 20 + hb.length + pad
  for (const b of blocks) { new Float32Array(buf, off, b.length).set(b); off += b.length * 4 }
  return buf
}

const f32 = (...v) => Float32Array.from(v)
const zeros = (n) => new Float32Array(n)

function oneFrame(over = {}) {
  return { water: f32(1, 2, 3), ions: f32(4, 5, 6), box: zeros(24), ...over }
}

describe('parseSolventBin', () => {
  it('reads a single sphere-mode frame', () => {
    const p = parseSolventBin(packSolventBin({ 0: oneFrame() }, { n_ions: 1 }))
    expect(p).not.toBeNull()
    expect(p.frameIds).toEqual([0])
    expect(p.atomistic).toBe(false)
  })

  it('returns water, ions and box as views onto the frame', () => {
    const buf = packSolventBin(
      { 0: { water: f32(1, 2, 3, 4, 5, 6), ions: f32(7, 8, 9), box: zeros(24) } },
      { n_ions: 1, n_waters_total: 99 })
    const p = parseSolventBin(buf)
    const f = p.frames.get(0)
    expect(Array.from(f.water)).toEqual([1, 2, 3, 4, 5, 6])
    expect(Array.from(f.ions)).toEqual([7, 8, 9])
    expect(f.box.length).toBe(24)
    expect(f.nWater).toBe(2)
    expect(p.nWatersTotal).toBe(99)
  })

  it('reads 9 floats per molecule in atomistic mode', () => {
    const buf = packSolventBin(
      { 0: { water: new Float32Array(18), nWater: 2, ions: zeros(0), box: zeros(24) } },
      { atomistic: true })
    const p = parseSolventBin(buf)
    expect(p.atomistic).toBe(true)
    expect(p.frames.get(0).water.length).toBe(18)
  })

  // A hydration shell is a different molecule set each frame — water diffuses. The
  // per-frame count is what lets the reader walk the blocks at all; assuming a
  // constant count would misread every frame after the first.
  it('handles a different water count in every frame', () => {
    const buf = packSolventBin({
      0: { water: f32(1, 1, 1), ions: zeros(0), box: zeros(24) },
      1: { water: f32(2, 2, 2, 3, 3, 3), ions: zeros(0), box: zeros(24) },
      2: { water: zeros(0), ions: zeros(0), box: zeros(24) },
    })
    const p = parseSolventBin(buf)
    expect(p.frames.get(0).nWater).toBe(1)
    expect(p.frames.get(1).nWater).toBe(2)
    expect(p.frames.get(2).nWater).toBe(0)
    expect(Array.from(p.frames.get(1).water)).toEqual([2, 2, 2, 3, 3, 3])
  })

  it('keys frames by their COMPOSITE index, not by position', () => {
    const buf = packSolventBin({
      4: oneFrame({ water: f32(4, 4, 4) }),
      9: oneFrame({ water: f32(9, 9, 9) }),
    }, { n_ions: 1 })
    const p = parseSolventBin(buf)
    expect(p.frameIds).toEqual([4, 9])
    expect(Array.from(p.frames.get(9).water)).toEqual([9, 9, 9])
    expect(p.frames.has(0)).toBe(false)
  })

  it('exposes the ion species table for colouring', () => {
    const buf = packSolventBin({ 0: oneFrame({ ions: f32(1, 1, 1, 2, 2, 2) }) },
      { n_ions: 2, ion_species: [0, 2] })
    const p = parseSolventBin(buf)
    expect(Array.from(p.ionSpecies)).toEqual([0, 2])
    expect(p.speciesTable[0]).toBe('NA')
    expect(p.speciesTable[2]).toBe('MG')
  })

  it('reports the shell radius and the cap flag', () => {
    const p = parseSolventBin(packSolventBin({ 0: oneFrame() },
      { n_ions: 1, shell_nm: 0.8, capped: true }))
    expect(p.shellNm).toBeCloseTo(0.8)
    expect(p.capped).toBe(true)
  })

  // The float blocks are only legal views if their offset is a multiple of 4, and
  // the JSON header is an arbitrary byte length — hence the zero pad. Vary the
  // header length through a full alignment cycle.
  for (const n of [1, 2, 3, 4, 5, 6, 7, 8]) {
    it(`decodes correctly with a header padded by ${(4 - (n % 4)) % 4} bytes`, () => {
      const buf = packSolventBin({ 0: oneFrame({ water: f32(7, 8, 9) }) },
        { n_ions: 1, pad: 'x'.repeat(n) })
      const p = parseSolventBin(buf)
      expect(Array.from(p.frames.get(0).water)).toEqual([7, 8, 9])
    })
  }

  describe('rejects bad input', () => {
    it('null / short buffer', () => {
      expect(parseSolventBin(null)).toBeNull()
      expect(parseSolventBin(new ArrayBuffer(8))).toBeNull()
    })

    it('wrong magic', () => {
      const buf = packSolventBin({ 0: oneFrame() }, { n_ions: 1 })
      new DataView(buf).setUint32(0, 0xDEADBEEF, true)
      expect(parseSolventBin(buf)).toBeNull()
    })

    it('the empty "not ready" payload', () => {
      expect(parseSolventBin(packSolventBin({}))).toBeNull()
    })

    it('a truncated float block rather than throwing', () => {
      const buf = packSolventBin({ 0: oneFrame({ water: f32(1, 2, 3) }) }, { n_ions: 1 })
      expect(parseSolventBin(buf.slice(0, buf.byteLength - 8))).toBeNull()
    })

    it('a corrupt JSON header', () => {
      const buf = packSolventBin({ 0: oneFrame() }, { n_ions: 1 })
      new Uint8Array(buf)[21] = 0x7B      // smash a byte inside the JSON
      expect(parseSolventBin(buf)).toBeNull()
    })
  })
})

// A blob produced by the REAL Python packer (backend/core/md_solvent.pack_solvent_bin),
// captured 2026-07-30 (format v2). The hand-rolled packer above shares no code with the backend, so
// on its own it only proves the parser is self-consistent — this pins both sides to the
// same bytes. Regenerate with tests/test_md_solvent_pack.py's inputs if the layout is
// ever versioned up.
const PYTHON_PACKED = 'VkxTTgIAAAACAAAAAAAAAOEAAAB7ImZyYW1lX2lkcyI6WzAsM10sImF0b21pc3RpYyI6ZmFsc2UsIm5fd2F0ZXJzX3RvdGFsIjo1MDAsIm5faW9ucyI6MSwic2hlbGxfbm0iOjAuNSwiY2FwcGVkIjp0cnVlLCJuX2lvbnNfdG90YWwiOjksImhhc19ib3giOnRydWUsInNwZWNpZXNfdGFibGUiOlsiTkEiLCJDTCIsIk1HIiwiSyIsIkNBIl0sImlvbl9zcGVjaWVzIjpbMl0sInBlcl9mcmFtZV9udyI6WzIsMV0sIm5fc2VyaWFscyI6MH0AAAAAAIA/AAAAQAAAQEAAAIBAAACgQAAAwEAAAOBAAAAAQQAAEEEAAAAAAACAPwAAAEAAAEBAAACAQAAAoEAAAMBAAADgQAAAAEEAABBBAAAgQQAAMEEAAEBBAABQQQAAYEEAAHBBAACAQQAAiEEAAJBBAACYQQAAoEEAAKhBAACwQQAAuEEAABBBAAAQQQAAEEEAAIA/AACAPwAAgD8AAAAAAAAAQAAAgEAAAMBAAAAAQQAAIEEAAEBBAABgQQAAgEEAAJBBAACgQQAAsEEAAMBBAADQQQAA4EEAAPBBAAAAQgAACEIAABBCAAAYQgAAIEIAAChCAAAwQgAAOEI='

function fromBase64(b64) {
  const bin = atob(b64)
  const u8 = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i)
  return u8.buffer
}

describe('cross-language pin against the Python packer', () => {
  it('decodes a real backend payload', () => {
    const p = parseSolventBin(fromBase64(PYTHON_PACKED))
    expect(p).not.toBeNull()
    expect(p.frameIds).toEqual([0, 3])
    expect(p.nWatersTotal).toBe(500)
    expect(p.nIons).toBe(1)
    expect(p.capped).toBe(true)
    expect(p.shellNm).toBeCloseTo(0.5)
    expect(p.speciesTable).toEqual(['NA', 'CL', 'MG', 'K', 'CA'])
    expect(Array.from(p.ionSpecies)).toEqual([2])          // MG
  })

  it('reads each frame\'s blocks at the right offsets', () => {
    const p = parseSolventBin(fromBase64(PYTHON_PACKED))
    const f0 = p.frames.get(0)
    expect(f0.nWater).toBe(2)
    expect(Array.from(f0.water)).toEqual([1, 2, 3, 4, 5, 6])
    expect(Array.from(f0.ions)).toEqual([7, 8, 9])
    expect(Array.from(f0.box)).toEqual([...Array(24).keys()])

    const f3 = p.frames.get(3)
    expect(f3.nWater).toBe(1)
    expect(Array.from(f3.water)).toEqual([9, 9, 9])
    expect(Array.from(f3.ions)).toEqual([1, 1, 1])
    expect(Array.from(f3.box)).toEqual([...Array(24).keys()].map((v) => v * 2))
  })
})

describe('solventDnaFrames', () => {
  it('returns the DNA half in the positions-only shape the controller consumes', () => {
    const buf = packSolventBin({
      0: { water: f32(1, 2, 3), ions: zeros(0), box: zeros(24), dna: f32(1, 1, 1, 2, 2, 2) },
      3: { water: f32(4, 5, 6), ions: zeros(0), box: zeros(24), dna: f32(9, 9, 9, 8, 8, 8) },
    }, { n_serials: 2 })
    const p = parseSolventBin(buf)
    expect(p.nSerials).toBe(2)
    const dna = solventDnaFrames(p)
    expect(Object.keys(dna)).toEqual(['0', '3'])
    expect(Array.from(dna['3'])).toEqual([9, 9, 9, 8, 8, 8])
  })

  it('is null when the payload carries no DNA block', () => {
    const p = parseSolventBin(packSolventBin({ 0: oneFrame() }, { n_ions: 1 }))
    expect(p.frames.get(0).dna).toBeNull()
    expect(solventDnaFrames(p)).toBeNull()
  })
})

// ── Independent toggles ──────────────────────────────────────────────────────
//
// Water / Ions / Box are independent checkboxes, so any subset of the blocks can be
// absent. v1 always read a fixed 24-float cell and trusted a global ion count, so
// any combination with a gap desynchronised every later read and the parser bailed —
// Water-alone and Ions-alone silently drew nothing, and only all-three-on lined up.
describe('independent water / ions / box', () => {
  const combos = [
    ['water only', { w: true, i: false, b: false }],
    ['ions only', { w: false, i: true, b: false }],
    ['box only', { w: false, i: false, b: true }],
    ['water + ions', { w: true, i: true, b: false }],
    ['water + box', { w: true, i: false, b: true }],
    ['ions + box', { w: false, i: true, b: true }],
    ['all three', { w: true, i: true, b: true }],
  ]

  for (const [name, { w, i, b }] of combos) {
    it(`decodes ${name}`, () => {
      const buf = packSolventBin({
        0: {
          water: w ? f32(1, 2, 3, 4, 5, 6) : zeros(0),
          nWater: w ? 2 : 0,
          ions: i ? f32(7, 8, 9) : zeros(0),
          box: b ? zeros(24) : zeros(0),
        },
      }, { n_ions: i ? 1 : 0, has_box: b, n_ions_total: 9 })
      const p = parseSolventBin(buf)
      expect(p, `${name} failed to parse`).not.toBeNull()
      const f = p.frames.get(0)
      expect(f.nWater).toBe(w ? 2 : 0)
      expect(f.water.length).toBe(w ? 6 : 0)
      expect(f.ions.length).toBe(i ? 3 : 0)
      expect(f.box === null).toBe(!b)
      expect(p.hasBox).toBe(b)
      // The TOTAL is still reported with the species toggled off, so the panel can
      // say "N of M molecules" either way.
      expect(p.nIonsTotal).toBe(9)
    })
  }

  it('keeps water values intact when ions and box are both absent', () => {
    const buf = packSolventBin(
      { 0: { water: f32(11, 22, 33), nWater: 1, ions: zeros(0), box: zeros(0) } },
      { n_ions: 0, has_box: false })
    expect(Array.from(parseSolventBin(buf).frames.get(0).water)).toEqual([11, 22, 33])
  })
})

// The exact payload the backend produces for the combination the user reported
// broken (Water on, Ions off, Box off) — captured from the real packer at v2.
const PY_WATER_ONLY = 'VkxTTgIAAAABAAAAAAAAAN0AAAB7ImZyYW1lX2lkcyI6WzBdLCJhdG9taXN0aWMiOmZhbHNlLCJuX3dhdGVyc190b3RhbCI6NTAwLCJuX2lvbnMiOjAsInNoZWxsX25tIjowLjUsImNhcHBlZCI6dHJ1ZSwibl9pb25zX3RvdGFsIjo5LCJoYXNfYm94IjpmYWxzZSwic3BlY2llc190YWJsZSI6WyJOQSIsIkNMIiwiTUciLCJLIiwiQ0EiXSwiaW9uX3NwZWNpZXMiOltdLCJwZXJfZnJhbWVfbnciOlsyXSwibl9zZXJpYWxzIjowfQAAAAAAgD8AAABAAABAQAAAgEAAAKBAAADAQA=='

describe('the reported regression, against real backend bytes', () => {
  it('parses a water-only payload', () => {
    const p = parseSolventBin(fromBase64(PY_WATER_ONLY))
    expect(p).not.toBeNull()
    expect(p.frames.get(0).nWater).toBe(2)
    expect(Array.from(p.frames.get(0).water)).toEqual([1, 2, 3, 4, 5, 6])
    expect(p.frames.get(0).ions.length).toBe(0)
    expect(p.frames.get(0).box).toBeNull()
    expect(p.nIonsTotal).toBe(9)
  })

  it('rejects a v1 blob rather than misreading it', () => {
    const buf = fromBase64(PY_WATER_ONLY)
    new DataView(buf).setUint32(4, 1, true)      // pretend it is the old format
    expect(parseSolventBin(buf)).toBeNull()
  })
})
