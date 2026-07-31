/**
 * md_solvent_bin.js — parse the binary solvent / periodic-cell payload from
 * POST /md/jobs/{id}/frames-solvent-bin (see backend/core/md_solvent.pack_solvent_bin).
 *
 * Binary rather than JSON because whole-box atomistic water on a large job is
 * millions of numbers per frame: as JSON that is tens of MB plus a JSON.parse that
 * materialises a JS number array before anything can narrow it. Here every block is
 * a Float32Array VIEW straight onto the transferred ArrayBuffer — no copy, no parse.
 *
 * Layout (little-endian):
 *   u32 magic(0x4E534C56 "NSLV") · u32 version · u32 nFrames · u32 reserved
 *   u32 headerLen · bytes[headerLen] UTF-8 JSON · zero-pad to a 4-byte boundary
 *   per frame, in header.frame_ids order:
 *     f32[per_frame_nw[i] * (atomistic ? 9 : 3)]  water — O,H,H per molecule
 *     f32[n_ions * 3]                    ions, omitted entirely when n_ions === 0
 *     f32[24]                            cell corners, only when header.has_box
 *     f32[n_serials * 3]                 DNA, only when header.n_serials > 0
 *
 * The pad is what makes the float views legal: `new Float32Array(buf, offset)` throws
 * unless offset % 4 === 0, and the JSON header is an arbitrary number of bytes.
 *
 * EVERY block is optional, and the header counts describe what was actually
 * WRITTEN — the toggles are independent, so any of water / ions / box can be
 * absent. Totals ride separately (`n_waters_total`, `n_ions_total`). Reading a
 * fixed-size block that the packer skipped puts every later read at the wrong
 * offset; that bug made Water-alone and Ions-alone silently draw nothing.
 *
 * nFrames === 0 ⇒ nothing to draw (no trajectory yet) → returns null.
 *
 * NOTE the per-frame water count VARIES: a hydration shell is a different set of
 * molecules every frame because water diffuses. That is why the count is per-frame
 * (`header.per_frame_nw`) rather than global, and why the overlay must snap to a
 * frame rather than interpolate between two of them.
 */
const _MAGIC = 0x4E534C56
// Bumped when the block layout changed to make every block optional. A stale tab
// against a newer backend must fail closed (draw nothing) rather than misparse.
const _VERSION = 2

/**
 * @param {ArrayBuffer} buf
 * @returns {{
 *   frames: Map<number, {water: Float32Array, nWater: number, ions: Float32Array,
 *                        box: Float32Array, dna: Float32Array|null}>,
 *   frameIds: number[], atomistic: boolean, ionSpecies: Uint8Array,
 *   speciesTable: string[], nWatersTotal: number, nIons: number,
 *   shellNm: number|null, capped: boolean, nSerials: number,
 * } | null}
 */
export function parseSolventBin(buf) {
  if (!buf || buf.byteLength < 20) return null
  const dv = new DataView(buf)
  if (dv.getUint32(0, true) !== _MAGIC) return null
  if (dv.getUint32(4, true) !== _VERSION) return null
  const nFrames = dv.getUint32(8, true)
  const headerLen = dv.getUint32(16, true)
  if (20 + headerLen > buf.byteLength) return null

  let header
  try {
    header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, headerLen)))
  } catch { return null }
  if (!nFrames || !header?.frame_ids?.length) return null

  const atomistic = !!header.atomistic
  const perMol = atomistic ? 9 : 3
  const nIons = header.n_ions | 0
  const nSerials = header.n_serials | 0
  const hasBox = !!header.has_box
  const nw = header.per_frame_nw || []

  let off = 20 + headerLen + ((4 - (headerLen % 4)) % 4)
  const frames = new Map()
  for (let i = 0; i < header.frame_ids.length; i++) {
    const nWater = nw[i] | 0
    let n = nWater * perMol
    if (off + n * 4 > buf.byteLength) return null
    const water = new Float32Array(buf, off, n); off += n * 4
    n = nIons * 3
    if (off + n * 4 > buf.byteLength) return null
    const ions = new Float32Array(buf, off, n); off += n * 4
    let box = null
    if (hasBox) {
      if (off + 96 > buf.byteLength) return null
      box = new Float32Array(buf, off, 24); off += 96
    }
    let dna = null
    if (nSerials) {
      n = nSerials * 3
      if (off + n * 4 > buf.byteLength) return null
      dna = new Float32Array(buf, off, n); off += n * 4
    }
    frames.set(header.frame_ids[i] | 0, { water, nWater, ions, box, dna })
  }

  return {
    frames,
    frameIds: header.frame_ids.map((v) => v | 0),
    atomistic,
    ionSpecies: Uint8Array.from(header.ion_species || []),
    speciesTable: header.species_table || [],
    nWatersTotal: header.n_waters_total | 0,
    nIonsTotal: (header.n_ions_total ?? header.n_ions) | 0,
    nIons,
    hasBox,
    shellNm: header.shell_nm ?? null,
    capped: !!header.capped,
    nSerials,
  }
}

/**
 * The DNA half of an `include_dna` payload, in the `{ "<idx>": Float32Array }` shape
 * the oxDNA display controller already consumes for positions-only heavy frames.
 * Returns null when the payload carries no DNA block.
 */
export function solventDnaFrames(parsed) {
  if (!parsed?.nSerials) return null
  const out = {}
  for (const [id, f] of parsed.frames) if (f.dna) out[String(id)] = f.dna
  return out
}
