import { describe, it, expect } from 'vitest'
import { parseSurfaceBin } from './surface_bin.js'

const MAGIC = 0x4E535246

// Build a binary blob the same way the backend pack_surface_bin does. `strandTable` +
// `strandIndex` append the optional strand block (design-surface recolour); omitting both
// mimics a minimal/overlay blob with no trailing block.
function pack(nv, nf, verts, faces, { rgb = null, rmsf = null,
                                      strandTable = null, strandIndex = null,
                                      nucTable = null, nucIndex = null } = {}) {
  const colorKind = rgb ? 1 : rmsf ? 2 : 0
  const colorBytes = rgb ? rgb.length : rmsf ? rmsf.length * 4 : 0
  // Each optional trailing block is `u32 kind · u32 tableLen · JSON · u32[nv]`, or a
  // bare `u32 0` marker. Mirrors backend pack_surface_bin._index_block.
  const enc = (table, index) => (table && index)
    ? { bytes: new TextEncoder().encode(JSON.stringify(table)), index }
    : null
  const blocks = [enc(strandTable, strandIndex), enc(nucTable, nucIndex)]
  // A block only writes its absent marker if a LATER block needs to be reachable —
  // matching the backend, which always writes both markers once nv > 0.
  const lastUsed = blocks.reduce((acc, b, i) => (b ? i : acc), -1)
  let trailing = 0
  for (let i = 0; i <= lastUsed; i++) {
    trailing += blocks[i] ? 4 + 4 + blocks[i].bytes.length + blocks[i].index.length * 4 : 4
  }
  const buf = new ArrayBuffer(16 + nv * 3 * 4 + nf * 3 * 4 + colorBytes + trailing)
  const dv = new DataView(buf)
  dv.setUint32(0, MAGIC, true); dv.setUint32(4, nv, true)
  dv.setUint32(8, nf, true);    dv.setUint32(12, colorKind, true)
  let off = 16
  new Float32Array(buf, off, nv * 3).set(verts); off += nv * 3 * 4
  new Uint32Array(buf, off, nf * 3).set(faces);  off += nf * 3 * 4
  if (rgb)  { new Uint8Array(buf, off, rgb.length).set(rgb); off += rgb.length }
  if (rmsf) { new Float32Array(buf, off, rmsf.length).set(rmsf); off += rmsf.length * 4 }
  for (let i = 0; i <= lastUsed; i++) {
    const b = blocks[i]
    if (!b) { dv.setUint32(off, 0, true); off += 4; continue }
    dv.setUint32(off, 1, true); off += 4
    dv.setUint32(off, b.bytes.length, true); off += 4
    new Uint8Array(buf, off, b.bytes.length).set(b.bytes); off += b.bytes.length
    for (let k = 0; k < b.index.length; k++) { dv.setUint32(off, b.index[k], true); off += 4 }
  }
  return buf
}

