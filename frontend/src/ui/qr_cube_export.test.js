import { expect, it, vi } from 'vitest'
import { unzipSync, strFromU8 } from 'three/addons/libs/fflate.module.js'
import { exportQrCube } from './qr_cube_export.js'
import { downloadHref } from './metric_export_modal.js'

vi.mock('./metric_export_modal.js', () => ({ downloadHref: vi.fn() }))

it('downloads a ZIP with six valid STLs and the tapered socket assembly instructions', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  let blob
  vi.stubGlobal('URL', {
    createObjectURL: vi.fn(value => { blob = value; return 'blob:qr-cube' }),
    revokeObjectURL: vi.fn(),
  })
  try {
    exportQrCube()
    expect(downloadHref).toHaveBeenCalledWith('nadoc-qr-cube-150mm-stl.zip', 'blob:qr-cube')
    expect(blob.type).toBe('application/zip')
    const buffer = await new Promise(resolve => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.readAsArrayBuffer(blob)
    })
    const files = unzipSync(new Uint8Array(buffer))
    const stls = Object.entries(files).filter(([name]) => name.endsWith('.stl'))
    expect(stls).toHaveLength(6)
    expect(files['face-5-bottom.stl']).toBeUndefined()
    for (const [, bytes] of stls) {
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
      expect(bytes.length).toBe(84 + 50 * view.getUint32(80, true))
      expect(view.getUint32(80, true)).toBeGreaterThan(0)
    }
    const assembly = JSON.parse(strFromU8(files['assembly.json']))
    expect(assembly.faces.map(face => face.face)).toEqual([0, 1, 2, 3, 4])
    expect(assembly.supportSocket).toMatchObject({ bottomDiameter: 90, topDiameter: 45, topClearance: 15, depth: 138 })
    expect(strFromU8(files['README.txt'])).toContain('Leave the bottom uncovered')
    vi.runAllTimers()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:qr-cube')
  } finally {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  }
})
