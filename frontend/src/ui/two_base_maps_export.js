import { openMetricExportModal, downloadText, downloadHref } from './metric_export_modal.js'
import { twoBasePlots, drawTwoBasePlot, DEFAULT_TWO_BASE_MAPS } from './two_base_maps_popup.js'

export function twoBaseCSV(result) {
  const quote = value => '"'+String(value).replaceAll('"','""')+'"'
  return ['frame,base_1,base_2,x_nm,y_nm,z_nm,rotation_vector_x_deg,rotation_vector_y_deg,rotation_vector_z_deg',
    ...result.rows.map((row,i) => [i+1,...result.bases,...row].map(quote).join(','))].join('\n')
}

export async function exportTwoBaseMaps(result, jobId, maps = DEFAULT_TWO_BASE_MAPS) {
  const choice = await openMetricExportModal()
  if (!choice) return
  const name = `two_base_maps_${jobId}`
  if (choice.data) downloadText(name+'.csv',twoBaseCSV(result))
  if (choice.png) {
    const plots = twoBasePlots(result)
    const image = document.createElement('canvas')
    image.width = 1120; image.height = 720
    const ctx = image.getContext('2d')
    ctx.fillStyle = '#0d1117'; ctx.fillRect(0,0,image.width,image.height)
    ctx.fillStyle = '#e6edf3'; ctx.font = '16px sans-serif'
    ctx.fillText(`2-base maps · ${result.bases[0]} → ${result.bases[1]} · ${result.frames} frames`,16,26)
    maps.forEach((index,slot) => {
      const canvas = document.createElement('canvas')
      drawTwoBasePlot(canvas,plots[index])
      ctx.drawImage(canvas,(slot%2)*560,40+Math.floor(slot/2)*340)
    })
    downloadHref(name+'.png',image.toDataURL('image/png'))
  }
}