describe('parseSurfaceBin', () => {
  it('parses vertices, faces, and rgb colours (u8 → 0-1 floats)', () => {
    const buf = pack(3, 1, [0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2],
                     { rgb: [255, 0, 0, 0, 255, 0, 0, 0, 255] })
    const m = parseSurfaceBin(buf)
    expect(m.vertices).toBeInstanceOf(Float32Array)
    expect(Array.from(m.vertices)).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0])
    expect(m.faces).toBeInstanceOf(Uint32Array)
    expect(Array.from(m.faces)).toEqual([0, 1, 2])
    expect(m.vertex_colors).toBeInstanceOf(Float32Array)
    expect(Array.from(m.vertex_colors)).toEqual([1, 0, 0, 0, 1, 0, 0, 0, 1])
    expect(m.vertex_rmsf).toBeUndefined()
  })

  it('parses the rmsf scalar variant', () => {
    const buf = pack(2, 0, [0, 0, 0, 1, 1, 1], [], { rmsf: [0.25, 0.75] })
    const m = parseSurfaceBin(buf)
    expect(Array.from(m.vertex_rmsf)).toEqual([0.25, 0.75])
    expect(m.vertex_colors).toBeUndefined()
  })

  it('parses the trailing strand-index block (design-surface recolour)', () => {
    // Odd-length rgb (9 bytes) + an odd-length JSON table force the vertex_strand_index
    // Uint32 view to a non-4-aligned offset — exercises the alignment-safe slice() path.
    const buf = pack(3, 1, [0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2],
                     { rgb: [255, 0, 0, 0, 255, 0, 0, 0, 255],
                       strandTable: ['a'], strandIndex: [0, 0, 0] })
    const m = parseSurfaceBin(buf)
    expect(m.vertex_strand_index_table).toEqual(['a'])
    expect(m.vertex_strand_index).toBeInstanceOf(Uint32Array)
    expect(Array.from(m.vertex_strand_index)).toEqual([0, 0, 0])
    expect(Array.from(m.vertex_colors)).toEqual([1, 0, 0, 0, 1, 0, 0, 0, 1])
  })

  it('parses a strand block with no colour block (colorKind 0)', () => {
    const buf = pack(2, 0, [0, 0, 0, 1, 1, 1], [],
                     { strandTable: ['scaf', 'stap'], strandIndex: [1, 0] })
    const m = parseSurfaceBin(buf)
    expect(m.vertex_strand_index_table).toEqual(['scaf', 'stap'])
    expect(Array.from(m.vertex_strand_index)).toEqual([1, 0])
    expect(m.vertex_colors).toBeUndefined()
  })

  it('backward-compatible: a blob with no trailing strand block omits the fields', () => {
    const buf = pack(3, 1, [0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2],
                     { rgb: [255, 0, 0, 0, 255, 0, 0, 0, 255] })
    const m = parseSurfaceBin(buf)
    expect(m.vertex_strand_index_table).toBeUndefined()
    expect(m.vertex_strand_index).toBeUndefined()
  })

  it('returns null for an empty (not-ready) mesh (nVerts=0)', () => {
    const buf = pack(0, 0, [], [])
    expect(parseSurfaceBin(buf)).toBeNull()
  })

  it('returns null for a bad magic / too-small buffer', () => {
    expect(parseSurfaceBin(new ArrayBuffer(8))).toBeNull()
    const bad = new ArrayBuffer(16); new DataView(bad).setUint32(0, 0xDEADBEEF, true)
    expect(parseSurfaceBin(bad)).toBeNull()
    expect(parseSurfaceBin(null)).toBeNull()
  })
})

// ── Per-vertex nucleotide block ───────────────────────────────────────────────
// Added 2026-08-01 so per-CLUSTER surface colouring can resolve a strand that spans
// several clusters. The scaffold spans nearly all of them, so a strand-keyed lookup
// paints the whole scaffold one colour (LESSONS D15).

describe('parseSurfaceBin — nucleotide block', () => {
  const V = [0, 0, 0, 1, 0, 0, 0, 1, 0]
  const F = [0, 1, 2]

  it('parses the nucleotide table alongside the strand table', () => {
    const buf = pack(3, 1, V, F, {
      strandTable: ['scaf'], strandIndex: [0, 0, 0],
      nucTable: ['h0:5:FORWARD', 'h1:9:REVERSE'], nucIndex: [0, 1, 0],
    })
    const out = parseSurfaceBin(buf)
    expect(out.vertex_strand_index_table).toEqual(['scaf'])
    expect(out.vertex_nuc_index_table).toEqual(['h0:5:FORWARD', 'h1:9:REVERSE'])
    expect(Array.from(out.vertex_nuc_index)).toEqual([0, 1, 0])
  })

  it('survives an unaligned offset from the second JSON table', () => {
    // Two variable-length JSON tables in a row make the alignment hazard worse than with
    // one; both index blocks must be copied out via slice, not viewed in place.
    const buf = pack(3, 1, V, F, {
      rgb: new Uint8Array(9).fill(7),
      strandTable: ['a'], strandIndex: [0, 0, 0],
      nucTable: ['h:1:FORWARD'], nucIndex: [0, 0, 0],
    })
    const out = parseSurfaceBin(buf)
    expect(Array.from(out.vertex_strand_index)).toEqual([0, 0, 0])
    expect(Array.from(out.vertex_nuc_index)).toEqual([0, 0, 0])
  })

  it('backward-compatible: a blob with only the strand block omits the nuc fields', () => {
    // The oxDNA frame-surface overlay and any pre-2026-08-01 producer.
    const buf = pack(3, 1, V, F, { strandTable: ['scaf'], strandIndex: [0, 0, 0] })
    const out = parseSurfaceBin(buf)
    expect(out.vertex_strand_index_table).toEqual(['scaf'])
    expect(out.vertex_nuc_index_table).toBeUndefined()
    expect(out.vertex_nuc_index).toBeUndefined()
  })

  it('backward-compatible: a blob with NO trailing blocks still parses', () => {
    const out = parseSurfaceBin(pack(3, 1, V, F))
    expect(out.vertex_strand_index_table).toBeUndefined()
    expect(out.vertex_nuc_index_table).toBeUndefined()
    expect(Array.from(out.vertices)).toEqual(V)
  })
})
