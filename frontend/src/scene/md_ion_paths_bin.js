/** Shared ion coordinates stay Float32 views; crossing windows only carry offsets. */
export function decodeMdIonPaths(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 12) throw new Error('Incomplete ion-path response')
  const view = new DataView(buffer)
  if (view.getUint32(0, true) !== 0x4e495054 || view.getUint32(4, true) !== 1) throw new Error('Unsupported ion-path response')
  const length = view.getUint32(8, true), start = 12 + Math.ceil(length / 4) * 4
  if (start > buffer.byteLength || (buffer.byteLength - start) % 4) throw new Error('Incomplete ion-path coordinates')
  const data = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 12, length)))
  if (!Array.isArray(data?.paths) || !Array.isArray(data.tracks) || !data.pore) throw new Error('Invalid ion-path metadata')
  const coords = new Float32Array(buffer, start)
  data.tracks = data.tracks.map(({ offset, count }) => {
    if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(count) || offset < 0 || count < 0 || offset + count * 3 > coords.length) throw new Error('Incomplete ion track')
    return coords.subarray(offset, offset + count * 3)
  })
  for (const path of data.paths) {
    const track = data.tracks[path.track]
    if (!track || !Number.isSafeInteger(path.point_start) || !Number.isSafeInteger(path.point_count)
      || path.point_start < 0 || path.point_count < 1 || (path.point_start + path.point_count) * 3 > track.length
      || !Array.isArray(path.offset) || path.offset.length !== 3 || !path.offset.every(Number.isFinite)) throw new Error('Invalid ion-path window')
  }
  return data
}
