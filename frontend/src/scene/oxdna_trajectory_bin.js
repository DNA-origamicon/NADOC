/**
 * Decode GET /oxdna/jobs/{id}/trajectory-bin.
 *
 * The legacy JSON trajectory expands every coordinate into a JavaScript number during
 * JSON.parse.  This format keeps the same metadata but exposes each frame as a zero-copy
 * Float32Array view over one transferred ArrayBuffer.
 *
 * Layout (little-endian; mirrored by oxdna_health.pack_composite_trajectory_bin):
 *   u32 magic("NTRJ") · u32 version(1) · u32 nFrames · u32 nKeys · u32 headerLen
 *   bytes[headerLen] JSON {keys, stages, markers}
 *   padding to 4-byte alignment
 *   f32[nFrames * nKeys * 6] frame coordinates
 */
const _MAGIC = 0x4E54524A
const _VERSION = 1

export function parseOxdnaTrajectoryBin(buf) {
  if (!buf || buf.byteLength < 20) return null
  const dv = new DataView(buf)
  if (dv.getUint32(0, true) !== _MAGIC || dv.getUint32(4, true) !== _VERSION) return null
  const nFrames = dv.getUint32(8, true)
  const nKeys = dv.getUint32(12, true)
  const headerLen = dv.getUint32(16, true)
  let off = 20
  if (off + headerLen > buf.byteLength) return null
  let header
  try {
    header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, off, headerLen)))
  } catch { return null }
  off += headerLen
  off += (4 - (off % 4)) % 4
  const frameSize = nKeys * 6
  const byteLength = nFrames * frameSize * 4
  if (off + byteLength !== buf.byteLength) return null
  if (!Array.isArray(header.keys) || header.keys.length !== nKeys || nFrames === 0) return null
  const all = new Float32Array(buf, off, nFrames * frameSize)
  const frames = Array.from({ length: nFrames }, (_, i) =>
    all.subarray(i * frameSize, (i + 1) * frameSize))
  return {
    ready: true,
    n_frames: nFrames,
    n_nucleotides: nKeys,
    keys: header.keys,
    frames,
    stages: Array.isArray(header.stages) ? header.stages : [],
    markers: Array.isArray(header.markers) ? header.markers : [],
    binary: true,
  }
}
