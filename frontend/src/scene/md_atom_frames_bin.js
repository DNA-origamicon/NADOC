/** Exact aligned coordinates; serial numbering is shared with the static topology. */
export function parseMdAtomFrames(buffer, { compact = false } = {}) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 16) throw new Error('Invalid MD atom frames')
  const h = new DataView(buffer)
  const version = h.getUint32(4, true)
  if (h.getUint32(0, true) !== 0x4D444146 || ![1,2].includes(version)) throw new Error('Unsupported MD atom frames')
  const n = h.getUint32(8, true), serials = h.getUint32(12, true)
  const count = version === 2 ? h.getUint32(16, true) : serials
  const map = version === 2 ? new Uint32Array(buffer, 24, count) : null
  if (map?.some(s => s >= serials)) throw new Error('Invalid MD atom serial')
  const start = version === 2 ? Math.ceil((24 + count * 4) / 8) * 8 : 16
  const size = 8 + count * 24
  if (start + n * size !== buffer.byteLength) throw new Error('Truncated MD atom frames')
  const frames = {}
  for (let i = 0, offset = start; i < n; i++, offset += size) {
    const dense = new Float64Array(buffer, offset + 8, count * 3)
    let xyz = dense
    if (map && compact) {
      xyz = { dense, serialMap: map, length: serials * 3, byteLength: dense.byteLength }
    } else if (map) {
      xyz = new Float64Array(serials * 3)
      for (let row = 0; row < count; row++) {
        const src=row*3, dst=map[row]*3
        xyz[dst]=dense[src]; xyz[dst+1]=dense[src+1]; xyz[dst+2]=dense[src+2]
      }
    }
    frames[String(h.getUint32(offset, true))] = xyz
  }
  return frames
}

/** Static columnar topology, retaining sparse serials, atom names and copy keys. */
export function parseMdAtomModel(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 16) throw new Error('Invalid MD atom model')
  const h = new DataView(buffer)
  if (h.getUint32(0,true) !== 0x4D44414D || h.getUint32(4,true) !== 1) throw new Error('Unsupported MD atom model')
  const length = h.getUint32(8,true)
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,16,length)))
  const base = 16 + Math.ceil(length / 8) * 8
  const result = { ...header, columnar:true, n_atoms:header.count, bonds_available:true }
  const types = { '<f8':Float64Array, '<u4':Uint32Array, '<i4':Int32Array }
  for (const c of header.columns) {
    const Type=types[c.dtype]
    if (!Type) throw new Error('Unsupported MD atom column')
    result[c.name] = new Type(buffer,base+c.offset,c.count)
  }
  result.auxHelixTable=['']; result.auxHelixIdx=new Uint32Array(header.count)
  result.auxT=new Float32Array(header.count)
  return result
}

/** Expand only the displayed frame, reusing a scratch buffer. Cached frames stay
 * dense float64; removing unused serial slots loses no coordinates or precision. */
export function expandMdAtomFrame(frame, scratch) {
  if (!frame?.dense) return frame
  const out = scratch?.length === frame.length ? scratch : new Float64Array(frame.length)
  out.fill(0)
  for (let row = 0; row < frame.serialMap.length; row++) {
    const src = row * 3, dst = frame.serialMap[row] * 3
    out[dst] = frame.dense[src]; out[dst+1] = frame.dense[src+1]; out[dst+2] = frame.dense[src+2]
  }
  return out
}
