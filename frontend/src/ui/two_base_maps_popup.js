import { buildChartSpec, drawChart } from './metric_graph.js'

export const DEFAULT_TWO_BASE_MAPS = [0, 1, 12, 13] // xy, xz; rotation xy, rotation xz
export const TWO_BASE_LABELS = ['Displacement x (nm)', 'Displacement y (nm)', 'Displacement z (nm)',
  'Rotation-vector x (°)', 'Rotation-vector y (°)', 'Rotation-vector z (°)']

export function twoBasePlots(result) {
  const plots = []
  for (let x = 0; x < 6; x++) for (let y = x + 1; y < 6; y++) {
    plots.push({ x, y, xLabel: TWO_BASE_LABELS[x], yLabel: TWO_BASE_LABELS[y],
      points: result.rows.map(row => [row[x], row[y]]) })
  }
  return plots
}

export function drawTwoBasePlot(canvas, plot) {
  const spec = buildChartSpec({ width: 560, height: 340,
    title: `${plot.yLabel.replace(/ \(.+\)/, '')} vs ${plot.xLabel.replace(/ \(.+\)/, '')}`,
    xLabel: plot.xLabel, yLabel: plot.yLabel,
    series: [{ color: '#58a6ff', points: plot.points }] })
  drawChart(canvas, { ...spec, series: [] })
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#58a6ff'; ctx.globalAlpha = .45
  for (const [x,y] of spec.series[0]?.pts || []) ctx.fillRect(x-1.25, y-1.25, 2.5, 2.5)
  ctx.globalAlpha = 1
  return spec
}

export function openTwoBaseMaps(result, { maps = [...DEFAULT_TWO_BASE_MAPS] } = {}) {
  document.getElementById('two-base-maps-popup')?.remove()
  const dialog = document.createElement('dialog')
  dialog.id = 'two-base-maps-popup'
  dialog.setAttribute('aria-label', '2-base maps')
  dialog.style.cssText = 'width:min(1200px,96vw);max-height:92vh;overflow:auto;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:8px;padding:16px;font:14px var(--font-ui,sans-serif)'
  const header = document.createElement('div')
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'
  const title = document.createElement('strong')
  title.textContent = '2-base maps'
  title.title = `${result.note}\nBase 1: ${result.bases[0]}\nBase 2: ${result.bases[1]}\n${result.frames} production frames. Hover over a point for its values. Export uses the four selected maps.`
  const close = document.createElement('button')
  close.textContent = 'Close'; close.onclick = () => dialog.close()
  header.append(title, close)
  const grid = document.createElement('div')
  grid.style.cssText = 'display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px'
  dialog.append(header, grid)
  dialog.addEventListener('close', () => dialog.remove(), { once: true })
  document.body.append(dialog)
  const plots = twoBasePlots(result)
  for (let slot = 0; slot < 4; slot++) {
    const panel = document.createElement('div')
    const label = document.createElement('label')
    label.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px'
    label.append(`Graph ${slot+1}`)
    const select = document.createElement('select')
    select.setAttribute('aria-label', `Graph ${slot+1} map`)
    select.style.cssText = 'flex:1;min-width:0;font:inherit;padding:5px;background:#161b22;color:#e6edf3;border:1px solid #484f58;border-radius:4px'
    plots.forEach((plot, i) => {
      const option = document.createElement('option')
      option.value = String(i); option.textContent = `${plot.yLabel} vs ${plot.xLabel}`
      select.append(option)
    })
    select.value = String(maps[slot])
    label.append(select)
    const canvas = document.createElement('canvas')
    canvas.style.cssText = 'display:block;width:100%;height:auto'
    canvas.setAttribute('role', 'img')
    panel.append(label,canvas); grid.append(panel)
    let plot, spec
    const paint = () => {
      maps[slot] = Number(select.value)
      plot = plots[maps[slot]]
      canvas.setAttribute('aria-label', `${plot.yLabel} versus ${plot.xLabel}`)
      canvas.title = `${plot.yLabel} versus ${plot.xLabel}. ${result.note}`
      spec = drawTwoBasePlot(canvas,plot)
    }
    select.addEventListener('change', paint); paint()
    canvas.addEventListener('mousemove', event => {
      const rect = canvas.getBoundingClientRect()
      const x = (event.clientX-rect.left)*spec.width/rect.width, y = (event.clientY-rect.top)*spec.height/rect.height
      let nearest = -1, distance = 100
      spec.series[0]?.pts.forEach(([px,py],i) => {
        const d = (px-x)**2+(py-y)**2
        if (d < distance) { distance = d; nearest = i }
      })
      canvas.title = nearest < 0 ? `${plot.yLabel} versus ${plot.xLabel}. ${result.note}`
        : `Frame ${nearest+1}: ${plot.xLabel} = ${plot.points[nearest][0].toFixed(4)}, ${plot.yLabel} = ${plot.points[nearest][1].toFixed(4)}`
    })
  }
  dialog.showModal()
  return dialog
}
