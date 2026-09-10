import { it, expect } from 'vitest'
import { decodeMdIonPaths } from './md_ion_paths_bin.js'

export function fixtureBuffer() {
  const metadata = { paths: [{ track: 0, point_start: 0, point_count: 2, offset: [0, 0, 0] }],
    tracks: [{ offset: 0, count: 2 }], pore: { radius_nm: 1 } }
  const json = new TextEncoder().encode(JSON.stringify(metadata))
  const start = 12 + Math.ceil(json.length / 4) * 4
  const buffer = new ArrayBuffer(start + 24), view = new DataView(buffer)
  view.setUint32(0, 0x4e495054, true); view.setUint32(4, 1, true); view.setUint32(8, json.length, true)
  new Uint8Array(buffer, 12, json.length).set(json)
  new Float32Array(buffer, start).set([0, -1, 0, 0, 1, 0])
  return buffer
}
it('uses shared float32 views and validates truncated responses', () => {
  const buffer = fixtureBuffer(), data = decodeMdIonPaths(buffer)
  expect(data.tracks[0].buffer).toBe(buffer)
  expect(Array.from(data.tracks[0])).toEqual([0, -1, 0, 0, 1, 0])
  expect(() => decodeMdIonPaths(buffer.slice(0, -4))).toThrow('Incomplete ion track')
  expect(() => decodeMdIonPaths(null)).toThrow('Incomplete ion-path response')
})
