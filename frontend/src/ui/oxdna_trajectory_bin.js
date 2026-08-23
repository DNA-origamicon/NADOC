const MAGIC = 'NADOTR1\0'

/** Decode the zero-copy Float32 trajectory transport.
 *  Layout: magic[8], headerBytes:u32le, UTF-8 JSON header, 4-byte pad, frame floats. */
export function decodeOxdnaTrajectoryBin(buf) {
  if (!(buf instanceof ArrayBuffer) || buf.byteLength < 12) return null
  const bytes = new Uint8Array(buf)
  for (let i = 0; i < MAGIC.length; i++) {
    if (bytes[i] !== MAGIC.charCodeAt(i)) return null
  }
  const headerBytes = new DataView(buf).getUint32(8, true)
  const headerEnd = 12 + headerBytes
  if (headerEnd > buf.byteLength) return null
  let header
  try {
    header = JSON.parse(new TextDecoder().decode(bytes.subarray(12, headerEnd)))
  } catch { return null }
  const dataOffset = (headerEnd + 3) & ~3
  const frameSize = Number(header.n_nucleotides) * 9
  const nFrames = Number(header.n_frames)
  if (!Number.isSafeInteger(frameSize) || !Number.isSafeInteger(nFrames)
      || frameSize < 0 || nFrames < 0
      || dataOffset + frameSize * nFrames * 4 !== buf.byteLength) return null
  const all = new Float32Array(buf, dataOffset, frameSize * nFrames)
  header.frames = Array.from({ length: nFrames }, (_, i) =>
    all.subarray(i * frameSize, (i + 1) * frameSize))
  return header
}
