/**
 * atomistic_bundle_bin.js — parse the columnar/binary atomistic display bundle from
 * GET /oxdna/jobs/{id}/atomistic-display-bundle-bin (see atomistic.pack_bundle_bin).
 *
 * The JSON bundle is ~124 MB for a VoltronCore-size design (330k atoms as verbose dicts
 * = 112 MB of it), and `JSON.parse` materialises 330k objects before a single pixel is
 * drawn.  That, not the GPU, was the multi-second stall on every oxDNA atomistic display.
 * This format ships the same information as typed arrays plus small interned string
 * tables — ~18 MB and no per-atom object.  Same idea as surface_bin.js.
 *
 * Two facts the encoder exploits (asserted backend-side, not assumed here):
 *   - atom serials are dense 0..n-1, so `serial` IS the row index and is never sent.
 *   - strand_id / helix_id / aux_helix_id / direction / element have tiny cardinality
 *     (hundreds at most across a whole origami), so each becomes an index + a table.
 *
 * Layout (little-endian):
 *   u32 magic(0x4E414231) · u32 version(1) · u32 nAtoms · u32 nBonds
 *   u32 headerLen · bytes[headerLen]  (UTF-8 JSON: string tables + descriptor scalars)
 *   ── atom columns, nAtoms each ──
 *   f32 x · f32 y · f32 z · i32 bpIndex · f32 auxT
 *   u16 strandIdx · u16 helixIdx · u16 auxHelixIdx · u8 elementIdx · u8 dirIdx
 *   ── bonds ──
 *   u32[nBonds*2] bond atom-index pairs
 *   ── stamp descriptor (see atomistic_stamp.js) ──
 *   u32 nNuc · u32 nNonrigid
 *   i32[nAtoms] atomNuc · f32[nAtoms*3] atomLocal · u32[nNonrigid] nonrigidSerials
 *   (atomNuc is SIGNED — expandStampFrames uses -1 for "this atom is non-rigid".)
 *
 * Columns are emitted widest-first so every typed-array view lands naturally aligned.
 * nAtoms == 0 ⇒ empty/not-ready → returns null.
 */
const _MAGIC = 0x4E414231   // "NAB1"
const _VERSION = 1

/**
 * Parse a binary atomistic bundle ArrayBuffer.
 * @returns {object|null} `{columnar:true, count, x, y, z, bpIndex, auxT, strandIdx,
 *   helixIdx, auxHelixIdx, elementIdx, dirIdx, <…>Table:string[], bonds:Uint32Array,
 *   topology_hash, n_nuc, n_atoms, atom_nuc, atom_local, nonrigid_serials, element_meta}`
 *   — or null if the buffer is absent, malformed, a version we don't speak, or empty.
 */
export function parseAtomisticBundleBin(buf) {
  if (!buf || buf.byteLength < 20) return null
  const dv = new DataView(buf)
  if (dv.getUint32(0, true) !== _MAGIC) return null
  if (dv.getUint32(4, true) !== _VERSION) return null    // unknown version → caller falls back to JSON
  const nAtoms = dv.getUint32(8, true)
  const nBonds = dv.getUint32(12, true)
  if (nAtoms === 0) return null
  const headerLen = dv.getUint32(16, true)
  let off = 20
  let header
  try {
    header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off, headerLen)))
  } catch { return null }
  off += headerLen
  // The variable-length JSON header leaves `off` arbitrary, so realign to 4 bytes before
  // taking any typed-array view (a misaligned Float32Array view throws).
  off += (4 - (off % 4)) % 4

  const f32 = (n) => { const v = new Float32Array(buf, off, n); off += n * 4; return v }
  const i32 = (n) => { const v = new Int32Array(buf, off, n);   off += n * 4; return v }
  const u32 = (n) => { const v = new Uint32Array(buf, off, n);  off += n * 4; return v }
  const u16 = (n) => { const v = new Uint16Array(buf, off, n);  off += n * 2; return v }
  const u8  = (n) => { const v = new Uint8Array(buf, off, n);   off += n;     return v }

  const x = f32(nAtoms), y = f32(nAtoms), z = f32(nAtoms)
  const bpIndex = i32(nAtoms)
  const auxT = f32(nAtoms)
  const strandIdx = u16(nAtoms), helixIdx = u16(nAtoms), auxHelixIdx = u16(nAtoms)
  const elementIdx = u8(nAtoms), dirIdx = u8(nAtoms)
  off += (4 - (off % 4)) % 4                       // the two u8 columns can leave us odd
  const bonds = u32(nBonds * 2)

  const nNuc = dv.getUint32(off, true); off += 4
  const nNonrigid = dv.getUint32(off, true); off += 4
  const atomNuc = i32(nAtoms)      // signed: -1 marks a non-rigid atom (expandStampFrames)
  const atomLocal = f32(nAtoms * 3)
  const nonrigidSerials = u32(nNonrigid)

  return {
    columnar: true,
    count: nAtoms,
    x, y, z, bpIndex, auxT,
    strandIdx, helixIdx, auxHelixIdx, elementIdx, dirIdx,
    strandTable: header.strand_table,
    helixTable: header.helix_table,
    auxHelixTable: header.aux_helix_table,
    elementTable: header.element_table,
    dirTable: header.dir_table,
    bonds,
    // Stamp-descriptor + metadata fields, same names the JSON bundle used so
    // atomistic_stamp.js and the renderer's element_meta path need no changes.
    element_meta: header.element_meta,
    topology_hash: header.topology_hash,
    n_nuc: nNuc,
    n_atoms: nAtoms,
    // NB `nuc_keys` is deliberately NOT carried: ~700 KB of JSON that nothing in
    // frontend/src ever reads (the stamp expansion is purely index-based).
    atom_nuc: atomNuc,
    atom_local: atomLocal,
    nonrigid_serials: nonrigidSerials,
  }
}
