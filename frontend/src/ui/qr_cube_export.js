import { zipSync, strToU8 } from 'three/addons/libs/fflate.module.js'
import { qrCubeFiles } from '../shared/qr_cube.js'
import { downloadHref } from './metric_export_modal.js'

export function qrCubeArchive() {
  const files = Object.fromEntries(Object.entries(qrCubeFiles()).map(([name, content]) =>
    [name, typeof content === 'string' ? new Uint8Array(strToU8(content)) : content]))
  return zipSync(files, { level: 1 })
}

export function exportQrCube() {
  const url = URL.createObjectURL(new Blob([qrCubeArchive()], { type: 'application/zip' }))
  try {
    downloadHref('nadoc-qr-cube-150mm-stl.zip', url)
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
