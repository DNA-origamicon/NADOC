/**
 * surface_bin.js — parse the compact binary surface mesh from
 * POST /oxdna/jobs/{id}/display-surface-bin (see oxdna_health.pack_surface_bin).
 *
 * ~2× smaller than the JSON mesh AND no million-number JSON.parse — the typed arrays
 * are views straight onto the transferred ArrayBuffer.
 *
 * Layout (little-endian):
 *   u32 magic(0x4E535246) · u32 nVerts · u32 nFaces · u32 colorKind
 *   f32[nVerts*3] vertices · u32[nFaces*3] faces
 *   colorKind 1 → u8[nVerts*3] rgb(0-255) ; 2 → f32[nVerts] rmsf ; 0 → none
 *   u32 strandKind
 *   strandKind 1 → u32 tableLen · bytes[tableLen] (UTF-8 JSON strand-id list)
 *                 · u32[nVerts] vertex_strand_index ; 0 → none
 * The trailing strand block (present on the DESIGN surface) lets the renderer recolour by
 * strand/group/cluster without a re-fetch; the sim overlay omits it.
 * nVerts == 0 ⇒ not ready / empty → returns null.
 */
const _MAGIC = 0x4E535246

/** Parse a binary surface mesh ArrayBuffer → { vertices:Float32Array, faces:Uint32Array,
 *  vertex_colors?:Float32Array(0-1), vertex_rmsf?:Float32Array,
 *  vertex_strand_index_table?:string[], vertex_strand_index?:Uint32Array }, or null (bad/empty). */
export function parseSurfaceBin(buf) {
  if (!buf || buf.byteLength < 16) return null
  const dv = new DataView(buf)
  if (dv.getUint32(0, true) !== _MAGIC) return null
  const nv = dv.getUint32(4, true)
  const nf = dv.getUint32(8, true)
  const colorKind = dv.getUint32(12, true)
  if (nv === 0) return null            // not ready / empty
  let off = 16
  const vertices = new Float32Array(buf, off, nv * 3); off += nv * 3 * 4
  const faces = new Uint32Array(buf, off, nf * 3);     off += nf * 3 * 4
  const out = { vertices, faces }
  if (colorKind === 1) {                               // rgb u8 → 0-1 floats (renderer wants floats)
    const rgb = new Uint8Array(buf, off, nv * 3)
    const cf = new Float32Array(nv * 3)
    for (let i = 0; i < cf.length; i++) cf[i] = rgb[i] / 255
    out.vertex_colors = cf; off += nv * 3
  } else if (colorKind === 2) {                        // rmsf scalar (frontend maps via colormap)
    out.vertex_rmsf = new Float32Array(buf, off, nv); off += nv * 4
  }
  // Optional trailing index blocks, each `u32 kind · u32 tableLen · JSON · u32[nv]`.
  // Both are optional and self-describing, which is what lets the format grow without a
  // version field: a decoder that predates a block simply runs out of bytes and stops.
  const _indexBlock = (tableKey, indexKey) => {
    if (off + 4 > buf.byteLength) return
    const kind = dv.getUint32(off, true); off += 4
    if (kind !== 1) return
    const tableLen = dv.getUint32(off, true); off += 4
    out[tableKey] = JSON.parse(
      new TextDecoder().decode(new Uint8Array(buf, off, tableLen))); off += tableLen
    // The variable-length JSON table can leave `off` unaligned for a Uint32 view, so
    // copy the index block out via slice (its own buffer is 4-byte aligned at 0).
    out[indexKey] = new Uint32Array(buf.slice(off, off + nv * 4)); off += nv * 4
  }
  // Strand block — design surface → client-side recolour by strand/group.
  _indexBlock('vertex_strand_index_table', 'vertex_strand_index')
  // Nucleotide block (2026-08-01) — `helix:bp:dir` per vertex, so per-CLUSTER colouring
  // can resolve a strand that spans several clusters. The scaffold spans nearly all of
  // them, so a strand-keyed lookup paints it one colour (LESSONS D15). Shipped by the
  // DESIGN surface and, since 2026-08-02, by the SIMULATION-frame surfaces too.
  _indexBlock('vertex_nuc_index_table', 'vertex_nuc_index')
  return out
}
